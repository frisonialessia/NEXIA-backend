# ──────────────────────────────────────────────────────────────────────────
# NEXIA · API  ·  implementa el contrato de lib/api/contract.ts del frontend
# - POST /v1/auth/login       → { token, usuario }  (login Bearer)
# - GET  /v1/auth/me          → usuario del token
# - GET/PUT /v1/org/permisos  → matriz de permisos de la organización
# - GET  /v1/fleet/snapshot   → estado completo (REST), por organización
# - WS   /v1/fleet/live?token=→ snapshot inicial + updates cada 2 s (vivo)
# - comandos (etiquetar / reparar / alta / edición / baja de máquinas)
#
# MULTI-TENANT: cada organización tiene su propio motor + hub (ver tenancy.py).
# El motor simulado actúa como "planta virtual" por organización; el frontend no
# nota la diferencia con un gateway real.
#
# Flag NEXIA_AUTH: con auth desactivada (default) todo queda abierto y se usa el
# tenant por defecto → comportamiento idéntico a FASE 1.
# ──────────────────────────────────────────────────────────────────────────

import asyncio
import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.middleware.cors import CORSMiddleware

from .auth.deps import (
    auth_activo,
    requiere_permiso,
    tenant_de,
    usuario_actual,
    usuario_por_token,
    usuario_requerido,
)
from .auth.models import Usuario
from .auth.passwords import verify_password
from .auth.roles import PERMISOS, ROLES, matriz_a_json
from .auth.seed import cargar_store
from .auth.tokens import crear_token, usando_secreto_inseguro
from .constants import INTERVALO_S
from .contract import (
    ComandoEtiquetar,
    LoginRequest,
    LoginResponse,
    MaquinaPatchDTO,
    MaquinaSeedDTO,
    SnapshotDTO,
    UsuarioDTO,
)
from .ingest.runner import correr_ingesta, crear_source
from .ingest.source import Lectura
from .tenancy import TenantRegistry


async def _bucle_motor(registry: TenantRegistry) -> None:
    """Modo SIMULACIÓN: cada INTERVALO_S avanza la planta de CADA organización y
    difunde su parche a los WebSocket de esa organización (su hub)."""
    while True:
        await asyncio.sleep(INTERVALO_S)
        for t in registry.all():
            async with t.lock:
                update = t.engine.step()
                await t.hub.broadcast(update)


def _hacer_on_lectura(registry: TenantRegistry):
    """Modo INGESTA: las lecturas reales entran al tenant por defecto. Enrutar
    cada Lectura a su organización es trabajo de una fase posterior; de momento
    alimenta la organización por defecto."""
    tenant = registry.default()

    async def _on_lectura(lectura: Lectura) -> None:
        async with tenant.lock:
            update = tenant.engine.ingest(
                lectura.maquina_id, lectura.vib, lectura.ts, lectura.telemetria()
            )
            if update:
                await tenant.hub.broadcast(update)

    return _on_lectura


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Seguridad (fail-fast): en producción (auth activa) exige un secreto JWT propio
    # o NO arranca. Evita firmar tokens con el secreto de desarrollo por descuido.
    if auth_activo() and usando_secreto_inseguro():
        raise RuntimeError(
            "NEXIA_AUTH=1 pero NEXIA_JWT_SECRET no está configurado (o usa el valor de "
            "desarrollo). Define un secreto propio y fuerte para arrancar con auth."
        )
    # Auth + tenants (en memoria, sembrados). En FASE 2b el store vendrá de la BD.
    app.state.auth_store = cargar_store()
    app.state.registry = TenantRegistry(app.state.auth_store)

    # Fuente de datos según NEXIA_SOURCE: simulador interno o ingesta externa.
    source = crear_source()
    if source is None:
        tarea = asyncio.create_task(_bucle_motor(app.state.registry))        # simulación
    else:
        tarea = asyncio.create_task(
            correr_ingesta(source, _hacer_on_lectura(app.state.registry))    # ingesta real
        )
    try:
        yield
    finally:
        if source is not None:
            await source.stop()
        tarea.cancel()
        try:
            await tarea
        except asyncio.CancelledError:
            pass


app = FastAPI(title="NEXIA API", version="2.0.0", lifespan=lifespan)

# CORS: el frontend (Vercel) llama a este API. Con Bearer (no cookies),
# allow_credentials puede quedar en False; Authorization pasa con allow_headers=*.
_origins = os.getenv("NEXIA_CORS_ORIGINS", "*")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if _origins.strip() == "*" else [o.strip() for o in _origins.split(",")],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def _broadcast_snapshot(tenant) -> None:
    await tenant.hub.broadcast({"type": "snapshot", "data": tenant.engine.snapshot()})


@app.get("/")
async def raiz(request: Request):
    registry: TenantRegistry = request.app.state.registry
    return {
        "servicio": "NEXIA API",
        "version": "2.0.0",
        "ws": "/v1/fleet/live",
        "auth": auth_activo(),
        "organizaciones": len(registry.all()),
        "clientes": sum(t.hub.count for t in registry.all()),
    }


