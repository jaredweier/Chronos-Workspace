"""P5 pattern calendar + soft compliance strip."""

from __future__ import annotations

import unittest

from logic.pattern_preview import (
    compliance_strip,
    form_preview_bundle,
    pattern_calendar_preview,
)


class PatternPreviewTests(unittest.TestCase):
    def test_multi_block_calendar(self):
        cal = pattern_calendar_preview(
            variations_text="6-2,5-3 | 6-3,5-2",
            style="rotating",
            days=28,
        )
        self.assertTrue(cal["success"])
        self.assertEqual(len(cal["rows"]), 2)
        self.assertEqual(cal["rows"][0]["cycle"], 16)
        self.assertEqual(len(cal["rows"][0]["cells"]), 28)
        self.assertTrue(any(c["on"] for c in cal["rows"][0]["cells"]))
        self.assertTrue(any(not c["on"] for c in cal["rows"][0]["cells"]))

    def test_empty_patterns_message(self):
        cal = pattern_calendar_preview(variations_text="")
        self.assertFalse(cal["success"])
        self.assertIn("Enter multi-block", cal["message"])

    def test_compliance_annual_fit(self):
        strip = compliance_strip(
            shift_length_hours=8.0,
            annual_hours_target=2008,
            annual_hours_variance=40,
            variations_text="6-2,5-3",
            style="rotating",
        )
        self.assertTrue(strip["success"])
        keys = {i["key"] for i in strip["items"]}
        self.assertIn("annual_fit", keys)

    def test_form_bundle(self):
        b = form_preview_bundle(
            {
                "variations": "6-2,5-3",
                "rot_style": "Rotating",
                "length": 8,
                "annual": 2008,
                "annual_var": 40,
            }
        )
        self.assertTrue(b["calendar"]["success"])
        self.assertTrue(b["compliance"]["success"])


if __name__ == "__main__":
    unittest.main()
