"""Reliafy Maintenance over MCP: the tools are only there when it's switched
on, and they drive the same workspace as the app.

A few tools, each with actions (maintenance_<area>(action, ...)) or kinds
(maintenance_get / maintenance_list): every call is held to its action's
arguments, and plan gating, the heavy slots and the usage log go by
tool.action."""

from datetime import datetime, timezone

import anyio
import httpx2
import mongomock
import pytest
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

UID = "user-m"
EXPECTED_TOOLS = {
    "maintenance_overview", "maintenance_guide", "maintenance_get", "maintenance_list", "maintenance_view_photo",
    "maintenance_positions", "maintenance_fitments", "maintenance_items", "maintenance_failure_modes",
    "maintenance_tasks", "maintenance_proposals", "maintenance_work_orders", "maintenance_measurements",
    "maintenance_locations", "maintenance_parts", "maintenance_reliability", "maintenance_topology",
    "maintenance_item_classes", "maintenance_manufacturers", "maintenance_attachments", "maintenance_workspace",
}


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


def _session(token, fn, mode="legacy"):
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
                                  mode=mode) as client:
                    out["value"] = await fn(client)

    anyio.run(main)
    return out["value"]


def _ok(result) -> dict:
    assert not result.is_error, result.content[0].text
    return result.structured_content


async def _do(client, tool, action, **args):
    """A write: maintenance_<area>(action, ...)."""
    return await client.call_tool(tool, {"action": action, **args})


async def _get(client, kind, id=None, **args):
    return await client.call_tool("maintenance_get", {"kind": kind, **({"id": id} if id else {}), **args})


async def _list(client, kind, **args):
    return await client.call_tool("maintenance_list", {"kind": kind, **args})


def test_tools_absent_unless_enabled():
    from backend.maintenance import mcp_tools
    from backend.mcp_server import mcp

    names = {t.name for t in anyio.run(mcp.list_tools)}
    assert not {"maintenance_overview", "maintenance_work_orders"} & names
    assert mcp_tools.TOOL_NAMES == []


def test_a_handful_of_tools_reads_apart_from_writes(env):
    """21 tools in place of 105: reads (overview, guide, get, list, view_photo) and one write tool
    per area, each with an action (or kind) enum whose every value the description lists."""
    from backend.maintenance import mcp_tools

    async def listed(client):
        return {t.name: t for t in (await client.list_tools()).tools if t.name.startswith("maintenance_")}

    tools = _session(env["token"], listed)
    assert set(tools) == EXPECTED_TOOLS and len(tools) == 21 == len(mcp_tools.TOOL_NAMES)
    reads = {n for n, t in tools.items() if t.annotations.read_only_hint}
    assert reads == {"maintenance_overview", "maintenance_guide", "maintenance_get", "maintenance_list",
                     "maintenance_view_photo"}
    assert set(mcp_tools.TABLES) == EXPECTED_TOOLS - {"maintenance_overview", "maintenance_guide",
                                                      "maintenance_view_photo"}
    for name, (selector, table) in mcp_tools.TABLES.items():
        t = tools[name]
        assert t.input_schema["properties"][selector]["enum"] == list(table) and selector in t.input_schema["required"]
        for value, (required, optional, _) in table.items():
            assert f"\n- {value}(" in t.description, (name, value)
            assert set((required + " " + optional).split()) <= set(t.input_schema["properties"]), (name, value)
    assert "close(work_order_id, actions?, on?, notes?, readings?)" in tools["maintenance_work_orders"].description


def test_the_action_validator():
    from backend.maintenance.mcp_tools import WORK_ORDERS, check

    with pytest.raises(ValueError, match=r"action 'close' needs work_order_id \(it takes work_order_id, "):
        check("action", "close", WORK_ORDERS, {"work_order_id": None, "notes": "done"})
    with pytest.raises(ValueError, match="action 'close' doesn't take hours, who"):
        check("action", "close", WORK_ORDERS, {"work_order_id": "w", "hours": 2, "who": "Sam"})
    assert check("action", "close", WORK_ORDERS, {"work_order_id": "w", "notes": "", "hours": None}) == {
        "work_order_id": "w", "notes": ""}
    assert check("action", "generate", WORK_ORDERS, {}) == {}


def test_the_validator_answers_over_mcp(env):
    async def flow(client):
        missing = await _do(client, "maintenance_work_orders", "close", notes="done")
        extra = await _do(client, "maintenance_positions", "create", name="Pump", study_id="s1")
        no_id = await _get(client, "position")
        bad_kind = await client.call_tool("maintenance_get", {"kind": "nope", "id": "x"})
        bad_status = await _list(client, "proposals", status="open")
        return missing, extra, no_id, bad_kind, bad_status

    missing, extra, no_id, bad_kind, bad_status = _session(env["token"], flow)
    assert missing.is_error and "action 'close' needs work_order_id" in missing.content[0].text
    assert extra.is_error and "action 'create' doesn't take study_id" in extra.content[0].text
    assert no_id.is_error and "kind 'position' needs id" in no_id.content[0].text
    assert bad_kind.is_error
    assert bad_status.is_error and "kind 'proposals' takes status pending" in bad_status.content[0].text


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
        assert EXPECTED_TOOLS <= names

        house = _ok(await _do(client, "maintenance_positions", "create", name="House"))
        pool = _ok(await _do(client, "maintenance_positions", "from_rcm", study_id=study.id, parent_id=house["id"]))
        pid = pool["position"]["id"]
        assert pool["tasks_added"] == 1
        _ok(await _do(client, "maintenance_fitments", "fit", position_id=pid, item_name="Astral CTX 280",
                      on="2024-11-01"))
        wo = _ok(await _do(client, "maintenance_work_orders", "open", position_id=pid, title="Pump screaming"))
        detail = _ok(await _get(client, "work_order", wo["id"]))
        bearing = next(f for f in detail["failure_modes"] if f["text"] == "Bearing worn")
        bad = await _do(client, "maintenance_work_orders", "close", work_order_id=wo["id"], actions=[{"kind": "nope"}])
        assert bad.is_error
        closed = _ok(await _do(client, "maintenance_work_orders", "close", work_order_id=wo["id"], on="2026-10-01",
                               actions=[{"kind": "replace", "failure_mode_id": bearing["id"],
                                         "new_item": {"name": "Astral CTX 280", "serial": "N2"}}]))
        assert closed["actions"][0]["fitted"]["serial"] == "N2"

        copy = _ok(await _do(client, "maintenance_positions", "copy", position_id=pid, name="Spa pump",
                             parent_id=house["id"]))
        assert copy["fitted"] is None and [t["name"] for t in copy["tasks"]] == ["Empty the pump basket"]

        position = _ok(await _get(client, "position", pid))
        overview = _ok(await client.call_tool("maintenance_overview", {}))
        missing = await _get(client, "position", "nope")
        return position, overview, missing

    position, overview, missing = _session(env["token"], flow)
    assert [(r["c"], r["status"]) for r in position["life_data"]] == [(0, "failed"), (1, "still fitted")]
    assert overview["summary"]["positions"] == 3
    assert missing.is_error and "Not found" in missing.content[0].text


