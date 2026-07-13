"""Recommend agent, skill, model tier, and cost class by task complexity and domain.

Auto-routes cheaper/faster models and free terminal tools for low complexity.
UI work is split across static (free), copy (cheap), layout (balanced), vision, and
browser agents (expensive) — including curated open-source UI agents from GitHub.
"""

from __future__ import annotations

import re
import sys
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

ROOT = __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__)))


# ---------------------------------------------------------------------------
# Catalog: cost tiers + models (advisory — any LLM allowed)
# ---------------------------------------------------------------------------

COST_ORDER = ("free", "cheap", "balanced", "flagship", "vision")

# Prefer lower cost within each complexity band
MODEL_BY_COST: Dict[str, str] = {
    "free": "none — terminal only (dev.py / pre-commit / CI)",
    "cheap": "fast/mini: Haiku, GPT-4o-mini, Gemini Flash, Grok Fast, Cursor Auto, Composer-fast",
    "balanced": "mid: Sonnet, Grok, Composer, GLM-class mid, OpenCode small→primary",
    "flagship": "reasoning/flagship: Opus, Sonnet-4-class, Grok reasoning, o-series",
    "vision": "vision-capable: Sonnet vision, GPT-4o, Grok vision, Gemini multimodal",
}

# ---------------------------------------------------------------------------
# UI / coding agent catalog (in-repo + internet/GitHub)
# Cost: free < cheap < balanced < flagship < vision
# ---------------------------------------------------------------------------

AGENT_CATALOG: Dict[str, Dict[str, Any]] = {
    # --- Free / terminal (always prefer first) ---
    "terminal-verify": {
        "kind": "in_repo",
        "cost": "free",
        "harness": "terminal",
        "when": "verify, audit, imports, cheap-check, preflight",
        "invoke": "python dev.py verify --tier fast|preflight|check",
        "url": None,
    },
    "ui-static-free": {
        "kind": "in_repo",
        "cost": "free",
        "harness": "terminal",
        "when": "spelling, wording scan, theme tokens without screenshots",
        "invoke": "python dev.py ui-review; python dev.py ui-diff --quick",
        "url": None,
    },
    # --- In-repo skills / OpenCode agents ---
    "cursor-tab": {
        "kind": "harness",
        "cost": "free",
        "harness": "cursor_tab",
        "when": "typo, rename, one-line",
        "invoke": "Cursor Tab / inline",
        "url": "https://cursor.com",
    },
    "cursor-ask": {
        "kind": "harness",
        "cost": "cheap",
        "harness": "cursor_ask",
        "when": "explain, locate, document",
        "invoke": "Cursor Ask + Auto/mini model",
        "url": "https://cursor.com/blog/agent-best-practices",
    },
    "cursor-agent": {
        "kind": "harness",
        "cost": "balanced",
        "harness": "cursor_agent",
        "when": "multi-file implement/fix",
        "invoke": "Cursor Agent; Plan mode if high",
        "url": "https://cursor.com/blog/agent-best-practices",
    },
    "opencode-primary": {
        "kind": "opencode",
        "cost": "balanced",
        "harness": "opencode",
        "when": "general coding with BYOK multi-model",
        "invoke": "opencode · /route-task · small_model=fast for light steps",
        "url": "https://github.com/anomalyco/opencode",
    },
    "opencode-ui-vision": {
        "kind": "opencode",
        "cost": "vision",
        "harness": "opencode",
        "when": "screenshot / layout looks wrong",
        "invoke": "OpenCode agent ui-vision-reviewer · /ui-observe",
        "url": "https://github.com/anomalyco/opencode",
    },
    "opencode-ui-static": {
        "kind": "opencode",
        "cost": "cheap",
        "harness": "opencode",
        "when": "copy/theme without PNGs",
        "invoke": "OpenCode agent ui-static-reviewer",
        "url": None,
    },
    "opencode-ui-chronos": {
        "kind": "opencode",
        "cost": "balanced",
        "harness": "opencode",
        "when": "NiceGUI / Chronos gui/* pages",
        "invoke": "OpenCode agent ui-chronos",
        "url": None,
    },
    "opencode-qa-free": {
        "kind": "opencode",
        "cost": "free",
        "harness": "opencode",
        "when": "run free gates only",
        "invoke": "OpenCode agent qa-free · /cheap-check /check",
        "url": None,
    },
    "skill-ui-dev": {
        "kind": "skill",
        "cost": "balanced",
        "harness": "any",
        "when": "tabs, widgets, layout code",
        "invoke": ".grok/skills/ui-development/SKILL.md",
        "url": None,
    },
    "skill-ui-aesthetics": {
        "kind": "skill",
        "cost": "cheap",
        "harness": "any",
        "when": "copy, Title Case, theme consistency",
        "invoke": ".grok/skills/ui-aesthetics-review/SKILL.md",
        "url": None,
    },
    "skill-ui-vision": {
        "kind": "skill",
        "cost": "vision",
        "harness": "any",
        "when": "PNG observe / visual QA",
        "invoke": ".grok/skills/ui-vision-review/SKILL.md",
        "url": None,
    },
    # External browser: Playwright only in-catalog. Others: docs/UI_AGENTS_CATALOG.md (user-escalation).
    "playwright": {
        "kind": "external",
        "cost": "cheap",
        "harness": "scripted_browser",
        "when": "repeatable scripted E2E (prefer over vision for known paths)",
        "invoke": "Playwright Python/JS tests against Chronos URLs",
        "url": "https://github.com/microsoft/playwright",
    },
}


