"""Holidays, availability, open shifts, settings, and backup."""

import json
import sqlite3
from datetime import date, timedelta
from typing import Dict, List, Optional

from config import DATE_INPUT_HINT
from database import backup_database, connection
from logic.officers import get_officer_by_id, get_officers_by_seniority, update_officer
from logic.scheduling import get_officer_day_status
from validators import parse_date, storage_date_str


def _log_audit(*args, **kwargs):
    from logic.users import log_audit_action

    log_audit_action(*args, **kwargs)


# Legacy seed brand → agency-neutral display (existing DBs)
_LEGACY_BRAND = {
    "department_name": {
        "Dodgeville Police Department": "Police Department",
        "Dodgeville PD": "Police Department",
    },
    "department_tagline": {
        "Wisconsin's Oldest Courthouse · Est. 1859": "Workforce command",
        "Est. 1859": "Workforce command",
    },
    "rotation_preset": {
        "2-2-3 (Dodgeville 14-day)": "2-2-3 (14-day)",
    },
}


def get_department_setting(key: str, default: str = "") -> str:
    with connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM department_settings WHERE key = ?", (key,))
        row = cursor.fetchone()
    value = row["value"] if row else default
    remap = _LEGACY_BRAND.get(key) or {}
    if value in remap:
        return remap[value]
    return value


