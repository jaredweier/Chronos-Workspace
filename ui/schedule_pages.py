"""Gantt timeline and monthly base/updated schedules."""

from calendar import monthrange
from datetime import date
from tkinter import filedialog, messagebox
from typing import Optional, Tuple

import customtkinter as ctk

from config import GANTT_COLORS, SNAPSHOT_STATUSES
from logic import (
    build_monthly_roster_by_date,
    build_schedule_matrix,
    compare_base_updated_schedule,
    create_manual_coverage_override,
    ensure_original_monthly_schedule,
    export_officer_schedule_ical,
    export_schedule_diff_csv,
    export_schedule_pdf,
    get_adjacent_cycle_window,
    get_current_cycle_window,
    get_cycle_day,
    get_holidays,
    get_monthly_summary_from_snapshot,
    get_officer_work_dates_from_summary,
    get_officers_by_seniority,
    get_schedule_snapshot,
    get_snapshot_day_roster,
    is_future_cycle_window,
    set_snapshot_assignment,
    sync_updated_schedule,
)
from ui.helpers import today_placeholder
from ui.theme import (
    CARD_PAD,
    CORNER_RADIUS,
    DODGEVILLE_ACCENT,
    DODGEVILLE_BLUE,
    DODGEVILLE_DANGER,
    DODGEVILLE_GOLD,
    DODGEVILLE_SUCCESS,
    DODGEVILLE_WARNING,
    UI_BG,
    UI_BORDER,
    UI_SURFACE,
    UI_SURFACE_LIGHT,
    UI_TEXT_MUTED,
    font,
)
from ui.widgets import Card, CompactButton, FormField, PrimaryButton, SectionHeader, ToolbarButton
from validators import format_date

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MONTHLY_CELL_WIDTH = 156
MONTHLY_CELL_HEIGHT = 148
MONTHLY_CELL_ROSTER_MAX = 6


