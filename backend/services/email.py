"""Outbound transactional email (team invites, share notifications).

Plain SMTP so any provider works — Gmail with an app password, Resend,
Postmark, SES. Configured entirely by env vars; when they're absent every
send is a logged no-op, so self-hosted and dev instances need nothing.

    SMTP_HOST, SMTP_PORT (587), SMTP_USER, SMTP_PASS
    EMAIL_FROM   e.g. "Reliafy <no-reply@reliafy.com>"

Delivery runs on a daemon thread: notification email must never add latency
to (or fail) the API call that triggered it.
"""

from __future__ import annotations

import logging
import smtplib
import threading
from email.message import EmailMessage

from backend import config

logger = logging.getLogger(__name__)


def enabled() -> bool:
    return bool(config.SMTP_HOST and config.EMAIL_FROM)


def _deliver(msg: EmailMessage) -> None:
    try:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=20) as smtp:
            smtp.starttls()
            if config.SMTP_USER:
                smtp.login(config.SMTP_USER, config.SMTP_PASS or "")
            smtp.send_message(msg)
        logger.info("email sent to=%s subject=%r", msg["To"], msg["Subject"])
    except Exception:
        logger.exception("email delivery failed to=%s subject=%r", msg["To"], msg["Subject"])


def send(to: str, subject: str, body: str) -> None:
    """Queue one plain-text email (no-op with a log line when unconfigured)."""
    if not to:
        return
    if not enabled():
        logger.info("email skipped (SMTP not configured) to=%s subject=%r", to, subject)
        return
    msg = EmailMessage()
    msg["From"] = config.EMAIL_FROM
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    threading.Thread(target=_deliver, args=(msg,), daemon=True).start()


def _app_url(path: str = "/") -> str:
    base = (config.PUBLIC_BASE_URL or "https://reliafy.com").rstrip("/")
    return f"{base}{path}"


# ---- Notifications -------------------------------------------------------------

def team_member_added(to: str, inviter_name: str, team_name: str) -> None:
    send(
        to,
        f"You've been added to {team_name} on Reliafy",
        f"{inviter_name} added you to the team \"{team_name}\" on Reliafy.\n\n"
        f"Everything in the team workspace is shared with you — open the workspace "
        f"switcher (top right) after signing in:\n\n{_app_url('/login')}\n\n"
        f"— Reliafy",
    )


def team_invite_pending(to: str, inviter_name: str, team_name: str) -> None:
    send(
        to,
        f"{inviter_name} invited you to {team_name} on Reliafy",
        f"{inviter_name} invited you to join the team \"{team_name}\" on Reliafy, "
        f"a reliability-engineering workbench.\n\n"
        f"Create a free account with this email address and you'll join the team "
        f"automatically:\n\n{_app_url('/login')}\n\n"
        f"— Reliafy",
    )


def new_signup(new_email: str | None, new_name: str | None) -> None:
    """Tell the operators a new account signed up.

    Push first (Pushover reaches a phone in seconds), falling back to email so
    an instance configured only with ADMIN_EMAILS keeps working. Fired from the
    server-side first-sight hook so it can't be missed.
    """
    from backend.services import push as push_service

    who = new_email or "unknown"
    if push_service.send(
        "New Reliafy signup",
        f"{new_name or '—'}\n{who}",
        url=_app_url("/admin"),
        url_title="Operator dashboard",
    ):
        return

    admins = sorted(config.ADMIN_EMAILS)
    if not admins:
        logger.info("new-signup notify skipped (no push, no ADMIN_EMAILS) email=%s",
                    new_email)
        return
    subject = f"New Reliafy signup: {who}"
    body = (
        "A new user just signed up for Reliafy.\n\n"
        f"Name:  {new_name or '—'}\n"
        f"Email: {new_email or '—'}\n\n"
        f"Operator dashboard: {_app_url('/admin')}\n\n"
        "— Reliafy"
    )
    for to in admins:
        send(to, subject, body)


def artifact_shared(to: str, sharer: str, artifact_name: str, link_path: str) -> None:
    send(
        to,
        f"{sharer} shared \"{artifact_name}\" with you on Reliafy",
        f"{sharer} shared \"{artifact_name}\" with you on Reliafy (view-only).\n\n"
        f"Open it here after signing in:\n\n{_app_url(link_path)}\n\n"
        f"— Reliafy",
    )
