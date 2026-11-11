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
    assert env.post("/api/v1/analyse/optimal_replacement", {
        "distribution_id": "weibull", "params": WEIBULL, "planned_cost": 100, "unplanned_cost": 1000},
        token=env.read_only).status_code == 200
    r = env.post("/api/v1/change/model_save", {"name": "x", "distribution": "weibull", "params": WEIBULL},
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
    r = env.client.post("/api/v1/analyse/fit", json=FIT, headers=session)
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
    assert env.post("/api/v1/analyse/fit", FIT, uid=OP).status_code == 200
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    monkeypatch.setattr(config, "AUTH_DISABLED", True)
    assert env.client.post("/api/v1/analyse/fit", json=FIT).status_code == 200  # no token needed


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
    mid = env.post("/api/v1/change/model_save", {"name": "Handbook", "distribution": "weibull",
                                                 "params": WEIBULL}).json()["model_id"]
    rid = env.post("/api/v1/change/rbd_create", {"name": "Two pumps", **GRAPH}).json()["id"]
    assert env.post("/api/v1/rbd/create", {"name": "x", **GRAPH}).status_code == 404  # earlier names are gone
    calls = [
        ("guide", None, {"topic": "units"}),
        ("list", "models", {}),
        ("get", "model", {"id": mid}),
        ("analyse", "reliability_at", {"model_id": mid, "times": [100, 500]}),
        ("analyse", "fit", FIT),
        ("analyse", "optimal_replacement", {"distribution_id": "weibull", "params": WEIBULL,
                                             "planned_cost": 100, "unplanned_cost": 1000}),
        ("analyse", "rbd", {"rbd_id": rid}),
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
    ds = env.post("/api/v1/change/dataset_upload", {"name": "Bearings", "csv": "hours,c\n120,0\n340,0\n510,1\n700,0"})
    assert ds.status_code == 200, ds.text
    saved = env.post("/api/v1/change/model_save", {"name": "Handbook", "distribution": "weibull", "params": WEIBULL})
    assert saved.status_code == 200 and saved.json()["model_id"]
    mid = saved.json()["model_id"]
    assert env.post("/api/v1/analyse/reliability_at", {"model_id": mid, "times": [500]}).status_code == 200
    r = env.post("/api/v1/analyse/next_failure", {"model_id": "nope", "age": 10})
    assert r.status_code == 404 and "not found" in r.json()["detail"]
    rbd = env.post("/api/v1/change/rbd_create", {"name": "Two pumps", **GRAPH})
    assert rbd.status_code == 200, rbd.text
    up = env.post("/api/v1/change/upload_create", {"purpose": "dataset", "filename": "x.csv"})
    assert up.status_code == 200 and up.json()["upload_id"]
    link = env.post("/api/v1/change/share_link", {"kind": "model", "id": mid})
    assert link.status_code == 200, link.text
    r = env.post("/api/v1/change/fleet_create_alert", {"fleet_id": "nope", "kind": "above", "threshold": 2})
    assert r.status_code in (404, 422) and "fleet" in r.json()["detail"].lower(), r.text  # a one-action tool
    assert env.post("/api/v1/get/upgrade_link").status_code in (200, 422)
    assert env.post("/api/v1/change/model_delete", {"model_id": mid}).status_code == 200
    # Scoped like MCP: B can't see A's dataset.
    assert env.post("/api/v1/get/dataset", {"id": ds.json()["id"]}, uid=B).status_code == 404


def test_errors(env):
    r = env.post("/api/v1/nosuch/thing")
    assert r.status_code == 404 and "/api/v1/tools" in r.json()["detail"]
    r = env.post("/api/v1/get/nope")
    assert r.status_code == 404 and "model" in r.json()["detail"]
    r = env.post("/api/v1/analyse/fit", {"data": "x"})
    assert r.status_code == 422 and "data: Input should be a valid list" in r.json()["detail"]
    assert "args" not in r.json()["detail"]  # over REST the arguments are the body
    r = env.post("/api/v1/analyse/optimal_replacement", {"distribution_id": "weibull", "params": WEIBULL})
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
    r = env.post("/api/v1/analyse/fit", FIT)
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
    mid = env.post("/api/v1/change/model_save", {"name": "H", "distribution": "weibull", "params": WEIBULL}).json()["model_id"]
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
    r = maint.post("/api/v1/maintenance/overview")
    assert r.status_code == 200 and "summary" in r.json()
    assert maint.post("/api/v1/maintenance/overview", uid=B).status_code == 404
    pos = maint.post("/api/v1/maintenance/positions.create", {"name": "Pump A"})
    assert pos.status_code == 200, pos.text
    tools_a = {t["name"] for t in maint.client.get("/api/v1/tools", headers=_auth(maint.token[A])).json()["tools"]}
    tools_b = {t["name"] for t in maint.client.get("/api/v1/tools", headers=_auth(maint.token[B])).json()["tools"]}
    assert "maintenance" in tools_a and not any(t.startswith("maintenance") for t in tools_b)
    spec_a = maint.client.get("/api/v1/openapi.json", headers=_auth(maint.token[A])).json()
    assert "/api/v1/maintenance/positions.create" in spec_a["paths"]
    assert "/api/v1/maintenance/graph_query" not in spec_a["paths"]  # graph queries: a narrower audience still
    spec_b = maint.client.get("/api/v1/openapi.json", headers=_auth(maint.token[B])).json()
    assert not any("/maintenance/" in p for p in spec_b["paths"] if p != "/api/v1/maintenance/photos")


def test_maintenance_names_over_the_limit_say_what_to_do(maint):
    pos = maint.post("/api/v1/maintenance/positions.create", {"name": "Filter"}).json()
    r = maint.post("/api/v1/maintenance/tasks.create", {"position_id": pos["id"], "name": "x" * 397, "interval": 1})
    assert r.status_code >= 400
    assert "The task's name is at most 200 characters; this one is 397. Shorten it and put the detail in the " \
           "task's instructions." in r.text
    r = maint.post("/api/v1/maintenance/work_orders.generate", {})
    assert r.status_code == 200 and r.json()["skipped"] == [] and r.json()["work_orders"] == []


def test_maintenance_task_resources_over_rest(maint):
    """The LSA on a task over REST: tasks.set_resources, read back on get.task."""
    pos = maint.post("/api/v1/maintenance/positions.create", {"name": "Pool"}).json()
    task = maint.post("/api/v1/maintenance/tasks.create", {"position_id": pos["id"], "name": "Test water",
                                                           "interval": 1, "unit": "weeks"}).json()
    r = maint.post("/api/v1/maintenance/tasks.set_resources", {"task_id": task["id"], "resources": {
        "labour": [{"trade": "Pool technician", "people": 1, "hours": 0.5}],
        "tools": [{"name": "Photometer"}]}})
    assert r.status_code == 200, r.text
    got = maint.post("/api/v1/maintenance/get.task", {"id": task["id"]}).json()
    assert got["task"]["resources"]["labour_hours"] == 0.5
    assert got["task"]["resources"]["tools"] == [{"name": "Photometer"}]
    assert maint.post("/api/v1/maintenance/tasks.set_resources", {"task_id": task["id"]}).status_code >= 400


def test_maintenance_move_a_measurement_point_over_rest(maint):
    a = maint.post("/api/v1/maintenance/positions.create", {"name": "Pump A"}).json()
    b = maint.post("/api/v1/maintenance/positions.create", {"name": "Pump B"}).json()
    point = maint.post("/api/v1/maintenance/measurements.add_point",
                       {"position_id": a["id"], "name": "Run hours", "kind": "counter", "unit": "hours"}).json()
    r = maint.post("/api/v1/maintenance/measurements.move_point", {"point_id": point["id"], "position_id": b["id"]})
    assert r.status_code == 200, r.text
    assert r.json()["from_position_id"] == a["id"]
    spec = maint.client.get("/api/v1/openapi.json", headers=_auth(maint.token[A])).json()
    assert "/api/v1/maintenance/measurements.move_point" in spec["paths"]
    r = maint.post("/api/v1/maintenance/measurements.move_point", {"point_id": point["id"]})
    assert r.status_code >= 400 and "position_id" in r.text


def test_a_task_raised_by_a_logged_event_over_rest(maint):
    pos = maint.post("/api/v1/maintenance/positions.create", {"name": "Pool"}).json()
    task = maint.post("/api/v1/maintenance/tasks.create", {
        "position_id": pos["id"], "name": "Check stabiliser", "trigger": {"kind": "event", "event_type": "Overflow"}})
    assert task.status_code == 200, task.text
    assert task.json()["on_event"] and task.json()["next_due"] is None
    r = maint.post("/api/v1/maintenance/positions.log_event", {"position_id": pos["id"], "event_type": "overflow"})
    assert r.status_code == 200, r.text
    assert [w["task"]["id"] for w in r.json()["work_orders_raised"]] == [task.json()["id"]]
    r = maint.post("/api/v1/maintenance/tasks.update", {"task_id": task.json()["id"], "clear_trigger": True})
    assert r.status_code == 200 and r.json()["trigger"] is None


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

    pid = maint.post("/api/v1/maintenance/positions.create", {"name": "Pump A"}).json()["id"]
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
    view = maint.post("/api/v1/maintenance/view_photo", {"photo_id": photo_id})
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

    tables = {**mcp_server.TABLES, **mcp_tools.TOOL_TABLES}
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
    from backend.routers import field_reports

    expected = set(api_tools.REST_ONLY) | set(field_reports.REST_ONLY)  # this caller has Reliafy Maintenance
    assert rest_only == expected
    assert {r["name"] for r in listing["rest_only"]} == expected
    for name, entry in field_reports.REST_ONLY.items():
        assert spec["paths"][entry["path"]][entry["method"].lower()]["operationId"] == name


def test_spec_is_valid_and_public_safe(env):
    spec = env.client.get("/api/v1/openapi.json").json()  # no credentials: the core tools
    assert spec["openapi"].startswith("3.1")
    assert "/api/v1/analyse/fit" in spec["paths"]
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
    op = spec["paths"]["/api/v1/analyse/fit"]["post"]
    assert op["x-reliafy-pro-only"] and op["x-reliafy-heavy"] and op["x-reliafy-scope"] == "read"


def test_report_a_problem_and_check_it(env):
    r = env.post("/api/v1/report_problem/report", {"kind": "missing_capability", "summary": "No way to undo a fit",
                                                   "tool": "change", "trying": "refit with other columns"})
    assert r.status_code == 200, r.text
    rid = r.json()["report_id"]
    assert env.post("/api/v1/report_problem/status", {"report_id": rid}).json()["status"] == "new"
    assert env.post("/api/v1/report_problem/status", {"report_id": rid}, uid=B).status_code == 404
    # Only operators triage or update.
    assert env.post("/api/v1/report_problem/update", {"report_id": rid, "status": "fixed"}).status_code in (400, 403, 422)
    assert env.post("/api/v1/report_problem/triage").status_code in (400, 403, 422)


def test_maintenance_decide_with_hidden_over_rest(maint):
    """failure_modes.decide's hidden argument over REST, as over MCP (the action table makes both), and the
    RCM decision diagram's refusal."""
    pos = maint.post("/api/v1/maintenance/positions.create", {"name": "Trip"}).json()
    mode = maint.post("/api/v1/maintenance/failure_modes.add", {"position_id": pos["id"], "text": "Trip dead"}).json()
    r = maint.post("/api/v1/maintenance/failure_modes.decide", {
        "failure_mode_id": mode["id"], "hidden": True, "consequence": "safety",
        "decision": {"outcome": "failure_finding", "task": "Test the trip", "interval": 6, "interval_unit": "months"}})
    assert r.status_code == 200, r.text
    assert r.json()["hidden"] is True and r.json()["consequence"] == "safety"
    r = maint.post("/api/v1/maintenance/failure_modes.decide", {
        "failure_mode_id": mode["id"], "hidden": False, "decision": {"outcome": "rtf", "rtf_basis": "random"}})
    assert r.status_code >= 400 and "can't be run to failure" in r.text
    spec = maint.client.get("/api/v1/openapi.json", headers=_auth(maint.token[A])).json()
    body = spec["paths"]["/api/v1/maintenance/failure_modes.decide"]["post"]["requestBody"]["content"]
    assert "hidden" in str(body) or "hidden" in str(spec["components"])


def test_maintenance_rcm_interval_calculators_over_rest(maint):
    """rcm.pf_interval and rcm.ff_interval over REST: the action table makes both, with
    the calculators' plain refusals."""
    r = maint.post("/api/v1/maintenance/rcm.pf_interval", {
        "pf_interval": 30, "pf_unit": "days", "onset_rate": 365.25 / 400, "inspection_cost": 20, "found_cost": 300,
        "failure_cost": 5000})
    assert r.status_code == 200, r.text
    assert r.json()["recommended"] == {"value": 2, "unit": "weeks"}  # half the P-F interval
    assert r.json()["cost_optimal"]["recommended"] == {"value": 4, "unit": "weeks"}
    r = maint.post("/api/v1/maintenance/rcm.pf_interval", {"pf_interval": 30, "pf_unit": "days"})
    assert r.status_code == 200 and r.json()["cost_optimal"] is None, r.text
    r = maint.post("/api/v1/maintenance/rcm.ff_interval", {
        "failure_rate": 0.001, "target_unavailability": 0.001})
    assert r.status_code == 200 and r.json()["recommended"] == {"value": 2, "unit": "years"}, r.text
    r = maint.post("/api/v1/maintenance/rcm.ff_interval", {"failure_rate": 0.1})
    assert r.status_code >= 400 and "Give a target unavailability" in r.text


def test_maintenance_settings_and_work_order_readings_over_rest(maint):
    """A setting point and readings taken at a work order over REST, as over MCP (the
    action tables make both): kind setting on add_point and update_point, readings on
    work_orders.update / close, and work_order_id / task_id on record and in reads."""
    pos = maint.post("/api/v1/maintenance/positions.create", {"name": "Pool"}).json()
    r = maint.post("/api/v1/maintenance/measurements.add_point", {
        "position_id": pos["id"], "name": "Chlorinator output", "kind": "setting", "unit": "%", "range_max": 100})
    assert r.status_code == 200, r.text
    chl = r.json()
    assert chl["kind"] == "setting" and chl["range_max"] == 100
    timer = maint.post("/api/v1/maintenance/measurements.add_point", {
        "position_id": pos["id"], "name": "Pump timer", "kind": "condition", "unit": "h"}).json()
    r = maint.post("/api/v1/maintenance/measurements.update_point", {"point_id": timer["id"], "kind": "setting"})
    assert r.status_code == 200 and r.json()["kind"] == "setting", r.text
    wo = maint.post("/api/v1/maintenance/work_orders.open", {"position_id": pos["id"], "title": "Change-over"}).json()
    r = maint.post("/api/v1/maintenance/work_orders.update", {
        "work_order_id": wo["id"], "readings": [{"point_id": timer["id"], "value": 8}]})
    assert r.status_code == 200, r.text
    assert {p["name"] for p in r.json()["reading_points"]} == {"Chlorinator output", "Pump timer"}
    r = maint.post("/api/v1/maintenance/work_orders.close", {
        "work_order_id": wo["id"], "actions": [{"kind": "other"}], "readings": [{"point_id": chl["id"], "value": 60}]})
    assert r.status_code == 200, r.text
    assert [x["point"]["name"] for x in r.json()["readings_taken"]] == sorted(["Chlorinator output", "Pump timer"])
    r = maint.post("/api/v1/maintenance/measurements.record", {
        "point_id": chl["id"], "value": 65, "work_order_id": wo["id"]})
    assert r.status_code == 200, r.text
    assert r.json()["readings"][0]["work_order_id"] == wo["id"]
    assert [c["value"] for c in r.json()["changes"]] == [65, 60]
    r = maint.post("/api/v1/maintenance/measurements.add_point", {
        "position_id": pos["id"], "name": "Bad", "kind": "setting", "range_min": 5, "range_max": 1})
    assert r.status_code >= 400 and "lowest value" in r.text


def test_life_models_on_positions_over_rest(maint):
    """maintenance models.link / models.unlink over REST (the action table makes both); get.position lists
    the models attached."""
    from backend import db as db_mod
    from backend.services import samples

    if not db_mod.get_db().models.find_one({"_id": "sample-model-bearings-weibull"}):
        samples.seed_samples(db_mod.get_db())
    pos = maint.post("/api/v1/maintenance/positions.create", {"name": "Pump M"}).json()
    r = maint.post("/api/v1/maintenance/models.link", {"position_id": pos["id"], "model_id": "sample-model-bearings-weibull"})
    assert r.status_code == 200, r.text
    link = r.json()
    assert link["role"] == "assigned"
    got = maint.post("/api/v1/maintenance/get.position", {"id": pos["id"]}).json()
    assert [x["id"] for x in got["models"]] == [link["id"]]
    two = maint.post("/api/v1/maintenance/models.link", {"position_id": pos["id"], "model_id": "x", "from_class": True})
    assert two.status_code in (400, 422) and "one of" in two.text
    assert maint.post("/api/v1/maintenance/models.unlink", {"link_id": link["id"]}).status_code == 200


def test_bayes_update_over_rest(maint):
    """analyse bayes_update (typed numbers as the baseline, a few failures) and maintenance models.link with fit +
    baseline (the position's history), over REST."""
    r = maint.post("/api/v1/analyse/bayes_update", {
        "baseline": {"distribution": "weibull", "params": [{"name": "alpha", "value": 3000}, {"name": "beta", "value": 2}],
                     "unit": "hours"},
        "trust": "guide", "x": [1400, 1900, 800], "c": [0, 0, 1]})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["method"] == "bayesian_update" and out["counts"] == {"failures": 2, "suspensions": 1}
    assert "pulled the characteristic life" in out["moved"] and "data_notice" in out
    pos = maint.post("/api/v1/maintenance/positions.create", {"name": "Pump B"}).json()
    maint.post("/api/v1/maintenance/fitments.fit", {"position_id": pos["id"], "item_name": "U1", "on": "2024-01-01"})
    maint.post("/api/v1/maintenance/fitments.remove", {"position_id": pos["id"], "on": "2024-03-01", "reason": "failure"})
    link = maint.post("/api/v1/maintenance/models.link", {
        "position_id": pos["id"], "fit": True, "trust": "guide",
        "baseline": {"distribution": "weibull", "params": [{"name": "alpha", "value": 120}, {"name": "beta", "value": 2}],
                     "unit": "days"}})
    assert link.status_code == 200, link.text
    assert link.json()["role"] == "bayesian" and link.json()["update"]["counts"]["failures"] == 1


def test_a_prediction_row_over_rest(maint):
    """maintenance models.link with prediction (a parts count from the position's parts list) over REST."""
    pos = maint.post("/api/v1/maintenance/positions.create", {"name": "Controller R"}).json()
    part = maint.post("/api/v1/maintenance/parts.create", {"part_number": "C-9", "name": "Capacitor"}).json()
    maint.post("/api/v1/maintenance/parts.add_to_position", {"position_id": pos["id"], "part_id": part["id"], "quantity": 3})
    r = maint.post("/api/v1/maintenance/models.link", {
        "position_id": pos["id"], "prediction": {"environment": "GB", "assign": {"C-9": {"record_id": "mil-hdbk-217f-n2:10-1-cp-25"}}}})
    assert r.status_code == 200, r.text
    link = r.json()
    assert link["role"] == "prediction" and link["source"]["environment"] == "GB"
    assert link["prediction"]["results"]["failure_rate_per_hour"] > 0


def test_rbd_rows_and_the_model_in_use_over_rest(maint):
    """maintenance models.link with build_rbd and use_link_id over REST."""
    top = maint.post("/api/v1/maintenance/positions.create", {"name": "Station R"}).json()
    for name in ("Pump 1", "Pump 2"):
        maint.post("/api/v1/maintenance/positions.create", {"name": name, "parent_id": top["id"]})
    built = maint.post("/api/v1/maintenance/models.link", {"position_id": top["id"], "build_rbd": True})
    assert built.status_code == 200, built.text
    assert built.json()["role"] == "rbd" and built.json()["placeholders"] == ["Pump 1", "Pump 2"]
    used = maint.post("/api/v1/maintenance/models.link", {"position_id": top["id"], "use_link_id": built.json()["id"]})
    assert used.status_code == 200 and used.json()["in_use"] is True


def test_missions_over_the_tools(env):
    """change rbd_mission adds, changes and deletes a named mission; analyse rbd_mission works it out
    (one, or every mission's chance of completing); get rbd lists them."""
    rid = env.post("/api/v1/change/rbd_create", {"name": "Two pumps", **GRAPH}).json()["id"]
    made = env.post("/api/v1/change/rbd_mission", {"rbd_id": rid, "name": "Duty", "phases": [
        {"name": "Start", "duration": 10, "not_needed": ["p2"]}, {"name": "Run", "duration": 100}]})
    assert made.status_code == 200, made.text
    mid = made.json()["mission_id"]
    got = env.post("/api/v1/analyse/rbd_mission", {"rbd_id": rid, "mission_id": mid}).json()
    assert got["name"] == "Duty" and 0 < got["result"]["mission_reliability"] < 1
    assert [p["name"] for p in got["result"]["phases"]] == ["Start", "Run"]
    assert got["result"]["phases"][1]["weakest_block"] in ("P1", "P2")  # Start can't fail: P2 stands in as working
    every = env.post("/api/v1/analyse/rbd_mission", {"rbd_id": rid}).json()
    assert [m["name"] for m in every["missions"]] == ["Duty"]
    assert env.post("/api/v1/get/rbd", {"id": rid}).json()["missions"] == [{"id": mid, "name": "Duty", "phases": 2}]
    bad = env.post("/api/v1/change/rbd_mission", {"rbd_id": rid, "mission_id": mid,
                                                  "phases": [{"name": "X", "duration": -1}]})
    assert bad.status_code in (400, 422)
    gone = env.post("/api/v1/change/rbd_mission", {"rbd_id": rid, "mission_id": mid, "delete": True}).json()
    assert gone["deleted"] == mid and gone["missions"] == []
