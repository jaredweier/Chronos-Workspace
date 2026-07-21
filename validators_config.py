"""Department settings, bidding eligibility, and certification validators."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Optional

from config import (
    DATE_DISPLAY_FORMAT,
    DATE_INPUT_HINT,
    DATE_STORAGE_FORMAT,
)
from validators import ValidationResult, format_date, normalize_optional_text, parse_date


def validate_staffing_settings(
    *,
    shift_length_hours: float,
    annual_hours_target: float,
    shift_count: int,
    target_officer_count: int,
    shift_starts_text: str = "",
) -> ValidationResult:
    from logic.staffing_config import (
        MAX_ANNUAL_HOURS,
        MAX_SHIFT_COUNT,
        MAX_SHIFT_LENGTH,
        MAX_TARGET_OFFICERS,
        MIN_ANNUAL_HOURS,
        MIN_SHIFT_COUNT,
        MIN_SHIFT_LENGTH,
        MIN_TARGET_OFFICERS,
        parse_shift_starts_text,
    )

    try:
        length = float(shift_length_hours)
    except (TypeError, ValueError):
        return ValidationResult.fail("Shift length must be a number")
    if length < MIN_SHIFT_LENGTH or length > MAX_SHIFT_LENGTH:
        return ValidationResult.fail(f"Shift length must be {MIN_SHIFT_LENGTH}–{MAX_SHIFT_LENGTH} hours")
    # Half-hour steps only (10.5, 11.0, 12.5, …)
    half_steps = round(length * 2)
    if abs(length * 2 - half_steps) > 1e-6:
        return ValidationResult.fail("Shift length must be in 0.5 hour steps (e.g. 10.5, 11, 12.5)")

    try:
        annual = float(annual_hours_target)
    except (TypeError, ValueError):
        return ValidationResult.fail("Annual hours target must be a number")
    if annual < MIN_ANNUAL_HOURS or annual > MAX_ANNUAL_HOURS:
        return ValidationResult.fail(f"Annual hours target must be {MIN_ANNUAL_HOURS:.0f}–{MAX_ANNUAL_HOURS:.0f}")

    try:
        shifts = int(shift_count)
    except (TypeError, ValueError):
        return ValidationResult.fail("Number of shifts must be a whole number")
    if shifts < MIN_SHIFT_COUNT or shifts > MAX_SHIFT_COUNT:
        return ValidationResult.fail(f"Number of shifts must be {MIN_SHIFT_COUNT}–{MAX_SHIFT_COUNT}")

    try:
        officers = int(target_officer_count)
    except (TypeError, ValueError):
        return ValidationResult.fail("Target officer count must be a whole number")
    if officers < MIN_TARGET_OFFICERS or officers > MAX_TARGET_OFFICERS:
        return ValidationResult.fail(f"Target officer count must be {MIN_TARGET_OFFICERS}–{MAX_TARGET_OFFICERS}")

    if shift_starts_text.strip():
        starts = parse_shift_starts_text(shift_starts_text)
        if not starts:
            return ValidationResult.fail("Shift start times must be HH:MM values (comma-separated)")
        for start in starts:
            if not re.match(r"^\d{1,2}:\d{2}$", start):
                return ValidationResult.fail(f"Invalid shift start time: {start}")

    return ValidationResult.pass_()


def validate_rotation_settings(
    *,
    cycle_length: int,
    preset: str,
    base_date_text: str = "",
    squad_a_days_text: str = "",
) -> ValidationResult:
    from config import ROTATION_PRESETS
    from logic.rotation_config import MAX_CYCLE_LENGTH, MIN_CYCLE_LENGTH, parse_squad_a_days_text

    try:
        days = int(cycle_length)
    except (TypeError, ValueError):
        return ValidationResult.fail("Rotation cycle length must be a number")
    if days < MIN_CYCLE_LENGTH or days > MAX_CYCLE_LENGTH:
        return ValidationResult.fail(f"Rotation cycle length must be {MIN_CYCLE_LENGTH}–{MAX_CYCLE_LENGTH} days")

    preset = normalize_optional_text(preset)
    if not preset or preset not in ROTATION_PRESETS:
        allowed = ", ".join(sorted(ROTATION_PRESETS.keys()))
        return ValidationResult.fail(f"Unknown rotation preset (choose: {allowed})")

    if base_date_text.strip():
        try:
            parse_date(base_date_text.strip())
        except ValueError:
            return ValidationResult.fail(f"Rotation base date must use {DATE_INPUT_HINT}")

    if squad_a_days_text.strip():
        squad_days = parse_squad_a_days_text(squad_a_days_text.strip(), days)
        if not squad_days:
            return ValidationResult.fail(f"Squad A days must be cycle days 1–{days} (comma-separated or JSON list)")

    return ValidationResult.pass_()


def parse_bids_due_datetime(value: Optional[str]) -> Optional[datetime]:
    """Parse supervisor free-text bid deadlines (ISO, display date, date+time)."""
    from datetime import datetime, time

    text = (value or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "").replace("T", " ")
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        DATE_STORAGE_FORMAT + " %H:%M:%S",
        DATE_STORAGE_FORMAT + " %H:%M",
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%Y %H:%M",
        "%m/%d/%y %H:%M:%S",
        "%m/%d/%y %H:%M",
        "%m-%d-%Y %H:%M:%S",
        "%m-%d-%Y %H:%M",
        "%m-%d-%y %H:%M:%S",
        "%m-%d-%y %H:%M",
        DATE_DISPLAY_FORMAT + " %H:%M",
        DATE_DISPLAY_FORMAT + " %H:%M:%S",
        "%d-%m-%Y %H:%M:%S",
        "%d-%m-%Y %H:%M",
        "%d.%m.%Y %H:%M:%S",
        "%d.%m.%Y %H:%M",
    ):
        try:
            return datetime.strptime(normalized, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        pass
    date_part, _, time_part = text.partition(" ")
    try:
        day = parse_date(date_part)
    except ValueError:
        return None
    if time_part:
        for fmt in ("%H:%M:%S", "%H:%M"):
            try:
                parsed_time = datetime.strptime(time_part, fmt).time()
                return datetime.combine(day, parsed_time)
            except ValueError:
                continue
        return None
    return datetime.combine(day, time(23, 59, 59))


def validate_shift_bid_eligibility(officer_id: int, shift_date: str) -> ValidationResult:
    """Officer must be active and not unavailable on the bid date."""
    from logic.officers import get_officer_by_id
    from logic.operations import is_officer_unavailable_on_date

    officer = get_officer_by_id(officer_id)
    if not officer or officer.get("active") != 1:
        return ValidationResult.fail("Officer not found or inactive")
    try:
        target = parse_date(shift_date)
    except ValueError:
        return ValidationResult.fail(f"Shift date must use {DATE_INPUT_HINT}")
    if is_officer_unavailable_on_date(officer_id, target):
        return ValidationResult.fail("Officer is unavailable (blackout) on that date")
    return ValidationResult.pass_()


def can_officer_work_day_band(
    officer_id: int,
    shift_date: str,
    shift_start: str,
    *,
    as_of: Optional[date] = None,
    check_fatigue: bool = True,
    check_consecutive: bool = True,
) -> ValidationResult:
    """Central gate for shift-band eligibility (blackout, certs, fatigue, consecutive days)."""
    from logic.labor_compliance import (
        compute_fatigue_score,
        get_fatigue_score_threshold,
        would_exceed_consecutive_work_limit,
    )

    base = validate_shift_bid_eligibility(officer_id, shift_date)
    if not base.ok:
        return base

    cert_check = validate_officer_certifications(officer_id, shift_start, as_of=as_of)
    if not cert_check.ok:
        return cert_check

    try:
        target = parse_date(shift_date)
    except ValueError:
        return ValidationResult.fail(f"Shift date must use {DATE_INPUT_HINT}")

    if check_consecutive and would_exceed_consecutive_work_limit(officer_id, target, adding_work_day=True):
        from logic.labor_compliance import get_max_consecutive_work_days

        return ValidationResult.fail(
            f"Would exceed {get_max_consecutive_work_days()}-day consecutive work limit on {format_date(target)}"
        )

    if check_fatigue:
        fatigue = compute_fatigue_score(officer_id, as_of=as_of or target)
        threshold = get_fatigue_score_threshold()
        if fatigue.get("severity") and fatigue.get("score", 0) >= threshold:
            return ValidationResult.fail(fatigue.get("message") or "Fatigue score above department threshold")

    return ValidationResult.pass_()


def validate_officer_certifications(
    officer_id: int,
    shift_start: str,
    *,
    as_of: Optional[date] = None,
) -> ValidationResult:
    """Required certifications for a shift band must be current."""
    from database import connection

    check_date = as_of or date.today()
    with connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT t.code, t.name
            FROM shift_cert_requirements r
            JOIN certification_types t ON r.cert_type_id = t.id
            WHERE r.shift_start = ? AND t.active = 1
            """,
            (shift_start,),
        )
        required = cursor.fetchall()
        if not required:
            return ValidationResult.pass_()

        cursor.execute(
            """
            SELECT t.code, c.expires_date
            FROM officer_certifications c
            JOIN certification_types t ON c.cert_type_id = t.id
            WHERE c.officer_id = ? AND t.active = 1
            """,
            (officer_id,),
        )
        held = {r["code"]: r["expires_date"] for r in cursor.fetchall()}

    missing = []
    expired = []
    for req in required:
        code = req["code"]
        if code not in held:
            missing.append(req["name"])
            continue
        exp = held[code]
        if exp:
            try:
                if parse_date(exp) < check_date:
                    expired.append(req["name"])
            except ValueError:
                pass
    if missing:
        return ValidationResult.fail(f"Missing certification(s): {', '.join(missing)}")
    if expired:
        return ValidationResult.fail(f"Expired certification(s): {', '.join(expired)}")
    return ValidationResult.pass_()
