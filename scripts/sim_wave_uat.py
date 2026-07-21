"""P17 — Simulator wave UAT pack (static + optional live browser).

Static checks always run (no Chronos required):
  - source markers for P0–P10 / P11+ panels exist
  - pure logic smoke for wave2/ops/pattern modules

Live checks (optional) when Chronos is up:
  set CHRONOS_PROOF_URL=http://127.0.0.1:8090
  python scripts/sim_wave_uat.py --live

Exit 0 = all static (and live if requested) passed.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Markers that must exist in source (trust: UI was wired, not vapor)
SOURCE_MARKERS = {
    "P1_autopsy": ("logic/constraint_autopsy.py", ["constraint_autopsy", "cheap_feasibility_strip"]),
    "P2_soft_rank": ("logic/soft_rank.py", ["rank_soft_among_feasible", "soft_components"]),
    "P3_visuals": ("logic/sim_visuals.py", ["coverage_band_heatmap", "officer_duty_gantt"]),
    "P3_ui": ("gui/pages/simulator/visuals_panel.py", ["render_coverage_heatmap", "render_officer_gantt"]),
    "P4_ops": ("logic/ops_bridge.py", ["publish_readiness_checklist", "seed_open_shifts_from_sim"]),
    "P5_pattern": ("logic/pattern_preview.py", ["pattern_calendar_preview", "compliance_strip"]),
    "P6_10_wave2": ("logic/sim_wave2.py", ["annotate_pareto_shortlist", "whatif_sandbox", "counterfactual_unlocks"]),
    "P6_ui_table": ("gui/pages/simulator/decision_table.py", ["Pareto", "FLSA 7/14/28", "Fatigue advisory"]),
    "P7_dialog": ("gui/pages/simulator/dialogs.py", ["What would unlock", "counterfactual"]),
    "P10_page": ("gui/pages/simulator/page.py", ["What-if sandbox", "whatif_sandbox"]),
    "P5_page": ("gui/pages/simulator/page.py", ["paint_pattern_preview", "pattern_preview_host"]),
    "P5_ui": ("gui/pages/simulator/pattern_preview_ui.py", ["Pattern calendar", "bind_pattern_preview"]),
    "P11_18": ("logic/horizon_pack.py", ["non_dominated_shortlist", "gantt_duty_delta", "scenario_story_cards"]),
    "P4_publish": ("gui/pages/simulator/publish_panel.py", ["Publish readiness", "open-shift"]),
}

# Live page text markers (subset — appear after navigation/search)
LIVE_STATIC_MARKERS = [
    "Find best",
    "Soft preferences",
    "What-if sandbox",
    "Pattern calendar",
    "Publish",
]


def _check_source() -> list[tuple[str, bool, str]]:
    rows = []
    for name, (rel, needles) in SOURCE_MARKERS.items():
        path = ROOT / rel
        if not path.is_file():
            rows.append((name, False, f"missing file {rel}"))
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        missing = [n for n in needles if n not in text]
        if missing:
            rows.append((name, False, f"missing markers: {missing}"))
        else:
            rows.append((name, True, "ok"))
    return rows


def _check_logic_smoke() -> list[tuple[str, bool, str]]:
    rows = []
    try:
        from logic.sim_wave2 import annotate_pareto_shortlist, multi_period_flsa_meters, whatif_sandbox

        r = annotate_pareto_shortlist(
            [
                {
                    "hard_constraints_ok": True,
                    "num_officers": 8,
                    "economics": {"est_ot_hours_total": 10, "fairness_score": 80},
                }
            ]
        )
        assert r and "pareto_labels" in r[0]
        w = whatif_sandbox({"num_officers": 6, "coverage_247": 1}, delta_n=1)
        assert w.get("success")
        m = multi_period_flsa_meters(shift_length_hours=8, duty_fraction=0.5)
        assert len(m) == 3
        rows.append(("logic_wave2", True, "ok"))
    except Exception as exc:
        rows.append(("logic_wave2", False, str(exc)[:200]))

    try:
        from logic.ops_bridge import publish_readiness_checklist

        c = publish_readiness_checklist(
            {
                "success": True,
                "best": {
                    "hard_constraints_ok": True,
                    "num_officers": 8,
                    "shift_starts": ["06:00"],
                },
            },
            {},
            implement_date="7/1/26",
        )
        assert c.get("ready") is True
        rows.append(("logic_ops", True, "ok"))
    except Exception as exc:
        rows.append(("logic_ops", False, str(exc)[:200]))

    try:
        from logic.pattern_preview import pattern_calendar_preview

        cal = pattern_calendar_preview(variations_text="6-2,5-3", style="rotating")
        assert cal.get("success")
        rows.append(("logic_pattern", True, "ok"))
    except Exception as exc:
        rows.append(("logic_pattern", False, str(exc)[:200]))

    try:
        from logic.horizon_pack import (
            non_dominated_shortlist,
            scenario_story_cards,
            structured_conflict_report,
        )

        assert callable(non_dominated_shortlist)
        assert callable(structured_conflict_report)
        assert callable(scenario_story_cards)
        rows.append(("logic_horizon", True, "ok"))
    except Exception as exc:
        rows.append(("logic_horizon", False, str(exc)[:200]))

    return rows


def _check_live(base: str) -> list[tuple[str, bool, str]]:
    rows = []
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        return [("playwright", False, f"not installed: {exc}")]

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.goto(base, wait_until="domcontentloaded", timeout=25000)
            page.wait_for_timeout(800)
            # Login
            uat = page.get_by_role("button", name=re.compile(r"Enter Full Product", re.I))
            if uat.count():
                uat.first.click()
                page.wait_for_timeout(1500)
            if "/login" in page.url or page.locator('input[type="password"]').count():
                try:
                    page.locator("input:visible").first.fill("admin")
                    page.locator('input[type="password"]').first.fill("admin")
                    page.get_by_role("button", name=re.compile(r"Sign In", re.I)).click()
                    page.wait_for_timeout(2000)
                except Exception:
                    pass
            page.goto(base.rstrip("/") + "/simulator", timeout=20000)
            page.wait_for_timeout(1500)
            body = page.inner_text("body") or ""
            if "/login" in page.url:
                rows.append(("live_login", False, "still on login"))
                browser.close()
                return rows
            rows.append(("live_login", True, page.url))
            for m in LIVE_STATIC_MARKERS:
                ok = m.lower() in body.lower() or m in body
                rows.append((f"live_text:{m}", ok, "found" if ok else "missing on /simulator"))
            # Expand soft prefs / what-if if present
            for label in ("Soft preferences", "What-if sandbox", "Pattern calendar"):
                try:
                    exp = page.get_by_text(label, exact=False)
                    if exp.count():
                        exp.first.click()
                        page.wait_for_timeout(400)
                        rows.append((f"live_click:{label}", True, "clicked"))
                    else:
                        rows.append((f"live_click:{label}", False, "not found"))
                except Exception as exc:
                    rows.append((f"live_click:{label}", False, str(exc)[:80]))
            out = ROOT / "logs" / "sim_wave_uat.png"
            out.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(out), full_page=True)
            rows.append(("live_screenshot", True, str(out)))
            browser.close()
    except Exception as exc:
        rows.append(("live", False, str(exc)[:240]))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description="Simulator wave UAT pack")
    ap.add_argument("--live", action="store_true", help="Also hit Chronos via Playwright")
    ap.add_argument(
        "--base",
        default=os.environ.get("CHRONOS_PROOF_URL", "http://127.0.0.1:8090"),
        help="Chronos base URL for --live",
    )
    args = ap.parse_args()

    print("=== P17 sim wave UAT ===")
    print("ROOT", ROOT)
    all_rows: list[tuple[str, bool, str]] = []
    all_rows.extend(_check_source())
    all_rows.extend(_check_logic_smoke())
    if args.live:
        print("LIVE", args.base)
        all_rows.extend(_check_live(args.base))
    else:
        print("(static only — pass --live when Chronos is up)")

    fails = 0
    for name, ok, detail in all_rows:
        mark = "OK  " if ok else "FAIL"
        print(f"  [{mark}] {name}: {detail}")
        if not ok:
            fails += 1

    print("===", "PASS" if fails == 0 else f"FAIL ({fails})", "===")
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
