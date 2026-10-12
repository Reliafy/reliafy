"""The operators' monthly content report (#353, #367).

What last month's content brought in, from first-party data only:

* **posts** — page views and visitors of each blog post and What's new
  update, and the sign-ups whose visit read it first;
* **channels** — tagged landings (``utm_source`` / ``utm_campaign``: email,
  linkedin, rss…): visitors, page views and the sign-ups they led to;
* **sign-ups** — new accounts, and how many of their visits were tagged;
* **emails** — update emails sent (the ``update_sends`` log);
* **unsubscribes** — opt-outs from the update emails in the month.

A sign-up is attributed by its visit: the signup event carries the same
daily visitor hash as that browser's pageviews (``auth.upsert_user``), so it
joins the tagged link and the first post seen that day, *before* signing up.
Visitors are daily hashes (visitor-days), and nothing here is linked to an
account. Months are Brisbane months. The scheduled job (``content_jobs``)
emails it on the 1st; the admin page shows the same tables.
"""

from __future__ import annotations

import html as html_lib
import json
import pathlib
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone

BRISBANE = timezone(timedelta(hours=10), "Australia/Brisbane")
DIST = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "dist"
_POST_RE = re.compile(r"^/(blog|whats-new)/([a-z0-9][a-z0-9-]*)/?$")
_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
NONE = "(untagged)"


def previous_month(day: date) -> str:
    first = day.replace(day=1)
    return (first - timedelta(days=1)).strftime("%Y-%m")


def month_range(month: str) -> tuple[datetime, datetime]:
    """The Brisbane month ``YYYY-MM`` as a UTC [start, end)."""
    if not _MONTH_RE.match(month or ""):
        raise ValueError("month must be YYYY-MM")
    y, m = int(month[:4]), int(month[5:])
    start = datetime(y, m, 1, tzinfo=BRISBANE)
    end = datetime(y + (m == 12), m % 12 + 1, 1, tzinfo=BRISBANE)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def titles(dist: pathlib.Path = DIST) -> dict[str, str]:
    try:
        return json.loads((dist / "content.json").read_text(encoding="utf-8")).get("titles") or {}
    except (OSError, ValueError, AttributeError):
        return {}


def _aware(value):
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def build(db, month: str, page_titles: dict[str, str] | None = None) -> dict:
    start, end = month_range(month)
    page_titles = titles() if page_titles is None else page_titles

    posts = defaultdict(lambda: {"views": 0, "_visitors": set(), "signups": 0})
    channels = defaultdict(lambda: {"pageviews": 0, "_visitors": set(), "signups": 0})
    touches: dict[tuple, dict] = {}
    signups = {"events": 0, "tagged": 0, "untagged": 0}

    events = sorted(
        db.metrics_events.find(
            {"created_at": {"$gte": start, "$lt": end}, "name": {"$in": ["pageview", "signup"]}},
            {"_id": 0, "name": 1, "path": 1, "utm_source": 1, "utm_campaign": 1,
             "visitor": 1, "day": 1, "created_at": 1}),
        key=lambda e: _aware(e.get("created_at")) or start)
    for e in events:
        key = (e.get("day"), e.get("visitor"))
        touch = touches.setdefault(key, {})
        if e.get("name") == "signup":
            signups["events"] += 1
            utm, post = touch.get("utm"), touch.get("post")
            signups["tagged" if utm else "untagged"] += 1
            channels[utm or (NONE, "")]["signups"] += 1
            if post:
                posts[post]["signups"] += 1
            continue
        m = _POST_RE.match(e.get("path") or "")
        post = f"/{m.group(1)}/{m.group(2)}" if m else None
        if post:
            posts[post]["views"] += 1
            posts[post]["_visitors"].add(key)
            touch.setdefault("post", post)
        source = (e.get("utm_source") or "").strip()
        if source:
            utm = (source, (e.get("utm_campaign") or "").strip())
            channels[utm]["pageviews"] += 1
            channels[utm]["_visitors"].add(key)
            touch.setdefault("utm", utm)

    post_rows = [{
        "path": path,
        "title": page_titles.get(path, ""),
        "kind": "update" if path.startswith("/whats-new/") else "blog",
        "views": row["views"],
        "visitors": len(row["_visitors"]),
        "signups": row["signups"],
    } for path, row in posts.items()]
    post_rows.sort(key=lambda r: (-r["views"], -r["signups"], r["path"]))

    channel_rows = [{
        "source": source,
        "campaign": campaign,
        "visitors": len(row["_visitors"]),
        "pageviews": row["pageviews"],
        "signups": row["signups"],
    } for (source, campaign), row in channels.items()]
    channel_rows.sort(key=lambda r: (r["source"] == NONE, -r["signups"], -r["visitors"],
                                     r["source"], r["campaign"]))

    sent = Counter()
    for r in db.update_sends.find({"status": "sent", "sent_at": {"$gte": start, "$lt": end}},
                                  {"update_slug": 1}):
        sent[r.get("update_slug") or ""] += 1

    unsub = Counter()
    for u in db.users.find({"email_updates_opt_out": True,
                            "email_updates_changed_at": {"$gte": start, "$lt": end}},
                           {"email_updates_source": 1}):
        unsub[u.get("email_updates_source") or "unknown"] += 1

    return {
        "month": month,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "posts": post_rows,
        "channels": channel_rows,
        "signups": {"accounts": db.users.count_documents({"created_at": {"$gte": start, "$lt": end}}),
                    **signups},
        "emails": [{"slug": s, "sent": n} for s, n in sorted(sent.items())],
        "unsubscribes": {"total": sum(unsub.values()), "by_source": dict(sorted(unsub.items()))},
    }


