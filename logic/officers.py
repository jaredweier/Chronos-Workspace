"""Officer roster CRUD, lookup, photos, and pay-period hour totals."""

import csv
import os
from datetime import date
from typing import Dict, List, Optional

from database import get_connection
from validators import (
    normalize_optional_text,
    parse_date,
    storage_date_str,
    validate_officer_profile,
)


def get_officers_by_seniority() -> List[Dict]:
    """Roster list sorted by seniority rank (ascending) for UI display and vacation grant ordering."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, name, seniority_rank, squad, shift_start, shift_end,
               pay_rate, night_differential_rate, photo_path, active, job_title
        FROM officers
        ORDER BY seniority_rank ASC, name ASC
    """)
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_officer_by_id(officer_id: int) -> Optional[Dict]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM officers WHERE id = ?", (officer_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def get_supervisors() -> List[Dict]:
    """Officers linked to active Supervisor or Administration app users."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT o.* FROM officers o
        JOIN app_users u ON u.officer_id = o.id
        WHERE o.active = 1 AND u.active = 1
          AND u.role IN ('Supervisor', 'Administration')
        ORDER BY o.name ASC
    """)
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_suggested_seniority_rank() -> int:
    """Suggested next seniority rank when adding an officer (UI convenience only)."""
    officers = get_officers_by_seniority()
    if not officers:
        return 1
    return max(o["seniority_rank"] for o in officers) + 1


def get_request_reviewer_officer_ids() -> List[int]:
    """Officer IDs for active Supervisor/Administration app users (notification targets)."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT DISTINCT officer_id FROM app_users
        WHERE active = 1
          AND role IN ('Supervisor', 'Administration')
          AND officer_id IS NOT NULL
    """)
    ids = [row[0] for row in cursor.fetchall() if row[0]]
    conn.close()
    if ids:
        return ids
    return [officer["id"] for officer in get_supervisors()]


def describe_day_off_request(officer_id: int, request_date: str) -> Dict:
    from logic.operations import is_officer_unavailable_on_date
    from logic.scheduling import is_officer_working_on_day, resolve_officer_shift_band, suggest_bump_chain

    """Advisory context for UI and supervisor notifications (does not block submit)."""
    officer = get_officer_by_id(officer_id)
    if not officer:
        return {"success": False, "message": "Officer not found"}

    parsed = parse_date(request_date)
    on_rotation = is_officer_working_on_day(officer_id, parsed)
    unavailable = is_officer_unavailable_on_date(officer_id, parsed)
    covered_start, _covered_end = resolve_officer_shift_band(
        officer_id,
        parsed,
        home_shift_start=officer.get("shift_start"),
        home_shift_end=officer.get("shift_end"),
    )
    suggestion = suggest_bump_chain(
        officer_id,
        request_date,
        officer["squad"],
        covered_start,
    )
    flags: List[str] = []
    if not on_rotation:
        flags.append("off-rotation day")
    if unavailable:
        flags.append("blackout date on file")
    if suggestion.success:
        flags.append("auto-approve eligible")
    elif suggestion.failure_reason == "minimum_rest":
        flags.append("minimum rest — supervisor override required")
    elif suggestion.failure_reason == "consecutive_days":
        flags.append("consecutive day limit — supervisor override required")
    else:
        flags.append("supervisor review likely")

    return {
        "success": True,
        "on_rotation": on_rotation,
        "unavailable": unavailable,
        "auto_approvable": suggestion.success,
        "coverage_message": suggestion.message,
        "summary": "; ".join(flags),
        "suggestion": suggestion,
    }


def add_officer(
    name: str,
    seniority_rank: int,
    squad: Optional[str],
    shift_start: Optional[str],
    shift_end: Optional[str],
    pay_rate: float = 30.0,
    night_differential_rate: float = 1.0,
    start_date: Optional[str] = None,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    address: Optional[str] = None,
    job_title: Optional[str] = None,
    annual_hours_target: Optional[float] = None,
    overtime_multiplier: float = 1.5,
) -> Dict:
    start_date = normalize_optional_text(start_date)
    email = normalize_optional_text(email)
    phone = normalize_optional_text(phone)
    address = normalize_optional_text(address)
    from logic.staffing_config import get_active_annual_hours_target
    from validators import (
        normalize_officer_job_title,
        normalize_officer_shift,
        normalize_officer_squad,
    )

    job_title = normalize_officer_job_title(job_title)
    squad = normalize_officer_squad(squad)
    shift_start, shift_end = normalize_officer_shift(shift_start, shift_end)
    if annual_hours_target is None:
        annual_hours_target = get_active_annual_hours_target()
    validation = validate_officer_profile(
        name.strip(),
        seniority_rank,
        squad,
        shift_start,
        shift_end,
        pay_rate,
        start_date=start_date,
        email=email,
        phone=phone,
        address=address,
        job_title=job_title,
        annual_hours_target=annual_hours_target,
        overtime_multiplier=overtime_multiplier,
    )
    if not validation.ok:
        return {"success": False, "message": validation.message}

    if start_date:
        start_date = storage_date_str(start_date)

    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO officers
            (name, seniority_rank, squad, shift_start, shift_end, pay_rate,
             night_differential_rate, start_date, email, phone, address,
             job_title, annual_hours_target, overtime_multiplier)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                name.strip(),
                seniority_rank,
                squad,
                shift_start,
                shift_end,
                pay_rate,
                night_differential_rate,
                start_date,
                email,
                phone,
                address,
                job_title,
                annual_hours_target,
                overtime_multiplier,
            ),
        )
        conn.commit()
        return {"success": True, "officer_id": cursor.lastrowid}
    except Exception as e:
        conn.rollback()
        return {"success": False, "message": str(e)}
    finally:
        conn.close()


