# Agent routing (Grok)

`python dev.py route-task "<task>"` → **one primary agent + cost_tier + one skill**.

Auto-context OFF · cheapest fit · any LLM allowed.
Policy: `@docs/AGENT_ROUTING.md` · external (user-only): `@docs/UI_AGENTS_CATALOG.md`

**Rules**
- Run route-task **once** per task; obey `cost_tier`.
- free/cheap: empty OSS; Tab/Ask/terminal only; no vision.
- Load at most **one** skill body if route prints it.
- Chain ≤ 3 steps. No skyvern/browser-use unless user escalates.

**Sufficiency:** stop gathering when confident. Hub: `docs/AGENT_STABLE.md`.