def test_a_study_given_as_json_drives_positions_and_tasks(env):
    """rcm create's study works with maintenance_positions from_rcm straight away,
    and a change through rcm update reaches the position's tasks (apply_rcm)."""

    async def flow(client):
        study = _ok(await client.call_tool("rcm", {
            "action": "create", "name": "Pool RCM", "system": "Pool pump", "functions": [
                {"text": "Circulate water", "failures": [{"text": "No flow", "modes": [
                    {"text": "Basket blocked", "consequence": "operational",
                     "decision": {"outcome": "on_condition", "interval": 1, "interval_unit": "weeks",
                                  "task": "Empty the pump basket"}},
                    {"text": "Bearing worn", "decision": {"outcome": "rtf", "rtf_basis": "random"}}]}]}]}))
        assert study["counts"]["scheduled_tasks"] == 1
        assert "from_rcm" in study["next"]
        made = _ok(await _do(client, "maintenance_positions", "from_rcm", study_id=study["study_id"]))
        got = _ok(await client.call_tool("get", {"kind": "rcm_study", "id": study["study_id"]}))
        basket = got["functions"][0]["failures"][0]["modes"][0]
        _ok(await client.call_tool("rcm", {"action": "update", "study_id": study["study_id"], "functions": [
            {"id": got["functions"][0]["id"], "failures": [{"id": got["functions"][0]["failures"][0]["id"],
                                                            "modes": [{"id": basket["id"], "decision": {
                                                                "outcome": "on_condition", "interval": 2,
                                                                "interval_unit": "weeks",
                                                                "task": "Empty the pump basket"}}]}]}]}))
        again = _ok(await _do(client, "maintenance_positions", "apply_rcm", position_id=made["position"]["id"],
                              study_id=study["study_id"]))
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
        return ({t.name for t in (await client.list_tools()).tools},
                await client.call_tool("maintenance_overview", {}),
                await _do(client, "maintenance_positions", "create", name="Pump"),
                await client.call_tool("maintenance_guide", {"topic": "model"}))

    monkeypatch.setattr(config, "ADMIN_EMAILS", set())
    monkeypatch.setattr(config, "MAINTENANCE_EMAILS", set())
    listed, result, write, guide = _session(env["token"], names)
    assert not EXPECTED_TOOLS & listed and {"list", "get"} <= listed
    for r in (result, write, guide):
        assert r.is_error and "isn't available" in r.content[0].text


def test_instructions_gain_the_maintenance_section_only_for_people_with_access(env, monkeypatch):
    """The server's instructions go to everyone; the maintenance section (the four structures,
    where to start, the guide, the data rules) only to people who see the maintenance tools,
    at initialize and at the newer protocol's server/discover alike."""
    from backend import config
    from backend.maintenance import mcp_guide
    from backend.mcp_server import INSTRUCTIONS

    async def instructions(client):
        return client.instructions

    section = mcp_guide.INSTRUCTIONS
    assert 1000 < len(section) < 2200
    for words in ("maintenance_overview", "maintenance_guide", "Positions", "Locations", "Classes", "Connections",
                  "never an invented day", "never place a fitted item"):
        assert words in section
    with_access = _session(env["token"], instructions)
    assert with_access.startswith(INSTRUCTIONS.strip()[:200]) and section.strip() in with_access
    modern = _session(env["token"], instructions, mode="auto")
    assert section.strip() in modern

    monkeypatch.setattr(config, "ADMIN_EMAILS", set())
    monkeypatch.setattr(config, "MAINTENANCE_EMAILS", set())
    without = _session(env["token"], instructions)
    assert without.strip() == INSTRUCTIONS.strip() and "maintenance_overview" not in without
    assert "maintenance_overview" not in _session(env["token"], instructions, mode="auto")


def test_the_guide_by_topic(env):
    from backend.maintenance import mcp_guide

    async def flow(client):
        index = _ok(await client.call_tool("maintenance_guide", {}))
        pages = {t: _ok(await client.call_tool("maintenance_guide", {"topic": t})) for t in index["topics"]}
        bad = await client.call_tool("maintenance_guide", {"topic": "nope"})
        return index, pages, bad

    index, pages, bad = _session(env["token"], flow)
    assert set(index["topics"]) == {"model", "register", "plan", "run", "learn", "decide", "data", "classes",
                                    "conditions", "structure"}
    structure = pages["structure"]["guide"]
    assert "add_component" in structure and "positions_from_structure" in structure and "loop" in structure
    conditions = pages["conditions"]["guide"]
    assert "exclude_condition" in conditions and "connection holds only its own conditions" in conditions
    assert "guide" not in index and bad.is_error
    model = pages["model"]["guide"]
    assert "FLOC" in model and "needs no placement" in model and "build each once" in model
    assert "meronomy" in model and "mereotopology" in model and "taxonomy" in model and "topology" in model
    assert "Never record a failure as planned" in pages["run"]["guide"]
    assert "accept" in pages["learn"]["guide"] and "user" in pages["learn"]["guide"]
    # Every tool named in the guide exists (tool names only; actions are checked by the descriptions).
    for name, (_, text) in mcp_guide.TOPICS.items():
        for word in text.replace(",", " ").replace(".", " ").replace(":", " ").split():
            if word.startswith("maintenance_") and word not in ("maintenance_<area>",):
                assert word in EXPECTED_TOOLS, (name, word)


def test_read_only_token_reads_but_cant_write(env):
    from backend.services import tokens

    read = tokens.create_token(env["db"], UID, "r", ["read"])["token"]

    async def flow(client):
        return (await client.call_tool("maintenance_overview", {}),
                await _list(client, "locations"),
                await client.call_tool("maintenance_guide", {"topic": "data"}),
                await _get(client, "position", "nope"),
                await _do(client, "maintenance_positions", "create", name="Pump"),
                await _do(client, "maintenance_workspace", "set_time_zone", time_zone="Australia/Brisbane"))

    overview, locations, guide, missing, create, tz = _session(read, flow)
    assert not overview.is_error and not locations.is_error and not guide.is_error
    assert missing.is_error and "Not found" in missing.content[0].text  # reached the tool
    for r in (create, tz):
        assert r.is_error and "write" in r.content[0].text


def test_calls_are_keyed_by_action_for_gating_heavy_slots_and_usage(env, monkeypatch):
    from backend import config, mcp_server
    from backend.maintenance import mcp_tools

    assert "maintenance_reliability.fit_class_model" in mcp_server.PRO_ONLY_TOOLS
    assert "maintenance_reliability" not in mcp_server.PRO_ONLY_TOOLS
    assert {"maintenance_reliability.fit_class_model", "maintenance_workspace.import_history",
            "maintenance_get.plan_economics", "maintenance_topology.generate_rbd"} <= mcp_server.HEAVY_TOOLS
    assert set(mcp_tools.HEAVY_CALLS) <= mcp_server.HEAVY_TOOLS

    monkeypatch.setattr(config, "USAGE_LOGGING", True)
    heavy_calls = []
    real = mcp_server._run_in_slot

    async def spy(uid, body, heavy=False):
        heavy_calls.append(heavy)
        return await real(uid, body, heavy=heavy)

    monkeypatch.setattr(mcp_server, "_run_in_slot", spy)

    async def flow(client):
        pos = _ok(await _do(client, "maintenance_positions", "create", name="Pump", position_class="Pool pump"))
        _ok(await _do(client, "maintenance_workspace", "import_history",
                      rows=[{"position": "House > Pool > Pump", "item": "Astral", "fitted": "2024-01-01"}]))
        await _do(client, "maintenance_work_orders", "close", notes="no id")
        _ok(await _get(client, "position", pos["id"]))
        return pos

    _session(env["token"], flow)
    assert heavy_calls == [False, True, False, False]
    events = list(env["db"].usage_events.find({"channel": "mcp", "uid": UID}))
    features = [(e["feature"], e["outcome"]) for e in events if e["feature"] not in ("initialize", "tools/list")]
    assert ("maintenance_positions.create", "ok") in features
    assert ("maintenance_workspace.import_history", "ok") in features
    assert ("maintenance_work_orders.close", "error") in features
    assert ("maintenance_get.position", "ok") in features


