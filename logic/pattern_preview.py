"""Pattern calendar preview + compliance strip (soft-only).

Vertex42-style on/off cycle calendar before full 56d sim.
Compliance strip = rest / FLSA / annual work-frac hints — never hard Find Best gates.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from logic.rotation_patterns import (
    ROTATION_STYLE_ROTATING,
    build_pattern,
    parse_variation_set,
    projected_annual_hours,
    validate_variation_set,
)

COLOR_ON = "#22c55e"
COLOR_OFF = "#1e293b"
COLOR_PHASE = "#3B7DD8"


def _f(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def parse_multi_block_texts(raw: str) -> List[str]:
    """Split '6-2,5-3 | 6-3,5-2' into variation texts."""
    return [p.strip() for p in (raw or "").split("|") if p.strip()]


def pattern_calendar_preview(
    *,
    variations_text: str = "",
    style: str = "rotating",
    days: int = 28,
    phase: int = 0,
    squad_preset: str = "",
) -> Dict[str, Any]:
    """Build compact on/off calendars for multi-block variations (or empty).

    Returns rows[{label, cycle, work_days, cells[{on, color, day}]}]
    """
    texts = parse_multi_block_texts(variations_text)
    st = (style or "rotating").lower()
    if st.startswith("fix"):
        st = "fixed"
    else:
        st = ROTATION_STYLE_ROTATING

    rows: List[Dict[str, Any]] = []
    errors: List[str] = []
    if not texts:
        if squad_preset:
            return {
                "success": True,
                "mode": "squad",
                "message": f"Squad preset: {squad_preset} (duty ring in sim — no multi-block grid)",
                "rows": [],
                "errors": [],
            }
        return {
            "success": False,
            "mode": "empty",
            "message": "Enter multi-block patterns (e.g. 6-2,5-3 | 6-3,5-2) for calendar preview",
            "rows": [],
            "errors": [],
        }

    try:
        patterns = parse_variation_set(texts, style=st)
    except ValueError as exc:
        # try each alone for partial preview
        patterns = []
        for t in texts:
            try:
                patterns.append(build_pattern(t, style=st if "," in t or st == "fixed" else st))
            except ValueError as e2:
                errors.append(f"{t}: {e2}")
        if not patterns:
            return {
                "success": False,
                "mode": "error",
                "message": str(exc),
                "rows": [],
                "errors": errors or [str(exc)],
            }

    ok, msg = validate_variation_set(patterns) if len(patterns) > 1 else (True, "OK")
    if not ok:
        errors.append(msg)

    n_days = max(7, min(56, int(days or 28)))
    for i, p in enumerate(patterns):
        pp = p.with_phase(int(phase or 0) + i)  # mild stagger display for multi
        vec = pp.duty_vector()
        if not vec:
            continue
        cells = []
        for d in range(n_days):
            on = bool(vec[(d + pp.phase) % len(vec)])
            cells.append(
                {
                    "day": d + 1,
                    "on": on,
                    "color": COLOR_ON if on else COLOR_OFF,
                    "label": "ON" if on else "OFF",
                }
            )
        rows.append(
            {
                "label": p.label or p.to_text() or f"Var {i + 1}",
                "cycle": p.cycle_length,
                "work_days": p.work_days_per_cycle(),
                "work_frac": round(p.work_days_per_cycle() / max(p.cycle_length, 1), 3),
                "cells": cells,
            }
        )

    return {
        "success": bool(rows),
        "mode": "multi_block",
        "message": (f"{len(rows)} pattern(s) · {n_days}d preview" + (f" · {errors[0]}" if errors else "")),
        "rows": rows,
        "errors": errors,
        "days": n_days,
    }


def compliance_strip(
    *,
    shift_length_hours: Optional[float] = None,
    annual_hours_target: Optional[float] = None,
    annual_hours_variance: Optional[float] = None,
    variations_text: str = "",
    style: str = "rotating",
    coverage_247: int = 0,
    min_rest_hours: float = 0.0,
    max_consecutive_work_days: int = 0,
    flsa_period_days: int = 28,
    avoid_flsa: bool = False,
    num_officers: int = 0,
    min_per_shift: int = 0,
) -> Dict[str, Any]:
    """Soft compliance / fit hints — not hard gates for Find Best."""
    items: List[Dict[str, Any]] = []
    length = _f(shift_length_hours, 0.0) if shift_length_hours is not None else None
    annual = _f(annual_hours_target, 0.0) if annual_hours_target is not None else None
    var = _f(annual_hours_variance, 40.0)

    texts = parse_multi_block_texts(variations_text)
    patterns = []
    if texts and length and length > 0:
        try:
            st = "fixed" if (style or "").lower().startswith("fix") else "rotating"
            patterns = parse_variation_set(texts, style=st)
        except ValueError as exc:
            items.append(
                {
                    "key": "pattern",
                    "ok": False,
                    "level": "warn",
                    "label": "Pattern parse",
                    "detail": str(exc)[:120],
                }
            )

    # Annual work-frac fit (soft)
    if patterns and length and annual and annual > 0:
        proj = [projected_annual_hours(p, length) for p in patterns]
        mean_p = sum(proj) / len(proj)
        dist = abs(mean_p - annual)
        ok = dist <= max(var, 20.0)
        items.append(
            {
                "key": "annual_fit",
                "ok": ok,
                "level": "ok" if ok else "warn",
                "label": "Annual vs pattern",
                "detail": f"pattern ~{mean_p:.0f}h · target {annual:.0f}h · Δ{dist:.0f}h (band ±{var:.0f})",
            }
        )
        for p, ph in zip(patterns, proj):
            items.append(
                {
                    "key": f"var_{p.to_text()}",
                    "ok": abs(ph - annual) <= max(var, 20.0),
                    "level": "ok" if abs(ph - annual) <= max(var, 20.0) else "warn",
                    "label": f"  {p.label or p.to_text()}",
                    "detail": f"~{ph:.0f}h/yr · work {p.work_days_per_cycle()}/{p.cycle_length}d",
                }
            )
    elif annual and length and length > 0:
        days_work = annual / length
        frac = days_work / 365.25
        ok = 0.35 <= frac <= 0.75
        items.append(
            {
                "key": "work_frac",
                "ok": ok,
                "level": "ok" if ok else "warn",
                "label": "Implied work fraction",
                "detail": f"{frac:.0%} of year on duty @ {length:g}h (soft check)",
            }
        )

    # Rest / consecutive — soft advisory when user locked fatigue
    if min_rest_hours and length and length > 0:
        # same-start daily rest = 24 - length
        same_start_rest = 24.0 - length
        ok = same_start_rest + 0.01 >= float(min_rest_hours)
        items.append(
            {
                "key": "rest",
                "ok": ok,
                "level": "ok" if ok else "warn",
                "label": "Rest between same-start days",
                "detail": (
                    f"~{same_start_rest:g}h gap vs min rest {min_rest_hours:g}h (overnight packs need full sim)"
                ),
            }
        )
    if max_consecutive_work_days and patterns:
        for p in patterns:
            # longest ON block
            longest = max((b.days_on for b in p.blocks), default=0)
            ok = longest <= int(max_consecutive_work_days)
            items.append(
                {
                    "key": f"consec_{p.to_text()}",
                    "ok": ok,
                    "level": "ok" if ok else "warn",
                    "label": f"Max consecutive ON ({p.to_text()})",
                    "detail": f"longest block {longest}d vs limit {max_consecutive_work_days}",
                }
            )

    # FLSA period load estimate (soft)
    if length and patterns:
        frac = patterns[0].work_days_per_cycle() / max(patterns[0].cycle_length, 1)
        period = max(7, int(flsa_period_days or 28))
        period_h = round(length * frac * period, 1)
        # §207(k) approx thresholds by period length
        thresh_map = {7: 43, 14: 86, 21: 129, 28: 171}
        thresh = thresh_map.get(period, 171 * period / 28.0)
        pct = 100.0 * period_h / max(thresh, 1)
        over = pct > 100 and avoid_flsa
        items.append(
            {
                "key": "flsa",
                "ok": not over,
                "level": "warn" if pct > 95 else "ok",
                "label": f"FLSA ~{period}d load (soft)",
                "detail": f"~{period_h:g}h / ~{thresh:g}h threshold ({pct:.0f}%)"
                + (" — avoid-OT locked" if avoid_flsa else ""),
            }
        )

    if coverage_247:
        items.append(
            {
                "key": "247",
                "ok": True,
                "level": "ok",
                "label": "24/7 min",
                "detail": f"min {coverage_247} on duty — hard gate in sim, not this strip",
            }
        )

    if num_officers and min_per_shift:
        items.append(
            {
                "key": "n_vs_min",
                "ok": num_officers >= min_per_shift,
                "level": "ok" if num_officers >= min_per_shift else "warn",
                "label": "N vs min/shift",
                "detail": f"N={num_officers} · min/band={min_per_shift}",
            }
        )

    warns = sum(1 for i in items if i.get("level") == "warn")
    return {
        "success": True,
        "items": items,
        "warn_count": warns,
        "summary": (
            "Compliance strip: all soft checks look OK"
            if not warns
            else f"Compliance strip: {warns} soft caution(s) — not Find Best gates"
        ),
    }


def form_preview_bundle(form: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Convenience from form_payload / config-like dict."""
    f = form or {}
    vars_raw = f.get("variations") or f.get("rotation_variations") or ""
    if isinstance(vars_raw, (list, tuple)):
        vars_raw = " | ".join(str(x) for x in vars_raw)
    style = f.get("rot_style") or f.get("rotation_style") or "rotating"
    if isinstance(style, str) and style.lower().startswith("rotat"):
        style = "rotating"
    cal = pattern_calendar_preview(
        variations_text=str(vars_raw),
        style=str(style),
        days=28,
        squad_preset=str(f.get("rotation") or f.get("rotation_type") or ""),
    )
    strip = compliance_strip(
        shift_length_hours=f.get("length") or f.get("shift_length_hours"),
        annual_hours_target=f.get("annual") or f.get("annual_hours_target"),
        annual_hours_variance=f.get("annual_var") or f.get("annual_hours_variance"),
        variations_text=str(vars_raw),
        style=str(style),
        coverage_247=int(f.get("cov247") or f.get("coverage_247") or 0),
        min_rest_hours=float(f.get("min_rest") or f.get("min_rest_hours") or 0),
        max_consecutive_work_days=int(f.get("max_consec") or f.get("max_consecutive_work_days") or 0),
        flsa_period_days=int(f.get("flsa_days") or f.get("flsa_work_period_days") or 28),
        avoid_flsa=bool(f.get("use_flsa") or f.get("avoid_flsa_overtime")),
        num_officers=int(f.get("officers") or f.get("num_officers") or 0),
        min_per_shift=int(f.get("min_ps") or f.get("min_per_shift") or 0),
    )
    return {"calendar": cal, "compliance": strip}
