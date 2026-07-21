"""
Unified verification — single source of truth for all gates.

Tiers are strict supersets (no conflicting signals):
  core      → imports + product core unittests           (~30–60s) — logic/UI edit day-to-day
  fast      → imports, audit, core-test, readiness       (~45–90s) — after each edit
  preflight → + slice-check + graphify                   (~1–2m)   — pre-commit / handoff
  check     → preflight + rust + product test + scenarios (~3m)    — ship / CI
  full      → check + smoke + ui-smoke                   (~5m)     — release candidate
  release   → full + ui-exhaustive                       (~15m)    — full regression
  agent-meta → imports + agent tooling tests only        (~30s)    — policy/token/route edits

honest_gate true only for check|full|release.
Product `test` step excludes tests/agent_meta/ (run via --tier agent-meta).
fast/core/preflight green ≠ ship. Audit 10/10 ≠ product health.

State: logs/last_verify.json (also mirrored to logs/last_gate.json for startup UI)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from typing import Callable, List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERIFY_STATE_PATH = os.path.join(ROOT, "logs", "last_verify.json")
GATE_STATE_PATH = os.path.join(ROOT, "logs", "last_gate.json")

IMPORT_MODULES = [
    "config",
    "models",
    "database",
    "validators",
    "auth_password",
    "logic",
    "analytics",
    "ui.app",
    "main",
    "cli",
    "audit",
]

# Product core — real domain asserts (not agent-meta / tier-structure tests).
CORE_TEST_MODULES: List[str] = [
    "tests.test_logic",
    "tests.test_validators",
    "tests.test_regressions",
    "tests.test_simulator_constraints",
    "tests.test_coverage_optimizer",
    "tests.test_payroll",
]

# Concrete steps only — tiers expand these lists (no duplicate steps).
STEP_CORE: List[str] = ["imports", "core-test"]
STEP_FAST: List[str] = ["imports", "audit", "core-test", "readiness"]
STEP_PREFLIGHT: List[str] = [
    "imports",
    "slice-check",
    "audit",
    "core-test",
    "readiness",
    "graphify",
]
STEP_CHECK: List[str] = STEP_PREFLIGHT + ["rust-backend", "test", "scenarios"]
STEP_FULL: List[str] = STEP_CHECK + ["smoke", "ui-workflow", "ui-smoke"]
STEP_RELEASE: List[str] = STEP_FULL + ["ui-exhaustive"]

STEP_AGENT_META: List[str] = ["imports", "agent-meta-test"]

TIERS: dict[str, List[str]] = {
    "core": STEP_CORE,
    "fast": STEP_FAST,
    "preflight": STEP_PREFLIGHT,
    "check": STEP_CHECK,
    "full": STEP_FULL,
    "release": STEP_RELEASE,
    "agent-meta": STEP_AGENT_META,
}

TIER_ALIASES = {
    "cheap-check": "fast",
    "cheap_check": "fast",
}

HONEST_TIERS = frozenset({"check", "full", "release"})


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_frozen() -> bool:
    try:
        from paths import is_frozen

        return is_frozen()
    except ImportError:
        return getattr(sys, "frozen", False)


def _step_imports() -> int:
    for name in IMPORT_MODULES:
        __import__(name)
        print(f"  ok: {name}")
    print("All imports successful.")
    return 0


def _step_audit() -> int:
    from audit import print_report, run_audit

    return print_report(run_audit())


def _step_core_test() -> int:
    """Product-core unittests only — fails when domain logic regresses."""
    print("  core-test modules:", flush=True)
    for mod in CORE_TEST_MODULES:
        print(f"    {mod}", flush=True)
    result = subprocess.run(
        [sys.executable, "-m", "unittest", *CORE_TEST_MODULES, "-v"],
        cwd=ROOT,
    )
    return result.returncode


def _step_slice_check() -> int:
    from scripts.vertical_slices import run_slice_check

    return run_slice_check(strict=False)


def _step_readiness() -> int:
    from scripts.readiness_check import run_readiness_check

    return run_readiness_check()


def _suite_without_agent_meta(suite: "unittest.TestSuite") -> "unittest.TestSuite":
    """Drop tests under tests.agent_meta from a discovered suite."""
    import unittest

    out = unittest.TestSuite()
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            filtered = _suite_without_agent_meta(item)
            if filtered.countTestCases():
                out.addTest(filtered)
            continue
        test_id = item.id()
        # e.g. tests.agent_meta.test_token_audit.TokenAuditTests.test_...
        if test_id.startswith("tests.agent_meta.") or ".agent_meta." in test_id:
            continue
        out.addTest(item)
    return out


def _step_test() -> int:
    """Product unittest discover — excludes tests/agent_meta (tooling meta)."""
    import unittest

    loader = unittest.TestLoader()
    raw = loader.discover("tests", pattern="test_*.py", top_level_dir=ROOT)
    suite = _suite_without_agent_meta(raw)
    print(
        f"  product suite: {suite.countTestCases()} cases (agent_meta excluded — use --tier agent-meta)",
        flush=True,
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


def _step_agent_meta_test() -> int:
    """Agent/tooling meta-tests only (token, route, verify structure)."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "unittest",
            "discover",
            "-s",
            "tests/agent_meta",
            "-t",
            ROOT,
            "-v",
        ],
        cwd=ROOT,
    )
    return result.returncode


