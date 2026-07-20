"""Payroll exception queue + FLSA period banners + combined pay export pack."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from validators import format_date, parse_date, storage_date


def flsa_period_banners(*, reference: Optional[date] = None, limit: int = 40) -> List[Dict[str, Any]]:
    """Per-officer 'hours to OT threshold' for current FLSA / dual period."""
    ref = reference or date.today()
    banners: List[Dict[str, Any]] = []
    try:
        from logic.dual_workforce import compute_officer_ot_split, get_dual_workforce_settings
        from logic.labor_compliance import flsa_threshold_for_period_days, get_flsa_207k_status, get_flsa_work_period
        from logic.officers import get_officers_by_seniority

        dual = get_dual_workforce_settings() or {}
        dual_on = bool(dual.get("enabled") or dual.get("flsa_dual_workforce"))

        for off in get_officers_by_seniority() or []:
            if off.get("active") not in (1, True, "1"):
                continue
            oid = int(off["id"])
            try:
                if dual_on:
                    split = compute_officer_ot_split(oid, reference=ref) or {}
                    hours = float(split.get("hours") or split.get("worked_hours") or 0)
                    thr = float(split.get("threshold") or split.get("ot_threshold") or 40)
                    profile = split.get("profile") or split.get("workforce_class") or "—"
                else:
                    st = get_flsa_207k_status(oid, reference=ref) or {}
                    hours = float(st.get("hours") or st.get("worked_hours") or st.get("total_hours") or 0)
                    thr = float(
                        st.get("threshold")
                        or st.get("threshold_hours")
                        or flsa_threshold_for_period_days(get_flsa_work_period() or 28)
                        or 171
                    )
                    profile = "sworn_7k"
                remaining = thr - hours
                pct = (hours / thr * 100.0) if thr > 0 else 0.0
                level = "ok"
                if remaining <= 0:
                    level = "critical"
                elif remaining <= thr * 0.15:
                    level = "warning"
                banners.append(
                    {
                        "officer_id": oid,
                        "officer_name": off.get("name"),
                        "hours": round(hours, 2),
                        "threshold": thr,
                        "remaining": round(remaining, 2),
                        "pct": round(pct, 1),
                        "level": level,
                        "profile": profile,
                        "message": (f"{off.get('name')}: {hours:g}/{thr:g}h ({remaining:g}h to OT) · {profile}"),
                    }
                )
            except Exception:
                continue
        banners.sort(
            key=lambda b: (0 if b["level"] == "critical" else 1 if b["level"] == "warning" else 2, b["remaining"])
        )
        return banners[:limit]
    except Exception:
        return banners


def list_payroll_exceptions(
    *,
    reference: Optional[date] = None,
    period_start: Optional[str] = None,
) -> Dict[str, Any]:
    """Missing punch / early anomalies / unapproved corrections / unlocked period issues."""
    ref = reference or date.today()
    items: List[Dict[str, Any]] = []

    try:
        from logic.payroll import get_pay_period

        if period_start:
            start = parse_date(period_start)
            period = get_pay_period(start)
        else:
            period = get_pay_period(ref)
        p_start, p_end = period[0], period[1]
    except Exception:
        p_start, p_end = ref, ref

    # Punch edit requests pending
    try:
        from database import connection

        with connection() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    """
                    SELECT * FROM punch_edit_requests
                    WHERE status IN ('Pending', 'pending', 'submitted')
                    ORDER BY id DESC LIMIT 100
                    """
                )
                for row in cur.fetchall() or []:
                    r = dict(row)
                    items.append(
                        {
                            "kind": "punch_correction",
                            "severity": "warning",
                            "officer_id": r.get("officer_id"),
                            "message": f"Punch correction pending #{r.get('id')}",
                            "ref_id": r.get("id"),
                            "date": r.get("work_date") or r.get("created_at"),
                        }
                    )
            except Exception:
                pass
    except Exception:
        pass

    # Timecards missing vs live working days (sample)
    try:
        from datetime import timedelta

        from logic.officers import get_officers_by_seniority
        from logic.payroll.timecard import get_timecard_period
        from logic.scheduling import get_officer_day_status

        for off in (get_officers_by_seniority() or [])[:30]:
            if off.get("active") not in (1, True, "1"):
                continue
            oid = int(off["id"])
            d = p_start
            missing_days = 0
            while d <= p_end and missing_days < 3:
                try:
                    st = get_officer_day_status(oid, d)
                    working = st in ("working", "covering", "swapped", "training")
                except Exception:
                    working = False
                if working:
                    # any timecard row?
                    try:
                        entries = get_timecard_period(oid, p_start, p_end) or []
                        if isinstance(entries, dict):
                            entries = entries.get("entries") or entries.get("rows") or []
                        has = any(
                            str(e.get("work_date") or e.get("entry_date") or "")[:10] == storage_date(d)
                            for e in (entries or [])
                            if isinstance(e, dict)
                        )
                        if not has:
                            missing_days += 1
                            if missing_days <= 2:
                                items.append(
                                    {
                                        "kind": "missing_timecard",
                                        "severity": "warning",
                                        "officer_id": oid,
                                        "officer_name": off.get("name"),
                                        "date": storage_date(d),
                                        "message": f"{off.get('name')}: no timecard on {format_date(d)} (scheduled working)",
                                    }
                                )
                    except Exception:
                        pass
                d += timedelta(days=1)
    except Exception:
        pass

    # FLSA critical banners as exceptions
    for b in flsa_period_banners(reference=ref, limit=15):
        if b.get("level") in ("critical", "warning"):
            items.append(
                {
                    "kind": "flsa_threshold",
                    "severity": b["level"],
                    "officer_id": b.get("officer_id"),
                    "officer_name": b.get("officer_name"),
                    "message": b.get("message"),
                }
            )

    return {
        "success": True,
        "period_start": storage_date(p_start),
        "period_end": storage_date(p_end),
        "count": len(items),
        "items": items,
        "message": f"{len(items)} payroll exception(s)",
    }


def export_pay_pack(
    *,
    period_start: Optional[str] = None,
    reference: Optional[date] = None,
    user_id: Optional[int] = None,
) -> Dict[str, Any]:
    """One pack: ADP CSV + dual OT ledger + OT equity + exception list."""
    ref = reference or date.today()
    paths: List[str] = []
    messages: List[str] = []

    try:
        from logic.payroll import get_pay_period

        if period_start:
            start, end = get_pay_period(parse_date(period_start))
        else:
            start, end = get_pay_period(ref)
    except Exception:
        start, end = ref, ref

    try:
        from logic.exports import export_adp_payroll_pack

        r = export_adp_payroll_pack(start, end)
        if r.get("success") and (r.get("path") or r.get("output_path")):
            paths.append(str(r.get("path") or r.get("output_path")))
        messages.append(r.get("message") or "ADP pack")
    except Exception as exc:
        messages.append(f"ADP: {exc}")

    try:
        from logic.dual_workforce import export_dual_ot_ledger_csv

        r = export_dual_ot_ledger_csv(start, end)
        if r.get("success") and (r.get("path") or r.get("output_path")):
            paths.append(str(r.get("path") or r.get("output_path")))
        messages.append(r.get("message") or "Dual OT ledger")
    except Exception as exc:
        messages.append(f"Dual OT: {exc}")

    try:
        from logic.ot_equity_ledger import export_ot_equity_dual_csv

        r = export_ot_equity_dual_csv()
        if r.get("success") and (r.get("path") or r.get("output_path")):
            paths.append(str(r.get("path") or r.get("output_path")))
        messages.append(r.get("message") or "OT equity")
    except Exception as exc:
        messages.append(f"OT equity: {exc}")

    # Exception list file
    try:
        ex = list_payroll_exceptions(reference=ref, period_start=storage_date(start))
        root = Path(__file__).resolve().parent.parent / "exports"
        root.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = root / f"payroll_exceptions_{storage_date(start)}_{stamp}.csv"
        import csv

        with out.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(
                f,
                fieldnames=["kind", "severity", "officer_id", "officer_name", "date", "message"],
                extrasaction="ignore",
            )
            w.writeheader()
            for row in ex.get("items") or []:
                w.writerow(row)
        paths.append(str(out))
        messages.append(f"Exceptions CSV ({ex.get('count', 0)})")
    except Exception as exc:
        messages.append(f"Exceptions: {exc}")

    return {
        "success": bool(paths),
        "paths": paths,
        "period_start": storage_date(start),
        "period_end": storage_date(end),
        "message": " · ".join(messages) if messages else "No exports produced",
    }


def schedule_to_timecard_defaults(
    officer_id: int,
    *,
    period_start: Optional[str] = None,
    reference: Optional[date] = None,
    user_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Prefill timecard from live schedule for the pay period."""
    from logic.payroll import get_pay_period
    from logic.payroll.timecard import auto_prefill_timecard_from_live_schedule, prefill_timecard_from_schedule

    ref = reference or date.today()
    if period_start:
        start, _end = get_pay_period(parse_date(period_start))
    else:
        start, _end = get_pay_period(ref)

    try:
        r = auto_prefill_timecard_from_live_schedule(int(officer_id), start)
    except Exception:
        try:
            r = prefill_timecard_from_schedule(int(officer_id), start)
        except Exception as exc2:
            return {"success": False, "message": str(exc2)}

    if isinstance(r, dict):
        return r
    return {"success": True, "message": "Timecard prefilled from live schedule", "result": r}
