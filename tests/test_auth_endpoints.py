import pytest
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient

from app.auth.seed import PASSWORD_DEMO
from app.main import app


@pytest.fixture
def client(monkeypatch):
    # Auth ACTIVADA + secreto fijo para todo el test.
    monkeypatch.setenv("NEXIA_AUTH", "1")
    monkeypatch.setenv("NEXIA_JWT_SECRET", "test-secret")
    with TestClient(app) as c:
        yield c


def _login(client, email, password=PASSWORD_DEMO):
    return client.post("/v1/auth/login", json={"email": email, "password": password})


def _tok(client, email):
    return _login(client, email).json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


# ── Login ───────────────────────────────────────────────────────────────────
def test_login_ok_devuelve_token_y_usuario(client):
    r = _login(client, "alessia@planta.com")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["token"], str) and body["token"]
    # Forma EXACTA del contrato (color omitido si no está definido).
    assert body["usuario"] == {"nombre": "Alessia", "email": "alessia@planta.com", "rol": "admin"}


def test_login_password_incorrecta_401(client):
    assert _login(client, "alessia@planta.com", "mal").status_code == 401


def test_login_email_desconocido_401(client):
    assert _login(client, "nadie@x.com").status_code == 401


# ── Bearer requerido + /me ────────────────────────────────────────────────────
def test_snapshot_sin_token_401(client):
    assert client.get("/v1/fleet/snapshot").status_code == 401


def test_me_devuelve_usuario(client):
    r = client.get("/v1/auth/me", headers=_auth(_tok(client, "carlos@planta.com")))
    assert r.status_code == 200 and r.json()["rol"] == "jefe"


def test_me_sin_token_401(client):
    assert client.get("/v1/auth/me").status_code == 401


# ── Aislamiento multi-tenant ──────────────────────────────────────────────────
def test_snapshot_scoped_a_planta_norte(client):
    snap = client.get("/v1/fleet/snapshot", headers=_auth(_tok(client, "alessia@planta.com"))).json()
    nombres = {m["id"] for m in snap["maquinas"]}
    assert "Bomba de agua cruda" in nombres
    assert "Bomba captación río" not in nombres  # es de Aguas del Valle


def test_aislamiento_entre_organizaciones(client):
    snap = client.get("/v1/fleet/snapshot", headers=_auth(_tok(client, "tecnico@aguasdelvalle.com"))).json()
    nombres = {m["id"] for m in snap["maquinas"]}
    assert "Bomba captación río" in nombres
    assert "Bomba de agua cruda" not in nombres


# ── Roles / permisos ──────────────────────────────────────────────────────────
def test_operador_audita_pero_no_gestiona_activos(client):
    tok = _tok(client, "luis@planta.com")  # operador
    assert client.post("/v1/alerts/x/label", json={"veredicto": "falsa"}, headers=_auth(tok)).status_code == 200
    assert client.post("/v1/machines", json={"id": "X", "sensor": "s", "sector": "y", "base": 2.0}, headers=_auth(tok)).status_code == 403


def test_tecnico_gestiona_activos(client):
    tok = _tok(client, "roberto@planta.com")  # tecnico
    r = client.post("/v1/machines", json={"id": "Nueva", "sensor": "s", "sector": "y", "base": 2.0}, headers=_auth(tok))
    assert r.status_code == 200


def test_lectura_no_audita(client):
    tok = _tok(client, "audit@planta.com")  # lectura
    assert client.post("/v1/alerts/x/label", json={"veredicto": "real"}, headers=_auth(tok)).status_code == 403


# ── Matriz de permisos ────────────────────────────────────────────────────────
def test_get_permisos_defaults(client):
    permisos = client.get("/v1/org/permisos", headers=_auth(_tok(client, "alessia@planta.com"))).json()["permisos"]
    assert permisos["activos"] == ["admin", "tecnico"]
    assert "operador" in permisos["auditar"]
    assert permisos["exportar"] == ["admin", "jefe", "tecnico", "lectura"]


def test_put_permisos_solo_admin(client):
    nuevos = {"permisos": {"activos": ["admin"]}}
    assert client.put("/v1/org/permisos", json=nuevos, headers=_auth(_tok(client, "carlos@planta.com"))).status_code == 403
    r = client.put("/v1/org/permisos", json=nuevos, headers=_auth(_tok(client, "alessia@planta.com")))
    assert r.status_code == 200 and r.json()["permisos"]["activos"] == ["admin"]


# ── WebSocket ─────────────────────────────────────────────────────────────────
def test_ws_sin_token_rechazado(client):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/v1/fleet/live"):
            pass


def test_ws_con_token_entrega_snapshot_de_su_org(client):
    tok = _tok(client, "alessia@planta.com")
    with client.websocket_connect(f"/v1/fleet/live?token={tok}") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "snapshot"
        nombres = {m["id"] for m in msg["data"]["maquinas"]}
        assert "Bomba de agua cruda" in nombres
