"""App users, authentication, and audit logging."""

from typing import Dict, List, Optional

from auth_password import hash_password, verify_password
from database import connection
from logic.officers import get_officer_by_id


def list_login_users() -> List[Dict]:
    with connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT u.*, o.name AS officer_name
            FROM app_users u
            LEFT JOIN officers o ON u.officer_id = o.id
            WHERE u.active = 1
            ORDER BY u.role, u.username
        """)
        rows = cursor.fetchall()
    users = [dict(row) for row in rows]
    for user in users:
        user.pop("password", None)
    return users


def authenticate_user(username: str, password: str) -> Dict:
    from logic.ldap_auth import ldap_auth_enabled, try_ldap_authenticate

    if ldap_auth_enabled():
        ldap_result = try_ldap_authenticate(username, password)
        if ldap_result.get("success"):
            with connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT u.*, o.name AS officer_name
                    FROM app_users u
                    LEFT JOIN officers o ON u.officer_id = o.id
                    WHERE u.username = ? AND u.active = 1
                    """,
                    (ldap_result.get("ldap_username") or username.strip(),),
                )
                row = cursor.fetchone()
            if row:
                user = dict(row)
                user.pop("password", None)
                log_audit_action("user.login", "app_user", user["id"], user["id"], user["username"])
                return {"success": True, "user": user, "auth_source": "ldap"}
            return {
                "success": False,
                "message": "LDAP authentication succeeded but no linked app account exists",
            }
        if not ldap_result.get("skipped"):
            return {"success": False, "message": ldap_result.get("message", "LDAP authentication failed")}

    with connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT u.*, o.name AS officer_name
            FROM app_users u
            LEFT JOIN officers o ON u.officer_id = o.id
            WHERE u.username = ? AND u.active = 1
        """,
            (username.strip(),),
        )
        row = cursor.fetchone()
    if not row:
        return {"success": False, "message": "Invalid username or password"}
    user = dict(row)

    stored = user["password"]
    if not verify_password(password, stored):
        return {"success": False, "message": "Invalid username or password"}
    if not stored.startswith("pbkdf2$"):
        _upgrade_password_hash(user["id"], password)
    user.pop("password", None)
    log_audit_action("user.login", "app_user", user["id"], user["id"], user["username"])
    return {"success": True, "user": user}


def create_app_user(
    username: str,
    password: str,
    role: str,
    officer_id: Optional[int] = None,
    must_change_password: bool = True,
    actor_user_id: Optional[int] = None,
) -> Dict:
    from validators import validate_app_user_role, validate_password, validate_username

    for check in (validate_username(username), validate_password(password), validate_app_user_role(role)):
        if not check.ok:
            return {"success": False, "message": check.message}

    with connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT id FROM app_users WHERE username = ?", (username.strip(),))
            if cursor.fetchone():
                return {"success": False, "message": "Username already exists"}
            if officer_id is not None:
                officer = get_officer_by_id(officer_id)
                if not officer:
                    return {"success": False, "message": "Linked officer not found"}
                cursor.execute(
                    "SELECT id FROM app_users WHERE officer_id = ? AND active = 1",
                    (officer_id,),
                )
                if cursor.fetchone():
                    return {"success": False, "message": "Officer already has an active login"}

            from auth_password import hash_password

            cursor.execute(
                """
                INSERT INTO app_users
                (officer_id, username, password, role, must_change_password)
                VALUES (?, ?, ?, ?, ?)
            """,
                (
                    officer_id,
                    username.strip(),
                    hash_password(password),
                    role,
                    1 if must_change_password else 0,
                ),
            )
            user_id = cursor.lastrowid
            conn.commit()
            log_audit_action(
                "user.create",
                "app_user",
                user_id,
                actor_user_id,
                f"{username.strip()} ({role})",
            )
            return {"success": True, "user_id": user_id, "message": "User created"}
        except Exception as e:
            conn.rollback()
            return {"success": False, "message": str(e)}


def _upgrade_password_hash(user_id: int, plaintext: str) -> None:
    with connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE app_users SET password = ? WHERE id = ?",
            (hash_password(plaintext), user_id),
        )
        conn.commit()


def admin_reset_user_password(
    user_id: int,
    new_password: str,
    must_change_password: bool = True,
    actor_user_id: Optional[int] = None,
) -> Dict:
    from validators import validate_password

    check = validate_password(new_password)
    if not check.ok:
        return {"success": False, "message": check.message}
    if not get_user_by_id(user_id):
        return {"success": False, "message": "User not found"}

    with connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                "UPDATE app_users SET password = ?, must_change_password = ? WHERE id = ?",
                (hash_password(new_password), 1 if must_change_password else 0, user_id),
            )
            conn.commit()
            log_audit_action("user.password_reset", "app_user", user_id, actor_user_id)
            return {"success": True, "message": "Password reset"}
        except Exception as e:
            conn.rollback()
            return {"success": False, "message": str(e)}


def allowed_roles_for_actor(actor_user_id: Optional[int]) -> List[str]:
    from permissions import USER_ROLES, role_has_permission

    actor = get_user_by_id(actor_user_id) if actor_user_id else None
    if not actor:
        return []
    if role_has_permission(actor["role"], "users.manage"):
        return list(USER_ROLES)
    if role_has_permission(actor["role"], "users.edit_role"):
        return ["Officer", "Supervisor"]
    return []


def change_own_password(user_id: int, current_password: str, new_password: str) -> Dict:
    from validators import validate_password

    validation = validate_password(new_password)
    if not validation.ok:
        return {"success": False, "message": validation.message}

    user = get_user_by_id(user_id)
    if not user:
        return {"success": False, "message": "User not found"}

    if not verify_password(current_password, user["password"]):
        return {"success": False, "message": "Current password is incorrect"}

    with connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                "UPDATE app_users SET password = ?, must_change_password = 0 WHERE id = ?",
                (hash_password(new_password), user_id),
            )
            conn.commit()
            log_audit_action("user.password_change", "app_user", user_id, user_id)
            return {"success": True, "message": "Password updated"}
        except Exception as e:
            conn.rollback()
            return {"success": False, "message": str(e)}


def clear_must_change_password(user_id: int, actor_user_id: Optional[int] = None) -> Dict:
    """Clear forced password-change flag without changing the password."""
    user = get_user_by_id(user_id)
    if not user:
        return {"success": False, "message": "User not found"}

    with connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                "UPDATE app_users SET must_change_password = 0 WHERE id = ?",
                (user_id,),
            )
            conn.commit()
            log_audit_action(
                "user.clear_must_change_password",
                "app_user",
                user_id,
                actor_user_id,
            )
            return {"success": True, "message": "Password change requirement cleared"}
        except Exception as e:
            conn.rollback()
            return {"success": False, "message": str(e)}


def complete_initial_setup(
    department_name: str,
    actor_user_id: Optional[int] = None,
) -> Dict:
    from logic.operations import set_department_setting

    name = (department_name or "").strip()
    if not name:
        return {"success": False, "message": "Department name is required"}
    set_department_setting("department_name", name)
    set_department_setting("setup_complete", "1")
    log_audit_action("setup.complete", "department_settings", None, actor_user_id, name)
    return {"success": True, "message": "Setup complete"}


def get_user_by_id(user_id: int) -> Optional[Dict]:
    with connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT u.*, o.name AS officer_name
            FROM app_users u
            LEFT JOIN officers o ON u.officer_id = o.id
            WHERE u.id = ?
        """,
            (user_id,),
        )
        row = cursor.fetchone()
    return dict(row) if row else None


