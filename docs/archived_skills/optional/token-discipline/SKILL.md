---
name: token-discipline
description: >
  Mandatory-style token minimization for Dodgeville PD Scheduler sessions.
  Use at session start and whenever prompts, index, or large files change.
---

# Token discipline (highest leverage skill)

## Session open (≤30s, $0)

```bash
python dev.py agent-kit --slice <id> --task "<task>"
# paste only: @logs/agent_kit/latest.md
```

## Graphify first (all project knowledge — avoid whole-repo reads)

Use for **any** project question (product, process, architecture, features), not only coding trivia.

```bash
python dev.py graphify-gate          # ensure graph fresh (also on verify preflight/check)
graphify query "<task or question>"  # any knowledge about the project
graphify path "A" "B"
graphify explain "Concept"
# hubs: graphify-out/KNOWLEDGE_HUB.md · GRAPH_REPORT.md
```

Then open **only** files the graph/slice/hub points to. Rebuild: `graphify extract . --code-only`

## Before every source read

```bash
python dev.py usage-brief <slice>
python dev.py read-budget path/to/file.py
python dev.py outline path/to/file.py   # if budget warns
python dev.py symbol Name --slice <id>
```

**Stop** gathering when you can edit confidently. Contradiction → graphify query or one targeted tool only.


## After every edit batch

```bash
python dev.py verify --tier fast
# ship / handoff:
python dev.py verify --tier check
```

Never claim done on fast alone for logic/UI.

## Never (token waste)

| Waste | Instead |
|-------|---------|
| Whole-repo read | `graphify query` + slice `touch_together` |
| Full 50KB+ `.py` | graphify explain/path → `outline` / `symbol` |
| Subagent for verify | run `dev.py verify` yourself |
| 78 UI PNGs | `ui-review` then one failed diff |
| Re-paste history | `context-window status` / new chat |
| Fat agent_pack | narrow `--slice` |
| Ignoring design/prose tools | use frontend-design **or** taste XOR; stop-slop for copy |

## Continuous improvement

```bash
python dev.py token-improve
python dev.py token-minimize
python dev.py token-audit --strict
```

## Context window

Keep: task, decisions, latest tool results.
Ephemeral: file dumps (prune after 2 turns).
Summarize @ 6000t → `logs/context_window/latest_summary.md`

## Related
`docs/AGENT_STABLE.md` · `docs/ZERO_AGENT_USAGE.md` · `.grok/rules/auto-minimize.md` · cost-efficient-workflow skill
