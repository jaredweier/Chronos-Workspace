"""Staffing product insights — conflict precheck, cost/OT/FLSA meters, fairness, demand, memo.

Used by Chronos simulator UI and optimizer ranked options. Not legal advice.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

# LE FLSA §7(k): 171 hours / 28 days (DOL Fact Sheet #8)
FLSA_LE_28_DAY_THRESHOLD = 171.0
FLSA_LE_HOURS_PER_DAY = 171.0 / 28.0


def flsa_threshold_for_period(period_days: int = 28) -> float:
    d = max(7, min(28, int(period_days or 28)))
    return round(FLSA_LE_HOURS_PER_DAY * d, 1)


def estimate_period_hours(
    *,
    shift_length_hours: float,
    duty_fraction: float = 0.5,
    period_days: int = 28,
) -> float:
    """Rough straight-time hours in an FLSA work period from length × duty fraction."""
    L = max(0.5, float(shift_length_hours or 8))
    frac = max(0.0, min(1.0, float(duty_fraction)))
    d = max(7, min(28, int(period_days or 28)))
    return round(L * frac * d, 1)


def duty_fraction_from_variations(variations: Optional[Sequence[str]]) -> float:
    if not variations:
        return 0.5
    try:
        from logic.rotation_patterns import parse_on_off_blocks

        fracs = []
        for text in variations:
            try:
                blocks = parse_on_off_blocks(str(text))
            except ValueError:
                continue
            if not blocks:
                continue
            on = sum(b.days_on for b in blocks)
            total = sum(b.length for b in blocks)
            if total:
                fracs.append(on / total)
        if fracs:
            return sum(fracs) / len(fracs)
    except Exception:
        pass
    return 0.5


def estimate_ot_cost(
    *,
    ot_hours: float,
    hourly_rate: float = 35.0,
    multiplier: float = 1.5,
) -> float:
    return round(max(0.0, float(ot_hours)) * float(hourly_rate) * float(multiplier), 2)


def _roster_avg_comp_hours() -> Optional[float]:
    """Mean comp bank across active officers when banks exist; else None."""
    try:
        from logic.officers import get_officers_by_seniority
        from logic.payroll.banks import get_officer_time_banks  # type: ignore

        hours = []
        for o in get_officers_by_seniority():
            if o.get("active") != 1:
                continue
            try:
                b = get_officer_time_banks(int(o["id"])) or {}
                h = b.get("comp_hours")
                if h is None and isinstance(b, dict):
                    h = (b.get("banks") or {}).get("comp_hours")
                if h is not None:
                    hours.append(float(h))
            except Exception:
                continue
        if hours:
            return sum(hours) / len(hours)
    except Exception:
        pass
    try:
        # No bank data — still report cap for product path
        return None
    except Exception:
        return None


def enrich_option_economics(
    row: Dict[str, Any],
    *,
    hourly_rate: float = 35.0,
    flsa_period_days: int = 28,
    variations: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Attach cost / FLSA / fairness / comp-cap fields to a ranked optimizer row."""
    out = dict(row)
    m = dict(out.get("metrics") or out.get("human_metrics") or {})
    length = float(out.get("shift_length_hours") or m.get("shift_length_hours") or 8)
    n = int(out.get("num_officers") or m.get("min_officers_required") or 0)
    vars_ = list(variations or out.get("rotation_variations") or [])
    frac = duty_fraction_from_variations(vars_)
    period_h = estimate_period_hours(shift_length_hours=length, duty_fraction=frac, period_days=flsa_period_days)
    thresh = flsa_threshold_for_period(flsa_period_days)
    # Structural OT: hours over threshold in period (per officer estimate)
    ot_per = max(0.0, period_h - thresh)
    # Extra window / 247 failures already imply OT pressure
    win_fail = int(m.get("extra_window_failures") or 0)
    c247_fail = int(m.get("coverage_247_failures") or 0)
    gap = int(m.get("gap_events") or 0)
    pressure_ot = (win_fail + c247_fail + gap) * length * 0.25
    ot_total = round(ot_per * max(n, 1) + pressure_ot, 1)
    cost = estimate_ot_cost(ot_hours=ot_total, hourly_rate=hourly_rate)

    # Fairness proxies from metrics when present
    annual_spread = float(m.get("annual_hours_spread") or 0)
    fairness = 100.0
    if annual_spread > 40:
        fairness -= min(40, (annual_spread - 40) * 0.5)
    if win_fail:
        fairness -= min(25, win_fail * 5)
    if c247_fail:
        fairness -= min(25, c247_fail * 5)
    fairness = max(0.0, round(fairness, 1))

    try:
        from config import FLSA_COMP_TIME_MAX_HOURS

        comp_cap = float(FLSA_COMP_TIME_MAX_HOURS or 480)
    except Exception:
        comp_cap = 480.0
    avg_comp = _roster_avg_comp_hours()
    # At/near cap → OT should be cash (not banked); warn product path
    force_cash = False
    comp_headroom = None
    if avg_comp is not None:
        comp_headroom = round(max(0.0, comp_cap - avg_comp), 1)
        force_cash = avg_comp >= comp_cap * 0.95
    # If structural OT is large and bank near cap, prefer cash path
    if ot_total > 0 and avg_comp is not None and avg_comp >= comp_cap * 0.9:
        force_cash = True

    econ = {
        "flsa_period_days": int(flsa_period_days),
        "flsa_threshold_hours": thresh,
        "est_period_hours_per_officer": period_h,
        "flsa_period_pct": round(100.0 * period_h / max(thresh, 1), 1),
        "est_ot_hours_total": ot_total,
        "est_ot_cost_usd": cost,
        "hourly_rate_assumed": hourly_rate,
        "fairness_score": fairness,
        "duty_fraction": round(frac, 3),
        "comp_cap_hours": comp_cap,
        "roster_avg_comp_hours": avg_comp,
        "comp_headroom_hours": comp_headroom,
        "force_cash_ot_path": force_cash,
        "ot_pay_mode": "cash" if force_cash else "comp_or_cash",
    }
    out["economics"] = econ
    hm = dict(out.get("human_metrics") or {})
    hm.update(
        {
            "est_ot_hours": ot_total,
            "est_ot_cost": cost,
            "flsa_period_pct": econ["flsa_period_pct"],
            "fairness_score": fairness,
            "force_cash_ot_path": force_cash,
            "comp_cap_hours": comp_cap,
        }
    )
    out["human_metrics"] = hm
    return out