@pytest.fixture()
def free_env(env, monkeypatch, mcp_on):
    """The maintenance user on the Free plan, signed in through OAuth as Claude's connector."""
    from backend import config
    from backend.services import oauth as oauth_service

    monkeypatch.setattr(config, "BILLING_ENABLED", True)
    monkeypatch.setattr(config, "ADMIN_EMAILS", set())
    token = oauth_service._issue(
        env["db"], family_id="fam-m", uid=UID, client_id="https://claude.ai/test", client_name="Claude",
        scopes=["mcp"], res=oauth_service.resource(), grant_created_at=datetime.now(timezone.utc))["access_token"]
    return {**env, "oauth": token}


def test_fitting_a_class_model_is_pro_only_but_the_tools_other_actions_are_not(free_env):
    from backend.services import billing

    async def flow(client):
        names = {t.name for t in (await client.list_tools()).tools}
        assert "maintenance_reliability" in names
        _ok(await _do(client, "maintenance_positions", "create", name="Pump", position_class="Pool pump"))
        costs = await _do(client, "maintenance_reliability", "set_class_costs", position_class="Pool pump",
                          planned_cost=100, failure_cost=1000)
        fit = await _do(client, "maintenance_reliability", "fit_class_model", position_class="Pool pump")
        return costs, fit

    costs, fit = _session(free_env["oauth"], flow)
    assert not costs.is_error and costs.structured_content["costs"]["planned_cost"] == 100
    assert fit.is_error and "part of Reliafy Pro" in fit.content[0].text
    assert billing.mcp_calls_used(free_env["db"], UID, "free") == 2  # the refused fit isn't counted


def test_class_model_fitting_is_pro_only_over_mcp():
    from backend import mcp_server
    from backend.maintenance import mcp_tools

    mcp_tools.register()
    try:
        assert "maintenance_reliability.fit_class_model" in mcp_server.PRO_ONLY_TOOLS
        assert "Pro" in mcp_server._pro_only_message("maintenance_reliability.fit_class_model")
    finally:
        mcp_tools.unregister()
    assert "maintenance_reliability.fit_class_model" not in mcp_server.PRO_ONLY_TOOLS
    assert "maintenance_get.plan_economics" not in mcp_server.HEAVY_TOOLS


def _fitted_class(name="Pool pump"):
    """Two pumps of a class with items in and the class's model, as fit_class_model
    records it (straight into the store the MCP tools read)."""
    from backend.maintenance.service import Maintenance, class_id
    from backend.routers import maintenance as router

    m = Maintenance(router._store, UID, UID)
    for i in (1, 2):
        pid = m.create_position(f"Pump {i}", position_class=name)["id"]
        m.fit(pid, new_item={"name": f"Pump {i}"}, on="2025-01-01")
    m._emit("class.model_fitted", {
        "id": class_id(UID, name), "name": name, "model_id": "m1", "distribution": "weibull",
        "params": [{"name": "alpha", "value": 600.0}, {"name": "beta", "value": 2.5}], "extras": None,
        "unit": "days", "fitted_on": m.today(), "failures": 6, "suspensions": 2})


def test_a_class_forecast_over_mcp(env):
    from backend import mcp_server

    assert "maintenance_get.class_forecast" in mcp_server.HEAVY_TOOLS
    _fitted_class()

    async def flow(client):
        out = _ok(await _get(client, "class_forecast", "Pool pump", period="quarter", periods=4))
        wrong = await _get(client, "class_forecast", "Pool pump", interval=3)
        guide = _ok(await client.call_tool("maintenance_guide", {"topic": "decide"}))
        return out, wrong, guide

    out, wrong, guide = _session(env["token"], flow)
    assert out["position_class"] == "Pool pump" and out["period"] == "quarter" and len(out["per_period"]) == 4
    assert out["n_forecast"] == 2 and out["headline"].startswith("≈ ")
    assert wrong.is_error and "doesn't take interval" in wrong.content[0].text
    assert "class_forecast" in guide["guide"]


def test_spares_stock_levels_over_mcp(env):
    # #31: set a part's lead time with maintenance_parts update, read hold N and the
    # plan with maintenance_get class_forecast / spares_plan.
    from backend import mcp_server
    from backend.maintenance.service import Maintenance
    from backend.routers import maintenance as router

    assert "maintenance_get.spares_plan" in mcp_server.HEAVY_TOOLS
    _fitted_class()
    m = Maintenance(router._store, UID, UID)
    positions = [p["id"] for p in m.s.nodes(UID, "Position")]

    async def flow(client):
        part = _ok(await _do(client, "maintenance_parts", "create", part_number="PP-1", name="Pool pump",
                             unit_cost=500))
        for pid in positions:
            _ok(await _do(client, "maintenance_parts", "add_to_position", position_id=pid, part_id=part["id"],
                          role="replacement"))
        updated = _ok(await _do(client, "maintenance_parts", "update", part_id=part["id"], lead_time_days=90,
                                service_level=0.9))
        brief = _ok(await _get(client, "class_forecast", "Pool pump"))
        plan = _ok(await _get(client, "spares_plan", "Pool pump", period="quarter", periods=4, service_level=0.99,
                              review_days=30))
        bad = await _get(client, "spares_plan", "Pool pump", service_level=5)
        wrong = await _do(client, "maintenance_parts", "update", part_id=part["id"], position_id=positions[0])
        guide = _ok(await client.call_tool("maintenance_guide", {"topic": "decide"}))
        return updated, brief, plan, bad, wrong, guide

    updated, brief, plan, bad, wrong, guide = _session(env["token"], flow)
    assert updated["lead_time_days"] == 90 and updated["service_level"] == 0.9
    st = brief["spares"][0]["stocking"]
    assert st["lead_time_basis"] == "part" and st["service_level"] == 0.9 and st["hold"] >= 0
    assert "per_period" not in st and "risk_curve" not in st and st["summary"].startswith("Hold ")
    part = plan["parts"][0]
    assert plan["period"] == "quarter" and part["service_level"] == 0.99 and part["window_days"] == 120
    assert len(part["per_period"]) == 4 and part["risk_curve"] and part["hold_cost"] == 500 * part["hold"]
    assert bad.is_error and "service level" in bad.content[0].text
    assert wrong.is_error and "doesn't take position_id" in wrong.content[0].text
    assert "spares_plan" in guide["guide"] and "lead_time_days" in guide["guide"]


def test_reading_a_class_forecast_isnt_pro_only(free_env):
    # Like plan_economics: only fitting the class's model is Pro.
    _fitted_class()

    async def flow(client):
        return await _get(client, "class_forecast", "Pool pump")

    assert not _session(free_env["oauth"], flow).is_error


