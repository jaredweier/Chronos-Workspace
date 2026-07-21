"""
Law-enforcement scheduling feature benchmark — free local checklist.

Compares Chronos/Dodgeville capabilities to common commercial LE scheduling
product themes (Aladtec, Snap Schedule, inTime, Vector, First Due — public feature lists).

Does **not** claim competitive parity. Honest Have / Partial / Missing.

    python dev.py le-benchmark
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Literal, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

Status = Literal["have", "partial", "missing"]


@dataclass
class FeatureRow:
    area: str
    feature: str
    status: Status
    evidence: str  # path or symbol
    commercial_note: str


def _exists(*rels: str) -> bool:
    return any((ROOT / r).is_file() for r in rels)


def _logic_has(name: str) -> bool:
    try:
        from scripts.logic_resolve import logic_has

        return logic_has(name)
    except Exception:
        return False


def _gui_mentions(*needles: str) -> bool:
    gui = ROOT / "gui"
    if not gui.is_dir():
        return False
    for path in gui.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="replace").lower()
        if all(n.lower() in text for n in needles):
            return True
        if any(n.lower() in text for n in needles):
            # single needle hits count as weak presence
            if len(needles) == 1:
                return True
    return False


def build_rows() -> List[FeatureRow]:
    rows: List[FeatureRow] = []

    def add(area, feature, status, evidence, note):
        rows.append(FeatureRow(area, feature, status, evidence, note))

    # Core rotation / coverage
    add(
        "Rotation",
        "14-day / Panama-style squad rotation",
        "have" if _logic_has("get_cycle_day") else "missing",
        "logic/scheduling.py + rust",
        "Snap/Aladtec rotating patterns",
    )
    add(
        "Coverage",
        "Cascading bump / replacement chain",
        "have" if _logic_has("suggest_bump_chain") else "missing",
        "logic/scheduling.py, coverage_optimizer",
        "Core LE differentiator vs retail schedulers",
    )
    add(
        "Coverage",
        "Night minimum (Fri/Sat)",
        "have",
        "validators + config.NIGHT_MINIMUM",
        "Public-safety staffing floors",
    )
    add(
        "Coverage",
        "Minimum rest between shifts",
        "have",
        "validators.validate_minimum_rest_gap",
        "Fatigue / FLSA-adjacent",
    )
    add(
        "Coverage",
        "Multi-plan “best coverage” ranking",
        "have" if _logic_has("preview_best_coverage_plans") else "missing",
        "logic.preview_best_coverage_plans",
        "Supervisor decision support",
    )
    add(
        "Coverage",
        "Optional CP-SAT multi-day feasibility",
        "partial" if _exists("logic/cp_sat_bridge.py") else "missing",
        "logic/cp_sat_bridge.py (optional ortools)",
        "OR-Tools class optimizers",
    )

    # Leave / swaps
    add(
        "Leave",
        "Day-off request + approve/reject",
        "have" if _logic_has("process_day_off_request") else "missing",
        "logic/requests.py + gui/pages/leave.py",
        "All commercial LE products",
    )
    add(
        "Leave",
        "Shift exchange / swap workflow",
        "have" if _logic_has("process_shift_swap") else "missing",
        "logic/requests.py",
        "Aladtec/Snap",
    )
    add(
        "Leave",
        "Court / training request types",
        "have"
        if _exists("logic/court_calendar.py") and _gui_mentions("court")
        else ("partial" if _exists("logic/court_calendar.py") else "missing"),
        "logic/court_calendar.py + gui/pages/court.py",
        "LE-specific leave types",
    )

    # Self-service / ops
    add(
        "Self-service",
        "Open shift post/claim",
        "have" if _logic_has("create_open_shift") else "missing",
        "logic/operations.py",
        "Marketplace-style fill",
    )
    add(
        "Self-service",
        "Shift bidding (events + awards)",
        "have"
        if _logic_has("create_shift_bid_event") and _gui_mentions("bidding")
        else ("partial" if _logic_has("create_shift_bid_event") else "missing"),
        "logic/bidding.py + gui/pages/bidding.py",
        "Seniority bid cycles (common LE)",
    )
    add(
        "Self-service",
        "Callback / extra-duty rotation",
        "have"
        if _exists("logic/callbacks.py") and _gui_mentions("callback")
        else ("partial" if _exists("logic/callbacks.py") else "missing"),
        "logic/callbacks.py + ops callout",
        "OT fairness lists",
    )

    # Time / payroll
    add(
        "Payroll",
        "Timecard + pay period lock",
        "have" if _logic_has("lock_pay_period") else "missing",
        "logic/payroll",
        "TCP/Aladtec timekeeping",
    )
    add(
        "Payroll",
        "Banked / comp time",
        "have" if _exists("logic/banked_time.py") else "missing",
        "logic/banked_time.py",
        "Public sector leave banks",
    )
    add(
        "Payroll",
        "FLSA / hours watch",
        "have"
        if _exists("logic/labor_compliance.py") and _exists("logic/dual_workforce.py")
        else ("partial" if _exists("logic/labor_compliance.py") else "missing"),
        "logic/labor_compliance.py + dual_workforce + payroll UI",
        "FLSA 7(k) period tracking",
    )

    # UI / access
    add(
        "UI",
        "Multi-user web console",
        "have" if _exists("gui/app.py") else "missing",
        "gui/ NiceGUI Chronos Command",
        "SaaS LE products are web-first",
    )
    add(
        "UI",
        "Mobile-first officer app",
        "partial" if _exists("gui/pages/mobile_home.py") else "missing",
        "gui/pages/mobile_home.py + PWA offline shell (not native store app)",
        "Aladtec/First Due mobile apps",
    )
    add(
        "UI",
        "Rich data grids (AG Grid)",
        "partial" if _exists("gui/tables.py") else "missing",
        "gui/tables.py helper (NiceGUI ui.aggrid)",
        "Enterprise roster/ledger UX",
    )
    add(
        "UI",
        "Live coverage heat / SOC board",
        "partial" if _gui_mentions("live") or _exists("gui/pages/schedules.py") else "missing",
        "gui/pages/schedules.py",
        "Ops floor dashboards",
    )

    # Integrations / ops
    add(
        "Integrations",
        "iCal / calendar export",
        "have" if _logic_has("export_officer_schedule_ical") else "missing",
        "logic/exports.py",
        "Officer personal calendars",
    )
    add(
        "Integrations",
        "LDAP / SSO",
        "partial" if _exists("logic/ldap_auth.py") else "missing",
        "logic/ldap_auth.py (optional)",
        "Enterprise IdP",
    )
    add(
        "Integrations",
        "CAD / RMS bidirectional",
        "partial" if _exists("logic/cad_rms_bridge.py") else "missing",
        "logic/cad_rms_bridge.py + /api/cad/inbound (bridge, not full vendor CAD)",
        "Vendor lock-in territory",
    )
    add(
        "Ops",
        "Certifications / training gates",
        "have"
        if _exists("logic/certifications.py") and _gui_mentions("cert")
        else ("partial" if _exists("logic/certifications.py") else "missing"),
        "logic/certifications.py + publish soft gates",
        "Qualification-based assignment",
    )
    add(
        "Ops",
        "Equitable OT ledger",
        "have" if _exists("logic/ot_equity_ledger.py") or _logic_has("get_ot_equity_summary") else "missing",
        "logic/ot_equity_ledger.py + fill modes",
        "OT fairness reporting",
    )
    add(
        "Ops",
        "SMS / push notifications",
        "partial" if _exists("logic/notify_channels.py") else "missing",
        "logic/notify_channels.py outbox + Twilio/SMTP when creds (file sink local)",
        "Callback paging",
    )
    add(
        "Ops",
        "Station / post min-staff board",
        "have" if _exists("logic/stations.py") else "missing",
        "logic/stations.py station_staffing_board + Ops Desk",
        "ESO multi-site post matrix",
    )
    add(
        "Ops",
        "Fatigue / rest hard stop + watchlist",
        "have" if _exists("logic/fatigue_gates.py") else "missing",
        "logic/fatigue_gates.py (open shift + manual cover + ops strip)",
        "Officer wellness / rest between shifts",
    )
    add(
        "Ops",
        "Scenario / what-if simulator",
        "have" if _logic_has("run_staffing_optimizer") or _exists("gui/pages/simulator/page.py") else "missing",
        "gui/pages/simulator/page.py",
        "Staffing planning",
    )

    return rows


def run_le_benchmark() -> int:
    rows = build_rows()
    counts = {"have": 0, "partial": 0, "missing": 0}
    for r in rows:
        counts[r.status] += 1

    print("Dodgeville PD — LE scheduling feature benchmark (honest)")
    print("Themes from public commercial LE product lists (Aladtec, Snap, inTime, …)")
    print("=" * 78)
    print(f"{'Area':<14} {'Status':<8} Feature")
    print("-" * 78)
    for r in rows:
        mark = {"have": "HAVE", "partial": "PART", "missing": "MISS"}[r.status]
        print(f"{r.area:<14} {mark:<8} {r.feature}")
        print(f"{'':14} {'':8}  → {r.evidence}")
    print("-" * 78)
    total = len(rows)
    print(f"HAVE {counts['have']} · PARTIAL {counts['partial']} · MISSING {counts['missing']} · total {total}")
    print()
    print("Strengths: rotation/bump math, leave, swaps, payroll depth, simulator, CLI.")
    print("Gaps: mobile app, SMS/paging, CAD/RMS, full Chronos bid UI, rich grids everywhere.")
    print("Next product bets: bidding UI · open-shift UX · AG Grid ledgers · notify channels.")
    print("=" * 78)
    print("Related: python dev.py parity-audit · docs/UI_RESEARCH_BRIEF.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_le_benchmark())
