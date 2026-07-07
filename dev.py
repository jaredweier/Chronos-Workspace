#!/usr/bin/env python3
"""Development tooling for Dodgeville PD Scheduler."""

import argparse
import os
import subprocess
import sys


def cmd_test(_args):
    # Merge stderr into stdout so PowerShell does not treat unittest's "... ok"
    # progress lines on stderr as a failing native command when output is piped.
    result = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        cwd=os.path.dirname(os.path.abspath(__file__)),
        stderr=subprocess.STDOUT,
    )
    return result.returncode


def cmd_audit(_args):
    from audit import print_report, run_audit

    return print_report(run_audit())


def cmd_reset_db(_args):
    from database import DB_PATH, init_database

    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        print(f"Removed {DB_PATH}")
    init_database()
    print("Database reinitialized and seeded (if empty).")
    return 0


def cmd_imports(_args):
    modules = [
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
    for name in modules:
        __import__(name)
        print(f"  ok: {name}")
    print("All imports successful.")
    return 0


def cmd_check(args):
    from scripts.preflight import run_preflight

    if run_preflight(with_refactor=getattr(args, "with_refactor", False)) != 0:
        print("\ncheck: FAILED (preflight)")
        return 1
    codes = [cmd_test(args), cmd_audit(args)]
    if getattr(args, "with_refactor", False):
        codes.append(cmd_refactor_check(args))
    if any(c != 0 for c in codes):
        print("\ncheck: FAILED")
        return 1
    print("\ncheck: ALL PASSED")
    return 0


def cmd_preflight(args):
    from scripts.preflight import run_preflight

    return run_preflight(with_refactor=getattr(args, "with_refactor", False))


def cmd_session_start(_args):
    from scripts.agent_gates import auto_before_session
    from scripts.session_start import run_session_start

    code = run_session_start()
    if code == 0:
        auto_before_session()
    return code


def cmd_verify_slice(args):
    from scripts.vertical_slices import run_verify_slice

    return run_verify_slice(args.slice_id)


def cmd_doctor(args):
    from scripts.doctor import run_doctor

    return run_doctor(verbose=getattr(args, "verbose", False))


def cmd_build_rust(args):
    from scripts.build_rust import run_build_rust

    return run_build_rust(release=not getattr(args, "debug", False))


def cmd_cheap_check(_args):
    from scripts.cheap_check import run_cheap_check

    return run_cheap_check()


def cmd_lint(args):
    from scripts.lint import run_lint

    return run_lint(
        fix=getattr(args, "fix", False),
        format_code=getattr(args, "format", False),
    )


def cmd_deps_audit(args):
    from scripts.deps_audit import run_deps_audit

    return run_deps_audit(requirements=getattr(args, "requirements", "requirements.txt"))


def cmd_token_audit(args):
    from scripts.token_audit import run_token_audit

    return run_token_audit(strict=getattr(args, "strict", False))


def cmd_token_scan(args):
    from scripts.token_scan import run_token_scan

    return run_token_scan(min_kb=getattr(args, "min_kb", 100), fix=getattr(args, "fix", False))


def cmd_token_minimize(args):
    from scripts.token_audit import run_token_audit
    from scripts.token_scan import run_token_scan

    min_kb = getattr(args, "min_kb", 50)
    do_fix = not getattr(args, "no_fix", False)
    code = run_token_scan(min_kb=min_kb, fix=do_fix)
    audit = run_token_audit(strict=getattr(args, "strict", False))
    return max(code, audit)


def cmd_token_improve(args):
    from scripts.token_improve import run_token_improve

    return run_token_improve(apply_fix=getattr(args, "apply", False), quiet=getattr(args, "quiet", False))


def cmd_agent_pack(args):
    from scripts.agent_pack import run_agent_pack

    raw = getattr(args, "task", None) or []
    task = " ".join(raw) if isinstance(raw, list) else str(raw or "")
    return run_agent_pack(
        task=task,
        slice_id=getattr(args, "slice_id", "") or "",
        complexity=getattr(args, "complexity", "") or "",
        quiet=getattr(args, "quiet", False),
    )


def cmd_outline(args):
    from scripts.file_outline import run_outline

    return run_outline(args.path, full=getattr(args, "full", False))


def cmd_symbol(args):
    from scripts.symbol_lookup import run_symbol_lookup

    return run_symbol_lookup(args.name, slice_id=getattr(args, "slice_id", "") or "")


def cmd_usage_brief(args):
    from scripts.usage_brief import run_usage_brief

    return run_usage_brief(
        slice_id=getattr(args, "slice_id", "") or "",
        verbose=getattr(args, "verbose", False),
    )


def cmd_fix_hint(args):
    from scripts.fix_hint import run_fix_hint

    return run_fix_hint(run_audit=not getattr(args, "no_audit", False))


def cmd_batch_process(args):
    from scripts.batch_process import run_batch_process

    return run_batch_process(
        getattr(args, "task", "") or "",
        input_path=getattr(args, "input", "") or "",
        items_json=getattr(args, "items", "") or "",
        stdin=getattr(args, "stdin", False),
        output_path=getattr(args, "output", "") or "",
        workers=getattr(args, "workers", 0) or 0,
        quiet=getattr(args, "quiet", False),
        full=getattr(args, "full", False),
    )


def cmd_context_window(args):
    from scripts.context_window import run_context_window

    argv = [args.action]
    if args.action == "status" and getattr(args, "json", False):
        argv.append("--json")
    if args.action == "task":
        argv.extend(args.text)
    elif args.action == "decision":
        argv.extend(args.text)
    elif args.action == "tool":
        argv.append(args.tool_id)
        if args.tokens:
            argv.extend(["--tokens", str(args.tokens)])
        if args.summary:
            argv.extend(["--summary", args.summary])
        if args.keep:
            argv.append("--keep")
    elif args.action == "keep":
        argv.append(args.tool_id)
    elif args.action == "record":
        argv.extend(["--id", args.record_id])
        if args.text:
            argv.extend(["--text", args.text])
        if args.keep:
            argv.append("--keep")
    elif args.action == "turn" and args.tokens:
        argv.extend(["--tokens", str(args.tokens)])
    return run_context_window(argv)


def cmd_agent_gates(args):
    from scripts.agent_gates import run_agent_gates

    return run_agent_gates(
        source="dev.py",
        command="agent-gates",
        quiet=getattr(args, "quiet", False),
        force=True,
        debounce_sec=0,
    )


def cmd_install_local_minimize(_args):
    from scripts.install_local_minimize import install

    return install()


def cmd_install_cursor_cli(args):
    from scripts.install_cursor_cli_path import run_install_cursor_cli

    return run_install_cursor_cli(
        bin_path=getattr(args, "bin", "") or "",
        add_expected=getattr(args, "add_expected", False),
    )


def cmd_startup_gates(args):
    from scripts.startup_gates import run_startup_gates

    return run_startup_gates(
        source="dev.py",
        command="startup-gates",
        full=getattr(args, "full", False),
        quiet=False,
        debounce_sec=0,
    )


def cmd_route_task(args):
    from scripts.agent_gates import auto_after_route_task
    from scripts.agent_route import route_task, run_agent_route

    raw = getattr(args, "task", None) or []
    task = " ".join(raw) if isinstance(raw, list) else str(raw or "")
    slice_ov = getattr(args, "slice_id", "") or ""
    code = run_agent_route(
        task,
        complexity=getattr(args, "complexity", "") or "",
        slice_id=slice_ov,
        as_json=getattr(args, "json", False),
    )
    if code == 0 and task.strip():
        rec = route_task(
            task,
            complexity_override=getattr(args, "complexity", "") or "",
            slice_override=slice_ov,
        )
        sid = slice_ov or (rec.slice_id if rec.slice_id not in ("general", "ui-vision", "cli-ops") else "")
        auto_after_route_task(task, sid)
        print("Auto context: @logs/agent_pack/latest.md")
    return code


def cmd_smoke(_args):
    from scripts.smoke_test import run_smoke

    return run_smoke()


def cmd_ui_smoke(_args):
    from scripts.ui_smoke_test import run_ui_smoke

    return run_ui_smoke()


def cmd_ui_functional(_args):
    from scripts.ui_functional_test import run_ui_functional

    return run_ui_functional()


def cmd_ui_exhaustive(_args):
    from scripts.ui_exhaustive_test import run_ui_exhaustive

    return run_ui_exhaustive()


def cmd_ui_handler_coverage(_args):
    from scripts.ui_handler_coverage import run_ui_handler_coverage

    return run_ui_handler_coverage()


def cmd_ui_review(args):
    from scripts.ui_aesthetics_review import run_ui_aesthetics_review

    return run_ui_aesthetics_review(
        strict=getattr(args, "strict", False),
        include_screenshots=not getattr(args, "no_screenshots", False),
        verbose=getattr(args, "verbose", False),
    )


def cmd_ui_diff(args):
    from scripts.ui_visual_diff import run_ui_visual_diff

    return run_ui_visual_diff(
        current_dir=getattr(args, "current_dir", "") or "",
        update_baseline=getattr(args, "update_baseline", False),
        quick=getattr(args, "quick", False),
        verbose=getattr(args, "verbose", False),
    )


def cmd_ui_observe(args):
    from scripts.ui_observe import run_ui_observe

    return run_ui_observe(
        live=getattr(args, "live", False),
        static_only=getattr(args, "static_only", False),
        skip_smoke=getattr(args, "skip_smoke", False),
        live_delay=getattr(args, "delay", 0.5),
        live_hold=getattr(args, "hold", 4.0),
        verbose=getattr(args, "verbose", False),
    )


def cmd_ui_live(args):
    from scripts.ui_live_screen_test import run_ui_live_screen

    mutating = None
    if getattr(args, "read_only", False):
        mutating = False
    elif getattr(args, "mutating", False):
        mutating = True
    return run_ui_live_screen(
        production=getattr(args, "production", False),
        step_delay=getattr(args, "delay", 0.65),
        hold_seconds=getattr(args, "hold", 6.0),
        mutating=mutating,
    )


def cmd_feature_map(_args):
    from scripts.feature_map import run_feature_map

    return run_feature_map()


def cmd_slice_map(args):
    from scripts.vertical_slices import run_slice_map

    return run_slice_map(verbose=getattr(args, "verbose", False))


def cmd_slice_check(args):
    from scripts.vertical_slices import run_slice_check

    return run_slice_check(strict=getattr(args, "strict", False))


def cmd_scenarios(_args):
    from scripts.scenarios import run_scenarios

    return run_scenarios()


def cmd_refactor_check(_args):
    from scripts.refactor_check import run_refactor_check

    return run_refactor_check()


def cmd_logic_imports(args):
    from scripts.audit_logic_imports import run_audit

    return run_audit(verbose=getattr(args, "verbose", False))


def cmd_verify_features(_args):
    """Run per-slice and full-stack verification: logic, smoke, scenarios, UI."""
    root = os.path.dirname(os.path.abspath(__file__))
    dev_py = os.path.join(root, "dev.py")
    steps = [
        "slice-check",
        "check",
        "smoke",
        "scenarios",
        "ui-smoke",
        "ui-exhaustive",
    ]
    print("Dodgeville PD Scheduler — feature verification")
    print("=" * 60)
    failed = []
    for name in steps:
        print(f"\n>>> {name}", flush=True)
        result = subprocess.run(
            [sys.executable, dev_py, name],
            cwd=root,
            stderr=subprocess.STDOUT,
        )
        if result.returncode != 0:
            failed.append(name)
    print("\n" + "=" * 60)
    if failed:
        print(f"verify-features: FAILED — {', '.join(failed)}")
        return 1
    print("verify-features: ALL PASSED")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Dodgeville PD Scheduler dev tools")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("test", help="Run unittest suite")
    sub.add_parser("audit", help="Run regression audit")
    sub.add_parser("reset-db", help="Delete DB and reinitialize")
    sub.add_parser("imports", help="Verify all modules import")
    check = sub.add_parser("check", help="imports + test + audit")
    check.add_argument(
        "--with-refactor",
        action="store_true",
        help="Also run refactor-check (layer boundaries, modularity)",
    )
    preflight = sub.add_parser(
        "preflight",
        help="Fast gate: imports + slice-check + audit (~15s)",
    )
    preflight.add_argument(
        "--with-refactor",
        action="store_true",
        help="Include refactor-check in preflight",
    )
    sub.add_parser("session-start", help="Resume context: handoff, priorities, doctor")
    verify_slice = sub.add_parser(
        "verify-slice",
        help="Run verify commands for one vertical slice (see slice-map)",
    )
    verify_slice.add_argument("slice_id", help="Slice id, e.g. payroll-timecard")
    doctor = sub.add_parser("doctor", help="Environment and schema health check")
    doctor.add_argument("-v", "--verbose", action="store_true", help="Show full paths")
    build_rust = sub.add_parser(
        "build-rust",
        help="Build scheduler_core Rust extension (requires Rust + maturin)",
    )
    build_rust.add_argument("--debug", action="store_true", help="Debug build (faster compile)")
    sub.add_parser("cheap-check", help="Ultra-fast free gate: imports + audit (~5s)")
    lint = sub.add_parser("lint", help="Ruff lint/format (pip install -r requirements-dev.txt)")
    lint.add_argument("--fix", action="store_true", help="Auto-fix safe ruff issues")
    lint.add_argument("--format", action="store_true", help="Also run ruff format")
    deps_audit = sub.add_parser(
        "deps-audit",
        help="Scan requirements.txt for known vulnerabilities (pip-audit)",
    )
    deps_audit.add_argument(
        "--requirements",
        default="requirements.txt",
        help="Requirements file to audit (default: requirements.txt)",
    )
    token_audit = sub.add_parser(
        "token-audit",
        help="Verify token-minimization artifacts and settings (no LLM)",
    )
    token_audit.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 if any minimization artifact is missing",
    )
    token_scan = sub.add_parser(
        "token-scan",
        help="Find large files still indexed (not in .cursorignore)",
    )
    token_scan.add_argument("--min-kb", type=int, default=100, help="Min file size KB (default 100)")
    token_scan.add_argument(
        "--fix",
        action="store_true",
        help="Append large indexable paths to .cursorignore + .cursorindexingignore",
    )
    token_min = sub.add_parser(
        "token-minimize",
        help="Scan + fix index bloat + audit minimization artifacts (free, no LLM)",
    )
    token_min.add_argument("--min-kb", type=int, default=50, help="Scan threshold KB (default 50)")
    token_min.add_argument("--no-fix", action="store_true", help="Scan only; do not update ignore files")
    token_min.add_argument("--strict", action="store_true", help="Fail audit on any gap")
    token_improve = sub.add_parser(
        "token-improve",
        help="Suggest new token savings; --apply runs token-scan --fix",
    )
    token_improve.add_argument("--apply", action="store_true", help="Auto-fix safe index gaps")
    token_improve.add_argument("--quiet", action="store_true", help="Only write logs/token_improve/latest.md")
    agent_pack = sub.add_parser(
        "agent-pack",
        help="Minimal pasteable context (route + slice + token estimates)",
    )
    agent_pack.add_argument("task", nargs="*", help="Optional task for routing")
    agent_pack.add_argument("--slice", default="", dest="slice_id")
    agent_pack.add_argument("--complexity", default="")
    agent_pack.add_argument("-q", "--quiet", action="store_true", help="Only print pack path")
    sub.add_parser(
        "install-local-minimize",
        help="Install git + verify Cursor hooks; refresh agent-pack",
    )
    install_cursor = sub.add_parser(
        "install-cursor-cli",
        help="Add Cursor CLI (cursor.cmd) to Windows user PATH",
    )
    install_cursor.add_argument(
        "--bin",
        default="",
        help="Override path to .../resources/app/bin if auto-detect fails",
    )
    install_cursor.add_argument(
        "--add-expected",
        action="store_true",
        help="Add standard Cursor bin path even if cursor.cmd not found yet",
    )
    agent_gates_p = sub.add_parser("agent-gates", help="Refresh agent-pack (auto on most dev.py)")
    agent_gates_p.add_argument("-q", "--quiet", action="store_true")
    ctx = sub.add_parser(
        "context-window",
        help="Context window: summarize @6k tokens, prune ephemeral tools",
    )
    ctx_sub = ctx.add_subparsers(dest="action", required=True)
    ctx_status = ctx_sub.add_parser("status", help="Show turn/tokens/pruning state")
    ctx_status.add_argument("--json", action="store_true", help="Structured JSON only")
    ctx_sub.add_parser("prune", help="Prune ephemeral tools past 2 turns")
    ctx_sub.add_parser("summarize", help="Force checkpoint summary")
    ctx_turn = ctx_sub.add_parser("turn", help="Advance turn (also runs on Cursor stop)")
    ctx_turn.add_argument("--tokens", type=int, default=0)
    ctx_task = ctx_sub.add_parser("task", help="Set current task (always kept)")
    ctx_task.add_argument("text", nargs="+")
    ctx_dec = ctx_sub.add_parser("decision", help="Record conclusion (always kept)")
    ctx_dec.add_argument("text", nargs="+")
    ctx_tool = ctx_sub.add_parser("tool", help="Register tool result")
    ctx_tool.add_argument("tool_id")
    ctx_tool.add_argument("--tokens", type=int, default=0)
    ctx_tool.add_argument("--summary", default="")
    ctx_tool.add_argument("--keep", action="store_true")
    ctx_keep = ctx_sub.add_parser("keep", help="Mark tool as referenced/kept")
    ctx_keep.add_argument("tool_id")
    ctx_rec = ctx_sub.add_parser("record", help="Register tool output text")
    ctx_rec.add_argument("--id", required=True, dest="record_id")
    ctx_rec.add_argument("--text", default="")
    ctx_rec.add_argument("--keep", action="store_true")
    batch = sub.add_parser(
        "batch-process",
        help="Batch independent items → JSON array aligned by index",
    )
    batch.add_argument(
        "task",
        choices=["classification", "extraction", "summarization", "scoring", "validation"],
    )
    batch.add_argument("--input", "-i", default="", help="JSON file with items[]")
    batch.add_argument("--items", default="", help="JSON array of items")
    batch.add_argument("--stdin", action="store_true", help="Read JSON payload from stdin")
    batch.add_argument("--output", "-o", default="", help="Write results JSON to file")
    batch.add_argument("--workers", type=int, default=0, help="Parallel workers")
    batch.add_argument("-q", "--quiet", action="store_true")
    batch.add_argument("--full", action="store_true", help="Nested result blob (verbose)")
    outline = sub.add_parser("outline", help="AST outline of a Python file (~low tokens)")
    outline.add_argument("path", help="File path relative to project root")
    outline.add_argument("--full", action="store_true", help="Do not truncate outline")
    symbol = sub.add_parser("symbol", help="Find symbol definition (scoped search)")
    symbol.add_argument("name", help="Class, function, or constant name")
    symbol.add_argument("--slice", default="", dest="slice_id", help="Limit to slice touch_together")
    usage_brief = sub.add_parser(
        "usage-brief",
        help="Print minimal agent context (slice touch_together + verify)",
    )
    usage_brief.add_argument("slice_id", nargs="?", default="", help="Slice id (optional)")
    usage_brief.add_argument("-v", "--verbose", action="store_true")
    fix_hint = sub.add_parser("fix-hint", help="Free hints after failed gate (audit + ladder)")
    fix_hint.add_argument("--no-audit", action="store_true")
    startup_gates = sub.add_parser(
        "startup-gates",
        help="Run automatic cheap-check/preflight (also runs on main.py and dev.py)",
    )
    startup_gates.add_argument("--full", action="store_true", help="Run preflight instead of cheap-check")
    route_task = sub.add_parser(
        "route-task",
        help="Recommend agent/model/skill by task complexity (auto-context OFF)",
    )
    route_task.add_argument("task", nargs="+", help="Task description")
    route_task.add_argument(
        "--complexity",
        default="",
        choices=["", "trivial", "low", "medium", "high", "vision", "verify"],
        help="Override detected complexity tier",
    )
    route_task.add_argument("--slice", default="", dest="slice_id", help="Override slice id")
    route_task.add_argument("--json", action="store_true", help="Structured JSON output only")
    sub.add_parser("smoke", help="Fast integration smoke tests (no GUI)")
    sub.add_parser("ui-smoke", help="Build UI shell and visit every page (headless)")
    sub.add_parser("ui-functional", help="Exercise UI handlers on isolated test DB")
    sub.add_parser("ui-exhaustive", help="Full tab-by-tab UI handler test (all features)")
    sub.add_parser("ui-handler-coverage", help="Summary of UI handler vs exhaustive test steps")
    ui_review = sub.add_parser(
        "ui-review",
        help="UI aesthetics, spelling, and wording review (writes logs/ui_review/)",
    )
    ui_review.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 if any errors or warnings are found",
    )
    ui_review.add_argument(
        "--no-screenshots",
        action="store_true",
        help="Do not reference latest ui-live screenshot directory",
    )
    ui_review.add_argument("-v", "--verbose", action="store_true", help="Print all findings")
    ui_diff = sub.add_parser(
        "ui-diff",
        help="Visual diff ui-live PNGs vs tests/ui_snapshots/baseline (Pillow)",
    )
    ui_diff.add_argument("--current-dir", default="", help="Screenshot run directory")
    ui_diff.add_argument(
        "--update-baseline",
        action="store_true",
        help="Copy latest ui-live PNGs to baseline",
    )
    ui_diff.add_argument(
        "--quick",
        action="store_true",
        help="Compare only nav/login PNGs numbered 01–15 (fast)",
    )
    ui_diff.add_argument("-v", "--verbose", action="store_true")
    ui_observe = sub.add_parser(
        "ui-observe",
        help="UI observation bundle for agents: smoke + ui-review (+ optional ui-live)",
    )
    ui_observe.add_argument(
        "--live",
        action="store_true",
        help="Run ui-live screenshots before smoke/review",
    )
    ui_observe.add_argument(
        "--static-only",
        action="store_true",
        help="ui-review only (skip ui-smoke)",
    )
    ui_observe.add_argument("--skip-smoke", action="store_true", help="Skip ui-smoke")
    ui_observe.add_argument("--delay", type=float, default=0.5, help="ui-live step delay")
    ui_observe.add_argument("--hold", type=float, default=4.0, help="ui-live hold at end")
    ui_observe.add_argument("-v", "--verbose", action="store_true", help="Verbose ui-review")
    ui_live = sub.add_parser(
        "ui-live",
        help="Visible on-screen UI test with screenshots (isolated test DB)",
    )
    ui_live.add_argument(
        "--production",
        action="store_true",
        help="Use production DB; navigation/refresh only (no create/delete)",
    )
    ui_live.add_argument("--delay", type=float, default=0.65, help="Seconds between steps")
    ui_live.add_argument("--hold", type=float, default=6.0, help="Seconds to keep window open at end")
    ui_live.add_argument(
        "--mutating",
        action="store_true",
        help="With --production: run create/approve/delete steps (default off for production)",
    )
    ui_live.add_argument(
        "--read-only",
        action="store_true",
        help="Navigation and refresh only (no create/delete even on test DB)",
    )
    sub.add_parser("feature-map", help="Print UI/logic/CLI feature coverage")
    slice_map = sub.add_parser("slice-map", help="Vertical slice registry map (see docs/VERTICAL_SLICES.md)")
    slice_map.add_argument("-v", "--verbose", action="store_true", help="Show summary and touch_together hints")
    slice_check = sub.add_parser("slice-check", help="Verify slice registry bindings (logic, UI, tests)")
    slice_check.add_argument("--strict", action="store_true", help="Fail on warnings too")
    sub.add_parser("scenarios", help="Run SCHEDULING_RULES S-01..S-11 regression scenarios")
    sub.add_parser(
        "verify-features",
        help="Full feature gate: slice-check, check, smoke, scenarios, ui-smoke, ui-exhaustive",
    )
    sub.add_parser("refactor-check", help="Architecture and modularity checks")
    logic_imports = sub.add_parser("logic-imports", help="Verify logic.py exports match callers")
    logic_imports.add_argument("-v", "--verbose", action="store_true", help="Show file references")

    args = parser.parse_args()
    handlers = {
        "test": cmd_test,
        "audit": cmd_audit,
        "reset-db": cmd_reset_db,
        "imports": cmd_imports,
        "check": cmd_check,
        "preflight": cmd_preflight,
        "session-start": cmd_session_start,
        "verify-slice": cmd_verify_slice,
        "doctor": cmd_doctor,
        "build-rust": cmd_build_rust,
        "cheap-check": cmd_cheap_check,
        "lint": cmd_lint,
        "deps-audit": cmd_deps_audit,
        "token-audit": cmd_token_audit,
        "token-scan": cmd_token_scan,
        "token-minimize": cmd_token_minimize,
        "token-improve": cmd_token_improve,
        "agent-pack": cmd_agent_pack,
        "outline": cmd_outline,
        "symbol": cmd_symbol,
        "usage-brief": cmd_usage_brief,
        "fix-hint": cmd_fix_hint,
        "agent-gates": cmd_agent_gates,
        "context-window": cmd_context_window,
        "batch-process": cmd_batch_process,
        "install-local-minimize": cmd_install_local_minimize,
        "install-cursor-cli": cmd_install_cursor_cli,
        "startup-gates": cmd_startup_gates,
        "route-task": cmd_route_task,
        "smoke": cmd_smoke,
        "ui-smoke": cmd_ui_smoke,
        "ui-functional": cmd_ui_functional,
        "ui-exhaustive": cmd_ui_exhaustive,
        "ui-handler-coverage": cmd_ui_handler_coverage,
        "ui-review": cmd_ui_review,
        "ui-diff": cmd_ui_diff,
        "ui-observe": cmd_ui_observe,
        "ui-live": cmd_ui_live,
        "feature-map": cmd_feature_map,
        "slice-map": cmd_slice_map,
        "slice-check": cmd_slice_check,
        "scenarios": cmd_scenarios,
        "verify-features": cmd_verify_features,
        "refactor-check": cmd_refactor_check,
        "logic-imports": cmd_logic_imports,
    }

    if args.command not in handlers:
        parser.print_help()
        return 1

    from scripts.startup_gates import auto_before_dev_command

    gate_code = auto_before_dev_command(args.command)
    if gate_code != 0:
        from scripts.fix_hint import run_fix_hint

        run_fix_hint(run_audit=True)
        return gate_code

    from scripts.agent_gates import auto_before_dev_command as auto_agent_gates

    auto_agent_gates(args.command)

    return handlers[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
