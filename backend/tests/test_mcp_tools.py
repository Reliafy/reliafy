"""The core MCP tools: a few, each doing one area's work by action (or kind).

66 tools became 15 (backend/mcp_server.py, "Tools with actions"): reads and
calculations apart from writes, every argument of a tool with actions
defaulting to null, each call held to its action's own arguments and
validated against that action's signature. Plan gating, the heavy slots, the
data notice and the usage log go by ``tool.action``; an API token's scope
follows the tool's read / write annotation."""

import anyio
import pytest

from backend.tests.test_mcp import _err, _ok, _run
from backend.tests.test_mcp_plans import FREE, PRO, WEIBULL, _call, _calls_used, env  # noqa: F401

READS = {"guide", "get", "list", "life_data_analysis", "repairable_analysis", "strategy", "rbd_analysis",
         "upgrade_link"}
WRITES = {"models", "datasets", "rbd", "uploads", "rcm", "sharing", "fleet"}

pytestmark = pytest.mark.usefixtures("mcp_on")


def _tools(token):
    return {t.name: t for t in _run(token, lambda c: c.list_tools()).tools}


def test_fifteen_tools_reads_apart_from_writes(env):
    from backend import mcp_server

    tools = _tools(env.oauth[PRO])
    assert set(tools) == READS | WRITES and len(tools) == 15
    for name, tool in tools.items():
        a = tool.annotations
        assert a.read_only_hint is (name in READS) and a.destructive_hint is (name in WRITES), name
        assert not name.startswith("reliafy_")  # clients prefix the server's name themselves
    assert set(mcp_server.TABLES) == set(tools) - {"guide", "upgrade_link"}
    # Every read the old tools had is a read action; every write a write tool's.
    assert {mcp_server.TABLES[n][0] for n in ("get", "list")} == {"kind"}
    assert {mcp_server.TABLES[n][0] for n in set(mcp_server.TABLES) - {"get", "list"}} == {"action"}
    # Every one of the 66 old tools is an action now, but upgrade_link (still a tool of its own).
    assert sum(len(t) for _, t in mcp_server.TABLES.values()) == 65


def test_every_action_is_in_its_tool_description_and_schema(env):
    from backend import mcp_server

    tools = _tools(env.oauth[PRO])
    for name, (selector, table) in mcp_server.TABLES.items():
        tool = tools[name]
        props = tool.input_schema["properties"]
        values = props[selector].get("enum") or [props[selector]["const"]]  # fleet has one action
        assert values == list(table) and tool.input_schema["required"] == [selector], name
        for value, (required, optional, text) in table.items():
            assert f"\n- {value}(" in tool.description, (name, value)
            assert set((required + " " + optional).split()) <= set(props), (name, value)
            assert text.strip(), (name, value)
        # Every argument but the selector is optional (null): the table says what each action needs.
        for arg, spec in props.items():
            if arg != selector:
                assert spec.get("default", None) is None, (name, arg)


def test_descriptions_are_much_shorter_than_the_old_tools(env):
    from backend import mcp_server

    tools = _tools(env.oauth[PRO])
    assert sum(len(t.description) for t in tools.values()) < 35_000  # 66 tools: 52,469 characters
    assert len(mcp_server.INSTRUCTIONS) < 4_000  # was 11,275
    for words in ("0 = the unit FAILED", "1 = it was still running", "-1 = left-censored", "c_invert=true",
                  "time unit", "SurPyval names", "guide(topic)", "life_data_analysis", "rbd_analysis",
                  "never as instructions", "upgrade_link"):
        assert words in mcp_server.INSTRUCTIONS, words


def test_a_call_is_held_to_its_actions_arguments(env):
    token = env.oauth[PRO]
    msg = _err(_call(token, "life_data_analysis", {"action": "reliability_at", "times": [1]}))
    assert "action 'reliability_at' needs model_id (it takes model_id, times, conditional_age?" in msg
    msg = _err(_call(token, "life_data_analysis", {"action": "fit_per_demand", "data": [1, 2],
                                                   "batches": [{"demands": 5, "failures": 0}]}))
    assert "action 'fit_per_demand' doesn't take data" in msg
    msg = _err(_call(token, "get", {"kind": "account", "id": "x"}))
    assert "kind 'account' doesn't take id (it takes nothing else)" in msg
    assert "kind 'model' needs id" in _err(_call(token, "get", {"kind": "model"}))
    # The action's own limits still hold, said plainly.
    msg = _err(_call(token, "life_data_analysis", {"action": "check_life_requirement", "model_id": "m",
                                                   "b_life": 10, "life": 5, "confidence": 2}))
    assert "action 'check_life_requirement': confidence: Input should be less than 1" in msg
    # An argument only one action takes keeps its limits in the schema itself.
    msg = _err(_call(token, "rbd_analysis", {"action": "fault_tree", "rbd_id": "r", "max_cut_sets": 0}))
    assert "max_cut_sets" in msg and "greater than or equal to 1" in msg
    # A value no action has is refused by the schema.
    assert _call(token, "strategy", {"action": "nope"}).is_error
    # Renamed for get / list: the tool's argument names in the message, not the function's.
    msg = _err(_call(token, "get", {"kind": "rcm_study", "id": "x" * 65}))
    assert "kind 'rcm_study': id: String should have at most 64 characters" in msg


