"""Tests for automatic startup gates."""

import os
import tempfile
import unittest
from unittest import mock

from scripts import startup_gates as sg


class StartupGatesTests(unittest.TestCase):
    def test_dev_skip_commands(self):
        self.assertIn("cheap-check", sg.DEV_SKIP_AUTO_GATES)
        self.assertIn("route-task", sg.DEV_SKIP_AUTO_GATES)
        self.assertNotIn("smoke", sg.DEV_SKIP_AUTO_GATES)

    def test_debounce_after_recent_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = os.path.join(tmp, "last_gate.json")
            with mock.patch.object(sg, "STATE_PATH", state_path):
                sg._write_state(passed=True, mode="cheap-check", source="test")
                self.assertTrue(sg._should_debounce(90))

    def test_no_debounce_after_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_path = os.path.join(tmp, "last_gate.json")
            with mock.patch.object(sg, "STATE_PATH", state_path):
                sg._write_state(passed=False, mode="cheap-check", source="test")
                self.assertFalse(sg._should_debounce(90))

    def test_skip_env_var(self):
        with mock.patch.dict(os.environ, {"SCHEDULER_SKIP_STARTUP_GATES": "1"}):
            code = sg.run_startup_gates(debounce_sec=0, ensure_hook=False)
            self.assertEqual(code, 0)

    def test_auto_before_cli_delegates(self):
        with mock.patch.object(sg, "run_startup_gates", return_value=0) as run:
            self.assertEqual(sg.auto_before_cli(), 0)
            run.assert_called_once()
            self.assertEqual(run.call_args.kwargs.get("source"), "cli.py")


if __name__ == "__main__":
    unittest.main()
