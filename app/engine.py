# ──────────────────────────────────────────────────────────────────────────
# MÁQUINA DE ESTADOS CON HISTÉRESIS + DETECCIÓN  ·  espejo de lib/engine/fsm.ts
# Funciones puras: detección por desviación → sigmoide → probabilidad de fallo,
# y una FSM anti-flapping (sube a crítico tras 3 lecturas altas, baja tras 5).
# ──────────────────────────────────────────────────────────────────────────

import math

PROB_ALTA = 0.6
DESV_ESTANDAR = 0.5


def probabilidad_fallo(real: float, esperado: float) -> float:
    """Probabilidad de fallo (0.02..0.99) por desviación, vía sigmoide."""
    desv = (real - esperado) / DESV_ESTANDAR
    return min(0.99, max(0.02, 1 / (1 + math.exp(-(desv - 3)))))


def es_alta(prob: float) -> bool:
    return prob >= PROB_ALTA


def transicion(estado: str, c_sube: int, c_baja: int, alto: bool):
    """Aplica una transición de la FSM. Devuelve (estado, c_sube, c_baja)."""
    if alto:
        c_sube += 1
        c_baja = 0
    else:
        c_baja += 1
        c_sube = 0

    siguiente = estado
    if estado == "STABLE":
        if alto:
            siguiente = "WARNING_PROBATION"
    elif estado == "WARNING_PROBATION":
        if c_sube >= 3:
            siguiente = "CRITICAL_ALERT"
        elif c_baja >= 2:
            siguiente = "STABLE"
    elif estado == "CRITICAL_ALERT":
        if not alto and c_baja >= 1:
            siguiente = "RECOVERY_PROBATION"
    elif estado == "RECOVERY_PROBATION":
        if c_baja >= 5:
            siguiente = "STABLE"
        elif alto:
            siguiente = "CRITICAL_ALERT"

    return siguiente, c_sube, c_baja


def causa_principal(tipo: str) -> str:
    from .constants import CAUSAS

    return (CAUSAS.get(tipo) or CAUSAS["bomba"])[0]
