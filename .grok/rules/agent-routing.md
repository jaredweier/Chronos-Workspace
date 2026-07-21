# Agent routing (Grok)

`python dev.py route-task "<task>"` → **one primary agent + cost_tier + one skill**.

Auto-context OFF · cheapest **honest** fit · any LLM allowed.
Policy: `@docs/AGENT_ROUTING.md` · external (user-only): `@docs/UI_AGENTS_CATALOG.md`

## Rules
- Run route-task **once** per task; start from recommended `cost_tier`.
- **Delegate down:** easy subtasks → free/cheap agents or models.
- **Keep up:** hard product, sim math, architecture, trust-critical ship → primary agent.
- free/cheap: Tab/Ask/terminal/mini; vision only when ROI/cost beats primary.
- Load skill body when it improves the edit.
- Tools / skills / subagents OK when they improve quality/speed **or cost less**.
- **Verify/gates:** subagent OK **if cheaper** than primary running the gate.
- **Graphify / vision:** same cost/ROI test — not default every turn.
- **Archived skills:** use only while needed, then put back in `docs/archived_skills/`.
- Chain stays lean; parallel only when slices independent.

**Sufficiency:** stop gathering when confident. Hub: `docs/AGENT_STABLE.md`.
