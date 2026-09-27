from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

from .client import FusionSolarReadClient
from .normalise import history_rows, plant_balance_rows, realtime_rows
from .signals import BATTERY_HISTORY_SIGNALS, INVERTER_HISTORY_SIGNALS, module_signal_ids
from .state import start_for_run
from .storage import RunStore
from .timeutil import station_today
from .validate import (
    opposite_sign_relationship,
    point_integration_vs_vendor_aggregates,
    validate_telemetry,
)


@dataclass
class Capability:
    device_class: str
    device_pseudonym: str
    historical_signal_ids: list[str]
    historical: bool
    current: bool
    notes: str = ""


def _classify(device: dict[str, Any]) -> str:
    text = " ".join(
        str(device.get(key, "")) for key in ("mocTypeName", "name", "devType", "type")
    ).lower()
    if "battery" in text or "energy storage" in text or "storage" in text:
        return "battery"
    if "inverter" in text:
        return "inverter"
    if "meter" in text or "power sensor" in text or "sensor" in text:
        return "meter"
    return "device"


def _dn(device: dict[str, Any]) -> str | None:
    for key in ("dn", "deviceDn", "id"):
        if device.get(key):
            return str(device[key])
    return None


def _history_has_data(payload: dict[str, Any]) -> bool:
    data = payload.get("data", payload) if isinstance(payload, dict) else {}
    if not isinstance(data, dict):
        return False
    for value in data.values():
        if isinstance(value, dict) and (value.get("data") or value.get("values")):
            return True
    return False


def discover_earliest(
    fetch_day: Callable[[date], dict[str, Any]],
    latest: date,
    lower_hint: date | None = None,
    max_years: int = 15,
) -> date:
    """Probe backwards conservatively and linearly scan the retention boundary."""

    limit = latest - timedelta(days=max_years * 366)

    def has(day: date) -> bool:
        try:
            return _history_has_data(fetch_day(day))
        except Exception:
            return False

    if lower_hint and lower_hint >= limit and has(lower_hint):
        return lower_hint

    newest_with: date | None = None
    for back in range(0, 32):
        candidate = latest - timedelta(days=back)
        if candidate < limit:
            break
        if has(candidate):
            newest_with = candidate
            break

    if newest_with is None:
        candidate = latest - timedelta(days=60)
        while candidate >= limit:
            if has(candidate):
                newest_with = candidate
                break
            candidate -= timedelta(days=60)

    if newest_with is None:
        return latest

    step = timedelta(days=30)
    current = newest_with - step
    consecutive_empty = 0
    oldest_with = newest_with
    first_empty: date | None = None

    while current >= limit:
        if has(current):
            oldest_with = current
            consecutive_empty = 0
            first_empty = None
        else:
            consecutive_empty += 1
            if first_empty is None:
                first_empty = current
            if consecutive_empty >= 2:
                break
        current -= step

    if first_empty is None:
        return max(limit, oldest_with)

    day = max(limit, current)
    while day <= oldest_with:
        if has(day):
            return day
        day += timedelta(days=1)
    return oldest_with


