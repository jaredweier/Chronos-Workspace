# Scheduling math (Grok — on demand)

Skill: `.grok/skills/scheduling-logic/SKILL.md` · rules: `SCHEDULING_RULES.md` (human; blocked from bulk read)

## Constants (`config.py`)
| Symbol | Value / meaning |
|--------|-----------------|
| `ROTATION_BASE_DATE` | 2026-06-28 |
| `ROTATION_CYCLE_LENGTH` | 14 days |
| `SHIFT_TIMES` | 1:06–17, 2:10–21, 3:15–02, 4:19–06 |
| `BUMP_RULES` | 1↔2, 2↔1/3, 3↔2/4, 4↔3 |
| `NIGHT_MINIMUM_OFFICERS` | 2 (Fri/Sat night only) |
| `MIN_REST_HOURS_BETWEEN_SHIFTS` | 8.0 |
| `BUMP_ASSIGNMENTS_BEFORE_BUSY` | 2 |

## Formulas
- **Cycle day:** days since base mod 14 → squad A/B on duty (Rust primary: `scheduler_core`)
- **Junior bumps first:** higher `seniority_rank` number = more junior
- **Pay period:** independent 14-day from `PAY_PERIOD_BASE_DATE` (shift **start** date owns hours)
- **Overnight hours:** count in period where shift **starts**

## Engine
`logic/scheduling.py` → `rust_bridge` → `scheduler_core`
Python multi-plan search: `logic/coverage_optimizer.py` (beam search, scored juniors)
Fallback: `rust_fallback.py`

## Configurable (department settings + staffing/rotation modules)
| Knob | Source |
|------|--------|
| Shift count / starts / length | `staffing_config` |
| Cycle length / squad days | `rotation_config` |
| Min per shift / night min / cascade depth | `CoveragePolicy` via settings keys |
| **Per-band min staff** | setting `min_staffing_by_band` JSON `{"06:00":2,"19:00":2}` or `06:00=2,19:00=2` |
| Annual hours target | staffing settings |

## Best-plan APIs
- `suggest_bump_chain` / `optimize_day_off_coverage` — day-off approval
- `preview_best_coverage_plans` — ranked alternatives for supervisors
- `run_staffing_optimizer` — simulator sweep (rotation × headcount × min staff)

## Free checks
`python dev.py math-domain run-checks` · `math-scenarios` · `fuzz-scheduling` · `audit` · `scenarios` · `unittest tests.test_coverage_optimizer`

## MAXIMUM CAPABILITY (logic/math)
Any OR/math source or technique is in scope. Tool: `python dev.py math-domain explore|brainstorm|research-queries|learn`
Starters: `docs/knowledge/math_logic_sources.json` (optional).

Improve aggressively: new optimizers, Rust/Python/CP-SAT hybrids, better scoring, policy knobs.
Current department defaults (night min, rest, junior-first) live in config/validators — change only with clear product intent, but research is unlimited.
