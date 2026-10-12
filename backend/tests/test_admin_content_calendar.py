"""The admin page's Content tab: the publishing calendar's assembly
(published, scheduled, planned, missed, gaps), What's new email status, the
pipeline box, and the admin-only endpoint."""

import json
from datetime import datetime, timezone

import mongomock
import pytest

from backend.services import content_calendar as C
from backend.services import remote_json
from backend.services.remote_json import Result

SITE = "https://reliafy.com"
CALENDAR = {
    "slots": [
        {"date": "2026-10-12", "type": "tutorial", "title": "Import your RBDs"},
        {"date": "2026-10-19", "type": "commentary", "title": "Spreadsheets"},
        {"date": "2026-10-26", "type": "tutorial", "title": "Verify a safety function"},
        {"date": "2026-11-02", "type": "whatsnew", "title": "What's new: November"},
        {"date": "2026-11-09", "type": "technical", "title": "to be chosen"},
    ],
    "skipped_weeks": ["2026-12-28"],
}
POSTS = [
    {"slug": "titan", "title": "Titan GPUs", "date": "2026-09-22", "summary": "An agent.", "image": "", "type": ""},
    # Fills the 12 Oct slot and takes its type.
    {"slug": "import-rbds", "title": "Import your RBDs", "date": "2026-10-12", "summary": "Import them.",
     "image": "/blog/import-card.png", "type": ""},
    # A day off its slot's date, in the same week, with its own type.
    {"slug": "spreadsheets", "title": "Spreadsheets", "date": "2026-10-20", "summary": "Where it goes wrong.",
     "image": "", "type": "technical"},
]
UPDATES = [
    {"slug": "october-2026", "title": "What's new: October", "date": "2026-10-01", "summary": "MCP.", "send": ""},
    {"slug": "november-2026", "title": "What's new: November", "date": "2026-11-02", "summary": "More.",
     "send": "auto"},
]
LINKEDIN = [
    {"kind": "short", "title": "Reliafy now opens block diagrams", "link": f"{SITE}/blog/import-rbds",
     "guid": f"{SITE}/social/2026-10-12-import-ffort-benchmarks", "date": "2026-10-12", "hold_until": "",
     "summary": "Reliafy now opens block diagrams.\n\nWe checked.", "image": ""},
    {"kind": "blog", "title": "Import your RBDs", "link": f"{SITE}/blog/import-rbds",
     "guid": f"{SITE}/blog/import-rbds#linkedin", "date": "2026-10-12", "hold_until": "",
     "summary": "Import your RBDs\n\nImport them.", "image": f"{SITE}/blog/import-card.png"},
    {"kind": "short", "title": "Spreadsheets, held", "link": f"{SITE}/blog/spreadsheets",
     "guid": f"{SITE}/social/2026-10-14-sheets", "date": "2026-10-14", "hold_until": "2026-10-20",
     "summary": "Spreadsheets.", "image": ""},
    {"kind": "blog", "title": "Spreadsheets", "link": f"{SITE}/blog/spreadsheets",
     "guid": f"{SITE}/blog/spreadsheets#linkedin", "date": "2026-10-20", "hold_until": "", "summary": "S",
     "image": ""},
    {"kind": "short", "title": "Friday", "link": "", "guid": f"{SITE}/social/2026-10-16-friday",
     "date": "2026-10-16", "hold_until": "", "summary": "Friday post.", "image": ""},
]


def view(month="2026-10", today="2026-10-13", **kw):
    args = {"calendar": CALENDAR, "posts": POSTS, "updates": UPDATES, "linkedin": LINKEDIN, "site": SITE, **kw}
    return C.assemble(month, today=today, **args)


def by_id(v):
    return {it["id"]: it for it in v["items"]}


def test_published_scheduled_and_slot_types():
    items = by_id(view())
    imp = items["blog:import-rbds"]
    assert imp["status"] == "published" and imp["type"] == "tutorial"      # slot's type
    assert imp["slot"]["date"] == "2026-10-12" and imp["image"] == "/blog/import-card.png"
    sheets = items["blog:spreadsheets"]
    assert sheets["status"] == "scheduled" and sheets["type"] == "technical"  # its own frontmatter type
    assert "slot:2026-10-19:commentary" not in items                          # filled, in its week
    assert items["whatsnew:october-2026"]["status"] == "published"
    assert items["whatsnew:october-2026"]["send"] == "manual"
    assert "blog:titan" not in items                                          # September


