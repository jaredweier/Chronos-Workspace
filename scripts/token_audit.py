"""Verify token-minimization artifacts and settings — no LLM required."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import List

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""


def _exists(rel: str) -> bool:
    return os.path.isfile(os.path.join(ROOT, rel)) or os.path.isdir(os.path.join(ROOT, rel))


def _read(rel: str) -> str:
    path = os.path.join(ROOT, rel)
    if not os.path.isfile(path):
        return ""
    with open(path, encoding="utf-8", errors="replace") as fh:
        return fh.read()


def _cursorignore_blocks_large_dump() -> Check:
    text = _read(".cursorignore")
    ok = "FULL_PROJECT_CODE" in text or "docs/FULL_PROJECT_CODE.txt" in text
    return Check(
        "cursorignore excludes FULL_PROJECT_CODE dump",
        ok,
        "add docs/FULL_PROJECT_CODE.txt to .cursorignore" if not ok else "ok",
    )


def _opencode_minimal() -> List[Check]:
    checks: List[Check] = []
    raw = _read("opencode.json")
    if not raw:
        checks.append(Check("opencode.json present", False))
        return checks
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        checks.append(Check("opencode.json valid JSON", False, str(exc)))
        return checks

    instructions = data.get("instructions", [])
    checks.append(
        Check(
            "opencode agent-pack mandate in instructions",
            bool(instructions) and any("agent_pack" in str(i) for i in instructions),
            "add minimal agent_pack mandate to opencode instructions",
        )
    )

    compaction = data.get("compaction", {})
    checks.append(
        Check(
            "opencode compaction.prune enabled",
            compaction.get("prune") is True,
            "set compaction.prune: true",
        )
    )

    watcher = data.get("watcher", {}).get("ignore", [])
    checks.append(
        Check(
            "opencode watcher ignores logs/dist/baselines",
            any("logs" in p for p in watcher) and any("baseline" in p for p in watcher),
            "expand watcher.ignore",
        )
    )

    commands = data.get("command", {})
    for cmd in ("cheap-check", "usage-brief", "fix-hint", "check", "route-task", "context-window"):
        checks.append(
            Check(
                f"opencode /{cmd} command",
                cmd in commands,
                f"add command.{cmd} to opencode.json" if cmd not in commands else "ok",
            )
        )

    return checks


def run_token_audit(*, strict: bool = False) -> int:
    os.chdir(ROOT)
    checks: List[Check] = []

    agents_md = _read("AGENTS.md")
    agents_lower = agents_md.lower()
    checks.append(
        Check(
            "AGENTS.md declares auto-context OFF",
            "auto-context off" in agents_lower or "auto-context is disabled" in agents_lower,
        )
    )
    checks.append(
        Check(
            "AGENTS.md references stable + dynamic packs",
            "AGENT_STABLE.md" in agents_md and "agent_pack/latest.md" in agents_md,
        )
    )
    stable = _read("docs/AGENT_STABLE.md")
    checks.append(
        Check(
            "docs/AGENT_STABLE.md present and has verify ladder",
            bool(stable) and "cheap-check" in stable and "Blocked" in stable,
        )
    )
    checks.append(
        Check(
            "docs/AGENT_STABLE.md has structured output policy",
            bool(stable) and "structured_output.py" in stable,
        )
    )
    checks.append(
        Check(
            "docs/AGENT_STABLE.md has context window policy",
            bool(stable) and "6000" in stable and "ephemeral" in stable.lower(),
        )
    )
    auto_rule = _read(".cursor/rules/auto-minimize.mdc")
    checks.append(
        Check(
            "Cursor auto-minimize alwaysApply",
            "alwaysApply: true" in auto_rule and "agent_pack/latest.md" in auto_rule and "AGENT_STABLE" in auto_rule,
        )
    )
    checks.append(
        Check(
            "Cursor auto-minimize sufficiency rule",
            "Sufficiency" in auto_rule or "sufficiency" in auto_rule.lower(),
        )
    )
    session_hook = _read(".cursor/hooks/session_start.py")
    checks.append(
        Check(
            "session_start hook injects sufficiency",
            "Sufficiency" in session_hook,
        )
    )
    grok_auto = _read(".grok/rules/auto-minimize.md")
    checks.append(
        Check(
            "Grok auto-minimize sufficiency rule",
            bool(grok_auto) and "Sufficiency" in grok_auto and "AGENT_STABLE" in grok_auto,
        )
    )
    for grok_rule in (
        "token-minimization.md",
        "agent-routing.md",
        "subagents.md",
        "architecture.md",
    ):
        text = _read(f".grok/rules/{grok_rule}")
        checks.append(
            Check(
                f"Grok {grok_rule} mirrors policy/sufficiency",
                bool(text)
                and ("AGENT_STABLE" in text or "auto-minimize" in text)
                and ("Sufficiency" in text or "sufficiency" in text.lower()),
            )
        )
    checks.append(_cursorignore_blocks_large_dump())
    ignore = _read(".cursorignore")
    for pattern in ("docs/HANDOFF.md", ".grok/skills/", "SCHEDULING_RULES.md", "*.png"):
        checks.append(
            Check(
                f"cursorignore blocks {pattern}",
                pattern.rstrip("/") in ignore or pattern in ignore,
            )
        )
    agents_lines = len(agents_md.splitlines()) if agents_md else 999
    checks.append(
        Check(
            "AGENTS.md lean (<=20 lines, refs only)",
            agents_lines <= 20,
            f"{agents_lines} lines — refs only; detail in docs/AGENT_STABLE.md",
        )
    )
    checks.append(
        Check(
            "AGENTS.md mandates minimization tools",
            bool(agents_md)
            and ("Minimize" in agents_md or "Caveman" in agents_md)
            and "usage-brief" in agents_md
            and ("route-task" in agents_md or "token-improve" in agents_md),
        )
    )
    stable = _read("docs/AGENT_STABLE.md")
    checks.append(
        Check(
            "AGENT_STABLE has continuous minimization section",
            "Continuous minimization" in stable and "token-improve" in stable,
        )
    )
    checks.extend(_opencode_minimal())

    for rel, label in (
        (".cursor/rules/token-minimization.mdc", "Cursor token-minimization rule"),
        (".cursor/rules/agent-routing.mdc", "Cursor agent-routing rule"),
        (".cursor/commands/preflight.md", "Cursor /preflight command"),
        (".cursor/commands/usage-brief.md", "Cursor /usage-brief command"),
        (".grok/rules/auto-minimize.md", "Grok always-on auto-minimize rule"),
        (".grok/rules/token-minimization.md", "Grok token-minimization rules"),
        (".grok/rules/agent-routing.md", "Grok agent-routing rules"),
        (".grok/skills/qa-verify/SKILL.md", "qa-verify skill"),
        (".grok/skills/ui-development/SKILL.md", "ui-development skill"),
        (".opencode/agents/qa-free.md", "OpenCode qa-free subagent"),
        ("scripts/usage_brief.py", "usage-brief script"),
        ("scripts/agent_pack.py", "agent-pack script"),
        ("scripts/file_outline.py", "outline script"),
        ("scripts/symbol_lookup.py", "symbol lookup script"),
        (".cursor/commands/agent-pack.md", "Cursor /agent-pack command"),
        (".cursor/rules/auto-minimize.mdc", "Cursor always-on auto-minimize rule"),
        ("scripts/agent_gates.py", "automatic agent gates"),
        ("scripts/context_window.py", "context window manager"),
        ("scripts/batch_process.py", "batch process (index-aligned JSON)"),
        ("scripts/structured_output.py", "structured output schemas"),
        ("scripts/token_scan.py", "token-scan script"),
        ("scripts/token_improve.py", "token-improve script"),
        ("scripts/read_guard.py", "read guard for Cursor hooks"),
        (".cursor/hooks.json", "Cursor hooks config"),
        (".cursorindexingignore", "Cursor index exclusions"),
        ("docs/AGENT_STABLE.md", "stable agent policy"),
        ("docs/AGENTS_REFERENCE.md", "on-demand agent reference"),
        ("scripts/cheap_check.py", "cheap-check script"),
        ("scripts/fix_hint.py", "fix-hint script"),
        ("scripts/startup_gates.py", "automatic startup gates"),
        ("slices/registry.py", "vertical slice registry"),
        (".pre-commit-config.yaml", "pre-commit hooks"),
        (".github/workflows/ci.yml", "GitHub Actions CI"),
    ):
        checks.append(Check(label, _exists(rel), rel if not _exists(rel) else "ok"))

    for pattern in ("tests/ui_snapshots/baseline/", "logs/", ".grok/sessions/"):
        checks.append(
            Check(
                f"cursorignore has {pattern}",
                pattern in ignore,
            )
        )
    for pattern in (
        "logic/payroll/timecard.py",
        "logic/scheduling.py",
        "logic/requests.py",
        "cli.py",
        "validators.py",
        "gui/pages/leave.py",
    ):
        checks.append(
            Check(
                f"cursorignore allows large source {pattern}",
                pattern not in ignore,
                "use outline/symbol — do not hide editable source",
            )
        )

    try:
        import sys

        if ROOT not in sys.path:
            sys.path.insert(0, ROOT)
        from scripts.token_scan import scan_large_files

        indexed, _ = scan_large_files(min_kb=50, limit=10)
        # Known large editable sources — outline/symbol required; not index surprises
        allowed_large = {
            "logic/payroll/timecard.py",
            "logic/payroll/period.py",
            "logic/payroll/entries.py",
            "logic/payroll/pay_codes.py",
            "logic/scheduling.py",
            "logic/scheduling_sim.py",
            "logic/requests.py",
            "logic/bidding.py",
            "logic/analytics.py",
            "cli.py",
            "validators.py",
            "validators_config.py",
            "analytics.py",
            "database.py",
            # Chronos NiceGUI finance package + other pages — outline/symbol first
            "gui/pages/finance/timecards.py",
            "gui/pages/finance/payroll_page.py",
            "gui/pages/finance/banks.py",
            "gui/pages/finance/ledger.py",
            "gui/pages/operations.py",
            "gui/pages/leave.py",
            "gui/pages/roster.py",
            "gui/pages/dashboard.py",
            "gui/pages/schedules.py",
            "gui/pages/self_service.py",
            "gui/pages/simulator.py",
        }
        surprise = [e["path"] for e in indexed if e["path"] not in allowed_large]
        checks.append(
            Check(
                "token-scan clean at 50KB (no surprise index files)",
                not surprise,
                f"unexpected: {', '.join(surprise) or 'ok'} — use outline/symbol for allowed large source",
            )
        )
    except Exception as exc:
        checks.append(Check("token-scan clean at 50KB", False, str(exc)))

    pack_src = _read("scripts/agent_pack.py")
    checks.append(
        Check(
            "agent_pack dynamic-only (refs stable, no inline blocked list)",
            "AGENT_STABLE" in pack_src or "docs/AGENT_STABLE.md" in pack_src,
            "agent_pack should reference docs/AGENT_STABLE.md, not inline BLOCKED_READS",
        )
    )
    checks.append(
        Check(
            "agent_pack has no BLOCKED_READS constant",
            "BLOCKED_READS" not in pack_src,
        )
    )

    # --- Auto-abide policy contracts (Phase 0/A) ---
    archive_under_skills = os.path.isdir(os.path.join(ROOT, ".grok", "skills", "_archive"))
    checks.append(
        Check(
            "no .grok/skills/_archive (moved out of skill discovery)",
            not archive_under_skills,
            "move to docs/archived_skills/ so Grok does not inject archive skill cards",
        )
    )
    claude_archive = os.path.isdir(os.path.join(ROOT, ".claude", "skills", "_archive"))
    checks.append(
        Check(
            "no .claude/skills/_archive under discovery",
            not claude_archive,
            "move to docs/archived_skills/claude/",
        )
    )
    demoted = (
        "agent-routing",
        "cost-efficient-workflow",
        "token-discipline",
        "frontend-design",
        "stop-slop",
        "refactor",
        "check-work",
    )
    for name in demoted:
        still = os.path.isdir(os.path.join(ROOT, ".grok", "skills", name))
        checks.append(
            Check(
                f"demoted skill not discoverable: {name}",
                not still,
                f"move .grok/skills/{name} → docs/archived_skills/optional/",
            )
        )
    checks.append(
        Check(
            "AGENTS.md bans archived_skills open",
            "archived_skills" in agents_md.lower() or "archive" in agents_md.lower(),
            "add hard ban: never open docs/archived_skills unless user names skill",
        )
    )
    kit_path = os.path.join(ROOT, "logs", "agent_kit", "latest.md")
    if os.path.isfile(kit_path):
        kit_chars = os.path.getsize(kit_path)
        checks.append(
            Check(
                "agent_kit latest.md lean (<=4500 chars)",
                kit_chars <= 4500,
                f"{kit_chars} chars — trim usage-brief HANDOFF excerpt / kit template",
            )
        )
    try:
        import sys as _sys

        if ROOT not in _sys.path:
            _sys.path.insert(0, ROOT)
        from scripts.agent_route import route_task

        rec_typo = route_task("fix typo on button")
        checks.append(
            Check(
                "route free/cheap typo has empty OSS",
                rec_typo.cost_tier in ("free", "cheap") and not rec_typo.oss_searches and not rec_typo.oss_actions,
                f"cost={rec_typo.cost_tier} oss={rec_typo.oss_searches}",
            )
        )
        checks.append(
            Check(
                "route catalog has no skyvern default",
                "skyvern" not in _read("scripts/agent_route.py").lower()
                or '"skyvern"' not in _read("scripts/agent_route.py"),
                "remove skyvern from AGENT_CATALOG",
            )
        )
        cat = _read("scripts/agent_route.py")
        checks.append(
            Check(
                "AGENT_CATALOG external only playwright (no skyvern/browser-use)",
                '"skyvern"' not in cat and '"browser-use"' not in cat,
                "drop external OSS agents from catalog; keep docs/UI_AGENTS_CATALOG.md",
            )
        )
    except Exception as exc:
        checks.append(Check("route_task policy fixtures", False, str(exc)))

    print("Dodgeville PD — token minimization audit")
    print("=" * 60)
    failed = [c for c in checks if not c.ok]
    for c in checks:
        mark = "ok" if c.ok else "MISSING"
        line = f"  [{mark}] {c.name}"
        if c.detail and not c.ok:
            line += f" — {c.detail}"
        print(line)

    print("\n" + "-" * 60)
    print("Policy: docs/AGENT_STABLE.md · Dynamic: logs/agent_pack/latest.md")
    print("-" * 60)

    score = len(checks) - len(failed)
    print(f"token-audit: {score}/{len(checks)} checks passed")
    if failed:
        print(f"  gaps: {len(failed)} — fix above before claiming full minimization")
        return 1 if strict else 0
    print("token-audit: ALL MINIMIZATION ARTIFACTS PRESENT")
    return 0


if __name__ == "__main__":
    import sys

    strict = "--strict" in sys.argv
    raise SystemExit(run_token_audit(strict=strict))
