"""The welcome-to-Pro email: once per account, ever, from the Stripe webhook
(paid) or the operator CLI (complimentary).

Delivery is always faked: ``email._deliver`` is replaced, so nothing here
talks to SMTP.
"""

import json

import mongomock
import pytest

U = "u-pro"
USER = {"_id": U, "email": "Sam.Ng@mail.example.org", "name": "Sam Ng", "email_verified": True,
        "stripe_customer_id": "cus_1"}


@pytest.fixture()
def test_db(monkeypatch):
    from backend import config, db

    d = mongomock.MongoClient()["reliafy_test"]
    monkeypatch.setattr(db, "_db", d)
    monkeypatch.setattr(db, "_simulated", True)
    monkeypatch.setattr(config, "PUBLIC_BASE_URL", None)
    d.users.insert_one(dict(USER))
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
    """Lifecycle emails on, sent inline (no thread)."""
    from backend import config
    from backend.services import lifecycle_emails

    monkeypatch.setattr(config, "LIFECYCLE_EMAILS", True)
    monkeypatch.setattr(lifecycle_emails, "_spawn", lambda fn, *args: fn(*args))
    return outbox


def _text(msg):
    return msg.get_body(("plain",)).get_content()


def _checkout(n=1):
    return {"id": f"evt_{n}", "type": "checkout.session.completed", "data": {"object": {
        "id": f"cs_{n}", "customer": "cus_1", "subscription": "sub_1",
        "metadata": {"uid": U, "kind": "pro"}}}}


AI_FEATURES = {"ai": True, "agent": True, "credits": 1000, "mcp": True}


def test_paid_variant_renders_what_pro_adds():
    from backend.services import lifecycle_emails as le

    r = le.render(le.PRO_WELCOME, name="Sam Ng", variant="paid", features=AI_FEATURES)
    assert r.subject == "Welcome to Reliafy Pro"
    assert r.text.startswith("Hi Sam,")
    for phrase in ("No storage limits", "90 days of run history", "up from 7", "1,000 AI credits every month",
                   "the AI assistant and the Reliability Agent", "billing page", "It comes to me", "Derryn"):
        assert phrase in r.text, phrase
    assert "utm_campaign=pro_welcome" in r.text
    # An account notice: no unsubscribe link or header.
    assert "nsubscribe" not in r.text and not r.headers
    for word in ("example", "sample"):
        assert word not in r.text.lower()


def test_paid_variant_drops_ai_lines_when_ai_is_off():
    from backend.services import lifecycle_emails as le

    r = le.render(le.PRO_WELCOME, name=None, variant="paid",
                  features={"ai": False, "agent": False, "credits": 0, "mcp": False})
    assert r.text.startswith("Hi,")
    assert "credit" not in r.text.lower() and "MCP" not in r.text


def test_complimentary_variant_has_no_ai_or_agent_wording():
    from backend.services import lifecycle_emails as le

    r = le.render(le.PRO_WELCOME, name="Sam Ng", variant="complimentary", features=AI_FEATURES)
    assert r.subject == "You're on Reliafy Pro"
    assert "free of charge" in r.text and "No storage limits" in r.text
    low = r.text.lower()
    for word in ("credit", "assistant", "agent", "billing", "invoice"):
        assert word not in low, word
    assert "Reliafy from Claude" in r.text  # MCP needs no credit


def test_fires_once_on_the_subscription_event(test_db, on):
    from backend.routers.billing import _handle_event

    _handle_event(test_db, _checkout(1))
    assert len(on) == 1
    msg = on[0]
    assert msg["To"] == USER["email"] and msg["Subject"] == "Welcome to Reliafy Pro"
    assert msg["Reply-To"] == "hello@reliafy.com"
    row = test_db.lifecycle_emails.find_one({"_id": f"pro_welcome:{U}"})
    assert row["status"] == "sent" and row["variant"] == "paid"

    # A retried webhook, a renewal and a portal update while on Pro: nothing more.
    _handle_event(test_db, _checkout(1))
    _handle_event(test_db, {"id": "evt_inv", "type": "invoice.paid",
                            "data": {"object": {"id": "in_2", "customer": "cus_1"}}})
    _handle_event(test_db, {"id": "evt_up", "type": "customer.subscription.updated", "data": {"object": {
        "id": "sub_1", "customer": "cus_1", "status": "active", "items": {"data": []}}}})
    assert len(on) == 1

    # Lapse, then subscribe again: still only the one.
    _handle_event(test_db, {"id": "evt_del", "type": "customer.subscription.deleted",
                            "data": {"object": {"id": "sub_1", "customer": "cus_1"}}})
    assert test_db.users.find_one({"_id": U})["plan"] == "free"
    _handle_event(test_db, _checkout(2))
    assert test_db.users.find_one({"_id": U})["plan"] == "pro"
    assert len(on) == 1


