"""Persist additional minimum-coverage windows (date/DOW + time range + min officers)."""

from __future__ import annotations

import json
from datetime import date
from typing import Dict, List, Optional

from logic.coverage_timeline import CoverageWindow
from logic.operations import get_department_setting, set_department_setting
from validators import parse_date, storage_date_str

SETTING_KEY = "coverage_windows_json"


def _parse_window_dict(item: Dict) -> Optional[CoverageWindow]:
    try:
        min_off = max(1, int(item.get("min_officers") or item.get("min") or 1))
        start = str(item.get("start_time") or item.get("start") or "").strip()
        end = str(item.get("end_time") or item.get("end") or "").strip()
        if not start or not end:
            return None
        specific = item.get("specific_date") or item.get("date")
        from logic.coverage_timeline import normalize_weekdays

        weekday = normalize_weekdays(item.get("weekday", item.get("weekdays", item.get("dow"))))
        # Store single int when one day (UI/legacy); tuple when multi
        if weekday is not None and len(weekday) == 1:
            weekday = weekday[0]
        specific_date = None
        if specific:
            specific_date = parse_date(str(specific)) if not isinstance(specific, date) else specific
        return CoverageWindow(
            min_officers=min_off,
            start_time=start if len(start) == 5 else f"{int(start.split(':')[0]):02d}:{start.split(':')[1]}",
            end_time=end if len(end) == 5 else f"{int(end.split(':')[0]):02d}:{end.split(':')[1]}",
            specific_date=specific_date,
            weekday=weekday,
            label=str(item.get("label") or ""),
        )
    except (TypeError, ValueError):
        return None


def list_coverage_windows() -> List[Dict]:
    raw = get_department_setting(SETTING_KEY, "") or ""
    if not raw.strip():
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    out = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            continue
        w = _parse_window_dict(item)
        if not w:
            continue
        out.append(
            {
                "id": item.get("id", i + 1),
                "min_officers": w.min_officers,
                "start_time": w.start_time,
                "end_time": w.end_time,
                "specific_date": w.specific_date.isoformat() if w.specific_date else None,
                "weekday": w.weekday,
                "label": w.label,
                "enabled": bool(item.get("enabled", True)),
            }
        )
    return out


def get_active_coverage_windows() -> List[CoverageWindow]:
    windows = []
    for item in list_coverage_windows():
        if not item.get("enabled", True):
            continue
        w = _parse_window_dict(item)
        if w:
            windows.append(w)
    return windows


def save_coverage_windows(windows: List[Dict], *, user_id: Optional[int] = None) -> Dict:
    cleaned = []
    for i, item in enumerate(windows or []):
        if not isinstance(item, dict):
            continue
        w = _parse_window_dict(item)
        if not w:
            continue
        cleaned.append(
            {
                "id": item.get("id") or i + 1,
                "min_officers": w.min_officers,
                "start_time": w.start_time,
                "end_time": w.end_time,
                "specific_date": storage_date_str(w.specific_date.isoformat()) if w.specific_date else None,
                "weekday": w.weekday,
                "label": w.label,
                "enabled": bool(item.get("enabled", True)),
            }
        )
    result = set_department_setting(SETTING_KEY, json.dumps(cleaned), user_id=user_id)
    if not result.get("success"):
        return result
    return {"success": True, "message": f"Saved {len(cleaned)} coverage window(s)", "windows": cleaned}


def add_coverage_window(
    *,
    min_officers: int,
    start_time: str,
    end_time: str,
    specific_date: str = "",
    weekday: Optional[int] = None,
    label: str = "",
    user_id: Optional[int] = None,
) -> Dict:
    windows = list_coverage_windows()
    next_id = max([int(w.get("id") or 0) for w in windows] + [0]) + 1
    windows.append(
        {
            "id": next_id,
            "min_officers": min_officers,
            "start_time": start_time,
            "end_time": end_time,
            "specific_date": specific_date or None,
            "weekday": weekday,
            "label": label,
            "enabled": True,
        }
    )
    return save_coverage_windows(windows, user_id=user_id)


def delete_coverage_window(window_id: int, *, user_id: Optional[int] = None) -> Dict:
    windows = [w for w in list_coverage_windows() if int(w.get("id") or 0) != int(window_id)]
    return save_coverage_windows(windows, user_id=user_id)


def get_coverage_247_minimum() -> int:
    raw = get_department_setting("coverage_247_minimum", "0") or "0"
    try:
        return max(0, int(float(raw)))
    except (TypeError, ValueError):
        return 0


def set_coverage_247_minimum(value: int, *, user_id: Optional[int] = None) -> Dict:
    n = max(0, int(value))
    return set_department_setting("coverage_247_minimum", str(n), user_id=user_id)
