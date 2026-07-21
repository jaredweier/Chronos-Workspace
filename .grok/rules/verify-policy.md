# Verification policy (mandatory — prevents test theater)

> State: `logs/last_verify.json` · Ship gate: `python dev.py verify --tier check`

## One ladder — strict supersets

| Tier | Command | When | Honest for ship? |
|------|---------|------|------------------|
| **core** | `python dev.py verify --tier core` | After logic/validators/gui/database edits | No (but runs product unittests) |
| fast | `python dev.py verify --tier fast` | After light edits (includes **core-test**) | No |
| preflight | `python dev.py verify --tier preflight` | Pre-commit, handoff (+ **graphify-gate**) | No |
| **check** | `python dev.py verify --tier check` | Before claiming done (product discover) | **Yes** |
| full | `python dev.py verify --tier full` | Release candidate | Yes |
| release | `python dev.py verify --tier release` | Full regression | Yes |
| agent-meta | `python dev.py verify --tier agent-meta` | After agent/token/route/policy tooling edits | No |

Aliases `cheap-check` → fast. Tiers cannot diverge from `scripts/verify.py`.
`core-test` modules: logic, validators, regressions, simulator_constraints, coverage_optimizer, payroll.
Ship `test` step **excludes** `tests/agent_meta/` (token/route/verify structure).

## Never (test theater)

1. **Claim success on fast/preflight alone** when UI, security, or scheduling logic changed.
2. **Patch a test to match broken behavior** without fixing the root cause in production code.
3. **Add a gate step that subprocesses a weaker gate** — all tiers use `scripts/verify.py`.
4. **Skip `check` before handoff** when the task touched `logic/*`, `validators.py`, `ui/*`, or `database.py`.
5. **Report "audit 10/10" as product health** — audit covers 10 historical regressions only.

## Always

1. **Reproduce the real failure** (manual steps or failing gate) before writing a fix.
2. **Run tier ≥ change scope:**
   - copy/theme only → fast
   - logic/validators/gui/database → **core** minimum; **check** before done
   - UI pages/login → check (full unittest + readiness)
3. **Read `logs/last_verify.json`** after any gate — `honest_gate: false` means not ship-ready.
4. **Fix root cause** — no workarounds, env hacks, or probe-only patches.

## Agent churn prevention

- Do not re-read whole repo after a passing fast tier.
- Verify/gates: primary **or** cheaper subagent/terminal — pick **lower total cost**; no expensive subagent tax by default.
- One verification run per edit batch; escalate tier only when fast fails or scope demands check.
