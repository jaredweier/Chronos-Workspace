"""Chronos Command — NiceGUI entry (web host + downloadable native window).

Modes:
  python main.py              # default: native window if available, else browser
  python main.py --web        # host online: bind 0.0.0.0
  python main.py --browser    # local browser (127.0.0.1)
  python main.py --native     # native window (pywebview)
"""

from __future__ import annotations

import argparse
import logging
import os
import secrets
import sys
from pathlib import Path

from nicegui import app, ui

from database import init_database
from gui.pages.access import render_access
from gui.pages.audit_trail import render_audit_trail
from gui.pages.availability import render_availability
from gui.pages.bidding import render_bidding
from gui.pages.callbacks import render_callbacks
from gui.pages.certs import render_certs
from gui.pages.channels import render_channels
from gui.pages.court import render_court
from gui.pages.dashboard import render_dashboard
from gui.pages.deploy import render_deploy
from gui.pages.exports_hub import render_exports_hub
from gui.pages.finance import render_banks, render_payroll, render_timecards
from gui.pages.leave import render_leave
from gui.pages.login import render_login
from gui.pages.media import render_media
from gui.pages.notifications import render_notifications
from gui.pages.operations import render_operations
from gui.pages.ops_desk import render_ops_desk
from gui.pages.roster import render_roster
from gui.pages.schedules import render_live_schedule, render_monthly_schedule, render_my_schedule
from gui.pages.security import render_security
from gui.pages.self_service import render_open_shifts
from gui.pages.simulator import render_simulator
from gui.pages.uat_hub import render_uat_hub

log = logging.getLogger("chronos.gui")


def _register_api_routes() -> None:
    """Offline snapshot + CAD inbound (bidirectional residual)."""
    try:
        from starlette.requests import Request
        from starlette.responses import JSONResponse
    except Exception:
        return

    @app.get("/api/offline/snapshot")
    async def api_offline_snapshot(request: Request):  # type: ignore[no-redef]
        from logic.offline_api import build_offline_snapshot

        officer_id = None
        try:
            from gui import session as gui_session

            officer_id = gui_session.linked_officer_id()
        except Exception:
            pass
        q = request.query_params.get("officer_id")
        if q:
            try:
                officer_id = int(q)
            except ValueError:
                pass
        snap = build_offline_snapshot(officer_id=officer_id)
        return JSONResponse(snap)

    @app.post("/api/offline/mutations")
    async def api_offline_mutations(request: Request):  # type: ignore[no-redef]
        """Apply client offline mutation queue on reconnect."""
        from logic.offline_api import apply_offline_mutations

        user_id = None
        officer_id = None
        try:
            from gui import session as gui_session

            u = gui_session.current_user() or {}
            user_id = u.get("id")
            officer_id = gui_session.linked_officer_id()
        except Exception:
            pass
        try:
            body = await request.json()
        except Exception:
            body = {}
        items = body.get("items") or body.get("mutations") or body.get("queue") or []
        if body.get("officer_id") and not officer_id:
            try:
                officer_id = int(body.get("officer_id"))
            except (TypeError, ValueError):
                pass
        result = apply_offline_mutations(items, user_id=user_id, officer_id=officer_id)
        status = 200 if result.get("success") or result.get("applied") else 400
        return JSONResponse(result, status_code=status)

    @app.post("/api/cad/inbound")
    async def api_cad_inbound(request: Request):  # type: ignore[no-redef]
        from logic.cad_rms_bridge import receive_cad_inbound

        token = request.headers.get("X-Chronos-CAD-Token") or request.query_params.get("token") or ""
        try:
            body = await request.json()
        except Exception:
            body = {}
        result = receive_cad_inbound(body, token=token)
        status = 401 if result.get("http_status") == 401 else (200 if result.get("success") else 400)
        return JSONResponse(result, status_code=status)

    @app.get("/api/cad/status")
    async def api_cad_status():  # type: ignore[no-redef]
        from logic.cad_rms_bridge import cad_bridge_status

        return JSONResponse(cad_bridge_status())


@ui.page("/login")
def page_login() -> None:
    render_login()


@ui.page("/")
def page_home() -> None:
    render_dashboard()


# —— Scheduling ——
@ui.page("/my-schedule")
def page_my_schedule() -> None:
    render_my_schedule()


@ui.page("/monthly-schedule")
def page_monthly() -> None:
    render_monthly_schedule()


@ui.page("/live-schedule")
def page_live() -> None:
    render_live_schedule()


@ui.page("/time-off")
def page_time_off() -> None:
    render_leave()


@ui.page("/open-shifts")
def page_open_shifts() -> None:
    render_open_shifts()


@ui.page("/bidding")
def page_bidding() -> None:
    render_bidding()


