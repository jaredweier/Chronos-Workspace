---
name: ui-aesthetics-review
description: Copy/theme polish — dev.py ui-review, Title Case, theme tokens. No vision unless user asks.
---

# UI Aesthetics Review Agent

## When to use

- User asks to improve GUI look and feel, copy, or spelling
- Before a demo, evaluation build, or department rollout
- After large UI changes â€” verify consistency across tabs

## Quick start

```bash
python dev.py ui-review              # static scan â†’ logs/ui_review/<timestamp>/
python dev.py ui-review -v           # print every finding
python dev.py ui-live --delay 0.25   # optional visual pass + screenshots
python dev.py ui-review              # re-check after fixes
python dev.py check                  # full regression gate
```

Optional fuller spelling: `pip install pyspellchecker`

## What the tool checks

| Category | Examples |
|----------|----------|
| **Spelling** | Common typos; unknown words (with pyspellchecker) |
| **Wording** | Double spaces, filler phrases, mixed terminology (Time-Off vs Requests) |
| **Aesthetics** | Hardcoded hex colors, button height/radius variance, raw `CTkFont()` |

## Agent workflow

1. **Run review** â€” `python dev.py ui-review -v`
2. **Read report** â€” `logs/ui_review/<latest>/report.md` and `report.json`
3. **Visual pass** (recommended) â€” open latest `logs/ui_live_test/<run>/` PNGs
4. **Fix by priority**
   - `error` spelling â†’ fix immediately
   - `warn` wording mismatches (nav vs profile shortcuts, inconsistent labels)
   - `info` aesthetics â†’ align colors to `config`/`theme`, standardize button sizes
5. **Re-run** â€” `python dev.py ui-review --strict` until 0 errors/warnings
6. **Verify** â€” `python dev.py ui-exhaustive` and `python dev.py check`

## Fix guidelines

- **Colors**: use `DODGEVILLE_*`, `UI_*` from `config.py`; Gantt uses `GANTT_COLORS`
- **Fonts**: `font("body")`, `font("heading")` from `ui/theme.py` â€” not raw `CTkFont`
- **Buttons**: primary actions `height=36â€“38`, table row actions `height=28â€“32`, `corner_radius=8` toolbars / `CORNER_RADIUS` cards
- **Copy**: match `NAV_ITEMS` labels in profile shortcuts and dialogs; professional police-department tone
- **Whitelist**: add legitimate domain terms to `scripts/data/ui_review_whitelist.txt`

## Scope boundaries

- **Do** edit `ui/*.py`, `ui/theme.py`, whitelist file
- **Do not** change scheduling logic, validators, or SQL for aesthetics-only work
- **Do not** weaken permission messages for brevity

## Delegation

| Finding type | Skill |
|--------------|-------|
| Theme/layout/widgets | `ui-development` |
| Review tooling itself | `cli-operations` |
| Cross-cutting | `dodgeville-scheduler` |