def set_department_setting(key: str, value: str, user_id: Optional[int] = None) -> Dict:
    from validators import validate_setting_key

    validation = validate_setting_key(key)
    if not validation.ok:
        return {"success": False, "message": validation.message}

    with connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO department_settings (key, value, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = CURRENT_TIMESTAMP
            """,
                (key, value),
            )
            conn.commit()
            _log_audit("settings.update", "setting", None, user_id, f"{key}={value}")
            return {"success": True}
        except Exception as e:
            conn.rollback()
            return {"success": False, "message": str(e)}


def get_position_pay_rates() -> Dict:
    """Return compensation config keyed by roster title."""
    from config import DEFAULT_POSITION_PAY_RATES, POSITION_PAY_SETTINGS_KEY
    from logic.payroll import count_pay_periods_in_year, monthly_pay_to_per_pay_period
    from logic.roster_titles import get_officer_title_options
    from validators import (
        default_annual_hours_for_title,
        position_amount_to_hourly,
        position_amount_to_monthly,
    )

    raw = get_department_setting(POSITION_PAY_SETTINGS_KEY, "")
    stored: Dict = {}
    if raw:
        try:
            stored = json.loads(raw)
        except json.JSONDecodeError:
            stored = {}

    rates = {}
    for title in get_officer_title_options():
        entry = dict(
            DEFAULT_POSITION_PAY_RATES.get(
                title,
                {"amount": 0.0, "pay_basis": "hourly", "is_salary": False},
            )
        )
        entry.update(stored.get(title) or {})
        entry["title"] = title
        from validators import default_pay_basis_for_title

        entry["pay_basis"] = entry.get("pay_basis") or default_pay_basis_for_title(title)
        entry["amount"] = float(entry.get("amount") or 0)
        entry["is_salary"] = bool(entry.get("is_salary"))
        try:
            entry["annual_hours"] = float(entry.get("annual_hours") or default_annual_hours_for_title(title))
        except (TypeError, ValueError):
            entry["annual_hours"] = default_annual_hours_for_title(title)
        entry["monthly_equivalent"] = position_amount_to_monthly(
            entry["amount"],
            entry["pay_basis"],
            entry["annual_hours"],
        )
        entry["hourly_equivalent"] = position_amount_to_hourly(
            entry["amount"],
            entry["pay_basis"],
            entry["annual_hours"],
        )
        entry["annual_salary"] = round(entry["monthly_equivalent"] * 12, 2)
        entry["per_pay_period_amount"] = monthly_pay_to_per_pay_period(entry["monthly_equivalent"])
        rates[title] = entry
    return {
        "success": True,
        "rates": rates,
        "pay_periods_per_year": count_pay_periods_in_year(),
        "default_annual_hours": default_annual_hours_for_title(None),
        "salary_annual_hours": default_annual_hours_for_title("Chief"),
    }


def save_position_pay_rates(rates: Dict, user_id: Optional[int] = None) -> Dict:
    """Persist position compensation (amount, basis, salary flag per title)."""
    from config import OFFICER_TITLE_OPTIONS, POSITION_PAY_SETTINGS_KEY
    from logic.payroll import monthly_pay_to_per_pay_period
    from logic.roster_titles import get_officer_title_options
    from validators import (
        default_annual_hours_for_title,
        normalize_position_pay_basis,
        position_amount_to_hourly,
        position_amount_to_monthly,
        validate_position_pay_entry,
    )

    existing = get_position_pay_rates().get("rates") or {}
    stored_raw = get_department_setting(POSITION_PAY_SETTINGS_KEY, "")
    try:
        prior_payload = json.loads(stored_raw) if stored_raw else {}
    except json.JSONDecodeError:
        prior_payload = {}

    payload = dict(prior_payload)
    for title in get_officer_title_options():
        entry = dict(existing.get(title) or {})
        if title in rates:
            entry.update(rates[title] or {})
        try:
            amount = float(entry.get("amount") or 0)
        except (TypeError, ValueError):
            return {"success": False, "message": f"{title}: amount must be numeric"}
        pay_basis = normalize_position_pay_basis(entry.get("pay_basis"))
        is_salary = bool(entry.get("is_salary"))
        try:
            annual_hours = float(entry.get("annual_hours") or default_annual_hours_for_title(title))
        except (TypeError, ValueError):
            return {"success": False, "message": f"{title}: annual hours must be numeric"}
        if amount <= 0:
            if title in OFFICER_TITLE_OPTIONS:
                return {"success": False, "message": f"{title}: amount must be greater than zero"}
            payload.pop(title, None)
            continue
        validation = validate_position_pay_entry(title, amount, pay_basis, is_salary, annual_hours=annual_hours)
        if not validation.ok:
            return {"success": False, "message": validation.message}
        monthly = position_amount_to_monthly(amount, pay_basis, annual_hours)
        payload[title] = {
            "amount": round(amount, 2),
            "pay_basis": pay_basis,
            "is_salary": is_salary,
            "annual_hours": round(annual_hours, 1),
            "monthly_equivalent": monthly,
            "hourly_equivalent": position_amount_to_hourly(amount, pay_basis, annual_hours),
            "annual_salary": round(monthly * 12, 2),
            "per_pay_period_amount": monthly_pay_to_per_pay_period(monthly),
        }

    result = set_department_setting(
        POSITION_PAY_SETTINGS_KEY,
        json.dumps(payload),
        user_id=user_id,
    )
    if not result.get("success"):
        return result
    return {"success": True, "rates": payload, "message": "Position pay rates saved"}


def apply_position_pay_rates_to_roster(user_id: Optional[int] = None) -> Dict:
    """Update each officer pay_rate from their title's configured compensation."""
    from validators import normalize_officer_job_title

    data = get_position_pay_rates()
    rates = data.get("rates") or {}
    officers = get_officers_by_seniority()
    updated = 0
    skipped = 0
    for officer in officers:
        title = normalize_officer_job_title(officer.get("job_title"))
        if not title or title not in rates:
            skipped += 1
            continue
        config = rates[title]
        hourly = config.get("hourly_equivalent") or 0
        if hourly <= 0:
            skipped += 1
            continue
        annual_hours = config.get("annual_hours")
        update_kwargs = {"pay_rate": hourly}
        if annual_hours:
            update_kwargs["annual_hours_target"] = float(annual_hours)
        result = update_officer(officer["id"], **update_kwargs)
        if result.get("success"):
            updated += 1
        else:
            skipped += 1
    _log_audit(
        "payroll.position_rates_apply",
        "payroll",
        None,
        user_id,
        f"updated={updated}, skipped={skipped}",
    )
    return {
        "success": True,
        "updated": updated,
        "skipped": skipped,
        "message": f"Applied position rates to {updated} officer(s)",
    }


def get_open_shifts(
    status: str = "open",
    limit: int = 50,
    officer_id: Optional[int] = None,
) -> List[Dict]:
    with connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT s.*, o.name AS filled_by_name
            FROM open_shifts s
            LEFT JOIN officers o ON s.filled_by_officer_id = o.id
            WHERE s.status = ?
            ORDER BY s.shift_date, s.shift_start
            LIMIT ?
        """,
            (status, limit),
        )
        rows = [dict(r) for r in cursor.fetchall()]
    if officer_id is not None:
        officer = get_officer_by_id(officer_id)
        if officer:
            rows = [r for r in rows if not r.get("squad") or r["squad"] == officer["squad"]]
    return rows


def create_open_shift(
    shift_date: str,
    shift_start: str,
    shift_end: str,
    squad: Optional[str] = None,
    notes: str = "",
    user_id: Optional[int] = None,
) -> Dict:
    from logic.requests import _notify_open_shift_posted
    from validators import validate_officer_shift

    validation = validate_officer_shift(shift_start, shift_end)
    if not validation.ok:
        return {"success": False, "message": validation.message}
    try:
        shift_date = storage_date_str(shift_date)
    except ValueError:
        return {"success": False, "message": f"Shift date must be {DATE_INPUT_HINT}"}
    if squad and squad not in ("A", "B"):
        return {"success": False, "message": "Squad must be A or B"}

    with connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO open_shifts (shift_date, shift_start, shift_end, squad, notes)
                VALUES (?, ?, ?, ?, ?)
            """,
                (shift_date, shift_start, shift_end, squad, notes or None),
            )
            shift_id = cursor.lastrowid
            conn.commit()
            _log_audit("open_shift.create", "open_shift", shift_id, user_id, shift_date)
            _notify_open_shift_posted(shift_id, shift_date, shift_start, shift_end, squad)
            return {"success": True, "shift_id": shift_id}
        except Exception as e:
            conn.rollback()
            return {"success": False, "message": str(e)}


