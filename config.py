"""
Dodgeville Police Department Scheduler
Centralized configuration, constants, and logging.
"""

import logging
import os
from datetime import date
from typing import Dict, Tuple

# ==================== ROTATION ====================
ROTATION_BASE_DATE: date = date(2026, 6, 28)
ROTATION_CYCLE_LENGTH: int = 14

# ==================== PAY PERIOD ====================
# Biweekly pay periods (independent of the 14-day rotation cycle).
# Anchor period: 22-06-2026 through 05-07-2026 (14 days, inclusive).
# Shift hours count in the period where the shift *starts*, even if it ends
# on the next calendar day (e.g. 19:00 on 05-07 through 06:00 on 06-07).
PAY_PERIOD_BASE_DATE: date = date(2026, 7, 6)
PAY_PERIOD_LENGTH: int = 14

# ==================== SHIFTS ====================
SHIFT_TIMES: Dict[int, Tuple[str, str]] = {
    1: ("06:00", "17:00"),
    2: ("10:00", "21:00"),
    3: ("15:00", "02:00"),
    4: ("19:00", "06:00"),
}

# Officer roster assignment (UI + optional DB NULL = unassigned)
OFFICER_UNASSIGNED_LABEL = "Unassigned"
OFFICER_SQUAD_OPTIONS = [OFFICER_UNASSIGNED_LABEL, "A", "B"]
OFFICER_SHIFT_OPTIONS = [OFFICER_UNASSIGNED_LABEL] + [f"{start} - {end}" for start, end in SHIFT_TIMES.values()]

# Department roster titles (job_title column)
OFFICER_TITLE_OPTIONS = (
    "Officer",
    "Sergeant",
    "Investigator",
    "Lieutenant",
    "Chief",
)
OFFICER_TITLE_ALIASES = {
    "patrol officer": "Officer",
    "police officer": "Officer",
    "chief of police": "Chief",
    "adminstrative assistant": "Administrative Assistant",
    "admin assistant": "Administrative Assistant",
}

# Position compensation defaults (payroll section; stored in department_settings JSON)
POSITION_PAY_SETTINGS_KEY = "position_pay_rates"
POSITION_PAY_BASIS_OPTIONS = ("hourly", "monthly", "yearly")
POSITION_PAY_BASIS_LABELS = {
    "hourly": "Hourly",
    "monthly": "Monthly",
    "yearly": "Yearly",
}
# Exempt/command titles default to annual salary on Position Pay Rates (still editable).
DEFAULT_ANNUAL_HOURS = 2008.0
YEARLY_SALARY_TITLES = frozenset({"Chief", "Lieutenant"})
SALARY_ANNUAL_HOURS = 2080.0
DEFAULT_POSITION_PAY_RATES = {
    "Officer": {"amount": 5355.0, "pay_basis": "monthly", "is_salary": False, "annual_hours": DEFAULT_ANNUAL_HOURS},
    "Sergeant": {"amount": 6280.0, "pay_basis": "monthly", "is_salary": False, "annual_hours": DEFAULT_ANNUAL_HOURS},
    "Investigator": {
        "amount": 5689.0,
        "pay_basis": "monthly",
        "is_salary": False,
        "annual_hours": DEFAULT_ANNUAL_HOURS,
    },
    "Lieutenant": {"amount": 80400.0, "pay_basis": "yearly", "is_salary": True, "annual_hours": SALARY_ANNUAL_HOURS},
    "Chief": {"amount": 93600.0, "pay_basis": "yearly", "is_salary": True, "annual_hours": SALARY_ANNUAL_HOURS},
}

# ==================== BUMPING RULES ====================
BUMP_RULES: Dict[int, Tuple[int, ...]] = {
    1: (2,),
    2: (1, 3),
    3: (2, 4),
    4: (3,),
}

NIGHT_MINIMUM_OFFICERS: int = 2
MIN_REST_HOURS_BETWEEN_SHIFTS: float = 8.0
BUMP_ASSIGNMENTS_BEFORE_BUSY: int = 2


def is_high_risk_night(target_date) -> bool:
    return target_date.weekday() in [4, 5]


# ==================== COLORS ====================
# Tactical command-center palette — deep navy void, electric cyan HUD, badge gold
DODGEVILLE_BLUE = "#081018"
DODGEVILLE_ACCENT = "#00B4D8"
DODGEVILLE_RED = "#E53935"
DODGEVILLE_GOLD = "#D4AF37"
DODGEVILLE_SUCCESS = "#00C853"
DODGEVILLE_DANGER = DODGEVILLE_RED
DODGEVILLE_WARNING = "#FFAB00"
DODGEVILLE_ORANGE = "#FF8F00"

GANTT_COLORS = {
    "working": "#00C853",
    "off": "#3D4F66",
    "bumped": "#FF8F00",
    "covering": "#D4AF37",
    "swapped": "#7C4DFF",
    "training": "#00BFA5",
    "court": "#AB47BC",
    "leave": "#546E7A",
    "night_window": "#00B4D8",
    "unknown": "#607D8B",
}

