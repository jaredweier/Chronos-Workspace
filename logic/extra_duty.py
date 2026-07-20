"""
Extra duty / special detail — TeleStaff / Netchex / PowerTime pattern.

Uses open_shifts as the staffing vacancy vehicle with a structured notes prefix
so duty roster and off-duty events stay distinct without a second roster engine.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from logic.operations import create_open_shift, get_open_shifts
from validators import format_date, parse_date

EXTRA_DUTY_PREFIX = "EXTRA_DUTY|"


def _encode_notes(
    *,
    event_name: str,
    location: str = "",
    billing_code: str = "",
    notes: str = "",
) -> str:
    # Pipe-delimited structured note for list/filter without schema change
    parts = [
        event_name.strip() or "Extra duty",
        (location or "").strip(),
        (billing_code or "").strip(),
        (notes or "").strip(),
    ]
    return EXTRA_DUTY_PREFIX + "|".join(parts)


def _decode_notes(raw: Optional[str]) -> Dict[str, str]:
    text = (raw or "").strip()
    if not text.startswith(EXTRA_DUTY_PREFIX):
        return {
            "is_extra_duty": False,
            "event_name": "",
            "location": "",
            "billing_code": "",
            "notes": text,
        }
    body = text[len(EXTRA_DUTY_PREFIX) :]
    bits = body.split("|", 3)
    while len(bits) < 4:
        bits.append("")
    return {
        "is_extra_duty": True,
        "event_name": bits[0],
        "location": bits[1],
        "billing_code": bits[2],
        "notes": bits[3],
    }


def create_extra_duty_event(
    event_date: str,
    shift_start: str,
    shift_end: str,
    *,
    event_name: str = "Extra duty",
    location: str = "",
    billing_code: str = "",
    squad: Optional[str] = None,
    notes: str = "",
    user_id: Optional[int] = None,
) -> Dict:
    """
    TeleStaff-style extra duty: post a fillable vacancy tagged for off-duty events.

    Billing/invoicing remains external — billing_code is stored for payroll export notes.
    """
    encoded = _encode_notes(
        event_name=event_name,
        location=location,
        billing_code=billing_code,
        notes=notes,
    )
    result = create_open_shift(
        event_date,
        shift_start,
        shift_end,
        squad=squad,
        notes=encoded,
        user_id=user_id,
    )
    if result.get("success"):
        result["extra_duty"] = True
        result["event_name"] = event_name
        result["message"] = result.get("message") or f"Extra duty posted: {event_name}"
    return result


def export_extra_duty_invoice_csv(
    *,
    status: str = "open",
    output_path: Optional[str] = None,
) -> Dict:
    """
    TeleStaff-style cost-recovery export: event, location, billing code, hours window.
    Not a full AR invoice — finance handoff CSV.
    """
    import csv
    from datetime import datetime
    from pathlib import Path

    # Invoice handoff usually wants open + filled; "all" pulls both.
    if status == "all":
        open_ev = list_extra_duty_events(status="open", limit=500).get("events") or []
        filled_ev = list_extra_duty_events(status="filled", limit=500).get("events") or []
        events = open_ev + filled_ev
    else:
        events = list_extra_duty_events(status=status or "open", limit=500).get("events") or []
    root = Path(__file__).resolve().parent.parent
    out_dir = root / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = (
        Path(output_path)
        if output_path
        else out_dir / (f"extra_duty_invoice_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
    )
    fields = [
        "shift_date",
        "event_name",
        "location",
        "billing_code",
        "shift_start",
        "shift_end",
        "squad",
        "station",
        "status",
        "filled_by_name",
        "notes",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for e in events:
            w.writerow({k: e.get(k, "") for k in fields})
    return {
        "success": True,
        "path": str(path),
        "count": len(events),
        "message": f"Exported {len(events)} extra-duty row(s)",
    }


def claim_extra_duty_event(
    shift_id: int,
    officer_id: int,
    *,
    user_id: Optional[int] = None,
) -> Dict:
    """Officer claims an EXTRA_DUTY open shift (marketplace fill)."""
    from database import connection
    from logic.operations import fill_open_shift

    with connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM open_shifts WHERE id = ?", (int(shift_id),))
        row = cur.fetchone()
    if not row:
        return {"success": False, "message": "Extra-duty shift not found"}
    shift = dict(row)
    meta = _decode_notes(shift.get("notes"))
    if not meta.get("is_extra_duty"):
        return {"success": False, "message": "Shift is not tagged as extra duty"}
    if (shift.get("status") or "").lower() != "open":
        return {"success": False, "message": f"Shift not open ({shift.get('status')})"}

    result = fill_open_shift(int(shift_id), int(officer_id), user_id=user_id)
    if result.get("success"):
        result["extra_duty"] = True
        result["event_name"] = meta.get("event_name")
        result["message"] = result.get("message") or f"Claimed extra duty: {meta.get('event_name')}"
    return result


def marketplace_board(*, limit: int = 50) -> Dict:
    """Open + recent filled extra-duty board for Chronos self-service."""
    open_ev = list_extra_duty_events(status="open", limit=limit).get("events") or []
    filled_ev = list_extra_duty_events(status="filled", limit=min(limit, 20)).get("events") or []
    return {
        "success": True,
        "open": open_ev,
        "filled_recent": filled_ev,
        "open_count": len(open_ev),
        "filled_count": len(filled_ev),
        "message": f"{len(open_ev)} open extra-duty post(s)",
    }


def list_extra_duty_events(
    *,
    status: str = "open",
    limit: int = 50,
) -> Dict:
    """List shifts tagged EXTRA_DUTY (TeleStaff-style special detail)."""
    statuses = ["open", "filled"] if status == "all" else [status or "open"]
    out: List[Dict] = []
    for st in statuses:
        rows = get_open_shifts(status=st, limit=max(limit * 4, 80)) or []
        for r in rows:
            if not isinstance(r, dict):
                continue
            meta = _decode_notes(r.get("notes"))
            if not meta.get("is_extra_duty"):
                continue
            item = dict(r)
            item.update(meta)
            # Prefer free-text notes field from encoded tail (not full raw)
            raw_date = r.get("shift_date") or r.get("date")
            try:
                item["date_display"] = format_date(parse_date(str(raw_date))) if raw_date else ""
            except Exception:
                item["date_display"] = str(raw_date or "")
            out.append(item)
            if len(out) >= limit:
                return {"success": True, "count": len(out), "events": out}
    return {"success": True, "count": len(out), "events": out}
