# On-demand Grok rules

Not always-injected. Load only when the task needs them:

| File | When |
|------|------|
| `architecture.md` | data flow, modules, tables |
| `cli-reference.md` | `cli.py` / admin commands |
| `feature-map.md` | feature coverage matrix |
| `known-issues.md` | open product gaps |
| `scheduling-math.md` | rotation / bump / optimizer math |
| `ui-modern.md` | Chronos UI tokens / widgets |
| `subagents.md` | spawn policy detail |

**Always-on** (top of `.grok/rules/`): `auto-minimize.md`, `verify-policy.md`, thin stubs + `agent-routing.md`, `token-minimization.md`.
