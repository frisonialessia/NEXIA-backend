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

from . import kpis
from .constants import (
    AHORRO_POR_PARADA,
    CALIBRACION_TICKS,
    CAMPOS_TELEMETRIA,
    FLOTA,
    MAX_EVENTOS,
    PRES_MAX,
    PRES_MIN,
    TICKS_CALENTAMIENTO,
    UMBRAL_CRITICO,
    UMBRAL_TEMP,
    VENTANA_HIST,
    tipo_de,
)
from .engine import causa_principal, es_alta, probabilidad_fallo, transicion

# Probabilidad nominal asignada a una alerta por umbral de telemetría (temp /
# presión). La detección de vibración sí calcula una probabilidad continua; un
# cruce de umbral es binario, así que se reporta con confianza alta y fija.
PROB_UMBRAL = 0.9


def _ahora_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class Telemetria:
    """Las 5 magnitudes de telemetría que acompañan a la vibración. Vive en el
    estado de la máquina (`Maquina.telemetria`) con CARRY-FORWARD: cada lectura
    actualiza solo lo que trae y conserva el último valor conocido del resto.
    Es la única representación de telemetría (no hay dict genérico)."""

    temp: Optional[float] = None
    pres: Optional[float] = None
    rpm: Optional[float] = None
    caudal: Optional[float] = None
    corriente: Optional[float] = None

    def merge(self, datos: Optional[dict]) -> None:
        """Funde (carry-forward) las magnitudes presentes y numéricas. Descarta
        el pivote 'vib', las claves desconocidas y los valores no numéricos: es
        la frontera de validación de la telemetría."""
        if not datos:
            return
        for campo in CAMPOS_TELEMETRIA:
            if campo not in datos or datos[campo] is None:
                continue
            try:
                setattr(self, campo, float(datos[campo]))
            except (TypeError, ValueError):
                continue

    def completa(self) -> bool:
        """¿Están las 5 magnitudes? (requisito para exponer TelemetriaDTO)."""
        return all(getattr(self, c) is not None for c in CAMPOS_TELEMETRIA)

    def presentes(self) -> dict[str, float]:
        """Magnitudes con valor, como ``{clave: float}`` (para KPIs/reglas)."""
        return {c: getattr(self, c) for c in CAMPOS_TELEMETRIA if getattr(self, c) is not None}

    def dto(self) -> Optional[dict]:
        """TelemetriaDTO: las 5 magnitudes, SOLO si están completas; si no, None."""
        if self.completa():
            return {c: getattr(self, c) for c in CAMPOS_TELEMETRIA}
        return None


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
    telemetria: Telemetria = field(default_factory=Telemetria)  # carry-forward
    temp_alerta: bool = False  # edge-trigger: ¿ya se alertó por sobretemperatura?
    pres_alerta: bool = False  # edge-trigger: ¿ya se alertó por presión fuera de rango?

    def kpis_dto(self) -> Optional[dict]:
        """KPIs derivados (energía/eficiencia/OEE) calculables con la telemetría
        actual. None si no hay datos suficientes. Capa aparte: no toca la FSM."""
        return kpis.desde_valores(self.telemetria.presentes()) or None

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
        # ADITIVOS: cada bloque solo se incluye cuando hay datos. Con la telemetría
        # del simulador desactivada (NEXIA_SIM_MULTIVAR=0) ninguno aparece →
        # payload idéntico al de antes de multi-variable.
        tele = self.telemetria.dto()
        if tele is not None:
            dto["telemetria"] = tele                # vista tipada (frontend)
        kpi = self.kpis_dto()
        if kpi is not None:
            dto["kpis"] = kpi
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


def _alerta_vibracion(m: Maquina, v: float, now_ms: int) -> dict:
    """Alerta clásica de vibración (la que ya consumía el frontend). Añade los
    campos aditivos campo/valor/limite para uniformar con las de telemetría."""
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
        "campo": "vibracion",
        "valor": v,
        "limite": m.umbral,
    }
    return alerta


