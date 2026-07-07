"""Print resume context for agents and developers starting a session."""

from __future__ import annotations

import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _read_head(path: str, lines: int = 30) -> list[str]:
    full = os.path.join(ROOT, path)
    if not os.path.isfile(full):
        return []
    with open(full, encoding="utf-8") as fh:
        return [line.rstrip() for line in fh.readlines()[:lines]]


def _extract_priorities(agents_md: str) -> list[str]:
    priorities: list[str] = []
    in_section = False
    for line in agents_md.splitlines():
        if "Next priorities" in line or "Open / next priorities" in line:
            in_section = True
            continue
        if in_section:
            if line.startswith("## ") or line.startswith("---"):
                break
            m = re.match(r"^\d+\.\s+(.+)", line.strip())
            if m:
                priorities.append(m.group(1))
    return priorities[:6]


def run_session_start() -> int:
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    os.chdir(ROOT)

    print("Dodgeville PD Scheduler — session start")
    print("=" * 60)

    handoff = _read_head("docs/HANDOFF.md", 25)
    if handoff:
        print("\nHandoff (docs/HANDOFF.md):")
        for line in handoff:
            if line.strip():
                print(f"  {line}")

    agents_path = os.path.join(ROOT, "AGENTS.md")
    if os.path.isfile(agents_path):
        with open(agents_path, encoding="utf-8") as fh:
            agents = fh.read()
        priorities = _extract_priorities(agents)
        if priorities:
            print("\nOpen priorities (AGENTS.md):")
            for i, item in enumerate(priorities, 1):
                print(f"  {i}. {item}")

    from slices.registry import SLICES

    print(f"\nSlices registered: {len(SLICES)}")
    print("  Run: python dev.py slice-map -v")

    print("\nEnvironment (doctor):")
    from scripts.doctor import run_doctor

    doctor_code = run_doctor(verbose=False)
    if doctor_code != 0:
        print("\nsession-start: doctor reported issues — fix before large changes")
        return doctor_code

    print("\nAutomatic gates: cheap-check on main.py, cli.py, dev.py (see logs/last_gate.json)")
    print("Automatic agent context: logs/agent_pack/latest.md (see logs/last_agent_gate.json)")
    print("  Skip: set SCHEDULER_SKIP_STARTUP_GATES=1")

    print("\nMinimize (mandatory):")
    print("  python dev.py usage-brief <slice>      # before reads")
    print("  python dev.py outline <file>           # before full read")
    print("  python dev.py cheap-check              # after edits")
    print("  python dev.py token-improve            # find new savings")
    print("\nAgent routing (auto-context OFF):")
    print('  python dev.py route-task "your task"')
    print("  python dev.py agent-pack --slice <id>  # minimal pasteable context")
    print("  python dev.py token-minimize           # scan + audit index")
    print("  docs/AGENT_ROUTING.md · docs/ZERO_AGENT_USAGE.md")

    print("\nQuick commands:")
    print("  python main.py")
    print("  python dev.py preflight")
    print("  python dev.py verify-slice <id>")
    print("  python dev.py check")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(run_session_start())
