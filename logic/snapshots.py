"""Schedule snapshots, monthly calendars, sync, and overrides."""

from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

from config import (
    SCHEDULE_SNAPSHOT_TYPES,
    SNAPSHOT_STATUSES,
    is_high_risk_night,
    logger,
)
from database import get_connection
from logic.officers import get_officer_by_id, get_officers_by_seniority
from logic.scheduling import (
    _get_monthly_rotation_base_only,
    _load_override_maps_for_range,
    _officer_day_status,
    _rotation_only_status,
    build_schedule_matrix,
    get_cycle_day,
    get_monthly_rotation_summary,
    get_squad_on_duty,
)
from validators import format_date, normalize_optional_text, storage_date_str


def _insert_override_record(
    cursor,
    override_date,
    original_officer_id,
    replacement_officer_id,
    reason,
    covered_shift_start: Optional[str] = None,
) -> None:
    if covered_shift_start is None:
        original = get_officer_by_id(original_officer_id)
        covered_shift_start = original["shift_start"] if original else None
    cursor.execute(
        """
        INSERT INTO schedule_overrides
        (override_date, original_officer_id, replacement_officer_id, reason, covered_shift_start)
        VALUES (?, ?, ?, ?, ?)
    """,
        (override_date, original_officer_id, replacement_officer_id, reason, covered_shift_start),
    )


def _insert_snapshot_rows(
    cursor,
    snapshot_id: int,
    year: int,
    month: int,
    use_overrides: bool,
    preserve_manual: Optional[Dict[Tuple[str, int], Dict]] = None,
) -> None:
    from logic.shift_assignment import (
        WORKING_ASSIGNMENT_STATUSES,
        covered_shift_for_officer_on_date,
        distribute_shift_bands,
        resolve_assignment_shift,
    )

    start, end = _month_date_range(year, month)
    officers = [o for o in get_officers_by_seniority() if o.get("active") == 1]
    preserve_manual = preserve_manual or {}

    if use_overrides:
        bumped, covering, swapped, bumped_status = _load_override_maps_for_range(start, end)
    else:
        bumped, covering, swapped, bumped_status = {}, {}, {}, {}

    cursor.execute("DELETE FROM schedule_snapshot_rows WHERE snapshot_id = ? AND is_manual = 0", (snapshot_id,))

    current = start
    while current <= end:
        date_str = current.isoformat()
        day_statuses: Dict[int, str] = {}
        for officer in officers:
            key = (date_str, officer["id"])
            if key in preserve_manual:
                continue
            if use_overrides:
                day_statuses[officer["id"]] = _officer_day_status(
                    officer,
                    current,
                    bumped,
                    covering,
                    swapped,
                    bumped_status,
                )
            else:
                day_statuses[officer["id"]] = _rotation_only_status(officer, current)

        assignable = [
            o
            for o in officers
            if day_statuses.get(o["id"]) in WORKING_ASSIGNMENT_STATUSES
            or day_statuses.get(o["id"]) == "covering"
        ]
        band_assignments = distribute_shift_bands(assignable)

        for officer in officers:
            key = (date_str, officer["id"])
            if key in preserve_manual:
                manual = preserve_manual[key]
                cursor.execute(
                    """
                    INSERT INTO schedule_snapshot_rows
                    (snapshot_id, assignment_date, officer_id, status,
                     shift_start, shift_end, is_manual, notes)
                    VALUES (?, ?, ?, ?, ?, ?, 1, ?)
                    ON CONFLICT(snapshot_id, assignment_date, officer_id) DO UPDATE SET
                        status = excluded.status,
                        shift_start = excluded.shift_start,
                        shift_end = excluded.shift_end,
                        is_manual = 1,
                        notes = excluded.notes
                """,
                    (
                        snapshot_id,
                        date_str,
                        officer["id"],
                        manual["status"],
                        manual.get("shift_start") or officer["shift_start"],
                        manual.get("shift_end") or officer["shift_end"],
                        manual.get("notes"),
                    ),
                )
                continue

            status = day_statuses[officer["id"]]
            covered = (
                covered_shift_for_officer_on_date(officer["id"], current)
                if status == "covering"
                else None
            )
            shift_start, shift_end = resolve_assignment_shift(
                officer,
                status,
                band_assignments,
                covered_shift_start=covered,
            )
            cursor.execute(
                """
                INSERT INTO schedule_snapshot_rows
                (snapshot_id, assignment_date, officer_id, status, shift_start, shift_end, is_manual)
                VALUES (?, ?, ?, ?, ?, ?, 0)
            """,
                (
                    snapshot_id,
                    date_str,
                    officer["id"],
                    status,
                    shift_start,
                    shift_end,
                ),
            )
        current += timedelta(days=1)