def test_nameplate_and_moves_over_mcp(env):
    async def flow(client):
        a = _ok(await _do(client, "maintenance_positions", "create", name="Pump A", position_class="Pool pump"))
        b = _ok(await _do(client, "maintenance_positions", "create", name="Pump B", position_class="Pool pump"))
        fitted = _ok(await _do(client, "maintenance_fitments", "fit", position_id=a["id"], item_name="Pump",
                               on="2025-01-01"))
        item_id = fitted["fitted"]["item"]["id"]
        item = _ok(await _do(client, "maintenance_items", "update", item_id=item_id, manufacturer="Astral",
                             model="CTX 280", serial="AX-1", nameplate={"Power": "1.1 kW", "Voltage": "240 V"}))
        assert item["nameplate"] == {"Power": "1.1 kW", "Voltage": "240 V"}
        moved = _ok(await _do(client, "maintenance_fitments", "move", item_id=item_id, position_id=b["id"],
                              on="2026-01-01"))
        classes = _ok(await _list(client, "position_classes"))
        pooled = _ok(await _get(client, "class_life_data", "Pool pump"))
        return moved, classes, pooled

    moved, classes, pooled = _session(env["token"], flow)
    assert moved["fitted_to"]["name"] == "Pump B" and len(moved["history"]) == 2
    assert classes["classes"][0]["fitments"] == 2 and len(pooled["rows"]) == 2


def test_notes_and_reading_corrections_over_mcp(env):
    from datetime import date, timedelta

    today = date.today().isoformat()
    ago = lambda n: (date.today() - timedelta(days=n)).isoformat()  # noqa: E731

    async def flow(client):
        tools = {t.name: t for t in (await client.list_tools()).tools}
        assert "\n- void(" in tools["maintenance_measurements"].description
        assert "\n- correct(" in tools["maintenance_measurements"].description
        pos = _ok(await _do(client, "maintenance_positions", "create", name="Pump"))
        point = _ok(await _do(client, "maintenance_measurements", "add_point", position_id=pos["id"], name="Hours",
                              kind="counter", unit="hours"))
        _ok(await _do(client, "maintenance_measurements", "record", point_id=point["id"], value=3000, on=ago(400)))
        stale = _ok(await _do(client, "maintenance_measurements", "record", point_id=point["id"], value=3774))
        moved = _ok(await _do(client, "maintenance_measurements", "correct", reading_id=stale["readings"][0]["id"],
                              on=ago(200), reason="old reading entered as today"))
        correction = next(r for r in moved["readings"] if r["status"] == "correction")
        no_reason = await _do(client, "maintenance_measurements", "void", reading_id=correction["id"], reason="")
        voided = _ok(await _do(client, "maintenance_measurements", "void", reading_id=correction["id"],
                               reason="duplicate"))
        read = _ok(await _get(client, "measurement_point", point["id"]))

        fitted = _ok(await _do(client, "maintenance_fitments", "fit", position_id=pos["id"], item_name="Pump"))
        item_id = fitted["fitted"]["item"]["id"]
        _ok(await _do(client, "maintenance_items", "update", item_id=item_id, notes="Diagnosis: worn bearing"))
        item = _ok(await _do(client, "maintenance_items", "update", item_id=item_id, append_note="Bearing ordered"))
        wo = _ok(await _do(client, "maintenance_work_orders", "open", position_id=pos["id"], title="Noisy",
                           notes="Grinding at start"))
        cancelled = _ok(await _do(client, "maintenance_work_orders", "cancel", work_order_id=wo["id"],
                                  reason="duplicate"))
        noted = _ok(await _do(client, "maintenance_work_orders", "update", work_order_id=wo["id"],
                              append_note="see #1"))
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


def test_tasks_failure_modes_and_past_fitments_through_mcp(env):
    async def flow(client):
        pid = _ok(await _do(client, "maintenance_positions", "create", name="Pump", position_class="Pool pump"))["id"]
        task = _ok(await _do(client, "maintenance_tasks", "create", position_id=pid, name="Clean basket", interval=1,
                             unit="weeks", source="oem", reference="Manual p. 12",
                             checklist=["Isolate", "Empty basket"]))
        assert (task["source"], task["unit"], task["outcome"]) == ("oem", "weeks", None)
        bad = await _do(client, "maintenance_tasks", "create", position_id=pid, name="X", interval=1, outcome="rtf")
        assert bad.is_error
        mode = _ok(await _do(client, "maintenance_failure_modes", "add", position_id=pid, text="Basket blocked"))
        linked = _ok(await _do(client, "maintenance_tasks", "update", task_id=task["id"], failure_mode_id=mode["id"]))
        assert linked["failure_mode"]["text"] == "Basket blocked"
        unlinked = _ok(await _do(client, "maintenance_tasks", "update", task_id=task["id"], unlink_failure_mode=True))
        assert unlinked["failure_mode"] is None

        _ok(await _do(client, "maintenance_fitments", "fit", position_id=pid, item_name="Astral", on="2024-01-01"))
        removed = _ok(await _do(client, "maintenance_fitments", "remove", position_id=pid, on="2025-01-01",
                                failure_mode_text="Seal leaking"))
        assert removed["life_data"][0]["c"] == 0
        ad_hoc = next(f for f in removed["failure_modes"] if f["ad_hoc"])
        merged = _ok(await _do(client, "maintenance_failure_modes", "merge", failure_mode_id=ad_hoc["id"],
                               into_failure_mode_id=mode["id"]))
        assert [f["text"] for f in merged["failure_modes"]] == ["Basket blocked"]
        edited = _ok(await _do(client, "maintenance_failure_modes", "update", failure_mode_id=mode["id"],
                               failure="No flow"))
        assert edited["failure"] == "No flow"

        past = _ok(await _do(client, "maintenance_fitments", "add_past", position_id=pid, start="2020-01-01",
                             end="2023-12-31", item_name="Old pump", failure_mode_text="Motor burnt out",
                             from_precision="year"))
        assert [r["c"] for r in past["life_data"]] == [2, 0]  # its start is known only to the year
        clash = await _do(client, "maintenance_fitments", "add_past", position_id=pid, start="2021-01-01",
                          end="2021-06-01", item_name="Ghost")
        assert clash.is_error and "Old pump" in clash.content[0].text
        no_end = await _do(client, "maintenance_fitments", "add_past", position_id=pid, start="2021-01-01")
        assert no_end.is_error and "action 'add_past' needs end" in no_end.content[0].text

        retired = _ok(await _do(client, "maintenance_tasks", "retire", task_id=task["id"], reason="not needed"))
        assert retired == {"retired": task["id"]}
        return True

    assert _session(env["token"], flow)


