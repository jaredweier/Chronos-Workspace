"""OT / call-in fill offers for day-off coverage.

Fill modes (department setting):
  - seniority_only: rank by seniority only (senior first = lower seniority_rank)
  - on_duty_partial_first: on-duty adjacent-band first (any order among them), then off-duty
  - on_duty_partial_by_seniority: on-duty adjacent by seniority, then off-duty by seniority
  - off_duty_first: off-duty candidates first, then on-duty

Tracks ordered_in and turned_down per officer per calendar year.
Call list: after ordered-in, officer moves to end of list (furthest from next call).
"""

from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional, Sequence, Tuple

from database import connection
from logic.operations import get_department_setting, set_department_setting
from logic.users import log_audit_action
from validators import parse_date, storage_date_str

FILL_MODE_SENIORITY_ONLY = "seniority_only"
FILL_MODE_ON_DUTY_PARTIAL_FIRST = "on_duty_partial_first"
FILL_MODE_ON_DUTY_PARTIAL_BY_SENIORITY = "on_duty_partial_by_seniority"
FILL_MODE_OFF_DUTY_FIRST = "off_duty_first"

FILL_MODES = [
    FILL_MODE_SENIORITY_ONLY,
    FILL_MODE_ON_DUTY_PARTIAL_FIRST,
    FILL_MODE_ON_DUTY_PARTIAL_BY_SENIORITY,
    FILL_MODE_OFF_DUTY_FIRST,
]

FILL_MODE_LABELS = {
    FILL_MODE_SENIORITY_ONLY: "Seniority only (highest seniority first — all eligible)",
    FILL_MODE_ON_DUTY_PARTIAL_FIRST: "On-duty first (adjacent band partial/whole, then off-duty)",
    FILL_MODE_ON_DUTY_PARTIAL_BY_SENIORITY: "On-duty first by seniority (adjacent band), then off-duty by seniority",
    FILL_MODE_OFF_DUTY_FIRST: "Off-duty first, then on-duty",
}

EVENT_ORDERED_IN = "ordered_in"
EVENT_TURNED_DOWN = "turned_down"
EVENT_VOLUNTEERED = "volunteered"
EVENT_PARTIAL_COVER = "partial_cover"

SETTING_FILL_MODE = "ot_fill_mode"


# Lower seniority_rank = more senior (department convention in this app)
def _seniority_key(officer: Dict) -> Tuple:
    return (int(officer.get("seniority_rank") or 9999), int(officer.get("id") or 0))


def get_ot_fill_mode() -> str:
    raw = (get_department_setting(SETTING_FILL_MODE, FILL_MODE_ON_DUTY_PARTIAL_BY_SENIORITY) or "").strip()
    return raw if raw in FILL_MODES else FILL_MODE_ON_DUTY_PARTIAL_BY_SENIORITY


def set_ot_fill_mode(mode: str, *, user_id: Optional[int] = None) -> Dict:
    mode = (mode or "").strip()
    if mode not in FILL_MODES:
        return {"success": False, "message": f"Invalid fill mode. Use: {', '.join(FILL_MODES)}"}
    r = set_department_setting(SETTING_FILL_MODE, mode, user_id=user_id)
    if not r.get("success"):
        return r
    return {
        "success": True,
        "message": f"OT fill mode: {FILL_MODE_LABELS.get(mode, mode)}",
        "mode": mode,
    }


def get_ot_fill_modes_for_ui() -> Dict:
    current = get_ot_fill_mode()
    return {
        "success": True,
        "mode": current,
        "options": [{"id": m, "label": FILL_MODE_LABELS[m], "selected": m == current} for m in FILL_MODES],
    }


def _adjacent_starts(shift_start: str) -> set:
    from logic.staffing_config import allowed_bump_sources_for_shift, normalize_shift_start_to_active

    covered = normalize_shift_start_to_active(shift_start) or shift_start
    neighbors = set(allowed_bump_sources_for_shift(covered) or ())
    neighbors.add(covered)
    return neighbors


