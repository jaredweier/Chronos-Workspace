"""Static UI completeness — no NiceGUI render (crash-safe).

Asserts that gui page sources wire the selectable options for new features.
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


class FeatureUiStaticTests(unittest.TestCase):
    def test_operations_off_duty_and_windows(self):
        src = _read("gui/pages/operations.py")
        for needle in (
            "Allow off-duty officers",
            "Prefer on-duty",
            "same squad only",
            "adjacent shift band",
            "Ranking criteria",
            "Save off-duty bump settings",
            "call list",
            "Reset next-up",
            ".docx",
            ".pdf",
            "import_bump_call_list_file",
            "24/7 minimum",
            "Add window",
            "coverage window",
            "fill offer order mode",
            "Save fill mode",
            "ordered-in",
        ):
            self.assertIn(needle, src)

        from logic.bump_off_duty import ALL_CRITERIA, CRITERION_LABELS

        # UI builds checkboxes from criteria_options; ensure labels exist in module used by UI
        for cid in ALL_CRITERIA:
            self.assertIn(cid, CRITERION_LABELS)
            self.assertTrue(CRITERION_LABELS[cid])

        # ops imports policy + file import
        self.assertIn("get_off_duty_bump_settings_for_ui", src)
        self.assertIn("save_off_duty_bump_policy", src)

    def test_simulator_implement_and_constraints(self):
        import glob

        src = ""
        for p in glob.glob(str(ROOT / "gui" / "pages" / "simulator" / "*.py")):
            src += Path(p).read_text(encoding="utf-8")
        for needle in (
            "Generate schedule",
            "Plan detail",
            "Publish as monthly",
            "ui.chip",
            "ui.splitter",
            "ui.spinner",
            "ui.refreshable",
            "throttled",
            "variance",
            "24/7",
            "Avoid FLSA",
            "implement_optimized_plan",
            "format_optimized_plan_view",
            "recommend_implement_dates",
            "Find best",
            "search_depth",
            "sim-hero",
            "sim-option-card",
        ):
            self.assertIn(needle, src)

    def test_leave_ot_fill_board(self):
        src = _read("gui/pages/leave.py")
        for needle in (
            "list_ot_fill_candidates",
            "apply_ot_fill_selection",
            "Order in",
            "Volunteer",
            "Cover officer",
            "Use auto plan",
            "Approve no cover",
            "leave-approve-dlg",
        ):
            self.assertIn(needle, src)
        # Regression: positional make_order(False) bound False to cover officer id
        self.assertNotIn("make_order(False)", src)
        self.assertNotIn("make_order(True)", src)
        self.assertNotIn("make_vol(False)", src)
        self.assertNotIn("make_vol(True)", src)
        # Compact dialog uses select + do_order_in (not per-row factory board)
        self.assertIn("do_order_in", src)
        self.assertIn("do_volunteer", src)
        self.assertIn('response="ordered_in"', src)
        self.assertIn('response="volunteered"', src)

    def test_simulator_no_multiarg_append(self):
        import glob

        src = ""
        for p in glob.glob(str(ROOT / "gui" / "pages" / "simulator" / "*.py")):
            src += Path(p).read_text(encoding="utf-8")
        # Regression: lines.append("", "Suggestions:") crashes at runtime
        self.assertNotIn('lines.append("", "Suggestions:")', src)
        self.assertNotIn('lines.append("",', src)
        # Explain path still present
        self.assertIn("explain_staffing_result", src)

    def test_timecard_period_jump_wires_storage(self):
        src = _read("gui/pages/finance/timecards.py")
        self.assertIn("_TIMECARD_PERIOD_KEY", src)
        self.assertIn("app.storage.user", src)
        self.assertIn("Current period", src)
        self.assertIn('ui.navigate.to("/timecards")', src)

    def test_roster_rotation_fields(self):
        src = _read("gui/pages/roster.py")
        self.assertIn("Rotation pattern", src)
        self.assertIn("Rotation phase", src)
        self.assertIn("rotation_pattern", src)
        self.assertIn("rotation_phase", src)
        self.assertIn("Max turn-downs", src)
        self.assertIn("Max ordered-in", src)
        self.assertIn("max_turn_downs_year", src)
        self.assertIn("max_ordered_in_year", src)
        self.assertIn("set_title_callin_limit", src)


if __name__ == "__main__":
    unittest.main()
