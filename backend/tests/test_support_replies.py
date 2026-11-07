"""Operator support replies (backend/routers/support.py): headers that thread
the reply, operator-only access, the unconfigured and over-the-limit refusals,
and the log."""

from datetime import datetime, timedelta, timezone

import mongomock
import pytest
from fastapi.testclient import TestClient

OP, PRO, FREE = "user-op", "user-pro", "user-free"
USERS = {
    OP: {"_id": OP, "email": "op@example.org", "name": "Op", "email_verified": True},
    PRO: {"_id": PRO, "email": "pro@example.org", "name": "Pro", "plan": "pro", "email_verified": True},
    FREE: {"_id": FREE, "email": "free@example.org", "name": "Free", "email_verified": True},
}
REPLY = {
    "to": "Customer <customer@example.com>",
    "subject": "Re: Weibull fit question",
    "text": "Hi,\n\nThanks for writing. Here is how to read the bounds...\n\nReliafy support",
    "in_reply_to": "<CAB123@mail.example.com>",
    "references": ["<root456@mail.example.com>"],
}
URL = "/api/v1/support/replies"


class FakeSMTP:
    sent: list = []
    fail = False

    def __init__(self, host, port, timeout=None):
        self.host = host

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self):
        pass

    def login(self, user, password):
        pass

    def send_message(self, msg):
        if FakeSMTP.fail:
            raise OSError("smtp down")
        FakeSMTP.sent.append(msg)


