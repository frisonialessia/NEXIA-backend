from app.constants import PERFIL_EQUIPO
from app.simulation import _telemetria_simulada, crear_maquina, procesar_lectura


def _maq(tipo):
    return crear_maquina({"id": tipo.upper(), "sensor": "s", "sector": "x", "base": 2.0, "tipo": tipo})


def _por_campo(alertas, campo):
    return [a for a in alertas if a.get("campo") == campo]


def test_bases_sanas_por_tipo():
    for tipo, p in PERFIL_EQUIPO.items():
        t = _telemetria_simulada(_maq(tipo), 2.0)  # v == expected → máquina sana
        assert abs(t["temp"] - p["temp"]) <= 3, tipo
        assert abs(t["pres"] - p["pres"]) <= 0.3, tipo
        assert abs(t["caudal"] - p["caudal"]) <= 3, tipo
        assert abs(t["rpm"] - p["rpm"]) <= 12, tipo
        assert abs(t["corriente"] - p["kw"] * 1.8) <= 0.6, tipo  # corriente ≈ kW × 1.8


def test_bajo_fallo_sube_temp_corriente_y_baja_rpm_caudal():
    m = _maq("bomba")
    sano = _telemetria_simulada(m, m.expected)
    fallo = _telemetria_simulada(m, m.expected + 6)  # severidad máxima
    assert fallo["temp"] > sano["temp"] + 10
    assert fallo["corriente"] > sano["corriente"]
    assert fallo["rpm"] < sano["rpm"]
    assert fallo["caudal"] < sano["caudal"]


def test_compresor_sano_a_82_no_alarma():
    # 82 °C es la base SANA de un compresor; su umbral es 98 → no debe alarmar.
    alertas = procesar_lectura(_maq("compresor"), 2.0, None, {"temp": 82.0})
    assert _por_campo(alertas, "temperatura") == []


def test_ventilador_sano_a_06_bar_no_alarma():
    # 0.6 bar es la base SANA de un ventilador; su rango es [0.2, 1.2].
    alertas = procesar_lectura(_maq("ventilador"), 2.0, None, {"pres": 0.6})
    assert _por_campo(alertas, "presion") == []


def test_compresor_si_alarma_por_sobretemperatura_real():
    alertas = procesar_lectura(_maq("compresor"), 2.0, None, {"temp": 99.0})  # > 98
    temp_alertas = _por_campo(alertas, "temperatura")
    assert len(temp_alertas) == 1
    assert temp_alertas[0]["limite"] == 98.0
