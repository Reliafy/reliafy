"""The MCP server at /mcp — auth, entitlement, tool behaviour and scoping.

Exercised through the real HTTP mount: the SDK's Streamable HTTP client talks
to the FastAPI app over an in-process ASGI transport, with the MCP session
manager's lifespan entered explicitly (httpx's ASGI transport doesn't run
app lifespans).
"""

import matplotlib

matplotlib.use("Agg")

import anyio
import httpx2
import mongomock
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

A, B = "user-a", "user-b"
USERS = {
    A: {"_id": A, "email": "a@example.org", "name": "A"},
    B: {"_id": B, "email": "b@example.org", "name": "B"},
}

TIMES = [120, 340, 510, 700, 980, 1200, 1500, 1800, 2100, 2600]
FLAGS = [0, 0, 1, 0, 0, 1, 0, 1, 0, 0]  # 0 = failed, 1 = still running

READ_TOOLS = {
    "list_models", "get_model", "reliability_at", "list_datasets", "list_rbds", "get_rbd",
    "analyze_rbd", "get_job", "fit_distribution", "export_rbd_python", "export_rbd_json", "optimal_replacement",
    "failure_finding_interval",
    "optimal_overhaul", "plan_demonstration_test", "list_fleets", "fleet_forecast", "list_fleet_alerts",
    "upgrade_link", "system_history", "list_share_links", "get_account", "get_dataset", "inspect_upload",
    "compare_groups", "cheapest_design", "fit_per_demand",
}
# Tools that reach outside Reliafy (upgrade_link creates a Stripe checkout).
OPEN_WORLD_TOOLS = {"upgrade_link"}
WRITE_TOOLS = {"fit_and_save_model", "save_model", "upload_dataset", "create_rbd", "clone_rbd", "edit_rbd",
               "create_fleet_alert",
               "delete_model", "delete_dataset", "delete_rbd", "upload_outage_log", "share_link",
               "revoke_share_link", "update_model", "update_dataset",
               "create_upload", "import_rbd", "import_excel"}


def _weibull(alpha, beta, placeholder=False):
    m = {"distribution_id": "weibull", "params": [{"name": "alpha", "value": alpha}, {"name": "beta", "value": beta}]}
    if placeholder:
        m["placeholder"] = True
    return m


# Controller in series with two redundant pumps.
GRAPH = {
    "nodes": [
        {"id": "input", "type": "input"},
        {"id": "ctl", "type": "component", "label": "Controller", "model": _weibull(1500, 1.8)},
        {"id": "p1", "type": "component", "label": "Pump A", "model": _weibull(900, 1.4)},
        {"id": "p2", "type": "component", "label": "Pump B", "model": _weibull(900, 1.4, placeholder=True)},
        {"id": "output", "type": "output"},
    ],
    "edges": [
        {"source": "input", "target": "ctl"}, {"source": "ctl", "target": "p1"},
        {"source": "ctl", "target": "p2"}, {"source": "p1", "target": "output"},
        {"source": "p2", "target": "output"},
    ],
}


