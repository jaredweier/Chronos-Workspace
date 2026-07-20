"""Assignable roster titles — built-in set plus supervisor-defined custom titles."""

import json
import re
from typing import Dict, List, Optional

from config import OFFICER_TITLE_ALIASES, OFFICER_TITLE_OPTIONS
from database import connection
from logic.operations import get_department_setting, set_department_setting
from logic.users import log_audit_action

CUSTOM_OFFICER_TITLES_KEY = "custom_officer_titles"
TITLE_CALLIN_LIMITS_KEY = "title_callin_limits_json"
_TITLE_MAX_LEN = 48


def get_builtin_officer_titles() -> tuple:
    return OFFICER_TITLE_OPTIONS


def get_custom_officer_titles() -> List[str]:
    try:
        raw = get_department_setting(CUSTOM_OFFICER_TITLES_KEY, "")
    except Exception:
        return []
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [str(t).strip() for t in data if str(t).strip()]


def get_titles_in_use_on_roster() -> List[str]:
    try:
        with connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT DISTINCT job_title FROM officers
                WHERE job_title IS NOT NULL AND TRIM(job_title) != ''
                ORDER BY job_title
                """
            )
            rows = [row["job_title"] for row in cursor.fetchall()]
        return rows
    except Exception:
        return []


def get_officer_title_options(*, include_in_use: bool = True) -> List[str]:
    """Built-in titles, custom titles, and (optionally) legacy titles on the roster."""
    titles: List[str] = list(OFFICER_TITLE_OPTIONS)
    for title in get_custom_officer_titles():
        if title not in titles:
            titles.append(title)
    if include_in_use:
        for title in get_titles_in_use_on_roster():
            normalized = _canonical_title(title)
            if normalized and normalized not in titles:
                titles.append(normalized)
    return titles


def is_assignable_officer_title(title: Optional[str]) -> bool:
    if not title:
        return False
    canonical = _canonical_title(title)
    if not canonical:
        return False
    if canonical in OFFICER_TITLE_OPTIONS:
        return True
    return canonical in get_officer_title_options()


def _canonical_title(title: str) -> str:
    from validators import normalize_officer_job_title

    return normalize_officer_job_title(title) or ""


def _normalize_new_title(title: str) -> Optional[str]:
    text = (title or "").strip()
    if not text:
        return None
    text = re.sub(r"\s+", " ", text)
    if len(text) < 2 or len(text) > _TITLE_MAX_LEN:
        return None
    mapped = OFFICER_TITLE_ALIASES.get(text.lower())
    if mapped:
        return mapped
    if text.lower() in {t.lower() for t in OFFICER_TITLE_OPTIONS}:
        for builtin in OFFICER_TITLE_OPTIONS:
            if builtin.lower() == text.lower():
                return builtin
    return text.title() if text.islower() or text.isupper() else text


def add_custom_officer_title(title: str, user_id: Optional[int] = None) -> Dict:
    """Add a supervisor-defined title (hourly/manual pay unless configured on Payroll tab)."""
    clean = _normalize_new_title(title)
    if not clean:
        return {
            "success": False,
            "message": f"Title must be 2–{_TITLE_MAX_LEN} characters",
        }
    if clean in OFFICER_TITLE_OPTIONS:
        return {"success": False, "message": f"'{clean}' is already a standard title"}
    custom = get_custom_officer_titles()
    if clean in custom:
        return {"success": False, "message": f"Title '{clean}' already exists"}
    custom.append(clean)
    result = set_department_setting(
        CUSTOM_OFFICER_TITLES_KEY,
        json.dumps(custom),
        user_id=user_id,
    )
    if not result.get("success"):
        return result
    log_audit_action("roster.add_title", "officers", None, user_id, clean)
    return {
        "success": True,
        "message": f"Title '{clean}' added",
        "title": clean,
        "titles": get_officer_title_options(),
    }


def get_title_callin_limits() -> Dict[str, Dict]:
    """Per-title defaults: {title: {max_turn_downs_year, max_ordered_in_year}} (null = unlimited)."""
    try:
        raw = get_department_setting(TITLE_CALLIN_LIMITS_KEY, "") or ""
    except Exception:
        return {}
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    out: Dict[str, Dict] = {}
    for title, entry in data.items():
        if not isinstance(entry, dict):
            continue
        out[str(title)] = {
            "max_turn_downs_year": _optional_nonneg_int(entry.get("max_turn_downs_year")),
            "max_ordered_in_year": _optional_nonneg_int(entry.get("max_ordered_in_year")),
        }
    return out


def _optional_nonneg_int(value) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    if n < 0:
        return None
    return n


def save_title_callin_limits(limits: Dict, *, user_id: Optional[int] = None) -> Dict:
    """Save title-level max turn-downs / ordered-in per year."""
    cleaned = {}
    for title, entry in (limits or {}).items():
        t = str(title or "").strip()
        if not t:
            continue
        if not isinstance(entry, dict):
            continue
        cleaned[t] = {
            "max_turn_downs_year": _optional_nonneg_int(entry.get("max_turn_downs_year")),
            "max_ordered_in_year": _optional_nonneg_int(entry.get("max_ordered_in_year")),
        }
    result = set_department_setting(TITLE_CALLIN_LIMITS_KEY, json.dumps(cleaned), user_id=user_id)
    if not result.get("success"):
        return result
    log_audit_action("roster.title_callin_limits", "department_settings", None, user_id, f"titles={len(cleaned)}")
    return {"success": True, "message": f"Saved call-in limits for {len(cleaned)} title(s)", "limits": cleaned}


def set_title_callin_limit(
    title: str,
    *,
    max_turn_downs_year: Optional[int] = None,
    max_ordered_in_year: Optional[int] = None,
    user_id: Optional[int] = None,
) -> Dict:
    limits = get_title_callin_limits()
    key = _canonical_title(title) or (title or "").strip()
    if not key:
        return {"success": False, "message": "Title required"}
    limits[key] = {
        "max_turn_downs_year": _optional_nonneg_int(max_turn_downs_year),
        "max_ordered_in_year": _optional_nonneg_int(max_ordered_in_year),
    }
    return save_title_callin_limits(limits, user_id=user_id)


def resolve_officer_callin_limits(officer: Dict) -> Dict:
    """
    Effective yearly caps for an officer.
    Officer field wins when set; else title default; else unlimited (None).
    """
    title_limits = get_title_callin_limits()
    title = _canonical_title(officer.get("job_title") or "") or (officer.get("job_title") or "")
    t_entry = title_limits.get(title) or title_limits.get(officer.get("job_title") or "") or {}

    def pick(officer_key: str, title_key: str) -> Optional[int]:
        raw = officer.get(officer_key)
        if raw is not None and raw != "":
            return _optional_nonneg_int(raw)
        return _optional_nonneg_int(t_entry.get(title_key))

    return {
        "max_turn_downs_year": pick("max_turn_downs_year", "max_turn_downs_year"),
        "max_ordered_in_year": pick("max_ordered_in_year", "max_ordered_in_year"),
        "source_title": title or None,
    }
