"""Reliability Agent (Anthropic Managed Agents) — tool execution, event
normalisation, metering + SSE route.

The SDK/streaming boundary is mocked at ``stream_run`` / ``upload_csv`` /
``enabled`` so tests are stable against the still-beta Managed Agents API; the
Reliafy-side tool execution (``_execute_tool``) is tested for real against a
mongomock db.
"""

import io
import json

import mongomock
import pandas as pd
from fastapi.testclient import TestClient

U = "agent-user"


def _sse_events(text: str) -> list:
    out = []
    for frame in text.split("\n\n"):
        for line in frame.splitlines():
            if line.startswith("data:"):
                out.append(json.loads(line[5:].strip()))
    return out


def test_norm_matches_managed_agents_event_schema():
    """Pin normalisation to the REAL Managed Agents event shapes (captured live):
    text on agent.message.content, bash command on agent.tool_use.input, output
    on agent.tool_result.content, our tools on agent.custom_tool_use, idle on
    session.thread_status_idle, usage on span.model_request_end.model_usage."""
    from backend.services import reliability_agent as agent

    assert agent._norm({"type": "span.model_request_start"}) == []
    assert agent._norm({"type": "user.message", "content": [{"text": "hi"}]}) == []

    assert agent._norm({"type": "agent.message", "content": [{"text": "Done."}]}) == \
        [{"type": "text", "text": "Done."}]

    tu = agent._norm({"type": "agent.tool_use", "name": "bash",
                      "input": {"command": 'python -c "print(6*7)"'}})[0]
    assert tu["type"] == "tool_use" and tu["name"] == "bash"
    assert tu["code"] == 'python -c "print(6*7)"'

    assert agent._norm({"type": "agent.tool_result", "content": [{"text": "42\n"}]}) == \
        [{"type": "tool_result", "output": "42\n"}]

    # Our Reliafy tools surface as a distinct event the UI renders specially.
    ct = agent._norm({"type": "agent.custom_tool_use", "name": "create_dataset",
                      "input": {"name": "X", "csv": "t\n1\n"}})
    assert ct == [{"type": "reliafy_tool", "name": "create_dataset",
                   "input": {"name": "X", "csv": "t\n1\n"}}]

    assert agent._norm({"type": "agent.thinking"}) == [{"type": "status", "status": "thinking"}]
    assert agent._norm({"type": "session.thread_status_idle"}) == \
        [{"type": "status", "status": "thread_status_idle"}]

    assert agent._is_idle({"type": "session.thread_status_idle"}) is True
    assert agent._is_idle({"type": "agent.message"}) is False
    assert agent._event_usage({"type": "agent.message"}) == (0, 0)
    assert agent._event_usage({"type": "span.model_request_end",
                               "model_usage": {"input_tokens": 1200, "output_tokens": 300}}) == (1200, 300)


def _csv() -> str:
    rows = "\n".join(str(v) for v in [120, 340, 560, 780, 910, 1100, 1350, 1600, 1820, 2050])
    return f"hours\n{rows}\n"


def test_execute_tool_creates_dataset_then_life_model():
    """The build→load tools run on the Reliafy side against a real (mock) db:
    create_dataset returns an id, create_life_model fits + saves against it."""
    from backend.services import reliability_agent as agent

    db = mongomock.MongoClient()["reliafy_test"]

    ds = agent._execute_tool(db, U, "create_dataset", {"name": "Bearings", "csv": _csv()})
    assert ds["ok"] and ds["n_rows"] == 10
    assert db.datasets.find_one({"_id": ds["dataset_id"], "owner_id": U}) is not None
    assert "Created dataset" in ds["summary"]

    lm = agent._execute_tool(db, U, "create_life_model", {
        "name": "Bearing life", "dataset_id": ds["dataset_id"],
        "distribution": "weibull", "time_column": "hours", "unit": "hours"})
    assert lm["ok"] and lm["distribution"] and lm["params"]
    saved = db.models.find_one({"_id": lm["model_id"], "owner_id": U})
    assert saved is not None and saved["dataset_id"] == ds["dataset_id"]

    # Errors come back as {"error": ...}, not exceptions.
    assert "error" in agent._execute_tool(db, U, "create_dataset", {"name": "x", "csv": ""})
    assert "error" in agent._execute_tool(db, U, "create_life_model",
                                          {"name": "x", "dataset_id": "missing",
                                           "distribution": "weibull", "time_column": "hours"})
    assert "error" in agent._execute_tool(db, U, "bogus_tool", {})


def test_config_exposes_agent_feature_flag(monkeypatch):
    from backend import config, db
    from backend.main import app

    monkeypatch.setattr(db, "_db", mongomock.MongoClient()["reliafy_test"])
    monkeypatch.setattr(db, "_simulated", True)
    client = TestClient(app)
    monkeypatch.setattr(config, "RELIABILITY_AGENT_ENABLED", False)
    assert client.get("/api/config").json()["reliability_agent"] is False
    monkeypatch.setattr(config, "RELIABILITY_AGENT_ENABLED", True)
    assert client.get("/api/config").json()["reliability_agent"] is True


