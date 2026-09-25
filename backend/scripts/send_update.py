"""Email a "What's new" update to every subscribed user.

Updates are the Markdown files under ``frontend/src/content/updates/``
(``YYYY-MM-DD-<slug>.md``, frontmatter ``title``/``date``/``summary``/
optional ``email_subject``), the same files the public /whats-new pages
render. This script turns one into an email and sends it.

    # Dry run (default): who would get it, and a rendered sample on disk.
    python -m backend.scripts.send_update --update october-2026

    # One copy to yourself; its unsubscribe link is inert.
    python -m backend.scripts.send_update --update october-2026 --test-to you@example.org

    # The real thing. Asks you to type the slug unless --yes.
    python -m backend.scripts.send_update --update october-2026 --send
    python -m backend.scripts.send_update --update october-2026 --send --yes --limit 50

Every send is recorded in ``update_sends`` (one row per update and user), so
a re-run only reaches people not yet sent — failed sends are retried. Users
who opted out, test-domain accounts, and ``--exclude`` addresses are skipped.
It uses the MONGODB_URI / SMTP_* environment of wherever it runs.
"""

from __future__ import annotations

import argparse
import html as html_lib
import pathlib
import re
import sys
import tempfile
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone

UPDATES_DIR = (
    pathlib.Path(__file__).resolve().parents[2]
    / "frontend" / "src" / "content" / "updates"
)
REPLY_TO = "hello@reliafy.com"
TEST_DOMAINS = ("example.com", "reliafy.test", "local")
TEST_TOKEN = "test"  # not a valid token: the unsubscribe endpoint 404s on it
MAX_CONSECUTIVE_FAILURES = 5


# ---- The update file ------------------------------------------------------

@dataclass
class Update:
    slug: str
    title: str
    date: str
    summary: str
    subject: str
    body: str  # markdown
    path: pathlib.Path


def slug_from_path(path: pathlib.Path) -> str:
    """Same rule as frontend/src/blog.js ``slugFromPath``."""
    return re.sub(r"^\d{4}-\d{2}(-\d{2})?-", "", path.name.removesuffix(".md"))


def parse_frontmatter(raw: str) -> tuple[dict, str]:
    """The frontend's minimal ``--- key: value ---`` parser, in Python."""
    m = re.match(r"^---\s*\r?\n([\s\S]*?)\r?\n---\s*\r?\n?([\s\S]*)$", raw)
    if not m:
        return {}, raw
    meta = {}
    for line in m.group(1).splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = re.sub(r"""^["']|["']$""", "", value.strip())
        if key:
            meta[key] = value
    return meta, m.group(2)


def load_update(path: pathlib.Path) -> Update:
    meta, body = parse_frontmatter(path.read_text(encoding="utf-8"))
    title = meta.get("title", "").strip()
    if not title:
        raise SystemExit(f"{path}: frontmatter has no title")
    return Update(
        slug=slug_from_path(path),
        title=title,
        date=meta.get("date", "").strip(),
        summary=meta.get("summary", "").strip(),
        subject=(meta.get("email_subject") or "").strip() or title,
        body=body.strip(),
        path=path,
    )


def find_update(slug: str, updates_dir: pathlib.Path = UPDATES_DIR) -> pathlib.Path:
    matches = [p for p in sorted(updates_dir.glob(f"*-{slug}.md"))
               if slug_from_path(p) == slug]
    if not matches:
        raise SystemExit(f"No update with slug {slug!r} in {updates_dir}")
    if len(matches) > 1:
        raise SystemExit(f"Slug {slug!r} is ambiguous: {', '.join(p.name for p in matches)}")
    return matches[0]


# ---- Rendering ------------------------------------------------------------

def _absolute(url: str) -> str:
    from backend.services.email import _app_url

    return _app_url(url) if url.startswith("/") and not url.startswith("//") else url


