"""Every MCP tool action over REST (backend/routers/api_tools.py): the same
calls, gating and results as over MCP, an OpenAPI spec of them, and the
parity check that keeps MCP, REST, the spec and the CLI in step."""

import matplotlib

matplotlib.use("Agg")

import io
import os
import sys

import mongomock
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from backend.tests.test_mcp import _ok, _run

A, B, FREE, OP = "user-a", "user-b", "user-free", "user-op"
USERS = {
    A: {"_id": A, "email": "a@example.org", "name": "A", "plan": "pro", "email_verified": True},
    B: {"_id": B, "email": "b@example.org", "name": "B", "plan": "pro", "email_verified": True},
    FREE: {"_id": FREE, "email": "free@example.org", "name": "Free", "email_verified": True},
    OP: {"_id": OP, "email": "op@example.org", "name": "Op", "email_verified": True},
}
WEIBULL = [{"name": "alpha", "value": 1200.0}, {"name": "beta", "value": 2.5}]
FIT = {"data": [120, 340, 510, 700, 980, 1200, 1500], "censored": [0, 0, 1, 0, 0, 1, 0]}

pytestmark = pytest.mark.usefixtures("mcp_on")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "python"))


@pytest.fixture()
def env(monkeypatch):
    from backend import config, db
    from backend.routers import ingest as ingest_router
    from backend.services import rbd_analysis, tokens

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    monkeypatch.setattr(config, "ADMIN_EMAILS", set())
    monkeypatch.setattr(rbd_analysis, "_AVAIL_SIMS", 20)
    test_db = mongomock.MongoClient()["reliafy_api_tools"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    ingest_router._hits.clear()
    for u in USERS.values():
        test_db.users.insert_one(dict(u))

    class Env:
        db = test_db
        token = {uid: tokens.create_token(test_db, uid, "api")["token"] for uid in USERS}
        read_only = tokens.create_token(test_db, A, "ro", ["read"])["token"]
        ingest_only = tokens.create_token(test_db, A, "ingest", ["ingest"])["token"]
        client = TestClient(__import__("backend.main", fromlist=["app"]).app)

        @classmethod
        def post(cls, path, body=None, uid=A, token=None, **kw):
            headers = {"Authorization": f"Bearer {token or cls.token[uid]}"}
            return cls.client.post(path, json=body if body is not None else {}, headers=headers, **kw)

    return Env


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


# ---- auth ------------------------------------------------------------------------

def test_auth_is_the_mcp_model(env):
    c = env.client
    assert c.post("/api/v1/list/models", json={}).status_code == 401
    assert c.post("/api/v1/list/models", json={}, headers=_auth("rlf_nope")).status_code == 401
    r = c.post("/api/v1/list/models", json={}, headers=_auth(env.ingest_only))
    assert r.status_code == 403 and "ingest" in r.json()["detail"]
    assert env.post("/api/v1/list/models").status_code == 200
    # A read-only token reads and calculates but can't write.
    assert env.post("/api/v1/strategy/optimal_replacement", {
        "distribution_id": "weibull", "params": WEIBULL, "planned_cost": 100, "unplanned_cost": 1000},
        token=env.read_only).status_code == 200
    r = env.post("/api/v1/models/save", {"name": "x", "distribution": "weibull", "params": WEIBULL},
                 token=env.read_only)
    assert r.status_code == 403 and "write" in r.json()["detail"]


def test_a_token_without_api_access_is_402_and_a_free_session_gets_the_allowance(env, monkeypatch):
    from backend import auth, config

    monkeypatch.setattr(config, "BILLING_ENABLED", True)
    r = env.post("/api/v1/list/models", uid=FREE)
    assert r.status_code == 402 and "Pro" in r.json()["detail"]
    assert env.post("/api/v1/list/models", uid=A).status_code == 200  # Pro

    # Signed in as a Free user (a session, not a token): the Free allowance, as over MCP.
    monkeypatch.setattr(auth, "_verified_claims", lambda token: {
        "uid": FREE, "email": "free@example.org", "email_verified": True})
    monkeypatch.setattr(config, "MCP_FREE_MONTHLY_CALLS", 2)
    session = {"Authorization": "Bearer firebase-id-token"}
    r = env.client.post("/api/v1/life_data_analysis/fit", json=FIT, headers=session)
    assert r.status_code == 402 and "Pro" in r.json()["detail"]  # fitting is Pro-only, not counted
    assert env.client.post("/api/v1/guide", json={}, headers=session).status_code == 200  # never counted
    assert env.client.post("/api/v1/list/models", json={}, headers=session).status_code == 200
    assert env.client.post("/api/v1/list/datasets", json={}, headers=session).status_code == 200
    r = env.client.post("/api/v1/list/rbds", json={}, headers=session)
    assert r.status_code == 429 and "2" in r.json()["detail"]


def test_operators_and_self_hosted_have_everything(env, monkeypatch):
    from backend import config

    monkeypatch.setattr(config, "BILLING_ENABLED", True)
    monkeypatch.setattr(config, "ADMIN_EMAILS", {"op@example.org"})
    assert env.post("/api/v1/life_data_analysis/fit", FIT, uid=OP).status_code == 200
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    monkeypatch.setattr(config, "AUTH_DISABLED", True)
    assert env.client.post("/api/v1/life_data_analysis/fit", json=FIT).status_code == 200  # no token needed


# ---- calls -----------------------------------------------------------------------

GRAPH = {"nodes": [{"id": "input", "type": "input"},
                   {"id": "p1", "type": "component", "label": "P1",
                    "model": {"distribution_id": "weibull", "params": WEIBULL}},
                   {"id": "p2", "type": "component", "label": "P2",
                    "model": {"distribution_id": "weibull", "params": WEIBULL}},
                   {"id": "output", "type": "output"}],
         "edges": [{"source": "input", "target": "p1"}, {"source": "input", "target": "p2"},
                   {"source": "p1", "target": "output"}, {"source": "p2", "target": "output"}]}


def test_results_are_the_mcp_results(env):
    mid = env.post("/api/v1/models/save", {"name": "Handbook", "distribution": "weibull",
                                           "params": WEIBULL}).json()["model_id"]
    rid = env.post("/api/v1/rbd/create", {"name": "Two pumps", **GRAPH}).json()["id"]
    calls = [
        ("guide", None, {"topic": "units"}),
        ("list", "models", {}),
        ("get", "model", {"id": mid}),
        ("life_data_analysis", "reliability_at", {"model_id": mid, "times": [100, 500]}),
        ("life_data_analysis", "fit", FIT),
        ("strategy", "optimal_replacement", {"distribution_id": "weibull", "params": WEIBULL,
                                             "planned_cost": 100, "unplanned_cost": 1000}),
        ("rbd_analysis", "analyze", {"rbd_id": rid}),
    ]

    async def over_mcp(client):
        out = []
        for tool, action, args in calls:
            sel = {"get": "kind", "list": "kind"}.get(tool, "action")
            out.append(_ok(await client.call_tool(tool, {**args, **({sel: action} if action else {})})))
        return out

    via_mcp = _run(env.token[A], over_mcp)
    for (tool, action, args), expected in zip(calls, via_mcp):
        r = env.post(f"/api/v1/{tool}" + (f"/{action}" if action else ""), args)
        assert r.status_code == 200, r.text
        got = r.json()
        for volatile in ("computed_at", "updated_at", "ran_at"):
            got.pop(volatile, None), expected.pop(volatile, None)
        assert got == expected, (tool, action)


def test_a_sample_of_every_tool(env):
    ds = env.post("/api/v1/datasets/upload", {"name": "Bearings", "csv": "hours,c\n120,0\n340,0\n510,1\n700,0"})
    assert ds.status_code == 200, ds.text
    saved = env.post("/api/v1/models/save", {"name": "Handbook", "distribution": "weibull", "params": WEIBULL})
    assert saved.status_code == 200 and saved.json()["model_id"]
    mid = saved.json()["model_id"]
    assert env.post("/api/v1/life_data_analysis/reliability_at", {"model_id": mid, "times": [500]}).status_code == 200
    r = env.post("/api/v1/repairable_analysis/next_failure", {"model_id": "nope", "age": 10})
    assert r.status_code == 404 and "not found" in r.json()["detail"]
    rbd = env.post("/api/v1/rbd/create", {"name": "Two pumps", **GRAPH})
    assert rbd.status_code == 200, rbd.text
    up = env.post("/api/v1/uploads/create", {"purpose": "dataset", "filename": "x.csv"})
    assert up.status_code == 200 and up.json()["upload_id"]
    assert env.post("/api/v1/rcm/create", {"name": "Pump RCM"}).status_code == 200
    link = env.post("/api/v1/sharing/create_link", {"kind": "model", "id": mid})
    assert link.status_code == 200, link.text
    r = env.post("/api/v1/fleet/create_alert", {"fleet_id": "nope", "kind": "above", "threshold": 2})
    assert r.status_code in (404, 422) and "fleet" in r.json()["detail"].lower(), r.text  # a one-action tool
    assert env.post("/api/v1/upgrade_link").status_code in (200, 422)
    assert env.post("/api/v1/models/delete", {"model_id": mid}).status_code == 200
    # Scoped like MCP: B can't see A's dataset.
    assert env.post("/api/v1/get/dataset", {"id": ds.json()["id"]}, uid=B).status_code == 404


def test_errors(env):
    r = env.post("/api/v1/nosuch/thing")
    assert r.status_code == 404 and "/api/v1/tools" in r.json()["detail"]
    r = env.post("/api/v1/get/nope")
    assert r.status_code == 404 and "model" in r.json()["detail"]
    r = env.post("/api/v1/life_data_analysis/fit", {"data": "x"})
    assert r.status_code == 422 and r.json()["detail"].startswith("data:")
    r = env.post("/api/v1/strategy/optimal_replacement", {"distribution_id": "weibull", "params": WEIBULL})
    assert r.status_code == 422 and "needs planned_cost" in r.json()["detail"]
    r = env.post("/api/v1/get/model", {"kind": "rbd", "id": "x"})
    assert r.status_code == 422 and "path" in r.json()["detail"]
    r = env.post("/api/v1/get/model", {"id": "nope"})
    assert r.status_code == 404 and "not found" in r.json()["detail"]
    r = env.client.post("/api/v1/list/models", content=b"[1]", headers=_auth(env.token[A]))
    assert r.status_code == 422
    assert env.post("/api/v1/guide/x").status_code == 404
    assert env.post("/api/v1/list").status_code == 404


def test_heavy_calls_share_the_mcp_heavy_slots(env, monkeypatch):
    from backend import mcp_server

    monkeypatch.setattr(mcp_server, "MCP_USER_HEAVY", 0)
    r = env.post("/api/v1/life_data_analysis/fit", FIT)
    assert r.status_code == 429 and "running at once" in r.json()["detail"]
    assert env.post("/api/v1/list/models").status_code == 200  # not heavy


def test_long_running_jobs_answer_with_a_job_id_to_poll(env):
    from backend.services import rbd_jobs

    job = rbd_jobs.create(env.db, uid=A, kind=rbd_jobs.KIND_SENSITIVITY, request={}, cache_key="k",
                          rbd_id="sample-rbd-pump-station", quick=False, store=False)
    r = env.post("/api/v1/get/job", {"id": job["_id"]})
    assert r.status_code == 200 and r.json()["status"] == "queued" and r.json()["job_id"] == job["_id"]
    rbd_jobs.finish(env.db, job["_id"], "failed", error="Stopped.")
    assert env.post("/api/v1/get/job", {"id": job["_id"]}).json()["status"] == "failed"
    assert env.post("/api/v1/get/job", {"id": job["_id"]}, uid=B).status_code == 404


def test_calls_are_logged_on_the_api_channel(env, monkeypatch):
    from backend.services import usage

    monkeypatch.setattr(usage, "enabled", lambda: True)
    env.post("/api/v1/list/models")
    events = list(env.db.usage_events.find({"uid": A, "feature": "list.models"}))
    assert [e["channel"] for e in events] == ["api"]


def test_the_old_routes_are_unchanged(env):
    # The fixed /api/v1 routes are mounted first: the generic ones never shadow them.
    r = env.client.post("/api/v1/strategy/optimal-replacement", headers=_auth(env.token[A]), json={
        "distribution_id": "weibull", "params": [1200, 2.5], "planned_cost": 100, "unplanned_cost": 1000})
    assert r.status_code == 200 and "optimal_time" in r.json()
    r = env.client.get("/api/v1/models", headers=_auth(env.token[A]))
    assert r.status_code == 200 and set(r.json()) == {"models"}
    r = env.client.post("/api/v1/datasets", headers=_auth(env.token[A]), json={
        "name": "D", "csv": "hours,failed\n120,1\n340,1\n510,0\n700,1"})
    assert r.status_code == 200 and r.json()["n_rows"] == 4
    mid = env.post("/api/v1/models/save", {"name": "H", "distribution": "weibull", "params": WEIBULL}).json()["model_id"]
    r = env.client.get(f"/api/v1/models/{mid}", headers=_auth(env.token[A]))
    assert r.status_code == 200 and r.json()["id"] == mid


# ---- maintenance: operators (and its users) only, as over MCP -------------------------------

@pytest.fixture()
def maint(env, monkeypatch, tmp_path):
    from backend import config
    from backend.maintenance import mcp_tools, photos
    from backend.maintenance.service import PROJECTORS
    from backend.maintenance.store import GraphStore
    from backend.routers import maintenance as router

    monkeypatch.setattr(config, "MAINTENANCE_ENABLED", True)
    monkeypatch.setattr(config, "MAINTENANCE_EMAILS", {"a@example.org"})
    monkeypatch.setattr(router, "_store", GraphStore(":memory:", PROJECTORS))
    monkeypatch.setattr(router, "_photo_store", photos.FilePhotoStore(str(tmp_path)))
    mcp_tools.register()
    yield env
    mcp_tools.unregister()


def test_maintenance_tools_only_for_its_users(maint):
    r = maint.post("/api/v1/maintenance_overview")
    assert r.status_code == 200 and "summary" in r.json()
    assert maint.post("/api/v1/maintenance_overview", uid=B).status_code == 404
    pos = maint.post("/api/v1/maintenance_positions/create", {"name": "Pump A"})
    assert pos.status_code == 200, pos.text
    tools_a = {t["name"] for t in maint.client.get("/api/v1/tools", headers=_auth(maint.token[A])).json()["tools"]}
    tools_b = {t["name"] for t in maint.client.get("/api/v1/tools", headers=_auth(maint.token[B])).json()["tools"]}
    assert "maintenance_positions" in tools_a and not any(t.startswith("maintenance_") for t in tools_b)
    assert "maintenance_graph_query" not in tools_a  # graph queries: a narrower audience still
    spec_b = maint.client.get("/api/v1/openapi.json", headers=_auth(maint.token[B])).json()
    assert not any("/maintenance_" in p for p in spec_b["paths"])


def _jpeg() -> bytes:
    img = Image.new("RGB", (320, 240), (200, 30, 30))
    exif = Image.Exif()
    exif[0x010F] = "PhoneCo"
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif)
    return buf.getvalue()


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), (10, 200, 10)).save(buf, "PNG")
    return buf.getvalue()


