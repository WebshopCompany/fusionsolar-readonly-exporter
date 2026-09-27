from fusionsolar_readonly_exporter.normalise import history_rows
from fusionsolar_readonly_exporter.validate import validate_telemetry


def synthetic_payload():
    return {
        "success": True,
        "data": {
            "30001": {
                "name": "Charging power",
                "unit": "kW",
                "data": [{"x": 1767225600000, "y": "0.0"}, {"x": 1767225900000, "y": "0.1"}],
            },
            "30007": {
                "name": "SOC",
                "unit": "%",
                "data": [{"x": 1767225600000, "y": "5"}, {"x": 1767225900000, "y": "6"}],
            },
        },
    }


def test_signal_id_and_raw_label_preserved_with_contradiction_status():
    rows = history_rows(
        synthetic_payload(),
        device_pseudonym="dev-test",
        device_class="battery",
        endpoint="device.history",
    )
    r = next(x for x in rows if x["signal_id"] == "30001")
    assert r["source_label"] == "Charging power"
    assert r["semantic_status"] == "SOURCE_LABEL_CONTRADICTED_BY_OBSERVED_BEHAVIOUR"


def test_validation_cadence_and_monotonicity():
    rows = history_rows(
        synthetic_payload(),
        device_pseudonym="dev-test",
        device_class="battery",
        endpoint="device.history",
    )
    v = validate_telemetry(rows)
    key = next(k for k in v["series"] if "30001" in k)
    assert v["series"][key]["cadence_seconds"] == 300
    assert v["series"][key]["monotonic_non_decreasing"] is True


def test_duplicate_detection_and_gap_detection():
    rows = history_rows(
        synthetic_payload(),
        device_pseudonym="dev-test",
        device_class="battery",
        endpoint="device.history",
    )
    rows.append(dict(rows[0]))
    soc = [row for row in rows if row["signal_id"] == "30007"]
    extra_1 = dict(soc[-1])
    extra_1["timestamp_utc"] = "2026-01-01T00:10:00+00:00"
    extra_2 = dict(soc[-1])
    extra_2["timestamp_utc"] = "2026-01-01T00:20:00+00:00"
    rows.extend([extra_1, extra_2])
    result = validate_telemetry(rows)
    assert result["duplicate_keys"] >= 1
    soc_key = next(key for key in result["series"] if "30007" in key)
    assert result["series"][soc_key]["gap_count"] >= 1
