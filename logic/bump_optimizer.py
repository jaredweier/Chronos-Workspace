"""**Optimizer brain** — bump chain planning and replacement pick.

Canonical implementation. Prefer public APIs from ``logic.coverage_optimizer``;
import this module for internals.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, List, Optional, Set, Tuple

import config
from config import is_high_risk_night
from database import connection
from logic import rust_bridge
from logic.officers import get_officer_by_id, get_officers_by_seniority
from logic.rotation_config import (
    get_active_rotation_base_date,
    get_active_rotation_cycle_length,
)
from logic.staffing_config import get_active_bump_rules_by_start, get_active_shift_times
from models import BumpChainStep, BumpChainSuggestion, BumpSimulationResult
from validators import applies_night_minimum, night_minimum_violation, parse_date


def _scheduling():
    """Lazy import of parent module to avoid circular import at load time."""
    import logic.scheduling as s

    return s


def _chain_excluded_officer_ids(
    steps: List[BumpChainStep],
    requesting_officer_id: Optional[int] = None,
) -> Set[int]:
    """Officers already bumped or assigned in the planned chain — not available as peers/replacements."""
    excluded: Set[int] = set()
    if requesting_officer_id is not None:
        excluded.add(requesting_officer_id)
    for step in steps:
        excluded.add(step.original_officer_id)
        excluded.add(step.replacement_officer_id)
    return excluded


def _bump_assignment_counts_for_date(
    request_date: str,
    planning_counts: Optional[Dict[int, int]] = None,
) -> Dict[int, int]:
    with connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT replacement_officer_id FROM schedule_overrides
            WHERE override_date = ? AND replacement_officer_id IS NOT NULL
        """,
            (request_date,),
        )
        counts: Dict[int, int] = {}
        for row in cursor.fetchall():
            rid = row["replacement_officer_id"]
            counts[rid] = counts.get(rid, 0) + 1
    for officer_id, extra in (planning_counts or {}).items():
        counts[officer_id] = counts.get(officer_id, 0) + extra
    return counts


def _bump_capacity_exhausted(officer_id: int, assignment_counts: Dict[int, int]) -> bool:
    return assignment_counts.get(officer_id, 0) >= config.BUMP_ASSIGNMENTS_BEFORE_BUSY


def count_remaining_on_shift_band(
    vacating_officer_id: int,
    vacated_shift_start: str,
    squad: str,
    schedule_context: Dict[int, Dict[str, str]],
    excluded_officer_ids: Set[int],
) -> int:
    """How many on-duty same-squad patrol officers remain on the vacated band."""
    from validators import officer_uses_command_staff_schedule

    vacated_band = _scheduling().normalize_shift_band(vacated_shift_start)
    if not vacated_band:
        return 0
    remaining = 0
    for officer in get_officers_by_seniority():
        if officer.get("active") != 1 or officer.get("squad") != squad:
            continue
        if officer_uses_command_staff_schedule(officer):
            continue
        oid = officer["id"]
        if oid == vacating_officer_id or oid in excluded_officer_ids:
            continue
        day_context = schedule_context.get(oid, {})
        if not _scheduling().officer_schedule_working(day_context):
            continue
        home_band = _scheduling().normalize_shift_band(
            _scheduling().officer_scheduled_shift_start(officer, day_context)
        )
        if home_band == vacated_band:
            remaining += 1
    return remaining


def _shift_retains_coverage_after_bump(
    vacating_officer_id: int,
    vacated_shift_start: str,
    squad: str,
    schedule_context: Dict[int, Dict[str, str]],
    excluded_officer_ids: Set[int],
    *,
    min_remaining: int = 1,
) -> bool:
    """True when enough on-duty same-squad officers remain on the vacated shift band.

    Multiple officers may share the same start time (e.g. two 06:00 slots).
    ``min_remaining`` comes from coverage policy (per-band or global min staff).
    """
    need = max(1, int(min_remaining))
    return (
        count_remaining_on_shift_band(
            vacating_officer_id,
            vacated_shift_start,
            squad,
            schedule_context,
            excluded_officer_ids,
        )
        >= need
    )


