from app.ingest.sources.mqtt_source import MqttSource


def _src():
    # __init__ solo lee variables de entorno; no abre red ni importa paho.
    return MqttSource()


def test_solo_vib():
    l = _src()._normalizar("nexia/Bomba/vibracion", b'{"rms_mm_s": 4.2}')
    assert l is not None
    assert l.vib == 4.2
    assert l.metricas == {}


def test_vib_mas_extra_passthrough():
    payload = b'{"rms_mm_s": 4.2, "temperatura": 71.5, "rpm": 1480, "magnitud_rara": 9, "ts": 123}'
    l = _src()._normalizar("nexia/Bomba/vibracion", payload)
    assert l.vib == 4.2
    # passthrough de cualquier clave numérica que no sea vib/ts/id:
    assert l.metricas == {"temperatura": 71.5, "rpm": 1480.0, "magnitud_rara": 9.0}
    assert "ts" not in l.metricas and "rms_mm_s" not in l.metricas
    assert l.ts == 123


def test_maquina_id_desde_topic():
    l = _src()._normalizar("nexia/Compresor/vibracion", b'{"vib": 3.0}')
    assert l.maquina_id == "Compresor"


def test_sin_vib_es_none():
    assert _src()._normalizar("nexia/Bomba/vibracion", b'{"temperatura": 50}') is None


def test_payload_invalido_es_none():
    assert _src()._normalizar("nexia/Bomba/vibracion", b"no-json") is None
