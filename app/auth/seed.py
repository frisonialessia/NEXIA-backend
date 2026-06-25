# ──────────────────────────────────────────────────────────────────────────
# SEMILLA DE AUTH · 2 organizaciones de demo (para mostrar el aislamiento)
# ──────────────────────────────────────────────────────────────────────────
# FASE 2a: orgs/usuarios en memoria. La contraseña de demo se hashea al arrancar
# (no se guarda en claro). En FASE 2b esto se sustituye por una carga desde la BD.
#
# ⚠️ Datos de DEMO. La contraseña común es solo para el entorno de pruebas.
# ──────────────────────────────────────────────────────────────────────────

from ..constants import FLOTA
from .models import Organizacion, Usuario
from .passwords import hash_password
from .roles import matriz_por_defecto
from .store import AuthStore

# Contraseña común de los usuarios de demo (entorno de pruebas).
PASSWORD_DEMO = "demo1234"

# Flota propia de la 2ª org: nombres distintos para que el aislamiento se vea.
FLOTA_AGUAS_DEL_VALLE = [
    {"id": "Bomba captación río", "sensor": "vib-av-01", "sector": "Captación", "base": 2.4, "esc": "sano"},
    {"id": "Soplante aireación",  "sensor": "vib-av-02", "sector": "Biológico",  "base": 3.1, "esc": "degradando"},
    {"id": "Bomba de fangos",     "sensor": "vib-av-03", "sector": "Deshidratación", "base": 2.0, "esc": "sano"},
]


def _semilla_demo() -> tuple[list[Organizacion], list[Usuario]]:
    norte = Organizacion(
        id="org-planta-norte", nombre="Planta Norte", slug="planta-norte",
        permisos=matriz_por_defecto(), flota_seed=list(FLOTA),
    )
    aguas = Organizacion(
        id="org-aguas-valle", nombre="Aguas del Valle", slug="aguas-del-valle",
        permisos=matriz_por_defecto(), flota_seed=FLOTA_AGUAS_DEL_VALLE,
    )
    h = hash_password(PASSWORD_DEMO)  # mismo hash reutilizable (misma contraseña demo)
    usuarios = [
        Usuario("u-norte-admin",    norte.id, "Alessia",   "alessia@planta.com", "admin",    h),
        Usuario("u-norte-jefe",     norte.id, "Carlos",    "carlos@planta.com",  "jefe",     h),
        Usuario("u-norte-tecnico",  norte.id, "Roberto",   "roberto@planta.com", "tecnico",  h),
        Usuario("u-norte-operador", norte.id, "Luis",      "luis@planta.com",    "operador", h),
        Usuario("u-norte-lectura",  norte.id, "Auditoría", "audit@planta.com",   "lectura",  h),
        Usuario("u-aguas-admin",    aguas.id, "Admin AV",  "admin@aguasdelvalle.com",   "admin",   h),
        Usuario("u-aguas-tecnico",  aguas.id, "Técnico AV","tecnico@aguasdelvalle.com", "tecnico", h),
    ]
    return [norte, aguas], usuarios


def cargar_store() -> AuthStore:
    """Construye el AuthStore. Hoy, la semilla de demo; mañana (2b), desde la BD."""
    orgs, usuarios = _semilla_demo()
    return AuthStore(orgs, usuarios)
