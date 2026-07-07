"""Department analytics, reports, and CSV exports."""

import csv
import os
from datetime import date, timedelta
from typing import Dict, List, Optional

from config import (
    FLSA_207K_ENABLED,
    FLSA_HOURS_WARN_PCT,
    FLSA_LE_WEEKLY_THRESHOLD,
    FLSA_WEEKLY_THRESHOLD,
    NIGHT_MINIMUM_OFFICERS,
    is_high_risk_night,
)
from database import get_connection
from logic.staffing_config import get_active_shift_times
from paths import data_path, ensure_data_dirs
from validators import applies_night_minimum, format_date, format_row_dates, parse_date


def _shift_starts() -> List[str]:
    return [start for start, _ in get_active_shift_times().values()]


def get_coverage_report(start_date: date, end_date: date) -> Dict:
    from logic import get_cycle_day, get_shift_coverage_counts_for_range, get_squad_on_duty

    coverage = get_shift_coverage_counts_for_range(start_date, end_date)
    issues = []
    days = []
    current = start_date
    while current <= end_date:
        cycle_day = get_cycle_day(current)
        squad = get_squad_on_duty(cycle_day)
        shift_counts = {}
        night_issues = []
        day_str = current.isoformat()
        for shift_start in _shift_starts():
            count = coverage.get((day_str, squad, shift_start), 0)
            shift_counts[shift_start] = count
            if applies_night_minimum(current, shift_start, is_high_risk_night):
                if count < NIGHT_MINIMUM_OFFICERS:
                    night_issues.append(
                        {
                            "shift_start": shift_start,
                            "count": count,
                            "minimum": NIGHT_MINIMUM_OFFICERS,
                        }
                    )
        day_entry = {
            "date": format_date(current),
            "cycle_day": cycle_day,
            "squad_on_duty": squad,
            "shift_counts": shift_counts,
            "high_risk_night": is_high_risk_night(current),
            "night_issues": night_issues,
        }
        days.append(day_entry)
        if night_issues:
            issues.append(day_entry)
        current += timedelta(days=1)

    return {
        "success": True,
        "start_date": format_date(start_date),
        "end_date": format_date(end_date),
        "days": days,
        "issue_count": len(issues),
        "issues": issues,
    }


