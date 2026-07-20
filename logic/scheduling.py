"""Generator brain: rotation, day status, rest, schedule matrix facade.

Scheduling *math* runs in scheduler_core (Rust) via logic/rust_bridge.py.
This module loads DB state, calls the bridge, and applies results to workflows.
Emergency Python math lives in logic/rust_fallback.py when Rust is not built.

Optimizer (bump / sim) lives in ``logic.coverage_optimizer``, ``logic.bump_optimizer``,
and ``logic.scheduling_sim`` — not re-exported here.
"""

from datetime import date, datetime, timedelta
from typing import Dict, Optional, Tuple

import config
from database import connection
from logic import rust_bridge, rust_fallback
from logic.officers import get_officer_by_id, get_officers_by_seniority
from logic.rotation_config import (
    get_active_rotation_base_date,
    get_active_rotation_cycle_length,
)
from logic.staffing_config import (
    get_active_shift_times,
)

_OFFICER_WORKING_STATUSES = frozenset({"working", "covering", "swapped", "training"})


def get_generated_schedule_day_context(target_date: date) -> Dict[int, Dict[str, str]]:
    """Generator fact: per-officer status + shift band (rotation + overrides, not stale snapshots)."""
    date_key = target_date.strftime("%Y-%m-%d")
    active = [o for o in get_officers_by_seniority() if o.get("active") == 1]
    statuses = batch_officer_day_status([(o["id"], target_date) for o in active])

    context: Dict[int, Dict[str, str]] = {}
    for officer in active:
        oid = officer["id"]
        context[oid] = {
            "status": statuses.get((oid, date_key), "off"),
            "shift_start": officer.get("shift_start") or "",
            "shift_end": officer.get("shift_end") or "",
        }

    with connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT replacement_officer_id, covered_shift_start
            FROM schedule_overrides
            WHERE override_date = ? AND replacement_officer_id IS NOT NULL
            """,
            (date_key,),
        )
        for row in cursor.fetchall():
            rid = row["replacement_officer_id"]
            if rid not in context or context[rid]["status"] != "covering":
                continue
            covered = row["covered_shift_start"]
            if covered:
                context[rid]["shift_start"] = covered
                context[rid]["shift_end"] = shift_end_for_start_active(covered)

    from logic.snapshots import get_schedule_snapshot

    for schedule_type in ("updated", "base"):
        snapshot = get_schedule_snapshot(target_date.year, target_date.month, schedule_type)
        if not snapshot:
            continue
        touched = False
        for row in snapshot.get("rows", []):
            if row.get("assignment_date") != date_key:
                continue
            oid = row["officer_id"]
            if oid not in context:
                continue
            row_status = row.get("status") or "off"
            if row_status not in _OFFICER_WORKING_STATUSES:
                continue
            touched = True
            if row_status in ("covering", "swapped", "training"):
                context[oid]["status"] = row_status
                assigned_start = row.get("assigned_shift_start") or row.get("home_shift_start") or ""
                assigned_end = row.get("assigned_shift_end") or row.get("home_shift_end") or ""
                if assigned_start:
                    context[oid]["shift_start"] = assigned_start
                if assigned_end:
                    context[oid]["shift_end"] = assigned_end
        if touched:
            break

    return context


def officer_schedule_working(day_context: Dict[str, str]) -> bool:
    """Generator fact: day-context status counts as on-duty for coverage rules."""
    return day_context.get("status") in _OFFICER_WORKING_STATUSES


def normalize_shift_band(shift_start: str) -> str:
    """Generator fact: snap a shift start label to the active staffing band."""
    from logic.staffing_config import normalize_shift_start_to_active

    return normalize_shift_start_to_active(shift_start or "")


def officer_scheduled_shift_start(officer: Dict, day_context: Dict[str, str]) -> str:
    return day_context.get("shift_start") or officer.get("shift_start") or ""


def replacement_shift_start_for_rules(officer: Dict, day_context: Dict[str, str]) -> str:
    """Generator fact: which band an officer is treated as covering under bump rules."""
    if officer_schedule_working(day_context):
        raw = officer_scheduled_shift_start(officer, day_context)
    else:
        raw = officer.get("shift_start") or ""
    return normalize_shift_band(raw)


# Private aliases (optimizer/payroll historically imported these)
_get_generated_schedule_day_context = get_generated_schedule_day_context
_officer_schedule_working = officer_schedule_working
_normalize_shift_band = normalize_shift_band
_officer_scheduled_shift_start = officer_scheduled_shift_start
_replacement_shift_start_for_rules = replacement_shift_start_for_rules


def get_current_cycle_window(reference: Optional[date] = None) -> Tuple[date, date]:
    """Return start/end dates for the active rotation cycle containing reference (default today)."""
    ref = reference or date.today()
    cycle_length = get_active_rotation_cycle_length()
    cycle_day = get_cycle_day(ref)
    start = ref - timedelta(days=cycle_day - 1)
    end = start + timedelta(days=cycle_length - 1)
    return start, end


def get_cycle_day(target_date: date) -> int:
    return rust_bridge.get_cycle_day(
        target_date,
        get_active_rotation_base_date(),
        get_active_rotation_cycle_length(),
    )


def get_squad_on_duty(cycle_day: int) -> str:
    return rust_bridge.get_squad_on_duty(cycle_day)


def officer_base_rotation_working(officer: Dict, target_date: date) -> bool:
    """Rotation schedule before overrides: per-officer pattern, patrol A/B, or command Mon–Fri."""
    from validators import officer_has_assignment

    if not officer_has_assignment(officer):
        return False

    # Per-officer multi-block / fixed pattern + phase (customizable rotations)
    pattern_text = (officer.get("rotation_pattern") or "").strip()
    if pattern_text:
        try:
            from logic.rotation_patterns import build_pattern

            phase = int(officer.get("rotation_phase") or 0)
            pattern = build_pattern(pattern_text, phase=phase)
            base = get_active_rotation_base_date()
            day_index = (target_date - base).days
            if day_index < 0:
                return False
            cycle_day = (day_index % pattern.cycle_length) + 1
            return pattern.is_working(cycle_day)
        except (ValueError, TypeError):
            pass

    rust_working = rust_bridge.officer_rotation_working(
        officer.get("squad") or "",
        officer.get("shift_start") or "",
        officer.get("active") == 1,
        officer.get("job_title") or "",
        target_date,
        get_active_rotation_base_date(),
        get_active_rotation_cycle_length(),
    )
    if rust_working is not None:
        return rust_working
    from validators import officer_uses_command_staff_schedule

    if officer_uses_command_staff_schedule(officer):
        return target_date.weekday() < 5
    squad = officer.get("squad")
    if not squad:
        return False
    return squad == get_squad_on_duty(get_cycle_day(target_date))


def is_officer_working_on_day(officer_id: int, target_date: date, squad: str = None) -> bool:
    officer = get_officer_by_id(officer_id)
    if not officer:
        return False
    if squad and officer.get("squad") != squad:
        return False
    return officer_base_rotation_working(officer, target_date)


def count_officers_on_shift_on_date(target_date: date, squad: str, shift_start: str) -> int:
    date_str = target_date.strftime("%Y-%m-%d")
    counts = get_shift_coverage_counts_for_range(target_date, target_date)
    return counts.get((date_str, squad, shift_start), 0)


def get_shift_coverage_counts_for_range(
    start_date: date,
    end_date: date,
) -> Dict[Tuple[str, str, str], int]:
    """Batch shift headcount: key (YYYY-MM-DD, squad, shift_start) -> count."""
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")
    shift_starts = [start for start, _ in get_active_shift_times().values()]

    with connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, squad, shift_start, active, job_title FROM officers WHERE active = 1
        """)
        officers = [dict(row) for row in cursor.fetchall()]
        cursor.execute(
            """
            SELECT override_date, original_officer_id, replacement_officer_id, covered_shift_start
            FROM schedule_overrides
            WHERE override_date >= ? AND override_date <= ?
        """,
            (start_str, end_str),
        )
        overrides = [dict(row) for row in cursor.fetchall()]

    override_rows = [
        (
            row["override_date"],
            row["original_officer_id"],
            row["replacement_officer_id"],
            row["covered_shift_start"],
        )
        for row in overrides
    ]
    rust_counts = rust_bridge.compute_coverage_counts(
        officers,
        override_rows,
        start_date,
        end_date,
        shift_starts,
        get_active_rotation_base_date(),
        get_active_rotation_cycle_length(),
    )
    if rust_counts is not None:
        return rust_counts

    return rust_fallback.python_compute_coverage_counts(
        officers,
        override_rows,
        start_date,
        end_date,
        shift_starts,
        get_cycle_day_fn=get_cycle_day,
        get_squad_on_duty_fn=get_squad_on_duty,
        normalize_shift_band_fn=_normalize_shift_band,
        officer_base_rotation_working_fn=officer_base_rotation_working,
    )


