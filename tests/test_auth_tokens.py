import time

from app.auth.models import Usuario
from app.auth.tokens import crear_token, verificar_token


def _u():
    return Usuario("u1", "o1", "Ana", "ana@x.com", "admin", "hash", color="#fff")


def test_token_roundtrip(monkeypatch):
    monkeypatch.setenv("NEXIA_JWT_SECRET", "s")
    claims = verificar_token(crear_token(_u()))
    assert claims["sub"] == "u1"
    assert claims["org"] == "o1"
    assert claims["rol"] == "admin"
    assert claims["email"] == "ana@x.com"


def test_token_expirado(monkeypatch):
    monkeypatch.setenv("NEXIA_JWT_SECRET", "s")
    monkeypatch.setenv("NEXIA_JWT_TTL_H", "1")
    # iat hace 2h → exp hace 1h → inválido
    t = crear_token(_u(), now=int(time.time()) - 7200)
    assert verificar_token(t) is None


def test_token_secreto_distinto(monkeypatch):
    monkeypatch.setenv("NEXIA_JWT_SECRET", "s1")
    t = crear_token(_u())
    monkeypatch.setenv("NEXIA_JWT_SECRET", "s2")
    assert verificar_token(t) is None


def test_token_manipulado(monkeypatch):
    monkeypatch.setenv("NEXIA_JWT_SECRET", "s")
    assert verificar_token(crear_token(_u()) + "x") is None
