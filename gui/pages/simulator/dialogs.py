"""Simulator dialogs extracted from page.py."""

from __future__ import annotations

import re
from typing import Awaitable, Callable, List, Optional

from nicegui import ui


def open_large_search_dialog(
    *,
    warning: str,
    on_run: Callable[[], Awaitable[None] | None],
    on_cancel: Optional[Callable[[], None]] = None,
) -> None:
    """Confirm before exhaustive free-space search."""
    with (
        ui.dialog() as cdlg,
        ui.card()
        .classes("q-pa-md")
        .style(
            "min-width:22rem;max-width:32rem;background:#0C1A2E;color:#E8EDF4;border:1px solid rgba(234,179,8,0.45)"
        ),
    ):
        ui.label("Large Search Space").style("font-size:1.1rem;font-weight:700;color:#FDE68A")
        ui.label(warning or "").style("color:#9AABC4;margin:12px 0;line-height:1.45;white-space:pre-wrap")

        async def _go():
            cdlg.close()
            import asyncio

            await asyncio.sleep(0.05)
            res = on_run()
            if hasattr(res, "__await__"):
                await res  # type: ignore[misc]

        def _stop():
            cdlg.close()
            if on_cancel:
                on_cancel()
            else:
                ui.notify(
                    "Search cancelled — lock more constraints to shrink space",
                    type="info",
                )

        with ui.row().classes("gap-2 flex-wrap"):
            ui.button("Run Full Search Anyway", on_click=_go).classes("btn-primary").props("no-caps unelevated")
            ui.button("Cancel", on_click=_stop).classes("btn-ghost").props("no-caps outline")
    cdlg.open()


def open_no_match_dialog(
    *,
    evaluated: int,
    rejected: int,
    extra: str = "",
    near_misses: Optional[List[dict]] = None,
    opt_result: Optional[dict] = None,
    config: Optional[dict] = None,
    apply_relaxation: Optional[Callable[[dict], bool]] = None,
    on_apply_and_research: Optional[Callable[[], Awaitable[None]]] = None,
    on_pick_near_miss: Optional[Callable[[dict], None]] = None,
    on_soften: Optional[Callable[[], Awaitable[None]]] = None,
    on_research: Optional[Callable[[], Awaitable[None]]] = None,
    on_close_summary: Optional[Callable[[], None]] = None,
) -> None:
    """No hard match — relaxations, near-misses, soften / re-search."""
    with (
        ui.dialog() as dlg,
        ui.card()
        .classes("q-pa-md")
        .style(
            "min-width:24rem;max-width:36rem;background:#0C1A2E;color:#E8EDF4;border:1px solid rgba(91,141,239,0.4)"
        ),
    ):
        ui.label("No Perfect Schedule").style("font-size:1.15rem;font-weight:700;color:#F8FAFC")
        body = (
            "No plan meets every selected hard requirement after checking "
            f"{evaluated or rejected:,} layout(s) ({rejected:,} ruled out).\n\n"
            "Annual hours use a year-average (365.25-day) model — officers will not "
            "all work identical hours in a calendar year when cycles do not divide "
            "365/366 evenly; the optimizer looks for similar hours across the roster.\n\n"
            "Closest alternatives (if any) are listed below. Reorder Constraint "
            "Priority above, then search again to re-rank tradeoffs."
        )
        if extra:
            body += f"\n\n{extra}"
        ui.label(body).style("color:#9AABC4;margin:12px 0;line-height:1.45;white-space:pre-wrap")

        # Structured constraint autopsy (Timefold-style explain / WFM gap board)
        try:
            from logic.constraint_autopsy import constraint_autopsy

            auto = constraint_autopsy(opt_result or {}, config or {})
            if auto.get("reasons") or auto.get("summary"):
                ui.label("Why It Failed").style("color:#FCA5A5;font-weight:700;margin-top:6px")
                if auto.get("summary"):
                    ui.label(str(auto["summary"])).style(
                        "color:#FDE68A;font-size:0.9rem;margin:4px 0 8px;line-height:1.4"
                    )
                for reason in (auto.get("reasons") or [])[:5]:
                    ui.label(f"· {reason.get('label')}: {reason.get('detail') or reason.get('count')}").style(
                        "color:#E8EDF4;font-size:0.88rem;margin-top:2px"
                    )
        except Exception:
            pass

        sugs: list = []
        try:
            from logic.optimizer_features import suggest_relaxations

            sugs = suggest_relaxations(opt_result or {}, config or {}) or []
        except Exception:
            sugs = []
        if not sugs:
            try:
                from logic.constraint_autopsy import constraint_autopsy

                for u in (constraint_autopsy(opt_result or {}, config or {}).get("unlocks") or [])[:3]:
                    sugs.append(
                        {
                            "action": u.get("action"),
                            "why": u.get("why"),
                            "estimated_unlock": u.get("estimated_unlock"),
                            "category": u.get("category") or "general",
                        }
                    )
            except Exception:
                pass

        if sugs and apply_relaxation and on_apply_and_research:
            ui.label("Fix it with one click").style("color:#86efac;font-weight:600;margin-top:4px")
            for s in sugs[:3]:

                async def _try_fix(sg=s):
                    if not apply_relaxation(sg):
                        ui.notify("Could not auto-apply — adjust the form manually", type="warning")
                        return
                    dlg.close()
                    await on_apply_and_research()

                ui.button(
                    f"{s.get('action', '')}",
                    icon="auto_fix_high",
                    on_click=_try_fix,
                ).classes("btn-primary q-mt-xs").props("no-caps unelevated align=left dense").style(
                    "width:100%;text-align:left;white-space:normal"
                )
                ui.label(s.get("why", "")).style("color:#9AABC4;font-size:0.85rem;margin-bottom:8px;margin-left:14px")

        misses = list(near_misses or [])[:5]
        if misses and on_pick_near_miss:
            ui.label("Closest Alternatives").style("color:#E8EDF4;font-weight:600;margin-top:10px")
            for nm in misses:

                def _pick(row=nm):
                    dlg.close()
                    on_pick_near_miss(row)

                ui.button(
                    (nm.get("summary") or "Alternative")[:120],
                    on_click=_pick,
                ).classes("btn-ghost q-mt-xs").props("no-caps outline dense align=left").style(
                    "width:100%;text-align:left;white-space:normal"
                )

        async def _soften():
            dlg.close()
            if on_soften:
                await on_soften()

        async def _research():
            dlg.close()
            if on_research:
                await on_research()

        def _cancel():
            dlg.close()
            if on_close_summary:
                on_close_summary()

        with ui.row().classes("gap-2 flex-wrap q-mt-md"):
            ui.button("Search Again With Current Priority", on_click=_research).classes("btn-primary").props(
                "no-caps unelevated"
            )
            ui.button("Soften & Search", on_click=_soften).classes("btn-ghost").props("no-caps outline")
            ui.button("Close", on_click=_cancel).classes("btn-ghost").props("no-caps outline")
    dlg.open()


def last_int_in_text(text: str) -> Optional[int]:
    nums = re.findall(r"\d+", text or "")
    return int(nums[-1]) if nums else None
