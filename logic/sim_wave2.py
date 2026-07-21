"""Wave-2 simulator insights: Pareto, counterfactuals, fatigue, FLSA meters, what-if.

Product law: hard feasibility first. All functions here are soft / UI / seed helpers.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

# LE §7(k) proportional thresholds (hours) for common work periods — legal OT, not wellness.
_FLSA_LE_THRESH = {7: 43, 8: 49, 9: 54, 10: 60, 14: 86, 15: 91, 21: 129, 28: 171}


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


def flsa_threshold_hours(period_days: int) -> float:
    d = max(7, min(28, int(period_days or 28)))
    if d in _FLSA_LE_THRESH:
        return float(_FLSA_LE_THRESH[d])
    return round(171.0 * d / 28.0, 1)


def multi_period_flsa_meters(
    *,
    shift_length_hours: float,
    duty_fraction: float,
    periods: Sequence[int] = (7, 14, 28),
) -> List[Dict[str, Any]]:
    """Soft legal OT threshold meters for several §7(k) work periods."""
    length = max(0.0, _f(shift_length_hours, 8.0))
    frac = max(0.0, min(1.0, _f(duty_fraction, 0.5)))
    out = []
    for p in periods:
        pd = max(7, min(28, int(p)))
        thresh = flsa_threshold_hours(pd)
        hours = round(length * frac * pd, 1)
        pct = round(100.0 * hours / max(thresh, 1.0), 1)
        out.append(
            {
                "period_days": pd,
                "threshold_hours": thresh,
                "est_hours": hours,
                "pct": pct,
                "over": pct > 100.0,
                "label": f"{pd}d",
                "detail": f"~{hours:g}h / {thresh:g}h legal OT threshold ({pct:.0f}%)",
            }
        )
    return out


def fatigue_advisory(row: Dict[str, Any]) -> Dict[str, Any]:
    """Soft fatigue signals from LE wellness literature — not hard gates.

    Heuristics: consecutive ON from pattern blocks, night load, quick-turn risk.
    """
    signals: List[Dict[str, Any]] = []
    score = 100.0  # higher = better (less fatigue risk)
    m = row.get("metrics") or {}
    vars_ = row.get("rotation_variations") or []
    length = _f(row.get("shift_length_hours") or m.get("shift_length_hours"), 8.0)

    # Longest ON block from multi-block text
    longest_on = 0
    try:
        from logic.rotation_patterns import parse_on_off_blocks

        for t in vars_ if isinstance(vars_, (list, tuple)) else []:
            try:
                blocks = parse_on_off_blocks(str(t))
                for b in blocks:
                    longest_on = max(longest_on, int(b.days_on))
            except Exception:
                continue
    except Exception:
        pass
    if longest_on >= 6:
        score -= 15
        signals.append(
            {
                "key": "long_on_block",
                "level": "warn",
                "detail": f"Longest ON block {longest_on}d — wellness lit often caps ~5–7 consecutive",
            }
        )
    elif longest_on > 0:
        signals.append(
            {
                "key": "on_block",
                "level": "ok",
                "detail": f"Longest ON block {longest_on}d",
            }
        )

    # 12h caution (soft)
    if length >= 12:
        score -= 10
        signals.append(
            {
                "key": "long_shift",
                "level": "warn",
                "detail": f"{length:g}h shifts — monitor fatigue if used routinely (soft advisory)",
            }
        )
    elif 9.5 <= length <= 10.5:
        signals.append(
            {
                "key": "ten_hour",
                "level": "ok",
                "detail": f"{length:g}h — often cited as balanced for patrol (example, not default)",
            }
        )

    rest_fails = _i(m.get("rest_failures"), 0)
    consec_fails = _i(m.get("consecutive_work_failures"), 0)
    if rest_fails:
        score -= min(25, rest_fails * 5)
        signals.append({"key": "rest", "level": "warn", "detail": f"{rest_fails} rest-gap event(s) in sim"})
    if consec_fails:
        score -= min(25, consec_fails * 5)
        signals.append({"key": "consec", "level": "warn", "detail": f"{consec_fails} max-consecutive breach(es)"})

    try:
        from logic.soft_rank import night_weekend_balance

        bal = night_weekend_balance(row)
        nsp = _f(bal.get("night_load_spread"), 0)
        if nsp >= 4:
            score -= min(20, nsp * 2)
            signals.append(
                {
                    "key": "night_spread",
                    "level": "warn",
                    "detail": f"Night load spread {nsp:.0f} work-days across officers",
                }
            )
    except Exception:
        pass

    # Early start soft (05:00-06:00)
    starts = row.get("shift_starts") or []
    if isinstance(starts, str):
        starts = [s.strip() for s in starts.split(",") if s.strip()]
    if any(str(s).startswith("05:") for s in starts):
        score -= 8
        signals.append(
            {
                "key": "early_start",
                "level": "warn",
                "detail": "Start near 05:00 can encroach on sleep (soft advisory)",
            }
        )

    score = max(0.0, min(100.0, round(score, 1)))
    return {
        "fatigue_score": score,
        "signals": signals,
        "summary": (
            f"Fatigue advisory {score:.0f}/100"
            + (f" · {sum(1 for s in signals if s.get('level') == 'warn')} caution(s)" if signals else "")
        ),
    }


def annotate_pareto_shortlist(ranked: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """P6: label non-dominated hard-OK options on axes min N, min OT, max fairness."""
    rows = [dict(r) for r in (ranked or [])]
    hard = [r for r in rows if r.get("hard_constraints_ok")]
    if not hard:
        for r in rows:
            r["pareto_labels"] = []
        return rows

    def n_of(r):
        return _i(r.get("num_officers"), 99)

    def ot_of(r):
        e = r.get("economics") or {}
        return _f(e.get("est_ot_hours_total"), 999.0)

    def fair_of(r):
        e = r.get("economics") or {}
        hm = r.get("human_metrics") or {}
        return _f(e.get("fairness_score") or hm.get("fairness_score") or r.get("soft_score"), 0.0)

    # Best values
    best_n = min(n_of(r) for r in hard)
    best_ot = min(ot_of(r) for r in hard)
    best_f = max(fair_of(r) for r in hard)

    for r in hard:
        labels = []
        if n_of(r) == best_n:
            labels.append("Pareto: min N")
        if ot_of(r) == best_ot:
            labels.append("Pareto: min OT")
        if fair_of(r) == best_f:
            labels.append("Pareto: max fairness")
        # Non-dominated check (N, OT minimize; fair maximize)
        dominated = False
        for o in hard:
            if o is r:
                continue
            if n_of(o) <= n_of(r) and ot_of(o) <= ot_of(r) and fair_of(o) >= fair_of(r):
                if n_of(o) < n_of(r) or ot_of(o) < ot_of(r) or fair_of(o) > fair_of(r):
                    dominated = True
                    break
        if not dominated and not labels:
            labels.append("Pareto: trade-off")
        r["pareto_labels"] = labels
        r["pareto_note"] = " · ".join(labels) if labels else ""

    for r in rows:
        if not r.get("hard_constraints_ok"):
            r["pareto_labels"] = []
            r["pareto_note"] = ""
    return rows


def soft_rank_delta(best: Dict[str, Any], second: Optional[Dict[str, Any]] = None) -> str:
    """P7: one-line why #1 beat #2 on soft axes."""
    if not best or not best.get("hard_constraints_ok"):
        return ""
    if not second or not second.get("hard_constraints_ok"):
        return best.get("soft_rank_note") or "Only hard-OK option"
    b_n, s_n = _i(best.get("num_officers")), _i(second.get("num_officers"))
    b_ot = _f((best.get("economics") or {}).get("est_ot_hours_total"))
    s_ot = _f((second.get("economics") or {}).get("est_ot_hours_total"))
    b_f = _f((best.get("economics") or {}).get("fairness_score") or best.get("soft_score"))
    s_f = _f((second.get("economics") or {}).get("fairness_score") or second.get("soft_score"))
    parts = []
    if b_n < s_n:
        parts.append(f"fewer officers ({b_n} vs {s_n})")
    elif b_n > s_n:
        parts.append(f"more officers ({b_n} vs {s_n}) for coverage softs")
    if b_ot + 0.5 < s_ot:
        parts.append(f"lower est OT ({b_ot:.0f}h vs {s_ot:.0f}h)")
    if b_f > s_f + 1:
        parts.append(f"higher fairness ({b_f:.0f} vs {s_f:.0f})")
    b_soft = _f(best.get("soft_score"))
    s_soft = _f(second.get("soft_score"))
    if b_soft and s_soft:
        parts.append(f"soft {b_soft:.0f} vs {s_soft:.0f}")
    if not parts:
        parts.append("similar soft trade-offs; tie-break by search score")
    return "Chose #1 over #2: " + "; ".join(parts[:4])


