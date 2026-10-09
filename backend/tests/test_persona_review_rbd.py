"""Regression tests for the persona review of 5 Oct (#265): safety and RBD
agent UX — a safety function without proof tests, the headline availability
with common cause, stage components' maintenance and costs, the refusals'
edit_rbd ops, structure_summary, times vs curve, summary_only, the proof-test
saw-tooth note and one spelling per unit.

Through the real MCP mount (helpers and the ``env`` fixture from test_mcp)
or, for the shared pieces, the services the app uses too.
"""

import json

import pytest

from backend.services import availability_answer, rbd_jobs, rbd_policies
from backend.services import rbds as rbds_service
from backend.units import canonical_unit
from backend.tests.test_availability_answers import _saved, _sif
from backend.tests.test_mcp import GRAPH, REPAIRABLE_STAGES, A, _call, _err, _ok, _run, env  # noqa: F401
from backend.tests.test_mcp_check_oct5 import pro  # noqa: F401 - a fixture
from backend.tests.test_rbd_costs import _exp, _io, _node


def _untested_sif(**extra):
    """_sif() with its proof tests taken off: every failure revealed at once."""
    graph = _sif(**extra)
    for n in graph["nodes"]:
        (n.get("data") or {}).pop("inspection", None)
    return graph


def _analyze(env, rid, **kw):
    return _ok(_call(env.token[A], "analyze_rbd", {"rbd_id": rid, **kw}))


def _stage(label, *names, k=None, **extra):
    comps = [{"label": n, "distribution": "exponential", "params": [{"name": "failure_rate", "value": 1e-4}],
              "repair_distribution": "exponential", "repair_params": [{"name": "failure_rate", "value": 0.2}],
              **extra.get(n, {})} for n in names]
    return {"label": label, "components": comps, **({"k_of_n": k} if k else {})}


# ---- 1. a safety function with no proof-tested block -----------------------------------------

def test_safety_function_without_proof_tests_warns_everywhere(env):
    out = _analyze(env, _saved(env, _untested_sif()), simulate=False)
    safety = out["safety"]
    # The safety summary...
    assert safety["proof_tests"] == "none" and safety["proof_tested_blocks"] == 0
    assert safety["warning"] == availability_answer.NO_PROOF_TESTS_AGENT
    assert safety["sil"] is not None and safety["sil_optimistic"] is True
    assert "optimistic" in safety["sil_note"]
    # ...and the answer's warnings, worded with the edit_rbd op for an agent.
    assert availability_answer.NO_PROOF_TESTS_AGENT in out["warnings"]
    assert "edit_rbd update_node inspection" in availability_answer.NO_PROOF_TESTS_AGENT
    assert "revealed and repaired at once" in availability_answer.NO_PROOF_TESTS_AGENT


def test_safety_function_with_proof_tests_has_no_such_warning(env):
    out = _analyze(env, _saved(env, _sif()), simulate=False)
    assert "proof_tests" not in out["safety"] and "sil_optimistic" not in out["safety"]
    assert not any("No proof tests" in w for w in out.get("warnings") or [])


def test_app_payload_carries_the_warning_and_flags_the_sil():
    """The payload the app reads (rbd_jobs.availability_out): result.warnings
    and the safety summary, also on a result saved before #265."""
    graph = _untested_sif()
    saved = {"steady_state_availability": 0.99999, "safety": {"pfd_avg": 1e-5, "sil": 4, "proof_tested_blocks": 0,
                                                              "common_cause": {"groups": 1, "included": True}}}
    out = rbd_jobs.availability_out(saved, {}, status={"state": "done"}, state=None, entitled=True, graph=graph)
    assert out["warnings"][0] == rbd_policies.NO_PROOF_TESTS
    assert out["safety"]["warning"] == rbd_policies.NO_PROOF_TESTS
    assert out["safety"]["sil_optimistic"] is True
    # Common cause leads the safety summary.
    assert next(iter(out["safety"])) == "common_cause_included" and out["safety"]["common_cause_included"] is True
    # Idempotent: said once however often it's finished.
    again = rbd_policies.safety_notes(graph, out)
    assert again["warnings"].count(rbd_policies.NO_PROOF_TESTS) == 1


def test_no_band_no_optimistic_flag():
    out = rbd_policies.safety_notes(_untested_sif(), {"safety": {"pfd_avg": 0.2, "sil": None}})
    assert out["safety"]["proof_tests"] == "none" and "sil_optimistic" not in out["safety"]


