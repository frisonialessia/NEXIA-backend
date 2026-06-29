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
    CALIBRACION_TICKS,
    CAMPOS_TELEMETRIA,
    COSTO_HORA_PARADA,
    COSTO_PARADA_POR_TIPO,
    FLOTA,
    HORAS_PARADA_TIPICA,
    MAX_EVENTOS,
    TICKS_CALENTAMIENTO,
    UMBRAL_CRITICO,
    VENTANA_HIST,
    perfil_de,
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
    costo_parada_hora: Optional[float] = None  # € / hora de parada (override por máquina)
    telemetria: Telemetria = field(default_factory=Telemetria)  # carry-forward
    temp_alerta: bool = False  # edge-trigger: ¿ya se alertó por sobretemperatura?
    pres_alerta: bool = False  # edge-trigger: ¿ya se alertó por presión fuera de rango?

    def kpis_dto(self) -> Optional[dict]:
        """KPIs derivados (energía/eficiencia/OEE) calculables con la telemetría
        actual. None si no hay datos suficientes. Capa aparte: no toca la FSM."""
        return kpis.desde_valores(self.telemetria.presentes()) or None

    def costo_parada_hora_efectivo(self) -> float:
        """€/hora de parada de ESTA máquina, o el nominal de planta si no se fijó.
        Alimenta el ROI real (ahorro al confirmar una alerta como 'real')."""
        return self.costo_parada_hora if self.costo_parada_hora is not None else COSTO_HORA_PARADA

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
            "costoParadaHora": self.costo_parada_hora_efectivo(),
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
        costo_parada_hora=(
            float(seed["costoParadaHora"]) if seed.get("costoParadaHora") is not None else None
        ),
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
    p = perfil_de(m.tipo)  # umbrales POR TIPO (un compresor a 82 °C no alarma)

    temp = m.telemetria.temp
    if temp is not None:
        if temp > p["temp_max"]:
            if not m.temp_alerta:
                m.temp_alerta = True
                alertas.append(_alerta_metrica(
                    m, v, now_ms, "temperatura",
                    f"Sobretemperatura: {temp} °C supera el umbral de {p['temp_max']} °C",
                    valor=temp, limite=p["temp_max"],
                ))
        else:
            m.temp_alerta = False  # volvió al rango → rearma

    pres = m.telemetria.pres
    if pres is not None:
        if pres < p["pres_min"] or pres > p["pres_max"]:
            if not m.pres_alerta:
                m.pres_alerta = True
                limite = p["pres_min"] if pres < p["pres_min"] else p["pres_max"]
                alertas.append(_alerta_metrica(
                    m, v, now_ms, "presion",
                    f"Presión fuera de rango: {pres} bar (rango {p['pres_min']}–{p['pres_max']} bar)",
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
    """Telemetría de DEMO realista POR TIPO de equipo. Parte de los valores base de
    máquina SANA (perfil del tipo) y los degrada con la severidad del fallo (cuánto
    supera la vibración a lo esperado): suben temp y corriente, bajan rpm y caudal;
    la presión se mantiene en torno a su base. En ingesta real las magnitudes llegan
    del PLC y esta función no se usa."""
    p = perfil_de(m.tipo)
    sev = max(0.0, min((v - m.expected) / 5.0, 1.0))  # 0 sano … 1 fallo severo

    def ruido(amplitud: float) -> float:
        return (random.random() - 0.5) * amplitud

    return {
        "temp": round(p["temp"] + sev * 25 + ruido(1.5), 1),
        "pres": round(p["pres"] + ruido(0.15), 2),
        "rpm": float(round(p["rpm"] * (1 - sev * 0.12) + ruido(8))),
        "caudal": round(max(0.0, p["caudal"] * (1 - sev * 0.30) + ruido(2)), 1),
        "corriente": round(p["kw"] * 1.8 * (1 + sev * 0.40) + ruido(0.4), 2),  # ≈ kW × 1.8
    }


def _demo_activo() -> bool:
    """¿Sembrar el libro de etiquetas de ejemplo para un ROI creíble en demo?
    NEXIA_DEMO=1 lo activa (apagado por defecto → arranque honesto en 0)."""
    return os.getenv("NEXIA_DEMO", "").strip().lower() in ("1", "true", "yes", "on")


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

    def __init__(self, flota_seed: Optional[list[dict]] = None) -> None:
        # Semilla de flota POR TENANT: cada organización arranca con su propia
        # flota. Sin argumento → FLOTA (la demo de siempre), para no romper nada.
        self._flota_seed = flota_seed if flota_seed is not None else FLOTA
        self.flota: list[Maquina] = []
        self.alertas: list[dict] = []
        self.historial: list[dict] = []
        self.eventos: list[dict] = []
        # ROI REAL: arrancan en CERO y se calculan desde las etiquetas reales (ver
        # etiquetar). Sin semillas → los números no son "de demo".
        self.savings = {"ahorroMes": 0.0, "paradasEvitadas": 0}
        self.registro = {"real": 0, "falsa": 0, "nc": 0}
        self._calentar()
        if _demo_activo():
            self._sembrar_demo()

    # ── Arranque ────────────────────────────────────────────────────────────
    def _calentar(self) -> None:
        self.flota = [crear_maquina(s) for s in self._flota_seed]
        iniciales: list[dict] = []
        for _ in range(TICKS_CALENTAMIENTO):
            for m in self.flota:
                for a in tick_maquina(m):
                    iniciales.insert(0, a)
        self.alertas = iniciales
        self.historial = [_a_historial(a) for a in iniciales]
        self.eventos = [_evento_deteccion(a) for a in iniciales]

    def _sembrar_demo(self) -> None:
        """MODO DEMO: asigna coste de parada por tipo a la flota y siembra el LIBRO
        con alertas YA confirmadas (2 'real' + 1 'falsa') para que el ROI REAL
        calcule un ahorro creíble (~$24k) DESDE esas etiquetas de ejemplo. No son
        números inventados: el ahorro se DERIVA de las etiquetas. El frontend las
        marca como 'ejemplo' (NEXT_PUBLIC_DEMO)."""
        for m in self.flota:
            if m.costo_parada_hora is None:
                m.costo_parada_hora = COSTO_PARADA_POR_TIPO.get(m.tipo, COSTO_HORA_PARADA)
        bombas = [m for m in self.flota if m.tipo == "bomba"]
        reales = (bombas or self.flota)[:2]
        falsas = [m for m in self.flota if m not in reales][:1]
        ahora = _ahora_ms()

        def _alerta_ejemplo(m, idx, veredicto, prob, margen):
            pico = round(m.umbral + margen, 2)
            return {
                "id": f"demo-{veredicto}-{idx}", "maquina": m.id, "sensor": m.sensor,
                "tipo": m.tipo, "prob": prob, "ts": ahora - (idx + 1) * 86_400_000,
                "causa": "Vibración fuera del rango esperado: posible "
                + causa_principal(m.tipo).lower(),
                "vib": pico, "exp": m.expected, "umbral": m.umbral,
                "campo": "vibracion", "valor": pico, "limite": m.umbral,
                "estado": "Resuelto", "veredicto": veredicto,
                "ahorro": m.costo_parada_hora_efectivo() * HORAS_PARADA_TIPICA
                if veredicto == "real" else 0.0,
            }

        libro = [_alerta_ejemplo(m, i, "real", 0.84, 1.4) for i, m in enumerate(reales)]
        libro += [_alerta_ejemplo(m, j, "falsa", 0.63, 0.8) for j, m in enumerate(falsas)]
        self.historial = libro + self.historial
        self._recalcular_roi()

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

    def _recalcular_roi(self) -> None:
        """Deriva savings y registro del LIBRO de etiquetas (historial con
        `veredicto`). El historial se persiste → el ROI es reproducible y consistente
        tras reiniciar, e idempotente (re-etiquetar no duplica)."""
        real = falsa = nc = 0
        ahorro = 0.0
        for h in self.historial:
            v = h.get("veredicto")
            if v == "real":
                real += 1
                ahorro += h.get("ahorro") or 0.0
            elif v == "falsa":
                falsa += 1
            elif v == "nc":
                nc += 1
        self.registro = {"real": real, "falsa": falsa, "nc": nc}
        self.savings = {"ahorroMes": round(ahorro, 2), "paradasEvitadas": real}

    # ── Comandos (mutan estado; main.py reemite snapshot por el WS) ───────────
    def etiquetar(self, alerta_id: str, veredicto: str) -> None:
        alerta = next((a for a in self.alertas if a["id"] == alerta_id), None)
        self.alertas = [a for a in self.alertas if a["id"] != alerta_id]
        # Ahorro de ESTA etiqueta: coste/hora de parada de la máquina × horas
        # típicas, solo si se confirma 'real'. Se sella en el libro (historial).
        ahorro = 0.0
        if veredicto == "real":
            ref = alerta or next((h for h in self.historial if h["id"] == alerta_id), None)
            m = self._maquina(ref.get("maquina")) if ref else None
            costo_hora = m.costo_parada_hora_efectivo() if m else COSTO_HORA_PARADA
            ahorro = costo_hora * HORAS_PARADA_TIPICA
        self.historial = [
            {**h, "estado": "Resuelto", "veredicto": veredicto, "ahorro": ahorro}
            if h["id"] == alerta_id else h
            for h in self.historial
        ]
        # ROI = proyección derivada del libro, no un contador suelto.
        self._recalcular_roi()
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
        if parcial.get("costoParadaHora") is not None:
            m.costo_parada_hora = float(parcial["costoParadaHora"])

    def quitar(self, id_: str) -> None:
        self.flota = [m for m in self.flota if m.id != id_]
        self.alertas = [a for a in self.alertas if a["maquina"] != id_]
