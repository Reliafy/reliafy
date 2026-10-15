"""Who may use Reliafy Maintenance while it's in development.

On when ``MAINTENANCE_ENABLED``; then everyone on a single-user install (sign-in
off), and on a deployment only operators (``ADMIN_EMAILS``) and the addresses in
``MAINTENANCE_EMAILS``. Graph queries in Cypher (#423) are narrower still:
:func:`graph_query_allowed`.
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


def graph_query_allowed(user: dict | None) -> bool:
    """Who may run their own Cypher on the maintenance graph (#423): only the
    addresses in ``GRAPH_QUERY_EMAILS`` (empty: no one), and only with
    Maintenance. Never from operator status alone. Every way in (the app's API,
    MCP, the guide) asks this."""
    if not config.GRAPH_QUERY_EMAILS or not user or not allowed(user):
        return False
    email = (user.get("email") or "").strip().lower()
    if not email or email not in config.GRAPH_QUERY_EMAILS:
        return False
    from backend.services import billing as billing_service

    return billing_service.email_trusted(user)