@pytest.fixture()
def env(monkeypatch):
    from backend import config, db
    from backend.services import email as email_service
    from backend.services import tokens

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", True)
    monkeypatch.setattr(config, "ADMIN_EMAILS", {"op@example.org"})
    monkeypatch.setattr(config, "SMTP_HOST", "smtp.example.test")
    monkeypatch.setattr(config, "EMAIL_FROM", "Reliafy <no-reply@example.test>")
    monkeypatch.setattr(config, "SUPPORT_FROM", "hello@reliafy.com")
    monkeypatch.setattr(config, "SUPPORT_FROM_NAME", "Reliafy support")
    monkeypatch.setattr(config, "SUPPORT_COPY_TO", "hello@reliafy.com")
    monkeypatch.setattr(config, "SUPPORT_REPLIES_PER_HOUR", 20)
    monkeypatch.setattr(email_service.smtplib, "SMTP", FakeSMTP)
    FakeSMTP.sent, FakeSMTP.fail = [], False
    test_db = mongomock.MongoClient()["reliafy_support"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    for u in USERS.values():
        test_db.users.insert_one(dict(u))

    class Env:
        db = test_db
        token = {uid: tokens.create_token(test_db, uid, "api")["token"] for uid in USERS}
        read_only = tokens.create_token(test_db, OP, "ro", ["read"])["token"]
        client = TestClient(__import__("backend.main", fromlist=["app"]).app)

        @classmethod
        def post(cls, body, uid=OP, token=None):
            return cls.client.post(URL, json=body, headers=_auth(token or cls.token[uid]))

        @classmethod
        def get(cls, uid=OP, token=None):
            return cls.client.get(URL, headers=_auth(token or cls.token[uid]))

    return Env


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_a_reply_threads_and_copies_the_inbox(env):
    r = env.post(REPLY)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["status"] == "sent" and out["to"] == "customer@example.com"
    [msg] = FakeSMTP.sent
    assert msg["From"] == "Reliafy support <hello@reliafy.com>"
    assert msg["To"] == "customer@example.com"
    assert msg["Reply-To"] == "hello@reliafy.com"
    assert msg["Subject"] == "Re: Weibull fit question"
    assert msg["In-Reply-To"] == "<CAB123@mail.example.com>"
    # The thread's root first, the message answered last.
    assert msg["References"] == "<root456@mail.example.com> <CAB123@mail.example.com>"
    assert msg["Bcc"] == "hello@reliafy.com"
    assert msg["Message-ID"].endswith("@reliafy.com>") and msg["Message-ID"] == out["message_id"]
    assert msg["X-Reliafy-Support-Reply"] == out["id"]
    assert msg.get_body(("plain",)).get_content().startswith("Hi,")
    assert out["sent_by"]["uid"] == OP and out["sent_by"]["token_id"]


def test_html_bare_ids_and_no_copy(env, monkeypatch):
    from backend import config

    monkeypatch.setattr(config, "SUPPORT_COPY_TO", "")
    r = env.post({"to": "c@example.com", "subject": "Hello", "text": "Plain", "html": "<p>Rich</p>",
                  "in_reply_to": "abc@mail.example.com"})
    assert r.status_code == 200, r.text
    [msg] = FakeSMTP.sent
    assert msg["In-Reply-To"] == "<abc@mail.example.com>"
    assert msg["References"] == "<abc@mail.example.com>"
    assert msg["Bcc"] is None
    assert msg.get_body(("html",)).get_content().strip() == "<p>Rich</p>"


def test_a_new_message_has_no_thread_headers(env):
    assert env.post({"to": "c@example.com", "subject": "Hello", "text": "Hi"}).status_code == 200
    [msg] = FakeSMTP.sent
    assert msg["In-Reply-To"] is None and msg["References"] is None


@pytest.mark.parametrize("body", [
    {"subject": "x", "text": "y"},
    {"to": "a@example.com, b@example.com", "subject": "x", "text": "y"},
    {"to": "a@example.com\r\nBcc: z@example.com", "subject": "x", "text": "y"},
    {"to": "a@example.com", "subject": "", "text": "y"},
    {"to": "a@example.com", "subject": "x", "text": ""},
    {"to": "a@example.com", "subject": "x", "text": "y", "in_reply_to": "not an id"},
    {"to": "a@example.com", "subject": "x", "text": "y", "references": [42]},
])
def test_bad_requests_are_refused_and_nothing_is_sent(env, body):
    r = env.post(body)
    assert r.status_code == 422 and r.json()["detail"]
    assert FakeSMTP.sent == [] and env.db.support_replies.count_documents({}) == 0


def test_only_operators(env):
    for uid in (PRO, FREE):
        r = env.post(REPLY, uid=uid)
        assert r.status_code == 403 and "operators" in r.json()["detail"]
        assert env.get(uid=uid).status_code == 403
    assert FakeSMTP.sent == []
    assert env.client.post(URL, json=REPLY).status_code == 401
    assert env.post(REPLY, token="rlf_nope").status_code == 401


def test_an_unverified_operator_address_is_not_an_operator(env):
    env.db.users.update_one({"_id": OP}, {"$set": {"email_verified": False}})
    assert env.post(REPLY).status_code == 403


def test_a_read_only_token_can_list_but_not_send(env):
    assert env.post(REPLY, token=env.read_only).status_code == 403
    assert env.get(token=env.read_only).status_code == 200


def test_unconfigured_email_is_503(env, monkeypatch):
    from backend import config

    monkeypatch.setattr(config, "SMTP_HOST", None)
    r = env.post(REPLY)
    assert r.status_code == 503 and "isn't configured" in r.json()["detail"]
    assert FakeSMTP.sent == []


def test_the_hourly_limit_is_429(env, monkeypatch):
    from backend import config

    monkeypatch.setattr(config, "SUPPORT_REPLIES_PER_HOUR", 2)
    # An old reply doesn't count.
    env.db.support_replies.insert_one({"_id": "old", "sent_at": datetime.now(timezone.utc) - timedelta(hours=2)})
    assert env.post(REPLY).status_code == 200
    assert env.post(REPLY).status_code == 200
    r = env.post(REPLY)
    assert r.status_code == 429 and "2 an hour" in r.json()["detail"]
    assert len(FakeSMTP.sent) == 2


def test_a_failed_send_is_502_and_logged(env):
    FakeSMTP.fail = True
    r = env.post(REPLY)
    assert r.status_code == 502 and "wasn't sent" in r.json()["detail"]
    [rec] = env.db.support_replies.find({})
    assert rec["status"] == "failed"


def test_the_log_lists_the_last_50_with_short_previews(env):
    long_text = "word " * 2000
    for i in range(3):
        assert env.post({**REPLY, "subject": f"Re: {i}", "text": long_text}).status_code == 200
    r = env.get()
    assert r.status_code == 200
    replies = r.json()["replies"]
    assert [x["subject"] for x in replies] == ["Re: 2", "Re: 1", "Re: 0"]
    first = replies[0]
    assert len(first["preview"]) <= 120
    assert first["in_reply_to"] == "<CAB123@mail.example.com>" and first["sent_by"]["uid"] == OP
    stored = env.db.support_replies.find_one({"_id": first["id"]})
    assert "text" not in stored and len(stored["preview"]) <= 120
    for i in range(55):
        env.db.support_replies.insert_one({"_id": f"x{i}", "sent_at": datetime.now(timezone.utc) - timedelta(days=1)})
    assert len(env.get().json()["replies"]) == 50