@ui.page("/callbacks")
def page_callbacks() -> None:
    render_callbacks()


@ui.page("/court")
def page_court() -> None:
    render_court()


@ui.page("/availability")
def page_availability() -> None:
    render_availability()


@ui.page("/notifications")
def page_notifications() -> None:
    render_notifications()


@ui.page("/certs")
def page_certs() -> None:
    render_certs()


@ui.page("/channels")
def page_channels() -> None:
    render_channels()


@ui.page("/deploy")
def page_deploy() -> None:
    render_deploy()


@ui.page("/audit")
def page_audit() -> None:
    render_audit_trail()


@ui.page("/my-week")
def page_my_week() -> None:
    """Officer mobile-first week home (alias of dashboard self-service strip)."""
    from gui.pages.mobile_home import render_mobile_home

    render_mobile_home()


@ui.page("/time-punch")
def page_time_punch() -> None:
    from gui.pages.time_punch import render_time_punch

    render_time_punch()


# Legacy redirects
@ui.page("/schedules")
def page_schedules_legacy() -> None:
    ui.navigate.to("/live-schedule")


@ui.page("/timeline")
def page_timeline_legacy() -> None:
    ui.navigate.to("/my-schedule")


@ui.page("/leave")
def page_leave_legacy() -> None:
    ui.navigate.to("/time-off")


@ui.page("/finance")
def page_finance_legacy() -> None:
    ui.navigate.to("/timecards")


# —— Personnel ——
@ui.page("/roster")
def page_roster() -> None:
    render_roster()


@ui.page("/media")
def page_media() -> None:
    render_media()


# —— Finance ——
@ui.page("/timecards")
def page_timecards() -> None:
    render_timecards()


@ui.page("/payroll")
def page_payroll() -> None:
    render_payroll()


@ui.page("/banks")
def page_banks() -> None:
    render_banks()


# —— Command ——
@ui.page("/simulator")
def page_simulator() -> None:
    render_simulator()


@ui.page("/operations")
def page_operations() -> None:
    render_operations()


@ui.page("/exports")
def page_exports() -> None:
    render_exports_hub()


@ui.page("/ops-desk")
def page_ops_desk() -> None:
    render_ops_desk()


@ui.page("/security")
def page_security() -> None:
    render_security()


@ui.page("/access")
def page_access() -> None:
    render_access()


@ui.page("/uat")
def page_uat() -> None:
    render_uat_hub()


def _storage_secret() -> str:
    env = os.environ.get("SCHEDULER_STORAGE_SECRET", "").strip()
    if env:
        return env
    try:
        from paths import data_path

        path = Path(data_path("storage_secret.txt"))
        if path.is_file():
            return path.read_text(encoding="utf-8").strip()
        path.parent.mkdir(parents=True, exist_ok=True)
        secret = secrets.token_hex(32)
        path.write_text(secret, encoding="utf-8")
        return secret
    except Exception:
        return secrets.token_hex(32)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Chronos Command")
    p.add_argument("--web", action="store_true", help="Host for online access")
    p.add_argument("--browser", action="store_true", help="Local browser only")
    p.add_argument("--native", action="store_true", help="Native desktop window")
    p.add_argument("--host", default=None)
    p.add_argument("--port", type=int, default=None)
    p.add_argument("--reload", action="store_true")
    return p.parse_args(argv)


def _resolve_mode(args: argparse.Namespace) -> str:
    env = os.environ.get("SCHEDULER_UI_MODE", "").strip().lower()
    if args.web or env == "web":
        return "web"
    if args.browser or env == "browser":
        return "browser"
    if args.native or env == "native":
        return "native"
    try:
        import webview  # noqa: F401

        return "native"
    except Exception:
        return "browser"


def _ensure_static_css() -> None:
    """Sync theme CSS to gui/static and mount /static for reliable stylesheet load."""
    from gui.theme import GLOBAL_CSS

    static_dir = Path(__file__).resolve().parent / "static"
    static_dir.mkdir(parents=True, exist_ok=True)
    css_path = static_dir / "chronos.css"
    try:
        if not (css_path.is_file() and css_path.read_text(encoding="utf-8") == GLOBAL_CSS):
            css_path.write_text(GLOBAL_CSS, encoding="utf-8")
    except OSError as exc:
        log.warning("Could not write chronos.css: %s", exc)
    try:
        app.add_static_files("/static", str(static_dir))
    except Exception as exc:
        log.warning("Could not mount /static: %s", exc)


