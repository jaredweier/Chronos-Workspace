---
name: ui-development
description: Chronos NiceGUI gui/* pages/widgets. Prefer docs + ui-domain only if API unknown.
---

# UI Development â€” focused

## Goal

Ship solid Chronos UI. Prefer in-repo tokens/docs; OSS only if user asks or API unknown.

## Tools

```bash
python dev.py ui-domain explore|brainstorm|research-queries|suggest --all|learn
python dev.py ui-review · ui-diff --quick · chronos-e2e
```

## Surfaces

- Primary: `gui/app.py`, `gui/shell.py`, `gui/pages/*`, `gui/static/chronos.css`, `gui/tables.py`
- Legacy `ui/*` only as reference

## Implementation

- Prefer complete UX over half-wired features
- Call `logic.*` for domain ops; no SQL in gui/
- Keep `.grok/rules/ui-modern.md` tokens

## Related

`scheduling-logic` · `ui-aesthetics-review` · `docs/AGENT_STABLE.md`
