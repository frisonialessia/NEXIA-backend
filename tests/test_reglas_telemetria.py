# Reglas de alerta multi-variable (NO vibración): sobretemperatura y presión
# fuera de rango. Edge-triggered e independientes de la FSM de vibración.

from app.contract import AlertaDTO
from app.simulation import crear_maquina, procesar_lectura

SEED = {"id": "T-1", "sensor": "s", "sector": "x", "base": 2.0, "esc": "sano"}


def _maquina():
    return crear_maquina(SEED)  # calib=0 → evalúa de inmediato


def _por_campo(alertas, campo):
    return [a for a in alertas if a.get("campo") == campo]


def test_sobretemperatura_dispara_alerta():
    m = _maquina()
    alertas = procesar_lectura(m, 2.0, None, {"temp": 85.0})
    temp_alertas = _por_campo(alertas, "temperatura")
    assert len(temp_alertas) == 1
    a = temp_alertas[0]
    assert a["valor"] == 85.0
    assert a["limite"] == 80.0
    AlertaDTO.model_validate(a)  # sigue siendo una AlertaDTO válida


def test_temperatura_edge_trigger_no_repite():
    m = _maquina()
    procesar_lectura(m, 2.0, None, {"temp": 85.0})            # dispara
    alertas = procesar_lectura(m, 2.0, None, {"temp": 86.0})  # sigue caliente
    assert _por_campo(alertas, "temperatura") == []           # no repite


def test_temperatura_rearma_tras_volver_al_rango():
    m = _maquina()
    procesar_lectura(m, 2.0, None, {"temp": 85.0})            # dispara
    procesar_lectura(m, 2.0, None, {"temp": 70.0})            # vuelve al rango
    alertas = procesar_lectura(m, 2.0, None, {"temp": 90.0})  # vuelve a disparar
    assert len(_por_campo(alertas, "temperatura")) == 1


def test_presion_alta_dispara_alerta():
    m = _maquina()
    alertas = procesar_lectura(m, 2.0, None, {"pres": 12.0})
    pres_alertas = _por_campo(alertas, "presion")
    assert len(pres_alertas) == 1
    assert pres_alertas[0]["limite"] == 10.0
    AlertaDTO.model_validate(pres_alertas[0])


def test_presion_baja_dispara_alerta():
    m = _maquina()
    alertas = procesar_lectura(m, 2.0, None, {"pres": 0.5})
    pres_alertas = _por_campo(alertas, "presion")
    assert len(pres_alertas) == 1
    assert pres_alertas[0]["limite"] == 1.0


def test_telemetria_en_rango_no_alerta():
    m = _maquina()
    assert procesar_lectura(m, 2.0, None, {"temp": 60.0, "pres": 4.0}) == []


def test_regla_temp_no_altera_fsm_vibracion():
    # Temperatura alta con vibración normal: hay alerta de temp pero la FSM
    # (que pivota solo en vibración) sigue STABLE y no hay alerta de vibración.
    m = _maquina()
    alertas = procesar_lectura(m, 2.0, None, {"temp": 95.0})
    assert m.estado == "STABLE"
    assert len(_por_campo(alertas, "temperatura")) == 1
    assert _por_campo(alertas, "vibracion") == []
