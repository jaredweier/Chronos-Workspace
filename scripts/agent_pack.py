"""Build a minimal pasteable agent context pack — one file instead of repo dump."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from typing import List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACK_DIR = os.path.join(ROOT, "logs", "agent_pack")
LATEST = os.path.join(PACK_DIR, "latest.md")


def _head(path: str, lines: int = 12) -> List[str]:
    full = os.path.join(ROOT, path)
    if not os.path.isfile(full):
        return []
    with open(full, encoding="utf-8") as fh:
        return [line.rstrip() for line in fh.readlines()[:lines]]


def _git_touch_status(paths: List[str]) -> List[str]:
    if not paths or not os.path.isdir(os.path.join(ROOT, ".git")):
        return []
    result = subprocess.run(
        ["git", "status", "--short", "--"] + paths,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    return [line for line in result.stdout.splitlines() if line.strip()]


def _last_gate() -> dict:
    path = os.path.join(ROOT, "logs", "last_gate.json")
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return {}


def _slice_touch(slice_id: str) -> tuple[Optional[dict], List[str]]:
    from slices.registry import SLICES

    match = next((s for s in SLICES if s["id"] == slice_id), None)
    if not match:
        return None, []
    return match, list(match.get("touch_together", []))


def build_agent_pack(
    *,
    task: str = "",
    slice_id: str = "",
    complexity: str = "",
) -> str:
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    os.chdir(ROOT)

    from scripts.agent_route import format_recommendation_compact, route_task
    from scripts.file_outline import outline_file
    from scripts.token_estimate import file_stats, format_stats_row

    lines: List[str] = [
        "# Agent context pack (dynamic)",
        f"Generated: {datetime.now(timezone.utc).isoformat()}",
        "stable: docs/AGENT_STABLE.md",
        "",
        "## FIRST: Caveman + Minimize (mandatory)",
        "- **Caveman:** short bullets. No preamble/recap/let-me. Prose only if user asks explain/docs.",
        "- **Token min:** fewest tools that finish fully+well. Parallel OK when it wins.",
        "- **Cost split:** easy → cheap/free; hard product/logic → primary. Prefer lower total usage.",
        "- Chain: `route-task` once → skill if helpful → edit/delegate → light=`fast` · logic/gui=`core` · ship=`check`",
        "- Tools/skills/subagents OK if cheaper/better. Gates/graphify/vision OK if cheaper than primary.",
        "- Archived skills: use only while needed, then put back in `docs/archived_skills/`.",
        "- Ship: `verify --tier check` + `honest_gate: true`. Never done on fast. Policy: `.grok/rules/auto-minimize.md`",
        "- Prompts/index: `token-improve` → `token-audit --strict`",
        "",
    ]

    if task.strip():
        rec = route_task(task, complexity_override=complexity, slice_override=slice_id)
        if not slice_id and rec.slice_id not in ("general", "ui-vision", "cli-ops"):
            slice_id = rec.slice_id
        lines.extend(["", "## Route (compact)", format_recommendation_compact(rec)])

    slice_def: Optional[dict] = None
    touch: List[str] = []
    if slice_id:
        slice_def, touch = _slice_touch(slice_id)
        if slice_def is None:
            lines.extend(["", f"Unknown slice: `{slice_id}` — run `python dev.py slice-map -v`"])
        else:
            lines.extend(
                [
                    "",
                    f"## Slice: {slice_def['id']} — {slice_def['name']}",
                    slice_def.get("summary", ""),
                    "",
                    "### Read/edit ONLY",
                ]
            )
            total_tokens = 0
            for path in touch:
                stats = file_stats(path)
                lines.append(format_stats_row(stats))
                total_tokens += stats.get("tokens", 0)
            lines.append(f"- **Total if all read whole:** ~{total_tokens:,} tokens")
            lines.append("- **Prefer:** outlines below or `python dev.py symbol <name>`")

            lines.extend(["", "### Outlines (read instead of full files)"])
            for path in touch:
                if path.endswith(".py") and os.path.isfile(os.path.join(ROOT, path)):
                    mini = outline_file(path, max_items=10)
                    lines.extend([f"#### `{path}`", "```", mini, "```"])

            verify = slice_def.get("verify", [])
            if verify:
                lines.extend(["", "### Verify (free, terminal)"])
                for cmd in verify:
                    lines.append(f"- `python dev.py {cmd}`")
                lines.append(f"- `python dev.py verify-slice {slice_id}`")

            git_lines = _git_touch_status(touch)
            if git_lines:
                lines.extend(["", "### Git status (slice files)"])
                lines.extend(f"`{g}`" for g in git_lines)

    gate = _last_gate()
    if gate:
        lines.extend(
            [
                "",
                "### Last startup gate",
                f"- passed: {gate.get('passed')} · mode: {gate.get('mode')} · {gate.get('timestamp', '')}",
            ]
        )

    try:
        from scripts.context_window import agent_hint, load_state

        ctx = load_state()
        if ctx.get("turn", 0) or ctx.get("current_task"):
            lines.extend(["", "### Context window", f"- {agent_hint()}"])
            if ctx.get("current_task"):
                lines.append(f"- task: {ctx['current_task'][:120]}")
    except Exception:
        pass

    handoff = _head("docs/HANDOFF.md", 6)
    if handoff:
        lines.extend(["", "## HANDOFF (6 lines max)"])
        lines.extend(handoff)

    return "\n".join(lines)


def build_agent_pack_json(**kwargs) -> dict:
    """Ultra-compact machine-readable pack for tooling."""
    md = build_agent_pack(**kwargs)
    return {
        "pack_tokens": max(1, len(md) // 4),
        "path": "logs/agent_pack/latest.md",
        "mandate": "logs/agent_pack/latest.md + docs/AGENT_STABLE.md",
    }


def run_agent_pack(
    *,
    task: str = "",
    slice_id: str = "",
    complexity: str = "",
    quiet: bool = False,
) -> int:
    content = build_agent_pack(task=task, slice_id=slice_id, complexity=complexity)
    os.makedirs(PACK_DIR, exist_ok=True)
    with open(LATEST, "w", encoding="utf-8") as fh:
        fh.write(content)

    est = max(1, len(content) // 4)
    if not quiet:
        print(content)
        print("=" * 60)
    print(f"agent-pack: wrote {LATEST} (~{est:,} tokens)")
    print("Paste @logs/agent_pack/latest.md into Agent — not the whole repo.")
    return 0


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("task", nargs="*", help="Optional task for route-task")
    p.add_argument("--slice", default="", dest="slice_id")
    p.add_argument("--complexity", default="")
    p.add_argument("-q", "--quiet", action="store_true")
    ns = p.parse_args()
    raise SystemExit(
        run_agent_pack(
            task=" ".join(ns.task),
            slice_id=ns.slice_id,
            complexity=ns.complexity,
            quiet=ns.quiet,
        )
    )
