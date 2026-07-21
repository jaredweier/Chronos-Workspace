"""KPI strip for simulator Find-best results (extracted from page.py)."""

from __future__ import annotations

from typing import Any, Optional

from nicegui import ui

from gui.pages.simulator.helpers import _kpi_html


def paint_simulator_kpis(
    kpi_host,
    *,
    hard_ok: Optional[bool] = None,
    officers_n: Any = None,
    layouts: Any = None,
    annual_avg: Any = None,
    window_fails: Any = None,
    rest_fails: Any = None,
    mode_text: str = "",
    annual_warn_target: Optional[float] = None,
    search_truncated: Optional[bool] = None,
    search_exhaustive: Optional[bool] = None,
) -> None:
    """Repaint the KPI host. Safe if host was destroyed (client disconnect)."""
    try:
        kpi_host.clear()
    except RuntimeError:
        return
    except Exception:
        return

    with kpi_host:
        if hard_ok is True:
            tone_h, val_h, hint_h = "g", "OK", "All hard constraints"
        elif hard_ok is False:
            tone_h, val_h, hint_h = "d", "MISS", "Near-miss or fail"
        else:
            tone_h, val_h, hint_h = "v", "—", mode_text or "Awaiting run"

        annual_tone = "v"
        annual_val = "—"
        if annual_avg is not None:
            try:
                annual_val = f"{float(annual_avg):.0f}"
                if annual_warn_target is not None and abs(float(annual_avg) - float(annual_warn_target)) > 20:
                    annual_tone = "w"
                else:
                    annual_tone = "g"
            except (TypeError, ValueError):
                annual_val = "—"
                annual_tone = "v"

        try:
            layouts_s = f"{int(layouts):,}" if layouts is not None else "—"
        except (TypeError, ValueError):
            layouts_s = "—"

        # Honest layout hint — never imply full exhaustive when truncated
        if search_exhaustive is True:
            layouts_hint = "Checked (full scan)"
        elif search_truncated:
            layouts_hint = "Checked (partial)"
        elif mode_text:
            layouts_hint = str(mode_text)[:28]
        else:
            layouts_hint = "Layouts evaluated"

        win_tone = "v"
        if window_fails == 0:
            win_tone = "g"
        elif window_fails:
            win_tone = "d"

        rest_tone = "v"
        rest_val = "—"
        if rest_fails is not None:
            try:
                rf = int(rest_fails)
                rest_val = str(rf)
                rest_tone = "g" if rf == 0 else "d"
            except (TypeError, ValueError):
                rest_val = "—"

        ui.html(
            _kpi_html("Hard", val_h, hint_h, tone_h)
            + _kpi_html(
                "Officers",
                str(officers_n if officers_n is not None else "—"),
                "Selected plan N",
                "v",
            )
            + _kpi_html("Layouts", layouts_s, layouts_hint, "v")
            + _kpi_html("Annual avg", annual_val, "Hours / year", annual_tone)
            + _kpi_html(
                "Windows",
                str(window_fails if window_fails is not None else "—"),
                "Extra-window shortfalls",
                win_tone,
            )
            + (_kpi_html("Rest", rest_val, "Min-rest shortfalls", rest_tone) if rest_fails is not None else ""),
            sanitize=False,
        )
