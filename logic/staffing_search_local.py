"""Warm-start local search after first hard-OK staffing plans.

Feasibility first: only improve among hard-OK neighbors (packs / phases).
Does not invent constraints; full simulate_schedule remains truth.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple


def neighbor_phase_layouts(
    phases: Sequence[int],
    *,
    cycle_length: int,
    max_neighbors: int = 12,
) -> List[List[int]]:
    """±1 phase nudges per slot (mod cycle)."""
    c = max(1, int(cycle_length))
    base = [int(x) % c for x in phases]
    out: List[List[int]] = []
    seen = {tuple(base)}
    for i in range(len(base)):
        for d in (-1, 1):
            trial = list(base)
            trial[i] = (trial[i] + d) % c
            key = tuple(trial)
            if key in seen:
                continue
            seen.add(key)
            out.append(trial)
            if len(out) >= max_neighbors:
                return out
    return out


def warm_start_from_hard_results(
    hard_rows: Sequence[Dict[str, Any]],
    *,
    simulate_fn: Callable[..., Any],
    build_row_fn: Callable[..., Dict[str, Any]],
    constraint_fail_fn: Callable[[Dict[str, Any]], bool],
    neighbor_packs_fn: Callable[[Sequence[str]], List[List[str]]],
    max_trials: int = 16,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> List[Dict[str, Any]]:
    """Hill-climb from existing hard-OK rows via neighbor packs + phase nudges.

    Returns additional hard-OK rows (may be empty). Does not drop originals.
    """
    extras: List[Dict[str, Any]] = []
    trials = 0
    for row in list(hard_rows)[:4]:
        if cancel_check and cancel_check():
            break
        starts = list(row.get("shift_starts") or [])
        ph = list(row.get("phase_overrides") or [])
        pm = list(row.get("pattern_slot_map") or [])
        cycle = 14
        try:
            vars_ = list(row.get("rotation_variations") or [])
            if vars_:
                from logic.rotation_patterns import build_pattern

                cycle = int(build_pattern(vars_[0], style=row.get("rotation_style") or "rotating").cycle_length)
        except Exception:
            cycle = 14

        pack_neighbors = neighbor_packs_fn(starts) if starts else []
        phase_neighbors = neighbor_phase_layouts(ph, cycle_length=cycle) if ph else []

        candidates: List[Tuple[Optional[List[str]], Optional[List[int]]]] = []
        for p in pack_neighbors[:6]:
            candidates.append((list(p), ph or None))
        for phn in phase_neighbors[:6]:
            candidates.append((starts or None, phn))

        for st, phases in candidates:
            if trials >= max_trials:
                break
            if cancel_check and cancel_check():
                break
            trials += 1
            try:
                sim = simulate_fn(row, starts=st, phases=phases, pattern_map=pm or None)
            except Exception:
                continue
            if not getattr(sim, "success", False) and not (isinstance(sim, dict) and sim.get("success")):
                continue
            m = getattr(sim, "metrics", None) or (sim.get("metrics") if isinstance(sim, dict) else {}) or {}
            if constraint_fail_fn(m):
                continue
            try:
                new_row = build_row_fn(sim, row, starts=st or starts, phases=phases or ph, pattern_map=pm)
            except Exception:
                continue
            if new_row.get("hard_constraints_ok"):
                new_row["warm_start"] = True
                extras.append(new_row)
    return extras
