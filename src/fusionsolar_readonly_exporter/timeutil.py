from __future__ import annotations

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

STATION_ZONE = ZoneInfo("Europe/London")
UTC = timezone.utc


def station_today() -> date:
    return datetime.now(STATION_ZONE).date()


def local_midnight(day: date) -> datetime:
    return datetime.combine(day, time.min, STATION_ZONE)


def local_midnight_ms(day: date) -> int:
    return int(local_midnight(day).timestamp() * 1000)


def utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(UTC).isoformat()


def local_iso_from_epoch_ms(epoch_ms: int) -> tuple[str, str, int]:
    dt_utc = datetime.fromtimestamp(epoch_ms / 1000, tz=UTC)
    dt_local = dt_utc.astimezone(STATION_ZONE)
    offset = dt_local.utcoffset()
    return (
        dt_utc.isoformat(),
        dt_local.isoformat(),
        int(offset.total_seconds() // 3600 if offset else 0),
    )


def huawei_timezone_offset_hours(day: date) -> int:
    offset = local_midnight(day).utcoffset()
    return int(offset.total_seconds() // 3600 if offset else 0)


def local_naive_series_to_utc(
    local_values: list[datetime],
) -> list[tuple[str, str]]:
    """Convert ordered Europe/London local wall times to monotonic UTC."""

    output: list[tuple[str, str]] = []
    previous_utc: datetime | None = None
    for naive in local_values:
        if naive.tzinfo is not None:
            raise ValueError("expected naive local wall time")
        candidates = [
            naive.replace(tzinfo=STATION_ZONE, fold=0),
            naive.replace(tzinfo=STATION_ZONE, fold=1),
        ]
        valid: list[tuple[datetime, datetime]] = []
        for local in candidates:
            utc_value = local.astimezone(UTC)
            roundtrip = utc_value.astimezone(STATION_ZONE).replace(tzinfo=None)
            if roundtrip == naive:
                valid.append((local, utc_value))
        unique: dict[datetime, datetime] = {utc_value: local for local, utc_value in valid}
        ordered = sorted((local, utc_value) for utc_value, local in unique.items())
        chosen = None
        for local, utc_value in ordered:
            if previous_utc is None or utc_value > previous_utc:
                chosen = (local, utc_value)
                break
        if chosen is None:
            raise ValueError(f"cannot map local FusionSolar timestamp monotonically: {naive}")
        local, utc_value = chosen
        output.append((utc_value.isoformat(), local.isoformat()))
        previous_utc = utc_value
    return output
