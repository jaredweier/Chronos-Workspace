import unittest

from tests.helpers import get_any_officer, test_database


class PayCodeRulesTests(unittest.TestCase):
    def test_default_overtime_multiplier(self):
        with test_database():
            import logic

            calc = logic.calculate_pay_for_entry("Overtime Earned", 4.0, 30.0)
            self.assertEqual(calc.overtime_pay, round(4.0 * 30.0 * 1.5, 2))

    def test_save_custom_pay_code_multiplier(self):
        with test_database():
            import logic

            result = logic.save_pay_code_rules(
                {
                    "codes": {
                        "Overtime Earned": {"rate_multiplier": 2.0},
                    }
                }
            )
            self.assertTrue(result["success"], result.get("message"))

            calc = logic.calculate_pay_for_entry("Overtime Earned", 4.0, 30.0)
            self.assertEqual(calc.overtime_pay, round(4.0 * 30.0 * 2.0, 2))

            loaded = logic.get_pay_code_rules()
            self.assertEqual(loaded["codes"]["Overtime Earned"]["rate_multiplier"], 2.0)

    def test_holiday_pay_uses_configured_multiplier(self):
        with test_database():
            import logic

            logic.save_pay_code_rules({"codes": {"Holiday Pay": {"rate_multiplier": 2.0}}})
            officer = get_any_officer("A")
            result = logic.create_payroll_entry(officer["id"], "2026-07-04", "Holiday Pay", 8.0)
            self.assertTrue(result["success"], result.get("message"))
            self.assertAlmostEqual(result["calculated_pay"], 8.0 * officer["pay_rate"] * 2.0, places=2)

    def test_callback_minimum_from_global_settings(self):
        with test_database():
            import logic

            logic.save_pay_code_rules({"global": {"callback_minimum_hours": 3.0}})
            calc = logic.calculate_pay_for_entry("Callback", 1.0, 25.0)
            self.assertEqual(calc.base_pay, round(3.0 * 25.0, 2))


if __name__ == "__main__":
    unittest.main()