def test_structured_fields_through_mcp(env):
    """Dates with precision, warranty, replacement cost, documents and trade (batch 1, 3.1-3.5)."""

    async def flow(client):
        tools = {t.name: t for t in (await client.list_tools()).tools}
        assert "\n- add_document(" in tools["maintenance_attachments"].description
        assert "\n- remove_document(" in tools["maintenance_attachments"].description
        pid = _ok(await _do(client, "maintenance_positions", "create", name="Pump", position_class="Pool pump"))["id"]
        pos = _ok(await _do(client, "maintenance_fitments", "fit", position_id=pid, item_name="Astral", on="2022"))
        iid = pos["fitted"]["item"]["id"]
        item = _ok(await _do(client, "maintenance_items", "update", item_id=iid,
                             purchase_date={"date": "2021", "source": "owner's estimate"},
                             in_service_date={"date": "2022-03-10", "precision": "estimated"},
                             warranty={"ends_on": "2030-01-01", "coverage": "motor", "registration_required": True},
                             replacement_cost={"amount": 950, "currency": "AUD", "source": "quote"}))
        assert item["purchase_date"]["display"] == "2021" and item["in_service_date"]["display"] == "~Mar 2022"
        assert item["warranty"]["summary"].endswith("registration still to do.")
        cleared = _ok(await _do(client, "maintenance_items", "update", item_id=iid, clear=["purchase_date"]))
        assert cleared["purchase_date"] is None and cleared["warranty"]
        doc = _ok(await _do(client, "maintenance_attachments", "add_document", url="https://example.com/m.pdf",
                            target_id=iid, kind="manual", title="Manual"))
        bad = await _do(client, "maintenance_attachments", "add_document", url="data:text/html,x", target_id=iid)
        assert bad.is_error and "http" in bad.content[0].text
        _ok(await _do(client, "maintenance_attachments", "add_document", url="https://example.com/ds",
                      position_class="Pool pump", kind="datasheet"))
        cls = _ok(await _do(client, "maintenance_reliability", "set_class_costs", position_class="Pool pump",
                            replacement_cost={"amount": 800}))
        assert cls["replacement_cost"]["amount"] == 800 and cls["documents"][0]["kind"] == "datasheet"
        assert cls["costs"]["planned_cost"] is None
        _ok(await _do(client, "maintenance_attachments", "remove_document", document_id=doc["id"]))
        fixed = _ok(await _do(client, "maintenance_fitments", "correct", fitment_id=pos["fitted"]["id"],
                              from_precision="month", start="2022-04"))
        assert fixed["from_precision"] == "month"
        wo = _ok(await _do(client, "maintenance_work_orders", "open", position_id=pid, title="Hum",
                           trade="Electrician"))
        assert wo["trade"] == "Electrician" and wo["warranty"]["coverage"] == "motor"
        wo = _ok(await _do(client, "maintenance_work_orders", "update", work_order_id=wo["id"], trade="Pool tech"))
        return wo, _ok(await _get(client, "item", iid))

    wo, item = _session(env["token"], flow)
    assert wo["trade"] == "Pool tech"
    assert item["documents"] == []


def test_a_parts_list_through_mcp(env):
    """A position's parts list: added, read back on the position, the part and the
    work order, flagged when a critical spare runs short, and drawn on at closing."""

    async def flow(client):
        pid = _ok(await _do(client, "maintenance_positions", "create", name="Pump A"))["id"]
        store = _ok(await _do(client, "maintenance_locations", "create", name="Store"))["id"]
        part = _ok(await _do(client, "maintenance_parts", "create", part_number="B1", name="Pump v2"))["id"]
        listed = _ok(await _do(client, "maintenance_parts", "add_to_position", position_id=pid, part_id=part,
                               role="replacement", critical=True, min_on_hand=1, notes="needs matching button kit"))
        lid = listed["parts_list"][0]["id"]
        overview = _ok(await client.call_tool("maintenance_overview", {}))
        cover = _ok(await _list(client, "spares_cover", include_unlisted=True))
        _ok(await _do(client, "maintenance_parts", "stock", part_id=part, location_id=store, quantity=2))
        changed = _ok(await _do(client, "maintenance_parts", "update_on_position", listing_id=lid, quantity=1,
                                notes="fits from serial 4000"))
        got = _ok(await _get(client, "part", part))
        position = _ok(await _get(client, "position", pid))
        wo = _ok(await _do(client, "maintenance_work_orders", "open", position_id=pid, title="Seized"))
        detail = _ok(await _get(client, "work_order", wo["id"]))
        closed = _ok(await _do(client, "maintenance_work_orders", "close", work_order_id=wo["id"],
                               actions=[{"kind": "replace", "part_id": part, "from_location_id": store}]))
        removed = _ok(await _do(client, "maintenance_parts", "remove_from_position", listing_id=lid))
        return overview, cover, changed, got, position, detail, closed, removed

    overview, cover, changed, got, position, detail, closed, removed = _session(env["token"], flow)
    assert overview["summary"]["critical_short"] == 1 and overview["critical_spares"][0]["notes"].startswith("needs")
    assert cover["no_spare"][0]["position"]["name"] == "Pump A" and cover["without_parts_list"] == []
    assert changed["parts_list"][0]["notes"] == "fits from serial 4000"
    assert got["used_at"][0]["position"]["name"] == "Pump A" and not got["critical_short"]
    assert position["parts_list"][0]["usable_on_hand"] == 2
    assert detail["suggested_parts"][0]["part"]["part_number"] == "B1"
    assert closed["actions"][0]["fitted"]["part_number"] == "B1" and closed["parts"][0]["quantity"] == 1
    assert removed["parts_list"] == []


def test_work_order_entries_and_checklists_through_mcp(env):
    """Labour, parts, other costs and their removal, status moves and checklist ticks."""

    async def flow(client):
        pid = _ok(await _do(client, "maintenance_positions", "create", name="Pump"))["id"]
        task = _ok(await _do(client, "maintenance_tasks", "create", position_id=pid, name="Service", interval=1,
                             checklist=["Isolate", "Grease"], last_done="2020-01-01"))
        made = _ok(await _do(client, "maintenance_work_orders", "generate"))["work_orders"]
        wid = made[0]["id"]
        assert made[0]["task"]["id"] == task["id"]
        _ok(await _do(client, "maintenance_work_orders", "status", work_order_id=wid, status="in_progress"))
        _ok(await _do(client, "maintenance_work_orders", "labour", work_order_id=wid, hours=2, who="Sam", rate=90))
        _ok(await _do(client, "maintenance_work_orders", "part_used", work_order_id=wid, part="Grease", unit_cost=5))
        costed = _ok(await _do(client, "maintenance_work_orders", "cost", work_order_id=wid, description="Hire",
                               amount=50))
        ticked = _ok(await _do(client, "maintenance_work_orders", "check", work_order_id=wid, index=0))
        detail = _ok(await _get(client, "work_order", wid))
        return costed, ticked, detail

    costed, ticked, detail = _session(env["token"], flow)
    assert ticked["checklist"][0]["done"] and not ticked["checklist"][1]["done"]
    assert detail["status"] == "in_progress"
    assert costed