def test_photos_over_the_api(maint, monkeypatch):
    from backend import config
    from backend.maintenance import photos
    from backend.services import usage

    pid = maint.post("/api/v1/maintenance_positions/create", {"name": "Pump A"}).json()["id"]
    hdr = {**_auth(maint.token[A]), "Content-Type": "image/jpeg"}
    r = maint.client.post(f"/api/v1/maintenance/photos?target_id={pid}&caption=Front", content=_jpeg(), headers=hdr)
    assert r.status_code == 200, r.text
    photo_id = r.json()["photo"]["id"]
    from backend.routers.maintenance import get_photo_store

    stored = Image.open(io.BytesIO(get_photo_store().get(photo_id, "full")))
    assert len(stored.getexif()) == 0  # EXIF stripped
    files = {"file": ("p.png", _png(), "image/png")}
    r = maint.client.post(f"/api/v1/maintenance/photos?target_id={pid}", files=files, headers=_auth(maint.token[A]))
    assert r.status_code == 200, r.text
    view = maint.post("/api/v1/maintenance_view_photo", {"photo_id": photo_id})
    assert view.status_code == 200 and view.json()["content"][0]["type"] == "image"

    bad = maint.client.post(f"/api/v1/maintenance/photos?target_id={pid}", content=b"%PDF nope", headers=hdr)
    assert bad.status_code == 422
    monkeypatch.setattr(photos, "MAX_UPLOAD_BYTES", 1000)
    big = maint.client.post(f"/api/v1/maintenance/photos?target_id={pid}", content=_jpeg(), headers=hdr)
    assert big.status_code == 413
    monkeypatch.setattr(photos, "MAX_UPLOAD_BYTES", 20 * 1024 * 1024)

    # Gating as on the session route: not a Maintenance user → 404; a read-only token → 403;
    # a token on an account without API access → 402.
    assert maint.client.post(f"/api/v1/maintenance/photos?target_id={pid}", content=_jpeg(),
                             headers={**_auth(maint.token[B]), "Content-Type": "image/jpeg"}).status_code == 404
    assert maint.client.post(f"/api/v1/maintenance/photos?target_id={pid}", content=_jpeg(),
                             headers={**_auth(maint.read_only), "Content-Type": "image/jpeg"}).status_code == 403
    monkeypatch.setattr(config, "BILLING_ENABLED", True)
    maint.db.users.update_one({"_id": A}, {"$unset": {"plan": 1}})
    assert maint.client.post(f"/api/v1/maintenance/photos?target_id={pid}", content=_jpeg(),
                             headers=hdr).status_code == 402
    monkeypatch.setattr(config, "ADMIN_EMAILS", {"a@example.org"})  # an operator
    monkeypatch.setattr(usage, "enabled", lambda: True)
    assert maint.client.post(f"/api/v1/maintenance/photos?target_id={pid}", content=_jpeg(),
                             headers=hdr).status_code == 200