def get_shift_number(shift_start: str) -> int:
    for num, (start, _) in get_active_shift_times().items():
        if start == shift_start:
            return num
    return 0


def resolve_officer_shift_band(
    officer_id: int,
    target_date: date,
    *,
    home_shift_start: Optional[str] = None,
    home_shift_end: Optional[str] = None,
) -> Tuple[str, str]:
    """Shift band for bump/coverage — generated schedule assignment, then home shift, from active staffing."""
    from logic.staffing_config import (
        get_active_shift_length_hours,
        get_active_shift_time_values,
        shift_end_from_length,
    )

    context = _get_generated_schedule_day_context(target_date).get(officer_id, {})
    start = context.get("shift_start") or home_shift_start or ""
    end = context.get("shift_end") or home_shift_end or ""
    if not start:
        officer = get_officer_by_id(officer_id)
        if officer:
            start = officer.get("shift_start") or ""
            end = officer.get("shift_end") or ""

    from logic.staffing_config import normalize_shift_start_to_active

    active_values = get_active_shift_time_values()
    if start:
        normalized = normalize_shift_start_to_active(start)
        for band_start, band_end in active_values:
            if band_start == normalized:
                return band_start, band_end if band_end else shift_end_from_length(
                    band_start, get_active_shift_length_hours()
                )
    if start and not end:
        end = shift_end_from_length(normalize_shift_start_to_active(start), get_active_shift_length_hours())
    return normalize_shift_start_to_active(start), end


