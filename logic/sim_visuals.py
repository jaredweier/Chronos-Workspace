"""Coverage heatmap + officer duty Gantt data for the schedule simulator.

Pure helpers (no NiceGUI). Colors: red under min, amber thin, green OK, slate off.
Inspired by WFM coverage heat strips and Mobiscroll-style resource timelines.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# Chronos / Quasar-aligned palette
COLOR_OFF = "#1e293b"
COLOR_OK = "#22c55e"
COLOR_THIN = "#f59e0b"
COLOR_SHORT = "#ef4444"
COLOR_EMPTY = "#0f172a"
COLOR_RISK = "#f97316"


def _as_dict(obj: Any) -> Dict[str, Any]:
    if isinstance(obj, dict):
        return obj
    if hasattr(obj, "__dict__"):
        return dict(obj.__dict__)
    return {}


def _result_bundle(result: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Normalize sim / opt / ranked payloads into one view dict."""
    r = result or {}
    if r.get("best") and not r.get("coverage_by_day"):
        best = r.get("best") or {}
        # Ranked option may nest metrics only — prefer full result fields
        merged = {**best, **{k: v for k, v in r.items() if k not in ("best", "ranked")}}
        if best.get("metrics") and not merged.get("metrics"):
            merged["metrics"] = best["metrics"]
        if best.get("officer_slots") and not merged.get("officer_slots"):
            merged["officer_slots"] = best["officer_slots"]
        if best.get("coverage_by_day") and not merged.get("coverage_by_day"):
            merged["coverage_by_day"] = best["coverage_by_day"]
        return merged
    return r


def coverage_band_heatmap(
    result: Optional[Dict[str, Any]] = None,
    *,
    max_days: int = 28,
    min_per_band: Optional[int] = None,
) -> Dict[str, Any]:
    """Day × shift-start coverage grid from coverage_by_day.

    Cell value = headcount on that start. Color vs min_per_band / night soft.
    """
    r = _result_bundle(result)
    coverage = r.get("coverage_by_day") or []
    m = r.get("metrics") or {}
    if min_per_band is None:
        min_per_band = int(m.get("min_per_shift") or r.get("min_per_shift") or 0)
    try:
        min_per_band = int(min_per_band or 0)
    except (TypeError, ValueError):
        min_per_band = 0

    # Collect start keys in stable order
    starts: List[str] = []
    seen = set()
    for day in coverage[:max_days]:
        if not isinstance(day, dict):
            continue
        sc = day.get("shift_counts") or {}
        if isinstance(sc, dict):
            for k in sorted(sc.keys()):
                if k not in seen:
                    seen.add(k)
                    starts.append(str(k))
    if not starts:
        cfg_starts = r.get("shift_starts") or (r.get("best") or {}).get("shift_starts") or []
        starts = [str(s) for s in cfg_starts]

    rows: List[Dict[str, Any]] = []
    for day in coverage[:max_days]:
        if not isinstance(day, dict):
            continue
        sc = day.get("shift_counts") or {}
        if not isinstance(sc, dict):
            sc = {}
        cells = []
        for st in starts:
            try:
                val = int(sc.get(st, 0) or 0)
            except (TypeError, ValueError):
                val = 0
            if min_per_band > 0 and 0 < val < min_per_band:
                color = COLOR_THIN
                level = "thin"
            elif min_per_band > 0 and val < min_per_band:
                color = COLOR_SHORT if val == 0 else COLOR_THIN
                level = "short" if val == 0 else "thin"
            elif val <= 0:
                color = COLOR_EMPTY
                level = "empty"
            else:
                color = COLOR_OK
                level = "ok"
            if day.get("high_risk_night") and st.startswith(("19", "20", "21", "22", "23", "00", "01", "02")):
                if level in ("thin", "short", "empty"):
                    color = COLOR_RISK
            cells.append({"start": st, "count": val, "color": color, "level": level})
        rows.append(
            {
                "date": str(day.get("date") or "")[:12],
                "working": day.get("working_officers"),
                "high_risk": bool(day.get("high_risk_night")),
                "cells": cells,
            }
        )

    short_n = sum(1 for row in rows for c in row["cells"] if c["level"] in ("short", "thin"))
    return {
        "success": bool(rows),
        "starts": starts,
        "rows": rows,
        "min_per_band": min_per_band,
        "short_or_thin": short_n,
        "message": (
            f"{len(rows)} day(s) · {len(starts)} start band(s) · {short_n} thin/short cell(s)"
            if rows
            else "No coverage_by_day — run Generate or Find Best first"
        ),
    }


