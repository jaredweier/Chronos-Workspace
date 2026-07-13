---
name: security
description: Auth/permissions — login, roles, password rules, users.manage.
---

# Security Subagent

## Scope

- `permissions.py` â€” `PERMISSIONS`, `role_has_permission`
- `auth_password.py` â€” hashing, validation, `must_change_password`
- `logic/users.py` â€” `authenticate_user`, `create_app_user`, user CRUD
- `ui/login.py`, `ui/admin_pages.py` â€” login and Access Control tab
- `ui/session_pages.py` â€” post-login flow, sign-out audit
- `tests/test_permissions.py` â€” permissions matrix

## Invariants (never break)

1. Validators are the gate for business rules â€” do not weaken them for convenience
2. UI gates use `self.can("permission.key")` â€” keys must exist in `PERMISSIONS`
3. `NAV_PERMISSIONS` in `ui/theme.py` must reference defined permission keys
4. Only Administration may `users.manage` and `settings.manage`
5. Demo accounts: document policy in code comments; prefer env flags over hard deletes

## Workflow

1. Map the capability to a permission key (add to `PERMISSIONS` if new)
2. Gate UI with `can()`; gate logic only when role affects data scope
3. Add CLI if admins need scripting (`cli.py users *`)
4. Extend `tests/test_permissions.py` for role Ã— permission matrix
5. Run `python dev.py preflight` then `python dev.py check`

## Key symbols

| Area | Symbols |
|------|---------|
| Auth | `authenticate_user`, `create_app_user`, `validate_password` |
| Permissions | `role_has_permission`, `PERMISSIONS`, `NAV_PERMISSIONS` |
| Login | `LoginFrame`, `_run_post_login_flow`, `must_change_password` |
| Audit | `log_audit_action("user.login")`, `user.logout` |

## Open priorities

- Force password change on first demo login (or disable for eval builds via env)
- Optional LDAP â€” stub interface only until department requests it
- `SKIP_DEMO_USERS` / production credential policy in `config.py`

## Do not

- Bypass validators in UI or CLI
- Grant Officer role `users.manage` or `database.backup` without sign-off
- Store plaintext passwords
