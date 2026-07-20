"""Reliability Agent (Anthropic Managed Agents) — metering + SSE route.

Mocks at the service boundary (``stream_run`` / ``upload_csv`` / ``enabled``), so
the tests are stable regardless of the exact — still beta — Managed Agents SDK
shapes. Kept in its own file, mirroring the self-contained service/router.
"""

import json

import mongomock
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
    """Pin the normalisation to the REAL Managed Agents event shapes (captured
    from a live run): text on agent.message.content, bash command on
    agent.tool_use.input, output on agent.tool_result.content, idle on
    session.thread_status_idle, and usage on span.model_request_end.model_usage.
    """
    from backend.services import reliability_agent as agent

    assert agent._norm({"type": "span.model_request_start"}) == []
    assert agent._norm({"type": "user.message", "content": [{"text": "hi"}]}) == []

    assert agent._norm({"type": "agent.message", "content": [{"text": "Forty-two."}]}) == \
        [{"type": "text", "text": "Forty-two."}]

    tu = agent._norm({"type": "agent.tool_use", "name": "bash",
                      "input": {"command": 'python -c "print(6*7)"'}})[0]
    assert tu["type"] == "tool_use" and tu["name"] == "bash"
    assert tu["code"] == 'python -c "print(6*7)"'

    assert agent._norm({"type": "agent.tool_result", "content": [{"text": "42\n"}]}) == \
        [{"type": "tool_result", "output": "42\n"}]

    assert agent._norm({"type": "agent.thinking"}) == [{"type": "status", "status": "thinking"}]
    assert agent._norm({"type": "session.thread_status_idle"}) == \
        [{"type": "status", "status": "thread_status_idle"}]

    assert agent._is_idle({"type": "session.thread_status_idle"}) is True
    assert agent._is_idle({"type": "agent.message"}) is False

    assert agent._event_usage({"type": "agent.message"}) == (0, 0)
    assert agent._event_usage({
        "type": "span.model_request_end",
        "model_usage": {"input_tokens": 1200, "output_tokens": 300},
    }) == (1200, 300)


def test_norm_extracts_inline_chart():
    """A base64 PNG the agent prints in tool output becomes an image event, with
    the marker stripped from the shown text."""
    from backend.services import reliability_agent as agent

    b64 = "iVBORw0KGgoAAAANS"  # not a real PNG; only the marker handling matters
    out = agent._norm({
        "type": "agent.tool_result",
        "content": [{"text": f"Saved chart.\n<<RELIAFY_IMG>>{b64}<<END_IMG>>\n"}],
    })
    kinds = [e["type"] for e in out]
    assert kinds == ["tool_result", "image"]
    assert "RELIAFY_IMG" not in out[0]["output"] and out[0]["output"].strip() == "Saved chart."
    assert out[1]["data"] == f"data:image/png;base64,{b64}"

    # Pure-image output yields only the image (no empty text bubble).
    only = agent._norm({"type": "agent.tool_result", "content": [{"text": f"<<RELIAFY_IMG>>{b64}<<END_IMG>>"}]})
    assert [e["type"] for e in only] == ["image"]


def test_norm_extracts_artifact_marker():
    """The preferred channel: the sandbox curls the PNG to our artifact endpoint,
    whose response marker lands in tool output — it becomes an image-URL event.
    A marker echoed in the model's prose is stripped there too."""
    from backend.services import reliability_agent as agent

    aid = "a" * 32
    out = agent._norm({
        "type": "agent.tool_result",
        "content": [{"text": f"<<RELIAFY_ARTIFACT:{aid}>>"}],
    })
    assert out == [{"type": "image", "url": f"/api/reliability-agent/artifacts/{aid}"}]

    prose = agent._norm({
        "type": "agent.message",
        "content": [{"text": f"Here's the chart: <<RELIAFY_ARTIFACT:{aid}>> Enjoy."}],
    })
    kinds = [e["type"] for e in prose]
    assert kinds == ["text", "image"]
    assert "RELIAFY_ARTIFACT" not in prose[0]["text"]


def test_artifact_upload_and_download_roundtrip(monkeypatch):
    """Sandbox POSTs a PNG with a minted token -> marker response; the owner
    (and only the owner) can GET the bytes back."""
    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app
    from backend.services import reliability_agent as agent

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    test_db = mongomock.MongoClient()["reliafy_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    client = TestClient(app)
    png = b"\x89PNG\r\n\x1a\n" + b"fakechartdata"

    try:
        token = agent.mint_artifact_token(test_db, U)

        # Upload (no user auth — the token is the auth), response IS the marker.
        r = client.post(f"/api/reliability-agent/artifacts/upload/{token}",
                        files={"file": ("c.png", png, "image/png")})
        assert r.status_code == 200, r.text
        assert r.text.startswith("<<RELIAFY_ARTIFACT:") and r.text.endswith(">>")
        artifact_id = r.text[len("<<RELIAFY_ARTIFACT:"):-2]

        # Bad token and non-PNG payloads are rejected.
        assert client.post("/api/reliability-agent/artifacts/upload/nope",
                           files={"file": ("c.png", png, "image/png")}).status_code == 403
        assert client.post(f"/api/reliability-agent/artifacts/upload/{token}",
                           files={"file": ("c.txt", b"not a png", "text/plain")}).status_code == 403

        # Owner downloads it; another user gets 404.
        app.dependency_overrides[get_current_user] = lambda: {"uid": U, "email": "a", "name": "A"}
        got = client.get(f"/api/reliability-agent/artifacts/{artifact_id}")
        assert got.status_code == 200
        assert got.content == png and got.headers["content-type"] == "image/png"

        app.dependency_overrides[get_current_user] = lambda: {"uid": "someone-else", "email": "b", "name": "B"}
        assert client.get(f"/api/reliability-agent/artifacts/{artifact_id}").status_code == 404
    finally:
        app.dependency_overrides.clear()


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

    # tokens: (1000*3 + 1000*15)/1e6 * 1e5 = 1800 mc
    assert agent.cost_millicents(0.0, 1000, 1000) == 1800
    # + session runtime: 0.08 * 60/3600 * 1e5 = 133.3 -> 133 mc
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
        monkeypatch.setattr(agent, "stream_run", lambda message, file_id=None, session_id=None, artifact_url=None: iter([
            {"type": "text", "text": "fitting…"},
            {"type": "tool_use", "name": "bash", "code": "import surpyval"},
            {"type": "tool_result", "output": "Weibull alpha=100 beta=2"},
            {"type": "image", "data": "data:image/png;base64,AAAA"},
            {"type": "_meter", "session_id": "sesn_xyz", "seconds": 60.0, "input_tokens": 1000, "output_tokens": 1000},
        ]))

        r = client.post("/api/reliability-agent/run", json={"message": "fit weibull", "file_id": "f1"})
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        evs = _sse_events(r.text)
        kinds = [e["type"] for e in evs]
        assert kinds == ["text", "tool_use", "tool_result", "image", "done"]

        done = evs[-1]
        assert done["session_id"] == "sesn_xyz"  # returned so the client reuses it
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
