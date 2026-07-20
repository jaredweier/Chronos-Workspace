"""Court / training calendar board — blocks that merge with duty visibility.

Uses day_off_requests of type Court or Training as the source of truth
(no second roster engine). Supervisors see a date-ordered board for the
window; coverage impact is advisory via existing bump preview hooks.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, List, Optional

from database import connection
from validators import format_date, parse_date

COURT_TYPES = ("Court", "Training")


def list_court_training_events(
    *,
    start: Optional[str] = None,
    end: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 200,
) -> Dict:
    """List Court/Training requests in a date window (inclusive)."""
    today = date.today()
    try:
        start_d = parse_date(start) if start else today - timedelta(days=7)
        end_d = parse_date(end) if end else today + timedelta(days=45)
    except ValueError as exc:
        return {"success": False, "message": str(exc), "events": []}
    if end_d < start_d:
        start_d, end_d = end_d, start_d

    with connection() as conn:
        cursor = conn.cursor()
        q = """
            SELECT r.*, o.name AS officer_name, o.squad, o.shift_start, o.shift_end
            FROM day_off_requests r
            JOIN officers o ON r.officer_id = o.id
            WHERE r.request_type IN ('Court', 'Training')
              AND r.request_date >= ? AND r.request_date <= ?
        """
        params: list = [start_d.isoformat(), end_d.isoformat()]
        if status:
            q += " AND r.status = ?"
            params.append(status)
        q += " ORDER BY r.request_date ASC, r.request_type ASC, o.name ASC LIMIT ?"
        params.append(int(limit))
        cursor.execute(q, params)
        rows = [dict(r) for r in cursor.fetchall()]

    events: List[Dict] = []
    for r in rows:
        rd = r.get("request_date")
        try:
            disp = format_date(parse_date(str(rd))) if rd else ""
        except Exception:
            disp = str(rd or "")
        events.append(
            {
                **r,
                "date_display": disp,
                "block_kind": r.get("request_type"),
                "title": f"{r.get('request_type')}: {r.get('officer_name')}",
            }
        )
    return {
        "success": True,
        "start": start_d.isoformat(),
        "end": end_d.isoformat(),
        "count": len(events),
        "events": events,
    }


def create_court_or_training(
    officer_id: int,
    event_date: str,
    request_type: str,
    *,
    notes: str = "",
    user_id: Optional[int] = None,
) -> Dict:
    """Create a Court or Training day-off style block via leave pipeline."""
    rtype = (request_type or "").strip().title()
    if rtype not in COURT_TYPES:
        return {"success": False, "message": "Type must be Court or Training"}
    from logic.requests import create_day_off_request
    from logic.users import log_audit_action

    result = create_day_off_request(
        officer_id,
        event_date,
        rtype,
        notes=notes or rtype,
    )
    if result.get("success") and user_id is not None:
        try:
            log_audit_action(
                "court.create",
                "day_off_request",
                result.get("request_id") or result.get("id"),
                user_id,
                f"{rtype} officer={officer_id} date={event_date}",
            )
        except Exception:
            pass
    return result


def court_calendar_summary(
    *,
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> Dict:
    """Counts by type/status for dashboard strip."""
    board = list_court_training_events(start=start, end=end, limit=500)
    if not board.get("success"):
        return board
    by_type: Dict[str, int] = {}
    by_status: Dict[str, int] = {}
    for e in board.get("events") or []:
        t = e.get("request_type") or "?"
        s = e.get("status") or "?"
        by_type[t] = by_type.get(t, 0) + 1
        by_status[s] = by_status.get(s, 0) + 1
    return {
        "success": True,
        "start": board.get("start"),
        "end": board.get("end"),
        "count": board.get("count"),
        "by_type": by_type,
        "by_status": by_status,
        "events": board.get("events"),
    }
