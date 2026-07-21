"""End-of-search narrowers + stage lock/unlock actions.

Product law: Find Best finds **feasible** schedules from entered constraints.
FLSA, certifications, fatigue, fairness, heatmaps, composite scores are
**optional later filters** among plans that already work — not primary search.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence


def _metrics(row: Dict[str, Any]) -> Dict[str, Any]:
    m = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
    hm = row.get("human_metrics") if isinstance(row.get("human_metrics"), dict) else {}
    # Prefer explicit metrics; fill gaps from human_metrics
    out = dict(hm)
    out.update(m)
    return out


def row_flsa_ok(row: Dict[str, Any]) -> bool:
    m = _metrics(row)
    return int(m.get("flsa_violations") or 0) == 0


def row_fatigue_ok(row: Dict[str, Any], *, min_rest: float = 0.0, max_consec: int = 0) -> bool:
    """Soft check using metrics already computed on the sim (no re-sim)."""
    m = _metrics(row)
    if min_rest > 0 and int(m.get("rest_failures") or 0) > 0:
        return False
    if max_consec > 0 and int(m.get("consecutive_work_failures") or 0) > 0:
        return False
    return True


def row_cert_note(row: Dict[str, Any], required: Sequence[str]) -> str:
    """Certs are a publish/fill gate — options do not assign named officers.

    Returns empty if no codes; otherwise a note that certs apply at publish.
    """
    codes = [c.strip() for c in (required or []) if (c or "").strip()]
    if not codes:
        return ""
    return (
        f"At publish/fill: prefer officers with {', '.join(codes)}. Staffing search does not assign named roster certs."
    )


def filter_ranked(
    ranked: Optional[Sequence[Dict[str, Any]]] = None,
    *,
    require_flsa_clean: bool = False,
    require_fatigue_ok: bool = False,
    min_rest_hours: float = 0.0,
    max_consecutive_work_days: int = 0,
    required_certs: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Filter already-found options. Does not re-run the optimizer.

    Certs never drop rows (no named officers on sim slots) — they attach a note.
    """
    rows = [r for r in (ranked or []) if isinstance(r, dict)]
    dropped: List[Dict[str, Any]] = []
    kept: List[Dict[str, Any]] = []
    cert_note = row_cert_note({}, required_certs or [])

    for r in rows:
        row = dict(r)
        reasons: List[str] = []
        if require_flsa_clean and not row_flsa_ok(row):
            reasons.append("flsa")
        if require_fatigue_ok and not row_fatigue_ok(
            row,
            min_rest=float(min_rest_hours or 0),
            max_consec=int(max_consecutive_work_days or 0),
        ):
            reasons.append("fatigue")
        if reasons:
            dropped.append({"row": row, "reasons": reasons})
            continue
        if cert_note:
            hm = dict(row.get("human_metrics") or {})
            hm["cert_publish_note"] = cert_note
            row["human_metrics"] = hm
            row["cert_publish_note"] = cert_note
        kept.append(row)

    # Re-rank 1..n for display
    for i, row in enumerate(kept, 1):
        row["rank"] = i

    return {
        "success": True,
        "ranked": kept,
        "dropped": dropped,
        "kept_count": len(kept),
        "dropped_count": len(dropped),
        "cert_note": cert_note,
        "filters": {
            "require_flsa_clean": bool(require_flsa_clean),
            "require_fatigue_ok": bool(require_fatigue_ok),
            "required_certs": list(required_certs or []),
        },
        "message": (
            f"Showing {len(kept)} of {len(rows)} option(s)"
            + (f" · hid {len(dropped)} by end filters" if dropped else "")
            + (f" · {cert_note}" if cert_note and kept else "")
        ),
    }


