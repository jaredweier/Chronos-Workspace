"""Payroll ledger entries and annual pay projection."""

"""Payroll entries, timecard, and pay-period management."""

from datetime import date
from typing import Dict, List, Optional

from config import (
    DATE_INPUT_HINT,
    PAYROLL_ENTRY_TYPES,
    TIMECARD_REGULAR_TYPE,
)
from database import connection
from logic.officers import get_officer_by_id
from logic.payroll.banks import _ensure_officer_time_banks
from logic.payroll.pay_codes import calculate_pay_for_entry, get_pay_code_rules
from logic.payroll.period import (
    count_pay_periods_in_year,
    get_pay_period,
    is_pay_period_locked,
    monthly_pay_to_per_pay_period,
    pay_period_for_shift_start,
)
from logic.scheduling_matrix import (
    officer_shift_hours,
    officer_work_days_per_cycle,
)
from validators import (
    parse_date,
)


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

    with connection() as conn:
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


def get_payroll_entries(
    officer_id: Optional[int] = None,
    limit: int = 100,
    period_start: Optional[date] = None,
) -> List[Dict]:
    with connection() as conn:
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
        return rows


def get_pay_stub_preview(officer_id: int, period_start: Optional[date] = None) -> Dict:
    from logic.analytics import get_pay_stub_preview as _stub

    return _stub(officer_id, period_start)


def import_timecard_to_payroll(
    officer_id: int,
    period_start: Optional[str] = None,
) -> Dict:
    start, _ = get_pay_period(parse_date(period_start) if period_start else None)
    if is_pay_period_locked(start):
        return {"success": False, "message": "Pay period is locked — import disabled"}
    start_str = start.isoformat()
    with connection() as conn:
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
        with connection() as conn:
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
        imported += 1

    if imported == 0:
        return {"success": False, "message": errors[0] if errors else "Import failed"}
    return {
        "success": True,
        "imported": imported,
        "message": f"Imported {imported} row(s) to payroll",
        "errors": errors,
    }


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

    shift_hours = officer_shift_hours(officer)
    work_days = officer_work_days_per_cycle(officer)
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
