"""Unit tests for constraint autopsy + cheap feasibility strip."""

from __future__ import annotations

import unittest

from logic.constraint_autopsy import (
    cheap_feasibility_strip,
    constraint_autopsy,
    format_autopsy_lines,
    rough_min_roster,
    theoretical_body_floor,
)


class ConstraintAutopsyTests(unittest.TestCase):
    def test_body_floor_247_and_windows(self):
        self.assertEqual(
            theoretical_body_floor(coverage_247=1, window_min=2, min_per_shift=0, n_starts=3),
            2,
        )
        self.assertEqual(
            theoretical_body_floor(coverage_247=1, window_min=0, min_per_shift=1, n_starts=3),
            1,
        )

    def test_rough_roster_hint(self):
        self.assertGreaterEqual(rough_min_roster(body_floor=2, pattern_work_frac=0.5), 4)

    def test_strip_blocks_n_below_body(self):
        strip = cheap_feasibility_strip(
            {
                "num_officers": 1,
                "coverage_247": 2,
                "min_per_shift": 0,
                "shift_starts": ["06:00", "14:00", "22:00"],
            }
        )
        self.assertEqual(strip["status"], "blocked")
        self.assertEqual(strip["risk"], "high")
        self.assertTrue(any("simultaneous floor" in ln for ln in strip["lines"]))

    def test_strip_annual_plausible(self):
        strip = cheap_feasibility_strip(
            {
                "num_officers": 8,
                "shift_length_hours": 8.0,
                "annual_hours_target": 2008,
                "coverage_247": 1,
            }
        )
        self.assertIn(strip["status"], ("ok", "caution"))
        self.assertTrue(any("Annual" in ln for ln in strip["lines"]))

    def test_autopsy_from_histogram(self):
        result = {
            "success": False,
            "impossible": True,
            "require_hard_ok": True,
            "scenarios_evaluated": 120,
            "failure_histogram": {"coverage_247": 80, "windows": 40, "annual": 10},
            "near_misses": [{"summary": "near"}],
        }
        auto = constraint_autopsy(result, {"cov247": 1, "officers": 6})
        self.assertFalse(auto["hard_ok"])
        self.assertTrue(auto["reasons"])
        self.assertEqual(auto["reasons"][0]["key"], "coverage_247")
        self.assertTrue(auto["unlocks"])
        lines = format_autopsy_lines(auto)
        self.assertTrue(any("24/7" in ln or "Coverage" in ln for ln in lines))

    def test_autopsy_hard_ok_summary(self):
        auto = constraint_autopsy(
            {"success": True, "best": {"hard_constraints_ok": True, "num_officers": 8}},
            {},
        )
        self.assertTrue(auto["hard_ok"])
        self.assertIn("met", auto["summary"].lower())


if __name__ == "__main__":
    unittest.main()
