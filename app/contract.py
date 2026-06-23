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
class LecturaDTO(BaseModel):
    t: int
    v: float
    exp: float


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
