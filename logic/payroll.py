"""Payroll entries, timecard, and pay-period management."""

import json
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

from config import (
    CALLBACK_MINIMUM_HOURS,
    DATE_INPUT_HINT,
    DAY_OFF_TIMECARD_DEFAULTS,
    DEFAULT_PAY_CODE_RULES,
    FLOAT_HOLIDAY_ANNUAL_HOURS,
    HOLIDAY_ANNUAL_HOURS,
    PAY_CODE_SETTINGS_KEY,
    PAY_PERIOD_BASE_DATE,
    PAY_PERIOD_LENGTH,
    PAYROLL_ENTRY_TYPES,
    SICK_MONTHLY_ACCRUAL_HOURS,
    TIMECARD_APPROVAL_STATUSES,
    TIMECARD_ENTRY_TYPES,
    TIMECARD_REGULAR_TYPE,
)
from database import get_connection
from logic.officers import get_officer_by_id, get_officers_by_seniority
from logic.operations import get_department_setting, set_department_setting
from logic.scheduling import (
    _officer_shift_hours,
    _officer_work_days_per_cycle,
    _shift_hours,
    get_current_cycle_window,
    get_officer_day_status,
)
from logic.snapshots import get_schedule_snapshot
from logic.users import log_audit_action
from models import PayCalculationResult
from validators import (
    format_date,
    format_pay_code_formula,
    is_overnight_shift,
    parse_date,
    storage_date_str,
    validate_pay_code_comp_ratio,
    validate_pay_code_rate_multiplier,
)


def get_pay_code_rules() -> Dict:
    """Return merged department pay-code calculation rules."""
    stored: Dict = {}
    raw = get_department_setting(PAY_CODE_SETTINGS_KEY, "")
    if raw:
        try:
            stored = json.loads(raw)
        except json.JSONDecodeError:
            stored = {}

    global_cfg = dict(DEFAULT_PAY_CODE_RULES.get("global") or {})
    global_cfg.update(stored.get("global") or {})
    try:
        global_cfg["callback_minimum_hours"] = float(global_cfg.get("callback_minimum_hours", CALLBACK_MINIMUM_HOURS))
        global_cfg["default_overtime_multiplier"] = float(global_cfg.get("default_overtime_multiplier", 1.5))
    except (TypeError, ValueError):
        global_cfg["callback_minimum_hours"] = CALLBACK_MINIMUM_HOURS
        global_cfg["default_overtime_multiplier"] = 1.5

    codes: Dict[str, Dict] = {}
    stored_codes = stored.get("codes") or {}
    for entry_type, default in (DEFAULT_PAY_CODE_RULES.get("codes") or {}).items():
        merged = dict(default)
        merged.update(stored_codes.get(entry_type) or {})
        merged["rate_multiplier"] = float(merged.get("rate_multiplier", 1.0))
        merged["comp_bank_credit_ratio"] = float(merged.get("comp_bank_credit_ratio", 0.0) or 0.0)
        merged["premium_multiplier"] = float(merged.get("premium_multiplier", 0.0) or 0.0)
        merged["paid"] = bool(merged.get("paid", True))
        merged["formula"] = format_pay_code_formula(entry_type, merged)
        codes[entry_type] = merged

    return {"success": True, "global": global_cfg, "codes": codes}


def save_pay_code_rules(rules: Dict, user_id: Optional[int] = None) -> Dict:
    """Persist pay-code multipliers and global payroll calculation settings."""
    incoming_global = rules.get("global") or {}
    incoming_codes = rules.get("codes") or {}
    current = get_pay_code_rules()

    global_cfg = dict(current.get("global") or {})
    try:
        if "callback_minimum_hours" in incoming_global:
            hours = float(incoming_global["callback_minimum_hours"])
            if hours < 0 or hours > 24:
                return {"success": False, "message": "Callback minimum must be between 0 and 24 hours"}
            global_cfg["callback_minimum_hours"] = hours
        if "default_overtime_multiplier" in incoming_global:
            mult = float(incoming_global["default_overtime_multiplier"])
            check = validate_pay_code_rate_multiplier(mult, "Default overtime")
            if not check.ok:
                return {"success": False, "message": check.message}
            global_cfg["default_overtime_multiplier"] = mult
    except (TypeError, ValueError):
        return {"success": False, "message": "Global pay settings must be numeric"}

    codes: Dict[str, Dict] = {}
    for entry_type, default in (DEFAULT_PAY_CODE_RULES.get("codes") or {}).items():
        merged = dict(current["codes"].get(entry_type) or default)
        if entry_type in incoming_codes:
            merged.update(incoming_codes[entry_type] or {})
        try:
            rate_mult = float(merged.get("rate_multiplier", 1.0))
            comp_ratio = float(merged.get("comp_bank_credit_ratio", 0.0) or 0.0)
            premium = float(merged.get("premium_multiplier", 0.0) or 0.0)
        except (TypeError, ValueError):
            return {"success": False, "message": f"{entry_type}: numeric fields required"}

        for check in (
            validate_pay_code_rate_multiplier(rate_mult, entry_type),
            validate_pay_code_comp_ratio(comp_ratio, entry_type),
        ):
            if not check.ok:
                return {"success": False, "message": check.message}
        if premium < 0 or premium > 10:
            return {"success": False, "message": f"{entry_type}: premium multiplier must be between 0 and 10"}

        codes[entry_type] = {
            "rate_multiplier": round(rate_mult, 3),
            "paid": bool(merged.get("paid", True)),
            "comp_bank_credit_ratio": round(comp_ratio, 3),
            "debit_comp_bank": bool(merged.get("debit_comp_bank")),
            "debit_sick_bank": bool(merged.get("debit_sick_bank")),
            "debit_float_holiday_bank": bool(merged.get("debit_float_holiday_bank")),
            "debit_holiday_bank": bool(merged.get("debit_holiday_bank")),
            "uses_callback_minimum": bool(merged.get("uses_callback_minimum")),
            "premium_multiplier": round(premium, 3),
            "counts_as_overtime": bool(merged.get("counts_as_overtime")),
        }

    payload = {"global": global_cfg, "codes": codes}
    result = set_department_setting(PAY_CODE_SETTINGS_KEY, json.dumps(payload), user_id=user_id)
    if not result.get("success"):
        return result
    log_audit_action("payroll.pay_code_rules", "payroll", None, user_id, "updated")
    return {"success": True, "message": "Pay code calculations saved", "rules": get_pay_code_rules()}


