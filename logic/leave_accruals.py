"""Leave accruals — balances + deduct on approve (vacation/sick/comp)."""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, Optional

from database import connection
from logic.operations import get_department_setting, set_department_setting
from logic.users import log_audit_action
from validators import parse_date, storage_date

SETTING_DEDUCT = "leave_accrual_deduct_on_approve"

# Map request types → bank column
TYPE_TO_BANK = {
    "Vacation": "float_holiday_hours",  # closest annual leave bank if no vacation column
    "Sick": "sick_hours",
    "Comp": "comp_hours",
    "Comp Time": "comp_hours",
    "Holiday": "holiday_hours",
    "Float": "float_holiday_hours",
    "Float Holiday": "float_holiday_hours",
}


def get_accrual_deduct_on_approve() -> bool:
    raw = (get_department_setting(SETTING_DEDUCT, "1") or "1").strip().lower()
    return raw in ("1", "true", "yes", "on")


def set_accrual_deduct_on_approve(enabled: bool, *, user_id: Optional[int] = None) -> Dict:
    r = set_department_setting(SETTING_DEDUCT, "1" if enabled else "0", user_id=user_id)
    if not r.get("success"):
        return r
    return {
        "success": True,
        "enabled": bool(enabled),
        "message": f"Deduct accruals on leave approve: {'ON' if enabled else 'OFF'}",
    }


def _shift_hours_for_officer(officer_id: int, request_date: str) -> float:
    try:
        from logic.staffing_config import get_staffing_settings

        settings = get_staffing_settings() or {}
        length = float(settings.get("shift_length_hours") or 8.0)
        # Prefer officer band length if parseable
        return max(1.0, min(16.0, length))
    except Exception:
        return 8.0


def get_officer_accrual_balances(officer_id: int, *, as_of: Optional[date] = None) -> Dict[str, Any]:
    """Balances with accrual bootstrap (sick monthly / holiday annual)."""
    from logic.payroll.banks import _ensure_officer_time_banks

    ref = as_of or date.today()
    with connection() as conn:
        cursor = conn.cursor()
        banks = _ensure_officer_time_banks(cursor, int(officer_id), ref)
        conn.commit()
        return {
            "success": True,
            "officer_id": int(officer_id),
            "as_of": storage_date(ref),
            "comp_hours": float(banks.get("comp_hours") or 0),
            "sick_hours": float(banks.get("sick_hours") or 0),
            "float_holiday_hours": float(banks.get("float_holiday_hours") or 0),
            "holiday_hours": float(banks.get("holiday_hours") or 0),
            "banks": dict(banks),
        }


def list_roster_accrual_balances(*, as_of: Optional[date] = None) -> Dict[str, Any]:
    from logic.officers import get_officers_by_seniority

    ref = as_of or date.today()
    rows = []
    for off in get_officers_by_seniority() or []:
        if off.get("active") not in (1, True, "1"):
            continue
        b = get_officer_accrual_balances(int(off["id"]), as_of=ref)
        rows.append(
            {
                "officer_id": off["id"],
                "officer_name": off.get("name"),
                "squad": off.get("squad"),
                "comp_hours": b.get("comp_hours"),
                "sick_hours": b.get("sick_hours"),
                "float_holiday_hours": b.get("float_holiday_hours"),
                "holiday_hours": b.get("holiday_hours"),
            }
        )
    return {"success": True, "as_of": storage_date(ref), "count": len(rows), "rows": rows}


def deduct_leave_accrual(
    officer_id: int,
    request_type: str,
    request_date: str,
    *,
    hours: Optional[float] = None,
    request_id: Optional[int] = None,
    user_id: Optional[int] = None,
    allow_negative: bool = False,
) -> Dict[str, Any]:
    """Debit the matching bank for an approved leave day."""
    if not get_accrual_deduct_on_approve():
        return {"success": True, "skipped": True, "message": "Accrual deduct disabled"}

    rtype = (request_type or "").strip()
    bank_col = TYPE_TO_BANK.get(rtype)
    if not bank_col:
        # Sick-like synonyms
        if rtype.lower() in ("sick", "ill", "injury"):
            bank_col = "sick_hours"
        elif rtype.lower() in ("vacation", "annual", "pto"):
            bank_col = "float_holiday_hours"
        else:
            return {
                "success": True,
                "skipped": True,
                "message": f"No accrual bank for type {rtype}",
            }

    hrs = float(hours) if hours is not None else _shift_hours_for_officer(officer_id, request_date)
    if hrs <= 0:
        return {"success": False, "message": "Hours must be positive"}

    try:
        parse_date(request_date)
    except ValueError as exc:
        return {"success": False, "message": str(exc)}

    from logic.payroll.banks import _ensure_officer_time_banks

    with connection() as conn:
        cursor = conn.cursor()
        try:
            banks = _ensure_officer_time_banks(cursor, int(officer_id), parse_date(request_date))
            current = float(banks.get(bank_col) or 0)
            if current < hrs and not allow_negative:
                return {
                    "success": False,
                    "message": f"Insufficient {bank_col.replace('_', ' ')}: have {current:g}h, need {hrs:g}h",
                    "balance": current,
                    "needed": hrs,
                    "bank": bank_col,
                }
            new_bal = current - hrs
            cursor.execute(
                f"UPDATE officer_time_banks SET {bank_col} = ? WHERE officer_id = ?",
                (new_bal, int(officer_id)),
            )
            # Ledger row if bank transactions table exists — optional
            try:
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS leave_accrual_ledger (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        officer_id INTEGER NOT NULL,
                        request_id INTEGER,
                        request_type TEXT,
                        request_date TEXT,
                        bank_column TEXT,
                        hours REAL,
                        balance_after REAL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        created_by_user_id INTEGER
                    )
                    """
                )
                cursor.execute(
                    """
                    INSERT INTO leave_accrual_ledger
                    (officer_id, request_id, request_type, request_date, bank_column, hours, balance_after,
                     created_by_user_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        int(officer_id),
                        request_id,
                        rtype,
                        storage_date(parse_date(request_date)),
                        bank_col,
                        -hrs,
                        new_bal,
                        user_id,
                    ),
                )
            except Exception:
                pass
            conn.commit()
            if user_id is not None:
                log_audit_action(
                    user_id,
                    "leave_accrual_deduct",
                    "officer_time_banks",
                    int(officer_id),
                    f"{rtype} -{hrs:g}h → {bank_col}={new_bal:g}",
                )
            return {
                "success": True,
                "officer_id": int(officer_id),
                "bank": bank_col,
                "hours_deducted": hrs,
                "balance_after": new_bal,
                "message": f"Deducted {hrs:g}h from {bank_col.replace('_', ' ')} (now {new_bal:g}h)",
            }
        except Exception as exc:
            conn.rollback()
            return {"success": False, "message": str(exc)}


def maybe_deduct_on_day_off_approve(
    request: Dict[str, Any],
    *,
    user_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Hook from process_day_off_request after successful approve."""
    return deduct_leave_accrual(
        int(request["officer_id"]),
        str(request.get("request_type") or ""),
        str(request.get("request_date") or ""),
        request_id=int(request["id"]) if request.get("id") is not None else None,
        user_id=user_id,
        allow_negative=True,  # do not block approve if bank short — log negative
    )
