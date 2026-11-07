"""Operator support replies: answer mail sent to the support inbox as Reliafy.

An operator (or an agent holding an operator's API token) sends the reply
through the app's SMTP settings, from ``SUPPORT_FROM``, with ``In-Reply-To``
and ``References`` set so it threads in the recipient's mailbox, and a blind
copy to ``SUPPORT_COPY_TO`` so the sent reply shows in the support inbox.

Every attempt is logged to ``support_replies`` (who, to whom, the subject and
a short preview, never the whole body) and counts towards the hourly cap,
``SUPPORT_REPLIES_PER_HOUR``, which is shared by every caller: it is an abuse
ceiling on mail sent as Reliafy, not a per-user allowance.
"""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import formataddr, formatdate, getaddresses, make_msgid

from backend import config
from backend.services import email as email_service

logger = logging.getLogger(__name__)

COLLECTION = "support_replies"
LIST_LIMIT = 50
PREVIEW_CHARS = 120
MAX_TEXT = 50_000
MAX_HTML = 200_000
MAX_REFERENCES = 20

_ADDRESS = re.compile(r"^[^@\s<>,;\"]+@[^@\s<>,;\"]+\.[^@\s<>,;\"]+$")
_MESSAGE_ID = re.compile(r"^<[^<>\s]+@[^<>\s]+>$")


class SupportError(ValueError):
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


def _now() -> datetime:
    return datetime.now(timezone.utc)


def configured() -> bool:
    return bool(config.SMTP_HOST and config.SUPPORT_FROM)