def calculate_pay_for_entry(
    entry_type: str,
    hours: float,
    base_rate: float,
    night_differential_hours: float = 0.0,
    night_differential_rate: float = 1.0,
    is_holiday_overtime: bool = False,
    banks: Optional[Dict] = None,
) -> PayCalculationResult:
    from validators import validate_comp_time_cap

    result = PayCalculationResult(entry_type=entry_type)
    banks = banks or {}
    rules = get_pay_code_rules()
    code = rules.get("codes", {}).get(entry_type)
    if not code:
        result.message = f"Unknown payroll entry type: {entry_type}"
        return result

    global_cfg = rules.get("global") or {}
    calc_hours = hours
    if code.get("uses_callback_minimum"):
        from logic.labor_compliance import callback_payable_hours

        calc_hours = callback_payable_hours(
            hours,
            float(global_cfg.get("callback_minimum_hours", CALLBACK_MINIMUM_HOURS)),
        )

    if code.get("debit_comp_bank") and banks.get("comp_hours", 0) < calc_hours:
        result.message = f"Insufficient comp bank ({banks.get('comp_hours', 0):.1f}h available)"
        return result
    if code.get("debit_sick_bank") and banks.get("sick_hours", 0) < calc_hours:
        result.message = f"Insufficient sick bank ({banks.get('sick_hours', 0):.1f}h available)"
        return result
    if code.get("debit_float_holiday_bank") and banks.get("float_holiday_hours", 0) < calc_hours:
        result.message = f"Insufficient float holiday bank ({banks.get('float_holiday_hours', 0):.1f}h available)"
        return result
    if code.get("debit_holiday_bank") and banks.get("holiday_hours", 0) < calc_hours:
        result.message = f"Insufficient holiday bank ({banks.get('holiday_hours', 0):.1f}h available)"
        return result

    rate_mult = float(code.get("rate_multiplier", 1.0))
    if entry_type == "Holiday Overtime" and is_holiday_overtime:
        premium = float(code.get("premium_multiplier") or 0.0)
        if premium > 0:
            rate_mult = premium

    if code.get("paid", True) and rate_mult > 0:
        pay_amount = round(calc_hours * base_rate * rate_mult, 2)
        if code.get("counts_as_overtime"):
            result.overtime_hours = calc_hours
            result.overtime_pay = pay_amount
            result.total_pay = pay_amount
        else:
            result.regular_hours = calc_hours
            result.base_pay = pay_amount
            result.total_pay = pay_amount
    else:
        result.regular_hours = calc_hours
        result.total_pay = 0.0

    credit_ratio = float(code.get("comp_bank_credit_ratio", 0.0) or 0.0)
    if credit_ratio > 0:
        comp_delta = round(calc_hours * credit_ratio, 2)
        cap_check = validate_comp_time_cap(banks.get("comp_hours", 0), comp_delta)
        if not cap_check.ok:
            result.message = cap_check.message
            return result
        result.comp_bank_delta = comp_delta

    if code.get("debit_comp_bank"):
        result.comp_bank_delta = -calc_hours
    if code.get("debit_sick_bank"):
        result.sick_bank_delta = -calc_hours
    if code.get("debit_float_holiday_bank"):
        result.float_holiday_bank_delta = -calc_hours
    if code.get("debit_holiday_bank"):
        result.holiday_bank_delta = -calc_hours

    _apply_night_differential(result, night_differential_hours, base_rate, night_differential_rate)
    return result


def create_payroll_entry(
    officer_id: int,
    entry_date: str,
    entry_type: str,
    hours: float,
    night_differential_hours: float = 0.0,
    notes: str = "",
    is_holiday_overtime: bool = False,
) -> Dict:
    officer = get_officer_by_id(officer_id)
    if not officer:
        return {"success": False, "message": "Officer not found"}
    if hours <= 0:
        return {"success": False, "message": "Hours must be greater than zero"}

    try:
        parsed_date = parse_date(entry_date)
    except ValueError:
        return {"success": False, "message": f"Date must be {DATE_INPUT_HINT}"}

    pay_start, pay_end = pay_period_for_shift_start(parsed_date)
    if is_pay_period_locked(pay_start):
        return {"success": False, "message": "Pay period is locked — payroll entries disabled"}

    conn = get_connection()
    cursor = conn.cursor()
    try:
        banks = _ensure_officer_time_banks(cursor, officer_id, parsed_date)
        calc = calculate_pay_for_entry(
            entry_type,
            hours,
            officer["pay_rate"],
            night_differential_hours=night_differential_hours,
            night_differential_rate=officer.get("night_differential_rate", 1.0),
            is_holiday_overtime=is_holiday_overtime,
            banks=banks,
        )
        if calc.message:
            conn.rollback()
            return {"success": False, "message": calc.message}

        cursor.execute(
            """
            INSERT INTO payroll_entries
            (officer_id, entry_date, entry_type, hours, night_differential_hours, calculated_pay,
             comp_bank_delta, sick_bank_delta, float_holiday_bank_delta, holiday_bank_delta, notes,
             pay_period_start)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                officer_id,
                entry_date,
                entry_type,
                hours,
                night_differential_hours,
                calc.total_pay,
                calc.comp_bank_delta,
                calc.sick_bank_delta,
                calc.float_holiday_bank_delta,
                calc.holiday_bank_delta,
                notes,
                pay_start.isoformat(),
            ),
        )
        cursor.execute(
            """
            UPDATE officer_time_banks
            SET comp_hours = comp_hours + ?,
                sick_hours = sick_hours + ?,
                float_holiday_hours = float_holiday_hours + ?,
                holiday_hours = holiday_hours + ?
            WHERE officer_id = ?
        """,
            (
                calc.comp_bank_delta,
                calc.sick_bank_delta,
                calc.float_holiday_bank_delta,
                calc.holiday_bank_delta,
                officer_id,
            ),
        )
        conn.commit()
        return {
            "success": True,
            "entry_id": cursor.lastrowid,
            "calculated_pay": calc.total_pay,
            "breakdown": calc,
        }
    except Exception as e:
        conn.rollback()
        return {"success": False, "message": str(e)}
    finally:
        conn.close()


def get_payroll_entries(
    officer_id: Optional[int] = None,
    limit: int = 100,
    period_start: Optional[date] = None,
) -> List[Dict]:
    conn = get_connection()
    cursor = conn.cursor()
    query = """
        SELECT p.*, o.name AS officer_name
        FROM payroll_entries p
        JOIN officers o ON p.officer_id = o.id
    """
    conditions: List[str] = []
    params: List = []
    if officer_id:
        conditions.append("p.officer_id = ?")
        params.append(officer_id)
    if period_start:
        start, _ = get_pay_period(period_start)
        conditions.append("p.pay_period_start = ?")
        params.append(start.isoformat())
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY p.entry_date DESC, p.id DESC LIMIT ?"
    params.append(limit)
    cursor.execute(query, params)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


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
    conn = get_connection()
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
    conn.close()

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


def get_pay_period_history(limit: int = 6, officer_id: Optional[int] = None) -> Dict:
    """Summarize recent pay periods from timecard and payroll data."""
    conn = get_connection()
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
    conn.close()
    return {"success": True, "periods": rows}


_TIMECARD_WORKING_STATUSES = frozenset({"working", "covering", "swapped", "training", "court"})


def _approved_day_off_request_type(officer_id: int, target_date: date) -> Optional[str]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT request_type FROM day_off_requests
        WHERE officer_id = ? AND request_date = ? AND status = 'Approved'
        ORDER BY processed_at DESC, id DESC
        LIMIT 1
    """,
        (officer_id, target_date.isoformat()),
    )
    row = cursor.fetchone()
    conn.close()
    return row["request_type"] if row else None