def test_create_rbd_validation_warns_a_safety_function_without_proof_tests(env):
    out = _ok(_call(env.token[A], "create_rbd", {"name": "SIF", "repairable": True, "safety_function": True,
                                                 "stages": [_stage("Valves", "Valve A", "Valve B")]}))
    # The app's Validate says it (in its words); an agent gets the edit_rbd op.
    graph = env.db.rbds.find_one({"_id": out["id"]})["graph"]
    assert rbd_policies.NO_PROOF_TESTS in rbd_policies.validation_warnings(graph)
    agent = availability_answer.NO_PROOF_TESTS_AGENT
    assert agent in out["warnings"]
    tested = _ok(_call(env.token[A], "create_rbd", {
        "name": "SIF", "repairable": True, "safety_function": True,
        "stages": [_stage("Valves", "Valve A", "Valve B", **{n: {"inspection": {"interval": 8760}}
                                                              for n in ("Valve A", "Valve B")})]}))
    assert agent not in tested["warnings"]
    # Not a safety function: nothing to say.
    plain = _ok(_call(env.token[A], "create_rbd", {"name": "x", "repairable": True,
                                                   "stages": REPAIRABLE_STAGES}))
    assert agent not in plain["warnings"]
    # Adding the proof tests by edit takes it away; it isn't repeated on other edits.
    ops = [{"op": "update_node", "ids": ["s0c0", "s0c1"], "inspection": {"interval": 8760}}]
    edited = _ok(_call(env.token[A], "edit_rbd", {"rbd_id": out["id"], "ops": ops}))
    assert agent not in edited["warnings"]


# ---- 2. a safety function leads with the availability with common cause ----------------------

def test_safety_answer_leads_with_the_headline_and_safety(env):
    out = _analyze(env, _saved(env, _sif()), simulate=False)
    keys = list(out)
    assert keys.index("availability") < keys.index("steady_state_availability")
    assert keys.index("safety") < keys.index("steady_state_availability")
    head = out["availability"]
    assert head["common_cause_included"] is True
    assert head["value"] == pytest.approx(1 - out["safety"]["pfd_avg"])
    # Every figure has the groups since #226: the headline is the long run with them.
    assert head["value"] == out["steady_state_availability"]
    assert head["without_common_cause"]["what"] == (
        "the long-run (steady-state) availability without the common-cause groups")


def test_non_safety_diagram_headline_is_unchanged(env):
    graph = _sif()
    graph.pop("safety_function")
    graph.pop("target_sil")
    out = _analyze(env, _saved(env, graph), simulate=False)
    head = out["availability"]
    assert head["value"] == out["steady_state_availability"]
    # Followed over time (#226), the groups are in a non-safety diagram's figures too.
    assert head["common_cause_included"] is True and head["without_common_cause"]["value"] > head["value"]
    assert "safety" not in out


# ---- 5. stage components take maintenance and costs; refusals give edit_rbd ops ---------------

def test_stage_components_take_inspection_preventive_and_costs(env):
    stages = [_stage("Logic", "PLC", **{"PLC": {"costs": {"repair": 100, "acquisition": 5000}}}),
              _stage("Valves", "Valve A", "Valve B",
                     **{"Valve A": {"inspection": {"interval": 4380, "cost": 200, "offset": 2190}},
                        "Valve B": {"preventive": {"policy": "age", "interval": 20000, "cost": 900}}})]
    out = _ok(_call(env.token[A], "create_rbd", {"name": "S", "repairable": True, "stages": stages}))
    data = {n["id"]: n["data"] for n in env.db.rbds.find_one({"_id": out["id"]})["graph"]["nodes"]}
    assert data["s0c0"]["costs"] == {"repair": 100, "acquisition": 5000}
    assert data["s1c0"]["inspection"] == {"interval": 4380, "cost": 200, "offset": 2190}
    assert data["s1c1"]["preventive"] == {"policy": "age", "interval": 20000, "cost": 900}
    # The same shapes as edit_rbd update_node takes (the schema is shared).
    tools = {t.name: t for t in _run(env.token[A], lambda c: c.list_tools()).tools}
    comp = tools["create_rbd"].input_schema["$defs"]["StageComponent"]["properties"]
    assert {"inspection", "preventive", "costs"} <= set(comp)


