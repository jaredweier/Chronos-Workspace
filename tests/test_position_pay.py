import unittest

from config import DEFAULT_ANNUAL_HOURS, OFFICER_TITLE_OPTIONS, SALARY_ANNUAL_HOURS
from tests.helpers import get_any_officer, test_database
from validators import (
    monthly_pay_to_hourly,
    position_amount_to_hourly,
    validate_position_pay_entry,
)


class PositionPayTests(unittest.TestCase):
    def test_hourly_monthly_yearly_conversion(self):
        self.assertEqual(position_amount_to_hourly(32.0, "hourly"), 32.0)
        self.assertAlmostEqual(
            position_amount_to_hourly(5200.0, "monthly"),
            monthly_pay_to_hourly(5200.0),
            places=2,
        )
        self.assertAlmostEqual(
            position_amount_to_hourly(93600.0, "yearly", SALARY_ANNUAL_HOURS),
            93600.0 / SALARY_ANNUAL_HOURS,
            places=2,
        )
        self.assertEqual(DEFAULT_ANNUAL_HOURS, 2008.0)

    def test_monthly_to_per_pay_period(self):
        with test_database():
            import logic

            periods = logic.count_pay_periods_in_year(2027)
            self.assertGreaterEqual(periods, 24)
            per_period = logic.monthly_pay_to_per_pay_period(5000.0, 2027)
            self.assertAlmostEqual(per_period, 5000.0 * 12 / periods, places=2)

    def test_yearly_salary_titles(self):
        with test_database():
            import logic
            from validators import is_yearly_salary_title  # noqa: F401 — used below

            self.assertTrue(is_yearly_salary_title("Chief"))
            self.assertTrue(is_yearly_salary_title("Lieutenant"))
            self.assertFalse(is_yearly_salary_title("Administrative Assistant"))
            loaded = logic.get_position_pay_rates()
            chief = loaded["rates"]["Chief"]
            lt = loaded["rates"]["Lieutenant"]
            self.assertEqual(chief["pay_basis"], "yearly")
            self.assertEqual(lt["pay_basis"], "yearly")
            self.assertEqual(chief["annual_hours"], SALARY_ANNUAL_HOURS)
            self.assertEqual(lt["annual_hours"], SALARY_ANNUAL_HOURS)
            self.assertAlmostEqual(chief["hourly_equivalent"], 93600.0 / SALARY_ANNUAL_HOURS, places=2)
            self.assertAlmostEqual(lt["hourly_equivalent"], 80400.0 / SALARY_ANNUAL_HOURS, places=2)

    def test_validate_position_pay_entry(self):
        self.assertTrue(validate_position_pay_entry("Sergeant", 6280.0, "monthly").ok)
        self.assertTrue(validate_position_pay_entry("Chief", 93600, "yearly", is_salary=True).ok)
        self.assertTrue(validate_position_pay_entry("Lieutenant", 80400, "yearly", is_salary=True).ok)
        self.assertFalse(validate_position_pay_entry("Captain", 40, "hourly").ok)

    def test_save_and_load_position_pay_rates(self):
        with test_database():
            import logic

            payload = {
                title: {
                    "amount": 5000.0 + idx * 100,
                    "pay_basis": "monthly",
                    "is_salary": False,
                }
                for idx, title in enumerate(OFFICER_TITLE_OPTIONS)
            }
            result = logic.save_position_pay_rates(payload)
            self.assertTrue(result["success"], result.get("message"))
            loaded = logic.get_position_pay_rates()
            self.assertEqual(loaded["rates"]["Officer"]["amount"], 5000.0)
            self.assertIn("per_pay_period_amount", loaded["rates"]["Officer"])
            self.assertAlmostEqual(
                loaded["rates"]["Officer"]["hourly_equivalent"],
                position_amount_to_hourly(5000.0, "monthly"),
                places=2,
            )

    def test_apply_position_rates_to_roster(self):
        with test_database():
            import logic

            logic.save_position_pay_rates(
                {
                    "Officer": {"amount": 5200.0, "pay_basis": "monthly", "is_salary": False},
                }
            )
            officer = get_any_officer("A")
            logic.update_officer(officer["id"], job_title="Officer", pay_rate=20.0)
            result = logic.apply_position_pay_rates_to_roster()
            self.assertTrue(result["success"])
            self.assertGreaterEqual(result["updated"], 1)
            refreshed = logic.get_officer_by_id(officer["id"])
            expected = position_amount_to_hourly(5200.0, "monthly")
            self.assertAlmostEqual(refreshed["pay_rate"], expected, places=2)

    def test_custom_title_annual_hours(self):
        with test_database():
            import logic

            logic.add_custom_officer_title("K9 Handler")
            result = logic.save_position_pay_rates(
                {
                    "K9 Handler": {
                        "amount": 45.0,
                        "pay_basis": "hourly",
                        "is_salary": False,
                        "annual_hours": 1920.0,
                    },
                }
            )
            self.assertTrue(result["success"], result.get("message"))
            loaded = logic.get_position_pay_rates()
            entry = loaded["rates"]["K9 Handler"]
            self.assertEqual(entry["annual_hours"], 1920.0)
            self.assertEqual(entry["hourly_equivalent"], 45.0)

    def test_apply_position_rates_sets_annual_hours(self):
        with test_database():
            import logic

            logic.save_position_pay_rates(
                {
                    "Lieutenant": {
                        "amount": 80400.0,
                        "pay_basis": "yearly",
                        "is_salary": True,
                        "annual_hours": 2080.0,
                    },
                }
            )
            officer = get_any_officer("A")
            logic.update_officer(officer["id"], job_title="Lieutenant", annual_hours_target=2000.0)
            logic.apply_position_pay_rates_to_roster()
            refreshed = logic.get_officer_by_id(officer["id"])
            self.assertEqual(refreshed["annual_hours_target"], 2080.0)

    def test_suggested_hourly_rate_for_title(self):
        with test_database():
            import logic

            logic.save_position_pay_rates({"Sergeant": {"amount": 6280.0, "pay_basis": "monthly", "is_salary": False}})
            hourly = logic.suggested_hourly_rate_for_title("Sergeant")
            self.assertAlmostEqual(hourly, position_amount_to_hourly(6280.0, "monthly"), places=2)


if __name__ == "__main__":
    unittest.main()