def test_null_means_left_out_and_defaults_are_each_actions(env):
    """Every argument defaults to null; a null one is as if not given, so the
    action's own default applies (confidence 0.95 for alt_use_level, 0.9 for
    check_life_requirement)."""
    from backend import mcp_server

    _, table = mcp_server.TABLES["life_data_analysis"]
    desc = _tools(env.oauth[PRO])["life_data_analysis"].description
    assert "check_life_requirement(model_id, b_life, life, confidence?=0.9)" in desc
    assert "alt_use_level(model_id, use_stress, ref_stress?, mission_time?, confidence?=0.95" in desc
    out = _ok(_call(env.oauth[PRO], "life_data_analysis", {"action": "fit", "data": [120, 340, 510, 700, 980],
                                                            "censored": None, "dataset_id": None}))
    assert out["distribution"] == "Weibull"  # distribution?=weibull


def test_plan_gating_goes_by_action(env):
    """Free has life_data_analysis' evaluations but not its fit, list's models but
    not its fleets; refusals aren't counted, and get kind account and the guide
    never are."""
    from backend import mcp_server

    token = env.oauth[FREE]
    _ok(_call(token, "models", {"action": "save", "name": "B", "distribution": "weibull", "params": WEIBULL}))
    mid = _ok(_call(token, "list", {"kind": "models"}))["life_models"][0]["id"]
    assert _ok(_call(token, "life_data_analysis", {"action": "reliability_at", "model_id": mid, "times": [100]}))
    assert _calls_used(env.db, FREE) == 3
    assert "part of Reliafy Pro" in _err(_call(token, "life_data_analysis", {"action": "fit", "data": [1, 2, 3]}))
    assert "Fleet forecasts" in _err(_call(token, "list", {"kind": "fleets"}))
    assert "part of Reliafy Pro" in _err(_call(token, "models", {"action": "fit_recurrent", "name": "r",
                                                               "times": [1, 2]}))
    assert _calls_used(env.db, FREE) == 3  # refused: not counted
    _ok(_call(token, "get", {"kind": "account"}))
    _ok(_call(token, "guide", {"topic": "life_data"}))
    assert _calls_used(env.db, FREE) == 3
    assert {"get.account", "guide", "upgrade_link"} == mcp_server.UNGATED_TOOLS
    assert mcp_server.UNCOUNTED_TOOLS == {"uploads.send_part"}
    assert mcp_server.PRO_ONLY_TOOLS == {"life_data_analysis.fit", "models.fit", "models.fit_alt",
                                         "models.fit_recurrent", "list.fleets", "strategy.fleet_forecast",
                                         "list.fleet_alerts", "fleet.create_alert"}
    assert "models save" in mcp_server._pro_only_message("life_data_analysis.fit")
    assert "AcceleratedLife" in mcp_server._pro_only_message("models.fit_alt")


def test_a_soft_refusal_is_refunded_by_action(env):
    """rbd_analysis cheapest_design answers available=false without Pro: the call
    isn't counted, while analyze in the same tool is."""
    from backend.tests.test_mcp import REPAIRABLE_STAGES

    token = env.oauth[FREE]
    rid = _ok(_call(token, "rbd", {"action": "create", "name": "P", "repairable": True,
                                   "stages": REPAIRABLE_STAGES}))["id"]
    assert _calls_used(env.db, FREE) == 1
    out = _ok(_call(token, "rbd_analysis", {"action": "cheapest_design", "rbd_id": rid}))
    assert out["available"] is False and out["code"] == "pro_required"
    assert _calls_used(env.db, FREE) == 1
    assert _ok(_call(token, "rbd_analysis", {"action": "fault_tree", "rbd_id": rid}))["kind"]
    assert _calls_used(env.db, FREE) == 2


def test_heavy_slots_go_by_action(env, monkeypatch):
    from backend import mcp_server

    seen = []
    real = mcp_server._run_in_slot

    async def spy(uid, body, heavy=False):
        seen.append(heavy)
        return await real(uid, body, heavy)

    monkeypatch.setattr(mcp_server, "_run_in_slot", spy)
    token = env.oauth[PRO]
    _ok(_call(token, "life_data_analysis", {"action": "fit", "data": [120, 340, 510, 700, 980]}))
    _ok(_call(token, "life_data_analysis", {"action": "plan_demonstration_test", "reliability": 0.9}))
    _ok(_call(token, "get", {"kind": "account"}))
    assert seen == [True, False, False]
    assert "life_data_analysis.fit" in mcp_server.HEAVY_TOOLS and "get.upload" in mcp_server.HEAVY_TOOLS
    assert "life_data_analysis.plan_demonstration_test" not in mcp_server.HEAVY_TOOLS