def test_stage_maintenance_is_refused_where_it_cant_apply(env):
    stages = [_stage("Valves", "Valve A", **{"Valve A": {"inspection": {"interval": 100}}})]
    msg = _err(_call(env.token[A], "create_rbd", {"name": "S", "stages": stages}))
    assert "repairable" in msg and "inspection" in msg
    both = [_stage("Valves", "Valve A", **{"Valve A": {"inspection": {"interval": 100},
                                                       "preventive": {"interval": 50}}})]
    msg = _err(_call(env.token[A], "create_rbd", {"name": "S", "repairable": True, "stages": both}))
    assert "not both" in msg


def _proof_tested(env, **diagram):
    stages = [_stage("Valves", "Valve A", "Valve B", **{n: {"inspection": {"interval": 4380}}
                                                        for n in ("Valve A", "Valve B")})]
    return _ok(_call(env.token[A], "create_rbd", {"name": "S", "repairable": True, "stages": stages,
                                                  **diagram}))["id"]


def test_optimise_intervals_refusal_gives_the_edit_rbd_ops(env):
    rid = _proof_tested(env)
    msg = _err(_call(env.token[A], "optimise_maintenance_intervals", {"rbd_id": rid}))
    assert "Nothing is priced" in msg
    assert "double-click" not in msg and "Cost & maintenance" not in msg
    ops = json.loads(msg[msg.index("["):msg.index("]", msg.rindex("downtime_rate")) + 1])
    by_id = {op.get("id"): op for op in ops}
    # Each update_node keeps the block's own schedule (update_node replaces it whole).
    assert by_id["s0c0"]["inspection"] == {"interval": 4380, "cost": "<cost per test>"}
    assert {"op": "set", "costs": {"downtime_rate": "<cost per unit time the whole system is down>"}} in ops
    # Sent as given (numbers filled in), they make it answer.
    filled = [{**op, "inspection": {**op["inspection"], "cost": 300}} for op in ops if op["op"] == "update_node"]
    _ok(_call(env.token[A], "edit_rbd", {"rbd_id": rid, "ops": filled}))
    out = _ok(_call(env.token[A], "optimise_maintenance_intervals", {"rbd_id": rid}))
    assert out["available"] is True


def test_optimise_intervals_without_schedules_says_how_to_add_them(env):
    rid = _ok(_call(env.token[A], "create_rbd", {"name": "x", "repairable": True,
                                                 "stages": REPAIRABLE_STAGES}))["id"]
    msg = _err(_call(env.token[A], "optimise_maintenance_intervals", {"rbd_id": rid}))
    assert "No block has scheduled replacement" in msg and "double-click" not in msg
    assert '"inspection": {"interval": "<time between tests>"' in msg and '"preventive": {"policy": "age"' in msg
    assert "Component block ids: s0c0, s1c0, s1c1" in msg


def test_cheapest_design_refusal_no_longer_points_at_the_app(pro):
    rid = _proof_tested(pro, costs={"horizon": 87600})
    msg = _err(_call(pro.token[A], "cheapest_design", {"rbd_id": rid}))
    assert "purchase price" in msg and "costs: {acquisition:" in msg
    assert "Cost & maintenance" not in msg and "Component block ids: s0c0, s0c1" in msg


# ---- 6. structure_summary on create_rbd and edit_rbd -----------------------------------------

def test_create_rbd_returns_the_structure_in_one_line(env):
    out = _ok(_call(env.token[A], "create_rbd", {"name": "x", "nodes": GRAPH["nodes"], "edges": GRAPH["edges"]}))
    assert out["structure_summary"] == "Controller → (Pump A ∥ Pump B)"
    stages = [_stage("Logic", "PLC"), _stage("Pumps", "P1", "P2", "P3", k=2)]
    voted = _ok(_call(env.token[A], "create_rbd", {"name": "v", "repairable": True, "stages": stages}))
    assert voted["structure_summary"] == "PLC → 2-of-3(P1, P2, P3)"


def test_edit_rbd_returns_the_new_structure(env):
    rid = _ok(_call(env.token[A], "create_rbd", {"name": "x", "nodes": GRAPH["nodes"],
                                                 "edges": GRAPH["edges"]}))["id"]
    node = {"id": "v", "type": "component", "label": "Valve", "model": GRAPH["nodes"][1]["model"]}
    out = _ok(_call(env.token[A], "edit_rbd", {"rbd_id": rid, "ops": [
        {"op": "add_node", "node": node, "after": "ctl"}]}))
    assert out["structure_summary"] == "Controller → Valve → (Pump A ∥ Pump B)"


