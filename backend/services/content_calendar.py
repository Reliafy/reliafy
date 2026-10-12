"""The publishing calendar on the admin page's Content tab.

One month of what's published, scheduled and planned, assembled from:

* the calendar's slots, ``.github/content/calendar.yml`` (the Dockerfile
  copies it into the image at the same path);
* the build's content index, ``frontend/dist/content.json`` (blog posts with
  their frontmatter ``type`` and image, What's new updates with ``send``),
  and the LinkedIn feed in ``frontend/dist/feeds.json`` (short posts and the
  automatic announcements, exactly as ``/social/feed.xml`` serves them);
* the email logs (``content_jobs``, ``update_sends``) for each What's new.

Statuses: **published** (dated today or earlier, UTC: live on the site and in
its feeds), **scheduled** (in this build, dated later), **planned** (a slot
with no file yet) and **missed** (a planned slot whose date has passed). A
**gap** is a weekday with no LinkedIn item, from the LinkedIn feed's first
day on (a weekday with a planned slot isn't one: its announcement will come).

:func:`assemble` is pure and unit-tested; :func:`month_view` loads the inputs.
"""

from __future__ import annotations

import calendar as _calendar
import json
import pathlib
from datetime import date, datetime, timedelta, timezone
from typing import Any

from backend import config
from backend.services import content_jobs, remote_json

ROOT = pathlib.Path(__file__).resolve().parents[2]
CALENDAR = ROOT / ".github" / "content" / "calendar.yml"
DIST = ROOT / "frontend" / "dist"
LINKEDIN_FEED = "/social/feed.xml"
SITE = "https://reliafy.com"

BLOG_TYPES = ("technical", "commentary", "tutorial")
# The drafting job: 08:00 Brisbane on the 15th (.github/workflows/content-draft.yml).
DRAFT_DAY, DRAFT_HOUR = 15, 8
CONTENT_PRS = remote_json.github("repos/Reliafy/reliafy/pulls?state=all&per_page=30")


# ---- Inputs ---------------------------------------------------------------------

def load_calendar(path: pathlib.Path = CALENDAR) -> dict:
    try:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - missing or malformed: no slots, never an error page
        return {}
    return data if isinstance(data, dict) else {}


def _json(path: pathlib.Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def load_build(dist: pathlib.Path = DIST) -> dict:
    """The build's posts, updates and LinkedIn items; ``indexed`` False when
    the build has no content index (a dev or self-host build: no prerender)."""
    content, feeds = _json(dist / "content.json"), _json(dist / "feeds.json")
    linkedin = next((f for f in (feeds or {}).get("feeds") or [] if f.get("path") == LINKEDIN_FEED), None)
    return {
        "indexed": content is not None,
        "posts": (content or {}).get("posts") or [],
        "updates": (content or {}).get("updates") or [],
        "linkedin": (linkedin or {}).get("items") or [],
        "site": (feeds or {}).get("site") or SITE,
    }


# ---- Assembly -------------------------------------------------------------------

def _d(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value or "").strip()[:10])
    except ValueError:
        return None


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _local_path(url: str, site: str) -> str:
    """A site URL as a path (images and links then work on any host)."""
    u = str(url or "")
    if site and u.startswith(site):
        return u[len(site):] or "/"
    return u


def _status(day: str, today: str, hold_until: str = "") -> str:
    return "published" if day <= today and (not hold_until or hold_until <= today) else "scheduled"


