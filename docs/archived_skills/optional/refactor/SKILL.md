---
name: refactor
description: >
  Dodgeville PD Scheduler refactor workflow — modularize logic.py and ui/app.py,
  reduce N+1 queries, CLI parity, UI helpers, permissions tests. Use when splitting
  monoliths, adding dev.py refactor-check, or running the improvement plan.
---

# Refactor Skill

## Vertical slices first

Before moving code, identify the slice in `slices/registry.py` (`python dev.py slice-map`).

- Edit only `touch_together` files for that slice (+ shared kernel if cross-cutting).
- Strategy: `docs/VERTICAL_SLICES.md`
- Verify: `python dev.py slice-check` then slice `verify` commands.

## Phases (execute in order)

1. **Quick wins** — `database.connection()`, batch coverage/conflicts, cache roster refresh
2. **CLI parity** — thin wrappers for submit/create/fill/delete/settings
3. **UI helpers** — `ui/helpers.py`; extract mixins (`requests_pages.py` first)
4. **logic/ package** — one slice per PR; stable `import logic` via `logic/__init__.py` (see `future_module` per slice)
5. **Security** — `SKIP_DEMO_USERS`, permissions matrix tests

## Verification after every phase

```bash
python dev.py logic-imports      # verify logic.py exports match callers
python scripts/detect_truncated_functions.py  # catch incomplete rebuilds
python dev.py refactor-check
python dev.py check
```

## Layer rules (never violate)

- Validators → logic → UI/CLI
- No SQL in `ui/` or `cli.py`
- `import logic` must keep working for all existing callers

## Module split map

| Module | Contents |
|--------|----------|
| `logic/officers.py` | Roster CRUD, `get_officers_by_seniority` |
| `logic/scheduling.py` | Rotation, bumping, schedule matrix, coverage counts |
| `logic/requests.py` | Day-off, swaps, notifications |
| `logic/payroll.py` | Payroll, timecard |
| `logic/users.py` | Auth, app users |
| `logic/snapshots.py` | Schedule snapshots |
| `logic/exports.py` | PDF + analytics wrappers |
| `logic/operations.py` | Holidays, availability, open shifts, simulator hooks |

## UI mixin map

| Mixin | File |
|-------|------|
| Requests + swaps | `ui/requests_pages.py` |
| Officers | `ui/officers_page.py` (later) |
| Payroll + timecard | `ui/payroll_pages.py` (later) |
