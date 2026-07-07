"""Officer roster CRUD, photos, and CSV import."""

from tkinter import filedialog, messagebox
from typing import Optional

import customtkinter as ctk

from config import (
    DATE_INPUT_HINT,
    OFFICER_SQUAD_OPTIONS,
    OFFICER_UNASSIGNED_LABEL,
    YEARLY_SALARY_TITLES,
)
from logic import (
    add_custom_officer_title,
    add_officer,
    bulk_adjust_pay_rates,
    delete_officer,
    get_builtin_officer_titles,
    get_officer_by_id,
    get_officer_time_banks,
    get_officer_title_options,
    get_officers_by_seniority,
    get_pay_period_hours_by_officer,
    get_suggested_seniority_rank,
    import_roster_from_csv,
    project_officer_annual_pay,
    set_officer_photo,
    suggested_hourly_rate_for_title,
    update_officer,
)
from logic import (
    remove_officer_photo as logic_remove_officer_photo,
)
from logic.staffing_config import get_active_annual_hours_target, get_officer_shift_options
from photos import load_thumbnail
from ui.helpers import refresh_all_officer_dropdowns
from ui.theme import (
    CARD_PAD,
    DODGEVILLE_ACCENT,
    DODGEVILLE_DANGER,
    DODGEVILLE_GOLD,
    DODGEVILLE_SUCCESS,
    DODGEVILLE_WARNING,
    UI_BORDER,
    UI_SURFACE,
    UI_TEXT_MUTED,
    font,
)
from ui.widgets import Card, FormField, SearchBar, SectionHeader, StatusBadge
from validators import (
    format_date,
    format_officer_shift_display,
    format_officer_squad_display,
    format_officer_title_display,
    normalize_officer_job_title,
    parse_officer_shift_ui,
)


