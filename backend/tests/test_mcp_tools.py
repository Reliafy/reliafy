"""The core MCP tools: six, each doing its work by action (or kind).

66 tools became 15 (Oct 2026), then 6 (Nov 2026: backend/mcp_server.py, "The
tools"): get / list read, analyse calculates, change writes, report_problem
and guide. Reads and calculations sit apart from writes, every argument of a
tool with actions defaults to null, each call is held to its action's own
arguments and validated against that action's signature. Plan gating, the
heavy slots, the data notice and the usage log go by ``tool.action``; an API
token's scope follows the tool's read / write annotation. The earlier names
are gone; ``LEGACY`` below maps every one of their actions to its new home."""

import json
import re

import anyio
import pytest

from backend.tests.test_mcp import _err, _ok, _run
from backend.tests.test_mcp_plans import FREE, PRO, WEIBULL, _call, _calls_used, env  # noqa: F401

READS = {"guide", "get", "list", "analyse"}
WRITES = {"change"}
REPORTS = {"report_problem"}  # writes Reliafy's own feedback, never the workspace

pytestmark = pytest.mark.usefixtures("mcp_on")

# Every tool name before Nov 2026 and where each of its actions went: old tool ->
# (its choosing argument, {old action: (new tool, new action)}); upgrade_link,
# which had no actions, maps from "". The old names no longer answer; this table
# (also in python/CHANGELOG.md, 0.5.0) proves nothing was lost.
LEGACY: dict = {
    "get": ("kind", {k: ("get", k) for k in ("model", "dataset", "rbd", "rbd_run", "job", "upload", "account")}),
    "list": ("kind", {k: ("list", k) for k in ("models", "datasets", "rbds", "rbd_runs", "fleets", "fleet_alerts",
                                               "share_links", "workspace_changes")}),
    "life_data_analysis": ("action", {k: ("analyse", k) for k in (
        "fit", "fit_per_demand", "reliability_at", "check_life_requirement", "compare_groups", "alt_use_level",
        "plan_demonstration_test", "plan_sequential_test", "plan_life_test", "plan_accelerated_test",
        "plan_comparison", "fit_joint", "predict_joint")}),
    "repairable_analysis": ("action", {k: ("analyse", k) for k in ("next_failure", "growth_projection")}),
    "strategy": ("action", {k: ("analyse", k) for k in (
        "optimal_replacement", "failure_finding_interval", "optimal_overhaul", "fleet_forecast",
        "calendar_replacement", "next_replacement")}),
    "rbd_analysis": ("action", {"analyze": ("analyse", "rbd"), **{k: ("analyse", f"rbd_{k}") for k in (
        "quote_simulation", "sensitivity", "optimise_intervals", "cheapest_design", "compare", "fault_tree",
        "allocate_targets", "system_history", "export_python", "export_json")}}),
    "models": ("action", {k: ("change", f"model_{k}") for k in (
        "fit", "save", "fit_alt", "fit_recurrent", "fit_joint", "update", "delete")}),
    "datasets": ("action", {k: ("change", f"dataset_{k}") for k in (
        "upload", "add_measurements", "remove_measurements", "split", "update", "delete")}),
    "rbd": ("action", {k: ("change", f"rbd_{k}") for k in ("create", "clone", "edit", "delete", "upload_outage_log")}),
    "uploads": ("action", {"create": ("change", "upload_create"), "send_part": ("change", "upload_send_part"),
                           "import_rbd": ("change", "import_rbd"), "import_excel": ("change", "import_excel")}),
    "sharing": ("action", {"create_link": ("change", "share_link"), "create_report": ("change", "share_report"),
                           "revoke_link": ("change", "share_revoke")}),
    "fleet": ("action", {"create_alert": ("change", "fleet_create_alert")}),
    "library": ("action", {"search": ("list", "library"), "get": ("get", "library_record"),
                           "sources": ("list", "library_sources")}),
    "report_problem": ("action", {k: ("report_problem", k) for k in ("report", "status", "triage", "update")}),
    "upgrade_link": ("", {"": ("get", "upgrade_link")}),
}

