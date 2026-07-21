"""Ensure graphify knowledge graph exists and stays current (code-only AST, free).

Used by verify tiers and agents. Graph is the central project map — code, structure,
and (via GRAPH_REPORT + linked sources) orientation for product/process questions.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
GRAPH_JSON = ROOT / "graphify-out" / "graph.json"
GRAPH_REPORT = ROOT / "graphify-out" / "GRAPH_REPORT.md"

# Paths that invalidate the graph when newer than graph.json
WATCH_GLOBS: Sequence[str] = (
    "logic/**/*.py",
    "gui/**/*.py",
    "ui/**/*.py",
    "validators.py",
    "validators_config.py",
    "config.py",
    "database.py",
    "cli.py",
    "models.py",
    "permissions.py",
    "slices/**/*.py",
    "docs/**/*.md",
    "AGENTS.md",
    "CLAUDE.md",
    "Agents.md",
    ".grok/rules/**/*.md",
    "rust/scheduler_core/src/**/*.rs",
)

SKIP_NAME_PARTS = (
    "FULL_PROJECT_CODE",
    "/__pycache__/",
    "\\__pycache__\\",
    "/.git/",
    "\\/.git\\",
    "graphify-out",
)


def _find_graphify() -> Optional[List[str]]:
    """Return argv prefix to run graphify CLI."""
    which = shutil.which("graphify")
    if which:
        return [which]
    home = Path.home()
    for candidate in (
        home / ".local" / "bin" / "graphify.exe",
        home / ".local" / "bin" / "graphify",
        Path(os.environ.get("USERPROFILE", "")) / ".local" / "bin" / "graphify.exe",
        Path(os.environ.get("APPDATA", "")) / "Python" / "Python314" / "Scripts" / "graphify.exe",
    ):
        if candidate.is_file():
            return [str(candidate)]
    # uv tool run fallback
    uv = shutil.which("uv")
    if uv:
        return [uv, "tool", "run", "--from", "graphifyy", "graphify"]
    return None


def _iter_watched_files() -> Iterable[Path]:
    for pattern in WATCH_GLOBS:
        if "*" in pattern or "?" in pattern:
            for p in ROOT.glob(pattern):
                if p.is_file():
                    rel = str(p.relative_to(ROOT)).replace("\\", "/")
                    if any(s in rel or s in str(p) for s in SKIP_NAME_PARTS):
                        continue
                    if "FULL_PROJECT_CODE" in p.name:
                        continue
                    yield p
        else:
            p = ROOT / pattern
            if p.is_file():
                yield p


def _newest_watched() -> Tuple[float, Optional[Path]]:
    newest_m = 0.0
    newest_p: Optional[Path] = None
    for p in _iter_watched_files():
        try:
            m = p.stat().st_mtime
        except OSError:
            continue
        if m > newest_m:
            newest_m = m
            newest_p = p
    return newest_m, newest_p


def graph_stale(grace_sec: float = 2.0) -> Tuple[bool, str]:
    """Return (stale, reason). Missing graph counts as stale."""
    if not GRAPH_JSON.is_file():
        return True, "graphify-out/graph.json missing"
    try:
        g_m = GRAPH_JSON.stat().st_mtime
    except OSError:
        return True, "cannot stat graph.json"
    src_m, src_p = _newest_watched()
    if src_m > g_m + grace_sec:
        rel = src_p.relative_to(ROOT).as_posix() if src_p else "?"
        return True, f"stale vs {rel}"
    return False, "ok"


def _node_count() -> int:
    try:
        data = json.loads(GRAPH_JSON.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    if isinstance(data, dict):
        nodes = data.get("nodes")
        if isinstance(nodes, list):
            return len(nodes)
        if isinstance(nodes, dict):
            return len(nodes)
        # networkx node-link sometimes uses "nodes" at top or nested
        g = data.get("graph")
        if isinstance(g, dict) and isinstance(g.get("nodes"), list):
            return len(g["nodes"])
    return 0


def rebuild_graph(*, quiet: bool = False) -> int:
    """Run code-only extract (no API key). Returns process exit code (0 = ok)."""
    cmd_base = _find_graphify()
    if not cmd_base:
        print("  graphify: CLI not found — install: uv tool install graphifyy")
        print("  (or: pipx install graphifyy)")
        return 1
    cmd = cmd_base + ["extract", str(ROOT), "--code-only", "--no-viz"]
    if not quiet:
        print(f"  graphify: {' '.join(cmd)}")
    env = os.environ.copy()
    # Prefer free local path
    env.setdefault("GRAPHIFY_CODE_ONLY", "1")
    result = subprocess.run(
        cmd,
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    # graphify may exit non-zero with warnings while still writing graph.json
    out = (result.stdout or "") + (result.stderr or "")
    if not quiet and out.strip():
        # Last few lines only
        lines = [ln for ln in out.splitlines() if ln.strip()][-8:]
        for ln in lines:
            print(f"  {ln}")
    if GRAPH_JSON.is_file() and _node_count() > 0:
        if result.returncode != 0 and not quiet:
            print("  graphify: CLI warned but graph.json is present — treating as OK")
        return 0
    return result.returncode if result.returncode != 0 else 1


def write_knowledge_hub() -> None:
    """Small agent entry file: where to look for all project knowledge."""
    out_dir = ROOT / "graphify-out"
    out_dir.mkdir(parents=True, exist_ok=True)
    hubs = [
        ("graphify-out/graph.json", "Queryable knowledge graph (code structure + links)"),
        ("graphify-out/GRAPH_REPORT.md", "God nodes, communities, suggested questions"),
        ("graphify-out/graph.html", "Interactive browser map"),
        ("docs/HANDOFF.md", "Session memory / product status"),
        ("docs/AGENT_STABLE.md", "Agent policy & verify ladder"),
        ("docs/AGENT_TOOLKIT.md", "Free tools hub"),
        ("docs/knowledge/", "FR / math / UI research deposits"),
        ("AGENTS.md", "Always-on agent rules (graphify-first)"),
        ("CLAUDE.md", "Claude multi-agent + tool notes"),
        ("slices/registry.py", "Vertical slice map"),
        (".grok/rules/", "Domain cards (UI, scheduling math, …)"),
    ]
    n = _node_count() if GRAPH_JSON.is_file() else 0
    lines = [
        "# Project knowledge hub (agent entry)",
        "",
        "Prefer this map **before** bulk-reading the repo.",
        "",
        f"- Graph nodes (last extract): **{n}**",
        "",
        "## Query first",
        "",
        "```bash",
        'graphify query "<any project question — code, product, process, architecture>"',
        'graphify path "A" "B"',
        'graphify explain "Concept"',
        "```",
        "",
        "## Knowledge sources",
        "",
    ]
    for path, desc in hubs:
        lines.append(f"- `{path}` — {desc}")
    lines.extend(
        [
            "",
            "## Rebuild",
            "",
            "```bash",
            "graphify extract . --code-only   # free, local AST",
            "python dev.py graphify-gate      # ensure fresh for verify",
            "```",
            "",
            "Scope is **all project knowledge** agents need: structure, coupling,",
            "where features live, and pointers into docs/rules — not only 'coding trivia'.",
            "",
        ]
    )
    (out_dir / "KNOWLEDGE_HUB.md").write_text("\n".join(lines), encoding="utf-8")


def run_graphify_gate(
    *,
    force: bool = False,
    strict: bool = True,
    quiet: bool = False,
) -> int:
    """
    Ensure graph is present and not stale; rebuild if needed.

    strict=True → missing CLI or failed rebuild fails the gate.
    """
    if not quiet:
        print("Dodgeville PD — graphify knowledge gate")
        print("=" * 56)

    stale, reason = graph_stale()
    if force:
        stale, reason = True, "force rebuild"

    if not stale:
        n = _node_count()
        if not quiet:
            print(f"  [ok] graph current ({n} nodes) — {reason}")
        write_knowledge_hub()
        if not quiet:
            print("  [ok] graphify-out/KNOWLEDGE_HUB.md")
            print("=" * 56)
        return 0

    if not quiet:
        print(f"  graphify: rebuild needed ({reason})")
    code = rebuild_graph(quiet=quiet)
    if code != 0:
        if strict:
            print("  [FAIL] graphify rebuild failed")
            return 1
        print("  [warn] graphify rebuild failed (non-strict)")
        return 0

    if not GRAPH_JSON.is_file() or _node_count() < 1:
        print("  [FAIL] graph.json empty or missing after rebuild")
        return 1 if strict else 0

    write_knowledge_hub()
    n = _node_count()
    if not quiet:
        print(f"  [ok] graph rebuilt ({n} nodes)")
        print("  [ok] graphify-out/KNOWLEDGE_HUB.md")
        print("=" * 56)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="Ensure graphify project knowledge graph is current")
    p.add_argument("--force", action="store_true", help="Always rebuild")
    p.add_argument("--soft", action="store_true", help="Warn only if rebuild fails")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)
    return run_graphify_gate(force=args.force, strict=not args.soft, quiet=args.quiet)


if __name__ == "__main__":
    raise SystemExit(main())
