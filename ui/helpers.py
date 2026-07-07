"""Shared UI helpers — result handling, export dialogs, roster refresh."""

from __future__ import annotations

import re
from datetime import date
from tkinter import filedialog, messagebox
from typing import Any, Callable, Dict, Optional, Tuple

import customtkinter as ctk

from config import DATE_INPUT_HINT
from logic import (
    get_officers_by_seniority,
)
from validators import format_date


def today_placeholder() -> str:
    return format_date(date.today())


def logic_success(result: Any) -> bool:
    if result is None:
        return False
    if hasattr(result, "success"):
        return bool(result.success)
    if isinstance(result, dict):
        return bool(result.get("success"))
    return False


def logic_message(result: Any, default: str = "Unknown error") -> str:
    if result is None:
        return default
    if hasattr(result, "message"):
        return result.message or default
    if isinstance(result, dict):
        return result.get("message", default)
    return default


def handle_logic_result(
    result: Any,
    *,
    success_title: str = "Success",
    success_detail: Optional[str] = None,
    error_title: str = "Error",
    on_success: Optional[Callable[[], None]] = None,
    set_status: Optional[Callable[[str], None]] = None,
) -> bool:
    if logic_success(result):
        if success_detail:
            messagebox.showinfo(success_title, success_detail)
        if set_status and success_detail:
            set_status(success_detail)
        if on_success:
            on_success()
        return True
    messagebox.showerror(error_title, logic_message(result))
    return False


def handle_export_result(
    result: Dict,
    *,
    label: str,
    set_status: Optional[Callable[[str], None]] = None,
) -> bool:
    if result.get("success"):
        detail = f"{label} exported ({result.get('count', '?')} rows)\n{result.get('path', '')}"
        messagebox.showinfo("Export", detail)
        if set_status:
            set_status(f"{label} exported")
        return True
    messagebox.showerror("Export Failed", result.get("message", "Unknown error"))
    return False


def ask_save_csv(default_name: str = "export") -> Optional[str]:
    return filedialog.asksaveasfilename(
        defaultextension=".csv",
        initialfile=f"{default_name}_{format_date(date.today())}.csv",
        filetypes=[("CSV", "*.csv")],
    )


def ask_open_csv() -> Optional[str]:
    return filedialog.askopenfilename(
        title="Select CSV file",
        filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
    )


def export_date_status_filters(
    parent: ctk.CTkToplevel,
    *,
    title: str,
    status_values: Tuple[str, ...],
    on_apply: Callable[[Optional[str], Optional[str], str], None],
) -> None:
    """Reusable date range + status filter dialog for CSV exports."""
    parent.title(title)
    parent.geometry("360x220")
    form = ctk.CTkFrame(parent, fg_color="transparent")
    form.pack(fill="both", expand=True, padx=16, pady=16)
    ctk.CTkLabel(form, text=f"From ({DATE_INPUT_HINT})").pack(anchor="w")
    date_from = ctk.CTkEntry(form, height=32, placeholder_text="optional")
    date_from.pack(fill="x", pady=(0, 8))
    ctk.CTkLabel(form, text=f"To ({DATE_INPUT_HINT})").pack(anchor="w")
    date_to = ctk.CTkEntry(form, height=32, placeholder_text="optional")
    date_to.pack(fill="x", pady=(0, 8))
    ctk.CTkLabel(form, text="Status").pack(anchor="w")
    status = ctk.CTkComboBox(form, values=list(status_values), height=32)
    status.pack(fill="x", pady=(0, 12))
    status.set(status_values[0])

    def apply():
        on_apply(
            date_from.get().strip() or None,
            date_to.get().strip() or None,
            status.get(),
        )
        parent.destroy()

    ctk.CTkButton(form, text="Export", command=apply).pack(fill="x")


def refresh_all_officer_dropdowns(app) -> None:
    """Refresh every roster-backed dropdown after CRUD or import."""
    callbacks = (
        "_refresh_officer_dropdown",
        "_refresh_payroll_officer_dropdown",
        "_refresh_swap_officer_dropdowns",
        "_refresh_notification_officer_filter",
        "_refresh_gantt_export_officers",
    )
    for name in callbacks:
        fn = getattr(app, name, None)
        if callable(fn):
            fn()
    if hasattr(app, "_refresh_dashboard_data"):
        app._refresh_dashboard_data()


def refresh_after_staffing_change(app) -> None:
    """Re-read shift/staffing settings and refresh dependent views."""
    refresh_shift = getattr(app, "_refresh_officer_shift_options", None)
    if callable(refresh_shift):
        refresh_shift()
    refresh_after_rotation_change(app)


def refresh_after_schedule_change(app) -> None:
    """Refresh live schedule, timeline, dashboard, and timecard after schedule changes."""
    refresh_gantt = getattr(app, "refresh_gantt", None)
    if callable(refresh_gantt):
        refresh_gantt()
    refresh_monthly = getattr(app, "refresh_monthly", None)
    if callable(refresh_monthly):
        try:
            refresh_monthly("updated")
        except Exception:
            pass
    if getattr(app, "current_page", None) == "timecard":
        refresh_timecard = getattr(app, "refresh_timecard", None)
        if callable(refresh_timecard):
            try:
                refresh_timecard()
            except Exception:
                pass
    if hasattr(app, "_refresh_dashboard_data"):
        app._refresh_dashboard_data()
    if getattr(app, "current_page", None) == "dashboard" and hasattr(app, "_refresh_dashboard"):
        app._refresh_dashboard()


def refresh_after_rotation_change(app) -> None:
    """Re-read rotation from DB and refresh every view that depends on cycle/squad duty."""
    if hasattr(app, "_update_sidebar_date"):
        app._update_sidebar_date()
    refresh_after_schedule_change(app)
    refresh_monthly = getattr(app, "refresh_monthly", None)
    if callable(refresh_monthly):
        try:
            refresh_monthly("base")
        except Exception:
            pass
    refresh_reports = getattr(app, "refresh_reports", None)
    if callable(refresh_reports):
        refresh_reports()


def active_officers():
    return [o for o in get_officers_by_seniority() if o.get("active") == 1]


def officer_label(officer: Dict, *, style: str = "default") -> str:
    if style == "squad":
        return f"{officer['name']}  ·  Squad {officer['squad']}  ·  {officer['shift_start']}"
    if style == "shift":
        return f"{officer['name']}  ·  {officer['shift_start']}–{officer['shift_end']}"
    return officer["name"]


def title_case_ui(text: str) -> str:
    """Capitalize the first letter of each word for headers, tabs, and labels."""
    if not text or not str(text).strip():
        return text

    def _cap_word(word: str) -> str:
        if not word:
            return word
        if word in ("—", "·", "/", "·"):
            return word
        parts = re.split(r"([-'])", word)
        out = []
        for part in parts:
            if part in ("-", "'"):
                out.append(part)
            elif part:
                out.append(part[:1].upper() + part[1:])
        return "".join(out)

    segments = text.split(" — ")
    return " — ".join(" ".join(_cap_word(w) for w in seg.split()) for seg in segments)
