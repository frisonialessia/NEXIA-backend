from app.contract import SnapshotDTO
from app.simulation import FleetEngine

LEGACY_MAQUINA = (
    "id", "sensor", "sector", "tipo", "base", "umbral", "estado", "prob",
    "expected", "ritmoDia", "horasOp", "hist", "esc", "calib",
)


def test_snapshot_valida_en_modo_sim():
    snap = FleetEngine().snapshot()
    dto = SnapshotDTO.model_validate(snap)
    assert len(dto.maquinas) == len(snap["maquinas"])


def test_campos_legacy_presentes():
    snap = FleetEngine().snapshot()
    for m in snap["maquinas"]:
        for campo in LEGACY_MAQUINA:
            assert campo in m


def test_snapshot_valida_con_telemetria_parcial():
    eng = FleetEngine()
    eng.crear({"id": "T-1", "sensor": "s", "sector": "x", "base": 2.0})
    eng.ingest("T-1", 2.0, None, {"temp": 50.0, "rpm": 1500})
    dto = SnapshotDTO.model_validate(eng.snapshot())  # no debe lanzar
    maq = next(m for m in dto.maquinas if m.id == "T-1")
    assert maq.telemetria is None  # incompleta (2 de 5) → no se expone tipada


def test_snapshot_valida_con_telemetria_completa():
    eng = FleetEngine()
    eng.crear({"id": "T-2", "sensor": "s", "sector": "x", "base": 2.0})
    full = {"temp": 50.0, "pres": 4.0, "rpm": 1500, "caudal": 90.0, "corriente": 12.0}
    eng.ingest("T-2", 2.0, None, full)
    dto = SnapshotDTO.model_validate(eng.snapshot())
    maq = next(m for m in dto.maquinas if m.id == "T-2")
    assert maq.telemetria is not None
    assert maq.telemetria.caudal == 90.0
    assert maq.kpis is not None and maq.kpis.eficiencia is not None
