from nicegui import ui

from gui.pages.simulator.helpers import _STEP_OFF, _STEP_ON

# Workflow steps (outer rail). Inner Phase 1–3 stepper lives under Requirements only.
STEP_META = (
    (1, "Requirements", "tune"),
    (2, "Find best", "travel_explore"),
    (3, "Manual build", "grid_on"),
    (4, "Publish", "publish"),
)


def render_stepper_rail(state: dict, step_labels: dict, go_step_cb) -> None:
    """Top workflow rail. Publish locked until a result exists."""
    with ui.element("div").classes("sim-step-rail").props('role="navigation" aria-label="Simulator steps"'):
        for idx, (i, title, icon) in enumerate(STEP_META):
            if idx:
                ui.element("div").classes("sim-step-connector")
            lab = ui.element("div").classes(_STEP_ON if i == 1 else _STEP_OFF)
            lab.props(f'tabindex="0" role="button" aria-label="Step {i}: {title}"')
            with lab:
                with ui.row().classes("items-center gap-2 no-wrap"):
                    ui.icon(icon).classes("text-sm")
                    ui.html(
                        f'<span class="sim-step-num">{i}</span>',
                        sanitize=False,
                    )
                    ui.label(title).classes("text-sm")

            def _nav(step=i):
                if step in (1, 2, 3) or state.get("result"):
                    go_step_cb(step)

            lab.on("click", _nav)
            lab.on("keydown.enter", _nav)
            step_labels[i] = lab
