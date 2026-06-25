# ──────────────────────────────────────────────────────────────────────────
# ROLES Y MATRIZ DE PERMISOS
# ──────────────────────────────────────────────────────────────────────────
# La matriz vive POR ORGANIZACIÓN (se siembra con estos defaults y el admin de
# la org la edita). El frontend es la fuente de la verdad del DISEÑO; estos
# defaults son su espejo EXACTO. 11 permisos × 5 roles.
# ──────────────────────────────────────────────────────────────────────────

# Roles válidos (los únicos que acepta el contrato de login).
ROLES = ("admin", "jefe", "tecnico", "operador", "lectura")

# permiso -> roles que lo tienen por defecto. NO reordenar sin tocar el frontend.
PERMISOS_DEFAULT: dict[str, tuple[str, ...]] = {
    "produccion":    ("admin", "jefe", "tecnico"),
    "auditar":       ("admin", "jefe", "tecnico", "operador"),  # etiquetar alertas
    "mantenimiento": ("admin", "jefe", "tecnico"),              # reparar máquina
    "activos":       ("admin", "tecnico"),                      # CRUD de máquinas
    "plantas":       ("admin", "jefe"),
    "facturacion":   ("admin",),
    "conexiones":    ("admin", "tecnico"),
    "usuarios":      ("admin",),
    "ajustesPlanta": ("admin", "jefe"),
    "exportar":      ("admin", "jefe", "tecnico", "lectura"),
    "tendencia":     ("admin", "jefe"),
}

# Lista canónica de permisos (en orden).
PERMISOS = tuple(PERMISOS_DEFAULT)


def matriz_por_defecto() -> dict[str, set[str]]:
    """Copia FRESCA de la matriz (set de roles por permiso) para sembrar una
    organización. Cada org recibe la suya para poder editarla sin afectar a otras."""
    return {permiso: set(roles) for permiso, roles in PERMISOS_DEFAULT.items()}


def matriz_a_json(permisos: dict[str, set[str]]) -> dict[str, list[str]]:
    """Serializa la matriz a JSON (listas ordenadas por el orden canónico de roles)."""
    return {p: [r for r in ROLES if r in permisos.get(p, set())] for p in PERMISOS}