def test_planned_and_missed_slots():
    items = by_id(view(today="2026-10-27"))
    missed = by_id(view(today="2026-10-27"))["slot:2026-10-26:tutorial"]
    assert missed["status"] == "missed" and missed["kind"] == "blog" and missed["type"] == "tutorial"
    planned = by_id(view(today="2026-10-13"))["slot:2026-10-26:tutorial"]
    assert planned["status"] == "planned" and planned["title"] == "Verify a safety function"
    nov = by_id(view("2026-11"))
    assert nov["slot:2026-11-09:technical"]["title"] == "To be chosen"
    assert nov["whatsnew:november-2026"]["send"] == "auto"
    assert "slot:2026-11-02:whatsnew" not in nov                              # the update fills it
    assert items["blog:spreadsheets"]["status"] == "published"


def test_linkedin_items_hold_and_kinds():
    items = by_id(view())
    short = items[f"li:{SITE}/social/2026-10-12-import-ffort-benchmarks"]
    assert short["kind"] == "linkedin" and short["status"] == "published"
    assert short["text"].startswith("Reliafy now opens")
    ann = items[f"li:{SITE}/blog/import-rbds#linkedin"]
    assert ann["kind"] == "announcement" and ann["image"] == "/blog/import-card.png"
    held = items[f"li:{SITE}/social/2026-10-14-sheets"]
    assert held["status"] == "scheduled" and held["hold_until"] == "2026-10-20"  # its page isn't live
    assert by_id(view(today="2026-10-20"))[f"li:{SITE}/social/2026-10-14-sheets"]["status"] == "published"


def test_gaps_counts_and_next():
    v = view()
    # LinkedIn starts 12 Oct; covered: 12, 14, 16, 20; 26 has a planned slot.
    assert v["gaps"] == ["2026-10-13", "2026-10-15", "2026-10-19", "2026-10-21", "2026-10-22",
                         "2026-10-23", "2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30"]
    assert v["linkedin_start"] == "2026-10-12"
    assert v["counts"] == {"posts": 3, "planned": 1, "linkedin": 5, "gaps": 10}
    assert v["next"]["id"] == f"li:{SITE}/social/2026-10-14-sheets"
    assert view("2026-09")["gaps"] == []                                      # before the feed began


def test_skipped_weeks_have_no_gaps():
    v = view("2026-12", today="2026-12-01")
    assert not any("2026-12-28" <= g <= "2027-01-01" for g in v["gaps"])
    assert "2026-12-24" in v["gaps"]


def test_bad_month():
    for bad in ("2026-13", "oct", "2026-10-01", ""):
        with pytest.raises(ValueError):
            C.month_range(bad)


# ---- Email status -------------------------------------------------------------------

@pytest.fixture()
def db():
    return mongomock.MongoClient()["reliafy_test"]


def test_email_status_before_and_after(db):
    item = {"slug": "november-2026", "date": "2026-11-02", "send": "auto"}
    s = C.email_status(db, item, auto_send=False)
    assert s == {"send": "auto", "auto_send": False, "test_due": "2026-10-30", "test": None,
                 "list": {"sent": 0, "status": None, "at": None}}
    at = datetime(2026, 10, 30, 0, 5)
    db.content_jobs.insert_one({"_id": "update-test:november-2026", "status": "done", "finished_at": at})
    db.content_jobs.insert_one({"_id": "update-send:november-2026", "status": "partial"})
    for i, status in enumerate(["sent", "sent", "failed"]):
        db.update_sends.insert_one({"_id": f"november-2026:u{i}", "update_slug": "november-2026", "uid": f"u{i}",
                                    "status": status, "sent_at": datetime(2026, 11, 2, 0, i)})
    db.update_sends.insert_one({"_id": "october-2026:u0", "update_slug": "october-2026", "status": "sent"})
    s = C.email_status(db, item, auto_send=True)
    assert s["auto_send"] is True
    assert s["test"] == {"status": "done", "at": "2026-10-30T00:05:00+00:00"}
    assert s["list"] == {"sent": 2, "status": "partial", "at": "2026-11-02T00:01:00+00:00"}
    assert C.email_status(db, {"slug": "x", "date": "2026-10-01", "send": "manual"},
                          auto_send=True)["send"] == "manual"


# ---- Pipeline ---------------------------------------------------------------------

def test_next_draft_run():
    utc = timezone.utc
    assert C.next_draft_run(datetime(2026, 10, 12, 3, tzinfo=utc)) == "2026-10-15T08:00:00+10:00"
    # 08:00 Brisbane on the 15th is 22:00 UTC on the 14th: just after it, next month.
    assert C.next_draft_run(datetime(2026, 10, 14, 22, 1, tzinfo=utc)) == "2026-11-15T08:00:00+10:00"
    assert C.next_draft_run(datetime(2026, 12, 20, tzinfo=utc)) == "2027-01-15T08:00:00+10:00"


