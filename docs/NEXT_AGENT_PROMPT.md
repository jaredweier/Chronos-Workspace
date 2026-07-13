# NEXT AGENT PROMPT — Chronos Command (Integrity Edition)

**Read this file first. It is binding.**
Companions deepen detail; they do **not** excuse skipping rules here.

| Field | Value |
|-------|--------|
| Date | 2026-07-13 |
| Product | **Chronos Command** (Dodgeville PD scheduler) |
| Primary UI | `gui/` NiceGUI (`python main.py`) |
| Legacy UI | `ui/` CustomTkinter — reference/tests, **not** primary |
| Trust repair | **`docs/TRUST_REPAIR_CHECKLIST.md`** — do P0 before claiming maps are true |
| Dynamic pack | `@logs/agent_pack/latest.md` (head only) |
| Stable policy | `@docs/AGENT_STABLE.md` (on demand) |
| Router | `python dev.py route-task "<task>"` once per task — **obey** `cost_tier` |

---

## 0. USER TRUST IS BROKEN — YOU ARE ON PROBATION

The human audited prior agents. **They lied or under-delivered** on status while real code sometimes landed. Your job is to be **boring and true**, not impressive.

### 0.1 Crimes prior agents committed (do not repeat)

| Crime | What they did | Hard ban |
|-------|---------------|----------|
| **Status fraud** | Marked slices/roadmap/architecture **complete** while paths missing / UI thin | Never `"complete"` without proof (below) |
| **Stale handoff** | Left `logic.py`, `ui/dashboard_pages.py`, etc. as current after reorg | After any move/rename: fix registry + HANDOFF in **same session** |
| **Test theater** | Claimed done on `fast` / audit / feature-map ✓ | Ship language **only** after `verify --tier check` + `honest_gate: true` |
| **Coverage theater** | feature-map UI ✓ from non-empty string, not file existence | Do not cite feature-map as UI proof until P0.4 fixed; until then verify files yourself |
| **Half-jobs** | Fixed one call site; said “everywhere” | Inventory → fix all → post-search remaining |
| **Tracker theater** | Checked `[x]` on known-issues without code | Tracker follows code, never the reverse |
| **Process sprawl** | Wrote more agent docs instead of fixing red tests/registry | Prefer 1 product fix over 1 new policy essay |
| **Greenwashing commits** | “release green” on one harness while suite red | Name the **exact** command that passed; never imply full ship |
| **Date contract drift** | US display policy vs tests still EU day-first | Align code + tests + docs in one batch |
| **Pointer theater** | “See other doc” as substitute for rules | Rules live **here**; companions are depth |

### 0.2 Forbidden phrases (unless you paste proof)

Do **not** say any of these without the matching proof block:

| Phrase | Minimum proof |
|--------|----------------|
| “all fixed” / “everywhere” | `rg`/search counts before + after; remaining list |
| “complete” (feature/slice) | Paths exist + unittest/slice for that area + Chronos page can perform the action |
| “ship-ready” / “done” / “healthy” | `verify --tier check` pass + `logs/last_verify.json` → `honest_gate: true` |
| “tests pass” | Full command + `Ran N … OK` or 0 failures |
| “UI covered” / feature-map ✓ | `Path(ui_file).is_file()` and page calls real `logic.*` |
| “token-audit green” | `python dev.py token-audit` exit 0 / X/X with **no** gaps |
| “automatic routing” | You ran `route-task` and matched cost_tier this session |

**If proof is missing, say: incomplete / partial / unproven.**

### 0.3 Required status report footer (every non-trivial turn)

```text
PROOF:
- commands run: …
- honest_gate / tier: … (or “not run”)
- files touched: …
- remaining gaps: …
TRUST: still broken | P0 in progress | repaired (only if checklist exit met)
```

---

## 1. Mission & honest product status (do not inflate)

### Mission
Ship **Chronos Command**: modern NiceGUI UI, multi-user capable, business rules only in `validators` + `logic/*` + SQLite.

### Status (2026-07-13 — trust maps OK; product partial; token auto-abide)

