from nicegui import ui

from logic.optimizer_features import (
    explain_window_failures,
    list_pinned_options,
    list_search_history,
    load_scenario_slots,
    shift_coverage_heatmap,
    unpin_option,
    weekend_night_heat_lines,
)


def render_results_panel_tools(state, _apply_ranked_option, _apply_form_payload, set_plan, plan_box, _ui_safe, set_why):

    def show_search_history():
        rows = list_search_history(limit=12)
        with (
            ui.dialog() as dlg,
            ui.card().classes("q-pa-md").style("min-width:22rem;max-width:40rem;background:#0C1A2E;color:#E8EDF4"),
        ):
            ui.label("Recent Optimizer Searches").style("font-weight:700;font-size:1.05rem;color:#F8FAFC")
            if not rows:
                ui.label("No searches yet.").style("color:#9AABC4")
            for row in rows:
                ui.label(
                    f"{row.get('at')} · "
                    f"{'OK' if row.get('success') else 'NO'} · "
                    f"N={row.get('num_officers') or '—'} · "
                    f"{row.get('wall_time_ms') or '—'}ms · "
                    f"{(row.get('message') or '')[:60]}"
                ).style("color:#D6E6FF;font-size:0.85rem;margin-top:6px;white-space:pre-wrap")
            ui.button("Close", on_click=dlg.close).classes("btn-ghost q-mt-md").props("no-caps outline")
        dlg.open()

    def show_pins():
        pins = list_pinned_options()
        with (
            ui.dialog() as dlg,
            ui.card().classes("q-pa-md").style("min-width:22rem;max-width:40rem;background:#0C1A2E;color:#E8EDF4"),
        ):
            ui.label("Pinned Options").style("font-weight:700;font-size:1.05rem")
            if not pins:
                ui.label("None yet.").style("color:#9AABC4")
            for i, p in enumerate(pins[:15]):
                row = p.get("row") or {}
                lab = f"{p.get('label')} · N={row.get('num_officers')} · {p.get('pinned_at')}"

                def _load_pin(r=row):
                    state["selected_row"] = r
                    _apply_ranked_option(r)
                    dlg.close()
                    ui.notify("Pinned option loaded", type="positive")

                def _drop(idx=i):
                    unpin_option(idx)
                    dlg.close()
                    ui.notify("Unpinned", type="info")

                with ui.row().classes("gap-2 items-center flex-wrap q-mt-xs"):
                    ui.button(lab[:80], on_click=_load_pin).classes("btn-ghost").props("no-caps outline dense")
                    ui.button("×", on_click=_drop).classes("btn-ghost").props("dense flat")
            ui.button("Close", on_click=dlg.close).classes("btn-ghost q-mt-md").props("no-caps outline")
        dlg.open()

    def show_slots():
        data = load_scenario_slots()
        with (
            ui.dialog() as dlg,
            ui.card().classes("q-pa-md").style("min-width:22rem;background:#0C1A2E;color:#E8EDF4"),
        ):
            ui.label("Multi-Scenario A / B / C").style("font-weight:700")
            for letter in ("A", "B", "C"):
                slot = data.get(letter) or {}
                if not slot:
                    ui.label(f"{letter}: empty").style("color:#7A8FA8;margin-top:6px")
                    continue
                ui.label(
                    f"{letter}: {slot.get('saved_at')} · "
                    f"{'OK' if slot.get('result_success') else '—'} · "
                    f"{(slot.get('message') or '')[:50]}"
                ).style("color:#D6E6FF;margin-top:6px")

                def _load(s=slot):
                    row = s.get("ranked_row") or s.get("best")
                    if row:
                        _apply_ranked_option(row)
                    cfg = s.get("config") or {}
                    if cfg:
                        # Full form payload shape — use flags + rot model so toggles match
                        vars_raw = cfg.get("rotation_variations") or []
                        has_vars = bool(vars_raw)
                        _apply_form_payload(
                            {
                                "officers": cfg.get("num_officers"),
                                "length": cfg.get("shift_length_hours"),
                                "annual": cfg.get("annual_hours_target"),
                                "annual_var": cfg.get("annual_hours_variance"),
                                "starts": ", ".join(cfg.get("shift_starts") or [])
                                if isinstance(cfg.get("shift_starts"), list)
                                else cfg.get("shift_starts"),
                                "variations": " | ".join(vars_raw) if isinstance(vars_raw, list) else vars_raw,
                                "use_officers": cfg.get("num_officers") is not None,
                                "use_length": cfg.get("shift_length_hours") is not None,
                                "use_starts": bool(cfg.get("shift_starts")),
                                "use_annual": cfg.get("annual_hours_target") is not None,
                                "use_rot_model": True,
                                "rot_model_kind": ("Multi-block on/off" if has_vars else "Squad preset"),
                                "use_style": has_vars,
                                "use_rotation": not has_vars,
                                "use_fatigue": float(cfg.get("min_rest_hours") or 0) > 0
                                or int(cfg.get("max_consecutive_work_days") or 0) > 0,
                                "min_rest": cfg.get("min_rest_hours"),
                                "max_consec": cfg.get("max_consecutive_work_days"),
                                "use_247": int(cfg.get("coverage_247") or 0) > 0,
                                "cov247": cfg.get("coverage_247"),
                                "use_windows": bool(cfg.get("use_extra_windows")),
                                "min_ps": cfg.get("min_per_shift"),
                                "windows": cfg.get("extra_windows"),
                            }
                        )
                    dlg.close()
                    ui.notify("Slot loaded", type="positive")

                ui.button(f"Load {letter}", on_click=_load).classes("btn-ghost").props("no-caps outline dense")
            ui.button("Close", on_click=dlg.close).classes("btn-ghost q-mt-md").props("no-caps outline")
        dlg.open()

    def do_heat():
        res = state.get("result") or {}
        hm = shift_coverage_heatmap(res)
        if not hm.get("success"):
            set_plan("Heatmap unavailable: " + str(hm.get("message")))
            return

        def _render():
            plan_box.clear()
            with plan_box:
                ui.label("Shift Coverage Heatmap").style(
                    "font-size: 1.2rem; font-weight: bold; color: #F8FAFC; margin-bottom: 8px;"
                )
                with ui.row().classes("gap-1 items-start"):
                    matrix = hm.get("matrix", [])
                    labels = hm.get("day_labels", [])
                    for wd, day_label in enumerate(labels):
                        if wd >= len(matrix):
                            continue
                        with ui.column().classes("gap-0"):
                            ui.label(day_label).style(
                                "font-size: 0.8rem; font-weight: bold; color: #9AABC4; text-align: center;"
                            )
                            for val in matrix[wd]:
                                color = "#3B7DD8" if val >= 2 else ("#5b8def" if val >= 1 else "#0f172a")
                                if val < hm.get("coverage_threshold", 1):
                                    color = "#ef4444"
                                ui.element("div").style(
                                    f"width: 24px; height: 10px; background-color: {color}; margin-bottom: 1px;"
                                )
                                ui.tooltip(f"{val} officers")
                ui.label(hm.get("message", "")).style("color: #E8EDF4; margin-top: 8px;")

        _ui_safe(_render)
        ui.notify("Heat grid visual ready", type="info")

    def show_weekend_heat():
        res = state.get("result") or state.get("opt_result") or {}
        if res.get("best") and not res.get("metrics"):
            pass
        lines = weekend_night_heat_lines(state.get("result") or res)
        set_why("\n".join(lines))
        ui.notify("Weekend heat in Why panel", type="info")

    def do_window_drill():
        res = state.get("result") or state.get("opt_result") or {}
        lines = explain_window_failures(res)
        set_why("\n".join(lines))
        ui.notify("Window drill-down in Why panel", type="info")

    return {
        "show_search_history": show_search_history,
        "show_pins": show_pins,
        "show_slots": show_slots,
        "do_heat": do_heat,
        "show_weekend_heat": show_weekend_heat,
        "do_window_drill": do_window_drill,
    }
