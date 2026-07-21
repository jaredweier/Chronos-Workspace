"""P11–P18 horizon pack unit tests."""

from __future__ import annotations

import unittest

from logic.horizon_pack import (
    gantt_duty_delta,
    non_dominated_shortlist,
    open_shift_deputy_from_sim,
    ot_ledger_vs_flsa,
    scenario_story_cards,
    structured_conflict_report,
)


class HorizonPackTests(unittest.TestCase):
    def test_non_dominated(self):
        ranked = [
            {
                "rank": 1,
                "hard_constraints_ok": True,
                "num_officers": 7,
                "economics": {"est_ot_hours_total": 20, "fairness_score": 70},
            },
            {
                "rank": 2,
                "hard_constraints_ok": True,
                "num_officers": 9,
                "economics": {"est_ot_hours_total": 5, "fairness_score": 90},
            },
            {"rank": 3, "hard_constraints_ok": False, "num_officers": 6, "economics": {}},
        ]
        nd = non_dominated_shortlist(ranked)
        self.assertGreaterEqual(nd["count"], 1)
        self.assertTrue(nd["chips"])

    def test_structured_conflicts(self):
        r = {
            "impossible": True,
            "failure_histogram": {"coverage_247": 10, "windows": 5},
            "metrics": {},
        }
        rep = structured_conflict_report(r)
        self.assertIn("C_247", rep["conflict_ids"])
        self.assertIn("C_WINDOWS", rep["conflict_ids"])

    def test_scenario_stories(self):
        cards = scenario_story_cards({"num_officers": 6, "coverage_247": 1})
        self.assertTrue(cards["cards"])
        self.assertTrue(any("If we" in (c.get("title") or "") for c in cards["cards"]))

    def test_gantt_delta(self):
        res = {
            "officer_slots": [
                {"label": "A", "shift_start": "06:00", "work_flags": [True, False, True]},
                {"label": "B", "shift_start": "22:00", "work_flags": [True, True, False]},
            ],
            "coverage_by_day": [{"date": "7/1/26"}, {"date": "7/2/26"}, {"date": "7/3/26"}],
        }
        out = gantt_duty_delta(res, slot_index=0, day_index=1, set_on=True)
        self.assertTrue(out["success"])
        self.assertTrue(out["after_on"])
        self.assertEqual(out["delta_bodies"], 1)

    def test_deputy_from_sim(self):
        r = open_shift_deputy_from_sim(
            {
                "metrics": {"min_per_shift": 2},
                "coverage_by_day": [
                    {
                        "date": "7/24/26",
                        "high_risk_night": True,
                        "shift_counts": {"22:00": 1, "06:00": 2},
                    }
                ],
                "shift_length_hours": 8,
            },
            start_date="7/24/26",
        )
        self.assertTrue(r.get("candidates") is not None)

    def test_ot_flsa_bridge(self):
        bridge = ot_ledger_vs_flsa(
            {"shift_length_hours": 8, "rotation_variations": ["6-2,5-3"]},
            flsa_period_days=28,
        )
        self.assertTrue(bridge["success"])
        self.assertTrue(bridge.get("sim_flsa_meters"))


if __name__ == "__main__":
    unittest.main()
