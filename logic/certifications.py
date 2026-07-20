"""Officer certifications and shift-band gating."""

from datetime import date
from typing import Dict, List, Optional, Tuple

from database import connection
from logic.officers import get_officer_by_id
from logic.users import log_audit_action
from validators import parse_date, storage_date_str


def list_certification_types(
    *,
    active_only: bool = True,
    category: Optional[str] = None,
) -> List[Dict]:
    with connection() as conn:
        cursor = conn.cursor()
        clauses = []
        params: List = []
        if active_only:
            clauses.append("active = 1")
        if category:
            clauses.append("category = ?")
            params.append(category)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        try:
            cursor.execute(f"SELECT * FROM certification_types{where} ORDER BY name", params)
        except Exception:
            # Pre-migration DBs without category
            cursor.execute(
                "SELECT * FROM certification_types" + (" WHERE active = 1" if active_only else "") + " ORDER BY name"
            )
        rows = [dict(r) for r in cursor.fetchall()]
    return rows


def list_immunization_types(*, active_only: bool = True) -> List[Dict]:
    """ESO-style medical readiness types (category=immunization)."""
    return list_certification_types(active_only=active_only, category="immunization")


def officer_immunization_status(officer_id: int, as_of: Optional[date] = None) -> Dict:
    """Summary of immunization/medical readiness for roster gates."""
    as_of = as_of or date.today()
    types = list_immunization_types(active_only=True)
    by_type = {c.get("cert_type_id"): c for c in get_officer_certifications(officer_id)}
    rows = []
    missing = 0
    expired = 0
    for t in types:
        tid = t["id"]
        rec = by_type.get(tid)
        if not rec:
            rows.append({"code": t.get("code"), "name": t.get("name"), "status": "missing"})
            missing += 1
            continue
        ok = _cert_is_valid(rec, as_of)
        st = "valid" if ok else "expired"
        if not ok:
            expired += 1
        rows.append(
            {
                "code": t.get("code"),
                "name": t.get("name"),
                "status": st,
                "expires_date": rec.get("expires_date"),
            }
        )
    return {
        "success": True,
        "officer_id": officer_id,
        "missing": missing,
        "expired": expired,
        "ok": missing == 0 and expired == 0,
        "items": rows,
    }


def get_officer_certifications(officer_id: int) -> List[Dict]:
    with connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT c.*, t.code, t.name AS cert_name, t.description
            FROM officer_certifications c
            JOIN certification_types t ON c.cert_type_id = t.id
            WHERE c.officer_id = ?
            ORDER BY t.name
            """,
            (officer_id,),
        )
        rows = [dict(r) for r in cursor.fetchall()]
    return rows


def list_expiring_certifications(*, within_days: int = 60, as_of: Optional[date] = None) -> List[Dict]:
    """Certs expiring within N days (or already expired) for dock / publish soft warnings."""
    from datetime import timedelta

    as_of = as_of or date.today()
    horizon = as_of + timedelta(days=max(0, int(within_days)))
    with connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT c.*, t.code, t.name AS cert_name, t.description,
                       o.name AS officer_name, o.id AS officer_id
                FROM officer_certifications c
                JOIN certification_types t ON c.cert_type_id = t.id
                JOIN officers o ON o.id = c.officer_id
                WHERE c.expires_date IS NOT NULL AND c.expires_date != ''
                  AND o.active = 1
                ORDER BY c.expires_date ASC
                """
            )
            rows = [dict(r) for r in cursor.fetchall()]
        except Exception:
            rows = []
    out: List[Dict] = []
    for row in rows:
        try:
            exp = parse_date(row.get("expires_date"))
        except Exception:
            continue
        if exp <= horizon:
            row["expires_date"] = exp.isoformat() if hasattr(exp, "isoformat") else row.get("expires_date")
            out.append(row)
    return out


