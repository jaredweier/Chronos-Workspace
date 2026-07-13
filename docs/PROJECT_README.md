# Dodgeville PD Scheduler — Project Status & Guide

This document summarizes **what the app does today**, **recent changes**, **how to run and test it**, and **where development is headed**. It mirrors the agent handoff in [`HANDOFF.md`](HANDOFF.md) in a form meant for humans and new contributors.

**Last updated:** 2026-07-13
**Tests:** `python -m unittest discover -s tests -p "test_*.py"` — **385 OK** (2026-07-13; re-prove after edits). Ship: `python dev.py verify --tier check` + `honest_gate: true`.
**Agent tokens:** `AGENTS.md` caveman + `docs/archived_skills/` (not discoverable). `python dev.py token-audit --strict`.

---

## What this application is

Scheduler for the Dodgeville Police Department: 14-day rotation, day-off requests with bumping, shift swaps, payroll/timecards, officer roster, notifications, exports, and schedule views. **Primary UI:** Chronos NiceGUI (`gui/`). Legacy CustomTkinter in `ui/pages/`. Domain rules in `logic/*` + `validators` + SQLite.

---

## Quick start

**One-click (Windows):** double-click [`START HERE.bat`](../START%20HERE.bat) at the project root. First run builds the app automatically; later runs open the scheduler immediately.

```bash
pip install -r requirements.txt
python main.py
```

| Role | Username | Password |
|------|----------|----------|
| Administration | `admin` | `admin` |
| Supervisor | `supervisor` | `supervisor` |
| Officer | `officer` | `officer` |

Login is **required** by default. For local testing without the sign-in screen: `set SCHEDULER_AUTO_LOGIN=1` (Windows) or `SCHEDULER_AUTO_LOGIN=1 python main.py`.

**Full verification:**

```bash
python dev.py check      # tests + audit + import smoke
python dev.py doctor     # environment and schema
python dev.py smoke      # fast integration smoke
python dev.py slice-map -v   # vertical slice registry (feature-oriented work)
python dev.py slice-check    # validate slice bindings
```

**Vertical slices:** Features are organized by user capability, not layer. See [`docs/VERTICAL_SLICES.md`](VERTICAL_SLICES.md) and `slices/registry.py`. When changing a feature, edit only that slice’s `touch_together` files.

**Scheduling rules reference:** [`SCHEDULING_RULES.md`](../SCHEDULING_RULES.md)

---

## How to work with the agent

Use this to get faster, more accurate help with less usage.

**Start a new chat after compression:**

> Read `docs/HANDOFF.md` and continue from open priorities.

**Message template:**

```text
Goal: [one sentence]
Tab/area: [e.g. Time Off, Officers]
Role: [admin / supervisor / officer]
Repro: [steps]
Expected: …
Actual: …
Constraints: [files not to touch; no refactors]
Verify: [dev.py check / GUI only / specific tab]
```

**Tips**

| Do | Avoid |
|----|--------|
| One scoped goal per message | “Fix everything” or vague “it’s broken” |
| Batch related fixes in one request | Many tiny ping-pong messages |
| Say which tab and login role | Guessing without repro steps |
| `python dev.py check` for code changes | “Make sure the whole app works” every time |
| Correct scope early (“chat only, not the app”) | Letting the wrong approach run long |
| Screenshots for UI layout/dropdown bugs | Long back-and-forth describing pixels |

**Session compression (your Cursor user rule):** at ~150k tokens or when you say compress/checkpoint — agent updates `HANDOFF.md` + `PROJECT_README.md` first, refreshes `FULL_PROJECT_CODE.txt` only if code changed, then summarizes. Not stored in the application codebase.

---

## Recent changes (July 2026)

### Scheduling ops roadmap (Tier 1 + Visual polish)

- **Command Post:** coverage gap board, on-duty-now strip, FLSA hours-watch alerts, officer **My Week** card, role-specific quick actions.
- **LE rules:** 8-hour minimum rest between shifts (supervisor can override from manual review); court and training request types with distinct schedule colors.
- **Reports:** equitable OT ledger on Ops Reports.
- **Notifications:** officers notified when the current monthly schedule is synced.
- **Time Off:** approve confirmation shows bump/coverage summary; ledger has type and status filter chips.
- **Roster:** qualification (title) badges and pay-period hours on list rows.
- **Schedules:** unsynced current-monthly empty-state CTA; Gantt empty-state with next-step button.

---

## Recent changes (June 2026)

### Payroll — pay period totals

- Payroll tab shows a **prominent total hours** for the current pay period.
- **More Details** expands to show breakdowns (night differential, comp time, classifications, etc.).
- Backend: `get_pay_period_hours_summary()` in `logic.py`; UI uses `ExpandableSection` in `ui/widgets.py`.

### Schedule tabs — renamed and clarified

| Previous name | Current name | What it shows |
|---------------|--------------|---------------|
| Base Rotation | **Original Monthly Schedule** | Auto-built from rotation, squad duty, and officer shifts. **Locked** after first generation — it does not change. |
| Live Duty Roster | **Current Monthly Schedule** | Live view with approved time off, bumps, swaps, and manual coverage. Use **Sync Current Monthly Schedule** to refresh. |

