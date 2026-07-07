"""Banked time balances, earned/used tracking, and FLSA display from timecards."""

from calendar import monthrange
from datetime import date
from typing import Dict, List, Optional, Tuple

from config import CALLBACK_MINIMUM_HOURS, TIMECARD_REGULAR_TYPE
from database import get_connection
from logic.labor_compliance import get_flsa_payroll_summary, get_flsa_work_period_days
from logic.officers import get_officer_by_id
from logic.operations import get_officer_time_banks
from logic.payroll import format_pay_period_label, get_adjacent_pay_period, get_pay_code_rules, get_pay_period
from validators import format_date, parse_date

TIME_SCOPES = ("pay_period", "month", "year", "all_time")

BANK_TYPES: Tuple[str, ...] = ("comp", "sick", "float_holiday", "holiday")

_BANK_META = {
    "comp": {
        "label": "Comp Time",
        "balance_key": "comp_hours",
        "delta_key": "comp_bank_delta",
    },
    "sick": {
        "label": "Sick Leave",
        "balance_key": "sick_hours",
        "delta_key": "sick_bank_delta",
    },
    "float_holiday": {
        "label": "Float Holiday",
        "balance_key": "float_holiday_hours",
        "delta_key": "float_holiday_bank_delta",
    },
    "holiday": {
        "label": "Holiday",
        "balance_key": "holiday_hours",
        "delta_key": "holiday_bank_delta",
    },
}


def resolve_time_scope(
    scope: str,
    reference: Optional[date] = None,
) -> Tuple[Optional[date], Optional[date], str]:
    """Return inclusive start/end and display label for a time scope."""
    if scope not in TIME_SCOPES:
        scope = "pay_period"
    ref = reference or date.today()
    if scope == "pay_period":
        start, end = get_pay_period(ref)
        return start, end, format_pay_period_label(start, end)
    if scope == "month":
        start = ref.replace(day=1)
        last_day = monthrange(ref.year, ref.month)[1]
        end = date(ref.year, ref.month, last_day)
        return start, end, ref.strftime("%B %Y")
    if scope == "year":
        start = date(ref.year, 1, 1)
        end = date(ref.year, 12, 31)
        return start, end, str(ref.year)
    return None, None, "All time"


def _date_clause(start: Optional[date], end: Optional[date], column: str = "entry_date") -> Tuple[str, List]:
    if start is None or end is None:
        return "", []
    return f" AND {column} >= ? AND {column} <= ?", [start.isoformat(), end.isoformat()]


def _preview_bank_deltas(
    entry_type: str,
    hours: float,
    base_rate: float = 0.0,
    night_diff_hours: float = 0.0,
) -> Dict[str, float]:
    """Compute bank deltas for reporting without balance-cap enforcement."""
    rules = get_pay_code_rules()
    code = (rules.get("codes") or {}).get(entry_type)
    if not code:
        return {key: 0.0 for key in BANK_TYPES}

    global_cfg = rules.get("global") or {}
    calc_hours = hours
    if code.get("uses_callback_minimum"):
        from logic.labor_compliance import callback_payable_hours

        calc_hours = callback_payable_hours(
            hours,
            float(global_cfg.get("callback_minimum_hours", CALLBACK_MINIMUM_HOURS)),
        )

    deltas = {key: 0.0 for key in BANK_TYPES}
    credit_ratio = float(code.get("comp_bank_credit_ratio", 0.0) or 0.0)
    if credit_ratio > 0:
        deltas["comp"] = round(calc_hours * credit_ratio, 2)
    if code.get("debit_comp_bank"):
        deltas["comp"] = -round(calc_hours, 2)
    if code.get("debit_sick_bank"):
        deltas["sick"] = -round(calc_hours, 2)
    if code.get("debit_float_holiday_bank"):
        deltas["float_holiday"] = -round(calc_hours, 2)
    if code.get("debit_holiday_bank"):
        deltas["holiday"] = -round(calc_hours, 2)
    return deltas


def _deltas_from_payroll_row(row: Dict) -> Dict[str, float]:
    return {
        "comp": float(row.get("comp_bank_delta") or 0.0),
        "sick": float(row.get("sick_bank_delta") or 0.0),
        "float_holiday": float(row.get("float_holiday_bank_delta") or 0.0),
        "holiday": float(row.get("holiday_bank_delta") or 0.0),
    }


def _split_earned_used(delta: float) -> Tuple[float, float]:
    if delta > 0:
        return delta, 0.0
    if delta < 0:
        return 0.0, abs(delta)
    return 0.0, 0.0


