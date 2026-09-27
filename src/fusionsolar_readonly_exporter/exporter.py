from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from typing import Any, Callable

from .client import FusionSolarReadClient
from .errors import ApiResponseError, AuthenticationError, ReadOnlyPolicyViolation
from .normalise import history_rows, plant_balance_rows, realtime_rows
from .signals import BATTERY_HISTORY_SIGNALS, INVERTER_HISTORY_SIGNALS, module_signal_ids
from .state import refresh_from_for_run, start_for_run
from .storage import RunStore
from .timeutil import station_today
from .validate import (
    opposite_sign_relationship,
    point_integration_vs_vendor_aggregates,
    validate_telemetry,
)


@dataclass
class HistoryBoundary:
    requested_start: date
    requested_end: date
    earliest_returned: date | None
    latest_returned: date | None
    probe_days: int
    empty_probe_days: list[date]
    error_probe_days: list[date]
    probable_retention_boundary: date | None

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        for key in (
            "requested_start",
            "requested_end",
            "earliest_returned",
            "latest_returned",
            "probable_retention_boundary",
        ):
            if value[key] is not None:
                value[key] = value[key].isoformat()
        value["empty_probe_days"] = [day.isoformat() for day in self.empty_probe_days]
        value["error_probe_days"] = [day.isoformat() for day in self.error_probe_days]
        return value


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
    return any(
        isinstance(value, dict) and (value.get("data") or value.get("values"))
        for value in data.values()
    )


def discover_history_boundary(
    fetch_day: Callable[[date], dict[str, Any]],
    latest: date,
    lower_hint: date | None = None,
    max_years: int = 15,
    sample_step_days: int = 30,
    boundary_empty_days: int = 14,
) -> HistoryBoundary:
    """Find oldest observed history without treating an empty outage as retention."""
    limit = latest - timedelta(days=max(1, max_years) * 366)
    outcomes: dict[date, bool | None] = {}

    def probe(day: date) -> bool | None:
        if day in outcomes:
            return outcomes[day]
        try:
            outcomes[day] = _history_has_data(fetch_day(day))
        except Exception:
            outcomes[day] = None
        return outcomes[day]

    if lower_hint and limit <= lower_hint <= latest:
        probe(lower_hint)
    for back in range(32):
        candidate = latest - timedelta(days=back)
        if candidate < limit:
            break
        probe(candidate)
    step = max(1, sample_step_days)
    cursor = latest - timedelta(days=step)
    while cursor >= limit:
        probe(cursor)
        cursor -= timedelta(days=step)
    probe(limit)

    positives = sorted(day for day, value in outcomes.items() if value is True)
    if not positives:
        return HistoryBoundary(
            limit,
            latest,
            None,
            None,
            len(outcomes),
            sorted(day for day, value in outcomes.items() if value is False),
            sorted(day for day, value in outcomes.items() if value is None),
            None,
        )

    oldest = positives[0]
    day = max(limit, oldest - timedelta(days=max(35, step + 5)))
    while day <= oldest:
        probe(day)
        day += timedelta(days=1)

    positives = sorted(day for day, value in outcomes.items() if value is True)
    earliest, newest = positives[0], positives[-1]
    boundary_start = max(limit, earliest - timedelta(days=max(1, boundary_empty_days)))
    day = boundary_start
    while day < earliest:
        probe(day)
        day += timedelta(days=1)
    boundary_values = [
        outcomes[probe_day]
        for probe_day in sorted(outcomes)
        if boundary_start <= probe_day < earliest
    ]
    probable = (
        earliest
        if len(boundary_values) >= boundary_empty_days
        and all(value is False for value in boundary_values)
        else None
    )
    return HistoryBoundary(
        limit,
        latest,
        earliest,
        newest,
        len(outcomes),
        sorted(day for day, value in outcomes.items() if value is False),
        sorted(day for day, value in outcomes.items() if value is None),
        probable,
    )


def discover_earliest(
    fetch_day: Callable[[date], dict[str, Any]],
    latest: date,
    lower_hint: date | None = None,
    max_years: int = 15,
) -> date:
    return (
        discover_history_boundary(fetch_day, latest, lower_hint, max_years).earliest_returned
        or latest
    )


