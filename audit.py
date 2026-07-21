"""
Regression audit for known scheduling bugs.
Run: python dev.py audit
"""

from dataclasses import dataclass
from typing import List

from config import ROTATION_BASE_DATE
from tests.helpers import get_any_officer, off_date_for_squad, test_database, working_date_for_squad


@dataclass
class AuditFinding:
    check_id: str
    passed: bool
    detail: str


def run_audit() -> List[AuditFinding]:
    findings: List[AuditFinding] = []

    with test_database():
        import logic
        from database import get_connection
        from logic.coverage_optimizer import validate_bump_feasibility

        # AUD-001: Off-rotation day-off request allowed at creation
        squad_b = get_any_officer("B")
        off_day = off_date_for_squad("B").strftime("%Y-%m-%d")
        r = logic.create_day_off_request(squad_b["id"], off_day, "Vacation")
        findings.append(
            AuditFinding(
                "AUD-001-off-rotation-request-allowed",
                r.get("success"),
                "ok" if r.get("success") else r.get("message", "request rejected"),
            )
        )

        squad_a = get_any_officer("A", "06:00")

        # AUD-002: Re-approve does not create duplicate overrides (Squad B working day → real bump)
        squad_b_dup = get_any_officer("B", "06:00")
        dup_work_day = working_date_for_squad("B").strftime("%Y-%m-%d")
        cr = logic.create_day_off_request(squad_b_dup["id"], dup_work_day, "Vacation")
        first_approve = logic.process_day_off_request(cr["request_id"], "approve")
        conn = get_connection()
        c = conn.cursor()
        c.execute(
            "SELECT COUNT(*) FROM schedule_overrides WHERE original_officer_id = ?",
            (squad_b_dup["id"],),
        )
        overrides_after_first = c.fetchone()[0]
        logic.process_day_off_request(cr["request_id"], "approve")
        c.execute(
            "SELECT COUNT(*) FROM schedule_overrides WHERE original_officer_id = ?",
            (squad_b_dup["id"],),
        )
        overrides_after_second = c.fetchone()[0]
        conn.close()
        aud002_ok = (
            first_approve.success and overrides_after_first >= 1 and overrides_after_second == overrides_after_first
        )
        findings.append(
            AuditFinding(
                "AUD-002-no-duplicate-override",
                aud002_ok,
                f"first_approve={first_approve.success}, overrides after first={overrides_after_first}, second={overrides_after_second}",
            )
        )

        # AUD-003: Day shift on Friday not blocked by night-minimum rule
        day_officer = get_any_officer("A", "06:00")
        bump = validate_bump_feasibility(
            day_officer["id"], "2026-07-03", day_officer["squad"], day_officer["shift_start"]
        )
        night_blocked = bump.requires_manual and "night" in bump.message.lower()
        findings.append(
            AuditFinding(
                "AUD-003-day-shift-not-night-blocked",
                not night_blocked,
                bump.message or "ok",
            )
        )

        # AUD-004: Rejected request cannot be re-approved
        cr2 = logic.create_day_off_request(squad_a["id"], "2026-07-02", "Sick")
        logic.process_day_off_request(cr2["request_id"], "reject")
        rej = logic.process_day_off_request(cr2["request_id"], "approve")
        findings.append(
            AuditFinding(
                "AUD-004-reject-blocks-reapprove",
                not rej.success,
                rej.message,
            )
        )

        # AUD-005: Dates before rotation base are rejected
        before_base = (ROTATION_BASE_DATE - __import__("datetime").timedelta(days=10)).strftime("%Y-%m-%d")
        cr3 = logic.create_day_off_request(squad_a["id"], before_base, "Vacation")
        findings.append(
            AuditFinding(
                "AUD-005-before-base-date-blocked",
                not cr3.get("success"),
                cr3.get("message", "ok"),
            )
        )

        # AUD-006: Bump auto-resolves when on-duty cascade completes
        bump_test_day = working_date_for_squad("A").strftime("%Y-%m-%d")
        bump_ok = validate_bump_feasibility(squad_a["id"], bump_test_day, squad_a["squad"], squad_a["shift_start"])
        if bump_ok.replacement_name:
            from validators import officer_uses_command_staff_schedule

            officers = logic.get_officers_by_seniority()
            replacement = next(o for o in officers if o["name"] == bump_ok.replacement_name)
            allowed = (
                bump_ok.success
                and replacement.get("squad") == squad_a["squad"]
                and not officer_uses_command_staff_schedule(replacement)
            )
            findings.append(
                AuditFinding(
                    "AUD-006-bump-finds-eligible-replacement",
                    allowed,
                    f"replacement={replacement['name']} squad={replacement['squad']} shift={replacement['shift_start']}",
                )
            )
        else:
            findings.append(
                AuditFinding(
                    "AUD-006-bump-finds-eligible-replacement",
                    False,
                    "no replacement found for bump test",
                )
            )

        # AUD-007: Supervisor can approve/reject Pending Manual Review
        from validators import officer_uses_command_staff_schedule

        officers_a6 = [
            o
            for o in logic.get_officers_by_seniority()
            if o["squad"] == "A" and o["shift_start"] == "06:00" and not officer_uses_command_staff_schedule(o)
        ]
        manual_officer = officers_a6[0] if officers_a6 else get_any_officer("A", "06:00")
        manual_day = off_date_for_squad("A").strftime("%Y-%m-%d")
        cr_mr = logic.create_day_off_request(manual_officer["id"], manual_day, "Vacation")
        logic.process_day_off_request(cr_mr["request_id"], "approve")
        forced = logic.process_day_off_request(cr_mr["request_id"], "approve")
        findings.append(
            AuditFinding(
                "AUD-007-manual-review-approve",
                forced.success and forced.status == "Approved",
                forced.message,
            )
        )

        # AUD-008 / S-07: Duplicate blocked while manual review pending
        dup_officer = get_any_officer("B", "10:00")
        dup_day = off_date_for_squad("B").strftime("%Y-%m-%d")
        cr_dup = logic.create_day_off_request(dup_officer["id"], dup_day, "Vacation")
        logic.process_day_off_request(cr_dup["request_id"], "approve")
        dup = logic.create_day_off_request(dup_officer["id"], dup_day, "Personal")
        findings.append(
            AuditFinding(
                "AUD-008-duplicate-during-manual-review",
                not dup.get("success"),
                dup.get("message", "blocked"),
            )
        )

        # AUD-009 / S-10: Off-rotation day routes to manual review (no on-duty replacement)
        s10_officer = get_any_officer("A", "06:00")
        s10_date = off_date_for_squad("A").strftime("%Y-%m-%d")
        cr_s10 = logic.create_day_off_request(s10_officer["id"], s10_date, "Vacation")
        pr_s10 = logic.process_day_off_request(cr_s10["request_id"], "approve")
        conn = get_connection()
        c = conn.cursor()
        c.execute(
            "SELECT COUNT(*) FROM schedule_overrides WHERE override_date = ? AND original_officer_id = ?",
            (s10_date, s10_officer["id"]),
        )
        s10_overrides = c.fetchone()[0]
        conn.close()
        findings.append(
            AuditFinding(
                "AUD-009-s10-off-rotation-manual-review",
                pr_s10.requires_manual and pr_s10.status == "Pending Manual Review" and s10_overrides == 0,
                f"status={pr_s10.status}, overrides={s10_overrides}",
            )
        )

        # AUD-010 / S-11: Shift swap creates dual overrides
        swap_o1 = get_any_officer("A", "06:00")
        swap_o2 = get_any_officer("A", "10:00")
        swap_day = working_date_for_squad("A").strftime("%Y-%m-%d")
        cr_swap = logic.create_shift_swap_request(swap_o1["id"], swap_o2["id"], swap_day)
        if not cr_swap.get("success"):
            findings.append(
                AuditFinding(
                    "AUD-010-s11-shift-swap-overrides",
                    False,
                    cr_swap.get("message", "swap create failed"),
                )
            )
        else:
            pr_swap = logic.process_shift_swap(cr_swap["swap_id"], "approve")
            conn = get_connection()
            c = conn.cursor()
            c.execute(
                "SELECT COUNT(*) FROM schedule_overrides WHERE override_date = ? AND reason = 'Shift Swap'",
                (swap_day,),
            )
            swap_count = c.fetchone()[0]
            conn.close()
            findings.append(
                AuditFinding(
                    "AUD-010-s11-shift-swap-overrides",
                    pr_swap.success and swap_count == 2,
                    f"swap={pr_swap.success}, overrides={swap_count}",
                )
            )

    return findings


def print_report(findings: List[AuditFinding]) -> int:
    passed = sum(1 for f in findings if f.passed)
    total = len(findings)
    print(
        f"Audit: {passed}/{total} passed\n"
        "NOTE: HISTORICAL ONLY (AUD-001..010 fixed regressions) — "
        "not product health. Green audit ≠ Chronos/simulator OK.\n"
    )
    for f in findings:
        status = "PASS" if f.passed else "FAIL"
        print(f"  [{status}] {f.check_id}: {f.detail}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(print_report(run_audit()))
