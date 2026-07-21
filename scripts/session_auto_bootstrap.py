#!/usr/bin/env python3
"""Auto-run at every new agent session (Grok/Cursor hook or launcher).

Refreshes lean kit/pack + SESSION_CONTRACT.md. No graphify tax.
Safe to call from any cwd; only acts when workspace is Chronos Workspace / MyProject
(or SCHEDULER_FORCE_BOOTSTRAP=1).
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "logs" / "SESSION_CONTRACT.md"
KIT = ROOT / "logs" / "agent_kit" / "latest.md"
PACK = ROOT / "logs" / "agent_pack" / "latest.md"

CONTRACT_BODY = """# Session contract (auto)

Bound by `AGENTS.md`. Always-on rules: `.grok/rules/auto-minimize.md` + `verify-policy.md`.
Domain cards: `.grok/rules/on-demand/` (load only when needed).

## 0) Caveman (ABSOLUTE)
Short bullets only. No preamble/recap/"let me". Prose only if user asks explain/docs.
Proof footer after non-trivial work. One question max when blocked.

## 1) Token minimize (ABSOLUTE)
Fewest tools that still finish **fully and well**. Prefer 1 thing at a time; parallel OK when it clearly wins.
`route-task` once → skill if helpful → edit (or delegate easy) → gate:
- light → `verify --tier fast`
- logic/validators/gui/database → `verify --tier core` then ship `check`
Ship only: `verify --tier check` + `logs/last_verify.json` → `honest_gate: true`
Never claim done on fast. Audit 10/10 = historical only (not product health).

## 1b) Cost split + leverage
Easy/mechanical → cheap/free agents or models. Hard product/logic/ship → **primary agent**.
Tools / skills / subagents **allowed** when they improve quality/speed **or cost less than primary**.
Verify/gates, graphify, vision OK **if cheaper / better ROI** than primary. Full: `.grok/rules/on-demand/subagents.md`

## 2) Trust
`docs/AGENT_TRUST_AND_MISTAKES.md` — prove user scenario before "fixed". Unit ≠ Chronos.
User numbers first (8h/2008h/6-2,5-3 were debug examples, not fixed product defaults).

## 3) Hard bans
Archived skills stay archived except while in use (then put back) · no thrash graphify/vision · kill processes you start · one Chronos on :8080

## 4) Product
`gui/` Chronos · `logic/*` + validators · no SQL in gui · brand via theme (not all-caps APP_NAME)
Simulator: `gui/pages/simulator/` · UAT: this tree always-on · proof: `scripts/_sim_path_proof.py`

## 5) Landing
**Only** `logs/NEXT_SESSION_BRIEF.md` for residuals. Trust file for mistakes.

