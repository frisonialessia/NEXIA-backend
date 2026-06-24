# ──────────────────────────────────────────────────────────────────────────
# MOTOR DE LA PLANTA VIRTUAL  ·  espejo de lib/data/simulated.ts + fleetStore.ts
# Mantiene el estado vivo de la flota en memoria, lo avanza un "tick" cada 2 s y
# expone el snapshot y los comandos en el formato del contrato (DTOs camelCase).
# El día que existan sensores reales, se reemplaza este motor por la ingesta;
# el contrato y el WebSocket no cambian.
# ──────────────────────────────────────────────────────────────────────────

import math
import os
import random
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .constants import (
    AHORRO_POR_PARADA,
    CALIBRACION_TICKS,
    FLOTA,
    MAX_EVENTOS,
    METRICA_PIVOTE,
    TICKS_CALENTAMIENTO,
    UMBRAL_CRITICO,
    VENTANA_HIST,
    tipo_de,
)
from .engine import causa_principal, es_alta, probabilidad_fallo, transicion


def _ahora_ms() -> int:
    return int(time.time() * 1000)


def _metricas_limpias(metricas: Optional[dict]) -> dict[str, float]:
    """Normaliza un dict de magnitudes EXTRA: descarta el pivote 'vib' (viaja
    aparte) y los valores no numéricos, y coacciona el resto a float. NO filtra
    por vocabulario: acepta CUALQUIER magnitud numérica que mande el PLC
    (passthrough). El vocabulario canónico (app/constants.py) solo aporta
    unidades/labels para las magnitudes conocidas; no limita lo que entra."""
    if not metricas:
        return {}
    limpio: dict[str, float] = {}
    for clave, valor in metricas.items():
        if clave == METRICA_PIVOTE:
            continue  # 'vib' nunca va en metricas (es el campo principal)
        try:
            limpio[clave] = float(valor)
        except (TypeError, ValueError):
            continue
    return limpio


@dataclass
class Maquina:
    id: str
    sensor: str
    sector: str
    base: float
    esc: str
    tipo: str
    umbral: float
    estado: str = "STABLE"
    c_sube: int = 0
    c_baja: int = 0
    hist: list = field(default_factory=list)  # [{"t","v","exp"[, "m": {...}]}]
    expected: float = 0.0
    prob: float = 0.05
    tick: int = 0
    ritmo_dia: float = 0.0
    horas_op: float = 0.0
    calib: int = 0
    metricas: dict = field(default_factory=dict)  # último valor por magnitud extra

    def to_dto(self) -> dict:
        dto = {
            "id": self.id,
            "sensor": self.sensor,
            "sector": self.sector,
            "tipo": self.tipo,
            "base": self.base,
            "umbral": self.umbral,
            "estado": self.estado,
            "prob": self.prob,
            "expected": self.expected,
            "ritmoDia": self.ritmo_dia,
            "horasOp": int(self.horas_op),
            "hist": self.hist,
            "esc": self.esc,
            "calib": self.calib,
        }
        # ADITIVO: solo se incluye `metricas` cuando la máquina tiene magnitudes
        # extra. En modo simulado por defecto queda fuera → payload idéntico al
        # de antes de multi-variable (el frontend no nota diferencia).
        if self.metricas:
            dto["metricas"] = dict(self.metricas)
        return dto


def crear_maquina(seed: dict) -> Maquina:
    tipo = seed.get("tipo") or tipo_de(seed["id"])
    esc = seed.get("esc", "sano")
    return Maquina(
        id=seed["id"],
        sensor=seed["sensor"],
        sector=seed["sector"],
        base=float(seed["base"]),
        esc=esc,
        tipo=tipo,
        umbral=float(seed.get("umbral") or UMBRAL_CRITICO),
        expected=float(seed["base"]),
        ritmo_dia=0.7 if esc == "degradando" else 0.0,
        horas_op=float(int(2000 + random.random() * 3000)),
        calib=0,
    )


def _avanzar_baseline(m: Maquina) -> None:
    """Avanza el reloj de la máquina y recalcula su baseline esperada (componente
    cíclica diaria). Común a la simulación y a la ingesta real."""
    m.tick += 1
    m.horas_op += 0.01
    dt = datetime.now()
    hora = dt.hour + dt.minute / 60
    ritmo = 0.3 * math.sin(((hora - 9) / 24) * 2 * math.pi)
    m.expected = round(m.base + ritmo, 3)


