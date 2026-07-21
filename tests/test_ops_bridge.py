"""P4 ops bridge — publish readiness + open-shift seeds."""

from __future__ import annotations

import unittest

from logic.ops_bridge import (
    format_readiness_lines,
    publish_readiness_checklist,
    suggest_open_shifts_from_sim,
)


class OpsBridgeTests(unittest.TestCase):
    def test_readiness_blocks_without_plan(self):
        chk = publish_readiness_checklist({}, {}, implement_date="")
        self.assertFalse(chk["ready"])
        self.assertGreaterEqual(chk["blocking_count"], 1)
        lines = format_readiness_lines(chk)
        self.assertTrue(any("✕" in ln or "Plan" in ln for ln in lines))

    def test_readiness_ready_with_hard_ok(self):
        result = {
            "success": True,
            "best": {
                "hard_constraints_ok": True,
                "num_officers": 8,
                "shift_starts": ["06:00", "14:00", "22:00"],
                "metrics": {"hard_constraints_ok": True, "gap_events": 0},
            },
            "metrics": {"hard_constraints_ok": True, "night_risk_gaps": 2},
        }
        chk = publish_readiness_checklist(result, {}, implement_date="7/1/26")
        self.assertTrue(chk["ready"])
        # night_risk is warn not blocking
        night = next(i for i in chk["items"] if i["key"] == "night_risk")
        self.assertFalse(night["ok"])
        self.assertFalse(night["blocking"])

    def test_open_shift_suggestions_from_thin_bands(self):
        result = {
            "metrics": {"min_per_shift": 2},
            "coverage_by_day": [
                {
                    "date": "7/24/26",
                    "high_risk_night": True,
                    "shift_counts": {"06:00": 2, "14:00": 2, "22:00": 1},
                },
                {
                    "date": "7/25/26",
                    "high_risk_night": False,
                    "shift_counts": {"06:00": 2, "14:00": 0, "22:00": 2},
                },
            ],
            "shift_length_hours": 8.0,
        }
        sug = suggest_open_shifts_from_sim(result, start_date="7/24/26", max_posts=10)
        self.assertTrue(sug["success"])
        self.assertGreaterEqual(sug["count"], 1)
        starts = {c["shift_start"] for c in sug["candidates"]}
        self.assertTrue("22:00" in starts or "14:00" in starts)


if __name__ == "__main__":
    unittest.main()
