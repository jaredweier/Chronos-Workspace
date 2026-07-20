"""
Staffing optimizer product helpers — presets, explain, fairness, what-if, export.

Used by Chronos simulator UI, scheduling_sim, CLI. Not bump/leave coverage.
"""

from __future__ import annotations

import csv
import json
import time
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple  # noqa: F401


def _exports_dir() -> Path:
    root = Path(__file__).resolve().parent.parent
    d = root / "exports"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── A1 / B4 presets & window templates ──────────────────────────────────────

REAL_WORLD_8H_PRESET: Dict[str, Any] = {
    "name": "Real-World 8h Pack",
    "rotation_type": "2-2-3 (14-day)",
    "num_officers": 8,
    "officer_counts": [7, 8, 9],
    "lock_officers": False,
    "shift_length_hours": 8.0,
    "lock_length": True,
    "annual_hours_target": 2008,
    "annual_hours_variance": 20,
    "lock_annual": True,
    "shift_starts": ["06:00", "14:00", "22:00"],
    "lock_starts": True,
    "min_per_shift": 1,
    "lock_min_ps": True,
    "rotation_style": "rotating",
    "rotation_variations": ["6-2,5-3", "6-3,5-2"],
    "lock_style": True,
    "coverage_247": 1,
    "use_extra_windows": True,
    "extra_windows": [
        {
            "min_officers": 2,
            "start_time": "19:00",
            "end_time": "03:00",
            "weekday": 4,
            "label": "Friday Night",
            "enabled": True,
        },
        {
            "min_officers": 2,
            "start_time": "19:00",
            "end_time": "03:00",
            "weekday": 5,
            "label": "Saturday Night",
            "enabled": True,
        },
    ],
    "notes": "8h multi-block ≈2008h/yr; Fri+Sat 19–03 min2 often needs 8 officers.",
}

WINDOW_TEMPLATES: Dict[str, List[Dict[str, Any]]] = {
    "fri_sat_night": list(REAL_WORLD_8H_PRESET["extra_windows"]),
    "weekend_all_day": [
        {
            "min_officers": 2,
            "start_time": "07:00",
            "end_time": "23:00",
            "weekday": 5,
            "label": "Saturday Day",
            "enabled": True,
        },
        {
            "min_officers": 2,
            "start_time": "07:00",
            "end_time": "23:00",
            "weekday": 6,
            "label": "Sunday Day",
            "enabled": True,
        },
    ],
    "holiday_eve": [
        {
            "min_officers": 3,
            "start_time": "16:00",
            "end_time": "02:00",
            "weekday": None,
            "label": "Holiday Eve Peak",
            "enabled": True,
        }
    ],
    "court_week_mornings": [
        {
            "min_officers": 2,
            "start_time": "08:00",
            "end_time": "12:00",
            "weekday": d,
            "label": f"Court {name}",
            "enabled": True,
        }
        for d, name in ((0, "Mon"), (1, "Tue"), (2, "Wed"), (3, "Thu"))
    ],
}


def list_window_templates() -> List[Dict[str, str]]:
    return [
        {"id": "fri_sat_night", "label": "Fri+Sat Night 19:00–03:00 Min 2"},
        {"id": "weekend_all_day", "label": "Sat+Sun Day Min 2"},
        {"id": "holiday_eve", "label": "Holiday Eve Peak Min 3"},
        {"id": "court_week_mornings", "label": "Court Week Mornings Min 2"},
    ]


def get_window_template(template_id: str) -> List[Dict[str, Any]]:
    return [dict(w) for w in WINDOW_TEMPLATES.get(template_id or "", [])]


def get_real_world_8h_preset() -> Dict[str, Any]:
    return json.loads(json.dumps(REAL_WORLD_8H_PRESET))


# ── D1 / D5 constraint checklist & near-miss deltas ─────────────────────────

_CHECK_KEYS = (
    ("coverage_247", "24/7 Coverage", "coverage_247_failures"),
    ("windows", "Extra Windows", "extra_window_failures"),
    ("gaps", "Min Per Shift / Gaps", "gap_events"),
    ("flsa", "FLSA OT Avoid", "flsa_violations"),
    ("annual", "Annual Hours", "annual_band_outside"),
)