def enrich_ranked_economics(
    ranked: Sequence[Dict[str, Any]],
    **kwargs,
) -> List[Dict[str, Any]]:
    return [enrich_option_economics(dict(r), **kwargs) for r in (ranked or [])]


def detect_constraint_conflicts(context: Dict[str, Any]) -> Dict[str, Any]:
    """Static precheck before long search — impossible or high-risk combos."""
    conflicts: List[Dict[str, str]] = []
    warnings: List[Dict[str, str]] = []

    def _i(k_use: str, k_val: str, default=None):
        if not context.get(k_use):
            return default
        try:
            return int(float(context.get(k_val)))
        except (TypeError, ValueError):
            return default

    def _f(k_use: str, k_val: str, default=None):
        if not context.get(k_use):
            return default
        try:
            return float(context.get(k_val))
        except (TypeError, ValueError):
            return default

    n = _i("use_officers", "officers")
    length = _f("use_length", "length")
    cov247 = _i("use_247", "cov247") or 0
    windows = list(context.get("windows") or []) if context.get("use_windows") else []
    win_min = 0
    for w in windows:
        if not isinstance(w, dict) or w.get("enabled") is False:
            continue
        try:
            win_min = max(win_min, int(w.get("min_officers") or 0))
        except (TypeError, ValueError):
            pass
    offday = bool(context.get("allow_offday"))
    starts = []
    if context.get("use_starts") and context.get("starts"):
        raw = context.get("starts")
        if isinstance(raw, str):
            starts = [s.strip() for s in raw.replace(";", ",").split(",") if s.strip()]
        else:
            starts = list(raw or [])

    if n is not None and cov247 and n < cov247:
        conflicts.append(
            {
                "code": "n_lt_247",
                "severity": "hard",
                "message": f"Officer count N={n} is below 24/7 minimum {cov247}.",
            }
        )
    if n is not None and win_min and n < win_min:
        conflicts.append(
            {
                "code": "n_lt_window",
                "severity": "hard",
                "message": f"N={n} cannot staff window min {win_min} even if all work that day.",
            }
        )
    if n is not None and n <= 7 and win_min >= 2 and (cov247 or 0) >= 1 and (length or 8) <= 9 and not offday:
        warnings.append(
            {
                "code": "lean_weekend_nights",
                "severity": "high",
                "message": (
                    f"N={n} with 24/7 + Fri/Sat-class windows often needs 8 officers for hard OK without off-day OT."
                ),
            }
        )
    if length and length >= 12 and starts and len(starts) >= 3:
        warnings.append(
            {
                "code": "12h_many_starts",
                "severity": "med",
                "message": "12h+ length with 3+ start bands may over-fragment coverage.",
            }
        )
    if context.get("use_annual") and context.get("use_length") and context.get("use_style"):
        try:
            from logic.constraint_suggest import _annual_from_pattern, _parse_variations

            vars_ = _parse_variations(context.get("variations"))
            ann = _f("use_annual", "annual")
            L = length
            if vars_ and ann and L:
                proj = _annual_from_pattern(L, vars_)
                varn = _f("use_annual", "annual_var") or 20
                if proj is not None and abs(proj - ann) > float(varn) + 5:
                    warnings.append(
                        {
                            "code": "annual_pattern_mismatch",
                            "severity": "med",
                            "message": (f"Pattern×length projects ~{proj:g}h/year but target is {ann:g}±{varn:g}."),
                        }
                    )
        except Exception:
            pass

    # Cert gate residual: required codes vs roster
    cert_raw = context.get("required_certs") or context.get("cert_codes") or ""
    if cert_raw or context.get("use_certs"):
        try:
            from logic.certifications import roster_cert_coverage_for_sim

            if isinstance(cert_raw, str):
                codes = [c.strip() for c in cert_raw.replace(";", ",").split(",") if c.strip()]
            else:
                codes = [str(c).strip() for c in (cert_raw or []) if str(c).strip()]
            cov = roster_cert_coverage_for_sim(
                required_codes=codes,
                shift_starts=starts or None,
                num_officers=n,
            )
            if codes and cov.get("eligible", 0) == 0:
                conflicts.append(
                    {
                        "code": "no_cert_eligible",
                        "severity": "hard",
                        "message": (f"No active officers hold required certs: {', '.join(codes)}"),
                    }
                )
            elif cov.get("thin_for_headcount"):
                warnings.append(
                    {
                        "code": "cert_thin",
                        "severity": "high",
                        "message": cov.get("message") or "Cert-eligible roster thin vs N",
                    }
                )
        except Exception:
            pass

    hard = [c for c in conflicts if c.get("severity") == "hard"]
    return {
        "success": True,
        "ok": len(hard) == 0,
        "conflicts": conflicts,
        "warnings": warnings,
        "blocking": len(hard) > 0,
        "message": (
            f"{len(hard)} blocking · {len(warnings)} warning(s)"
            if (hard or warnings)
            else "No static conflicts detected"
        ),
        "lines": [c["message"] for c in conflicts + warnings],
    }


