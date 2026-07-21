"""Continuous wall-clock occupancy for coverage constraints.

Bands (shift starts) remain assignment + bump legality.
This module answers: how many officers are on duty at time t,
and whether 24/7 + date/time window minima are met.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


@functools.lru_cache(maxsize=128)
def _parse_hhmm(value: str) -> int:
    parts = (value or "").strip().split(":")
    if len(parts) < 2:
        raise ValueError(f"Invalid time: {value}")
    return int(parts[0]) * 60 + int(parts[1])


@functools.lru_cache(maxsize=4096)
def assignment_intervals(
    work_date: date,
    shift_start: str,
    shift_end: str,
) -> List[Tuple[datetime, datetime]]:
    """Expand one duty day into half-open [start, end) datetimes (overnight splits)."""
    start_m = _parse_hhmm(shift_start)
    end_m = _parse_hhmm(shift_end)
    day0 = datetime(work_date.year, work_date.month, work_date.day)
    start_dt = day0 + timedelta(minutes=start_m)
    if end_m > start_m:
        end_dt = day0 + timedelta(minutes=end_m)
        return [(start_dt, end_dt)]
    # Overnight: work_date start → midnight next day, then midnight → end on next calendar day
    midnight_next = day0 + timedelta(days=1)
    end_dt = midnight_next + timedelta(minutes=end_m)
    return [(start_dt, midnight_next), (midnight_next, end_dt)]


def build_occupancy_events(
    assignments: Sequence[Tuple[date, str, str]],
) -> List[Tuple[datetime, int]]:
    """Return sorted (timestamp, delta) events for sweep-line (+1 start, -1 end)."""
    events: List[Tuple[datetime, int]] = []
    for work_date, start, end in assignments:
        for a, b in assignment_intervals(work_date, start, end):
            events.append((a, 1))
            events.append((b, -1))
    events.sort(key=lambda x: (x[0], -x[1]))
    return events


def occupancy_at(
    assignments: Sequence[Tuple[date, str, str]],
    when: datetime,
) -> int:
    """How many officers on duty at exact instant (end exclusive)."""
    count = 0
    for work_date, start, end in assignments:
        for a, b in assignment_intervals(work_date, start, end):
            if a <= when < b:
                count += 1
    return count


def min_occupancy_in_range(
    assignments: Sequence[Tuple[date, str, str]],
    range_start: datetime,
    range_end: datetime,
    *,
    step_minutes: int = 15,
) -> int:
    """Minimum headcount over [range_start, range_end) using sweep line.

    Occupancy is piecewise-constant; extrema only change at event times.
    Samples occupancy at range_start and after every event inside the range.
    ``step_minutes`` is kept for API compat (unused — event sampling is exact).
    """
    del step_minutes  # API compat; sweep events are exact for half-open intervals
    if range_end <= range_start:
        return 0

    events = build_occupancy_events(assignments)

    current_occ = 0
    i = 0
    n = len(events)

    # Apply all events at or before range_start → occupancy at range_start
    while i < n and events[i][0] <= range_start:
        current_occ += events[i][1]
        i += 1

    min_occ = current_occ

    # Walk events strictly inside the open-ended window
    while i < n:
        t = events[i][0]
        if t >= range_end:
            break
        # Process all deltas at this timestamp (+1 before -1 via sort key)
        while i < n and events[i][0] == t:
            current_occ += events[i][1]
            i += 1
        if t >= range_start and current_occ < min_occ:
            min_occ = current_occ

    return min_occ


def normalize_weekdays(raw) -> Optional[Tuple[int, ...]]:
    """
    Normalize weekday field to a sorted tuple of 0=Mon..6=Sun, or None (all days).

    Accepts int, list/tuple/set of ints, or None / "".
    """
    if raw is None or raw == "":
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return (int(raw) % 7,)
    if isinstance(raw, (list, tuple, set)):
        out = []
        for item in raw:
            try:
                out.append(int(item) % 7)
            except (TypeError, ValueError):
                continue
        return tuple(sorted(set(out))) if out else None
    try:
        return (int(raw) % 7,)
    except (TypeError, ValueError):
        return None


@dataclass
class CoverageWindow:
    """Additional minimum coverage for a date or weekday time range."""

    min_officers: int
    start_time: str  # HH:MM
    end_time: str  # HH:MM
    # specific_date and weekday are independent: date wins when set
    specific_date: Optional[date] = None
    # int or sequence of ints (0=Mon..6=Sun); None = every day
    weekday: Optional[object] = None
    label: str = ""

    def weekday_set(self) -> Optional[set]:
        """None = all days; else set of Python weekday() ints."""
        return None if normalize_weekdays(self.weekday) is None else set(normalize_weekdays(self.weekday) or ())

    def matches_date(self, d: date) -> bool:
        if self.specific_date is not None:
            return d == self.specific_date
        wds = normalize_weekdays(self.weekday)
        if wds is not None:
            return d.weekday() in wds
        return True

    def window_datetimes(self, d: date) -> Tuple[datetime, datetime]:
        start_m = _parse_hhmm(self.start_time)
        end_m = _parse_hhmm(self.end_time)
        day0 = datetime(d.year, d.month, d.day)
        start_dt = day0 + timedelta(minutes=start_m)
        if end_m > start_m:
            end_dt = day0 + timedelta(minutes=end_m)
        else:
            end_dt = day0 + timedelta(days=1, minutes=end_m)
        return start_dt, end_dt


def check_coverage_247(
    assignments: Sequence[Tuple[date, str, str]],
    day: date,
    min_officers: int,
    *,
    step_minutes: int = 15,
) -> Dict:
    """Require at least min_officers every step across the full calendar day (and overnight spill into next)."""
    start = datetime(day.year, day.month, day.day)
    end = start + timedelta(days=1)
    # Include prior-day overnight tails by allowing assignments dated day-1
    min_c = min_occupancy_in_range(assignments, start, end, step_minutes=step_minutes)
    ok = min_c >= min_officers
    return {
        "ok": ok,
        "min_occupancy": min_c,
        "required": min_officers,
        "day": day.isoformat(),
        "message": (
            f"24/7 coverage OK (min {min_c} ≥ {min_officers})"
            if ok
            else f"24/7 coverage short (min {min_c} < {min_officers}) on {day.isoformat()}"
        ),
    }


def check_coverage_window(
    assignments: Sequence[Tuple[date, str, str]],
    window: CoverageWindow,
    anchor_date: date,
    *,
    step_minutes: int = 15,
) -> Dict:
    if not window.matches_date(anchor_date):
        return {"ok": True, "skipped": True, "message": "Window does not apply to this date"}
    start_dt, end_dt = window.window_datetimes(anchor_date)
    min_c = min_occupancy_in_range(assignments, start_dt, end_dt, step_minutes=step_minutes)
    ok = min_c >= window.min_officers
    label = window.label or f"{window.start_time}–{window.end_time}"
    return {
        "ok": ok,
        "min_occupancy": min_c,
        "required": window.min_officers,
        "label": label,
        "range_start": start_dt.isoformat(sep=" "),
        "range_end": end_dt.isoformat(sep=" "),
        "message": (
            f"Window {label} OK (min {min_c} ≥ {window.min_officers})"
            if ok
            else f"Window {label} short (min {min_c} < {window.min_officers})"
        ),
    }


def evaluate_day_coverage(
    assignments: Sequence[Tuple[date, str, str]],
    day: date,
    *,
    min_247: int = 0,
    windows: Optional[Iterable[CoverageWindow]] = None,
    step_minutes: int = 15,
) -> Dict:
    """Aggregate 24/7 + extra windows for one calendar day."""
    results = []
    all_ok = True
    if min_247 > 0:
        r = check_coverage_247(assignments, day, min_247, step_minutes=step_minutes)
        results.append(r)
        all_ok = all_ok and r["ok"]
    for w in windows or []:
        r = check_coverage_window(assignments, w, day, step_minutes=step_minutes)
        if r.get("skipped"):
            continue
        results.append(r)
        all_ok = all_ok and r["ok"]
    return {"ok": all_ok, "checks": results, "day": day.isoformat()}