def suggest_lock_actions(
    stage_report: Optional[Sequence[Dict[str, Any]]] = None,
    stage_tips: Optional[Sequence[str]] = None,
    *,
    current: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Actionable lock/unlock chips from stage report (for faster re-search)."""
    cur = current or {}
    actions: List[Dict[str, Any]] = []
    seen = set()

    def _add(aid: str, label: str, patch: Dict[str, Any], why: str = "") -> None:
        if aid in seen:
            return
        seen.add(aid)
        actions.append({"id": aid, "label": label, "form_patch": patch, "why": why})

    # From current free dims / tips heuristics
    tips = list(stage_tips or [])
    tip_blob = " ".join(tips).lower()

    n_counts = cur.get("officer_counts") or []
    if isinstance(n_counts, list) and len(n_counts) > 1:
        mid = sorted(int(x) for x in n_counts)[len(n_counts) // 2]
        _add(
            "lock_n_mid",
            f"Lock officers = {mid}",
            {"use_officers": True, "officers": str(mid)},
            "Fewer headcounts → much faster re-search",
        )
        lo, hi = min(int(x) for x in n_counts), max(int(x) for x in n_counts)
        _add(
            "lock_n_hi",
            f"Lock officers = {hi}",
            {"use_officers": True, "officers": str(hi)},
            "Upper end of viable range after stages",
        )
        if lo != hi:
            _add(
                "lock_n_lo",
                f"Try lean N = {lo}",
                {"use_officers": True, "officers": str(lo)},
                "Lowest N that survived body floors",
            )

    lengths = cur.get("length_opts") or cur.get("shift_length_options") or []
    if isinstance(lengths, list) and len(lengths) > 1:
        L0 = float(lengths[0])
        _add(
            "lock_len",
            f"Lock shift length = {L0:g}h",
            {"use_length": True, "length": str(L0)},
            "Free lengths explode search space",
        )

    if cur.get("free_starts") or "starts still free" in tip_blob or "start packs" in tip_blob:
        _add(
            "lock_starts_8",
            "Lock starts 06:00 / 14:00 / 22:00",
            {"use_starts": True, "starts": "06:00, 14:00, 22:00"},
            "Locked packs are far faster than free half-hour search",
        )

    if "many officer" in tip_blob or "officer counts free" in tip_blob:
        _add(
            "advise_n_range",
            "Tip: pick a smaller free-N range",
            {},
            "Use Small/Medium presets or Custom lo–hi before Find Best",
        )

    # Stage-specific reasons
    for st in stage_report or []:
        if not isinstance(st, dict):
            continue
        sid = str(st.get("stage_id") or "")
        after = st.get("after") or {}
        if sid == "coverage_247" and int(after.get("officer_counts") or 0) == 1:
            _add(
                "lock_n_single",
                "Only one N survived 24/7 — lock it",
                {},
                "Re-run with that officer count locked",
            )
        for t in list(st.get("tips") or [])[:1]:
            if "lock" in str(t).lower() and len(actions) < 8:
                _add(f"tip_{sid}", str(t)[:80], {}, str(t))

    return actions[:10]


def failure_recovery_options(
    opt_result: Optional[Dict[str, Any]] = None,
    *,
    flsa_enabled_in_form: bool = False,
) -> List[Dict[str, str]]:
    """Last-resort options when Find Best finds no hard-OK plan.

    Kelly / FLSA work-period tweaks are recovery suggestions only — not search
    constraints and not payroll pay-period changes.
    """
    r = opt_result or {}
    if r.get("success") and (r.get("best") or {}).get("hard_constraints_ok"):
        return []
    hist = r.get("failure_histogram") or {}
    tips: List[Dict[str, str]] = []
    if int(hist.get("window") or 0) or int(hist.get("coverage_247") or 0):
        tips.append(
            {
                "id": "raise_n",
                "action": "Raise officer count by 1–2 and re-search",
                "why": "Coverage floors often need one more body on thin multi-block days.",
            }
        )
        tips.append(
            {
                "id": "lower_window",
                "action": "Lower peak window min by 1 (or shorten the window)",
                "why": "Peak Fri/Sat nights drive headcount more than average FTE.",
            }
        )
    if int(hist.get("annual") or 0):
        tips.append(
            {
                "id": "widen_annual",
                "action": "Widen annual ±variance or unlock annual hard band",
                "why": "Cycle length rarely divides the year evenly — band, not exact hours.",
            }
        )
    if int(hist.get("flsa") or 0) or flsa_enabled_in_form:
        tips.append(
            {
                "id": "flsa_period",
                "action": "Try a different FLSA work-period length (7–28) as an end filter only",
                "why": (
                    "FLSA §207(k) period is independent of rotation cycle length and of "
                    "payroll pay periods elsewhere. Does not change Find Best constraints."
                ),
            }
        )
        tips.append(
            {
                "id": "kelly_style",
                "action": "Consider Kelly-style day-off inserts only after feasibility is close",
                "why": "Last-resort hours reduction when rotation is otherwise fixed — not a default search stage.",
            }
        )
    if not tips:
        tips.append(
            {
                "id": "lock_dims",
                "action": "Lock shift length and starts, free only officer count",
                "why": "Smaller free space finds viable plans faster.",
            }
        )
    return tips


def export_constraint_report(
    opt_result: Optional[Dict[str, Any]] = None,
    *,
    selected: Optional[Dict[str, Any]] = None,
) -> str:
    """Human-readable constraint / options report for command staff (text)."""
    r = opt_result or {}
    lines: List[str] = [
        "Chronos Command — staffing search report",
        "=" * 48,
        f"Message: {r.get('message') or '—'}",
        f"Architecture: {(r.get('constraints_applied') or {}).get('search_architecture') or '—'}",
        f"Layouts checked: {r.get('scenarios_evaluated') or 0}",
        f"Full sims: {r.get('full_sims_run') or 0}",
        f"Hard options kept: {r.get('scenarios_kept') or 0}",
        "",
        "Feasibility stages:",
    ]
    for st in r.get("stage_report") or []:
        if not isinstance(st, dict):
            continue
        lines.append(
            f"  [{('ok' if st.get('ok') else 'weak')}] {st.get('title')}: "
            f"N {(st.get('before') or {}).get('officer_counts')}→{(st.get('after') or {}).get('officer_counts')} · "
            f"L {(st.get('before') or {}).get('length_opts')}→{(st.get('after') or {}).get('length_opts')}"
        )
        for t in list(st.get("tips") or [])[:2]:
            lines.append(f"      · {t}")
    lines.append("")
    lines.append("Ranked options (human metrics — not composite score):")
    for row in (r.get("ranked") or [])[:12]:
        if not isinstance(row, dict):
            continue
        m = row.get("human_metrics") or row.get("metrics") or {}
        lines.append(
            f"  #{row.get('rank')}: N={row.get('num_officers')} · "
            f"L={row.get('shift_length_hours')}h · "
            f"starts={','.join(row.get('shift_starts') or [])} · "
            f"hard={row.get('hard_constraints_ok')} · "
            f"247_fail={m.get('coverage_247_failures')} · "
            f"win_fail={m.get('extra_window_failures')} · "
            f"gaps={m.get('zero_staff_gaps') or m.get('gap_events')}"
        )
    if selected:
        lines.append("")
        lines.append(f"Selected: {selected.get('summary') or selected.get('rank')}")
    for fr in failure_recovery_options(r):
        lines.append(f"Recovery: {fr.get('action')} — {fr.get('why')}")
    lines.append("")
    lines.append(
        "Note: FLSA / certs / fatigue / fairness are optional later filters among "
        "working plans — not the primary search objective."
    )
    return "\n".join(lines)


def publish_readiness(state_like: Dict[str, Any]) -> Dict[str, Any]:
    """Honest publish residual: what is missing before implement."""
    selected = state_like.get("selected_row") or state_like.get("best")
    ranked = state_like.get("ranked") or []
    opt = state_like.get("opt_result") or {}
    gaps: List[str] = []
    if not selected and not (opt.get("best") or ranked):
        gaps.append("No coverage option selected — run Find Best and pick an option.")
    elif not selected and (opt.get("best") or ranked):
        gaps.append("An option exists but none is selected — click an Option card first.")
    if selected and not selected.get("hard_constraints_ok", True):
        gaps.append(
            "Selected option did not meet hard constraints — publish may still run, but coverage shortfalls remain."
        )
    cert_note = (selected or {}).get("cert_publish_note") or (
        ((selected or {}).get("human_metrics") or {}).get("cert_publish_note")
    )
    if cert_note:
        gaps.append(str(cert_note))
    ok = not any("No coverage" in g or "none is selected" in g for g in gaps)
    return {
        "ready": ok and bool(selected or opt.get("best")),
        "gaps": gaps,
        "message": (
            "Ready to publish."
            if ok and (selected or opt.get("best"))
            else (" · ".join(gaps) if gaps else "Not ready.")
        ),
        "has_selection": bool(selected),
    }