def shift_end_for_start_active(shift_start: str) -> str:
    """Generator fact: end time for a start band from active shift times / length."""
    from logic.staffing_config import get_active_shift_length_hours, shift_end_from_length

    for start, end in get_active_shift_times().values():
        if start == shift_start:
            return end
    if shift_start:
        return shift_end_from_length(shift_start, get_active_shift_length_hours())
    return shift_start


_shift_end_for_start = shift_end_for_start_active  # back-compat; prefer shift_assignment.shift_end_for_start


def _shift_bounds(target_date: date, shift_start: str, shift_end: str) -> Tuple[datetime, datetime]:
    hour_s, min_s = map(int, shift_start.split(":"))
    hour_e, min_e = map(int, shift_end.split(":"))
    start_dt = datetime(target_date.year, target_date.month, target_date.day, hour_s, min_s)
    end_dt = datetime(target_date.year, target_date.month, target_date.day, hour_e, min_e)
    if end_dt <= start_dt:
        end_dt += timedelta(days=1)
    return start_dt, end_dt


def compute_minimum_rest_gap(
    officer_id: int,
    assignment_date: date,
    new_shift_start: str,
    new_shift_end: str,
) -> Optional[float]:
    officer = get_officer_by_id(officer_id)
    if officer:
        window_start = assignment_date - timedelta(days=1)
        window_end = assignment_date + timedelta(days=1)
        bumped_by_date, covering_by_date, swapped_by_date, bumped_status_by_date = _load_override_maps_for_range(
            window_start, window_end
        )
        covering_starts = _load_covering_shift_starts_for_range(window_start, window_end)
        rust_gap = rust_bridge.minimum_rest_gap(
            officer_id,
            assignment_date,
            new_shift_start,
            new_shift_end,
            officer.get("shift_start") or "",
            officer.get("shift_end") or "",
            bumped_by_date,
            covering_by_date,
            swapped_by_date,
            bumped_status_by_date,
            covering_starts,
            list(get_active_shift_times().values()),
            get_active_rotation_base_date(),
            get_active_rotation_cycle_length(),
        )
        if rust_gap is not None:
            return rust_gap

    new_start_dt, new_end_dt = _shift_bounds(assignment_date, new_shift_start, new_shift_end)
    min_gap = None
    for delta in (-1, 1):
        adj_date = assignment_date + timedelta(days=delta)
        band = get_officer_effective_shift_band(officer_id, adj_date)
        if not band:
            continue
        adj_start_dt, adj_end_dt = _shift_bounds(adj_date, band[0], band[1])
        if delta == -1:
            gap = (new_start_dt - adj_end_dt).total_seconds() / 3600.0
        else:
            gap = (adj_start_dt - new_end_dt).total_seconds() / 3600.0
        if min_gap is None or gap < min_gap:
            min_gap = gap
    return min_gap


def officer_meets_minimum_rest(
    officer_id: int,
    assignment_date: date,
    shift_start: str,
    shift_end: str,
) -> bool:
    from validators import validate_minimum_rest_gap

    gap = compute_minimum_rest_gap(officer_id, assignment_date, shift_start, shift_end)
    return validate_minimum_rest_gap(gap, config.MIN_REST_HOURS_BETWEEN_SHIFTS).ok


def describe_minimum_rest_violation(
    officer_id: int,
    assignment_date: date,
    shift_start: str,
    shift_end: str,
    officer_name: Optional[str] = None,
) -> Optional[str]:
    """Return a user-facing rest violation message, or None if rest is satisfied."""
    if officer_meets_minimum_rest(officer_id, assignment_date, shift_start, shift_end):
        return None
    gap = compute_minimum_rest_gap(officer_id, assignment_date, shift_start, shift_end)
    label = officer_name or "Officer"
    gap_text = f"{gap:.1f}h" if gap is not None else "insufficient rest"
    return (
        f"Minimum rest violation: {label} has {gap_text} between shifts "
        f"(minimum {config.MIN_REST_HOURS_BETWEEN_SHIFTS:.0f}h) — supervisor override required"
    )


# --- Generator matrix (home: scheduling_matrix) ---
from logic.scheduling_matrix import (  # noqa: E402,F401
    _get_monthly_rotation_base_only,
    _load_covering_shift_starts_for_range,
    _load_override_maps_for_range,
    _officer_day_status,
    _officer_history_reason,
    _officer_shift_hours,
    _officer_work_days_per_cycle,
    _rotation_only_status,
    _schedule_status_for_override_reason,
    _shift_hours,
    batch_officer_day_status,
    build_schedule_matrix,
    get_monthly_rotation_summary,
    get_officer_day_status,
    get_officer_effective_shift_band,
    get_officer_work_dates_from_summary,
    get_schedule_conflicts,
    officer_shift_hours,
    officer_work_days_per_cycle,
    shift_hours,
)