@pytest.fixture()
def env(monkeypatch):
    from backend import config, db
    from backend.routers import ingest as ingest_router
    from backend.services import rbd_analysis, tokens

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    monkeypatch.setattr(config, "ADMIN_EMAILS", set())
    monkeypatch.setattr(rbd_analysis, "_AVAIL_SIMS", 20)  # keep the suite quick
    test_db = mongomock.MongoClient()["reliafy_mcp_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    ingest_router._hits.clear()
    for u in USERS.values():
        test_db.users.insert_one(dict(u))

    class Env:
        db = test_db
        token = {uid: tokens.create_token(test_db, uid, "mcp")["token"] for uid in USERS}

    return Env


def _run(token, fn):
    """Open an MCP client session as ``token`` and run ``await fn(client)``."""
    from backend.main import app
    from backend.mcp_server import mcp_http_app

    out = {}

    async def main():
        async with mcp_http_app.lifespan():
            async with httpx2.AsyncClient(
                transport=httpx2.ASGITransport(app=app), base_url="http://testserver",
                headers={"Authorization": f"Bearer {token}"},
            ) as hc:
                async with Client(streamable_http_client("http://testserver/mcp", http_client=hc),
                                  mode="legacy") as client:
                    out["value"] = await fn(client)

    anyio.run(main)
    return out["value"]


def _call(token, name, args=None):
    async def fn(client):
        return await client.call_tool(name, args or {})

    return _run(token, fn)


def _ok(result) -> dict:
    assert not result.is_error, result.content[0].text
    return result.structured_content


def _err(result) -> str:
    assert result.is_error
    return result.content[0].text


def _post_mcp(headers=None):
    from backend.main import app

    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    return TestClient(app).post(
        "/mcp", json=body, headers={"Accept": "application/json, text/event-stream", **(headers or {})})


# ---- auth & entitlement -------------------------------------------------------

def test_missing_or_bad_token_is_401(env):
    r = _post_mcp()
    assert r.status_code == 401
    assert r.headers["www-authenticate"].startswith("Bearer")

    r = _post_mcp({"Authorization": "Bearer rlf_not-a-real-token"})
    assert r.status_code == 401
    assert "invalid_token" in r.headers["www-authenticate"]
    assert "Invalid, expired or revoked" in r.json()["detail"]

    r = _post_mcp({"Authorization": "Basic abc"})
    assert r.status_code == 401


def test_app_lifespan_runs_the_mcp_session_manager(env):
    """Through FastAPI's own lifespan (as uvicorn runs it): initialize works,
    and GET/DELETE get 405 (stateless — nothing to stream or terminate)."""
    from backend.main import app

    auth = {"Authorization": f"Bearer {env.token[A]}", "Accept": "application/json, text/event-stream"}
    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "pytest", "version": "1"}}}
    with TestClient(app) as client:
        r = client.post("/mcp", json=init, headers=auth)
        assert r.status_code == 200, r.text
        result = r.json()["result"]
        assert result["serverInfo"]["name"] == "reliafy"
        assert "0 = the unit FAILED" in result["instructions"]
        assert client.get("/mcp", headers=auth).status_code == 405
        assert client.delete("/mcp", headers=auth).status_code == 405
    # Outside the lifespan the endpoint says so rather than crashing.
    assert TestClient(app).post("/mcp", json=init, headers=auth).status_code == 503


def test_free_user_gets_403_when_billing_is_on(env, monkeypatch):
    from backend import config

    monkeypatch.setattr(config, "BILLING_ENABLED", True)
    r = _post_mcp({"Authorization": f"Bearer {env.token[A]}"})
    assert r.status_code == 403
    assert "API token is part of Reliafy Pro" in r.json()["detail"]

    # Pro gets in.
    env.db.users.update_one({"_id": A}, {"$set": {"plan": "pro"}})
    tools = _run(env.token[A], lambda c: c.list_tools())
    assert len(tools.tools) == len(READ_TOOLS | WRITE_TOOLS)


def test_self_hosted_is_always_allowed_and_last_used_is_recorded(env):
    from backend.mcp_server import authenticate

    # Billing off (self-hosted): api_access_allowed is true for any user.
    status, user, _ = authenticate(env.db, f"Bearer {env.token[B]}")
    assert status == 200 and user["uid"] == B
    assert env.db.api_tokens.find_one({"uid": B})["last_used_at"] is not None


def test_bearer_resolvers_are_pluggable(env, monkeypatch):
    from backend import mcp_server

    monkeypatch.setattr(mcp_server, "BEARER_RESOLVERS", [
        *mcp_server.BEARER_RESOLVERS,
        lambda db, raw: {"uid": A, "email": "a@example.org"} if raw == "oauth-xyz" else None,
    ])
    assert mcp_server.resolve_bearer(env.db, "oauth-xyz")["uid"] == A
    assert mcp_server.resolve_bearer(env.db, "nope") is None


