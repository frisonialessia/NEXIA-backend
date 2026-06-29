import pytest
from fastapi.testclient import TestClient

from app.main import app


def test_arranca_sin_auth_aunque_no_haya_secreto(monkeypatch):
    # Modo demo (auth off): no se exige secreto → arranca igual que en FASE 1.
    monkeypatch.delenv("NEXIA_AUTH", raising=False)
    monkeypatch.delenv("NEXIA_JWT_SECRET", raising=False)
    with TestClient(app):
        pass


def test_falla_si_auth_on_sin_secreto(monkeypatch):
    monkeypatch.setenv("NEXIA_AUTH", "1")
    monkeypatch.delenv("NEXIA_JWT_SECRET", raising=False)
    with pytest.raises(RuntimeError):
        with TestClient(app):
            pass


def test_falla_si_auth_on_con_secreto_de_desarrollo(monkeypatch):
    monkeypatch.setenv("NEXIA_AUTH", "1")
    monkeypatch.setenv("NEXIA_JWT_SECRET", "dev-insecure-secret-change-me")
    with pytest.raises(RuntimeError):
        with TestClient(app):
            pass


def test_arranca_si_auth_on_con_secreto_propio(monkeypatch):
    monkeypatch.setenv("NEXIA_AUTH", "1")
    monkeypatch.setenv("NEXIA_JWT_SECRET", "un-secreto-propio-y-fuerte")
    with TestClient(app):
        pass
