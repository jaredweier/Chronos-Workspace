"""Unit tests for coverage heat + officer Gantt builders."""

from __future__ import annotations

import unittest

from logic.sim_visuals import coverage_band_heatmap, officer_duty_gantt, side_by_side_compare


class SimVisualsTests(unittest.TestCase):
    def test_coverage_band_heatmap_from_days(self):
        result = {
            "min_per_shift": 1,
            "coverage_by_day": [
                {
                    "date": "7/21/26",
                    "working_officers": 3,
                    "high_risk_night": False,
                    "shift_counts": {"06:00": 1, "14:00": 1, "22:00": 0},
                },
                {
                    "date": "7/22/26",
                    "working_officers": 4,
                    "high_risk_night": True,
                    "shift_counts": {"06:00": 2, "14:00": 1, "22:00": 1},
                },
            ],
        }
        hm = coverage_band_heatmap(result)
        self.assertTrue(hm["success"])
        self.assertEqual(hm["starts"], ["06:00", "14:00", "22:00"])
        self.assertEqual(len(hm["rows"]), 2)
        # Empty night band is short when min_per_shift=1
        night0 = hm["rows"][0]["cells"][2]
        self.assertEqual(night0["count"], 0)
        self.assertIn(night0["level"], ("short", "empty"))

    def test_officer_gantt_from_work_flags(self):
        result = {
            "coverage_by_day": [{"date": "7/21/26"}, {"date": "7/22/26"}, {"date": "7/23/26"}],
            "officer_slots": [
                {
                    "label": "Officer 1",
                    "shift_start": "06:00",
                    "squad": "A",
                    "work_flags": [True, False, True],
                    "work_days_in_sim": 2,
                },
                {
                    "label": "Officer 2",
                    "shift_start": "22:00",
                    "squad": "B",
                    "work_flags": [False, True, True],
                    "work_days_in_sim": 2,
                },
            ],
        }
        g = officer_duty_gantt(result)
        self.assertTrue(g["success"])
        self.assertTrue(g["has_duty_flags"])
        self.assertEqual(len(g["rows"]), 2)
        self.assertTrue(g["rows"][0]["cells"][0]["on"])
        self.assertFalse(g["rows"][0]["cells"][1]["on"])
        # Night start uses command blue
        self.assertEqual(g["rows"][1]["cells"][1]["color"], "#3B7DD8")

    def test_sim_result_attaches_work_flags(self):
        from simulator import SimulatorConfig, simulate_schedule

        cfg = SimulatorConfig(
            rotation_type="2-2-3 (14-day)",
            num_officers=6,
            shift_length_hours=8.0,
            annual_hours_target=2008,
            shift_starts=["06:00", "14:00", "22:00"],
            min_per_shift=1,
            simulation_days=14,
            auto_min_officers=False,
            apply_department_rules=False,
            coverage_247=1,
        )
        r = simulate_schedule(cfg)
        self.assertTrue(r.success, r.message)
        self.assertTrue(r.officer_slots)
        flags = r.officer_slots[0].work_flags
        self.assertEqual(len(flags), 14)
        self.assertTrue(any(flags))
        payload = {
            "coverage_by_day": r.coverage_by_day,
            "officer_slots": [s.__dict__ for s in r.officer_slots],
            "metrics": r.metrics,
            "min_per_shift": 1,
        }
        hm = coverage_band_heatmap(payload)
        g = officer_duty_gantt(payload)
        self.assertTrue(hm["success"])
        self.assertTrue(g["success"])
        self.assertTrue(g["has_duty_flags"])

    def test_side_by_side(self):
        cards = side_by_side_compare(
            [
                {"metrics": {"hard_constraints_ok": True, "avg_annual_hours": 2000}, "num_officers": 8},
                {"metrics": {"hard_constraints_ok": False}, "best": {"num_officers": 7}},
            ],
            labels=["A", "B"],
        )
        self.assertEqual(len(cards["cards"]), 2)
        self.assertEqual(cards["cards"][0]["label"], "A")


if __name__ == "__main__":
    unittest.main()
