"""
Leave donation — NEOGOV public-sector pattern.

Donor debits bank balance; recipient credits same bank type. Audit + notify.
"""

from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional

from database import connection
from logic.banked_time import BANK_TYPES
from logic.officers import get_officer_by_id
from logic.operations import get_officer_time_banks
from logic.requests import create_notification
from logic.users import log_audit_action

# Public map — do not import banked_time private _BANK_META
_BANK_COLUMNS = {
    "comp": ("comp_hours", "Comp Time"),
    "sick": ("sick_hours", "Sick Leave"),
    "float_holiday": ("float_holiday_hours", "Float Holiday"),
    "holiday": ("holiday_hours", "Holiday"),
}


def donate_leave_hours(
    donor_officer_id: int,
    recipient_officer_id: int,
    bank_type: str,
    hours: float,
    *,
    notes: str = "",
    user_id: Optional[int] = None,
) -> Dict:
    """Transfer bank hours from donor to recipient (comp/sick/holiday/float)."""
    try:
        donor_officer_id = int(donor_officer_id)
        recipient_officer_id = int(recipient_officer_id)
    except (TypeError, ValueError):
        return {"success": False, "message": "Invalid officer id"}
    if donor_officer_id == recipient_officer_id:
        return {"success": False, "message": "Donor and recipient must differ"}
    if bank_type not in BANK_TYPES or bank_type not in _BANK_COLUMNS:
        return {"success": False, "message": f"Unknown bank type: {bank_type}"}
    try:
        hours = float(hours)
    except (TypeError, ValueError):
        return {"success": False, "message": "Hours must be numeric"}
    if hours <= 0:
        return {"success": False, "message": "Hours must be greater than zero"}
    if hours > 200:
        return {"success": False, "message": "Single donation limited to 200 hours"}

    donor = get_officer_by_id(donor_officer_id)
    recipient = get_officer_by_id(recipient_officer_id)
    if not donor or not recipient:
        return {"success": False, "message": "Officer not found"}

    bal_key, label = _BANK_COLUMNS[bank_type]
    donor_banks = get_officer_time_banks(donor_officer_id)
    if not donor_banks.get("success"):
        return {"success": False, "message": donor_banks.get("message") or "Donor banks unavailable"}
    available = float(donor_banks.get(bal_key) or 0)
    if available + 1e-9 < hours:
        return {
            "success": False,
            "message": f"Insufficient {label} balance ({available:.1f}h available)",
        }

    with connection() as conn:
        cursor = conn.cursor()
        try:
            from logic.payroll import _ensure_officer_time_banks

            _ensure_officer_time_banks(cursor, donor_officer_id, date.today())
            _ensure_officer_time_banks(cursor, recipient_officer_id, date.today())

            # bal_key is whitelist-only from _BANK_COLUMNS
            cursor.execute(
                f"""
                UPDATE officer_time_banks
                SET {bal_key} = {bal_key} - ?
                WHERE officer_id = ? AND {bal_key} >= ?
                """,
                (hours, donor_officer_id, hours),
            )
            if cursor.rowcount != 1:
                conn.rollback()
                return {"success": False, "message": "Donation failed — concurrent balance change?"}

            cursor.execute(
                f"""
                UPDATE officer_time_banks
                SET {bal_key} = {bal_key} + ?
                WHERE officer_id = ?
                """,
                (hours, recipient_officer_id),
            )
            if cursor.rowcount != 1:
                conn.rollback()
                return {"success": False, "message": "Donation failed — recipient bank row missing"}

            cursor.execute(
                """
                INSERT INTO leave_donations
                (donor_officer_id, recipient_officer_id, bank_type, hours, notes, status, created_by_user_id)
                VALUES (?, ?, ?, ?, ?, 'completed', ?)
                """,
                (
                    donor_officer_id,
                    recipient_officer_id,
                    bank_type,
                    hours,
                    notes or None,
                    user_id,
                ),
            )
            donation_id = cursor.lastrowid
            conn.commit()
        except Exception as exc:
            conn.rollback()
            return {"success": False, "message": str(exc)}

    log_audit_action(
        "leave.donation",
        "leave_donation",
        donation_id,
        user_id,
        f"{donor['name']} → {recipient['name']} {hours}h {bank_type}",
    )
    # Notify after commit so transfer is not rolled back if notify fails
    try:
        create_notification(
            recipient_officer_id,
            "leave_donation",
            "Leave donation received",
            f"{donor['name']} donated {hours:.1f}h {label} to your bank.",
            related_id=donation_id,
            related_type="leave_donation",
        )
        create_notification(
            donor_officer_id,
            "leave_donation",
            "Leave donation sent",
            f"You donated {hours:.1f}h {label} to {recipient['name']}.",
            related_id=donation_id,
            related_type="leave_donation",
        )
    except Exception:
        pass
    return {
        "success": True,
        "donation_id": donation_id,
        "message": f"Donated {hours:.1f}h {label} to {recipient['name']}",
        "hours": hours,
        "bank_type": bank_type,
    }


def list_leave_donations(limit: int = 50, officer_id: Optional[int] = None) -> Dict:
    with connection() as conn:
        cursor = conn.cursor()
        q = """
            SELECT d.*,
                   don.name AS donor_name,
                   rec.name AS recipient_name
            FROM leave_donations d
            JOIN officers don ON d.donor_officer_id = don.id
            JOIN officers rec ON d.recipient_officer_id = rec.id
        """
        params: List = []
        if officer_id:
            q += " WHERE d.donor_officer_id = ? OR d.recipient_officer_id = ?"
            params.extend([officer_id, officer_id])
        q += " ORDER BY d.id DESC LIMIT ?"
        params.append(limit)
        cursor.execute(q, params)
        rows = [dict(r) for r in cursor.fetchall()]
    return {"success": True, "count": len(rows), "donations": rows}
