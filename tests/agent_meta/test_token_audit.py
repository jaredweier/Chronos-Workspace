"""Tests for token minimization audit."""

import unittest

from scripts import token_audit as ta


class TokenAuditTests(unittest.TestCase):
    def test_all_artifacts_present(self):
        code = ta.run_token_audit(strict=True)
        self.assertEqual(code, 0, "token-audit should pass after artifacts wired")

    def test_cursorignore_blocks_dump(self):
        check = ta._cursorignore_blocks_large_dump()
        self.assertTrue(check.ok, check.detail)

    def test_opencode_agent_mandate(self):
        checks = ta._opencode_minimal()
        instr = next(c for c in checks if "agent-pack mandate" in c.name.lower())
        self.assertTrue(instr.ok, instr.detail)


if __name__ == "__main__":
    unittest.main()
