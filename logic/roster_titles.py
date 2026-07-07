"""Assignable roster titles — built-in set plus supervisor-defined custom titles."""

import json
import re
from typing import Dict, List, Optional

from config import OFFICER_TITLE_ALIASES, OFFICER_TITLE_OPTIONS
from database import get_connection
from logic.operations import get_department_setting, set_department_setting
from logic.users import log_audit_action

CUSTOM_OFFICER_TITLES_KEY = "custom_officer_titles"
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
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT DISTINCT job_title FROM officers
            WHERE job_title IS NOT NULL AND TRIM(job_title) != ''
            ORDER BY job_title
            """
        )
        rows = [row["job_title"] for row in cursor.fetchall()]
        conn.close()
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