def _timecard_defaults_for_schedule_status(
    officer: Dict,
    status: str,
    shift_start: str,
    shift_end: str,
    target_date: date,
) -> Dict:
    shift_hours = _shift_hours(shift_start, shift_end)
    if status in _TIMECARD_WORKING_STATUSES:
        entry_type = "Training" if status == "training" else TIMECARD_REGULAR_TYPE
        return {
            "scheduled": True,
            "time_in": shift_start,
            "time_out": shift_end,
            "hours_worked": shift_hours,
            "entry_type": entry_type,
            "notes": "",
        }

    if status in ("leave", "bumped"):
        req_type = _approved_day_off_request_type(officer["id"], target_date)
        if req_type and req_type in DAY_OFF_TIMECARD_DEFAULTS:
            pay_type, fixed_hours = DAY_OFF_TIMECARD_DEFAULTS[req_type]
            hours = fixed_hours if fixed_hours is not None else shift_hours
            return {
                "scheduled": False,
                "time_in": "",
                "time_out": "",
                "hours_worked": hours,
                "entry_type": pay_type,
                "notes": f"From live schedule — {req_type}",
            }

    return {
        "scheduled": False,
        "time_in": "",
        "time_out": "",
        "hours_worked": 0.0,
        "entry_type": TIMECARD_REGULAR_TYPE,
        "notes": "",
    }


def get_officer_live_schedule_day(officer_id: int, target_date: date) -> Dict:
    """Resolve one officer-day from live (updated) snapshot, then rotation + overrides."""
    officer = get_officer_by_id(officer_id)
    if not officer:
        return {
            "scheduled": False,
            "status": "off",
            "time_in": "",
            "time_out": "",
            "hours_worked": 0.0,
            "entry_type": TIMECARD_REGULAR_TYPE,
            "notes": "",
            "source": "none",
        }

    snapshot = get_schedule_snapshot(target_date.year, target_date.month, "updated")
    source = "live"
    if not snapshot:
        snapshot = get_schedule_snapshot(target_date.year, target_date.month, "base")
        source = "base" if snapshot else "rotation"

    row = None
    if snapshot:
        for snap_row in snapshot.get("rows", []):
            if snap_row["officer_id"] == officer_id and snap_row["assignment_date"] == target_date.isoformat():
                row = snap_row
                break

    if row:
        status = row["status"]
        shift_start = row.get("assigned_shift_start") or row.get("shift_start") or officer.get("shift_start") or ""
        shift_end = row.get("assigned_shift_end") or row.get("shift_end") or officer.get("shift_end") or ""
    else:
        status = get_officer_day_status(officer_id, target_date)
        shift_start = officer.get("shift_start") or ""
        shift_end = officer.get("shift_end") or ""
        if status == "covering":
            from logic.shift_assignment import covered_shift_for_officer_on_date

            covered = covered_shift_for_officer_on_date(officer_id, target_date)
            if covered:
                shift_start = covered

    defaults = _timecard_defaults_for_schedule_status(
        officer,
        status,
        shift_start,
        shift_end,
        target_date,
    )
    defaults["status"] = status
    defaults["source"] = source
    return defaults


def get_timecard_approval(officer_id: int, period_start: Optional[date] = None) -> Dict:
    start, _ = get_pay_period(period_start)
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT ta.*, u.username AS approved_by_username
        FROM timecard_approvals ta
        LEFT JOIN app_users u ON ta.approved_by_user_id = u.id
        WHERE ta.officer_id = ? AND ta.pay_period_start = ?
    """,
        (officer_id, start.isoformat()),
    )
    row = cursor.fetchone()
    conn.close()
    if not row:
        return {
            "officer_id": officer_id,
            "pay_period_start": start.isoformat(),
            "status": "Draft",
        }
    return dict(row)


def list_timecard_approvals_for_period(period_start: Optional[date] = None) -> Dict:
    start, end = get_pay_period(period_start)
    start_str = start.isoformat()
    officers = [o for o in get_officers_by_seniority() if o.get("active") == 1]
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT officer_id, status, submitted_at, approved_at, supervisor_notes
        FROM timecard_approvals
        WHERE pay_period_start = ?
    """,
        (start_str,),
    )
    by_officer = {row["officer_id"]: dict(row) for row in cursor.fetchall()}
    cursor.execute(
        """
        SELECT officer_id, COALESCE(SUM(hours_worked), 0) AS total_hours,
               COUNT(*) AS line_count
        FROM timecard_entries
        WHERE pay_period_start = ?
        GROUP BY officer_id
    """,
        (start_str,),
    )
    hours_by_officer = {row["officer_id"]: dict(row) for row in cursor.fetchall()}
    conn.close()

    rows = []
    for officer in officers:
        approval = by_officer.get(officer["id"], {})
        hours = hours_by_officer.get(officer["id"], {})
        rows.append(
            {
                "officer_id": officer["id"],
                "officer_name": officer["name"],
                "status": approval.get("status", "Draft"),
                "submitted_at": approval.get("submitted_at"),
                "approved_at": approval.get("approved_at"),
                "supervisor_notes": approval.get("supervisor_notes") or "",
                "total_hours": round(hours.get("total_hours") or 0, 2),
                "line_count": hours.get("line_count") or 0,
            }
        )
    return {
        "success": True,
        "period_start": start_str,
        "period_end": end.isoformat(),
        "rows": rows,
    }


