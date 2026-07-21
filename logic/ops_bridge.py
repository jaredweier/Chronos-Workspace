"""Simulator → ops bridge: publish readiness, open-shift seeds, bid → soft prefs.

P4 product bridge (WFM pattern): after a feasible plan exists, surface a
publish checklist, optional open-shift callouts for thin bands, and import
shift-bid participation into soft ranking prefs — never as hard gates.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from validators import format_date, parse_date, storage_date_str


def _as_dict(obj: Any) -> Dict[str, Any]:
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "__dict__"):
        return dict(obj.__dict__)
    return {}


def _i(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _result_bundle(result: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    r = result or {}
    best = r.get("best") or {}
    if best and not r.get("metrics"):
        return {**r, "metrics": best.get("metrics") or r.get("metrics") or {}}
    return r


def publish_readiness_checklist(
    result: Optional[Dict[str, Any]] = None,
    config: Optional[Dict[str, Any]] = None,
    *,
    implement_date: str = "",
) -> Dict[str, Any]:
    """Structured pre-publish checklist. blocking items should stop Publish."""
    r = _result_bundle(result)
    c = config or {}
    best = r.get("best") or r
    m = r.get("metrics") or best.get("metrics") or {}
    items: List[Dict[str, Any]] = []

    def add(key: str, ok: bool, label: str, detail: str = "", *, blocking: bool = False):
        items.append(
            {
                "key": key,
                "ok": bool(ok),
                "label": label,
                "detail": detail,
                "blocking": bool(blocking and not ok),
                "level": "blocking" if (blocking and not ok) else ("ok" if ok else "warn"),
            }
        )

    # Success / hard
    hard = best.get("hard_constraints_ok")
    if hard is None:
        hard = m.get("hard_constraints_ok")
    success = bool(r.get("success") or best.get("success") or hard)
    add(
        "plan_success",
        success and hard is not False,
        "Plan available",
        "Hard constraints met" if hard else "No successful hard-OK plan loaded",
        blocking=True,
    )
    add(
        "hard_ok",
        hard is True or hard is None and success,
        "Hard constraints OK",
        "Soft/near-miss only — publish may leave residual shortfalls" if hard is False else "",
        blocking=True,
    )

    starts = best.get("shift_starts") or r.get("shift_starts") or c.get("shift_starts") or []
    if isinstance(starts, str):
        starts = [s.strip() for s in starts.split(",") if s.strip()]
    add(
        "starts",
        bool(starts),
        "Shift starts defined",
        f"{len(starts)} band(s)" if starts else "Missing starts",
        blocking=True,
    )

    n = _i(best.get("num_officers") or m.get("min_officers_required") or c.get("num_officers"), 0)
    add("headcount", n >= 1, "Officer count", f"N={n}" if n else "No headcount", blocking=True)

    # Date
    date_ok = False
    date_detail = "Enter implement start date"
    if (implement_date or "").strip():
        try:
            parse_date(implement_date.strip())
            date_ok = True
            date_detail = implement_date.strip()
        except Exception as exc:
            date_detail = str(exc)
    add("implement_date", date_ok, "Implement start date", date_detail, blocking=True)

    # Soft / residual warnings (non-blocking)
    win = _i(m.get("extra_window_failures"), 0)
    c247 = _i(m.get("coverage_247_failures"), 0)
    gaps = _i(m.get("gap_events"), 0)
    night = _i(m.get("night_risk_gaps"), 0)
    flsa = _i(m.get("flsa_violations"), 0)
    add("windows", win == 0, "Extra windows", f"{win} shortfall(s)" if win else "Clear")
    add("coverage_247", c247 == 0, "24/7 coverage", f"{c247} short day(s)" if c247 else "Clear")
    add("gaps", gaps == 0, "Min-per-shift gaps", f"{gaps} event(s)" if gaps else "Clear")
    add("night_risk", night == 0, "High-risk night soft", f"{night} thin night(s)" if night else "Clear")
    add("flsa", flsa == 0, "FLSA hard filter", f"{flsa} slot(s) over cap" if flsa else "Clear")

    soft = best.get("soft_score")
    if soft is not None:
        add("soft_score", True, "Soft rank score", f"{soft}")
    note = best.get("soft_rank_note") or (r.get("soft_rank") or {}).get("message")
    if note:
        add("soft_note", True, "Soft rank note", str(note)[:120])

    blocking = [x for x in items if x.get("blocking")]
    warns = [x for x in items if x.get("level") == "warn"]
    ready = not blocking
    return {
        "ready": ready,
        "blocking_count": len(blocking),
        "warn_count": len(warns),
        "items": items,
        "summary": (
            "Ready to publish"
            if ready and not warns
            else ("Ready with warnings" if ready else f"{len(blocking)} blocking item(s)")
        ),
    }


def suggest_open_shifts_from_sim(
    result: Optional[Dict[str, Any]] = None,
    *,
    start_date: str = "",
    max_posts: int = 12,
    min_per_band: Optional[int] = None,
) -> Dict[str, Any]:
    """Propose open-shift callouts for thin/empty start bands on coverage days.

    Does not insert — returns candidates for supervisor confirm.
    """
    r = _result_bundle(result)
    best = r.get("best") or r
    coverage = r.get("coverage_by_day") or best.get("coverage_by_day") or []
    m = r.get("metrics") or best.get("metrics") or {}
    floor = min_per_band if min_per_band is not None else _i(m.get("min_per_shift") or best.get("min_per_shift"), 1)
    if floor < 1:
        floor = 1

    length_h = float(best.get("shift_length_hours") or r.get("shift_length_hours") or 8.0)
    length_min = max(30, int(round(length_h * 60)))

    # Anchor calendar if implement date given
    anchor: Optional[date] = None
    if (start_date or "").strip():
        try:
            anchor = parse_date(start_date.strip())
        except Exception:
            anchor = None

    candidates: List[Dict[str, Any]] = []
    for i, day in enumerate(coverage):
        if not isinstance(day, dict):
            continue
        sc = day.get("shift_counts") or {}
        if not isinstance(sc, dict):
            continue
        raw_d = str(day.get("date") or "")
        try:
            # coverage dates are often M/D/YY
            d = parse_date(raw_d) if raw_d else None
        except Exception:
            d = anchor + timedelta(days=i) if anchor else None
        if d is None and anchor is not None:
            d = anchor + timedelta(days=i)
        if d is None:
            continue
        for st, cnt in sc.items():
            try:
                c = int(cnt)
            except (TypeError, ValueError):
                c = 0
            short = max(0, floor - c)
            if short <= 0:
                continue
            # end time
            try:
                hh, mm = map(int, str(st).split(":"))
                end_m = (hh * 60 + mm + length_min) % (24 * 60)
                en = f"{end_m // 60:02d}:{end_m % 60:02d}"
            except Exception:
                en = "00:00"
            risk = bool(day.get("high_risk_night"))
            candidates.append(
                {
                    "shift_date": storage_date_str(d.isoformat()),
                    "shift_date_display": format_date(d),
                    "shift_start": str(st),
                    "shift_end": en,
                    "shortfall": short,
                    "on_band": c,
                    "required": floor,
                    "high_risk": risk,
                    "notes": (f"Sim callout: band {st} had {c}/{floor}" + (" (high-risk night)" if risk else "")),
                    "priority": (0 if risk else 1, -short, str(st)),
                }
            )

    candidates.sort(key=lambda x: x["priority"])
    out = candidates[:max_posts]
    for row in out:
        row.pop("priority", None)
    return {
        "success": True,
        "candidates": out,
        "count": len(out),
        "message": (
            f"{len(out)} open-shift callout(s) suggested from thin bands"
            if out
            else "No thin bands — no open-shift seeds"
        ),
    }


def seed_open_shifts_from_sim(
    result: Optional[Dict[str, Any]] = None,
    *,
    start_date: str = "",
    max_posts: int = 8,
    user_id: Optional[int] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Create open_shifts rows from sim thin bands (supervisor callout board)."""
    from logic.operations import create_open_shift

    sug = suggest_open_shifts_from_sim(result, start_date=start_date, max_posts=max_posts)
    cands = sug.get("candidates") or []
    if dry_run or not cands:
        return {
            "success": True,
            "dry_run": True,
            "created": [],
            "candidates": cands,
            "message": sug.get("message"),
        }

    created: List[Dict[str, Any]] = []
    errors: List[str] = []
    for c in cands:
        r = create_open_shift(
            c["shift_date"],
            c["shift_start"],
            c["shift_end"],
            squad=None,
            notes=c.get("notes") or "From simulator thin band",
            user_id=user_id,
        )
        if r.get("success"):
            created.append({"shift_id": r.get("shift_id"), **c})
        else:
            errors.append(r.get("message") or "create failed")

    return {
        "success": bool(created) or not cands,
        "created": created,
        "errors": errors,
        "count": len(created),
        "message": f"Posted {len(created)} open shift(s)" + (f" · {len(errors)} error(s)" if errors else ""),
    }