def get_shift_cert_requirements() -> List[Dict]:
    with connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT r.*, t.code, t.name AS cert_name
            FROM shift_cert_requirements r
            JOIN certification_types t ON r.cert_type_id = t.id
            ORDER BY r.shift_start, t.name
            """
        )
        rows = [dict(r) for r in cursor.fetchall()]
    return rows


def _cert_is_valid(row: Dict, as_of: date) -> bool:
    expires = row.get("expires_date")
    if not expires:
        return True
    try:
        return parse_date(expires) >= as_of
    except ValueError:
        return True


def officer_meets_shift_cert_requirements(
    officer_id: int,
    shift_start: str,
    as_of: Optional[date] = None,
) -> Tuple[bool, str]:
    """Return (ok, message) for required certs on a shift band."""
    from validators import validate_officer_certifications

    check = validate_officer_certifications(officer_id, shift_start, as_of=as_of)
    if check.ok:
        return True, ""
    return False, check.message or "Missing required certification"


def officer_has_cert_codes(
    officer_id: int,
    required_codes: List[str],
    *,
    as_of: Optional[date] = None,
) -> Tuple[bool, str]:
    """True if officer holds all active/valid cert codes (by type code)."""
    codes = [str(c).strip().upper() for c in (required_codes or []) if str(c).strip()]
    if not codes:
        return True, ""
    as_of = as_of or date.today()
    held = get_officer_certifications(officer_id)
    valid_codes = set()
    for row in held:
        code = str(row.get("code") or "").strip().upper()
        if code and _cert_is_valid(row, as_of):
            valid_codes.add(code)
    missing = [c for c in codes if c not in valid_codes]
    if missing:
        return False, f"Missing cert(s): {', '.join(missing)}"
    return True, ""


def filter_officers_meeting_certs(
    officer_ids: List[int],
    required_codes: List[str],
    *,
    as_of: Optional[date] = None,
    shift_start: Optional[str] = None,
) -> Dict:
    """Filter roster for sim / open-shift fill by cert codes and optional band rules."""
    codes = [str(c).strip() for c in (required_codes or []) if str(c).strip()]
    ok_ids: List[int] = []
    blocked: List[Dict] = []
    for oid in officer_ids or []:
        try:
            oid_i = int(oid)
        except (TypeError, ValueError):
            continue
        if codes:
            ok, msg = officer_has_cert_codes(oid_i, codes, as_of=as_of)
            if not ok:
                blocked.append({"officer_id": oid_i, "reason": msg})
                continue
        if shift_start:
            ok, msg = officer_meets_shift_cert_requirements(oid_i, shift_start, as_of=as_of)
            if not ok:
                blocked.append({"officer_id": oid_i, "reason": msg})
                continue
        ok_ids.append(oid_i)
    return {
        "success": True,
        "required_codes": codes,
        "eligible_ids": ok_ids,
        "blocked": blocked,
        "eligible_count": len(ok_ids),
        "blocked_count": len(blocked),
        "message": (
            f"{len(ok_ids)} eligible · {len(blocked)} blocked by certs"
            if codes or shift_start
            else f"{len(ok_ids)} officers (no cert filter)"
        ),
    }


def roster_cert_coverage_for_sim(
    *,
    required_codes: Optional[List[str]] = None,
    shift_starts: Optional[List[str]] = None,
    num_officers: Optional[int] = None,
) -> Dict:
    """Precheck: how many active officers can fill required certs / band starts."""
    from logic.officers import get_officers_by_seniority

    active = [o for o in get_officers_by_seniority() if o.get("active") == 1]
    ids = [int(o["id"]) for o in active if o.get("id") is not None]
    codes = list(required_codes or [])
    starts = list(shift_starts or [])
    # Eligible if meets codes AND at least one start band (or any if no starts)
    if not starts:
        filt = filter_officers_meeting_certs(ids, codes)
        eligible = filt["eligible_count"]
        blocked = filt["blocked_count"]
    else:
        eligible_set = set()
        blocked_n = 0
        for st in starts:
            filt = filter_officers_meeting_certs(ids, codes, shift_start=str(st))
            eligible_set.update(filt["eligible_ids"])
            blocked_n = max(blocked_n, filt["blocked_count"])
        eligible = len(eligible_set)
        blocked = max(0, len(ids) - eligible)
    need = int(num_officers) if num_officers is not None else 0
    thin = bool(need and eligible < need)
    return {
        "success": True,
        "active_roster": len(ids),
        "eligible": eligible,
        "blocked": blocked,
        "required_codes": codes,
        "thin_for_headcount": thin,
        "message": (f"Cert-eligible roster: {eligible}/{len(ids)}" + (f" — thin vs N={need}" if thin else "")),
    }


def assign_officer_certification(
    officer_id: int,
    cert_type_id: int,
    *,
    issued_date: Optional[str] = None,
    expires_date: Optional[str] = None,
    notes: str = "",
    user_id: Optional[int] = None,
) -> Dict:
    if not get_officer_by_id(officer_id):
        return {"success": False, "message": "Officer not found"}
    with connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT id FROM certification_types WHERE id = ? AND active = 1", (cert_type_id,))
            if not cursor.fetchone():
                return {"success": False, "message": "Certification type not found"}
            issued = storage_date_str(issued_date) if issued_date else None
            expires = storage_date_str(expires_date) if expires_date else None
            cursor.execute(
                """
                INSERT INTO officer_certifications (officer_id, cert_type_id, issued_date, expires_date, notes)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(officer_id, cert_type_id) DO UPDATE SET
                    issued_date = excluded.issued_date,
                    expires_date = excluded.expires_date,
                    notes = excluded.notes
                """,
                (officer_id, cert_type_id, issued, expires, notes or None),
            )
            conn.commit()
            log_audit_action("cert.assign", "officer_certification", officer_id, user_id, str(cert_type_id))
            return {"success": True}
        except ValueError as exc:
            return {"success": False, "message": str(exc)}
        except Exception as exc:
            conn.rollback()
            return {"success": False, "message": str(exc)}


def set_shift_cert_requirement(shift_start: str, cert_type_id: int, *, user_id: Optional[int] = None) -> Dict:
    with connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO shift_cert_requirements (shift_start, cert_type_id)
                VALUES (?, ?)
                ON CONFLICT(shift_start, cert_type_id) DO NOTHING
                """,
                (shift_start, cert_type_id),
            )
            conn.commit()
            log_audit_action("cert.requirement", "shift_cert_requirement", cert_type_id, user_id, shift_start)
            return {"success": True}
        except Exception as exc:
            conn.rollback()
            return {"success": False, "message": str(exc)}
