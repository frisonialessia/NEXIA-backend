from app import kpis


def test_energia_trifasica():
    val = kpis.energia_kw(10.0, 400.0)
    assert val == round(3 ** 0.5 * 400 * 10 * 0.85 / 1000, 3)


def test_energia_monofasica():
    val = kpis.energia_kw(10.0, 230.0, trifasico=False)
    assert val == round(230 * 10 * 0.85 / 1000, 3)


def test_energia_invalida_es_none():
    assert kpis.energia_kw(0, 400) is None
    assert kpis.energia_kw(None, 400) is None
    assert kpis.energia_kw(10, 0) is None


def test_eficiencia():
    assert kpis.eficiencia(80, 100) == 80.0
    assert kpis.eficiencia(150, 100) == 100.0  # acotada a 100%
    assert kpis.eficiencia(50, 0) is None       # evita división por cero


def test_oee():
    assert kpis.oee(0.9, 0.95, 0.99) == round(0.9 * 0.95 * 0.99 * 100, 1)
    assert kpis.oee(1.5, 1.0, 1.0) == 100.0     # factores acotados a 1
    assert kpis.oee(None, 0.9, 0.9) is None


def test_desde_valores():
    out = kpis.desde_valores({"vib": 2.0, "corriente": 10.0, "voltaje": 400.0})
    assert "energiaKw" in out
    assert kpis.desde_valores({"vib": 2.0}) == {}  # sin corriente → sin KPI
