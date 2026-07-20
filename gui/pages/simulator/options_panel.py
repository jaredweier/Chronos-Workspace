from nicegui import ui

from gui.pages.simulator.helpers import (
    _DOW_NAME_TO_WEEKDAY,
    _DOW_NAMES,
    _HINT,
    _ROTATION_OPTIONS,
    _STYLE_OPTIONS,
    _WEEKDAY_TO_NAME,
    _set_enabled,
    given_solve_toggle,
)
from gui.shell import panel
from logic.optimizer_features import get_window_template, list_window_templates
from logic.staffing_insights import court_board_to_demand_windows, get_demand_template, list_demand_templates
from validators import parse_date, storage_date_str


def render_options_panel(
    state: dict,
    placeholder_rot: str,
    _persist_form,
    _refresh_space_estimate,
    _show_constraint_suggestions,
):
    ui_elements = {}

    with panel("Coverage Requirements"):
        with (
            ui.element("div")
            .classes("w-full grid sim-option-card")
            .style("grid-template-columns: minmax(200px, 1fr) 2fr; align-items: center; gap: 1.5rem;")
        ):
            use_start_date = ui.checkbox("Target Start Date", value=False)
            with ui.element("div"):
                sim_start_date = ui.input(
                    label="YYYY-MM-DD",
                    value="",
                    placeholder="e.g. 2026-07-17",
                ).classes("w-full")
        use_start_date.on_value_change(lambda e: _set_enabled([sim_start_date], bool(e.value)))
        _set_enabled([sim_start_date], False)

        with (
            ui.element("div")
            .classes("w-full grid sim-option-card")
            .style("grid-template-columns: minmax(200px, 1fr) 2fr; align-items: center; gap: 1.5rem;")
        ):
            use_rotation = given_solve_toggle(ui, "Rotation Pattern")
            with ui.element("div"):
                rotation = (
                    ui.select(
                        _ROTATION_OPTIONS,
                        value=placeholder_rot,
                        label="Pattern",
                    )
                    .classes("w-full")
                    .props("outlined dense dark")
                )
                ui.label("Solve for: every rotation pattern is searched").classes("sim-free-hint")
        use_rotation.on_value_change(lambda e: _set_enabled([rotation], bool(e.value)))
        _set_enabled([rotation], False)

        with (
            ui.element("div")
            .classes("w-full grid sim-option-card")
            .style("grid-template-columns: minmax(200px, 1fr) 2fr; align-items: center; gap: 1.5rem;")
        ):
            use_officers = given_solve_toggle(ui, "Officer Count").tooltip(
                "Locked: Uses exact number. Unlocked: Searches between Min/Max band to find optimal headcount."
            )
            with ui.element("div"):
                with ui.row().classes("w-full gap-2 no-wrap"):
                    officers = ui.input(
                        label="Min / Exact",
                        value="8",
                        placeholder="e.g. 8",
                    ).classes("w-full")
                    officers_max = (
                        ui.input(
                            label="Max (Unlocked)",
                            value="12",
                            placeholder="e.g. 12",
                        )
                        .classes("w-full")
                        .bind_visibility_from(use_officers, "value", backward=lambda x: not x)
                    )
                ui.label("Solve for: Search space bounds").classes("sim-free-hint")

        def _on_lock_officers(e=None):
            _set_enabled([officers], True)  # Always enabled so user can set min/exact
            try:
                _refresh_space_estimate()
            except Exception:
                pass

        use_officers.on_value_change(_on_lock_officers)
        _set_enabled([officers], False)

        with (
            ui.element("div")
            .classes("w-full grid sim-option-card")
            .style("grid-template-columns: minmax(200px, 1fr) 2fr; align-items: center; gap: 1.5rem;")
        ):
            use_length = given_solve_toggle(ui, "Shift Length").tooltip(
                "Locked: All shifts use this duration. Unlocked: Optimizer sweeps multiple lengths (e.g. 8, 10, 12)."
            )
            with ui.element("div"):
                length = ui.input(
                    label="Hours (0.5 Steps)",
                    value="8",
                    placeholder="e.g. 8",
                ).classes("w-full")
                ui.label("Solve for: 8/10/12h (Standard) · 8–12h in half-hour steps (Deep)").classes("sim-free-hint")

        def _on_lock_length(e=None):
            _set_enabled([length], bool(use_length.value))
            try:
                _refresh_space_estimate()
            except Exception:
                pass

        use_length.on_value_change(_on_lock_length)
        _set_enabled([length], False)

        with (
            ui.element("div")
            .classes("w-full grid sim-option-card")
            .style("grid-template-columns: minmax(200px, 1fr) 2fr; align-items: center; gap: 1.5rem;")
        ):
            use_annual = ui.checkbox("Require: Annual Hours Target", value=False).tooltip(
                "Locked: Strict failure if projected annual hours fall outside target ± variance. Unlocked: Reported but does not reject scenario."
            )
            with ui.element("div"):
                annual = ui.input(
                    label="Annual Hours Target",
                    value="2080",
                    placeholder="e.g. 2080",
                ).classes("w-full")
                annual_var = ui.input(
                    label="Allowed Variance (± Hours)",
                    value="20",
                    placeholder="e.g. 20",
                ).classes("w-full")
        use_annual.on_value_change(lambda e: _set_enabled([annual, annual_var], bool(e.value)))
        _set_enabled([annual, annual_var], False)

        with (
            ui.element("div")
            .classes("w-full grid sim-option-card")
            .style("grid-template-columns: minmax(200px, 1fr) 2fr; align-items: center; gap: 1.5rem;")
        ):
            use_starts = given_solve_toggle(ui, "Shift Start Times").tooltip(
                "Locked: Exact start times used. Unlocked: Optimizer searches realistic start packs across 24h clock."
            )
            with ui.element("div"):
                starts = ui.input(
                    label="Starts (Comma-Separated)",
                    value="06:00, 14:00, 22:00",
                    placeholder="e.g. 06:00, 14:00, 19:00, 22:00",
                ).classes("w-full")
                ui.label("Solve for: realistic start packs searched per length").classes("sim-free-hint")
                ui.html(
                    '<div style="font-size: 0.8rem; color: var(--sim-muted); margin-top: 4px;">Real-world 8h pack (e.g. 06:00, 14:00, 22:00) provides 3 equal 8-hour shift bands.</div>'
                )

        def _on_lock_starts(e=None):
            _set_enabled([starts], bool(use_starts.value))
            try:
                _refresh_space_estimate()
            except Exception:
                pass

        use_starts.on_value_change(_on_lock_starts)
        _set_enabled([starts], False)

        with (
            ui.element("div")
            .classes("w-full grid sim-option-card")
            .style("grid-template-columns: minmax(200px, 1fr) 2fr; align-items: center; gap: 1.5rem;")
        ):
            use_min_ps = ui.checkbox("Require: Minimum Officers Per Shift", value=False).tooltip(
                "Locked: Hard constraint enforcing every shift band gets >= X officers."
            )
            with ui.element("div"):
                min_ps = ui.input(
                    label="Minimum Officers Per Shift",
                    value="1",
                    placeholder="e.g. 1",
                ).classes("w-full")

        def _on_lock_min_ps(e=None):
            _set_enabled([min_ps], bool(use_min_ps.value))
            try:
                _refresh_space_estimate()
            except Exception:
                pass

        use_min_ps.on_value_change(_on_lock_min_ps)
        _set_enabled([min_ps], False)

        with (
            ui.element("div")
            .classes("w-full grid sim-option-card")
            .style("grid-template-columns: minmax(200px, 1fr) 2fr; align-items: center; gap: 1.5rem;")
        ):
            use_247 = ui.checkbox("Require: 24/7 Continuous Minimum", value=False).tooltip(
                "Locked: Fails immediately if coverage drops below X at any minute of the day."
            )
            with ui.element("div"):
                cov247 = ui.input(
                    label="24/7 Minimum (All Hours)",
                    value="1",
                    placeholder="e.g. 1",
                ).classes("w-full")
        use_247.on_value_change(lambda e: _set_enabled([cov247], bool(e.value)))
        _set_enabled([cov247], False)

        with (
            ui.element("div")
            .classes("w-full grid sim-option-card")
            .style("grid-template-columns: minmax(200px, 1fr) 2fr; align-items: center; gap: 1.5rem;")
        ):
            use_style = given_solve_toggle(ui, "Rotation Style").tooltip(
                "Select Fixed or Rotating to enforce a style, or leave unlocked to explore both."
            )
            with ui.element("div"):
                rot_style = (
                    ui.select(_STYLE_OPTIONS, value="Rotating", label="Style")
                    .classes("w-full")
                    .props("outlined dense dark")
                )
                ui.label("Solve for: multi-block variations discovered naturally").classes("sim-free-hint")
                # Hide variations input in standard view, simulator will naturally discover or use active rotation.
                variations = ui.input(value="").classes("hidden")

        use_style.on_value_change(lambda e: _set_enabled([rot_style], bool(e.value)))
        _set_enabled([rot_style], False)

        with ui.expansion(
            "Advanced requirements (bumps, off-day OT, certs, fatigue, FLSA)",
            icon="tune",
            value=False,
        ).classes("sim-adv w-full q-mt-sm"):
            with (
                ui.element("div")
                .classes("w-full grid sim-option-card")
                .style("grid-template-columns: minmax(200px, 1fr) 2fr; align-items: center; gap: 1.5rem;")
            ):
                use_nearby = ui.checkbox("Allow: Nearby Start Bumps (Work Days)", value=False).tooltip(
                    "Locked: Allows up to N bumps based on available start bands. Unlocked: Rigid single home start."
                )
                with ui.element("div"):
                    nearby_hops = ui.input(
                        label="Max Bumps (0-6)",
                        value="2",
                        placeholder="e.g. 2",
                    ).classes("w-full")
                    ui.label("Example: home 19:00 with 1 bump → 14:00 or 22:00 on ON days only.").style(_HINT)
            use_nearby.on_value_change(lambda e: _set_enabled([nearby_hops], bool(e.value)))
            _set_enabled([nearby_hops], False)

            with (
                ui.element("div")
                .classes("w-full grid sim-option-card")
                .style("grid-template-columns: minmax(200px, 1fr) 2fr; align-items: center; gap: 1.5rem;")
            ):
                allow_offday = ui.checkbox("Allow Off-Day Coverage (OT Call-In)", value=False).tooltip(
                    "Locked: Off-days can be filled (OT). Unlocked: Only work days filled."
                )
                with ui.element("div"):
                    ui.label("Only when checked: multi-block OFF days may fill windows.").style(_HINT)

            with (
                ui.element("div")
                .classes("w-full grid sim-option-card")
                .style("grid-template-columns: minmax(200px, 1fr) 2fr; align-items: center; gap: 1.5rem;")
            ):
                use_certs = ui.checkbox("Require: Cert Codes (Fill Gate)", value=False)
                with ui.element("div"):
                    cert_codes = ui.input(
                        label="Cert Codes (Comma-Separated)",
                        value="FTO, K9, EMT",
                        placeholder="e.g. FTO, K9, EMT",
                    ).classes("w-full")
                    ui.label(
                        "Only officers holding these codes are eligible when applying home starts / open-shift style fills."
                    ).style(_HINT)
            use_certs.on_value_change(lambda e: _set_enabled([cert_codes], bool(e.value)))
            _set_enabled([cert_codes], False)

            with (
                ui.element("div")
                .classes("w-full grid sim-option-card")
                .style("grid-template-columns: minmax(200px, 1fr) 2fr; align-items: center; gap: 1.5rem;")
            ):
                use_fatigue = ui.checkbox("Require: Fatigue / Rest Rules", value=False).tooltip(
                    "Locked: Hard validation of rest periods between shifts. Unlocked: Natural rest only."
                )
                with ui.element("div"):
                    min_rest = ui.input(
                        label="Min Rest (Hours)",
                        value="8",
                        placeholder="e.g. 8",
                    ).classes("w-full")
                    max_consec = ui.input(
                        label="Max Consecutive Work Days",
                        value="5",
                        placeholder="e.g. 5",
                    ).classes("w-full")
                    ui.label(
                        "Optional hard fatigue: rest between consecutive duty days; cap multi-block ON streaks."
                    ).style(_HINT)
            use_fatigue.on_value_change(lambda e: _set_enabled([min_rest, max_consec], bool(e.value)))
            _set_enabled([min_rest, max_consec], False)

            with (
                ui.element("div")
                .classes("w-full grid sim-option-card")
                .style("grid-template-columns: minmax(200px, 1fr) 2fr; align-items: center; gap: 1.5rem;")
            ):
                use_flsa = ui.checkbox("Require: Avoid FLSA Overtime", value=False).tooltip(
                    "Locked: Fails if FLSA threshold exceeded. Evaluated dynamically based on rotation length."
                )
                with ui.element("div"):
                    flsa_days = ui.input(
                        label="Max Work Period (Days)",
                        value="28",
                        placeholder="e.g. 28",
                    ).classes("w-full")
            use_flsa.on_value_change(lambda e: _set_enabled([flsa_days], bool(e.value)))
            _set_enabled([flsa_days], False)

    with panel("Extra Minimum Staffing Windows"):
        ui.label(
            "When checked, every window below is a hard minimum. "
            "Windows are empty until you add them or restore a saved form. "
            "Demand templates convert peak-risk hours into windows."
        ).style(_HINT)
        use_windows = ui.checkbox("Require: Extra Minimum Staffing Windows", value=False).tooltip(
            "Locked: Validates peak windows (merges with 24/7 / Min per Shift, doesn't stack)."
        )
        with ui.row().classes("gap-2 flex-wrap q-mb-sm"):
            for tmpl in list_demand_templates():

                def _apply_demand(tid=tmpl["id"], lab=tmpl["label"]):
                    if tid == "from_court_board":
                        r = court_board_to_demand_windows()
                        wins = list(r.get("windows") or [])
                        if not wins:
                            ui.notify(r.get("message") or "No court events", type="warning")
                            return
                        msg = r.get("message") or lab
                    else:
                        wins = get_demand_template(tid)
                        msg = lab
                    if not wins:
                        ui.notify("Unknown template", type="warning")
                        return
                    state["windows"] = list(wins)
                    use_windows.value = True
                    try:
                        _refresh_win_list()
                    except Exception:
                        pass
                    _persist_form()
                    ui.notify(f"Demand windows: {msg}", type="positive")
                    try:
                        _show_constraint_suggestions("windows")
                    except Exception:
                        pass

                ui.button(tmpl["label"][:32], on_click=_apply_demand).classes("btn-ghost").props(
                    "dense no-caps outline"
                )
        win_body = ui.column().classes("w-full")
        win_list_col = ui.column().classes("w-full gap-1 q-mb-sm")

        def _refresh_win_list():
            win_list_col.clear()
            with win_list_col:
                if not state["windows"]:
                    ui.label("No Windows Added Yet.").style("color:#7A8FA8;font-size:0.9rem")
                    return
                for i, w in enumerate(state["windows"]):
                    if w.get("specific_date"):
                        when = f"Date {w.get('specific_date')}"
                    elif w.get("weekday") is not None:
                        when = _WEEKDAY_TO_NAME.get(w.get("weekday"), f"Weekday {w.get('weekday')}")
                    else:
                        when = "Any Day"
                    line = (
                        f"#{i + 1} · Min {w.get('min_officers')} · "
                        f"{w.get('start_time')}–{w.get('end_time')} · "
                        f"{when} · {w.get('label') or 'Window'}"
                    )
                    with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                        ui.label(line).classes("text-sm").style("color:#E8EDF4;flex:1")

                        def _del(idx=i):
                            if 0 <= idx < len(state["windows"]):
                                state["windows"].pop(idx)
                                _refresh_win_list()

                        ui.button("Remove", on_click=_del).classes("btn-ghost").props("dense no-caps outline")

        with win_body:
            _refresh_win_list()
            w_min = ui.input(label="Min Officers", value="2").classes("w-full")
            w_start = ui.input(label="Start Time (HH:MM)", value="19:00").classes("w-full")
            w_end = ui.input(label="End Time (HH:MM)", value="03:00").classes("w-full")
            w_dow = (
                ui.select(_DOW_NAMES, value="Friday", label="Day Of Week")
                .classes("w-full")
                .props("outlined dense dark")
            )
            w_date = ui.input(label="Or Specific Date (M/D/YY, Optional)", value="").classes("w-full")
            w_label = ui.input(label="Label", value="Friday Night").classes("w-full")
            win_inputs = [w_min, w_start, w_end, w_dow, w_date, w_label]

            def add_window():
                if not use_windows.value:
                    ui.notify("Enable Extra Windows First", type="warning")
                    return
                try:
                    mn = int((w_min.value or "1").strip())
                except ValueError:
                    ui.notify("Min Officers Must Be A Number", type="negative")
                    return
                start = (w_start.value or "").strip()
                end = (w_end.value or "").strip()
                if not start or not end:
                    ui.notify("Start And End Times Required", type="negative")
                    return
                day_name = (w_dow.value or "Any Day").strip()
                weekday = _DOW_NAME_TO_WEEKDAY.get(day_name)
                specific_iso = None
                raw_d = (w_date.value or "").strip()
                if raw_d:
                    try:
                        specific_iso = storage_date_str(parse_date(raw_d))
                    except Exception:
                        ui.notify("Date Must Be M/D/YY", type="negative")
                        return
                state["windows"].append(
                    {
                        "min_officers": mn,
                        "start_time": start,
                        "end_time": end,
                        "weekday": weekday if not specific_iso else None,
                        "specific_date": specific_iso,
                        "label": (w_label.value or "").strip() or "Window",
                        "enabled": True,
                    }
                )
                _refresh_win_list()
                ui.notify(f"Window Added ({day_name})", type="positive")

            def load_dept_windows():
                try:
                    from logic import list_coverage_windows

                    n = 0
                    for row in list_coverage_windows() or []:
                        if row.get("enabled") is False:
                            continue
                        state["windows"].append(
                            {
                                "min_officers": row.get("min_officers") or 1,
                                "start_time": row.get("start_time"),
                                "end_time": row.get("end_time"),
                                "weekday": row.get("weekday"),
                                "specific_date": row.get("specific_date"),
                                "label": row.get("label") or "Window",
                                "enabled": True,
                            }
                        )
                        n += 1
                    _refresh_win_list()
                    ui.notify(f"Loaded {n} Department Window(s)", type="info")
                except Exception as exc:
                    ui.notify(f"Could Not Load: {exc}", type="negative")

            def apply_window_template(tid: str):
                wins = get_window_template(tid)
                if not wins:
                    ui.notify("Unknown template", type="warning")
                    return
                use_windows.value = True
                state["windows"] = list(wins)
                _refresh_win_list()
                ui.notify(f"Loaded window template ({len(wins)})", type="positive")

            with ui.row().classes("gap-2 flex-wrap q-mt-sm"):
                btn_add_win = (
                    ui.button("Add Window", on_click=add_window)
                    .classes("btn-primary")
                    .props("no-caps unelevated dense")
                )
                btn_load_win = (
                    ui.button("Load From Operations", on_click=load_dept_windows)
                    .classes("btn-ghost")
                    .props("no-caps outline dense")
                )
                for tmpl in list_window_templates():
                    tid = tmpl["id"]
                    ui.button(
                        tmpl["label"][:28],
                        on_click=lambda t=tid: apply_window_template(t),
                    ).classes("btn-ghost").props("no-caps outline dense")
                win_inputs.extend([btn_add_win, btn_load_win])

        def _sync_win_enabled(e=None):
            _set_enabled(win_inputs, bool(use_windows.value))

        use_windows.on_value_change(_sync_win_enabled)

    ui_elements = {
        "use_start_date": use_start_date,
        "sim_start_date": sim_start_date,
        "use_rotation": use_rotation,
        "rotation": rotation,
        "use_officers": use_officers,
        "officers": officers,
        "officers_max": officers_max,
        "use_length": use_length,
        "length": length,
        "use_annual": use_annual,
        "annual": annual,
        "annual_var": annual_var,
        "use_starts": use_starts,
        "starts": starts,
        "use_min_ps": use_min_ps,
        "min_ps": min_ps,
        "use_247": use_247,
        "cov247": cov247,
        "use_style": use_style,
        "rot_style": rot_style,
        "variations": variations,
        "use_nearby": use_nearby,
        "nearby_hops": nearby_hops,
        "allow_offday": allow_offday,
        "use_certs": use_certs,
        "cert_codes": cert_codes,
        "use_fatigue": use_fatigue,
        "min_rest": min_rest,
        "max_consec": max_consec,
        "use_flsa": use_flsa,
        "flsa_days": flsa_days,
        "use_windows": use_windows,
        "_refresh_win_list": _refresh_win_list,
    }
    return ui_elements
