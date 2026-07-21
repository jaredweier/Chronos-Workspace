"""Wave B: staged feasibility search — constraints first, not score."""

from __future__ import annotations

import unittest


class StaffingSearchStagesTests(unittest.TestCase):
    def test_multi_pattern_split_includes_four_two(self):
        from logic.staffing_search_stages import multi_pattern_split_maps

        maps = multi_pattern_split_maps(6, 2)
        self.assertTrue(maps)
        # 4 on pattern 0, 2 on pattern 1 (or reverse) — example mix, not a rule
        splits = {(m.count(0), m.count(1)) for m in maps}
        self.assertIn((4, 2), splits)
        self.assertIn((2, 4), splits)
        self.assertIn((3, 3), splits)

    def test_stages_shrink_n_for_247(self):
        from logic.staffing_search_stages import run_feasibility_stages

        axes = {
            "officer_counts": [2, 3, 4, 5, 6, 7, 8],
            "length_opts": [8.0],  # ceil(24/8)×1 = 3 bodies for 24/7 min 1
            "variation_sets": [["6-2,5-3", "6-3,5-2"]],
            "rotation_types": ["2-2-3 (14-day)"],
            "min_per_shift_options": [1],
            "style": "rotating",
            "base_variations": ["6-2,5-3", "6-3,5-2"],
            "free_starts": True,
            "locked_starts_opts": None,
            "staffing": {},
        }
        out, outcomes, tips = run_feasibility_stages(
            axes,
            annual=2008.0,
            annual_variance=40.0,
            annual_hours_hard=False,
            coverage_247=1,
            use_extra_windows=False,
            extra_windows=[],
        )
        self.assertTrue(outcomes)
        self.assertEqual(len(outcomes), 5)
        ns = out["officer_counts"]
        self.assertTrue(all(n >= 3 for n in ns), ns)
        self.assertNotIn(2, ns)
        self.assertTrue(any("24/7" in t or "body" in t.lower() for t in tips) or any(o.reasons for o in outcomes))

    def test_mixed_cycle_variation_sets_dropped(self):
        from logic.staffing_search_stages import stage_rotation_shape

        # 5-2 is 7-day cycle; 6-2,5-3 is 16-day — must not mix in one set
        axes = {
            "officer_counts": [6],
            "length_opts": [8.0],
            "variation_sets": [["6-2,5-3", "5-2"], ["6-2,5-3", "6-3,5-2"]],
            "rotation_types": ["2-2-3 (14-day)"],
            "min_per_shift_options": [1],
            "style": "rotating",
            "base_variations": ["6-2,5-3"],
            "free_starts": False,
            "locked_starts_opts": [["06:00", "14:00", "22:00"]],
            "staffing": {},
        }
        out, outcome = stage_rotation_shape(axes)
        self.assertTrue(outcome.ok)
        for vs in out["variation_sets"]:
            if not vs:
                continue
            # remaining multi sets must share cycle length
            from logic.rotation_patterns import build_pattern

            cycles = {build_pattern(t, style="rotating").cycle_length for t in vs}
            self.assertEqual(len(cycles), 1, vs)

    def test_feasibility_sort_prefers_hard_ok_and_lower_n(self):
        from logic.staffing_search_stages import feasibility_sort_key

        a = {
            "hard_constraints_ok": True,
            "num_officers": 8,
            "metrics": {"coverage_247_failures": 0, "extra_window_failures": 0, "gap_events": 0},
            "score": 50,
        }
        b = {
            "hard_constraints_ok": True,
            "num_officers": 6,
            "metrics": {"coverage_247_failures": 0, "extra_window_failures": 0, "gap_events": 0},
            "score": 10,
        }
        c = {
            "hard_constraints_ok": False,
            "num_officers": 4,
            "metrics": {"coverage_247_failures": 2, "extra_window_failures": 0, "gap_events": 0},
            "score": 999,
        }
        rows = sorted([a, b, c], key=lambda r: feasibility_sort_key(r, annual=2008))
        self.assertTrue(rows[0]["hard_constraints_ok"])
        self.assertEqual(rows[0]["num_officers"], 6)
        self.assertFalse(rows[-1]["hard_constraints_ok"])

    def test_optimize_includes_stage_report_on_cancel(self):
        """Full optimize is heavy — cancel immediately after stages via cancel_check."""
        from logic.staffing_optimizer import optimize_staffing_scenarios

        calls = {"n": 0}

        def _cancel():
            # Allow stages (no cancel during stage progress), then cancel sim loop
            calls["n"] += 1
            return calls["n"] > 8

        result = optimize_staffing_scenarios(
            officer_counts=[6],
            shift_length_hours=8.0,
            annual_hours_target=2008.0,
            annual_hours_variance=40.0,
            annual_hours_hard=False,
            shift_starts=["06:00", "14:00", "22:00"],
            free_starts=False,
            free_lengths=False,
            free_officer_counts=False,
            free_variations=False,
            rotation_style="rotating",
            rotation_variations=["6-2,5-3", "6-3,5-2"],
            coverage_247=1,
            use_extra_windows=False,
            simulation_days=14,
            require_hard_ok=True,
            search_depth="standard",
            cancel_check=_cancel,
        )
        self.assertIn("stage_report", result)
        self.assertGreaterEqual(len(result.get("stage_report") or []), 3)
        self.assertEqual(
            (result.get("constraints_applied") or {}).get("search_architecture"),
            "staged_feasibility",
        )
        self.assertTrue(result.get("stage_tips") is not None)


if __name__ == "__main__":
    unittest.main()
