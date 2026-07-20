"""Shift bidding — supervisors publish bid events; officers rank preferences; seniority resolves conflicts."""

from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

from database import connection
from logic.officers import get_officer_by_id, get_officers_by_seniority
from logic.rotation_preview import (
    award_schedule_dates,
    parse_bid_rotation_pattern,
    serialize_rotation_pattern,
    shift_start_for_option,
    shift_start_times_list,
)
from logic.users import log_audit_action
from validators import (
    can_officer_work_day_band,
    normalize_optional_text,
    parse_bids_due_datetime,
    parse_date,
    storage_date_str,
)

SHIFT_BID_AWARD_REASON = "Shift Bid Award"
_EVENT_FIELDS = (
    "title",
    "number_of_shifts",
    "shift_length",
    "rotation",
    "shift_start_times",
    "shifts_begin",
    "bids_due_by",
    "squad",
    "notes",
)


def _parse_option_count(text: Optional[str]) -> int:
    if not text:
        return 1
    try:
        return max(1, min(int(str(text).strip()), 50))
    except (ValueError, TypeError):
        return 1


def _first_start_time(text: Optional[str]) -> Optional[str]:
    times = shift_start_times_list(text)
    return times[0] if times else None


def _normalize_squad(value: Optional[str]) -> Optional[str]:
    if not value or str(value).strip().lower() in ("all", "", "any"):
        return None
    squad = str(value).strip().upper()
    if squad in ("A", "B"):
        return squad
    return None


def _event_visible_to_officer(event: Dict, officer: Dict) -> bool:
    squad = event.get("squad")
    if squad and officer.get("squad") != squad:
        return False
    return True


def _is_bidding_closed(event: Dict) -> bool:
    if event.get("bids_closed_at"):
        return True
    due_dt = parse_bids_due_datetime(event.get("bids_due_by"))
    if not due_dt:
        return False
    return due_dt < datetime.now()


def auto_close_expired_shift_bid_events() -> int:
    """Stamp bids_closed_at on open events past deadline (idempotent)."""
    with connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM shift_bid_events WHERE status = 'open' AND bids_closed_at IS NULL")
        rows = [dict(r) for r in cursor.fetchall()]
        closed = 0
        now = datetime.now().isoformat(timespec="seconds")
        for event in rows:
            if not _is_bidding_closed(event):
                continue
            cursor.execute(
                "UPDATE shift_bid_events SET bids_closed_at = ? WHERE id = ? AND bids_closed_at IS NULL",
                (now, event["id"]),
            )
            if cursor.rowcount:
                closed += 1
        if closed:
            conn.commit()
    return closed


def _load_event_options(cursor, event_id: int) -> List[Dict]:
    cursor.execute(
        """
        SELECT o.*, off.name AS awarded_officer_name
        FROM shift_bid_options o
        LEFT JOIN officers off ON o.awarded_officer_id = off.id
        WHERE o.event_id = ?
        ORDER BY o.option_number
        """,
        (event_id,),
    )
    return [dict(r) for r in cursor.fetchall()]


def get_shift_bid_event(event_id: int, *, officer_id: Optional[int] = None) -> Optional[Dict]:
    with connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM shift_bid_events WHERE id = ?", (event_id,))
        row = cursor.fetchone()
        if not row:
            return None
        event = dict(row)
        event["options"] = _load_event_options(cursor, event_id)
        if officer_id is not None:
            cursor.execute(
                """
                SELECT option_id, preference_rank
                FROM shift_bid_rankings
                WHERE event_id = ? AND officer_id = ?
                ORDER BY preference_rank
                """,
                (event_id, officer_id),
            )
            event["my_rankings"] = [dict(r) for r in cursor.fetchall()]
            event["has_submitted"] = bool(event["my_rankings"])
        cursor.execute(
            """
            SELECT COUNT(DISTINCT officer_id) AS respondent_count
            FROM shift_bid_rankings WHERE event_id = ?
            """,
            (event_id,),
        )
        event["respondent_count"] = cursor.fetchone()["respondent_count"]
    return event


