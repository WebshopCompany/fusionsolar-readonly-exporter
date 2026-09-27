from datetime import date
import os
import stat
import zipfile

from fusionsolar_readonly_exporter.state import refresh_from_for_run, start_for_run
from fusionsolar_readonly_exporter.storage import RunStore


def test_incremental_overlap():
    state = {"last_successful_day": "2026-01-10"}
    assert start_for_run(state, date(2026, 1, 1), full=False, overlap_days=2) == date(2026, 1, 8)
    assert refresh_from_for_run(state, date(2026, 1, 1), full=False, overlap_days=2) == date(
        2026, 1, 8
    )
    assert start_for_run(state, date(2026, 1, 1), full=True, overlap_days=2) == date(2026, 1, 1)
    assert refresh_from_for_run(state, date(2026, 1, 1), full=True, overlap_days=2) is None


def test_resource_day_completion_is_bound_to_active_workspace(tmp_path):
    output_root = tmp_path / "out"
    state_root = tmp_path / "state"
    store = RunStore.create(output_root, state_root)
    day = date(2026, 1, 1)
    key = "history:dev-synthetic"
    store.save_resource_day_checkpoint(key, day, {"telemetry": []})
    store.mark_resource_day_complete(key, day)
    reopened = RunStore.create(output_root, state_root)
    assert reopened.root == store.root
    assert reopened.resource_day_complete(key, day)
    assert reopened.has_resource_day_checkpoint(key, day)
    assert "raw-device-id" not in (state_root / "state.json").read_text()


def test_manifest_hash_zip_and_private_checkpoint_boundary(tmp_path):
    store = RunStore.create(tmp_path / "out", tmp_path / "state")
    (store.root / "validation" / "x.json").write_text("{}")
    store.save_resource_day_checkpoint("history:dev-synthetic", date(2026, 1, 1), {"telemetry": []})
    manifest = store.manifest({"test": True})
    assert any(
        item["path"] == "validation/x.json" and len(item["sha256"]) == 64
        for item in manifest["files"]
    )
    assert not any(".checkpoints" in item["path"] for item in manifest["files"])
    archive = store.package_zip()
    with zipfile.ZipFile(archive) as handle:
        names = handle.namelist()
    assert not any(name.startswith("state/") for name in names)
    assert not any(name.startswith(".checkpoints/") for name in names)


def test_private_permissions_on_posix(tmp_path):
    store = RunStore.create(tmp_path / "out", tmp_path / "state")
    (store.root / "validation" / "x.json").write_text("{}")
    archive = store.package_zip()
    if os.name != "nt":
        assert stat.S_IMODE(store.root.stat().st_mode) == 0o700
        assert stat.S_IMODE((store.state_root / "state.json").stat().st_mode) == 0o600
        assert stat.S_IMODE((store.root / "validation" / "x.json").stat().st_mode) == 0o600
        assert stat.S_IMODE(archive.stat().st_mode) == 0o600


def test_pseudonym_is_stable_and_not_raw_id(tmp_path):
    store = RunStore.create(tmp_path / "out", tmp_path / "state")
    a = store.pseudonym("synthetic-device-123")
    b = store.pseudonym("synthetic-device-123")
    assert a == b and "synthetic-device-123" not in a


def test_redaction_removes_sensitive_values():
    from fusionsolar_readonly_exporter.storage import _redact

    value = {
        "username": "owner",
        "password": "secret",
        "nested": {"token": "abc", "safe": "yes"},
    }
    redacted = _redact(value)
    assert redacted["username"] == "<redacted>"
    assert redacted["password"] == "<redacted>"
    assert redacted["nested"]["token"] == "<redacted>"
    assert redacted["nested"]["safe"] == "yes"
