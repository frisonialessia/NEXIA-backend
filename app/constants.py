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
# Añadir una magnitud nueva = una línea en METRICAS + CAMPOS_TELEMETRIA. Motor,
# adaptadores y KPIs derivan todos de aquí.
#
# Las claves usan los MISMOS nombres cortos que el TelemetriaDTO del contrato
# (espejo del frontend): temp, pres, rpm, caudal, corriente.
METRICA_PIVOTE = "vib"

METRICAS: dict[str, dict[str, str]] = {
    "vib":       {"unidad": "mm/s", "label": "Vibración"},
    "temp":      {"unidad": "°C",   "label": "Temperatura"},
    "pres":      {"unidad": "bar",  "label": "Presión"},
    "rpm":       {"unidad": "rpm",  "label": "Velocidad"},
    "caudal":    {"unidad": "m³/h", "label": "Caudal"},
    "corriente": {"unidad": "A",    "label": "Corriente"},
}

# Las 5 magnitudes (en ORDEN) que componen la telemetría = el TelemetriaDTO del
# contrato. 'vib' (el pivote de detección) viaja aparte, en su propio campo.
CAMPOS_TELEMETRIA = ("temp", "pres", "rpm", "caudal", "corriente")


def es_metrica_valida(clave: str) -> bool:
    """True si `clave` pertenece al vocabulario canónico (vib + telemetría)."""
    return clave in METRICAS


def unidad(clave: str) -> str:
    """Unidad de una métrica (cadena vacía si no está en el vocabulario)."""
    m = METRICAS.get(clave)
    return m["unidad"] if m else ""


# ── Reglas multi-variable (alertas que NO son de vibración) ──────────────────
# Detección por umbral simple y EDGE-TRIGGERED (una alerta al cruzar el umbral,
# no una por tick mientras siga fuera). Defaults globales; un override por
# máquina/tipo es trabajo futuro (iría en el seed / PATCH de la máquina).
UMBRAL_TEMP = 80.0   # °C  — por encima: alerta de sobretemperatura
PRES_MIN = 1.0       # bar — por debajo: alerta de presión baja
PRES_MAX = 10.0      # bar — por encima: alerta de sobrepresión

# ── Perfil por tipo de equipo (telemetría realista + umbrales por tipo) ──────
# Valores BASE de máquina SANA (temp °C, pres bar, caudal m³/h, rpm nominal, kw de
# potencia) y RANGOS de alerta por tipo. 'bomba' conserva los umbrales legacy
# (= UMBRAL_TEMP / PRES_MIN / PRES_MAX) para no cambiar el comportamiento base.
# Un compresor sano a 82 °C o un ventilador a 0.6 bar NO deben alarmar: por eso
# los umbrales son por tipo.
PERFIL_EQUIPO: dict[str, dict[str, float]] = {
    "bomba":      {"temp": 54, "pres": 5.2, "caudal": 62, "rpm": 1480, "kw": 7.5,
                   "temp_max": UMBRAL_TEMP, "pres_min": PRES_MIN, "pres_max": PRES_MAX},
    "compresor":  {"temp": 82, "pres": 8.5, "caudal": 38, "rpm": 2950, "kw": 22,
                   "temp_max": 98.0, "pres_min": 6.0, "pres_max": 11.0},
    "motor":      {"temp": 63, "pres": 1.8, "caudal": 12, "rpm": 1460, "kw": 11,
                   "temp_max": 90.0, "pres_min": 1.0, "pres_max": 3.5},
    "ventilador": {"temp": 47, "pres": 0.6, "caudal": 88, "rpm": 950, "kw": 4,
                   "temp_max": 70.0, "pres_min": 0.2, "pres_max": 1.2},
}

# Coste de parada por hora (€) por tipo, para el ROI (override por máquina posible).
COSTO_PARADA_POR_TIPO: dict[str, float] = {
    "bomba": 1500, "compresor": 2500, "motor": 2000, "ventilador": 900,
}


def perfil_de(tipo: str) -> dict:
    """Perfil del tipo (base + umbrales). Default 'bomba' para tipos desconocidos."""
    return PERFIL_EQUIPO.get(tipo, PERFIL_EQUIPO["bomba"])


# ── Nominales para KPIs (OEE / eficiencia / energía) ─────────────────────────
# Valores de diseño con los que se normalizan las magnitudes medidas. Son la
# "base": el día que haya datos por máquina (placa, histórico) se parametrizan.
CAUDAL_NOMINAL = 100.0  # m³/h — caudal de diseño (rendimiento = real / nominal)


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
