# Known Issues Tracker

> Run `python dev.py audit` for historical regressions. **Open items below are real — not all fixed.**

## Open (product / design)

- [x] **Bump pick uses junior-first seniority** — `find_replacement_officer` picks highest `seniority_rank` (most junior) among eligible same-squad officers (`logic/scheduling.py`)
- [ ] **Partial bump cascades** — incomplete chains intentionally route to **Pending Manual Review** (product policy; not a bug — do not auto-complete) (`plan_bump_chain` / `process_day_off_request`)
- [x] **Legacy bid tables** — empty `shift_bid_slots` / `shift_bids` dropped on init; new DBs skip creation (`database.py`)
- [x] **analytics package** — `analytics.py` is a thin re-export of `logic.analytics`; dashboard wrappers live in `logic/dashboard.py`
- [x] **Monolith modules (2026-07-09)** — payroll `logic/payroll/*`; scheduling `scheduling.py` + `scheduling_bump` / `_matrix` / `_sim`; validators facade + `validators_dates|rules|officer|auth|ops` (+ lazy `validators_config`); root `ui/*_pages.py` gone
- [ ] **LDAP optional** — `logic/ldap_auth.py` when configured; **not department-tested** — leave off unless field-validated
- [x] **CTk maximize freeze** — `apply_main_window_layout` once-only via `_applied_for` in `ui/window_layout.py`; do **not** bind `<Map>` to maximize (login `<Map>` may only re-center login window)
- [x] **Chronos leave approve UX** — confirm + multi-plan pick + reject notes in `gui/pages/leave.py` (2026-07-09); still partial until browser e2e
- [x] **Date display contract** — user-visible calendar dates via `validators.format_date` (**M/D/YY** mm-dd-yy, `/` or `-`, year 2 or 4 digits); storage ISO. Intentional exceptions: clock times (`gui/clock.py`), CSV export stamps (`gui/tables.py`), weekday abbr next to `format_date` on matrix headers

## Open (agent / process) — fixed 2026-07-08

- [x] Stale `architecture.md` claimed swaps/notifications/payroll unimplemented
- [x] `known-issues.md` all `[x]` masked open design gaps
- [x] Layered gates (`preflight` green, `check` red) — unified `scripts/verify.py`
- [x] Demo `must_change_password` cleared on existing DBs — `_migrate_demo_password_policy`
- [x] Portable/CI could skip ship gate — `verify --tier full` + rust assert

## Critical (fixed — audit AUD-001..010)

- [x] Approve day-off when officer not scheduled working
- [x] Re-approve duplicate overrides
- [x] Night minimum on day shifts Fri/Sat
- [x] No validation on `create_day_off_request`
- [x] Replacement count in coverage
- [x] `get_cycle_day` before base date
- [x] Approve when override insert fails (transaction)
- [x] Duplicate during manual review
- [x] Cascading bump modeled (`plan_bump_chain`)

## Medium UI (fixed)

- [x] Requests officer dropdown stale
- [x] Dashboard stats refresh
- [x] Gantt cycle window
- [x] Manual review approve/reject
- [x] Replacements show as covering in Gantt
