"""Time punch policy + officer clock + punch correction approvals.

Department setting ``punch_required`` (default **off**):
  - off → officers may free-enter timecard hours (and may still punch)
  - on  → officers clock in/out; manual timecard entry blocked for officers

Any change to an existing punch (forgot time, wrong type) goes through
``punch_edit_requests`` → supervisor notify → approve/reject.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from database import connection

PUNCH_REQUIRED_KEY = "punch_required"


def ensure_punch_tables() -> None:
    from logic.geofence_clock import ensure_geofence_tables

    ensure_geofence_tables()
    with connection() as conn:
        # Extra columns on punches for audit of applied edits
        cols = {r[1] for r in conn.execute("PRAGMA table_info(geofence_punches)").fetchall()}
        if "edited" not in cols:
            conn.execute("ALTER TABLE geofence_punches ADD COLUMN edited INTEGER DEFAULT 0")
        if "original_created_at" not in cols:
            conn.execute("ALTER TABLE geofence_punches ADD COLUMN original_created_at TIMESTAMP")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS punch_edit_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                punch_id INTEGER NOT NULL,
                officer_id INTEGER NOT NULL,
                requested_by_user_id INTEGER,
                current_punch_type TEXT,
                current_created_at TEXT,
                proposed_punch_type TEXT,
                proposed_created_at TEXT,
                reason TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                reviewed_by_user_id INTEGER,
                review_notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                reviewed_at TIMESTAMP,
                FOREIGN KEY (punch_id) REFERENCES geofence_punches(id),
                FOREIGN KEY (officer_id) REFERENCES officers(id)
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_punch_edit_status ON punch_edit_requests(status, created_at)")
        conn.commit()


def is_punch_required() -> bool:
    from logic.operations import get_department_setting

    raw = (get_department_setting(PUNCH_REQUIRED_KEY, "0") or "0").strip().lower()
    return raw in ("1", "true", "yes", "on")


def get_punch_policy() -> Dict[str, Any]:
    from logic.geofence_clock import get_geofence_config

    required = is_punch_required()
    return {
        "success": True,
        "punch_required": required,
        "default": False,
        "mode_label": "Punch required" if required else "Free time entry (punch optional)",
        "manual_timecard_allowed_for_officers": not required,
        "geofence": get_geofence_config(),
        "message": (
            "Officers must clock in/out; manual hours blocked for officers."
            if required
            else "Officers may enter hours on the timecard without punching (default)."
        ),
    }


def set_punch_required(required: bool, *, user_id: Optional[int] = None) -> Dict[str, Any]:
    """Admin/supervisor: require punch clock (default off)."""
    from logic.operations import set_department_setting

    set_department_setting(PUNCH_REQUIRED_KEY, "1" if required else "0")
    try:
        from logic.users import log_audit_action

        log_audit_action(
            "punch.policy_set",
            "department_settings",
            None,
            user_id,
            f"punch_required={1 if required else 0}",
        )
    except Exception:
        pass
    return {"success": True, "policy": get_punch_policy(), "message": get_punch_policy()["mode_label"]}


def _notify_supervisors(*, title: str, message: str, related_id: Optional[int] = None) -> int:
    from logic.officers import get_request_reviewer_officer_ids
    from logic.requests import create_notification

    n = 0
    for oid in get_request_reviewer_officer_ids() or []:
        try:
            r = create_notification(
                int(oid),
                "Punch Edit",
                title[:120],
                message[:500],
                related_id=related_id,
                related_type="punch_edit_request",
            )
            if r.get("success"):
                n += 1
        except Exception:
            continue
    return n


def _notify_officer(officer_id: int, *, title: str, message: str, related_id: Optional[int] = None) -> None:
    try:
        from logic.requests import create_notification

        create_notification(
            int(officer_id),
            "Punch Edit",
            title[:120],
            message[:500],
            related_id=related_id,
            related_type="punch_edit_request",
        )
    except Exception:
        pass


def officer_clock(
    officer_id: int,
    punch_type: str,
    *,
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    notes: str = "",
    user_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Easy clock in/out for an officer (wraps geofence punch)."""
    from logic.geofence_clock import clock_status, record_geofence_punch

    ensure_punch_tables()
    ptype = (punch_type or "in").strip().lower()
    if ptype not in ("in", "out"):
        return {"success": False, "message": "Use punch type in or out"}
    st = clock_status(int(officer_id))
    if ptype == "in" and st.get("clocked_in"):
        return {"success": False, "message": "Already clocked in — clock out first"}
    if ptype == "out" and not st.get("clocked_in"):
        return {"success": False, "message": "Not clocked in — clock in first"}
    r = record_geofence_punch(
        int(officer_id),
        ptype,
        lat=lat,
        lon=lon,
        notes=(notes or "officer clock")[:200],
    )
    if r.get("success"):
        r["policy"] = get_punch_policy()
        r["status"] = clock_status(int(officer_id))
        try:
            from logic.users import log_audit_action

            log_audit_action(
                "punch.clock",
                "geofence_punch",
                r.get("id"),
                user_id,
                f"officer={officer_id} type={ptype}",
            )
        except Exception:
            pass
    return r


