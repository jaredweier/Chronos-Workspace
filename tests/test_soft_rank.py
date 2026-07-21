"""Soft rank among hard-OK only — never promote hard-fail."""

from __future__ import annotations

import unittest

from logic.soft_rank import (
    apply_soft_rank_to_result,
    default_soft_prefs,
    rank_soft_among_feasible,
    soft_components,
)


class SoftRankTests(unittest.TestCase):
    def _ok_row(self, n: int, spread: float, night_spread: int = 0, **extra):
        flags_a = [True, False, True, False] + [False] * 10
        flags_b = [True, True, True, True] + [False] * 10 if night_spread else flags_a
        return {
            "hard_constraints_ok": True,
            "num_officers": n,
            "shift_starts": ["06:00", "14:00", "22:00"],
            "metrics": {"annual_hours_spread": spread, "hard_constraints_ok": True},
            "economics": {"est_ot_hours_total": float(extra.get("ot", 10)), "fairness_score": 80},
            "officer_slots": [
                {"label": "A", "shift_start": "22:00", "work_flags": flags_a},
                {"label": "B", "shift_start": "22:00", "work_flags": flags_b},
                {"label": "C", "shift_start": "06:00", "work_flags": flags_a},
            ],
            "coverage_by_day": [
                {"date": "2026-07-24", "high_risk_night": True},
                {"date": "2026-07-25", "high_risk_night": True},
            ],
            **extra,
        }

    def test_hard_fail_scores_zero(self):
        row = self._ok_row(8, 20)
        row["hard_constraints_ok"] = False
        c = soft_components(row)
        self.assertEqual(c["total"], 0.0)

    def test_fewer_officers_wins_among_hard_ok(self):
        a = self._ok_row(9, 10, ot=5)
        b = self._ok_row(7, 10, ot=5)
        prefs = default_soft_prefs()
        prefs.update(
            {
                "balance_nights": 0,
                "balance_weekends": 0,
                "fewer_officers": 2.0,
                "lower_ot": 0,
                "lower_annual_spread": 0,
                "prefer_night_starts": 0,
            }
        )
        out = rank_soft_among_feasible([a, b], prefs)
        self.assertTrue(out["soft_applied"])
        self.assertEqual(out["best"]["num_officers"], 7)
        self.assertEqual(out["ranked"][0]["num_officers"], 7)

    def test_hard_fail_never_before_hard_ok(self):
        ok = self._ok_row(8, 50)
        bad = self._ok_row(6, 0)
        bad["hard_constraints_ok"] = False
        bad["soft_score"] = 999  # poison — must not win
        out = rank_soft_among_feasible([bad, ok], default_soft_prefs())
        self.assertTrue(out["best"]["hard_constraints_ok"])
        self.assertEqual(out["ranked"][0]["hard_constraints_ok"], True)
        self.assertFalse(out["ranked"][-1]["hard_constraints_ok"])

    def test_apply_soft_rank_to_result_preserves_success(self):
        r = {
            "success": True,
            "message": "Best Option: test",
            "ranked": [self._ok_row(8, 30), self._ok_row(7, 5)],
            "best": self._ok_row(8, 30),
        }
        out = apply_soft_rank_to_result(r, default_soft_prefs())
        self.assertTrue(out["success"])
        self.assertTrue(out["soft_rank"]["applied"])
        self.assertTrue(out["best"].get("hard_constraints_ok"))
        self.assertIn("soft_score", out["ranked"][0])


if __name__ == "__main__":
    unittest.main()