# Actions added since the six tools (no earlier tool had them), and those among
# them that are heavy (a compute slot) or whose results carry people's text (the
# data notice). A PR that adds core actions adds them here, under its own comment.
NEW_ACTIONS = {
    # A Bayesian update of a baseline life model with a few failures (Nov 2026).
    ("analyse", "bayes_update"),
    # Maintainability prediction (Nov 2026).
    ("get", "maintainability_prediction"), ("list", "maintainability_predictions"), ("analyse", "maintainability"),
    ("change", "maintainability_save"), ("change", "maintainability_update"), ("change", "maintainability_delete"),
    # Reliability prediction: a parts count from handbook base rates (Nov 2026).
    ("analyse", "prediction"), ("get", "prediction"), ("list", "predictions"),
    ("change", "prediction_save"), ("change", "prediction_update"), ("change", "prediction_delete"),
    # A user's own data libraries: saved life models as records (Nov 2026).
    ("get", "library"), ("list", "libraries"), ("change", "library_create"), ("change", "library_update"),
    ("change", "library_delete"), ("change", "library_add_model"), ("change", "library_remove_record"),
    # Fault trees built by hand (Nov 2026).
    ("get", "fault_tree"), ("list", "fault_trees"), ("analyse", "fault_tree"), ("change", "fault_tree_save"),
    ("change", "fault_tree_delete"),
}
NEW_HEAVY = {"analyse.fault_tree"}
NEW_TEXT = {"get.maintainability_prediction", "list.maintainability_predictions",
            "list.fault_trees", "get.fault_tree", "analyse.fault_tree",
            # A user library's name, notes and record labels are the user's words.
            "get.library", "list.libraries",
            # A reliability prediction's lines and assemblies are named by people (or a product's parts list).
            "list.predictions", "get.prediction", "analyse.prediction"}

# The earlier tools' sets (to 1 Nov 2026), by their old keys: the new sets must be these, renamed.
OLD_PRO_ONLY = {"life_data_analysis.fit", "models.fit", "models.fit_alt", "models.fit_recurrent", "list.fleets",
                "strategy.fleet_forecast", "list.fleet_alerts", "fleet.create_alert",
                "life_data_analysis.fit_joint", "models.fit_joint"}
OLD_HEAVY = {"rbd_analysis.analyze", "rbd_analysis.compare", "rbd_analysis.cheapest_design",
             "rbd_analysis.sensitivity", "rbd_analysis.fault_tree", "rbd_analysis.optimise_intervals",
             "rbd_analysis.allocate_targets", "rbd_analysis.system_history", "life_data_analysis.fit",
             "life_data_analysis.alt_use_level", "life_data_analysis.compare_groups", "models.fit", "models.fit_alt",
             "models.fit_recurrent", "strategy.fleet_forecast", "uploads.import_rbd", "uploads.import_excel",
             "get.upload", "datasets.upload", "rbd.upload_outage_log", "life_data_analysis.fit_joint",
             "models.fit_joint"}
OLD_UNGATED = {"upgrade_link", "get.account", "guide", "report_problem.report", "report_problem.status",
               "report_problem.triage", "report_problem.update"}
OLD_UNCOUNTED = {"uploads.send_part", "library.search", "library.get", "library.sources"}
OLD_TEXT = {"list.models", "get.model", "list.datasets", "get.dataset", "list.rbds", "get.rbd", "get.upload",
            "list.workspace_changes", "list.fleets", "list.share_links", "library.search", "library.get"}
