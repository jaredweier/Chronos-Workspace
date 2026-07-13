"""Print minimal agent context — slice-scoped files and verify commands."""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _head(path: str, lines: int = 35) -> list[str]:
    full = os.path.join(ROOT, path)
    if not os.path.isfile(full):
        return []
    with open(full, encoding="utf-8") as fh:
        return [line.rstrip() for line in fh.readlines()[:lines]]


def run_usage_brief(slice_id: str = "", verbose: bool = False) -> int:
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    os.chdir(ROOT)

    from logic import rust_bridge
    from slices.registry import SLICES

    print("Dodgeville PD — usage brief (dynamic slice context)")
    print("=" * 60)
    print(f"Backend: {rust_bridge.backend_name()} scheduling math")
    print("Policy: docs/AGENT_STABLE.md · Pack: logs/agent_pack/latest.md")

    # Trust table only by default (token tax); full handoff if --verbose
    handoff = _head("docs/HANDOFF.md", 40 if verbose else 8)
    if handoff:
        print("\n--- HANDOFF excerpt ---")
        for line in handoff:
            if line.strip():
                print(line)

    if slice_id:
        match = next((s for s in SLICES if s["id"] == slice_id), None)
        if not match:
            print(f"\nUnknown slice: {slice_id}")
            print("Run: python dev.py slice-map -v")
            return 1
        print(f"\n--- Slice: {match['id']} — {match['name']} ---")
        print(match.get("summary", ""))
        touch = match.get("touch_together", [])
        if touch:
            from scripts.token_estimate import file_stats, format_stats_row

            print("\nRead/edit ONLY (use `outline` / `symbol` before full read):")
            total = 0
            for path in touch:
                stats = file_stats(path)
                print(format_stats_row(stats))
                total += stats.get("tokens", 0)
            print(f"  TOTAL whole-file read: ~{total:,} tokens")
            print(f"  Pack: python dev.py agent-pack --slice {slice_id}")
        verify = match.get("verify", [])
        if verify:
            print("\nVerify:")
            for cmd in verify:
                print(f"  python dev.py {cmd}")
            print(f"  python dev.py verify-slice {slice_id}")
    else:
        print("\n--- All slices (use slice id for detail) ---")
        for s in SLICES:
            print(f"  {s['id']}: {s['name']}")

    print("=" * 60)
    return 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    verbose = "-v" in sys.argv or "--verbose" in sys.argv
    raise SystemExit(run_usage_brief(slice_id=args[0] if args else "", verbose=verbose))