def get_shift_bid_events(
    *,
    status: Optional[str] = None,
    officer_id: Optional[int] = None,
    include_drafts: bool = False,
    limit: int = 20,
) -> List[Dict]:
    auto_close_expired_shift_bid_events()
    with connection() as conn:
        cursor = conn.cursor()
        clauses = []
        params: List = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        elif not include_drafts:
            clauses.append("status != 'draft'")
        if officer_id is not None:
            officer = get_officer_by_id(officer_id)
            if officer:
                clauses.append("(squad IS NULL OR squad = ?)")
                params.append(officer.get("squad"))
            clauses.append("status = 'open'")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        cursor.execute(
            f"""
            SELECT e.*,
                   (SELECT COUNT(*) FROM shift_bid_options o WHERE o.event_id = e.id) AS option_count,
                   (SELECT COUNT(DISTINCT r.officer_id) FROM shift_bid_rankings r WHERE r.event_id = e.id) AS respondent_count
            FROM shift_bid_events e
            {where}
            ORDER BY e.created_at DESC
            LIMIT ?
            """,
            (*params, limit),
        )
        rows = [dict(r) for r in cursor.fetchall()]
    if officer_id is not None:
        officer = get_officer_by_id(officer_id)
        if officer:
            rows = [r for r in rows if _event_visible_to_officer(r, officer) and not _is_bidding_closed(r)]
    return rows


def officer_has_active_shift_bid(officer_id: Optional[int] = None) -> bool:
    return bool(get_shift_bid_events(officer_id=officer_id))


