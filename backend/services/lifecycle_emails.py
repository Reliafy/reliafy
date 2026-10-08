"""Lifecycle emails (#272): a welcome on signup and a tip email on day 3.

* **welcome** — on a new account's first sign-in with a verified email
  (``backend.auth.upsert_user``; Google sign-ins are verified at once,
  email/password accounts once the user follows Firebase's link). Accounts
  older than ``WELCOME_MAX_AGE`` never get one, so switching the feature on
  doesn't greet everyone who signs in that week.
* **day3** — sent by a daily run (``POST /internal/lifecycle/day3``, Cloud
  Scheduler) to verified accounts 3 to 7 days old. Two versions, "start" and
  "further", picked by whether the account has saved anything of its own.
  Neither says anything about what the user did.

Rules, both kinds: off unless ``LIFECYCLE_EMAILS`` is set (and SMTP is
configured); at most once per user and kind — the ``lifecycle_emails`` send
log (``_id`` = ``<kind>:<uid>``) is claimed before sending, a failed send is
retried at most ``MAX_ATTEMPTS`` times in all; the product-update opt-out and
its one-click unsubscribe cover these emails too; test domains are skipped;
links to the site carry ``utm_medium=lifecycle&utm_campaign=<kind>``.
"""

from __future__ import annotations

import html as html_lib
import logging
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from backend import config

logger = logging.getLogger(__name__)

KINDS = ("welcome", "day3")
WELCOME_MAX_AGE = timedelta(days=3)
DAY3_MIN_AGE = timedelta(days=3)
DAY3_MAX_AGE = timedelta(days=7)  # a missed daily run is caught up within this
DAY3_BATCH = 200
DAY3_DELAY_S = 0.5
MAX_ATTEMPTS = 3
MAX_CONSECUTIVE_FAILURES = 5
FROM_NAME = "Derryn at Reliafy"
UTM_MEDIUM = "lifecycle"

# Collections whose documents mean "saved something of their own" (samples
# belong to SAMPLE_OWNER, so they never count).
_SAVED = ("models", "rbds", "datasets", "degradation_models", "rcm_studies",
          "strategy_analyses", "fleets")

_EMAIL_RE = re.compile(r"^[^@\s]+@([^@\s]+\.[^@\s]+)$")


def enabled() -> bool:
    from backend.services import email as email_service

    return bool(config.LIFECYCLE_EMAILS) and email_service.enabled()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value) -> datetime | None:
    """Mongo hands datetimes back naive (UTC)."""
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def skip_reason(user: dict | None) -> str | None:
    """Why this account gets no lifecycle email, or None."""
    from backend.scripts.send_update import _test_domain
    from backend.services import email_prefs

    if not user:
        return "no user"
    m = _EMAIL_RE.match((user.get("email") or "").strip())
    if not m:
        return "no valid email"
    if _test_domain(m.group(1).lower()):
        return "test domain"
    if not user.get("email_verified"):
        return "email not verified"
    if not email_prefs.is_subscribed(user):
        return "opted out"
    return None


# ---- The send log ---------------------------------------------------------

def _log_id(kind: str, uid: str) -> str:
    return f"{kind}:{uid}"


def ensure_indexes(db) -> None:
    db.lifecycle_emails.create_index([("kind", 1), ("uid", 1)], unique=True)
    db.lifecycle_emails.create_index([("kind", 1), ("status", 1), ("sent_at", -1)])


def handled(db, kind: str, uid: str) -> bool:
    """Sent, being sent, or out of retries: nothing more to do."""
    row = db.lifecycle_emails.find_one({"_id": _log_id(kind, uid)}, {"status": 1, "attempts": 1})
    if not row:
        return False
    return row.get("status") != "failed" or int(row.get("attempts") or 0) >= MAX_ATTEMPTS


def claim(db, kind: str, uid: str, email: str) -> bool:
    """Take the right to send ``kind`` to ``uid``. True for exactly one
    caller: the first ever, or one retrying a failed send with attempts
    left. A send that never reported back stays claimed (at most once)."""
    from pymongo.errors import DuplicateKeyError

    now = _now()
    try:
        db.lifecycle_emails.insert_one({
            "_id": _log_id(kind, uid), "kind": kind, "uid": uid, "email": email,
            "status": "sending", "attempts": 1, "claimed_at": now,
        })
        return True
    except DuplicateKeyError:
        pass
    r = db.lifecycle_emails.update_one(
        {"_id": _log_id(kind, uid), "status": "failed", "attempts": {"$lt": MAX_ATTEMPTS}},
        {"$set": {"status": "sending", "claimed_at": now, "email": email},
         "$inc": {"attempts": 1}},
    )
    return r.modified_count == 1


