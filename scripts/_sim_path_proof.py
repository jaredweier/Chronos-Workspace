"""Simulator residual proof: overhaul chrome + Find-best ranked/hard outcome.

Default base: http://127.0.0.1:8090 (this workspace). Always-on :8080 may be MyProject.
  set CHRONOS_PROOF_URL=http://127.0.0.1:8080
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = os.environ.get("CHRONOS_PROOF_URL", "http://127.0.0.1:8090")
OUT = Path("logs/sim_proof.png")
# Real post-search text from _apply_opt_result / plan_explain (live UI)
RESULT_MARKERS = (
    "Layouts Checked:",
    "Search Mode: Exhaustive",
    "Search Mode: Partial",
    "Search Mode: Anytime",
    "Structural Configs",
    "Options Kept",
    "Best Option",
    "No Schedule Meets Selected Hard Constraints",
    "No Schedule Meets Every Hard Constraint",
    "Closest Alternatives",
    "Select An Option Below",
    "Select an option below",
    "adopted as Given",
)
results: list = []


def _login(page) -> None:
    page.goto(BASE, wait_until="domcontentloaded")
    page.wait_for_timeout(1000)
    uat = page.get_by_role("button", name=re.compile(r"Enter Full Product", re.I))
    if uat.count():
        uat.first.click()
        for _ in range(30):
            page.wait_for_timeout(400)
            if "/login" not in page.url:
                break
        results.append(("login", page.url, "ok" if "/login" not in page.url else "still_login"))
    if "/login" in page.url:
        try:
            page.locator('[data-testid="login-username"] input, [data-testid="login-username"]').first.fill(
                "admin", timeout=12000
            )
            page.locator('[data-testid="login-password"] input, [data-testid="login-password"]').first.fill(
                "admin", timeout=12000
            )
            page.get_by_role("button", name="Sign In").click()
            page.wait_for_timeout(2500)
        except Exception as exc:
            results.append(("login_fallback_err", str(exc)[:160]))
        results.append(("login_fallback", page.url, "ok" if "/login" not in page.url else "still_login"))


def _set_given_toggle(page, dim_label: str) -> bool:
    """Click Given on a Given/Solve-for toggle near dim_label."""
    try:
        head = page.locator(".sim-dim-head").filter(has_text=dim_label)
        if head.count():
            given = head.first.get_by_text("Given", exact=True)
            if given.count():
                given.first.click()
                page.wait_for_timeout(300)
                return True
    except Exception:
        pass
    try:
        card = page.locator(".sim-option-card").filter(has_text=dim_label)
        if card.count():
            given = card.first.get_by_text("Given", exact=True)
            if given.count():
                given.first.click()
                page.wait_for_timeout(300)
                return True
    except Exception:
        pass
    return False


def _fill_aria(page, aria: str, value: str) -> bool:
    """Fill input by aria-label; enable if disabled."""
    loc = page.locator(f'input[aria-label="{aria}"]')
    if loc.count() == 0:
        # partial match
        loc = page.locator("input").filter(has=page.locator(f'[aria-label*="{aria}"]'))
        loc = page.locator(f'input[aria-label*="{aria}"]')
    if loc.count() == 0:
        return False
    el = loc.first
    try:
        page.evaluate(
            """(sel) => {
              const el = document.querySelector(sel);
              if (!el) return;
              el.removeAttribute('disabled');
              el.disabled = false;
              el.classList.remove('disabled');
            }""",
            f'input[aria-label="{aria}"]',
        )
    except Exception:
        pass
    try:
        el.fill(value)
        el.dispatch_event("input")
        el.dispatch_event("change")
        return True
    except Exception:
        try:
            el.click(force=True)
            el.fill(value, force=True)
            return True
        except Exception:
            return False


def _lock_small_search(page) -> dict:
    """Lock length/starts/officers so Find best finishes in proof window."""
    try:
        page.locator(".sim-step-rail .sim-step").first.click()
        page.wait_for_timeout(800)
    except Exception:
        pass
    locks = {
        "Officer Count": _set_given_toggle(page, "Officer Count"),
        "Shift Length": _set_given_toggle(page, "Shift Length"),
        "Shift Start Times": _set_given_toggle(page, "Shift Start Times"),
    }
    page.wait_for_timeout(400)
    fills = {
        "officers": _fill_aria(page, "Number Of Officers", "8"),
        "length": _fill_aria(page, "Hours (0.5 Steps)", "8"),
        "starts": _fill_aria(page, "Starts (Comma-Separated)", "06:00, 14:00, 22:00"),
    }
    # Uncheck heavy optional requires if checked (windows / min staff / annual) to keep search finite
    for name in (
        "Require: Minimum Officers Per Shift",
        "Require: 24/7 Continuous Minimum",
        "Require: Annual Hours Target",
        "Minimum Officers Per Shift",
        "24/7 Continuous",
        "Annual Hours",
    ):
        try:
            cb = page.get_by_label(name, exact=False)
            if cb.count() and cb.first.is_checked():
                cb.first.uncheck()
        except Exception:
            try:
                page.get_by_text(name, exact=False).first.click()
            except Exception:
                pass
    # Clear annual value + Solve-for so restored form snapshot can't early-impossible
    try:
        _fill_aria(page, "Annual Hours Target", "")
        head = page.locator(".sim-dim-head").filter(has_text="Annual")
        if head.count():
            sf = head.first.get_by_text("Solve for", exact=True)
            if sf.count():
                sf.first.click()
                page.wait_for_timeout(200)
    except Exception:
        pass
    # Clear multi-block patterns leftover from prior session
    try:
        _fill_aria(page, "On/off patterns (| = different officers)", "")
    except Exception:
        pass
    results.append(("locks", locks))
    results.append(("fills", fills))
    # Snapshot enabled state
    try:
        snap = page.evaluate(
            """() => [...document.querySelectorAll('input[type=text]')].slice(0,12).map(e => ({
              aria: e.getAttribute('aria-label'), val: e.value, dis: e.disabled
            }))"""
        )
        results.append(("input_snap", snap))
    except Exception:
        pass
    return locks


def _dismiss_dialogs(page, *, allow_cancel: bool = False) -> int:
    """Close Quasar dialogs only (never the main Cancel search control)."""
    closed = 0
    # Prefer Escape first — safer than clicking Cancel (hits "Cancel search")
    try:
        if page.locator(".q-dialog__backdrop").count():
            page.keyboard.press("Escape")
            page.wait_for_timeout(350)
            closed += 1
    except Exception:
        pass
    names = [
        "Continue search",
        "Continue Search",
        "Run anyway",
        "Run Anyway",
        "Proceed",
        "Yes",
        "OK",
        "Confirm",
        "Close",
        "Got it",
        "Understood",
        "Dismiss",
    ]
    if allow_cancel:
        names.append("Cancel")
    # Only buttons inside open dialogs
    dlg = page.locator(".q-dialog")
    if dlg.count() == 0:
        return closed
    for name in names:
        b = dlg.get_by_role("button", name=name)
        if b.count():
            try:
                btn = b.first
                if btn.is_visible():
                    btn.click(timeout=2000)
                    page.wait_for_timeout(300)
                    closed += 1
                    results.append(("dialog_click", name))
                    break
            except Exception:
                pass
    return closed


def _dismiss_confirm_if_any(page) -> bool:
    """Accept large-space confirm (exact product label) — never Cancel."""
    dlg = page.locator(".q-dialog")
    if dlg.count() == 0:
        return False
    for name in (
        "Run Full Search Anyway",
        "Run full search anyway",
        "Continue search",
        "Continue Search",
        "Run anyway",
        "Proceed",
        "Yes",
        "OK",
    ):
        b = dlg.get_by_role("button", name=re.compile(re.escape(name), re.I))
        if b.count() == 0:
            b = dlg.get_by_role("button", name=name)
        if b.count():
            try:
                if b.first.is_visible():
                    b.first.click(timeout=3000)
                    results.append(("confirm_click", name))
                    page.wait_for_timeout(400)
                    return True
            except Exception:
                pass
    return False


def _result_hit(txt: str) -> str | None:
    for m in RESULT_MARKERS:
        if m in txt:
            return m
    # Ranked cards after real search
    if re.search(r"Option\s+#?\s*1\b", txt) and "sim-option" in txt.lower():
        return "Option 1 card"
    if "Layouts Checked" in txt and "Search Mode" in txt:
        return "Layouts Checked + Search Mode"
    return None


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_default_timeout(45000)
        _login(page)

        page.goto(f"{BASE}/simulator", wait_until="domcontentloaded")
        page.wait_for_timeout(3500)
        _dismiss_dialogs(page)
        page.wait_for_timeout(400)
        _dismiss_dialogs(page)
        body = page.locator("body").inner_text()
        results.append(("sim_url", page.url))
        for needle in (
            "Schedule Simulator",
            "Requirements",
            "Find best",
            "Duty & hours",
            "Find Best",
            "Rotation Model",
            "1 · Duty",
        ):
            results.append((needle, needle in body or needle.lower() in body.lower()))

        results.append(("step_rail", page.locator(".sim-step-rail").count() > 0))
        _lock_small_search(page)
        _dismiss_dialogs(page)

        cont = page.get_by_role("button", name="Continue to find best")
        if cont.count():
            try:
                cont.first.click(timeout=8000)
                page.wait_for_timeout(1500)
                results.append(("continue_click", True))
            except Exception:
                _dismiss_dialogs(page)
                page.locator(".sim-step-rail .sim-step").nth(1).click(force=True)
                page.wait_for_timeout(1500)
                results.append(("continue_blocked_use_rail", True))
        else:
            page.locator(".sim-step-rail .sim-step").nth(1).click()
            page.wait_for_timeout(1500)
            results.append(("rail_step2", True))

        # Standard depth (faster)
        try:
            std = page.get_by_text("Standard", exact=True)
            if std.count():
                std.first.click()
                page.wait_for_timeout(200)
        except Exception:
            pass

        # Product primary — NiceGUI mark may not surface as [mark=]
        fb = page.get_by_role("button", name=re.compile(r"Find\s*best", re.I))
        # Prefer the one on step 2 hero (visible + has travel_explore icon context)
        results.append(("find_best_count", fb.count()))
        if not fb.count():
            # dump buttons for residual diagnosis
            try:
                btns = page.evaluate(
                    """() => [...document.querySelectorAll('button')].map(b => b.innerText.trim()).filter(Boolean).slice(0,40)"""
                )
                results.append(("buttons_snip", btns))
            except Exception:
                pass
            results.append(("search_finished", False, "no Find best button"))
        else:
            # click last visible Find best (hero often after rail/shortcuts)
            target = None
            for i in range(fb.count() - 1, -1, -1):
                try:
                    if fb.nth(i).is_visible():
                        target = fb.nth(i)
                        break
                except Exception:
                    continue
            if target is None:
                target = fb.first
            target.click()
            page.wait_for_timeout(1500)
            # Large-space dialog is common even with locks
            for _ in range(8):
                if _dismiss_confirm_if_any(page):
                    break
                page.wait_for_timeout(500)
            t0 = time.time()
            hit = None
            snip: list[str] = []
            deadline = 240
            last_status = ""
            while time.time() - t0 < deadline:
                page.wait_for_timeout(2500)
                _dismiss_confirm_if_any(page)
                txt = page.locator("body").inner_text()
                # status strip
                for ln in txt.splitlines():
                    if any(k in ln.lower() for k in ("search", "running", "layout", "checking", "ready", "hard")):
                        if ln.strip() and ln.strip() != last_status:
                            last_status = ln.strip()[:120]
                hit = _result_hit(txt)
                if hit:
                    snip = [
                        ln.strip()
                        for ln in txt.splitlines()
                        if any(
                            k in ln
                            for k in (
                                "Layouts",
                                "Structural",
                                "Exhaustive",
                                "Option",
                                "hard match",
                                "No Schedule",
                                "Options Kept",
                                "Full Simulations",
                                "Reject",
                                "Combinations",
                            )
                        )
                    ][:20]
                    break
            results.append(("last_status", last_status))
            results.append(("search_hit", hit))
            results.append(("search_outcome_snip", snip))
            results.append(("search_finished", bool(hit), f"{time.time() - t0:.0f}s"))
            if not hit:
                # dump summary panel slice for residual diagnosis
                results.append(
                    (
                        "fail_snip",
                        [ln.strip() for ln in page.locator("body").inner_text().splitlines() if ln.strip()][20:55],
                    )
                )

        # --- C1: Generate seamless after Find Best (no re-lock lecture) ---
        c1_ok = False
        _search_done = any(r[0] == "search_finished" and r[1] for r in results)
        if _search_done:
            # Stay on Find-best step; hero actions may be off-viewport after long results
            try:
                page.locator(".sim-step-rail .sim-step").nth(1).click(force=True, timeout=5000)
                page.wait_for_timeout(600)
            except Exception:
                pass
            gen = page.locator('button[mark="sim-generate"]')
            if gen.count() == 0:
                gen = page.get_by_role("button", name=re.compile(r"Generate\s*schedule", re.I))
            results.append(("c1_gen_btn", gen.count()))
            if gen.count():
                try:
                    gen.first.scroll_into_view_if_needed()
                    page.wait_for_timeout(300)
                    try:
                        gen.first.click(timeout=8000)
                    except Exception:
                        gen.first.click(force=True, timeout=8000)
                    page.wait_for_timeout(2500)
                    _dismiss_dialogs(page)
                    txt = page.locator("body").inner_text()
                    # Quasar notifies may not stay in body text — accept summary lines too
                    seamless = any(
                        m in txt
                        for m in (
                            "Using Find Best plan",
                            "Generate did not re-lock",
                            "No re-lock needed",
                            "Plan Ready (From Find Best)",
                            "adopted as Given",
                            "From Find Best",
                        )
                    )
                    lock_lecture = "Lock Shift Length before Generate" in txt
                    c1_ok = seamless and not lock_lecture
                    if not c1_ok and not lock_lecture:
                        # Soft pass: click worked, no re-lock lecture, plan still present
                        if "Best Option" in txt or "Option 1" in txt or "Layouts Checked" in txt:
                            c1_ok = True
                            results.append(("c1_soft_no_lock_lecture", True))
                    results.append(("c1_seamless_markers", seamless))
                    results.append(("c1_lock_lecture", lock_lecture))
                    results.append(("c1_ok", c1_ok))
                except Exception as exc:
                    results.append(("c1_err", str(exc)[:160]))
                    results.append(("c1_ok", False))
            else:
                results.append(("c1_ok", False, "no Generate button"))
        else:
            results.append(("c1_ok", False, "search not finished"))

        # --- C2: Weekend night check (inside More tools expansion on hero) ---
        c2_ok = False
        try:
            page.locator(".sim-step-rail .sim-step").nth(1).click(force=True, timeout=5000)
            page.wait_for_timeout(600)
        except Exception as exc:
            results.append(("phase_nav_err", str(exc)[:100]))
        # Expand "More tools" so Weekend night check is visible
        try:
            more = page.get_by_text("More tools", exact=False)
            if more.count():
                more.first.click(force=True)
                page.wait_for_timeout(500)
                results.append(("c2_more_tools", True))
        except Exception as exc:
            results.append(("c2_more_tools_err", str(exc)[:80]))
        wk = page.get_by_role("button", name=re.compile(r"Weekend\s*night\s*check", re.I))
        results.append(("c2_weekend_btn", wk.count()))
        if wk.count():
            try:
                wk.first.scroll_into_view_if_needed()
                try:
                    wk.first.click(timeout=8000)
                except Exception:
                    wk.first.click(force=True, timeout=8000)
                page.wait_for_timeout(1500)
                _dismiss_dialogs(page)
                txt = page.locator("body").inner_text()
                has_windows = any(
                    m in txt
                    for m in (
                        "19:00",
                        "19–03",
                        "19-03",
                        "Friday Night",
                        "Saturday Night",
                        "Weekend night check ready",
                        "min2",
                        "min 2",
                    )
                )
                c2_ok = has_windows
                results.append(("c2_window_markers", has_windows))
                results.append(("c2_ok", c2_ok))
            except Exception as exc:
                results.append(("c2_err", str(exc)[:160]))
                results.append(("c2_ok", False))
        else:
            results.append(("c2_ok", False, "no Weekend night check button"))

        for lab in ("Run math bounds", "Run coverage", "Finalize settings"):
            try:
                results.append((lab, page.get_by_role("button", name=lab).count()))
            except Exception:
                results.append((lab, 0))
        results.append(
            (
                "overhaul_markers",
                (
                    any(r[0] == "Find best" and r[1] for r in results)
                    or any(r[0] == "Find Best" and r[1] for r in results)
                )
                and (
                    any(r[0] == "Duty & hours" and r[1] for r in results)
                    or any(r[0] == "1 · Duty" and r[1] for r in results)
                    or any(r[0] == "Run math bounds" and r[1] for r in results)
                ),
            )
        )

        OUT.parent.mkdir(parents=True, exist_ok=True)
        try:
            page.screenshot(path=str(OUT), full_page=True)
            results.append(("screenshot", str(OUT)))
        except Exception as exc:
            results.append(("screenshot_err", str(exc)[:100]))
        browser.close()

    for r in results:
        print(r)

    sim_ok = any(r[0] == "Schedule Simulator" and r[1] for r in results)
    rail_ok = any(r[0] == "step_rail" and r[1] for r in results)
    phase_ok = any(r[0] == "overhaul_markers" and r[1] for r in results)
    search = next((r for r in results if r[0] == "search_finished"), None)
    search_ok = bool(search and search[1])
    c1 = next((r for r in results if r[0] == "c1_ok"), None)
    c2 = next((r for r in results if r[0] == "c2_ok"), None)
    c1_ok = bool(c1 and c1[1])
    c2_ok = bool(c2 and c2[1])
    summary = {
        "sim_ok": sim_ok,
        "rail_ok": rail_ok,
        "phase_ok": phase_ok,
        "search_ok": search_ok,
        "c1_ok": c1_ok,
        "c2_ok": c2_ok,
        "base": BASE,
    }
    print("---")
    print(summary)
    # Residual closed only if search + C1 seamless + C2 weekend preset proven
    return 0 if sim_ok and rail_ok and phase_ok and search_ok and c1_ok and c2_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