def create_shift_bid_event(
    *,
    title: str = "",
    number_of_shifts: str = "",
    shift_length: str = "",
    rotation: str = "",
    shift_start_times: str = "",
    shifts_begin: str = "",
    bids_due_by: str = "",
    squad: Optional[str] = None,
    notes: str = "",
    user_id: Optional[int] = None,
) -> Dict:
    with connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO shift_bid_events (
                    title, number_of_shifts, shift_length, rotation, shift_start_times,
                    shifts_begin, bids_due_by, squad, notes, created_by_user_id, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft')
                """,
                (
                    normalize_optional_text(title) or "Shift Bid",
                    normalize_optional_text(number_of_shifts),
                    normalize_optional_text(shift_length),
                    normalize_optional_text(rotation),
                    normalize_optional_text(shift_start_times),
                    normalize_optional_text(shifts_begin),
                    normalize_optional_text(bids_due_by),
                    _normalize_squad(squad),
                    normalize_optional_text(notes),
                    user_id,
                ),
            )
            event_id = cursor.lastrowid
            conn.commit()
            log_audit_action("shift_bid.create_event", "shift_bid_event", event_id, user_id, title or "")
            return {"success": True, "event_id": event_id}
        except Exception as exc:
            conn.rollback()
            return {"success": False, "message": str(exc)}


def build_shift_bid_payload_from_simulation(sim_result: Dict, **overrides) -> Dict:
    """Map schedule simulator output to shift bid event fields."""
    if not sim_result or not sim_result.get("success"):
        return {"success": False, "message": "Run a schedule simulation first"}

    config = sim_result.get("simulation_config") or {}
    templates = sim_result.get("shift_templates") or []
    metrics = sim_result.get("metrics") or {}

    shift_starts: List[str] = []
    for start, _end in templates:
        if start and start not in shift_starts:
            shift_starts.append(start)
    if not shift_starts:
        for slot in sim_result.get("officer_slots") or []:
            start = slot.get("shift_start")
            if start and start not in shift_starts:
                shift_starts.append(start)

    num_shifts = len(shift_starts) or len(templates) or 1
    hours = config.get("shift_length_hours")
    shift_length = f"{hours:g} hours" if hours else ""
    rotation = config.get("rotation_type") or ""

    shifts_begin = overrides.get("shifts_begin") or sim_result.get("simulation_start_date") or ""
    if not shifts_begin:
        coverage = sim_result.get("coverage_by_day") or []
        if coverage:
            shifts_begin = coverage[0].get("date") or ""

    note_bits = [
        "Imported from schedule simulator.",
        f"Coverage {metrics.get('coverage_percent', 0)}%",
        f"FTE est. {metrics.get('fte_required', '—')}",
        f"{config.get('num_officers', '—')} officers modeled",
    ]
    default_notes = "  ·  ".join(str(x) for x in note_bits if x)

    return {
        "success": True,
        "title": overrides.get("title") or f"Shift Bid — {rotation or 'Simulator'}",
        "number_of_shifts": str(num_shifts),
        "shift_length": shift_length,
        "rotation": rotation,
        "shift_start_times": ", ".join(shift_starts),
        "shifts_begin": shifts_begin,
        "bids_due_by": overrides.get("bids_due_by") or "",
        "squad": overrides.get("squad"),
        "notes": overrides.get("notes") or default_notes,
    }


def create_shift_bid_from_simulation(
    sim_result: Dict,
    *,
    publish: bool = False,
    user_id: Optional[int] = None,
    **overrides,
) -> Dict:
    """Create a draft shift bid (optionally publish) from simulator results."""
    payload = build_shift_bid_payload_from_simulation(sim_result, **overrides)
    if not payload.get("success"):
        return payload

    squad = payload.pop("squad", None)
    result = create_shift_bid_event(
        title=payload.get("title", ""),
        number_of_shifts=payload.get("number_of_shifts", ""),
        shift_length=payload.get("shift_length", ""),
        rotation=payload.get("rotation", ""),
        shift_start_times=payload.get("shift_start_times", ""),
        shifts_begin=payload.get("shifts_begin", ""),
        bids_due_by=payload.get("bids_due_by", ""),
        squad=squad,
        notes=payload.get("notes", ""),
        user_id=user_id,
    )
    if not result.get("success"):
        return result

    event_id = result["event_id"]
    scenario_id = sim_result.get("scenario_id")
    if scenario_id:
        with connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE shift_bid_events SET simulation_id = ? WHERE id = ?",
                (scenario_id, event_id),
            )
            conn.commit()
    log_audit_action("shift_bid.import_sim", "shift_bid_event", event_id, user_id, payload.get("title", ""))

    if publish:
        pub = publish_shift_bid_event(event_id, user_id=user_id)
        if not pub.get("success"):
            return {
                "success": False,
                "message": f"Draft created (ID {event_id}) but publish failed: {pub.get('message')}",
                "event_id": event_id,
            }
        result["published"] = True
        result["option_count"] = pub.get("option_count", 0)

    result["imported_from_simulator"] = True
    return result


def update_shift_bid_event(event_id: int, **fields) -> Dict:
    event = get_shift_bid_event(event_id)
    if not event:
        return {"success": False, "message": "Bid event not found"}
    if event["status"] != "draft":
        return {"success": False, "message": "Only draft events can be edited"}

    updates = []
    values = []
    for key in _EVENT_FIELDS:
        if key not in fields:
            continue
        value = fields[key]
        if key == "squad":
            value = _normalize_squad(value)
        else:
            value = (
                normalize_optional_text(value) if key != "title" else (normalize_optional_text(value) or "Shift Bid")
            )
        updates.append(f"{key} = ?")
        values.append(value)
    if not updates:
        return {"success": True}

    with connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                f"UPDATE shift_bid_events SET {', '.join(updates)} WHERE id = ? AND status = 'draft'",
                (*values, event_id),
            )
            if cursor.rowcount == 0:
                return {"success": False, "message": "Bid event not found or not editable"}
            conn.commit()
            return {"success": True}
        except Exception as exc:
            conn.rollback()
            return {"success": False, "message": str(exc)}


def _option_label_for(event: Dict, option_number: int, shift_start: Optional[str]) -> str:
    rotation = (event.get("rotation") or "").strip()
    if shift_start and rotation:
        return f"{shift_start} — {rotation} (slot {option_number})"
    if shift_start:
        return f"{shift_start} shift"
    return f"Shift {option_number}"


def _create_event_options(cursor, event_id: int, event: Dict, count: int) -> None:
    times = shift_start_times_list(event.get("shift_start_times"))
    shift_date = _event_shift_date(event)
    cursor.execute("DELETE FROM shift_bid_options WHERE event_id = ?", (event_id,))
    for num in range(1, count + 1):
        shift_start = times[(num - 1) % len(times)] if times else None
        label = _option_label_for(event, num, shift_start)
        cursor.execute(
            """
            INSERT INTO shift_bid_options (event_id, option_number, label, shift_start, shift_date, status)
            VALUES (?, ?, ?, ?, ?, 'open')
            """,
            (event_id, num, label, shift_start, shift_date),
        )


def publish_shift_bid_event(event_id: int, *, user_id: Optional[int] = None) -> Dict:
    from logic.requests import _notify_shift_bid_event_published

    with connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT * FROM shift_bid_events WHERE id = ? AND status = 'draft'", (event_id,))
            row = cursor.fetchone()
            if not row:
                return {"success": False, "message": "Draft bid event not found"}
            event = dict(row)
            count = _parse_option_count(event.get("number_of_shifts"))
            pattern = parse_bid_rotation_pattern(event.get("rotation"))
            times = shift_start_times_list(event.get("shift_start_times"))
            rotation_json = serialize_rotation_pattern(pattern, shift_starts=times or None)
            _create_event_options(cursor, event_id, event, count)
            cursor.execute(
                """
                UPDATE shift_bid_events
                SET status = 'open', published_at = CURRENT_TIMESTAMP, rotation_json = ?
                WHERE id = ?
                """,
                (rotation_json, event_id),
            )
            conn.commit()
            _notify_shift_bid_event_published(event_id, event)
            log_audit_action("shift_bid.publish", "shift_bid_event", event_id, user_id, event.get("title") or "")
            return {"success": True, "option_count": count}
        except Exception as exc:
            conn.rollback()
            return {"success": False, "message": str(exc)}


def submit_shift_bid_rankings(
    event_id: int,
    officer_id: int,
    rankings: List[Dict],
    *,
    user_id: Optional[int] = None,
) -> Dict:
    officer = get_officer_by_id(officer_id)
    if not officer or officer.get("active") != 1:
        return {"success": False, "message": "Officer not found or inactive"}

    with connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT * FROM shift_bid_events WHERE id = ? AND status = 'open'", (event_id,))
            event_row = cursor.fetchone()
            if not event_row:
                return {"success": False, "message": "Bid event not open"}
            event = dict(event_row)
            if not _event_visible_to_officer(event, officer):
                return {"success": False, "message": "This bid event is not for your squad"}
            if _is_bidding_closed(event):
                return {"success": False, "message": "Bidding deadline has passed"}

            options = _load_event_options(cursor, event_id)
            option_ids = {o["id"] for o in options}
            cleaned: List[Tuple[int, int]] = []
            seen_ranks = set()
            seen_options = set()
            for entry in rankings:
                option_id = entry.get("option_id")
                rank = entry.get("preference_rank") or entry.get("rank")
                if option_id is None or rank is None:
                    continue
                try:
                    option_id = int(option_id)
                    rank = int(rank)
                except (TypeError, ValueError):
                    return {"success": False, "message": "Invalid ranking entry"}
                if option_id not in option_ids:
                    return {"success": False, "message": "Unknown shift option"}
                if rank < 1 or rank > len(options):
                    return {"success": False, "message": f"Rank must be between 1 and {len(options)}"}
                if rank in seen_ranks or option_id in seen_options:
                    return {"success": False, "message": "Each shift and rank can only be used once"}
                seen_ranks.add(rank)
                seen_options.add(option_id)
                cleaned.append((option_id, rank))
            if not cleaned:
                return {"success": False, "message": "Rank at least one shift preference"}

            check_date = _event_shift_date(event) or date.today().isoformat()
            option_by_id = {o["id"]: o for o in options}
            for option_id, _rank in cleaned:
                option = option_by_id.get(option_id)
                if not option:
                    continue
                shift_start = shift_start_for_option(event, option)
                if not shift_start:
                    continue
                eligibility = can_officer_work_day_band(officer_id, check_date, shift_start)
                if not eligibility.ok:
                    label = option.get("label") or f"Shift {option.get('option_number')}"
                    return {
                        "success": False,
                        "message": f"Cannot rank {label}: {eligibility.message}",
                    }

            cursor.execute(
                "DELETE FROM shift_bid_rankings WHERE event_id = ? AND officer_id = ?", (event_id, officer_id)
            )
            for option_id, rank in cleaned:
                cursor.execute(
                    """
                    INSERT INTO shift_bid_rankings (event_id, officer_id, option_id, preference_rank)
                    VALUES (?, ?, ?, ?)
                    """,
                    (event_id, officer_id, option_id, rank),
                )
            conn.commit()
            log_audit_action("shift_bid.submit_rankings", "shift_bid_event", event_id, user_id, f"officer={officer_id}")
            return {"success": True, "ranked_count": len(cleaned)}
        except Exception as exc:
            conn.rollback()
            return {"success": False, "message": str(exc)}


def get_shift_bid_rankings_for_event(event_id: int) -> List[Dict]:
    with connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT r.*, o.name AS officer_name, o.seniority_rank, o.squad,
                   opt.label AS option_label, opt.option_number
            FROM shift_bid_rankings r
            JOIN officers o ON r.officer_id = o.id
            JOIN shift_bid_options opt ON r.option_id = opt.id
            WHERE r.event_id = ?
            ORDER BY o.seniority_rank ASC, r.preference_rank ASC
            """,
            (event_id,),
        )
        rows = [dict(r) for r in cursor.fetchall()]
    return rows


