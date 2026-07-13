# Dodgeville PD — Agent Rules

Auto-context off. Skills on demand. Primary UI: `gui/` Chronos.
**Bootstrap:** `python dev.py session-start` → `@logs/agent_kit/latest.md` · `@logs/agent_pack/latest.md`
**Stable:** `@docs/AGENT_STABLE.md`

## Caveman
Short bullets. No preamble. Prose only if user asks explain/docs.

## Route once
`python dev.py route-task "<task>"` → obey **cost_tier**. Load **one** skill if printed.

## Minimize
`usage-brief` → `outline`/`symbol` → edit **touch_together** → `verify --tier fast`
Ship: `verify --tier check` + `logs/last_verify.json` → `honest_gate: true`

## Hard bans
No explore/plan subagents. No subagents for gates. Max 1 skill body/task.
Never open `docs/archived_skills/` unless user names that skill.
Optional only if user asks: graphify · vision · OSS research.
