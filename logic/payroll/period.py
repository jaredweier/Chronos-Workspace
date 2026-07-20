"""Pay-period calendar, locks, and period helpers."""

"""Payroll entries, timecard, and pay-period management."""

from datetime import date, timedelta
from typing import Dict, Optional, Tuple

from config import (
    DATE_INPUT_HINT,
    PAY_PERIOD_BASE_DATE,
    PAY_PERIOD_LENGTH,
)
from database import connection
from logic.operations import get_department_setting, set_department_setting
from logic.scheduling import (
    get_current_cycle_window,
)
from logic.users import log_audit_action
from validators import (
    format_date,
    parse_date,
)


def get_pay_period(reference: Optional[date] = None) -> Tuple[date, date]:
    """Return start/end for the 14-day pay period containing reference (default today)."""
    ref = reference or date.today()
    period_index = (ref - PAY_PERIOD_BASE_DATE).days // PAY_PERIOD_LENGTH
    start = PAY_PERIOD_BASE_DATE + timedelta(days=period_index * PAY_PERIOD_LENGTH)
    end = start + timedelta(days=PAY_PERIOD_LENGTH - 1)
    return start, end


def normalize_pay_period_start(value: Optional[date]) -> date:
    """Map any date to the start of its containing pay period."""
    start, _ = get_pay_period(value)
    return start


def format_pay_period_label(period_start: date, period_end: Optional[date] = None) -> str:
    """Human-readable pay period range including 14-day length."""
    if period_end is None:
        _, period_end = get_pay_period(period_start)
    return f"{format_date(period_start)} – {format_date(period_end)} (14 days)"


def is_current_pay_period(period_start: date, reference: Optional[date] = None) -> bool:
    current_start, _ = get_pay_period(reference)
    norm_start, _ = get_pay_period(period_start)
    return norm_start == current_start


def pay_period_for_shift_start(shift_start_date: date) -> Tuple[date, date]:
    """Hours belong to the pay period in which the shift started (not when it ended)."""
    return get_pay_period(shift_start_date)


def search_pay_period_by_date(query: str) -> Dict:
    """Find the 14-day pay period that contains a shift-start date."""
    try:
        target = parse_date(query)
    except ValueError:
        return {"success": False, "message": f"Enter a date as {DATE_INPUT_HINT}"}
    start, end = get_pay_period(target)
    return {
        "success": True,
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "label": format_pay_period_label(start, end),
        "shift_start_date": target.isoformat(),
    }


def list_pay_periods_catalog(
    officer_id: Optional[int] = None,
    *,
    reference: Optional[date] = None,
    limit: Optional[int] = None,
) -> Dict:
    """List pay periods from department anchor through reference for search/history pickers."""
    ref = reference or date.today()
    current_start, current_end = get_pay_period(ref)
    with connection() as conn:
        cursor = conn.cursor()
        if officer_id:
            cursor.execute(
                """
                SELECT pay_period_start AS period_start,
                       SUM(hours_worked) AS total_hours,
                       COUNT(*) AS line_count
                FROM timecard_entries
                WHERE officer_id = ?
                GROUP BY pay_period_start
            """,
                (officer_id,),
            )
        else:
            cursor.execute(
                """
                SELECT pay_period_start AS period_start,
                       SUM(hours_worked) AS total_hours,
                       COUNT(DISTINCT officer_id) AS officer_count
                FROM timecard_entries
                GROUP BY pay_period_start
            """
            )
        data_by_start = {row["period_start"]: dict(row) for row in cursor.fetchall()}

    periods = []
    start = current_start
    while start >= PAY_PERIOD_BASE_DATE:
        _, end = get_pay_period(start)
        key = start.isoformat()
        stats = data_by_start.get(key, {})
        periods.append(
            {
                "period_start": key,
                "period_end": end.isoformat(),
                "label": format_pay_period_label(start, end),
                "is_current": start == current_start,
                "has_data": key in data_by_start,
                "total_hours": round(float(stats.get("total_hours") or 0), 2),
                "line_count": stats.get("line_count") or stats.get("officer_count") or 0,
            }
        )
        if limit and len(periods) >= limit:
            break
        start, _ = get_adjacent_pay_period(start, -1)

    return {
        "success": True,
        "current_period_start": current_start.isoformat(),
        "current_period_end": current_end.isoformat(),
        "periods": periods,
    }


def get_adjacent_pay_period(period_start: date, direction: int) -> Tuple[date, date]:
    """Return the pay period before (-1) or after (+1) the period containing period_start."""
    start, end = get_pay_period(period_start)
    if direction < 0:
        return get_pay_period(start - timedelta(days=1))
    if direction > 0:
        return get_pay_period(end + timedelta(days=1))
    return start, end


def count_pay_periods_in_year(year: Optional[int] = None) -> int:
    """Count pay periods whose start date falls in the calendar year."""
    year = year or date.today().year
    start, _ = get_pay_period(date(year, 1, 1))
    if start.year < year:
        while start.year < year:
            start, _ = get_adjacent_pay_period(start, 1)
    if start.year > year:
        return 0
    count = 0
    current = start
    while current.year == year:
        count += 1
        current, _ = get_adjacent_pay_period(current, 1)
    return count


def annual_salary_to_per_pay_period(annual_salary: float, year: Optional[int] = None) -> float:
    """Spread annual salary evenly across pay periods in the year."""
    periods = count_pay_periods_in_year(year)
    if periods <= 0 or annual_salary <= 0:
        return 0.0
    return round(annual_salary / periods, 2)


