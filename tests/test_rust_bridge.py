"""Rust bridge and scheduling math parity (Python fallback always; Rust when built)."""

import unittest
from datetime import date

from config import ROTATION_BASE_DATE, ROTATION_CYCLE_LENGTH
from logic import rust_bridge


class RustBridgeTests(unittest.TestCase):
    def test_cycle_day_python_path(self):
        target = date(2026, 7, 10)
        day = rust_bridge.get_cycle_day(target, ROTATION_BASE_DATE, ROTATION_CYCLE_LENGTH)
        self.assertGreaterEqual(day, 1)
        self.assertLessEqual(day, ROTATION_CYCLE_LENGTH)

    def test_squad_on_duty(self):
        self.assertEqual(rust_bridge.get_squad_on_duty(1), "A")
        self.assertEqual(rust_bridge.get_squad_on_duty(3), "B")

    def test_backend_reports_python_when_extension_missing(self):
        if rust_bridge.available():
            self.assertEqual(rust_bridge.backend_name(), "rust")
        else:
            self.assertEqual(rust_bridge.backend_name(), "python")

    def test_rust_matches_python_cycle_day_when_built(self):
        if not rust_bridge.available():
            self.skipTest("scheduler_core extension not built")
        import scheduler_core

        iso = "2026-07-15"
        self.assertEqual(
            scheduler_core.get_cycle_day(ROTATION_BASE_DATE.isoformat(), iso, ROTATION_CYCLE_LENGTH),
            rust_bridge.get_cycle_day(date(2026, 7, 15), ROTATION_BASE_DATE, ROTATION_CYCLE_LENGTH),
        )

    def test_rust_matches_python_custom_squad_schedule_when_built(self):
        if not rust_bridge.available():
            self.skipTest("scheduler_core extension not built")
        schedule = {
            "mode": "squad_a_days",
            "cycle_length": 14,
            "squad_a_days": [1, 2, 3, 4, 5, 6, 7],
        }
        import scheduler_core

        for day in range(1, 15):
            py = "A" if day in schedule["squad_a_days"] else "B"
            rust = scheduler_core.get_squad_on_duty(day, schedule)
            self.assertEqual(rust, py, f"day {day}")


if __name__ == "__main__":
    unittest.main()