# ---- tool listing ----------------------------------------------------------------

def test_tools_list_has_every_tool_with_annotations(env):
    tools = {t.name: t for t in _run(env.token[A], lambda c: c.list_tools()).tools}
    assert set(tools) == READ_TOOLS | WRITE_TOOLS
    for name, tool in tools.items():
        a = tool.annotations
        assert a.open_world_hint is (name in OPEN_WORLD_TOOLS), name
        assert a.destructive_hint is (name in WRITE_TOOLS), name
        assert tool.title, name
        assert a.read_only_hint is (name in READ_TOOLS), name
        assert tool.description and tool.input_schema["type"] == "object"
        assert tool.output_schema is not None
    # The RBD rules travel with the tool.
    assert "Redundancy MUST be modelled as redundancy" in tools["create_rbd"].description
    assert "0 = the unit failed" in tools["fit_distribution"].description


# ---- fitting ----------------------------------------------------------------------

def _direct_fit(times, flags, **options):
    from backend import fitting

    df = pd.DataFrame({"x": times, "c": flags})
    return fitting.fit("weibull", df, {"x": "x", "c": "c"}, options=options or None)


def test_fit_inline_censored_matches_fitting(env):
    out = _ok(_call(env.token[A], "fit_distribution", {"data": TIMES, "censored": FLAGS, "unit": "hours"}))
    ref = _direct_fit(TIMES, FLAGS)
    assert out["saved"] is False and out["distribution"] == "Weibull" and out["unit"] == "hours"
    for got, want in zip(out["params"], ref["params"]):
        assert got["name"] == want["name"]
        assert got["value"] == pytest.approx(want["value"], rel=1e-9)
    assert out["gof"]["aic"] == pytest.approx(next(g["value"] for g in ref["gof"] if g["id"] == "aic"))
    assert out["metrics"]["b10"] > 0 and out["metrics"]["mttf"] > out["metrics"]["b10"]
    # Nothing persisted.
    assert env.db.models.count_documents({}) == 0 and env.db.datasets.count_documents({}) == 0


def test_c_invert_flips_the_flags(env):
    inverted = [1 - f for f in FLAGS]
    out = _ok(_call(env.token[A], "fit_distribution", {"data": TIMES, "censored": inverted, "c_invert": True}))
    ref = _direct_fit(TIMES, FLAGS)
    assert [p["value"] for p in out["params"]] == pytest.approx([p["value"] for p in ref["params"]])


def test_fit_errors_are_user_facing(env):
    msg = _err(_call(env.token[A], "fit_distribution", {"data": [100, 200], "censored": [1, 1]}))
    assert "marked as censored" in msg and "Traceback" not in msg
    msg = _err(_call(env.token[A], "fit_distribution", {"data": TIMES, "distribution": "nope"}))
    assert "isn't a supported" in msg


def test_best_fit_reports_the_selection(env):
    out = _ok(_call(env.token[A], "fit_distribution", {"data": TIMES, "censored": FLAGS, "distribution": "best"}))
    assert out["selection"]["criterion"] == "aic" and out["selection"]["candidates"]


