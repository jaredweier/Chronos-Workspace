"""Schedule matrix, day status, and override maps — **generator** brain.

Public fact APIs for payroll/optimizer: ``get_officer_day_status``,
``shift_hours``, ``officer_shift_hours``, ``officer_work_days_per_cycle``.
Private ``_`` names kept as aliases for back-compat.
"""

from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional, Set, Tuple

from config import is_high_risk_night
from database import connection
from logic import rust_bridge, rust_fallback
from logic.officers import get_officer_by_id, get_officers_by_seniority
from logic.rotation_config import (
    get_active_rotation_base_date,
    get_active_rotation_cycle_length,
)


def _scheduling():
    import logic.scheduling as s

    return s


def build_schedule_matrix(start_date: date, end_date: date) -> Tuple[List[Dict], List[date]]:
    officers = [o for o in get_officers_by_seniority() if o.get("active") == 1]

    bumped_by_date, covering_by_date, swapped_by_date, bumped_status_by_date = _load_override_maps_for_range(
        start_date, end_date
    )
    rust_matrix = rust_bridge.build_schedule_matrix(
        officers,
        bumped_by_date,
        covering_by_date,
        swapped_by_date,
        bumped_status_by_date,
        start_date,
        end_date,
        get_active_rotation_base_date(),
        get_active_rotation_cycle_length(),
    )
    if rust_matrix is not None:
        return rust_matrix

    return rust_fallback.python_build_schedule_matrix(
        officers,
        bumped_by_date,
        covering_by_date,
        swapped_by_date,
        bumped_status_by_date,
        start_date,
        end_date,
        _officer_day_status,
    )


def get_officer_day_status(officer_id: int, target_date: date) -> str:
    statuses = batch_officer_day_status([(officer_id, target_date)])
    return statuses.get((officer_id, target_date.strftime("%Y-%m-%d")), "off")


def batch_officer_day_status(
    pairs: List[Tuple[int, date]],
) -> Dict[Tuple[int, str], str]:
    """Resolve schedule status for many (officer_id, date) pairs with one override load."""
    if not pairs:
        return {}
    min_d = min(d for _, d in pairs)
    max_d = max(d for _, d in pairs)
    officers = [o for o in get_officers_by_seniority() if o.get("active") == 1]
    bumped_by_date, covering_by_date, swapped_by_date, bumped_status_by_date = _load_override_maps_for_range(
        min_d, max_d
    )
    pair_keys = [(officer_id, target.strftime("%Y-%m-%d")) for officer_id, target in pairs]
    rust_statuses = rust_bridge.batch_day_status(
        officers,
        bumped_by_date,
        covering_by_date,
        swapped_by_date,
        bumped_status_by_date,
        pair_keys,
        get_active_rotation_base_date(),
        get_active_rotation_cycle_length(),
    )
    if rust_statuses is not None:
        return {key: rust_statuses.get(key, "off") for key in pair_keys}

    return rust_fallback.python_batch_day_status(
        officers,
        bumped_by_date,
        covering_by_date,
        swapped_by_date,
        bumped_status_by_date,
        pair_keys,
        _officer_day_status,
    )


def _get_monthly_rotation_base_only(year: int, month: int) -> List[Dict]:
    from calendar import monthrange

    _, last_day = monthrange(year, month)
    officers = [o for o in get_officers_by_seniority() if o.get("active") == 1]
    summary = []
    for day_num in range(1, last_day + 1):
        target = date(year, month, day_num)
        cycle_day = _scheduling().get_cycle_day(target)
        squad = _scheduling().get_squad_on_duty(cycle_day)
        working_count = sum(1 for o in officers if _rotation_only_status(o, target) == "working")
        summary.append(
            {
                "date": target,
                "cycle_day": cycle_day,
                "squad_on_duty": squad,
                "working_officers": working_count,
                "high_risk_night": is_high_risk_night(target),
                "snapshot_rows": [],
            }
        )
    return summary