def build_items(*, calendar: dict, posts: list, updates: list, linkedin: list,
                today: str, site: str = SITE) -> list[dict]:
    """Every dated item, slots included: blog posts, updates, LinkedIn items,
    and the calendar's slots that no file fills yet."""
    items: list[dict] = []
    pages = []  # (kind, date, item) for slot matching
    for p in posts:
        if not _d(p.get("date")):
            continue
        t = str(p.get("type") or "").strip().lower()
        it = {"id": f"blog:{p.get('slug')}", "kind": "blog", "type": t if t in BLOG_TYPES else None,
              "date": p["date"][:10], "title": p.get("title") or "Untitled", "text": p.get("summary") or "",
              "link": f"/blog/{p.get('slug')}", "image": _local_path(p.get("image") or "", site),
              "status": _status(p["date"][:10], today)}
        items.append(it)
        pages.append(("blog", it))
    for u in updates:
        if not _d(u.get("date")):
            continue
        it = {"id": f"whatsnew:{u.get('slug')}", "kind": "whatsnew", "type": None, "date": u["date"][:10],
              "title": u.get("title") or "Untitled", "text": u.get("summary") or "",
              "link": f"/whats-new/{u.get('slug')}", "image": "", "slug": u.get("slug"),
              "send": "auto" if str(u.get("send") or "").strip().lower() == "auto" else "manual",
              "status": _status(u["date"][:10], today)}
        items.append(it)
        pages.append(("whatsnew", it))
    for li in linkedin:
        day = str(li.get("date") or "")[:10]
        if not _d(day):
            continue
        short = li.get("kind") == "short"
        hold = str(li.get("hold_until") or "")[:10]
        items.append({
            "id": f"li:{li.get('guid')}", "kind": "linkedin" if short else "announcement", "type": None,
            "date": day, "title": li.get("title") or "", "text": li.get("summary") or "",
            "link": li.get("link") or "", "image": _local_path(li.get("image") or "", site),
            "hold_until": hold if hold > day else "", "status": _status(day, today, hold),
        })

    # Each slot is filled by a post of its kind in the same week (the exact
    # date first); a blog post without a frontmatter type takes its slot's.
    used: set[str] = set()
    for slot in calendar.get("slots") or []:
        day = _d(slot.get("date"))
        stype = str(slot.get("type") or "").strip().lower()
        if not day or not stype:
            continue
        kind = "whatsnew" if stype == "whatsnew" else "blog"
        week = _monday(day)
        cands = [it for k, it in pages if k == kind and it["id"] not in used and _monday(_d(it["date"])) == week]
        cands.sort(key=lambda it: (it["date"] != day.isoformat(), it["date"]))
        if cands:
            it = cands[0]
            used.add(it["id"])
            it["slot"] = {"date": day.isoformat(), "type": stype, "title": slot.get("title") or ""}
            if kind == "blog" and not it["type"] and stype in BLOG_TYPES:
                it["type"] = stype
            continue
        title = str(slot.get("title") or "").strip()
        items.append({
            "id": f"slot:{day.isoformat()}:{stype}", "kind": kind,
            "type": stype if stype in BLOG_TYPES else None, "date": day.isoformat(),
            "title": "To be chosen" if title.lower() == "to be chosen" else title,
            "text": "", "link": "", "image": "", "slot": {"date": day.isoformat(), "type": stype, "title": title},
            "status": "missed" if day.isoformat() < today else "planned",
        })

    order = {"whatsnew": 0, "blog": 1, "announcement": 2, "linkedin": 3}
    items.sort(key=lambda it: (it["date"], order.get(it["kind"], 9), it["title"]))
    return items


def month_range(month: str) -> tuple[date, date]:
    """First and last day of ``YYYY-MM``; ValueError otherwise."""
    y, m = (int(x) for x in month.split("-"))
    if len(month) != 7 or not (1 <= m <= 12):
        raise ValueError(month)
    return date(y, m, 1), date(y, m, _calendar.monthrange(y, m)[1])


def assemble(month: str, *, today: str, calendar: dict, posts: list, updates: list,
             linkedin: list, site: str = SITE) -> dict:
    """The month's items, its gaps and counts, and the next item to go out
    (from any month)."""
    first, last = month_range(month)
    everything = build_items(calendar=calendar, posts=posts, updates=updates, linkedin=linkedin,
                             today=today, site=site)
    lo, hi = first.isoformat(), last.isoformat()
    items = [it for it in everything if lo <= it["date"] <= hi]

    li_dates = [it["date"] for it in everything if it["kind"] in ("linkedin", "announcement")]
    start = min(li_dates) if li_dates else None
    skipped = {str(w)[:10] for w in calendar.get("skipped_weeks") or []}
    covered = {it["date"] for it in items
               if it["kind"] in ("linkedin", "announcement")
               or (it["status"] in ("planned", "missed") and it.get("slot"))}
    gaps = []
    if start:
        d = first
        while d <= last:
            iso = d.isoformat()
            if d.weekday() < 5 and iso >= start and iso not in covered and _monday(d).isoformat() not in skipped:
                gaps.append(iso)
            d += timedelta(days=1)

    upcoming = [it for it in everything if it["date"] > today and it["status"] != "missed"]
    return {
        "month": month,
        "today": today,
        "items": items,
        "gaps": gaps,
        "counts": {
            "posts": sum(it["kind"] in ("blog", "whatsnew") and it["status"] not in ("planned", "missed")
                         for it in items),
            "planned": sum(it["status"] in ("planned", "missed") for it in items),
            "linkedin": sum(it["kind"] in ("linkedin", "announcement") for it in items),
            "gaps": len(gaps),
        },
        "next": upcoming[0] if upcoming else None,
        "linkedin_start": start,
    }


