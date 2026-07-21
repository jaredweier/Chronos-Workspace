"""Multi-block rotation patterns: fixed vs rotating, variations, phase.

Used by simulator, schedule builder duty checks, and future per-officer roster fields.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

MAX_COMPOSITE_CYCLE_LENGTH = 112
MIN_BLOCK_ON = 1
MAX_BLOCK_ON = 28
MIN_BLOCK_OFF = 0
MAX_BLOCK_OFF = 28

ROTATION_STYLE_FIXED = "fixed"
ROTATION_STYLE_ROTATING = "rotating"


@dataclass(frozen=True)
class OnOffBlock:
    days_on: int
    days_off: int

    @property
    def length(self) -> int:
        return self.days_on + self.days_off


@dataclass
class RotationPattern:
    """One rotation variation (duty vector over a cycle)."""

    style: str  # fixed | rotating
    blocks: List[OnOffBlock] = field(default_factory=list)
    label: str = ""
    phase: int = 0  # cycle offset days

    @property
    def cycle_length(self) -> int:
        return sum(b.length for b in self.blocks)

    def duty_vector(self) -> List[bool]:
        vec: List[bool] = []
        for block in self.blocks:
            vec.extend([True] * block.days_on)
            vec.extend([False] * block.days_off)
        return vec

    def is_working(self, cycle_day: int) -> bool:
        """cycle_day is 1-based within the cycle."""
        vec = self.duty_vector()
        if not vec:
            return False
        n = len(vec)
        idx = (cycle_day - 1 + self.phase) % n
        return vec[idx]

    def work_days_per_cycle(self) -> int:
        return sum(1 for d in self.duty_vector() if d)

    def to_text(self) -> str:
        return ",".join(f"{b.days_on}-{b.days_off}" for b in self.blocks)

    def with_phase(self, phase: int) -> "RotationPattern":
        return RotationPattern(
            style=self.style,
            blocks=list(self.blocks),
            label=self.label,
            phase=int(phase) % max(self.cycle_length, 1),
        )


def parse_on_off_blocks(text: str) -> List[OnOffBlock]:
    """Parse '5-2' or '5-3,6-2' or '4-4,4-4,4-4,5-3,5-3' into blocks."""
    raw = (text or "").strip()
    if not raw:
        return []
    blocks: List[OnOffBlock] = []
    # Allow spaces around commas
    parts = re.split(r"[,;]+", raw)
    for part in parts:
        part = part.strip()
        if not part:
            continue
        m = re.match(r"^(\d+)\s*[-/]\s*(\d+)$", part)
        if not m:
            raise ValueError(f"Invalid rotation block: {part!r} (use on-off like 5-2)")
        on_d, off_d = int(m.group(1)), int(m.group(2))
        if on_d < MIN_BLOCK_ON or on_d > MAX_BLOCK_ON:
            raise ValueError(f"days_on must be {MIN_BLOCK_ON}–{MAX_BLOCK_ON}, got {on_d}")
        if off_d < MIN_BLOCK_OFF or off_d > MAX_BLOCK_OFF:
            raise ValueError(f"days_off must be {MIN_BLOCK_OFF}–{MAX_BLOCK_OFF}, got {off_d}")
        blocks.append(OnOffBlock(on_d, off_d))
    return blocks


def build_pattern(
    text: str,
    *,
    style: Optional[str] = None,
    phase: int = 0,
    label: str = "",
) -> RotationPattern:
    blocks = parse_on_off_blocks(text)
    if not blocks:
        raise ValueError("Rotation pattern is empty")
    cycle = sum(b.length for b in blocks)
    if cycle > MAX_COMPOSITE_CYCLE_LENGTH:
        raise ValueError(f"Cycle length {cycle} exceeds max {MAX_COMPOSITE_CYCLE_LENGTH}")
    if style is None:
        style = ROTATION_STYLE_FIXED if len(blocks) == 1 else ROTATION_STYLE_ROTATING
    style = style.lower().strip()
    if style not in (ROTATION_STYLE_FIXED, ROTATION_STYLE_ROTATING):
        raise ValueError("style must be 'fixed' or 'rotating'")
    if style == ROTATION_STYLE_FIXED and len(blocks) != 1:
        raise ValueError("Fixed rotation must be a single on-off block (e.g. 5-2)")
    if style == ROTATION_STYLE_ROTATING and len(blocks) < 2:
        raise ValueError("Rotating rotation needs multiple blocks (e.g. 5-3,6-2)")
    return RotationPattern(
        style=style,
        blocks=blocks,
        label=label or text.strip(),
        phase=phase % cycle if cycle else 0,
    )


def validate_variation_set(patterns: Sequence[RotationPattern]) -> Tuple[bool, str]:
    """All variations must share the same cycle length."""
    if not patterns:
        return False, "At least one rotation variation is required"
    lengths = {p.cycle_length for p in patterns}
    if len(lengths) != 1:
        detail = ", ".join(f"{p.label or p.to_text()}={p.cycle_length}" for p in patterns)
        return False, f"All variations must share the same cycle length ({detail})"
    return True, f"OK ({next(iter(lengths))}-day cycle, {len(patterns)} variation(s))"


def parse_variation_set(
    texts: Sequence[str],
    *,
    style: Optional[str] = None,
) -> List[RotationPattern]:
    patterns = [build_pattern(t, style=style) for t in texts if (t or "").strip()]
    ok, msg = validate_variation_set(patterns)
    if not ok:
        raise ValueError(msg)
    return patterns


def projected_annual_hours(
    pattern: RotationPattern,
    shift_length_hours: float,
    *,
    days_per_year: float = 365.25,
) -> float:
    """
    Year-average annual hours from work fraction × shift length.

    Uses 365.25 (mean Gregorian year) so leap years are averaged in.
    Cycle length rarely divides 365/366 evenly — real calendar years will
    differ slightly by officer phase; compare officers for fairness, not
    exact equality to a single target hour.
    """
    cl = pattern.cycle_length
    if cl <= 0:
        return 0.0
    work_frac = pattern.work_days_per_cycle() / cl
    return round(work_frac * days_per_year * shift_length_hours, 1)


def annual_hours_within_band(
    projected: float,
    target: float,
    *,
    variance_hours: float = 0.0,
    variance_percent: float = 0.0,
) -> Tuple[bool, float, float, float]:
    """Return (ok, low, high, distance_outside). distance_outside=0 if inside band."""
    band = float(variance_hours or 0.0)
    if variance_percent:
        band = max(band, abs(target) * float(variance_percent) / 100.0)
    low = target - band
    high = target + band
    if projected < low:
        return False, low, high, low - projected
    if projected > high:
        return False, low, high, projected - high
    return True, low, high, 0.0


def pattern_summary(pattern: RotationPattern) -> Dict:
    return {
        "style": pattern.style,
        "label": pattern.label,
        "text": pattern.to_text(),
        "cycle_length": pattern.cycle_length,
        "phase": pattern.phase,
        "work_days_per_cycle": pattern.work_days_per_cycle(),
        "duty_vector": pattern.duty_vector(),
    }


def _blocks_to_text(blocks: Sequence[OnOffBlock]) -> str:
    return ",".join(f"{b.days_on}-{b.days_off}" for b in blocks)


def block_order_variants(blocks: Sequence[OnOffBlock]) -> List[List[OnOffBlock]]:
    """Rotate / reverse block order (e.g. 6-2,5-3 → 5-3,6-2). Same cycle, different phase shape."""
    bl = list(blocks)
    if not bl:
        return []
    n = len(bl)
    out: List[List[OnOffBlock]] = []
    seen = set()
    for i in range(n):
        cand = bl[i:] + bl[:i]
        key = _blocks_to_text(cand)
        if key not in seen:
            seen.add(key)
            out.append(cand)
    rev = list(reversed(bl))
    key = _blocks_to_text(rev)
    if key not in seen:
        out.append(rev)
    return out


def complementary_off_swap(blocks: Sequence[OnOffBlock]) -> Optional[List[OnOffBlock]]:
    """Same ON days, swap OFF days between adjacent blocks (two-block multi).

    Example: 6-2,5-3 (16d, 11 work) ↔ 6-3,5-2 (16d, 11 work).
    Officers can mix these on one cycle so daily body counts stagger.
    """
    bl = list(blocks)
    if len(bl) != 2:
        return None
    a, b = bl[0], bl[1]
    partner = [OnOffBlock(a.days_on, b.days_off), OnOffBlock(b.days_on, a.days_off)]
    if _blocks_to_text(partner) == _blocks_to_text(bl):
        return None
    if sum(x.length for x in partner) != sum(x.length for x in bl):
        return None
    if sum(x.days_on for x in partner) != sum(x.days_on for x in bl):
        return None
    return partner


def expand_variation_family(
    texts: Sequence[str],
    *,
    style: Optional[str] = None,
) -> List[str]:
    """Expand seed multi-block strings into a same-cycle family for officer mix.

    From any seeds (examples or user-typed):
    - block-order variants (6-2,5-3 and 5-3,6-2)
    - complementary OFF swaps (6-2,5-3 and 6-3,5-2)
    Does **not** invent a fixed department scenario — only algebra on what was given
    (or empty → empty).
    """
    seeds = [t.strip() for t in texts if (t or "").strip()]
    if not seeds:
        return []
    out: List[str] = []
    seen = set()
    cycle_lens: set = set()

    def _add_blocks(blocks: List[OnOffBlock], st: Optional[str]) -> None:
        if not blocks:
            return
        try:
            p = RotationPattern(
                style=(st or (ROTATION_STYLE_ROTATING if len(blocks) > 1 else ROTATION_STYLE_FIXED)),
                blocks=list(blocks),
                label=_blocks_to_text(blocks),
            )
        except Exception:
            return
        key = p.to_text()
        if key in seen:
            return
        # Keep one cycle length family only (first seed wins)
        if cycle_lens and p.cycle_length not in cycle_lens:
            return
        cycle_lens.add(p.cycle_length)
        seen.add(key)
        out.append(key)

    for t in seeds:
        try:
            p = build_pattern(t, style=style)
        except ValueError:
            continue
        _add_blocks(p.blocks, p.style)
        for var in block_order_variants(p.blocks):
            _add_blocks(var, p.style)
        partner = complementary_off_swap(p.blocks)
        if partner:
            _add_blocks(partner, p.style)
            for var in block_order_variants(partner):
                _add_blocks(var, p.style)

    # Prefer multi-pattern sets; if only fixed singles, keep them
    return out


def patterns_for_work_fraction(
    work_frac: float,
    *,
    max_cycle: int = 28,
    min_cycle: int = 8,
    tol: float = 0.02,
) -> List[List[OnOffBlock]]:
    """Find multi-block decompositions near a target work fraction.

    Pure math — not a baked product default. Prefer LE-sane blocks (on≥2, off≥1)
    and closer fraction matches first.
    """
    if work_frac <= 0 or work_frac >= 1:
        return []
    scored: List[Tuple[float, int, List[OnOffBlock]]] = []
    seen = set()
    max_c = max(min_cycle, min(int(max_cycle), MAX_COMPOSITE_CYCLE_LENGTH))
    # Prefer classic LE cycle lengths first, then remaining
    preferred = [14, 16, 21, 28, 12, 10, 15, 18, 20, 24]
    cycles = [c for c in preferred if min_cycle <= c <= max_c]
    cycles += [c for c in range(int(min_cycle), max_c + 1) if c not in cycles]

    for cycle in cycles:
        work = int(round(work_frac * cycle))
        if work < 2 or work >= cycle:
            continue
        frac = work / cycle
        err = abs(frac - work_frac)
        if err > tol + 1e-9:
            continue
        off_total = cycle - work
        if off_total < 1:
            continue
        # Two-block composites only (rotating multi-block family)
        for on1 in range(2, min(MAX_BLOCK_ON, work - 1) + 1):
            on2 = work - on1
            if on2 < 2 or on2 > MAX_BLOCK_ON:
                continue
            for off1 in range(1, min(MAX_BLOCK_OFF, off_total - 1) + 1):
                off2 = off_total - off1
                if off2 < 1 or off2 > MAX_BLOCK_OFF:
                    continue
                # Skip extreme imbalance (one micro-block + one giant)
                if max(on1, on2) > 2 * min(on1, on2) + 2:
                    continue
                blocks = [OnOffBlock(on1, off1), OnOffBlock(on2, off2)]
                key = _blocks_to_text(blocks)
                if key in seen:
                    continue
                seen.add(key)
                # Prefer balanced on/off and closer frac
                balance = abs(on1 - on2) + abs(off1 - off2)
                score = err * 1000 + balance + (0 if cycle in (14, 16, 21, 28) else 5)
                scored.append((score, cycle, blocks))

    scored.sort(key=lambda x: (x[0], x[1]))
    return [b for _, _, b in scored]


def generate_multi_block_variation_sets(
    *,
    shift_length_hours: float,
    annual_hours_target: float,
    annual_variance: float = 40.0,
    max_sets: int = 24,
    max_cycle: int = 28,
) -> List[List[str]]:
    """Build variation *sets* for free multi-block search from annual math.

    Each set is 1+ patterns of the **same cycle length** so officers can be mixed
    (some on one multi-block shape, others on complementary OFF-swap / order flips).
    """
    length = max(0.5, float(shift_length_hours or 8.0))
    target = float(annual_hours_target or 0.0)
    if target <= 0:
        return []
    work_frac = target / (365.25 * length)
    lo = max(0.05, (target - float(annual_variance or 0)) / (365.25 * length))
    hi = min(0.95, (target + float(annual_variance or 0)) / (365.25 * length))
    mid = max(lo, min(hi, work_frac))

    families: List[List[str]] = []
    seen_set = set()

    def _add_set(texts: List[str]) -> None:
        if not texts:
            return
        key = tuple(sorted(texts))
        if key in seen_set:
            return
        try:
            parse_variation_set(texts, style="rotating")
        except ValueError:
            return
        seen_set.add(key)
        families.append(list(texts))

    for blocks in patterns_for_work_fraction(mid, max_cycle=max_cycle, tol=0.025)[:40]:
        family = expand_variation_family([_blocks_to_text(blocks)])
        multi = [t for t in family if "," in t]
        if len(multi) >= 2:
            _add_set(multi[:4])
            _add_set(multi[:2])
        if len(families) >= max_sets:
            break

    if len(families) < 4:
        for frac in (lo, hi, (lo + hi) / 2):
            for blocks in patterns_for_work_fraction(frac, max_cycle=max_cycle, tol=0.04)[:20]:
                multi = [t for t in expand_variation_family([_blocks_to_text(blocks)]) if "," in t]
                if len(multi) >= 2:
                    _add_set(multi[:4])
                if len(families) >= max_sets:
                    break
            if len(families) >= max_sets:
                break

    return families[:max_sets]