# ── Auth ──────────────────────────────────────────────────────────────────────
@app.post("/v1/auth/login", response_model=LoginResponse, response_model_exclude_none=True)
async def login(req: LoginRequest, request: Request):
    usuario = request.app.state.auth_store.usuario_por_email(req.email)
    if usuario is None or not verify_password(req.password, usuario.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Credenciales inválidas")
    return {"token": crear_token(usuario), "usuario": usuario.dto()}


@app.get("/v1/auth/me", response_model=UsuarioDTO, response_model_exclude_none=True)
async def me(usuario: Usuario = Depends(usuario_requerido)):
    return usuario.dto()


# ── Matriz de permisos por organización ─────────────────────────────────────────
@app.get("/v1/org/permisos")
async def get_permisos(request: Request, usuario: Optional[Usuario] = Depends(usuario_actual)):
    store = request.app.state.auth_store
    org_id = usuario.org_id if (auth_activo() and usuario) else request.app.state.registry.default().org_id
    org = store.org(org_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organización no encontrada")
    return {"organizacion": org.id, "permisos": matriz_a_json(org.permisos)}


@app.put("/v1/org/permisos")
async def put_permisos(payload: dict, request: Request, usuario: Usuario = Depends(usuario_requerido)):
    store = request.app.state.auth_store
    org = store.org(usuario.org_id)
    if org is None or not org.rol_tiene(usuario.rol, "usuarios"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo un admin puede editar la matriz")
    nuevos = payload.get("permisos")
    if not isinstance(nuevos, dict):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Falta 'permisos' (objeto)")
    # Solo se aceptan permisos y roles conocidos (la forma de la matriz es fija).
    org.permisos = {p: {r for r in nuevos.get(p, []) if r in ROLES} for p in PERMISOS}
    return {"organizacion": org.id, "permisos": matriz_a_json(org.permisos)}


# ── Snapshot REST ────────────────────────────────────────────────────────────
@app.get("/v1/fleet/snapshot", response_model=SnapshotDTO)
async def snapshot(request: Request, usuario: Optional[Usuario] = Depends(usuario_actual)):
    tenant = tenant_de(request, usuario)
    async with tenant.lock:
        return tenant.engine.snapshot()


# ── WebSocket en vivo ────────────────────────────────────────────────────────
@app.websocket("/v1/fleet/live")
async def live(ws: WebSocket):
    # Auth por query param: /v1/fleet/live?token=<jwt>. Resuelve la organización.
    registry: TenantRegistry = ws.app.state.registry
    if auth_activo():
        usuario = usuario_por_token(ws, ws.query_params.get("token"))
        tenant = registry.get(usuario.org_id) if usuario else None
        if tenant is None:
            await ws.close(code=status.WS_1008_POLICY_VIOLATION)
            return
    else:
        tenant = registry.default()

    await tenant.hub.connect(ws)
    try:
        await ws.send_json({"type": "snapshot", "data": tenant.engine.snapshot()})
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        tenant.hub.disconnect(ws)
    except Exception:
        tenant.hub.disconnect(ws)


# ── Comandos (cada uno exige su permiso; mutan el tenant del usuario) ─────────
@app.post("/v1/alerts/{alerta_id}/label")
async def etiquetar(
    alerta_id: str, cmd: ComandoEtiquetar, request: Request,
    usuario: Optional[Usuario] = Depends(requiere_permiso("auditar")),
):
    tenant = tenant_de(request, usuario)
    async with tenant.lock:
        tenant.engine.etiquetar(alerta_id, cmd.veredicto)
        await _broadcast_snapshot(tenant)
    return {"ok": True}


@app.post("/v1/machines/{maquina_id}/repair")
async def reparar(
    maquina_id: str, request: Request,
    usuario: Optional[Usuario] = Depends(requiere_permiso("mantenimiento")),
):
    tenant = tenant_de(request, usuario)
    async with tenant.lock:
        tenant.engine.reparar(maquina_id)
        await _broadcast_snapshot(tenant)
    return {"ok": True}


@app.post("/v1/machines")
async def crear_maquina(
    seed: MaquinaSeedDTO, request: Request,
    usuario: Optional[Usuario] = Depends(requiere_permiso("activos")),
):
    tenant = tenant_de(request, usuario)
    async with tenant.lock:
        tenant.engine.crear(seed.model_dump(exclude_none=True))
        await _broadcast_snapshot(tenant)
    return {"ok": True}


@app.patch("/v1/machines/{maquina_id}")
async def editar_maquina(
    maquina_id: str, parcial: MaquinaPatchDTO, request: Request,
    usuario: Optional[Usuario] = Depends(requiere_permiso("activos")),
):
    tenant = tenant_de(request, usuario)
    async with tenant.lock:
        tenant.engine.editar(maquina_id, parcial.model_dump(exclude_none=True))
        await _broadcast_snapshot(tenant)
    return {"ok": True}


@app.delete("/v1/machines/{maquina_id}")
async def quitar_maquina(
    maquina_id: str, request: Request,
    usuario: Optional[Usuario] = Depends(requiere_permiso("activos")),
):
    tenant = tenant_de(request, usuario)
    async with tenant.lock:
        tenant.engine.quitar(maquina_id)
        await _broadcast_snapshot(tenant)
    return {"ok": True}
