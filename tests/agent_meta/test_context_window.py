"""Tests for context window management."""

import os
import tempfile
import unittest
from unittest import mock

from scripts import context_window as cw


class ContextWindowTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._state = os.path.join(self._tmp.name, "state.json")
        self._summary = os.path.join(self._tmp.name, "latest_summary.md")
        self._ctx_dir = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def _patches(self):
        return (
            mock.patch.object(cw, "STATE_PATH", self._state),
            mock.patch.object(cw, "SUMMARY_PATH", self._summary),
            mock.patch.object(cw, "CTX_DIR", self._ctx_dir),
        )

    def test_ephemeral_pruned_after_two_turns(self):
        p1, p2, p3 = self._patches()
        with p1, p2, p3:
            cw.register_tool("grep:foo", tokens=100, ephemeral=True, summary="grep foo")
            cw.advance_turn()
            info = cw.advance_turn()
            self.assertGreaterEqual(info["pruned"], 1)
            state = cw.load_state()
            self.assertEqual(state["tool_results"], [])

    def test_kept_tool_survives_prune(self):
        p1, p2, p3 = self._patches()
        with p1, p2, p3:
            cw.register_tool("read:logic.py", tokens=500, keep=True, summary="need logic")
            cw.advance_turn()
            cw.advance_turn()
            cw.advance_turn()
            cw.prune_ephemeral()
            state = cw.load_state()
            self.assertEqual(len(state["tool_results"]), 1)
            self.assertTrue(state["tool_results"][0]["keep"])

    def test_summarize_at_threshold(self):
        p1, p2, p3 = self._patches()
        with p1, p2, p3:
            cw.set_task("fix context window")
            cw.add_decision("ephemeral tools drop after 2 turns")
            cw.register_tool("big-read", tokens=6100, ephemeral=True, summary="large output")
            self.assertTrue(os.path.isfile(self._summary))
            with open(self._summary, encoding="utf-8") as fh:
                text = fh.read()
            self.assertIn("fix context window", text)
            self.assertIn("ephemeral tools drop", text)
            state = cw.load_state()
            self.assertEqual(state["tokens_since_summary"], 0)

    def test_decisions_persist_after_summary(self):
        p1, p2, p3 = self._patches()
        with p1, p2, p3:
            cw.add_decision("keep this conclusion")
            state = cw.load_state()
            state["tokens_since_summary"] = cw.SUMMARY_THRESHOLD
            cw.save_state(state)
            cw.apply_summary(cw.load_state())
            state = cw.load_state()
            self.assertTrue(any("keep this" in d["text"] for d in state["decisions"]))


if __name__ == "__main__":
    unittest.main()
