from app.constants import COSTO_HORA_PARADA, HORAS_PARADA_TIPICA
from app.simulation import FleetEngine

SEED = {"id": "T-1", "sensor": "s", "sector": "x", "base": 2.0}


def test_savings_y_registro_arrancan_en_cero():
    snap = FleetEngine(flota_seed=[SEED]).snapshot()
    assert snap["savings"] == {"ahorroMes": 0.0, "paradasEvitadas": 0}
    assert snap["registro"] == {"real": 0, "falsa": 0, "nc": 0}


def test_etiquetar_real_suma_el_costo_de_esa_maquina():
    e = FleetEngine(flota_seed=[{**SEED, "costoParadaHora": 2000}])
    e.alertas = [{"id": "a1", "maquina": "T-1"}]
    e.etiquetar("a1", "real")
    snap = e.snapshot()
    assert snap["savings"]["ahorroMes"] == 2000 * HORAS_PARADA_TIPICA
    assert snap["savings"]["paradasEvitadas"] == 1
    assert snap["registro"]["real"] == 1


def test_etiquetar_real_usa_el_nominal_si_no_hay_costo():
    e = FleetEngine(flota_seed=[SEED])
    e.alertas = [{"id": "a1", "maquina": "T-1"}]
    e.etiquetar("a1", "real")
    assert e.snapshot()["savings"]["ahorroMes"] == COSTO_HORA_PARADA * HORAS_PARADA_TIPICA


def test_etiquetar_falsa_no_suma_ahorro_pero_cuenta():
    e = FleetEngine(flota_seed=[SEED])
    e.alertas = [{"id": "a1", "maquina": "T-1"}]
    e.etiquetar("a1", "falsa")
    snap = e.snapshot()
    assert snap["savings"] == {"ahorroMes": 0.0, "paradasEvitadas": 0}
    assert snap["registro"]["falsa"] == 1


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
