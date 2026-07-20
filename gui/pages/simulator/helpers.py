"""Shared simulator helpers/constants (extracted from page.py)."""

from __future__ import annotations

from config import SIMULATOR_MULTI_BLOCK_CATALOG, SIMULATOR_ROTATION_TYPES

_DOW_NAMES = [
    "Any Day",
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]
_DOW_NAME_TO_WEEKDAY = {
    "Any Day": None,
    "Monday": 0,
    "Tuesday": 1,
    "Wednesday": 2,
    "Thursday": 3,
    "Friday": 4,
    "Saturday": 5,
    "Sunday": 6,
}
_WEEKDAY_TO_NAME = {v: k for k, v in _DOW_NAME_TO_WEEKDAY.items() if v is not None}
_WEEKDAY_TO_NAME[None] = "Any Day"

_ROTATION_OPTIONS = list(SIMULATOR_ROTATION_TYPES)
_STYLE_OPTIONS = ["Fixed", "Rotating"]
_MULTI_BLOCK_LABELS = [c["label"] for c in SIMULATOR_MULTI_BLOCK_CATALOG]
_MULTI_BY_LABEL = {c["label"]: c for c in SIMULATOR_MULTI_BLOCK_CATALOG}

_RESULT_STYLE = ""  # prefer class sim-result-panel
_OPTION_STYLE = ""  # class sim-option-card
_OPTION_ACTIVE = ""  # class sim-option-card active
_STEP_ON = "sim-step sim-step-on"
_STEP_OFF = "sim-step"
_STEP_DONE = "sim-step sim-step-done"
_HINT = "color:#9AABC4;font-size:0.88rem;line-height:1.45;margin-bottom:12px"
_ROW = ""  # prefer class sim-lock-row


def _chip_html(label: str, kind: str = "info") -> str:
    """Status chip for KPI / option headers (kind: ok|warn|crit|info)."""
    k = kind if kind in ("ok", "warn", "crit", "info") else "info"
    return f'<span class="status-chip status-chip-{k}">{label}</span>'


def _kpi_html(label: str, value: str, hint: str = "", tone: str = "v") -> str:
    t = tone if tone in ("v", "w", "g", "d") else "v"
    h = f'<div class="kpi-hint">{hint}</div>' if hint else ""
    return (
        f'<div class="kpi {t}">'
        f'<div class="kpi-l">{label}</div>'
        f'<div class="kpi-v" style="font-size:22px;margin-top:8px">{value}</div>'
        f"{h}</div>"
    )


def _set_enabled(widgets: list, enabled: bool) -> None:
    for w in widgets:
        try:
            if enabled:
                w.props(remove="disable")
                try:
                    w.classes(remove="sim-field-disabled")
                except Exception:
                    pass
            else:
                w.props("disable")
                try:
                    w.classes(add="sim-field-disabled")
                except Exception:
                    pass
        except Exception:
            pass


def _lock_row_classes(locked: bool) -> str:
    return "sim-lock-row sim-locked" if locked else "sim-lock-row"


def given_solve_toggle(ui, label: str):
    """Given / Solve-for segmented toggle for a schedule-shape axis.

    Drop-in for the old lock checkbox: exposes .value (bool) and
    .on_value_change, so every downstream use_X reference keeps working.
    Returns (toggle, free_hint_label) — free_hint shows what the optimizer
    searches while the axis is on Solve for.
    """
    with ui.element("div").classes("sim-dim-head"):
        ui.label(label).classes("sim-dim-label")
        toggle = (
            ui.toggle({False: "Solve for", True: "Given"}, value=False)
            .props("no-caps dense unelevated toggle-color=primary")
            .classes("sim-given-toggle")
        )
    return toggle
