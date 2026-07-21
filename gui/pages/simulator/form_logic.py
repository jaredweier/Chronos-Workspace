"""Pure form / metrics helpers extracted from simulator page.py."""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def parse_shift_starts(raw: Optional[str]) -> List[str]:
    """Comma/semicolon-separated HH:MM starts → cleaned list."""
    text = (raw or "").strip()
    if not text:
        return []
    parts = []
    for chunk in text.replace(";", ",").split(","):
        s = chunk.strip()
        if s:
            parts.append(s)
    return parts


def human_metrics_lines(metrics: Optional[dict]) -> List[str]:
    """User-facing metric lines for plan summary panels."""
    lines: List[str] = []
    m = metrics or {}
    for label, key in (
        ("Coverage Percent", "coverage_percent"),
        ("Coverage Gaps", "gap_events"),
        ("Constraints Met", "hard_constraints_ok"),
        ("24/7 Shortfalls", "coverage_247_failures"),
        ("Window Shortfalls", "extra_window_failures"),
        ("Rest Shortfalls", "rest_failures"),
        ("Consecutive Work Shortfalls", "consecutive_work_failures"),
        ("Avg Annual Hours", "avg_annual_hours"),
        ("FTE Required", "fte_required"),
        ("FTE Basis", "fte_basis"),
        ("Officers Used", "min_officers_required"),
        ("Nearby Start Bumps", "nearby_start_hops"),
        ("Off-Day Coverage On", "allow_offday_coverage"),
        ("Off-Day Assignments", "offday_coverage_assignments"),
    ):
        if key in m and m[key] is not None:
            lines.append(f"{label}: {m[key]}")
    return lines


def safe_float(value: Any, default: float = 0.0) -> float:
    if value is None or value == "":
        return float(default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def safe_int(value: Any, default: int = 0) -> int:
    if value is None or value == "":
        return int(default)
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return int(default)


def first_present(*values: Any, default: Any = None) -> Any:
    """First value that is not None (empty string allowed)."""
    for v in values:
        if v is not None:
            return v
    return default


def form_snapshot_keys() -> tuple[str, ...]:
    """Stable keys used by form undo / persist / share payloads."""
    return (
        "use_rotation",
        "rotation",
        "use_officers",
        "officers",
        "officers_max",
        "use_length",
        "length",
        "use_annual",
        "annual",
        "annual_var",
        "use_starts",
        "starts",
        "use_min_ps",
        "min_ps",
        "use_247",
        "cov247",
        "use_style",
        "rot_style",
        "variations",
        "use_windows",
        "windows",
        "use_nearby",
        "nearby_hops",
        "allow_offday",
        "use_certs",
        "certs",
        "use_fatigue",
        "min_rest",
        "max_consec",
        "use_flsa",
        "flsa_days",
        "search_depth",
        "use_rot_model",
        "rot_model_kind",
    )


def constraint_priority_labels() -> Dict[str, str]:
    return {
        "coverage_247": "24/7 coverage",
        "windows": "Extra windows",
        "gaps": "Min per shift band",
        "flsa": "FLSA OT avoid",
        "annual": "Annual hours (year-average fairness)",
        "headcount": "Prefer fewer officers",
    }