def markdown_to_html(md: str) -> str:
    import markdown

    out = markdown.markdown(md, extensions=["extra", "sane_lists"])
    # Site-relative links and images mean nothing in a mail client.
    return re.sub(r'(href|src)="(/[^/"][^"]*)"',
                  lambda m: f'{m.group(1)}="{_absolute(m.group(2))}"', out)


def markdown_to_text(md: str) -> str:
    """The Markdown source, lightly cleaned for a plain-text part."""
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", md)                    # images
    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)[^)]*\)",
                  lambda m: f"{m.group(1)} ({_absolute(m.group(2))})", text)  # links
    text = re.sub(r"^```.*$\n?", "", text, flags=re.M)                # fences
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.M)                # headings
    text = re.sub(r"(\*\*|__)(.+?)\1", r"\2", text)                   # bold
    text = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"\1", text)  # italics
    text = re.sub(r"`([^`]+)`", r"\1", text)                          # inline code
    text = re.sub(r"<[^>\n]+>", "", text)                             # stray tags
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def first_name(name: str | None) -> str | None:
    """A usable first name, or None. Auth falls back to the email address
    for the display name, which is no greeting."""
    name = (name or "").strip()
    if not name or "@" in name:
        return None
    return name.split()[0]


@dataclass
class Rendered:
    subject: str
    text: str
    html: str
    headers: dict


def render(update: Update, name: str | None, token: str) -> Rendered:
    from backend.services.email import _app_url

    web = _app_url(f"/whats-new/{update.slug}")
    unsub_page = _app_url(f"/unsubscribe?t={token}")
    unsub_api = _app_url(f"/api/email/unsubscribe?t={token}")
    first = first_name(name)
    greeting = f"Hi {first}," if first else "Hi,"
    footer = (f"You're receiving this because you have a Reliafy account. "
              f"Unsubscribe: {unsub_page} · Reliafy, Brisbane, Australia · {REPLY_TO}")

    text = (
        f"{greeting}\n\n"
        f"Here's what's new in Reliafy.\n\n"
        f"{update.title}\n{'=' * min(len(update.title), 60)}\n\n"
        f"{markdown_to_text(update.body)}\n\n"
        f"Read it on the web: {web}\n\n"
        f"--\n{footer}\n"
    )

    esc = html_lib.escape
    html = f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>{esc(update.title)}</title></head>
