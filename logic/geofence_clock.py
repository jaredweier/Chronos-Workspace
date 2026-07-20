"""Geofenced clock-in foundation (NEOGOV-style).

Config via department_settings:
  geofence_enabled = 0|1
  geofence_lat, geofence_lon, geofence_radius_m
Punches stored for later timekeeping productization.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Dict, List, Optional

from database import connection


def ensure_geofence_tables() -> None:
    with connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS geofence_punches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                officer_id INTEGER NOT NULL,
                punch_type TEXT NOT NULL,
                lat REAL,
                lon REAL,
                accuracy_m REAL,
                within_fence INTEGER,
                distance_m REAL,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (officer_id) REFERENCES officers(id)
            )
            """
        )
        conn.commit()


def get_geofence_config() -> Dict[str, Any]:
    from logic.operations import get_department_setting

    def _f(key: str, default: str = "") -> str:
        return (get_department_setting(key, default) or default).strip()

    enabled = _f("geofence_enabled", "0").lower() in ("1", "true", "yes", "on")
    try:
        lat = float(_f("geofence_lat", "0") or 0)
        lon = float(_f("geofence_lon", "0") or 0)
        radius = float(_f("geofence_radius_m", "200") or 200)
    except (TypeError, ValueError):
        lat = lon = 0.0
        radius = 200.0
    return {
        "enabled": enabled,
        "lat": lat,
        "lon": lon,
        "radius_m": radius,
        "configured": enabled and (lat != 0 or lon != 0),
    }


