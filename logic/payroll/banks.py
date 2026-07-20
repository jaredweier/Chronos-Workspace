"""Officer time-bank accrual bootstrap and bulk rate tools."""

"""Payroll entries, timecard, and pay-period management."""

from datetime import date
from typing import Dict, Optional

from config import (
    FLOAT_HOLIDAY_ANNUAL_HOURS,
    HOLIDAY_ANNUAL_HOURS,
    SICK_MONTHLY_ACCRUAL_HOURS,
)
from database import connection


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

    with connection() as conn:
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
