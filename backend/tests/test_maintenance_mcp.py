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


def test_a_study_given_as_json_drives_positions_and_tasks(env):
    """create_rcm_study's study works with position_from_rcm straight away,
    and a change through update_rcm_study reaches the position's tasks."""

    async def flow(client):
        study = _ok(await client.call_tool("create_rcm_study", {
            "name": "Pool RCM", "system": "Pool pump", "functions": [
                {"text": "Circulate water", "failures": [{"text": "No flow", "modes": [
                    {"text": "Basket blocked", "consequence": "operational",
                     "decision": {"outcome": "on_condition", "interval": 1, "interval_unit": "weeks",
                                  "task": "Empty the pump basket"}},
                    {"text": "Bearing worn", "decision": {"outcome": "rtf", "rtf_basis": "random"}}]}]}]}))
        assert study["counts"]["scheduled_tasks"] == 1
        made = _ok(await client.call_tool("position_from_rcm", {"study_id": study["study_id"]}))
        got = _ok(await client.call_tool("get_rcm_study", {"study_id": study["study_id"]}))
        basket = got["functions"][0]["failures"][0]["modes"][0]
        _ok(await client.call_tool("update_rcm_study", {"study_id": study["study_id"], "functions": [
            {"id": got["functions"][0]["id"], "failures": [{"id": got["functions"][0]["failures"][0]["id"],
                                                            "modes": [{"id": basket["id"], "decision": {
                                                                "outcome": "on_condition", "interval": 2,
                                                                "interval_unit": "weeks",
                                                                "task": "Empty the pump basket"}}]}]}]}))
        again = _ok(await client.call_tool("apply_rcm_to_position", {"position_id": made["position"]["id"],
                                                                     "study_id": study["study_id"]}))
        return made, again

    made, again = _session(env["token"], flow)
    assert made["position"]["name"] == "Pool pump" and made["tasks_added"] == 1 and made["failure_modes_added"] == 2
    assert again["tasks_updated"] == 1 and again["tasks_added"] == 0 and again["failure_modes_added"] == 0
    assert [t["interval"] for t in again["position"]["tasks"]] == [2]


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


def test_tasks_failure_modes_and_past_fitments_through_mcp(env):
    async def flow(client):
        pid = _ok(await client.call_tool("create_position", {"name": "Pump", "position_class": "Pool pump"}))["id"]
        task = _ok(await client.call_tool("create_task", {
            "position_id": pid, "name": "Clean basket", "interval": 1, "unit": "weeks", "source": "oem",
            "reference": "Manual p. 12", "checklist": ["Isolate", "Empty basket"]}))
        assert (task["source"], task["unit"], task["outcome"]) == ("oem", "weeks", None)
        bad = await client.call_tool("create_task", {"position_id": pid, "name": "X", "interval": 1,
                                                     "outcome": "rtf"})
        assert bad.is_error
        mode = _ok(await client.call_tool("add_failure_mode", {"position_id": pid, "text": "Basket blocked"}))
        linked = _ok(await client.call_tool("update_task", {"task_id": task["id"], "failure_mode_id": mode["id"]}))
        assert linked["failure_mode"]["text"] == "Basket blocked"
        unlinked = _ok(await client.call_tool("update_task", {"task_id": task["id"], "unlink_failure_mode": True}))
        assert unlinked["failure_mode"] is None

        _ok(await client.call_tool("fit_item", {"position_id": pid, "item_name": "Astral", "on": "2024-01-01"}))
        removed = _ok(await client.call_tool("remove_item", {"position_id": pid, "on": "2025-01-01",
                                                             "failure_mode_text": "Seal leaking"}))
        assert removed["life_data"][0]["c"] == 0
        ad_hoc = next(f for f in removed["failure_modes"] if f["ad_hoc"])
        merged = _ok(await client.call_tool("merge_failure_mode", {"failure_mode_id": ad_hoc["id"],
                                                                   "into_failure_mode_id": mode["id"]}))
        assert [f["text"] for f in merged["failure_modes"]] == ["Basket blocked"]
        edited = _ok(await client.call_tool("update_failure_mode", {"failure_mode_id": mode["id"],
                                                                    "failure": "No flow"}))
        assert edited["failure"] == "No flow"

        past = _ok(await client.call_tool("add_past_fitment", {
            "position_id": pid, "start": "2020-01-01", "end": "2023-12-31", "item_name": "Old pump",
            "failure_mode_text": "Motor burnt out", "from_precision": "year"}))
        assert [r["c"] for r in past["life_data"]] == [0, 0]
        clash = await client.call_tool("add_past_fitment", {"position_id": pid, "start": "2021-01-01",
                                                            "end": "2021-06-01", "item_name": "Ghost"})
        assert clash.is_error and "Old pump" in clash.content[0].text
        return True

    assert _session(env["token"], flow)


