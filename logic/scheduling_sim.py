"""**Optimizer brain** — schedule simulation and coverage-plan preview.

Prefer importing from this module (or ``logic.coverage_optimizer`` for bumps).
``logic.scheduling`` re-exports remain for back-compat only.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from validators import parse_date


def _parse_sim_start(val):
    from datetime import date as _date

    if val is None:
        return None
    if isinstance(val, _date):
        return val
    try:
        return _date.fromisoformat(str(val))
    except (ValueError, TypeError):
        return None


def _parse_sim_start(val):
    from datetime import date as _date

    if val is None:
        return None
    if isinstance(val, _date):
        return val
    try:
        return _date.fromisoformat(str(val))
    except (ValueError, TypeError):
        return None


def run_schedule_simulation(
    rotation_type: str,
    num_officers: int,
    shift_length_hours: float,
    annual_hours_target: float,
    shift_starts: List[str],
    apply_department_rules: bool = False,
    min_per_shift: int = 1,
    simulation_days: int = 28,
    night_minimum: int | None = None,
    *,
    annual_hours_variance: float = 40.0,
    annual_hours_hard: bool = False,
    coverage_247: int = 0,
    avoid_flsa_overtime: bool = False,
    flsa_work_period_days: int = 28,
    rotation_style: str = "",
    rotation_variations: Optional[List[str]] = None,
    stagger_phases: bool = True,
    auto_min_officers: bool = True,
    use_extra_windows: bool = False,
    extra_windows: Optional[List[Dict]] = None,
    phase_overrides: Optional[List[int]] = None,
    pattern_slot_map: Optional[List[int]] = None,
    flexible_daily_starts: bool = False,
    nearby_start_hops: int = 1,
    allow_offday_coverage: bool = False,
    min_rest_hours: float = 0.0,
    max_consecutive_work_days: int = 0,
    sim_start_date=None,
    phase_limit: int = 3,
) -> Dict:
    from config import NIGHT_MINIMUM_OFFICERS
    from logic.staffing_config import get_staffing_config
    from simulator import SimulatorConfig, simulate_schedule

    # Coalesce None → staffing config fallback so simulate_schedule always
    # receives concrete numbers (float(None) crashes inside the sim).
    if shift_length_hours is None or annual_hours_target is None:
        _sc = get_staffing_config()
        if shift_length_hours is None:
            shift_length_hours = float(_sc.get("shift_length_hours") or 8.0)
        if annual_hours_target is None:
            annual_hours_target = float(_sc.get("annual_hours_target") or 2080.0)

    config = SimulatorConfig(
        rotation_type=rotation_type,
        num_officers=num_officers if num_officers is not None else 0,
        shift_length_hours=shift_length_hours,
        annual_hours_target=annual_hours_target,
        shift_starts=shift_starts,
        apply_department_rules=apply_department_rules,
        min_per_shift=min_per_shift,
        simulation_days=simulation_days,
        night_minimum=night_minimum if night_minimum is not None else NIGHT_MINIMUM_OFFICERS,
        annual_hours_variance=annual_hours_variance,
        annual_hours_hard=annual_hours_hard,
        coverage_247=coverage_247,
        avoid_flsa_overtime=avoid_flsa_overtime,
        flsa_work_period_days=flsa_work_period_days,
        rotation_style=rotation_style,
        rotation_variations=list(rotation_variations or []),
        stagger_phases=stagger_phases,
        auto_min_officers=auto_min_officers,
        use_extra_windows=bool(use_extra_windows),
        extra_windows=list(extra_windows or []),
        phase_overrides=list(phase_overrides) if phase_overrides is not None else None,
        pattern_slot_map=list(pattern_slot_map) if pattern_slot_map is not None else None,
        flexible_daily_starts=bool(flexible_daily_starts),
        nearby_start_hops=int(nearby_start_hops),
        allow_offday_coverage=bool(allow_offday_coverage),
        min_rest_hours=float(min_rest_hours or 0),
        max_consecutive_work_days=int(max_consecutive_work_days or 0),
        sim_start_date=_parse_sim_start(sim_start_date),
        phase_limit=int(phase_limit),
    )
    result = simulate_schedule(config)
    if not result.success:
        return {"success": False, "message": result.message or "Simulation failed"}
    coverage = result.coverage_by_day
    start_label = coverage[0]["date"] if coverage else None
    return {
        "success": True,
        "message": result.message or "Simulation complete",
        "compute_backend": result.compute_backend,
        "metrics": result.metrics,
        "officer_slots": [slot.__dict__ for slot in result.officer_slots],
        "coverage_by_day": coverage,
        "suggestions": [
            {"severity": s.severity, "title": s.title, "message": s.message, "recommendation": s.recommendation}
            for s in result.suggestions
        ],
        "shift_templates": result.shift_templates,
        "simulation_start_date": start_label,
        "simulation_config": {
            "rotation_type": rotation_type,
            "num_officers": num_officers,
            "shift_length_hours": shift_length_hours,
            "annual_hours_target": annual_hours_target,
            "shift_starts": shift_starts,
            "apply_department_rules": apply_department_rules,
            "min_per_shift": min_per_shift,
            "simulation_days": simulation_days,
            "coverage_247": coverage_247,
            "avoid_flsa_overtime": avoid_flsa_overtime,
            "use_extra_windows": use_extra_windows,
            "extra_windows": list(extra_windows or []),
        },
    }


def run_staffing_optimizer(
    *,
    rotation_types: Optional[List[str]] = None,
    officer_counts: Optional[List[int]] = None,
    min_per_shift_options: Optional[List[int]] = None,
    shift_length_hours: Optional[float] = None,
    annual_hours_target: Optional[float] = None,
    shift_starts: Optional[List[str]] = None,
    simulation_days: int = 28,
    coverage_247: int = 0,
    avoid_flsa_overtime: bool = False,
    flsa_work_period_days: int = 28,
    annual_hours_variance: float = 40.0,
    annual_hours_hard: bool = False,
    use_extra_windows: bool = False,
    extra_windows: Optional[List[Dict]] = None,
    night_minimum: Optional[int] = None,
    require_hard_ok: bool = True,
    rotation_style: str = "",
    rotation_variations: Optional[List[str]] = None,
    stagger_phases: bool = True,
    shift_starts_options: Optional[List[List[str]]] = None,
    shift_length_options: Optional[List[float]] = None,
    free_officer_counts: bool = False,
    free_starts: bool = False,
    free_lengths: bool = False,
    free_variations: bool = False,
    constraint_weights: Optional[Dict] = None,
    constraint_priority: Optional[List[str]] = None,
    soft_prefs: Optional[Dict] = None,
    nearby_start_hops: int = 1,
    allow_offday_coverage: bool = False,
    min_rest_hours: float = 0.0,
    max_consecutive_work_days: int = 0,
    sim_start_date=None,
    phase_limit: int = 3,
    progress_callback=None,
    cancel_check=None,
    **_compat,
) -> Dict:
    """Find best staffing plan via exhaustive constraint-space search (not bump logic)."""
    from logic.staffing_optimizer import optimize_staffing_scenarios

    return optimize_staffing_scenarios(
        rotation_types=rotation_types,
        officer_counts=officer_counts,
        min_per_shift_options=min_per_shift_options,
        shift_length_hours=shift_length_hours,
        annual_hours_target=annual_hours_target,
        shift_starts=shift_starts,
        simulation_days=simulation_days,
        coverage_247=coverage_247,
        avoid_flsa_overtime=avoid_flsa_overtime,
        flsa_work_period_days=flsa_work_period_days,
        annual_hours_variance=annual_hours_variance,
        annual_hours_hard=annual_hours_hard,
        use_extra_windows=use_extra_windows,
        extra_windows=extra_windows,
        night_minimum=night_minimum,
        require_hard_ok=require_hard_ok,
        rotation_style=rotation_style,
        rotation_variations=rotation_variations,
        stagger_phases=stagger_phases,
        shift_starts_options=shift_starts_options,
        shift_length_options=shift_length_options,
        free_officer_counts=free_officer_counts,
        free_starts=free_starts,
        free_lengths=free_lengths,
        free_variations=free_variations,
        constraint_weights=constraint_weights,
        constraint_priority=constraint_priority,
        soft_prefs=soft_prefs if soft_prefs is not None else _compat.get("soft_prefs"),
        nearby_start_hops=int(nearby_start_hops),
        allow_offday_coverage=allow_offday_coverage,
        min_rest_hours=min_rest_hours,
        max_consecutive_work_days=max_consecutive_work_days,
        sim_start_date=sim_start_date,
        progress_callback=progress_callback,
        cancel_check=cancel_check,
    )


def estimate_staffing_search_space(**kwargs) -> Dict:
    """UI pre-flight: how many layouts / expected time for current free/locked dims."""
    from logic.staffing_optimizer import estimate_search_space

    return estimate_search_space(**kwargs)


def run_staffing_stage_wizard(**kwargs) -> Dict:
    """Pause after feasibility stages — lock dims — then full Find Best."""
    from logic.staffing_stage_wizard import run_stages_only

    return run_stages_only(**kwargs)


def find_min_officers_hard(**kwargs) -> Dict:
    """Binary-search minimum headcount for hard constraints."""
    from logic.optimizer_features import find_min_officers_hard as _fn

    return _fn(**kwargs)


def what_if_staffing_delta(base_kwargs: Dict, **kwargs) -> Dict:
    """Re-run with one delta (officers / windows / length)."""
    from logic.optimizer_features import what_if_delta

    return what_if_delta(base_kwargs, **kwargs)


def compare_shift_length_scenarios(
    *,
    lengths: Optional[List[float]] = None,
    officer_count: int = 0,
    annual_hours_target: Optional[float] = None,
    annual_hours_variance: float = 40.0,
    rotation_variations: Optional[List[str]] = None,
    coverage_247: int = 0,
    extra_windows: Optional[List[Dict]] = None,
    night_minimum: Optional[int] = None,
    simulation_days: int = 28,
    require_hard_ok: bool = True,
    progress_callback=None,
    cancel_check=None,
    parallel: bool = True,
    depth: str = "deep",
    min_rest_hours: float = 0.0,
    max_consecutive_work_days: int = 0,
    sim_start_date=None,
    phase_limit: int = 3,
    nearby_start_hops: int = 1,
    allow_offday_coverage: bool = False,
    **_compat,
) -> Dict:
    """Compare locked shift lengths (default 8/10/12h) under caller coverage constraints.

    No baked Fri/Sat or multi-block example — pass windows/variations from the form.
    Lengths run in parallel by default (shared cancel_check) to cut wall time.

    depth:
      - "quick": 21-day sim, top LE packs + caller multi-block vars
      - "deep": 28-day + full start pack set (default exhaustive)
    """
    import time as _time
    from concurrent.futures import ThreadPoolExecutor, as_completed

    if officer_count < 1:
        return {"success": False, "message": "Officer count required for length compare", "comparisons": []}
    if annual_hours_target is None or float(annual_hours_target) <= 0:
        return {"success": False, "message": "Annual hours target required for length compare", "comparisons": []}

    lengths = list(lengths or [8.0, 10.0, 12.0])
    # Empty = squad preset path; never inject example multi-block strings
    rotation_variations = list(rotation_variations or [])
    quick = str(depth or "deep").strip().lower() in ("quick", "fast", "cheap")
    if quick:
        simulation_days = min(int(simulation_days or 28), 21)
    else:
        simulation_days = max(int(simulation_days or 28), 28)
    # None/empty = no extra windows (caller must pass windows they want)
    extra_windows = list(extra_windows or [])

    n_len = len(lengths)
    t0 = _time.perf_counter()

    def _one_length(idx: int, length: float) -> Dict:
        if cancel_check and cancel_check():
            return {
                "shift_length_hours": float(length),
                "success": False,
                "cancelled": True,
                "message": "Compare cancelled",
            }

        def _progress_wrap(info, _i=idx, _L=length):
            if progress_callback is None:
                return
            payload = dict(info) if isinstance(info, dict) else {"message": str(info)}
            payload["compare_index"] = _i
            payload["compare_length"] = float(_L)
            payload["compare_total"] = n_len
            msg = payload.get("message") or ""
            payload["message"] = f"Compare {_L:g}h ({_i + 1}/{n_len}) · {msg}"
            try:
                progress_callback(payload)
            except Exception:
                pass

        # Prefer LE evening pack first when length is 8h-class (hard night windows)
        starts = (
            ["06:00", "14:00", "19:00", "22:00"]
            if float(length) <= 9.0
            else (["06:00", "18:00"] if float(length) >= 11.5 else ["06:00", "14:00", "22:00"])
        )
        if float(length) <= 9.0:
            # Quality packs always (evening first) — residual 6 closed: quick keeps these
            start_opts = [
                ["06:00", "14:00", "19:00", "22:00"],
                ["06:00", "14:00", "22:00"],
            ]
            if not quick:
                start_opts.append(["07:00", "15:00", "19:00", "23:00"])
        elif float(length) >= 11.5:
            start_opts = [["06:00", "18:00"], ["07:00", "19:00"]]
            if not quick:
                start_opts.append(["06:00", "14:00", "22:00"])
        else:
            start_opts = [starts]
            if not quick:
                start_opts.append(["07:00", "15:00", "23:00"])
        vars_use = list(rotation_variations)  # full multi-block set for quick + deep

        result = run_staffing_optimizer(
            rotation_types=["2-2-3 (14-day)"],
            officer_counts=[int(officer_count)],
            min_per_shift_options=[1],
            shift_length_hours=float(length),
            shift_starts=starts,
            shift_starts_options=start_opts,
            free_lengths=False,
            free_officer_counts=False,
            free_starts=False,
            free_variations=bool(vars_use),
            min_rest_hours=min_rest_hours,
            max_consecutive_work_days=max_consecutive_work_days,
            nearby_start_hops=nearby_start_hops,
            allow_offday_coverage=allow_offday_coverage,
            rotation_style="rotating" if vars_use else "",
            rotation_variations=vars_use,
            annual_hours_target=float(annual_hours_target),
            annual_hours_variance=float(annual_hours_variance),
            annual_hours_hard=True,
            coverage_247=int(coverage_247),
            use_extra_windows=bool(extra_windows),
            extra_windows=extra_windows,
            night_minimum=night_minimum,
            simulation_days=int(simulation_days),
            require_hard_ok=require_hard_ok,
            progress_callback=_progress_wrap if progress_callback else None,
            cancel_check=cancel_check,
        )
        best = result.get("best") or {}
        # Attach economics for memo / UI (same as Find Best ranked cards)
        try:
            from logic.staffing_insights import enrich_option_economics

            if best:
                best = enrich_option_economics(best)
        except Exception:
            pass
        hm = best.get("human_metrics") or {}
        m = best.get("metrics") or {}
        econ = best.get("economics") or {}
        return {
            "shift_length_hours": float(length),
            "success": bool(result.get("success") and best),
            "impossible": bool(result.get("impossible")),
            "cancelled": bool(result.get("cancelled")),
            "message": result.get("message"),
            "scenarios_evaluated": result.get("scenarios_evaluated"),
            "full_sims_run": result.get("full_sims_run"),
            "wall_time_ms": result.get("wall_time_ms"),
            "best_rank": best.get("rank"),
            "best_starts": best.get("shift_starts") or best.get("starts"),
            "best_variation": (
                best.get("rotation_variations") or best.get("rotation_variation") or best.get("variation")
            ),
            "annual_mean": (
                m.get("avg_annual_hours") or best.get("annual_hours_mean") or best.get("mean_annual_hours")
            ),
            "hard_ok": bool(best.get("hard_constraints_ok", result.get("success"))),
            "window_short": hm.get("extra_window_failures") or m.get("extra_window_failures"),
            "near_miss_count": len(result.get("near_misses") or []),
            "est_ot_hours": econ.get("est_ot_hours_total"),
            "est_ot_cost": econ.get("est_ot_cost_usd"),
            "flsa_period_pct": econ.get("flsa_period_pct"),
            "fairness_score": econ.get("fairness_score"),
            "economics": econ,
        }

    comparisons: List[Dict] = []
    use_parallel = bool(parallel) and n_len > 1
    if use_parallel:
        by_idx: Dict[int, Dict] = {}
        with ThreadPoolExecutor(max_workers=min(n_len, 3)) as pool:
            futs = {pool.submit(_one_length, idx, length): idx for idx, length in enumerate(lengths)}
            for fut in as_completed(futs):
                idx = futs[fut]
                try:
                    by_idx[idx] = fut.result()
                except Exception as exc:
                    by_idx[idx] = {
                        "shift_length_hours": float(lengths[idx]),
                        "success": False,
                        "message": f"Compare failed: {exc}",
                    }
        comparisons = [by_idx[i] for i in range(n_len) if i in by_idx]
    else:
        for idx, length in enumerate(lengths):
            if cancel_check and cancel_check():
                return {
                    "success": False,
                    "cancelled": True,
                    "message": "Compare cancelled",
                    "comparisons": comparisons,
                    "wall_time_ms": int((_time.perf_counter() - t0) * 1000),
                }
            comparisons.append(_one_length(idx, length))

    if cancel_check and cancel_check():
        return {
            "success": False,
            "cancelled": True,
            "message": "Compare cancelled",
            "comparisons": comparisons,
            "wall_time_ms": int((_time.perf_counter() - t0) * 1000),
            "parallel": use_parallel,
        }
    if any(c.get("cancelled") for c in comparisons):
        return {
            "success": False,
            "cancelled": True,
            "message": "Compare cancelled",
            "comparisons": comparisons,
            "wall_time_ms": int((_time.perf_counter() - t0) * 1000),
            "parallel": use_parallel,
        }

    viable = [c for c in comparisons if c.get("success")]
    from logic.optimizer_features import format_compare_table

    wall_ms = int((_time.perf_counter() - t0) * 1000)
    return {
        "success": True,
        "officer_count": int(officer_count),
        "annual_hours_target": float(annual_hours_target),
        "lengths": lengths,
        "comparisons": comparisons,
        "table_lines": format_compare_table(comparisons),
        "viable_count": len(viable),
        "wall_time_ms": wall_ms,
        "parallel": use_parallel,
        "depth": "quick" if quick else "deep",
        "message": (
            f"Compared {len(lengths)} length(s): {len(viable)} viable under hard constraints"
            f" · {wall_ms} ms" + (" · parallel" if use_parallel else "") + (" · quick" if quick else " · deep")
        ),
    }


def preview_best_coverage_plans(
    original_officer_id: int,
    request_date: str,
    squad: str,
    shift_start: str,
    *,
    max_plans: int = 5,
) -> Dict:
    """List ranked coverage plans for UI / supervisor review."""
    from logic.coverage_optimizer import load_coverage_policy, search_best_coverage_plans

    policy = load_coverage_policy()
    policy.max_plans = max_plans
    from logic.scheduling import get_generated_schedule_day_context

    ctx = get_generated_schedule_day_context(parse_date(request_date))
    plans = search_best_coverage_plans(
        original_officer_id,
        request_date,
        squad,
        shift_start,
        ctx,
        policy=policy,
    )
    # Plans already best-first from beam search. plan_score kept for tests/diagnostics only.
    return {
        "success": True,
        "count": len(plans),
        "plans": [
            {
                "success": p.success,
                "message": p.message,
                "rank": i,
                "plan_score": p.plan_score,  # internal ranking only
                "chain": p.chain,
                "score_components": getattr(p, "score_components", None) or [],
                "steps": [
                    {
                        "step": s.step_number,
                        "original": s.original_officer_name,
                        "replacement": s.replacement_officer_name,
                        "from_shift": s.replacement_shift,
                        "to_shift": s.original_shift,
                        "on_duty": s.replacement_on_duty,
                        "original_id": s.original_officer_id,
                        "replacement_id": s.replacement_officer_id,
                    }
                    for s in p.steps
                ],
                "requires_manual": p.requires_manual,
                "failure_reason": p.failure_reason,
            }
            for i, p in enumerate(plans, 1)
        ],
        "policy": {
            "min_per_shift": policy.min_per_shift,
            "min_by_band": dict(policy.min_by_band),
            "night_minimum": policy.night_minimum,
            "max_cascade_depth": policy.max_cascade_depth,
            "beam_width": policy.beam_width,
            "w_junior": policy.w_junior,
            "w_spare_capacity": policy.w_spare_capacity,
            "w_same_start": policy.w_same_start,
            "w_shallow_chain": policy.w_shallow_chain,
        },
    }


def get_simulator_defaults_from_roster() -> Dict:
    from simulator import config_from_current_roster

    cfg = config_from_current_roster()
    return {
        "success": True,
        "rotation_type": cfg.rotation_type,
        "num_officers": cfg.num_officers,
        "shift_length_hours": cfg.shift_length_hours,
        "annual_hours_target": cfg.annual_hours_target,
        "shift_starts": ", ".join(cfg.shift_starts),
        "apply_department_rules": cfg.apply_department_rules,
        "min_per_shift": cfg.min_per_shift,
    }
