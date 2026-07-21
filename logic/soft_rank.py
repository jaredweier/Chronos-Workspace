"""Soft ranking among *feasible* (hard-OK) staffing options only.

Product law: Find Best hard constraints first. Fairness / prefs / OT / night
balance are optional narrowers — never promote a hard-fail over hard-OK.

Inspired by OR-Tools preference maximize + Timefold soft scores.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

DEFAULT_SOFT_PREFS: Dict[str, float] = {
    # Higher weight = stronger preference when re-ranking hard-OK set
    "balance_nights": 1.0,  # even night starts across officers
    "balance_weekends": 0.8,  # even Fri/Sat work days
    "fewer_officers": 0.6,  # mild — lower N better among hard-OK
    "lower_ot": 0.7,  # lower est OT hours/cost
    "lower_annual_spread": 1.0,  # smaller hours range across roster
    "prefer_night_starts": 0.0,  # optional: reward packs with night bands
}


def default_soft_prefs() -> Dict[str, float]:
    return dict(DEFAULT_SOFT_PREFS)


def _as_dict(obj: Any) -> Dict[str, Any]:
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "__dict__"):
        return dict(obj.__dict__)
    return {}


def _f(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _i(v: Any, default: int = 0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _is_night_start(start: str) -> bool:
    try:
        h = int(str(start).split(":")[0])
    except Exception:
        return False
    return h >= 19 or h < 6


def night_weekend_balance(row: Dict[str, Any]) -> Dict[str, float]:
    """Per-option balance metrics from officer_slots work_flags + starts.

    Returns night_gini-ish spread (0=even), weekend_spread, night_counts list stats.
    """
    slots = row.get("officer_slots") or (row.get("metrics") or {}).get("officer_slots") or []
    if not slots and row.get("best"):
        slots = (row.get("best") or {}).get("officer_slots") or []
    night_loads: List[int] = []
    weekend_loads: List[int] = []
    coverage = row.get("coverage_by_day") or []
    weekend_idx = set()
    for i, day in enumerate(coverage):
        if not isinstance(day, dict):
            continue
        if day.get("high_risk_night"):
            weekend_idx.add(i)
        else:
            # parse date weekday if possible
            d = str(day.get("date") or "")
            try:
                from datetime import datetime

                for fmt in ("%Y-%m-%d", "%m/%d/%y", "%m/%d/%Y"):
                    try:
                        wd = datetime.strptime(d[:10] if fmt.startswith("%Y") else d, fmt).weekday()
                        if wd in (4, 5):
                            weekend_idx.add(i)
                        break
                    except ValueError:
                        continue
            except Exception:
                pass

    for raw in slots:
        s = _as_dict(raw)
        flags = s.get("work_flags") or s.get("duty_vector") or []
        if not isinstance(flags, list):
            flags = []
        start = str(s.get("shift_start") or s.get("home_start") or "")
        is_night = _is_night_start(start)
        n_on = sum(1 for f in flags if f)
        if is_night:
            night_loads.append(n_on)
        else:
            night_loads.append(0)  # day-start officers contribute 0 night load
        # weekend ON days
        w_on = sum(1 for i, f in enumerate(flags) if f and i in weekend_idx)
        if not weekend_idx and flags:
            # no coverage calendar — approximate last 2/7 of days as weekend-ish skip
            w_on = sum(1 for i, f in enumerate(flags) if f and (i % 7) in (4, 5))
        weekend_loads.append(w_on)

    def _spread(vals: List[int]) -> float:
        if not vals:
            return 0.0
        return float(max(vals) - min(vals))

    return {
        "night_load_spread": _spread(night_loads),
        "weekend_load_spread": _spread(weekend_loads),
        "night_officers": sum(1 for s in slots if _is_night_start(str(_as_dict(s).get("shift_start") or ""))),
        "n_slots": len(slots),
    }


def soft_components(
    row: Dict[str, Any],
    prefs: Optional[Dict[str, float]] = None,
    *,
    peer_n_min: Optional[int] = None,
    peer_n_max: Optional[int] = None,
    peer_ot_max: Optional[float] = None,
    peer_spread_max: Optional[float] = None,
) -> Dict[str, float]:
    """Component soft scores in ~0–100 (higher better). Hard-fail rows score 0."""
    p = {**DEFAULT_SOFT_PREFS, **(prefs or {})}
    hard = row.get("hard_constraints_ok")
    if hard is False:
        return {
            "hard_gate": 0.0,
            "balance_nights": 0.0,
            "balance_weekends": 0.0,
            "fewer_officers": 0.0,
            "lower_ot": 0.0,
            "lower_annual_spread": 0.0,
            "prefer_night_starts": 0.0,
            "total": 0.0,
        }

    m = row.get("metrics") or row.get("human_metrics") or {}
    econ = row.get("economics") or {}
    bal = night_weekend_balance(row)

    # Balance: 100 when spread 0, drop as spread grows
    night_sp = bal.get("night_load_spread") or 0.0
    week_sp = bal.get("weekend_load_spread") or 0.0
    bal_n = max(0.0, 100.0 - night_sp * 8.0)
    bal_w = max(0.0, 100.0 - week_sp * 10.0)

    n = _i(row.get("num_officers") or m.get("min_officers_required"), 0)
    if peer_n_min is not None and peer_n_max is not None and peer_n_max > peer_n_min:
        # Higher score for fewer officers within hard-OK peer set
        fewer = 100.0 * (peer_n_max - n) / max(peer_n_max - peer_n_min, 1)
    elif n > 0:
        fewer = max(0.0, 100.0 - (n - 4) * 6.0)
    else:
        fewer = 50.0

    ot = _f(econ.get("est_ot_hours_total"), _f(m.get("est_ot_hours"), 0.0))
    if peer_ot_max and peer_ot_max > 0:
        lower_ot = 100.0 * (1.0 - min(1.0, ot / peer_ot_max))
    else:
        lower_ot = max(0.0, 100.0 - ot * 2.0)

    spread = _f(m.get("annual_hours_spread") or (row.get("human_metrics") or {}).get("annual_hours_spread"), 0.0)
    if peer_spread_max and peer_spread_max > 0:
        lower_spread = 100.0 * (1.0 - min(1.0, spread / peer_spread_max))
    else:
        lower_spread = max(0.0, 100.0 - spread * 0.8)

    starts = row.get("shift_starts") or []
    if isinstance(starts, str):
        starts = [s.strip() for s in starts.split(",") if s.strip()]
    night_starts = sum(1 for s in starts if _is_night_start(str(s)))
    prefer_night = 100.0 if night_starts else 40.0
    if night_starts >= 2:
        prefer_night = 100.0
    elif night_starts == 1:
        prefer_night = 80.0

    # fairness_score from economics if present
    fair = _f(econ.get("fairness_score") or (row.get("human_metrics") or {}).get("fairness_score"), 50.0)

    comps = {
        "hard_gate": 100.0 if hard is not False else 0.0,
        "balance_nights": bal_n,
        "balance_weekends": bal_w,
        "fewer_officers": fewer,
        "lower_ot": lower_ot,
        "lower_annual_spread": lower_spread,
        "prefer_night_starts": prefer_night,
        "fairness_proxy": fair,
    }
    # Weighted total (ignore hard_gate in sum — already filtered)
    wsum = 0.0
    total = 0.0
    for key, w in p.items():
        ww = _f(w, 0.0)
        if ww <= 0:
            continue
        base = comps.get(key, comps.get("fairness_proxy", 50.0))
        total += base * ww
        wsum += ww
    comps["total"] = round(total / wsum, 2) if wsum else round(fair, 2)
    return comps


def rank_soft_among_feasible(
    ranked: Sequence[Dict[str, Any]],
    prefs: Optional[Dict[str, float]] = None,
    *,
    near_misses: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Re-order hard-OK options by soft score; hard-fail / near-miss stay after.

    Returns {ranked, best, soft_applied, prefs_used, message}.
    """
    prefs_used = {**DEFAULT_SOFT_PREFS, **(prefs or {})}
    rows = [dict(r) for r in (ranked or [])]
    hard_ok = [r for r in rows if r.get("hard_constraints_ok")]
    hard_fail = [r for r in rows if not r.get("hard_constraints_ok")]

    # Peer norms among hard-OK only
    ns = [_i(r.get("num_officers"), 0) for r in hard_ok if _i(r.get("num_officers"), 0) > 0]
    ots = []
    spreads = []
    for r in hard_ok:
        m = r.get("metrics") or {}
        econ = r.get("economics") or {}
        ots.append(_f(econ.get("est_ot_hours_total"), 0.0))
        spreads.append(_f(m.get("annual_hours_spread"), 0.0))
    peer_n_min = min(ns) if ns else None
    peer_n_max = max(ns) if ns else None
    peer_ot_max = max(ots) if ots else None
    peer_spread_max = max(spreads) if spreads else None

    scored: List[Tuple[float, Dict[str, Any]]] = []
    for r in hard_ok:
        comps = soft_components(
            r,
            prefs_used,
            peer_n_min=peer_n_min,
            peer_n_max=peer_n_max,
            peer_ot_max=peer_ot_max if peer_ot_max and peer_ot_max > 0 else None,
            peer_spread_max=peer_spread_max if peer_spread_max and peer_spread_max > 0 else None,
        )
        r["soft_score"] = comps["total"]
        r["soft_components"] = comps
        r["soft_rank_note"] = _note(comps, prefs_used)
        # Preserve internal hard score as secondary key
        hard_score = _f(r.get("_internal_score") or r.get("score"), 0.0)
        scored.append((comps["total"], hard_score, r))

    scored.sort(key=lambda t: (-t[0], -t[1]))
    ordered_hard = []
    for i, (_, __, r) in enumerate(scored, start=1):
        r["rank"] = i
        r["soft_rank"] = i
        ordered_hard.append(r)

    # Near-misses / hard fails after — ranks continue
    base = len(ordered_hard)
    for j, r in enumerate(hard_fail):
        r = dict(r)
        r["soft_score"] = 0.0
        r["soft_components"] = soft_components(r, prefs_used)
        r["soft_rank_note"] = "Hard constraints not met — soft prefs not applied"
        r["rank"] = base + j + 1
        ordered_hard.append(r)

    # Optional near_misses not already in ranked
    if near_misses:
        seen = {id(r) for r in ordered_hard}
        for nm in near_misses:
            if nm in seen:
                continue
            r = dict(nm)
            if r.get("hard_constraints_ok"):
                continue
            r["soft_score"] = 0.0
            r["soft_rank_note"] = "Near-miss — soft prefs not applied"
            r["rank"] = len(ordered_hard) + 1
            ordered_hard.append(r)

    best = ordered_hard[0] if ordered_hard else None
    msg = None
    if best and best.get("hard_constraints_ok") and best.get("soft_rank_note"):
        msg = f"Soft rank among hard-OK: {best['soft_rank_note']}"
    return {
        "ranked": ordered_hard,
        "best": best,
        "soft_applied": bool(hard_ok),
        "prefs_used": prefs_used,
        "hard_ok_count": len(hard_ok),
        "message": msg,
    }


