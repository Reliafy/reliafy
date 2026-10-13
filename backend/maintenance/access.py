"""Who may use Reliafy Maintenance while it's in development.

On when ``MAINTENANCE_ENABLED``; then everyone on a single-user install (sign-in
off), and on a deployment only operators (``ADMIN_EMAILS``) and the addresses in
``MAINTENANCE_EMAILS``.
"""

from __future__ import annotations

from backend import config


def allowed(user: dict | None) -> bool:
    if not config.MAINTENANCE_ENABLED or not user:
        return False
    if config.AUTH_DISABLED:
        return True
    from backend.services import billing as billing_service

    email = (user.get("email") or "").strip().lower()
    trusted = billing_service.email_trusted(user)
    return trusted and (email in config.MAINTENANCE_EMAILS or billing_service.is_admin_user(user))
