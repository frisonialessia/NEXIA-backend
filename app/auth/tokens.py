# ──────────────────────────────────────────────────────────────────────────
# TOKENS · JWT propio (HS256) — implementación con SOLO stdlib
# ──────────────────────────────────────────────────────────────────────────
# El backend emite su propio JWT en /v1/auth/login y lo verifica en cada request
# (Authorization: Bearer <token>) y en el WebSocket (?token=). Encaja exacto con
# el contrato del frontend, sin depender de Supabase Auth.
#
# Se usa HMAC-SHA256 de la stdlib (hmac/hashlib): cero dependencias nativas
# (nada de PyJWT/cryptography), por lo que importa y corre en cualquier entorno.
# El token es un JWT HS256 estándar; el frontend lo trata como opaco.
#
# Secreto y caducidad por entorno:
#   NEXIA_JWT_SECRET  → clave de firma (OBLIGATORIA en prod).
#   NEXIA_JWT_TTL_H   → horas de validez (default 12).
# ──────────────────────────────────────────────────────────────────────────

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Optional

ALGO = "HS256"
_SECRETO_DEV = "dev-insecure-secret-change-me"


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _secret() -> bytes:
    return os.getenv("NEXIA_JWT_SECRET", _SECRETO_DEV).encode("utf-8")


def _ttl_segundos() -> int:
    return int(float(os.getenv("NEXIA_JWT_TTL_H", "12")) * 3600)


def _firmar(signing_input: bytes) -> str:
    return _b64url_encode(hmac.new(_secret(), signing_input, hashlib.sha256).digest())


def crear_token(usuario, now: Optional[int] = None) -> str:
    """Firma un JWT HS256 para `usuario` (duck-typed: id/org_id/email/rol/nombre/
    color). `now` (epoch s) es inyectable para tests; por defecto, la hora actual."""
    iat = now if now is not None else int(time.time())
    header = {"alg": ALGO, "typ": "JWT"}
    payload = {
        "sub": usuario.id,
        "org": usuario.org_id,
        "email": usuario.email,
        "rol": usuario.rol,
        "nombre": usuario.nombre,
        "color": usuario.color,
        "iat": iat,
        "exp": iat + _ttl_segundos(),
    }
    h = _b64url_encode(json.dumps(header, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    p = _b64url_encode(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    signing_input = f"{h}.{p}".encode("ascii")
    return f"{h}.{p}.{_firmar(signing_input)}"


def verificar_token(token: str) -> Optional[dict]:
    """Devuelve los claims si el token es válido y no ha expirado; si no, None
    (firma inválida, expirado, manipulado, malformado…). Nunca lanza. La firma se
    compara en tiempo constante y SIEMPRE con HMAC (no se consulta el 'alg' del
    token → inmune a alg-confusion)."""
    try:
        h, p, sig = token.split(".")
    except (ValueError, AttributeError):
        return None
    if not hmac.compare_digest(_firmar(f"{h}.{p}".encode("ascii")), sig):
        return None
    try:
        payload = json.loads(_b64url_decode(p))
    except (ValueError, TypeError):
        return None
    exp = payload.get("exp")
    if exp is not None and int(time.time()) >= int(exp):
        return None
    return payload