def _address(value, field: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise SupportError(f"{field} is required: one email address.")
    if any(ch in raw for ch in "\r\n"):
        raise SupportError(f"{field} must be one email address on one line.")
    found = [a for _, a in getaddresses([raw]) if a]
    addr = found[0] if len(found) == 1 else ""
    if not _ADDRESS.match(addr):
        raise SupportError(f"{field} must be one email address, like name@example.com.")
    return addr


def _message_id(value, field: str) -> str:
    raw = str(value or "").strip()
    if raw and not raw.startswith("<"):
        raw = f"<{raw}>"
    if not _MESSAGE_ID.match(raw):
        raise SupportError(f"{field} must be a Message-ID like <abc123@mail.example.com>.")
    return raw


def _references(in_reply_to: str | None, references) -> list[str]:
    if references is None:
        references = []
    if isinstance(references, str):
        references = references.split()
    if not isinstance(references, (list, tuple)):
        raise SupportError("references must be a list of Message-IDs.")
    refs = []
    for ref in references:
        mid = _message_id(ref, "Each reference")
        if mid not in refs:
            refs.append(mid)
    # The message being answered is always the last reference (RFC 5322 3.6.4).
    if in_reply_to:
        if in_reply_to in refs:
            refs.remove(in_reply_to)
        refs.append(in_reply_to)
    if len(refs) > MAX_REFERENCES:  # keep the first (the thread's root) and the latest
        refs = refs[:1] + refs[-(MAX_REFERENCES - 1):]
    return refs


def build_reply(body: dict, reply_id: str) -> EmailMessage:
    """The reply as a message, validated; raises :class:`SupportError`."""
    if not isinstance(body, dict):
        raise SupportError("Send a JSON object: {to, subject, text, in_reply_to?, references?, html?}.")
    to = _address(body.get("to"), "to")
    subject = email_service.clean_text(body.get("subject"), 200)
    if not subject:
        raise SupportError("subject is required.")
    text = body.get("text")
    if not isinstance(text, str) or not text.strip():
        raise SupportError("text is required: the reply as plain text.")
    if len(text) > MAX_TEXT:
        raise SupportError(f"text is too long (at most {MAX_TEXT:,} characters).")
    html = body.get("html")
    if html is not None and (not isinstance(html, str) or len(html) > MAX_HTML):
        raise SupportError(f"html must be text of at most {MAX_HTML:,} characters.")
    in_reply_to = body.get("in_reply_to")
    in_reply_to = _message_id(in_reply_to, "in_reply_to") if in_reply_to else None
    refs = _references(in_reply_to, body.get("references"))

    from_addr = _address(config.SUPPORT_FROM, "SUPPORT_FROM")
    msg = EmailMessage()
    msg["From"] = formataddr((email_service.clean_text(config.SUPPORT_FROM_NAME, 60), from_addr))
    msg["To"] = to
    msg["Subject"] = subject
    msg["Reply-To"] = from_addr
    msg["Date"] = formatdate(localtime=False)
    msg["Message-ID"] = make_msgid(domain=from_addr.rsplit("@", 1)[1])
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if refs:
        msg["References"] = " ".join(refs)
    copy_to = (config.SUPPORT_COPY_TO or "").strip()
    if copy_to:
        msg["Bcc"] = _address(copy_to, "SUPPORT_COPY_TO")
    # Lets an inbox reader recognise its own copies and find the log entry.
    msg["X-Reliafy-Support-Reply"] = reply_id
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    return msg


def sent_last_hour(db) -> int:
    return db[COLLECTION].count_documents({"sent_at": {"$gte": _now() - timedelta(hours=1)}})


def send_reply(db, user: dict, body: dict) -> dict:
    """Validate, check the cap, send synchronously and log. Returns the log
    entry (as :func:`public`). Raises :class:`SupportError` with the status
    to answer."""
    if not configured():
        raise SupportError("Email isn't configured on this server (no SMTP settings), "
                           "so support replies can't be sent.", 503)
    reply_id = uuid.uuid4().hex
    msg = build_reply(body, reply_id)
    limit = max(0, int(config.SUPPORT_REPLIES_PER_HOUR))
    if sent_last_hour(db) >= limit:
        raise SupportError(f"The support reply limit is {limit} an hour, and it has been reached. "
                           "Try again later.", 429)
    record = {
        "_id": reply_id,
        "to": msg["To"],
        "subject": msg["Subject"],
        "in_reply_to": msg["In-Reply-To"],
        "message_id": msg["Message-ID"],
        "preview": email_service.clean_text(body.get("text"), PREVIEW_CHARS),
        "sent_at": _now(),
        "uid": user.get("uid"),
        "email": user.get("email"),
        "token_id": user.get("via_token"),
        "status": "sending",
    }
    # Logged before sending so a burst can't overrun the cap; failures count too.
    db[COLLECTION].insert_one(record)
    try:
        email_service._deliver(msg, raise_errors=True)
    except Exception as exc:  # noqa: BLE001 - reported, logged
        db[COLLECTION].update_one({"_id": reply_id}, {"$set": {"status": "failed"}})
        raise SupportError("The mail server refused or didn't answer, so the reply wasn't sent. "
                           "Try again in a few minutes.", 502) from exc
    db[COLLECTION].update_one({"_id": reply_id}, {"$set": {"status": "sent"}})
    record["status"] = "sent"
    logger.info("support reply sent id=%s to=%s", reply_id, email_service.mask_address(record["to"]))
    return public(record)


def list_replies(db, limit: int = LIST_LIMIT) -> list[dict]:
    return [public(r) for r in db[COLLECTION].find({}).sort("sent_at", -1).limit(limit)]


def public(record: dict) -> dict:
    sent_at = record.get("sent_at")
    return {
        "id": record["_id"],
        "to": record.get("to"),
        "subject": record.get("subject"),
        "in_reply_to": record.get("in_reply_to"),
        "message_id": record.get("message_id"),
        "preview": record.get("preview"),
        "sent_at": sent_at.isoformat() if hasattr(sent_at, "isoformat") else sent_at,
        "status": record.get("status"),
        "sent_by": {"uid": record.get("uid"), "email": record.get("email"),
                    "token_id": record.get("token_id")},
    }