def _upsert_timecard_approval(
    officer_id: int,
    period_start: date,
    status: str,
    *,
    user_id: Optional[int] = None,
    supervisor_notes: Optional[str] = None,
    mark_submitted: bool = False,
    mark_approved: bool = False,
) -> Dict:
    if status not in TIMECARD_APPROVAL_STATUSES:
        return {"success": False, "message": f"Invalid approval status: {status}"}

    start_str = period_start.isoformat()
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT id, status FROM timecard_approvals
            WHERE officer_id = ? AND pay_period_start = ?
        """,
            (officer_id, start_str),
        )
        existing = cursor.fetchone()
        if existing:
            cursor.execute(
                """
                UPDATE timecard_approvals
                SET status = ?, supervisor_notes = COALESCE(?, supervisor_notes),
                    submitted_at = CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE submitted_at END,
                    approved_by_user_id = CASE WHEN ? THEN ? ELSE approved_by_user_id END,
                    approved_at = CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE approved_at END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """,
                (
                    status,
                    supervisor_notes,
                    1 if mark_submitted else 0,
                    1 if mark_approved else 0,
                    user_id,
                    1 if mark_approved else 0,
                    existing["id"],
                ),
            )
        else:
            cursor.execute(
                """
                INSERT INTO timecard_approvals
                (officer_id, pay_period_start, status, submitted_at,
                 approved_by_user_id, approved_at, supervisor_notes)
                VALUES (?, ?, ?, CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE NULL END,
                        CASE WHEN ? THEN ? ELSE NULL END,
                        CASE WHEN ? THEN CURRENT_TIMESTAMP ELSE NULL END, ?)
            """,
                (
                    officer_id,
                    start_str,
                    status,
                    1 if mark_submitted else 0,
                    1 if mark_approved else 0,
                    user_id,
                    1 if mark_approved else 0,
                    supervisor_notes,
                ),
            )
        conn.commit()
        return {"success": True, "status": status}
    except Exception as exc:
        conn.rollback()
        return {"success": False, "message": str(exc)}
    finally:
        conn.close()


def submit_timecard_for_approval(
    officer_id: int,
    period_start: Optional[date] = None,
    user_id: Optional[int] = None,
) -> Dict:
    start, _ = get_pay_period(period_start)
    if is_pay_period_locked(start):
        return {"success": False, "message": "Pay period is locked"}
    current = get_timecard_approval(officer_id, start)
    if current.get("status") == "Approved":
        return {"success": False, "message": "Timecard is already approved for this period"}
    return _upsert_timecard_approval(
        officer_id,
        start,
        "Submitted",
        user_id=user_id,
        mark_submitted=True,
    )


def approve_timecard_period(
    officer_id: int,
    period_start: Optional[date] = None,
    user_id: Optional[int] = None,
    supervisor_notes: str = "",
) -> Dict:
    start, _ = get_pay_period(period_start)
    if is_pay_period_locked(start):
        return {"success": False, "message": "Pay period is locked"}
    result = _upsert_timecard_approval(
        officer_id,
        start,
        "Approved",
        user_id=user_id,
        supervisor_notes=supervisor_notes or None,
        mark_approved=True,
    )
    if result.get("success"):
        log_audit_action(
            "timecard.approve",
            "timecard_approval",
            officer_id,
            user_id,
            start.isoformat(),
        )
        result["message"] = "Timecard approved for this pay period"
    return result


def reject_timecard_period(
    officer_id: int,
    period_start: Optional[date] = None,
    user_id: Optional[int] = None,
    supervisor_notes: str = "",
) -> Dict:
    start, _ = get_pay_period(period_start)
    if is_pay_period_locked(start):
        return {"success": False, "message": "Pay period is locked"}
    result = _upsert_timecard_approval(
        officer_id,
        start,
        "Rejected",
        user_id=user_id,
        supervisor_notes=supervisor_notes or None,
    )
    if result.get("success"):
        result["message"] = "Timecard returned to officer for corrections"
    return result


def is_timecard_period_approved(officer_id: int, period_start: Optional[date] = None) -> bool:
    return get_timecard_approval(officer_id, period_start).get("status") == "Approved"


def save_timecard_entry(
    officer_id: int,
    entry_date: str,
    hours_worked: float,
    entry_type: str = TIMECARD_REGULAR_TYPE,
    time_in: str = "",
    time_out: str = "",
    night_diff_hours: float = 0.0,
    notes: str = "",
    period_start: Optional[str] = None,
    timecard_id: Optional[int] = None,
    *,
    override_approval: bool = False,
) -> Dict:
    officer = get_officer_by_id(officer_id)
    if not officer:
        return {"success": False, "message": "Officer not found"}
    if entry_type not in TIMECARD_ENTRY_TYPES:
        return {"success": False, "message": f"Invalid entry type: {entry_type}"}

    try:
        parsed = parse_date(entry_date)
    except ValueError:
        return {"success": False, "message": f"Entry date must be {DATE_INPUT_HINT}"}

    pay_start, pay_end = pay_period_for_shift_start(parsed)
    if is_pay_period_locked(pay_start):
        return {"success": False, "message": "Pay period is locked — timecard edits are disabled"}
    if is_timecard_period_approved(officer_id, pay_start) and not override_approval:
        return {
            "success": False,
            "message": "Timecard approved for this pay period — contact a supervisor to make changes",
        }

    if period_start and storage_date_str(period_start) != pay_start.isoformat():
        return {
            "success": False,
            "message": (
                f"Shift start {format_date(parsed)} belongs to pay period "
                f"{format_date(pay_start)} – {format_date(pay_end)}, not the selected period"
            ),
        }
    pay_start_str = pay_start.isoformat()

    conn = get_connection()
    cursor = conn.cursor()
    try:
        if timecard_id is not None:
            cursor.execute(
                """
                SELECT id, payroll_entry_id FROM timecard_entries
                WHERE id = ? AND officer_id = ?
            """,
                (timecard_id, officer_id),
            )
            existing = cursor.fetchone()
            if not existing:
                return {"success": False, "message": "Timecard entry not found"}
            if existing["payroll_entry_id"]:
                return {"success": False, "message": "Entry already imported to payroll — cannot edit"}
            cursor.execute(
                """
                UPDATE timecard_entries
                SET pay_period_start = ?, entry_date = ?, hours_worked = ?, time_in = ?, time_out = ?,
                    entry_type = ?, night_diff_hours = ?, notes = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """,
                (
                    pay_start_str,
                    entry_date,
                    hours_worked,
                    time_in or None,
                    time_out or None,
                    entry_type,
                    night_diff_hours,
                    notes or None,
                    timecard_id,
                ),
            )
            entry_id = timecard_id
        else:
            cursor.execute(
                """
                INSERT INTO timecard_entries
                (officer_id, pay_period_start, entry_date, hours_worked, time_in, time_out,
                 entry_type, night_diff_hours, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    officer_id,
                    pay_start_str,
                    entry_date,
                    hours_worked,
                    time_in or None,
                    time_out or None,
                    entry_type,
                    night_diff_hours,
                    notes or None,
                ),
            )
            entry_id = cursor.lastrowid
        conn.commit()
        result = {"success": True, "timecard_id": entry_id}
        if is_overnight_shift(time_in, time_out):
            result["overnight"] = True
            result["message"] = (
                f"Overnight shift saved — all hours count in pay period "
                f"{format_date(pay_start)} – {format_date(pay_end)} (shift start date)"
            )
        return result
    except Exception as e:
        conn.rollback()
        return {"success": False, "message": str(e)}
    finally:
        conn.close()