def test_positions_and_locations_through_mcp(env):
    """Positions are functional locations, locations the physical tree; a fitted item is where its
    position is; work orders by area."""

    async def flow(client):
        tools = {t.name: t for t in (await client.list_tools()).tools}
        guide = tools["maintenance_overview"].description
        assert "FLOC" in guide and "needs no placement" in guide and "build each once" in guide
        assert "maintenance_guide" in guide
        assert "ISN'T fitted" in tools["maintenance_items"].description
        assert "location_id" in tools["maintenance_list"].input_schema["properties"]
        site = _ok(await _do(client, "maintenance_locations", "create", name="Site"))["id"]
        sub = _ok(await _do(client, "maintenance_locations", "create", name="Substation 2", parent_id=site))["id"]
        mcc = _ok(await _do(client, "maintenance_positions", "create", name="MCC-3", location_id=sub))
        assert mcc["location"]["display"] == "Site › Substation 2"
        feeder = _ok(await _do(client, "maintenance_positions", "create", name="Feeder 13", parent_id=mcc["id"]))
        assert feeder["location"]["inherited_from"]["name"] == "MCC-3"
        pos = _ok(await _do(client, "maintenance_fitments", "fit", position_id=feeder["id"], item_name="Breaker"))
        iid = pos["fitted"]["item"]["id"]
        refused = await _do(client, "maintenance_items", "place", item_id=iid, location_id=site)
        assert refused.is_error and "position's location instead (its location_id)" in refused.content[0].text
        item = _ok(await _get(client, "item", iid))
        assert item["location"]["how"] == "fitted" and item["location"]["name"] == "Substation 2"
        wo = _ok(await _do(client, "maintenance_work_orders", "open", position_id=feeder["id"], title="Trip test"))
        there = _ok(await _list(client, "work_orders", status="open", location_id=site))
        assert [w["id"] for w in there["work_orders"]] == [wo["id"]]
        assert there["work_orders"][0]["location"]["name"] == "Substation 2"
        loc = _ok(await _get(client, "location", site))
        assert loc["systems"][0]["system"]["name"] == "MCC-3" and loc["counts"]["fitted_items"] == 1
        tree = _ok(await _list(client, "locations"))["tree"]
        assert tree[0]["all_positions"] == 2
        places = _ok(await _list(client, "places"))
        assert [(p["name"], p["positions"], p["items"], p["open_work_orders"]) for p in places["places"]] == [
            ("Site", 2, 1, 1)]
        assert places["not_placed"]["positions"] == 0 and "position_ids" not in places["not_placed"]
        moved = _ok(await _do(client, "maintenance_positions", "update", position_id=feeder["id"], location_id=site))
        assert moved["location"]["name"] == "Site" and not moved["location"]["inherited"]
        cleared = _ok(await _do(client, "maintenance_positions", "update", position_id=feeder["id"],
                                clear_location=True))
        assert cleared["location"]["inherited"]
        plan = _ok(await _do(client, "maintenance_positions", "adopt_placements"))
        assert plan == {"dry_run": True, "changes": [], "skipped": []}
        renamed = _ok(await _do(client, "maintenance_locations", "update", location_id=sub, name="Sub 2"))
        assert renamed["name"] == "Sub 2"
        return True

    assert _session(env["token"], flow)


def test_a_positions_operating_context_through_mcp(env):
    async def flow(client):
        made = _ok(await _do(client, "maintenance_positions", "create", name="Pump 4", description="Borehole pump",
                             operating_context="Runs 18 hours a day in sandy water."))
        assert made["operating_context"] == "Runs 18 hours a day in sandy water."
        assert made["description"] == "Borehole pump"
        kept = _ok(await _do(client, "maintenance_positions", "update", position_id=made["id"], name="Pump 4A"))
        assert kept["operating_context"] == "Runs 18 hours a day in sandy water."
        changed = _ok(await _do(client, "maintenance_positions", "update", position_id=made["id"],
                                operating_context="Standby; run weekly."))
        assert changed["operating_context"] == "Standby; run weekly."
        cleared = _ok(await _do(client, "maintenance_positions", "update", position_id=made["id"],
                                operating_context=""))
        assert cleared["operating_context"] == ""
        assert (_ok(await _get(client, "position", made["id"])))["operating_context"] == ""
        too_long = await _do(client, "maintenance_positions", "create", name="Pump 5", operating_context="x" * 4001)
        assert too_long.is_error and "operating context is at most 4000" in too_long.content[0].text
        return True

    assert _session(env["token"], flow)


def test_the_workspaces_time_zone_over_mcp(env):
    async def flow(client):
        before = _ok(await client.call_tool("maintenance_overview", {}))
        assert before["time_zone"] is None and before["today"]
        bad = await _do(client, "maintenance_workspace", "set_time_zone", time_zone="Mars/Olympus_Mons")
        assert bad.is_error and "isn't a time zone" in bad.content[0].text
        assert _ok(await _do(client, "maintenance_workspace", "set_time_zone", time_zone="Australia/Brisbane")) == {
            "time_zone": "Australia/Brisbane"}
        after = _ok(await client.call_tool("maintenance_overview", {}))
        assert after["time_zone"] == "Australia/Brisbane"
        return after

    from backend.services import time_zones

    after = _session(env["token"], flow)
    assert after["today"] == time_zones.today("Australia/Brisbane").isoformat()
    assert env["db"].users.find_one({"_id": UID})["time_zone"] == "Australia/Brisbane"


def test_tasks_on_items_and_locations_through_mcp(env):
    """A task takes exactly one subject; the item's and the location's tasks show on
    the item and the location, and their work orders on the item (where it is) and the
    location (a round listing the positions there)."""

    async def flow(client):
        area = _ok(await _do(client, "maintenance_locations", "create", name="Area 1"))
        pump = _ok(await _do(client, "maintenance_positions", "create", name="Pump", location_id=area["id"]))
        fitted = _ok(await _do(client, "maintenance_fitments", "fit", position_id=pump["id"], item_name="Gauge G1",
                               on="2026-01-01"))
        gauge = fitted["fitted"]["item"]["id"]
        both = await _do(client, "maintenance_tasks", "create", name="Calibrate", interval=1, unit="years",
                         position_id=pump["id"], item_id=gauge)
        assert both.is_error and "exactly one" in both.content[0].text
        cal = _ok(await _do(client, "maintenance_tasks", "create", name="Calibrate", interval=1, unit="years",
                            item_id=gauge, source="statutory", last_done="2025-01-01", while_stored="run"))
        assert cal["subject"]["kind"] == "item" and cal["while_stored"] == "run"
        by_use = await _do(client, "maintenance_tasks", "create", name="Walk", interval=10, unit="hours",
                           location_id=area["id"])
        assert by_use.is_error and "calendar" in by_use.content[0].text
        walk = _ok(await _do(client, "maintenance_tasks", "create", name="Walk the area", interval=1, unit="weeks",
                             location_id=area["id"], include_positions=True, last_done="2026-01-01"))
        meter = _ok(await _do(client, "maintenance_measurements", "add_point", item_id=gauge, kind="counter",
                              unit="hours", name="Own hours"))
        item = _ok(await _get(client, "item", gauge))
        location = _ok(await _get(client, "location", area["id"]))
        position = _ok(await _get(client, "position", pump["id"]))
        overview = _ok(await client.call_tool("maintenance_overview", {}))
        made = _ok(await _do(client, "maintenance_work_orders", "generate", horizon_days=0))["work_orders"]
        rounds = next(w for w in made if w["subject"]["kind"] == "location")
        replace = await _do(client, "maintenance_work_orders", "close", work_order_id=rounds["id"],
                            actions=[{"kind": "replace"}])
        closed = _ok(await _do(client, "maintenance_work_orders", "close", work_order_id=rounds["id"],
                               actions=[{"kind": "inspect", "finding": "ok"}]))
        return cal, walk, meter, item, location, position, overview, made, rounds, replace, closed

    cal, walk, meter, item, location, position, overview, made, rounds, replace, closed = _session(env["token"], flow)
    assert meter["item"]["name"] == "Gauge G1" and item["measurements"][0]["id"] == meter["id"]
    assert [t["id"] for t in item["tasks"]] == [cal["id"]]
    assert [t["id"] for t in location["tasks"]] == [walk["id"]]
    assert [t["id"] for t in position["item_tasks"]] == [cal["id"]] and position["tasks"] == []
    assert {t["subject"]["kind"] for t in overview["due"]} == {"item", "location"}
    assert sorted(w["subject"]["kind"] for w in made) == ["item", "location"]
    item_wo = next(w for w in made if w["subject"]["kind"] == "item")
    assert item_wo["position"]["name"] == "Pump" and item_wo["location"]["name"] == "Area 1"
    assert [c["text"] for c in rounds["checklist"]] == ["Pump"]
    assert replace.is_error and "is a location" in replace.content[0].text
    assert closed["status"] == "closed"


