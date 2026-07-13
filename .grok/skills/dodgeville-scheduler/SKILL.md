---
name: dodgeville-scheduler
description: Dodgeville PD Scheduler product work — scheduling, bumps, leave, payroll, gui/, tests.
---

# Dodgeville Scheduler Development Skill

## Before any change

0. **Route task:** `python dev.py route-task "<task>"` — auto-context OFF; load one skill if printed
1. Read `docs/HANDOFF.md` when resuming â€” only if user requests or @-mentions
2. Identify the **vertical slice**: `python dev.py slice-map -v` â†’ `slices/registry.py` â†’ `docs/VERTICAL_SLICES.md`
3. Run `python dev.py check` to establish baseline
4. Edit only that slice's `touch_together` files (+ shared kernel if cross-cutting); layers: validators â†’ logic â†’ UI/CLI

## Fix workflow

1. Add/adjust validation in `validators.py` first
2. Wire `logic.py` to call validators (never duplicate checks in UI)
3. Add regression test in `tests/test_regressions.py` or `tests/test_validators.py`
4. Update `.grok/rules/known-issues.md` checkbox when fixed
5. Run `python dev.py check` â€” all tests and audit must pass

## UI workflow

- `main.py` calls `logic.*` only; refresh stale widgets after mutations
- After officer CRUD: refresh officer list AND requests dropdown
- After request actions: refresh dashboard stats and gantt if visible
- Use `config` colors and `GANTT_COLORS`; match existing tab layout patterns

## New feature workflow

1. Schema change â†’ `database.py` `init_database()`
2. Business rules â†’ `logic.py`
3. Validation â†’ `validators.py`
4. GUI tab or CLI command
5. Seed data update in `seed_data.py` if needed
6. Tests + `dev.py audit` entry if scheduling-critical

## Subagent routing

| Task type | Load skill |
|-----------|------------|
| Bump, rotation, validators | `scheduling-logic` |
| Tabs, widgets, login UI | `ui-development` |
| CLI commands, dev scripts | `cli-operations` |
| Cross-cutting / unsure | this skill |

See `.grok/rules/subagents.md` for delegation patterns.

## Dev commands (run these, do not just tell the user)

```bash
python dev.py doctor       # Python, deps, schema, assets
python dev.py smoke        # day-off, user, iCal, PDF flows
python dev.py feature-map  # UI â†” logic â†” CLI table
python dev.py ui-review    # UI spelling, wording, aesthetics report
python dev.py check        # full gate: imports + unittest + audit
python dev.py test         # unittest only
python dev.py audit        # regression audit
python dev.py reset-db     # fresh DB + seed
```

## CLI quick reference

```bash
python cli.py users list
python cli.py overrides assign --original-officer-id 3 --replacement-officer-id 7 --date 2026-07-10
python cli.py export ical --officer-id 3
```

Full list: `.grok/rules/cli-reference.md`

## Scheduling invariants (never break)

- Officers only request off on days their squad is on duty
- Night minimum only for night shifts on Fri/Sat
- Pending-only approval; no duplicate overrides
- Bump replacements: same squad, allowed shift (seniority rank only for vacation grant ordering)
- `cli.py` must use `logic.add_officer`, not raw SQL
