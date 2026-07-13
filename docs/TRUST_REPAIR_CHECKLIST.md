# Trust Repair Checklist — Chronos / Dodgeville PD

**Purpose:** Restore honest agent status after repeated overclaims.
**Audience:** Next agent + human.
**Rule:** Do not mark a row done without the **Success proof** command/output.
**Created:** 2026-07-09 · **Updated:** 2026-07-13

Primary UI is **`gui/`** (NiceGUI). Legacy **`ui/`** is reference/tests unless a task explicitly says otherwise.

### Definition of trust restored (maps — not full product)

| Proof | Result (2026-07-13) |
|-------|---------------------|
| `python dev.py slice-check` | clean (all bindings resolve) |
| Full unittest `discover -s tests -p "test_*.py"` | **385 OK** (`SCHEDULER_SKIP_AGENT_GATES=1`) |
| `python dev.py token-audit --strict` | **89/89** |
| `verify --tier check` | **PASS** · `honest_gate: true` (2026-07-13) |
| Product Chronos dual-rate | still **partial** (logic smoke ≠ browser e2e) |
| Ship claim | only after `verify --tier check` + `honest_gate: true` |

---

## How to use

1. Work **top to bottom** within a phase (P0 before P1).
2. After each row: paste **proof** into your status report (paths, counts, exit codes).
3. Update `docs/HANDOFF.md` + `docs/NEXT_AGENT_PROMPT.md` status **only with proof**.
4. Never claim “trust repaired” until **Phase exit criteria** pass.

---

## P0 — Stop the lies (maps & gates)

| # | Repair | Files / targets | Success proof |
|---|--------|-----------------|---------------|
| P0.1 | **Rewrite slice registry paths** to real files | `slices/registry.py` | Every `ui_mixin` / `touch_together` path exists: `python dev.py slice-check` → **0 issues** |
| P0.2 | Point slices at **primary Chronos UI** where product lives | Prefer `gui/pages/*.py`; legacy `ui/pages/*.py` only if still maintained | Registry `ui_mixin` points at files that `Path(p).is_file()` |
| P0.3 | Set honest **`status`** per slice | `slices/registry.py` | No slice with missing UI or thin Chronos page marked `"complete"`; use `"partial"` / `"planned"` |
| P0.4 | Fix **feature-map honesty** | `scripts/feature_map.py` + registry | UI column requires **existing file(s)**, not `bool(feat["ui"])`. After fix: missing page → UI `—` or gap note |
| P0.5 | Align **vertical-slice tests** | `tests/test_vertical_slices.py` | `python -m unittest tests.test_vertical_slices -v` → **OK** |
| P0.6 | Kill stale **HANDOFF paths** | `docs/HANDOFF.md` | Zero references to deleted monoliths as current: `logic.py`, `ui/*_pages.py` at repo root (except historical “was” notes) |
| P0.7 | Kill stale **key symbols** block | `docs/HANDOFF.md` § Key symbols | Lists only paths that exist + match `gui/` primary story |
| P0.8 | Fix **known-issues** path drift | `.grok/rules/known-issues.md` | No open item citing missing files as if they still exist; statuses match disk |
| P0.9 | Fix **TOKEN_PERFORMANCE** green claim | `docs/TOKEN_PERFORMANCE.md` | Text matches `python dev.py token-audit` (do not say “currently green” if gaps remain) |
| P0.10 | Root **README** structure | `README.md` | Project tree matches `logic/`, `gui/`, not deleted `logic.py` monolith |

**P0 exit:**
`python dev.py slice-check` clean · `python -m unittest tests.test_vertical_slices` OK · HANDOFF has no live broken paths · feature-map does not print UI ✓ for missing files.

---

## P1 — Make the test suite tell the truth

| # | Repair | Files / targets | Success proof |
|---|--------|-----------------|---------------|
| P1.1 | **Date contract** (US M/D/YY display; storage ISO) | `validators.py`, `tests/test_validators.py` | `parse_date` / `format_date` / `format_datetime` tests match **documented** policy; no EU day-first expectation unless policy is dual-parse and tested both ways |
| P1.2 | Officer contact validation tests | `validators.py`, `tests/test_validators.py` | Test matches current validators |
| P1.3 | Pay-period search | `logic/payroll.py` (or related), `tests/test_timecard_schedules.py` | `test_search_pay_period_by_date` passes **for the right reason** (fix logic or fix fixture/base date — not delete assert) |
| P1.4 | Rotation settings apply | `logic/rotation_config.py`, scheduling bridge, test | `test_save_rotation_settings_applies_to_scheduling` passes |
| P1.5 | Agent-route / structured-output tests | `scripts/agent_route.py`, tests | Trivial tier and JSON shape match **current** router behavior; update tests **or** code with deliberate choice, document in report |
| P1.6 | Read-guard tests | `scripts/read_guard.py`, tests | Paths to “large UI” match files that exist (`gui/` or real `ui/pages/`) |
| P1.7 | Token-audit artifacts | token tools + `tests/test_token_audit.py` | Audit and test agree; no false “green” prose |

**P1 exit:**
`python -m unittest discover -s tests -p "test_*.py" -q` → **0 failures**
Then: `python dev.py verify --tier check` → pass + `logs/last_verify.json` has `"honest_gate": true`