def rank_open_shift_candidates(shift_id: int, *, limit: int = 12) -> Dict:
    """
    TeleStaff-style vacancy ranking: certs + rest + fatigue/OT equity + junior-first.

    Does not fill — returns ordered candidates for supervisor/self-service.
    """
    from logic.analytics import get_equitable_ot_ledger
    from logic.certifications import officer_meets_shift_cert_requirements
    from logic.officers import get_officers_by_seniority
    from validators import parse_date

    with connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM open_shifts WHERE id = ? AND status = 'open'", (shift_id,))
        row = cursor.fetchone()
    if not row:
        return {"success": False, "message": "Open shift not found", "candidates": []}
    shift = dict(row)
    try:
        as_of = parse_date(shift["shift_date"])
    except Exception:
        return {"success": False, "message": "Invalid shift date", "candidates": []}

    ot_by: Dict[int, float] = {}
    try:
        for r in (get_equitable_ot_ledger(as_of) or {}).get("ledger") or []:
            if isinstance(r, dict) and r.get("officer_id") is not None:
                ot_by[int(r["officer_id"])] = float(r.get("ot_hours") or 0)
    except Exception:
        pass

    squad = shift.get("squad")
    station = (shift.get("station") or "").strip()
    candidates = []
    for o in get_officers_by_seniority():
        if o.get("active") != 1:
            continue
        if squad and o.get("squad") and o.get("squad") != squad:
            continue
        # Prefer same station when vacancy is station-scoped (ESO multi-post pattern)
        oid = o["id"]
        try:
            cert_ok, _ = officer_meets_shift_cert_requirements(oid, shift["shift_start"], as_of)
        except Exception:
            cert_ok = False
        if not cert_ok:
            continue
        rank = int(o.get("seniority_rank") or 0)
        ot_h = ot_by.get(oid, 0.0)
        station_bonus = 5.0 if station and (o.get("station") or "").strip() == station else 0.0
        # Prefer junior (higher rank number) and lower OT (TeleStaff fatigue)
        score = rank * 10.0 + max(0.0, 40.0 - min(ot_h, 40.0)) * 2.0 + station_bonus
        candidates.append(
            {
                "officer_id": oid,
                "officer_name": o.get("name"),
                "squad": o.get("squad"),
                "seniority_rank": rank,
                "ot_hours": round(ot_h, 2),
                "score": round(score, 2),
                "station": o.get("station") or "",
            }
        )
    candidates.sort(key=lambda c: (-c["score"], c["officer_id"]))
    return {
        "success": True,
        "shift_id": shift_id,
        "shift_date": shift.get("shift_date"),
        "shift_start": shift.get("shift_start"),
        "candidates": candidates[:limit],
        "count": min(len(candidates), limit),
    }


