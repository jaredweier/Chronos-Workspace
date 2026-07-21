# UI modern (Grok — on demand)

`@logs/agent_kit/latest.md` · skill: `.grok/skills/ui-development/SKILL.md`

## Design skill XOR (mandatory)

On UI visual work, load **one** of:

- **frontend-design** — `.grok/skills/frontend-design/SKILL.md` (or `.agents/skills/frontend-design/`)
- **taste-skill** — one skill from the taste pack (e.g. `design-taste-frontend`, `redesign-existing-projects`) under `.grok/skills/` / `.agents/skills/`

**Never both** unless the user explicitly says to combine. User-named skill wins. Unspecified: Chronos polish → taste; greenfield brand look → frontend-design. State the pick in one line. See `AGENTS.md` § UI design skills.

## Tokens
`usage-brief <slice>` → `outline ui/*_pages.py` → edit widgets first → `ui-review` → `verify --tier fast`

## Design system (must use)
| Token / widget | Role |
|----------------|------|
| `PrimaryButton` | One filled accent CTA only |
| `SecondaryButton` | Neutral outline |
| `DangerButton` | Destructive outline (never solid red next to green) |
| `EmptyState` | Empty lists — title + hint + optional CTA |
| `ToastHost` / `set_status` | Success feedback (not `messagebox.showinfo`) |
| `font("…")` | Never raw `CTkFont` |
| `UI_*` / `DODGEVILLE_*` | No hardcoded hex in pages |

## Copy
- **Sentence case** chrome ("Save changes", not "Save Changes")
- One product term: **Shift exchange**, **Blackout dates**
- Status bar quiet: background refresh → `set_status(..., toast=False)`

## Layout / LE enterprise look
- Hide subnav when page has no hub (`_update_subnav` must `grid_remove`)
- Cards: `UI_SURFACE` + `UI_BORDER` / `UI_BORDER_GLOW`; `Card(..., accent=True)` for hot panels
- StatCard left rail; NavButton lit rail when active; SegmentBar filled accent when active
- Micro labels: `micro_label(parent, "Ops floor")` for command-center chrome
- Gantt: thin bars, today = `UI_ACCENT_GLOW` border
- Never rainbow toolbars — primary / secondary / danger hierarchy only

## Free verify ladder
`ui-review` → `ui-diff --quick` → `ui-smoke` → `check` → vision only if needed

## Research (read once)
`docs/UI_RESEARCH_BRIEF.md` — Mark43, Deputy, Gusto, Linear 2026, COPS LE dashboards

## Patterns to prefer
| Pattern | Widget / API |
|---------|----------------|
| Severity strip | `AlertBanner(..., severity=critical|warning|success)` |
| Schedule legend | `StatusLegend(parent, [(label, color), ...])` |
| Outcome shortcut | `ActionTile(title, subtitle, command=…)` |
| Jump / command | Topbar SearchBar + Ctrl+K → `_jump_to_page` |

## OSS
[CustomTkinter](https://github.com/TomSchimansky/CustomTkinter) · project theme `ui/theme.py` · `ui/widgets.py`
