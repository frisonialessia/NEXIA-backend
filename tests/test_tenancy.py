from app.auth.seed import cargar_store
from app.tenancy import TenantRegistry


def _registry():
    return TenantRegistry(cargar_store())


def test_un_tenant_por_organizacion():
    assert len(_registry().all()) == 2


def test_flotas_aisladas_por_tenant():
    reg = _registry()
    norte = {m.id for m in reg.get("org-planta-norte").engine.flota}
    aguas = {m.id for m in reg.get("org-aguas-valle").engine.flota}
    assert "Bomba de agua cruda" in norte and "Bomba de agua cruda" not in aguas
    assert "Bomba captación río" in aguas and "Bomba captación río" not in norte


def test_tenant_por_defecto_es_el_primero():
    assert _registry().default().org_id == "org-planta-norte"


def test_cada_tenant_tiene_motor_hub_lock_propios():
    reg = _registry()
    a, b = reg.get("org-planta-norte"), reg.get("org-aguas-valle")
    assert a.engine is not b.engine
    assert a.hub is not b.hub
    assert a.lock is not b.lock
