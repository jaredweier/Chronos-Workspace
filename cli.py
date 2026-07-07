#!/usr/bin/env python3
"""
Dodgeville Police Department Scheduler - Admin CLI
"""

import argparse
from datetime import date

from config import DAY_OFF_REQUEST_TYPES
from database import backup_database
from logic import (
    add_holiday,
    add_officer_availability,
    admin_reset_user_password,
    bulk_approve_auto_ok_requests,
    bulk_reject_pending_requests,
    compare_base_updated_schedule,
    create_app_user,
    create_day_off_request,
    create_manual_coverage_override,
    create_open_shift,
    create_shift_swap_request,
    delete_holiday,
    delete_officer_availability,
    export_audit_csv,
    export_coverage_pdf,
    export_officer_schedule_ical,
    export_pay_period_history_csv,
    export_payroll_csv,
    export_payroll_pdf,
    export_requests_csv,
    export_requests_pdf,
    export_roster_csv,
    export_schedule_diff_csv,
    export_schedule_pdf,
    export_shift_swaps_csv,
    export_shift_swaps_pdf,
    export_timecard_csv,
    fill_open_shift,
    get_audit_log,
    get_coverage_report,
    get_current_cycle_window,
    get_dashboard_insights,
    get_day_off_requests,
    get_department_setting,
    get_holidays,
    get_labor_compliance_report,
    get_notifications,
    get_officer_availability,
    get_officers_by_seniority,
    get_open_shifts,
    get_overtime_alerts,
    get_pay_period_history,
    get_pending_day_off_requests,
    get_pending_shift_swap_requests,
    get_schedule_conflicts,
    get_shift_swap_requests,
    get_unread_notification_count,
    import_roster_from_csv,
    is_pay_period_locked,
    list_all_users,
    lock_pay_period,
    mark_all_notifications_read,
    mark_notification_read,
    process_day_off_request,
    process_shift_swap,
    resolve_notification_navigation,
    set_app_user_active,
    set_department_setting,
    unlock_pay_period,
    update_app_user,
)
from logic import (
    add_officer as logic_add_officer,
)
from logic import (
    delete_officer as logic_delete_officer,
)
from logic import (
    update_officer as logic_update_officer,
)
from permissions import USER_ROLES
from validators import format_date, parse_date


def list_officers():
    officers = get_officers_by_seniority()
    if not officers:
        print("No officers found.")
        return

    from validators import format_officer_title_display

    print(
        f"{'ID':<5} {'Name':<22} {'Title':<22} {'Squad':<6} {'Shift':<15} {'Start':<12} "
        f"{'Phone':<16} {'Email':<24} {'Active':<6}"
    )
    print("-" * 140)
    for o in officers:
        shift = f"{o['shift_start']}-{o['shift_end']}"
        active = "Yes" if o.get("active") == 1 else "No"
        title = format_officer_title_display(o.get("job_title")) or "—"
        print(
            f"{o['id']:<5} {o['name']:<22} {title:<22} {o['squad']:<6} {shift:<15} "
            f"{(format_date(o['start_date']) if o.get('start_date') else '—'):<12} {(o.get('phone') or '—'):<16} "
            f"{(o.get('email') or '—'):<24} {active:<6}"
        )


def _validate_cli_job_title(job_title: str) -> bool:
    from validators import validate_officer_job_title

    if not job_title:
        return True
    check = validate_officer_job_title(job_title)
    if not check.ok:
        print(f"Error: {check.message}")
        return False
    return True


def list_officer_titles_cmd(_args):
    from logic import get_builtin_officer_titles, get_custom_officer_titles, get_officer_title_options

    print("Standard titles:", ", ".join(get_builtin_officer_titles()))
    custom = get_custom_officer_titles()
    if custom:
        print("Custom titles:", ", ".join(custom))
    else:
        print("Custom titles: (none)")
    print("All assignable:", ", ".join(get_officer_title_options()))


def add_officer_title_cmd(args):
    from logic import add_custom_officer_title

    result = add_custom_officer_title(args.title)
    if result.get("success"):
        print(result.get("message", "Title added"))
    else:
        print(f"Error: {result.get('message', 'Unknown error')}")


def add_officer(args):
    if args.job_title and not _validate_cli_job_title(args.job_title):
        return
    result = logic_add_officer(
        args.name,
        args.seniority,
        args.squad,
        args.shift_start,
        args.shift_end,
        args.pay_rate,
        start_date=args.start_date,
        email=args.email,
        phone=args.phone,
        address=args.address,
        job_title=args.job_title,
    )
    if result.get("success"):
        print(f"Officer '{args.name}' added successfully (ID: {result['officer_id']})")
    else:
        print(f"Error: {result.get('message', 'Unknown error')}")


def update_officer_cmd(args):
    if args.job_title and not _validate_cli_job_title(args.job_title):
        return
    fields = {}
    for key in (
        "name",
        "seniority_rank",
        "squad",
        "shift_start",
        "shift_end",
        "pay_rate",
        "start_date",
        "email",
        "phone",
        "address",
        "job_title",
    ):
        cli_key = key if key != "seniority_rank" else "seniority"
        value = getattr(args, cli_key, None)
        if value is not None:
            fields[key] = value
    if args.active is not None:
        fields["active"] = 1 if args.active else 0
    if not fields:
        print("Error: No fields to update")
        return
    result = logic_update_officer(args.officer_id, **fields)
    if result.get("success"):
        print(f"Officer {args.officer_id} updated successfully")
    else:
        print(f"Error: {result.get('message', 'Unknown error')}")


def delete_officer_cmd(args):
    result = logic_delete_officer(args.officer_id)
    if result.get("success"):
        print(result.get("message", "Officer deleted"))
    else:
        print(f"Error: {result.get('message', 'Unknown error')}")


def import_officers_cmd(args):
    result = import_roster_from_csv(args.file, update_existing=not args.skip_existing)
    print(result.get("message", "Done"))
    for detail in result.get("error_details", []):
        print(f"  {detail}")


def _print_requests_table(requests, empty_msg: str = "No requests."):
    if not requests:
        print(empty_msg)
        return
    print(f"{'ID':<5} {'Date':<12} {'Type':<18} {'Officer':<25} {'Squad':<6} {'Status':<20}")
    print("-" * 90)
    for r in requests:
        print(
            f"{r['id']:<5} {format_date(r['request_date']):<12} {r['request_type']:<18} "
            f"{r['officer_name']:<25} {r['squad']:<6} {r['status']:<20}"
        )


def list_pending_requests():
    _print_requests_table(get_pending_day_off_requests(), "No pending requests.")


def list_requests(args):
    status = None if args.status in (None, "all") else args.status
    requests = get_day_off_requests(
        status_filter=status,
        date_from=args.from_date,
        date_to=args.to_date,
    )
    _print_requests_table(requests, "No matching requests.")


