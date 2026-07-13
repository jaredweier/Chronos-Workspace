"""Auto-abide token policy fixtures (no LLM)."""

from __future__ import annotations

import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TokenPolicyTests(unittest.TestCase):
    def test_agents_md_lean(self) -> None:
        path = os.path.join(ROOT, "AGENTS.md")
        with open(path, encoding="utf-8") as fh:
            lines = fh.readlines()
        self.assertLessEqual(len(lines), 20)
        text = "".join(lines).lower()
        self.assertIn("auto-context off", text)
        self.assertIn("caveman", text)
        self.assertIn("archived_skills", text)

    def test_no_skill_archive_under_discovery(self) -> None:
        self.assertFalse(os.path.isdir(os.path.join(ROOT, ".grok", "skills", "_archive")))
        demoted = (
            "agent-routing",
            "cost-efficient-workflow",
            "token-discipline",
            "frontend-design",
            "stop-slop",
            "refactor",
            "check-work",
        )
        for name in demoted:
            self.assertFalse(
                os.path.isdir(os.path.join(ROOT, ".grok", "skills", name)),
                msg=f"{name} still under .grok/skills",
            )

    def test_route_typo_empty_oss(self) -> None:
        import sys

        if ROOT not in sys.path:
            sys.path.insert(0, ROOT)
        from scripts.agent_route import route_task

        rec = route_task("fix typo on button")
        self.assertIn(rec.cost_tier, ("free", "cheap"))
        self.assertEqual(rec.oss_searches, [])
        self.assertEqual(rec.oss_actions, [])

    def test_catalog_no_skyvern_key(self) -> None:
        path = os.path.join(ROOT, "scripts", "agent_route.py")
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        self.assertNotIn('"skyvern"', src)
        self.assertNotIn('"browser-use"', src)


if __name__ == "__main__":
    unittest.main()