def counterfactual_unlocks(
    result: Optional[Dict[str, Any]] = None,
    config: Optional[Dict[str, Any]] = None,
    *,
    max_cards: int = 5,
) -> List[Dict[str, Any]]:
    """P7: minimal-change cards to flip near-miss → likely hard-OK."""
    from logic.optimizer_features import suggest_relaxations

    r = result or {}
    c = config or {}
    cards: List[Dict[str, Any]] = []

    # Prefer structured relaxations
    for s in suggest_relaxations(r, c)[:max_cards]:
        cards.append(
            {
                "action": s.get("action") or "",
                "why": s.get("why") or "",
                "delta": s.get("delta") or "",
                "estimated_unlock": bool(s.get("estimated_unlock")),
                "category": s.get("category") or "general",
                "kind": "relaxation",
            }
        )

    # Near-miss counterfactuals from metrics
    near = r.get("near_misses") or []
    best = r.get("best") if not (r.get("best") or {}).get("hard_constraints_ok") else None
    miss = best or (near[0] if near else None)
    if miss:
        m = miss.get("metrics") or {}
        n = _i(miss.get("num_officers") or c.get("num_officers") or c.get("officers"), 0)
        win = _i(m.get("extra_window_failures"), 0)
        c247 = _i(m.get("coverage_247_failures"), 0)
        if win > 0 and not any("window" in (x.get("category") or "") for x in cards):
            cards.append(
                {
                    "action": f"Raise N from {n} to {n + 1} (counterfactual)",
                    "why": f"Near-miss had {win} window shortfall(s); +1 officer often clears Fri/Sat peaks",
                    "delta": "+1 officer",
                    "estimated_unlock": win <= 4,
                    "category": "headcount",
                    "kind": "counterfactual",
                }
            )
        if c247 > 0:
            cards.append(
                {
                    "action": "Unlock 24/7 or raise N (counterfactual)",
                    "why": f"{c247} day(s) below 24/7 floor in near-miss",
                    "delta": "coverage_247 or +N",
                    "estimated_unlock": c247 <= 6,
                    "category": "coverage_247",
                    "kind": "counterfactual",
                }
            )

    # Dedup by action
    seen = set()
    out = []
    for card in cards:
        a = card.get("action") or ""
        if a in seen:
            continue
        seen.add(a)
        out.append(card)
        if len(out) >= max_cards:
            break
    return out


