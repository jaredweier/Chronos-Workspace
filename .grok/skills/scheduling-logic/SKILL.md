---
name: scheduling-logic
description: Scheduling math — rotation, bumps, optimizers, rest/night, Rust/CP-SAT. Prefer dev.py math-domain.
---

# Scheduling logic & mathematics â€” focused

## Goal

Best scheduling math quality and performance. No solver allowlists.

## Tools

```bash
python dev.py math-domain explore|brainstorm|research-queries|engines|run-checks|learn
python dev.py math-scenarios --with-cpsat
python dev.py fuzz-scheduling
python dev.py scenarios Â· audit
```

Prefer in-repo solvers + tests. External math research only if user asks.

## In-repo map

| Area | Where |
|------|--------|
| Rotation / squad | `logic/scheduling.py`, `rust/scheduler_core` |
| Bump / cascade | `coverage_optimizer.py`, bump APIs |
| Validation | `validators.py` |
| CP-SAT what-if | `logic/cp_sat_bridge.py` |
| Payroll math | `logic/payroll.py`, `labor_compliance.py` |

## Freedom

- New optimizers, scoring, Rust/Python splits, optional engines â€” encouraged if better
- Policy knobs (night min, rest, junior-first) should stay **configurable** and tested
- Deposit: `math-domain learn --url â€¦ --as-idea`

## Related

`docs/knowledge/math_logic_sources.json` Â· `first-responder-wfm` Â· `payroll-timecard`
