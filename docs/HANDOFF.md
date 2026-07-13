# Session Handoff — Dodgeville PD Scheduler

**Purpose:** Living memory for agents (and humans) to resume work without re-reading full chat history.
**Human-readable mirror:** [`PROJECT_README.md`](PROJECT_README.md) — keep both in sync when updating.
**Update this file** when you finish a meaningful chunk of work (features, fixes, renames, perf passes).

**Last updated:** 2026-07-13
**Verification:** run `python dev.py verify --tier check` before ship (do not trust stale counts). **`honest_gate: true` required** for any done/ship claim.
**Next agent (self-contained):** **[`docs/NEXT_AGENT_PROMPT.md`](NEXT_AGENT_PROMPT.md)** — integrity edition; anti-lie rules + proof requirements
**Trust repair:** maps restored (P0/P1); product still **partial** — see P2 inventory
**Depth only:** `TOKEN_PERFORMANCE.md` · `CHRONOS_SOURCES.md` · `UI_AGENTS_CATALOG.md` · `AGENT_ROUTING.md` · `python dev.py route-task`

### Trust status (updated 2026-07-13)

| Check | Status |
|-------|--------|
| Slice registry | **Fixed** — paths → `gui/pages/*` + `ui/pages/*`; status mostly `partial` |
| feature-map UI column | **Fixed** — requires existing `ui_files` |
| Full unittest | **385 tests OK** (2026-07-13, `SCHEDULER_SKIP_AGENT_GATES=1`; +token policy) |
| `verify --tier check` | **PASS** 2026-07-13 · `honest_gate: true` (`logs/last_verify.json`) |
| token-audit | **89/89** (2026-07-13 auto-abide + skill discovery prune) |
| Skill discovery | Active skills under `.grok/skills/` only (~10); archives in `docs/archived_skills/` (not injected) |
| Chronos product depth | **Partial** — P2 inventory below |
| Domain engine | **Strong** |
| Chronos leave (P2) | Approve + multi-plan pick + reject notes in `gui/pages/leave.py`; **logic smoke** only; **browser click-approve unproven** |
| Chronos payroll (P2) | Lock/unlock UI + **logic smoke**; browser lock click unproven |
| Chronos notifications (P2) | Open path map + create/mark-read; **logic smoke**; chrome e2e optional |

Trust maps restored. Product Chronos dual-rated **partial**. Agent auto-abide: caveman AGENTS + lean kit + no archive skill cards (2026-07-13).

### Scheduling modularization (2026-07-09)

`logic/scheduling.py` split (public API unchanged — `import logic` / `from logic.scheduling import …`):

| Module | Role |
|--------|------|
| `logic/scheduling.py` | Rotation/rest core + re-exports (~450 lines) |
| `logic/scheduling_bump.py` | Bump chain / replacement / format / validate |
| `logic/scheduling_matrix.py` | Matrix, day status, override maps |
| `logic/scheduling_sim.py` | Simulator + multi-plan preview (earlier extract) |

Scripts: `scripts/split_scheduling_bump.py`, `scripts/split_scheduling_matrix.py` (idempotent).
**Validators split (same session):** facade `validators.py` + `validators_dates|rules|officer|auth|ops.py`; config gates lazy-re-exported from `validators_config.py`. Script: `scripts/split_validators.py`.
---

## Quick resume

| Item | Value |
|------|--------|
| Product | **Chronos Command** (NiceGUI primary UI in `gui/`) |
| Run GUI | `python main.py` → `gui.app` |
| Legacy UI | `ui/pages/*` CustomTkinter — not primary; **old root `ui/*_pages.py` mixins removed** |
| Demo logins | `admin` / `admin`, `supervisor` / `supervisor`, `officer` / `officer` |
| Auto-login | **Off by default** — set `SCHEDULER_AUTO_LOGIN=1` for dev skip-login |
| Full verify | `python dev.py verify --tier check` + read `logs/last_verify.json` |
| Domain rules | `SCHEDULING_RULES.md`, `.grok/rules/known-issues.md` |
| Display dates | US **M/D/YY** e.g. `7/9/26` via `validators.format_date` — not day-first |

**User workflow lately:** iterative live GUI testing — launch app, fix feedback, re-run `dev.py check`, relaunch.

**UI hazard (2026-07-06):** Do **not** bind `<Map>` (or other show/configure events) to `apply_main_window_layout()` in `ui/window_layout.py`. That function toggles `state("normal")` → `state("zoomed")` and steals focus (`focus_force`, `-topmost`); a Map feedback loop froze Windows (rapid popups, Task Manager unusable). Layout runs **once** at login/bootstrap only; `_applied_for` guard in `window_layout.py`. Before `ui-live` / `ui-observe --live`, confirm the guard is still present.