# ---- the spec and the parity check ---------------------------------------------------------

def _registry(user):
    """Every (tool, action) registered on the MCP server that ``user`` sees."""
    import anyio

    from backend.routers import api_tools

    tools = anyio.run(api_tools.visible_tools, user)
    return tools, {(t.name, a or None) for t in tools for a in api_tools.actions_of(t)}


def test_parity_every_mcp_action_has_rest_openapi_and_cli(maint, monkeypatch):
    """Fails when an MCP tool action has no REST route, no OpenAPI entry or no
    CLI command: they must never drift apart again."""
    import anyio

    from backend import config
    from backend.mcp_server import mcp
    from backend.routers import api_tools
    from reliafy import cli

    monkeypatch.setattr(config, "GRAPH_QUERY_EMAILS", {"a@example.org"})  # everything visible
    user = {"uid": A, "email": "a@example.org", "email_verified": True}
    tools, actions = _registry(user)
    every = anyio.run(mcp.list_tools)
    assert {t.name for t in tools} == {t.name for t in every}, "a registered MCP tool is hidden from REST"
    assert len(actions) > 150
    # Checked against the action tables themselves, not only what the REST layer derives.
    from backend import mcp_server
    from backend.maintenance import mcp_tools

    tables = {**mcp_server.TABLES, **{k: v for k, v in mcp_tools.TABLES.items() if k in mcp_tools.TOOL_NAMES}}
    from_tables = {(tool, a) for tool, (_, table) in tables.items() for a in table}
    assert from_tables - actions == set(), "MCP actions REST doesn't route"
    assert {t for t, a in actions if a is None} == {t.name for t in tools if t.name not in tables}

    spec = maint.client.get("/api/v1/openapi.json", headers=_auth(maint.token[A])).json()
    in_spec = set(cli.operations(spec))
    assert actions - in_spec == set(), "MCP actions missing from the OpenAPI spec"
    assert in_spec - actions == set()
    commands = set(cli.commands_from_spec(spec))
    assert {f"{t} {a}" if a else t for t, a in actions} == commands, "MCP actions the CLI can't list"
    listing = maint.client.get("/api/v1/tools", headers=_auth(maint.token[A])).json()
    listed = {(t["name"], a["action"]) for t in listing["tools"] for a in t["actions"]}
    assert listed == actions
    # Every one has a REST route: the generic layer answers it (its own 401 for a bad token,
    # not a routing 404/405 or another route's).
    for tool, action in actions:
        path = f"/api/v1/{tool}/{action}" if action else f"/api/v1/{tool}"
        r = maint.client.post(path, json={}, headers=_auth("rlf_not-a-token"))
        assert (r.status_code, r.json()["detail"]) == (401, "Invalid, expired or revoked token."), path

    # REST/CLI-only capabilities are an explicit allow-list, in the spec and the listing.
    rest_only = {op["operationId"] for item in spec["paths"].values() for op in item.values()
                 if op.get("x-reliafy-rest-only")}
    assert rest_only == set(api_tools.REST_ONLY)
    assert {r["name"] for r in listing["rest_only"]} == set(api_tools.REST_ONLY)


