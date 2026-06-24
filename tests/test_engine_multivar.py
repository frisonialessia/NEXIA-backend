from app.simulation import FleetEngine, crear_maquina, procesar_lectura

SEED = {"id": "T-1", "sensor": "s", "sector": "x", "base": 2.0, "esc": "sano"}


def _maquina():
    return crear_maquina(SEED)  # calib=0 → evalúa de inmediato


def test_ingest_almacena_metricas_passthrough():
    eng = FleetEngine()
    eng.crear(SEED)
    eng.ingest("T-1", 2.1, None, {"temperatura": 55.0, "magnitud_rara": 99, "vib": 9.9, "texto": "n/a"})
    m = eng._maquina("T-1")
    assert m.metricas["temperatura"] == 55.0
    assert m.metricas["magnitud_rara"] == 99.0  # passthrough: cualquier numérica
    assert "vib" not in m.metricas              # el pivote nunca va en metricas
    assert "texto" not in m.metricas            # no numérica → descartada


def test_metricas_no_numericas_se_descartan():
    m = _maquina()
    procesar_lectura(m, 2.0, None, {"temperatura": "n/a", "rpm": "1500"})
    assert "temperatura" not in m.metricas
    assert m.metricas["rpm"] == 1500.0  # coacciona una str numérica


def test_carry_forward_entre_lecturas():
    m = _maquina()
    procesar_lectura(m, 2.0, None, {"temperatura": 50.0})
    procesar_lectura(m, 2.1, None, {"rpm": 1500})
    assert m.metricas == {"temperatura": 50.0, "rpm": 1500.0}


def test_to_dto_omite_metricas_si_vacio():
    assert "metricas" not in _maquina().to_dto()


def test_to_dto_incluye_metricas_si_presente():
    m = _maquina()
    procesar_lectura(m, 2.0, None, {"temperatura": 50.0})
    assert m.to_dto()["metricas"]["temperatura"] == 50.0


def test_hist_byte_shape_sin_metricas():
    # Sin magnitudes extra, el punto de historial es EXACTAMENTE el de siempre.
    m = _maquina()
    procesar_lectura(m, 2.0)
    assert set(m.hist[-1].keys()) == {"t", "v", "exp"}


def test_hist_incluye_m_con_metricas():
    m = _maquina()
    procesar_lectura(m, 2.0, None, {"rpm": 1500})
    assert m.hist[-1]["m"]["rpm"] == 1500.0


def test_fsm_no_cambia_con_metricas():
    # Misma serie de vibración con y sin métricas → MISMO camino de estados:
    # las magnitudes extra no tocan la detección.
    serie = [2.0, 8.0, 8.0, 8.0, 8.0, 8.0]

    def correr(con_metricas):
        m = _maquina()
        out = []
        for v in serie:
            metricas = {"temperatura": 60.0, "rpm": 1500} if con_metricas else None
            procesar_lectura(m, v, None, metricas)
            out.append(m.estado)
        return out

    assert correr(True) == correr(False)
    assert "CRITICAL_ALERT" in correr(False)  # la serie sí dispara crítico


def test_engine_snapshot_sin_metricas_por_defecto(monkeypatch):
    # El snapshot del motor (lo que difunde el WebSocket) NO gana claves nuevas
    # en modo simulado por defecto: garantía de payload intacto.
    monkeypatch.delenv("NEXIA_SIM_MULTIVAR", raising=False)
    eng = FleetEngine()
    for m in eng.snapshot()["maquinas"]:
        assert "metricas" not in m
        for p in m["hist"]:
            assert set(p.keys()) == {"t", "v", "exp"}