---

## Recent session work (2026-07)

### Window layout freeze fix (2026-07-06)

| Change | Purpose |
|--------|---------|
| `ui/session_pages.py` | Removed `<Map>` → `apply_main_window_layout` binding (feedback loop) |
| `ui/window_layout.py` | `_applied_for` set — maximize/focus at most once per root window |

**Recovery if loop returns:** Admin CMD `taskkill /F /IM python.exe`; delete `logs/ui_live_test/.running.lock` if stale. Prefer `python dev.py ui-smoke` (headless) until fixed.

### Agent tooling, OSS integration, usage minimization (2026-07-06)

| Artifact | Purpose |
|----------|---------|
| `.gitignore` | Keep logs, db, dist, terminals out of git |
| `.pre-commit-config.yaml` | preflight on commit |
| `.github/workflows/ci.yml` | Free CI on push (needs `setup_github.ps1`) |
| `opencode.json` + `.opencode/` | OpenCode agents/commands; compaction + image limits |
| `docs/USAGE_MINIMIZATION.md` | Human/agent guide to reduce LLM spend |
| `.grok/skills/cost-efficient-workflow/` | Agent skill: free gates first |
| `python dev.py ui-diff --quick` | Nav/login PNGs only (01–15) |
| `tests/ui_snapshots/baseline/` | 78 UI regression baselines seeded |
| `scripts/install_opencode.ps1` | winget/npm/scoop/GitHub release download |
| `scripts/setup_github.ps1` | Link remote + stage CI paths |

**Usage ladder:** `preflight` → `verify-slice` → `ui-diff --quick` → `check` → `ui-observe` (no `--live`) → vision only if needed.

**Blocked (user action):** GitHub push (no `origin` remote); OpenCode install if no network/package manager.

### Vertical slice architecture (logic split done; **registry honest as of 2026-07-09**)

Brownfield VSA: [`docs/VERTICAL_SLICES.md`](VERTICAL_SLICES.md).
**P0 repaired:** `python dev.py slice-check` → all bindings resolve; slice status is mostly **`partial`** (not complete). Primary UI paths are `gui/pages/*` (+ legacy `ui/pages/*` where listed).

| Artifact | Purpose |
|----------|---------|
| `slices/registry.py` | Slice defs — Chronos `gui/pages/*` + logic touch sets |
| `python dev.py slice-map -v` | Find slice by capability; see `touch_together` files |
| `python dev.py slice-check` | Path existence / integrity |
| `tests/test_vertical_slices.py` | Registry integrity tests |

**Logic package split:** under `logic/*.py`; `import logic` via `logic/__init__.py`.
**UI:** primary Chronos `gui/pages/*`; legacy `ui/pages/*` secondary (freeze except bugs unless task says otherwise).

### Chronos depth inventory (P2 — 2026-07-09)

Dual-rate only. **Logic strong ≠ Chronos complete.** Re-prove with browser smoke before `"complete"`.

| Feature | Logic | Chronos page(s) | User can… | Status |
|---------|-------|-----------------|-----------|--------|
| Dashboard / KPIs | strong | `gui/pages/dashboard.py` | KPIs, gap board, hours watch, quick actions | **partial** |
| Roster | strong | `roster.py` | CRUD-ish personnel | **partial** |
| Day-off + swaps | strong | `leave.py` | Submit, preview, plans, confirm plan pick, reject notes, bulk, swaps | **partial** (logic smoke OK; browser click-approve unproven) |
| Schedules | strong | `schedules.py` | My / monthly / live matrix | **partial** |
| Payroll / timecard | strong | `finance/*` | Entry, prefill, **lock/unlock**, banks, ledger | **partial** (logic lock smoke OK; browser lock unproven) |
| Notifications | strong | `notifications.py` | Inbox, mark read, compose, Open→route map | **partial** (path smoke OK) |
| Ops reports | strong | `operations.py` | Gaps, hours, OT equity, full insights | **partial** |
| Open shifts | strong | `self_service.py` | Board, post, claim/assign | **partial** |
| Shift bidding | exists | `bidding.py` | Events + officer bid form | **partial** |
| Availability | strong | `availability.py` | Blackouts / holidays | **partial** |
| Simulator | yes | `simulator.py` | Scenario trainer | OK (UI-only by design) |
| Security / users | strong | `security.py`, `access.py` | RBAC chrome / access | **partial** |
| Multi-user deploy | NiceGUI | — | Hostable; hardening open | **partial** |

**Legacy `ui/`:** frozen except bugs unless explicitly tasked.
**Logic package (2026-07):**