@dataclass
class RouteRecommendation:
    complexity: str
    cost_tier: str
    slice_id: str
    skill: str
    cursor_mode: str
    opencode_agent: str
    model_tier: str
    preferred_model: str
    primary_agent: str
    ui_lane: str
    agents: List[str] = field(default_factory=list)
    external_agents: List[str] = field(default_factory=list)
    subagents: List[str] = field(default_factory=list)
    verify: List[str] = field(default_factory=list)
    do_not: List[str] = field(default_factory=list)
    oss_searches: List[str] = field(default_factory=list)
    oss_actions: List[str] = field(default_factory=list)
    rationale: str = ""


# Domain: (regex, slice_id, skill, weight)
DOMAIN_KEYWORDS: List[Tuple[str, str, str, int]] = [
    (r"\b(bump|rotation|day.?off|swap|schedule|coverage|cascade|night.?min)\b", "scheduling", "scheduling-logic", 3),
    (r"\b(payroll|timecard|pay.?period|overtime|flsa)\b", "payroll-timecard", "payroll-timecard", 3),
    (r"\b(password|permission|auth|ldap|rbac|cjis)\b", "security", "security", 3),
    (r"\b(user.?account|create.?user|deactivate.?user)\b", "security", "security", 2),
    (r"\b(login|sign.?in)\b", "security", "security", 1),  # weak — may also be UI
    (r"\b(nicegui|chronos|duty.?console|gui/|gui\.)\b", "ui-chronos", "ui-development", 4),
    (r"\b(customtkinter|ctk)\b", "ui", "ui-development", 2),
    (r"\b(tab|widget|layout|nav|sidebar|dashboard|gantt|page)\b", "ui", "ui-development", 2),
    (
        r"\b(theme|css|spacing|contrast|title.?case|wording|label|copy|typography)\b",
        "ui-copy",
        "ui-aesthetics-review",
        3,
    ),
    (r"\b(screenshot|png|visual|look.?wrong|ui.?observe|pixel)\b", "ui-vision", "ui-vision-review", 4),
    (r"\b(browser.?use|playwright|skyvern|e2e|live.?ui|click.?through)\b", "ui-browser", "ui-vision-review", 4),
    (r"\b(simulator|what.?if|staffing.?sim)\b", "simulator", "ui-development", 2),
    (r"\b(cli|dev\.py|script|export|backup)\b", "cli-ops", "cli-operations", 3),
    (r"\b(build|pyinstaller|\.exe|frozen|dist)\b", "build", "build-deploy", 3),
    (r"\b(rust|scheduler_core|pyo3)\b", "scheduling", "scheduling-logic", 3),
    (r"\b(refactor|split|monolith|mixin)\b", "refactor", "refactor", 3),
    (r"\b(date.?format|format_date|m/d|timezone|clock)\b", "ui", "ui-development", 2),
    (r"\b(media|logo|upload|brand)\b", "ui-chronos", "ui-development", 2),
]