def _note(comps: Dict[str, float], prefs: Dict[str, float]) -> str:
    """One-line why this option ranks soft-high."""
    parts = []
    if _f(prefs.get("balance_nights")) > 0:
        parts.append(f"night balance {comps.get('balance_nights', 0):.0f}")
    if _f(prefs.get("lower_annual_spread")) > 0:
        parts.append(f"hours spread {comps.get('lower_annual_spread', 0):.0f}")
    if _f(prefs.get("fewer_officers")) > 0:
        parts.append(f"headcount {comps.get('fewer_officers', 0):.0f}")
    if _f(prefs.get("lower_ot")) > 0:
        parts.append(f"OT {comps.get('lower_ot', 0):.0f}")
    total = comps.get("total", 0)
    if not parts:
        return f"soft score {total:.0f}"
    return f"soft {total:.0f} · " + ", ".join(parts[:3])


def apply_soft_rank_to_result(
    result: Optional[Dict[str, Any]] = None,
    prefs: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """Mutate-safe: return new result dict with soft-reordered ranked/best."""
    r = dict(result or {})
    if not r.get("ranked") and r.get("best"):
        r["ranked"] = [r["best"]]
    out = rank_soft_among_feasible(
        r.get("ranked") or [],
        prefs,
        near_misses=r.get("near_misses"),
    )
    r["ranked"] = out["ranked"]
    if out["best"] is not None:
        r["best"] = out["best"]
    r["soft_rank"] = {
        "applied": out["soft_applied"],
        "prefs": out["prefs_used"],
        "hard_ok_count": out["hard_ok_count"],
        "message": out["message"],
    }
    if out["message"] and r.get("success"):
        # Append soft note — do not claim hard feasibility changed
        base = r.get("message") or ""
        if "Soft rank" not in base:
            r["message"] = f"{base} · {out['message']}" if base else out["message"]
    return r