# UI theme extensions
UI_BG = "#050A12"
UI_SURFACE = "#0C1624"
UI_SURFACE_LIGHT = "#132238"
UI_BORDER = "#1E3A5F"
UI_TEXT_MUTED = "#7A9CC6"
UI_SIDEBAR = "#060D16"
UI_ACCENT_GLOW = "#00E5FF"

# ==================== DATE FORMATS ====================
# User-facing input/display (DD-MM-YYYY); SQLite storage remains ISO (YYYY-MM-DD).
DATE_DISPLAY_FORMAT = "%d-%m-%Y"
DATETIME_DISPLAY_FORMAT = "%d-%m-%Y %H:%M"
DATE_INPUT_HINT = "DD-MM-YYYY"
DATE_STORAGE_FORMAT = "%Y-%m-%d"

# ==================== DEPARTMENT BRANDING ====================
DEFAULT_DEPARTMENT_NAME = "Dodgeville Police Department"
DEFAULT_DEPARTMENT_MISSION = "To protect and serve, in partnership with our community, through integrity and compassion"
DEFAULT_DEPARTMENT_TAGLINE = "Wisconsin's Oldest Courthouse · Est. 1859"

# ==================== DEV AUTO-LOGIN ====================
# Production default: login required. For local UI testing set SCHEDULER_AUTO_LOGIN=1.
AUTO_LOGIN_ENABLED = os.environ.get("SCHEDULER_AUTO_LOGIN", "0").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)
AUTO_LOGIN_USERNAME = os.environ.get("SCHEDULER_AUTO_LOGIN_USER", "admin").strip() or "admin"
AUTO_LOGIN_SKIP_PASSWORD_CHANGE = True

# ==================== DAY-OFF REQUESTS ====================
DAY_OFF_REQUEST_TYPES = (
    "Vacation",
    "Sick",
    "Personal",
    "Comp Time",
    "Bereavement",
    "Training",
    "Court",
)

REQUEST_TYPE_SCHEDULE_STATUS = {
    "Training": "training",
    "Court": "court",
    "Vacation": "leave",
    "Sick": "leave",
    "Personal": "leave",
    "Comp Time": "leave",
    "Bereavement": "leave",
}

# ==================== REQUEST STATUS ====================
REQUEST_STATUS = {
    "pending": "Pending",
    "approved": "Approved",
    "rejected": "Rejected",
    "pending_manual": "Pending Manual Review",
}

TIMECARD_REGULAR_TYPE = "Regular Hours"

PAYROLL_ENTRY_TYPES = [
    "Overtime Earned",
    "Callback",
    "Comp Earned",
    "Comp Taken",
    "Holiday Pay",
    "Holiday Overtime",
    "Holiday Comp Earned",
    "Holiday Overtime Comp Earned",
    "Sick Time Used",
    "Bereavement",
    "Training",
    "Unpaid",
    "Float Holiday Taken",
    "Holiday Taken",
]

TIMECARD_ENTRY_TYPES = [TIMECARD_REGULAR_TYPE] + PAYROLL_ENTRY_TYPES

# Pay code formulas (payroll/timecard; stored in department_settings JSON)
PAY_CODE_SETTINGS_KEY = "pay_code_rules"


def _pay_code_rule(
    rate_multiplier: float = 1.0,
    *,
    paid: bool = True,
    comp_bank_credit_ratio: float = 0.0,
    debit_comp_bank: bool = False,
    debit_sick_bank: bool = False,
    debit_float_holiday_bank: bool = False,
    debit_holiday_bank: bool = False,
    uses_callback_minimum: bool = False,
    premium_multiplier: float = 0.0,
    counts_as_overtime: bool = False,
) -> dict:
    return {
        "rate_multiplier": rate_multiplier,
        "paid": paid,
        "comp_bank_credit_ratio": comp_bank_credit_ratio,
        "debit_comp_bank": debit_comp_bank,
        "debit_sick_bank": debit_sick_bank,
        "debit_float_holiday_bank": debit_float_holiday_bank,
        "debit_holiday_bank": debit_holiday_bank,
        "uses_callback_minimum": uses_callback_minimum,
        "premium_multiplier": premium_multiplier,
        "counts_as_overtime": counts_as_overtime,
    }


DEFAULT_PAY_CODE_RULES = {
    "global": {
        "callback_minimum_hours": 2.0,
        "default_overtime_multiplier": 1.5,
    },
    "codes": {
        TIMECARD_REGULAR_TYPE: _pay_code_rule(1.0),
        "Overtime Earned": _pay_code_rule(1.5, counts_as_overtime=True),
        "Callback": _pay_code_rule(1.0, uses_callback_minimum=True),
        "Comp Earned": _pay_code_rule(1.0, comp_bank_credit_ratio=0.5),
        "Comp Taken": _pay_code_rule(1.0, debit_comp_bank=True),
        "Holiday Pay": _pay_code_rule(2.5, counts_as_overtime=True),
        "Holiday Overtime": _pay_code_rule(2.5, premium_multiplier=3.0, counts_as_overtime=True),
        "Holiday Comp Earned": _pay_code_rule(1.0, comp_bank_credit_ratio=1.5),
        "Holiday Overtime Comp Earned": _pay_code_rule(1.0, comp_bank_credit_ratio=2.0),
        "Sick Time Used": _pay_code_rule(1.0, debit_sick_bank=True),
        "Bereavement": _pay_code_rule(1.0),
        "Training": _pay_code_rule(1.0),
        "Unpaid": _pay_code_rule(0.0, paid=False),
        "Float Holiday Taken": _pay_code_rule(1.0, debit_float_holiday_bank=True),
        "Holiday Taken": _pay_code_rule(1.0, debit_holiday_bank=True),
    },
}

