"""Department shift and staffing configuration from department_settings."""

from __future__ import annotations

import json
import re
from typing import Dict, List, Optional, Set, Tuple

from config import (
    DEFAULT_ANNUAL_HOURS,
    OFFICER_UNASSIGNED_LABEL,
    SHIFT_TIMES,
)

DEFAULT_SHIFT_LENGTH_HOURS = 11.0
DEFAULT_SHIFT_COUNT = len(SHIFT_TIMES)
DEFAULT_TARGET_OFFICER_COUNT = 16
DEFAULT_SHIFT_STARTS = [start for start, _ in SHIFT_TIMES.values()]
MIN_SHIFT_COUNT = 1
MAX_SHIFT_COUNT = 6
MIN_SHIFT_LENGTH = 4.0
MAX_SHIFT_LENGTH = 16.0
MIN_TARGET_OFFICERS = 1
MAX_TARGET_OFFICERS = 200
MIN_ANNUAL_HOURS = 1000.0
MAX_ANNUAL_HOURS = 3000.0


def _get_setting(key: str, default: str = "") -> str:
    from logic.operations import get_department_setting

    try:
        return get_department_setting(key, default)
    except Exception:
        return default


def _parse_time_minutes(value: str) -> int:
    parts = value.strip().split(":")
    return int(parts[0]) * 60 + int(parts[1])


def _format_minutes(total: int) -> str:
    total = total % (24 * 60)
    return f"{total // 60:02d}:{total % 60:02d}"


def shift_end_from_length(start: str, hours: float) -> str:
    return _format_minutes(_parse_time_minutes(start) + int(hours * 60))


def parse_shift_starts_text(text: str) -> List[str]:
    raw = (text or "").strip()
    if not raw:
        return []
    return [part.strip() for part in re.split(r"[,;\s]+", raw) if part.strip()]