def _month_date_range(year: int, month: int) -> Tuple[date, date]:
    from calendar import monthrange

    _, last_day = monthrange(year, month)
    return date(year, month, 1), date(year, month, last_day)


def compare_base_updated_schedule(
    year: int,
    month: int,
    officer_id: Optional[int] = None,
) -> Dict:
    """Return row-level differences between published base and synced updated snapshots."""
    base = get_schedule_snapshot(year, month, "base")
    updated = get_schedule_snapshot(year, month, "updated")
    if not base:
        return {"success": False, "message": "Base schedule not published for this month"}
    if not updated:
        return {"success": False, "message": "Updated schedule not synced for this month"}

    def _row_key(row: Dict) -> Tuple[str, int]:
        return (row["assignment_date"], row["officer_id"])

    base_map = {_row_key(r): r for r in base.get("rows", [])}
    updated_map = {_row_key(r): r for r in updated.get("rows", [])}
    all_keys = sorted(set(base_map.keys()) | set(updated_map.keys()))

    diffs = []
    dates_with_changes = set()
    for key in all_keys:
        base_row = base_map.get(key)
        updated_row = updated_map.get(key)
        base_status = base_row["status"] if base_row else None
        updated_status = updated_row["status"] if updated_row else None
        base_shift = (
            (
                base_row.get("assigned_shift_start") or base_row.get("shift_start"),
                base_row.get("assigned_shift_end") or base_row.get("shift_end"),
            )
            if base_row
            else (None, None)
        )
        updated_shift = (
            (
                updated_row.get("assigned_shift_start") or updated_row.get("shift_start"),
                updated_row.get("assigned_shift_end") or updated_row.get("shift_end"),
            )
            if updated_row
            else (None, None)
        )
        base_notes = (base_row.get("notes") or "") if base_row else ""
        updated_notes = (updated_row.get("notes") or "") if updated_row else ""

        row_officer_id = (base_row or updated_row)["officer_id"]
        if officer_id is not None and row_officer_id != officer_id:
            continue

        changed = base_status != updated_status or base_shift != updated_shift or base_notes != updated_notes
        if not changed:
            continue

        assignment_date = key[0]
        dates_with_changes.add(assignment_date)
        diffs.append(
            {
                "assignment_date": assignment_date,
                "officer_id": row_officer_id,
                "officer_name": (base_row or updated_row).get("officer_name", ""),
                "base_status": base_status,
                "updated_status": updated_status,
                "base_shift_start": base_shift[0],
                "base_shift_end": base_shift[1],
                "updated_shift_start": updated_shift[0],
                "updated_shift_end": updated_shift[1],
                "base_notes": base_notes,
                "updated_notes": updated_notes,
                "is_manual": bool(updated_row and updated_row.get("is_manual")),
            }
        )

    return {
        "success": True,
        "year": year,
        "month": month,
        "diff_count": len(diffs),
        "dates_with_changes": sorted(dates_with_changes),
        "diffs": diffs,
    }