def _finish(db, kind: str, uid: str, status: str, *, variant: str | None = None,
            error: str | None = None) -> None:
    fields = {"status": status, "error": error}
    if status == "sent":
        fields["sent_at"] = _now()
    if variant:
        fields["variant"] = variant
    db.lifecycle_emails.update_one({"_id": _log_id(kind, uid)}, {"$set": fields})


# ---- The emails -----------------------------------------------------------

WELCOME_SUBJECT = "Welcome to Reliafy"
WELCOME_PREHEADER = "Three ways to start, and how to reach me."
WELCOME_BODY = """\
Thanks for signing up. I'm Derryn, and I built Reliafy.

Three ways to start:

1. [Open a sample model](/modelling/m/sample-model-bearings-weibull): a Weibull fit to 30 bearing failure times, with its plots and B-lives.
2. [Paste failure times](/modelling/new?mode=paste) from a spreadsheet and fit a distribution. Put a 1 next to any unit that's still running.
3. [Open a sample block diagram](/rbds/b/sample-rbd-pump-station), a controller and two pumps, and change it to match your system.

If you use Claude or another AI agent, you can [connect it to Reliafy over MCP](/api-docs#mcp) and work from there.

Reply to this email if you get stuck or something doesn't work. It comes to me.

Derryn"""

DAY3_SUBJECT = "Three things to try in a block diagram"
DAY3_PREHEADER = "Fault trees, what to improve, and your diagram as Python."
_DAY3_TIPS = """\
1. **Fault tree.** The Fault tree tab draws a diagram as a fault tree and ranks the minimal cut sets by how much each one contributes.
2. **What to improve.** On a repairable diagram, the Calculator tab ranks every change you could make, like a longer life, a faster repair or one more crew, by how much it lifts availability.
3. **Download as Python.** Any saved diagram downloads as a standalone Python script, so you can rerun it or check the working yourself."""

DAY3_BODIES = {
    # Nothing saved yet: a sample to try the tips on, and the guide.
    "start": f"""\
Most people start Reliafy with a block diagram, so here are three things in the RBD builder that are easy to miss.

{_DAY3_TIPS}

The [instrument air sample](/rbds/b/sample-rbd-instrument-air-availability) is a good one to try them on, and the [RBD guide](/guides/build-an-rbd) walks through building your own.

Reply if you get stuck. It comes to me.

Derryn""",
    # Something saved: the same tips, then two for building your own.
    "further": f"""\
Here are three things in the RBD builder that are easy to miss.

{_DAY3_TIPS}

Two more for when you're building your own: a block can use a life model fitted to your own failure data, and the Design tab finds the cheapest redundancy that meets a reliability target. The [RBD guide](/guides/build-an-rbd) covers both.

Reply if you get stuck. It comes to me.

Derryn""",
}


@dataclass
class Rendered:
    subject: str
    text: str
    html: str
    headers: dict