def _step_scenarios() -> int:
    from scripts.scenarios import run_scenarios

    return run_scenarios()


def _step_smoke() -> int:
    from scripts.smoke_test import run_smoke

    return run_smoke()


def _step_ui_smoke() -> int:
    """Subprocess — isolate Tk teardown from later ui-exhaustive in release tier."""
    result = subprocess.run(
        [sys.executable, os.path.join(ROOT, "scripts", "ui_smoke_test.py")],
        cwd=ROOT,
    )
    return result.returncode


def _step_rust_backend() -> int:
    from logic import rust_bridge

    name = rust_bridge.backend_name()
    if name != "rust":
        print(f"  [FAIL] scheduling backend is {name!r} — run: python dev.py build-rust")
        err = rust_bridge.load_error()
        if err:
            print(f"  detail: {err}")
        return 1
    print(f"  ok: scheduling backend ({name})")
    return 0


def _step_ui_workflow() -> int:
    """Subprocess — headless Tk teardown must not poison in-process ui-smoke login probe."""
    result = subprocess.run(
        [sys.executable, os.path.join(ROOT, "scripts", "ui_workflow_probe.py")],
        cwd=ROOT,
    )
    return result.returncode


def _step_ui_exhaustive() -> int:
    """Subprocess — fresh Tk root; must not share process with ui-smoke."""
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    # Stream stdout live — capture_output can deadlock on long [ok] step output.
    result = subprocess.run(
        [sys.executable, "-u", os.path.join(ROOT, "scripts", "ui_exhaustive_test.py")],
        cwd=ROOT,
        env=env,
    )
    return result.returncode


def _step_refactor_check() -> int:
    from scripts.refactor_check import run_refactor_check

    return run_refactor_check()


def _step_graphify() -> int:
    """Keep central knowledge graph current (code-only AST; free)."""
    from scripts.graphify_gate import run_graphify_gate

    return run_graphify_gate(force=False, strict=True, quiet=False)


_STEP_RUNNERS: dict[str, Callable[[], int]] = {
    "imports": _step_imports,
    "audit": _step_audit,
    "core-test": _step_core_test,
    "agent-meta-test": _step_agent_meta_test,
    "slice-check": _step_slice_check,
    "readiness": _step_readiness,
    "readiness-check": _step_readiness,
    "test": _step_test,
    "scenarios": _step_scenarios,
    "smoke": _step_smoke,
    "ui-smoke": _step_ui_smoke,
    "ui-workflow": _step_ui_workflow,
    "rust-backend": _step_rust_backend,
    "ui-exhaustive": _step_ui_exhaustive,
    "refactor-check": _step_refactor_check,
    "graphify": _step_graphify,
}


def tier_steps(tier: str, *, with_refactor: bool = False) -> List[str]:
    key = TIER_ALIASES.get(tier, tier)
    if key not in TIERS:
        raise ValueError(f"Unknown tier {tier!r}; choose from {sorted(TIERS)}")
    steps = list(TIERS[key])
    if with_refactor and "refactor-check" not in steps:
        steps.append("refactor-check")
    return steps


def is_subset(child: str, parent: str) -> bool:
    """True when every child step appears in parent tier in the same relative order."""
    child_steps = tier_steps(child)
    parent_steps = tier_steps(parent)
    pi = 0
    for step in child_steps:
        while pi < len(parent_steps) and parent_steps[pi] != step:
            pi += 1
        if pi >= len(parent_steps):
            return False
        pi += 1
    return True


