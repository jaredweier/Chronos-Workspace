"""Unified verification — tiers must be strict supersets, no duplicate/conflicting gates."""

import unittest

from scripts.verify import (
    CORE_TEST_MODULES,
    STEP_CHECK,
    STEP_CORE,
    STEP_FAST,
    STEP_FULL,
    STEP_PREFLIGHT,
    is_subset,
    tier_steps,
)


class VerifyUnifiedTests(unittest.TestCase):
    def test_core_subset_of_fast(self):
        self.assertTrue(is_subset("core", "fast"))

    def test_fast_subset_of_preflight(self):
        self.assertTrue(is_subset("fast", "preflight"))

    def test_preflight_subset_of_check(self):
        self.assertTrue(is_subset("preflight", "check"))

    def test_check_subset_of_full(self):
        self.assertTrue(is_subset("check", "full"))

    def test_full_subset_of_release(self):
        self.assertTrue(is_subset("full", "release"))

    def test_no_duplicate_steps_in_check(self):
        steps = tier_steps("check")
        self.assertEqual(len(steps), len(set(steps)), f"duplicate steps: {steps}")

    def test_core_test_in_fast_and_preflight(self):
        self.assertIn("core-test", STEP_CORE)
        self.assertIn("core-test", STEP_FAST)
        self.assertIn("core-test", STEP_PREFLIGHT)

    def test_core_modules_are_product_not_meta(self):
        self.assertGreaterEqual(len(CORE_TEST_MODULES), 4)
        joined = " ".join(CORE_TEST_MODULES)
        self.assertIn("test_logic", joined)
        self.assertIn("test_regressions", joined)
        self.assertNotIn("test_token", joined)
        self.assertNotIn("test_verify_unified", joined)

    def test_readiness_in_fast_and_preflight(self):
        self.assertIn("readiness", STEP_FAST)
        self.assertIn("readiness", STEP_PREFLIGHT)

    def test_audit_runs_once_in_check(self):
        self.assertEqual(tier_steps("check").count("audit"), 1)

    def test_check_includes_test_and_scenarios(self):
        self.assertIn("test", STEP_CHECK)
        self.assertIn("scenarios", STEP_CHECK)

    def test_full_includes_smoke_and_ui_smoke(self):
        self.assertIn("smoke", STEP_FULL)
        self.assertIn("ui-smoke", STEP_FULL)
        self.assertIn("ui-workflow", STEP_FULL)

    def test_check_includes_rust_backend(self):
        self.assertIn("rust-backend", STEP_CHECK)

    def test_preflight_and_check_include_graphify(self):
        self.assertIn("graphify", STEP_PREFLIGHT)
        self.assertIn("graphify", STEP_CHECK)
        self.assertNotIn("graphify", STEP_FAST)
        self.assertNotIn("graphify", STEP_CORE)

    def test_tier_alias_cheap_check(self):
        self.assertEqual(tier_steps("cheap-check"), tier_steps("fast"))

    def test_agent_meta_tier_isolated(self):
        steps = tier_steps("agent-meta")
        self.assertIn("agent-meta-test", steps)
        self.assertNotIn("agent-meta-test", STEP_CHECK)
        self.assertNotIn("agent-meta-test", STEP_FAST)

    def test_product_suite_excludes_agent_meta(self):
        import os
        import unittest

        from scripts.verify import ROOT, _suite_without_agent_meta

        loader = unittest.TestLoader()
        raw = loader.discover("tests", pattern="test_*.py", top_level_dir=ROOT)
        full = raw.countTestCases()
        product = _suite_without_agent_meta(raw).countTestCases()
        self.assertLess(product, full, f"full={full} product={product}")
        self.assertGreaterEqual(full - product, 10)
        self.assertTrue(os.path.isdir(os.path.join(ROOT, "tests", "agent_meta")))


if __name__ == "__main__":
    unittest.main()
