"""Timecard, payroll, and pay-period exports."""

from datetime import date
from tkinter import filedialog, messagebox
from typing import Optional, Tuple

import customtkinter as ctk

from config import (
    DATE_INPUT_HINT,
    PAYROLL_ENTRY_TYPES,
    POSITION_PAY_BASIS_LABELS,
    TIMECARD_ENTRY_TYPES,
    TIMECARD_REGULAR_TYPE,
    YEARLY_SALARY_TITLES,
)
from logic import (
    add_custom_officer_title,
    apply_position_pay_rates_to_roster,
    approve_timecard_period,
    auto_prefill_timecard_from_live_schedule,
    calculate_pay_for_entry,
    copy_timecard_from_previous_period,
    create_payroll_entry,
    delete_timecard_entry,
    export_pay_stub_pdf,
    export_payroll_csv,
    export_payroll_pdf,
    export_timecard_csv,
    format_pay_period_label,
    get_adjacent_pay_period,
    get_builtin_officer_titles,
    get_department_pay_summary,
    get_flsa_settings,
    get_holidays_in_range,
    get_officer_time_banks,
    get_officer_title_options,
    get_officers_by_seniority,
    get_pay_code_rules,
    get_pay_period,
    get_pay_period_history,
    get_pay_period_hours_summary,
    get_pay_stub_preview,
    get_payroll_entries,
    get_payroll_period_timesheets,
    get_position_pay_rates,
    get_timecard_entries_for_scope,
    get_timecard_period,
    import_timecard_to_payroll,
    is_current_pay_period,
    is_future_pay_period,
    is_pay_period_locked,
    is_timecard_period_approved,
    list_pay_periods_catalog,
    list_timecard_approvals_for_period,
    lock_pay_period,
    prefill_timecard_from_schedule,
    project_officer_annual_pay,
    reject_timecard_period,
    resolve_time_scope,
    save_flsa_settings,
    save_pay_code_rules,
    save_position_pay_rates,
    save_timecard_entry,
    search_pay_period_by_date,
    shift_scope_reference,
    submit_timecard_for_approval,
    unlock_pay_period,
)
from ui.helpers import today_placeholder
from ui.theme import (
    CARD_PAD,
    DODGEVILLE_ACCENT,
    DODGEVILLE_BLUE,
    DODGEVILLE_DANGER,
    DODGEVILLE_GOLD,
    DODGEVILLE_SUCCESS,
    DODGEVILLE_WARNING,
    UI_BORDER,
    UI_SURFACE,
    UI_TEXT_MUTED,
    font,
)
from ui.widgets import AlertBanner, Card, ExpandableSection, FormField, SectionHeader
from validators import (
    format_date,
    format_officer_title_display,
    format_position_pay_summary,
    normalize_position_pay_basis,
    parse_date,
    position_amount_to_hourly,
)


