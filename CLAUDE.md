# Claude / multi-agent notes

**Binding process:** `AGENTS.md` + bootstrap `logs/SESSION_CONTRACT.md`.
**Trust:** `docs/AGENT_TRUST_AND_MISTAKES.md` · **Verify:** `.grok/rules/verify-policy.md`

- Caveman + token min (see AGENTS)
- **Cost split:** easy → cheap agents/models; hard product/logic → primary; prefer lower total usage
- Tools/skills/subagents OK if cheaper/better (including verify gates when cheaper)
- Graphify / vision / GBrain: OK when cost/ROI beats primary (not every turn)
- Archived skills: use temporarily → put back in `docs/archived_skills/`
- Ship: `python dev.py verify --tier check` → `honest_gate: true`
- Logic/gui edits: `verify --tier core` first; never claim done on fast alone

## Optional (Claude Code host)

```bash
python scripts/session_auto_bootstrap.py
python dev.py graphify-gate   # only if using graphify this session
```

UI skills XOR: taste (Chronos polish) **or** frontend-design — not both unless asked.
Domain skills: `.grok/skills/*` · on-demand rules: `.grok/rules/on-demand/`