def test_usage_is_logged_by_action(env, monkeypatch):
    from backend import config

    monkeypatch.setattr(config, "USAGE_LOGGING", True)
    token = env.oauth[FREE]
    _ok(_call(token, "list", {"kind": "rbds"}))
    _err(_call(token, "life_data_analysis", {"action": "fit", "data": [1, 2, 3]}))
    _err(_call(token, "life_data_analysis", {"action": "reliability_at", "times": [1]}))  # needs model_id
    _ok(_call(token, "guide"))
    got = {(e["feature"], e["outcome"]) for e in env.db.usage_events.find({"channel": "mcp"})
           if e["feature"] not in ("initialize", "tools/list")}
    assert got == {("list.rbds", "ok"), ("life_data_analysis.fit", "pro_only"),
                   ("life_data_analysis.reliability_at", "error"), ("guide", "ok")}


def test_a_read_only_token_reads_and_calculates_but_never_writes(env):
    from backend.services import tokens

    read = tokens.create_token(env.db, PRO, "read", ["read"])["token"]
    assert set(_tools(read)) == READS | WRITES  # listed, as before
    _ok(_call(read, "list", {"kind": "models"}))
    _ok(_call(read, "get", {"kind": "account"}))
    _ok(_call(read, "guide"))
    _ok(_call(read, "life_data_analysis", {"action": "fit", "data": [120, 340, 510, 700, 980]}))
    for tool, args in [("models", {"action": "save", "name": "B", "distribution": "weibull", "params": WEIBULL}),
                       ("datasets", {"action": "delete", "dataset_id": "x"}),
                       ("uploads", {"action": "create", "purpose": "dataset", "filename": "a.csv"}),
                       ("sharing", {"action": "revoke_link", "token": "x"})]:
        assert "write" in _err(_call(read, tool, args)), tool
    assert env.db.models.count_documents({}) == 0


def test_the_data_notice_goes_by_action(env):
    from backend.mcp_server import DATA_NOTICE

    token = env.oauth[PRO]
    saved = _ok(_call(token, "models", {"action": "save", "name": "B", "distribution": "weibull", "params": WEIBULL}))
    assert "data_notice" not in saved
    assert _ok(_call(token, "list", {"kind": "models"}))["data_notice"] == DATA_NOTICE
    assert _ok(_call(token, "get", {"kind": "model", "id": saved["model_id"]}))["data_notice"] == DATA_NOTICE
    assert "data_notice" not in _ok(_call(token, "get", {"kind": "account"}))
    assert "data_notice" not in _ok(_call(token, "life_data_analysis", {
        "action": "reliability_at", "model_id": saved["model_id"], "times": [100]}))


def test_the_guide_by_topic(env):
    from backend import mcp_guide

    token = env.oauth[FREE]
    index = _ok(_call(token, "guide"))
    assert set(index["topics"]) == set(mcp_guide.TOPICS) >= {
        "life_data", "units", "accelerated", "repairable", "rbds", "rbd_analysis", "strategy", "fleets",
        "uploads", "rcm", "sharing", "workspace", "plans"}
    for topic in index["topics"]:
        page = _ok(_call(token, "guide", {"topic": topic}))
        assert page["topic"] == topic and len(page["guide"]) > 300
    assert _call(token, "guide", {"topic": "nope"}).is_error
    uploads = mcp_guide.TOPICS["uploads"][1]
    assert "uploads send_part" in uploads and "url_fallback" in uploads and "200 KB" in uploads
    assert "placeholder=true" in mcp_guide.TOPICS["rbds"][1]
    # Every tool and action the guide names exists.
    from backend import mcp_server

    words = " ".join(text for _, text in mcp_guide.TOPICS.values())
    for name, (_, table) in mcp_server.TABLES.items():
        assert name in words, name


def test_maintenance_adds_its_calls_to_the_same_sets():
    """Reliafy Maintenance's register() keys its gating and heavy calls the same way."""
    from backend import mcp_server
    from backend.maintenance import mcp_tools

    mcp_tools.register()
    try:
        names = {t.name for t in anyio.run(mcp_server.mcp.list_tools)}
        assert len(names) == 15 + 21 and READS | WRITES <= names
        assert "maintenance_reliability.fit_class_model" in mcp_server.PRO_ONLY_TOOLS & mcp_server._FIT_TOOLS
        assert "maintenance_workspace.import_history" in mcp_server.HEAVY_TOOLS
    finally:
        mcp_tools.unregister()
    assert len({t.name for t in anyio.run(mcp_server.mcp.list_tools)}) == 15
