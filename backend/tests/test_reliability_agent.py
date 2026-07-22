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
    # No time column and no interval pair -> a clear error, not a fit crash.
    assert "error" in agent._execute_tool(db, U, "create_life_model",
                                          {"name": "x", "dataset_id": ds["dataset_id"],
                                           "distribution": "weibull"})


def test_execute_tool_creates_rbd_series_parallel():
    """create_rbd expands a series-of-parallel spec into a valid, analysable RBD
    (controller in series with two redundant pumps) and saves it."""
    from backend.services import reliability_agent as agent
    from backend.services import rbds as rbds_service

    db = mongomock.MongoClient()["reliafy_test"]
    inp = {
        "name": "Pump station",
        "stages": [
            {"label": "Controller", "components": [
                {"label": "PLC", "distribution": "weibull",
                 "params": [{"name": "alpha", "value": 1500}, {"name": "beta", "value": 1.8}]},
            ]},
            {"label": "Pumps", "k_of_n": 1, "components": [
                {"label": "Pump A", "distribution": "weibull",
                 "params": [{"name": "alpha", "value": 900}, {"name": "beta", "value": 1.4}]},
                {"label": "Pump B", "distribution": "weibull",
                 "params": [{"name": "alpha", "value": 900}, {"name": "beta", "value": 1.4}]},
            ]},
        ],
    }
    res = agent._execute_tool(db, U, "create_rbd", inp)
    assert res["ok"], res
    assert res["n_stages"] == 2 and res["n_components"] == 3

    rbd = rbds_service.get_rbd(db, res["rbd_id"], owner_id=U)
    assert rbd is not None
    # The laid-out graph is a valid, closed-form-solvable RBD.
    v = rbds_service.validate_graph(db, rbd.graph, owner_id=U)
    assert v["valid"] and v["can_calculate"], v
    # A parallel stage (>1 component) gets a k-of-n voting node as its exit.
    assert any(n["type"] == "knode" for n in rbd.graph["nodes"])
    # And it actually analyses end to end.
    out = rbds_service.analyze_rbd(db, res["rbd_id"], owner_id=U, t_max=1000.0)
    assert out is not None

    # Bad spec -> a clean error, not an exception.
    assert "error" in agent._execute_tool(db, U, "create_rbd", {"name": "x", "stages": []})
    assert "error" in agent._execute_tool(db, U, "create_rbd", {"name": "x", "stages": [
        {"components": [{"label": "c", "distribution": "weibull"}]}]})  # no params


def test_create_life_model_full_inputs():
    """The expanded tool passes censoring, counts, the offset/zi/lfp modifiers,
    fixed params, and covariates through to the fit."""
    from backend.services import reliability_agent as agent

    db = mongomock.MongoClient()["reliafy_test"]

    # Censored data with a count column + a 3-parameter (offset) Weibull.
    rows = [("100", "0", "3"), ("250", "0", "2"), ("400", "1", "5"), ("600", "0", "4"),
            ("820", "1", "6"), ("1050", "0", "3")]
    csv = "t,censored,qty\n" + "\n".join(",".join(r) for r in rows) + "\n"
    ds = agent._execute_tool(db, U, "create_dataset", {"name": "Censored", "csv": csv})
    m = agent._execute_tool(db, U, "create_life_model", {
        "name": "Weibull 3p", "dataset_id": ds["dataset_id"], "distribution": "weibull",
        "time_column": "t", "censored_column": "censored", "count_column": "qty",
        "offset": True, "unit": "hours"})
    assert m["ok"], m
    saved = db.models.find_one({"_id": m["model_id"]})
    spec = saved["spec"]
    assert spec["mapping"] == {"x": "t", "c": "censored", "n": "qty"}
    assert spec["options"]["offset"] is True

    # Regression: a proportional-hazards fit with a covariate column.
    reg_rows = [("120", "0", "40"), ("300", "0", "55"), ("470", "1", "60"),
                ("640", "0", "48"), ("910", "1", "70"), ("1180", "0", "52"),
                ("150", "0", "44"), ("520", "0", "63")]
    reg = "time,censored,temp\n" + "\n".join(",".join(r) for r in reg_rows) + "\n"
    dsr = agent._execute_tool(db, U, "create_dataset", {"name": "ALT", "csv": reg})
    mr = agent._execute_tool(db, U, "create_life_model", {
        "name": "Weibull PH", "dataset_id": dsr["dataset_id"], "distribution": "weibull_ph",
        "time_column": "time", "censored_column": "censored", "covariates": ["temp"]})
    assert mr["ok"], mr
    saved_r = db.models.find_one({"_id": mr["model_id"]})
    assert saved_r["spec"]["covariates"] == ["temp"]
    assert saved_r["kind"] == "regression"


class _FakeStream:
    def __init__(self, events): self._events = events
    def __enter__(self): return iter(self._events)
    def __exit__(self, *a): return False


class _FakeClient:
    """Scripts two stream rounds: the agent calls create_dataset, goes idle; then
    (after we return the tool result) a final message + idle. Captures sends."""
    def __init__(self):
        self.sent = []
        rounds = [
            [{"type": "agent.custom_tool_use", "id": "tu1", "name": "create_dataset",
              "input": {"name": "X", "csv": "t\n1\n2\n3\n"}},
             {"type": "session.thread_status_idle"}],
            [{"type": "agent.message", "content": [{"text": "done"}]},
             {"type": "session.thread_status_idle"}],
        ]
        outer = self
        class _Events:
            def send(self, sid, events=None): outer.sent.append(events)
            def stream(self, sid): return _FakeStream(rounds.pop(0) if rounds else [])
        class _Sessions:
            events = _Events()
            def create(self, **kw): return type("S", (), {"id": "s1"})()
        self.beta = type("B", (), {"sessions": _Sessions()})()