def _load_override_maps_for_range(
    start_date: date, end_date: date
) -> Tuple[
    Dict[str, Set[int]],
    Dict[str, Set[int]],
    Dict[str, Set[int]],
    Dict[str, Dict[int, str]],
]:
    """Return bumped/covering/swapped maps and per-day bumped schedule statuses."""
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")
    bumped_by_date: Dict[str, Set[int]] = {}
    covering_by_date: Dict[str, Set[int]] = {}
    swapped_by_date: Dict[str, Set[int]] = {}
    bumped_status_by_date: Dict[str, Dict[int, str]] = {}
    with connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT override_date, original_officer_id, replacement_officer_id, reason
            FROM schedule_overrides
            WHERE override_date >= ? AND override_date <= ?
        """,
            (start_str, end_str),
        )
        for row in cursor.fetchall():
            day_key = row["override_date"]
            original_id = row["original_officer_id"]
            replacement_id = row["replacement_officer_id"]
            if row["reason"] == "Shift Swap":
                swapped_by_date.setdefault(day_key, set()).add(original_id)
                if replacement_id:
                    swapped_by_date.setdefault(day_key, set()).add(replacement_id)
                continue
            if row["reason"] == "Shift Bid Award":
                if replacement_id:
                    covering_by_date.setdefault(day_key, set()).add(replacement_id)
                continue
            bumped_by_date.setdefault(day_key, set()).add(original_id)
            bumped_status_by_date.setdefault(day_key, {})[original_id] = _schedule_status_for_override_reason(
                row["reason"]
            )
            if replacement_id:
                covering_by_date.setdefault(day_key, set()).add(replacement_id)
    return bumped_by_date, covering_by_date, swapped_by_date, bumped_status_by_date


def _schedule_status_for_override_reason(reason: Optional[str]) -> str:
    from config import REQUEST_TYPE_SCHEDULE_STATUS

    if reason and reason.startswith("Day-off: "):
        req_type = reason[len("Day-off: ") :].strip()
        return REQUEST_TYPE_SCHEDULE_STATUS.get(req_type, "bumped")
    return "bumped"


def _officer_day_status(
    officer: Dict,
    target_date: date,
    bumped_by_date: Dict[str, Set[int]],
    covering_by_date: Dict[str, Set[int]],
    swapped_by_date: Optional[Dict[str, Set[int]]] = None,
    bumped_status_by_date: Optional[Dict[str, Dict[int, str]]] = None,
) -> str:
    date_str = target_date.strftime("%Y-%m-%d")
    officer_id = officer["id"]
    if swapped_by_date and officer_id in swapped_by_date.get(date_str, ()):
        return "swapped"
    if officer_id in bumped_by_date.get(date_str, ()):
        if bumped_status_by_date:
            return bumped_status_by_date.get(date_str, {}).get(officer_id, "bumped")
        return "bumped"
    if officer_id in covering_by_date.get(date_str, ()):
        return "covering"
    if _scheduling().officer_base_rotation_working(officer, target_date):
        return "working"
    return "off"


def _officer_history_reason(cursor, officer_id: int) -> Optional[str]:
    history_checks = [
        ("day off requests", "SELECT 1 FROM day_off_requests WHERE officer_id = ? LIMIT 1", (officer_id,)),
        ("payroll entries", "SELECT 1 FROM payroll_entries WHERE officer_id = ? LIMIT 1", (officer_id,)),
        ("notifications", "SELECT 1 FROM notifications WHERE recipient_officer_id = ? LIMIT 1", (officer_id,)),
        (
            "schedule overrides",
            "SELECT 1 FROM schedule_overrides WHERE original_officer_id = ? OR replacement_officer_id = ? LIMIT 1",
            (officer_id, officer_id),
        ),
        (
            "shift swaps",
            "SELECT 1 FROM shift_swaps WHERE officer1_id = ? OR officer2_id = ? LIMIT 1",
            (officer_id, officer_id),
        ),
    ]
    for label, query, params in history_checks:
        cursor.execute(query, params)
        if cursor.fetchone():
            return label
    return None


def officer_shift_hours(officer: Dict) -> float:
    """Generator fact: hours for an officer's assigned shift band."""
    start = officer["shift_start"].split(":")
    end = officer["shift_end"].split(":")
    start_m = int(start[0]) * 60 + int(start[1])
    end_m = int(end[0]) * 60 + int(end[1])
    if end_m <= start_m:
        end_m += 24 * 60
    return round((end_m - start_m) / 60, 2)