def month_label(month: str) -> str:
    return datetime.strptime(month + "-01", "%Y-%m-%d").strftime("%B %Y")


def _tables(report: dict) -> list[tuple[str, list[str], list[list]]]:
    s = report["signups"]
    return [
        ("Posts", ["Post", "Views", "Visitors", "Sign-ups"],
         [[r["title"] or r["path"], r["views"], r["visitors"], r["signups"]] for r in report["posts"]]),
        ("Channels (UTM)", ["Source", "Campaign", "Visitors", "Page views", "Sign-ups"],
         [[r["source"], r["campaign"] or "—", r["visitors"], r["pageviews"], r["signups"]]
          for r in report["channels"]]),
        ("Sign-ups", ["New accounts", "Tagged visit", "Untagged"],
         [[s["accounts"], s["tagged"], s["untagged"]]]),
        ("Update emails", ["Update", "Sent"], [[r["slug"], r["sent"]] for r in report["emails"]]),
        ("Unsubscribes", ["How", "Count"],
         [[k, v] for k, v in report["unsubscribes"]["by_source"].items()]),
    ]


def render_text(report: dict) -> str:
    lines = [f"Reliafy content report: {month_label(report['month'])}", ""]
    for title, head, rows in _tables(report):
        lines.append(title)
        if not rows:
            lines += ["  (none)", ""]
            continue
        cells = [head] + [[str(c) for c in r] for r in rows]
        widths = [max(len(r[i]) for r in cells) for i in range(len(head))]
        for r in cells:
            lines.append("  " + "  ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip())
        lines.append("")
    lines.append("Visitors are daily-hashed visitor-days. A sign-up counts for the tagged link and "
                 "the first post its visit saw before signing up.")
    return "\n".join(lines) + "\n"


def render_html(report: dict) -> str:
    from backend.services import email_templates as tpl

    esc = html_lib.escape
    cell = f"padding:4px 10px;border-bottom:1px solid {tpl.LINE};text-align:left;font-size:14px;"
    parts = []
    for title, head, rows in _tables(report):
        parts.append(f'<h3 style="margin:20px 0 6px;font-size:15px;color:{tpl.INK};">{esc(title)}</h3>')
        if not rows:
            parts.append(f'<p style="margin:0;color:{tpl.MUTED};font-size:14px;">None.</p>')
            continue
        th = "".join(f'<th style="{cell}color:{tpl.MUTED};font-weight:600;">{esc(h)}</th>' for h in head)
        trs = "".join("<tr>" + "".join(f'<td style="{cell}">{esc(str(c))}</td>' for c in r) + "</tr>"
                      for r in rows)
        parts.append(f'<table cellpadding="0" cellspacing="0" style="border-collapse:collapse;'
                     f'width:100%;">{"<tr>" + th + "</tr>"}{trs}</table>')
    parts.append(f'<p style="margin:16px 0 0;color:{tpl.MUTED};font-size:13px;">Visitors are '
                 "daily-hashed visitor-days. A sign-up counts for the tagged link and the first "
                 "post its visit saw before signing up.</p>")
    from backend.services.email import _app_url

    return tpl.layout(body_html="".join(parts), base_url=_app_url("/"),
                      title=f"Content report: {month_label(report['month'])}",
                      eyebrow="Operators", cta=("Open the admin page", _app_url("/admin")))