def test_last_content_pr(monkeypatch):
    prs = [{"number": 380, "title": "Fix", "html_url": "a", "state": "open", "head": {"ref": "fix/x"}},
           {"number": 379, "title": "Content for October", "html_url": "b", "state": "closed",
            "merged_at": "2026-10-12T06:00:00Z", "created_at": "2026-10-11T00:00:00Z",
            "head": {"ref": "content/october"}}]
    monkeypatch.setattr(remote_json, "get", lambda url, refresh=False: Result(prs, None, 1.0))
    assert C.last_content_pr() == {"number": 379, "title": "Content for October", "url": "b",
                                   "state": "merged", "at": "2026-10-12T06:00:00Z"}
    monkeypatch.setattr(remote_json, "get", lambda url, refresh=False: Result(error="rate limited"))
    assert C.last_content_pr() == {"error": "rate limited"}


# ---- Loading and the endpoint -------------------------------------------------------

@pytest.fixture()
def build(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "content.json").write_text(json.dumps({"pages": {}, "posts": POSTS, "updates": UPDATES}))
    (dist / "feeds.json").write_text(json.dumps({"site": SITE, "feeds": [
        {"path": "/blog/feed.xml", "items": []}, {"path": "/social/feed.xml", "items": LINKEDIN}]}))
    cal = tmp_path / "calendar.yml"
    cal.write_text('slots:\n  - date: "2026-10-26"\n    type: tutorial\n    title: "Verify"\n')
    return dist, cal


def test_month_view_loads_the_build(db, build, monkeypatch):
    from backend import config

    dist, cal = build
    monkeypatch.setattr(remote_json, "get", lambda url, refresh=False: Result(error="timed out"))
    monkeypatch.setattr(config, "CONTENT_CRON_AUDIENCE", "https://x.run.app/internal/content/run")
    monkeypatch.setattr(config, "CONTENT_CRON_SA", None)
    v = C.month_view(db, "2026-11", now=datetime(2026, 10, 13, tzinfo=timezone.utc), dist=dist, calendar_path=cal)
    assert v["indexed"] is True
    nov = by_id(v)["whatsnew:november-2026"]
    assert nov["email"]["send"] == "auto" and nov["email"]["test_due"] == "2026-10-30"
    p = v["pipeline"]
    assert p["scheduler"] is False and p["last_pr"] == {"error": "timed out"}
    assert p["feed_url"] == f"{SITE}/social/feed.xml" and p["next_draft"].startswith("2026-10-15")
    # No build index (a dev build): the calendar's slots only.
    empty = C.month_view(db, "2026-10", now=datetime(2026, 10, 13, tzinfo=timezone.utc),
                         dist=dist / "missing", calendar_path=cal)
    assert empty["indexed"] is False and [it["id"] for it in empty["items"]] == ["slot:2026-10-26:tutorial"]


def test_the_real_calendar_parses():
    cal = C.load_calendar()
    assert cal["slots"] and all({"date", "type", "title"} <= set(s) for s in cal["slots"])
    assert C.load_calendar(C.ROOT / "no-such.yml") == {}


def test_endpoint_is_admin_only(db, monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config
    from backend import db as db_module
    from backend.auth import get_current_user
    from backend.main import app

    monkeypatch.setattr(db_module, "_db", db)
    monkeypatch.setattr(db_module, "_simulated", True)
    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    monkeypatch.setattr(config, "ADMIN_EMAILS", set())
    monkeypatch.setattr(remote_json, "get", lambda url, refresh=False: Result(error="timed out"))
    app.dependency_overrides[get_current_user] = lambda: {"uid": "op", "email": "op@ops.example.org",
                                                          "email_verified": True}
    try:
        client = TestClient(app)
        assert client.get("/api/admin/content-calendar?month=2026-10").status_code == 403
        monkeypatch.setattr(config, "ADMIN_EMAILS", {"op@ops.example.org"})
        r = client.get("/api/admin/content-calendar?month=2026-10")
        assert r.status_code == 200 and r.json()["month"] == "2026-10" and "pipeline" in r.json()
        assert client.get("/api/admin/content-calendar?month=oct").status_code == 422
        r = client.get("/api/admin/content-calendar")
        assert r.status_code == 200 and r.json()["month"] == datetime.now(timezone.utc).strftime("%Y-%m")
    finally:
        app.dependency_overrides.clear()
