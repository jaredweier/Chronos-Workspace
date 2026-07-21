# Project knowledge hub (agent entry)

Prefer this map **before** bulk-reading the repo.

- Graph nodes (last extract): **5043**

## Query first

```bash
graphify query "<any project question — code, product, process, architecture>"
graphify path "A" "B"
graphify explain "Concept"
```

## Knowledge sources

- `graphify-out/graph.json` — Queryable knowledge graph (code structure + links)
- `graphify-out/GRAPH_REPORT.md` — God nodes, communities, suggested questions
- `graphify-out/graph.html` — Interactive browser map
- `docs/HANDOFF.md` — Session memory / product status
- `docs/AGENT_STABLE.md` — Agent policy & verify ladder
- `docs/AGENT_TOOLKIT.md` — Free tools hub
- `docs/knowledge/` — FR / math / UI research deposits
- `AGENTS.md` — Always-on agent rules (graphify-first)
- `CLAUDE.md` — Claude multi-agent + tool notes
- `slices/registry.py` — Vertical slice map
- `.grok/rules/` — Domain cards (UI, scheduling math, …)

## Rebuild

```bash
graphify extract . --code-only   # free, local AST
python dev.py graphify-gate      # ensure fresh for verify
```

Scope is **all project knowledge** agents need: structure, coupling,
where features live, and pointers into docs/rules — not only 'coding trivia'.
