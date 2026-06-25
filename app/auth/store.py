# ──────────────────────────────────────────────────────────────────────────
# STORE DE AUTH · interfaz de acceso a orgs/usuarios
# ──────────────────────────────────────────────────────────────────────────
# Implementación EN MEMORIA para FASE 2a. La forma de esta clase es la "interfaz
# de repositorio": en FASE 2b se añade una implementación Postgres con los mismos
# métodos y se cambia el cableado, sin tocar deps/main.
# ──────────────────────────────────────────────────────────────────────────

from typing import Optional

from .models import Organizacion, Usuario


class AuthStore:
    def __init__(self, orgs: list[Organizacion], usuarios: list[Usuario]) -> None:
        self._orgs: dict[str, Organizacion] = {o.id: o for o in orgs}
        self._por_email: dict[str, Usuario] = {u.email.strip().lower(): u for u in usuarios}
        self._por_id: dict[str, Usuario] = {u.id: u for u in usuarios}

    def usuario_por_email(self, email: str) -> Optional[Usuario]:
        return self._por_email.get((email or "").strip().lower())

    def usuario_por_id(self, uid: str) -> Optional[Usuario]:
        return self._por_id.get(uid)

    def org(self, org_id: str) -> Optional[Organizacion]:
        return self._orgs.get(org_id)

    def orgs(self) -> list[Organizacion]:
        return list(self._orgs.values())
