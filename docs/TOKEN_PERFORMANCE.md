# Token Performance — Catalog + Findings (Chronos / Dodgeville)

**Purpose:** Make agents **faster and cheaper** by using free repo tools + proven context-engineering practice.
**Not optional flavor text.** Pair with `docs/NEXT_AGENT_PROMPT.md`.
**Last researched:** 2026-07-09 · **In-repo audit:** `python dev.py token-audit` → **75/75** after trust repair (re-run after tooling/doc changes).

---

## Core finding (industry + this repo)

| Finding | Implication for agents |
|---------|------------------------|
| **Every token competes for attention** (context engineering 2026) | Prefer *relevant* context over *more* context. Dumping the repo worsens quality and cost. |
| **Quality collapses when context is bloated** (~half-window / long noisy threads) | New chat per distinct task; summarize @ ~6k via `context-window`; don’t re-read fixed files. |
| **Just-in-time retrieval beats preloading** (Anthropic-style context eng.) | `outline` / `symbol` / `rg` / `usage-brief` first; full file only when editing. |
| **Lean always-on rules, fat on-demand docs** (Cursor agent best practices) | Point to files; never paste style guides or full HANDOFF into always-on rules. |
| **Plan → implement once beats 3 fix loops** | Multi-file / ambiguous work: short plan + inventory; then one edit batch. |
| **~80% of verify is free local** (this repo) | Run `dev.py` gates yourself; don’t burn Agent turns rediscovering imports/audit. |
| **Half-fixes cost more than full inventory** | One `rg` + fix-all is cheaper than “fixed one place” → user angry → 2 more sessions. |
| **Subagents multiply context** | Default: no subagent for gates. Spawn only when cheaper than primary. |
| **Images / graphify are expensive** | No thrash dumps; vision/graphify only when cost/ROI beats primary; static `ui-review` first when enough. |
| **Archived skills** | Use only while needed; put back in `docs/archived_skills/` after. |

---

## External sources (research, not decoration)

| Source | URL | Takeaway for Chronos agents |
|--------|-----|------------------------------|
| **Cursor — Agent best practices** | https://cursor.com/blog/agent-best-practices | Plan mode for hard tasks; new chat when confused; lean rules (pointers not dumps); skills on-demand; verifiable goals (tests/gates). |
| **Cursor — Plan mode** | https://cursor.com/blog/plan-mode | Research → questions → plan → approve → build. Revert+replan faster than patching a wrong branch. |
| **Addy Osmani — LLM coding workflow 2026** | https://medium.com/@addyosmani/my-llm-coding-workflow-going-into-2026-52fe1681325e | Pack **relevant** modules only; state out-of-scope; selective context > whole-repo ingest. |
| **Context engineering 2026** | https://pub.towardsai.net/state-of-context-engineering-in-2026-cf92d010eab1 | Progressive disclosure; compression; routing; hybrid sliding window (keep recent raw, summarize old). |
| **Token optimization / cost** | https://www.obviousworks.ch/en/token-optimization-saves-up-to-80-percent-llm-costs/ | JIT retrieval, compaction, sub-agents for isolation, avoid context bloat — **sub-agents only when isolation helps, not for free gates**. |
| **Context length techniques** | https://agenta.ai/blog/top-6-techniques-to-manage-context-length-in-llms | Truncation, routing, buffering, compression — prefer our free compress (`context-window summarize`) over re-reading history. |
| **Context window ≠ memory** | https://www.morphllm.com/llm-context-window-comparison | History is **re-billed every turn**; long agent loops explode cost — keep threads short, prune tool dumps. |
| **Cursor token economy (community)** | https://medium.com/coding-nexus/cursor-best-practices-2-0-adapting-to-the-token-economy-63b1073689ab | Disable idle MCP; modular files; paste **errors only** not full logs; ignore lockfiles/binaries. |
| **Lean rules / cost** | https://aisecurityguard.io/learn/how-to/how-to-reduce-cursor-ai-costs | Bloated always-on rules = 2–5k tokens **per request** forever; audit and delete dead rules. |
| **Reddit Cursor workflows** | https://www.reddit.com/r/cursor/comments/1mpdjt7/best_strategy_to_reduce_agent_token_usage_per/ | Feed exact files / slice; new chat per request when switching tasks. |
| **gitingest / repo2txt** | https://gitingest.com/ · https://github.com/abinthomasonline/repo2txt | Whole-repo dumps are **anti-pattern here** — use only if user forces; prefer `agent-pack` / `usage-brief`. |