def whatif_sandbox(
    form: Optional[Dict[str, Any]] = None,
    *,
    delta_n: int = 0,
    delta_window_min: int = 0,
    delta_247: int = 0,
) -> Dict[str, Any]:
    """P10: cheap what-if without full 56d sim — strip + predicted unlock narrative."""
    from logic.constraint_autopsy import cheap_feasibility_strip

    base = dict(form or {})
    # Apply deltas
    n = _i(base.get("num_officers") or base.get("officers"), 0)
    if delta_n:
        n = max(0, n + int(delta_n))
        base["num_officers"] = n
        base["officers"] = n
        base["auto_min_officers"] = n < 1

    cov = _i(base.get("coverage_247") or base.get("cov247"), 0)
    if delta_247:
        cov = max(0, cov + int(delta_247))
        base["coverage_247"] = cov
        base["cov247"] = cov

    windows = base.get("extra_windows") or base.get("windows") or []
    if delta_window_min and isinstance(windows, list):
        new_wins = []
        for w in windows:
            if not isinstance(w, dict):
                new_wins.append(w)
                continue
            ww = dict(w)
            mn = _i(ww.get("min_officers") or ww.get("min"), 0)
            ww["min_officers"] = max(0, mn + int(delta_window_min))
            new_wins.append(ww)
        base["extra_windows"] = new_wins
        base["windows"] = new_wins

    strip = cheap_feasibility_strip(base)
    narrative = []
    if delta_n:
        narrative.append(f"ΔN={delta_n:+d} → locked N={n or 'free'}")
    if delta_window_min:
        narrative.append(f"Δ window min={delta_window_min:+d}")
    if delta_247:
        narrative.append(f"Δ 24/7={delta_247:+d} → min {cov}")
    if strip.get("status") == "blocked":
        narrative.append("Still blocked by simultaneous body floor")
    elif strip.get("status") == "caution":
        narrative.append("Caution: may still fail full 56d hard search")
    else:
        narrative.append("Cheap strip looks open — Find Best still required for hard proof")

    # Predicted unlock (heuristic)
    unlock = None
    if strip.get("status") == "blocked" and strip.get("body_floor"):
        need = int(strip["body_floor"])
        if n and n < need:
            unlock = f"Raise N to ≥{need} (body floor) before Find Best"
        else:
            unlock = f"Lower 24/7 or peak window min (body floor {need})"
    elif strip.get("status") == "caution" and strip.get("roster_hint"):
        unlock = f"Consider N near roster hint ≥{strip['roster_hint']}"

    return {
        "success": True,
        "form": base,
        "strip": strip,
        "narrative": " · ".join(narrative),
        "predicted_unlock": unlock,
        "deltas": {"n": delta_n, "window_min": delta_window_min, "coverage_247": delta_247},
    }