def fill_open_shift(shift_id: int, officer_id: int, user_id: Optional[int] = None) -> Dict:
    from logic.certifications import officer_meets_shift_cert_requirements
    from logic.requests import _notify_open_shift_filled
    from validators import parse_date

    officer = get_officer_by_id(officer_id)
    if not officer:
        return {"success": False, "message": "Officer not found"}

    with connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT * FROM open_shifts WHERE id = ? AND status = 'open'", (shift_id,))
            row = cursor.fetchone()
            if not row:
                return {"success": False, "message": "Open shift not found"}
            shift = dict(row)
            cert_ok, cert_msg = officer_meets_shift_cert_requirements(
                officer_id,
                shift["shift_start"],
                parse_date(shift["shift_date"]),
            )
            if not cert_ok:
                return {"success": False, "message": cert_msg}
            try:
                from logic.fatigue_gates import check_rest_hard_stop

                rest = check_rest_hard_stop(
                    int(officer_id),
                    work_date=str(shift["shift_date"]),
                    shift_start=shift.get("shift_start"),
                    shift_end=shift.get("shift_end"),
                    user_id=user_id,
                )
                if rest.get("blocked"):
                    return {
                        "success": False,
                        "message": rest.get("message") or "Rest/fatigue hard stop",
                        "requires_override": True,
                    }
            except Exception:
                pass
            cursor.execute(
                """
                UPDATE open_shifts
                SET status = 'filled', filled_by_officer_id = ?
                WHERE id = ?
            """,
                (officer_id, shift_id),
            )
            conn.commit()
            _log_audit("open_shift.fill", "open_shift", shift_id, user_id, officer["name"])
            _notify_open_shift_filled(dict(row), officer)
            return {"success": True}
        except Exception as e:
            conn.rollback()
            return {"success": False, "message": str(e)}


def add_holiday(
    name: str,
    holiday_date: str,
    is_paid: bool = True,
    notes: str = "",
    user_id: Optional[int] = None,
) -> Dict:
    from validators import validate_holiday

    validation = validate_holiday(name, holiday_date)
    if not validation.ok:
        return {"success": False, "message": validation.message}

    holiday_date = storage_date_str(holiday_date)
    with connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO holidays (holiday_date, name, is_paid, notes)
                VALUES (?, ?, ?, ?)
            """,
                (holiday_date, name.strip(), 1 if is_paid else 0, notes or None),
            )
            holiday_id = cursor.lastrowid
            conn.commit()
            _log_audit("holiday.add", "holiday", holiday_id, user_id, name)
            return {"success": True, "holiday_id": holiday_id}
        except sqlite3.IntegrityError:
            return {"success": False, "message": "Holiday already exists for that date"}
        except Exception as e:
            conn.rollback()
            return {"success": False, "message": str(e)}


def add_officer_availability(
    officer_id: int,
    unavailable_date: str,
    reason: str = "",
    user_id: Optional[int] = None,
) -> Dict:
    from logic.requests import _notify_availability_conflict
    from validators import validate_availability_entry

    officer = get_officer_by_id(officer_id)
    validation = validate_availability_entry(officer, unavailable_date)
    if not validation.ok:
        return {"success": False, "message": validation.message}

    unavailable_date = storage_date_str(unavailable_date)
    with connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO officer_availability (officer_id, unavailable_date, reason)
                VALUES (?, ?, ?)
            """,
                (officer_id, unavailable_date, reason or None),
            )
            entry_id = cursor.lastrowid
            conn.commit()
            _log_audit(
                "availability.add",
                "availability",
                entry_id,
                user_id,
                f"officer={officer_id} date={unavailable_date}",
            )
            from validators import parse_date

            status = get_officer_day_status(officer_id, parse_date(unavailable_date))
            schedule_conflict = status in ("working", "covering", "swapped")
            result = {"success": True, "entry_id": entry_id, "schedule_conflict": schedule_conflict}
            if schedule_conflict:
                result["warning"] = "Recorded, but this date conflicts with your scheduled shift"
                _notify_availability_conflict(officer, entry_id, unavailable_date, status)
            return result
        except sqlite3.IntegrityError:
            return {"success": False, "message": "Availability already recorded for that date"}
        except Exception as e:
            conn.rollback()
            return {"success": False, "message": str(e)}


