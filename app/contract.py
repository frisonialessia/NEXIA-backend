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
# NOTA multi-variable: la telemetría (temp/pres/rpm/caudal/corriente) NO va en el
# punto de historial, sino en `MaquinaDTO.telemetria` (último valor). El historial
# sigue siendo EXACTAMENTE {t,v,exp} (lo que el frontend ya grafica), así el
# contrato previo no cambia: `vib`/`exp`/`v` siguen siendo el eje.
class LecturaDTO(BaseModel):
    t: int
    v: float
    exp: float


# Telemetría TIPADA (espejo EXACTO del frontend): las 5 magnitudes que la UI
# grafica. Solo se emite cuando las 5 están presentes (por eso son floats no-nulos
# aquí), pero el campo `MaquinaDTO.telemetria` es opcional (None si faltan datos).
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
    telemetria: Optional[TelemetriaDTO] = None  # 5 magnitudes, solo si están completas
    kpis: Optional[KpisDTO] = None              # KPIs derivados (energía/eficiencia/OEE)


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
