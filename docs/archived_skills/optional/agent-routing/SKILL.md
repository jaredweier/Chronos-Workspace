---
name: agent-routing
description: >
  Route Chronos/Dodgeville tasks by complexity to the cheapest fit agent and model.
  Includes multi-UI-agent chains (static, Chronos NiceGUI, vision, browser OSS).
  Auto-context OFF — load skills on demand.
---

# Agent Routing

## Policy

1. **Auto-context OFF** — no full HANDOFF/skills dump unless routed or @-mentioned.
2. **Any agent/LLM allowed** — pick by fit; prefer **lowest cost_tier**.
3. **Route first** — `python dev.py route-task "<task>"`.
4. **UI work** — follow printed **ui_lane** and **agent chain** (cheap→expensive). Catalog: `docs/UI_AGENTS_CATALOG.md`.

## Complexity → cost (auto)

| Tier | Cost | Mode | Model |
|------|------|------|-------|
| verify | free | terminal | none |
| trivial | free | Tab | none |
| low | cheap | Ask | mini / Flash / Haiku / Grok Fast |
| medium | balanced | Agent | Sonnet / Grok / Composer |
| high | flagship | Plan→Agent | Opus / reasoning |
| vision | vision | Agent+1PNG | vision **after** ui-review |
| browser | vision | Playwright first | then browser-use / Skyvern |

## UI agents (built-in chain)

| Lane | OpenCode agent | Escalate (OSS) |
|------|----------------|----------------|
| copy | `ui-static-reviewer` | — |
| chronos | `ui-chronos` | Playwright → browser-use |
| layout | primary + ui-development | Cline |
| vision | `ui-vision-reviewer` | OmniParser → browser-use |
| browser | ui-chronos + catalog | Stagehand → Skyvern |

Never vision for typo/Title Case. Never flagship for verify.

## Domain → skill

| Domain | Skill |
|--------|-------|
| bump, rotation, day-off | `scheduling-logic` |
| payroll, timecard | `payroll-timecard` |
| auth, permissions | `security` |
| Chronos gui / NiceGUI | `ui-development` |
| copy / theme | `ui-aesthetics-review` |
| screenshots | `ui-vision-review` |
| cli, dev.py | `cli-operations` |
| build, .exe | `build-deploy` |
| refactor | `refactor` |
| unsure | `dodgeville-scheduler` |

**UI visual design XOR:** for look/layout aesthetics, also load **either** `frontend-design` **or** one taste-skill (e.g. `design-taste-frontend` / `redesign-existing-projects`) — **never both** unless the user says so. Defaults: Chronos polish → taste; greenfield brand → frontend-design. See `AGENTS.md` § UI design skills.

## Context

`logs/agent_pack/latest.md` · `docs/AGENT_STABLE.md` · `docs/AGENT_ROUTING.md` · `docs/UI_AGENTS_CATALOG.md` · `docs/TOKEN_PERFORMANCE.md`
