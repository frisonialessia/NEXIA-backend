# ──────────────────────────────────────────────────────────────────────────
# ADAPTADOR · CSV (replay)
# ──────────────────────────────────────────────────────────────────────────
# Fuente REAL y funcional: lee un fichero CSV de lecturas y las reproduce a un
# ritmo dado, emitiendo una `Lectura` por fila. Sirve para:
#   1) Probar todo el pipeline (ingesta → motor → WebSocket → UI) sin hardware.
#   2) Cargar datos históricos de un export de la planta.
#
# Formato del CSV (cabecera obligatoria):
#     maquina_id,vib,ts
#     Bomba de agua cruda,2.4,
#     Bomba de agua cruda,5.1,
#   - maquina_id: debe coincidir con el id del activo en la flota.
#   - vib: vibración RMS en mm/s.
#   - ts: epoch ms (opcional; vacío = 'ahora').
#
# 🔌 MAPEO DE CAMPOS: si tu CSV usa otras columnas (p. ej. 'asset','rms_mm_s'),
#    ajusta COL_MAQUINA / COL_VIB / COL_TS abajo. Ese es el único punto a tocar.
# ──────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import asyncio
import csv
from typing import Optional

from ..source import Lectura, Source

# 🔌 Mapeo de campos: nombres de columna esperados en el CSV de origen.
COL_MAQUINA = "maquina_id"
COL_VIB = "vib"
COL_TS = "ts"


class CsvReplaySource(Source):
    def __init__(self, ruta: str, intervalo_s: float = 2.0, en_bucle: bool = True) -> None:
        super().__init__()
        self.ruta = ruta
        self.intervalo_s = intervalo_s
        self.en_bucle = en_bucle
        self._corriendo = False

    def _leer_filas(self) -> list[Lectura]:
        filas: list[Lectura] = []
        with open(self.ruta, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                try:
                    ts_raw = (row.get(COL_TS) or "").strip()
                    filas.append(
                        Lectura(
                            maquina_id=row[COL_MAQUINA].strip(),
                            vib=float(row[COL_VIB]),
                            ts=int(ts_raw) if ts_raw else None,
                        )
                    )
                except (KeyError, ValueError):
                    # Fila inválida: se descarta (validación de entrada).
                    continue
        return filas

    async def run(self) -> None:
        self._corriendo = True
        filas = self._leer_filas()
        while self._corriendo:
            for lectura in filas:
                if not self._corriendo:
                    break
                await self.emit(lectura)
                await asyncio.sleep(self.intervalo_s)
            if not self.en_bucle:
                break

    async def stop(self) -> None:
        self._corriendo = False