def create_manual_coverage_override(
    original_officer_id: int,
    replacement_officer_id: int,
    override_date: str,
    reason: str = "Manual Coverage",
    actor_user_id: Optional[int] = None,
) -> Dict:
    from logic.requests import create_notification
    from logic.users import log_audit_action
    from validators import validate_manual_override

    original = get_officer_by_id(original_officer_id)
    replacement = get_officer_by_id(replacement_officer_id)
    check = validate_manual_override(original, replacement, override_date, reason)
    if not check.ok:
        return {"success": False, "message": check.message}

    override_date = storage_date_str(override_date)
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT id FROM schedule_overrides
            WHERE override_date = ? AND original_officer_id = ?
            """,
            (override_date, original_officer_id),
        )
        if cursor.fetchone():
            return {
                "success": False,
                "message": f"{original['name']} already has coverage assigned on {format_date(override_date)}",
            }

        reason_text = normalize_optional_text(reason) or "Manual Coverage"
        _insert_override_record(
            cursor,
            override_date,
            original_officer_id,
            replacement_officer_id,
            reason_text,
            original["shift_start"],
        )
        conn.commit()
        apply_live_schedule_for_date(override_date, actor_user_id)
        log_audit_action(
            "schedule.manual_override",
            "schedule_override",
            cursor.lastrowid,
            actor_user_id,
            f"{original['name']} → {replacement['name']} on {override_date}",
        )
        create_notification(
            replacement_officer_id,
            "coverage",
            "Manual coverage assignment",
            f"You are assigned to cover {original['name']}'s {original['shift_start']} shift on {override_date}.",
            related_id=None,
            related_type="schedule_override",
        )
        return {
            "success": True,
            "message": (
                f"{replacement['name']} assigned to cover {original['name']} "
                f"({original['shift_start']}) on {override_date}"
            ),
        }
    except Exception as e:
        conn.rollback()
        logger.error(f"Failed to create manual override: {e}")
        return {"success": False, "message": str(e)}
    finally:
        conn.close()


def create_override_record(
    override_date,
    original_officer_id,
    replacement_officer_id,
    reason,
    covered_shift_start: Optional[str] = None,
) -> bool:
    conn = get_connection()
    cursor = conn.cursor()
    try:
        _insert_override_record(
            cursor,
            override_date,
            original_officer_id,
            replacement_officer_id,
            reason,
            covered_shift_start,
        )
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        logger.error(f"Failed to create override: {e}")
        return False
    finally:
        conn.close()


def get_monthly_summary_from_snapshot(
    snapshot: Optional[Dict],
    year: int,
    month: int,
    schedule_type: str = "base",
) -> List[Dict]:
    from calendar import monthrange

    _, last_day = monthrange(year, month)

    if not snapshot:
        if schedule_type == "base":
            return _get_monthly_rotation_base_only(year, month)
        return get_monthly_rotation_summary(year, month)

    rows_by_date: Dict[str, List[Dict]] = {}
    for row in snapshot.get("rows", []):
        rows_by_date.setdefault(row["assignment_date"], []).append(row)

    summary = []
    for day_num in range(1, last_day + 1):
        target = date(year, month, day_num)
        date_str = target.isoformat()
        day_rows = rows_by_date.get(date_str, [])
        working_count = sum(1 for r in day_rows if r["status"] in ("working", "covering", "swapped", "training"))
        cycle_day = get_cycle_day(target)
        summary.append(
            {
                "date": target,
                "cycle_day": cycle_day,
                "squad_on_duty": get_squad_on_duty(cycle_day),
                "working_officers": working_count,
                "high_risk_night": is_high_risk_night(target),
                "snapshot_rows": day_rows,
            }
        )
    return summary


def get_officer_schedule_window(
    officer_id: int,
    start_date: Optional[date] = None,
    days: int = 7,
) -> Dict:
    officer = get_officer_by_id(officer_id)
    if not officer:
        return {"success": False, "message": "Officer not found"}

    start = start_date or date.today()
    end = start + timedelta(days=days - 1)
    matrix, day_list = build_schedule_matrix(start, end)
    entry = next((e for e in matrix if e["officer"]["id"] == officer_id), None)
    schedule_days = []
    for d in day_list:
        status = entry["days"][d] if entry else "off"
        schedule_days.append(
            {
                "date": d.isoformat(),
                "day_label": f"{d.strftime('%a')} {format_date(d)}",
                "status": status,
            }
        )
    return {
        "success": True,
        "officer": officer,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "days": schedule_days,
    }


def get_schedule_snapshot(year: int, month: int, schedule_type: str) -> Optional[Dict]:
    if schedule_type not in SCHEDULE_SNAPSHOT_TYPES:
        return None
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT * FROM schedule_snapshots
        WHERE year = ? AND month = ? AND schedule_type = ?
    """,
        (year, month, schedule_type),
    )
    row = cursor.fetchone()
    if not row:
        conn.close()
        return None
    snapshot = dict(row)
    cursor.execute(
        """
        SELECT r.id, r.snapshot_id, r.assignment_date, r.officer_id, r.status,
               r.shift_start AS assigned_shift_start, r.shift_end AS assigned_shift_end,
               r.is_manual, r.notes,
               o.name AS officer_name, o.squad,
               o.shift_start AS home_shift_start, o.shift_end AS home_shift_end
        FROM schedule_snapshot_rows r
        JOIN officers o ON r.officer_id = o.id
        WHERE r.snapshot_id = ?
        ORDER BY r.assignment_date, o.name
    """,
        (snapshot["id"],),
    )
    snapshot["rows"] = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return snapshot