def enrich_wave2_result(
    result: Optional[Dict[str, Any]] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Attach Pareto labels, rank delta, counterfactuals, fatigue on a search result."""
    r = dict(result or {})
    ranked = list(r.get("ranked") or [])
    # Ensure economics for Pareto OT/fairness
    try:
        from logic.staffing_insights import enrich_ranked_economics

        ranked = enrich_ranked_economics(ranked)
    except Exception:
        pass
    ranked = annotate_pareto_shortlist(ranked)
    for row in ranked:
        if row.get("hard_constraints_ok"):
            fat = fatigue_advisory(row)
            row["fatigue_advisory"] = fat
            row["fatigue_score"] = fat.get("fatigue_score")
            # Multi-period FLSA soft meters
            try:
                from logic.staffing_insights import duty_fraction_from_variations

                frac = duty_fraction_from_variations(row.get("rotation_variations") or [])
            except Exception:
                frac = 0.5
            length = _f(row.get("shift_length_hours"), 8.0)
            meters = multi_period_flsa_meters(shift_length_hours=length, duty_fraction=frac)
            row["flsa_period_meters"] = meters
            econ = dict(row.get("economics") or {})
            econ["flsa_period_meters"] = meters
            row["economics"] = econ

    r["ranked"] = ranked
    if ranked:
        r["best"] = ranked[0]
        second = ranked[1] if len(ranked) > 1 else None
        r["soft_rank_delta"] = soft_rank_delta(ranked[0], second)
        if ranked[0].get("pareto_note"):
            msg = r.get("message") or ""
            if "Pareto" not in msg:
                r["message"] = f"{msg} · {ranked[0]['pareto_note']}" if msg else ranked[0]["pareto_note"]

    hard_ok = any(x.get("hard_constraints_ok") for x in ranked)
    if not hard_ok or r.get("impossible"):
        r["counterfactual_unlocks"] = counterfactual_unlocks(r, config)
    else:
        r["counterfactual_unlocks"] = counterfactual_unlocks(r, config)  # still useful for near-misses
        if r.get("success") and r.get("best") and r.get("soft_rank_delta"):
            # Keep delta for explain
            pass

    # Pareto champions index
    champs = {"min_n": None, "min_ot": None, "max_fairness": None}
    for row in ranked:
        labs = row.get("pareto_labels") or []
        if "Pareto: min N" in labs:
            champs["min_n"] = row.get("rank")
        if "Pareto: min OT" in labs:
            champs["min_ot"] = row.get("rank")
        if "Pareto: max fairness" in labs:
            champs["max_fairness"] = row.get("rank")
    r["pareto_champions"] = champs
    return r
