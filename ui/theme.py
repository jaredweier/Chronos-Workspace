"""UI theme constants and fonts."""

import customtkinter as ctk

from config import (
    DODGEVILLE_ACCENT,
    DODGEVILLE_BLUE,
    DODGEVILLE_DANGER,
    DODGEVILLE_GOLD,
    DODGEVILLE_RED,
    DODGEVILLE_SUCCESS,
    DODGEVILLE_WARNING,
    UI_ACCENT_GLOW,
    UI_BG,
    UI_BORDER,
    UI_SIDEBAR,
    UI_SURFACE,
    UI_SURFACE_LIGHT,
    UI_TEXT_MUTED,
)

__all__ = [
    "DODGEVILLE_ACCENT",
    "DODGEVILLE_BLUE",
    "DODGEVILLE_DANGER",
    "DODGEVILLE_GOLD",
    "DODGEVILLE_RED",
    "DODGEVILLE_SUCCESS",
    "DODGEVILLE_WARNING",
    "UI_ACCENT_GLOW",
    "UI_BG",
    "UI_BORDER",
    "UI_SIDEBAR",
    "UI_SURFACE",
    "UI_SURFACE_LIGHT",
    "UI_TEXT_MUTED",
]

FONT_SPECS = {
    "title": {"size": 34, "weight": "bold"},
    "heading": {"size": 24, "weight": "bold"},
    "subheading": {"size": 18, "weight": "bold"},
    "body": {"size": 16},
    "small": {"size": 14},
    "stat_value": {"size": 34, "weight": "bold"},
    "stat_label": {"size": 14},
    "nav": {"size": 16, "weight": "bold"},
    "nav_section": {"size": 12, "weight": "bold"},
    "mono": {"size": 14, "family": "Consolas"},
}

_font_cache: dict = {}


def font(key: str) -> ctk.CTkFont:
    if key not in _font_cache:
        _font_cache[key] = ctk.CTkFont(**FONT_SPECS[key])
    return _font_cache[key]


STATUS_COLORS = {
    "Pending": DODGEVILLE_WARNING,
    "Pending Manual Review": DODGEVILLE_WARNING,
    "Approved": DODGEVILLE_SUCCESS,
    "Rejected": DODGEVILLE_DANGER,
    "Active": DODGEVILLE_SUCCESS,
    "Inactive": "#6B7280",
    "Auto OK": DODGEVILLE_SUCCESS,
    "Needs Review": DODGEVILLE_WARNING,
    "Open": DODGEVILLE_WARNING,
    "Filled": UI_TEXT_MUTED,
    "Working": DODGEVILLE_SUCCESS,
    "Off": "#6B7280",
    "Bumped": DODGEVILLE_WARNING,
    "Covering": DODGEVILLE_GOLD,
    "Swapped": DODGEVILLE_ACCENT,
    "Training": "#1ABC9C",
    "Court": "#8E44AD",
    "Leave": "#5D6D7E",
}

SCHEDULE_STATUS_LABELS = {
    "working": "Working",
    "off": "Off",
    "bumped": "Bumped",
    "covering": "Covering",
    "swapped": "Swapped",
    "training": "Training",
    "court": "Court",
    "leave": "Leave",
}

# Nav keys requiring a permission (omitted = visible to all signed-in roles)
NAV_PERMISSIONS = {
    "officers": "officers.manage",
    "simulator": "simulator.use",
    "reports": "reports.view",
    "users": ("users.manage", "users.edit_role"),
}

# Every page frame key (used by tests, show_page, permissions)
NAV_ITEMS = [
    ("dashboard", "Command Post", "★"),
    ("base_schedule", "Original Monthly Schedule", "▦"),
    ("live_schedule", "Live Schedule", "▧"),
    ("timecard", "Timecard", "🕐"),
    ("banked_time", "Banked Time", "🏦"),
    ("timeline", "Duty Timeline", "▬"),
    ("requests", "Time Off", "✉"),
    ("swaps", "Shift Exchange", "⇄"),
    ("notifications", "Alerts", "🔔"),
    ("officers", "Patrol Roster", "👮"),
    ("payroll", "Payroll Ledger", "💲"),
    ("simulator", "Scenario Trainer", "⚙"),
    ("reports", "Ops Reports", "📊"),
    ("availability", "Blackout Dates", "📅"),
    ("users", "Access Control", "🔐"),
]

# Hub groups — related tabs combined under one sidebar item + sub-navigation
NAV_HUBS: dict[str, dict] = {
    "schedules": {
        "label": "Schedules",
        "icon": "▦",
        "default": "base_schedule",
        "pages": ("base_schedule", "live_schedule", "timeline"),
        "tabs": (
            ("base_schedule", "Original Monthly"),
            ("live_schedule", "Live Schedule"),
            ("timeline", "Timeline"),
        ),
    },
    "leave": {
        "label": "Leave & Swaps",
        "icon": "✉",
        "default": "requests",
        "pages": ("requests", "swaps"),
        "tabs": (
            ("requests", "Time Off"),
            ("swaps", "Shift Exchange"),
        ),
    },
    "payroll_hub": {
        "label": "Payroll",
        "icon": "💲",
        "default": "timecard",
        "pages": ("timecard", "banked_time", "payroll"),
        "tabs": (
            ("timecard", "Timecard"),
            ("banked_time", "Banked Time"),
            ("payroll", "Ledger"),
        ),
    },
    "operations": {
        "label": "Operations",
        "icon": "📊",
        "default": "reports",
        "pages": ("reports", "availability", "simulator"),
        "tabs": (
            ("reports", "Reports"),
            ("availability", "Blackout Dates"),
            ("simulator", "Trainer"),
        ),
    },
}

