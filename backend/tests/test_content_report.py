"""#353/#367: the operators' monthly content report — views per post, sign-ups
by tagged link and post, update emails sent, unsubscribes — emailed on the 1st
and shown on the admin page."""

from datetime import date, datetime, timedelta, timezone

import mongomock
import pytest

from backend.services import content_jobs, content_report, metrics

UTC = timezone.utc
OPS = "ops@ops.example.org"
TITLES = {"/blog/import-rbds": "Import your RBDs", "/whats-new/october-2026": "What's new: October"}


def at(y, m, d, hh=12):
    """Brisbane wall-clock time as an aware UTC datetime."""
    return datetime(y, m, d, hh, tzinfo=content_report.BRISBANE).astimezone(UTC)


@pytest.fixture()
def db(monkeypatch):
    from backend import config, db as db_module

    d = mongomock.MongoClient()["reliafy_test"]
    monkeypatch.setattr(db_module, "_db", d)
    monkeypatch.setattr(db_module, "_simulated", True)
    monkeypatch.setattr(config, "PUBLIC_BASE_URL", None)
    monkeypatch.setattr(config, "CONTENT_OPERATOR_EMAILS", [OPS])
    monkeypatch.setattr(config, "UPDATE_AUTO_SEND", False)
    monkeypatch.setattr(content_report, "titles", lambda *a, **k: TITLES)
    return d


def _event(d, name, path, when, visitor, source="", campaign=""):
    d.metrics_events.insert_one({
        "name": name, "path": path, "utm_source": source, "utm_medium": "", "utm_campaign": campaign,
        "visitor": visitor, "day": when.strftime("%Y-%m-%d"), "created_at": when})


def _seed(d):
    oct5 = at(2026, 10, 5)
    # Visitor A: LinkedIn link to the import post, then signs up.
    _event(d, "pageview", "/blog/import-rbds", oct5, "A", "linkedin", "import-rbds")
    _event(d, "pageview", "/modelling", oct5 + timedelta(minutes=1), "A", "linkedin", "import-rbds")
    _event(d, "signup", "/login", oct5 + timedelta(minutes=2), "A")
    # Visitor B: the update email, reads October's update, no sign-up.
    _event(d, "pageview", "/whats-new/october-2026", oct5, "B", "email", "october-2026")
    # Visitor C: untagged, reads the import post twice, signs up.
    _event(d, "pageview", "/blog/import-rbds", oct5, "C")
    _event(d, "pageview", "/blog/import-rbds/", oct5 + timedelta(minutes=1), "C")
    _event(d, "signup", "/login", oct5 + timedelta(minutes=3), "C")
    # Visitor D signs up, and only *afterwards* lands from RSS: not attributed.
    _event(d, "signup", "/login", oct5, "D")
    _event(d, "pageview", "/blog/import-rbds", oct5 + timedelta(minutes=5), "D", "rss", "import-rbds")
    # Outside the month (Brisbane): 1 Oct 09:00 is still September in UTC terms
    # but October in Brisbane — counted; 1 Nov 08:00 Brisbane — not counted.
    _event(d, "pageview", "/blog/import-rbds", at(2026, 10, 1, 9), "E")
    _event(d, "pageview", "/blog/import-rbds", at(2026, 11, 1, 8), "F")
    # Not a post.
    _event(d, "pageview", "/blog/feed.xml", oct5, "G")
    d.users.insert_many([
        {"_id": "a", "created_at": oct5}, {"_id": "c", "created_at": oct5}, {"_id": "d", "created_at": oct5},
        {"_id": "o1", "email_updates_opt_out": True, "email_updates_changed_at": oct5,
         "email_updates_source": "one_click"},
        {"_id": "o2", "email_updates_opt_out": True, "email_updates_changed_at": at(2026, 9, 20),
         "email_updates_source": "link"},
        {"_id": "o3", "email_updates_opt_out": False, "email_updates_changed_at": oct5},
    ])
    d.update_sends.insert_many([
        {"_id": "october-2026:u1", "update_slug": "october-2026", "uid": "u1", "status": "sent", "sent_at": at(2026, 10, 4)},
        {"_id": "october-2026:u2", "update_slug": "october-2026", "uid": "u2", "status": "sent", "sent_at": at(2026, 10, 4)},
        {"_id": "october-2026:u3", "update_slug": "october-2026", "uid": "u3", "status": "failed", "sent_at": at(2026, 10, 4)},
    ])


def test_month_helpers():
    assert content_report.previous_month(date(2026, 11, 1)) == "2026-10"
    assert content_report.previous_month(date(2027, 1, 3)) == "2026-12"
    start, end = content_report.month_range("2026-12")
    assert start == datetime(2026, 11, 30, 14, tzinfo=UTC) and end == datetime(2026, 12, 31, 14, tzinfo=UTC)
    with pytest.raises(ValueError):
        content_report.month_range("2026-13")


