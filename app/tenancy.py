# ──────────────────────────────────────────────────────────────────────────
# MULTI-TENANCY · un motor de planta por organización
# ──────────────────────────────────────────────────────────────────────────
# Antes había un único FleetEngine global. Ahora cada organización tiene el suyo,
# con su propia flota, su hub de WebSocket (los clientes solo reciben los datos
# de SU organización) y su lock (serializa mutaciones por tenant). El bucle del
# simulador en main.py itera todos los tenants.
# ──────────────────────────────────────────────────────────────────────────

import asyncio
from typing import Optional

from .auth.store import AuthStore
from .hub import ConnectionHub
from .simulation import FleetEngine


class Tenant:
    """El estado vivo de UNA organización: su motor, su hub y su lock."""

    def __init__(self, org_id: str, flota_seed: Optional[list[dict]] = None) -> None:
        self.org_id = org_id
        self.engine = FleetEngine(flota_seed=flota_seed or None)
        self.hub = ConnectionHub()
        self.lock = asyncio.Lock()


class TenantRegistry:
    """Crea y guarda un Tenant por organización del AuthStore."""

    def __init__(self, store: AuthStore) -> None:
        orgs = store.orgs()
        self._tenants: dict[str, Tenant] = {
            org.id: Tenant(org.id, org.flota_seed) for org in orgs
        }
        # Tenant por defecto (cuando NEXIA_AUTH=0): la primera organización.
        self._default_id: Optional[str] = orgs[0].id if orgs else None

    def get(self, org_id: str) -> Optional[Tenant]:
        return self._tenants.get(org_id)

    def default(self) -> Tenant:
        if self._default_id is None:
            raise RuntimeError("No hay ninguna organización sembrada")
        return self._tenants[self._default_id]

    def all(self) -> list[Tenant]:
        return list(self._tenants.values())
