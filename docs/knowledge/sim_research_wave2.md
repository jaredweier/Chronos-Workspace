# Schedule simulator — research wave 2 (post P0–P5)

**Date:** 2026-07-21
**Mode:** External learning only (OR papers, LE wellness, WFM products, CP-SAT practice).
**Product law (unchanged):** Hard feasibility from **entered constraints** first; score / fairness / FLSA / fatigue = **optional narrowers among working plans**. Eval **56 days**. User numbers first. Thin façade — no re-monolith.

## Already landed (wave 1)

| Tier | Theme | Repo |
|------|--------|------|
| P0 | Stabilize extract + night_risk | `0d5b83a` |
| P1 | Constraint autopsy + live feasibility strip | `30fa268` |
| P2 | Soft rank among hard-OK | `2b72ed4` |
| P3 | Coverage heat + officer Gantt | `5707151` |
| P4 | Publish readiness + open-shift + bid→soft | `28fd841` |
| P5 | Pattern calendar + soft compliance strip | `28d3f7e` |

---

## New external themes (wave 2)

### 1. Multi-objective / Pareto (not single “best score”)

**Sources:** MODeM / rotating workforce multi-objective papers; MyShyft multi-objective scheduling; Pareto front diversity research; McKinsey workforce AI scheduling.

**Pattern:** Supervisors rarely want one scalar optimum. They want a **small non-dominated set**: e.g. fewer officers vs lower OT vs better night balance — trade-offs you can *see*.

**Chronos fit:**
- After hard-OK set exists, plot / table **2–3 axes** among soft metrics (already partially in decision table).
- Label options as “Pareto: min N”, “Pareto: min OT”, “Pareto: max fairness” instead of only soft_score #1.
- **Do not** make multi-objective replace hard feasibility.

**Proposed tier: P6 — Pareto shortlist among hard-OK**

---

### 2. Explainability (“why not better?”)

**Sources:** “Why Is There No (Better) Solution?” (rotating workforce, 2025); research on AI shift-scheduling explanations; Timefold explain-score (already inspired P1).

**Pattern:** Decision makers need:
1. Why this option won among feasible
2. Why a *better* preferred option was **impossible**
3. Minimal change to unlock the preferred trade-off

**Chronos fit:**
- P1 autopsy covers “why fail”.
- Next: **counterfactual unlock cards** on near-misses: “+1 officer → hard OK”; “drop window min 2→1 → hard OK” (partially in `suggest_relaxations`).
- Soft rank note exists; extend with **delta vs #2** (“chose fewer officers; costs +12 night load spread”).

**Proposed tier: P7 — Counterfactual unlock + rank delta explain**

---

### 3. LE fatigue / wellness science (soft metrics, not hard law)

**Sources:** National Policing Institute (shift work/fatigue 2026); Police Chief Magazine 24/7 fatigue; NIJ fatigue policies; PowerDMS wellness + scheduling; Indeavor 4/10 discussion.

**Evidence-backed soft signals (examples only — never product defaults):**
- Prefer **forward** rotation (day→evening→night) over backward when multi-block rotates starts
- Cap **consecutive nights** and **quick turnarounds** (already have rest / max consecutive as *optional* hard when user locks)
- 10h / 4-on-3-off often cited for wellness — **catalog example only**, not forced default
- Avoid early starts 05:00–06:00 when free-searching day packs (soft preference in start packs)

**Chronos fit:**
- Soft components: `forward_rotation_bonus`, `quick_turnaround_penalty`, `consec_night_spread`
- Pattern preview compliance strip already has rest/FLSA soft — add **fatigue advisory** lines
- Keep FLSA §207(k) as **period math** independent of rotation cycle (already product law)

**Proposed tier: P8 — Fatigue advisory soft metrics (user-optional weights)**

---

### 4. FLSA §7(k) honesty (compliance strip, not wellness gospel)

**Sources:** DOL Fact Sheet #8; industry FLSA LE explainers.

**Key facts for product copy:**
- Work period **7–28 days**; LE OT after hours proportional to 171/28 (e.g. 86h / 14d)
- §7(k) is **overtime threshold law**, not a medical “optimal week” standard
- Simulator soft strip should say **“legal OT threshold estimate”** not “safe hours”

**Chronos fit:**
- Tighten compliance-strip / economics labels for honesty
- Optional: show **multiple period lengths** (7/14/28) side-by-side soft meters on ranked cards

**Proposed tier: P8b (with P8) — Multi-period FLSA soft meters**

---

### 5. CP-SAT soft objective practice (seeds still only)