Calendar cells emphasize **officer name and shift times**; squad appears as a small **Sq A / Sq B** badge. Up to four officers per day in the grid; click a day for the full roster below.

### Time Off — request ledger

The Time Off tab includes a **Day Off Requests** ledger at the bottom:

- **Submitted** timestamp, **Employee**, **Type**, **Date Off**, **Status**
- Officers see **only their own** requests; supervisors and administration see **all** employees.

### Officers — title, squad, and shift editing

**Problem:** Dropdowns for Title, Squad, and Shift did not work when placed inside a scrollable form (CustomTkinter limitation).

**Solution:** Those three fields sit in a **fixed header bar** above the scrollable officer form, using read-only combo boxes. Saving reloads the officer record correctly.

### Scroll performance

Several screens felt laggy when scrolling. Optimizations applied:

| Screen | Change |
|--------|--------|
| Monthly schedules | One label per calendar day instead of many nested widgets; roster loaded once per month |
| Time Off queue | Removed heavy bump simulation from every row; use **Preview** for coverage detail |
| Day-off ledger | Skips full rebuild when data has not changed |
| Officer list | Faster selection highlighting via in-memory cache |
| Payroll period | Shows first 3 timecard lines per officer, then “+N more entries” |

If a specific tab still feels slow, note which one — Gantt and some dashboard lists were not part of this pass.

### Project documentation and full code dump

- **[`HANDOFF.md`](HANDOFF.md)** — for agents resuming work on the project
- **[`FULL_PROJECT_CODE.txt`](FULL_PROJECT_CODE.txt)** — entire project in one file (~29 MB)
- **Regenerate dump:** `python scripts/export_project_code.py`
- **Includes:** source, database, `build/`, `__pycache__/` (binaries encoded as base64)
- **Excludes:** `dist/` (large PyInstaller output — rebuild with `build.bat`)

---

## Project layout (high level)

```
MyProject/
├── main.py                 # Launches Chronos (gui/)
├── logic/                  # Domain package (scheduling, payroll, requests, …)
├── validators.py           # Facade + validators_* modules
├── database.py             # SQLite schema and connection
├── cli.py                  # Admin CLI (calls logic.*)
├── dev.py                  # Tests, audit, doctor, smoke, verify
├── gui/                    # Primary UI — Chronos NiceGUI
│   ├── app.py, shell.py
│   └── pages/              # leave, roster, schedules, finance/, …
├── ui/pages/               # Legacy CustomTkinter (secondary)
├── tests/
├── docs/
│   ├── PROJECT_README.md
│   ├── HANDOFF.md
│   └── archived_skills/    # Not agent-discoverable
└── SCHEDULING_RULES.md
```

**Architecture rule:** UI calls `logic.*` only — no SQL or scheduling rules in `gui/`.

---

## UI tip for developers

Do **not** put `CTkComboBox` controls inside `CTkScrollableFrame` for fields users must edit. Use a sticky header (see `ui/officers_pages.py`) or a dialog instead.

---

## What’s next

1. Continue polish from live UI testing (user feedback on specific tabs)
2. Further slim `ui/app.py` — extract profile dialog; page mixins already in place
3. Production login — auto-login off by default (done); optional LDAP / forced password change on demo accounts
4. Refresh evaluation build (`build_test.bat` / `build_quick.bat`)
5. Optional: more scroll tuning on Gantt, notifications, or dashboard if needed

---

## Useful commands

```bash
python main.py                    # GUI
python cli.py officers list       # Roster via CLI
python cli.py requests pending    # Pending time-off requests
python dev.py scenarios           # Scheduling scenarios S-01..S-11
python dev.py feature-map         # UI / logic / CLI coverage map
python dev.py ui-review           # UI wording and aesthetics report
python scripts/export_project_code.py  # refresh FULL_PROJECT_CODE.txt
python -m unittest discover -s tests -v
```

---

## Related documentation

| Document | Audience |
|----------|----------|
| [`DEPLOYMENT.md`](DEPLOYMENT.md) | Roll out to 8 PCs with one shared schedule; VPN/remote access options |
| [`deploy/Start Dodgeville Scheduler.bat`](deploy/Start%20Dodgeville%20Scheduler.bat) | IT launcher — copy to server share next to the `.exe` |
| [`FULL_PROJECT_CODE.txt`](FULL_PROJECT_CODE.txt) | Full project dump (~29 MB): source, database, `build/`, `__pycache__/` (binaries as base64; `dist/` omitted). Regenerate: `python scripts/export_project_code.py` |
| [`HANDOFF.md`](HANDOFF.md) | Agents resuming a session — update when finishing significant work |
| [`AGENTS.md`](../AGENTS.md) | Coding rules and layer boundaries |
| [`SCHEDULING_RULES.md`](../SCHEDULING_RULES.md) | Department scheduling scenarios and rules |
| [`.grok/rules/`](../.grok/rules/) | Architecture, CLI reference, known issues |

When you complete a feature or fix, update **both** `HANDOFF.md` and this file (or ask your agent to update them together).
