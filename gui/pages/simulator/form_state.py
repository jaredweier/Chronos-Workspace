"""Form snapshot / persist / restore — extracted from simulator page.py."""

from __future__ import annotations

from typing import Any, Callable, Dict

from nicegui import ui

from logic.optimizer_features import load_last_simulator_constraints, save_form_snapshot
from logic.rotation_config import normalize_rotation_preset_name


def bind_form_state(state: dict, c: Dict[str, Any]) -> Dict[str, Callable]:
    """Bind form payload/persist/restore handlers to widget refs."""

    officers = c["officers"]
    length = c["length"]
    annual = c["annual"]
    annual_var = c["annual_var"]
    starts = c["starts"]
    min_ps = c["min_ps"]
    variations = c["variations"]
    use_officers = c["use_officers"]
    use_length = c["use_length"]
    use_starts = c["use_starts"]
    use_247 = c["use_247"]
    use_windows = c["use_windows"]
    use_min_ps = c["use_min_ps"]
    use_rotation = c["use_rotation"]
    use_style = c["use_style"]
    use_rot_model = c.get("use_rot_model")
    rot_model_kind = c.get("rot_model_kind")
    sync_rotation_model = c.get("sync_rotation_model")
    use_annual = c["use_annual"]
    use_flsa = c["use_flsa"]
    use_nearby = c["use_nearby"]
    nearby_hops = c["nearby_hops"]
    allow_offday = c["allow_offday"]
    use_certs = c["use_certs"]
    cert_codes = c["cert_codes"]
    use_fatigue = c["use_fatigue"]
    min_rest = c["min_rest"]
    max_consec = c["max_consec"]
    cov247 = c["cov247"]
    flsa_days = c["flsa_days"]
    rot_style = c["rot_style"]
    multi_catalog = c["multi_catalog"]
    rotation = c["rotation"]
    man_days = c.get("man_days")  # optional; manual editor may not export widget
    refresh_win_list = c["refresh_win_list"]
    set_enabled = c["set_enabled"]
    refresh_lock_strip = c["refresh_lock_strip"]
    refresh_space_estimate = c["refresh_space_estimate"]

    def form_payload() -> dict:
        return {
            "officers": officers.value,
            "length": length.value,
            "annual": annual.value,
            "annual_var": annual_var.value,
            "starts": starts.value,
            "min_ps": min_ps.value,
            "variations": variations.value,
            "use_officers": bool(use_officers.value),
            "use_length": bool(use_length.value),
            "use_starts": bool(use_starts.value),
            "use_247": bool(use_247.value),
            "use_windows": bool(use_windows.value),
            "use_min_ps": bool(use_min_ps.value),
            "use_rotation": bool(use_rotation.value),
            "use_style": bool(use_style.value),
            "use_rot_model": bool(use_rot_model.value)
            if use_rot_model is not None
            else bool(use_rotation.value or use_style.value),
            "rot_model_kind": getattr(rot_model_kind, "value", None)
            if rot_model_kind is not None
            else ("Squad preset" if use_rotation.value else "Multi-block on/off"),
            "use_annual": bool(use_annual.value),
            "use_flsa": bool(use_flsa.value),
            "use_nearby": bool(use_nearby.value),
            "nearby_hops": nearby_hops.value,
            "allow_offday": bool(allow_offday.value),
            "use_certs": bool(use_certs.value),
            "required_certs": cert_codes.value,
            "use_fatigue": bool(use_fatigue.value),
            "min_rest": min_rest.value,
            "max_consec": max_consec.value,
            "cov247": cov247.value,
            "flsa_days": flsa_days.value,
            "rot_style": getattr(rot_style, "value", None),
            "multi_catalog": getattr(multi_catalog, "value", None),
            "windows": list(state.get("windows") or []),
            "rotation": getattr(rotation, "value", None),
            "manual_days": (man_days.value if man_days is not None else state.get("manual_days")),
            "manual_grid": state.get("manual_grid"),
        }

    def apply_form_payload(data: dict) -> None:
        if not data:
            return
        state["restoring_form"] = True
        try:
            apply_form_payload_inner(data)
        finally:
            state["restoring_form"] = False

    def apply_form_payload_inner(data: dict) -> None:
        def _val_ok(key: str, widget) -> bool:
            # Same guard as _apply_suggest_values (Bug B): a Given/Require
            # flag may only restore as ON if its paired value survives the
            # round-trip — otherwise the form reloads locked-but-empty and
            # silently blocks Find Best with "Fix numbers". This restore
            # path (page load) previously had no guard; found live
            # 2026-07-17 after a save-during-restore race emptied cov247.
            v = data.get(key)
            if v is None:
                v = getattr(widget, "value", None)
            return v is not None and str(v).strip() != ""

        if data.get("officers") is not None:
            officers.value = str(data["officers"])
        if data.get("length") is not None:
            length.value = str(data["length"])
        if data.get("annual") is not None:
            annual.value = str(data["annual"])
        if data.get("annual_var") is not None:
            annual_var.value = str(data["annual_var"])
        if data.get("starts") is not None:
            starts.value = str(data["starts"])
        if data.get("min_ps") is not None:
            min_ps.value = str(data["min_ps"])
        if data.get("variations") is not None:
            variations.value = str(data["variations"])
        if data.get("use_officers") is not None:
            use_officers.value = bool(data["use_officers"]) and _val_ok("officers", officers)
            set_enabled([officers], bool(use_officers.value))
        if data.get("use_length") is not None:
            use_length.value = bool(data["use_length"]) and _val_ok("length", length)
            set_enabled([length], bool(use_length.value))
        if data.get("use_starts") is not None:
            use_starts.value = bool(data["use_starts"]) and _val_ok("starts", starts)
            set_enabled([starts], bool(use_starts.value))
        if data.get("use_247") is not None:
            use_247.value = bool(data["use_247"]) and _val_ok("cov247", cov247)
            set_enabled([cov247], bool(use_247.value))
        if data.get("use_windows") is not None:
            use_windows.value = bool(data["use_windows"])
        if data.get("use_min_ps") is not None:
            use_min_ps.value = bool(data["use_min_ps"]) and _val_ok("min_ps", min_ps)
            set_enabled([min_ps], bool(use_min_ps.value))
        # Prefer unified rotation model; fall back to legacy dual flags
        if rot_model_kind is not None and data.get("rot_model_kind"):
            try:
                rot_model_kind.value = data["rot_model_kind"]
            except Exception:
                pass
        elif data.get("use_style") and _val_ok("variations", variations):
            if rot_model_kind is not None:
                try:
                    rot_model_kind.value = "Multi-block on/off"
                except Exception:
                    pass
        elif data.get("use_rotation") and _val_ok("rotation", rotation):
            if rot_model_kind is not None:
                try:
                    rot_model_kind.value = "Squad preset"
                except Exception:
                    pass
        if use_rot_model is not None:
            given = False
            if data.get("use_rot_model") is not None:
                given = bool(data["use_rot_model"])
            else:
                given = bool(data.get("use_rotation") or data.get("use_style"))
            # Require matching value for the chosen model
            kind = str(getattr(rot_model_kind, "value", "") or "")
            if kind.lower().startswith("squad"):
                given = given and _val_ok("rotation", rotation)
            else:
                given = given and _val_ok("variations", variations)
            use_rot_model.value = given
            if callable(sync_rotation_model):
                sync_rotation_model()
            else:
                use_rotation.value = bool(given and kind.lower().startswith("squad"))
                use_style.value = bool(given and not kind.lower().startswith("squad"))
        else:
            if data.get("use_rotation") is not None:
                use_rotation.value = bool(data["use_rotation"]) and _val_ok("rotation", rotation)
                set_enabled([rotation], bool(use_rotation.value))
            if data.get("use_style") is not None:
                use_style.value = bool(data["use_style"]) and _val_ok("variations", variations)
                set_enabled([rot_style, multi_catalog, variations], bool(use_style.value))
        if data.get("use_annual") is not None:
            use_annual.value = bool(data["use_annual"]) and _val_ok("annual", annual)
            set_enabled([annual, annual_var], bool(use_annual.value))
        if data.get("use_flsa") is not None:
            use_flsa.value = bool(data["use_flsa"])
            set_enabled([flsa_days], bool(use_flsa.value))
        if data.get("use_nearby") is not None:
            use_nearby.value = bool(data["use_nearby"]) and _val_ok("nearby_hops", nearby_hops)
            set_enabled([nearby_hops], bool(use_nearby.value))
        if data.get("nearby_hops") is not None:
            nearby_hops.value = str(data["nearby_hops"])
        if data.get("allow_offday") is not None:
            allow_offday.value = bool(data["allow_offday"])
        # Fatigue / rest — saved in payload but previously not restored (wiring hole)
        if data.get("min_rest") is not None:
            min_rest.value = str(data["min_rest"])
        if data.get("max_consec") is not None:
            max_consec.value = str(data["max_consec"])
        if data.get("use_fatigue") is not None:
            use_fatigue.value = bool(data["use_fatigue"]) and (
                _val_ok("min_rest", min_rest) or _val_ok("max_consec", max_consec)
            )
            set_enabled([min_rest, max_consec], bool(use_fatigue.value))
        if data.get("required_certs") is not None:
            rc = data["required_certs"]
            cert_codes.value = ", ".join(str(x) for x in rc) if isinstance(rc, list) else str(rc)
        if data.get("use_certs") is not None:
            use_certs.value = bool(data["use_certs"]) and _val_ok("required_certs", cert_codes)
            set_enabled([cert_codes], bool(use_certs.value))
        if data.get("cov247") is not None:
            cov247.value = str(data["cov247"])
        if data.get("flsa_days") is not None:
            flsa_days.value = str(data["flsa_days"])
        if data.get("rot_style"):
            try:
                rot_style.value = data["rot_style"]
            except Exception:
                pass
        if data.get("multi_catalog"):
            try:
                multi_catalog.value = data["multi_catalog"]
            except Exception:
                pass
        if data.get("windows") is not None:
            state["windows"] = list(data["windows"] or [])
            try:
                refresh_win_list()
            except Exception:
                pass
        if data.get("rotation"):
            try:
                rotation.value = normalize_rotation_preset_name(data["rotation"])
            except Exception:
                pass
        if data.get("manual_grid") is not None:
            state["manual_grid"] = data["manual_grid"]
        if data.get("manual_days") is not None:
            state["manual_days"] = data["manual_days"]
            if man_days is not None:
                try:
                    man_days.value = str(data["manual_days"])
                except Exception:
                    pass

    def push_undo():
        try:
            stack = list(state.get("form_undo") or [])
            stack.append(form_payload())
            state["form_undo"] = stack[-15:]
        except Exception:
            pass

    def undo_form():
        stack = list(state.get("form_undo") or [])
        if not stack:
            ui.notify("Nothing to undo", type="info")
            return
        data = stack.pop()
        state["form_undo"] = stack
        apply_form_payload(data)
        ui.notify("Form undone", type="info")

    def persist_form():
        # Value-change handlers fire while a restore is mid-flight; saving
        # then snapshots a half-restored form (e.g. use_247 on, cov247 not
        # yet set) and corrupts the stored constraints for the next load.
        if state.get("restoring_form"):
            return
        push_undo()
        data = form_payload()
        save_form_snapshot(data)
        try:
            from nicegui import app as _app

            store = getattr(_app.storage, "user", None)
            if store is not None:
                store["sim_form"] = data
        except Exception:
            pass

    def restore_form():
        data = None
        try:
            from nicegui import app as _app

            store = getattr(_app.storage, "user", None)
            if store:
                data = store.get("sim_form")
        except Exception:
            data = None
        if not data:
            data = load_last_simulator_constraints()
        if data:
            apply_form_payload(data)
        try:
            refresh_lock_strip()
        except Exception:
            pass
        try:
            refresh_space_estimate()
        except Exception:
            pass

    return {
        "form_payload": form_payload,
        "apply_form_payload": apply_form_payload,
        "push_undo": push_undo,
        "undo_form": undo_form,
        "persist_form": persist_form,
        "restore_form": restore_form,
    }
