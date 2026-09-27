from __future__ import annotations

from datetime import date, datetime, timezone
import json
import zipfile

import pytest

pytest.importorskip("pyarrow")

from fusionsolar_readonly_exporter.auth import AuthenticatedSession
from fusionsolar_readonly_exporter.client import FusionSolarReadClient
from fusionsolar_readonly_exporter.exporter import Exporter
from fusionsolar_readonly_exporter.storage import RunStore

TODAY = date(2026, 1, 3)
EARLIEST = date(2026, 1, 1)


class FakeResponse:
    status_code = 200
    headers = {}
    content = b"{}"
    text = "{}"

    def __init__(self, payload=None):
        self.payload = {} if payload is None else payload

    def json(self):
        return self.payload


class ScriptedTransport:
    def __init__(self):
        self.last_response_sha256 = "a" * 64
        self.history_days = []
        self.plant_days = []

    def request(self, method, url, purpose, **kwargs):
        if purpose == "auth.login-page":
            return FakeResponse()
        if purpose == "auth.pubkey":
            return FakeResponse({"enableEncrypt": False})
        if purpose == "auth.login-v2":
            return FakeResponse({})
        if purpose == "session.keepalive":
            return FakeResponse()
        if purpose == "topology.company":
            return FakeResponse({"data": {"moDn": "synthetic-company"}})
        raise AssertionError(f"unexpected auth request: {purpose}")

    @staticmethod
    def _day_from_ms(value):
        return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc).date()

    def post_json(self, url, purpose, **kwargs):
        if purpose == "topology.plants":
            return {
                "data": {
                    "list": [{"dn": "plant-synthetic", "name": "Synthetic plant"}]
                }
            }
        if purpose == "alarms.current":
            return {"data": []}
        raise AssertionError(f"unexpected POST JSON: {purpose}")

    def get_json(self, url, purpose, **kwargs):
        params = kwargs.get("params") or {}
        if purpose == "topology.devices":
            return {"data": [{"dn": "battery-synthetic", "name": "Battery"}]}
        if purpose == "device.realtime":
            return {
                "data": {
                    "signals": [
                        {"id": "30007", "name": "SOC", "unit": "%", "value": "50"},
                        {
                            "id": "30005",
                            "name": "Charge/Discharge power",
                            "unit": "kW",
                            "value": "1",
                        },
                    ]
                }
            }
        if purpose == "device.kpi":
            return {
                "data": {
                    "signals": [
                        {
                            "id": "10007",
                            "name": "SOH",
                            "unit": "%",
                            "value": "95",
                        }
                    ]
                }
            }
        if purpose == "battery.module":
            return {"data": {"signals": []}}
        if purpose == "device.history":
            day = self._day_from_ms(params["date"])
            self.history_days.append(day)
            signal_ids = params["signalIds"]
            if day < EARLIEST:
                return {"data": {signal: {"data": []} for signal in signal_ids}}
            stamp = int(
                datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp()
                * 1000
            )
            return {
                "data": {
                    "30001": {
                        "name": "Charging power",
                        "unit": "kW",
                        "data": [{"x": stamp, "y": "0.1"}],
                    },
                    "30002": {
                        "name": "Discharging power",
                        "unit": "kW",
                        "data": [{"x": stamp, "y": "0.0"}],
                    },
                    "30005": {
                        "name": "Charge/Discharge power",
                        "unit": "kW",
                        "data": [{"x": stamp, "y": "1.0"}],
                    },
                    "30006": {
                        "name": "Battery voltage",
                        "unit": "V",
                        "data": [{"x": stamp, "y": "400"}],
                    },
                    "30007": {
                        "name": "SOC",
                        "unit": "%",
                        "data": [{"x": stamp, "y": "50"}],
                    },
                }
            }
        if purpose == "plant.balance":
            day = self._day_from_ms(params["queryTime"])
            self.plant_days.append(day)
            if day < EARLIEST:
                return {"data": {"xAxis": []}}
            return {
                "data": {
                    "xAxis": [f"{day.isoformat()} 00:00"],
                    "productPower": [1.0],
                    "chargeAndDisChargePower": [-1.0],
                    "totalProductPower": 0.2,
                }
            }
        raise AssertionError(f"unexpected GET JSON: {purpose}")


def test_whole_mocked_run_and_incremental_rerun(monkeypatch, tmp_path):
    import fusionsolar_readonly_exporter.exporter as exporter_module

    monkeypatch.setattr(exporter_module, "station_today", lambda: TODAY)
    transport = ScriptedTransport()
    auth = AuthenticatedSession(
        transport,
        "synthetic-user",
        "synthetic-password",
        "region01eu5.fusionsolar.huawei.com",
        work_dir=tmp_path / "state",
    )
    auth.login()
    client = FusionSolarReadClient(auth)

    state_dir = tmp_path / "state"
    first_store = RunStore.create(tmp_path / "out-first", state_dir)
    first_zip = Exporter(
        client,
        first_store,
        full=True,
        overlap_days=1,
        history_max_years=1,
        progress=lambda _message: None,
    ).run()
    assert first_zip.exists()
    assert first_store.state()["last_successful_day"] == TODAY.isoformat()
    assert first_store.state()["resource_days"]

    coverage = json.loads(
        (first_store.root / "validation" / "coverage.json").read_text()
    )
    assert coverage["requested_range"]["start"] == EARLIEST.isoformat()
    assert coverage["per_signal"]

    capabilities = json.loads(
        (first_store.root / "validation" / "capabilities.json").read_text()
    )
    assert any(item["outcome"] == "available" for item in capabilities["findings"])

    with zipfile.ZipFile(first_zip) as archive:
        names = set(archive.namelist())
    assert "manifest.json" in names
    assert "validation/coverage.json" in names
    assert "normalised/telemetry.parquet" in names

    second_store = RunStore.create(tmp_path / "out-second", state_dir)
    second_zip = Exporter(
        client,
        second_store,
        full=False,
        overlap_days=1,
        history_max_years=1,
        progress=lambda _message: None,
    ).run()
    assert second_zip.exists()
    second_coverage = json.loads(
        (second_store.root / "validation" / "coverage.json").read_text()
    )
    assert second_coverage["requested_range"]["start"] == date(2026, 1, 2).isoformat()
    assert second_store.state()["last_successful_day"] == TODAY.isoformat()
