"""Coverage heatmap + officer duty Gantt — first-class result visuals."""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from nicegui import ui

from logic.sim_visuals import coverage_band_heatmap, officer_duty_gantt, side_by_side_compare


def _active_result(state: dict) -> dict:
    """Prefer full sim result; fall back to opt best row shape."""
    res = state.get("result")
    if isinstance(res, dict) and (res.get("coverage_by_day") or res.get("officer_slots")):
        return res
    opt = state.get("opt_result") or {}
    if isinstance(opt, dict):
        if opt.get("coverage_by_day") or opt.get("officer_slots"):
            return opt
        best = opt.get("best") or state.get("selected_row") or {}
        if best:
            return {
                **best,
                "metrics": best.get("metrics") or opt.get("metrics") or {},
                "coverage_by_day": best.get("coverage_by_day") or opt.get("coverage_by_day") or [],
                "officer_slots": best.get("officer_slots") or opt.get("officer_slots") or [],
                "best": best,
            }
    return res if isinstance(res, dict) else {}


def render_coverage_heatmap(host, result: dict, *, max_days: int = 21) -> None:
    host.clear()
    hm = coverage_band_heatmap(result, max_days=max_days)
    with host:
        ui.label("Coverage Heat (day × start)").style(
            "font-weight:700;font-size:1.05rem;color:#F8FAFC;margin-bottom:6px"
        )
        ui.label(hm.get("message") or "").style("color:#9AABC4;font-size:0.85rem;margin-bottom:8px")
        if not hm.get("success"):
            return
        starts = hm.get("starts") or []
        # Header row
        with ui.row().classes("gap-0 items-center flex-nowrap").style("overflow-x:auto;max-width:100%"):
            ui.label("Date").style("width:5.5rem;color:#9AABC4;font-size:0.75rem;flex-shrink:0")
            ui.label("N").style("width:1.8rem;color:#9AABC4;font-size:0.75rem;text-align:center;flex-shrink:0")
            for st in starts:
                ui.label(str(st)[:5]).style(
                    "width:2.4rem;color:#9AABC4;font-size:0.7rem;text-align:center;flex-shrink:0"
                )
        for row in hm.get("rows") or []:
            with ui.row().classes("gap-0 items-center flex-nowrap").style("overflow-x:auto;max-width:100%"):
                risk = " !" if row.get("high_risk") else ""
                ui.label(f"{row.get('date')}{risk}").style("width:5.5rem;color:#E8EDF4;font-size:0.75rem;flex-shrink:0")
                ui.label(str(row.get("working") if row.get("working") is not None else "—")).style(
                    "width:1.8rem;color:#D6E6FF;font-size:0.75rem;text-align:center;flex-shrink:0"
                )
                for cell in row.get("cells") or []:
                    with (
                        ui.element("div")
                        .style(
                            f"width:2.4rem;height:1.35rem;background:{cell.get('color')};"
                            "border:1px solid rgba(255,255,255,0.06);flex-shrink:0;"
                            "display:flex;align-items:center;justify-content:center;"
                            "font-size:0.7rem;color:#0f172a;font-weight:600"
                        )
                        .tooltip(f"{row.get('date')} {cell.get('start')}: {cell.get('count')} ({cell.get('level')})")
                    ):
                        ui.label(str(cell.get("count", 0))).style("color:#f8fafc;font-size:0.7rem")
        with ui.row().classes("gap-3 q-mt-sm flex-wrap"):
            for lab, col in (
                ("OK", "#22c55e"),
                ("Thin", "#f59e0b"),
                ("Short/empty", "#ef4444"),
                ("High-risk thin", "#f97316"),
            ):
                with ui.row().classes("gap-1 items-center"):
                    ui.element("div").style(f"width:12px;height:12px;background:{col};border-radius:2px")
                    ui.label(lab).style("color:#9AABC4;font-size:0.75rem")


