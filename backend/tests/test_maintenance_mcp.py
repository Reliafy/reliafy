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
    monkeypatch.setattr(config, "MAINTENANCE_EMAILS", {"m@example.org"})
    test_db = mongomock.MongoClient()["reliafy_maint_mcp"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    monkeypatch.setattr(router, "_store", GraphStore(":memory:", PROJECTORS))
    ingest_router._hits.clear()
    test_db.users.insert_one({"_id": UID, "email": "m@example.org", "name": "M", "email_verified": True})
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
                headers={"Authorization": f"Bearer {token}"} if token else {},
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


def test_no_token_needed_when_sign_in_is_off(env, monkeypatch):
    from backend import config

    async def overview(client):
        return await client.call_tool("maintenance_overview", {})

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    with pytest.raises(Exception):
        _session("", overview)  # 401: a token (or OAuth) is needed
    monkeypatch.setattr(config, "AUTH_DISABLED", True)
    result = _session("", overview)
    assert not result.is_error and result.structured_content["summary"]["positions"] == 0


def test_tools_hidden_from_people_without_access(env, monkeypatch):
    from backend import config

    async def names(client):
        return {t.name for t in (await client.list_tools()).tools}, await client.call_tool("maintenance_overview", {})

    monkeypatch.setattr(config, "ADMIN_EMAILS", set())
    monkeypatch.setattr(config, "MAINTENANCE_EMAILS", set())
    listed, result = _session(env["token"], names)
    assert "maintenance_overview" not in listed and "list_models" in listed
    assert result.is_error and "isn't available" in result.content[0].text


def test_nameplate_and_moves_over_mcp(env):
    async def flow(client):
        a = _ok(await client.call_tool("create_position", {"name": "Pump A", "position_class": "Pool pump"}))
        b = _ok(await client.call_tool("create_position", {"name": "Pump B", "position_class": "Pool pump"}))
        fitted = _ok(await client.call_tool("fit_item", {"position_id": a["id"], "item_name": "Pump",
                                                         "on": "2025-01-01"}))
        item_id = fitted["fitted"]["item"]["id"]
        item = _ok(await client.call_tool("update_item", {
            "item_id": item_id, "manufacturer": "Astral", "model": "CTX 280", "serial": "AX-1",
            "nameplate": {"Power": "1.1 kW", "Voltage": "240 V"}}))
        assert item["nameplate"] == {"Power": "1.1 kW", "Voltage": "240 V"}
        moved = _ok(await client.call_tool("move_item", {"item_id": item_id, "position_id": b["id"],
                                                         "on": "2026-01-01"}))
        classes = _ok(await client.call_tool("list_position_classes", {}))
        pooled = _ok(await client.call_tool("class_life_data", {"position_class": "Pool pump"}))
        return moved, classes, pooled

    moved, classes, pooled = _session(env["token"], flow)
    assert moved["fitted_to"]["name"] == "Pump B" and len(moved["history"]) == 2
    assert classes["classes"][0]["fitments"] == 2 and len(pooled["rows"]) == 2


def test_notes_and_reading_corrections_over_mcp(env):
    from datetime import date, timedelta

    today = date.today().isoformat()
    ago = lambda n: (date.today() - timedelta(days=n)).isoformat()  # noqa: E731

    async def flow(client):
        names = {t.name for t in (await client.list_tools()).tools}
        assert {"void_reading", "correct_reading"} <= names
        pos = _ok(await client.call_tool("create_position", {"name": "Pump"}))
        point = _ok(await client.call_tool("add_measurement_point", {
            "position_id": pos["id"], "name": "Hours", "kind": "counter", "unit": "hours"}))
        _ok(await client.call_tool("record_reading", {"point_id": point["id"], "value": 3000, "on": ago(400)}))
        stale = _ok(await client.call_tool("record_reading", {"point_id": point["id"], "value": 3774}))
        moved = _ok(await client.call_tool("correct_reading", {
            "reading_id": stale["readings"][0]["id"], "on": ago(200), "reason": "old reading entered as today"}))
        correction = next(r for r in moved["readings"] if r["status"] == "correction")
        no_reason = await client.call_tool("void_reading", {"reading_id": correction["id"], "reason": ""})
        voided = _ok(await client.call_tool("void_reading", {"reading_id": correction["id"], "reason": "duplicate"}))
        read = _ok(await client.call_tool("get_measurement_point", {"point_id": point["id"]}))

        fitted = _ok(await client.call_tool("fit_item", {"position_id": pos["id"], "item_name": "Pump"}))
        item_id = fitted["fitted"]["item"]["id"]
        _ok(await client.call_tool("update_item", {"item_id": item_id, "notes": "Diagnosis: worn bearing"}))
        item = _ok(await client.call_tool("update_item", {"item_id": item_id, "append_note": "Bearing ordered"}))
        wo = _ok(await client.call_tool("open_work_order", {"position_id": pos["id"], "title": "Noisy",
                                                            "notes": "Grinding at start"}))
        cancelled = _ok(await client.call_tool("cancel_work_order", {"work_order_id": wo["id"],
                                                                     "reason": "duplicate"}))
        noted = _ok(await client.call_tool("update_work_order", {"work_order_id": wo["id"], "append_note": "see #1"}))
        return moved, no_reason, voided, read, item, cancelled, noted

    moved, no_reason, voided, read, item, cancelled, noted = _session(env["token"], flow)
    assert moved["read_at"] == ago(200)
    assert no_reason.is_error and "reason" in no_reason.content[0].text
    assert voided["reading"] == 3000
    assert [r["status"] for r in read["readings"]] == ["replaced", "voided", "ok"]
    assert item["notes"] == f"Diagnosis: worn bearing\n{today}: Bearing ordered"
    assert len(item["note_history"]) == 2
    assert cancelled["notes"] == "Grinding at start" and cancelled["cancel_reason"] == "duplicate"
    assert noted["notes"] == f"Grinding at start\n{today}: see #1"


def test_class_model_fitting_is_pro_only_over_mcp():
    from backend import mcp_server
    from backend.maintenance import mcp_tools

    mcp_tools.register()
    try:
        assert "fit_class_model" in mcp_server.PRO_ONLY_TOOLS
        assert "Pro" in mcp_server._pro_only_message("fit_class_model")
    finally:
        mcp_tools.unregister()
    assert "fit_class_model" not in mcp_server.PRO_ONLY_TOOLS
