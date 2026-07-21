"""NiceGUI: multi-block pattern calendar + soft compliance strip."""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from nicegui import ui

from logic.pattern_preview import form_preview_bundle


def render_pattern_calendar(host, cal: dict) -> None:
    host.clear()
    with host:
        ui.label("Pattern calendar (preview)").style(
            "font-weight:700;color:#F8FAFC;font-size:0.95rem;margin-bottom:4px"
        )
        ui.label(cal.get("message") or "").style("color:#9AABC4;font-size:0.8rem;margin-bottom:8px")
        if not cal.get("rows"):
            return
        for row in cal.get("rows") or []:
            with ui.row().classes("gap-1 items-center flex-wrap q-mb-xs"):
                ui.label(str(row.get("label") or "")[:28]).style(
                    "width:9rem;color:#E8EDF4;font-size:0.75rem;flex-shrink:0"
                )
                ui.label(f"{row.get('work_days')}/{row.get('cycle')}d").style(
                    "width:3.2rem;color:#9AABC4;font-size:0.7rem;flex-shrink:0"
                )
                for cell in (row.get("cells") or [])[:28]:
                    ui.element("div").style(
                        f"width:0.85rem;height:0.85rem;background:{cell.get('color')};"
                        "border-radius:2px;border:1px solid rgba(255,255,255,0.06);flex-shrink:0"
                    ).tooltip(f"Day {cell.get('day')}: {cell.get('label')}")
        with ui.row().classes("gap-3 q-mt-xs"):
            for lab, col in (("ON", "#22c55e"), ("OFF", "#1e293b")):
                with ui.row().classes("gap-1 items-center"):
                    ui.element("div").style(f"width:10px;height:10px;background:{col};border-radius:2px")
                    ui.label(lab).style("color:#9AABC4;font-size:0.7rem")


def render_compliance_strip(host, strip: dict) -> None:
    host.clear()
    with host:
        ui.label("Compliance strip (soft only)").style(
            "font-weight:700;color:#F8FAFC;font-size:0.95rem;margin-bottom:4px"
        )
        ui.label(strip.get("summary") or "").style("color:#9AABC4;font-size:0.8rem;margin-bottom:6px")
        for it in strip.get("items") or []:
            if it.get("ok"):
                c, mark = "#86efac", "✓"
            else:
                c, mark = "#FDE68A", "!"
            det = f" — {it['detail']}" if it.get("detail") else ""
            ui.label(f"{mark} {it.get('label')}{det}").style(f"color:{c};font-size:0.8rem;margin-top:2px")


def bind_pattern_preview(
    state: dict,
    host,
    *,
    form_payload: Optional[Callable[[], dict]] = None,
    get_variations: Optional[Callable[[], str]] = None,
    get_style: Optional[Callable[[], str]] = None,
) -> Dict[str, Any]:
    """Bind paint() into host with calendar + compliance sections."""

    cal_host = None
    strip_host = None

    def _ensure():
        nonlocal cal_host, strip_host
        host.clear()
        with host:
            with ui.expansion("Pattern calendar & compliance (soft)", icon="calendar_view_month", value=True).classes(
                "w-full sim-adv"
            ):
                ui.label(
                    "Preview on/off cycles before Find Best. Compliance items are soft cautions — "
                    "they do not block search."
                ).style("color:#9AABC4;font-size:0.8rem;margin-bottom:8px")
                ui.button("Refresh preview", on_click=lambda: paint()).classes("btn-ghost q-mb-sm").props(
                    "no-caps outline dense"
                )
                cal_host = ui.element("div").classes("w-full q-mb-md")
                strip_host = ui.element("div").classes("w-full")

    def paint():
        _ensure()
        form = {}
        if callable(form_payload):
            try:
                form = form_payload() or {}
            except Exception:
                form = {}
        if callable(get_variations):
            try:
                form["variations"] = get_variations()
            except Exception:
                pass
        if callable(get_style):
            try:
                form["rot_style"] = get_style()
            except Exception:
                pass
        bundle = form_preview_bundle(form)
        if cal_host is not None:
            render_pattern_calendar(cal_host, bundle.get("calendar") or {})
        if strip_host is not None:
            render_compliance_strip(strip_host, bundle.get("compliance") or {})
        state["pattern_preview"] = bundle

    return {"paint": paint, "ensure": _ensure}