def delete_timecard_entry(
    timecard_id: int,
    officer_id: int,
    *,
    override_approval: bool = False,
) -> Dict:
    """Remove a timecard row (e.g. extra pay-type line on the same day)."""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT id, payroll_entry_id, pay_period_start FROM timecard_entries
            WHERE id = ? AND officer_id = ?
        """,
            (timecard_id, officer_id),
        )
        row = cursor.fetchone()
        if not row:
            return {"success": False, "message": "Timecard entry not found"}
        if row["payroll_entry_id"]:
            return {"success": False, "message": "Entry already imported to payroll — cannot delete"}
        period = parse_date(row["pay_period_start"])
        if is_pay_period_locked(period):
            return {"success": False, "message": "Pay period is locked — timecard edits are disabled"}
        if is_timecard_period_approved(officer_id, period) and not override_approval:
            return {
                "success": False,
                "message": "Timecard approved for this pay period — contact a supervisor to make changes",
            }
        cursor.execute("DELETE FROM timecard_entries WHERE id = ?", (timecard_id,))
        conn.commit()
        return {"success": True, "message": "Timecard entry removed"}
    except Exception as e:
        conn.rollback()
        return {"success": False, "message": str(e)}
    finally:
        conn.close()


def _apply_night_differential(
    result: PayCalculationResult,
    night_differential_hours: float,
    _base_rate: float,
    night_differential_rate: float,
) -> None:
    """Night premium is added after entry-type multipliers on base rate (flat $/hr)."""
    if night_differential_hours <= 0:
        return
    result.night_differential_hours = night_differential_hours
    result.night_differential_pay = round(night_differential_hours * night_differential_rate, 2)
    result.total_pay += result.night_differential_pay


def _ensure_officer_time_banks(cursor, officer_id: int, as_of: date) -> Dict:
    cursor.execute("SELECT * FROM officer_time_banks WHERE officer_id = ?", (officer_id,))
    row = cursor.fetchone()
    if not row:
        cursor.execute(
            """
            INSERT INTO officer_time_banks
            (officer_id, comp_hours, sick_hours, float_holiday_hours, holiday_hours,
             sick_accrual_month, annual_accrual_year)
            VALUES (?, 0, 0, 0, 0, NULL, NULL)
        """,
            (officer_id,),
        )
        cursor.execute("SELECT * FROM officer_time_banks WHERE officer_id = ?", (officer_id,))
        row = cursor.fetchone()

    banks = dict(row)
    month_key = as_of.strftime("%Y-%m")
    year_key = as_of.year

    sick_delta = 0.0
    last_month = banks.get("sick_accrual_month")
    if last_month is None:
        sick_delta = SICK_MONTHLY_ACCRUAL_HOURS
        banks["sick_accrual_month"] = month_key
    elif last_month < month_key:
        sick_delta = SICK_MONTHLY_ACCRUAL_HOURS * _months_between(last_month, month_key)
        banks["sick_accrual_month"] = month_key

    float_delta = 0.0
    holiday_delta = 0.0
    last_year = banks.get("annual_accrual_year")
    if last_year is None:
        float_delta = FLOAT_HOLIDAY_ANNUAL_HOURS
        holiday_delta = HOLIDAY_ANNUAL_HOURS
        banks["annual_accrual_year"] = year_key
    elif last_year < year_key:
        years = year_key - last_year
        float_delta = FLOAT_HOLIDAY_ANNUAL_HOURS * years
        holiday_delta = HOLIDAY_ANNUAL_HOURS * years
        banks["annual_accrual_year"] = year_key

    if sick_delta or float_delta or holiday_delta:
        cursor.execute(
            """
            UPDATE officer_time_banks
            SET sick_hours = sick_hours + ?,
                float_holiday_hours = float_holiday_hours + ?,
                holiday_hours = holiday_hours + ?,
                sick_accrual_month = ?,
                annual_accrual_year = ?
            WHERE officer_id = ?
        """,
            (
                sick_delta,
                float_delta,
                holiday_delta,
                banks["sick_accrual_month"],
                banks["annual_accrual_year"],
                officer_id,
            ),
        )
        cursor.execute("SELECT * FROM officer_time_banks WHERE officer_id = ?", (officer_id,))
        banks = dict(cursor.fetchone())

    return banks


def _months_between(start_ym: str, end_ym: str) -> int:
    start_year, start_month = map(int, start_ym.split("-"))
    end_year, end_month = map(int, end_ym.split("-"))
    return (end_year - start_year) * 12 + (end_month - start_month)


def bulk_adjust_pay_rates(
    percent_change: float = 0.0,
    flat_amount: float = 0.0,
    squad: Optional[str] = None,
) -> Dict:
    if percent_change == 0 and flat_amount == 0:
        return {"success": False, "message": "Provide a percent change or flat amount"}

    conn = get_connection()
    cursor = conn.cursor()
    try:
        if squad in ("A", "B"):
            cursor.execute(
                """
                UPDATE officers
                SET pay_rate = ROUND(pay_rate * ? + ?, 2)
                WHERE active = 1 AND squad = ?
            """,
                (1 + percent_change / 100, flat_amount, squad),
            )
        else:
            cursor.execute(
                """
                UPDATE officers
                SET pay_rate = ROUND(pay_rate * ? + ?, 2)
                WHERE active = 1
            """,
                (1 + percent_change / 100, flat_amount),
            )
        updated = cursor.rowcount
        conn.commit()
        return {"success": True, "updated": updated, "message": f"Updated pay rates for {updated} officer(s)"}
    except Exception as e:
        conn.rollback()
        return {"success": False, "message": str(e)}
    finally:
        conn.close()


def copy_timecard_from_previous_period(
    officer_id: int,
    period_start: Optional[date] = None,
) -> Dict:
    """Copy prior pay period timecard rows into the current period (same cycle offsets)."""
    start, end = get_pay_period(period_start)
    if is_pay_period_locked(start):
        return {"success": False, "message": "Pay period is locked"}

    prev_start, _ = get_adjacent_pay_period(start, -1)
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT * FROM timecard_entries
        WHERE officer_id = ? AND pay_period_start = ?
        ORDER BY entry_date
    """,
        (officer_id, prev_start.isoformat()),
    )
    prev_rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    if not prev_rows:
        return {"success": False, "message": "No timecard data in previous pay period"}

    copied = 0
    skipped = 0
    for row in prev_rows:
        src = parse_date(row["entry_date"])
        target = src + timedelta(days=PAY_PERIOD_LENGTH)
        if target > end or target < start:
            skipped += 1
            continue
        target_str = target.isoformat()
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT payroll_entry_id FROM timecard_entries
            WHERE officer_id = ? AND entry_date = ?
        """,
            (officer_id, target_str),
        )
        existing = cursor.fetchone()
        conn.close()
        if existing and existing["payroll_entry_id"]:
            skipped += 1
            continue
        result = save_timecard_entry(
            officer_id,
            target_str,
            row.get("hours_worked") or 0.0,
            row.get("entry_type") or TIMECARD_REGULAR_TYPE,
            row.get("time_in") or "",
            row.get("time_out") or "",
            row.get("night_diff_hours") or 0.0,
            row.get("notes") or "",
            period_start=start.isoformat(),
        )
        if result.get("success"):
            copied += 1

    return {
        "success": True,
        "copied": copied,
        "skipped": skipped,
        "message": f"Copied {copied} day(s) from previous pay period",
    }


def get_pay_stub_preview(officer_id: int, period_start: Optional[date] = None) -> Dict:
    from analytics import get_pay_stub_preview as _stub

    return _stub(officer_id, period_start)


def _summarize_pay_period_hours(
    timecard_rows: List[Dict],
    payroll_rows: List[Dict],
) -> Dict:
    """Aggregate hours from timecard rows plus payroll-only entries (not imported from timecard)."""
    by_type = {entry_type: 0.0 for entry_type in TIMECARD_ENTRY_TYPES}
    imported_payroll_ids = {row["payroll_entry_id"] for row in timecard_rows if row.get("payroll_entry_id")}
    total_hours = 0.0
    night_diff_hours = 0.0

    for row in timecard_rows:
        entry_type = row.get("entry_type") or TIMECARD_REGULAR_TYPE
        hours = float(row.get("hours_worked") or 0)
        if entry_type not in by_type:
            by_type[entry_type] = 0.0
        by_type[entry_type] += hours
        total_hours += hours
        night_diff_hours += float(row.get("night_diff_hours") or 0)

    for row in payroll_rows:
        if row.get("id") in imported_payroll_ids:
            continue
        entry_type = row.get("entry_type") or TIMECARD_REGULAR_TYPE
        hours = float(row.get("hours") or 0)
        if entry_type not in by_type:
            by_type[entry_type] = 0.0
        by_type[entry_type] += hours
        total_hours += hours
        night_diff_hours += float(row.get("night_differential_hours") or 0)

    return {
        "total_hours": round(total_hours, 2),
        "night_diff_hours": round(night_diff_hours, 2),
        "by_entry_type": {key: round(value, 2) for key, value in by_type.items()},
    }


def get_pay_period_hours_summary(
    period_start: Optional[date] = None,
    officer_id: Optional[int] = None,
) -> Dict:
    """Hour totals for a pay period, broken down by classification and night differential."""
    start, end = get_pay_period(period_start)
    start_str = start.isoformat()
    end_str = end.isoformat()

    conn = get_connection()
    cursor = conn.cursor()
    if officer_id:
        cursor.execute(
            """
            SELECT hours_worked, entry_type, night_diff_hours, payroll_entry_id
            FROM timecard_entries
            WHERE pay_period_start = ? AND officer_id = ?
        """,
            (start_str, officer_id),
        )
    else:
        cursor.execute(
            """
            SELECT hours_worked, entry_type, night_diff_hours, payroll_entry_id
            FROM timecard_entries
            WHERE pay_period_start = ?
        """,
            (start_str,),
        )
    timecard_rows = [dict(row) for row in cursor.fetchall()]

    if officer_id:
        cursor.execute(
            """
            SELECT id, hours, entry_type, night_differential_hours
            FROM payroll_entries
            WHERE officer_id = ? AND pay_period_start = ?
        """,
            (officer_id, start_str),
        )
    else:
        cursor.execute(
            """
            SELECT id, hours, entry_type, night_differential_hours
            FROM payroll_entries
            WHERE pay_period_start = ?
        """,
            (start_str,),
        )
    payroll_rows = [dict(row) for row in cursor.fetchall()]
    conn.close()

    summary = _summarize_pay_period_hours(timecard_rows, payroll_rows)
    result = {
        "success": True,
        "period_start": start_str,
        "period_end": end_str,
        **summary,
    }
    if officer_id is not None:
        from logic.labor_compliance import get_flsa_payroll_summary

        result["flsa"] = get_flsa_payroll_summary(officer_id)
    else:
        from logic.labor_compliance import flsa_threshold_for_period_days, get_flsa_work_period_days

        period_days = get_flsa_work_period_days()
        result["flsa"] = {
            "success": True,
            "enabled": True,
            "period_days": period_days,
            "hours_threshold": flsa_threshold_for_period_days(period_days),
            "department_scope": True,
        }
    return result


def get_payroll_period_timesheets(period_start: Optional[date] = None) -> Dict:
    start, end = get_pay_period(period_start)
    start_str = start.isoformat()
    end_str = end.isoformat()
    officers = [o for o in get_officers_by_seniority() if o.get("active") == 1]
    sheets = []
    grand_hours = 0.0
    grand_pay = 0.0

    conn = get_connection()
    cursor = conn.cursor()
    for officer in officers:
        cursor.execute(
            """
            SELECT * FROM timecard_entries
            WHERE officer_id = ? AND pay_period_start = ?
            ORDER BY entry_date
        """,
            (officer["id"], start_str),
        )
        timecard_rows = [dict(r) for r in cursor.fetchall()]
        cursor.execute(
            """
            SELECT * FROM payroll_entries
            WHERE officer_id = ? AND pay_period_start = ?
            ORDER BY entry_date
        """,
            (officer["id"], start_str),
        )
        payroll_rows = [dict(r) for r in cursor.fetchall()]
        total_hours = sum(r.get("hours_worked") or 0 for r in timecard_rows)
        total_pay = sum(r.get("calculated_pay") or 0 for r in payroll_rows)
        grand_hours += total_hours
        grand_pay += total_pay
        sheets.append(
            {
                "officer": officer,
                "total_hours": round(total_hours, 2),
                "total_pay": round(total_pay, 2),
                "timecard_rows": timecard_rows,
                "payroll_rows": payroll_rows,
            }
        )
    conn.close()

    return {
        "success": True,
        "period_start": start_str,
        "period_end": end_str,
        "sheets": sheets,
        "grand_total_hours": round(grand_hours, 2),
        "grand_total_pay": round(grand_pay, 2),
    }


def get_timecard_period(
    officer_id: int,
    period_start: Optional[date] = None,
) -> Dict:
    officer = get_officer_by_id(officer_id)
    if not officer:
        return {"success": False, "message": "Officer not found"}

    start, end = get_pay_period(period_start)
    start_str = start.isoformat()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT * FROM timecard_entries
        WHERE officer_id = ? AND pay_period_start = ?
        ORDER BY entry_date, id
    """,
        (officer_id, start_str),
    )
    saved_by_date: Dict[str, List[Dict]] = {}
    for row in cursor.fetchall():
        saved_by_date.setdefault(row["entry_date"], []).append(dict(row))
    conn.close()

    def _entry_payload(row: Dict, scheduled: bool, default_hours: float) -> Dict:
        if "time_in" in row:
            time_in = row.get("time_in") or ""
        else:
            time_in = officer["shift_start"] if scheduled else ""
        if "time_out" in row:
            time_out = row.get("time_out") or ""
        else:
            time_out = officer["shift_end"] if scheduled else ""
        if "hours_worked" in row:
            hours = row.get("hours_worked", 0.0)
        else:
            hours = default_hours if scheduled else 0.0
        return {
            "timecard_id": row.get("id"),
            "hours_worked": hours,
            "time_in": time_in,
            "time_out": time_out,
            "overnight": is_overnight_shift(time_in, time_out),
            "entry_type": row.get("entry_type") or TIMECARD_REGULAR_TYPE,
            "night_diff_hours": row.get("night_diff_hours") or 0.0,
            "notes": row.get("notes") or "",
            "imported": bool(row.get("payroll_entry_id")),
        }

    approval = get_timecard_approval(officer_id, start)
    days = []
    current = start
    while current <= end:
        key = current.isoformat()
        live = get_officer_live_schedule_day(officer_id, current)
        scheduled = live["scheduled"]
        default_hours = live["hours_worked"]
        default_time_in = live["time_in"]
        default_time_out = live["time_out"]
        default_type = live["entry_type"]
        default_notes = live.get("notes") or ""
        saved_rows = saved_by_date.get(key, [])
        if saved_rows:
            entries = [_entry_payload(row, scheduled, default_hours) for row in saved_rows]
        else:
            entries = [
                _entry_payload(
                    {
                        "time_in": default_time_in,
                        "time_out": default_time_out,
                        "hours_worked": default_hours,
                        "entry_type": default_type,
                        "notes": default_notes,
                    },
                    scheduled,
                    default_hours,
                )
            ]
        primary = entries[0]
        days.append(
            {
                "entry_date": key,
                "day_label": f"{current.strftime('%a')} {format_date(current)}",
                "scheduled": scheduled,
                "schedule_status": live.get("status"),
                "schedule_source": live.get("source"),
                "entries": entries,
                "hours_worked": primary["hours_worked"],
                "time_in": primary["time_in"],
                "time_out": primary["time_out"],
                "overnight": primary["overnight"],
                "entry_type": primary["entry_type"],
                "night_diff_hours": primary["night_diff_hours"],
                "notes": primary["notes"],
                "imported": primary["imported"],
                "timecard_id": primary.get("timecard_id"),
            }
        )
        current += timedelta(days=1)

    return {
        "success": True,
        "officer": officer,
        "period_start": start_str,
        "period_end": end.isoformat(),
        "approval_status": approval.get("status", "Draft"),
        "approval": approval,
        "days": days,
    }


