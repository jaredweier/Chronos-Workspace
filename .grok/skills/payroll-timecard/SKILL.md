---
name: payroll-timecard
description: Payroll/timecard domain — periods, locks, overnight, holidays. logic/payroll*, gui finance pages.
---

# Payroll & Timecard Subagent

## Scope

- `logic/payroll.py` â€” pay periods, timecard CRUD, lock/unlock, imports
- `ui/payroll_pages.py` â€” Payroll tab, Timecard tab
- `logic/operations.py` â€” holidays (`get_holidays_in_range`)
- `tests/test_payroll.py`, `tests/test_timecard_schedules.py`
- Slice: `payroll-timecard` in `slices/registry.py`

## Pay period rules

- 14-day periods aligned to department calendar (`get_pay_period`)
- `lock_pay_period` blocks edits for that period only
- `is_future_pay_period` compares normalized period starts â€” pass explicit `reference=` in tests
- Overnight shifts: `time_in`/`time_out` span midnight; hours attach to shift **start** period

## Date-sensitive testing

Use fixed reference dates â€” never rely on `date.today()` in assertions:

```python
from datetime import date
ref = date(2026, 6, 30)
logic.lock_pay_period(ref)
logic.is_future_pay_period(next_start, reference=ref)
```

Use `tests.helpers.reference_today()` or `TEST_REFERENCE_DATE` instead of `date.today()` in assertions.

## OPEN research (payroll math)

Any public FLSA/comp-time/payroll source is allowed (DOL fact sheets, OPM, municipal policies, vendor marketing math).
Also: `python dev.py math-domain research-queries "FLSA 7k"` Â· `fr-domain flsa` Â· web_search freely.
Deposit: `math-domain learn` or `fr-domain learn`.

## Workflow

1. Find slice: `python dev.py slice-map -v` â†’ `payroll-timecard`
2. Fix validators if input invalid; else `logic/payroll.py` / `labor_compliance.py` / `banked_time.py`
3. Wire UI in `gui/pages/finance.py` (primary) or legacy `ui/` only if needed
4. `python dev.py verify-slice payroll-timecard` or targeted unittests
5. `python dev.py verify --tier check` before ship

## Key symbols

| Area | Functions |
|------|-----------|
| Periods | `get_pay_period`, `get_adjacent_pay_period`, `is_future_pay_period` |
| Lock | `lock_pay_period`, `unlock_pay_period`, `is_pay_period_locked` |
| Timecard | `save_timecard_entry`, `prefill_timecard_from_schedule` |
| Summary | `get_pay_period_hours_summary`, `_summarize_pay_period_hours` |
| Holidays | `get_holidays_in_range`, `ui` â˜… markers on timecard |

## Do not

- Lock payroll without supervisor/admin permission check
- Use `date.today()` in unit test expected values without `reference=`
- Put pay calculation rules in UI