def write_verify_state(
    *,
    tier: str,
    passed: bool,
    failed_steps: List[str],
    duration_sec: float,
    source: str = "",
) -> None:
    os.makedirs(os.path.dirname(VERIFY_STATE_PATH), exist_ok=True)
    payload = {
        "timestamp": _utc_now(),
        "tier": tier,
        "passed": passed,
        "failed_steps": failed_steps,
        "steps": tier_steps(tier),
        "duration_sec": round(duration_sec, 1),
        "source": source,
        "honest_gate": tier in HONEST_TIERS,
    }
    with open(VERIFY_STATE_PATH, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)

    # Mirror for startup_gates GUI warning (backward compatible).
    gate_payload = {
        "timestamp": payload["timestamp"],
        "passed": passed,
        "mode": tier,
        "source": source or "verify",
        "command": f"verify --tier {tier}",
        "failed_steps": failed_steps,
    }
    with open(GATE_STATE_PATH, "w", encoding="utf-8") as fh:
        json.dump(gate_payload, fh, indent=2)


def read_verify_state() -> dict:
    if not os.path.isfile(VERIFY_STATE_PATH):
        return {}
    try:
        with open(VERIFY_STATE_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return {}


def run_tier(
    tier: str,
    *,
    with_refactor: bool = False,
    source: str = "",
    quiet: bool = False,
) -> int:
    """Run a verification tier. Returns 0 on success."""
    import time

    key = TIER_ALIASES.get(tier, tier)
    if key not in TIERS:
        print(f"Unknown tier: {tier!r}. Choose: {', '.join(sorted(TIERS))}")
        return 1

    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    os.chdir(ROOT)

    steps = tier_steps(key, with_refactor=with_refactor)
    label = key if key == tier else f"{tier} ({key})"
    honest = key in HONEST_TIERS
    if not quiet:
        print(f"Dodgeville PD Scheduler — verify:{label}")
        print("=" * 60)
        if not honest:
            print(
                "HONEST_GATE: false — this tier is NOT ship-ready.\n"
                "  • full unittest discover runs only on: check | full | release\n"
                "  • audit 10/10 = historical regressions only (not product health)\n"
                "  • after logic/validators/gui/database edits: prefer --tier core or check\n"
                "  • ship claim only: verify --tier check  →  honest_gate: true\n"
                f"  • steps this run: {', '.join(steps)}"
            )
            print("-" * 60)

    failed: List[str] = []
    started = time.time()

    for name in steps:
        if not quiet:
            print(f"\n>>> {name}", flush=True)
        runner = _STEP_RUNNERS.get(name)
        if runner is None:
            print(f"  [skip] unknown step {name!r}")
            failed.append(name)
            continue
        try:
            code = runner()
        except Exception as exc:
            print(f"  [error] {name}: {exc}")
            code = 1
        if code != 0:
            failed.append(name)

    duration = time.time() - started
    write_verify_state(
        tier=key,
        passed=not failed,
        failed_steps=failed,
        duration_sec=duration,
        source=source,
    )

    if not quiet:
        print("\n" + "=" * 60)
        if failed:
            print(f"verify:{label}: FAILED — {', '.join(failed)}")
            print("Next: python dev.py fix-hint")
            if not honest:
                print(f"Note: {key} is not a ship gate — run: python dev.py verify --tier check")
        else:
            print(f"verify:{label}: ALL PASSED ({duration:.0f}s)")
            if not honest:
                print("HONEST_GATE: still false — do not claim fixed/ship on this tier alone.")
            else:
                print("HONEST_GATE: true (ship-eligible tier; Chronos UI still needs scenario proof).")
    return 1 if failed else 0


# Thin wrappers — existing commands delegate here (no divergent step lists).
def run_fast(**kwargs) -> int:
    return run_tier("fast", **kwargs)


def run_preflight(**kwargs) -> int:
    return run_tier("preflight", **kwargs)


def run_check(**kwargs) -> int:
    return run_tier("check", **kwargs)


def run_full(**kwargs) -> int:
    return run_tier("full", **kwargs)


def run_release(**kwargs) -> int:
    return run_tier("release", **kwargs)
