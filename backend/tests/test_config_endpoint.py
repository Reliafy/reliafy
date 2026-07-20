"""The public /api/config capabilities endpoint."""

import matplotlib

matplotlib.use("Agg")

import mongomock
import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch):
    from backend import db
    from backend.main import app

    test_db = mongomock.MongoClient()["reliafy_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    return TestClient(app)


def test_config_is_public_and_reports_capabilities(client, monkeypatch):
    from backend import config

    # Cloud-ish deployment: auth on, AI key set, Stripe configured.
    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "AI_PROVIDER", "anthropic")
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setattr(config, "STRIPE_API_KEY", "sk_test_x")
    monkeypatch.setattr(config, "BILLING_ENABLED", True)
    monkeypatch.setattr(config, "RELIABILITY_AGENT_ENABLED", False)

    r = client.get("/api/config")  # no Authorization header
    assert r.status_code == 200
    assert r.json() == {"auth": True, "ai": True, "billing": True, "reliability_agent": False}


def test_config_single_user_self_host(client, monkeypatch):
    from backend import config

    # OSS self-host: single-user mode, no AI key, no Stripe.
    monkeypatch.setattr(config, "AUTH_DISABLED", True)
    monkeypatch.setattr(config, "AI_PROVIDER", "anthropic")
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", None)
    monkeypatch.setattr(config, "OPENAI_API_KEY", None)
    monkeypatch.setattr(config, "STRIPE_API_KEY", None)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    monkeypatch.setattr(config, "RELIABILITY_AGENT_ENABLED", False)

    assert client.get("/api/config").json() == {
        "auth": False,
        "ai": False,
        "billing": False,
        "reliability_agent": False,
    }


def test_config_byo_key_self_host_enables_ai_only(client, monkeypatch):
    from backend import config

    # Self-hoster who sets their own provider key gets the assistant (uncharged).
    monkeypatch.setattr(config, "AUTH_DISABLED", True)
    monkeypatch.setattr(config, "AI_PROVIDER", "openai")
    monkeypatch.setattr(config, "OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(config, "STRIPE_API_KEY", None)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    monkeypatch.setattr(config, "RELIABILITY_AGENT_ENABLED", False)

    assert client.get("/api/config").json() == {
        "auth": False,
        "ai": True,
        "billing": False,
        "reliability_agent": False,
    }
