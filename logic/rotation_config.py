"""Active rotation configuration from department_settings."""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Dict, FrozenSet, Optional, Set

from config import ROTATION_BASE_DATE, ROTATION_CYCLE_LENGTH, ROTATION_PRESETS
from validators import format_date, parse_date

DEFAULT_PRESET_NAME = "2-2-3 (Dodgeville 14-day)"
DEFAULT_SQUAD_A_DAYS: FrozenSet[int] = frozenset({1, 2, 5, 6, 7, 10, 11})
MIN_CYCLE_LENGTH = 7
MAX_CYCLE_LENGTH = 28


def _get_setting(key: str, default: str = "") -> str:
    from logic.operations import get_department_setting

    try:
        return get_department_setting(key, default)
    except Exception:
        return default


def get_active_rotation_cycle_length() -> int:
    raw = _get_setting("rotation_cycle_length", str(ROTATION_CYCLE_LENGTH))
    try:
        return max(MIN_CYCLE_LENGTH, min(int(raw), MAX_CYCLE_LENGTH))
    except ValueError:
        return ROTATION_CYCLE_LENGTH


def get_active_rotation_base_date() -> date:
    raw = _get_setting("rotation_base_date", "").strip()
    if raw:
        try:
            return parse_date(raw)
        except ValueError:
            pass
    return ROTATION_BASE_DATE


def get_active_rotation_preset_name() -> str:
    return _get_setting("rotation_preset", DEFAULT_PRESET_NAME) or DEFAULT_PRESET_NAME


def _resolve_preset() -> Dict:
    name = get_active_rotation_preset_name()
    preset = ROTATION_PRESETS.get(name)
    if not preset:
        preset = ROTATION_PRESETS[DEFAULT_PRESET_NAME]
    merged = dict(preset)
    merged["cycle_length"] = get_active_rotation_cycle_length()
    return merged


def get_active_squad_a_days() -> FrozenSet[int]:
    custom = _get_setting("rotation_squad_a_days", "").strip()
    if custom:
        try:
            days = json.loads(custom)
            if isinstance(days, list) and days:
                cycle = get_active_rotation_cycle_length()
                valid = {int(d) for d in days if 1 <= int(d) <= cycle}
                if valid:
                    return frozenset(valid)
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

    preset = _resolve_preset()
    if "squad_a_days" in preset:
        return frozenset(preset["squad_a_days"])
    return DEFAULT_SQUAD_A_DAYS


def is_squad_working(squad: str, cycle_day: int, preset: Optional[Dict] = None) -> bool:
    if squad not in ("A", "B"):
        return False

    active = preset or _resolve_preset()
    cycle_len = active["cycle_length"]
    if cycle_day < 1 or cycle_day > cycle_len:
        return False

    custom_days = _get_setting("rotation_squad_a_days", "").strip()
    if custom_days or "squad_a_days" in active:
        on_a = cycle_day in get_active_squad_a_days()
        return on_a if squad == "A" else not on_a

    if "squad_patterns" in active:
        pattern = active["squad_patterns"].get(squad, active["squad_patterns"].get("A", []))
        if not pattern:
            return False
        idx = (cycle_day - 1) % len(pattern)
        return pattern[idx] == 1

    work_days = active.get("work_days_per_cycle", 7)
    squads = active.get("squads", 2)
    half = work_days // squads if squads else work_days
    if squad == "A":
        return ((cycle_day - 1) % cycle_len) < half
    offset = cycle_len // squads if squads else 0
    return ((cycle_day - 1 + offset) % cycle_len) < half


def get_squad_on_duty(cycle_day: int) -> str:
    return "A" if is_squad_working("A", cycle_day) else "B"


def get_rust_rotation_schedule() -> Dict:
    """Rotation payload passed to scheduler_core for squad-duty math."""
    active = _resolve_preset()
    cycle_length = active["cycle_length"]
    custom_days = _get_setting("rotation_squad_a_days", "").strip()

    if custom_days or "squad_a_days" in active:
        return {
            "mode": "squad_a_days",
            "cycle_length": cycle_length,
            "squad_a_days": sorted(get_active_squad_a_days()),
        }
    if "squad_patterns" in active:
        patterns = active["squad_patterns"]
        return {
            "mode": "squad_patterns",
            "cycle_length": cycle_length,
            "pattern_a": list(patterns.get("A", [])),
            "pattern_b": list(patterns.get("B", [])),
        }
    return {
        "mode": "equal_split",
        "cycle_length": cycle_length,
        "work_days_per_cycle": active.get("work_days_per_cycle", 7),
        "squads": active.get("squads", 2),
    }


def get_preset_cycle_length(preset_name: str) -> int:
    preset = ROTATION_PRESETS.get(preset_name)
    if not preset:
        return ROTATION_CYCLE_LENGTH
    return int(preset.get("cycle_length", ROTATION_CYCLE_LENGTH))


def parse_squad_a_days_text(text: str, cycle_length: int) -> Optional[Set[int]]:
    """Parse comma/space-separated or JSON list of cycle days (1..cycle_length)."""
    raw = (text or "").strip()
    if not raw:
        return None
    values: Set[int] = set()
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            for item in parsed:
                day = int(item)
                if 1 <= day <= cycle_length:
                    values.add(day)
            return values or None
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    for part in re.split(r"[,;\s]+", raw):
        part = part.strip()
        if not part:
            continue
        try:
            day = int(part)
        except ValueError:
            return None
        if 1 <= day <= cycle_length:
            values.add(day)
    return values or None


def save_rotation_settings(
    *,
    cycle_length: int,
    preset: str,
    base_date_text: str = "",
    squad_a_days_text: str = "",
    user_id: Optional[int] = None,
) -> Dict:
    """Validate and persist rotation settings; returns active config snapshot."""
    from validators import validate_rotation_settings

    validation = validate_rotation_settings(
        cycle_length=cycle_length,
        preset=preset,
        base_date_text=base_date_text,
        squad_a_days_text=squad_a_days_text,
    )
    if not validation.ok:
        return {"success": False, "message": validation.message}

    from logic.operations import set_department_setting

    base_value = ""
    if base_date_text.strip():
        base_value = parse_date(base_date_text.strip()).isoformat()

    squad_days = parse_squad_a_days_text(squad_a_days_text, cycle_length)
    squad_value = json.dumps(sorted(squad_days)) if squad_days else ""

    updates = (
        ("rotation_cycle_length", str(cycle_length)),
        ("rotation_preset", preset.strip()),
        ("rotation_base_date", base_value),
        ("rotation_squad_a_days", squad_value),
    )
    for key, value in updates:
        result = set_department_setting(key, value, user_id=user_id)
        if not result.get("success"):
            return result

    config = get_rotation_config()
    return {
        "success": True,
        "message": (
            f"Rotation saved: {config['cycle_length']}-day {config['preset']} "
            f"(base {format_date(parse_date(config['base_date']))})"
        ),
        "config": config,
    }


def get_rotation_config() -> Dict:
    import logic.rust_bridge as rust_bridge_module

    preset = _resolve_preset()
    return {
        "cycle_length": get_active_rotation_cycle_length(),
        "base_date": get_active_rotation_base_date().isoformat(),
        "preset": get_active_rotation_preset_name(),
        "squad_a_days": sorted(get_active_squad_a_days()),
        "rust_backend": rust_bridge_module.available(),
        "rust_schedule_mode": get_rust_rotation_schedule().get("mode"),
        "squads": preset.get("squads", 2),
    }
