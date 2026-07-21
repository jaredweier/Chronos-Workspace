"""run_sim + publish/secondary tools — extracted from simulator page.py."""

from __future__ import annotations

from typing import Any, Callable, Dict

from nicegui import run, ui

from logic import (
    create_shift_bid_from_simulation,
    export_simulation_csv,
    format_optimized_plan_view,
    get_last_optimized_plan,
    implement_optimized_plan,
    preview_implement_plan,
    recommend_implement_dates,
    save_last_optimized_plan,
    save_simulator_scenario,
)
from logic.optimizer_features import (
    diff_options,
    export_form_config_json,
    export_ranked_options_csv,
    export_search_audit_json,
    export_share_eml,
    fairness_report,
    fairness_report_with_roster,
    format_share_message,
    load_form_snapshot,
    option_seed_from_row,
    pin_option,
    save_scenario_slot,
)
from logic.plan_explain import explain_staffing_result
from logic.scheduling_sim import run_schedule_simulation
from logic.sim_product_pack import (
    apply_sim_winner_to_draft_month,
    fairness_report_full,
    import_live_department_constraints,
    plain_english_staffing_explain,
    sensitivity_headcount,
    sensitivity_relax_night_min,
    try_cpsat_when_small,
)
from logic.staffing_insights import detect_constraint_conflicts, export_staffing_memo


def can_reuse_find_best_for_generate(state: dict) -> bool:
    """C1: Find Best (or ranked adopt) already produced a plan — Generate reuses it.

    True when state has a successful sim result and either a selected ranked row
    or an optimizer result (opt_result). Skips re-lock lecture + re-sim.
    """
    existing = state.get("result")
    if not isinstance(existing, dict) or not existing.get("success"):
        return False
    if state.get("selected_row") is not None:
        return True
    opt = state.get("opt_result")
    if not isinstance(opt, dict):
        return False
    return bool(opt.get("best") or opt.get("ranked") or opt.get("success"))