**In-repo policy (authoritative for commands):**
`docs/AGENT_STABLE.md` · `docs/USAGE_MINIMIZATION.md` · `docs/ZERO_AGENT_USAGE.md` · `.grok/rules/auto-minimize.md` · `.grok/rules/token-minimization.md` · `.grok/rules/verify-policy.md`

---

## Free command ladder (run in terminal — $0 LLM)

### Session bootstrap (once)

```bash
python dev.py session-start          # handoff + doctor + agent-kit
# then @ logs/agent_kit/latest.md  OR  head of logs/agent_pack/latest.md
python dev.py route-task "<task>"    # once; cost_tier + UI agent chain (see UI_AGENTS_CATALOG.md)
```

### Before any multi-file read

```bash
python dev.py slice-map              # find slice id (or Chronos: gui/* + matching logic)
python dev.py usage-brief <slice>    # touch_together + verify hints
python dev.py outline path/to/file.py
python dev.py symbol <Name> [--slice id]
python dev.py read-budget path/to/file.py   # refuse full-read if budget huge unless editing
```

### After each edit batch

```bash
python dev.py verify --tier fast     # alias: cheap-check
# fail? →
python dev.py fix-hint
```

### Before claiming done (honest ship)

```bash
python dev.py verify --tier check    # only honest_gate for logic/UI/db
# read logs/last_verify.json — if honest_gate false, do NOT claim done
```

### Context / index hygiene

```bash
python dev.py context-window status
python dev.py context-window task "…"
python dev.py context-window decision "…"
# summarize when status says ≥ ~6000 tokens since summary
python dev.py token-improve          # → logs/token_improve/latest.md
python dev.py token-scan             # large still-indexed files
python dev.py token-minimize         # after index/prompt changes
python dev.py token-audit [--strict]
python dev.py agent-pack             # minimal pasteable pack
```

### UI without vision tax

```bash
python dev.py ui-review              # text/theme/spelling
python dev.py ui-diff --quick        # cheap pixels
python dev.py ui-smoke
# ONLY if still stuck:
python dev.py ui-observe             # then --live, ONE failed PNG
```

---

## Decision tree (execute in order)

```
Task arrives
  ├─ Can free gate answer? (doctor/smoke/fix-hint) → terminal only, stop
  ├─ Need code change?
  │    ├─ Identify slice or path (slice-map / user path)
  │    ├─ usage-brief + outline/symbol
  │    ├─ Inventory ALL instances (rg) if “fix X everywhere”
  │    ├─ One edit batch (all instances)
  │    ├─ verify --tier fast
  │    └─ Scope needs check? → verify --tier check + last_verify.json
  └─ Report: evidence + remaining gaps (never vague “all fixed”)
```

### Chronos-specific paths (avoid wrong tree)

| Task type | Prefer | Avoid |
|-----------|--------|--------|
| NiceGUI shell/pages | `gui/*`, `gui/static/chronos.css` | Full re-read of `ui/*` CTk unless parity |
| Date display | `validators.format_date`, `config.DATE_*`, `gui/clock.py` | Scattering strftime in pages |
| Brand/media | `gui/brand_assets.py`, `gui/pages/media.py` | Guessing upload API without NiceGUI docs |
| Scheduling rules | `logic/*`, `validators.py` | Duplicating rules in `gui/` |
| Framework API unknown | `docs/CHRONOS_SOURCES.md` + web | Trial-and-error loops |

---

## Token waste hall of shame (this project’s real failures)

