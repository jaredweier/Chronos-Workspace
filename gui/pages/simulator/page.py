"""Schedule Simulator — fixed constraint rows (no layout jump), hard search, publish."""

from __future__ import annotations

from nicegui import ui

from config import SIMULATOR_ROTATION_TYPES
from gui import session
from gui.pages.simulator.constraint_suggest_ui import bind_constraint_suggest
from gui.pages.simulator.form_logic import (
    constraint_priority_labels,
    human_metrics_lines,
    parse_shift_starts,
)
from gui.pages.simulator.form_state import bind_form_state
from gui.pages.simulator.helpers import (
    _HINT,
    _STEP_DONE,
    _STEP_OFF,
    _STEP_ON,
    _chip_html,
    _set_enabled,
)
from gui.pages.simulator.kpi_panel import paint_simulator_kpis
from gui.pages.simulator.manual_editor import render_manual_editor
from gui.pages.simulator.optimizer_actions import bind_optimizer_actions
from gui.pages.simulator.publish_panel import render_publish_panel
from gui.pages.simulator.ranked_render import bind_ranked_render
from gui.pages.simulator.requirements_form import render_requirements_form
from gui.pages.simulator.results_panel import render_results_panel_tools
from gui.pages.simulator.search_hero import build_search_hero
from gui.pages.simulator.side_actions import bind_side_actions
from gui.pages.simulator.stepper_rail import render_stepper_rail
from gui.pages.simulator.styles import apply_simulator_css
from gui.shell import layout, page_header
from gui.ui_patterns import skeleton_block, throttled
from logic import (
    format_optimized_plan_view,
    save_last_optimized_plan,
)
from logic.optimizer_features import (
    default_weight_map,
    format_checklist_line,
    near_miss_deltas,
    weights_from_sliders,
    why_best_lines,
)
from logic.plan_explain import explain_ranked_option