def test_save_persists_and_lists_and_matches_rest_reliability(env):
    from backend.main import app

    saved = _ok(_call(env.token[A], "fit_and_save_model", {
        "data": TIMES, "censored": FLAGS, "unit": "hours", "name": "MCP bearings"}))
    mid = saved["model_id"]
    assert saved["saved"] and saved["url"].endswith(f"/modelling/m/{mid}")
    assert env.db.models.find_one({"_id": mid})["owner_id"] == A
    assert env.db.datasets.find_one({"_id": saved["dataset_id"]})["owner_id"] == A

    listed = _ok(_call(env.token[A], "list_models", {"kind": "life"}))
    assert mid in [m["id"] for m in listed["life_models"]]

    detail = _ok(_call(env.token[A], "get_model", {"model_id": mid}))
    assert {p["name"] for p in detail["params"]} == {"alpha", "beta"}
    assert detail["metrics"]["mttf"] > 0

    rel = _ok(_call(env.token[A], "reliability_at", {"model_id": mid, "times": [500, 1000]}))
    client = TestClient(app)
    for point in rel["points"]:
        rest = client.post(f"/api/v1/models/{mid}/reliability",
                           headers={"Authorization": f"Bearer {env.token[A]}"}, json={"t": point["t"]}).json()["at"]
        for key in ("reliability", "failure", "hazard", "cumulative_hazard", "density"):
            assert point[key] == pytest.approx(rest[key])

    cond = _ok(_call(env.token[A], "reliability_at", {"model_id": mid, "times": [200], "conditional_age": 500}))
    r = {p["t"]: p for p in _ok(_call(env.token[A], "reliability_at", {"model_id": mid, "times": [500, 700]}))["points"]}
    assert cond["points"][0]["conditional_reliability"] == pytest.approx(r[700]["reliability"] / r[500]["reliability"])


def test_dataset_upload_then_fit_from_it(env):
    ds = _ok(_call(env.token[A], "upload_dataset", {
        "name": "Pumps", "csv": "hours,failed\n" + "\n".join(f"{t},{c}" for t, c in zip(TIMES, FLAGS))}))
    assert ds["columns"] == ["hours", "failed"] and ds["n_rows"] == len(TIMES)
    assert ds["id"] in [d["id"] for d in _ok(_call(env.token[A], "list_datasets"))["datasets"]]

    msg = _err(_call(env.token[A], "fit_distribution", {"dataset_id": ds["id"]}))
    assert "time_column" in msg and "hours" in msg
    out = _ok(_call(env.token[A], "fit_distribution", {
        "dataset_id": ds["id"], "time_column": "hours", "censor_column": "failed"}))
    ref = _direct_fit(TIMES, FLAGS)
    assert [p["value"] for p in out["params"]] == pytest.approx([p["value"] for p in ref["params"]])


# ---- RBDs --------------------------------------------------------------------------

def test_create_analyze_and_export_rbd(env):
    created = _ok(_call(env.token[A], "create_rbd", {"name": "Pump skid", "unit": "Hours", **GRAPH}))
    rid = created["id"]
    assert created["placeholders"] == ["Pump B"] and created["n_blocks"] == 3
    doc = env.db.rbds.find_one({"_id": rid})
    assert doc["owner_id"] == A and all("position" in n for n in doc["graph"]["nodes"])
    assert doc["graph"]["nodes"][0]["data"]["label"]  # fleshed out for the builder

    # Round trip: get_rbd returns the compact form create_rbd accepts.
    got = _ok(_call(env.token[A], "get_rbd", {"rbd_id": rid}))
    assert {n["id"] for n in got["graph"]["nodes"]} == {"input", "ctl", "p1", "p2", "output"}
    assert next(n for n in got["graph"]["nodes"] if n["id"] == "p2")["model"]["placeholder"] is True

    res = _ok(_call(env.token[A], "analyze_rbd", {"rbd_id": rid, "times": [100, 500]}))
    assert res["kind"] == "non_repairable" and res["available"]
    assert res["mttf"] > 0 and res["b_life"]["b10"] > 0
    assert res["reliability_at"][0]["reliability"] > res["reliability_at"][1]["reliability"]
    assert "Controller" in res["importance"]["birnbaum"]
    assert "placeholder" in res["warning"]

    # Same numbers as the service the REST endpoint calls.
    from backend.services import rbds as rbds_service

    ref = rbds_service.analyze_graph(env.db, doc["graph"], [A])
    assert res["mttf"] == pytest.approx(ref["mttf"])

    script = _ok(_call(env.token[A], "export_rbd_python", {"rbd_id": rid}))
    assert script["filename"].endswith(".py")
    assert "import repyability" in script["script"] or "from repyability" in script["script"]
    compile(script["script"], script["filename"], "exec")

    assert rid in [r["id"] for r in _ok(_call(env.token[A], "list_rbds"))["rbds"]]


