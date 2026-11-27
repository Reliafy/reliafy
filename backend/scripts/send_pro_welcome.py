"""Send the welcome-to-Pro email to one account by hand.

For a complimentary Pro grant (``plan: "pro"``, ``plan_until: None`` on the
user doc), which no Stripe event announces. Paid subscribers get the "paid"
version from the Stripe webhook on their own. Both versions share the
``lifecycle_emails`` send log (``pro_welcome:<uid>``), so an account gets
one Pro welcome, ever, whichever way it went.

    # Dry run (default): who it would go to, and the rendered text. Sends nothing.
    python -m backend.scripts.send_pro_welcome --uid <uid>

    # The real thing (complimentary is the default version here).
    python -m backend.scripts.send_pro_welcome --uid <uid> --send

    # Record it as sent without sending (an email that went out by hand).
    python -m backend.scripts.send_pro_welcome --uid <uid> --mark-sent --note "sent by hand 27 Nov"

``--email`` finds the account by address instead of ``--uid``. ``--send``
refuses an account that isn't on Pro, one that's skipped (deleted, no valid
or verified address, test domain) and one that has already had a Pro welcome.
It uses the MONGODB_URI / SMTP_* environment of wherever it runs.
"""

from __future__ import annotations

import argparse
import pathlib
import sys


def _find_user(db, uid: str | None, email: str | None) -> dict | None:
    if uid:
        return db.users.find_one({"_id": {"$eq": uid}})
    import re

    return db.users.find_one({"email": {"$regex": f"^{re.escape(email.strip())}$", "$options": "i"}})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m backend.scripts.send_pro_welcome",
        description="Send the welcome-to-Pro email to one account (dry run by default).",
    )
    who = parser.add_mutually_exclusive_group(required=True)
    who.add_argument("--uid", help="the account's user id")
    who.add_argument("--email", help="the account's email address (case-insensitive)")
    parser.add_argument("--variant", choices=("complimentary", "paid"), default="complimentary",
                        help="which version (default complimentary)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--send", action="store_true", help="send it")
    mode.add_argument("--mark-sent", action="store_true",
                      help="record it as already sent, without sending anything")
    parser.add_argument("--note", default="", help="a note stored on the send-log row (--mark-sent)")
    args = parser.parse_args(argv)

    from backend import db as db_module
    from backend.services import billing
    from backend.services import email as email_service
    from backend.services import lifecycle_emails as le

    db = db_module.get_db()
    user = _find_user(db, args.uid, args.email)
    if user is None:
        print("No such account.", file=sys.stderr)
        return 1
    uid = user["_id"]
    kind = le.PRO_WELCOME
    print(f"Account: {uid} <{user.get('email') or '?'}>, plan {user.get('plan') or 'free'}")

    if args.mark_sent:
        if le.mark_sent(db, kind, uid, variant=args.variant, note=args.note):
            print(f"Recorded {kind} ({args.variant}) as sent. Nothing was sent.")
            return 0
        print("Already in the send log; nothing changed.")
        return 0

    already = le.handled(db, kind, uid)
    skip = le.account_skip_reason(user)
    pro = billing.is_pro(user)
    print(f"Already had a Pro welcome: {'yes' if already else 'no'}")
    print(f"Skipped: {skip or 'no'}")
    if not pro:
        print("Not on Pro (plan isn't 'pro' or it has lapsed).")

    r = le.render(kind, name=user.get("name"), variant=args.variant, features=le.pro_features(db))
    print(f"\nSubject: {r.subject}\nPreheader: {le.PRO_WELCOME_PREHEADER}\n")
    print(r.text)

    if not args.send:
        print("Dry run: nothing sent. Add --send to send it.")
        return 0
    if already or skip or not pro:
        print("Refusing to send (see above).", file=sys.stderr)
        return 1
    if not email_service.enabled():
        print("SMTP isn't configured (SMTP_HOST / EMAIL_FROM); refusing to send.", file=sys.stderr)
        return 2
    status = le.send_one(db, kind, uid, args.variant)
    print(f"Result: {status}")
    return 0 if status == "sent" else 1


if __name__ == "__main__":
    # As send_update: pick up the repo's .env before backend.config is imported.
    try:
        from dotenv import load_dotenv

        load_dotenv(pathlib.Path(__file__).resolve().parents[2] / ".env")
    except ImportError:  # pragma: no cover
        pass
    sys.exit(main())
