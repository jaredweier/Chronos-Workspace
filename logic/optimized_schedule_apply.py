"""View / recommend / implement optimized simulator plans as monthly schedules."""

from __future__ import annotations

import json
from datetime import date
from typing import Any, Dict, List, Optional

from logic.operations import get_department_setting, set_department_setting
from logic.users import log_audit_action
from validators import format_date, parse_date, storage_date_str

DEFAULTS_KEY = "schedule_builder_defaults_json"
LAST_PLAN_KEY = "last_optimized_plan_json"


def _snap_hhmm_half_hour(label: str) -> str:
    """Duty-board rule: shift starts on :00 or :30 only."""
    try:
        parts = (label or "00:00").strip().split(":")
        h = int(parts[0]) % 24
        m = int(parts[1]) if len(parts) > 1 else 0
    except (TypeError, ValueError, IndexError):
        return "00:00"
    total = (h * 60 + m + 15) // 30 * 30
    total %= 24 * 60
    return f"{total // 60:02d}:{total % 60:02d}"


def _normalize_half_hour_starts(starts: List[Any]) -> List[str]:
    out: List[str] = []
    seen = set()
    for raw in starts or []:
        if raw is None:
            continue
        s = _snap_hhmm_half_hour(str(raw).strip())
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def _pay_period_window(reference: date) -> tuple[date, date]:
    """Calendar-only pay period bounds from config (no payroll package import)."""
    from datetime import timedelta

    from config import PAY_PERIOD_BASE_DATE, PAY_PERIOD_LENGTH

    period_index = (reference - PAY_PERIOD_BASE_DATE).days // PAY_PERIOD_LENGTH
    start = PAY_PERIOD_BASE_DATE + timedelta(days=period_index * PAY_PERIOD_LENGTH)
    end = start + timedelta(days=PAY_PERIOD_LENGTH - 1)
    return start, end


def _adjacent_pay_period(period_start: date, direction: int) -> tuple[date, date]:
    from datetime import timedelta

    start, end = _pay_period_window(period_start)
    if direction < 0:
        return _pay_period_window(start - timedelta(days=1))
    if direction > 0:
        return _pay_period_window(end + timedelta(days=1))
    return start, end


def _format_period_label(period_start: date, period_end: date) -> str:
    return f"{format_date(period_start)} – {format_date(period_end)} (14 days)"


def recommend_implement_dates(reference: Optional[date] = None) -> Dict:
    """Recommend implement dates from pay-period calendar (config; not payroll math)."""
    ref = reference or date.today()
    cur_start, cur_end = _pay_period_window(ref)
    next_start, next_end = _adjacent_pay_period(cur_start, direction=1)
    # Prefer next pay period start if we're past day 1 of current; else current start if not started
    if ref <= cur_start:
        recommended = cur_start
        reason = "Current pay period start"
    else:
        recommended = next_start
        reason = "Next pay period start (recommended for clean payroll alignment)"
    options = [
        {
            "date": cur_start.isoformat(),
            "label": _format_period_label(cur_start, cur_end),
            "kind": "current_pay_period",
            "recommended": recommended == cur_start,
        },
        {
            "date": next_start.isoformat(),
            "label": _format_period_label(next_start, next_end),
            "kind": "next_pay_period",
            "recommended": recommended == next_start,
        },
        {
            "date": date(ref.year, ref.month, 1).isoformat(),
            "label": f"First of month ({format_date(date(ref.year, ref.month, 1))})",
            "kind": "month_start",
            "recommended": False,
        },
    ]
    # Following month start
    if ref.month == 12:
        nm = date(ref.year + 1, 1, 1)
    else:
        nm = date(ref.year, ref.month + 1, 1)
    options.append(
        {
            "date": nm.isoformat(),
            "label": f"First of next month ({format_date(nm)})",
            "kind": "next_month_start",
            "recommended": False,
        }
    )
    return {
        "success": True,
        "recommended_date": recommended.isoformat(),
        "recommended_label": _format_period_label(*_pay_period_window(recommended)),
        "reason": reason,
        "options": options,
    }


