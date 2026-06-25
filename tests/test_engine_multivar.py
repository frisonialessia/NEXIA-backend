from app.simulation import FleetEngine, crear_maquina, procesar_lectura

SEED = {"id": "T-1", "sensor": "s", "sector": "x", "base": 2.0, "esc": "sano"}


def _maquina():
    return crear_maquina(SEED)  # calib=0 → evalúa de inmediato


def test_ingest_almacena_telemetria_filtrada():
    eng = FleetEngine()
    eng.crear(SEED)
    eng.ingest("T-1", 2.1, None, {"temp": 55.0, "desconocida": 99, "vib": 9.9})
    m = eng._maquina("T-1")
    assert m.telemetria.temp == 55.0
    assert m.telemetria.presentes() == {"temp": 55.0}  # desconocida/vib descartadas


def test_telemetria_no_numerica_se_descarta():
    m = _maquina()
    procesar_lectura(m, 2.0, None, {"temp": "n/a", "rpm": "1500"})
    assert m.telemetria.temp is None
    assert m.telemetria.rpm == 1500.0  # coacciona una str numérica


def test_carry_forward_entre_lecturas():
    m = _maquina()
    procesar_lectura(m, 2.0, None, {"temp": 50.0})
    procesar_lectura(m, 2.1, None, {"rpm": 1500})
    assert m.telemetria.presentes() == {"temp": 50.0, "rpm": 1500.0}


def test_to_dto_omite_extras_si_vacio():
    dto = _maquina().to_dto()
    assert "telemetria" not in dto
    assert "kpis" not in dto


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


def test_hist_siempre_t_v_exp():
    # El punto de historial es SIEMPRE {t,v,exp} (la telemetría va aparte).
    m = _maquina()
    procesar_lectura(m, 2.0, None, {"temp": 60.0, "rpm": 1500})
    assert set(m.hist[-1].keys()) == {"t", "v", "exp"}


def test_fsm_no_cambia_con_telemetria():
    # Misma serie de vibración con y sin telemetría (en rango) → MISMO camino de
    # estados: la telemetría no toca la detección de vibración.
    serie = [2.0, 8.0, 8.0, 8.0, 8.0, 8.0]

    def correr(con_tele):
        m = _maquina()
        out = []
        for v in serie:
            tele = {"temp": 60.0, "rpm": 1500} if con_tele else None
            procesar_lectura(m, v, None, tele)
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
        assert "telemetria" not in m
        assert "kpis" not in m
        for p in m["hist"]:
            assert set(p.keys()) == {"t", "v", "exp"}