def test_spec_is_valid_and_public_safe(env):
    spec = env.client.get("/api/v1/openapi.json").json()  # no credentials: the core tools
    assert spec["openapi"].startswith("3.1")
    assert "/api/v1/life_data_analysis/fit" in spec["paths"]
    assert not any(p.startswith("/api/v1/maintenance_") for p in spec["paths"])
    schemas = spec["components"]["schemas"]
    import json
    import re

    text = json.dumps(spec)
    for ref in set(re.findall(r'"\$ref": "#/components/schemas/([^"]+)"', text)):
        assert ref in schemas, ref
    assert "#/$defs/" not in text
    # Built only from the public tool definitions: no private names.
    for word in ("accelerator", "mojo", "planning repo", "partner"):
        assert word not in text.lower(), word
    op = spec["paths"]["/api/v1/life_data_analysis/fit"]["post"]
    assert op["x-reliafy-pro-only"] and op["x-reliafy-heavy"] and op["x-reliafy-scope"] == "read"


def test_report_a_problem_and_check_it(env):
    r = env.post("/api/v1/report_problem/report", {"kind": "missing_capability", "summary": "No way to undo a fit",
                                                   "tool": "models", "trying": "refit with other columns"})
    assert r.status_code == 200, r.text
    rid = r.json()["report_id"]
    assert env.post("/api/v1/report_problem/status", {"report_id": rid}).json()["status"] == "new"
    assert env.post("/api/v1/report_problem/status", {"report_id": rid}, uid=B).status_code == 404
    # Only operators triage or update.
    assert env.post("/api/v1/report_problem/update", {"report_id": rid, "status": "fixed"}).status_code in (400, 403, 422)
    assert env.post("/api/v1/report_problem/triage").status_code in (400, 403, 422)
