"""Tests for read_guard."""

import unittest

from scripts.read_guard import check_read, known_large_ui_files


class ReadGuardTests(unittest.TestCase):
    def test_block_full_project_code(self):
        r = check_read("docs/FULL_PROJECT_CODE.txt")
        self.assertEqual(r.action, "deny")

    def test_block_png(self):
        r = check_read("tests/ui_snapshots/baseline/foo.png")
        self.assertEqual(r.action, "deny")

    def test_allow_config(self):
        r = check_read("config.py")
        self.assertEqual(r.action, "allow")

    def test_product_modules_readable(self):
        # After modular splits, most product modules are under LARGE_FILE_KB — allow or ask both OK
        for path in ("cli.py", "gui/pages/leave.py", "logic/payroll/timecard.py", "gui/theme.py"):
            r = check_read(path)
            self.assertIn(r.action, ("allow", "ask"), msg=f"{path}: {r}")

    def test_payroll_package_readable(self):
        r = check_read("logic/payroll/timecard.py")
        self.assertIn(r.action, ("allow", "ask"))

    def test_known_large_ui_list_is_list(self):
        large = known_large_ui_files()
        self.assertIsInstance(large, list)
        # Empty is valid when all modules stay under threshold after splits
        for path, kb in large:
            self.assertTrue(path.endswith(".py") or "/" in path)
            self.assertGreaterEqual(kb, 0)


if __name__ == "__main__":
    unittest.main()
