# CLI Reference

> Grok: `@logs/agent_pack/latest.md` · `@docs/AGENT_STABLE.md` · **Sufficiency:** stop when confident; no extra reads unless contradictory or incomplete.

Admin CLI: `python cli.py <command> ...` — thin wrapper over `logic.*`.

## Officers

```bash
python cli.py officers list
python cli.py officers add --name "Jane Doe" --seniority 5 --squad A --shift-start 06:00 --shift-end 14:00
python cli.py officers update 3 --squad B --active 1
python cli.py officers delete 99
```

## Day-off requests

```bash
python cli.py requests pending
python cli.py requests list --status Pending --from 2026-07-01 --to 2026-07-14
python cli.py requests approve 12
python cli.py requests reject 12
python cli.py requests bulk-approve
python cli.py requests bulk-reject --notes "Department closure"
```

## Shift swaps

```bash
python cli.py swaps pending
python cli.py swaps approve 4
python cli.py swaps reject 4
```

## Manual coverage

```bash
python cli.py overrides assign \
  --original-officer-id 3 --replacement-officer-id 7 --date 2026-07-10 \
  --reason "Supervisor assignment"
```

## Users (login accounts)

```bash
python cli.py users list
python cli.py users list --active-only
python cli.py users create --username jdoe --password 'TempPass1!' --role Officer --officer-id 3
python cli.py users update 5 --role Supervisor --officer-id 8
python cli.py users update 5 --clear-officer-link
python cli.py users reset-password 5 --password 'NewPass1!'
python cli.py users deactivate 5
python cli.py users activate 5
```

## Exports

```bash
python cli.py export schedule --start 2026-07-01 --end 2026-07-14
python cli.py export ical --officer-id 3 --output exports/officer3.ics
python cli.py export payroll --officer-id 3
python cli.py export coverage
python cli.py export requests --status Pending
python cli.py csv roster --output exports/roster.csv
python cli.py csv payroll --period-start 2026-07-01
```

## Reports & maintenance

```bash
python cli.py reports summary
python cli.py reports coverage --start 2026-07-01 --end 2026-07-14
python cli.py reports overtime
python cli.py schedule-diff --year 2026 --month 7
python cli.py pay-period status
python cli.py pay-period lock
python cli.py backup
python cli.py audit-log list --limit 50
```

## Dev tooling (not cli.py)

```bash
python dev.py doctor
python dev.py smoke
python dev.py feature-map
python dev.py check
```
