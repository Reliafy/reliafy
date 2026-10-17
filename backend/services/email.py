"""Outbound email (team invites, share notifications, product updates).

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
import unicodedata
from email.message import EmailMessage
from email.utils import formataddr, parseaddr

from backend import config

logger = logging.getLogger(__name__)


def mask_address(address: str | None) -> str:
    """A recipient for the logs: ``derryn@gmail.com`` -> ``d***@gmail.com``
    (each address in a comma-separated list)."""
    out = []
    for part in str(address or "").split(","):
        part = part.strip()
        if "@" not in part:
            out.append("***" if part else "")
            continue
        local, domain = part.rsplit("@", 1)
        out.append(f"{local[:1]}***@{domain}")
    return ", ".join(p for p in out if p)


def clean_text(value, limit: int = 80) -> str:
    """User-supplied text (a team or display name) made safe for a subject
    line or body: control characters become spaces, whitespace collapses,
    and anything past ``limit`` characters is cut with an ellipsis."""
    text = "".join(" " if unicodedata.category(ch)[0] == "C" else ch for ch in str(value or ""))
    text = " ".join(text.split())
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text


def enabled() -> bool:
    return bool(config.SMTP_HOST and config.EMAIL_FROM)


def _deliver(msg: EmailMessage, *, raise_errors: bool = False) -> None:
    """Hand one message to the SMTP server.

    Failures are logged and swallowed (a notification must never break the
    request that triggered it) unless ``raise_errors`` — the bulk sender
    wants the exception so it can record the failure and retry later.
    """
    try:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=20) as smtp:
            smtp.starttls()
            if config.SMTP_USER:
                smtp.login(config.SMTP_USER, config.SMTP_PASS or "")
            smtp.send_message(msg)
        logger.info("email sent to=%s subject=%r", mask_address(msg["To"]), msg["Subject"])
    except Exception:
        logger.exception("email delivery failed to=%s subject=%r", mask_address(msg["To"]), msg["Subject"])
        if raise_errors:
            raise


def build_message(
    to: str,
    subject: str,
    body: str,
    html: str | None = None,
    reply_to: str | None = None,
    headers: dict[str, str] | None = None,
    from_name: str | None = None,
) -> EmailMessage:
    """Compose a message: plain text, or multipart/alternative with ``html``.

    ``from_name`` replaces the display name of ``EMAIL_FROM`` (the address,
    and so the sending domain, stays the same)."""
    msg = EmailMessage()
    msg["From"] = _from_header(from_name)
    msg["To"] = to
    # A subject is one header line: user-supplied names inside it never break it.
    msg["Subject"] = clean_text(subject, 200)
    if reply_to:
        msg["Reply-To"] = reply_to
    for name, value in (headers or {}).items():
        if name in msg:
            del msg[name]
        msg[name] = value
    msg.set_content(body)
    if html:
        msg.add_alternative(html, subtype="html")
    return msg


def _from_header(from_name: str | None) -> str | None:
    if not from_name:
        return config.EMAIL_FROM
    _, address = parseaddr(config.EMAIL_FROM or "")
    if not address:
        return config.EMAIL_FROM
    return formataddr((clean_text(from_name, 60), address))


def send(
    to: str,
    subject: str,
    body: str,
    html: str | None = None,
    reply_to: str | None = None,
    headers: dict[str, str] | None = None,
) -> None:
    """Queue one email (no-op with a log line when unconfigured).

    Plain text by default; pass ``html`` for a multipart/alternative message
    and ``headers`` for extra headers (e.g. List-Unsubscribe).
    """
    if not to:
        return
    if not enabled():
        logger.info("email skipped (SMTP not configured) to=%s subject=%r", mask_address(to), subject)
        return
    msg = build_message(to, subject, body, html=html, reply_to=reply_to, headers=headers)
    threading.Thread(target=_deliver, args=(msg,), daemon=True).start()


def send_now(
    to: str,
    subject: str,
    body: str,
    html: str | None = None,
    reply_to: str | None = None,
    headers: dict[str, str] | None = None,
    from_name: str | None = None,
) -> EmailMessage:
    """Deliver one email synchronously, raising on failure (bulk sender).

    Unlike :func:`send` this does not check :func:`enabled` — the caller
    decides what an unconfigured server means.
    """
    msg = build_message(to, subject, body, html=html, reply_to=reply_to, headers=headers,
                        from_name=from_name)
    _deliver(msg, raise_errors=True)
    return msg


def _app_url(path: str = "/") -> str:
    base = (config.PUBLIC_BASE_URL or "https://reliafy.com").rstrip("/")
    return f"{base}{path}"


# ---- Notifications -------------------------------------------------------------

def team_invite_pending(to: str, inviter_name: str, team_name: str) -> None:
    inviter_name, team_name = clean_text(inviter_name), clean_text(team_name)
    send(
        to,
        f"{inviter_name} invited you to {team_name} on Reliafy",
        f"{inviter_name} invited you to join the team \"{team_name}\" on Reliafy, "
        f"a reliability-engineering workbench.\n\n"
        f"Sign in with this email address (or create a free account with it) and "
        f"accept or decline the invitation in Settings:\n\n{_app_url('/settings')}\n\n"
        f"If you weren't expecting this, you can ignore it: you won't join the team "
        f"unless you accept.\n\n"
        f"— Reliafy",
    )


def new_signup(new_email: str | None, new_name: str | None) -> None:
    """Tell the operators a new account signed up.

    Push first (Pushover reaches a phone in seconds), falling back to email so
    an instance configured only with ADMIN_EMAILS keeps working. Fired from the
    server-side first-sight hook so it can't be missed.
    """
    from backend import extensions
    from backend.services import push as push_service

    who = new_email or "unknown"
    page = extensions.operator_page_path()
    link, link_title = (_app_url(page), "Operator dashboard") if page else (_app_url("/modelling"), "Open Reliafy")
    if push_service.send(
        "New Reliafy signup",
        f"{new_name or '—'}\n{who}",
        url=link,
        url_title=link_title,
    ):
        return

    admins = sorted(config.ADMIN_EMAILS)
    if not admins:
        logger.info("new-signup notify skipped (no push, no ADMIN_EMAILS) email=%s",
                    mask_address(new_email))
        return
    subject = f"New Reliafy signup: {who}"
    body = (
        "A new user just signed up for Reliafy.\n\n"
        f"Name:  {new_name or '—'}\n"
        f"Email: {new_email or '—'}\n\n"
        f"{link_title}: {link}\n\n"
        "— Reliafy"
    )
    for to in admins:
        send(to, subject, body)


def artifact_shared(to: str, sharer: str, artifact_name: str, link_path: str,
                    sharer_email: str | None = None) -> None:
    """Tell someone an artifact was shared with them. The names come from the
    sharer, so they're cleaned and capped; the sharer's account address is
    shown beside their name so the recipient can tell who sent it."""
    sharer, artifact_name = clean_text(sharer, 60), clean_text(artifact_name, 80)
    sharer_email = clean_text(sharer_email, 254)
    who = f"{sharer} ({sharer_email})" if sharer_email and sharer_email.lower() != sharer.lower() else sharer
    send(
        to,
        f"{sharer} shared \"{artifact_name}\" with you on Reliafy",
        f"{who} shared \"{artifact_name}\" with you on Reliafy (view-only).\n\n"
        f"Open it here after signing in:\n\n{_app_url(link_path)}\n\n"
        f"— Reliafy",
    )