def delete_officer_availability(entry_id: int, user_id: Optional[int] = None) -> Dict:
    with connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT id FROM officer_availability WHERE id = ?", (entry_id,))
            if not cursor.fetchone():
                return {"success": False, "message": "Availability entry not found"}
            cursor.execute("DELETE FROM officer_availability WHERE id = ?", (entry_id,))
            conn.commit()
            _log_audit("availability.delete", "availability", entry_id, user_id)
            return {"success": True}
        except Exception as e:
            conn.rollback()
            return {"success": False, "message": str(e)}


def update_holiday(
    holiday_id: int,
    name: str,
    holiday_date: str,
    is_paid: bool = True,
    notes: str = "",
    user_id: Optional[int] = None,
) -> Dict:
    from validators import validate_holiday

    validation = validate_holiday(name, holiday_date)
    if not validation.ok:
        return {"success": False, "message": validation.message}

    holiday_date = storage_date_str(holiday_date)
    with connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT id FROM holidays WHERE id = ?", (holiday_id,))
            if not cursor.fetchone():
                return {"success": False, "message": "Holiday not found"}
            cursor.execute(
                """
                UPDATE holidays
                SET holiday_date = ?, name = ?, is_paid = ?, notes = ?
                WHERE id = ?
            """,
                (holiday_date, name.strip(), 1 if is_paid else 0, notes or None, holiday_id),
            )
            conn.commit()
            _log_audit("holiday.update", "holiday", holiday_id, user_id, name)
            return {"success": True, "holiday_id": holiday_id}
        except sqlite3.IntegrityError:
            return {"success": False, "message": "Another holiday already exists for that date"}
        except Exception as e:
            conn.rollback()
            return {"success": False, "message": str(e)}


def delete_holiday(holiday_id: int, user_id: Optional[int] = None) -> Dict:
    with connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("DELETE FROM holidays WHERE id = ?", (holiday_id,))
            if cursor.rowcount == 0:
                return {"success": False, "message": "Holiday not found"}
            conn.commit()
            _log_audit("holiday.delete", "holiday", holiday_id, user_id)
            return {"success": True}
        except Exception as e:
            conn.rollback()
            return {"success": False, "message": str(e)}


def get_all_department_settings() -> Dict[str, str]:
    with connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT key, value FROM department_settings ORDER BY key")
        rows = {r["key"]: r["value"] for r in cursor.fetchall()}
    return rows


def get_holidays(year: Optional[int] = None) -> List[Dict]:
    with connection() as conn:
        cursor = conn.cursor()
        if year:
            cursor.execute(
                """
                SELECT * FROM holidays
                WHERE strftime('%Y', holiday_date) = ?
                ORDER BY holiday_date
            """,
                (str(year),),
            )
        else:
            cursor.execute("SELECT * FROM holidays ORDER BY holiday_date")
        rows = [dict(r) for r in cursor.fetchall()]
    return rows