def get_coverage_gap_board(hours_ahead: int = 48) -> Dict:
    """Near-term staffing gaps for the on-duty squad (today through hours_ahead)."""
    from logic import get_cycle_day, get_shift_coverage_counts_for_range, get_squad_on_duty

    today = date.today()
    end = today + timedelta(days=max(1, hours_ahead // 24))
    coverage = get_shift_coverage_counts_for_range(today, end)
    shift_ends = {start: end for start, end in get_active_shift_times().values()}

    gaps = []
    current = today
    while current <= end:
        squad = get_squad_on_duty(get_cycle_day(current))
        day_str = current.isoformat()
        for shift_start in _shift_starts():
            count = coverage.get((day_str, squad, shift_start), 0)
            gap_type = None
            severity = None
            minimum = None
            if count == 0:
                gap_type = "zero_coverage"
                severity = "critical"
            elif applies_night_minimum(current, shift_start, is_high_risk_night):
                if count < NIGHT_MINIMUM_OFFICERS:
                    gap_type = "night_minimum"
                    severity = "warning"
                    minimum = NIGHT_MINIMUM_OFFICERS
            if gap_type:
                shift_end = shift_ends.get(shift_start, "")
                gaps.append(
                    {
                        "date": format_date(current),
                        "shift_start": shift_start,
                        "shift_end": shift_end,
                        "shift_label": f"{shift_start}–{shift_end}" if shift_end else shift_start,
                        "squad_on_duty": squad,
                        "count": count,
                        "minimum": minimum,
                        "gap_type": gap_type,
                        "severity": severity,
                        "high_risk_night": is_high_risk_night(current),
                    }
                )
        current += timedelta(days=1)

    gaps.sort(key=lambda g: (g["date"], g["shift_start"]))
    return {
        "success": True,
        "start_date": format_date(today),
        "end_date": format_date(end),
        "hours_ahead": hours_ahead,
        "gaps": gaps,
        "gap_count": len(gaps),
        "critical_count": sum(1 for g in gaps if g["severity"] == "critical"),
        "warning_count": sum(1 for g in gaps if g["severity"] == "warning"),
    }


def get_overtime_alerts(
    period_start: Optional[date] = None,
    hours_threshold: Optional[float] = None,
    officer_id: Optional[int] = None,
) -> Dict:
    from logic import get_department_setting, get_payroll_period_timesheets

    if hours_threshold is None:
        try:
            hours_threshold = float(get_department_setting("overtime_threshold", "80"))
        except ValueError:
            hours_threshold = 80.0

    sheets = get_payroll_period_timesheets(period_start)
    alerts = []
    for sheet in sheets.get("sheets", []):
        officer = sheet["officer"]
        hours = sheet.get("total_hours") or 0.0
        target = officer.get("annual_hours_target") or 2080.0
        period_cap = round(target / 26, 1)
        if hours >= hours_threshold or hours > period_cap * 1.1:
            alerts.append(
                {
                    "officer_id": officer["id"],
                    "officer_name": officer["name"],
                    "squad": officer["squad"],
                    "hours": hours,
                    "period_cap": period_cap,
                    "severity": "critical" if hours >= hours_threshold else "warning",
                }
            )
    if officer_id is not None:
        alerts = [a for a in alerts if a["officer_id"] == officer_id]
    alerts.sort(key=lambda a: a["hours"], reverse=True)
    return {
        "success": True,
        "period_start": sheets.get("period_start"),
        "period_end": sheets.get("period_end"),
        "threshold": hours_threshold,
        "alerts": alerts,
        "alert_count": len(alerts),
    }


_OT_LEDGER_TYPES = frozenset(
    {
        "Overtime Earned",
        "Comp Earned",
        "Holiday Overtime",
        "Holiday Overtime Comp Earned",
        "Holiday Comp Earned",
    }
)


def get_equitable_ot_ledger(period_start: Optional[date] = None) -> Dict:
    """Fairness ledger: OT/comp hours by officer vs squad average for the pay period."""
    from logic import get_payroll_period_timesheets

    sheets = get_payroll_period_timesheets(period_start)
    ledger = []
    squad_hours: Dict[str, List[float]] = {}

    for sheet in sheets.get("sheets", []):
        officer = sheet["officer"]
        ot_hours = 0.0
        for row in sheet.get("timecard_rows", []):
            if row.get("entry_type") in _OT_LEDGER_TYPES:
                ot_hours += row.get("hours_worked") or 0.0
        for row in sheet.get("payroll_rows", []):
            if row.get("entry_type") in _OT_LEDGER_TYPES:
                ot_hours += row.get("hours") or 0.0
        squad = officer.get("squad") or "?"
        squad_hours.setdefault(squad, []).append(ot_hours)
        ledger.append(
            {
                "officer_id": officer["id"],
                "officer_name": officer["name"],
                "squad": squad,
                "ot_hours": round(ot_hours, 2),
            }
        )

    squad_avg = {squad: round(sum(values) / len(values), 2) if values else 0.0 for squad, values in squad_hours.items()}
    for row in ledger:
        avg = squad_avg.get(row["squad"], 0.0)
        vs_avg = round(row["ot_hours"] - avg, 2)
        row["squad_avg_ot"] = avg
        row["vs_avg"] = vs_avg
        if vs_avg > 4:
            row["fairness"] = "high"
        elif vs_avg < -4:
            row["fairness"] = "low"
        else:
            row["fairness"] = "balanced"

    ledger.sort(key=lambda r: (-r["ot_hours"], r["officer_name"]))
    dept_total = round(sum(r["ot_hours"] for r in ledger), 2)
    dept_avg = round(dept_total / len(ledger), 2) if ledger else 0.0
    return {
        "success": True,
        "period_start": sheets.get("period_start"),
        "period_end": sheets.get("period_end"),
        "ledger": ledger,
        "officer_count": len(ledger),
        "department_ot_total": dept_total,
        "department_ot_avg": dept_avg,
        "squad_averages": squad_avg,
    }


def get_hours_watch(
    period_start: Optional[date] = None,
    officer_id: Optional[int] = None,
) -> Dict:
    """FLSA-oriented hours watch: weekly and pay-period threshold warnings."""
    from logic import get_department_setting, get_officers_by_seniority, get_payroll_period_timesheets
    from validators import is_officer_active

    try:
        period_threshold = float(get_department_setting("overtime_threshold", "80"))
    except ValueError:
        period_threshold = 80.0
    try:
        weekly_threshold = float(get_department_setting("flsa_weekly_threshold", str(FLSA_WEEKLY_THRESHOLD)))
    except ValueError:
        weekly_threshold = FLSA_WEEKLY_THRESHOLD
    try:
        le_weekly_threshold = float(get_department_setting("flsa_le_weekly_threshold", str(FLSA_LE_WEEKLY_THRESHOLD)))
    except ValueError:
        le_weekly_threshold = FLSA_LE_WEEKLY_THRESHOLD

    period_warn = period_threshold * FLSA_HOURS_WARN_PCT
    weekly_warn = weekly_threshold * FLSA_HOURS_WARN_PCT
    le_weekly_warn = le_weekly_threshold * FLSA_HOURS_WARN_PCT

    sheets = get_payroll_period_timesheets(period_start)
    period_hours_by_officer = {
        sheet["officer"]["id"]: sheet.get("total_hours") or 0.0 for sheet in sheets.get("sheets", [])
    }

    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT officer_id, SUM(hours_worked) AS week_hours
        FROM timecard_entries
        WHERE entry_date >= ? AND entry_date <= ?
        GROUP BY officer_id
    """,
        (week_start.isoformat(), week_end.isoformat()),
    )
    week_hours_map = {row["officer_id"]: row["week_hours"] or 0.0 for row in cursor.fetchall()}
    conn.close()

    warnings = []
    for officer in get_officers_by_seniority():
        if not is_officer_active(officer):
            continue
        oid = officer["id"]
        if officer_id is not None and oid != officer_id:
            continue
        period_hours = period_hours_by_officer.get(oid, 0.0)
        week_hours = week_hours_map.get(oid, 0.0)
        issues = []
        severity = None
        flsa_207k_hours = None
        if period_hours >= period_threshold:
            issues.append(f"pay period {period_hours:.1f}h ≥ {period_threshold:.0f}h")
            severity = "critical"
        elif period_hours >= period_warn:
            issues.append(f"pay period {period_hours:.1f}h approaching {period_threshold:.0f}h")
            severity = severity or "warning"
        if week_hours >= weekly_threshold:
            issues.append(f"work week {week_hours:.1f}h ≥ {weekly_threshold:.0f}h FLSA")
            severity = "critical"
        elif week_hours >= weekly_warn:
            issues.append(f"work week {week_hours:.1f}h approaching {weekly_threshold:.0f}h FLSA")
            severity = severity or "warning"
        if week_hours >= le_weekly_threshold:
            issues.append(f"work week {week_hours:.1f}h ≥ {le_weekly_threshold:.0f}h LE §207(k) weekly")
            severity = "critical"
        elif week_hours >= le_weekly_warn:
            issues.append(f"work week {week_hours:.1f}h approaching {le_weekly_threshold:.0f}h LE weekly")
            severity = severity or "warning"
        if FLSA_207K_ENABLED:
            from logic.labor_compliance import get_flsa_207k_status

            flsa_207k = get_flsa_207k_status(oid)
            flsa_207k_hours = flsa_207k["hours"]
            if flsa_207k["severity"] == "critical":
                issues.append(flsa_207k["message"])
                severity = "critical"
            elif flsa_207k["severity"] == "warning":
                issues.append(flsa_207k["message"])
                severity = severity or "warning"
        if issues:
            warnings.append(
                {
                    "officer_id": oid,
                    "officer_name": officer["name"],
                    "squad": officer["squad"],
                    "period_hours": round(period_hours, 2),
                    "week_hours": round(week_hours, 2),
                    "period_threshold": period_threshold,
                    "weekly_threshold": weekly_threshold,
                    "le_weekly_threshold": le_weekly_threshold,
                    "flsa_207k_hours": flsa_207k_hours,
                    "message": "; ".join(issues),
                    "severity": severity,
                }
            )

    warnings.sort(
        key=lambda w: (0 if w["severity"] == "critical" else 1, -w["period_hours"]),
    )
    return {
        "success": True,
        "period_start": sheets.get("period_start"),
        "period_end": sheets.get("period_end"),
        "week_start": format_date(week_start),
        "week_end": format_date(week_end),
        "period_threshold": period_threshold,
        "weekly_threshold": weekly_threshold,
        "warnings": warnings,
        "warning_count": len(warnings),
        "critical_count": sum(1 for w in warnings if w["severity"] == "critical"),
    }


def get_schedule_conflicts(
    start_date: date,
    end_date: date,
    officer_id: Optional[int] = None,
) -> Dict:
    conn = get_connection()
    cursor = conn.cursor()
    query = """
        SELECT a.*, o.name AS officer_name, o.squad
        FROM officer_availability a
        JOIN officers o ON a.officer_id = o.id
        WHERE a.unavailable_date >= ? AND a.unavailable_date <= ?
    """
    params: List = [start_date.isoformat(), end_date.isoformat()]
    if officer_id is not None:
        query += " AND a.officer_id = ?"
        params.append(officer_id)
    query += " ORDER BY a.unavailable_date, o.name"
    cursor.execute(query, params)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    from logic import batch_officer_day_status

    pairs = [(row["officer_id"], parse_date(row["unavailable_date"])) for row in rows]
    status_map = batch_officer_day_status(pairs)
    conflicts = []
    for row in rows:
        key = (row["officer_id"], row["unavailable_date"])
        status = status_map.get(key, "off")
        if status in ("working", "covering", "swapped"):
            conflicts.append(
                {
                    **row,
                    "schedule_status": status,
                }
            )

    return {
        "success": True,
        "start_date": format_date(start_date),
        "end_date": format_date(end_date),
        "conflicts": [format_row_dates(c, "unavailable_date") for c in conflicts],
        "conflict_count": len(conflicts),
    }


def get_payroll_ytd(year: Optional[int] = None) -> Dict:
    from logic import get_officers_by_seniority

    yr = year or date.today().year
    start = f"{yr}-01-01"
    end = f"{yr}-12-31"
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT officer_id,
               SUM(calculated_pay) AS total_pay,
               SUM(hours) AS total_hours,
               SUM(night_differential_hours) AS night_hours
        FROM payroll_entries
        WHERE entry_date >= ? AND entry_date <= ?
        GROUP BY officer_id
    """,
        (start, end),
    )
    by_officer = {r["officer_id"]: dict(r) for r in cursor.fetchall()}
    cursor.execute(
        """
        SELECT SUM(calculated_pay) AS dept_pay, SUM(hours) AS dept_hours
        FROM payroll_entries
        WHERE entry_date >= ? AND entry_date <= ?
    """,
        (start, end),
    )
    totals = dict(cursor.fetchone() or {})
    conn.close()

    officers = get_officers_by_seniority()
    rows = []
    for officer in officers:
        if officer.get("active") != 1:
            continue
        stats = by_officer.get(officer["id"], {})
        rows.append(
            {
                "officer": officer,
                "total_pay": round(stats.get("total_pay") or 0.0, 2),
                "total_hours": round(stats.get("total_hours") or 0.0, 2),
                "night_hours": round(stats.get("night_hours") or 0.0, 2),
            }
        )
    rows.sort(key=lambda r: r["total_pay"], reverse=True)

    return {
        "success": True,
        "year": yr,
        "officers": rows,
        "department_total_pay": round(totals.get("dept_pay") or 0.0, 2),
        "department_total_hours": round(totals.get("dept_hours") or 0.0, 2),
    }


def get_labor_cost_forecast(months_ahead: int = 3) -> Dict:
    from logic import get_department_pay_summary

    summary = get_department_pay_summary()
    annual = summary.get("department_annual_total") or 0.0
    monthly = round(annual / 12, 2)
    today = date.today()
    forecast = []
    for i in range(months_ahead):
        m = today.month + i
        y = today.year + (m - 1) // 12
        m = ((m - 1) % 12) + 1
        forecast.append(
            {
                "year": y,
                "month": m,
                "projected_cost": monthly,
            }
        )
    return {
        "success": True,
        "monthly_average": monthly,
        "annual_projection": annual,
        "forecast": forecast,
    }


def get_pay_stub_preview(officer_id: int, period_start: Optional[date] = None) -> Dict:
    from logic import get_officer_by_id, get_payroll_period_timesheets

    officer = get_officer_by_id(officer_id)
    if not officer:
        return {"success": False, "message": "Officer not found"}

    sheets = get_payroll_period_timesheets(period_start)
    sheet = next(
        (s for s in sheets.get("sheets", []) if s["officer"]["id"] == officer_id),
        None,
    )
    if not sheet:
        return {"success": False, "message": "No timesheet data for period"}

    regular_hours = sum(
        r.get("hours_worked") or 0 for r in sheet.get("timecard_rows", []) if r.get("entry_type") == "Regular Hours"
    )
    other_hours = sheet["total_hours"] - regular_hours
    gross = sheet["total_pay"]
    rate = officer.get("pay_rate") or 0.0
    from logic.payroll import project_officer_annual_pay

    salary = project_officer_annual_pay(officer_id)
    scheduled_salary = salary.get("per_pay_period_salary") if salary.get("success") else None

    return {
        "success": True,
        "officer": officer,
        "period_start": format_date(sheets["period_start"]),
        "period_end": format_date(sheets["period_end"]),
        "regular_hours": round(regular_hours, 2),
        "other_hours": round(other_hours, 2),
        "total_hours": sheet["total_hours"],
        "hourly_rate": rate,
        "gross_pay": gross,
        "scheduled_per_period_salary": scheduled_salary,
        "monthly_pay": salary.get("monthly_pay") if salary.get("success") else None,
        "payroll_rows": sheet.get("payroll_rows", []),
        "timecard_rows": sheet.get("timecard_rows", []),
    }


def export_roster_csv(output_path: Optional[str] = None) -> Dict:
    from logic import get_officers_by_seniority

    ensure_data_dirs()
    if not output_path:
        output_path = data_path(f"exports/roster_{format_date(date.today())}.csv")

    officers = get_officers_by_seniority()
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    fields = [
        "id",
        "name",
        "seniority_rank",
        "squad",
        "shift_start",
        "shift_end",
        "pay_rate",
        "night_differential_rate",
        "job_title",
        "email",
        "phone",
        "start_date",
        "active",
    ]
    with open(output_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for o in officers:
            writer.writerow(format_row_dates(o, "start_date"))

    return {"success": True, "path": output_path, "count": len(officers)}


def export_payroll_csv(
    period_start: Optional[date] = None,
    officer_id: Optional[int] = None,
    output_path: Optional[str] = None,
) -> Dict:
    from logic import get_pay_period

    ensure_data_dirs()
    start, end = get_pay_period(period_start)
    if not output_path:
        suffix = f"_{officer_id}" if officer_id else ""
        output_path = data_path(f"exports/payroll_{format_date(start)}_{format_date(end)}{suffix}.csv")

    conn = get_connection()
    cursor = conn.cursor()
    query = """
        SELECT p.*, o.name AS officer_name, o.squad
        FROM payroll_entries p
        JOIN officers o ON p.officer_id = o.id
        WHERE p.entry_date >= ? AND p.entry_date <= ?
    """
    params: List = [start.isoformat(), end.isoformat()]
    if officer_id:
        query += " AND p.officer_id = ?"
        params.append(officer_id)
    query += " ORDER BY p.entry_date, o.name"
    cursor.execute(query, tuple(params))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    if not rows:
        return {"success": False, "message": "No payroll entries in period"}

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    fields = list(rows[0].keys())
    with open(output_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(format_row_dates(row, "entry_date"))

    return {"success": True, "path": output_path, "count": len(rows)}


def export_requests_csv(
    status_filter: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    officer_id: Optional[int] = None,
    output_path: Optional[str] = None,
) -> Dict:
    from logic import get_day_off_requests

    ensure_data_dirs()
    requests = get_day_off_requests(
        status_filter=status_filter,
        date_from=date_from,
        date_to=date_to,
        officer_id=officer_id,
    )
    if not requests:
        return {"success": False, "message": "No requests match filters"}

    if not output_path:
        output_path = data_path(f"exports/requests_{format_date(date.today())}.csv")

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    fields = [
        "id",
        "officer_name",
        "squad",
        "shift_start",
        "shift_end",
        "request_date",
        "request_type",
        "status",
        "notes",
        "admin_notes",
        "processed_at",
        "created_at",
    ]
    with open(output_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in requests:
            writer.writerow(format_row_dates(row, "request_date"))

    return {"success": True, "path": output_path, "count": len(requests)}


def export_shift_swaps_csv(
    status_filter: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    officer_id: Optional[int] = None,
    pending_only: bool = False,
    output_path: Optional[str] = None,
) -> Dict:
    from logic import get_shift_swap_requests

    ensure_data_dirs()
    swaps = get_shift_swap_requests(
        status_filter=status_filter,
        date_from=date_from,
        date_to=date_to,
        officer_id=officer_id,
        pending_only=pending_only,
    )
    if not swaps:
        return {"success": False, "message": "No swap requests match filters"}

    if not output_path:
        output_path = data_path(f"exports/shift_swaps_{format_date(date.today())}.csv")

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    fields = [
        "id",
        "swap_date",
        "officer1_name",
        "officer1_squad",
        "officer1_shift",
        "officer2_name",
        "officer2_squad",
        "officer2_shift",
        "status",
        "admin_notes",
        "processed_at",
        "created_at",
    ]
    with open(output_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in swaps:
            writer.writerow(format_row_dates(row, "swap_date"))

    return {"success": True, "path": output_path, "count": len(swaps)}


def export_simulation_csv(
    result: Dict,
    output_path: Optional[str] = None,
) -> Dict:
    if not result.get("success"):
        return {"success": False, "message": result.get("message", "No simulation data")}

    slots = result.get("officer_slots") or []
    if not slots:
        return {"success": False, "message": "No officer slot assignments to export"}

    ensure_data_dirs()
    if not output_path:
        output_path = data_path(f"exports/simulation_{format_date(date.today())}.csv")

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    fields = [
        "slot_id",
        "label",
        "squad",
        "shift_start",
        "shift_end",
        "projected_annual_hours",
        "work_days_in_sim",
    ]
    with open(output_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in slots:
            writer.writerow(row)

    return {"success": True, "path": output_path, "count": len(slots)}


def export_pay_period_history_csv(
    limit: int = 12,
    officer_id: Optional[int] = None,
    output_path: Optional[str] = None,
) -> Dict:
    from logic import get_pay_period_history

    ensure_data_dirs()
    data = get_pay_period_history(limit, officer_id=officer_id)
    periods = data.get("periods") or []
    if not periods:
        return {"success": False, "message": "No pay period history"}

    if not output_path:
        suffix = f"officer_{officer_id}" if officer_id else "department"
        output_path = data_path(f"exports/pay_period_history_{suffix}_{format_date(date.today())}.csv")

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    fields = [
        "period_start",
        "period_end",
        "total_hours",
        "total_pay",
        "officer_count",
        "locked",
    ]
    with open(output_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in periods:
            writer.writerow(format_row_dates(row, "period_start", "period_end"))

    return {"success": True, "path": output_path, "count": len(periods)}


def export_timecard_csv(
    period_start: Optional[date] = None,
    officer_id: Optional[int] = None,
    output_path: Optional[str] = None,
) -> Dict:
    from logic import get_pay_period

    ensure_data_dirs()
    start, end = get_pay_period(period_start)
    if not output_path:
        suffix = f"_{officer_id}" if officer_id else ""
        output_path = data_path(f"exports/timecard_{format_date(start)}_{format_date(end)}{suffix}.csv")

    conn = get_connection()
    cursor = conn.cursor()
    query = """
        SELECT t.*, o.name AS officer_name, o.squad, o.shift_start, o.shift_end
        FROM timecard_entries t
        JOIN officers o ON t.officer_id = o.id
        WHERE t.pay_period_start = ?
    """
    params: List = [start.isoformat()]
    if officer_id:
        query += " AND t.officer_id = ?"
        params.append(officer_id)
    query += " ORDER BY o.name, t.entry_date"
    cursor.execute(query, tuple(params))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    if not rows:
        return {"success": False, "message": "No timecard entries in period"}

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    fields = [
        "officer_name",
        "squad",
        "shift_start",
        "shift_end",
        "pay_period_start",
        "entry_date",
        "hours_worked",
        "time_in",
        "time_out",
        "entry_type",
        "night_diff_hours",
        "notes",
        "payroll_entry_id",
    ]
    with open(output_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(format_row_dates(row, "pay_period_start", "entry_date"))

    return {"success": True, "path": output_path, "count": len(rows)}


def get_labor_budget_status(year: Optional[int] = None) -> Dict:
    from logic import get_department_pay_summary, get_department_setting

    raw = get_department_setting("annual_labor_budget", "").strip()
    if not raw:
        summary = get_department_pay_summary()
        return {
            "success": True,
            "configured": False,
            "projected_annual": summary.get("department_annual_total", 0),
        }
    try:
        budget = float(raw)
    except ValueError:
        return {"success": False, "message": "Invalid annual_labor_budget setting"}

    yr = year or date.today().year
    ytd = get_payroll_ytd(yr)
    forecast = get_labor_cost_forecast(1)
    projected = forecast.get("annual_projection") or 0.0
    ytd_spent = ytd.get("department_total_pay") or 0.0
    ytd_pct = round(ytd_spent / budget * 100, 1) if budget else 0.0
    projected_pct = round(projected / budget * 100, 1) if budget else 0.0

    return {
        "success": True,
        "configured": True,
        "year": yr,
        "annual_budget": round(budget, 2),
        "ytd_spent": ytd_spent,
        "projected_annual": projected,
        "ytd_pct": ytd_pct,
        "projected_pct": projected_pct,
        "over_budget": projected > budget,
        "remaining_ytd": round(max(0.0, budget - ytd_spent), 2),
    }


def get_dashboard_insights(officer_id: Optional[int] = None) -> Dict:
    from config import REQUEST_STATUS
    from logic import (
        compare_base_updated_schedule,
        get_current_cycle_window,
        get_day_off_requests,
        get_labor_compliance_report,
        get_open_shifts,
        get_pending_day_off_requests,
        get_pending_manual_review_count,
        get_pending_shift_swap_requests,
    )

    today = date.today()
    start, end = get_current_cycle_window(today)
    holidays = _upcoming_holidays(60)
    schedule_diff = compare_base_updated_schedule(
        today.year,
        today.month,
        officer_id=officer_id,
    )
    schedule_diff_count = schedule_diff.get("diff_count", 0) if schedule_diff.get("success") else 0
    pending_all = get_pending_day_off_requests()
    swaps_all = get_pending_shift_swap_requests()

    if officer_id is not None:
        pending = [r for r in pending_all if r["officer_id"] == officer_id]
        pending_swaps = [s for s in swaps_all if s["officer1_id"] == officer_id or s["officer2_id"] == officer_id]
        conflicts = get_schedule_conflicts(start, end, officer_id=officer_id)
        overtime = get_overtime_alerts(officer_id=officer_id)
        hours_watch = get_hours_watch(officer_id=officer_id)
        labor_compliance = get_labor_compliance_report(officer_id=officer_id)
        manual_review = len(
            [
                r
                for r in get_day_off_requests(status_filter=REQUEST_STATUS["pending_manual"])
                if r["officer_id"] == officer_id
            ]
        )
        top_ot = overtime.get("alerts", [{}])[0] if overtime.get("alerts") else {}
        return {
            "success": True,
            "officer_scoped": True,
            "coverage_issues": 0,
            "coverage_gap_count": 0,
            "coverage_gap_critical": 0,
            "coverage_gaps": [],
            "overtime_alerts": overtime.get("alert_count", 0),
            "overtime_alert_top_hours": top_ot.get("hours"),
            "overtime_alert_top_severity": top_ot.get("severity"),
            "hours_watch_count": hours_watch.get("warning_count", 0),
            "hours_watch_critical": hours_watch.get("critical_count", 0),
            "hours_watch_top": hours_watch.get("warnings", [{}])[0] if hours_watch.get("warnings") else None,
            "labor_compliance_count": labor_compliance.get("issue_count", 0),
            "labor_compliance_top": labor_compliance.get("issues", [{}])[0] if labor_compliance.get("issues") else None,
            "schedule_conflicts": conflicts.get("conflict_count", 0),
            "schedule_diff_count": schedule_diff_count,
            "pending_requests": len(pending),
            "pending_swaps": len(pending_swaps),
            "pending_manual_review": manual_review,
            "claimable_open_shifts": len(get_open_shifts(officer_id=officer_id)),
            "open_shifts": 0,
            "upcoming_holidays": holidays,
            "monthly_labor_cost": 0,
            "annual_labor_projection": 0,
            "labor_budget": {"configured": False},
        }

    coverage = get_coverage_report(start, end)
    gap_board = get_coverage_gap_board()
    overtime = get_overtime_alerts()
    hours_watch = get_hours_watch()
    labor_compliance = get_labor_compliance_report()
    conflicts = get_schedule_conflicts(start, end)
    labor = get_labor_cost_forecast(1)
    budget = get_labor_budget_status()
    return {
        "success": True,
        "officer_scoped": False,
        "coverage_issues": coverage.get("issue_count", 0),
        "coverage_gap_count": gap_board.get("gap_count", 0),
        "coverage_gap_critical": gap_board.get("critical_count", 0),
        "coverage_gaps": gap_board.get("gaps", []),
        "overtime_alerts": overtime.get("alert_count", 0),
        "overtime_alert_top_hours": None,
        "overtime_alert_top_severity": None,
        "hours_watch_count": hours_watch.get("warning_count", 0),
        "hours_watch_critical": hours_watch.get("critical_count", 0),
        "hours_watch_top": hours_watch.get("warnings", [{}])[0] if hours_watch.get("warnings") else None,
        "labor_compliance_count": labor_compliance.get("issue_count", 0),
        "labor_compliance_critical": sum(
            1 for i in labor_compliance.get("issues", []) if i.get("severity") == "critical"
        ),
        "labor_compliance_top": labor_compliance.get("issues", [{}])[0] if labor_compliance.get("issues") else None,
        "schedule_conflicts": conflicts.get("conflict_count", 0),
        "schedule_diff_count": schedule_diff_count,
        "pending_requests": len(pending_all),
        "pending_swaps": len(swaps_all),
        "pending_manual_review": get_pending_manual_review_count(),
        "claimable_open_shifts": 0,
        "open_shifts": len(get_open_shifts()),
        "upcoming_holidays": holidays,
        "monthly_labor_cost": labor.get("monthly_average", 0),
        "annual_labor_projection": labor.get("annual_projection", 0),
        "labor_budget": budget,
    }


def export_audit_csv(
    output_path: Optional[str] = None,
    limit: int = 500,
    action_filter: Optional[str] = None,
) -> Dict:
    from logic import get_audit_log

    ensure_data_dirs()
    entries = get_audit_log(limit, action_filter=action_filter)
    if not entries:
        return {"success": False, "message": "No audit log entries"}

    if not output_path:
        output_path = data_path(f"exports/audit_{format_date(date.today())}.csv")

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    fields = ["id", "created_at", "action", "entity_type", "entity_id", "username", "details"]
    with open(output_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in entries:
            writer.writerow(row)

    return {"success": True, "path": output_path, "count": len(entries)}


def export_schedule_diff_csv(
    year: int,
    month: int,
    output_path: Optional[str] = None,
    officer_id: Optional[int] = None,
) -> Dict:
    from logic import compare_base_updated_schedule

    result = compare_base_updated_schedule(year, month, officer_id=officer_id)
    if not result.get("success"):
        return result

    diffs = result.get("diffs", [])
    if not diffs:
        return {"success": False, "message": "No differences between base and updated schedules"}

    ensure_data_dirs()
    if not output_path:
        suffix = f"_officer_{officer_id}" if officer_id else ""
        output_path = data_path(f"exports/schedule_diff_{year}_{month:02d}{suffix}.csv")

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    fields = [
        "assignment_date",
        "officer_name",
        "base_status",
        "updated_status",
        "base_shift_start",
        "base_shift_end",
        "updated_shift_start",
        "updated_shift_end",
        "base_notes",
        "updated_notes",
        "is_manual",
    ]
    with open(output_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in diffs:
            writer.writerow(format_row_dates(row, "assignment_date"))

    return {"success": True, "path": output_path, "count": len(diffs)}


def _upcoming_holidays(days_ahead: int = 60) -> List[Dict]:
    today = date.today()
    end = today + timedelta(days=days_ahead)
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT * FROM holidays
        WHERE holiday_date >= ? AND holiday_date <= ?
        ORDER BY holiday_date
    """,
        (today.isoformat(), end.isoformat()),
    )
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows
