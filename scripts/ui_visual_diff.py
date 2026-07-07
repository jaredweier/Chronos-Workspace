"""
Compare ui-live screenshots against baselines (Pillow — already a project dependency).

Baselines: tests/ui_snapshots/baseline/
Current:   logs/ui_live_test/<run>/ or --current-dir

Run:
  python dev.py ui-diff
  python dev.py ui-diff --update-baseline
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from typing import List, Tuple

_QUICK_PREFIX = re.compile(r"^(\d{2})_")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE_DIR = os.path.join(ROOT, "tests", "ui_snapshots", "baseline")
DIFF_DIR_NAME = "diff"
THRESHOLD_RATIO = 0.02  # max differing pixel ratio before fail


def _list_pngs(directory: str) -> List[str]:
    if not os.path.isdir(directory):
        return []
    return sorted(name for name in os.listdir(directory) if name.lower().endswith(".png"))


def _latest_live_dir() -> str:
    live_root = os.path.join(ROOT, "logs", "ui_live_test")
    if not os.path.isdir(live_root):
        return ""
    runs = [
        os.path.join(live_root, name)
        for name in os.listdir(live_root)
        if os.path.isdir(os.path.join(live_root, name)) and not name.startswith(".")
    ]
    if not runs:
        return ""
    runs.sort(key=os.path.getmtime, reverse=True)
    return runs[0]


def _is_quick_shot(name: str) -> bool:
    """Nav + login screenshots only (01–15): fast layout smoke."""
    match = _QUICK_PREFIX.match(name)
    if not match:
        return False
    return 1 <= int(match.group(1)) <= 15


def _filter_quick(names: List[str]) -> List[str]:
    return [name for name in names if _is_quick_shot(name)]


def _compare_images(
    path_a: str,
    path_b: str,
    diff_path: str,
    *,
    save_diff: bool = True,
) -> Tuple[float, bool]:
    from PIL import Image, ImageChops

    img_a = Image.open(path_a).convert("RGB")
    img_b = Image.open(path_b).convert("RGB")
    if img_a.size != img_b.size:
        img_b = img_b.resize(img_a.size, Image.Resampling.LANCZOS)
    diff = ImageChops.difference(img_a, img_b)
    hist = diff.histogram()
    pixels = img_a.size[0] * img_a.size[1]
    changed = sum(hist[1:256]) + sum(hist[257:512]) + sum(hist[513:768])
    ratio = changed / max(pixels * 3, 1)
    ok = ratio <= THRESHOLD_RATIO
    if save_diff and not ok:
        diff.save(diff_path)
    return ratio, ok


def run_ui_visual_diff(
    *,
    current_dir: str = "",
    update_baseline: bool = False,
    quick: bool = False,
    verbose: bool = False,
) -> int:
    current = current_dir or _latest_live_dir()
    if not current or not os.path.isdir(current):
        print("ui-diff: no screenshot directory — run: python dev.py ui-live")
        return 1

    os.makedirs(BASELINE_DIR, exist_ok=True)

    if update_baseline:
        copied = 0
        for name in _list_pngs(current):
            shutil.copy2(os.path.join(current, name), os.path.join(BASELINE_DIR, name))
            copied += 1
        print(f"ui-diff: updated {copied} baseline(s) in {BASELINE_DIR}")
        return 0

    diff_out = os.path.join(current, DIFF_DIR_NAME)
    os.makedirs(diff_out, exist_ok=True)

    current_files = _list_pngs(current)
    if quick:
        current_files = _filter_quick(current_files)
    if not current_files:
        hint = " (quick: none matched 01–15)" if quick else ""
        print(f"ui-diff: no PNGs in {current}{hint}")
        return 1

    baseline_files = set(_list_pngs(BASELINE_DIR))
    failed: List[str] = []
    missing: List[str] = []
    passed = 0

    print("Dodgeville PD Scheduler — UI visual diff")
    print("=" * 60)
    print(f"Current:  {current}")
    print(f"Baseline: {BASELINE_DIR}")
    print(f"Threshold: {THRESHOLD_RATIO:.1%} pixel difference")
    if quick:
        print(f"Mode: quick — {len(current_files)} nav/login shot(s) (01–15)")
    print("-" * 60)

    for name in current_files:
        cur_path = os.path.join(current, name)
        base_path = os.path.join(BASELINE_DIR, name)
        if name not in baseline_files:
            missing.append(name)
            if verbose:
                print(f"  [NEW] {name} (no baseline)")
            continue
        ratio, ok = _compare_images(
            base_path,
            cur_path,
            os.path.join(diff_out, name),
            save_diff=True,
        )
        if ok:
            passed += 1
            if verbose:
                print(f"  [ok] {name} ({ratio:.2%})")
        else:
            failed.append(name)
            print(f"  [FAIL] {name} ({ratio:.2%} diff) → {diff_out}/{name}")

    report = {
        "current_dir": current,
        "baseline_dir": BASELINE_DIR,
        "passed": passed,
        "failed": failed,
        "missing_baseline": missing,
        "threshold": THRESHOLD_RATIO,
    }
    with open(os.path.join(diff_out, "report.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)

    print("-" * 60)
    if missing and not baseline_files:
        print("No baselines yet. Run: python dev.py ui-diff --update-baseline")
        print("  (after: python dev.py ui-live)")
        return 0
    if failed:
        print(f"ui-diff: FAILED — {len(failed)} image(s) differ")
        return 1
    print(f"ui-diff: PASSED — {passed} compared, {len(missing)} new without baseline")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Visual diff for ui-live screenshots")
    parser.add_argument("--current-dir", default="", help="Screenshot run directory")
    parser.add_argument("--update-baseline", action="store_true", help="Copy current to baseline")
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Compare only nav/login PNGs numbered 01–15",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    raise SystemExit(
        run_ui_visual_diff(
            current_dir=args.current_dir,
            update_baseline=args.update_baseline,
            quick=args.quick,
            verbose=args.verbose,
        )
    )