def soft_prefs_from_bid_rankings(
    event_id: Optional[int] = None,
    *,
    base_prefs: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """Map shift-bid rankings → soft_prefs boosts (night / weekend preference).

    Uses latest open/closed bid event if event_id omitted.
    """
    from logic.soft_rank import default_soft_prefs

    prefs = dict(base_prefs or default_soft_prefs())
    try:
        from database import connection
    except Exception as exc:
        return {"success": False, "message": str(exc), "soft_prefs": prefs}

    with connection() as conn:
        cur = conn.cursor()
        eid = event_id
        if not eid:
            cur.execute(
                """
                SELECT id FROM shift_bid_events
                WHERE status IN ('open', 'closed', 'published', 'draft')
                ORDER BY id DESC LIMIT 1
                """
            )
            row = cur.fetchone()
            if not row:
                return {
                    "success": False,
                    "message": "No shift bid events found",
                    "soft_prefs": prefs,
                }
            eid = int(row[0] if not isinstance(row, dict) else row["id"])

        # Options with start times
        cur.execute(
            "SELECT id, shift_start, label FROM shift_bid_options WHERE event_id = ?",
            (eid,),
        )
        opts = cur.fetchall()
        opt_starts: Dict[int, str] = {}
        for o in opts:
            if isinstance(o, dict):
                oid, st = int(o["id"]), str(o.get("shift_start") or "")
            else:
                oid, st = int(o[0]), str(o[1] or "")
            opt_starts[oid] = st

        cur.execute(
            """
            SELECT option_id, rank FROM shift_bid_rankings
            WHERE event_id = ?
            """,
            (eid,),
        )
        ranks = cur.fetchall()

    if not ranks:
        return {
            "success": False,
            "message": f"Bid event #{eid} has no rankings yet",
            "soft_prefs": prefs,
            "event_id": eid,
        }

    # rank 1 = most preferred; weight night starts if popular
    night_weight = 0.0
    day_weight = 0.0
    n = 0
    for row in ranks:
        if isinstance(row, dict):
            oid, rk = int(row["option_id"]), int(row.get("rank") or 99)
        else:
            oid, rk = int(row[0]), int(row[1] or 99)
        st = opt_starts.get(oid, "")
        try:
            hh = int(str(st).split(":")[0])
        except Exception:
            hh = 12
        is_night = hh >= 19 or hh < 6
        # higher score for better ranks
        w = max(0.0, 4.0 - float(rk))
        if is_night:
            night_weight += w
        else:
            day_weight += w
        n += 1

    if n:
        if night_weight > day_weight * 1.1:
            prefs["prefer_night_starts"] = min(2.0, float(prefs.get("prefer_night_starts") or 0) + 0.8)
            prefs["balance_nights"] = min(2.0, float(prefs.get("balance_nights") or 0) + 0.3)
            hint = "Bids favor night starts — boosted prefer_night_starts"
        elif day_weight > night_weight * 1.1:
            prefs["prefer_night_starts"] = max(0.0, float(prefs.get("prefer_night_starts") or 0) * 0.5)
            hint = "Bids favor day starts — reduced prefer_night_starts"
        else:
            prefs["balance_nights"] = min(2.0, float(prefs.get("balance_nights") or 0) + 0.5)
            hint = "Bids mixed — boosted night balance"
    else:
        hint = "No ranking weight"

    return {
        "success": True,
        "event_id": eid,
        "soft_prefs": prefs,
        "message": hint,
        "samples": n,
    }


def format_readiness_lines(checklist: Optional[Dict[str, Any]] = None) -> List[str]:
    c = checklist or {}
    lines = [c.get("summary") or "Publish readiness"]
    for it in c.get("items") or []:
        mark = "✓" if it.get("ok") else ("✕" if it.get("blocking") else "!")
        det = f" — {it['detail']}" if it.get("detail") else ""
        lines.append(f"{mark} {it.get('label')}{det}")
    return lines
