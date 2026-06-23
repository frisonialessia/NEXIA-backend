# ──────────────────────────────────────────────────────────────────────────
# NEXIA · API  ·  implementa el contrato de lib/api/contract.ts del frontend
# - GET  /v1/fleet/snapshot   → estado completo (REST)
# - WS   /v1/fleet/live       → snapshot inicial + updates cada 2 s (vivo)
# - comandos (etiquetar / reparar / alta / edición / baja de máquinas)
# El motor simulado actúa como "planta virtual": publica al MISMO WebSocket que
# publicaría un gateway real, así el frontend no nota la diferencia.
# ──────────────────────────────────────────────────────────────────────────

import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .constants import INTERVALO_S
from .contract import ComandoEtiquetar, MaquinaPatchDTO, MaquinaSeedDTO, SnapshotDTO
from .hub import ConnectionHub
from .simulation import FleetEngine

engine = FleetEngine()
hub = ConnectionHub()
lock = asyncio.Lock()  # serializa mutaciones + broadcasts (evita interleaving)


async def _broadcast_snapshot() -> None:
    await hub.broadcast({"type": "snapshot", "data": engine.snapshot()})


async def _bucle_motor() -> None:
    """Avanza la planta cada INTERVALO_S y difunde el parche a los clientes."""
    while True:
        await asyncio.sleep(INTERVALO_S)
        async with lock:
            update = engine.step()
            await hub.broadcast(update)


@asynccontextmanager
async def lifespan(app: FastAPI):
    tarea = asyncio.create_task(_bucle_motor())
    try:
        yield
    finally:
        tarea.cancel()
        try:
            await tarea
        except asyncio.CancelledError:
            pass


app = FastAPI(title="NEXIA API", version="1.0.0", lifespan=lifespan)

# CORS: el frontend (Vercel) llama a este API. Orígenes configurables por entorno.
_origins = os.getenv("NEXIA_CORS_ORIGINS", "*")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if _origins.strip() == "*" else [o.strip() for o in _origins.split(",")],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def raiz():
    return {"servicio": "NEXIA API", "version": "1.0.0", "ws": "/v1/fleet/live", "clientes": hub.count}


# ── Snapshot REST ────────────────────────────────────────────────────────────
@app.get("/v1/fleet/snapshot", response_model=SnapshotDTO)
async def snapshot():
    async with lock:
        return engine.snapshot()


# ── WebSocket en vivo ────────────────────────────────────────────────────────
@app.websocket("/v1/fleet/live")
async def live(ws: WebSocket):
    await hub.connect(ws)
    try:
        # Snapshot inicial al conectar.
        await ws.send_json({"type": "snapshot", "data": engine.snapshot()})
        # No esperamos mensajes del cliente; mantenemos la conexión abierta y
        # detectamos la desconexión.
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        hub.disconnect(ws)
    except Exception:
        hub.disconnect(ws)


# ── Comandos ─────────────────────────────────────────────────────────────────
@app.post("/v1/alerts/{alerta_id}/label")
async def etiquetar(alerta_id: str, cmd: ComandoEtiquetar):
    async with lock:
        engine.etiquetar(alerta_id, cmd.veredicto)
        await _broadcast_snapshot()
    return {"ok": True}


@app.post("/v1/machines/{maquina_id}/repair")
async def reparar(maquina_id: str):
    async with lock:
        engine.reparar(maquina_id)
        await _broadcast_snapshot()
    return {"ok": True}


@app.post("/v1/machines")
async def crear_maquina(seed: MaquinaSeedDTO):
    async with lock:
        engine.crear(seed.model_dump(exclude_none=True))
        await _broadcast_snapshot()
    return {"ok": True}


@app.patch("/v1/machines/{maquina_id}")
async def editar_maquina(maquina_id: str, parcial: MaquinaPatchDTO):
    async with lock:
        engine.editar(maquina_id, parcial.model_dump(exclude_none=True))
        await _broadcast_snapshot()
    return {"ok": True}


@app.delete("/v1/machines/{maquina_id}")
async def quitar_maquina(maquina_id: str):
    async with lock:
        engine.quitar(maquina_id)
        await _broadcast_snapshot()
    return {"ok": True}