def list_ot_fill_candidates(
    original_officer_id: int,
    request_date: str,
    squad: str,
    shift_start: str,
    *,
    mode: Optional[str] = None,
    include_year_stats: bool = True,
) -> Dict:
    """Ranked candidates for covering a day-off (same paths supervisor sees)."""
    from logic.officers import get_officer_by_id, get_officers_by_seniority
    from logic.scheduling import officer_base_rotation_working
    from validators import officer_uses_command_staff_schedule

    mode = mode or get_ot_fill_mode()
    if mode not in FILL_MODES:
        mode = FILL_MODE_ON_DUTY_PARTIAL_BY_SENIORITY

    try:
        req_date = parse_date(request_date)
    except ValueError as exc:
        return {"success": False, "message": str(exc)}

    year = req_date.year
    adjacent = _adjacent_starts(shift_start)
    original = get_officer_by_id(original_officer_id)
    if not original:
        return {"success": False, "message": "Original officer not found"}

    on_duty: List[Dict] = []
    off_duty: List[Dict] = []

    for officer in get_officers_by_seniority():
        if officer.get("active") != 1:
            continue
        if officer["id"] == original_officer_id:
            continue
        if officer_uses_command_staff_schedule(officer):
            continue
        oid = int(officer["id"])
        working = officer_base_rotation_working(officer, req_date)
        home = officer.get("shift_start") or ""
        from logic.staffing_config import normalize_shift_start_to_active

        home_n = normalize_shift_start_to_active(home) or home
        is_adjacent = home_n in adjacent if home_n else False
        same_squad = (officer.get("squad") or "") == (squad or officer.get("squad"))

        stats = get_officer_ot_fill_year_stats(oid, year) if include_year_stats else {}
        from logic.roster_titles import resolve_officer_callin_limits

        limits = resolve_officer_callin_limits(officer)
        max_td = limits.get("max_turn_downs_year")
        max_oi = limits.get("max_ordered_in_year")
        y_td = int(stats.get("turned_down") or 0)
        y_oi = int(stats.get("ordered_in") or 0)
        blocked_turn_downs = max_td is not None and y_td >= max_td
        blocked_ordered_in = max_oi is not None and y_oi >= max_oi
        # At either yearly cap → not eligible for call-list / order offers
        ineligible = blocked_turn_downs or blocked_ordered_in
        row = {
            "officer_id": oid,
            "name": officer.get("name"),
            "squad": officer.get("squad"),
            "seniority_rank": officer.get("seniority_rank"),
            "shift_start": home,
            "on_duty": working,
            "adjacent_band": is_adjacent,
            "same_squad": same_squad,
            "can_partial": working and is_adjacent,
            "year_ordered_in": y_oi,
            "year_turned_down": y_td,
            "year_volunteered": stats.get("volunteered", 0),
            "max_turn_downs_year": max_td,
            "max_ordered_in_year": max_oi,
            "blocked_turn_downs_cap": blocked_turn_downs,
            "blocked_ordered_in_cap": blocked_ordered_in,
            "ineligible_for_order": ineligible,
            "call_list_position": None,
        }
        if ineligible:
            # Still listed at end with flag (supervisor visibility) — not offerable for order-in
            row["fill_hint"] = "At yearly max turn-downs" if blocked_turn_downs else "At yearly max ordered-in"
        if working:
            on_duty.append(row)
        else:
            off_duty.append(row)

    # Fatigue soft scores (tie-break only — mode / CBA order stays primary)
    fatigue_by_id: Dict[int, float] = {}
    thr = 70.0
    _compute_fatigue = None
    try:
        from logic.labor_compliance import compute_fatigue_score as _compute_fatigue
        from logic.labor_compliance import get_fatigue_score_threshold

        thr = float(get_fatigue_score_threshold())
    except Exception:
        _compute_fatigue = None
    if _compute_fatigue is not None:
        for row in on_duty + off_duty:
            oid = int(row["officer_id"])
            try:
                fs = _compute_fatigue(oid) or {}
                fatigue_by_id[oid] = float(fs.get("score") or 0)
            except Exception:
                fatigue_by_id[oid] = 0.0
    for row in on_duty + off_duty:
        fs = float(fatigue_by_id.get(int(row["officer_id"]), 0.0))
        row["fatigue_score"] = round(fs, 1)
        row["fatigue_elevated"] = fs >= thr

    # Annotate call list order
    from logic.bump_off_duty import get_bump_call_list, get_call_list_cursor

    call_list = get_bump_call_list()
    if call_list:
        cursor = get_call_list_cursor() % len(call_list)
        pos_map = {}
        for i, e in enumerate(call_list):
            # distance from next-up (0 = next)
            dist = (i - cursor) % len(call_list)
            pos_map[int(e["officer_id"])] = dist
        for row in on_duty + off_duty:
            row["call_list_position"] = pos_map.get(row["officer_id"])

    def by_seniority(rows: List[Dict]) -> List[Dict]:
        # Seniority primary; lower fatigue preferred as LE wellness tie-break
        return sorted(
            rows,
            key=lambda r: (
                int(r.get("seniority_rank") or 9999),
                float(r.get("fatigue_score") or 0),
                r["officer_id"],
            ),
        )

    def by_call_list(rows: List[Dict]) -> List[Dict]:
        return sorted(
            rows,
            key=lambda r: (
                r["call_list_position"] if r.get("call_list_position") is not None else 999,
                float(r.get("fatigue_score") or 0),
                int(r.get("seniority_rank") or 9999),
            ),
        )

    if mode == FILL_MODE_SENIORITY_ONLY:
        ranked = by_seniority(on_duty + off_duty)
    elif mode == FILL_MODE_ON_DUTY_PARTIAL_FIRST:
        # Adjacent on-duty first; fatigue tie-break within each band bucket
        adj_on = by_seniority([r for r in on_duty if r.get("adjacent_band")])
        other_on = by_seniority([r for r in on_duty if not r.get("adjacent_band")])
        ranked = adj_on + other_on + by_call_list(off_duty)
    elif mode == FILL_MODE_ON_DUTY_PARTIAL_BY_SENIORITY:
        adj_on = by_seniority([r for r in on_duty if r.get("adjacent_band")])
        other_on = by_seniority([r for r in on_duty if not r.get("adjacent_band")])
        ranked = adj_on + other_on + by_seniority(off_duty)
    elif mode == FILL_MODE_OFF_DUTY_FIRST:
        ranked = by_call_list(off_duty) + by_seniority(on_duty)
    else:
        ranked = by_seniority(on_duty + off_duty)

    # Eligible first (not at yearly caps), ineligible last for audit visibility
    eligible = [r for r in ranked if not r.get("ineligible_for_order")]
    ineligible = [r for r in ranked if r.get("ineligible_for_order")]
    ranked = eligible + ineligible

    for i, r in enumerate(ranked, 1):
        r["offer_order"] = i
        if r.get("ineligible_for_order"):
            continue
        if r.get("on_duty") and r.get("adjacent_band"):
            base = "On-duty · can take partial or whole shift (adjacent band)"
        elif r.get("on_duty"):
            base = "On-duty · other band (may require order-in / OT)"
        else:
            base = "Off-duty · call-in / OT"
        if r.get("fatigue_elevated"):
            r["fill_hint"] = f"{base} · elevated fatigue ({r.get('fatigue_score')})"
        else:
            r["fill_hint"] = base

    return {
        "success": True,
        "mode": mode,
        "mode_label": FILL_MODE_LABELS.get(mode, mode),
        "request_date": storage_date_str(request_date),
        "covered_shift_start": shift_start,
        "squad": squad,
        "original_officer_id": original_officer_id,
        "original_officer_name": original.get("name"),
        "candidates": ranked,
        "eligible_count": len(eligible),
        "ineligible_count": len(ineligible),
        "count": len(ranked),
        "year": year,
    }