def _night_minimum_uncovered_failure(
    req_date: date,
    squad: str,
    shift_start: str,
    steps: List[BumpChainStep],
    blocked_officer_name: Optional[str] = None,
    blocked_shift: Optional[str] = None,
) -> Optional[BumpChainSuggestion]:
    if not applies_night_minimum(req_date, shift_start, is_high_risk_night):
        return None
    current = _scheduling().count_officers_on_shift_on_date(req_date, squad, shift_start)
    if not night_minimum_violation(current):
        return None
    return BumpChainSuggestion(
        success=False,
        steps=steps,
        message=("Cannot cover shift — would drop night coverage below minimum on a high-risk night"),
        requires_manual=True,
        failure_reason="night_minimum",
        blocked_officer_name=blocked_officer_name,
        blocked_shift=blocked_shift or shift_start,
    )


def find_replacement_officer(
    original_officer_id: int,
    request_date: str,
    squad: str,
    shift_start: str,
    schedule_context: Dict[int, Dict[str, str]],
    assignment_counts: Optional[Dict[int, int]] = None,
    chain_excluded_ids: Optional[Set[int]] = None,
    *,
    enforce_minimum_rest: bool = True,
    enforce_consecutive_work: bool = True,
) -> Optional[Dict]:
    """Pick best on-duty same-squad patrol replacement (scored junior + capacity + band)."""
    from logic.coverage_optimizer import list_scored_replacements

    ranked = list_scored_replacements(
        original_officer_id,
        request_date,
        squad,
        shift_start,
        schedule_context,
        assignment_counts,
        chain_excluded_ids,
        enforce_minimum_rest=enforce_minimum_rest,
        enforce_consecutive_work=enforce_consecutive_work,
        limit=1,
    )
    return ranked[0][1] if ranked else None


def _bump_suggestion_from_rust(data: Dict) -> BumpChainSuggestion:
    steps = [
        BumpChainStep(
            step_number=s["step_number"],
            original_officer_id=s["original_officer_id"],
            original_officer_name=s["original_officer_name"],
            original_shift=s["original_shift"],
            replacement_officer_id=s["replacement_officer_id"],
            replacement_officer_name=s["replacement_officer_name"],
            replacement_shift=s["replacement_shift"],
            replacement_on_duty=s["replacement_on_duty"],
        )
        for s in data.get("steps", [])
    ]
    chain = [(int(a), int(b)) for a, b in data.get("chain", [])]
    return BumpChainSuggestion(
        success=bool(data.get("success")),
        chain=chain,
        steps=steps,
        primary_replacement_name=data.get("primary_replacement_name"),
        message=data.get("message", ""),
        requires_manual=bool(data.get("requires_manual")),
        failure_reason=data.get("failure_reason"),
    )