Generated: {ts}
"""


# Known workspace folder names for this project
_WORKSPACE_NAMES = ("myproject", "chronos workspace", "chronos_workspace")


def _is_myproject_workspace() -> bool:
    if os.environ.get("SCHEDULER_FORCE_BOOTSTRAP", "").strip() in ("1", "true", "yes"):
        return True
    markers = (
        os.environ.get("GROK_WORKSPACE_ROOT", ""),
        os.environ.get("CLAUDE_PROJECT_DIR", ""),
        os.getcwd(),
    )
    root_s = str(ROOT).lower().replace("/", "\\")
    for m in markers:
        if not m:
            continue
        p = str(Path(m).resolve()).lower().replace("/", "\\")
        if p == root_s or p.startswith(root_s + "\\"):
            return True
        leaf = Path(m).resolve().name.lower()
        if leaf in _WORKSPACE_NAMES and any(w in root_s for w in _WORKSPACE_NAMES):
            return True
    # Always match if cwd is under ROOT
    try:
        Path(os.getcwd()).resolve().relative_to(ROOT)
        return True
    except ValueError:
        pass
    return False


def run_bootstrap(*, quiet: bool = True) -> int:
    if not _is_myproject_workspace():
        if not quiet:
            print("session_auto_bootstrap: skip (not Chronos/MyProject workspace)")
        return 0

    os.chdir(ROOT)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    slice_id = os.environ.get("SCHEDULER_SLICE", "").strip() or "general"
    task = os.environ.get("SCHEDULER_AGENT_TASK", "").strip() or "Session auto-bootstrap — Chronos token-min"

    # Soft gates (never fail session open)
    try:
        from scripts.agent_gates import run_agent_gates

        run_agent_gates(
            source="session-auto",
            command="SessionStart",
            quiet=True,
            force=True,
            debounce_sec=0,
        )
    except Exception:
        pass

    try:
        from scripts.agent_kit import run_agent_kit

        run_agent_kit(slice_id=slice_id, task=task, quiet=True)
    except Exception as exc:
        if not quiet:
            print(f"agent-kit failed: {exc}")

    try:
        from scripts.agent_pack import run_agent_pack

        run_agent_pack(task=task, slice_id=slice_id, quiet=True)
    except Exception:
        pass

    try:
        from scripts.context_window import set_task

        set_task(task)
    except Exception:
        pass

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    CONTRACT.parent.mkdir(parents=True, exist_ok=True)
    CONTRACT.write_text(CONTRACT_BODY.format(ts=ts), encoding="utf-8")

    if not quiet:
        print(f"session_auto_bootstrap: kit={KIT} contract={CONTRACT}")
    return 0


def cursor_session_start_json() -> dict:
    """Cursor-compatible SessionStart stdout payload (if host honors it)."""
    pack_est = 0
    if PACK.is_file():
        pack_est = max(1, len(PACK.read_text(encoding="utf-8", errors="replace")) // 4)
    context = (
        "SESSION CONTRACT ACTIVE (auto).\n"
        "=== FIRST: CAVEMAN + TOKEN MIN (ABSOLUTE) ===\n"
        "Caveman: short bullets only. No preamble/recap/let-me. Prose only if user asks explain/docs.\n"
        "Minimize: fewest tools that finish fully+well. Parallel OK when it wins. Easy→cheap; hard→primary.\n"
        "Chain: route-task once → skill if helpful → edit/delegate → verify --tier fast|core|check.\n"
        "Tools/skills/subagents OK if cheaper or better. Gates/graphify/vision OK if cheaper than primary.\n"
        "Archived skills: use then put back. Ship: check + honest_gate true. @.grok/rules/auto-minimize.md\n"
        f"Obey @AGENTS.md | @logs/SESSION_CONTRACT.md | @logs/agent_pack/latest.md (~{pack_est}t).\n"
        "TRUST: @docs/AGENT_TRUST_AND_MISTAKES.md — never claim fixed without user-scenario proof. Unit!=Chronos.\n"
        f"LANDINGS/RESIDUALS: @logs/NEXT_SESSION_BRIEF.md | @docs/HANDOFF.md NEXT SESSION\n"
        "Workspace: C:\\Users\\Windows\\Chronos Workspace only — NEVER MyProject.\n"
        "Always-on :8080 = this tree (ChronosAlwaysOnUAT). One Chronos only.\n"
        "Simulator package: gui/pages/simulator/ (page.py still holds Requirements form + optimizer actions).\n"
        "User numbers first; 8h/2008h/6-2,5-3 are example numbers to fix sim logic — NOT fixed constraints.\n"
        "Proof: scripts/_sim_path_proof.py · tests.test_simulator_constraints · verify --tier fast|check.\n"
        "Open residual: Requirements form still in page.py; live SMS/email deferred; LDAP untested.\n"
    )
    return {
        "continue": True,
        "additional_context": context,
        "agent_message": context,
    }


def main() -> int:
    # Consume stdin (hook payload) if present and requested by environment
    if not sys.stdin.isatty() and os.environ.get("GROK_HOOK_EVENT"):
        try:
            json.load(sys.stdin)
        except Exception:
            pass

    code = run_bootstrap(quiet=True)

    # Cursor / some hosts read additional_context from SessionStart stdout
    event = (os.environ.get("GROK_HOOK_EVENT") or "").lower()
    is_cursor = bool(os.environ.get("CURSOR_TRACE_ID"))
    if event in ("session_start", "sessionstart") or is_cursor:
        print(json.dumps(cursor_session_start_json()))
    else:
        sys.stdout.buffer.write(b"============================================================\n")
        sys.stdout.buffer.write(b"SESSION BOOTSTRAP: ACTIVE CONTEXT\n")
        sys.stdout.buffer.write(b"============================================================\n")
        for fpath, name in [
            (CONTRACT, "RULES & CONTRACT"),
            (PACK, "DYNAMIC PACK"),
            (ROOT / "docs" / "AGENT_TRUST_AND_MISTAKES.md", "TRUST & MISTAKES"),
            (ROOT / "logs" / "NEXT_SESSION_BRIEF.md", "NEXT SESSION BRIEF"),
        ]:
            if fpath.is_file():
                sys.stdout.buffer.write(f"\n--- {name} ---\n".encode("utf-8"))
                sys.stdout.buffer.write(fpath.read_bytes())
                sys.stdout.buffer.write(b"\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