def import_timecard_to_payroll(
    officer_id: int,
    period_start: Optional[str] = None,
) -> Dict:
    start, _ = get_pay_period(parse_date(period_start) if period_start else None)
    if is_pay_period_locked(start):
        return {"success": False, "message": "Pay period is locked — import disabled"}
    start_str = start.isoformat()
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT * FROM timecard_entries
        WHERE officer_id = ? AND pay_period_start = ?
          AND payroll_entry_id IS NULL
          AND entry_type != ?
          AND hours_worked > 0
    """,
        (officer_id, start_str, TIMECARD_REGULAR_TYPE),
    )
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    if not rows:
        return {"success": False, "message": "No payable timecard rows to import"}

    imported = 0
    errors = []
    for row in rows:
        if row["entry_type"] not in PAYROLL_ENTRY_TYPES:
            continue
        result = create_payroll_entry(
            officer_id,
            row["entry_date"],
            row["entry_type"],
            row["hours_worked"],
            night_differential_hours=row.get("night_diff_hours") or 0.0,
            notes=row.get("notes") or "Imported from timecard",
        )
        if not result.get("success"):
            errors.append(f"{row['entry_date']}: {result.get('message')}")
            continue
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE timecard_entries
            SET payroll_entry_id = ?, imported_at = CURRENT_TIMESTAMP
            WHERE id = ?
        """,
            (result["entry_id"], row["id"]),
        )
        conn.commit()
        conn.close()
        imported += 1

    if imported == 0:
        return {"success": False, "message": errors[0] if errors else "Import failed"}
    return {
        "success": True,
        "imported": imported,
        "message": f"Imported {imported} row(s) to payroll",
        "errors": errors,
    }