def test_create_rbd_rejects_bad_structures(env):
    bad = {"nodes": [n for n in GRAPH["nodes"] if n["id"] != "output"],
           "edges": [e for e in GRAPH["edges"] if e["target"] != "output"]}
    msg = _err(_call(env.token[A], "create_rbd", {"name": "Broken", **bad}))
    assert "Invalid RBD" in msg or "output" in msg.lower()
    msg = _err(_call(env.token[A], "create_rbd", {"name": "Neither"}))
    assert "exactly one" in msg
    assert env.db.rbds.count_documents({"owner_id": A}) == 0


REPAIRABLE_STAGES = [
    {"label": "Drive", "components": [{
        "label": "Motor", "distribution": "weibull",
        "params": [{"name": "alpha", "value": 2000}, {"name": "beta", "value": 1.5}],
        "repair_distribution": "lognormal",
        "repair_params": [{"name": "mu", "value": 1.5}, {"name": "sigma", "value": 0.4}]}]},
    {"label": "Pumps", "components": [
        {"label": f"Pump {s}", "distribution": "weibull",
         "params": [{"name": "alpha", "value": 900}, {"name": "beta", "value": 1.2}],
         "repair_distribution": "lognormal",
         "repair_params": [{"name": "mu", "value": 1.0}, {"name": "sigma", "value": 0.3}]}
        for s in "AB"]},
]


def test_repairable_analysis_follows_the_paid_gate_and_cache(env, monkeypatch):
    from backend.services import billing as billing_service

    created = _ok(_call(env.token[A], "create_rbd", {
        "name": "Duty/standby pumps", "repairable": True, "stages": REPAIRABLE_STAGES}))
    rid = created["id"]
    assert created["repairable"] is True

    # API access but no premium compute: the exact figures (#154), and a clear
    # message for the simulation, not an error.
    monkeypatch.setattr(billing_service, "premium_compute_allowed", lambda db, user: False)
    denied = _call(env.token[A], "analyze_rbd", {"rbd_id": rid})
    out = _ok(denied)
    assert out["available"] is True and out["has_simulation"] is False
    assert out["exact"]["status"] == "ok" and 0 < out["exact"]["mission_availability"] <= 1
    assert out["simulation"]["available"] is False and out["simulation"]["code"] == "pro_required"
    assert "Pro" in out["simulation"]["message"]
    assert not env.db.rbds.find_one({"_id": rid}).get("availability_cache")

    # Entitled: computes and stores the result on the owner's diagram.
    monkeypatch.setattr(billing_service, "premium_compute_allowed", lambda db, user: True)
    out = _ok(_call(env.token[A], "analyze_rbd", {"rbd_id": rid}))
    assert out["available"] and out["kind"] == "repairable"
    assert 0 < out["steady_state_availability"] <= 1 and out["cached"] is False
    assert env.db.rbds.find_one({"_id": rid}).get("availability_cache")

    # Entitlement lapses: the saved result is still served.
    monkeypatch.setattr(billing_service, "premium_compute_allowed", lambda db, user: False)
    out = _ok(_call(env.token[A], "analyze_rbd", {"rbd_id": rid}))
    assert out["available"] and out["steady_state_availability"] > 0 and out["can_recompute"] is False


# ---- calculators --------------------------------------------------------------------

def test_calculators_match_the_strategy_service(env):
    from backend.services import strategy_store

    params = [{"name": "alpha", "value": 1200.0}, {"name": "beta", "value": 2.5}]
    out = _ok(_call(env.token[A], "optimal_replacement", {
        "distribution_id": "weibull", "params": params, "planned_cost": 100, "unplanned_cost": 1000}))
    ref = strategy_store.compute("optimal_replacement", {
        "distribution_id": "weibull", "params": params, "planned_cost": 100, "unplanned_cost": 1000, "unit": ""})
    assert out["beneficial"] == ref["beneficial"] and out["beneficial"]

    ff = _ok(_call(env.token[A], "failure_finding_interval", {
        "distribution_id": "exponential", "params": [{"name": "failure_rate", "value": 1e-4}],
        "target_availability": 0.99}))
    assert ff  # shape is the calculator's own

    msg = _err(_call(env.token[A], "optimal_replacement", {"planned_cost": 1, "unplanned_cost": 2}))
    assert "model_id" in msg


