from pathlib import Path

from app.ingest.sources.csv_source import CsvReplaySource

_INGEST = Path(__file__).resolve().parents[1] / "app" / "ingest"
SAMPLE = _INGEST / "sample_readings.csv"
SAMPLE_MULTI = _INGEST / "sample_readings_multi.csv"


def test_csv_3col_backcompat():
    # El CSV de 3 columnas de siempre sigue funcionando, sin métricas extra.
    filas = CsvReplaySource(str(SAMPLE))._leer_filas()
    assert len(filas) > 0
    assert all(l.metricas == {} for l in filas)
    assert filas[0].vib > 0


def test_csv_multivar_lee_metricas():
    filas = CsvReplaySource(str(SAMPLE_MULTI))._leer_filas()
    primera = filas[0]
    assert primera.maquina_id == "Bomba de agua cruda"
    assert "temperatura" in primera.metricas
    assert "rpm" in primera.metricas
    assert "vib" not in primera.metricas  # el pivote viaja en el campo vib


def test_csv_columna_desconocida_se_ignora(tmp_path):
    p = tmp_path / "r.csv"
    p.write_text(
        "maquina_id,vib,ts,temperatura,desconocida\nM1,2.0,,50.0,99\n",
        encoding="utf-8",
    )
    filas = CsvReplaySource(str(p))._leer_filas()
    assert filas[0].metricas == {"temperatura": 50.0}


def test_csv_celda_no_numerica_se_descarta(tmp_path):
    p = tmp_path / "r.csv"
    p.write_text(
        "maquina_id,vib,ts,temperatura,rpm\nM1,2.0,,n/a,1500\n",
        encoding="utf-8",
    )
    filas = CsvReplaySource(str(p))._leer_filas()
    assert filas[0].metricas == {"rpm": 1500.0}
