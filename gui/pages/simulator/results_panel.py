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
from logic.result_narrowers import filter_ranked, suggest_lock_actions
from logic.sim_visuals import coverage_band_heatmap


def render_results_panel_tools(
    state,
    _apply_ranked_option,
    _apply_form_payload,
    set_plan,
    plan_box,
    _ui_safe,
    set_why,
    *,
    render_ranked=None,
    set_summary=None,
    form_refs=None,
):

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
        res = state.get("result") or state.get("opt_result") or {}
        band = coverage_band_heatmap(res, max_days=21)
        # Prefer day×start band heat (coverage_by_day); fall back to weekday×slot PNG path
        if band.get("success"):

            def _render_band():
                plan_box.clear()
                with plan_box:
                    from gui.pages.simulator.visuals_panel import render_coverage_heatmap

                    host = ui.element("div").classes("w-full")
                    render_coverage_heatmap(host, res, max_days=21)
                    ui.label("Also available under Explain → Coverage heat.").style(
                        "color:#9AABC4;font-size:0.8rem;margin-top:8px"
                    )

            _ui_safe(_render_band)
            ui.notify("Coverage heat (day × start) ready", type="info")
            return

        hm = shift_coverage_heatmap(res)
        if not hm.get("success"):
            set_plan("Heatmap unavailable: " + str(hm.get("message") or band.get("message")))
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

    def open_end_narrowers():
        """Post-search filters: FLSA / fatigue / cert notes — do not re-run Find Best."""
        refs = form_refs or {}
        opt = state.get("opt_result") or {}
        base = list(state.get("ranked_all") or state.get("ranked") or opt.get("ranked") or [])
        if not base:
            ui.notify("Run Find Best first — nothing to narrow", type="warning")
            return

        with (
            ui.dialog() as dlg,
            ui.card()
            .classes("q-pa-md")
            .style(
                "min-width:22rem;max-width:36rem;background:#0C1A2E;color:#E8EDF4;"
                "border:1px solid rgba(91,141,239,0.35)"
            ),
        ):
            ui.label("Narrow working options").style("font-weight:700;font-size:1.1rem;color:#F8FAFC")
            ui.label(
                "These filters only hide options already found. "
                "They do not re-run Find Best. Certs attach a publish note only."
            ).style("color:#9AABC4;margin:8px 0 12px;line-height:1.4")
            flsa_cb = ui.checkbox("Hide options with FLSA violations", value=False)
            fat_cb = ui.checkbox("Hide options failing fatigue metrics", value=False)
            cert_cb = ui.checkbox("Attach cert codes note (publish / fill)", value=False)
            cert_in = ui.input(
                label="Cert codes",
                value=str(getattr(refs.get("cert_codes"), "value", None) or ""),
                placeholder="FTO, K9",
            ).classes("w-full")

            def _apply():
                codes = []
                if cert_cb.value:
                    raw = (cert_in.value or "").replace(";", ",")
                    codes = [c.strip() for c in raw.split(",") if c.strip()]
                min_rest = 0.0
                max_c = 0
                try:
                    if refs.get("use_fatigue") and getattr(refs["use_fatigue"], "value", False):
                        min_rest = float(str(getattr(refs.get("min_rest"), "value", None) or "0").strip() or 0)
                        max_c = int(float(str(getattr(refs.get("max_consec"), "value", None) or "0").strip() or 0))
                except (TypeError, ValueError):
                    min_rest, max_c = 8.0 if fat_cb.value else 0.0, 6 if fat_cb.value else 0
                if fat_cb.value and min_rest <= 0 and max_c <= 0:
                    min_rest, max_c = 8.0, 6
                out = filter_ranked(
                    base,
                    require_flsa_clean=bool(flsa_cb.value),
                    require_fatigue_ok=bool(fat_cb.value),
                    min_rest_hours=min_rest,
                    max_consecutive_work_days=max_c,
                    required_certs=codes if cert_cb.value else None,
                )
                kept = out.get("ranked") or []
                state["ranked"] = kept
                if render_ranked:
                    render_ranked(kept, selected=1 if kept else 0)
                if kept:
                    _apply_ranked_option(kept[0])
                msg = out.get("message") or ""
                if set_summary:
                    set_summary(msg)
                set_why(msg + ("\n" + (out.get("cert_note") or "") if out.get("cert_note") else ""))
                ui.notify(msg, type="positive" if kept else "warning")
                dlg.close()

            def _reset():
                state["ranked"] = [dict(r) for r in base]
                if render_ranked:
                    render_ranked(state["ranked"], selected=1 if state["ranked"] else 0)
                if state["ranked"]:
                    _apply_ranked_option(state["ranked"][0])
                ui.notify("End filters cleared — showing all found options", type="info")
                dlg.close()

            with ui.row().classes("gap-2 q-mt-md flex-wrap"):
                ui.button("Apply filters", on_click=_apply).classes("btn-primary").props("no-caps unelevated")
                ui.button("Show all options", on_click=_reset).classes("btn-ghost").props("no-caps outline")
                ui.button("Close", on_click=dlg.close).classes("btn-ghost").props("no-caps outline")
        dlg.open()

    def open_stage_lock_actions():
        """Interactive tips: lock form fields and re-search faster."""
        opt = state.get("opt_result") or {}
        ca = (opt.get("constraints_applied") or {}) if isinstance(opt, dict) else {}
        current = {
            "officer_counts": ca.get("officer_counts") or [],
            "length_opts": ca.get("shift_length_options") or [],
            "free_starts": True,
        }
        actions = suggest_lock_actions(
            opt.get("stage_report"),
            opt.get("stage_tips"),
            current=current,
        )
        tips = list(opt.get("stage_tips") or [])
        if not actions and not tips:
            ui.notify("Run Find Best first to get stage tips", type="warning")
            return

        with (
            ui.dialog() as dlg,
            ui.card()
            .classes("q-pa-md")
            .style(
                "min-width:22rem;max-width:36rem;background:#0C1A2E;color:#E8EDF4;"
                "border:1px solid rgba(91,141,239,0.35)"
            ),
        ):
            ui.label("Faster next search").style("font-weight:700;font-size:1.1rem;color:#F8FAFC")
            ui.label("Stages already narrowed the domain. Lock a value below, then run Find Best again.").style(
                "color:#9AABC4;margin:8px 0 12px;line-height:1.4"
            )
            for t in tips[:6]:
                ui.label(f"· {t}").style("color:#D6E6FF;font-size:0.88rem;margin-bottom:4px")

            def _apply_patch(patch: dict, label: str = ""):
                if not patch:
                    ui.notify(label or "Tip only — adjust form manually", type="info")
                    return
                try:
                    _apply_form_payload(patch)
                except Exception:
                    refs = form_refs or {}
                    for k, v in patch.items():
                        w = refs.get(k)
                        if w is None:
                            continue
                        try:
                            if k.startswith("use_") and hasattr(w, "value"):
                                w.value = bool(v)
                            elif hasattr(w, "value"):
                                w.value = v
                        except Exception:
                            pass
                ui.notify(f"Applied: {label or 'form lock'}", type="positive")
                dlg.close()

            for a in actions:
                lab = a.get("label") or a.get("id")
                patch = a.get("form_patch") or {}
                why = a.get("why") or ""

                def _click(p=patch, L=lab):
                    _apply_patch(p, L)

                ui.button(lab, on_click=_click).classes("btn-primary q-mt-xs").props(
                    "no-caps unelevated dense align=left"
                ).style("width:100%;text-align:left;white-space:normal")
                if why:
                    ui.label(why).style("color:#9AABC4;font-size:0.82rem;margin:0 0 8px 12px")
            ui.button("Close", on_click=dlg.close).classes("btn-ghost q-mt-md").props("no-caps outline")
        dlg.open()

    return {
        "show_search_history": show_search_history,
        "show_pins": show_pins,
        "show_slots": show_slots,
        "do_heat": do_heat,
        "show_weekend_heat": show_weekend_heat,
        "do_window_drill": do_window_drill,
        "open_end_narrowers": open_end_narrowers,
        "open_stage_lock_actions": open_stage_lock_actions,
    }