def bind_side_actions(state: dict, c: Dict[str, Any]) -> Dict[str, Callable]:
    """Bind generate/publish/export secondary handlers."""

    baseline_kwargs = c["baseline_kwargs"]
    current_config = c["current_config"]
    precheck_conflicts = c["precheck_conflicts"]
    persist_form = c["persist_form"]
    paint_kpis = c["paint_kpis"]
    apply_ranked_option = c["apply_ranked_option"]
    form_payload = c["form_payload"]
    apply_form_payload = c["apply_form_payload"]
    refresh_space_estimate = c["refresh_space_estimate"]
    human_metrics = c["human_metrics"]
    set_summary = c["set_summary"]
    set_why = c["set_why"]
    set_plan = c["set_plan"]
    set_action_log = c["set_action_log"]
    impl_date = c["impl_date"]
    apply_officers = c["apply_officers"]
    force_regen = c["force_regen"]
    save_defaults = c["save_defaults"]
    btn_impl = c["btn_impl"]
    session = c["session"]
    officers = c["officers"]
    use_officers = c["use_officers"]
    length = c["length"]
    use_length = c["use_length"]
    starts = c["starts"]
    use_starts = c["use_starts"]
    min_ps = c["min_ps"]
    use_min_ps = c["use_min_ps"]
    variations = c["variations"]
    use_style = c["use_style"]
    go_step = c["go_step"]
    rotation = c["rotation"]
    use_windows = c["use_windows"]
    constraint_context = c["constraint_context"]

    def run_sim():
        """Generate schedule. Seamless after Find Best: use loaded plan (no re-lock)."""
        # C1: Find Best / ranked apply already built a plan — open it without lock lecture
        if can_reuse_find_best_for_generate(state):
            existing = state["result"]
            cfg = state.get("config") or current_config()
            try:
                view = format_optimized_plan_view(existing, cfg)
                set_plan(view.get("text") or existing.get("message") or "")
            except Exception:
                set_plan(existing.get("message") or "Plan loaded from Find Best.")
            metrics = existing.get("metrics") or {}
            row = state.get("selected_row") or (state.get("opt_result") or {}).get("best") or {}
            lines = [
                existing.get("message") or "Plan Ready (From Find Best)",
                "No re-lock needed — option already adopted as Given.",
                "",
            ] + human_metrics(metrics)
            set_summary("\n".join(lines))
            try:
                paint_kpis(
                    hard_ok=metrics.get("hard_constraints_ok") if metrics else row.get("hard_constraints_ok"),
                    officers_n=row.get("num_officers") or metrics.get("min_officers_required"),
                    layouts=(state.get("opt_result") or {}).get("scenarios_evaluated"),
                    annual_avg=metrics.get("avg_annual_hours"),
                    window_fails=metrics.get("extra_window_failures"),
                    rest_fails=metrics.get("rest_failures"),
                    mode_text="From Find Best",
                    search_truncated=(state.get("opt_result") or {}).get("search_truncated"),
                    search_exhaustive=(state.get("opt_result") or {}).get("search_exhaustive"),
                )
            except Exception:
                pass
            try:
                go_step(2)
            except Exception:
                pass
            ui.notify("Using Find Best plan — Generate did not re-lock", type="positive")
            return

        base = baseline_kwargs()
        if base.get("error"):
            ui.notify(base["error"] or "Check Numeric Fields", type="negative")
            return
        if base.get("shift_length_hours") is None:
            ui.notify("Lock Shift Length before Generate (or run Find Best first)", type="warning")
            return
        if not base.get("shift_starts"):
            ui.notify("Lock Shift Starts before Generate (or run Find Best first)", type="warning")
            return
        # Annual optional soft for Generate when Given elsewhere; use 0 only if free
        # (not a product default — empty band means no annual hard filter)
        _ann = base.get("annual_hours_target")
        if _ann is None:
            row = state.get("selected_row") or {}
            if row.get("annual_hours_target") is not None:
                _ann = float(row["annual_hours_target"])
            else:
                _ann = 0.0
        if not precheck_conflicts(force_dialog=False):
            ui.notify("Fix blocking constraint conflicts first", type="negative")
            return
        persist_form()
        result = run_schedule_simulation(
            rotation_type=base["rotation_type"],
            num_officers=base["num_officers"],
            shift_length_hours=float(base["shift_length_hours"]),
            annual_hours_target=float(_ann),
            shift_starts=list(base["shift_starts"]),
            min_per_shift=base["min_per_shift"],
            simulation_days=56,
            annual_hours_variance=float(base.get("annual_hours_variance") or 0),
            annual_hours_hard=bool(base.get("annual_hours_hard") and _ann),
            coverage_247=base["coverage_247"],
            avoid_flsa_overtime=base["avoid_flsa_overtime"],
            flsa_work_period_days=base["flsa_work_period_days"],
            rotation_style=base["rotation_style"],
            rotation_variations=base["rotation_variations"],
            auto_min_officers=base["auto_min_officers"],
            apply_department_rules=False,
            use_extra_windows=base["use_extra_windows"],
            extra_windows=base["extra_windows"],
            stagger_phases=True,
            nearby_start_hops=int(base.get("nearby_start_hops") or 0),
            allow_offday_coverage=bool(base.get("allow_offday_coverage")),
            min_rest_hours=float(base.get("min_rest_hours") or 0),
            max_consecutive_work_days=int(base.get("max_consecutive_work_days") or 0),
        )
        state["result"] = result
        state["config"] = current_config()
        if not result.get("success"):
            set_summary(result.get("message", "Failed"))
            ui.notify(result.get("message", "Failed"), type="negative")
            return
        metrics = result.get("metrics") or {}
        hard = bool(state.get("hard_mode", True))
        lines = [result.get("message") or "Simulation Complete", ""] + human_metrics(metrics)
        # Always explain plan (UX residual)
        try:
            from logic.plan_explain import explain_staffing_result

            lines.append("")
            lines.extend(
                explain_staffing_result(
                    {
                        "success": True,
                        "best": {
                            "metrics": metrics,
                            "shift_starts": base.get("shift_starts"),
                            "num_officers": base.get("num_officers"),
                            "shift_length_hours": base.get("shift_length_hours"),
                            "hard_constraints_ok": metrics.get("hard_constraints_ok"),
                        },
                        "message": result.get("message"),
                    }
                )[:8]
            )
        except Exception:
            pass
        set_summary("\n".join(lines))
        if hard and not metrics.get("hard_constraints_ok", True):
            try:
                show_no_match = c.get("show_no_match_dialog")
                if callable(show_no_match):
                    show_no_match(1, 1)
            except Exception:
                pass
        uid = (session.current_user() or {}).get("id")
        save_last_optimized_plan(result, state["config"], user_id=uid)
        view = format_optimized_plan_view(result, state["config"])
        set_plan(view.get("text") or "")
        single = [
            {
                "rank": 1,
                "summary": (
                    f"{base['rotation_type']} · "
                    f"{metrics.get('min_officers_required', base['num_officers'])} Officers · "
                    f"Min {base['min_per_shift']} Per Shift"
                ),
                "rotation_type": base["rotation_type"],
                "num_officers": int(metrics.get("min_officers_required") or base["num_officers"] or 0),
                "min_per_shift": base["min_per_shift"],
                "shift_length_hours": base["shift_length_hours"],
                "annual_hours_target": _ann,
                "shift_starts": base["shift_starts"],
                "rotation_variations": base["rotation_variations"],
                "rotation_style": base["rotation_style"],
                "hard_constraints_ok": metrics.get("hard_constraints_ok"),
            }
        ]
        try:
            render_ranked = c.get("render_ranked")
            if callable(render_ranked):
                render_ranked(single, selected=1)
        except Exception:
            pass
        try:
            paint_kpis(
                hard_ok=metrics.get("hard_constraints_ok"),
                officers_n=metrics.get("min_officers_required") or base.get("num_officers"),
                layouts=1,
                annual_avg=metrics.get("avg_annual_hours"),
                window_fails=metrics.get("extra_window_failures"),
                mode_text="Generate schedule",
            )
        except Exception:
            pass
        ui.notify("Simulation complete", type="positive")

    async def implement_plan():
        res = state.get("result")
        cfg = state.get("config")
        if not res or not res.get("success"):
            stored = get_last_optimized_plan()
            if stored:
                res, cfg = stored.get("result"), stored.get("config")
        if not res or not res.get("success"):
            ui.notify("No Successful Plan To Publish", type="warning")
            set_action_log("Publish Failed: No Plan In Memory.", ok=False)
            return
        start_date = (impl_date.value or "").strip()
        uid = (session.current_user() or {}).get("id")
        plan_cfg = cfg or current_config()
        plan_res = res
        btn_impl.props("disable loading")
        set_action_log("Publishing In Background…", ok=None)
        try:
            r = await run.io_bound(
                implement_optimized_plan,
                start_date=start_date,
                result=plan_res,
                config=plan_cfg,
                user_id=uid,
                apply_officer_assignments=bool(apply_officers.value),
                force_regenerate=bool(force_regen.value),
                save_as_defaults=bool(save_defaults.value),
            )
        except Exception as exc:
            r = {"success": False, "message": f"Publish Crashed: {exc}"}
        finally:
            try:
                btn_impl.props(remove="disable loading")
            except Exception:
                pass
        msg = r.get("message") or ("Done" if r.get("success") else "Failed")
        ui.notify(msg, type="positive" if r.get("success") else "negative")
        if r.get("success"):
            set_action_log(
                "\n".join(
                    [
                        "Publish OK",
                        msg,
                        f"Year/Month: {r.get('year')}/{r.get('month')}",
                        f"Snapshot Id: {r.get('snapshot_id')}",
                        f"Live Snapshot Id: {r.get('live_snapshot_id')}",
                    ]
                ),
                ok=True,
            )
        else:
            set_action_log(f"Publish Failed\n{msg}", ok=False)

    def save_scenario():
        if not state.get("result"):
            ui.notify("Run Coverage First", type="warning")
            return
        uid = (session.current_user() or {}).get("id")
        name = f"Scenario {rotation.value} · {officers.value} Officers"
        tags = ["chronos"]
        if "8" in str(length.value or ""):
            tags.append("8h")
        if use_windows.value:
            tags.append("windows")
        r = save_simulator_scenario(
            name,
            config=state.get("config") or current_config(),
            result=state.get("result"),
            user_id=uid,
            notes="Saved From Chronos Simulator",
            tags=tags,
        )
        if r.get("success"):
            set_action_log(f"Save OK\nScenario Id: {r.get('scenario_id')}", ok=True)
            ui.notify(f"Saved #{r.get('scenario_id')}", type="positive")
        else:
            set_action_log(f"Save Failed\n{r.get('message')}", ok=False)

    def preview_publish():
        res = state.get("result")
        cfg = state.get("config")
        if not res or not res.get("success"):
            stored = get_last_optimized_plan()
            if stored:
                res, cfg = stored.get("result"), stored.get("config")
        if not res:
            ui.notify("No plan to preview", type="warning")
            return
        r = preview_implement_plan(
            start_date=(impl_date.value or "").strip(),
            result=res,
            config=cfg or current_config(),
            apply_officer_assignments=bool(apply_officers.value),
        )
        set_action_log(r.get("text") or r.get("message") or "Preview", ok=True)
        ui.notify("Publish preview (dry run)", type="info")

    def export_csv():
        if not state.get("result"):
            ui.notify("Run Coverage First", type="warning")
            return
        r = export_simulation_csv(state["result"])
        if r.get("success"):
            set_action_log(f"Export OK\nPath: {r.get('path')}", ok=True)
            ui.notify(f"Exported: {r.get('path')}", type="positive")
        else:
            set_action_log(f"Export Failed\n{r.get('message')}", ok=False)

    def bid_from_sim():
        if not state.get("result"):
            ui.notify("Run Coverage First", type="warning")
            return
        uid = (session.current_user() or {}).get("id")
        r = create_shift_bid_from_simulation(state["result"], publish=False, user_id=uid)
        if r.get("success"):
            set_action_log(f"Bid Draft OK\nEvent Id: {r.get('event_id')}", ok=True)
            ui.notify(f"Bid Draft #{r.get('event_id')}", type="positive")
        else:
            set_action_log(f"Bid Failed\n{r.get('message')}", ok=False)

    def export_options():
        ranked = state.get("ranked") or []
        if not ranked:
            ui.notify("No options to export", type="warning")
            return
        r = export_ranked_options_csv(ranked)
        if r.get("success"):
            ui.notify(f"Exported {r.get('path')}", type="positive")
            set_summary(f"Options CSV:\n{r.get('path')}")
        else:
            ui.notify("Export failed", type="negative")

    def export_audit():
        res = state.get("opt_result")
        if not res:
            ui.notify("Run Find Best first", type="warning")
            return
        r = export_search_audit_json(res)
        if r.get("success"):
            ui.notify(f"Audit: {r.get('path')}", type="positive")
            set_summary(f"Search audit JSON:\n{r.get('path')}")
        else:
            ui.notify("Audit export failed", type="negative")

    def run_diff_ab():
        a, b = state.get("compare_a"), state.get("compare_b")
        if not a or not b:
            ui.notify("Mark Option A and Option B first", type="warning")
            return
        lines = diff_options(a, b)
        set_summary("\n".join(lines))
        set_why("Side-by-side option comparison")

    def run_fairness():
        res = state.get("result") or state.get("opt_result") or {}
        full = fairness_report_full(res)
        lines = full.get("lines") or fairness_report_with_roster(res)
        if len(lines) < 3:
            lines = fairness_report(res)
        set_plan("\n".join(lines))
        set_summary("Fairness report in Plan Detail (roster names mapped)")
        ui.notify("Fairness report ready", type="info")

    def run_plain_explain():
        res = state.get("opt_result") or state.get("result") or {}
        exp = plain_english_staffing_explain(res)
        set_why(exp.get("text") or exp.get("message") or "")
        ui.notify("Plain-English explain ready", type="info")

    def run_sensitivity():
        cfg = state.get("last_config") or state.get("form") or load_form_snapshot() or {}
        if not isinstance(cfg, dict):
            cfg = {}
        # Attach last result for delta 0
        if state.get("opt_result"):
            cfg = dict(cfg)
            cfg["_cached_result"] = state.get("opt_result")
        # Cheap by default (residual: full search was too slow)
        sens = sensitivity_headcount(cfg, deep=False)
        night = sensitivity_relax_night_min(cfg, deep=False)
        text = (sens.get("text") or "") + "\n\n" + (night.get("text") or "")
        set_summary(text)
        ui.notify("Sensitivity complete (cheap mode)", type="info")

    def run_import_live():
        r = import_live_department_constraints()
        if r.get("success"):
            form = r.get("form") or {}
            # Best-effort hydrate state without inventing
            state["form"] = form
            set_summary(
                "Loaded live department constraints (no invented defaults):\n"
                + "\n".join(f"  {k}: {v}" for k, v in list(form.items())[:20])
            )
            ui.notify(r.get("message") or "Loaded", type="positive")
        else:
            ui.notify(r.get("message") or "Import failed", type="negative")

    def run_apply_winner_month():
        res = state.get("opt_result") or state.get("result")
        cfg = state.get("last_config") or state.get("form") or {}
        rec = recommend_implement_dates()
        start = rec.get("recommended_date") or ""
        uid = (session.current_user() or {}).get("id")
        r = apply_sim_winner_to_draft_month(
            start_date=start,
            result=res,
            config=cfg if isinstance(cfg, dict) else {},
            user_id=uid,
        )
        ui.notify(
            r.get("message") or ("Applied" if r.get("success") else "Apply failed"),
            type="positive" if r.get("success") else "warning",
        )
        if r.get("success"):
            set_summary((r.get("preview") or {}).get("text") or r.get("message") or "Draft month applied")

    def run_cpsat_small():
        cfg = state.get("last_config") or state.get("form") or load_form_snapshot() or {}
        if not isinstance(cfg, dict):
            cfg = {}
        r = try_cpsat_when_small(cfg)
        if r.get("skipped"):
            ui.notify(r.get("message") or "CP-SAT skipped", type="info")
            return
        if r.get("success"):
            state["opt_result"] = r
            exp = plain_english_staffing_explain(r)
            set_why(exp.get("text") or "")
            ui.notify("CP-SAT solved", type="positive")
        else:
            ui.notify(r.get("message") or "CP-SAT failed — use beam search", type="warning")

    def do_pin():
        row = state.get("selected_row")
        if not row:
            ranked = state.get("ranked") or []
            row = ranked[0] if ranked else None
        if not row:
            ui.notify("Select an option first", type="warning")
            return
        r = pin_option(row)
        ui.notify(f"Pinned: {r.get('label')}", type="positive")

    def do_share():
        res = state.get("opt_result") or {}
        if not res.get("best") and state.get("result"):
            res = {
                "best": state.get("selected_row") or (state.get("ranked") or [None])[0],
                "message": "Selected option",
                "scenarios_evaluated": (state.get("opt_result") or {}).get("scenarios_evaluated"),
                "wall_time_ms": (state.get("opt_result") or {}).get("wall_time_ms"),
            }
        body = format_share_message(res if res.get("best") else state.get("opt_result"))
        r = export_share_eml(state.get("opt_result") or res)
        try:
            ui.clipboard.write(body)
            ui.notify(f"Share text copied · .eml {r.get('path')}", type="positive")
        except Exception:
            set_why(body + f"\n\n.eml: {r.get('path')}")
            ui.notify("Share text in Why panel", type="info")

    def save_slot(letter: str):
        r = save_scenario_slot(
            letter,
            config=state.get("config") or current_config(),
            result=state.get("result") or state.get("opt_result"),
            ranked_row=state.get("selected_row"),
        )
        ui.notify(f"Saved scenario slot {r.get('slot')}", type="positive")

    def lock_selected_seed():
        row = state.get("selected_row")
        if not row:
            ranked = state.get("ranked") or []
            row = ranked[0] if ranked else None
        if not row:
            ui.notify("Select an option first", type="warning")
            return
        seed = option_seed_from_row(row)
        if seed.get("num_officers") is not None:
            officers.value = str(seed["num_officers"])
            use_officers.value = True
        if seed.get("shift_length_hours") is not None:
            length.value = str(seed["shift_length_hours"])
            use_length.value = True
        if seed.get("shift_starts"):
            starts.value = ", ".join(seed["shift_starts"])
            use_starts.value = True
        if seed.get("min_per_shift") is not None:
            min_ps.value = str(seed["min_per_shift"])
            use_min_ps.value = True
        if seed.get("rotation_variations"):
            variations.value = " | ".join(seed["rotation_variations"])
            use_style.value = True
            if c.get("use_rot_model") is not None and c.get("rot_model_kind") is not None:
                try:
                    c["rot_model_kind"].value = "Multi-block on/off"
                    c["use_rot_model"].value = True
                    if callable(c.get("sync_rotation_model")):
                        c["sync_rotation_model"]()
                except Exception:
                    pass
        try:
            refresh_space_estimate()
        except Exception:
            pass
        ui.notify("Locked form from selected option (seed for re-search)", type="positive")

    def apply_stay():
        row = state.get("selected_row")
        if not row:
            ui.notify("Select an option on Coverage step", type="warning")
            return
        apply_ranked_option(row)
        ui.notify("Option applied — still on Publish", type="positive")

    def apply_and_publish_step():
        row = state.get("selected_row")
        if row:
            apply_ranked_option(row)
        go_step(4)
        ui.notify("Option loaded — review Publish", type="info")

    def copy_summary():
        text = ""
        try:
            # last summary is in state if we track it
            text = state.get("last_summary") or ""
        except Exception:
            text = ""
        if not text and state.get("opt_result"):
            text = "\n".join(explain_staffing_result(state["opt_result"]))
        if not text:
            ui.notify("Nothing to copy", type="warning")
            return
        try:
            ui.clipboard.write(text)
            ui.notify("Summary copied", type="positive")
        except Exception:
            # Fallback path for environments without clipboard API
            set_why(text)
            ui.notify("Summary shown in Why panel (clipboard unavailable)", type="info")

    def export_config():
        r = export_form_config_json(form_payload())
        if r.get("success"):
            ui.notify(f"Config: {r.get('path')}", type="positive")
            set_summary(f"Exported config:\n{r.get('path')}")
        else:
            ui.notify("Export failed", type="negative")

    def import_config():
        with (
            ui.dialog() as dlg,
            ui.card().classes("q-pa-md").style("min-width:20rem;background:#0C1A2E;color:#E8EDF4"),
        ):
            ui.label("Import Config JSON Path").style("font-weight:700")
            path_in = ui.input(
                label="Full path to .json",
                value="",
            ).classes("w-full")

            def _go():
                from logic.optimizer_features import import_form_config_json

                r = import_form_config_json((path_in.value or "").strip())
                if not r.get("success"):
                    ui.notify(r.get("message") or "Import failed", type="negative")
                    return
                apply_form_payload(r.get("config") or {})
                persist_form()
                dlg.close()
                ui.notify("Config imported", type="positive")

            ui.button("Import", on_click=_go).classes("btn-primary").props("no-caps unelevated")
            ui.button("Cancel", on_click=dlg.close).classes("btn-ghost").props("no-caps outline")
        dlg.open()

    def export_memo():
        r = export_staffing_memo(
            result=state.get("result"),
            config=state.get("config"),
            ranked=state.get("ranked") or ((state.get("opt_result") or {}).get("ranked")),
            conflicts=detect_constraint_conflicts(constraint_context()),
        )
        if r.get("success"):
            set_summary((r.get("text") or "")[:4000])
            ui.notify(f"Memo: {r.get('path')}", type="positive")
        else:
            ui.notify("Memo export failed", type="negative")

    return {
        "run_sim": run_sim,
        "implement_plan": implement_plan,
        "save_scenario": save_scenario,
        "preview_publish": preview_publish,
        "export_csv": export_csv,
        "bid_from_sim": bid_from_sim,
        "export_options": export_options,
        "export_audit": export_audit,
        "run_diff_ab": run_diff_ab,
        "run_fairness": run_fairness,
        "run_plain_explain": run_plain_explain,
        "run_sensitivity": run_sensitivity,
        "run_import_live": run_import_live,
        "run_apply_winner_month": run_apply_winner_month,
        "run_cpsat_small": run_cpsat_small,
        "do_pin": do_pin,
        "do_share": do_share,
        "save_slot": save_slot,
        "lock_selected_seed": lock_selected_seed,
        "apply_stay": apply_stay,
        "apply_and_publish_step": apply_and_publish_step,
        "copy_summary": copy_summary,
        "export_config": export_config,
        "import_config": import_config,
        "export_memo": export_memo,
    }