def suggest_bump_chain(
    original_officer_id: int,
    request_date: str,
    squad: str,
    shift_start: str,
    max_depth: int = 8,
    *,
    supervisor_override: bool = False,
) -> BumpChainSuggestion:
    """Suggest a complete bump chain with step-by-step coverage detail."""
    req_date = parse_date(request_date)

    with connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM officers WHERE active = 1 ORDER BY id ASC",
        )
        officers = [dict(row) for row in cursor.fetchall()]
        cursor.execute(
            """
            SELECT original_officer_id, replacement_officer_id, reason
            FROM schedule_overrides WHERE override_date = ?
            """,
            (request_date,),
        )
        overrides_on_date = [
            (
                row["original_officer_id"],
                row["replacement_officer_id"],
                None,
                row["reason"] or "",
            )
            for row in cursor.fetchall()
        ]

    schedule_context = _scheduling().get_generated_schedule_day_context(req_date)
    shift_times = list(get_active_shift_times().values())
    enforce_compliance = not supervisor_override
    rest_window_start = req_date - timedelta(days=1)
    rest_window_end = req_date + timedelta(days=1)
    covering_shift_starts = _scheduling()._load_covering_shift_starts_for_range(rest_window_start, rest_window_end)
    from logic.labor_compliance import get_max_consecutive_work_days

    rust_data = rust_bridge.suggest_bump_chain(
        officers,
        overrides_on_date,
        original_officer_id,
        request_date,
        squad,
        shift_start,
        get_active_bump_rules_by_start(),
        shift_times,
        schedule_context,
        config.NIGHT_MINIMUM_OFFICERS,
        config.MIN_REST_HOURS_BETWEEN_SHIFTS,
        get_active_rotation_base_date(),
        get_active_rotation_cycle_length(),
        config.BUMP_ASSIGNMENTS_BEFORE_BUSY,
        max_depth,
        enforce_minimum_rest=enforce_compliance,
        enforce_consecutive_work=enforce_compliance,
        max_consecutive_work_days=get_max_consecutive_work_days(),
        covering_shift_starts=covering_shift_starts,
    )
    from logic.coverage_optimizer import optimize_day_off_coverage

    opt = optimize_day_off_coverage(
        original_officer_id,
        request_date,
        squad,
        shift_start,
        supervisor_override=supervisor_override,
        max_depth=max_depth,
    )
    if rust_data is None:
        return opt

    rust_plan = _bump_suggestion_from_rust(rust_data)
    # Rank complete plans: shorter chain first, then higher internal plan_score.
    # Scores are ranking-only — never surfaced to supervisors in messages.
    if opt.success and not rust_plan.success:
        return opt
    if rust_plan.success and not opt.success:
        return rust_plan
    if opt.success and rust_plan.success:
        rust_depth = len(rust_plan.chain or [])
        opt_depth = len(opt.chain or [])
        opt_score = float(opt.plan_score or 0.0)
        rust_score = float(rust_plan.plan_score or 0.0)
        prefer_opt = opt_depth < rust_depth or (opt_depth == rust_depth and opt_score > rust_score)
        if prefer_opt:
            n_alt = opt.alternatives_considered
            if n_alt and int(n_alt) > 1:
                opt.message = (
                    f"Best of {int(n_alt)} options — {opt_depth} assignment(s) · vs engine {rust_depth}-step chain"
                )
            else:
                opt.message = f"Auto-approve ready — {opt_depth} assignment(s) · vs engine {rust_depth}-step chain"
            return opt
        return rust_plan
    return opt if opt.success else rust_plan


def _minimum_rest_manual_failure(
    request_date: str,
    shift_start: str,
    schedule_context: Dict[int, Dict[str, str]],
    assignment_counts: Dict[int, int],
    chain_excluded: Set[int],
    original_officer_id: int,
    squad: str,
    blocked_officer_name: str,
    blocked_shift: str,
) -> Optional[BumpChainSuggestion]:
    """When cover exists but only if rest were ignored, route to supervisor override."""
    rest_pick = find_replacement_officer(
        original_officer_id,
        request_date,
        squad,
        _scheduling().normalize_shift_band(shift_start),
        schedule_context,
        assignment_counts,
        chain_excluded,
        enforce_minimum_rest=False,
    )
    if not rest_pick:
        return None
    covered_end = _scheduling().shift_end_for_start_active(_scheduling().normalize_shift_band(shift_start))
    msg = _scheduling().describe_minimum_rest_violation(
        rest_pick["id"],
        parse_date(request_date),
        _scheduling().normalize_shift_band(shift_start),
        covered_end,
        rest_pick.get("name"),
    )
    if not msg:
        return None
    return BumpChainSuggestion(
        success=False,
        message=msg,
        requires_manual=True,
        failure_reason="minimum_rest",
        blocked_officer_name=blocked_officer_name,
        blocked_shift=blocked_shift,
    )


