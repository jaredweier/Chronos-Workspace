"""Staffing insights: conflicts, economics, demand, memo."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class StaffingInsightsTests(unittest.TestCase):
    def test_conflict_n_below_247(self):
        from logic.staffing_insights import detect_constraint_conflicts

        r = detect_constraint_conflicts({"use_officers": True, "officers": "3", "use_247": True, "cov247": "5"})
        self.assertFalse(r.get("ok"))
        self.assertTrue(r.get("blocking"))

    def test_lean_weekend_warning(self):
        from logic.staffing_insights import detect_constraint_conflicts

        r = detect_constraint_conflicts(
            {
                "use_officers": True,
                "officers": "7",
                "use_247": True,
                "cov247": "1",
                "use_windows": True,
                "windows": [{"min_officers": 2, "enabled": True}],
                "use_length": True,
                "length": "8",
                "allow_offday": False,
            }
        )
        self.assertTrue(r.get("ok"))  # warning not hard
        self.assertTrue(any("8 officers" in w.get("message", "") for w in r.get("warnings") or []))

    def test_enrich_economics(self):
        from logic.staffing_insights import enrich_option_economics

        row = {
            "num_officers": 8,
            "shift_length_hours": 8.0,
            "rotation_variations": ["6-2,5-3"],
            "metrics": {"hard_constraints_ok": True, "avg_annual_hours": 2008},
        }
        e = enrich_option_economics(row)
        self.assertIn("economics", e)
        self.assertIn("est_ot_cost_usd", e["economics"])
        self.assertIn("flsa_period_pct", e["economics"])
        self.assertIn("fairness_score", e["economics"])

    def test_demand_templates(self):
        from logic.staffing_insights import get_demand_template, list_demand_templates

        self.assertGreaterEqual(len(list_demand_templates()), 2)
        wins = get_demand_template("fri_sat_night")
        self.assertEqual(len(wins), 2)
        self.assertEqual(wins[0]["start_time"], "19:00")

    def test_staffing_memo(self):
        from logic.staffing_insights import export_staffing_memo

        r = export_staffing_memo(
            result={
                "metrics": {"hard_constraints_ok": True, "avg_annual_hours": 2008},
                "simulation_config": {"num_officers": 8, "shift_length_hours": 8},
            },
            ranked=[
                {
                    "rank": 1,
                    "num_officers": 8,
                    "shift_starts": ["06:00", "14:00"],
                    "economics": {
                        "est_ot_hours_total": 10,
                        "est_ot_cost_usd": 525,
                        "flsa_period_pct": 90,
                        "fairness_score": 88,
                    },
                }
            ],
        )
        self.assertTrue(r.get("success"), r)
        self.assertTrue(Path(r["path"]).is_file())
        self.assertIn("CHRONOS STAFFING MEMO", r.get("text") or "")

    def test_manual_nearby_seed(self):
        from logic.manual_schedule_build import seed_grid_with_nearby_hops

        r = seed_grid_with_nearby_hops(
            num_officers=6,
            num_days=14,
            shift_starts=["06:00", "14:00", "19:00", "22:00"],
            rotation_type="2-2-3 (14-day)",
            rotation_variations=["6-2,5-3", "6-3,5-2"],
            nearby_hops=1,
        )
        self.assertTrue(r.get("success"), r)
        self.assertIn("nearby", (r.get("message") or "").lower())

    def test_cycle_cell(self):
        from logic.manual_schedule_build import cycle_cell_start, empty_grid

        g = empty_grid(2, 3)
        r = cycle_cell_start(g, 0, 0, ["06:00", "14:00"])
        self.assertEqual(r.get("value"), "06:00")
        r2 = cycle_cell_start(g, 0, 0, ["06:00", "14:00"])
        self.assertEqual(r2.get("value"), "14:00")
        r3 = cycle_cell_start(g, 0, 0, ["06:00", "14:00"])
        self.assertEqual(r3.get("value"), "OFF")

    def test_court_board_to_windows(self):
        from logic.staffing_insights import court_board_to_demand_windows

        r = court_board_to_demand_windows()
        self.assertTrue(r.get("success"), r)
        self.assertIn("windows", r)

    def test_economics_comp_cap_fields(self):
        from logic.staffing_insights import enrich_option_economics

        e = enrich_option_economics(
            {
                "num_officers": 8,
                "shift_length_hours": 8.0,
                "rotation_variations": ["6-2,5-3"],
                "metrics": {},
            }
        )
        econ = e.get("economics") or {}
        self.assertIn("comp_cap_hours", econ)
        self.assertIn("force_cash_ot_path", econ)
        self.assertIn("ot_pay_mode", econ)

    def test_compare_quick_depth(self):
        import time

        from logic.scheduling_sim import compare_shift_length_scenarios

        t0 = time.time()
        # Annual is required (no baked product default) — test fixture only
        r = compare_shift_length_scenarios(
            lengths=[8.0, 10.0],
            officer_count=8,
            annual_hours_target=2008,
            annual_hours_variance=40,
            simulation_days=21,
            depth="quick",
            require_hard_ok=True,
        )
        elapsed = time.time() - t0
        self.assertTrue(r.get("success") or r.get("comparisons"), r)
        self.assertEqual(r.get("depth"), "quick")
        # Quick keeps multi-block quality (not stripped to 1 var)
        self.assertIn("quick", (r.get("message") or "").lower())
        # Soft wall bound
        self.assertLess(elapsed, 120.0)
        # At least one comparison row with economics when successful
        for c in r.get("comparisons") or []:
            if c.get("success"):
                self.assertTrue(c.get("economics") is not None or c.get("hard_ok") is not None)
                break


if __name__ == "__main__":
    unittest.main()
