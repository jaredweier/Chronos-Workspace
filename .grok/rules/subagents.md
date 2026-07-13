# Subagent policy (token budget)

**Auto-context OFF.** Routing is advisory. `@docs/AGENT_STABLE.md` · `@logs/agent_pack/latest.md`

## When to spawn
- User asks, **or** parallel work > ~5 minutes.
- Never for greps, single-file reads, config edits, or verify gates.
- Never explore/plan subagents — use Grep/Read inline.

## Default roles (in-repo only)
| Role | Path | Cost |
|------|------|------|
| Route | `python dev.py route-task` | free |
| Scheduling | skill `scheduling-logic` | balanced+ |
| UI Chronos | skill `ui-development` | balanced |
| UI copy | skill `ui-aesthetics-review` + `ui-review` | cheap |
| UI vision | skill `ui-vision-review` after static gates | vision |
| QA | terminal `verify` / skill `qa-verify` | free |
| Payroll | skill `payroll-timecard` | balanced |
| CLI | skill `cli-operations` | cheap |
| Security | skill `security` | balanced |
| Build | skill `build-deploy` | balanced |

**External browser agents:** user-escalation only — see `docs/UI_AGENTS_CATALOG.md`. Prefer Playwright scripts over vision agents.

**Sufficiency:** stop when confident. Escalate cost only when lower tier fails.
