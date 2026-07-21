"""Constraint suggestion + lock helpers — extracted from simulator page.py."""

from __future__ import annotations

from typing import Any, Callable, Dict

from nicegui import ui

from logic.constraint_suggest import suggest_constraint


def bind_constraint_suggest(state: dict, c: Dict[str, Any]) -> Dict[str, Callable]:
    """Bind suggestion UI handlers to form widgets."""

    use_rotation = c["use_rotation"]
    rotation = c["rotation"]
    use_officers = c["use_officers"]
    officers = c["officers"]
    use_length = c["use_length"]
    length = c["length"]
    use_annual = c["use_annual"]
    annual = c["annual"]
    annual_var = c["annual_var"]
    use_starts = c["use_starts"]
    starts = c["starts"]
    use_min_ps = c["use_min_ps"]
    min_ps = c["min_ps"]
    use_247 = c["use_247"]
    cov247 = c["cov247"]
    use_style = c["use_style"]
    variations = c["variations"]
    rot_style = c["rot_style"]
    multi_catalog = c["multi_catalog"]
    use_windows = c["use_windows"]
    use_nearby = c["use_nearby"]
    nearby_hops = c["nearby_hops"]
    allow_offday = c["allow_offday"]
    use_flsa = c["use_flsa"]
    flsa_days = c["flsa_days"]
    use_fatigue = c["use_fatigue"]
    min_rest = c["min_rest"]
    max_consec = c["max_consec"]
    use_certs = c["use_certs"]
    cert_codes = c["cert_codes"]
    set_enabled = c["set_enabled"]
    persist_form = c["persist_form"]
    refresh_space_estimate = c["refresh_space_estimate"]
    hint_rotation = c.get("hint_rotation")
    hint_officers = c.get("hint_officers")
    hint_length = c.get("hint_length")
    hint_starts = c.get("hint_starts")
    hint_style = c.get("hint_style")
    win_inputs = c.get("win_inputs") or []
    refresh_win_list = c.get("refresh_win_list") or (lambda: None)

    def constraint_context() -> dict:
        """Currently locked form values for suggestion engine."""
        return {
            "use_rotation": bool(use_rotation.value),
            "rotation": getattr(rotation, "value", None),
            "use_officers": bool(use_officers.value),
            "officers": officers.value,
            "use_length": bool(use_length.value),
            "length": length.value,
            "use_annual": bool(use_annual.value),
            "annual": annual.value,
            "annual_var": annual_var.value,
            "use_starts": bool(use_starts.value),
            "starts": starts.value,
            "use_min_ps": bool(use_min_ps.value),
            "min_ps": min_ps.value,
            "use_247": bool(use_247.value),
            "cov247": cov247.value,
            "use_style": bool(use_style.value),
            "variations": variations.value,
            "rot_style": getattr(rot_style, "value", None),
            "use_windows": bool(use_windows.value),
            "windows": list(state.get("windows") or []),
            "use_nearby": bool(use_nearby.value),
            "nearby_hops": nearby_hops.value,
            "allow_offday": bool(allow_offday.value),
            "use_flsa": bool(use_flsa.value),
            "flsa_days": flsa_days.value,
            "use_fatigue": bool(use_fatigue.value),
            "min_rest": min_rest.value,
            "max_consec": max_consec.value,
            "use_certs": bool(use_certs.value),
            "required_certs": (cert_codes.value if use_certs.value else ""),
        }

    def apply_suggest_values(values: dict) -> None:
        if not values:
            return

        def _has_value(*keys: str) -> bool:
            # A lock may only be restored as locked if every value it needs
            # actually came back with it — otherwise the form reloads into a
            # stuck "locked but empty" state that blocks Find Best with a
            # silent "Fix numbers" error until the user notices and manually
            # unlocks it.
            for k in keys:
                v = values.get(k)
                if v is None or (isinstance(v, str) and not v.strip()):
                    return False
            return True

        state["suppress_suggest"] = True
        try:
            if values.get("rotation"):
                try:
                    rotation.value = values["rotation"]
                except Exception:
                    pass
            if "use_rotation" in values:
                use_rotation.value = bool(values["use_rotation"]) and _has_value("rotation")
                set_enabled([rotation], bool(use_rotation.value))
            if values.get("officers") is not None:
                officers.value = str(values["officers"])
            if "use_officers" in values:
                use_officers.value = bool(values["use_officers"]) and _has_value("officers")
                set_enabled([officers], bool(use_officers.value))
            if values.get("length") is not None:
                length.value = str(values["length"])
            if "use_length" in values:
                use_length.value = bool(values["use_length"]) and _has_value("length")
                set_enabled([length], bool(use_length.value))
            if values.get("annual") is not None:
                annual.value = str(values["annual"])
            if values.get("annual_var") is not None:
                annual_var.value = str(values["annual_var"])
            if "use_annual" in values:
                use_annual.value = bool(values["use_annual"]) and _has_value("annual")
                set_enabled([annual, annual_var], bool(use_annual.value))
            if values.get("starts") is not None:
                starts.value = str(values["starts"])
            if "use_starts" in values:
                use_starts.value = bool(values["use_starts"]) and _has_value("starts")
                set_enabled([starts], bool(use_starts.value))
            if values.get("min_ps") is not None:
                min_ps.value = str(values["min_ps"])
            if "use_min_ps" in values:
                use_min_ps.value = bool(values["use_min_ps"]) and _has_value("min_ps")
                set_enabled([min_ps], bool(use_min_ps.value))
            if values.get("cov247") is not None:
                cov247.value = str(values["cov247"])
            if "use_247" in values:
                use_247.value = bool(values["use_247"]) and _has_value("cov247")
                set_enabled([cov247], bool(use_247.value))
            if values.get("variations") is not None:
                variations.value = str(values["variations"])
            if values.get("rot_style"):
                try:
                    rot_style.value = values["rot_style"]
                except Exception:
                    pass
            if "use_style" in values:
                use_style.value = bool(values["use_style"]) and _has_value("variations")
                set_enabled([rot_style, multi_catalog, variations], bool(use_style.value))
            if "use_windows" in values:
                use_windows.value = bool(values["use_windows"])
            if "windows" in values:
                state["windows"] = list(values.get("windows") or [])
                try:
                    refresh_win_list()
                except Exception:
                    pass
            if values.get("nearby_hops") is not None:
                nearby_hops.value = str(values["nearby_hops"])
            if "use_nearby" in values:
                use_nearby.value = bool(values["use_nearby"]) and _has_value("nearby_hops")
                set_enabled([nearby_hops], bool(use_nearby.value))
            if "allow_offday" in values:
                allow_offday.value = bool(values["allow_offday"])
            if values.get("flsa_days") is not None:
                flsa_days.value = str(values["flsa_days"])
            if "use_flsa" in values:
                use_flsa.value = bool(values["use_flsa"])
                set_enabled([flsa_days], bool(use_flsa.value))

            try:
                refresh_space_estimate()
            except Exception:
                pass
            persist_form()
        finally:
            state["suppress_suggest"] = False

    def show_constraint_suggestions(field: str, *, force: bool = False) -> None:
        if state.get("restoring_form") or state.get("suppress_suggest"):
            return
        ctx = constraint_context()
        # Only guide when other constraints already locked (or forced Help)
        field_flags = {
            "rotation": "use_rotation",
            "officers": "use_officers",
            "length": "use_length",
            "annual": "use_annual",
            "starts": "use_starts",
            "min_ps": "use_min_ps",
            "coverage_247": "use_247",
            "variations": "use_style",
            "style": "use_style",
            "windows": "use_windows",
            "nearby": "use_nearby",
            "flsa": "use_flsa",
            "offday": "allow_offday",
        }
        self_flag = field_flags.get((field or "").lower())
        other_flags = (
            "use_rotation",
            "use_officers",
            "use_length",
            "use_annual",
            "use_starts",
            "use_min_ps",
            "use_247",
            "use_style",
            "use_windows",
            "use_nearby",
            "use_flsa",
            "allow_offday",
        )
        other_locked = any(bool(ctx.get(k)) for k in other_flags if k != self_flag)
        if not force and not other_locked:
            return
        # Suggest from other locks; temporarily clear self so engine ignores empty new field
        ctx_for = dict(ctx)
        if self_flag:
            ctx_for[self_flag] = False
        sugg = suggest_constraint(field, ctx_for)
        opts = list(sugg.get("options") or [])
        if not opts and not force:
            return

        with (
            ui.dialog() as dlg,
            ui.card()
            .classes("q-pa-md")
            .style(
                "min-width:22rem;max-width:34rem;background:#0C1A2E;color:#E8EDF4;"
                "border:1px solid rgba(91,141,239,0.45)"
            ),
        ):
            ui.label(sugg.get("title") or "Suggestions").style("font-weight:700;font-size:1.1rem;color:#F8FAFC")
            ui.label(sugg.get("explanation") or "").style(
                "color:#9AABC4;font-size:0.88rem;margin:6px 0 10px;white-space:pre-wrap"
            )
            ui.label(sugg.get("custom_hint") or "").style("color:#86efac;font-size:0.82rem;margin-bottom:10px")
            for opt in opts:
                lab = opt.get("label") or "Option"
                if opt.get("recommended"):
                    lab = "★ " + lab
                why = opt.get("why") or ""
                with ui.row().classes("w-full items-start gap-2 q-mb-sm flex-wrap"):
                    with ui.column().classes("flex-1"):
                        ui.label(lab).style("color:#E8EDF4;font-weight:600;font-size:0.92rem")
                        if why:
                            ui.label(why).style("color:#9AABC4;font-size:0.8rem;white-space:pre-wrap")

                    def _pick(vals=opt.get("values") or {}):
                        apply_suggest_values(vals)
                        dlg.close()
                        ui.notify("Suggestion applied — edit freely anytime", type="positive")

                    ui.button("Use", on_click=_pick).classes("btn-primary").props("dense no-caps unelevated")
            with ui.row().classes("gap-2 q-mt-sm flex-wrap"):
                ui.button(
                    "Enter My Own Value",
                    on_click=dlg.close,
                ).classes("btn-ghost").props("no-caps outline")
                ui.button(
                    "Why These?",
                    on_click=lambda: ui.notify(
                        sugg.get("explanation") or "Based on locked constraints",
                        type="info",
                        multi_line=True,
                    ),
                ).classes("btn-ghost").props("no-caps outline")
        dlg.open()

    def on_lock_with_suggest(field: str, enable_fn, widget_lock_flag):
        """enable_fn enables inputs; suggest when user turns lock ON."""

        def _handler(e=None):
            on = bool(widget_lock_flag.value)
            enable_fn(on)
            if on and not state.get("restoring_form") and not state.get("suppress_suggest"):
                # Defer slightly so lock flag is in context
                try:
                    show_constraint_suggestions(field)
                except Exception:
                    pass
            try:
                refresh_space_estimate()
            except Exception:
                pass
            try:
                persist_form()
            except Exception:
                pass

        return _handler

    # Re-bind locks so enabling a constraint offers context-aware suggestions
    def _hint(h, show: bool):
        if h is None:
            return
        try:
            h.set_visibility(show)
        except Exception:
            pass

    def en_rot(on: bool):
        set_enabled([rotation], on)
        _hint(hint_rotation, not on)

    def en_off(on: bool):
        set_enabled([officers], on)
        _hint(hint_officers, not on)

    def en_len(on: bool):
        set_enabled([length], on)
        _hint(hint_length, not on)

    def en_ann(on: bool):
        set_enabled([annual, annual_var], on)

    def en_st(on: bool):
        set_enabled([starts], on)
        _hint(hint_starts, not on)

    def en_mp(on: bool):
        set_enabled([min_ps], on)

    def en_247(on: bool):
        set_enabled([cov247], on)

    def en_style(on: bool):
        set_enabled([rot_style, multi_catalog, variations], on)
        _hint(hint_style, not on)

    def en_near(on: bool):
        set_enabled([nearby_hops], on)

    def en_flsa(on: bool):
        set_enabled([flsa_days], on)

    use_rotation.on_value_change(on_lock_with_suggest("rotation", en_rot, use_rotation))
    use_officers.on_value_change(on_lock_with_suggest("officers", en_off, use_officers))
    use_length.on_value_change(on_lock_with_suggest("length", en_len, use_length))
    use_annual.on_value_change(on_lock_with_suggest("annual", en_ann, use_annual))
    use_starts.on_value_change(on_lock_with_suggest("starts", en_st, use_starts))
    use_min_ps.on_value_change(on_lock_with_suggest("min_ps", en_mp, use_min_ps))
    use_247.on_value_change(on_lock_with_suggest("coverage_247", en_247, use_247))
    use_style.on_value_change(on_lock_with_suggest("variations", en_style, use_style))
    use_nearby.on_value_change(on_lock_with_suggest("nearby", en_near, use_nearby))
    use_flsa.on_value_change(on_lock_with_suggest("flsa", en_flsa, use_flsa))

    def on_windows_lock(e=None):
        set_enabled(win_inputs, bool(use_windows.value))
        if use_windows.value and not state.get("restoring_form") and not state.get("suppress_suggest"):
            try:
                show_constraint_suggestions("windows")
            except Exception:
                pass
        try:
            persist_form()
        except Exception:
            pass

    use_windows.on_value_change(on_windows_lock)

    def on_offday_lock(e=None):
        if allow_offday.value and not state.get("restoring_form") and not state.get("suppress_suggest"):
            try:
                show_constraint_suggestions("offday")
            except Exception:
                pass
        try:
            persist_form()
        except Exception:
            pass

    allow_offday.on_value_change(on_offday_lock)
    use_fatigue.on_value_change(
        lambda e: (
            set_enabled([min_rest, max_consec], bool(use_fatigue.value)),
            (
                show_constraint_suggestions("nearby")
                if use_fatigue.value and not state.get("restoring_form") and not state.get("suppress_suggest")
                else None
            ),
        )
    )

    # Suggest when focusing an empty locked field (sim UX residual)
    def focus_suggest(field: str, widget):
        def _h(e=None):
            try:
                val = (getattr(widget, "value", None) or "").strip()
            except Exception:
                val = ""
            if val:
                return
            if state.get("restoring_form") or state.get("suppress_suggest"):
                return
            try:
                show_constraint_suggestions(field)
            except Exception:
                pass

        return _h

    try:
        officers.on("focus", focus_suggest("officers", officers))
        length.on("focus", focus_suggest("length", length))
        annual.on("focus", focus_suggest("annual", annual))
        starts.on("focus", focus_suggest("starts", starts))
        cov247.on("focus", focus_suggest("coverage_247", cov247))
        variations.on("focus", focus_suggest("variations", variations))
        nearby_hops.on("focus", focus_suggest("nearby", nearby_hops))
    except Exception:
        pass

    def suggest_next_unlocked():
        """Popup for the first unlocked common field given current locks."""
        order = [
            ("length", use_length),
            ("annual", use_annual),
            ("starts", use_starts),
            ("officers", use_officers),
            ("variations", use_style),
            ("coverage_247", use_247),
            ("windows", use_windows),
            ("nearby", use_nearby),
        ]
        for name, lock in order:
            if not lock.value:
                show_constraint_suggestions(name, force=True)
                return
        show_constraint_suggestions("officers", force=True)

    return {
        "constraint_context": constraint_context,
        "apply_suggest_values": apply_suggest_values,
        "show_constraint_suggestions": show_constraint_suggestions,
        "on_lock_with_suggest": on_lock_with_suggest,
        "en_rot": en_rot,
        "en_off": en_off,
        "en_len": en_len,
        "en_ann": en_ann,
        "en_st": en_st,
        "en_mp": en_mp,
        "en_247": en_247,
        "en_style": en_style,
        "en_near": en_near,
        "en_flsa": en_flsa,
        "on_windows_lock": on_windows_lock,
        "on_offday_lock": on_offday_lock,
        "focus_suggest": focus_suggest,
        "suggest_next_unlocked": suggest_next_unlocked,
    }
