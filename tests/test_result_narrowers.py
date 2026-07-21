"""End filters + publish readiness + stage lock actions."""

from __future__ import annotations

import unittest


class ResultNarrowersTests(unittest.TestCase):
    def test_filter_flsa_hides_violations(self):
        from logic.result_narrowers import filter_ranked

        ranked = [
            {
                "rank": 1,
                "num_officers": 6,
                "hard_constraints_ok": True,
                "metrics": {"flsa_violations": 0, "gap_events": 0},
            },
            {
                "rank": 2,
                "num_officers": 7,
                "hard_constraints_ok": True,
                "metrics": {"flsa_violations": 2, "gap_events": 0},
            },
        ]
        out = filter_ranked(ranked, require_flsa_clean=True)
        self.assertEqual(out["kept_count"], 1)
        self.assertEqual(out["dropped_count"], 1)
        self.assertEqual(out["ranked"][0]["num_officers"], 6)
        self.assertEqual(out["ranked"][0]["rank"], 1)

    def test_certs_do_not_drop_rows(self):
        from logic.result_narrowers import filter_ranked

        ranked = [
            {"rank": 1, "num_officers": 6, "metrics": {"flsa_violations": 0}},
        ]
        out = filter_ranked(ranked, required_certs=["FTO", "K9"])
        self.assertEqual(out["kept_count"], 1)
        self.assertIn("FTO", out.get("cert_note") or "")
        self.assertIn("cert_publish_note", out["ranked"][0])

    def test_suggest_lock_actions_from_counts(self):
        from logic.result_narrowers import suggest_lock_actions

        acts = suggest_lock_actions(
            stage_report=[{"stage_id": "officers_annual", "tips": ["Many officer counts free"]}],
            stage_tips=["Many officer counts free — locking a range speeds search"],
            current={"officer_counts": [6, 7, 8, 9], "length_opts": [8.0, 9.0, 10.0], "free_starts": True},
        )
        self.assertTrue(acts)
        ids = {a["id"] for a in acts}
        self.assertTrue(any("lock_n" in i for i in ids) or any("Lock officers" in a["label"] for a in acts))

    def test_publish_readiness_needs_selection(self):
        from logic.result_narrowers import publish_readiness

        r = publish_readiness({"selected_row": None, "ranked": [], "opt_result": {}})
        self.assertFalse(r["ready"])
        self.assertTrue(r["gaps"])

        r2 = publish_readiness(
            {
                "selected_row": {"hard_constraints_ok": True, "num_officers": 8},
                "ranked": [{}],
                "opt_result": {"best": {}},
            }
        )
        self.assertTrue(r2["ready"])
        self.assertTrue(r2["has_selection"])

    def test_failure_recovery_and_report(self):
        from logic.result_narrowers import export_constraint_report, failure_recovery_options

        opt = {
            "success": False,
            "message": "No hard match",
            "failure_histogram": {"window": 3, "coverage_247": 1},
            "stage_report": [{"title": "Windows", "ok": True, "before": {}, "after": {}, "tips": ["x"]}],
            "ranked": [],
            "constraints_applied": {"search_architecture": "staged_feasibility"},
        }
        tips = failure_recovery_options(opt)
        self.assertTrue(tips)
        text = export_constraint_report(opt)
        self.assertIn("staffing search report", text.lower())
        self.assertIn("staged_feasibility", text)


if __name__ == "__main__":
    unittest.main()