def get_holidays_in_range(start: date, end: date) -> List[Dict]:
    """Holidays between start and end dates (inclusive)."""
    with connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM holidays
            WHERE holiday_date >= ? AND holiday_date <= ?
            ORDER BY holiday_date
        """,
            (start.isoformat(), end.isoformat()),
        )
        rows = [dict(r) for r in cursor.fetchall()]
    return rows


def get_officer_availability(
    officer_id: Optional[int] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> List[Dict]:
    query = """
        SELECT a.*, o.name AS officer_name, o.squad
        FROM officer_availability a
        JOIN officers o ON a.officer_id = o.id
    """
    clauses = []
    params: List = []
    if officer_id:
        clauses.append("a.officer_id = ?")
        params.append(officer_id)
    if start_date:
        clauses.append("a.unavailable_date >= ?")
        params.append(start_date.isoformat())
    if end_date:
        clauses.append("a.unavailable_date <= ?")
        params.append(end_date.isoformat())
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY a.unavailable_date, o.name"
    with connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        rows = [dict(r) for r in cursor.fetchall()]
    return rows


def get_officer_time_banks(officer_id: int, as_of: Optional[date] = None) -> Dict:
    from logic.payroll import _ensure_officer_time_banks

    as_of = as_of or date.today()
    with connection() as conn:
        cursor = conn.cursor()
        try:
            banks = _ensure_officer_time_banks(cursor, officer_id, as_of)
            conn.commit()
            return {
                "success": True,
                "comp_hours": banks["comp_hours"],
                "sick_hours": banks["sick_hours"],
                "float_holiday_hours": banks["float_holiday_hours"],
                "holiday_hours": banks["holiday_hours"],
            }
        except Exception as e:
            conn.rollback()
            return {"success": False, "message": str(e)}


def get_pending_manual_review_count() -> int:
    with connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM day_off_requests WHERE status = 'Pending Manual Review'")
        count = cursor.fetchone()[0]
    return count


def get_upcoming_holidays(days_ahead: int = 60) -> List[Dict]:
    today = date.today()
    end = today + timedelta(days=days_ahead)
    with connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM holidays
            WHERE holiday_date >= ? AND holiday_date <= ?
            ORDER BY holiday_date
        """,
            (today.isoformat(), end.isoformat()),
        )
        rows = [dict(r) for r in cursor.fetchall()]
    return rows


def is_officer_unavailable_on_date(officer_id: int, target_date: date) -> bool:
    from validators import _officer_unavailable_on_date

    return _officer_unavailable_on_date(officer_id, target_date)


def get_backup_status(*, max_age_days: int = 7) -> Dict:
    """Latest backup age for dashboard reminders and admin UI."""
    from database import list_backup_files
    from paths import data_path

    today = date.today()
    last_setting = get_department_setting("last_auto_backup") or ""
    last_manual = get_department_setting("last_manual_backup") or ""
    files = list_backup_files()
    latest_path = files[0] if files else None
    latest_mtime_days: Optional[int] = None
    if latest_path:
        import os
        from datetime import datetime

        mtime = datetime.fromtimestamp(os.path.getmtime(latest_path))
        latest_mtime_days = (today - mtime.date()).days

    days_since = latest_mtime_days
    if last_setting:
        try:
            days_setting = (today - parse_date(last_setting)).days
            days_since = days_since if days_since is not None else days_setting
            if days_since is not None:
                days_since = min(days_since, days_setting)
            else:
                days_since = days_setting
        except ValueError:
            pass

    needs_backup = days_since is None or days_since >= max_age_days
    return {
        "success": True,
        "backup_dir": data_path("backups"),
        "latest_path": latest_path,
        "latest_age_days": days_since,
        "needs_backup": needs_backup,
        "max_age_days": max_age_days,
        "last_auto_backup": last_setting or None,
        "last_manual_backup": last_manual or None,
        "backup_count": len(files),
    }


def restore_database_from_backup(backup_path: str, *, user_id: Optional[int] = None) -> Dict:
    from database import restore_database

    try:
        safety_path = restore_database(backup_path)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        return {"success": False, "message": str(exc)}
    set_department_setting("last_manual_backup", date.today().isoformat())
    _log_audit("database.restore", "database", None, user_id, f"{backup_path} -> safety:{safety_path}")
    return {
        "success": True,
        "message": "Database restored from backup. Restart recommended if data looks stale.",
        "safety_backup": safety_path,
        "restored_from": backup_path,
    }


def maybe_run_auto_backup(max_age_days: int = 7) -> Optional[str]:

    last = get_department_setting("last_auto_backup") or ""
    today = date.today()
    if last:
        try:
            last_date = parse_date(last)
            if (today - last_date).days < max_age_days:
                return None
        except ValueError:
            pass
    path = backup_database()
    set_department_setting("last_auto_backup", today.isoformat())
    _log_audit("database.auto_backup", "database", None, None, path)
    return path
