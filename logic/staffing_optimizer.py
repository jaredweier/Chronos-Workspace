"""
Staffing schedule optimizer — exhaustive search over the constraint-defined space.

NOT bump / leave-coverage logic (see coverage_optimizer / bump_optimizer).

Search size is determined only by free vs locked dimensions and multi-block
phase/pattern layouts — there is no max_total_evals cap that abandons remaining
candidates. Call estimate_search_space() before a run to warn operators when the
space (and wall time) is large.

Near-miss plans are retained when no layout meets every hard constraint, ranked
by user constraint_weights / constraint_priority.
"""

from __future__ import annotations

import itertools
import os
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

import config

# C1 — opt-in process pool (Windows spawn-safe top-level worker)
_OPT_PROCESS_WORKERS = max(0, int(os.environ.get("SCHEDULER_OPT_PROCESS_WORKERS", "0") or 0))
# Default: half of cores (2–4) for full-sim batches — cancel still checked between batches
_OPT_THREAD_DEFAULT = min(4, max(2, (os.cpu_count() or 4) // 2))
_OPT_THREAD_WORKERS = max(
    1,
    int(os.environ.get("SCHEDULER_OPT_THREAD_WORKERS", str(_OPT_THREAD_DEFAULT)) or _OPT_THREAD_DEFAULT),
)

# Bounded microcaches (cheap prune / pack filters). Cleared only by process lifetime;
# keys are pure inputs so cross-run reuse is safe.
_ANNUAL_HOURS_CACHE: Dict[Tuple[str, float], float] = {}
_DUTY_VEC_CACHE: Dict[int, Tuple[bool, ...]] = {}
_MAX_REST_PACK_CACHE: Dict[Tuple[Tuple[str, ...], float, int, int], int] = {}
_PACK_WINDOW_BANDS_CACHE: Dict[Tuple[Tuple[str, ...], float, Tuple[Tuple[Any, ...], ...], Optional[int]], bool] = {}
_MAX_ON_STREAK_CACHE: Dict[Tuple[Tuple[bool, ...], int], int] = {}
_CACHE_CAP = 4096


def _cache_put(store: Dict, key: Any, value: Any) -> Any:
    if len(store) >= _CACHE_CAP:
        # Drop an arbitrary ~25% (dict order = insertion) to bound memory
        for i, k in enumerate(list(store.keys())):
            if i >= _CACHE_CAP // 4:
                break
            del store[k]
    store[key] = value
    return value


def _pattern_cache_key(pattern) -> str:
    """Stable text key for RotationPattern / _DutyRing annual + duty caches."""
    try:
        return str(pattern.to_text())
    except Exception:
        try:
            return str(tuple(pattern.duty_vector()))
        except Exception:
            return str(id(pattern))


def _duty_vec_cached(pattern) -> Tuple[bool, ...]:
    pid = id(pattern)
    hit = _DUTY_VEC_CACHE.get(pid)
    if hit is not None:
        return hit
    try:
        vec = tuple(bool(x) for x in pattern.duty_vector())
    except Exception:
        vec = tuple()
    return _cache_put(_DUTY_VEC_CACHE, pid, vec)


def _projected_annual_cached(pattern, shift_length: float) -> float:
    from logic.rotation_patterns import projected_annual_hours

    key = (_pattern_cache_key(pattern), round(float(shift_length), 4))
    hit = _ANNUAL_HOURS_CACHE.get(key)
    if hit is not None:
        return hit
    val = float(projected_annual_hours(pattern, shift_length))
    return _cache_put(_ANNUAL_HOURS_CACHE, key, val)


def _full_sim_worker(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Top-level picklable worker for process-pool full sims."""
    from simulator import SimulatorConfig, simulate_schedule

    ph = payload.get("ph")
    pm = payload.get("pm")
    cfg = SimulatorConfig(**payload["cfg"])
    sim = simulate_schedule(cfg)
    return {
        "ph": ph,
        "pm": pm,
        "success": bool(sim.success),
        "metrics": dict(sim.metrics or {}),
        "suggestions": [
            {
                "severity": s.severity,
                "title": s.title,
                "message": s.message,
                "recommendation": s.recommendation,
            }
            for s in (sim.suggestions or [])
        ],
        "officer_slots": [s.__dict__ if hasattr(s, "__dict__") else s for s in (sim.officer_slots or [])],
    }


# Full start-pack catalog size when starts are free (no artificial depth cap)
FREE_STARTS_MAX_PACKS = 64

# Legacy name kept for imports; content is example-only fallback if annual math empty.
# Prefer generate_multi_block_variation_sets(annual, length) when free_variations.
MULTI_BLOCK_CATALOG: List[List[str]] = []

# Default soft priority when ranking near-misses (higher = more important to satisfy)
DEFAULT_CONSTRAINT_WEIGHTS: Dict[str, float] = {
    "coverage_247": 100.0,
    "windows": 90.0,
    "gaps": 80.0,
    "flsa": 70.0,
    "annual": 40.0,  # year math is approximate — softest by default
    "headcount": 10.0,  # prefer fewer officers when equal quality
}

CONSTRAINT_LABELS: Dict[str, str] = {
    "coverage_247": "24/7 Minimum Coverage",
    "windows": "Extra Staffing Windows",
    "gaps": "Minimum Officers Per Shift Band",
    "flsa": "Avoid FLSA Overtime",
    "annual": "Annual Hours Target (Year-Average Fairness)",
    "headcount": "Prefer Fewer Officers",
}


def _format_hhmm(hour: int, minute: int = 0) -> str:
    """Clock label; minute must be 0 or 30 (half-hour grid only)."""
    m = 0 if int(minute) < 15 else (30 if int(minute) < 45 else 0)
    h = int(hour) % 24
    if int(minute) >= 45:
        h = (h + 1) % 24
    return f"{h:02d}:{m:02d}"


def _half_hour_starts() -> List[str]:
    """All legal start times on a 30-minute grid (00:00, 00:30, …, 23:30)."""
    out: List[str] = []
    for h in range(24):
        out.append(_format_hhmm(h, 0))
        out.append(_format_hhmm(h, 30))
    return out


def _snap_to_half_hour(label: str) -> str:
    """Snap a HH:MM string to the nearest half-hour slot."""
    try:
        parts = (label or "00:00").strip().split(":")
        h = int(parts[0])
        m = int(parts[1]) if len(parts) > 1 else 0
    except (TypeError, ValueError):
        return "00:00"
    total = (h * 60 + m + 15) // 30 * 30
    total %= 24 * 60
    return _format_hhmm(total // 60, total % 60)


def pack_meets_coverage_247(
    starts: Sequence[str],
    shift_length_hours: float,
    coverage_247: int = 1,
) -> bool:
    """
    True if pack can *possibly* support 24/7 occupancy ≥ coverage_247.

    Only rejects when some half-hour has **zero** covering bands (stacking
    cannot invent cover). Concurrent need (>1) is an assignment problem:
    classic 06/14/22 @8h meets dual 24/7 with 2 officers per band.
    Use bodies_needed_247 for the person floor.
    """
    need = int(coverage_247 or 0)
    if need <= 0:
        return True
    if not starts:
        return False
    # Unique starts only — duplicate labels do not add timeline cover
    uniq = list(dict.fromkeys(str(s) for s in starts if s))
    # ≥1 band at thinnest sample; need itself is headcount not band count
    return pack_window_band_capacity(uniq, float(shift_length_hours), "00:00", "23:59") >= 1


def generate_start_packs(
    shift_length_hours: float,
    *,
    max_packs: int = 1000,
    num_officers: int = 6,
    max_bands: Optional[int] = None,
    min_bands: int = 2,
    extra_windows: Optional[List[Dict]] = None,
    coverage_247: int = 0,
    filter_infeasible: bool = True,
    min_rest_hours: float = 0.0,
    nearby_hops: int = 1,
) -> List[List[str]]:
    """
    Build start-time packs on a 30-minute grid.

    When filter_infeasible and hard-ish coverage is set (windows / 24/7 / min rest),
    drop packs that cannot possibly cover those arcs — L2 domain reduction before search.
    """
    import itertools
    import math

    packs: List[List[str]] = []
    seen = set()
    length = float(shift_length_hours)
    cov = int(coverage_247 or 0)
    wins = list(extra_windows or []) if extra_windows else []
    min_rest = float(min_rest_hours or 0)
    # L2: when coverage constraints bind, do not flood C(n,k) to 1000 —
    # search already only uses priority head (~48–64).
    if filter_infeasible and (cov > 0 or wins or min_rest > 0):
        max_packs = min(int(max_packs), int(FREE_STARTS_MAX_PACKS))

    def _feasible(uniq: List[str]) -> bool:
        if not filter_infeasible:
            return True
        if cov > 0 and not pack_meets_coverage_247(uniq, length, cov):
            return False
        if wins and not pack_meets_window_bands(uniq, length, wins, num_officers=num_officers):
            return False
        if min_rest > 0:
            mx = max_rest_minutes_for_pack(
                uniq,
                length,
                day_gap_days=1,
                nearby_hops=int(nearby_hops or 0),
            )
            if mx < min_rest * 60.0 - 1.0:
                return False
        return True

    def _add(starts: Sequence[str]) -> None:
        cleaned = [_snap_to_half_hour(s) for s in starts if s]
        if len(cleaned) < 2:
            return
        uniq = []
        for s in cleaned:
            if s not in uniq:
                uniq.append(s)
        if len(uniq) < 2:
            return
        key = tuple(sorted(uniq))
        if key in seen:
            return
        if not _feasible(uniq):
            return
        seen.add(key)
        packs.append(list(uniq))

    # Base hours to select from
    core_starts = [
        "05:00",
        "06:00",
        "07:00",
        "08:00",  # Morning
        "13:00",
        "14:00",
        "15:00",
        "16:00",
        "17:00",  # Afternoon
        "18:00",
        "19:00",
        "20:00",
        "21:00",
        "22:00",
        "23:00",  # Night
        "00:00",
        "02:00",  # Midnight
    ]

    # Priority LE-sane packs FIRST (never crowded out by C(n,k) explosion).
    # Shapes only — not a single department scenario: equal-space, evening denser,
    # 12h dual, staggered 10h-class. Caller constraints decide which hard-pass.
    for seed in (
        ["06:00", "14:00", "22:00"],
        ["06:00", "14:00", "19:00", "22:00"],
        ["07:00", "15:00", "23:00"],
        ["07:00", "15:00", "19:00", "23:00"],
        ["06:00", "18:00"],
        ["07:00", "19:00"],
        ["05:00", "13:00", "21:00"],
        ["08:00", "16:00", "00:00"],
        ["06:00", "12:00", "18:00", "00:00"],
        ["07:00", "13:00", "19:00", "01:00"],
    ):
        _add(seed)

    # Equal-spaced bands from anchors
    anchors = ["05:00", "06:00", "07:00", "18:00", "19:00"]
    for spacing_h in [6, 8, 12]:
        spacing_min = spacing_h * 60
        for a in anchors:
            try:
                ah, am = map(int, a.split(":"))
                base = ah * 60 + am
                combo = [
                    _format_hhmm((base + i * spacing_min) // 60, (base + i * spacing_min) % 60)
                    for i in range(24 // spacing_h)
                ]
                _add(combo)
            except Exception:
                pass

    # Prefer explicit max_bands; else HEAD-style cap by roster size (≤6).
    # 24/7 implies at least ceil(24/L) bands.
    min_k = max(2, int(min_bands or 2))
    if cov > 0 and length > 0:
        min_k = max(min_k, int(math.ceil(24.0 / length)))
    if max_bands is None:
        max_combos = min(max(2, int(num_officers or 2)), 6)
    else:
        max_combos = min(max(int(min_bands or 2), int(max_bands)), 8)
    if min_k > max_combos:
        max_combos = min_k

    # Combinatorial fill after priority seeds (may hit max_packs)
    for k in range(min_k, max_combos + 1):
        for combo in itertools.combinations(core_starts, k):
            _add(combo)
            if len(packs) >= max_packs:
                break
        if len(packs) >= max_packs:
            break

    # If filters wiped everything, return unfiltered priority seeds so soft mode
    # can still rank near-misses (never empty domain silently).
    if not packs and filter_infeasible and (cov > 0 or wins or min_rest > 0):
        return generate_start_packs(
            length,
            max_packs=max(16, max_packs // 4),
            num_officers=num_officers,
            max_bands=max_bands,
            min_bands=min_bands,
            filter_infeasible=False,
        )[: max(8, min(32, max_packs))]

    return packs[:max_packs]


def generate_length_options(*, lo: float = 8.0, hi: float = 12.5) -> List[float]:
    out: List[float] = []
    x = lo
    while x <= hi + 1e-9:
        out.append(round(x, 1))
        x += 0.5
    return out


def generate_officer_counts(
    *,
    explicit: Optional[List[int]] = None,
    free: bool = False,
    base: int = 8,
    lo: int = 4,
    hi: int = 20,
) -> List[int]:
    if explicit is not None:
        return sorted({max(1, int(n)) for n in explicit})
    if not free:
        return [max(1, int(base))]
    return list(range(max(1, lo), max(lo, hi) + 1))


def generate_phase_layouts(
    n_slots: int,
    cycle_length: int,
    *,
    mode: str = "full",
) -> List[List[int]]:
    """
    Phase model for multi-block stagger:
    - even spacing for every offset (priority + full)
    - arithmetic progressions step×offset (full; thinned when large)
    mode='priority' — even spacing + anchors only (fast first pass)
    mode='full' — denser finite model (no random sample)
    """
    if n_slots < 1 or cycle_length < 1:
        return [[0] * max(n_slots, 0)]
    layouts: List[List[int]] = []
    seen = set()
    priority_only = (mode or "full").strip().lower() == "priority"

    def _add(phases: List[int]) -> None:
        key = tuple(int(p) % cycle_length for p in phases)
        if key in seen:
            return
        seen.add(key)
        layouts.append(list(key))

    stride = max(1, cycle_length // max(n_slots, 1))
    for offset in range(cycle_length):
        _add([(i * stride + offset) % cycle_length for i in range(n_slots)])

    _add([0] * n_slots)
    _add([i % cycle_length for i in range(n_slots)])
    # Half-cycle stagger (common LE multi-block)
    half = max(1, cycle_length // 2)
    _add([(i * half) % cycle_length for i in range(n_slots)])

    if priority_only:
        return layouts

    # Arithmetic progressions — thin offsets when space is large
    max_step = max(2, min(cycle_length // 2, n_slots + 2))
    offset_stride = 1 if (cycle_length <= 14 and n_slots <= 7) else 2
    for step in range(1, max_step + 1):
        for offset in range(0, cycle_length, offset_stride):
            _add([((i * step) + offset) % cycle_length for i in range(n_slots)])

    return layouts


def generate_pattern_maps(n_slots: int, n_patterns: int) -> List[List[int]]:
    """Complete structured pattern↔slot maps (full 2^n when n_slots ≤ 10 and 2 patterns)."""
    if n_slots < 1 or n_patterns < 1:
        return [[0] * max(n_slots, 0)]
    if n_patterns == 1:
        return [[0] * n_slots]
    maps: List[List[int]] = []
    seen = set()

    def _add(m: List[int]) -> None:
        key = tuple(int(x) % n_patterns for x in m)
        if key in seen:
            return
        seen.add(key)
        maps.append(list(key))

    _add([i % n_patterns for i in range(n_slots)])
    _add([(n_patterns - 1 - (i % n_patterns)) for i in range(n_slots)])
    mid = n_slots // 2
    _add([0] * mid + [1 % n_patterns] * (n_slots - mid))
    _add([1 % n_patterns] * mid + [0] * (n_slots - mid))
    _add([(i // 2) % n_patterns for i in range(n_slots)])
    _add([0] * n_slots)
    if n_patterns > 1:
        _add([1 % n_patterns] * n_slots)

    if n_patterns == 2 and n_slots <= 6:
        # Full assignment space 2^n (complete for two multi-block variations)
        for k in range(0, n_slots + 1):
            for ones in itertools.combinations(range(n_slots), k):
                m = [0] * n_slots
                for i in ones:
                    m[i] = 1
                _add(m)
    elif n_patterns == 2:
        # Larger N: every headcount split + even/odd placements (finite model, no sample cap)
        for k in range(0, n_slots + 1):
            if k == 0:
                _add([0] * n_slots)
                continue
            step = n_slots / k
            for shift in range(max(1, n_slots // max(k, 1))):
                m = [0] * n_slots
                for j in range(k):
                    m[int(j * step + shift) % n_slots] = 1
                _add(m)
    return maps


def _window_weekdays_from_extra(
    extra_windows: Optional[List[Dict]] = None,
    *,
    default: Tuple[int, ...] = (4, 5),
) -> Tuple[int, ...]:
    """Weekdays (0=Mon) that carry a window min floor; default Fri/Sat."""
    if not extra_windows:
        return default
    found: List[int] = []
    for w in extra_windows:
        if not isinstance(w, dict) or not w.get("enabled", True):
            continue
        try:
            need = int(w.get("min_officers") or 0)
        except (TypeError, ValueError):
            need = 0
        if need <= 0:
            continue
        raw = w.get("weekday", w.get("weekdays", w.get("dow")))
        if raw is None:
            # Unscoped window → all days
            return tuple(range(7))
        if isinstance(raw, (list, tuple, set)):
            for item in raw:
                try:
                    found.append(int(item) % 7)
                except (TypeError, ValueError):
                    continue
        else:
            try:
                found.append(int(raw) % 7)
            except (TypeError, ValueError):
                continue
    return tuple(sorted(set(found))) if found else default


def bodies_needed_247(shift_length_hours: float, coverage_247: int) -> int:
    """
    Concurrent person-floor for 24/7: each ON officer covers one shift of length L.
    Need ceil(24/L)×coverage_247 (stacking allowed — e.g. 8h dual = 3 bands × 2 = 6).
    """
    import math

    cov = max(0, int(coverage_247 or 0))
    if cov <= 0:
        return 0
    length = float(shift_length_hours or 0)
    if length <= 0:
        return cov
    bands = max(1, math.ceil(24.0 / length))
    return int(bands * cov)


def rest_gap_minutes(
    prev_start: str,
    curr_start: str,
    shift_length_hours: float,
    *,
    day_gap_days: int = 1,
) -> int:
    """
    Rest minutes from end of prev shift to start of next (matches simulator hard gate).

    Overnight: end clock ≤ start clock ⇒ end is next calendar morning.
    day_gap_days: calendar days between the two work dates (1 = consecutive days).
    """
    ps = _hhmm_to_min(prev_start)
    length_min = max(0, int(round(float(shift_length_hours) * 60)))
    pe_clock = (ps + length_min) % (24 * 60)
    if length_min > 0 and pe_clock <= ps:
        pe_abs = pe_clock + 24 * 60
    else:
        pe_abs = pe_clock
    gap = max(0, int(day_gap_days))
    curr_abs = gap * 24 * 60 + _hhmm_to_min(curr_start)
    return int(curr_abs - pe_abs)


def max_rest_minutes_for_pack(
    shift_starts: Sequence[str],
    shift_length_hours: float,
    *,
    day_gap_days: int = 1,
    nearby_hops: int = 0,
) -> int:
    """Best rest achievable between two work days using pack starts (± nearby hops)."""
    starts = list(shift_starts or [])
    hops = max(0, int(nearby_hops or 0))
    gap = int(day_gap_days or 1)
    if not starts:
        # No pack: same-start rest only (conservative; free clock can do better)
        return max(0, 24 * 60 - max(0, int(round(float(shift_length_hours) * 60))))
    ckey = (tuple(sorted(str(s) for s in starts)), float(shift_length_hours), gap, hops)
    hit = _MAX_REST_PACK_CACHE.get(ckey)
    if hit is not None:
        return int(hit)
    expanded = set(starts)
    if hops > 0:
        for s in starts:
            base = _hhmm_to_min(s)
            for h in range(-hops, hops + 1):
                m = (base + h * 30) % (24 * 60)
                expanded.add(f"{m // 60:02d}:{m % 60:02d}")
    labels = list(expanded)
    best = 0
    for s1 in labels:
        for s2 in labels:
            best = max(best, rest_gap_minutes(s1, s2, shift_length_hours, day_gap_days=gap))
    return int(_cache_put(_MAX_REST_PACK_CACHE, ckey, int(best)))


def pattern_has_adjacent_on(vec: Sequence[bool], phase: int = 0) -> bool:
    """True if duty ring has two consecutive ON days (wrap-aware over 2 cycles)."""
    if not vec:
        return False
    n = len(vec)
    for d in range(2 * n - 1):
        a = bool(vec[(d + int(phase)) % n])
        b = bool(vec[(d + 1 + int(phase)) % n])
        if a and b:
            return True
    return False


def _cheap_rest_fail(
    patterns,
    phases: List[int],
    pat_map: List[int],
    *,
    n_slots: int,
    shift_length: float,
    shift_starts: Optional[Sequence[str]],
    min_rest_hours: float,
    nearby_hops: int = 0,
) -> bool:
    """
    True if consecutive ON days exist and *no* pack start pair can meet min rest.

    Sound prune only (does not fail when some pair works — assignment may still fail full sim).
    """
    need = float(min_rest_hours or 0)
    if need <= 0 or not patterns or n_slots < 1:
        return False
    # Any officer with adjacent ON days?
    has_adj = False
    for i in range(n_slots):
        p = patterns[int(pat_map[i]) % len(patterns)]
        vec = _duty_vec_cached(p)
        if not vec:
            continue
        ph = int(phases[i]) % max(len(vec), 1)
        if pattern_has_adjacent_on(vec, ph):
            has_adj = True
            break
    if not has_adj:
        return False
    max_r = max_rest_minutes_for_pack(
        list(shift_starts or []),
        float(shift_length),
        day_gap_days=1,
        nearby_hops=int(nearby_hops or 0),
    )
    # 1-minute tolerance matches simulator
    return max_r < need * 60.0 - 1.0


def _day_body_counts(
    patterns,
    phases: List[int],
    pat_map: List[int],
    *,
    n_slots: int,
    simulation_days: int,
    sim_start: date,
    window_weekdays: Optional[Sequence[int]] = None,
) -> Tuple[List[int], List[int]]:
    """Fast body counts — precompute shifted duty rings (Python hot path; Rust full-sim separate).

    Returns (day_counts, window_day_counts) where window_day_counts are ON bodies
    on weekdays in window_weekdays (default Fri/Sat).
    """
    cycle = patterns[0].cycle_length
    n_days = max(simulation_days, cycle)
    wds = set(int(x) % 7 for x in (window_weekdays if window_weekdays is not None else (4, 5)))
    # Precompute each slot's duty mask for day_offset 0..n_days-1
    slot_work: List[List[bool]] = []
    for i in range(n_slots):
        p = patterns[pat_map[i] % len(patterns)]
        vec = _duty_vec_cached(p)
        n = len(vec)
        phase = int(phases[i]) % max(cycle, 1)
        if not n:
            slot_work.append([False] * n_days)
            continue
        # rotated view: day d uses vec[(d+phase)%n]
        slot_work.append([bool(vec[(d + phase) % n]) for d in range(n_days)])
    day_counts: List[int] = [0] * n_days
    window_days: List[int] = []
    base_wd = sim_start.weekday()
    for d in range(n_days):
        c = 0
        for i in range(n_slots):
            if slot_work[i][d]:
                c += 1
        day_counts[d] = c
        if (base_wd + d) % 7 in wds:
            window_days.append(c)
    return day_counts, window_days


def _max_on_streak(vec: Sequence[bool], phase: int = 0) -> int:
    """Max consecutive ON days over two cycles (wrap-aware)."""
    if not vec:
        return 0
    vkey = tuple(bool(x) for x in vec)
    ph = int(phase) % max(len(vkey), 1)
    ckey = (vkey, ph)
    hit = _MAX_ON_STREAK_CACHE.get(ckey)
    if hit is not None:
        return int(hit)
    n = len(vkey)
    doubled = [bool(vkey[(i + ph) % n]) for i in range(2 * n)]
    best = 0
    streak = 0
    for w in doubled:
        if w:
            streak += 1
            best = max(best, streak)
        else:
            streak = 0
    return int(_cache_put(_MAX_ON_STREAK_CACHE, ckey, int(best)))


def on_days_in_window_extremes(vec: Sequence[bool], window: int) -> Tuple[int, int]:
    """
    (sparsest, densest) ON-day counts over any contiguous `window` on the duty ring.

    Phase-invariant for a pure cycle. Sparsest × length > FLSA thr ⇒ every fixed
    period fails (sound hard prune). Densest × length ≤ thr ⇒ never fails.
    """
    if not vec or window < 1:
        return 0, 0
    n = len(vec)
    w = int(window)
    # Ring long enough for one full set of start offsets
    ring = [bool(x) for x in vec] * (w // n + 3)
    s = sum(1 for x in ring[:w] if x)
    lo = hi = s
    for i in range(1, n):
        s += (1 if ring[i + w - 1] else 0) - (1 if ring[i - 1] else 0)
        lo = min(lo, s)
        hi = max(hi, s)
    return int(lo), int(hi)


def pattern_flsa_always_fails(
    vec: Sequence[bool],
    shift_length_hours: float,
    *,
    period_days: int = 28,
    threshold: float = 171.0,
) -> bool:
    """True if every contiguous period_days block exceeds §207(k) hours (sound)."""
    if period_days < 1 or threshold <= 0 or not vec:
        return False
    lo, _hi = on_days_in_window_extremes(vec, int(period_days))
    return float(lo) * float(shift_length_hours) > float(threshold) + 1e-6


class _DutyRing:
    """Minimal pattern stand-in for squad presets in cheap prune (duty only)."""

    __slots__ = ("_vec", "cycle_length", "label")

    def __init__(self, vec: Sequence[bool], *, label: str = ""):
        self._vec = [bool(x) for x in vec]
        self.cycle_length = max(1, len(self._vec))
        self.label = label or "duty"

    def duty_vector(self) -> List[bool]:
        return list(self._vec)

    def work_days_per_cycle(self) -> int:
        return sum(1 for x in self._vec if x)


def duty_patterns_from_rotation(rotation_type: str) -> List[_DutyRing]:
    """Squad preset → duty rings for cheap prune / FLSA (not multi-block algebra)."""
    try:
        from config import ROTATION_PRESETS
    except Exception:
        return []
    preset = ROTATION_PRESETS.get(rotation_type) or ROTATION_PRESETS.get(str(rotation_type or "").strip())
    if not preset:
        return []
    cycle_len = int(preset.get("cycle_length") or 1)
    out: List[_DutyRing] = []
    if "squad_patterns" in preset:
        for name, pattern in (preset.get("squad_patterns") or {}).items():
            if pattern:
                out.append(_DutyRing([bool(x) for x in pattern], label=str(name)))
    elif "squad_a_days" in preset:
        squad_a = preset.get("squad_a_days") or set()
        out.append(_DutyRing([(i + 1) in squad_a for i in range(cycle_len)], label="A"))
        # Complement squad B (classic 2-squad)
        out.append(_DutyRing([(i + 1) not in squad_a for i in range(cycle_len)], label="B"))
    return out


def is_night_start(start: str) -> bool:
    try:
        hour = int(str(start).split(":")[0])
    except (TypeError, ValueError):
        return False
    return hour >= 18 or hour < 6


def pack_has_night_start(starts: Optional[Sequence[str]]) -> bool:
    return any(is_night_start(s) for s in (starts or []) if s)


def overnight_coverage_forced(
    *,
    coverage_247: int = 0,
    extra_windows: Optional[List[Dict]] = None,
    shift_length_hours: float = 8.0,
) -> bool:
    """True if 24/7 or a window arc requires staffing through night hours."""
    if int(coverage_247 or 0) > 0:
        return True
    night_samples = [22 * 60, 0, 2 * 60, 4 * 60]  # 22:00, 00:00, 02:00, 04:00
    for w in extra_windows or []:
        if not isinstance(w, dict) or not w.get("enabled", True):
            continue
        try:
            need = int(w.get("min_officers") or 0)
        except (TypeError, ValueError):
            need = 0
        if need <= 0:
            continue
        samples = _window_sample_minutes(
            str(w.get("start_time") or "00:00"),
            str(w.get("end_time") or "23:59"),
        )
        if any(
            m in samples or _minute_in_window(m, str(w.get("start_time") or "00:00"), str(w.get("end_time") or "23:59"))
            for m in night_samples
        ):
            return True
        # Overlap any night sample with window
        for m in night_samples:
            if _minute_in_window(
                m,
                str(w.get("start_time") or "00:00"),
                str(w.get("end_time") or "23:59"),
            ):
                return True
    del shift_length_hours
    return False


def _window_sample_minutes(win_start: str, win_end: str, step: int = 30) -> List[int]:
    ws = _hhmm_to_min(win_start)
    we = _hhmm_to_min(win_end)
    samples: List[int] = []
    if we > ws:
        t = ws
        while t < we:
            samples.append(t)
            t += step
    else:
        t = ws
        while t < 24 * 60:
            samples.append(t)
            t += step
        t = 0
        while t < we:
            samples.append(t)
            t += step
    return samples


def _minute_in_window(minute: int, win_start: str, win_end: str) -> bool:
    ws = _hhmm_to_min(win_start)
    we = _hhmm_to_min(win_end)
    m = int(minute) % (24 * 60)
    if we > ws:
        return ws <= m < we
    return m >= ws or m < we


def _cheap_flsa_fail(
    patterns,
    phases: List[int],
    pat_map: List[int],
    *,
    n_slots: int,
    shift_length: float,
    simulation_days: int,
    period_days: int,
    threshold: float,
) -> bool:
    """True if any officer's duty ring fails fixed-anchor FLSA for all anchors."""
    if period_days < 1 or threshold <= 0 or not patterns:
        return False
    # Fast sound path: sparsest period always over threshold
    for i in range(n_slots):
        p = patterns[int(pat_map[i]) % len(patterns)]
        vec = p.duty_vector()
        if pattern_flsa_always_fails(
            vec,
            float(shift_length),
            period_days=int(period_days),
            threshold=float(threshold),
        ):
            return True
    try:
        from simulator import _flsa_period_hours_ok
    except Exception:
        return False
    n_days = max(int(simulation_days), int(patterns[0].cycle_length), int(period_days))
    for i in range(n_slots):
        p = patterns[int(pat_map[i]) % len(patterns)]
        vec = p.duty_vector()
        if not vec:
            continue
        # Skip slow path when densest cannot exceed thr (always OK)
        _lo, hi = on_days_in_window_extremes(vec, int(period_days))
        if float(hi) * float(shift_length) <= float(threshold) + 1e-6:
            continue
        n = len(vec)
        phase = int(phases[i]) % n
        flags = [bool(vec[(d + phase) % n]) for d in range(n_days)]
        if not _flsa_period_hours_ok(flags, float(shift_length), int(period_days), float(threshold)):
            return True
    return False


def _shift_end_hhmm(start: str, length_hours: float) -> str:
    sm = _hhmm_to_min(start)
    em = (sm + int(round(float(length_hours) * 60))) % (24 * 60)
    return f"{em // 60:02d}:{em % 60:02d}"


def _cheap_window_minute_fail(
    patterns,
    phases: List[int],
    pat_map: List[int],
    *,
    n_slots: int,
    shift_starts: Sequence[str],
    shift_length: float,
    simulation_days: int,
    sim_start: date,
    windows: List[Dict],
    nearby_hops: int = 1,
    allow_offday_coverage: bool = False,
) -> bool:
    """
    C3 minute-bin: home+nearby pack assign on rotation ON days only (unless
    allow_offday_coverage). Fail if any window min occupancy short.
    """
    if not windows or not shift_starts or not patterns:
        return False
    from logic.coverage_timeline import (
        CoverageWindow,
        check_coverage_window,
    )

    cycle = patterns[0].cycle_length
    n_days = max(simulation_days, cycle)
    starts = list(shift_starts)
    length = float(shift_length)
    win_objs: List[CoverageWindow] = []
    for w in windows:
        if not isinstance(w, dict) or not w.get("enabled", True):
            continue
        try:
            mn = int(w.get("min_officers") or 0)
        except (TypeError, ValueError):
            mn = 0
        if mn <= 0:
            continue
        from logic.coverage_timeline import normalize_weekdays

        win_objs.append(
            CoverageWindow(
                min_officers=mn,
                start_time=str(w.get("start_time") or "00:00"),
                end_time=str(w.get("end_time") or "23:59"),
                specific_date=None,
                weekday=normalize_weekdays(w.get("weekday", w.get("weekdays", w.get("dow")))),
                label=str(w.get("label") or "Window"),
            )
        )
    if not win_objs:
        return False

    slot_vecs = []
    slot_phase = []
    for i in range(n_slots):
        p = patterns[pat_map[i] % len(patterns)]
        slot_vecs.append(p.duty_vector())
        slot_phase.append(int(phases[i]) % max(cycle, 1))

    # Home+nearby on ON days only (matches simulator default).
    from simulator import assign_pack_starts_for_coverage

    hops = max(0, int(nearby_hops if nearby_hops is not None else 1))
    weekdays: set = set()
    for w in win_objs:
        wset = w.weekday_set()
        if wset is not None:
            weekdays |= wset
    home_for_slot = [starts[i % len(starts)] for i in range(n_slots)]
    # Prior-day overnight tails for morning/post-midnight window minutes
    # (mirrors simulator phase-3 seed: only true overnight end≤start).
    prev_overnight: List[Tuple[date, str, str]] = []

    def _overnight_tails(work_date: date, bands_or_asg) -> List[Tuple[date, str, str]]:
        out: List[Tuple[date, str, str]] = []
        for item in bands_or_asg:
            if len(item) == 3:
                _wd, st, en = item[0], item[1], item[2]
            else:
                st, en = item[0], item[1]
            try:
                sm = _hhmm_to_min(st)
                em = _hhmm_to_min(en)
            except Exception:
                continue
            if em <= sm:
                out.append((work_date, st, en))
        return out

    for day_offset in range(n_days):
        day = sim_start + timedelta(days=day_offset)
        # Always build duty seats so overnight handoff stays continuous even on
        # non-window weekdays (skipping would drop prior tails into window days).
        day_wins = [w for w in win_objs if w.matches_date(day)]
        win_need = max((int(w.min_officers or 0) for w in day_wins), default=0)
        primary = max(day_wins, key=lambda w: int(w.min_officers or 0)) if day_wins else None
        win_start = str(primary.start_time or "19:00") if primary else "19:00"
        win_end = str(primary.end_time or "03:00") if primary else "03:00"
        working_idx = []
        off_idx = []
        for i in range(n_slots):
            vec = slot_vecs[i]
            n = len(vec)
            if n and vec[(day_offset + slot_phase[i]) % n]:
                working_idx.append(i)
            else:
                off_idx.append(i)
        homes = [home_for_slot[i] for i in working_idx]
        bands = assign_pack_starts_for_coverage(
            len(working_idx),
            starts,
            length,
            home_starts=homes,
            min_per_shift=1,
            fri_sat_window=win_need > 0,
            nearby_hops=hops,
            window_min=win_need,
            window_start=win_start,
            window_end=win_end,
        )
        asg = [(day, st, en) for st, en in bands]
        # Off-day call-in only when user opted in (any window day, not Fri/Sat only)
        if allow_offday_coverage and win_need > 0 and day_wins:
            if len(working_idx) < win_need:
                short = win_need - len(working_idx)
                # Prefer starts covering the window arc
                prefer_st = win_start
                for oi in off_idx:
                    if short <= 0:
                        break
                    home = home_for_slot[oi]
                    pick = home if home in starts else starts[0]
                    # Prefer a pack start near the window open
                    best_d, best = 10**9, pick
                    for cand in starts:
                        d = abs(_hhmm_to_min(cand) - _hhmm_to_min(prefer_st))
                        d = min(d, 24 * 60 - d)
                        if d < best_d:
                            best_d, best = d, cand
                    pick = best
                    asg.append((day, pick, _shift_end_hhmm(pick, length)))
                    short -= 1
        # Day-0 steady-state seed (same as simulator): treat today's overnight
        # bands as if they also ran yesterday so 00:00–morning is covered.
        prior = list(prev_overnight)
        if day_offset == 0 and not prior:
            for _wd, st, en in _overnight_tails(day, asg):
                prior.append((day - timedelta(days=1), st, en))
        asg_with_prior = prior + asg
        if day_wins:
            for wo in day_wins:
                chk = check_coverage_window(asg_with_prior, wo, day, step_minutes=30)
                if not chk.get("skipped") and not chk.get("ok", True):
                    return True
        # Advance overnight handoff for the next calendar morning
        prev_overnight = _overnight_tails(day, asg)
    return False


def _window_body_floor(windows: Optional[List[Dict]], *, use_windows: bool) -> int:
    """Max min_officers across enabled windows (moment floor; not serial-band total)."""
    if not use_windows or not windows:
        return 0
    need = 0
    for w in windows:
        if not isinstance(w, dict) or not w.get("enabled", True):
            continue
        try:
            need = max(need, int(w.get("min_officers") or 0))
        except (TypeError, ValueError):
            continue
    return max(0, need)


def _hhmm_to_min(label: str) -> int:
    try:
        parts = (label or "00:00").strip().split(":")
        return int(parts[0]) % 24 * 60 + (int(parts[1]) if len(parts) > 1 else 0)
    except (TypeError, ValueError, IndexError):
        return 0


def _shift_covers_minute(start_min: int, length_min: int, minute_of_day: int) -> bool:
    """Whether a shift starting at start_min for length_min covers minute_of_day (0..1439)."""
    if length_min <= 0:
        return False
    end = start_min + length_min
    if end <= 24 * 60:
        return start_min <= minute_of_day < end
    # Overnight
    return minute_of_day >= start_min or minute_of_day < (end % (24 * 60))


def pack_window_band_capacity(
    starts: Sequence[str],
    shift_length_hours: float,
    win_start: str,
    win_end: str,
    *,
    step_minutes: int = 30,
) -> int:
    """
    C3 — count of start *bands* that cover the thinnest sample in the window.

    Not a headcount ceiling (many officers may share one start). Use
    pack_meets_window_bands for impossible-pack pruning (needs ≥1 covering band).
    """
    if not starts:
        return 0
    length_min = max(30, int(round(float(shift_length_hours) * 60)))
    start_mins = [_hhmm_to_min(s) for s in starts]
    ws = _hhmm_to_min(win_start)
    we = _hhmm_to_min(win_end)
    samples: List[int] = []
    if we > ws:
        t = ws
        while t < we:
            samples.append(t)
            t += max(15, int(step_minutes))
    else:
        t = ws
        while t < 24 * 60:
            samples.append(t)
            t += max(15, int(step_minutes))
        t = 0
        while t < we:
            samples.append(t)
            t += max(15, int(step_minutes))
    if not samples:
        return 0
    mins: List[int] = []
    for m in samples:
        cover = sum(1 for sm in start_mins if _shift_covers_minute(sm, length_min, m))
        mins.append(cover)
    return min(mins) if mins else 0


def pack_meets_window_bands(
    starts: Sequence[str],
    shift_length_hours: float,
    windows: Optional[List[Dict]],
    *,
    num_officers: Optional[int] = None,
) -> bool:
    """
    True if start pack can *possibly* cover windows.

    Only rejects when some window sample has **zero** covering bands
    (no amount of stacking on starts can help), or need > num_officers.
    """
    if not windows:
        return True

    def _win_need(w: Dict) -> int:
        try:
            return int(w.get("min_officers") or 0)
        except (TypeError, ValueError):
            return 0

    win_key = tuple(
        (
            str(w.get("start_time") or w.get("start") or ""),
            str(w.get("end_time") or w.get("end") or ""),
            _win_need(w),
            bool(w.get("enabled", True)),
        )
        for w in windows
        if isinstance(w, dict)
    )
    ckey = (
        tuple(str(s) for s in starts),
        float(shift_length_hours),
        win_key,
        int(num_officers) if num_officers is not None else None,
    )
    hit = _PACK_WINDOW_BANDS_CACHE.get(ckey)
    if hit is not None:
        return bool(hit)
    ok = True
    for w in windows:
        if not isinstance(w, dict) or not w.get("enabled", True):
            continue
        try:
            need = int(w.get("min_officers") or 0)
        except (TypeError, ValueError):
            need = 0
        if need <= 0:
            continue
        if num_officers is not None and need > int(num_officers):
            ok = False
            break
        st = str(w.get("start_time") or w.get("start") or "00:00")
        en = str(w.get("end_time") or w.get("end") or "23:59")
        # Any covering band at the thinnest sample?
        if pack_window_band_capacity(starts, shift_length_hours, st, en) < 1:
            ok = False
            break
    return bool(_cache_put(_PACK_WINDOW_BANDS_CACHE, ckey, ok))


def _cheap_reject(
    patterns,
    phases: List[int],
    pat_map: List[int],
    *,
    n_slots: int,
    shift_length: float,
    annual_target: float,
    annual_variance: float,
    annual_hard: bool,
    simulation_days: int,
    cov247: int,
    use_windows: bool,
    window_min: int = 0,
    n_bands: int = 1,
    min_ps: int,
    sim_start: date,
    shift_starts: Optional[Sequence[str]] = None,
    extra_windows: Optional[List[Dict]] = None,
    precomputed: Optional[Tuple[List[int], List[int]]] = None,
    nearby_hops: int = 1,
    allow_offday_coverage: bool = False,
    avoid_flsa: bool = False,
    flsa_period_days: int = 28,
    flsa_threshold: float = 171.0,
    max_consecutive_work_days: int = 0,
    min_rest_hours: float = 0.0,
    night_minimum: int = 0,
    rotation_type: str = "",
    skip_window_minute: bool = False,
) -> Optional[str]:
    """Prune layouts that cannot possibly meet hard floors (bodies / pattern annual mean).

    skip_window_minute: when True, skip C3 minute-bin (heavy). Caller may defer
    minute checks to top-ranked candidates only — full sim remains truth.
    """
    del n_bands  # pack size is not a daily body-floor multiplier
    # Squad path: synthesize duty rings when multi-block patterns absent
    if not patterns and rotation_type:
        patterns = duty_patterns_from_rotation(rotation_type)
        if patterns and phases is not None and pat_map is not None:
            if len(phases) < n_slots:
                phases = list(phases) + [0] * (n_slots - len(phases))
            if len(pat_map) < n_slots:
                # Round-robin squads
                n_pat = len(patterns)
                pat_map = [i % n_pat for i in range(n_slots)]
    if patterns:
        if annual_hard:
            # Pattern math is cycle-based year-average — phase does not change hours.
            # Match simulator: mean outside band OR unfair spread (max−min > 2×variance).
            hours = [
                _projected_annual_cached(patterns[pat_map[i] % len(patterns)], shift_length) for i in range(n_slots)
            ]
            avg = sum(hours) / max(len(hours), 1)
            # B4 fix: only apply the 2% floor when variance is truly unset (<=0).
            # Never silently override a user-set tight variance (e.g. ±20h).
            if float(annual_variance or 0) > 0:
                band = float(annual_variance)
            else:
                band = abs(float(annual_target)) * 0.02
            if abs(avg - float(annual_target)) > band + 1e-6:
                return "annual"
            if hours and (max(hours) - min(hours)) > max(band * 2.0, 40.0) + 1e-6:
                return "annual"
        # Max consecutive ON days — pattern-intrinsic (phase cannot shorten longest ON run)
        max_c = int(max_consecutive_work_days or 0)
        if max_c > 0:
            for i in range(n_slots):
                p = patterns[int(pat_map[i]) % len(patterns)]
                vec = _duty_vec_cached(p)
                if not vec:
                    continue
                ph = int(phases[i]) % max(len(vec), 1)
                if _max_on_streak(vec, ph) > max_c:
                    return "consecutive"
        # Min rest: consecutive ON + pack cannot achieve rest (start-pair best case)
        if float(min_rest_hours or 0) > 0 and _cheap_rest_fail(
            patterns,
            phases,
            pat_map,
            n_slots=n_slots,
            shift_length=shift_length,
            shift_starts=shift_starts,
            min_rest_hours=float(min_rest_hours),
            nearby_hops=nearby_hops,
        ):
            return "rest"
        # FLSA fixed-anchor prune (optional hard)
        if avoid_flsa and _cheap_flsa_fail(
            patterns,
            phases,
            pat_map,
            n_slots=n_slots,
            shift_length=shift_length,
            simulation_days=simulation_days,
            period_days=int(flsa_period_days or 28),
            threshold=float(flsa_threshold or 171.0),
        ):
            return "flsa"
        win_wds = _window_weekdays_from_extra(extra_windows if use_windows else None)
        if precomputed is not None:
            day_counts, window_day_counts = precomputed
        else:
            day_counts, window_day_counts = _day_body_counts(
                patterns,
                phases,
                pat_map,
                n_slots=n_slots,
                simulation_days=simulation_days,
                sim_start=sim_start,
                window_weekdays=win_wds,
            )
        # 24/7 needs concurrent person-hours, not just min officers at one moment
        if cov247 > 0 and day_counts:
            need247 = bodies_needed_247(shift_length, cov247)
            if min(day_counts) < need247:
                return "coverage_247"
        # Night minimum (Fri/Sat high-risk): only when overnight cover is forced
        # (24/7 or night window). Soft metric alone does not hard-fail empty night bands.
        nmin = max(0, int(night_minimum or 0))
        if (
            nmin > 0
            and pack_has_night_start(shift_starts)
            and overnight_coverage_forced(
                coverage_247=cov247,
                extra_windows=extra_windows if use_windows else None,
                shift_length_hours=shift_length,
            )
        ):
            # Fri/Sat body floor for high-risk nights (config.is_high_risk_night)
            _, fri_sat_bodies = _day_body_counts(
                patterns,
                phases,
                pat_map,
                n_slots=n_slots,
                simulation_days=simulation_days,
                sim_start=sim_start,
                window_weekdays=(4, 5),
            )
            if fri_sat_bodies and min(fri_sat_bodies) < min(nmin, n_slots):
                return "night"
        # Body floor for windows = max min_officers from windows (not n_bands heuristic).
        # When off-day coverage is OFF, body floor is hard: OFF officers do not work.
        if use_windows and window_day_counts and window_min > 0:
            if min(window_day_counts) < min(window_min, n_slots):
                return "window"
        # C3 — pack shape: zero covering bands
        if use_windows and shift_starts and extra_windows:
            if not pack_meets_window_bands(shift_starts, shift_length, extra_windows):
                return "window"
        # C3 minute-bin occupancy with home+nearby ON-day starts (heavier; only if body OK)
        if (
            not skip_window_minute
            and use_windows
            and shift_starts
            and extra_windows
            and phases is not None
            and pat_map is not None
        ):
            if _cheap_window_minute_fail(
                patterns,
                phases,
                pat_map,
                n_slots=n_slots,
                shift_starts=shift_starts,
                shift_length=shift_length,
                simulation_days=simulation_days,
                sim_start=sim_start,
                windows=list(extra_windows),
                nearby_hops=nearby_hops,
                allow_offday_coverage=allow_offday_coverage,
            ):
                return "window"
        # Body floor only: thin multi-block days may run fewer shifts than pack
        # size. Equal-spaced full-pack staffing is not a hard daily requirement.
        # Concurrent floors (24/7 / windows) handle coverage; min_ps is per
        # *used* start (enforced in full sim), not every pack band every day.
        if min_ps > 0 and day_counts:
            floor = min(int(min_ps), int(n_slots))
            if min(day_counts) < floor:
                return "gaps"
    return None


def _weights_from_priority(
    priority: Optional[List[str]] = None,
    weights: Optional[Dict[str, float]] = None,
) -> Dict[str, float]:
    w = dict(DEFAULT_CONSTRAINT_WEIGHTS)
    if weights:
        for k, v in weights.items():
            if k in w:
                try:
                    w[k] = float(v)
                except (TypeError, ValueError):
                    pass
    if priority:
        # Earlier in list = higher priority → assign descending weights
        base = 100.0
        for i, key in enumerate(priority):
            if key in w and key != "headcount":
                w[key] = base - i * 12.0
    return w


def _violation_vector(m: Dict, *, annual: float, annual_variance: float) -> Dict[str, float]:
    """Non-negative violation magnitudes for near-miss scoring.

    B6 fix: split annual_band_outside and annual distance into separate terms
    with calibrated coefficients so a plan with 1 officer slightly out of band
    does not outscore a plan with genuine coverage gaps.
    """
    gaps = float(m.get("gap_events") or m.get("zero_staff_slots") or m.get("coverage_gap_count") or 0)
    # annual_band_outside: number of officers outside band (x15 per officer)
    # annual distance: how far mean is from target (normalized, x12 max per unit)
    annual_outside_count = float(m.get("annual_band_outside") or 0)
    annual_mean_dist = (
        abs(float(m.get("avg_annual_hours") or annual) - annual) * 12.0 / max(float(annual_variance) or 40.0, 1.0)
    )
    return {
        "coverage_247": float(m.get("coverage_247_failures") or 0),
        "windows": float(m.get("extra_window_failures") or 0),
        "gaps": gaps,
        "flsa": float(m.get("flsa_violations") or 0),
        "annual": annual_outside_count * 15.0 + annual_mean_dist,
        "annual_spread": float(m.get("annual_hours_spread") or 0),
    }


def _score_metrics(
    m: Dict,
    *,
    annual: float,
    annual_variance: float = 40.0,
    n_off: int,
    hard_ok: bool,
    weights: Dict[str, float],
    pattern_slot_map: Optional[List[int]] = None,
    multi_block: bool = False,
) -> float:
    var = float(annual_variance if annual_variance is not None else (m.get("annual_hours_variance") or 40))
    v = _violation_vector(m, annual=annual, annual_variance=var)
    penalty = 0.0
    for key in ("coverage_247", "windows", "gaps", "flsa", "annual"):
        penalty += v.get(key, 0) * float(weights.get(key, 1.0))
    # Peer spread (officers not identical — penalize large unfairness only)
    penalty += float(v.get("annual_spread") or 0) * float(weights.get("annual", 40.0)) * 0.05
    # Clamp n_off to >=1 so a degenerate 0-officer config never escapes the headcount penalty
    penalty += max(1, n_off) * float(weights.get("headcount", 10.0)) * 0.05
    # Multi-block: prefer mixed pattern maps over all-officers-same-pattern
    if multi_block and pattern_slot_map and len(pattern_slot_map) > 1:
        uniq = len({int(x) for x in pattern_slot_map})
        if uniq < 2:
            penalty += 25.0
        else:
            # Mild bonus for balanced split (closer to 50/50)
            zeros = sum(1 for x in pattern_slot_map if int(x) % 2 == 0)
            bal = abs(zeros / len(pattern_slot_map) - 0.5)
            penalty += bal * 15.0
    # Correct metric key names from simulator:
    # "rest_failures" and "consecutive_work_failures" (not the old mismatched names)
    rest_hits = float(m.get("rest_failures") or m.get("rest_gap_violations") or m.get("min_rest_failures") or 0)
    consec = float(
        m.get("consecutive_work_failures")
        or m.get("consecutive_work_violations")
        or m.get("max_consecutive_failures")
        or 0
    )
    penalty += rest_hits * 8.0 + consec * 6.0
    return 100_000 - penalty - (0 if hard_ok else 5_000)


def _constraint_fail(
    m: Dict,
    *,
    require_hard_ok: bool,
    avoid_flsa_overtime: bool,
    cov247: int,
    use_extra_windows: bool,
    windows: list,
    annual_hours_hard: bool,
    min_ps: int,
    min_rest_hours: float = 0.0,
    max_consecutive_work_days: int = 0,
) -> bool:
    """Return True if this sim result fails any active hard constraint.

    B9 fix: always respect hard_constraints_ok from the simulator — even when
    min_ps=0, a plan with genuine coverage gaps has hard_ok=False already set
    by the simulator and should be rejected here.

    B1 fix: rest_failures and consecutive_work_failures now checked when the
    corresponding user constraints are active.
    """
    if not require_hard_ok:
        return False
    # B9: always gate on the simulator's own hard_constraints_ok flag
    if not bool(m.get("hard_constraints_ok", True)):
        return True
    if avoid_flsa_overtime and int(m.get("flsa_violations") or 0):
        return True
    if cov247 > 0 and int(m.get("coverage_247_failures") or 0):
        return True
    if use_extra_windows and windows and int(m.get("extra_window_failures") or 0):
        return True
    if annual_hours_hard:
        if int(m.get("annual_mean_outside") or 0) > 0:
            return True
        if int(m.get("annual_unfair") or 0) > 0:
            return True
    # Only check min_ps gaps independently when min_ps > 0 (redundant with hard_ok above
    # but kept for clarity when hard_ok key is absent from older sim results)
    gaps = m.get("gap_events")
    if gaps is None:
        gaps = m.get("zero_staff_slots") or m.get("coverage_gap_count") or 0
    if int(min_ps) > 0 and int(gaps or 0) > 0:
        return True
    # B1: rest and consecutive-day hard gates
    if min_rest_hours > 0 and int(m.get("rest_failures") or 0) > 0:
        return True
    if max_consecutive_work_days > 0 and int(m.get("consecutive_work_failures") or 0) > 0:
        return True
    return False


def _resolve_axes(
    *,
    rotation_types,
    officer_counts,
    min_per_shift_options,
    shift_length_hours,
    shift_length_options,
    shift_starts,
    shift_starts_options,
    free_officer_counts,
    free_starts,
    free_lengths,
    free_variations,
    rotation_variations,
    rotation_style,
    annual_hours_target=None,
    annual_hours_variance=40.0,
):
    from logic.rotation_config import get_rotation_config
    from logic.staffing_config import get_staffing_config

    staffing = get_staffing_config()
    rot = get_rotation_config()
    if rotation_types is None:
        from config import SIMULATOR_ROTATION_TYPES

        rotation_types = list(SIMULATOR_ROTATION_TYPES)
        active = rot.get("preset_name") or rot.get("active_preset")
        if active and active not in rotation_types:
            rotation_types.insert(0, active)

    base_officers = int(staffing.get("active_officer_count") or staffing.get("target_officer_count") or 16)
    if officer_counts is None:
        if free_officer_counts:
            officer_counts = generate_officer_counts(free=True, base=base_officers, lo=4, hi=20)
        else:
            officer_counts = sorted(
                {
                    max(4, base_officers - 4),
                    base_officers,
                    base_officers + 2,
                    base_officers + 4,
                    staffing.get("target_officer_count") or base_officers,
                }
            )
    else:
        officer_counts = sorted({max(1, int(n)) for n in officer_counts})

    if min_per_shift_options is None:
        min_per_shift_options = [1, 2]
    else:
        min_per_shift_options = [max(1, int(x)) for x in min_per_shift_options]

    if shift_length_options:
        length_opts = [float(x) for x in shift_length_options]
    elif free_lengths:
        length_opts = generate_length_options()
    elif shift_length_hours is not None:
        length_opts = [float(shift_length_hours)]
    else:
        length_opts = [float(staffing["shift_length_hours"])]

    locked_starts_opts: Optional[List[List[str]]] = None
    if shift_starts_options:
        locked_starts_opts = [list(s) for s in shift_starts_options if s]
    elif shift_starts:
        locked_starts_opts = [list(shift_starts)]
    elif not free_starts:
        default_starts = [b["start"] for b in staffing.get("shift_times") or []]
        if not default_starts:
            default_starts = [config.SHIFT_TIMES[k][0] for k in sorted(config.SHIFT_TIMES)]
        locked_starts_opts = [default_starts]

    from logic.rotation_patterns import expand_variation_family, generate_multi_block_variation_sets

    base_variations = [v for v in (rotation_variations or []) if (v or "").strip()]
    style = (rotation_style or "").strip().lower()
    # Resolve annual/length for free multi-block math (not a baked 6-2,5-3 catalog)
    try:
        _ann = (
            float(annual_hours_target)
            if annual_hours_target is not None
            else float(staffing.get("annual_hours_target") or 0)
        )
    except (TypeError, ValueError):
        _ann = float(staffing.get("annual_hours_target") or 0)
    try:
        _len0 = float(length_opts[0]) if length_opts else float(staffing.get("shift_length_hours") or 8)
    except (TypeError, ValueError, IndexError):
        _len0 = 8.0
    try:
        _avar = float(annual_hours_variance) if annual_hours_variance is not None else 40.0
    except (TypeError, ValueError):
        _avar = 40.0

    if base_variations:
        # Locked seeds: when free_variations is also exploring style/mix, expand the
        # same-cycle family (block order + complementary OFF swaps) so officers can
        # mix — not a single hardcoded pair as "the" rotation.
        # Pure locked (free_variations off): use exactly the user's set.
        if free_variations:
            family = expand_variation_family(base_variations, style=style or None)
            variation_sets: List[List[str]] = [list(base_variations)]
            if family and set(family) != set(base_variations):
                variation_sets.append(family)
            if len(family) >= 2:
                for a, b in itertools.combinations(family[:6], 2):
                    variation_sets.append([a, b])
            # Dedupe sets
            dedup = []
            seen_s = set()
            for vs in variation_sets:
                key = tuple(vs)
                if key not in seen_s:
                    seen_s.add(key)
                    dedup.append(vs)
            variation_sets = dedup
        else:
            variation_sets = [list(base_variations)]
    elif free_variations:
        # Free: generate families from annual ÷ (365.25 × length) work fraction
        variation_sets = generate_multi_block_variation_sets(
            shift_length_hours=_len0,
            annual_hours_target=_ann if _ann > 0 else float(staffing.get("annual_hours_target") or 2080.0),
            annual_variance=_avar,
            max_sets=20,
        )
        if not variation_sets:
            variation_sets = [[]]
    else:
        variation_sets = [[]]
    if base_variations and style not in ("fixed", "rotating"):
        style = "rotating" if any("," in v for v in base_variations) else "fixed"
    elif free_variations and style not in ("fixed", "rotating"):
        style = "rotating"

    free_dims = []
    if free_officer_counts or (officer_counts is not None and len(officer_counts) > 1):
        free_dims.append("officer_count")
    if free_lengths or len(length_opts) > 1:
        free_dims.append("shift_length")
    if free_starts or (locked_starts_opts is None):
        free_dims.append("shift_starts")
    if len(min_per_shift_options) > 1:
        free_dims.append("min_per_shift")
    if len(rotation_types) > 1:
        free_dims.append("rotation")
    if free_variations or len(variation_sets) > 1:
        free_dims.append("rotation_variations")
    if base_variations or free_variations:
        free_dims.append("phase_and_pattern_assignment")

    return {
        "rotation_types": list(rotation_types),
        "officer_counts": list(officer_counts),
        "min_per_shift_options": list(min_per_shift_options),
        "length_opts": length_opts,
        "locked_starts_opts": locked_starts_opts,
        "free_starts": free_starts or locked_starts_opts is None,
        "variation_sets": variation_sets,
        "style": style,
        "base_variations": base_variations,
        "free_dims": free_dims,
        "staffing": staffing,
    }


# Prefer complete scan when post-bind layouts under this; else anytime.
# Measured: free multi-block free-starts often 50k+ (anytime); locked packs << 1k.
# 2500 keeps small locked domains exhaustive without forcing mid-size free to thrash.
EXHAUSTIVE_LAYOUT_THRESHOLD = 2_500
# Hard-OK often lands <15s on free starts; 90s was thrash on impossible. 60s still roomy.
ANYTIME_WALL_SEC_DEFAULT = 60.0
# Exhaustive soft wall: if ≥1 hard-OK and wall hit, stop + mark truncated (honest).
EXHAUSTIVE_SOFT_WALL_SEC = 25.0
# After first hard-OK in anytime mode, allow this many more seconds for ranked diversity.
ANYTIME_AFTER_HARD_SEC = 12.0

# search_depth: wall/pack budgets only (free lengths always full half-hour grid).
_DEPTH_BUDGETS = {
    "standard": {
        "anytime_wall": 45.0,
        "after_hard": 8.0,
        "exhaustive_soft": 18.0,
        "max_cheap_pass": 32,
        "max_full_per_struct": 16,
        "max_hard_results": 16,
    },
    "deep": {
        "anytime_wall": 90.0,
        "after_hard": 20.0,
        "exhaustive_soft": 40.0,
        "max_cheap_pass": 64,
        "max_full_per_struct": 32,
        "max_hard_results": 32,
    },
}


def _depth_key(search_depth: str) -> str:
    d = (search_depth or "standard").strip().lower()
    if d in ("deep", "thorough", "full"):
        return "deep"
    return "standard"


def domain_reduction_report(axes: Dict[str, Any]) -> Dict[str, Any]:
    """Post-bind domain sizes for estimate/UI (no baked scenario text)."""
    return {
        "free_dimensions": list(axes.get("free_dims") or []),
        "raw_counts": dict(axes.get("raw_counts") or {}),
        "bound_counts": dict(axes.get("bound_counts") or {}),
        "bind_reasons": list(axes.get("bind_reasons") or []),
        "officer_counts": list(axes.get("officer_counts") or []),
        "length_opts": list(axes.get("length_opts") or []),
        "variation_sets": len(axes.get("variation_sets") or []),
        "rotation_types": list(axes.get("rotation_types") or []),
        "min_per_shift_options": list(axes.get("min_per_shift_options") or []),
        "min_bands_hint": axes.get("min_bands_hint"),
        "filter_start_packs": bool(axes.get("filter_start_packs")),
    }


def bind_domains(
    axes: Dict[str, Any],
    *,
    coverage_247: int = 0,
    use_extra_windows: bool = False,
    extra_windows: Optional[List[Dict]] = None,
    annual_hours_target: Optional[float] = None,
    annual_hours_variance: float = 40.0,
    annual_hours_hard: bool = False,
    max_consecutive_work_days: int = 0,
    min_rest_hours: float = 0.0,
    avoid_flsa: bool = False,
    flsa_work_period_days: int = 28,
) -> Dict[str, Any]:
    """
    Co-reduce free axes from constraints *together* (CSP domain reduction).

    Sparse Given (e.g. only officer count) leaves other axes wide.
    Each hard/Given constraint further intersects domains — does not invent
    24/7/windows/annual filters when those constraints are off.
    """
    import copy
    import math

    from logic.optimizer_features import early_impossible_proof
    from logic.rotation_patterns import build_pattern, projected_annual_hours

    out = copy.copy(axes)
    reasons: List[str] = []
    cov = max(0, int(coverage_247 or 0))
    wins = list(extra_windows or []) if use_extra_windows else []
    win_min = _window_body_floor(wins, use_windows=bool(use_extra_windows and wins))
    max_c = max(0, int(max_consecutive_work_days or 0))
    min_rest = float(min_rest_hours or 0)
    style = (out.get("style") or "rotating").strip().lower()
    try:
        annual = (
            float(annual_hours_target)
            if annual_hours_target is not None
            else float((out.get("staffing") or {}).get("annual_hours_target") or 2080)
        )
    except (TypeError, ValueError):
        annual = 2080.0
    try:
        avar = float(annual_hours_variance) if annual_hours_variance is not None else 40.0
    except (TypeError, ValueError):
        avar = 40.0

    raw = {
        "officer_counts": len(out.get("officer_counts") or []),
        "length_opts": len(out.get("length_opts") or []),
        "variation_sets": len(out.get("variation_sets") or []),
        "rotation_types": len(out.get("rotation_types") or []),
        "min_per_shift_options": len(out.get("min_per_shift_options") or []),
    }

    length_opts = [float(x) for x in (out.get("length_opts") or [8.0])]
    variation_sets: List[List[str]] = [list(vs) for vs in (out.get("variation_sets") or [[]])]
    base_vars = [v for v in (out.get("base_variations") or []) if (v or "").strip()]

    has_multi = any(bool(vs) and any("," in str(x) for x in (vs or [])) for vs in variation_sets) or any(
        "," in str(x) for x in base_vars
    )

    # Fixed style: multi-segment multi-block invalid — keep single-block only
    if style == "fixed":
        kept_fixed = []
        for vs in variation_sets:
            if not vs:
                kept_fixed.append(vs)
                continue
            if all("," not in str(t) for t in vs):
                kept_fixed.append(vs)
        if kept_fixed != variation_sets:
            reasons.append(f"fixed style: variation sets {len(variation_sets)}→{len(kept_fixed)}")
            variation_sets = kept_fixed or [[]]
            out["variation_sets"] = variation_sets
            has_multi = any(bool(vs) and any("," in str(x) for x in (vs or [])) for vs in variation_sets)

    # Multi-block duty → collapse squad catalog
    if has_multi and len(out.get("rotation_types") or []) > 1:
        n_rt = len(out["rotation_types"])
        out["rotation_types"] = [out["rotation_types"][0]]
        reasons.append(f"multi-block: rotation types {n_rt}→1")

    def _set_hits_annual(vs: List[str], length: float) -> bool:
        if not annual_hours_hard:
            return True
        if not vs:
            return True
        try:
            pats = [
                build_pattern(t, style=style if style in ("fixed", "rotating") else None)
                for t in vs
                if (t or "").strip()
            ]
        except ValueError:
            return False
        if not pats:
            return True
        hours = [projected_annual_hours(p, length) for p in pats]
        lo, hi = min(hours), max(hours)
        band = avar if avar > 0 else abs(annual) * 0.02
        return (lo - band) <= annual <= (hi + band)

    # Annual hard × length × patterns only when annual hard + patterns exist
    if annual_hours_hard and (any(vs for vs in variation_sets) or base_vars):
        proof_sets = [vs for vs in variation_sets if vs] or ([base_vars] if base_vars else [])

        kept_sets = []
        for vs in variation_sets:
            if not vs:
                kept_sets.append(vs)
                continue
            if any(_set_hits_annual(vs, L) for L in length_opts):
                kept_sets.append(vs)
        if kept_sets and len(kept_sets) < len(variation_sets):
            reasons.append(f"annual×pattern: variation sets {len(variation_sets)}→{len(kept_sets)}")
            variation_sets = kept_sets
        out["variation_sets"] = variation_sets

        kept_L = []
        for L in length_opts:
            sets_for_L = [vs for vs in variation_sets if vs] or proof_sets
            if not sets_for_L:
                kept_L.append(L)
                continue
            if any(_set_hits_annual(vs, L) for vs in sets_for_L):
                kept_L.append(L)
        if kept_L and len(kept_L) < len(length_opts):
            reasons.append(f"annual×length: lengths {len(length_opts)}→{len(kept_L)}")
            length_opts = kept_L
        elif not kept_L and length_opts:
            reasons.append("annual×length: no length hits band (kept for soft/near-miss)")
        out["length_opts"] = length_opts

    # 24/7 × length: band count must fit under max N
    n_list = [int(n) for n in (out.get("officer_counts") or [])]
    max_n = max(n_list) if n_list else 0
    if cov > 0 and length_opts and max_n > 0:
        kept_L = []
        for L in length_opts:
            bands = int(math.ceil(24.0 / float(L))) if L > 0 else 99
            if bands <= max_n:
                kept_L.append(L)
        if kept_L and len(kept_L) < len(length_opts):
            reasons.append(f"24/7×length: lengths {len(length_opts)}→{len(kept_L)}")
            length_opts = kept_L
            out["length_opts"] = length_opts

    # Officer counts: only cut when other floors active (sparse N alone stays wide)
    if n_list and (cov > 0 or win_min > 0 or (annual_hours_hard and (has_multi or base_vars))):
        kept_n = []
        for n in n_list:
            ok_any = False
            for L in length_opts or [8.0]:
                proof_vars = list(base_vars)
                if not proof_vars:
                    for vs in variation_sets:
                        if vs:
                            proof_vars = list(vs)
                            break
                _rot0 = ""
                rts = out.get("rotation_types") or []
                if rts:
                    _rot0 = str(rts[0])
                reason = early_impossible_proof(
                    num_officers=int(n),
                    shift_length_hours=float(L),
                    annual_hours_target=float(annual),
                    annual_hours_variance=float(avar),
                    annual_hours_hard=bool(annual_hours_hard and (bool(proof_vars) or bool(_rot0))),
                    rotation_variations=proof_vars or None,
                    coverage_247=cov,
                    window_min=win_min,
                    rotation_style=style or "rotating",
                    max_consecutive_work_days=max_c,
                    min_rest_hours=min_rest,
                    avoid_flsa=bool(avoid_flsa),
                    flsa_work_period_days=int(flsa_work_period_days or 28),
                    rotation_type=_rot0,
                )
                if reason is None:
                    ok_any = True
                    break
            if ok_any:
                kept_n.append(n)
            else:
                reasons.append(f"N={n}: impossible under co-bound constraints")
        if kept_n:
            if len(kept_n) < len(n_list):
                reasons.append(f"officer counts {len(n_list)}→{len(kept_n)}")
            out["officer_counts"] = kept_n
            n_list = kept_n

    # FLSA × length: drop lengths where every offered multi-block always fails §207(k)
    if avoid_flsa and length_opts and (base_vars or any(variation_sets)):
        try:
            from logic.labor_compliance import flsa_threshold_for_period_days

            period = max(7, min(int(flsa_work_period_days or 28), 28))
            thr = float(flsa_threshold_for_period_days(period))
            proof_texts: List[str] = list(base_vars)
            if not proof_texts:
                for vs in variation_sets:
                    proof_texts.extend(list(vs or []))
            pats = []
            for t in proof_texts:
                try:
                    pats.append(
                        build_pattern(
                            t,
                            style=style if style in ("fixed", "rotating") else None,
                        )
                    )
                except ValueError:
                    continue
            if pats:
                kept_L_flsa = []
                for L in length_opts:
                    if all(
                        pattern_flsa_always_fails(
                            p.duty_vector(),
                            float(L),
                            period_days=period,
                            threshold=thr,
                        )
                        for p in pats
                    ):
                        continue
                    kept_L_flsa.append(L)
                if kept_L_flsa and len(kept_L_flsa) < len(length_opts):
                    reasons.append(f"FLSA×length: lengths {len(length_opts)}→{len(kept_L_flsa)}")
                    length_opts = kept_L_flsa
                    out["length_opts"] = length_opts
                elif not kept_L_flsa:
                    reasons.append(f"FLSA: all lengths always exceed {thr:g}h/{period}d for offered patterns")
        except Exception:
            pass

    # Max consecutive: drop variation sets where every pattern exceeds cap
    if max_c > 0 and variation_sets:
        kept_vs: List[List[str]] = []
        for vs in variation_sets:
            if not vs:
                kept_vs.append(vs)
                continue
            ok_pat = False
            for t in vs:
                try:
                    p = build_pattern(
                        t,
                        style=style if style in ("fixed", "rotating") else None,
                    )
                except ValueError:
                    continue
                if _max_on_streak(p.duty_vector(), 0) <= max_c:
                    ok_pat = True
                    break
            if ok_pat:
                kept_vs.append(vs)
            else:
                reasons.append(f"drop variation set (all patterns > max consecutive {max_c}): {vs}")
        if kept_vs and len(kept_vs) < len(variation_sets):
            reasons.append(f"max consecutive: variation sets {len(variation_sets)}→{len(kept_vs)}")
            variation_sets = kept_vs
            out["variation_sets"] = variation_sets
        elif not kept_vs and variation_sets:
            # Leave one set so caller can surface early-impossible near-miss
            reasons.append(f"max consecutive {max_c}: no viable multi-block set")

    # Min rest × locked start packs: drop packs that cannot rest between adjacent ON
    locked_starts = out.get("locked_starts_opts")
    if min_rest > 0 and locked_starts is not None and length_opts:
        has_adj = False
        for vs in variation_sets:
            for t in vs or []:
                try:
                    p = build_pattern(
                        t,
                        style=style if style in ("fixed", "rotating") else None,
                    )
                except ValueError:
                    continue
                if pattern_has_adjacent_on(p.duty_vector(), 0):
                    has_adj = True
                    break
            if has_adj:
                break
        if has_adj:
            kept_packs = []
            for pack in locked_starts:
                ok_L = False
                for L in length_opts:
                    mx = max_rest_minutes_for_pack(
                        list(pack),
                        float(L),
                        day_gap_days=1,
                        nearby_hops=1,
                    )
                    if mx >= min_rest * 60.0 - 1.0:
                        ok_L = True
                        break
                if ok_L:
                    kept_packs.append(list(pack))
            if kept_packs and len(kept_packs) < len(locked_starts):
                reasons.append(f"min rest×packs: locked packs {len(locked_starts)}→{len(kept_packs)}")
                out["locked_starts_opts"] = kept_packs
            elif not kept_packs:
                reasons.append("min rest: no locked pack meets rest with adjacent ON patterns")

    # min_per_shift vs headcount
    mps_opts = [max(1, int(x)) for x in (out.get("min_per_shift_options") or [1])]
    if n_list and len(mps_opts) > 1:
        max_n = max(n_list)
        kept_m = [m for m in mps_opts if m <= max_n]
        if kept_m and len(kept_m) < len(mps_opts):
            reasons.append(f"min_per_shift×N: options {len(mps_opts)}→{len(kept_m)}")
            out["min_per_shift_options"] = kept_m

    # Free-start pack filter when coverage OR rest binds multi-block adjacent ON
    rest_binds_packs = bool(min_rest > 0)
    filter_packs = bool(cov > 0 or (use_extra_windows and wins) or rest_binds_packs)
    out["filter_start_packs"] = filter_packs
    out["bind_min_rest_hours"] = min_rest
    out["bind_max_consecutive"] = max_c
    out["bind_avoid_flsa"] = bool(avoid_flsa)
    out["bind_flsa_period_days"] = int(flsa_work_period_days or 28)

    min_b_hint = 2
    if cov > 0 and length_opts:
        min_b_hint = max(min_b_hint, max(int(math.ceil(24.0 / float(L))) for L in length_opts))
    out["min_bands_hint"] = min_b_hint
    out["bind_windows"] = wins
    out["bind_coverage_247"] = cov
    out["bind_annual_hard"] = bool(annual_hours_hard)
    out["bind_reasons"] = reasons
    out["raw_counts"] = raw
    out["bound_counts"] = {
        "officer_counts": len(out.get("officer_counts") or []),
        "length_opts": len(out.get("length_opts") or []),
        "variation_sets": len(out.get("variation_sets") or []),
        "rotation_types": len(out.get("rotation_types") or []),
        "min_per_shift_options": len(out.get("min_per_shift_options") or []),
    }
    free_dims = list(out.get("free_dims") or [])
    if len(out.get("officer_counts") or []) <= 1 and "officer_count" in free_dims:
        free_dims = [d for d in free_dims if d != "officer_count"]
    if len(out.get("length_opts") or []) <= 1 and "shift_length" in free_dims:
        free_dims = [d for d in free_dims if d != "shift_length"]
    if len(out.get("rotation_types") or []) <= 1 and "rotation" in free_dims:
        free_dims = [d for d in free_dims if d != "rotation"]
    if len(out.get("variation_sets") or []) <= 1 and "rotation_variations" in free_dims:
        free_dims = [d for d in free_dims if d != "rotation_variations"]
    if len(out.get("min_per_shift_options") or []) <= 1 and "min_per_shift" in free_dims:
        free_dims = [d for d in free_dims if d != "min_per_shift"]
    if out.get("locked_starts_opts") is not None and "shift_starts" in free_dims:
        free_dims = [d for d in free_dims if d != "shift_starts"]
    out["free_dims"] = free_dims
    return out


def neighbor_start_packs(starts: Sequence[str], *, max_neighbors: int = 12) -> List[List[str]]:
    """±30 minute nudge on one band (after first hard-OK)."""
    base = [_snap_to_half_hour(s) for s in starts if s]
    if len(base) < 2:
        return []
    out: List[List[str]] = []
    seen = {tuple(sorted(base))}
    for i, s in enumerate(base):
        try:
            parts = s.split(":")
            total = int(parts[0]) * 60 + int(parts[1] if len(parts) > 1 else 0)
        except (ValueError, IndexError):
            continue
        for delta in (-30, 30):
            nt = (total + delta) % (24 * 60)
            cand = list(base)
            cand[i] = _format_hhmm(nt // 60, nt % 60)
            uniq: List[str] = []
            for x in cand:
                if x not in uniq:
                    uniq.append(x)
            if len(uniq) < 2:
                continue
            key = tuple(sorted(uniq))
            if key in seen:
                continue
            seen.add(key)
            out.append(uniq)
            if len(out) >= max_neighbors:
                return out
    return out


def try_cpsat_phase_seed(
    *,
    n_officers: int,
    cycle_length: int,
    n_patterns: int = 1,
    duty_rings: Optional[List[List[bool]]] = None,
    pattern_map: Optional[List[int]] = None,
    min_daily_on: int = 0,
    window_weekday_floors: Optional[List[Tuple[int, int]]] = None,
    sim_start_weekday: int = 0,
    free_pattern_map: bool = True,
) -> Optional[List[int]]:
    """Optional CP-SAT joint phase seed (phases only). Full sim remains truth."""
    joint = try_cpsat_joint_seed(
        n_officers=n_officers,
        cycle_length=cycle_length,
        n_patterns=n_patterns,
        duty_rings=duty_rings,
        pattern_map=pattern_map,
        min_daily_on=min_daily_on,
        window_weekday_floors=window_weekday_floors,
        sim_start_weekday=sim_start_weekday,
        free_pattern_map=free_pattern_map,
    )
    return joint[0] if joint else None


def try_cpsat_joint_seed(
    *,
    n_officers: int,
    cycle_length: int,
    n_patterns: int = 1,
    duty_rings: Optional[List[List[bool]]] = None,
    pattern_map: Optional[List[int]] = None,
    min_daily_on: int = 0,
    window_weekday_floors: Optional[List[Tuple[int, int]]] = None,
    sim_start_weekday: int = 0,
    free_pattern_map: bool = True,
) -> Optional[Tuple[List[int], List[int]]]:
    """CP-SAT (phases, pattern_map) seed. Full sim remains truth."""
    try:
        from logic.staffing_cpsat import suggest_joint_seed

        return suggest_joint_seed(
            n_officers=n_officers,
            cycle_length=cycle_length,
            duty_rings=duty_rings,
            pattern_map=pattern_map,
            min_daily_on=int(min_daily_on or 0),
            window_weekday_floors=window_weekday_floors,
            sim_start_weekday=int(sim_start_weekday or 0),
            free_pattern_map=bool(free_pattern_map),
        )
    except Exception:
        if n_officers < 1 or cycle_length < 1:
            return None
        step = max(1, cycle_length // max(1, n_officers))
        phases = [(i * step) % cycle_length for i in range(int(n_officers))]
        n_pat = max(1, int(n_patterns))
        pmap = list(pattern_map) if pattern_map is not None else [i % n_pat for i in range(int(n_officers))]
        return phases, pmap[: int(n_officers)]


def estimate_search_space(
    *,
    rotation_types: Optional[List[str]] = None,
    officer_counts: Optional[List[int]] = None,
    min_per_shift_options: Optional[List[int]] = None,
    shift_length_hours: Optional[float] = None,
    shift_starts: Optional[List[str]] = None,
    shift_starts_options: Optional[List[List[str]]] = None,
    shift_length_options: Optional[List[float]] = None,
    rotation_style: str = "",
    rotation_variations: Optional[List[str]] = None,
    free_officer_counts: bool = False,
    free_starts: bool = False,
    free_lengths: bool = False,
    free_variations: bool = False,
    stagger_phases: bool = True,
    annual_hours_hard: bool = False,
    annual_hours_target: Optional[float] = None,
    annual_hours_variance: float = 0.0,
    coverage_247: int = 0,
    use_extra_windows: bool = False,
    extra_windows: Optional[List[Dict]] = None,
    max_consecutive_work_days: int = 0,
    min_rest_hours: float = 0.0,
    avoid_flsa_overtime: bool = False,
    flsa_work_period_days: int = 28,
    **_ignored,
) -> Dict:
    """
    Count layouts in the constraint-defined search space and estimate wall time.
    Used by the UI to warn before Find Best.
    """
    from config import ROTATION_PRESETS
    from logic.rotation_patterns import build_pattern

    axes = _resolve_axes(
        rotation_types=rotation_types,
        officer_counts=officer_counts,
        min_per_shift_options=min_per_shift_options,
        shift_length_hours=shift_length_hours,
        shift_length_options=shift_length_options,
        shift_starts=shift_starts,
        shift_starts_options=shift_starts_options,
        free_officer_counts=free_officer_counts,
        free_starts=free_starts,
        free_lengths=free_lengths,
        free_variations=free_variations,
        rotation_variations=rotation_variations,
        rotation_style=rotation_style,
        annual_hours_target=annual_hours_target,
        annual_hours_variance=annual_hours_variance,
    )
    axes = bind_domains(
        axes,
        coverage_247=int(coverage_247 or 0),
        use_extra_windows=bool(use_extra_windows),
        extra_windows=extra_windows,
        annual_hours_target=annual_hours_target,
        annual_hours_variance=annual_hours_variance,
        annual_hours_hard=bool(annual_hours_hard),
        max_consecutive_work_days=int(max_consecutive_work_days or 0),
        min_rest_hours=float(min_rest_hours or 0),
        avoid_flsa=bool(avoid_flsa_overtime),
        flsa_work_period_days=int(flsa_work_period_days or 28),
    )

    # Multiplicative estimate (avoid nested full enumeration when free dims explode)
    total = 0
    outer = 0
    sample_cycle = 14
    for variations in axes["variation_sets"]:
        if not variations:
            continue
        try:
            p0 = build_pattern(
                variations[0],
                style=axes["style"] if axes["style"] in ("fixed", "rotating") else None,
            )
            sample_cycle = max(sample_cycle, p0.cycle_length)
        except ValueError:
            pass

    # Cache phase/map counts by (n_off, cycle, n_pat)
    phase_map_cache: Dict[Tuple[int, int, int], int] = {}

    def _inner_count(n_off: int, cycle: int, n_pat: int, has_var: bool) -> int:
        if not has_var or not stagger_phases:
            return 1
        key = (n_off, cycle, n_pat)
        if key not in phase_map_cache:
            # Match real search: priority phases first (full expand only when needed)
            phase_map_cache[key] = len(generate_phase_layouts(n_off, cycle, mode="priority")) * len(
                generate_pattern_maps(n_off, n_pat)
            )
        return phase_map_cache[key]

    # Cache generate_start_packs length by shift length to avoid re-running the
    # combinatorial generator for every (n_off, length) pair in the estimate loop.
    _pack_len_cache: Dict[Tuple[float, int, int, int, int], int] = {}
    _est_wins = list(extra_windows or []) if use_extra_windows else []
    _est_cov = int(coverage_247 or 0)

    def _pack_count(L: float, min_b: int, max_b: int, n_off: int = 8) -> int:
        filt = bool(_est_cov > 0 or _est_wins)
        key = (L, min_b, max_b, _est_cov, 1 if _est_wins else 0, int(filt))
        if key not in _pack_len_cache:
            # Cap matches practical free-starts depth (not C(n,k)×1000 fiction)
            mp = FREE_STARTS_MAX_PACKS if filt else min(1000, FREE_STARTS_MAX_PACKS * 4)
            _pack_len_cache[key] = len(
                generate_start_packs(
                    float(L),
                    num_officers=int(n_off),
                    min_bands=min_b,
                    max_bands=max_b,
                    max_packs=mp,
                    extra_windows=_est_wins or None,
                    coverage_247=_est_cov,
                    filter_infeasible=filt,
                )
            )
        return _pack_len_cache[key]

    n_rot_valid = 0
    for rotation in axes["rotation_types"]:
        for variations in axes["variation_sets"]:
            if rotation not in ROTATION_PRESETS and not variations:
                continue
            n_rot_valid += 1
            cycle = sample_cycle
            n_pat = max(1, len(variations) if variations else 1)
            if variations:
                try:
                    cycle = build_pattern(
                        variations[0],
                        style=axes["style"] if axes["style"] in ("fixed", "rotating") else None,
                    ).cycle_length
                    n_pat = len(variations)
                except ValueError:
                    continue
            for n_off in axes["officer_counts"]:
                from logic.optimizer_features import early_impossible_proof

                inner = _inner_count(int(n_off), cycle, n_pat, bool(variations))
                max_b = min(6, max(2, int(n_off)))
                for length in axes["length_opts"]:
                    min_b = 2
                    if coverage_247 > 0:
                        import math

                        min_b = max(min_b, math.ceil(24.0 / float(length)))
                    if min_b > max_b:
                        max_b = min_b
                    if annual_hours_hard or coverage_247 > 0 or use_extra_windows:
                        win_min = _window_body_floor(extra_windows, use_windows=use_extra_windows)
                        _est_rot = ""
                        _rts = axes.get("rotation_types") or []
                        if _rts:
                            _est_rot = str(_rts[0])
                        reason = early_impossible_proof(
                            num_officers=int(n_off),
                            shift_length_hours=float(length),
                            annual_hours_target=float(annual_hours_target or 2080.0),
                            annual_hours_variance=float(annual_hours_variance),
                            annual_hours_hard=bool(annual_hours_hard),
                            rotation_variations=variations,
                            coverage_247=int(coverage_247 or 0),
                            window_min=win_min,
                            rotation_style=axes["style"],
                            rotation_type=_est_rot,
                        )
                        if reason:
                            continue

                    if axes["locked_starts_opts"] is not None:
                        n_starts = len(axes["locked_starts_opts"])
                    else:
                        n_starts = _pack_count(float(length), min_b, max_b, int(n_off))
                    for _min_ps in axes["min_per_shift_options"]:
                        outer += n_starts
                        total += n_starts * inner

    # ~3–8 ms cheap check, ~150–250 ms full sim; assume ~30% pass cheap
    est_cheap_sec = total * 0.004
    est_full_sec = total * 0.30 * 0.18
    est_sec = est_cheap_sec + est_full_sec
    est_sec_hi = est_sec * 2.5

    # Risk bands for operator confirm (time model is pessimistic; real path is faster
    # after cheap prune, but free starts/length/N still warrants confirm).
    if total >= 500_000 or est_sec_hi >= 3600:
        risk = "extreme"
    elif total >= 80_000 or est_sec_hi >= 600:
        risk = "high"
    elif total >= 15_000 or est_sec_hi >= 120:
        risk = "medium"
    else:
        risk = "low"

    def _fmt_time(sec: float) -> str:
        if sec < 60:
            return f"~{max(1, int(sec))} seconds"
        if sec < 3600:
            return f"~{sec / 60:.0f}–{sec * 2.5 / 60:.0f} minutes"
        return f"~{sec / 3600:.1f}–{sec * 2.5 / 3600:.1f} hours"

    bind_note = ""
    bind_reasons = list(axes.get("bind_reasons") or [])
    if bind_reasons:
        bind_note = " Bound: " + "; ".join(bind_reasons[:4])
        if len(bind_reasons) > 4:
            bind_note += f" (+{len(bind_reasons) - 4} more)"

    warning = ""
    if risk in ("high", "extreme"):
        locks_needed = [d for d in ("officer_count", "shift_starts", "shift_length") if d in axes["free_dims"]]
        suggestion = (
            f"Lock {', '.join(locks_needed).replace('_', ' ')} to shrink the space."
            if locks_needed
            else "Lock more constraints to shrink the space."
        )
        warning = (
            f"With current free dimensions ({', '.join(axes['free_dims']) or 'none'}), "
            f"about {total:,} layouts must be checked. "
            f"Expected time {_fmt_time(est_sec)}. "
            f"{suggestion}"
            f"{bind_note}"
        )
    elif risk == "medium":
        warning = (
            f"Search space ≈ {total:,} layouts ({_fmt_time(est_sec)}). "
            f"Locking more requirements will shrink this.{bind_note}"
        )
    else:
        warning = f"Search space ≈ {total:,} layouts ({_fmt_time(est_sec)}).{bind_note}"

    return {
        "success": True,
        "total_layouts": total,
        "outer_structural": outer,
        "free_dimensions": list(axes["free_dims"]),
        "risk": risk,
        "warning": warning,
        "est_seconds_low": round(est_sec, 1),
        "est_seconds_high": round(est_sec_hi, 1),
        "time_label": _fmt_time(est_sec),
        "requires_confirm": risk in ("high", "extreme") or total >= 50_000,
        "officer_counts": axes["officer_counts"],
        "length_options": axes["length_opts"],
        "min_per_shift_options": axes["min_per_shift_options"],
        "rotation_types": axes["rotation_types"],
        "constraint_labels": dict(CONSTRAINT_LABELS),
        "default_weights": dict(DEFAULT_CONSTRAINT_WEIGHTS),
        "bind_reasons": bind_reasons,
        "raw_counts": dict(axes.get("raw_counts") or {}),
        "bound_counts": dict(axes.get("bound_counts") or {}),
        "domain_report": domain_reduction_report(axes),
    }


def optimize_staffing_scenarios(
    *,
    rotation_types: Optional[List[str]] = None,
    officer_counts: Optional[List[int]] = None,
    min_per_shift_options: Optional[List[int]] = None,
    shift_length_hours: Optional[float] = None,
    annual_hours_target: Optional[float] = None,
    shift_starts: Optional[List[str]] = None,
    simulation_days: int = 56,
    sim_start_date: str = None,
    coverage_247: int = 0,
    avoid_flsa_overtime: bool = False,
    flsa_work_period_days: int = 28,
    annual_hours_variance: float = 40.0,
    annual_hours_hard: bool = False,
    use_extra_windows: bool = False,
    extra_windows: Optional[List[Dict]] = None,
    night_minimum: Optional[int] = None,
    require_hard_ok: bool = True,
    rotation_style: str = "",
    rotation_variations: Optional[List[str]] = None,
    stagger_phases: bool = True,
    shift_starts_options: Optional[List[List[str]]] = None,
    shift_length_options: Optional[List[float]] = None,
    max_total_evals: Optional[int] = None,  # ignored — no artificial eval cap
    search_depth: str = "standard",  # standard=faster walls · deep=thorough walls
    max_inner_trials: Optional[int] = None,  # ignored
    free_officer_counts: bool = False,
    free_starts: bool = False,
    free_lengths: bool = False,
    free_variations: bool = False,
    constraint_weights: Optional[Dict[str, float]] = None,
    constraint_priority: Optional[List[str]] = None,
    soft_prefs: Optional[Dict[str, float]] = None,  # soft rank among hard-OK only
    nearby_start_hops: int = 1,
    allow_offday_coverage: bool = False,
    min_rest_hours: float = 0.0,
    max_consecutive_work_days: int = 0,
    progress_callback=None,
    cancel_check=None,
) -> Dict:
    """
    Sweep of the constraint-defined space (outer × phase × pattern).

    search_depth: "standard" (faster anytime/pack budgets) or "deep" (thorough).
    Free shift lengths stay the full half-hour grid when free (depth does not
    drop lengths — that false-greened viable options). Depth only changes
    wall-clock / pack / diversity budgets.

    max_total_evals / max_inner_trials accepted for API compat (ignored).

    nearby_start_hops — work-day start "bumps" from home (± pack bands).
    allow_offday_coverage — only when user opts in; default respects rotation OFF.

    progress_callback(dict) — optional; receives done/total/full_sims/best_summary.
    cancel_check() — optional; when True, stop and return partial results.
    """
    from config import ROTATION_PRESETS
    from logic.rotation_patterns import build_pattern
    from simulator import SimulatorConfig, simulate_schedule

    del max_total_evals, max_inner_trials  # no hard eval caps
    _depth = _depth_key(search_depth)
    _bud = dict(_DEPTH_BUDGETS[_depth])

    nearby_hops = max(0, int(nearby_start_hops if nearby_start_hops is not None else 1))
    offday_ok = bool(allow_offday_coverage)

    t0 = time.perf_counter()
    weights = _weights_from_priority(constraint_priority, constraint_weights)
    cancelled = False

    def _cancelled() -> bool:
        nonlocal cancelled
        if cancel_check is None:
            return cancelled
        try:
            if cancel_check():
                cancelled = True
                return True
        except Exception:
            pass
        return cancelled

    def _progress(**kwargs) -> None:
        if progress_callback is None:
            return
        try:
            progress_callback(kwargs)
        except Exception:
            pass

    space = estimate_search_space(
        rotation_types=rotation_types,
        officer_counts=officer_counts,
        min_per_shift_options=min_per_shift_options,
        shift_length_hours=shift_length_hours,
        shift_starts=shift_starts,
        shift_starts_options=shift_starts_options,
        shift_length_options=shift_length_options,
        rotation_style=rotation_style,
        rotation_variations=rotation_variations,
        free_officer_counts=free_officer_counts,
        free_starts=free_starts,
        free_lengths=free_lengths,
        free_variations=free_variations,
        stagger_phases=stagger_phases,
        annual_hours_hard=bool(annual_hours_hard),
        annual_hours_target=annual_hours_target,
        annual_hours_variance=float(annual_hours_variance if annual_hours_variance is not None else 40.0),
        coverage_247=int(coverage_247 or 0),
        use_extra_windows=bool(use_extra_windows),
        extra_windows=extra_windows,
    )

    axes = _resolve_axes(
        rotation_types=rotation_types,
        officer_counts=officer_counts,
        min_per_shift_options=min_per_shift_options,
        shift_length_hours=shift_length_hours,
        shift_length_options=shift_length_options,
        shift_starts=shift_starts,
        shift_starts_options=shift_starts_options,
        free_officer_counts=free_officer_counts,
        free_starts=free_starts,
        free_lengths=free_lengths,
        free_variations=free_variations,
        rotation_variations=rotation_variations,
        rotation_style=rotation_style,
        annual_hours_target=annual_hours_target,
        annual_hours_variance=annual_hours_variance,
    )

    staffing = axes["staffing"]
    annual = float(annual_hours_target) if annual_hours_target is not None else float(staffing["annual_hours_target"])
    # UI passes None when the annual-hours requirement is off; every consumer
    # below expects a number (float() at the early-impossible gate crashed on
    # None — found live 2026-07-17). Coalesce to the signature default once.
    annual_hours_variance = float(annual_hours_variance) if annual_hours_variance is not None else 40.0
    night_min = int(night_minimum) if night_minimum is not None else int(config.NIGHT_MINIMUM_OFFICERS)
    windows = list(extra_windows or [])
    cov247 = max(0, int(coverage_247 or 0))
    # L0–L2: shrink axes using constraints together (before any layout enum)
    axes = bind_domains(
        axes,
        coverage_247=cov247,
        use_extra_windows=bool(use_extra_windows),
        extra_windows=windows,
        annual_hours_target=annual,
        annual_hours_variance=annual_hours_variance,
        annual_hours_hard=bool(annual_hours_hard),
        max_consecutive_work_days=int(max_consecutive_work_days or 0),
        min_rest_hours=float(min_rest_hours or 0),
        avoid_flsa=bool(avoid_flsa_overtime),
        flsa_work_period_days=int(flsa_work_period_days or 28),
    )
    style = axes["style"]
    sim_start = date.today()
    if sim_start_date:
        try:
            from datetime import date as _date

            sim_start = _date.fromisoformat(str(sim_start_date))
        except (ValueError, TypeError):
            sim_start = date.today()  # graceful fallback
    window_min = _window_body_floor(windows, use_windows=bool(use_extra_windows and windows))
    multi_block_mode = any((v and any("," in str(x) for x in v)) for v in axes.get("variation_sets") or []) or any(
        "," in str(x) for x in (axes.get("base_variations") or [])
    )

    # C5 — early impossible when every officer count fails pattern/body floors
    from logic.optimizer_features import diversify_ranked, early_impossible_proof

    early_skip_all = True
    early_reasons: List[str] = []
    length0 = float(axes["length_opts"][0]) if axes["length_opts"] else float(shift_length_hours or 8)
    for n_try in axes["officer_counts"]:
        _rot_try = ""
        _rts_try = axes.get("rotation_types") or []
        if _rts_try:
            _rot_try = str(_rts_try[0])
        reason = early_impossible_proof(
            num_officers=int(n_try),
            shift_length_hours=length0,
            annual_hours_target=float(annual),
            annual_hours_variance=float(annual_hours_variance),
            annual_hours_hard=bool(annual_hours_hard),
            rotation_variations=axes.get("base_variations") or None,
            coverage_247=cov247,
            window_min=window_min,
            rotation_style=style or "rotating",
            max_consecutive_work_days=int(max_consecutive_work_days or 0),
            min_rest_hours=float(min_rest_hours or 0),
            avoid_flsa=bool(avoid_flsa_overtime),
            flsa_work_period_days=int(flsa_work_period_days or 28),
            rotation_type=_rot_try,
        )
        if reason:
            early_reasons.append(f"N={n_try}: {reason}")
        else:
            early_skip_all = False
    if early_skip_all and axes["officer_counts"] and require_hard_ok:
        # Still one soft full-sim so UI gets near-miss options (not empty silence).
        from simulator import SimulatorConfig, simulate_schedule

        n_try = max(int(x) for x in axes["officer_counts"])
        length_try = length0
        starts_try = (
            list(axes["locked_starts_opts"][0]) if axes.get("locked_starts_opts") else ["06:00", "14:00", "22:00"]
        )
        vars_try = list(axes.get("base_variations") or [])
        cfg = SimulatorConfig(
            rotation_type=(axes["rotation_types"][0] if axes["rotation_types"] else "2-2-3 (14-day)"),
            num_officers=n_try,
            shift_length_hours=float(length_try),
            annual_hours_target=float(annual),
            shift_starts=starts_try,
            apply_department_rules=False,
            min_per_shift=int(axes["min_per_shift_options"][0]),
            simulation_days=int(simulation_days),
            night_minimum=night_min,
            annual_hours_variance=float(annual_hours_variance),
            annual_hours_hard=bool(annual_hours_hard),
            coverage_247=cov247,
            avoid_flsa_overtime=bool(avoid_flsa_overtime),
            flsa_work_period_days=int(flsa_work_period_days or 28),
            use_extra_windows=bool(use_extra_windows and windows),
            extra_windows=windows,
            auto_min_officers=False,
            rotation_style=style or "rotating",
            rotation_variations=vars_try,
            stagger_phases=True,
        )
        sim = simulate_schedule(cfg)
        near: List[Dict] = []
        if sim.success:
            m = sim.metrics or {}
            v = _violation_vector(m, annual=annual, annual_variance=annual_hours_variance)
            failed = [k for k in ("coverage_247", "windows", "gaps", "flsa", "annual") if v.get(k, 0) > 0]
            near.append(
                {
                    "score": 0,
                    "rotation_type": cfg.rotation_type,
                    "num_officers": n_try,
                    "min_per_shift": cfg.min_per_shift,
                    "shift_length_hours": length_try,
                    "annual_hours_target": annual,
                    "shift_starts": starts_try,
                    "rotation_style": style,
                    "rotation_variations": vars_try,
                    "hard_constraints_ok": False,
                    "metrics": m,
                    "violations": v,
                    "failed_constraints": failed or ["windows"],
                    "summary": (
                        f"{n_try} Officers · Early impossible — "
                        + (early_reasons[0] if early_reasons else "constraints")
                    ),
                    "rank": 1,
                    "human_metrics": {
                        "extra_window_failures": int(m.get("extra_window_failures") or 0),
                        "coverage_247_failures": int(m.get("coverage_247_failures") or 0),
                        "failed_constraints": failed or ["windows"],
                        "hard_constraints_ok": False,
                    },
                }
            )
        wall_ms = int((time.perf_counter() - t0) * 1000)
        msg = "No Schedule Meets The Selected Hard Constraints (early proof)"
        if early_reasons:
            msg += " — " + early_reasons[0]
        return {
            "success": False,
            "cancelled": False,
            "scenarios_evaluated": 1,
            "scenarios_kept": 0,
            "rejected_hard_constraints": len(axes["officer_counts"]),
            "outer_configs": 1,
            "inner_trials": 1,
            "full_sims_run": 1,
            "pruned_cheap": 0,
            "search_exhaustive": True,
            "budget_exhausted": False,
            "wall_time_ms": wall_ms,
            "failure_histogram": {"early_impossible": len(early_reasons)},
            "space_estimate": space,
            "space_note": space.get("warning") or "",
            "constraint_weights": weights,
            "constraint_priority": list(constraint_priority or []),
            "near_misses": near,
            "best": None,
            "ranked": [],
            "message": msg,
            "impossible": True,
            "early_impossible": True,
            "early_reasons": early_reasons,
            "constraints_applied": {
                "coverage_247": cov247,
                "officer_counts": list(axes["officer_counts"]),
                "search_mode": "early_impossible",
            },
        }

    results: List[Dict] = []
    near_misses: List[Dict] = []
    rejected_hard = 0
    outer_configs = 0
    cheap_evals = 0
    full_sims = 0
    pruned_cheap = 0
    fail_hist: Dict[str, int] = {
        "hard_ok": 0,
        "flsa": 0,
        "window": 0,
        "coverage_247": 0,
        "annual": 0,
        "gaps": 0,
        "sim_fail": 0,
        "cheap_reject": 0,
    }

    ordered_n = sorted(axes["officer_counts"])
    space_total = int(space.get("total_layouts") or 0)
    # Anytime when bound space is large; complete scan preferred under threshold.
    prefer_exhaustive = space_total <= EXHAUSTIVE_LAYOUT_THRESHOLD
    anytime_wall = float(_bud["anytime_wall"])
    exhaustive_soft_wall = float(_bud["exhaustive_soft"])
    after_hard_sec = float(_bud["after_hard"])
    budget_exhausted = False
    search_truncated = False
    _first_hard_t: Optional[float] = None
    max_hard_results_run = int(_bud["max_hard_results"])
    if prefer_exhaustive:
        max_hard_results_run = max(max_hard_results_run, 32 if _depth == "deep" else 24)
    _progress(
        phase="start",
        done=0,
        total=space_total,
        full_sims=0,
        message=(
            f"Starting {'exhaustive' if prefer_exhaustive else 'anytime'} search "
            f"({space_total:,} bound layouts, depth={_depth})…"
        ),
    )

    # Global body cache: (pattern texts, N, phases, pat_map) → day counts — across packs
    _global_body_cache: Dict[
        Tuple[Tuple[str, ...], int, Tuple[int, ...], Tuple[int, ...]],
        Tuple[List[int], List[int]],
    ] = {}
    # Pack catalog cache: avoid re-running generate_start_packs for same (L,N,bands,filters)
    _pack_gen_cache: Dict[Tuple[Any, ...], List[List[str]]] = {}
    # CP-SAT joint seed cache: (N, cycle, duty rings, floors) → seed
    _joint_seed_cache: Dict[Tuple[Any, ...], Optional[Tuple[List[int], List[int]]]] = {}
    # FLSA threshold once per run (not per cheap node)
    try:
        from logic.labor_compliance import flsa_threshold_for_period_days as _flsa_fn_once

        _flsa_thr_run = float(_flsa_fn_once(int(flsa_work_period_days or 28)))
    except Exception:
        try:
            _flsa_thr_run = float(getattr(config, "FLSA_207K_HOURS_THRESHOLD", 171.0))
        except Exception:
            _flsa_thr_run = 171.0
    _win_wds_run = _window_weekdays_from_extra(windows if use_extra_windows else None)
    # Defer heavy minute-bin to top candidates when windows bind (body floor still always run)
    _defer_win_minute = bool(use_extra_windows and windows)

    def _enough_hard() -> bool:
        return bool(require_hard_ok and len(results) >= max_hard_results_run)

    def _note_hard_found() -> None:
        nonlocal _first_hard_t, search_truncated
        if results and _first_hard_t is None:
            _first_hard_t = time.perf_counter()
        if _enough_hard():
            search_truncated = True

    def _budget_hit() -> bool:
        nonlocal budget_exhausted, search_truncated
        if cancelled:
            return True
        if _enough_hard():
            search_truncated = True
            return True
        elapsed = time.perf_counter() - t0
        if prefer_exhaustive:
            # Soft wall: complete scan preferred, but don't thrash after hard-OK
            if results and elapsed >= exhaustive_soft_wall:
                search_truncated = True
                return True
            return False
        if elapsed >= anytime_wall:
            budget_exhausted = True
            search_truncated = True
            return True
        # After first hard-OK, only spend a short diversity window
        if _first_hard_t is not None and len(results) >= 4:
            if (time.perf_counter() - _first_hard_t) >= after_hard_sec:
                search_truncated = True
                return True
        return False

    def _record_fail(m: Optional[Dict]) -> None:
        if not m:
            fail_hist["sim_fail"] += 1
            return
        if not m.get("hard_constraints_ok", True):
            fail_hist["hard_ok"] += 1
        if int(m.get("flsa_violations") or 0):
            fail_hist["flsa"] += 1
        if int(m.get("extra_window_failures") or 0):
            fail_hist["window"] += 1
        if int(m.get("coverage_247_failures") or 0):
            fail_hist["coverage_247"] += 1
        if int(m.get("annual_mean_outside") or m.get("annual_band_outside") or 0):
            fail_hist["annual"] += 1
        gaps = m.get("gap_events")
        if gaps is None:
            gaps = m.get("zero_staff_slots") or 0
        if int(gaps or 0):
            fail_hist["gaps"] += 1

    def _row_from_sim(
        *,
        sim,
        rot_key,
        n_off,
        min_ps,
        length,
        starts,
        use_style,
        variations,
        ph,
        pm,
        hard_ok,
    ) -> Dict:
        m = sim.metrics or {}
        score = _score_metrics(
            m,
            annual=annual,
            annual_variance=float(annual_hours_variance),
            n_off=int(n_off),
            hard_ok=hard_ok,
            weights=weights,
            pattern_slot_map=list(pm) if isinstance(pm, (list, tuple)) else None,
            multi_block=bool(multi_block_mode or (variations and len(variations) > 1)),
        )
        v = _violation_vector(m, annual=annual, annual_variance=annual_hours_variance)
        failed = [k for k in ("coverage_247", "windows", "gaps", "flsa", "annual") if v.get(k, 0) > 0]
        return {
            "score": round(score, 2),
            "rotation_type": rot_key,
            "num_officers": n_off,
            "min_per_shift": min_ps,
            "shift_length_hours": length,
            "annual_hours_target": annual,
            "shift_starts": list(starts),
            "rotation_style": use_style,
            "rotation_variations": list(variations),
            "hard_constraints_ok": hard_ok,
            "metrics": m,
            "violations": v,
            "failed_constraints": failed,
            "phase_overrides": list(ph) if ph is not None else None,
            "pattern_slot_map": list(pm) if pm is not None else None,
            # Soft rank / Gantt: duty flags + coverage (P2/P3)
            "officer_slots": [s.__dict__ if hasattr(s, "__dict__") else s for s in (sim.officer_slots or [])],
            "coverage_by_day": list(sim.coverage_by_day or []),
            "suggestions": [
                {
                    "severity": s.severity,
                    "title": s.title,
                    "message": s.message,
                    "recommendation": s.recommendation,
                }
                for s in (sim.suggestions or [])
            ],
        }

    # Fail-first outer order: length → N → variations → rotation → min_ps → packs
    for length in axes["length_opts"]:
        if _budget_hit() or _cancelled():
            break
        for n_off in ordered_n:
            if _budget_hit() or _cancelled():
                break
            # Max distinct start bands ≈ roster size
            max_b = min(6, max(2, int(n_off)))
            for variations in axes["variation_sets"]:
                if _budget_hit() or _cancelled():
                    break
                for rotation in axes["rotation_types"]:
                    if _budget_hit() or _cancelled():
                        break
                    if rotation not in ROTATION_PRESETS and not variations:
                        continue
                    rot_key = rotation if rotation in ROTATION_PRESETS else next(iter(ROTATION_PRESETS.keys()))
                    use_style = style
                    if variations and use_style not in ("fixed", "rotating"):
                        use_style = "rotating" if any("," in v for v in variations) else "fixed"

                    parsed_patterns = []
                    cycle_len = 14
                    if variations:
                        try:
                            for t in variations:
                                parsed_patterns.append(
                                    build_pattern(
                                        t,
                                        style=use_style if use_style in ("fixed", "rotating") else None,
                                    )
                                )
                            cycle_len = parsed_patterns[0].cycle_length
                        except ValueError:
                            continue

                    # CP-SAT joint phase+pattern seed (window-aware). Full sim still truth.
                    # Skip when domain already tiny (seed cost > benefit) or cache hit.
                    _phase_seed = None
                    _pat_map_seed = None
                    _joint_min_bodies = 0
                    if parsed_patterns and stagger_phases and int(n_off) <= 12:
                        import math as _math_seed

                        from logic.staffing_cpsat import phase_quality, windows_to_weekday_floors

                        _duty_rings = [list(p.duty_vector()) for p in parsed_patterns]
                        _body_floor = 0
                        if cov247 > 0 and float(length) > 0:
                            _bands = max(1, _math_seed.ceil(24.0 / float(length)))
                            _body_floor = int(_bands) * int(cov247)
                        _win_floors = windows_to_weekday_floors(windows) if use_extra_windows and windows else None
                        _jkey = (
                            int(n_off),
                            int(cycle_len),
                            tuple(tuple(r) for r in _duty_rings),
                            int(_body_floor),
                            tuple(_win_floors) if _win_floors else None,
                            int(sim_start.weekday()),
                        )
                        if _jkey in _joint_seed_cache:
                            _joint = _joint_seed_cache[_jkey]
                        else:
                            # Skip joint solver when bound space is already small
                            if space_total > 0 and space_total < 200:
                                _joint = None
                            else:
                                _joint = try_cpsat_joint_seed(
                                    n_officers=int(n_off),
                                    cycle_length=int(cycle_len),
                                    n_patterns=len(parsed_patterns),
                                    duty_rings=_duty_rings,
                                    min_daily_on=_body_floor,
                                    window_weekday_floors=_win_floors,
                                    sim_start_weekday=int(sim_start.weekday()),
                                    free_pattern_map=True,
                                )
                            _joint_seed_cache[_jkey] = _joint
                        if _joint is not None:
                            _phase_seed, _pat_map_seed = _joint
                            _mn, _, _mw = phase_quality(
                                _phase_seed,
                                _duty_rings,
                                pattern_map=_pat_map_seed,
                                sim_start_weekday=int(sim_start.weekday()),
                                window_weekday_floors=_win_floors,
                            )
                            _joint_min_bodies = int(_mn)

                    for min_ps in axes["min_per_shift_options"]:
                        if _budget_hit() or _cancelled():
                            break
                        import math

                        min_b = 2
                        if cov247 > 0:
                            min_b = max(min_b, math.ceil(24.0 / float(length)))
                        if min_b > max_b:
                            max_b = min_b

                        if axes["locked_starts_opts"] is not None:
                            starts_opts = [list(s) for s in axes["locked_starts_opts"]]
                        else:
                            _filt = bool(
                                axes.get("filter_start_packs")
                                or (
                                    require_hard_ok
                                    and (
                                        cov247 > 0 or (use_extra_windows and windows) or float(min_rest_hours or 0) > 0
                                    )
                                )
                            )
                            _pack_max = FREE_STARTS_MAX_PACKS if _filt else min(1000, FREE_STARTS_MAX_PACKS * 4)
                            _pack_key = (
                                float(length),
                                int(n_off),
                                max(min_b, int(axes.get("min_bands_hint") or 2)),
                                int(max_b),
                                int(_pack_max),
                                int(cov247),
                                bool(_filt),
                                float(min_rest_hours or 0),
                                int(nearby_hops or 0),
                                tuple(
                                    (
                                        str(w.get("start_time") or w.get("start") or ""),
                                        str(w.get("end_time") or w.get("end") or ""),
                                        int(w.get("min_officers") or 0),
                                        str(w.get("weekday", w.get("weekdays", ""))),
                                    )
                                    for w in (windows if use_extra_windows and windows else [])
                                ),
                            )
                            if _pack_key in _pack_gen_cache:
                                starts_opts = [list(p) for p in _pack_gen_cache[_pack_key]]
                            else:
                                starts_opts = generate_start_packs(
                                    float(length),
                                    num_officers=int(n_off),
                                    min_bands=max(min_b, int(axes.get("min_bands_hint") or 2)),
                                    max_bands=max_b,
                                    max_packs=_pack_max,
                                    extra_windows=windows if use_extra_windows else None,
                                    coverage_247=cov247,
                                    filter_infeasible=_filt,
                                    min_rest_hours=float(min_rest_hours or 0),
                                    nearby_hops=int(nearby_hops or 0),
                                )
                                _pack_gen_cache[_pack_key] = [list(p) for p in starts_opts]
                            # Start-band CP-SAT seed: re-rank packs by body-feasible coverage
                            # Skip when pack list already tiny (rank cost > benefit)
                            if (
                                starts_opts
                                and len(starts_opts) > 4
                                and (cov247 > 0 or (use_extra_windows and windows) or _joint_min_bodies > 0)
                            ):
                                try:
                                    from logic.staffing_cpsat import rank_start_packs_seed

                                    _bodies = max(int(_joint_min_bodies or 0), 1)
                                    starts_opts = rank_start_packs_seed(
                                        starts_opts,
                                        shift_length_hours=float(length),
                                        n_bodies=_bodies,
                                        coverage_247=int(cov247),
                                        extra_windows=windows if use_extra_windows else None,
                                        min_per_shift=int(min_ps or 0),
                                        max_keep=len(starts_opts),
                                    )
                                except Exception:
                                    pass

                        def _starts_priority(st: Sequence[str]) -> Tuple[int, int, int, str]:
                            hours = []
                            for s in st:
                                try:
                                    hours.append(int(str(s).split(":")[0]))
                                except ValueError:
                                    hours.append(0)
                            has_19 = any(h == 19 for h in hours)
                            has_14 = any(12 <= h < 19 for h in hours)
                            has_22 = any(h >= 20 or h < 5 for h in hours)
                            has_am = any(5 <= h <= 9 for h in hours)
                            if has_19 and has_14 and has_22 and has_am:
                                score = 0
                            elif has_19 and has_14 and has_22:
                                score = 1
                            elif has_14 and has_22 and has_am and not has_19:
                                score = 2
                            elif has_19 and has_14:
                                score = 3
                            elif has_19:
                                score = 4
                            else:
                                score = 6
                            return (score, -len(st), min(hours) if hours else 99, ",".join(st))

                        if axes["locked_starts_opts"] is None and len(starts_opts) > 1:
                            starts_opts = sorted(starts_opts, key=_starts_priority)
                            pack_cap = 48 if require_hard_ok else FREE_STARTS_MAX_PACKS
                            if prefer_exhaustive:
                                pack_cap = max(pack_cap, min(len(starts_opts), FREE_STARTS_MAX_PACKS))
                            if len(starts_opts) > pack_cap:
                                starts_opts = starts_opts[:pack_cap]
                                search_truncated = True

                        # Explore packs; anytime caps unless space small enough for exhaustive
                        max_hard_results = max_hard_results_run
                        max_unique_start_packs = 8 if not prefer_exhaustive else max(8, min(32, len(starts_opts)))
                        exhaustive_packs_left = 2 if not prefer_exhaustive else max(2, min(8, len(starts_opts)))

                        def _unique_packs() -> int:
                            return len(
                                {tuple(r.get("shift_starts") or []) for r in results if r.get("hard_constraints_ok")}
                            )

                        _seen_pack_keys = {tuple(sorted(s)) for s in starts_opts}

                        for starts in starts_opts:
                            if _budget_hit() or _cancelled():
                                break
                            if require_hard_ok and (
                                len(results) >= max_hard_results or _unique_packs() >= max_unique_start_packs
                            ):
                                search_truncated = True
                                break
                            _seen_pack_keys.add(tuple(sorted(starts)))
                            # C3 pack-level prune: only when zero bands cover a window
                            # sample (stacking officers cannot help). need>N still full-sims
                            # so soft mode can rank near-misses.
                            if (
                                use_extra_windows
                                and windows
                                and not pack_meets_window_bands(
                                    starts,
                                    float(length),
                                    windows,
                                    num_officers=None,
                                )
                            ):
                                pruned_cheap += 1
                                fail_hist["cheap_reject"] = fail_hist.get("cheap_reject", 0) + 1
                                fail_hist["window"] = fail_hist.get("window", 0) + 1
                                if require_hard_ok:
                                    rejected_hard += 1
                                continue
                            outer_configs += 1
                            n_bands = max(1, len(starts))
                            hard_ok_this_pack = False

                            if parsed_patterns and stagger_phases:
                                # Priority phases first (fast); expand to full if no hard-OK.
                                phase_layouts = generate_phase_layouts(int(n_off), cycle_len, mode="priority")
                                pat_maps = generate_pattern_maps(int(n_off), len(parsed_patterns))
                            elif parsed_patterns:
                                phase_layouts = [[0] * int(n_off)]
                                pat_maps = generate_pattern_maps(int(n_off), len(parsed_patterns))
                            else:
                                phase_layouts = [None]
                                pat_maps = [None]

                            # Fast path: simulator built-in stagger (None overrides) before
                            # exhaustive phase×pattern cheap scan — finds 14/19 evening packs
                            # and good multi-block offsets without waiting on 2k+ cheap nodes.
                            _fast_layouts: List[Tuple[Optional[List[int]], Optional[List[int]]]] = []
                            if parsed_patterns and stagger_phases:
                                _fast_layouts.append((None, None))
                            for _fph, _fpm in _fast_layouts:
                                if _cancelled():
                                    break
                                if require_hard_ok and len(results) >= max_hard_results:
                                    break
                                cfg = SimulatorConfig(
                                    rotation_type=rot_key,
                                    num_officers=int(n_off),
                                    shift_length_hours=float(length),
                                    annual_hours_target=float(annual),
                                    shift_starts=list(starts),
                                    apply_department_rules=False,
                                    min_per_shift=int(min_ps),
                                    simulation_days=int(simulation_days),
                                    night_minimum=night_min,
                                    annual_hours_variance=float(annual_hours_variance),
                                    annual_hours_hard=bool(annual_hours_hard),
                                    coverage_247=cov247,
                                    avoid_flsa_overtime=bool(avoid_flsa_overtime),
                                    flsa_work_period_days=int(flsa_work_period_days or 28),
                                    use_extra_windows=bool(use_extra_windows and windows),
                                    extra_windows=windows,
                                    auto_min_officers=False,
                                    rotation_style=use_style,
                                    rotation_variations=list(variations),
                                    stagger_phases=True,
                                    phase_overrides=None,
                                    pattern_slot_map=None,
                                    flexible_daily_starts=False,
                                    nearby_start_hops=nearby_hops,
                                    allow_offday_coverage=offday_ok,
                                    min_rest_hours=float(min_rest_hours),
                                    max_consecutive_work_days=int(max_consecutive_work_days),
                                    sim_start_date=sim_start,
                                )
                                sim = simulate_schedule(cfg)
                                full_sims += 1
                                cheap_evals += 1
                                _progress(
                                    phase="fast",
                                    done=cheap_evals,
                                    total=space_total or cheap_evals,
                                    full_sims=full_sims,
                                    message=f"Fast stagger try · starts {starts}",
                                )
                                if not sim.success:
                                    continue
                                m = sim.metrics or {}
                                hard_ok = bool(m.get("hard_constraints_ok", True))
                                row = _row_from_sim(
                                    sim=sim,
                                    rot_key=rot_key,
                                    n_off=n_off,
                                    min_ps=min_ps,
                                    length=length,
                                    starts=starts,
                                    use_style=use_style,
                                    variations=variations,
                                    ph=None,
                                    pm=None,
                                    hard_ok=hard_ok,
                                )
                                if not _constraint_fail(
                                    m,
                                    require_hard_ok=require_hard_ok,
                                    avoid_flsa_overtime=avoid_flsa_overtime,
                                    cov247=cov247,
                                    use_extra_windows=bool(use_extra_windows and windows),
                                    windows=windows,
                                    annual_hours_hard=annual_hours_hard,
                                    min_ps=int(min_ps),
                                    min_rest_hours=float(min_rest_hours),
                                    max_consecutive_work_days=int(max_consecutive_work_days),
                                ):
                                    results.append(row)
                                    _note_hard_found()
                                    hard_ok_this_pack = True
                                    # Neighborhood ±30m only when starts are free (locked packs stay locked)
                                    if axes["locked_starts_opts"] is None:
                                        for nb in neighbor_start_packs(starts):
                                            nk = tuple(sorted(nb))
                                            if nk not in _seen_pack_keys:
                                                _seen_pack_keys.add(nk)
                                                starts_opts.append(nb)
                                    if len(results) >= max_hard_results:
                                        break
                                    continue
                                rejected_hard += 1
                                _record_fail(m)
                                near_misses.append(row)

                            if require_hard_ok and len(results) >= max_hard_results:
                                search_truncated = True
                                continue
                            # Fast path hard-OK this pack → skip heavy phase×map grid.
                            # Full sim remains truth for that hit; other packs still searched.
                            if require_hard_ok and hard_ok_this_pack:
                                continue
                            if require_hard_ok and results and exhaustive_packs_left <= 0 and not prefer_exhaustive:
                                search_truncated = True
                                continue
                            if require_hard_ok and not hard_ok_this_pack:
                                exhaustive_packs_left -= 1

                            _cheap_penalty = {
                                "coverage_247": 50_000,
                                "window": 40_000,
                                "gaps": 30_000,
                                "annual": 20_000,
                                "rest": 45_000,
                                "consecutive": 42_000,
                                "flsa": 35_000,
                                "night": 38_000,
                            }
                            # Prefer CP-SAT joint phase + pattern-map seeds first
                            if _phase_seed is not None and phase_layouts and phase_layouts[0] is not None:
                                sk = tuple(_phase_seed)
                                if sk not in {tuple(p) for p in phase_layouts if p is not None}:
                                    phase_layouts = [_phase_seed] + list(phase_layouts)
                            if _pat_map_seed is not None and pat_maps:
                                pmk = tuple(_pat_map_seed)
                                if pmk not in {tuple(m) for m in pat_maps if m is not None}:
                                    pat_maps = [_pat_map_seed] + list(pat_maps)

                            pat_key = tuple(variations) if variations else tuple()
                            candidates: List[Tuple[float, Optional[List[int]], Optional[List[int]], bool]] = []
                            _flsa_thr = float(_flsa_thr_run)
                            _win_wds = _win_wds_run
                            for ph in phase_layouts:
                                if _cancelled() or _budget_hit():
                                    break
                                for pm in pat_maps:
                                    cheap_evals += 1
                                    if cheap_evals % 250 == 0 or cheap_evals == 1:
                                        _progress(
                                            phase="cheap",
                                            done=cheap_evals,
                                            total=space_total or cheap_evals,
                                            full_sims=full_sims,
                                            message=(
                                                f"Cheap filter {cheap_evals:,}"
                                                + (f" / {space_total:,}" if space_total else "")
                                            ),
                                        )
                                    if parsed_patterns and ph is not None and pm is not None:
                                        gkey = (
                                            pat_key,
                                            int(n_off),
                                            tuple(ph),
                                            tuple(pm),
                                            tuple(_win_wds),
                                        )
                                        if gkey in _global_body_cache:
                                            day_counts, win_bodies = _global_body_cache[gkey]
                                        else:
                                            day_counts, win_bodies = _day_body_counts(
                                                parsed_patterns,
                                                ph,
                                                pm,
                                                n_slots=int(n_off),
                                                simulation_days=int(simulation_days),
                                                sim_start=sim_start,
                                                window_weekdays=_win_wds,
                                            )
                                            _global_body_cache[gkey] = (day_counts, win_bodies)
                                        body_score = (min(day_counts) if day_counts else 0) * 1000 + (
                                            min(win_bodies) if win_bodies else 0
                                        ) * 100
                                        # Light cheap first; defer C3 minute-bin to top ranks
                                        reason = _cheap_reject(
                                            parsed_patterns,
                                            ph,
                                            pm,
                                            n_slots=int(n_off),
                                            shift_length=float(length),
                                            annual_target=float(annual),
                                            annual_variance=float(annual_hours_variance),
                                            annual_hard=bool(annual_hours_hard),
                                            simulation_days=int(simulation_days),
                                            cov247=cov247,
                                            use_windows=bool(use_extra_windows and windows),
                                            window_min=window_min,
                                            n_bands=n_bands,
                                            min_ps=int(min_ps),
                                            sim_start=sim_start,
                                            shift_starts=starts,
                                            extra_windows=windows,
                                            precomputed=(day_counts, win_bodies),
                                            nearby_hops=nearby_hops,
                                            allow_offday_coverage=offday_ok,
                                            avoid_flsa=bool(avoid_flsa_overtime),
                                            flsa_period_days=int(flsa_work_period_days or 28),
                                            flsa_threshold=float(_flsa_thr),
                                            max_consecutive_work_days=int(max_consecutive_work_days or 0),
                                            min_rest_hours=float(min_rest_hours or 0),
                                            night_minimum=int(night_min or 0),
                                            rotation_type=str(rot_key or ""),
                                            skip_window_minute=_defer_win_minute,
                                        )
                                        if reason:
                                            pruned_cheap += 1
                                            fail_hist["cheap_reject"] += 1
                                            fail_hist[reason] = fail_hist.get(reason, 0) + 1
                                            if require_hard_ok:
                                                rejected_hard += 1
                                            cheap_score = body_score - float(_cheap_penalty.get(reason, 25_000))
                                            candidates.append((cheap_score, ph, pm, False))
                                        else:
                                            candidates.append((float(body_score), ph, pm, True))
                                    else:
                                        # Squad (no multi-block patterns): still cheap-prune packs
                                        if ph is None and pm is None:
                                            reason = _cheap_reject(
                                                None,
                                                [0] * int(n_off),
                                                [0] * int(n_off),
                                                n_slots=int(n_off),
                                                shift_length=float(length),
                                                annual_target=float(annual),
                                                annual_variance=float(annual_hours_variance),
                                                annual_hard=bool(annual_hours_hard),
                                                simulation_days=int(simulation_days),
                                                cov247=cov247,
                                                use_windows=bool(use_extra_windows and windows),
                                                window_min=window_min,
                                                n_bands=n_bands,
                                                min_ps=int(min_ps),
                                                sim_start=sim_start,
                                                shift_starts=starts,
                                                extra_windows=windows,
                                                nearby_hops=nearby_hops,
                                                allow_offday_coverage=offday_ok,
                                                avoid_flsa=bool(avoid_flsa_overtime),
                                                flsa_period_days=int(flsa_work_period_days or 28),
                                                flsa_threshold=float(_flsa_thr),
                                                max_consecutive_work_days=int(max_consecutive_work_days or 0),
                                                min_rest_hours=float(min_rest_hours or 0),
                                                night_minimum=int(night_min or 0),
                                                rotation_type=str(rot_key or ""),
                                                skip_window_minute=_defer_win_minute,
                                            )
                                            if reason:
                                                pruned_cheap += 1
                                                fail_hist["cheap_reject"] += 1
                                                fail_hist[reason] = fail_hist.get(reason, 0) + 1
                                                if require_hard_ok:
                                                    rejected_hard += 1
                                                candidates.append(
                                                    (-float(_cheap_penalty.get(reason, 25_000)), ph, pm, False)
                                                )
                                            else:
                                                candidates.append((0.0, ph, pm, True))
                                        else:
                                            candidates.append((0.0, ph, pm, True))
                            if _cancelled():
                                break

                            # Built-in multi-block stagger heuristic (None overrides) —
                            # often the strongest layout; always evaluated.
                            if parsed_patterns and stagger_phases:
                                candidates.append((1e12, None, None, True))
                            if not candidates:
                                candidates.append((0.0, None, None, True))

                            candidates.sort(key=lambda x: -x[0])
                            # Defer C3 minute-bin: only top light-pass candidates (not all phase×map)
                            max_cheap_pass = int(_bud["max_cheap_pass"])
                            if _defer_win_minute and parsed_patterns:
                                # Top body-ranked only; exhaustive gets a wider minute budget
                                _minute_budget = max(max_cheap_pass * 2, 64)
                                if prefer_exhaustive:
                                    _minute_budget = max(_minute_budget, max_cheap_pass * 4, 128)
                                _refined: List[Tuple[float, Optional[List[int]], Optional[List[int]], bool]] = []
                                _minute_checked = 0
                                for cheap_score, ph, pm, passed in candidates:
                                    if (
                                        passed
                                        and ph is not None
                                        and pm is not None
                                        and _minute_checked < _minute_budget
                                    ):
                                        _minute_checked += 1
                                        cheap_evals += 1
                                        if _cheap_window_minute_fail(
                                            parsed_patterns,
                                            ph,
                                            pm,
                                            n_slots=int(n_off),
                                            shift_starts=starts,
                                            shift_length=float(length),
                                            simulation_days=int(simulation_days),
                                            sim_start=sim_start,
                                            windows=list(windows),
                                            nearby_hops=nearby_hops,
                                            allow_offday_coverage=offday_ok,
                                        ):
                                            pruned_cheap += 1
                                            fail_hist["cheap_reject"] += 1
                                            fail_hist["window"] = fail_hist.get("window", 0) + 1
                                            if require_hard_ok:
                                                rejected_hard += 1
                                            cheap_score = float(cheap_score) - float(
                                                _cheap_penalty.get("window", 40_000)
                                            )
                                            _refined.append((cheap_score, ph, pm, False))
                                        else:
                                            _refined.append((float(cheap_score), ph, pm, True))
                                    else:
                                        # Unchecked light-pass: keep passed=True so they
                                        # remain eligible for full-sim. Never false-fail.
                                        # Mark search truncated — did not minute-check all.
                                        if passed and ph is not None and pm is not None:
                                            search_truncated = True
                                            _refined.append(
                                                (
                                                    float(cheap_score) - 500.0,
                                                    ph,
                                                    pm,
                                                    True,
                                                )
                                            )
                                        else:
                                            _refined.append((cheap_score, ph, pm, passed))
                                candidates = _refined
                                candidates.sort(key=lambda x: -x[0])

                            # Full-sim queue: top cheap-pass + top cheap-fail for near-miss
                            full_queue: List[Tuple[float, Optional[List[int]], Optional[List[int]]]] = []
                            cheap_pass_kept = 0
                            cheap_fail_kept = 0
                            for cheap_score, ph, pm, passed in candidates:
                                if passed:
                                    if cheap_pass_kept < max_cheap_pass:
                                        full_queue.append((cheap_score, ph, pm))
                                        cheap_pass_kept += 1
                                    else:
                                        # Eligible pass skipped full-sim → not exhaustive
                                        search_truncated = True
                                elif cheap_fail_kept < 5:
                                    full_queue.append((cheap_score, ph, pm))
                                    cheap_fail_kept += 1

                            found_hard_structural = False
                            best_miss_row = None
                            best_miss_score = -1e18
                            rank_pool_remaining = 4
                            full_this_struct = 0
                            max_full_per_struct = int(_bud["max_full_per_struct"])
                            # C1 — parallel full-sims: threads default; process pool via env
                            use_proc = _OPT_PROCESS_WORKERS > 0
                            parallel_workers = _OPT_PROCESS_WORKERS if use_proc else _OPT_THREAD_WORKERS

                            def _cfg_dict(ph, pm) -> Dict[str, Any]:
                                return {
                                    "rotation_type": rot_key,
                                    "num_officers": int(n_off),
                                    "shift_length_hours": float(length),
                                    "annual_hours_target": float(annual),
                                    "shift_starts": list(starts),
                                    "apply_department_rules": False,
                                    "min_per_shift": int(min_ps),
                                    "simulation_days": int(simulation_days),
                                    "night_minimum": night_min,
                                    "annual_hours_variance": float(annual_hours_variance),
                                    "annual_hours_hard": bool(annual_hours_hard),
                                    "coverage_247": cov247,
                                    "avoid_flsa_overtime": bool(avoid_flsa_overtime),
                                    "flsa_work_period_days": int(flsa_work_period_days or 28),
                                    "use_extra_windows": bool(use_extra_windows and windows),
                                    "extra_windows": windows,
                                    "auto_min_officers": False,
                                    "rotation_style": use_style,
                                    "rotation_variations": list(variations),
                                    "stagger_phases": bool(stagger_phases) if ph is None else False,
                                    "phase_overrides": list(ph) if ph is not None else None,
                                    "pattern_slot_map": list(pm) if pm is not None else None,
                                    "flexible_daily_starts": False,
                                    "nearby_start_hops": nearby_hops,
                                    "allow_offday_coverage": offday_ok,
                                    "min_rest_hours": float(min_rest_hours),
                                    "max_consecutive_work_days": int(max_consecutive_work_days),
                                    "sim_start_date": sim_start,
                                }

                            def _run_one_full(ph, pm):
                                cfg = SimulatorConfig(**_cfg_dict(ph, pm))
                                sim = simulate_schedule(cfg)
                                return ph, pm, sim

                            class _SimProxy:
                                __slots__ = ("success", "metrics", "suggestions", "officer_slots")

                                def __init__(self, d: Dict[str, Any]):
                                    self.success = d.get("success")
                                    self.metrics = d.get("metrics") or {}
                                    self.suggestions = []
                                    self.officer_slots = d.get("officer_slots") or []

                            q_idx = 0
                            while q_idx < len(full_queue):
                                if _cancelled():
                                    break
                                if full_this_struct >= max_full_per_struct:
                                    break
                                if found_hard_structural and rank_pool_remaining <= 0:
                                    break
                                batch_n = min(
                                    parallel_workers,
                                    max_full_per_struct - full_this_struct,
                                    len(full_queue) - q_idx,
                                )
                                if found_hard_structural:
                                    batch_n = min(batch_n, max(1, rank_pool_remaining))
                                batch = full_queue[q_idx : q_idx + batch_n]
                                q_idx += batch_n
                                batch_out = []
                                if batch_n <= 1 or (not use_proc and parallel_workers <= 1):
                                    for _cs, ph, pm in batch:
                                        batch_out.append(_run_one_full(ph, pm))
                                elif use_proc:
                                    payloads = [
                                        {
                                            "ph": ph,
                                            "pm": pm,
                                            "cfg": _cfg_dict(ph, pm),
                                        }
                                        for _cs, ph, pm in batch
                                    ]
                                    try:
                                        with ProcessPoolExecutor(max_workers=batch_n) as pool:
                                            for d in pool.map(_full_sim_worker, payloads):
                                                batch_out.append(
                                                    (
                                                        d.get("ph"),
                                                        d.get("pm"),
                                                        _SimProxy(d),
                                                    )
                                                )
                                    except Exception:
                                        # Fallback serial if process pool fails (Windows)
                                        for _cs, ph, pm in batch:
                                            batch_out.append(_run_one_full(ph, pm))
                                else:
                                    with ThreadPoolExecutor(max_workers=batch_n) as pool:
                                        futs = [pool.submit(_run_one_full, ph, pm) for _cs, ph, pm in batch]
                                        for fut in as_completed(futs):
                                            try:
                                                batch_out.append(fut.result())
                                            except Exception:
                                                fail_hist["sim_fail"] += 1
                                for ph, pm, sim in batch_out:
                                    full_sims += 1
                                    full_this_struct += 1
                                    if full_sims == 1 or full_sims % 10 == 0:
                                        _progress(
                                            phase="full_sim",
                                            done=cheap_evals,
                                            total=space_total or cheap_evals,
                                            full_sims=full_sims,
                                            message=(
                                                f"Full sim {full_sims:,} · "
                                                f"cheap {cheap_evals:,}"
                                                + (f"/{space_total:,}" if space_total else "")
                                                + (f" · hard-OK {len(results)}" if results else "")
                                            ),
                                        )
                                    if not sim.success:
                                        fail_hist["sim_fail"] += 1
                                        continue
                                    m = sim.metrics or {}
                                    hard_ok = bool(m.get("hard_constraints_ok", True))
                                    row = _row_from_sim(
                                        sim=sim,
                                        rot_key=rot_key,
                                        n_off=n_off,
                                        min_ps=min_ps,
                                        length=length,
                                        starts=starts,
                                        use_style=use_style,
                                        variations=variations,
                                        ph=ph,
                                        pm=pm,
                                        hard_ok=hard_ok,
                                    )
                                    if _constraint_fail(
                                        m,
                                        require_hard_ok=require_hard_ok,
                                        avoid_flsa_overtime=avoid_flsa_overtime,
                                        cov247=cov247,
                                        use_extra_windows=bool(use_extra_windows and windows),
                                        windows=windows,
                                        annual_hours_hard=annual_hours_hard,
                                        min_ps=int(min_ps),
                                        min_rest_hours=float(min_rest_hours),
                                        max_consecutive_work_days=int(max_consecutive_work_days),
                                    ):
                                        rejected_hard += 1
                                        _record_fail(m)
                                        sc = float(row.get("score") or 0)
                                        if sc > best_miss_score:
                                            best_miss_score = sc
                                            best_miss_row = row
                                        continue
                                    results.append(row)
                                    _note_hard_found()
                                    if found_hard_structural:
                                        rank_pool_remaining -= 1
                                    else:
                                        found_hard_structural = True
                                        rank_pool_remaining = 4
                            if best_miss_row is not None and not found_hard_structural:
                                near_misses.append(best_miss_row)

                            # Expand to full phase model only when priority pass missed hard-OK
                            if (
                                parsed_patterns
                                and stagger_phases
                                and not found_hard_structural
                                and not _cancelled()
                                and not (require_hard_ok and len(results) >= max_hard_results)
                            ):
                                full_phases = generate_phase_layouts(int(n_off), cycle_len, mode="full")
                                seen_ph = {tuple(p) for p in phase_layouts if p is not None}
                                extra_phases = [p for p in full_phases if p is not None and tuple(p) not in seen_ph]
                                if extra_phases:
                                    phase_layouts = extra_phases
                                    candidates = []
                                    for ph in phase_layouts:
                                        if _cancelled():
                                            break
                                        for pm in pat_maps:
                                            cheap_evals += 1
                                            if cheap_evals % 250 == 0:
                                                _progress(
                                                    phase="cheap_expand",
                                                    done=cheap_evals,
                                                    total=space_total or cheap_evals,
                                                    full_sims=full_sims,
                                                    message=(f"Expand phases {cheap_evals:,}"),
                                                )
                                            if ph is not None and pm is not None:
                                                _win_wds2 = _window_weekdays_from_extra(
                                                    windows if use_extra_windows else None
                                                )
                                                day_counts, win_bodies = _day_body_counts(
                                                    parsed_patterns,
                                                    ph,
                                                    pm,
                                                    n_slots=int(n_off),
                                                    simulation_days=int(simulation_days),
                                                    sim_start=sim_start,
                                                    window_weekdays=_win_wds2,
                                                )
                                                body_score = (min(day_counts) if day_counts else 0) * 1000 + (
                                                    min(win_bodies) if win_bodies else 0
                                                ) * 100
                                                try:
                                                    from logic.labor_compliance import (
                                                        flsa_threshold_for_period_days as _flsa_fn2,
                                                    )

                                                    _flsa_thr2 = float(_flsa_fn2(int(flsa_work_period_days or 28)))
                                                except Exception:
                                                    try:
                                                        from config import (
                                                            FLSA_207K_HOURS_THRESHOLD as _flsa_thr2,
                                                        )
                                                    except Exception:
                                                        _flsa_thr2 = 171.0
                                                reason = _cheap_reject(
                                                    parsed_patterns,
                                                    ph,
                                                    pm,
                                                    n_slots=int(n_off),
                                                    shift_length=float(length),
                                                    annual_target=float(annual),
                                                    annual_variance=float(annual_hours_variance),
                                                    annual_hard=bool(annual_hours_hard),
                                                    simulation_days=int(simulation_days),
                                                    cov247=cov247,
                                                    use_windows=bool(use_extra_windows and windows),
                                                    window_min=window_min,
                                                    n_bands=n_bands,
                                                    min_ps=int(min_ps),
                                                    sim_start=sim_start,
                                                    shift_starts=starts,
                                                    extra_windows=windows,
                                                    precomputed=(day_counts, win_bodies),
                                                    nearby_hops=nearby_hops,
                                                    allow_offday_coverage=offday_ok,
                                                    avoid_flsa=bool(avoid_flsa_overtime),
                                                    flsa_period_days=int(flsa_work_period_days or 28),
                                                    flsa_threshold=float(_flsa_thr2),
                                                    max_consecutive_work_days=int(max_consecutive_work_days or 0),
                                                    min_rest_hours=float(min_rest_hours or 0),
                                                    night_minimum=int(night_min or 0),
                                                    rotation_type=str(rot_key or ""),
                                                )
                                                if reason:
                                                    pruned_cheap += 1
                                                    fail_hist["cheap_reject"] += 1
                                                    fail_hist[reason] = fail_hist.get(reason, 0) + 1
                                                    if require_hard_ok:
                                                        rejected_hard += 1
                                                    cheap_score = body_score - float(_cheap_penalty.get(reason, 25_000))
                                                    candidates.append((cheap_score, ph, pm, False))
                                                else:
                                                    candidates.append(
                                                        (
                                                            float(body_score),
                                                            ph,
                                                            pm,
                                                            True,
                                                        )
                                                    )
                                    candidates.sort(key=lambda x: -x[0])
                                    full_queue = []
                                    cheap_pass_kept = 0
                                    cheap_fail_kept = 0
                                    for cheap_score, ph, pm, passed in candidates:
                                        if passed and cheap_pass_kept < max_cheap_pass:
                                            full_queue.append((cheap_score, ph, pm))
                                            cheap_pass_kept += 1
                                        elif not passed and cheap_fail_kept < 5:
                                            full_queue.append((cheap_score, ph, pm))
                                            cheap_fail_kept += 1
                                    rank_pool_remaining = 4
                                    full_this_struct = 0
                                    for cheap_score, ph, pm in full_queue:
                                        if _cancelled():
                                            break
                                        if full_this_struct >= max_full_per_struct:
                                            break
                                        if found_hard_structural and rank_pool_remaining <= 0:
                                            break
                                        cfg = SimulatorConfig(
                                            rotation_type=rot_key,
                                            num_officers=int(n_off),
                                            shift_length_hours=float(length),
                                            annual_hours_target=float(annual),
                                            shift_starts=list(starts),
                                            apply_department_rules=False,
                                            min_per_shift=int(min_ps),
                                            simulation_days=int(simulation_days),
                                            night_minimum=night_min,
                                            annual_hours_variance=float(annual_hours_variance),
                                            annual_hours_hard=bool(annual_hours_hard),
                                            coverage_247=cov247,
                                            avoid_flsa_overtime=bool(avoid_flsa_overtime),
                                            flsa_work_period_days=int(flsa_work_period_days or 28),
                                            use_extra_windows=bool(use_extra_windows and windows),
                                            extra_windows=windows,
                                            auto_min_officers=False,
                                            rotation_style=use_style,
                                            rotation_variations=list(variations),
                                            stagger_phases=False,
                                            phase_overrides=list(ph) if ph is not None else None,
                                            pattern_slot_map=list(pm) if pm is not None else None,
                                            flexible_daily_starts=False,
                                            nearby_start_hops=nearby_hops,
                                            allow_offday_coverage=offday_ok,
                                            min_rest_hours=float(min_rest_hours),
                                            max_consecutive_work_days=int(max_consecutive_work_days),
                                            sim_start_date=sim_start,
                                        )
                                        sim = simulate_schedule(cfg)
                                        full_sims += 1
                                        full_this_struct += 1
                                        if not sim.success:
                                            fail_hist["sim_fail"] += 1
                                            continue
                                        m = sim.metrics or {}
                                        hard_ok = bool(m.get("hard_constraints_ok", True))
                                        row = _row_from_sim(
                                            sim=sim,
                                            rot_key=rot_key,
                                            n_off=n_off,
                                            min_ps=min_ps,
                                            length=length,
                                            starts=starts,
                                            use_style=use_style,
                                            variations=variations,
                                            ph=ph,
                                            pm=pm,
                                            hard_ok=hard_ok,
                                        )
                                        if _constraint_fail(
                                            m,
                                            require_hard_ok=require_hard_ok,
                                            avoid_flsa_overtime=avoid_flsa_overtime,
                                            cov247=cov247,
                                            use_extra_windows=bool(use_extra_windows and windows),
                                            windows=windows,
                                            annual_hours_hard=annual_hours_hard,
                                            min_ps=int(min_ps),
                                            min_rest_hours=float(min_rest_hours),
                                            max_consecutive_work_days=int(max_consecutive_work_days),
                                        ):
                                            rejected_hard += 1
                                            _record_fail(m)
                                            sc = float(row.get("score") or 0)
                                            if sc > best_miss_score:
                                                best_miss_score = sc
                                                best_miss_row = row
                                            continue
                                        results.append(row)
                                        _note_hard_found()
                                        if found_hard_structural:
                                            rank_pool_remaining -= 1
                                        else:
                                            found_hard_structural = True
                                            rank_pool_remaining = 4
                                    if best_miss_row is not None and not found_hard_structural:
                                        near_misses.append(best_miss_row)
                    if _cancelled() or _budget_hit():
                        break
                if _cancelled() or _budget_hit():
                    break
            if _cancelled() or _budget_hit():
                break
        if _cancelled() or _budget_hit():
            break
    # rotation loop ends above

    results.sort(key=lambda r: (0 if r.get("hard_constraints_ok") else 1, -r["score"]))
    near_misses.sort(key=lambda r: -r["score"])

    def _dedupe(rows: List[Dict]) -> List[Dict]:
        out: List[Dict] = []
        seen = set()
        for row in rows:
            ph = row.get("phase_overrides")
            pm = row.get("pattern_slot_map")
            sk = (
                row["rotation_type"],
                row["num_officers"],
                row["min_per_shift"],
                row["shift_length_hours"],
                tuple(row.get("shift_starts") or []),
                tuple(row.get("rotation_variations") or []),
                tuple(ph) if isinstance(ph, (list, tuple)) else ph,
                tuple(pm) if isinstance(pm, (list, tuple)) else pm,
                tuple(row.get("failed_constraints") or []),
            )
            if sk in seen:
                continue
            seen.add(sk)
            out.append(row)
        return out

    results = diversify_ranked(_dedupe(results), limit=24)
    near_misses = _dedupe(near_misses)[:20]

    def _finalize(rows: List[Dict], *, near: bool = False) -> None:
        for i, row in enumerate(rows, 1):
            m = row.get("metrics") or {}
            zero_gaps = int(
                m.get("gap_events")
                if m.get("gap_events") is not None
                else (m.get("zero_staff_slots") or m.get("coverage_gap_count") or 0)
            )
            night_fails = int(m.get("night_minimum_failures") or m.get("night_risk_gaps") or 0)
            flsa_fails = int(m.get("flsa_violations") or 0)
            win_fails = int(m.get("extra_window_failures") or 0)
            c247_fails = int(m.get("coverage_247_failures") or 0)
            hours_delta = abs(float(m.get("avg_annual_hours") or annual) - annual)
            spread = float(m.get("annual_hours_spread") or 0)
            row["rank"] = i
            bits = [
                str(row["rotation_type"]),
                f"{row['num_officers']} Officers",
                f"Min {row['min_per_shift']} Per Shift",
            ]
            if near and row.get("failed_constraints"):
                labels = [CONSTRAINT_LABELS.get(k, k) for k in row["failed_constraints"]]
                bits.append("Misses: " + ", ".join(labels))
            if zero_gaps:
                bits.append(f"Coverage Gaps {zero_gaps}")
            if night_fails:
                bits.append(f"Night Short {night_fails}")
            if flsa_fails:
                bits.append(f"FLSA Over Cap {flsa_fails}")
            if win_fails:
                bits.append(f"Window Short {win_fails}")
            if c247_fails:
                bits.append(f"24/7 Short {c247_fails}")
            if hours_delta >= 1:
                bits.append(f"Annual Mean Off ~{hours_delta:.0f}h")
            if spread >= 1:
                bits.append(f"Officer Hours Spread ~{spread:.0f}h")
            if not near and not zero_gaps and row.get("hard_constraints_ok"):
                bits.append("Meets Selected Constraints")
            row["summary"] = " · ".join(bits)
            row["_internal_score"] = row.pop("score", None)
            row["human_metrics"] = {
                "zero_staff_gaps": zero_gaps,
                "night_minimum_failures": night_fails,
                "flsa_violations": flsa_fails,
                "extra_window_failures": win_fails,
                "coverage_247_failures": c247_fails,
                "annual_hours_delta": round(hours_delta, 1),
                "annual_hours_spread": round(spread, 1),
                "num_officers": row["num_officers"],
                "min_per_shift": row["min_per_shift"],
                "rotation_type": row["rotation_type"],
                "hard_constraints_ok": row.get("hard_constraints_ok"),
                "failed_constraints": list(row.get("failed_constraints") or []),
            }

    _finalize(results)
    _finalize(near_misses, near=True)

    # Cost / FLSA / fairness meters on ranked + near-miss cards
    try:
        from logic.staffing_insights import enrich_ranked_economics

        results = enrich_ranked_economics(results)
        near_misses = enrich_ranked_economics(near_misses)
    except Exception:
        pass

    # Soft rank among hard-OK only (prefs never override hard feasibility)
    soft_msg = None
    soft_prefs_used = None
    wave2_meta: Dict = {}
    try:
        from logic.soft_rank import rank_soft_among_feasible

        _soft = rank_soft_among_feasible(
            results,
            soft_prefs if isinstance(soft_prefs, dict) else None,
        )
        soft_ok = [r for r in (_soft.get("ranked") or []) if r.get("hard_constraints_ok")]
        if soft_ok:
            results = soft_ok
        soft_msg = _soft.get("message")
        soft_prefs_used = _soft.get("prefs_used")
    except Exception:
        soft_msg = None
        soft_prefs_used = None

    # Wave 2: Pareto labels, fatigue, FLSA meters, counterfactuals, rank delta
    try:
        from logic.sim_wave2 import enrich_wave2_result

        _w2 = enrich_wave2_result(
            {"ranked": results, "near_misses": near_misses, "success": bool(results)},
            {
                "officers": (axes.get("officer_counts") or [None])[0],
                "cov247": cov247,
                "windows": windows if use_extra_windows else [],
            },
        )
        if _w2.get("ranked"):
            results = [r for r in _w2["ranked"] if r.get("hard_constraints_ok")] or list(_w2["ranked"])
        wave2_meta = {
            "soft_rank_delta": _w2.get("soft_rank_delta"),
            "counterfactual_unlocks": _w2.get("counterfactual_unlocks") or [],
            "pareto_champions": _w2.get("pareto_champions") or {},
        }
        if _w2.get("message") and soft_msg and "Pareto" in str(_w2.get("message")):
            soft_msg = _w2["message"]
        elif _w2.get("soft_rank_delta"):
            soft_msg = (soft_msg + " · " if soft_msg else "") + str(_w2["soft_rank_delta"])
    except Exception:
        wave2_meta = {}

    wall_ms = int((time.perf_counter() - t0) * 1000)
    total_eval = cheap_evals
    best = results[0] if results else None

    if cancelled:
        msg = f"Search Cancelled After {total_eval:,} Cheap Checks · {full_sims:,} Full Sims"
        if best:
            msg += (
                f" — Best So Far: {best['rotation_type']} · "
                f"{best['num_officers']} Officers · Min {best['min_per_shift']} Per Shift"
            )
    elif best:
        msg = (
            f"Best Option: {best['rotation_type']} · {best['num_officers']} Officers · "
            f"Min {best['min_per_shift']} Per Shift"
        )
    elif near_misses:
        msg = (
            "No Schedule Meets Every Hard Constraint — "
            f"showing {len(near_misses)} closest alternative(s). "
            "Adjust constraint priorities and search again."
        )
    else:
        msg = "No Schedule Meets The Selected Hard Constraints"
    if rejected_hard and best and not cancelled:
        msg += f" · {rejected_hard} Ruled Out By Hard Constraints"
    elif rejected_hard and not best:
        msg += f" ({rejected_hard} Combinations Ruled Out)"
    # Honest anytime / soft-exhaustive stop (UI progress + banner)
    if not cancelled and (search_truncated or budget_exhausted):
        if budget_exhausted:
            msg += f" · Search time limit ({int(anytime_wall)}s) — best so far"
        elif prefer_exhaustive:
            msg += " · Partial scan (stopped after hard matches)"
        else:
            msg += " · Partial scan (not every layout checked)"
    if soft_msg and best and best.get("hard_constraints_ok"):
        msg = f"{msg} · {soft_msg}" if msg else soft_msg

    if require_hard_ok:
        success = bool(results)
        grouped = {}
        for r in results:
            # Group by (rotation_type, num_officers, shift_length) so different N
            # values for the same rotation type both surface in the ranked list.
            starts_k = tuple(r.get("shift_starts") or [])
            vars_k = tuple(r.get("rotation_variations") or [])
            gk = (r["rotation_type"], r["num_officers"], r["shift_length_hours"], starts_k, vars_k)
            if gk not in grouped:
                grouped[gk] = r
        ranked = list(grouped.values())[:15]
        best_out = best
    else:
        source_list = results if results else near_misses
        grouped = {}
        for r in source_list:
            starts_k = tuple(r.get("shift_starts") or [])
            vars_k = tuple(r.get("rotation_variations") or [])
            gk = (r["rotation_type"], r["num_officers"], r["shift_length_hours"], starts_k, vars_k)
            if gk not in grouped:
                grouped[gk] = r
        ranked = list(grouped.values())[:15]
        best_out = ranked[0] if ranked else None
        success = bool(best_out)

    _progress(
        phase="done",
        done=total_eval,
        total=space_total or total_eval,
        full_sims=full_sims,
        message=msg,
        success=success,
        cancelled=cancelled,
    )

    return {
        "success": success,
        "cancelled": cancelled,
        "scenarios_evaluated": total_eval,
        "scenarios_kept": len(results),
        "rejected_hard_constraints": rejected_hard,
        "outer_configs": outer_configs,
        "inner_trials": total_eval,
        "full_sims_run": full_sims,
        "pruned_cheap": pruned_cheap,
        "search_exhaustive": bool(
            not cancelled and not budget_exhausted and not search_truncated and prefer_exhaustive
        ),
        "budget_exhausted": bool(budget_exhausted),
        "search_truncated": bool(search_truncated or budget_exhausted),
        "wall_time_ms": wall_ms,
        "failure_histogram": fail_hist,
        "space_estimate": space,
        "space_note": space.get("warning") or "",
        "domain_report": domain_reduction_report(axes),
        "bind_reasons": list(axes.get("bind_reasons") or []),
        "constraint_weights": weights,
        "constraint_priority": list(constraint_priority or []),
        "soft_prefs": soft_prefs_used,
        "soft_rank": {
            "applied": bool(soft_prefs_used and best and best.get("hard_constraints_ok")),
            "message": soft_msg,
            "delta": (wave2_meta or {}).get("soft_rank_delta"),
        },
        "soft_rank_delta": (wave2_meta or {}).get("soft_rank_delta"),
        "counterfactual_unlocks": (wave2_meta or {}).get("counterfactual_unlocks") or [],
        "pareto_champions": (wave2_meta or {}).get("pareto_champions") or {},
        "near_misses": near_misses,
        "best": best_out,
        "ranked": ranked,
        "message": msg,
        "impossible": require_hard_ok and not results,
        "constraints_applied": {
            "coverage_247": cov247,
            "avoid_flsa_overtime": bool(avoid_flsa_overtime),
            "use_extra_windows": bool(use_extra_windows and windows),
            "extra_window_count": len(windows) if use_extra_windows else 0,
            "simulation_days": int(simulation_days),
            "rotation_types": list(axes["rotation_types"]),
            "officer_counts": list(axes["officer_counts"]),
            "min_per_shift_options": list(axes["min_per_shift_options"]),
            "shift_starts_options": axes["locked_starts_opts"]
            if axes["locked_starts_opts"] is not None
            else ["<all modeled packs for free starts>"],
            "shift_length_options": axes["length_opts"],
            "rotation_style": style,
            "rotation_variations": list(axes["base_variations"]),
            "variation_sets": len(axes["variation_sets"]),
            "annual_hours_target": annual,
            "search_mode": "exhaustive" if prefer_exhaustive and not search_truncated else "anytime",
            "constraint_weights": weights,
            "bind_reasons": list(axes.get("bind_reasons") or []),
        },
    }
