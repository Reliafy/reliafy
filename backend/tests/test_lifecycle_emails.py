"""Lifecycle emails (#272) and the email-campaign report (#269).

Delivery is always faked: ``email._deliver`` is replaced, so nothing here
talks to SMTP.
"""

from datetime import datetime, timedelta, timezone

import mongomock
import pytest

CRON_URL = "https://reliafy-abc.a.run.app/internal/lifecycle/day3"
CRON_SA = "lifecycle-cron@reliafy-test.iam.gserviceaccount.com"
UTM_WELCOME = "utm_source=email&utm_medium=lifecycle&utm_campaign=welcome"
UTM_DAY3 = "utm_source=email&utm_medium=lifecycle&utm_campaign=day3"

NEW = {"uid": "u-new", "email": "Sam.Ng@mail.example.org", "name": "Sam Ng",
       "email_verified": True}


def _now():
    return datetime.now(timezone.utc)


@pytest.fixture()
def test_db(monkeypatch):
    from backend import config, db

    d = mongomock.MongoClient()["reliafy_test"]
    monkeypatch.setattr(db, "_db", d)
    monkeypatch.setattr(db, "_simulated", True)
    monkeypatch.setattr(config, "PUBLIC_BASE_URL", None)
    return d


@pytest.fixture()
def outbox(monkeypatch):
    from backend import config
    from backend.services import email

    monkeypatch.setattr(config, "SMTP_HOST", "smtp.invalid")
    monkeypatch.setattr(config, "EMAIL_FROM", "Reliafy <hello@reliafy.test>")
    sent = []
    monkeypatch.setattr(email, "_deliver", lambda msg, **kw: sent.append(msg))
    return sent


@pytest.fixture()
def on(monkeypatch, outbox):
    """Lifecycle emails switched on, the welcome sent inline (no thread)."""
    from backend import config
    from backend.services import lifecycle_emails

    monkeypatch.setattr(config, "LIFECYCLE_EMAILS", True)
    monkeypatch.setattr(lifecycle_emails, "_spawn", lambda fn, *args: fn(*args))
    return outbox


@pytest.fixture()
def cron(monkeypatch):
    """The day-3 endpoint configured, with a fake Google token verifier."""
    from backend import config
    from backend.services import oidc

    monkeypatch.setattr(config, "LIFECYCLE_CRON_AUDIENCE", CRON_URL)
    monkeypatch.setattr(config, "LIFECYCLE_CRON_SA", CRON_SA)

    def fake_verify(token, audience):
        assert audience == CRON_URL
        if token == "scheduler-token":
            return {"email": CRON_SA, "email_verified": True, "aud": audience}
        if token == "other-token":
            return {"email": "someone@else.iam.gserviceaccount.com", "email_verified": True}
        raise ValueError("bad signature")

    monkeypatch.setattr(oidc, "_verify_token", fake_verify)


@pytest.fixture()
def as_user(test_db, monkeypatch):
    """A TestClient whose signed-in user is whatever ``who`` holds."""
    from fastapi.testclient import TestClient

    from backend import config
    from backend.auth import get_current_user
    from backend.main import app

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    who = dict(NEW)
    app.dependency_overrides[get_current_user] = lambda: dict(who)
    try:
        yield TestClient(app), who
    finally:
        app.dependency_overrides.clear()


def _text(msg):
    return msg.get_body(("plain",)).get_content()


def _html(msg):
    return msg.get_body(("html",)).get_content()


# ---- Off by default ----------------------------------------------------------

def test_off_by_default(as_user, outbox, cron):
    from backend import config

    assert config._truthy(None) is False  # LIFECYCLE_EMAILS unset -> off
    client, _ = as_user
    assert client.get("/api/me").status_code == 200
    r = client.post("/internal/lifecycle/day3", headers={"Authorization": "Bearer scheduler-token"})
    assert r.status_code == 200 and r.json()["enabled"] is False
    assert outbox == []


# ---- Welcome -----------------------------------------------------------------