def approve_request(request_id: int):
    result = process_day_off_request(request_id, action="approve")
    if result.success:
        print(result.message)
    elif result.requires_manual:
        print(f"Manual review required: {result.message}")
    else:
        print(f"Failed: {result.message}")


def reject_request(request_id: int):
    result = process_day_off_request(request_id, action="reject")
    print(result.message if result.success else f"Failed: {result.message}")


def submit_request_cmd(args):
    result = create_day_off_request(
        args.officer_id,
        args.date,
        args.type,
        notes=args.notes or "",
    )
    if result.get("success"):
        print(f"Request submitted (ID: {result['request_id']})")
    else:
        print(f"Error: {result.get('message', 'Unknown error')}")


def create_swap_cmd(args):
    result = create_shift_swap_request(args.officer1_id, args.officer2_id, args.date)
    if result.get("success"):
        print(f"Swap submitted (ID: {result['swap_id']}, status: {result.get('status')})")
    else:
        print(f"Error: {result.get('message', 'Unknown error')}")


def fill_open_shift_cmd(args):
    result = fill_open_shift(args.shift_id, args.officer_id)
    print("Open shift filled." if result.get("success") else f"Error: {result.get('message')}")


def delete_holiday_cmd(args):
    result = delete_holiday(args.holiday_id)
    print("Holiday deleted." if result.get("success") else f"Error: {result.get('message')}")


def delete_availability_cmd(args):
    result = delete_officer_availability(args.entry_id)
    print("Availability entry deleted." if result.get("success") else f"Error: {result.get('message')}")


def get_setting_cmd(args):
    value = get_department_setting(args.key, "")
    print(value if value else "(not set)")


def set_setting_cmd(args):
    result = set_department_setting(args.key, args.value)
    print("Setting saved." if result.get("success") else f"Error: {result.get('message')}")


def staffing_settings_cmd(args):
    from logic.staffing_config import get_staffing_config, save_staffing_settings

    if args.staffing_action == "show":
        config = get_staffing_config()
        print(f"Shift length: {config['shift_length_hours']} hours")
        print(f"Annual hours target: {config['annual_hours_target']}")
        print(f"Shift count: {config['shift_count']}")
        print(f"Target officers: {config['target_officer_count']} (active roster: {config['active_officer_count']})")
        print(f"Shift starts: {', '.join(config['shift_starts'])}")
        for band in config["shift_times"]:
            print(f"  {band['start']} – {band['end']}")
        return
    if args.staffing_action == "set":
        result = save_staffing_settings(
            shift_length_hours=args.shift_length,
            annual_hours_target=args.annual_hours,
            shift_count=args.shift_count,
            target_officer_count=args.target_officers,
            shift_starts_text=args.shift_starts or "",
        )
        if result.get("success"):
            print(result.get("message", "Staffing saved."))
        else:
            print(f"Error: {result.get('message')}")


def rotation_settings_cmd(args):
    from logic.rotation_config import get_rotation_config, save_rotation_settings

    if args.rotation_action == "show":
        config = get_rotation_config()
        print(f"Preset: {config['preset']}")
        print(f"Cycle length: {config['cycle_length']} days")
        print(f"Base date: {config['base_date']}")
        print(f"Squad A days: {config['squad_a_days']}")
        print(f"Schedule mode: {config.get('rust_schedule_mode')}")
        start, end = get_current_cycle_window()
        print(f"Current cycle: {format_date(start)} – {format_date(end)}")
        return
    if args.rotation_action == "set":
        result = save_rotation_settings(
            cycle_length=args.cycle_length,
            preset=args.preset,
            base_date_text=args.base_date or "",
            squad_a_days_text=args.squad_a_days or "",
        )
        if result.get("success"):
            print(result.get("message", "Rotation saved."))
        else:
            print(f"Error: {result.get('message')}")


def backup():
    path = backup_database()
    print(f"Database backed up to: {path}")


def _print_swaps_table(swaps, empty_msg: str = "No shift swaps."):
    if not swaps:
        print(empty_msg)
        return
    print(f"{'ID':<5} {'Date':<12} {'Officer 1':<22} {'Officer 2':<22} {'Status':<20}")
    print("-" * 85)
    for s in swaps:
        print(
            f"{s['id']:<5} {format_date(s['swap_date']):<12} {s['officer1_name']:<22} "
            f"{s['officer2_name']:<22} {s['status']:<20}"
        )


def list_pending_swaps():
    _print_swaps_table(get_pending_shift_swap_requests(), "No pending shift swaps.")


def list_swaps(args):
    if args.status == "pending":
        swaps = get_pending_shift_swap_requests(date_from=args.from_date, date_to=args.to_date)
    elif args.status in (None, "all"):
        swaps = get_shift_swap_requests(date_from=args.from_date, date_to=args.to_date)
    else:
        swaps = get_shift_swap_requests(
            status_filter=args.status,
            date_from=args.from_date,
            date_to=args.to_date,
        )
    _print_swaps_table(swaps, "No matching shift swaps.")


def approve_swap(swap_id: int):
    result = process_shift_swap(swap_id, action="approve")
    if result.success:
        print(result.message)
    elif result.requires_manual:
        print(f"Manual review required: {result.message}")
    else:
        print(f"Failed: {result.message}")


def reject_swap(swap_id: int):
    result = process_shift_swap(swap_id, action="reject")
    print(result.message if result.success else f"Failed: {result.message}")


def list_notifications(unread_only: bool = False, officer_id: int = None):
    notes = get_notifications(officer_id=officer_id, unread_only=unread_only)
    unread = get_unread_notification_count(officer_id=officer_id)
    if not notes:
        print(f"No notifications ({unread} unread).")
        return

    print(f"Notifications ({unread} unread):")
    print(f"{'ID':<5} {'To':<20} {'Type':<12} {'Title':<24} {'Nav':<14} {'Read':<6}")
    print("-" * 85)
    for n in notes:
        read_flag = "yes" if n.get("is_read") else "no"
        nav = (resolve_notification_navigation(n) or {}).get("page", "—")
        print(
            f"{n['id']:<5} {n.get('recipient_name', ''):<20} {n.get('type', ''):<12} "
            f"{n.get('title', '')[:24]:<24} {nav:<14} {read_flag:<6}"
        )


def read_notification(notification_id: int):
    result = mark_notification_read(notification_id)
    print("Marked read." if result.get("success") else f"Failed: {result.get('message')}")


def read_all_notifications(officer_id: int = None):
    result = mark_all_notifications_read(officer_id=officer_id)
    if result.get("success"):
        print(f"Marked {result.get('updated', 0)} notification(s) read.")
    else:
        print(f"Failed: {result.get('message')}")