def _collect_timecard_bank_events(
    officer_id: int,
    start: Optional[date],
    end: Optional[date],
) -> List[Dict]:
    officer = get_officer_by_id(officer_id)
    if not officer:
        return []

    clause, params = _date_clause(start, end, column="t.entry_date")
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        f"""
        SELECT t.*, p.comp_bank_delta AS pe_comp, p.sick_bank_delta AS pe_sick,
               p.float_holiday_bank_delta AS pe_float, p.holiday_bank_delta AS pe_holiday
        FROM timecard_entries t
        LEFT JOIN payroll_entries p ON p.id = t.payroll_entry_id
        WHERE t.officer_id = ?
          AND t.hours_worked > 0
          AND t.entry_type != ?
          {clause}
        ORDER BY t.entry_date, t.id
        """,
        [officer_id, TIMECARD_REGULAR_TYPE, *params],
    )
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    events: List[Dict] = []
    base_rate = float(officer.get("pay_rate") or 0.0)
    for row in rows:
        if row.get("payroll_entry_id"):
            deltas = {
                "comp": float(row.get("pe_comp") or 0.0),
                "sick": float(row.get("pe_sick") or 0.0),
                "float_holiday": float(row.get("pe_float") or 0.0),
                "holiday": float(row.get("pe_holiday") or 0.0),
            }
        else:
            deltas = _preview_bank_deltas(
                row["entry_type"],
                float(row["hours_worked"]),
                base_rate=base_rate,
                night_diff_hours=float(row.get("night_diff_hours") or 0.0),
            )
        if not any(deltas.values()):
            continue
        events.append(
            {
                "source": "timecard",
                "entry_date": row["entry_date"],
                "entry_type": row["entry_type"],
                "hours_worked": float(row["hours_worked"]),
                "timecard_id": row.get("id"),
                "payroll_entry_id": row.get("payroll_entry_id"),
                "notes": row.get("notes") or "",
                "deltas": deltas,
            }
        )
    return events


def _collect_payroll_bank_events(
    officer_id: int,
    start: Optional[date],
    end: Optional[date],
) -> List[Dict]:
    clause, params = _date_clause(start, end)
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        f"""
        SELECT *
        FROM payroll_entries
        WHERE officer_id = ?
          AND (
            ABS(COALESCE(comp_bank_delta, 0)) > 0
            OR ABS(COALESCE(sick_bank_delta, 0)) > 0
            OR ABS(COALESCE(float_holiday_bank_delta, 0)) > 0
            OR ABS(COALESCE(holiday_bank_delta, 0)) > 0
          )
          {clause}
        ORDER BY entry_date, id
        """,
        [officer_id, *params],
    )
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    events: List[Dict] = []
    for row in rows:
        deltas = _deltas_from_payroll_row(row)
        if not any(deltas.values()):
            continue
        events.append(
            {
                "source": "payroll",
                "entry_date": row["entry_date"],
                "entry_type": row["entry_type"],
                "hours_worked": float(row.get("hours") or 0.0),
                "timecard_id": None,
                "payroll_entry_id": row.get("id"),
                "notes": row.get("notes") or "",
                "deltas": deltas,
            }
        )
    return events


def _merge_bank_events(timecard_events: List[Dict], payroll_events: List[Dict]) -> List[Dict]:
    linked_payroll_ids = {e["payroll_entry_id"] for e in timecard_events if e.get("payroll_entry_id")}
    merged = list(timecard_events)
    for event in payroll_events:
        if event.get("payroll_entry_id") in linked_payroll_ids:
            continue
        merged.append(event)
    merged.sort(key=lambda e: (e["entry_date"], e.get("payroll_entry_id") or 0, e.get("timecard_id") or 0))
    return merged


def _summarize_bank_events(events: List[Dict]) -> Dict[str, Dict[str, float]]:
    summary = {bank: {"earned": 0.0, "used": 0.0, "net": 0.0} for bank in BANK_TYPES}
    for event in events:
        for bank in BANK_TYPES:
            delta = float(event["deltas"].get(bank, 0.0))
            earned, used = _split_earned_used(delta)
            summary[bank]["earned"] = round(summary[bank]["earned"] + earned, 2)
            summary[bank]["used"] = round(summary[bank]["used"] + used, 2)
            summary[bank]["net"] = round(summary[bank]["net"] + delta, 2)
    return summary


