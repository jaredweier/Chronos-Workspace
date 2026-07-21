"""Verification policy — canonical gates and anti-patterns (single source for dev.py help)."""

from __future__ import annotations

VERIFY_LADDER = """
Verification tiers (strict supersets — use only these for ship claims):

  python dev.py verify --tier core       (~30–60s) product core unittests (not ship)
  python dev.py verify --tier fast       (~45–90s) after each edit (audit + core-test + readiness)
  python dev.py verify --tier preflight  (~1–2m)   pre-commit / handoff
  python dev.py verify --tier check      (~3m)     ship gate (honest_gate; product tests only)
  python dev.py verify --tier full       (~5m)     release candidate
  python dev.py verify --tier release    (~5–40m)  full regression + ui-exhaustive (82 steps)
  python dev.py verify --tier agent-meta (~30s)    token/route/verify tooling tests only

honest_gate true only on check|full|release. Audit 10/10 = historical only.
Ship discover excludes tests/agent_meta/. Aliases: cheap-check → fast

UI exhaustive (canonical — do not pipe through Select-Object):

  python dev.py ui-exhaustive
  python -u scripts/ui_exhaustive_test.py

Log + honest exit code on PowerShell:

  python -u scripts/ui_exhaustive_test.py *> logs/ui_exhaustive_run.log
  Write-Output "EXH:$LASTEXITCODE"
""".strip()

ANTI_PATTERNS = """
Avoid (false failures, hangs, deadlocks):

  • python scripts/ui_exhaustive_test.py 2>&1 | Select-Object -Last N
  • Inline python -c headless_login / role-session probes without exhaustive harness
  • Stop-Process on all python* before ui-exhaustive or verify --tier release
  • Claiming ship-ready on fast/preflight when logic, validators, or ui/* changed
  • Concurrent ui-exhaustive or release runs (use logs/.ui_exhaustive.lock)
""".strip()


def print_verify_help() -> int:
    print("Dodgeville PD — verification policy")
    print("=" * 60)
    print(VERIFY_LADDER)
    print()
    print(ANTI_PATTERNS)
    print("=" * 60)
    print("State: logs/last_verify.json (honest_gate true only at check/full/release)")
    return 0


def print_ui_exhaustive_banner() -> None:
    print("Canonical: python dev.py ui-exhaustive (no PowerShell pipes)")
    print("Policy:    python dev.py verify-help")
    print("-" * 60)
