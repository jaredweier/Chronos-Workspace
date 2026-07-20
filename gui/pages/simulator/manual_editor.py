from nicegui import ui

from gui.pages.simulator.helpers import _HINT
from logic.manual_schedule_build import (
    cycle_cell_start,
    empty_grid,
    evaluate_manual_grid,
    grid_to_text,
    seed_grid_with_nearby_hops,
    set_cell,
)


def render_manual_editor(
    state: dict,
    step_panels: dict,
    go_step,
    _baseline_kwargs,
    _current_config,
    set_plan,
    set_summary,
    session,
    save_last_optimized_plan,
    format_optimized_plan_view,
    length_input,
    officers_input,
    starts_input,
):
    step3 = ui.element("div").classes("w-full").style("display:none")
    step_panels[3] = step3
    with step3:
        with (
            ui.card()
            .classes("w-full q-pa-md")
            .style("background: var(--sim-panel); border: 1px solid var(--sim-border); box-shadow: none;")
        ):
            ui.label("Manual schedule builder").style("font-size: 1.1rem; font-weight: 600; color: #F8FAFC;")
            ui.label(
                "Build any schedule by editing officer × day cells. "
                "Seed from rotation ON days, then override freely. "
                "Evaluate hard constraints, then send to publish."
            ).style(_HINT)
            with ui.row().classes("gap-2 flex-wrap items-end q-mt-sm"):
                man_days = ui.input(label="Days In Grid", value="14").classes("w-32")
                man_officer = ui.input(label="Officer # (1-based)", value="1").classes("w-32")
                man_day = ui.input(label="Day # (0-based)", value="0").classes("w-32")
                man_start = ui.input(
                    label="Start (HH:MM or OFF)",
                    value="OFF",
                    placeholder="19:00 or OFF",
                ).classes("w-40")
            man_grid_box = ui.element("div").classes("sim-grid-host")
            man_eval_box = ui.element("div").classes("sim-result-panel").style("min-height:3rem;")

            def _manual_n_officers() -> int:
                try:
                    n = int((officers_input.value or "").strip() or "0")
                except ValueError:
                    n = 0
                return max(n, 1)

            def _parse_starts():
                text = starts_input.value or ""
                return [s.strip() for s in text.replace(";", ",").split(",") if s.strip()]

            def _manual_starts_list() -> list:
                st = _parse_starts()
                return st if st else ["06:00", "14:00", "19:00", "22:00"]

            def _manual_set_eval(text: str):
                man_eval_box.clear()
                with man_eval_box:
                    ui.label(text or "—").style("color:#D6E6FF;white-space:pre-wrap;line-height:1.45")

            def manual_new_empty():
                try:
                    days = max(1, min(56, int((man_days.value or "14").strip() or "14")))
                except ValueError:
                    days = 14
                state["manual_days"] = days
                state["manual_grid"] = empty_grid(_manual_n_officers(), days)
                _manual_refresh_view()
                _manual_set_eval(f"Empty grid {_manual_n_officers()} officers × {days} days")
                ui.notify("Empty grid ready", type="info")

            def manual_seed_rotation():
                base = _baseline_kwargs()
                if base.get("error"):
                    ui.notify(base["error"], type="negative")
                    return
                try:
                    days = max(1, min(56, int((man_days.value or "14").strip() or "14")))
                except ValueError:
                    days = 14
                n = _manual_n_officers()
                hops = int(base.get("nearby_start_hops") or 0)
                r = seed_grid_with_nearby_hops(
                    num_officers=n,
                    num_days=days,
                    shift_starts=_manual_starts_list(),
                    rotation_type=base.get("rotation_type") or "",
                    rotation_style=base.get("rotation_style") or "rotating",
                    rotation_variations=base.get("rotation_variations") or [],
                    nearby_hops=hops,
                    respect_off_days=True,
                )
                state["manual_grid"] = r.get("grid")
                state["manual_days"] = days
                _manual_refresh_view()
                _manual_set_eval(r.get("message") or "Seeded")
                ui.notify(r.get("message") or "Seeded", type="positive")

            def _manual_refresh_view():
                grid = state.get("manual_grid")
                man_grid_box.clear()
                with man_grid_box:
                    if not grid:
                        ui.label("No grid yet. Use Seed From Rotation or New Empty Grid.").style("color:#9AABC4")
                        return
                    ui.label(grid_to_text(grid, max_days=14)).style("color:#E8EDF4;white-space:pre;font-size:0.85rem;")
                    ui.label("Click a cell button to cycle OFF → pack starts (editable).").style(
                        "color:#9AABC4;font-size:0.8rem;margin-top:8px"
                    )
                    pack = _manual_starts_list()
                    show_days = min(len(grid[0]), 14)
                    show_off = min(len(grid), 12)
                    for oi in range(show_off):
                        with ui.element("div").classes("sim-grid-row"):
                            ui.html(
                                f'<span class="sim-grid-label">O{oi + 1}</span>',
                            )
                            for di in range(show_days):
                                val = grid[oi][di] or "OFF"
                                is_off = str(val).upper() in ("OFF", "", "NONE")

                                def _cycle(o=oi, d=di):
                                    g = state.get("manual_grid")
                                    if not g:
                                        return
                                    r = cycle_cell_start(g, o, d, pack)
                                    if r.get("success"):
                                        state["manual_grid"] = r["grid"]
                                        _manual_refresh_view()

                                cell_cls = (
                                    "btn-ghost sim-cell-btn sim-cell-off"
                                    if is_off
                                    else "btn-ghost sim-cell-btn sim-cell-on"
                                )
                                ui.button(
                                    str(val)[:5],
                                    on_click=_cycle,
                                ).classes(cell_cls).props("dense no-caps outline size=sm").tooltip(
                                    f"Officer {oi + 1} · day {di}"
                                )
                    if len(grid) > show_off or len(grid[0]) > show_days:
                        ui.label(
                            f"Showing {show_off}×{show_days} of {len(grid)}×{len(grid[0])} "
                            "(use Set Cell for full edit)."
                        ).style("color:#7A8FA8;font-size:0.75rem")

            def manual_set_cell():
                grid = state.get("manual_grid")
                if not grid:
                    ui.notify("Create a grid first", type="warning")
                    return
                try:
                    oi = int((man_officer.value or "1").strip()) - 1
                    di = int((man_day.value or "0").strip())
                except ValueError:
                    ui.notify("Bad officer/day", type="negative")
                    return
                raw = (man_start.value or "OFF").strip()
                r = set_cell(grid, oi, di, raw)
                if not r.get("success"):
                    ui.notify(r.get("message") or "Failed", type="negative")
                    return
                state["manual_grid"] = r["grid"]
                _manual_refresh_view()
                ui.notify(f"O{oi + 1} day {di} → {raw}", type="info")

            def manual_evaluate():
                grid = state.get("manual_grid")
                if not grid:
                    ui.notify("No grid", type="warning")
                    return
                base = _baseline_kwargs()
                if base.get("error"):
                    ui.notify(base["error"], type="negative")
                    return
                sh_len = base.get("shift_length_hours")
                if sh_len is None:
                    try:
                        sh_len = float((length_input.value or "").strip())
                    except Exception:
                        sh_len = None
                if sh_len is None:
                    ui.notify("Lock shift length on Requirements first", type="warning")
                    return
                result = evaluate_manual_grid(
                    grid,
                    shift_length_hours=float(sh_len),
                    coverage_247=int(base.get("coverage_247") or 0),
                    use_extra_windows=bool(base.get("use_extra_windows")),
                    extra_windows=list(base.get("extra_windows") or []),
                    annual_hours_target=float(base.get("annual_hours_target") or 0)
                    if base.get("annual_hours_target") is not None
                    else 0.0,
                    annual_hours_variance=float(base.get("annual_hours_variance") or 0)
                    if base.get("annual_hours_variance") is not None
                    else 0.0,
                    annual_hours_hard=bool(base.get("annual_hours_hard")),
                    rotation_type=base.get("rotation_type") or "",
                    rotation_style=base.get("rotation_style") or "",
                    rotation_variations=list(base.get("rotation_variations") or []),
                    nearby_start_hops=int(base.get("nearby_start_hops") or 0),
                    allow_offday_coverage=bool(base.get("allow_offday_coverage")),
                )
                if not result.get("success"):
                    ui.notify(result.get("message") or "Eval failed", type="negative")
                    return
                m = result.get("metrics") or {}
                lines = [
                    result.get("message") or "Evaluated",
                    f"Hard OK: {m.get('hard_constraints_ok')}",
                    f"24/7 shortfalls: {m.get('coverage_247_failures')}",
                    f"Window shortfalls: {m.get('extra_window_failures')}",
                    f"Avg annual (from grid): {m.get('avg_annual_hours')}",
                ]
                _manual_set_eval("\n".join(lines))
                ui.notify("Manual schedule evaluated", type="positive")

            def manual_use_plan():
                grid = state.get("manual_grid")
                if not grid:
                    ui.notify("No grid", type="warning")
                    return
                base = _baseline_kwargs()
                if base.get("error"):
                    ui.notify(base["error"], type="negative")
                    return
                sh_len = base.get("shift_length_hours")
                if sh_len is None:
                    try:
                        sh_len = float((length_input.value or "").strip())
                    except Exception:
                        ui.notify("Lock shift length first", type="warning")
                        return
                result = evaluate_manual_grid(
                    grid,
                    shift_length_hours=float(sh_len),
                    coverage_247=int(base.get("coverage_247") or 0),
                    use_extra_windows=bool(base.get("use_extra_windows")),
                    extra_windows=list(base.get("extra_windows") or []),
                    annual_hours_target=float(base.get("annual_hours_target") or 0)
                    if base.get("annual_hours_target") is not None
                    else 0.0,
                    annual_hours_variance=float(base.get("annual_hours_variance") or 0)
                    if base.get("annual_hours_variance") is not None
                    else 0.0,
                    annual_hours_hard=bool(base.get("annual_hours_hard")),
                    rotation_type=base.get("rotation_type") or "",
                    rotation_style=base.get("rotation_style") or "",
                    rotation_variations=list(base.get("rotation_variations") or []),
                    nearby_start_hops=int(base.get("nearby_start_hops") or 0),
                    allow_offday_coverage=bool(base.get("allow_offday_coverage")),
                )
                if not result.get("success"):
                    ui.notify(result.get("message") or "Failed", type="negative")
                    return
                state["result"] = result
                state["config"] = result.get("simulation_config") or _current_config()
                uid = (session.current_user() or {}).get("id")
                save_last_optimized_plan(result, state["config"], user_id=uid)
                view = format_optimized_plan_view(result, state["config"])
                try:
                    set_plan(view.get("text") or result.get("message") or "")
                    set_summary(result.get("message") or "Manual plan ready")
                except Exception:
                    pass
                _manual_set_eval((result.get("message") or "OK") + "\nPlan stored — go to Publish.")
                ui.notify("Manual plan ready for Publish", type="positive")
                go_step(4)

            with ui.row().classes("gap-2 flex-wrap q-mt-md"):
                ui.button("New Empty Grid", on_click=manual_new_empty).classes("btn-ghost").props("no-caps outline")
                ui.button("Seed From Rotation (ON Days)", on_click=manual_seed_rotation).classes("btn-primary").props(
                    "no-caps unelevated"
                )
                ui.button("Set Cell", on_click=manual_set_cell).classes("btn-ghost").props("no-caps outline")
                ui.button("Evaluate", on_click=manual_evaluate).classes("btn-ghost").props("no-caps outline")
                ui.button("Use as plan → publish", on_click=manual_use_plan).classes("btn-primary").props(
                    "no-caps unelevated"
                )
            with ui.row().classes("gap-2 flex-wrap q-mt-sm"):
                ui.button("Back to find best", on_click=lambda: go_step(2)).classes("btn-ghost").props(
                    "no-caps outline"
                )
                ui.button("Back to requirements", on_click=lambda: go_step(1)).classes("btn-ghost").props(
                    "no-caps outline"
                )

    return _manual_refresh_view