def list_officer_punches(officer_id: int, *, limit: int = 40) -> List[Dict[str, Any]]:
    ensure_punch_tables()
    from logic.geofence_clock import list_geofence_punches

    return list_geofence_punches(officer_id=int(officer_id), limit=limit)


def request_punch_edit(
    punch_id: int,
    officer_id: int,
    *,
    proposed_created_at: str,
    proposed_punch_type: Optional[str] = None,
    reason: str = "",
    user_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Officer requests a correction; does not change punch until approved."""
    ensure_punch_tables()
    reason = (reason or "").strip()
    if len(reason) < 3:
        return {"success": False, "message": "Reason required (why the punch needs changing)"}
    prop_ts = (proposed_created_at or "").strip()
    if not prop_ts:
        return {"success": False, "message": "Proposed date/time required"}
    # Normalize common M/D/YY HH:MM or ISO
    try:
        prop_ts = _normalize_punch_ts(prop_ts)
    except ValueError as exc:
        return {"success": False, "message": str(exc)}

    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM geofence_punches WHERE id = ? AND officer_id = ?",
            (int(punch_id), int(officer_id)),
        ).fetchone()
        if not row:
            return {"success": False, "message": "Punch not found for this officer"}
        punch = dict(row)
        ptype = (proposed_punch_type or punch.get("punch_type") or "in").strip().lower()
        if ptype not in ("in", "out", "break_start", "break_end"):
            return {"success": False, "message": "Invalid proposed punch type"}
        # One pending edit per punch
        pending = conn.execute(
            """
            SELECT id FROM punch_edit_requests
            WHERE punch_id = ? AND status = 'pending'
            """,
            (int(punch_id),),
        ).fetchone()
        if pending:
            return {
                "success": False,
                "message": f"Pending edit request #{pending['id']} already exists for this punch",
            }
        cur = conn.execute(
            """
            INSERT INTO punch_edit_requests
            (punch_id, officer_id, requested_by_user_id, current_punch_type, current_created_at,
             proposed_punch_type, proposed_created_at, reason, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')
            """,
            (
                int(punch_id),
                int(officer_id),
                user_id,
                punch.get("punch_type"),
                str(punch.get("created_at") or ""),
                ptype,
                prop_ts,
                reason[:400],
            ),
        )
        conn.commit()
        req_id = int(cur.lastrowid)

    n = _notify_supervisors(
        title="Punch correction requested",
        message=(
            f"Officer #{officer_id} requests edit on punch #{punch_id}: "
            f"{punch.get('punch_type')} @ {punch.get('created_at')} → {ptype} @ {prop_ts}. "
            f"Reason: {reason[:200]}. Review in Chronos → Time Punch."
        ),
        related_id=req_id,
    )
    try:
        from logic.users import log_audit_action

        log_audit_action(
            "punch.edit_requested",
            "punch_edit_request",
            req_id,
            user_id,
            f"punch={punch_id} → {prop_ts}",
        )
    except Exception:
        pass
    # Channel hook optional
    try:
        from logic.notify_channels import dispatch_channel_hooks
        from logic.officers import get_request_reviewer_officer_ids

        dispatch_channel_hooks(
            subject="Punch correction requested",
            body=f"Punch #{punch_id} edit pending approval. Reason: {reason[:200]}",
            officer_ids=get_request_reviewer_officer_ids(),
            user_id=user_id,
        )
    except Exception:
        pass
    return {
        "success": True,
        "request_id": req_id,
        "supervisors_notified": n,
        "message": f"Edit request #{req_id} submitted — awaiting supervisor approval ({n} notified)",
    }


def _normalize_punch_ts(raw: str) -> str:
    s = raw.strip().replace("T", " ")
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%m/%d/%Y %H:%M",
        "%m/%d/%y %H:%M",
        "%m-%d-%Y %H:%M",
        "%m-%d-%y %H:%M",
        "%Y-%m-%d",
    ):
        try:
            dt = datetime.strptime(s[:19], fmt)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    # Try validators parse_date + time
    try:
        from validators import parse_date

        parts = s.split()
        d = parse_date(parts[0])
        if d and len(parts) >= 2:
            tpart = parts[1]
            if len(tpart) == 5:
                tpart = tpart + ":00"
            return f"{d.isoformat()} {tpart}"
        if d:
            return f"{d.isoformat()} 00:00:00"
    except Exception:
        pass
    raise ValueError("Could not parse date/time — use M/D/YY HH:MM or YYYY-MM-DD HH:MM")


def list_punch_edit_requests(
    *,
    status: str = "pending",
    officer_id: Optional[int] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    ensure_punch_tables()
    limit = max(1, min(int(limit or 50), 200))
    sql = """
        SELECT r.*, o.name AS officer_name
        FROM punch_edit_requests r
        LEFT JOIN officers o ON o.id = r.officer_id
        WHERE 1=1
    """
    params: list = []
    if status and status != "all":
        sql += " AND r.status = ?"
        params.append(status)
    if officer_id is not None:
        sql += " AND r.officer_id = ?"
        params.append(int(officer_id))
    sql += " ORDER BY r.id DESC LIMIT ?"
    params.append(limit)
    with connection() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def approve_punch_edit(
    request_id: int,
    *,
    user_id: Optional[int] = None,
    review_notes: str = "",
) -> Dict[str, Any]:
    ensure_punch_tables()
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM punch_edit_requests WHERE id = ?",
            (int(request_id),),
        ).fetchone()
        if not row:
            return {"success": False, "message": "Request not found"}
        req = dict(row)
        if (req.get("status") or "").lower() != "pending":
            return {"success": False, "message": f"Request already {req.get('status')}"}
        punch = conn.execute(
            "SELECT * FROM geofence_punches WHERE id = ?",
            (int(req["punch_id"]),),
        ).fetchone()
        if not punch:
            return {"success": False, "message": "Original punch missing"}
        punch = dict(punch)
        orig = punch.get("original_created_at") or punch.get("created_at")
        conn.execute(
            """
            UPDATE geofence_punches
            SET punch_type = ?, created_at = ?, edited = 1,
                original_created_at = COALESCE(original_created_at, ?)
            WHERE id = ?
            """,
            (
                req.get("proposed_punch_type") or punch.get("punch_type"),
                req.get("proposed_created_at"),
                orig,
                int(req["punch_id"]),
            ),
        )
        conn.execute(
            """
            UPDATE punch_edit_requests
            SET status = 'approved', reviewed_by_user_id = ?, review_notes = ?,
                reviewed_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (user_id, (review_notes or "")[:240], int(request_id)),
        )
        conn.commit()

    _notify_officer(
        int(req["officer_id"]),
        title="Punch correction approved",
        message=(
            f"Your punch #{req['punch_id']} change was approved "
            f"({req.get('proposed_punch_type')} @ {req.get('proposed_created_at')})."
        ),
        related_id=int(request_id),
    )
    try:
        from logic.users import log_audit_action

        log_audit_action(
            "punch.edit_approved",
            "punch_edit_request",
            int(request_id),
            user_id,
            f"punch={req['punch_id']}",
        )
    except Exception:
        pass
    return {"success": True, "message": f"Approved edit request #{request_id} — punch updated"}


def reject_punch_edit(
    request_id: int,
    *,
    user_id: Optional[int] = None,
    review_notes: str = "",
) -> Dict[str, Any]:
    ensure_punch_tables()
    notes = (review_notes or "").strip()
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM punch_edit_requests WHERE id = ?",
            (int(request_id),),
        ).fetchone()
        if not row:
            return {"success": False, "message": "Request not found"}
        req = dict(row)
        if (req.get("status") or "").lower() != "pending":
            return {"success": False, "message": f"Request already {req.get('status')}"}
        conn.execute(
            """
            UPDATE punch_edit_requests
            SET status = 'rejected', reviewed_by_user_id = ?, review_notes = ?,
                reviewed_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (user_id, notes[:240], int(request_id)),
        )
        conn.commit()

    _notify_officer(
        int(req["officer_id"]),
        title="Punch correction rejected",
        message=(f"Your punch #{req['punch_id']} change was rejected." + (f" Note: {notes}" if notes else "")),
        related_id=int(request_id),
    )
    try:
        from logic.users import log_audit_action

        log_audit_action(
            "punch.edit_rejected",
            "punch_edit_request",
            int(request_id),
            user_id,
            f"punch={req['punch_id']}",
        )
    except Exception:
        pass
    return {"success": True, "message": f"Rejected edit request #{request_id}"}


def assert_manual_timecard_allowed(
    *,
    officer_id: int,
    actor_is_supervisor: bool = False,
    from_punch_pipeline: bool = False,
) -> Dict[str, Any]:
    """Gate free-form timecard entry when punch_required is on."""
    if from_punch_pipeline or actor_is_supervisor or not is_punch_required():
        return {"success": True, "allowed": True}
    return {
        "success": False,
        "allowed": False,
        "message": (
            "Department requires clock in/out. Use Time Punch to record hours, or ask a supervisor to enter time."
        ),
    }
