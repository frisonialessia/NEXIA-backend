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


def test_snapshot_valida_con_multivar():
    eng = FleetEngine()
    eng.crear({"id": "T-1", "sensor": "s", "sector": "x", "base": 2.0})
    eng.ingest("T-1", 2.0, None, {"temperatura": 50.0, "rpm": 1500})
    # No debe lanzar: el contrato acepta las magnitudes extra (campos opcionales).
    dto = SnapshotDTO.model_validate(eng.snapshot())
    maq = next(m for m in dto.maquinas if m.id == "T-1")
    assert maq.metricas == {"temperatura": 50.0, "rpm": 1500.0}