class Exporter:
    def __init__(
        self,
        client: FusionSolarReadClient,
        store: RunStore,
        *,
        full: bool = False,
        overlap_days: int = 2,
        progress: Callable[[str], None] = print,
    ):
        self.client = client
        self.store = store
        self.full = full
        self.overlap_days = overlap_days
        self.progress = progress
        self.telemetry: list[dict[str, Any]] = []
        self.aggregates: list[dict[str, Any]] = []
        self.current: list[dict[str, Any]] = []
        self.capabilities: list[Capability] = []

    def run(self) -> Path:
        self.progress("Discovering plant...")
        plants = self.client.plants()
        if not plants:
            raise RuntimeError("No FusionSolar plants were returned")

        self.progress("Discovering devices...")
        devices: list[dict[str, Any]] = []
        for plant in plants:
            plant_dn = _dn(plant)
            if not plant_dn:
                continue
            try:
                devices.extend(self.client.devices(plant_dn))
            except Exception as exc:
                self._finding(
                    "capability_probe_errors.jsonl",
                    {"class": "plant-devices", "error": type(exc).__name__},
                )

        if not devices:
            devices = self.client.devices()
        devices = list({_dn(device): device for device in devices if _dn(device)}.values())

        self.progress("Probing available signals...")
        today = station_today()
        initial_state = self.store.state()
        global_earliest = today
        per_device: dict[str, tuple[str, str, list[str], date]] = {}

        for device in devices:
            device_dn = _dn(device)
            if not device_dn:
                continue
            device_class = _classify(device)
            pseudo = self.store.pseudonym(device_dn)
            known = (
                BATTERY_HISTORY_SIGNALS
                if device_class == "battery"
                else INVERTER_HISTORY_SIGNALS
                if device_class == "inverter"
                else []
            )
            current_available = False

            try:
                realtime = self.client.realtime(device_dn)
                raw_hash = self.client.t.last_response_sha256
                current_rows = realtime_rows(
                    realtime,
                    device_pseudonym=pseudo,
                    device_class=device_class,
                    source_endpoint="device.realtime",
                    raw_sha256=raw_hash,
                )
                self.current.extend(current_rows)
                current_available = bool(current_rows)
            except Exception:
                current_rows = []

            if not known and current_rows:
                signal_ids = sorted({row["signal_id"] for row in current_rows})[:100]
                found: list[str] = []
                for index in range(0, len(signal_ids), 20):
                    chunk = signal_ids[index : index + 20]
                    try:
                        payload = self.client.history(device_dn, chunk, today)
                    except Exception:
                        continue
                    data = payload.get("data", {}) if isinstance(payload, dict) else {}
                    found.extend(
                        str(key)
                        for key, value in data.items()
                        if isinstance(value, dict) and (value.get("data") or value.get("values"))
                    )
                known = sorted(set(found))

            if known:
                self.progress(f"Determining historical range for {device_class}...")
                earliest = discover_earliest(
                    lambda day, dn=device_dn, ids=known: self.client.history(dn, ids, day),
                    today,
                )
                per_device[device_dn] = (device_class, pseudo, known, earliest)
                global_earliest = min(global_earliest, earliest)

            self.capabilities.append(
                Capability(
                    device_class=device_class,
                    device_pseudonym=pseudo,
                    historical_signal_ids=known,
                    historical=bool(known),
                    current=current_available,
                    notes=(
                        "module/pack/SOH fields are current-only unless historical "
                        "probing proves otherwise"
                    ),
                )
            )

        plant_ranges: dict[str, tuple[str, date]] = {}
        for plant in plants:
            plant_dn = _dn(plant)
            if not plant_dn:
                continue
            pseudo = self.store.pseudonym(plant_dn)

            def plant_probe(day: date, station_dn: str = plant_dn) -> dict[str, Any]:
                raw = self.client.plant_balance(station_dn, day)
                data = raw.get("data", {}) if isinstance(raw, dict) else {}
                return {"data": {"balance": {"data": data.get("xAxis") or []}}}

            earliest = discover_earliest(plant_probe, today)
            plant_ranges[plant_dn] = (pseudo, earliest)
            global_earliest = min(global_earliest, earliest)

        start = start_for_run(
            initial_state,
            global_earliest,
            full=self.full,
            overlap_days=self.overlap_days,
        )
        self.progress(f"Backfilling from {start.isoformat()}...")

        day = start
        watermark_blocked = False
        completed_through: date | None = None

        while day <= today:
            day_errors = 0

            for plant_dn, (pseudo, earliest) in plant_ranges.items():
                if day < earliest:
                    continue
                try:
                    raw = self.client.plant_balance(plant_dn, day)
                    raw_hash = self.client.t.last_response_sha256
                    telemetry, aggregates = plant_balance_rows(
                        raw,
                        device_pseudonym=pseudo,
                        day=day,
                        raw_sha256=raw_hash,
                    )
                    self.telemetry.extend(telemetry)
                    self.aggregates.extend(aggregates)
                except Exception as exc:
                    day_errors += 1
                    self._finding(
                        "acquisition_errors.jsonl",
                        {
                            "date": day.isoformat(),
                            "class": "plant",
                            "error": type(exc).__name__,
                        },
                    )

            for device_dn, (
                device_class,
                pseudo,
                signal_ids,
                earliest,
            ) in per_device.items():
                if day < earliest:
                    continue
                try:
                    raw = self.client.history(device_dn, signal_ids, day)
                    raw_hash = self.client.t.last_response_sha256
                    self.telemetry.extend(
                        history_rows(
                            raw,
                            device_pseudonym=pseudo,
                            device_class=device_class,
                            endpoint="device.history",
                            raw_sha256=raw_hash,
                        )
                    )
                except Exception as exc:
                    day_errors += 1
                    self._finding(
                        "acquisition_errors.jsonl",
                        {
                            "date": day.isoformat(),
                            "class": device_class,
                            "error": type(exc).__name__,
                        },
                    )

            if day_errors:
                watermark_blocked = True
            else:
                completed_through = day
            day += timedelta(days=1)

        self.progress("Collecting current diagnostics...")
        for device in devices:
            device_dn = _dn(device)
            if not device_dn:
                continue
            device_class = _classify(device)
            pseudo = self.store.pseudonym(device_dn)

            try:
                realtime = self.client.realtime(device_dn)
                self.current.extend(
                    realtime_rows(
                        realtime,
                        device_pseudonym=pseudo,
                        device_class=device_class,
                        source_endpoint="device.realtime",
                        raw_sha256=self.client.t.last_response_sha256,
                    )
                )
            except Exception:
                pass

            try:
                alarms = self.client.alarms(device_dn)
                (self.store.root / "validation" / f"alarms_{pseudo}.json").write_text(
                    json.dumps(alarms, indent=2), encoding="utf-8"
                )
            except Exception:
                pass

            if device_class == "battery":
                try:
                    kpi = self.client.kpi(device_dn, ["10007"])
                    self.current.extend(
                        realtime_rows(
                            kpi,
                            device_pseudonym=pseudo,
                            device_class="battery",
                            source_endpoint="device.kpi",
                            raw_sha256=self.client.t.last_response_sha256,
                        )
                    )
                except Exception:
                    pass

                for module in ("1", "2", "3", "4"):
                    signal_ids = module_signal_ids(module)
                    if not signal_ids:
                        continue
                    try:
                        module_data = self.client.battery_module(device_dn, module, signal_ids)
                        self.current.extend(
                            realtime_rows(
                                module_data,
                                device_pseudonym=pseudo,
                                device_class=f"battery-module-{module}",
                                source_endpoint="battery.module",
                                raw_sha256=self.client.t.last_response_sha256,
                            )
                        )
                    except Exception:
                        pass

        self._deduplicate()
        self.progress("Validating...")
        self.store.write_table("normalised/telemetry", self.telemetry)
        self.store.write_table("normalised/daily_aggregates", self.aggregates)
        self.store.write_table("normalised/current_diagnostics", self.current)

        validation = validate_telemetry(self.telemetry)
        (self.store.root / "validation" / "telemetry_validation.json").write_text(
            json.dumps(validation, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        sign_report = opposite_sign_relationship(
            self.telemetry,
            a_endpoint="device.history",
            a_signal="30005",
            b_endpoint="plant.balance",
            b_signal="chargeAndDisChargePower",
        )
        (self.store.root / "validation" / "charge_discharge_sign_relationship.json").write_text(
            json.dumps(sign_report, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        integration = point_integration_vs_vendor_aggregates(self.telemetry, self.aggregates)
        (self.store.root / "derived" / "point_integration_vs_vendor_aggregates.json").write_text(
            json.dumps(integration, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        capabilities = [capability.__dict__ for capability in self.capabilities]
        (self.store.root / "validation" / "capabilities.json").write_text(
            json.dumps(capabilities, indent=2, sort_keys=True),
            encoding="utf-8",
        )

        self.store.manifest(
            {
                "exporter_version": "0.1.0",
                "full_rebuild": self.full,
                "incremental_overlap_days": self.overlap_days,
                "earliest_probed_day": global_earliest.isoformat(),
                "latest_requested_day": today.isoformat(),
                "capabilities": capabilities,
                "dependency": {
                    "fusion-solar-py": "0.1.2",
                    "inspected_upstream_commit": ("3e02b9f5d831673070e0f7ddac7d9db53ca2368b"),
                },
                "claim_boundary": (
                    "observational vendor telemetry; no SOH/RUL/degradation ground-truth claim"
                ),
            }
        )

        self.progress("Packaging...")
        archive = self.store.package_zip()

        if not watermark_blocked and completed_through is not None:
            final_state = self.store.state()
            previous_text = final_state.get("last_successful_day")
            previous = date.fromisoformat(previous_text) if previous_text else None
            if previous is None or completed_through > previous:
                final_state["last_successful_day"] = completed_through.isoformat()
            final_state["last_data_host"] = self.client.host
            self.store.save_state(final_state)

        self.progress(f"Done. {archive}")
        return archive

    def _finding(self, name: str, obj: dict[str, Any]) -> None:
        with (self.store.root / "validation" / name).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(obj, sort_keys=True) + "\n")

    def _deduplicate(self) -> None:
        def deduplicate(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
            seen: set[tuple[Any, ...]] = set()
            output: list[dict[str, Any]] = []
            for row in rows:
                key = tuple(
                    (key, json.dumps(row.get(key), sort_keys=True, default=str))
                    for key in sorted(row)
                )
                if key not in seen:
                    seen.add(key)
                    output.append(row)
            return output

        self.telemetry = deduplicate(self.telemetry)
        self.aggregates = deduplicate(self.aggregates)
        self.current = deduplicate(self.current)