def test_a_bridge_says_it_isnt_series_parallel(env):
    m = GRAPH["nodes"][1]["model"]
    nodes = [{"id": "input", "type": "input"}, {"id": "output", "type": "output"},
             *({"id": i, "type": "component", "label": i, "model": m} for i in ("a", "b", "c", "d", "e"))]
    edges = [("input", "a"), ("input", "b"), ("a", "c"), ("b", "d"), ("a", "e"), ("e", "d"), ("c", "output"),
             ("d", "output")]
    out = _ok(_call(env.token[A], "create_rbd", {"name": "bridge", "nodes": nodes,
                                                 "edges": [{"source": s, "target": t} for s, t in edges]}))
    assert out["structure_summary"].startswith("Not series-parallel (e.g. a bridge): 5 blocks, 8 connections")


# ---- 9. times vs curve -----------------------------------------------------------------------

def test_analyze_rbd_documents_times_against_the_curve(env):
    tools = {t.name: t for t in _run(env.token[A], lambda c: c.list_tools()).tools}
    times = " ".join(tools["analyze_rbd"].input_schema["properties"]["times"]["description"].split())
    assert "reliability_at" in times and "don't change `curve`" in times and "t_max" in times
    rid = _ok(_call(env.token[A], "create_rbd", {"name": "x", "nodes": GRAPH["nodes"],
                                                 "edges": GRAPH["edges"]}))["id"]
    out = _analyze(env, rid, times=[123.0])
    assert [p["t"] for p in out["reliability_at"]] == [123.0]
    assert 123.0 not in [p["t"] for p in out["curve"]]


# ---- 10. summary_only ------------------------------------------------------------------------

def test_summary_only_non_repairable(env):
    rid = _ok(_call(env.token[A], "create_rbd", {"name": "x", "nodes": GRAPH["nodes"],
                                                 "edges": GRAPH["edges"]}))["id"]
    full = _analyze(env, rid, times=[100.0])
    lean = _analyze(env, rid, times=[100.0], summary_only=True)
    assert lean["mttf"] == full["mttf"] and lean["b_life"] == full["b_life"]
    assert lean["reliability_at"] == full["reliability_at"]
    assert not {"curve", "importance", "structure"} & set(lean)
    top = lean["top_importance"]
    assert top["measure"] == "fussell_vesely" and top["blocks"][0]["label"] == "Controller"
    assert "summary_only" in lean and len(json.dumps(lean)) < len(json.dumps(full))


def test_summary_only_repairable_safety_function(env):
    rid = _saved(env, _untested_sif())
    full = _analyze(env, rid, simulate=False)
    lean = _analyze(env, rid, simulate=False, summary_only=True)
    for key in ("availability", "mean_up_time", "mean_down_time", "unavailability"):
        assert lean[key] == full[key]
    assert lean["safety"]["pfd_avg"] == full["safety"]["pfd_avg"] and lean["safety"]["sil_optimistic"] is True
    assert availability_answer.NO_PROOF_TESTS_AGENT in lean["warnings"]
    assert "curve" not in lean["exact"] and "routes" not in lean["exact"]
    assert "importance" not in lean and lean["top_importance"]["blocks"]
    assert len(json.dumps(lean)) < len(json.dumps(full)) / 2


# ---- 13. A(t) oscillates with the proof tests ------------------------------------------------

def test_proof_test_note_names_the_tested_blocks(env):
    out = _analyze(env, _saved(env, _sif()), simulate=False)
    note = out["proof_test_note"]
    assert note.startswith("A(t) oscillates with the proof-test cycle on “Pt1”, “Pt2”, “Ls”, “Valve”")
    untested = _analyze(env, _saved(env, _untested_sif()), simulate=False)
    assert "proof_test_note" not in untested


def test_proof_test_note_without_a_safety_function():
    graph = {"repairable": True, "nodes": [*_io(), _node("pump", model=_exp(1e-4),
                                                         inspection={"interval": 720})]}
    out = rbd_policies.safety_notes(graph, {"steady_state_availability": 0.99})
    assert "“Pump”" in out["proof_test_note"] and "safety" not in out


# ---- 8. one spelling per unit ----------------------------------------------------------------

@pytest.mark.parametrize("typed, stored", [
    ("hours", "Hours"), ("HRS", "Hours"), ("h", "Hours"), (" Hours ", "Hours"), ("days", "Days"),
    ("yr", "Years"), ("cycles", "Cycles"), ("km", "Kilometres"), ("Miles", "Miles"), ("minutes", "Minutes"),
    ("furlongs", "furlongs"), ("", ""), ("units", "units"),
])
def test_canonical_unit(typed, stored):
    assert canonical_unit(typed) == stored


