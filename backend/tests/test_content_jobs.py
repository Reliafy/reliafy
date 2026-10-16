"""#367: the scheduled What's new send. A `send: auto` update gets a test copy
to the operators on the Friday before and goes to the list at 10:00 Brisbane
on its date, through the CLI's send path. Delivery is always faked."""

import json
from datetime import date, datetime, timedelta, timezone

import mongomock
import pytest
from fastapi.testclient import TestClient

from backend.scripts.send_update import Update
from backend.services import content_jobs

UTC = timezone.utc
OPS = "ops@ops.example.org"


def bne(y, m, d, hh, mm=0):
    """A Brisbane wall-clock time (UTC+10) as an aware UTC datetime."""
    return datetime(y, m, d, hh, mm, tzinfo=content_jobs.BRISBANE).astimezone(UTC)


def _update(slug="november-2026", day="2026-11-02", send="auto"):
    return Update(slug=slug, title="What's new in Reliafy: November 2026", date=day,
                  summary="Lots of things.", subject="New in Reliafy this month",
                  body="Things happened. See [the blog](/blog).", path=None, send=send)


UPDATES = [_update(), _update(slug="manual-one", day="2026-11-02", send="")]


@pytest.fixture()
def db(monkeypatch):
    from backend import config, db as db_module

    d = mongomock.MongoClient()["reliafy_test"]
    monkeypatch.setattr(db_module, "_db", d)
    monkeypatch.setattr(db_module, "_simulated", True)
    monkeypatch.setattr(config, "PUBLIC_BASE_URL", None)
    monkeypatch.setattr(config, "UPDATE_AUTO_SEND", True)
    monkeypatch.setattr(config, "CONTENT_OPERATOR_EMAILS", [OPS])
    monkeypatch.setattr(config, "UPDATE_EMAIL_EXCLUDE", {"skip.me@four.example.org"})
    monkeypatch.setattr(config, "UPDATE_AUTO_SECONDS", 240)
    d.users.insert_many([
        {"_id": "u1", "email": "alice@one.example.org", "name": "Alice Smith"},
        {"_id": "u2", "email": "bob@two.example.org", "name": "Bob"},
        {"_id": "u3", "email": "carol@three.example.org", "email_updates_opt_out": True},  # opted out
        {"_id": "u4", "email": "dev@example.com"},                                        # test domain
        {"_id": "u6", "email": "Skip.Me@four.example.org"},                               # excluded by config
    ])
    # October's report counts as sent: these tests are about the update steps
    # (the report has its own tests below).
    d.content_jobs.insert_one({"_id": "report:2026-10", "status": "done"})
    return d


@pytest.fixture()
def outbox(monkeypatch):
    from backend import config
    from backend.services import email

    monkeypatch.setattr(config, "SMTP_HOST", "smtp.invalid")
    monkeypatch.setattr(config, "EMAIL_FROM", "Reliafy <updates@reliafy.test>")
    sent = []
    monkeypatch.setattr(email, "_deliver", lambda msg, **kw: sent.append(msg))
    return sent


@pytest.fixture()
def pushes(monkeypatch):
    from backend.services import push

    got = []
    monkeypatch.setattr(push, "send", lambda title, message, **kw: got.append((title, message)) or True)
    return got


def _run(db, when, **kw):
    """One run (no extensions are installed in these tests)."""
    kw.setdefault("updates", UPDATES)
    return content_jobs.run(db, now=when, sleep=lambda s: None, **kw)


def test_friday_before():
    assert content_jobs.friday_before(date(2026, 11, 2)) == date(2026, 10, 30)   # Monday
    assert content_jobs.friday_before(date(2026, 11, 6)) == date(2026, 10, 30)   # a Friday: the one before
    assert content_jobs.friday_before(date(2026, 11, 7)) == date(2026, 11, 6)    # Saturday


def test_nothing_before_the_friday_or_before_ten(db, outbox, pushes):
    assert _run(db, bne(2026, 10, 29, 12))["actions"] == []
    assert _run(db, bne(2026, 10, 30, 9, 55))["actions"] == []
    assert outbox == [] and pushes == []


