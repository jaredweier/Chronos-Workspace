"""Modern CustomTkinter UI for Dodgeville PD Scheduler."""

import sys
from datetime import date
from typing import Optional

import customtkinter as ctk

from ui.admin_pages import AdminPageMixin
from ui.banked_time_pages import BankedTimePageMixin
from ui.dashboard_pages import DashboardPageMixin
from ui.feature_pages import AvailabilityPageMixin, ReportsPageMixin
from ui.notifications_pages import NotificationsPageMixin
from ui.officers_pages import OfficersPageMixin
from ui.payroll_pages import PayrollPageMixin
from ui.requests_pages import RequestsPageMixin
from ui.schedule_pages import SchedulePageMixin
from ui.session_pages import SessionPageMixin
from ui.shell_pages import ShellPageMixin
from ui.simulator_pages import SimulatorPageMixin
from ui.theme import UI_BG

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")
ctk.set_widget_scaling(1.15)
ctk.set_window_scaling(1.0)


class DodgevilleSchedulerApp(
    ShellPageMixin,
    SessionPageMixin,
    AdminPageMixin,
    ReportsPageMixin,
    AvailabilityPageMixin,
    RequestsPageMixin,
    SchedulePageMixin,
    PayrollPageMixin,
    BankedTimePageMixin,
    SimulatorPageMixin,
    NotificationsPageMixin,
    OfficersPageMixin,
    DashboardPageMixin,
):
    def __init__(self):
        self.root = ctk.CTk()
        self.root.title("Dodgeville Police Department Scheduler")
        self.root.minsize(1100, 700)
        self.root.configure(fg_color=UI_BG)

        self.current_user = None
        self.selected_officer_id = None
        self.current_page = None
        self._schedule_mode = "base"
        self.nav_buttons = {}
        self.stat_cards = {}
        self.pages = {}
        self._photo_image = None
        self._pay_preview_calc = None
        self._gantt_spec = None
        self._gantt_cells = {}
        self._schedule_pages = {}
        self._monthly_spec = None
        self._monthly_cells = {}
        self._officer_row_widgets = {}
        self._request_row_widgets = {}
        self._payroll_row_widgets = {}
        self._payroll_period_start: Optional[date] = None
        self._timecard_period_start: Optional[date] = None
        self._timecard_scope: str = "pay_period"
        self._timecard_scope_reference: Optional[date] = None
        self._swap_row_widgets = {}
        self._request_view = "queue"
        self._monthly_selected_day = None
        self._monthly_roster_frame = None
        self._notification_row_widgets = {}
        self._highlight_request_id = None
        self._highlight_swap_id = None
        self._highlight_availability_id = None
        self._highlight_open_shift_id = None
        self._availability_row_widgets = {}
        self._open_shift_row_widgets = {}
        self._gantt_cycle_start: Optional[date] = None
        self._last_simulation_result = None
        self._brand_images = []

        self._bootstrap_session()


def run():
    from config import configure_logging
    from scripts.startup_gates import gui_gate_warning_if_failed

    configure_logging()
    try:
        app = DodgevilleSchedulerApp()
        app.root.after(400, lambda: gui_gate_warning_if_failed(app.root))
        app.root.mainloop()
    except Exception:
        import traceback

        tb = traceback.format_exc()
        try:
            configure_logging()
            import logging

            logging.getLogger("dodgeville").critical("Startup failed:\n%s", tb)
        except Exception:
            pass
        try:
            import tkinter as tk
            from tkinter import messagebox

            err_root = tk.Tk()
            err_root.withdraw()
            messagebox.showerror(
                "Dodgeville Scheduler — Startup Failed",
                tb[-3500:] if len(tb) > 3500 else tb,
            )
            err_root.destroy()
        except Exception:
            print(tb, file=sys.stderr)
        raise
