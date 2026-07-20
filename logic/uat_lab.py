"""Virtual UAT lab — prepare demo accounts + sample data for full-product remote testing.

Enable with SCHEDULER_UAT_LAB=1 (Start Remote UAT Tunnel.bat sets this).

Goals:
  · Testers open one URL and exercise the whole product as Administration
  · Demo passwords work without must_change_password friction
  · Enough seed rows that leave / open shifts / notify / ops are not empty shells
"""

from __future__ import annotations

import os
from datetime import date, timedelta
from typing import Any, Dict, List


def uat_lab_enabled() -> bool:
    return os.environ.get("SCHEDULER_UAT_LAB", "").strip().lower() in ("1", "true", "yes", "on")


def prepare_uat_lab() -> Dict[str, Any]:
    """Idempotent prep. Safe to call on every server start when UAT lab is on."""
    if not uat_lab_enabled():
        return {"success": False, "skipped": True, "message": "SCHEDULER_UAT_LAB not set"}

    notes: List[str] = []
    try:
        from database import init_database

        init_database()
    except Exception as exc:
        return {"success": False, "message": f"init_database: {exc}"}

    notes.extend(_ensure_demo_accounts())
    notes.extend(_clear_must_change_password())
    notes.extend(_seed_sample_activity())
    notes.append("full product = login Administration (admin/admin)")
    notes.append("optional roles: supervisor/supervisor · officer/officer")

    return {"success": True, "uat_lab": True, "notes": notes}


def _ensure_demo_accounts() -> List[str]:
    from auth_password import hash_password
    from database import connection

    notes: List[str] = []
    wanted = (
        ("admin", "admin", "Administration"),
        ("supervisor", "supervisor", "Supervisor"),
        ("officer", "officer", "Officer"),
    )
    with connection() as conn:
        cur = conn.cursor()
        try:
            # Link officer to first active roster row when possible
            cur.execute("SELECT id FROM officers WHERE active = 1 ORDER BY id LIMIT 1")
            row = cur.fetchone()
            default_oid = int(row[0]) if row else None

            for username, password, role in wanted:
                cur.execute("SELECT id, role FROM app_users WHERE username = ?", (username,))
                existing = cur.fetchone()
                if existing:
                    cur.execute(
                        """
                        UPDATE app_users
                        SET password = ?, role = ?, must_change_password = 0, active = 1
                        WHERE username = ?
                        """,
                        (hash_password(password), role, username),
                    )
                    notes.append(f"reset {username} → {role}")
                else:
                    oid = default_oid if role == "Officer" else None
                    cur.execute(
                        """
                        INSERT INTO app_users
                        (officer_id, username, password, role, must_change_password, active)
                        VALUES (?, ?, ?, ?, 0, 1)
                        """,
                        (oid, username, hash_password(password), role),
                    )
                    notes.append(f"created {username} → {role}")
            conn.commit()
        except Exception as exc:
            conn.rollback()
            notes.append(f"accounts warn: {exc}")
    return notes


def _clear_must_change_password() -> List[str]:
    from database import connection

    try:
        with connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "UPDATE app_users SET must_change_password = 0 WHERE username IN ('admin','supervisor','officer')"
            )
            n = cur.rowcount
            conn.commit()
        return [f"must_change_password cleared n={n}"]
    except Exception as exc:
        return [f"must_change clear warn: {exc}"]


