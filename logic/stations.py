"""Multi-station / post matrix (ESO / multi-site sheriff pattern)."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from database import connection


def ensure_stations_table() -> None:
    with connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS station_posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                min_staff INTEGER DEFAULT 1,
                active INTEGER DEFAULT 1,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()


def list_station_posts(*, active_only: bool = True) -> List[Dict[str, Any]]:
    ensure_stations_table()
    sql = "SELECT * FROM station_posts"
    if active_only:
        sql += " WHERE active = 1"
    sql += " ORDER BY code"
    with connection() as conn:
        return [dict(r) for r in conn.execute(sql).fetchall()]


def upsert_station_post(
    code: str,
    name: str,
    *,
    min_staff: int = 1,
    active: bool = True,
    notes: str = "",
) -> Dict[str, Any]:
    ensure_stations_table()
    code = (code or "").strip().upper()
    name = (name or "").strip()
    if not code or not name:
        return {"success": False, "message": "Code and name required"}
    try:
        ms = max(0, int(min_staff))
    except (TypeError, ValueError):
        ms = 1
    with connection() as conn:
        existing = conn.execute("SELECT id FROM station_posts WHERE code = ?", (code,)).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE station_posts SET name = ?, min_staff = ?, active = ?, notes = ?
                WHERE code = ?
                """,
                (name, ms, 1 if active else 0, (notes or "")[:240], code),
            )
            conn.commit()
            return {"success": True, "id": int(existing["id"]), "message": f"Updated station {code}"}
        cur = conn.execute(
            """
            INSERT INTO station_posts (code, name, min_staff, active, notes)
            VALUES (?, ?, ?, ?, ?)
            """,
            (code, name, ms, 1 if active else 0, (notes or "")[:240]),
        )
        conn.commit()
        return {"success": True, "id": int(cur.lastrowid), "message": f"Created station {code}"}


def get_station_min_staffing_matrix() -> Dict[str, Any]:
    """Min staff by station code for multi-post coverage."""
    posts = list_station_posts(active_only=True)
    matrix = {p["code"]: int(p.get("min_staff") or 1) for p in posts}
    # Also merge department setting JSON if present
    try:
        from logic.operations import get_department_setting

        raw = get_department_setting("station_min_staffing_json", "") or ""
        if raw.strip():
            extra = json.loads(raw)
            if isinstance(extra, dict):
                for k, v in extra.items():
                    try:
                        matrix[str(k).upper()] = int(v)
                    except (TypeError, ValueError):
                        pass
    except Exception:
        pass
    return {"success": True, "matrix": matrix, "posts": posts}


def officers_by_station() -> Dict[str, Any]:
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT COALESCE(NULLIF(TRIM(station), ''), 'UNASSIGNED') AS station,
                   COUNT(*) AS n
            FROM officers WHERE active = 1
            GROUP BY station
            ORDER BY station
            """
        ).fetchall()
    return {
        "success": True,
        "counts": {r["station"]: int(r["n"]) for r in rows},
    }


def ensure_default_hq_station(*, min_staff: Optional[int] = None) -> Dict[str, Any]:
    """Create HQ post if none configured. Does not overwrite existing posts."""
    ensure_stations_table()
    posts = list_station_posts(active_only=False)
    if posts:
        hq = next((p for p in posts if str(p.get("code") or "").upper() == "HQ"), None)
        if hq:
            return {"success": True, "created": False, "id": hq.get("id"), "message": "HQ already exists"}
        return {"success": True, "created": False, "message": f"{len(posts)} station(s) already configured"}
    # Default min: at least 2 for patrol floor, or 1 for tiny rosters
    n_active = 0
    try:
        with connection() as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM officers WHERE active = 1").fetchone()
            n_active = int(row["n"] if row else 0)
    except Exception:
        n_active = 0
    ms = int(min_staff) if min_staff is not None else (2 if n_active >= 4 else 1)
    return upsert_station_post("HQ", "Headquarters", min_staff=ms, active=True, notes="Default seed post")


def assign_unassigned_to_station(
    station_code: str = "HQ",
    *,
    only_active: bool = True,
    user_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Assign officers with blank/null station to station_code. Leaves others alone."""
    code = (station_code or "HQ").strip().upper() or "HQ"
    ensure_stations_table()
    # Ensure post exists so board can count
    posts = {str(p.get("code") or "").upper() for p in list_station_posts(active_only=False)}
    if code not in posts:
        upsert_station_post(code, code.title() if code != "HQ" else "Headquarters", min_staff=1)

    sql = """
        UPDATE officers
        SET station = ?
        WHERE (station IS NULL OR TRIM(station) = '')
    """
    if only_active:
        sql += " AND active = 1"
    with connection() as conn:
        cur = conn.execute(sql, (code,))
        n = int(cur.rowcount or 0)
        conn.commit()
    try:
        from logic.users import log_audit_action

        log_audit_action(
            "roster.station_assign_unassigned",
            "officers",
            None,
            user_id,
            f"assigned={n} station={code}",
        )
    except Exception:
        pass
    return {
        "success": True,
        "updated": n,
        "station": code,
        "message": f"Assigned {n} unassigned officer(s) to {code}",
    }