_officer_shift_hours = officer_shift_hours  # back-compat


def officer_work_days_per_cycle(officer: Dict) -> int:
    """Generator fact: on-duty days in the active rotation cycle for this officer's squad."""
    count = 0
    cycle_length = get_active_rotation_cycle_length()
    for day in range(1, cycle_length + 1):
        if _scheduling().get_squad_on_duty(day) == officer["squad"]:
            count += 1
    return count


_officer_work_days_per_cycle = officer_work_days_per_cycle  # back-compat


def _rotation_only_status(officer: Dict, target_date: date) -> str:
    if _scheduling().officer_base_rotation_working(officer, target_date):
        return "working"
    return "off"


def shift_hours(shift_start: str, shift_end: str) -> float:
    """Generator fact: length in hours of a shift start/end pair (overnight-aware)."""
    start_h, start_m = map(int, shift_start.split(":"))
    end_h, end_m = map(int, shift_end.split(":"))
    start_mins = start_h * 60 + start_m
    end_mins = end_h * 60 + end_m
    if end_mins <= start_mins:
        end_mins += 24 * 60
    return round((end_mins - start_mins) / 60, 2)


_shift_hours = shift_hours  # back-compat


def get_monthly_rotation_summary(year: int, month: int) -> List[Dict]:
    return _get_monthly_rotation_base_only(year, month)


def get_officer_work_dates_from_summary(
    officer_id: int,
    summary: List[Dict],
) -> Set[str]:
    """ISO dates in a monthly summary where the officer is scheduled on duty."""
    if not officer_id or not summary:
        return set()
    officer = get_officer_by_id(officer_id)
    if not officer:
        return set()

    dates: Set[str] = set()
    for entry in summary:
        target = entry["date"]
        rows = entry.get("snapshot_rows")
        if rows:
            if any(
                r.get("officer_id") == officer_id and r.get("status") in _scheduling()._OFFICER_WORKING_STATUSES
                for r in rows
            ):
                dates.add(target.isoformat())
        elif get_officer_day_status(officer_id, target) in _scheduling()._OFFICER_WORKING_STATUSES:
            dates.add(target.isoformat())
    return dates


def get_schedule_conflicts(
    start_date: date,
    end_date: date,
    officer_id: Optional[int] = None,
) -> Dict:
    from logic.analytics import get_schedule_conflicts as _conflicts

    return _conflicts(start_date, end_date, officer_id=officer_id)


def _load_covering_shift_starts_for_range(start_date: date, end_date: date) -> Dict[str, Dict[int, str]]:
    """Date -> replacement_officer_id -> covered_shift_start for rest/compliance math."""
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")
    out: Dict[str, Dict[int, str]] = {}
    with connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT override_date, replacement_officer_id, covered_shift_start
            FROM schedule_overrides
            WHERE override_date >= ? AND override_date <= ?
              AND replacement_officer_id IS NOT NULL
              AND covered_shift_start IS NOT NULL
            """,
            (start_str, end_str),
        )
        for row in cursor.fetchall():
            day_key = row["override_date"]
            repl_id = row["replacement_officer_id"]
            covered = row["covered_shift_start"]
            if repl_id is not None and covered:
                out.setdefault(day_key, {})[repl_id] = covered
    return out


def get_officer_effective_shift_band(officer_id: int, target_date: date) -> Optional[Tuple[str, str]]:
    status = get_officer_day_status(officer_id, target_date)
    if status not in ("working", "covering", "swapped"):
        return None
    officer = get_officer_by_id(officer_id)
    if not officer:
        return None
    shift_start = officer["shift_start"]
    shift_end = officer["shift_end"]
    if status == "covering":
        with connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT covered_shift_start FROM schedule_overrides
                WHERE override_date = ? AND replacement_officer_id = ?
                LIMIT 1
            """,
                (target_date.isoformat(), officer_id),
            )
            row = cursor.fetchone()
        if row and row["covered_shift_start"]:
            shift_start = row["covered_shift_start"]
            shift_end = _scheduling().shift_end_for_start_active(shift_start)
    return shift_start, shift_end
