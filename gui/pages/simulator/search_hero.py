"""Step 2 coverage-search hero UI (extracted from page.py)."""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from nicegui import ui


def build_search_hero(
    state: dict,
    *,
    on_depth_change: Optional[Callable[[], None]] = None,
    on_soft_search: Optional[Callable] = None,
    on_search_history: Optional[Callable[[], None]] = None,
) -> Dict[str, Any]:
    """Build Find-best hero + tools. Returns widget refs for later wiring.

    Callbacks may be bound later via returned widgets' on_click if None here.
    """
    out: Dict[str, Any] = {}

    with ui.element("div").classes("sim-hero"):
        ui.html(
            '<div class="sim-hero-title">Find best schedule</div>'
            '<p class="sim-hero-sub">'
            "Given locks narrow the search. Solve-for axes stay free. "
            "Results show hard OK, windows, rest, and whether the scan was full or partial."
            "</p>",
            sanitize=False,
        )
        ui.html(
            '<div class="sim-micro" style="margin-bottom:6px">Given locks</div>',
            sanitize=False,
        )
        out["lock_strip"] = ui.element("div").classes("sim-lock-strip")
        with ui.element("div").classes("sim-hero-actions"):
            out["btn_opt"] = (
                ui.button("Find best", icon="travel_explore")
                .classes("btn-primary")
                .props("no-caps unelevated")
                .mark("sim-find-best")
            )
            out["btn_gen"] = (
                ui.button("Generate schedule", icon="calendar_month")
                .classes("btn-ghost")
                .props("no-caps outline")
                .mark("sim-generate")
            )

            def _cancel_opt():
                ev = state.get("opt_cancel")
                if ev is not None:
                    ev.set()
                    ui.notify("Cancelling search…", type="warning")
                else:
                    ui.notify("No search running", type="info")

            out["btn_cancel"] = (
                ui.button("Cancel", icon="cancel", on_click=_cancel_opt)
                .classes("btn-ghost")
                .props("no-caps outline dense")
            )
            with ui.element("div").classes("sim-tool-group"):
                ui.html(
                    '<span class="sim-tool-group-label">Depth</span>',
                    sanitize=False,
                )
                out["search_depth"] = (
                    ui.toggle(
                        {"standard": "Faster", "deep": "Thorough"},
                        value=str(state.get("search_depth") or "standard"),
                    )
                    .props("no-caps dense dark")
                    .tooltip(
                        "Faster: shorter search walls + fewer packs after hard-OK. "
                        "Thorough: longer walls + more diversity. "
                        "Free shift lengths always use the full 8–12.5h half-hour grid "
                        "(depth does not drop lengths)."
                    )
                )

            def _on_depth(e=None):
                state["search_depth"] = str(getattr(e, "value", None) or out["search_depth"].value or "standard")
                if on_depth_change:
                    try:
                        on_depth_change()
                    except Exception:
                        pass

            out["search_depth"].on_value_change(_on_depth)
            out["mode_label"] = ui.label("Hard mode").classes("text-xs").style("color:var(--muted);margin-left:4px")

        # Secondary tools behind progressive disclosure (Step 2 declutter)
        with ui.expansion("More tools", icon="tune").classes("w-full sim-hero-secondary").props("dense dark"):
            with ui.element("div").classes("sim-tool-group"):
                out["btn_compare"] = (
                    ui.button("Compare lengths")
                    .classes("btn-ghost")
                    .props("no-caps outline dense")
                    .tooltip("Parallel hard search at 8, 10, 12h")
                )
                out["compare_quick"] = ui.checkbox("Quick", value=True).tooltip(
                    "Faster: 14-day sim, one start pack per length"
                )
                out["btn_min_n"] = (
                    ui.button("Min officers")
                    .classes("btn-ghost")
                    .props("no-caps outline dense")
                    .tooltip("Smallest N that meets hard multi-block constraints")
                )
                out["btn_whatif"] = ui.button("What-if +1").classes("btn-ghost").props("no-caps outline dense")
                out["btn_weekend_preset"] = (
                    ui.button("Weekend night check")
                    .classes("btn-ghost")
                    .props("no-caps outline dense")
                    .tooltip(
                        "Scenario preset (examples only): Fri+Sat 19:00–03:00 min 2 windows + "
                        "24/7 floor on. You still enter N / length / starts. Solve for multi-block."
                    )
                )

                if on_soft_search is not None:
                    ui.button("Soften", on_click=on_soft_search).classes("btn-ghost").props(
                        "no-caps outline dense"
                    ).tooltip("Search without hard fail-fast")
                else:
                    out["btn_soften"] = (
                        ui.button("Soften")
                        .classes("btn-ghost")
                        .props("no-caps outline dense")
                        .tooltip("Search without hard fail-fast")
                    )

                if on_search_history is not None:
                    ui.button("Search history", on_click=on_search_history).classes("btn-ghost").props(
                        "no-caps outline dense"
                    )
                else:
                    out["btn_history"] = ui.button("Search history").classes("btn-ghost").props("no-caps outline dense")

    out["search_status_host"] = ui.element("div").classes("sim-search-status")
    with out["search_status_host"]:
        out["progress_bar"] = (
            ui.linear_progress(value=0, show_value=False)
            .classes("flex-1")
            .props("color=primary track-color=grey-9 size=8px")
        )
        out["progress_bar"].style("display:none")
        out["search_spinner"] = ui.spinner("dots", size="1.6em", color="primary")
        out["search_spinner"].set_visibility(False)
        out["search_status"] = ui.label("Ready · hard constraints").classes("text-xs").style("color:var(--muted)")

    # C3a: Search Mode badge (updated after Find Best)
    out["search_mode_badge"] = ui.label("").classes("text-xs q-mb-xs").style("color:var(--muted);display:none")

    out["kpi_host"] = ui.element("div").classes("kpi-row q-mb-md")
    with out["kpi_host"]:
        ui.html(
            '<div class="empty-state" style="grid-column:1/-1">'
            '<div class="empty-state-title">No search yet</div>'
            '<div class="empty-state-hint">'
            "Run Find best or Generate schedule. Results land here as KPIs."
            "</div></div>",
            sanitize=False,
        )

    return out
