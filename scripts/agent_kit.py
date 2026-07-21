"""One free command: minimal agent bootstrap (token-first, caveman)."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "logs" / "agent_kit"
LATEST = OUT_DIR / "latest.md"


def _run(cmd: List[str], timeout: int = 60) -> str:
    try:
        r = subprocess.run(
            cmd,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "SCHEDULER_SKIP_AGENT_GATES": "1"},
        )
        out = (r.stdout or "") + (r.stderr or "")
        return out.strip()
    except Exception as exc:
        return f"(failed: {exc})"


def _head(text: str, n: int = 20) -> str:
    lines = text.splitlines()
    if len(lines) <= n:
        return text
    return "\n".join(lines[:n]) + f"\n… ({len(lines) - n} more)"


def run_agent_kit(
    *,
    slice_id: str = "",
    task: str = "",
    quiet: bool = False,
) -> int:
    os.chdir(ROOT)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    py = sys.executable

    sid = (slice_id or "").strip() or "general"
    route = ""
    if task:
        route = _run([py, "dev.py", "route-task", "--json", task], timeout=30)

    brief = _run([py, "dev.py", "usage-brief", sid], timeout=30)

    ts = datetime.now(timezone.utc).isoformat()
    body = f"""# Agent kit
Generated: {ts}

## Paste
`@logs/agent_kit/latest.md` + `@logs/agent_pack/latest.md` + `@docs/AGENT_STABLE.md`

## Rules (auto-abide) — FIRST
- **Caveman:** short bullets. No preamble/recap/let-me. Prose only if user asks explain/docs.
- **Token min:** fewest tools that finish fully+well. Parallel OK when it wins.
- **Cost split:** easy → cheap/free; hard product/logic → primary. Prefer lower total usage.
- Chain: `route-task` once → skill if helpful → edit/delegate → `verify --tier fast|core|check`
- Tools/skills/subagents OK if cheaper/better. Gates/graphify/vision OK if cheaper than primary.
- Archived skills: use then put back. Ship: `verify --tier check` + honest_gate true.

- ONLY this Chronos Workspace — NEVER MyProject.

## Free cmds
| Need | Cmd |
|------|-----|
| Route | `python dev.py route-task "…"` |
| Slice | `python dev.py usage-brief <slice>` |
| Outline | `python dev.py outline path.py` |
| Ship | `python dev.py verify --tier check` |

## Route
```
{_head(route or "(pass --task for route)", 8)}
```

## Brief ({sid})
```
{_head(brief, 12)}
```
"""
    LATEST.write_text(body, encoding="utf-8")
    if not quiet:
        print(body)
        print(f"\nWrote {LATEST}")
    else:
        print(LATEST)
    return 0
