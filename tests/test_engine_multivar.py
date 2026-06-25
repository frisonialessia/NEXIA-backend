from app.simulation import FleetEngine, crear_maquina, procesar_lectura

SEED = {"id": "T-1", "sensor": "s", "sector": "x", "base": 2.0, "esc": "sano"}


def _maquina():
    return crear_maquina(SEED)  # calib=0 → evalúa de inmediato


def test_ingest_almacena_metricas_filtradas():
    eng = FleetEngine()
    eng.crear(SEED)
    eng.ingest("T-1", 2.1, None, {"temp": 55.0, "desconocida": 99, "vib": 9.9})
    m = eng._maquina("T-1")
    assert m.metricas["temp"] == 55.0
    assert "desconocida" not in m.metricas  # fuera del vocabulario canónico
    assert "vib" not in m.metricas          # el pivote nunca va en metricas


def test_metricas_no_numericas_se_descartan():
    m = _maquina()
    procesar_lectura(m, 2.0, None, {"temp": "n/a", "rpm": "1500"})
    assert "temp" not in m.metricas
    assert m.metricas["rpm"] == 1500.0  # coacciona una str numérica


def test_carry_forward_entre_lecturas():
    m = _maquina()
    procesar_lectura(m, 2.0, None, {"temp": 50.0})
    procesar_lectura(m, 2.1, None, {"rpm": 1500})
    assert m.metricas == {"temp": 50.0, "rpm": 1500.0}


def test_to_dto_omite_extras_si_vacio():
    dto = _maquina().to_dto()
    assert "metricas" not in dto
    assert "telemetria" not in dto
    assert "kpis" not in dto


def test_to_dto_incluye_metricas_si_presente():
    m = _maquina()
    procesar_lectura(m, 2.0, None, {"temp": 50.0})
    assert m.to_dto()["metricas"]["temp"] == 50.0


def test_telemetria_solo_si_completa():
    m = _maquina()
    # Con 4 de 5 magnitudes, la telemetría tipada NO se emite todavía.
    procesar_lectura(m, 2.0, None, {"temp": 50.0, "pres": 4.0, "rpm": 1500, "caudal": 90})
    assert m.to_dto().get("telemetria") is None
    # Al completar la quinta, aparece la vista tipada con las 5.
    procesar_lectura(m, 2.0, None, {"corriente": 12.0})
    tele = m.to_dto()["telemetria"]
    assert set(tele) == {"temp", "pres", "rpm", "caudal", "corriente"}
    assert tele["corriente"] == 12.0


def test_kpis_aparece_con_corriente_y_caudal():
    m = _maquina()
    procesar_lectura(m, 2.0, None, {"corriente": 12.0, "caudal": 90.0})
    kpi = m.to_dto()["kpis"]
    assert "energiaKw" in kpi and "eficiencia" in kpi and "oee" in kpi


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
    # Misma serie de vibración con y sin métricas (en rango) → MISMO camino de
    # estados: la telemetría no toca la detección de vibración.
    serie = [2.0, 8.0, 8.0, 8.0, 8.0, 8.0]

    def correr(con_metricas):
        m = _maquina()
        out = []
        for v in serie:
            metricas = {"temp": 60.0, "rpm": 1500} if con_metricas else None
            procesar_lectura(m, v, None, metricas)
            out.append(m.estado)
        return out

    assert correr(True) == correr(False)
    assert "CRITICAL_ALERT" in correr(False)  # la serie sí dispara crítico


def test_sim_telemetria_por_defecto(monkeypatch):
    # Decisión: el simulador genera telemetría POR DEFECTO (multi-variable vivo).
    monkeypatch.delenv("NEXIA_SIM_MULTIVAR", raising=False)
    eng = FleetEngine()
    for m in eng.snapshot()["maquinas"]:
        assert set(m["telemetria"]) == {"temp", "pres", "rpm", "caudal", "corriente"}
        assert "kpis" in m


def test_sim_telemetria_desactivable(monkeypatch):
    # Con NEXIA_SIM_MULTIVAR=0 el payload es el de antes de multi-variable.
    monkeypatch.setenv("NEXIA_SIM_MULTIVAR", "0")
    eng = FleetEngine()
    for m in eng.snapshot()["maquinas"]:
        assert "metricas" not in m
        assert "telemetria" not in m
        for p in m["hist"]:
            assert set(p.keys()) == {"t", "v", "exp"}
