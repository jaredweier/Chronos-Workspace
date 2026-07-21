"""Requirements step (Phase 1–3 form) — extracted from page.py."""

from __future__ import annotations

from typing import Any, Callable, Dict

from nicegui import ui

from config import SIMULATOR_ROTATION_TYPES
from gui.pages.simulator.helpers import (
    _HINT,
    _MULTI_BLOCK_LABELS,
    _MULTI_BY_LABEL,
    _ROTATION_OPTIONS,
    _STYLE_OPTIONS,
    _set_enabled,
    given_solve_toggle,
)
from gui.pages.simulator.windows_panel import render_windows_panel
from gui.shell import panel
from logic import (
    get_simulator_scenario,
    list_simulator_scenarios,
)
from logic.scheduling_sim import get_simulator_defaults_from_roster


def render_requirements_form(
    state: dict,
    step_panels: dict,
    go_step: Callable[[int], None],
    *,
    baseline_kwargs: Callable[[], dict],
    refresh_space_estimate: Callable[[], None],
    persist_form: Callable[[], None],
    restore_form: Callable[[], None],
    show_suggestions: Callable[[str], None],
) -> Dict[str, Any]:
    """Build Step 1 Requirements UI (inner Phase 1–3). Returns form widget refs."""
    out: Dict[str, Any] = {}

    _placeholder_rot = SIMULATOR_ROTATION_TYPES[0] if SIMULATOR_ROTATION_TYPES else ""

    # ── Step 1 ─────────────────────────────────────────────────────────
    step1 = ui.element("div").classes("w-full")
    step_panels[1] = step1
    with step1:
        with ui.element("div").classes("sim-quickstart q-mb-sm"):
            ui.label("Shortcuts").classes("sim-micro")
            with ui.row().classes("gap-2 flex-wrap"):
                # Ghost only — one primary CTA lives on step 2 (Find best)
                btn_q_min = (
                    ui.button("Fewest officers", icon="groups")
                    .classes("btn-ghost")
                    .props("no-caps outline dense")
                    .tooltip("Smallest headcount that meets locked requirements")
                )
                btn_q_will = (
                    ui.button("Will N work?", icon="help_center")
                    .classes("btn-ghost")
                    .props("no-caps outline dense")
                    .tooltip("Lock headcount as Given, then search")
                )
                btn_q_plus = (
                    ui.button("What-if +1", icon="trending_up")
                    .classes("btn-ghost")
                    .props("no-caps outline dense")
                    .tooltip("Compare current headcount vs one more officer")
                )

        ui.label(
            "Given = you lock the value. Solve for = Find Best searches. "
            "Leave fields empty + Solve for until you know the number."
        ).style(_HINT)

        def _refresh_lock_progress():
            # Progress strip removed in the declutter pass — the
            # Given/Solve-for toggles already show state per row.
            pass

        with ui.element("div").classes("grid-2"):

            def _run_phase(limit: int):
                try:
                    kwargs = baseline_kwargs()
                    if kwargs.get("error"):
                        ui.notify(kwargs["error"] or "Check Numeric Fields", type="negative")
                        return
                    if kwargs.get("shift_length_hours") is None:
                        ui.notify("Lock Shift Length before continuing", type="warning")
                        return
                    if not kwargs.get("shift_starts"):
                        ui.notify("Lock Shift Starts before continuing", type="warning")
                        return
                    if kwargs.get("annual_hours_target") is None:
                        ui.notify("Lock Annual Hours before continuing", type="warning")
                        return
                    kwargs["phase_limit"] = limit
                    kwargs.pop("required_cert_codes", None)
                    from logic.scheduling_sim import run_schedule_simulation

                    res = run_schedule_simulation(**kwargs)
                    if res.get("success"):
                        ui.notify(res.get("message", "Success"), type="positive")
                        req_stepper.next()
                    else:
                        ui.notify(res.get("message", "Failed"), type="negative")
                except Exception as e:
                    ui.notify(f"Error: {e}", type="negative")

            with panel("Requirements"):
                ui.label(
                    "1 · Duty & hours · 2 · Coverage floors · 3 · Optional labor rules. "
                    "Examples in placeholders are not defaults."
                ).classes("text-xs q-mb-sm").style("color:var(--muted)")
                with ui.stepper().props("vertical").classes("w-full bg-transparent shadow-none") as req_stepper:
                    with ui.step("1 · Duty & hours").classes("sim-stepper-step"):
                        # Fixed grid rows — never remove from layout

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

                        # --- Rotation model (one control — squad OR multi-block, not both) ---
                        _ROT_MODEL_OPTIONS = ["Squad preset", "Multi-block on/off"]
                        with (
                            ui.element("div")
                            .classes("w-full grid sim-option-card")
                            .style("grid-template-columns: minmax(200px, 1fr) 2fr; align-items: center; gap: 1.5rem;")
                        ):
                            use_rot_model = given_solve_toggle(ui, "Rotation Model")
                            with ui.element("div"):
                                hint_rotation = ui.label(
                                    "Solve for: multi-block families from annual/length + squad presets"
                                ).classes("sim-free-hint")
                                rot_model_kind = (
                                    ui.select(
                                        _ROT_MODEL_OPTIONS,
                                        value="Multi-block on/off",
                                        label="How officers work on/off days",
                                    )
                                    .classes("w-full")
                                    .props("outlined dense dark")
                                    .tooltip(
                                        "Pick one model. Squad = named department cycles. "
                                        "Multi-block = on/off patterns (mix officers across same-cycle variations)."
                                    )
                                )
                                # Hidden compatibility toggles (form_state / optimizer still read these)
                                use_rotation = ui.checkbox("use_rotation").classes("hidden").style("display:none")
                                use_style = ui.checkbox("use_style").classes("hidden").style("display:none")
                                use_rotation.value = False
                                use_style.value = False

                                squad_box = ui.element("div").classes("w-full q-mt-xs")
                                with squad_box:
                                    rotation = (
                                        ui.select(
                                            _ROTATION_OPTIONS,
                                            value=_placeholder_rot,
                                            label="Squad preset",
                                        )
                                        .classes("w-full")
                                        .props("outlined dense dark")
                                    )
                                multi_box = ui.element("div").classes("w-full q-mt-xs")
                                with multi_box:
                                    rot_style = (
                                        ui.select(_STYLE_OPTIONS, value="Rotating", label="Fixed or rotating")
                                        .classes("w-full")
                                        .props("outlined dense dark")
                                    )
                                    multi_catalog = (
                                        ui.select(
                                            _MULTI_BLOCK_LABELS,
                                            value=_MULTI_BLOCK_LABELS[0],
                                            label="Optional examples (not required)",
                                        )
                                        .classes("w-full")
                                        .props("outlined dense dark")
                                    )
                                    variations = ui.input(
                                        label="On/off patterns (| = different officers)",
                                        value="",
                                        placeholder="same cycle, e.g. 6-2,5-3 | 6-3,5-2",
                                    ).classes("w-full")
                                    ui.label(
                                        "Same cycle length. | splits officer variations "
                                        "(order flips and complements allowed)."
                                    ).classes("text-xs").style("color:var(--muted);margin-top:4px")

                                def _is_squad_model() -> bool:
                                    return str(rot_model_kind.value or "").lower().startswith("squad")

                                def _sync_rotation_model(e=None):
                                    given = bool(use_rot_model.value)
                                    squad = _is_squad_model()
                                    try:
                                        squad_box.set_visibility(squad)
                                        multi_box.set_visibility(not squad)
                                    except Exception:
                                        pass
                                    # Only one duty path active when Given
                                    use_rotation.value = bool(given and squad)
                                    use_style.value = bool(given and not squad)
                                    _set_enabled([rot_model_kind], given)
                                    _set_enabled([rotation], bool(given and squad))
                                    _set_enabled(
                                        [rot_style, multi_catalog, variations],
                                        bool(given and not squad),
                                    )
                                    try:
                                        hint_rotation.set_visibility(not given)
                                    except Exception:
                                        pass

                                def _apply_multi_catalog_example(e=None):
                                    """Explicit Apply only — catalog select does not auto-Given."""
                                    cat = _MULTI_BY_LABEL.get(multi_catalog.value or "")
                                    if not cat:
                                        ui.notify("Pick an example pattern first", type="warning")
                                        return
                                    if cat.get("variations"):
                                        variations.value = cat["variations"]
                                    st = (cat.get("style") or "rotating").lower()
                                    rot_style.value = "Rotating" if st == "rotating" else "Fixed"
                                    use_rot_model.value = True
                                    rot_model_kind.value = "Multi-block on/off"
                                    _sync_rotation_model()
                                    persist_form()
                                    ui.notify("Example applied as Given multi-block", type="positive")

                                ui.button(
                                    "Apply example",
                                    icon="playlist_add",
                                    on_click=_apply_multi_catalog_example,
                                ).classes("btn-ghost q-mt-xs").props("no-caps outline dense").tooltip(
                                    "Copies the selected example into patterns and locks Rotation Model. "
                                    "Does not run automatically on select."
                                )
                                use_rot_model.on_value_change(_sync_rotation_model)
                                rot_model_kind.on_value_change(_sync_rotation_model)
                                _sync_rotation_model()

                        with (
                            ui.element("div")
                            .classes("w-full grid sim-option-card")
                            .style("grid-template-columns: minmax(200px, 1fr) 2fr; align-items: center; gap: 1.5rem;")
                        ):
                            use_officers = given_solve_toggle(ui, "Officer Count")
                            with ui.element("div"):
                                officers = ui.input(
                                    label="Number Of Officers",
                                    value="",
                                    placeholder="e.g. 8",
                                ).classes("w-full")
                                hint_officers = ui.label("Solve for: 4–20 officers searched (all depths)").classes(
                                    "sim-free-hint"
                                )

                        def _on_lock_officers(e=None):
                            _set_enabled([officers], bool(use_officers.value))
                            try:
                                refresh_space_estimate()
                            except Exception:
                                pass

                        use_officers.on_value_change(_on_lock_officers)
                        _set_enabled([officers], False)

                        with (
                            ui.element("div")
                            .classes("w-full grid sim-option-card")
                            .style("grid-template-columns: minmax(200px, 1fr) 2fr; align-items: center; gap: 1.5rem;")
                        ):
                            use_length = given_solve_toggle(ui, "Shift Length")
                            with ui.element("div"):
                                length = ui.input(
                                    label="Hours (0.5 Steps)",
                                    value="",
                                    placeholder="e.g. 8",
                                ).classes("w-full")
                                hint_length = ui.label(
                                    "Solve for: full 8–12.5h half-hour grid (depth = speed only)"
                                ).classes("sim-free-hint")

                        def _on_lock_length(e=None):
                            _set_enabled([length], bool(use_length.value))
                            try:
                                refresh_space_estimate()
                            except Exception:
                                pass

                        use_length.on_value_change(_on_lock_length)
                        _set_enabled([length], False)

                        with (
                            ui.element("div")
                            .classes("w-full grid sim-option-card")
                            .style("grid-template-columns: minmax(200px, 1fr) 2fr; align-items: center; gap: 1.5rem;")
                        ):
                            use_annual = ui.checkbox("Require: Annual Hours Target", value=False)
                            with ui.element("div"):
                                annual = ui.input(
                                    label="Annual Hours Target",
                                    value="",
                                    placeholder="e.g. 2008",
                                ).classes("w-full")
                                annual_var = ui.input(
                                    label="Allowed Variance (± Hours)",
                                    value="",
                                    placeholder="e.g. 20",
                                ).classes("w-full")
                        use_annual.on_value_change(lambda e: _set_enabled([annual, annual_var], bool(e.value)))
                        _set_enabled([annual, annual_var], False)

                        with (
                            ui.element("div")
                            .classes("w-full grid sim-option-card")
                            .style("grid-template-columns: minmax(200px, 1fr) 2fr; align-items: center; gap: 1.5rem;")
                        ):
                            use_starts = given_solve_toggle(ui, "Shift Start Times")
                            with ui.element("div"):
                                starts = ui.input(
                                    label="Starts (Comma-Separated)",
                                    value="",
                                    placeholder="e.g. 06:00, 14:00, 19:00, 22:00",
                                ).classes("w-full")
                                hint_starts = ui.label("Solve for: realistic start packs searched per length").classes(
                                    "sim-free-hint"
                                )
                                ui.html(
                                    '<div style="font-size: 0.8rem; color: var(--sim-muted); margin-top: 4px;">'
                                    "Locked starts are your pack bands. Length × starts should cover the day "
                                    "without structural gaps when 24/7 is required."
                                    "</div>"
                                )

                        def _on_lock_starts(e=None):
                            _set_enabled([starts], bool(use_starts.value))
                            try:
                                refresh_space_estimate()
                            except Exception:
                                pass

                        use_starts.on_value_change(_on_lock_starts)
                        _set_enabled([starts], False)

                        with ui.stepper_navigation():
                            ui.button("Run math bounds", on_click=lambda: _run_phase(1)).props("color=primary")
                    with ui.step("2 · Coverage floors").classes("sim-stepper-step"):
                        with (
                            ui.element("div")
                            .classes("w-full grid sim-option-card")
                            .style("grid-template-columns: minmax(200px, 1fr) 2fr; align-items: center; gap: 1.5rem;")
                        ):
                            use_min_ps = ui.checkbox("Require: Minimum Officers Per Shift", value=False)
                            with ui.element("div"):
                                min_ps = ui.input(
                                    label="Minimum Officers Per Shift",
                                    value="",
                                    placeholder="e.g. 1",
                                ).classes("w-full")

                        def _on_lock_min_ps(e=None):
                            _set_enabled([min_ps], bool(use_min_ps.value))
                            try:
                                refresh_space_estimate()
                            except Exception:
                                pass

                        use_min_ps.on_value_change(_on_lock_min_ps)
                        _set_enabled([min_ps], False)

                        with (
                            ui.element("div")
                            .classes("w-full grid sim-option-card")
                            .style("grid-template-columns: minmax(200px, 1fr) 2fr; align-items: center; gap: 1.5rem;")
                        ):
                            use_247 = ui.checkbox("Require: 24/7 Continuous Minimum", value=False)
                            with ui.element("div"):
                                cov247 = ui.input(
                                    label="Minimum On Duty At All Times",
                                    value="",
                                    placeholder="e.g. 1",
                                ).classes("w-full")
                        use_247.on_value_change(lambda e: _set_enabled([cov247], bool(e.value)))
                        _set_enabled([cov247], False)

                        # Rotation model fields live above (squad OR multi-block — single path)
                        hint_style = hint_rotation  # alias for older bind maps

                        with ui.expansion(
                            "Advanced requirements (bumps, off-day OT, certs, fatigue, FLSA)",
                            icon="tune",
                            value=False,
                        ).classes("sim-adv w-full q-mt-sm"):
                            with (
                                ui.element("div")
                                .classes("w-full grid sim-option-card")
                                .style(
                                    "grid-template-columns: minmax(200px, 1fr) 2fr; align-items: center; gap: 1.5rem;"
                                )
                            ):
                                use_nearby = ui.checkbox("Allow: Nearby Start Bumps (Work Days)", value=False)
                                with ui.element("div"):
                                    nearby_hops = ui.input(
                                        label="Bumps Allowed (± Pack Bands From Home)",
                                        value="",
                                        placeholder="e.g. 1",
                                    ).classes("w-full")
                                    ui.label("Example: home 19:00 with 1 bump → 14:00 or 22:00 on ON days only.").style(
                                        _HINT
                                    )
                            use_nearby.on_value_change(lambda e: _set_enabled([nearby_hops], bool(e.value)))
                            _set_enabled([nearby_hops], False)
                            with (
                                ui.element("div")
                                .classes("w-full grid sim-option-card")
                                .style(
                                    "grid-template-columns: minmax(200px, 1fr) 2fr; align-items: center; gap: 1.5rem;"
                                )
                            ):
                                allow_offday = ui.checkbox(
                                    "Allow Off-Day Coverage (OT Call-In)",
                                    value=False,
                                )
                                with ui.element("div"):
                                    ui.label("Only when checked: multi-block OFF days may fill windows.").style(_HINT)

                            with (
                                ui.element("div")
                                .classes("w-full grid sim-option-card")
                                .style(
                                    "grid-template-columns: minmax(200px, 1fr) 2fr; align-items: center; gap: 1.5rem;"
                                )
                            ):
                                use_certs = ui.checkbox("Require: Cert Codes (Fill Gate)", value=False)
                                with ui.element("div"):
                                    cert_codes = ui.input(
                                        label="Cert Codes (Comma-Separated)",
                                        value="",
                                        placeholder="e.g. FTO, K9, EMT",
                                    ).classes("w-full")
                                    ui.label(
                                        "Only officers holding these codes are eligible when "
                                        "applying home starts / open-shift style fills."
                                    ).style(_HINT)
                            use_certs.on_value_change(lambda e: _set_enabled([cert_codes], bool(e.value)))
                            _set_enabled([cert_codes], False)

                            with ui.stepper_navigation():
                                ui.button("Run coverage", on_click=lambda: _run_phase(2)).props("color=primary")
                                ui.button("Back", on_click=req_stepper.previous).props("flat")
                    with ui.step("3 · Optional labor rules").classes("sim-stepper-step"):
                        with (
                            ui.element("div")
                            .classes("w-full grid sim-option-card")
                            .style("grid-template-columns: minmax(200px, 1fr) 2fr; align-items: center; gap: 1.5rem;")
                        ):
                            use_fatigue = ui.checkbox("Require: Fatigue / Rest Rules", value=False)
                            with ui.element("div"):
                                min_rest = ui.input(
                                    label="Min Rest Hours Between Work Days",
                                    value="",
                                    placeholder="e.g. 8",
                                ).classes("w-full")
                                max_consec = ui.input(
                                    label="Max Consecutive Work Days (0=off)",
                                    value="",
                                    placeholder="e.g. 6",
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
                            use_flsa = ui.checkbox("Require: Avoid FLSA Overtime", value=False)
                            with ui.element("div"):
                                flsa_days = ui.input(
                                    label="FLSA Work Period Days (7–28)",
                                    value="",
                                    placeholder="e.g. 28",
                                ).classes("w-full")
                        use_flsa.on_value_change(lambda e: _set_enabled([flsa_days], bool(e.value)))
                        _set_enabled([flsa_days], False)

                    with ui.stepper_navigation():
                        ui.button("Finalize settings", on_click=req_stepper.next).props("color=primary")
                        ui.button("Back", on_click=req_stepper.previous).props("flat")
            # Windows panel (package) — persist/suggest late-bound
            _win = render_windows_panel(
                state,
                persist_form=persist_form,
                show_suggestions=show_suggestions,
            )
            use_windows = _win["use_windows"]
            win_inputs = _win["win_inputs"]
            _refresh_win_list = _win["refresh_win_list"]

        def load_defaults():
            """Optional: pull current roster/dept numbers into form (user action only)."""
            d = get_simulator_defaults_from_roster()
            if not d.get("success"):
                ui.notify(d.get("message") or "No roster defaults", type="warning")
                return
            if d.get("rotation_type"):
                try:
                    rotation.value = d["rotation_type"]
                    rot_model_kind.value = "Squad preset"
                    use_rot_model.value = True
                    _sync_rotation_model()
                except Exception:
                    pass
            if d.get("num_officers") is not None:
                officers.value = str(d["num_officers"])
                use_officers.value = True
                _set_enabled([officers], True)
            if d.get("shift_length_hours") is not None:
                length.value = str(d["shift_length_hours"])
                use_length.value = True
                _set_enabled([length], True)
            if d.get("annual_hours_target") is not None:
                annual.value = str(int(d["annual_hours_target"]))
                use_annual.value = True
                _set_enabled([annual, annual_var], True)
            st = d.get("shift_starts")
            if st:
                starts.value = ", ".join(st) if isinstance(st, list) else str(st)
                use_starts.value = True
                _set_enabled([starts], True)
            if d.get("min_per_shift") is not None:
                min_ps.value = str(d["min_per_shift"])
                use_min_ps.value = True
                _set_enabled([min_ps], True)
            persist_form()
            ui.notify("Roster values loaded into form (saved)", type="info")

        def save_constraints():
            persist_form()
            ui.notify("Constraints saved for next session", type="positive")

        with ui.element("div").classes("sim-footer-actions"):
            ui.button("Save constraints", on_click=save_constraints).classes("btn-ghost").props("no-caps outline")
            ui.button(
                "Load last saved", on_click=lambda: (restore_form(), ui.notify("Restored last saved", type="info"))
            ).classes("btn-ghost").props("no-caps outline")
            ui.button("Load roster defaults", on_click=load_defaults).classes("btn-ghost").props("no-caps outline")

            def open_load_scenarios():
                rows = list_simulator_scenarios(limit=20)
                with (
                    ui.dialog() as dlg,
                    ui.card()
                    .classes("q-pa-md")
                    .style("min-width:22rem;max-width:36rem;background:#0C1A2E;color:#E8EDF4"),
                ):
                    ui.label("Saved Scenarios").style("font-weight:700;font-size:1.1rem;color:#F8FAFC")
                    if not rows:
                        ui.label("No saved scenarios yet.").style("color:#9AABC4")
                    for row in rows:
                        tags = row.get("tags") or []
                        lab = f"#{row.get('id')} · {row.get('name') or 'Scenario'}" + (
                            f" · {', '.join(tags)}" if tags else ""
                        )

                        def _load(sid=row.get("id")):
                            sc = get_simulator_scenario(int(sid))
                            if not sc:
                                ui.notify("Not found", type="negative")
                                return
                            cfg = sc.get("config") or {}
                            res = sc.get("result")
                            if cfg.get("rotation_variations"):
                                variations.value = " | ".join(cfg["rotation_variations"])
                                rot_model_kind.value = "Multi-block on/off"
                                use_rot_model.value = True
                                _sync_rotation_model()
                            elif cfg.get("rotation_type"):
                                try:
                                    rotation.value = cfg["rotation_type"]
                                    rot_model_kind.value = "Squad preset"
                                    use_rot_model.value = True
                                    _sync_rotation_model()
                                except Exception:
                                    pass
                            if cfg.get("num_officers") is not None:
                                officers.value = str(cfg["num_officers"])
                                use_officers.value = True
                            if cfg.get("shift_length_hours") is not None:
                                length.value = str(cfg["shift_length_hours"])
                            if cfg.get("annual_hours_target") is not None:
                                annual.value = str(int(cfg["annual_hours_target"]))
                            st = cfg.get("shift_starts")
                            if st:
                                starts.value = ", ".join(st) if isinstance(st, list) else str(st)
                            if cfg.get("min_per_shift") is not None:
                                min_ps.value = str(cfg["min_per_shift"])
                            if cfg.get("extra_windows"):
                                state["windows"] = list(cfg["extra_windows"])
                                use_windows.value = True
                                try:
                                    _refresh_win_list()
                                except Exception:
                                    pass
                            if res and res.get("success"):
                                state["result"] = res
                                state["config"] = cfg
                            dlg.close()
                            ui.notify(f"Loaded scenario #{sid}", type="positive")

                        ui.button(lab[:90], on_click=_load).classes("btn-ghost q-mt-xs").props(
                            "no-caps outline dense align=left"
                        ).style("width:100%;text-align:left")
                    ui.button("Close", on_click=dlg.close).classes("btn-ghost q-mt-sm").props("no-caps outline")
                dlg.open()

            ui.button("Load saved scenario", on_click=open_load_scenarios).classes("btn-ghost").props("no-caps outline")
            ui.button(
                "Continue to find best",
                icon="travel_explore",
                on_click=lambda: go_step(2),
            ).classes("btn-primary").props("no-caps unelevated")

        # Live lock progress as checkboxes toggle
        for _lock_cb in (
            use_rot_model,
            use_officers,
            use_length,
            use_annual,
            use_starts,
            use_min_ps,
            use_247,
            use_windows,
            use_nearby,
            use_certs,
            use_fatigue,
            use_flsa,
        ):
            try:
                _lock_cb.on_value_change(lambda e=None: _refresh_lock_progress())
            except Exception:
                pass
        try:
            _refresh_lock_progress()
        except Exception:
            pass

    for _k, _v in (
        ("use_start_date", use_start_date),
        ("sim_start_date", sim_start_date),
        ("use_rot_model", use_rot_model),
        ("rot_model_kind", rot_model_kind),
        ("sync_rotation_model", _sync_rotation_model),
        ("use_rotation", use_rotation),
        ("rotation", rotation),
        ("hint_rotation", hint_rotation),
        ("use_officers", use_officers),
        ("officers", officers),
        ("hint_officers", hint_officers),
        ("use_length", use_length),
        ("length", length),
        ("hint_length", hint_length),
        ("use_annual", use_annual),
        ("annual", annual),
        ("annual_var", annual_var),
        ("use_starts", use_starts),
        ("starts", starts),
        ("hint_starts", hint_starts),
        ("use_min_ps", use_min_ps),
        ("min_ps", min_ps),
        ("use_247", use_247),
        ("cov247", cov247),
        ("use_style", use_style),
        ("hint_style", hint_style),
        ("rot_style", rot_style),
        ("multi_catalog", multi_catalog),
        ("variations", variations),
        ("use_nearby", use_nearby),
        ("nearby_hops", nearby_hops),
        ("allow_offday", allow_offday),
        ("use_certs", use_certs),
        ("cert_codes", cert_codes),
        ("use_fatigue", use_fatigue),
        ("min_rest", min_rest),
        ("max_consec", max_consec),
        ("use_flsa", use_flsa),
        ("flsa_days", flsa_days),
        ("use_windows", use_windows),
        ("win_inputs", win_inputs),
        ("refresh_win_list", _refresh_win_list),
        ("btn_q_min", btn_q_min),
        ("btn_q_will", btn_q_will),
        ("btn_q_plus", btn_q_plus),
        ("req_stepper", req_stepper),
        ("refresh_lock_progress", _refresh_lock_progress),
        ("load_defaults", load_defaults),
        ("save_constraints", save_constraints),
        ("open_load_scenarios", open_load_scenarios),
    ):
        out[_k] = _v
    return out