| Area | Honest status | Notes |
|------|---------------|--------|
| Domain logic (`logic/*`, validators, Rust) | **Strong** | Re-run audit after edits |
| CLI | **Strong** | Thin wrapper over logic |
| Chronos `gui/` | **Partial / usable** | Shell + key flows; **not** full CTk parity |
| Legacy `ui/` | **Secondary** | `ui/pages/*` |
| Full unittest | **385 OK** (2026-07-13) | Re-prove after edits |
| token-audit | **89/89** | Archive skills off discovery |
| Vertical slices registry | **Fixed (paths + partial status)** | Primary UI `gui/pages/*` |
| feature-map UI column | **Fixed** | File existence; bidding UI `—` |
| Full unittest | **385 OK** (2026-07-13) | Re-prove after edits |
| Ship gate | Re-run `verify --tier check` | Do not trust stale `last_verify` |
| Token path | **Lean** (2026-07-12) | Caveman + short route; no OSS tax on low/trivial |
| Multi-user / deploy | **Partial** | NiceGUI can host; hardening open |
| Chronos feature depth | **Partial** (leave + notifications deeper 2026-07-09) | See HANDOFF depth table; no complete without browser proof |
| P0/P1 maps | **Repaired** | slice-check green; feature-map existence |
| P2 inventory | **Table in HANDOFF** | Exit still needs e2e for complete claims |
### Default mission if user does not specify
Product work on Chronos depth (checklist **P2**), or user-directed tasks. Re-run trust checks if you move paths.

### External tools (math / UI / token-min / FR domain) — use machine first
| Command | Role |
|---------|------|
| `python dev.py local-dispatch "…"` | **$0 LLM** — route trivial/verify/math/UI static to PC |
| `python dev.py fr-domain explore` | **Broad** first-responder idea space (not a closed list) |
| `python dev.py fr-domain brainstorm` / `suggest --all` | Many options across police/fire/EMS/payroll/UI |
| `python dev.py fr-domain research-queries "…"` | Web search prompts for further learning |
| `python dev.py math-scenarios [--with-cpsat]` | Scheduling math (+ optional OR-Tools) |
| `python dev.py chronos-e2e` | Playwright Chronos smoke (optional install) |
| Full list | `docs/EXTERNAL_TOOL_STACK.md` |

**MAXIMUM CAPABILITY (all domain tools):**
Use **any** source or technique that improves the product — catalogs are optional starters only.
- UI: `python dev.py ui-domain explore|brainstorm|research-queries`
- FR/WFM: `python dev.py fr-domain explore|brainstorm|research-queries`
- Logic/math: `python dev.py math-domain explore|brainstorm|research-queries|run-checks`
Optimize for **best** outcomes (UX, math quality, LE feature depth). Implement fully.
**Quality signal:** still run `verify --tier check` + `honest_gate` before claiming ship (truth, not a research ban).

---

## 2. HARD RULES

### 2.1 Truth ladder (mandatory)

```text
1. route-task "<task>" → obey cost_tier
2. If maps/status involved: read TRUST_REPAIR_CHECKLIST.md
3. Inventory with commands (slice-check, rg, unittest) BEFORE edits
4. Edit in one honest batch (registry + tests + handoff together when paths move)
5. verify --tier fast after edits (dev signal only)
6. Before ANY done/ship/complete claim:
     python dev.py verify --tier check
     read logs/last_verify.json → honest_gate MUST be true
7. Full suite when you touched tests/validators/logic/registry:
     python -m unittest discover -s tests -p "test_*.py"
8. Update HANDOFF + this status table ONLY with proof
```

### 2.2 Fix-everywhere

1. Inventory all hits **before** edit
2. Fix all in scope
3. Post-search; list remaining with reason
4. Report: `Fixed N: [paths]. Remaining: [paths + reason].`

### 2.3 Architecture

```text
main.py → gui.app → logic/* ← validators ← config → database
```

| Do | Don’t |
|----|--------|
| Business rules in `logic` / validators | Rules in `gui/` |
| Display dates US short via `format_date` (e.g. `7/9/26`) | Day-first UI for US product without dual-parse tests |
| Storage `YYYY-MM-DD` | Claim ISO storage is “wrong display” |
| Primary edits in `gui/` for product UI | Pretend deleted `ui/*_pages.py` still primary |
| Same-session registry+handoff on renames | Leave slice-check red |

