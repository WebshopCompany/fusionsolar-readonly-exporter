from pathlib import Path

import pytest

import fusionsolar_readonly_exporter.stage1 as stage1


class FakeAuth:
    def __init__(
        self, transport, username, password, data_host, captcha_provider=None, work_dir=None
    ):
        self.transport = transport
        self.username = username
        self.password = password
        self.data_host = data_host
        self.company_dn = None

    def login(self):
        self.company_dn = "company-private-id"
        self.username = ""
        self.password = ""


class SafeClient:
    realtime_calls = 0

    def __init__(self, auth):
        self.auth = auth

    def plants(self):
        return [{"dn": "plant-private-id", "name": "Home"}]

    def devices(self, parent_dn=None):
        assert parent_dn in {"plant-private-id", None}
        return [{"dn": "device-private-id", "name": "Battery storage"}]

    def realtime(self, device_dn):
        assert device_dn == "device-private-id"
        type(self).realtime_calls += 1
        return {"data": {"privateTelemetry": 123.4}}

    def history(self, *args, **kwargs):
        raise AssertionError("Stage-1 must not invoke history")

    def plant_balance(self, *args, **kwargs):
        raise AssertionError("Stage-1 must not invoke historical plant balance")


class DummyTransport:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


def _run(monkeypatch, tmp_path: Path, *, host="region01eu5.fusionsolar.huawei.com"):
    monkeypatch.setattr(stage1, "ReadOnlyTransport", DummyTransport)
    monkeypatch.setattr(stage1, "AuthenticatedSession", FakeAuth)
    SafeClient.realtime_calls = 0
    monkeypatch.setattr(stage1, "FusionSolarReadClient", SafeClient)
    lines = []
    code = stage1.run_stage1(
        host,
        "private-user@example.invalid",
        "private-password-value",
        work_dir=tmp_path,
        output=lines.append,
    )
    return code, lines


def test_stage1_success_never_invokes_history_or_full_export(monkeypatch, tmp_path):
    import fusionsolar_readonly_exporter.exporter as exporter_module

    monkeypatch.setattr(
        exporter_module.Exporter,
        "run",
        lambda self: (_ for _ in ()).throw(AssertionError("full exporter invoked")),
    )
    code, lines = _run(monkeypatch, tmp_path)
    assert code == 0
    assert SafeClient.realtime_calls == 1
    assert "HISTORICAL_REQUESTS: 0" in lines
    assert "BACKFILL_STARTED: NO" in lines
    assert "STAGE1_RESULT: PASS" in lines


def test_stage1_diagnostics_do_not_expose_ids_credentials_or_telemetry(monkeypatch, tmp_path):
    code, lines = _run(monkeypatch, tmp_path)
    output = "\n".join(lines)
    assert code == 0
    for secret in (
        "private-user@example.invalid",
        "private-password-value",
        "plant-private-id",
        "device-private-id",
        "123.4",
        "region01eu5.fusionsolar.huawei.com",
    ):
        assert secret not in output
    assert "PLANT_COUNT: 1" in lines
    assert "DEVICE_COUNT: 1" in lines
    assert "DEVICE_CLASSES: battery" in lines


def test_invalid_host_fails_before_transport_or_auth(monkeypatch, tmp_path):
    monkeypatch.setattr(
        stage1,
        "ReadOnlyTransport",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("transport created")),
    )
    lines = []
    code = stage1.run_stage1(
        "https://example.org/private",
        "private-user",
        "private-password",
        work_dir=tmp_path,
        output=lines.append,
    )
    assert code == 3
    assert "HOST_VALIDATION: FAIL" in lines
    assert "AUTHENTICATION: NOT_ATTEMPTED" in lines
    assert "HISTORICAL_REQUESTS: 0" in lines


def test_stage1_source_has_no_full_export_or_history_execution_path():
    source = Path(stage1.__file__).read_text(encoding="utf-8")
    prohibited = (
        "Exporter(",
        "Exporter.run",
        ".history(",
        "plant_balance(",
        "--full",
        "RunStore",
        "package_zip",
    )
    assert not any(term in source for term in prohibited)


def test_main_invalid_host_never_prompts_for_credentials(monkeypatch):
    prompts = []

    def fake_input(prompt):
        prompts.append(prompt)
        return "https://example.org"

    monkeypatch.setattr("builtins.input", fake_input)
    monkeypatch.setattr(
        stage1.getpass,
        "getpass",
        lambda prompt: (_ for _ in ()).throw(AssertionError("password prompted")),
    )
    assert stage1.main([]) == 3
    assert prompts == ["FusionSolar browser host or URL: "]


def test_non_huawei_and_unsupported_host_classes_are_rejected():
    assert stage1._host_pattern_class("https://example.org") == "unknown"
    assert stage1._host_pattern_class("region01eu5.fusionsolar.huawei.com") == "region"
    with pytest.raises(Exception):
        stage1._login_host_for("region01la5.fusionsolar.huawei.com")