def _roster_entry_from_snapshot_row(row: Dict) -> Optional[Dict]:
    if row["status"] not in ("working", "covering", "swapped", "training"):
        return None
    shift_start = row.get("assigned_shift_start") or row.get("shift_start") or row.get("home_shift_start")
    shift_end = row.get("assigned_shift_end") or row.get("shift_end") or row.get("home_shift_end")
    return {
        "officer": {
            "id": row["officer_id"],
            "name": row["officer_name"],
            "squad": row["squad"],
            "shift_start": shift_start,
            "shift_end": shift_end,
            "home_shift_start": row.get("home_shift_start"),
            "home_shift_end": row.get("home_shift_end"),
        },
        "status": row["status"],
        "notes": row.get("notes"),
        "is_manual": row.get("is_manual"),
    }


def _roster_from_snapshot_day_rows(day_rows: List[Dict]) -> List[Dict]:
    roster = []
    for row in day_rows:
        entry = _roster_entry_from_snapshot_row(row)
        if entry:
            roster.append(entry)
    return roster


def build_monthly_roster_by_date(
    snapshot: Optional[Dict],
    year: int,
    month: int,
) -> Dict[date, List[Dict]]:
    from calendar import monthrange

    _, last_day = monthrange(year, month)
    result: Dict[date, List[Dict]] = {}

    if not snapshot:
        start = date(year, month, 1)
        end = date(year, month, last_day)
        matrix, days = build_schedule_matrix(start, end)
        for target in days:
            roster = []
            for entry in matrix:
                off = entry["officer"]
                status = entry["days"][target]
                if status in ("working", "covering", "swapped"):
                    roster.append({"officer": off, "status": status})
            result[target] = roster
        return result

    rows_by_date: Dict[str, List[Dict]] = {}
    for row in snapshot.get("rows", []):
        rows_by_date.setdefault(row["assignment_date"], []).append(row)

    for day_num in range(1, last_day + 1):
        target = date(year, month, day_num)
        result[target] = _roster_from_snapshot_day_rows(
            rows_by_date.get(target.isoformat(), []),
        )
    return result


def get_snapshot_day_roster(snapshot: Optional[Dict], target: date) -> List[Dict]:
    if not snapshot:
        matrix, _ = build_schedule_matrix(target, target)
        roster = []
        for entry in matrix:
            off = entry["officer"]
            status = entry["days"][target]
            if status in ("working", "covering", "swapped"):
                roster.append({"officer": off, "status": status})
        return roster

    day_rows = [row for row in snapshot.get("rows", []) if row["assignment_date"] == target.isoformat()]
    return _roster_from_snapshot_day_rows(day_rows)


