from nicegui import ui

from gui import session
from gui.pages.simulator.helpers import _HINT
from gui.shell import panel
from logic import recommend_implement_dates
from logic.ops_bridge import publish_readiness_checklist
from logic.staffing_insights import recommend_pay_period_preview
from validators import format_date


def render_publish_panel(state: dict, go_step_cb) -> tuple[ui.element, dict]:
    step4 = ui.element("div").classes("w-full").style("display:none")
    elements = {}
    with step4:
        with ui.element("div").classes("sim-publish-hero"):
            ui.html(
                '<div class="sim-section-title">Publish plan</div>',
                sanitize=False,
            )
            ui.label(
                "Apply the selected coverage option as a monthly schedule. Preview first if you want a dry run."
            ).style(_HINT)

        # P4 — publish readiness (blocking vs warn)
        readiness_host = ui.element("div").classes("w-full q-mb-sm")
        elements["readiness_host"] = readiness_host

        def refresh_readiness():
            res = state.get("result") or state.get("opt_result") or {}
            cfg = state.get("config") or state.get("last_config") or {}
            date_val = ""
            try:
                date_val = (elements.get("impl_date").value or "") if elements.get("impl_date") else ""
            except Exception:
                date_val = ""
            chk = publish_readiness_checklist(res, cfg, implement_date=date_val)
            state["publish_readiness"] = chk
            readiness_host.clear()
            with readiness_host:
                color = "#86efac" if chk.get("ready") else "#fca5a5"
                ui.label(f"Publish readiness: {chk.get('summary')}").style(
                    f"font-weight:700;color:{color};margin-bottom:6px"
                )
                for it in chk.get("items") or []:
                    if it.get("ok"):
                        c = "#86efac"
                        mark = "✓"
                    elif it.get("blocking"):
                        c = "#fca5a5"
                        mark = "✕"
                    else:
                        c = "#FDE68A"
                        mark = "!"
                    det = f" — {it['detail']}" if it.get("detail") else ""
                    ui.label(f"{mark} {it.get('label')}{det}").style(f"color:{c};font-size:0.85rem;margin-top:2px")

        elements["refresh_readiness"] = refresh_readiness

        with panel("Publish as monthly schedule"):
            rec = recommend_implement_dates()
            rec_raw = rec.get("recommended_date") or ""
            try:
                rec_date = format_date(rec_raw) if rec_raw else ""
            except Exception:
                rec_date = rec_raw
            ui.label(f"Recommended start: {rec.get('recommended_label') or ''} ({rec.get('reason', '')})").style(
                "color:#D6E6FF;font-size:0.9rem"
            )
            impl_date = ui.input(label="Implement start date (M/D/YY)", value=rec_date).classes("w-full")
            elements["impl_date"] = impl_date
            try:
                impl_date.on_value_change(lambda e: refresh_readiness())
            except Exception:
                pass

            with ui.row().classes("gap-2 flex-wrap q-mt-sm"):
                for opt in rec.get("options") or []:
                    d = opt.get("date") or ""
                    try:
                        d_disp = format_date(d) if d else d
                    except Exception:
                        d_disp = d
                    lab = (
                        "★ " + (opt.get("label") or d_disp) if opt.get("recommended") else (opt.get("label") or d_disp)
                    )

                    def _pick(date_val=d_disp):
                        impl_date.value = date_val
                        refresh_readiness()

                    ui.button(lab, on_click=_pick).classes("btn-ghost").props("no-caps outline dense")

            elements["apply_officers"] = ui.checkbox("Update officer home shifts from plan", value=False)
            elements["force_regen"] = ui.checkbox("Regenerate monthly if already published", value=True)
            elements["save_defaults"] = ui.checkbox("Save as schedule builder defaults", value=True)

        with panel("Ops bridge (after plan)"):
            ui.label("Callouts and bids use the loaded plan — soft prefs only; never change hard feasibility.").style(
                _HINT
            )
            with ui.row().classes("gap-2 flex-wrap q-mt-sm"):
                elements["btn_refresh_ready"] = (
                    ui.button("Refresh readiness", on_click=refresh_readiness)
                    .classes("btn-ghost")
                    .props("no-caps outline dense")
                )
                elements["btn_seed_open"] = (
                    ui.button("Preview open-shift callouts").classes("btn-ghost").props("no-caps outline dense")
                )
                elements["btn_post_open"] = (
                    ui.button("Post open-shift callouts").classes("btn-ghost").props("no-caps outline dense")
                )
                elements["btn_import_bid_prefs"] = (
                    ui.button("Import bid prefs → soft rank").classes("btn-ghost").props("no-caps outline dense")
                )

        ui.html(
            '<div class="sim-section-title" style="margin-top:12px">Action log</div>',
            sanitize=False,
        )
        action_log = ui.element("div").classes("sim-result-panel").style("min-height:5rem;max-height:12rem;")

        def set_action_log(text: str, *, ok: bool | None = None):
            action_log.clear()
            color = "#E8EDF4"
            if ok is True:
                color = "#86efac"
            elif ok is False:
                color = "#fca5a5"
            with action_log:
                ui.label(text or "—").style(f"color:{color};white-space:pre-wrap;line-height:1.45")

        elements["set_action_log"] = set_action_log
        set_action_log("No actions yet.")

        with ui.row().classes("gap-2 q-mt-md flex-wrap"):
            elements["btn_impl"] = ui.button("Publish as monthly").classes("btn-primary").props("no-caps unelevated")
            elements["btn_preview"] = (
                ui.button("Preview publish (dry run)").classes("btn-ghost").props("no-caps outline dense")
            )
            elements["btn_apply_stay"] = (
                ui.button("Apply option & stay").classes("btn-ghost").props("no-caps outline dense")
            )
            elements["btn_apply_pub"] = (
                ui.button("Apply option & go publish").classes("btn-ghost").props("no-caps outline dense")
            )
            elements["btn_save"] = ui.button("Save scenario").classes("btn-ghost").props("no-caps outline dense")
            elements["btn_csv"] = ui.button("Export CSV").classes("btn-ghost").props("no-caps outline dense")

            btn_bid = None
            if session.can("shift_bids.manage"):
                btn_bid = ui.button("Create Bid Draft").classes("btn-ghost").props("no-caps outline dense")
            elements["btn_bid"] = btn_bid

            ui.button("Back To Coverage", on_click=lambda: go_step_cb(2)).classes("btn-ghost").props("no-caps outline")
            ui.button("Back To Manual", on_click=lambda: go_step_cb(3)).classes("btn-ghost").props("no-caps outline")

            # Pay-period preview strip
            try:
                pp = recommend_pay_period_preview((impl_date.value or "").strip())
                ui.label(pp.get("message") or "Pay period preview").style(
                    "color:#9AABC4;font-size:0.85rem;margin-top:8px"
                )
            except Exception:
                pass

    return step4, elements
