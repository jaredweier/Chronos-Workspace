"""Constraint autopsy + cheap feasibility strip for the schedule simulator.

Industry pattern (Timefold explain-score / WFM gap boards):
  hard feasibility first; soft scores never block Find Best.

This module is pure (no UI / no SQL). UI layers format the dicts.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

_CONSTRAINT_PLAIN = {
    "coverage_247": "24/7 Coverage",
    "windows": "Extra Windows",
    "window": "Extra Windows",
    "gaps": "Min Per Shift / Gaps",
    "flsa": "FLSA OT",
    "annual": "Annual Hours",
    "cheap_reject": "Cheap Reject (domain)",
    "rest": "Rest / Fatigue",
    "fatigue": "Rest / Fatigue",
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


def theoretical_body_floor(
    *,
    coverage_247: int = 0,
    window_min: int = 0,
    min_per_shift: int = 0,
    n_starts: int = 0,
) -> int:
    """Rough lower bound on simultaneous bodies (not full roster size)."""
    floor = max(_i(coverage_247), _i(window_min), 0)
    if _i(min_per_shift) > 0 and _i(n_starts) > 0:
        # Concurrent starts can stack; floor is at least max concurrent demand
        floor = max(floor, _i(min_per_shift))
    return max(floor, 0)


def rough_min_roster(
    *,
    body_floor: int,
    shift_length_hours: Optional[float] = None,
    pattern_work_frac: float = 0.5,
) -> int:
    """Heuristic roster size from body floor ÷ work fraction (multi-block ~0.5–0.6)."""
    bf = max(0, _i(body_floor))
    if bf <= 0:
        return 0
    frac = _f(pattern_work_frac, 0.5)
    if frac <= 0.05:
        frac = 0.5
    # length reserved for future annual math; not used in body→roster convert
    _ = shift_length_hours
    return max(bf, int(round(bf / frac)))


def cheap_feasibility_strip(form: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Live strip signals from form locks — no full 56d sim.

    Returns status: ok | caution | blocked, lines[], risk.
    """
    c = form or {}
    lines: List[str] = []
    risk = "low"
    status = "ok"

    n = _i(c.get("num_officers") or c.get("officers"), 0)
    auto_n = bool(c.get("auto_min_officers") or not n)
    length = c.get("shift_length_hours")
    if length is None:
        length = c.get("length")
    length_f = _f(length, 0.0) if length is not None else None

    cov247 = _i(c.get("coverage_247") or c.get("cov247"), 0)
    min_ps = _i(c.get("min_per_shift") or c.get("min_ps"), 0)
    starts = c.get("shift_starts") or c.get("starts") or []
    if isinstance(starts, str):
        starts = [s.strip() for s in starts.split(",") if s.strip()]
    n_starts = len(starts) if isinstance(starts, (list, tuple)) else 0

    win_min = 0
    windows = c.get("extra_windows") or c.get("windows") or []
    if isinstance(windows, list):
        for w in windows:
            if not isinstance(w, dict):
                continue
            if w.get("enabled", True) is False:
                continue
            win_min = max(win_min, _i(w.get("min_officers") or w.get("min"), 0))

    body = theoretical_body_floor(
        coverage_247=cov247,
        window_min=win_min,
        min_per_shift=min_ps,
        n_starts=n_starts,
    )
    roster_hint = rough_min_roster(body_floor=body, shift_length_hours=length_f)

    if body > 0:
        lines.append(f"Body floor (simultaneous): ≥{body}")
    if roster_hint > 0:
        lines.append(f"Rough roster hint: ≥{roster_hint} (work-frac heuristic, not a hard gate)")

    if not auto_n and n > 0 and roster_hint > 0 and n < roster_hint:
        status = "caution"
        risk = "medium"
        lines.append(f"Locked N={n} is below rough roster hint {roster_hint} — Find Best may return no hard match.")
    if not auto_n and n > 0 and body > 0 and n < body:
        status = "blocked"
        risk = "high"
        lines.append(f"Locked N={n} < simultaneous floor {body} — hard coverage cannot hold.")

    annual = c.get("annual_hours_target") or c.get("annual")
    if annual is not None and length_f and length_f > 0:
        # 2008h / length ≈ work days; multi-block ~ half calendar days work
        target = _f(annual)
        days_work = target / length_f if length_f else 0
        frac = days_work / 365.25 if days_work else 0
        if frac < 0.35 or frac > 0.75:
            if status == "ok":
                status = "caution"
                risk = "medium" if risk == "low" else risk
            lines.append(
                f"Annual {target:.0f}h @ {length_f:g}h ≈ work-frac {frac:.0%} — "
                "check multi-block pattern vs target (soft band)."
            )
        else:
            lines.append(f"Annual {target:.0f}h @ {length_f:g}h ≈ work-frac {frac:.0%} (plausible)")

    if cov247 > 0:
        lines.append(f"24/7 min {cov247} locked — needs continuous tile + enough N")
    if win_min > 0:
        lines.append(f"Peak window min {win_min}")

    if not lines:
        lines.append("Locks look open — space estimate drives search cost.")

    return {
        "status": status,
        "risk": risk,
        "body_floor": body,
        "roster_hint": roster_hint,
        "lines": lines,
    }


