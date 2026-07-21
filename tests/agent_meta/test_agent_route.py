"""Tests for scripts/agent_route.py."""

import unittest

from scripts.agent_route import route_task


class AgentRouteTests(unittest.TestCase):
    def test_scheduling_medium(self):
        rec = route_task("fix day-off bump cascade approval")
        self.assertEqual(rec.complexity, "medium")
        self.assertIn("scheduling", rec.skill)

    def test_vision_tier(self):
        rec = route_task("dashboard layout looks wrong screenshot")
        self.assertEqual(rec.complexity, "vision")
        self.assertIn("ui-vision", rec.skill)

    def test_trivial_tier(self):
        rec = route_task("fix typo in requests tab label")
        self.assertEqual(rec.complexity, "trivial")

    def test_high_override(self):
        rec = route_task("small tweak", complexity_override="high")
        self.assertEqual(rec.complexity, "high")

    def test_verify_tier(self):
        rec = route_task("run audit and verify tests pass")
        self.assertEqual(rec.complexity, "verify")


if __name__ == "__main__":
    unittest.main()
