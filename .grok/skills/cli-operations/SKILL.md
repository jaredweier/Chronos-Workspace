---
name: cli-operations
description: Admin CLI and dev tooling — cli.py, dev.py, scripts/, exports, backups. No raw SQL in CLI.
---

# CLI & Operations Subagent

## Scope

- `cli.py` â€” admin commands (must call `logic.*`, never raw SQL)
- `dev.py` â€” developer gates
- `scripts/doctor.py`, `scripts/smoke_test.py`, `scripts/feature_map.py`
- `exports.py` / export functions in `logic.py`

## Dev commands

| Command | Purpose |
|---------|---------|
| `python dev.py doctor` | Python version, deps, imports, DB schema, assets |
| `python dev.py smoke` | Fast integration: day-off, user, iCal, PDF |
| `python dev.py feature-map` | UI â†” logic â†” CLI coverage table |
| `python dev.py check` | imports + 140 tests + audit |
| `python dev.py audit` | Scheduling regression audit only |
| `python dev.py reset-db` | Wipe and reseed |

## CLI surface (add new commands here)

When logic exists but CLI lacks coverage:

1. Add handler function in `cli.py`
2. Register subparser in `main()`
3. Document in `.grok/rules/cli-reference.md`
4. Update `scripts/feature_map.py` FEATURES list
5. Optionally add smoke step in `scripts/smoke_test.py`

## Recent CLI additions

- `users list|create|update|reset-password|activate|deactivate`
- `overrides assign`
- `export ical --officer-id N`

## Pattern for new export command

```python
def export_foo_cmd(args):
    result = export_foo(...)  # from logic
    if result.get("success"):
        print(f"Exported: {result['path']}")
    else:
        print(f"Failed: {result.get('message')}")
```

## Do not

- Duplicate validation in CLI â€” logic already validates
- Add SQL to cli.py â€” use logic CRUD functions
