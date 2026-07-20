"""Call-back rotation list and event tracking."""

from datetime import date
from typing import Dict, List, Optional

from database import connection
from logic.officers import get_officer_by_id, get_officers_by_seniority
from logic.users import log_audit_action
from validators import is_officer_active, storage_date_str


def get_callback_rotation(*, active_only: bool = True) -> List[Dict]:
    with connection() as conn:
        cursor = conn.cursor()
        query = """
            SELECT r.*, o.name AS officer_name, o.squad, o.seniority_rank
            FROM callback_rotation r
            JOIN officers o ON r.officer_id = o.id
        """
        if active_only:
            query += " WHERE r.active = 1 AND o.active = 1"
        query += " ORDER BY r.sort_order ASC, o.seniority_rank ASC"
        cursor.execute(query)
        rows = [dict(r) for r in cursor.fetchall()]
    return rows


def sync_callback_rotation_from_roster(*, user_id: Optional[int] = None) -> Dict:
    """Ensure every active patrol officer appears on the callback list."""
    with connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT MAX(sort_order) FROM callback_rotation")
            row = cursor.fetchone()
            next_order = (row[0] or 0) + 1
            added = 0
            for officer in get_officers_by_seniority():
                if not is_officer_active(officer):
                    continue
                from validators import officer_uses_command_staff_schedule

                if officer_uses_command_staff_schedule(officer):
                    continue
                cursor.execute(
                    "SELECT id FROM callback_rotation WHERE officer_id = ?",
                    (officer["id"],),
                )
                if cursor.fetchone():
                    continue
                cursor.execute(
                    "INSERT INTO callback_rotation (officer_id, sort_order, active) VALUES (?, ?, 1)",
                    (officer["id"], next_order),
                )
                next_order += 1
                added += 1
            conn.commit()
            if added:
                log_audit_action("callback.sync_rotation", "callback_rotation", None, user_id, f"added={added}")
            return {"success": True, "added": added, "message": f"Added {added} officer(s) to callback rotation"}
        except Exception as exc:
            conn.rollback()
            return {"success": False, "message": str(exc)}


