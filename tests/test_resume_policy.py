from datetime import date

from fusionsolar_readonly_exporter.exporter import resource_day_needed
from fusionsolar_readonly_exporter.storage import RunStore


def test_partial_run_reopens_workspace_and_reuses_only_checkpointed_days(tmp_path):
    output_root = tmp_path / "out"
    state_root = tmp_path / "state"
    store = RunStore.create(output_root, state_root)
    completed = date(2026, 1, 1)
    missing = date(2026, 1, 2)
    resource = "history:dev-synthetic"
    payload = {"telemetry": [{"timestamp_utc": "2026-01-01T00:00:00+00:00"}]}
    store.save_resource_day_checkpoint(resource, completed, payload)
    store.mark_resource_day_complete(resource, completed)

    reopened = RunStore.create(output_root, state_root)
    assert reopened.root == store.root
    assert resource_day_needed(reopened, resource, completed, refresh_from=None) is False
    assert reopened.load_resource_day_checkpoint(resource, completed) == payload
    assert resource_day_needed(reopened, resource, missing, refresh_from=None) is True


def test_completion_flag_without_checkpoint_is_never_trusted(tmp_path):
    store = RunStore.create(tmp_path / "out", tmp_path / "state")
    resource = "history:dev-synthetic"
    day = date(2026, 1, 10)
    store.mark_resource_day_complete(resource, day)
    assert resource_day_needed(store, resource, day, refresh_from=None) is True
    assert resource_day_needed(store, resource, day, refresh_from=date(2026, 1, 8)) is True