def record_ot_fill_event(
    officer_id: int,
    event_date: str,
    event_type: str,
    *,
    fill_mode: Optional[str] = None,
    request_id: Optional[int] = None,
    hours: float = 0.0,
    is_partial: bool = False,
    is_ordered: bool = False,
    covered_shift_start: Optional[str] = None,
    notes: str = "",
    user_id: Optional[int] = None,
    update_call_list: bool = True,
) -> Dict:
    """Record ordered-in / turned-down / volunteered / partial; update call list if ordered."""
    from logic.officers import get_officer_by_id

    officer = get_officer_by_id(officer_id)
    if not officer:
        return {"success": False, "message": "Officer not found"}
    try:
        d = parse_date(event_date)
        event_date = storage_date_str(event_date)
    except ValueError as exc:
        return {"success": False, "message": str(exc)}

    event_type = (event_type or "").strip()
    allowed = {EVENT_ORDERED_IN, EVENT_TURNED_DOWN, EVENT_VOLUNTEERED, EVENT_PARTIAL_COVER}
    if event_type not in allowed:
        return {"success": False, "message": f"event_type must be one of {sorted(allowed)}"}

    if event_type == EVENT_ORDERED_IN:
        is_ordered = True
    if event_type == EVENT_PARTIAL_COVER and not is_ordered:
        is_ordered = False

    year = d.year
    # Enforce yearly max ordered-in / turn-downs when recording order-in
    if event_type == EVENT_ORDERED_IN:
        from logic.roster_titles import resolve_officer_callin_limits

        limits = resolve_officer_callin_limits(officer)
        stats = get_officer_ot_fill_year_stats(officer_id, year)
        max_oi = limits.get("max_ordered_in_year")
        max_td = limits.get("max_turn_downs_year")
        if max_oi is not None and int(stats.get("ordered_in") or 0) >= max_oi:
            return {
                "success": False,
                "message": (
                    f"{officer['name']} has reached max ordered-in for {year} ({stats.get('ordered_in')}/{max_oi})"
                ),
                "year_stats": stats,
            }
        if max_td is not None and int(stats.get("turned_down") or 0) >= max_td:
            return {
                "success": False,
                "message": (
                    f"{officer['name']} has reached max turn-downs for {year} "
                    f"({stats.get('turned_down')}/{max_td}) — not eligible for order-in"
                ),
                "year_stats": stats,
            }

    with connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO ot_fill_events
                (officer_id, event_year, event_date, event_type, fill_mode, request_id,
                 hours, is_partial, is_ordered, covered_shift_start, notes, created_by_user_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    officer_id,
                    year,
                    event_date,
                    event_type,
                    fill_mode or get_ot_fill_mode(),
                    request_id,
                    float(hours or 0),
                    1 if is_partial else 0,
                    1 if is_ordered else 0,
                    covered_shift_start,
                    notes or None,
                    user_id,
                ),
            )
            eid = cursor.lastrowid
            conn.commit()
        except Exception as exc:
            conn.rollback()
            return {"success": False, "message": str(exc)}

    call_list_msg = ""
    if update_call_list and event_type == EVENT_ORDERED_IN:
        moved = move_officer_to_end_of_call_list(officer_id, user_id=user_id)
        if moved.get("success"):
            call_list_msg = f"; {moved.get('message', 'call list updated')}"

    # Mirror ordered/volunteer hours into legacy callback_events when hours > 0
    if event_type in (EVENT_ORDERED_IN, EVENT_VOLUNTEERED, EVENT_PARTIAL_COVER) and hours and hours > 0:
        try:
            from logic.callbacks import record_callback_event

            record_callback_event(
                officer_id,
                event_date,
                float(hours),
                notes=f"ot_fill:{event_type} {notes or ''}".strip(),
                user_id=user_id,
            )
        except Exception:
            pass

    log_audit_action(
        f"ot_fill.{event_type}",
        "ot_fill_event",
        eid,
        user_id,
        f"{officer['name']} {event_date} partial={is_partial} ordered={is_ordered}",
    )
    stats = get_officer_ot_fill_year_stats(officer_id, year)
    return {
        "success": True,
        "event_id": eid,
        "message": f"Recorded {event_type} for {officer['name']}{call_list_msg}",
        "year_stats": stats,
    }


