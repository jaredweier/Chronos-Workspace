"""Extra minimum staffing windows panel (extracted from page.py)."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from nicegui import ui

from gui.pages.simulator.helpers import (
    _DOW_NAME_TO_WEEKDAY,
    _DOW_NAMES,
    _HINT,
    _WEEKDAY_TO_NAME,
    _set_enabled,
)
from gui.shell import panel
from logic.optimizer_features import get_window_template, list_window_templates
from logic.staffing_insights import (
    court_board_to_demand_windows,
    get_demand_template,
    list_demand_templates,
)
from validators import parse_date, storage_date_str


def render_windows_panel(
    state: dict,
    *,
    persist_form: Optional[Callable[[], None]] = None,
    show_suggestions: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """Build Extra Minimum Staffing Windows UI. Returns widget + refresh refs."""
    out: Dict[str, Any] = {}

    with panel("Extra Minimum Staffing Windows"):
        ui.label(
            "When checked, every window below is a hard minimum. "
            "Windows are empty until you add them or restore a saved form. "
            "Demand templates convert peak-risk hours into windows."
        ).style(_HINT)
        use_windows = ui.checkbox("Require: Extra Minimum Staffing Windows", value=False)
        out["use_windows"] = use_windows

        with ui.row().classes("gap-2 flex-wrap q-mb-sm"):
            for tmpl in list_demand_templates():

                def _apply_demand(tid=tmpl["id"], lab=tmpl["label"]):
                    if tid == "from_court_board":
                        r = court_board_to_demand_windows()
                        wins = list(r.get("windows") or [])
                        if not wins:
                            ui.notify(
                                r.get("message") or "No court events",
                                type="warning",
                            )
                            return
                        msg = r.get("message") or lab
                    else:
                        wins = get_demand_template(tid)
                        msg = lab
                    if not wins:
                        ui.notify("Unknown template", type="warning")
                        return
                    state["windows"] = list(wins)
                    use_windows.value = True
                    try:
                        _refresh_win_list()
                    except Exception:
                        pass
                    if persist_form:
                        try:
                            persist_form()
                        except Exception:
                            pass
                    ui.notify(f"Demand windows: {msg}", type="positive")
                    if show_suggestions:
                        try:
                            show_suggestions("windows")
                        except Exception:
                            pass

                ui.button(
                    tmpl["label"][:32],
                    on_click=_apply_demand,
                ).classes("btn-ghost").props("dense no-caps outline")

        win_body = ui.column().classes("w-full")
        win_list_col = ui.column().classes("w-full gap-1 q-mb-sm")

        def _refresh_win_list():
            win_list_col.clear()
            with win_list_col:
                if not state["windows"]:
                    ui.label("No Windows Added Yet.").style("color:#7A8FA8;font-size:0.9rem")
                    return
                for i, w in enumerate(state["windows"]):
                    if w.get("specific_date"):
                        when = f"Date {w.get('specific_date')}"
                    elif w.get("weekday") is not None:
                        when = _WEEKDAY_TO_NAME.get(w.get("weekday"), f"Weekday {w.get('weekday')}")
                    else:
                        when = "Any Day"
                    line = (
                        f"#{i + 1} · Min {w.get('min_officers')} · "
                        f"{w.get('start_time')}–{w.get('end_time')} · "
                        f"{when} · {w.get('label') or 'Window'}"
                    )
                    with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                        ui.label(line).classes("text-sm").style("color:#E8EDF4;flex:1")

                        def _del(idx=i):
                            if 0 <= idx < len(state["windows"]):
                                state["windows"].pop(idx)
                                _refresh_win_list()

                        ui.button("Remove", on_click=_del).classes("btn-ghost").props("dense no-caps outline")

        out["refresh_win_list"] = _refresh_win_list

        with win_body:
            _refresh_win_list()
            w_min = ui.input(label="Min Officers", value="2").classes("w-full")
            w_start = ui.input(label="Start Time (HH:MM)", value="19:00").classes("w-full")
            w_end = ui.input(label="End Time (HH:MM)", value="03:00").classes("w-full")
            w_dow = (
                ui.select(_DOW_NAMES, value="Friday", label="Day Of Week")
                .classes("w-full")
                .props("outlined dense dark")
            )
            w_date = ui.input(label="Or Specific Date (M/D/YY, Optional)", value="").classes("w-full")
            w_label = ui.input(label="Label", value="Friday Night").classes("w-full")
            win_inputs: List[Any] = [w_min, w_start, w_end, w_dow, w_date, w_label]

            def add_window():
                if not use_windows.value:
                    ui.notify("Enable Extra Windows First", type="warning")
                    return
                try:
                    mn = int((w_min.value or "1").strip())
                except ValueError:
                    ui.notify("Min Officers Must Be A Number", type="negative")
                    return
                start = (w_start.value or "").strip()
                end = (w_end.value or "").strip()
                if not start or not end:
                    ui.notify("Start And End Times Required", type="negative")
                    return
                day_name = (w_dow.value or "Any Day").strip()
                weekday = _DOW_NAME_TO_WEEKDAY.get(day_name)
                specific_iso = None
                raw_d = (w_date.value or "").strip()
                if raw_d:
                    try:
                        specific_iso = storage_date_str(parse_date(raw_d))
                    except Exception:
                        ui.notify("Date Must Be M/D/YY", type="negative")
                        return
                state["windows"].append(
                    {
                        "min_officers": mn,
                        "start_time": start,
                        "end_time": end,
                        "weekday": weekday if not specific_iso else None,
                        "specific_date": specific_iso,
                        "label": (w_label.value or "").strip() or "Window",
                        "enabled": True,
                    }
                )
                _refresh_win_list()
                ui.notify(f"Window Added ({day_name})", type="positive")

            def load_dept_windows():
                try:
                    from logic import list_coverage_windows

                    n = 0
                    for row in list_coverage_windows() or []:
                        if row.get("enabled") is False:
                            continue
                        state["windows"].append(
                            {
                                "min_officers": row.get("min_officers") or 1,
                                "start_time": row.get("start_time"),
                                "end_time": row.get("end_time"),
                                "weekday": row.get("weekday"),
                                "specific_date": row.get("specific_date"),
                                "label": row.get("label") or "Window",
                                "enabled": True,
                            }
                        )
                        n += 1
                    _refresh_win_list()
                    ui.notify(f"Loaded {n} Department Window(s)", type="info")
                except Exception as exc:
                    ui.notify(f"Could Not Load: {exc}", type="negative")

            def apply_window_template(tid: str):
                wins = get_window_template(tid)
                if not wins:
                    ui.notify("Unknown template", type="warning")
                    return
                use_windows.value = True
                state["windows"] = list(wins)
                _refresh_win_list()
                ui.notify(f"Loaded window template ({len(wins)})", type="positive")

            with ui.row().classes("gap-2 flex-wrap q-mt-sm"):
                btn_add_win = (
                    ui.button("Add Window", on_click=add_window)
                    .classes("btn-primary")
                    .props("no-caps unelevated dense")
                )
                btn_load_win = (
                    ui.button("Load From Operations", on_click=load_dept_windows)
                    .classes("btn-ghost")
                    .props("no-caps outline dense")
                )
                for tmpl in list_window_templates():
                    tid = tmpl["id"]
                    ui.button(
                        tmpl["label"][:28],
                        on_click=lambda t=tid: apply_window_template(t),
                    ).classes("btn-ghost").props("no-caps outline dense")
                win_inputs.extend([btn_add_win, btn_load_win])

        def _sync_win_enabled(e=None):
            _set_enabled(win_inputs, bool(use_windows.value))

        use_windows.on_value_change(_sync_win_enabled)
        out["win_inputs"] = win_inputs
        out["sync_enabled"] = _sync_win_enabled

    return out