def monthly_pay_to_per_pay_period(monthly: float, year: Optional[int] = None) -> float:
    """Monthly salary × 12, dispersed evenly across pay periods in the year."""
    return annual_salary_to_per_pay_period(monthly * 12, year)


def suggested_hourly_rate_for_title(job_title: Optional[str]) -> Optional[float]:
    """Hourly base rate from title compensation config (monthly × 12 ÷ 2008)."""
    from logic.operations import get_position_pay_rates
    from validators import normalize_officer_job_title

    title = normalize_officer_job_title(job_title)
    if not title:
        return None
    entry = (get_position_pay_rates().get("rates") or {}).get(title)
    if not entry:
        return None
    hourly = float(entry.get("hourly_equivalent") or 0.0)
    return hourly if hourly > 0 else None


def get_adjacent_cycle_window(cycle_start: date, direction: int) -> Tuple[date, date]:
    """Return the rotation cycle before (-1) or after (+1) the cycle containing cycle_start."""
    start, end = get_current_cycle_window(cycle_start)
    if direction < 0:
        return get_current_cycle_window(start - timedelta(days=1))
    if direction > 0:
        return get_current_cycle_window(end + timedelta(days=1))
    return start, end


def is_future_cycle_window(cycle_start: date, reference: Optional[date] = None) -> bool:
    current_start, _ = get_current_cycle_window(reference)
    return cycle_start > current_start


def is_future_pay_period(period_start: date, reference: Optional[date] = None) -> bool:
    current_start, _ = get_pay_period(reference)
    norm_start, _ = get_pay_period(period_start)
    return norm_start > current_start


def lock_pay_period(period_start: Optional[date] = None, user_id: Optional[int] = None) -> Dict:
    from logic.requests import _notify_supervisors

    start, end = get_pay_period(period_start)
    set_department_setting("locked_pay_period_start", start.isoformat(), user_id)
    set_department_setting("locked_pay_period_end", end.isoformat(), user_id)
    log_audit_action("pay_period.lock", "pay_period", None, user_id, start.isoformat())
    _notify_supervisors(
        "Payroll",
        "Pay period locked",
        f"{format_date(start)} – {format_date(end)} is locked for edits and imports",
        related_type="pay_period",
    )
    return {"success": True, "period_start": start.isoformat(), "period_end": end.isoformat()}


def unlock_pay_period(user_id: Optional[int] = None) -> Dict:
    from logic.requests import _notify_supervisors

    set_department_setting("locked_pay_period_start", "", user_id)
    set_department_setting("locked_pay_period_end", "", user_id)
    log_audit_action("pay_period.unlock", "pay_period", None, user_id)
    _notify_supervisors("Payroll", "Pay period unlocked", "Timecard edits and imports are re-enabled")
    return {"success": True}


def is_pay_period_locked(period_start: Optional[date] = None) -> bool:
    start, _ = get_pay_period(period_start)
    locked = get_department_setting("locked_pay_period_start", "")
    return bool(locked) and locked == start.isoformat()


def get_pay_period_lock_reminder(
    *,
    days_before_end: int = 3,
    reference: Optional[date] = None,
) -> Dict:
    """Supervisor reminder when the current pay period is ending soon and not locked."""
    today = reference or date.today()
    start, end = get_pay_period(today)
    if not is_current_pay_period(start, reference=today):
        return {
            "success": True,
            "needs_reminder": False,
            "days_until_end": None,
            "period_start": start.isoformat(),
            "period_end": end.isoformat(),
            "locked": is_pay_period_locked(start),
        }
    days_left = (end - today).days
    locked = is_pay_period_locked(start)
    return {
        "success": True,
        "needs_reminder": not locked and 0 <= days_left <= days_before_end,
        "days_until_end": days_left,
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "locked": locked,
        "days_before_end": days_before_end,
    }


def get_pay_period_history(limit: int = 6, officer_id: Optional[int] = None) -> Dict:
    """Summarize recent pay periods from timecard and payroll data."""
    with connection() as conn:
        cursor = conn.cursor()
        if officer_id:
            cursor.execute(
                """
                SELECT pay_period_start AS period_start,
                       SUM(hours_worked) AS total_hours,
                       1 AS officer_count
                FROM timecard_entries
                WHERE officer_id = ?
                GROUP BY pay_period_start
                ORDER BY pay_period_start DESC
                LIMIT ?
            """,
                (officer_id, limit),
            )
        else:
            cursor.execute(
                """
                SELECT pay_period_start AS period_start,
                       SUM(hours_worked) AS total_hours,
                       COUNT(DISTINCT officer_id) AS officer_count
                FROM timecard_entries
                GROUP BY pay_period_start
                ORDER BY pay_period_start DESC
                LIMIT ?
            """,
                (limit,),
            )
        rows = [dict(r) for r in cursor.fetchall()]
        for row in rows:
            p_start = row["period_start"]
            _, p_end = get_pay_period(parse_date(p_start))
            row["period_end"] = p_end.isoformat()
            if officer_id:
                cursor.execute(
                    """
                    SELECT COALESCE(SUM(calculated_pay), 0) AS total_pay
                    FROM payroll_entries
                    WHERE officer_id = ? AND pay_period_start = ?
                """,
                    (officer_id, p_start),
                )
            else:
                cursor.execute(
                    """
                    SELECT COALESCE(SUM(calculated_pay), 0) AS total_pay
                    FROM payroll_entries
                    WHERE pay_period_start = ?
                """,
                    (p_start,),
                )
            row["total_pay"] = round(cursor.fetchone()["total_pay"] or 0, 2)
            row["total_hours"] = round(row["total_hours"] or 0, 2)
            row["locked"] = is_pay_period_locked(parse_date(p_start))
    return {"success": True, "periods": rows}
