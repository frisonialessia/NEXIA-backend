# ──────────────────────────────────────────────────────────────────────────
# MÓDULO DE INGESTA · RUNNER (cableado fuente → motor → WebSocket)
# ──────────────────────────────────────────────────────────────────────────
# Conecta un `Source` con el motor y el hub. Es el único sitio donde se eligen
# las piezas; ni la fuente conoce el motor, ni el motor la fuente.
#
# La fuente activa se elige por la variable de entorno NEXIA_SOURCE:
#   sim  (por defecto) → no hay ingesta externa; corre el simulador interno.
#   csv                → reproduce app/ingest/sample_readings.csv (o NEXIA_CSV_PATH).
#   mqtt               → escucha un broker MQTT real (ver mqtt_source.py).
#
# 🔌 AÑADIR UNA FUENTE NUEVA (Modbus, OPC UA, HTTP, ADP/UKG…): escribe un Source
#    en app/ingest/sources/ y añade una rama aquí en crear_source(). Nada más.
# ──────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import os
from pathlib import Path
from typing import Awaitable, Callable, Optional

from .source import Lectura, Source
from .sources.csv_source import CsvReplaySource

_CSV_POR_DEFECTO = str(Path(__file__).parent / "sample_readings.csv")


def crear_source() -> Optional[Source]:
    """Devuelve la fuente de ingesta según el entorno, o None para modo simulado."""
    modo = os.getenv("NEXIA_SOURCE", "sim").strip().lower()

    if modo in ("", "sim", "simulacion", "simulation"):
        return None

    if modo == "csv":
        ruta = os.getenv("NEXIA_CSV_PATH", _CSV_POR_DEFECTO)
        intervalo = float(os.getenv("NEXIA_CSV_INTERVALO_S", "2"))
        return CsvReplaySource(ruta, intervalo_s=intervalo)

    if modo == "mqtt":
        from .sources.mqtt_source import MqttSource  # import perezoso (dep opcional)

        return MqttSource()

    if modo in ("opcua", "opc-ua", "opc.ua"):
        from .sources.opcua_source import OpcUaSource  # import perezoso (dep opcional)

        return OpcUaSource()

    raise ValueError(f"NEXIA_SOURCE desconocido: {modo!r} (usa sim | csv | mqtt | opcua)")


async def correr_ingesta(source: Source, on_lectura: Callable[[Lectura], Awaitable[None]]) -> None:
    """Suscribe el motor a la fuente y la arranca. `on_lectura` es el puente al
    motor (lo provee main.py: mete la lectura al engine y difunde por el WS)."""
    source.on_reading(on_lectura)
    await source.run()