def test_calculators_use_a_saved_models_extras(env):
    """A saved model's offset / LFP fraction reach the calculators, as in the
    app: an LFP wear-out model is run-to-failure, an offset lengthens the
    failure-finding interval."""
    from backend.services import strategy

    weib = [{"name": "alpha", "value": 1000.0}, {"name": "beta", "value": 3.0}]
    lfp = _ok(_call(env.token[A], "save_model", {
        "name": "LFP pumps", "distribution": "weibull", "params": weib + [{"name": "p", "value": 0.6}]}))
    out = _ok(_call(env.token[A], "optimal_replacement", {
        "model_id": lfp["model_id"], "planned_cost": 100, "unplanned_cost": 1000}))
    assert out["beneficial"] is False and "40% of units never fail" in out["recommendation"]

    rate = [{"name": "failure_rate", "value": 1e-3}]
    off = _ok(_call(env.token[A], "save_model", {
        "name": "Offset relief valve", "distribution": "exponential",
        "params": rate + [{"name": "gamma", "value": 500.0}]}))
    ff = _ok(_call(env.token[A], "failure_finding_interval", {
        "model_id": off["model_id"], "target_availability": 0.99}))
    ref = strategy.failure_finding("exponential", rate, 0.99, extras={"gamma": 500.0})
    assert ff["interval"] == pytest.approx(ref["interval"])
    assert ff["interval"] > strategy.failure_finding("exponential", rate, 0.99)["interval"]


def test_plan_demonstration_test(env):
    out = _ok(_call(env.token[A], "plan_demonstration_test", {
        "reliability": 0.95, "confidence": 0.95, "mission_time": 1000, "unit": "hours"}))
    assert out["units"] == 59 and out["solve_for"] == "units"
    assert out["summary"] == (
        "Test 59 units for 1,000 hours each with no failures to show R(1,000 hours) ≥ 95% at 95% confidence.")
    assert out["assumptions"] and out["tradeoff"]["cells"] == "Units to test"
    assert out["tradeoff"]["columns"] == "allowed failures 0, 1, 2, 3"
    assert out["tradeoff"]["rows"] == {"1,000 hours (1×)": [59, 93, 124, 153]}
    assert "rows" not in out["tradeoff"]["rows"] and "curve" not in out  # lean: no plotting fields

    # Weibayes: test twice as long with a known shape, fewer units; the same plan the app computes.
    ext = _ok(_call(env.token[A], "plan_demonstration_test", {
        "reliability": 0.95, "mission_time": 1000, "test_multiple": 2, "shape": 2, "unit": "hours"}))
    assert ext["units"] == 15 and ext["test_time_per_unit"] == 2000
    assert ext["tradeoff"]["rows"]["2,000 hours (2×)"] == [15, 24, 32, 40]

    # Units given: solve for the test time per unit.
    tt = _ok(_call(env.token[A], "plan_demonstration_test", {
        "reliability": 0.95, "mission_time": 1000, "shape": 2, "units": 20, "unit": "hours"}))
    assert tt["solve_for"] == "test_time" and round(tt["test_time_per_unit"]) == 1709

    mtbf = _ok(_call(env.token[A], "plan_demonstration_test", {"method": "mtbf", "mtbf": 1000, "unit": "hours"}))
    assert round(mtbf["total_test_time"]) == 2996 and mtbf["summary"].startswith("Run 2,996 hours")

    assert "Weibull shape" in _err(_call(env.token[A], "plan_demonstration_test", {
        "reliability": 0.95, "test_multiple": 2}))
    assert "Target reliability" in _err(_call(env.token[A], "plan_demonstration_test", {}))


