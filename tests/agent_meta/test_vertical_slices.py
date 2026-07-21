"""Registry integrity for vertical slice map."""

import os
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class VerticalSliceRegistryTests(unittest.TestCase):
    def test_slice_ids_unique(self):
        from slices.registry import SLICES

        ids = [s["id"] for s in SLICES]
        self.assertEqual(len(ids), len(set(ids)), f"duplicate ids: {ids}")

    def test_required_fields_present(self):
        from slices.registry import SLICES

        required = ("id", "name", "summary", "status", "ui_pages", "logic", "touch_together", "future_module")
        for s in SLICES:
            for key in required:
                self.assertIn(key, s, f"slice {s.get('id')} missing {key}")

    def test_slice_check_passes(self):
        from scripts.vertical_slices import run_slice_check

        self.assertEqual(run_slice_check(), 0)

    def test_shared_kernel_files_exist(self):
        from slices.registry import SHARED_KERNEL

        for rel in SHARED_KERNEL["files"]:
            path = ROOT / rel.replace("/", os.sep)
            self.assertTrue(path.is_file(), f"missing shared kernel file: {rel}")

    def test_touch_together_paths_exist(self):
        from slices.registry import SLICES

        for s in SLICES:
            for rel in s.get("touch_together", []):
                path = ROOT / rel.replace("/", os.sep)
                self.assertTrue(path.is_file(), f"{s['id']}: missing {rel}")


if __name__ == "__main__":
    unittest.main()