def ensure_original_monthly_schedule(
    year: int,
    month: int,
    user_id: Optional[int] = None,
) -> Dict:
    """Create and lock the original monthly schedule from rotation rules if not yet generated."""
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT id, locked FROM schedule_snapshots
            WHERE year = ? AND month = ? AND schedule_type = 'base'
        """,
            (year, month),
        )
        existing = cursor.fetchone()
        if existing and existing["locked"]:
            return {
                "success": True,
                "snapshot_id": existing["id"],
                "created": False,
                "message": "Original monthly schedule already generated",
            }

        if existing:
            snapshot_id = existing["id"]
            cursor.execute(
                """
                UPDATE schedule_snapshots
                SET generated_at = CURRENT_TIMESTAMP, generated_by_user_id = ?, locked = 1
                WHERE id = ?
            """,
                (user_id, snapshot_id),
            )
        else:
            cursor.execute(
                """
                INSERT INTO schedule_snapshots (year, month, schedule_type, locked, generated_by_user_id)
                VALUES (?, ?, 'base', 1, ?)
            """,
                (year, month, user_id),
            )
            snapshot_id = cursor.lastrowid

        _insert_snapshot_rows(cursor, snapshot_id, year, month, use_overrides=False)
        conn.commit()
        return {
            "success": True,
            "snapshot_id": snapshot_id,
            "created": True,
            "message": "Original monthly schedule generated",
        }
    except Exception as e:
        conn.rollback()
        return {"success": False, "message": str(e)}
    finally:
        conn.close()


def publish_base_schedule(year: int, month: int, user_id: int) -> Dict:
    result = ensure_original_monthly_schedule(year, month, user_id)
    if not result.get("success"):
        return result
    if not result.get("created"):
        return {
            "success": False,
            "message": "Original monthly schedule already generated and locked",
        }
    return {
        "success": True,
        "snapshot_id": result["snapshot_id"],
        "message": "Original monthly schedule generated",
    }


def set_snapshot_assignment(
    year: int,
    month: int,
    schedule_type: str,
    assignment_date: str,
    officer_id: int,
    status: str,
    notes: str = "",
    shift_start: Optional[str] = None,
    shift_end: Optional[str] = None,
) -> Dict:
    if schedule_type not in SCHEDULE_SNAPSHOT_TYPES:
        return {"success": False, "message": "Invalid schedule type"}
    if status not in SNAPSHOT_STATUSES:
        return {"success": False, "message": f"Invalid status. Use: {', '.join(SNAPSHOT_STATUSES)}"}

    officer = get_officer_by_id(officer_id)
    if not officer:
        return {"success": False, "message": "Officer not found"}

    snapshot = get_schedule_snapshot(year, month, schedule_type)
    if not snapshot:
        return {"success": False, "message": "Schedule not generated yet"}

    if schedule_type == "base" and snapshot.get("locked"):
        return {"success": False, "message": "Base schedule is locked"}

    from logic.shift_assignment import get_shift_band_options, shift_end_for_start

    effective_start = shift_start or officer.get("shift_start") or ""
    effective_end = shift_end or (shift_end_for_start(effective_start) if effective_start else officer.get("shift_end") or "")
    if status in ("working", "covering", "swapped", "training"):
        bands = get_shift_band_options()
        if bands and (effective_start, effective_end) not in bands:
            from validators import validate_officer_shift

            check = validate_officer_shift(effective_start, effective_end)
            if not check.ok:
                return {"success": False, "message": check.message or "Invalid shift band"}

    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            INSERT INTO schedule_snapshot_rows
            (snapshot_id, assignment_date, officer_id, status, shift_start, shift_end, is_manual, notes)
            VALUES (?, ?, ?, ?, ?, ?, 1, ?)
            ON CONFLICT(snapshot_id, assignment_date, officer_id) DO UPDATE SET
                status = excluded.status,
                shift_start = excluded.shift_start,
                shift_end = excluded.shift_end,
                is_manual = 1,
                notes = excluded.notes
        """,
            (
                snapshot["id"],
                assignment_date,
                officer_id,
                status,
                effective_start,
                effective_end,
                notes or None,
            ),
        )
        conn.commit()
        return {"success": True}
    except Exception as e:
        conn.rollback()
        return {"success": False, "message": str(e)}
    finally:
        conn.close()


def apply_live_schedule_for_date(override_date: str, user_id: Optional[int] = None) -> Dict:
    """Rebuild the live (updated) snapshot for the month containing override_date — no publish notify."""
    from validators import parse_date

    try:
        target = parse_date(override_date)
    except ValueError as exc:
        return {"success": False, "message": str(exc)}
    return sync_updated_schedule(target.year, target.month, user_id, notify=False)


def sync_updated_schedule(
    year: int,
    month: int,
    user_id: Optional[int] = None,
    *,
    notify: bool = True,
) -> Dict:
    from logic.requests import _notify_schedule_published

    base_result = ensure_original_monthly_schedule(year, month, user_id)
    if not base_result.get("success"):
        return base_result

    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT id FROM schedule_snapshots
            WHERE year = ? AND month = ? AND schedule_type = 'updated'
        """,
            (year, month),
        )
        row = cursor.fetchone()
        if row:
            snapshot_id = row["id"]
            cursor.execute(
                """
                UPDATE schedule_snapshots
                SET generated_at = CURRENT_TIMESTAMP, generated_by_user_id = ?
                WHERE id = ?
            """,
                (user_id, snapshot_id),
            )
        else:
            cursor.execute(
                """
                INSERT INTO schedule_snapshots (year, month, schedule_type, generated_by_user_id)
                VALUES (?, ?, 'updated', ?)
            """,
                (year, month, user_id),
            )
            snapshot_id = cursor.lastrowid

        cursor.execute(
            """
            SELECT assignment_date, officer_id, status, shift_start, shift_end, notes
            FROM schedule_snapshot_rows
            WHERE snapshot_id = ? AND is_manual = 1
        """,
            (snapshot_id,),
        )
        preserve = {(r["assignment_date"], r["officer_id"]): dict(r) for r in cursor.fetchall()}

        _insert_snapshot_rows(cursor, snapshot_id, year, month, use_overrides=True, preserve_manual=preserve)
        conn.commit()
        if notify:
            _notify_schedule_published(year, month, snapshot_id)
        message = (
            "Live schedule published and staff notified"
            if notify
            else "Live schedule updated"
        )
        return {"success": True, "snapshot_id": snapshot_id, "message": message}
    except Exception as e:
        conn.rollback()
        return {"success": False, "message": str(e)}
    finally:
        conn.close()
