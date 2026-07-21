"""Staged feasibility search for staffing optimizer.

Priority (product law):
  1) Find schedules that meet **entered** constraints.
  2) Score / fairness / heatmap / FLSA / certs / fatigue are later optional
     narrowers — not early search drivers (unless the user enabled them as constraints).

Each stage co-reduces the free domain using prior stage results, emits short
tips (what to lock/unlock next), then hands a smaller axes dict to full sim.
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple


@dataclass
class StageOutcome:
    stage_id: str
    title: str
    ok: bool
    tips: List[str] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)
    before: Dict[str, int] = field(default_factory=dict)
    after: Dict[str, int] = field(default_factory=dict)


def _counts(axes: Dict[str, Any]) -> Dict[str, int]:
    return {
        "officer_counts": len(axes.get("officer_counts") or []),
        "length_opts": len(axes.get("length_opts") or []),
        "variation_sets": len(axes.get("variation_sets") or []),
        "rotation_types": len(axes.get("rotation_types") or []),
        "min_per_shift_options": len(axes.get("min_per_shift_options") or []),
    }


def _axis_snapshot(axes: Dict[str, Any]) -> str:
    c = _counts(axes)
    return (
        f"N×{c['officer_counts']} · L×{c['length_opts']} · patterns×{c['variation_sets']} · rot×{c['rotation_types']}"
    )


def multi_pattern_split_maps(n_slots: int, n_patterns: int = 2) -> List[List[int]]:
    """Explicit headcount splits for same-cycle multi-pattern assignment.

    Example (not a product rule): N=6, 2 patterns → maps with 4+2, 3+3, 5+1, …
    Phases remain independent (0…cycle_length−1) in the full search.
    """
    if n_slots < 1 or n_patterns < 1:
        return [[0] * max(n_slots, 0)]
    if n_patterns == 1:
        return [[0] * n_slots]
    maps: List[List[int]] = []
    seen = set()

    def _add(m: List[int]) -> None:
        key = tuple(int(x) % n_patterns for x in m)
        if key in seen:
            return
        seen.add(key)
        maps.append(list(key))

    # Round-robin + reverse
    _add([i % n_patterns for i in range(n_slots)])
    _add([(n_patterns - 1 - (i % n_patterns)) for i in range(n_slots)])
    # Every split size k officers on pattern 1, rest on 0
    if n_patterns == 2:
        for k in range(0, n_slots + 1):
            m = [0] * n_slots
            # pack first k on pattern 1
            for i in range(k):
                m[i] = 1
            _add(m)
            # pack last k on pattern 1
            m2 = [0] * n_slots
            for i in range(n_slots - k, n_slots):
                m2[i] = 1
            _add(m2)
            # interleave first k
            if 0 < k < n_slots:
                m3 = [0] * n_slots
                step = n_slots / k
                for j in range(k):
                    m3[int(j * step) % n_slots] = 1
                _add(m3)
    else:
        for i in range(n_slots):
            m = [i % n_patterns for _ in range(n_slots)]
            _add([((i + j) % n_patterns) for j in range(n_slots)])
    return maps


def _bodies_needed(length: float, coverage_247: int) -> int:
    if coverage_247 <= 0 or length <= 0:
        return 0
    bands = max(1, int(math.ceil(24.0 / float(length))))
    return bands * int(coverage_247)


def _window_floor(windows: Optional[Sequence[Dict]], *, use_windows: bool) -> int:
    if not use_windows or not windows:
        return 0
    floor = 0
    for w in windows:
        if not isinstance(w, dict) or w.get("enabled") is False:
            continue
        try:
            floor = max(floor, int(w.get("min_officers") or 0))
        except (TypeError, ValueError):
            continue
    return floor


def stage_officers_and_annual(
    axes: Dict[str, Any],
    *,
    annual: float,
    annual_variance: float,
    annual_hours_hard: bool,
    coverage_247: int,
    use_extra_windows: bool,
    extra_windows: Optional[List[Dict]],
) -> Tuple[Dict[str, Any], StageOutcome]:
    """Stage 1: headcount + shift length + annual band co-reduction."""
    out = copy.deepcopy(axes)
    before = _counts(out)
    tips: List[str] = []
    reasons: List[str] = []
    win_floor = _window_floor(extra_windows, use_windows=use_extra_windows)
    cov = max(0, int(coverage_247 or 0))

    lengths = [float(x) for x in (out.get("length_opts") or [8.0])]
    officers = [int(x) for x in (out.get("officer_counts") or [1])]

    # Drop lengths that cannot hit annual when annual is hard + multi-block known
    if annual_hours_hard and annual > 0:
        kept_L: List[float] = []
        from logic.rotation_patterns import build_pattern, projected_annual_hours

        style = (out.get("style") or "rotating").strip().lower()
        var_sets = out.get("variation_sets") or [[]]
        for L in lengths:
            ok_L = False
            for vs in var_sets:
                if not vs:
                    # squad path: keep length (annual checked in full sim)
                    ok_L = True
                    break
                try:
                    pats = [
                        build_pattern(t, style=style if style in ("fixed", "rotating") else None)
                        for t in vs
                        if (t or "").strip()
                    ]
                except ValueError:
                    continue
                if not pats:
                    ok_L = True
                    break
                hours = [projected_annual_hours(p, L) for p in pats]
                lo, hi = annual - annual_variance, annual + annual_variance
                if any(lo - 1e-6 <= h <= hi + 1e-6 for h in hours):
                    ok_L = True
                    break
            if ok_L:
                kept_L.append(L)
        if kept_L and len(kept_L) < len(lengths):
            reasons.append(f"annual band: lengths {len(lengths)}→{len(kept_L)}")
            out["length_opts"] = kept_L
            lengths = kept_L
            tips.append(
                f"Shift lengths that can hit ~{annual:.0f}h (±{annual_variance:.0f}) "
                f"kept: {', '.join(str(x) for x in kept_L[:8])}" + ("…" if len(kept_L) > 8 else "")
            )
        elif not kept_L and lengths:
            tips.append(
                "No shift length hits the annual band with current patterns — "
                "unlock annual variance or change multi-block patterns."
            )

    # Drop N that cannot meet concurrent body floors for any remaining length
    min_bodies = 0
    if lengths:
        min_bodies = min(_bodies_needed(L, cov) for L in lengths) if cov else 0
    min_bodies = max(min_bodies, win_floor)
    if min_bodies > 0:
        kept_n = [n for n in officers if n >= min_bodies]
        if kept_n and len(kept_n) < len(officers):
            reasons.append(f"body floor ≥{min_bodies}: officers {len(officers)}→{len(kept_n)}")
            out["officer_counts"] = sorted(set(kept_n))
            tips.append(
                f"Need at least {min_bodies} officers for "
                f"{'24/7 + ' if cov else ''}coverage floors at current lengths — "
                f"dropped lower headcounts."
            )
        elif not kept_n:
            tips.append(
                f"All officer counts are below the body floor ({min_bodies}). Raise N or lower 24/7 / window minimums."
            )
            # keep original so full search can still emit near-misses
        else:
            tips.append(f"Officer range OK for body floor ≥{min_bodies}.")
    else:
        tips.append("No concurrent body floor from 24/7/windows — headcount stays free.")

    if len(out.get("officer_counts") or []) > 6:
        tips.append("Many officer counts free — locking a range (or single N) speeds the next stages.")
    if len(out.get("length_opts") or []) > 4:
        tips.append("Many shift lengths free — locking length shrinks search a lot.")

    after = _counts(out)
    ok = after["officer_counts"] > 0 and after["length_opts"] > 0
    return out, StageOutcome(
        stage_id="officers_annual",
        title="Officers · annual · shift length",
        ok=ok,
        tips=tips,
        reasons=reasons,
        before=before,
        after=after,
    )


def stage_rotation_shape(
    axes: Dict[str, Any],
) -> Tuple[Dict[str, Any], StageOutcome]:
    """Stage 2: rotation style + same-cycle multi-block families."""
    out = copy.deepcopy(axes)
    before = _counts(out)
    tips: List[str] = []
    reasons: List[str] = []
    from logic.rotation_patterns import build_pattern

    style = (out.get("style") or "").strip().lower()
    var_sets = [list(vs) for vs in (out.get("variation_sets") or [[]])]
    kept: List[List[str]] = []
    for vs in var_sets:
        if not vs:
            kept.append(vs)
            continue
        cycles = []
        good = True
        for t in vs:
            try:
                p = build_pattern(t, style=style if style in ("fixed", "rotating") else None)
                cycles.append(int(p.cycle_length))
            except ValueError:
                good = False
                break
        if not good or not cycles:
            reasons.append(f"drop invalid set {vs!r}")
            continue
        # Same-cycle family only (product model)
        if len(set(cycles)) > 1:
            reasons.append(f"drop mixed cycle lengths {set(cycles)} in {vs}")
            tips.append(
                f"Skipped pattern set with mixed cycle lengths {sorted(set(cycles))} — "
                "officers must share one cycle length (different on/off patterns OK)."
            )
            continue
        kept.append(vs)
    if kept and len(kept) < len(var_sets):
        out["variation_sets"] = kept
        reasons.append(f"rotation sets {len(var_sets)}→{len(kept)}")
    elif not kept and var_sets:
        out["variation_sets"] = [[]]
        tips.append("No valid multi-block sets left — falling back to squad/preset duty.")

    multi = any(vs and any("," in str(x) for x in vs) for vs in (out.get("variation_sets") or []))
    if multi:
        tips.append(
            "Multi-block: officers share one cycle length; different day-on/day-off "
            "patterns can be mixed (e.g. some on 6-2,5-3 and others on 6-3,5-2). "
            "Phases stagger 0…cycle_length−1."
        )
        ns = out.get("officer_counts") or []
        if ns:
            n0 = int(ns[0])
            if n0 >= 4:
                tips.append(
                    f"With ~{n0} officers and 2 patterns, search will try headcount splits "
                    f"(e.g. {n0 - n0 // 3}+{n0 // 3}) — not a fixed rule."
                )
    else:
        tips.append("Squad/preset rotation path (no multi-block variation sets).")

    if style in ("fixed", "rotating"):
        tips.append(f"Rotation style locked: {style}.")
    else:
        tips.append("Rotation style free — locking Fixed or Rotating reduces pattern search.")

    after = _counts(out)
    return out, StageOutcome(
        stage_id="rotation",
        title="Rotation shape · multi-block family",
        ok=True,
        tips=tips,
        reasons=reasons,
        before=before,
        after=after,
    )


def stage_coverage_skeleton(
    axes: Dict[str, Any],
    *,
    coverage_247: int,
) -> Tuple[Dict[str, Any], StageOutcome]:
    """Stage 3: 24/7 concurrent body feasibility for N×length."""
    out = copy.deepcopy(axes)
    before = _counts(out)
    tips: List[str] = []
    reasons: List[str] = []
    cov = max(0, int(coverage_247 or 0))
    if cov <= 0:
        tips.append("24/7 continuous coverage is off — skeleton stage skipped.")
        return out, StageOutcome(
            stage_id="coverage_247",
            title="24/7 coverage skeleton",
            ok=True,
            tips=tips,
            before=before,
            after=_counts(out),
        )

    lengths = [float(x) for x in (out.get("length_opts") or [8.0])]
    officers = [int(x) for x in (out.get("officer_counts") or [])]
    viable_pairs = []
    for L in lengths:
        need = _bodies_needed(L, cov)
        ok_ns = [n for n in officers if n >= need]
        if ok_ns:
            viable_pairs.append((L, need, ok_ns))
    if not viable_pairs:
        tips.append(
            f"No N×length pair meets 24/7 min {cov} (need ceil(24/L)×{cov} bodies). Raise officers or lower 24/7 min."
        )
        return out, StageOutcome(
            stage_id="coverage_247",
            title="24/7 coverage skeleton",
            ok=False,
            tips=tips,
            reasons=["no viable N×L for 24/7"],
            before=before,
            after=_counts(out),
        )

    kept_L = sorted({p[0] for p in viable_pairs})
    kept_n = sorted({n for p in viable_pairs for n in p[2]})
    if len(kept_L) < len(lengths):
        reasons.append(f"24/7: lengths {len(lengths)}→{len(kept_L)}")
        out["length_opts"] = kept_L
    if len(kept_n) < len(officers):
        reasons.append(f"24/7: officers {len(officers)}→{len(kept_n)}")
        out["officer_counts"] = kept_n
    needs = sorted({p[1] for p in viable_pairs})
    tips.append(
        f"24/7 min {cov}: body floors by length → {needs}. "
        f"Kept N={kept_n[0]}…{kept_n[-1]} · L={kept_L[0]}…{kept_L[-1]}."
    )
    after = _counts(out)
    return out, StageOutcome(
        stage_id="coverage_247",
        title="24/7 coverage skeleton",
        ok=True,
        tips=tips,
        reasons=reasons,
        before=before,
        after=after,
    )


def stage_peak_windows(
    axes: Dict[str, Any],
    *,
    use_extra_windows: bool,
    extra_windows: Optional[List[Dict]],
) -> Tuple[Dict[str, Any], StageOutcome]:
    """Stage 4: peak window body floors (does not invent windows)."""
    out = copy.deepcopy(axes)
    before = _counts(out)
    tips: List[str] = []
    reasons: List[str] = []
    floor = _window_floor(extra_windows, use_windows=use_extra_windows)
    if floor <= 0:
        tips.append("No extra coverage windows — peak stage skipped.")
        return out, StageOutcome(
            stage_id="windows",
            title="Peak coverage windows",
            ok=True,
            tips=tips,
            before=before,
            after=_counts(out),
        )

    officers = [int(x) for x in (out.get("officer_counts") or [])]
    kept = [n for n in officers if n >= floor]
    if kept and len(kept) < len(officers):
        out["officer_counts"] = sorted(set(kept))
        reasons.append(f"window min {floor}: officers {len(officers)}→{len(kept)}")
        tips.append(f"Extra windows need ≥{floor} on duty in the peak band — headcounts below {floor} removed.")
    elif not kept:
        tips.append(f"All officer counts are below window min {floor}. Raise N or lower window minimums.")
    else:
        tips.append(f"Window floor {floor}: all remaining headcounts OK.")

    # Hint free starts
    if out.get("free_starts"):
        tips.append(
            "Starts still free — next stage builds half-hour packs that can cover window bands. "
            "Locking start times (e.g. 06:00/14:00/22:00) is much faster."
        )
    out["min_bands_hint"] = max(int(out.get("min_bands_hint") or 0), 2)
    out["filter_start_packs"] = True
    after = _counts(out)
    return out, StageOutcome(
        stage_id="windows",
        title="Peak coverage windows",
        ok=bool(out.get("officer_counts")),
        tips=tips,
        reasons=reasons,
        before=before,
        after=after,
    )


def stage_starts_and_assign_tips(
    axes: Dict[str, Any],
    *,
    coverage_247: int = 0,
    use_extra_windows: bool = False,
    extra_windows: Optional[List[Dict]] = None,
) -> Tuple[Dict[str, Any], StageOutcome]:
    """Stage 5: start-pack + phase/map tips; CP-SAT/heuristic seeds when available."""
    out = copy.deepcopy(axes)
    before = _counts(out)
    tips: List[str] = []
    reasons: List[str] = []
    if out.get("free_starts") or out.get("locked_starts_opts") is None:
        tips.append(
            "Start packs: half-hour LE-sane grids; search only packs that can cover 24/7/windows with remaining N."
        )
        try:
            from logic.staffing_cpsat import ortools_available, rank_start_packs_seed
            from logic.staffing_optimizer import generate_start_packs

            n0 = int((out.get("officer_counts") or [8])[0])
            L0 = float((out.get("length_opts") or [8.0])[0])
            raw_packs = generate_start_packs(
                L0,
                num_officers=n0,
                coverage_247=int(coverage_247 or 0),
                extra_windows=list(extra_windows or []) if use_extra_windows else None,
                max_packs=48,
            )
            if raw_packs:
                ranked = rank_start_packs_seed(
                    raw_packs[:40],
                    shift_length_hours=L0,
                    n_bodies=n0,
                    coverage_247=int(coverage_247 or 0),
                    extra_windows=extra_windows if use_extra_windows else None,
                    max_keep=8,
                )
                if ranked:
                    out["cpsat_start_pack_seeds"] = [list(p) for p in ranked]
                    reasons.append(f"start pack seeds {len(ranked)}")
                    eng = "CP-SAT" if ortools_available() else "heuristic"
                    tips.append(f"{eng} ranked {len(ranked)} start-pack seeds for full search.")
        except Exception:
            tips.append("Start-pack seed ranking skipped — full pack generator will run.")
    else:
        tips.append("Start times locked — pack catalog is a single given set.")
    multi = any(vs and any("," in str(x) for x in vs) for vs in (out.get("variation_sets") or []))
    if multi:
        tips.append(
            "Phase & pattern assignment: each officer phase ∈ [0, cycle_length). "
            "Pattern maps assign officers to different same-cycle on/off rings."
        )
        try:
            from logic.staffing_cpsat import ortools_available, suggest_joint_seed

            n0 = int((out.get("officer_counts") or [6])[0])
            joint = suggest_joint_seed(
                n_officers=n0,
                cycle_length=16,
                n_patterns=2,
                min_daily_on=max(1, int(coverage_247 or 0)),
            )
            if joint:
                out["cpsat_phase_seed"] = joint[0]
                out["cpsat_pattern_seed"] = joint[1]
                eng = "CP-SAT" if ortools_available() else "heuristic"
                tips.append(f"{eng} joint phase+pattern seed ready for multi-block assign.")
                reasons.append("joint phase/pattern seed")
        except Exception:
            pass
    tips.append(
        "Next: full simulation (56-day hard eval) only on candidates that survived "
        "these stages — feasibility first, not ranking score."
    )
    return out, StageOutcome(
        stage_id="starts_assign",
        title="Starts · phases · pattern maps",
        ok=True,
        tips=tips,
        reasons=reasons,
        before=before,
        after=_counts(out),
    )


def run_feasibility_stages(
    axes: Dict[str, Any],
    *,
    annual: float,
    annual_variance: float = 40.0,
    annual_hours_hard: bool = False,
    coverage_247: int = 0,
    use_extra_windows: bool = False,
    extra_windows: Optional[List[Dict]] = None,
    progress: Optional[Callable[[Dict[str, Any]], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> Tuple[Dict[str, Any], List[StageOutcome], List[str]]:
    """Run all feasibility stages; return narrowed axes, outcomes, flat tips."""
    stages_fn = [
        lambda a: stage_officers_and_annual(
            a,
            annual=annual,
            annual_variance=annual_variance,
            annual_hours_hard=annual_hours_hard,
            coverage_247=coverage_247,
            use_extra_windows=use_extra_windows,
            extra_windows=extra_windows,
        ),
        stage_rotation_shape,
        lambda a: stage_coverage_skeleton(a, coverage_247=coverage_247),
        lambda a: stage_peak_windows(a, use_extra_windows=use_extra_windows, extra_windows=extra_windows),
        lambda a: stage_starts_and_assign_tips(
            a,
            coverage_247=coverage_247,
            use_extra_windows=use_extra_windows,
            extra_windows=extra_windows,
        ),
    ]
    cur = copy.deepcopy(axes)
    outcomes: List[StageOutcome] = []
    all_tips: List[str] = []
    n_stages = len(stages_fn)
    for i, fn in enumerate(stages_fn):
        if cancel_check is not None:
            try:
                if cancel_check():
                    break
            except Exception:
                pass
        cur, outcome = fn(cur)
        outcomes.append(outcome)
        all_tips.extend(outcome.tips)
        if progress is not None:
            try:
                # Do NOT set done/total here — those drive the full-search progress bar.
                progress(
                    {
                        "phase": f"stage:{outcome.stage_id}",
                        "stage": outcome.stage_id,
                        "stage_title": outcome.title,
                        "stage_index": i + 1,
                        "stage_total": n_stages,
                        "message": (f"Stage {i + 1}/{n_stages}: {outcome.title} — {_axis_snapshot(cur)}"),
                        "tips": list(outcome.tips),
                        "stage_ok": outcome.ok,
                    }
                )
            except Exception:
                pass
    return cur, outcomes, all_tips


def format_stage_report(outcomes: Sequence[StageOutcome]) -> List[str]:
    lines: List[str] = ["Feasibility stages (constraints first — not score):"]
    for o in outcomes:
        mark = "ok" if o.ok else "weak"
        lines.append(
            f"  [{mark}] {o.title}: "
            f"N {o.before.get('officer_counts', 0)}→{o.after.get('officer_counts', 0)} · "
            f"L {o.before.get('length_opts', 0)}→{o.after.get('length_opts', 0)} · "
            f"patterns {o.before.get('variation_sets', 0)}→{o.after.get('variation_sets', 0)}"
        )
        for t in o.tips[:2]:
            lines.append(f"      · {t}")
    return lines


def feasibility_sort_key(row: Dict[str, Any], *, annual: float = 0.0) -> Tuple:
    """Sort hard-OK plans by human metrics; internal score last."""
    m = row.get("metrics") or {}
    hard = 0 if row.get("hard_constraints_ok") else 1
    c247 = int(m.get("coverage_247_failures") or 0)
    wins = int(m.get("extra_window_failures") or 0)
    gaps = int(m.get("gap_events") if m.get("gap_events") is not None else (m.get("zero_staff_slots") or 0))
    flsa = int(m.get("flsa_violations") or 0)
    n_off = int(row.get("num_officers") or 99)
    # annual distance only as soft tie-break among feasible
    try:
        ann_delta = abs(float(m.get("avg_annual_hours") or annual) - float(annual or 0))
    except (TypeError, ValueError):
        ann_delta = 0.0
    score = float(row.get("score") or row.get("_internal_score") or 0)
    return (hard, c247, wins, gaps, flsa, n_off, ann_delta, -score)
