# Schedule simulator — external research map

**Date:** 2026-07-21
**Purpose:** Inspiration from open OR / WFM products. Not a clone of proprietary code.
**Product law:** Feasible schedules from **entered constraints** first; score / fairness / FLSA / fatigue / heatmap = optional **narrowers among working plans**. Hard eval **56 days**.

## Solver / OR sources

| Source | Patterns to reuse |
|--------|-------------------|
| [OR-Tools employee scheduling](https://developers.google.com/optimization/scheduling/employee_scheduling) | Hard coverage + at-most-one/day; soft fairness min/max shifts; preference maximize after hard OK |
| [shift_scheduling_sat.py](https://github.com/google/or-tools/blob/main/examples/python/shift_scheduling_sat.py) | Multi-day model, transition penalties, request soft weights → **CP-SAT seeds only** |
| Timefold / OptaPlanner | Hard vs soft scores, explain-score UX |
| Staffjoy (open-source suite) | Forecast → decompose → assign pipeline (stage wizard mental model) |

**Chronos domain ≠ pure nurse rostering.** We optimize rotation + starts + windows; 56d `simulate_schedule` remains ground truth.

## WFM / public-safety UX patterns

Coverage heat strip · gap board · open shift / callout · bid/preference capture · what-if scenarios · compliance strip (rest/OT/FLSA) separate from “feasible” · publish readiness checklist.

## Visual references

- [Mobiscroll employee shift timeline](https://demo.mobiscroll.com/timeline/employee-shifts) — officer × time Gantt
- Schedule-X / resource calendars — week / multi-week views
- Vertex42-style rotation calendars — pattern preview before full sim

## Opportunity tiers (for product backlog)

| Tier | Focus |
|------|--------|
| **P0** | Stabilize extract wiring + honest metrics — **landed** `0d5b83a` |
| **P1** | Constraint autopsy + live cheap feasibility strip — **landed** (`logic/constraint_autopsy.py`) |
| **P2** | Hard-then-soft pipeline; fairness min–max; prefs among feasible |
| **P3** | Heatmap prominence; officer Gantt; side-by-side compare |
| **P4** | Open-shift / bid bridge after implement |

## Non-goals

- Re-monolith `staffing_optimizer.py`
- Soft constraints as Find Best hard gates
- Replace Chronos sim with generic nurse CP-SAT only
- Invent product defaults from demo numbers (8h / 2008 / 6-2,5-3)

## Related internal notes

- `docs/knowledge/sim_staged_search_notes.md` — staged search design
- `docs/HANDOFF.md` — product do-not-rebreak
