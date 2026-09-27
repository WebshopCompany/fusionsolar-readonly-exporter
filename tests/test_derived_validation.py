from fusionsolar_readonly_exporter.validate import (
    opposite_sign_relationship,
    point_integration_vs_vendor_aggregates,
)


def test_endpoint_specific_opposite_sign_is_reported_not_corrected():
    rows = []
    for i, (a, b) in enumerate(((1.0, -1.0), (-2.0, 2.0))):
        timestamp = f"2026-01-01T00:0{i}:00+00:00"
        rows.append(
            {
                "timestamp_utc": timestamp,
                "source_endpoint": "device.history",
                "signal_id": "30005",
                "raw_value": a,
            }
        )
        rows.append(
            {
                "timestamp_utc": timestamp,
                "source_endpoint": "plant.balance",
                "signal_id": "chargeAndDisChargePower",
                "raw_value": b,
            }
        )
    report = opposite_sign_relationship(
        rows,
        a_endpoint="device.history",
        a_signal="30005",
        b_endpoint="plant.balance",
        b_signal="chargeAndDisChargePower",
    )
    assert report["aligned_points"] == 2
    assert report["max_abs_opposite_sign_error"] == 0
    assert report["interpretation"] == "REPORT_ONLY_DO_NOT_SILENTLY_FLIP_SIGNS"


def test_point_integration_is_labelled_diagnostic_and_vendor_value_preserved():
    rows = [
        {
            "timestamp_local": "2026-01-01T00:00:00+00:00",
            "device_pseudonym": "dev-test",
            "source_endpoint": "plant.balance",
            "signal_id": "productPower",
            "raw_value": 1.0,
        },
        {
            "timestamp_local": "2026-01-01T00:05:00+00:00",
            "device_pseudonym": "dev-test",
            "source_endpoint": "plant.balance",
            "signal_id": "productPower",
            "raw_value": 1.0,
        },
    ]
    aggregates = [
        {
            "date": "2026-01-01",
            "device_pseudonym": "dev-test",
            "field": "totalProductPower",
            "raw_value": 0.10,
        }
    ]
    report = point_integration_vs_vendor_aggregates(rows, aggregates)
    comparison = report["comparisons"][0]
    assert comparison["vendor_value"] == 0.10
    assert comparison["derived_kwh"] != comparison["vendor_value"]
    assert report["replacement_of_vendor_aggregate"] is False
