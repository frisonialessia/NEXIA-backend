# Fixtures compartidas. La suite no necesita hardware ni dependencias de
# ingesta (paho-mqtt / asyncua): todo lo real se prueba con dobles o con las
# funciones puras del adaptador.

import pytest

from app.simulation import FleetEngine

# Semilla de máquina de prueba (calib=0 al crearla con crear_maquina → evalúa ya).
SEED = {"id": "T-1", "sensor": "vib-test", "sector": "Test", "base": 2.0, "esc": "sano"}


@pytest.fixture
def engine():
    """FleetEngine recién calentado (estado de demo en memoria)."""
    return FleetEngine()


@pytest.fixture
def seed():
    return dict(SEED)
