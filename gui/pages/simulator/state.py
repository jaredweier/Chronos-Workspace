import dataclasses
from typing import Any, Dict, List, Optional

from logic.optimizer_features import default_weight_map


@dataclasses.dataclass
class SimulatorState:
    """Centralized state for the Schedule Simulator."""

    result: Optional[Any] = None
    config: Optional[Any] = None
    ranked: List[Any] = dataclasses.field(default_factory=list)
    selected_rank: int = 0
    compare_a: Optional[Any] = None
    compare_b: Optional[Any] = None
    opt_result: Optional[Any] = None
    windows: List[Dict[str, Any]] = dataclasses.field(default_factory=list)
    hard_mode: bool = True
    step: int = 1
    opt_running: bool = False
    opt_cancel: Optional[Any] = None
    opt_t0: Optional[float] = None
    constraint_priority: List[str] = dataclasses.field(
        default_factory=lambda: [
            "coverage_247",
            "windows",
            "gaps",
            "flsa",
            "annual",
            "headcount",
        ]
    )
    space_estimate: Optional[Any] = None
    pending_opt_kw: Optional[Dict[str, Any]] = None
    form_undo: List[Any] = dataclasses.field(default_factory=list)
    constraint_weights: Dict[str, float] = dataclasses.field(default_factory=default_weight_map)
    auto_find_after_preset: bool = False
    manual_grid: Optional[Any] = None
    manual_days: int = 14
    restoring_form: bool = False
    suppress_suggest: bool = False
    search_depth: str = "standard"
    max_step_reached: int = 1

    def to_dict(self) -> Dict[str, Any]:
        """Convert state to dictionary for compatibility if needed."""
        return dataclasses.asdict(self)

    def update(self, **kwargs) -> None:
        """Update multiple fields at once."""
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
