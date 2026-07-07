import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.helpers import test_database


class StaffingConfigTests(unittest.TestCase):
    def setUp(self):
        self._db_cm = test_database()
        self._db_cm.__enter__()
        import logic

        self.logic = logic

    def tearDown(self):
        self._db_cm.__exit__(None, None, None)

    def test_defaults_match_department_standard(self):
        from config import DEFAULT_ANNUAL_HOURS, SHIFT_TIMES
        from logic.staffing_config import (
            get_active_annual_hours_target,
            get_active_shift_count,
            get_active_shift_times,
            get_officer_shift_options,
        )

        self.assertEqual(get_active_shift_count(), len(SHIFT_TIMES))
        self.assertEqual(get_active_annual_hours_target(), DEFAULT_ANNUAL_HOURS)
        self.assertEqual(set(get_active_shift_times().values()), set(SHIFT_TIMES.values()))
        self.assertEqual(len(get_officer_shift_options()), len(SHIFT_TIMES) + 1)

    def test_save_staffing_applies_to_scheduling_and_validation(self):
        from logic.staffing_config import save_staffing_settings
        from validators import validate_officer_shift

        result = save_staffing_settings(
            shift_length_hours=10.0,
            annual_hours_target=2000.0,
            shift_count=3,
            target_officer_count=12,
            shift_starts_text="06:00, 14:00, 22:00",
        )
        self.assertTrue(result.get("success"), result.get("message"))

        times = self.logic.get_active_shift_times()
        self.assertEqual(len(times), 3)
        self.assertEqual(self.logic.get_shift_number("14:00"), 2)
        self.assertTrue(validate_officer_shift("06:00", times[1][1]).ok)
        self.assertFalse(validate_officer_shift("19:00", "06:00").ok)
        self.assertEqual(self.logic.get_active_annual_hours_target(), 2000.0)
        self.assertEqual(self.logic.get_target_officer_count(), 12)

    def test_bump_rules_scale_with_shift_count(self):
        from logic.staffing_config import get_active_bump_rules_by_start, save_staffing_settings

        save_staffing_settings(
            shift_length_hours=11.0,
            annual_hours_target=2080.0,
            shift_count=3,
            target_officer_count=10,
            shift_starts_text="06:00, 14:00, 22:00",
        )
        rules = get_active_bump_rules_by_start()
        self.assertEqual(len(rules), 3)
        self.assertEqual(rules.get("14:00"), ("06:00", "22:00"))

    def test_custom_shift_starts_drive_bump_and_coverage(self):
        from logic.scheduling import resolve_officer_shift_band
        from logic.staffing_config import (
            can_officer_cover_shift,
            get_active_bump_rules_by_start,
            get_active_shift_starts_list,
            save_staffing_settings,
        )

        save_staffing_settings(
            shift_length_hours=10.0,
            annual_hours_target=2080.0,
            shift_count=3,
            target_officer_count=10,
            shift_starts_text="07:00, 13:30, 21:00",
        )
        starts = get_active_shift_starts_list()
        self.assertEqual(starts, ["07:00", "13:30", "21:00"])
        self.assertTrue(can_officer_cover_shift("13:30", "07:00"))
        self.assertFalse(can_officer_cover_shift("21:00", "07:00"))

        from tests.helpers import get_any_officer

        original = get_any_officer("A", "06:00")
        off_day = __import__("datetime").date(2026, 6, 30)
        covered_start, _ = resolve_officer_shift_band(
            original["id"],
            off_day,
            home_shift_start=original.get("shift_start"),
            home_shift_end=original.get("shift_end"),
        )
        self.assertEqual(covered_start, "07:00")
        rules = get_active_bump_rules_by_start()
        self.assertEqual(rules.get("07:00"), ("13:30",))
        self.assertEqual(rules.get("21:00"), ("13:30",))


if __name__ == "__main__":
    unittest.main()
