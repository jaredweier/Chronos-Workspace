import unittest

from config import OFFICER_TITLE_OPTIONS
from tests.helpers import test_database


class RosterTitleTests(unittest.TestCase):
    def test_builtin_titles(self):
        self.assertEqual(
            list(OFFICER_TITLE_OPTIONS),
            ["Officer", "Sergeant", "Investigator", "Lieutenant", "Chief"],
        )

    def test_add_custom_title(self):
        with test_database():
            import logic

            result = logic.add_custom_officer_title("Administrative Assistant")
            self.assertTrue(result["success"], result.get("message"))
            titles = logic.get_officer_title_options()
            self.assertIn("Administrative Assistant", titles)
            self.assertTrue(logic.is_assignable_officer_title("Administrative Assistant"))

    def test_admin_assistant_hourly_manual_not_yearly(self):
        with test_database():
            import logic
            from validators import is_yearly_salary_title

            logic.add_custom_officer_title("Administrative Assistant")
            self.assertFalse(is_yearly_salary_title("Administrative Assistant"))
            officer = logic.get_officers_by_seniority()[0]
            logic.update_officer(officer["id"], job_title="Administrative Assistant", pay_rate=28.5)
            refreshed = logic.get_officer_by_id(officer["id"])
            self.assertAlmostEqual(refreshed["pay_rate"], 28.5, places=2)
            self.assertIsNone(logic.suggested_hourly_rate_for_title("Administrative Assistant"))

    def test_duplicate_builtin_rejected(self):
        with test_database():
            import logic

            result = logic.add_custom_officer_title("Sergeant")
            self.assertFalse(result["success"])


if __name__ == "__main__":
    unittest.main()