def render_simulator() -> None:
    _placeholder_rot = SIMULATOR_ROTATION_TYPES[0] if SIMULATOR_ROTATION_TYPES else ""

    def body() -> None:
        apply_simulator_css(ui)
        if not session.can("simulator.use"):
            page_header("Schedule Simulator", "Permission Required", kicker="Command")
            ui.html(
                '<div class="alert alert-warn">Schedule Simulator Is Limited To Supervisors.</div>',
                sanitize=False,
            )
            return

        page_header(
            "Schedule Simulator",
            "Requirements → find best → publish",
            kicker="Command",
        )

        state: dict = {
            "result": None,
            "config": None,
            "ranked": [],
            "selected_rank": 0,
            "compare_a": None,
            "compare_b": None,
            "opt_result": None,
            "windows": [],
            "hard_mode": True,
            "step": 1,
            "opt_running": False,
            "opt_cancel": None,
            "opt_t0": None,
            # Higher index = lower priority; first items weigh more for near-miss ranking
            "constraint_priority": [
                "coverage_247",
                "windows",
                "gaps",
                "flsa",
                "annual",
                "headcount",
            ],
            "space_estimate": None,
            "pending_opt_kw": None,
            "form_undo": [],
            "constraint_weights": default_weight_map(),
            "auto_find_after_preset": False,
            "manual_grid": None,
            "manual_days": 14,
            "restoring_form": False,
            "suppress_suggest": False,
            # standard = interactive UAT band; deep = exhaustive free-N 4–20 + 28-day
            "search_depth": "standard",
            "max_step_reached": 1,
        }
        step_labels: dict = {}
        step_panels: dict = {}
        sim_page = ui.element("div").classes("sim-page w-full")

        def go_step(n: int) -> None:
            state["step"] = n
            try:
                state["max_step_reached"] = max(int(state.get("max_step_reached") or 1), n)
            except Exception:
                state["max_step_reached"] = n
            for i in (1, 2, 3, 4):
                if step_labels.get(i):
                    if i == n:
                        cls = _STEP_ON
                    elif i < n or (i <= int(state.get("max_step_reached") or 1) and i != n):
                        cls = _STEP_DONE if i < n else _STEP_OFF
                    else:
                        cls = _STEP_OFF
                    # visited but not current → done styling only for prior steps
                    if i < n:
                        cls = _STEP_DONE
                    elif i == n:
                        cls = _STEP_ON
                    else:
                        cls = _STEP_OFF
                    step_labels[i].classes(replace=cls)
                if step_panels.get(i):
                    step_panels[i].style("display:block" if i == n else "display:none")
            if n == 2:
                try:
                    _refresh_space_estimate()
                except Exception:
                    pass
                try:
                    _refresh_lock_strip()
                except Exception:
                    pass
            if n == 3:
                try:
                    _manual_refresh_view()
                except Exception:
                    pass
            try:
                _refresh_lock_progress()
            except Exception:
                pass

        with sim_page:
            # Outer workflow rail (package). Inner Phase 1–3 is under Requirements only.
            render_stepper_rail(state, step_labels, go_step)

            # Widget placeholders only — real values come from last saved constraints.
            # Do not treat these as product defaults when a snapshot exists.
            _req = render_requirements_form(
                state,
                step_panels,
                go_step,
                baseline_kwargs=lambda: _baseline_kwargs(),
                refresh_space_estimate=lambda: _refresh_space_estimate(),
                persist_form=lambda: _persist_form(),
                restore_form=lambda: _restore_form(),
                show_suggestions=lambda f: _show_constraint_suggestions(f),
            )
            use_start_date = _req["use_start_date"]
            sim_start_date = _req["sim_start_date"]
            use_rot_model = _req["use_rot_model"]
            rot_model_kind = _req["rot_model_kind"]
            _sync_rotation_model = _req["sync_rotation_model"]
            use_rotation = _req["use_rotation"]
            rotation = _req["rotation"]
            hint_rotation = _req["hint_rotation"]
            use_officers = _req["use_officers"]
            officers = _req["officers"]
            hint_officers = _req["hint_officers"]
            use_length = _req["use_length"]
            length = _req["length"]
            hint_length = _req["hint_length"]
            use_annual = _req["use_annual"]
            annual = _req["annual"]
            annual_var = _req["annual_var"]
            use_starts = _req["use_starts"]
            starts = _req["starts"]
            hint_starts = _req["hint_starts"]
            use_min_ps = _req["use_min_ps"]
            min_ps = _req["min_ps"]
            use_247 = _req["use_247"]
            cov247 = _req["cov247"]
            use_style = _req["use_style"]
            hint_style = _req["hint_style"]
            rot_style = _req["rot_style"]
            multi_catalog = _req["multi_catalog"]
            variations = _req["variations"]
            use_nearby = _req["use_nearby"]
            nearby_hops = _req["nearby_hops"]
            allow_offday = _req["allow_offday"]
            use_certs = _req["use_certs"]
            cert_codes = _req["cert_codes"]
            use_fatigue = _req["use_fatigue"]
            min_rest = _req["min_rest"]
            max_consec = _req["max_consec"]
            use_flsa = _req["use_flsa"]
            flsa_days = _req["flsa_days"]
            use_windows = _req["use_windows"]
            win_inputs = _req["win_inputs"]
            _refresh_win_list = _req["refresh_win_list"]
            btn_q_min = _req["btn_q_min"]
            btn_q_will = _req["btn_q_will"]
            btn_q_plus = _req["btn_q_plus"]
            _refresh_lock_progress = _req["refresh_lock_progress"]

        # ── Step 2 ─────────────────────────────────────────────────────────
        step2 = ui.element("div").classes("w-full").style("display:none")
        step_panels[2] = step2
        with step2:
            # Decision hero (package) — wire click handlers after action defs
            _hero = build_search_hero(state)
            lock_strip = _hero["lock_strip"]
            btn_opt = _hero["btn_opt"]
            btn_gen = _hero["btn_gen"]
            search_depth = _hero["search_depth"]
            mode_label = _hero["mode_label"]
            btn_compare = _hero["btn_compare"]
            compare_quick = _hero["compare_quick"]
            btn_min_n = _hero["btn_min_n"]
            btn_whatif = _hero["btn_whatif"]
            btn_weekend_preset = _hero.get("btn_weekend_preset")
            btn_soften = _hero.get("btn_soften")
            btn_history = _hero.get("btn_history")
            search_status_host = _hero["search_status_host"]
            progress_bar = _hero["progress_bar"]
            search_spinner = _hero["search_spinner"]
            search_status = _hero["search_status"]
            search_mode_badge = _hero.get("search_mode_badge")
            kpi_host = _hero["kpi_host"]
            skeleton_host = ui.element("div").classes("q-mb-sm")
            skeleton_host.set_visibility(False)
            with skeleton_host:
                # Native NiceGUI skeleton (llms.txt) + Chronos shimmer fallback
                ui.skeleton(type="QToolbar").classes("w-full q-mb-xs")
                ui.skeleton(type="QToolbar").classes("w-full q-mb-xs")
                ui.skeleton(type="text").classes("w-3/4")
                skeleton_block(rows=2, label="Searching layouts…")
            space_warn = ui.element("div").classes("sim-space-warn risk-medium")
            with space_warn:
                ui.label("Select requirements, then open Find best — space size appears here.")

            prio_labels = constraint_priority_labels()
            prio_col = ui.column().classes("w-full gap-1 q-mb-sm")
            weight_sliders: dict = {}

            def _render_priority():
                prio_col.clear()
                order = list(state.get("constraint_priority") or [])
                with prio_col:
                    for i, key in enumerate(order):
                        with ui.row().classes("gap-2 items-center flex-wrap"):
                            ui.label(f"{i + 1}. {prio_labels.get(key, key)}").style("color:#D6E6FF;min-width:16rem")

                            def _up(idx=i):
                                o = list(state["constraint_priority"])
                                if idx > 0:
                                    o[idx - 1], o[idx] = o[idx], o[idx - 1]
                                    state["constraint_priority"] = o
                                    _render_priority()

                            def _dn(idx=i):
                                o = list(state["constraint_priority"])
                                if idx < len(o) - 1:
                                    o[idx + 1], o[idx] = o[idx], o[idx + 1]
                                    state["constraint_priority"] = o
                                    _render_priority()

                            ui.button("↑", on_click=_up).props("dense flat no-caps").classes("btn-ghost")
                            ui.button("↓", on_click=_dn).props("dense flat no-caps").classes("btn-ghost")

            with ui.expansion(
                "Advanced: priority & weights (near-miss ranking)",
                icon="tune",
            ).classes("sim-adv w-full"):
                ui.label(
                    "When no perfect match, reorder priority (top = most important) "
                    "and tune weights for near-miss ranking."
                ).style(_HINT)
                _render_priority()
                ui.label("Constraint weights").style("color:#E8EDF4;font-weight:600;margin-top:8px")
                with ui.column().classes("w-full gap-1 q-mb-sm"):
                    for wkey, wlabel in (
                        ("coverage_247", "24/7"),
                        ("windows", "Windows"),
                        ("gaps", "Gaps"),
                        ("flsa", "FLSA"),
                        ("annual", "Annual"),
                        ("headcount", "Fewer officers"),
                    ):
                        with ui.row().classes("gap-2 items-center flex-wrap"):
                            ui.label(wlabel).style("color:#D6E6FF;min-width:7rem")
                            sl = (
                                ui.slider(
                                    min=0,
                                    max=120,
                                    value=float((state.get("constraint_weights") or {}).get(wkey, 50)),
                                    step=5,
                                )
                                .classes("w-64")
                                .props("label dark")
                            )
                            weight_sliders[wkey] = sl

                            def _sync_w(e=None, k=wkey, s=sl):
                                state["constraint_weights"] = weights_from_sliders(
                                    {
                                        **(state.get("constraint_weights") or {}),
                                        k: float(s.value or 0),
                                    }
                                )

                            sl.on_value_change(_sync_w)

            def set_space_warn(text: str, *, risk: str = "low"):
                space_warn.clear()
                rk = risk if risk in ("low", "medium", "high", "extreme") else "medium"
                space_warn.classes(replace=f"sim-space-warn risk-{rk}")
                color = {
                    "low": "#A7F3D0",
                    "medium": "#FDE68A",
                    "high": "#FDBA74",
                    "extreme": "#FCA5A5",
                }.get(rk, "#FDE68A")
                with space_warn:
                    ui.label(text or "—").style(f"color:{color};white-space:pre-wrap;line-height:1.45")

            def _refresh_lock_strip():
                lock_strip.clear()
                pairs = [
                    ("Rotation model", bool(use_rotation.value or use_style.value)),
                    ("Officers", bool(use_officers.value)),
                    ("Length", bool(use_length.value)),
                    ("Annual", bool(use_annual.value)),
                    ("Starts", bool(use_starts.value)),
                    ("Min/shift", bool(use_min_ps.value)),
                    ("24/7", bool(use_247.value)),
                    ("Windows", bool(use_windows.value)),
                ]
                with lock_strip:
                    for lab, locked in pairs:
                        # Native NiceGUI chips (Quasar) — clearer than custom HTML
                        chip = ui.chip(
                            f"{lab} · {'LOCK' if locked else 'FREE'}",
                            icon="lock" if locked else "lock_open",
                        ).props("dense outline")
                        if locked:
                            chip.props("color=positive text-color=white")
                            chip.classes("sim-ng-chip-on")
                        else:
                            chip.props("color=warning text-color=dark")
                            chip.classes("sim-ng-chip-free")
                    depth = state.get("search_depth") or "standard"
                    ui.chip(
                        f"Search · {depth.upper()}",
                        icon="speed",
                    ).props("dense outline color=primary")

            def _paint_kpis(
                *,
                hard_ok=None,
                officers_n=None,
                layouts=None,
                annual_avg=None,
                window_fails=None,
                rest_fails=None,
                mode_text: str = "",
                search_truncated=None,
                search_exhaustive=None,
            ):
                paint_simulator_kpis(
                    kpi_host,
                    hard_ok=hard_ok,
                    officers_n=officers_n,
                    layouts=layouts,
                    annual_avg=annual_avg,
                    window_fails=window_fails,
                    rest_fails=rest_fails,
                    mode_text=mode_text,
                    search_truncated=search_truncated,
                    search_exhaustive=search_exhaustive,
                )

            ui.html('<div class="sim-section-title">Summary</div>', sanitize=False)
            summary_box = ui.element("div").classes("sim-result-panel")
            ui.html(
                '<div class="sim-section-title" style="margin-top:12px">Why #1 / tips</div>',
                sanitize=False,
            )
            why_box = ui.element("div").classes("sim-result-panel").style("min-height:3rem;max-height:10rem")

            # Secondary tools grouped into 4 menus (Phase 6) — every former
            # strip button lives on, one level down. Handlers are late-bound
            # closures: defined further below in body(), resolved at click.
            with ui.row().classes("gap-2 flex-wrap q-mt-sm items-center"):
                btn_apply_month = (
                    ui.button("Apply winner → draft month").classes("btn-primary").props("no-caps unelevated dense")
                )
                with (
                    ui.dropdown_button("Compare", icon="compare_arrows")
                    .classes("btn-ghost")
                    .props("no-caps outline dense")
                ):
                    ui.menu_item("Diff A vs B", on_click=lambda: run_diff_ab())
                    ui.menu_item("Sensitivity (+N / night)", on_click=lambda: run_sensitivity())
                    ui.menu_item("CP-SAT (small N)", on_click=lambda: run_cpsat_small())
                with (
                    ui.dropdown_button("Explain", icon="psychology").classes("btn-ghost").props("no-caps outline dense")
                ):
                    ui.menu_item("Plain English explain", on_click=lambda: run_plain_explain())
                    ui.menu_item("Fairness report", on_click=lambda: run_fairness())
                    ui.menu_item("Weekend heat", on_click=lambda: show_weekend_heat())
                    ui.menu_item("Heat map (PNG)", on_click=lambda: do_heat())
                    ui.menu_item("Window failures", on_click=lambda: do_window_drill())
                with ui.dropdown_button("Export", icon="ios_share").classes("btn-ghost").props("no-caps outline dense"):
                    ui.menu_item("Options CSV", on_click=lambda: export_options())
                    ui.menu_item("Search audit JSON", on_click=lambda: export_audit())
                    ui.menu_item("Staffing memo", on_click=lambda: export_memo())
                    ui.menu_item("Config JSON", on_click=lambda: export_config())
                    ui.menu_item("Share best (.eml)", on_click=lambda: do_share())
                    ui.menu_item("Copy summary", on_click=lambda: copy_summary())
                with (
                    ui.dropdown_button("Scenarios", icon="inventory_2")
                    .classes("btn-ghost")
                    .props("no-caps outline dense")
                ):
                    ui.menu_item("Save → A", on_click=lambda: save_slot("A"))
                    ui.menu_item("Save → B", on_click=lambda: save_slot("B"))
                    ui.menu_item("Save → C", on_click=lambda: save_slot("C"))
                    ui.menu_item("Open A/B/C", on_click=lambda: show_slots())
                    ui.menu_item("Pin selected", on_click=lambda: do_pin())
                    ui.menu_item("Pinned list", on_click=lambda: show_pins())
                    ui.menu_item("Lock selected as seed", on_click=lambda: lock_selected_seed())
                    ui.menu_item("Import config JSON", on_click=lambda: import_config())
                    ui.menu_item("Import live constraints", on_click=lambda: run_import_live())

            # Decision table paints here after every search (primary output)
            decision_host = ui.element("div").classes("w-full q-mt-sm")

            # Splitter: ranked options | plan detail (NiceGUI layout primitive)
            with ui.splitter(value=52).classes("w-full sim-split q-mt-sm") as result_split:
                with result_split.before:
                    ui.html(
                        '<div class="sim-section-title">Coverage options</div>',
                        sanitize=False,
                    )
                    ui.label("Select one · mark A/B for diff · click card to load").style(_HINT)
                    # scroll_area + refreshable = NiceGUI llms.txt list pattern
                    with ui.scroll_area().classes("w-full").style("height: 22rem; max-height: 50vh;"):

                        @ui.refreshable
                        def options_ui() -> None:
                            ranked = list(state.get("ranked") or [])
                            selected = int(state.get("selected_rank") or 1)
                            if not ranked:
                                ui.html(
                                    '<div class="empty-state">'
                                    '<div class="empty-state-title">No coverage options yet</div>'
                                    '<div class="empty-state-hint">'
                                    "Run Find best — ranked plans appear here with hard/near-miss chips."
                                    "</div></div>",
                                    sanitize=False,
                                )
                                return
                            for row in ranked[:10]:
                                rank = int(row.get("rank") or 0)
                                detail_lines = explain_ranked_option(row)
                                check = format_checklist_line(row)
                                if check:
                                    detail_lines = [check] + detail_lines
                                deltas = near_miss_deltas(row)
                                if deltas and not row.get("hard_constraints_ok"):
                                    detail_lines.append("Missed by: " + "; ".join(deltas[:3]))
                                if row.get("suggestions"):
                                    detail_lines.append(row.get("suggestions"))
                                summary = row.get("summary") or (
                                    f"{row.get('rotation_type')} · "
                                    f"{row.get('num_officers')} officers · "
                                    f"Min {row.get('min_per_shift')} per shift"
                                )
                                body = "\n".join(detail_lines[:8]) if detail_lines else summary
                                hard = row.get("hard_constraints_ok")
                                if hard is None:
                                    hard = (row.get("human_metrics") or {}).get("hard_constraints_ok")
                                active = rank == selected
                                is_a = state.get("compare_a") is row or (
                                    (state.get("compare_a") or {}).get("rank") == rank and state.get("compare_a")
                                )
                                is_b = state.get("compare_b") is row or (
                                    (state.get("compare_b") or {}).get("rank") == rank and state.get("compare_b")
                                )
                                chips = []
                                if active:
                                    chips.append(_chip_html("Selected", "info"))
                                if hard is True:
                                    chips.append(_chip_html("Hard OK", "ok"))
                                elif hard is False:
                                    chips.append(_chip_html("Near-miss", "warn"))
                                mrow = row.get("metrics") or row.get("human_metrics") or {}
                                try:
                                    wf = int(mrow.get("extra_window_failures") or 0)
                                    if wf > 0:
                                        chips.append(_chip_html(f"Win×{wf}", "warn"))
                                except (TypeError, ValueError):
                                    pass
                                try:
                                    rf = int(mrow.get("rest_failures") or 0)
                                    if rf > 0:
                                        chips.append(_chip_html(f"Rest×{rf}", "warn"))
                                except (TypeError, ValueError):
                                    pass
                                try:
                                    c247f = int(mrow.get("coverage_247_failures") or 0)
                                    if c247f > 0:
                                        chips.append(_chip_html(f"24/7×{c247f}", "warn"))
                                except (TypeError, ValueError):
                                    pass
                                chips.append(_chip_html(f"N={row.get('num_officers') or '—'}", "info"))
                                if row.get("shift_length_hours") is not None:
                                    chips.append(_chip_html(f"{row.get('shift_length_hours')}h", "info"))
                                if is_a:
                                    chips.append(_chip_html("Diff A", "info"))
                                if is_b:
                                    chips.append(_chip_html("Diff B", "info"))

                                def _select(r=row, rk=rank):
                                    state["selected_row"] = r
                                    state["selected_rank"] = rk
                                    _apply_ranked_option(r)
                                    options_ui.refresh()
                                    try:
                                        set_why("\n".join(why_best_lines({"best": r, "ranked": ranked})))
                                    except Exception:
                                        pass
                                    try:
                                        m = r.get("metrics") or r.get("human_metrics") or {}
                                        _paint_kpis(
                                            hard_ok=r.get("hard_constraints_ok"),
                                            officers_n=r.get("num_officers"),
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

                                def _mark_a(r=row):
                                    state["compare_a"] = r
                                    ui.notify(f"Option {r.get('rank')} → Diff A", type="info")
                                    options_ui.refresh()

                                def _mark_b(r=row):
                                    state["compare_b"] = r
                                    ui.notify(f"Option {r.get('rank')} → Diff B", type="info")
                                    options_ui.refresh()

                                card = ui.element("div").classes(
                                    "sim-option-card active" if active else "sim-option-card"
                                )
                                card.props(
                                    f'tabindex="0" role="button" '
                                    f'aria-pressed="{"true" if active else "false"}" '
                                    f'aria-label="Coverage option {rank}"'
                                )
                                with card:
                                    ui.html(
                                        f'<div class="sim-option-head">'
                                        f'<span class="sim-option-rank">#{rank}</span>'
                                        f'<span class="sim-option-title">Option {rank}</span>'
                                        f"{''.join(chips)}</div>",
                                        sanitize=False,
                                    )
                                    ui.label(body).classes("sim-option-body")
                                    with ui.row().classes("gap-2 q-mt-xs flex-wrap sim-option-actions"):
                                        ui.button("Load", icon="check", on_click=_select).classes("btn-primary").props(
                                            "dense no-caps unelevated"
                                        )
                                        ui.button("Mark A", on_click=_mark_a).classes("btn-ghost").props(
                                            "dense no-caps outline"
                                        )
                                        ui.button("Mark B", on_click=_mark_b).classes("btn-ghost").props(
                                            "dense no-caps outline"
                                        )
                                card.on("click", _select)
                                card.on("keydown.enter", _select)

                        options_ui()
                with result_split.after:
                    ui.html(
                        '<div class="sim-section-title">Plan detail</div>',
                        sanitize=False,
                    )
                    with ui.scroll_area().classes("w-full").style("height: 22rem; max-height: 50vh;"):
                        plan_box = ui.element("div").classes("sim-result-panel")

            def _ui_safe(fn) -> None:
                """Ignore updates after client disconnect (Cloudflare tunnel blips)."""
                try:
                    fn()
                except RuntimeError as exc:
                    msg = str(exc).lower()
                    if "deleted" in msg or "client" in msg:
                        return
                    raise
                except Exception:
                    return

            def set_summary(text: str):
                def _do():
                    summary_box.clear()
                    with summary_box:
                        ui.label(text or "—").style("color:#E8EDF4;white-space:pre-wrap;line-height:1.5")

                _ui_safe(_do)

            def set_why(text: str = ""):
                def _do():
                    why_box.clear()
                    with why_box:
                        ui.label(text or "—").style(
                            "color:#D6E6FF;white-space:pre-wrap;line-height:1.45;font-size:0.9rem"
                        )

                _ui_safe(_do)

            # Bound rendered plan text so one label can't blow up a WebSocket
            # frame (the raised 10MB cap in gui/app.py stays as safety net,
            # but should no longer be load-bearing). Full text stays in
            # state["plan_full_text"] server-side for exports.
            _PLAN_RENDER_CAP = 60_000  # chars ≈ well under default 1MB frame

            def set_plan(text: str):
                def _do():
                    full = text or "—"
                    state["plan_full_text"] = full
                    shown = full
                    if len(full) > _PLAN_RENDER_CAP:
                        shown = (
                            full[:_PLAN_RENDER_CAP]
                            + "\n… (view truncated — use Export › Options CSV / Staffing memo for the full plan)"
                        )
                    plan_box.clear()
                    with plan_box:
                        ui.label(shown).style("color:#D6E6FF;white-space:pre-wrap;line-height:1.45")

                _ui_safe(_do)

            set_summary("Run Find best or Generate schedule.")
            set_plan(
                "Plan detail appears after a successful run.\n"
                "Ranked options and Why #1 explain hard-constraint tradeoffs."
            )
            _paint_kpis(mode_text="Hard constraints · ready")

        # ── Step 3 · Manual Build (package) ────────────────────────────────
        # Callables resolve at click time after _baseline_kwargs is defined below.
        _man = render_manual_editor(
            state,
            step_panels,
            go_step,
            baseline_kwargs=lambda: _baseline_kwargs(),
            current_config=lambda: _current_config(),
            parse_starts=lambda: _parse_starts(),
            set_plan=lambda t: set_plan(t),
            set_summary=lambda t: set_summary(t),
            session=session,
            save_last_optimized_plan=save_last_optimized_plan,
            format_optimized_plan_view=format_optimized_plan_view,
            length_input=length,
            officers_input=officers,
        )
        _manual_refresh_view = _man["refresh"]

        # ── Step 4 · Publish (package) ─────────────────────────────────────
        step4, _pub = render_publish_panel(state, go_step)
        step_panels[4] = step4
        impl_date = _pub["impl_date"]
        apply_officers = _pub["apply_officers"]
        force_regen = _pub["force_regen"]
        save_defaults = _pub["save_defaults"]
        set_action_log = _pub["set_action_log"]
        btn_impl = _pub["btn_impl"]
        btn_preview = _pub["btn_preview"]
        btn_apply_stay = _pub["btn_apply_stay"]
        btn_apply_pub = _pub["btn_apply_pub"]
        btn_save = _pub["btn_save"]
        btn_csv = _pub["btn_csv"]
        btn_bid = _pub.get("btn_bid")

        # ── Logic helpers ──────────────────────────────────────────────────

        def _parse_starts(raw: str | None = None):
            text = raw if raw is not None else (starts.value or "")
            return parse_shift_starts(text)

        def _style_value() -> str:
            if not use_style.value:
                return ""
            return "rotating" if (rot_style.value or "").lower().startswith("rotat") else "fixed"

        def _var_list() -> list:
            if not use_style.value:
                return []
            return [p.strip() for p in (variations.value or "").split("|") if p.strip()]

        # ("Suggest Next Constraint" button removed in the declutter pass —
        # per-field suggestions still fire on lock/focus via
        # _show_constraint_suggestions.)

        def _nums():
            """Parse locked fields only. Empty locked field → error. Unlocked → None."""
            try:
                n = None
                if use_officers.value:
                    raw = (officers.value or "").strip()
                    if not raw:
                        return None, None, None, None, None, None, None, "Officer count required when locked"
                    n = int(raw)
                ln = None
                if use_length.value:
                    raw = (length.value or "").strip()
                    if not raw:
                        return None, None, None, None, None, None, None, "Shift length required when locked"
                    ln = float(raw)
                an = None
                av = None
                if use_annual.value:
                    raw_a = (annual.value or "").strip()
                    raw_v = (annual_var.value or "").strip()
                    if not raw_a:
                        return None, None, None, None, None, None, None, "Annual hours required when locked"
                    an = float(raw_a)
                    av = float(raw_v) if raw_v else 0.0
                mp = None
                if use_min_ps.value:
                    raw = (min_ps.value or "").strip()
                    if not raw:
                        return None, None, None, None, None, None, None, "Min per shift required when locked"
                    mp = int(raw)
                c247 = None
                if use_247.value:
                    raw = (cov247.value or "").strip()
                    if not raw:
                        return None, None, None, None, None, None, None, "24/7 minimum required when locked"
                    c247 = int(raw)
                fd = None
                if use_flsa.value:
                    raw = (flsa_days.value or "").strip()
                    fd = int(raw) if raw else 28
                return n, ln, an, av, mp, c247, fd, None
            except ValueError as exc:
                return None, None, None, None, None, None, None, str(exc)

        def _parse_nearby_hops() -> int:
            if not bool(use_nearby.value):
                return 0
            try:
                raw = (nearby_hops.value or "").strip()
                if not raw:
                    return 0
                return max(0, min(6, int(raw)))
            except (TypeError, ValueError):
                return 0

        def _baseline_kwargs() -> dict:
            n, ln, an, av, mp, c247, fd, err = _nums()
            if err:
                return {"error": err}
            st = _parse_starts() if use_starts.value else []
            if use_starts.value and not st:
                return {"error": "Shift starts required when locked"}
            if use_rotation.value and not (rotation.value or "").strip():
                return {"error": "Squad preset required when Rotation model is Given + Squad"}
            if use_style.value and not _var_list():
                return {"error": "On/off patterns required when Rotation model is Given + Multi-block"}
            # Unlocked dimensions: free for search / neutral for single sim
            # Multi-block path clears squad duty; squad path clears multi-block duty.
            return {
                "rotation_type": (rotation.value if use_rotation.value else (rotation.value or _placeholder_rot)),
                "num_officers": int(n) if use_officers.value and n and n >= 1 else 0,
                "auto_min_officers": not use_officers.value or not n or n < 1,
                "shift_length_hours": float(ln) if use_length.value and ln is not None else None,
                "annual_hours_target": float(an) if use_annual.value and an is not None else None,
                "annual_hours_variance": float(av) if use_annual.value and av is not None else None,
                "annual_hours_hard": bool(use_annual.value and state.get("hard_mode", True)),
                "shift_starts": st if use_starts.value else None,
                "min_per_shift": int(mp) if use_min_ps.value and mp is not None else 1,
                "simulation_days": 56,
                "coverage_247": int(c247) if use_247.value and c247 is not None else 0,
                "sim_start_date": sim_start_date.value if use_start_date.value else None,
                "avoid_flsa_overtime": bool(use_flsa.value),
                "flsa_work_period_days": int(fd) if use_flsa.value and fd is not None else 28,
                "rotation_style": _style_value() if use_style.value else "",
                "rotation_variations": _var_list() if use_style.value else [],
                "use_extra_windows": bool(use_windows.value and state["windows"]),
                "extra_windows": list(state["windows"]) if use_windows.value else [],
                "apply_department_rules": False,
                "stagger_phases": True,
                "nearby_start_hops": _parse_nearby_hops(),
                "allow_offday_coverage": bool(allow_offday.value),
                "min_rest_hours": (float((min_rest.value or "0").strip() or 0) if use_fatigue.value else 0.0),
                "max_consecutive_work_days": (
                    int(float((max_consec.value or "0").strip() or 0)) if use_fatigue.value else 0
                ),
                "required_cert_codes": (
                    [c.strip() for c in (cert_codes.value or "").replace(";", ",").split(",") if c.strip()]
                    if use_certs.value
                    else []
                ),
            }

        def _current_config():
            base = _baseline_kwargs()
            base.pop("error", None)
            base.pop("auto_min_officers", None)
            base.pop("stagger_phases", None)
            return base

        def _human_metrics(metrics: dict) -> list[str]:
            return human_metrics_lines(metrics)

        _cs = bind_constraint_suggest(
            state,
            {
                "use_rotation": use_rotation,
                "rotation": rotation,
                "use_officers": use_officers,
                "officers": officers,
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
                "variations": variations,
                "rot_style": rot_style,
                "multi_catalog": multi_catalog,
                "use_windows": use_windows,
                "use_nearby": use_nearby,
                "nearby_hops": nearby_hops,
                "allow_offday": allow_offday,
                "use_flsa": use_flsa,
                "flsa_days": flsa_days,
                "use_fatigue": use_fatigue,
                "min_rest": min_rest,
                "max_consec": max_consec,
                "use_certs": use_certs,
                "cert_codes": cert_codes,
                "set_enabled": _set_enabled,
                "persist_form": lambda: _persist_form(),
                "refresh_space_estimate": lambda: _refresh_space_estimate(),
                "hint_rotation": hint_rotation,
                "hint_officers": hint_officers,
                "hint_length": hint_length,
                "hint_starts": hint_starts,
                "hint_style": hint_style,
                "win_inputs": win_inputs,
                "refresh_win_list": _refresh_win_list,
            },
        )
        _constraint_context = _cs["constraint_context"]
        _apply_suggest_values = _cs["apply_suggest_values"]
        _show_constraint_suggestions = _cs["show_constraint_suggestions"]
        _on_lock_with_suggest = _cs["on_lock_with_suggest"]
        _en_rot = _cs["en_rot"]
        _en_off = _cs["en_off"]
        _en_len = _cs["en_len"]
        _en_ann = _cs["en_ann"]
        _en_st = _cs["en_st"]
        _en_mp = _cs["en_mp"]
        _en_247 = _cs["en_247"]
        _en_style = _cs["en_style"]
        _en_near = _cs["en_near"]
        _en_flsa = _cs["en_flsa"]
        _on_windows_lock = _cs["on_windows_lock"]
        _on_offday_lock = _cs["on_offday_lock"]
        _focus_suggest = _cs["focus_suggest"]
        _suggest_next_unlocked = _cs["suggest_next_unlocked"]

        _rr = bind_ranked_render(
            state,
            {
                "rotation": rotation,
                "use_rotation": use_rotation,
                "use_rot_model": use_rot_model,
                "rot_model_kind": rot_model_kind,
                "sync_rotation_model": _sync_rotation_model,
                "officers": officers,
                "min_ps": min_ps,
                "length": length,
                "annual": annual,
                "annual_var": annual_var,
                "starts": starts,
                "variations": variations,
                "use_style": use_style,
                "use_officers": use_officers,
                "use_starts": use_starts,
                "use_length": use_length,
                "use_annual": use_annual,
                "use_fatigue": use_fatigue,
                "min_rest": min_rest,
                "max_consec": max_consec,
                "cov247": cov247,
                "baseline_kwargs": _baseline_kwargs,
                "current_config": _current_config,
                "human_metrics": _human_metrics,
                "paint_kpis": _paint_kpis,
                "constraint_context": _constraint_context,
                "persist_form": lambda: _persist_form(),
                "set_enabled": _set_enabled,
                "set_summary": lambda t: set_summary(t),
                "set_why": lambda t="": set_why(t),
                "set_plan": lambda t: set_plan(t),
                "options_ui": options_ui,
                "decision_host": decision_host,
                "session": session,
                "run_opt": lambda **kw: _run_opt(**kw),
                "en_off": lambda on: _en_off(on),
                "en_st": lambda on: _en_st(on),
                "en_len": lambda on: _en_len(on),
                "en_ann": lambda on: _en_ann(on),
                "refresh_win_list": _refresh_win_list,
                "parse_starts": _parse_starts,
                "nums": _nums,
                "mode_label": mode_label,
            },
        )
        _load_option = _rr["load_option"]
        _run_stress_test = _rr["run_stress_test"]
        _paint_decision_table = _rr["paint_decision_table"]
        _render_ranked = _rr["render_ranked"]
        _apply_ranked_option = _rr["apply_ranked_option"]
        _apply_relaxation = _rr["apply_relaxation"]
        _show_no_match_dialog = _rr["show_no_match_dialog"]
        _precheck_conflicts = _rr["precheck_conflicts"]

        # Optimizer actions (package) — after form + chrome + ranked helpers exist
        _oa = bind_optimizer_actions(
            state,
            {
                "use_starts": use_starts,
                "use_length": use_length,
                "use_officers": use_officers,
                "officers": officers,
                "use_rotation": use_rotation,
                "rotation": rotation,
                "use_min_ps": use_min_ps,
                "use_annual": use_annual,
                "annual": annual,
                "annual_var": annual_var,
                "use_247": use_247,
                "use_start_date": use_start_date,
                "sim_start_date": sim_start_date,
                "use_flsa": use_flsa,
                "use_windows": use_windows,
                "use_style": use_style,
                "allow_offday": allow_offday,
                "use_fatigue": use_fatigue,
                "min_rest": min_rest,
                "max_consec": max_consec,
                "starts": starts,
                "compare_quick": compare_quick,
                "nums": _nums,
                "parse_starts": _parse_starts,
                "style_value": _style_value,
                "var_list": _var_list,
                "parse_nearby_hops": _parse_nearby_hops,
                "baseline_kwargs": _baseline_kwargs,
                "constraint_context": _constraint_context,
                "current_config": _current_config,
                "paint_kpis": _paint_kpis,
                "render_ranked": _render_ranked,
                "apply_ranked_option": _apply_ranked_option,
                "show_no_match_dialog": _show_no_match_dialog,
                "set_space_warn": set_space_warn,
                # Thunks: page rebinds set_summary later for copy-buffer tracking
                "set_summary": lambda text: set_summary(text),
                "set_why": lambda text="": set_why(text),
                "btn_opt": btn_opt,
                "btn_gen": btn_gen,
                "btn_compare": btn_compare,
                "btn_min_n": btn_min_n,
                "btn_whatif": btn_whatif,
                "search_spinner": search_spinner,
                "skeleton_host": skeleton_host,
                "search_status": search_status,
                "search_status_host": search_status_host,
                "progress_bar": progress_bar,
                "mode_label": mode_label,
                "options_ui": options_ui,
                "search_mode_badge": search_mode_badge,
            },
        )
        _optimizer_kwargs = _oa["optimizer_kwargs"]
        _refresh_space_estimate = _oa["refresh_space_estimate"]
        _apply_opt_result = _oa["apply_opt_result"]
        _set_search_buttons = _oa["set_search_buttons"]
        _execute_opt = _oa["execute_opt"]
        _run_opt = _oa["run_opt_inner"]
        run_opt = _oa["run_opt"]
        run_compare = _oa["run_compare"]
        run_min_n = _oa["run_min_n"]
        run_whatif = _oa["run_whatif"]

        _fs = bind_form_state(
            state,
            {
                "officers": officers,
                "length": length,
                "annual": annual,
                "annual_var": annual_var,
                "starts": starts,
                "min_ps": min_ps,
                "variations": variations,
                "use_officers": use_officers,
                "use_length": use_length,
                "use_starts": use_starts,
                "use_247": use_247,
                "use_windows": use_windows,
                "use_min_ps": use_min_ps,
                "use_rotation": use_rotation,
                "use_style": use_style,
                "use_rot_model": use_rot_model,
                "rot_model_kind": rot_model_kind,
                "sync_rotation_model": _sync_rotation_model,
                "use_annual": use_annual,
                "use_flsa": use_flsa,
                "use_nearby": use_nearby,
                "nearby_hops": nearby_hops,
                "allow_offday": allow_offday,
                "use_certs": use_certs,
                "cert_codes": cert_codes,
                "use_fatigue": use_fatigue,
                "min_rest": min_rest,
                "max_consec": max_consec,
                "cov247": cov247,
                "flsa_days": flsa_days,
                "rot_style": rot_style,
                "multi_catalog": multi_catalog,
                "rotation": rotation,
                "man_days": _man.get("man_days"),
                "refresh_win_list": _refresh_win_list,
                "set_enabled": _set_enabled,
                "refresh_lock_strip": _refresh_lock_strip,
                "refresh_space_estimate": lambda: _refresh_space_estimate(),
            },
        )
        _form_payload = _fs["form_payload"]
        _apply_form_payload = _fs["apply_form_payload"]
        _push_undo = _fs["push_undo"]
        _persist_form = _fs["persist_form"]
        _restore_form = _fs["restore_form"]

        _sa = bind_side_actions(
            state,
            {
                "baseline_kwargs": _baseline_kwargs,
                "current_config": _current_config,
                "precheck_conflicts": _precheck_conflicts,
                "persist_form": lambda: _persist_form(),
                "paint_kpis": _paint_kpis,
                "apply_ranked_option": _apply_ranked_option,
                "form_payload": lambda: _form_payload(),
                "apply_form_payload": _apply_form_payload,
                "refresh_space_estimate": lambda: _refresh_space_estimate(),
                "human_metrics": _human_metrics,
                "set_summary": lambda t: set_summary(t),
                "set_why": lambda t="": set_why(t),
                "set_plan": lambda t: set_plan(t),
                "set_action_log": set_action_log,
                "impl_date": impl_date,
                "apply_officers": apply_officers,
                "force_regen": force_regen,
                "save_defaults": save_defaults,
                "btn_impl": btn_impl,
                "session": session,
                "officers": officers,
                "use_officers": use_officers,
                "length": length,
                "use_length": use_length,
                "starts": starts,
                "use_starts": use_starts,
                "min_ps": min_ps,
                "use_min_ps": use_min_ps,
                "variations": variations,
                "use_style": use_style,
                "use_rot_model": use_rot_model,
                "rot_model_kind": rot_model_kind,
                "sync_rotation_model": _sync_rotation_model,
                "go_step": go_step,
                "render_ranked": _render_ranked,
                "show_no_match_dialog": _show_no_match_dialog,
                "rotation": rotation,
                "use_windows": use_windows,
                "constraint_context": _constraint_context,
            },
        )
        run_sim = _sa["run_sim"]
        implement_plan = _sa["implement_plan"]
        save_scenario = _sa["save_scenario"]
        preview_publish = _sa["preview_publish"]
        export_csv = _sa["export_csv"]
        bid_from_sim = _sa["bid_from_sim"]
        export_options = _sa["export_options"]
        export_audit = _sa["export_audit"]
        run_diff_ab = _sa["run_diff_ab"]
        run_fairness = _sa["run_fairness"]
        run_plain_explain = _sa["run_plain_explain"]
        run_sensitivity = _sa["run_sensitivity"]
        run_import_live = _sa["run_import_live"]
        run_apply_winner_month = _sa["run_apply_winner_month"]
        run_cpsat_small = _sa["run_cpsat_small"]
        do_pin = _sa["do_pin"]
        do_share = _sa["do_share"]
        save_slot = _sa["save_slot"]
        lock_selected_seed = _sa["lock_selected_seed"]
        apply_stay = _sa["apply_stay"]
        apply_and_publish_step = _sa["apply_and_publish_step"]
        copy_summary = _sa["copy_summary"]
        export_config = _sa["export_config"]
        import_config = _sa["import_config"]
        export_memo = _sa["export_memo"]

        # Pins / history / heat / slots — package (after form apply exists)
        _result_tools = render_results_panel_tools(
            state,
            _apply_ranked_option,
            _apply_form_payload,
            set_plan,
            plan_box,
            _ui_safe,
            set_why,
        )
        show_pins = _result_tools["show_pins"]
        show_slots = _result_tools["show_slots"]
        do_heat = _result_tools["do_heat"]
        do_window_drill = _result_tools["do_window_drill"]
        show_weekend_heat = _result_tools["show_weekend_heat"]
        show_search_history = _result_tools["show_search_history"]

        # Track last summary text for copy
        _orig_set_summary = set_summary

        def set_summary(text: str):  # type: ignore[no-redef]
            state["last_summary"] = text or ""
            _orig_set_summary(text)

        try:
            _restore_form()
        except Exception:
            pass
        # Throttle form persist — typing storms hurt NiceGUI WS payload / storage
        _persist_throttled = throttled(_persist_form, 0.45)
        try:
            for w in (length, annual, annual_var, variations, officers, starts, min_ps):
                w.on_value_change(lambda e: _persist_throttled())
        except Exception:
            pass

        btn_gen.on_click(run_sim)
        btn_opt.on_click(run_opt)
        btn_compare.on_click(run_compare)
        btn_min_n.on_click(run_min_n)
        btn_whatif.on_click(run_whatif)

        def _apply_weekend_night_preset():
            """C2: Fri+Sat night windows + 24/7 example scenario (no baked N/length)."""
            from logic.staffing_insights import demand_template_fri_sat_nights

            # Windows — labeled example (user can edit)
            state["windows"] = demand_template_fri_sat_nights(2)
            try:
                use_windows.value = True
            except Exception:
                pass
            try:
                _refresh_win_list()
            except Exception:
                pass
            # 24/7 floor on (Require)
            try:
                use_247.value = True
                if not (cov247.value or "").strip():
                    cov247.value = "1"  # example only when empty
            except Exception:
                pass
            # Multi-block solve-for (open search over on/off patterns)
            try:
                if use_rot_model is not None:
                    use_rot_model.value = False
                if rot_model_kind is not None:
                    rot_model_kind.value = "Multi-block on/off"
                if callable(_sync_rotation_model):
                    _sync_rotation_model()
            except Exception:
                pass
            try:
                _persist_form()
                _refresh_space_estimate()
                _refresh_lock_strip()
            except Exception:
                pass
            go_step(2)
            ui.notify(
                "Weekend night check ready: Fri/Sat 19–03 min2 (example) + 24/7. "
                "Enter N / length / starts, then Find best.",
                type="info",
                position="top",
            )

        if btn_weekend_preset is not None:
            btn_weekend_preset.on_click(_apply_weekend_night_preset)

        if btn_soften is not None:

            async def _soft_search():
                await _run_opt(require_hard_ok=False)

            btn_soften.on_click(_soft_search)
        if btn_history is not None:
            btn_history.on_click(lambda: show_search_history())

        # Depth change also refreshes space estimate (hero only sets state)
        def _on_depth_refresh(e=None):
            state["search_depth"] = str(getattr(e, "value", None) or search_depth.value or "standard")
            try:
                _refresh_space_estimate()
            except Exception:
                pass

        search_depth.on_value_change(_on_depth_refresh)

        # Quick-start question buttons (step 1) reuse the same flows.
        async def _q_min_officers():
            go_step(2)
            await run_min_n()

        async def _q_whatif():
            go_step(2)
            await run_whatif()

        def _q_will_n():
            with (
                ui.dialog() as qdlg,
                ui.card()
                .classes("q-pa-md")
                .style("min-width:20rem;background:#0C1A2E;color:#E8EDF4;border:1px solid rgba(91,141,239,0.45)"),
            ):
                ui.label("Will N officers work?").style("font-weight:700;font-size:1.05rem;color:#F8FAFC")
                n_in = ui.input(label="Officer count", value=(officers.value or "8")).classes("w-full")

                async def _q_go():
                    raw = (n_in.value or "").strip()
                    try:
                        n = int(raw)
                    except ValueError:
                        ui.notify("Enter a whole number of officers", type="warning")
                        return
                    if n < 1:
                        ui.notify("Officer count must be at least 1", type="warning")
                        return
                    officers.value = str(n)
                    use_officers.value = True
                    _en_off(True)
                    qdlg.close()
                    go_step(2)
                    await run_opt()

                with ui.row().classes("gap-2 q-mt-sm"):
                    ui.button("Search", on_click=_q_go).classes("btn-primary").props("no-caps unelevated")
                    ui.button("Cancel", on_click=qdlg.close).classes("btn-ghost").props("no-caps outline")
            qdlg.open()

        btn_q_min.on_click(_q_min_officers)
        btn_q_will.on_click(_q_will_n)
        btn_q_plus.on_click(_q_whatif)

        # (Secondary tools now wired inline in the 4 dropdown menus above.)
        btn_apply_month.on_click(run_apply_winner_month)
        btn_impl.on_click(implement_plan)
        btn_preview.on_click(preview_publish)
        btn_apply_stay.on_click(apply_stay)
        btn_apply_pub.on_click(apply_and_publish_step)
        btn_save.on_click(save_scenario)
        btn_csv.on_click(export_csv)
        if btn_bid is not None:
            btn_bid.on_click(bid_from_sim)

        go_step(1)

    layout("simulator", body)
