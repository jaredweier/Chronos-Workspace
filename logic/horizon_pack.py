"""P11–P16 / P18 horizon features for the schedule simulator.

P11 non-dominated shortlist · P12 structured conflicts · P13 open-shift deputy
P14 OT ledger ↔ FLSA · P15 bid→seed prefs · P16 scenario stories · P18 gantt delta
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

# ── P12 structured conflict IDs (MUS-style catalog) ─────────────────────────

CONFLICT_CATALOG: Dict[str, Dict[str, str]] = {
    "C_BODY_FLOOR": {
        "label": "Body floor vs locked N",
        "fix": "Raise officer count or lower 24/7 / peak window min",
    },
    "C_247": {
        "label": "24/7 coverage shortfalls",
        "fix": "Add officers, stagger phases, or lower 24/7 min",
    },
    "C_WINDOWS": {
        "label": "Peak window shortfalls",
        "fix": "Raise N, add evening starts, or lower window min",
    },
    "C_GAPS": {
        "label": "Min-per-shift gaps",
        "fix": "Lower min/shift or add start bands",
    },
    "C_ANNUAL": {
        "label": "Annual hours band",
        "fix": "Widen annual variance or unlock length / multi-block",
    },
    "C_FLSA": {
        "label": "FLSA period over threshold",
        "fix": "Shorter shifts, more officers, or unlock avoid-OT",
    },
    "C_REST": {
        "label": "Rest / consecutive limits",
        "fix": "Relax fatigue locks or change start pack",
    },
    "C_CHEAP": {
        "label": "Cheap domain reject",
        "fix": "Unlock starts / N / length (domain prune)",
    },
    "C_UNKNOWN": {
        "label": "Unclassified hard fail",
        "fix": "Review autopsy histogram and near-miss metrics",
    },
}


def _i(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _f(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def structured_conflict_report(
    result: Optional[Dict[str, Any]] = None,
    *,
    form: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """P12: map failure histogram / metrics → conflict IDs + fixes."""
    r = result or {}
    form = form or {}
    ids: List[str] = []
    hist = r.get("failure_histogram") or {}
    m = (r.get("best") or {}).get("metrics") or r.get("metrics") or {}

    def add(cid: str):
        if cid not in ids:
            ids.append(cid)

    if hist.get("coverage_247") or _i(m.get("coverage_247_failures")):
        add("C_247")
    if hist.get("windows") or hist.get("window") or _i(m.get("extra_window_failures")):
        add("C_WINDOWS")
    if hist.get("gaps") or _i(m.get("gap_events")):
        add("C_GAPS")
    if hist.get("annual") or _i(m.get("annual_band_outside")) or _i(m.get("annual_mean_outside")):
        add("C_ANNUAL")
    if hist.get("flsa") or _i(m.get("flsa_violations")):
        add("C_FLSA")
    if _i(m.get("rest_failures")) or _i(m.get("consecutive_work_failures")):
        add("C_REST")
    if hist.get("cheap_reject"):
        add("C_CHEAP")

    # Body floor vs N
    try:
        from logic.constraint_autopsy import cheap_feasibility_strip

        strip = cheap_feasibility_strip(form or r.get("constraints_applied") or {})
        if strip.get("status") == "blocked":
            add("C_BODY_FLOOR")
    except Exception:
        pass

    if not ids and (r.get("impossible") or not r.get("success")):
        add("C_UNKNOWN")

    conflicts = []
    for cid in ids:
        meta = CONFLICT_CATALOG.get(cid, CONFLICT_CATALOG["C_UNKNOWN"])
        conflicts.append(
            {
                "id": cid,
                "label": meta["label"],
                "fix": meta["fix"],
                "count": _i(hist.get(cid.replace("C_", "").lower()) or hist.get(cid), 0) or None,
            }
        )
    return {
        "success": True,
        "conflict_ids": ids,
        "conflicts": conflicts,
        "summary": (
            f"{len(conflicts)} structured conflict(s): " + ", ".join(ids) if ids else "No structured conflicts"
        ),
    }


# ── P11 non-dominated shortlist ─────────────────────────────────────────────


def non_dominated_shortlist(
    ranked: Sequence[Dict[str, Any]],
    *,
    max_keep: int = 6,
) -> Dict[str, Any]:
    """P11: keep only hard-OK non-dominated on (N min, OT min, fairness max)."""
    from logic.sim_wave2 import annotate_pareto_shortlist

    rows = annotate_pareto_shortlist([dict(r) for r in (ranked or [])])
    hard = [r for r in rows if r.get("hard_constraints_ok")]

    def n_of(r):
        return _i(r.get("num_officers"), 99)

    def ot_of(r):
        return _f((r.get("economics") or {}).get("est_ot_hours_total"), 999.0)

    def fair_of(r):
        e = r.get("economics") or {}
        return _f(e.get("fairness_score") or r.get("soft_score"), 0.0)

    nd = []
    for r in hard:
        dominated = False
        for o in hard:
            if o is r:
                continue
            if n_of(o) <= n_of(r) and ot_of(o) <= ot_of(r) and fair_of(o) >= fair_of(r):
                if n_of(o) < n_of(r) or ot_of(o) < ot_of(r) or fair_of(o) > fair_of(r):
                    dominated = True
                    break
        if not dominated:
            r = dict(r)
            r["non_dominated"] = True
            nd.append(r)

    # rank chips
    chips = []
    for r in nd[:max_keep]:
        chips.append(
            {
                "rank": r.get("rank"),
                "n": n_of(r),
                "ot": ot_of(r),
                "fairness": fair_of(r),
                "labels": r.get("pareto_labels") or [],
                "summary": (r.get("summary") or "")[:80],
            }
        )
    return {
        "success": True,
        "non_dominated": nd[:max_keep],
        "chips": chips,
        "count": len(nd),
        "message": f"{len(nd)} non-dominated hard-OK option(s) on N/OT/fairness",
    }


# ── P13 open-shift deputy ───────────────────────────────────────────────────


def score_open_shift_candidates(
    candidates: Sequence[Dict[str, Any]],
    *,
    limit: int = 12,
) -> Dict[str, Any]:
    """P13: rank thin-band callouts + attach deputy score from live roster when possible."""
    from logic.ops_bridge import suggest_open_shifts_from_sim  # noqa: F401 — re-export path

    cands = [dict(c) for c in (candidates or [])]
    # Prefer high-risk + larger shortfall first (already sorted); add deputy scores
    scored = []
    for c in cands:
        base = 50.0
        if c.get("high_risk"):
            base += 25
        base += min(20, _i(c.get("shortfall"), 0) * 8)
        # try live candidate rank if shift exists
        deputy = None
        try:
            from logic.operations import rank_open_shift_candidates

            sid = c.get("shift_id")
            if sid:
                rr = rank_open_shift_candidates(int(sid), limit=5)
                if rr.get("success"):
                    deputy = (rr.get("candidates") or [])[:3]
                    base += 5
        except Exception:
            pass
        c["deputy_score"] = round(base, 1)
        c["deputy_candidates"] = deputy
        scored.append(c)
    scored.sort(key=lambda x: (-_f(x.get("deputy_score")), 0 if x.get("high_risk") else 1))
    return {
        "success": True,
        "candidates": scored[:limit],
        "message": f"{min(len(scored), limit)} callout(s) ranked for deputy fill",
    }


def open_shift_deputy_from_sim(
    result: Optional[Dict[str, Any]] = None,
    *,
    start_date: str = "",
    max_posts: int = 8,
) -> Dict[str, Any]:
    from logic.ops_bridge import suggest_open_shifts_from_sim

    sug = suggest_open_shifts_from_sim(result, start_date=start_date, max_posts=max_posts)
    return score_open_shift_candidates(sug.get("candidates") or [], limit=max_posts)


# ── P14 live OT ledger ↔ FLSA meters ────────────────────────────────────────


def ot_ledger_vs_flsa(
    row: Optional[Dict[str, Any]] = None,
    *,
    flsa_period_days: int = 28,
) -> Dict[str, Any]:
    """Side-by-side soft meters: sim FLSA estimate vs live equitable OT ledger head."""
    row = row or {}
    meters = row.get("flsa_period_meters")
    if not meters:
        try:
            from logic.sim_wave2 import multi_period_flsa_meters
            from logic.staffing_insights import duty_fraction_from_variations

            frac = duty_fraction_from_variations(row.get("rotation_variations") or [])
            length = _f(row.get("shift_length_hours"), 8.0)
            meters = multi_period_flsa_meters(shift_length_hours=length, duty_fraction=frac, periods=(7, 14, 28))
        except Exception:
            meters = []

    live = {"available": False, "top": [], "message": "Live OT ledger unavailable"}
    try:
        from logic.analytics import get_equitable_ot_ledger

        ledger = get_equitable_ot_ledger(limit=8) or {}
        rows = ledger.get("rows") or ledger.get("officers") or ledger
        if isinstance(rows, list) and rows:
            top = []
            for r in rows[:5]:
                if not isinstance(r, dict):
                    continue
                top.append(
                    {
                        "name": r.get("name") or r.get("officer_name") or r.get("id"),
                        "ot_hours": r.get("ot_hours") or r.get("overtime_hours") or r.get("hours"),
                    }
                )
            live = {
                "available": True,
                "top": top,
                "message": f"{len(top)} officer(s) from equitable OT ledger",
            }
    except Exception as exc:
        live["message"] = f"Ledger: {exc}"[:120]

    return {
        "success": True,
        "sim_flsa_meters": meters,
        "live_ot": live,
        "note": "Sim meters = structural estimate; ledger = actual OT equity (compare, soft only)",
        "period_days": flsa_period_days,
    }


# ── P15 bid prefs → seed soft vector ────────────────────────────────────────


def bid_prefs_for_cpsat_seed(
    event_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Map bid rankings to seed soft weights (pattern balance / night preference)."""
    from logic.ops_bridge import soft_prefs_from_bid_rankings

    r = soft_prefs_from_bid_rankings(event_id=event_id)
    prefs = r.get("soft_prefs") or {}
    # Seed vector for CP-SAT: higher night preference → favor maps with night-capable patterns
    seed = {
        "w_pattern_equity": 50 + int(10 * _f(prefs.get("balance_nights"), 0)),
        "w_night_pref": int(20 * _f(prefs.get("prefer_night_starts"), 0)),
        "soft_prefs": prefs,
        "event_id": r.get("event_id"),
        "message": r.get("message") or "",
        "success": bool(r.get("success")),
    }
    return seed


