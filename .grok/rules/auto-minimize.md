# Auto-minimize (Grok — always on)

`@logs/agent_pack/latest.md` · `@docs/AGENT_STABLE.md` · `@AGENTS.md`

**Bootstrap:** `python dev.py agent-kit` → `@logs/agent_kit/latest.md`
**Chain:** `route-task` (once) → `usage-brief` → `outline`/`symbol` → edit → `verify --tier fast` · ship: `check` + `honest_gate`
**Caveman:** short bullets; no research tax unless user asks.

**Hard bans**
- No explore/plan subagents. No subagents for verify/gates.
- Max **1** skill body per task (only if route printed it).
- Max **1** `route-task` per task. Batch edits; no thrash reads.
- Never open `docs/archived_skills/` unless user names that skill.

**Sufficiency:** stop when confident. No whole-repo reads.

**Improve:** prompts/index change → `python dev.py token-improve` → `token-audit --strict`
