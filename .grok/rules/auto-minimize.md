# Auto-minimize (Grok — always on)

**FIRST with caveman** at every session open. Do not wait for user paste.

**Sufficiency:** stop gathering when confident. Hub: `docs/AGENT_STABLE.md`.

## Caveman (pair with this file)
Short bullets. No preamble, no recap, no "let me". Prose only if user asks explain/docs.

## Token minimize (absolute)
- Fewest tool calls/tokens that still finish the task **fully and well**
- Prefer **1 thing at a time**; parallel/background OK when it clearly speeds real work — check in if unsure
- Max **1** `route-task` / task · Load skills **when they help** (not every turn)
- **Tools / skills / subagents allowed** when they improve quality, speed, or correctness **or cost less than primary**
- **Cost split:** easy/mechanical → cheap/free agents or models; hard product/logic/architecture → primary (this) agent
- Subagents for **verify/gates OK only if cheaper** than running the gate yourself
- **Graphify / vision OK only if cheaper** (or clearly better ROI) than primary doing the same work
- Stop when confident · No whole-repo thrash · No thrash re-reads after green fast
- Kill every process you start when its task is done

## Cost-tier work split
| Work | Who |
|------|-----|
| Outline, grep, renames, copy polish, simple docs, format | cheap / free / Tab / mini |
| Multi-file UI wire, routine tests, pack scaffolding | balanced secondary agent |
| Simulator math, optimizer honesty, architecture, ship judgment, trust-critical fixes | **primary agent** (this session) |
| Verify ladder | primary **or** cheaper subagent/terminal — pick lower total cost |

`python dev.py route-task` still picks cheapest **fit**; primary may override up when task is hard, or **delegate down** easy subtasks.

## Archived skills
- Live skills: `.grok/skills/*`
- Archive: `docs/archived_skills/` — **leave archived by default**
- Need one → copy/load only what you need → **put it right back in the archive** when done
- Do not leave archive skills sitting in live paths after the task

## Chain
`route-task` (once) → skill if needed → outline/symbol → edit (or delegate easy slice) → gate:
- light → `verify --tier fast`
- logic/validators/gui/database → `verify --tier core` then ship `check`
Ship: `verify --tier check` + `honest_gate: true` — never claim done on fast alone

## Paste / auto
`@AGENTS.md` · `@logs/SESSION_CONTRACT.md` (caveman+minimize lead) · `@logs/agent_pack/latest.md` · `@docs/AGENT_STABLE.md`
Landing: `@logs/NEXT_SESSION_BRIEF.md` only (HANDOFF/NEXT_AGENT_PROMPT are stubs)

## Hard bans
- Do not leave archived skills un-archived after use
- Domain rules: load `.grok/rules/on-demand/*` only when needed (not every turn)
- No thrash graphify/vision “just because” — only when cost/ROI beats primary

## Improve
Prompts/index change → `python dev.py token-improve` → `token-audit --strict`
