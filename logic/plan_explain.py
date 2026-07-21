"""
Coverage plan narratives for supervisors.

Optimizer scores rank options internally (best first). Primary text is
human options + step chains — not raw scores or weight formulas.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def explain_score_weights(policy: Optional[Dict[str, Any]] = None) -> str:
    """Diagnostic-only soft-score formula (not shown in primary UI)."""
    p = policy or {}
    w_j = p.get("w_junior", "w_junior")
    w_s = p.get("w_spare_capacity", "w_spare")
    w_same = p.get("w_same_start", "w_same")
    w_depth = p.get("w_shallow_chain", "w_shallow")
    return (
        "Internal rank (higher better) ≈ "
        f"{w_j}×seniority_rank(junior-first) + "
        f"{w_s}×spare_bump_slots + "
        f"{w_same}×same_shift_band + "
        f"{w_depth}×(max_depth − chain_length)\n"
        "Hard gates: squad match, working that day, cover-allowed band, "
        "rest gap, consecutive-work limit, certs, max bump assignments."
    )


def explain_replacement_components(
    officer: Dict[str, Any],
    *,
    policy: Optional[Dict[str, Any]] = None,
    assignment_used: int = 0,
    same_band: bool = True,
) -> str:
    """Diagnostic one-line for a candidate (tests / debug)."""
    p = policy or {}
    try:
        w_j = float(p.get("w_junior", 1.0))
        w_s = float(p.get("w_spare_capacity", 1.0))
        w_same = float(p.get("w_same_start", 1.0))
        max_bump = int(p.get("max_bump_assignments", 2) or 2)
    except (TypeError, ValueError):
        w_j, w_s, w_same, max_bump = 1.0, 1.0, 1.0, 2
    rank = int(officer.get("seniority_rank") or 0)
    spare = max(0, max_bump - assignment_used)
    same = 1.0 if same_band else 0.0
    total = w_j * rank + w_s * spare + w_same * same
    name = officer.get("name") or officer.get("id") or "?"
    return f"{name}: internal_rank={total:.1f} [junior={w_j}×{rank}; spare={w_s}×{spare}; same_band={w_same}×{same:g}]"


_CONSTRAINT_PLAIN = {
    "coverage_247": "24/7 Coverage",
    "windows": "Extra Windows",
    "gaps": "Min Per Shift",
    "flsa": "FLSA OT",
    "annual": "Annual Hours",
}


def explain_ranked_option(row: Optional[Dict[str, Any]] = None) -> List[str]:
    """Plain-language lines for one staffing option card (no raw scores)."""
    r = row or {}
    lines: List[str] = []
    if r.get("summary"):
        lines.append(str(r["summary"]))
    starts = r.get("shift_starts") or r.get("starts")
    if starts:
        if isinstance(starts, (list, tuple)):
            lines.append("Starts: " + ", ".join(str(s) for s in starts))
        else:
            lines.append(f"Starts: {starts}")
    vars_ = r.get("rotation_variations") or []
    if vars_:
        lines.append("Multi-Block: " + " | ".join(str(v) for v in vars_))
    length = r.get("shift_length_hours")
    if length is not None:
        lines.append(f"Shift Length: {length:g}h" if isinstance(length, float) else f"Shift Length: {length}h")
    hm = r.get("human_metrics") or {}
    m = r.get("metrics") or {}
    hard = r.get("hard_constraints_ok")
    if hard is None:
        hard = hm.get("hard_constraints_ok")
    if hard is not None:
        lines.append("Hard Constraints: " + ("Met" if hard else "Not Met"))
    failed = r.get("failed_constraints") or hm.get("failed_constraints") or []
    if failed:
        labels = [_CONSTRAINT_PLAIN.get(k, k) for k in failed]
        lines.append("Misses: " + ", ".join(labels))
    avg = hm.get("annual_hours_delta")
    if avg is None and m.get("avg_annual_hours") is not None:
        lines.append(f"Avg Annual Hours: {float(m['avg_annual_hours']):.0f}")
    elif avg is not None and float(avg) >= 1:
        lines.append(f"Annual Mean Off Target: ~{float(avg):.0f}h")
    for label, key in (
        ("24/7 Short", "coverage_247_failures"),
        ("Window Short", "extra_window_failures"),
        ("Coverage Gaps", "zero_staff_gaps"),
    ):
        n = hm.get(key)
        if n is None and key == "zero_staff_gaps":
            n = m.get("gap_events") or m.get("zero_staff_slots")
        if n is None:
            n = m.get(key)
        if n and int(n) > 0:
            lines.append(f"{label}: {int(n)}")
    # Cost / FLSA / fairness (from staffing_insights enrichment)
    econ = r.get("economics") or {}
    if econ.get("est_ot_hours_total") is not None:
        lines.append(f"Est. OT Hours: {econ['est_ot_hours_total']}")
    if econ.get("est_ot_cost_usd") is not None:
        lines.append(f"Est. OT Cost: ${econ['est_ot_cost_usd']}")
    if econ.get("flsa_period_pct") is not None:
        lines.append(
            f"FLSA Period Load: {econ['flsa_period_pct']}% of {econ.get('flsa_threshold_hours', 171)}h threshold"
        )
    if econ.get("fairness_score") is not None:
        lines.append(f"Fairness Score: {econ['fairness_score']}/100")
    elif hm.get("fairness_score") is not None:
        lines.append(f"Fairness Score: {hm['fairness_score']}/100")
    if econ.get("force_cash_ot_path") or hm.get("force_cash_ot_path"):
        cap = econ.get("comp_cap_hours") or hm.get("comp_cap_hours") or 480
        lines.append(f"Comp bank near FLSA cap ({cap:g}h) — prefer cash OT path")
    elif econ.get("comp_headroom_hours") is not None:
        lines.append(f"Comp headroom ≈ {econ['comp_headroom_hours']}h (cap {econ.get('comp_cap_hours', 480):g}h)")
    return lines


def explain_staffing_result(result: Optional[Dict[str, Any]] = None) -> List[str]:
    """Plain-language why a staffing search result is best / near-miss."""
    from logic.optimizer_features import (
        format_checklist_line,
        headcount_banner,
        near_miss_deltas,
        suggest_unlocks,
        why_best_lines,
    )

    r = result or {}
    lines: List[str] = []
    if r.get("impossible"):
        lines.append("No Schedule Meets Selected Hard Constraints")
    elif r.get("success") and r.get("best"):
        lines.append(r.get("message") or "Best Option: Meets Selected Constraints")
        if "Best Option" not in (lines[0] or "") and r.get("success"):
            lines.insert(0, "Best Option: Meets Selected Constraints")
    else:
        lines.append(r.get("message") or "Search Finished Without A Perfect Match")
    banner = headcount_banner(r)
    if banner:
        lines.append(banner)
    evals = r.get("scenarios_evaluated")
    if evals is not None:
        # Title Case — Chronos summary + Playwright assert "Layouts Checked"
        lines.append(f"Layouts Checked: {int(evals):,}")
        lines.append(f"Combinations Tried: {int(evals):,}")
    # Honest search mode (do not claim exhaustive when truncated / anytime)
    mode = (r.get("constraints_applied") or {}).get("search_mode") or r.get("search_mode")
    if r.get("search_exhaustive") is True:
        mode_label = "Exhaustive"
    elif r.get("budget_exhausted"):
        mode_label = "Anytime (time limit)"
    elif r.get("search_truncated"):
        mode_label = "Partial (not every layout)"
    elif mode:
        mode_label = str(mode).replace("_", " ").title()
    else:
        mode_label = None
    if mode_label:
        lines.append(f"Search Mode: {mode_label}")
    full_n = r.get("full_sims_run")
    if full_n is not None:
        lines.append(f"Full Simulations: {int(full_n):,}")
    pruned = r.get("pruned_cheap")
    if pruned is not None:
        lines.append(f"Pruned Impossible: {int(pruned):,}")
    wall = r.get("wall_time_ms")
    if wall is not None:
        lines.append(f"Search Time: {int(wall)} ms")
    best = r.get("best") or {}
    if best:
        lines.append(format_checklist_line(best))
        lines.extend(explain_ranked_option(best)[:6])
        rank = best.get("rank")
        if rank is not None:
            lines.append(f"Best Option: #{rank}")
        if not best.get("hard_constraints_ok"):
            deltas = near_miss_deltas(best)
            if deltas:
                lines.append("Missed By:")
                lines.extend(f"  · {d}" for d in deltas[:6])
    hist = r.get("failure_histogram") or {}
    if hist:
        top = sorted(
            ((k, v) for k, v in hist.items() if v),
            key=lambda x: -x[1],
        )[:4]
        if top:
            lines.append("Top Reject Reasons: " + ", ".join(f"{_CONSTRAINT_PLAIN.get(k, k)}×{v}" for k, v in top))
    near = r.get("near_misses") or []
    if near and not (r.get("success") and r.get("best")):
        lines.append(f"Closest Alternatives: {len(near)}")
        if near:
            for d in near_miss_deltas(near[0])[:4]:
                lines.append(f"  · {d}")
    kept = r.get("scenarios_kept")
    if kept is not None and r.get("success"):
        lines.append(f"Options Kept: {int(kept)}")
    if r.get("impossible") or not r.get("success"):
        # Structured autopsy (WFM gap-board / explain-score style)
        try:
            from logic.constraint_autopsy import constraint_autopsy, format_autopsy_lines

            auto = constraint_autopsy(r, r.get("constraints_applied") or {})
            alines = format_autopsy_lines(auto, max_lines=10)
            if alines:
                lines.append("Constraint Autopsy:")
                lines.extend(alines)
            else:
                for s in suggest_unlocks(r)[:4]:
                    lines.append(f"Tip: {s}")
        except Exception:
            for s in suggest_unlocks(r)[:4]:
                lines.append(f"Tip: {s}")
    if r.get("success") and r.get("best"):
        why = why_best_lines(r)
        if why:
            lines.append("Why #1:")
            lines.extend(f"  {w}" for w in why[:5])
        best = r.get("best") or {}
        if best.get("soft_rank_note") or best.get("soft_score") is not None:
            lines.append(
                "Soft rank (among hard-OK): " + (best.get("soft_rank_note") or f"score {best.get('soft_score')}")
            )
        sr = r.get("soft_rank") or {}
        if sr.get("message") and sr.get("message") not in "\n".join(lines):
            lines.append(str(sr["message"]))
    return lines


def format_option_steps(plan: Dict[str, Any], option_num: int) -> List[str]:
    """Plain-language lines for one ranked option (no scores)."""
    lines: List[str] = []
    ok = plan.get("success")
    manual = plan.get("requires_manual")
    msg = (plan.get("message") or "").strip()
    if ok:
        flag = "ready"
    elif manual:
        flag = "needs supervisor"
    else:
        flag = "not viable"
    if msg and msg.lower().startswith("option "):
        lines.append(f"{msg} ({flag})")
    else:
        n_steps = len(plan.get("steps") or plan.get("chain") or [])
        lines.append(f"Option {option_num}: {n_steps or '—'} move(s) ({flag})")
        if msg:
            lines.append(f"  {msg}")
    steps = plan.get("steps") or []
    if steps:
        for st in steps:
            if isinstance(st, dict):
                duty = st.get("on_duty")
                duty_bit = ""
                if duty is False:
                    duty_bit = " [off-duty call-in]"
                elif duty is True:
                    duty_bit = " [on duty]"
                lines.append(
                    f"  Step {st.get('step', '?')}: "
                    f"{st.get('replacement', '?')} covers {st.get('original', '?')} "
                    f"({st.get('from_shift', '?')} → {st.get('to_shift', '?')})"
                    f"{duty_bit}"
                )
            else:
                lines.append(f"  {st}")
    elif plan.get("chain"):
        chain = plan.get("chain") or []
        bits = []
        for pair in chain[:8]:
            if isinstance(pair, (list, tuple)) and len(pair) >= 2:
                bits.append(f"{pair[1]}→{pair[0]}")
            else:
                bits.append(str(pair))
        if bits:
            lines.append("  Chain: " + " · ".join(bits))
    if plan.get("failure_reason"):
        lines.append(f"  Reason: {plan['failure_reason']}")
    return lines


def explain_coverage_plans(
    payload: Dict[str, Any],
    *,
    include_diagnostics: bool = False,
) -> str:
    """Ranked options narrative for supervisors (best first). Scores omitted by default."""
    if not isinstance(payload, dict):
        return str(payload)
    if payload.get("success") is False:
        return payload.get("message") or "No viable plans"
    plans = payload.get("plans") or []
    if not plans:
        return payload.get("message") or "No plans returned"

    lines: List[str] = []
    n_ok = sum(1 for p in plans if isinstance(p, dict) and p.get("success"))
    lines.append(f"Ranked coverage options (best first) — {n_ok} ready of {len(plans)}")
    pol = payload.get("policy") or {}
    if pol:
        lines.append(
            f"Rules: min {pol.get('min_per_shift', pol.get('min_per_band', '—'))}/band · "
            f"night min {pol.get('night_minimum', '—')} · "
            f"max cascade {pol.get('max_cascade_depth', '—')}"
        )
    lines.append("")

    for i, plan in enumerate(plans, 1):
        if not isinstance(plan, dict):
            lines.append(f"Option {i}: {plan}")
            continue
        lines.extend(format_option_steps(plan, i))
        if include_diagnostics:
            comps = plan.get("score_components") or plan.get("penalties") or []
            if comps:
                lines.append("  [diagnostic rank components]")
                for c in comps[:8]:
                    if isinstance(c, dict):
                        lines.append(f"    · {c.get('name') or c.get('id')}: {c.get('value') or c.get('delta') or c}")
                    else:
                        lines.append(f"    · {c}")
        lines.append("")

    lines.append("Pick the option that fits staffing and fairness. Incomplete cascades need manual review.")
    if include_diagnostics and pol:
        lines.append("")
        lines.append(explain_score_weights(pol))
    return "\n".join(lines).strip()
