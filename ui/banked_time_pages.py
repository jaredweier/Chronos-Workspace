"""Banked time balances, FLSA status, and transaction drill-down."""

from datetime import date
from tkinter import messagebox
from typing import Optional

import customtkinter as ctk

from logic import (
    get_bank_transactions,
    get_banked_time_summary,
    get_officers_by_seniority,
    shift_scope_reference,
)
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
from ui.widgets import Card, SectionHeader

_SCOPE_OPTIONS = ("Pay Period", "Month", "Year", "All Time")
_SCOPE_MAP = {
    "Pay Period": "pay_period",
    "Month": "month",
    "Year": "year",
    "All Time": "all_time",
}
_SCOPE_REVERSE = {v: k for k, v in _SCOPE_MAP.items()}


class BankedTimePageMixin:
    def _build_banked_time(self):
        page = self.pages["banked_time"]
        page.grid_rowconfigure(3, weight=1)
        page.grid_columnconfigure(0, weight=1)

        hdr = ctk.CTkFrame(page, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", pady=(0, 8))

        self.bt_scope_label = ctk.CTkLabel(hdr, text="", font=font("heading"))
        self.bt_scope_label.pack(side="left")

        nav = ctk.CTkFrame(hdr, fg_color="transparent")
        nav.pack(side="left", padx=(12, 0))
        self._bt_prev_btn = ctk.CTkButton(
            nav,
            text="◀",
            width=36,
            height=36,
            fg_color=UI_BORDER,
            command=lambda: self._shift_banked_time_scope(-1),
        )
        self._bt_prev_btn.pack(side="left", padx=(0, 4))
        ctk.CTkButton(
            nav,
            text="Today",
            width=64,
            height=36,
            fg_color=UI_SURFACE,
            command=self._reset_banked_time_reference,
        ).pack(side="left", padx=(0, 4))
        self._bt_next_btn = ctk.CTkButton(
            nav,
            text="▶",
            width=36,
            height=36,
            fg_color=UI_BORDER,
            command=lambda: self._shift_banked_time_scope(1),
        )
        self._bt_next_btn.pack(side="left")

        if self.can("timecard.view_all"):
            officers = [o for o in get_officers_by_seniority() if o.get("active") == 1]
            labels = [o["name"] for o in officers]
            self.bt_officer_map = {n: o["id"] for n, o in zip(labels, officers)}
            self.bt_officer_combo = ctk.CTkComboBox(
                hdr,
                values=labels,
                width=220,
                height=36,
                command=lambda _: self.refresh_banked_time(),
            )
            self.bt_officer_combo.pack(side="right", padx=(8, 0))
            if labels:
                self.bt_officer_combo.set(labels[0])
        else:
            self.bt_officer_map = {}
            self.bt_officer_combo = None
            if self.current_user and self.current_user.get("officer_id"):
                name = self.current_user.get("officer_name") or "My Banks"
                ctk.CTkLabel(hdr, text=name, font=font("subheading")).pack(side="right", padx=(8, 0))

        filter_row = ctk.CTkFrame(page, fg_color="transparent")
        filter_row.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        ctk.CTkLabel(
            filter_row,
            text="View",
            font=font("small"),
            text_color=UI_TEXT_MUTED,
        ).pack(side="left")
        self.bt_scope_combo = ctk.CTkComboBox(
            filter_row,
            values=list(_SCOPE_OPTIONS),
            width=140,
            height=32,
            command=self._on_banked_time_scope_change,
        )
        self.bt_scope_combo.set("Pay Period")
        self.bt_scope_combo.pack(side="left", padx=(6, 0))
        ctk.CTkLabel(
            filter_row,
            text="Balances update from timecards · sick/float/holiday accruals apply automatically",
            font=font("small"),
            text_color=UI_TEXT_MUTED,
        ).pack(side="left", padx=(12, 0))

        self.bt_flsa_card = Card(page)
        self.bt_flsa_card.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        SectionHeader(
            self.bt_flsa_card.body,
            "FLSA §207(k)",
            "Auto-calculated from rotation cycle length and timecard hours",
        ).pack(fill="x", padx=CARD_PAD, pady=(CARD_PAD, 0))
        self.bt_flsa_body = ctk.CTkFrame(self.bt_flsa_card.body, fg_color="transparent")
        self.bt_flsa_body.pack(fill="x", padx=CARD_PAD, pady=(0, CARD_PAD))

        self.bt_banks_scroll = ctk.CTkScrollableFrame(page, fg_color="transparent")
        self.bt_banks_scroll.grid(row=3, column=0, sticky="nsew")

        self._banked_time_scope = "pay_period"
        self._banked_time_reference: Optional[date] = None

    def _banked_time_officer_id(self) -> Optional[int]:
        if self._is_officer_role():
            return self._linked_officer_id()
        if self.bt_officer_combo:
            name = self.bt_officer_combo.get()
            return self.bt_officer_map.get(name)
        return None

    def _on_banked_time_scope_change(self, selection: str):
        self._banked_time_scope = _SCOPE_MAP.get(selection, "pay_period")
        self.refresh_banked_time()

    def _shift_banked_time_scope(self, direction: int):
        if self._banked_time_scope == "all_time":
            return
        ref = self._banked_time_reference or date.today()
        self._banked_time_reference = shift_scope_reference(self._banked_time_scope, ref, direction)
        self.refresh_banked_time()

    def _reset_banked_time_reference(self):
        self._banked_time_reference = None
        self.refresh_banked_time()

    def refresh_banked_time(self):
        officer_id = self._banked_time_officer_id()
        if not officer_id:
            return

        summary = get_banked_time_summary(
            officer_id,
            scope=self._banked_time_scope,
            reference=self._banked_time_reference,
        )
        if not summary.get("success"):
            messagebox.showerror("Banked Time", summary.get("message", "Unable to load"))
            return

        scope_label = summary.get("scope_label", "")
        if summary.get("period_start_display"):
            self.bt_scope_label.configure(
                text=f"{scope_label}  ({summary['period_start_display']} – {summary['period_end_display']})"
            )
        else:
            self.bt_scope_label.configure(text=scope_label)

        nav_enabled = self._banked_time_scope != "all_time"
        state = "normal" if nav_enabled else "disabled"
        self._bt_prev_btn.configure(state=state)
        self._bt_next_btn.configure(state=state)

        self._render_banked_time_flsa(summary.get("flsa") or {}, summary.get("flsa_work_period_days"))
        self._render_bank_cards(officer_id, summary.get("banks") or [])

    def _render_banked_time_flsa(self, flsa: dict, period_days: int):
        for w in self.bt_flsa_body.winfo_children():
            w.destroy()

        if not flsa.get("enabled"):
            ctk.CTkLabel(
                self.bt_flsa_body,
                text="FLSA §207(k) tracking is disabled in department settings.",
                font=font("small"),
                text_color=UI_TEXT_MUTED,
                anchor="w",
            ).pack(fill="x")
            return

        period_days = flsa.get("period_days") or period_days
        anchor = flsa.get("flsa_base_date_display", "")
        header = (
            f"{period_days}-day FLSA work period"
            f"{f' (anchor {anchor})' if anchor else ''}  ·  "
            f"{flsa.get('period_start_display', '')} – {flsa.get('period_end_display', '')}"
        )
        ctk.CTkLabel(
            self.bt_flsa_body,
            text=header,
            font=font("small"),
            text_color=UI_TEXT_MUTED,
            anchor="w",
        ).pack(fill="x", pady=(0, 6))

        hours = float(flsa.get("hours_worked", 0.0))
        threshold = float(flsa.get("hours_threshold", 0.0))
        pct = min(100.0, (hours / threshold * 100.0) if threshold else 0.0)
        severity = flsa.get("severity")
        bar_color = DODGEVILLE_SUCCESS
        if severity == "warning":
            bar_color = DODGEVILLE_WARNING
        elif severity == "critical":
            bar_color = DODGEVILLE_DANGER

        row = ctk.CTkFrame(self.bt_flsa_body, fg_color="transparent")
        row.pack(fill="x")
        ctk.CTkLabel(
            row,
            text=f"{hours:.1f}h worked",
            font=font("subheading"),
            anchor="w",
        ).pack(side="left")
        ctk.CTkLabel(
            row,
            text=f"/ {threshold:.0f}h threshold",
            font=font("small"),
            text_color=UI_TEXT_MUTED,
            anchor="w",
        ).pack(side="left", padx=(6, 0))

        bar_wrap = ctk.CTkFrame(self.bt_flsa_body, fg_color=UI_BORDER, corner_radius=6, height=12)
        bar_wrap.pack(fill="x", pady=(6, 4))
        bar_wrap.pack_propagate(False)
        if pct > 0:
            ctk.CTkFrame(
                bar_wrap,
                fg_color=bar_color,
                corner_radius=6,
                width=max(
                    8, int(bar_wrap.winfo_reqwidth() * pct / 100) if bar_wrap.winfo_reqwidth() else int(200 * pct / 100)
                ),
            ).pack(side="left", fill="y")

        if flsa.get("message"):
            ctk.CTkLabel(
                self.bt_flsa_body,
                text=flsa["message"],
                font=font("small"),
                text_color=bar_color,
                anchor="w",
            ).pack(fill="x", pady=(2, 0))
        over = float(flsa.get("over_threshold_hours", 0.0))
        if over > 0:
            ctk.CTkLabel(
                self.bt_flsa_body,
                text=f"Overtime due this FLSA period: {over:.1f}h",
                font=font("small"),
                text_color=DODGEVILLE_DANGER,
                anchor="w",
            ).pack(fill="x", pady=(2, 0))

    def _render_bank_cards(self, officer_id: int, banks: list):
        for w in self.bt_banks_scroll.winfo_children():
            w.destroy()

        if not banks:
            ctk.CTkLabel(
                self.bt_banks_scroll,
                text="No bank activity for this view.",
                font=font("body"),
                text_color=UI_TEXT_MUTED,
            ).pack(pady=24)
            return

        grid = ctk.CTkFrame(self.bt_banks_scroll, fg_color="transparent")
        grid.pack(fill="x")
        for col in range(2):
            grid.grid_columnconfigure(col, weight=1, uniform="banks")

        for idx, bank in enumerate(banks):
            card = Card(grid)
            card.grid(row=idx // 2, column=idx % 2, sticky="nsew", padx=(0 if idx % 2 == 0 else 6, 0), pady=(0, 8))

            body = ctk.CTkFrame(card.body, fg_color="transparent")
            body.pack(fill="both", expand=True, padx=CARD_PAD, pady=CARD_PAD)
            SectionHeader(body, bank["label"], "Earned and used from timecards in selected view").pack(
                fill="x", pady=(0, CARD_PAD)
            )

            ctk.CTkLabel(
                body,
                text=f"{bank['balance']:.1f}h",
                font=font("title"),
                text_color=DODGEVILLE_GOLD,
                anchor="w",
            ).pack(anchor="w")
            ctk.CTkLabel(
                body,
                text="Current balance",
                font=font("small"),
                text_color=UI_TEXT_MUTED,
                anchor="w",
            ).pack(anchor="w", pady=(0, CARD_PAD))

            stats = ctk.CTkFrame(body, fg_color="transparent")
            stats.pack(fill="x")
            for label, value, color in (
                ("Earned", bank["earned"], DODGEVILLE_SUCCESS),
                ("Used", bank["used"], DODGEVILLE_DANGER),
                ("Net", bank["net"], DODGEVILLE_ACCENT),
            ):
                col_frame = ctk.CTkFrame(stats, fg_color=UI_SURFACE, corner_radius=8)
                col_frame.pack(side="left", fill="x", expand=True, padx=(0, 6))
                ctk.CTkLabel(
                    col_frame,
                    text=label,
                    font=font("small"),
                    text_color=UI_TEXT_MUTED,
                ).pack(pady=(8, 0))
                ctk.CTkLabel(
                    col_frame,
                    text=f"{value:.1f}h",
                    font=font("subheading"),
                    text_color=color,
                ).pack(pady=(0, 8))

            ctk.CTkButton(
                body,
                text="View transactions",
                height=32,
                fg_color=DODGEVILLE_BLUE,
                hover_color=DODGEVILLE_ACCENT,
                command=lambda b=bank["key"], oid=officer_id: self._open_bank_transactions(oid, b),
            ).pack(fill="x", pady=(CARD_PAD, 0))

    def _open_bank_transactions(self, officer_id: int, bank_type: str):
        dlg = ctk.CTkToplevel(self.root)
        dlg.title("Bank Transactions")
        dlg.geometry("720x520")
        dlg.transient(self.root)
        dlg.grab_set()

        hdr = ctk.CTkFrame(dlg, fg_color="transparent")
        hdr.pack(fill="x", padx=16, pady=(12, 8))
        title_lbl = ctk.CTkLabel(hdr, text="", font=font("heading"), anchor="w")
        title_lbl.pack(side="left")

        scope_var = ctk.StringVar(value=_SCOPE_REVERSE.get(self._banked_time_scope, "Pay Period"))
        scope_combo = ctk.CTkComboBox(hdr, values=list(_SCOPE_OPTIONS), width=140, height=32, variable=scope_var)
        scope_combo.pack(side="right")

        nav = ctk.CTkFrame(dlg, fg_color="transparent")
        nav.pack(fill="x", padx=16, pady=(0, 8))
        ref_holder = {"date": self._banked_time_reference}

        def load_transactions():
            scope = _SCOPE_MAP.get(scope_var.get(), "pay_period")
            data = get_bank_transactions(officer_id, bank_type, scope=scope, reference=ref_holder["date"])
            if not data.get("success"):
                messagebox.showerror("Transactions", data.get("message", "Failed"), parent=dlg)
                return
            title_lbl.configure(text=f"{data['bank_label']} — {data['scope_label']}")
            for w in scroll.winfo_children():
                w.destroy()
            totals = data.get("totals") or {}
            ctk.CTkLabel(
                scroll,
                text=(
                    f"Earned {totals.get('earned', 0):.1f}h  ·  "
                    f"Used {totals.get('used', 0):.1f}h  ·  "
                    f"Net {totals.get('net', 0):.1f}h"
                ),
                font=font("small"),
                text_color=UI_TEXT_MUTED,
                anchor="w",
            ).pack(fill="x", pady=(0, 8))

            txns = data.get("transactions") or []
            if not txns:
                ctk.CTkLabel(scroll, text="No transactions in this view.", text_color=UI_TEXT_MUTED).pack(pady=24)
                return

            header = ctk.CTkFrame(scroll, fg_color=UI_SURFACE, corner_radius=8)
            header.pack(fill="x", pady=(0, 4))
            for text, width in (
                ("Date", 100),
                ("Pay Code", 160),
                ("Hours", 60),
                ("Earned", 70),
                ("Used", 70),
                ("Source", 80),
            ):
                ctk.CTkLabel(header, text=text, font=font("small"), width=width, anchor="w").pack(
                    side="left", padx=6, pady=6
                )

            for txn in txns:
                row = ctk.CTkFrame(scroll, fg_color="transparent")
                row.pack(fill="x", pady=2)
                earned_txt = f"{txn['earned']:.1f}h" if txn["earned"] else "—"
                used_txt = f"{txn['used']:.1f}h" if txn["used"] else "—"
                for text, width in (
                    (txn["entry_date_display"], 100),
                    (txn["entry_type"], 160),
                    (f"{txn['hours_worked']:.1f}", 60),
                    (earned_txt, 70),
                    (used_txt, 70),
                    (txn["source"], 80),
                ):
                    ctk.CTkLabel(row, text=text, font=font("small"), width=width, anchor="w").pack(side="left", padx=6)

        def shift_ref(direction: int):
            scope = _SCOPE_MAP.get(scope_var.get(), "pay_period")
            if scope == "all_time":
                return
            ref = ref_holder["date"] or date.today()
            ref_holder["date"] = shift_scope_reference(scope, ref, direction)
            load_transactions()

        ctk.CTkButton(nav, text="◀", width=36, command=lambda: shift_ref(-1)).pack(side="left", padx=(0, 4))
        ctk.CTkButton(
            nav, text="Today", width=64, command=lambda: (ref_holder.update({"date": None}), load_transactions())
        ).pack(side="left", padx=(0, 4))
        ctk.CTkButton(nav, text="▶", width=36, command=lambda: shift_ref(1)).pack(side="left", padx=(0, 12))
        scope_combo.configure(command=lambda _: load_transactions())

        scroll = ctk.CTkScrollableFrame(dlg, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=16, pady=(0, 16))
        load_transactions()