def save_geofence_config(
    *,
    enabled: bool,
    lat: float,
    lon: float,
    radius_m: float = 200.0,
) -> Dict[str, Any]:
    from logic.operations import set_department_setting

    set_department_setting("geofence_enabled", "1" if enabled else "0")
    set_department_setting("geofence_lat", str(lat))
    set_department_setting("geofence_lon", str(lon))
    set_department_setting("geofence_radius_m", str(radius_m))
    return {"success": True, "config": get_geofence_config()}


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def record_geofence_punch(
    officer_id: int,
    punch_type: str,
    *,
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    accuracy_m: Optional[float] = None,
    notes: str = "",
) -> Dict[str, Any]:
    ensure_geofence_tables()
    cfg = get_geofence_config()
    ptype = (punch_type or "in").strip().lower()
    if ptype not in ("in", "out", "break_start", "break_end"):
        ptype = "in"
    distance = None
    within = None
    if lat is not None and lon is not None and cfg.get("configured"):
        distance = _haversine_m(float(lat), float(lon), float(cfg["lat"]), float(cfg["lon"]))
        within = 1 if distance <= float(cfg["radius_m"]) else 0
        if cfg.get("enabled") and not within:
            return {
                "success": False,
                "message": f"Outside geofence ({distance:.0f}m > {cfg['radius_m']}m)",
                "distance_m": distance,
                "within_fence": False,
            }
    with connection() as conn:
        cur = conn.execute(
            """
            INSERT INTO geofence_punches
            (officer_id, punch_type, lat, lon, accuracy_m, within_fence, distance_m, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(officer_id),
                ptype,
                lat,
                lon,
                accuracy_m,
                within,
                distance,
                (notes or "")[:200],
            ),
        )
        conn.commit()
        return {
            "success": True,
            "id": int(cur.lastrowid),
            "within_fence": bool(within) if within is not None else None,
            "distance_m": distance,
            "message": "Punch recorded",
        }


def list_geofence_punches(*, officer_id: Optional[int] = None, limit: int = 50) -> List[Dict[str, Any]]:
    ensure_geofence_tables()
    limit = max(1, min(int(limit or 50), 200))
    if officer_id:
        sql = "SELECT * FROM geofence_punches WHERE officer_id = ? ORDER BY id DESC LIMIT ?"
        params: tuple = (int(officer_id), limit)
    else:
        sql = "SELECT * FROM geofence_punches ORDER BY id DESC LIMIT ?"
        params = (limit,)
    with connection() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def _parse_punch_ts(raw: Any) -> Optional[datetime]:
    if raw is None:
        return None
    s = str(raw).strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:26], fmt)
        except ValueError:
            continue
    return None


def pair_in_out_segments(
    punches: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Pair consecutive in→out punches into work segments (hours)."""
    ordered = sorted(punches, key=lambda p: str(p.get("created_at") or ""))
    open_in: Optional[Dict[str, Any]] = None
    segments: List[Dict[str, Any]] = []
    for p in ordered:
        pt = (p.get("punch_type") or "").lower()
        if pt == "in":
            open_in = p
        elif pt == "out" and open_in is not None:
            t0 = _parse_punch_ts(open_in.get("created_at"))
            t1 = _parse_punch_ts(p.get("created_at"))
            hours = 0.0
            if t0 and t1 and t1 > t0:
                hours = (t1 - t0).total_seconds() / 3600.0
            segments.append(
                {
                    "officer_id": open_in.get("officer_id") or p.get("officer_id"),
                    "in_id": open_in.get("id"),
                    "out_id": p.get("id"),
                    "time_in": open_in.get("created_at"),
                    "time_out": p.get("created_at"),
                    "entry_date": (t0.date().isoformat() if t0 else None),
                    "hours": round(hours, 2),
                    "within_fence": open_in.get("within_fence"),
                }
            )
            open_in = None
    return segments


def apply_geofence_punches_to_timecard(
    officer_id: int,
    *,
    user_id: Optional[int] = None,
    limit: int = 40,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Convert paired in/out geofence punches into timecard entries.

    Uses pay code Regular by default. Skips zero-hour and already-noted segments.
    """
    ensure_geofence_tables()
    punches = list_geofence_punches(officer_id=int(officer_id), limit=limit)
    # Chronological for pairing (list is DESC)
    segments = pair_in_out_segments(list(reversed(punches)))
    created = 0
    skipped = 0
    details: List[str] = []
    if dry_run:
        return {
            "success": True,
            "dry_run": True,
            "segments": segments,
            "count": len(segments),
            "message": f"{len(segments)} segment(s) would be considered",
        }
    try:
        from logic.payroll import save_timecard_entry
    except Exception as exc:
        return {"success": False, "message": f"Timecard API unavailable: {exc}"}

    for seg in segments:
        hrs = float(seg.get("hours") or 0)
        if hrs <= 0.01:
            skipped += 1
            continue
        entry_date = seg.get("entry_date")
        if not entry_date:
            skipped += 1
            continue
        note = f"geofence punch in#{seg.get('in_id')}-out#{seg.get('out_id')}"
        try:
            r = save_timecard_entry(
                int(officer_id),
                entry_date,
                float(hrs),
                notes=note,
                override_approval=True,
            )
            if r.get("success"):
                created += 1
                details.append(f"{entry_date} +{hrs}h")
            else:
                skipped += 1
                details.append(r.get("message") or "skip")
        except Exception as exc:
            skipped += 1
            details.append(str(exc)[:80])
    try:
        from logic.users import log_audit_action

        log_audit_action(
            "geofence.apply_timecard",
            "officer",
            int(officer_id),
            user_id,
            f"created={created} skipped={skipped}",
        )
    except Exception:
        pass
    return {
        "success": True,
        "created": created,
        "skipped": skipped,
        "segments": len(segments),
        "details": details[:12],
        "message": f"Geofence→timecard: created {created}, skipped {skipped}",
    }


def clock_status(officer_id: int) -> Dict[str, Any]:
    """Whether officer is currently punched in (last punch is in)."""
    rows = list_geofence_punches(officer_id=int(officer_id), limit=1)
    if not rows:
        return {"success": True, "clocked_in": False, "last": None}
    last = rows[0]
    return {
        "success": True,
        "clocked_in": (last.get("punch_type") or "").lower() == "in",
        "last": last,
        "config": get_geofence_config(),
    }
