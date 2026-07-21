# Handoff

**Landing residuals:** `logs/NEXT_SESSION_BRIEF.md` (read first for open items).
**Workspace:** `C:\Users\Windows\Chronos Workspace` only · never MyProject.
**Do-not-rebreak product law:** this file + `AGENTS.md`.

---

## NEXT SESSION

- **GitHub:** `jaredweier/Chronos-Workspace` · branch `master` — keep pushed.
- **Sim research P0–P18:** landed (horizon pack, soft rank, autopsy, visuals, ops bridge).
- **Staged search port (2026-07-21):** `staffing_search_stages` · `staffing_stage_wizard` · `result_narrowers` · `staffing_search_local` wired into main `staffing_optimizer` + Explain menu.
- **Optimizer:** still a large `logic/staffing_optimizer.py` on main (split modules exist only on older worktree). Prefer **additive** modules — do not re-monolith further; full split is a separate deliberate refactor.
- Ship `verify --tier check` **only if human asks**. Day-to-day: focused unit / `core`.
- Chronos: one process; often `:8080` or `:8090`.

---

## Product law (do not re-break)

1. **Sim #1:** find schedules that meet **entered constraints**.
2. Soft / score / FLSA / fatigue / fairness / heatmap = **later optional narrowers** among hard-OK plans.
3. Hard eval **56 days** (UI/optimizer). Units may use 28d.
4. User numbers first — no invented dept defaults; no Dodgeville in UI defaults.
5. Rotation model: Squad **or** Multi-block. Multi-pattern same-cycle OK.
6. FLSA period ≠ rotation length ≠ payroll period.
7. Brand: Chronos Command · Quasar primary `#3B7DD8`.

---

## Hot modules

```
logic/staffing_optimizer.py       # main search (still large on master)
logic/staffing_search_stages.py   # staged feasibility
logic/staffing_stage_wizard.py    # pause → lock → Find Best
logic/result_narrowers.py         # end filters + recovery + publish readiness
logic/staffing_search_local.py    # warm-start helpers
logic/horizon_pack.py · sim_wave2 · constraint_autopsy · soft_rank
gui/pages/simulator/*             # Chronos sim UI
scripts/sim_wave_uat.py · python dev.py sim-wave-uat
```

---

## Open / optional (human-driven)

- Human Chronos retest of stage wizard + narrowers
- Live UAT: Chronos up → `python dev.py sim-wave-uat --live`
- Full optimizer façade split (worktree had it) — only if human prioritizes
- Legacy: dual-rate / leave browser proof · SMS · LDAP · tunnel

---

## Trust

`docs/AGENT_TRUST_AND_MISTAKES.md` — prove user scenario; unit ≠ Chronos.
