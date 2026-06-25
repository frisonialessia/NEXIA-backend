# ──────────────────────────────────────────────────────────────────────────
# DEPENDENCIAS DE AUTH (FastAPI)
# ──────────────────────────────────────────────────────────────────────────
# Extraen y validan el Bearer, resuelven el usuario y comprueban permisos según
# la matriz de su organización. El AuthStore y el TenantRegistry viven en
# app.state (los pone main.py al arrancar).
#
# Flag NEXIA_AUTH: con auth DESACTIVADA (default) todo queda abierto y se usa el
# tenant por defecto → comportamiento idéntico a antes de FASE 2 (demo FASE 1).
# ──────────────────────────────────────────────────────────────────────────

import os
from typing import Optional

from fastapi import Header, HTTPException, Request, status

from .models import Usuario
from .tokens import verificar_token


def auth_activo() -> bool:
    """¿Se exige autenticación? (NEXIA_AUTH=1|true|yes|on)."""
    return os.getenv("NEXIA_AUTH", "0").strip().lower() in ("1", "true", "yes", "on")


def _bearer(authorization: Optional[str]) -> Optional[str]:
    """Saca el token de un header 'Authorization: Bearer <token>'."""
    if not authorization:
        return None
    partes = authorization.split()
    if len(partes) == 2 and partes[0].lower() == "bearer":
        return partes[1]
    return None


def usuario_por_token(request: Request, token: Optional[str]) -> Optional[Usuario]:
    """Verifica un token (de header o de query ?token=) y devuelve su usuario, o
    None si el token falta/es inválido/expiró o el usuario ya no existe."""
    if not token:
        return None
    claims = verificar_token(token)
    if not claims:
        return None
    return request.app.state.auth_store.usuario_por_id(claims.get("sub"))


async def usuario_actual(
    request: Request, authorization: Optional[str] = Header(default=None)
) -> Optional[Usuario]:
    """Usuario del request. Con auth desactivada → None (modo abierto). Con auth
    activada → 401 si el Bearer falta o no es válido."""
    if not auth_activo():
        return None
    usuario = usuario_por_token(request, _bearer(authorization))
    if usuario is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token Bearer ausente o inválido")
    return usuario


async def usuario_requerido(
    request: Request, authorization: Optional[str] = Header(default=None)
) -> Usuario:
    """Exige SIEMPRE un Bearer válido, independientemente de NEXIA_AUTH (para
    /v1/auth/me y operaciones que solo tienen sentido autenticadas)."""
    usuario = usuario_por_token(request, _bearer(authorization))
    if usuario is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token Bearer ausente o inválido")
    return usuario


def requiere_permiso(permiso: str):
    """Dependency factory: exige que el rol del usuario tenga `permiso` en la
    matriz de su organización. Con auth desactivada, no bloquea (modo abierto)."""

    async def dep(request: Request, authorization: Optional[str] = Header(default=None)) -> Optional[Usuario]:
        if not auth_activo():
            return None
        usuario = usuario_por_token(request, _bearer(authorization))
        if usuario is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token Bearer ausente o inválido")
        org = request.app.state.auth_store.org(usuario.org_id)
        if org is None or not org.rol_tiene(usuario.rol, permiso):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"El rol '{usuario.rol}' no tiene el permiso '{permiso}'",
            )
        return usuario

    return dep


def tenant_de(request: Request, usuario: Optional[Usuario]):
    """Tenant (engine+hub+lock) del request. Con auth desactivada o sin usuario →
    el tenant por defecto. Con usuario → el de su organización (404 si no existe)."""
    registry = request.app.state.registry
    if not auth_activo() or usuario is None:
        return registry.default()
    tenant = registry.get(usuario.org_id)
    if tenant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "La organización no tiene planta")
    return tenant
