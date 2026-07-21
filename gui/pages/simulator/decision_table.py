"""Top-3 decision table — the primary comparison surface after a search.

Renders the best ranked options side by side with per-row winner
highlighting so a supervisor can decide without the Mark A/B ritual.
Cost fields come from logic.staffing_insights.enrich_option_economics.
"""

from __future__ import annotations

from typing import Any, Callable

from nicegui import ui

from logic.staffing_insights import enrich_option_economics, option_fatigue_score


def _avg_roster_hourly_rate(default: float = 35.0) -> float:
    """Mean hourly-equivalent across configured position rates; fallback 35."""
    try:
        from logic.operations import get_position_pay_rates

        rates = get_position_pay_rates() or {}
        vals = [
            float(v.get("hourly_equivalent") or 0)
            for v in rates.values()
            if isinstance(v, dict) and float(v.get("hourly_equivalent") or 0) > 0
        ]
        if vals:
            return round(sum(vals) / len(vals), 2)
    except Exception:
        pass
    return default


def _metric(row: dict, key: str) -> Any:
    m = row.get("metrics") or row.get("human_metrics") or {}
    return m.get(key)


def _fmt(val: Any, suffix: str = "") -> str:
    if val is None:
        return "—"
    if isinstance(val, float):
        val = round(val, 1)
    return f"{val}{suffix}"


def build_decision_table(
    host: Any,
    ranked: list,
    *,
    on_load: Callable[[dict], None],
    annual_target: float | None = None,
    flsa_period_days: int = 28,
    on_stress_test: Callable[[], None] | None = None,
    stress_results: dict | None = None,
) -> None:
    """Clear `host` and paint the top-3 comparison table into it."""
    host.clear()
    top = [dict(r) for r in (ranked or [])[:3]]
    if not top:
        return
    rate = _avg_roster_hourly_rate()
    top = [enrich_option_economics(r, hourly_rate=rate, flsa_period_days=flsa_period_days) for r in top]

    def econ(r: dict, key: str) -> Any:
        return (r.get("economics") or {}).get(key)

    # (label, getter, better) — better: "min" | "max" | None (no winner shading)
    rows: list[tuple[str, Callable[[dict], Any], str | None]] = [
        ("Officers", lambda r: r.get("num_officers"), "min"),
        ("Shift length", lambda r: r.get("shift_length_hours"), None),
        ("Pattern", lambda r: r.get("rotation_type") or "—", None),
        ("Hard constraints", lambda r: "OK" if r.get("hard_constraints_ok") else "Near-miss", None),
        ("Coverage %", lambda r: _metric(r, "coverage_percent"), "max"),
        ("Coverage gaps", lambda r: _metric(r, "gap_events"), "min"),
        ("Avg annual hrs", lambda r: _metric(r, "avg_annual_hours"), None),
        (f"Est. OT cost / {flsa_period_days}d", lambda r: econ(r, "est_ot_cost_usd"), "min"),
        ("Est. OT hours", lambda r: econ(r, "est_ot_hours_total"), "min"),
        ("Fairness score", lambda r: econ(r, "fairness_score"), "max"),
        ("Soft score", lambda r: r.get("soft_score"), "max"),
        ("FLSA period load", lambda r: econ(r, "flsa_period_pct"), None),
        ("Fatigue score", lambda r: (option_fatigue_score(r) or {}).get("score"), "max"),
    ]

    stress = stress_results or {}

    def _stress_cell(r: dict) -> str:
        s = stress.get(int(r.get("rank") or 0))
        if not s:
            return "—"
        if s.get("survives_one_out"):
            return f"Yes (holds at {s.get('n_tested')})"
        return f"No — {s.get('message', '')}"

    rows.append(("Survives 1 officer out", _stress_cell, None))

    def winners(getter, better) -> set:
        if better is None:
            return set()
        vals = []
        for i, r in enumerate(top):
            v = getter(r)
            if isinstance(v, (int, float)):
                vals.append((i, float(v)))
        if len(vals) < 2:
            return set()
        pick = min(vals, key=lambda t: t[1]) if better == "min" else max(vals, key=lambda t: t[1])
        best_val = pick[1]
        return {i for i, v in vals if v == best_val}

    with host:
        ui.html('<div class="sim-section-title">Decision table — top options</div>', sanitize=False)
        ui.label(
            f"Cost assumes avg roster rate ${rate}/h × 1.5 OT"
            + (f" · annual target {int(annual_target)}h" if annual_target else "")
        ).classes("sim-free-hint")
        with ui.element("div").classes("sim-decision-scroll"):
            with ui.element("table").classes("sim-decision-table"):
                with ui.element("thead"), ui.element("tr"):
                    ui.element("th")
                    for r in top:
                        with ui.element("th"):
                            ui.label(f"Option {r.get('rank')}")
                with ui.element("tbody"):
                    for label, getter, better in rows:
                        win = winners(getter, better)
                        with ui.element("tr"):
                            with ui.element("th"):
                                ui.label(label)
                            for i, r in enumerate(top):
                                suffix = "%" if label in ("Coverage %", "FLSA period load") else ""
                                prefix = "$" if label.startswith("Est. OT cost") else ""
                                cell = ui.element("td")
                                if i in win:
                                    cell.classes("sim-win-cell")
                                with cell:
                                    ui.label(prefix + _fmt(getter(r), suffix))
                    with ui.element("tr"):
                        ui.element("th")
                        for r in top:
                            with ui.element("td"):
                                ui.button(
                                    "Load this plan",
                                    on_click=lambda _=None, row=r: on_load(row),
                                ).classes("btn-primary").props("dense no-caps unelevated")
        if on_stress_test is not None and not stress:
            ui.button(
                "Stress-test these options (1 officer out)",
                icon="personal_injury",
                on_click=lambda _=None: on_stress_test(),
            ).classes("btn-ghost q-mt-sm").props("no-caps outline dense")
