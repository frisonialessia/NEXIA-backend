# ──────────────────────────────────────────────────────────────────────────
# KPIs DERIVADOS  ·  energía, eficiencia, OEE
# ──────────────────────────────────────────────────────────────────────────
# Funciones PURAS que derivan indicadores a partir de las magnitudes que ya
# trae una máquina multi-variable (ver Lectura.valores() / Maquina.telemetria).
#
# ESTADO: deja "listo el camino". Hoy NO se exponen en el contrato (el frontend
# no cambia). `desde_valores()` devuelve un dict camelCase pensado para poblar,
# el día de mañana, un futuro MaquinaDTO.kpis SIN acoplar el motor a los KPIs:
# el motor sigue calculando solo la FSM de vibración; esto es una capa aparte.
# ──────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import math
from typing import Optional

from .constants import CAUDAL_NOMINAL

# Voltaje de línea por defecto (V) si el PLC no reporta 'voltaje'.
VOLTAJE_NOMINAL = 400.0
# Factor de potencia típico de un motor industrial cuando no se conoce.
FACTOR_POTENCIA = 0.85

# Placeholders de OEE hasta que haya datos reales de parada (disponibilidad) y de
# scrap (calidad). Hoy solo el RENDIMIENTO sale de un dato medido (caudal/nominal);
# el día que existan esos datos, estos dos se sustituyen por el valor real.
DISPONIBILIDAD_BASE = 0.95
CALIDAD_BASE = 0.99


def energia_kw(
    corriente: Optional[float],
    voltaje: Optional[float] = VOLTAJE_NOMINAL,
    fp: float = FACTOR_POTENCIA,
    trifasico: bool = True,
) -> Optional[float]:
    """Potencia activa estimada (kW) a partir de corriente (A) y voltaje (V).
    Trifásico: P = √3 · V · I · fp. Monofásico: P = V · I · fp.
    Devuelve None si falta o es inválido alguno de los datos."""
    if not corriente or not voltaje or corriente <= 0 or voltaje <= 0:
        return None
    factor = math.sqrt(3) if trifasico else 1.0
    return round(factor * voltaje * corriente * fp / 1000.0, 3)


def eficiencia(salida: Optional[float], entrada: Optional[float]) -> Optional[float]:
    """Eficiencia salida/entrada en % (acotada a 0..100). None si la entrada es
    inválida (evita división por cero)."""
    if not entrada or entrada <= 0 or salida is None:
        return None
    return round(max(0.0, min(1.0, salida / entrada)) * 100, 1)


def oee(
    disponibilidad: Optional[float],
    rendimiento: Optional[float],
    calidad: Optional[float],
) -> Optional[float]:
    """OEE = Disponibilidad × Rendimiento × Calidad, en %. Cada factor es un
    ratio 0..1 (se acota). None si falta alguno."""
    factores = (disponibilidad, rendimiento, calidad)
    if any(f is None for f in factores):
        return None
    producto = 1.0
    for f in factores:
        producto *= max(0.0, min(1.0, f))
    return round(producto * 100, 1)


def desde_valores(valores: dict[str, float]) -> dict[str, float]:
    """Calcula los KPIs DERIVABLES con las magnitudes presentes en `valores`
    (p. ej. {'caudal','corriente'}). Si no hay 'voltaje' se usa el nominal. Solo
    incluye los KPIs calculables con los datos disponibles — no inventa nada.

    Alimenta `MaquinaDTO.kpis` (claves camelCase). Capa aparte del motor: la FSM
    de vibración no depende de esto."""
    kpis: dict[str, float] = {}

    # Energía activa estimada a partir de la corriente del motor (+ voltaje
    # nominal si el PLC no lo reporta).
    e = energia_kw(valores.get("corriente"), valores.get("voltaje", VOLTAJE_NOMINAL))
    if e is not None:
        kpis["energiaKw"] = e

    # Eficiencia = caudal real / caudal de diseño (en %).
    caudal = valores.get("caudal")
    ef = eficiencia(caudal, CAUDAL_NOMINAL)
    if ef is not None:
        kpis["eficiencia"] = ef

    # OEE base = Disponibilidad × Rendimiento × Calidad. Hoy solo el RENDIMIENTO
    # sale de un dato medido (caudal/nominal); disponibilidad y calidad son
    # placeholders documentados (ver arriba) hasta que haya datos de parada/scrap.
    if caudal is not None and CAUDAL_NOMINAL > 0:
        rendimiento = caudal / CAUDAL_NOMINAL
        o = oee(DISPONIBILIDAD_BASE, rendimiento, CALIDAD_BASE)
        if o is not None:
            kpis["oee"] = o

    return kpis