# The earlier tools and their actions (80, plus upgrade_link and guide).
OLD_TOOLS = {
    "get": {"model", "dataset", "rbd", "rbd_run", "job", "upload", "account"},
    "list": {"models", "datasets", "rbds", "rbd_runs", "fleets", "fleet_alerts", "share_links", "workspace_changes"},
    "life_data_analysis": {"fit", "fit_per_demand", "reliability_at", "check_life_requirement", "compare_groups",
                           "alt_use_level", "plan_demonstration_test", "plan_sequential_test", "plan_life_test",
                           "plan_accelerated_test", "plan_comparison", "fit_joint", "predict_joint"},
    "repairable_analysis": {"next_failure", "growth_projection"},
    "strategy": {"optimal_replacement", "failure_finding_interval", "optimal_overhaul", "fleet_forecast",
                 "calendar_replacement", "next_replacement"},
    "rbd_analysis": {"analyze", "quote_simulation", "sensitivity", "optimise_intervals", "cheapest_design",
                     "compare", "fault_tree", "allocate_targets", "system_history", "export_python", "export_json"},
    "models": {"fit", "save", "fit_alt", "fit_recurrent", "fit_joint", "update", "delete"},
    "datasets": {"upload", "add_measurements", "remove_measurements", "split", "update", "delete"},
    "rbd": {"create", "clone", "edit", "delete", "upload_outage_log"},
    "uploads": {"create", "send_part", "import_rbd", "import_excel"},
    "sharing": {"create_link", "create_report", "revoke_link"},
    "fleet": {"create_alert"},
    "library": {"search", "get", "sources"},
    "report_problem": {"report", "status", "triage", "update"},
    "upgrade_link": {""},
}

def _tools(token):
    return {t.name: t for t in _run(token, lambda c: c.list_tools()).tools}


def _new_key(old: str) -> str:
    tool, _, action = old.partition(".")
    if tool == "guide":
        return "guide"
    new_tool, new_action = LEGACY[tool][1][action]
    return f"{new_tool}.{new_action}"


def test_every_earlier_tool_and_action_has_its_new_home():
    """The mapping table, old tool/action -> new tool/action: every earlier
    capability is reachable, and every new action is some earlier one's."""
    from backend import mcp_server

    assert {old: set(table) for old, (_, table) in LEGACY.items()} == OLD_TOOLS
    targets = set()
    for old, (selector, table) in LEGACY.items():
        for action, (tool, new_action) in table.items():
            assert new_action in mcp_server.TABLES[tool][1], (old, action)
            targets.add((tool, new_action))
    every_new = {(t, a) for t, (_, table) in mcp_server.TABLES.items() for a in table}
    assert targets | NEW_ACTIONS == every_new and not targets & NEW_ACTIONS
    assert sum(len(t) for t in OLD_TOOLS.values()) == 81  # 80 actions + upgrade_link
    assert len(every_new) == 81 + len(NEW_ACTIONS)


def test_gating_and_slots_are_the_earlier_ones_renamed():
    """Pricing is unchanged: the Pro-only, ungated, uncounted, heavy and
    data-notice calls are exactly the earlier ones under their new names."""
    from backend import mcp_server

    # Plus the Bayesian update (Nov 2026): fitting, so Pro like the rest.
    assert {_new_key(k) for k in OLD_PRO_ONLY} | {"analyse.bayes_update"} == mcp_server.PRO_ONLY_TOOLS
    assert {_new_key(k) for k in OLD_HEAVY} | NEW_HEAVY == mcp_server.HEAVY_TOOLS
    assert {_new_key(k) for k in OLD_UNGATED} == mcp_server.UNGATED_TOOLS
    assert {_new_key(k) for k in OLD_UNCOUNTED} == mcp_server.UNCOUNTED_TOOLS
    assert {_new_key(k) for k in OLD_TEXT} | NEW_TEXT == mcp_server.TEXT_RESULT_TOOLS
    assert mcp_server._FIT_TOOLS == {_new_key(k) for k in OLD_PRO_ONLY if "fleet" not in k} | {"analyse.bayes_update"}


def test_earlier_names_are_gone(env):
    from backend import mcp_server

    listed = set(_tools(env.oauth[PRO]))
    assert listed == READS | WRITES | REPORTS
    for old in set(LEGACY) - listed:
        assert old not in {t.name for t in anyio.run(mcp_server.mcp.list_tools)}
        assert _call(env.oauth[PRO], old, {}).is_error, old