def _seed_sample_activity() -> List[str]:
    """Light sample rows so UI pages show real widgets during UAT."""
    notes: List[str] = []
    try:
        from config import SHIFT_TIMES
        from logic.officers import get_officers_by_seniority
        from logic.operations import create_open_shift, get_open_shifts
        from logic.requests import create_day_off_request, create_notification

        offs = [o for o in (get_officers_by_seniority() or []) if o.get("active", 1)]
        if not offs:
            notes.append("no officers — roster empty")
            return notes
        oid = int(offs[0]["id"])
        squad = str(offs[0].get("squad") or "A")

        # Pending leave (ignore if validation blocks)
        try:
            from logic.scheduling import officer_base_rotation_working

            day = date.today()
            for i in range(0, 28):
                d = day + timedelta(days=i)
                if officer_base_rotation_working(offs[0], d):
                    r = create_day_off_request(oid, d.isoformat(), "Vacation", "uat_lab_seed")
                    if r.get("success"):
                        notes.append(f"sample leave rid={r.get('request_id')} day={d}")
                    else:
                        notes.append(f"leave seed: {r.get('message', '')[:60]}")
                    break
        except Exception as exc:
            notes.append(f"leave seed skip: {exc}")

        # Open shift
        try:
            listed = get_open_shifts()
            n = len(listed) if isinstance(listed, list) else 0
            if n == 0:
                start, end = SHIFT_TIMES[1]
                day_s = (date.today() + timedelta(days=5)).isoformat()
                r = create_open_shift(day_s, start, end, squad=squad, notes="UAT lab open shift")
                notes.append(f"open shift: {r.get('success')} {r.get('message', '')[:40]}")
            else:
                notes.append(f"open shifts already n={n}")
        except Exception as exc:
            notes.append(f"open shift skip: {exc}")

        # In-app notify
        try:
            create_notification(
                oid,
                "system",
                "Welcome to Chronos UAT",
                "Sign in as admin/admin for full product access. See /uat for the feature map.",
            )
            notes.append("welcome notification")
        except Exception as exc:
            notes.append(f"notify skip: {exc}")
    except Exception as exc:
        notes.append(f"sample activity: {exc}")
    return notes


def uat_feature_map() -> List[Dict[str, str]]:
    """Every primary Chronos surface for the tester hub (full product)."""
    return [
        {"path": "/", "title": "Duty Board", "area": "Overview"},
        {"path": "/my-week", "title": "My Week", "area": "Overview"},
        {"path": "/notifications", "title": "Alerts", "area": "Overview"},
        {"path": "/my-schedule", "title": "My Schedule", "area": "Scheduling"},
        {"path": "/monthly-schedule", "title": "Monthly Schedule", "area": "Scheduling"},
        {"path": "/live-schedule", "title": "Live Schedule", "area": "Scheduling"},
        {"path": "/time-off", "title": "Time Off Requests", "area": "Scheduling"},
        {"path": "/open-shifts", "title": "Open Shifts", "area": "Scheduling"},
        {"path": "/bidding", "title": "Shift Bidding", "area": "Scheduling"},
        {"path": "/callbacks", "title": "Callback Rotation", "area": "Scheduling"},
        {"path": "/court", "title": "Court & Training", "area": "Scheduling"},
        {"path": "/availability", "title": "Availability", "area": "Scheduling"},
        {"path": "/roster", "title": "Patrol Roster", "area": "Personnel"},
        {"path": "/certs", "title": "Certifications", "area": "Personnel"},
        {"path": "/timecards", "title": "Timecards", "area": "Finance"},
        {"path": "/time-punch", "title": "Time Punch", "area": "Finance"},
        {"path": "/banks", "title": "Time Banks", "area": "Finance"},
        {"path": "/payroll", "title": "Payroll", "area": "Finance"},
        {"path": "/ops-desk", "title": "Ops Desk", "area": "Command"},
        {"path": "/simulator", "title": "Schedule Simulator", "area": "Command"},
        {"path": "/operations", "title": "Ops Reports", "area": "Command"},
        {"path": "/exports", "title": "Exports Hub", "area": "Command"},
        {"path": "/channels", "title": "Notify Channels", "area": "Command"},
        {"path": "/audit", "title": "Audit Trail", "area": "Command"},
        {"path": "/deploy", "title": "Deploy & Implement", "area": "Command"},
        {"path": "/media", "title": "Branding & Media", "area": "Command"},
        {"path": "/security", "title": "Security & Governance", "area": "Command"},
        {"path": "/access", "title": "Access Control", "area": "Command"},
    ]