# ── P16 scenario story cards ────────────────────────────────────────────────


def scenario_story_cards(
    form: Optional[Dict[str, Any]] = None,
    *,
    deltas: Optional[Sequence[Dict[str, int]]] = None,
) -> Dict[str, Any]:
    """Narrative cards: 'If we hire 1…' from what-if sandbox batch."""
    from logic.sim_wave2 import whatif_sandbox

    form = form or {}
    deltas = list(
        deltas
        or (
            {"delta_n": 1, "delta_window_min": 0, "delta_247": 0},
            {"delta_n": 0, "delta_window_min": -1, "delta_247": 0},
            {"delta_n": 0, "delta_window_min": 0, "delta_247": -1},
            {"delta_n": 2, "delta_window_min": 0, "delta_247": 0},
        )
    )
    cards = []
    for d in deltas:
        r = whatif_sandbox(
            form,
            delta_n=_i(d.get("delta_n")),
            delta_window_min=_i(d.get("delta_window_min")),
            delta_247=_i(d.get("delta_247")),
        )
        title_bits = []
        if d.get("delta_n"):
            title_bits.append(f"hire {d['delta_n']}" if d["delta_n"] > 0 else f"cut {-d['delta_n']}")
        if d.get("delta_window_min"):
            title_bits.append(f"window min {d['delta_window_min']:+d}")
        if d.get("delta_247"):
            title_bits.append(f"24/7 {d['delta_247']:+d}")
        status = (r.get("strip") or {}).get("status") or "ok"
        story = r.get("narrative") or ""
        if r.get("predicted_unlock"):
            story = f"{story}. Unlock: {r['predicted_unlock']}"
        cards.append(
            {
                "title": "If we " + " and ".join(title_bits) if title_bits else "Baseline",
                "status": status,
                "story": story,
                "deltas": d,
                "tone": "positive" if status == "ok" else ("warning" if status == "caution" else "negative"),
            }
        )
    return {"success": True, "cards": cards, "message": f"{len(cards)} scenario story card(s)"}