def render(kind: str, *, name: str | None, token: str, variant: str | None = None) -> Rendered:
    """Subject, plain text and HTML for one recipient, links tagged."""
    from backend.scripts.send_update import REPLY_TO, first_name, markdown_to_html, markdown_to_text
    from backend.services import email_links
    from backend.services import email_templates as tpl
    from backend.services.email import _app_url, clean_text

    if kind == "welcome":
        subject, preheader, body = WELCOME_SUBJECT, WELCOME_PREHEADER, WELCOME_BODY
    elif kind == "day3":
        subject, preheader = DAY3_SUBJECT, DAY3_PREHEADER
        body = DAY3_BODIES[variant or "start"]
    else:
        raise ValueError(f"unknown lifecycle email {kind!r}")

    unsub_page = _app_url(f"/unsubscribe?t={token}")
    unsub_api = _app_url(f"/api/email/unsubscribe?t={token}")
    first = first_name(clean_text(name, 60))
    greeting = f"Hi {first}," if first else "Hi,"
    why = "You're getting this because you signed up for Reliafy."

    text = (
        f"{greeting}\n\n{markdown_to_text(body)}\n\n"
        f"--\n{why} Unsubscribe: {unsub_page}\n"
    )
    footer_html = (
        f"{why}<br>"
        f'<a href="{unsub_page}" style="color:{tpl.FAINT};text-decoration:underline;">Unsubscribe</a>'
        f" &nbsp;·&nbsp; Reliafy, Brisbane, Australia"
    )
    html = tpl.layout(
        body_html=tpl.style_body(f"<p>{html_lib.escape(greeting)}</p>\n{markdown_to_html(body)}"),
        base_url=_app_url("/"),
        preheader=preheader,
        footer_html=footer_html,
    )
    headers = {
        "List-Unsubscribe": f"<{unsub_api}>, <mailto:{REPLY_TO}?subject=unsubscribe>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }
    text = email_links.tag_text(text, medium=UTM_MEDIUM, campaign=kind)
    html = email_links.tag_html(html, medium=UTM_MEDIUM, campaign=kind)
    return Rendered(subject=subject, text=text, html=html, headers=headers)


def has_saved(db, uid: str) -> bool:
    """Whether the account has saved anything of its own (picks the day-3
    version; never quoted back to the user)."""
    return any(db[c].find_one({"owner_id": uid}, {"_id": 1}) for c in _SAVED)


# ---- Sending --------------------------------------------------------------

def send_one(db, kind: str, uid: str) -> str:
    """Send ``kind`` to ``uid`` unless skipped or already handled. Returns
    ``sent``, ``failed``, ``skipped`` or ``already``."""
    from backend.scripts.send_update import REPLY_TO
    from backend.services import email as email_service
    from backend.services import email_prefs

    user = db.users.find_one({"_id": uid})
    if skip_reason(user):
        return "skipped"
    email = user["email"].strip()
    if not claim(db, kind, uid, email):
        return "already"
    variant = None
    try:
        if kind == "day3":
            variant = "further" if has_saved(db, uid) else "start"
        token = email_prefs.token_for(db, uid)
        r = render(kind, name=user.get("name"), token=token, variant=variant)
        email_service.send_now(email, r.subject, r.text, html=r.html, reply_to=REPLY_TO,
                               headers=r.headers, from_name=FROM_NAME)
    except Exception as exc:  # noqa: BLE001 - logged, retried within MAX_ATTEMPTS
        logger.warning("lifecycle email %s to uid=%s failed: %s", kind, uid, exc)
        _finish(db, kind, uid, "failed", variant=variant, error=str(exc)[:500])
        return "failed"
    _finish(db, kind, uid, "sent", variant=variant)
    return "sent"


def _spawn(fn, *args) -> None:
    """Run off the request thread (a login must never wait on SMTP)."""
    threading.Thread(target=fn, args=args, daemon=True).start()


def _send_welcome(db, uid: str) -> None:
    try:
        send_one(db, "welcome", uid)
    except Exception:  # noqa: BLE001 - never surfaces anywhere
        logger.exception("welcome email failed uid=%s", uid)


def maybe_send_welcome(db, uid: str) -> bool:
    """Called on every sign-in. Starts the welcome email when this is a new,
    verified, subscribed account that hasn't had one. True when started."""
    if not enabled():
        return False
    user = db.users.find_one({"_id": uid})
    if skip_reason(user):
        return False
    created = _aware(user.get("created_at"))
    if created is None or _now() - created > WELCOME_MAX_AGE:
        return False
    if handled(db, "welcome", uid):
        return False
    _spawn(_send_welcome, db, uid)
    return True


def run_day3(db, *, now: datetime | None = None, limit: int = DAY3_BATCH,
             sleep=time.sleep) -> dict:
    """The daily run: the day-3 email to every eligible account 3 to 7 days
    old that hasn't had it. Returns a tally."""
    if not enabled():
        return {"enabled": False, "sent": 0, "failed": 0, "skipped": 0, "already": 0}
    ensure_indexes(db)
    now = now or _now()
    candidates = db.users.find(
        {"created_at": {"$gte": now - DAY3_MAX_AGE, "$lte": now - DAY3_MIN_AGE},
         "email_verified": True},
        {"_id": 1},
    ).sort("created_at", 1)
    tally = {"enabled": True, "sent": 0, "failed": 0, "skipped": 0, "already": 0}
    consecutive = attempted = 0
    for u in candidates:
        if handled(db, "day3", u["_id"]):
            tally["already"] += 1
            continue
        if attempted >= limit:
            break
        if attempted:
            sleep(DAY3_DELAY_S)
        status = send_one(db, "day3", u["_id"])
        tally[status] += 1
        if status in ("sent", "failed"):
            attempted += 1
        consecutive = consecutive + 1 if status == "failed" else 0
        if consecutive >= MAX_CONSECUTIVE_FAILURES:
            logger.error("day-3 run stopped: %d failures in a row", consecutive)
            break
    logger.info("day-3 run: %s", tally)
    return tally