def render_officer_gantt(host, result: dict, *, max_days: int = 21) -> None:
    host.clear()
    g = officer_duty_gantt(result, max_days=max_days)
    with host:
        ui.label("Officer Duty Gantt").style("font-weight:700;font-size:1.05rem;color:#F8FAFC;margin-bottom:6px")
        ui.label(g.get("message") or "").style("color:#9AABC4;font-size:0.85rem;margin-bottom:4px")
        if g.get("hint"):
            ui.label(g["hint"]).style("color:#FDE68A;font-size:0.8rem;margin-bottom:8px")
        if not g.get("success"):
            return
        dates = g.get("dates") or []
        # Day headers (compact)
        with ui.row().classes("gap-0 items-center flex-nowrap").style("overflow-x:auto;max-width:100%"):
            ui.label("Officer").style("width:7.5rem;color:#9AABC4;font-size:0.75rem;flex-shrink:0")
            ui.label("Start").style("width:3.2rem;color:#9AABC4;font-size:0.75rem;flex-shrink:0")
            for i, d in enumerate(dates[:max_days] or range(max_days)):
                lab = str(d)[-5:] if isinstance(d, str) and len(str(d)) >= 5 else str(i + 1)
                ui.label(lab).style("width:1.15rem;color:#7A8FA8;font-size:0.6rem;text-align:center;flex-shrink:0")
        for row in g.get("rows") or []:
            with ui.row().classes("gap-0 items-center flex-nowrap").style("overflow-x:auto;max-width:100%"):
                ui.label(str(row.get("label") or "")[:14]).style(
                    "width:7.5rem;color:#E8EDF4;font-size:0.75rem;flex-shrink:0"
                )
                ui.label(str(row.get("start") or "—")[:5]).style(
                    "width:3.2rem;color:#D6E6FF;font-size:0.75rem;flex-shrink:0"
                )
                for cell in row.get("cells") or []:
                    tip = f"{row.get('label')} {cell.get('date')}: {'ON' if cell.get('on') else 'OFF'} @ {row.get('start')}"
                    ui.element("div").style(
                        f"width:1.15rem;height:1.15rem;background:{cell.get('color')};"
                        "border:1px solid rgba(255,255,255,0.05);flex-shrink:0;border-radius:2px"
                    ).tooltip(tip)
        with ui.row().classes("gap-3 q-mt-sm flex-wrap"):
            for lab, col in (("ON (day)", "#22c55e"), ("ON (night)", "#3B7DD8"), ("OFF", "#1e293b")):
                with ui.row().classes("gap-1 items-center"):
                    ui.element("div").style(f"width:12px;height:12px;background:{col};border-radius:2px")
                    ui.label(lab).style("color:#9AABC4;font-size:0.75rem")


def render_compare_cards(host, plans: list, labels: Optional[list] = None) -> None:
    host.clear()
    data = side_by_side_compare(plans, labels=labels)
    with host:
        ui.label("Scenario Compare").style("font-weight:700;font-size:1.05rem;color:#F8FAFC;margin-bottom:8px")
        if not data.get("cards"):
            ui.label("Select or pin 2–3 options first.").style("color:#9AABC4")
            return
        with ui.row().classes("gap-3 flex-wrap"):
            for card in data["cards"]:
                with (
                    ui.card()
                    .classes("q-pa-sm")
                    .style("min-width:11rem;background:#0C1A2E;border:1px solid rgba(59,125,216,0.35);color:#E8EDF4")
                ):
                    ui.label(str(card.get("label"))).style("font-weight:700;color:#F8FAFC")
                    hard = card.get("hard_ok")
                    hard_t = "Hard OK" if hard else ("Hard fail" if hard is False else "Hard —")
                    hard_c = "#86efac" if hard else ("#fca5a5" if hard is False else "#9AABC4")
                    ui.label(hard_t).style(f"color:{hard_c};font-size:0.85rem")
                    ui.label(f"N={card.get('n') if card.get('n') is not None else '—'}").style(
                        "color:#D6E6FF;font-size:0.85rem"
                    )
                    starts = card.get("starts")
                    if isinstance(starts, (list, tuple)):
                        starts = ", ".join(str(s) for s in starts[:4])
                    ui.label(f"Starts: {starts or '—'}").style("color:#9AABC4;font-size:0.8rem")
                    ui.label(
                        f"Annual avg: {card.get('annual_avg') if card.get('annual_avg') is not None else '—'}"
                    ).style("color:#9AABC4;font-size:0.8rem")
                    ui.label(
                        f"Win short: {card.get('win_fails') if card.get('win_fails') is not None else '—'} · "
                        f"24/7: {card.get('c247_fails') if card.get('c247_fails') is not None else '—'}"
                    ).style("color:#9AABC4;font-size:0.8rem")