def test_friday_test_copy_goes_to_operators_once(db, outbox, pushes):
    out = _run(db, bne(2026, 10, 30, 10, 5))
    (action,) = out["actions"]
    assert action["step"] == "test copy" and action["result"] == "sent"
    (msg,) = outbox
    assert msg["To"] == OPS
    assert msg["Subject"] == "[Test] New in Reliafy this month"
    # The test copy's unsubscribe link is the inert token.
    assert "unsubscribe?t=test" in msg.get_body(("plain",)).get_content()
    assert db.update_sends.count_documents({}) == 0
    # Again that afternoon, and over the weekend: nothing more.
    assert _run(db, bne(2026, 10, 30, 15))["actions"][0]["result"] == "already sent"
    assert _run(db, bne(2026, 11, 1, 11))["actions"][0]["result"] == "already sent"
    assert len(outbox) == 1 and pushes == []


def test_a_missed_friday_is_caught_up_before_the_date(db, outbox):
    _run(db, bne(2026, 10, 31, 10, 5))  # Saturday
    assert [m["To"] for m in outbox] == [OPS]


def test_sends_to_the_list_on_its_date_at_ten(db, outbox, pushes):
    assert _run(db, bne(2026, 11, 2, 9, 59))["actions"] == []
    out = _run(db, bne(2026, 11, 2, 10, 5))
    (action,) = out["actions"]
    assert action["step"] == "send" and action["result"] == "sent"
    assert action["sent"] == 2 and action["failed"] == 0
    assert action["excluded"] == {"opted out": 1, "test domain": 1,
                                  "excluded (UPDATE_EMAIL_EXCLUDE)": 1}
    assert sorted(m["To"] for m in outbox) == ["alice@one.example.org", "bob@two.example.org"]
    # Opt-outs, test domains and the configured exclusions got nothing.
    assert all(m["To"] not in ("carol@three.example.org", "dev@example.com", "Skip.Me@four.example.org")
               for m in outbox)
    rows = {r["uid"]: r["status"] for r in db.update_sends.find({"update_slug": "november-2026"})}
    assert rows == {"u1": "sent", "u2": "sent"}
    # The manual update (no `send: auto`) was never touched.
    assert db.update_sends.count_documents({"update_slug": "manual-one"}) == 0
    assert db.content_jobs.find_one({"_id": "update-send:november-2026"})["status"] == "done"
    (push,) = pushes
    assert push[0] == "What's new sent: november-2026" and push[1].startswith("2 sent, 0 failed")


def test_rerun_is_idempotent_and_later_signups_dont_get_it(db, outbox, pushes):
    _run(db, bne(2026, 11, 2, 10, 5))
    outbox.clear()
    db.users.insert_one({"_id": "u9", "email": "late@nine.example.org"})
    out = _run(db, bne(2026, 11, 2, 11, 5))
    assert out["actions"][0]["result"] == "already sent"
    assert outbox == [] and len(pushes) == 1


def test_a_failed_send_is_retried_next_run_without_resending(db, outbox, pushes, monkeypatch):
    from backend.services import email

    sent = []

    def flaky(msg, **kw):
        if msg["To"] == "bob@two.example.org" and not sent:
            sent.append("boom")
            raise OSError("421 try later")
        outbox.append(msg)

    monkeypatch.setattr(email, "_deliver", flaky)
    first = _run(db, bne(2026, 11, 2, 10, 5))["actions"][0]
    assert first["result"] == "partial" and first["sent"] == 1 and first["failed"] == 1
    assert pushes[-1][1].endswith("not finished, the next run continues.")
    second = _run(db, bne(2026, 11, 2, 11, 5))["actions"][0]
    assert second["result"] == "sent" and second["sent"] == 1
    assert sorted(m["To"] for m in outbox) == ["alice@one.example.org", "bob@two.example.org"]


def test_a_run_out_of_time_stops_and_the_next_continues(db, outbox, monkeypatch):
    from backend import config

    monkeypatch.setattr(config, "UPDATE_AUTO_SECONDS", 10)
    ticks = iter([0, 0, 11, 11, 11])  # deadline set at 0; out of time before the 2nd email
    first = _run(db, bne(2026, 11, 2, 10, 5), clock=lambda: next(ticks))["actions"][0]
    assert first["result"] == "partial" and first["sent"] == 1
    second = _run(db, bne(2026, 11, 2, 11, 5))["actions"][0]
    assert second["result"] == "sent" and second["sent"] == 1
    assert len(outbox) == 2