# Complexity signals — avoid false "trivial" on "date format"
TRIVIAL = re.compile(
    r"\b(typo|spell(ing)?|whitespace|trailing.?space|import.?order|rename.?only|comment.?only)\b",
    re.I,
)
VERIFY_ONLY = re.compile(
    r"\b(verify|check|test|audit|preflight|did.+pass|run.+tests|cheap.?check)\b",
    re.I,
)
VISION_COMPLEXITY = re.compile(
    r"\b(screenshot|visual|png|observe|look.?and.?feel|layout.?bug|ui.?review.?live|pixel|see.?the.?ui)\b",
    re.I,
)
BROWSER_COMPLEXITY = re.compile(
    r"\b(browser.?use|skyvern|playwright|e2e|click.?through|live.?browser|walk.?through.?ui)\b",
    re.I,
)
HIGH_COMPLEXITY = re.compile(
    r"\b(architect|refactor|multi.?slice|migrate|redesign|integrat|package.?split|rust|rewrite)\b",
    re.I,
)
LOW = re.compile(r"\b(explain|what does|how does|where is|document|locate)\b", re.I)
COPY_ONLY = re.compile(
    r"\b(title.?case|capitalize|wording|label.?text|spelling|copy.?edit|tooltip.?text)\b",
    re.I,
)
FIX_IMPL = re.compile(r"\b(fix|implement|add|build|wire|change|update|migrate)\b", re.I)


def _match_domain(text: str) -> Tuple[str, str, List[str]]:
    """Return best (slice_id, skill, matched_tags)."""
    scores: Dict[Tuple[str, str], int] = {}
    tags: List[str] = []
    for pattern, slice_id, skill, weight in DOMAIN_KEYWORDS:
        if re.search(pattern, text, re.I):
            key = (slice_id, skill)
            scores[key] = scores.get(key, 0) + weight
            tags.append(slice_id)
    if not scores:
        return "general", "dodgeville-scheduler", []
    best = max(scores.items(), key=lambda kv: kv[1])[0]
    return best[0], best[1], tags


def _complexity(text: str, override: str = "", domain_tags: Optional[List[str]] = None) -> str:
    if override:
        return override.lower()
    tags = domain_tags or []
    if BROWSER_COMPLEXITY.search(text) or "ui-browser" in tags:
        return "browser"
    # Typo/spelling stays free even when phrased as "fix typo …"
    if TRIVIAL.search(text):
        return "trivial"
    if VERIFY_ONLY.search(text) and not FIX_IMPL.search(text):
        return "verify"
    if VISION_COMPLEXITY.search(text) or "ui-vision" in tags:
        return "vision"
    if COPY_ONLY.search(text) and not re.search(r"\b(layout|widget|logic|implement|wire)\b", text, re.I):
        return "low"
    if HIGH_COMPLEXITY.search(text):
        return "high"
    if LOW.search(text):
        return "low"
    # Long multi-clause tasks → high
    if len(text.split()) > 30 or text.count(",") >= 3:
        return "high"
    if "ui-chronos" in tags or "nicegui" in text.lower():
        return "medium"
    return "medium"


def _cost_tier(complexity: str) -> str:
    return {
        "trivial": "free",
        "low": "cheap",
        "medium": "balanced",
        "high": "flagship",
        "vision": "vision",
        "browser": "vision",
        "verify": "free",
    }.get(complexity, "balanced")


def _ui_lane(complexity: str, tags: List[str], text: str) -> str:
    if complexity == "browser" or "ui-browser" in tags:
        return "browser"
    if complexity == "vision" or "ui-vision" in tags:
        return "vision"
    # Copy/title-case wins over chronos so we stay on cheap static agents
    if "ui-copy" in tags or COPY_ONLY.search(text):
        return "copy"
    if "ui-chronos" in tags or re.search(r"\b(nicegui|chronos)\b", text, re.I):
        return "chronos"
    if any(t.startswith("ui") for t in tags) or re.search(r"\b(ui|gui|layout|theme)\b", text, re.I):
        return "layout"
    if complexity == "verify":
        return "none"
    return "none"


def _cursor_mode(complexity: str) -> str:
    return {
        "trivial": "Tab completion (or inline edit) — no Agent",
        "low": "Ask + cheap model",
        "medium": "Agent + balanced model",
        "high": "Plan (Shift+Tab) then Agent + flagship",
        "vision": "Agent + 1 screenshot max (or Browser) + vision model",
        "browser": "Agent optional; prefer scripted Playwright then browser-use",
        "verify": "Terminal only (qa-free) — no LLM unless interpreting failure",
    }.get(complexity, "Agent")


def _model_tier(complexity: str) -> str:
    cost = _cost_tier(complexity)
    return MODEL_BY_COST[cost]


