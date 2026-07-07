import os
import tempfile
import unittest
from datetime import date, timedelta

from config import TIMECARD_REGULAR_TYPE
from tests.helpers import get_any_officer, test_database


class TestPayroll(unittest.TestCase):
    def test_create_payroll_entry(self):
        with test_database():
            import logic

            officer = get_any_officer("A")
            result = logic.create_payroll_entry(officer["id"], "2026-07-01", "Overtime Earned", 4.0)
            self.assertTrue(result["success"])
            self.assertGreater(result["calculated_pay"], 0)

            entries = logic.get_payroll_entries(officer_id=officer["id"])
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["entry_type"], "Overtime Earned")

    def test_night_differential_after_multiplier(self):
        with test_database():
            import logic

            calc = logic.calculate_pay_for_entry(
                "Overtime Earned",
                8.0,
                30.0,
                night_differential_hours=4.0,
                night_differential_rate=1.5,
            )
            self.assertEqual(calc.overtime_pay, round(8.0 * 30.0 * 1.5, 2))
            self.assertEqual(calc.night_differential_pay, round(4.0 * 1.5, 2))
            self.assertEqual(calc.total_pay, round(calc.overtime_pay + calc.night_differential_pay, 2))

    def test_holiday_pay_multiplier(self):
        with test_database():
            import logic

            officer = get_any_officer("A")
            result = logic.create_payroll_entry(officer["id"], "2026-07-04", "Holiday Pay", 8.0)
            self.assertTrue(result["success"])
            self.assertAlmostEqual(result["calculated_pay"], 8.0 * officer["pay_rate"] * 2.5, places=2)

    def test_comp_earned_credits_bank(self):
        with test_database():
            import logic

            officer = get_any_officer("A")
            result = logic.create_payroll_entry(officer["id"], "2026-07-01", "Comp Earned", 8.0)
            self.assertTrue(result["success"])
            banks = logic.get_officer_time_banks(officer["id"], date(2026, 7, 1))
            self.assertEqual(banks["comp_hours"], 4.0)

    def test_comp_taken_debits_bank(self):
        with test_database():
            import logic

            officer = get_any_officer("A")
            logic.create_payroll_entry(officer["id"], "2026-07-01", "Comp Earned", 8.0)
            result = logic.create_payroll_entry(officer["id"], "2026-07-02", "Comp Taken", 4.0)
            self.assertTrue(result["success"])
            banks = logic.get_officer_time_banks(officer["id"], date(2026, 7, 2))
            self.assertEqual(banks["comp_hours"], 0.0)

    def test_comp_taken_insufficient_bank(self):
        with test_database():
            import logic

            officer = get_any_officer("A")
            result = logic.create_payroll_entry(officer["id"], "2026-07-01", "Comp Taken", 1.0)
            self.assertFalse(result["success"])
            self.assertIn("Insufficient comp bank", result["message"])

    def test_sick_monthly_accrual(self):
        with test_database():
            import logic
            from config import SICK_MONTHLY_ACCRUAL_HOURS

            officer = get_any_officer("A")
            banks = logic.get_officer_time_banks(officer["id"], date(2026, 7, 1))
            self.assertEqual(banks["sick_hours"], SICK_MONTHLY_ACCRUAL_HOURS)

    def test_unpaid_zero_pay(self):
        with test_database():
            import logic

            officer = get_any_officer("A")
            result = logic.create_payroll_entry(officer["id"], "2026-07-01", "Unpaid", 8.0)
            self.assertTrue(result["success"])
            self.assertEqual(result["calculated_pay"], 0.0)

    def test_annual_holiday_banks_accrue(self):
        with test_database():
            import logic
            from config import FLOAT_HOLIDAY_ANNUAL_HOURS, HOLIDAY_ANNUAL_HOURS

            officer = get_any_officer("A")
            banks = logic.get_officer_time_banks(officer["id"], date(2026, 1, 15))
            self.assertEqual(banks["float_holiday_hours"], FLOAT_HOLIDAY_ANNUAL_HOURS)
            self.assertEqual(banks["holiday_hours"], HOLIDAY_ANNUAL_HOURS)

    def test_payroll_entries_period_filter(self):
        with test_database():
            import logic

            officer = get_any_officer("A")
            period_start, _ = logic.get_pay_period()
            logic.create_payroll_entry(
                officer["id"],
                period_start.isoformat(),
                "Overtime Earned",
                4.0,
            )
            logic.create_payroll_entry(officer["id"], "2020-01-01", "Unpaid", 2.0)
            scoped = logic.get_payroll_entries(
                officer_id=officer["id"],
                period_start=period_start,
            )
            self.assertEqual(len(scoped), 1)
            self.assertEqual(scoped[0]["entry_type"], "Overtime Earned")

    def test_pay_period_hours_summary(self):
        with test_database():
            import logic

            officer = get_any_officer("A")
            period_start, period_end = logic.get_pay_period()
            day_two = min(period_start + timedelta(days=1), period_end)
            day_three = min(period_start + timedelta(days=2), period_end)

            logic.save_timecard_entry(
                officer["id"],
                period_start.isoformat(),
                8.0,
                entry_type=TIMECARD_REGULAR_TYPE,
                night_diff_hours=2.0,
            )
            logic.save_timecard_entry(
                officer["id"],
                day_two.isoformat(),
                4.0,
                entry_type="Comp Earned",
            )
            logic.create_payroll_entry(
                officer["id"],
                day_three.isoformat(),
                "Overtime Earned",
                3.0,
            )

            summary = logic.get_pay_period_hours_summary(period_start)
            self.assertTrue(summary["success"])
            self.assertEqual(summary["total_hours"], 15.0)
            self.assertEqual(summary["night_diff_hours"], 2.0)
            self.assertEqual(summary["by_entry_type"][TIMECARD_REGULAR_TYPE], 8.0)
            self.assertEqual(summary["by_entry_type"]["Comp Earned"], 4.0)
            self.assertEqual(summary["by_entry_type"]["Overtime Earned"], 3.0)

            scoped = logic.get_pay_period_hours_summary(period_start, officer_id=officer["id"])
            self.assertEqual(scoped["total_hours"], 15.0)

    def test_export_payroll_csv_officer_scope(self):
        with test_database():
            import logic

            officer_a = get_any_officer("A")
            officer_b = get_any_officer("B")
            period_start, _ = logic.get_pay_period()
            logic.create_payroll_entry(
                officer_a["id"],
                period_start.isoformat(),
                "Overtime Earned",
                4.0,
            )
            logic.create_payroll_entry(
                officer_b["id"],
                period_start.isoformat(),
                "Unpaid",
                2.0,
            )
            with tempfile.TemporaryDirectory() as tmp:
                path = os.path.join(tmp, "payroll.csv")
                result = logic.export_payroll_csv(
                    period_start=period_start,
                    officer_id=officer_a["id"],
                    output_path=path,
                )
                self.assertTrue(result["success"], result.get("message"))
                self.assertEqual(result["count"], 1)
                with open(path, encoding="utf-8") as fh:
                    content = fh.read()
                self.assertIn(officer_a["name"], content)
                self.assertNotIn(officer_b["name"], content)


if __name__ == "__main__":
    unittest.main()
