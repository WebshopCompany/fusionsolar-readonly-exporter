import pytest

pytest.importorskip("pyarrow")

from fusionsolar_readonly_exporter.storage import RunStore


def test_csv_and_real_parquet_are_both_written(tmp_path):
    store = RunStore.create(tmp_path / "out", tmp_path / "state")
    csv_path, parquet_path = store.write_table(
        "normalised/synthetic",
        [
            {
                "timestamp_utc": "2026-01-01T00:00:00+00:00",
                "signal_id": "synthetic",
                "raw_value": 1.0,
            }
        ],
    )
    assert csv_path.stat().st_size > 0
    assert parquet_path.read_bytes()[:4] == b"PAR1"
