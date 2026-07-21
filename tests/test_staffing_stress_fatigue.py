"""Unit tests for absence_stress_test and option_fatigue_score."""

from __future__ import annotations

import unittest

from logic.staffing_insights import absence_stress_test, option_fatigue_score


class AbsenceStressTests(unittest.TestCase):
    def test_too_few_officers_fails_cleanly(self):
        out = absence_stress_test({"num_officers": 1})
        self.assertFalse(out["survives_one_out"])
        self.assertFalse(out["success"])

    def test_reevaluates_at_n_minus_one(self):
        row = {
            "num_officers": 8,
            "shift_length_hours": 8.0,
            "shift_starts": ["06:00", "14:00", "22:00"],
            "rotation_type": "6-2",
            "rotation_style": "rotating",
            "rotation_variations": ["6-2"],
        }
        out = absence_stress_test(row, {"simulation_days": 28, "coverage_247": 1})
        self.assertTrue(out["success"], out.get("message"))
        self.assertEqual(out["n_tested"], 7)
        self.assertIn("survives_one_out", out)
        self.assertIn("shortfalls", out)

    def test_thin_roster_does_not_survive(self):
        # 2 officers on 24/7 min 1 cannot lose one and still cover around the clock
        row = {
            "num_officers": 2,
            "shift_length_hours": 8.0,
            "shift_starts": ["06:00", "14:00", "22:00"],
            "rotation_type": "6-2",
            "rotation_style": "rotating",
            "rotation_variations": ["6-2"],
        }
        out = absence_stress_test(row, {"simulation_days": 14, "coverage_247": 1})
        self.assertTrue(out["success"], out.get("message"))
        self.assertFalse(out["survives_one_out"])


class FatigueScoreTests(unittest.TestCase):
    def test_gentle_pattern_scores_high(self):
        out = option_fatigue_score(
            {
                "shift_length_hours": 8.0,
                "rotation_variations": ["5-2"],
                "shift_starts": ["06:00", "14:00"],
            }
        )
        self.assertTrue(out["success"])
        self.assertGreaterEqual(out["score"], 75)
        self.assertEqual(out["risk_band"], "low")

    def test_brutal_pattern_scores_low_with_flags(self):
        out = option_fatigue_score(
            {
                "shift_length_hours": 12.5,
                "rotation_variations": ["7-1"],
                "shift_starts": ["19:00", "22:00"],
            }
        )
        self.assertLess(out["score"], 60)
        self.assertTrue(out["flags"])
        self.assertIn(out["risk_band"], ("moderate", "high"))

    def test_score_bounded_0_100(self):
        out = option_fatigue_score(
            {
                "shift_length_hours": 12.5,
                "rotation_variations": ["13-1"],
                "shift_starts": ["19:00", "23:00", "01:00"],
            }
        )
        self.assertGreaterEqual(out["score"], 0)
        self.assertLessEqual(out["score"], 100)


if __name__ == "__main__":
    unittest.main()
