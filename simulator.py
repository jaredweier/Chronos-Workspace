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
    apply_department_rules: bool = True
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


def _squad_working(rotation_type: str, squad: str, cycle_day: int, preset: Dict) -> bool:
    if "squad_a_days" in preset:
        on_a = cycle_day in preset["squad_a_days"]
        return on_a if squad == "A" else not on_a
    if "squad_patterns" in preset:
        pattern = preset["squad_patterns"].get(squad, preset["squad_patterns"].get("A", []))
        idx = (cycle_day - 1) % len(pattern)
        return pattern[idx] == 1
    work_days = preset.get("work_days_per_cycle", 7)
    half = work_days // preset.get("squads", 2)
    if squad == "A":
        return ((cycle_day - 1) % preset["cycle_length"]) < half
    offset = preset["cycle_length"] // preset.get("squads", 2)
    return ((cycle_day - 1 + offset) % preset["cycle_length"]) < half


def _assign_officers(
    num_officers: int,
    shift_templates: List[Tuple[str, str]],
    preset: Dict,
    roster_officers: Optional[List[Dict]] = None,
) -> List[SimulatorOfficerSlot]:
    squads = ["A", "B"] if preset.get("squads", 2) >= 2 else ["A"]
    slots = []
    roster = (roster_officers or [])[:num_officers]
    count = len(roster) if roster else num_officers
    for i in range(count):
        shift_start, shift_end = shift_templates[i % len(shift_templates)]
        if roster:
            officer = roster[i]
            slots.append(
                SimulatorOfficerSlot(
                    slot_id=officer["id"],
                    label=officer["name"],
                    squad=officer.get("squad") or squads[i % len(squads)],
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


def _nearby_band_indices(
    home_idx: int,
    k: int,
    *,
    hops: int = 1,
) -> List[int]:
    """Pack indices within ±hops of home (circular on time-sorted pack order)."""
    if k <= 0:
        return []
    hops = max(0, int(hops))
    home_idx = int(home_idx) % k
    out = []
    for d in range(0, hops + 1):
        for sign in (0,) if d == 0 else (-1, 1):
            j = (home_idx + sign * d) % k
            if j not in out:
                out.append(j)
    return out


def _balance_day_assignments(
    working_slots: List[SimulatorOfficerSlot],
    shift_templates: List[Tuple[str, str]],
    *,
    min_per_shift: int,
    prefer_night: bool = False,
    fri_sat_window: bool = False,
    nearby_hops: int = 1,
) -> List[Tuple[str, str]]:
    """Assign today's working officers onto pack bands.

    Officers keep a *home* start but may move to nearby pack bands (default ±1),
    e.g. home 19:00 → 14:00 or 22:00. Fri/Sat window mode still targets evening
    coverage while preferring home/nearby affinity over free float.
    """
    if not working_slots or not shift_templates:
        return []
    n = len(working_slots)
    k = len(shift_templates)
    need = max(min_per_shift, 1)
    # Time-sort pack so "nearby" = adjacent clocks (06↔14↔19↔22)
    order = sorted(range(k), key=lambda i: _hhmm_to_min(shift_templates[i][0]))
    inv = [0] * k
    for rank, bi in enumerate(order):
        inv[bi] = rank
    counts = [n // k + (1 if i < n % k else 0) for i in range(k)]

    def _hour(i: int) -> int:
        try:
            return int(shift_templates[i][0].split(":")[0])
        except ValueError:
            return 0

    # Bands that cover Fri/Sat 19:00–03:00 style windows (start hour):
    # 14–18:00 → through evening; 19:00 → full window; ≥20 → late night into morning.
    afternoon = [i for i in range(k) if 12 <= _hour(i) < 19]
    evening = [i for i in range(k) if _hour(i) == 19 or (18 <= _hour(i) < 20)]
    night = [i for i in range(k) if _hour(i) >= 20 or _hour(i) < 6]
    morning = [i for i in range(k) if i not in afternoon and i not in evening and i not in night]

    def _enforce_floor():
        if n < k * need:
            return
        for i in range(k):
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
        while have < want and guard < 20:
            guard += 1
            donors = [j for j in range(k) if j not in group and counts[j] > need]
            if not donors:
                donors = [j for j in range(k) if j not in group and counts[j] > 0]
            if not donors:
                break
            rich = max(donors, key=lambda j: counts[j])
            poor = min(group, key=lambda j: counts[j])
            counts[rich] -= 1
            counts[poor] += 1
            have += 1

    _enforce_floor()
    if fri_sat_window and n >= 2:
        # Prefer explicit evening starts (19:00 / 7p): two officers on 19:00 cover
        # the whole 19:00–03:00 min-2 window alone (8h shift).
        if evening:
            _give(evening, min(2, n))
            _enforce_floor()
            # Still keep late-night continuity if bodies remain
            if n >= 4:
                _give(night, min(1, n))
                _enforce_floor()
        elif n >= 4:
            # Classic 06/14/22: need 2 afternoon (14:00 covers 19–22) + 2 night (22–06)
            _give(afternoon, min(2, n - need * max(len(morning), 0)))
            _give(night, min(2, n - need * max(len(morning) + len(afternoon), 0)))
            _enforce_floor()
    elif prefer_night:
        _give(evening + night + afternoon, min(2, n))
        _enforce_floor()

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

    def _take_seat(prefer: List[int]) -> Optional[int]:
        for want in prefer:
            for si, band in enumerate(seat_avail):
                if not used[si] and band == want:
                    used[si] = True
                    return band
        for si, band in enumerate(seat_avail):
            if not used[si]:
                used[si] = True
                return band
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
        # Nearby in time-sorted pack rank space
        home_rank = inv[home_i]
        prefer_ranks = []
        for d in range(0, hops + 1):
            for sign in (0,) if d == 0 else (-1, 1):
                r = (home_rank + sign * d) % k
                prefer_ranks.append(r)
        prefer_bands = [order[r] for r in prefer_ranks]
        # Fri/Sat: if home is evening-capable, try evening seats first among nearby
        if fri_sat_window and evening:
            eve_first = [b for b in prefer_bands if b in evening] + [b for b in prefer_bands if b not in evening]
            prefer_bands = eve_first
        band = _take_seat(prefer_bands)
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
    min_247: int = 1,
    fri_sat_window: bool = False,
    window_min: int = 2,
    window_start: str = "19:00",
    window_end: str = "03:00",
    hint_templates: Optional[List[Tuple[str, str]]] = None,
    prev_starts: Optional[List[str]] = None,
) -> List[Tuple[str, str]]:
    """
    Pick start times for *today's* working officers from the half-hour grid.

    Bands move by day: Fri can load 19:00 swings; other days rebalance for 24/7.
    Uses prior day's starts for overnight continuity into this morning.
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

    # Equal spacing (n independent bands — any count)
    for base in (0, 30, 60, 90, 120, 180, 240, 300, 360, 420, 480):
        step = max(30, (24 * 60) // max(n, 1))
        _add_pat([_min_to_hhmm(base + i * step) for i in range(n)])

    # k-band packs with round-robin load (k = 2..min(6,n))
    for k in range(2, min(6, n) + 1):
        for base in (5 * 60, 6 * 60, 7 * 60, 8 * 60):
            step = max(30, (24 * 60) // k)
            bands = [_min_to_hhmm(base + i * step) for i in range(k)]
            _add_pat([bands[i % k] for i in range(n)])

    # Classic LE packs (bands can differ by day via choosing among these)
    for trip in (
        ["06:00", "14:00", "22:00"],
        ["07:00", "15:00", "23:00"],
        ["05:00", "13:00", "21:00"],
        ["06:00", "14:00", "19:00"],
        ["06:00", "14:00", "19:00", "22:00"],
        ["07:00", "15:00", "19:00", "23:00"],
        ["06:00", "12:00", "18:00", "00:00"],
    ):
        if len(trip) <= n:
            _add_pat([trip[i % len(trip)] for i in range(n)])

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
    """True if no contiguous FLSA window of period_days exceeds threshold hours."""
    if period_days < 1 or not work_day_flags:
        return True
    n = len(work_day_flags)
    # Extend by one period for wrap-free sliding windows over finite sim
    for start in range(0, max(1, n - period_days + 1)):
        hours = sum(1 for d in work_day_flags[start : start + period_days] if d) * shift_hours
        if hours > threshold + 1e-6:
            return False
    return True


def _auto_min_officer_search(config: SimulatorConfig, max_n: int = 80) -> Tuple[int, Optional["SimulatorResult"]]:
    """Bisect search for smallest N that yields a hard-constraint-passing simulation.

    Uses a true binary search: O(log N) full-sim calls instead of O(N).
    Falls back to the best soft-pass found if no N satisfies hard constraints.
    """
    best_soft: Optional[SimulatorResult] = None
    best_soft_n: int = max_n

    def _try(n: int) -> bool:
        """Return True when N passes hard constraints; cache any soft pass."""
        nonlocal best_soft, best_soft_n
        trial = SimulatorConfig(**{**config.__dict__, "num_officers": n, "auto_min_officers": False})
        result = _simulate_schedule_fixed_n(trial)
        if not result.success:
            return False
        if result.metrics.get("hard_constraints_ok", True):
            return True
        # Soft pass — keep as fallback
        if best_soft is None or n < best_soft_n:
            best_soft_n, best_soft = n, result
        return False

    # Phase 1: find an upper bound that works (doubles from 1)
    lo, hi = 1, 1
    while hi <= max_n and not _try(hi):
        hi = min(hi * 2, max_n)
        if hi == max_n and not _try(hi):
            return best_soft_n, best_soft

    # Phase 2: bisect lo..hi to find the minimum passing N
    lo = max(1, hi // 2)
    while lo < hi:
        mid = (lo + hi) // 2
        if _try(mid):
            hi = mid
        else:
            lo = mid + 1

    # Confirm and return
    trial = SimulatorConfig(**{**config.__dict__, "num_officers": hi, "auto_min_officers": False})
    result = _simulate_schedule_fixed_n(trial)
    if result.success and result.metrics.get("hard_constraints_ok", True):
        return hi, result
    return best_soft_n, best_soft


def simulate_schedule(config: SimulatorConfig) -> SimulatorResult:
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
        slot_pat_idx = list(range(n_slots))
        if config.pattern_slot_map and len(config.pattern_slot_map) >= n_slots:
            slot_pat_idx = [int(config.pattern_slot_map[i]) % n_pat for i in range(n_slots)]
        else:
            slot_pat_idx = [i % n_pat for i in range(n_slots)]
        sim_start = config.sim_start_date or date.today()
        best_phases = [0] * n_slots
        if config.phase_overrides is not None and len(config.phase_overrides) >= n_slots:
            best_phases = [int(config.phase_overrides[i]) % max(cycle_length, 1) for i in range(n_slots)]
        elif config.stagger_phases and n_slots > 1:
            best_score = -(10**9)
            # Score using real calendar weekdays over the sim window so Fri/Sat
            # night windows get enough bodies (need ≥5 for 1+2+2 on 8h three-band).
            for step in range(1, max(2, cycle_length // 2 + 1)):
                for offset in range(cycle_length):
                    trial = [((i * step) + offset) % cycle_length for i in range(n_slots)]
                    day_counts = []
                    fri_sat_penalty = 0
                    for day_offset in range(max(config.simulation_days, cycle_length)):
                        cycle_day = (day_offset % cycle_length) + 1
                        working = 0
                        for i in range(n_slots):
                            p = custom_patterns[slot_pat_idx[i]].with_phase(trial[i])
                            if p.is_working(cycle_day):
                                working += 1
                        day_counts.append(working)
                        cal = sim_start + timedelta(days=day_offset)
                        if cal.weekday() in (4, 5) and working < 5:
                            fri_sat_penalty += (5 - working) * 200
                    score = (
                        min(day_counts) * 1000
                        + sorted(day_counts)[min(1, len(day_counts) - 1)] * 50
                        - (max(day_counts) - min(day_counts))
                        - fri_sat_penalty
                    )
                    if score > best_score:
                        best_score = score
                        best_phases = trial
        for i, slot in enumerate(slots):
            base_p = custom_patterns[slot_pat_idx[i]]
            if config.phase_overrides is not None:
                phase = best_phases[i]
            else:
                phase = best_phases[i] if config.stagger_phases else 0
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

    # Rust path only when not using custom multi-block / FLSA hard / 24/7 / extra windows
    use_rust = (
        rust_bridge
        and rust_bridge.available()
        and not custom_patterns
        and not config.avoid_flsa_overtime
        and not config.coverage_247
        and not (config.use_extra_windows and config.extra_windows)
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
    per_slot_work_flags: List[List[bool]] = [[] for _ in slots]
    prev_day_starts: List[str] = []
    offday_coverage_total = 0

    for day_offset in range(config.simulation_days):
        target = sim_start + timedelta(days=day_offset)
        cycle_day = (day_offset % cycle_length) + 1
        shift_counts: Dict[str, int] = {t[0]: 0 for t in shift_templates}
        working_officers: List[SimulatorOfficerSlot] = []
        working_indices: List[int] = []

        for si, slot in enumerate(slots):
            if custom_patterns:
                working = slot_patterns[si].is_working(cycle_day)
            elif config.apply_department_rules:
                from logic.rotation_config import is_squad_working

                working = is_squad_working(slot.squad, cycle_day, preset)
            else:
                working = _squad_working(config.rotation_type, slot.squad, cycle_day, preset)
            per_slot_work_flags[si].append(working)
            if not working:
                continue
            slot.work_days_in_sim += 1
            working_officers.append(slot)
            working_indices.append(si)

        # Daily start assignment: flexible half-hour grid OR pack rebalance with
        # home + nearby hops (e.g. home 19:00 may work 14:00 / 22:00 that day).
        fri_sat = target.weekday() in (4, 5)
        win_min = 0
        if config.use_extra_windows and config.extra_windows and fri_sat:
            win_min = 2
            for w in config.extra_windows:
                if not isinstance(w, dict) or w.get("enabled") is False:
                    continue
                try:
                    wd = w.get("weekday")
                    if wd is not None and int(wd) != target.weekday():
                        continue
                    win_min = max(win_min, int(w.get("min_officers") or 2))
                except (TypeError, ValueError):
                    pass
        nearby_hops = max(0, int(getattr(config, "nearby_start_hops", 1) or 0))
        if getattr(config, "flexible_daily_starts", False) and working_officers:
            day_bands = _assign_flexible_day_starts(
                len(working_officers),
                config.shift_length_hours,
                min_247=max(int(config.coverage_247 or 0), int(config.min_per_shift or 0), 1)
                if (config.coverage_247 or config.min_per_shift)
                else 0,
                fri_sat_window=fri_sat and bool(config.use_extra_windows and config.extra_windows),
                window_min=win_min,
                window_start="19:00",
                window_end="03:00",
                hint_templates=shift_templates,
                prev_starts=prev_day_starts,
            )
        else:
            day_bands = _balance_day_assignments(
                working_officers,
                shift_templates,
                min_per_shift=config.min_per_shift,
                prefer_night=is_high_risk_night(target),
                fri_sat_window=fri_sat and bool(config.use_extra_windows and config.extra_windows),
                nearby_hops=nearby_hops,
            )
        # Track used starts only (empty fixed templates are not gaps when flexible)
        used_counts: Dict[str, int] = {}
        today_starts: List[str] = []
        for slot, (st, en) in zip(working_officers, day_bands):
            used_counts[st] = used_counts.get(st, 0) + 1
            shift_counts[st] = shift_counts.get(st, 0) + 1
            day_assignments.append((target, st, en))
            today_starts.append(st)

        # Off-day coverage: multi-block OFF officers can start at home/nearby when
        # work-day body count alone cannot staff min window / 24/7 floors.
        offday_adds = 0
        if getattr(config, "allow_offday_coverage", False) and custom_patterns and shift_templates:
            off_slots = [slots[si] for si in range(len(slots)) if si not in working_indices]
            need_bodies = max(
                int(config.coverage_247 or 0),
                int(config.min_per_shift or 0),
                int(win_min) if fri_sat else 0,
            )
            short = max(0, need_bodies - len(working_officers))
            # Also pull when Fri/Sat evening seats thin vs window_min
            evening_starts = {
                t[0]
                for t in shift_templates
                if _hhmm_to_min(t[0]) >= 18 * 60
                or _hhmm_to_min(t[0]) < 6 * 60
                or 12 * 60 <= _hhmm_to_min(t[0]) < 20 * 60
            }
            eve_on = sum(1 for s in today_starts if s in evening_starts or _hhmm_to_min(s) >= 14 * 60)
            if fri_sat and win_min > 0:
                short = max(short, win_min - min(eve_on, win_min) if eve_on < win_min else 0)
                # Prefer dedicated 19:00-class starts for window
                n_19 = sum(1 for s in today_starts if abs(_hhmm_to_min(s) - 19 * 60) <= 30)
                short = max(short, win_min - n_19 if n_19 < win_min else 0)
            for off_slot in off_slots:
                if short <= 0:
                    break
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
                # Fri/Sat: bias toward evening band among nearby
                if fri_sat and win_min > 0:
                    prefer = sorted(
                        prefer,
                        key=lambda i: (
                            0
                            if abs(_hhmm_to_min(shift_templates[i][0]) - 19 * 60) <= 30
                            else 1
                            if _hhmm_to_min(shift_templates[i][0]) >= 14 * 60
                            else 2,
                            abs(_hhmm_to_min(shift_templates[i][0]) - 19 * 60),
                        ),
                    )
                pick_i = prefer[0] if prefer else home_i
                st, en = shift_templates[pick_i]
                day_assignments.append((target, st, en))
                today_starts.append(st)
                used_counts[st] = used_counts.get(st, 0) + 1
                shift_counts[st] = shift_counts.get(st, 0) + 1
                offday_adds += 1
                short -= 1
            offday_coverage_total += offday_adds

        prev_day_starts = today_starts

        day_min = min(used_counts.values()) if used_counts else 0
        day_max = max(used_counts.values()) if used_counts else 0
        min_coverage = min(min_coverage, day_min)
        max_coverage = max(max_coverage, day_max)

        # Band floor gaps only for rigid fixed-desk model (no nearby moves, no flex grid).
        # Home+nearby rebalance intentionally leaves some pack bands empty some days.
        rigid_bands = (
            not getattr(config, "flexible_daily_starts", False)
            and int(getattr(config, "nearby_start_hops", 1) or 0) <= 0
        )
        if rigid_bands:
            for shift_start, count in shift_counts.items():
                required = config.min_per_shift
                if config.apply_department_rules and _is_night_shift_start(shift_start) and is_high_risk_night(target):
                    required = max(required, config.night_minimum)
                if count < required:
                    gap = required - count
                    gap_counter[(day_offset, shift_start)] = gap_counter.get((day_offset, shift_start), 0) + gap
                    total_gap_hours += gap * config.shift_length_hours
                    if _is_night_shift_start(shift_start) and is_high_risk_night(target):
                        night_risk_gaps += 1

        coverage_by_day.append(
            {
                "date": format_date(target),
                "cycle_day": cycle_day,
                "shift_counts": shift_counts,
                "working_officers": len(working_officers),
                "min_shift_coverage": day_min,
                "high_risk_night": is_high_risk_night(target),
            }
        )

    # Annual hours: use rotation-cycle fraction when multi-block patterns are set.
    # Short sim windows (28d) + phase stagger produce noisy work_day counts that
    # falsely put everyone outside a tight ±20h band even when the pattern is
    # exactly 2008h (e.g. 11/16 × 365 × 8h = 2007.5).
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
    # Coefficient of range: (max − min) / avg.  Named "range_ratio" to distinguish
    # from statistical variance.  Threshold in suggestions is 0.15 (~300h on 2008h).
    hours_range_ratio = 0.0
    if hours_list and avg_hours:
        hours_range_ratio = (max(hours_list) - min(hours_list)) / avg_hours

    slots_per_day = len(shift_templates)
    weekly_hours_needed = 24 * 7 * max(config.min_per_shift, config.coverage_247 or 1)
    annual_hours_needed = weekly_hours_needed * 52
    fte_required = annual_hours_needed / max(config.annual_hours_target, 1)

    coverage_pct = 100.0
    if gap_counter:
        total_required = config.simulation_days * slots_per_day * config.min_per_shift
        total_met = total_required - sum(gap_counter.values())
        coverage_pct = round(100 * total_met / max(total_required, 1), 1)

    # --- Hard constraint evaluation ---
    hard_ok = True
    flsa_violations = 0
    flsa_threshold = 0.0
    if config.avoid_flsa_overtime:
        from logic.labor_compliance import flsa_threshold_for_period_days

        period_days = max(7, min(int(config.flsa_work_period_days or 28), 28))
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
                # Overnight or late starts that cover early morning of first_day+1
                # also imply prior cycle coverage into first_day 00:00–start.
                try:
                    sh = int(st.split(":")[0])
                except ValueError:
                    sh = 0
                if sh >= 18 or sh < 6:
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

    # Annual hours: cycle math is a year-average. Officers will not all work
    # identical hours in a calendar year (cycle rarely divides 365/366; phase
    # and leap years shift duty days). Hard mode checks:
    #   1) mean hours near target (± variance)
    #   2) peer fairness — max−min spread not far beyond variance
    # Individual officers may sit slightly outside the band without failing hard.
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
        # Allow peer spread up to 2× variance (phases/year boundary); beyond = unfair
        max_spread = max(float(config.annual_hours_variance or 0) * 2.0, 40.0)
        if annual_hours_spread > max_spread + 1e-6:
            annual_unfair = 1
        if config.annual_hours_hard and (annual_mean_outside or annual_unfair):
            hard_ok = False

    rigid_bands = (
        not getattr(config, "flexible_daily_starts", False) and int(getattr(config, "nearby_start_hops", 1) or 0) <= 0
    )
    if gap_counter and config.min_per_shift > 0 and rigid_bands:
        hard_ok = False

    # --- min_rest_hours hard gate ---
    # Check chronological day_assignments per slot to enforce a minimum rest
    # gap between the end of one shift and the start of the next work day.
    rest_failures = 0
    min_rest = float(getattr(config, "min_rest_hours", 0) or 0)
    if min_rest > 0 and day_assignments:
        # Group assignments by slot index for chronological gap checking
        slot_asg_map: Dict[int, List[Tuple[date, str, str]]] = {i: [] for i in range(len(slots))}
        # day_assignments are (date, start, end) in sim order — map back to slot
        # via per_slot_work_flags which tracks slot work days in order.
        slot_day_idx: List[int] = [0] * len(slots)  # pointer into per_slot_work_flags
        asg_flat: List[Tuple[int, date, str, str]] = []
        day_iter_off = 0
        for day_offset in range(config.simulation_days):
            target_d = sim_start + timedelta(days=day_offset)
            for si in range(len(slots)):
                if day_offset < len(per_slot_work_flags[si]) and per_slot_work_flags[si][day_offset]:
                    # Find assignment for this slot on this day
                    # Assignments were appended in order: working_officers then off-day fills
                    # We use (date, shift_start) key matching slot home band
                    pass  # populated below from day_assignments chronologically
        # Rebuild per-slot chronological assignment list
        _slot_assigns: Dict[int, List[Tuple[date, str, str]]] = {i: [] for i in range(len(slots))}
        _day_slot_cursor = [0] * len(slots)
        for day_offset in range(config.simulation_days):
            target_d = sim_start + timedelta(days=day_offset)
            for si, slot in enumerate(slots):
                if day_offset < len(per_slot_work_flags[si]) and per_slot_work_flags[si][day_offset]:
                    # Match to day_assignments by date + slot home band (best-effort)
                    for da in day_assignments:
                        if da[0] == target_d:
                            _slot_assigns[si].append(da)
                            break
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
        "avg_annual_hours": round(avg_hours, 1),
        # Coefficient of range (max−min)/avg — see hours_range_ratio comment above
        "hours_variance_ratio": round(hours_range_ratio, 3),  # legacy key kept for UI compat
        "hours_range_ratio": round(hours_range_ratio, 3),
        "gap_events": len(gap_counter),
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
    gap_events = int(metrics.get("gap_events", 0))
    total_gap_hours = gap_events * config.shift_length_hours
    night_risk_gaps = 0
    for day in coverage_by_day:
        if not day.get("high_risk_night"):
            continue
        shift_counts = day.get("shift_counts", {})
        for shift_start, count in shift_counts.items():
            required = config.min_per_shift
            if config.apply_department_rules and _is_night_shift_start(shift_start):
                required = max(required, config.night_minimum)
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
    # Align with Python path: band min gaps are hard when min_per_shift enforced
    if "hard_constraints_ok" not in enriched:
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
        suggestions.append(
            SimulatorSuggestion(
                severity="critical",
                title="Understaffed for 24/7 coverage",
                message=(
                    f"Estimated {metrics['fte_required']:.1f} FTE required; you have {config.num_officers} officers."
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

    if config.apply_department_rules and metrics["night_risk_gaps"] > 0:
        suggestions.append(
            SimulatorSuggestion(
                severity="warning",
                title="Friday/Saturday night minimum at risk",
                message=f"{metrics['night_risk_gaps']} night shift(s) below department minimum.",
                recommendation=f"Assign {NIGHT_MINIMUM_OFFICERS}+ officers to each night shift on Fri/Sat.",
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

    if not gap_counter and metrics["coverage_percent"] >= 99:
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
