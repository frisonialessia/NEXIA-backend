import asyncio
import json

from app.ingest.sources.opcua_source import OpcUaSource, agrupar_por_maquina


def test_agrupar_por_maquina():
    nodos = [
        {"node": "n1", "maquina": "A", "campo": "vib"},
        {"node": "n2", "maquina": "A", "campo": "temperatura"},
        {"node": "n3", "maquina": "B", "campo": "vib"},
    ]
    grupos = agrupar_por_maquina(nodos)
    assert set(grupos) == {"A", "B"}
    assert len(grupos["A"]) == 2
    assert len(grupos["B"]) == 1


# ── Dobles de prueba: un cliente OPC UA falso, sin servidor ni asyncua ────────
class _FakeNode:
    def __init__(self, valor):
        self._valor = valor

    async def read_value(self):
        if isinstance(self._valor, Exception):
            raise self._valor
        return self._valor


class _FakeClient:
    def __init__(self, valores):
        self._valores = valores  # node_id -> valor (o Exception para simular fallo)

    def get_node(self, node_id):
        return _FakeNode(self._valores[node_id])


def _correr(src, client):
    capturadas = []

    async def cap(lectura):
        capturadas.append(lectura)

    src.on_reading(cap)

    async def run():
        await src._leer_todos(client)

    asyncio.run(run())
    return capturadas


def _src(monkeypatch, nodos):
    monkeypatch.setenv("OPCUA_NODES", json.dumps(nodos))
    return OpcUaSource()


def test_una_lectura_multivar_por_maquina(monkeypatch):
    nodos = [
        {"node": "v", "maquina": "A", "campo": "vib"},
        {"node": "t", "maquina": "A", "campo": "temperatura"},
        {"node": "r", "maquina": "A", "campo": "rpm"},
    ]
    src = _src(monkeypatch, nodos)
    cap = _correr(src, _FakeClient({"v": 4.0, "t": 60.0, "r": 1500.0}))
    assert len(cap) == 1
    assert cap[0].maquina_id == "A"
    assert cap[0].vib == 4.0
    assert cap[0].metricas == {"temperatura": 60.0, "rpm": 1500.0}


def test_sin_vib_no_emite(monkeypatch):
    nodos = [{"node": "t", "maquina": "A", "campo": "temperatura"}]
    src = _src(monkeypatch, nodos)
    cap = _correr(src, _FakeClient({"t": 60.0}))
    assert cap == []  # el motor pivota en vib; sin vib no se emite


def test_nodo_ilegible_se_omite_solo_esa_magnitud(monkeypatch):
    nodos = [
        {"node": "v", "maquina": "A", "campo": "vib"},
        {"node": "t", "maquina": "A", "campo": "temperatura"},
    ]
    src = _src(monkeypatch, nodos)
    cap = _correr(src, _FakeClient({"v": 4.0, "t": RuntimeError("boom")}))
    assert len(cap) == 1
    assert cap[0].vib == 4.0
    assert cap[0].metricas == {}  # temp ilegible se cae, la máquina igual emite


def test_campo_passthrough(monkeypatch):
    nodos = [
        {"node": "v", "maquina": "A", "campo": "vib"},
        {"node": "x", "maquina": "A", "campo": "magnitud_rara"},
    ]
    src = _src(monkeypatch, nodos)
    cap = _correr(src, _FakeClient({"v": 4.0, "x": 99.0}))
    assert len(cap) == 1
    # passthrough: cualquier 'campo' configurado entra como métrica.
    assert cap[0].metricas == {"magnitud_rara": 99.0}