# Consolidated sidebar (fewer items, grouped by workflow)
# Entries: ("section", "Label") | (key, label, icon)  — key may be hub or page
SIDEBAR_NAV = [
    ("section", "Overview"),
    ("dashboard", "Command Post", "★"),
    ("section", "Scheduling"),
    ("schedules", "Schedules", "▦"),
    ("leave", "Leave & Swaps", "✉"),
    ("section", "People"),
    ("officers", "Roster", "👮"),
    ("section", "Finance"),
    ("payroll_hub", "Payroll", "💲"),
    ("section", "Administration"),
    ("operations", "Operations", "📊"),
    ("users", "Access Control", "🔐"),
]

PAGE_SUBTITLES = {
    "dashboard": "Today's watch, alerts, and pending actions",
    "base_schedule": "Rotation plan from squad and shift assignments, fixed after generation",
    "live_schedule": "Live schedule — auto-updates when time off, bumps, swaps, or coverage changes",
    "timecard": "Biweekly pay period time entry (hours count where shift starts)",
    "banked_time": "Comp, sick, and holiday banks with FLSA §207(k) tracking from timecards",
    "timeline": "14 day duty timeline by officer and squad",
    "requests": "Submit time off, preview coverage, and review history",
    "swaps": "Exchange shifts between officers on the same duty day",
    "notifications": "Alerts for requests, swaps, and coverage events",
    "officers": "Photos, ranks, pay rates, and time banks",
    "payroll": "Biweekly pay period timesheets, totals, and ledger entries",
    "simulator": "Train on rotations, staffing models, and 24/7 coverage",
    "reports": "Coverage, overtime, labor cost, and exports",
    "availability": "Officer blackout dates and department holidays",
    "users": "Logins, roles, and password management",
}

OFFICER_PAGE_SUBTITLES = {
    "dashboard": "Your Rotation, Requests, And Alerts At A Glance",
    "base_schedule": "Original monthly plan. White border marks your scheduled days",
    "live_schedule": "Your live schedule with time off, bumps, and swaps",
    "timeline": "Your 14 day shift timeline",
    "requests": "Submit And Track Your Time Off Requests",
    "swaps": "Request And Manage Your Shift Swaps",
    "notifications": "Alerts For Your Requests, Swaps, And Coverage",
    "timecard": "Your biweekly pay period time entries",
    "banked_time": "Your comp, sick, and holiday bank balances and FLSA status",
    "payroll": "Your biweekly pay period totals and ledger entries",
    "availability": "Mark Dates You Are Unavailable And View Holidays",
}

UI_TEXT_LIGHT = "#B8D4F0"
UI_TEXT_ACCENT = "#00E5FF"
UI_NAV_TEXT = "#E8F4FF"
UI_PHOTO_BG = "#060D16"
BRAND_PHOTO_BORDER = DODGEVILLE_GOLD

CORNER_RADIUS = 8
CARD_PAD = 16
CONTENT_PAD = 24
SUBNAV_HEIGHT = 40
TOPBAR_HEIGHT = 72
BTN_HEIGHT_PRIMARY = 42
BTN_HEIGHT_TOOLBAR = 36
BTN_HEIGHT_COMPACT = 32
BTN_RADIUS = 6
ACCENT_STRIPE_HEIGHT = 2
TACTICAL_STRIPE_GOLD_HEIGHT = 1


def tactical_stripe(parent, *, side="top", pack_kwargs=None) -> None:
    """Dual cyan + gold accent bar — law-enforcement command UI motif."""
    pack_kwargs = pack_kwargs or {}
    pack_kwargs.setdefault("fill", "x")
    if side == "bottom":
        order = ("gold", "glow")
    else:
        order = ("glow", "gold")
    for kind in order:
        color = UI_ACCENT_GLOW if kind == "glow" else DODGEVILLE_GOLD
        height = ACCENT_STRIPE_HEIGHT if kind == "glow" else TACTICAL_STRIPE_GOLD_HEIGHT
        ctk.CTkFrame(parent, fg_color=color, height=height, corner_radius=0).pack(
            side=side,
            **pack_kwargs,
        )


def hub_for_page(page_key: str) -> str | None:
    for hub_key, hub in NAV_HUBS.items():
        if page_key in hub["pages"]:
            return hub_key
    return None


def page_title(page_key: str) -> str:
    hub = hub_for_page(page_key)
    if hub:
        return NAV_HUBS[hub]["label"]
    for key, label, _ in NAV_ITEMS:
        if key == page_key:
            return label
    return page_key.replace("_", " ").title()


def resolve_nav_target(key: str) -> str:
    """Map sidebar hub key to default child page."""
    if key in NAV_HUBS:
        return NAV_HUBS[key]["default"]
    return key