def export_coverage(args):
    if args.start and args.end:
        start, end = parse_date(args.start), parse_date(args.end)
    else:
        start, end = get_current_cycle_window()
    result = export_coverage_pdf(start, end, output_path=args.output)
    if result.get("success"):
        print(f"Coverage PDF: {result['path']}")
    else:
        print(f"Failed: {result.get('message')}")


def export_schedule(args):
    if args.start and args.end:
        start = parse_date(args.start)
        end = parse_date(args.end)
    else:
        start, end = get_current_cycle_window()
    result = export_schedule_pdf(
        start,
        end,
        officer_id=args.officer_id,
        output_path=args.output,
    )
    if result.get("success"):
        print(f"Schedule PDF: {result['path']}")
    else:
        print(f"Failed: {result.get('message')}")


def export_payroll(args):
    period_start = parse_date(args.period_start) if args.period_start else None
    result = export_payroll_pdf(
        officer_id=args.officer_id,
        period_start=period_start,
        output_path=args.output,
    )
    if result.get("success"):
        print(f"Payroll PDF: {result['path']}")
    else:
        print(f"Failed: {result.get('message')}")


def export_requests(args):
    result = export_requests_pdf(
        status_filter=args.status,
        date_from=args.from_date,
        date_to=args.to_date,
        officer_id=args.officer_id,
        output_path=args.output,
    )
    if result.get("success"):
        print(f"Requests PDF: {result['path']}")
    else:
        print(f"Failed: {result.get('message')}")


def export_swaps_pdf_cmd(args):
    status = None
    pending_only = False
    if args.status:
        val = args.status.lower()
        if val == "all":
            status = None
        elif val == "pending":
            pending_only = True
        else:
            status = args.status
    result = export_shift_swaps_pdf(
        status_filter=status,
        date_from=args.from_date,
        date_to=args.to_date,
        officer_id=args.officer_id,
        pending_only=pending_only,
        output_path=args.output,
    )
    if result.get("success"):
        print(f"Shift swaps PDF: {result['path']}")
    else:
        print(f"Failed: {result.get('message')}")


def list_holidays(args):
    holidays = get_holidays(args.year)
    if not holidays:
        print("No holidays found.")
        return
    for h in holidays:
        paid = "paid" if h.get("is_paid") else "unpaid"
        print(f"{format_date(h['holiday_date']):<12} {h['name']:<24} {paid}")


def add_holiday_cmd(args):
    result = add_holiday(args.name, args.date, is_paid=not args.unpaid)
    if result.get("success"):
        print(f"Holiday added (ID: {result['holiday_id']})")
    else:
        print(f"Error: {result.get('message')}")


def reports_labor_compliance(args):
    report = get_labor_compliance_report(officer_id=args.officer_id)
    scope = f" (officer {args.officer_id})" if args.officer_id else ""
    print(f"Labor compliance{scope}")
    print(
        f"§207(k) {report.get('flsa_207k_period_days')}-day period "
        f"{report.get('flsa_207k_period_start')} – {report.get('flsa_207k_period_end')} "
        f"(threshold {report.get('flsa_207k_threshold')}h, rotation {report.get('rotation_cycle_length')}d)"
    )
    print(
        f"Comp cap: {report.get('comp_cap_hours')}h  |  Max consecutive days: {report.get('max_consecutive_work_days')}"
    )
    print(f"Issues: {report.get('issue_count', 0)}")
    for item in report.get("issues", []):
        print(f"  [{item.get('severity', '?').upper()}] {item['officer_name']}: {item['message']}")


def reports_summary(args):
    insights = get_dashboard_insights(officer_id=args.officer_id)
    scope = f" (officer {args.officer_id})" if args.officer_id else ""
    print(f"Dashboard summary{scope}")
    print(f"Coverage issues (cycle): {insights.get('coverage_issues', 0)}")
    print(f"Overtime alerts: {insights.get('overtime_alerts', 0)}")
    print(f"Schedule conflicts: {insights.get('schedule_conflicts', 0)}")
    print(f"Schedule changes (month): {insights.get('schedule_diff_count', 0)}")
    print(f"Pending requests: {insights.get('pending_requests', 0)}")
    print(f"Pending swaps: {insights.get('pending_swaps', 0)}")
    print(f"Labor compliance issues: {insights.get('labor_compliance_count', 0)}")
    if insights.get("officer_scoped"):
        print(f"Pending manual review: {insights.get('pending_manual_review', 0)}")
        print(f"Claimable open shifts: {insights.get('claimable_open_shifts', 0)}")
    else:
        print(f"Open shifts posted: {insights.get('open_shifts', 0)}")
        print(f"Monthly labor (proj.): ${insights.get('monthly_labor_cost', 0):,.0f}")
        budget = insights.get("labor_budget") or {}
        if budget.get("configured"):
            print(
                f"Labor budget YTD: ${budget['ytd_spent']:,.0f} / ${budget['annual_budget']:,.0f} "
                f"({budget['ytd_pct']:.0f}%)"
            )


def reports_coverage(args):
    if args.start and args.end:
        start, end = parse_date(args.start), parse_date(args.end)
    else:
        start, end = get_current_cycle_window()
    report = get_coverage_report(start, end)
    print(f"Coverage {report['start_date']} – {report['end_date']}: {report['issue_count']} issue(s)")
    for issue in report.get("issues", []):
        print(f"  {issue['date']} Squad {issue['squad_on_duty']}: {issue['night_issues']}")


def export_roster(args):
    result = export_roster_csv(output_path=args.output)
    if result.get("success"):
        print(f"Roster CSV: {result['path']} ({result['count']} rows)")
    else:
        print(f"Failed: {result.get('message')}")


def schedule_diff_cmd(args):
    year = args.year or date.today().year
    month = args.month or date.today().month
    if args.output:
        result = export_schedule_diff_csv(
            year,
            month,
            args.output,
            officer_id=args.officer_id,
        )
        if result.get("success"):
            print(f"Schedule diff CSV: {result['path']} ({result['count']} rows)")
        else:
            print(f"Failed: {result.get('message')}")
        return
    result = compare_base_updated_schedule(year, month, officer_id=args.officer_id)
    if not result.get("success"):
        print(f"Failed: {result.get('message')}")
        return
    print(f"Base vs Updated — {year}-{month:02d}: {result['diff_count']} change(s)")
    for item in result.get("diffs", [])[: args.limit]:
        print(
            f"  {item['assignment_date']}  {item['officer_name']:<20}  "
            f"{item['base_status'] or '—'} → {item['updated_status'] or '—'}"
        )


def export_payroll_csv_cmd(args):
    period = parse_date(args.period_start) if args.period_start else None
    result = export_payroll_csv(
        period_start=period,
        officer_id=args.officer_id,
        output_path=args.output,
    )
    if result.get("success"):
        print(f"Payroll CSV: {result['path']} ({result['count']} rows)")
    else:
        print(f"Failed: {result.get('message')}")