def format_bid_event_summary(event_id: int) -> str:
    event = get_shift_bid_event(event_id)
    if not event:
        return "Bid event not found."
    lines = [
        event.get("title") or "Shift Bid",
        f"Shifts: {event.get('number_of_shifts') or '—'}  ·  Length: {event.get('shift_length') or '—'}",
        f"Rotation: {event.get('rotation') or '—'}",
        f"Start times: {event.get('shift_start_times') or '—'}",
        f"Shifts begin: {event.get('shifts_begin') or '—'}",
        f"Bids due by: {event.get('bids_due_by') or '—'}",
        f"Options: {len(event.get('options', []))}  ·  Responses: {event.get('respondent_count', 0)}",
    ]
    return "\n".join(lines)


def preview_shift_bid_awards(event_id: int) -> Dict:
    """Dry-run seniority awards without persisting."""
    event = get_shift_bid_event(event_id)
    if not event:
        return {"success": False, "message": "Bid event not found"}
    if event.get("status") not in ("open", "finalized"):
        return {"success": False, "message": "Preview requires an open or finalized event"}
    awards = _resolve_awards_by_seniority(event_id)
    unassigned = [opt for opt in event.get("options", []) if opt["id"] not in {a["option_id"] for a in awards}]
    return {
        "success": True,
        "event_id": event_id,
        "awards": awards,
        "award_count": len(awards),
        "unassigned_options": [{"option_id": o["id"], "label": o.get("label")} for o in unassigned],
    }