class SchedulePageMixin:
    def _build_timeline(self):
        page = self.pages["timeline"]
        page.grid_rowconfigure(1, weight=1)
        page.grid_columnconfigure(0, weight=1)

        toolbar = ctk.CTkFrame(page, fg_color="transparent")
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        toolbar.grid_columnconfigure(0, weight=1)

        nav_row = ctk.CTkFrame(toolbar, fg_color="transparent")
        nav_row.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        self._gantt_cycle_label = ctk.CTkLabel(
            nav_row,
            text="Showing current 14 day cycle",
            font=font("body"),
            text_color=UI_TEXT_MUTED,
        )
        self._gantt_cycle_label.pack(side="left")
        gantt_nav = ctk.CTkFrame(nav_row, fg_color="transparent")
        gantt_nav.pack(side="left", padx=(12, 0))
        CompactButton(
            gantt_nav,
            text="◀",
            width=36,
            command=lambda: self._shift_gantt_cycle(-1),
        ).pack(side="left", padx=(0, 4))
        ToolbarButton(
            gantt_nav,
            text="Today",
            width=64,
            command=self._reset_gantt_cycle,
        ).pack(side="left", padx=(0, 4))
        self._gantt_cycle_next_btn = CompactButton(
            gantt_nav,
            text="▶",
            width=36,
            command=lambda: self._shift_gantt_cycle(1),
        )
        self._gantt_cycle_next_btn.pack(side="left")
        ToolbarButton(nav_row, text="Refresh", width=80, command=self.refresh_gantt).pack(side="right")

        export_row = ctk.CTkFrame(toolbar, fg_color="transparent")
        export_row.grid(row=1, column=0, sticky="ew")
        self._gantt_export_officer_map = {}
        if not self._is_officer_role():
            ctk.CTkLabel(
                export_row,
                text="Officer",
                font=font("small"),
                text_color=UI_TEXT_MUTED,
            ).pack(side="left", padx=(0, 6))
            self._gantt_export_officer = ctk.CTkComboBox(
                export_row,
                values=["Select officer..."],
                width=180,
                height=32,
            )
            self._gantt_export_officer.pack(side="left", padx=(0, 12))
            self._refresh_gantt_export_officers()
        export_label = "My PDF" if self._is_officer_role() else "Export PDF"
        ToolbarButton(
            export_row,
            text=export_label,
            fg_color=DODGEVILLE_BLUE,
            command=self._export_gantt_pdf,
        ).pack(side="right", padx=(6, 0))
        if self.can("schedule.export_own") or not self._is_officer_role():
            ical_label = "My Calendar" if self._is_officer_role() else "iCal"
            ToolbarButton(
                export_row,
                text=ical_label,
                fg_color=DODGEVILLE_GOLD,
                command=self._export_gantt_ical,
            ).pack(side="right", padx=(6, 0))

        self.gantt_scroll = ctk.CTkScrollableFrame(page, fg_color=UI_SURFACE, corner_radius=CORNER_RADIUS)
        self.gantt_scroll.grid(row=1, column=0, sticky="nsew")

        legend = ctk.CTkFrame(page, fg_color="transparent")
        legend.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        for status, color in GANTT_COLORS.items():
            if status == "night_window":
                continue
            ctk.CTkLabel(legend, text=f"● {status.title()}", text_color=color, font=font("small")).pack(
                side="left", padx=12
            )

    def _gantt_view_window(self) -> Tuple[date, date]:
        ref = self._gantt_cycle_start or date.today()
        return get_current_cycle_window(ref)

    def _shift_gantt_cycle(self, direction: int):
        start, _ = self._gantt_view_window()
        next_start, _ = get_adjacent_cycle_window(start, direction)
        if direction > 0 and is_future_cycle_window(next_start):
            return
        self._gantt_cycle_start = next_start
        self.refresh_gantt()

    def _reset_gantt_cycle(self):
        self._gantt_cycle_start = None
        self.refresh_gantt()

    def _export_gantt_pdf(self):
        start, end = self._gantt_view_window()
        officer_id = self._linked_officer_id() if self._is_officer_role() else None
        self._export_pdf_result(
            export_schedule_pdf(start, end, officer_id=officer_id),
            "Schedule PDF",
        )

    def _refresh_gantt_export_officers(self):
        if not hasattr(self, "_gantt_export_officer"):
            return
        officers = [o for o in get_officers_by_seniority() if o.get("active") == 1]
        labels = [o["name"] for o in officers]
        self._gantt_export_officer_map = {o["name"]: o["id"] for o in officers}
        self._gantt_export_officer.configure(values=labels or ["No officers"])
        if labels:
            self._gantt_export_officer.set(labels[0])

    def _gantt_export_officer_id(self) -> Optional[int]:
        if self._is_officer_role():
            return self._linked_officer_id()
        if hasattr(self, "_gantt_export_officer"):
            return self._gantt_export_officer_map.get(self._gantt_export_officer.get())
        return None

    def _export_gantt_ical(self):
        start, end = self._gantt_view_window()
        officer_id = self._gantt_export_officer_id()
        if not officer_id:
            messagebox.showwarning(
                "Export",
                "Select an officer to export, or link your login to an officer profile.",
            )
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".ics",
            filetypes=[("iCalendar", "*.ics")],
            initialfile=f"schedule_{format_date(start)}.ics",
        )
        result = export_officer_schedule_ical(
            officer_id,
            start_date=start,
            end_date=end,
            output_path=path or None,
        )
        if result.get("success"):
            messagebox.showinfo("Export", f"Calendar saved to:\n{result['path']}")
            self.set_status("Schedule calendar exported")
        else:
            messagebox.showerror("Export Failed", result.get("message", "Unknown error"))

    def _update_gantt_cells(self, matrix, days, today):
        for row_idx, entry in enumerate(matrix, start=1):
            for col, day in enumerate(days, start=1):
                status = entry["days"][day]
                color = GANTT_COLORS.get(status, GANTT_COLORS["unknown"])
                self._gantt_cells[(row_idx, col)].configure(
                    fg_color=color,
                    border_width=2 if day == today else 0,
                )

    def refresh_gantt(self):
        self._refresh_gantt_export_officers()
        start, end = self._gantt_view_window()
        if hasattr(self, "_gantt_cycle_label"):
            viewing_current = self._gantt_cycle_start is None
            note = "" if viewing_current else "  ·  historical view"
            self._gantt_cycle_label.configure(
                text=f"Cycle window: {format_date(start)} – {format_date(end)}{note}",
            )
        if hasattr(self, "_gantt_cycle_next_btn"):
            next_start, _ = get_adjacent_cycle_window(start, 1)
            state = "disabled" if is_future_cycle_window(next_start) else "normal"
            self._gantt_cycle_next_btn.configure(state=state)
        matrix, days = build_schedule_matrix(start, end)
        if self._is_officer_role():
            oid = self._linked_officer_id()
            if oid:
                matrix = [e for e in matrix if e["officer"]["id"] == oid]
        today = date.today()
        officer_ids = tuple(entry["officer"]["id"] for entry in matrix)
        spec = (start, end, officer_ids, len(days))

        cells_stale = not self._gantt_cells
        if not cells_stale:
            for cell in self._gantt_cells.values():
                try:
                    if not cell.winfo_exists():
                        cells_stale = True
                        break
                except Exception:
                    cells_stale = True
                    break

        if spec != self._gantt_spec or cells_stale:
            for w in self.gantt_scroll.winfo_children():
                w.destroy()
            self._gantt_cells = {}
            self._gantt_spec = spec

            if not matrix:
                empty = ctk.CTkFrame(self.gantt_scroll, fg_color=UI_SURFACE, corner_radius=8)
                empty.pack(fill="x", padx=12, pady=24)
                if self._is_officer_role() and not self._linked_officer_id():
                    msg = "Your login is not linked to an officer profile. Ask a supervisor to link your account."
                    cta = None
                elif self._is_officer_role():
                    msg = "No schedule rows to display for your profile this cycle."
                    cta = ("Submit Time Off", lambda: self.show_page("requests"))
                else:
                    msg = "No active officers on the roster for this cycle window."
                    cta = ("Patrol Roster", lambda: self.show_page("officers"))
                ctk.CTkLabel(
                    empty,
                    text=msg,
                    font=font("body"),
                    text_color=UI_TEXT_MUTED,
                    wraplength=520,
                ).pack(padx=16, pady=(16, 8))
                if cta:
                    PrimaryButton(
                        empty,
                        text=cta[0],
                        fg_color=DODGEVILLE_ACCENT,
                        command=cta[1],
                    ).pack(padx=16, pady=(0, 16))
                return

            grid = ctk.CTkFrame(self.gantt_scroll, fg_color="transparent")
            grid.pack(padx=12, pady=12)

            ctk.CTkLabel(grid, text="Officer", width=180, font=font("subheading")).grid(row=0, column=0, padx=4, pady=4)
            for col, day in enumerate(days, start=1):
                is_today = day == today
                hdr_color = DODGEVILLE_ACCENT if is_today else UI_TEXT_MUTED
                ctk.CTkLabel(
                    grid,
                    text=f"{day.strftime('%a')}\n{format_date(day)}\nD{get_cycle_day(day)}",
                    width=56,
                    font=font("small"),
                    text_color=hdr_color,
                ).grid(row=0, column=col, padx=2, pady=4)

            for row_idx, entry in enumerate(matrix, start=1):
                officer = entry["officer"]
                shift_line = self._shift_time_label(officer)
                officer_label = officer["name"][:20]
                if shift_line:
                    officer_label += f"\n{shift_line}"
                ctk.CTkLabel(
                    grid,
                    text=officer_label,
                    width=180,
                    anchor="w",
                    font=font("body"),
                ).grid(row=row_idx, column=0, padx=4, pady=2, sticky="w")
                for col, day in enumerate(days, start=1):
                    status = entry["days"][day]
                    color = GANTT_COLORS.get(status, GANTT_COLORS["unknown"])
                    cell = ctk.CTkFrame(
                        grid,
                        width=52,
                        height=24,
                        fg_color=color,
                        corner_radius=6,
                        border_width=2 if day == today else 0,
                        border_color="#FFFFFF",
                    )
                    cell.grid(row=row_idx, column=col, padx=2, pady=2)
                    self._gantt_cells[(row_idx, col)] = cell
                    shift = self._shift_time_label(officer)
                    cell.bind(
                        "<Button-1>",
                        lambda e, n=officer["name"], d=day, s=status, sh=shift: self.set_status(
                            f"{n}  {sh}  ·  {format_date(d)}: {s}" if sh else f"{n}: {format_date(d)}: {s}"
                        ),
                    )
        else:
            self._update_gantt_cells(matrix, days, today)

    # ── Monthly Schedules (base + updated) ─────────────────────────────
    def _build_base_schedule(self):
        self._build_monthly_schedule_page("base_schedule", "base")

    def _build_live_schedule(self):
        self._build_monthly_schedule_page(
            "live_schedule",
            "updated",
            publish_label="Publish & Notify Staff",
        )

    def _build_monthly_schedule_page(self, page_key: str, schedule_type: str, publish_label: str = ""):
        page = self.pages[page_key]
        page.grid_rowconfigure(1, weight=1)
        page.grid_columnconfigure(0, weight=1)

        toolbar = ctk.CTkFrame(page, fg_color="transparent")
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        toolbar.grid_columnconfigure(0, weight=1)

        ctrl = ctk.CTkFrame(toolbar, fg_color="transparent")
        ctrl.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        today = date.today()
        month_year = ctk.CTkComboBox(
            ctrl,
            values=[f"{today.year}-{m:02d}" for m in range(1, 13)],
            height=32,
            width=130,
        )
        month_year.set(f"{today.year}-{today.month:02d}")
        month_year.pack(side="left")
        CompactButton(
            ctrl,
            text="Apply",
            width=72,
            command=lambda: self.refresh_monthly(schedule_type),
        ).pack(side="left", padx=(8, 12))
        status_label = ctk.CTkLabel(ctrl, text="", font=font("small"), text_color=UI_TEXT_MUTED)
        status_label.pack(side="left")

        pdf_label = "My PDF" if self._is_officer_role() else "Export PDF"
        ToolbarButton(
            ctrl,
            text=pdf_label,
            fg_color=DODGEVILLE_BLUE,
            command=lambda st=schedule_type: self._export_monthly_pdf(st),
        ).pack(side="right", padx=(6, 0))

        can_publish = schedule_type == "updated" and self.can("schedule.updated.sync")
        if can_publish and publish_label:
            PrimaryButton(
                ctrl,
                text=publish_label,
                command=lambda: self._schedule_action(schedule_type),
            ).pack(side="right", padx=(6, 0))

        if schedule_type == "updated":
            if self.can("schedule.updated.edit"):
                CompactButton(
                    ctrl,
                    text="Coverage",
                    width=78,
                    command=self._show_manual_coverage_dialog,
                ).pack(side="right", padx=(4, 0))
                CompactButton(
                    ctrl,
                    text="Edit",
                    width=56,
                    command=lambda: self._manual_schedule_edit(schedule_type),
                ).pack(side="right", padx=(4, 0))
            CompactButton(
                ctrl,
                text="Compare",
                width=72,
                fg_color=DODGEVILLE_GOLD,
                hover_color=DODGEVILLE_ACCENT,
                command=lambda: self._show_schedule_diff(),
            ).pack(side="right", padx=(4, 0))
            diff_csv_label = "My Diff" if self._is_officer_role() else "Diff CSV"
            CompactButton(
                ctrl,
                text=diff_csv_label,
                width=72,
                fg_color=DODGEVILLE_ACCENT,
                hover_color=DODGEVILLE_BLUE,
                command=self._export_updated_diff_csv_from_toolbar,
            ).pack(side="right", padx=(4, 0))

        scroll = ctk.CTkScrollableFrame(page, fg_color="transparent")
        scroll.grid(row=1, column=0, sticky="nsew")

        self._schedule_pages[schedule_type] = {
            "page_key": page_key,
            "schedule_type": schedule_type,
            "month_year": month_year,
            "scroll": scroll,
            "status_label": status_label,
            "spec": None,
            "cells": {},
            "selected_day": None,
            "selected_entry": None,
            "roster_list": None,
            "snapshot": None,
        }

    def _schedule_action(self, schedule_type: str):
        if not self.can("schedule.updated.sync"):
            messagebox.showwarning("Permission", "Only Supervisor or Administration can sync.")
            return
        year, month = self._parse_month_year(self._schedule_pages["updated"]["month_year"].get())
        result = sync_updated_schedule(year, month, self.current_user["id"])
        if result.get("success"):
            messagebox.showinfo("Schedule", result.get("message", "Done"))
            self.refresh_monthly(schedule_type)
        else:
            messagebox.showerror("Schedule", result.get("message", "Failed"))

    def _parse_month_year(self, value: str):
        year_str, month_str = value.split("-")
        return int(year_str), int(month_str)

    def _export_monthly_pdf(self, schedule_type: str):
        state = self._schedule_pages.get(schedule_type)
        if not state:
            return
        year, month = self._parse_month_year(state["month_year"].get())
        _, last_day = monthrange(year, month)
        start = date(year, month, 1)
        end = date(year, month, last_day)
        label = "Original Monthly" if schedule_type == "base" else "Current Monthly"
        officer_id = self._linked_officer_id() if self._is_officer_role() else None
        self._export_pdf_result(
            export_schedule_pdf(start, end, officer_id=officer_id),
            f"{label} schedule PDF",
        )

    def _show_manual_coverage_dialog(self):
        if not self.can("schedule.updated.edit"):
            messagebox.showwarning("Permission", "Only Supervisor or Administration can assign coverage.")
            return

        dialog = ctk.CTkToplevel(self.root)
        dialog.title("Assign Manual Coverage")
        dialog.geometry("440x400")
        dialog.configure(fg_color=UI_BG)
        dialog.transient(self.root)
        dialog.grab_set()

        card = ctk.CTkFrame(dialog, fg_color=UI_SURFACE, corner_radius=CORNER_RADIUS)
        card.pack(fill="both", expand=True, padx=20, pady=20)
        SectionHeader(
            card,
            "Coverage Override",
            "Assign a replacement without a time off request",
        ).pack(fill="x", padx=CARD_PAD, pady=(CARD_PAD, 8))

        form = ctk.CTkFrame(card, fg_color="transparent")
        form.pack(fill="x", padx=CARD_PAD)
        officers = [o for o in get_officers_by_seniority() if o.get("active") == 1]
        labels = [f"{o['name']}  ·  {o['shift_start']}" for o in officers]
        officer_map = {lbl: o["id"] for lbl, o in zip(labels, officers)}

        date_entry = FormField(
            form, "Date", lambda p: ctk.CTkEntry(p, height=36, placeholder_text=today_placeholder())
        ).widget
        original_combo = FormField(
            form,
            "Officer Being Covered",
            lambda p: ctk.CTkComboBox(p, height=36, values=labels or ["No officers"]),
        ).widget
        replacement_combo = FormField(
            form,
            "Covering Officer",
            lambda p: ctk.CTkComboBox(p, height=36, values=labels or ["No officers"]),
        ).widget
        reason_entry = FormField(
            form, "Reason (optional)", lambda p: ctk.CTkEntry(p, height=36, placeholder_text="Manual Coverage")
        ).widget
        if labels:
            original_combo.set(labels[0])
            replacement_combo.set(labels[1] if len(labels) > 1 else labels[0])

        err = ctk.CTkLabel(form, text="", font=font("small"), text_color=DODGEVILLE_DANGER)
        err.pack(fill="x", pady=(4, 0))

        def submit():
            orig_id = officer_map.get(original_combo.get())
            repl_id = officer_map.get(replacement_combo.get())
            if not orig_id or not repl_id:
                err.configure(text="Select both officers.")
                return
            result = create_manual_coverage_override(
                orig_id,
                repl_id,
                date_entry.get().strip(),
                reason_entry.get().strip() or "Manual Coverage",
                actor_user_id=self.current_user.get("id"),
            )
            if not result.get("success"):
                err.configure(text=result.get("message", "Failed"))
                return
            dialog.destroy()
            messagebox.showinfo("Coverage Assigned", result.get("message", "Override saved."))
            self.set_status("Manual coverage override saved")
            if self.current_page == "timeline":
                self.refresh_gantt()
            from ui.helpers import refresh_after_schedule_change

            refresh_after_schedule_change(self)
            self.refresh_notifications()
            self._update_notification_badge()

        ctk.CTkButton(
            card,
            text="Assign Coverage",
            height=40,
            fg_color=DODGEVILLE_SUCCESS,
            command=submit,
        ).pack(fill="x", padx=CARD_PAD, pady=(12, CARD_PAD))

        dialog.wait_window()

    def _manual_schedule_edit(self, schedule_type: str):
        if not self.can("schedule.updated.edit"):
            messagebox.showwarning("Permission", "Only Supervisor or Administration can edit.")
            return
        state = self._schedule_pages.get(schedule_type)
        if not state or not state.get("selected_entry"):
            messagebox.showwarning("Select Day", "Click a calendar day first.")
            return
        entry = state["selected_entry"]
        year, month = self._parse_month_year(state["month_year"].get())
        if not get_schedule_snapshot(year, month, schedule_type):
            if schedule_type == "updated":
                sync_updated_schedule(year, month, self.current_user["id"])
            else:
                messagebox.showwarning("Schedule", "Open Original Monthly Schedule for this month first.")
                return
        dialog = ctk.CTkToplevel(self.root)
        dialog.title("Manual Schedule Edit")
        dialog.geometry("420x360")
        dialog.transient(self.root)
        form = ctk.CTkFrame(dialog, fg_color="transparent")
        form.pack(fill="both", expand=True, padx=16, pady=16)
        officers = [o for o in get_officers_by_seniority() if o.get("active") == 1]
        off_labels = [o["name"] for o in officers]
        off_map = {o["name"]: o for o in officers}
        ctk.CTkLabel(form, text="Officer", font=font("small"), text_color=UI_TEXT_MUTED).pack(anchor="w")
        off_combo = ctk.CTkComboBox(form, values=off_labels, height=36)
        off_combo.pack(fill="x", pady=(0, 8))
        if off_labels:
            off_combo.set(off_labels[0])
        ctk.CTkLabel(form, text="Status", font=font("small"), text_color=UI_TEXT_MUTED).pack(anchor="w")
        status_combo = ctk.CTkComboBox(form, values=list(SNAPSHOT_STATUSES), height=36)
        status_combo.pack(fill="x", pady=(0, 8))
        status_combo.set("working")
        from logic.shift_assignment import get_shift_band_options

        shift_bands = get_shift_band_options()
        shift_labels = [f"{s} - {e}" for s, e in shift_bands]
        ctk.CTkLabel(form, text="Shift band (any officer)", font=font("small"), text_color=UI_TEXT_MUTED).pack(
            anchor="w"
        )
        shift_combo = ctk.CTkComboBox(form, values=shift_labels or ["—"], height=36)
        shift_combo.pack(fill="x", pady=(0, 8))
        if shift_labels:
            shift_combo.set(shift_labels[0])
        ctk.CTkLabel(form, text="Notes", font=font("small"), text_color=UI_TEXT_MUTED).pack(anchor="w")
        notes_entry = ctk.CTkEntry(form, height=36)
        notes_entry.pack(fill="x", pady=(0, 12))

        def save_manual():
            officer = off_map.get(off_combo.get())
            if not officer:
                return
            shift_start = None
            shift_end = None
            if shift_labels and status_combo.get() in ("working", "covering", "swapped", "training"):
                from validators import parse_officer_shift_ui

                shift_start, shift_end = parse_officer_shift_ui(shift_combo.get())
            result = set_snapshot_assignment(
                year,
                month,
                schedule_type,
                entry["date"].isoformat(),
                officer["id"],
                status_combo.get(),
                notes_entry.get().strip(),
                shift_start=shift_start,
                shift_end=shift_end,
            )
            if result.get("success"):
                from ui.helpers import refresh_after_schedule_change

                dialog.destroy()
                refresh_after_schedule_change(self)
                self.set_status("Manual assignment saved")
            else:
                messagebox.showerror("Error", result.get("message", "Save failed"))

        ctk.CTkButton(form, text="Save Assignment", fg_color=DODGEVILLE_SUCCESS, command=save_manual).pack(fill="x")

    def _schedule_diff_officer_id(self) -> Optional[int]:
        if self._is_officer_role():
            return self._linked_officer_id()
        return None

    def _show_schedule_diff(self):
        state = self._schedule_pages.get("updated")
        if not state:
            return
        year, month = self._parse_month_year(state["month_year"].get())
        officer_id = self._schedule_diff_officer_id()
        result = compare_base_updated_schedule(year, month, officer_id=officer_id)
        if not result.get("success"):
            messagebox.showwarning("Schedule Diff", result.get("message", "Cannot compare"))
            return

        diffs = result.get("diffs", [])
        dialog = ctk.CTkToplevel(self.root)
        dialog.title(f"Original vs Current Monthly, {date(year, month, 1).strftime('%B %Y')}")
        dialog.geometry("720x520")
        dialog.transient(self.root)

        header = ctk.CTkFrame(dialog, fg_color="transparent")
        header.pack(fill="x", padx=16, pady=(16, 8))
        title = f"{result['diff_count']} change(s) from original monthly schedule"
        if officer_id:
            title = f"{result['diff_count']} of your change(s) from original monthly schedule"
        ctk.CTkLabel(header, text=title, font=font("subheading")).pack(side="left")
        ctk.CTkButton(
            header,
            text="Export CSV",
            width=100,
            height=32,
            fg_color=DODGEVILLE_ACCENT,
            command=lambda: self._export_schedule_diff_csv(year, month, officer_id=officer_id),
        ).pack(side="right")

        scroll = ctk.CTkScrollableFrame(dialog, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        if not diffs:
            ctk.CTkLabel(
                scroll,
                text="No differences. Current monthly matches original.",
                text_color=UI_TEXT_MUTED,
                font=font("body"),
            ).pack(pady=20)
            return

        linked_id = self._linked_officer_id() if self._is_officer_role() else None
        for item in diffs:
            is_self = linked_id and item.get("officer_id") == linked_id
            row_kwargs = {
                "fg_color": UI_SURFACE,
                "corner_radius": 8,
                "border_width": 2 if is_self else 0,
            }
            if is_self:
                row_kwargs["border_color"] = DODGEVILLE_GOLD
            row = ctk.CTkFrame(scroll, **row_kwargs)
            row.pack(fill="x", pady=4)
            inner = ctk.CTkFrame(row, fg_color="transparent")
            inner.pack(fill="x", padx=12, pady=10)
            manual = "  · manual" if item.get("is_manual") else ""
            ctk.CTkLabel(
                inner,
                text=f"{item['assignment_date']}  ·  {item['officer_name']}{manual}",
                font=font("subheading"),
                anchor="w",
                text_color=DODGEVILLE_GOLD if is_self else None,
            ).pack(fill="x")
            change = f"{item['base_status'] or 'none'}  →  {item['updated_status'] or 'none'}"
            ctk.CTkLabel(
                inner,
                text=change,
                font=font("body"),
                anchor="w",
            ).pack(fill="x", pady=(4, 0))
            if item.get("base_notes") or item.get("updated_notes"):
                notes = f"Notes: {item.get('base_notes') or 'none'} → {item.get('updated_notes') or 'none'}"
                ctk.CTkLabel(
                    inner,
                    text=notes,
                    font=font("small"),
                    text_color=UI_TEXT_MUTED,
                    anchor="w",
                ).pack(fill="x", pady=(2, 0))

    def _export_updated_diff_csv_from_toolbar(self):
        state = self._schedule_pages.get("updated")
        if not state:
            return
        year, month = self._parse_month_year(state["month_year"].get())
        self._export_schedule_diff_csv(year, month)

    def _export_schedule_diff_csv(
        self,
        year: int,
        month: int,
        officer_id: Optional[int] = None,
    ):
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
        )
        oid = officer_id if officer_id is not None else self._schedule_diff_officer_id()
        result = export_schedule_diff_csv(year, month, path or None, officer_id=oid)
        if result.get("success"):
            messagebox.showinfo(
                "Export",
                f"Schedule diff exported ({result['count']} rows)\n{result['path']}",
            )
            self.set_status("Schedule diff CSV exported")
        else:
            messagebox.showerror("Export Failed", result.get("message", "Export failed"))

    def _shift_time_label(self, officer: dict) -> str:
        start = officer.get("shift_start") or ""
        end = officer.get("shift_end") or ""
        if start and end:
            return f"{start} – {end}"
        return ""

    def _compact_shift_time(self, officer: dict) -> str:
        start = officer.get("shift_start") or ""
        end = officer.get("shift_end") or ""
        if start and end:
            return f"{start}–{end}"
        return ""

    def _officer_last_name(self, name: str) -> str:
        parts = (name or "").strip().split()
        return parts[-1] if parts else "—"

    def _sort_day_roster(self, roster: list) -> list:
        return sorted(
            roster,
            key=lambda item: (
                item["officer"].get("shift_start") or "",
                item["officer"].get("name") or "",
            ),
        )

    def _monthly_cell_indicators(self, entry: dict, holidays_by_date: dict) -> str:
        parts = []
        if holidays_by_date.get(entry["date"].isoformat()):
            parts.append("★")
        if entry.get("high_risk_night"):
            parts.append("⚠")
        return " ".join(parts)

    def _format_monthly_cell_roster(
        self,
        roster: list,
        max_show: int = MONTHLY_CELL_ROSTER_MAX,
    ) -> str:
        linked_id = self._linked_officer_id() if self._is_officer_role() else None
        sorted_roster = self._sort_day_roster(roster)
        if not sorted_roster:
            return ""
        lines = []
        for item in sorted_roster[:max_show]:
            off = item["officer"]
            last = self._officer_last_name(off.get("name"))
            shift = self._compact_shift_time(off)
            line = f"{last}  {shift}" if shift else last
            if item.get("status") not in ("working",):
                line += f" ({item['status'][:4]})"
            if linked_id and off.get("id") == linked_id:
                line = f"▸ {line}"
            lines.append(line)
        remaining = len(sorted_roster) - max_show
        if remaining > 0:
            lines.append(f"+{remaining} more")
        return "\n".join(lines)

    def _monthly_day_header_colors(self, entry: dict, today: date) -> Tuple[str, str]:
        d = entry["date"]
        if d == today:
            return DODGEVILLE_ACCENT, "#FFFFFF"
        if d.weekday() >= 5:
            return UI_BORDER, UI_TEXT_MUTED
        return UI_SURFACE_LIGHT, "#FFFFFF"

    def _monthly_day_body_color(self, entry: dict, today: date) -> str:
        d = entry["date"]
        if d == today:
            return UI_SURFACE
        if d.weekday() >= 5:
            return UI_BORDER
        return UI_SURFACE

    def _bind_monthly_cell_click(self, widget, schedule_type: str, day_num: int, entry: dict):
        widget.bind(
            "<Button-1>",
            lambda e, dn=day_num, ent=entry, st=schedule_type: self._select_monthly_day(st, dn, ent),
        )
        for child in widget.winfo_children():
            self._bind_monthly_cell_click(child, schedule_type, day_num, entry)

    def _create_monthly_pad_cell(self, parent, row: int, col: int):
        pad = ctk.CTkFrame(
            parent,
            width=MONTHLY_CELL_WIDTH,
            height=MONTHLY_CELL_HEIGHT,
            fg_color=UI_BG,
            corner_radius=0,
        )
        pad.grid(row=row, column=col, padx=1, pady=1, sticky="nsew")
        pad.grid_propagate(False)

    def _create_monthly_legend(
        self,
        parent,
        schedule_type: str,
        officer_work_dates: set,
        diff_dates: set,
    ):
        legend = ctk.CTkFrame(parent, fg_color="transparent")
        legend.pack(fill="x", pady=(0, 10))
        chips = ["Today", "Selected"]
        if officer_work_dates:
            chips.append("Your shift")
        if schedule_type == "updated" and diff_dates:
            chips.append("Changed")
        chips.extend(["★ Holiday", "⚠ Night min"])
        for text in chips:
            ctk.CTkLabel(
                legend,
                text=text,
                font=font("small"),
                text_color=UI_TEXT_MUTED,
                fg_color=UI_BORDER,
                corner_radius=6,
                width=0,
                height=22,
            ).pack(side="left", padx=(0, 6))

    def _create_monthly_day_cell(
        self,
        parent,
        day_num: int,
        entry: dict,
        today: date,
        diff_dates: set,
        officer_work_dates: set,
        selected_day: Optional[int] = None,
    ) -> dict:
        border, border_color = self._monthly_cell_style(
            entry,
            today,
            diff_dates,
            officer_work_dates,
            selected_day,
            day_num,
        )
        header_bg, header_fg = self._monthly_day_header_colors(entry, today)
        body_bg = self._monthly_day_body_color(entry, today)
        cell = ctk.CTkFrame(
            parent,
            width=MONTHLY_CELL_WIDTH,
            height=MONTHLY_CELL_HEIGHT,
            fg_color=body_bg,
            corner_radius=0,
            border_width=border,
            border_color=border_color,
        )
        cell.grid_propagate(False)
        header = ctk.CTkFrame(cell, fg_color=header_bg, height=28, corner_radius=0)
        header.pack(fill="x")
        header.pack_propagate(False)
        indicators_label = ctk.CTkLabel(
            header,
            text="",
            font=font("small"),
            text_color=DODGEVILLE_GOLD,
            anchor="w",
        )
        indicators_label.pack(side="left", padx=(6, 0))
        day_label = ctk.CTkLabel(
            header,
            text=str(day_num),
            font=font("subheading"),
            text_color=header_fg,
            anchor="e",
        )
        day_label.pack(side="right", padx=(0, 8))
        roster_body = ctk.CTkFrame(cell, fg_color=body_bg, corner_radius=0)
        roster_body.pack(fill="both", expand=True, padx=6, pady=(4, 6))
        roster_label = ctk.CTkLabel(
            roster_body,
            text="",
            font=font("small"),
            anchor="nw",
            justify="left",
            wraplength=MONTHLY_CELL_WIDTH - 16,
            text_color="#FFFFFF",
        )
        roster_label.pack(fill="both", expand=True, anchor="nw")
        return {
            "frame": cell,
            "header": header,
            "day_label": day_label,
            "indicators_label": indicators_label,
            "roster_label": roster_label,
            "entry": entry,
        }

    def _populate_monthly_cell(
        self,
        widgets: dict,
        roster: list,
        entry: dict,
        holidays_by_date: dict,
        today: date,
    ):
        header_bg, header_fg = self._monthly_day_header_colors(entry, today)
        body_bg = self._monthly_day_body_color(entry, today)
        widgets["header"].configure(fg_color=header_bg)
        widgets["frame"].configure(fg_color=body_bg)
        widgets["day_label"].configure(text_color=header_fg)
        widgets["indicators_label"].configure(
            text=self._monthly_cell_indicators(entry, holidays_by_date),
        )
        roster_text = self._format_monthly_cell_roster(roster)
        widgets["roster_label"].configure(
            text=roster_text or " ",
            text_color=UI_TEXT_MUTED if not roster_text else "#FFFFFF",
        )
        widgets["entry"] = entry

    def _monthly_officer_work_dates(self, summary: list) -> set:
        if not self._is_officer_role():
            return set()
        oid = self._linked_officer_id()
        if not oid:
            return set()
        return get_officer_work_dates_from_summary(oid, summary)

    def _monthly_cell_style(
        self,
        entry: dict,
        today: date,
        diff_dates: set,
        officer_work_dates: set,
        selected_day: Optional[int],
        day_num: int,
    ) -> tuple[int, str]:
        d = entry["date"]
        if selected_day == day_num:
            return 2, DODGEVILLE_ACCENT
        if d == today:
            return 2, "#FFFFFF"
        if d.isoformat() in officer_work_dates:
            return 2, "#FFFFFF"
        if d.isoformat() in diff_dates:
            return 2, DODGEVILLE_GOLD
        return 0, "#FFFFFF"

    def _apply_monthly_selection(self, state):
        if not state.get("cells"):
            return
        today = date.today()
        diff_dates = state.get("diff_dates") or set()
        officer_work_dates = state.get("officer_work_dates") or set()
        selected_day = state.get("selected_day")
        holidays_by_date = state.get("holidays_by_date") or {}
        roster_by_date = state.get("roster_by_date") or {}
        for day_num, widgets in state["cells"].items():
            entry = widgets["entry"]
            border, border_color = self._monthly_cell_style(
                entry,
                today,
                diff_dates,
                officer_work_dates,
                selected_day,
                day_num,
            )
            widgets["frame"].configure(border_width=border, border_color=border_color)
            roster = roster_by_date.get(entry["date"], [])
            self._populate_monthly_cell(widgets, roster, entry, holidays_by_date, today)

    def _update_monthly_cells(self, state, summary, today, holidays_by_date):
        state["holidays_by_date"] = holidays_by_date
        self._apply_monthly_selection(state)

    def refresh_monthly(self, schedule_type: str = "base"):
        state = self._schedule_pages.get(schedule_type)
        if not state:
            return
        year, month = self._parse_month_year(state["month_year"].get())
        actor_id = self.current_user.get("id") if self.current_user else None
        ensure_original_monthly_schedule(year, month, user_id=actor_id)
        snapshot = get_schedule_snapshot(year, month, schedule_type)
        state["snapshot"] = snapshot
        if schedule_type == "base":
            if snapshot and snapshot.get("locked"):
                state["status_label"].configure(
                    text=(
                        f"Generated {format_date(snapshot['generated_at'][:10])}, locked  ·  "
                        "does not change after generation"
                    ),
                    text_color=DODGEVILLE_SUCCESS,
                )
            elif snapshot:
                state["status_label"].configure(text="Draft, not locked", text_color=DODGEVILLE_WARNING)
            else:
                state["status_label"].configure(
                    text="Generating original schedule from rotation…",
                    text_color=UI_TEXT_MUTED,
                )
        else:
            if snapshot:
                generated = snapshot.get("generated_at", "")[:16].replace("T", " ")
                state["status_label"].configure(
                    text=f"Live · auto-updates on approvals · last refresh {generated or '—'}",
                    text_color=DODGEVILLE_SUCCESS,
                )
            else:
                state["status_label"].configure(
                    text="Live schedule will populate when the first change is approved.",
                    text_color=DODGEVILLE_WARNING,
                )

        self._refresh_monthly_sync_cta(state, schedule_type, snapshot, year, month)
        if schedule_type == "updated":
            self._refresh_live_today_panel(state, snapshot, year, month)

        summary = get_monthly_summary_from_snapshot(snapshot, year, month, schedule_type)
        state["roster_by_date"] = build_monthly_roster_by_date(snapshot, year, month)
        holidays_by_date = {h["holiday_date"]: h["name"] for h in get_holidays(year)}
        today = date.today()
        diff_dates = set()
        if schedule_type == "updated":
            diff_officer_id = self._schedule_diff_officer_id()
            diff_result = compare_base_updated_schedule(
                year,
                month,
                officer_id=diff_officer_id,
            )
            if diff_result.get("success"):
                diff_dates = set(diff_result.get("dates_with_changes", []))
        state["diff_dates"] = diff_dates
        state["officer_work_dates"] = self._monthly_officer_work_dates(summary)
        officer_work_dates = state["officer_work_dates"]
        state["holidays_by_date"] = holidays_by_date
        spec = (schedule_type, year, month)

        if today.year == year and today.month == month:
            state["selected_day"] = today.day
            state["selected_entry"] = summary[today.day - 1]
        elif not state.get("selected_day") or state.get("spec") != spec:
            state["selected_day"] = 1
            state["selected_entry"] = summary[0]

        if spec != state["spec"]:
            for w in state["scroll"].winfo_children():
                w.destroy()
            state["cells"] = {}
            state["spec"] = spec

            subtitle = (
                "Rotation plan — fixed after generation"
                if schedule_type == "base"
                else "Live view — reflects approved time off, bumps, swaps, and coverage"
            )
            SectionHeader(
                state["scroll"],
                date(year, month, 1).strftime("%B %Y"),
                subtitle,
            ).pack(anchor="w", pady=(0, 6))
            self._create_monthly_legend(
                state["scroll"],
                schedule_type,
                officer_work_dates,
                diff_dates,
            )

            cal_shell = ctk.CTkFrame(state["scroll"], fg_color=UI_BORDER, corner_radius=8)
            cal_shell.pack(fill="x")
            grid = ctk.CTkFrame(cal_shell, fg_color=UI_BG, corner_radius=0)
            grid.pack(padx=1, pady=1, fill="x")
            for col in range(7):
                grid.grid_columnconfigure(col, weight=1, minsize=MONTHLY_CELL_WIDTH)
            for i, wd in enumerate(WEEKDAYS):
                hdr = ctk.CTkFrame(grid, fg_color=UI_SURFACE, height=28, corner_radius=0)
                hdr.grid(row=0, column=i, padx=1, pady=(1, 1), sticky="ew")
                hdr.grid_propagate(False)
                ctk.CTkLabel(
                    hdr,
                    text=wd,
                    font=font("small"),
                    text_color=UI_TEXT_MUTED,
                ).pack(expand=True)

            _, last_day = monthrange(year, month)
            first_weekday = date(year, month, 1).weekday()
            selected_day = state.get("selected_day")
            for pad_col in range(first_weekday):
                self._create_monthly_pad_cell(grid, 1, pad_col)
            for day_num in range(1, last_day + 1):
                entry = summary[day_num - 1]
                widgets = self._create_monthly_day_cell(
                    grid,
                    day_num,
                    entry,
                    today,
                    diff_dates,
                    officer_work_dates,
                    selected_day,
                )
                roster = state["roster_by_date"].get(entry["date"], [])
                self._populate_monthly_cell(widgets, roster, entry, holidays_by_date, today)
                pos = first_weekday + day_num - 1
                widgets["frame"].grid(
                    row=1 + pos // 7,
                    column=pos % 7,
                    padx=1,
                    pady=1,
                    sticky="nsew",
                )
                state["cells"][day_num] = widgets
                self._bind_monthly_cell_click(widgets["frame"], schedule_type, day_num, entry)
            total_slots = first_weekday + last_day
            trailing = (7 - (total_slots % 7)) % 7
            for pad_idx in range(trailing):
                self._create_monthly_pad_cell(grid, 1 + (total_slots + pad_idx - 1) // 7, (total_slots + pad_idx) % 7)

            roster_frame = Card(state["scroll"])
            roster_frame.pack(fill="x", pady=(12, 0))
            roster_title = "Day Detail" if schedule_type == "updated" else "Original Day Detail"
            SectionHeader(
                roster_frame.body,
                roster_title,
                "Select a day on the calendar — today is selected by default",
            ).pack(fill="x", padx=CARD_PAD, pady=(CARD_PAD, 8))
            state["roster_list"] = ctk.CTkScrollableFrame(
                roster_frame.body,
                fg_color="transparent",
                height=240,
            )
            state["roster_list"].pack(fill="x", padx=CARD_PAD, pady=(0, CARD_PAD))
            if state["selected_entry"]:
                self._refresh_monthly_roster(schedule_type, state["selected_entry"])
        else:
            self._update_monthly_cells(state, summary, today, holidays_by_date)
            if state.get("selected_entry"):
                self._refresh_monthly_roster(schedule_type, state["selected_entry"])

    def _refresh_live_today_panel(self, state, snapshot, year: int, month: int) -> None:
        today = date.today()
        existing = state.get("live_today_card")
        if existing is not None:
            try:
                if existing.winfo_exists():
                    existing.destroy()
            except Exception:
                pass
            state["live_today_card"] = None
        if today.year != year or today.month != month:
            return
        roster = get_snapshot_day_roster(snapshot, today) if snapshot else []
        card = Card(state["scroll"])
        header = f"Today · {today.strftime('%A, %B %d')}"
        if not roster:
            SectionHeader(
                card.body,
                header,
                "No officers scheduled on duty in the live schedule for today.",
            ).pack(fill="x", padx=CARD_PAD, pady=CARD_PAD)
        else:
            SectionHeader(
                card.body,
                header,
                f"{len(roster)} on duty — includes bumps, coverage, and swaps",
            ).pack(fill="x", padx=CARD_PAD, pady=(CARD_PAD, 4))
            list_frame = ctk.CTkFrame(card.body, fg_color="transparent")
            list_frame.pack(fill="x", padx=CARD_PAD, pady=(0, CARD_PAD))
            for item in sorted(roster, key=lambda r: r["officer"].get("name", "")):
                off = item["officer"]
                status = item.get("status", "working")
                color = GANTT_COLORS.get(status, DODGEVILLE_ACCENT)
                shift = self._shift_time_label(off) or "—"
                ctk.CTkLabel(
                    list_frame,
                    text=f"{off.get('name', 'Officer')}  ·  {shift}  ·  {status}",
                    font=font("small"),
                    text_color=color,
                    anchor="w",
                ).pack(fill="x", pady=1)
        children = list(state["scroll"].winfo_children())
        if children:
            card.pack(fill="x", pady=(0, 12), before=children[0])
        else:
            card.pack(fill="x", pady=(0, 12))
        state["live_today_card"] = card

    def _refresh_monthly_sync_cta(self, state, schedule_type: str, snapshot, year: int, month: int):
        existing = state.get("sync_cta")
        if existing is not None:
            try:
                if existing.winfo_exists():
                    existing.destroy()
            except Exception:
                pass
            state["sync_cta"] = None
        if schedule_type != "updated" or snapshot:
            return
        card = Card(state["scroll"])
        SectionHeader(
            card.body,
            "Live Schedule Starting Soon",
            "Approve a time-off request, bump, or swap and this month will update automatically.",
        ).pack(fill="x", padx=CARD_PAD, pady=(CARD_PAD, 8))
        action_row = ctk.CTkFrame(card.body, fg_color="transparent")
        action_row.pack(fill="x", padx=CARD_PAD, pady=(0, CARD_PAD))
        if self.can("schedule.updated.sync"):
            PrimaryButton(
                action_row,
                text="Build Live Schedule Now",
                command=lambda: self._schedule_action("updated"),
            ).pack(side="left")
        else:
            ctk.CTkLabel(
                action_row,
                text="Live schedule builds automatically when supervisors approve leave or coverage.",
                font=font("body"),
                text_color=UI_TEXT_MUTED,
            ).pack(side="left")
        try:
            children = [c for c in state["scroll"].winfo_children() if c is not card]
            if children:
                card.pack(fill="x", pady=(0, 12), before=children[0])
            else:
                card.pack(fill="x", pady=(0, 12))
        except Exception:
            card.pack(fill="x", pady=(0, 12))
        state["sync_cta"] = card

    def _select_monthly_day(self, schedule_type: str, day_num: int, entry: dict):
        state = self._schedule_pages[schedule_type]
        state["selected_day"] = day_num
        state["selected_entry"] = entry
        self._apply_monthly_selection(state)
        self._refresh_monthly_roster(schedule_type, entry)

    def _refresh_monthly_roster(self, schedule_type: str, entry: dict):
        state = self._schedule_pages.get(schedule_type)
        if not state or not state.get("roster_list"):
            return
        roster_list = state["roster_list"]
        for w in roster_list.winfo_children():
            w.destroy()
        target = entry["date"]
        roster_by_date = state.get("roster_by_date")
        if roster_by_date is not None:
            roster = roster_by_date.get(target, [])
        else:
            roster = get_snapshot_day_roster(state.get("snapshot"), target)
        squad = entry.get("squad_on_duty", "")
        squad_color = DODGEVILLE_ACCENT if squad == "A" else DODGEVILLE_BLUE
        holiday_name = (state.get("holidays_by_date") or {}).get(target.isoformat())
        day_hdr = ctk.CTkFrame(roster_list, fg_color="transparent")
        day_hdr.pack(fill="x", pady=(0, 8))
        title_parts = [f"{target.strftime('%A')}, {format_date(target)}"]
        if holiday_name:
            title_parts.append(f"★ {holiday_name}")
        ctk.CTkLabel(
            day_hdr,
            text="  ·  ".join(title_parts),
            font=font("subheading"),
            anchor="w",
            text_color=DODGEVILLE_GOLD if holiday_name else None,
        ).pack(side="left", fill="x", expand=True)
        meta = ctk.CTkFrame(day_hdr, fg_color="transparent")
        meta.pack(side="right")
        if squad:
            ctk.CTkLabel(
                meta,
                text=f"Squad {squad}",
                font=font("small"),
                fg_color=squad_color,
                corner_radius=4,
                width=52,
                height=20,
            ).pack(side="right", padx=(4, 0))
        duty_count = entry.get("working_officers", len(roster))
        ctk.CTkLabel(
            meta,
            text=f"{duty_count} on duty",
            font=font("small"),
            text_color=UI_TEXT_MUTED,
        ).pack(side="right", padx=(4, 0))
        linked_id = self._linked_officer_id() if self._is_officer_role() else None
        if roster:
            for item in self._sort_day_roster(roster):
                off = item["officer"]
                is_self = linked_id and off.get("id") == linked_id
                row = ctk.CTkFrame(
                    roster_list,
                    fg_color=UI_SURFACE,
                    corner_radius=6,
                    border_width=2 if is_self else 0,
                    border_color=DODGEVILLE_GOLD if is_self else UI_BORDER,
                )
                row.pack(fill="x", pady=2)
                inner = ctk.CTkFrame(row, fg_color="transparent")
                inner.pack(fill="x", padx=10, pady=6)
                inner.grid_columnconfigure(0, weight=1)
                ctk.CTkLabel(
                    inner,
                    text=off.get("name") or "Officer",
                    font=font("body"),
                    anchor="w",
                    text_color=DODGEVILLE_GOLD if is_self else "#FFFFFF",
                ).grid(row=0, column=0, sticky="w")
                shift_text = self._shift_time_label(off) or "—"
                ctk.CTkLabel(
                    inner,
                    text=shift_text,
                    font=font("small"),
                    text_color=DODGEVILLE_ACCENT,
                    anchor="e",
                ).grid(row=0, column=1, sticky="e", padx=(8, 0))
                meta_parts = [item["status"].title()]
                if item.get("is_manual"):
                    meta_parts.append("manual")
                if item.get("notes"):
                    meta_parts.append(item["notes"])
                ctk.CTkLabel(
                    inner,
                    text=" · ".join(meta_parts),
                    font=font("small"),
                    text_color=UI_TEXT_MUTED,
                    anchor="w",
                ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 0))
        else:
            ctk.CTkLabel(
                roster_list,
                text="No officers on duty this day.",
                font=font("body"),
                text_color=UI_TEXT_MUTED,
                anchor="w",
            ).pack(fill="x", pady=4)
