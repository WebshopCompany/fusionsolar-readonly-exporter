from datetime import date, datetime, timezone
import pytest
from fusionsolar_readonly_exporter.timeutil import (
    STATION_ZONE,
    local_midnight,
    local_midnight_ms,
    local_naive_series_to_utc,
)


def test_london_spring_dst_boundary():
    assert local_midnight(date(2026, 3, 29)).utcoffset().total_seconds() == 0
    assert local_midnight(date(2026, 3, 30)).utcoffset().total_seconds() == 3600


def test_london_autumn_dst_boundary():
    assert local_midnight(date(2026, 10, 25)).utcoffset().total_seconds() == 3600
    assert local_midnight(date(2026, 10, 26)).utcoffset().total_seconds() == 0


def test_midnight_epoch_is_timezone_aware():
    day = date(2026, 7, 1)
    got = datetime.fromtimestamp(local_midnight_ms(day) / 1000, tz=timezone.utc).astimezone(
        STATION_ZONE
    )
    assert got.date() == day and got.hour == 0


def test_autumn_repeated_hour_maps_to_increasing_utc():
    wall = [
        datetime(2026, 10, 25, 0, 55),
        datetime(2026, 10, 25, 1, 0),
        datetime(2026, 10, 25, 1, 55),
        datetime(2026, 10, 25, 1, 0),
        datetime(2026, 10, 25, 1, 55),
        datetime(2026, 10, 25, 2, 0),
    ]
    converted = local_naive_series_to_utc(wall)
    utc = [datetime.fromisoformat(item[0]) for item in converted]
    assert all(b > a for a, b in zip(utc, utc[1:]))
    assert converted[1][1].endswith("+01:00")
    assert converted[3][1].endswith("+00:00")


def test_nonexistent_spring_wall_time_is_rejected():
    with pytest.raises(ValueError):
        local_naive_series_to_utc([datetime(2026, 3, 29, 1, 30)])
