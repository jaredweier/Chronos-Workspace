"""Optimizer search actions extracted from simulator page.py."""

from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict

from nicegui import run, ui

from gui.pages.simulator.dialogs import open_large_search_dialog
from logic.optimizer_features import (
    append_search_history,
    default_weight_map,
    why_best_lines,
)
from logic.plan_explain import explain_staffing_result
from logic.scheduling_sim import (
    compare_shift_length_scenarios,
    estimate_staffing_search_space,
    find_min_officers_hard,
    run_staffing_optimizer,
    run_staffing_stage_wizard,
    what_if_staffing_delta,
)
from logic.staffing_insights import detect_constraint_conflicts

OPT_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="staffing-opt")


def bind_optimizer_actions(state: dict, c: Dict[str, Any]) -> Dict[str, Callable]:
    """Bind Find Best / compare / min-N / what-if handlers to form + chrome refs."""

    # Dependencies injected from page.py
    use_starts = c["use_starts"]
    use_length = c["use_length"]
    use_officers = c["use_officers"]
    officers = c["officers"]
    use_rotation = c["use_rotation"]
    rotation = c["rotation"]
    use_min_ps = c["use_min_ps"]
    use_annual = c["use_annual"]
    use_247 = c["use_247"]
    use_start_date = c["use_start_date"]
    sim_start_date = c["sim_start_date"]
    use_flsa = c["use_flsa"]
    use_windows = c["use_windows"]
    use_style = c["use_style"]
    allow_offday = c["allow_offday"]
    use_fatigue = c["use_fatigue"]
    min_rest = c["min_rest"]
    max_consec = c["max_consec"]
    starts = c["starts"]
    compare_quick = c["compare_quick"]
    nums = c["nums"]
    parse_starts = c["parse_starts"]
    style_value = c["style_value"]
    var_list = c["var_list"]
    parse_nearby_hops = c["parse_nearby_hops"]
    baseline_kwargs = c["baseline_kwargs"]
    constraint_context = c["constraint_context"]
    current_config = c["current_config"]
    paint_kpis = c["paint_kpis"]
    render_ranked = c["render_ranked"]
    apply_ranked_option = c["apply_ranked_option"]
    show_no_match_dialog = c["show_no_match_dialog"]
    set_space_warn = c["set_space_warn"]
    set_summary = c["set_summary"]
    set_why = c["set_why"]
    btn_opt = c["btn_opt"]
    btn_gen = c["btn_gen"]
    btn_compare = c["btn_compare"]
    btn_min_n = c["btn_min_n"]
    btn_whatif = c["btn_whatif"]
    search_spinner = c["search_spinner"]
    skeleton_host = c["skeleton_host"]
    search_status = c["search_status"]
    search_status_host = c["search_status_host"]
    progress_bar = c["progress_bar"]
    mode_label = c["mode_label"]
    options_ui = c["options_ui"]

    def _optimizer_kwargs(*, require_hard_ok: bool) -> dict:
        n, ln, an, av, mp, c247, fd, err = nums()
        if err:
            return {"error": err}
        free_starts = not use_starts.value
        free_lengths = not use_length.value
        free_officers = not (use_officers.value and n is not None and n >= 1)
        if not free_officers:
            off_counts = [int(n)]
        else:
            # Unselected officer count must search the full realistic
            # range, not a narrow band around a guessed hint — a hint-based
            # band could sit entirely outside the true viable range and
            # cause Find Best to report "impossible" when a valid option
            # Headcount is a small integer axis — both depths search 4–20 fully.
            off_counts = list(range(4, 21))
        # Free lengths: always full 8–12.5h half-hour grid (depth never drops
        # lengths — that false-greened viable options). Depth only changes
        # search wall/pack budgets in the optimizer.
        length_opts = None
        if free_lengths:
            length_opts = [8.0, 8.5, 9.0, 9.5, 10.0, 10.5, 11.0, 11.5, 12.0, 12.5]
        st = parse_starts() if use_starts.value else None
        depth = str(state.get("search_depth") or "standard").strip().lower()
        if depth not in ("standard", "deep"):
            depth = "standard"
        return {
            "rotation_types": [rotation.value] if use_rotation.value else None,
            "officer_counts": off_counts,
            "min_per_shift_options": [int(mp)] if use_min_ps.value and mp is not None else None,
            "shift_length_hours": float(ln) if use_length.value and ln is not None else None,
            "shift_length_options": length_opts,
            "search_depth": depth,
            "annual_hours_target": float(an) if use_annual.value and an is not None else None,
            "shift_starts": st,
            "free_starts": free_starts,
            "free_lengths": free_lengths,
            "free_officer_counts": free_officers,
            # Multi-block free when Rotation model is not Given as multi-block
            "free_variations": (not use_style.value) or (not var_list()),
            # Always 28-day hard eval — shorter windows can false-green lean N
            "simulation_days": 56,
            "coverage_247": int(c247) if use_247.value and c247 is not None else 0,
            "sim_start_date": sim_start_date.value if use_start_date.value else None,
            "avoid_flsa_overtime": bool(use_flsa.value),
            "flsa_work_period_days": int(fd) if use_flsa.value and fd is not None else 28,
            "annual_hours_variance": float(av) if use_annual.value and av is not None else None,
            "annual_hours_hard": bool(use_annual.value and require_hard_ok),
            "use_extra_windows": bool(use_windows.value and state["windows"]),
            "extra_windows": list(state["windows"]) if use_windows.value else [],
            "require_hard_ok": require_hard_ok,
            "rotation_style": style_value(),
            "rotation_variations": var_list(),
            "stagger_phases": True,
            "nearby_start_hops": parse_nearby_hops(),
            "allow_offday_coverage": bool(allow_offday.value),
            "min_rest_hours": (float((min_rest.value or "0").strip() or 0) if use_fatigue.value else 0.0),
            "max_consecutive_work_days": (
                int(float((max_consec.value or "0").strip() or 0)) if use_fatigue.value else 0
            ),
            "constraint_priority": list(state.get("constraint_priority") or []),
            "constraint_weights": dict(state.get("constraint_weights") or default_weight_map()),
            # Soft prefs only re-rank hard-OK options (never change feasibility)
            "soft_prefs": dict(state.get("soft_prefs") or {}),
        }

    def _refresh_space_estimate():
        kw = _optimizer_kwargs(require_hard_ok=bool(state.get("hard_mode", True)))
        if kw.get("error"):
            set_space_warn(f"Fix numbers: {kw['error']}", risk="high")
            return None
        kw.pop("error", None)
        est = estimate_staffing_search_space(
            **{
                k: v
                for k, v in kw.items()
                if k
                not in (
                    "require_hard_ok",
                    "annual_hours_hard",
                    "annual_hours_variance",
                    "annual_hours_target",
                    "coverage_247",
                    "avoid_flsa_overtime",
                    "flsa_work_period_days",
                    "use_extra_windows",
                    "extra_windows",
                    "simulation_days",
                    "constraint_priority",
                    "constraint_weights",
                    "soft_prefs",
                    "stagger_phases",
                    "min_rest_hours",
                    "max_consecutive_work_days",
                    "allow_offday_coverage",
                    "nearby_start_hops",
                    "require_hard_ok",
                )
            }
        )
        state["space_estimate"] = est
        risk = est.get("risk") or "low"
        lines = [
            est.get("warning") or "",
            f"Layouts In Space: {int(est.get('total_layouts') or 0):,}",
            f"Free Dimensions: {', '.join(est.get('free_dimensions') or []) or 'none (fully locked)'}",
        ]
        # Live cheap feasibility strip (no 56d sim) — hard body floor only; soft annual caution
        try:
            from logic.constraint_autopsy import cheap_feasibility_strip

            form_snap = {
                "num_officers": kw.get("num_officers"),
                "auto_min_officers": kw.get("auto_min_officers"),
                "shift_length_hours": kw.get("shift_length_hours"),
                "coverage_247": kw.get("coverage_247"),
                "min_per_shift": kw.get("min_per_shift"),
                "shift_starts": kw.get("shift_starts"),
                "extra_windows": kw.get("extra_windows"),
                "annual_hours_target": kw.get("annual_hours_target"),
            }
            # Prefer live form when optimizer kwargs omit unlocked dims
            try:
                cfg = current_config() if callable(current_config) else {}
                if isinstance(cfg, dict):
                    form_snap = {**form_snap, **{k: cfg.get(k, form_snap.get(k)) for k in form_snap}}
            except Exception:
                pass
            strip = cheap_feasibility_strip(form_snap)
            state["feasibility_strip"] = strip
            for ln in strip.get("lines") or []:
                if ln:
                    lines.append(ln)
            # Escalate risk if body floor blocks locked N
            sr = strip.get("risk") or "low"
            order = {"low": 0, "medium": 1, "high": 2, "extreme": 3}
            if order.get(sr, 0) > order.get(risk, 0):
                risk = sr
        except Exception:
            pass
        if est.get("requires_confirm"):
            lines.append(
                "Confirm before Find Best — this can take a long time. "
                "Lock officer count / starts / length if possible."
            )
        set_space_warn("\n".join([x for x in lines if x]), risk=risk)
        return est

    def _paint_search_mode_badge(result: dict) -> None:
        """C3a: always-visible Search Mode line after a run."""
        badge = c.get("search_mode_badge")
        if badge is None:
            return
        if result.get("search_exhaustive") is True:
            mode = "Exhaustive"
        elif result.get("budget_exhausted"):
            mode = "Anytime (time limit)"
        elif result.get("search_truncated"):
            mode = "Partial"
        else:
            mode = (
                str((result.get("constraints_applied") or {}).get("search_mode") or "Search").replace("_", " ").title()
            )
        evals = result.get("scenarios_evaluated")
        wall = result.get("wall_time_ms")
        parts = [f"Search Mode: {mode}"]
        if evals is not None:
            try:
                parts.append(f"{int(evals):,} layouts")
            except (TypeError, ValueError):
                pass
        if wall is not None:
            try:
                parts.append(f"{int(wall)} ms")
            except (TypeError, ValueError):
                pass
        try:
            badge.set_text(" · ".join(parts))
            badge.style("color:var(--muted);display:block")
        except Exception:
            pass

    def _apply_opt_result(result: dict, *, require_hard_ok: bool) -> None:
        state["config"] = current_config()
        near = result.get("near_misses") or []
        try:
            _paint_search_mode_badge(result)
        except Exception:
            pass
        if result.get("impossible") or (require_hard_ok and (not result.get("success") or not result.get("best"))):
            state["opt_result"] = result
            note = result.get("space_note") or ""
            hist = result.get("failure_histogram") or {}
            if hist:
                top = ", ".join(f"{k}={v}" for k, v in sorted(hist.items(), key=lambda x: -x[1]) if v)
                if top:
                    note = (note + "\n" if note else "") + f"Reject reasons: {top}"
            evals = int(result.get("scenarios_evaluated") or 0)
            full_n = int(result.get("full_sims_run") or 0)
            tips = explain_staffing_result(result)
            _mode = (
                "Exhaustive"
                if result.get("search_exhaustive")
                else (
                    "Anytime (time limit)"
                    if result.get("budget_exhausted")
                    else ("Partial" if result.get("search_truncated") else "Search")
                )
            )
            set_summary(
                "\n".join(
                    tips
                    or [
                        result.get("message") or "No Schedule Meets Selected Hard Constraints",
                        f"Layouts Checked: {evals:,}",
                        f"Search Mode: {_mode}",
                        f"Combinations Tried: {evals:,}",
                        f"Full Simulations: {full_n:,} · Pruned Impossible: {result.get('pruned_cheap', '—')}",
                        note,
                        "",
                        "Closest alternatives listed below (if any).",
                    ]
                )
            )
            try:
                set_why("\n".join(tips[-8:] if tips else []))
            except Exception:
                pass
            if near:
                render_ranked(near[:10], selected=1)
            else:
                render_ranked([])
            try:
                nm0 = (near[0] if near else {}) or {}
                m0 = nm0.get("metrics") or nm0.get("human_metrics") or {}
                paint_kpis(
                    hard_ok=False,
                    officers_n=nm0.get("num_officers"),
                    layouts=evals,
                    annual_avg=m0.get("avg_annual_hours"),
                    window_fails=m0.get("extra_window_failures"),
                    rest_fails=m0.get("rest_failures"),
                    mode_text="No hard match",
                    search_truncated=bool(result.get("search_truncated")),
                    search_exhaustive=bool(result.get("search_exhaustive")),
                )
            except Exception:
                pass
            show_no_match_dialog(
                evals,
                int(result.get("rejected_hard_constraints") or 0),
                extra=note,
                near_misses=near,
            )
            return
        if not result.get("success") or not result.get("best"):
            set_summary(result.get("message", "No Combination Found"))
            ui.notify(result.get("message", "No Combination Found"), type="negative")
            render_ranked([])
            return
        ranked = result.get("ranked") or []
        best = result["best"]
        state["opt_result"] = result
        lines = list(explain_staffing_result(result))
        if result.get("search_exhaustive") is True:
            _search_line = "Search Mode: Exhaustive"
        elif result.get("budget_exhausted"):
            _search_line = "Search Mode: Anytime (time limit)"
        elif result.get("search_truncated"):
            _search_line = "Search Mode: Partial (not every layout)"
        else:
            _mode = (result.get("constraints_applied") or {}).get("search_mode") or "anytime"
            _search_line = f"Search Mode: {str(_mode).replace('_', ' ').title()}"
        if result.get("wall_time_ms") is not None:
            _search_line += f" · {result.get('wall_time_ms')} ms"
        lines.extend(
            [
                f"Structural Configs: {result.get('outer_configs', '—')} · "
                f"Full Simulations: {result.get('full_sims_run', '—')} · "
                f"Pruned Impossible: {result.get('pruned_cheap', '—')}",
                f"Options Kept: {result.get('scenarios_kept', len(ranked))}",
                _search_line,
            ]
        )
        if result.get("space_note"):
            lines.append(result["space_note"])
        lines.extend(["", "Select An Option Below To Load It."])
        set_summary("\n".join(lines))
        try:
            set_why("\n".join(why_best_lines(result)))
        except Exception:
            set_why("")
        render_ranked(ranked, selected=int(best.get("rank") or 1))
        # C1: adopt best as selected so Generate seamless path sees selected_row
        state["selected_row"] = best
        state["selected_rank"] = int(best.get("rank") or 1)
        apply_ranked_option(best)
        try:
            bm = best.get("metrics") or best.get("human_metrics") or {}
            paint_kpis(
                hard_ok=best.get("hard_constraints_ok"),
                officers_n=best.get("num_officers"),
                layouts=result.get("scenarios_evaluated"),
                annual_avg=bm.get("avg_annual_hours"),
                window_fails=bm.get("extra_window_failures"),
                rest_fails=bm.get("rest_failures"),
                mode_text="Hard" if require_hard_ok else "Softened",
                search_truncated=bool(result.get("search_truncated")),
                search_exhaustive=bool(result.get("search_exhaustive")),
            )
        except Exception:
            pass
        ui.notify(result.get("message", "Coverage Search Complete"), type="positive")

    def _set_search_buttons(running: bool) -> None:
        state["opt_running"] = running
        try:
            if running:
                btn_opt.props("disable loading")
                btn_gen.props("disable")
                btn_compare.props("disable")
                btn_min_n.props("disable")
                btn_whatif.props("disable")
            else:
                btn_opt.props(remove="disable loading")
                btn_gen.props(remove="disable")
                btn_compare.props(remove="disable")
                btn_min_n.props(remove="disable")
                btn_whatif.props(remove="disable")
        except Exception:
            pass
        try:
            search_spinner.set_visibility(bool(running))
            skeleton_host.set_visibility(bool(running))
            if running:
                search_status.set_text("Searching layouts…")
                search_status_host.classes(add="is-running")
            else:
                search_status.set_text("Ready · hard constraints")
                search_status_host.classes(remove="is-running")
        except Exception:
            pass

    async def _execute_opt(kw: dict, *, require_hard_ok: bool):
        """Run search on worker thread; poll progress on UI thread (no hang)."""
        if state.get("opt_running"):
            ui.notify("Search already running", type="warning")
            return
        state["hard_mode"] = require_hard_ok
        mode_label.set_text("Mode: hard constraints" if require_hard_ok else "Mode: softened (best effort)")
        cancel_ev = threading.Event()
        progress: dict = {
            "message": "Searching layouts…",
            "done": 0,
            "total": 0,
            "full_sims": 0,
        }
        state["opt_cancel"] = cancel_ev
        import time as _time

        state["opt_t0"] = _time.perf_counter()
        _set_search_buttons(True)
        try:
            progress_bar.style("display:block")
            progress_bar.value = 0
        except Exception:
            pass
        try:
            state["ranked"] = []
            options_ui.refresh()
        except Exception:
            pass
        set_summary("Searching layouts…")
        ui.notify("Searching layouts…", type="info", position="top")
        await asyncio.sleep(0.05)

        def _on_progress(info: dict) -> None:
            if not isinstance(info, dict):
                return
            progress["message"] = str(info.get("message") or progress["message"])
            if info.get("done") is not None:
                progress["done"] = int(info["done"])
            if info.get("total") is not None:
                progress["total"] = int(info["total"])
            if info.get("full_sims") is not None:
                progress["full_sims"] = int(info["full_sims"])

        job_kw = dict(kw)
        job_kw["progress_callback"] = _on_progress
        job_kw["cancel_check"] = cancel_ev.is_set

        loop = asyncio.get_event_loop()
        try:
            fut = loop.run_in_executor(
                OPT_EXECUTOR,
                lambda: run_staffing_optimizer(**job_kw),
            )
            while not fut.done():
                done = int(progress.get("done") or 0)
                total = int(progress.get("total") or 0)
                full = int(progress.get("full_sims") or 0)
                msg = progress.get("message") or "Searching…"
                eta = ""
                t0 = state.get("opt_t0")
                if t0 and done > 5 and total > done:
                    import time as _time

                    elapsed = max(0.1, _time.perf_counter() - float(t0))
                    rate = done / elapsed
                    remain = max(0, (total - done) / max(rate, 1e-6))
                    eta = f" · ETA ~{int(remain)}s"
                if total > 0:
                    frac = min(1.0, done / max(total, 1))
                    pct = f" · {int(100 * frac)}%"
                    try:
                        progress_bar.value = frac
                    except Exception:
                        pass
                    try:
                        search_status.set_text(f"{int(100 * frac)}% · {done:,}/{total:,}{eta}")
                    except Exception:
                        pass
                    set_summary(
                        f"{msg}\nLayouts: {done:,} / {total:,}{pct}{eta} · "
                        f"Full Sims: {full:,}\n"
                        "Cancel search stops after the current layout."
                    )
                else:
                    try:
                        search_status.set_text(f"{done:,} layouts · sims {full:,}{eta}")
                    except Exception:
                        pass
                    set_summary(
                        f"{msg}\nLayouts: {done:,} · Full Sims: {full:,}{eta}\n"
                        "Cancel search stops after the current layout."
                    )
                await asyncio.sleep(0.25)
            result = fut.result()
        except Exception as exc:
            _set_search_buttons(False)
            set_summary(f"Search Failed: {exc}")
            ui.notify(f"Search Failed: {exc}", type="negative")
            return
        finally:
            _set_search_buttons(False)
            state["opt_cancel"] = None
            state["opt_t0"] = None
            try:
                progress_bar.style("display:none")
                progress_bar.value = 0
            except Exception:
                pass

        if not isinstance(result, dict):
            set_summary(f"Search Failed: unexpected result type {type(result)!r}")
            ui.notify("Search Failed: bad result", type="negative")
            return
        if result.get("cancelled") and not result.get("best") and not result.get("near_misses"):
            set_summary(result.get("message") or "Search cancelled")
            ui.notify("Search cancelled", type="warning")
            return
        try:
            best = result.get("best") or {}
            append_search_history(
                {
                    "success": result.get("success"),
                    "message": (result.get("message") or "")[:120],
                    "num_officers": best.get("num_officers"),
                    "wall_time_ms": result.get("wall_time_ms"),
                    "scenarios_evaluated": result.get("scenarios_evaluated"),
                    "hard_ok": best.get("hard_constraints_ok"),
                }
            )
        except Exception:
            pass
        try:
            _apply_opt_result(result, require_hard_ok=require_hard_ok)
        except Exception as exc:
            set_summary(
                f"{result.get('message') or 'Search finished'}\n"
                f"Layouts Checked: {int(result.get('scenarios_evaluated') or 0):,}\n"
                f"UI apply error: {exc}"
            )
            ui.notify(f"Search finished; apply error: {exc}", type="warning")
            near = result.get("near_misses") or result.get("ranked") or []
            if near:
                render_ranked(near[:10], selected=1)

    async def _run_opt(*, require_hard_ok: bool, force: bool = False):
        kw = _optimizer_kwargs(require_hard_ok=require_hard_ok)
        if kw.get("error"):
            ui.notify(kw.get("error") or "Check Numeric Fields", type="negative")
            return
        chk = detect_constraint_conflicts(constraint_context())
        if chk.get("blocking"):
            for msg in (chk.get("lines") or [])[:4]:
                ui.notify(msg, type="negative")
            return
        if chk.get("warnings") and not force:
            for msg in (chk.get("lines") or [])[:3]:
                ui.notify(msg, type="warning")
        if use_officers.value:
            try:
                n = int((officers.value or "0").strip() or "0")
            except ValueError:
                n = 0
            if n < 1:
                ui.notify("Officer Count Requires A Number When Selected", type="warning")
                return
        kw.pop("error", None)
        est = _refresh_space_estimate()
        if not force and est and est.get("requires_confirm") and require_hard_ok:
            state["pending_opt_kw"] = dict(kw)
            state["pending_require_hard"] = require_hard_ok

            async def _go_full():
                job = dict(state.get("pending_opt_kw") or kw)
                hard = bool(state.get("pending_require_hard", require_hard_ok))
                await _execute_opt(job, require_hard_ok=hard)

            open_large_search_dialog(
                warning=est.get("warning") or "",
                on_run=_go_full,
            )
            return

        await _execute_opt(kw, require_hard_ok=require_hard_ok)

    async def run_opt():
        _refresh_space_estimate()
        await _run_opt(require_hard_ok=True)

    async def run_stage_wizard():
        """Pause after feasibility stages — lock dims — then full Find Best."""
        kw = _optimizer_kwargs(require_hard_ok=bool(state.get("hard_mode", True)))
        if kw.get("error"):
            ui.notify(kw.get("error") or "Check Numeric Fields", type="negative")
            return
        kw.pop("error", None)
        _set_search_buttons(True)
        set_summary("Running feasibility stages (no full sim yet)…")
        try:
            progress: dict = {"message": "Stages…"}

            def _on_progress(info: dict) -> None:
                if isinstance(info, dict):
                    progress["message"] = str(info.get("message") or progress["message"])

            job = dict(kw)
            job["progress_callback"] = _on_progress
            loop = asyncio.get_event_loop()
            fut = loop.run_in_executor(OPT_EXECUTOR, lambda: run_staffing_stage_wizard(**job))
            while not fut.done():
                try:
                    search_status.set_text(str(progress.get("message") or "Stages…")[:80])
                except Exception:
                    pass
                set_summary(str(progress.get("message") or "Stages…"))
                await asyncio.sleep(0.2)
            result = fut.result()
        except Exception as exc:
            _set_search_buttons(False)
            ui.notify(f"Stage wizard failed: {exc}", type="negative")
            return
        finally:
            _set_search_buttons(False)

        if not isinstance(result, dict):
            ui.notify("Stage wizard bad result", type="negative")
            return
        state["stage_wizard"] = result
        lines = list(result.get("stage_lines") or [])
        lines.append("")
        lines.append(result.get("message") or "Stages done")
        for t in list(result.get("stage_tips") or [])[:8]:
            lines.append(f"· {t}")
        set_summary("\n".join(lines))

        with (
            ui.dialog() as dlg,
            ui.card()
            .classes("q-pa-md")
            .style(
                "min-width:24rem;max-width:40rem;background:#0C1A2E;color:#E8EDF4;border:1px solid rgba(91,141,239,0.4)"
            ),
        ):
            ui.label("Stage wizard — pause before full search").style("font-weight:700;font-size:1.1rem;color:#F8FAFC")
            ui.label("Feasibility stages finished. Lock dimensions to shrink search, then continue.").style(
                "color:#9AABC4;margin:8px 0 12px;line-height:1.4"
            )
            for line in list(result.get("stage_lines") or [])[:12]:
                ui.label(line).style("color:#D6E6FF;font-size:0.85rem;white-space:pre-wrap")

            hints = result.get("form_hints") or {}
            if hints:
                ui.label("Auto-lock suggestion: " + ", ".join(f"{k}={v}" for k, v in hints.items())).style(
                    "color:#86efac;margin-top:8px"
                )

            apply_payload = c.get("apply_form_payload")

            def _apply_patch(patch: dict, lab: str = ""):
                if not patch:
                    return
                if callable(apply_payload):
                    try:
                        apply_payload(patch)
                    except Exception:
                        pass
                ui.notify(f"Locked: {lab or list(patch.keys())}", type="positive")

            if hints and apply_payload:

                def _auto():
                    _apply_patch(hints, "auto from stages")
                    dlg.close()

                ui.button("Apply auto-locks", on_click=_auto).classes("btn-primary q-mt-sm").props("no-caps unelevated")

            for a in list(result.get("lock_actions") or [])[:8]:
                lab = a.get("label") or a.get("id")
                patch = a.get("form_patch") or {}
                why = a.get("why") or ""

                def _clk(p=patch, L=lab):
                    _apply_patch(p, L)

                ui.button(str(lab), on_click=_clk).classes("btn-ghost q-mt-xs").props(
                    "no-caps outline dense align=left"
                ).style("width:100%;text-align:left;white-space:normal")
                if why:
                    ui.label(why).style("color:#9AABC4;font-size:0.8rem;margin:0 0 6px 10px")

            async def _continue_full():
                dlg.close()
                await _run_opt(require_hard_ok=bool(state.get("hard_mode", True)), force=True)

            ui.button("Continue full Find Best", on_click=_continue_full).classes("btn-primary q-mt-md").props(
                "no-caps unelevated"
            )
            ui.button("Close (edit form manually)", on_click=dlg.close).classes("btn-ghost q-mt-sm").props(
                "no-caps outline"
            )
        dlg.open()

    async def run_compare():
        """Compare 8/10/12h under same coverage constraints (locked N)."""
        if state.get("opt_running"):
            ui.notify("Search already running", type="warning")
            return
        base = baseline_kwargs()
        if base.get("error"):
            ui.notify(base["error"] or "Check requirements", type="negative")
            return
        try:
            n = int(base.get("num_officers") or 0)
        except (TypeError, ValueError):
            n = 0
        if n < 1:
            ui.notify("Lock officer count (Given) before compare", type="warning")
            return
        annual = base.get("annual_hours_target")
        if annual is None:
            ui.notify("Lock annual hours before compare", type="warning")
            return
        variance = float(base.get("annual_hours_variance") or 40)
        wins = list(base.get("extra_windows") or []) if base.get("use_extra_windows") else []
        cov247 = int(base.get("coverage_247") or 0)
        cancel_ev = threading.Event()
        state["opt_cancel"] = cancel_ev
        state["opt_running"] = True
        depth = "quick" if bool(compare_quick.value) else "deep"
        set_summary(f"Comparing 8h / 10h / 12h ({depth}, parallel)…\nCancel Search stops mid-search on each length.")
        try:
            result = await run.io_bound(
                lambda: compare_shift_length_scenarios(
                    lengths=[8.0, 10.0, 12.0],
                    officer_count=n,
                    annual_hours_target=float(annual),
                    annual_hours_variance=variance,
                    coverage_247=cov247,
                    extra_windows=wins or None,
                    rotation_variations=list(base.get("rotation_variations") or []) or None,
                    require_hard_ok=True,
                    cancel_check=cancel_ev.is_set,
                    depth=depth,
                )
            )
        except Exception as exc:
            set_summary(f"Compare Failed: {exc}")
            ui.notify(f"Compare Failed: {exc}", type="negative")
            state["opt_running"] = False
            state["opt_cancel"] = None
            return
        state["opt_running"] = False
        state["opt_cancel"] = None
        if result.get("cancelled"):
            set_summary(result.get("message") or "Compare cancelled")
            ui.notify("Compare cancelled", type="warning")
            return
        lines = list(result.get("table_lines") or [])
        if not lines:
            lines = [result.get("message") or "Shift Length Comparison", ""]
            for c in result.get("comparisons") or []:
                flag = "OK" if c.get("success") else "NO"
                lines.append(
                    f"{c.get('shift_length_hours')}h · {flag} · "
                    f"Layouts Checked: {c.get('scenarios_evaluated', '—')} · "
                    f"starts={c.get('best_starts') or '—'} · "
                    f"var={c.get('best_variation') or '—'} · "
                    f"near_miss={c.get('near_miss_count', 0)}"
                )
        set_summary("\n".join(lines))
        set_why(result.get("message") or "Compare finished")
        ui.notify(result.get("message") or "Compare Done", type="positive")

    async def run_min_n():
        if state.get("opt_running"):
            ui.notify("Search already running", type="warning")
            return
        cancel_ev = threading.Event()
        state["opt_cancel"] = cancel_ev
        _set_search_buttons(True)
        set_summary("Finding minimum officers for hard constraints…")
        try:
            base = baseline_kwargs()
            result = await run.io_bound(
                lambda: find_min_officers_hard(
                    lo=max(1, int(base.get("num_officers") or 1) // 2),
                    hi=max(16, int(base.get("num_officers") or 16) + 4),
                    shift_length_hours=float(base.get("shift_length_hours") or 0) or None,
                    annual_hours_target=float(base.get("annual_hours_target") or 0) or None,
                    annual_hours_variance=float(base.get("annual_hours_variance") or 40),
                    rotation_variations=list(base.get("rotation_variations") or []) or None,
                    shift_starts=list(base.get("shift_starts") or []) or None,
                    coverage_247=int(base.get("coverage_247") or 0),
                    extra_windows=list(base.get("extra_windows") or []) or None,
                    night_minimum=base.get("night_minimum"),
                    cancel_check=cancel_ev.is_set,
                )
            )
        except Exception as exc:
            set_summary(f"Min-N failed: {exc}")
            ui.notify(str(exc), type="negative")
            _set_search_buttons(False)
            return
        _set_search_buttons(False)
        state["opt_cancel"] = None
        lines = [result.get("message") or "Min officers", ""]
        for t in result.get("trials") or []:
            st = t.get("best_starts") or []
            st_s = ",".join(str(s) for s in st) if isinstance(st, list) else ""
            lines.append(
                f"N={t.get('num_officers')}: "
                f"{'OK' if t.get('success') else 'NO'}" + (f" · starts={st_s}" if st_s else "")
            )
        best = result.get("best") or {}
        bst = best.get("shift_starts") or []
        if bst:
            lines.append("Best starts: " + (",".join(str(s) for s in bst) if isinstance(bst, list) else str(bst)))
        if result.get("cpsat_note"):
            lines.append(f"CP-SAT note: {result['cpsat_note']}")
        set_summary("\n".join(lines))
        if result.get("success") and result.get("min_officers"):
            officers.value = str(result["min_officers"])
            use_officers.value = True
            # Reflect LE pack that hard-OK'd (incl. 19:00 when used)
            if bst and isinstance(bst, list):
                try:
                    starts.value = ", ".join(str(s) for s in bst)
                    use_starts.value = True
                except Exception:
                    pass
            ui.notify(f"Min officers: {result['min_officers']}", type="positive")
        else:
            ui.notify(result.get("message") or "No min N", type="warning")

    async def run_whatif():
        if state.get("opt_running"):
            ui.notify("Search already running", type="warning")
            return
        kw = _optimizer_kwargs(require_hard_ok=True)
        if kw.get("error"):
            ui.notify("Check numeric fields", type="negative")
            return
        kw.pop("error", None)
        _set_search_buttons(True)
        set_summary("What-if: +1 officer…")
        try:
            result = await run.io_bound(lambda: what_if_staffing_delta(kw, delta_officers=1))
        except Exception as exc:
            set_summary(f"What-if failed: {exc}")
            _set_search_buttons(False)
            return
        _set_search_buttons(False)
        set_summary(
            f"{result.get('message')}\nBase: {result.get('base_message')}\nAlt (+1): {result.get('alt_message')}"
        )
        ui.notify(result.get("message") or "What-if done", type="info")

    return {
        "optimizer_kwargs": _optimizer_kwargs,
        "refresh_space_estimate": _refresh_space_estimate,
        "apply_opt_result": _apply_opt_result,
        "set_search_buttons": _set_search_buttons,
        "execute_opt": _execute_opt,
        "run_opt_inner": _run_opt,
        "run_opt": run_opt,
        "run_stage_wizard": run_stage_wizard,
        "run_compare": run_compare,
        "run_min_n": run_min_n,
        "run_whatif": run_whatif,
    }