def bulk_set_station(
    station_code: str,
    *,
    officer_ids: Optional[List[int]] = None,
    only_unassigned: bool = False,
    only_active: bool = True,
    user_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Set station for many officers (roster bulk action)."""
    code = (station_code or "").strip().upper()
    if not code:
        return {"success": False, "message": "Station code required"}
    ensure_stations_table()
    posts = {str(p.get("code") or "").upper() for p in list_station_posts(active_only=False)}
    if code not in posts:
        upsert_station_post(code, code if code != "HQ" else "Headquarters", min_staff=1)

    clauses = ["1=1"]
    params: List[Any] = [code]
    if officer_ids is not None:
        ids = [int(x) for x in officer_ids if x is not None]
        if not ids:
            return {"success": False, "message": "No officer ids"}
        placeholders = ",".join("?" * len(ids))
        clauses.append(f"id IN ({placeholders})")
        params.extend(ids)
    if only_unassigned:
        clauses.append("(station IS NULL OR TRIM(station) = '')")
    if only_active:
        clauses.append("active = 1")
    where = " AND ".join(clauses)
    with connection() as conn:
        cur = conn.execute(f"UPDATE officers SET station = ? WHERE {where}", params)
        n = int(cur.rowcount or 0)
        conn.commit()
    try:
        from logic.users import log_audit_action

        log_audit_action(
            "roster.bulk_set_station",
            "officers",
            None,
            user_id,
            f"updated={n} station={code} only_unassigned={only_unassigned}",
        )
    except Exception:
        pass
    return {
        "success": True,
        "updated": n,
        "station": code,
        "message": f"Set station {code} on {n} officer(s)",
    }


def station_staffing_board() -> Dict[str, Any]:
    """Compare configured station min_staff vs active roster headcount (ESO multi-post pattern).

    Matches officer.station to post codes case-insensitively. Posts with no matching
    officers count as 0. UNASSIGNED officers are reported separately (not applied to mins).
    """
    ensure_stations_table()
    posts = list_station_posts(active_only=True)
    counts_raw = officers_by_station().get("counts") or {}
    # Normalize keys for case-insensitive match
    counts_norm: Dict[str, int] = {}
    for k, v in counts_raw.items():
        key = str(k or "UNASSIGNED").strip() or "UNASSIGNED"
        counts_norm[key.upper()] = counts_norm.get(key.upper(), 0) + int(v)

    unassigned = int(counts_norm.get("UNASSIGNED", 0))
    rows: List[Dict[str, Any]] = []
    under: List[Dict[str, Any]] = []
    for p in posts:
        code = str(p.get("code") or "").strip().upper()
        if not code:
            continue
        min_staff = max(0, int(p.get("min_staff") or 0))
        assigned = int(counts_norm.get(code, 0))
        gap = max(0, min_staff - assigned)
        status = "ok" if gap == 0 else ("critical" if assigned == 0 and min_staff > 0 else "under")
        row = {
            "code": code,
            "name": p.get("name") or code,
            "min_staff": min_staff,
            "assigned": assigned,
            "gap": gap,
            "status": status,
            "active": bool(p.get("active", 1)),
            "notes": (p.get("notes") or "")[:120],
        }
        rows.append(row)
        if gap > 0:
            under.append(row)

    # Posts may be empty — still surface unassigned roster pressure
    ok = len(under) == 0
    if not posts:
        message = (
            f"No station posts configured · {unassigned} officer(s) unassigned. Add posts under Deploy → Stations."
        )
        level = "info"
    elif under:
        codes = ", ".join(f"{u['code']} (−{u['gap']})" for u in under[:6])
        message = f"{len(under)} station(s) under min staff: {codes}"
        level = "critical" if any(u["status"] == "critical" for u in under) else "warning"
    else:
        message = f"{len(rows)} station(s) at or above min staff"
        level = "ok"

    return {
        "success": True,
        "ok": ok,
        "level": level,
        "message": message,
        "posts": rows,
        "understaffed": under,
        "understaffed_count": len(under),
        "unassigned": unassigned,
        "configured_posts": len(posts),
    }
