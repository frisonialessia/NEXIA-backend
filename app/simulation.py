# ──────────────────────────────────────────────────────────────────────────
# MOTOR DE LA PLANTA VIRTUAL  ·  espejo de lib/data/simulated.ts + fleetStore.ts
# Mantiene el estado vivo de la flota en memoria, lo avanza un "tick" cada 2 s y
# expone el snapshot y los comandos en el formato del contrato (DTOs camelCase).
# El día que existan sensores reales, se reemplaza este motor por la ingesta;
# el contrato y el WebSocket no cambian.
# ──────────────────────────────────────────────────────────────────────────

import math
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
    TICKS_CALENTAMIENTO,
    UMBRAL_CRITICO,
    VENTANA_HIST,
    tipo_de,
)
from .engine import causa_principal, es_alta, probabilidad_fallo, transicion


def _ahora_ms() -> int:
    return int(time.time() * 1000)


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
    hist: list = field(default_factory=list)  # [{"t","v","exp"}]
    expected: float = 0.0
    prob: float = 0.05
    tick: int = 0
    ritmo_dia: float = 0.0
    horas_op: float = 0.0
    calib: int = 0

    def to_dto(self) -> dict:
        return {
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


def tick_maquina(m: Maquina) -> Optional[dict]:
    """Avanza una máquina un paso. Devuelve una AlertaDTO si acaba de entrar en
    crítico; si no, None. Muta la máquina en sitio."""
    m.tick += 1
    m.horas_op += 0.01

    dt = datetime.now()
    hora = dt.hour + dt.minute / 60
    ritmo = 0.3 * math.sin(((hora - 9) / 24) * 2 * math.pi)
    m.expected = round(m.base + ritmo, 3)

    if m.esc == "sano":
        v = m.expected + (random.random() - 0.5) * 0.4
    elif m.esc == "degradando":
        v = m.expected + min(m.tick * 0.05, 4.5) + (random.random() - 0.5) * 0.5
    else:  # critico
        v = m.expected + 4 + random.random() * 2
    v = max(0.0, round(v, 3))

    now_ms = _ahora_ms()

    # ── Calibración: aprendiendo baseline (sin juzgar, sin alertas) ──────────
    if m.calib > 0:
        m.calib -= 1
        m.prob = 0.05
        m.estado = "STABLE"
        m.c_sube = 0
        m.c_baja = 0
        m.hist.append({"t": now_ms, "v": v, "exp": m.expected})
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

    m.hist.append({"t": now_ms, "v": v, "exp": m.expected})
    if len(m.hist) > VENTANA_HIST:
        m.hist.pop(0)

    return alerta


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
