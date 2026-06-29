from fastapi.testclient import TestClient

from app.main import app
from app.persistence import (
    SqlitePersistence,
    crear_persistencia,
    dump_engine,
    restaurar_engine,
)
from app.simulation import FleetEngine, Telemetria


def test_off_por_defecto(monkeypatch):
    monkeypatch.delenv("NEXIA_PERSIST", raising=False)
    monkeypatch.delenv("NEXIA_SQLITE_PATH", raising=False)
    assert crear_persistencia() is None  # modo memoria = comportamiento de siempre


def test_se_activa_con_path(monkeypatch, tmp_path):
    monkeypatch.setenv("NEXIA_SQLITE_PATH", str(tmp_path / "x.db"))
    p = crear_persistencia()
    assert p is not None
    p.close()


def test_dump_restore_roundtrip():
    e1 = FleetEngine()
    e1.savings = {"ahorroMes": 99999, "paradasEvitadas": 7}
    e1.registro = {"real": 1, "falsa": 2, "nc": 3}
    ids = [m.id for m in e1.flota]

    e2 = FleetEngine()
    restaurar_engine(e2, dump_engine(e1))
    assert [m.id for m in e2.flota] == ids
    assert e2.savings == {"ahorroMes": 99999, "paradasEvitadas": 7}
    assert e2.registro == {"real": 1, "falsa": 2, "nc": 3}
    # La telemetría se reconstruye como Telemetria, no como dict.
    assert all(isinstance(m.telemetria, Telemetria) for m in e2.flota)


def test_sqlite_guardar_cargar(tmp_path):
    p = SqlitePersistence(str(tmp_path / "s.db"))
    assert p.cargar("org-x") is None
    p.guardar("org-x", {"engine": {"savings": {"a": 1}}, "permisos": {}})
    assert p.cargar("org-x")["engine"]["savings"]["a"] == 1
    p.close()


def test_estado_sobrevive_reinicio(monkeypatch, tmp_path):
    # auth off (demo, tenant por defecto). Crea una máquina, "reinicia" el backend
    # (nuevo TestClient con el mismo fichero) y comprueba que persiste.
    monkeypatch.delenv("NEXIA_AUTH", raising=False)
    monkeypatch.setenv("NEXIA_SQLITE_PATH", str(tmp_path / "demo.db"))
    nueva = {"id": "Máquina Persistente", "sensor": "s", "sector": "z", "base": 2.0}

    with TestClient(app) as c:
        assert c.post("/v1/machines", json=nueva).status_code == 200
        antes = {m["id"] for m in c.get("/v1/fleet/snapshot").json()["maquinas"]}
        assert "Máquina Persistente" in antes

    with TestClient(app) as c:  # "reinicio": mismo fichero → restaura
        despues = {m["id"] for m in c.get("/v1/fleet/snapshot").json()["maquinas"]}
        assert "Máquina Persistente" in despues