def test_cost_millicents_tokens_plus_session_runtime(monkeypatch):
    from backend import config
    from backend.services import reliability_agent as agent

    monkeypatch.setattr(config, "RELIABILITY_AGENT_MODEL", "m")
    monkeypatch.setattr(config, "TOKEN_PRICES", {"m": {"in": 3.0, "out": 15.0}})
    monkeypatch.setattr(config, "AI_MARKUP", 1.0)
    monkeypatch.setattr(config, "MANAGED_AGENT_USD_PER_HOUR", 0.08)

    assert agent.cost_millicents(0.0, 1000, 1000) == 1800
    assert agent.cost_millicents(60.0, 1000, 1000) == 1800 + 133


def test_enabled_follows_api_key(monkeypatch):
    from backend import config
    from backend.services import reliability_agent as agent

    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", None)
    assert agent.enabled() is False
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "sk-test")
    assert agent.enabled() is True


def _client(monkeypatch):
    from backend import config, db

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", True)
    monkeypatch.setattr(config, "RELIABILITY_AGENT_MODEL", "m")
    monkeypatch.setattr(config, "TOKEN_PRICES", {"m": {"in": 3.0, "out": 15.0}})
    monkeypatch.setattr(config, "AI_MARKUP", 1.0)
    monkeypatch.setattr(config, "MANAGED_AGENT_USD_PER_HOUR", 0.08)
    test_db = mongomock.MongoClient()["reliafy_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    from backend.main import app
    return TestClient(app), app, test_db


def test_run_config_and_credit_gates(monkeypatch):
    from backend.auth import get_current_user
    from backend.services import reliability_agent as agent

    client, app, _ = _client(monkeypatch)
    body = {"message": "hi"}
    try:
        app.dependency_overrides[get_current_user] = lambda: {"uid": U, "email": "a", "name": "A"}
        monkeypatch.setattr(agent, "enabled", lambda: False)
        assert client.post("/api/reliability-agent/run", json=body).status_code == 503
        monkeypatch.setattr(agent, "enabled", lambda: True)
        assert client.post("/api/reliability-agent/run", json=body).status_code == 402
    finally:
        app.dependency_overrides.clear()


def test_run_streams_events_and_meters(monkeypatch):
    from backend.auth import get_current_user
    from backend.services import billing
    from backend.services import reliability_agent as agent

    client, app, test_db = _client(monkeypatch)
    try:
        app.dependency_overrides[get_current_user] = lambda: {"uid": U, "email": "a", "name": "A"}
        billing.grant_credits(test_db, U, 1000, "test")
        monkeypatch.setattr(agent, "enabled", lambda: True)
        # stream_run's new signature: (db, uid, message, file_id=None, session_id=None).
        monkeypatch.setattr(agent, "stream_run", lambda db, uid, message, file_id=None, session_id=None: iter([
            {"type": "text", "text": "here's my plan…"},
            {"type": "reliafy_tool", "name": "create_dataset", "input": {}},
            {"type": "reliafy_tool_result", "name": "create_dataset", "ok": True, "summary": "Created dataset “X” (10 rows)."},
            {"type": "_meter", "session_id": "sesn_xyz", "seconds": 60.0, "input_tokens": 1000, "output_tokens": 1000},
        ]))

        r = client.post("/api/reliability-agent/run", json={"message": "fit weibull", "file_id": "f1"})
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        evs = _sse_events(r.text)
        assert [e["type"] for e in evs] == ["text", "reliafy_tool", "reliafy_tool_result", "done"]

        done = evs[-1]
        assert done["session_id"] == "sesn_xyz"
        # 1800 (tokens) + 133 (session runtime) = 1933 mc -> 2 credits; 998 left
        assert done["cost_millicents"] == 1933
        assert done["cost_cents"] == 2
        assert done["credit_cents"] == 998
        assert billing.account(test_db, U)["credit_cents"] == 998
    finally:
        app.dependency_overrides.clear()


def test_upload_endpoint(monkeypatch):
    from backend.auth import get_current_user
    from backend.services import reliability_agent as agent

    client, app, _ = _client(monkeypatch)
    try:
        app.dependency_overrides[get_current_user] = lambda: {"uid": U, "email": "a", "name": "A"}
        monkeypatch.setattr(agent, "enabled", lambda: True)
        monkeypatch.setattr(agent, "upload_csv", lambda data, filename="data.csv": "file-123")
        r = client.post("/api/reliability-agent/upload", files={"file": ("d.csv", b"t\n1\n2\n", "text/csv")})
        assert r.status_code == 200
        assert r.json()["file_id"] == "file-123"
    finally:
        app.dependency_overrides.clear()