# ── P18 Gantt duty toggle → delta metrics ───────────────────────────────────


def gantt_duty_delta(
    result: Optional[Dict[str, Any]] = None,
    *,
    slot_index: int = 0,
    day_index: int = 0,
    set_on: Optional[bool] = None,
) -> Dict[str, Any]:
    """Toggle one officer-day duty flag and recompute local coverage counts (no full re-sim).

    Returns before/after headcount on that day and a soft delta message.
    Full hard proof still requires Generate / Find Best.
    """
    r = dict(result or {})
    slots = [
        dict(s) if isinstance(s, dict) else dict(getattr(s, "__dict__", {}) or {})
        for s in (r.get("officer_slots") or [])
    ]
    coverage = [dict(d) for d in (r.get("coverage_by_day") or []) if isinstance(d, dict)]
    if not slots:
        return {"success": False, "message": "No officer_slots — run Generate first"}
    si = max(0, min(int(slot_index), len(slots) - 1))
    slot = slots[si]
    flags = list(slot.get("work_flags") or slot.get("duty_vector") or [])
    if not flags and coverage:
        flags = [False] * len(coverage)
    if day_index < 0 or day_index >= max(len(flags), 1):
        return {"success": False, "message": f"day_index {day_index} out of range"}
    while len(flags) <= day_index:
        flags.append(False)
    before = bool(flags[day_index])
    after = (not before) if set_on is None else bool(set_on)
    flags[day_index] = after
    slot["work_flags"] = flags
    slots[si] = slot

    # Local day working count
    day_on_before = sum(
        1
        for s in (r.get("officer_slots") or [])
        for ff in [list((s if isinstance(s, dict) else getattr(s, "__dict__", {}) or {}).get("work_flags") or [])]
        if day_index < len(ff) and ff[day_index]
    )
    day_on_after = sum(
        1 for s in slots for ff in [list(s.get("work_flags") or [])] if day_index < len(ff) and ff[day_index]
    )
    date_lab = ""
    if day_index < len(coverage):
        date_lab = str(coverage[day_index].get("date") or "")
        coverage[day_index]["working_officers"] = day_on_after

    return {
        "success": True,
        "slot_index": si,
        "day_index": day_index,
        "date": date_lab,
        "officer": slot.get("label") or f"Officer {si + 1}",
        "before_on": before,
        "after_on": after,
        "day_working_before": day_on_before,
        "day_working_after": day_on_after,
        "delta_bodies": day_on_after - day_on_before,
        "officer_slots": slots,
        "coverage_by_day": coverage,
        "message": (
            f"{slot.get('label') or 'Officer'} day {day_index + 1}: "
            f"{'ON' if before else 'OFF'}→{'ON' if after else 'OFF'} · "
            f"day bodies {day_on_before}→{day_on_after} "
            "(local delta only — re-run Generate for hard truth)"
        ),
        "soft_only": True,
    }


def enrich_horizon_result(
    result: Optional[Dict[str, Any]] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Attach P11 shortlist + P12 conflicts + P14 OT bridge onto a search result."""
    from logic.sim_wave2 import enrich_wave2_result

    r = enrich_wave2_result(result, config)
    nd = non_dominated_shortlist(r.get("ranked") or [])
    r["non_dominated_shortlist"] = nd
    r["conflict_report"] = structured_conflict_report(r, form=config or {})
    best = r.get("best") or {}
    r["ot_flsa_bridge"] = ot_ledger_vs_flsa(best)
    if r.get("impossible") or not r.get("success"):
        # merge conflict IDs into counterfactual section messaging
        cr = r["conflict_report"]
        if cr.get("conflict_ids"):
            r["structured_conflicts"] = cr["conflicts"]
    return r