def test_overlapping_runs_cannot_both_send(db, outbox):
    now = bne(2026, 11, 2, 10, 5)
    db.content_jobs.insert_one({"_id": "update-send:november-2026", "status": "running",
                                "lease_until": now + timedelta(minutes=20)})
    assert _run(db, now)["actions"][0]["result"] == "another run has it"
    assert outbox == []
    # A lease that lapsed (a run that died) is taken over.
    assert _run(db, now + timedelta(minutes=31))["actions"][0]["result"] == "sent"


def test_not_sent_after_its_window(db, outbox):
    assert _run(db, bne(2026, 11, 6, 10, 5))["actions"] == []
    assert outbox == []


def test_auto_send_off_sends_nothing(db, outbox, monkeypatch):
    from backend import config

    monkeypatch.setattr(config, "UPDATE_AUTO_SEND", False)
    out = _run(db, bne(2026, 11, 2, 10, 5))
    assert out["auto_send"] is False and out["actions"] == []
    assert outbox == []


def test_dry_run_reports_and_records_nothing(db, outbox):
    test = _run(db, bne(2026, 10, 30, 10, 5), dry_run=True)["actions"][0]
    assert test == {"step": "test copy", "slug": "november-2026", "date": "2026-11-02",
                    "result": "would send", "to": 1}
    send = _run(db, bne(2026, 11, 2, 10, 5), dry_run=True)["actions"][0]
    assert send["result"] == "would send" and send["eligible"] == 2
    assert outbox == []
    assert db.content_jobs.count_documents({"_id": {"$ne": "report:2026-10"}}) == 0
    assert db.update_sends.count_documents({}) == 0


def test_refuses_when_email_isnt_configured(db, monkeypatch):
    from backend import config

    monkeypatch.setattr(config, "SMTP_HOST", None)
    with pytest.raises(content_jobs.EmailNotConfigured):
        _run(db, bne(2026, 11, 2, 10, 5))
    # A dry run still answers.
    assert _run(db, bne(2026, 11, 2, 10, 5), dry_run=True)["ok"] is True
    assert db.update_sends.count_documents({}) == 0


def test_updates_come_from_the_build_when_present(tmp_path):
    (tmp_path / "content.json").write_text(json.dumps({"pages": {}, "updates": [
        {"slug": "november-2026", "title": "Nov", "date": "2026-11-02", "summary": "S",
         "email_subject": "", "send": "auto", "body": "Hello"}]}))
    (u,) = content_jobs.load_updates(tmp_path)
    assert (u.slug, u.subject, u.send, u.body) == ("november-2026", "Nov", "auto", "Hello")
    # No build file: the source files in the checkout.
    assert all(x.slug for x in content_jobs.load_updates(tmp_path / "nowhere"))


# ---- The endpoint --------------------------------------------------------------

@pytest.fixture()
def client(db, monkeypatch):
    from backend.main import app

    return TestClient(app)


def test_endpoint_refuses_without_the_schedulers_token(client, monkeypatch):
    from backend import config

    monkeypatch.setattr(config, "CONTENT_CRON_AUDIENCE", "https://x.run.app/internal/content/run")
    monkeypatch.setattr(config, "CONTENT_CRON_SA", "cron@p.iam.gserviceaccount.com")
    assert client.post("/internal/content/run").status_code == 401
    assert client.post("/internal/content/run", headers={"Authorization": "Bearer junk"}).status_code == 401


def test_endpoint_runs_and_refuses_without_email(client, monkeypatch, outbox):
    from backend import config
    from backend.services import oidc

    monkeypatch.setattr(oidc, "verify", lambda *a, **k: {"email": "cron"})
    monkeypatch.setattr(content_jobs, "load_updates", lambda *a, **k: UPDATES)
    r = client.post("/internal/content/run?dry_run=true")
    assert r.status_code == 200 and r.json()["dry_run"] is True
    monkeypatch.setattr(config, "SMTP_HOST", None)
    r = client.post("/internal/content/run")
    assert r.status_code == 503 and r.json()["ok"] is False
