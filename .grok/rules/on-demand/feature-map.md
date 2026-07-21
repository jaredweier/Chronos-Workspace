# Feature Map (static reference)

> Grok: `@logs/agent_pack/latest.md` · `@docs/AGENT_STABLE.md` · **Sufficiency:** stop when confident; no extra reads unless contradictory or incomplete.

Run `python dev.py feature-map` for a live check against the codebase.

## Coverage matrix

| Feature | UI | CLI | Key logic |
|---------|----|----|-----------|
| Officer roster | Officers tab | `officers *` | `add_officer`, `update_officer` |
| Day-off requests | Requests tab | `requests *` | `create_day_off_request`, `process_day_off_request` |
| Shift swaps | Swaps tab | `swaps *` | `process_shift_swap` |
| Manual coverage | Updated Schedule | `overrides assign` | `create_manual_coverage_override` |
| Notifications | Notifications tab | `notifications *` | `get_notifications`, `mark_notification_read` |
| Payroll / timecard | Payroll, Timecard | `pay-period`, `csv payroll` | `save_timecard_entry`, `lock_pay_period` |
| Schedules / Gantt | Base, Updated, Timeline | `export schedule`, `schedule-diff` | `get_officer_schedule_window` |
| iCal export | Timeline | `export ical` | `export_officer_schedule_ical` |
| User accounts | User Accounts | `users *` | `create_app_user`, `authenticate_user` |
| Reports | Dashboard, Reports | `reports *` | `get_dashboard_insights` |
| Availability | Availability | `availability *` | `add_officer_availability` |
| Open shifts | Dashboard | `open-shifts *` | `create_open_shift` |
| Simulator | Simulator tab | — | UI-only |
| Backup | Admin setup | `backup` | `database.backup_database` |

## Intentional gaps

- **Simulator** — supervisor training tool; no CLI equivalent needed.
- **GUI-only polish** — login dialog, setup wizard, photo upload have no CLI (by design).

## When adding a feature

1. Implement `validators` → `logic`
2. Wire UI tab with permission gate
3. Add `cli.py` command if admins need scripting
4. Update `scripts/feature_map.py` FEATURES list
5. Add smoke step if end-to-end critical