def _preferred_model(complexity: str) -> str:
    """Single concrete default pick (lowest cost that fits)."""
    return {
        "trivial": "none / Tab",
        "low": "Auto | Haiku | Flash | Grok Fast",
        "medium": "Sonnet | Grok | Composer | OpenCode primary",
        "high": "Opus / reasoning flagship",
        "vision": "vision model only after ui-review fails",
        "browser": "cheap model + Playwright first; vision only if needed",
        "verify": "none",
    }.get(complexity, "balanced mid-tier")


def _select_agents(complexity: str, ui_lane: str, skill: str) -> Tuple[str, str, List[str], List[str]]:
    """
    Returns primary_agent, opencode_agent, ordered agent ids, external agent ids.
    Core chains only (max 3). External OSS agents are user-escalation only.
    """
    external: List[str] = []

    if complexity == "verify":
        ordered = ["terminal-verify", "opencode-qa-free"]
        return "terminal-verify", "qa-free", ordered[:3], external

    if complexity == "trivial":
        ordered = ["cursor-tab", "ui-static-free", "terminal-verify"]
        return "cursor-tab", "primary (skip if Tab done)", ordered[:3], external

    if complexity == "low" and ui_lane in ("copy", "layout", "none"):
        if ui_lane == "copy":
            ordered = ["ui-static-free", "skill-ui-aesthetics", "cursor-ask"]
            return "skill-ui-aesthetics", "ui-static-reviewer", ordered[:3], external
        ordered = ["cursor-ask", "opencode-primary"]
        return "cursor-ask", "primary + small_model", ordered[:3], external

    if ui_lane == "copy":
        ordered = ["ui-static-free", "skill-ui-aesthetics", "cursor-agent"]
        return "skill-ui-aesthetics", "ui-static-reviewer", ordered[:3], external

    if ui_lane == "chronos":
        if complexity in ("vision", "browser"):
            ordered = ["ui-static-free", "playwright", "opencode-ui-chronos"]
            external = ["playwright"]
            return "playwright", "ui-chronos", ordered[:3], external
        ordered = ["cursor-agent", "skill-ui-dev", "opencode-ui-chronos"]
        primary = "cursor-agent" if complexity == "high" else "cursor-agent"
        return primary, "ui-chronos", ordered[:3], external

    if ui_lane == "vision" or complexity == "vision":
        ordered = ["ui-static-free", "skill-ui-vision", "opencode-ui-vision"]
        return "skill-ui-vision", "ui-vision-reviewer", ordered[:3], external

    if ui_lane == "browser" or complexity == "browser":
        ordered = ["playwright", "opencode-ui-chronos", "cursor-agent"]
        external = ["playwright"]
        return "playwright", "ui-chronos", ordered[:3], external

    if ui_lane == "layout":
        ordered = ["skill-ui-dev", "cursor-agent", "opencode-primary"]
        return "skill-ui-dev", f"primary + skill {skill}", ordered[:3], external

    if complexity == "high":
        ordered = ["cursor-agent", "opencode-primary"]
        return "cursor-agent (Plan first)", f"primary + skill {skill}", ordered[:3], external

    if complexity == "medium":
        ordered = ["cursor-agent", "opencode-primary"]
        return "cursor-agent", f"primary + skill {skill}", ordered[:3], external

    ordered = ["cursor-ask", "opencode-primary"]
    return "cursor-ask", "primary", ordered[:3], external


def _subagents(complexity: str, skill: str, ui_lane: str) -> List[str]:
    """At most one skill name. Never dual-load. qa-verify is a terminal gate, not a subagent."""
    if complexity in ("verify", "trivial", "low"):
        return []
    if complexity == "high":
        return [skill] if skill else []
    if complexity in ("vision", "browser") or ui_lane in ("vision", "browser"):
        return ["ui-vision-review"]
    if ui_lane == "chronos":
        return []  # skill already on route.skill
    if complexity == "medium":
        return [skill] if skill else []
    return []


def _verify_commands(complexity: str, slice_id: str, ui_lane: str) -> List[str]:
    cmds = ["python dev.py verify --tier fast"]
    if complexity == "verify":
        return [
            "python dev.py verify --tier fast",
            "python dev.py verify --tier preflight",
            "python dev.py verify --tier check",
        ]
    if ui_lane in ("copy", "layout", "chronos", "vision"):
        cmds.append("python dev.py ui-review")
    if ui_lane in ("vision", "browser"):
        cmds.append("python dev.py ui-diff --quick")
        cmds.append("# only if still stuck: python dev.py ui-observe --live  (1 PNG)")
    if slice_id and slice_id not in ("general", "ui", "ui-copy", "ui-vision", "ui-chronos", "ui-browser"):
        cmds.append(f"python dev.py verify-slice {slice_id}")
    if complexity in ("medium", "high", "vision", "browser") or ui_lane == "chronos":
        cmds.append("python dev.py verify --tier check  # ship gate")
    return cmds


