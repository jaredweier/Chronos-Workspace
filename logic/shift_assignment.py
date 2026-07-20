"""Per-day shift band assignment — any officer may work any active shift band."""

from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional, Tuple

from logic.staffing_config import get_active_shift_length_hours, get_active_shift_times, shift_end_from_length

WORKING_ASSIGNMENT_STATUSES = frozenset({"working", "swapped", "training"})


def get_shift_band_options() -> List[Tuple[str, str]]:
    return list(get_active_shift_times().values())


def shift_end_for_start(shift_start: str) -> str:
    for start, end in get_shift_band_options():
        if start == shift_start:
            return end
    return shift_end_from_length(shift_start, get_active_shift_length_hours())


def distribute_shift_bands(officers: List[Dict]) -> Dict[int, Tuple[str, str]]:
    """Round-robin assign active shift bands across officers (any officer → any band)."""
    bands = get_shift_band_options()
    if not bands:
        return {o["id"]: (o.get("shift_start") or "", o.get("shift_end") or "") for o in officers}
    return {o["id"]: bands[idx % len(bands)] for idx, o in enumerate(officers)}


def resolve_assignment_shift(
    officer: Dict,
    status: str,
    band_assignments: Dict[int, Tuple[str, str]],
    covered_shift_start: Optional[str] = None,
) -> Tuple[str, str]:
    if status == "covering" and covered_shift_start:
        return covered_shift_start, shift_end_for_start(covered_shift_start)
    if status in WORKING_ASSIGNMENT_STATUSES:
        return band_assignments.get(
            officer["id"],
            (officer.get("shift_start") or "", officer.get("shift_end") or ""),
        )
    return officer.get("shift_start") or "", officer.get("shift_end") or ""


def covered_shift_for_officer_on_date(officer_id: int, target_date: date) -> Optional[str]:
    from database import connection

    with connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT covered_shift_start FROM schedule_overrides
            WHERE override_date = ? AND replacement_officer_id = ?
            LIMIT 1
        """,
            (target_date.isoformat(), officer_id),
        )
        row = cursor.fetchone()
    if row and row["covered_shift_start"]:
        return row["covered_shift_start"]
    return None