def is_setup_complete() -> bool:
    from logic.operations import get_department_setting

    return get_department_setting("setup_complete") == "1"


def list_all_users(include_inactive: bool = True) -> List[Dict]:
    query = """
        SELECT u.id, u.officer_id, u.username, u.role, u.active,
               u.must_change_password, u.created_at, o.name AS officer_name
        FROM app_users u
        LEFT JOIN officers o ON u.officer_id = o.id
    """
    if not include_inactive:
        query += " WHERE u.active = 1"
    query += " ORDER BY u.active DESC, u.role, u.username"
    with connection() as conn:
        cursor = conn.cursor()
        cursor.execute(query)
        rows = [dict(row) for row in cursor.fetchall()]
    return rows


def log_audit_action(
    action: str,
    entity_type: str = "",
    entity_id: Optional[int] = None,
    user_id: Optional[int] = None,
    details: str = "",
) -> None:
    with connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO audit_log (action, entity_type, entity_id, user_id, details)
            VALUES (?, ?, ?, ?, ?)
        """,
            (action, entity_type or None, entity_id, user_id, details or None),
        )
        conn.commit()


def set_app_user_active(user_id: int, active: bool, actor_user_id: Optional[int] = None) -> Dict:
    user = get_user_by_id(user_id)
    if not user:
        return {"success": False, "message": "User not found"}
    with connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("UPDATE app_users SET active = ? WHERE id = ?", (1 if active else 0, user_id))
            conn.commit()
            action = "user.activate" if active else "user.deactivate"
            log_audit_action(action, "app_user", user_id, actor_user_id)
            return {"success": True, "message": "User deactivated" if not active else "User activated"}
        except Exception as e:
            conn.rollback()
            return {"success": False, "message": str(e)}


def update_app_user(
    user_id: int,
    role: Optional[str] = None,
    officer_id: Optional[int] = None,
    clear_officer_link: bool = False,
    actor_user_id: Optional[int] = None,
) -> Dict:
    from permissions import role_has_permission
    from validators import validate_app_user_role, validate_user_role_change

    user = get_user_by_id(user_id)
    if not user:
        return {"success": False, "message": "User not found"}
    actor = get_user_by_id(actor_user_id) if actor_user_id else None

    changing_role = role is not None and role != user["role"]
    changing_link = clear_officer_link or (officer_id is not None and officer_id != user.get("officer_id"))

    if changing_link and actor_user_id is not None:
        if not actor or not role_has_permission(actor["role"], "users.manage"):
            return {
                "success": False,
                "message": "Administration access required to change officer links",
            }

    if role is not None:
        check = validate_app_user_role(role)
        if not check.ok:
            return {"success": False, "message": check.message}
        if changing_role and actor_user_id is not None:
            auth = validate_user_role_change(actor, user, role)
            if not auth.ok:
                return {"success": False, "message": auth.message}

    with connection() as conn:
        cursor = conn.cursor()
        try:
            new_officer_id = user["officer_id"]
            if clear_officer_link:
                new_officer_id = None
            elif officer_id is not None:
                officer = get_officer_by_id(officer_id)
                if not officer:
                    return {"success": False, "message": "Linked officer not found"}
                cursor.execute(
                    "SELECT id FROM app_users WHERE officer_id = ? AND active = 1 AND id != ?",
                    (officer_id, user_id),
                )
                if cursor.fetchone():
                    return {"success": False, "message": "Officer already has an active login"}
                new_officer_id = officer_id

            new_role = role if role is not None else user["role"]
            cursor.execute(
                "UPDATE app_users SET role = ?, officer_id = ? WHERE id = ?",
                (new_role, new_officer_id, user_id),
            )
            conn.commit()
            log_audit_action("user.update", "app_user", user_id, actor_user_id)
            return {"success": True, "message": "User updated"}
        except Exception as e:
            conn.rollback()
            return {"success": False, "message": str(e)}
