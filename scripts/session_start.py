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

    handoff = _read_head("docs/HANDOFF.md", 8)
    if handoff:
        print("\nHandoff (docs/HANDOFF.md, 8 lines):")
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

    # Always refresh free agent-kit so the next/this session has a pasteable pack.
    slice_id = os.environ.get("SCHEDULER_SLICE", "").strip() or "general"
    task = os.environ.get("SCHEDULER_AGENT_TASK", "").strip() or "Session resume — follow agent-kit"
    print(f"\nAgent kit (auto): slice={slice_id}")
    try:
        from scripts.agent_kit import run_agent_kit

        run_agent_kit(slice_id=slice_id, task=task, quiet=True)
        kit = os.path.join(ROOT, "logs", "agent_kit", "latest.md")
        print(f"  → @{os.path.relpath(kit, ROOT).replace(chr(92), '/')}")
        print("  Paste: @logs/agent_kit/latest.md  (not the whole repo)")
    except Exception as exc:
        print(f"  (agent-kit failed: {exc})")

    print("\nMinimize (caveman):")
    print("  @logs/agent_kit/latest.md + @logs/agent_pack/latest.md")
    print('  python dev.py route-task "…"          # once; obey cost_tier')
    print("  python dev.py usage-brief <slice>      # before reads")
    print("  python dev.py outline <file>           # before full read")
    print("  python dev.py verify --tier fast       # after edits")
    print("  python dev.py verify --tier check      # ship + honest_gate")
    print("  OSS/graphify/vision: only if user asks")
    print("\nQuick:")
    print("  python main.py · python dev.py preflight · python dev.py agent-pack --slice <id>")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(run_session_start())