def record_turned_down(
    officer_id: int,
    event_date: str,
    *,
    request_id: Optional[int] = None,
    notes: str = "",
    user_id: Optional[int] = None,
    fill_mode: Optional[str] = None,
) -> Dict:
    return record_ot_fill_event(
        officer_id,
        event_date,
        EVENT_TURNED_DOWN,
        request_id=request_id,
        notes=notes,
        user_id=user_id,
        fill_mode=fill_mode,
        update_call_list=False,
    )


def record_ordered_in(
    officer_id: int,
    event_date: str,
    *,
    request_id: Optional[int] = None,
    hours: float = 0.0,
    is_partial: bool = False,
    covered_shift_start: Optional[str] = None,
    notes: str = "",
    user_id: Optional[int] = None,
    fill_mode: Optional[str] = None,
) -> Dict:
    return record_ot_fill_event(
        officer_id,
        event_date,
        EVENT_ORDERED_IN,
        request_id=request_id,
        hours=hours,
        is_partial=is_partial,
        is_ordered=True,
        covered_shift_start=covered_shift_start,
        notes=notes,
        user_id=user_id,
        fill_mode=fill_mode,
        update_call_list=True,
    )


def move_officer_to_end_of_call_list(officer_id: int, *, user_id: Optional[int] = None) -> Dict:
    """After order-in: officer becomes furthest from next call (end of list, cursor → top)."""
    from logic.bump_off_duty import get_bump_call_list, reset_call_list_cursor, save_bump_call_list

    entries = get_bump_call_list()
    if not entries:
        # Also try callback_rotation table
        return _move_callback_rotation_to_end(officer_id, user_id=user_id)

    oid = int(officer_id)
    found = [e for e in entries if int(e["officer_id"]) == oid]
    rest = [e for e in entries if int(e["officer_id"]) != oid]
    if not found:
        # Not on list — append then they are at end
        rest.append({"officer_id": oid, "name": "", "note": "added after order-in", "order": len(rest)})
        new_list = rest
    else:
        new_list = rest + found
    r = save_bump_call_list(new_list, user_id=user_id)
    if not r.get("success"):
        return r
    reset_call_list_cursor(user_id=user_id)
    # Keep callback_rotation in sync when present
    _move_callback_rotation_to_end(officer_id, user_id=user_id)
    return {
        "success": True,
        "message": f"Officer {oid} moved to end of call list (furthest from next call)",
        "entries": r.get("entries"),
    }