# ---- What's new email -------------------------------------------------------------

def email_status(db, item: dict, *, auto_send: bool) -> dict:
    """A What's new update's email: auto or manual, the test copy (sent when),
    the list send (how many, from ``update_sends``), and the auto-send switch."""
    slug = item.get("slug") or ""
    day = _d(item.get("date"))
    test = db.content_jobs.find_one({"_id": f"update-test:{slug}"}) or {}
    job = db.content_jobs.find_one({"_id": f"update-send:{slug}"}) or {}
    sent = db.update_sends.count_documents({"update_slug": slug, "status": "sent"})
    last = next(iter(db.update_sends.find({"update_slug": slug, "status": "sent"}, {"sent_at": 1})
                     .sort("sent_at", -1).limit(1)), None)

    def iso(v):
        if isinstance(v, datetime):
            return (v if v.tzinfo else v.replace(tzinfo=timezone.utc)).isoformat()
        return v

    return {
        "send": item.get("send") or "manual",
        "auto_send": bool(auto_send),
        "test_due": content_jobs.friday_before(day).isoformat() if day else None,
        "test": ({"status": test.get("status"), "at": iso(test.get("finished_at") or test.get("started_at"))}
                 if test else None),
        "list": {"sent": sent, "status": job.get("status"),
                 "at": iso(last.get("sent_at")) if last else None},
    }


# ---- Pipeline -----------------------------------------------------------------------

def next_draft_run(now: datetime) -> str:
    """The drafting job's next run (08:00 Brisbane on the 15th), ISO with offset."""
    local = now.astimezone(content_jobs.BRISBANE)
    run = local.replace(day=DRAFT_DAY, hour=DRAFT_HOUR, minute=0, second=0, microsecond=0)
    if run <= local:
        y, m = (local.year + 1, 1) if local.month == 12 else (local.year, local.month + 1)
        run = run.replace(year=y, month=m)
    return run.isoformat()


def last_content_pr(*, refresh: bool = False) -> dict:
    """The latest pull request from a ``content/`` branch (GitHub, cached)."""
    res = remote_json.get(CONTENT_PRS, refresh=refresh)
    if res.data is None:
        return {"error": res.error or "unavailable"}
    for p in res.data:
        if str((p.get("head") or {}).get("ref") or "").startswith("content/"):
            state = "merged" if p.get("merged_at") else p.get("state")
            return {"number": p.get("number"), "title": p.get("title"), "url": p.get("html_url"),
                    "state": state, "at": p.get("merged_at") or p.get("created_at")}
    return {"none": True}


def pipeline(site: str, *, now: datetime, refresh: bool = False) -> dict:
    return {
        "next_draft": next_draft_run(now),
        "last_pr": last_content_pr(refresh=refresh),
        "scheduler": bool(config.CONTENT_CRON_AUDIENCE and config.CONTENT_CRON_SA),
        "auto_send": bool(config.UPDATE_AUTO_SEND),
        "feed_url": f"{site}{LINKEDIN_FEED}",
    }


def month_view(db, month: str, *, now: datetime | None = None, dist: pathlib.Path = DIST,
               calendar_path: pathlib.Path = CALENDAR, refresh: bool = False) -> dict:
    """Everything the Content tab shows for ``month`` (YYYY-MM)."""
    now = now or datetime.now(timezone.utc)
    build = load_build(dist)
    view = assemble(month, today=now.astimezone(timezone.utc).date().isoformat(),
                    calendar=load_calendar(calendar_path), posts=build["posts"], updates=build["updates"],
                    linkedin=build["linkedin"], site=build["site"])
    for it in view["items"]:
        if it["kind"] == "whatsnew" and it.get("slug"):
            it["email"] = email_status(db, it, auto_send=config.UPDATE_AUTO_SEND)
    view["indexed"] = build["indexed"]
    view["pipeline"] = pipeline(build["site"], now=now, refresh=refresh)
    return view