**Sources:** CP-SAT rostering guides; OR-Tools discuss real-world soft weights (coverage >> fairness >> isolated offs); Perron scheduling seminar; CP-SAT primer.

**Pattern:** Hard booleans for coverage/rest; **weighted soft** objective for preferences; time-limit anytime best.

**Chronos fit:**
- Expand seed objective to include soft night-balance / weekend equity **only inside seed pack search**
- Never replace 56d `simulate_schedule` truth
- Align weight magnitudes with existing soft_prefs (coverage still hard outside seeds)

**Proposed tier: P9 — Richer CP-SAT seed soft objective (seeds only)**

---

### 6. Interactive front-end / adoption (McKinsey + WFM)

**Sources:** McKinsey smart scheduling; Teams Shifts / UKG-class patterns (prior research).

**Pattern:** Drag-drop, preloaded AI options, live metrics dashboards beat spreadsheets.

**Chronos already has:** heat, Gantt, decision table, stage wizard, publish checklist.

**Remaining gaps:**
- **What-if sandbox** sticky: change N/window min and see cheap strip + estimated space without full search
- **Scenario story**: “If we hire 1, weekend nights clear” (ties to P7)
- Browser-proven UAT of P0–P5 panels

**Proposed tier: P10 — Sticky what-if sandbox (cheap strip + predicted unlock)**

---

## Opportunity map (wave 2)

| Tier | Theme | Effort | Value | Depends |
|------|--------|--------|-------|---------|
| **P6** | Pareto shortlist labels among hard-OK (min N / min OT / max fairness) | M | High supervisor clarity | P2 soft components |
| **P7** | Counterfactual unlock cards + soft rank delta vs #2 | M | Trust / “why this plan” | P1 autopsy, relaxations |
| **P8** | Fatigue advisory soft metrics + optional weights | M | LE-domain differentiation | P2, P5 strip |
| **P8b** | Multi-period FLSA soft meters (7/14/28) | S | Compliance honesty | P8 or alone |
| **P9** | CP-SAT seed soft objective expansion | M–L | Search quality | Existing bridge |
| **P10** | Sticky what-if sandbox (no full sim) | M | Speed / exploration | P1 strip, P7 |

**Recommended build order if continuing product work:**
**P7 → P6 → P8b → P8 → P10 → P9**
(Explain trust first, then choice UI, then LE soft meters, then interactive sandbox, then heavier solver seeds.)

---

## Explicit non-goals (wave 2)

- Single “AI best schedule” black box without hard/soft separation
- Hard-coding 10h/4-on-3-off or 2008h as product defaults
- Claiming §7(k) thresholds as wellness optima
- Full Timefold/Java stack import
- Replacing Chronos sim with pure nurse CP-SAT assignment

---

## Key links (bookmark)

- [DOL FS #8 LE/Fire FLSA](https://www.dol.gov/agencies/whd/fact-sheets/8-flsa-police-firefighters)
- [Policing Institute: shift work & fatigue](https://www.policinginstitute.org/infocus/infocus-shift-work-fatigue-and-overtime-in-policing-balancing-officer-wellness-and-public-safety/)
- [Police Chief: fatigue in 24/7 ops](https://www.policechiefmagazine.org/human-fatigue-in-247-operations/)
- [OR-Tools CP-SAT](https://developers.google.com/optimization/cp/cp_solver)
- [CP-SAT primer (Krupke)](https://github.com/d-krupke/cpsat-primer)
- McKinsey: smart scheduling / workforce AI
- Multi-objective rotating workforce / Pareto explainability papers (MODeM, 2024–2025)

---

## Chronos module hooks (for implementers)

| Next tier | Touch first |
|-----------|-------------|
| P6 | `logic/soft_rank.py`, decision table, ranked_render |
| P7 | `logic/optimizer_features.suggest_relaxations`, `constraint_autopsy`, dialogs |
| P8 | `soft_rank` components, `pattern_preview.compliance_strip` |
| P8b | `staffing_insights.enrich_option_economics`, decision table |
| P9 | `logic/staffing_cpsat.py` / cpsat bridge only |
| P10 | `constraint_autopsy.cheap_feasibility_strip` + requirements form live panel |

---

## Success criteria for wave 2 product work

1. Hard feasibility still primary; soft/Pareto never blocks Find Best.
2. Supervisor can answer “why this plan?” and “what’s the next hire unlock?” without reading solver logs.
3. Fatigue/FLSA copy stays **honest** (legal vs wellness).
4. All new code unit-tested; autopush to `Chronos-Workspace` when building.
