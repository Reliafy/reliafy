"""Stripe fulfilment: the webhook needs its signing secret whenever billing is
on, and a credit grant for a Stripe event happens once however often (or
however concurrently) the event is delivered."""

import json
import threading

import mongomock
import pytest
from fastapi.testclient import TestClient

U = "user-a"


@pytest.fixture()
def env(monkeypatch):
    from backend import config, db

    monkeypatch.setattr(config, "BILLING_ENABLED", True)
    test_db = mongomock.MongoClient()["reliafy_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    from backend.main import app

    yield TestClient(app), test_db


def test_webhook_requires_a_secret_when_billing_is_on(env, monkeypatch):
    from backend import config
    from backend.services import billing

    client, db = env
    monkeypatch.setattr(config, "STRIPE_WEBHOOK_SECRET", None)
    event = {"id": "evt_1", "type": "checkout.session.completed", "data": {"object": {
        "id": "cs_x", "metadata": {"uid": U, "kind": "pack", "grant_cents": "5000"}}}}
    r = client.post("/api/stripe/webhook", content=json.dumps(event))
    assert r.status_code == 503
    assert billing.account(db, U)["credit_cents"] == 0

    # Self-hosted with billing off: unchanged (unsigned events still accepted).
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    assert client.post("/api/stripe/webhook", content=json.dumps(event)).status_code == 200


def test_webhook_with_a_secret_still_checks_the_signature(env, monkeypatch):
    from backend import config
    from backend.services import billing

    client, db = env
    monkeypatch.setattr(config, "STRIPE_WEBHOOK_SECRET", "whsec_test")
    event = {"id": "evt_1", "type": "checkout.session.completed", "data": {"object": {
        "id": "cs_x", "metadata": {"uid": U, "kind": "pack", "grant_cents": "5000"}}}}
    r = client.post("/api/stripe/webhook", content=json.dumps(event),
                    headers={"stripe-signature": "t=1,v1=nope"})
    assert r.status_code == 400
    assert billing.account(db, U)["credit_cents"] == 0


def test_replayed_checkout_event_grants_once(env):
    from backend.routers.billing import _handle_event
    from backend.services import billing

    _client, db = env
    event = {"id": "evt_2", "type": "checkout.session.completed", "data": {"object": {
        "id": "cs_2", "metadata": {"uid": U, "kind": "pack", "grant_cents": "2100"}}}}
    for _ in range(3):
        _handle_event(db, event)
    assert billing.account(db, U)["credit_cents"] == 2100
    assert db.credit_ledger.count_documents({"ref": "cs_2", "kind": "grant"}) == 1

    # Deliveries racing each other still grant once.
    event2 = {"id": "evt_3", "type": "checkout.session.completed", "data": {"object": {
        "id": "cs_3", "metadata": {"uid": U, "kind": "pack", "grant_cents": "500"}}}}
    barrier = threading.Barrier(4)

    def deliver():
        barrier.wait()
        _handle_event(db, event2)

    threads = [threading.Thread(target=deliver) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert billing.account(db, U)["credit_cents"] == 2600


def test_grant_recorded_without_a_key_is_not_repeated(env):
    """Ledger rows from before grants were keyed still count as granted."""
    from backend.services import billing

    _client, db = env
    db.credit_ledger.insert_one({"uid": U, "kind": "grant", "millicents": 500_000,
                                 "reason": "purchase", "ref": "cs_old"})
    assert billing.grant_credits_once(db, U, 500, "purchase", "cs_old") is False
    assert billing.account(db, U)["credit_cents"] == 0


def test_monthly_pro_grant_ledger_row_stops_a_second_grant(env, monkeypatch):
    from backend import config
    from backend.services import billing

    _client, db = env
    monkeypatch.setattr(config, "PRO_MONTHLY_CREDIT_CENTS", 1000)
    billing.set_plan(db, U, "pro", customer_id="cus_7")
    # Another delivery already wrote the invoice's ledger row (its increment
    # in flight): this one must not add the credit again.
    db.credit_ledger.insert_one({"_id": "grant:pro-monthly:in_7", "uid": U, "kind": "grant",
                                 "millicents": 1_000_000, "reason": "pro-monthly", "ref": "in_x"})
    assert billing.grant_monthly_pro_credits(db, "cus_7", "in_7") is False
    assert billing.account(db, U)["credit_cents"] == 0
    assert billing.grant_monthly_pro_credits(db, "cus_7", "in_8") is True
    assert billing.grant_monthly_pro_credits(db, "cus_7", "in_8") is False
    assert billing.account(db, U)["credit_cents"] == 1000
