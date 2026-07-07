"""
Rust scheduling core bridge (PyO3 extension: scheduler_core).

Falls back to pure Python when the native module is not built.
Build: python dev.py build-rust  (requires Rust + maturin)
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Optional, Set, Tuple

_RUST = None
_RUST_ERROR: Optional[str] = None

try:
    import scheduler_core as _RUST
except ImportError as exc:
    _RUST_ERROR = str(exc)


def available() -> bool:
    return _RUST is not None


def backend_name() -> str:
    return "rust" if available() else "python"


def load_error() -> Optional[str]:
    return _RUST_ERROR


def _rotation_schedule() -> Dict[str, Any]:
    from logic.rotation_config import get_rust_rotation_schedule

    return get_rust_rotation_schedule()


def get_cycle_day(target_date: date, base_date: date, cycle_length: int) -> int:
    if _RUST:
        return int(
            _RUST.get_cycle_day(
                base_date.isoformat(),
                target_date.isoformat(),
                cycle_length,
            )
        )
    days_diff = (target_date - base_date).days
    if days_diff < 0:
        days_diff += (-(days_diff // cycle_length) + 1) * cycle_length
    return (days_diff % cycle_length) + 1


def get_squad_on_duty(cycle_day: int) -> str:
    from logic.rotation_config import get_squad_on_duty as active_squad_on_duty

    if _RUST:
        return str(_RUST.get_squad_on_duty(cycle_day, _rotation_schedule()))
    return active_squad_on_duty(cycle_day)


def build_schedule_matrix_rust(
    officers: List[Dict],
    bumped_by_date: Dict[str, Set[int]],
    covering_by_date: Dict[str, Set[int]],
    swapped_by_date: Dict[str, Set[int]],
    bumped_status_by_date: Dict[str, Dict[int, str]],
    start_date: date,
    end_date: date,
    base_date: date,
    cycle_length: int,
) -> Optional[Tuple[List[Dict], List[date]]]:
    if not _RUST:
        return None
    payload = _RUST.build_schedule_matrix(
        officers,
        {k: list(v) for k, v in bumped_by_date.items()},
        {k: list(v) for k, v in covering_by_date.items()},
        {k: list(v) for k, v in swapped_by_date.items()},
        bumped_status_by_date,
        start_date.isoformat(),
        end_date.isoformat(),
        base_date.isoformat(),
        cycle_length,
        _rotation_schedule(),
    )
    days: List[date] = []
    for iso in payload["days"]:
        y, m, d = (int(x) for x in iso.split("-"))
        days.append(date(y, m, d))
    officers_by_id = {o["id"]: o for o in officers}
    matrix = []
    for entry in payload["matrix"]:
        off = entry["officer"]
        if isinstance(off, dict):
            officer = off
        else:
            officer = officers_by_id.get(off["id"], off)
        day_status = {}
        for iso, status in entry["days"].items():
            y, m, d = (int(x) for x in iso.split("-"))
            day_status[date(y, m, d)] = status
        matrix.append({"officer": officer, "days": day_status})
    return matrix, days


def compute_coverage_counts_rust(
    officers: List[Dict],
    overrides: List[Tuple[str, int, Optional[int], Optional[str]]],
    start_date: date,
    end_date: date,
    shift_starts: List[str],
    base_date: date,
    cycle_length: int,
) -> Optional[Dict[Tuple[str, str, str], int]]:
    if not _RUST:
        return None
    raw = _RUST.compute_coverage_counts(
        officers,
        overrides,
        start_date.isoformat(),
        end_date.isoformat(),
        shift_starts,
        base_date.isoformat(),
        cycle_length,
    )
    out: Dict[Tuple[str, str, str], int] = {}
    for key, count in raw.items():
        out[(key[0], key[1], key[2])] = int(count)
    return out


def suggest_bump_chain_rust(
    officers: List[Dict],
    overrides_on_date: List[Tuple[int, Optional[int], Optional[str], str]],
    original_officer_id: int,
    request_date: str,
    squad: str,
    shift_start: str,
    bump_rules_by_start: Dict[str, Tuple[str, ...]],
    shift_times: List[Tuple[str, str]],
    schedule_context: Dict[int, Dict[str, str]],
    night_minimum: int,
    min_rest_hours: float,
    base_date: date,
    cycle_length: int,
    max_assignments_before_busy: int = 2,
    max_depth: int = 8,
) -> Optional[Dict[str, Any]]:
    if not _RUST:
        return None
    rules = {start: list(allowed) for start, allowed in bump_rules_by_start.items()}
    context = {
        str(officer_id): {
            "status": ctx.get("status", "off"),
            "shift_start": ctx.get("shift_start", ""),
        }
        for officer_id, ctx in schedule_context.items()
    }
    return dict(
        _RUST.suggest_bump_chain(
            officers,
            overrides_on_date,
            original_officer_id,
            request_date,
            squad,
            shift_start,
            rules,
            shift_times,
            context,
            night_minimum,
            min_rest_hours,
            base_date.isoformat(),
            cycle_length,
            _rotation_schedule(),
            max_assignments_before_busy,
            max_depth,
        )
    )


def simulate_schedule_rust(
    config_dict: Dict[str, Any],
    preset_dict: Dict[str, Any],
    sim_start: date,
) -> Optional[Dict[str, Any]]:
    if not _RUST:
        return None
    return dict(
        _RUST.simulate_schedule(
            config_dict,
            preset_dict,
            sim_start.isoformat(),
        )
    )