def _centered_native_geometry() -> tuple[int, int]:
    """Size native window from the primary display and center it (x/y + size)."""
    w, h = 1280, 800
    try:
        import ctypes

        try:
            # Per-monitor DPI so GetSystemMetrics matches real pixels
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # type: ignore[attr-defined]
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass
        user32 = ctypes.windll.user32
        sw = int(user32.GetSystemMetrics(0))
        sh = int(user32.GetSystemMetrics(1))
        if sw > 200 and sh > 200:
            w = min(1400, max(1024, int(sw * 0.75)))
            h = min(900, max(700, int(sh * 0.78)))
            w = min(w, sw - 32)
            h = min(h, sh - 48)
            x = max(0, (sw - w) // 2)
            y = max(0, (sh - h) // 2)
            # pywebview create_window kwargs (merged after width/height)
            app.native.window_args.clear()
            app.native.window_args.update(
                {
                    "width": w,
                    "height": h,
                    "x": x,
                    "y": y,
                    "resizable": True,
                    "minimized": False,
                    "maximized": False,
                    "fullscreen": False,
                    "focus": True,
                }
            )
            log.info("Native window centered x=%s y=%s w=%s h=%s (display %sx%s)", x, y, w, h, sw, sh)
    except Exception as exc:
        log.warning("Display metrics unavailable: %s", exc)
        app.native.window_args.update({"width": w, "height": h, "x": 80, "y": 60})
    return w, h


def run(argv: list[str] | None = None) -> None:
    from config import APP_NAME, APP_VERSION, configure_logging

    configure_logging()
    init_database()
    try:
        from logic.uat_lab import prepare_uat_lab, uat_lab_enabled

        if uat_lab_enabled():
            prep = prepare_uat_lab()
            log.info("UAT lab prep: %s", prep)
            print(f"UAT lab: {prep.get('notes') or prep}")
    except Exception as exc:
        log.warning("UAT lab prep skipped: %s", exc)
    _ensure_static_css()
    _register_api_routes()

    args = _parse_args(argv if argv is not None else sys.argv[1:])
    mode = _resolve_mode(args)
    port = args.port or int(os.environ.get("SCHEDULER_PORT", "8080"))
    if mode == "web":
        host = args.host or os.environ.get("SCHEDULER_HOST", "0.0.0.0")
        show, native = False, False
    elif mode == "native":
        host = args.host or "127.0.0.1"
        show, native = False, True
    else:
        host = args.host or "127.0.0.1"
        show, native = True, False

    secret = _storage_secret()
    title = f"{APP_NAME}"
    window_size = None
    if native:
        window_size = _centered_native_geometry()
    log.info("Starting Chronos Command mode=%s host=%s port=%s v%s", mode, host, port, APP_VERSION)
    if mode == "web":
        print(f"\n=== {title} (ONLINE) ===\nListening http://{host}:{port}\n")
    elif mode == "native":
        print(f"\n=== {title} (DESKTOP) ===\nwindow={window_size}\n")
    else:
        print(f"\n=== {title} (BROWSER) ===\nhttp://{host}:{port}\n")

    # Longer reconnect + history help Cloudflare quick-tunnels (WS blips common).
    # UAT stable mode: never enable NiceGUI/uvicorn file-reload mid-session.
    reconnect = float(os.environ.get("SCHEDULER_RECONNECT_TIMEOUT", "120") or "120")
    uat_stable = (os.environ.get("SCHEDULER_UAT_LAB") or "").strip() in ("1", "true", "yes") or (
        os.environ.get("SCHEDULER_UAT_STABLE") or ""
    ).strip() in ("1", "true", "yes")
    do_reload = bool(args.reload) and not uat_stable
    # Slightly slower binding pull reduces WebSocket chatter under tunnels
    bind_iv = float(os.environ.get("SCHEDULER_BINDING_INTERVAL", "0.25") or "0.25")

    # The simulator page (large ranked-option lists, coverage-by-day grids,
    # heatmap matrices) can push a single reactive update past python-socketio's
    # 1 MB default Engine.IO frame size, which the client reports as "Message
    # too long" and forces a disconnect/reconnect loop. Raise the ceiling
    # before starting the server.
    try:
        from nicegui import core as _nicegui_core

        _nicegui_core.sio.eio.max_http_buffer_size = int(
            os.environ.get("SCHEDULER_WS_MAX_BUFFER_BYTES", "10000000") or "10000000"
        )
    except Exception:
        pass

    ui.run(
        title=title,
        host=host,
        port=port,
        dark=True,
        reload=do_reload,
        show=show,
        native=native,
        window_size=window_size,
        storage_secret=secret,
        favicon="🛡️",
        uvicorn_logging_level="warning",
        show_welcome_message=mode == "web",
        reconnect_timeout=reconnect,
        message_history_length=2000,
        binding_refresh_interval=bind_iv,
        prod_js=True,
    )


if __name__ in {"__main__", "__mp_main__"}:
    run()
