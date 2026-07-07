import json
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.helpers import test_database


class RotationConfigTests(unittest.TestCase):
    def setUp(self):
        self._db_cm = test_database()
        self._db_cm.__enter__()
        import logic

        self.logic = logic

    def tearDown(self):
        self._db_cm.__exit__(None, None, None)

    def test_default_matches_config_constants(self):
        from config import ROTATION_BASE_DATE, ROTATION_CYCLE_LENGTH
        from logic.rotation_config import (
            get_active_rotation_base_date,
            get_active_rotation_cycle_length,
            get_squad_on_duty,
        )

        self.assertEqual(get_active_rotation_cycle_length(), ROTATION_CYCLE_LENGTH)
        self.assertEqual(get_active_rotation_base_date(), ROTATION_BASE_DATE)
        self.assertEqual(get_squad_on_duty(1), "A")
        self.assertEqual(get_squad_on_duty(3), "B")

    def test_custom_cycle_length_used_by_scheduling(self):
        self.logic.set_department_setting("rotation_cycle_length", "21")

        self.assertEqual(self.logic.get_active_rotation_cycle_length(), 21)
        start, end = self.logic.get_current_cycle_window(date(2026, 7, 10))
        self.assertEqual((end - start).days + 1, 21)
        self.assertEqual(self.logic.get_cycle_day(date(2026, 7, 10)), 13)

    def test_custom_squad_a_days(self):
        days = json.dumps([1, 2, 3, 4, 5, 6, 7])
        self.logic.set_department_setting("rotation_preset", "Panama 12-hour")
        self.logic.set_department_setting("rotation_squad_a_days", days)

        from logic import rust_bridge
        from logic.rotation_config import get_squad_on_duty

        self.assertEqual(get_squad_on_duty(5), "A")
        self.assertEqual(get_squad_on_duty(8), "B")
        if rust_bridge.available():
            self.assertEqual(rust_bridge.get_squad_on_duty(5), "A")
            self.assertEqual(rust_bridge.get_squad_on_duty(8), "B")

    def test_custom_base_date_blocks_earlier_requests(self):
        self.logic.set_department_setting("rotation_base_date", "2026-07-01")

        from validators import validate_cycle_date

        before = validate_cycle_date(date(2026, 6, 28))
        self.assertFalse(before.ok)
        after = validate_cycle_date(date(2026, 7, 5))
        self.assertTrue(after.ok)

    def test_flsa_period_independent_of_rotation_cycle(self):
        from config import FLSA_207K_WORK_PERIOD_DAYS
        from logic.labor_compliance import get_flsa_work_period_days

        self.logic.set_department_setting("rotation_cycle_length", "21")
        self.logic.set_department_setting("flsa_work_period_days", "")
        self.assertEqual(get_flsa_work_period_days(), FLSA_207K_WORK_PERIOD_DAYS)

        self.logic.set_department_setting("flsa_work_period_days", "21")
        self.assertEqual(get_flsa_work_period_days(), 21)

    def test_save_rotation_settings_applies_to_scheduling(self):
        from logic.rotation_config import save_rotation_settings

        result = save_rotation_settings(
            cycle_length=21,
            preset="Panama 12-hour",
            base_date_text="01-07-2026",
            squad_a_days_text="1,2,3,4,5,6,7",
        )
        self.assertTrue(result.get("success"), result.get("message"))

        self.assertEqual(self.logic.get_active_rotation_cycle_length(), 21)
        self.assertEqual(self.logic.get_cycle_day(date(2026, 7, 8)), 8)
        self.assertEqual(self.logic.get_squad_on_duty(8), "B")

        officers = self.logic.get_officers_by_seniority()
        squad_a = next(o for o in officers if o["squad"] == "A")
        self.assertTrue(self.logic.is_officer_working_on_day(squad_a["id"], date(2026, 7, 1)))
        self.assertFalse(self.logic.is_officer_working_on_day(squad_a["id"], date(2026, 7, 8)))

    def test_save_rotation_rejects_invalid_preset(self):
        from logic.rotation_config import save_rotation_settings

        result = save_rotation_settings(cycle_length=14, preset="Not A Real Preset")
        self.assertFalse(result.get("success"))


if __name__ == "__main__":
    unittest.main()