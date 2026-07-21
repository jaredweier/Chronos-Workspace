# Architecture Reference

> Grok: `@logs/agent_pack/latest.md` · `@docs/AGENT_STABLE.md` · **Sufficiency:** stop when confident.

## Data flow

```
main.py / cli.py
    → logic/* (business rules via logic package)
        → validators.py (pre-checks)
        → database.py (SQLite)
    → ui/*_pages.py (presentation only)
    → config.py / permissions.py
```

Scheduling math: `logic/rust_bridge.py` → `scheduler_core` (Rust). Emergency: `logic/rust_fallback.py`.

## Key tables

- `officers` — roster
- `day_off_requests` — time-off workflow
- `schedule_overrides` — bump assignments (original → replacement)
- `shift_swaps` — swap requests (UI + logic)
- `notifications` — in-app alerts (implemented)
- `payroll_entries` — timecard / payroll ledger (implemented)
- `shift_bid_events` — tier 2 shift bidding

## Request approval flow

1. Validate request is `Pending`
2. Validate officer active and working on `request_date`
3. `validate_bump_feasibility` / `suggest_bump_chain` (night min, rest, consecutive days)
4. `find_replacement_officer` (same squad, allowed shifts; **seniority not used for bump pick**)
5. Insert `schedule_overrides`, update request status
6. Notify requester and replacement officer (`create_notification`)

## Agent knowledge map (graphify)

Prefer `graphify query` / `path` / `explain` against `graphify-out/graph.json` before bulk-reading modules.
Refresh: `graphify extract . --code-only`. Overview: `graphify-out/GRAPH_REPORT.md`. See `AGENTS.md`.

## Verification

Ship gate: `python dev.py verify --tier check` · Release: `verify --tier full`

## Test strategy

- `tests/test_logic.py` — rotation, bump, payroll
- `tests/test_validators.py` — validation rules
- `tests/test_regressions.py` — audit-backed bug regressions
- `scripts/ui_workflow_probe.py` — automated workflow checklist
- `tests/helpers.py` — `TestDatabase` context manager