def test_structured_fields_through_mcp(env):
    """Dates with precision, warranty, replacement cost, documents and trade (batch 1, 3.1-3.5)."""

    async def flow(client):
        names = {t.name for t in (await client.list_tools()).tools}
        assert {"add_document", "remove_document"} <= names
        pid = _ok(await client.call_tool("create_position", {"name": "Pump", "position_class": "Pool pump"}))["id"]
        pos = _ok(await client.call_tool("fit_item", {"position_id": pid, "item_name": "Astral", "on": "2022"}))
        iid = pos["fitted"]["item"]["id"]
        item = _ok(await client.call_tool("update_item", {
            "item_id": iid, "purchase_date": {"date": "2021", "source": "owner's estimate"},
            "in_service_date": {"date": "2022-03-10", "precision": "estimated"},
            "warranty": {"ends_on": "2030-01-01", "coverage": "motor", "registration_required": True},
            "replacement_cost": {"amount": 950, "currency": "AUD", "source": "quote"}}))
        assert item["purchase_date"]["display"] == "2021" and item["in_service_date"]["display"] == "~Mar 2022"
        assert item["warranty"]["summary"].endswith("registration still to do.")
        cleared = _ok(await client.call_tool("update_item", {"item_id": iid, "clear": ["purchase_date"]}))
        assert cleared["purchase_date"] is None and cleared["warranty"]
        doc = _ok(await client.call_tool("add_document", {"url": "https://example.com/m.pdf", "target_id": iid,
                                                          "kind": "manual", "title": "Manual"}))
        bad = await client.call_tool("add_document", {"url": "data:text/html,x", "target_id": iid})
        assert bad.is_error and "http" in bad.content[0].text
        _ok(await client.call_tool("add_document", {"url": "https://example.com/ds", "position_class": "Pool pump",
                                                    "kind": "datasheet"}))
        cls = _ok(await client.call_tool("set_class_costs", {"position_class": "Pool pump",
                                                             "replacement_cost": {"amount": 800}}))
        assert cls["replacement_cost"]["amount"] == 800 and cls["documents"][0]["kind"] == "datasheet"
        assert cls["costs"]["planned_cost"] is None
        _ok(await client.call_tool("remove_document", {"document_id": doc["id"]}))
        fixed = _ok(await client.call_tool("correct_fitment", {"fitment_id": pos["fitted"]["id"],
                                                               "from_precision": "month", "start": "2022-04"}))
        assert fixed["from_precision"] == "month"
        wo = _ok(await client.call_tool("open_work_order", {"position_id": pid, "title": "Hum",
                                                            "trade": "Electrician"}))
        assert wo["trade"] == "Electrician" and wo["warranty"]["coverage"] == "motor"
        wo = _ok(await client.call_tool("update_work_order", {"work_order_id": wo["id"], "trade": "Pool tech"}))
        return wo, _ok(await client.call_tool("get_item", {"item_id": iid}))

    wo, item = _session(env["token"], flow)
    assert wo["trade"] == "Pool tech"
    assert item["documents"] == []
