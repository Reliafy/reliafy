"""Product-update emails: opt-out preference, unsubscribe routes, and the
sender CLI. Delivery is always faked — nothing here talks to SMTP."""

import pathlib
import re

import mongomock
import pytest

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "updates"
SLUG = "test-update"

ME = {"uid": "u-me", "email": "Pat.Lee@mail.example.org", "name": "Pat Lee"}


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
    """Configure a fake SMTP server and capture every message 'delivered'."""
    from backend import config
    from backend.services import email

    monkeypatch.setattr(config, "SMTP_HOST", "smtp.invalid")
    monkeypatch.setattr(config, "EMAIL_FROM", "Reliafy <updates@reliafy.test>")
    sent = []
    monkeypatch.setattr(email, "_deliver", lambda msg, **kw: sent.append(msg))
    return sent


@pytest.fixture()
def client(test_db, monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config
    from backend.auth import get_current_user
    from backend.main import app

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    test_db.users.insert_one({"_id": ME["uid"], "email": ME["email"],
                              "email_lc": ME["email"].lower(), "name": ME["name"]})
    app.dependency_overrides[get_current_user] = lambda: ME
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


# ---- Service ---------------------------------------------------------------

def test_token_created_once_and_reused(test_db):
    from backend.services import email_prefs

    test_db.users.insert_one({"_id": "u1", "email": "a@x.org"})
    t1 = email_prefs.token_for(test_db, "u1")
    t2 = email_prefs.token_for(test_db, "u1")
    assert t1 == t2 and re.fullmatch(r"[0-9a-f]{32}", t1)
    assert email_prefs.user_by_token(test_db, t1)["_id"] == "u1"
    assert email_prefs.user_by_token(test_db, "test") is None
    assert email_prefs.user_by_token(test_db, "0" * 32) is None


def test_mask_email():
    from backend.services.email_prefs import mask_email

    assert mask_email("derryn@gmail.com") == "d****n@gmail.com"
    assert mask_email("ab@x.org") == "a****@x.org"
    assert mask_email("") == ""


# ---- Public unsubscribe routes --------------------------------------------

def _token(test_db, uid=ME["uid"]):
    from backend.services import email_prefs

    return email_prefs.token_for(test_db, uid)


def test_get_does_not_change_state(client, test_db):
    t = _token(test_db)
    r = client.get(f"/api/email/unsubscribe?t={t}")
    assert r.status_code == 200
    assert r.json() == {"email": "P****e@mail.example.org", "subscribed": True}
    assert "email_updates_opt_out" not in test_db.users.find_one({"_id": ME["uid"]})


def test_one_click_post_opts_out_idempotently(client, test_db):
    t = _token(test_db)
    for _ in range(2):
        r = client.post(f"/api/email/unsubscribe?t={t}",
                        content="List-Unsubscribe=One-Click",
                        headers={"Content-Type": "application/x-www-form-urlencoded"})
        assert r.status_code == 200
        assert r.json() == {"email": "P****e@mail.example.org", "subscribed": False}
    doc = test_db.users.find_one({"_id": ME["uid"]})
    assert doc["email_updates_opt_out"] is True
    assert doc["email_updates_source"] == "one_click"
    assert client.get(f"/api/email/unsubscribe?t={t}").json()["subscribed"] is False


def test_post_accepts_json_and_empty_body_then_resubscribe(client, test_db):
    t = _token(test_db)
    assert client.post(f"/api/email/unsubscribe?t={t}", json={}).json()["subscribed"] is False
    assert client.post(f"/api/email/resubscribe?t={t}").json() == {
        "email": "P****e@mail.example.org", "subscribed": True}
    assert client.post(f"/api/email/unsubscribe?t={t}").json()["subscribed"] is False


def test_unknown_token_404(client):
    for t in ("test", "0" * 32, "", "zz"):
        assert client.get(f"/api/email/unsubscribe?t={t}").status_code == 404
        r = client.post(f"/api/email/unsubscribe?t={t}")
        assert r.status_code == 404 and "detail" in r.json()
        assert client.post(f"/api/email/resubscribe?t={t}").status_code == 404


def test_me_email_preferences(client, test_db):
    assert client.get("/api/me/email-preferences").json() == {"updates": True}
    assert client.put("/api/me/email-preferences", json={"updates": False}).json() == {"updates": False}
    assert test_db.users.find_one({"_id": ME["uid"]})["email_updates_opt_out"] is True
    assert client.get("/api/me/email-preferences").json() == {"updates": False}
    assert client.put("/api/me/email-preferences", json={"updates": True}).json() == {"updates": True}
    assert client.put("/api/me/email-preferences", json={}).status_code == 422


# ---- Sender CLI -------------------------------------------------------------

def _seed_users(d):
    d.users.insert_many([
        {"_id": "u1", "email": "alice@one.example.org", "name": "Alice Smith"},
        {"_id": "u2", "email": "bob@two.example.org", "name": "bob@two.example.org"},
        {"_id": "u3", "email": "carol@three.example.org", "name": "Carol",
         "email_updates_opt_out": True},                       # opted out
        {"_id": "u4", "email": "dev@example.com", "name": "Dev"},  # test domain
        {"_id": "u5", "email": "dev@local", "name": "Dev"},        # no dot in domain
        {"_id": "u6", "email": "Skip.Me@four.example.org"},         # --exclude
        {"_id": "u7", "email": "erin@five.example.org", "name": "Erin"},  # already sent
        {"_id": "u8", "email": None},
    ])
    d.update_sends.insert_one({"_id": f"{SLUG}:u7", "update_slug": SLUG, "uid": "u7",
                               "email": "erin@five.example.org", "status": "sent"})


def _run(*args, **kw):
    from backend.scripts import send_update

    return send_update.main(["--update", SLUG, "--delay", "0", *args],
                            updates_dir=FIXTURES, sleep=lambda s: None, **kw)


def test_dry_run_sends_and_writes_nothing(test_db, outbox, capsys):
    _seed_users(test_db)
    before = list(test_db.users.find())
    assert _run("--exclude", "skip.me@FOUR.example.org") == 0
    out = capsys.readouterr().out
    assert "Eligible: 2" in out
    assert "opted out: 1" in out and "test domain: 1" in out
    assert "already sent: 1" in out and "--exclude: 1" in out
    assert outbox == []
    assert test_db.update_sends.count_documents({}) == 1
    assert list(test_db.users.find()) == before
    sample_dir = re.search(r"Sample written to (\S+)/ ", out).group(1)
    html = (pathlib.Path(sample_dir) / "sample.html").read_text()
    assert re.search(r"<h2[^>]*>Faster fits</h2>", html) and "Hi Alice," in html


def test_send_only_to_eligible_and_rerun_sends_nothing(test_db, outbox, capsys):
    _seed_users(test_db)
    assert _run("--send", "--yes", "--exclude", "SKIP.ME@four.example.org") == 0
    assert sorted(m["To"] for m in outbox) == ["alice@one.example.org", "bob@two.example.org"]
    rows = {r["uid"]: r for r in test_db.update_sends.find()}
    assert rows["u1"]["status"] == rows["u2"]["status"] == "sent"
    assert set(rows) == {"u1", "u2", "u7"}
    assert "Done: 2 sent, 0 failed" in capsys.readouterr().out

    outbox.clear()
    assert _run("--send", "--yes", "--exclude", "skip.me@four.example.org") == 0
    assert outbox == []


def test_message_contents(test_db, outbox):
    from backend.services import email_prefs

    _seed_users(test_db)
    assert _run("--send", "--yes", "--limit", "1") == 0
    (msg,) = outbox
    assert msg["To"] == "alice@one.example.org"
    assert msg["Subject"] == "What's new in Reliafy: January"
    assert msg["Reply-To"] == "hello@reliafy.com"
    token = email_prefs.token_for(test_db, "u1")
    assert msg["List-Unsubscribe"] == (
        f"<https://reliafy.com/api/email/unsubscribe?t={token}>, "
        "<mailto:hello@reliafy.com?subject=unsubscribe>")
    assert msg["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    assert msg.get_content_type() == "multipart/alternative"
    text = msg.get_body(("plain",)).get_content()
    html = msg.get_body(("html",)).get_content()
    web = "https://reliafy.com/whats-new/test-update"
    assert text.startswith("Hi Alice,")
    assert f"Read it on the web: {web}" in text
    assert f"Unsubscribe: https://reliafy.com/unsubscribe?t={token}" in text
    assert "reference page (https://reliafy.com/reference/weibull)" in text
    assert "**" not in text and "## " not in text
    assert web in html and 'href="https://reliafy.com/reference/weibull"' in html
    # Name fell back to the email address -> no name in the greeting.
    outbox.clear()
    assert _run("--send", "--yes") == 0
    bob = next(m for m in outbox if m["To"] == "bob@two.example.org")
    assert bob.get_body(("plain",)).get_content().startswith("Hi,\n")


def test_failed_send_recorded_and_retried(test_db, outbox, monkeypatch, capsys):
    from backend.services import email

    _seed_users(test_db)

    def boom(msg, **kw):
        if msg["To"] == "bob@two.example.org":
            raise OSError("mailbox unavailable")
        outbox.append(msg)

    monkeypatch.setattr(email, "_deliver", boom)
    assert _run("--send", "--yes") == 1
    assert test_db.update_sends.find_one({"uid": "u2"})["status"] == "failed"
    assert "mailbox unavailable" in test_db.update_sends.find_one({"uid": "u2"})["error"]

    monkeypatch.setattr(email, "_deliver", lambda msg, **kw: outbox.append(msg))
    outbox.clear()
    assert _run("--send", "--yes") == 0
    assert [m["To"] for m in outbox] == ["bob@two.example.org"]
    assert test_db.update_sends.find_one({"uid": "u2"})["status"] == "sent"


def test_send_requires_typed_confirmation(test_db, outbox):
    _seed_users(test_db)
    assert _run("--send", input_fn=lambda prompt: "nope") == 1
    assert outbox == [] and test_db.update_sends.count_documents({}) == 1
    assert _run("--send", input_fn=lambda prompt: SLUG) == 0
    assert len(outbox) == 3  # no --exclude this time


def test_test_to_sends_one_inert_copy(test_db, outbox):
    _seed_users(test_db)
    assert _run("--test-to", "me@six.example.org") == 0
    (msg,) = outbox
    assert msg["To"] == "me@six.example.org"
    assert "?t=test>" in msg["List-Unsubscribe"]
    assert test_db.update_sends.count_documents({}) == 1  # only the seeded row


def test_refuses_without_smtp(test_db, monkeypatch):
    from backend import config

    monkeypatch.setattr(config, "SMTP_HOST", None)
    assert _run("--send", "--yes") == 2
    assert _run("--test-to", "me@six.example.org") == 2


def test_plain_send_is_backward_compatible(outbox, monkeypatch):
    import threading

    from backend.services import email

    class Now:
        def __init__(self, target, args, daemon):
            self.target, self.args = target, args

        def start(self):
            self.target(*self.args)

    monkeypatch.setattr(threading, "Thread", Now)
    email.send("a@x.org", "Hi", "plain body")
    email.send("b@x.org", "Hi", "text", html="<p>html</p>", reply_to="r@x.org",
               headers={"X-Test": "1"})
    plain, rich = outbox
    assert plain.get_content_type() == "text/plain" and plain["Reply-To"] is None
    assert rich.get_content_type() == "multipart/alternative"
    assert rich["Reply-To"] == "r@x.org" and rich["X-Test"] == "1"
