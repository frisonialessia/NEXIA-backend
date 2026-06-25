# ──────────────────────────────────────────────────────────────────────────
# CONTRASEÑAS · hashing con PBKDF2-HMAC-SHA256 (solo stdlib)
# ──────────────────────────────────────────────────────────────────────────
# Nunca se guarda la contraseña en claro: solo su hash con sal aleatoria. Se usa
# hashlib.pbkdf2_hmac (stdlib) → cero dependencias nativas (nada de bcrypt/cffi),
# importa y corre en cualquier entorno. PBKDF2-SHA256 con sal por contraseña es un
# esquema estándar y robusto para este caso.
#
# Formato almacenado:  pbkdf2_sha256$<iteraciones>$<salt_b64>$<hash_b64>
# ──────────────────────────────────────────────────────────────────────────

import base64
import hashlib
import hmac
import os
from typing import Optional

_ALGO = "pbkdf2_sha256"
_ITERACIONES = 200_000


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _ub64(s: str) -> bytes:
    return base64.b64decode(s.encode("ascii"))


def hash_password(plano: str, *, iteraciones: int = _ITERACIONES, salt: Optional[bytes] = None) -> str:
    """Devuelve el hash PBKDF2 (con sal aleatoria) de la contraseña en claro."""
    salt = salt if salt is not None else os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", plano.encode("utf-8"), salt, iteraciones)
    return f"{_ALGO}${iteraciones}${_b64(salt)}${_b64(dk)}"


def verify_password(plano: str, hashed: str) -> bool:
    """True si la contraseña en claro coincide con el hash. Comparación en tiempo
    constante. Nunca lanza (un hash malformado → False)."""
    try:
        algo, iteraciones, salt_b64, dk_b64 = hashed.split("$")
        if algo != _ALGO:
            return False
        dk = hashlib.pbkdf2_hmac("sha256", plano.encode("utf-8"), _ub64(salt_b64), int(iteraciones))
        return hmac.compare_digest(dk, _ub64(dk_b64))
    except (ValueError, TypeError):
        return False
