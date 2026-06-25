from app.ingest.source import Lectura


def test_campos_telemetria_por_defecto_none():
    l = Lectura("M1", 2.0)
    assert l.temp is None and l.pres is None and l.rpm is None
    assert l.caudal is None and l.corriente is None


def test_telemetria_vacia_sin_extra():
    assert Lectura("M1", 2.0).telemetria() == {}


def test_telemetria_desde_campos_nombrados():
    l = Lectura("M1", 2.0, temp=70.0, rpm=1480)
    assert l.telemetria() == {"temp": 70.0, "rpm": 1480.0}


def test_valores_incluye_pivote_y_telemetria():
    l = Lectura("M1", 2.0, temp=50.0, rpm=1500.0)
    assert l.valores() == {"vib": 2.0, "temp": 50.0, "rpm": 1500.0}


def test_valores_sin_extra():
    assert Lectura("M1", 2.0).valores() == {"vib": 2.0}


def test_telemetria_nunca_incluye_vib():
    assert "vib" not in Lectura("M1", 2.0, temp=70.0).telemetria()