# ── Demand heatmap → windows ────────────────────────────────────────────────


def demand_template_fri_sat_nights(min_officers: int = 2) -> List[Dict[str, Any]]:
    return [
        {
            "min_officers": int(min_officers),
            "start_time": "19:00",
            "end_time": "03:00",
            "weekday": 4,
            "label": "Friday Night (demand)",
            "enabled": True,
            "source": "demand_template",
        },
        {
            "min_officers": int(min_officers),
            "start_time": "19:00",
            "end_time": "03:00",
            "weekday": 5,
            "label": "Saturday Night (demand)",
            "enabled": True,
            "source": "demand_template",
        },
    ]


def demand_template_from_heatmap(
    cells: Sequence[Dict[str, Any]],
    *,
    threshold: int = 2,
) -> List[Dict[str, Any]]:
    """cells: {weekday:0-6, start_hour:0-23, end_hour:0-23, min_officers:int}."""
    out = []
    for c in cells or []:
        if not isinstance(c, dict):
            continue
        try:
            mn = int(c.get("min_officers") or threshold)
            wd = c.get("weekday")
            sh = int(c.get("start_hour") or 0) % 24
            eh = int(c.get("end_hour") or 0) % 24
        except (TypeError, ValueError):
            continue
        if mn <= 0:
            continue
        out.append(
            {
                "min_officers": mn,
                "start_time": f"{sh:02d}:00",
                "end_time": f"{eh:02d}:00",
                "weekday": int(wd) if wd is not None else None,
                "label": str(c.get("label") or f"Demand DOW{wd} {sh:02d}-{eh:02d}"),
                "enabled": True,
                "source": "demand_heatmap",
            }
        )
    return out


