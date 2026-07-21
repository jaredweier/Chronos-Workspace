"""Tests for OSS dev tooling wrappers."""

import os
import subprocess
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class OssToolsTests(unittest.TestCase):
    def test_lint_reports_missing_ruff(self):
        from scripts.lint import run_lint

        with mock.patch("scripts.lint._ruff_cmd", return_value=None):
            self.assertEqual(run_lint(), 1)

    def test_deps_audit_missing_file(self):
        from scripts.deps_audit import run_deps_audit

        self.assertEqual(run_deps_audit(requirements="no-such-requirements.txt"), 1)

    def test_dev_lint_help(self):
        result = subprocess.run(
            [sys.executable, "dev.py", "lint", "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("ruff", result.stdout.lower())

    def test_dev_deps_audit_help(self):
        result = subprocess.run(
            [sys.executable, "dev.py", "deps-audit", "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("requirements", result.stdout.lower())


if __name__ == "__main__":
    unittest.main()