def build_shift_times(
    shift_count: int,
    shift_length_hours: float,
    shift_starts: Optional[List[str]] = None,
) -> Dict[int, Tuple[str, str]]:
    starts = list(shift_starts or DEFAULT_SHIFT_STARTS)
    if len(starts) < shift_count:
        spacing = max(1, (24 * 60) // max(shift_count, 1))
        base = _parse_time_minutes(starts[-1]) if starts else 6 * 60
        while len(starts) < shift_count:
            base = (base + spacing) % (24 * 60)
            starts.append(_format_minutes(base))
    times: Dict[int, Tuple[str, str]] = {}
    for idx, start in enumerate(starts[:shift_count], start=1):
        times[idx] = (start, shift_end_from_length(start, shift_length_hours))
    return times


def get_active_shift_length_hours() -> float:
    raw = _get_setting("shift_length_hours", str(DEFAULT_SHIFT_LENGTH_HOURS))
    try:
        hours = float(raw)
        return max(MIN_SHIFT_LENGTH, min(hours, MAX_SHIFT_LENGTH))
    except ValueError:
        return DEFAULT_SHIFT_LENGTH_HOURS


def get_active_annual_hours_target() -> float:
    raw = _get_setting("department_annual_hours_target", str(DEFAULT_ANNUAL_HOURS))
    try:
        hours = float(raw)
        return max(MIN_ANNUAL_HOURS, min(hours, MAX_ANNUAL_HOURS))
    except ValueError:
        return DEFAULT_ANNUAL_HOURS


def get_active_shift_count() -> int:
    raw = _get_setting("shift_count", str(DEFAULT_SHIFT_COUNT))
    try:
        count = int(raw)
        return max(MIN_SHIFT_COUNT, min(count, MAX_SHIFT_COUNT))
    except ValueError:
        return DEFAULT_SHIFT_COUNT


def get_target_officer_count() -> int:
    raw = _get_setting("target_officer_count", str(DEFAULT_TARGET_OFFICER_COUNT))
    try:
        count = int(raw)
        return max(MIN_TARGET_OFFICERS, min(count, MAX_TARGET_OFFICERS))
    except ValueError:
        return DEFAULT_TARGET_OFFICER_COUNT


def get_active_shift_starts() -> List[str]:
    custom = parse_shift_starts_text(_get_setting("department_shift_starts", ""))
    if custom:
        return custom
    count = get_active_shift_count()
    return DEFAULT_SHIFT_STARTS[:count]


def get_active_shift_times() -> Dict[int, Tuple[str, str]]:
    raw = _get_setting("department_shift_times", "").strip()
    if raw:
        try:
            payload = json.loads(raw)
            if isinstance(payload, list) and payload:
                times: Dict[int, Tuple[str, str]] = {}
                for idx, item in enumerate(payload, start=1):
                    if isinstance(item, (list, tuple)) and len(item) == 2:
                        times[idx] = (str(item[0]), str(item[1]))
                    elif isinstance(item, dict) and item.get("start") and item.get("end"):
                        times[idx] = (str(item["start"]), str(item["end"]))
                if times:
                    return times
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
    return build_shift_times(
        get_active_shift_count(),
        get_active_shift_length_hours(),
        get_active_shift_starts(),
    )


def get_active_shift_time_values() -> Set[Tuple[str, str]]:
    return set(get_active_shift_times().values())


def get_active_shift_starts_list() -> List[str]:
    return [start for start, _ in get_active_shift_times().values()]


def _shift_start_sort_key(shift_start: str) -> int:
    try:
        hour, minute = shift_start.split(":")
        return int(hour) * 60 + int(minute)
    except ValueError:
        return 0


def get_active_bump_rules_by_start() -> Dict[str, Tuple[str, ...]]:
    """Clock-adjacent shift start times may cover each other (not shift slot numbers)."""
    starts = sorted(get_active_shift_starts_list(), key=_shift_start_sort_key)
    rules: Dict[str, Tuple[str, ...]] = {}
    for idx, start in enumerate(starts):
        neighbors: List[str] = []
        if idx > 0:
            neighbors.append(starts[idx - 1])
        if idx < len(starts) - 1:
            neighbors.append(starts[idx + 1])
        rules[start] = tuple(neighbors)
    return rules


def normalize_shift_start_to_active(shift_start: str) -> str:
    """Map a shift start to the closest active department band (for bump/coverage after staffing edits)."""
    if not shift_start:
        return ""
    active = get_active_shift_starts_list()
    if not active:
        return shift_start
    if shift_start in active:
        return shift_start
    target = _shift_start_sort_key(shift_start)
    return min(active, key=lambda band: abs(_shift_start_sort_key(band) - target))


def allowed_bump_sources_for_shift(covered_shift_start: str) -> Tuple[str, ...]:
    normalized = normalize_shift_start_to_active(covered_shift_start)
    return get_active_bump_rules_by_start().get(normalized, ())


def can_officer_cover_shift(replacement_shift_start: str, covered_shift_start: str) -> bool:
    if not replacement_shift_start or not covered_shift_start:
        return False
    replacement = normalize_shift_start_to_active(replacement_shift_start)
    covered = normalize_shift_start_to_active(covered_shift_start)
    return replacement in allowed_bump_sources_for_shift(covered)


def get_active_bump_rules() -> Dict[int, Tuple[int, ...]]:
    """Legacy shift-number view — derived from clock-adjacent start-time rules."""
    shift_times = get_active_shift_times()
    by_start = get_active_bump_rules_by_start()
    rules: Dict[int, Tuple[int, ...]] = {}
    for shift_num, (start, _) in shift_times.items():
        allowed_starts = by_start.get(start, ())
        allowed_nums = tuple(num for num, (s, _) in shift_times.items() if s in allowed_starts)
        rules[shift_num] = allowed_nums
    return rules


def get_active_night_shift_starts() -> Set[str]:
    starts: Set[str] = set()
    for start, _ in get_active_shift_times().values():
        try:
            hour = int(start.split(":")[0])
        except ValueError:
            continue
        if hour >= 15 or hour < 6:
            starts.add(start)
    return starts


def get_officer_shift_options() -> List[str]:
    return [OFFICER_UNASSIGNED_LABEL] + [f"{start} - {end}" for start, end in get_active_shift_times().values()]


def get_staffing_config() -> Dict:
    times = get_active_shift_times()
    from logic import get_officers_by_seniority

    active_officers = [o for o in get_officers_by_seniority() if o.get("active") == 1]
    return {
        "shift_length_hours": get_active_shift_length_hours(),
        "annual_hours_target": get_active_annual_hours_target(),
        "shift_count": get_active_shift_count(),
        "target_officer_count": get_target_officer_count(),
        "shift_starts": get_active_shift_starts(),
        "shift_times": [{"start": s, "end": e} for s, e in times.values()],
        "active_officer_count": len(active_officers),
        "bump_rules": {k: list(v) for k, v in get_active_bump_rules().items()},
        "bump_rules_by_start": {k: list(v) for k, v in get_active_bump_rules_by_start().items()},
    }


def save_staffing_settings(
    *,
    shift_length_hours: float,
    annual_hours_target: float,
    shift_count: int,
    target_officer_count: int,
    shift_starts_text: str = "",
    user_id: Optional[int] = None,
) -> Dict:
    from validators import validate_staffing_settings

    validation = validate_staffing_settings(
        shift_length_hours=shift_length_hours,
        annual_hours_target=annual_hours_target,
        shift_count=shift_count,
        target_officer_count=target_officer_count,
        shift_starts_text=shift_starts_text,
    )
    if not validation.ok:
        return {"success": False, "message": validation.message}

    from logic.operations import set_department_setting

    starts = parse_shift_starts_text(shift_starts_text) or DEFAULT_SHIFT_STARTS[:shift_count]
    shift_times = build_shift_times(shift_count, shift_length_hours, starts)
    shift_json = json.dumps([[s, e] for s, e in shift_times.values()])

    updates = (
        ("shift_length_hours", str(shift_length_hours)),
        ("department_annual_hours_target", str(annual_hours_target)),
        ("shift_count", str(shift_count)),
        ("target_officer_count", str(target_officer_count)),
        ("department_shift_starts", ", ".join(starts[:shift_count])),
        ("department_shift_times", shift_json),
    )
    for key, value in updates:
        result = set_department_setting(key, value, user_id=user_id)
        if not result.get("success"):
            return result

    config = get_staffing_config()
    bands = ", ".join(f"{b['start']}–{b['end']}" for b in config["shift_times"])
    return {
        "success": True,
        "message": (
            f"Staffing saved: {config['shift_count']} shifts × {config['shift_length_hours']:.1f}h, "
            f"{config['annual_hours_target']:.0f}h/year target, {config['target_officer_count']} officer target · {bands}"
        ),
        "config": config,
    }
