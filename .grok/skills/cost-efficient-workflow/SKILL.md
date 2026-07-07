---
name: cost-efficient-workflow
description: >
  Minimize LLM/API usage for Dodgeville PD Scheduler — prefer free dev.py gates,
  slice-scoped reads, static UI review, and pre-commit before vision agents.
  Use when asked to reduce costs, usage rates, or token spend (optional — not mandatory).
---

# Cost-Efficient Workflow (optional budget tier)

**Primary routing:** use `agent-routing` skill first. This skill is for budget-conscious paths only.

## Golden rule (when minimizing spend)

Prefer free terminal gates before LLM verify loops.

## Tier 0 — always free (do first)

| Command | Time | Use |
|---------|------|-----|
| `python dev.py cheap-check` | ~5s | After every edit |
| `python dev.py usage-brief <slice>` | instant | Before reading files |
| `python dev.py token-improve` | instant | Find new savings (mandatory if prompts/index change) |
| `python dev.py token-minimize` | ~5s | Scan index + audit artifacts |
| `python dev.py fix-hint` | ~5s | After any red gate |
| `pre-commit run` | ~15s | Before commit |
| GitHub CI on push | remote | Replaces Agent-as-CI |

## Verification ladder

| Step | Command | LLM cost |
|------|---------|----------|
| 1 | `cheap-check` | $0 |
| 2 | `preflight` | $0 |
| 3 | `verify-slice <id>` | $0 |
| 4 | targeted `unittest` | $0 |
| 5 | `ui-smoke` / `ui-review` | $0 |
| 6 | `ui-diff --quick` | $0 |
| 7 | `check` | $0 (handoff only) |
| 8 | `ui-observe` (no `--live`) | Low |
| 9 | `ui-observe --live` | High — last resort |

## Cursor-specific (minimize Pro credit pool)

- **Tab** for typos, imports, boilerplate (unlimited, no credits)
- **Ask mode** for "how does X work?" — not Agent
- **Auto model** for mixed tasks (cheaper routing)
- **New chat** per feature; `@Past Chats` instead of pasting history
- **Plan mode** (`Shift+Tab`) — approve plan once, avoid fix loops
- Slash: `/preflight`, `/check-free`, `/usage-brief`, `/slice-fix`
- Rules: `.cursor/rules/token-minimization.mdc` (`alwaysApply: false` — @ mention only)
- Index: `.cursorignore` excludes logs, dist, 78 PNG baselines, FULL_PROJECT_CODE dump

## Grok / subagent rules

- **Never** spawn subagents for `cheap-check`, `preflight`, `audit`, `slice-check`
- Load domain skill + this skill only — not whole `.grok/` tree
- Read `docs/HANDOFF.md` (20 lines) + `usage-brief` output — not transcript dumps
- UI vision skill only after `ui-review` + `ui-diff --quick` fail

## Context scope

```bash
python dev.py slice-map -v
python dev.py usage-brief day-off-requests
python dev.py context-window status
```

Edit/read **only** printed `touch_together` paths. Context policy: `docs/AGENT_STABLE.md` § Context window — ephemeral tools prune after 2 turns; summarize @ 6000t.

## UI observation ladder

```
ui-review → ui-diff --quick → ui-diff (full) → ui-observe → ui-observe --live
```

Share one failed `diff/*.png`, never 78 baselines.

## OpenCode

- `/cheap-check`, `/check`, `/usage-brief` — terminal only
- `compaction.prune: true` in `opencode.json`
- `qa-free` subagent for verify-only tasks

## Do not

- Re-run `check` after every line change
- Attach screenshots to prompts by default
- Read `logic/__init__.py` when slice-map names the module
- Use `verify-features` except release
- Use `ui-exhaustive` for typo fixes

Guides: `docs/ZERO_AGENT_USAGE.md`, `docs/USAGE_MINIMIZATION.md`
