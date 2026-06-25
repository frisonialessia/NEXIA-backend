from fastapi.testclient import TestClient

from app.contract import SnapshotDTO
from app.main import app


def test_snapshot_http_ok():
    with TestClient(app) as client:
        r = client.get("/v1/fleet/snapshot")
    assert r.status_code == 200
    data = r.json()
    for k in ("maquinas", "alertas", "historial", "eventos", "savings", "registro"):
        assert k in data
    # Revalida contra el contrato (REST y WS comparten esta misma forma).
    SnapshotDTO.model_validate(data)


def test_snapshot_http_invariantes_y_forma():
    with TestClient(app) as client:
        data = client.get("/v1/fleet/snapshot").json()
    for m in data["maquinas"]:
        # Invariante legacy: el punto de historial SIEMPRE trae t/v/exp.
        for p in m["hist"]:
            assert "t" in p and "v" in p and "exp" in p
        # Si hay telemetría (el simulador la genera por defecto), trae las 5.
        if m.get("telemetria") is not None:
            assert set(m["telemetria"]) == {"temp", "pres", "rpm", "caudal", "corriente"}