def test_hard_approval_gate_blocks_tools_until_approved(monkeypatch):
    """The create tools only run when the turn is approved — the gate is enforced
    in code, not just the prompt."""
    from backend.services import reliability_agent as agent

    # Unapproved: the tool call is BLOCKED — nothing is created, agent gets an error.
    db1 = mongomock.MongoClient()["reliafy_test"]
    fake1 = _FakeClient()
    monkeypatch.setattr(agent, "_client", lambda: fake1)
    evs = list(agent.stream_run(db1, U, "go", session_id="s1", approved=False))
    kinds = [e["type"] for e in evs]
    assert "reliafy_tool_blocked" in kinds
    assert "reliafy_tool_result" not in kinds
    assert db1.datasets.count_documents({}) == 0            # nothing created
    result_sent = fake1.sent[-1][0]                          # the user.custom_tool_result
    assert result_sent["is_error"] is True

    # Approved: the same call executes and the dataset lands.
    db2 = mongomock.MongoClient()["reliafy_test"]
    fake2 = _FakeClient()
    monkeypatch.setattr(agent, "_client", lambda: fake2)
    evs2 = list(agent.stream_run(db2, U, "go", session_id="s1", approved=True))
    kinds2 = [e["type"] for e in evs2]
    assert "reliafy_tool_result" in kinds2 and "reliafy_tool_blocked" not in kinds2
    assert db2.datasets.count_documents({"owner_id": U}) == 1
    assert fake2.sent[-1][0]["is_error"] is False


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
    from backend.services import billing
    from backend.services import reliability_agent as agent

    client, app, test_db = _client(monkeypatch)
    body = {"message": "hi"}
    try:
        app.dependency_overrides[get_current_user] = lambda: {"uid": U, "email": "a", "name": "A"}
        monkeypatch.setattr(agent, "enabled", lambda: False)
        assert client.post("/api/reliability-agent/run", json=body).status_code == 503
        monkeypatch.setattr(agent, "enabled", lambda: True)
        # Free tier (only the starter grant, never paid) is blocked as a paid
        # feature — even holding those free credits.
        billing.grant_credits(test_db, U, 1000, "starter")
        r_free = client.post("/api/reliability-agent/run", json=body)
        assert r_free.status_code == 403 and r_free.json()["code"] == "pro_required"
        # Pro but out of credits -> the ordinary credit gate (402).
        billing.set_plan(test_db, U, "pro")
        billing.charge_credits(test_db, U, 1000, "reset")  # -> 0 credits
        r_broke = client.post("/api/reliability-agent/run", json=body)
        assert r_broke.status_code == 402 and r_broke.json()["code"] == "no_credits"
    finally:
        app.dependency_overrides.clear()


def test_purchased_credits_unlock_agent_without_pro(monkeypatch):
    """A non-Pro user who has BOUGHT credits (ledger reason 'purchase') is
    entitled to the agent — the paid gate passes and the run streams."""
    from backend.auth import get_current_user
    from backend.services import billing
    from backend.services import reliability_agent as agent

    client, app, test_db = _client(monkeypatch)
    try:
        app.dependency_overrides[get_current_user] = lambda: {"uid": U, "email": "a", "name": "A"}
        monkeypatch.setattr(agent, "enabled", lambda: True)
        monkeypatch.setattr(agent, "stream_run", lambda db, uid, message, file_id=None, session_id=None, approved=False: iter([
            {"type": "text", "text": "plan"},
            {"type": "_meter", "session_id": "s1", "seconds": 0.0, "input_tokens": 0, "output_tokens": 0},
        ]))
        billing.grant_credits(test_db, U, 500, "purchase", "cs_test")  # bought a pack, still free plan
        assert billing.account(test_db, U)["is_pro"] is False
        r = client.post("/api/reliability-agent/run", json={"message": "hi"})
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
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
        billing.set_plan(test_db, U, "pro")  # the agent is Pro-only
        monkeypatch.setattr(agent, "enabled", lambda: True)
        # stream_run signature: (db, uid, message, file_id=None, session_id=None, approved=False).
        monkeypatch.setattr(agent, "stream_run", lambda db, uid, message, file_id=None, session_id=None, approved=False: iter([
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
    from backend.services import billing
    from backend.services import reliability_agent as agent

    client, app, test_db = _client(monkeypatch)
    files = {"file": ("d.csv", b"t\n1\n2\n", "text/csv")}
    try:
        app.dependency_overrides[get_current_user] = lambda: {"uid": U, "email": "a", "name": "A"}
        monkeypatch.setattr(agent, "enabled", lambda: True)
        monkeypatch.setattr(agent, "upload_csv", lambda data, filename="data.csv": "file-123")
        # Free tier can't upload to the agent sandbox either (Pro-only).
        r_free = client.post("/api/reliability-agent/upload", files=files)
        assert r_free.status_code == 403 and r_free.json()["code"] == "pro_required"
        # Pro succeeds.
        billing.set_plan(test_db, U, "pro")
        r = client.post("/api/reliability-agent/upload", files=files)
        assert r.status_code == 200
        assert r.json()["file_id"] == "file-123"
    finally:
        app.dependency_overrides.clear()
