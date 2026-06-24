from fastapi.testclient import TestClient

from app.main import app


def test_snapshot_http_ok():
    with TestClient(app) as client:
        r = client.get("/v1/fleet/snapshot")
    assert r.status_code == 200
    data = r.json()
    for k in ("maquinas", "alertas", "historial", "eventos", "savings", "registro"):
        assert k in data


def test_http_sim_default_campos_opcionales_nulos():
    # En modo simulado por defecto (sin NEXIA_SIM_MULTIVAR) los campos
    # multi-variable llegan como null por REST (aditivos): el frontend los ignora.
    # Los campos legacy del punto de historial siguen presentes.
    with TestClient(app) as client:
        data = client.get("/v1/fleet/snapshot").json()
    for m in data["maquinas"]:
        assert m.get("metricas") is None
        for p in m["hist"]:
            assert "v" in p and "exp" in p and "t" in p
            assert p.get("m") is None