def get_next_callback_candidate(*, as_of: Optional[date] = None) -> Dict:
    """Officer at top of rotation who has not been called back most recently."""
    rotation = get_callback_rotation(active_only=True)
    if not rotation:
        return {"success": True, "candidate": None, "message": "Callback rotation is empty"}

    with connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT officer_id, MAX(event_date) AS last_call
            FROM callback_events
            GROUP BY officer_id
            """
        )
        last_calls = {r["officer_id"]: r["last_call"] for r in cursor.fetchall()}

    def sort_key(entry: Dict):
        oid = entry["officer_id"]
        last = last_calls.get(oid) or "0000-01-01"
        return (last, entry["sort_order"])

    ordered = sorted(rotation, key=sort_key)
    top = ordered[0]
    return {
        "success": True,
        "candidate": {
            "officer_id": top["officer_id"],
            "officer_name": top["officer_name"],
            "squad": top.get("squad"),
            "sort_order": top["sort_order"],
            "last_callback": last_calls.get(top["officer_id"]),
        },
    }


def record_callback_event(
    officer_id: int,
    event_date: str,
    hours: float,
    *,
    notes: str = "",
    user_id: Optional[int] = None,
    allow_zero_hours: bool = False,
    outcome: str = "",
) -> Dict:
    """Record OT/callback offer or worked hours.

    *allow_zero_hours* / *outcome* ``offered``|``declined`` — equity log only
    (no payroll hours). Worked events still require hours > 0.
    """
    officer = get_officer_by_id(officer_id)
    if not officer:
        return {"success": False, "message": "Officer not found"}
    try:
        event_date = storage_date_str(event_date)
    except ValueError as exc:
        return {"success": False, "message": str(exc)}
    try:
        hours_f = float(hours)
    except (TypeError, ValueError):
        return {"success": False, "message": "Hours must be numeric"}
    outcome_n = (outcome or "").strip().lower()
    offer_like = allow_zero_hours or outcome_n in ("offered", "declined", "offer", "turn_down")
    if hours_f < 0:
        return {"success": False, "message": "Hours cannot be negative"}
    if hours_f <= 0 and not offer_like:
        return {"success": False, "message": "Hours must be positive"}
    if hours_f <= 0:
        hours_f = 0.0
    note_parts = []
    if notes:
        note_parts.append(str(notes).strip())
    if outcome_n and outcome_n not in (notes or "").lower():
        note_parts.append(f"[outcome={outcome_n}]")
    notes_final = " · ".join(p for p in note_parts if p) or None

    with connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO callback_events (officer_id, event_date, hours, notes, created_by_user_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (officer_id, event_date, hours_f, notes_final, user_id),
            )
            event_id = cursor.lastrowid
            conn.commit()
            log_audit_action(
                "callback.record",
                "callback_event",
                event_id,
                user_id,
                f"{officer['name']} {hours_f}h {event_date} {outcome_n or 'worked'}",
            )
            return {
                "success": True,
                "event_id": event_id,
                "message": (
                    f"Offer logged for {officer['name']}"
                    if offer_like and hours_f <= 0
                    else f"Recorded {hours_f}h for {officer['name']}"
                ),
                "outcome": outcome_n or ("offered" if hours_f <= 0 else "worked"),
            }
        except Exception as exc:
            conn.rollback()
            return {"success": False, "message": str(exc)}


def record_callback_offer(
    officer_id: int,
    event_date: str,
    *,
    notes: str = "OT offer (call-down)",
    user_id: Optional[int] = None,
    accepted: Optional[bool] = None,
    hours: float = 0.0,
) -> Dict:
    """One-click call-down: log offer; optional accept (with hours) or decline."""
    if accepted is True:
        return record_callback_event(
            officer_id,
            event_date,
            hours if hours > 0 else 0.0,
            notes=notes or "OT offer accepted",
            user_id=user_id,
            allow_zero_hours=hours <= 0,
            outcome="accepted" if hours > 0 else "offered",
        )
    if accepted is False:
        return record_callback_event(
            officer_id,
            event_date,
            0.0,
            notes=notes or "OT offer declined",
            user_id=user_id,
            allow_zero_hours=True,
            outcome="declined",
        )
    return record_callback_event(
        officer_id,
        event_date,
        0.0,
        notes=notes or "OT offer (call-down) — pending accept",
        user_id=user_id,
        allow_zero_hours=True,
        outcome="offered",
    )


def get_callback_events(*, limit: int = 50, officer_id: Optional[int] = None) -> List[Dict]:
    with connection() as conn:
        cursor = conn.cursor()
        if officer_id is not None:
            cursor.execute(
                """
                SELECT e.*, o.name AS officer_name
                FROM callback_events e
                JOIN officers o ON e.officer_id = o.id
                WHERE e.officer_id = ?
                ORDER BY e.event_date DESC, e.id DESC
                LIMIT ?
                """,
                (officer_id, limit),
            )
        else:
            cursor.execute(
                """
                SELECT e.*, o.name AS officer_name
                FROM callback_events e
                JOIN officers o ON e.officer_id = o.id
                ORDER BY e.event_date DESC, e.id DESC
                LIMIT ?
                """,
                (limit,),
            )
        rows = [dict(r) for r in cursor.fetchall()]
    return rows


def get_callback_ledger(limit: int = 30) -> Dict:
    """Summary for Ops Reports — rotation order + recent events."""
    rotation = get_callback_rotation(active_only=True)
    events = get_callback_events(limit=limit)
    next_up = get_next_callback_candidate()
    return {
        "success": True,
        "rotation": rotation,
        "recent_events": events,
        "next_candidate": next_up.get("candidate"),
        "rotation_count": len(rotation),
        "event_count": len(events),
    }


def run_callback_calldown(
    event_date: str,
    *,
    max_offers: int = 5,
    notes: str = "Auto call-down sequence",
    user_id: Optional[int] = None,
    notify: bool = True,
) -> Dict:
    """Offer OT to next N rotation candidates (decline-style equity log for each).

    Does not auto-accept. Logs ``offered`` for each candidate in fairness order,
    optionally SMS/email pages them, and returns the ordered offer list.
    """
    try:
        event_date = storage_date_str(event_date)
    except ValueError as exc:
        return {"success": False, "message": str(exc), "offers": []}
    try:
        n = max(1, min(int(max_offers or 5), 20))
    except (TypeError, ValueError):
        n = 5

    rotation = get_callback_rotation(active_only=True)
    if not rotation:
        return {"success": False, "message": "Callback rotation is empty — sync roster", "offers": []}

    with connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT officer_id, MAX(event_date) AS last_call
            FROM callback_events
            GROUP BY officer_id
            """
        )
        last_calls = {r["officer_id"]: r["last_call"] for r in cursor.fetchall()}

    ordered = sorted(
        rotation,
        key=lambda e: (last_calls.get(e["officer_id"]) or "0000-01-01", e["sort_order"]),
    )
    offers: List[Dict] = []
    for entry in ordered[:n]:
        oid = int(entry["officer_id"])
        r = record_callback_offer(
            oid,
            event_date,
            notes=f"{notes} · position {len(offers) + 1}",
            user_id=user_id,
            accepted=None,
        )
        row = {
            "officer_id": oid,
            "officer_name": entry.get("officer_name"),
            "squad": entry.get("squad"),
            "sort_order": entry.get("sort_order"),
            "position": len(offers) + 1,
            "success": bool(r.get("success")),
            "message": r.get("message"),
            "event_id": r.get("event_id"),
        }
        if r.get("success"):
            try:
                from logic.ot_equity_ledger import record_ot_offer

                record_ot_offer(
                    oid,
                    0.0,  # zero-hour offer counts as offer event; hours filled later
                    event_date=event_date,
                    source="callback_calldown",
                    source_id=r.get("event_id"),
                    notes=notes,
                    user_id=user_id,
                )
            except Exception:
                pass
        if notify and r.get("success"):
            try:
                from logic.notify_channels import dispatch_template

                row["notify"] = dispatch_template(
                    "callback_offer",
                    officer_ids=[oid],
                    prefer_sms=True,
                    user_id=user_id,
                    date=event_date,
                    notes=notes,
                )
            except Exception as exc:
                row["notify"] = {"success": False, "message": str(exc)[:120]}
        offers.append(row)

    ok_n = sum(1 for o in offers if o.get("success"))
    log_audit_action(
        "callback.calldown",
        "callback_rotation",
        None,
        user_id,
        f"date={event_date} offered={ok_n}/{len(offers)}",
    )
    return {
        "success": ok_n > 0,
        "event_date": event_date,
        "offers": offers,
        "offered_count": ok_n,
        "message": f"Call-down: offered {ok_n} of {len(offers)} candidate(s) for {event_date}",
    }