def test_six_tools_reads_apart_from_writes(env):
    from backend import mcp_server

    tools = _tools(env.oauth[PRO])
    assert set(tools) == READS | WRITES | REPORTS and len(tools) == 6
    for name, tool in tools.items():
        a = tool.annotations
        assert a.read_only_hint is (name in READS) and a.destructive_hint is (name in WRITES), name
        assert not name.startswith("reliafy_")  # clients prefix the server's name themselves
    assert set(mcp_server.TABLES) == set(tools) - {"guide"}
    assert {mcp_server.TABLES[n][0] for n in ("get", "list")} == {"kind"}
    assert {mcp_server.TABLES[n][0] for n in set(mcp_server.TABLES) - {"get", "list"}} == {"action"}
    assert sum(len(t) for _, t in mcp_server.TABLES.values()) == 81 + len(NEW_ACTIONS)


def test_every_action_is_in_its_tool_description_and_schema(env):
    """tools/list carries each tool's actions and an open args object; what
    each action needs is in the description, everything in its own schema."""
    from backend import mcp_server

    tools = _tools(env.oauth[PRO])
    for name, (selector, table) in mcp_server.TABLES.items():
        tool = tools[name]
        # "Required: a/b(x, y); c(z)." — actions needing the same arguments share an entry.
        listed = {}
        for values, need in re.findall(r"([\w/]+)\(([^)]*)\)", tool.description.partition(" Required: ")[2]):
            listed.update(dict.fromkeys(values.split("/"), need))
        props = tool.input_schema["properties"]
        assert set(props) == {selector, "args"} and tool.input_schema["required"] == [selector], name
        assert props[selector]["enum"] == list(table) and props["args"]["type"] == "object", name
        for value, (required, optional, text) in table.items():
            assert text.strip(), (name, value)
            if required.strip() and (name, value) not in mcp_server.ONE_OF:
                assert listed.get(value) == ", ".join(required.split()), (name, value)
            own = mcp_server.ACTION_SCHEMAS[(name, value)]
            assert set(required.split()) == set(own["required"]), (name, value)
            assert set((required + " " + optional).split()) == set(own["properties"]), (name, value)


def test_the_listed_tools_are_small(env):
    """Every connection loads tools/list and the instructions into the agent's
    context: under 8,000 characters for the six tools (192,060 as 16 tools with
    full schemas; 7,914 with the maintainability prediction, fault tree and
    reliability prediction actions, Nov 2026, after shortening the shared
    args and guide text; 7,972 with the user libraries' seven actions, after
    trimming the tool intros, titles and the replacement one-liners) and
    about 1,000 for the instructions (3,663 before)."""
    from backend import mcp_server

    tools = _tools(env.oauth[PRO])
    listed = json.dumps([t.model_dump(mode="json", by_alias=True, exclude_none=True) for t in tools.values()])
    assert len(listed) < 8_000
    assert len(mcp_server.INSTRUCTIONS) < 1_100
    for words in ("0 = the unit FAILED", "1 = still running", "-1 = left-censored", "2 = interval-censored",
                  "c_invert=true", "time unit", "Never invent failure data", "point values", "don't retry",
                  "guide(topic)", "guide(action=", "analyse", "change", "never instructions"):
        assert words in mcp_server.INSTRUCTIONS, words


def test_a_call_without_its_arguments_is_told_where_they_go(env):
    """Arguments go under args; a call that leaves them out (or puts them
    beside the action, where the schema has no place for them) is refused with
    what's missing and where the action's schema is."""
    token = env.oauth[PRO]
    msg = _err(_run(token, lambda c: c.call_tool("analyse", {"action": "reliability_at", "args": {"times": [1]}})))
    assert "needs model_id" in msg and "Arguments go in args" in msg and "guide(action='analyse.reliability_at')" in msg
    msg = _err(_run(token, lambda c: c.call_tool("analyse", {"action": "reliability_at", "model_id": "m",
                                                            "times": [1], "args": None})))
    assert "needs model_id, times" in msg and "guide(action='analyse.reliability_at')" in msg
    msg = _err(_run(token, lambda c: c.call_tool("analyse", {"action": "check_life_requirement", "args": {
        "model_id": "m", "b_life": 10, "life": 5, "confidence": 2}})))
    assert "confidence: Input should be less than 1" in msg and "guide(action='analyse.check_life_requirement')" in msg
    out = _ok(_run(token, lambda c: c.call_tool("analyse", {"action": "plan_demonstration_test",
                                                           "args": {"reliability": 0.95}})))
    assert out["units"] == 59