def prefill_timecard_from_schedule(
    officer_id: int,
    period_start: Optional[date] = None,
    *,
    include_leave_days: bool = True,
    override_approval: bool = False,
) -> Dict:
    """Save timecard rows from the live schedule for days not yet saved or imported."""
    start, _ = get_pay_period(period_start)
    if is_pay_period_locked(start):
        return {"success": False, "message": "Pay period is locked"}
    if is_timecard_period_approved(officer_id, start) and not override_approval:
        return {"success": False, "message": "Timecard is approved — unlock by rejecting before re-prefill"}

    data = get_timecard_period(officer_id, start)
    if not data.get("success"):
        return data

    saved = 0
    skipped = 0
    for day in data["days"]:
        if any(e.get("imported") for e in day.get("entries", [])):
            skipped += 1
            continue
        if any(e.get("timecard_id") for e in day.get("entries", [])):
            continue
        if not day.get("scheduled") and not include_leave_days:
            continue
        live = get_officer_live_schedule_day(officer_id, parse_date(day["entry_date"]))
        if not live.get("scheduled") and not include_leave_days:
            continue
        if not live.get("scheduled") and live.get("status") not in ("leave", "bumped"):
            continue
        primary = day["entries"][0]
        result = save_timecard_entry(
            officer_id,
            day["entry_date"],
            primary["hours_worked"],
            primary.get("entry_type") or TIMECARD_REGULAR_TYPE,
            primary.get("time_in") or "",
            primary.get("time_out") or "",
            primary.get("night_diff_hours") or 0.0,
            primary.get("notes") or "",
            period_start=start.isoformat(),
            override_approval=override_approval,
        )
        if result.get("success"):
            saved += 1

    return {
        "success": True,
        "saved": saved,
        "skipped_imported": skipped,
        "message": f"Prefilled {saved} day(s) from live schedule",
    }