def resource_day_needed(
    store: RunStore, resource: str, day: date, refresh_from: date | None
) -> bool:
    if refresh_from is not None and day >= refresh_from:
        return True
    return not store.resource_day_complete(resource, day)


def _failure_outcome(exc: Exception) -> str:
    if isinstance(exc, ReadOnlyPolicyViolation):
        return "policy_denied"
    if isinstance(exc, AuthenticationError):
        return "authentication_permission_issue"
    if isinstance(exc, ApiResponseError):
        return "parse_schema_failure"
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if status in {400, 404, 405}:
        return "unsupported_not_exposed"
    if status in {401, 403}:
        return "authentication_permission_issue"
    if status is not None or exc.__class__.__name__ in {
        "ConnectionError",
        "ConnectTimeout",
        "ReadTimeout",
        "Timeout",
        "HTTPError",
    }:
        return "http_api_failure"
    if isinstance(exc, (KeyError, TypeError, ValueError, json.JSONDecodeError)):
        return "parse_schema_failure"
    return "unexpected_failure"


def _row_extent(rows: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    timestamps = sorted(str(row["timestamp_utc"]) for row in rows if row.get("timestamp_utc"))
    return (timestamps[0], timestamps[-1]) if timestamps else (None, None)


class Exporter:
    def __init__(
        self,
        client: FusionSolarReadClient,
        store: RunStore,
        *,
        full: bool = False,
        overlap_days: int = 2,
        history_max_years: int = 15,
        progress: Callable[[str], None] = print,
    ):
        self.client = client
        self.store = store
        self.full = full
        self.overlap_days = overlap_days
        self.history_max_years = history_max_years
        self.progress = progress
        self.telemetry: list[dict[str, Any]] = []
        self.aggregates: list[dict[str, Any]] = []
        self.current: list[dict[str, Any]] = []
        self.capabilities: list[Capability] = []
        self.capability_findings: list[dict[str, Any]] = []
        self.history_boundaries: dict[str, dict[str, Any]] = {}
        self.coverage_requests: list[dict[str, Any]] = []

    def _finding(
        self,
        resource: str,
        operation: str,
        outcome: str,
        exc: Exception | None = None,
        detail: str | None = None,
    ) -> None:
        item: dict[str, Any] = {
            "resource": resource,
            "operation": operation,
            "outcome": outcome,
        }
        if exc is not None:
            item["error_type"] = type(exc).__name__
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status is not None:
                item["http_status"] = status
        if detail:
            item["detail"] = detail
        self.capability_findings.append(item)

    def _diagnostic_rows(
        self,
        resource: str,
        operation: str,
        fetch: Callable[[], dict[str, Any]],
        normalise: Callable[[dict[str, Any]], list[dict[str, Any]]],
    ) -> list[dict[str, Any]]:
        try:
            rows = normalise(fetch())
        except (ReadOnlyPolicyViolation, AuthenticationError) as exc:
            self._finding(resource, operation, _failure_outcome(exc), exc)
            raise
        except Exception as exc:
            self._finding(resource, operation, _failure_outcome(exc), exc)
            return []
        self._finding(resource, operation, "available" if rows else "empty_no_data")
        return rows

    def _record_coverage(
        self, resource: str, day: date, rows: list[dict[str, Any]], outcome: str
    ) -> None:
        earliest, latest = _row_extent(rows)
        self.coverage_requests.append(
            {
                "resource": resource,
                "requested_day": day.isoformat(),
                "outcome": outcome,
                "row_count": len(rows),
                "actual_earliest_returned_utc": earliest,
                "actual_latest_returned_utc": latest,
            }
        )

    def _coverage_report(self, start: date, end: date) -> dict[str, Any]:
        grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
        for row in self.telemetry:
            grouped[
                (
                    str(row.get("device_pseudonym")),
                    str(row.get("source_endpoint")),
                    str(row.get("signal_id")),
                )
            ].append(row)
        signals = []
        for (device, endpoint, signal), rows in sorted(grouped.items()):
            earliest, latest = _row_extent(rows)
            days = set()
            for row in rows:
                try:
                    days.add(
                        datetime.fromisoformat(str(row["timestamp_local"])).date().isoformat()
                    )
                except (KeyError, TypeError, ValueError):
                    continue
            signals.append(
                {
                    "device_pseudonym": device,
                    "source_endpoint": endpoint,
                    "signal_id": signal,
                    "rows": len(rows),
                    "days_with_data": len(days),
                    "actual_earliest_returned_utc": earliest,
                    "actual_latest_returned_utc": latest,
                }
            )
        return {
            "requested_range": {"start": start.isoformat(), "end": end.isoformat()},
            "history_boundaries": self.history_boundaries,
            "resource_day_requests": self.coverage_requests,
            "per_signal": signals,
            "boundary_note": (
                "Empty probe days, probe errors, observed history and probable retention "
                "boundaries are distinct. A probable boundary is not vendor-confirmed retention."
            ),
        }

    def _probe_device(
        self, device: dict[str, Any], today: date
    ) -> tuple[str, str, list[str], HistoryBoundary | None] | None:
        device_dn = _dn(device)
        if not device_dn:
            return None
        device_class = _classify(device)
        pseudo = self.store.pseudonym(device_dn)
        known = (
            list(BATTERY_HISTORY_SIGNALS)
            if device_class == "battery"
            else list(INVERTER_HISTORY_SIGNALS)
            if device_class == "inverter"
            else []
        )
        current_rows = self._diagnostic_rows(
            pseudo,
            "device.realtime",
            lambda: self.client.realtime(device_dn),
            lambda payload: realtime_rows(
                payload,
                device_pseudonym=pseudo,
                device_class=device_class,
                source_endpoint="device.realtime",
                raw_sha256=self.client.t.last_response_sha256,
            ),
        )
        self.current.extend(current_rows)

        if not known and current_rows:
            found: list[str] = []
            signal_ids = sorted({row["signal_id"] for row in current_rows})[:100]
            for index in range(0, len(signal_ids), 20):
                chunk = signal_ids[index : index + 20]
                try:
                    payload = self.client.history(device_dn, chunk, today)
                except Exception as exc:
                    self._finding(pseudo, "history.capability-probe", _failure_outcome(exc), exc)
                    if isinstance(exc, (ReadOnlyPolicyViolation, AuthenticationError)):
                        raise
                    continue
                data = payload.get("data", {}) if isinstance(payload, dict) else {}
                found.extend(
                    str(key)
                    for key, value in data.items()
                    if isinstance(value, dict) and (value.get("data") or value.get("values"))
                )
            known = sorted(set(found))

        boundary = None
        if known:
            boundary = discover_history_boundary(
                lambda day: self.client.history(device_dn, known, day),
                today,
                max_years=self.history_max_years,
            )
            self.history_boundaries[f"history:{pseudo}"] = boundary.to_dict()

        self.capabilities.append(
            Capability(
                device_class,
                pseudo,
                known,
                bool(boundary and boundary.earliest_returned),
                bool(current_rows),
                "module/pack/SOH fields are current-only unless history is observed",
            )
        )
        return device_class, pseudo, known, boundary

    def run(self):
        self.progress("Discovering plant...")
        plants = self.client.plants()
        if not plants:
            raise RuntimeError("No FusionSolar plants were returned")

        devices: list[dict[str, Any]] = []
        for plant in plants:
            plant_dn = _dn(plant)
            if not plant_dn:
                continue
            try:
                devices.extend(self.client.devices(plant_dn))
            except Exception as exc:
                self._finding("plant", "topology.devices", _failure_outcome(exc), exc)
                if isinstance(exc, (ReadOnlyPolicyViolation, AuthenticationError)):
                    raise
        if not devices:
            devices = self.client.devices()
        devices = list({_dn(device): device for device in devices if _dn(device)}.values())

        today = station_today()
        initial_state = self.store.state()
        global_earliest = today
        per_device: dict[str, tuple[str, str, list[str], date]] = {}
        for device in devices:
            result = self._probe_device(device, today)
            if not result:
                continue
            device_class, pseudo, known, boundary = result
            device_dn = _dn(device)
            if device_dn and known and boundary and boundary.earliest_returned:
                per_device[device_dn] = (
                    device_class,
                    pseudo,
                    known,
                    boundary.earliest_returned,
                )
                global_earliest = min(global_earliest, boundary.earliest_returned)

        plant_ranges: dict[str, tuple[str, date]] = {}
        for plant in plants:
            plant_dn = _dn(plant)
            if not plant_dn:
                continue
            pseudo = self.store.pseudonym(plant_dn)

            def plant_probe(day: date, dn: str = plant_dn) -> dict[str, Any]:
                raw = self.client.plant_balance(dn, day)
                data = raw.get("data", {}) if isinstance(raw, dict) else {}
                return {"data": {"balance": {"data": data.get("xAxis") or []}}}

            boundary = discover_history_boundary(
                plant_probe, today, max_years=self.history_max_years
            )
            self.history_boundaries[f"plant:{pseudo}"] = boundary.to_dict()
            if boundary.earliest_returned:
                plant_ranges[plant_dn] = (pseudo, boundary.earliest_returned)
                global_earliest = min(global_earliest, boundary.earliest_returned)

        start = start_for_run(
            initial_state,
            global_earliest,
            full=self.full,
            overlap_days=self.overlap_days,
        )
        refresh_from = refresh_from_for_run(
            initial_state,
            global_earliest,
            full=self.full,
            overlap_days=self.overlap_days,
        )
        watermark_blocked = False
        completed_through: date | None = None
        day = start

        while day <= today:
            errors = 0
            for plant_dn, (pseudo, earliest) in plant_ranges.items():
                if day < earliest:
                    continue
                resource = f"plant:{pseudo}"
                if not resource_day_needed(self.store, resource, day, refresh_from):
                    self._record_coverage(resource, day, [], "resumed_skip_completed")
                    continue
                try:
                    raw = self.client.plant_balance(plant_dn, day)
                    telemetry, aggregates = plant_balance_rows(
                        raw,
                        device_pseudonym=pseudo,
                        day=day,
                        raw_sha256=self.client.t.last_response_sha256,
                    )
                    self.telemetry.extend(telemetry)
                    self.aggregates.extend(aggregates)
                    self.store.mark_resource_day_complete(resource, day)
                    self._record_coverage(
                        resource,
                        day,
                        telemetry,
                        "success_with_data" if telemetry or aggregates else "success_empty",
                    )
                except Exception as exc:
                    errors += 1
                    self._record_coverage(resource, day, [], _failure_outcome(exc))
                    self._finding(pseudo, "plant.balance", _failure_outcome(exc), exc)
                    if isinstance(exc, (ReadOnlyPolicyViolation, AuthenticationError)):
                        raise

            for device_dn, (device_class, pseudo, signal_ids, earliest) in per_device.items():
                if day < earliest:
                    continue
                resource = f"history:{pseudo}"
                if not resource_day_needed(self.store, resource, day, refresh_from):
                    self._record_coverage(resource, day, [], "resumed_skip_completed")
                    continue
                try:
                    raw = self.client.history(device_dn, signal_ids, day)
                    rows = history_rows(
                        raw,
                        device_pseudonym=pseudo,
                        device_class=device_class,
                        endpoint="device.history",
                        raw_sha256=self.client.t.last_response_sha256,
                    )
                    self.telemetry.extend(rows)
                    self.store.mark_resource_day_complete(resource, day)
                    self._record_coverage(
                        resource,
                        day,
                        rows,
                        "success_with_data" if rows else "success_empty",
                    )
                except Exception as exc:
                    errors += 1
                    self._record_coverage(resource, day, [], _failure_outcome(exc))
                    self._finding(pseudo, "device.history", _failure_outcome(exc), exc)
                    if isinstance(exc, (ReadOnlyPolicyViolation, AuthenticationError)):
                        raise
            if errors:
                watermark_blocked = True
            elif not watermark_blocked:
                completed_through = day
            day += timedelta(days=1)

        for device in devices:
            device_dn = _dn(device)
            if not device_dn:
                continue
            device_class = _classify(device)
            pseudo = self.store.pseudonym(device_dn)
            self.current.extend(
                self._diagnostic_rows(
                    pseudo,
                    "device.realtime.final",
                    lambda dn=device_dn: self.client.realtime(dn),
                    lambda payload: realtime_rows(
                        payload,
                        device_pseudonym=pseudo,
                        device_class=device_class,
                        source_endpoint="device.realtime",
                        raw_sha256=self.client.t.last_response_sha256,
                    ),
                )
            )
            try:
                alarms = self.client.alarms(device_dn)
                self._finding(
                    pseudo, "alarms.current", "available" if alarms else "empty_no_data"
                )
                (self.store.root / "validation" / f"alarms_{pseudo}.json").write_text(
                    json.dumps(alarms, indent=2), encoding="utf-8"
                )
            except (ReadOnlyPolicyViolation, AuthenticationError) as exc:
                self._finding(pseudo, "alarms.current", _failure_outcome(exc), exc)
                raise
            except Exception as exc:
                self._finding(pseudo, "alarms.current", _failure_outcome(exc), exc)

            if device_class == "battery":
                self.current.extend(
                    self._diagnostic_rows(
                        pseudo,
                        "device.kpi",
                        lambda dn=device_dn: self.client.kpi(dn, ["10007"]),
                        lambda payload: realtime_rows(
                            payload,
                            device_pseudonym=pseudo,
                            device_class="battery",
                            source_endpoint="device.kpi",
                            raw_sha256=self.client.t.last_response_sha256,
                        ),
                    )
                )
                for module in ("1", "2", "3", "4"):
                    signal_ids = module_signal_ids(module)
                    if not signal_ids:
                        self._finding(
                            pseudo,
                            f"battery.module.{module}",
                            "unsupported_not_exposed",
                            detail="no signal identifiers configured",
                        )
                        continue
                    self.current.extend(
                        self._diagnostic_rows(
                            pseudo,
                            f"battery.module.{module}",
                            lambda dn=device_dn, m=module, ids=signal_ids: self.client.battery_module(
                                dn, m, ids
                            ),
                            lambda payload, m=module: realtime_rows(
                                payload,
                                device_pseudonym=pseudo,
                                device_class=f"battery-module-{m}",
                                source_endpoint="battery.module",
                                raw_sha256=self.client.t.last_response_sha256,
                            ),
                        )
                    )

        self._deduplicate()
        self.store.write_table("normalised/telemetry", self.telemetry)
        self.store.write_table("normalised/daily_aggregates", self.aggregates)
        self.store.write_table("normalised/current_diagnostics", self.current)

        (self.store.root / "validation" / "telemetry_validation.json").write_text(
            json.dumps(validate_telemetry(self.telemetry), indent=2, sort_keys=True),
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
            json.dumps(sign_report, indent=2, sort_keys=True), encoding="utf-8"
        )
        integration = point_integration_vs_vendor_aggregates(self.telemetry, self.aggregates)
        (self.store.root / "derived" / "point_integration_vs_vendor_aggregates.json").write_text(
            json.dumps(integration, indent=2, sort_keys=True), encoding="utf-8"
        )
        capabilities = [capability.__dict__ for capability in self.capabilities]
        (self.store.root / "validation" / "capabilities.json").write_text(
            json.dumps(
                {"devices": capabilities, "findings": self.capability_findings},
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        (self.store.root / "validation" / "coverage.json").write_text(
            json.dumps(self._coverage_report(start, today), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        self.store.manifest(
            {
                "exporter_version": "0.1.0",
                "full_rebuild": self.full,
                "incremental_overlap_days": self.overlap_days,
                "requested_start_day": start.isoformat(),
                "latest_requested_day": today.isoformat(),
                "oldest_observed_history_day": global_earliest.isoformat(),
                "history_boundaries": self.history_boundaries,
                "capabilities": capabilities,
                "dependency": {
                    "fusion-solar-py": "0.1.2",
                    "inspected_upstream_commit": "3e02b9f5d831673070e0f7ddac7d9db53ca2368b",
                },
                "claim_boundary": (
                    "observational vendor telemetry; no SOH/RUL/degradation ground-truth claim"
                ),
            }
        )
        archive = self.store.package_zip()

        if not watermark_blocked and completed_through is not None:
            final_state = self.store.state()
            previous_text = final_state.get("last_successful_day")
            previous = date.fromisoformat(str(previous_text)) if previous_text else None
            if previous is None or completed_through > previous:
                final_state["last_successful_day"] = completed_through.isoformat()
            final_state["last_data_host"] = self.client.host
            self.store.save_state(final_state)
        return archive

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