class OfficersPageMixin:
    def _build_officers(self):
        page = self.pages["officers"]
        page.grid_columnconfigure(0, weight=2)
        page.grid_columnconfigure(1, weight=3)
        page.grid_rowconfigure(0, weight=1)

        left = Card(page)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        roster_header = ctk.CTkFrame(left.body, fg_color="transparent")
        roster_header.pack(fill="x", padx=CARD_PAD, pady=(CARD_PAD, 4))
        SectionHeader(roster_header, "Roster", "Click an officer to edit").pack(side="left")
        self.officer_roster_count = ctk.CTkLabel(
            roster_header,
            text="",
            font=font("small"),
            text_color=UI_TEXT_MUTED,
        )
        self.officer_roster_count.pack(side="right")
        search_row = ctk.CTkFrame(left.body, fg_color="transparent")
        search_row.pack(fill="x", padx=CARD_PAD, pady=(0, 8))
        self.officer_search = SearchBar(search_row, "Search by name or squad...")
        self.officer_search.pack(side="left", fill="x", expand=True)
        self.officer_search.bind("<KeyRelease>", lambda e: self.refresh_officer_list())
        self.off_show_inactive = ctk.CTkCheckBox(
            search_row,
            text="Inactive",
            font=font("small"),
            command=self.refresh_officer_list,
        )
        self.off_show_inactive.pack(side="right", padx=(8, 0))
        self.officer_list = ctk.CTkScrollableFrame(left.body, fg_color="transparent")
        self.officer_list.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        right = Card(page)
        right.grid(row=0, column=1, sticky="nsew")
        right.body.grid_rowconfigure(2, weight=1)
        right.body.grid_columnconfigure(0, weight=1)

        self._officer_form_mode = "edit"
        self._officer_picker_map = {}
        self._officer_picker_syncing = False

        pick_row = ctk.CTkFrame(right.body, fg_color="transparent")
        pick_row.grid(row=0, column=0, sticky="ew", padx=CARD_PAD, pady=(CARD_PAD, 6))
        pick_left = ctk.CTkFrame(pick_row, fg_color="transparent")
        pick_left.pack(side="left", fill="x", expand=True)
        self.off_selection_label = ctk.CTkLabel(
            pick_left,
            text="Editing: none selected",
            font=font("subheading"),
            anchor="w",
        )
        self.off_selection_label.pack(fill="x")
        ctk.CTkLabel(
            pick_left,
            text="Select from dropdown or roster. Set title, squad, and shift in the header bar.",
            font=font("small"),
            text_color=UI_TEXT_MUTED,
            anchor="w",
        ).pack(fill="x", pady=(2, 0))
        self.off_picker = ctk.CTkComboBox(
            pick_row,
            values=["—"],
            width=300,
            height=36,
            command=self._on_officer_picker,
        )
        self.off_picker.pack(side="right", padx=(12, 0))

        # Sticky name + save bar — always visible (not pushed off-screen)
        sticky_bar = ctk.CTkFrame(right.body, fg_color=UI_BORDER, corner_radius=8)
        sticky_bar.grid(row=1, column=0, sticky="ew", padx=CARD_PAD, pady=(0, 8))
        sticky_inner = ctk.CTkFrame(sticky_bar, fg_color="transparent")
        sticky_inner.pack(fill="x", padx=12, pady=12)
        name_col = ctk.CTkFrame(sticky_inner, fg_color="transparent")
        name_col.pack(side="left", fill="x", expand=True, padx=(0, 12))
        ctk.CTkLabel(
            name_col,
            text="Full Name",
            font=font("small"),
            text_color=UI_TEXT_MUTED,
            anchor="w",
        ).pack(fill="x", pady=(0, 4))
        self.off_name = ctk.CTkEntry(
            name_col,
            height=40,
            border_width=2,
            border_color=DODGEVILLE_GOLD,
        )
        self.off_name.pack(fill="x")
        ctk.CTkLabel(
            name_col,
            text="Title",
            font=font("small"),
            text_color=UI_TEXT_MUTED,
            anchor="w",
        ).pack(fill="x", pady=(8, 4))
        builtin = get_builtin_officer_titles()
        self._job_title_var = ctk.StringVar(value=builtin[0])
        self.off_job_title = ctk.CTkComboBox(
            name_col,
            values=get_officer_title_options(),
            height=36,
            variable=self._job_title_var,
            state="readonly",
            command=self._on_job_title_selected,
        )
        self.off_job_title.pack(fill="x")
        if self.can("officers.manage"):
            title_add_row = ctk.CTkFrame(name_col, fg_color="transparent")
            title_add_row.pack(fill="x", pady=(4, 0))
            self._new_title_entry = ctk.CTkEntry(
                title_add_row,
                height=32,
                placeholder_text="Add custom title (e.g. Administrative Assistant)",
            )
            self._new_title_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
            ctk.CTkButton(
                title_add_row,
                text="Add Title",
                width=90,
                height=32,
                fg_color=UI_BORDER,
                hover_color=DODGEVILLE_ACCENT,
                command=self._add_officer_title,
            ).pack(side="right")
        assign_row = ctk.CTkFrame(name_col, fg_color="transparent")
        assign_row.pack(fill="x", pady=(8, 0))
        assign_row.grid_columnconfigure((0, 1), weight=1)
        squad_col = ctk.CTkFrame(assign_row, fg_color="transparent")
        squad_col.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ctk.CTkLabel(
            squad_col,
            text="Squad Assignment",
            font=font("small"),
            text_color=UI_TEXT_MUTED,
            anchor="w",
        ).pack(fill="x", pady=(0, 4))
        self._squad_var = ctk.StringVar(value=OFFICER_SQUAD_OPTIONS[1])
        self.off_squad = ctk.CTkComboBox(
            squad_col,
            values=list(OFFICER_SQUAD_OPTIONS),
            height=36,
            variable=self._squad_var,
            state="readonly",
            command=self._on_squad_selected,
        )
        self.off_squad.pack(fill="x")
        shift_col = ctk.CTkFrame(assign_row, fg_color="transparent")
        shift_col.grid(row=0, column=1, sticky="ew", padx=(6, 0))
        ctk.CTkLabel(
            shift_col,
            text="Shift Assignment",
            font=font("small"),
            text_color=UI_TEXT_MUTED,
            anchor="w",
        ).pack(fill="x", pady=(0, 4))
        shift_options = get_officer_shift_options()
        self._shift_var = ctk.StringVar(value=shift_options[1] if len(shift_options) > 1 else shift_options[0])
        self.off_shift = ctk.CTkComboBox(
            shift_col,
            values=list(get_officer_shift_options()),
            height=36,
            variable=self._shift_var,
            state="readonly",
            command=self._on_shift_selected,
        )
        self.off_shift.pack(fill="x")
        save_col = ctk.CTkFrame(sticky_inner, fg_color="transparent")
        save_col.pack(side="right")
        ctk.CTkButton(
            save_col,
            text="Save Changes",
            width=140,
            height=40,
            corner_radius=8,
            fg_color=DODGEVILLE_SUCCESS,
            command=self.save_officer,
        ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            save_col,
            text="New Officer",
            width=120,
            height=40,
            corner_radius=8,
            fg_color=DODGEVILLE_ACCENT,
            command=self.new_officer_form,
        ).pack(side="left")

        form_scroll = ctk.CTkScrollableFrame(right.body, fg_color="transparent")
        form_scroll.grid(row=2, column=0, sticky="nsew", padx=CARD_PAD, pady=(0, 8))

        photo_row = ctk.CTkFrame(form_scroll, fg_color="transparent")
        photo_row.pack(fill="x", pady=(0, 8))
        self.off_photo_frame = ctk.CTkFrame(
            photo_row,
            width=120,
            height=120,
            fg_color=UI_BORDER,
            corner_radius=12,
        )
        self.off_photo_frame.pack(side="left")
        self.off_photo_frame.pack_propagate(False)
        self.off_photo_label = ctk.CTkLabel(
            self.off_photo_frame,
            text="No Photo",
            font=font("small"),
            text_color=UI_TEXT_MUTED,
        )
        self.off_photo_label.place(relx=0.5, rely=0.5, anchor="center")
        photo_btns = ctk.CTkFrame(photo_row, fg_color="transparent")
        photo_btns.pack(side="left", padx=12, fill="y")
        ctk.CTkButton(
            photo_btns,
            text="Upload Photo",
            height=32,
            corner_radius=8,
            fg_color=DODGEVILLE_ACCENT,
            command=self.upload_officer_photo,
        ).pack(anchor="w", pady=(0, 6))
        ctk.CTkButton(
            photo_btns,
            text="Remove Photo",
            height=32,
            corner_radius=8,
            fg_color=UI_BORDER,
            hover_color=DODGEVILLE_DANGER,
            command=self.remove_officer_photo,
        ).pack(anchor="w")

        self.off_seniority = FormField(
            form_scroll, "Seniority Rank (roster lookup)", lambda p: ctk.CTkEntry(p, height=36)
        ).widget
        self.off_pay = FormField(
            form_scroll,
            "Base Pay Rate ($/hr)",
            lambda p: ctk.CTkEntry(p, height=36),
        ).widget
        self.off_pay_hint = ctk.CTkLabel(
            form_scroll,
            text="Auto-filled from title monthly pay (×12÷2008) — supervisors may override",
            font=font("small"),
            text_color=UI_TEXT_MUTED,
            anchor="w",
        )
        self.off_pay_hint.pack(fill="x", pady=(0, 4))
        self.off_night_diff = FormField(
            form_scroll,
            "Night Differential ($/hr)",
            lambda p: ctk.CTkEntry(p, height=36, placeholder_text="1.0"),
        ).widget
        pay_row = ctk.CTkFrame(form_scroll, fg_color="transparent")
        pay_row.pack(fill="x", pady=4)
        pay_row.grid_columnconfigure((0, 1), weight=1)
        annual_frame = ctk.CTkFrame(pay_row, fg_color="transparent")
        annual_frame.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.off_annual_hours = FormField(
            annual_frame, "Annual Hours Target", lambda p: ctk.CTkEntry(p, height=36, placeholder_text="2008")
        ).widget
        ot_frame = ctk.CTkFrame(pay_row, fg_color="transparent")
        ot_frame.grid(row=0, column=1, sticky="ew", padx=(6, 0))
        self.off_ot_multiplier = FormField(
            ot_frame, "OT Multiplier", lambda p: ctk.CTkEntry(p, height=36, placeholder_text="1.5")
        ).widget
        self.off_pay_projection = ctk.CTkLabel(
            form_scroll,
            text="Annual pay projection: not set",
            font=font("small"),
            text_color=UI_TEXT_MUTED,
            anchor="w",
        )
        self.off_pay_projection.pack(fill="x", pady=(4, 0))

        SectionHeader(form_scroll, "Contact Information", "Start date and contact details").pack(
            fill="x",
            pady=(12, 8),
        )
        self.off_start_date = FormField(
            form_scroll,
            "Start Date",
            lambda p: ctk.CTkEntry(p, height=36, placeholder_text=DATE_INPUT_HINT),
        ).widget
        contact_row = ctk.CTkFrame(form_scroll, fg_color="transparent")
        contact_row.pack(fill="x", pady=4)
        contact_row.grid_columnconfigure((0, 1), weight=1)
        email_frame = ctk.CTkFrame(contact_row, fg_color="transparent")
        email_frame.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.off_email = FormField(
            email_frame, "Email", lambda p: ctk.CTkEntry(p, height=36, placeholder_text="name@example.com")
        ).widget
        phone_frame = ctk.CTkFrame(contact_row, fg_color="transparent")
        phone_frame.grid(row=0, column=1, sticky="ew", padx=(6, 0))
        self.off_phone = FormField(
            phone_frame, "Phone", lambda p: ctk.CTkEntry(p, height=36, placeholder_text="(608) 555-0100")
        ).widget
        addr_frame = ctk.CTkFrame(form_scroll, fg_color="transparent")
        addr_frame.pack(fill="x", pady=(4, 0))
        ctk.CTkLabel(addr_frame, text="Address", font=font("small"), text_color=UI_TEXT_MUTED, anchor="w").pack(
            fill="x", pady=(0, 4)
        )
        self.off_address = ctk.CTkTextbox(addr_frame, height=72, corner_radius=8, border_color=UI_BORDER)
        self.off_address.pack(fill="x")

        self.off_banks = ctk.CTkLabel(
            form_scroll,
            text="Time banks: not set",
            font=font("small"),
            text_color=UI_TEXT_MUTED,
            anchor="w",
        )
        self.off_banks.pack(fill="x", pady=(12, 4))
        self.off_active = ctk.CTkCheckBox(form_scroll, text="Active on roster", font=font("body"))
        self.off_active.select()
        self.off_active.pack(anchor="w", pady=12)

        btns = ctk.CTkFrame(right.body, fg_color="transparent")
        btns.grid(row=3, column=0, sticky="ew", padx=CARD_PAD, pady=(0, CARD_PAD))
        ctk.CTkButton(
            btns,
            text="Import Roster",
            height=38,
            corner_radius=8,
            fg_color=UI_BORDER,
            hover_color=DODGEVILLE_ACCENT,
            command=self.import_roster_csv,
        ).pack(
            side="right",
            padx=(8, 0),
        )
        ctk.CTkButton(
            btns,
            text="Bulk Pay Rates",
            height=38,
            corner_radius=8,
            fg_color=UI_BORDER,
            hover_color=DODGEVILLE_GOLD,
            command=self.bulk_pay_rate_dialog,
        ).pack(
            side="right",
            padx=(8, 0),
        )
        action_btns = ctk.CTkFrame(btns, fg_color="transparent")
        action_btns.pack(side="right")
        ctk.CTkButton(
            action_btns,
            text="Deactivate",
            height=38,
            corner_radius=8,
            fg_color=UI_BORDER,
            hover_color=DODGEVILLE_WARNING,
            command=self.deactivate_officer,
        ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            action_btns,
            text="Delete Officer",
            height=38,
            corner_radius=8,
            fg_color=DODGEVILLE_DANGER,
            command=self.delete_officer_profile,
        ).pack(side="left")

        self.refresh_officer_list()
        officers = [o for o in get_officers_by_seniority() if o.get("active") == 1]
        if officers:
            self.load_officer(officers[0]["id"])
        else:
            self.new_officer_form()

    def _on_job_title_selected(self, _value=None):
        self._job_title_var.set(self.off_job_title.get())
        if self.can("officers.manage"):
            hourly = suggested_hourly_rate_for_title(self._job_title_var.get())
            if hourly and hourly > 0:
                self.off_pay.delete(0, "end")
                self.off_pay.insert(0, f"{hourly:.2f}")
            self._refresh_pay_rate_hint()

    def _refresh_pay_rate_hint(self):
        if not hasattr(self, "off_pay_hint"):
            return
        title = self._job_title_var.get()
        hourly = suggested_hourly_rate_for_title(title)
        if hourly and hourly > 0:
            if title in YEARLY_SALARY_TITLES:
                formula = "yearly salary ÷ 2008"
            else:
                formula = "monthly × 12 ÷ 2008"
            self.off_pay_hint.configure(
                text=f"Suggested from {title}: ${hourly:.2f}/hr ({formula}) — editable",
            )
        else:
            self.off_pay_hint.configure(
                text="Set title pay on Payroll → Position Pay Rates, or enter base rate manually",
            )

    def _on_squad_selected(self, _value=None):
        self._squad_var.set(self.off_squad.get())

    def _on_shift_selected(self, _value=None):
        self._shift_var.set(self.off_shift.get())

    def _assignment_combo_state(self) -> str:
        return "readonly" if self.can("officers.manage") else "disabled"

    def _refresh_officer_title_options(self):
        values = get_officer_title_options()
        current = self._job_title_var.get()
        self.off_job_title.configure(values=values)
        if current in values:
            self._job_title_var.set(current)
        elif values:
            self._job_title_var.set(values[0])

    def _add_officer_title(self):
        if not self.can("officers.manage"):
            return
        title = self._new_title_entry.get().strip()
        if not title:
            messagebox.showwarning("Add Title", "Enter a title name.")
            return
        uid = self.current_user.get("id") if self.current_user else None
        result = add_custom_officer_title(title, user_id=uid)
        if not result.get("success"):
            messagebox.showerror("Add Title", result.get("message", "Failed"))
            return
        self._new_title_entry.delete(0, "end")
        self._refresh_officer_title_options()
        self._job_title_var.set(result["title"])
        self.set_status(result.get("message", "Title added"))

    def _configure_job_title_combo(self, job_title=None):
        normalized = normalize_officer_job_title(job_title) or get_builtin_officer_titles()[0]
        self._refresh_officer_title_options()
        if normalized not in self.off_job_title.cget("values"):
            self.off_job_title.configure(values=[normalized, *self.off_job_title.cget("values")])
        self._job_title_var.set(normalized)
        self.off_job_title.configure(state=self._assignment_combo_state())

    def _configure_squad_combo(self, squad=None):
        display = format_officer_squad_display(squad)
        values = list(OFFICER_SQUAD_OPTIONS)
        if display not in values:
            values = [display, *values]
        self.off_squad.configure(values=values)
        self._squad_var.set(display)
        self.off_squad.configure(state=self._assignment_combo_state())

    def _refresh_officer_shift_options(self):
        options = get_officer_shift_options()
        current = self._shift_var.get().strip()
        self.off_shift.configure(values=list(options))
        if current in options:
            self._shift_var.set(current)
        elif len(options) > 1:
            self._shift_var.set(options[1])

    def _configure_shift_combo(self, shift_start=None, shift_end=None):
        display = format_officer_shift_display(shift_start, shift_end)
        values = list(get_officer_shift_options())
        if display not in values:
            values = [display, *values]
        self.off_shift.configure(values=values)
        self._shift_var.set(display)
        self.off_shift.configure(state=self._assignment_combo_state())

    def _officer_row_meta_line(self, officer, period_hours: Optional[float] = None):
        squad = format_officer_squad_display(officer.get("squad"))
        shift = format_officer_shift_display(officer.get("shift_start"), officer.get("shift_end"))
        parts = [f"Squad {squad}", f"#{officer['seniority_rank']}", shift]
        if period_hours is not None:
            parts.append(f"{period_hours:.1f}h this period")
        return " · ".join(p for p in parts if p)

    def _bind_officer_row_click(self, row, officer_id: int):
        def _click(_event=None):
            self.load_officer(officer_id)

        row.bind("<Button-1>", _click)
        for child in row.winfo_children():
            child.bind("<Button-1>", _click)
            for grand in child.winfo_children():
                grand.bind("<Button-1>", _click)

    def _officer_picker_label(self, officer):
        squad = format_officer_squad_display(officer.get("squad"))
        return f"{officer['name']}  ·  Squad {squad}  ·  #{officer['seniority_rank']}"

    def _sync_officer_picker(self, visible_officers):
        if not hasattr(self, "off_picker"):
            return
        self._officer_picker_map = {self._officer_picker_label(o): o["id"] for o in visible_officers}
        labels = list(self._officer_picker_map.keys()) or ["No officers shown"]
        if self.can("officers.manage"):
            labels = ["(new officer)"] + labels
        self._officer_picker_syncing = True
        self.off_picker.configure(values=labels)
        if self.selected_officer_id:
            for label, officer_id in self._officer_picker_map.items():
                if officer_id == self.selected_officer_id:
                    self.off_picker.set(label)
                    break
        elif self._officer_form_mode == "new":
            self.off_picker.set("(new officer)")
        self._officer_picker_syncing = False

    def _on_officer_picker(self, choice):
        if self._officer_picker_syncing:
            return
        if choice == "(new officer)":
            self.new_officer_form()
            return
        officer_id = self._officer_picker_map.get(choice)
        if officer_id and officer_id != self.selected_officer_id:
            self.load_officer(officer_id)

    def _highlight_officer_selection(self):
        cache = getattr(self, "_officer_cache", {})
        for officer_id, row in self._officer_row_widgets.items():
            officer = cache.get(officer_id)
            if officer:
                self._update_officer_row(row, officer)

    def _create_officer_row(self, officer):
        active = officer.get("active") == 1
        is_selected = self.selected_officer_id == officer["id"]
        officer_id = officer["id"]
        bg = DODGEVILLE_ACCENT if is_selected else (UI_SURFACE if active else "#2A2A2A")
        row = ctk.CTkFrame(self.officer_list, fg_color=bg, corner_radius=8)
        inner = ctk.CTkFrame(row, fg_color="transparent")
        inner.pack(fill="x", padx=12, pady=8)
        top = ctk.CTkFrame(inner, fg_color="transparent")
        top.pack(fill="x")
        ctk.CTkLabel(
            top,
            text=officer["name"],
            font=font("body"),
            text_color="#FFFFFF",
            anchor="w",
        ).pack(side="left")
        badges = ctk.CTkFrame(top, fg_color="transparent")
        badges.pack(side="right")
        row._officer_badges = badges
        self._populate_officer_row_badges(badges, officer, active)
        period_hours = getattr(self, "_roster_period_hours", {}).get(officer_id)
        meta = ctk.CTkLabel(
            inner,
            text=self._officer_row_meta_line(officer, period_hours),
            font=font("small"),
            text_color=UI_TEXT_MUTED,
            anchor="w",
        )
        meta.pack(fill="x", pady=(4, 0))
        row._officer_meta = meta
        self._bind_officer_row_click(row, officer_id)
        return row

    def _populate_officer_row_badges(self, badges, officer, active: bool):
        for child in badges.winfo_children():
            child.destroy()
        title = format_officer_title_display(officer.get("job_title"))
        if title:
            StatusBadge(badges, title).pack(side="left", padx=(4, 0))
        StatusBadge(badges, "Active" if active else "Inactive").pack(side="left", padx=(4, 0))

    def _update_officer_row(self, row, officer):
        active = officer.get("active") == 1
        is_selected = self.selected_officer_id == officer["id"]
        bg = DODGEVILLE_ACCENT if is_selected else (UI_SURFACE if active else "#2A2A2A")
        row.configure(fg_color=bg)
        if hasattr(row, "_officer_badges"):
            self._populate_officer_row_badges(row._officer_badges, officer, active)
        period_hours = getattr(self, "_roster_period_hours", {}).get(officer["id"])
        if hasattr(row, "_officer_meta"):
            row._officer_meta.configure(
                text=self._officer_row_meta_line(officer, period_hours),
            )

    def _officer_row_meta(self, officer):
        squad = format_officer_squad_display(officer.get("squad"))
        shift = format_officer_shift_display(
            officer.get("shift_start"),
            officer.get("shift_end"),
        )
        title = format_officer_title_display(officer.get("job_title"))
        parts = [
            title or "No title",
            f"Squad {squad}",
            f"#{officer['seniority_rank']}",
            shift,
        ]
        if officer.get("start_date"):
            parts.append(f"since {format_date(officer['start_date'])}")
        if officer.get("phone"):
            parts.append(officer["phone"])
        return " · ".join(parts)

    def _officer_contact_fields(self):
        return {
            "start_date": self.off_start_date.get().strip(),
            "email": self.off_email.get().strip(),
            "phone": self.off_phone.get().strip(),
            "address": self.off_address.get("1.0", "end").strip(),
        }

    def refresh_officer_list(self):
        query = self.officer_search.get().strip().lower()
        visible = []
        all_officers = get_officers_by_seniority()
        self._officer_cache = {o["id"]: o for o in all_officers}
        try:
            self._roster_period_hours = get_pay_period_hours_by_officer()
        except Exception:
            self._roster_period_hours = {}
        show_inactive = self.off_show_inactive.get() if hasattr(self, "off_show_inactive") else False
        for officer in all_officers:
            if not show_inactive and officer.get("active") != 1:
                continue
            label = f"{officer['name']} {officer['squad']}".lower()
            if query and query not in label:
                continue
            visible.append(officer)

        visible_ids = {o["id"] for o in visible}
        for officer_id, row in list(self._officer_row_widgets.items()):
            if officer_id not in visible_ids:
                row.destroy()
                del self._officer_row_widgets[officer_id]

        for officer in visible:
            officer_id = officer["id"]
            row = self._officer_row_widgets.get(officer_id)
            stale = False
            if row is not None:
                try:
                    stale = not row.winfo_exists()
                except Exception:
                    stale = True
            if row is None or stale:
                row = self._create_officer_row(officer)
                self._officer_row_widgets[officer_id] = row
            else:
                self._update_officer_row(row, officer)
            row.pack_forget()

        for officer in visible:
            self._officer_row_widgets[officer["id"]].pack(fill="x", pady=3, padx=4)

        if hasattr(self, "officer_roster_count"):
            active_total = sum(1 for o in all_officers if o.get("active") == 1)
            self.officer_roster_count.configure(
                text=f"{len(visible)} shown · {active_total} active · {len(all_officers)} total"
            )

        self._sync_officer_picker(visible)

    def import_roster_csv(self):
        if not self.can("officers.manage"):
            messagebox.showwarning("Permission", "You do not have permission to import the roster.")
            return
        path = filedialog.askopenfilename(
            title="Import Roster CSV",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not path:
            return
        result = import_roster_from_csv(path)
        if result.get("success"):
            details = result.get("message", "Import complete.")
            if result.get("error_details"):
                details += "\n\n" + "\n".join(result["error_details"])
            messagebox.showinfo("Import Roster", details)
            self.refresh_officer_list()
            refresh_all_officer_dropdowns(self)
            self.set_status("Roster imported")
        else:
            messagebox.showerror("Import Failed", result.get("message", "Unknown error"))

    def _show_officer_photo(self, photo_path=None):
        if not hasattr(self, "off_photo_label"):
            return
        try:
            if not self.off_photo_label.winfo_exists():
                return
        except Exception:
            return
        if photo_path:
            img, _ = load_thumbnail(photo_path, size=(160, 160))
            if img:
                self._photo_image = img
                self.off_photo_label.configure(text="")
                self.off_photo_label.configure(image=img)
                return
        try:
            self.off_photo_label.configure(text="No Photo", image="")
        except Exception:
            self.off_photo_label.configure(text="No Photo")
        self._photo_image = None

    def upload_officer_photo(self):
        if not self.selected_officer_id:
            messagebox.showwarning("Save First", "Save the officer profile before uploading a photo.")
            return
        path = filedialog.askopenfilename(
            title="Select Officer Photo",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.gif *.webp *.bmp")],
        )
        if not path:
            return
        result = set_officer_photo(self.selected_officer_id, path)
        if result.get("success"):
            self._show_officer_photo(result["photo_path"])
            self.refresh_officer_list()
            self.set_status("Photo uploaded")
        else:
            messagebox.showerror("Upload Failed", result.get("message", "Unknown error"))

    def remove_officer_photo(self):
        if not self.selected_officer_id:
            return
        result = logic_remove_officer_photo(self.selected_officer_id)
        if result.get("success"):
            self._show_officer_photo()
            self.refresh_officer_list()
            self.set_status("Photo removed")
        else:
            messagebox.showerror("Error", result.get("message", "Remove failed."))

    def new_officer_form(self):
        self._officer_form_mode = "new"
        self.selected_officer_id = None
        if hasattr(self, "off_selection_label"):
            self.off_selection_label.configure(text="Adding: new officer")
        self._officer_picker_syncing = True
        if hasattr(self, "off_picker"):
            self.off_picker.set("(new officer)")
        self._officer_picker_syncing = False
        self.off_name.configure(state="normal")
        self.off_name.delete(0, "end")
        for entry, val in [
            (self.off_seniority, str(get_suggested_seniority_rank())),
            (self.off_pay, "30.0"),
            (self.off_night_diff, "1.0"),
            (self.off_annual_hours, str(int(get_active_annual_hours_target()))),
            (self.off_ot_multiplier, "1.5"),
            (self.off_start_date, ""),
            (self.off_email, ""),
            (self.off_phone, ""),
        ]:
            entry.delete(0, "end")
            entry.insert(0, val)
        self.off_address.delete("1.0", "end")
        self.off_banks.configure(text="Time banks: not set")
        self.off_pay_projection.configure(text="Annual pay projection: not set")
        self._configure_job_title_combo(get_builtin_officer_titles()[0])
        self._configure_squad_combo("A")
        opts = get_officer_shift_options()
        default_shift = opts[1] if len(opts) > 1 else opts[0]
        self._configure_shift_combo(*parse_officer_shift_ui(default_shift))
        self.off_active.select()
        self._show_officer_photo()
        self.refresh_officer_list()

    def load_officer(self, officer_id, force_reload=False):
        if not force_reload and self.selected_officer_id == officer_id and self._officer_form_mode == "edit":
            self._highlight_officer_selection()
            return
        officer = get_officer_by_id(officer_id)
        if not officer:
            messagebox.showwarning("Officer", "That officer could not be loaded.")
            return
        self._officer_form_mode = "edit"
        self.selected_officer_id = officer_id
        if hasattr(self, "off_selection_label"):
            self.off_selection_label.configure(text=f"Editing: {officer['name']}")
        self._officer_picker_syncing = True
        if hasattr(self, "off_picker"):
            label = self._officer_picker_label(officer)
            if label not in self._officer_picker_map:
                self._officer_picker_map[label] = officer_id
            self.off_picker.set(label)
        self._officer_picker_syncing = False
        self.off_name.configure(state="normal")
        self.off_name.delete(0, "end")
        self.off_name.insert(0, officer["name"])
        self._configure_job_title_combo(officer.get("job_title"))
        for entry, val in [
            (self.off_seniority, str(officer["seniority_rank"])),
            (self.off_pay, str(officer["pay_rate"])),
            (self.off_night_diff, str(officer.get("night_differential_rate", 1.0))),
            (self.off_annual_hours, str(officer.get("annual_hours_target") or get_active_annual_hours_target())),
            (self.off_ot_multiplier, str(officer.get("overtime_multiplier") or 1.5)),
            (self.off_start_date, format_date(officer["start_date"]) if officer.get("start_date") else ""),
            (self.off_email, officer.get("email") or ""),
            (self.off_phone, officer.get("phone") or ""),
        ]:
            entry.delete(0, "end")
            entry.insert(0, val)
        self.off_address.delete("1.0", "end")
        if officer.get("address"):
            self.off_address.insert("1.0", officer["address"])
        banks = get_officer_time_banks(officer_id)
        if banks.get("success"):
            self.off_banks.configure(
                text=(
                    f"Time banks: Comp {banks['comp_hours']:.1f}h · "
                    f"Sick {banks['sick_hours']:.1f}h · "
                    f"Float {banks['float_holiday_hours']:.1f}h · "
                    f"Holiday {banks['holiday_hours']:.1f}h"
                )
            )
        else:
            self.off_banks.configure(text="Time banks: not set")
        self._configure_squad_combo(officer.get("squad"))
        self._configure_shift_combo(officer.get("shift_start"), officer.get("shift_end"))
        if officer.get("active") == 1:
            self.off_active.select()
        else:
            self.off_active.deselect()
        self._show_officer_photo(officer.get("photo_path"))
        self._refresh_pay_rate_hint()
        self._refresh_officer_pay_projection(officer_id)
        self._highlight_officer_selection()

    def _refresh_officer_pay_projection(self, officer_id: int):
        proj = project_officer_annual_pay(officer_id)
        if not proj.get("success"):
            self.off_pay_projection.configure(text="Annual pay projection: not set")
            return
        self.off_pay_projection.configure(
            text=(
                f"${proj.get('monthly_pay', 0):,.0f}/mo · "
                f"${proj.get('per_pay_period_salary', 0):,.0f}/pay period · "
                f"${proj.get('annual_salary', proj.get('base_annual_pay', 0)):,.0f}/yr salary"
                f"  (+ OT ${proj.get('overtime_pay', 0):,.0f} projected)"
            )
        )

    def bulk_pay_rate_dialog(self):
        if not self.can("payroll.bulk_adjust"):
            messagebox.showwarning("Permission", "Only Supervisor or Administration can bulk-adjust pay.")
            return
        dialog = ctk.CTkToplevel(self.root)
        dialog.title("Bulk Pay Rate Adjustment")
        dialog.geometry("400x300")
        dialog.transient(self.root)
        form = ctk.CTkFrame(dialog, fg_color="transparent")
        form.pack(fill="both", expand=True, padx=16, pady=16)
        ctk.CTkLabel(form, text="Percent Change (%)", font=font("small"), text_color=UI_TEXT_MUTED).pack(anchor="w")
        pct = ctk.CTkEntry(form, height=36, placeholder_text="e.g. 3.5 for 3.5% raise")
        pct.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(form, text="Flat Amount ($/hr)", font=font("small"), text_color=UI_TEXT_MUTED).pack(anchor="w")
        flat = ctk.CTkEntry(form, height=36, placeholder_text="0.0")
        flat.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(form, text="Squad Filter", font=font("small"), text_color=UI_TEXT_MUTED).pack(anchor="w")
        squad = ctk.CTkComboBox(form, values=["All", "A", "B"], height=36)
        squad.pack(fill="x", pady=(0, 12))
        squad.set("All")

        def apply_bulk():
            try:
                percent = float(pct.get().strip() or "0")
                amount = float(flat.get().strip() or "0")
            except ValueError:
                messagebox.showerror("Validation", "Enter numeric values.")
                return
            sq = squad.get()
            result = bulk_adjust_pay_rates(
                percent_change=percent,
                flat_amount=amount,
                squad=None if sq == "All" else sq,
            )
            if result.get("success"):
                dialog.destroy()
                self.refresh_officer_list()
                self._refresh_payroll_officer_dropdown()
                self.set_status(result.get("message", "Pay rates updated"))
            else:
                messagebox.showerror("Error", result.get("message", "Update failed"))

        ctk.CTkButton(form, text="Apply to Roster", fg_color=DODGEVILLE_SUCCESS, command=apply_bulk).pack(fill="x")

    def _parse_squad(self):
        value = self._squad_var.get().strip()
        if value == OFFICER_UNASSIGNED_LABEL:
            return None
        return value

    def _parse_shift(self):
        return parse_officer_shift_ui(self._shift_var.get().strip())

    def save_officer(self):
        if not self.can("officers.manage"):
            messagebox.showwarning(
                "Permission",
                "Only Supervisor or Administration can edit the patrol roster.",
            )
            return
        try:
            name = self.off_name.get().strip()
            seniority = int(self.off_seniority.get().strip())
            pay_rate = float(self.off_pay.get().strip())
            night_diff = float(self.off_night_diff.get().strip() or "1.0")
            annual_target = float(self.off_annual_hours.get().strip() or str(get_active_annual_hours_target()))
            ot_mult = float(self.off_ot_multiplier.get().strip() or "1.5")
        except ValueError:
            messagebox.showerror("Validation", "Check numeric fields (seniority, pay, hours, OT).")
            return
        if not name:
            messagebox.showerror("Validation", "Name is required.")
            return
        squad = self._parse_squad()
        shift_start, shift_end = self._parse_shift()
        active = 1 if self.off_active.get() else 0
        contact = self._officer_contact_fields()
        pay_fields = {
            "job_title": normalize_officer_job_title(self._job_title_var.get().strip()),
            "annual_hours_target": annual_target,
            "overtime_multiplier": ot_mult,
        }
        if self._officer_form_mode == "new" or not self.selected_officer_id:
            if self._officer_form_mode != "new":
                messagebox.showwarning(
                    "Select Officer",
                    "Choose an officer from the dropdown or roster list before saving changes.",
                )
                return
            result = add_officer(
                name,
                seniority,
                squad,
                shift_start,
                shift_end,
                pay_rate,
                night_diff,
                **contact,
                **pay_fields,
            )
            saved_id = result.get("officer_id")
        else:
            result = update_officer(
                self.selected_officer_id,
                name=name,
                seniority_rank=seniority,
                squad=squad,
                shift_start=shift_start,
                shift_end=shift_end,
                pay_rate=pay_rate,
                night_differential_rate=night_diff,
                active=active,
                **contact,
                **pay_fields,
            )
            saved_id = self.selected_officer_id
        if result.get("success"):
            if saved_id:
                self.selected_officer_id = saved_id
                self._officer_form_mode = "edit"
                self.refresh_officer_list()
                self.load_officer(saved_id, force_reload=True)
                refresh_all_officer_dropdowns(self)
                self.set_status(f"Officer saved: {name}")
            else:
                self.refresh_officer_list()
                self._highlight_officer_selection()
                refresh_all_officer_dropdowns(self)
                self.set_status(f"Officer saved: {name}")
        else:
            messagebox.showerror("Error", result.get("message", "Save failed."))

    def deactivate_officer(self):
        if not self.selected_officer_id:
            messagebox.showwarning("Select Officer", "Select an officer from the roster first.")
            return
        if messagebox.askyesno("Confirm", "Deactivate this officer?"):
            update_officer(self.selected_officer_id, active=0)
            self.off_active.deselect()
            self.refresh_officer_list()
            refresh_all_officer_dropdowns(self)
            self.set_status("Officer deactivated")

    def delete_officer_profile(self):
        if not self.selected_officer_id:
            messagebox.showwarning("Select Officer", "Select an officer from the roster first.")
            return
        officer = get_officer_by_id(self.selected_officer_id)
        if not officer:
            return
        prompt = (
            f"Permanently delete {officer['name']}?\n\n"
            "Officers with scheduling history cannot be deleted. Use Deactivate instead."
        )
        if not messagebox.askyesno("Delete Officer", prompt):
            return
        officer_id = self.selected_officer_id
        result = delete_officer(officer_id)
        if result.get("success"):
            row = self._officer_row_widgets.pop(officer_id, None)
            if row:
                row.destroy()
            self.new_officer_form()
            refresh_all_officer_dropdowns(self)
            self._refresh_dashboard()
            self.set_status(result.get("message", "Officer deleted"))
        else:
            messagebox.showerror("Delete Failed", result.get("message", "Delete failed."))
