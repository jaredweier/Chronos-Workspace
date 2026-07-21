"""Environment and project health checks for Dodgeville PD Scheduler."""

from __future__ import annotations

import importlib
import os
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _check(label: str, ok: bool, detail: str = "") -> tuple[bool, str]:
    status = "ok" if ok else "FAIL"
    line = f"  [{status}] {label}"
    if detail:
        line += f" — {detail}"
    return ok, line


def run_doctor(verbose: bool = False) -> int:
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    os.chdir(ROOT)

    lines: list[str] = []
    all_ok = True

    ok, line = _check("Python", sys.version_info >= (3, 10), sys.version.split()[0])
    lines.append(line)
    all_ok &= ok

    deps = ["customtkinter", "PIL", "reportlab"]
    for dep in deps:
        try:
            importlib.import_module(dep)
            ok, line = _check(f"dependency {dep}", True)
        except ImportError as exc:
            ok, line = _check(f"dependency {dep}", False, str(exc))
        lines.append(line)
        all_ok &= ok

    core_modules = [
        "config",
        "database",
        "validators",
        "logic",
        "cli",
        "audit",
        "permissions",
    ]
    for name in core_modules:
        try:
            importlib.import_module(name)
            ok, line = _check(f"import {name}", True)
        except Exception as exc:
            ok, line = _check(f"import {name}", False, str(exc))
        lines.append(line)
        all_ok &= ok

    # Brand images are runtime uploads (photos/) — not required on disk for healthy install
    try:
        from photos import chronos_logo_path, department_logo_path, department_photo_path

        brand_ok = True
        _ = chronos_logo_path(), department_logo_path(), department_photo_path()
        ok, line = _check("brand path APIs", brand_ok, "optional uploads under photos/")
    except Exception as exc:
        ok, line = _check("brand path APIs", False, str(exc))
    lines.append(line)
    all_ok &= ok

    from database import DB_PATH, init_database

    db_ok = True
    db_detail = DB_PATH
    try:
        init_database()
        conn = sqlite3.connect(DB_PATH)
        try:
            conn.execute("PRAGMA foreign_keys = ON")
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
            required = {
                "officers",
                "day_off_requests",
                "schedule_overrides",
                "shift_swaps",
                "app_users",
                "notifications",
                "payroll_entries",
            }
            missing = required - tables
            if missing:
                db_ok = False
                db_detail = f"missing tables: {', '.join(sorted(missing))}"
        finally:
            conn.close()
    except Exception as exc:
        db_ok = False
        db_detail = str(exc)

    ok, line = _check("database schema", db_ok, db_detail)
    lines.append(line)
    all_ok &= ok

    try:
        from logic import rust_bridge

        if rust_bridge.available():
            import scheduler_core

            ok, line = _check(
                "rust scheduler_core",
                True,
                scheduler_core.backend_info(),
            )
            all_ok &= ok
        else:
            detail = "MISSING — scheduling math uses python-fallback (run: python dev.py build-rust)"
            err = rust_bridge.load_error()
            if err:
                detail = f"{detail} — {err}"
            ok, line = _check(
                "rust scheduler_core",
                False,
                detail,
            )
            all_ok &= ok
    except Exception as exc:
        ok, line = _check("rust scheduler_core", False, str(exc))
        all_ok &= ok
    lines.append(line)

    for folder in ("photos", "logs", "backups", "exports"):
        path = os.path.join(ROOT, folder)
        exists = os.path.isdir(path)
        ok, line = _check(f"data dir {folder}/", exists)
        lines.append(line)
        all_ok &= ok

    optional_tools = [
        ("ruff", "ruff", "pip install -r requirements-dev.txt"),
        ("pyspellchecker", "spellchecker", "richer ui-review spelling"),
        ("pre-commit", "pre_commit", "standardized git hooks"),
        ("pip-audit", "pip_audit", "dependency vulnerability scan"),
    ]
    optional_lines: list[str] = []
    for label, module, hint in optional_tools:
        try:
            importlib.import_module(module)
            optional_lines.append(f"  [ok] optional {label}")
        except ImportError:
            optional_lines.append(f"  [—] optional {label} — {hint}")

    print("Dodgeville PD Scheduler — doctor")
    print("-" * 40)
    for line in lines:
        print(line)
    if optional_lines:
        print("Optional OSS dev tools:")
        for line in optional_lines:
            print(line)
    print("-" * 40)
    if all_ok:
        print("doctor: ALL CHECKS PASSED")
        return 0
    print("doctor: ISSUES FOUND")
    return 1


if __name__ == "__main__":
    verbose = "--verbose" in sys.argv or "-v" in sys.argv
    raise SystemExit(run_doctor(verbose=verbose))