def _do_not(complexity: str, ui_lane: str) -> List[str]:
    """Hard cost guards — short list."""
    tips = [
        "Caveman replies (short bullets). No vision/flagship for verify/trivial/low.",
        "No subagents for gates. Ship only after check + honest_gate.",
        "OSS research only if user asks or API truly unknown (medium+).",
    ]
    if complexity in ("verify", "trivial", "low"):
        tips.append("Stay free/cheap: Tab/Ask/terminal only.")
    if ui_lane in ("vision", "browser"):
        tips.append("Static ui-review / ui-diff --quick before any PNG vision.")
    return tips


def _oss_hints(text: str, complexity: str, ui_lane: str, tags: List[str]) -> Tuple[List[str], List[str]]:
    """Opt-in research only. Empty for verify/trivial/low unless debugging foreign API."""
    if complexity in ("verify", "trivial", "low"):
        return [], []

    searches: List[str] = []
    actions: List[str] = []
    keywords = " ".join(text.split()[:8])

    # Medium+ only: minimal hints when UI/API keywords present
    if complexity in ("high", "vision", "browser") or (
        complexity == "medium"
        and (
            ui_lane in ("chronos", "layout", "vision", "browser")
            or re.search(r"\b(nicegui|unknown api|how do i|docs)\b", text, re.I)
        )
    ):
        if ui_lane in ("chronos", "layout") or re.search(r"\b(nicegui|gui/)\b", text, re.I):
            searches.append(f"site:nicegui.io/documentation {keywords}")
            actions.append("Optional: python dev.py ui-domain research-queries (user-ask or API unknown)")

        if ui_lane in ("vision", "browser") or complexity in ("vision", "browser"):
            searches.append("Playwright Python login flow example")
            actions.append("Prefer playwright over vision agents")

        if re.search(r"\b(auth|login|session|storage)\b", text, re.I):
            searches.append("NiceGUI authentication example github")

        if re.search(
            r"\b(bump|cascade|cp.?sat|ortools|optimizer)\b",
            text,
            re.I,
        ):
            searches.append(f"OR-Tools CP-SAT {keywords}")
            actions.append("Optional: python dev.py math-domain explore (user-ask)")

    if not searches and not actions:
        return [], []

    def _dedupe(items: List[str]) -> List[str]:
        seen = set()
        out = []
        for x in items:
            if x not in seen:
                seen.add(x)
                out.append(x)
        return out

    return _dedupe(searches)[:4], _dedupe(actions)[:4]


def route_task(
    task: str,
    *,
    complexity_override: str = "",
    slice_override: str = "",
) -> RouteRecommendation:
    text = (task or "").strip()
    slice_id, skill_name, tags = _match_domain(text)
    complexity = _complexity(text, complexity_override, tags)
    if slice_override:
        slice_id = slice_override

    ui_lane = _ui_lane(complexity, tags, text)
    cost = _cost_tier(complexity)

    # Force skill for UI lanes
    if ui_lane == "copy":
        skill_name = "ui-aesthetics-review"
        if slice_id == "general":
            slice_id = "ui-copy"
    elif ui_lane == "vision":
        skill_name = "ui-vision-review"
        if slice_id in ("general", "cli-ops"):
            slice_id = "ui-vision"
    elif ui_lane == "chronos":
        skill_name = "ui-development"
        if slice_id == "general":
            slice_id = "ui-chronos"
    elif ui_lane == "browser":
        skill_name = "ui-vision-review"
        slice_id = "ui-browser"
    elif ui_lane == "layout" and skill_name == "dodgeville-scheduler":
        skill_name = "ui-development"

    primary, opencode, agents, external = _select_agents(complexity, ui_lane, skill_name)
    oss_searches, oss_actions = _oss_hints(text, complexity, ui_lane, tags)

    rationale = (
        f"tags={tags or ['general']} slice=`{slice_id}` skill=`{skill_name}` "
        f"complexity=`{complexity}` cost=`{cost}` ui=`{ui_lane}` agent=`{primary}`."
    )
    if complexity_override:
        rationale += f" Override complexity={complexity_override}."

    return RouteRecommendation(
        complexity=complexity,
        cost_tier=cost,
        slice_id=slice_id,
        skill=f".grok/skills/{skill_name}/SKILL.md",
        cursor_mode=_cursor_mode(complexity),
        opencode_agent=opencode,
        model_tier=_model_tier(complexity),
        preferred_model=_preferred_model(complexity),
        primary_agent=primary,
        ui_lane=ui_lane,
        agents=agents,
        external_agents=external,
        subagents=_subagents(complexity, skill_name, ui_lane),
        verify=_verify_commands(complexity, slice_id, ui_lane),
        do_not=_do_not(complexity, ui_lane),
        oss_searches=oss_searches,
        oss_actions=oss_actions,
        rationale=rationale,
    )


