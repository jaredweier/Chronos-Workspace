"""Application shell — sidebar, topbar, navigation, and page refresh orchestration."""

from datetime import date
from tkinter import messagebox

import customtkinter as ctk

from database import backup_database
from logic import get_cycle_day, get_squad_on_duty, get_unread_notification_count, log_audit_action
from ui.assets import load_logo
from ui.branding import get_department_branding
from ui.helpers import handle_export_result, title_case_ui
from ui.profile_dialog import open_my_profile_dialog
from ui.theme import (
    CONTENT_PAD,
    DODGEVILLE_ACCENT,
    DODGEVILLE_DANGER,
    DODGEVILLE_GOLD,
    DODGEVILLE_SUCCESS,
    NAV_HUBS,
    NAV_ITEMS,
    NAV_PERMISSIONS,
    OFFICER_PAGE_SUBTITLES,
    PAGE_SUBTITLES,
    SIDEBAR_NAV,
    TOPBAR_HEIGHT,
    UI_ACCENT_GLOW,
    UI_BG,
    UI_BORDER,
    UI_SIDEBAR,
    UI_SURFACE,
    UI_TEXT_MUTED,
    font,
    hub_for_page,
    page_title,
    resolve_nav_target,
    tactical_stripe,
)
from ui.widgets import NavButton, NavSectionLabel, SubNavBar
from validators import format_date


