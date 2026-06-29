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
from .persistence import crear_persistencia, dump_engine, restaurar_engine
from .tenancy import TenantRegistry


CHECKPOINT_CADA_TICKS = 5  # ~10 s con INTERVALO_S=2: cadencia de guardado a disco


async def _bucle_motor(app: FastAPI) -> None:
    """Modo SIMULACIÓN: cada INTERVALO_S avanza la planta de CADA organización y
    difunde su parche a los WebSocket de esa organización (su hub). Si la
    persistencia está activa, hace checkpoint a disco cada CHECKPOINT_CADA_TICKS."""
    registry: TenantRegistry = app.state.registry
    ticks = 0
    while True:
        await asyncio.sleep(INTERVALO_S)
        ticks += 1
        checkpoint = ticks % CHECKPOINT_CADA_TICKS == 0
        for t in registry.all():
            async with t.lock:
                update = t.engine.step()
                await t.hub.broadcast(update)
                if checkpoint:
                    _persistir_tenant(app, t)


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
    # Auth + tenants (en memoria, sembrados).
    app.state.auth_store = cargar_store()
    app.state.registry = TenantRegistry(app.state.auth_store)

    # Persistencia local OPCIONAL (SQLite, $0). Desactivada por defecto → estado en
    # memoria como hasta ahora. Si está activa, restaura el estado guardado al arrancar.
    app.state.persistencia = crear_persistencia()
    if app.state.persistencia:
        _restaurar_todo(app)

    # Fuente de datos según NEXIA_SOURCE: simulador interno o ingesta externa.
    source = crear_source()
    if source is None:
        tarea = asyncio.create_task(_bucle_motor(app))                       # simulación
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
        # Checkpoint final + cierre ordenado de la persistencia.
        if app.state.persistencia:
            _checkpoint_todo(app)
            app.state.persistencia.close()


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
    _persistir_tenant(app, tenant)  # gated: no-op si la persistencia está desactivada


def _persistir_tenant(app: FastAPI, tenant) -> None:
    """Guarda el estado de un tenant (motor + matriz de permisos) si hay
    persistencia activa. No-op en modo memoria (default)."""
    persistencia = getattr(app.state, "persistencia", None)
    if not persistencia:
        return
    org = app.state.auth_store.org(tenant.org_id)
    record = {
        "engine": dump_engine(tenant.engine),
        "permisos": matriz_a_json(org.permisos) if org else {},
    }
    persistencia.guardar(tenant.org_id, record)


def _restaurar_todo(app: FastAPI) -> None:
    """Restaura el estado de cada tenant desde disco al arrancar (si existe)."""
    for t in app.state.registry.all():
        estado = app.state.persistencia.cargar(t.org_id)
        if not estado:
            continue
        restaurar_engine(t.engine, estado.get("engine", {}))
        org = app.state.auth_store.org(t.org_id)
        permisos = estado.get("permisos")
        if org is not None and isinstance(permisos, dict):
            org.permisos = {p: {r for r in permisos.get(p, []) if r in ROLES} for p in PERMISOS}


def _checkpoint_todo(app: FastAPI) -> None:
    for t in app.state.registry.all():
        _persistir_tenant(app, t)


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
