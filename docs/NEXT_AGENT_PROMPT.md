# Next Agent Prompt

## 0 — Speak & budget (first)
- **Caveman:** short bullets. No preamble/recap/let-me. Prose only if user asks explain/docs.
- **Token minimize:** fewest tools; 1 thing at a time; no parallel/background spam.
- Run: `python scripts/session_auto_bootstrap.py` — contract opens with these rules.
- Chain: `route-task` once → edit → `verify --tier fast`
- Ship only: `verify --tier check` + `honest_gate: true`. Unit ≠ Chronos.

## 1 — Where you are
- **Workspace:** `C:\Users\Windows\Chronos Workspace` (NOT MyProject)
- **Brief (must read):** `logs/NEXT_SESSION_BRIEF.md` — simulator package map, bind order, residuals
- **Handoff:** `docs/HANDOFF.md` · **Trust:** `docs/AGENT_TRUST_AND_MISTAKES.md`

## 2 — Product pick-up (simulator)
- Package under `gui/pages/simulator/`; `page.py` ~1208 lines is orchestrator only
- Extracted modules (do not re-inline):
  `requirements_form` · `optimizer_actions` · `form_state` · `side_actions` ·
  `constraint_suggest_ui` · `ranked_render` · plus panels (manual, publish, windows, hero, …)
- Always-on UAT: this tree on **:8080** only (`ChronosAlwaysOnUAT`)
- Find-best proof: `scripts/_sim_path_proof.py`
- Wiring labels test: `tests.test_simulator_constraints` — add new package files to its scan list if you extract more

## 3 — Continue
Obey brief open residuals. User task after binding rules above.