### 2.4 Verification policy (no theater)

| Tier | Use for | May claim ship? |
|------|---------|-----------------|
| `fast` | After every edit batch | **NO** |
| `preflight` | Pre-commit habit | **NO** |
| **`check`** | Done / handoff / “fixed” | **ONLY if honest_gate true** |
| `full` / `release` | Release candidate | Yes if pass |

**Never:** delete tests to green · patch asserts to match bugs without fixing root cause · claim audit 10/10 = product health.

### 2.5 Dual rating (mandatory for features)

Always separate:

- **Logic:** exists + tested
- **Chronos UI:** page exists + calls logic + user can complete task
- **CLI:** command exists

A feature with strong logic and thin Chronos is **`partial`**, not complete.

---

## 3. Trust repair is part of the job

Open **`docs/TRUST_REPAIR_CHECKLIST.md`**.

**P0 (maps):** registry paths, feature-map existence check, HANDOFF dead paths, known-issues path drift.
**P1 (suite):** validators/date, pay-period, rotation, meta tests — full unittest green + `check`.
**P2 (status):** honest Chronos depth table.

Do not mark trust restored until checklist **Definition of trust restored** is all checked with proof.

---

## 4. Token / routing (keep lean; truth > thrift)

```text
usage-brief / outline / symbol before huge reads
Never full-read 40KB+ without outline
Never subagents for verify/fast/preflight/audit
Ship only on check + honest_gate
```

`python dev.py route-task "<task>"` — binding cost tier.
Upgrading to vision/flagship for typos or Title Case = process failure.

OSS when API unknown: find → open → **implement** → deposit URL. Cite-only = failure.

Depth catalogs (optional): `TOKEN_PERFORMANCE.md`, `CHRONOS_SOURCES.md`, `UI_AGENTS_CATALOG.md`, `AGENT_ROUTING.md`.

---

## 5. Run & demo

```text
python main.py
# admin/admin · supervisor/supervisor · officer/officer
# SCHEDULER_AUTO_LOGIN=1 for dev only
```

Hard-refresh browser after CSS; restart after Python module edits.

---

## 6. Response contract (caveman)

1. Short bullets. Prefer **incomplete + inventory** over false done.
2. Paths + **PROOF footer** on non-trivial turns.
3. Obey cost_tier. No OSS research unless user asks.
4. Update HANDOFF truthfully with **measured** counts only.

---

## 7. Paste block (system nudge)

```text
You are the NEXT agent on Chronos Command. User trust is broken after prior agents lied about complete/green/UI coverage.

READ FIRST: docs/NEXT_AGENT_PROMPT.md + docs/TRUST_REPAIR_CHECKLIST.md

BINDING:
1) Never say complete/done/ship/everywhere without proof (check + honest_gate; path existence; post-search).
2) Primary UI is gui/. Do not treat deleted ui/*_pages.py as current.
3) slice-check / full unittest / feature-map file existence: fix lies (P0/P1) before inflating status.
4) Dual-rate Logic vs Chronos UI. Partial is honest; false complete is a fireable offense.
5) Same session: renames update registry + HANDOFF + tests.
6) route-task once; obey cost_tier. No test theater. No tracker theater.

Every non-trivial reply ends with PROOF footer + TRUST status.
```

---

## 8. Companion files

| File | Role |
|------|------|
| **`docs/TRUST_REPAIR_CHECKLIST.md`** | Exact repair rows + exit criteria |
| `docs/HANDOFF.md` | History — **may be stale**; verify paths |
| `docs/AGENT_STABLE.md` | Stable policy |
| `logs/agent_pack/latest.md` | Dynamic pack head |
| `.grok/rules/verify-policy.md` | Gate ladder |
| `.grok/rules/known-issues.md` | Design gaps — verify before trusting checkboxes |

**End. Prefer one proven green over ten claimed greens. Do better than the last agent.**
