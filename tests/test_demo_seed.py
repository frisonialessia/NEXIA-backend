from fastapi.testclient import TestClient

from app.main import app
from app.simulation import FleetEngine


def test_sin_demo_arranca_en_cero(monkeypatch):
    monkeypatch.delenv("NEXIA_DEMO", raising=False)
    assert FleetEngine().snapshot()["savings"] == {"ahorroMes": 0.0, "paradasEvitadas": 0}


def test_demo_siembra_un_roi_creible(monkeypatch):
    monkeypatch.setenv("NEXIA_DEMO", "1")
    snap = FleetEngine().snapshot()
    # ROI DERIVADO de etiquetas de ejemplo (no inventado): ~$24k.
    assert 20000 <= snap["savings"]["ahorroMes"] <= 25000
    assert snap["savings"]["paradasEvitadas"] >= 2
    assert snap["registro"]["real"] >= 2


def test_demo_via_api_y_contrato_valido(monkeypatch):
    monkeypatch.setenv("NEXIA_DEMO", "1")
    monkeypatch.delenv("NEXIA_AUTH", raising=False)
    with TestClient(app) as c:  # valida SnapshotDTO (historial incluido)
        snap = c.get("/v1/fleet/snapshot").json()
    assert snap["savings"]["ahorroMes"] >= 20000
    assert any(h.get("veredicto") == "real" for h in snap["historial"])