def test_optimal_overhaul_uses_a_recurrent_model(env):
    from backend.services import recurrent as recurrent_service

    doc = recurrent_service.save_from_params(
        env.db, "Compressors", "crow_amsaa",
        [{"name": "alpha", "value": 1000}, {"name": "beta", "value": 2}], 5000, "hours", A)
    out = _ok(_call(env.token[A], "optimal_overhaul", {"model_id": doc.id, "cost_repair": 100, "cost_overhaul": 1000}))
    assert out
    assert doc.id in [m["id"] for m in _ok(_call(env.token[A], "list_models", {"kind": "recurrent"}))["recurrent_models"]]
    msg = _err(_call(env.token[A], "optimal_overhaul", {"model_id": "nope", "cost_repair": 1, "cost_overhaul": 2}))
    assert "Recurrent model not found" in msg


# ---- scoping -------------------------------------------------------------------------

def test_a_non_parametric_model_is_no_rbd_block(env):
    """RePyability 0.12 refuses a non-parametric node: create_rbd says to fit a
    parametric distribution instead."""
    km = _ok(_call(env.token[A], "fit_and_save_model", {
        "data": TIMES, "censored": FLAGS, "distribution": "kaplan_meier", "name": "KM bearings"}))
    graph = {**GRAPH, "nodes": [
        {**n, "model": {"saved_model_id": km["model_id"]}} if n["id"] == "ctl" else n for n in GRAPH["nodes"]]}
    msg = _err(_call(env.token[A], "create_rbd", {"name": "Empirical", **graph}))
    assert "non-parametric" in msg and "Fit a parametric distribution" in msg


def test_users_cannot_read_each_others_artifacts(env):
    model = _ok(_call(env.token[A], "fit_and_save_model", {
        "data": TIMES, "censored": FLAGS, "name": "A's model"}))
    rbd = _ok(_call(env.token[A], "create_rbd", {"name": "A's RBD", **GRAPH}))

    b = env.token[B]
    assert "not found" in _err(_call(b, "get_model", {"model_id": model["model_id"]})).lower()
    assert "not found" in _err(_call(b, "reliability_at", {"model_id": model["model_id"], "times": [1]})).lower()
    assert "not found" in _err(_call(b, "get_rbd", {"rbd_id": rbd["id"]})).lower()
    assert "not found" in _err(_call(b, "analyze_rbd", {"rbd_id": rbd["id"]})).lower()
    assert "not found" in _err(_call(b, "export_rbd_python", {"rbd_id": rbd["id"]})).lower()
    assert "not found" in _err(_call(b, "fit_distribution", {
        "dataset_id": model["dataset_id"], "time_column": "x"})).lower()
    assert "not found" in _err(_call(b, "optimal_replacement", {
        "model_id": model["model_id"], "planned_cost": 1, "unplanned_cost": 5})).lower()
    ids = [m["id"] for m in _ok(_call(b, "list_models"))["life_models"]]
    assert model["model_id"] not in ids
    assert rbd["id"] not in [r["id"] for r in _ok(_call(b, "list_rbds"))["rbds"]]
    assert model["dataset_id"] not in [d["id"] for d in _ok(_call(b, "list_datasets"))["datasets"]]

    # B can't smuggle A's saved model into a diagram of their own either.
    graph = {**GRAPH, "nodes": [
        {**n, "model": {"saved_model_id": model["model_id"]}} if n["id"] == "ctl" else n for n in GRAPH["nodes"]]}
    assert "not found" in _err(_call(b, "create_rbd", {"name": "Sneaky", **graph})).lower()
    # ... while A can.
    ok = _ok(_call(env.token[A], "create_rbd", {"name": "Linked", **graph, "include_graph": True}))
    ctl = next(n for n in ok["graph"]["nodes"] if n["id"] == "ctl")
    assert ctl["model"]["saved_model_id"] == model["model_id"]
