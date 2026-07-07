"""Role-based permissions — extend PERMISSIONS as requirements are finalized."""

from typing import Dict, Tuple

USER_ROLES: Tuple[str, ...] = ("Officer", "Supervisor", "Administration")

PERMISSIONS: Dict[str, Tuple[str, ...]] = {
    "login": USER_ROLES,
    "timecard.view_own": USER_ROLES,
    "timecard.edit_own": USER_ROLES,
    "timecard.view_all": ("Supervisor", "Administration"),
    "timecard.edit_all": ("Supervisor", "Administration"),
    "timecard.submit": USER_ROLES,
    "timecard.approve": ("Supervisor", "Administration"),
    "payroll.view_own": USER_ROLES,
    "payroll.view_all": ("Supervisor", "Administration"),
    "payroll.edit": ("Supervisor", "Administration"),
    "payroll.import_timecard": ("Supervisor", "Administration"),
    "payroll.lock_period": ("Supervisor", "Administration"),
    "open_shifts.manage": ("Supervisor", "Administration"),
    "open_shifts.claim": USER_ROLES,
    "schedule.base.view": USER_ROLES,
    "schedule.base.publish": ("Supervisor", "Administration"),
    "schedule.updated.view": USER_ROLES,
    "schedule.updated.sync": ("Supervisor", "Administration"),
    "schedule.updated.edit": ("Supervisor", "Administration"),
    "schedule.export_own": USER_ROLES,
    "officers.manage": ("Supervisor", "Administration"),
    "requests.submit": USER_ROLES,
    "requests.submit_any": ("Supervisor", "Administration"),
    "requests.approve": ("Supervisor", "Administration"),
    "swaps.submit": USER_ROLES,
    "swaps.approve": ("Supervisor", "Administration"),
    "notifications.manage": ("Supervisor", "Administration"),
    "users.manage": ("Administration",),
    "users.edit_role": ("Supervisor", "Administration"),
    "admin.settings": ("Administration",),
    "database.backup": ("Supervisor", "Administration"),
    "simulator.use": ("Supervisor", "Administration"),
    "payroll.bulk_adjust": ("Supervisor", "Administration"),
    "reports.view": ("Supervisor", "Administration"),
    "reports.export": ("Supervisor", "Administration"),
    "availability.view": USER_ROLES,
    "availability.manage_own": USER_ROLES,
    "availability.manage_all": ("Supervisor", "Administration"),
    "holidays.manage": ("Administration",),
    "settings.manage": ("Administration",),
    "audit.view": ("Supervisor", "Administration"),
}


def role_has_permission(role: str, permission: str) -> bool:
    allowed = PERMISSIONS.get(permission, USER_ROLES)
    return role in allowed


def role_has_any_permission(role: str, permissions: Tuple[str, ...]) -> bool:
    return any(role_has_permission(role, perm) for perm in permissions)
