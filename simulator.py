"""
Schedule Simulator — generates and optimizes 24/7 patrol coverage plans.
Pure logic module; called from logic.py.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

from config import (
    NIGHT_MINIMUM_OFFICERS,
    ROTATION_PRESETS,
    is_high_risk_night,
)
from validators import format_date

try:
    from logic import rust_bridge
except ImportError:
    rust_bridge = None  # type: ignore


@dataclass
class SimulatorConfig:
    rotation_type: str
    num_officers: int  # 0 or negative → auto minimum officers
    shift_length_hours: float
    annual_hours_target: float
    shift_starts: List[str]
    # Default False matches UI/optimizer/store — pure what-if sims.
    # True pulls live roster squads (can leave a squad empty if roster is unbalanced).
    apply_department_rules: bool = False
    min_per_shift: int = 1
    simulation_days: int = 28
    night_minimum: int = NIGHT_MINIMUM_OFFICERS
    # Extended customizable constraints (all optional / toggleable)
    annual_hours_variance: float = 40.0
    annual_hours_hard: bool = False
    coverage_247: int = 0  # 0 = off; else min officers every moment
    avoid_flsa_overtime: bool = False
    flsa_work_period_days: int = 28
    rotation_style: str = ""  # fixed | rotating | empty (use rotation_type preset)
    rotation_variations: List[str] = field(default_factory=list)  # e.g. ["5-3,6-2", "5-2,6-3"]
    stagger_phases: bool = True
    use_extra_windows: bool = False
    extra_windows: List[Dict] = field(default_factory=list)  # {dow|date, start, end, min}
    auto_min_officers: bool = True
    # When True: each day re-picks from the half-hour grid (experimental).
    # Default False: daily rebalance among the chosen start *pack* (bands still
    # move between pack clocks day-to-day via _balance_day_assignments).
    flexible_daily_starts: bool = False
    # Work-day start flex: officers keep a home start but may move ±nearby_start_hops
    # pack bands (e.g. home 19:00 → 14:00 or 22:00). User-settable "bumps" in UI.
    nearby_start_hops: int = 1
    # Off-day coverage: OFF only when user opts in. Default False — rotation ON days only.
    allow_offday_coverage: bool = False
    # Fatigue (optional hard): 0 = off. Rest between consecutive work-day ends→starts.
    min_rest_hours: float = 0.0
    # Max consecutive ON days in multi-block vector (0 = off).
    max_consecutive_work_days: int = 0
    # Calendar anchor for the sim window (Fri/Sat night detection, phase
    # staggering). None = today. UI's "sim start date" lock was previously
    # silently dropped here — simulate_schedule hardcoded date.today().
    sim_start_date: Optional[date] = None
    phase_limit: int = 3
    # Staffing-optimizer inner search (optional). When set, skip heuristic stagger.
    phase_overrides: Optional[List[int]] = None  # per-slot cycle phase
    pattern_slot_map: Optional[List[int]] = None  # per-slot index into rotation_variations


@dataclass
class SimulatorSuggestion:
    severity: str
    title: str
    message: str
    recommendation: str = ""


@dataclass
class SimulatorOfficerSlot:
    slot_id: int
    label: str
    squad: str
    shift_start: str
    shift_end: str
    projected_annual_hours: float
    work_days_in_sim: int


@dataclass
class SimulatorResult:
    success: bool
    message: str = ""
    compute_backend: str = "python"
    shift_templates: List[Tuple[str, str]] = field(default_factory=list)
    officer_slots: List[SimulatorOfficerSlot] = field(default_factory=list)
    coverage_by_day: List[Dict] = field(default_factory=list)
    metrics: Dict = field(default_factory=dict)
    suggestions: List[SimulatorSuggestion] = field(default_factory=list)


def _parse_time_minutes(value: str) -> int:
    parts = value.strip().split(":")
    return int(parts[0]) * 60 + int(parts[1])


def _format_minutes(total: int) -> str:
    total = total % (24 * 60)
    return f"{total // 60:02d}:{total % 60:02d}"


def _shift_end(start: str, hours: float) -> str:
    return _format_minutes(_parse_time_minutes(start) + int(hours * 60))


def _is_night_shift_start(start: str) -> bool:
    hour = int(start.split(":")[0])
    return hour >= 18 or hour < 6


def generate_shift_templates(
    shift_length_hours: float,
    shift_starts: Optional[List[str]] = None,
    use_department_shifts: bool = False,
) -> List[Tuple[str, str]]:
    if use_department_shifts:
        from logic.staffing_config import get_active_shift_times

        return list(get_active_shift_times().values())

    if shift_starts:
        cleaned = [s.strip() for s in shift_starts if s.strip()]
        if cleaned:
            return [(s, _shift_end(s, shift_length_hours)) for s in cleaned]

    templates = []
    length_minutes = int(shift_length_hours * 60)
    if length_minutes <= 0:
        return templates
    count = max(1, math.ceil((24 * 60) / length_minutes))
    spacing = (24 * 60) // count
    for i in range(count):
        start = _format_minutes(i * spacing)
        templates.append((start, _shift_end(start, shift_length_hours)))
    return templates


def _squad_working(
    rotation_type: str,
    squad: str,
    cycle_day: int,
    preset: Dict,
    *,
    phase: int = 0,
) -> bool:
    """Whether squad is ON for cycle_day (1-based). phase shifts squad_patterns rings."""
    del rotation_type  # preset already resolved by caller
    if "squad_a_days" in preset:
        on_a = cycle_day in preset["squad_a_days"]
        return on_a if squad == "A" else not on_a
    if "squad_patterns" in preset:
        pattern = preset["squad_patterns"].get(squad, preset["squad_patterns"].get("A", []))
        if not pattern:
            return False
        # phase rotates the duty ring so single-squad presets can stagger
        idx = (cycle_day - 1 + int(phase or 0)) % len(pattern)
        return bool(pattern[idx])
    work_days = preset.get("work_days_per_cycle", 7)
    half = work_days // preset.get("squads", 2)
    cyc = max(1, int(preset.get("cycle_length") or 1))
    if squad == "A":
        return ((cycle_day - 1 + int(phase or 0)) % cyc) < half
    offset = cyc // preset.get("squads", 2)
    return ((cycle_day - 1 + offset + int(phase or 0)) % cyc) < half


def _squad_union_has_off_day(preset: Dict) -> bool:
    """True if unphased squad patterns leave some cycle day with nobody ON."""
    if "squad_a_days" in preset:
        return False  # classic A/B complement covers every day
    patterns = preset.get("squad_patterns") or {}
    vecs = [list(v) for v in patterns.values() if v]
    if not vecs:
        # equal-split fallback without patterns: multi-squad covers by construction
        return int(preset.get("squads") or 1) <= 1
    n = max(len(v) for v in vecs)
    for d in range(n):
        if not any(bool(v[d % len(v)]) for v in vecs):
            return True
    return False


def _squad_phase_offsets(
    preset: Dict,
    n_slots: int,
    *,
    stagger: bool,
    phase_overrides: Optional[List[int]] = None,
) -> List[int]:
    """Per-slot duty-ring phase for squad presets (enables 24/7 on single-pattern rings).

    Only auto-staggers when the unphased multi-squad union has holes (e.g. Continental
    single ring). Complement A/B packs (Pitman, 4-on-4-off) keep phase 0 so pairs stay
    opposite.
    """
    n = max(0, int(n_slots))
    if n < 1:
        return []
    cyc = max(1, int(preset.get("cycle_length") or 1))
    if phase_overrides is not None:
        out = []
        step0 = max(1, cyc // max(n, 1))
        for i in range(n):
            if i < len(phase_overrides):
                out.append(int(phase_overrides[i]) % cyc)
            else:
                out.append((i * step0) % cyc)
        return out
    if not stagger or n <= 1 or not _squad_union_has_off_day(preset):
        return [0] * n
    # Even stagger across the cycle (same idea as multi-block phase search seed)
    if n > cyc:
        return [i % cyc for i in range(n)]
    step = max(1, cyc // n)
    return [(i * step) % cyc for i in range(n)]


def _assign_officers(
    num_officers: int,
    shift_templates: List[Tuple[str, str]],
    preset: Dict,
    roster_officers: Optional[List[Dict]] = None,
) -> List[SimulatorOfficerSlot]:
    """Build exactly ``num_officers`` slots (pad roster shortfall with synthetics).

    Earlier bug: when roster was shorter than num_officers, only len(roster)
    slots were created — silent headcount truncation.
    """
    squads = ["A", "B"] if preset.get("squads", 2) >= 2 else ["A"]
    n_sq = max(1, int(preset.get("squads") or len(squads)))
    # Expand squad labels beyond A/B when preset has 3+ squads
    if n_sq > len(squads):
        squads = [chr(ord("A") + i) for i in range(n_sq)]
    slots: List[SimulatorOfficerSlot] = []
    roster = list(roster_officers or [])[: max(0, int(num_officers))]
    n = max(0, int(num_officers))
    templates = shift_templates or [("06:00", "14:00")]
    for i in range(n):
        shift_start, shift_end = templates[i % len(templates)]
        if i < len(roster):
            officer = roster[i]
            raw_sq = (officer.get("squad") or "").strip().upper()
            # Keep real squad if it is a valid preset letter; else alternate
            if raw_sq and raw_sq in squads:
                squad = raw_sq
            else:
                squad = squads[i % len(squads)]
            slots.append(
                SimulatorOfficerSlot(
                    slot_id=int(officer.get("id") or i + 1),
                    label=str(officer.get("name") or f"Officer {i + 1}"),
                    squad=squad,
                    shift_start=shift_start,
                    shift_end=shift_end,
                    projected_annual_hours=0.0,
                    work_days_in_sim=0,
                )
            )
        else:
            squad = squads[i % len(squads)]
            slots.append(
                SimulatorOfficerSlot(
                    slot_id=i + 1,
                    label=f"Officer {i + 1}",
                    squad=squad,
                    shift_start=shift_start,
                    shift_end=shift_end,
                    projected_annual_hours=0.0,
                    work_days_in_sim=0,
                )
            )
    return slots


def _optimize_assignments(
    slots: List[SimulatorOfficerSlot],
    shift_templates: List[Tuple[str, str]],
    coverage_gaps: Dict[Tuple[int, str], int],
) -> List[SimulatorOfficerSlot]:
    """Redistribute slots toward understaffed bands identified in coverage_gaps.

    If no gaps are provided (standard path) this falls back to the even
    round-robin distribution.  When gaps exist, officers whose home band is
    NOT in the gap set are swapped toward a gapped band (preferring the
    closest clock to their home start).
    """
    if not shift_templates or not slots:
        return slots
    # Round-robin baseline so every band gets at least one officer
    for i, slot in enumerate(slots):
        slot.shift_start, slot.shift_end = shift_templates[i % len(shift_templates)]
    if not coverage_gaps:
        return slots
    # Build set of shift starts that have recorded gaps
    gapped_starts = {st for (_d, st) in coverage_gaps.keys()}
    if not gapped_starts:
        return slots
    # Find slots NOT already assigned to a gapped band
    non_gapped = [s for s in slots if s.shift_start not in gapped_starts]
    gapped_targets = [t for t in shift_templates if t[0] in gapped_starts]
    if not non_gapped or not gapped_targets:
        return slots
    # Reassign each non-gapped slot to the nearest (in clock time) gapped band
    for slot in non_gapped:
        home_m = _hhmm_to_min(slot.shift_start)
        best_t, best_d = gapped_targets[0], 10**9
        for t in gapped_targets:
            d = abs(_hhmm_to_min(t[0]) - home_m)
            d = min(d, 24 * 60 - d)
            if d < best_d:
                best_d, best_t = d, t
        slot.shift_start, slot.shift_end = best_t
    return slots


def _pack_band_index(start: str, templates: List[Tuple[str, str]]) -> int:
    """Nearest pack band index for a home start label."""
    if not templates:
        return 0
    sm = _hhmm_to_min(start)
    best_i, best_d = 0, 10**9
    for i, (st, _en) in enumerate(templates):
        d = abs(_hhmm_to_min(st) - sm)
        d = min(d, 24 * 60 - d)
        if d < best_d:
            best_d, best_i = d, i
    return best_i


def _balance_day_assignments(
    working_slots: List[SimulatorOfficerSlot],
    shift_templates: List[Tuple[str, str]],
    *,
    min_per_shift: int,
    prefer_night: bool = False,
    fri_sat_window: bool = False,
    nearby_hops: int = 1,
    window_min: int = 0,
    window_start: str = "",
    window_end: str = "",
    shift_length_hours: float = 8.0,
    coverage_247: int = 0,
    active_windows: Optional[List[Dict]] = None,
    min_rest_hours: float = 0.0,
    prev_work_starts: Optional[List[Optional[str]]] = None,
) -> List[Tuple[str, str]]:
    """Assign today's working officers onto pack bands.

    Officers keep a *home* start but may move to nearby pack bands (default ±1).
    When a coverage window is active, bias seats onto bands that cover that window
    (clocks from window_start/end — not a baked example).
    When coverage_247>0, window rebalance must not collapse the 24h tile.
    active_windows: optional list of {start_time,end_time,min_officers} for multi-window days.
    min_rest_hours + prev_work_starts: prefer seats that leave enough rest after yesterday.
    """
    if not working_slots or not shift_templates:
        return []
    n = len(working_slots)
    k = len(shift_templates)
    # min_per_shift floor on *used* starts; 0 = no floor (geometry still uses geo_need=1)
    need = max(0, int(min_per_shift or 0))
    geo_need = max(need, 1)
    preserve_247 = int(coverage_247 or 0) > 0
    min_rest = float(min_rest_hours or 0)
    prev_sts: List[Optional[str]] = list(prev_work_starts or [])
    while len(prev_sts) < n:
        prev_sts.append(None)
    # Time-sort pack so "nearby" = adjacent clocks
    order = sorted(range(k), key=lambda i: _hhmm_to_min(shift_templates[i][0]))
    inv = [0] * k
    for rank, bi in enumerate(order):
        inv[bi] = rank

    # Seat plan for *today*. Thin rotation days may run fewer bands than the
    # home pack size — equal spacing of the full pack is not required daily.
    # Prefer a subset that spans the clock (24h continuity) over forcing all k.
    if n >= k * geo_need:
        counts = [n // k + (1 if i < n % k else 0) for i in range(k)]
    else:
        # How many distinct starts can we staff at geo_need each?
        n_active = max(1, min(k, max(1, n // geo_need)))
        # Prefer at least enough starts to tile ~24h at this length (soft goal)
        length_h = max(0.5, float(shift_length_hours or 8.0))
        span_goal = max(1, int(math.ceil(24.0 / length_h)))
        n_active = max(n_active, min(k, min(n, span_goal)))
        n_active = min(n_active, n)  # can't open more bands than bodies if need=1
        counts = [0] * k
        if n_active >= k:
            picks = list(order)
        elif n_active == 1:
            picks = [order[0]]
        else:
            picks = []
            for j in range(n_active):
                rank = int(round(j * (k - 1) / max(n_active - 1, 1)))
                bi = order[rank]
                if bi not in picks:
                    picks.append(bi)
            for bi in order:
                if len(picks) >= n_active:
                    break
                if bi not in picks:
                    picks.append(bi)
        na = max(1, len(picks))
        for j, bi in enumerate(picks):
            counts[bi] = n // na + (1 if j < n % na else 0)

    def _hour(i: int) -> int:
        try:
            return int(shift_templates[i][0].split(":")[0])
        except ValueError:
            return 0

    # Generic band classes (time-of-day only; window bias uses cover-set below)
    afternoon = [i for i in range(k) if 12 <= _hour(i) < 18]
    evening = [i for i in range(k) if 18 <= _hour(i) < 22]
    night = [i for i in range(k) if _hour(i) >= 22 or _hour(i) < 6]
    _morning = [i for i in range(k) if i not in afternoon and i not in evening and i not in night]  # noqa: F841 — band partition reserved

    # Window samples → covering bands (continuous min occupancy, not just union hits).
    # Each sample carries its own need (supports multiple windows same day).
    cover_bands: List[int] = []
    # (covering_band_indices, required_occupancy)
    window_samples: List[Tuple[List[int], int]] = []
    wmin = max(0, int(window_min or 0))
    length_m = max(30, int(round(float(shift_length_hours) * 60)))

    def _add_window_samples(w_start: str, w_end: str, need_occ: int) -> None:
        if need_occ <= 0 or not w_start or not w_end:
            return
        w_sm = _hhmm_to_min(w_start)
        w_em = _hhmm_to_min(w_end)
        win_len = (w_em - w_sm) % (24 * 60) or (24 * 60)
        t = 0
        while t < win_len:
            abs_m = (w_sm + t) % (24 * 60)
            covering: List[int] = []
            for i in range(k):
                sm = _hhmm_to_min(shift_templates[i][0])
                rel = (abs_m - sm) % (24 * 60)
                if rel < length_m:
                    covering.append(i)
            if covering:
                window_samples.append((covering, int(need_occ)))
                for bi in covering:
                    if bi not in cover_bands:
                        cover_bands.append(bi)
            t += 30

    if fri_sat_window:
        multi = list(active_windows or [])
        if multi:
            for aw in multi:
                if not isinstance(aw, dict):
                    continue
                try:
                    mo = int(aw.get("min_officers") or 0)
                except (TypeError, ValueError):
                    mo = 0
                st = str(aw.get("start_time") or aw.get("start") or "").strip()
                en = str(aw.get("end_time") or aw.get("end") or "").strip()
                if mo > 0 and st and en:
                    _add_window_samples(st, en, mo)
        elif wmin > 0 and window_start and window_end:
            _add_window_samples(window_start, window_end, wmin)

    def _enforce_floor():
        # Full roster day: keep every pack band at `need` when bodies allow.
        # Thin day: only rebalance among bands already open (don't force equal pack).
        # min_per_shift=0 → no per-band floor.
        if need <= 0:
            return
        if n >= k * need:
            targets = list(range(k))
        else:
            targets = [i for i in range(k) if counts[i] > 0]
        if not targets:
            return
        for i in targets:
            guard = 0
            while counts[i] < need and guard < 10:
                guard += 1
                rich = max(range(k), key=lambda j: counts[j])
                if counts[rich] <= need:
                    break
                counts[rich] -= 1
                counts[i] += 1

    def _give(group: List[int], want: int):
        if not group or want <= 0:
            return
        have = sum(counts[i] for i in group)
        guard = 0
        donor_floor = need if need > 0 else 0
        while have < want and guard < 20:
            guard += 1
            donors = [j for j in range(k) if j not in group and counts[j] > donor_floor]
            if not donors:
                donors = [j for j in range(k) if j not in group and counts[j] > 0]
            if not donors:
                # May open a closed pack band when window needs it (thin → denser)
                donors = [j for j in range(k) if j not in group]
            if not donors:
                break
            rich = max(donors, key=lambda j: counts[j])
            poor = min(group, key=lambda j: counts[j])
            if counts[rich] <= 0 and rich not in group:
                # pull one seat from richest active band
                active = [j for j in range(k) if counts[j] > 0 and j not in group]
                if not active:
                    break
                rich = max(active, key=lambda j: counts[j])
            if counts[rich] <= 0:
                break
            counts[rich] -= 1
            counts[poor] += 1
            have += 1

    def _sample_occ(covering: List[int]) -> int:
        return sum(counts[i] for i in covering)

    def _shortfall(sample: Tuple[List[int], int]) -> int:
        covering, need_occ = sample
        return max(0, int(need_occ) - _sample_occ(covering))

    def _rebalance_window_occupancy():
        """Raise occupancy on short window samples (per-sample need).

        Sequential bands (14:00 then 22:00 for 19–03) each need their need_occ
        seats on samples they cover. Multi-window days merge all samples.
        When preserve_247, never drain a band below 1 if that would leave fewer
        than span_goal open bands (keeps 24h tile alive).
        """
        if not window_samples or n < 1:
            return
        length_h = max(0.5, float(shift_length_hours or 8.0))
        span_goal = max(1, int(math.ceil(24.0 / length_h)))
        for _ in range(n * k + 8):
            thin = max(window_samples, key=_shortfall)
            if _shortfall(thin) <= 0:
                break
            covering, need_occ = thin
            # Prefer non-cover donors, then bands outside this sample
            non_cover = [j for j in range(k) if j not in cover_bands and counts[j] > 0]
            outside = [j for j in range(k) if j not in covering and counts[j] > 0]
            donors = non_cover or outside
            if not donors:
                break

            def _safe_donor(j: int) -> bool:
                if counts[j] <= 0:
                    return False
                if preserve_247 and counts[j] == 1:
                    open_n = sum(1 for i in range(k) if counts[i] > 0)
                    if open_n <= span_goal:
                        return False
                # Don't increase another sample's shortfall
                for s in window_samples:
                    if s is thin:
                        continue
                    cov_s, need_s = s
                    if j in cov_s and _sample_occ(cov_s) - 1 < need_s:
                        # only block if it would create/worsen shortfall below need
                        if _sample_occ(cov_s) <= need_s:
                            return False
                return True

            safe = [j for j in donors if _safe_donor(j)]
            if not safe:
                break
            rich = max(safe, key=lambda j: counts[j])
            poor = min(covering, key=lambda j: counts[j])
            if counts[rich] <= 0:
                break
            counts[rich] -= 1
            counts[poor] += 1

    _enforce_floor()
    if fri_sat_window and n >= 1 and (window_samples or wmin > 0):
        if window_samples:
            _rebalance_window_occupancy()
            # Second pass after floor in case min_ps stole seats
            if not preserve_247:
                _enforce_floor()
            _rebalance_window_occupancy()
        elif cover_bands:
            for bi in cover_bands:
                _give([bi], min(wmin, n))
            _enforce_floor()
        elif evening:
            _give(evening, min(wmin, n))
            _enforce_floor()
            if n >= wmin * 2:
                _give(night, min(wmin, n))
                _enforce_floor()
        elif n >= wmin * 2:
            _give(afternoon, min(wmin, n))
            _give(night, min(wmin, n))
            _enforce_floor()
    elif prefer_night:
        # High-risk night: stack onto night bands without collapsing 24h tile.
        # With n==span_goal (e.g. 3×8h), keep ≥1 on each open span band; only surplus
        # stacks night (else 0/1/2 loses morning and breaks 24/7).
        night_want = max(int(wmin or 0), 2)
        length_h = max(0.5, float(shift_length_hours or 8.0))
        span_goal = max(1, int(math.ceil(24.0 / length_h)))
        open_bands = [i for i in range(k) if counts[i] > 0]
        surplus = max(0, n - max(span_goal, len(open_bands)))
        # How many night seats we can add above 1 without emptying a span band
        if night and surplus > 0:
            _give(night, min(night_want, 1 + surplus))
        elif night and n > span_goal:
            # Still try mild night bias if we have more bodies than one tile
            _give(night, min(night_want, n - (span_goal - 1)))
        elif night and not open_bands:
            _give(night, min(night_want, n))
        elif not night:
            _give(evening + afternoon, min(night_want, n))

    # Seat multiset from target counts
    seats: List[int] = []
    for i in range(k):
        seats.extend([i] * max(0, counts[i]))
    while len(seats) < n:
        seats.append(order[0] if order else 0)
    seats = seats[:n]
    seat_avail = list(seats)

    # Assign each working officer: prefer home, then nearby hops, then any remaining seat
    hops = max(0, int(nearby_hops))
    assigned: List[Optional[int]] = [None] * n
    used = [False] * len(seat_avail)

    def _rest_ok(prev_st: Optional[str], band_i: int) -> bool:
        if min_rest <= 0 or not prev_st:
            return True
        try:
            from logic.staffing_optimizer import rest_gap_minutes

            gap = rest_gap_minutes(
                str(prev_st),
                shift_templates[int(band_i)][0],
                float(shift_length_hours),
                day_gap_days=1,
            )
            return gap >= min_rest * 60.0 - 1.0
        except Exception:
            return True

    def _take_seat(prefer: List[int], *, prev_st: Optional[str] = None) -> Optional[int]:
        # Prefer rest-legal seats first when min_rest binds
        ordered = list(prefer)
        if min_rest > 0 and prev_st:
            ordered = [b for b in ordered if _rest_ok(prev_st, b)] + [b for b in ordered if not _rest_ok(prev_st, b)]
        for want in ordered:
            for si, band in enumerate(seat_avail):
                if not used[si] and band == want:
                    used[si] = True
                    return band
        # Any remaining seat — rest-legal first
        rest_first = list(range(len(seat_avail)))
        if min_rest > 0 and prev_st:
            rest_first = sorted(
                rest_first,
                key=lambda si: (0 if (not used[si] and _rest_ok(prev_st, seat_avail[si])) else 1, si),
            )
        for si in rest_first:
            if not used[si]:
                used[si] = True
                return seat_avail[si]
        return None

    # Officers with rarer home bands first so they keep home when possible
    home_idxs = [
        _pack_band_index(getattr(s, "shift_start", "") or shift_templates[0][0], shift_templates) for s in working_slots
    ]
    order_off = sorted(
        range(n),
        key=lambda oi: (home_idxs.count(home_idxs[oi]), home_idxs[oi], oi),
    )
    for oi in order_off:
        home_i = home_idxs[oi]
        prev_st = prev_sts[oi] if oi < len(prev_sts) else None
        # Nearby in time-sorted pack rank space
        home_rank = inv[home_i]
        prefer_ranks = []
        for d in range(0, hops + 1):
            for sign in (0,) if d == 0 else (-1, 1):
                r = home_rank + sign * d
                if 0 <= r < k:
                    prefer_ranks.append(r)
        prefer_bands = [order[r] for r in prefer_ranks]
        # Rest-hard: if no nearby seat is rest-legal, try whole pack
        if min_rest > 0 and prev_st and not any(_rest_ok(prev_st, b) for b in prefer_bands):
            prefer_bands = prefer_bands + [order[r] for r in range(k) if order[r] not in prefer_bands]
        # Window-active: prefer seats on covering bands among nearby
        if fri_sat_window and cover_bands:
            cov_first = [b for b in prefer_bands if b in cover_bands] + [
                b for b in prefer_bands if b not in cover_bands
            ]
            prefer_bands = cov_first
        band = _take_seat(prefer_bands, prev_st=prev_st)
        assigned[oi] = band if band is not None else home_i

    return [shift_templates[int(assigned[i] if assigned[i] is not None else 0)] for i in range(n)]


def assign_pack_starts_for_coverage(
    n_working: int,
    shift_starts: List[str],
    shift_length_hours: float,
    *,
    home_starts: Optional[List[str]] = None,
    min_per_shift: int = 1,
    fri_sat_window: bool = False,
    nearby_hops: int = 1,
    window_min: int = 0,
    window_start: str = "",
    window_end: str = "",
    coverage_247: int = 0,
) -> List[Tuple[str, str]]:
    """Public helper for cheap filter + optimizer: pack starts with home/nearby model."""
    if n_working <= 0 or not shift_starts:
        return []
    templates = [(s, _end_for_start(s, shift_length_hours)) for s in shift_starts if s]
    if not templates:
        return []
    homes = list(home_starts or [])
    while len(homes) < n_working:
        homes.append(templates[len(homes) % len(templates)][0])

    class _S:
        def __init__(self, st: str):
            self.shift_start = st

    slots = [_S(homes[i]) for i in range(n_working)]
    return _balance_day_assignments(
        slots,  # type: ignore[arg-type]
        templates,
        min_per_shift=min_per_shift,
        prefer_night=fri_sat_window,
        fri_sat_window=fri_sat_window,
        nearby_hops=nearby_hops,
        window_min=window_min,
        window_start=window_start,
        window_end=window_end,
        shift_length_hours=shift_length_hours,
        coverage_247=int(coverage_247 or 0),
    )


def _hhmm_to_min(label: str) -> int:
    try:
        parts = (label or "00:00").strip().split(":")
        return int(parts[0]) * 60 + (int(parts[1]) if len(parts) > 1 else 0)
    except (TypeError, ValueError):
        return 0


def _min_to_hhmm(total: int) -> str:
    total = int(total) % (24 * 60)
    return f"{total // 60:02d}:{total % 60:02d}"


def _end_for_start(start: str, length_hours: float) -> str:
    return _min_to_hhmm(_hhmm_to_min(start) + int(round(float(length_hours) * 60)))


def _half_hour_grid() -> List[str]:
    return [_min_to_hhmm(h * 60 + m) for h in range(24) for m in (0, 30)]


def _coverage_bins(
    starts: List[str],
    length_hours: float,
    *,
    prev_starts: Optional[List[str]] = None,
) -> List[int]:
    """48 half-hour bins for calendar day D.

    Includes overnight tails from *previous* day's starts (covers 00:00–morning).
    Today's overnight wraps into morning bins for scoring next-day handoff.
    """
    bins = [0] * 48
    length_m = max(30, int(round(float(length_hours) * 60)))

    def _add(start_label: str, *, from_prev: bool) -> None:
        sm = _hhmm_to_min(start_label)
        t = 0
        while t < length_m:
            abs_m = sm + t
            if from_prev:
                # Prior duty day: only spill after midnight into this calendar morning
                if abs_m >= 24 * 60:
                    bins[((abs_m - 24 * 60) // 30) % 48] += 1
            else:
                # Today: only minutes on this calendar day (0..24h). Overnight
                # tail covers *tomorrow* morning via prev_starts handoff.
                if abs_m < 24 * 60:
                    bins[(abs_m // 30) % 48] += 1
            t += 30

    for s in prev_starts or []:
        _add(s, from_prev=True)
    for s in starts:
        _add(s, from_prev=False)
    return bins


def _day_start_score_fast(
    starts: List[str],
    length_hours: float,
    *,
    min_247: int,
    window_min: int,
    window_start: str,
    window_end: str,
    fri_sat: bool,
    prev_starts: Optional[List[str]] = None,
) -> Tuple[float, int, int]:
    """Higher better. Fast bin occupancy (includes prior overnight tails)."""
    if not starts and not prev_starts:
        return -1e9, 0, 0
    bins = _coverage_bins(starts, length_hours, prev_starts=prev_starts)
    min247 = min(bins) if bins else 0
    win_occ = min247
    if fri_sat and window_min > 0:
        ws = _hhmm_to_min(window_start)
        we = _hhmm_to_min(window_end)
        if we > ws:
            idxs = list(range(ws // 30, max(ws // 30 + 1, (we + 29) // 30)))
        else:
            # 19:00–03:00: evening bins + early morning (from today's overnight or prev)
            idxs = list(range(ws // 30, 48)) + list(range(0, max(1, (we + 29) // 30)))
        win_occ = min(bins[i % 48] for i in idxs) if idxs else 0
    score = float(min247) * 1000.0
    if min_247 > 0 and min247 < min_247:
        score -= 50_000.0  # hard preference: never pick a plan with 24/7 holes
    if fri_sat:
        score += float(win_occ) * 800.0
        if window_min > 0 and win_occ < window_min:
            score -= 40_000.0
        if win_occ >= window_min:
            score += 5000.0
    if min_247 > 0 and min247 >= min_247:
        score += 3000.0
    score -= len(set(starts)) * 0.25
    return score, int(min247), int(win_occ)


def _assign_flexible_day_starts(
    n: int,
    length_hours: float,
    *,
    min_247: int = 0,
    fri_sat_window: bool = False,
    window_min: int = 0,
    window_start: str = "19:00",
    window_end: str = "03:00",
    hint_templates: Optional[List[Tuple[str, str]]] = None,
    prev_starts: Optional[List[str]] = None,
) -> List[Tuple[str, str]]:
    """
    Pick start times for *today's* working officers from the half-hour grid.

    Bands move by day: Fri can load 19:00 swings; other days rebalance for 24/7.
    Uses prior day's starts for overnight continuity into this morning.
    Defaults: min_247/window_min=0 (off) — callers pass real floors; do not invent 1/2.
    """
    if n <= 0:
        return []
    length_hours = max(0.5, float(length_hours))
    need247 = max(0, int(min_247))
    wmin = max(0, int(window_min)) if fri_sat_window else 0
    win_s = window_start if window_start else "19:00"
    prev = list(prev_starts or [])

    patterns: List[List[str]] = []

    def _add_pat(starts: List[str]) -> None:
        if len(starts) == n:
            patterns.append(list(starts))

    # Equal spacing is *one* option — not preferred over uneven packs
    for base in (0, 30, 60, 90, 120, 180, 240, 300, 360, 420, 480):
        step = max(30, (24 * 60) // max(n, 1))
        _add_pat([_min_to_hhmm(base + i * step) for i in range(n)])

    # Uneven steps (different gap between starts — not equal-spaced)
    for base in (5 * 60, 6 * 60, 7 * 60):
        for gaps in ((8 * 60, 6 * 60), (7 * 60, 5 * 60), (10 * 60, 4 * 60), (5 * 60, 5 * 60, 8 * 60)):
            starts = []
            t = base
            starts.append(_min_to_hhmm(t))
            for g in gaps:
                t = (t + g) % (24 * 60)
                starts.append(_min_to_hhmm(t))
                if len(starts) >= n:
                    break
            if len(starts) < n:
                # pad by stacking on last / first for thin multi-on-one-band days
                while len(starts) < n:
                    starts.append(starts[len(starts) % max(1, len(starts))])
            _add_pat(starts[:n])

    # k-band packs with round-robin load (k may be < n → fewer shifts, more doubles)
    for k in range(1, min(6, n) + 1):
        for base in (5 * 60, 6 * 60, 7 * 60, 8 * 60, 14 * 60, 19 * 60):
            # equal and uneven step variants
            for step in (max(30, (24 * 60) // max(k, 1)), 5 * 60, 7 * 60, 10 * 60):
                bands = [_min_to_hhmm((base + i * step) % (24 * 60)) for i in range(max(k, 1))]
                # unique-ish preserve order
                uniq = []
                for b in bands:
                    if b not in uniq:
                        uniq.append(b)
                if not uniq:
                    continue
                _add_pat([uniq[i % len(uniq)] for i in range(n)])

    # Named LE packs (optional shapes — day picker may choose a different set tomorrow)
    for trip in (
        ["06:00", "14:00", "22:00"],
        ["07:00", "15:00", "23:00"],
        ["05:00", "13:00", "21:00"],
        ["06:00", "14:00", "19:00"],
        ["06:00", "14:00", "19:00", "22:00"],
        ["07:00", "15:00", "19:00", "23:00"],
        ["06:00", "12:00", "18:00", "00:00"],
        ["06:00", "18:00"],
        ["07:00", "19:00"],
        ["14:00", "22:00"],
        ["19:00", "07:00"],
    ):
        if len(trip) <= n:
            _add_pat([trip[i % len(trip)] for i in range(n)])
        elif n < len(trip):
            # Thin day: take a subset of the pack, not the full equal grid
            _add_pat(list(trip[:n]))
            _add_pat([trip[i] for i in range(0, len(trip), max(1, len(trip) // n))][:n])

    # Fri/Sat: window + 24/7 with overnight handoff awareness
    if fri_sat_window and wmin > 0:
        if n >= 4:
            for core in (
                [win_s, win_s, "06:00", "14:00"],
                [win_s, win_s, "06:00", "22:00"],
                [win_s, win_s, "14:00", "22:00"],
                ["06:00", "14:00", win_s, "22:00"],
                ["06:00", "14:00", "14:00", "22:00"],
                ["06:00", "14:00", "22:00", "22:00"],
            ):
                starts = list(core)
                while len(starts) < n:
                    starts.append("10:00")
                _add_pat(starts[:n])
        if n >= 5:
            _add_pat(([win_s, win_s, "06:00", "14:00", "22:00"] + ["10:00"] * 3)[:n])

    if hint_templates:

        class _S:
            pass

        fake = [_S() for _ in range(n)]
        bal = _balance_day_assignments(
            fake,  # type: ignore[arg-type]
            hint_templates,
            min_per_shift=1,
            prefer_night=fri_sat_window,
            fri_sat_window=fri_sat_window,
        )
        if bal and len(bal) >= n:
            _add_pat([b[0] for b in bal[:n]])

    def _score(pat: List[str]) -> float:
        use_prev = prev
        if not use_prev:
            use_prev = [s for s in pat if _hhmm_to_min(s) >= 18 * 60 or _hhmm_to_min(s) < 6 * 60] or ["22:00"]
        # Window span that crosses midnight: also credit today's starts that
        # spill into early morning (e.g. 19:00→03:00).
        sc, min247, win_occ = _day_start_score_fast(
            pat,
            length_hours,
            min_247=need247,
            window_min=wmin,
            window_start=win_s,
            window_end=window_end or "03:00",
            fri_sat=bool(fri_sat_window),
            prev_starts=use_prev,
        )
        if fri_sat_window and wmin > 0:
            # Prefer dedicated evening starts (same clock all night) — department style.
            n_evening = sum(
                1
                for s in pat
                if abs(_hhmm_to_min(s) - _hhmm_to_min(win_s)) <= 30
                or _hhmm_to_min(s) in (18 * 60, 18 * 60 + 30, 19 * 60, 19 * 60 + 30)
            )
            if n_evening >= wmin:
                sc += 25_000.0
            else:
                sc -= 15_000.0
                sc += n_evening * 2_000.0
        return sc

    best: List[str] = []
    best_sc = -1e18
    for pat in patterns:
        sc = _score(pat)
        if sc > best_sc:
            best_sc = sc
            best = pat
    if not best:
        step = max(30, (24 * 60) // max(n, 1))
        best = [_min_to_hhmm(i * step) for i in range(n)]

    # Safety valve only: if the scored winner has zero evening-class starts when
    # the window requires them, inject a fallback spine.  This is a last resort—
    # the scorer already awards +25_000 for meeting wmin evening starts, so a good
    # pattern list will always win before this fires.  The old unconditional block
    # was removed because it discarded the entire scoring loop on n≥4, and
    # produced broken plans for 10h/12h shifts (22:00+10h = 08:00 next day leaves
    # a 03:00–06:00 gap that the fixed spine cannot patch).
    if fri_sat_window and wmin > 0 and best:
        n_eve_best = sum(
            1
            for s in best
            if abs(_hhmm_to_min(s) - _hhmm_to_min(win_s)) <= 60
            or _hhmm_to_min(s) in (18 * 60, 18 * 60 + 30, 19 * 60, 19 * 60 + 30)
        )
        if n_eve_best == 0:
            # Degenerate case: scorer found nothing evening-adjacent at all.
            spine = [win_s] * min(wmin, n)
            for s in ("06:00", "14:00", "22:00"):
                if len(spine) >= n:
                    break
                spine.append(s)
            while len(spine) < n:
                spine.append("10:00")
            best = spine[:n]

    return [(s, _end_for_start(s, length_hours)) for s in best]


def _snap_half_hour(hours: float) -> float:
    """Nearest 0.5h using half-up (avoid banker's round of 10.25 → 10.0)."""
    return math.floor(float(hours) * 2 + 0.5) / 2.0


def _patterns_for_config(config: SimulatorConfig):
    """Optional multi-block / fixed-rotating patterns; empty list → use squad preset path."""
    from logic.rotation_patterns import build_pattern, validate_variation_set

    texts = [t for t in (config.rotation_variations or []) if (t or "").strip()]
    if not texts:
        return []
    style = (config.rotation_style or "").strip().lower() or None
    patterns = []
    for t in texts:
        patterns.append(build_pattern(t, style=style if style in ("fixed", "rotating") else None))
    ok, msg = validate_variation_set(patterns)
    if not ok:
        raise ValueError(msg)
    return patterns


def _flsa_period_hours_ok(
    work_day_flags: List[bool],
    shift_hours: float,
    period_days: int,
    threshold: float,
) -> bool:
    """True if some fixed §207(k) anchor has no full period over threshold (non-sliding)."""
    if period_days < 1 or not work_day_flags:
        return True
    n = len(work_day_flags)
    # Short horizon: pro-rate threshold (no complete work period in the sim window).
    if n < period_days:
        hours = sum(1 for d in work_day_flags if d) * shift_hours
        return hours <= threshold * (n / float(period_days)) + 1e-6

    # Department may pick work-period start (anchor). Only complete periods count —
    # partial trailing stubs must not greenwash a heavy pattern.
    for anchor in range(period_days):
        if anchor > n - period_days:
            break
        ok = True
        for start in range(anchor, n - period_days + 1, period_days):
            hours = sum(1 for d in work_day_flags[start : start + period_days] if d) * shift_hours
            if hours > threshold + 1e-6:
                ok = False
                break
        if ok:
            return True
    return False


def _max_work_ratio(config: SimulatorConfig) -> float:
    """Best-case work fraction across multi-block / squad duty rings."""
    max_work_ratio = 0.0
    try:
        custom_patterns = _patterns_for_config(config)
        for p in custom_patterns:
            vec = p.duty_vector()
            if vec and len(vec) > 0:
                max_work_ratio = max(max_work_ratio, sum(1 for x in vec if x) / len(vec))
    except Exception:
        pass

    if max_work_ratio <= 0.0:
        from config import ROTATION_PRESETS

        preset = ROTATION_PRESETS.get(config.rotation_type)
        if preset:
            cycle_len = max(1, int(preset.get("cycle_length") or 1))
            if "squad_a_days" in preset:
                max_work_ratio = len(preset["squad_a_days"]) / cycle_len
            elif "squad_patterns" in preset:
                for _sq_name, pattern in (preset.get("squad_patterns") or {}).items():
                    if pattern and len(pattern) > 0:
                        max_work_ratio = max(
                            max_work_ratio,
                            sum(1 for x in pattern if x) / len(pattern),
                        )
    return float(max_work_ratio) if max_work_ratio > 0.0 else 1.0


def _window_duration_hours(start_time: str, end_time: str) -> float:
    """Half-open window length in hours (overnight wrap OK)."""
    try:
        ws = _hhmm_to_min(start_time)
        we = _hhmm_to_min(end_time)
    except Exception:
        return 0.0
    if we > ws:
        return (we - ws) / 60.0
    if we == ws:
        return 24.0
    return (24 * 60 - ws + we) / 60.0


def _window_weekly_person_hours(config: SimulatorConfig) -> float:
    """Sum of (min_officers × window_hours × days_per_week) for enabled windows."""
    if not getattr(config, "use_extra_windows", False) or not config.extra_windows:
        return 0.0
    from logic.coverage_timeline import normalize_weekdays

    total = 0.0
    for w in config.extra_windows or []:
        if not isinstance(w, dict) or w.get("enabled") is False:
            continue
        try:
            need = int(w.get("min_officers") or 0)
        except (TypeError, ValueError):
            need = 0
        if need <= 0:
            continue
        st = str(w.get("start_time") or w.get("start") or "").strip()
        en = str(w.get("end_time") or w.get("end") or "").strip()
        if not st or not en:
            continue
        hours = _window_duration_hours(st, en)
        if hours <= 0:
            continue
        wds = normalize_weekdays(w.get("weekday", w.get("weekdays", w.get("dow"))))
        days = 7 if wds is None else max(1, len(set(wds)))
        total += float(need) * hours * float(days)
    return total


def _concurrent_body_floor(config: SimulatorConfig) -> int:
    """
    Concurrent ON-body demand from hard coverage floors.

    min_per_shift applies to *used* starts only (thin multi-block days may run
    fewer bands) — do **not** multiply by full pack band count.
    """
    import math

    daily_bodies = 0
    min_ps = max(0, int(config.min_per_shift or 0))
    if min_ps > 0:
        daily_bodies = max(daily_bodies, min_ps)

    if config.coverage_247 and int(config.coverage_247 or 0) > 0:
        shift_length = float(config.shift_length_hours or 8.0)
        if shift_length > 0:
            bodies_247 = max(1, math.ceil(24.0 / shift_length)) * int(config.coverage_247)
            daily_bodies = max(daily_bodies, bodies_247)

    if getattr(config, "use_extra_windows", False) and config.extra_windows:
        for w in config.extra_windows or []:
            if not isinstance(w, dict) or not w.get("enabled", True):
                continue
            try:
                need = int(w.get("min_officers") or 0)
            except (TypeError, ValueError):
                need = 0
            if need > 0:
                daily_bodies = max(daily_bodies, need)

    return int(daily_bodies)


def _theoretical_min_officers(config: SimulatorConfig) -> int:
    """
    Lower-bound headcount: concurrent body floor ÷ max work fraction.

    Average daily ON = N × work_frac ≥ body floor (phase-invariant bound).
    """
    import math

    daily_bodies = _concurrent_body_floor(config)
    if daily_bodies <= 0:
        return 1
    work_frac = _max_work_ratio(config)
    return max(1, math.ceil(float(daily_bodies) / float(work_frac)))


def _get_all_duty_vectors(config: SimulatorConfig) -> List[List[bool]]:
    try:
        custom = _patterns_for_config(config)
        if custom:
            return [p.duty_vector() for p in custom if p.duty_vector()]
    except Exception:
        pass

    from config import ROTATION_PRESETS

    preset = ROTATION_PRESETS.get(config.rotation_type)
    if not preset:
        return []

    vectors = []
    cycle_len = preset.get("cycle_length", 1)
    if "squad_patterns" in preset:
        for pattern in preset["squad_patterns"].values():
            if pattern:
                vectors.append([bool(x) for x in pattern])
    elif "squad_a_days" in preset:
        squad_a = preset["squad_a_days"]
        vectors.append([(i + 1) in squad_a for i in range(cycle_len)])
    return vectors


def _pre_simulation_fast_fail(config: SimulatorConfig) -> Tuple[bool, str]:
    """Check pattern-intrinsic hard constraints that mathematically cannot pass."""
    import math

    # 1. Structural 24/7 check
    if getattr(config, "coverage_247", 0) > 0:
        shift_templates = generate_shift_templates(
            config.shift_length_hours or 8.0,
            config.shift_starts,
            use_department_shifts=config.apply_department_rules and not config.shift_starts,
        )
        if shift_templates:
            covered = [False] * 1440
            duration_m = int((config.shift_length_hours or 8.0) * 60)
            for st, _ in shift_templates:
                st_m = _hhmm_to_min(st)
                for i in range(duration_m):
                    covered[(st_m + i) % 1440] = True
            if not all(covered):
                return True, "Shift bands leave structural gaps; 24/7 coverage is impossible."

    # 1a2. Synchronized OFF days: single-ring presets without phase stagger cannot 24/7
    if int(getattr(config, "coverage_247", 0) or 0) > 0:
        try:
            from config import ROTATION_PRESETS as _RP

            _pre = _RP.get(config.rotation_type) or {}
            if (
                _pre
                and _squad_union_has_off_day(_pre)
                and not bool(getattr(config, "stagger_phases", True))
                and not getattr(config, "rotation_variations", None)
            ):
                return (
                    True,
                    "Rotation leaves cycle day(s) with all officers OFF; "
                    "enable phase stagger or use complementary squads for 24/7.",
                )
        except Exception:
            pass

    # 1b. Headcount vs 24/7 concurrent floor (avg ON = N×work_frac).
    # Runs for any fixed N>0 (auto_min_officers only gates blank-N search, not this).
    # Do **not** hard-abort on window mins alone — impossible windows still run so
    # metrics (extra_window_failures) and optimizer near-misses stay populated.
    n_off = int(getattr(config, "num_officers", 0) or 0)
    if n_off > 0 and int(getattr(config, "coverage_247", 0) or 0) > 0:
        shift_length = float(config.shift_length_hours or 8.0)
        bodies_247 = (
            max(1, math.ceil(24.0 / shift_length)) * int(config.coverage_247)
            if shift_length > 0
            else int(config.coverage_247)
        )
        if n_off < bodies_247:
            return (
                True,
                f"Officers ({n_off}) < 24/7 concurrent body floor ({bodies_247}).",
            )
        work_frac = _max_work_ratio(config)
        avg_on = float(n_off) * float(work_frac)
        if avg_on + 1e-9 < float(bodies_247):
            need_n = max(1, math.ceil(float(bodies_247) / float(work_frac)))
            return (
                True,
                f"Avg daily ON ≤{avg_on:.1f} (work frac {work_frac:.2%}) "
                f"but 24/7 needs {bodies_247} bodies — try ≥{need_n} officers.",
            )

    vectors = _get_all_duty_vectors(config)
    if not vectors:
        return False, ""

    # 2. Min rest — best rest between consecutive ON days across pack starts
    min_rest = float(getattr(config, "min_rest_hours", 0) or 0)
    if min_rest > 0:
        has_adjacent = False
        for vec in vectors:
            if not vec:
                continue
            n = len(vec)
            for i in range(2 * n - 1):
                if vec[i % n] and vec[(i + 1) % n]:
                    has_adjacent = True
                    break
            if has_adjacent:
                break
        if has_adjacent:
            starts = [s for s in (config.shift_starts or []) if s]
            if not starts:
                try:
                    starts = [
                        st
                        for st, _ in generate_shift_templates(
                            config.shift_length_hours or 8.0,
                            None,
                            use_department_shifts=bool(config.apply_department_rules),
                        )
                    ]
                except Exception:
                    starts = []
            length = float(config.shift_length_hours or 8.0)
            try:
                from logic.staffing_optimizer import max_rest_minutes_for_pack

                hops = max(0, int(getattr(config, "nearby_start_hops", 1) or 0))
                max_r = max_rest_minutes_for_pack(
                    starts or ["06:00"],
                    length,
                    day_gap_days=1,
                    nearby_hops=hops,
                )
            except Exception:
                # Same-start rest only
                max_r = max(0, 24 * 60 - int(round(length * 60)))
            if max_r < min_rest * 60.0 - 1.0:
                return (
                    True,
                    f"Start pack cannot leave {min_rest:g}h rest between consecutive ON days "
                    f"(best ≈{max_r / 60.0:.1f}h).",
                )
            # 24/7 staffs every band every day — each start must transition to *some*
            # next-day start with enough rest (overnight→overnight often caps at 16h @8h).
            if int(getattr(config, "coverage_247", 0) or 0) > 0 and starts:
                try:
                    from logic.staffing_optimizer import rest_gap_minutes

                    worst_best = 10**9
                    worst_prev = starts[0]
                    for prev in starts:
                        best = max(rest_gap_minutes(prev, curr, length, day_gap_days=1) for curr in starts)
                        if best < worst_best:
                            worst_best = best
                            worst_prev = prev
                    if worst_best < min_rest * 60.0 - 1.0:
                        return (
                            True,
                            f"24/7 needs start {worst_prev} every day; best rest to any "
                            f"pack start next day is ≈{worst_best / 60.0:.1f}h "
                            f"(need {min_rest:g}h).",
                        )
                except Exception:
                    pass

    max_c = int(getattr(config, "max_consecutive_work_days", 0) or 0)
    if max_c > 0:
        for vec in vectors:
            if not vec:
                continue
            doubled = vec + vec
            streak = 0
            for working in doubled:
                if working:
                    streak += 1
                    if streak > max_c:
                        return True, f"Rotation mathematically violates max consecutive days (>{max_c})."
                else:
                    streak = 0

    # FLSA is counted in Phase 3 with flsa_violations metrics — do not hard-abort here
    # (empty metrics break detect/report paths and unit proofs).

    # Annual hard: envelope across duty rings (mixed multi-block can hit mid-band)
    if getattr(config, "annual_hours_hard", False):
        length = float(config.shift_length_hours or 8.0)
        projections: List[float] = []
        for vec in vectors:
            if not vec:
                continue
            working_days = sum(1 for x in vec if x)
            cycle_length = len(vec)
            projections.append(round((working_days / cycle_length) * 365.25 * length, 1))
        if projections:
            target = float(config.annual_hours_target)
            band = float(getattr(config, "annual_hours_variance", 0) or 0)
            if band <= 0:
                band = abs(target) * 0.02
            lo, hi = min(projections), max(projections)
            best = min(projections, key=lambda h: abs(h - target))
            can_hit = (lo - band) <= target <= (hi + band) or abs(best - target) <= band + 1.0
            if not can_hit:
                return (
                    True,
                    f"Duty annual hours [{lo:.0f}–{hi:.0f}] cannot hit {target:g}±{band:g}.",
                )

    return False, ""


def _auto_min_officer_search(config: SimulatorConfig, max_n: int = 80) -> Tuple[int, Optional["SimulatorResult"]]:
    """Bisect search for smallest N that yields a hard-constraint-passing simulation.

    Uses a true binary search: O(log N) full-sim calls instead of O(N).
    Falls back to the best soft-pass found if no N satisfies hard constraints.
    """
    best_soft: Optional[SimulatorResult] = None
    best_soft_n: int = max_n

    _last_pass: dict = {"n": None, "result": None}

    def _try(n: int) -> bool:
        """Return True when N passes hard constraints; cache any soft pass."""
        nonlocal best_soft, best_soft_n
        trial = SimulatorConfig(**{**config.__dict__, "num_officers": n, "auto_min_officers": False})
        result = _simulate_schedule_fixed_n(trial)
        if not result.success:
            return False
        if result.metrics.get("hard_constraints_ok", True):
            _last_pass["n"] = n
            _last_pass["result"] = result
            return True
        # Soft pass — keep as fallback
        if best_soft is None or n < best_soft_n:
            best_soft_n, best_soft = n, result
        return False

    theoretical_min = _theoretical_min_officers(config)

    # Phase 1: find an upper bound that works (doubles from theoretical_min)
    lo = theoretical_min
    hi = theoretical_min
    while hi <= max_n and not _try(hi):
        hi = min(hi * 2 if hi > 0 else 2, max_n)
        if hi == max_n and not _try(hi):
            return best_soft_n, best_soft

    # Phase 2: bisect lo..hi to find the minimum passing N
    lo = max(theoretical_min, hi // 2)
    while lo < hi:
        mid = (lo + hi) // 2
        if _try(mid):
            hi = mid
        else:
            lo = mid + 1

    # Confirm and return
    if _last_pass["n"] == hi and _last_pass["result"]:
        return hi, _last_pass["result"]
    return best_soft_n, best_soft


def simulate_schedule(config: SimulatorConfig) -> SimulatorResult:
    fails, msg = _pre_simulation_fast_fail(config)
    if fails:
        return SimulatorResult(success=False, message=msg)

    try:
        raw_len = float(config.shift_length_hours)
    except (TypeError, ValueError):
        return SimulatorResult(success=False, message="Shift length must be a number")
    if raw_len <= 0:
        return SimulatorResult(success=False, message="Shift length must be positive")
    # Require exact 0.5h steps (10.5 ok; 10.25 rejected)
    if abs(raw_len * 2 - round(raw_len * 2)) > 1e-6:
        return SimulatorResult(success=False, message="Shift length must be in 0.5 hour steps")
    config.shift_length_hours = _snap_half_hour(raw_len)

    if config.num_officers < 1 and config.auto_min_officers:
        min_n, result = _auto_min_officer_search(config)
        if result is None:
            return SimulatorResult(
                success=False,
                message="Could not find any officer count that meets hard constraints",
            )
        result.metrics["min_officers_required"] = min_n
        result.metrics["auto_sized"] = True
        result.message = f"Simulation complete (auto min officers = {min_n})"
        return result

    if config.num_officers < 1:
        return SimulatorResult(success=False, message="At least one officer is required (or leave blank for auto min)")

    return _simulate_schedule_fixed_n(config)


def _simulate_schedule_fixed_n(config: SimulatorConfig) -> SimulatorResult:
    preset = ROTATION_PRESETS.get(config.rotation_type)
    if not preset:
        # Allow custom multi-block only runs with a fallback equal_split preset
        if config.rotation_variations:
            preset = {
                "cycle_length": 14,
                "squads": 2,
                "work_days_per_cycle": 7,
                "label": "custom-variations",
            }
        else:
            return SimulatorResult(success=False, message=f"Unknown rotation type: {config.rotation_type}")

    try:
        custom_patterns = _patterns_for_config(config)
    except ValueError as exc:
        return SimulatorResult(success=False, message=str(exc))

    shift_templates = generate_shift_templates(
        config.shift_length_hours,
        config.shift_starts,
        use_department_shifts=config.apply_department_rules and not config.shift_starts,
    )
    if not shift_templates:
        return SimulatorResult(success=False, message="Could not build shift templates")

    roster_officers = None
    if config.apply_department_rules:
        from logic import get_officers_by_seniority

        roster_officers = [o for o in get_officers_by_seniority() if o.get("active") == 1]
    slots = _assign_officers(config.num_officers, shift_templates, preset, roster_officers)

    # Attach rotation variation + phase when multi-block patterns provided.
    # Stagger by spreading phases evenly across the cycle (not 0,0,1,1…).
    # Staffing optimizer may pass phase_overrides / pattern_slot_map for deep search.
    slot_patterns = []
    if custom_patterns:
        cycle_length = custom_patterns[0].cycle_length
        n_slots = max(len(slots), 1)
        n_pat = len(custom_patterns)
        # Pad short pattern maps with round-robin (do not silently ignore short maps)
        if config.pattern_slot_map:
            slot_pat_idx = [
                int(config.pattern_slot_map[i]) % n_pat if i < len(config.pattern_slot_map) else (i % n_pat)
                for i in range(n_slots)
            ]
        else:
            slot_pat_idx = [i % n_pat for i in range(n_slots)]
        sim_start = config.sim_start_date or date.today()
        best_phases = [0] * n_slots
        # Pad short phase lists with even stagger for remaining slots
        if config.phase_overrides is not None:
            step0 = max(1, cycle_length // max(n_slots, 1))
            for i in range(n_slots):
                if i < len(config.phase_overrides):
                    best_phases[i] = int(config.phase_overrides[i]) % max(cycle_length, 1)
                else:
                    best_phases[i] = (i * step0) % max(cycle_length, 1)
        elif config.stagger_phases and n_slots > 1:
            import math as _math_phase

            best_score = -(10**9)
            # Concurrent body floors from user constraints only (not pack_bands×min_ps)
            everyday_floor = 0
            if int(config.coverage_247 or 0) > 0:
                _L = float(config.shift_length_hours or 8.0)
                if _L > 0:
                    everyday_floor = max(
                        everyday_floor,
                        max(1, _math_phase.ceil(24.0 / _L)) * int(config.coverage_247),
                    )
            _min_ps = int(config.min_per_shift or 0)
            if _min_ps > 0:
                # Used-start floor only — thin multi-block days may run fewer bands
                everyday_floor = max(everyday_floor, _min_ps)
            everyday_floor = min(everyday_floor, n_slots) if everyday_floor > 0 else 0
            window_floor_by_wd: Dict[int, int] = {}
            if config.use_extra_windows and config.extra_windows:
                from logic.coverage_timeline import normalize_weekdays

                for w in config.extra_windows:
                    if not isinstance(w, dict) or w.get("enabled") is False:
                        continue
                    try:
                        mo = int(w.get("min_officers") or 0)
                    except (TypeError, ValueError):
                        continue
                    if mo <= 0:
                        continue
                    wds = normalize_weekdays(w.get("weekday", w.get("weekdays", w.get("dow"))))
                    if wds is None:
                        everyday_floor = max(everyday_floor, min(mo, n_slots))
                    else:
                        for wi in wds:
                            window_floor_by_wd[wi] = max(window_floor_by_wd.get(wi, 0), min(mo, n_slots))
            for step in range(1, min(4, cycle_length // 2 + 1)):
                for offset in range(0, cycle_length, max(1, cycle_length // 4)):
                    trial = [((i * step) + offset) % cycle_length for i in range(n_slots)]
                    day_counts = []
                    body_penalty = 0
                    for day_offset in range(max(config.simulation_days, cycle_length)):
                        cycle_day = (day_offset % cycle_length) + 1
                        working = 0
                        for i in range(n_slots):
                            p = custom_patterns[slot_pat_idx[i]].with_phase(trial[i])
                            if p.is_working(cycle_day):
                                working += 1
                        day_counts.append(working)
                        cal = sim_start + timedelta(days=day_offset)
                        need = everyday_floor
                        if cal.weekday() in window_floor_by_wd:
                            need = max(need, window_floor_by_wd[cal.weekday()])
                        if need > 0 and working < need:
                            body_penalty += (need - working) * 200
                    score = (
                        min(day_counts) * 1000
                        + sorted(day_counts)[min(1, len(day_counts) - 1)] * 50
                        - (max(day_counts) - min(day_counts))
                        - body_penalty
                    )
                    if score > best_score:
                        best_score = score
                        best_phases = trial
        for i, slot in enumerate(slots):
            base_p = custom_patterns[slot_pat_idx[i]]
            if config.phase_overrides is not None or config.stagger_phases:
                phase = best_phases[i]
            else:
                phase = 0
            slot_patterns.append(base_p.with_phase(phase))
        squad_a_days = set()
    elif config.apply_department_rules:
        from logic.rotation_config import get_active_rotation_cycle_length, get_active_squad_a_days

        cycle_length = get_active_rotation_cycle_length()
        squad_a_days = set(get_active_squad_a_days())
        sim_start = config.sim_start_date or date.today()
    else:
        cycle_length = preset["cycle_length"]
        squad_a_days = set(preset.get("squad_a_days", {1, 2, 5, 6, 7, 10, 11}))
        sim_start = config.sim_start_date or date.today()

    per_slot_work_flags: List[List[bool]] = [[] for _ in slots]
    # Squad-path duty phases (stagger single-pattern rings so OFF days are not global)
    squad_phases: List[int] = [0] * len(slots)
    if not custom_patterns:
        squad_phases = _squad_phase_offsets(
            preset,
            len(slots),
            stagger=bool(getattr(config, "stagger_phases", True)),
            phase_overrides=config.phase_overrides if not config.apply_department_rules else None,
        )
    # --- PHASE 1: Pure Math Evaluation ---
    for day_offset in range(config.simulation_days):
        cycle_day = (day_offset % cycle_length) + 1
        for si, slot in enumerate(slots):
            if custom_patterns:
                working = slot_patterns[si].is_working(cycle_day)
            elif config.apply_department_rules:
                from logic.rotation_config import is_squad_working

                # Department live rotation: honor real squad calendars (no synthetic phase)
                working = is_squad_working(slot.squad, cycle_day, preset)
            else:
                working = _squad_working(
                    config.rotation_type,
                    slot.squad,
                    cycle_day,
                    preset,
                    phase=squad_phases[si] if si < len(squad_phases) else 0,
                )
            per_slot_work_flags[si].append(working)
            if working:
                slot.work_days_in_sim += 1

    hours_per_work_day = config.shift_length_hours
    if custom_patterns and slot_patterns:
        from logic.rotation_patterns import projected_annual_hours

        for si, slot in enumerate(slots):
            slot.projected_annual_hours = projected_annual_hours(slot_patterns[si], config.shift_length_hours)
    else:
        annual_factor = 365 / max(config.simulation_days, 1)
        for slot in slots:
            slot.projected_annual_hours = round(slot.work_days_in_sim * hours_per_work_day * annual_factor, 1)

    hours_list = [s.projected_annual_hours for s in slots]
    avg_hours = sum(hours_list) / len(hours_list) if hours_list else 0
    hours_range_ratio = 0.0
    if hours_list and avg_hours:
        hours_range_ratio = (max(hours_list) - min(hours_list)) / avg_hours

    annual_band_outside = 0
    annual_mean_outside = 0
    annual_unfair = 0
    annual_hours_spread = 0.0
    from logic.rotation_patterns import annual_hours_within_band

    for slot in slots:
        ok_band, _lo, _hi, dist = annual_hours_within_band(
            slot.projected_annual_hours,
            config.annual_hours_target,
            variance_hours=config.annual_hours_variance,
        )
        if not ok_band:
            annual_band_outside += 1

    if hours_list:
        annual_hours_spread = round(max(hours_list) - min(hours_list), 1)
        ok_mean, _, _, _ = annual_hours_within_band(
            avg_hours,
            config.annual_hours_target,
            variance_hours=config.annual_hours_variance,
        )
        if not ok_mean:
            annual_mean_outside = 1
        max_spread = max(float(config.annual_hours_variance or 0) * 2.0, 40.0)
        if annual_hours_spread > max_spread + 1e-6:
            annual_unfair = 1
        if config.annual_hours_hard and (annual_mean_outside or annual_unfair):
            # Phase 1 FAIL: Mathematically impossible to meet annual hours bounds
            metrics = {
                "coverage_percent": 0.0,
                "min_shift_coverage": 0,
                "max_shift_coverage": 0,
                "fte_required": 0,
                "avg_annual_hours": round(avg_hours, 1),
                "hours_variance_ratio": round(hours_range_ratio, 3),
                "hours_range_ratio": round(hours_range_ratio, 3),
                "gap_events": 999,
                "night_risk_gaps": 0,
                "total_gap_hours": 0,
                "shifts_per_day": len(shift_templates),
                "compute_backend": "python",
                "hard_constraints_ok": False,
                "flsa_violations": 0,
                "flsa_threshold_hours": 0.0,
                # Not evaluated on annual-only phase-1 fail — never claim OK
                "coverage_247_ok": None,
                "coverage_247_failures": None,
                "extra_window_failures": None,
                "extra_window_checks": 0,
                "extra_windows_active": 0,
                "annual_band_outside": annual_band_outside,
                "annual_mean_outside": annual_mean_outside,
                "annual_unfair": annual_unfair,
                "annual_hours_spread": annual_hours_spread,
                "annual_hours_variance": config.annual_hours_variance,
                "min_officers_required": config.num_officers,
                "custom_patterns": len(custom_patterns),
                "nearby_start_hops": int(getattr(config, "nearby_start_hops", 1) or 0),
                "allow_offday_coverage": bool(getattr(config, "allow_offday_coverage", False)),
                "offday_coverage_assignments": 0,
                "min_rest_hours": float(getattr(config, "min_rest_hours", 0) or 0),
                "max_consecutive_work_days": int(getattr(config, "max_consecutive_work_days", 0) or 0),
                "rest_failures": None,
                "consecutive_work_failures": None,
            }
            return SimulatorResult(
                success=True,
                message="Failed Phase 1: Annual hours outside hard bounds.",
                compute_backend="python",
                shift_templates=shift_templates,
                officer_slots=slots,
                coverage_by_day=[],
                metrics=metrics,
                suggestions=[],
            )
    # Rust path only when not using features the Rust sim does not evaluate
    use_rust = (
        rust_bridge
        and rust_bridge.available()
        and not custom_patterns
        and not config.avoid_flsa_overtime
        and not config.coverage_247
        and not (config.use_extra_windows and config.extra_windows)
        and not float(getattr(config, "min_rest_hours", 0) or 0) > 0
        and not int(getattr(config, "max_consecutive_work_days", 0) or 0) > 0
        and not bool(getattr(config, "allow_offday_coverage", False))
        and not bool(getattr(config, "flexible_daily_starts", False))
    )
    if use_rust:
        rust_config = {
            "rotation_type": config.rotation_type,
            "num_officers": config.num_officers,
            "shift_length_hours": config.shift_length_hours,
            "simulation_days": config.simulation_days,
            "min_per_shift": config.min_per_shift,
            "apply_department_rules": config.apply_department_rules,
            "annual_hours_target": config.annual_hours_target,
            "night_minimum": config.night_minimum,
            "shift_templates": shift_templates,
            "squad_a_days": squad_a_days,
        }
        rust_out = rust_bridge.simulate_schedule_rust(rust_config, preset, sim_start)
        if rust_out and rust_out.get("success"):
            coverage = rust_out.get("coverage_by_day", [])
            metrics = _enrich_rust_sim_metrics(
                config,
                dict(rust_out.get("metrics", {})),
                coverage,
                slots,
                custom_patterns=custom_patterns if custom_patterns else None,
                slot_patterns=slot_patterns if slot_patterns else None,
            )
            metrics["compute_backend"] = "rust"
            gap_counter: Dict = {}
            suggestions = _build_suggestions(config, metrics, shift_templates, gap_counter)
            return SimulatorResult(
                success=True,
                message=rust_out.get("message", "Simulation complete"),
                compute_backend="rust",
                shift_templates=shift_templates,
                officer_slots=slots,
                coverage_by_day=coverage,
                metrics=metrics,
                suggestions=suggestions,
            )

    coverage_by_day: List[Dict] = []
    gap_counter: Dict[Tuple[int, str], int] = {}
    min_coverage = 999
    max_coverage = 0
    night_risk_gaps = 0
    total_gap_hours = 0
    day_assignments: List[Tuple[date, str, str]] = []
    _slot_assigns: Dict[int, List[Tuple[date, str, str]]] = {i: [] for i in range(len(slots))}
    prev_day_starts: List[str] = []
    offday_coverage_total = 0

    if getattr(config, "phase_limit", 3) == 1:
        metrics = {
            "avg_annual_hours": round(avg_hours, 1),
            "annual_band_outside": annual_band_outside,
            "annual_mean_outside": annual_mean_outside,
            "annual_unfair": annual_unfair,
            "annual_hours_spread": annual_hours_spread,
            "annual_hours_variance": config.annual_hours_variance,
            "hard_constraints_ok": True,
            "shifts_per_day": len(shift_templates),
            "min_officers_required": config.num_officers,
            "compute_backend": "python",
        }
        return SimulatorResult(
            success=True,
            message="Phase 1 (Math bounds) complete.",
            compute_backend="python",
            shift_templates=shift_templates,
            officer_slots=slots,
            coverage_by_day=[],
            metrics=metrics,
            suggestions=[],
        )

    # --- PHASE 2: Start Times & Gaps ---
    for day_offset in range(config.simulation_days):
        target = sim_start + timedelta(days=day_offset)
        cycle_day = (day_offset % cycle_length) + 1
        shift_counts: Dict[str, int] = {t[0]: 0 for t in shift_templates}
        working_officers: List[SimulatorOfficerSlot] = []
        working_indices: List[int] = []

        for si, slot in enumerate(slots):
            working = per_slot_work_flags[si][day_offset]
            if not working:
                continue
            working_officers.append(slot)
            working_indices.append(si)

        # Daily start assignment: flexible half-hour grid OR pack rebalance with
        # home + nearby hops from the user's pack (not a fixed 19:00 example).
        win_min = 0
        win_start = "19:00"
        win_end = "03:00"
        day_windows: List[Dict] = []
        if config.use_extra_windows and config.extra_windows:
            from logic.coverage_timeline import normalize_weekdays

            for w in config.extra_windows:
                if not isinstance(w, dict) or w.get("enabled") is False:
                    continue
                try:
                    wds = normalize_weekdays(w.get("weekday", w.get("weekdays", w.get("dow"))))
                    if wds is not None and target.weekday() not in wds:
                        continue
                    mo = int(w.get("min_officers") or 0)
                    if mo <= 0:
                        continue
                    st = (w.get("start_time") or w.get("start") or "").strip()
                    en = (w.get("end_time") or w.get("end") or "").strip()
                    if st and en:
                        day_windows.append({"min_officers": mo, "start_time": st, "end_time": en})
                    if mo >= win_min:
                        win_min = mo
                        if st and en:
                            win_start, win_end = st, en
                except (TypeError, ValueError):
                    pass
        window_active = win_min > 0 or bool(day_windows)
        nearby_hops = max(0, int(getattr(config, "nearby_start_hops", 1) or 0))
        # Pack path rebalances per day (subset of pack when thin; nearby hops).
        # Equal full-pack spacing is not required. Explicit flexible_daily_starts
        # uses the half-hour grid for freer day-to-day clocks.
        use_flex = bool(getattr(config, "flexible_daily_starts", False))
        if use_flex and working_officers:
            # min_247 = concurrent occupancy floor (24/7 min officers every moment),
            # not pack-bands×min_ps and not min_per_shift (per used start).
            day_bands = _assign_flexible_day_starts(
                len(working_officers),
                config.shift_length_hours,
                min_247=int(config.coverage_247 or 0),
                fri_sat_window=window_active,
                window_min=win_min,
                window_start=win_start,
                window_end=win_end,
                hint_templates=shift_templates,
                prev_starts=prev_day_starts,
            )
        else:
            # Prior start for consecutive ON slots (rest-aware seat pick)
            prev_work_starts: List[Optional[str]] = []
            for si in working_indices:
                hist = _slot_assigns.get(si) or []
                if hist and hist[-1][0] == target - timedelta(days=1):
                    prev_work_starts.append(hist[-1][1])
                else:
                    prev_work_starts.append(None)
            day_bands = _balance_day_assignments(
                working_officers,
                shift_templates,
                min_per_shift=config.min_per_shift,
                prefer_night=is_high_risk_night(target),
                fri_sat_window=window_active,
                nearby_hops=nearby_hops,
                window_min=win_min,
                window_start=win_start,
                window_end=win_end,
                shift_length_hours=config.shift_length_hours,
                coverage_247=int(config.coverage_247 or 0),
                active_windows=day_windows or None,
                min_rest_hours=float(getattr(config, "min_rest_hours", 0) or 0),
                prev_work_starts=prev_work_starts,
            )
        # Track used starts only (empty fixed templates are not gaps when flexible)
        used_counts: Dict[str, int] = {}
        today_starts: List[str] = []
        for (slot, (st, en)), si in zip(zip(working_officers, day_bands), working_indices):
            _slot_assigns[si].append((target, st, en))
            used_counts[st] = used_counts.get(st, 0) + 1
            shift_counts[st] = shift_counts.get(st, 0) + 1
            day_assignments.append((target, st, en))
            today_starts.append(st)

        # Off-day coverage: multi-block OFF officers can start at home/nearby when
        # work-day body count or *minute occupancy* cannot staff 24/7 / window floors.
        offday_adds = 0
        if getattr(config, "allow_offday_coverage", False) and custom_patterns and shift_templates:
            _L = float(config.shift_length_hours or 8.0)
            cov247 = int(config.coverage_247 or 0)

            def _body_short() -> int:
                need = 0
                if cov247 > 0 and _L > 0:
                    need = max(need, max(1, math.ceil(24.0 / _L)) * cov247)
                if int(config.min_per_shift or 0) > 0:
                    need = max(need, int(config.min_per_shift))
                if int(win_min or 0) > 0:
                    need = max(need, int(win_min))
                n_on = len(working_officers) + offday_adds
                return max(0, need - n_on)

            def _occ_short(starts: List[str]) -> int:
                """How far min half-hour occupancy is below 24/7 floor."""
                if cov247 <= 0 or not starts:
                    return cov247 if cov247 > 0 else 0
                bins = _coverage_bins(starts, _L, prev_starts=prev_day_starts)
                if not bins:
                    return cov247
                return max(0, cov247 - min(bins))

            def _win_short(starts: List[str]) -> int:
                if win_min <= 0 or not window_active:
                    return 0
                ws = _hhmm_to_min(win_start) if win_start else 19 * 60
                we = _hhmm_to_min(win_end) if win_end else 3 * 60
                bins = _coverage_bins(starts, _L, prev_starts=prev_day_starts)
                if not bins:
                    return win_min
                if we > ws:
                    idxs = list(range(ws // 30, max(ws // 30 + 1, (we + 29) // 30)))
                else:
                    idxs = list(range(ws // 30, 48)) + list(range(0, max(1, (we + 29) // 30)))
                occ = min(bins[i % 48] for i in idxs) if idxs else 0
                return max(0, win_min - occ)

            def _total_short(starts: List[str]) -> int:
                return max(_body_short(), _occ_short(starts), _win_short(starts))

            def _thin_bin_start(starts: List[str]) -> Optional[str]:
                """Prefer a pack start that covers the thinnest 24/7 or window bin."""
                bins = _coverage_bins(starts, _L, prev_starts=prev_day_starts)
                if not bins:
                    return None
                # Target the worst bin under floor
                worst_i = min(range(48), key=lambda i: bins[i])
                if cov247 > 0 and bins[worst_i] >= cov247 and _win_short(starts) <= 0:
                    return None
                if _win_short(starts) > 0 and win_start:
                    # Prefer window cover first when window short
                    worst_i = None
                    ws = _hhmm_to_min(win_start)
                    we = _hhmm_to_min(win_end) if win_end else 3 * 60
                    if we > ws:
                        idxs = list(range(ws // 30, max(ws // 30 + 1, (we + 29) // 30)))
                    else:
                        idxs = list(range(ws // 30, 48)) + list(range(0, max(1, (we + 29) // 30)))
                    if idxs:
                        worst_i = min(idxs, key=lambda i: bins[i % 48]) % 48
                if worst_i is None:
                    worst_i = min(range(48), key=lambda i: bins[i])
                target_m = worst_i * 30
                length_m = max(30, int(round(_L * 60)))
                best_st, best_d = None, 10**9
                for st, _en in shift_templates:
                    sm = _hhmm_to_min(st)
                    # Does this start cover target minute on this calendar day?
                    rel = (target_m - sm) % (24 * 60)
                    if rel < length_m and sm + rel < 24 * 60:
                        d = rel  # prefer starts that cover soon after begin
                        if d < best_d:
                            best_d, best_st = d, st
                return best_st

            short = _total_short(today_starts)
            off_indices = [si for si in range(len(slots)) if si not in working_indices]
            for si in off_indices:
                short = _total_short(today_starts)
                if short <= 0:
                    break
                off_slot = slots[si]
                home = off_slot.shift_start or shift_templates[0][0]
                home_i = _pack_band_index(home, shift_templates)
                order = sorted(
                    range(len(shift_templates)),
                    key=lambda i: _hhmm_to_min(shift_templates[i][0]),
                )
                inv = [0] * len(shift_templates)
                for rank, bi in enumerate(order):
                    inv[bi] = rank
                home_rank = inv[home_i]
                prefer = []
                for d in range(0, nearby_hops + 1):
                    for sign in (0,) if d == 0 else (-1, 1):
                        r = (home_rank + sign * d) % len(shift_templates)
                        prefer.append(order[r])
                # Prefer start covering thinnest occupancy bin (247 / window)
                thin_st = _thin_bin_start(today_starts)
                if thin_st:
                    prefer = sorted(
                        prefer,
                        key=lambda i: (
                            0 if shift_templates[i][0] == thin_st else 1,
                            abs(_hhmm_to_min(shift_templates[i][0]) - _hhmm_to_min(thin_st)),
                        ),
                    )
                elif window_active and win_min > 0:
                    win_anchor = _hhmm_to_min(win_start) if win_start else 19 * 60
                    prefer = sorted(
                        prefer,
                        key=lambda i: (
                            0
                            if abs(_hhmm_to_min(shift_templates[i][0]) - win_anchor) <= 30
                            else 1
                            if abs(_hhmm_to_min(shift_templates[i][0]) - win_anchor) <= 5 * 60
                            else 2,
                            abs(_hhmm_to_min(shift_templates[i][0]) - win_anchor),
                        ),
                    )
                # Rest-aware: if called in after yesterday ON, prefer legal next start
                min_rest_od = float(getattr(config, "min_rest_hours", 0) or 0)
                hist = _slot_assigns.get(si) or []
                prev_st_od = hist[-1][1] if hist and hist[-1][0] == target - timedelta(days=1) else None
                if min_rest_od > 0 and prev_st_od:
                    try:
                        from logic.staffing_optimizer import rest_gap_minutes

                        def _od_rest_ok(bi: int) -> bool:
                            g = rest_gap_minutes(
                                prev_st_od,
                                shift_templates[bi][0],
                                _L,
                                day_gap_days=1,
                            )
                            return g >= min_rest_od * 60.0 - 1.0

                        legal = [bi for bi in prefer if _od_rest_ok(bi)]
                        if legal:
                            prefer = legal + [bi for bi in prefer if bi not in legal]
                        else:
                            # expand to full pack for a legal rest seat
                            all_i = list(range(len(shift_templates)))
                            legal_all = [bi for bi in all_i if _od_rest_ok(bi)]
                            if legal_all:
                                prefer = legal_all + prefer
                    except Exception:
                        pass
                pick_i = prefer[0] if prefer else home_i
                st, en = shift_templates[pick_i]
                day_assignments.append((target, st, en))
                # Count for rest / FLSA / consecutive — was coverage-only before
                _slot_assigns[si].append((target, st, en))
                per_slot_work_flags[si][day_offset] = True
                slots[si].work_days_in_sim += 1
                today_starts.append(st)
                used_counts[st] = used_counts.get(st, 0) + 1
                shift_counts[st] = shift_counts.get(st, 0) + 1
                offday_adds += 1
            offday_coverage_total += offday_adds

        prev_day_starts = today_starts

        # Min/max across *used* starts only. Rotation days with fewer officers
        # may run fewer shifts — empty pack slots are not failures (24/7/windows are).
        used_vals = [int(c) for c in used_counts.values() if int(c) > 0]
        day_min = min(used_vals) if used_vals else 0
        day_max = max(used_vals) if used_vals else 0
        min_coverage = min(min_coverage, day_min) if used_vals else min_coverage
        max_coverage = max(max_coverage, day_max)

        # Band floor: only for starts *run today*. Do not force every pack band
        # every day (multi-block thins the roster; starts may differ by day).
        high_risk = is_high_risk_night(target)
        if config.min_per_shift > 0:
            if used_counts:
                for st, count in used_counts.items():
                    c = int(count)
                    if c > 0 and c < config.min_per_shift:
                        gap = config.min_per_shift - c
                        gap_counter[(day_offset, st)] = gap_counter.get((day_offset, st), 0) + gap
                        total_gap_hours += gap * config.shift_length_hours
            else:
                # Nobody working — only a gap if a minimum was required at all
                n_working_today = len(working_officers) + offday_adds
                if n_working_today < config.min_per_shift:
                    gap = config.min_per_shift - n_working_today
                    gap_counter[(day_offset, "total")] = gap_counter.get((day_offset, "total"), 0) + gap
                    total_gap_hours += gap * config.shift_length_hours

        # High-risk night (Fri/Sat): score configured night starts vs night_minimum.
        # Include empty bands (c==0) — missing night coverage is a risk gap.
        if high_risk and config.night_minimum and config.night_minimum > 0:
            required = int(config.night_minimum)
            if config.apply_department_rules:
                required = max(required, int(config.min_per_shift or 0))
            night_starts = [st for st in (config.shift_starts or []) if _is_night_shift_start(st)]
            if not night_starts:
                # Fall back to whatever night keys actually ran
                night_starts = [st for st in used_counts if _is_night_shift_start(st)]
            for st in night_starts:
                c = int(used_counts.get(st, 0))
                if c < required:
                    night_risk_gaps += 1

        coverage_by_day.append(
            {
                "date": format_date(target),
                "cycle_day": cycle_day,
                "shift_counts": shift_counts,
                "working_officers": len(working_officers),
                "min_shift_coverage": day_min,
                "high_risk_night": high_risk,
            }
        )

    # Off-day OT adds real work days — recompute annual from flags (not pattern only)
    if offday_coverage_total > 0:
        annual_factor = 365.0 / max(config.simulation_days, 1)
        for si, slot in enumerate(slots):
            work_days = sum(1 for f in per_slot_work_flags[si] if f)
            slot.work_days_in_sim = work_days
            slot.projected_annual_hours = round(work_days * hours_per_work_day * annual_factor, 1)
        hours_list = [s.projected_annual_hours for s in slots]
        avg_hours = sum(hours_list) / len(hours_list) if hours_list else 0
        hours_range_ratio = 0.0
        if hours_list and avg_hours:
            hours_range_ratio = (max(hours_list) - min(hours_list)) / avg_hours
        annual_band_outside = 0
        annual_mean_outside = 0
        annual_unfair = 0
        annual_hours_spread = 0.0
        for slot in slots:
            ok_band, _lo, _hi, _dist = annual_hours_within_band(
                slot.projected_annual_hours,
                config.annual_hours_target,
                variance_hours=config.annual_hours_variance,
            )
            if not ok_band:
                annual_band_outside += 1
        if hours_list:
            annual_hours_spread = round(max(hours_list) - min(hours_list), 1)
            ok_mean, _, _, _ = annual_hours_within_band(
                avg_hours,
                config.annual_hours_target,
                variance_hours=config.annual_hours_variance,
            )
            if not ok_mean:
                annual_mean_outside = 1
            max_spread = max(float(config.annual_hours_variance or 0) * 2.0, 40.0)
            if annual_hours_spread > max_spread + 1e-6:
                annual_unfair = 1

    slots_per_day = len(shift_templates)
    # FTE estimate: concurrent person-hours (24/7 floor), pack×min_ps×length,
    # or window person-hours. Do not mix min_per_shift with concurrent occupancy.
    # Window-only must not invent a full 24×7×1 floor (was overstating FTE badly).
    if int(config.coverage_247 or 0) > 0:
        weekly_hours_needed = 24.0 * 7 * int(config.coverage_247)
        fte_basis = "24/7"
    elif int(config.min_per_shift or 0) > 0 and shift_templates:
        weekly_hours_needed = (
            len(shift_templates) * int(config.min_per_shift) * float(config.shift_length_hours or 8.0) * 7
        )
        fte_basis = "min_per_shift"
    elif getattr(config, "use_extra_windows", False) and config.extra_windows:
        weekly_hours_needed = _window_weekly_person_hours(config)
        if weekly_hours_needed <= 0:
            # Windows on but zero person-hours — do not invent 24×7 floor
            weekly_hours_needed = 0.0
            fte_basis = "none"
        else:
            fte_basis = "windows"
    else:
        # No 24/7, min_ps, or window demand — FTE not meaningful
        weekly_hours_needed = 0.0
        fte_basis = "none"
    annual_hours_needed = weekly_hours_needed * 52
    if weekly_hours_needed > 0:
        fte_required = annual_hours_needed / max(float(config.annual_hours_target or 1), 1.0)
    else:
        fte_required = 0.0

    coverage_pct = 100.0
    if gap_counter and int(config.min_per_shift or 0) > 0:
        total_required = config.simulation_days * slots_per_day * int(config.min_per_shift)
        total_met = total_required - sum(gap_counter.values())
        coverage_pct = round(100 * total_met / max(total_required, 1), 1)
    elif gap_counter:
        # min_ps off — report 0% if any structural gap events recorded
        coverage_pct = 0.0

    if getattr(config, "phase_limit", 3) == 2:
        # Phase 2 stops before 247/rest/FLSA — hard_ok only reflects min_ps gaps here
        gap_sum = int(sum(gap_counter.values())) if gap_counter else 0
        metrics = {
            "avg_annual_hours": round(avg_hours, 1),
            "annual_band_outside": annual_band_outside,
            "annual_mean_outside": annual_mean_outside,
            "annual_unfair": annual_unfair,
            "annual_hours_spread": annual_hours_spread,
            "annual_hours_variance": config.annual_hours_variance,
            "hard_constraints_ok": gap_sum == 0 or int(config.min_per_shift or 0) <= 0,
            "shifts_per_day": len(shift_templates),
            "min_officers_required": config.num_officers,
            "compute_backend": "python",
            "gap_events": gap_sum,
            "total_gap_hours": total_gap_hours,
            "night_risk_gaps": night_risk_gaps,
            "coverage_percent": 100.0 if not total_gap_hours else 0.0,
            "min_shift_coverage": min_coverage if min_coverage != 999 else 0,
            "max_shift_coverage": max_coverage,
            "phase_limit": 2,
            "coverage_247_ok": None,  # not evaluated in phase 2
            "rest_failures": None,
        }
        return SimulatorResult(
            success=True,
            message="Phase 2 (Chronological Assignments) complete.",
            compute_backend="python",
            shift_templates=shift_templates,
            officer_slots=slots,
            coverage_by_day=coverage_by_day,
            metrics=metrics,
            suggestions=[],
        )

    # --- PHASE 3: Labor Compliance (FLSA & Rest Gaps) ---
    hard_ok = True
    flsa_violations = 0
    flsa_threshold = 0.0
    if config.avoid_flsa_overtime:
        from logic.labor_compliance import flsa_threshold_for_period_days

        if config.flsa_work_period_days and int(config.flsa_work_period_days) > 0:
            period_days = max(7, min(int(config.flsa_work_period_days), 28))
        else:
            period_days = max(7, min(cycle_length, 28))
        try:
            flsa_threshold = flsa_threshold_for_period_days(period_days)
        except Exception:
            flsa_threshold = round((171.0 / 28.0) * period_days, 1)
        for flags in per_slot_work_flags:
            if not _flsa_period_hours_ok(flags, config.shift_length_hours, period_days, flsa_threshold):
                flsa_violations += 1
                hard_ok = False

    coverage_247_ok = True
    coverage_247_failures = 0
    extra_window_failures = 0
    extra_window_checks = 0
    window_objs = []
    if config.use_extra_windows and config.extra_windows:
        from logic.coverage_windows_store import _parse_window_dict

        for item in config.extra_windows:
            if not isinstance(item, dict):
                continue
            if item.get("enabled") is False:
                continue
            w = _parse_window_dict(item)
            if w:
                window_objs.append(w)

    if (config.coverage_247 and config.coverage_247 > 0) or window_objs:
        from logic.coverage_timeline import evaluate_day_coverage

        # Seed prior-day overnight tails for the first sim day so 24/7 checks
        # do not false-fail at 00:00–shift-start (no history before sim_start).
        seed_prior: List[Tuple[date, str, str]] = []
        if config.coverage_247 and config.coverage_247 > 0 and day_assignments:
            first_day = sim_start
            for work_date, st, en in day_assignments:
                if work_date != first_day:
                    continue
                # Only *overnight* shifts (end clock ≤ start) spill past midnight into
                # the next calendar morning. Early day starts (e.g. 05:00–13:00) do not.
                try:
                    sm = _hhmm_to_min(st)
                    em = _hhmm_to_min(en)
                except Exception:
                    continue
                if em <= sm:
                    seed_prior.append((first_day - timedelta(days=1), st, en))

        for day_offset in range(config.simulation_days):
            day = sim_start + timedelta(days=day_offset)
            day_asg = [a for a in day_assignments if a[0] == day or a[0] == day - timedelta(days=1)]
            if day_offset == 0 and seed_prior:
                day_asg = list(seed_prior) + day_asg
            result = evaluate_day_coverage(
                day_asg,
                day,
                min_247=int(config.coverage_247 or 0),
                windows=window_objs or None,
            )
            for chk in result.get("checks") or []:
                if chk.get("skipped"):
                    continue
                # 24/7 checks have no "label" from check_coverage_247; windows have label
                is_window = "label" in chk or "range_start" in chk
                if is_window:
                    extra_window_checks += 1
                    if not chk.get("ok", True):
                        extra_window_failures += 1
                        hard_ok = False
                else:
                    if not chk.get("ok", True):
                        coverage_247_ok = False
                        coverage_247_failures += 1
                        hard_ok = False
            if not result.get("ok", True) and not window_objs and config.coverage_247:
                coverage_247_ok = False
                hard_ok = False

    # (Annual bounds checked in Phase 1)

    if gap_counter and config.min_per_shift > 0:
        hard_ok = False

    # Annual hard (also after off-day OT recompute above)
    if config.annual_hours_hard and (annual_mean_outside or annual_unfair):
        hard_ok = False

    # --- min_rest_hours hard gate ---
    # Check chronological day_assignments per slot to enforce a minimum rest
    # gap between the end of one shift and the start of the next work day.
    rest_failures = 0
    min_rest = float(getattr(config, "min_rest_hours", 0) or 0)
    if min_rest > 0 and day_assignments:
        for si in range(len(slots)):
            asg_list = _slot_assigns[si]
            for k in range(1, len(asg_list)):
                prev_date, prev_st, prev_en = asg_list[k - 1]
                curr_date, curr_st, curr_en = asg_list[k]
                # End of prev shift
                prev_end_m = _hhmm_to_min(prev_en)
                # If end < start, overnight shift: end is next calendar day
                prev_start_m = _hhmm_to_min(prev_st)
                if prev_end_m <= prev_start_m:  # overnight
                    prev_end_m += 24 * 60
                # Start of current shift (absolute minutes from prev_date midnight)
                day_gap_m = int((curr_date - prev_date).days) * 24 * 60
                curr_start_abs = day_gap_m + _hhmm_to_min(curr_st)
                rest_gap = curr_start_abs - prev_end_m
                if rest_gap < min_rest * 60 - 1:  # 1-minute tolerance
                    rest_failures += 1
        if rest_failures:
            hard_ok = False

    metrics = {
        "coverage_percent": coverage_pct,
        "min_shift_coverage": min_coverage if min_coverage != 999 else 0,
        "max_shift_coverage": max_coverage,
        "fte_required": round(fte_required, 2),
        "fte_basis": fte_basis,
        "avg_annual_hours": round(avg_hours, 1),
        # Coefficient of range (max−min)/avg — see hours_range_ratio comment above
        "hours_variance_ratio": round(hours_range_ratio, 3),  # legacy key kept for UI compat
        "hours_range_ratio": round(hours_range_ratio, 3),
        # Magnitude of understaffed band seats (not distinct day keys)
        "gap_events": int(sum(gap_counter.values())) if gap_counter else 0,
        "night_risk_gaps": night_risk_gaps,
        "total_gap_hours": round(total_gap_hours, 1),
        "shifts_per_day": slots_per_day,
        "compute_backend": "python",
        "hard_constraints_ok": hard_ok,
        "flsa_violations": flsa_violations,
        "flsa_threshold_hours": flsa_threshold,
        "coverage_247_ok": coverage_247_ok,
        "coverage_247_failures": coverage_247_failures,
        "extra_window_failures": extra_window_failures,
        "extra_window_checks": extra_window_checks,
        "extra_windows_active": len(window_objs),
        "annual_band_outside": annual_band_outside,
        "annual_mean_outside": annual_mean_outside,
        "annual_unfair": annual_unfair,
        "annual_hours_spread": annual_hours_spread,
        "annual_hours_variance": config.annual_hours_variance,
        "min_officers_required": config.num_officers,
        "custom_patterns": len(custom_patterns),
        "nearby_start_hops": int(getattr(config, "nearby_start_hops", 1) or 0),
        "allow_offday_coverage": bool(getattr(config, "allow_offday_coverage", False)),
        "offday_coverage_assignments": int(offday_coverage_total),
        "min_rest_hours": float(getattr(config, "min_rest_hours", 0) or 0),
        "max_consecutive_work_days": int(getattr(config, "max_consecutive_work_days", 0) or 0),
        "rest_failures": rest_failures,
        "consecutive_work_failures": 0,
    }

    # Consecutive ON-day fatigue gate — enforced for all rotation paths:
    # multi-block custom patterns AND squad presets.  per_slot_work_flags is
    # populated in the main sim loop for every path.
    max_c = int(getattr(config, "max_consecutive_work_days", 0) or 0)
    if max_c > 0 and per_slot_work_flags:
        consec_fail = 0
        for si in range(len(slots)):
            flags = per_slot_work_flags[si] if si < len(per_slot_work_flags) else []
            streak = 0
            for working in flags:
                if working:
                    streak += 1
                    if streak > max_c:
                        consec_fail += 1
                else:
                    streak = 0
        metrics["consecutive_work_failures"] = consec_fail
        if consec_fail:
            hard_ok = False
            metrics["hard_constraints_ok"] = False

    suggestions = _build_suggestions(config, metrics, shift_templates, gap_counter)
    if config.avoid_flsa_overtime and flsa_violations:
        suggestions.append(
            SimulatorSuggestion(
                severity="critical",
                title="FLSA overtime would be generated",
                message=f"{flsa_violations} slot(s) exceed §207(k) cap ({flsa_threshold}h / period).",
                recommendation="Reduce days on, shorten shifts, or add officers / stagger variations.",
            )
        )
    if config.coverage_247 and not coverage_247_ok:
        suggestions.append(
            SimulatorSuggestion(
                severity="critical",
                title="24/7 continuous coverage short",
                message=f"{coverage_247_failures} day(s) drop below {config.coverage_247} officer(s) on duty.",
                recommendation="Add officers, stagger rotations, or add overlapping shift starts.",
            )
        )
    if window_objs and extra_window_failures:
        suggestions.append(
            SimulatorSuggestion(
                severity="critical",
                title="Extra min-staffing windows short",
                message=(f"{extra_window_failures} window check(s) failed ({len(window_objs)} active window rule(s))."),
                recommendation="Add officers, change starts, or lower that day/time minimum.",
            )
        )

    message = "Simulation complete"
    if config.avoid_flsa_overtime and flsa_violations:
        message = "Simulation complete — FLSA hard filter failed (plan not compliant)"
    elif window_objs and extra_window_failures:
        message = "Simulation complete — extra staffing windows not fully met"
    elif config.coverage_247 and not coverage_247_ok:
        message = "Simulation complete — 24/7 minimum not fully met"

    return SimulatorResult(
        success=True,
        message=message,
        compute_backend="python",
        shift_templates=shift_templates,
        officer_slots=slots,
        coverage_by_day=coverage_by_day,
        metrics=metrics,
        suggestions=suggestions,
    )


def _enrich_rust_sim_metrics(
    config: SimulatorConfig,
    metrics: Dict,
    coverage_by_day: List[Dict],
    slots: List[SimulatorOfficerSlot],
    *,
    custom_patterns=None,
    slot_patterns=None,
) -> Dict:
    """Fill presentation metrics Rust omits (gap hours, night risk, annual hours).

    Fix (2025-07): When custom multi-block patterns are active, use
    projected_annual_hours() (cycle-based, accurate) instead of the noisy
    28-day extrapolation.  The extrapolation is kept only for the squad-preset
    path where patterns are not available.
    """
    assert getattr(config, "coverage_247", 0) == 0, "Rust path cannot evaluate 24/7 coverage yet"

    gap_events = int(metrics.get("gap_events", 0))
    total_gap_hours = gap_events * config.shift_length_hours
    night_risk_gaps = 0
    nmin = int(getattr(config, "night_minimum", 0) or 0)
    night_starts = [st for st in (config.shift_starts or []) if _is_night_shift_start(st)]
    for day in coverage_by_day:
        if not day.get("high_risk_night") or nmin <= 0:
            continue
        shift_counts = day.get("shift_counts", {}) or {}
        required = nmin
        if config.apply_department_rules:
            required = max(required, int(config.min_per_shift or 0))
        starts = night_starts or [st for st in shift_counts if _is_night_shift_start(st)]
        for shift_start in starts:
            count = int(shift_counts.get(shift_start, 0))
            if count < required:
                night_risk_gaps += 1

    hours_list = []
    if custom_patterns and slot_patterns and len(slot_patterns) == len(slots):
        # Correct path: cycle-based projected_annual_hours per slot
        from logic.rotation_patterns import projected_annual_hours

        for si, slot in enumerate(slots):
            slot.projected_annual_hours = projected_annual_hours(slot_patterns[si], config.shift_length_hours)
            hours_list.append(slot.projected_annual_hours)
    else:
        # Fallback: extrapolation (squad presets without custom_patterns)
        annual_factor = 365 / max(config.simulation_days, 1)
        for slot in slots:
            slot.projected_annual_hours = round(slot.work_days_in_sim * config.shift_length_hours * annual_factor, 1)
            hours_list.append(slot.projected_annual_hours)

    avg_hours = sum(hours_list) / len(hours_list) if hours_list else 0.0
    hours_range_ratio = 0.0
    if hours_list and avg_hours:
        hours_range_ratio = (max(hours_list) - min(hours_list)) / avg_hours

    enriched = dict(metrics)
    enriched.setdefault("total_gap_hours", round(total_gap_hours, 1))
    enriched.setdefault("night_risk_gaps", night_risk_gaps)
    enriched.setdefault("avg_annual_hours", round(avg_hours, 1))
    enriched.setdefault("hours_range_ratio", round(hours_range_ratio, 3))
    enriched.setdefault("hours_variance_ratio", round(hours_range_ratio, 3))  # legacy compat
    # FTE basis honesty (match Python path — never invent 24×7 when unconstrained)
    if "fte_basis" not in enriched or not enriched.get("fte_basis"):
        if int(config.coverage_247 or 0) > 0:
            weekly = 24.0 * 7 * int(config.coverage_247)
            enriched["fte_basis"] = "24/7"
        elif int(config.min_per_shift or 0) > 0 and (config.shift_starts or []):
            n_starts = len(config.shift_starts or [])
            weekly = n_starts * int(config.min_per_shift) * float(config.shift_length_hours or 8) * 7
            enriched["fte_basis"] = "min_per_shift"
        elif getattr(config, "use_extra_windows", False) and config.extra_windows:
            weekly = _window_weekly_person_hours(config)
            enriched["fte_basis"] = "windows" if weekly > 0 else "none"
            if weekly <= 0:
                weekly = 0.0
        else:
            weekly = 0.0
            enriched["fte_basis"] = "none"
        if weekly > 0:
            enriched["fte_required"] = round(weekly * 52 / max(float(config.annual_hours_target or 1), 1.0), 2)
        else:
            enriched["fte_required"] = 0.0
    # Align with Python path: band min gaps are hard when min_per_shift enforced
    if "hard_constraints_ok" not in enriched:
        # BUG-9 guard: Rust path cannot enforce 24/7 checks.
        assert not config.coverage_247, "Rust path cannot enforce 24/7 coverage"
        gaps = int(enriched.get("gap_events") or 0)
        enriched["hard_constraints_ok"] = not (gaps > 0 and config.min_per_shift > 0)
    return enriched


def _build_suggestions(
    config: SimulatorConfig,
    metrics: Dict,
    shift_templates: List[Tuple[str, str]],
    gap_counter: Dict,
) -> List[SimulatorSuggestion]:
    suggestions: List[SimulatorSuggestion] = []

    if metrics["fte_required"] > config.num_officers:
        need = math.ceil(metrics["fte_required"] - config.num_officers)
        basis = str(metrics.get("fte_basis") or "")
        if basis == "24/7" or int(config.coverage_247 or 0) > 0:
            fte_title = "Understaffed for 24/7 coverage"
        elif basis == "windows":
            fte_title = "Understaffed for staffing windows"
        else:
            fte_title = "Understaffed vs estimated FTE"
        basis_note = f" (basis: {basis})" if basis else ""
        suggestions.append(
            SimulatorSuggestion(
                severity="critical",
                title=fte_title,
                message=(
                    f"Estimated {metrics['fte_required']:.1f} FTE required{basis_note}; "
                    f"you have {config.num_officers} officers."
                ),
                recommendation=f"Add at least {need} officer(s) or extend shift overlap.",
            )
        )

    if metrics["coverage_percent"] < 100:
        suggestions.append(
            SimulatorSuggestion(
                severity="critical",
                title="Coverage gaps detected",
                message=(
                    f"{metrics['gap_events']} understaffed shift(s); "
                    f"{metrics['total_gap_hours']:.0f} gap hours in simulation."
                ),
                recommendation="Reassign officers to under-covered shifts or add a shift start time.",
            )
        )

    if metrics.get("night_risk_gaps", 0) and int(getattr(config, "night_minimum", 0) or 0) > 0:
        nmin = int(config.night_minimum)
        suggestions.append(
            SimulatorSuggestion(
                severity="warning",
                title="Friday/Saturday night minimum at risk",
                message=f"{metrics['night_risk_gaps']} night shift(s) below night minimum ({nmin}).",
                recommendation=f"Assign {nmin}+ officers to each night shift on Fri/Sat.",
            )
        )

    rest_f = int(metrics.get("rest_failures") or 0)
    min_rest = float(getattr(config, "min_rest_hours", 0) or 0)
    if rest_f > 0 and min_rest > 0:
        suggestions.append(
            SimulatorSuggestion(
                severity="critical",
                title="Minimum rest between shifts not met",
                message=f"{rest_f} consecutive work-day pair(s) leave less than {min_rest:g}h rest.",
                recommendation="Widen start pack, lower min rest, or reduce consecutive ON days.",
            )
        )

    consec_f = int(metrics.get("consecutive_work_failures") or 0)
    max_c = int(getattr(config, "max_consecutive_work_days", 0) or 0)
    if consec_f > 0 and max_c > 0:
        suggestions.append(
            SimulatorSuggestion(
                severity="critical",
                title="Max consecutive work days exceeded",
                message=f"{consec_f} officer slot(s) exceed {max_c} consecutive ON days.",
                recommendation="Use a lighter rotation block or raise the consecutive-day limit.",
            )
        )

    if metrics["avg_annual_hours"] > config.annual_hours_target * 1.08:
        suggestions.append(
            SimulatorSuggestion(
                severity="warning",
                title="Annual hours exceed target",
                message=(
                    f"Average projected {metrics['avg_annual_hours']:.0f}h vs target {config.annual_hours_target:.0f}h."
                ),
                recommendation="Add officers, shorten shifts, or use a lighter rotation pattern.",
            )
        )
    elif metrics["avg_annual_hours"] < config.annual_hours_target * 0.85:
        suggestions.append(
            SimulatorSuggestion(
                severity="info",
                title="Room for additional duties",
                message=f"Average projected {metrics['avg_annual_hours']:.0f}h — below annual target.",
                recommendation="Officers have capacity for training, court, or special assignments.",
            )
        )

    # hours_range_ratio = (max−min)/avg.  0.15 ≈ 300h spread on a 2008h target.
    if metrics.get("hours_range_ratio", metrics.get("hours_variance_ratio", 0)) > 0.15:
        spread = round(metrics.get("annual_hours_spread", 0), 0)
        suggestions.append(
            SimulatorSuggestion(
                severity="info",
                title="Uneven hour distribution",
                message=(
                    f"Annual hours span ≈{spread:.0f}h across officer slots "
                    f"(range/avg ratio {metrics.get('hours_range_ratio', 0):.2f})."
                ),
                recommendation="Rotate shift assignments or rebalance squads.",
            )
        )

    if len(shift_templates) < math.ceil(24 / config.shift_length_hours):
        suggestions.append(
            SimulatorSuggestion(
                severity="info",
                title="Consider additional shift bands",
                message=(f"{len(shift_templates)} shift band(s) for {config.shift_length_hours:.0f}-hour blocks."),
                recommendation="Add shift start times to reduce handoff gaps.",
            )
        )

    # Only praise band coverage when hard floors also clear (no 247/window/rest lies)
    hard_ok = bool(metrics.get("hard_constraints_ok", True))
    cov247_ok = bool(metrics.get("coverage_247_ok", True))
    win_fail = int(metrics.get("extra_window_failures") or 0)
    night_soft = int(metrics.get("night_risk_gaps") or 0)
    if (
        hard_ok
        and cov247_ok
        and win_fail == 0
        and night_soft == 0
        and not gap_counter
        and float(metrics.get("coverage_percent") or 0) >= 99
    ):
        suggestions.append(
            SimulatorSuggestion(
                severity="info",
                title="Strong coverage profile",
                message="Simulation meets minimum staffing across all shift bands.",
                recommendation="Export assignments to the roster or view Original Monthly Schedule.",
            )
        )

    return suggestions


def config_from_current_roster() -> SimulatorConfig:
    """Build simulator defaults from live department configuration."""
    from logic import get_officers_by_seniority
    from logic.rotation_config import get_active_rotation_preset_name
    from logic.staffing_config import (
        get_active_annual_hours_target,
        get_active_shift_length_hours,
        get_active_shift_starts,
    )

    officers = [o for o in get_officers_by_seniority() if o.get("active") == 1]
    shift_starts = get_active_shift_starts() or sorted({o["shift_start"] for o in officers})
    return SimulatorConfig(
        rotation_type=get_active_rotation_preset_name(),
        num_officers=max(len(officers), 1),
        shift_length_hours=get_active_shift_length_hours(),
        annual_hours_target=get_active_annual_hours_target(),
        shift_starts=shift_starts,
        apply_department_rules=True,
        min_per_shift=1,
    )