def format_recommendation_compact(rec: RouteRecommendation) -> str:
    """Minimal route line for agent-pack."""
    verify = rec.verify[0] if rec.verify else "python dev.py verify --tier fast"
    skill = rec.skill.split("/")[-2] if "/" in rec.skill else rec.skill
    return (
        f"tier={rec.complexity} cost={rec.cost_tier} agent={rec.primary_agent} "
        f"model={rec.preferred_model.split('|')[0].strip()} "
        f"slice={rec.slice_id} skill={skill} ui={rec.ui_lane} verify={verify}"
    )


def format_recommendation(rec: RouteRecommendation, task: str) -> str:
    lines = [
        "Chronos route",
        f"task: {task[:120]}{'…' if len(task) > 120 else ''}",
        f"cost={rec.cost_tier} complexity={rec.complexity} ui={rec.ui_lane}",
        f"primary={rec.primary_agent} model={rec.preferred_model.split('|')[0].strip()}",
        f"slice={rec.slice_id} skill={rec.skill}",
        f"cursor={rec.cursor_mode} opencode={rec.opencode_agent}",
        f"rationale: {rec.rationale}",
        "chain:",
    ]
    for i, aid in enumerate(rec.agents[:3], 1):
        meta = AGENT_CATALOG.get(aid, {})
        lines.append(f"  {i}. [{meta.get('cost', '?')}] {aid}")
    if rec.subagents:
        lines.append(f"subagents: {', '.join(rec.subagents)}")
    if rec.external_agents:
        lines.append(f"external (user-escalation): {', '.join(rec.external_agents)}")
    if rec.oss_searches or rec.oss_actions:
        lines.append("oss (optional):")
        for q in rec.oss_searches:
            lines.append(f"  · {q}")
        for a in rec.oss_actions:
            lines.append(f"  · {a}")
    lines.append("verify:")
    for cmd in rec.verify[:4]:
        lines.append(f"  {cmd}")
    lines.append("guards:")
    for d in rec.do_not:
        lines.append(f"  · {d}")
    return "\n".join(lines)


def run_agent_route(
    task: str,
    *,
    complexity: str = "",
    slice_id: str = "",
    as_json: bool = False,
    verbose: bool = False,
) -> int:
    if not task.strip():
        print('Usage: python dev.py route-task "fix bump approval"')
        print('       python dev.py route-task --json "fix bump approval"')
        print('       python dev.py route-task --verbose "…"')
        print('       python dev.py route-task --complexity vision "layout broken"')
        return 1
    rec = route_task(task, complexity_override=complexity, slice_override=slice_id)
    if as_json:
        from scripts.structured_output import dump_json, shape_route

        print(dump_json(shape_route(rec)))
        return 0
    if verbose:
        print(format_recommendation(rec, task))
    else:
        print(format_recommendation_compact(rec))
        print(f"task: {task[:100]}{'…' if len(task) > 100 else ''}")
        print(f"rationale: {rec.rationale}")
        if rec.do_not:
            print("guards: " + "; ".join(rec.do_not[:2]))
    return 0


if __name__ == "__main__":
    args = sys.argv[1:]
    comp = ""
    slice_ov = ""
    as_json = False
    verbose = False
    rest: List[str] = []
    i = 0
    while i < len(args):
        if args[i] == "--complexity" and i + 1 < len(args):
            comp = args[i + 1]
            i += 2
        elif args[i] == "--slice" and i + 1 < len(args):
            slice_ov = args[i + 1]
            i += 2
        elif args[i] == "--json":
            as_json = True
            i += 1
        elif args[i] == "--verbose":
            verbose = True
            i += 1
        else:
            rest.append(args[i])
            i += 1
    raise SystemExit(
        run_agent_route(" ".join(rest), complexity=comp, slice_id=slice_ov, as_json=as_json, verbose=verbose)
    )
