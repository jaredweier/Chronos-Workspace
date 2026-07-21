"""Stage wizard — pause after feasibility stages."""

from __future__ import annotations

import unittest


class StageWizardTests(unittest.TestCase):
    def test_run_stages_only_returns_wizard_pause(self):
        from logic.staffing_stage_wizard import run_stages_only

        r = run_stages_only(
            officer_counts=[6, 7, 8],
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
            require_hard_ok=True,
        )
        self.assertTrue(r.get("success"))
        self.assertTrue(r.get("wizard_pause"))
        self.assertGreaterEqual(len(r.get("stage_report") or []), 3)
        self.assertIn("bound_axes", r)
        self.assertTrue(r.get("bound_axes", {}).get("officer_counts"))

    def test_scheduling_sim_export(self):
        from logic.scheduling_sim import run_staffing_stage_wizard

        r = run_staffing_stage_wizard(
            officer_counts=[8],
            shift_length_hours=8.0,
            annual_hours_target=2008.0,
            shift_starts=["06:00", "14:00", "22:00"],
            free_starts=False,
            coverage_247=1,
            rotation_style="rotating",
            rotation_variations=["6-2,5-3"],
        )
        self.assertTrue(r.get("wizard_pause"))
        self.assertTrue(r.get("success"))


if __name__ == "__main__":
    unittest.main()