def _alerta_metrica(
    m: Maquina, v: float, now_ms: int, campo: str, causa: str, valor: float, limite: float
) -> dict:
    """Alerta por una magnitud de telemetría (temperatura, presión…). Reusa el
    MISMO formato que la de vibración (vib/exp/umbral con el contexto de
    vibración actual) y añade los campos aditivos campo/valor/limite que
    identifican qué magnitud disparó. Así el contrato no cambia para el frontend."""
    alerta = {
        "id": f"al-{campo}-{m.id}-{now_ms}",
        "maquina": m.id,
        "sensor": m.sensor,
        "tipo": m.tipo,
        "causa": causa,
        "prob": PROB_UMBRAL,
        "ts": now_ms,
        "vib": v,
        "exp": m.expected,
        "umbral": m.umbral,
        "campo": campo,
        "valor": round(valor, 3),
        "limite": limite,
    }
    return alerta


def _reglas_telemetria(m: Maquina, v: float, now_ms: int) -> list[dict]:
    """Reglas de alerta sobre magnitudes que NO son vibración (sobretemperatura,
    presión fuera de rango). EDGE-TRIGGERED: una alerta al cruzar el umbral; no
    se repite cada tick mientras siga fuera, y se rearma al volver al rango. NO
    intervienen en la FSM de vibración."""
    alertas: list[dict] = []

    temp = m.telemetria.temp
    if temp is not None:
        if temp > UMBRAL_TEMP:
            if not m.temp_alerta:
                m.temp_alerta = True
                alertas.append(_alerta_metrica(
                    m, v, now_ms, "temperatura",
                    f"Sobretemperatura: {temp} °C supera el umbral de {UMBRAL_TEMP} °C",
                    valor=temp, limite=UMBRAL_TEMP,
                ))
        else:
            m.temp_alerta = False  # volvió al rango → rearma

    pres = m.telemetria.pres
    if pres is not None:
        fuera = pres < PRES_MIN or pres > PRES_MAX
        if fuera:
            if not m.pres_alerta:
                m.pres_alerta = True
                limite = PRES_MIN if pres < PRES_MIN else PRES_MAX
                alertas.append(_alerta_metrica(
                    m, v, now_ms, "presion",
                    f"Presión fuera de rango: {pres} bar (rango {PRES_MIN}–{PRES_MAX} bar)",
                    valor=pres, limite=limite,
                ))
        else:
            m.pres_alerta = False  # volvió al rango → rearma

    return alertas


def _evaluar(m: Maquina, v: float, now_ms: int, telemetria: Optional[dict] = None) -> list[dict]:
    """EL MOTOR. Dada una lectura de vibración `v` (venga de donde venga) y, de
    forma OPCIONAL, otras magnitudes (`telemetria`: temp, pres, rpm, caudal,
    corriente…), aplica calibración, probabilidad de fallo y la FSM, y devuelve
    la LISTA de alertas generadas en este paso (vacía si ninguna): la de
    vibración al entrar en crítico, más las de telemetría (temp/presión).

    La detección de FALLO PIVOTA solo sobre `v` (FSM + probabilidad intactas).
    Las magnitudes extra son telemetría: se almacenan, alimentan reglas de umbral
    propias e independientes, y se exponen. NO sabe si el dato es real o simulado."""
    v = max(0.0, round(v, 3))

    # Telemetría multi-variable: fusiona (carry-forward) las magnitudes presentes
    # en el estado de la máquina. No interviene en la FSM de vibración.
    m.telemetria.merge(telemetria)

    def _punto() -> dict:
        # Punto de historial: EXACTAMENTE {"t","v","exp"} (lo que el frontend ya
        # consume). La telemetría viaja aparte, en Maquina.telemetria.
        return {"t": now_ms, "v": v, "exp": m.expected}

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
        return []

    m.prob = probabilidad_fallo(v, m.expected)
    alto = es_alta(m.prob)
    prev = m.estado
    m.estado, m.c_sube, m.c_baja = transicion(m.estado, m.c_sube, m.c_baja, alto)

    alertas: list[dict] = []
    if m.estado == "CRITICAL_ALERT" and prev != "CRITICAL_ALERT":
        alertas.append(_alerta_vibracion(m, v, now_ms))

    # Reglas de telemetría (independientes de la FSM de vibración).
    alertas.extend(_reglas_telemetria(m, v, now_ms))

    m.hist.append(_punto())
    if len(m.hist) > VENTANA_HIST:
        m.hist.pop(0)

    return alertas