def test_opted_out_still_gets_it_but_test_domains_and_missing_accounts_dont(test_db, on):
    from backend.routers.billing import _handle_event

    test_db.users.update_one({"_id": U}, {"$set": {"email_updates_opt_out": True}})
    _handle_event(test_db, _checkout(1))
    assert len(on) == 1

    test_db.users.insert_one({"_id": "u-test", "email": "a@reliafy.test", "email_verified": True})
    ev = _checkout(3)
    ev["data"]["object"]["metadata"]["uid"] = "u-test"
    _handle_event(test_db, ev)
    ev = _checkout(4)
    ev["data"]["object"]["metadata"]["uid"] = "u-gone"
    _handle_event(test_db, ev)
    assert len(on) == 1


def test_webhook_still_succeeds_if_sending_raises(test_db, on, monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config
    from backend.main import app
    from backend.services import email, lifecycle_emails

    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    monkeypatch.setattr(config, "STRIPE_WEBHOOK_SECRET", None)

    def boom(msg, **kw):
        raise RuntimeError("smtp down")

    monkeypatch.setattr(email, "_deliver", boom)
    r = TestClient(app).post("/api/stripe/webhook", content=json.dumps(_checkout(1)))
    assert r.status_code == 200
    assert test_db.users.find_one({"_id": U})["plan"] == "pro"
    assert test_db.lifecycle_emails.find_one({"_id": f"pro_welcome:{U}"})["status"] == "failed"

    # Even an error before the send starts never reaches the webhook.
    monkeypatch.setattr(lifecycle_emails, "maybe_send_pro_welcome",
                        lambda *a: (_ for _ in ()).throw(RuntimeError("bad")))
    test_db.users.update_one({"_id": U}, {"$set": {"plan": "free"}})
    r = TestClient(app).post("/api/stripe/webhook", content=json.dumps(_checkout(2)))
    assert r.status_code == 200


def test_off_without_lifecycle_emails(test_db, outbox):
    from backend.routers.billing import _handle_event

    _handle_event(test_db, _checkout(1))
    assert outbox == [] and test_db.lifecycle_emails.count_documents({}) == 0


def test_cli_dry_run_sends_nothing(test_db, on, capsys):
    from backend.scripts import send_pro_welcome

    test_db.users.update_one({"_id": U}, {"$set": {"plan": "pro", "plan_until": None}})
    assert send_pro_welcome.main(["--uid", U]) == 0
    out = capsys.readouterr().out
    assert "You're on Reliafy Pro" in out and "Dry run: nothing sent" in out
    assert "credit" not in out.lower()
    assert on == [] and test_db.lifecycle_emails.count_documents({}) == 0


def test_cli_send_then_the_webhook_sends_nothing_more(test_db, on, capsys):
    from backend.routers.billing import _handle_event
    from backend.scripts import send_pro_welcome

    # Not on Pro yet: refused.
    assert send_pro_welcome.main(["--uid", U, "--send"]) == 1
    assert on == []
    test_db.users.update_one({"_id": U}, {"$set": {"plan": "pro", "plan_until": None}})
    assert send_pro_welcome.main(["--email", "sam.ng@MAIL.example.org", "--send"]) == 0
    assert len(on) == 1 and on[0]["Subject"] == "You're on Reliafy Pro"
    # A second run, and a later paid subscription, send nothing more.
    assert send_pro_welcome.main(["--uid", U, "--send"]) == 1
    test_db.users.update_one({"_id": U}, {"$set": {"plan": "free"}})
    _handle_event(test_db, _checkout(5))
    assert len(on) == 1


def test_cli_mark_sent_records_without_sending(test_db, on, capsys):
    from backend.routers.billing import _handle_event
    from backend.scripts import send_pro_welcome

    assert send_pro_welcome.main(["--uid", U, "--mark-sent", "--note", "sent by hand"]) == 0
    assert on == []
    row = test_db.lifecycle_emails.find_one({"_id": f"pro_welcome:{U}"})
    assert row["status"] == "sent" and row["variant"] == "complimentary" and row["note"] == "sent by hand"
    assert send_pro_welcome.main(["--uid", U, "--mark-sent"]) == 0
    assert "Already in the send log" in capsys.readouterr().out
    _handle_event(test_db, _checkout(6))
    assert on == []