def test_item_classes_and_the_nameplate_flow_over_mcp(env):
    """Load the starter taxonomy, then the nameplate flow: match the maker, find or make the
    part (the model) with its class, link the item and fill in its attributes."""

    async def flow(client):
        tools = {t.name: t for t in (await client.list_tools()).tools}
        item_class_actions = tools["maintenance_item_classes"].input_schema["properties"]["action"]["enum"]
        assert item_class_actions == ["create", "update", "set_attributes", "retire", "assign", "import",
                                      "load_starter", "create_condition", "update_condition", "retire_condition",
                                      "apply_condition", "exclude_condition", "remove_condition",
                                      "import_conditions"]
        assert tools["maintenance_manufacturers"].input_schema["properties"]["action"]["enum"] == [
            "create", "update", "merge", "link", "link_by_name"]
        assert _ok(await _list(client, "item_classes"))["tree"] == []
        dry = _ok(await _do(client, "maintenance_item_classes", "load_starter"))
        assert dry["dry_run"] and dry["source"] == "Reliafy starter taxonomy"
        _ok(await _do(client, "maintenance_item_classes", "load_starter", dry_run=False))
        tree = _ok(await _list(client, "item_classes"))
        rot = next(c for c in tree["tree"] if c["name"] == "Rotating equipment")
        pump = next(c for c in rot["children"] if c["name"] == "Pump")
        cent = next(c for c in pump["children"] if c["name"] == "Centrifugal")
        mine = _ok(await _do(client, "maintenance_item_classes", "create", name="Fire pump", parent_id=cent["id"],
                             code="FP", level="type", attributes=[{"name": "Rated pressure", "unit": "kPa"}]))
        assert mine["display"] == "Rotating equipment › Pump › Centrifugal › Fire pump"
        bad = await _do(client, "maintenance_item_classes", "update", item_class_id=pump["id"], parent_id=mine["id"])
        assert bad.is_error and "inside itself" in bad.content[0].text
        got = _ok(await _get(client, "item_class", mine["id"]))
        assert got["display"] == mine["display"]

        pos = _ok(await _do(client, "maintenance_positions", "create", name="Fire pump 1"))
        fitted = _ok(await _do(client, "maintenance_fitments", "fit", position_id=pos["id"], item_name="Fire pump",
                               manufacturer="K.S.B."))
        item_id = fitted["fitted"]["item"]["id"]
        assert _ok(await _get(client, "manufacturer_match", text="K.S.B."))["match"] is None
        ksb = _ok(await _do(client, "maintenance_manufacturers", "create", name="KSB", aliases=["KSB SE & Co. KGaA"]))
        assert _ok(await _get(client, "manufacturer_match", text="K.S.B."))["match"]["id"] == ksb["id"]
        part = _ok(await _do(client, "maintenance_parts", "create", part_number="Etanorm 050-032-200",
                             name="Etanorm fire pump", item_class_id=mine["id"], manufacturer_id=ksb["id"]))
        item = _ok(await _do(client, "maintenance_items", "set_part", item_id=item_id, part_id=part["id"]))
        assert item["item_class"]["via"] == "part" and item["manufacturer_entry"]["name"] == "KSB"
        item = _ok(await _do(client, "maintenance_items", "set_attributes", item_id=item_id, values={
            "Flow": "45 m3/h", "Head": 32, "Rated pressure": 700, "Shaft seal": "packing"}))
        wrong = await _do(client, "maintenance_items", "set_attributes", item_id=item_id, values={"Flow": "12 L/s"})
        assert wrong.is_error and "m3/h" in wrong.content[0].text
        listed = _ok(await _list(client, "items", item_class_id=pump["id"]))
        by_maker = _ok(await _list(client, "parts", manufacturer_id=ksb["id"]))
        linked = _ok(await _do(client, "maintenance_manufacturers", "link_by_name", dry_run=False))
        exported = _ok(await _list(client, "item_classes", format="csv"))
        imported = _ok(await _do(client, "maintenance_item_classes", "import", csv="path,code\nSkids > Pump skid,SK\n"))
        both = await _do(client, "maintenance_item_classes", "import")
        unlinked = _ok(await _do(client, "maintenance_items", "set_part", item_id=item_id, part_id="none"))
        maker = _ok(await _get(client, "manufacturer", ksb["id"]))
        return item, listed, by_maker, linked, exported, imported, both, unlinked, maker

    item, listed, by_maker, linked, exported, imported, both, unlinked, maker = _session(env["token"], flow)
    values = {a["name"]: a["value"] for a in item["attributes"]}
    assert values["Flow"] == 45.0 and values["Rated pressure"] == 700.0 and values["Shaft seal"] == "packing"
    assert [i["name"] for i in listed["items"]] == ["Fire pump"]
    assert [p["part_number"] for p in by_maker["parts"]] == ["Etanorm 050-032-200"]
    assert [x["text"] for x in linked["links"]] == ["K.S.B."]
    assert "Rotating equipment > Pump > Centrifugal > Fire pump,FP,type" in exported["csv"]
    assert imported["dry_run"] and imported["counts"]["create"] == 2
    assert both.is_error
    assert unlinked["part"] is None
    assert maker["name"] == "KSB"


def test_conditions_over_mcp(env):
    """The register by path, applied to a site, excluded on a room, a value overridden lower
    down, read back with where each comes from; a connection's own; retired, it's gone."""

    async def flow(client):
        imported = _ok(await _do(client, "maintenance_item_classes", "import_conditions",
                                 csv="path,kind,unit\nOutdoor,,\nAmbient temperature,value,°C\nHazardous area > Zone 1,,\n"))
        assert imported["dry_run"] and imported["counts"]["create"] == 4
        _ok(await _do(client, "maintenance_item_classes", "import_conditions", dry_run=False, conditions=[
            {"path": "Outdoor"}, {"path": "Ambient temperature", "kind": "value", "unit": "°C"}]))
        made = _ok(await _do(client, "maintenance_item_classes", "create_condition", name="Seawater"))
        tree = _ok(await _list(client, "conditions"))
        ids = {c["name"]: c["id"] for c in tree["tree"]}
        assert set(ids) == {"Ambient temperature", "Outdoor", "Seawater"} and ids["Seawater"] == made["id"]
        site = _ok(await _do(client, "maintenance_locations", "create", name="Site"))
        area = _ok(await _do(client, "maintenance_locations", "create", name="Area 2", parent_id=site["id"]))
        room = _ok(await _do(client, "maintenance_locations", "create", name="Control room", parent_id=site["id"]))
        pump = _ok(await _do(client, "maintenance_positions", "create", name="Pump", location_id=area["id"]))
        plc = _ok(await _do(client, "maintenance_positions", "create", name="PLC", location_id=room["id"]))
        for target, cond, extra in ((site, "Outdoor", {}), (site, "Ambient temperature", {"value": 40}),
                                    (area, "Ambient temperature", {"value": "55 °C", "note": "sun all day"})):
            _ok(await _do(client, "maintenance_item_classes", "apply_condition", target_id=target["id"],
                          condition_id=ids[cond], **extra))
        _ok(await _do(client, "maintenance_item_classes", "exclude_condition", target_id=room["id"],
                      condition_id=ids["Outdoor"]))
        at_pump = _ok(await _get(client, "conditions", pump["id"]))
        at_plc = _ok(await _get(client, "conditions", plc["id"]))
        line = _ok(await _do(client, "maintenance_topology", "connect", from_id=pump["id"], to_id=plc["id"]))
        _ok(await _do(client, "maintenance_item_classes", "apply_condition", target_id=line["id"],
                      condition_id=ids["Seawater"]))
        at_line = _ok(await _get(client, "conditions", line["id"]))
        wrong = await _do(client, "maintenance_item_classes", "apply_condition", target_id=pump["id"],
                          condition_id=ids["Outdoor"], value=3)
        missing = await _do(client, "maintenance_item_classes", "apply_condition", condition_id=ids["Outdoor"])
        _ok(await _do(client, "maintenance_item_classes", "update_condition", condition_id=ids["Seawater"],
                      description="Raw seawater"))
        _ok(await _do(client, "maintenance_item_classes", "remove_condition", target_id=room["id"],
                      condition_id=ids["Outdoor"]))
        back = _ok(await _get(client, "conditions", plc["id"]))
        _ok(await _do(client, "maintenance_item_classes", "retire_condition", condition_id=ids["Outdoor"]))
        retired = _ok(await _get(client, "position", pump["id"]))
        exported = _ok(await _list(client, "conditions", format="csv"))
        return at_pump, at_plc, at_line, wrong, missing, back, retired, exported

    at_pump, at_plc, at_line, wrong, missing, back, retired, exported = _session(env["token"], flow)
    pump = {e["condition"]["name"]: (e["value"], e["source"]["name"]) for e in at_pump["conditions"]}
    assert pump == {"Outdoor": (None, "Site"), "Ambient temperature": (55.0, "Area 2")}
    assert [e["condition"]["name"] for e in at_plc["conditions"]] == ["Ambient temperature"]
    assert at_plc["excluded"][0]["source"]["name"] == "Control room"
    assert at_line["target"]["kind"] == "Interface" and at_line["conditions"][0]["own"]
    assert wrong.is_error and "has no value" in wrong.content[0].text
    assert missing.is_error and "target_id" in missing.content[0].text
    assert {e["condition"]["name"] for e in back["conditions"]} == {"Outdoor", "Ambient temperature"}
    assert [e["condition"]["name"] for e in retired["conditions"]] == ["Ambient temperature"]
    assert "Seawater,presence,,,Raw seawater" in exported["csv"] and "Outdoor" not in exported["csv"]