def _sim_multivar_activo() -> bool:
    """¿El simulador genera telemetría (temp/pres/rpm/caudal/corriente)? Por
    DEFECTO sí, para que el frontend vea multi-variable EN VIVO sin hardware. Se
    apaga con NEXIA_SIM_MULTIVAR=0 (entonces el modo simulado emite solo
    vibración y el payload es idéntico al de antes de multi-variable)."""
    return os.getenv("NEXIA_SIM_MULTIVAR", "1").strip().lower() not in ("0", "false", "no", "off")


def _telemetria_simulada(m: Maquina, v: float) -> dict[str, float]:
    """Telemetría de DEMO: las 5 magnitudes del TelemetriaDTO, plausibles y
    correladas con la vibración, para que el frontend vea multi-variable EN VIVO
    sin hardware. Se mantiene en rangos normales (no dispara las reglas de
    temp/presión). En ingesta real las magnitudes llegan del PLC y esta función
    no se usa."""
    desv = max(0.0, v - m.expected)  # cuánto se desvía de lo esperado
    return {
        "temp": round(45 + desv * 3 + (random.random() - 0.5) * 2, 1),
        "pres": round(4.0 + (random.random() - 0.5) * 0.3, 2),
        "rpm": float(round(1480 - desv * 20 + (random.random() - 0.5) * 10)),
        "caudal": round(max(0.0, 98 - desv * 4 + (random.random() - 0.5) * 2), 1),
        "corriente": round(12 + desv * 0.8 + (random.random() - 0.5) * 0.5, 2),
    }


def tick_maquina(m: Maquina) -> list[dict]:
    """Un paso de SIMULACIÓN: avanza el baseline, genera la vibración simulada
    (y la telemetría de demo si está activa) y la evalúa. Devuelve la lista de
    alertas generadas en este paso (vacía si ninguna)."""
    _avanzar_baseline(m)
    v = _vibracion_simulada(m)
    telemetria = _telemetria_simulada(m, v) if _sim_multivar_activo() else None
    return _evaluar(m, v, _ahora_ms(), telemetria)


def procesar_lectura(
    m: Maquina, vib: float, ts: Optional[int] = None, telemetria: Optional[dict] = None
) -> list[dict]:
    """Procesa una lectura REAL ya normalizada (vib en mm/s, más magnitudes de
    telemetría opcionales) que entra por el módulo de ingesta. Mismo motor que la
    simulación, distinta fuente. Devuelve la lista de alertas generadas."""
    _avanzar_baseline(m)
    return _evaluar(m, float(vib), ts or _ahora_ms(), telemetria)


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
                for a in tick_maquina(m):
                    iniciales.insert(0, a)
        self.alertas = iniciales
        self.historial = [_a_historial(a) for a in iniciales]
        self.eventos = [_evento_deteccion(a) for a in iniciales]

    # ── Tick periódico ───────────────────────────────────────────────────────
    def step(self) -> dict:
        """Avanza la flota un paso y devuelve el parche 'update' para el WS."""
        nuevas: list[dict] = []
        for m in self.flota:
            nuevas.extend(tick_maquina(m))

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
        telemetria: Optional[dict] = None,
    ) -> Optional[dict]:
        """Punto de entrada para una lectura real (la llama el módulo de ingesta,
        ver app/ingest/). Procesa la lectura —vibración + magnitudes de telemetría
        opcionales— con el MISMO motor que la simulación y devuelve el parche
        'update' para el WebSocket, o None si la máquina no existe. El motor no
        sabe de qué fuente vino el dato."""
        m = self._maquina(maquina_id)
        if m is None:
            # Máquina desconocida. Para auto-registrar activos al vuelo, aquí se
            # podría crear con crear_maquina({...}); de momento se ignora.
            return None

        alertas = procesar_lectura(m, vib, ts, telemetria)
        if alertas:
            self.alertas = alertas + self.alertas
            self.historial = [_a_historial(a) for a in alertas] + self.historial
            self.eventos = ([_evento_deteccion(a) for a in alertas] + self.eventos)[:MAX_EVENTOS]

        update: dict = {"type": "update", "maquinas": [mm.to_dto() for mm in self.flota]}
        if alertas:
            update["nuevasAlertas"] = alertas
            update["nuevosEventos"] = [_evento_deteccion(a) for a in alertas]
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
