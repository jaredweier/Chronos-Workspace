"""Find large indexable files not excluded by .cursorignore — reduce surprise token cost."""

from __future__ import annotations

import fnmatch
import os
import sys
from typing import List, Tuple

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SKIP_DIRS = {
    ".git",
    "dist",
    "build",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    "rust",
    "terminals",
}

IGNORE_MARKER = "# Large source files"
IGNORE_HINT = "# Large source files — use: python dev.py outline <path> | symbol <name> | usage-brief <slice>"
INDEXING_MARKER = "# Large source files (token-scan)"

# Editable source — indexable by design; agents use outline/symbol instead of hiding.
ALLOWED_LARGE_SOURCE = {
    "ui/payroll_pages.py",
    "ui/feature_pages.py",
    "ui/schedule_pages.py",
    "logic/payroll/timecard.py",
    "logic/payroll/period.py",
    "logic/payroll/entries.py",
    "logic/payroll/pay_codes.py",
    "logic/scheduling.py",
    "logic/scheduling_sim.py",
    "logic/requests.py",
    "cli.py",
    "validators.py",
    "validators_config.py",
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
    "gui/pages/simulator/page.py",
    "logic/staffing_optimizer.py",
    "logic/optimizer_features.py",
    "logic/coverage_optimizer.py",
    "logic/bump_optimizer.py",
    "simulator.py",
}


def _load_ignore_patterns() -> List[str]:
    path = os.path.join(ROOT, ".cursorignore")
    if not os.path.isfile(path):
        return []
    patterns: List[str] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#"):
                patterns.append(line.replace("\\", "/"))
    return patterns


def _ignored(rel: str, patterns: List[str]) -> bool:
    rel = rel.replace("\\", "/")
    for pat in patterns:
        p = pat.rstrip("/")
        if pat.endswith("/"):
            if rel.startswith(p + "/") or rel == p:
                return True
        elif "*" in pat or "?" in pat:
            if fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(os.path.basename(rel), pat):
                return True
        elif rel == p or rel.startswith(p + "/"):
            return True
    return False


def scan_large_files(*, min_kb: int = 100, limit: int = 25) -> Tuple[List[dict], List[dict]]:
    patterns = _load_ignore_patterns()
    indexed_large: List[dict] = []
    ignored_large: List[dict] = []

    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if not name.endswith((".py", ".md", ".txt", ".json", ".yaml", ".yml")):
                continue
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, ROOT).replace("\\", "/")
            try:
                size = os.path.getsize(full)
            except OSError:
                continue
            if size < min_kb * 1024:
                continue
            entry = {
                "path": rel,
                "kb": round(size / 1024, 1),
                "tokens": max(1, size // 4),
            }
            if _ignored(rel, patterns):
                ignored_large.append(entry)
            else:
                indexed_large.append(entry)

    indexed_large.sort(key=lambda x: x["kb"], reverse=True)
    ignored_large.sort(key=lambda x: x["kb"], reverse=True)
    return indexed_large[:limit], ignored_large[:limit]


def _append_paths_to_ignore_file(path: str, paths: List[str], *, marker: str, hint: str) -> List[str]:
    added: List[str] = []
    if not paths:
        return added

    existing = ""
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            existing = fh.read()

    existing_lines = {line.strip() for line in existing.splitlines()}
    for rel in paths:
        if rel in existing_lines:
            continue
        added.append(rel)

    if not added:
        return added

    block = [hint if hint not in existing else marker]
    if marker not in existing and hint not in existing:
        block = [hint]
    block.extend(added)

    with open(path, "a", encoding="utf-8", newline="\n") as fh:
        if existing and not existing.endswith("\n"):
            fh.write("\n")
        fh.write("\n".join(block) + "\n")
    return added


def apply_token_scan_fix(indexed: List[dict]) -> List[str]:
    paths = [e["path"] for e in indexed]
    added = _append_paths_to_ignore_file(
        os.path.join(ROOT, ".cursorignore"),
        paths,
        marker=IGNORE_MARKER,
        hint=IGNORE_HINT,
    )
    _append_paths_to_ignore_file(
        os.path.join(ROOT, ".cursorindexingignore"),
        paths,
        marker=INDEXING_MARKER,
        hint=f"{INDEXING_MARKER} — outline/symbol instead of full read",
    )
    return added


def run_token_scan(*, min_kb: int = 100, fix: bool = False) -> int:
    os.chdir(ROOT)
    indexed, ignored = scan_large_files(min_kb=min_kb)

    print("Dodgeville PD — token scan (index vs cursorignore)")
    print("=" * 60)
    print(f"Threshold: {min_kb} KB+")
    allowed = [e for e in indexed if e["path"] in ALLOWED_LARGE_SOURCE]
    surprise = [e for e in indexed if e["path"] not in ALLOWED_LARGE_SOURCE]

    if allowed:
        print("\n[OK] Large editable source (use outline/symbol — not cursorignored):")
        for e in allowed:
            print(f"  {e['path']}: {e['kb']} KB (~{e['tokens']:,} tokens)")

    print("\n[!] Still indexable (add to .cursorignore if not needed every turn):")
    if surprise:
        for e in surprise:
            print(f"  {e['path']}: {e['kb']} KB (~{e['tokens']:,} tokens)")
    else:
        print("  (none — good)")

    print("\n✓ Large but already ignored (sample):")
    for e in ignored[:8]:
        print(f"  {e['path']}: {e['kb']} KB")
    if len(ignored) > 8:
        print(f"  ... {len(ignored) - 8} more")

    if fix and surprise:
        added = apply_token_scan_fix(surprise)
        if added:
            print(f"\n+ Added {len(added)} path(s) to .cursorignore / .cursorindexingignore")
            for rel in added:
                print(f"    {rel}")
            indexed, _ = scan_large_files(min_kb=min_kb)
        else:
            print("\n(fix: paths already listed in ignore files)")

    print("\n" + "=" * 60)
    if surprise:
        print(f"token-scan: {len(surprise)} large indexable file(s) — run: python dev.py token-scan --fix")
        return 1
    print("token-scan: no large surprise index files")
    return 0


if __name__ == "__main__":
    import sys

    kb = 100
    do_fix = False
    for arg in sys.argv[1:]:
        if arg.startswith("--min-kb="):
            kb = int(arg.split("=", 1)[1])
        elif arg == "--fix":
            do_fix = True
    raise SystemExit(run_token_scan(min_kb=kb, fix=do_fix))
