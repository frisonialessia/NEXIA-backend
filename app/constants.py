# ──────────────────────────────────────────────────────────────────────────
# CONSTANTES DEL DOMINIO  ·  espejo de lib/constants.ts del frontend
# Mismos valores que la simulación del frontend, para que la "planta virtual"
# se comporte idéntico hasta el día que lleguen sensores reales.
# ──────────────────────────────────────────────────────────────────────────

# ── Dinero ──────────────────────────────────────────────────────────────────
COSTO_HORA_PARADA = 1500
HORAS_PARADA_TIPICA = 8
AHORRO_POR_PARADA = COSTO_HORA_PARADA * HORAS_PARADA_TIPICA  # 12000

# ── Umbral de fallo y calibración ───────────────────────────────────────────
UMBRAL_CRITICO = 6.5
CALIBRACION_TICKS = 6  # una máquina nueva aprende su baseline antes de alertar

# ── Métricas multi-variable ──────────────────────────────────────────────────
# Vocabulario CANÓNICO de magnitudes que puede transportar una Lectura. 'vib'
# (vibración) es el PIVOTE: la magnitud sobre la que el motor calcula la
# probabilidad de fallo y corre la FSM. El resto son telemetría ADITIVA: se
# almacenan y se exponen en el contrato, pero hoy NO alteran la detección. Son,
# además, la base para KPIs futuros (OEE, eficiencia, energía → ver app/kpis.py).
#
# El motor acepta CUALQUIER magnitud numérica que mande el PLC (passthrough): el
# único campo reservado es el pivote 'vib'. Este vocabulario NO filtra lo que
# entra; solo aporta unidades/labels y nombres recomendados para las magnitudes
# conocidas (y alimenta los KPIs). Añadir una conocida = una línea en METRICAS.
METRICA_PIVOTE = "vib"

METRICAS: dict[str, dict[str, str]] = {
    "vib":         {"unidad": "mm/s", "label": "Vibración"},
    "temperatura": {"unidad": "°C",   "label": "Temperatura"},
    "presion":     {"unidad": "bar",  "label": "Presión"},
    "rpm":         {"unidad": "rpm",  "label": "Velocidad"},
    "corriente":   {"unidad": "A",    "label": "Corriente"},
    "voltaje":     {"unidad": "V",    "label": "Voltaje"},
    "caudal":      {"unidad": "m³/h", "label": "Caudal"},
}

# Todas las claves válidas, y las EXTRA (todo menos el pivote, que viaja aparte).
CLAVES_METRICAS = set(METRICAS)
CLAVES_EXTRA = CLAVES_METRICAS - {METRICA_PIVOTE}


def es_metrica_valida(clave: str) -> bool:
    """True si `clave` pertenece al vocabulario canónico de métricas."""
    return clave in CLAVES_METRICAS


def unidad(clave: str) -> str:
    """Unidad de una métrica (cadena vacía si no está en el vocabulario)."""
    m = METRICAS.get(clave)
    return m["unidad"] if m else ""


# ── Motor / simulación ──────────────────────────────────────────────────────
TICKS_CALENTAMIENTO = 8
INTERVALO_S = 2.0
MAX_EVENTOS = 50
VENTANA_HIST = 40

# ── Flota inicial (las 6 máquinas de la demo) ───────────────────────────────
FLOTA = [
    {"id": "Bomba de llenado #1", "sensor": "vib-eje-01", "sector": "Embotelladora", "base": 2.1, "esc": "degradando"},
    {"id": "Compresor de aire #2", "sensor": "vib-01", "sector": "Procesadora de alimentos", "base": 3.4, "esc": "sano"},
    {"id": "Motor cinta transportadora", "sensor": "vib-eje-02", "sector": "Embotelladora", "base": 1.8, "esc": "sano"},
    {"id": "Bomba de agua cruda", "sensor": "vib-01", "sector": "Tratamiento de agua", "base": 2.6, "esc": "critico"},
    {"id": "Ventilador extractor", "sensor": "vib-03", "sector": "Taller mecánico", "base": 1.5, "esc": "sano"},
    {"id": "Bomba dosificadora", "sensor": "vib-02", "sector": "Tratamiento de agua", "base": 2.0, "esc": "sano"},
]

# ── Causas raíz por tipo de máquina ─────────────────────────────────────────
CAUSAS = {
    "bomba": ["Cavitación", "Desgaste de rodamiento", "Desalineación de eje", "Fuga en sello"],
    "compresor": ["Desgaste de rodamiento", "Válvula defectuosa", "Desbalance"],
    "motor": ["Desalineación de eje", "Falla de bobinado", "Rodamiento dañado"],
    "ventilador": ["Desbalance de aspas", "Acumulación de suciedad", "Rodamiento dañado"],
}


def tipo_de(id_: str) -> str:
    """Deduce el tipo de máquina a partir de su nombre (igual que el frontend)."""
    low = id_.lower()
    if "bomba" in low:
        return "bomba"
    if "compresor" in low:
        return "compresor"
    if "motor" in low:
        return "motor"
    if "ventilador" in low:
        return "ventilador"
    return "bomba"
