"""OT equalization dual ledger — hours offered vs hours worked (CrewSense pattern)."""

from __future__ import annotations

from typing import Any, Dict, Optional

from database import connection


def ensure_ot_equity_tables() -> None:
    with connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ot_equity_ledger (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                officer_id INTEGER NOT NULL,
                entry_type TEXT NOT NULL,
                hours REAL NOT NULL DEFAULT 0,
                event_date DATE,
                source TEXT,
                source_id INTEGER,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_by_user_id INTEGER,
                FOREIGN KEY (officer_id) REFERENCES officers(id)
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ot_equity_officer ON ot_equity_ledger(officer_id, entry_type)")
        conn.commit()


def record_ot_offer(
    officer_id: int,
    hours: float,
    *,
    event_date: Optional[str] = None,
    source: str = "callback",
    source_id: Optional[int] = None,
    notes: str = "",
    user_id: Optional[int] = None,
) -> Dict[str, Any]:
    return _insert(
        officer_id,
        "offered",
        hours,
        event_date=event_date,
        source=source,
        source_id=source_id,
        notes=notes,
        user_id=user_id,
    )


def record_ot_worked(
    officer_id: int,
    hours: float,
    *,
    event_date: Optional[str] = None,
    source: str = "timecard",
    source_id: Optional[int] = None,
    notes: str = "",
    user_id: Optional[int] = None,
) -> Dict[str, Any]:
    return _insert(
        officer_id,
        "worked",
        hours,
        event_date=event_date,
        source=source,
        source_id=source_id,
        notes=notes,
        user_id=user_id,
    )


def _insert(
    officer_id: int,
    entry_type: str,
    hours: float,
    *,
    event_date: Optional[str],
    source: str,
    source_id: Optional[int],
    notes: str,
    user_id: Optional[int],
) -> Dict[str, Any]:
    ensure_ot_equity_tables()
    try:
        oid = int(officer_id)
        hrs = float(hours)
    except (TypeError, ValueError):
        return {"success": False, "message": "Invalid officer or hours"}
    if hrs < 0:
        return {"success": False, "message": "Hours must be ≥ 0"}
    with connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO ot_equity_ledger
            (officer_id, entry_type, hours, event_date, source, source_id, notes, created_by_user_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (oid, entry_type, hrs, event_date, source, source_id, (notes or "")[:240], user_id),
        )
        conn.commit()
        return {"success": True, "id": int(cur.lastrowid)}


def get_ot_equity_summary(*, limit: int = 100) -> Dict[str, Any]:
    """Per-officer offered vs worked totals for fairness boards."""
    ensure_ot_equity_tables()
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT e.officer_id,
                   o.name AS officer_name,
                   o.seniority_rank,
                   SUM(CASE WHEN e.entry_type = 'offered' THEN e.hours ELSE 0 END) AS hours_offered,
                   SUM(CASE WHEN e.entry_type = 'worked' THEN e.hours ELSE 0 END) AS hours_worked
            FROM ot_equity_ledger e
            LEFT JOIN officers o ON o.id = e.officer_id
            GROUP BY e.officer_id
            ORDER BY hours_offered DESC, hours_worked DESC
            LIMIT ?
            """,
            (max(1, min(limit, 500)),),
        ).fetchall()
    out = []
    for r in rows:
        offered = float(r["hours_offered"] or 0)
        worked = float(r["hours_worked"] or 0)
        out.append(
            {
                "officer_id": r["officer_id"],
                "officer_name": r["officer_name"] or f"#{r['officer_id']}",
                "seniority_rank": r["seniority_rank"],
                "hours_offered": offered,
                "hours_worked": worked,
                "delta_offered_minus_worked": round(offered - worked, 2),
                "acceptance_rate": round(worked / offered, 3) if offered > 0 else None,
            }
        )
    return {"success": True, "rows": out, "count": len(out)}


def export_ot_equity_dual_csv() -> Dict[str, Any]:
    from datetime import datetime
    from pathlib import Path

    from paths import data_path

    summary = get_ot_equity_summary(limit=500)
    path = Path(data_path("exports")) / f"ot_equity_dual_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["officer_id,officer_name,seniority_rank,hours_offered,hours_worked,delta,acceptance_rate"]
    for r in summary.get("rows") or []:
        lines.append(
            f"{r.get('officer_id')},"
            f'"{(r.get("officer_name") or "").replace(chr(34), "")}",'
            f"{r.get('seniority_rank') or ''},"
            f"{r.get('hours_offered')},"
            f"{r.get('hours_worked')},"
            f"{r.get('delta_offered_minus_worked')},"
            f"{r.get('acceptance_rate') if r.get('acceptance_rate') is not None else ''}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"success": True, "path": str(path), "count": len(summary.get("rows") or [])}
