# ──────────────────────────────────────────────────────────────────────────
# MÓDULO DE INGESTA · EL "PUERTO" (contrato de entrada)
# ──────────────────────────────────────────────────────────────────────────
# Patrón puerto/adaptador (hexagonal). Aquí se define el ÚNICO formato que el
# motor entiende: `Lectura`. Cualquier fuente de datos —CSV, MQTT, Modbus TCP,
# OPC UA, un PLC industrial, una API HTTP— se implementa como un `Source`
# concreto que, por cada dato que recibe del mundo real, lo normaliza a
# `Lectura` y llama a `emit()`.
#
# REGLA DE ORO: el motor (app/simulation.py) NO conoce ninguna fuente concreta.
# Solo recibe `Lectura` ya limpias y validadas. Cambiar de CSV a MQTT mañana =
# escribir/activar otro `Source`; la lógica de cómputo no se entera.
#
#        mundo real          adaptador (Source)        motor
#   ┌──────────────────┐   ┌──────────────────┐   ┌──────────────┐
#   │ PLC / sensor /   │──▶│ normaliza a      │──▶│ engine.ingest│
#   │ CSV / API / MQTT │   │ Lectura + emit() │   │ (FSM, alertas)│
#   └──────────────────┘   └──────────────────┘   └──────────────┘
# ──────────────────────────────────────────────────────────────────────────

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

from ..constants import CAMPOS_TELEMETRIA


@dataclass
class Lectura:
    """Dato YA normalizado y validado que entra al motor. Toda fuente, sin
    importar el protocolo de origen, debe producir exactamente esto."""

    maquina_id: str
    """Identidad de la máquina. DEBE coincidir con el id del activo en la flota
    (el mismo que se ve en la UI). El mapeo 'tag del sensor → maquina_id' se hace
    en el Source concreto (ver el mapeo de campos en cada adaptador)."""

    vib: float
    """Vibración RMS en mm/s. Es el PIVOTE: la magnitud sobre la que el motor
    calcula la probabilidad de fallo. Si tu sensor entrega otra unidad/escala,
    conviértela en el Source ANTES de emitir."""

    ts: Optional[int] = None
    """Marca de tiempo epoch en milisegundos. None = 'ahora' (lo pone el motor)."""

    # ── Telemetría: magnitudes EXTRA además de la vibración (todas opcionales) ──
    # Espejo del TelemetriaDTO del contrato. Una fuente que solo tenga vibración
    # las deja en None y el comportamiento es idéntico al de antes de
    # multi-variable. NUNCA incluyen 'vib' (esa viaja en el campo `vib`).
    temp: Optional[float] = None
    """Temperatura (°C)."""
    pres: Optional[float] = None
    """Presión (bar)."""
    rpm: Optional[float] = None
    """Velocidad real medida (rpm)."""
    caudal: Optional[float] = None
    """Caudal (m³/h)."""
    corriente: Optional[float] = None
    """Corriente del motor (A)."""

    def telemetria(self) -> dict[str, float]:
        """Las magnitudes de telemetría PRESENTES como ``{clave: float}`` (sin
        'vib'). Es lo que se entrega al motor (`engine.ingest(..., telemetria=…)`)."""
        return {
            c: float(getattr(self, c))
            for c in CAMPOS_TELEMETRIA
            if getattr(self, c) is not None
        }

    def valores(self) -> dict[str, float]:
        """Todas las magnitudes juntas, incluido el pivote:
        ``{"vib": self.vib, **self.telemetria()}``. Útil para KPIs y almacenamiento."""
        return {"vib": self.vib, **self.telemetria()}


# Función que el runner registra para recibir cada lectura (fuente → motor).
Handler = Callable[[Lectura], Awaitable[None]]


class Source(ABC):
    """Puerto de entrada (el 'enchufe'). Un adaptador concreto hereda de aquí,
    implementa `run()` para leer su fuente, y por cada dato llama a `emit()`.
    No conoce el motor: solo emite Lecturas."""

    def __init__(self) -> None:
        self._handler: Optional[Handler] = None

    def on_reading(self, handler: Handler) -> None:
        """El runner registra aquí a quién entregar cada lectura."""
        self._handler = handler

    async def emit(self, lectura: Lectura) -> None:
        """Lo llama el Source por cada dato recibido y normalizado."""
        if self._handler is not None:
            await self._handler(lectura)

    @abstractmethod
    async def run(self) -> None:
        """Arranca la fuente y emite Lecturas hasta que se cancele la tarea.
        Aquí es donde el adaptador real abre la conexión (broker MQTT, socket
        Modbus, sesión OPC UA, fichero…) y traduce cada dato a `Lectura`."""
        raise NotImplementedError

    async def stop(self) -> None:
        """Cierre ordenado de la fuente (override opcional)."""
        return None