def export_requests_csv_cmd(args):
    status = None if not args.status or args.status.lower() == "all" else args.status
    result = export_requests_csv(
        status_filter=status,
        date_from=args.from_date,
        date_to=args.to_date,
        officer_id=args.officer_id,
        output_path=args.output,
    )
    if result.get("success"):
        print(f"Requests CSV: {result['path']} ({result['count']} rows)")
    else:
        print(f"Failed: {result.get('message')}")


def export_pay_period_history_csv_cmd(args):
    result = export_pay_period_history_csv(
        limit=args.limit,
        officer_id=args.officer_id,
        output_path=args.output,
    )
    if result.get("success"):
        print(f"Pay period history CSV: {result['path']} ({result['count']} rows)")
    else:
        print(f"Failed: {result.get('message')}")


def export_timecard_csv_cmd(args):
    period = parse_date(args.period_start) if args.period_start else None
    result = export_timecard_csv(
        period_start=period,
        officer_id=args.officer_id,
        output_path=args.output,
    )
    if result.get("success"):
        print(f"Timecard CSV: {result['path']} ({result['count']} rows)")
    else:
        print(f"Failed: {result.get('message')}")


def export_shift_swaps_csv_cmd(args):
    status = None
    pending_only = False
    if args.status:
        val = args.status.lower()
        if val == "all":
            status = None
        elif val == "pending":
            pending_only = True
        else:
            status = args.status
    result = export_shift_swaps_csv(
        status_filter=status,
        date_from=args.from_date,
        date_to=args.to_date,
        officer_id=args.officer_id,
        pending_only=pending_only,
        output_path=args.output,
    )
    if result.get("success"):
        print(f"Shift swaps CSV: {result['path']} ({result['count']} rows)")
    else:
        print(f"Failed: {result.get('message')}")


def pay_period_status(_args):
    locked = is_pay_period_locked()
    start, end = get_current_cycle_window()
    state = "LOCKED" if locked else "open"
    print(f"Pay period {format_date(start)} – {format_date(end)}: {state}")


def pay_period_lock(_args):
    result = lock_pay_period()
    if result.get("success"):
        print(f"Locked pay period {format_date(result['period_start'])} – {format_date(result['period_end'])}")
    else:
        print(f"Error: {result.get('message')}")


def pay_period_unlock(_args):
    result = unlock_pay_period()
    if result.get("success"):
        print("Pay period unlocked")
    else:
        print(f"Error: {result.get('message')}")


def pay_period_history_cmd(args):
    data = get_pay_period_history(args.limit)
    if not data.get("periods"):
        print("No pay period history.")
        return
    for p in data["periods"]:
        lock = " locked" if p.get("locked") else ""
        print(
            f"{format_date(p['period_start'])} – {format_date(p['period_end'])}  "
            f"{p['total_hours']:.1f}h  ${p['total_pay']:,.2f}  "
            f"({p['officer_count']} officers){lock}"
        )


def list_open_shifts(args):
    shifts = get_open_shifts(officer_id=args.officer_id)
    if not shifts:
        print("No open shifts.")
        return
    for s in shifts:
        squad = f"Squad {s['squad']} " if s.get("squad") else ""
        print(f"{s['id']:<4} {format_date(s['shift_date']):<12} {squad}{s['shift_start']}-{s['shift_end']}")


def post_open_shift(args):
    result = create_open_shift(args.date, args.shift_start, args.shift_end, squad=args.squad)
    if result.get("success"):
        print(f"Open shift posted (ID: {result['shift_id']})")
    else:
        print(f"Error: {result.get('message')}")


def list_availability(args):
    entries = get_officer_availability(officer_id=args.officer_id)
    if not entries:
        print("No availability entries.")
        return
    for e in entries:
        reason = f"  {e.get('reason')}" if e.get("reason") else ""
        print(f"{e['id']:<4} {e['officer_name']:<22} {format_date(e['unavailable_date']):<12}{reason}")


def add_availability_cmd(args):
    result = add_officer_availability(args.officer_id, args.date, args.reason or "")
    if result.get("success"):
        print(f"Availability recorded (ID: {result['entry_id']})")
        if result.get("warning"):
            print(f"Warning: {result['warning']}")
    else:
        print(f"Error: {result.get('message')}")


def availability_conflicts_cmd(args):
    if args.start and args.end:
        start, end = parse_date(args.start), parse_date(args.end)
    else:
        start, end = get_current_cycle_window()
    data = get_schedule_conflicts(start, end, officer_id=args.officer_id)
    print(f"Conflicts {data['start_date']} – {data['end_date']}: {data['conflict_count']} issue(s)")
    for c in data.get("conflicts", []):
        print(f"  {c['unavailable_date']}  {c['officer_name']}  ({c['schedule_status']})  {c.get('reason') or ''}")


def list_users_cmd(args):
    users = list_all_users(include_inactive=not args.active_only)
    if not users:
        print("No users found.")
        return
    print(f"{'ID':<5} {'Username':<18} {'Role':<16} {'Officer':<22} {'Active':<7} {'MustChg':<8}")
    print("-" * 90)
    for u in users:
        active = "Yes" if u.get("active") == 1 else "No"
        must_chg = "Yes" if u.get("must_change_password") == 1 else "No"
        print(
            f"{u['id']:<5} {u['username']:<18} {u['role']:<16} "
            f"{(u.get('officer_name') or '—'):<22} {active:<7} {must_chg:<8}"
        )


def create_user_cmd(args):
    result = create_app_user(
        args.username,
        args.password,
        args.role,
        officer_id=args.officer_id,
        must_change_password=not args.no_force_change,
    )
    if result.get("success"):
        print(f"User '{args.username}' created (ID: {result['user_id']})")
    else:
        print(f"Error: {result.get('message', 'Unknown error')}")


def update_user_cmd(args):
    if args.clear_officer_link:
        result = update_app_user(args.user_id, clear_officer_link=True)
    else:
        fields = {}
        if args.role is not None:
            fields["role"] = args.role
        if args.officer_id is not None:
            fields["officer_id"] = args.officer_id
        if not fields:
            print("Error: No fields to update")
            return
        result = update_app_user(args.user_id, **fields)
    if result.get("success"):
        print(f"User {args.user_id} updated")
    else:
        print(f"Error: {result.get('message', 'Unknown error')}")


def reset_user_password_cmd(args):
    result = admin_reset_user_password(
        args.user_id,
        args.password,
        must_change_password=not args.no_force_change,
    )
    if result.get("success"):
        print(f"Password reset for user {args.user_id}")
    else:
        print(f"Error: {result.get('message', 'Unknown error')}")