class PayrollPageMixin:
    def _export_payroll_pdf(self):
        if not (self.can("reports.export") or self._is_officer_role()):
            return
        p_start, _ = self._payroll_view_period()
        officer_id = None
        if self._is_officer_role():
            officer_id = self._linked_officer_id()
        else:
            filt = self.pay_filter.get()
            if filt != "All Officers" and filt in self.pay_officer_map:
                officer_id = self.pay_officer_map[filt]["id"]
        self._export_pdf_result(
            export_payroll_pdf(officer_id=officer_id, period_start=p_start),
            "Payroll PDF",
        )

    def _export_payroll_csv_from_tab(self):
        if not (self.can("reports.export") or self._is_officer_role()):
            return
        p_start, _ = self._payroll_view_period()
        officer_id = self._linked_officer_id() if self._is_officer_role() else None
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
        )
        if not path:
            return
        result = export_payroll_csv(
            period_start=p_start,
            officer_id=officer_id,
            output_path=path,
        )
        if result.get("success"):
            messagebox.showinfo(
                "Export",
                f"Payroll exported ({result['count']} rows)\n{result['path']}",
            )
            self.set_status("Payroll CSV exported")
        else:
            messagebox.showerror("Export Failed", result.get("message", "Unknown error"))

    def _build_timecard(self):
        page = self.pages["timecard"]
        page.grid_rowconfigure(4, weight=1)
        page.grid_columnconfigure(0, weight=1)

        hdr = ctk.CTkFrame(page, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        period_start, period_end = get_pay_period()
        self.tc_period_label = ctk.CTkLabel(
            hdr,
            text=f"Pay Period: {format_pay_period_label(period_start, period_end)}",
            font=font("heading"),
        )
        self.tc_period_label.pack(side="left")
        ctk.CTkLabel(
            hdr,
            text="14-day periods · hours count where the shift starts (overnight shifts too)",
            font=font("small"),
            text_color=UI_TEXT_MUTED,
        ).pack(side="left", padx=(12, 0))
        self.tc_totals_label = ctk.CTkLabel(
            hdr,
            text="",
            font=font("small"),
            text_color=UI_TEXT_MUTED,
        )
        self.tc_totals_label.pack(side="left", padx=(12, 0))
        tc_nav = ctk.CTkFrame(hdr, fg_color="transparent")
        tc_nav.pack(side="left", padx=(8, 0))
        ctk.CTkButton(
            tc_nav,
            text="◀",
            width=36,
            height=36,
            fg_color=UI_BORDER,
            command=lambda: self._shift_timecard_period(-1),
        ).pack(side="left", padx=(0, 4))
        ctk.CTkButton(
            tc_nav,
            text="Today",
            width=64,
            height=36,
            fg_color=UI_SURFACE,
            command=self._reset_timecard_period,
        ).pack(side="left", padx=(0, 4))
        self._tc_period_next_btn = ctk.CTkButton(
            tc_nav,
            text="▶",
            width=36,
            height=36,
            fg_color=UI_BORDER,
            command=lambda: self._shift_timecard_period(1),
        )
        self._tc_period_next_btn.pack(side="left")

        if self.can("timecard.view_all"):
            officers = [o for o in get_officers_by_seniority() if o.get("active") == 1]
            labels = [o["name"] for o in officers]
            self.tc_officer_map = {n: o["id"] for n, o in zip(labels, officers)}
            self.tc_officer_combo = ctk.CTkComboBox(
                hdr, values=labels, width=220, height=36, command=lambda _: self.refresh_timecard()
            )
            self.tc_officer_combo.pack(side="left", padx=12)
            if labels:
                self.tc_officer_combo.set(labels[0])
        else:
            self.tc_officer_map = {}
            self.tc_officer_combo = None
            if self.current_user and self.current_user.get("officer_id"):
                name = self.current_user.get("officer_name") or "My Timecard"
                ctk.CTkLabel(hdr, text=name, font=font("subheading")).pack(side="left", padx=12)

        self._tc_copy_btn = ctk.CTkButton(
            hdr,
            text="Copy Prev Period",
            height=36,
            fg_color=UI_SURFACE,
            hover_color=DODGEVILLE_GOLD,
            command=self.copy_previous_timecard,
        )
        self._tc_copy_btn.pack(side="right", padx=(8, 0))
        self._tc_prefill_btn = ctk.CTkButton(
            hdr,
            text="Refresh from Live Schedule",
            height=36,
            fg_color=UI_SURFACE,
            hover_color=DODGEVILLE_ACCENT,
            command=self.prefill_timecard,
        )
        self._tc_prefill_btn.pack(side="right", padx=(8, 0))
        self._tc_submit_btn = ctk.CTkButton(
            hdr,
            text="Submit for Approval",
            height=36,
            fg_color=DODGEVILLE_GOLD,
            hover_color=DODGEVILLE_ACCENT,
            command=self._submit_timecard_for_approval,
        )
        if self.can("timecard.submit"):
            self._tc_submit_btn.pack(side="right", padx=(8, 0))
        self._tc_approve_btn = ctk.CTkButton(
            hdr,
            text="Approve Timecard",
            height=36,
            fg_color=DODGEVILLE_SUCCESS,
            command=self._approve_timecard_period,
        )
        self._tc_reject_btn = ctk.CTkButton(
            hdr,
            text="Return for Edits",
            height=36,
            fg_color=DODGEVILLE_DANGER,
            command=self._reject_timecard_period,
        )
        if self.can("timecard.approve"):
            self._tc_approve_btn.pack(side="right", padx=(8, 0))
            self._tc_reject_btn.pack(side="right", padx=(8, 0))
        self._tc_save_btn = ctk.CTkButton(
            hdr,
            text="Save All Days",
            height=36,
            fg_color=DODGEVILLE_SUCCESS,
            command=self.save_all_timecard,
        )
        self._tc_save_btn.pack(side="right", padx=(8, 0))
        self._tc_import_btn = ctk.CTkButton(
            hdr,
            text="Import to Payroll",
            height=36,
            fg_color=DODGEVILLE_ACCENT,
            command=self.import_timecard_payroll,
        )
        self._tc_import_btn.pack(side="right")
        ctk.CTkButton(
            hdr,
            text="Export CSV",
            height=36,
            fg_color=DODGEVILLE_GOLD,
            command=self._export_timecard_csv,
        ).pack(side="right", padx=(8, 0))

        search_row = ctk.CTkFrame(page, fg_color="transparent")
        search_row.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        ctk.CTkLabel(
            search_row,
            text="Find period",
            font=font("small"),
            text_color=UI_TEXT_MUTED,
        ).pack(side="left")
        self.tc_period_search = ctk.CTkEntry(
            search_row,
            width=120,
            height=32,
            placeholder_text=today_placeholder(),
        )
        self.tc_period_search.pack(side="left", padx=(6, 4))
        ctk.CTkButton(
            search_row,
            text="Go",
            width=48,
            height=32,
            fg_color=DODGEVILLE_BLUE,
            command=self._search_timecard_period,
        ).pack(side="left", padx=(0, 12))
        ctk.CTkLabel(
            search_row,
            text="History",
            font=font("small"),
            text_color=UI_TEXT_MUTED,
        ).pack(side="left")
        self.tc_period_picker = ctk.CTkComboBox(
            search_row,
            width=280,
            height=32,
            values=["Loading..."],
            command=self._pick_timecard_period,
        )
        self.tc_period_picker.pack(side="left", padx=(6, 0))
        ctk.CTkLabel(
            search_row,
            text="View",
            font=font("small"),
            text_color=UI_TEXT_MUTED,
        ).pack(side="left", padx=(16, 0))
        self.tc_scope_combo = ctk.CTkComboBox(
            search_row,
            values=["Pay Period", "Month", "Year", "All Time"],
            width=120,
            height=32,
            command=self._on_timecard_scope_change,
        )
        self.tc_scope_combo.set("Pay Period")
        self.tc_scope_combo.pack(side="left", padx=(6, 0))

        self.tc_lock_banner = ctk.CTkFrame(page, fg_color="transparent")
        self.tc_lock_banner.grid(row=2, column=0, sticky="ew", pady=(0, 6))

        self.tc_approval_panel = ctk.CTkFrame(page, fg_color="transparent")
        self.tc_approval_panel.grid(row=3, column=0, sticky="ew", pady=(0, 6))

        self.timecard_scroll = ctk.CTkScrollableFrame(page, fg_color="transparent")
        self.timecard_scroll.grid(row=4, column=0, sticky="nsew")
        page.grid_rowconfigure(4, weight=1)
        self._timecard_day_widgets = []

    def _timecard_can_override_approval(self) -> bool:
        return self.can("timecard.edit_all")

    def _timecard_read_only(self) -> bool:
        period_start, _ = self._timecard_view_period()
        officer_id = self._timecard_officer_id()
        approved = (
            officer_id
            and is_timecard_period_approved(officer_id, period_start)
            and not self._timecard_can_override_approval()
        )
        return is_pay_period_locked(period_start) or not is_current_pay_period(period_start) or approved

    def _timecard_officer_id(self):
        if self.tc_officer_combo:
            oid = self.tc_officer_map.get(self.tc_officer_combo.get())
            if oid:
                return oid
        if self.current_user:
            return self.current_user.get("officer_id")
        return None

    def _timecard_view_period(self) -> Tuple[date, date]:
        if self._timecard_period_start:
            return get_pay_period(self._timecard_period_start)
        return get_pay_period()

    def _timecard_scope_key(self) -> str:
        label = self.tc_scope_combo.get() if hasattr(self, "tc_scope_combo") else "Pay Period"
        return {
            "Pay Period": "pay_period",
            "Month": "month",
            "Year": "year",
            "All Time": "all_time",
        }.get(label, "pay_period")

    def _on_timecard_scope_change(self, _selection: str = ""):
        self._timecard_scope = self._timecard_scope_key()
        self._timecard_scope_reference = None
        self.refresh_timecard()

    def _shift_timecard_period(self, direction: int):
        scope = self._timecard_scope_key()
        if scope == "all_time":
            return
        if scope == "pay_period":
            start, _ = self._timecard_view_period()
            next_start, _ = get_adjacent_pay_period(start, direction)
            if direction > 0 and is_future_pay_period(next_start):
                return
            self._timecard_period_start = next_start
            self._payroll_period_start = next_start
        else:
            ref = self._timecard_scope_reference or date.today()
            self._timecard_scope_reference = shift_scope_reference(scope, ref, direction)
        self.refresh_timecard()

    def _reset_timecard_period(self):
        self._timecard_period_start = None
        self._payroll_period_start = None
        self._timecard_scope_reference = None
        self.refresh_timecard()

    def _refresh_timecard_period_picker(self):
        if not hasattr(self, "tc_period_picker"):
            return
        officer_id = self._timecard_officer_id()
        catalog = list_pay_periods_catalog(officer_id)
        labels = []
        self._tc_period_pick_map = {}
        for row in catalog.get("periods", []):
            hours_note = f" · {row['total_hours']:.1f}h" if row.get("has_data") else ""
            current_note = " · current" if row.get("is_current") else ""
            label = f"{row['label']}{hours_note}{current_note}"
            labels.append(label)
            self._tc_period_pick_map[label] = row["period_start"]
        if not labels:
            labels = ["No pay periods"]
        self.tc_period_picker.configure(values=labels)
        period_start, _ = self._timecard_view_period()
        match = next(
            (lbl for lbl, ps in self._tc_period_pick_map.items() if ps == period_start.isoformat()),
            labels[0],
        )
        self.tc_period_picker.set(match)

    def _search_timecard_period(self):
        query = self.tc_period_search.get().strip()
        if not query:
            messagebox.showwarning("Search", f"Enter a shift-start date ({DATE_INPUT_HINT}).")
            return
        result = search_pay_period_by_date(query)
        if not result.get("success"):
            messagebox.showerror("Search", result.get("message", "Not found"))
            return
        from validators import parse_date

        self._timecard_period_start = parse_date(result["period_start"])
        self._payroll_period_start = self._timecard_period_start
        if hasattr(self, "tc_scope_combo"):
            self.tc_scope_combo.set("Pay Period")
        self._timecard_scope = "pay_period"
        self._timecard_scope_reference = None
        self.refresh_timecard()
        self.set_status(f"Showing pay period {result['label']}")

    def _pick_timecard_period(self, selection: str):
        period_start = getattr(self, "_tc_period_pick_map", {}).get(selection)
        if not period_start:
            return
        from validators import parse_date

        self._timecard_period_start = parse_date(period_start)
        self._payroll_period_start = self._timecard_period_start
        if hasattr(self, "tc_scope_combo"):
            self.tc_scope_combo.set("Pay Period")
        self._timecard_scope = "pay_period"
        self._timecard_scope_reference = None
        self.refresh_timecard()

    def _export_timecard_csv(self):
        period_start, _ = self._timecard_view_period()
        officer_id = self._timecard_officer_id()
        if self._is_officer_role():
            officer_id = self._linked_officer_id()
        elif self.tc_officer_combo and officer_id:
            pass
        else:
            officer_id = None
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
        )
        if not path:
            return
        result = export_timecard_csv(
            period_start=period_start,
            officer_id=officer_id,
            output_path=path,
        )
        if result.get("success"):
            messagebox.showinfo(
                "Export",
                f"Timecard exported ({result['count']} rows)\n{result['path']}",
            )
            self.set_status("Timecard CSV exported")
        else:
            messagebox.showerror("Export Failed", result.get("message", "Unknown error"))

    def refresh_timecard(self):
        officer_id = self._timecard_officer_id()
        if not officer_id:
            return
        scope = self._timecard_scope_key()
        self._timecard_scope = scope
        if scope != "pay_period":
            self._refresh_timecard_scope_view(officer_id, scope)
            return
        period_start, period_end = self._timecard_view_period()
        viewing_current = is_current_pay_period(period_start)
        locked = is_pay_period_locked(period_start)
        approved = is_timecard_period_approved(officer_id, period_start)
        suffix = "  ·  LOCKED" if locked else ""
        if approved:
            suffix += "  ·  APPROVED"
        if not viewing_current:
            suffix += "  ·  past period (read-only)"
        self.tc_period_label.configure(
            text=f"Pay Period: {format_pay_period_label(period_start, period_end)}{suffix}",
            text_color=DODGEVILLE_DANGER if locked else ("#7FD99A" if approved else "#FFFFFF"),
        )
        self._refresh_timecard_period_picker()
        if hasattr(self, "_tc_period_next_btn"):
            next_start, _ = get_adjacent_pay_period(period_start, 1)
            self._tc_period_next_btn.configure(
                state="disabled" if is_future_pay_period(next_start) else "normal",
            )
        read_only = self._timecard_read_only()
        if viewing_current and not locked and not approved:
            auto_prefill_timecard_from_live_schedule(officer_id, period_start)
        for w in self.tc_lock_banner.winfo_children():
            w.destroy()
        if locked:
            AlertBanner(
                self.tc_lock_banner,
                "Pay period is locked. Timecard edits and payroll import are disabled.",
                "warning",
            ).pack(fill="x")
        elif approved and not self._timecard_can_override_approval():
            AlertBanner(
                self.tc_lock_banner,
                "Supervisor approved this timecard for the pay period. Contact a supervisor to request changes.",
                "success",
            ).pack(fill="x")
        period_holidays = get_holidays_in_range(period_start, period_end)
        self._tc_holiday_by_date = {h["holiday_date"]: h for h in period_holidays}
        if period_holidays:
            parts = []
            for h in period_holidays:
                paid = "paid" if h.get("is_paid") else "unpaid"
                parts.append(f"{format_date(h['holiday_date'])} — {h['name']} ({paid})")
            AlertBanner(
                self.tc_lock_banner,
                "Department holidays this pay period: " + "  ·  ".join(parts),
                "info",
            ).pack(fill="x", pady=(6, 0) if locked or approved else 0)
        if self.can("payroll.edit"):
            AlertBanner(
                self.tc_lock_banner,
                "Pay formulas and base rates: Payroll tab → Position Pay Rates & Pay Code Calculations",
                "info",
            ).pack(fill="x", pady=(6, 0))
        self._refresh_timecard_approval_panel(period_start)
        editable = not read_only
        for btn in (self._tc_save_btn, self._tc_import_btn, self._tc_copy_btn, self._tc_prefill_btn):
            if btn:
                btn.configure(state="disabled" if not editable else "normal")
        if hasattr(self, "_tc_submit_btn"):
            can_submit = editable and self.can("timecard.submit") and self._linked_officer_id() == officer_id
            self._tc_submit_btn.configure(state="normal" if can_submit else "disabled")
        if hasattr(self, "_tc_approve_btn"):
            can_review = self.can("timecard.approve") and viewing_current and not locked
            state = "normal" if can_review else "disabled"
            self._tc_approve_btn.configure(state=state)
            self._tc_reject_btn.configure(state=state)
        data = get_timecard_period(officer_id, period_start)
        if not data.get("success"):
            return
        total_hours = sum(e.get("hours_worked") or 0 for d in data["days"] for e in d.get("entries", []))
        entry_count = sum(len(d.get("entries", [])) for d in data["days"])
        imported_rows = sum(1 for d in data["days"] for e in d.get("entries", []) if e.get("imported"))
        if hasattr(self, "tc_totals_label"):
            self.tc_totals_label.configure(
                text=(f"{total_hours:.1f}h total  ·  {entry_count} line(s)  ·  {imported_rows} imported to payroll"),
            )
        for w in self.timecard_scroll.winfo_children():
            w.destroy()
        self._timecard_day_widgets = []

        header = ctk.CTkFrame(self.timecard_scroll, fg_color=UI_SURFACE, corner_radius=8)
        header.pack(fill="x", pady=(0, 6))
        inner = ctk.CTkFrame(header, fg_color="transparent")
        inner.pack(fill="x", padx=12, pady=8)
        for col, text in enumerate(["Date", "In", "Out", "Hours", "Pay Type", "Night Hrs", "Notes", ""]):
            ctk.CTkLabel(inner, text=text, font=font("small"), text_color=UI_TEXT_MUTED, width=90 if col else 110).grid(
                row=0, column=col, padx=2
            )

        for day in data["days"]:
            day_group = ctk.CTkFrame(self.timecard_scroll, fg_color="transparent")
            day_group.pack(fill="x", pady=3)
            for row_index, entry in enumerate(day.get("entries", [])):
                self._render_timecard_entry_row(
                    day_group,
                    day,
                    entry,
                    row_index,
                    read_only,
                )

    def _refresh_timecard_scope_view(self, officer_id: int, scope: str):
        ref = self._timecard_scope_reference
        start, end, scope_label = resolve_time_scope(scope, ref)
        if start and end:
            label = f"{scope_label}  ({format_date(start)} – {format_date(end)})  ·  read-only"
        else:
            label = f"{scope_label}  ·  read-only"
        self.tc_period_label.configure(text=label, text_color="#FFFFFF")
        if hasattr(self, "tc_totals_label"):
            self.tc_totals_label.configure(text="")
        if hasattr(self, "_tc_period_next_btn"):
            nav_state = "disabled" if scope == "all_time" else "normal"
            self._tc_period_next_btn.configure(state=nav_state)
        for w in self.tc_lock_banner.winfo_children():
            w.destroy()
        AlertBanner(
            self.tc_lock_banner,
            "Month, year, and all-time views are read-only. Switch to Pay Period to edit entries.",
            "info",
        ).pack(fill="x")
        for w in self.tc_approval_panel.winfo_children():
            w.destroy()
        for btn in (
            self._tc_save_btn,
            self._tc_import_btn,
            self._tc_copy_btn,
            self._tc_prefill_btn,
            getattr(self, "_tc_submit_btn", None),
            getattr(self, "_tc_approve_btn", None),
            getattr(self, "_tc_reject_btn", None),
        ):
            if btn:
                btn.configure(state="disabled")
        data = get_timecard_entries_for_scope(officer_id, scope=scope, reference=ref)
        if not data.get("success"):
            return
        if hasattr(self, "tc_totals_label"):
            self.tc_totals_label.configure(
                text=f"{data.get('total_hours', 0):.1f}h total  ·  {data.get('entry_count', 0)} line(s)",
            )
        for w in self.timecard_scroll.winfo_children():
            w.destroy()
        self._timecard_day_widgets = []
        header = ctk.CTkFrame(self.timecard_scroll, fg_color=UI_SURFACE, corner_radius=8)
        header.pack(fill="x", pady=(0, 6))
        inner = ctk.CTkFrame(header, fg_color="transparent")
        inner.pack(fill="x", padx=12, pady=8)
        for col, text in enumerate(["Date", "In", "Out", "Hours", "Pay Type", "Night Hrs", "Notes", "Status"]):
            ctk.CTkLabel(inner, text=text, font=font("small"), text_color=UI_TEXT_MUTED, width=90 if col else 110).grid(
                row=0, column=col, padx=2
            )
        for row in data.get("entries") or []:
            row_frame = ctk.CTkFrame(self.timecard_scroll, fg_color=UI_SURFACE, corner_radius=8)
            row_frame.pack(fill="x", pady=2)
            inner_row = ctk.CTkFrame(row_frame, fg_color="transparent")
            inner_row.pack(fill="x", padx=10, pady=8)
            entry_date = parse_date(row["entry_date"])
            status = "Imported" if row.get("payroll_entry_id") else "Saved"
            for col, text in enumerate(
                [
                    format_date(entry_date),
                    row.get("time_in") or "—",
                    row.get("time_out") or "—",
                    f"{float(row.get('hours_worked') or 0):.1f}",
                    row.get("entry_type") or TIMECARD_REGULAR_TYPE,
                    f"{float(row.get('night_diff_hours') or 0):.1f}",
                    (row.get("notes") or "")[:40],
                    status,
                ]
            ):
                ctk.CTkLabel(inner_row, text=text, font=font("small"), width=90 if col else 110, anchor="w").grid(
                    row=0, column=col, padx=2, sticky="w"
                )

    def _render_timecard_entry_row(self, day_group, day, entry, row_index: int, read_only: bool):
        row_frame = ctk.CTkFrame(day_group, fg_color=UI_SURFACE, corner_radius=8)
        row_frame.pack(fill="x", pady=2)
        row = ctk.CTkFrame(row_frame, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=8)

        date_cell = ctk.CTkFrame(row, fg_color="transparent", width=110)
        date_cell.grid(row=0, column=0, padx=2, sticky="w")
        if row_index == 0:
            sched = "✓" if day["scheduled"] else "·"
            overnight = "  ↪" if entry.get("overnight") else ""
            holiday = getattr(self, "_tc_holiday_by_date", {}).get(day["entry_date"])
            holiday_mark = f"  ★ {holiday['name']}" if holiday else ""
            ctk.CTkLabel(
                date_cell,
                text=f"{day['day_label']} {sched}{overnight}{holiday_mark}",
                anchor="w",
                text_color=DODGEVILLE_GOLD if holiday else None,
            ).pack(side="left")
            if not read_only:
                ctk.CTkButton(
                    date_cell,
                    text="+",
                    width=28,
                    height=28,
                    fg_color=DODGEVILLE_SUCCESS,
                    hover_color=DODGEVILLE_ACCENT,
                    font=font("small"),
                    command=lambda d=day, g=day_group: self._add_timecard_extra_row(d, g),
                ).pack(side="left", padx=(4, 0))
        else:
            ctk.CTkLabel(
                date_cell,
                text="  + line",
                anchor="w",
                text_color=UI_TEXT_MUTED,
            ).pack(side="left")

        time_in = ctk.CTkEntry(row, width=70, height=30, placeholder_text="06:00")
        time_in.insert(0, entry.get("time_in") or "")
        time_in.grid(row=0, column=1, padx=2)
        time_out = ctk.CTkEntry(row, width=70, height=30, placeholder_text="17:00")
        time_out.insert(0, entry.get("time_out") or "")
        time_out.grid(row=0, column=2, padx=2)
        hours = ctk.CTkEntry(row, width=60, height=30)
        hours.insert(0, str(entry.get("hours_worked") or 0))
        hours.grid(row=0, column=3, padx=2)
        pay_type = ctk.CTkComboBox(row, values=TIMECARD_ENTRY_TYPES, width=150, height=30)
        pay_type.set(entry.get("entry_type") or TIMECARD_ENTRY_TYPES[0])
        pay_type.grid(row=0, column=4, padx=2)
        night = ctk.CTkEntry(row, width=60, height=30)
        night.insert(0, str(entry.get("night_diff_hours") or 0))
        night.grid(row=0, column=5, padx=2)
        notes = ctk.CTkEntry(row, width=120, height=30)
        notes.insert(0, entry.get("notes") or "")
        notes.grid(row=0, column=6, padx=2)

        imported = entry.get("imported")
        entry_state = "disabled" if imported or read_only else "normal"
        for widget in (time_in, time_out, hours, pay_type, night, notes):
            widget.configure(state=entry_state)
        if imported:
            row_frame.configure(fg_color=UI_BORDER)

        action_col = ctk.CTkFrame(row, fg_color="transparent")
        action_col.grid(row=0, column=7, padx=2)
        timecard_id = entry.get("timecard_id")
        save_btn = ctk.CTkButton(
            action_col,
            text="Locked" if imported or read_only else "Save",
            width=70,
            height=30,
            fg_color=UI_BORDER if imported or read_only else DODGEVILLE_BLUE,
            state="disabled" if imported or read_only else "normal",
            command=lambda d=day["entry_date"], tid=timecard_id, ti=time_in, tout=time_out, h=hours, pt=pay_type, n=night, nt=notes: (
                self._save_timecard_day(
                    d,
                    ti,
                    tout,
                    h,
                    pt,
                    n,
                    nt,
                    timecard_id=tid,
                )
            ),
        )
        save_btn.pack(side="left")
        if row_index > 0 and not read_only and not imported:
            ctk.CTkButton(
                action_col,
                text="×",
                width=28,
                height=30,
                fg_color=DODGEVILLE_DANGER,
                hover_color=UI_BORDER,
                command=lambda tid=timecard_id, rf=row_frame: self._remove_timecard_entry_row(tid, rf),
            ).pack(side="left", padx=(4, 0))

        self._timecard_day_widgets.append(
            {
                "date": day["entry_date"],
                "timecard_id": timecard_id,
                "time_in": time_in,
                "time_out": time_out,
                "hours": hours,
                "pay_type": pay_type,
                "night": night,
                "notes": notes,
                "imported": imported,
            }
        )

    def _add_timecard_extra_row(self, day, day_group):
        if self._timecard_read_only():
            return
        empty_entry = {
            "timecard_id": None,
            "hours_worked": 0,
            "time_in": "",
            "time_out": "",
            "entry_type": TIMECARD_REGULAR_TYPE,
            "night_diff_hours": 0,
            "notes": "",
            "imported": False,
            "overnight": False,
        }
        row_index = len(day_group.winfo_children())
        self._render_timecard_entry_row(day_group, day, empty_entry, row_index, read_only=False)

    def _remove_timecard_entry_row(self, timecard_id, row_frame):
        if self._timecard_read_only():
            return
        officer_id = self._timecard_officer_id()
        if not officer_id:
            return
        if timecard_id:
            result = delete_timecard_entry(
                timecard_id,
                officer_id,
                override_approval=self._timecard_can_override_approval(),
            )
            if not result.get("success"):
                messagebox.showerror("Remove", result.get("message", "Delete failed"))
                return
            self.refresh_timecard()
            self.set_status(result.get("message", "Entry removed"))
        else:
            row_frame.destroy()

    def _save_timecard_day(
        self,
        entry_date,
        time_in,
        time_out,
        hours,
        pay_type,
        night,
        notes,
        timecard_id=None,
    ):
        officer_id = self._timecard_officer_id()
        if not officer_id:
            return
        try:
            hrs = float(hours.get().strip() or "0")
            night_h = float(night.get().strip() or "0")
        except ValueError:
            messagebox.showerror("Validation", "Hours must be numeric.")
            return
        result = save_timecard_entry(
            officer_id,
            entry_date,
            hrs,
            pay_type.get(),
            time_in.get().strip(),
            time_out.get().strip(),
            night_h,
            notes.get().strip(),
            timecard_id=timecard_id,
            override_approval=self._timecard_can_override_approval(),
        )
        if result.get("success"):
            self.set_status(result.get("message") or f"Timecard saved for {format_date(entry_date)}")
            self.refresh_timecard()
        else:
            messagebox.showerror("Error", result.get("message", "Save failed"))

    def _refresh_timecard_approval_panel(self, period_start: date):
        for w in self.tc_approval_panel.winfo_children():
            w.destroy()
        if not self.can("timecard.view_all"):
            return
        summary = list_timecard_approvals_for_period(period_start)
        if not summary.get("success"):
            return
        card = Card(self.tc_approval_panel)
        card.pack(fill="x")
        SectionHeader(
            card.body,
            "Timecard Approvals",
            "Review and approve each officer's timecard for this pay period",
        ).pack(fill="x", padx=CARD_PAD, pady=(CARD_PAD, 6))
        rows_frame = ctk.CTkFrame(card.body, fg_color="transparent")
        rows_frame.pack(fill="x", padx=CARD_PAD, pady=(0, CARD_PAD))
        for col, label in enumerate(["Officer", "Hours", "Lines", "Status", ""]):
            ctk.CTkLabel(
                rows_frame,
                text=label,
                font=font("small"),
                text_color=UI_TEXT_MUTED,
                width=120 if col == 0 else 80,
            ).grid(row=0, column=col, padx=4, sticky="w")
        for idx, row in enumerate(summary.get("rows", []), start=1):
            status = row.get("status", "Draft")
            color = {
                "Approved": DODGEVILLE_SUCCESS,
                "Submitted": DODGEVILLE_GOLD,
                "Rejected": DODGEVILLE_DANGER,
            }.get(status, UI_TEXT_MUTED)
            ctk.CTkLabel(rows_frame, text=row["officer_name"], anchor="w", width=120).grid(
                row=idx, column=0, padx=4, sticky="w"
            )
            ctk.CTkLabel(rows_frame, text=f"{row['total_hours']:.1f}h", width=80).grid(row=idx, column=1, padx=4)
            ctk.CTkLabel(rows_frame, text=str(row["line_count"]), width=80).grid(row=idx, column=2, padx=4)
            ctk.CTkLabel(rows_frame, text=status, text_color=color, width=80).grid(row=idx, column=3, padx=4)
            if self.can("timecard.approve"):
                ctk.CTkButton(
                    rows_frame,
                    text="Open",
                    width=64,
                    height=26,
                    command=lambda oid=row["officer_id"], name=row["officer_name"]: self._open_officer_timecard(
                        oid, name
                    ),
                ).grid(row=idx, column=4, padx=4)

    def _open_officer_timecard(self, officer_id: int, officer_name: str):
        if self.tc_officer_combo:
            self.tc_officer_combo.set(officer_name)
        self.refresh_timecard()

    def _submit_timecard_for_approval(self):
        officer_id = self._linked_officer_id()
        if not officer_id:
            messagebox.showwarning("Timecard", "Your account is not linked to an officer profile.")
            return
        p_start, _ = self._timecard_view_period()
        result = submit_timecard_for_approval(officer_id, p_start, self.current_user.get("id"))
        if result.get("success"):
            self.set_status("Timecard submitted for supervisor approval")
            self.refresh_timecard()
        else:
            messagebox.showerror("Submit", result.get("message", "Submit failed"))

    def _approve_timecard_period(self):
        if not self.can("timecard.approve"):
            return
        officer_id = self._timecard_officer_id()
        if not officer_id:
            return
        p_start, _ = self._timecard_view_period()
        result = approve_timecard_period(officer_id, p_start, self.current_user.get("id"))
        if result.get("success"):
            self.set_status(result.get("message", "Approved"))
            self.refresh_timecard()
        else:
            messagebox.showerror("Approve", result.get("message", "Approve failed"))

    def _reject_timecard_period(self):
        if not self.can("timecard.approve"):
            return
        officer_id = self._timecard_officer_id()
        if not officer_id:
            return
        p_start, _ = self._timecard_view_period()
        result = reject_timecard_period(officer_id, p_start, self.current_user.get("id"))
        if result.get("success"):
            self.set_status(result.get("message", "Returned for edits"))
            self.refresh_timecard()
        else:
            messagebox.showerror("Return", result.get("message", "Failed"))

    def copy_previous_timecard(self):
        if self._timecard_read_only():
            messagebox.showwarning("Locked", "Cannot modify a locked or historical pay period.")
            return
        officer_id = self._timecard_officer_id()
        if not officer_id:
            return
        p_start, _ = self._timecard_view_period()
        result = copy_timecard_from_previous_period(officer_id, p_start)
        if result.get("success"):
            self.set_status(result.get("message", "Copied"))
            self.refresh_timecard()
        else:
            messagebox.showerror("Copy", result.get("message", "Failed"))

    def prefill_timecard(self):
        if self._timecard_read_only():
            messagebox.showwarning("Locked", "Cannot modify a locked or historical pay period.")
            return
        officer_id = self._timecard_officer_id()
        if not officer_id:
            return
        p_start, _ = self._timecard_view_period()
        result = prefill_timecard_from_schedule(
            officer_id,
            p_start,
            override_approval=self._timecard_can_override_approval(),
        )
        if result.get("success"):
            self.set_status(result.get("message", "Prefilled from live schedule"))
            self.refresh_timecard()
        else:
            messagebox.showerror("Prefill", result.get("message", "Failed"))

    def save_all_timecard(self):
        if self._timecard_read_only():
            messagebox.showwarning("Locked", "Cannot modify a locked or historical pay period.")
            return
        pending = []
        for widgets in self._timecard_day_widgets:
            if not widgets["time_in"].winfo_exists():
                continue
            if widgets.get("imported"):
                continue
            pending.append(
                {
                    "date": widgets["date"],
                    "timecard_id": widgets.get("timecard_id"),
                    "time_in": widgets["time_in"].get().strip(),
                    "time_out": widgets["time_out"].get().strip(),
                    "hours": widgets["hours"].get().strip(),
                    "pay_type": widgets["pay_type"].get(),
                    "night": widgets["night"].get().strip(),
                    "notes": widgets["notes"].get().strip(),
                }
            )
        saved = 0
        officer_id = self._timecard_officer_id()
        if not officer_id:
            return
        for row in pending:
            try:
                hrs = float(row["hours"] or "0")
                night_h = float(row["night"] or "0")
            except ValueError:
                messagebox.showerror("Validation", "Hours must be numeric.")
                return
            result = save_timecard_entry(
                officer_id,
                row["date"],
                hrs,
                row["pay_type"],
                row["time_in"],
                row["time_out"],
                night_h,
                row["notes"],
                timecard_id=row.get("timecard_id"),
                override_approval=self._timecard_can_override_approval(),
            )
            if result.get("success"):
                saved += 1
            else:
                messagebox.showerror("Error", result.get("message", "Save failed"))
                break
        self.refresh_timecard()
        self.set_status(f"Saved {saved} timecard line(s)")

    def import_timecard_payroll(self):
        officer_id = self._timecard_officer_id()
        if not officer_id:
            return
        if not self.can("payroll.import_timecard"):
            if self.current_user.get("officer_id") != officer_id:
                messagebox.showwarning("Permission", "You can only import your own timecard.")
                return
        p_start, _ = self._timecard_view_period()
        result = import_timecard_to_payroll(officer_id, period_start=p_start.isoformat())
        if result.get("success"):
            messagebox.showinfo("Payroll", result.get("message", "Imported"))
            self.refresh_timecard()
            self.refresh_payroll()
        else:
            messagebox.showerror("Import", result.get("message", "Import failed"))

    def _jump_to_payroll_period(self, period_start_str: str):
        from validators import parse_date

        period = parse_date(period_start_str)
        self._payroll_period_start = period
        self._timecard_period_start = period
        self.show_page("payroll")
        self.refresh_payroll_period()

    def _jump_to_timecard_period(self, period_start_str: str):
        from validators import parse_date

        self._timecard_period_start = parse_date(period_start_str)
        self.show_page("timecard")
        self.refresh_timecard()

    def _build_payroll(self):
        page = self.pages["payroll"]
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(5, weight=1)

        period_hdr = Card(page)
        period_hdr.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        ph = ctk.CTkFrame(period_hdr.body, fg_color="transparent")
        ph.pack(fill="x", padx=CARD_PAD, pady=CARD_PAD)
        self._pay_period_header = SectionHeader(
            ph,
            "Pay Period Timesheets",
            "Biweekly periods · hours count where shift starts",
        )
        self._pay_period_header.pack(side="left", fill="x", expand=True)
        nav_frame = ctk.CTkFrame(ph, fg_color="transparent")
        nav_frame.pack(side="left", padx=(8, 0))
        ctk.CTkButton(
            nav_frame,
            text="◀",
            width=36,
            height=32,
            fg_color=UI_BORDER,
            command=lambda: self._shift_payroll_period(-1),
        ).pack(side="left", padx=(0, 4))
        ctk.CTkButton(
            nav_frame,
            text="Today",
            width=64,
            height=32,
            fg_color=UI_SURFACE,
            command=self._reset_payroll_period,
        ).pack(side="left", padx=(0, 4))
        self._pay_period_next_btn = ctk.CTkButton(
            nav_frame,
            text="▶",
            width=36,
            height=32,
            fg_color=UI_BORDER,
            command=lambda: self._shift_payroll_period(1),
        )
        self._pay_period_next_btn.pack(side="left")
        btn_frame = ctk.CTkFrame(ph, fg_color="transparent")
        btn_frame.pack(side="right")
        self._pay_lock_btn = ctk.CTkButton(
            btn_frame,
            text="Lock Period",
            width=100,
            height=32,
            fg_color=DODGEVILLE_WARNING,
            command=self._toggle_pay_period_lock,
        )
        if self.can("payroll.lock_period"):
            self._pay_lock_btn.pack(side="left", padx=4)
        ctk.CTkButton(
            btn_frame,
            text="Refresh Period",
            width=120,
            height=32,
            command=self.refresh_payroll_period,
        ).pack(side="left")
        if self.can("reports.export") or self._is_officer_role():
            csv_label = "Export My CSV" if self._is_officer_role() else "Export CSV"
            ctk.CTkButton(
                btn_frame,
                text=csv_label,
                width=110,
                height=32,
                fg_color=DODGEVILLE_GOLD,
                command=self._export_payroll_csv_from_tab,
            ).pack(side="left", padx=(4, 0))
        ctk.CTkButton(
            btn_frame,
            text="Pay Stub",
            width=90,
            height=32,
            fg_color=DODGEVILLE_GOLD,
            command=self._preview_payroll_stub,
        ).pack(side="left", padx=(4, 0))
        ctk.CTkButton(
            btn_frame,
            text="Stub PDF",
            width=90,
            height=32,
            fg_color=DODGEVILLE_BLUE,
            command=self._export_payroll_stub,
        ).pack(side="left", padx=(4, 0))
        self.pay_stub_preview = ctk.CTkLabel(
            period_hdr.body,
            text="",
            font=font("small"),
            text_color=UI_TEXT_MUTED,
            anchor="w",
            wraplength=900,
        )
        self.pay_stub_preview.pack(fill="x", padx=CARD_PAD, pady=(0, 4))
        pay_search = ctk.CTkFrame(period_hdr.body, fg_color="transparent")
        pay_search.pack(fill="x", padx=CARD_PAD, pady=(0, 6))
        ctk.CTkLabel(pay_search, text="Find period", font=font("small"), text_color=UI_TEXT_MUTED).pack(side="left")
        self.pay_period_search = ctk.CTkEntry(
            pay_search,
            width=120,
            height=32,
            placeholder_text=today_placeholder(),
        )
        self.pay_period_search.pack(side="left", padx=(6, 4))
        ctk.CTkButton(
            pay_search,
            text="Go",
            width=48,
            height=32,
            fg_color=DODGEVILLE_BLUE,
            command=self._search_payroll_period,
        ).pack(side="left", padx=(0, 12))
        ctk.CTkLabel(pay_search, text="History", font=font("small"), text_color=UI_TEXT_MUTED).pack(side="left")
        self.pay_period_picker = ctk.CTkComboBox(
            pay_search,
            width=300,
            height=32,
            values=["Loading..."],
            command=self._pick_payroll_period,
        )
        self.pay_period_picker.pack(side="left", padx=(6, 0))
        self.pay_period_scroll = ctk.CTkScrollableFrame(period_hdr.body, fg_color="transparent", height=220)
        self.pay_period_scroll.pack(fill="x", padx=8, pady=(0, 8))

        if self.can("payroll.edit"):
            self._build_flsa_settings_card(page)
            self._build_position_pay_rates_card(page)
            self._build_pay_code_rules_card(page)

        history_card = Card(page)
        history_card.grid(row=4, column=0, sticky="ew", pady=(0, 10))
        hist_hdr = ctk.CTkFrame(history_card.body, fg_color="transparent")
        hist_hdr.pack(fill="x", padx=CARD_PAD, pady=(CARD_PAD, 6))
        SectionHeader(hist_hdr, "Recent Pay Periods", "Click a period to view details").pack(side="left")
        if self.can("reports.export") or self._is_officer_role():
            hist_csv_label = "Export My History" if self._is_officer_role() else "Export History"
            ctk.CTkButton(
                hist_hdr,
                text=hist_csv_label,
                width=120,
                height=28,
                fg_color=DODGEVILLE_GOLD,
                command=self._export_pay_period_history_csv,
            ).pack(side="right")
        self.pay_history_frame = ctk.CTkFrame(history_card.body, fg_color="transparent")
        self.pay_history_frame.pack(fill="x", padx=CARD_PAD, pady=(0, CARD_PAD))

        body = ctk.CTkFrame(page, fg_color="transparent")
        body.grid(row=5, column=0, sticky="nsew")
        body.grid_columnconfigure(0, weight=2)
        body.grid_columnconfigure(1, weight=3)
        body.grid_rowconfigure(0, weight=1)

        self.pay_form_card = Card(body)
        self.pay_form_card.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        form_card = self.pay_form_card
        SectionHeader(form_card.body, "New Payroll Entry", "Hours auto calculate pay from officer rate").pack(
            fill="x", padx=CARD_PAD, pady=(CARD_PAD, 12)
        )
        pf = ctk.CTkFrame(form_card.body, fg_color="transparent")
        pf.pack(fill="x", padx=CARD_PAD)
        self.pay_officer = FormField(
            pf,
            "Officer",
            lambda p: ctk.CTkComboBox(p, height=36, values=["Loading..."], command=self._on_pay_officer_change),
        ).widget
        self.pay_banks = ctk.CTkLabel(
            pf, text="Time banks: not set", font=font("small"), text_color=UI_TEXT_MUTED, anchor="w"
        )
        self.pay_banks.pack(fill="x", pady=(0, 4))
        self.pay_position_rate = ctk.CTkLabel(
            pf, text="Position rate: not set", font=font("small"), text_color=UI_TEXT_MUTED, anchor="w"
        )
        self.pay_position_rate.pack(fill="x", pady=(0, 8))
        self.pay_date = FormField(
            pf, "Entry Date", lambda p: ctk.CTkEntry(p, height=36, placeholder_text=today_placeholder())
        ).widget
        self.pay_type = FormField(
            pf,
            "Entry Type",
            lambda p: ctk.CTkComboBox(p, height=36, values=PAYROLL_ENTRY_TYPES, command=self._on_pay_type_change),
        ).widget
        self.pay_formula_hint = ctk.CTkLabel(
            pf,
            text="Formula: —",
            font=font("small"),
            text_color=UI_TEXT_MUTED,
            anchor="w",
            wraplength=360,
        )
        self.pay_formula_hint.pack(fill="x", pady=(0, 8))
        self.pay_hours = FormField(pf, "Hours", lambda p: ctk.CTkEntry(p, height=36, placeholder_text="8.0")).widget
        self.pay_night_hours = FormField(
            pf, "Night Differential Hours", lambda p: ctk.CTkEntry(p, height=36, placeholder_text="0")
        ).widget
        self.pay_notes = FormField(pf, "Notes", lambda p: ctk.CTkEntry(p, height=36)).widget
        self.pay_holiday_ot = ctk.CTkCheckBox(pf, text="Holiday Overtime (premium rate)", font=font("body"))
        self.pay_holiday_ot.pack(anchor="w", pady=8)

        preview = ctk.CTkFrame(form_card.body, fg_color=UI_BORDER, corner_radius=8)
        preview.pack(fill="x", padx=CARD_PAD, pady=8)
        self.pay_preview = ctk.CTkLabel(preview, text="Estimated pay: not set", font=font("subheading"), anchor="w")
        self.pay_preview.pack(fill="x", padx=12, pady=12)

        ctk.CTkButton(
            pf,
            text="Preview Calculation",
            height=34,
            corner_radius=8,
            fg_color=UI_BORDER,
            hover_color=DODGEVILLE_ACCENT,
            command=self.preview_payroll,
        ).pack(fill="x", pady=(4, 8))
        ctk.CTkButton(
            form_card.body,
            text="Save Entry",
            height=40,
            corner_radius=8,
            fg_color=DODGEVILLE_SUCCESS,
            command=self.save_payroll_entry,
        ).pack(fill="x", padx=CARD_PAD, pady=CARD_PAD)

        self.pay_officer_map = {}

        list_card = Card(body)
        list_card.grid(row=0, column=1, sticky="nsew")
        hdr = ctk.CTkFrame(list_card.body, fg_color="transparent")
        hdr.pack(fill="x", padx=CARD_PAD, pady=(CARD_PAD, 4))
        SectionHeader(hdr, "Payroll Ledger", "Recent entries").pack(side="left")
        if self._is_officer_role():
            ctk.CTkButton(
                hdr,
                text="Export My PDF",
                width=110,
                height=32,
                fg_color=DODGEVILLE_BLUE,
                command=self._export_payroll_pdf,
            ).pack(side="right", padx=(8, 0))
        elif self.can("reports.export"):
            ctk.CTkButton(
                hdr,
                text="Export PDF",
                width=100,
                height=32,
                fg_color=DODGEVILLE_BLUE,
                command=self._export_payroll_pdf,
            ).pack(side="right", padx=(8, 0))
        self.pay_filter = ctk.CTkComboBox(
            hdr, values=["All Officers"], width=180, height=32, command=lambda _: self.refresh_payroll()
        )
        self.pay_filter.pack(side="right")
        self.payroll_list = ctk.CTkScrollableFrame(list_card.body, fg_color="transparent")
        self.payroll_list.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self._refresh_payroll_officer_dropdown()
        self._on_pay_type_change()
        if not self.can("payroll.edit"):
            self.pay_form_card.grid_remove()
            body.grid_columnconfigure(0, weight=0)
        if self._is_officer_role():
            self.pay_filter.pack_forget()
        self.refresh_payroll_period()

    def _build_flsa_settings_card(self, page):
        from config import DATE_INPUT_HINT

        card = Card(page)
        card.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        hdr = ctk.CTkFrame(card.body, fg_color="transparent")
        hdr.pack(fill="x", padx=CARD_PAD, pady=(CARD_PAD, 8))
        SectionHeader(
            hdr,
            "FLSA §207(k) Work Period",
            "Independent of pay period — set work-period length (days) and anchor date",
        ).pack(side="left", fill="x", expand=True)
        ctk.CTkButton(
            hdr,
            text="Save FLSA",
            width=100,
            height=30,
            fg_color=DODGEVILLE_SUCCESS,
            command=self._save_flsa_settings,
        ).pack(side="right")

        form = ctk.CTkFrame(card.body, fg_color="transparent")
        form.pack(fill="x", padx=CARD_PAD, pady=(0, CARD_PAD))
        form.grid_columnconfigure((0, 1, 2), weight=1)

        days_col = ctk.CTkFrame(form, fg_color="transparent")
        days_col.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ctk.CTkLabel(days_col, text="Work period (days)", font=font("small"), text_color=UI_TEXT_MUTED).pack(anchor="w")
        self.flsa_days_entry = ctk.CTkEntry(days_col, height=36, placeholder_text="7–28")
        self.flsa_days_entry.pack(fill="x", pady=(4, 0))

        base_col = ctk.CTkFrame(form, fg_color="transparent")
        base_col.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        ctk.CTkLabel(
            base_col,
            text=f"Period anchor date ({DATE_INPUT_HINT})",
            font=font("small"),
            text_color=UI_TEXT_MUTED,
        ).pack(anchor="w")
        self.flsa_base_entry = ctk.CTkEntry(base_col, height=36)
        self.flsa_base_entry.pack(fill="x", pady=(4, 0))

        self.flsa_status_label = ctk.CTkLabel(
            form,
            text="",
            font=font("small"),
            text_color=UI_TEXT_MUTED,
            anchor="w",
            wraplength=900,
        )
        self.flsa_status_label.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        self.refresh_flsa_settings()

    def refresh_flsa_settings(self):
        if not hasattr(self, "flsa_days_entry"):
            return
        data = get_flsa_settings()
        if not data.get("success"):
            return
        self.flsa_days_entry.delete(0, "end")
        self.flsa_days_entry.insert(0, str(data.get("work_period_days", "")))
        self.flsa_base_entry.delete(0, "end")
        self.flsa_base_entry.insert(0, data.get("base_date_display", ""))
        self.flsa_status_label.configure(
            text=(
                f"Current FLSA window: {data.get('current_period_start', '')} – "
                f"{data.get('current_period_end', '')}  ·  "
                f"Threshold {data.get('hours_threshold', 0):.0f}h  ·  "
                f"Not tied to 14-day pay periods"
            )
        )

    def _save_flsa_settings(self):
        if not self.can("payroll.edit"):
            return
        try:
            days = int(self.flsa_days_entry.get().strip())
        except ValueError:
            messagebox.showerror("FLSA", "Enter a valid work-period length (7–28 days).")
            return
        uid = self.current_user.get("id") if self.current_user else None
        result = save_flsa_settings(
            days,
            self.flsa_base_entry.get().strip(),
            user_id=uid,
        )
        if result.get("success"):
            messagebox.showinfo("FLSA", result.get("message", "Saved"))
            self.refresh_flsa_settings()
            if self.current_page == "banked_time":
                self.refresh_banked_time()
            self.set_status("FLSA settings saved")
        else:
            messagebox.showerror("FLSA", result.get("message", "Save failed"))

    def _build_position_pay_rates_card(self, page):
        card = Card(page)
        card.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        hdr = ctk.CTkFrame(card.body, fg_color="transparent")
        hdr.pack(fill="x", padx=CARD_PAD, pady=(CARD_PAD, 8))
        SectionHeader(
            hdr,
            "Position Pay Rates",
            "Standard ranks + custom titles · edit hrs/yr per title for hourly conversion",
        ).pack(side="left", fill="x", expand=True)
        btn_row = ctk.CTkFrame(hdr, fg_color="transparent")
        btn_row.pack(side="right")
        ctk.CTkButton(
            btn_row,
            text="Add Title",
            width=90,
            height=30,
            fg_color=UI_BORDER,
            hover_color=DODGEVILLE_ACCENT,
            command=self._add_position_pay_title,
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            btn_row,
            text="Apply to Roster",
            width=120,
            height=30,
            fg_color=UI_BORDER,
            hover_color=DODGEVILLE_ACCENT,
            command=self._apply_position_pay_rates,
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            btn_row,
            text="Save Rates",
            width=100,
            height=30,
            fg_color=DODGEVILLE_SUCCESS,
            command=self._save_position_pay_rates,
        ).pack(side="left")

        table_hdr = ctk.CTkFrame(card.body, fg_color=UI_SURFACE, corner_radius=8)
        table_hdr.pack(fill="x", padx=CARD_PAD, pady=(0, 4))
        inner_hdr = ctk.CTkFrame(table_hdr, fg_color="transparent")
        inner_hdr.pack(fill="x", padx=10, pady=8)
        for col, (text, width) in enumerate(
            [
                ("Title", 120),
                ("Amount ($)", 90),
                ("Basis", 80),
                ("Hrs/yr", 70),
                ("Salary", 50),
                ("Hourly", 80),
                ("Per period", 90),
            ]
        ):
            ctk.CTkLabel(
                inner_hdr,
                text=text,
                width=width,
                anchor="w",
                font=font("small"),
                text_color=UI_TEXT_MUTED,
            ).grid(row=0, column=col, padx=2, sticky="w")

        self._position_pay_rows = {}
        self._position_pay_scroll = ctk.CTkScrollableFrame(card.body, fg_color="transparent", height=210)
        self._position_pay_scroll.pack(fill="x", padx=CARD_PAD, pady=(0, CARD_PAD))
        self._rebuild_position_pay_rows()
        self.refresh_position_pay_rates()

    def _rebuild_position_pay_rows(self):
        if not hasattr(self, "_position_pay_scroll"):
            return
        for w in self._position_pay_scroll.winfo_children():
            w.destroy()
        self._position_pay_rows = {}
        basis_values = [POSITION_PAY_BASIS_LABELS[k] for k in ("hourly", "monthly", "yearly")]
        for title in get_officer_title_options():
            row = ctk.CTkFrame(self._position_pay_scroll, fg_color=UI_SURFACE, corner_radius=8)
            row.pack(fill="x", pady=2)
            inner = ctk.CTkFrame(row, fg_color="transparent")
            inner.pack(fill="x", padx=10, pady=8)
            if title in YEARLY_SALARY_TITLES:
                title_text = f"{title} (yr)"
            elif title not in get_builtin_officer_titles():
                title_text = f"{title} *"
            else:
                title_text = title
            ctk.CTkLabel(inner, text=title_text, width=120, anchor="w", font=font("body")).grid(
                row=0,
                column=0,
                padx=2,
                sticky="w",
            )
            amount = ctk.CTkEntry(inner, width=90, height=30)
            amount.grid(row=0, column=1, padx=2)
            basis = ctk.CTkComboBox(inner, values=basis_values, width=80, height=30)
            basis.grid(row=0, column=2, padx=2)
            default_basis = "yearly" if title in YEARLY_SALARY_TITLES else "monthly"
            basis.set(POSITION_PAY_BASIS_LABELS[default_basis])
            annual_hours = ctk.CTkEntry(inner, width=70, height=30)
            annual_hours.grid(row=0, column=3, padx=2)
            salary = ctk.CTkCheckBox(inner, text="", width=50)
            salary.grid(row=0, column=4, padx=2)
            if title in YEARLY_SALARY_TITLES:
                salary.select()
            equiv = ctk.CTkLabel(
                inner,
                text="—",
                width=80,
                anchor="w",
                font=font("small"),
                text_color=UI_TEXT_MUTED,
            )
            equiv.grid(row=0, column=5, padx=2, sticky="w")
            per_period = ctk.CTkLabel(
                inner,
                text="—",
                width=90,
                anchor="w",
                font=font("small"),
                text_color=UI_TEXT_MUTED,
            )
            per_period.grid(row=0, column=6, padx=2, sticky="w")
            self._position_pay_rows[title] = {
                "amount": amount,
                "basis": basis,
                "annual_hours": annual_hours,
                "salary": salary,
                "equiv": equiv,
                "per_period": per_period,
            }
            amount.bind("<KeyRelease>", lambda _e, t=title: self._update_position_pay_equiv(t))
            annual_hours.bind("<KeyRelease>", lambda _e, t=title: self._update_position_pay_equiv(t))
            basis.configure(command=lambda _v, t=title: self._update_position_pay_equiv(t))

    def _add_position_pay_title(self):
        if not self.can("payroll.edit"):
            return
        dialog = ctk.CTkInputDialog(text="New roster title:", title="Add Title")
        title = (dialog.get_input() or "").strip()
        if not title:
            return
        uid = self.current_user.get("id") if self.current_user else None
        result = add_custom_officer_title(title, user_id=uid)
        if not result.get("success"):
            messagebox.showerror("Add Title", result.get("message", "Failed"))
            return
        self._rebuild_position_pay_rows()
        self.refresh_position_pay_rates()
        messagebox.showinfo("Add Title", result.get("message", "Title added"))
        self.set_status(f"Title added: {result.get('title')}")

    def refresh_position_pay_rates(self):
        if not hasattr(self, "_position_pay_rows"):
            return
        data = get_position_pay_rates()
        rates = data.get("rates") or {}
        for title, widgets in self._position_pay_rows.items():
            entry = rates.get(title) or {}
            widgets["amount"].delete(0, "end")
            widgets["amount"].insert(0, str(entry.get("amount") or ""))
            basis_key = entry.get("pay_basis") or "hourly"
            widgets["basis"].set(POSITION_PAY_BASIS_LABELS.get(basis_key, "Hourly"))
            if entry.get("is_salary"):
                widgets["salary"].select()
            else:
                widgets["salary"].deselect()
            from validators import default_annual_hours_for_title

            widgets["annual_hours"].delete(0, "end")
            widgets["annual_hours"].insert(
                0,
                str(int(entry.get("annual_hours") or default_annual_hours_for_title(title))),
            )
            self._update_position_pay_equiv(title)

    def _collect_position_pay_rates(self) -> dict:
        payload = {}
        for title, widgets in self._position_pay_rows.items():
            amount_text = widgets["amount"].get().strip()
            try:
                amount = float(amount_text) if amount_text else 0.0
            except ValueError:
                amount = -1
            hours_text = widgets["annual_hours"].get().strip()
            try:
                annual_hours = float(hours_text) if hours_text else 0.0
            except ValueError:
                annual_hours = -1
            payload[title] = {
                "amount": amount,
                "pay_basis": normalize_position_pay_basis(widgets["basis"].get()),
                "is_salary": bool(widgets["salary"].get()),
                "annual_hours": annual_hours,
            }
        return payload

    def _update_position_pay_equiv(self, title: str):
        from logic.payroll import monthly_pay_to_per_pay_period
        from validators import default_annual_hours_for_title, position_amount_to_monthly

        widgets = self._position_pay_rows.get(title)
        if not widgets:
            return
        try:
            amount = float(widgets["amount"].get().strip() or "0")
        except ValueError:
            widgets["equiv"].configure(text="Invalid")
            widgets["per_period"].configure(text="—")
            return
        hours_text = widgets["annual_hours"].get().strip()
        try:
            annual_hours = float(hours_text) if hours_text else default_annual_hours_for_title(title)
        except ValueError:
            widgets["equiv"].configure(text="Invalid hrs")
            widgets["per_period"].configure(text="—")
            return
        basis = normalize_position_pay_basis(widgets["basis"].get())
        hourly = position_amount_to_hourly(amount, basis, annual_hours)
        monthly = position_amount_to_monthly(amount, basis, annual_hours)
        per_period = monthly_pay_to_per_pay_period(monthly)
        salary_tag = " · Sal" if widgets["salary"].get() else ""
        widgets["equiv"].configure(text=f"${hourly:.2f}{salary_tag}")
        widgets["per_period"].configure(text=f"${per_period:,.0f}")

    def _save_position_pay_rates(self):
        if not self.can("payroll.edit"):
            return
        payload = self._collect_position_pay_rates()
        uid = self.current_user.get("id") if self.current_user else None
        result = save_position_pay_rates(payload, user_id=uid)
        if result.get("success"):
            messagebox.showinfo("Position Pay", result.get("message", "Rates saved"))
            self.refresh_position_pay_rates()
            self.set_status("Position pay rates saved")
            if messagebox.askyesno(
                "Apply to Roster",
                "Apply updated hourly base rates to all officers by title now?",
            ):
                self._apply_position_pay_rates()
        else:
            messagebox.showerror("Save Failed", result.get("message", "Unknown error"))

    def _apply_position_pay_rates(self):
        if not self.can("payroll.edit"):
            return
        if not messagebox.askyesno(
            "Apply Position Rates",
            "Update every officer's hourly pay rate from their title's configured compensation?",
        ):
            return
        uid = self.current_user.get("id") if self.current_user else None
        result = apply_position_pay_rates_to_roster(user_id=uid)
        if result.get("success"):
            messagebox.showinfo("Apply Rates", result.get("message", "Rates applied"))
            self._refresh_payroll_officer_dropdown()
            self._on_pay_officer_change()
            self.set_status(result.get("message", "Position rates applied"))
        else:
            messagebox.showerror("Apply Failed", result.get("message", "Unknown error"))

    def _build_pay_code_rules_card(self, page):
        card = Card(page)
        card.grid(row=3, column=0, sticky="ew", pady=(0, 10))
        self._mount_pay_code_rules_panel(card.body)

    def _mount_pay_code_rules_panel(self, parent):
        hdr = ctk.CTkFrame(parent, fg_color="transparent")
        hdr.pack(fill="x", padx=CARD_PAD, pady=(CARD_PAD, 8))
        SectionHeader(
            hdr,
            "Pay Code Calculations",
            "Base pay comes from each officer's rate (or Position Pay Rates above) · formulas use hours × base rate × multiplier",
        ).pack(side="left", fill="x", expand=True)
        ctk.CTkButton(
            hdr,
            text="Save Formulas",
            width=110,
            height=30,
            fg_color=DODGEVILLE_SUCCESS,
            command=self._save_pay_code_rules,
        ).pack(side="right")

        global_row = ctk.CTkFrame(parent, fg_color=UI_SURFACE, corner_radius=8)
        global_row.pack(fill="x", padx=CARD_PAD, pady=(0, 6))
        global_inner = ctk.CTkFrame(global_row, fg_color="transparent")
        global_inner.pack(fill="x", padx=10, pady=8)
        ctk.CTkLabel(
            global_inner,
            text="Callback minimum (hrs)",
            font=font("small"),
            text_color=UI_TEXT_MUTED,
        ).grid(row=0, column=0, padx=(0, 8), sticky="w")
        self._pay_code_callback_min = ctk.CTkEntry(global_inner, width=70, height=30)
        self._pay_code_callback_min.grid(row=0, column=1, padx=(0, 16))
        ctk.CTkLabel(
            global_inner,
            text="Default OT multiplier",
            font=font("small"),
            text_color=UI_TEXT_MUTED,
        ).grid(row=0, column=2, padx=(0, 8), sticky="w")
        self._pay_code_default_ot = ctk.CTkEntry(global_inner, width=70, height=30)
        self._pay_code_default_ot.grid(row=0, column=3)

        table_hdr = ctk.CTkFrame(parent, fg_color=UI_SURFACE, corner_radius=8)
        table_hdr.pack(fill="x", padx=CARD_PAD, pady=(0, 4))
        inner_hdr = ctk.CTkFrame(table_hdr, fg_color="transparent")
        inner_hdr.pack(fill="x", padx=10, pady=8)
        for col, (text, width) in enumerate(
            [
                ("Pay Code", 150),
                ("Formula", 220),
                ("× Base", 70),
                ("Comp +", 70),
                ("Premium", 70),
                ("Paid", 50),
            ]
        ):
            ctk.CTkLabel(
                inner_hdr,
                text=text,
                width=width,
                anchor="w",
                font=font("small"),
                text_color=UI_TEXT_MUTED,
            ).grid(row=0, column=col, padx=2, sticky="w")

        scroll = ctk.CTkScrollableFrame(parent, fg_color="transparent", height=240)
        scroll.pack(fill="x", padx=CARD_PAD, pady=(0, CARD_PAD))
        self._pay_code_rows = {}
        for entry_type in TIMECARD_ENTRY_TYPES:
            row = ctk.CTkFrame(scroll, fg_color=UI_SURFACE, corner_radius=8)
            row.pack(fill="x", pady=2)
            inner = ctk.CTkFrame(row, fg_color="transparent")
            inner.pack(fill="x", padx=10, pady=8)
            ctk.CTkLabel(inner, text=entry_type, width=150, anchor="w", font=font("body")).grid(
                row=0, column=0, padx=2, sticky="w"
            )
            formula_lbl = ctk.CTkLabel(
                inner,
                text="—",
                width=220,
                anchor="w",
                font=font("small"),
                text_color=UI_TEXT_MUTED,
            )
            formula_lbl.grid(row=0, column=1, padx=2, sticky="w")
            multiplier = ctk.CTkEntry(inner, width=70, height=30)
            multiplier.grid(row=0, column=2, padx=2)
            comp_ratio = ctk.CTkEntry(inner, width=70, height=30)
            comp_ratio.grid(row=0, column=3, padx=2)
            premium = ctk.CTkEntry(inner, width=70, height=30)
            premium.grid(row=0, column=4, padx=2)
            paid = ctk.CTkCheckBox(inner, text="", width=50)
            paid.grid(row=0, column=5, padx=2)
            self._pay_code_rows[entry_type] = {
                "multiplier": multiplier,
                "comp_ratio": comp_ratio,
                "premium": premium,
                "paid": paid,
                "formula": formula_lbl,
            }
            for widget in (multiplier, comp_ratio, premium, paid):
                if hasattr(widget, "configure"):
                    widget.bind(
                        "<KeyRelease>",
                        lambda _e, code=entry_type: self._update_pay_code_formula_preview(code),
                    )
            paid.configure(command=lambda _v, code=entry_type: self._update_pay_code_formula_preview(code))
        self.refresh_pay_code_rules()

    def refresh_pay_code_rules(self):
        if not hasattr(self, "_pay_code_rows"):
            return
        data = get_pay_code_rules()
        global_cfg = data.get("global") or {}
        if hasattr(self, "_pay_code_callback_min"):
            self._pay_code_callback_min.delete(0, "end")
            self._pay_code_callback_min.insert(0, str(global_cfg.get("callback_minimum_hours", 2.0)))
            self._pay_code_default_ot.delete(0, "end")
            self._pay_code_default_ot.insert(0, str(global_cfg.get("default_overtime_multiplier", 1.5)))
        for entry_type, widgets in self._pay_code_rows.items():
            rule = data.get("codes", {}).get(entry_type, {})
            widgets["multiplier"].delete(0, "end")
            widgets["multiplier"].insert(0, str(rule.get("rate_multiplier", 1.0)))
            widgets["comp_ratio"].delete(0, "end")
            widgets["comp_ratio"].insert(0, str(rule.get("comp_bank_credit_ratio", 0.0) or 0.0))
            widgets["premium"].delete(0, "end")
            widgets["premium"].insert(0, str(rule.get("premium_multiplier", 0.0) or 0.0))
            if rule.get("paid", True):
                widgets["paid"].select()
            else:
                widgets["paid"].deselect()
            widgets["premium"].configure(state="normal" if entry_type == "Holiday Overtime" else "disabled")
            self._update_pay_code_formula_preview(entry_type)

    def _update_pay_code_formula_preview(self, entry_type: str):
        widgets = self._pay_code_rows.get(entry_type)
        if not widgets:
            return
        from validators import format_pay_code_formula

        try:
            rate_mult = float(widgets["multiplier"].get().strip() or "0")
            comp_ratio = float(widgets["comp_ratio"].get().strip() or "0")
            premium = float(widgets["premium"].get().strip() or "0")
        except ValueError:
            widgets["formula"].configure(text="Invalid number")
            return
        rule = {
            "paid": bool(widgets["paid"].get()),
            "rate_multiplier": rate_mult,
            "comp_bank_credit_ratio": comp_ratio,
            "premium_multiplier": premium,
            "uses_callback_minimum": entry_type == "Callback",
            "counts_as_overtime": entry_type in ("Overtime Earned", "Holiday Pay", "Holiday Overtime"),
        }
        widgets["formula"].configure(text=format_pay_code_formula(entry_type, rule))

    def _collect_pay_code_rules(self) -> dict:
        payload = {"global": {}, "codes": {}}
        if hasattr(self, "_pay_code_callback_min"):
            payload["global"]["callback_minimum_hours"] = self._pay_code_callback_min.get().strip()
            payload["global"]["default_overtime_multiplier"] = self._pay_code_default_ot.get().strip()
        for entry_type, widgets in self._pay_code_rows.items():
            payload["codes"][entry_type] = {
                "rate_multiplier": widgets["multiplier"].get().strip(),
                "comp_bank_credit_ratio": widgets["comp_ratio"].get().strip(),
                "premium_multiplier": widgets["premium"].get().strip(),
                "paid": bool(widgets["paid"].get()),
            }
        return payload

    def _save_pay_code_rules(self):
        if not self.can("payroll.edit"):
            return
        uid = self.current_user.get("id") if self.current_user else None
        result = save_pay_code_rules(self._collect_pay_code_rules(), user_id=uid)
        if result.get("success"):
            messagebox.showinfo("Pay Codes", result.get("message", "Saved"))
            self.refresh_pay_code_rules()
            self.set_status("Pay code calculations saved")
        else:
            messagebox.showerror("Save Failed", result.get("message", "Unknown error"))

    def _payroll_view_period(self) -> Tuple[date, date]:
        if self._payroll_period_start:
            return get_pay_period(self._payroll_period_start)
        return get_pay_period()

    def _payroll_stub_officer_id(self) -> Optional[int]:
        if self._is_officer_role():
            return self._linked_officer_id()
        officer = self._get_selected_pay_officer() if hasattr(self, "pay_officer") else None
        return officer["id"] if officer else None

    def _preview_payroll_stub(self):
        oid = self._payroll_stub_officer_id()
        if not oid:
            messagebox.showwarning("Pay Stub", "Select an officer first.")
            return
        p_start, _ = self._payroll_view_period()
        stub = get_pay_stub_preview(oid, p_start)
        if not stub.get("success"):
            if hasattr(self, "pay_stub_preview"):
                self.pay_stub_preview.configure(text=stub.get("message", "Unavailable"))
            return
        o = stub["officer"]
        salary_note = ""
        if stub.get("scheduled_per_period_salary"):
            salary_note = f"  ·  Scheduled salary ${stub['scheduled_per_period_salary']:,.2f}/period"
        if stub.get("monthly_pay"):
            salary_note += f"  (${stub['monthly_pay']:,.0f}/mo)"
        text = (
            f"Pay stub for {o['name']}: {format_date(stub['period_start'])} to {format_date(stub['period_end'])}  ·  "
            f"Base ${stub['hourly_rate']:.2f}/hr{salary_note}  ·  "
            f"Regular {stub['regular_hours']:.1f}h  ·  Other {stub['other_hours']:.1f}h  ·  "
            f"Gross ${stub['gross_pay']:,.2f}"
        )
        if hasattr(self, "pay_stub_preview"):
            self.pay_stub_preview.configure(text=text)
        self.set_status("Pay stub preview updated")

    def _export_payroll_stub(self):
        oid = self._payroll_stub_officer_id()
        if not oid:
            messagebox.showwarning("Pay Stub", "Select an officer first.")
            return
        p_start, _ = self._payroll_view_period()
        path = filedialog.asksaveasfilename(
            defaultextension=".pdf",
            filetypes=[("PDF", "*.pdf")],
        )
        result = export_pay_stub_pdf(oid, period_start=p_start, output_path=path or None)
        if result.get("success"):
            messagebox.showinfo("Export", f"Pay stub saved to:\n{result['path']}")
            self.set_status("Pay stub PDF exported")
        else:
            messagebox.showerror("Export Failed", result.get("message", "Export failed"))

    def _shift_payroll_period(self, direction: int):
        start, _ = self._payroll_view_period()
        next_start, _ = get_adjacent_pay_period(start, direction)
        if direction > 0 and is_future_pay_period(next_start):
            return
        self._payroll_period_start = next_start
        self._timecard_period_start = next_start
        self.refresh_payroll_period()

    def _reset_payroll_period(self):
        self._payroll_period_start = None
        self._timecard_period_start = None
        self.refresh_payroll_period()

    def _refresh_payroll_period_picker(self):
        if not hasattr(self, "pay_period_picker"):
            return
        officer_id = self._linked_officer_id() if self._is_officer_role() else None
        catalog = list_pay_periods_catalog(officer_id)
        labels = []
        self._pay_period_pick_map = {}
        for row in catalog.get("periods", []):
            hours_note = f" · {row['total_hours']:.1f}h" if row.get("has_data") else ""
            current_note = " · current" if row.get("is_current") else ""
            label = f"{row['label']}{hours_note}{current_note}"
            labels.append(label)
            self._pay_period_pick_map[label] = row["period_start"]
        if not labels:
            labels = ["No pay periods"]
        self.pay_period_picker.configure(values=labels)
        period_start, _ = self._payroll_view_period()
        match = next(
            (lbl for lbl, ps in self._pay_period_pick_map.items() if ps == period_start.isoformat()),
            labels[0],
        )
        self.pay_period_picker.set(match)

    def _search_payroll_period(self):
        query = self.pay_period_search.get().strip()
        if not query:
            messagebox.showwarning("Search", f"Enter a shift-start date ({DATE_INPUT_HINT}).")
            return
        result = search_pay_period_by_date(query)
        if not result.get("success"):
            messagebox.showerror("Search", result.get("message", "Not found"))
            return
        from validators import parse_date

        self._payroll_period_start = parse_date(result["period_start"])
        self._timecard_period_start = self._payroll_period_start
        self.refresh_payroll_period()
        self.set_status(f"Showing pay period {result['label']}")

    def _pick_payroll_period(self, selection: str):
        period_start = getattr(self, "_pay_period_pick_map", {}).get(selection)
        if not period_start:
            return
        from validators import parse_date

        self._payroll_period_start = parse_date(period_start)
        self._timecard_period_start = self._payroll_period_start
        self.refresh_payroll_period()

    def _populate_pay_period_hours_details(self, parent, summary: dict):
        for child in parent.winfo_children():
            child.destroy()
        inner = ctk.CTkFrame(parent, fg_color="transparent")
        inner.pack(fill="x", padx=10, pady=8)
        by_type = summary.get("by_entry_type") or {}
        detail_rows = []
        flsa = summary.get("flsa") or {}
        if flsa.get("enabled") and not flsa.get("department_scope"):
            flsa_label = (
                f"FLSA §207(k) ({flsa.get('period_days', '?')}-day period "
                f"{flsa.get('period_start_display', '')} – {flsa.get('period_end_display', '')})"
            )
            detail_rows.append(
                (
                    flsa_label,
                    flsa.get("hours_worked", 0.0),
                    f"/ {flsa.get('hours_threshold', 0):.0f}h",
                )
            )
            if flsa.get("over_threshold_hours", 0) > 0:
                detail_rows.append(
                    ("FLSA overtime hours (period)", flsa.get("over_threshold_hours", 0.0), "OT due"),
                )
        detail_rows.extend(
            [
                ("Night shift differential (premium)", summary.get("night_diff_hours", 0.0), ""),
                (TIMECARD_REGULAR_TYPE, by_type.get(TIMECARD_REGULAR_TYPE, 0.0), ""),
            ]
        )
        for entry_type in PAYROLL_ENTRY_TYPES:
            detail_rows.append((entry_type, by_type.get(entry_type, 0.0), ""))
        for row_idx, row in enumerate(detail_rows):
            label, hours = row[0], row[1]
            suffix = row[2] if len(row) > 2 else ""
            ctk.CTkLabel(
                inner,
                text=label,
                font=font("small"),
                text_color=UI_TEXT_MUTED,
                anchor="w",
            ).grid(row=row_idx, column=0, sticky="w", padx=(0, 16), pady=2)
            value = f"{hours:.1f}h"
            if suffix:
                value = f"{value} {suffix}"
            ctk.CTkLabel(
                inner,
                text=value,
                font=font("small"),
                anchor="e",
            ).grid(row=row_idx, column=1, sticky="e", pady=2)
        inner.grid_columnconfigure(0, weight=1)

    def _toggle_pay_period_lock(self):
        uid = self.current_user.get("id") if self.current_user else None
        p_start, _ = self._payroll_view_period()
        if not is_current_pay_period(p_start):
            messagebox.showwarning(
                "Pay Period",
                "Return to the current pay period before locking or unlocking.",
            )
            return
        if is_pay_period_locked(p_start):
            result = unlock_pay_period(user_id=uid)
            action = "unlocked"
        else:
            result = lock_pay_period(p_start, user_id=uid)
            action = "locked"
        if result.get("success"):
            self.set_status(f"Pay period {action}")
            self.refresh_payroll_period()
        else:
            messagebox.showerror("Lock", result.get("message", "Failed"))

    def refresh_payroll_period(self):
        if not hasattr(self, "pay_period_scroll"):
            return
        p_start, p_end = self._payroll_view_period()
        viewing_current = is_current_pay_period(p_start)
        locked = is_pay_period_locked(p_start)
        if hasattr(self, "_pay_period_header"):
            lock_note = "  ·  LOCKED" if locked else ""
            hist_note = "" if viewing_current else "  ·  past period"
            self._pay_period_header.configure(
                subtitle=(f"{format_pay_period_label(p_start, p_end)}  ·  timecard summary{lock_note}{hist_note}"),
            )
        self._refresh_payroll_period_picker()
        if hasattr(self, "_pay_period_next_btn"):
            next_start, _ = get_adjacent_pay_period(p_start, 1)
            state = "disabled" if is_future_pay_period(next_start) else "normal"
            self._pay_period_next_btn.configure(state=state)
        if hasattr(self, "_pay_lock_btn") and self.can("payroll.lock_period"):
            if viewing_current:
                self._pay_lock_btn.configure(state="normal")
                self._pay_lock_btn.configure(
                    text="Unlock Period" if locked else "Lock Period",
                    fg_color=DODGEVILLE_DANGER if locked else DODGEVILLE_WARNING,
                )
            else:
                self._pay_lock_btn.configure(state="disabled")
        for w in self.pay_period_scroll.winfo_children():
            w.destroy()
        data = get_payroll_period_timesheets(p_start)
        if not data.get("success"):
            return
        if self._is_officer_role():
            oid = self._linked_officer_id()
            if oid:
                data["sheets"] = [s for s in data.get("sheets", []) if s["officer"]["id"] == oid]
                data["grand_total_hours"] = sum(s["total_hours"] for s in data["sheets"])
                data["grand_total_pay"] = sum(s["total_pay"] for s in data["sheets"])

        summary_officer_id = None
        if self._is_officer_role():
            summary_officer_id = self._linked_officer_id()
        hours_summary = get_pay_period_hours_summary(p_start, officer_id=summary_officer_id)
        dept = get_department_pay_summary() if not self._is_officer_role() else None
        totals = ctk.CTkFrame(self.pay_period_scroll, fg_color=UI_SURFACE, corner_radius=8)
        totals.pack(fill="x", pady=(0, 8))
        totals_inner = ctk.CTkFrame(totals, fg_color="transparent")
        totals_inner.pack(fill="x", padx=12, pady=10)
        label = "My pay period" if self._is_officer_role() else "Department pay period"
        total_hours = hours_summary.get("total_hours", data["grand_total_hours"])
        ctk.CTkLabel(
            totals_inner,
            text=f"{total_hours:.1f} hours",
            font=font("stat_value"),
            text_color=DODGEVILLE_ACCENT,
            anchor="w",
        ).pack(fill="x")
        ctk.CTkLabel(
            totals_inner,
            text=f"{label} total",
            font=font("small"),
            text_color=UI_TEXT_MUTED,
            anchor="w",
        ).pack(fill="x", pady=(0, 6))
        pay_line = f"${data['grand_total_pay']:,.2f} period pay"
        if dept and dept.get("success"):
            pay_line += f"  ·  Projected annual payroll ${dept['department_annual_total']:,.0f}"
        ctk.CTkLabel(
            totals_inner,
            text=pay_line,
            font=font("subheading"),
            wraplength=900,
            anchor="w",
        ).pack(fill="x")
        details = ExpandableSection(totals_inner, title="More Details")
        details.pack(fill="x", pady=(8, 0))
        self._populate_pay_period_hours_details(details.body, hours_summary)

        for sheet in data["sheets"]:
            card = ctk.CTkFrame(self.pay_period_scroll, fg_color=UI_SURFACE, corner_radius=8)
            card.pack(fill="x", pady=4)
            inner = ctk.CTkFrame(card, fg_color="transparent")
            inner.pack(fill="x", padx=12, pady=10)
            officer = sheet["officer"]
            ctk.CTkLabel(
                inner,
                text=officer["name"],
                font=font("subheading"),
                anchor="w",
            ).pack(fill="x")
            detail = f"Timecard: {sheet['total_hours']:.1f}h  ·  Payroll: ${sheet['total_pay']:,.2f}"
            proj = project_officer_annual_pay(officer["id"])
            if proj.get("success"):
                detail += (
                    f"  ·  ${proj['monthly_pay']:,.0f}/mo"
                    f"  ·  ${proj['per_pay_period_salary']:,.0f}/period"
                    f"  ·  ${proj['annual_salary']:,.0f}/yr"
                )
            ctk.CTkLabel(
                inner,
                text=detail,
                font=font("small"),
                text_color=UI_TEXT_MUTED,
                anchor="w",
            ).pack(fill="x")
            if sheet["timecard_rows"]:
                max_rows = 3
                rows = sheet["timecard_rows"]
                for row in rows[:max_rows]:
                    line = (
                        f"  {format_date(row['entry_date'])}  {row.get('hours_worked', 0):.1f}h  "
                        f"{row.get('entry_type', '')}"
                    )
                    if row.get("payroll_entry_id"):
                        line += "  ✓ payroll"
                    ctk.CTkLabel(inner, text=line, font=font("small"), anchor="w").pack(fill="x")
                extra = len(rows) - max_rows
                if extra > 0:
                    ctk.CTkLabel(
                        inner,
                        text=f"  +{extra} more entries",
                        font=font("small"),
                        text_color=UI_TEXT_MUTED,
                        anchor="w",
                    ).pack(fill="x")
            else:
                ctk.CTkLabel(
                    inner,
                    text="No timecard entries this period",
                    font=font("small"),
                    text_color=UI_TEXT_MUTED,
                    anchor="w",
                ).pack(fill="x", padx=8)
        if hasattr(self, "pay_stub_preview") and self._payroll_stub_officer_id():
            self._preview_payroll_stub()
        self._refresh_pay_period_history()

    def _refresh_pay_period_history(self):
        if not hasattr(self, "pay_history_frame"):
            return
        for w in self.pay_history_frame.winfo_children():
            w.destroy()
        officer_id = self._linked_officer_id() if self._is_officer_role() else None
        data = get_pay_period_history(6, officer_id=officer_id)
        if not data.get("periods"):
            ctk.CTkLabel(
                self.pay_history_frame,
                text="No timecard data yet.",
                font=font("small"),
                text_color=UI_TEXT_MUTED,
            ).pack(anchor="w")
            return
        for period in data["periods"]:
            p_start = period["period_start"]
            p_end = period["period_end"]
            lock_tag = "  · locked" if period.get("locked") else ""
            row = ctk.CTkFrame(self.pay_history_frame, fg_color=UI_SURFACE, corner_radius=6)
            row.pack(fill="x", pady=2)
            inner = ctk.CTkFrame(row, fg_color="transparent")
            inner.pack(fill="x", padx=8, pady=6)
            ctk.CTkLabel(
                inner,
                text=(
                    f"{format_date(p_start)} – {format_date(p_end)}  ·  {period['total_hours']:.1f}h  ·  "
                    f"${period['total_pay']:,.2f}{lock_tag}"
                ),
                font=font("small"),
                anchor="w",
            ).pack(side="left", fill="x", expand=True)
            ctk.CTkButton(
                inner,
                text="Timecard",
                width=72,
                height=26,
                fg_color=UI_BORDER,
                command=lambda ps=p_start: self._jump_to_timecard_period(ps),
            ).pack(side="right", padx=(4, 0))
            ctk.CTkButton(
                inner,
                text="Payroll",
                width=72,
                height=26,
                fg_color=DODGEVILLE_ACCENT,
                command=lambda ps=p_start: self._jump_to_payroll_period(ps),
            ).pack(side="right")

    def _refresh_payroll_officer_dropdown(self):
        officers = [o for o in get_officers_by_seniority() if o.get("active") == 1]
        if self._is_officer_role():
            oid = self._linked_officer_id()
            officers = [o for o in officers if o["id"] == oid] if oid else []
        labels = [f"{o['name']}  ·  ${o['pay_rate']:.2f}/hr" for o in officers]
        self.pay_officer_map = {lbl: o for lbl, o in zip(labels, officers)}
        self.pay_officer.configure(values=labels or ["No officers"])
        if hasattr(self, "pay_filter"):
            if self._is_officer_role() and labels:
                self.pay_filter.configure(values=labels)
                self.pay_filter.set(labels[0])
            else:
                filter_vals = ["All Officers"] + labels
                self.pay_filter.configure(values=filter_vals)
                self.pay_filter.set("All Officers")
        if labels:
            self.pay_officer.set(labels[0])
        self._refresh_pay_banks()

    def _on_pay_type_change(self, _value=None):
        entry_type = self.pay_type.get()
        show_holiday_ot = entry_type == "Holiday Overtime"
        if show_holiday_ot:
            rules = get_pay_code_rules().get("codes", {}).get("Holiday Overtime", {})
            premium = rules.get("premium_multiplier") or 3.0
            self.pay_holiday_ot.configure(text=f"Holiday Overtime (premium × {premium})")
            self.pay_holiday_ot.pack(anchor="w", pady=8)
        else:
            self.pay_holiday_ot.pack_forget()
            self.pay_holiday_ot.deselect()
        if hasattr(self, "pay_formula_hint"):
            rule = get_pay_code_rules().get("codes", {}).get(entry_type, {})
            formula = rule.get("formula") or "—"
            self.pay_formula_hint.configure(text=f"Formula: {formula}")

    def _on_pay_officer_change(self, _value=None):
        self._refresh_pay_banks()
        self._refresh_pay_position_rate()

    def _refresh_pay_position_rate(self):
        if not hasattr(self, "pay_position_rate"):
            return
        officer = self._get_selected_pay_officer()
        if not officer:
            self.pay_position_rate.configure(text="Position rate: not set")
            return
        title = format_officer_title_display(officer.get("job_title"))
        if not title:
            self.pay_position_rate.configure(
                text=f"Officer rate: ${officer.get('pay_rate', 0):.2f}/hr (no title assigned)",
            )
            return
        data = get_position_pay_rates()
        config = (data.get("rates") or {}).get(title)
        if config:
            self.pay_position_rate.configure(
                text=f"Position ({title}): {format_position_pay_summary(config)}",
            )
        else:
            self.pay_position_rate.configure(
                text=f"Position ({title}): not configured  ·  Officer rate ${officer.get('pay_rate', 0):.2f}/hr",
            )

    def _refresh_pay_banks(self):
        if not hasattr(self, "pay_banks"):
            return
        officer = self._get_selected_pay_officer()
        if not officer:
            self.pay_banks.configure(text="Time banks: not set")
            if hasattr(self, "pay_position_rate"):
                self.pay_position_rate.configure(text="Position rate: not set")
            return
        entry_date = self.pay_date.get().strip() if hasattr(self, "pay_date") else ""
        try:
            as_of = parse_date(entry_date)
        except ValueError:
            as_of = date.today()
        banks = get_officer_time_banks(officer["id"], as_of)
        if not banks.get("success"):
            self.pay_banks.configure(text="Time banks: unavailable")
            return
        self.pay_banks.configure(
            text=(
                f"Time banks: Comp {banks['comp_hours']:.1f}h  ·  "
                f"Sick {banks['sick_hours']:.1f}h  ·  "
                f"Float {banks['float_holiday_hours']:.1f}h  ·  "
                f"Holiday {banks['holiday_hours']:.1f}h"
            )
        )

    def _get_selected_pay_officer(self):
        return self.pay_officer_map.get(self.pay_officer.get())

    def preview_payroll(self):
        officer = self._get_selected_pay_officer()
        if not officer:
            return
        try:
            hours = float(self.pay_hours.get().strip() or "0")
            night_h = float(self.pay_night_hours.get().strip() or "0")
        except ValueError:
            messagebox.showerror("Validation", "Hours must be numeric.")
            return
        entry_date = self.pay_date.get().strip()
        try:
            as_of = parse_date(entry_date)
        except ValueError:
            messagebox.showerror("Validation", f"Entry date must be {DATE_INPUT_HINT}.")
            return
        banks_data = get_officer_time_banks(officer["id"], as_of)
        banks = banks_data if banks_data.get("success") else {}
        calc = calculate_pay_for_entry(
            self.pay_type.get(),
            hours,
            officer["pay_rate"],
            night_differential_hours=night_h,
            night_differential_rate=officer.get("night_differential_rate", 1.0),
            is_holiday_overtime=bool(self.pay_holiday_ot.get()),
            banks=banks,
        )
        self._pay_preview_calc = calc
        if calc.message:
            self.pay_preview.configure(text=calc.message)
            return
        bank_note = ""
        deltas = []
        if calc.comp_bank_delta:
            deltas.append(f"comp {calc.comp_bank_delta:+.1f}h")
        if calc.sick_bank_delta:
            deltas.append(f"sick {calc.sick_bank_delta:+.1f}h")
        if calc.float_holiday_bank_delta:
            deltas.append(f"float {calc.float_holiday_bank_delta:+.1f}h")
        if calc.holiday_bank_delta:
            deltas.append(f"holiday {calc.holiday_bank_delta:+.1f}h")
        if deltas:
            bank_note = f"  |  Bank: {', '.join(deltas)}"
        self.pay_preview.configure(
            text=(
                f"Estimated pay: ${calc.total_pay:,.2f}  "
                f"(base ${calc.base_pay:.2f} + OT ${calc.overtime_pay:.2f} + night ${calc.night_differential_pay:.2f})"
                f"{bank_note}"
            )
        )

    def save_payroll_entry(self):
        officer = self._get_selected_pay_officer()
        if not officer:
            messagebox.showerror("Error", "Select an officer.")
            return
        entry_date = self.pay_date.get().strip()
        try:
            parse_date(entry_date)
            hours = float(self.pay_hours.get().strip())
            night_h = float(self.pay_night_hours.get().strip() or "0")
        except ValueError:
            messagebox.showerror("Validation", f"Check date ({DATE_INPUT_HINT}) and hours.")
            return
        result = create_payroll_entry(
            officer["id"],
            entry_date,
            self.pay_type.get(),
            hours,
            night_differential_hours=night_h,
            notes=self.pay_notes.get().strip(),
            is_holiday_overtime=bool(self.pay_holiday_ot.get()),
        )
        if result.get("success"):
            self.pay_notes.delete(0, "end")
            self.pay_hours.delete(0, "end")
            self.pay_hours.insert(0, "")
            self.pay_preview.configure(text=f"Saved: ${result['calculated_pay']:,.2f}")
            self._refresh_pay_banks()
            self.refresh_payroll()
            self.set_status(f"Payroll entry #{result['entry_id']} saved")
        else:
            messagebox.showerror("Error", result.get("message", "Save failed."))

    def _create_payroll_row(self, entry):
        row = ctk.CTkFrame(self.payroll_list, fg_color=UI_SURFACE, corner_radius=8)
        inner = ctk.CTkFrame(row, fg_color="transparent")
        inner.pack(fill="x", padx=12, pady=10)
        name_label = ctk.CTkLabel(inner, text=entry["officer_name"], font=font("subheading"), anchor="w")
        name_label.pack(fill="x")
        detail_label = ctk.CTkLabel(inner, text="", font=font("small"), text_color=UI_TEXT_MUTED, anchor="w")
        detail_label.pack(fill="x")
        notes_label = ctk.CTkLabel(inner, text="", font=font("small"), anchor="w")
        notes_label.pack(fill="x", pady=(2, 0))
        row._payroll_labels = {"name": name_label, "detail": detail_label, "notes": notes_label}
        self._update_payroll_row(row, entry)
        return row

    def _update_payroll_row(self, row, entry):
        labels = row._payroll_labels
        labels["name"].configure(text=entry["officer_name"])
        detail = (
            f"{format_date(entry['entry_date'])}  ·  {entry['entry_type']}  ·  "
            f"{entry['hours']}h  ·  ${entry['calculated_pay']:,.2f}"
        )
        if entry.get("night_differential_hours"):
            detail += f"  ·  night {entry['night_differential_hours']}h"
        bank_parts = []
        for key, label in [
            ("comp_bank_delta", "comp"),
            ("sick_bank_delta", "sick"),
            ("float_holiday_bank_delta", "float"),
            ("holiday_bank_delta", "holiday"),
        ]:
            delta = entry.get(key) or 0
            if delta:
                bank_parts.append(f"{label} {delta:+.1f}h")
        if bank_parts:
            detail += f"  ·  bank {' / '.join(bank_parts)}"
        labels["detail"].configure(text=detail)
        notes = entry.get("notes") or ""
        labels["notes"].configure(text=notes)
        if notes:
            labels["notes"].pack(fill="x", pady=(2, 0))
        else:
            labels["notes"].pack_forget()

    def refresh_payroll(self):
        if hasattr(self, "pay_period_scroll"):
            self.refresh_payroll_period()
        if not hasattr(self, "payroll_list"):
            return
        p_start, _ = self._payroll_view_period()
        officer_id = None
        if self._is_officer_role():
            officer_id = self._linked_officer_id()
        else:
            filt = self.pay_filter.get()
            if filt != "All Officers" and filt in self.pay_officer_map:
                officer_id = self.pay_officer_map[filt]["id"]
        entries = get_payroll_entries(
            officer_id=officer_id,
            limit=200,
            period_start=p_start,
        )
        entry_ids = {entry["id"] for entry in entries}
        filter_key = (officer_id, p_start.isoformat())

        if filter_key != getattr(self, "_payroll_filter_key", None):
            for row in self._payroll_row_widgets.values():
                row.destroy()
            self._payroll_row_widgets = {}
            for widget in self.payroll_list.winfo_children():
                widget.destroy()
            self._payroll_filter_key = filter_key

        for entry_id, row in list(self._payroll_row_widgets.items()):
            if entry_id not in entry_ids:
                row.destroy()
                del self._payroll_row_widgets[entry_id]

        for widget in self.payroll_list.winfo_children():
            if widget not in self._payroll_row_widgets.values():
                widget.destroy()

        if not entries:
            ctk.CTkLabel(
                self.payroll_list,
                text="No payroll entries yet.",
                text_color=UI_TEXT_MUTED,
                font=font("body"),
            ).pack(pady=20)
            return

        for entry in entries:
            row = self._payroll_row_widgets.get(entry["id"])
            if row is None:
                row = self._create_payroll_row(entry)
                self._payroll_row_widgets[entry["id"]] = row
            else:
                self._update_payroll_row(row, entry)
            row.pack_forget()

        for entry in entries:
            self._payroll_row_widgets[entry["id"]].pack(fill="x", pady=4)