def _vibracion_simulada(m: Maquina) -> float:
    """Genera la vibración SIMULADA según el escenario. En ingesta real, este
    valor llega del sensor y esta función no se usa."""
    if m.esc == "sano":
        return m.expected + (random.random() - 0.5) * 0.4
    if m.esc == "degradando":
        return m.expected + min(m.tick * 0.05, 4.5) + (random.random() - 0.5) * 0.5
    return m.expected + 4 + random.random() * 2  # critico


def _evaluar(m: Maquina, v: float, now_ms: int, metricas: Optional[dict] = None) -> Optional[dict]:
    """EL MOTOR. Dada una lectura de vibración `v` (venga de donde venga) y, de
    forma OPCIONAL, otras magnitudes (`metricas`: temperatura, presión, rpm,
    corriente…), aplica calibración, probabilidad de fallo y la FSM, y devuelve
    una alerta si la máquina acaba de entrar en crítico.

    La detección PIVOTA solo sobre `v`: las magnitudes extra son telemetría
    ADITIVA (se almacenan y se exponen, pero no cambian la FSM ni la
    probabilidad). NO sabe si el dato es real o simulado: esta es la frontera
    entre la fuente de datos y la lógica de cómputo."""
    v = max(0.0, round(v, 3))

    # Telemetría multi-variable: fusiona (carry-forward) las magnitudes extra
    # conocidas en el estado de la máquina. No interviene en la detección; solo
    # enriquece el estado y cada punto del historial.
    extra = _metricas_limpias(metricas)
    if extra:
        m.metricas.update(extra)

    def _punto() -> dict:
        # Punto de historial. Conserva exactamente {"t","v","exp"} (lo que el
        # frontend ya consume) y añade "m" SOLO si hay magnitudes extra.
        p = {"t": now_ms, "v": v, "exp": m.expected}
        if m.metricas:
            p["m"] = dict(m.metricas)
        return p

    # ── Calibración: aprendiendo baseline (sin juzgar, sin alertas) ──────────
    if m.calib > 0:
        m.calib -= 1
        m.prob = 0.05
        m.estado = "STABLE"
        m.c_sube = 0
        m.c_baja = 0
        m.hist.append(_punto())
        if len(m.hist) > VENTANA_HIST:
            m.hist.pop(0)
        return None

    m.prob = probabilidad_fallo(v, m.expected)
    alto = es_alta(m.prob)
    prev = m.estado
    m.estado, m.c_sube, m.c_baja = transicion(m.estado, m.c_sube, m.c_baja, alto)

    alerta = None
    if m.estado == "CRITICAL_ALERT" and prev != "CRITICAL_ALERT":
        alerta = {
            "id": f"al-{m.id}-{now_ms}",
            "maquina": m.id,
            "sensor": m.sensor,
            "tipo": m.tipo,
            "causa": "Vibración fuera del rango esperado: posible " + causa_principal(m.tipo).lower(),
            "prob": m.prob,
            "ts": now_ms,
            "vib": v,
            "exp": m.expected,
            "umbral": m.umbral,
        }
        if m.metricas:
            alerta["metricas"] = dict(m.metricas)

    m.hist.append(_punto())
    if len(m.hist) > VENTANA_HIST:
        m.hist.pop(0)

    return alerta


def _sim_multivar_activo() -> bool:
    """¿El simulador debe generar magnitudes extra de DEMO? Opt-in por entorno
    (NEXIA_SIM_MULTIVAR=1). Apagado por defecto → el modo simulado emite solo
    vibración y el payload en vivo es idéntico al de antes de multi-variable."""
    return os.getenv("NEXIA_SIM_MULTIVAR", "").strip().lower() in ("1", "true", "yes", "on", "si")


def _metricas_simuladas(m: Maquina, v: float) -> dict[str, float]:
    """Magnitudes extra de DEMO, plausibles y correladas con la vibración, para
    que el frontend vea multi-variable EN VIVO sin hardware. Solo se usan en
    simulación cuando NEXIA_SIM_MULTIVAR está activo; en ingesta real las
    magnitudes llegan del PLC y esta función no se usa."""
    desv = max(0.0, v - m.expected)  # cuánto se desvía de lo esperado
    return {
        "temperatura": round(45 + desv * 3 + (random.random() - 0.5) * 2, 1),
        "presion": round(4.0 + (random.random() - 0.5) * 0.3, 2),
        "rpm": float(round(1480 - desv * 20 + (random.random() - 0.5) * 10)),
        "corriente": round(12 + desv * 0.8 + (random.random() - 0.5) * 0.5, 2),
    }


