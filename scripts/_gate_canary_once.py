"""One-shot: prove core-test goes red on intentional fail, then green after restore."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "tests" / "test_logic.py"
MARKER = "    def test_gate_canary_must_fail(self):\n        self.fail('gate canary')\n"


def run_core() -> int:
    return subprocess.call(
        [
            sys.executable,
            "-m",
            "unittest",
            "tests.test_logic",
            "tests.test_validators",
            "-q",
        ],
        cwd=ROOT,
    )


def main() -> int:
    text = TARGET.read_text(encoding="utf-8")
    if MARKER in text:
        print("canary already present — abort")
        return 2
    # Insert canary method into first TestCase class body
    needle = "class "
    # Append a tiny TestCase at end of file
    broken = text.rstrip() + "\n\n\nclass _GateCanary(unittest.TestCase):\n" + MARKER
    if "import unittest" not in broken.split("class _GateCanary", 1)[0][-500:]:
        pass  # unittest already imported in test_logic
    TARGET.write_text(broken + "\n", encoding="utf-8")
    try:
        code_red = run_core()
        print(f"RED_RUN exit={code_red} (expect nonzero)")
    finally:
        TARGET.write_text(text, encoding="utf-8")
        print("restored test_logic.py")
    code_green = run_core()
    print(f"GREEN_RUN exit={code_green} (expect 0)")
    if code_red == 0:
        print("FAIL: core stayed green with canary — suite may be no-op")
        return 1
    if code_green != 0:
        print("FAIL: core red after restore")
        return 1
    print("OK: core gate fails closed then recovers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
