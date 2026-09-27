from __future__ import annotations

from datetime import date, datetime
import json
from typing import Any

from .signals import COMMUNITY_LABELS, semantic_status
from .timeutil import local_iso_from_epoch_ms, local_naive_series_to_utc


def _raw_value(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _signals_data(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    data = payload.get("data", payload)
    return data if isinstance(data, dict) else {}


def history_rows(
    payload: dict[str, Any],
    *,
    device_pseudonym: str,
    device_class: str,
    endpoint: str,
    raw_sha256: str | None = None,
) -> list[dict[str, Any]]:
    rows = []
    for signal_id, obj in _signals_data(payload).items():
        if not isinstance(obj, dict):
            continue
        label = obj.get("name") or COMMUNITY_LABELS.get(str(signal_id))
        unit = obj.get("unit")
        points = obj.get("data") or obj.get("values") or []
        if isinstance(points, dict):
            points = [{"x": key, "y": value} for key, value in points.items()]
        for point in points:
            if isinstance(point, dict):
                timestamp = point.get("x") or point.get("timestamp") or point.get("time")
                value = point.get("y") if "y" in point else point.get("value")
            elif isinstance(point, (list, tuple)) and len(point) >= 2:
                timestamp, value = point[0], point[1]
            else:
                continue
            if timestamp is None:
                continue
            try:
                timestamp_ms = int(str(timestamp))
                if timestamp_ms < 10_000_000_000:
                    timestamp_ms *= 1000
                utc_value, local_value, _ = local_iso_from_epoch_ms(timestamp_ms)
            except Exception:
                continue
            rows.append(
                {
                    "timestamp_utc": utc_value,
                    "timestamp_local": local_value,
                    "station_timezone": "Europe/London",
                    "device_pseudonym": device_pseudonym,
                    "device_class": device_class,
                    "source_endpoint": endpoint,
                    "signal_id": str(signal_id),
                    "source_label": label,
                    "source_unit": unit,
                    "raw_value": _raw_value(value),
                    "semantic_status": semantic_status(str(signal_id), label),
                    "raw_response_sha256": raw_sha256,
                }
            )
    return rows


def plant_balance_rows(
    payload: dict[str, Any],
    *,
    device_pseudonym: str,
    day: date,
    raw_sha256: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    data = payload.get("data", payload) if isinstance(payload, dict) else {}
    if not isinstance(data, dict):
        return [], []
    xaxis = data.get("xAxis") or []
    telemetry = []
    aggregates = []
    parsed_axis: list[tuple[str, str] | None]
    try:
        naive_axis = [datetime.strptime(str(value), "%Y-%m-%d %H:%M") for value in xaxis]
        parsed_axis = list(local_naive_series_to_utc(naive_axis))
    except Exception:
        parsed_axis = [None for _ in xaxis]
    for key, value in data.items():
        if key in {"xAxis", "stationTimezone", "clientTimezone", "stationDn"}:
            continue
        if isinstance(value, list) and len(value) == len(xaxis):
            for index, raw_value in enumerate(value):
                if raw_value in (None, "--", ""):
                    continue
                parsed = parsed_axis[index]
                if parsed is None:
                    continue
                utc_value, local_value = parsed
                telemetry.append(
                    {
                        "timestamp_utc": utc_value,
                        "timestamp_local": local_value,
                        "station_timezone": "Europe/London",
                        "device_pseudonym": device_pseudonym,
                        "device_class": "plant",
                        "source_endpoint": "plant.balance",
                        "signal_id": key,
                        "source_label": key,
                        "source_unit": None,
                        "raw_value": _raw_value(raw_value),
                        "semantic_status": "SOURCE_LABEL_ONLY",
                        "raw_response_sha256": raw_sha256,
                    }
                )
        elif not isinstance(value, (dict, list)):
            aggregates.append(
                {
                    "date": day.isoformat(),
                    "device_pseudonym": device_pseudonym,
                    "source_endpoint": "plant.balance",
                    "field": key,
                    "raw_value": _raw_value(value),
                    "semantic_status": "SOURCE_LABEL_ONLY",
                    "raw_response_sha256": raw_sha256,
                }
            )
    return telemetry, aggregates


def _signal_items(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    data = payload.get("data", payload)

    def unpack(value: Any) -> list[dict[str, Any]]:
        if isinstance(value, list):
            output: list[dict[str, Any]] = []
            for item in value:
                output.extend(unpack(item))
            return output
        if not isinstance(value, dict):
            return []

        signals = value.get("signals")
        if isinstance(signals, list):
            return [item for item in signals if isinstance(item, dict)]
        if isinstance(signals, dict):
            output = []
            for signal_id, signal in signals.items():
                if isinstance(signal, dict):
                    item = dict(signal)
                    item.setdefault("id", signal_id)
                else:
                    item = {"id": signal_id, "value": signal}
                output.append(item)
            return output

        if any(key in value for key in ("id", "signalId", "sigId")):
            return [value]
        return []

    return unpack(data)


def realtime_rows(
    payload: dict[str, Any],
    *,
    device_pseudonym: str,
    device_class: str,
    source_endpoint: str,
    raw_sha256: str | None = None,
) -> list[dict[str, Any]]:
    from .timeutil import STATION_ZONE, UTC

    now_utc = datetime.now(UTC)
    rows = []
    for signal in _signal_items(payload):
        signal_id = str(signal.get("id") or signal.get("signalId") or signal.get("sigId") or "")
        if not signal_id:
            continue
        label = signal.get("name") or signal.get("signalName")
        value = signal.get("realValue", signal.get("value"))
        rows.append(
            {
                "timestamp_utc": now_utc.isoformat(),
                "timestamp_local": now_utc.astimezone(STATION_ZONE).isoformat(),
                "station_timezone": "Europe/London",
                "device_pseudonym": device_pseudonym,
                "device_class": device_class,
                "source_endpoint": source_endpoint,
                "signal_id": signal_id,
                "source_label": label,
                "source_unit": signal.get("unit"),
                "raw_value": _raw_value(value),
                "semantic_status": semantic_status(signal_id, label),
                "raw_response_sha256": raw_sha256,
            }
        )
    return rows
