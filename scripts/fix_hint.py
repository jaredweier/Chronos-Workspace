"""Suggest free next steps after a failed gate — no LLM required."""

from __future__ import annotations

import os
import re
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _slice_for_path(path: str) -> str:
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    from slices.registry import SLICES

    norm = path.replace("\\", "/")
    best = ""
    best_len = 0
    for s in SLICES:
        for touch in s.get("touch_together", []):
            t = touch.replace("\\", "/")
            if norm == t or norm.endswith("/" + t) or t in norm:
                if len(t) > best_len:
                    best_len = len(t)
                    best = s["id"]
    return best


def run_fix_hint(run_audit: bool = True) -> int:
    os.chdir(ROOT)
    print("Dodgeville PD — fix-hint (free)")
    print("=" * 60)

    from scripts.verify import read_verify_state

    state = read_verify_state()
    if state:
        print("Last verify run:")
        print(f"  tier:    {state.get('tier', '?')}")
        print(f"  passed:  {state.get('passed', '?')}")
        print(f"  honest:  {state.get('honest_gate', False)} (ship-ready only when check+ passes)")
        failed = state.get("failed_steps") or []
        if failed:
            print(f"  failed:  {', '.join(failed)}")
            print("\nEscalate: python dev.py verify --tier check")
        print("  state:   logs/last_verify.json")

    log_path = os.path.join(ROOT, "check_result.log")
    if os.path.isfile(log_path):
        with open(log_path, encoding="utf-8", errors="replace") as fh:
            tail = fh.readlines()[-40:]
        print("\nFrom check_result.log (last lines):")
        for line in tail:
            print(" ", line.rstrip())

    if run_audit:
        print("\n>>> audit (free)")
        result = subprocess.run(
            [sys.executable, "dev.py", "audit"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8"
        )
        out = (result.stdout or "") + (result.stderr or "")
        for line in out.splitlines():
            if "[FAIL]" in line or "FAIL" in line:
                print(line)
                m = re.search(r"([A-Za-z0-9_./\\-]+\.py)", line)
                if m:
                    sid = _slice_for_path(m.group(1))
                    if sid:
                        print(f"  → slice: {sid}")
                        print(f"  → python dev.py usage-brief {sid}")
                        print(f"  → python dev.py verify-slice {sid}")

    print("\nPolicy: .grok/rules/verify-policy.md")
    print("Context: @logs/agent_pack/latest.md + @docs/AGENT_STABLE.md")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    no_audit = "--no-audit" in sys.argv
    raise SystemExit(run_fix_hint(run_audit=not no_audit))
