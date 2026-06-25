# ──────────────────────────────────────────────────────────────────────────
# MODELOS DE AUTH · Organización y Usuario (multi-tenant)
# ──────────────────────────────────────────────────────────────────────────
# En FASE 2a viven en memoria (sembrados). En 2b serán filas en Postgres; estos
# dataclasses son la forma que la capa de repositorio devolverá igualmente.
# ──────────────────────────────────────────────────────────────────────────

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Usuario:
    id: str
    org_id: str
    nombre: str
    email: str
    rol: str            # admin | jefe | tecnico | operador | lectura
    password_hash: str
    color: Optional[str] = None

    def dto(self) -> dict:
        """Forma EXACTA que consume el frontend: {nombre, email, rol, color?}.
        `color` solo aparece si está definido."""
        d = {"nombre": self.nombre, "email": self.email, "rol": self.rol}
        if self.color is not None:
            d["color"] = self.color
        return d


@dataclass
class Organizacion:
    id: str
    nombre: str
    slug: str
    permisos: dict[str, set[str]]            # permiso -> roles (matriz editable)
    flota_seed: list[dict] = field(default_factory=list)

    def rol_tiene(self, rol: str, permiso: str) -> bool:
        """¿El `rol` tiene `permiso` según la matriz de ESTA organización?"""
        return rol in self.permisos.get(permiso, set())
