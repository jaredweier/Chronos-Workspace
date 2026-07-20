"""Timecard entries, approvals, prefill, period summaries."""

"""Payroll entries, timecard, and pay-period management."""

from datetime import date, timedelta
from typing import Dict, List, Optional

from config import (
    DATE_INPUT_HINT,
    DAY_OFF_TIMECARD_DEFAULTS,
    PAY_PERIOD_LENGTH,
    TIMECARD_APPROVAL_STATUSES,
    TIMECARD_ENTRY_TYPES,
    TIMECARD_REGULAR_TYPE,
)
from database import connection
from logic.officers import get_officer_by_id, get_officers_by_seniority
from logic.payroll.period import (
    get_adjacent_pay_period,
    get_pay_period,
    is_pay_period_locked,
    pay_period_for_shift_start,
)
from logic.scheduling_matrix import (
    get_officer_day_status,
)
from logic.scheduling_matrix import (
    shift_hours as compute_shift_hours,
)
from logic.snapshots import get_schedule_snapshot
from logic.users import log_audit_action
from models import PayCalculationResult
from validators import (
    format_date,
    is_overnight_shift,
    parse_date,
    storage_date_str,
)

_TIMECARD_WORKING_STATUSES = frozenset({"working", "covering", "swapped", "training", "court"})


def _approved_day_off_request_type(officer_id: int, target_date: date) -> Optional[str]:
    with connection() as conn:
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
        return row["request_type"] if row else None


def _timecard_defaults_for_schedule_status(
    officer: Dict,
    status: str,
    shift_start: str,
    shift_end: str,
    target_date: date,
) -> Dict:
    shift_hours = compute_shift_hours(shift_start, shift_end)
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
    with connection() as conn:
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
    with connection() as conn:
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
    with connection() as conn:
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

    # Punch-required policy (default off): block free-form entry unless
    # supervisor override_approval or entry came from punch pipeline notes.
    try:
        from logic.time_punch import assert_manual_timecard_allowed, is_punch_required

        if is_punch_required() and not override_approval:
            notes_l = (notes or "").lower()
            from_punch = "geofence punch" in notes_l or "punch in#" in notes_l or notes_l.startswith("punch")
            gate = assert_manual_timecard_allowed(
                officer_id=int(officer_id),
                actor_is_supervisor=False,
                from_punch_pipeline=from_punch,
            )
            if not gate.get("allowed"):
                return {"success": False, "message": gate.get("message") or "Punch required"}
    except Exception:
        pass

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

    with connection() as conn:
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


def delete_timecard_entry(
    timecard_id: int,
    officer_id: int,
    *,
    override_approval: bool = False,
) -> Dict:
    """Remove a timecard row (e.g. extra pay-type line on the same day)."""
    with connection() as conn:
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


def copy_timecard_from_previous_period(
    officer_id: int,
    period_start: Optional[date] = None,
) -> Dict:
    """Copy prior pay period timecard rows into the current period (same cycle offsets)."""
    start, end = get_pay_period(period_start)
    if is_pay_period_locked(start):
        return {"success": False, "message": "Pay period is locked"}

    prev_start, _ = get_adjacent_pay_period(start, -1)
    with connection() as conn:
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
        with connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT payroll_entry_id FROM timecard_entries
                WHERE officer_id = ? AND entry_date = ?
            """,
                (officer_id, target_str),
            )
            existing = cursor.fetchone()
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

    with connection() as conn:
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

    with connection() as conn:
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
    with connection() as conn:
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
