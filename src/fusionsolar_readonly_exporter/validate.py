from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime
from typing import Any


def _num(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def validate_telemetry(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {"rows": len(rows), "duplicate_keys": 0, "series": {}, "warnings": []}
    seen: set[tuple[Any, ...]] = set()
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = (
            row.get("device_pseudonym"),
            row.get("signal_id"),
            row.get("timestamp_utc"),
            row.get("source_endpoint"),
        )
        if key in seen:
            result["duplicate_keys"] += 1
        seen.add(key)
        grouped[
            (row.get("device_pseudonym"), row.get("signal_id"), row.get("source_endpoint"))
        ].append(row)

    for key, series_rows in grouped.items():
        series_rows = sorted(series_rows, key=lambda item: item.get("timestamp_utc") or "")
        deltas: list[float] = []
        bad_numeric = 0
        values: list[float] = []
        previous = None
        for row in series_rows:
            try:
                current = datetime.fromisoformat(str(row["timestamp_utc"]))
                if previous is not None:
                    deltas.append((current - previous).total_seconds())
                previous = current
            except (TypeError, ValueError):
                pass
            if _num(row.get("raw_value")):
                values.append(float(row["raw_value"]))
            elif row.get("raw_value") not in (None, "", "--"):
                bad_numeric += 1

        positive = [delta for delta in deltas if delta > 0]
        cadence = None
        if positive:
            rounded = [round(delta) for delta in positive]
            cadence = max(set(rounded), key=rounded.count)
        gaps = [delta for delta in positive if cadence and delta > cadence * 1.5]
        sid = str(key[1])
        monotonic = None
        if sid in {"30001", "30002"} and len(values) > 1:
            monotonic = all(b >= a for a, b in zip(values, values[1:]))
        result["series"]["|".join(map(str, key))] = {
            "count": len(series_rows),
            "cadence_seconds": cadence,
            "gap_count": len(gaps),
            "max_gap_seconds": max(gaps) if gaps else 0,
            "bad_numeric": bad_numeric,
            "min": min(values) if values else None,
            "max": max(values) if values else None,
            "monotonic_non_decreasing": monotonic,
        }

    for row in rows:
        if str(row.get("signal_id")) == "30007" and _num(row.get("raw_value")):
            value = float(row["raw_value"])
            if value < 0 or value > 100:
                result["warnings"].append("SOC outside 0..100")
    return result


def opposite_sign_relationship(
    rows: list[dict[str, Any]], *, a_endpoint: str, a_signal: str, b_endpoint: str, b_signal: str
) -> dict[str, Any]:
    a = {
        row["timestamp_utc"]: float(row["raw_value"])
        for row in rows
        if row.get("source_endpoint") == a_endpoint
        and str(row.get("signal_id")) == a_signal
        and _num(row.get("raw_value"))
    }
    b = {
        row["timestamp_utc"]: float(row["raw_value"])
        for row in rows
        if row.get("source_endpoint") == b_endpoint
        and str(row.get("signal_id")) == b_signal
        and _num(row.get("raw_value"))
    }
    common = sorted(set(a) & set(b))
    if not common:
        return {
            "a_endpoint": a_endpoint,
            "a_signal": a_signal,
            "b_endpoint": b_endpoint,
            "b_signal": b_signal,
            "aligned_points": 0,
            "interpretation": "UNVERIFIED_NO_ALIGNED_POINTS",
        }
    errors = [abs(a[timestamp] + b[timestamp]) for timestamp in common]
    return {
        "a_endpoint": a_endpoint,
        "a_signal": a_signal,
        "b_endpoint": b_endpoint,
        "b_signal": b_signal,
        "aligned_points": len(common),
        "max_abs_opposite_sign_error": max(errors),
        "mean_abs_opposite_sign_error": sum(errors) / len(errors),
        "interpretation": "REPORT_ONLY_DO_NOT_SILENTLY_FLIP_SIGNS",
    }


_AGGREGATE_MAP = {
    "productPower": "totalProductPower",
    "usePower": "totalUsePower",
    "selfUsePower": "totalSelfUsePower",
    "onGridPower": "totalOnGridPower",
    "buyPower": "totalBuyPower",
}


def point_integration_vs_vendor_aggregates(
    telemetry: list[dict[str, Any]], aggregates: list[dict[str, Any]]
) -> dict[str, Any]:
    """Compare a named 5-minute right-rectangle diagnostic with vendor daily aggregates.

    This diagnostic is deliberately *not* an energy reconstruction claim. It exists to quantify the
    mismatch and to prevent point samples from being silently treated as interval averages.
    """
    vendor: dict[tuple[str, str, str], float] = {}
    for row in aggregates:
        if _num(row.get("raw_value")):
            vendor[
                (str(row.get("date")), str(row.get("device_pseudonym")), str(row.get("field")))
            ] = float(row["raw_value"])

    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in telemetry:
        signal = str(row.get("signal_id"))
        if row.get("source_endpoint") != "plant.balance" or signal not in _AGGREGATE_MAP:
            continue
        try:
            day = datetime.fromisoformat(str(row["timestamp_local"])).date().isoformat()
        except (TypeError, ValueError):
            continue
        grouped[(day, str(row.get("device_pseudonym")), signal)].append(row)

    comparisons = []
    for (day, device, signal), rows in sorted(grouped.items()):
        values = [float(row["raw_value"]) for row in rows if _num(row.get("raw_value"))]
        if not values:
            continue
        derived_kwh = sum(values) * (300.0 / 3600.0)
        vendor_field = _AGGREGATE_MAP[signal]
        vendor_value = vendor.get((day, device, vendor_field))
        comparisons.append(
            {
                "date": day,
                "device_pseudonym": device,
                "series_signal": signal,
                "vendor_aggregate_field": vendor_field,
                "method": "RIGHT_RECTANGLE_ASSUMING_300_SECONDS_PER_POINT_DIAGNOSTIC_ONLY",
                "derived_kwh": derived_kwh,
                "vendor_value": vendor_value,
                "difference": None if vendor_value is None else derived_kwh - vendor_value,
                "claim_boundary": "point samples are not assumed to be interval averages",
            }
        )
    return {"comparisons": comparisons, "replacement_of_vendor_aggregate": False}
