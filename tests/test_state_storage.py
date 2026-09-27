from datetime import date
import zipfile
from fusionsolar_readonly_exporter.state import start_for_run
from fusionsolar_readonly_exporter.storage import RunStore


def test_incremental_overlap():
    assert start_for_run(
        {"last_successful_day": "2026-01-10"}, date(2026, 1, 1), full=False, overlap_days=2
    ) == date(2026, 1, 8)
    assert start_for_run(
        {"last_successful_day": "2026-01-10"}, date(2026, 1, 1), full=True, overlap_days=2
    ) == date(2026, 1, 1)


def test_manifest_hash_and_zip_excludes_state(tmp_path):
    store = RunStore.create(tmp_path / "out", tmp_path / "state")
    (store.root / "validation" / "x.json").write_text("{}")
    m = store.manifest({"test": True})
    assert any(x["path"] == "validation/x.json" and len(x["sha256"]) == 64 for x in m["files"])
    z = store.package_zip()
    with zipfile.ZipFile(z) as f:
        names = f.namelist()
    assert not any(n.startswith("state/") for n in names)


def test_pseudonym_is_stable_and_not_raw_id(tmp_path):
    store = RunStore.create(tmp_path / "out", tmp_path / "state")
    a = store.pseudonym("synthetic-device-123")
    b = store.pseudonym("synthetic-device-123")
    assert a == b and "synthetic-device-123" not in a


def test_redaction_removes_sensitive_values():
    from fusionsolar_readonly_exporter.storage import _redact

    value = {"username": "owner", "password": "secret", "nested": {"token": "abc", "safe": "yes"}}
    redacted = _redact(value)
    assert redacted["username"] == "<redacted>"
    assert redacted["password"] == "<redacted>"
    assert redacted["nested"]["token"] == "<redacted>"
    assert redacted["nested"]["safe"] == "yes"
