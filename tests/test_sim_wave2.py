"""Wave 2: Pareto, counterfactuals, fatigue, FLSA meters, what-if."""

from __future__ import annotations

import unittest

from logic.sim_wave2 import (
    annotate_pareto_shortlist,
    counterfactual_unlocks,
    enrich_wave2_result,
    fatigue_advisory,
    multi_period_flsa_meters,
    soft_rank_delta,
    whatif_sandbox,
)


class SimWave2Tests(unittest.TestCase):
    def test_pareto_labels(self):
        rows = [
            {
                "hard_constraints_ok": True,
                "num_officers": 7,
                "economics": {"est_ot_hours_total": 20, "fairness_score": 70},
                "rank": 1,
            },
            {
                "hard_constraints_ok": True,
                "num_officers": 9,
                "economics": {"est_ot_hours_total": 5, "fairness_score": 90},
                "rank": 2,
            },
            {"hard_constraints_ok": False, "num_officers": 6, "economics": {}, "rank": 3},
        ]
        out = annotate_pareto_shortlist(rows)
        labels0 = " ".join(out[0].get("pareto_labels") or [])
        labels1 = " ".join(out[1].get("pareto_labels") or [])
        self.assertIn("min N", labels0)
        self.assertIn("min OT", labels1)
        self.assertIn("max fairness", labels1)
        self.assertEqual(out[2].get("pareto_labels"), [])

    def test_soft_rank_delta(self):
        a = {"hard_constraints_ok": True, "num_officers": 7, "soft_score": 80, "economics": {"est_ot_hours_total": 10}}
        b = {"hard_constraints_ok": True, "num_officers": 9, "soft_score": 60, "economics": {"est_ot_hours_total": 20}}
        d = soft_rank_delta(a, b)
        self.assertIn("fewer officers", d)

    def test_counterfactual_from_near_miss(self):
        r = {
            "success": False,
            "impossible": True,
            "near_misses": [
                {
                    "hard_constraints_ok": False,
                    "num_officers": 6,
                    "metrics": {"extra_window_failures": 3, "coverage_247_failures": 0},
                }
            ],
        }
        cards = counterfactual_unlocks(r, {"officers": 6})
        self.assertTrue(cards)
        self.assertTrue(any("officer" in (c.get("action") or "").lower() for c in cards))

    def test_fatigue_advisory(self):
        row = {
            "shift_length_hours": 12.0,
            "rotation_variations": ["6-2,5-3"],
            "metrics": {},
            "shift_starts": ["06:00", "14:00", "22:00"],
        }
        fat = fatigue_advisory(row)
        self.assertIn("fatigue_score", fat)
        self.assertLess(fat["fatigue_score"], 100)

    def test_flsa_meters(self):
        meters = multi_period_flsa_meters(shift_length_hours=8.0, duty_fraction=0.5, periods=(7, 14, 28))
        self.assertEqual(len(meters), 3)
        self.assertEqual(meters[-1]["period_days"], 28)
        self.assertAlmostEqual(meters[-1]["threshold_hours"], 171.0)

    def test_whatif_sandbox(self):
        r = whatif_sandbox(
            {"num_officers": 4, "coverage_247": 2, "shift_starts": ["06:00", "14:00", "22:00"]},
            delta_n=2,
        )
        self.assertTrue(r["success"])
        self.assertIn("narrative", r)
        self.assertEqual(r["form"].get("num_officers"), 6)

    def test_enrich_wave2(self):
        result = {
            "success": True,
            "ranked": [
                {
                    "hard_constraints_ok": True,
                    "num_officers": 8,
                    "shift_length_hours": 8.0,
                    "rotation_variations": ["6-2,5-3"],
                    "metrics": {"hard_constraints_ok": True, "annual_hours_spread": 10},
                },
                {
                    "hard_constraints_ok": True,
                    "num_officers": 9,
                    "shift_length_hours": 8.0,
                    "rotation_variations": ["6-2,5-3"],
                    "metrics": {"hard_constraints_ok": True},
                },
            ],
        }
        out = enrich_wave2_result(result, {})
        self.assertTrue(out["ranked"][0].get("pareto_labels") is not None)
        self.assertIn("soft_rank_delta", out)


if __name__ == "__main__":
    unittest.main()