def format_optimized_plan_view(result: Dict, config: Optional[Dict] = None) -> Dict:
    """Build a screen-friendly grid from a simulation/optimizer result."""
    if not result or not result.get("success"):
        return {"success": False, "message": result.get("message") if result else "No plan"}

    slots = result.get("officer_slots") or []
    coverage = result.get("coverage_by_day") or []
    metrics = result.get("metrics") or {}
    cfg = config or result.get("simulation_config") or {}

    # Normalize slots (dataclass dicts or plain)
    slot_rows = []
    for s in slots:
        if isinstance(s, dict):
            slot_rows.append(s)
        else:
            slot_rows.append(getattr(s, "__dict__", {}))

    day_rows = []
    for day in coverage[:62]:
        if not isinstance(day, dict):
            continue
        day_rows.append(
            {
                "date": day.get("date"),
                "cycle_day": day.get("cycle_day"),
                "working_officers": day.get("working_officers"),
                "min_shift_coverage": day.get("min_shift_coverage"),
                "shift_counts": day.get("shift_counts") or {},
                "high_risk_night": day.get("high_risk_night"),
            }
        )

    lines = [
        f"Plan view · {len(slot_rows)} slots · {len(day_rows)} days shown",
        f"Coverage %: {metrics.get('coverage_percent', '—')} · "
        f"Min officers req: {metrics.get('min_officers_required', metrics.get('auto_sized') and 'auto' or '—')}",
        f"Hard constraints OK: {metrics.get('hard_constraints_ok', '—')}",
        "",
        "Officer slots:",
    ]
    for s in slot_rows[:40]:
        lines.append(
            f"  {s.get('label') or s.get('slot_id')}: squad {s.get('squad')} "
            f"{s.get('shift_start')}–{s.get('shift_end')} · ~{s.get('projected_annual_hours', '—')}h/yr"
        )
    if len(slot_rows) > 40:
        lines.append(f"  … +{len(slot_rows) - 40} more")
    lines.append("")
    lines.append("Daily coverage (first days):")
    for d in day_rows[:14]:
        counts = d.get("shift_counts") or {}
        cnt = ", ".join(f"{k}:{v}" for k, v in sorted(counts.items()))
        lines.append(f"  {d.get('date')} · working {d.get('working_officers')} · {cnt}")

    return {
        "success": True,
        "text": "\n".join(lines),
        "slots": slot_rows,
        "coverage_by_day": day_rows,
        "metrics": metrics,
        "config": cfg,
        "shift_templates": result.get("shift_templates") or [],
    }


def save_last_optimized_plan(result: Dict, config: Dict, *, user_id: Optional[int] = None) -> Dict:
    payload = {
        "result": result,
        "config": config,
        "saved_at": date.today().isoformat(),
    }
    r = set_department_setting(LAST_PLAN_KEY, json.dumps(payload), user_id=user_id)
    if not r.get("success"):
        return r
    return {"success": True, "message": "Optimized plan saved for review"}


def get_last_optimized_plan() -> Optional[Dict]:
    raw = get_department_setting(LAST_PLAN_KEY, "") or ""
    if not raw.strip():
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def get_schedule_builder_defaults() -> Dict:
    raw = get_department_setting(DEFAULTS_KEY, "") or ""
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def set_schedule_builder_defaults(defaults: Dict, *, user_id: Optional[int] = None) -> Dict:
    r = set_department_setting(DEFAULTS_KEY, json.dumps(defaults or {}), user_id=user_id)
    if not r.get("success"):
        return r
    return {"success": True, "message": "Schedule builder defaults saved", "defaults": defaults}