def _move_callback_rotation_to_end(officer_id: int, *, user_id: Optional[int] = None) -> Dict:
    with connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT officer_id, sort_order FROM callback_rotation WHERE active = 1 ORDER BY sort_order ASC"
            )
            rows = cursor.fetchall()
            if not rows:
                return {"success": True, "message": "No callback_rotation rows"}
            ids = [int(r["officer_id"]) for r in rows]
            if officer_id not in ids:
                cursor.execute("SELECT MAX(sort_order) FROM callback_rotation")
                mx = cursor.fetchone()[0] or 0
                cursor.execute(
                    "INSERT INTO callback_rotation (officer_id, sort_order, active) VALUES (?, ?, 1)",
                    (officer_id, mx + 1),
                )
            else:
                ids = [i for i in ids if i != officer_id] + [officer_id]
                for order, oid in enumerate(ids):
                    cursor.execute(
                        "UPDATE callback_rotation SET sort_order = ?, updated_at = CURRENT_TIMESTAMP WHERE officer_id = ?",
                        (order, oid),
                    )
            conn.commit()
            return {"success": True, "message": "callback_rotation updated"}
        except Exception as exc:
            conn.rollback()
            return {"success": False, "message": str(exc)}


def get_officer_ot_fill_year_stats(officer_id: int, year: Optional[int] = None) -> Dict:
    if year is None:
        year = date.today().year
    with connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT event_type, COUNT(*) AS n,
                   SUM(CASE WHEN is_ordered = 1 THEN 1 ELSE 0 END) AS ordered_flags
            FROM ot_fill_events
            WHERE officer_id = ? AND event_year = ?
            GROUP BY event_type
            """,
            (officer_id, year),
        )
        by_type = {r["event_type"]: int(r["n"]) for r in cursor.fetchall()}
    return {
        "officer_id": officer_id,
        "year": year,
        "ordered_in": by_type.get(EVENT_ORDERED_IN, 0),
        "turned_down": by_type.get(EVENT_TURNED_DOWN, 0),
        "volunteered": by_type.get(EVENT_VOLUNTEERED, 0),
        "partial_cover": by_type.get(EVENT_PARTIAL_COVER, 0),
        "by_type": by_type,
    }


def get_ot_fill_year_leaderboard(year: Optional[int] = None, *, limit: int = 50) -> Dict:
    if year is None:
        year = date.today().year
    with connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT e.officer_id, o.name,
                   SUM(CASE WHEN e.event_type = 'ordered_in' THEN 1 ELSE 0 END) AS ordered_in,
                   SUM(CASE WHEN e.event_type = 'turned_down' THEN 1 ELSE 0 END) AS turned_down,
                   SUM(CASE WHEN e.event_type = 'volunteered' THEN 1 ELSE 0 END) AS volunteered
            FROM ot_fill_events e
            JOIN officers o ON o.id = e.officer_id
            WHERE e.event_year = ?
            GROUP BY e.officer_id
            ORDER BY ordered_in DESC, turned_down DESC
            LIMIT ?
            """,
            (year, limit),
        )
        rows = [dict(r) for r in cursor.fetchall()]
    return {"success": True, "year": year, "rows": rows}