| Module | Slice |
|--------|--------|
| `logic/officers.py` | roster |
| `logic/scheduling.py` | rotation, bumping, matrix |
| `logic/requests.py` | day-off, swaps, notifications |
| `logic/snapshots.py` | monthly calendars, sync, overrides |
| `logic/payroll/` | payroll, timecard (package: period, pay_codes, timecard, entries, banks) |
| `logic/users.py` | auth, app users |
| `logic/operations.py` | holidays, availability, open shifts, settings |
| `logic/exports.py` | PDF/CSV/iCal export wrappers |
| `logic/dashboard.py` | dashboard + analytics delegates |
| `logic/_core.py` | thin shim (re-exports exports + dashboard) |

Tooling: `scripts/extract_logic_requests.py`, `scripts/extract_logic_modules.py`, `scripts/extract_logic_core_trim.py`

**Agent rule:** When changing a feature, find its slice → edit only `touch_together` files (+ shared kernel if cross-cutting) → run slice `verify` + `python dev.py check`.

**UI note:** monthly schedule CTAs live under Chronos `gui/pages/schedules.py` / legacy `ui/pages/*` (root `ui/*_pages.py` mixins removed).

### Industry roadmap — Tier 1, Visual/UX, Phases A–C (**logic largely done; Chronos UI partial — do not call complete**)

Much of the public-safety scheduling UX backlog exists in **logic** and/or **legacy UI**. Chronos `gui/` has KPIs and key flows but **not full parity**. Rate Logic vs Chronos separately.

**Tier 1 (logic + UI):**

| Feature | Key symbols |
|---------|-------------|
| Coverage gap board | `analytics.get_coverage_gap_board()`, dashboard card + alerts |
| FLSA / hours watch | `analytics.get_hours_watch()`, dashboard + My Profile |
| Minimum rest (8h) | `config.MIN_REST_HOURS_BETWEEN_SHIFTS`, `validators.validate_minimum_rest_gap()`, manual-review override path |
| Court / training types | `DAY_OFF_REQUEST_TYPES`, Gantt colors, `REQUEST_TYPE_SCHEDULE_STATUS` |
| Equitable OT ledger | `analytics.get_equitable_ot_ledger()`, Ops Reports section |
| Schedule-published notify | `_notify_schedule_published()` after `sync_updated_schedule()` |
| Officer My Week | `get_officer_schedule_window()`, dashboard card for officer role |

**Visual & UX:** on-duty-now strip, consolidated alert stack, clickable stat cards, approve confirmation modal with bump summary, ledger type + status filter chips, roster title badges + pay-period hours on rows, global `STATUS_COLORS`, monthly sync empty-state CTA, Gantt empty-state CTA, officer-simplified Command Post quick actions.

**Phases A–C** overlap the above (dashboard ops clarity, LE scheduling rules, self-service home + open-shift polish).

**Gotcha:** Minimum rest violations route to **Pending Manual Review**; supervisor approve uses override messaging (see `tests/test_regressions.py`).

---

## Recent session work (2026-06)

### Payroll — period totals and breakdown

- **Logic:** `get_pay_period_hours_summary()`, `_summarize_pay_period_hours()` in `logic.py`
- **UI:** Prominent pay-period hour total on Payroll tab; **More Details** expandable section (`ExpandableSection` in `ui/widgets.py`)
- **Tests:** `tests/test_payroll.py`

### Schedule naming and behavior

| Old label | Current label | Behavior |
|-----------|---------------|----------|
| Base Rotation | **Original Monthly Schedule** | Auto-generated from rotation/squad/shift on first view; **locked** after generation (`ensure_original_monthly_schedule()` in `logic.py`) |
| Live Duty Roster | **Current Monthly Schedule** | Reflects approved time off, bumps, swaps, manual edits; **Sync Current Monthly Schedule** action |

- **UI:** `ui/schedule_pages.py`, nav labels in `ui/theme.py`
- **Cell display:** Officer name + shift time prominent; squad shown as small `Sq A/B` badge (up to 4 officers per day; click day for full roster below)

### Time Off — day-off request ledger

- Bottom **Day Off Requests** ledger on Time Off tab
- Columns: Submitted (timestamp), Employee, Type, Date Off, Status
- **Officers:** own requests only; **Supervisor/Admin:** all employees
- **Logic:** `get_day_off_requests_for_viewer()`, `format_datetime()` in `validators.py`; `created_at` from DB
- **UI:** `ui/requests_pages.py`

### Officers roster — title / squad / shift fix

**Root cause:** `CTkComboBox` inside `CTkScrollableFrame` — dropdowns do not work reliably in CustomTkinter.