def apply_schedule_builder_defaults_to_department(*, user_id: Optional[int] = None) -> Dict:
    """Push saved builder defaults into active staffing/rotation settings."""
    defaults = get_schedule_builder_defaults()
    if not defaults:
        return {"success": False, "message": "No schedule builder defaults saved"}

    from logic.staffing_config import save_staffing_settings

    starts = defaults.get("shift_starts") or []
    if isinstance(starts, str):
        starts_text = starts
    else:
        starts_text = ", ".join(str(s) for s in starts)

    staff = save_staffing_settings(
        shift_length_hours=float(defaults.get("shift_length_hours") or 11),
        annual_hours_target=float(defaults.get("annual_hours_target") or 2080),
        shift_count=int(defaults.get("shift_count") or max(len(starts) if isinstance(starts, list) else 4, 1)),
        target_officer_count=int(defaults.get("num_officers") or defaults.get("target_officer_count") or 16),
        shift_starts_text=starts_text,
        annual_hours_variance=float(defaults.get("annual_hours_variance") or 40),
        user_id=user_id,
    )
    if not staff.get("success"):
        return staff

    # Rotation variations / style
    if defaults.get("rotation_variations"):
        set_department_setting(
            "rotation_variations_json",
            json.dumps(defaults.get("rotation_variations")),
            user_id=user_id,
        )
    if defaults.get("rotation_style"):
        set_department_setting("rotation_style", str(defaults["rotation_style"]), user_id=user_id)
    if defaults.get("rotation_type"):
        set_department_setting("rotation_preset", str(defaults["rotation_type"]), user_id=user_id)
    if defaults.get("coverage_247") is not None:
        set_department_setting("coverage_247_minimum", str(int(defaults["coverage_247"])), user_id=user_id)

    return {
        "success": True,
        "message": "Department staffing defaults applied from optimized plan",
        "defaults": defaults,
    }


