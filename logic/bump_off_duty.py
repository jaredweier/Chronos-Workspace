"""Off-duty officer eligibility and ranking for day-off bump / call-in.

When enabled, bump logic may call in officers who are not scheduled working
that day (OT / call-back). Ranking criteria are multi-select; any combination
of enabled criteria is summed into a soft score.

Settings live in department_settings (JSON + flags).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional, Sequence, Set, Tuple

from logic.operations import get_department_setting, set_department_setting

# Multi-select ranking criteria (ids stable for UI + storage)
CRITERION_SENIORITY = "seniority"  # junior first (higher rank #) or senior first via invert
CRITERION_SENIORITY_SENIOR_FIRST = "seniority_senior_first"
CRITERION_CALL_LIST = "call_list"  # rotating call-in order
CRITERION_DAYS_OFF = "days_off"  # more consecutive days off preferred
CRITERION_MIN_DAYS_OFF = "min_days_off"  # hard filter: must have ≥ N days off
CRITERION_LOW_OT = "low_ot"  # lower period OT preferred
CRITERION_LEAST_RECENT_CALLBACK = "least_recent_callback"  # fair rotation of call-ins
CRITERION_SAME_SQUAD = "same_squad"  # soft prefer same squad (if multi-squad allowed)
CRITERION_HOME_BAND_MATCH = "home_band_match"  # prefer home shift matches covered

ALL_CRITERIA = [
    CRITERION_SENIORITY,
    CRITERION_SENIORITY_SENIOR_FIRST,
    CRITERION_CALL_LIST,
    CRITERION_DAYS_OFF,
    CRITERION_MIN_DAYS_OFF,
    CRITERION_LOW_OT,
    CRITERION_LEAST_RECENT_CALLBACK,
    CRITERION_SAME_SQUAD,
    CRITERION_HOME_BAND_MATCH,
]

CRITERION_LABELS = {
    CRITERION_SENIORITY: "Seniority — junior first (default LE bump)",
    CRITERION_SENIORITY_SENIOR_FIRST: "Seniority — senior first",
    CRITERION_CALL_LIST: "Rotating call list order",
    CRITERION_DAYS_OFF: "More consecutive days off preferred",
    CRITERION_MIN_DAYS_OFF: "Require minimum consecutive days off (hard filter)",
    CRITERION_LOW_OT: "Lower recent OT hours preferred",
    CRITERION_LEAST_RECENT_CALLBACK: "Longest since last call-in / off-duty cover",
    CRITERION_SAME_SQUAD: "Prefer same squad (when other squads allowed)",
    CRITERION_HOME_BAND_MATCH: "Prefer home shift matches covered band",
}

SETTING_POLICY = "bump_off_duty_policy_json"
SETTING_CALL_LIST = "bump_call_list_json"
SETTING_CALL_CURSOR = "bump_call_list_cursor"


@dataclass
class OffDutyBumpPolicy:
    """User-configurable off-duty call-in rules for bumps."""

    allow_off_duty: bool = False
    # Multi-select ranking / filter criteria (order = display; all enabled contribute)
    criteria: List[str] = field(default_factory=lambda: [CRITERION_SENIORITY, CRITERION_CALL_LIST])
    # Hard filter: minimum consecutive days currently off before eligible
    min_days_off_required: int = 0
    # Scope
    same_squad_only: bool = True
    # Band rules for OT call-in
    require_adjacent_band: bool = False  # False = any band OK
    # Prefer on-duty candidates over off-duty when both exist
    prefer_on_duty_first: bool = True
    # Weights when criterion enabled
    w_seniority: float = 12.0
    w_call_list: float = 20.0
    w_days_off: float = 8.0
    w_low_ot: float = 4.0
    w_least_recent: float = 10.0
    w_same_squad: float = 5.0
    w_home_band: float = 6.0
    # Large bonus so on-duty always ranks above off-duty when prefer_on_duty_first
    w_on_duty_bonus: float = 1000.0

    def uses(self, criterion: str) -> bool:
        return criterion in (self.criteria or [])

    def to_dict(self) -> Dict:
        return {
            "allow_off_duty": self.allow_off_duty,
            "criteria": list(self.criteria or []),
            "min_days_off_required": self.min_days_off_required,
            "same_squad_only": self.same_squad_only,
            "require_adjacent_band": self.require_adjacent_band,
            "prefer_on_duty_first": self.prefer_on_duty_first,
            "w_seniority": self.w_seniority,
            "w_call_list": self.w_call_list,
            "w_days_off": self.w_days_off,
            "w_low_ot": self.w_low_ot,
            "w_least_recent": self.w_least_recent,
            "w_same_squad": self.w_same_squad,
            "w_home_band": self.w_home_band,
            "w_on_duty_bonus": self.w_on_duty_bonus,
        }


def load_off_duty_bump_policy() -> OffDutyBumpPolicy:
    raw = get_department_setting(SETTING_POLICY, "") or ""
    if not raw.strip():
        return OffDutyBumpPolicy()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return OffDutyBumpPolicy()
    if not isinstance(data, dict):
        return OffDutyBumpPolicy()
    criteria = data.get("criteria") or []
    if isinstance(criteria, str):
        criteria = [c.strip() for c in criteria.split(",") if c.strip()]
    criteria = [c for c in criteria if c in ALL_CRITERIA]
    return OffDutyBumpPolicy(
        allow_off_duty=bool(data.get("allow_off_duty", False)),
        criteria=criteria or [CRITERION_SENIORITY],
        min_days_off_required=max(0, int(data.get("min_days_off_required") or 0)),
        same_squad_only=bool(data.get("same_squad_only", True)),
        require_adjacent_band=bool(data.get("require_adjacent_band", False)),
        prefer_on_duty_first=bool(data.get("prefer_on_duty_first", True)),
        w_seniority=float(data.get("w_seniority", 12.0)),
        w_call_list=float(data.get("w_call_list", 20.0)),
        w_days_off=float(data.get("w_days_off", 8.0)),
        w_low_ot=float(data.get("w_low_ot", 4.0)),
        w_least_recent=float(data.get("w_least_recent", 10.0)),
        w_same_squad=float(data.get("w_same_squad", 5.0)),
        w_home_band=float(data.get("w_home_band", 6.0)),
        w_on_duty_bonus=float(data.get("w_on_duty_bonus", 1000.0)),
    )


def save_off_duty_bump_policy(policy: OffDutyBumpPolicy | Dict, *, user_id: Optional[int] = None) -> Dict:
    if isinstance(policy, dict):
        p = load_off_duty_bump_policy()
        for k, v in policy.items():
            if hasattr(p, k):
                setattr(p, k, v)
        # criteria cleanup
        crit = policy.get("criteria", p.criteria)
        if isinstance(crit, str):
            crit = [c.strip() for c in crit.split(",") if c.strip()]
        p.criteria = [c for c in (crit or []) if c in ALL_CRITERIA]
        p.allow_off_duty = bool(policy.get("allow_off_duty", p.allow_off_duty))
        p.min_days_off_required = max(0, int(policy.get("min_days_off_required", p.min_days_off_required) or 0))
        p.same_squad_only = bool(policy.get("same_squad_only", p.same_squad_only))
        p.require_adjacent_band = bool(policy.get("require_adjacent_band", p.require_adjacent_band))
        p.prefer_on_duty_first = bool(policy.get("prefer_on_duty_first", p.prefer_on_duty_first))
        policy = p
    result = set_department_setting(SETTING_POLICY, json.dumps(policy.to_dict()), user_id=user_id)
    if not result.get("success"):
        return result
    return {
        "success": True,
        "message": (
            f"Off-duty bump: {'ON' if policy.allow_off_duty else 'OFF'} · "
            f"criteria={', '.join(policy.criteria) or 'none'}"
        ),
        "policy": policy.to_dict(),
    }


# ---- Call list --------------------------------------------------------------


def get_bump_call_list() -> List[Dict]:
    """Ordered rotating call list: [{officer_id, name?, note?}]."""
    raw = get_department_setting(SETTING_CALL_LIST, "") or ""
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
        if isinstance(item, int):
            out.append({"officer_id": item, "order": i})
        elif isinstance(item, dict) and item.get("officer_id") is not None:
            out.append(
                {
                    "officer_id": int(item["officer_id"]),
                    "name": item.get("name") or "",
                    "note": item.get("note") or "",
                    "order": int(item.get("order", i)),
                }
            )
    out.sort(key=lambda x: x.get("order", 0))
    return out


def save_bump_call_list(entries: Sequence, *, user_id: Optional[int] = None) -> Dict:
    """Save list from officer ids, names, or dicts. Resolves names to ids when possible."""
    from logic.officers import get_officers_by_seniority

    officers = [o for o in get_officers_by_seniority() if o.get("active") == 1]
    by_id = {int(o["id"]): o for o in officers}
    by_name = {str(o.get("name") or "").strip().lower(): o for o in officers}

    cleaned = []
    for i, item in enumerate(entries or []):
        oid = None
        name = ""
        note = ""
        if isinstance(item, int):
            oid = item
        elif isinstance(item, str):
            text = item.strip()
            if text.isdigit():
                oid = int(text)
            else:
                o = by_name.get(text.lower())
                if o:
                    oid = int(o["id"])
                    name = o.get("name") or text
                else:
                    continue
        elif isinstance(item, dict):
            if item.get("officer_id") is not None:
                oid = int(item["officer_id"])
            elif item.get("name"):
                o = by_name.get(str(item["name"]).strip().lower())
                if o:
                    oid = int(o["id"])
            name = item.get("name") or ""
            note = item.get("note") or ""
        if oid is None or oid not in by_id:
            continue
        cleaned.append(
            {
                "officer_id": oid,
                "name": name or by_id[oid].get("name") or "",
                "note": note,
                "order": i,
            }
        )
    # de-dupe preserving order
    seen: Set[int] = set()
    unique = []
    for e in cleaned:
        if e["officer_id"] in seen:
            continue
        seen.add(e["officer_id"])
        unique.append(e)
    r = set_department_setting(SETTING_CALL_LIST, json.dumps(unique), user_id=user_id)
    if not r.get("success"):
        return r
    return {"success": True, "message": f"Call list saved ({len(unique)} officers)", "entries": unique}


def parse_call_list_text(text: str) -> List:
    """Parse paste/import text: one officer id or name per line, or comma-separated."""
    import re

    raw = (text or "").strip()
    if not raw:
        return []
    parts = re.split(r"[\n,;]+", raw)
    return [p.strip() for p in parts if p.strip()]


def import_bump_call_list_text(text: str, *, user_id: Optional[int] = None) -> Dict:
    return save_bump_call_list(parse_call_list_text(text), user_id=user_id)


def _extract_text_from_docx_bytes(raw: bytes) -> str:
    """Stdlib-only .docx text extract (zip + word/document.xml)."""
    import re
    import zipfile
    from io import BytesIO
    from xml.etree import ElementTree as ET

    with zipfile.ZipFile(BytesIO(raw)) as zf:
        try:
            xml_bytes = zf.read("word/document.xml")
        except KeyError as exc:
            raise ValueError("Not a valid .docx (missing word/document.xml)") from exc
    # Strip namespaces for simple text walk
    root = ET.fromstring(xml_bytes)
    texts: List[str] = []
    for el in root.iter():
        tag = el.tag.split("}")[-1] if "}" in el.tag else el.tag
        if tag == "t" and el.text:
            texts.append(el.text)
        elif tag == "tab":
            texts.append("\t")
        elif tag in ("br", "cr"):
            texts.append("\n")
        elif tag == "p":
            texts.append("\n")
    joined = "".join(texts)
    # Normalize whitespace but keep newlines
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in joined.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def _extract_text_from_pdf_bytes(raw: bytes) -> str:
    """Optional pypdf; clear error if missing (no crash)."""
    try:
        from io import BytesIO

        from pypdf import PdfReader  # type: ignore
    except ImportError as exc:
        raise ValueError(
            "PDF import requires pypdf (optional): pip install pypdf — or export call list as .txt/.docx"
        ) from exc
    from io import BytesIO

    reader = PdfReader(BytesIO(raw))
    parts: List[str] = []
    # Cap pages to keep light
    for page in reader.pages[:50]:
        try:
            parts.append(page.extract_text() or "")
        except Exception:
            continue
    text = "\n".join(parts).strip()
    if not text:
        raise ValueError("No extractable text in PDF (scanned image PDFs not supported)")
    return text


def extract_text_from_upload(filename: str, raw: bytes) -> str:
    """Extract plain text from call-list upload bytes.

    Supported: .txt .csv .list .docx; .pdf if pypdf installed.
    .doc (legacy Word) rejected with guidance.
    """
    name = (filename or "upload.txt").strip().lower()
    if not raw:
        raise ValueError("Empty file")
    if name.endswith(".doc") and not name.endswith(".docx"):
        raise ValueError("Legacy .doc not supported — save as .docx or paste as text")
    if name.endswith(".docx"):
        return _extract_text_from_docx_bytes(raw)
    if name.endswith(".pdf"):
        return _extract_text_from_pdf_bytes(raw)
    # Plain text family
    for enc in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def import_bump_call_list_file(
    filename: str,
    raw: bytes,
    *,
    user_id: Optional[int] = None,
) -> Dict:
    """Import call list from uploaded file bytes (txt/csv/docx/pdf)."""
    try:
        text = extract_text_from_upload(filename, raw)
    except ValueError as exc:
        return {"success": False, "message": str(exc)}
    # Strip comment tails after # for each line (docx/pdf may include notes)
    cleaned_lines = []
    for line in (text or "").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            cleaned_lines.append(line)
    result = import_bump_call_list_text("\n".join(cleaned_lines), user_id=user_id)
    if result.get("success"):
        result["message"] = f"{result.get('message', 'Imported')} from {filename or 'upload'}"
        result["extracted_preview"] = "\n".join(cleaned_lines[:20])
    return result


def get_call_list_cursor() -> int:
    raw = get_department_setting(SETTING_CALL_CURSOR, "0") or "0"
    try:
        return max(0, int(raw))
    except ValueError:
        return 0


def reset_call_list_cursor(*, user_id: Optional[int] = None) -> Dict:
    """Set rotating call list next-up to the top of the list."""
    set_department_setting(SETTING_CALL_CURSOR, "0", user_id=user_id)
    nxt = get_next_call_list_officer()
    return {
        "success": True,
        "message": "Call list next-up reset to top",
        "cursor": 0,
        "next_officer": nxt,
    }


def get_next_call_list_officer() -> Optional[Dict]:
    """Next call-list officer who is still under yearly turn-down / ordered-in caps."""
    entries = get_bump_call_list()
    if not entries:
        return None
    from datetime import date as _date

    from logic.officers import get_officer_by_id
    from logic.ot_fill import get_officer_ot_fill_year_stats
    from logic.roster_titles import resolve_officer_callin_limits

    year = _date.today().year
    n = len(entries)
    cursor = get_call_list_cursor() % n
    for offset in range(n):
        e = entries[(cursor + offset) % n]
        oid = int(e["officer_id"])
        officer = get_officer_by_id(oid)
        if not officer or officer.get("active") != 1:
            continue
        limits = resolve_officer_callin_limits(officer)
        stats = get_officer_ot_fill_year_stats(oid, year)
        max_oi = limits.get("max_ordered_in_year")
        max_td = limits.get("max_turn_downs_year")
        if max_oi is not None and int(stats.get("ordered_in") or 0) >= max_oi:
            continue
        if max_td is not None and int(stats.get("turned_down") or 0) >= max_td:
            continue
        out = dict(e)
        out["skipped_offsets"] = offset
        return out
    return None


def advance_call_list_cursor(*, user_id: Optional[int] = None) -> int:
    """Rotate cursor after a successful off-duty call-in from the list.

    Prefer ``move_officer_to_end_of_call_list`` (via record_ordered_in) so the
    ordered officer is furthest from next call; cursor advance alone is fallback.
    """
    entries = get_bump_call_list()
    if not entries:
        return 0
    nxt = (get_call_list_cursor() + 1) % len(entries)
    set_department_setting(SETTING_CALL_CURSOR, str(nxt), user_id=user_id)
    return nxt


def record_call_list_order_in(officer_id: int, *, user_id: Optional[int] = None) -> Dict:
    """Move ordered officer to end of call list (furthest from next call)."""
    from logic.ot_fill import move_officer_to_end_of_call_list

    return move_officer_to_end_of_call_list(int(officer_id), user_id=user_id)


def call_list_rank_score(officer_id: int, policy: OffDutyBumpPolicy) -> float:
    """Higher = better (next on rotating list scores highest)."""
    entries = get_bump_call_list()
    if not entries:
        return 0.0
    n = len(entries)
    cursor = get_call_list_cursor() % n
    # position relative to cursor: 0 = next up → max score
    id_to_idx = {e["officer_id"]: i for i, e in enumerate(entries)}
    if officer_id not in id_to_idx:
        return 0.0
    idx = id_to_idx[officer_id]
    # distance forward from cursor
    dist = (idx - cursor) % n
    # closer to next-up → higher score
    return policy.w_call_list * (n - dist) / max(n, 1)


# ---- Days off / last callback -----------------------------------------------


def count_consecutive_days_off(officer_id: int, as_of: date) -> int:
    """How many consecutive days the officer was not working ending the day before as_of."""
    from logic.officers import get_officer_by_id
    from logic.scheduling import officer_base_rotation_working

    officer = get_officer_by_id(officer_id)
    if not officer:
        return 0
    count = 0
    d = as_of - timedelta(days=1)
    # look back up to 28 days
    for _ in range(28):
        if officer_base_rotation_working(officer, d):
            break
        # also treat approved day-off as off (already not on base if override)
        count += 1
        d -= timedelta(days=1)
    return count


def days_since_last_offduty_cover(officer_id: int, as_of: date) -> int:
    """Days since officer last covered someone else's shift (schedule_overrides)."""
    from database import connection

    with connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT MAX(override_date) AS last_d FROM schedule_overrides
            WHERE replacement_officer_id = ?
              AND override_date < ?
            """,
            (officer_id, as_of.isoformat()),
        )
        row = cursor.fetchone()
    if not row or not row["last_d"]:
        return 365  # never called → max fairness
    try:
        from validators import parse_date

        last = parse_date(row["last_d"])
        return max(0, (as_of - last).days)
    except (TypeError, ValueError):
        return 0


def score_off_duty_candidate(
    officer: Dict,
    *,
    covered_shift_start: str,
    request_squad: str,
    coverage_date: date,
    policy: OffDutyBumpPolicy,
    ot_hours: float = 0.0,
) -> Tuple[bool, float, Dict]:
    """
    Return (eligible, score, breakdown).
    Hard filters applied first (min days off, squad, etc.).
    """
    from logic.staffing_config import can_officer_cover_shift, normalize_shift_start_to_active

    breakdown: Dict = {"on_duty": False}
    oid = int(officer["id"])
    home = officer.get("shift_start") or ""
    covered = normalize_shift_start_to_active(covered_shift_start) or covered_shift_start

    if policy.same_squad_only and officer.get("squad") != request_squad:
        return False, 0.0, {"reason": "different_squad"}

    if policy.require_adjacent_band:
        if home and covered and not can_officer_cover_shift(home, covered):
            # also allow exact match
            if normalize_shift_start_to_active(home) != covered:
                return False, 0.0, {"reason": "band_not_allowed"}

    days_off = count_consecutive_days_off(oid, coverage_date)
    breakdown["days_off"] = days_off

    if policy.uses(CRITERION_MIN_DAYS_OFF) or policy.min_days_off_required > 0:
        need = policy.min_days_off_required
        if policy.uses(CRITERION_MIN_DAYS_OFF) and need <= 0:
            need = 1  # criterion on with 0 → at least 1 day off
        if days_off < need:
            return False, 0.0, {"reason": "min_days_off", "days_off": days_off, "need": need}

    score = 0.0
    rank = int(officer.get("seniority_rank") or 0)

    if policy.uses(CRITERION_SENIORITY):
        # junior first: higher rank number better
        score += policy.w_seniority * rank
        breakdown["seniority"] = rank
    if policy.uses(CRITERION_SENIORITY_SENIOR_FIRST):
        score += policy.w_seniority * max(0, 100 - rank)
        breakdown["seniority_senior_first"] = rank
    if policy.uses(CRITERION_CALL_LIST):
        cl = call_list_rank_score(oid, policy)
        score += cl
        breakdown["call_list"] = cl
    if policy.uses(CRITERION_DAYS_OFF):
        score += policy.w_days_off * min(days_off, 14)
        breakdown["days_off_score"] = days_off
    if policy.uses(CRITERION_LOW_OT):
        low_ot = max(0.0, 40.0 - min(float(ot_hours), 40.0))
        score += policy.w_low_ot * low_ot
        breakdown["ot_hours"] = ot_hours
    if policy.uses(CRITERION_LEAST_RECENT_CALLBACK):
        since = days_since_last_offduty_cover(oid, coverage_date)
        score += policy.w_least_recent * min(since, 90) / 10.0
        breakdown["days_since_callback"] = since
    if policy.uses(CRITERION_SAME_SQUAD) and officer.get("squad") == request_squad:
        score += policy.w_same_squad
        breakdown["same_squad"] = True
    if policy.uses(CRITERION_HOME_BAND_MATCH):
        from logic.staffing_config import normalize_shift_start_to_active

        if home and normalize_shift_start_to_active(home) == covered:
            score += policy.w_home_band
            breakdown["home_band_match"] = True

    return True, score, breakdown


def get_off_duty_bump_settings_for_ui() -> Dict:
    policy = load_off_duty_bump_policy()
    return {
        "success": True,
        "policy": policy.to_dict(),
        "criteria_options": [
            {"id": c, "label": CRITERION_LABELS.get(c, c), "selected": c in policy.criteria} for c in ALL_CRITERIA
        ],
        "call_list": get_bump_call_list(),
        "call_list_cursor": get_call_list_cursor(),
    }