**Fix:** Moved **Title**, **Squad Assignment**, and **Shift Assignment** to a **sticky header bar** above the scrollable form:
- `StringVar` + `state="readonly"` combos
- Helpers: `_configure_job_title_combo`, `_configure_squad_combo`, `_configure_shift_combo`
- `load_officer(..., force_reload=True)` after save
- **Tests:** `tests/test_roster_import.py` — `test_update_officer_job_title`, `test_update_officer_squad_and_shift`

**Pattern to reuse:** Never put editable combos inside scrollable frames; use sticky header or modal.

### Scroll performance (laggy screens)

Identified hot paths and optimized:

| Area | Problem | Fix |
|------|---------|-----|
| Monthly calendar | ~31 days × nested frames/labels; `get_snapshot_day_roster()` per day | `build_monthly_roster_by_date()` once per month; **one multiline label** per day cell (`.configure()` not destroy/recreate) |
| Time Off queue | `suggest_bump_chain()` on every pending row | Coverage badge only for `Pending Manual Review`; full bump plan on **Preview** only |
| Day-off ledger | Full destroy/rebuild on every `refresh_requests()` | Signature cache in `refresh_day_off_request_ledger()` — skip rebuild if data unchanged |
| Officer list | `get_officer_by_id()` per row on selection highlight | `_officer_cache` populated in `refresh_officer_list()` |
| Payroll period scroll | All timecard lines per officer | Show **3 lines** + `+N more entries` |

**Key files:** `logic.py`, `ui/schedule_pages.py`, `ui/requests_pages.py`, `ui/officers_pages.py`, `ui/payroll_pages.py`

If scroll is still slow on a specific tab, profile that tab first — Gantt and other scrollables were not changed in this pass.

### Documentation and code dump (2026-07)

- **`docs/HANDOFF.md`** — agent handoff (this file)
- **`docs/PROJECT_README.md`** — human-readable project status mirror
- **`docs/FULL_PROJECT_CODE.txt`** — full project in one text file (~29 MB)
- **`scripts/export_project_code.py`** — regenerates the dump
- **Dump includes:** all source, `dodgeville_scheduler.db`, `build/`, `__pycache__/` (binaries as base64)
- **Dump excludes:** `dist/` (rebuild locally), `logs/`, `exports/`, `backups/`, `terminals/`
- **`docs/PROJECT_README.md`** — **How to work with the agent** section (templates, tips, compression user rule)

### Production login default (2026-07)

- `AUTO_LOGIN_ENABLED` defaults to **off** (`SCHEDULER_AUTO_LOGIN` must be `1` to skip login)
- Demo accounts unchanged: `admin`/`admin`, etc.

### `ui/app.py` shell cleanup (2026-07)

- Page logic in mixins; shell trimmed to nav, login, and refresh orchestration
- **My Profile** dialog extracted to `ui/profile_dialog.py` (`open_my_profile_dialog`)

---

## Architecture reminders

- Chronos UI → `logic.*` only (no SQL in `gui/`)
- Validators are single source of truth for pre-checks
- Primary pages: `gui/pages/*` · Legacy: `ui/pages/*` · Registry must match disk (see trust checklist)

---

## Open / next priorities

1. **Chronos depth (P2)** — dual-rate features; browser-prove leave approve / payroll lock before `"complete"`
2. **Continue live UI feedback** on `gui/`
3. **Production credential / LDAP** — one true story for `must_change_password` + optional LDAP
4. ~~**Evaluation build**~~ — frozen package tooling exists (`scripts/build_frozen_eval.py`)
5. **Tier 2 logic** — bidding/callbacks/certs; do not claim Chronos shipped without page proof
6. ~~Token prune~~ — done 2026-07-12 (caveman, lean route, skills `_archive`)

---

## Key symbols (current — verify paths exist before editing)

```
gui/app.py, gui/shell.py, gui/pages/*   — Chronos primary UI
logic/scheduling*.py, logic/requests.py, logic/payroll/*, …
validators.py (+ validators_*.py), database.py, config.py, cli.py
slices/registry.py                      — paths OK (slice-check clean 2026-07-12)
ui/pages/*                              — legacy CTk pages (secondary)
ui/widgets.py, ui/theme.py              — legacy helpers may still be referenced by tests

DELETED / do not cite as current:
  logic.py (monolith)
  ui/dashboard_pages.py, ui/requests_pages.py, ui/payroll_pages.py,
  ui/schedule_pages.py, ui/officers_pages.py, ui/feature_pages.py, …
```

---

## How to update this file

At end of a session or feature:

1. Bump **Last updated** date and verification command result
2. Add a subsection under **Recent session work** (or start a new dated section)
3. Move completed items out of **Open / next priorities**; add new follow-ups
4. Note any **gotchas** (UI patterns, env quirks) future agents must not re-learn

Do not duplicate full scheduling rules here — link to `SCHEDULING_RULES.md` and `.grok/rules/` instead.