def get_shift_bid_participation_report(event_id: int) -> Dict:
    event = get_shift_bid_event(event_id)
    if not event:
        return {"success": False, "message": "Bid event not found"}
    eligible = _eligible_officers_for_event(event)
    rankings = get_shift_bid_rankings_for_event(event_id)
    respondents = {r["officer_id"] for r in rankings}
    missing = [o for o in eligible if o["id"] not in respondents]
    return {
        "success": True,
        "event_id": event_id,
        "title": event.get("title"),
        "status": event.get("status"),
        "eligible_count": len(eligible),
        "respondent_count": len(respondents),
        "missing_officers": [{"officer_id": o["id"], "name": o["name"]} for o in missing],
        "rankings": rankings,
    }


def get_officer_shift_bid_awards(officer_id: int, *, limit: int = 10) -> List[Dict]:
    with connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT e.id AS event_id, e.title, e.status, e.finalized_at, e.shifts_begin,
                   o.id AS option_id, o.label, o.shift_start, o.shift_date
            FROM shift_bid_options o
            JOIN shift_bid_events e ON o.event_id = e.id
            WHERE o.awarded_officer_id = ? AND e.status = 'finalized'
            ORDER BY e.finalized_at DESC
            LIMIT ?
            """,
            (officer_id, limit),
        )
        rows = [dict(r) for r in cursor.fetchall()]
    return rows


def _resolve_awards_by_seniority(event_id: int) -> List[Dict]:
    rankings = get_shift_bid_rankings_for_event(event_id)
    by_officer: Dict[int, List[Dict]] = {}
    for row in rankings:
        by_officer.setdefault(row["officer_id"], []).append(row)
    officers = []
    for officer_id, prefs in by_officer.items():
        officer = get_officer_by_id(officer_id)
        if not officer:
            continue
        officers.append((officer["seniority_rank"], officer_id, sorted(prefs, key=lambda p: p["preference_rank"])))
    officers.sort(key=lambda item: item[0])

    awarded_options = set()
    awards = []
    for _rank, officer_id, prefs in officers:
        for pref in prefs:
            if pref["option_id"] in awarded_options:
                continue
            awarded_options.add(pref["option_id"])
            awards.append(
                {
                    "option_id": pref["option_id"],
                    "option_label": pref["option_label"],
                    "officer_id": officer_id,
                    "officer_name": pref["officer_name"],
                    "preference_rank": pref["preference_rank"],
                }
            )
            break
    return awards


def _event_shift_date(event: Dict) -> Optional[str]:
    begin = event.get("shifts_begin")
    if not begin:
        return None
    try:
        return storage_date_str(begin)
    except ValueError:
        try:
            return parse_date(begin).isoformat()
        except ValueError:
            return None


def _eligible_officers_for_event(event: Dict) -> List[Dict]:
    officers = [o for o in get_officers_by_seniority() if o.get("active") == 1]
    squad = event.get("squad")
    if squad:
        officers = [o for o in officers if o.get("squad") == squad]
    return officers


def _remove_shift_bid_award_schedule(
    event: Dict,
    officer_id: int,
    user_id: Optional[int],
    *,
    option: Optional[Dict] = None,
) -> Dict:
    from logic.snapshots import apply_live_schedule_for_date

    if option:
        schedule_pairs = award_schedule_dates(event, option, weeks=2)
        dates = [pair[0] for pair in schedule_pairs if pair[0]]
    else:
        shift_date = _event_shift_date(event)
        dates = [shift_date] if shift_date else []

    if not dates:
        return {"success": True, "skipped": True}

    with connection() as conn:
        cursor = conn.cursor()
        try:
            for shift_date in dates:
                cursor.execute(
                    """
                    DELETE FROM schedule_overrides
                    WHERE override_date = ? AND replacement_officer_id = ? AND reason = ?
                    """,
                    (shift_date, officer_id, SHIFT_BID_AWARD_REASON),
                )
            conn.commit()
        except Exception as exc:
            conn.rollback()
            return {"success": False, "message": str(exc)}

    for shift_date in dates:
        result = apply_live_schedule_for_date(shift_date, user_id)
        if not result.get("success"):
            return result
    return {"success": True, "dates_removed": len(dates)}


def _apply_event_award_schedule(
    event: Dict,
    officer_id: int,
    user_id: Optional[int],
    *,
    option: Optional[Dict] = None,
) -> Dict:
    from logic.snapshots import apply_live_schedule_for_date

    if option:
        schedule_pairs = award_schedule_dates(event, option, weeks=2)
    else:
        shift_date = _event_shift_date(event)
        shift_start = _first_start_time(event.get("shift_start_times"))
        schedule_pairs = [(shift_date, shift_start)] if shift_date and shift_start else []

    if not schedule_pairs:
        return {"success": True, "skipped": True}

    applied_dates: List[str] = []
    with connection() as conn:
        cursor = conn.cursor()
        try:
            for shift_date, shift_start in schedule_pairs:
                if not shift_date or not shift_start:
                    continue
                cursor.execute(
                    """
                    SELECT id FROM schedule_overrides
                    WHERE override_date = ? AND replacement_officer_id = ? AND reason = ?
                    """,
                    (shift_date, officer_id, SHIFT_BID_AWARD_REASON),
                )
                if not cursor.fetchone():
                    cursor.execute(
                        """
                        INSERT INTO schedule_overrides
                        (override_date, original_officer_id, replacement_officer_id, reason, covered_shift_start)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (shift_date, officer_id, officer_id, SHIFT_BID_AWARD_REASON, shift_start),
                    )
                applied_dates.append(shift_date)
            conn.commit()
        except Exception as exc:
            conn.rollback()
            return {"success": False, "message": str(exc)}

    for shift_date in applied_dates:
        result = apply_live_schedule_for_date(shift_date, user_id)
        if not result.get("success"):
            return result
    return {"success": True, "dates_applied": len(applied_dates)}


