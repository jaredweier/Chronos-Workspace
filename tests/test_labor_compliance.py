import unittest
from datetime import date, timedelta

from config import (
    CALLBACK_MINIMUM_HOURS,
    FLSA_207K_BASE_DATE,
    FLSA_207K_WORK_PERIOD_DAYS,
    FLSA_COMP_TIME_MAX_HOURS,
    MAX_CONSECUTIVE_WORK_DAYS,
)
from tests.helpers import get_any_officer, test_database


class LaborComplianceTests(unittest.TestCase):
    def test_flsa_work_period_uses_manual_days_not_pay_period(self):
        with test_database():
            import logic

            logic.set_department_setting("flsa_work_period_days", "21")
            period_days = logic.get_flsa_work_period_days()
            self.assertEqual(period_days, 21)
            ref = FLSA_207K_BASE_DATE + timedelta(days=10)
            start, end = logic.get_flsa_207k_work_period(ref)
            self.assertEqual(start, FLSA_207K_BASE_DATE)
            self.assertEqual((end - start).days + 1, 21)

    def test_flsa_default_period_not_rotation(self):
        with test_database():
            import logic

            logic.set_department_setting("flsa_work_period_days", "")
            logic.set_department_setting("rotation_cycle_length", "14")
            self.assertEqual(logic.get_flsa_work_period_days(), FLSA_207K_WORK_PERIOD_DAYS)

    def test_flsa_threshold_scales_with_period_days(self):
        with test_database():
            import logic

            days = logic.get_flsa_work_period_days()
            threshold = logic.flsa_threshold_for_period_days(days)
            self.assertAlmostEqual(threshold, round(171.0 * days / 28.0, 1), places=1)

    def test_flsa_207k_status_structure(self):
        with test_database():
            import logic

            officer = get_any_officer("A")
            status = logic.get_flsa_207k_status(officer["id"], date(2026, 7, 1))
            self.assertIn("hours", status)
            self.assertIn("threshold", status)
            self.assertEqual(status["period_days"], logic.get_flsa_work_period_days())

    def test_flsa_payroll_summary(self):
        with test_database():
            import logic

            officer = get_any_officer("A")
            flsa = logic.get_flsa_payroll_summary(officer["id"], date(2026, 7, 1))
            self.assertTrue(flsa["enabled"])
            self.assertEqual(flsa["period_days"], logic.get_flsa_work_period_days())
            self.assertIn("hours_threshold", flsa)

    def test_pay_period_hours_summary_includes_flsa(self):
        with test_database():
            import logic

            officer = get_any_officer("A")
            p_start, _ = logic.get_pay_period()
            summary = logic.get_pay_period_hours_summary(p_start, officer_id=officer["id"])
            self.assertIn("flsa", summary)
            self.assertTrue(summary["flsa"].get("enabled"))

    def test_callback_minimum_hours(self):
        with test_database():
            import logic

            self.assertEqual(logic.callback_payable_hours(0.5), CALLBACK_MINIMUM_HOURS)
            self.assertEqual(logic.callback_payable_hours(3.0), 3.0)

    def test_callback_payroll_entry(self):
        with test_database():
            import logic

            officer = get_any_officer("A")
            result = logic.create_payroll_entry(officer["id"], "2026-07-01", "Callback", 0.5)
            self.assertTrue(result["success"])
            self.assertAlmostEqual(result["calculated_pay"], CALLBACK_MINIMUM_HOURS * officer["pay_rate"], places=2)

    def test_comp_time_cap_blocks_accrual(self):
        with test_database():
            import logic
            from database import get_connection

            officer = get_any_officer("A")
            logic.get_officer_time_banks(officer["id"], date(2026, 7, 1))
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE officer_time_banks SET comp_hours = ? WHERE officer_id = ?",
                (FLSA_COMP_TIME_MAX_HOURS - 1, officer["id"]),
            )
            conn.commit()
            conn.close()

            result = logic.create_payroll_entry(officer["id"], "2026-07-01", "Comp Earned", 8.0)
            self.assertFalse(result["success"])
            self.assertIn("Comp time cap", result["message"])

    def test_labor_compliance_report(self):
        with test_database():
            import logic

            report = logic.get_labor_compliance_report()
            self.assertTrue(report["success"])
            self.assertIn("issues", report)
            self.assertEqual(report["flsa_207k_period_days"], logic.get_flsa_work_period_days())
            self.assertEqual(report["comp_cap_hours"], FLSA_COMP_TIME_MAX_HOURS)

    def test_validate_comp_time_cap_validator(self):
        from validators import validate_comp_time_cap

        self.assertTrue(validate_comp_time_cap(100, 10).ok)
        self.assertFalse(validate_comp_time_cap(FLSA_COMP_TIME_MAX_HOURS - 1, 2).ok)

    def test_validate_consecutive_work_days(self):
        from validators import validate_consecutive_work_days

        self.assertTrue(validate_consecutive_work_days(MAX_CONSECUTIVE_WORK_DAYS, MAX_CONSECUTIVE_WORK_DAYS).ok)
        self.assertFalse(validate_consecutive_work_days(MAX_CONSECUTIVE_WORK_DAYS + 1, MAX_CONSECUTIVE_WORK_DAYS).ok)


if __name__ == "__main__":
    unittest.main()
