"""Ranked options render/apply + no-match dialog — extracted from page.py."""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Dict

from nicegui import run, ui

from gui.pages.simulator.decision_table import build_decision_table
from gui.pages.simulator.dialogs import last_int_in_text, open_no_match_dialog
from logic import format_optimized_plan_view, save_last_optimized_plan
from logic.optimizer_features import why_best_lines
from logic.rotation_config import normalize_rotation_preset_name
from logic.scheduling_sim import run_schedule_simulation
from logic.staffing_insights import detect_constraint_conflicts


def bind_ranked_render(state: dict, c: Dict[str, Any]) -> Dict[str, Callable]:
    """Bind ranked list / apply / no-match / precheck handlers."""

    rotation = c["rotation"]
    officers = c["officers"]
    min_ps = c["min_ps"]
    length = c["length"]
    annual = c["annual"]
    annual_var = c.get("annual_var")
    starts = c["starts"]
    variations = c["variations"]
    use_style = c["use_style"]
    use_rotation = c.get("use_rotation")
    use_rot_model = c.get("use_rot_model")
    rot_model_kind = c.get("rot_model_kind")
    sync_rotation_model = c.get("sync_rotation_model")
    use_officers = c.get("use_officers")
    use_starts = c.get("use_starts")
    use_length = c.get("use_length")
    use_annual = c.get("use_annual")
    use_fatigue = c["use_fatigue"]
    min_rest = c["min_rest"]
    max_consec = c["max_consec"]
    cov247 = c.get("cov247")
    baseline_kwargs = c["baseline_kwargs"]
    current_config = c["current_config"]
    human_metrics = c["human_metrics"]
    paint_kpis = c["paint_kpis"]
    constraint_context = c["constraint_context"]
    persist_form = c["persist_form"]
    set_enabled = c["set_enabled"]
    set_summary = c["set_summary"]
    set_why = c["set_why"]
    set_plan = c["set_plan"]
    options_ui = c["options_ui"]
    decision_host = c["decision_host"]
    session = c["session"]
    run_opt = c["run_opt"]
    en_off = c.get("en_off") or (lambda on: set_enabled([officers], on))
    en_st = c.get("en_st") or (lambda on: set_enabled([starts], on))
    en_len = c.get("en_len") or (lambda on: set_enabled([length], on))
    en_ann = c.get("en_ann") or (lambda on: set_enabled([annual], on) if annual is not None else None)
    refresh_win_list = c.get("refresh_win_list") or (lambda: None)
    parse_starts = c.get("parse_starts") or (lambda: [])
    nums = c.get("nums") or (lambda: (None, None, None, None, None, None, None, None))
    mode_label = c.get("mode_label")

    def load_option(row: dict):
        """Select + load a ranked option (decision table and cards share this)."""
        state["selected_row"] = row
        state["selected_rank"] = int(row.get("rank") or 1)
        apply_ranked_option(row)
        try:
            options_ui.refresh()
        except Exception:
            pass
        try:
            set_why("\n".join(why_best_lines({"best": row, "ranked": list(state.get("ranked") or [])})))
        except Exception:
            pass
        try:
            m = row.get("metrics") or row.get("human_metrics") or {}
            paint_kpis(
                hard_ok=row.get("hard_constraints_ok"),
                officers_n=row.get("num_officers"),
                layouts=None,
                annual_avg=m.get("avg_annual_hours"),
                window_fails=m.get("extra_window_failures"),
                rest_fails=m.get("rest_failures"),
                mode_text="Selected option",
                search_truncated=(state.get("opt_result") or {}).get("search_truncated"),
                search_exhaustive=(state.get("opt_result") or {}).get("search_exhaustive"),
            )
        except Exception:
            pass

    async def run_stress_test():
        from logic.staffing_insights import absence_stress_test

        top = list(state.get("ranked") or [])[:3]
        if not top:
            return
        kw = baseline_kwargs()
        kw.pop("error", None)
        ui.notify("Stress-testing top options (1 officer out)…", type="info")

        def _work():
            return {int(r.get("rank") or 0): absence_stress_test(r, kw) for r in top}

        try:
            state["stress_results"] = await run.io_bound(_work)
        except Exception as exc:
            ui.notify(f"Stress test failed: {exc}", type="negative")
            return
        paint_decision_table()
        ui.notify("Stress test done", type="positive")

    def paint_decision_table():
        try:
            _, _, an, _, _, _, fd, _ = nums()
        except Exception:
            an, fd = None, None
        try:
            build_decision_table(
                decision_host,
                list(state.get("ranked") or []),
                on_load=_load_option,
                annual_target=an,
                flsa_period_days=int(fd or 28),
                on_stress_test=lambda: asyncio.create_task(run_stress_test()),
                stress_results=state.get("stress_results") or {},
            )
        except Exception:
            pass

    def render_ranked(ranked: list, selected: int = 1):
        """Update ranked list state + refresh NiceGUI local-scope options_ui."""
        state["ranked"] = list(ranked or [])
        state["selected_rank"] = int(selected or 1)
        state["stress_results"] = {}  # stale after any new search
        try:
            options_ui.refresh()
        except Exception:
            pass
        paint_decision_table()

    def apply_ranked_option(row: dict):
        """Load ranked option into form, adopt as Given, re-sim with same hard constraints."""
        try:
            rt = row.get("rotation_type") or rotation.value
            rotation.value = normalize_rotation_preset_name(rt) if rt else rotation.value
        except Exception:
            pass
        if row.get("num_officers") is not None:
            officers.value = str(row["num_officers"])
            if use_officers is not None:
                use_officers.value = True
            try:
                en_off(True)
            except Exception:
                pass
        if row.get("min_per_shift") is not None:
            min_ps.value = str(row["min_per_shift"])
        if row.get("shift_length_hours") is not None:
            length.value = str(row["shift_length_hours"])
            if use_length is not None:
                use_length.value = True
            try:
                en_len(True)
            except Exception:
                pass
        if row.get("annual_hours_target") is not None:
            annual.value = str(int(row["annual_hours_target"]))
            if use_annual is not None:
                use_annual.value = True
            try:
                en_ann(True)
            except Exception:
                pass
        st = row.get("shift_starts")
        if st:
            starts.value = ", ".join(st) if isinstance(st, list) else str(st)
            if use_starts is not None:
                use_starts.value = True
            try:
                en_st(True)
            except Exception:
                pass
        if row.get("rotation_variations"):
            variations.value = " | ".join(row["rotation_variations"])
            use_style.value = True
            if use_rot_model is not None and rot_model_kind is not None:
                try:
                    rot_model_kind.value = "Multi-block on/off"
                    use_rot_model.value = True
                    if callable(sync_rotation_model):
                        sync_rotation_model()
                except Exception:
                    pass
        elif row.get("rotation_type"):
            try:
                rotation.value = row["rotation_type"]
                if use_rotation is not None:
                    use_rotation.value = True
                if use_rot_model is not None and rot_model_kind is not None:
                    rot_model_kind.value = "Squad preset"
                    use_rot_model.value = True
                    if callable(sync_rotation_model):
                        sync_rotation_model()
            except Exception:
                pass

        try:
            persist_form()
        except Exception:
            pass

        base = baseline_kwargs()
        if base.get("error"):
            ui.notify(f"Check Numbers: {base['error']}", type="negative")
            return
        ph = row.get("phase_overrides")
        pm = row.get("pattern_slot_map")
        # No silent bake of 8h / 0 annual — require real dims from row or Given base
        _len = (
            row.get("shift_length_hours")
            if row.get("shift_length_hours") is not None
            else base.get("shift_length_hours")
        )
        _ann = (
            row.get("annual_hours_target")
            if row.get("annual_hours_target") is not None
            else base.get("annual_hours_target")
        )
        _starts = list(row.get("shift_starts") or base.get("shift_starts") or [])
        if _len is None or not _starts:
            ui.notify(
                "Option missing shift length or starts — cannot load plan honestly.",
                type="warning",
            )
            return
        if _ann is None:
            _ann = 0.0  # annual optional soft metric only when not Given
        _avar = base.get("annual_hours_variance")
        _mps = row.get("min_per_shift") if row.get("min_per_shift") is not None else base.get("min_per_shift")
        _cov = base.get("coverage_247")
        _n = row.get("num_officers") if row.get("num_officers") is not None else base.get("num_officers")
        if _n is None or int(_n or 0) < 1:
            ui.notify("Option missing officer count — cannot load plan.", type="warning")
            return
        full = run_schedule_simulation(
            rotation_type=row.get("rotation_type") or base.get("rotation_type") or "",
            num_officers=int(_n),
            shift_length_hours=float(_len),
            annual_hours_target=float(_ann),
            shift_starts=_starts,
            min_per_shift=int(_mps if _mps is not None else 0),
            simulation_days=56,
            annual_hours_variance=float(_avar if _avar is not None else 0),
            annual_hours_hard=bool(base.get("annual_hours_hard")),
            coverage_247=int(_cov if _cov is not None else 0),
            avoid_flsa_overtime=bool(base.get("avoid_flsa_overtime")),
            flsa_work_period_days=int(base.get("flsa_work_period_days") or 28),
            rotation_style=base.get("rotation_style") or row.get("rotation_style") or "",
            rotation_variations=list(row.get("rotation_variations") or base.get("rotation_variations") or []),
            auto_min_officers=False,
            apply_department_rules=False,
            use_extra_windows=bool(base.get("use_extra_windows")),
            extra_windows=list(base.get("extra_windows") or []),
            # Replay optimizer layout exactly when present
            stagger_phases=bool(ph is None and pm is None),
            phase_overrides=list(ph) if isinstance(ph, (list, tuple)) else None,
            pattern_slot_map=list(pm) if isinstance(pm, (list, tuple)) else None,
            nearby_start_hops=int(base.get("nearby_start_hops") or 0),
            allow_offday_coverage=bool(base.get("allow_offday_coverage")),
            # Match Find Best fatigue hard constraints (was omitted — false OK)
            min_rest_hours=float(base.get("min_rest_hours") or 0),
            max_consecutive_work_days=int(base.get("max_consecutive_work_days") or 0),
        )
        if full.get("success"):
            state["result"] = full
            state["config"] = current_config()
            uid = (session.current_user() or {}).get("id")
            save_last_optimized_plan(full, state["config"], user_id=uid)
            view = format_optimized_plan_view(full, state["config"])
            set_plan(view.get("text") or full.get("message") or "")
            ui.notify(f"Using Option {row.get('rank')} (adopted as Given)", type="positive")
        else:
            ui.notify(full.get("message") or "Could Not Build Plan", type="warning")

    def apply_relaxation(s: dict) -> bool:
        """Apply one suggested relaxation to the form. True if applied."""
        cat = (s.get("category") or "").lower()
        action = s.get("action") or ""
        delta = s.get("delta") or ""
        if cat == "headcount":
            n = last_int_in_text(action)
            if not n:
                return False
            officers.value = str(n)
            if use_officers is not None:
                use_officers.value = True
            en_off(True)
            return True
        if cat == "coverage_247":
            n = last_int_in_text(delta) or last_int_in_text(action)
            if n is None or cov247 is None:
                return False
            cov247.value = str(max(0, n))
            return True
        if cat == "annual_hours":
            n = last_int_in_text(delta)
            if not n or annual_var is None:
                return False
            annual_var.value = str(n)
            return True
        if cat == "window":
            n = last_int_in_text(delta)
            if n is None:
                return False
            import re

            mlab = re.search(r"'([^']+)'", action)
            lab = mlab.group(1) if mlab else ""
            wins = list(state.get("windows") or [])
            for w in wins:
                if isinstance(w, dict) and (not lab or w.get("label") == lab):
                    w["min_officers"] = n
                    break
            else:
                return False
            state["windows"] = wins
            try:
                refresh_win_list()
            except Exception:
                pass
            return True
        if cat == "gaps":
            # Unlock starts so search can try more packs — do not inject a fixed clock
            if use_starts is not None and use_starts.value:
                use_starts.value = False
                en_st(False)
            return True
        if cat == "general":
            if use_officers is not None:
                use_officers.value = False
            en_off(False)
            if use_starts is not None:
                use_starts.value = False
            en_st(False)
            return True
        return False

    def show_no_match_dialog(
        evaluated: int,
        rejected: int,
        extra: str = "",
        near_misses: list | None = None,
    ):
        async def _after_relax():
            persist_form()
            ui.notify("Relaxation applied", type="info")
            await run_opt(require_hard_ok=True)

        def _pick_near(row: dict):
            apply_ranked_option(row)
            render_ranked(
                [{"rank": 1, **row, "summary": row.get("summary")}],
                selected=1,
            )
            set_summary(
                "Loaded Near-Miss Alternative (does not meet all hard constraints).\n" + (row.get("summary") or "")
            )

        async def _soften():
            state["hard_mode"] = False
            if mode_label is not None:
                try:
                    mode_label.set_text("Mode: Softened (Best Effort)")
                except Exception:
                    pass
            await run_opt(require_hard_ok=False)

        async def _research():
            await run_opt(require_hard_ok=True)

        def _close_sum():
            set_summary(
                "No Schedule Meets Selected Hard Constraints.\n"
                "Use closest alternatives, change priority order, or soften."
            )

        open_no_match_dialog(
            evaluated=evaluated,
            rejected=rejected,
            extra=extra,
            near_misses=near_misses,
            opt_result=state.get("opt_result") or {},
            config=state.get("config") or {},
            apply_relaxation=apply_relaxation,
            on_apply_and_research=_after_relax,
            on_pick_near_miss=_pick_near,
            on_soften=_soften,
            on_research=_research,
            on_close_summary=_close_sum,
        )

    def precheck_conflicts(*, force_dialog: bool = True) -> bool:
        """Return True if search may proceed (no hard conflicts or user overrides)."""
        ctx = constraint_context()
        if use_fatigue.value:
            ctx["use_fatigue"] = True
            ctx["min_rest"] = min_rest.value
            ctx["max_consec"] = max_consec.value
        chk = detect_constraint_conflicts(ctx)
        if chk.get("ok") and not chk.get("warnings"):
            return True
        lines = chk.get("lines") or [chk.get("message") or "Conflict check"]
        if force_dialog:
            with (
                ui.dialog() as dlg,
                ui.card()
                .classes("q-pa-md")
                .style(
                    "min-width:22rem;max-width:34rem;background:#0C1A2E;color:#E8EDF4;"
                    "border:1px solid rgba(251,191,36,0.5)"
                ),
            ):
                ui.label("Constraint Precheck").style("font-weight:700;font-size:1.05rem;color:#FDE68A")
                for msg in lines[:12]:
                    ui.label(f"· {msg}").style("color:#E8EDF4;font-size:0.88rem;margin-top:4px")
                if chk.get("blocking"):
                    ui.label("Blocking conflicts — fix constraints before long search.").style(
                        "color:#fca5a5;margin-top:10px"
                    )
                    ui.button("Close", on_click=dlg.close).classes("btn-ghost q-mt-md").props("no-caps outline")
                else:
                    ui.label("Warnings only — you may continue.").style("color:#FDE68A;margin-top:10px")
                    state["_precheck_continue"] = False

                    def _go():
                        state["_precheck_continue"] = True
                        dlg.close()

                    ui.button("Search Anyway", on_click=_go).classes("btn-primary q-mt-md").props("no-caps unelevated")
                    ui.button("Cancel", on_click=dlg.close).classes("btn-ghost q-mt-md").props("no-caps outline")
            dlg.open()
            if chk.get("blocking"):
                return False
            # Dialog is async-ish; for sync path treat warnings as proceed with notify
            for msg in lines[:3]:
                ui.notify(msg, type="warning")
        return not chk.get("blocking")

    return {
        "load_option": load_option,
        "run_stress_test": run_stress_test,
        "paint_decision_table": paint_decision_table,
        "render_ranked": render_ranked,
        "apply_ranked_option": apply_ranked_option,
        "apply_relaxation": apply_relaxation,
        "show_no_match_dialog": show_no_match_dialog,
        "precheck_conflicts": precheck_conflicts,
    }
