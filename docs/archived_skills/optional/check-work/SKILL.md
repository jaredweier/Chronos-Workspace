---
name: check-work
description: >
  Self-verify Dodgeville PD changes before handing off — review diff scope,
  run preflight/slice verify/check, confirm layer boundaries. Use when asked
  to check work, verify changes, or self-verify.
---

# Check Work (project-local)

Run `python dev.py cheap-check` first (free, ~5s). See `docs/ZERO_AGENT_USAGE.md`. Do not spawn subagents for verify steps.

## Steps (in order)

0. **Cheap gate** — `python dev.py cheap-check`
1. **Scope** — `python dev.py usage-brief <slice-id>` or `slice-map -v`
2. **Diff review** — only `touch_together` files changed (+ shared kernel if cross-cutting)
3. **Preflight** — `python dev.py preflight`
4. **Slice verify** — `python dev.py verify-slice <id>` when slice is known
5. **Full gate** — `python dev.py check` (add `--with-refactor` after structural edits)
6. **UI touched?** — `python dev.py ui-smoke` minimum; `ui-exhaustive` for handler changes

## Red flags

- SQL in `ui/*.py` (except `backup_database` import in shell)
- Business rules inlined in UI or CLI
- `import logic` breakage — run `python dev.py logic-imports`
- Date-sensitive tests using bare `date.today()` for expectations

## Pass criteria

- `preflight` exit 0
- `check` exit 0
- No new items in audit failures
- HANDOFF priorities updated if meaningful chunk completed

## Commands cheat sheet

```bash
python dev.py session-start     # resume context
python dev.py preflight
python dev.py verify-slice roster
python dev.py check --with-refactor
python dev.py refactor-check
```
