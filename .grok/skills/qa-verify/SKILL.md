---
name: qa-verify
description: Verification ladder — cheap-check, verify tiers, audit, scenarios. Terminal only; no subagents for gates.
---

# QA / Verify Subagent

Do not use a subagent for gates below — run terminal commands (free).

## Verification ladder (fast â†’ thorough)

| Step | Command | When |
|------|---------|------|
| 0 | `python dev.py cheap-check` | Every edit â€” ~5s |
| 1 | `python dev.py preflight` | Before commit â€” ~15s |
| 2 | `python dev.py verify-slice <id>` | After touching one slice |
| 3 | `python dev.py check` | Before marking work done â€” ~70s |
| 4 | `python dev.py verify-features` | Release / large UI change |

## Slice-targeted verify

```bash
python dev.py slice-map -v              # find slice id
python dev.py verify-slice payroll-timecard
python dev.py verify-slice day-off-requests
```

Runs only the `verify` commands listed in `slices/registry.py` for that slice.

## Regression sources

- `audit.py` â€” 10 AUD-* checks (`python dev.py audit`)
- `scripts/scenarios.py` â€” S-01..S-11 (`python dev.py scenarios`)
- `tests/test_regressions.py` â€” bug-specific unit tests
- `tests/test_permissions.py` â€” role matrix

## UI verification

```bash
python dev.py ui-smoke          # headless, all pages
python dev.py ui-functional     # handler exercise on test DB
python dev.py ui-exhaustive     # full tab coverage
python dev.py ui-review         # spelling, wording, theme
python dev.py ui-live           # visible screenshots (optional)
```

## Workflow after a fix

1. Reproduce failure with smallest command (unittest or `dev.py audit`)
2. Fix in correct layer (validators â†’ logic â†’ UI)
3. Add regression test or audit entry if user-reported
4. `python dev.py preflight`
5. `python dev.py verify-slice <id>` if slice known
6. `python dev.py check`

## Do not

- Mark complete on `imports` alone
- Skip `audit` after scheduling logic changes
- Run `ui-exhaustive` for typo-only fixes (use `ui-review` or `check`)