def auto_prefill_timecard_from_live_schedule(
    officer_id: int,
    period_start: Optional[date] = None,
) -> Dict:
    """Silently prefill empty timecard days from the live schedule for the current period."""
    return prefill_timecard_from_schedule(
        officer_id,
        period_start,
        include_leave_days=False,
    )


def project_officer_annual_pay(officer_id: int) -> Dict:
    from config import DEFAULT_ANNUAL_HOURS
    from logic.operations import get_position_pay_rates
    from validators import normalize_officer_job_title, position_amount_to_monthly

    officer = get_officer_by_id(officer_id)
    if not officer:
        return {"success": False, "message": "Officer not found"}

    title = normalize_officer_job_title(officer.get("job_title"))
    title_cfg = (get_position_pay_rates().get("rates") or {}).get(title or "")
    if title_cfg:
        monthly_pay = float(title_cfg.get("monthly_equivalent") or 0.0)
        if monthly_pay <= 0:
            monthly_pay = position_amount_to_monthly(
                float(title_cfg.get("amount") or 0.0),
                title_cfg.get("pay_basis") or "monthly",
            )
    else:
        monthly_pay = round(float(officer["pay_rate"]) * DEFAULT_ANNUAL_HOURS / 12, 2)

    annual_salary = round(monthly_pay * 12, 2)
    per_pay_period = monthly_pay_to_per_pay_period(monthly_pay)
    pay_periods = count_pay_periods_in_year()

    shift_hours = _officer_shift_hours(officer)
    work_days = _officer_work_days_per_cycle(officer)
    from logic.rotation_config import get_active_rotation_cycle_length
    from logic.staffing_config import get_active_annual_hours_target

    cycle_length = get_active_rotation_cycle_length()
    scheduled_annual_hours = round(work_days / cycle_length * 365 * shift_hours, 1)
    target = officer.get("annual_hours_target") or get_active_annual_hours_target()
    hourly_rate = float(officer.get("pay_rate") or 0.0)
    ot_multiplier = officer.get("overtime_multiplier") or get_pay_code_rules()["global"].get(
        "default_overtime_multiplier", 1.5
    )
    overtime_hours = max(0.0, scheduled_annual_hours - target)
    overtime_pay = round(overtime_hours * hourly_rate * ot_multiplier, 2)

    return {
        "success": True,
        "officer_id": officer_id,
        "monthly_pay": monthly_pay,
        "annual_salary": annual_salary,
        "per_pay_period_salary": per_pay_period,
        "pay_periods_per_year": pay_periods,
        "hourly_rate": hourly_rate,
        "annual_hours": scheduled_annual_hours,
        "annual_hours_target": target,
        "shift_hours": shift_hours,
        "work_days_per_cycle": work_days,
        "base_annual_pay": annual_salary,
        "overtime_hours": round(overtime_hours, 1),
        "overtime_pay": overtime_pay,
        "total_annual_pay": round(annual_salary + overtime_pay, 2),
        "hours_vs_target": round(scheduled_annual_hours - target, 1),
    }