| Waste | Why it hurts | Replacement |
|-------|--------------|-------------|
| Whole-repo / `FULL_PROJECT_CODE.txt` | 100k+ tokens, noise | `agent-pack`, `usage-brief`, outlines |
| Full-read 40–60KB logic files | ~10–16k tokens each | `outline` → read symbol range only |
| Re-running explore after green `fast` | No new info | Stop; escalate tier only on fail or ship |
| Subagent for verify | Double context + latency | Single terminal `dev.py verify` |
| “Fixed one date string” | User re-opens session | `rg` inventory → fix all → post-search list |
| Pasting full test logs | Bloat | Last 30 lines / assertion only |
| Vision for typo | Image tokens | `ui-review` |
| Long always-on rules | Tax every request | Pointers to AGENT_STABLE / this file |
| Continuing dead thread | Summarization noise | New chat + `@NEXT_AGENT_PROMPT` + pack |
| Re-implementing NiceGUI from memory | Retry loops | `CHRONOS_SOURCES.md` once |

---

## Performance ≠ fewer keystrokes only

**Efficient agent = correct work in fewer billable turns.**

1. **Inventory once** (`rg`/outline) beats three partial fix sessions.
2. **Plan multi-file work** (even 5 bullets) beats thrash.
3. **Free gates** beat LLM “does it import?”.
4. **Honest incomplete** beats false done (avoids angry restart + full re-context).
5. **On-demand skills** (`.grok/skills/*/SKILL.md`) beat loading every skill.

---

## Continuous improvement (agents must ship savings)

When touching `AGENTS.md`, `AGENT_STABLE.md`, `.cursorignore`, hooks, or `dev.py` meta:

1. `python dev.py token-improve` → read `logs/token_improve/latest.md`
2. Apply **safe** items only (do **not** cursorignore core domain files you still need to edit — prefer outline; index ignore is for *passive* index bloat)
3. `python dev.py token-audit --strict`
4. Note user-facing process changes in `docs/HANDOFF.md`
5. If the same waste pattern appears **twice**, add a free `dev.py` subcommand or row here

**token-improve (2026-07-09 sample):** suggested ignoring large `logic/payroll.py`, `cli.py`, `logic/scheduling.py` from index — treat as **index** advice, not “never read.” When editing those files: outline/symbol first.

---

## Verify honesty (anti test-theater)

| Tier | Command | Ship claim allowed? |
|------|---------|---------------------|
| fast | `verify --tier fast` | **No** |
| preflight | `verify --tier preflight` | **No** |
| **check** | `verify --tier check` | **Yes** (if `honest_gate` true) |
| full | `verify --tier full` | Yes (release) |

Policy: `.grok/rules/verify-policy.md`. Never patch tests to match broken product.

---

## Paste-ready agent checklist (every turn)

```text
[ ] Task scoped (slice or gui/* paths)?
[ ] usage-brief / outline / symbol before full reads?
[ ] “Fix X” → full rg inventory before edits?
[ ] Edit batch covers ALL instances?
[ ] verify --tier fast after edits?
[ ] Ship? → check + last_verify.json honest_gate
[ ] Report remaining gaps with paths (not vibes)
[ ] Long thread? → context-window status / new chat
[ ] Unknown NiceGUI? → CHRONOS_SOURCES not guess
```

---

## Related in-repo docs

| Doc | Role |
|-----|------|
| `docs/AGENT_STABLE.md` | Mandatory tools + sufficiency |
| `docs/USAGE_MINIMIZATION.md` | Human + agent spend ladder |
| `docs/ZERO_AGENT_USAGE.md` | Prefer zero Agent |
| `docs/CHRONOS_SOURCES.md` | Framework OSS (saves retry tokens) |
| `docs/NEXT_AGENT_PROMPT.md` | Session handoff + embeds this ladder |
| `.grok/skills/token-discipline/SKILL.md` | Skill load on demand |
| `.grok/skills/cost-efficient-workflow/SKILL.md` | Free gates first |