def _consecutive_days_manual_failure(
    request_date: str,
    shift_start: str,
    schedule_context: Dict[int, Dict[str, str]],
    assignment_counts: Dict[int, int],
    chain_excluded: Set[int],
    original_officer_id: int,
    squad: str,
    blocked_officer_name: str,
    blocked_shift: str,
) -> Optional[BumpChainSuggestion]:
    """When cover exists but only if consecutive-day cap were ignored, route to supervisor."""
    from logic.labor_compliance import describe_consecutive_work_violation

    consecutive_pick = find_replacement_officer(
        original_officer_id,
        request_date,
        squad,
        _scheduling().normalize_shift_band(shift_start),
        schedule_context,
        assignment_counts,
        chain_excluded,
        enforce_consecutive_work=False,
    )
    if not consecutive_pick:
        return None
    msg = describe_consecutive_work_violation(
        consecutive_pick["id"],
        parse_date(request_date),
        adding_work_day=False,
        officer_name=consecutive_pick.get("name"),
    )
    if not msg:
        return None
    return BumpChainSuggestion(
        success=False,
        message=msg,
        requires_manual=True,
        failure_reason="consecutive_days",
        blocked_officer_name=blocked_officer_name,
        blocked_shift=blocked_shift,
    )


def _suggest_bump_chain_python(
    original_officer_id: int,
    request_date: str,
    squad: str,
    shift_start: str,
    schedule_context: Dict[int, Dict[str, str]],
    max_depth: int,
    *,
    enforce_minimum_rest: bool = True,
    enforce_consecutive_work: bool = True,
) -> BumpChainSuggestion:
    """Emergency fallback — prefer scheduler_core via rust_bridge.suggest_bump_chain."""
    req_date = parse_date(request_date)

    chain: List[Tuple[int, int]] = []
    steps: List[BumpChainStep] = []
    assignment_counts = _bump_assignment_counts_for_date(request_date)
    current_id = original_officer_id
    current_shift = shift_start

    while len(chain) < max_depth:
        current = get_officer_by_id(current_id)
        if not current:
            return BumpChainSuggestion(
                success=False,
                message="Officer not found while planning coverage",
                requires_manual=True,
                failure_reason="officer_missing",
            )

        chain_excluded = _chain_excluded_officer_ids(steps, requesting_officer_id=original_officer_id)
        replacement = find_replacement_officer(
            current_id,
            request_date,
            squad,
            _scheduling().normalize_shift_band(current_shift),
            schedule_context,
            assignment_counts,
            chain_excluded,
            enforce_minimum_rest=enforce_minimum_rest,
            enforce_consecutive_work=enforce_consecutive_work,
        )
        if not replacement:
            night_fail = _night_minimum_uncovered_failure(
                req_date,
                squad,
                current_shift,
                steps,
                blocked_officer_name=current["name"],
                blocked_shift=current_shift,
            )
            if night_fail:
                return night_fail
            if not chain:
                if enforce_minimum_rest:
                    rest_fail = _minimum_rest_manual_failure(
                        request_date,
                        current_shift,
                        schedule_context,
                        assignment_counts,
                        chain_excluded,
                        current_id,
                        squad,
                        current["name"],
                        current_shift,
                    )
                    if rest_fail:
                        return rest_fail
                if enforce_consecutive_work:
                    consecutive_fail = _consecutive_days_manual_failure(
                        request_date,
                        current_shift,
                        schedule_context,
                        assignment_counts,
                        chain_excluded,
                        current_id,
                        squad,
                        current["name"],
                        current_shift,
                    )
                    if consecutive_fail:
                        return consecutive_fail
                return BumpChainSuggestion(
                    success=False,
                    message="No replacement available on an allowed shift",
                    requires_manual=True,
                    failure_reason="no_replacement",
                    blocked_officer_name=current["name"],
                    blocked_shift=current_shift,
                )
            coverage_excluded = _chain_excluded_officer_ids(steps, requesting_officer_id=original_officer_id)
            if _shift_retains_coverage_after_bump(
                current_id,
                _scheduling().normalize_shift_band(current_shift),
                squad,
                schedule_context,
                coverage_excluded,
            ):
                primary = get_officer_by_id(chain[0][1])
                return BumpChainSuggestion(
                    success=True,
                    chain=chain,
                    steps=steps,
                    primary_replacement_name=primary["name"] if primary else None,
                    message=f"Auto-approve ready — {len(chain)} assignment(s)",
                )
            return BumpChainSuggestion(
                success=False,
                steps=steps,
                message=(
                    f"Cascade incomplete — no cover for {current['name']}'s "
                    f"{current_shift} shift after earlier assignments"
                ),
                requires_manual=True,
                failure_reason="cascade_incomplete",
                blocked_officer_name=current["name"],
                blocked_shift=current_shift,
            )

        repl_context = schedule_context.get(replacement["id"], {})
        on_duty = _scheduling().officer_schedule_working(repl_context)
        repl_shift = repl_context.get("shift_start") or replacement.get("shift_start") or ""
        steps.append(
            BumpChainStep(
                step_number=len(steps) + 1,
                original_officer_id=current_id,
                original_officer_name=current["name"],
                original_shift=current_shift,
                replacement_officer_id=replacement["id"],
                replacement_officer_name=replacement["name"],
                replacement_shift=repl_shift,
                replacement_on_duty=on_duty,
            )
        )
        chain.append((current_id, replacement["id"]))
        assignment_counts[replacement["id"]] = assignment_counts.get(replacement["id"], 0) + 1

        vacated_shift = repl_shift or replacement.get("shift_start") or ""
        coverage_excluded = _chain_excluded_officer_ids(steps, requesting_officer_id=original_officer_id)
        if _shift_retains_coverage_after_bump(
            replacement["id"],
            vacated_shift,
            squad,
            schedule_context,
            coverage_excluded,
        ):
            primary = get_officer_by_id(chain[0][1])
            return BumpChainSuggestion(
                success=True,
                chain=chain,
                steps=steps,
                primary_replacement_name=primary["name"] if primary else None,
                message=f"Auto-approve ready — {len(chain)} assignment(s)",
            )

        current_id = replacement["id"]
        current_shift = repl_shift or replacement.get("shift_start") or current_shift

    last = steps[-1] if steps else None
    return BumpChainSuggestion(
        success=False,
        steps=steps,
        message="Coverage chain too deep — supervisor must assign manually",
        requires_manual=True,
        failure_reason="cascade_too_deep",
        blocked_officer_name=last.replacement_officer_name if last else None,
        blocked_shift=last.replacement_shift if last else shift_start,
    )


