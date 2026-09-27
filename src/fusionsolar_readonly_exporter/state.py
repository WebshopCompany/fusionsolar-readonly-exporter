from __future__ import annotations

from datetime import date, timedelta
from typing import Any


def start_for_run(
    state: dict[str, Any], earliest: date, *, full: bool, overlap_days: int = 2
) -> date:
    if full or not state.get("last_successful_day"):
        return earliest
    last = date.fromisoformat(str(state["last_successful_day"]))
    return max(earliest, last - timedelta(days=max(0, overlap_days)))


def refresh_from_for_run(
    state: dict[str, Any], earliest: date, *, full: bool, overlap_days: int = 2
) -> date | None:
    if full or not state.get("last_successful_day"):
        return None
    last = date.fromisoformat(str(state["last_successful_day"]))
    return max(earliest, last - timedelta(days=max(0, overlap_days)))