<body style="margin:0;padding:0;background:#f6f6f4;">
<div style="max-width:600px;margin:0 auto;padding:24px 20px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;font-size:15px;line-height:1.55;color:#1f2328;background:#ffffff;">
<p>{esc(greeting)}</p>
<p>Here's what's new in Reliafy.</p>
<h1 style="font-size:22px;line-height:1.3;margin:24px 0 8px;">{esc(update.title)}</h1>
{markdown_to_html(update.body)}
<p style="margin-top:28px;">Read it on the web: <a href="{esc(web)}" style="color:#0b6bcb;">{esc(web)}</a></p>
<hr style="border:none;border-top:1px solid #e3e3e0;margin:28px 0 16px;">
<p style="font-size:12px;line-height:1.5;color:#6b6f76;">You're receiving this because you have a Reliafy account.
<a href="{esc(unsub_page)}" style="color:#6b6f76;">Unsubscribe</a> · Reliafy, Brisbane, Australia ·
<a href="mailto:{REPLY_TO}" style="color:#6b6f76;">{REPLY_TO}</a></p>
</div>
</body></html>
"""
    headers = {
        "List-Unsubscribe": f"<{unsub_api}>, <mailto:{REPLY_TO}?subject=unsubscribe>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }
    return Rendered(subject=update.subject, text=text, html=html, headers=headers)


# ---- Recipients -----------------------------------------------------------

_EMAIL_RE = re.compile(r"^[^@\s]+@([^@\s]+\.[^@\s]+)$")


def _test_domain(domain: str) -> bool:
    return any(domain == d or domain.endswith("." + d) for d in TEST_DOMAINS)


def recipients(db, slug: str, exclude: set[str]) -> tuple[list[dict], Counter]:
    """Users to send to, and why everyone else is skipped."""
    from backend.services import email_prefs

    sent = {r["uid"] for r in db.update_sends.find(
        {"update_slug": slug, "status": "sent"}, {"uid": 1})}
    eligible, skipped, seen = [], Counter(), set()
    for u in db.users.find({}, {"email": 1, "name": 1, "email_updates_opt_out": 1,
                                "email_unsub_token": 1}).sort("_id", 1):
        email = (u.get("email") or "").strip()
        m = _EMAIL_RE.match(email)
        lc = email.lower()
        if not m:
            skipped["no valid email"] += 1
        elif _test_domain(m.group(1).lower()):
            skipped["test domain"] += 1
        elif lc in exclude:
            skipped["--exclude"] += 1
        elif not email_prefs.is_subscribed(u):
            skipped["opted out"] += 1
        elif u["_id"] in sent:
            skipped["already sent"] += 1
        elif lc in seen:
            skipped["duplicate address"] += 1
        else:
            seen.add(lc)
            eligible.append(u)
    return eligible, skipped


# ---- Modes ----------------------------------------------------------------

def _dry_run(db, update: Update, eligible: list[dict]) -> int:
    from backend.services.email import build_message

    sample_user = eligible[0] if eligible else {}
    r = render(update, sample_user.get("name"),
               sample_user.get("email_unsub_token") or "SAMPLE-TOKEN")
    msg = build_message("recipient@example.com", r.subject, r.text, html=r.html,
                        reply_to=REPLY_TO, headers=r.headers)
    out = pathlib.Path(tempfile.mkdtemp(prefix=f"reliafy-update-{update.slug}-"))
    (out / "sample.eml").write_bytes(bytes(msg))
    (out / "sample.txt").write_text(r.text, encoding="utf-8")
    (out / "sample.html").write_text(r.html, encoding="utf-8")
    print(f"Sample written to {out}/ (sample.eml, sample.txt, sample.html)")
    print("Dry run: nothing sent, nothing written. Use --test-to EMAIL or --send.")
    return 0


def _test_send(db, update: Update, to: str) -> int:
    from backend.services import email as email_service

    user = db.users.find_one({"email_lc": to.strip().lower()}, {"name": 1}) or {}
    r = render(update, user.get("name"), TEST_TOKEN)
    try:
        email_service.send_now(to, r.subject, r.text, html=r.html,
                               reply_to=REPLY_TO, headers=r.headers)
    except Exception as exc:  # noqa: BLE001
        print(f"Test send to {to} FAILED: {exc}", file=sys.stderr)
        return 1
    print(f"Test copy sent to {to} (unsubscribe link inert). Nothing recorded.")
    return 0


def _record(db, slug: str, u: dict, status: str, error: str | None = None) -> None:
    db.update_sends.update_one(
        {"_id": f"{slug}:{u['_id']}"},
        {"$set": {"update_slug": slug, "uid": u["_id"], "email": u.get("email"),
                  "status": status, "error": error,
                  "sent_at": datetime.now(timezone.utc)}},
        upsert=True,
    )


def _send_all(db, update: Update, eligible: list[dict], delay: float,
              sleep=time.sleep) -> int:
    from backend.services import email as email_service
    from backend.services import email_prefs

    db.update_sends.create_index([("update_slug", 1), ("uid", 1)], unique=True)
    tally, consecutive = Counter(), 0
    for i, u in enumerate(eligible):
        if i:
            sleep(delay)
        # Re-read: someone may have unsubscribed while the run was going.
        fresh = db.users.find_one({"_id": u["_id"]}) or {}
        if not email_prefs.is_subscribed(fresh):
            _record(db, update.slug, u, "skipped", "opted out during send")
            tally["skipped"] += 1
            continue
        token = email_prefs.token_for(db, u["_id"])
        r = render(update, fresh.get("name"), token)
        try:
            email_service.send_now(fresh.get("email") or u["email"], r.subject, r.text,
                                   html=r.html, reply_to=REPLY_TO, headers=r.headers)
        except Exception as exc:  # noqa: BLE001 - recorded, retried next run
            _record(db, update.slug, u, "failed", str(exc)[:500])
            tally["failed"] += 1
            consecutive += 1
            print(f"  failed {u['_id']}: {exc}", file=sys.stderr)
            if consecutive >= MAX_CONSECUTIVE_FAILURES:
                print(f"Stopping: {consecutive} failures in a row (SMTP down?). "
                      "Re-run to retry.", file=sys.stderr)
                break
            continue
        consecutive = 0
        _record(db, update.slug, u, "sent")
        tally["sent"] += 1
        if tally["sent"] % 25 == 0:
            print(f"  ... {tally['sent']} sent")
    print(f"Done: {tally['sent']} sent, {tally['failed']} failed, "
          f"{tally['skipped']} skipped (of {len(eligible)} eligible).")
    return 1 if tally["failed"] else 0


def main(argv: list[str] | None = None, *, input_fn=input, sleep=time.sleep,
         updates_dir: pathlib.Path | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m backend.scripts.send_update",
        description="Email a What's-new update to subscribed users (dry run by default).",
    )
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--update", metavar="SLUG", help="update slug (filename minus date and .md)")
    src.add_argument("--file", metavar="PATH", help="path to an update .md file")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--test-to", metavar="EMAIL", help="send one copy here; records nothing")
    mode.add_argument("--send", action="store_true", help="send to every eligible user")
    parser.add_argument("--yes", action="store_true", help="skip the confirmation prompt (--send)")
    parser.add_argument("--exclude", metavar="EMAIL", action="append", default=[],
                        help="skip this address (repeatable, case-insensitive)")
    parser.add_argument("--delay", type=float, default=1.0,
                        help="seconds between sends (default 1.0)")
    parser.add_argument("--limit", type=int, default=None, help="send to at most N users")
    args = parser.parse_args(argv)

    from backend import db as db_module
    from backend.services import email as email_service

    path = pathlib.Path(args.file) if args.file else find_update(args.update, updates_dir or UPDATES_DIR)
    update = load_update(path)
    if args.update and update.slug != args.update:  # pragma: no cover - find_update guarantees
        raise SystemExit("slug mismatch")

    print(f"Update: {update.title!r} ({update.slug}, dated {update.date or '?'})")
    print(f"Subject: {update.subject}")
    today = datetime.now(timezone.utc).date().isoformat()
    future = bool(update.date) and update.date > today
    if future:
        print(f"WARNING: dated {update.date}, after today ({today}) — the web page "
              "won't be live yet, so the email's link would 404.")

    if (args.test_to or args.send) and not email_service.enabled():
        print("SMTP isn't configured (SMTP_HOST / EMAIL_FROM); refusing to send.",
              file=sys.stderr)
        return 2

    db = db_module.get_db()

    if args.test_to:
        return _test_send(db, update, args.test_to)

    exclude = {e.strip().lower() for e in args.exclude if e.strip()}
    eligible, skipped = recipients(db, update.slug, exclude)
    print(f"Eligible: {len(eligible)}")
    print(f"Excluded: {sum(skipped.values())}"
          + "".join(f"\n  {reason}: {n}" for reason, n in sorted(skipped.items())))
    if args.limit is not None:
        eligible = eligible[: max(args.limit, 0)]
        print(f"Limited to {len(eligible)} this run.")

    if not args.send:
        return _dry_run(db, update, eligible)

    if future:
        print("Refusing to send an update dated in the future.", file=sys.stderr)
        return 1
    if not eligible:
        print("Nobody to send to.")
        return 0
    if not args.yes:
        try:
            typed = input_fn(f"Send {update.slug!r} to {len(eligible)} users? "
                             f"Type the slug to confirm: ")
        except EOFError:
            typed = ""
        if typed.strip() != update.slug:
            print("Not confirmed; nothing sent.")
            return 1
    return _send_all(db, update, eligible, args.delay, sleep=sleep)


if __name__ == "__main__":
    sys.exit(main())
