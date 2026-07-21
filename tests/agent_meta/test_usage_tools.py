"""Tests for zero-usage dev tooling."""

import subprocess
import sys
import unittest

from scripts.usage_brief import run_usage_brief


class UsageToolsTests(unittest.TestCase):
    def test_usage_brief_unknown_slice_fails(self):
        code = run_usage_brief(slice_id="not-a-real-slice-xyz")
        self.assertEqual(code, 1)

    def test_usage_brief_known_slice(self):
        code = run_usage_brief(slice_id="day-off-requests")
        self.assertEqual(code, 0)

    def test_cheap_check_runs(self):
        root = __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.dirname(__file__)))
        result = subprocess.run(
            [sys.executable, "dev.py", "cheap-check"],
            cwd=root,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
