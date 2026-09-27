from datetime import date, timedelta

import pytest

from fusionsolar_readonly_exporter.errors import SessionExpired
from fusionsolar_readonly_exporter.exporter import discover_earliest, discover_history_boundary


def _payload(has_data):
    pts = [{"x": 1, "y": 1}] if has_data else []
    return {"data": {"30007": {"data": pts}}}


def test_earliest_probe_transition():
    earliest = date(2025, 11, 17)
    latest = date(2026, 1, 15)

    def fetch(day):
        return _payload(day >= earliest)

    assert discover_earliest(fetch, latest, max_years=1) == earliest


def test_extended_outage_is_not_mistaken_for_retention_boundary():
    latest = date(2026, 9, 1)
    older_start = date(2025, 5, 1)
    older_end = date(2025, 8, 31)
    recent_start = date(2026, 5, 1)

    def fetch(day):
        return _payload(older_start <= day <= older_end or day >= recent_start)

    boundary = discover_history_boundary(fetch, latest, max_years=2, sample_step_days=30)
    assert boundary.earliest_returned is not None
    assert boundary.earliest_returned <= older_end
    assert boundary.earliest_returned < recent_start
    assert any(older_end < day < recent_start for day in boundary.empty_probe_days)


def test_probe_errors_are_distinct_from_empty_days():
    latest = date(2026, 1, 15)
    fail_day = latest - timedelta(days=1)

    def fetch(day):
        if day == fail_day:
            raise TimeoutError("synthetic")
        return _payload(day >= date(2026, 1, 10))

    boundary = discover_history_boundary(fetch, latest, max_years=1)
    assert fail_day in boundary.error_probe_days
    assert fail_day not in boundary.empty_probe_days


def test_session_expiry_is_not_misclassified_as_history_gap():
    def fetch(_day):
        raise SessionExpired("synthetic expired session")

    with pytest.raises(SessionExpired):
        discover_history_boundary(fetch, date(2026, 1, 15), max_years=1)
