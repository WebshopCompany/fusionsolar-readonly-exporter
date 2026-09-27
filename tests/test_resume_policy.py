from datetime import date

from fusionsolar_readonly_exporter.exporter import resource_day_needed
from fusionsolar_readonly_exporter.storage import RunStore


def test_partial_first_run_skips_only_durable_completed_resource_days(tmp_path):
    store = RunStore.create(tmp_path / "out", tmp_path / "state")
    completed = date(2026, 1, 1)
    missing = date(2026, 1, 2)
    resource = "history:dev-synthetic"
    store.mark_resource_day_complete(resource, completed)
    assert resource_day_needed(store, resource, completed, refresh_from=None) is False
    assert resource_day_needed(store, resource, missing, refresh_from=None) is True


def test_incremental_overlap_refetches_completed_days_deterministically(tmp_path):
    store = RunStore.create(tmp_path / "out", tmp_path / "state")
    resource = "history:dev-synthetic"
    day = date(2026, 1, 10)
    store.mark_resource_day_complete(resource, day)
    assert resource_day_needed(store, resource, day, refresh_from=date(2026, 1, 8)) is True