def constraint_autopsy(
    result: Optional[Dict[str, Any]] = None,
    config: Optional[Dict[str, Any]] = None,
    *,
    max_reasons: int = 5,
    max_unlocks: int = 3,
) -> Dict[str, Any]:
    """Structured post-search autopsy (hard-first).

    Returns:
      summary, reasons[{label, count, detail}], unlocks[{action, why, estimated_unlock}],
      near_miss_count, hard_ok, impossible
    """
    from logic.optimizer_features import near_miss_deltas, suggest_relaxations, suggest_unlocks

    r = result or {}
    c = config or {}
    best = r.get("best") or {}
    hard_ok = bool(r.get("success") and best.get("hard_constraints_ok"))
    impossible = bool(r.get("impossible") or (not hard_ok and r.get("require_hard_ok", True)))

    reasons: List[Dict[str, Any]] = []
    hist = r.get("failure_histogram") or {}
    if isinstance(hist, dict):
        for key, count in sorted(hist.items(), key=lambda kv: -_i(kv[1])):
            if not _i(count):
                continue
            reasons.append(
                {
                    "key": key,
                    "label": _CONSTRAINT_PLAIN.get(str(key), str(key).replace("_", " ").title()),
                    "count": _i(count),
                    "detail": f"{_i(count):,} layout(s) rejected",
                }
            )
            if len(reasons) >= max_reasons:
                break

    # Near-miss metric detail if histogram empty
    if not reasons:
        m = best.get("metrics") or {}
        hm = best.get("human_metrics") or {}
        for key, label in (
            ("coverage_247_failures", "24/7 Coverage"),
            ("extra_window_failures", "Extra Windows"),
            ("gap_events", "Coverage Gaps"),
            ("rest_failures", "Rest / Fatigue"),
            ("annual_band_outside", "Annual Hours"),
            ("night_risk_gaps", "High-Risk Night Soft"),
        ):
            n = m.get(key)
            if n is None:
                n = hm.get(key)
            if n and _i(n) > 0:
                reasons.append(
                    {
                        "key": key,
                        "label": label,
                        "count": _i(n),
                        "detail": f"{_i(n)} event(s) on best / near-miss",
                    }
                )
        if best and not best.get("hard_constraints_ok"):
            for d in near_miss_deltas(best)[:4]:
                reasons.append(
                    {
                        "key": "near_miss",
                        "label": "Near-Miss",
                        "count": 1,
                        "detail": str(d),
                    }
                )

    unlocks: List[Dict[str, Any]] = []
    for s in suggest_relaxations(r, c)[:max_unlocks]:
        unlocks.append(
            {
                "action": s.get("action") or "",
                "why": s.get("why") or "",
                "category": s.get("category") or "general",
                "estimated_unlock": bool(s.get("estimated_unlock")),
                "delta": s.get("delta") or "",
            }
        )
    if not unlocks:
        for tip in suggest_unlocks(r)[:max_unlocks]:
            unlocks.append(
                {
                    "action": tip,
                    "why": "",
                    "category": "general",
                    "estimated_unlock": False,
                    "delta": "",
                }
            )

    near = r.get("near_misses") or []
    evals = _i(r.get("scenarios_evaluated"), 0)
    rejected = evals  # layouts ruled out ≈ evaluated when none hard-OK

    if hard_ok:
        summary = "Hard constraints met — optional narrowers only."
    elif reasons:
        top = reasons[0]
        summary = f"No hard match. Top reject: {top['label']} ({top['count']:,})."
    else:
        summary = "No hard match. Review unlocks below or soften constraints."

    return {
        "summary": summary,
        "hard_ok": hard_ok,
        "impossible": impossible and not hard_ok,
        "reasons": reasons[:max_reasons],
        "unlocks": unlocks[:max_unlocks],
        "near_miss_count": len(near),
        "layouts_checked": evals,
        "rejected": rejected,
    }


def format_autopsy_lines(autopsy: Optional[Dict[str, Any]] = None, *, max_lines: int = 12) -> List[str]:
    """Plain text lines for Why / summary panels."""
    a = autopsy or {}
    lines: List[str] = []
    if a.get("summary"):
        lines.append(str(a["summary"]))
    for r in a.get("reasons") or []:
        lines.append(f"· {r.get('label')}: {r.get('detail') or r.get('count')}")
        if len(lines) >= max_lines:
            return lines
    if a.get("unlocks"):
        lines.append("Top unlocks:")
        for u in a["unlocks"]:
            act = u.get("action") or ""
            why = u.get("why") or ""
            mark = "✓ likely" if u.get("estimated_unlock") else "try"
            lines.append(f"  [{mark}] {act}" + (f" — {why}" if why else ""))
            if len(lines) >= max_lines:
                break
    if a.get("near_miss_count"):
        lines.append(f"Closest alternatives: {a['near_miss_count']}")
    return lines[:max_lines]


def autopsy_and_strip(
    result: Optional[Dict[str, Any]] = None,
    form: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Convenience for tests / callers."""
    return constraint_autopsy(result, form or {}), cheap_feasibility_strip(form)