def officer_duty_gantt(
    result: Optional[Dict[str, Any]] = None,
    *,
    max_days: int = 28,
    max_officers: int = 24,
) -> Dict[str, Any]:
    """Officer rows × day columns from work_flags (ON = green/start tint, OFF = slate)."""
    r = _result_bundle(result)
    slots = r.get("officer_slots") or []
    coverage = r.get("coverage_by_day") or []
    dates = [str(d.get("date") or "")[:10] for d in coverage[:max_days] if isinstance(d, dict)]

    rows: List[Dict[str, Any]] = []
    for raw in slots[:max_officers]:
        s = _as_dict(raw)
        flags = s.get("work_flags") or s.get("duty_vector") or []
        if not isinstance(flags, list):
            flags = []
        start = str(s.get("shift_start") or s.get("home_start") or "—")
        label = str(s.get("label") or f"Officer {s.get('slot_id') or '?'}")
        cells = []
        n_days = max(len(dates), len(flags), 1)
        for i in range(min(max_days, n_days)):
            on = bool(flags[i]) if i < len(flags) else False
            date = dates[i] if i < len(dates) else str(i + 1)
            if on:
                # Night starts slightly cooler blue; day starts green
                try:
                    hh = int(start.split(":")[0])
                except Exception:
                    hh = 8
                color = "#3B7DD8" if (hh >= 19 or hh < 6) else COLOR_OK
                level = "on"
            else:
                color = COLOR_OFF
                level = "off"
            cells.append({"day": i, "date": date, "on": on, "color": color, "level": level})
        if not flags and not cells:
            cells = [{"day": 0, "date": "—", "on": False, "color": COLOR_EMPTY, "level": "unknown"}]
        rows.append(
            {
                "label": label,
                "start": start,
                "squad": s.get("squad") or "",
                "annual": s.get("projected_annual_hours"),
                "work_days": s.get("work_days_in_sim"),
                "cells": cells,
            }
        )

    has_flags = any(any(c.get("on") for c in row["cells"]) for row in rows)
    return {
        "success": bool(rows),
        "has_duty_flags": has_flags,
        "dates": dates[:max_days],
        "rows": rows,
        "message": (
            f"{len(rows)} officer(s) · {min(max_days, len(dates) or max((len(x['cells']) for x in rows), default=0))} day(s)"
            if rows
            else "No officer_slots — run Generate or load a ranked option"
        ),
        "hint": (
            None
            if has_flags
            else "Duty flags missing on slots — re-run Generate after update to fill Gantt ON/OFF days."
        ),
    }


def side_by_side_compare(
    plans: List[Optional[Dict[str, Any]]],
    *,
    labels: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Compact compare cards for 2–3 ranked options / results."""
    labs = labels or [f"Plan {i + 1}" for i in range(len(plans))]
    cards: List[Dict[str, Any]] = []
    for i, p in enumerate(plans[:3]):
        r = _result_bundle(p)
        m = r.get("metrics") or {}
        best = r.get("best") or r
        cards.append(
            {
                "label": labs[i] if i < len(labs) else f"Plan {i + 1}",
                "n": best.get("num_officers") or m.get("min_officers_required"),
                "starts": best.get("shift_starts") or r.get("shift_starts"),
                "length": best.get("shift_length_hours") or r.get("shift_length_hours"),
                "hard_ok": m.get("hard_constraints_ok", best.get("hard_constraints_ok")),
                "annual_avg": m.get("avg_annual_hours"),
                "win_fails": m.get("extra_window_failures"),
                "c247_fails": m.get("coverage_247_failures"),
                "night_risk": m.get("night_risk_gaps"),
                "gaps": m.get("gap_events"),
            }
        )
    return {"success": bool(cards), "cards": cards}


def heat_cell_tooltip(cell: Dict[str, Any], *, date: str = "") -> str:
    return f"{date} {cell.get('start')}: {cell.get('count')} · {cell.get('level')}"
