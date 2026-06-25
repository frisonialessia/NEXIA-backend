from app.auth.roles import PERMISOS, ROLES, matriz_a_json, matriz_por_defecto


def test_son_11_permisos_y_5_roles():
    assert len(PERMISOS) == 11
    assert set(ROLES) == {"admin", "jefe", "tecnico", "operador", "lectura"}


def test_matriz_defaults_exactos():
    m = matriz_por_defecto()
    assert m["produccion"] == {"admin", "jefe", "tecnico"}
    assert m["auditar"] == {"admin", "jefe", "tecnico", "operador"}
    assert m["mantenimiento"] == {"admin", "jefe", "tecnico"}
    assert m["activos"] == {"admin", "tecnico"}  # NO jefe
    assert m["plantas"] == {"admin", "jefe"}
    assert m["facturacion"] == {"admin"}
    assert m["conexiones"] == {"admin", "tecnico"}
    assert m["usuarios"] == {"admin"}
    assert m["ajustesPlanta"] == {"admin", "jefe"}
    assert m["exportar"] == {"admin", "jefe", "tecnico", "lectura"}  # lectura SÍ exporta
    assert m["tendencia"] == {"admin", "jefe"}


def test_cada_org_tiene_copia_independiente():
    a, b = matriz_por_defecto(), matriz_por_defecto()
    a["activos"].add("operador")
    assert "operador" not in b["activos"]


def test_matriz_a_json_orden_canonico():
    j = matriz_a_json(matriz_por_defecto())
    assert j["activos"] == ["admin", "tecnico"]
    assert j["exportar"] == ["admin", "jefe", "tecnico", "lectura"]
    assert set(j) == set(PERMISOS)
