# Subagent policy (value + cost)

**Auto-context OFF.** Routing is advisory. `@docs/AGENT_STABLE.md` · `@logs/agent_pack/latest.md`

## Policy (2026-07-20)
User: **tools, skills, and subagents allowed** when they improve development **or use less budget than primary**.

Spawn for **leverage and lower cost**, not habit.

## When to spawn
- Easy / mechanical work a cheaper agent can finish alone
- Parallel independent slices
- Explore/map large unknown areas when inline thrash would cost more
- Plan drafts for multi-step redesigns (primary reviews and owns ship)
- **Verify/gates** when a small/cheap agent + terminal is **cheaper** than primary running the full gate context
- Graphify / vision passes when cheaper or better ROI than primary doing the same
- User asks

## When NOT to spawn
- Subagent would cost **more** than primary doing the work
- Single-file greps, config one-liners, tiny renames (do inline)
- Rubber-stamp “check work” that re-reads everything without new evidence
- Duplicate primary’s open context for free

## Cost split (binding intent)
| Difficulty | Owner |
|------------|--------|
| Trivial / low | free/cheap secondary · Tab · mini · empty OSS |
| Medium routine | balanced secondary · skill-backed agent |
| High / trust-critical / sim math / ship call | **primary agent** keeps ownership |
| Verify / gates | cheapest path: terminal alone, cheap subagent, or primary — **min total cost** |
| Graphify / vision | only when cost/ROI beats primary |

Primary agent: **do hard stuff**; **delegate easy and cheaper gate runs**. Secondary returns short proof + residuals — primary does not claim “fixed” without that proof (or own recheck when trust-critical).

## Archived skills
`docs/archived_skills/` stays archived. Need one → use temporarily → **return to archive** immediately after.

## Default roles (in-repo)
| Role | Path | Cost |
|------|------|------|
| Route | `python dev.py route-task` | free |
| Explore/map | subagent `explore` (read-only) when area large | cheap–balanced |
| Plan draft | subagent `plan` (read-only) for multi-step redesign | balanced |
| Verify (if cheaper) | small agent + `python dev.py verify --tier …` | free–cheap |
| Scheduling | skill `scheduling-logic` | balanced+ |
| UI Chronos | skill `ui-development` | balanced |
| UI copy | skill `ui-aesthetics-review` + `ui-review` | cheap |
| UI vision | skill `ui-vision-review` when ROI beats primary | vision |
| QA | terminal `verify` / skill `qa-verify` | free |
| Payroll | skill `payroll-timecard` | balanced |
| CLI | skill `cli-operations` | cheap |
| Security | skill `security` | balanced |
| Build | skill `build-deploy` | balanced |

**External browser agents:** prefer Playwright scripts; escalate only when cheaper path fails — `docs/UI_AGENTS_CATALOG.md`.

**Sufficiency:** stop when confident. Escalate cost only when lower tier fails. Kill processes you start.