def _unlock_base_if_needed(year: int, month: int) -> None:
    from database import connection

    with connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE schedule_snapshots SET locked = 0
            WHERE year = ? AND month = ? AND schedule_type = 'base'
            """,
            (year, month),
        )
        conn.commit()


def preview_implement_plan(
    *,
    start_date: str = "",
    result: Optional[Dict] = None,
    config: Optional[Dict] = None,
    apply_officer_assignments: bool = True,
) -> Dict:
    """B6 — dry-run publish: what would be written (no DB mutation)."""
    plan = result or {}
    cfg = config or plan.get("simulation_config") or {}
    if not plan.get("success"):
        return {"success": False, "message": "No successful plan to preview", "dry_run": True}
    slots = plan.get("officer_slots") or []
    metrics = plan.get("metrics") or {}
    rec = recommend_implement_dates()
    starts = cfg.get("shift_starts") or []
    lines = [
        "Publish Preview (Dry Run — nothing written)",
        f"Start date input: {start_date or '(use recommended)'}",
        f"Recommended: {rec.get('recommended_date')} — {rec.get('reason')}",
        f"Officers / slots: {len(slots)}",
        f"Shift starts: {', '.join(str(s) for s in starts) if starts else '—'}",
        f"Length: {cfg.get('shift_length_hours', '—')}h · Annual target: {cfg.get('annual_hours_target', '—')}",
        f"Apply officer assignments: {bool(apply_officer_assignments)}",
        f"Hard OK: {metrics.get('hard_constraints_ok', '—')}",
        "",
        "Would create/update original + live monthly snapshots for the implement month.",
        "Officer home starts would update only if apply_officer_assignments is on.",
    ]
    for s in slots[:12]:
        if not isinstance(s, dict):
            s = getattr(s, "__dict__", {}) or {}
        lines.append(
            f"  · {s.get('label') or s.get('slot_id')}: "
            f"{s.get('shift_start')}–{s.get('shift_end')} squad {s.get('squad')}"
        )
    if len(slots) > 12:
        lines.append(f"  … +{len(slots) - 12} more slots")
    return {
        "success": True,
        "dry_run": True,
        "message": "Preview only — click Publish to apply",
        "text": "\n".join(lines),
        "recommended_date": rec.get("recommended_date"),
        "slot_count": len(slots),
        "metrics": metrics,
        "config": cfg,
    }


def implement_optimized_plan(
    *,
    start_date: str,
    result: Optional[Dict] = None,
    config: Optional[Dict] = None,
    user_id: Optional[int] = None,
    apply_officer_assignments: bool = True,
    force_regenerate: bool = True,
    save_as_defaults: bool = True,
) -> Dict:
    """
    Apply optimized plan as department defaults and generate monthly schedule
    for the month containing start_date.
    """
    if result is None or config is None:
        last = get_last_optimized_plan()
        if not last:
            return {"success": False, "message": "No optimized plan to implement — run simulator first"}
        result = result or last.get("result") or {}
        config = config or last.get("config") or {}

    if not result.get("success"):
        return {"success": False, "message": "Plan is not a successful optimization result"}

    try:
        start = parse_date(start_date)
    except ValueError as exc:
        return {"success": False, "message": str(exc)}

    # Prefer best-plan starts on result (optimizer truth) over form config
    def _as_start_list(raw) -> List[str]:
        if raw is None:
            return []
        if isinstance(raw, str):
            return [s.strip() for s in raw.replace(";", ",").split(",") if s.strip()]
        return [str(s).strip() for s in list(raw) if s is not None and str(s).strip()]

    res_starts = (
        result.get("shift_starts")
        or (result.get("best") or {}).get("shift_starts")
        or (result.get("metrics") or {}).get("shift_starts")
        or (result.get("simulation_config") or {}).get("shift_starts")
    )
    start_list = _as_start_list(res_starts)
    if not start_list:
        start_list = _as_start_list(config.get("shift_starts"))
    templates = result.get("shift_templates") or []
    if not start_list and templates:
        start_list = [t[0] if isinstance(t, (list, tuple)) else t.get("start") for t in templates]
    # Duty board: :00 / :30 only (snap odd minutes e.g. :07 → :00)
    start_list = _normalize_half_hour_starts(start_list)
    if not start_list:
        return {
            "success": False,
            "message": "Plan has no valid half-hour shift starts (:00 / :30 only)",
        }

    defaults = {
        "shift_length_hours": float(config.get("shift_length_hours") or 11),
        "annual_hours_target": float(config.get("annual_hours_target") or 2080),
        "annual_hours_variance": float(config.get("annual_hours_variance") or 40),
        "shift_starts": start_list,
        "shift_count": len(start_list) or int(config.get("shift_count") or 4),
        "num_officers": int(
            (result.get("metrics") or {}).get("min_officers_required") or config.get("num_officers") or 0
        )
        or len(result.get("officer_slots") or []),
        "target_officer_count": int(config.get("num_officers") or 0) or len(result.get("officer_slots") or []),
        "min_per_shift": int(config.get("min_per_shift") or 1),
        "rotation_type": config.get("rotation_type") or "",
        "rotation_style": config.get("rotation_style") or "",
        "rotation_variations": config.get("rotation_variations") or [],
        "coverage_247": int(config.get("coverage_247") or 0),
        "avoid_flsa_overtime": bool(config.get("avoid_flsa_overtime")),
        "implemented_start_date": storage_date_str(start.isoformat()),
        "source": "optimized_plan",
    }

    # Always persist defaults for apply path; honor save_as_defaults for long-term store
    set_schedule_builder_defaults(defaults, user_id=user_id)
    if not save_as_defaults:
        # Apply once for this implement, then clear persistent builder defaults
        applied = apply_schedule_builder_defaults_to_department(user_id=user_id)
        if not applied.get("success"):
            return applied
        set_department_setting(DEFAULTS_KEY, "", user_id=user_id)
    else:
        applied = apply_schedule_builder_defaults_to_department(user_id=user_id)
        if not applied.get("success"):
            return applied

    officer_updates = 0
    if apply_officer_assignments:
        cert_codes = config.get("required_cert_codes") or config.get("required_certs") or []
        if isinstance(cert_codes, str):
            cert_codes = [c.strip() for c in cert_codes.replace(";", ",").split(",") if c.strip()]
        officer_updates = _apply_slots_to_officers(
            result.get("officer_slots") or [],
            user_id=user_id,
            required_cert_codes=list(cert_codes) if cert_codes else None,
        )

    try:
        from logic.staffing_insights import append_publish_audit

        append_publish_audit(
            config=defaults,
            result=result,
            user_id=user_id,
            message=f"implement_optimized_plan {storage_date_str(start.isoformat())}",
        )
    except Exception:
        pass

    year, month = start.year, start.month
    if force_regenerate:
        _unlock_base_if_needed(year, month)
        # Delete base rows so ensure_original rebuilds
        from database import connection

        with connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id FROM schedule_snapshots WHERE year=? AND month=? AND schedule_type='base'",
                (year, month),
            )
            row = cursor.fetchone()
            if row:
                cursor.execute("DELETE FROM schedule_snapshot_rows WHERE snapshot_id=?", (row["id"],))
                cursor.execute("DELETE FROM schedule_snapshots WHERE id=?", (row["id"],))
            cursor.execute(
                "SELECT id FROM schedule_snapshots WHERE year=? AND month=? AND schedule_type='updated'",
                (year, month),
            )
            row = cursor.fetchone()
            if row:
                cursor.execute("DELETE FROM schedule_snapshot_rows WHERE snapshot_id=?", (row["id"],))
                cursor.execute("DELETE FROM schedule_snapshots WHERE id=?", (row["id"],))
            conn.commit()

    from logic.snapshots import ensure_original_monthly_schedule

    gen = ensure_original_monthly_schedule(year, month, user_id)
    if not gen.get("success"):
        return gen

    log_audit_action(
        "schedule.implement_optimized",
        "schedule_snapshot",
        gen.get("snapshot_id"),
        user_id,
        f"start={start.isoformat()} officers_updated={officer_updates}",
    )
    return {
        "success": True,
        "message": (
            f"Implemented optimized plan from {format_date(start)}: "
            f"monthly {month}/{year} generated; {officer_updates} officer assignment(s) updated; "
            f"defaults saved for next generator run"
        ),
        "year": year,
        "month": month,
        "snapshot_id": gen.get("snapshot_id"),
        "live_snapshot_id": gen.get("live_snapshot_id"),
        "officer_updates": officer_updates,
        "defaults": defaults,
        "recommended": recommend_implement_dates(start),
    }


def _apply_slots_to_officers(
    slots: List[Any],
    *,
    user_id: Optional[int] = None,
    required_cert_codes: Optional[List[str]] = None,
) -> int:
    """Map simulation slots onto real officers when slot_id matches officer id.

    Skips officers who fail required cert codes or band cert requirements.
    """
    from logic.certifications import (
        officer_has_cert_codes,
        officer_meets_shift_cert_requirements,
    )
    from logic.officers import get_officer_by_id, update_officer

    codes = [str(c).strip() for c in (required_cert_codes or []) if str(c).strip()]
    updated = 0
    for raw in slots:
        s = raw if isinstance(raw, dict) else getattr(raw, "__dict__", {})
        oid = s.get("slot_id") or s.get("id")
        try:
            oid = int(oid)
        except (TypeError, ValueError):
            continue
        officer = get_officer_by_id(oid)
        if not officer:
            continue
        st = s.get("shift_start")
        if codes:
            ok, _msg = officer_has_cert_codes(oid, codes)
            if not ok:
                continue
        if st:
            ok, _msg = officer_meets_shift_cert_requirements(oid, str(st))
            if not ok:
                continue
        fields = {}
        if s.get("squad") in ("A", "B"):
            fields["squad"] = s["squad"]
        if st:
            fields["shift_start"] = _snap_hhmm_half_hour(str(st))
            end_raw = s.get("shift_end") or officer.get("shift_end")
            fields["shift_end"] = _snap_hhmm_half_hour(str(end_raw)) if end_raw else fields["shift_start"]
        # pattern fields if present on slot
        if s.get("rotation_pattern"):
            fields["rotation_pattern"] = s["rotation_pattern"]
        if s.get("rotation_phase") is not None:
            fields["rotation_phase"] = int(s["rotation_phase"])
        if not fields:
            continue
        r = update_officer(oid, **fields)
        if r.get("success"):
            updated += 1
    return updated


def next_generator_should_use_defaults() -> bool:
    d = get_schedule_builder_defaults()
    return bool(d.get("source") == "optimized_plan" or d.get("shift_starts"))
