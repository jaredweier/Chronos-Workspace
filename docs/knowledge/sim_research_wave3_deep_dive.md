# Deep dive — after P0–P10 (research wave 3)

**Date:** 2026-07-21
**Context:** Wave 1 (P0–P5) + wave 2 product build (P6–P10 in `logic/sim_wave2.py`, commit `19e8e64`) are on GitHub.
**This doc:** deeper competitive + OR + LE-science dive → **next-horizon backlog only** (P11+). No claim that Chronos equals enterprise TeleStaff.

---

## Where Chronos sits now

| Layer | Chronos capability (landed) |
|-------|-----------------------------|
| Hard search | Staged feasibility, 56d sim truth, free/locked axes |
| Explain fail | Autopsy, counterfactual unlocks, relaxations |
| Soft rank | Prefs, Pareto labels (min N / OT / fairness), rank delta |
| Visuals | Day×start heat, officer Gantt, pattern calendar |
| Compliance soft | Multi-period FLSA meters, fatigue advisory |
| Ops bridge | Publish readiness, open-shift seeds, bid→soft |
| Explore | What-if sandbox (cheap strip), space estimate |
| Seeds | CP-SAT joint phase/map + soft pattern equity |

**Differentiation:** Chronos is a **constraint-first schedule design simulator** for multi-block / squad / 24/7 / windows / annual — not primarily a daily vacancy board.

---

## Competitive landscape (public-safety WFM)

| Product class | Strength | Gap vs Chronos sim focus |
|---------------|----------|---------------------------|
| **UKG TeleStaff** | Enterprise rules, OT, self-service, CAD/payroll integrations, burnout visibility | Heavy SaaS; less “design a new rotation from math” |
| **First Due** | LE/Fire shiftboard, trades, call shifts, vacancy deputy, incident adjacency | Day-of ops, not multi-block optimizer |
| **Aladtec** | 24/7 public safety, gap fill, union rules, mobile | Ops rostering |
| **WhenToWork** | Light drag-drop, swap, availability | Small dept / simple rules |
| **inTime** | LE payroll integration | Ops + payroll |

**Inspiration to steal (ideas only):**

1. **Scheduling Deputy / vacancy recommendations** — rank who should fill open shifts (Chronos has open-shift seed + OT equity ranking elsewhere; connect more tightly to sim thin bands).
2. **Unified on-duty + off-duty conflict** — court/detail vs patrol rest (fatigue path).
3. **Real-time burnout / hours watch** — already partial in Command Post; link sim FLSA meters to live OT ledger.
4. **Mobile self-service trades** — product later; not sim math.

---

## OR / explainability deep notes

### Multi-objective rotating workforce (MODeM / PSA)

- Pareto Simulated Annealing yields **sets** of non-dominated rosters.
- Chronos P6 is a **lightweight proxy** on post-hard axes (N, OT, fairness) — not a true multi-objective search.
- **Next (P11):** optional second pass that keeps all hard-OK, returns top-k non-dominated on 3 axes without collapsing to soft_score alone.

### Explain infeasibility (MUS / MCS)

- Industrial CP papers use **Minimal Unsatisfiable Subsets** and **Minimal Correction Sets** for “why infeasible / smallest fix.”
- Chronos counterfactuals approximate MCS-style unlocks via histogram + relaxations.
- **Next (P12):** true conflict set on **cheap reject reasons** (structured enum), not only free-text tips.

### Lexicographic vs Pareto

- Lex: hard priority order (we already have constraint_priority for near-miss).
- Pareto: no priority among softs.
- Hybrid: hard lex (feasibility) → soft Pareto shortlist (P6) → user picks. **Already product-shaped.**

---

## LE fatigue science → product caution

From Policing Institute / Police Chief / NIJ-class sources:

| Practice | Product mapping |
|----------|-----------------|
| Prefer forward rotation | Soft component / pattern catalog note |
| Limit consecutive nights | Soft fatigue + optional hard max_consec (user lock) |
| 10h/4-on-3-off often favorable | **Example catalog only** — never default |
| Avoid 05:00–06:00 starts when free | Soft start-pack penalty (partial in fatigue advisory) |
| §7(k) ≠ wellness standard | Copy: “legal OT threshold” only |

**Do not** hard-code medical claims into Find Best.

---

## Horizon backlog (P11+)

| ID | Theme | Rationale |
|----|--------|-----------|
| **P11** | True multi-objective shortlist (non-dominated set UI chip row) | Beyond single soft_score #1 |
| **P12** | Structured cheap-reject conflict IDs → MUS-style report | Stronger autopsy |
| **P13** | Open-shift deputy: score candidates from thin-band callouts + rest/OT equity | TeleStaff/FirstDue gap fill |
| **P14** | Live OT ledger ↔ sim FLSA meters side-by-side | Burnout visibility |
| **P15** | Bid + preference vector into CP-SAT seed soft (still seed-only) | Close loop prefs→search |
| **P16** | Scenario stories (“hire 1 clears Fri night”) narrative cards from what-if | Supervisor language |
| **P17** | Browser UAT pack for P0–P10 panels | Trust / no theater |
| **P18** | Optional drag-edit of duty Gantt → re-sim delta | McKinsey interactive ideal |

**Suggested next product build order:** **P17 (prove UI) → P11 → P12 → P13 → P16**.

---

## Architecture guardrails (still)

1. `staffing_optimizer.py` façade thin — wave2 in `sim_wave2` / `soft_rank` / `ops_bridge`.
2. 56d `simulate_schedule` remains truth; CP-SAT seeds only.
3. Soft never blocks Find Best.
4. No Dodgeville / 8h/2008 as product defaults.
5. FLSA period ≠ rotation cycle ≠ payroll period.

---

## Proof of wave2 land

- Hub: `logic/sim_wave2.py`
- Tests: `tests/test_sim_wave2.py`
- Git: `19e8e64` on `jaredweier/Chronos-Workspace`
- UI: decision table Pareto/FLSA/fatigue; no-match counterfactuals; what-if expansion; soft prefs fatigue weight

---

## Deep-dive sources (bookmark)

- Mugdan 2025 — explainability / rotating workforce multi-objective
- MODeM 2024 — Pareto SA for RWS
- CP 2025 industrial explainable workforce (MUS/MCS)
- DOL Fact Sheet #8 — LE/Fire FLSA
- Policing Institute / Police Chief fatigue articles
- First Due / UKG TeleStaff / Aladtec public feature pages (ops inspiration)
