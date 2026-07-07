"""Find new token-saving opportunities — run each session when prompts/index change."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import List

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "logs", "token_improve")
LATEST = os.path.join(OUT_DIR, "latest.md")

AGENTS_MAX_LINES = 20
PACK_WARN_TOKENS = 2500


def _read(path: str) -> str:
    full = os.path.join(ROOT, path)
    if not os.path.isfile(full):
        return ""
    with open(full, encoding="utf-8") as fh:
        return fh.read()


def _suggestions(*, apply_fix: bool) -> tuple[List[str], List[str]]:
    actions: List[str] = []
    notes: List[str] = []

    from scripts.token_scan import apply_token_scan_fix, scan_large_files

    indexed, _ = scan_large_files(min_kb=50, limit=15)
    if indexed:
        paths = ", ".join(e["path"] for e in indexed[:5])
        actions.append(f"Add to .cursorignore: {paths} — run `python dev.py token-scan --fix`")
        if apply_fix:
            added = apply_token_scan_fix(indexed)
            if added:
                notes.append(f"Applied token-scan --fix: {', '.join(added)}")

    pack_path = os.path.join(ROOT, "logs", "agent_pack", "latest.md")
    if os.path.isfile(pack_path):
        pack_tokens = max(1, os.path.getsize(pack_path) // 4)
        if pack_tokens > PACK_WARN_TOKENS:
            actions.append(f"agent_pack ~{pack_tokens:,}t — narrow slice, shorten HANDOFF head, avoid inline outlines")

    agents = _read("AGENTS.md")
    if agents:
        n = len(agents.splitlines())
        if n > AGENTS_MAX_LINES:
            actions.append(f"AGENTS.md is {n} lines (max {AGENTS_MAX_LINES}) — move detail to docs/AGENT_STABLE.md")

    for rel, label in (
        (".cursor/rules/auto-minimize.mdc", "Cursor auto-minimize"),
        (".grok/rules/auto-minimize.md", "Grok auto-minimize"),
    ):
        text = _read(rel)
        if text and len(text) > 1200:
            actions.append(f"{label} verbose ({len(text)} chars) — keep refs only, detail in AGENT_STABLE")

    ignore = _read(".cursorignore")
    for pattern in ("terminals/", "agent-tools/", "*.log"):
        if pattern not in ignore:
            actions.append(f"Consider adding `{pattern}` to .cursorignore")

    if not actions:
        notes.append("No new high-impact gaps — re-run after adding large files or prompt bloat.")

    return actions, notes


def run_token_improve(*, apply_fix: bool = False, quiet: bool = False) -> int:
    os.chdir(ROOT)
    os.makedirs(OUT_DIR, exist_ok=True)

    actions, notes = _suggestions(apply_fix=apply_fix)
    ts = datetime.now(timezone.utc).isoformat()

    lines = [
        "# Token improve report",
        f"Generated: {ts}",
        "",
        "## Actions (agents: implement safe items, then token-audit --strict)",
    ]
    if actions:
        lines.extend(f"- {a}" for a in actions)
    else:
        lines.append("- (none)")

    lines.extend(["", "## Notes"])
    lines.extend(f"- {n}" for n in notes)
    lines.extend(
        [
            "",
            "## Mandatory tool chain",
            "1. `usage-brief <slice>` before reads",
            "2. `outline` / `symbol` before full file read",
            "3. `cheap-check` after edits",
            "4. `token-minimize` after index/prompt changes",
            "",
            "Policy: docs/AGENT_STABLE.md § Mandatory minimization · § Continuous minimization",
        ]
    )

    content = "\n".join(lines) + "\n"
    with open(LATEST, "w", encoding="utf-8") as fh:
        fh.write(content)

    if not quiet:
        print("Dodgeville PD — token improve")
        print("=" * 60)
        for a in actions:
            print(f"  → {a}")
        for n in notes:
            print(f"  · {n}")
        print("=" * 60)
        print("Report: logs/token_improve/latest.md")
        if actions:
            print("token-improve: ACTION ITEMS — implement then `python dev.py token-audit --strict`")
            return 1
        print("token-improve: no new action items")
    return 0


if __name__ == "__main__":
    import sys

    apply = "--apply" in sys.argv
    quiet = "--quiet" in sys.argv
    raise SystemExit(run_token_improve(apply_fix=apply, quiet=quiet))