def plan_bump_chain(
    original_officer_id: int,
    request_date: str,
    squad: str,
    shift_start: str,
    max_depth: int = 8,
) -> Tuple[List[Tuple[int, int]], Optional[str]]:
    """Build a complete bump chain. Partial cascades are rejected for manual review."""
    suggestion = suggest_bump_chain(original_officer_id, request_date, squad, shift_start, max_depth=max_depth)
    if suggestion.success:
        return suggestion.chain, None
    return [], suggestion.message


def format_bump_suggestion(suggestion: BumpChainSuggestion) -> str:
    if suggestion.success:
        lines = [suggestion.message or "Coverage plan ready."]
        for step in suggestion.steps:
            lines.append(
                f"Step {step.step_number}: {step.replacement_officer_name} "
                f"covers {step.original_officer_name} ({step.original_shift})"
            )
        return "\n".join(lines)
    lines = [f"Supervisor required: {suggestion.message}"]
    if suggestion.blocked_officer_name and suggestion.blocked_shift:
        lines.append(f"Blocked at: {suggestion.blocked_officer_name} ({suggestion.blocked_shift})")
    for step in suggestion.steps:
        lines.append(
            f"Step {step.step_number}: {step.replacement_officer_name} → "
            f"{step.original_officer_name} ({step.original_shift})"
        )
    return "\n".join(lines)


def validate_bump_feasibility(officer_id: int, request_date: str, squad: str, shift_start: str) -> BumpSimulationResult:
    suggestion = suggest_bump_chain(officer_id, request_date, squad, shift_start)
    if suggestion.success:
        return BumpSimulationResult(
            success=True,
            replacement_name=suggestion.primary_replacement_name,
            message=suggestion.message,
            suggestion=suggestion,
        )
    return BumpSimulationResult(
        success=False,
        message=suggestion.message,
        requires_manual=True,
        reason=suggestion.failure_reason,
        suggestion=suggestion,
    )
