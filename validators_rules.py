"""Schedule / day-off / rest / night-min validators (validators split)."""

from __future__ import annotations

from datetime import date
from typing import Optional

from config import DATE_INPUT_HINT, NIGHT_MINIMUM_OFFICERS
from validators import (
    REQUESTABLE_STATUSES,
    SWAP_REQUESTABLE_STATUSES,
    ValidationResult,
)
from validators_dates import format_date, parse_date


def _night_shift_starts() -> set:
    from logic.staffing_config import get_active_night_shift_starts

    return get_active_night_shift_starts()


def is_officer_active(officer: dict) -> bool:
    return officer.get("active") == 1


def is_night_shift(shift_start: str) -> bool:
    return shift_start in _night_shift_starts()


def applies_night_minimum(target_date: date, shift_start: str, is_high_risk_night) -> bool:
    """Night staffing rules apply only to night shifts on Fri/Sat."""
    return is_high_risk_night(target_date) and is_night_shift(shift_start)


def validate_cycle_date(target_date: date) -> ValidationResult:
    from logic.rotation_config import get_active_rotation_base_date

    base_date = get_active_rotation_base_date()
    if target_date < base_date:
        return ValidationResult.fail(
            f"Date {format_date(target_date)} is before rotation base {format_date(base_date)}"
        )
    return ValidationResult.pass_()


def validate_officer_working(is_working: bool, request_date: date) -> ValidationResult:
    if not is_working:
        return ValidationResult.fail(f"Officer is not scheduled to work on {format_date(request_date)}")
    return ValidationResult.pass_()


def validate_request_status(status: str, action: str) -> ValidationResult:
    if action in ("approve", "reject") and status not in REQUESTABLE_STATUSES:
        allowed = ", ".join(REQUESTABLE_STATUSES)
        return ValidationResult.fail(f"Cannot {action} request with status '{status}' (only {allowed} allowed)")
    return ValidationResult.pass_()


def validate_no_duplicate_pending(has_pending: bool, officer_name: str, request_date: str) -> ValidationResult:
    if has_pending:
        return ValidationResult.fail(f"{officer_name} already has a pending request for {format_date(request_date)}")
    return ValidationResult.pass_()


def validate_day_off_request(
    officer: Optional[dict],
    request_date: str,
) -> ValidationResult:
    if not officer:
        return ValidationResult.fail("Officer not found")
    if not is_officer_active(officer):
        return ValidationResult.fail("Officer is inactive")

    try:
        parsed = parse_date(request_date)
    except ValueError:
        return ValidationResult.fail(f"Date must be {DATE_INPUT_HINT}")

    cycle_check = validate_cycle_date(parsed)
    if not cycle_check.ok:
        return cycle_check

    return ValidationResult.pass_()


def validate_request_type(request_type: str) -> ValidationResult:
    from config import DAY_OFF_REQUEST_TYPES

    normalized = (request_type or "").strip()
    if not normalized:
        return ValidationResult.fail("Request type is required")
    if normalized not in DAY_OFF_REQUEST_TYPES:
        allowed = ", ".join(DAY_OFF_REQUEST_TYPES)
        return ValidationResult.fail(f"Request type must be one of: {allowed}")
    return ValidationResult.pass_()


def _officer_unavailable_on_date(officer_id: int, target_date: date) -> bool:
    from database import connection

    date_str = target_date.isoformat()
    with connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT 1 FROM officer_availability
            WHERE officer_id = ? AND unavailable_date = ?
        """,
            (officer_id, date_str),
        )
        return cursor.fetchone() is not None


def validate_process_day_off(
    request: dict,
    officer: Optional[dict],
    action: str,
) -> ValidationResult:
    if not request:
        return ValidationResult.fail("Request not found")

    status_check = validate_request_status(request.get("status", ""), action)
    if not status_check.ok:
        return status_check

    if action == "reject":
        return ValidationResult.pass_()

    if not officer:
        return ValidationResult.fail("Officer not found")

    return ValidationResult.pass_()


def validate_swap_status(status: str, action: str) -> ValidationResult:
    if action in ("approve", "reject") and status not in SWAP_REQUESTABLE_STATUSES:
        allowed = ", ".join(SWAP_REQUESTABLE_STATUSES)
        return ValidationResult.fail(f"Cannot {action} swap with status '{status}' (only {allowed} allowed)")
    return ValidationResult.pass_()


def validate_process_shift_swap(swap: Optional[dict], action: str) -> ValidationResult:
    if not swap:
        return ValidationResult.fail("Swap request not found")
    status_check = validate_swap_status(swap.get("status", ""), action)
    if not status_check.ok:
        return status_check
    return ValidationResult.pass_()


def night_minimum_violation(current_count: int) -> bool:
    """True if removing one officer would drop below minimum."""
    return current_count <= NIGHT_MINIMUM_OFFICERS


def validate_minimum_rest_gap(
    gap_hours: Optional[float],
    min_hours: float,
    context: str = "",
) -> ValidationResult:
    """True if gap_hours is None (no adjacent shift) or meets minimum rest."""
    if gap_hours is None:
        return ValidationResult.pass_()
    if gap_hours < min_hours:
        prefix = f"{context}: " if context else ""
        return ValidationResult.fail(f"{prefix}{gap_hours:.1f}h between shifts (minimum {min_hours:.0f}h required)")
    return ValidationResult.pass_()


def validate_comp_time_cap(current_hours: float, accrual_delta: float, max_hours: float = None) -> ValidationResult:
    """FLSA public-sector compensatory time accrual cap (default 480h)."""
    from config import FLSA_COMP_TIME_MAX_HOURS

    cap = max_hours if max_hours is not None else FLSA_COMP_TIME_MAX_HOURS
    if accrual_delta <= 0:
        return ValidationResult.pass_()
    projected = current_hours + accrual_delta
    if projected > cap:
        return ValidationResult.fail(
            f"Comp time cap exceeded: {current_hours:.1f}h + {accrual_delta:.1f}h "
            f"exceeds FLSA maximum {cap:.0f}h — use Overtime Earned (cash) instead"
        )
    return ValidationResult.pass_()


def validate_consecutive_work_days(streak: int, max_days: int, context: str = "") -> ValidationResult:
    """Department fatigue rule — max consecutive scheduled work days."""
    if streak <= max_days:
        return ValidationResult.pass_()
    prefix = f"{context}: " if context else ""
    return ValidationResult.fail(f"{prefix}{streak} consecutive work day(s) exceeds limit of {max_days}")
