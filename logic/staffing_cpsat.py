"""
Optional CP-SAT helpers for staffing simulator seeds.

Does not replace simulate_schedule (FLSA, annual, windows truth).
Missing ortools → pure-Python finite candidates only.

Seeds:
1. Joint phase + pattern-map (max min-daily ON + window weekday floors)
2. Start-pack rank / band feasibility given body count
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple


def ortools_available() -> bool:
    try:
        from logic.cp_sat_bridge import ortools_available as _av

        return bool(_av())
    except Exception:
        return False


def even_phase_layout(n_officers: int, cycle_length: int) -> Optional[List[int]]:
    if n_officers < 1 or cycle_length < 1:
        return None
    step = max(1, cycle_length // max(1, n_officers))
    return [(i * step) % cycle_length for i in range(int(n_officers))]


def default_pattern_map(n_officers: int, n_patterns: int) -> List[int]:
    n_pat = max(1, int(n_patterns))
    return [i % n_pat for i in range(int(n_officers))]


def _normalize_duty_rings(
    duty_rings: Optional[Sequence[Sequence[bool]]],
    *,
    cycle_length: int,
) -> List[List[bool]]:
    """One bool ring per pattern; pad/trim to cycle_length."""
    if not duty_rings:
        return [[True] * max(1, int(cycle_length))]
    rings: List[List[bool]] = []
    c = max(1, int(cycle_length))
    for ring in duty_rings:
        vec = [bool(x) for x in ring]
        if not vec:
            vec = [True]
        if len(vec) < c:
            reps = (c + len(vec) - 1) // len(vec)
            vec = (vec * reps)[:c]
        else:
            vec = vec[:c]
        rings.append(vec)
    return rings


def _day_on_counts(
    phases: Sequence[int],
    rings: Sequence[Sequence[bool]],
    pat_map: Sequence[int],
) -> List[int]:
    if not phases or not rings:
        return []
    c = len(rings[0])
    n = len(phases)
    out: List[int] = []
    for d in range(c):
        on = 0
        for i in range(n):
            ring = rings[int(pat_map[i]) % len(rings)]
            phase = int(phases[i]) % c
            if ring[(d + phase) % c]:
                on += 1
        out.append(on)
    return out


def _min_daily_on(phases: Sequence[int], rings: Sequence[Sequence[bool]], pat_map: Sequence[int]) -> int:
    counts = _day_on_counts(phases, rings, pat_map)
    return min(counts) if counts else 0


def _window_day_floors(
    *,
    cycle_length: int,
    sim_start_weekday: int,
    window_weekday_floors: Optional[Sequence[Tuple[int, int]]],
) -> List[int]:
    """
    Per cycle day index → body floor from window weekdays.

    window_weekday_floors: (weekday 0=Mon .. 6=Sun, min_bodies)
    """
    c = max(1, int(cycle_length))
    floors = [0] * c
    if not window_weekday_floors:
        return floors
    base = int(sim_start_weekday) % 7
    # Max floor if same weekday appears multiple times (take max need)
    by_wd: Dict[int, int] = {}
    for wd, need in window_weekday_floors:
        try:
            wdi = int(wd) % 7
            n = max(0, int(need))
        except (TypeError, ValueError):
            continue
        by_wd[wdi] = max(by_wd.get(wdi, 0), n)
    for d in range(c):
        wd = (base + d) % 7
        floors[d] = by_wd.get(wd, 0)
    return floors


def windows_to_weekday_floors(extra_windows: Optional[Sequence[Dict[str, Any]]]) -> List[Tuple[int, int]]:
    """Extract (weekday, min_officers) from simulator window dicts."""
    out: List[Tuple[int, int]] = []
    for w in extra_windows or []:
        if not isinstance(w, dict) or not w.get("enabled", True):
            continue
        try:
            need = int(w.get("min_officers") or 0)
        except (TypeError, ValueError):
            need = 0
        if need <= 0:
            continue
        # weekday may be int or list
        raw = w.get("weekday", w.get("weekdays", w.get("dow")))
        if raw is None:
            # All days of week if unspecified
            for d in range(7):
                out.append((d, need))
            continue
        if isinstance(raw, (list, tuple, set)):
            for item in raw:
                try:
                    out.append((int(item) % 7, need))
                except (TypeError, ValueError):
                    continue
        else:
            try:
                out.append((int(raw) % 7, need))
            except (TypeError, ValueError):
                continue
    return out


def optimize_joint_phase_pattern(
    *,
    n_officers: int,
    cycle_length: int,
    duty_rings: Optional[Sequence[Sequence[bool]]] = None,
    pattern_map: Optional[Sequence[int]] = None,
    free_pattern_map: bool = True,
    min_daily_on: int = 0,
    window_weekday_floors: Optional[Sequence[Tuple[int, int]]] = None,
    sim_start_weekday: int = 0,
    time_limit_sec: float = 3.0,
) -> Optional[Tuple[List[int], List[int]]]:
    """
    Joint phase + pattern-map seed.

    Maximizes: min_all_ON * 1000 + min_window_day_ON * 100 + sum(daily ON)
    Hard floors: min_daily_on every day; per-day floors from window weekdays.
    If pattern_map locked (free_pattern_map=False), only phases vary.
    """
    n = int(n_officers)
    c = int(cycle_length)
    if n < 1 or c < 1:
        return None

    rings = _normalize_duty_rings(duty_rings, cycle_length=c)
    n_pat = len(rings)
    floor_all = max(0, int(min_daily_on or 0))
    day_floors = _window_day_floors(
        cycle_length=c,
        sim_start_weekday=sim_start_weekday,
        window_weekday_floors=window_weekday_floors,
    )
    # Effective hard floor per day
    hard_floor = [max(floor_all, day_floors[d]) for d in range(c)]
    window_days = [d for d in range(c) if day_floors[d] > 0]

    lock_map: Optional[List[int]] = None
    if pattern_map is not None and not free_pattern_map:
        lock_map = [int(x) % n_pat for x in pattern_map][:n]
        while len(lock_map) < n:
            lock_map.append(len(lock_map) % n_pat)
    elif not free_pattern_map or n_pat == 1:
        lock_map = default_pattern_map(n, n_pat)

    if not ortools_available():
        return _python_best_joint(n, c, rings, lock_map, hard_floor, window_days)

    try:
        from ortools.sat.python import cp_model
    except Exception:
        return _python_best_joint(n, c, rings, lock_map, hard_floor, window_days)

    model = cp_model.CpModel()
    # Element encoding (fast): phase/pat IntVars + per-day ON table lookup
    phase_vars = [model.NewIntVar(0, c - 1, f"ph_{i}") for i in range(n)]
    pat_vars: Optional[List] = None
    if lock_map is None:
        pat_vars = [model.NewIntVar(0, n_pat - 1, f"pat_{i}") for i in range(n)]

    cover_vars = []
    for d in range(c):
        on_terms = []
        for i in range(n):
            on_i = model.NewIntVar(0, 1, f"on_{i}_{d}")
            if lock_map is not None:
                ring = rings[lock_map[i]]
                table = [1 if ring[(d + p) % c] else 0 for p in range(c)]
                model.AddElement(phase_vars[i], table, on_i)
            else:
                assert pat_vars is not None
                # index = pat * c + phase → duty[pat][(d+phase)%c]
                table: List[int] = []
                for k in range(n_pat):
                    ring = rings[k]
                    for p in range(c):
                        table.append(1 if ring[(d + p) % c] else 0)
                idx = model.NewIntVar(0, n_pat * c - 1, f"idx_{i}_{d}")
                model.Add(idx == pat_vars[i] * c + phase_vars[i])
                model.AddElement(idx, table, on_i)
            on_terms.append(on_i)
        if not on_terms:
            if hard_floor[d] > 0:
                return _soften_joint(
                    n=n,
                    c=c,
                    rings=rings,
                    lock_map=lock_map,
                    hard_floor=hard_floor,
                    window_days=window_days,
                    floor_all=floor_all,
                    window_weekday_floors=window_weekday_floors,
                    sim_start_weekday=sim_start_weekday,
                    time_limit_sec=time_limit_sec,
                )
            cover = model.NewConstant(0)
        else:
            cover = model.NewIntVar(0, n, f"cover_{d}")
            model.Add(cover == sum(on_terms))
        cover_vars.append(cover)
        if hard_floor[d] > 0:
            model.Add(cover >= hard_floor[d])

    min_all = model.NewIntVar(0, n, "min_all")
    for cv in cover_vars:
        model.Add(min_all <= cv)

    if window_days:
        min_win = model.NewIntVar(0, n, "min_win")
        for d in window_days:
            model.Add(min_win <= cover_vars[d])
    else:
        min_win = model.NewConstant(0)

    sum_cover = sum(cover_vars)
    # Lex-ish hard floors first; soft: coverage sum + pattern-map equity (P9)
    # Imbalance penalty only when free pattern map (never overrides hard floors).
    soft_equity = model.NewConstant(0)
    if pat_vars is not None and n_pat >= 2:
        max_pc = model.NewIntVar(0, n, "max_pc")
        min_pc = model.NewIntVar(0, n, "min_pc")
        model.Add(min_pc <= max_pc)
        for k in range(n_pat):
            bits = []
            for i in range(n):
                b = model.NewBoolVar(f"is_pat_{i}_{k}")
                model.Add(pat_vars[i] == k).OnlyEnforceIf(b)
                model.Add(pat_vars[i] != k).OnlyEnforceIf(b.Not())
                bits.append(b)
            cnt = model.NewIntVar(0, n, f"pat_cnt_{k}")
            model.Add(cnt == sum(bits))
            model.Add(max_pc >= cnt)
            model.Add(min_pc <= cnt)
        imb = model.NewIntVar(0, n, "pat_imb")
        model.Add(imb == max_pc - min_pc)
        soft_equity = imb
    # Maximize: min_all >> min_win >> sum_cover; soft subtract pattern imbalance
    model.Maximize(min_all * 1_000_000 + min_win * 1_000 + sum_cover * 10 - soft_equity * 50)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(time_limit_sec)
    solver.parameters.num_search_workers = 1
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return _soften_joint(
            n=n,
            c=c,
            rings=rings,
            lock_map=lock_map,
            hard_floor=hard_floor,
            window_days=window_days,
            floor_all=floor_all,
            window_weekday_floors=window_weekday_floors,
            sim_start_weekday=sim_start_weekday,
            time_limit_sec=time_limit_sec,
        )

    phases = [int(solver.Value(phase_vars[i])) for i in range(n)]
    if lock_map is not None:
        pmap = list(lock_map)
    else:
        assert pat_vars is not None
        pmap = [int(solver.Value(pat_vars[i])) for i in range(n)]
    # Keep finite Python best if it strictly beats incomplete CP-SAT on min_all
    py = _python_best_joint(n, c, rings, lock_map, hard_floor, window_days)
    if py is not None:
        py_counts = _day_on_counts(py[0], rings, py[1])
        cp_counts = _day_on_counts(phases, rings, pmap)
        if py_counts and cp_counts:
            py_key = (
                min(py_counts),
                min(py_counts[d] for d in window_days) if window_days else min(py_counts),
                sum(py_counts),
            )
            cp_key = (
                min(cp_counts),
                min(cp_counts[d] for d in window_days) if window_days else min(cp_counts),
                sum(cp_counts),
            )
            if py_key > cp_key:
                return py
    return phases, pmap


def _soften_joint(
    *,
    n: int,
    c: int,
    rings: List[List[bool]],
    lock_map: Optional[List[int]],
    hard_floor: List[int],
    window_days: List[int],
    floor_all: int,
    window_weekday_floors: Optional[Sequence[Tuple[int, int]]],
    sim_start_weekday: int,
    time_limit_sec: float,
) -> Optional[Tuple[List[int], List[int]]]:
    """Drop hard floors stepwise: window-only → all-floor 0."""
    # 1) window floors only (no universal floor)
    if floor_all > 0 or any(hard_floor):
        day_floors = _window_day_floors(
            cycle_length=c,
            sim_start_weekday=sim_start_weekday,
            window_weekday_floors=window_weekday_floors,
        )
        if any(day_floors) and (floor_all > 0 or max(hard_floor) > max(day_floors)):
            got = optimize_joint_phase_pattern(
                n_officers=n,
                cycle_length=c,
                duty_rings=rings,
                pattern_map=lock_map,
                free_pattern_map=lock_map is None,
                min_daily_on=0,
                window_weekday_floors=window_weekday_floors,
                sim_start_weekday=sim_start_weekday,
                time_limit_sec=time_limit_sec,
            )
            if got is not None:
                return got
        # 2) no floors
        if max(hard_floor) > 0 or floor_all > 0:
            return optimize_joint_phase_pattern(
                n_officers=n,
                cycle_length=c,
                duty_rings=rings,
                pattern_map=lock_map,
                free_pattern_map=lock_map is None,
                min_daily_on=0,
                window_weekday_floors=None,
                sim_start_weekday=sim_start_weekday,
                time_limit_sec=time_limit_sec,
            )
    return _python_best_joint(n, c, rings, lock_map, [0] * c, window_days)


def _python_best_joint(
    n: int,
    c: int,
    rings: Sequence[Sequence[bool]],
    lock_map: Optional[List[int]],
    hard_floor: Sequence[int],
    window_days: Sequence[int],
) -> Optional[Tuple[List[int], List[int]]]:
    """Finite candidates: even phases × simple pattern maps."""
    n_pat = len(rings)
    phase_cands: List[List[int]] = []
    step = max(1, c // max(n, 1))
    for offset in range(c):
        phase_cands.append([(i * step + offset) % c for i in range(n)])
    half = max(1, c // 2)
    phase_cands.append([(i * half) % c for i in range(n)])
    phase_cands.append([0] * n)
    phase_cands.append([i % c for i in range(n)])

    if lock_map is not None:
        maps = [list(lock_map)]
    else:
        maps = [
            default_pattern_map(n, n_pat),
            [0] * n,
            [(n_pat - 1) if n_pat else 0] * n if n_pat > 1 else default_pattern_map(n, n_pat),
            [0] * (n // 2) + [1 % n_pat] * (n - n // 2),
            [1 % n_pat] * (n // 2) + [0] * (n - n // 2),
        ]

    best: Optional[Tuple[List[int], List[int]]] = None
    best_key = (-1, -1, -1)
    for ph in phase_cands:
        for pm in maps:
            counts = _day_on_counts(ph, rings, pm)
            if not counts:
                continue
            if any(counts[d] < hard_floor[d] for d in range(c) if hard_floor[d] > 0):
                continue
            min_all = min(counts)
            min_win = min(counts[d] for d in window_days) if window_days else min_all
            total = sum(counts)
            key = (min_all, min_win, total)
            if key > best_key:
                best_key = key
                best = (list(ph), list(pm))
    if best is not None:
        return best
    # Relax floors
    for ph in phase_cands:
        for pm in maps:
            counts = _day_on_counts(ph, rings, pm)
            if not counts:
                continue
            min_all = min(counts)
            min_win = min(counts[d] for d in window_days) if window_days else min_all
            total = sum(counts)
            key = (min_all, min_win, total)
            if key > best_key:
                best_key = key
                best = (list(ph), list(pm))
    if best is not None:
        return best
    ph0 = even_phase_layout(n, c) or [0] * n
    return ph0, (lock_map or default_pattern_map(n, n_pat))


# Backward-compatible phase-only API
def optimize_phases_max_min_on(
    *,
    n_officers: int,
    cycle_length: int,
    duty_rings: Optional[Sequence[Sequence[bool]]] = None,
    pattern_map: Optional[Sequence[int]] = None,
    min_daily_on: int = 0,
    time_limit_sec: float = 2.0,
) -> Optional[List[int]]:
    """Phase-only (pattern map locked to arg or alternating default)."""
    rings = _normalize_duty_rings(duty_rings, cycle_length=int(cycle_length))
    n_pat = len(rings)
    locked = (
        list(pattern_map)[: int(n_officers)] if pattern_map is not None else default_pattern_map(int(n_officers), n_pat)
    )
    got = optimize_joint_phase_pattern(
        n_officers=n_officers,
        cycle_length=cycle_length,
        duty_rings=rings,
        pattern_map=locked,
        free_pattern_map=False,
        min_daily_on=min_daily_on,
        window_weekday_floors=None,
        time_limit_sec=time_limit_sec,
    )
    return got[0] if got else None


def suggest_phase_layout(
    *,
    n_officers: int,
    cycle_length: int,
    n_patterns: int = 1,
    duty_rings: Optional[Sequence[Sequence[bool]]] = None,
    pattern_map: Optional[Sequence[int]] = None,
    min_daily_on: int = 0,
    time_limit_sec: float = 2.0,
    window_weekday_floors: Optional[Sequence[Tuple[int, int]]] = None,
    sim_start_weekday: int = 0,
    free_pattern_map: bool = True,
) -> Optional[List[int]]:
    """Phase seed only (pattern via suggest_joint_seed)."""
    del n_patterns
    joint = suggest_joint_seed(
        n_officers=n_officers,
        cycle_length=cycle_length,
        duty_rings=duty_rings,
        pattern_map=pattern_map,
        min_daily_on=min_daily_on,
        time_limit_sec=time_limit_sec,
        window_weekday_floors=window_weekday_floors,
        sim_start_weekday=sim_start_weekday,
        free_pattern_map=free_pattern_map,
    )
    if joint is not None:
        return joint[0]
    return even_phase_layout(n_officers, cycle_length)


def suggest_joint_seed(
    *,
    n_officers: int,
    cycle_length: int,
    duty_rings: Optional[Sequence[Sequence[bool]]] = None,
    pattern_map: Optional[Sequence[int]] = None,
    min_daily_on: int = 0,
    time_limit_sec: float = 3.0,
    window_weekday_floors: Optional[Sequence[Tuple[int, int]]] = None,
    sim_start_weekday: int = 0,
    free_pattern_map: bool = True,
) -> Optional[Tuple[List[int], List[int]]]:
    """Return (phases, pattern_map) seed or None."""
    if not duty_rings and pattern_map is None:
        ph = even_phase_layout(n_officers, cycle_length)
        if ph is None:
            return None
        return ph, default_pattern_map(n_officers, 1)
    return optimize_joint_phase_pattern(
        n_officers=n_officers,
        cycle_length=cycle_length,
        duty_rings=duty_rings,
        pattern_map=pattern_map,
        free_pattern_map=free_pattern_map and pattern_map is None,
        min_daily_on=min_daily_on,
        window_weekday_floors=window_weekday_floors,
        sim_start_weekday=sim_start_weekday,
        time_limit_sec=time_limit_sec,
    )


def phase_quality(
    phases: Sequence[int],
    duty_rings: Sequence[Sequence[bool]],
    *,
    pattern_map: Optional[Sequence[int]] = None,
    sim_start_weekday: int = 0,
    window_weekday_floors: Optional[Sequence[Tuple[int, int]]] = None,
) -> Tuple[int, float, int]:
    """Return (min_daily_on, mean_daily_on, min_window_day_on)."""
    if not phases or not duty_rings:
        return 0, 0.0, 0
    rings = _normalize_duty_rings(duty_rings, cycle_length=len(duty_rings[0]))
    n = len(phases)
    if pattern_map is None:
        pat_map = default_pattern_map(n, len(rings))
    else:
        pat_map = [int(x) % len(rings) for x in pattern_map][:n]
        while len(pat_map) < n:
            pat_map.append(len(pat_map) % len(rings))
    counts = _day_on_counts(phases, rings, pat_map)
    if not counts:
        return 0, 0.0, 0
    day_floors = _window_day_floors(
        cycle_length=len(counts),
        sim_start_weekday=sim_start_weekday,
        window_weekday_floors=window_weekday_floors,
    )
    win_days = [d for d, f in enumerate(day_floors) if f > 0]
    min_win = min(counts[d] for d in win_days) if win_days else min(counts)
    return min(counts), (sum(counts) / len(counts)), min_win


# ---------------------------------------------------------------------------
# Start-band / pack seed
# ---------------------------------------------------------------------------


def _hhmm_to_min(hhmm: str) -> int:
    parts = str(hhmm or "00:00").strip().split(":")
    try:
        h = int(parts[0])
        m = int(parts[1]) if len(parts) > 1 else 0
    except (TypeError, ValueError):
        return 0
    return (h % 24) * 60 + (m % 60)


def _shift_covers_minute(start_min: int, length_min: int, minute: int) -> bool:
    end = start_min + length_min
    if end <= 24 * 60:
        return start_min <= minute < end
    # overnight
    return minute >= start_min or minute < (end % (24 * 60))


def _window_samples(win_start: str, win_end: str, step: int = 30) -> List[int]:
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
    return samples or [ws]


def pack_band_cover_matrix(
    starts: Sequence[str],
    shift_length_hours: float,
    sample_minutes: Sequence[int],
) -> List[List[int]]:
    """cover[b][s] = 1 if band b covers sample s."""
    length_min = max(30, int(round(float(shift_length_hours) * 60)))
    start_mins = [_hhmm_to_min(s) for s in starts]
    mat: List[List[int]] = []
    for sm in start_mins:
        mat.append([1 if _shift_covers_minute(sm, length_min, m) else 0 for m in sample_minutes])
    return mat


def start_pack_body_feasible(
    starts: Sequence[str],
    *,
    shift_length_hours: float,
    n_bodies: int,
    coverage_247: int = 0,
    extra_windows: Optional[Sequence[Dict[str, Any]]] = None,
    min_per_shift: int = 0,
    time_limit_sec: float = 1.0,
) -> bool:
    """
    CP-SAT: can n_bodies officers assigned to starts meet 24/7 + windows?

    One-day body snapshot (thin-day seed). Full sim still truth.
    """
    bands = list(starts)
    b = len(bands)
    n = int(n_bodies)
    if b < 1 or n < 1:
        return False
    cov = max(0, int(coverage_247 or 0))
    mps = max(0, int(min_per_shift or 0))

    # Samples: full day if 24/7; window samples; always a few anchors
    samples: List[int] = []
    if cov > 0:
        samples.extend(list(range(0, 24 * 60, 30)))
    for w in extra_windows or []:
        if not isinstance(w, dict) or not w.get("enabled", True):
            continue
        try:
            need = int(w.get("min_officers") or 0)
        except (TypeError, ValueError):
            need = 0
        if need <= 0:
            continue
        samples.extend(
            _window_samples(
                str(w.get("start_time") or "00:00"),
                str(w.get("end_time") or "23:59"),
            )
        )
    if not samples:
        samples = [0, 6 * 60, 12 * 60, 18 * 60, 22 * 60]
    # unique preserve order
    seen = set()
    uniq_samples: List[int] = []
    for m in samples:
        if m not in seen:
            seen.add(m)
            uniq_samples.append(m)

    cover = pack_band_cover_matrix(bands, shift_length_hours, uniq_samples)

    if not ortools_available():
        # Heuristic: each sample needs enough covering bands * stack
        for si, _m in enumerate(uniq_samples):
            need = cov
            for w in extra_windows or []:
                if not isinstance(w, dict) or not w.get("enabled", True):
                    continue
                try:
                    wneed = int(w.get("min_officers") or 0)
                except (TypeError, ValueError):
                    wneed = 0
                if wneed <= 0:
                    continue
                st = _hhmm_to_min(str(w.get("start_time") or "00:00"))
                en = _hhmm_to_min(str(w.get("end_time") or "23:59"))
                mm = uniq_samples[si]
                in_win = (st <= mm < en) if en > st else (mm >= st or mm < en)
                if in_win:
                    need = max(need, wneed)
            covering = sum(1 for bi in range(b) if cover[bi][si])
            if covering < 1 and need > 0:
                return False
            if need > n:
                return False
        return True

    try:
        from ortools.sat.python import cp_model
    except Exception:
        return True

    model = cp_model.CpModel()
    # x[i, band] officer i → band
    x = []
    for i in range(n):
        row = [model.NewBoolVar(f"s_{i}_{j}") for j in range(b)]
        model.AddExactlyOne(row)
        x.append(row)

    band_count = []
    for j in range(b):
        cnt = model.NewIntVar(0, n, f"bc_{j}")
        model.Add(cnt == sum(x[i][j] for i in range(n)))
        band_count.append(cnt)
        if mps > 0:
            # Soft: unused bands OK (thin day) — only if used, but we can't
            # express easily; skip hard mps on seed
            pass

    for si, _m in enumerate(uniq_samples):
        need = cov
        for w in extra_windows or []:
            if not isinstance(w, dict) or not w.get("enabled", True):
                continue
            try:
                wneed = int(w.get("min_officers") or 0)
            except (TypeError, ValueError):
                wneed = 0
            if wneed <= 0:
                continue
            st = _hhmm_to_min(str(w.get("start_time") or "00:00"))
            en = _hhmm_to_min(str(w.get("end_time") or "23:59"))
            mm = uniq_samples[si]
            in_win = (st <= mm < en) if en > st else (mm >= st or mm < en)
            if in_win:
                need = max(need, wneed)
        if need <= 0:
            continue
        covering = [band_count[j] for j in range(b) if cover[j][si]]
        if not covering:
            return False
        model.Add(sum(covering) >= need)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(time_limit_sec)
    solver.parameters.num_search_workers = 1
    status = solver.Solve(model)
    return status in (cp_model.OPTIMAL, cp_model.FEASIBLE)


def rank_start_packs_seed(
    packs: Sequence[Sequence[str]],
    *,
    shift_length_hours: float,
    n_bodies: int,
    coverage_247: int = 0,
    extra_windows: Optional[Sequence[Dict[str, Any]]] = None,
    min_per_shift: int = 0,
    max_keep: int = 48,
) -> List[List[str]]:
    """
    Re-order start packs: feasible-with-bodies first, then band capacity score.
    """
    if not packs:
        return []
    scored: List[Tuple[int, int, int, List[str]]] = []
    for pack in packs:
        p = list(pack)
        if len(p) < 2:
            continue
        feasible = start_pack_body_feasible(
            p,
            shift_length_hours=shift_length_hours,
            n_bodies=n_bodies,
            coverage_247=coverage_247,
            extra_windows=extra_windows,
            min_per_shift=min_per_shift,
            time_limit_sec=0.5,
        )
        # Capacity score: sum of window thin-band counts + 247 cover
        cap = 0
        length = float(shift_length_hours)
        if coverage_247 > 0:
            for m in range(0, 24 * 60, 60):
                cover_n = sum(
                    1
                    for s in p
                    if _shift_covers_minute(
                        _hhmm_to_min(s),
                        max(30, int(round(length * 60))),
                        m,
                    )
                )
                cap += cover_n
        for w in extra_windows or []:
            if not isinstance(w, dict) or not w.get("enabled", True):
                continue
            samples = _window_samples(
                str(w.get("start_time") or "00:00"),
                str(w.get("end_time") or "23:59"),
            )
            for m in samples:
                cover_n = sum(
                    1
                    for s in p
                    if _shift_covers_minute(
                        _hhmm_to_min(s),
                        max(30, int(round(length * 60))),
                        m,
                    )
                )
                cap += cover_n * 3
        scored.append((1 if feasible else 0, cap, len(p), p))

    scored.sort(key=lambda t: (-t[0], -t[1], -t[2], ",".join(t[3])))
    out = [t[3] for t in scored[: max(1, int(max_keep))]]
    return out if out else [list(p) for p in packs[:max_keep]]


def assign_officers_to_starts(
    n_bodies: int,
    starts: Sequence[str],
    *,
    shift_length_hours: float,
    coverage_247: int = 0,
    extra_windows: Optional[Sequence[Dict[str, Any]]] = None,
    time_limit_sec: float = 1.0,
) -> Optional[List[int]]:
    """
    Map body index → start index meeting coverage samples.
    Returns list of start indices length n_bodies, or None.
    """
    bands = list(starts)
    b = len(bands)
    n = int(n_bodies)
    if b < 1 or n < 1:
        return None
    if not start_pack_body_feasible(
        bands,
        shift_length_hours=shift_length_hours,
        n_bodies=n,
        coverage_247=coverage_247,
        extra_windows=extra_windows,
        time_limit_sec=time_limit_sec,
    ):
        return None
    if not ortools_available():
        # Round-robin
        return [i % b for i in range(n)]

    try:
        from ortools.sat.python import cp_model
    except Exception:
        return [i % b for i in range(n)]

    samples: List[int] = []
    cov = max(0, int(coverage_247 or 0))
    if cov > 0:
        samples.extend(list(range(0, 24 * 60, 30)))
    for w in extra_windows or []:
        if not isinstance(w, dict) or not w.get("enabled", True):
            continue
        try:
            need = int(w.get("min_officers") or 0)
        except (TypeError, ValueError):
            need = 0
        if need <= 0:
            continue
        samples.extend(
            _window_samples(
                str(w.get("start_time") or "00:00"),
                str(w.get("end_time") or "23:59"),
            )
        )
    seen = set()
    uniq: List[int] = []
    for m in samples or [0, 720, 1320]:
        if m not in seen:
            seen.add(m)
            uniq.append(m)
    cover = pack_band_cover_matrix(bands, shift_length_hours, uniq)

    model = cp_model.CpModel()
    x = []
    for i in range(n):
        row = [model.NewBoolVar(f"a_{i}_{j}") for j in range(b)]
        model.AddExactlyOne(row)
        x.append(row)
    band_count = []
    for j in range(b):
        cnt = model.NewIntVar(0, n, f"abc_{j}")
        model.Add(cnt == sum(x[i][j] for i in range(n)))
        band_count.append(cnt)

    for si, _m in enumerate(uniq):
        need = cov
        for w in extra_windows or []:
            if not isinstance(w, dict) or not w.get("enabled", True):
                continue
            try:
                wneed = int(w.get("min_officers") or 0)
            except (TypeError, ValueError):
                wneed = 0
            if wneed <= 0:
                continue
            st = _hhmm_to_min(str(w.get("start_time") or "00:00"))
            en = _hhmm_to_min(str(w.get("end_time") or "23:59"))
            mm = uniq[si]
            in_win = (st <= mm < en) if en > st else (mm >= st or mm < en)
            if in_win:
                need = max(need, wneed)
        if need <= 0:
            continue
        covering = [band_count[j] for j in range(b) if cover[j][si]]
        if covering:
            model.Add(sum(covering) >= need)

    # Prefer balanced bands
    max_c = model.NewIntVar(0, n, "maxc")
    for j in range(b):
        model.Add(max_c >= band_count[j])
    model.Minimize(max_c)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(time_limit_sec)
    solver.parameters.num_search_workers = 1
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return [i % b for i in range(n)]
    out: List[int] = []
    for i in range(n):
        for j in range(b):
            if solver.Value(x[i][j]) == 1:
                out.append(j)
                break
    return out
