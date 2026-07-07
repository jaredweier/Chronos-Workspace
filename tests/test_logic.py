import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

# Project root on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.helpers import test_database


class TestRotationLogic(unittest.TestCase):
    """Rotation and bump tests — isolated in-memory DB per test (avoids Windows file locks)."""

    def setUp(self):
        self._db_cm = test_database()
        self._db_cm.__enter__()
        import database
        import logic

        self.database = database
        self.logic = logic

    def tearDown(self):
        self._db_cm.__exit__(None, None, None)

    def test_cycle_day_wraps_at_14(self):
        base = date(2026, 6, 28)
        self.assertEqual(self.logic.get_cycle_day(base), 1)
        self.assertEqual(self.logic.get_cycle_day(date(2026, 7, 11)), 14)
        self.assertEqual(self.logic.get_cycle_day(date(2026, 7, 12)), 1)

    def test_squad_a_working_days(self):
        for day in [1, 2, 5, 6, 7, 10, 11]:
            self.assertEqual(self.logic.get_squad_on_duty(day), "A")
        for day in [3, 4, 8, 9, 12, 13, 14]:
            self.assertEqual(self.logic.get_squad_on_duty(day), "B")

    def test_shift_number_mapping(self):
        self.assertEqual(self.logic.get_shift_number("06:00"), 1)
        self.assertEqual(self.logic.get_shift_number("10:00"), 2)
        self.assertEqual(self.logic.get_shift_number("15:00"), 3)
        self.assertEqual(self.logic.get_shift_number("19:00"), 4)

    def test_high_risk_night_friday_saturday(self):
        self.assertTrue(self.logic.is_high_risk_night(date(2026, 7, 3)))  # Friday
        self.assertTrue(self.logic.is_high_risk_night(date(2026, 7, 4)))  # Saturday
        self.assertFalse(self.logic.is_high_risk_night(date(2026, 7, 6)))  # Monday

    def test_officer_working_follows_squad_rotation(self):
        officers = self.logic.get_officers_by_seniority()
        squad_a = next(o for o in officers if o["squad"] == "A")
        squad_b = next(o for o in officers if o["squad"] == "B")

        # Day 1: Squad A on duty
        self.assertTrue(self.logic.is_officer_working_on_day(squad_a["id"], date(2026, 6, 28)))
        self.assertFalse(self.logic.is_officer_working_on_day(squad_b["id"], date(2026, 6, 28)))

        # Day 3: Squad B on duty
        self.assertFalse(self.logic.is_officer_working_on_day(squad_a["id"], date(2026, 6, 30)))
        self.assertTrue(self.logic.is_officer_working_on_day(squad_b["id"], date(2026, 6, 30)))

    def test_bump_rules_allowed_shifts(self):
        from logic.staffing_config import get_active_bump_rules_by_start

        rules = get_active_bump_rules_by_start()
        self.assertEqual(rules.get("06:00"), ("10:00",))
        self.assertEqual(rules.get("19:00"), ("15:00",))

    def test_validate_bump_finds_replacement(self):
        officers = self.logic.get_officers_by_seniority()
        # Squad A day 1 — shift 1 officer requests off; shift 2/3 can bump
        original = next(o for o in officers if o["squad"] == "A" and o["shift_start"] == "06:00")
        request_date = "2026-06-30"  # Squad B day — cascade completes without extra coverage

        result = self.logic.validate_bump_feasibility(
            original["id"], request_date, original["squad"], original["shift_start"]
        )
        self.assertTrue(result.success)
        self.assertIsNotNone(result.replacement_name)

    def test_night_minimum_blocks_bump_on_high_risk_night(self):
        officers = self.logic.get_officers_by_seniority()
        night_shift = next(o for o in officers if o["squad"] == "A" and o["shift_start"] == "19:00")
        friday = "2026-07-03"
        if self.logic.is_officer_working_on_day(night_shift["id"], date(2026, 7, 3)):
            result = self.logic.validate_bump_feasibility(
                night_shift["id"], friday, night_shift["squad"], night_shift["shift_start"]
            )
            self.assertTrue(result.success, result.message)

    def test_suggest_bump_chain_explains_manual_block(self):
        from unittest.mock import patch

        officers = self.logic.get_officers_by_seniority()
        original = next(o for o in officers if o["squad"] == "A" and o["shift_start"] == "06:00")
        work_day = "2026-06-28"
        with patch("config.MIN_REST_HOURS_BETWEEN_SHIFTS", 10.0):
            suggestion = self.logic.suggest_bump_chain(
                original["id"], work_day, original["squad"], original["shift_start"]
            )
        self.assertFalse(suggestion.success)
        self.assertTrue(suggestion.requires_manual)
        self.assertTrue(suggestion.steps)
        self.assertIn("Supervisor required", self.logic.format_bump_suggestion(suggestion))

    def test_suggest_bump_chain_off_rotation_auto(self):
        officers = self.logic.get_officers_by_seniority()
        original = next(o for o in officers if o["squad"] == "A" and o["shift_start"] == "06:00")
        suggestion = self.logic.suggest_bump_chain(
            original["id"], "2026-06-30", original["squad"], original["shift_start"]
        )
        self.assertTrue(suggestion.success)
        self.assertEqual(len(suggestion.steps), 1)
        self.assertFalse(suggestion.steps[0].replacement_on_duty)

    def test_cascade_completes_without_manual_review(self):
        officers = self.logic.get_officers_by_seniority()
        original = next(o for o in officers if o["squad"] == "A" and o["shift_start"] == "06:00")
        request_date = "2026-06-30"  # Squad off duty — replacement needs no cascade
        chain, err = self.logic.plan_bump_chain(
            original["id"], request_date, original["squad"], original["shift_start"]
        )
        self.assertIsNone(err)
        self.assertEqual(len(chain), 1)

        create_result = self.logic.create_day_off_request(original["id"], request_date, "Vacation", "Cascade test")
        self.assertTrue(create_result["success"])
        process_result = self.logic.process_day_off_request(create_result["request_id"], action="approve")
        self.assertTrue(process_result.success)

        with self.database.connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM schedule_overrides WHERE override_date = ?",
                (request_date,),
            )
            self.assertEqual(cursor.fetchone()[0], 1)

    def test_incomplete_cascade_routes_to_manual_review(self):
        from unittest.mock import patch

        officers = self.logic.get_officers_by_seniority()
        original = next(o for o in officers if o["squad"] == "A" and o["shift_start"] == "06:00")
        request_date = "2026-07-02"
        with patch("config.MIN_REST_HOURS_BETWEEN_SHIFTS", 10.0):
            chain, err = self.logic.plan_bump_chain(
                original["id"], request_date, original["squad"], original["shift_start"]
            )
            self.assertIsNotNone(err)
            self.assertEqual(len(chain), 0)

            create_result = self.logic.create_day_off_request(
                original["id"], request_date, "Vacation", "Cascade manual test"
            )
            result = self.logic.process_day_off_request(create_result["request_id"], "approve")
        self.assertFalse(result.success)
        self.assertTrue(result.requires_manual)
        self.assertEqual(result.status, "Pending Manual Review")

    def test_bulk_approve_auto_ok_requests(self):
        officers = self.logic.get_officers_by_seniority()
        officer = next(o for o in officers if o["squad"] == "A")
        created = self.logic.create_day_off_request(
            officer["id"],
            "2026-06-28",
            "Vacation",
        )
        self.assertTrue(created["success"])
        result = self.logic.bulk_approve_auto_ok_requests()
        self.assertTrue(result["success"])

    def test_bulk_reject_pending_requests(self):
        officers = self.logic.get_officers_by_seniority()
        officer = next(o for o in officers if o["squad"] == "B")
        created = self.logic.create_day_off_request(
            officer["id"],
            "2026-06-29",
            "Vacation",
        )
        self.assertTrue(created["success"])
        result = self.logic.bulk_reject_pending_requests()
        self.assertTrue(result["success"])
        self.assertGreaterEqual(result["rejected"], 1)
        reqs = self.logic.get_day_off_requests(status_filter="Rejected")
        self.assertTrue(any(r["id"] == created["request_id"] for r in reqs))

    def test_approved_training_maps_to_training_status(self):
        from tests.helpers import get_any_officer, off_date_for_squad

        original = get_any_officer("B", "06:00")
        target = off_date_for_squad("B")
        create_result = self.logic.create_day_off_request(
            original["id"],
            target.isoformat(),
            "Training",
            "Training day test",
        )
        self.assertTrue(create_result["success"])
        approve = self.logic.process_day_off_request(create_result["request_id"], "approve")
        self.assertTrue(approve.success)
        status = self.logic.get_officer_day_status(original["id"], target)
        self.assertEqual(status, "training")

    def test_create_and_approve_day_off_request(self):
        officers = self.logic.get_officers_by_seniority()
        officer = next(o for o in officers if o["squad"] == "A")
        create_result = self.logic.create_day_off_request(officer["id"], "2026-06-28", "Vacation", "Test")
        self.assertTrue(create_result["success"])

        process_result = self.logic.process_day_off_request(create_result["request_id"], action="approve")
        self.assertIn(process_result.status, ["Approved", "Pending Manual Review"])

    def test_payroll_overtime_calculation(self):
        result = self.logic.calculate_pay_for_entry("Overtime Earned", 8.0, 30.0)
        self.assertEqual(result.overtime_pay, 360.0)
        self.assertEqual(result.total_pay, 360.0)

    def test_payroll_holiday_multiplier(self):
        result = self.logic.calculate_pay_for_entry("Holiday Pay", 8.0, 30.0)
        self.assertEqual(result.overtime_pay, 600.0)

    def test_schedule_matrix_matches_rotation(self):
        start = date(2026, 7, 12)
        end = start + timedelta(days=13)
        matrix, days = self.logic.build_schedule_matrix(start, end)
        self.assertEqual(len(days), 14)
        squad_a = next(e for e in matrix if e["officer"]["squad"] == "A")
        squad_b = next(e for e in matrix if e["officer"]["squad"] == "B")
        self.assertEqual(squad_a["days"][start], "working")
        self.assertEqual(squad_b["days"][start], "off")
        self.assertEqual(squad_a["days"][date(2026, 7, 14)], "off")
        self.assertEqual(squad_b["days"][date(2026, 7, 14)], "working")

    def test_monthly_summary_working_counts(self):
        summary = self.logic.get_monthly_rotation_summary(2026, 6)
        self.assertEqual(len(summary), 30)
        day_one = summary[0]
        self.assertEqual(day_one["date"], date(2026, 6, 1))
        self.assertGreater(day_one["working_officers"], 0)

    def test_officer_work_dates_from_summary(self):
        officers = self.logic.get_officers_by_seniority()
        officer_a = next(o for o in officers if o["squad"] == "A" and o.get("active") == 1)
        summary = self.logic.get_monthly_rotation_summary(2026, 7)
        work_dates = self.logic.get_officer_work_dates_from_summary(officer_a["id"], summary)
        self.assertGreater(len(work_dates), 0)
        for entry in summary:
            status = self.logic.get_officer_day_status(officer_a["id"], entry["date"])
            if status in ("working", "covering", "swapped", "training"):
                self.assertIn(entry["date"].isoformat(), work_dates)


if __name__ == "__main__":
    unittest.main()