def tick_maquina(m: Maquina) -> Optional[dict]:
    """Un paso de SIMULACIÓN: avanza el baseline, genera la vibración simulada y
    la evalúa. Devuelve una alerta si acaba de entrar en crítico."""
    _avanzar_baseline(m)
    v = _vibracion_simulada(m)
    metricas = _metricas_simuladas(m, v) if _sim_multivar_activo() else None
    return _evaluar(m, v, _ahora_ms(), metricas)


def procesar_lectura(
    m: Maquina, vib: float, ts: Optional[int] = None, metricas: Optional[dict] = None
) -> Optional[dict]:
    """Procesa una lectura REAL ya normalizada (vib en mm/s, más magnitudes extra
    opcionales en `metricas`) que entra por el módulo de ingesta. Mismo motor que
    la simulación, distinta fuente."""
    _avanzar_baseline(m)
    return _evaluar(m, float(vib), ts or _ahora_ms(), metricas)


def _evento_deteccion(a: dict) -> dict:
    return {"id": "ev-" + a["id"], "ts": a["ts"], "tipo": "deteccion", "maquina": a["maquina"], "detalle": a["causa"], "prob": a["prob"]}


def _evento_resolucion(a: dict, veredicto: str) -> dict:
    detalle = (
        "Confirmado como fallo real"
        if veredicto == "real"
        else "Descartado como falsa alarma"
        if veredicto == "falsa"
        else "Marcado como no concluyente"
    )
    return {"id": f"ev-res-{a['id']}-{_ahora_ms()}", "ts": _ahora_ms(), "tipo": "resolucion", "maquina": a["maquina"], "detalle": detalle}


def _a_historial(a: dict) -> dict:
    return {**a, "estado": "Pendiente"}


