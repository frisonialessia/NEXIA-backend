# ──────────────────────────────────────────────────────────────────────────
# PERSISTENCIA LOCAL · SQLite ($0, sin servicios externos)
# ──────────────────────────────────────────────────────────────────────────
# Capa OPCIONAL y ADITIVA: desactivada por defecto → el backend corre 100 % en
# memoria como hasta ahora (mismo comportamiento, mismo contrato). Si se activa
# por entorno, el estado de cada organización (flota + alertas + historial +
# eventos + savings/registro + matriz de permisos) se guarda en un fichero SQLite
# local y se restaura al arrancar → sobrevive reinicios. Cero coste, cero infra.
#
# Activación:
#   NEXIA_SQLITE_PATH=/ruta/al/fichero.db   (ruta explícita), o
#   NEXIA_PERSIST=1                          (usa ./nexia_estado.db por defecto)
#
# Diseño deliberado: NO toca el motor (simulation.py) ni el contrato. Serializa el
# estado leyendo atributos públicos del FleetEngine; main.py llama a guardar/
# restaurar desde la capa de orquestación. El engine sigue siendo puro in-memory.
# ──────────────────────────────────────────────────────────────────────────

import dataclasses
import json
import os
import sqlite3
import threading
import time
from typing import Optional

from .simulation import Maquina, Telemetria


def crear_persistencia() -> Optional["SqlitePersistence"]:
    """Devuelve la persistencia según el entorno, o None (modo memoria, default)."""
    path = os.getenv("NEXIA_SQLITE_PATH", "").strip()
    if not path and os.getenv("NEXIA_PERSIST", "").strip().lower() in ("1", "true", "yes", "on", "sqlite"):
        path = "nexia_estado.db"
    return SqlitePersistence(path) if path else None


# ── Serialización del estado de un FleetEngine (sin tocar el motor) ──────────
def dump_engine(engine) -> dict:
    """Vuelca el estado COMPLETO de un FleetEngine a tipos JSON-serializables."""
    return {
        "flota": [dataclasses.asdict(m) for m in engine.flota],
        "alertas": engine.alertas,
        "historial": engine.historial,
        "eventos": engine.eventos,
        "savings": engine.savings,
        "registro": engine.registro,
    }


def restaurar_engine(engine, data: Optional[dict]) -> None:
    """Restaura el estado en un FleetEngine ya construido. Tolerante a datos
    antiguos (ignora campos desconocidos; si una máquina no encaja, la salta)."""
    if not data:
        return
    campos_m = {f.name for f in dataclasses.fields(Maquina)}
    campos_t = {f.name for f in dataclasses.fields(Telemetria)}
    flota = []
    for cruda in data.get("flota", []):
        md = {k: v for k, v in dict(cruda).items() if k in campos_m}
        tele = md.pop("telemetria", None)
        try:
            m = Maquina(**md)
        except TypeError:
            continue  # forma incompatible → se omite esa máquina
        if isinstance(tele, dict):
            m.telemetria = Telemetria(**{k: v for k, v in tele.items() if k in campos_t})
        flota.append(m)
    if flota:
        engine.flota = flota
    for attr in ("alertas", "historial", "eventos", "savings", "registro"):
        if attr in data:
            setattr(engine, attr, data[attr])


# ── Backend SQLite (clave→JSON por organización) ─────────────────────────────
class SqlitePersistence:
    """Almacén key→JSON por organización en un fichero SQLite local."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute(
            "create table if not exists tenant_state ("
            "  org_id text primary key,"
            "  data text not null,"
            "  updated_at text not null)"
        )
        self._conn.commit()

    def cargar(self, org_id: str) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                "select data from tenant_state where org_id=?", (org_id,)
            ).fetchone()
        return json.loads(row[0]) if row else None

    def guardar(self, org_id: str, record: dict) -> None:
        payload = json.dumps(record)
        ahora = str(int(time.time()))
        with self._lock:
            self._conn.execute(
                "insert into tenant_state (org_id, data, updated_at) values (?,?,?) "
                "on conflict(org_id) do update set data=excluded.data, updated_at=excluded.updated_at",
                (org_id, payload, ahora),
            )
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()
