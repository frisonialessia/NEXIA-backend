from app.ingest.source import Lectura


def test_metricas_por_defecto_vacio():
    assert Lectura("M1", 2.0).metricas == {}


def test_metricas_no_comparten_estado():
    # Guarda contra el clásico bug de default mutable compartido entre instancias.
    a = Lectura("M1", 2.0)
    b = Lectura("M2", 3.0)
    a.metricas["temperatura"] = 50.0
    assert b.metricas == {}


def test_valores_incluye_pivote_y_extra():
    l = Lectura("M1", 2.0, metricas={"temperatura": 50.0, "rpm": 1500.0})
    assert l.valores() == {"vib": 2.0, "temperatura": 50.0, "rpm": 1500.0}


def test_valores_sin_extra():
    assert Lectura("M1", 2.0).valores() == {"vib": 2.0}