def export_callback_equity_csv(
    *,
    limit: int = 500,
    output_path: Optional[str] = None,
) -> Dict:
    """Union/grievance handoff: rotation order + event outcomes CSV."""
    import csv
    from datetime import datetime
    from pathlib import Path

    rotation = get_callback_rotation(active_only=False)
    events = get_callback_events(limit=limit)
    root = Path(__file__).resolve().parent.parent
    out_dir = root / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = (
        Path(output_path)
        if output_path
        else out_dir / f"callback_equity_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    )

    # Aggregate counts per officer for fairness snapshot
    counts: Dict[int, Dict] = {}
    for e in events:
        oid = int(e.get("officer_id") or 0)
        if not oid:
            continue
        bucket = counts.setdefault(
            oid,
            {"offers": 0, "declines": 0, "worked_hours": 0.0, "events": 0},
        )
        bucket["events"] += 1
        notes = (e.get("notes") or "").lower()
        hrs = float(e.get("hours") or 0)
        if "declined" in notes or "outcome=declined" in notes:
            bucket["declines"] += 1
        elif hrs <= 0 or "offered" in notes or "outcome=offered" in notes:
            bucket["offers"] += 1
        if hrs > 0:
            bucket["worked_hours"] += hrs

    fields = [
        "sort_order",
        "officer_id",
        "officer_name",
        "squad",
        "active",
        "offers_logged",
        "declines_logged",
        "worked_hours",
        "event_count",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for row in rotation:
            oid = int(row["officer_id"])
            c = counts.get(oid) or {}
            w.writerow(
                {
                    "sort_order": row.get("sort_order"),
                    "officer_id": oid,
                    "officer_name": row.get("officer_name"),
                    "squad": row.get("squad"),
                    "active": row.get("active"),
                    "offers_logged": c.get("offers", 0),
                    "declines_logged": c.get("declines", 0),
                    "worked_hours": round(float(c.get("worked_hours") or 0), 2),
                    "event_count": c.get("events", 0),
                }
            )
        # Events detail file sibling
        detail = path.with_name(path.stem + "_events.csv")
        ef = [
            "event_id",
            "event_date",
            "officer_id",
            "officer_name",
            "hours",
            "notes",
        ]
        with detail.open("w", newline="", encoding="utf-8") as df:
            dw = csv.DictWriter(df, fieldnames=ef, extrasaction="ignore")
            dw.writeheader()
            for e in events:
                dw.writerow(
                    {
                        "event_id": e.get("id"),
                        "event_date": e.get("event_date"),
                        "officer_id": e.get("officer_id"),
                        "officer_name": e.get("officer_name"),
                        "hours": e.get("hours"),
                        "notes": e.get("notes"),
                    }
                )

    return {
        "success": True,
        "path": str(path),
        "events_path": str(detail),
        "rotation_count": len(rotation),
        "event_count": len(events),
        "message": f"Exported equity for {len(rotation)} officer(s), {len(events)} event(s)",
    }
