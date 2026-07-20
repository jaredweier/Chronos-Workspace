"""Dashboard and analytics delegates (dashboard + reports slices)."""

from datetime import date
from typing import Dict, List, Optional

from database import connection
from logic.officers import get_officers_by_seniority
from logic.payroll import project_officer_annual_pay


def get_audit_log(limit: int = 50, action_filter: Optional[str] = None) -> List[Dict]:
    with connection() as conn:
        cursor = conn.cursor()
        query = """
            SELECT a.*, u.username
            FROM audit_log a
            LEFT JOIN app_users u ON a.user_id = u.id
        """
        params: List = []
        if action_filter:
            query += " WHERE a.action LIKE ?"
            params.append(f"%{action_filter}%")
        query += " ORDER BY a.created_at DESC LIMIT ?"
        params.append(limit)
        cursor.execute(query, tuple(params))
        rows = [dict(r) for r in cursor.fetchall()]
    return rows


def get_dashboard_kpis_fast(officer_id: Optional[int] = None) -> Dict:
    """Lightweight home KPIs for Chronos Command (avoids multi-second analytics scans).

    Full labor/coverage intelligence remains on Ops Reports via get_dashboard_insights.
    """
    from logic.requests import get_pending_day_off_requests, get_pending_shift_swap_requests

    try:
        pending_all = get_pending_day_off_requests() or []
    except Exception:
        pending_all = []
    try:
        swaps_all = get_pending_shift_swap_requests() or []
    except Exception:
        swaps_all = []

    if officer_id is not None:
        pending = [r for r in pending_all if r.get("officer_id") == officer_id]
        swaps = [s for s in swaps_all if s.get("officer1_id") == officer_id or s.get("officer2_id") == officer_id]
    else:
        pending = pending_all
        swaps = swaps_all

    # Cheap gap signal: count open manual-review leave only (not full coverage board)
    try:
        from config import REQUEST_STATUS
        from logic.requests import get_day_off_requests

        manual = get_day_off_requests(status_filter=REQUEST_STATUS.get("pending_manual", "Pending Manual Review"))
        if officer_id is not None:
            manual = [r for r in (manual or []) if r.get("officer_id") == officer_id]
        manual_n = len(manual or [])
    except Exception:
        manual_n = 0

    return {
        "success": True,
        "fast": True,
        "pending_requests": len(pending),
        "pending_swaps": len(swaps),
        "coverage_gap_count": 0,
        "coverage_issues": manual_n,
        "pending_manual_review": manual_n,
    }


def get_coverage_report(start_date: date, end_date: date) -> Dict:
    from logic.analytics import get_coverage_report as _report

    return _report(start_date, end_date)


def get_coverage_gap_board(hours_ahead: int = 48) -> Dict:
    from logic.analytics import get_coverage_gap_board as _board

    return _board(hours_ahead=hours_ahead)


def get_hours_watch(
    period_start: Optional[date] = None,
    officer_id: Optional[int] = None,
) -> Dict:
    from logic.analytics import get_hours_watch as _watch

    return _watch(period_start=period_start, officer_id=officer_id)


def get_labor_compliance_report(officer_id: Optional[int] = None) -> Dict:
    from logic.labor_compliance import get_labor_compliance_report as _report

    return _report(officer_id=officer_id)


def get_equitable_ot_ledger(period_start: Optional[date] = None) -> Dict:
    from logic.analytics import get_equitable_ot_ledger as _ledger

    return _ledger(period_start=period_start)


def get_dashboard_insights(officer_id: Optional[int] = None) -> Dict:
    from logic.analytics import get_dashboard_insights as _insights

    return _insights(officer_id=officer_id)


def get_department_pay_summary() -> Dict:
    officers = [o for o in get_officers_by_seniority() if o.get("active") == 1]
    rows = []
    total_pay = 0.0
    for officer in officers:
        proj = project_officer_annual_pay(officer["id"])
        if proj.get("success"):
            rows.append({**proj, "officer": officer})
            total_pay += proj["total_annual_pay"]
    return {
        "success": True,
        "officers": rows,
        "department_annual_total": round(total_pay, 2),
        "avg_pay_rate": round(sum(o["pay_rate"] for o in officers) / len(officers), 2) if officers else 0,
    }


def get_labor_budget_status(year: Optional[int] = None) -> Dict:
    from logic.analytics import get_labor_budget_status as _status

    return _status(year)


def get_labor_cost_forecast(months_ahead: int = 3) -> Dict:
    from logic.analytics import get_labor_cost_forecast as _forecast

    return _forecast(months_ahead)


def get_overtime_alerts(
    period_start: Optional[date] = None,
    hours_threshold: float = 80.0,
    officer_id: Optional[int] = None,
) -> Dict:
    from logic.analytics import get_overtime_alerts as _alerts

    return _alerts(period_start, hours_threshold, officer_id=officer_id)


def get_payroll_ytd(year: Optional[int] = None) -> Dict:
    from logic.analytics import get_payroll_ytd as _ytd

    return _ytd(year)