def test_the_guide_gives_any_actions_full_schema(env):
    token = env.oauth[PRO]
    out = _ok(_call(token, "guide", {"action": "analyse.fit"}))["action"]
    assert out["tool"] == "analyse" and out["action"] == "fit" and out["call"] == "analyse(action='fit', args={…})"
    assert out["takes"].startswith("distribution?=weibull, data?")
    props = out["arguments"]["properties"]
    assert "censored" in props and "0 = failed" in json.dumps(props["censored"])
    edit = _ok(_call(token, "guide", {"action": "change.rbd_edit"}))["action"]["arguments"]
    assert edit["required"] == ["rbd_id", "ops"] and edit["$defs"]  # the ops' nested types come along
    for ref in set(__import__("re").findall(r'"#/\$defs/([^"]+)"', json.dumps(edit))):
        assert ref in edit["$defs"], ref
    both = _ok(_call(token, "guide", {"action": "analyse.rbd", "topic": "rbd_analysis"}))
    assert both["topic"] == "rbd_analysis" and both["action"]["action"] == "rbd" and "topics" not in both
    assert "e.g. 'analyse.fit'" in _err(_call(token, "guide", {"action": "nope.fit"}))


def test_a_call_is_held_to_its_actions_arguments(env):
    token = env.oauth[PRO]
    msg = _err(_call(token, "analyse", {"action": "reliability_at", "times": [1]}))
    assert "action 'reliability_at' needs model_id (it takes model_id, times, conditional_age?" in msg
    msg = _err(_call(token, "analyse", {"action": "fit_per_demand", "data": [1, 2],
                                        "batches": [{"demands": 5, "failures": 0}]}))
    assert "action 'fit_per_demand' doesn't take data" in msg
    msg = _err(_call(token, "get", {"kind": "account", "id": "x"}))
    assert "kind 'account' doesn't take id (it takes nothing else)" in msg
    assert "kind 'model' needs id" in _err(_call(token, "get", {"kind": "model"}))
    # The action's own limits still hold, said plainly.
    msg = _err(_call(token, "analyse", {"action": "check_life_requirement", "model_id": "m",
                                        "b_life": 10, "life": 5, "confidence": 2}))
    assert "action 'check_life_requirement': confidence: Input should be less than 1" in msg
    # An argument only one action takes keeps its limits in the schema itself.
    msg = _err(_call(token, "analyse", {"action": "rbd_fault_tree", "rbd_id": "r", "max_cut_sets": 0}))
    assert "max_cut_sets" in msg and "greater than or equal to 1" in msg
    # A value no action has is refused by the schema.
    assert _call(token, "analyse", {"action": "nope"}).is_error
    # Renamed for get / list: the tool's argument names in the message, not the function's.
    msg = _err(_call(token, "get", {"kind": "upload", "id": "x" * 65}))
    assert "kind 'upload': id: String should have at most 64 characters" in msg


def test_null_means_left_out_and_defaults_are_each_actions(env):
    """Every argument defaults to null; a null one is as if not given, so the
    action's own default applies (confidence 0.95 for alt_use_level, 0.9 for
    check_life_requirement)."""
    from backend import mcp_server

    from backend.mcp_server import action_schema

    assert action_schema("analyse.check_life_requirement")["takes"] == "model_id, b_life, life, confidence?=0.9"
    assert action_schema("analyse.alt_use_level")["takes"].startswith(
        "model_id, use_stress, ref_stress?, mission_time?, confidence?=0.95")
    out = _ok(_call(env.oauth[PRO], "analyse", {"action": "fit", "data": [120, 340, 510, 700, 980],
                                                 "censored": None, "dataset_id": None}))
    assert out["distribution"] == "Weibull"  # distribution?=weibull