def apply_ot_fill_selection(
    request_id: int,
    cover_officer_id: int,
    *,
    response: str = EVENT_ORDERED_IN,
    is_partial: bool = False,
    hours: float = 0.0,
    turned_down_ids: Optional[Sequence[int]] = None,
    actor_user_id: Optional[int] = None,
    admin_notes: str = "",
) -> Dict:
    """
    Record turn-downs, record cover response, approve day-off with preferred chain
    cover_officer → original.
    """
    from logic.officers import get_officer_by_id
    from logic.requests import process_day_off_request

    with connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT r.*, o.squad, o.shift_start, o.shift_end, o.name AS officer_name
            FROM day_off_requests r
            JOIN officers o ON o.id = r.officer_id
            WHERE r.id = ?
            """,
            (request_id,),
        )
        row = cursor.fetchone()
    if not row:
        return {"success": False, "message": "Request not found"}
    request = dict(row)
    cover = get_officer_by_id(cover_officer_id)
    if not cover:
        return {"success": False, "message": "Cover officer not found"}

    event_date = storage_date_str(request["request_date"])
    mode = get_ot_fill_mode()

    for tid in turned_down_ids or []:
        record_turned_down(
            int(tid),
            event_date,
            request_id=request_id,
            user_id=actor_user_id,
            fill_mode=mode,
            notes="Turned down OT / fill offer",
        )

    resp = (response or EVENT_ORDERED_IN).strip()
    if resp == EVENT_TURNED_DOWN:
        return record_turned_down(
            cover_officer_id,
            event_date,
            request_id=request_id,
            user_id=actor_user_id,
            fill_mode=mode,
        )

    if resp == EVENT_ORDERED_IN:
        record_ordered_in(
            cover_officer_id,
            event_date,
            request_id=request_id,
            hours=hours,
            is_partial=is_partial,
            covered_shift_start=request.get("shift_start"),
            user_id=actor_user_id,
            fill_mode=mode,
        )
    elif resp == EVENT_VOLUNTEERED:
        record_ot_fill_event(
            cover_officer_id,
            event_date,
            EVENT_VOLUNTEERED,
            request_id=request_id,
            hours=hours,
            is_partial=is_partial,
            covered_shift_start=request.get("shift_start"),
            user_id=actor_user_id,
            fill_mode=mode,
            update_call_list=False,
        )
    elif resp == EVENT_PARTIAL_COVER:
        record_ot_fill_event(
            cover_officer_id,
            event_date,
            EVENT_PARTIAL_COVER,
            request_id=request_id,
            hours=hours,
            is_partial=True,
            is_ordered=False,
            covered_shift_start=request.get("shift_start"),
            user_id=actor_user_id,
            fill_mode=mode,
            update_call_list=False,
        )

    chain = [(int(request["officer_id"]), int(cover_officer_id))]
    result = process_day_off_request(
        request_id,
        action="approve",
        admin_notes=admin_notes or f"OT fill: {resp} by {cover.get('name')}",
        actor_user_id=actor_user_id,
        preferred_chain=chain,
    )
    return {
        "success": getattr(result, "success", False),
        "message": getattr(result, "message", str(result)),
        "requires_manual": getattr(result, "requires_manual", False),
        "status": getattr(result, "status", ""),
        "cover_officer_id": cover_officer_id,
        "response": resp,
        "year_stats": get_officer_ot_fill_year_stats(cover_officer_id, parse_date(event_date).year),
    }