---

## P2 — Honest product status (Chronos vs logic)

For each feature: mark **Logic / Chronos UI / Legacy UI / CLI** separately. Do not use one “complete.”

**Updated 2026-07-09 (inventory + leave/notifications depth).** Canonical table also in `docs/HANDOFF.md` § Chronos depth inventory.

| Feature | Logic | Chronos `gui/` | Legacy `ui/` | CLI | Honesty |
|---------|-------|----------------|--------------|-----|---------|
| Dashboard / KPIs | strong | gap board + hours watch + KPIs (`dashboard.py`) | partial | yes | **partial** |
| Roster | strong | `roster.py` | pages | yes | **partial** |
| Day-off + swaps | strong | `leave.py` confirm plan pick + reject notes | pages | yes | **partial** (deeper) |
| Schedules / matrix | strong | my/monthly/live (`schedules.py`) | pages | yes | **partial** |
| Payroll / timecard | strong | `finance/*` lock UI | pages | yes | **partial** (logic lock smoke OK; browser unproven) |
| Shift bidding | exists | `bidding.py` events + bid form | pages | check | **partial** |
| Open shifts | strong | `self_service.py` post/claim/digest | pages | yes | **partial** |
| Notifications | strong | inbox + compose + **Open→route** | pages | yes | **partial** |
| Ops reports | strong | `operations.py` gaps/OT/hours | pages | yes | **partial** |
| Simulator | yes | `simulator.py` | yes | no | OK |
| Backup / security | yes | `security.py` chrome | yes | yes | **partial** |

| # | Repair | Success proof | Status |
|---|--------|---------------|--------|
| P2.1 | Inventory Chronos depth per feature | HANDOFF table with paths + one-line capability | **Done 2026-07-09** |
| P2.2 | feature-map / registry status matches table | No `"complete"` where Chronos thin; slice-check green | **Done** (partial statuses) |
| P2.3 | Legacy freeze note | HANDOFF: legacy frozen except bugs | **Done 2026-07-09** |

**P2 exit:** User can read HANDOFF and know what works in **browser Chronos** without opening code.
**Still open for true complete:** browser e2e / chronos-e2e per critical flow; payroll lock proven live.

---

## P3 — Product contract cleanup (after P0–P1)

| # | Repair | Notes | Success proof |
|---|--------|-------|---------------|
| P3.1 | Full date-display audit | All user-visible dates via `format_date` / agreed helper | `rg` remaining raw `strftime` in `gui/` listed; intentional only |
| P3.2 | Demo password policy story | HANDOFF vs `must_change_password` vs migration | One true story in HANDOFF + known-issues; matches DB seed behavior |
| P3.3 | Structure soft monoliths | `logic/scheduling.py`, `validators.py`, `logic/payroll.py` | Optional splits; if deferred, keep structure-lint soft warns **honest** |
| P3.4 | Disk hygiene note | `backups/`, `logs/`, `dist/` | `.gitignore` already; document “do not treat dist green as product green” |

---

## Forbidden “repairs” (these made things worse before)

| Do not | Why |
|--------|-----|
| Edit known-issues to all `[x]` without code | Masks open design gaps |
| Delete failing tests to get green | Test theater |
| Change assert to match broken production without root-cause note | Same |
| Run only `verify --tier fast` then say ship-ready | `honest_gate: false` |
| Add more agent process docs instead of fixing registry/tests | Process sprawl |
| Print feature-map ✓ without file existence | Coverage theater |
| Leave HANDOFF “complete” after reorg | Stale handoff lies |

---

## Recommended first session sequence (copy)

```text
1. python dev.py route-task "trust repair P0 slice registry + handoff honesty"
2. Inventory missing paths: python dev.py slice-check
3. Fix slices/registry.py + feature_map existence checks (P0.1–P0.4)
4. Fix tests/test_vertical_slices (P0.5)
5. Rewrite HANDOFF paths + status (P0.6–P0.7)
6. python -m unittest discover -s tests -p "test_*.py"  → triage P1 failures
7. Fix domain/test contract (P1) until 0 failures
8. python dev.py verify --tier check
9. Read logs/last_verify.json → require honest_gate true
10. Update NEXT_AGENT_PROMPT status table with proof only
```

---

## Definition of “trust restored”

All of the following:

- [x] `slice-check` 0 issues — **2026-07-09**
- [x] Full unittest 0 failures — **381 OK** (2026-07-12)
- [x] `verify --tier check` pass + `honest_gate: true` — re-run after each edit batch; see `logs/last_verify.json`
- [x] feature-map cannot show UI ✓ for missing files — bidding UI `—`
- [x] HANDOFF “Key symbols” paths all exist (deleted roots listed as deleted)
- [x] token-audit **75/75**; slice statuses mostly `partial` (honest)
- [x] Chronos vs logic dual-rated via `status: partial` + feature-map notes

**P0/P1 done.** Remaining open work is **P2/P3 product depth** (Chronos parity), not map lies.
**2026-07-12:** token prune (caveman, lean router, skills archived). Do not claim browser e2e complete without named Playwright command.

Until P2: product Chronos may still be thin; **agent map trust is restored.**