def test_plan_gating_goes_by_action(env):
    """Free has analyse's evaluations but not its fit, list's models but
    not its fleets; refusals aren't counted, and get kind account and the guide
    never are."""
    token = env.oauth[FREE]
    _ok(_call(token, "change", {"action": "model_save", "name": "B", "distribution": "weibull", "params": WEIBULL}))
    mid = _ok(_call(token, "list", {"kind": "models"}))["life_models"][0]["id"]
    assert _ok(_call(token, "analyse", {"action": "reliability_at", "model_id": mid, "times": [100]}))
    assert _calls_used(env.db, FREE) == 3
    assert "part of Reliafy Pro" in _err(_call(token, "analyse", {"action": "fit", "data": [1, 2, 3]}))
    assert "Fleet forecasts" in _err(_call(token, "list", {"kind": "fleets"}))
    assert "part of Reliafy Pro" in _err(_call(token, "change", {"action": "model_fit_recurrent", "name": "r",
                                                          "times": [1, 2]}))
    assert _calls_used(env.db, FREE) == 3  # refused: not counted
    _ok(_call(token, "get", {"kind": "account"}))
    _ok(_call(token, "guide", {"topic": "life_data"}))
    assert _calls_used(env.db, FREE) == 3
    from backend import mcp_server

    assert "change model_save" in mcp_server._pro_only_message("analyse.fit")
    assert "AcceleratedLife" in mcp_server._pro_only_message("change.model_fit_alt")
    assert "WeibullJointPH" in mcp_server._pro_only_message("analyse.fit_joint")


def test_a_soft_refusal_is_refunded_by_action(env):
    """analyse rbd_cheapest_design answers available=false without Pro: the call
    isn't counted, while rbd_fault_tree in the same tool is."""
    from backend.tests.test_mcp import REPAIRABLE_STAGES

    token = env.oauth[FREE]
    rid = _ok(_call(token, "change", {"action": "rbd_create", "name": "P", "repairable": True,
                                      "stages": REPAIRABLE_STAGES}))["id"]
    assert _calls_used(env.db, FREE) == 1
    out = _ok(_call(token, "analyse", {"action": "rbd_cheapest_design", "rbd_id": rid}))
    assert out["available"] is False and out["code"] == "pro_required"
    assert _calls_used(env.db, FREE) == 1
    assert _ok(_call(token, "analyse", {"action": "rbd_fault_tree", "rbd_id": rid}))["kind"]
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
    _ok(_call(token, "analyse", {"action": "fit", "data": [120, 340, 510, 700, 980]}))
    _ok(_call(token, "analyse", {"action": "plan_demonstration_test", "reliability": 0.9}))
    _ok(_call(token, "get", {"kind": "account"}))
    assert seen == [True, False, False]
    assert "analyse.fit" in mcp_server.HEAVY_TOOLS and "get.upload" in mcp_server.HEAVY_TOOLS
    assert "analyse.plan_demonstration_test" not in mcp_server.HEAVY_TOOLS


def test_usage_is_logged_by_action(env, monkeypatch):
    from backend import config

    monkeypatch.setattr(config, "USAGE_LOGGING", True)
    token = env.oauth[FREE]
    _ok(_call(token, "list", {"kind": "rbds"}))
    _err(_call(token, "analyse", {"action": "fit", "data": [1, 2, 3]}))
    _err(_call(token, "analyse", {"action": "reliability_at", "times": [1]}))  # needs model_id
    _ok(_call(token, "guide"))
    got = {(e["feature"], e["outcome"]) for e in env.db.usage_events.find({"channel": "mcp"})
           if e["feature"] not in ("initialize", "tools/list")}
    assert got == {("list.rbds", "ok"), ("analyse.fit", "pro_only"),
                   ("analyse.reliability_at", "error"), ("guide", "ok")}


def test_a_read_only_token_reads_and_calculates_but_never_writes(env):
    from backend.services import tokens

    read = tokens.create_token(env.db, PRO, "read", ["read"])["token"]
    assert set(_tools(read)) == READS | WRITES | REPORTS  # listed, as before
    _ok(_call(read, "list", {"kind": "models"}))
    _ok(_call(read, "get", {"kind": "account"}))
    _ok(_call(read, "guide"))
    _ok(_call(read, "analyse", {"action": "fit", "data": [120, 340, 510, 700, 980]}))
    for args in [{"action": "model_save", "name": "B", "distribution": "weibull", "params": WEIBULL},
                 {"action": "dataset_delete", "dataset_id": "x"},
                 {"action": "upload_create", "purpose": "dataset", "filename": "a.csv"},
                 {"action": "share_revoke", "token": "x"}]:
        assert "write" in _err(_call(read, "change", args)), args
    assert env.db.models.count_documents({}) == 0