def update_officer(officer_id: int, **fields) -> Dict:
    allowed = {
        "name",
        "seniority_rank",
        "squad",
        "shift_start",
        "shift_end",
        "pay_rate",
        "night_differential_rate",
        "active",
        "photo_path",
        "start_date",
        "email",
        "phone",
        "address",
        "job_title",
        "annual_hours_target",
        "overtime_multiplier",
    }
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return {"success": False, "message": "No valid fields to update"}

    for text_field in ("name", "start_date", "email", "phone", "address"):
        if text_field in updates:
            updates[text_field] = normalize_optional_text(updates[text_field])

    from validators import (
        normalize_officer_job_title,
        normalize_officer_shift,
        normalize_officer_squad,
    )

    if "job_title" in updates:
        updates["job_title"] = normalize_officer_job_title(updates["job_title"])

    if "squad" in updates:
        updates["squad"] = normalize_officer_squad(updates["squad"])
    if "shift_start" in updates or "shift_end" in updates:
        start = updates.get("shift_start")
        end = updates.get("shift_end")
        if start is None or end is None:
            officer_tmp = get_officer_by_id(officer_id)
            if officer_tmp:
                start = start if start is not None else officer_tmp.get("shift_start")
                end = end if end is not None else officer_tmp.get("shift_end")
        updates["shift_start"], updates["shift_end"] = normalize_officer_shift(start, end)

    officer = get_officer_by_id(officer_id)
    if not officer:
        return {"success": False, "message": "Officer not found"}

    profile_fields = {
        "name",
        "seniority_rank",
        "squad",
        "shift_start",
        "shift_end",
        "pay_rate",
        "start_date",
        "email",
        "phone",
        "address",
        "job_title",
        "annual_hours_target",
        "overtime_multiplier",
    }
    if profile_fields.intersection(updates):
        validation = validate_officer_profile(
            updates.get("name", officer["name"]),
            updates.get("seniority_rank", officer["seniority_rank"]),
            updates.get("squad", officer["squad"]),
            updates.get("shift_start", officer["shift_start"]),
            updates.get("shift_end", officer["shift_end"]),
            updates.get("pay_rate", officer["pay_rate"]),
            start_date=updates.get("start_date", officer.get("start_date")),
            email=updates.get("email", officer.get("email")),
            phone=updates.get("phone", officer.get("phone")),
            address=updates.get("address", officer.get("address")),
            job_title=updates.get("job_title", officer.get("job_title")),
            annual_hours_target=updates.get("annual_hours_target", officer.get("annual_hours_target") or 2080.0),
            overtime_multiplier=updates.get("overtime_multiplier", officer.get("overtime_multiplier") or 1.5),
        )
        if not validation.ok:
            return {"success": False, "message": validation.message}

    if updates.get("start_date"):
        updates["start_date"] = storage_date_str(updates["start_date"])

    columns = ", ".join(f"{key} = ?" for key in updates)
    values = list(updates.values()) + [officer_id]

    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(f"UPDATE officers SET {columns} WHERE id = ?", values)
        conn.commit()
        if cursor.rowcount == 0:
            return {"success": False, "message": "Officer not found"}
        return {"success": True}
    except Exception as e:
        conn.rollback()
        return {"success": False, "message": str(e)}
    finally:
        conn.close()