TIMECARD_APPROVAL_STATUSES = ("Draft", "Submitted", "Approved", "Rejected")

# Approved day-off request type → default timecard pay type and hours (None = use scheduled shift length)
DAY_OFF_TIMECARD_DEFAULTS = {
    "Vacation": ("Unpaid", 0.0),
    "Sick": ("Sick Time Used", None),
    "Personal": ("Unpaid", 0.0),
    "Comp Time": ("Comp Taken", None),
    "Bereavement": ("Bereavement", None),
    "Training": ("Training", None),
    "Court": ("Regular Hours", 0.0),
}

SCHEDULE_SNAPSHOT_TYPES = ("base", "updated")

SNAPSHOT_STATUSES = (
    "working",
    "off",
    "bumped",
    "covering",
    "swapped",
    "leave",
    "training",
    "court",
)

SIMULATOR_ROTATION_TYPES = [
    "2-2-3 (Dodgeville 14-day)",
    "4-on-4-off",
    "Panama 12-hour",
    "Continental 7-day",
    "Equal split (custom cycle)",
]

DEFAULT_OVERTIME_MULTIPLIER = 1.5

# FLSA hours watch (weekly OT + pay-period cap warnings)
FLSA_WEEKLY_THRESHOLD = 40.0
FLSA_LE_WEEKLY_THRESHOLD = 43.0  # 7-day work period election for law enforcement (§207(k))
FLSA_HOURS_WARN_PCT = 0.9

# FLSA §207(k) — work period aligned to department rotation (DOL Fact Sheet #8)
# Default 28-day / 171h; scales with rotation_cycle_length via labor_compliance.
FLSA_207K_ENABLED = True
FLSA_207K_WORK_PERIOD_DAYS = 28
FLSA_207K_HOURS_THRESHOLD = 171.0
FLSA_207K_BASE_DATE: date = ROTATION_BASE_DATE
FLSA_207K_HOURS_PER_DAY = 171.0 / 28.0  # DOL scale factor for custom period lengths

# Public-sector compensatory time accrual cap (FLSA)
FLSA_COMP_TIME_MAX_HOURS = 480.0

# Scheduling fatigue policy — routes to manual review; supervisor may override
MAX_CONSECUTIVE_WORK_DAYS = 13

# Call-back / call-in minimum paid hours (common CBA practice)
CALLBACK_MINIMUM_HOURS = 2.0

ROTATION_PRESETS = {
    "2-2-3 (Dodgeville 14-day)": {
        "cycle_length": 14,
        "squads": 2,
        "squad_a_days": {1, 2, 5, 6, 7, 10, 11},
    },
    "4-on-4-off": {
        "cycle_length": 8,
        "squads": 2,
        "squad_patterns": {"A": [1, 1, 1, 1, 0, 0, 0, 0], "B": [0, 0, 0, 0, 1, 1, 1, 1]},
    },
    "Panama 12-hour": {
        "cycle_length": 14,
        "squads": 2,
        "squad_a_days": {1, 2, 3, 4, 5, 6, 7},
    },
    "Continental 7-day": {
        "cycle_length": 7,
        "squads": 1,
        "squad_patterns": {"A": [1, 1, 1, 0, 0, 1, 1]},
    },
    "Equal split (custom cycle)": {
        "cycle_length": 14,
        "squads": 2,
        "work_days_per_cycle": 7,
    },
}

# Time bank accrual (per SCHEDULING_RULES.txt)
SICK_MONTHLY_ACCRUAL_HOURS = 8.0
FLOAT_HOLIDAY_ANNUAL_HOURS = 24.0  # 3 x 8 hours
HOLIDAY_ANNUAL_HOURS = 80.0  # 10 x 8 hours

# ==================== LOGGING ====================
LOG_LEVEL = "INFO"
LOG_FILE = "dodgeville_scheduler.log"
_logging_configured = False


def configure_logging() -> logging.Logger:
    """Configure file/console logging once (call from app entry, not on import)."""
    global _logging_configured
    log = logging.getLogger("DodgevilleScheduler")
    if _logging_configured:
        return log
    if not os.path.exists("logs"):
        os.makedirs("logs")
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL),
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(f"logs/{LOG_FILE}"),
            logging.StreamHandler(),
        ],
    )
    _logging_configured = True
    return log


logger = logging.getLogger("DodgevilleScheduler")
