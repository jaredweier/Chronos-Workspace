"""Tests for token-scan."""

import unittest

from scripts import token_scan as ts


class TokenScanTests(unittest.TestCase):
    def test_handoff_ignored(self):
        patterns = ts._load_ignore_patterns()
        self.assertTrue(ts._ignored("docs/HANDOFF.md", patterns))

    def test_config_not_ignored(self):
        patterns = ts._load_ignore_patterns()
        self.assertFalse(ts._ignored("config.py", patterns))

    def test_run_token_scan_returns_int(self):
        code = ts.run_token_scan(min_kb=5000)
        self.assertIn(code, (0, 1))


if __name__ == "__main__":
    unittest.main()