def test_product_structure_over_mcp(env):
    """A BOM imported as rows (dry run, then for real, then again with no change), a loop
    refused with its path, a line added and changed by hand, the structure and where used
    read back, a level set and the list renamed, and positions made from the structure."""
    rows = [{"NHA": "", "PN": "SYS-1", "Nomenclature": "Cooling system", "Indenture level": "System"},
            {"NHA": "SYS-1", "PN": "PU-1", "Qty": "2", "Nomenclature": "Pump unit", "Indenture level": "Subsystem"},
            {"NHA": "PU-1", "PN": "MTR-1", "Qty": "1", "Nomenclature": "Motor", "Indenture level": "LRU"},
            {"NHA": "MTR-1", "PN": "BRG-1", "Qty": "2", "Nomenclature": "Bearing", "Indenture level": "Component"},
            {"NHA": "PU-1", "PN": "BRG-1", "Qty": "2"}]

    async def flow(client):
        dry = _ok(await _do(client, "maintenance_parts", "import_bom", rows=rows))
        done = _ok(await _do(client, "maintenance_parts", "import_bom", rows=rows, dry_run=False))
        again = _ok(await _do(client, "maintenance_parts", "import_bom", rows=rows, dry_run=False))
        parts = {p["part_number"]: p["id"] for p in _ok(await _list(client, "parts"))["parts"]}
        loop = await _do(client, "maintenance_parts", "add_component", part_id=parts["BRG-1"],
                         component_id=parts["SYS-1"])
        seal = _ok(await _do(client, "maintenance_parts", "create", part_number="S-1", name="Seal"))
        _ok(await _do(client, "maintenance_parts", "add_component", part_id=parts["PU-1"], component_id=seal["id"],
                      ref="S1"))
        changed = _ok(await _do(client, "maintenance_parts", "update_component", part_id=parts["PU-1"],
                                component_id=seal["id"], quantity=3))
        _ok(await _do(client, "maintenance_parts", "remove_component", part_id=parts["PU-1"], component_id=seal["id"]))
        structure = _ok(await _get(client, "part_structure", parts["SYS-1"]))
        used = _ok(await _get(client, "where_used", parts["BRG-1"]))
        level = _ok(await _do(client, "maintenance_parts", "set_level", part_id=seal["id"], level="sru"))
        levels = _ok(await _do(client, "maintenance_parts", "set_levels",
                               levels=["System", "Subsystem", "LRU", "Shop unit", "Component"],
                               renamed={"SRU": "Shop unit"}))
        top = _ok(await _do(client, "maintenance_positions", "create", name="Cooling"))
        positions = _ok(await _do(client, "maintenance_parts", "positions_from_structure", part_id=parts["SYS-1"],
                                  position_id=top["id"], levels=["System", "Subsystem"]))
        made = _ok(await _do(client, "maintenance_parts", "positions_from_structure", part_id=parts["SYS-1"],
                             position_id=top["id"], levels=["System", "Subsystem"], dry_run=False))
        stray = await _do(client, "maintenance_parts", "set_level", part_id=seal["id"], level="LRU", ref="x")
        return dry, done, again, loop, changed, structure, used, level, levels, positions, made, stray

    dry, done, again, loop, changed, structure, used, level, levels, positions, made, stray = _session(
        env["token"], flow)
    assert dry["dry_run"] and dry["counts"]["parts_created"] == 4 and dry["counts"]["lines_added"] == 4
    assert not done["dry_run"] and again["counts"]["unchanged"] == 4 and again["counts"]["lines_added"] == 0
    assert loop.is_error and "BRG-1 › SYS-1 › PU-1" in loop.content[0].text
    assert {c["part_number"]: c["qty"] for c in changed["tree"]["children"]}["S-1"] == 3
    assert {r["part_number"]: r["total"] for r in structure["rollup"]} == {"PU-1": 2, "MTR-1": 2, "BRG-1": 8}
    assert [a["part_number"] for a in used["assemblies"]] == ["SYS-1", "PU-1", "MTR-1"]
    assert level["level"] == "SRU"
    assert [x["name"] for x in levels["levels"]][3] == "Shop unit"
    assert positions["dry_run"] and positions["counts"]["create"] == 3
    assert not made["dry_run"] and made["counts"]["create"] == 3
    assert stray.is_error and "ref" in stray.content[0].text


def test_an_over_long_name_is_refused_with_what_to_do_and_generate_lists_skipped(env):
    """The same limit and message as the app; generate's result has a skipped list."""

    async def flow(client):
        pid = _ok(await _do(client, "maintenance_positions", "create", name="Filter"))["id"]
        refused = await _do(client, "maintenance_tasks", "create", position_id=pid, name="x" * 397, interval=1)
        titled = await _do(client, "maintenance_work_orders", "open", position_id=pid, title="y" * 250)
        _ok(await _do(client, "maintenance_tasks", "create", position_id=pid, name="Check", interval=1,
                      last_done="2020-01-01"))
        made = _ok(await _do(client, "maintenance_work_orders", "generate"))
        return refused, titled, made

    refused, titled, made = _session(env["token"], flow)
    assert refused.is_error and (
        "The task's name is at most 200 characters; this one is 397. Shorten it and put the detail in the "
        "task's instructions.") in refused.content[0].text
    assert titled.is_error and "at most 200 characters; this one is 250" in titled.content[0].text
    assert made["skipped"] == [] and len(made["work_orders"]) == 1
