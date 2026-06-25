# ──────────────────────────────────────────────────────────────────────────
# CONTRATO (modelos de entrada/salida)  ·  espejo de lib/api/contract.ts
# Pydantic valida los cuerpos de los comandos y documenta el snapshot en /docs.
# Los nombres de campo son EXACTAMENTE los del contrato (camelCase) para que el
# frontend los consuma sin mapeo extra.
# ──────────────────────────────────────────────────────────────────────────

from typing import Literal, Optional

from pydantic import BaseModel

Estado = Literal["STABLE", "WARNING_PROBATION", "CRITICAL_ALERT", "RECOVERY_PROBATION"]
TipoMaquina = Literal["bomba", "compresor", "motor", "ventilador"]
Escenario = Literal["sano", "degradando", "critico"]
Veredicto = Literal["real", "falsa", "nc"]


# ── Cuerpos de comandos ─────────────────────────────────────────────────────
class ComandoEtiquetar(BaseModel):
    veredicto: Veredicto


class MaquinaSeedDTO(BaseModel):
    id: str
    sensor: str
    sector: str
    base: float
    esc: Escenario = "sano"
    tipo: Optional[TipoMaquina] = None
    umbral: Optional[float] = None


class MaquinaPatchDTO(BaseModel):
    sensor: Optional[str] = None
    sector: Optional[str] = None
    base: Optional[float] = None
    esc: Optional[Escenario] = None
    tipo: Optional[TipoMaquina] = None
    umbral: Optional[float] = None


# ── Modelos de salida (solo para documentación en /docs) ────────────────────
# NOTA multi-variable: los campos `metricas` / `m` son ADITIVOS y OPCIONALES.
# Solo aparecen con valor cuando la fuente aporta magnitudes extra (temperatura,
# presión, rpm, corriente…). En modo simulado por defecto van vacíos, así que el
# contrato que ya consume el frontend no cambia: `vib`/`exp`/`v` siguen siendo el
# eje. El frontend puede ignorarlos hasta que quiera graficarlos.
class LecturaDTO(BaseModel):
    t: int
    v: float
    exp: float
    m: Optional[dict[str, float]] = None  # magnitudes extra en ese instante


# Telemetría TIPADA (espejo EXACTO del frontend). Convive con el dict genérico
# `metricas`: `metricas` es extensible (cualquier magnitud del vocabulario);
# `telemetria` es la vista fija que el frontend grafica. Solo se emite cuando las
# 5 magnitudes están presentes (por eso son floats no-nulos aquí, pero el campo
# `MaquinaDTO.telemetria` es opcional).
class TelemetriaDTO(BaseModel):
    temp: float       # °C
    pres: float       # bar
    rpm: float        # RPM real medida
    caudal: float     # m³/h
    corriente: float  # A


# KPIs derivados (base de OEE/eficiencia/energía). Todos opcionales: solo vienen
# con valor cuando hay datos para calcularlos. Aditivo: el frontend los ignora
# hasta que quiera mostrarlos.
class KpisDTO(BaseModel):
    eficiencia: Optional[float] = None   # % — caudal real / caudal nominal
    oee: Optional[float] = None          # % — disponibilidad × rendimiento × calidad
    energiaKw: Optional[float] = None    # kW activos estimados (corriente × voltaje)


class MaquinaDTO(BaseModel):
    id: str
    sensor: str
    sector: str
    tipo: TipoMaquina
    base: float
    umbral: float
    estado: Estado
    prob: float
    expected: float
    ritmoDia: float
    horasOp: int
    hist: list[LecturaDTO]
    esc: Optional[Escenario] = None
    calib: Optional[int] = None
    metricas: Optional[dict[str, float]] = None  # dict genérico: último valor por magnitud extra
    telemetria: Optional[TelemetriaDTO] = None   # vista tipada (5 magnitudes), solo si completa
    kpis: Optional[KpisDTO] = None               # KPIs derivados (energía/eficiencia/OEE)


class AlertaDTO(BaseModel):
    id: str
    maquina: str
    sensor: str
    tipo: TipoMaquina
    causa: str
    prob: float
    ts: int
    vib: float
    exp: float
    umbral: float
    estado: Optional[Literal["Pendiente", "Resuelto"]] = None
    metricas: Optional[dict[str, float]] = None  # magnitudes extra al detectar
    # Aditivos: qué magnitud disparó la alerta y su valor/límite. `campo` es
    # "vibracion" | "temperatura" | "presion". Permiten al frontend distinguir
    # alertas de vibración de las de telemetría sin romper el contrato previo.
    campo: Optional[str] = None
    valor: Optional[float] = None
    limite: Optional[float] = None


class EventoDTO(BaseModel):
    id: str
    ts: int
    tipo: Literal["deteccion", "resolucion"]
    maquina: str
    detalle: str
    prob: Optional[float] = None


class SavingsDTO(BaseModel):
    ahorroMes: float
    paradasEvitadas: int


class RegistroDTO(BaseModel):
    real: int
    falsa: int
    nc: int


class SnapshotDTO(BaseModel):
    maquinas: list[MaquinaDTO]
    alertas: list[AlertaDTO]
    historial: list[AlertaDTO]
    eventos: list[EventoDTO]
    savings: SavingsDTO
    registro: RegistroDTO
