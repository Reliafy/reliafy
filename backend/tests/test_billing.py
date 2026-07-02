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