def bind_visuals_panel(
    state: dict,
    host,
    *,
    set_why: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """Bind paint + dialog openers for heatmap / gantt / compare."""

    heat_host = None
    gantt_host = None
    compare_host = None

    def _ensure_sections():
        nonlocal heat_host, gantt_host, compare_host
        host.clear()
        with host:
            with ui.expansion("Coverage heat & officer Gantt", icon="grid_on", value=True).classes("w-full sim-adv"):
                with ui.row().classes("gap-2 flex-wrap q-mb-sm"):
                    ui.button("Refresh visuals", on_click=lambda: paint_visuals()).classes("btn-primary").props(
                        "no-caps unelevated dense"
                    )
                    ui.button("Compare top 3", on_click=lambda: paint_compare()).classes("btn-ghost").props(
                        "no-caps outline dense"
                    )
                heat_host = ui.element("div").classes("w-full q-mb-md")
                gantt_host = ui.element("div").classes("w-full q-mb-md")
                compare_host = ui.element("div").classes("w-full")

    def paint_visuals():
        _ensure_sections()
        res = _active_result(state)
        if heat_host is not None:
            render_coverage_heatmap(heat_host, res)
        if gantt_host is not None:
            render_officer_gantt(gantt_host, res)
        if set_why and res:
            short = (res.get("metrics") or {}).get("night_risk_gaps")
            if short:
                try:
                    set_why(f"Visuals refreshed · night_risk_gaps={short}")
                except Exception:
                    pass

    def paint_compare():
        _ensure_sections()
        ranked = list(state.get("ranked") or [])[:3]
        plans = []
        for row in ranked:
            plans.append(
                {
                    "best": row,
                    "metrics": row.get("metrics") or {},
                    "num_officers": row.get("num_officers"),
                    "shift_starts": row.get("shift_starts"),
                    "shift_length_hours": row.get("shift_length_hours"),
                }
            )
        if not plans and state.get("result"):
            plans = [state.get("result")]
        if compare_host is not None:
            render_compare_cards(
                compare_host,
                plans,
                labels=[f"#{r.get('rank') or i + 1}" for i, r in enumerate(ranked)] or None,
            )

    def open_heat_dialog():
        res = _active_result(state)
        with (
            ui.dialog() as dlg,
            ui.card().classes("q-pa-md").style("min-width:28rem;max-width:56rem;background:#0C1A2E;color:#E8EDF4"),
        ):
            box = ui.element("div").classes("w-full")
            render_coverage_heatmap(box, res, max_days=28)
            ui.button("Close", on_click=dlg.close).classes("btn-ghost q-mt-md").props("no-caps outline")
        dlg.open()

    def open_gantt_dialog():
        res = _active_result(state)
        with (
            ui.dialog() as dlg,
            ui.card().classes("q-pa-md").style("min-width:28rem;max-width:56rem;background:#0C1A2E;color:#E8EDF4"),
        ):
            box = ui.element("div").classes("w-full")
            render_officer_gantt(box, res, max_days=28)
            ui.button("Close", on_click=dlg.close).classes("btn-ghost q-mt-md").props("no-caps outline")
        dlg.open()

    return {
        "paint_visuals": paint_visuals,
        "paint_compare": paint_compare,
        "open_heat_dialog": open_heat_dialog,
        "open_gantt_dialog": open_gantt_dialog,
        "ensure": _ensure_sections,
    }