def list_demand_templates() -> List[Dict[str, str]]:
    return [
        {"id": "fri_sat_night", "label": "Fri+Sat Night 19–03 Min 2 (peak risk)"},
        {"id": "weekend_day", "label": "Sat+Sun Day 07–23 Min 2"},
        {"id": "weekday_morning", "label": "Mon–Fri Court Morning 08–12 Min 2"},
        {"id": "from_court_board", "label": "From Court/Training Board (live)"},
    ]


def court_board_to_demand_windows(
    *,
    start: Optional[str] = None,
    end: Optional[str] = None,
    min_officers: int = 1,
    only_approved: bool = False,
) -> Dict[str, Any]:
    """Convert court/training board events into specific-date coverage windows.

    Each date with court/training gets a morning window (08:00–12:00) so the
    simulator can hold min bodies while officers are blocked for court.
    """
    try:
        from logic.court_calendar import list_court_training_events
    except Exception as exc:
        return {"success": False, "message": str(exc), "windows": []}

    board = list_court_training_events(start=start, end=end, limit=500)
    if not board.get("success"):
        return {"success": False, "message": board.get("message"), "windows": []}

    by_date: Dict[str, int] = {}
    keep_status = {
        "approved",
        "pending",
        "pending manual review",
    }
    for e in board.get("events") or []:
        st = str(e.get("status") or "").lower()
        if only_approved and st != "approved":
            continue
        if not only_approved and st not in keep_status and st not in ("", "none"):
            # skip rejected/cancelled
            if st in ("rejected", "cancelled", "denied"):
                continue
        rd = str(e.get("request_date") or "")[:10]
        if not rd:
            continue
        by_date[rd] = by_date.get(rd, 0) + 1

    windows: List[Dict[str, Any]] = []
    for rd, cnt in sorted(by_date.items()):
        need = max(int(min_officers), min(3, 1 + cnt // 2))
        windows.append(
            {
                "min_officers": need,
                "start_time": "08:00",
                "end_time": "12:00",
                "weekday": None,
                "specific_date": rd,
                "label": f"Court/Training load ({cnt}) {rd}",
                "enabled": True,
                "source": "court_board",
            }
        )
    return {
        "success": True,
        "event_days": len(by_date),
        "windows": windows,
        "message": (
            f"Built {len(windows)} court/training window(s) from board"
            if windows
            else "No court/training events in window"
        ),
    }


def get_demand_template(template_id: str) -> List[Dict[str, Any]]:
    tid = (template_id or "").strip()
    if tid == "fri_sat_night":
        return demand_template_fri_sat_nights(2)
    if tid == "weekend_day":
        return [
            {
                "min_officers": 2,
                "start_time": "07:00",
                "end_time": "23:00",
                "weekday": 5,
                "label": "Saturday Day (demand)",
                "enabled": True,
                "source": "demand_template",
            },
            {
                "min_officers": 2,
                "start_time": "07:00",
                "end_time": "23:00",
                "weekday": 6,
                "label": "Sunday Day (demand)",
                "enabled": True,
                "source": "demand_template",
            },
        ]
    if tid == "weekday_morning":
        return [
            {
                "min_officers": 2,
                "start_time": "08:00",
                "end_time": "12:00",
                "weekday": d,
                "label": f"Court morning DOW{d}",
                "enabled": True,
                "source": "demand_template",
            }
            for d in (0, 1, 2, 3, 4)
        ]
    if tid == "from_court_board":
        r = court_board_to_demand_windows()
        return list(r.get("windows") or [])
    return []


# ── Staffing risk strip (dashboard) ──────────────────────────────────────────


def staffing_risk_snapshot() -> Dict[str, Any]:
    """Lightweight command-strip metrics from live schedule + leave + OT hints."""
    risks: List[str] = []
    metrics: Dict[str, Any] = {}
    try:
        from logic.officers import get_officers_by_seniority

        active = [o for o in get_officers_by_seniority() if o.get("active") == 1]
        metrics["active_officers"] = len(active)
        if len(active) < 8:
            risks.append(f"Active roster {len(active)} — lean for 24/7 + weekend nights")
    except Exception:
        pass
    try:
        from logic import get_dashboard_kpis_fast

        kpis = get_dashboard_kpis_fast() or {}
        if isinstance(kpis, dict):
            metrics["pending_leave"] = int(kpis.get("pending_requests") or 0)
            metrics["coverage_gaps"] = int(kpis.get("coverage_gap_count") or 0)
            if metrics["pending_leave"]:
                risks.append(f"{metrics['pending_leave']} pending leave/request(s)")
            if metrics["coverage_gaps"]:
                risks.append(f"{metrics['coverage_gaps']} coverage gap(s) next 48h")
    except Exception:
        metrics["pending_leave"] = 0
    try:
        from logic.coverage_windows_store import get_active_coverage_windows

        wins = get_active_coverage_windows() or []
        metrics["active_windows"] = len(wins)
    except Exception:
        metrics["active_windows"] = 0

    level = "ok"
    if len(risks) >= 3:
        level = "high"
    elif risks:
        level = "watch"
    return {
        "success": True,
        "level": level,
        "risks": risks,
        "metrics": metrics,
        "lines": risks or ["No elevated staffing risks detected from live snapshot"],
    }


# ── Publish audit + staffing memo ────────────────────────────────────────────


def _exports_dir() -> Path:
    root = Path(__file__).resolve().parent.parent
    d = root / "exports"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _logs_dir() -> Path:
    root = Path(__file__).resolve().parent.parent
    d = root / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def append_publish_audit(
    *,
    config: Optional[Dict] = None,
    result: Optional[Dict] = None,
    user_id: Optional[int] = None,
    message: str = "",
) -> Dict[str, Any]:
    path = _logs_dir() / "sim_publish_audit.jsonl"
    entry = {
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "user_id": user_id,
        "message": message,
        "config": config or {},
        "metrics": (result or {}).get("metrics") or {},
        "hard_ok": ((result or {}).get("metrics") or {}).get("hard_constraints_ok"),
        "manual": bool(((result or {}).get("metrics") or {}).get("manual_build")),
    }
    try:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")
        return {"success": True, "path": str(path)}
    except Exception as exc:
        return {"success": False, "message": str(exc)}


def export_staffing_memo(
    *,
    result: Optional[Dict] = None,
    config: Optional[Dict] = None,
    ranked: Optional[Sequence[Dict]] = None,
    conflicts: Optional[Dict] = None,
    filename: Optional[str] = None,
) -> Dict[str, Any]:
    """Plain-text chief packet (memo)."""
    cfg = config or (result or {}).get("simulation_config") or {}
    m = (result or {}).get("metrics") or {}
    lines = [
        "CHRONOS STAFFING MEMO",
        f"Generated: {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}",
        "",
        "CONSTRAINTS",
        f"  Rotation: {cfg.get('rotation_type') or '—'}",
        f"  Officers: {cfg.get('num_officers') or m.get('min_officers_required') or '—'}",
        f"  Length: {cfg.get('shift_length_hours') or '—'}h",
        f"  Annual: {cfg.get('annual_hours_target') or '—'} ± {cfg.get('annual_hours_variance') or '—'}",
        f"  Starts: {cfg.get('shift_starts') or '—'}",
        f"  24/7: {cfg.get('coverage_247') or 0}",
        f"  Patterns: {cfg.get('rotation_variations') or '—'}",
        f"  Nearby hops: {cfg.get('nearby_start_hops') or 0}",
        f"  Off-day OT: {cfg.get('allow_offday_coverage')}",
        "",
        "RESULTS",
        f"  Hard OK: {m.get('hard_constraints_ok')}",
        f"  24/7 shortfalls: {m.get('coverage_247_failures')}",
        f"  Window shortfalls: {m.get('extra_window_failures')}",
        f"  Avg annual: {m.get('avg_annual_hours')}",
        f"  Manual build: {m.get('manual_build')}",
    ]
    if conflicts:
        lines.append("")
        lines.append("PRECHECK")
        for msg in conflicts.get("lines") or []:
            lines.append(f"  · {msg}")
    if ranked:
        lines.append("")
        lines.append("RANKED OPTIONS")
        for row in list(ranked)[:5]:
            e = row.get("economics") or {}
            lines.append(
                f"  #{row.get('rank')} N={row.get('num_officers')} "
                f"starts={row.get('shift_starts')} "
                f"OT≈{e.get('est_ot_hours_total', '—')}h "
                f"cost≈${e.get('est_ot_cost_usd', '—')} "
                f"FLSA%={e.get('flsa_period_pct', '—')} "
                f"fair={e.get('fairness_score', '—')}"
            )
    lines.append("")
    lines.append("Not legal advice. FLSA §7(k) thresholds are configurable estimates.")
    path = _exports_dir() / (filename or f"staffing_memo_{time.strftime('%Y%m%d_%H%M%S')}.txt")
    path.write_text("\n".join(lines), encoding="utf-8")
    return {"success": True, "path": str(path), "text": "\n".join(lines)}


def list_user_scenario_library(limit: int = 30) -> List[Dict[str, Any]]:
    """Named user-saved scenarios only (no program defaults)."""
    try:
        from logic.simulator_store import list_simulator_scenarios

        return list_simulator_scenarios(limit=limit)
    except Exception:
        return []


def recommend_pay_period_preview(start_date: str = "") -> Dict[str, Any]:
    """Publish preview: which pay period the implement date falls in."""
    try:
        from logic.optimized_schedule_apply import recommend_implement_dates
        from validators import parse_date

        rec = recommend_implement_dates()
        if start_date:
            try:
                d = parse_date(start_date)
                rec = recommend_implement_dates(d)
            except Exception:
                pass
        return {
            "success": True,
            "recommended_date": rec.get("recommended_date"),
            "recommended_label": rec.get("recommended_label"),
            "reason": rec.get("reason"),
            "options": rec.get("options") or [],
            "message": (
                f"Pay period start {rec.get('recommended_label') or rec.get('recommended_date')}: "
                f"{rec.get('reason') or ''}"
            ),
        }
    except Exception as exc:
        return {"success": False, "message": str(exc)}


def absence_stress_test(
    row: Dict[str, Any],
    constraints: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Re-evaluate a winning option with one officer out.

    Schedules die on vacation/sick/training, not on paper — this answers
    "does this plan survive 1 officer out?" by re-running the same shape
    (pattern, length, starts, requirements) at N-1 officers.

    Returns {survives_one_out, n_tested, message, shortfalls:{...}}.
    """
    from logic.scheduling_sim import run_schedule_simulation

    r = dict(row or {})
    c = dict(constraints or {})
    n = int(r.get("num_officers") or 0)
    if n <= 1:
        return {
            "success": False,
            "survives_one_out": False,
            "n_tested": max(n - 1, 0),
            "message": "Not enough officers to test an absence.",
        }
    starts = list(r.get("shift_starts") or r.get("best_starts") or [])
    length = float(r.get("shift_length_hours") or 8.0)
    try:
        sim = run_schedule_simulation(
            rotation_type=str(r.get("rotation_type") or ""),
            num_officers=n - 1,
            shift_length_hours=length,
            annual_hours_target=float(c.get("annual_hours_target") or 0.0),
            shift_starts=starts,
            min_per_shift=int(c.get("min_per_shift") or 1),
            simulation_days=int(c.get("simulation_days") or 56),
            annual_hours_variance=float(c.get("annual_hours_variance") or 40.0),
            annual_hours_hard=False,
            coverage_247=int(c.get("coverage_247") or 0),
            rotation_style=str(r.get("rotation_style") or c.get("rotation_style") or ""),
            rotation_variations=list(r.get("rotation_variations") or c.get("rotation_variations") or []),
            auto_min_officers=False,
            use_extra_windows=bool(c.get("use_extra_windows")),
            extra_windows=list(c.get("extra_windows") or []),
            nearby_start_hops=int(c.get("nearby_start_hops") or 0),
            allow_offday_coverage=bool(c.get("allow_offday_coverage")),
        )
    except Exception as exc:
        return {"success": False, "survives_one_out": False, "n_tested": n - 1, "message": str(exc)}
    m = sim.get("metrics") or {}
    gaps = int(m.get("gap_events") or 0)
    c247 = int(m.get("coverage_247_failures") or 0)
    wins = int(m.get("extra_window_failures") or 0)
    survives = bool(sim.get("success")) and gaps == 0 and c247 == 0 and wins == 0
    if survives:
        msg = f"Survives 1 out: coverage holds at {n - 1} officers."
    else:
        parts = []
        if gaps:
            parts.append(f"{gaps} coverage gap(s)")
        if c247:
            parts.append(f"{c247} 24/7 shortfall(s)")
        if wins:
            parts.append(f"{wins} window shortfall(s)")
        msg = f"At {n - 1} officers: " + (", ".join(parts) if parts else "simulation failed") + "."
    return {
        "success": True,
        "survives_one_out": survives,
        "n_tested": n - 1,
        "message": msg,
        "shortfalls": {"gap_events": gaps, "coverage_247_failures": c247, "extra_window_failures": wins},
    }


def option_fatigue_score(row: Dict[str, Any]) -> Dict[str, Any]:
    """Fatigue / quality-of-life score (0-100, higher = better) for a ranked option.

    Scored from the schedule shape itself: consecutive-work runs, night-shift
    load, shift length, and weekend distribution — the questions a union asks
    on day one. Flags list each penalty applied.
    """
    from config import MAX_CONSECUTIVE_WORK_DAYS

    r = dict(row or {})
    score = 100.0
    flags: List[str] = []
    length = float(r.get("shift_length_hours") or 8.0)
    variations = [v.strip() for v in (r.get("rotation_variations") or []) if str(v).strip()]

    # Longest consecutive-ON run across multi-block variations like "6-2,5-3"
    longest_run = 0
    for var in variations:
        for block in str(var).replace("|", ",").split(","):
            b = block.strip()
            if "-" in b:
                on = b.split("-", 1)[0].strip()
                if on.isdigit():
                    longest_run = max(longest_run, int(on))
    if not longest_run:
        rot = str(r.get("rotation_type") or "")
        head = rot.split("-", 1)[0].strip() if "-" in rot else ""
        if head.isdigit():
            longest_run = int(head)
    cap = int(MAX_CONSECUTIVE_WORK_DAYS or 13)
    if longest_run >= cap:
        score -= 35
        flags.append(f"{longest_run} consecutive work days meets/exceeds policy cap {cap}")
    elif longest_run >= 7:
        score -= 20
        flags.append(f"{longest_run} consecutive work days (7+ is high fatigue)")
    elif longest_run >= 6:
        score -= 10
        flags.append(f"{longest_run} consecutive work days")

    # Long shifts compound fatigue
    if length >= 12:
        score -= 15
        flags.append(f"{length:g}h shifts (12h+ raises fatigue risk)")
    elif length >= 10.5:
        score -= 8
        flags.append(f"{length:g}h shifts")

    # Night starts (19:00-03:59 starts count as night duty)
    starts = [str(s) for s in (r.get("shift_starts") or r.get("best_starts") or [])]
    night_starts = 0
    for s in starts:
        try:
            hh = int(s.split(":", 1)[0])
        except (ValueError, AttributeError):
            continue
        if hh >= 19 or hh < 4:
            night_starts += 1
    if starts and night_starts:
        frac = night_starts / len(starts)
        if frac >= 0.5:
            score -= 12
            flags.append("half or more of start bands are nights")
        else:
            score -= 5
            flags.append(f"{night_starts} night start band(s)")

    # Off-day recovery: shortest OFF block across variations
    shortest_off = None
    for var in variations:
        for block in str(var).replace("|", ",").split(","):
            b = block.strip()
            if "-" in b:
                off = b.split("-", 1)[1].strip()
                if off.isdigit():
                    off_n = int(off)
                    shortest_off = off_n if shortest_off is None else min(shortest_off, off_n)
    if shortest_off is not None and shortest_off < 2:
        score -= 10
        flags.append("single-day recovery between blocks")

    score = max(0.0, round(score, 1))
    band = "low" if score >= 75 else ("moderate" if score >= 50 else "high")
    return {"success": True, "score": score, "risk_band": band, "flags": flags}