class FleetEngine:
    """Estado vivo de la planta + comandos. Toda mutación es síncrona; el broadcast
    al WebSocket lo orquesta main.py tras cada cambio."""

    def __init__(self) -> None:
        self.flota: list[Maquina] = []
        self.alertas: list[dict] = []
        self.historial: list[dict] = []
        self.eventos: list[dict] = []
        self.savings = {"ahorroMes": 2 * AHORRO_POR_PARADA, "paradasEvitadas": 2}
        self.registro = {"real": 23, "falsa": 4, "nc": 3}
        self._calentar()

    # ── Arranque ────────────────────────────────────────────────────────────
    def _calentar(self) -> None:
        self.flota = [crear_maquina(s) for s in FLOTA]
        iniciales: list[dict] = []
        for _ in range(TICKS_CALENTAMIENTO):
            for m in self.flota:
                a = tick_maquina(m)
                if a:
                    iniciales.insert(0, a)
        self.alertas = iniciales
        self.historial = [_a_historial(a) for a in iniciales]
        self.eventos = [_evento_deteccion(a) for a in iniciales]

    # ── Tick periódico ───────────────────────────────────────────────────────
    def step(self) -> dict:
        """Avanza la flota un paso y devuelve el parche 'update' para el WS."""
        nuevas: list[dict] = []
        for m in self.flota:
            a = tick_maquina(m)
            if a:
                nuevas.append(a)

        if nuevas:
            self.alertas = nuevas + self.alertas
            self.historial = [_a_historial(a) for a in nuevas] + self.historial
            self.eventos = ([_evento_deteccion(a) for a in nuevas] + self.eventos)[:MAX_EVENTOS]

        update: dict = {"type": "update", "maquinas": [m.to_dto() for m in self.flota]}
        if nuevas:
            update["nuevasAlertas"] = nuevas
            update["nuevosEventos"] = [_evento_deteccion(a) for a in nuevas]
        return update

    # ── Ingesta de datos REALES ───────────────────────────────────────────────
    def ingest(
        self,
        maquina_id: str,
        vib: float,
        ts: Optional[int] = None,
        metricas: Optional[dict] = None,
    ) -> Optional[dict]:
        """Punto de entrada para una lectura real (la llama el módulo de ingesta,
        ver app/ingest/). Procesa la lectura —vibración + magnitudes extra
        opcionales (`metricas`)— con el MISMO motor que la simulación y devuelve
        el parche 'update' para el WebSocket, o None si la máquina no existe. El
        motor no sabe de qué fuente vino el dato."""
        m = self._maquina(maquina_id)
        if m is None:
            # Máquina desconocida. Para auto-registrar activos al vuelo, aquí se
            # podría crear con crear_maquina({...}); de momento se ignora.
            return None

        alerta = procesar_lectura(m, vib, ts, metricas)
        if alerta:
            self.alertas = [alerta] + self.alertas
            self.historial = [_a_historial(alerta)] + self.historial
            self.eventos = ([_evento_deteccion(alerta)] + self.eventos)[:MAX_EVENTOS]

        update: dict = {"type": "update", "maquinas": [mm.to_dto() for mm in self.flota]}
        if alerta:
            update["nuevasAlertas"] = [alerta]
            update["nuevosEventos"] = [_evento_deteccion(alerta)]
        return update

    # ── Snapshot completo ─────────────────────────────────────────────────────
    def snapshot(self) -> dict:
        return {
            "maquinas": [m.to_dto() for m in self.flota],
            "alertas": self.alertas,
            "historial": self.historial,
            "eventos": self.eventos,
            "savings": self.savings,
            "registro": self.registro,
        }

    def _maquina(self, id_: str) -> Optional[Maquina]:
        return next((m for m in self.flota if m.id == id_), None)

    # ── Comandos (mutan estado; main.py reemite snapshot por el WS) ───────────
    def etiquetar(self, alerta_id: str, veredicto: str) -> None:
        alerta = next((a for a in self.alertas if a["id"] == alerta_id), None)
        self.alertas = [a for a in self.alertas if a["id"] != alerta_id]
        self.historial = [
            {**h, "estado": "Resuelto"} if h["id"] == alerta_id else h for h in self.historial
        ]
        if alerta and veredicto == "real":
            self.savings = {
                "ahorroMes": self.savings["ahorroMes"] + AHORRO_POR_PARADA,
                "paradasEvitadas": self.savings["paradasEvitadas"] + 1,
            }
        if veredicto in self.registro:
            self.registro = {**self.registro, veredicto: self.registro[veredicto] + 1}
        if alerta:
            self.eventos = ([_evento_resolucion(alerta, veredicto)] + self.eventos)[:MAX_EVENTOS]

    def reparar(self, maquina_id: str) -> None:
        m = self._maquina(maquina_id)
        if m:
            m.esc = "sano"
            m.ritmo_dia = 0.0
            m.c_sube = 0
            m.c_baja = 0
            m.estado = "RECOVERY_PROBATION"
            m.prob = 0.05
        self.alertas = [a for a in self.alertas if a["maquina"] != maquina_id]
        self.historial = [
            {**h, "estado": "Resuelto"} if h["maquina"] == maquina_id and h["estado"] == "Pendiente" else h
            for h in self.historial
        ]
        evento = {
            "id": f"ev-mant-{maquina_id}-{_ahora_ms()}",
            "ts": _ahora_ms(),
            "tipo": "resolucion",
            "maquina": maquina_id,
            "detalle": "Mantenimiento completado · máquina en recuperación",
        }
        self.eventos = ([evento] + self.eventos)[:MAX_EVENTOS]

    def crear(self, seed: dict) -> None:
        if any(m.id == seed["id"] for m in self.flota):
            return  # nombre duplicado
        nueva = crear_maquina(seed)
        nueva.calib = CALIBRACION_TICKS  # arranca aprendiendo su baseline
        self.flota.append(nueva)

    def editar(self, id_: str, parcial: dict) -> None:
        m = self._maquina(id_)
        if not m:
            return
        if parcial.get("sector") is not None:
            m.sector = parcial["sector"]
        if parcial.get("sensor") is not None:
            m.sensor = parcial["sensor"]
        if parcial.get("base") is not None:
            m.base = float(parcial["base"])
        if parcial.get("tipo") is not None:
            m.tipo = parcial["tipo"]
        if parcial.get("umbral") is not None:
            m.umbral = float(parcial["umbral"])
        if parcial.get("esc") is not None:
            m.esc = parcial["esc"]
            m.ritmo_dia = 0.7 if parcial["esc"] == "degradando" else 0.0

    def quitar(self, id_: str) -> None:
        self.flota = [m for m in self.flota if m.id != id_]
        self.alertas = [a for a in self.alertas if a["maquina"] != id_]
