from app.constants import COSTO_HORA_PARADA, HORAS_PARADA_TIPICA
from app.persistence import dump_engine, restaurar_engine
from app.simulation import FleetEngine

SEED = {"id": "T-1", "sensor": "s", "sector": "x", "base": 2.0}


def _con_alerta(e, maquina="T-1", aid="a1"):
    """Inyecta una alerta activa realista: presente en alertas Y en historial
    (el libro), como en el flujo real."""
    a = {"id": aid, "maquina": maquina, "estado": "Pendiente"}
    e.alertas = [a]
    e.historial = [a]
    return e


def test_savings_y_registro_arrancan_en_cero():
    snap = FleetEngine(flota_seed=[SEED]).snapshot()
    assert snap["savings"] == {"ahorroMes": 0.0, "paradasEvitadas": 0}
    assert snap["registro"] == {"real": 0, "falsa": 0, "nc": 0}


def test_etiquetar_real_suma_el_costo_de_esa_maquina():
    e = _con_alerta(FleetEngine(flota_seed=[{**SEED, "costoParadaHora": 2000}]))
    e.etiquetar("a1", "real")
    snap = e.snapshot()
    assert snap["savings"]["ahorroMes"] == 2000 * HORAS_PARADA_TIPICA
    assert snap["savings"]["paradasEvitadas"] == 1
    assert snap["registro"]["real"] == 1


def test_etiquetar_real_usa_el_nominal_si_no_hay_costo():
    e = _con_alerta(FleetEngine(flota_seed=[SEED]))
    e.etiquetar("a1", "real")
    assert e.snapshot()["savings"]["ahorroMes"] == COSTO_HORA_PARADA * HORAS_PARADA_TIPICA


def test_etiquetar_falsa_no_suma_ahorro_pero_cuenta():
    e = _con_alerta(FleetEngine(flota_seed=[SEED]))
    e.etiquetar("a1", "falsa")
    snap = e.snapshot()
    assert snap["savings"] == {"ahorroMes": 0.0, "paradasEvitadas": 0}
    assert snap["registro"]["falsa"] == 1


def test_reetiquetar_es_idempotente():
    # ROI derivado del libro → corregir una etiqueta no duplica.
    e = _con_alerta(FleetEngine(flota_seed=[{**SEED, "costoParadaHora": 1000}]))
    e.etiquetar("a1", "real")
    assert e.snapshot()["savings"]["paradasEvitadas"] == 1
    e.etiquetar("a1", "falsa")  # corrección
    snap = e.snapshot()
    assert snap["savings"] == {"ahorroMes": 0.0, "paradasEvitadas": 0}
    assert snap["registro"] == {"real": 0, "falsa": 1, "nc": 0}


def test_roi_sobrevive_via_historial_persistido():
    e1 = _con_alerta(FleetEngine(flota_seed=[{**SEED, "costoParadaHora": 1000}]))
    e1.etiquetar("a1", "real")
    e2 = FleetEngine(flota_seed=[SEED])
    restaurar_engine(e2, dump_engine(e1))  # "reinicio"
    assert e2.snapshot()["savings"]["ahorroMes"] == 1000 * HORAS_PARADA_TIPICA
    assert any(h.get("veredicto") == "real" for h in e2.historial)


def test_costo_por_maquina_se_expone_en_el_dto():
    e = FleetEngine(flota_seed=[{**SEED, "costoParadaHora": 3333}])
    assert e.snapshot()["maquinas"][0]["costoParadaHora"] == 3333


def test_costo_efectivo_nominal_en_el_dto():
    e = FleetEngine(flota_seed=[SEED])
    assert e.snapshot()["maquinas"][0]["costoParadaHora"] == COSTO_HORA_PARADA


def test_editar_actualiza_el_costo_por_maquina():
    e = FleetEngine(flota_seed=[SEED])
    e.editar("T-1", {"costoParadaHora": 999})
    assert e.snapshot()["maquinas"][0]["costoParadaHora"] == 999