def set_user_active_cmd(args, active: bool):
    result = set_app_user_active(args.user_id, active)
    if result.get("success"):
        print(result.get("message", "Done"))
    else:
        print(f"Error: {result.get('message', 'Unknown error')}")


def assign_override_cmd(args):
    result = create_manual_coverage_override(
        args.original_officer_id,
        args.replacement_officer_id,
        args.date,
        reason=args.reason or "Manual Coverage",
    )
    if result.get("success"):
        print(result.get("message", "Coverage assigned"))
    else:
        print(f"Error: {result.get('message', 'Unknown error')}")


def export_ical_cmd(args):
    if args.start and args.end:
        start = parse_date(args.start)
        end = parse_date(args.end)
    else:
        start, end = get_current_cycle_window()
    result = export_officer_schedule_ical(
        args.officer_id,
        start_date=start,
        end_date=end,
        output_path=args.output,
    )
    if result.get("success"):
        print(f"iCal: {result['path']}")
    else:
        print(f"Failed: {result.get('message')}")


def main():
    parser = argparse.ArgumentParser(description="Dodgeville PD Scheduler Admin CLI")
    subparsers = parser.add_subparsers(dest="command")

    # Officers
    officers = subparsers.add_parser("officers", help="Manage officers")
    officers_sub = officers.add_subparsers(dest="action")
    officers_sub.add_parser("list", help="List all officers")

    add = officers_sub.add_parser("add", help="Add new officer")
    add.add_argument("--name", required=True)
    add.add_argument("--seniority", type=int, required=True)
    add.add_argument("--squad", required=True, choices=["A", "B"])
    add.add_argument("--shift-start", required=True)
    add.add_argument("--shift-end", required=True)
    add.add_argument("--pay-rate", type=float, default=30.0)
    add.add_argument("--start-date", help="Employment start date DD-MM-YYYY")
    add.add_argument("--email")
    add.add_argument("--phone")
    add.add_argument("--address")
    add.add_argument("--job-title", help="Roster title (standard or supervisor-added custom)")

    update = officers_sub.add_parser("update", help="Update an officer")
    update.add_argument("officer_id", type=int)
    update.add_argument("--name")
    update.add_argument("--seniority", type=int, dest="seniority")
    update.add_argument("--squad", choices=["A", "B"])
    update.add_argument("--shift-start")
    update.add_argument("--shift-end")
    update.add_argument("--pay-rate", type=float)
    update.add_argument("--start-date")
    update.add_argument("--email")
    update.add_argument("--phone")
    update.add_argument("--address")
    update.add_argument("--job-title", dest="job_title", help="Roster title (standard or custom)")
    update.add_argument("--active", type=int, choices=[0, 1])

    delete = officers_sub.add_parser("delete", help="Delete an officer without scheduling history")
    delete.add_argument("officer_id", type=int)

    titles = officers_sub.add_parser("titles", help="Manage assignable roster titles")
    titles_sub = titles.add_subparsers(dest="titles_action")
    titles_sub.add_parser("list", help="List standard and custom titles")
    titles_add = titles_sub.add_parser("add", help="Add a custom title")
    titles_add.add_argument("title", help="New title name")

    imp = officers_sub.add_parser("import", help="Import roster from CSV (export format)")
    imp.add_argument("--file", required=True, help="Path to roster CSV file")
    imp.add_argument(
        "--skip-existing",
        action="store_true",
        help="Do not update officers matched by ID; only add new rows",
    )

    # Requests
    requests = subparsers.add_parser("requests", help="Manage day-off requests")
    requests_sub = requests.add_subparsers(dest="action")
    requests_sub.add_parser("pending", help="List pending requests")
    req_list = requests_sub.add_parser("list", help="List requests with optional filters")
    req_list.add_argument("--status", help="Filter by status (or 'all')")
    req_list.add_argument("--from", dest="from_date", help="Start date DD-MM-YYYY")
    req_list.add_argument("--to", dest="to_date", help="End date DD-MM-YYYY")

    requests_sub.add_parser("bulk-approve", help="Approve all auto-OK pending requests")
    bulk_reject = requests_sub.add_parser("bulk-reject", help="Reject all standard pending requests")
    bulk_reject.add_argument("--notes", default="Bulk rejected", help="Admin notes on rejections")

    approve = requests_sub.add_parser("approve", help="Approve a request")
    approve.add_argument("request_id", type=int)

    reject = requests_sub.add_parser("reject", help="Reject a request")
    reject.add_argument("request_id", type=int)

    req_submit = requests_sub.add_parser("submit", help="Submit a day-off request")
    req_submit.add_argument("--officer-id", type=int, required=True)
    req_submit.add_argument("--date", required=True, help="DD-MM-YYYY")
    req_submit.add_argument("--type", required=True, choices=list(DAY_OFF_REQUEST_TYPES))
    req_submit.add_argument("--notes", default="")

    # Swaps
    swaps = subparsers.add_parser("swaps", help="Manage shift swap requests")
    swaps_sub = swaps.add_subparsers(dest="action")
    swaps_sub.add_parser("pending", help="List pending swaps")
    swap_list = swaps_sub.add_parser("list", help="List swaps with optional filters")
    swap_list.add_argument("--status", help="Filter: pending, Approved, Rejected, or all")
    swap_list.add_argument("--from", dest="from_date", help="Start date DD-MM-YYYY")
    swap_list.add_argument("--to", dest="to_date", help="End date DD-MM-YYYY")

    swap_approve = swaps_sub.add_parser("approve", help="Approve a swap")
    swap_approve.add_argument("swap_id", type=int)

    swap_reject = swaps_sub.add_parser("reject", help="Reject a swap")
    swap_reject.add_argument("swap_id", type=int)

    swap_create = swaps_sub.add_parser("create", help="Create a shift swap request")
    swap_create.add_argument("--officer1-id", type=int, required=True)
    swap_create.add_argument("--officer2-id", type=int, required=True)
    swap_create.add_argument("--date", required=True, help="DD-MM-YYYY")

    # Notifications
    notifications = subparsers.add_parser("notifications", help="View notifications")
    notif_sub = notifications.add_subparsers(dest="action")
    notif_list = notif_sub.add_parser("list", help="List notifications")
    notif_list.add_argument("--unread", action="store_true")
    notif_list.add_argument("--officer-id", type=int)

    notif_read = notif_sub.add_parser("read", help="Mark one notification read")
    notif_read.add_argument("notification_id", type=int)

    notif_read_all = notif_sub.add_parser("read-all", help="Mark all notifications read")
    notif_read_all.add_argument("--officer-id", type=int)

    # Exports
    exports = subparsers.add_parser("export", help="Export PDF reports")
    export_sub = exports.add_subparsers(dest="action")

    exp_schedule = export_sub.add_parser("schedule", help="Export schedule PDF")
    exp_schedule.add_argument("--start", help="Start date DD-MM-YYYY")
    exp_schedule.add_argument("--end", help="End date DD-MM-YYYY")
    exp_schedule.add_argument("--officer-id", type=int, help="Limit to one officer")
    exp_schedule.add_argument("--output", help="Output file path")

    exp_payroll = export_sub.add_parser("payroll", help="Export payroll PDF")
    exp_payroll.add_argument("--officer-id", type=int)
    exp_payroll.add_argument("--period-start", help="Pay period start DD-MM-YYYY")
    exp_payroll.add_argument("--output", help="Output file path")

    exp_coverage = export_sub.add_parser("coverage", help="Export coverage report PDF")
    exp_coverage.add_argument("--start", help="Start date DD-MM-YYYY")
    exp_coverage.add_argument("--end", help="End date DD-MM-YYYY")
    exp_coverage.add_argument("--output", help="Output file path")

    exp_requests = export_sub.add_parser("requests", help="Export day-off requests PDF")
    exp_requests.add_argument("--status", help="Filter by status")
    exp_requests.add_argument("--from", dest="from_date", help="Start date DD-MM-YYYY")
    exp_requests.add_argument("--to", dest="to_date", help="End date DD-MM-YYYY")
    exp_requests.add_argument("--officer-id", type=int, help="Limit to one officer's requests")
    exp_requests.add_argument("--output", help="Output file path")

    exp_swaps = export_sub.add_parser("swaps", help="Export shift swap requests PDF")
    exp_swaps.add_argument("--status", help="Filter: pending, Approved, Rejected, or all")
    exp_swaps.add_argument("--from", dest="from_date", help="Start date DD-MM-YYYY")
    exp_swaps.add_argument("--to", dest="to_date", help="End date DD-MM-YYYY")
    exp_swaps.add_argument("--officer-id", type=int)
    exp_swaps.add_argument("--output", help="Output file path")

    exp_ical = export_sub.add_parser("ical", help="Export officer schedule as iCal (.ics)")
    exp_ical.add_argument("--officer-id", type=int, required=True)
    exp_ical.add_argument("--start", help="Start date DD-MM-YYYY")
    exp_ical.add_argument("--end", help="End date DD-MM-YYYY")
    exp_ical.add_argument("--output", help="Output file path")

    # Users
    users = subparsers.add_parser("users", help="Manage application login accounts")
    users_sub = users.add_subparsers(dest="action")
    users_list = users_sub.add_parser("list", help="List app users")
    users_list.add_argument(
        "--active-only",
        action="store_true",
        help="Hide deactivated accounts",
    )
    users_create = users_sub.add_parser("create", help="Create a login account")
    users_create.add_argument("--username", required=True)
    users_create.add_argument("--password", required=True)
    users_create.add_argument("--role", required=True, choices=list(USER_ROLES))
    users_create.add_argument("--officer-id", type=int, help="Link to officer record")
    users_create.add_argument(
        "--no-force-change",
        action="store_true",
        help="Do not require password change on first login",
    )
    users_update = users_sub.add_parser("update", help="Update role or officer link")
    users_update.add_argument("user_id", type=int)
    users_update.add_argument("--role", choices=list(USER_ROLES))
    users_update.add_argument("--officer-id", type=int)
    users_update.add_argument(
        "--clear-officer-link",
        action="store_true",
        help="Remove officer link",
    )
    users_reset = users_sub.add_parser("reset-password", help="Reset user password")
    users_reset.add_argument("user_id", type=int)
    users_reset.add_argument("--password", required=True)
    users_reset.add_argument("--no-force-change", action="store_true")
    users_deact = users_sub.add_parser("deactivate", help="Deactivate a user")
    users_deact.add_argument("user_id", type=int)
    users_act = users_sub.add_parser("activate", help="Reactivate a user")
    users_act.add_argument("user_id", type=int)

    # Manual overrides
    overrides = subparsers.add_parser("overrides", help="Schedule coverage overrides")
    ov_sub = overrides.add_subparsers(dest="action")
    ov_assign = ov_sub.add_parser("assign", help="Assign manual coverage for a shift")
    ov_assign.add_argument("--original-officer-id", type=int, required=True)
    ov_assign.add_argument("--replacement-officer-id", type=int, required=True)
    ov_assign.add_argument("--date", required=True, help="Override date DD-MM-YYYY")
    ov_assign.add_argument("--reason", default="Manual Coverage")

    # Holidays
    holidays = subparsers.add_parser("holidays", help="Manage department holidays")
    hol_sub = holidays.add_subparsers(dest="action")
    hol_list = hol_sub.add_parser("list", help="List holidays")
    hol_list.add_argument("--year", type=int)
    hol_add = hol_sub.add_parser("add", help="Add a holiday")
    hol_add.add_argument("--name", required=True)
    hol_add.add_argument("--date", required=True, help="DD-MM-YYYY")
    hol_add.add_argument("--unpaid", action="store_true")
    hol_del = hol_sub.add_parser("delete", help="Delete a holiday")
    hol_del.add_argument("holiday_id", type=int)

    settings = subparsers.add_parser("settings", help="Department settings")
    set_sub = settings.add_subparsers(dest="action")
    set_get = set_sub.add_parser("get", help="Get a setting value")
    set_get.add_argument("key")
    set_set = set_sub.add_parser("set", help="Set a setting value")
    set_set.add_argument("key")
    set_set.add_argument("value")
    set_rot = set_sub.add_parser("rotation", help="Show or update rotation schedule")
    rot_sub = set_rot.add_subparsers(dest="rotation_action")
    rot_sub.add_parser("show", help="Show active rotation configuration")
    rot_set = rot_sub.add_parser("set", help="Save rotation schedule (applies department-wide)")
    rot_set.add_argument("--cycle-length", type=int, required=True, help="7–28 days")
    rot_set.add_argument("--preset", required=True, help="Rotation preset name")
    rot_set.add_argument("--base-date", default="", help="Cycle anchor DD-MM-YYYY (optional)")
    rot_set.add_argument("--squad-a-days", default="", help="Optional Squad A on-duty days")
    set_staff = set_sub.add_parser("staffing", help="Show or update shift and staffing configuration")
    staff_sub = set_staff.add_subparsers(dest="staffing_action")
    staff_sub.add_parser("show", help="Show active staffing configuration")
    staff_set = staff_sub.add_parser("set", help="Save staffing configuration")
    staff_set.add_argument("--shift-length", type=float, required=True, help="Hours per shift")
    staff_set.add_argument("--annual-hours", type=float, required=True, help="Department annual hours target")
    staff_set.add_argument("--shift-count", type=int, required=True, help="Number of shift bands")
    staff_set.add_argument("--target-officers", type=int, required=True, help="Target roster size")
    staff_set.add_argument("--shift-starts", default="", help="Comma-separated HH:MM start times")

    # Reports
    reports = subparsers.add_parser("reports", help="Analytics and summaries")
    rep_sub = reports.add_subparsers(dest="action")
    rep_sum = rep_sub.add_parser("summary", help="Dashboard-style summary")
    rep_sum.add_argument("--officer-id", type=int, help="Officer-scoped summary")
    rep_cov = rep_sub.add_parser("coverage", help="Coverage report for date range")
    rep_cov.add_argument("--start", help="DD-MM-YYYY")
    rep_cov.add_argument("--end", help="DD-MM-YYYY")
    rep_ot = rep_sub.add_parser("overtime", help="Overtime alerts for current period")
    rep_ot.add_argument("--officer-id", type=int, help="Limit to one officer")
    rep_conf = rep_sub.add_parser("conflicts", help="Availability vs schedule conflicts")
    rep_conf.add_argument("--start", help="DD-MM-YYYY")
    rep_conf.add_argument("--end", help="DD-MM-YYYY")
    rep_conf.add_argument("--officer-id", type=int, help="Limit to one officer")
    rep_lc = rep_sub.add_parser("labor-compliance", help="FLSA §207(k), comp cap, consecutive-day alerts")
    rep_lc.add_argument("--officer-id", type=int, help="Limit to one officer")

    # Schedule diff
    sched_diff = subparsers.add_parser("schedule-diff", help="Compare base vs updated schedule")
    sched_diff.add_argument("--year", type=int, help="Year (default: current)")
    sched_diff.add_argument("--month", type=int, help="Month 1-12 (default: current)")
    sched_diff.add_argument("--output", help="Export diff to CSV instead of printing")
    sched_diff.add_argument("--officer-id", type=int, help="Limit to one officer's changes")
    sched_diff.add_argument("--limit", type=int, default=50, help="Max rows when printing")

    # CSV exports
    csv_export = subparsers.add_parser("csv", help="Export CSV data")
    csv_sub = csv_export.add_subparsers(dest="action")
    csv_roster = csv_sub.add_parser("roster", help="Export officer roster")
    csv_roster.add_argument("--output", help="Output file path")
    csv_pay = csv_sub.add_parser("payroll", help="Export payroll for pay period")
    csv_pay.add_argument("--period-start", help="Pay period start DD-MM-YYYY")
    csv_pay.add_argument("--officer-id", type=int, help="Limit to one officer")
    csv_pay.add_argument("--output", help="Output file path")
    csv_req = csv_sub.add_parser("requests", help="Export day-off requests")
    csv_req.add_argument("--status", help="Filter by status (or 'all')")
    csv_req.add_argument("--from", dest="from_date", help="Start date DD-MM-YYYY")
    csv_req.add_argument("--to", dest="to_date", help="End date DD-MM-YYYY")
    csv_req.add_argument("--output", help="Output file path")
    csv_req.add_argument("--officer-id", type=int, help="Limit to one officer's requests")
    csv_swaps = csv_sub.add_parser("swaps", help="Export shift swap requests")
    csv_swaps.add_argument("--status", help="Filter: pending, Approved, Rejected, or all")
    csv_swaps.add_argument("--from", dest="from_date", help="Start date DD-MM-YYYY")
    csv_swaps.add_argument("--to", dest="to_date", help="End date DD-MM-YYYY")
    csv_swaps.add_argument("--officer-id", type=int, help="Limit to swaps involving officer")
    csv_swaps.add_argument("--output", help="Output file path")
    csv_tc = csv_sub.add_parser("timecard", help="Export timecard entries for pay period")
    csv_tc.add_argument("--period-start", help="Pay period start DD-MM-YYYY")
    csv_tc.add_argument("--officer-id", type=int, help="Limit to one officer")
    csv_tc.add_argument("--output", help="Output file path")
    csv_hist = csv_sub.add_parser("pay-history", help="Export pay period history summary")
    csv_hist.add_argument("--limit", type=int, default=12)
    csv_hist.add_argument("--officer-id", type=int)
    csv_hist.add_argument("--output", help="Output file path")

    # Pay period
    pay_period = subparsers.add_parser("pay-period", help="Lock/unlock current pay period")
    pp_sub = pay_period.add_subparsers(dest="action")
    pp_sub.add_parser("status", help="Show lock status")
    pp_sub.add_parser("lock", help="Lock current pay period")
    pp_sub.add_parser("unlock", help="Unlock pay period")
    pp_hist = pp_sub.add_parser("history", help="List recent pay periods")
    pp_hist.add_argument("--limit", type=int, default=6)

    # Availability
    availability = subparsers.add_parser("availability", help="Officer blackout dates")
    avail_sub = availability.add_subparsers(dest="action")
    avail_list = avail_sub.add_parser("list", help="List availability entries")
    avail_list.add_argument("--officer-id", type=int)
    avail_add = avail_sub.add_parser("add", help="Add blackout date")
    avail_add.add_argument("--officer-id", type=int, required=True)
    avail_add.add_argument("--date", required=True, help="DD-MM-YYYY")
    avail_add.add_argument("--reason", default="")
    avail_conf = avail_sub.add_parser("conflicts", help="Show schedule conflicts")
    avail_conf.add_argument("--officer-id", type=int)
    avail_conf.add_argument("--start", help="DD-MM-YYYY")
    avail_conf.add_argument("--end", help="DD-MM-YYYY")
    avail_del = avail_sub.add_parser("delete", help="Delete an availability entry")
    avail_del.add_argument("entry_id", type=int)

    # Open shifts
    open_shifts = subparsers.add_parser("open-shifts", help="Manage open shifts")
    os_sub = open_shifts.add_subparsers(dest="action")
    os_list = os_sub.add_parser("list", help="List open shifts")
    os_list.add_argument("--officer-id", type=int, help="Filter to shifts claimable by officer")
    os_post = os_sub.add_parser("post", help="Post an open shift")
    os_post.add_argument("--date", required=True)
    os_post.add_argument("--shift-start", required=True)
    os_post.add_argument("--shift-end", required=True)
    os_post.add_argument("--squad", choices=["A", "B"])
    os_fill = os_sub.add_parser("fill", help="Assign an officer to an open shift")
    os_fill.add_argument("shift_id", type=int)
    os_fill.add_argument("--officer-id", type=int, required=True)

    # Audit
    audit = subparsers.add_parser("audit-log", help="View or export audit log")
    audit_sub = audit.add_subparsers(dest="action")
    audit_list = audit_sub.add_parser("list", help="List recent audit entries")
    audit_list.add_argument("--limit", type=int, default=25)
    audit_list.add_argument("--action", help="Filter by action substring")
    audit_export = audit_sub.add_parser("export", help="Export audit log CSV")
    audit_export.add_argument("--output", help="Output file path")
    audit_export.add_argument("--limit", type=int, default=500)
    audit_export.add_argument("--action", help="Filter by action substring")

    # Backup
    subparsers.add_parser("backup", help="Backup the database")

    args = parser.parse_args()

    if args.command == "officers":
        if args.action == "list":
            list_officers()
        elif args.action == "add":
            add_officer(args)
        elif args.action == "update":
            update_officer_cmd(args)
        elif args.action == "delete":
            delete_officer_cmd(args)
        elif args.action == "import":
            import_officers_cmd(args)
        elif args.action == "titles":
            if args.titles_action == "list":
                list_officer_titles_cmd(args)
            elif args.titles_action == "add":
                add_officer_title_cmd(args)
    elif args.command == "requests":
        if args.action == "pending":
            list_pending_requests()
        elif args.action == "list":
            list_requests(args)
        elif args.action == "bulk-approve":
            result = bulk_approve_auto_ok_requests()
            print(result.get("message", "Done"))
            for err in result.get("failed", []):
                print(f"  Failed: {err}")
        elif args.action == "bulk-reject":
            result = bulk_reject_pending_requests(admin_notes=args.notes)
            print(result.get("message", "Done"))
            for err in result.get("failed", []):
                print(f"  Failed: {err}")
        elif args.action == "approve":
            approve_request(args.request_id)
        elif args.action == "reject":
            reject_request(args.request_id)
        elif args.action == "submit":
            submit_request_cmd(args)
    elif args.command == "swaps":
        if args.action == "pending":
            list_pending_swaps()
        elif args.action == "list":
            list_swaps(args)
        elif args.action == "approve":
            approve_swap(args.swap_id)
        elif args.action == "reject":
            reject_swap(args.swap_id)
        elif args.action == "create":
            create_swap_cmd(args)
    elif args.command == "notifications":
        if args.action == "list":
            list_notifications(unread_only=args.unread, officer_id=args.officer_id)
        elif args.action == "read":
            read_notification(args.notification_id)
        elif args.action == "read-all":
            read_all_notifications(officer_id=args.officer_id)
    elif args.command == "export":
        if args.action == "schedule":
            export_schedule(args)
        elif args.action == "coverage":
            export_coverage(args)
        elif args.action == "payroll":
            export_payroll(args)
        elif args.action == "requests":
            export_requests(args)
        elif args.action == "swaps":
            export_swaps_pdf_cmd(args)
        elif args.action == "ical":
            export_ical_cmd(args)
    elif args.command == "users":
        if args.action == "list":
            list_users_cmd(args)
        elif args.action == "create":
            create_user_cmd(args)
        elif args.action == "update":
            update_user_cmd(args)
        elif args.action == "reset-password":
            reset_user_password_cmd(args)
        elif args.action == "deactivate":
            set_user_active_cmd(args, active=False)
        elif args.action == "activate":
            set_user_active_cmd(args, active=True)
    elif args.command == "overrides":
        if args.action == "assign":
            assign_override_cmd(args)
    elif args.command == "holidays":
        if args.action == "list":
            list_holidays(args)
        elif args.action == "add":
            add_holiday_cmd(args)
        elif args.action == "delete":
            delete_holiday_cmd(args)
    elif args.command == "settings":
        if args.action == "get":
            get_setting_cmd(args)
        elif args.action == "set":
            set_setting_cmd(args)
        elif args.action == "rotation":
            rotation_settings_cmd(args)
        elif args.action == "staffing":
            staffing_settings_cmd(args)
    elif args.command == "reports":
        if args.action == "summary":
            reports_summary(args)
        elif args.action == "coverage":
            reports_coverage(args)
        elif args.action == "overtime":
            data = get_overtime_alerts(officer_id=args.officer_id)
            for a in data.get("alerts", []):
                print(f"{a['officer_name']:<22} {a['hours']:.1f}h  ({a['severity']})")
        elif args.action == "conflicts":
            if args.start and args.end:
                start, end = parse_date(args.start), parse_date(args.end)
            else:
                start, end = get_current_cycle_window()
            data = get_schedule_conflicts(start, end, officer_id=args.officer_id)
            print(f"Conflicts {data['start_date']} – {data['end_date']}: {data['conflict_count']} issue(s)")
            for c in data.get("conflicts", []):
                print(
                    f"  {c['unavailable_date']}  {c['officer_name']}  ({c['schedule_status']})  {c.get('reason') or ''}"
                )
        elif args.action == "labor-compliance":
            reports_labor_compliance(args)
    elif args.command == "schedule-diff":
        schedule_diff_cmd(args)
    elif args.command == "csv":
        if args.action == "roster":
            export_roster(args)
        elif args.action == "payroll":
            export_payroll_csv_cmd(args)
        elif args.action == "requests":
            export_requests_csv_cmd(args)
        elif args.action == "swaps":
            export_shift_swaps_csv_cmd(args)
        elif args.action == "timecard":
            export_timecard_csv_cmd(args)
        elif args.action == "pay-history":
            export_pay_period_history_csv_cmd(args)
    elif args.command == "pay-period":
        if args.action == "status":
            pay_period_status(args)
        elif args.action == "lock":
            pay_period_lock(args)
        elif args.action == "unlock":
            pay_period_unlock(args)
        elif args.action == "history":
            pay_period_history_cmd(args)
    elif args.command == "availability":
        if args.action == "list":
            list_availability(args)
        elif args.action == "add":
            add_availability_cmd(args)
        elif args.action == "conflicts":
            availability_conflicts_cmd(args)
        elif args.action == "delete":
            delete_availability_cmd(args)
    elif args.command == "open-shifts":
        if args.action == "list":
            list_open_shifts(args)
        elif args.action == "post":
            post_open_shift(args)
        elif args.action == "fill":
            fill_open_shift_cmd(args)
    elif args.command == "audit-log":
        if args.action == "list":
            for row in get_audit_log(args.limit, action_filter=args.action):
                print(
                    f"{row['created_at'][:19]}  {row['action']:<24}  {row.get('username') or '—'}  {row.get('details') or ''}"
                )
        elif args.action == "export":
            result = export_audit_csv(args.output, args.limit, action_filter=args.action)
            if result.get("success"):
                print(f"Audit CSV: {result['path']} ({result['count']} rows)")
            else:
                print(f"Failed: {result.get('message')}")
    elif args.command == "backup":
        backup()
    else:
        parser.print_help()


if __name__ == "__main__":
    from scripts.startup_gates import auto_before_cli

    gate_code = auto_before_cli()
    if gate_code != 0:
        from scripts.fix_hint import run_fix_hint

        run_fix_hint(run_audit=True)
        raise SystemExit(gate_code)
    main()