def constraint_checklist(row: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Per-constraint pass/fail for option cards and audit."""
    r = row or {}
    m = r.get("metrics") or {}
    hm = r.get("human_metrics") or {}
    failed = set(r.get("failed_constraints") or hm.get("failed_constraints") or [])
    hard = r.get("hard_constraints_ok")
    if hard is None:
        hard = hm.get("hard_constraints_ok")
    items: List[Dict[str, Any]] = []
    for key, label, metric_key in _CHECK_KEYS:
        n = hm.get(metric_key)
        if n is None:
            if metric_key == "gap_events":
                n = m.get("gap_events") or m.get("zero_staff_slots") or hm.get("zero_staff_gaps")
            else:
                n = m.get(metric_key)
        try:
            count = int(n or 0)
        except (TypeError, ValueError):
            count = 0
        ok = key not in failed and count == 0
        if hard is False and key in failed:
            ok = False
        items.append(
            {
                "key": key,
                "label": label,
                "ok": ok,
                "count": count,
                "mark": "✅" if ok else "❌",
            }
        )
    return items


def format_checklist_line(row: Optional[Dict[str, Any]] = None) -> str:
    items = constraint_checklist(row)
    return " ".join(f"{it['mark']} {it['label']}" for it in items)


def near_miss_deltas(row: Optional[Dict[str, Any]] = None) -> List[str]:
    """How far a near-miss missed (plain language)."""
    r = row or {}
    m = r.get("metrics") or {}
    hm = r.get("human_metrics") or {}
    lines: List[str] = []
    mapping = [
        ("extra_window_failures", "Window shortfalls", "nights/slots"),
        ("coverage_247_failures", "24/7 shortfalls", "slots"),
        ("gap_events", "Coverage gaps", "events"),
        ("flsa_violations", "FLSA over-cap", "periods"),
        ("annual_band_outside", "Officers outside annual band", "officers"),
        ("annual_mean_outside", "Mean annual off target", "flag"),
        ("night_minimum_failures", "Night minimum short", "nights"),
    ]
    for key, label, unit in mapping:
        n = hm.get(key)
        if n is None:
            if key == "gap_events":
                n = m.get("gap_events") or hm.get("zero_staff_gaps") or m.get("zero_staff_slots")
            else:
                n = m.get(key)
        try:
            v = int(n or 0)
        except (TypeError, ValueError):
            continue
        if v > 0:
            lines.append(f"{label}: {v} {unit}")
    delta = hm.get("annual_hours_delta")
    if delta is None and m.get("avg_annual_hours") is not None:
        target = r.get("annual_hours_target")
        if target is not None:
            try:
                delta = abs(float(m["avg_annual_hours"]) - float(target))
            except (TypeError, ValueError):
                delta = None
    if delta is not None:
        try:
            d = float(delta)
            if d >= 1:
                lines.append(f"Annual mean off target: ~{d:.0f}h")
        except (TypeError, ValueError):
            pass
    spread = hm.get("annual_hours_spread") or m.get("annual_hours_spread")
    if spread is not None:
        try:
            s = float(spread)
            if s >= 1:
                lines.append(f"Officer hours spread: ~{s:.0f}h")
        except (TypeError, ValueError):
            pass
    return lines


def why_best_lines(result: Optional[Dict[str, Any]] = None) -> List[str]:
    """A9 — why #1 ranked (plain)."""
    r = result or {}
    best = r.get("best") or {}
    lines: List[str] = []
    if not best:
        lines.append("No best option selected.")
        return lines
    if best.get("hard_constraints_ok"):
        lines.append("Meets every selected hard constraint.")
    else:
        lines.append("Best available near-miss (not all hard constraints met).")
        lines.extend(near_miss_deltas(best))
    lines.append(format_checklist_line(best))
    n = best.get("num_officers")
    if n is not None:
        lines.append(f"Uses {n} officers (prefer fewer when quality ties).")
    starts = best.get("shift_starts") or []
    if starts:
        lines.append("Starts: " + ", ".join(str(s) for s in starts))
    vars_ = best.get("rotation_variations") or []
    if vars_:
        lines.append("Multi-block: " + " | ".join(str(v) for v in vars_))
    ranked = r.get("ranked") or []
    if len(ranked) > 1:
        lines.append(f"{len(ranked)} options kept — pick another if starts or N differ.")
    return lines


def suggest_unlocks(result: Optional[Dict[str, Any]] = None) -> List[str]:
    """B8 — when impossible, suggest free dimensions."""
    r = result or {}
    lines: List[str] = []
    if not (r.get("impossible") or (not r.get("success") and r.get("require_hard_ok", True))):
        if r.get("success"):
            return lines
    hist = r.get("failure_histogram") or {}
    cons = r.get("constraints_applied") or {}
    if hist.get("window") or hist.get("windows"):
        lines.append("Unlock shift starts (try evening 14:00+19:00 packs) or raise officer count.")
    if hist.get("coverage_247"):
        lines.append("Unlock officer count (raise N) or lower 24/7 minimum.")
    if hist.get("annual"):
        lines.append("Widen annual variance or unlock multi-block / shift length.")
    if hist.get("gaps"):
        lines.append("Lower minimum officers per shift band or add officers.")
    offs = cons.get("officer_counts") or []
    if offs and max(int(x) for x in offs) < 8:
        lines.append("Try officer count free 7–9 — hard Fri/Sat nights often need 8.")
    if not lines:
        lines.append("Unlock officer count and/or shift starts, then Find Best again.")
        lines.append("Or Soften constraints to see closest alternatives.")
    return lines


def headcount_banner(result: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """D2 — honest needs-N banner."""
    r = result or {}
    best = r.get("best") or {}
    if not best or not best.get("hard_constraints_ok"):
        return None
    n = best.get("num_officers")
    tried = (r.get("constraints_applied") or {}).get("officer_counts") or []
    if n is None:
        return None
    try:
        n = int(n)
        tried_i = [int(x) for x in tried]
    except (TypeError, ValueError):
        return None
    if tried_i and n > min(tried_i):
        return f"Hard constraints need {n} officers (lower counts in search did not fully pass)."
    if n >= 8:
        near = r.get("near_misses") or []
        for nm in near:
            try:
                if int(nm.get("num_officers") or 0) < n and not nm.get("hard_constraints_ok"):
                    return f"Hard pack needs {n} officers — {n - 1} left residual shortfalls (often weekend nights)."
            except (TypeError, ValueError):
                continue
    return None


# ── A4 option diff ───────────────────────────────────────────────────────────


def diff_options(
    a: Optional[Dict[str, Any]] = None,
    b: Optional[Dict[str, Any]] = None,
) -> List[str]:
    a, b = a or {}, b or {}
    lines = ["Option A vs Option B"]
    pairs = [
        ("num_officers", "Officers"),
        ("shift_length_hours", "Length"),
        ("min_per_shift", "Min/Shift"),
        ("rotation_type", "Rotation"),
    ]
    for key, label in pairs:
        va, vb = a.get(key), b.get(key)
        if va != vb:
            lines.append(f"{label}: {va} → {vb}")
        else:
            lines.append(f"{label}: {va} (same)")
    sa = a.get("shift_starts") or []
    sb = b.get("shift_starts") or []
    lines.append(f"Starts A: {', '.join(str(x) for x in sa) if sa else '—'}")
    lines.append(f"Starts B: {', '.join(str(x) for x in sb) if sb else '—'}")
    va = a.get("rotation_variations") or []
    vb = b.get("rotation_variations") or []
    lines.append(f"Multi-block A: {' | '.join(map(str, va)) or '—'}")
    lines.append(f"Multi-block B: {' | '.join(map(str, vb)) or '—'}")
    lines.append("Checklist A: " + format_checklist_line(a))
    lines.append("Checklist B: " + format_checklist_line(b))
    return lines


# ── B5 fairness ──────────────────────────────────────────────────────────────


def fairness_report(result: Optional[Dict[str, Any]] = None) -> List[str]:
    r = result or {}
    slots = r.get("officer_slots") or []
    m = r.get("metrics") or {}
    lines = ["Fairness Report"]
    hours: List[float] = []
    for s in slots:
        if not isinstance(s, dict):
            s = getattr(s, "__dict__", {}) or {}
        h = s.get("projected_annual_hours")
        if h is not None:
            try:
                hours.append(float(h))
            except (TypeError, ValueError):
                pass
        label = s.get("label") or s.get("slot_id") or "?"
        start = s.get("shift_start") or "—"
        lines.append(
            f"  {label}: {start} · ~{s.get('projected_annual_hours', '—')}h/yr · "
            f"work days {s.get('work_days_in_sim', '—')}"
        )
    if hours:
        lines.insert(
            1,
            f"Annual range: {min(hours):.0f}–{max(hours):.0f}h · "
            f"spread {max(hours) - min(hours):.0f}h · "
            f"mean {sum(hours) / len(hours):.0f}h",
        )
    if m.get("avg_annual_hours") is not None:
        lines.append(f"Metrics mean annual: {float(m['avg_annual_hours']):.1f}h")
    if m.get("annual_hours_spread") is not None:
        lines.append(f"Metrics spread: {float(m['annual_hours_spread']):.1f}h")
    return lines[:48]


# ── B1 min headcount ─────────────────────────────────────────────────────────


def _le_start_packs_for_length(length: float, base: Optional[List[str]] = None) -> Tuple[List[str], List[List[str]]]:
    """LE-sane half-hour packs; 8h-class includes 19:00 for Fri/Sat night windows."""
    base_starts = list(base or ["06:00", "14:00", "22:00"])
    if float(length) <= 9.0:
        primary = ["06:00", "14:00", "19:00", "22:00"]
        opts = [
            ["06:00", "14:00", "19:00", "22:00"],
            ["06:00", "14:00", "22:00"],
            ["07:00", "15:00", "19:00", "23:00"],
        ]
        # Keep caller base if already a known pack
        if base_starts and base_starts not in opts:
            opts = [base_starts] + [o for o in opts if o != base_starts]
        return primary if not base else base_starts, opts
    return base_starts, [base_starts]


def find_min_officers_hard(
    *,
    lo: int = 4,
    hi: int = 16,
    shift_length_hours: float = 8.0,
    annual_hours_target: float = 2008.0,
    annual_hours_variance: float = 20.0,
    rotation_variations: Optional[List[str]] = None,
    shift_starts: Optional[List[str]] = None,
    shift_starts_options: Optional[List[List[str]]] = None,
    coverage_247: int = 1,
    extra_windows: Optional[List[Dict]] = None,
    night_minimum: Optional[int] = None,
    simulation_days: int = 28,
    progress_callback=None,
    cancel_check=None,
) -> Dict[str, Any]:
    """Binary search smallest N that meets hard constraints (product path).

    Multi-block 6-2/5-3 style + LE start packs (incl. 19:00 for 8h nights).
    """
    from logic.scheduling_sim import run_staffing_optimizer

    rotation_variations = list(rotation_variations or ["6-2,5-3", "6-3,5-2"])
    starts, auto_opts = _le_start_packs_for_length(
        float(shift_length_hours), list(shift_starts) if shift_starts else None
    )
    start_opts = [list(x) for x in shift_starts_options] if shift_starts_options else auto_opts
    if extra_windows is None:
        extra_windows = list(REAL_WORLD_8H_PRESET["extra_windows"])

    lo, hi = max(1, int(lo)), max(int(lo), int(hi))
    best_n: Optional[int] = None
    best_result: Optional[Dict] = None
    trials: List[Dict] = []
    left, right = lo, hi
    while left <= right:
        if cancel_check and cancel_check():
            return {
                "success": False,
                "cancelled": True,
                "message": "Min-N search cancelled",
                "trials": trials,
            }
        mid = (left + right) // 2
        if progress_callback:
            try:
                progress_callback(
                    {
                        "message": f"Testing {mid} officers…",
                        "done": len(trials),
                        "total": max(1, hi - lo + 1),
                    }
                )
            except Exception:
                pass
        # B10 fix: resolve the configured rotation preset before falling back
        # to the hardcoded Dodgeville name (which fails on any other deployment).
        try:
            from logic.rotation_config import get_rotation_config

            _rc = get_rotation_config()
            _preset = _rc.get("preset_name") or _rc.get("active_preset")
        except Exception:
            _preset = None
        if not _preset:
            try:
                from config import ROTATION_PRESETS

                _preset = next(iter(ROTATION_PRESETS), "2-2-3 (Dodgeville 14-day)")
            except Exception:
                _preset = "2-2-3 (Dodgeville 14-day)"
        res = run_staffing_optimizer(
            rotation_types=[_preset],
            officer_counts=[mid],
            min_per_shift_options=[1],
            shift_length_hours=float(shift_length_hours),
            shift_starts=starts,
            shift_starts_options=start_opts,
            free_lengths=False,
            free_officer_counts=False,
            free_starts=False,
            free_variations=False,
            rotation_style="rotating",
            rotation_variations=rotation_variations,
            annual_hours_target=float(annual_hours_target),
            annual_hours_variance=float(annual_hours_variance),
            annual_hours_hard=True,
            coverage_247=int(coverage_247),
            use_extra_windows=bool(extra_windows),
            extra_windows=extra_windows,
            night_minimum=night_minimum,
            simulation_days=int(simulation_days),
            require_hard_ok=True,
            cancel_check=cancel_check,
        )
        ok = bool(res.get("success") and (res.get("best") or {}).get("hard_constraints_ok"))
        trials.append(
            {
                "num_officers": mid,
                "success": ok,
                "message": res.get("message"),
                "best_starts": (res.get("best") or {}).get("shift_starts"),
            }
        )
        if ok:
            best_n = mid
            best_result = res
            right = mid - 1
        else:
            left = mid + 1

    # Optional CP-SAT note (feasibility sketch only)
    cpsat_note = None
    try:
        from logic.cp_sat_bridge import minimize_officer_count, ortools_available

        if ortools_available():
            sol = minimize_officer_count(
                ["day", "eve", "night"],
                [f"d{i}" for i in range(7)],
                min_per_band={"day": 1, "eve": 1, "night": max(1, coverage_247)},
                min_officers=lo,
                max_officers=hi,
                time_limit_sec=1.0,
            )
            if sol.feasible:
                cpsat_note = sol.message
    except Exception:
        cpsat_note = None

    if best_n is None:
        return {
            "success": False,
            "impossible": True,
            "message": f"No hard-OK headcount between {lo} and {hi}",
            "trials": trials,
            "min_officers": None,
            "cpsat_note": cpsat_note,
        }
    return {
        "success": True,
        "min_officers": best_n,
        "message": f"Minimum officers for hard constraints: {best_n}",
        "trials": trials,
        "best": (best_result or {}).get("best"),
        "optimizer_result": best_result,
        "cpsat_note": cpsat_note,
    }


# ── B2 what-if ───────────────────────────────────────────────────────────────


def what_if_delta(
    base_kwargs: Dict[str, Any],
    *,
    delta_officers: int = 0,
    drop_windows: bool = False,
    shift_length_hours: Optional[float] = None,
    require_hard_ok: bool = True,
    cancel_check=None,
) -> Dict[str, Any]:
    """Re-run optimizer with one change; return before/after hard-OK."""
    from logic.scheduling_sim import run_staffing_optimizer

    base = dict(base_kwargs or {})
    base.pop("error", None)
    # Baseline
    base_run = run_staffing_optimizer(**base, cancel_check=cancel_check)
    alt = dict(base)
    if delta_officers:
        counts = list(alt.get("officer_counts") or [8])
        try:
            counts = [max(1, int(c) + int(delta_officers)) for c in counts]
        except (TypeError, ValueError):
            counts = [8 + int(delta_officers)]
        alt["officer_counts"] = counts
        alt["free_officer_counts"] = False
    if drop_windows:
        alt["use_extra_windows"] = False
        alt["extra_windows"] = []
    if shift_length_hours is not None:
        alt["shift_length_hours"] = float(shift_length_hours)
        alt["free_lengths"] = False
    alt["require_hard_ok"] = require_hard_ok
    alt_run = run_staffing_optimizer(**alt, cancel_check=cancel_check)
    return {
        "success": True,
        "base_success": bool(base_run.get("success")),
        "alt_success": bool(alt_run.get("success")),
        "base_message": base_run.get("message"),
        "alt_message": alt_run.get("message"),
        "base_best": base_run.get("best"),
        "alt_best": alt_run.get("best"),
        "delta_officers": delta_officers,
        "drop_windows": drop_windows,
        "shift_length_hours": shift_length_hours,
        "message": (f"Base hard-OK={bool(base_run.get('success'))} → Alt hard-OK={bool(alt_run.get('success'))}"),
    }


# ── C5 early impossible ──────────────────────────────────────────────────────


def early_impossible_proof(
    *,
    num_officers: int,
    shift_length_hours: float,
    annual_hours_target: float,
    annual_hours_variance: float,
    annual_hours_hard: bool,
    rotation_variations: Optional[Sequence[str]],
    coverage_247: int,
    window_min: int,
    rotation_style: str = "rotating",
) -> Optional[str]:
    """Return reason string if pattern math alone proves hard failure."""
    from logic.rotation_patterns import build_pattern, projected_annual_hours

    vars_ = [v for v in (rotation_variations or []) if (v or "").strip()]

    if not vars_:
        if coverage_247 > 0 and int(num_officers) < int(coverage_247):
            return f"officers ({num_officers}) < 24/7 minimum ({coverage_247})"
        if window_min > 0 and int(num_officers) < int(window_min):
            return f"officers ({num_officers}) < window minimum ({window_min})"
        return None

    try:
        patterns = [
            build_pattern(
                t,
                style=rotation_style if rotation_style in ("fixed", "rotating") else None,
            )
            for t in vars_
        ]
    except ValueError as exc:
        return f"invalid multi-block pattern: {exc}"

    # Verify coverage bounds based on rotation math
    work_fracs = [p.work_days_per_cycle() / max(1, p.cycle_length) for p in patterns]
    avg_work_frac = sum(work_fracs) / max(1, len(work_fracs))
    max_daily_staffing = int(num_officers * avg_work_frac)

    if coverage_247 > 0:
        import math

        shifts_needed = math.ceil(24.0 / float(shift_length_hours))
        working_needed = shifts_needed * int(coverage_247)
        if max_daily_staffing < working_needed:
            return f"rotation supports max {max_daily_staffing} working/day, but 24/7 requires {working_needed} (for {shifts_needed} shifts)"

    if window_min > 0 and max_daily_staffing < int(window_min):
        return f"rotation supports max {max_daily_staffing} working/day, but window minimum is {window_min}"

    if annual_hours_hard:
        hours = [
            projected_annual_hours(patterns[i % len(patterns)], float(shift_length_hours))
            for i in range(max(1, int(num_officers)))
        ]
        avg = sum(hours) / max(1, len(hours))
        if float(annual_hours_variance or 0) > 0:
            band = float(annual_hours_variance)
        else:
            band = abs(float(annual_hours_target)) * 0.02
        if abs(avg - float(annual_hours_target)) > band + 1.0:
            return f"pattern mean annual ~{avg:.0f}h outside {annual_hours_target:g}±{annual_hours_variance:g}"

    return None


# ── C6 diversify ranked ──────────────────────────────────────────────────────


def diversify_ranked(rows: List[Dict], *, limit: int = 15) -> List[Dict]:
    """Prefer diverse start packs / N in top-K (not near clones)."""
    if not rows:
        return []
    out: List[Dict] = []
    seen_starts: set = set()
    seen_n: set = set()
    # Pass 1: unique starts
    for row in rows:
        key = tuple(row.get("shift_starts") or [])
        if key in seen_starts and len(out) >= 3:
            continue
        seen_starts.add(key)
        seen_n.add(row.get("num_officers"))
        out.append(row)
        if len(out) >= limit:
            return out
    # Pass 2: fill remaining by score order
    for row in rows:
        if row in out:
            continue
        out.append(row)
        if len(out) >= limit:
            break
    return out


# ── A3 / D3 export ───────────────────────────────────────────────────────────


def export_ranked_options_csv(
    ranked: List[Dict],
    *,
    filename: Optional[str] = None,
) -> Dict[str, Any]:
    path = _exports_dir() / (filename or f"optimizer_options_{time.strftime('%Y%m%d_%H%M%S')}.csv")
    fields = [
        "rank",
        "num_officers",
        "shift_length_hours",
        "min_per_shift",
        "shift_starts",
        "rotation_variations",
        "hard_constraints_ok",
        "failed_constraints",
        "summary",
    ]
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for row in ranked or []:
            w.writerow(
                {
                    "rank": row.get("rank"),
                    "num_officers": row.get("num_officers"),
                    "shift_length_hours": row.get("shift_length_hours"),
                    "min_per_shift": row.get("min_per_shift"),
                    "shift_starts": ",".join(str(s) for s in (row.get("shift_starts") or [])),
                    "rotation_variations": "|".join(str(v) for v in (row.get("rotation_variations") or [])),
                    "hard_constraints_ok": row.get("hard_constraints_ok"),
                    "failed_constraints": ",".join(row.get("failed_constraints") or []),
                    "summary": row.get("summary"),
                }
            )
    return {"success": True, "path": str(path)}


def search_audit_payload(result: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    r = result or {}
    return {
        "saved_at": date.today().isoformat(),
        "success": r.get("success"),
        "impossible": r.get("impossible"),
        "message": r.get("message"),
        "scenarios_evaluated": r.get("scenarios_evaluated"),
        "full_sims_run": r.get("full_sims_run"),
        "pruned_cheap": r.get("pruned_cheap"),
        "wall_time_ms": r.get("wall_time_ms"),
        "failure_histogram": r.get("failure_histogram"),
        "constraints_applied": r.get("constraints_applied"),
        "constraint_weights": r.get("constraint_weights"),
        "best": r.get("best"),
        "ranked": r.get("ranked"),
        "near_misses": r.get("near_misses"),
        "space_estimate": r.get("space_estimate"),
        "why_best": why_best_lines(r),
        "suggest_unlocks": suggest_unlocks(r),
        "headcount_banner": headcount_banner(r),
    }


def export_search_audit_json(
    result: Optional[Dict[str, Any]] = None,
    *,
    filename: Optional[str] = None,
) -> Dict[str, Any]:
    path = _exports_dir() / (filename or f"optimizer_audit_{time.strftime('%Y%m%d_%H%M%S')}.json")
    payload = search_audit_payload(result)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return {"success": True, "path": str(path)}


def format_compare_table(comparisons: List[Dict]) -> List[str]:
    """A10 — readable compare lines (table-like)."""
    lines = [
        "Shift Length Compare",
        f"{'Len':>4}  {'Hard':>4}  {'Annual':>8}  {'Layouts':>10}  {'ms':>8}  Starts",
        "-" * 72,
    ]
    for c in comparisons or []:
        ann = c.get("annual_mean")
        ann_s = f"{float(ann):.0f}" if ann is not None else "—"
        starts = c.get("best_starts") or []
        st = ",".join(str(s) for s in starts) if isinstance(starts, list) else str(starts or "—")
        lines.append(
            f"{c.get('shift_length_hours', '—')!s:>4}  "
            f"{'OK' if c.get('success') else 'NO':>4}  "
            f"{ann_s:>8}  "
            f"{c.get('scenarios_evaluated', '—')!s:>10}  "
            f"{c.get('wall_time_ms', '—')!s:>8}  "
            f"{st}"
        )
    return lines


def option_seed_from_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """B3 — form seed from a ranked option."""
    r = row or {}
    return {
        "rotation_type": r.get("rotation_type"),
        "num_officers": r.get("num_officers"),
        "shift_length_hours": r.get("shift_length_hours"),
        "annual_hours_target": r.get("annual_hours_target"),
        "shift_starts": list(r.get("shift_starts") or []),
        "min_per_shift": r.get("min_per_shift"),
        "rotation_style": r.get("rotation_style") or "rotating",
        "rotation_variations": list(r.get("rotation_variations") or []),
        "phase_overrides": r.get("phase_overrides"),
        "pattern_slot_map": r.get("pattern_slot_map"),
        "lock_officers": True,
        "lock_length": True,
        "lock_starts": True,
        "lock_min_ps": True,
        "lock_style": True,
    }


def projected_annual_for_pattern(
    variation: str,
    shift_length_hours: float,
    *,
    style: str = "rotating",
) -> Optional[float]:
    """Live annual hours from multi-block pattern text (UI calculator)."""
    try:
        from logic.rotation_patterns import build_pattern, projected_annual_hours

        p = build_pattern(
            variation,
            style=style if style in ("fixed", "rotating") else None,
        )
        return float(projected_annual_hours(p, float(shift_length_hours)))
    except Exception:
        return None


def multi_block_annual_lines(
    variations: Sequence[str],
    shift_length_hours: float,
    *,
    style: str = "rotating",
    target: float = 2008.0,
    variance: float = 20.0,
) -> List[str]:
    lines: List[str] = []
    hours: List[float] = []
    for v in variations or []:
        h = projected_annual_for_pattern(v, shift_length_hours, style=style)
        if h is None:
            lines.append(f"{v}: (invalid pattern)")
            continue
        hours.append(h)
        flag = "OK" if abs(h - target) <= variance + 1e-6 else "OFF"
        lines.append(f"{v}: ~{h:.1f}h/yr [{flag}]")
    if hours:
        avg = sum(hours) / len(hours)
        lines.insert(0, f"Mean ~{avg:.1f}h · target {target:g}±{variance:g}")
    return lines


def form_snapshot_path() -> Path:
    root = Path(__file__).resolve().parent.parent
    d = root / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d / "sim_form_last.json"


def save_form_snapshot(data: Dict[str, Any]) -> Dict[str, Any]:
    path = form_snapshot_path()
    try:
        payload = dict(data or {})
        payload["saved_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        return {"success": True, "path": str(path)}
    except Exception as exc:
        return {"success": False, "message": str(exc)}


def load_form_snapshot() -> Optional[Dict[str, Any]]:
    path = form_snapshot_path()
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def load_last_simulator_constraints() -> Optional[Dict[str, Any]]:
    """Last user-saved simulator form, else last optimized plan config.

    Never invents product defaults — returns None when user has not saved yet.
    """
    snap = load_form_snapshot()
    if snap and isinstance(snap, dict) and len(snap) > 1:
        return snap
    try:
        from logic.optimized_schedule_apply import get_last_optimized_plan

        last = get_last_optimized_plan()
        if last and isinstance(last.get("config"), dict) and last["config"]:
            cfg = dict(last["config"])
            # Normalize to form-payload-ish keys for UI restore
            return {
                "from_last_plan": True,
                "rotation": cfg.get("rotation_type"),
                "officers": cfg.get("num_officers"),
                "length": cfg.get("shift_length_hours"),
                "annual": cfg.get("annual_hours_target"),
                "annual_var": cfg.get("annual_hours_variance"),
                "starts": (
                    ", ".join(cfg["shift_starts"])
                    if isinstance(cfg.get("shift_starts"), list)
                    else cfg.get("shift_starts")
                ),
                "min_ps": cfg.get("min_per_shift"),
                "variations": (
                    " | ".join(cfg["rotation_variations"])
                    if isinstance(cfg.get("rotation_variations"), list)
                    else cfg.get("rotation_variations")
                ),
                "use_officers": cfg.get("num_officers") is not None,
                "use_length": cfg.get("shift_length_hours") is not None,
                "use_starts": bool(cfg.get("shift_starts")),
                "use_247": bool(cfg.get("coverage_247")),
                "use_windows": bool(cfg.get("use_extra_windows")),
                "windows": list(cfg.get("extra_windows") or []),
                "use_nearby": int(cfg.get("nearby_start_hops") or 0) > 0,
                "nearby_hops": cfg.get("nearby_start_hops", 1),
                "allow_offday": bool(cfg.get("allow_offday_coverage")),
                "use_annual": cfg.get("annual_hours_target") is not None,
                "use_style": bool(cfg.get("rotation_variations") or cfg.get("rotation_style")),
                "use_rotation": bool(cfg.get("rotation_type")),
                "rot_style": ("Rotating" if (cfg.get("rotation_style") or "").lower() == "rotating" else "Fixed"),
                "coverage_247": cfg.get("coverage_247"),
            }
    except Exception:
        pass
    return None


def export_form_config_json(data: Dict[str, Any], *, filename: Optional[str] = None) -> Dict[str, Any]:
    path = _exports_dir() / (filename or f"simulator_config_{time.strftime('%Y%m%d_%H%M%S')}.json")
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    return {"success": True, "path": str(path)}


def import_form_config_json(path_str: str) -> Dict[str, Any]:
    p = Path(path_str)
    if not p.is_file():
        return {"success": False, "message": f"Not found: {path_str}"}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"success": False, "message": "Config must be a JSON object"}
        return {"success": True, "config": data}
    except Exception as exc:
        return {"success": False, "message": str(exc)}


def search_history_path() -> Path:
    root = Path(__file__).resolve().parent.parent
    d = root / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d / "optimizer_search_history.json"


def append_search_history(entry: Dict[str, Any], *, limit: int = 20) -> None:
    path = search_history_path()
    rows: List[Dict] = []
    if path.is_file():
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(rows, list):
                rows = []
        except Exception:
            rows = []
    rows.insert(
        0,
        {
            "at": time.strftime("%Y-%m-%d %H:%M:%S"),
            **{
                k: entry.get(k)
                for k in (
                    "success",
                    "message",
                    "num_officers",
                    "wall_time_ms",
                    "scenarios_evaluated",
                    "hard_ok",
                )
            },
        },
    )
    path.write_text(json.dumps(rows[:limit], indent=2), encoding="utf-8")


def list_search_history(*, limit: int = 10) -> List[Dict]:
    path = search_history_path()
    if not path.is_file():
        return []
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
        return list(rows)[:limit] if isinstance(rows, list) else []
    except Exception:
        return []


def weekend_night_heat_lines(result: Optional[Dict[str, Any]] = None) -> List[str]:
    """Summarize Fri/Sat night risk from metrics / coverage."""
    r = result or {}
    m = r.get("metrics") or (r.get("best") or {}).get("metrics") or {}
    lines = ["Weekend Night Heat"]
    win_f = m.get("extra_window_failures")
    c247 = m.get("coverage_247_failures")
    hard = m.get("hard_constraints_ok")
    lines.append(f"Hard OK: {hard}")
    lines.append(f"Window shortfalls: {win_f if win_f is not None else '—'}")
    lines.append(f"24/7 shortfalls: {c247 if c247 is not None else '—'}")
    coverage = r.get("coverage_by_day") or []
    fri_sat = 0
    thin = 0
    for day in coverage:
        if not isinstance(day, dict):
            continue
        d = day.get("date") or ""
        try:
            from datetime import date as _date

            parts = str(d).split("-")
            if len(parts) == 3:
                wd = _date(int(parts[0]), int(parts[1]), int(parts[2])).weekday()
                if wd in (4, 5):
                    fri_sat += 1
                    if day.get("high_risk_night") or int(day.get("working_officers") or 99) < 2:
                        thin += 1
        except Exception:
            continue
    if fri_sat:
        lines.append(f"Fri/Sat days in view: {fri_sat} · thin/risk flags: {thin}")
    return lines


# ── Pins / multi-scenario / undo ─────────────────────────────────────────────


def _pins_path() -> Path:
    root = Path(__file__).resolve().parent.parent
    d = root / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d / "optimizer_pinned_options.json"


def list_pinned_options() -> List[Dict[str, Any]]:
    p = _pins_path()
    if not p.is_file():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return list(data) if isinstance(data, list) else []
    except Exception:
        return []


def pin_option(row: Dict[str, Any], *, label: str = "") -> Dict[str, Any]:
    pins = list_pinned_options()
    entry = {
        "pinned_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "label": label or f"Option {row.get('rank') or len(pins) + 1}",
        "row": {
            k: row.get(k)
            for k in (
                "rank",
                "num_officers",
                "shift_length_hours",
                "shift_starts",
                "rotation_variations",
                "rotation_type",
                "min_per_shift",
                "hard_constraints_ok",
                "summary",
                "phase_overrides",
                "pattern_slot_map",
                "annual_hours_target",
                "human_metrics",
                "failed_constraints",
            )
        },
    }
    pins.insert(0, entry)
    _pins_path().write_text(json.dumps(pins[:30], indent=2, default=str), encoding="utf-8")
    return {"success": True, "count": len(pins[:30]), "label": entry["label"]}


def unpin_option(index: int = 0) -> Dict[str, Any]:
    pins = list_pinned_options()
    if not pins or index < 0 or index >= len(pins):
        return {"success": False, "message": "No pin at index"}
    pins.pop(index)
    _pins_path().write_text(json.dumps(pins, indent=2, default=str), encoding="utf-8")
    return {"success": True, "count": len(pins)}


def scenario_slots_path() -> Path:
    root = Path(__file__).resolve().parent.parent / "logs"
    root.mkdir(parents=True, exist_ok=True)
    return root / "optimizer_scenario_slots.json"


def save_scenario_slot(
    slot: str,
    *,
    config: Optional[Dict] = None,
    result: Optional[Dict] = None,
    ranked_row: Optional[Dict] = None,
) -> Dict[str, Any]:
    key = (slot or "A").strip().upper()[:1]
    if key not in ("A", "B", "C"):
        key = "A"
    path = scenario_slots_path()
    data: Dict[str, Any] = {}
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    data[key] = {
        "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "config": config or {},
        "result_success": bool((result or {}).get("success")),
        "message": (result or {}).get("message"),
        "metrics": (result or {}).get("metrics"),
        "ranked_row": ranked_row,
        "best": (result or {}).get("best"),
    }
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    return {"success": True, "slot": key}


def load_scenario_slots() -> Dict[str, Any]:
    path = scenario_slots_path()
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


# ── Heat map (text + optional PNG) ───────────────────────────────────────────


def coverage_heat_grid(result: Optional[Dict[str, Any]] = None) -> List[str]:
    """Day × shift-start heat text grid from coverage_by_day."""
    r = result or {}
    coverage = r.get("coverage_by_day") or []
    if not coverage:
        return ["No coverage_by_day in result — run Generate or load an option first."]
    lines = ["Coverage Heat (working officers by day · shift counts)"]
    lines.append(f"{'Date':12} {'Work':>4}  Shift bands")
    for day in coverage[:31]:
        if not isinstance(day, dict):
            continue
        d = str(day.get("date") or "")[:10]
        w = day.get("working_officers")
        counts = day.get("shift_counts") or {}
        if isinstance(counts, dict):
            band = " ".join(f"{k}:{v}" for k, v in sorted(counts.items())[:8])
        else:
            band = str(counts)
        risk = " !" if day.get("high_risk_night") else ""
        lines.append(f"{d:12} {w if w is not None else '—':>4}  {band}{risk}")
    return lines


def _heat_color(value: float, vmax: float) -> Tuple[int, int, int]:
    """Yellow→orange→red scale (no matplotlib)."""
    if vmax <= 0:
        return (40, 48, 64)
    t = max(0.0, min(1.0, float(value) / vmax))
    # dark blue-gray empty → gold → red
    r = int(40 + t * 200)
    g = int(48 + (1.0 - abs(t - 0.45) * 1.2) * 140)
    b = int(64 + (1.0 - t) * 40)
    return (min(255, r), min(255, max(0, g)), min(255, max(0, b)))


def export_coverage_heat_png(
    result: Optional[Dict[str, Any]] = None,
    *,
    filename: Optional[str] = None,
) -> Dict[str, Any]:
    """Day×hour occupancy PNG via Pillow (no matplotlib required)."""
    r = result or {}
    coverage = r.get("coverage_by_day") or []
    path = _exports_dir() / (filename or f"coverage_heat_{time.strftime('%Y%m%d_%H%M%S')}.png")
    days: List[str] = []
    matrix: List[List[int]] = []
    for day in coverage[:21]:
        if not isinstance(day, dict):
            continue
        days.append(str(day.get("date") or "")[:10])
        row = [0] * 24
        counts = day.get("shift_counts") or {}
        try:
            work = int(day.get("working_officers") or 0)
        except (TypeError, ValueError):
            work = 0
        if isinstance(counts, dict) and counts:
            for k, v in counts.items():
                try:
                    h = int(str(k).split(":")[0])
                    row[h % 24] = int(v)
                except (TypeError, ValueError):
                    pass
        else:
            row[12] = work
        matrix.append(row)
    # Always write text companion
    txt = _exports_dir() / path.name.replace(".png", ".txt")
    txt.write_text("\n".join(coverage_heat_grid(r)), encoding="utf-8")
    if not matrix:
        return {
            "success": True,
            "path": str(txt),
            "format": "text",
            "message": "No coverage_by_day — text only",
        }
    try:
        from PIL import Image, ImageDraw, ImageFont

        cell_w, cell_h = 28, 22
        left, top = 96, 36
        right, bottom = 24, 24
        w = left + 24 * cell_w + right
        h = top + len(matrix) * cell_h + bottom
        img = Image.new("RGB", (w, h), (12, 26, 46))
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.load_default()
        except Exception:
            font = None
        vmax = max(max(row) for row in matrix) or 1
        draw.text((8, 8), "Coverage heat (shift-start counts)", fill=(230, 236, 244), font=font)
        for hi in range(0, 24, 2):
            draw.text(
                (left + hi * cell_w + 4, top - 14),
                f"{hi:02d}",
                fill=(154, 171, 196),
                font=font,
            )
        for yi, row in enumerate(matrix):
            label = days[yi] if yi < len(days) else str(yi)
            draw.text((4, top + yi * cell_h + 4), label[-8:], fill=(214, 230, 255), font=font)
            for xi, val in enumerate(row):
                x0 = left + xi * cell_w
                y0 = top + yi * cell_h
                draw.rectangle(
                    [x0, y0, x0 + cell_w - 1, y0 + cell_h - 1],
                    fill=_heat_color(val, vmax),
                    outline=(30, 45, 70),
                )
                if val:
                    draw.text(
                        (x0 + 8, y0 + 4),
                        str(val),
                        fill=(255, 255, 255) if val > vmax * 0.5 else (20, 20, 20),
                        font=font,
                    )
        img.save(path, format="PNG")
        return {
            "success": True,
            "path": str(path),
            "text_path": str(txt),
            "format": "png",
        }
    except Exception as exc:
        return {
            "success": True,
            "path": str(txt),
            "format": "text",
            "message": f"PNG failed ({exc}); text written",
        }


# ── Window failure drill-down ────────────────────────────────────────────────


def explain_window_failures(result: Optional[Dict[str, Any]] = None) -> List[str]:
    """Per-date window / night shortfalls from coverage + metrics."""
    r = result or {}
    m = r.get("metrics") or {}
    lines = ["Window Failure Drill-Down"]
    lines.append(
        f"Total window shortfalls: {m.get('extra_window_failures', '—')} / checks {m.get('extra_window_checks', '—')}"
    )
    lines.append(f"24/7 shortfalls: {m.get('coverage_247_failures', '—')}")
    coverage = r.get("coverage_by_day") or []
    hit = 0
    for day in coverage:
        if not isinstance(day, dict):
            continue
        risk = day.get("high_risk_night")
        work = day.get("working_officers")
        try:
            w = int(work) if work is not None else None
        except (TypeError, ValueError):
            w = None
        if risk or (w is not None and w < 2):
            hit += 1
            counts = day.get("shift_counts") or {}
            band = ", ".join(f"{k}:{v}" for k, v in sorted(counts.items())) if isinstance(counts, dict) else ""
            lines.append(
                f"  · {day.get('date')}: working={work}"
                + (" · high_risk_night" if risk else "")
                + (f" · {band}" if band else "")
            )
        if hit >= 20:
            lines.append("  … truncated")
            break
    if hit == 0:
        lines.append("No thin Fri/Sat or high-risk nights flagged in coverage grid.")
        if int(m.get("extra_window_failures") or 0) > 0:
            lines.append("Metrics still report window shortfalls — re-run option load for day detail.")
    return lines


# ── Share best option ────────────────────────────────────────────────────────


def format_share_message(result: Optional[Dict[str, Any]] = None) -> str:
    r = result or {}
    best = r.get("best") or {}
    lines = [
        "Chronos staffing recommendation",
        r.get("message") or "",
        format_checklist_line(best),
    ]
    if best.get("num_officers") is not None:
        lines.append(f"Officers: {best.get('num_officers')}")
    starts = best.get("shift_starts") or []
    if starts:
        lines.append("Starts: " + ", ".join(str(s) for s in starts))
    vars_ = best.get("rotation_variations") or []
    if vars_:
        lines.append("Multi-block: " + " | ".join(str(v) for v in vars_))
    if best.get("summary"):
        lines.append(str(best["summary"]))
    lines.append(f"Layouts checked: {r.get('scenarios_evaluated', '—')}")
    lines.append(f"Search time: {r.get('wall_time_ms', '—')} ms")
    return "\n".join(x for x in lines if x)


def export_share_eml(
    result: Optional[Dict[str, Any]] = None,
    *,
    to_addr: str = "",
    subject: str = "Chronos staffing option",
) -> Dict[str, Any]:
    body = format_share_message(result)
    path = _exports_dir() / f"optimizer_share_{time.strftime('%Y%m%d_%H%M%S')}.eml"
    # Minimal .eml for Outlook / mail clients
    content = (
        f"To: {to_addr or 'supervisor@example.local'}\n"
        f"Subject: {subject}\n"
        f"Content-Type: text/plain; charset=utf-8\n"
        f"\n"
        f"{body}\n"
    )
    path.write_text(content, encoding="utf-8")
    return {"success": True, "path": str(path), "body": body}


# ── Fairness with roster names ───────────────────────────────────────────────


def fairness_report_with_roster(result: Optional[Dict[str, Any]] = None) -> List[str]:
    lines = fairness_report(result)
    try:
        from logic.officers import get_officers_by_seniority

        officers = get_officers_by_seniority() or []
    except Exception:
        return lines
    if not officers:
        return lines
    names = []
    for o in officers[:40]:
        nm = o.get("name") or o.get("full_name") or f"#{o.get('id')}"
        names.append(str(nm))
    lines.append("")
    lines.append("Roster names (seniority order, for mapping slots):")
    for i, nm in enumerate(names):
        lines.append(f"  Slot~{i + 1}: {nm}")
    # Map first N slots to roster order if counts match
    slots = (result or {}).get("officer_slots") or []
    if slots and names:
        lines.append("")
        lines.append("Suggested name map (slot order ↔ roster seniority):")
        for i, s in enumerate(slots[: len(names)]):
            if not isinstance(s, dict):
                s = getattr(s, "__dict__", {}) or {}
            lines.append(
                f"  {s.get('label') or i}: {names[i]} · "
                f"{s.get('shift_start')} · ~{s.get('projected_annual_hours', '—')}h"
            )
    return lines


# ── Constraint weight helpers ────────────────────────────────────────────────


def default_weight_map() -> Dict[str, float]:
    return {
        "coverage_247": 100.0,
        "windows": 90.0,
        "gaps": 80.0,
        "flsa": 70.0,
        "annual": 40.0,
        "headcount": 10.0,
    }


def weights_from_sliders(values: Dict[str, float]) -> Dict[str, float]:
    base = default_weight_map()
    for k, v in (values or {}).items():
        if k in base:
            try:
                base[k] = float(v)
            except (TypeError, ValueError):
                pass
    return base


# ── F1 Coverage Heatmap ──────────────────────────────────────────────────────


def shift_coverage_heatmap(
    result: Optional[Dict[str, Any]] = None,
    *,
    step_minutes: int = 30,
) -> Dict[str, Any]:
    """F1 — 7×(24*60/step) coverage count matrix from a sim result.

    Returns a dict with:
      matrix[weekday][slot] = int coverage count (0..N)
      weekday: 0=Mon…6=Sun
      slot: 0 = 00:00, 1 = 00:30, … 47 = 23:30 (for step=30)
      thin_slots: list of {weekday, slot, time, count} where count < threshold
    """
    r = result or {}
    best = r.get("best") or {}
    slots = best.get("officer_slots") or r.get("officer_slots") or []
    starts = best.get("shift_starts") or r.get("shift_starts") or []
    length_h = float(best.get("shift_length_hours") or r.get("shift_length_hours") or 8.0)
    sim_days = int(best.get("simulation_days") or r.get("simulation_days") or 28)

    n_per_day = (24 * 60) // step_minutes
    matrix: List[List[int]] = [[0] * n_per_day for _ in range(7)]

    if not slots or not starts:
        return {
            "success": False,
            "message": "No officer slot data in result",
            "matrix": matrix,
            "thin_slots": [],
        }

    length_min = max(30, int(round(length_h * 60)))

    def _hm(s: str) -> int:
        try:
            h, m = map(int, (s or "00:00").split(":"))
            return h * 60 + m
        except Exception:
            return 0

    # Build a simple per-weekday×slot accumulator from assigned starts
    for s in slots:
        if not isinstance(s, dict):
            s = getattr(s, "__dict__", {}) or {}
        work_flags = s.get("work_flags") or s.get("duty_vector") or []
        start = s.get("shift_start") or s.get("home_start") or (starts[0] if starts else "06:00")
        sm = _hm(str(start))
        # Use first sim_days days
        from datetime import date

        sim_start = date.today()
        try:
            sim_start_raw = best.get("sim_start") or r.get("sim_start")
            if sim_start_raw:
                sim_start = date.fromisoformat(str(sim_start_raw))
        except Exception:
            pass
        for d in range(min(sim_days, max(len(work_flags), 1))):
            working = bool(work_flags[d]) if d < len(work_flags) else False
            if not working:
                continue
            wd = (sim_start.weekday() + d) % 7
            end_min = sm + length_min
            t = sm
            while t < end_min:
                slot_idx = (t % (24 * 60)) // step_minutes
                matrix[wd][slot_idx] += 1
                t += step_minutes

    # Normalize: divide by number of each weekday in sim_days to get avg coverage
    from collections import Counter as _Counter
    from datetime import date, timedelta

    wd_count: Dict[int, int] = _Counter((date.today() + timedelta(days=d)).weekday() for d in range(sim_days))
    norm_matrix: List[List[float]] = []
    for wd in range(7):
        n = max(1, wd_count.get(wd, 1))
        norm_matrix.append([round(matrix[wd][s] / n, 2) for s in range(n_per_day)])

    # Identify thin slots
    thin_threshold = max(1, int(best.get("coverage_247") or r.get("coverage_247") or 1))
    thin_slots: List[Dict[str, Any]] = []
    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    for wd in range(7):
        for s in range(n_per_day):
            c = norm_matrix[wd][s]
            if c < thin_threshold:
                hh = (s * step_minutes) // 60
                mm = (s * step_minutes) % 60
                thin_slots.append(
                    {
                        "weekday": wd,
                        "weekday_name": day_names[wd],
                        "slot": s,
                        "time": f"{hh:02d}:{mm:02d}",
                        "avg_coverage": c,
                        "threshold": thin_threshold,
                    }
                )

    thin_slots.sort(key=lambda x: x["avg_coverage"])

    return {
        "success": True,
        "matrix": norm_matrix,
        "thin_slots": thin_slots[:24],  # top 24 worst slots
        "n_per_day": n_per_day,
        "step_minutes": step_minutes,
        "day_labels": day_names,
        "coverage_threshold": thin_threshold,
        "message": (
            f"{len(thin_slots)} thin slot(s) below threshold {thin_threshold}"
            if thin_slots
            else "All slots meet coverage threshold"
        ),
    }


# ── F2 Specific Constraint Relaxations ──────────────────────────────────────


def suggest_relaxations(
    result: Optional[Dict[str, Any]] = None,
    constraints: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """F2 — when no hard-OK option found, return specific numbered relaxations
    ranked by minimum change needed to likely flip a near-miss to hard-OK.

    Each entry has:
      rank, category, action, delta, why, estimated_unlock (bool)
    """
    r = result or {}
    c = constraints or {}
    suggestions: List[Dict[str, Any]] = []

    if r.get("success") and (r.get("best") or {}).get("hard_constraints_ok"):
        return []  # Already passing

    near = r.get("near_misses") or []
    best_miss = r.get("best") if not (r.get("best") or {}).get("hard_constraints_ok") else None
    if not best_miss and near:
        best_miss = near[0]

    m = (best_miss or {}).get("metrics") or {}
    hm = (best_miss or {}).get("human_metrics") or {}

    # --- Window violations ---
    win_fails = int(m.get("extra_window_failures") or hm.get("extra_window_failures") or 0)
    if win_fails > 0:
        # Try to quantify: how short?
        shortfall = win_fails  # slots short; 1 slot ~= 30 min window period
        cur_n = int((best_miss or {}).get("num_officers") or c.get("officers") or 0)
        suggestions.append(
            {
                "rank": 1,
                "category": "headcount",
                "action": f"Raise officer count from {cur_n} to {cur_n + 1}",
                "delta": "+1 officer",
                "why": (
                    f"Best near-miss missed {win_fails} window slot(s). "
                    f"One extra officer on the evening pack often covers Fri/Sat shortfalls."
                ),
                "estimated_unlock": win_fails <= 3,
            }
        )
        win_list = c.get("windows") or []
        for w in win_list if isinstance(win_list, list) else []:
            if not isinstance(w, dict) or not w.get("enabled", True):
                continue
            mn = int(w.get("min_officers") or 0)
            if mn >= 2:
                suggestions.append(
                    {
                        "rank": 2,
                        "category": "window",
                        "action": f"Lower '{w.get('label', 'window')}' min from {mn} to {mn - 1}",
                        "delta": f"min_officers {mn} → {mn - 1}",
                        "why": f"{win_fails} shortfall(s) on this window. Reducing by 1 often resolves thin nights.",
                        "estimated_unlock": win_fails <= shortfall,
                    }
                )

    # --- 24/7 coverage failures ---
    cov_fails = int(m.get("coverage_247_failures") or hm.get("coverage_247_failures") or 0)
    if cov_fails > 0:
        cur_n = int((best_miss or {}).get("num_officers") or c.get("officers") or 0)
        cov247 = int(c.get("cov247") or 1)
        suggestions.append(
            {
                "rank": 1 if not suggestions else max(s["rank"] for s in suggestions) + 1,
                "category": "headcount",
                "action": f"Raise officer count from {cur_n} to {cur_n + cov247}",
                "delta": f"+{cov247} officer(s)",
                "why": f"{cov_fails} 24/7 slot(s) below minimum {cov247}. Need at least {cov247} on-duty at all times.",
                "estimated_unlock": cov_fails <= 5,
            }
        )
        if cov247 > 1:
            suggestions.append(
                {
                    "rank": max(s["rank"] for s in suggestions) + 1,
                    "category": "coverage_247",
                    "action": f"Lower 24/7 minimum from {cov247} to {cov247 - 1}",
                    "delta": f"cov247 {cov247} → {cov247 - 1}",
                    "why": f"{cov_fails} slots short. Reducing 24/7 minimum by 1 may allow the current roster to pass.",
                    "estimated_unlock": cov_fails <= 8,
                }
            )

    # --- Annual hours band violations ---
    annual_out = int(m.get("annual_band_outside") or hm.get("annual_band_outside") or 0)
    annual_mean = float(m.get("avg_annual_hours") or 0)
    annual_target = float(c.get("annual") or 0) or annual_mean
    annual_var = float(c.get("annual_var") or 20)
    if annual_out > 0 and annual_mean > 0:
        dist = abs(annual_mean - annual_target)
        min_var_needed = round(dist + 5, 0)
        suggestions.append(
            {
                "rank": max((s["rank"] for s in suggestions), default=0) + 1,
                "category": "annual_hours",
                "action": f"Widen annual variance from ±{annual_var:.0f}h to ±{min_var_needed:.0f}h",
                "delta": f"annual_var {annual_var:.0f} → {min_var_needed:.0f}",
                "why": (
                    f"{annual_out} officer(s) outside ±{annual_var:.0f}h band. "
                    f"Pattern projects ~{annual_mean:.0f}h; target is {annual_target:.0f}h (gap {dist:.0f}h)."
                ),
                "estimated_unlock": annual_out <= 2,
            }
        )

    # --- Gap / min-per-shift violations ---
    gap_fails = int(m.get("gap_events") or m.get("zero_staff_slots") or hm.get("gap_events") or 0)
    if gap_fails > 0:
        suggestions.append(
            {
                "rank": max((s["rank"] for s in suggestions), default=0) + 1,
                "category": "gaps",
                "action": "Add evening start band (e.g. 19:00) to cover thin periods",
                "delta": "add start band",
                "why": (
                    f"{gap_fails} band-gap slot(s) found. "
                    "An additional 19:00 start often fills night coverage holes without adding officers."
                ),
                "estimated_unlock": gap_fails <= 6,
            }
        )

    if not suggestions:
        suggestions.append(
            {
                "rank": 1,
                "category": "general",
                "action": "Free officer count and shift starts, then run Find Best again",
                "delta": "free dimensions",
                "why": "No specific failure data available from near-miss. Running with free officer count will find the minimum needed.",
                "estimated_unlock": False,
            }
        )

    # De-dupe by action text and sort by rank, likely-unlock first
    seen_actions: set = set()
    out = []
    for s in sorted(suggestions, key=lambda x: (x["rank"], 0 if x.get("estimated_unlock") else 1)):
        if s["action"] not in seen_actions:
            seen_actions.add(s["action"])
            out.append(s)

    return out