def test_report_tables(db):
    _seed(db)
    r = content_report.build(db, "2026-10")
    posts = {p["path"]: p for p in r["posts"]}
    assert set(posts) == {"/blog/import-rbds", "/whats-new/october-2026"}
    imp = posts["/blog/import-rbds"]
    assert imp["title"] == "Import your RBDs" and imp["kind"] == "blog"
    assert imp["views"] == 5            # A, C twice, D, E (Brisbane 1 Oct)
    assert imp["visitors"] == 4         # visitor-days A, C, D, E
    assert imp["signups"] == 2          # A and C read it before signing up; D after
    assert posts["/whats-new/october-2026"]["views"] == 1
    assert posts["/whats-new/october-2026"]["kind"] == "update"

    ch = {(c["source"], c["campaign"]): c for c in r["channels"]}
    assert ch[("linkedin", "import-rbds")] == {"source": "linkedin", "campaign": "import-rbds",
                                               "visitors": 1, "pageviews": 2, "signups": 1}
    assert ch[("email", "october-2026")]["signups"] == 0
    assert ch[("rss", "import-rbds")]["signups"] == 0          # the visit came after the sign-up
    assert ch[(content_report.NONE, "")]["signups"] == 2       # C and D
    assert r["signups"] == {"accounts": 3, "events": 3, "tagged": 1, "untagged": 2}
    assert r["emails"] == [{"slug": "october-2026", "sent": 2}]
    assert r["unsubscribes"] == {"total": 1, "by_source": {"one_click": 1}}


def test_report_renders_as_text_and_html(db):
    _seed(db)
    r = content_report.build(db, "2026-10")
    text = content_report.render_text(r)
    assert text.startswith("Reliafy content report: October 2026")
    assert "Import your RBDs" in text and "linkedin" in text and "october-2026" in text
    html = content_report.render_html(r)
    assert "<table" in html and "Import your RBDs" in html


def test_empty_month(db):
    r = content_report.build(db, "2026-08")
    assert r["posts"] == [] and r["channels"] == [] and r["emails"] == []
    assert "(none)" in content_report.render_text(r)


def test_signup_event_carries_the_visitors_daily_hash(db):
    """The signup joins its visit: same hash as that browser's pageviews."""
    from backend.auth import upsert_user

    upsert_user(db, {"uid": "new1", "email": "n@x.example.org"}, ip="203.0.113.9", user_agent="HeadlessThing/1")
    (ev,) = list(db.metrics_events.find({"name": "signup"}))
    day = ev["day"]
    assert ev["visitor"] == metrics._visitor_hash(day, "203.0.113.9", "HeadlessThing/1")
    # Even a bot-looking user agent's account is counted; and only once.
    upsert_user(db, {"uid": "new1", "email": "n@x.example.org"}, ip="203.0.113.9", user_agent="x")
    assert db.metrics_events.count_documents({"name": "signup"}) == 1


# ---- In the scheduled job --------------------------------------------------------

@pytest.fixture()
def outbox(monkeypatch):
    from backend import config
    from backend.services import email

    monkeypatch.setattr(config, "SMTP_HOST", "smtp.invalid")
    monkeypatch.setattr(config, "EMAIL_FROM", "Reliafy <updates@reliafy.test>")
    sent = []
    monkeypatch.setattr(email, "_deliver", lambda msg, **kw: sent.append(msg))
    return sent


def test_job_emails_last_months_report_on_the_first_once(db, outbox):
    _seed(db)
    assert content_jobs.run(db, now=at(2026, 11, 1, 9))["actions"] == []   # before 10:00
    out = content_jobs.run(db, now=at(2026, 11, 1, 10))
    (action,) = out["actions"]
    assert action == {"step": "monthly report", "month": "2026-10", "result": "sent", "sent": 1, "failed": 0}
    (msg,) = outbox
    assert msg["To"] == OPS and msg["Subject"] == "Reliafy content report: October 2026"
    assert "Import your RBDs" in msg.get_body(("plain",)).get_content()
    # Again later that day and that week: not again. After the 7th: nothing.
    assert content_jobs.run(db, now=at(2026, 11, 1, 15))["actions"][0]["result"] == "already sent"
    assert content_jobs.run(db, now=at(2026, 11, 8, 10))["actions"] == []
    assert len(outbox) == 1


def test_job_report_catches_up_a_missed_first_and_dry_runs(db, outbox):
    dry = content_jobs.run(db, now=at(2026, 12, 3, 11), dry_run=True)["actions"][0]
    assert dry["result"] == "would send" and dry["month"] == "2026-11"
    assert outbox == [] and db.content_jobs.count_documents({}) == 0
    assert content_jobs.run(db, now=at(2026, 12, 3, 11))["actions"][0]["result"] == "sent"


def test_admin_endpoint(db, monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config
    from backend.auth import get_current_user
    from backend.main import app

    _seed(db)
    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    who = {"uid": "op", "email": "op@ops.example.org", "email_verified": True}
    app.dependency_overrides[get_current_user] = lambda: dict(who)
    try:
        client = TestClient(app)
        assert client.get("/api/admin/content-report?month=2026-10").status_code == 403
        monkeypatch.setattr(config, "ADMIN_EMAILS", {"op@ops.example.org"})
        r = client.get("/api/admin/content-report?month=2026-10")
        assert r.status_code == 200 and r.json()["signups"]["accounts"] == 3
        assert client.get("/api/admin/content-report?month=oct").status_code == 422
        assert client.get("/api/admin/content-report").status_code == 200
    finally:
        app.dependency_overrides.clear()