class ShellPageMixin:
    """Main window chrome: nav, page routing, status bar, and global refresh."""

    def _build_shell(self) -> None:
        self.shell = ctk.CTkFrame(self.root, fg_color=UI_BG, corner_radius=0)
        self.shell.pack(fill="both", expand=True)
        self.shell.grid_columnconfigure(1, weight=1)
        self.shell.grid_rowconfigure(0, weight=1)

        self._build_sidebar()
        self._build_main_area()

    def _sidebar_entry_visible(self, key: str) -> bool:
        if key in NAV_HUBS:
            for page_key in NAV_HUBS[key]["pages"]:
                perm = NAV_PERMISSIONS.get(page_key)
                if not perm:
                    return True
                perms = perm if isinstance(perm, tuple) else (perm,)
                if any(self.can(p) for p in perms):
                    return True
            return False
        perm = NAV_PERMISSIONS.get(key)
        if perm:
            perms = perm if isinstance(perm, tuple) else (perm,)
            return any(self.can(p) for p in perms)
        return True

    def _visible_hub_tabs(self, hub_key: str) -> list[tuple[str, str]]:
        hub = NAV_HUBS[hub_key]
        visible: list[tuple[str, str]] = []
        for page_key, label in hub["tabs"]:
            perm = NAV_PERMISSIONS.get(page_key)
            if perm:
                perms = perm if isinstance(perm, tuple) else (perm,)
                if not any(self.can(p) for p in perms):
                    continue
            visible.append((page_key, label))
        return visible

    def _update_subnav(self, page_key: str) -> None:
        hub_key = hub_for_page(page_key)
        if not hub_key or not hasattr(self, "subnav"):
            return
        tabs = self._visible_hub_tabs(hub_key)
        if tabs:
            self.subnav.set_tabs(tabs, page_key)
            self.subnav.grid(row=1, column=0, sticky="ew")
        else:
            self.subnav.grid_remove()

    def _build_sidebar(self) -> None:
        sidebar = ctk.CTkFrame(self.shell, width=268, fg_color=UI_SIDEBAR, corner_radius=0)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)

        tactical_stripe(sidebar)

        brand = ctk.CTkFrame(sidebar, fg_color="transparent")
        brand.pack(fill="x", padx=16, pady=(18, 14))
        branding = get_department_branding()
        brand_row = ctk.CTkFrame(brand, fg_color="transparent")
        brand_row.pack(fill="x")
        logo_img = load_logo((64, 64))
        if logo_img:
            self._remember_brand_image(logo_img)
            ctk.CTkLabel(brand_row, text="", image=logo_img).pack(side="left", padx=(0, 10))
        text_col = ctk.CTkFrame(brand_row, fg_color="transparent")
        text_col.pack(side="left", fill="x", expand=True)
        short_name = branding["name"].replace(" Police Department", " PD")
        ctk.CTkLabel(
            text_col,
            text=short_name,
            font=font("subheading"),
            text_color=UI_ACCENT_GLOW,
        ).pack(anchor="w")
        ctk.CTkLabel(
            text_col,
            text="Tactical Duty Scheduler",
            font=font("body"),
            text_color="#FFFFFF",
        ).pack(anchor="w")
        self._sidebar_mission_label = ctk.CTkLabel(
            brand,
            text=branding["tagline"],
            font=font("small"),
            text_color=DODGEVILLE_GOLD,
            wraplength=200,
        )
        self._sidebar_mission_label.pack(anchor="w", pady=(6, 0))

        nav_frame = ctk.CTkFrame(sidebar, fg_color="transparent")
        nav_frame.pack(fill="x", padx=10, pady=4)
        for entry in SIDEBAR_NAV:
            if entry[0] == "section":
                NavSectionLabel(nav_frame, text=entry[1]).pack(anchor="w", padx=8, pady=(10, 4))
                continue
            key, label, icon = entry
            if not self._sidebar_entry_visible(key):
                continue
            btn = NavButton(
                nav_frame,
                label,
                icon,
                command=lambda k=key: self.show_page(resolve_nav_target(k)),
            )
            btn.pack(fill="x", pady=2)
            self.nav_buttons[key] = btn

        ctk.CTkFrame(sidebar, fg_color=UI_BORDER, height=1).pack(fill="x", padx=16, pady=12)
        ctk.CTkButton(
            sidebar,
            text="↻  Refresh All",
            height=36,
            corner_radius=8,
            fg_color=UI_SURFACE,
            hover_color=DODGEVILLE_ACCENT,
            command=self.refresh_all,
        ).pack(fill="x", padx=16, pady=(0, 8))
        if self.can("database.backup"):
            ctk.CTkButton(
                sidebar,
                text="💾  Backup Database",
                height=36,
                corner_radius=8,
                fg_color=UI_SURFACE,
                hover_color=DODGEVILLE_SUCCESS,
                command=self.backup_database,
            ).pack(fill="x", padx=16, pady=(0, 8))
        ctk.CTkButton(
            sidebar,
            text="⎋  Sign Out",
            height=36,
            corner_radius=8,
            fg_color=UI_SURFACE,
            hover_color=DODGEVILLE_DANGER,
            command=self.sign_out,
        ).pack(fill="x", padx=16, pady=(0, 16))

        self.sidebar_date = ctk.CTkLabel(
            sidebar,
            text="",
            font=font("small"),
            text_color=UI_TEXT_MUTED,
        )
        self.sidebar_date.pack(side="bottom", pady=16)

    def _build_main_area(self) -> None:
        main = ctk.CTkFrame(self.shell, fg_color=UI_BG, corner_radius=0)
        main.grid(row=0, column=1, sticky="nsew", padx=(0, 0), pady=0)
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(1, weight=1)

        topbar_wrap = ctk.CTkFrame(main, fg_color=UI_BG, corner_radius=0)
        topbar_wrap.grid(row=0, column=0, sticky="ew")
        topbar_wrap.grid_columnconfigure(0, weight=1)
        self.topbar = ctk.CTkFrame(
            topbar_wrap,
            fg_color=UI_SURFACE,
            height=TOPBAR_HEIGHT,
            corner_radius=0,
            border_width=1,
            border_color=UI_BORDER,
        )
        self.topbar.grid(row=0, column=0, sticky="ew")
        self.topbar.grid_propagate(False)
        tactical_stripe(self.topbar, side="bottom")

        title_block = ctk.CTkFrame(self.topbar, fg_color="transparent")
        title_block.pack(side="left", fill="y", padx=24, pady=(12, 10))
        self.page_title = ctk.CTkLabel(title_block, text="", font=font("heading"), anchor="w")
        self.page_title.pack(fill="x")
        self.topbar_subtitle = ctk.CTkLabel(
            title_block,
            text="",
            font=font("small"),
            text_color=UI_TEXT_MUTED,
            anchor="w",
        )
        self.topbar_subtitle.pack(fill="x", pady=(2, 0))

        topbar_right = ctk.CTkFrame(self.topbar, fg_color="transparent")
        topbar_right.pack(side="right", fill="y", padx=(0, 24), pady=12)
        self.user_badge = ctk.CTkLabel(
            topbar_right,
            text="",
            font=font("small"),
            text_color=UI_TEXT_MUTED,
            cursor="hand2",
        )
        self.user_badge.pack(side="right", padx=(12, 0))
        self.user_badge.bind("<Button-1>", lambda e: open_my_profile_dialog(self))
        topbar_logo = load_logo((44, 44))
        if topbar_logo:
            self._remember_brand_image(topbar_logo)
            ctk.CTkLabel(topbar_right, text="", image=topbar_logo).pack(side="right")

        self.subnav = SubNavBar(topbar_wrap, on_select=self.show_page)
        self.subnav.grid(row=1, column=0, sticky="ew")
        self.subnav.grid_remove()

        self.content = ctk.CTkFrame(main, fg_color=UI_BG, corner_radius=0)
        self.content.grid(row=1, column=0, sticky="nsew", padx=CONTENT_PAD, pady=(12, CONTENT_PAD))
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)

        self.statusbar = ctk.CTkLabel(
            main,
            text="SYS :: Ready",
            font=font("mono"),
            text_color=UI_ACCENT_GLOW,
            anchor="w",
            height=28,
        )
        self.statusbar.grid(row=2, column=0, sticky="ew", padx=24, pady=(0, 8))

        for key, label, _ in NAV_ITEMS:
            frame = ctk.CTkFrame(self.content, fg_color=UI_BG)
            self.pages[key] = frame

        self._build_dashboard()
        self._build_base_schedule()
        self._build_live_schedule()
        self._build_timecard()
        self._build_banked_time()
        self._build_timeline()
        self._build_requests()
        self._build_swaps()
        self._build_notifications()
        self._build_officers()
        self._build_payroll()
        self._build_simulator()
        self._build_reports()
        self._build_availability()
        self._build_users()

    def show_page(self, key: str) -> None:
        if key == "notifications":
            key = "dashboard"
        if key == "updated_schedule":
            key = "live_schedule"
        key = resolve_nav_target(key)
        if key not in self.pages:
            return
        for k, frame in self.pages.items():
            frame.grid_forget()
        self.pages[key].grid(row=0, column=0, sticky="nsew")
        self.page_title.configure(text=page_title(key))
        if self._is_officer_role():
            subtitle = title_case_ui(OFFICER_PAGE_SUBTITLES.get(key, PAGE_SUBTITLES.get(key, "")))
        else:
            subtitle = title_case_ui(PAGE_SUBTITLES.get(key, ""))
        self.topbar_subtitle.configure(text=subtitle)
        for k, btn in self.nav_buttons.items():
            if k in NAV_HUBS:
                btn.set_active(key in NAV_HUBS[k]["pages"])
            else:
                btn.set_active(k == key)
        self._update_subnav(key)
        self.current_page = key
        self._refresh_page(key)
        self._update_sidebar_date()
        self._update_notification_badge()
        self._update_user_badge()

    def set_status(self, message: str) -> None:
        self.statusbar.configure(text=message)

    def _export_pdf_result(self, result, label: str) -> None:
        handle_export_result(result, label=label, set_status=self.set_status)

    def _update_notification_badge(self) -> None:
        officer_id = self._linked_officer_id() if self._is_officer_role() else None
        count = get_unread_notification_count(officer_id=officer_id)
        btn = self.nav_buttons.get("dashboard")
        if btn:
            btn.set_badge(count)

    def _update_user_badge(self) -> None:
        if not hasattr(self, "user_badge") or not self.current_user:
            return
        name = self.current_user.get("officer_name") or self.current_user.get("username")
        self.user_badge.configure(text=name)

    def _update_sidebar_date(self) -> None:
        today = date.today()
        cycle = get_cycle_day(today)
        squad = get_squad_on_duty(cycle)
        self.sidebar_date.configure(
            text=f"{format_date(today)}\nCycle Day {cycle} · Squad {squad}",
        )

    def refresh_all(self) -> None:
        self._refresh_page(self.current_page)
        if self.current_page != "dashboard":
            self._refresh_dashboard_data()
        self.set_status("Data refreshed")

    def backup_database(self) -> None:
        if not self.can("database.backup"):
            messagebox.showwarning("Permission", "Only Supervisor or Administration can backup.")
            return
        try:
            path = backup_database()
            uid = self.current_user.get("id") if self.current_user else None
            log_audit_action("database.backup", "database", None, uid, path)
            messagebox.showinfo("Backup Complete", f"Database saved to:\n{path}")
            self.set_status(f"Backup saved: {path}")
        except Exception as exc:
            messagebox.showerror("Backup Failed", str(exc))

    def _refresh_current_page(self) -> None:
        if self.current_page:
            self._refresh_page(self.current_page)
            self.set_status("Page refreshed")

    def _bind_keyboard_shortcuts(self) -> None:
        shortcuts: list[tuple[str, str]] = []
        for entry in SIDEBAR_NAV:
            if entry[0] == "section":
                continue
            nav_key = entry[0]
            if nav_key not in self.nav_buttons:
                continue
            shortcuts.append((nav_key, resolve_nav_target(nav_key)))
        self.root.bind("<Control-Key-0>", lambda e: self.show_page("dashboard"))
        self.root.bind("<Control-Shift-Q>", lambda e: self.sign_out())
        for index, (_nav_key, page_key) in enumerate(shortcuts[:9], start=1):
            self.root.bind(
                f"<Control-Key-{index}>",
                lambda e, page=page_key: self.show_page(page),
            )

    def _refresh_page(self, key: str) -> None:
        refreshers = {
            "dashboard": self._refresh_dashboard,
            "base_schedule": lambda: self.refresh_monthly("base"),
            "live_schedule": lambda: self.refresh_monthly("updated"),
            "timecard": self.refresh_timecard,
            "banked_time": self.refresh_banked_time,
            "timeline": self.refresh_gantt,
            "requests": self.refresh_requests,
            "swaps": self.refresh_swaps,
            "notifications": lambda: (self.show_page("dashboard"), self.refresh_notifications()),
            "officers": self.refresh_officer_list,
            "payroll": self.refresh_payroll,
            "simulator": lambda: None,
            "reports": self.refresh_reports,
            "availability": self.refresh_availability,
            "users": self.refresh_users,
        }
        refreshers.get(key, lambda: None)()
