from app.ingest.source import Lectura


def test_metricas_por_defecto_vacio():
    assert Lectura("M1", 2.0).metricas == {}


def test_campos_nombrados_por_defecto_none():
    l = Lectura("M1", 2.0)
    assert l.temp is None and l.pres is None and l.rpm is None
    assert l.caudal is None and l.corriente is None


def test_metricas_no_comparten_estado():
    # Guarda contra el clásico bug de default mutable compartido entre instancias.
    a = Lectura("M1", 2.0)
    b = Lectura("M2", 3.0)
    a.metricas["temp"] = 50.0
    assert b.metricas == {}


def test_valores_incluye_pivote_y_extra():
    l = Lectura("M1", 2.0, metricas={"temp": 50.0, "rpm": 1500.0})
    assert l.valores() == {"vib": 2.0, "temp": 50.0, "rpm": 1500.0}


def test_valores_sin_extra():
    assert Lectura("M1", 2.0).valores() == {"vib": 2.0}


def test_campos_nombrados_se_funden_en_todas_metricas():
    l = Lectura("M1", 2.0, temp=70.0, rpm=1480)
    assert l.todas_metricas() == {"temp": 70.0, "rpm": 1480.0}
    assert l.valores() == {"vib": 2.0, "temp": 70.0, "rpm": 1480.0}


def test_dict_y_campos_nombrados_se_combinan():
    # El dict genérico y los campos tipados conviven; el campo nombrado gana.
    l = Lectura("M1", 2.0, metricas={"pres": 4.0, "temp": 10.0}, temp=70.0)
    assert l.todas_metricas() == {"pres": 4.0, "temp": 70.0}


def test_todas_metricas_nunca_incluye_vib():
    assert "vib" not in Lectura("M1", 2.0, temp=70.0).todas_metricas()
