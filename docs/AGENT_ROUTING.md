# Agent & LLM Routing — Chronos Command / Dodgeville PD

**Auto-context: OFF.** Load skills/docs on demand.
**Any agent/LLM allowed** — recommendations pick **lowest cost that fits** complexity.
**Router (source of truth):** `python dev.py route-task "<task>"` → `scripts/agent_route.py`
**UI agent catalog:** [`UI_AGENTS_CATALOG.md`](UI_AGENTS_CATALOG.md)
**Token ladder:** [`TOKEN_PERFORMANCE.md`](TOKEN_PERFORMANCE.md)

---

## Quick route

```bash
python dev.py route-task "fix Title Case on media page"
python dev.py route-task "screenshot shows broken nav"
python dev.py route-task "e2e click through login"
python dev.py route-task --complexity high "redesign scheduling IA"
python dev.py route-task --json "wire chronos payroll tab"
```

Output includes: **complexity**, **cost_tier**, **primary_agent**, **preferred_model**, **agent chain** (cheap→expensive), **external OSS UI agents**, **do_not**, verify commands.

---

## Complexity → cost → model (automatic)

| Tier | Signals | Cost | Cursor | Default model class | OpenCode |
|------|---------|------|--------|---------------------|----------|
| **verify** | run tests, audit, did it pass | **free** | Terminal | none | `qa-free` |
| **trivial** | typo, spelling, whitespace only | **free** | **Tab** | none | skip |
| **low** | explain, where is, copy-only | **cheap** | **Ask** | Haiku / Flash / Grok Fast / Auto | `small_model` / ui-static |
| **medium** | one feature/bug, Chronos page | **balanced** | **Agent** | Sonnet / Grok / Composer | primary + skill / **ui-chronos** |
| **high** | multi-slice, redesign, rust | **flagship** | **Plan→Agent** | Opus / reasoning | primary + qa |
| **vision** | screenshot, looks wrong | **vision** | Agent + **1 PNG** | vision model **after** static gates | **ui-vision-reviewer** |
| **browser** | e2e, click-through, browser-use | **vision** | optional Agent | cheap+Playwright first | ui-chronos + catalog |

**Rule:** never jump cost tiers (e.g. Opus for typo, vision for Title Case).

---

## UI lanes (auto-detected)

| Lane | Triggers | First agents | Escalate |
|------|----------|--------------|----------|
| **none** | non-UI | domain skill | — |
| **copy** | Title Case, wording, theme text | `ui-review` → aesthetics skill → ui-static-reviewer | Ask mini |
| **layout** | tabs, widgets, pages | ui-development → Cursor Agent | Cline |
| **chronos** | NiceGUI, Chronos, gui/, media, duty console | **ui-chronos** → Playwright | browser-use |
| **vision** | png, screenshot, look wrong | static free → vision skill | OmniParser → browser-use |
| **browser** | e2e, playwright, skyvern, click through | **Playwright** | Stagehand → browser-use → Skyvern |

---

## Domain → skill

| Working on… | Skill |
|-------------|--------|
| Bump, rotation, day-off, swaps | `scheduling-logic` |
| Payroll / timecard | `payroll-timecard` |
| Auth / passwords / RBAC | `security` |
| Chronos NiceGUI `gui/*` | `ui-development` (+ OpenCode **ui-chronos**) |
| Copy / Title Case / theme | `ui-aesthetics-review` |
| Screenshots / visual QA | `ui-vision-review` |
| CLI / dev.py | `cli-operations` |
| .exe / freeze | `build-deploy` |
| Split monolith | `refactor` |
| Unsure | `dodgeville-scheduler` |

---

## External UI agents (built into router)

Catalog + URLs: **`docs/UI_AGENTS_CATALOG.md`**. Wired in `scripts/agent_route.py` → `AGENT_CATALOG`.

| Prefer early (cheaper) | Prefer late (costly, **user-escalation only**) |
|------------------------|--------------------------------------------------|
| Terminal gates, Cursor Tab/Ask/Agent | browser-use, Skyvern, UI-TARS, OmniParser |
| OpenCode `qa-free` / ui-static / ui-chronos | Multi-PNG vision |
| Free `ui-review` / Playwright (browser lane) | `ui-observe --live` |

**2026-07-12 prune:** default agent chain ≤3 steps; OSS empty for verify/trivial/low; design skills in `.grok/skills/_archive/`.

---

## Subagents

| Task | Subagents |
|------|-----------|
| high complexity | domain skill + qa-verify |
| vision / browser | ui-vision-review + ui-development |
| chronos medium | ui-development + token-discipline |
| verify / trivial / low | **none by default**; subagent OK **only if cheaper** than primary |

**Verify/gates/graphify/vision:** subagent OK when total usage is **less** than primary doing the same work.

---

## Platform notes

### Cursor
- Plan mode for **high**; Tab for **trivial**; Ask for **low**.
- Lean rules; `@docs/UI_AGENTS_CATALOG.md` on demand.
- https://cursor.com/blog/agent-best-practices

### Grok
- `AGENTS.md` minimal; run `route-task` once per task.
- Load only the printed skill path.

### OpenCode
- Agents: `qa-free`, `ui-static-reviewer`, `ui-chronos`, `ui-vision-reviewer`
- `/route-task` → follow printed cost tier and agent chain
- `small_model: fast` for light steps (`opencode.json`)

---

## Related

- [`UI_AGENTS_CATALOG.md`](UI_AGENTS_CATALOG.md) — full agent list + GitHub links
- [`TOKEN_PERFORMANCE.md`](TOKEN_PERFORMANCE.md) — token findings
- [`CHRONOS_SOURCES.md`](CHRONOS_SOURCES.md) — NiceGUI OSS
- [`NEXT_AGENT_PROMPT.md`](NEXT_AGENT_PROMPT.md) — session handoff