def delete_officer(officer_id: int) -> Dict:
    from logic.scheduling import _officer_history_reason

    officer = get_officer_by_id(officer_id)
    if not officer:
        return {"success": False, "message": "Officer not found"}

    conn = get_connection()
    cursor = conn.cursor()
    try:
        history = _officer_history_reason(cursor, officer_id)
        if history:
            return {
                "success": False,
                "message": (
                    f"Cannot delete officer with existing {history}. Deactivate instead to keep scheduling history."
                ),
            }

        remove_officer_photo(officer_id)
        cursor.execute("DELETE FROM officer_time_banks WHERE officer_id = ?", (officer_id,))
        cursor.execute("DELETE FROM officers WHERE id = ?", (officer_id,))
        deleted = cursor.rowcount
        conn.commit()
        if deleted == 0:
            return {"success": False, "message": "Officer not found"}
        return {"success": True, "message": f"Officer '{officer['name']}' deleted"}
    except Exception as e:
        conn.rollback()
        return {"success": False, "message": str(e)}
    finally:
        conn.close()


def import_roster_from_csv(file_path: str, update_existing: bool = True) -> Dict:
    """Import officers from a roster CSV (same columns as export_roster_csv)."""

    if not os.path.isfile(file_path):
        return {"success": False, "message": f"File not found: {file_path}"}

    added = updated = skipped = errors = 0
    error_details: List[str] = []

    with open(file_path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames:
            return {"success": False, "message": "CSV is empty or missing header row"}

        for row_num, row in enumerate(reader, start=2):
            name = (row.get("name") or "").strip()
            if not name:
                skipped += 1
                continue

            try:
                seniority = int(row["seniority_rank"])
                squad = row["squad"].strip().upper()
                shift_start = row["shift_start"].strip()
                shift_end = row["shift_end"].strip()
                pay_rate = float(row.get("pay_rate") or 30.0)
                night_diff = float(row.get("night_differential_rate") or 1.0)
            except (KeyError, ValueError, AttributeError) as exc:
                errors += 1
                error_details.append(f"Row {row_num}: invalid data ({exc})")
                continue

            from validators import normalize_officer_job_title

            profile_kwargs = {
                "night_differential_rate": night_diff,
                "job_title": normalize_officer_job_title((row.get("job_title") or "").strip() or None),
                "email": (row.get("email") or "").strip() or None,
                "phone": (row.get("phone") or "").strip() or None,
                "start_date": (row.get("start_date") or "").strip() or None,
            }

            active_val = row.get("active")
            active = None
            if active_val is not None and str(active_val).strip() != "":
                active = 1 if str(active_val).strip().lower() in ("1", "true", "yes") else 0

            officer_id_str = (row.get("id") or "").strip()
            officer_id = int(officer_id_str) if officer_id_str.isdigit() else None
            existing = get_officer_by_id(officer_id) if officer_id else None

            if existing and update_existing:
                update_fields = {
                    "name": name,
                    "seniority_rank": seniority,
                    "squad": squad,
                    "shift_start": shift_start,
                    "shift_end": shift_end,
                    "pay_rate": pay_rate,
                    **profile_kwargs,
                }
                if active is not None:
                    update_fields["active"] = active
                result = update_officer(officer_id, **update_fields)
                if result.get("success"):
                    updated += 1
                else:
                    errors += 1
                    error_details.append(f"Row {row_num}: {result.get('message')}")
            elif existing:
                skipped += 1
            else:
                result = add_officer(
                    name,
                    seniority,
                    squad,
                    shift_start,
                    shift_end,
                    pay_rate,
                    **profile_kwargs,
                )
                if result.get("success"):
                    added += 1
                    if active is not None and active == 0:
                        update_officer(result["officer_id"], active=0)
                else:
                    errors += 1
                    error_details.append(f"Row {row_num}: {result.get('message')}")

    message = f"Import complete: {added} added, {updated} updated, {skipped} skipped"
    if errors:
        message += f", {errors} errors"

    return {
        "success": errors == 0 or (added + updated > 0),
        "message": message,
        "added": added,
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
        "error_details": error_details[:10],
    }


def get_pay_period_hours_by_officer(period_start: Optional[date] = None) -> Dict[int, float]:
    from logic.payroll import get_payroll_period_timesheets

    """Map officer_id -> total hours logged in the pay period (for roster/dashboard)."""
    sheets = get_payroll_period_timesheets(period_start)
    return {sheet["officer"]["id"]: round(sheet.get("total_hours") or 0.0, 1) for sheet in sheets.get("sheets", [])}


def remove_officer_photo(officer_id: int) -> Dict:
    from photos import remove_officer_photo as _remove_photo

    officer = get_officer_by_id(officer_id)
    if not officer:
        return {"success": False, "message": "Officer not found"}
    _remove_photo(officer_id, officer.get("photo_path"))
    return update_officer(officer_id, photo_path=None)


def set_officer_photo(officer_id: int, source_path: str) -> Dict:
    from photos import save_officer_photo

    result = save_officer_photo(officer_id, source_path)
    if not result.get("success"):
        return result
    update = update_officer(officer_id, photo_path=result["photo_path"])
    if not update.get("success"):
        return update
    return result