def test_welcome_on_first_verified_sign_in_once(as_user, on, test_db):
    from backend.services import email_prefs

    client, _ = as_user
    assert client.get("/api/me").status_code == 200
    (msg,) = on
    assert msg["To"] == NEW["email"]
    assert msg["Subject"] == "Welcome to Reliafy"
    assert msg["From"] == "Derryn at Reliafy <hello@reliafy.test>"
    assert msg["Reply-To"] == "hello@reliafy.com"
    token = email_prefs.token_for(test_db, NEW["uid"])
    assert msg["List-Unsubscribe"].startswith(f"<https://reliafy.com/api/email/unsubscribe?t={token}>")
    assert msg["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    text = _text(msg)
    assert text.startswith("Hi Sam,\n")
    assert f"/modelling/m/sample-model-bearings-weibull?{UTM_WELCOME}" in text
    assert f"/modelling/new?mode=paste&{UTM_WELCOME}" in text
    assert f"/rbds/b/sample-rbd-pump-station?{UTM_WELCOME}" in text
    assert f"/api-docs?{UTM_WELCOME}#mcp" in text
    assert "It comes to me." in text
    assert f"Unsubscribe: https://reliafy.com/unsubscribe?t={token}\n" in text
    assert f'href="https://reliafy.com/unsubscribe?t={token}"' in _html(msg)
    row = test_db.lifecycle_emails.find_one({"_id": f"welcome:{NEW['uid']}"})
    assert row["status"] == "sent" and row["attempts"] == 1

    # Every later sign-in: nothing more.
    for _ in range(3):
        client.get("/api/me")
    assert len(on) == 1


def test_welcome_waits_for_a_verified_address(as_user, on, test_db):
    client, who = as_user
    who["email_verified"] = False
    client.get("/api/me")
    assert on == [] and test_db.lifecycle_emails.count_documents({}) == 0
    who["email_verified"] = True  # followed Firebase's verification link
    client.get("/api/me")
    assert [m["Subject"] for m in on] == ["Welcome to Reliafy"]


def test_no_welcome_for_existing_accounts(as_user, on, test_db):
    test_db.users.insert_one({"_id": NEW["uid"], "email": NEW["email"],
                              "created_at": _now() - timedelta(days=30)})
    client, _ = as_user
    client.get("/api/me")
    assert on == []


@pytest.mark.parametrize("email, extra", [
    ("pat@example.com", {}),                               # test domain
    ("pat@qa.reliafy.test", {}),                           # test domain
    ("Sam.Ng@mail.example.org", {"email_updates_opt_out": True}),  # opted out
])
def test_no_welcome_for_test_domains_or_opted_out(as_user, on, test_db, email, extra):
    test_db.users.insert_one({"_id": NEW["uid"], "email": email, "created_at": _now(), **extra})
    client, who = as_user
    who["email"] = email
    client.get("/api/me")
    assert on == []


def test_welcome_failure_never_breaks_sign_in(as_user, on, monkeypatch):
    from backend.services import email

    def boom(msg, **kw):
        raise OSError("smtp down")

    monkeypatch.setattr(email, "_deliver", boom)
    client, _ = as_user
    assert client.get("/api/me").status_code == 200


def test_welcome_name_is_escaped_in_html(test_db, outbox):
    from backend.services import lifecycle_emails

    r = lifecycle_emails.render("welcome", name="<script>x</script>", token="a" * 32)
    assert "<script>x" not in r.html and "&lt;script&gt;x" in r.html


# ---- Send log ----------------------------------------------------------------

def test_claim_is_once_and_failed_sends_retry_a_bounded_number_of_times(test_db):
    from backend.services import lifecycle_emails as L

    L.ensure_indexes(test_db)
    assert L.claim(test_db, "day3", "u1", "a@x.org") is True
    assert L.claim(test_db, "day3", "u1", "a@x.org") is False  # in flight
    for attempt in range(2, L.MAX_ATTEMPTS + 1):
        L._finish(test_db, "day3", "u1", "failed", error="boom")
        assert L.handled(test_db, "day3", "u1") is False
        assert L.claim(test_db, "day3", "u1", "a@x.org") is True
    L._finish(test_db, "day3", "u1", "failed", error="boom")
    assert L.handled(test_db, "day3", "u1") is True
    assert L.claim(test_db, "day3", "u1", "a@x.org") is False
    assert test_db.lifecycle_emails.find_one({"_id": "day3:u1"})["attempts"] == L.MAX_ATTEMPTS
    # Kinds are independent.
    assert L.claim(test_db, "welcome", "u1", "a@x.org") is True


# ---- Day 3 -------------------------------------------------------------------

def _seed_day3(d):
    now = _now()
    d.users.insert_many([
        # Due, nothing saved -> "start".
        {"_id": "d1", "email": "alice@one.example.org", "name": "Alice Smith",
         "email_verified": True, "created_at": now - timedelta(days=3, hours=2)},
        # Due, has a saved diagram -> "further".
        {"_id": "d2", "email": "bob@two.example.org", "name": "Bob",
         "email_verified": True, "created_at": now - timedelta(days=5)},
        # Too new, too old.
        {"_id": "d3", "email": "carol@three.example.org", "email_verified": True,
         "created_at": now - timedelta(days=2)},
        {"_id": "d4", "email": "dan@four.example.org", "email_verified": True,
         "created_at": now - timedelta(days=9)},
        # Due but unverified, opted out, a test domain, already sent.
        {"_id": "d5", "email": "erin@five.example.org", "email_verified": False,
         "created_at": now - timedelta(days=4)},
        {"_id": "d6", "email": "fay@six.example.org", "email_verified": True,
         "email_updates_opt_out": True, "created_at": now - timedelta(days=4)},
        {"_id": "d7", "email": "gus@example.com", "email_verified": True,
         "created_at": now - timedelta(days=4)},
        {"_id": "d8", "email": "hal@eight.example.org", "email_verified": True,
         "created_at": now - timedelta(days=4)},
    ])
    d.rbds.insert_one({"_id": "r1", "owner_id": "d2", "name": "Bob's secret conveyor"})
    d.lifecycle_emails.insert_one({"_id": "day3:d8", "kind": "day3", "uid": "d8",
                                   "status": "sent", "attempts": 1})


def _trigger(client, token="scheduler-token"):
    return client.post("/internal/lifecycle/day3", headers={"Authorization": f"Bearer {token}"})


def test_day3_endpoint_requires_the_scheduler_token(as_user, on, cron, test_db):
    from backend import config

    _seed_day3(test_db)
    client, _ = as_user
    assert client.post("/internal/lifecycle/day3").status_code == 401
    assert _trigger(client, "garbage").status_code == 401
    assert _trigger(client, "other-token").status_code == 401
    assert client.post("/internal/lifecycle/day3",
                       headers={"Authorization": "Basic scheduler-token"}).status_code == 401
    config.LIFECYCLE_CRON_SA = None  # unconfigured: refuses everything
    assert _trigger(client).status_code == 401
    assert on == []


def test_day3_sends_to_the_right_people_once(as_user, on, cron, test_db):
    _seed_day3(test_db)
    client, _ = as_user
    r = _trigger(client)
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is True and body["sent"] == 2 and body["failed"] == 0
    assert sorted(m["To"] for m in on) == ["alice@one.example.org", "bob@two.example.org"]
    rows = {r["uid"]: r for r in test_db.lifecycle_emails.find({"kind": "day3"})}
    assert rows["d1"]["variant"] == "start" and rows["d2"]["variant"] == "further"
    assert rows["d1"]["status"] == rows["d2"]["status"] == "sent"

    on.clear()
    assert _trigger(client).json()["sent"] == 0
    assert on == []


def test_day3_never_mentions_what_the_user_did(as_user, on, cron, test_db):
    from backend.services import lifecycle_emails as L

    _seed_day3(test_db)
    client, _ = as_user
    _trigger(client)
    by_to = {m["To"]: m for m in on}
    alice, bob = _text(by_to["alice@one.example.org"]), _text(by_to["bob@two.example.org"])
    assert "conveyor" not in bob and "conveyor" not in _html(by_to["bob@two.example.org"])
    for text in (alice, bob):
        assert "you saved" not in text.lower() and "you haven't" not in text.lower()
        assert f"/guides/build-an-rbd?{UTM_DAY3}" in text
        assert "Fault tree" in text and "What to improve" in text and "Download as Python" in text
    assert f"/rbds/b/sample-rbd-instrument-air-availability?{UTM_DAY3}" in alice
    # The body is one of two fixed texts: only the greeting and the
    # unsubscribe token differ between recipients.
    for variant in ("start", "further"):
        a = L.render("day3", name="Alice", token="a" * 32, variant=variant).text
        b = L.render("day3", name="Zed", token="b" * 32, variant=variant).text
        strip = lambda t: t.split("\n", 1)[1].rsplit("Unsubscribe:", 1)[0]  # noqa: E731
        assert strip(a) == strip(b)
    assert by_to["alice@one.example.org"]["Subject"] == L.DAY3_SUBJECT


def test_day3_respects_an_unsubscribe_from_the_welcome(as_user, on, cron, test_db):
    _seed_day3(test_db)
    client, _ = as_user
    from backend.services import email_prefs

    token = email_prefs.token_for(test_db, "d1")
    r = client.post(f"/api/email/unsubscribe?t={token}",
                    content=b"List-Unsubscribe=One-Click",
                    headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert r.status_code == 200
    _trigger(client)
    assert [m["To"] for m in on] == ["bob@two.example.org"]


def test_day3_failed_send_is_retried_next_run(as_user, on, cron, test_db, monkeypatch):
    from backend.services import email

    _seed_day3(test_db)
    client, _ = as_user

    def flaky(msg, **kw):
        if msg["To"] == "bob@two.example.org":
            raise OSError("mailbox unavailable")
        on.append(msg)

    monkeypatch.setattr(email, "_deliver", flaky)
    assert _trigger(client).json()["failed"] == 1
    row = test_db.lifecycle_emails.find_one({"_id": "day3:d2"})
    assert row["status"] == "failed" and "mailbox unavailable" in row["error"]

    monkeypatch.setattr(email, "_deliver", lambda msg, **kw: on.append(msg))
    on.clear()
    assert _trigger(client).json()["sent"] == 1
    assert [m["To"] for m in on] == ["bob@two.example.org"]


def test_day3_without_smtp_sends_nothing(as_user, cron, test_db, monkeypatch):
    from backend import config

    monkeypatch.setattr(config, "LIFECYCLE_EMAILS", True)
    monkeypatch.setattr(config, "SMTP_HOST", None)
    _seed_day3(test_db)
    client, _ = as_user
    assert _trigger(client).json()["enabled"] is False
    assert test_db.lifecycle_emails.count_documents({}) == 1  # the seeded row


# ---- Email-campaign report (#269) --------------------------------------------

def test_email_campaign_report(as_user, test_db, monkeypatch):
    from backend import config

    client, who = as_user
    assert client.get("/api/admin/email-campaigns").status_code == 403

    monkeypatch.setattr(config, "ADMIN_EMAILS", {NEW["email"].lower()})
    now = _now()
    sent = now - timedelta(days=2)
    test_db.update_sends.insert_many([
        {"_id": "nov:a", "update_slug": "nov", "uid": "a", "status": "sent", "sent_at": sent},
        {"_id": "nov:b", "update_slug": "nov", "uid": "b", "status": "sent", "sent_at": sent},
        {"_id": "nov:c", "update_slug": "nov", "uid": "c", "status": "failed", "sent_at": sent},
    ])
    test_db.lifecycle_emails.insert_one({"_id": "welcome:a", "kind": "welcome", "uid": "a",
                                         "status": "sent", "sent_at": sent})
    test_db.users.insert_many([
        {"_id": "a", "last_login": sent - timedelta(days=1)},
        {"_id": "b", "last_login": sent + timedelta(hours=5)},  # came back
    ])
    test_db.usage_events.insert_many([
        {"uid": "a", "ts": sent + timedelta(days=4), "channel": "app"},  # too late
    ])
    ev = lambda **kw: {"name": "pageview", "path": "/whats-new/nov", "utm_source": "email",  # noqa: E731
                       "utm_medium": "update", "utm_campaign": "nov", "visitor": "v1",
                       "day": "2026-11-01", "created_at": now, **kw}
    test_db.metrics_events.insert_many([
        ev(), ev(path="/rbds/b"), ev(visitor="v2"),
        ev(name="activated", path="/modelling"),
        ev(utm_medium="social", utm_campaign="launch"),       # not an email
        ev(utm_source="linkedin"),                            # not an email
    ])

    data = client.get("/api/admin/email-campaigns").json()
    rows = {(r["medium"], r["campaign"]): r for r in data["campaigns"]}
    assert set(rows) == {("update", "nov"), ("lifecycle", "welcome")}
    nov = rows[("update", "nov")]
    assert nov["sent"] == 2 and nov["pageviews"] == 3 and nov["visitors"] == 2
    assert nov["top_pages"][0] == {"key": "/whats-new/nov", "count": 2}
    assert nov["events"] == [{"key": "activated", "count": 1}]
    assert nov["active"] == 1
    assert rows[("lifecycle", "welcome")]["active"] is None
    assert data["active_days"] == 3