def test_units_are_stored_in_one_spelling(env):
    out = _ok(_call(env.token[A], "create_rbd", {"name": "x", "unit": "hrs", "nodes": GRAPH["nodes"],
                                                 "edges": GRAPH["edges"]}))
    assert out["unit"] == "Hours"
    assert env.db.rbds.find_one({"_id": out["id"]})["graph"]["unit"] == "Hours"
    _ok(_call(env.token[A], "edit_rbd", {"rbd_id": out["id"], "ops": [{"op": "set", "unit": "cycles"}]}))
    assert env.db.rbds.find_one({"_id": out["id"]})["graph"]["unit"] == "Cycles"
    _ok(_call(env.token[A], "edit_rbd", {"rbd_id": out["id"], "ops": [{"op": "set", "unit": "furlongs"}]}))
    assert env.db.rbds.find_one({"_id": out["id"]})["graph"]["unit"] == "furlongs"  # unknown: as typed


def test_a_diagram_stored_in_another_spelling_keeps_its_saved_results(pro):
    """A diagram saved as "hours" before #265 shows "Hours", keeps its stored
    spelling on a save, and its saved simulation still matches."""
    rid = _ok(_call(pro.token[A], "create_rbd", {"name": "x", "repairable": True,
                                                 "stages": REPAIRABLE_STAGES}))["id"]
    pro.db.rbds.update_one({"_id": rid}, {"$set": {"graph.unit": "hours"}})
    _analyze(pro, rid, simulate=True)
    # Re-key the saved simulation as a result saved before #265 was keyed.
    doc = pro.db.rbds.find_one({"_id": rid})
    legacy = rbds_service.availability_cache_key(doc["graph"], unit="hours")
    assert legacy != rbds_service.availability_cache_key(doc["graph"])
    pro.db.rbds.update_one({"_id": rid}, {"$set": {"availability_cache.key": legacy}})

    got = _ok(_call(pro.token[A], "get_rbd", {"rbd_id": rid}))
    assert got["unit"] == "Hours" and got["graph"]["unit"] == "Hours"
    again = _analyze(pro, rid)
    assert again["cached"] is True and again["has_simulation"] is True
    # A save (a rename-only edit) keeps "hours", so the key goes on matching.
    _ok(_call(pro.token[A], "edit_rbd", {"rbd_id": rid, "ops": [{"op": "set", "name": "renamed"}]}))
    assert pro.db.rbds.find_one({"_id": rid})["graph"]["unit"] == "hours"
    assert _analyze(pro, rid)["cached"] is True
    # And an edit the analysis sees still says the saved simulation is out of date.
    model = {"distribution_id": "weibull", "params": [{"name": "alpha", "value": 500}, {"name": "beta", "value": 1.2}]}
    edited = _ok(_call(pro.token[A], "edit_rbd", {"rbd_id": rid, "ops": [
        {"op": "update_node", "id": "s1c0", "model": model}]}))
    assert "simulation_note" in edited


def test_keys_of_diagrams_in_the_apps_spelling_are_unchanged():
    """The canonical key is the old key wherever the unit was already spelt
    the app's way (or blank, or unknown): no saved result is put out of date."""
    import hashlib

    for unit in ("Hours", "", "furlongs"):
        graph = {"unit": unit, "nodes": [*_io(), _node("p", model=_exp(1e-3))],
                 "edges": [{"source": "input", "target": "p"}, {"source": "p", "target": "output"}]}
        old = {"v": rbds_service.AVAILABILITY_CACHE_VERSION,
               "graph": {**rbds_service.canonical_analysis_graph(graph), "unit": unit.strip()},
               "t_simulation": None}
        blob = json.dumps(old, sort_keys=True, separators=(",", ":"), default=str)
        assert rbds_service.availability_cache_key(graph) == hashlib.sha256(blob.encode()).hexdigest()


def test_sample_pump_station_has_a_unit(env):
    from backend.services import samples

    spec = next(s for s in samples.SAMPLE_RBDS if s["id"] == "sample-rbd-pump-station")
    assert spec["graph"]["unit"] == "Hours"
    assert all(s["graph"].get("unit") for s in samples.SAMPLE_RBDS)
    # A sample seeded blank before gets it on the next boot.
    env.db.rbds.update_one({"_id": spec["id"]}, {"$set": {"graph.unit": ""}})
    samples.seed_samples(env.db)
    assert env.db.rbds.find_one({"_id": spec["id"]})["graph"]["unit"] == "Hours"
