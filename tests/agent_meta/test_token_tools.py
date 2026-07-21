"""Tests for token-minimization helper tools."""

import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TokenToolsTests(unittest.TestCase):
    def test_agent_pack_writes_latest(self):
        from scripts.agent_pack import LATEST, run_agent_pack

        code = run_agent_pack(task="fix typo", slice_id="roster", quiet=True)
        self.assertEqual(code, 0)
        self.assertTrue(os.path.isfile(LATEST))
        with open(LATEST, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("roster", text)
        self.assertIn("docs/AGENT_STABLE.md", text)
        self.assertNotIn("Do NOT read", text)

    def test_outline_config(self):
        from scripts.file_outline import outline_file

        text = outline_file("config.py")
        self.assertIn("config.py", text)
        self.assertIn("tokens", text.lower())

    def test_symbol_lookup_process_day_off(self):
        from scripts.symbol_lookup import lookup_symbol

        hits = lookup_symbol("process_day_off_request", slice_id="day-off-requests")
        self.assertTrue(any("logic" in h[0] for h in hits))

    def test_usage_brief_shows_token_estimates(self):
        result = subprocess.run(
            [sys.executable, "dev.py", "usage-brief", "roster"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("tokens", result.stdout.lower())

    def test_dev_agent_pack_help(self):
        result = subprocess.run(
            [sys.executable, "dev.py", "agent-pack", "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("agent-pack", result.stdout)


if __name__ == "__main__":
    unittest.main()