def get_banked_time_summary(
    officer_id: int,
    scope: str = "pay_period",
    reference: Optional[date] = None,
) -> Dict:
    officer = get_officer_by_id(officer_id)
    if not officer:
        return {"success": False, "message": "Officer not found"}

    start, end, scope_label = resolve_time_scope(scope, reference)
    as_of = end or date.today()
    balances = get_officer_time_banks(officer_id, as_of)
    if not balances.get("success"):
        return balances

    timecard_events = _collect_timecard_bank_events(officer_id, start, end)
    payroll_events = _collect_payroll_bank_events(officer_id, start, end)
    events = _merge_bank_events(timecard_events, payroll_events)
    activity = _summarize_bank_events(events)

    banks = []
    for bank_key in BANK_TYPES:
        meta = _BANK_META[bank_key]
        bal = float(balances.get(meta["balance_key"], 0.0))
        act = activity[bank_key]
        banks.append(
            {
                "key": bank_key,
                "label": meta["label"],
                "balance": round(bal, 2),
                "earned": act["earned"],
                "used": act["used"],
                "net": act["net"],
            }
        )

    flsa = get_flsa_payroll_summary(officer_id, as_of)
    return {
        "success": True,
        "officer_id": officer_id,
        "officer_name": officer["name"],
        "scope": scope,
        "scope_label": scope_label,
        "period_start": start.isoformat() if start else None,
        "period_end": end.isoformat() if end else None,
        "period_start_display": format_date(start) if start else "",
        "period_end_display": format_date(end) if end else "",
        "banks": banks,
        "flsa": flsa,
        "flsa_work_period_days": get_flsa_work_period_days(),
        "transaction_count": len(events),
    }


def get_bank_transactions(
    officer_id: int,
    bank_type: str,
    scope: str = "pay_period",
    reference: Optional[date] = None,
) -> Dict:
    if bank_type not in BANK_TYPES:
        return {"success": False, "message": f"Unknown bank type: {bank_type}"}

    officer = get_officer_by_id(officer_id)
    if not officer:
        return {"success": False, "message": "Officer not found"}

    start, end, scope_label = resolve_time_scope(scope, reference)
    timecard_events = _collect_timecard_bank_events(officer_id, start, end)
    payroll_events = _collect_payroll_bank_events(officer_id, start, end)
    events = _merge_bank_events(timecard_events, payroll_events)

    transactions = []
    for event in events:
        delta = float(event["deltas"].get(bank_type, 0.0))
        if abs(delta) < 0.005:
            continue
        earned, used = _split_earned_used(delta)
        transactions.append(
            {
                "entry_date": event["entry_date"],
                "entry_date_display": format_date(parse_date(event["entry_date"])),
                "entry_type": event["entry_type"],
                "hours_worked": event["hours_worked"],
                "delta": round(delta, 2),
                "earned": earned,
                "used": used,
                "source": event["source"],
                "notes": event.get("notes") or "",
            }
        )

    meta = _BANK_META[bank_type]
    return {
        "success": True,
        "bank_type": bank_type,
        "bank_label": meta["label"],
        "scope": scope,
        "scope_label": scope_label,
        "period_start": start.isoformat() if start else None,
        "period_end": end.isoformat() if end else None,
        "transactions": transactions,
        "totals": {
            "earned": round(sum(t["earned"] for t in transactions), 2),
            "used": round(sum(t["used"] for t in transactions), 2),
            "net": round(sum(t["delta"] for t in transactions), 2),
        },
    }


def get_timecard_entries_for_scope(
    officer_id: int,
    scope: str = "pay_period",
    reference: Optional[date] = None,
) -> Dict:
    """Flat timecard listing for month/year/all-time views."""
    officer = get_officer_by_id(officer_id)
    if not officer:
        return {"success": False, "message": "Officer not found"}

    start, end, scope_label = resolve_time_scope(scope, reference)
    clause, params = _date_clause(start, end)
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        f"""
        SELECT *
        FROM timecard_entries
        WHERE officer_id = ?
          AND hours_worked > 0
          {clause}
        ORDER BY entry_date, id
        """,
        [officer_id, *params],
    )
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    total_hours = round(sum(float(r.get("hours_worked") or 0.0) for r in rows), 2)
    return {
        "success": True,
        "officer": officer,
        "scope": scope,
        "scope_label": scope_label,
        "period_start": start.isoformat() if start else None,
        "period_end": end.isoformat() if end else None,
        "entries": rows,
        "total_hours": total_hours,
        "entry_count": len(rows),
    }


def shift_scope_reference(scope: str, reference: date, direction: int) -> date:
    """Move reference date backward/forward within a scope."""
    if scope == "pay_period":
        start, _ = get_pay_period(reference)
        next_start, _ = get_adjacent_pay_period(start, direction)
        return next_start
    if scope == "month":
        month = reference.month + direction
        year = reference.year
        while month < 1:
            month += 12
            year -= 1
        while month > 12:
            month -= 12
            year += 1
        day = min(reference.day, monthrange(year, month)[1])
        return date(year, month, day)
    if scope == "year":
        return date(reference.year + direction, reference.month, reference.day)
    return reference
