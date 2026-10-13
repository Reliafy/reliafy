"""Reliafy Maintenance over MCP: the tools are only there when it's switched
on, and they drive the same workspace as the app."""

import anyio
import httpx2
import mongomock
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

UID = "user-m"


@pytest.fixture()
def env(monkeypatch):
    from backend import config, db
    from backend.maintenance import mcp_tools
    from backend.maintenance.service import PROJECTORS
    from backend.maintenance.store import GraphStore
    from backend.routers import ingest as ingest_router
    from backend.routers import maintenance as router
    from backend.services import tokens

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    monkeypatch.setattr(config, "MAINTENANCE_ENABLED", True)
    test_db = mongomock.MongoClient()["reliafy_maint_mcp"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    monkeypatch.setattr(router, "_store", GraphStore(":memory:", PROJECTORS))
    ingest_router._hits.clear()
    test_db.users.insert_one({"_id": UID, "email": "m@example.org", "name": "M"})
    mcp_tools.register()
    yield {"db": test_db, "token": tokens.create_token(test_db, UID, "mcp")["token"]}
    mcp_tools.unregister()


def _session(token, fn):
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


def _ok(result) -> dict:
    assert not result.is_error, result.content[0].text
    return result.structured_content


def test_tools_absent_unless_enabled():
    from backend.maintenance import mcp_tools
    from backend.mcp_server import mcp

    names = {t.name for t in anyio.run(mcp.list_tools)}
    assert not {"maintenance_overview", "close_work_order"} & names
    assert mcp_tools.TOOL_NAMES == []


def test_a_house_through_mcp(env):
    from backend.services import rcm as rcm_service

    study = rcm_service.create_study(env["db"], "Pool RCM", "Pool pump", "", UID)
    rcm_service.replace_tree(env["db"], study.id, [
        {"text": "Circulate water", "failures": [{"text": "No flow", "modes": [
            {"text": "Basket blocked", "consequence": "operational",
             "decision": {"outcome": "on_condition", "interval": 1, "interval_unit": "weeks",
                          "task": "Empty the pump basket"}},
            {"text": "Bearing worn", "consequence": "operational",
             "decision": {"outcome": "rtf", "rtf_basis": "random"}}]}]}], UID)

    async def flow(client):
        names = {t.name for t in (await client.list_tools()).tools}
        assert {"maintenance_overview", "position_from_rcm", "close_work_order", "copy_position"} <= names

        house = _ok(await client.call_tool("create_position", {"name": "House"}))
        pool = _ok(await client.call_tool("position_from_rcm", {"study_id": study.id, "parent_id": house["id"]}))
        pid = pool["position"]["id"]
        assert pool["tasks_added"] == 1
        _ok(await client.call_tool("fit_item", {"position_id": pid, "item_name": "Astral CTX 280",
                                                "on": "2024-11-01"}))
        wo = _ok(await client.call_tool("open_work_order", {"position_id": pid, "title": "Pump screaming"}))
        detail = _ok(await client.call_tool("get_work_order", {"work_order_id": wo["id"]}))
        bearing = next(f for f in detail["failure_modes"] if f["text"] == "Bearing worn")
        bad = await client.call_tool("close_work_order", {"work_order_id": wo["id"], "actions": [{"kind": "nope"}]})
        assert bad.is_error
        closed = _ok(await client.call_tool("close_work_order", {
            "work_order_id": wo["id"], "on": "2026-10-01",
            "actions": [{"kind": "replace", "failure_mode_id": bearing["id"],
                         "new_item": {"name": "Astral CTX 280", "serial": "N2"}}]}))
        assert closed["actions"][0]["fitted"]["serial"] == "N2"

        copy = _ok(await client.call_tool("copy_position", {"position_id": pid, "name": "Spa pump",
                                                            "parent_id": house["id"]}))
        assert copy["fitted"] is None and [t["name"] for t in copy["tasks"]] == ["Empty the pump basket"]

        position = _ok(await client.call_tool("get_position", {"position_id": pid}))
        overview = _ok(await client.call_tool("maintenance_overview", {}))
        missing = await client.call_tool("get_position", {"position_id": "nope"})
        return position, overview, missing

    position, overview, missing = _session(env["token"], flow)
    assert [(r["c"], r["status"]) for r in position["life_data"]] == [(0, "failed"), (1, "still fitted")]
    assert overview["summary"]["positions"] == 3
    assert missing.is_error and "Not found" in missing.content[0].text
