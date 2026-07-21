"""Tests for automatic agent token-minimization gates."""

import json
import os
import tempfile
import unittest
from unittest import mock

from scripts import agent_gates as ag


class AgentGatesTests(unittest.TestCase):
    def test_skip_env_var(self):
        with mock.patch.dict(os.environ, {"SCHEDULER_SKIP_AGENT_GATES": "1"}):
            code = ag.run_agent_gates(force=True, debounce_sec=0)
            self.assertEqual(code, 0)

    def test_force_writes_pack_and_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            pack = os.path.join(tmp, "agent_pack", "latest.md")
            state = os.path.join(tmp, "last_agent_gate.json")
            with mock.patch.object(ag, "PACK_PATH", pack):
                with mock.patch.object(ag, "STATE_PATH", state):
                    with mock.patch.dict(os.environ, {}, clear=False):
                        os.environ.pop("SCHEDULER_SKIP_AGENT_GATES", None)
                        code = ag.run_agent_gates(
                            slice_id="roster",
                            force=True,
                            debounce_sec=0,
                            quiet=True,
                        )
            self.assertEqual(code, 0)
            self.assertTrue(os.path.isfile(pack))
            self.assertTrue(os.path.isfile(state))
            with open(state, encoding="utf-8") as fh:
                data = json.load(fh)
            self.assertEqual(data["slice_id"], "roster")
            self.assertIn("mandate", data)

    def test_dev_skip_agent_gates_meta_commands(self):
        self.assertIn("agent-pack", ag.DEV_SKIP_AGENT_GATES)
        self.assertIn("agent-gates", ag.DEV_SKIP_AGENT_GATES)
        self.assertNotIn("check", ag.DEV_SKIP_AGENT_GATES)

    def test_agent_context_hint(self):
        hint = ag.agent_context_hint()
        self.assertIn("agent_pack", hint)
        self.assertIn("AGENT_STABLE", hint)


if __name__ == "__main__":
    unittest.main()
