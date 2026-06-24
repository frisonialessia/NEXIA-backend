from app.ingest.sources.mqtt_source import MqttSource


def _src():
    # __init__ solo lee variables de entorno; no abre red ni importa paho.
    return MqttSource()


def test_solo_vib():
    l = _src()._normalizar("nexia/Bomba/vibracion", b'{"rms_mm_s": 4.2}')
    assert l is not None
    assert l.vib == 4.2
    assert l.metricas == {}


def test_vib_mas_extra():
    payload = b'{"rms_mm_s": 4.2, "temperatura": 71.5, "rpm": 1480, "desconocida": 9}'
    l = _src()._normalizar("nexia/Bomba/vibracion", payload)
    assert l.vib == 4.2
    assert l.metricas == {"temperatura": 71.5, "rpm": 1480.0}


def test_maquina_id_desde_topic():
    l = _src()._normalizar("nexia/Compresor/vibracion", b'{"vib": 3.0}')
    assert l.maquina_id == "Compresor"


def test_sin_vib_es_none():
    assert _src()._normalizar("nexia/Bomba/vibracion", b'{"temperatura": 50}') is None


def test_payload_invalido_es_none():
    assert _src()._normalizar("nexia/Bomba/vibracion", b"no-json") is None
