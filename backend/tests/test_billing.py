"""Credits, plan caps, and the metered assistant proxy."""

import matplotlib

matplotlib.use("Agg")

import io

import numpy as np
import pandas as pd
import pytest


@pytest.fixture()
def session(monkeypatch):
    import mongomock

    from backend import db

    test_db = mongomock.MongoClient()["reliafy_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    yield test_db


U = "user-a"


def test_credit_ledger_grant_charge_and_floor(session):
    from backend.services import billing

    assert billing.account(session, U)["credit_cents"] == 0
    assert billing.grant_credits(session, U, 500, "purchase") == 500
    assert billing.charge_credits(session, U, 120, "assistant") == 380
    # A charge larger than the balance floors at zero, never negative.
    assert billing.charge_credits(session, U, 9999, "assistant") == 0
    assert billing.account(session, U)["credit_cents"] == 0


def test_starter_grant_is_once(session, monkeypatch):
    from backend import config
    from backend.services import billing

    monkeypatch.setattr(config, "FREE_GRANT_CENTS", 25)
    billing.ensure_starter_grant(session, U)
    billing.ensure_starter_grant(session, U)  # idempotent
    assert billing.account(session, U)["credit_cents"] == 25


def test_ai_cost_applies_markup(monkeypatch):
    from backend import config
    from backend.services import billing

    monkeypatch.setattr(config, "AI_MARKUP", 1.30)
    monkeypatch.setattr(config, "TOKEN_PRICES", {"m": {"in": 3.0, "out": 15.0}})
    # 1M in + 1M out = $3 + $15 = $18 -> 1800c * 1.3 = 2340c
    assert billing.ai_cost_cents("m", 1_000_000, 1_000_000) == 2340
    # Tiny usage still costs at least 1 cent.
    assert billing.ai_cost_cents("m", 1, 0) == 1


def test_is_pro_respects_expiry(monkeypatch):
    from datetime import datetime, timedelta, timezone

    from backend.services import billing

    assert billing.is_pro({"plan": "free"}) is False
    assert billing.is_pro({"plan": "pro"}) is True
    past = datetime.now(timezone.utc) - timedelta(days=1)
    future = datetime.now(timezone.utc) + timedelta(days=1)
    assert billing.is_pro({"plan": "pro", "plan_until": past}) is False
    assert billing.is_pro({"plan": "pro", "plan_until": future}) is True


def test_caps_only_when_billing_enabled(session, monkeypatch):
    from backend import config
    from backend.services import billing

    session.datasets.insert_many([{"_id": "d1", "owner_id": U}, {"_id": "d2", "owner_id": U}, {"_id": "d3", "owner_id": U}])

    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    assert billing.would_exceed_cap(session, U, "datasets") is False  # billing off

    monkeypatch.setattr(config, "BILLING_ENABLED", True)
    monkeypatch.setattr(config, "FREE_MAX_DATASETS", 3)
    assert billing.would_exceed_cap(session, U, "datasets") is True  # at cap, free

    billing.set_plan(session, U, "pro")
    assert billing.would_exceed_cap(session, U, "datasets") is False  # pro lifts caps


def _csv():
    df = pd.DataFrame({"t": np.round(np.random.default_rng(1).weibull(2.0, 30) * 100, 2)})
    b = io.StringIO(); df.to_csv(b, index=False); return b.getvalue().encode()


def test_api_enforces_dataset_cap(monkeypatch):
    import mongomock
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", True)
    monkeypatch.setattr(config, "FREE_MAX_DATASETS", 1)
    test_db = mongomock.MongoClient()["reliafy_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    client = TestClient(app)
    try:
        app.dependency_overrides[get_current_user] = lambda: {"uid": U, "email": "a", "name": "A"}
        r1 = client.post("/api/datasets", files={"file": ("a.csv", _csv(), "text/csv")}, data={"name": "a"})
        assert r1.status_code == 200
        r2 = client.post("/api/datasets", files={"file": ("b.csv", _csv()[:-3] + b"9\n", "text/csv")}, data={"name": "b"})
        assert r2.status_code == 402
        assert r2.json()["code"] == "cap"
    finally:
        app.dependency_overrides.clear()


def test_assistant_step_requires_config_then_charges(monkeypatch):
    import mongomock
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app
    from backend.services import assistant as assistant_service
    from backend.services import billing

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", True)
    monkeypatch.setattr(config, "AI_MODEL", "m")
    monkeypatch.setattr(config, "TOKEN_PRICES", {"m": {"in": 3.0, "out": 15.0}})
    monkeypatch.setattr(config, "AI_MARKUP", 1.0)
    test_db = mongomock.MongoClient()["reliafy_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    client = TestClient(app)
    body = {"system": "s", "messages": [{"role": "user", "content": "hi"}], "tools": []}
    try:
        app.dependency_overrides[get_current_user] = lambda: {"uid": U, "email": "a", "name": "A"}

        # Not configured -> 503.
        monkeypatch.setattr(assistant_service, "enabled", lambda: False)
        assert client.post("/api/assistant/step", json=body).status_code == 503

        # Configured but no credits -> 402.
        monkeypatch.setattr(assistant_service, "enabled", lambda: True)
        assert client.post("/api/assistant/step", json=body).status_code == 402

        # With credit, a step charges the metered cost.
        billing.grant_credits(session_db(test_db), U, 1000, "test")
        monkeypatch.setattr(
            assistant_service, "step",
            lambda system, messages, tools: {
                "message": {"role": "assistant", "content": [{"type": "text", "text": "hello"}]},
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 1000, "output_tokens": 1000},
            },
        )
        r = client.post("/api/assistant/step", json=body)
        assert r.status_code == 200
        data = r.json()
        # 1000 in *3/1e6 + 1000 out *15/1e6 = $0.018 -> 2c (ceil), markup 1.0
        assert data["cost_cents"] == 2
        assert data["credit_cents"] == 998
    finally:
        app.dependency_overrides.clear()


def session_db(test_db):
    return test_db


def test_webhook_grants_credits_and_sets_pro(session):
    from backend.routers.billing import _handle_event
    from backend.services import billing

    _handle_event(session, {
        "type": "checkout.session.completed",
        "data": {"object": {"id": "cs_1", "metadata": {"uid": U, "kind": "pack", "grant_cents": "2100"}}},
    })
    assert billing.account(session, U)["credit_cents"] == 2100

    _handle_event(session, {
        "type": "checkout.session.completed",
        "data": {"object": {"id": "cs_2", "customer": "cus_1", "metadata": {"uid": U, "kind": "pro"}}},
    })
    assert billing.account(session, U)["is_pro"] is True

    _handle_event(session, {
        "type": "customer.subscription.deleted",
        "data": {"object": {"customer": "cus_1"}},
    })
    assert billing.account(session, U)["is_pro"] is False


def test_admin_emails_bypass_caps_and_ai_credits(monkeypatch):
    import mongomock
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app
    from backend.services import assistant as assistant_service
    from backend.services import billing

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", True)
    monkeypatch.setattr(config, "FREE_MAX_DATASETS", 1)
    monkeypatch.setattr(config, "ADMIN_EMAILS", {"admin@example.com", "operator@example.com"})
    monkeypatch.setattr(config, "AI_MODEL", "m")
    monkeypatch.setattr(config, "TOKEN_PRICES", {"m": {"in": 3.0, "out": 15.0}})
    test_db = mongomock.MongoClient()["reliafy_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    client = TestClient(app)

    admin = {"uid": "admin-1", "email": "Admin@example.com", "name": "D"}  # case-insensitive
    assert billing.is_admin_user(admin) is True
    assert billing.is_admin_user({"uid": "x", "email": "someone@else.com"}) is False

    try:
        app.dependency_overrides[get_current_user] = lambda: admin

        # Caps don't apply: exceed FREE_MAX_DATASETS=1 freely.
        for i in range(3):
            r = client.post(
                "/api/datasets",
                files={"file": (f"a{i}.csv", f"t\n{i}1\n{i}2\n{i}3\n".encode(), "text/csv")},
                data={"name": f"a{i}"},
            )
            assert r.status_code == 200, r.text

        # Reported as an operator with their REAL plan (so purchase flows
        # stay testable), not masqueraded as pro.
        me = client.get("/api/me").json()
        assert me["admin"] is True and me["plan"] == "free"
        bill = client.get("/api/billing").json()
        assert bill["admin"] is True and bill["plan"] == "free"

        # AI: zero balance is fine and nothing is charged.
        monkeypatch.setattr(assistant_service, "enabled", lambda: True)
        monkeypatch.setattr(
            assistant_service, "step",
            lambda system, messages, tools: {
                "message": {"role": "assistant", "content": [{"type": "text", "text": "hi"}]},
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 1000, "output_tokens": 1000},
            },
        )
        r = client.post("/api/assistant/step", json={"system": "s", "messages": [], "tools": []})
        assert r.status_code == 200
        assert billing.account(test_db, "admin-1")["credit_cents"] >= 0  # never negative
        # No charge was recorded for the admin.
        assert test_db.credit_ledger.count_documents({"uid": "admin-1", "kind": "charge"}) == 0
    finally:
        app.dependency_overrides.clear()


def test_invoice_paid_grants_monthly_pro_credit_idempotently(session, monkeypatch):
    from backend import config
    from backend.routers.billing import _handle_event
    from backend.services import billing

    monkeypatch.setattr(config, "PRO_MONTHLY_CREDIT_CENTS", 1000)
    # A pro user whose Stripe customer id is known (set during checkout).
    billing.set_plan(session, U, "pro", customer_id="cus_123")

    inv = {"type": "invoice.paid", "data": {"object": {"id": "in_1", "customer": "cus_123"}}}
    _handle_event(session, inv)
    assert billing.account(session, U)["credit_cents"] == 1000

    # Webhook retry / duplicate delivery: no double grant.
    _handle_event(session, inv)
    assert billing.account(session, U)["credit_cents"] == 1000

    # Next month's invoice grants again.
    _handle_event(session, {"type": "invoice.paid", "data": {"object": {"id": "in_2", "customer": "cus_123"}}})
    assert billing.account(session, U)["credit_cents"] == 2000

    # Unknown customer: no-op, no crash.
    _handle_event(session, {"type": "invoice.paid", "data": {"object": {"id": "in_3", "customer": "cus_nope"}}})
    assert billing.account(session, U)["credit_cents"] == 2000


def test_gpt55_metering():
    from backend import config
    from backend.services import billing

    # gpt-5.5 list price: $5/1M in, $30/1M out. With the default 1.3 markup a
    # typical assistant step (2k in, 500 out) costs ceil((0.01 + 0.015)*1.3*100)
    assert "gpt-5.5" in config.TOKEN_PRICES
    cents = billing.ai_cost_cents("gpt-5.5", 2000, 500)
    expected_usd = (2000 * 5.0 + 500 * 30.0) / 1_000_000
    import math
    assert cents == max(1, math.ceil(expected_usd * 100 * config.AI_MARKUP))


def test_cached_tokens_billed_at_cached_rate(monkeypatch):
    from backend import config
    from backend.services import billing

    monkeypatch.setattr(config, "AI_MARKUP", 1.0)
    monkeypatch.setattr(config, "TOKEN_PRICES", {"m": {"in": 5.0, "cached_in": 0.5, "out": 30.0}})

    # 1k full-rate in + 9k cached in: (1000*5 + 9000*0.5)/1e6 = $0.0095 -> 950mc
    assert billing.ai_cost_millicents("m", 1000, 0, cached_input_tokens=9000) == 950
    # Same tokens all at full rate would be 5x the input cost.
    assert billing.ai_cost_millicents("m", 10000, 0) == 5000
    # A model without a cached price bills cached tokens at the full rate.
    monkeypatch.setattr(config, "TOKEN_PRICES", {"m": {"in": 5.0, "out": 30.0}})
    assert billing.ai_cost_millicents("m", 1000, 0, cached_input_tokens=9000) == 5000


def test_millicent_charges_accumulate_without_per_step_rounding(session):
    from backend.services import billing

    billing.grant_credits(session, U, 10, "test")  # 10 credits = 10,000 mc
    # Five sub-cent charges of 600 mc (0.6 credits) each: old cent-metering
    # would have taken 5 whole credits; millicents take exactly 3,000 mc.
    for _ in range(5):
        billing.charge_millicents(session, U, 600, "assistant")
    acct = billing.account(session, U)
    assert acct["credit_millicents"] == 7000
    assert acct["credit_cents"] == 7


def test_legacy_cents_balance_migrates_losslessly(session):
    from backend.services import billing

    # A pre-migration user doc holding only credit_cents.
    session.users.insert_one({"_id": "legacy-1", "credit_cents": 500})
    assert billing.account(session, "legacy-1")["credit_cents"] == 500

    # First charge migrates to millicents without losing the balance.
    bal = billing.charge_millicents(session, "legacy-1", 400, "assistant")
    assert bal == 499
    acct = billing.account(session, "legacy-1")
    assert acct["credit_millicents"] == 499_600
