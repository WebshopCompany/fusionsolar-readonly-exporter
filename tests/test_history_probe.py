from datetime import date
from fusionsolar_readonly_exporter.exporter import discover_earliest


def test_earliest_probe_transition():
    earliest = date(2025, 11, 17)
    latest = date(2026, 1, 15)

    def fetch(day):
        pts = [{"x": 1, "y": 1}] if day >= earliest else []
        return {"data": {"30007": {"data": pts}}}

    got = discover_earliest(fetch, latest, max_years=1)
    assert got == earliest