def finalize_shift_bid_event(event_id: int, *, user_id: Optional[int] = None) -> Dict:
    from logic.requests import _notify_shift_bid_event_finalized

    event = None
    awards: List[Dict] = []
    with connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT * FROM shift_bid_events WHERE id = ? AND status = 'open'", (event_id,))
            row = cursor.fetchone()
            if not row:
                return {"success": False, "message": "Open bid event not found"}
            event = dict(row)
            awards = _resolve_awards_by_seniority(event_id)
            awarded_option_ids = {a["option_id"] for a in awards}

            for award in awards:
                cursor.execute(
                    """
                    UPDATE shift_bid_options
                    SET status = 'awarded', awarded_officer_id = ?
                    WHERE id = ?
                    """,
                    (award["officer_id"], award["option_id"]),
                )

            if awarded_option_ids:
                placeholders = ",".join("?" * len(awarded_option_ids))
                cursor.execute(
                    f"""
                    UPDATE shift_bid_options SET status = 'unassigned'
                    WHERE event_id = ? AND id NOT IN ({placeholders})
                    """,
                    (event_id, *awarded_option_ids),
                )
            else:
                cursor.execute(
                    "UPDATE shift_bid_options SET status = 'unassigned' WHERE event_id = ?",
                    (event_id,),
                )

            cursor.execute(
                """
                UPDATE shift_bid_events
                SET status = 'finalized', finalized_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (event_id,),
            )
            conn.commit()
        except Exception as exc:
            conn.rollback()
            return {"success": False, "message": str(exc)}

    options_by_id = {o["id"]: o for o in get_shift_bid_event(event_id).get("options", [])}
    for award in awards:
        option = options_by_id.get(award["option_id"])
        schedule_result = _apply_event_award_schedule(event, award["officer_id"], user_id, option=option)
        if not schedule_result.get("success"):
            return {
                "success": False,
                "message": (
                    f"Awards saved but schedule update failed for {award['officer_name']}: "
                    f"{schedule_result.get('message')}"
                ),
            }
    _notify_shift_bid_event_finalized(event_id, event, awards)
    log_audit_action("shift_bid.finalize", "shift_bid_event", event_id, user_id, f"awards={len(awards)}")
    return {"success": True, "awards": awards, "award_count": len(awards)}


def cancel_shift_bid_event(event_id: int, *, user_id: Optional[int] = None) -> Dict:
    with connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT * FROM shift_bid_events WHERE id = ? AND status IN ('draft', 'open')",
                (event_id,),
            )
            row = cursor.fetchone()
            if not row:
                return {"success": False, "message": "Bid event not found or already closed"}
            event = dict(row)
            cursor.execute(
                "UPDATE shift_bid_events SET status = 'cancelled' WHERE id = ?",
                (event_id,),
            )
            conn.commit()
            if event["status"] == "open":
                from logic.requests import create_notification

                label = event.get("title") or "Shift bid"
                cursor.execute(
                    "SELECT DISTINCT officer_id FROM shift_bid_rankings WHERE event_id = ?",
                    (event_id,),
                )
                for respondent in cursor.fetchall():
                    create_notification(
                        respondent["officer_id"],
                        "Shift Bid",
                        "Bid cancelled",
                        f"Supervisor cancelled {label}",
                        related_id=event_id,
                        related_type="shift_bid_event",
                    )
            log_audit_action("shift_bid.cancel", "shift_bid_event", event_id, user_id, "")
            return {"success": True}
        except Exception as exc:
            conn.rollback()
            return {"success": False, "message": str(exc)}


def update_shift_bid_assignments(
    event_id: int,
    assignments: List[Dict],
    *,
    user_id: Optional[int] = None,
) -> Dict:
    """Supervisor override of finalized awards. Each entry: {option_id, officer_id} (officer_id None = unassign)."""
    from logic.requests import create_notification

    event = None
    changes: List[Dict] = []
    with connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT * FROM shift_bid_events WHERE id = ? AND status = 'finalized'", (event_id,))
            row = cursor.fetchone()
            if not row:
                return {"success": False, "message": "Finalized bid event not found"}
            event = dict(row)

            cursor.execute("SELECT * FROM shift_bid_options WHERE event_id = ?", (event_id,))
            options = {r["id"]: dict(r) for r in cursor.fetchall()}
            if not options:
                return {"success": False, "message": "No shift options on this event"}

            new_map: Dict[int, Optional[int]] = {}
            for entry in assignments:
                option_id = entry.get("option_id")
                officer_id = entry.get("officer_id")
                if option_id not in options:
                    return {"success": False, "message": f"Unknown shift option {option_id}"}
                if officer_id is not None:
                    officer = get_officer_by_id(int(officer_id))
                    if not officer or officer.get("active") != 1:
                        return {"success": False, "message": "Officer not found or inactive"}
                    if not _event_visible_to_officer(event, officer):
                        return {
                            "success": False,
                            "message": f"{officer['name']} is not eligible for this event's squad",
                        }
                    officer_id = int(officer_id)
                new_map[int(option_id)] = officer_id

            if len(new_map) != len(options):
                return {"success": False, "message": "Provide an assignment for every shift option"}

            assigned_officers = [oid for oid in new_map.values() if oid is not None]
            if len(assigned_officers) != len(set(assigned_officers)):
                return {"success": False, "message": "Each officer can only be assigned to one shift"}

            old_officers_set = {
                opt.get("awarded_officer_id") for opt in options.values() if opt.get("awarded_officer_id")
            }
            new_officers_set = {oid for oid in new_map.values() if oid is not None}

            for option_id, new_officer_id in new_map.items():
                option = options[option_id]
                old_officer_id = option.get("awarded_officer_id")
                if old_officer_id == new_officer_id:
                    continue
                if new_officer_id:
                    cursor.execute(
                        """
                        UPDATE shift_bid_options
                        SET awarded_officer_id = NULL, status = 'unassigned'
                        WHERE event_id = ? AND awarded_officer_id = ? AND id != ?
                        """,
                        (event_id, new_officer_id, option_id),
                    )
                if new_officer_id:
                    cursor.execute(
                        """
                        UPDATE shift_bid_options
                        SET status = 'awarded', awarded_officer_id = ?
                        WHERE id = ?
                        """,
                        (new_officer_id, option_id),
                    )
                else:
                    cursor.execute(
                        """
                        UPDATE shift_bid_options
                        SET status = 'unassigned', awarded_officer_id = NULL
                        WHERE id = ?
                        """,
                        (option_id,),
                    )
                changes.append(
                    {
                        "option_id": option_id,
                        "option_label": option.get("label"),
                        "old_officer_id": old_officer_id,
                        "new_officer_id": new_officer_id,
                    }
                )

            officers_needing_schedule_remove = old_officers_set - new_officers_set
            officers_needing_schedule_apply = new_officers_set - old_officers_set
            schedule_removals: List[Tuple[int, Dict]] = []
            schedule_applies: List[Tuple[int, Dict]] = []

            for option_id, new_officer_id in new_map.items():
                option = options[option_id]
                old_officer_id = option.get("awarded_officer_id")
                if old_officer_id == new_officer_id:
                    continue
                if old_officer_id in officers_needing_schedule_remove:
                    schedule_removals.append((old_officer_id, option))
                if new_officer_id in officers_needing_schedule_apply:
                    schedule_applies.append((new_officer_id, option))

            if not changes:
                return {"success": True, "changed": 0, "message": "No changes"}

            conn.commit()
        except Exception as exc:
            conn.rollback()
            return {"success": False, "message": str(exc)}

    seen_remove = set()
    for officer_id, option in schedule_removals:
        key = (officer_id, option["id"])
        if key in seen_remove:
            continue
        seen_remove.add(key)
        result = _remove_shift_bid_award_schedule(event, officer_id, user_id, option=option)
        if not result.get("success"):
            return {
                "success": False,
                "message": f"Assignments saved but schedule cleanup failed: {result.get('message')}",
            }
    seen_apply = set()
    for officer_id, option in schedule_applies:
        key = (officer_id, option["id"])
        if key in seen_apply:
            continue
        seen_apply.add(key)
        result = _apply_event_award_schedule(event, officer_id, user_id, option=option)
        if not result.get("success"):
            return {
                "success": False,
                "message": f"Assignments saved but schedule update failed: {result.get('message')}",
            }

    title = event.get("title") or "Shift bid"
    for change in changes:
        label = change.get("option_label") or "Shift"
        new_id = change.get("new_officer_id")
        old_id = change.get("old_officer_id")
        if new_id:
            create_notification(
                new_id,
                "Shift Bid",
                "Assignment updated",
                f"Supervisor assigned you to {label} in {title}",
                related_id=event_id,
                related_type="shift_bid_event",
            )
        if old_id and old_id != new_id:
            create_notification(
                old_id,
                "Shift Bid",
                "Assignment updated",
                f"Supervisor changed the assignment for {label} in {title}",
                related_id=event_id,
                related_type="shift_bid_event",
            )

    log_audit_action(
        "shift_bid.reassign",
        "shift_bid_event",
        event_id,
        user_id,
        f"changes={len(changes)}",
    )
    return {"success": True, "changed": len(changes), "changes": changes}


def reassign_shift_bid_option(
    event_id: int,
    option_id: int,
    officer_id: Optional[int] = None,
    *,
    user_id: Optional[int] = None,
) -> Dict:
    event = get_shift_bid_event(event_id)
    if not event:
        return {"success": False, "message": "Bid event not found"}
    assignments = [
        {"option_id": opt["id"], "officer_id": opt.get("awarded_officer_id")} for opt in event.get("options", [])
    ]
    for entry in assignments:
        if entry["option_id"] == option_id:
            entry["officer_id"] = officer_id
            break
    else:
        return {"success": False, "message": "Shift option not found"}
    return update_shift_bid_assignments(event_id, assignments, user_id=user_id)


# Backward-compatible aliases for CLI/tests naming
def get_shift_bid_slots(*, status: str = "open", officer_id: Optional[int] = None, limit: int = 50) -> List[Dict]:
    status_map = {"bidding": "open", "awarded": "finalized", "cancelled": "cancelled"}
    mapped = status_map.get(status, status)
    return get_shift_bid_events(status=mapped, officer_id=officer_id, include_drafts=mapped == "draft", limit=limit)