def test_the_data_notice_goes_by_action(env):
    from backend.mcp_server import DATA_NOTICE

    token = env.oauth[PRO]
    saved = _ok(_call(token, "change", {"action": "model_save", "name": "B", "distribution": "weibull",
                                        "params": WEIBULL}))
    assert "data_notice" not in saved
    assert _ok(_call(token, "list", {"kind": "models"}))["data_notice"] == DATA_NOTICE
    assert _ok(_call(token, "get", {"kind": "model", "id": saved["model_id"]}))["data_notice"] == DATA_NOTICE
    assert "data_notice" not in _ok(_call(token, "get", {"kind": "account"}))
    assert "data_notice" not in _ok(_call(token, "analyse", {
        "action": "reliability_at", "model_id": saved["model_id"], "times": [100]}))


def test_the_guide_by_topic(env):
    from backend import mcp_guide

    token = env.oauth[FREE]
    index = _ok(_call(token, "guide"))
    assert set(index["topics"]) == set(mcp_guide.TOPICS) >= {
        "life_data", "units", "accelerated", "repairable", "rbds", "rbd_analysis", "strategy", "fleets",
        "uploads", "sharing", "workspace", "plans"}
    for topic in index["topics"]:
        page = _ok(_call(token, "guide", {"topic": topic}))
        assert page["topic"] == topic and len(page["guide"]) > 300
    assert _call(token, "guide", {"topic": "nope"}).is_error
    uploads = mcp_guide.TOPICS["uploads"][1]
    assert "change upload_send_part" in uploads and "url_fallback" in uploads and "200 KB" in uploads
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
        every = anyio.run(mcp_server.mcp.list_tools)
        names = {t.name for t in every}
        # One maintenance tool, its actions every earlier maintenance_* tool's (keys unchanged).
        assert names == READS | WRITES | REPORTS | {"maintenance"}
        assert "maintenance_reliability.fit_class_model" in mcp_server.PRO_ONLY_TOOLS & mcp_server._FIT_TOOLS
        assert {"maintenance_workspace.import_history", "maintenance_apply"} <= mcp_server.HEAVY_TOOLS
        assert {"maintenance_graph_query", "maintenance_graph_schema"} <= mcp_server.HEAVY_TOOLS
        _, table = mcp_tools.TOOL_TABLES["maintenance"]
        expected = {f"{area[len('maintenance_'):]}.{verb}" for area, (_, t) in mcp_tools.TABLES.items() for verb in t}
        expected |= {"overview", "guide", "view_photo", "graph_schema", "graph_query", "apply"}
        assert set(table) == expected and len(table) == 247  # 189 + work packages (Nov 2026): 9 actions, 2 reads, work_orders.mark, out of service ×4; + signals ×9, signal_data ×3; progression ×2; + failure reports (Nov 2026): 7 actions, 2 reads; + FME(C)A: failure_modes.score (positions.add_sample_uav since removed: the sample quadcopter is products.add_sample); + products (Nov 2026): 4 actions, 2 gets, 3 lists; products.add_sample; - positions.add_sample_truck (Nov 2026: the sample product is the one sample); + failure_modes.undo_delete (Nov 2026); + positions.log_event (Nov 2026); + measurements.move_point (Nov 2026); + tasks.set_resources (Nov 2026: the LSA); + rcm.pf_interval, rcm.ff_interval (Nov 2026; first named interval_on_condition, interval_failure_finding); + models.link, models.unlink (Nov 2026: life models on positions)
        # The whole list an operator loads on every connection, guarded (301,819 characters as 40 tools).
        listed = json.dumps([t.model_dump(mode="json", by_alias=True, exclude_none=True) for t in every])
        assert len(listed) < 22_000  # was 20,000 before the signal channel actions, 21,000 before failure reports
    finally:
        mcp_tools.unregister()
    assert len({t.name for t in anyio.run(mcp_server.mcp.list_tools)}) == 6
