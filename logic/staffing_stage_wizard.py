"""Interactive stage wizard: run feasibility stages, pause for lock/unlock, then full search.

Product: find feasible schedules from entered constraints first.
Stages shrink domain; user locks dims; full sim only after continue.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional


def run_stages_only(
    *,
    progress_callback: Optional[Callable] = None,
    cancel_check: Optional[Callable] = None,
    **kwargs,
) -> Dict[str, Any]:
    """Resolve + bind + feasibility stages only (no full sim sweep).

    Returns stage_report, tips, lock actions, and a form_patch_hints dict
    so the UI can lock values before Find Best continues.
    """
    from logic.result_narrowers import suggest_lock_actions
    from logic.staffing_optimizer import (
        _resolve_axes,
        bind_domains,
        domain_reduction_report,
        estimate_search_space,
    )
    from logic.staffing_search_stages import format_stage_report, run_feasibility_stages

    space_keys = (
        "rotation_types",
        "officer_counts",
        "min_per_shift_options",
        "shift_length_hours",
        "shift_starts",
        "shift_starts_options",
        "shift_length_options",
        "rotation_style",
        "rotation_variations",
        "free_officer_counts",
        "free_starts",
        "free_lengths",
        "free_variations",
        "stagger_phases",
        "annual_hours_hard",
        "annual_hours_target",
        "annual_hours_variance",
        "coverage_247",
        "use_extra_windows",
        "extra_windows",
    )
    space_kw = {k: kwargs.get(k) for k in space_keys}
    # Main estimate_search_space does float(variance) without None coalesce
    if space_kw.get("annual_hours_variance") is None:
        space_kw["annual_hours_variance"] = 40.0
    space = estimate_search_space(**space_kw)

    axes = _resolve_axes(
        rotation_types=kwargs.get("rotation_types"),
        officer_counts=kwargs.get("officer_counts"),
        min_per_shift_options=kwargs.get("min_per_shift_options"),
        shift_length_hours=kwargs.get("shift_length_hours"),
        shift_length_options=kwargs.get("shift_length_options"),
        shift_starts=kwargs.get("shift_starts"),
        shift_starts_options=kwargs.get("shift_starts_options"),
        free_officer_counts=bool(kwargs.get("free_officer_counts")),
        free_starts=bool(kwargs.get("free_starts")),
        free_lengths=bool(kwargs.get("free_lengths")),
        free_variations=bool(kwargs.get("free_variations")),
        rotation_variations=kwargs.get("rotation_variations"),
        rotation_style=kwargs.get("rotation_style") or "",
        annual_hours_target=kwargs.get("annual_hours_target"),
        annual_hours_variance=kwargs.get("annual_hours_variance") or 40.0,
    )
    windows = list(kwargs.get("extra_windows") or [])
    use_win = bool(kwargs.get("use_extra_windows") and windows)
    cov247 = int(kwargs.get("coverage_247") or 0)
    annual = float(
        kwargs.get("annual_hours_target")
        if kwargs.get("annual_hours_target") is not None
        else (axes.get("staffing") or {}).get("annual_hours_target") or 2080
    )
    avar = float(kwargs.get("annual_hours_variance") if kwargs.get("annual_hours_variance") is not None else 40.0)

    axes = bind_domains(
        axes,
        coverage_247=cov247,
        use_extra_windows=use_win,
        extra_windows=windows,
        annual_hours_target=annual,
        annual_hours_variance=avar,
        annual_hours_hard=bool(kwargs.get("annual_hours_hard")),
        max_consecutive_work_days=int(kwargs.get("max_consecutive_work_days") or 0),
        min_rest_hours=float(kwargs.get("min_rest_hours") or 0),
        avoid_flsa=bool(kwargs.get("avoid_flsa_overtime")),
        flsa_work_period_days=int(kwargs.get("flsa_work_period_days") or 28),
    )

    def _prog(info):
        if progress_callback and isinstance(info, dict):
            try:
                progress_callback(info)
            except Exception:
                pass

    axes, outcomes, tips = run_feasibility_stages(
        axes,
        annual=annual,
        annual_variance=avar,
        annual_hours_hard=bool(kwargs.get("annual_hours_hard")),
        coverage_247=cov247,
        use_extra_windows=use_win,
        extra_windows=windows,
        progress=_prog,
        cancel_check=cancel_check,
    )

    stage_report = [
        {
            "stage_id": o.stage_id,
            "title": o.title,
            "ok": o.ok,
            "tips": list(o.tips),
            "reasons": list(o.reasons),
            "before": dict(o.before),
            "after": dict(o.after),
        }
        for o in outcomes
    ]
    current = {
        "officer_counts": list(axes.get("officer_counts") or []),
        "length_opts": list(axes.get("length_opts") or []),
        "free_starts": bool(axes.get("free_starts")),
    }
    actions = suggest_lock_actions(stage_report, tips, current=current)
    report_lines = format_stage_report(outcomes)

    # Suggested single locks for fastest continue
    form_hints: Dict[str, Any] = {}
    ns = current["officer_counts"]
    if len(ns) == 1:
        form_hints["use_officers"] = True
        form_hints["officers"] = str(ns[0])
    ls = current["length_opts"]
    if len(ls) == 1:
        form_hints["use_length"] = True
        form_hints["length"] = str(ls[0])
    locked = axes.get("locked_starts_opts")
    if locked and len(locked) == 1:
        form_hints["use_starts"] = True
        form_hints["starts"] = ", ".join(locked[0])

    return {
        "success": True,
        "wizard_pause": True,
        "message": "Feasibility stages complete — lock dimensions, then continue full search",
        "stage_report": stage_report,
        "stage_tips": tips,
        "stage_lines": report_lines,
        "lock_actions": actions,
        "form_hints": form_hints,
        "domain_report": domain_reduction_report(axes),
        "bound_axes": {
            "officer_counts": list(axes.get("officer_counts") or []),
            "length_opts": list(axes.get("length_opts") or []),
            "variation_sets": list(axes.get("variation_sets") or []),
            "rotation_types": list(axes.get("rotation_types") or []),
            "min_per_shift_options": list(axes.get("min_per_shift_options") or []),
            "free_starts": bool(axes.get("free_starts")),
            "style": axes.get("style") or "",
            "base_variations": list(axes.get("base_variations") or []),
        },
        "space_estimate": space,
        "constraints_applied": {
            "search_architecture": "staged_wizard_pause",
            "coverage_247": cov247,
        },
    }
