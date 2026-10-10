"""RBD exchange in RePyability's JSON format (#174).

* Export: the document loads with RePyability's own ``rbd_from_json`` and is
  the RBD the app analyses (same reliability / availability).
* Round trip: Reliafy -> JSON -> Reliafy gives back the same diagram.
* Library files (``rbd.to_json()`` written in code) import as the RBD they
  describe; what Reliafy can't hold is listed in the import notes.
* Untrusted uploads stay within the import limits.
"""

import copy
import json
import warnings

import numpy as np
import pytest

from backend.services import rbd_analysis as ra
from backend.services import rbd_graph, rbd_import, rbd_json, samples
from backend.services.rbd_import import RbdImportError
from backend.tests.test_mcp import env  # noqa: F401 - fixture
from backend.tests.test_rbd_import_api import USER, client  # noqa: F401 - fixture

TIMES = [50.0, 200.0, 500.0, 1000.0, 2500.0]



def _notes(d):
    """Import notes other than #187's "no time unit" note, which a file
    without a unit (RePyability's JSON has none) rightly carries."""
    return [w for w in d.warnings if w != rbd_import.UNIT_MISSING]

def _w(alpha, beta, **extra):
    return {"source": "params", "distribution": "Weibull", "distribution_id": "weibull",
            "params": [{"name": "alpha", "value": alpha}, {"name": "beta", "value": beta}], **extra}


def _exp(rate, **extra):
    return {"source": "params", "distribution": "Exponential", "distribution_id": "exponential",
            "params": [{"name": "failure_rate", "value": rate}], **extra}


def _ln(mu, sigma, **extra):
    return {"source": "params", "distribution": "Lognormal", "distribution_id": "lognormal",
            "params": [{"name": "mu", "value": mu}, {"name": "sigma", "value": sigma}], **extra}


def _node(nid, ntype, label, x=0, y=0, **data):
    return {"id": nid, "type": ntype, "position": {"x": x, "y": y}, "data": {"label": label, **data}}


def _edges(*pairs):
    return [{"id": f"e{i}", "source": a, "target": b} for i, (a, b) in enumerate(pairs)]


SUB = {
    "nodes": [_node("input", "input", "Input"), _node("x", "component", "Motor", 200, 0, model=_w(4000, 2.2)),
              _node("y", "component", "Gearbox", 400, 0, model=_exp(1e-4)),
              _node("output", "output", "Output", 600, 0)],
    "edges": _edges(("input", "x"), ("x", "y"), ("y", "output")),
    "unit": "Hours",
}


def _plant(sub_id="sub-1"):
    """Every non-repairable block type the builder draws."""
    nodes = [
        _node("input", "input", "Input"),
        _node("a", "component", "Pump A", 280, -150, model=_w(900, 1.4, extras={"gamma": 10.0})),
        _node("d", "component", "Pump D", 280, -50, model=_w(900, 1.4, extras={"gamma": 10.0}, placeholder=True)),
        _node("b", "parallel", "Fans", 280, 50, model=_exp(1e-3), n=3),
        _node("c", "series", "Seals", 280, 150, model=_ln(6.5, 0.5), n=2),
        _node("v", "knode", "2 of 4", 560, 0, n=2, k=4),
        _node("sc", "standby", "Cold dryer", 840, 0, model=_w(3000, 1.8), spares=2, dormancy=0, cold=True,
              startProb=0.95),
        _node("sw", "standby", "Warm pump", 1120, 0, model=_w(2500, 1.5), standbyModel=_w(2000, 1.5),
              spares=1, dormancy=0.3),
        _node("sh", "standby", "Hot fans", 1400, -80, model=_exp(5e-4), spares=1, dormancy=1),
        _node("sh2", "standby", "Hot mixed", 1400, 80, model=_exp(5e-4), standbyModel=_exp(8e-4),
              spares=2, dormancy=1),
        _node("r", "component", "↺ Pump A", 1120, 200, repeat_of="a"),
        _node("p", "component", "Bypass (failed)", 1680, 120, state="failed"),
        _node("sub", "subsystem", "Drive", 1680, -40, rbd={"id": sub_id, "name": "Drive train"}),
        _node("output", "output", "Output", 1960, 0),
    ]
    edges = _edges(
        ("input", "a"), ("input", "d"), ("input", "b"), ("input", "c"),
        ("a", "v"), ("d", "v"), ("b", "v"), ("c", "v"),
        ("v", "sc"), ("sc", "sw"), ("sw", "sh"), ("sw", "sh2"), ("input", "r"), ("r", "sh2"),
        ("sh", "sub"), ("sh2", "sub"), ("sh", "p"), ("p", "output"), ("sub", "output"),
    )
    return {"nodes": nodes, "edges": edges, "unit": "Hours",
            "ccf_groups": [{"id": "g1", "members": ["a", "d"], "beta": 0.05}]}


def _maintained():
    """A repairable diagram using costs, maintenance, tests, crews and groups."""
    rep = _ln(2.0, 0.6)
    nodes = [
        _node("input", "input", "Input"),
        _node("p1", "component", "Pump 1", 280, -80, model=_w(2000, 1.6), repair=rep, maintenance_group="north",
              costs={"repair": {"min": 150, "max": 250}, "replace": 1500, "downtime": 40, "acquisition": 20000},
              preventive={"policy": "age", "interval": 900, "duration": 6, "cost": 400, "opportunity": 600}),
        _node("p2", "component", "Pump 2", 280, 80, model=_w(2000, 1.6), repair=rep, maintenance_group="north",
              crew_priority=2),
        _node("v", "knode", "1 of 2", 560, 0, n=1, k=2),
        _node("dry", "standby", "Dryers", 840, 0, model=_w(5000, 2.0), repair=_exp(0.1), spares=1, dormancy=0,
              cold=True, startProb=0.97, repair_one_at_a_time=True),
        _node("sv", "component", "Safety valve", 1120, 0, model=_exp(2e-5), instant_repair=True,
              inspection={"interval": 4380, "duration": rep, "cost": 300, "offset": 1000, "coverage": 0.9,
                          "full_test": 43800}),
        _node("cm", "component", "Compressor", 1400, 0, model=_w(3000, 2.5), repair=_exp(0.05),
              preventive={"policy": "condition", "interval": 200, "threshold": 0.05, "inspection_cost": 10,
                          "duration": 0, "cost": 900}),
        _node("output", "output", "Output", 1680, 0),
    ]
    edges = _edges(("input", "p1"), ("input", "p2"), ("p1", "v"), ("p2", "v"), ("v", "dry"), ("dry", "sv"),
                   ("sv", "cm"), ("cm", "output"))
    return {"nodes": nodes, "edges": edges, "unit": "Hours", "repairable": True,
            "costs": {"downtime_rate": 500, "horizon": 87600}, "repair_crews": {"crews": 2},
            "maintenance_groups": {"north": {"setup_cost": 2000, "system_down": False}},
            "safety_function": True, "target_sil": 2,
            "ccf_groups": [{"id": "g1", "members": ["p1", "p2"], "beta": 0.05}]}


SAVED = {"sub-1": SUB}


def _resolve_sub(sub_id):
    return copy.deepcopy(SAVED.get(sub_id))


def _export(graph, name="Plant"):
    return rbd_json.to_json(rbd_json.to_document(copy.deepcopy(graph), name, resolve_subsystem=_resolve_sub))


def _import(text, filename="plant.json"):
    return rbd_import.import_file(text.encode("utf-8"), filename)


def _reliability(graph, sub=_resolve_sub):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return ra.analyze(graph, resolve_subsystem=sub, at_times=TIMES)


def _r_at(result):
    return result["at"]["sf"]


class _Rbd:
    def __init__(self, rid, graph, name="Drive train"):
        self.id, self.graph, self.name = rid, graph, name


# ---------------------------------------------------------------------------
# Export: what RePyability loads is what the app analyses
# ---------------------------------------------------------------------------
def test_nonrepairable_export_loads_in_repyability_as_the_apps_rbd():
    from repyability.rbd.serialisation import rbd_from_json

    graph = _plant()
    text = _export(graph)
    doc = json.loads(text)
    assert doc["type"] == "NonRepairableRBD" and doc["repyability_version"]
    assert doc["reliafy"]["format"] == "reliafy-rbd" and doc["reliafy"]["graph"] == graph
    assert doc["reliafy"]["subsystems"]["sub-1"]["graph"] == SUB

    rbd = rbd_from_json(text)
    app = _reliability(graph)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        # The pinned block is an analysis override in both.
        mine = rbd.sf(np.array(TIMES), broken_nodes=["p"])
    np.testing.assert_allclose(mine, _r_at(app), rtol=2e-3)


def test_repairable_export_loads_in_repyability_with_its_maintenance():
    from repyability.rbd.serialisation import rbd_from_json

    graph = _maintained()
    text = _export(graph)
    rbd = rbd_from_json(text)
    assert type(rbd).__name__ == "RepairableRBD"
    doc = json.loads(text)
    by_node = {c["node"]: c["component"] for c in doc["components"]}
    assert by_node["p1"]["repair_cost"]["model"]["distribution"] == "Uniform"
    assert by_node["p1"]["preventive"]["opportunity"] == 600 and by_node["p1"]["group"] == "north"
    assert by_node["sv"]["repairability"] == "instant" and by_node["sv"]["inspection"]["coverage"] == 0.9
    assert by_node["dry"]["kind"] == "rbd"  # repaired one unit at a time: its own one-crew diagram
    assert doc["repair_crews"] == 2 and doc["downtime_cost_rate"] == 500
    assert doc["maintenance_groups"] == [{"group": "north", "setup_cost": 2000.0}]


def test_export_refuses_blocks_on_workspace_only_models():
    graph = {
        "nodes": [_node("input", "input", "Input"),
                  _node("ph", "component", "Bearing", model={"kind": "regression", "modelId": "m1", "name": "PH"}),
                  _node("km", "component", "Seal", model={"kind": "nonparametric", "modelId": "m2"}),
                  _node("ls", "loadshare", "Shared", model={"kind": "regression", "modelId": "m3"}, units=2, k=1,
                        load=10),
                  _node("output", "output", "Output")],
        "edges": _edges(("input", "ph"), ("ph", "km"), ("km", "ls"), ("ls", "output")),
    }
    with pytest.raises(rbd_json.ExportError) as exc:
        rbd_json.to_document(graph, "PH")
    msg = str(exc.value)
    assert "“Bearing” uses a fitted proportional-hazards model" in msg
    assert "“Seal” uses a non-parametric model" in msg and "“Shared” is a load-sharing group" in msg
    assert "Download as Python" in msg


def test_export_names_blocks_without_a_model_but_not_pinned_ones():
    graph = {"nodes": [_node("input", "input", "Input"), _node("a", "component", "Empty"),
                       _node("b", "component", "Pinned", state="working"), _node("output", "output", "Output")],
             "edges": _edges(("input", "a"), ("a", "b"), ("b", "output"))}
    with pytest.raises(rbd_json.ExportError, match="“Empty” has no life model"):
        rbd_json.to_document(graph, "x")
    graph["nodes"][1]["data"]["model"] = _w(100, 2)
    doc = rbd_json.to_document(graph, "x")
    assert {"node": "b", "model": {"kind": "perfect_reliability"}} in doc["reliabilities"]


# ---------------------------------------------------------------------------
# Round trip: Reliafy -> JSON -> Reliafy
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("make", [_plant, _maintained])
def test_round_trip_gives_back_the_same_diagram(make):
    graph = make()
    [d] = _import(_export(graph))
    assert d.source_format == "Reliafy (RePyability JSON)" and d.name == "Plant"
    rbd_import.link_references([d], None, lambda rid: _Rbd(rid, SAVED[rid]) if rid in SAVED else None)
    assert d.warnings == []
    assert rbd_graph.normalize_graph(d.graph) == rbd_graph.normalize_graph(graph)


def test_round_trip_keeps_saved_model_links_only_when_they_still_match():
    class Saved:
        id, name, kind = "m1", "Pump fit", "distribution"
        results = {"distribution": "Weibull", "distribution_id": "weibull",
                   "params": [{"name": "alpha", "value": 900}, {"name": "beta", "value": 1.4}]}

    graph = _plant()
    graph["nodes"][1]["data"]["model"] = {**rbd_graph.normalize_model({"saved_model_id": "m1"}, "a", lambda _: Saved),
                                          "params": Saved.results["params"]}
    text = _export(graph)
    subs = lambda rid: _Rbd(rid, SAVED[rid]) if rid in SAVED else None  # noqa: E731

    [d] = _import(text)
    rbd_import.link_references([d], lambda mid: Saved if mid == "m1" else None, subs)
    assert d.warnings == []
    assert d.graph["nodes"][1]["data"]["model"]["modelId"] == "m1"

    # Someone else (or after a refit): the block keeps the file's parameters, unlinked.
    [d] = _import(text)
    rbd_import.link_references([d], lambda mid: None, subs)
    model = d.graph["nodes"][1]["data"]["model"]
    assert "modelId" not in model and model["params"] == Saved.results["params"]
    assert "“Pump A” used saved models you can't open here" in d.warnings[0]
    rbd_graph.normalize_graph(d.graph)  # valid without any resolver


def test_a_subsystem_the_importer_cant_open_is_drawn_in_place():
    graph = _plant()
    [d] = _import(_export(graph))  # no links restored: someone else's import
    assert any("“Drive” linked the sub-system “Drive train”" in w for w in d.warnings)
    ids = {n["id"] for n in d.graph["nodes"]}
    assert {"sub/in", "sub/out", "sub/x", "sub/y"} <= ids and "sub" not in ids
    norm = rbd_graph.normalize_graph(d.graph)
    np.testing.assert_allclose(_r_at(_reliability(norm, None)), _r_at(_reliability(graph)), rtol=1e-9)

    # The same when the saved sub-system changed since the export.
    changed = copy.deepcopy(SUB)
    changed["nodes"][1]["data"]["model"] = _w(5000, 2.2)
    [d] = _import(_export(graph))
    rbd_import.link_references([d], None, lambda rid: _Rbd(rid, changed))
    assert "sub/x" in {n["id"] for n in d.graph["nodes"]}


@pytest.mark.parametrize("sample", [s["id"] for s in samples.SAMPLE_RBDS])
def test_samples_round_trip(sample):
    s = next(s for s in samples.SAMPLE_RBDS if s["id"] == sample)
    [d] = _import(_export(s["graph"], s["name"]))
    assert _notes(d) == [] and d.name == s["name"]
    assert rbd_graph.normalize_graph(d.graph) == rbd_graph.normalize_graph(copy.deepcopy(s["graph"]))


# ---------------------------------------------------------------------------
# Read from the RePyability part alone (library files, edited files)
# ---------------------------------------------------------------------------
def _core_only(text):
    doc = json.loads(text)
    doc.pop("reliafy")
    return json.dumps(doc)


def test_nonrepairable_core_alone_gives_the_same_reliability():
    graph = _plant()
    [d] = _import(_core_only(_export(graph)))
    assert d.source_format == "RePyability JSON"
    norm = rbd_graph.normalize_graph(d.graph)
    # The pin is an analysis override, not part of RePyability's diagram.
    for n in norm["nodes"]:
        if n["id"] == "p":
            assert n["type"] == "component"
            n["data"]["state"] = "failed"
    np.testing.assert_allclose(_r_at(_reliability(norm, None)), _r_at(_reliability(graph)), rtol=1e-6)
    types = {n["id"]: n["type"] for n in norm["nodes"]}
    assert types["b"] == "parallel" and types["c"] == "series" and types["sc"] == "standby"
    assert types["sh"] == "parallel"  # hot standby of identical units = active parallel
    assert norm["ccf_groups"][0]["members"] == ["a", "d"]
    extras = next(n for n in norm["nodes"] if n["id"] == "a")["data"]["model"]["extras"]
    assert extras == {"gamma": 10.0}
    assert next(n for n in norm["nodes"] if n["id"] == "r")["data"]["repeat_of"] == "a"


def test_repairable_core_alone_gives_the_same_availability():
    graph = _maintained()
    [d] = _import(_core_only(_export(graph)))
    norm = rbd_graph.normalize_graph(d.graph)
    data = {n["id"]: n["data"] for n in norm["nodes"]}
    assert norm["repair_crews"] == {"crews": 2} and norm["costs"] == {"downtime_rate": 500.0}
    assert norm["maintenance_groups"] == {"north": {"setup_cost": 2000.0}}
    assert data["p1"]["costs"]["repair"] == {"min": 150, "max": 250}
    assert data["p1"]["preventive"]["opportunity"] == 600 and data["p1"]["maintenance_group"] == "north"
    assert data["dry"]["repair_one_at_a_time"] is True and data["dry"]["startProb"] == 0.97
    assert data["sv"]["instant_repair"] is True and data["sv"]["inspection"]["full_test"] == 43800
    assert data["p2"]["crew_priority"] == 2
    assert next(n for n in norm["nodes"] if n["id"] == "v")["type"] == "knode"

    # The app builds the very same RePyability diagram from it.
    from repyability.rbd.serialisation import rbd_to_dict

    def built(g):
        rbd, *_ = ra._build_repairable_rbd(g, with_ccf=True)
        return rbd_json.comparable(rbd_to_dict(rbd))

    assert built(norm) == built(graph)


def test_an_edited_core_is_rebuilt_from_repyability_and_keeps_labels():
    doc = json.loads(_export(_plant()))
    a = next(r for r in doc["reliabilities"] if r["node"] == "a")
    a["model"]["model"]["params"] = [1200.0, 1.4]
    [d] = _import(json.dumps(doc))
    assert "changed after Reliafy wrote it" in _notes(d)[0]
    node = next(n for n in d.graph["nodes"] if n["id"] == "a")
    assert node["data"]["label"] == "Pump A" and node["data"]["model"]["params"][0]["value"] == 1200.0
    assert d.graph["unit"] == "Hours" and d.name == "Plant"


def test_a_file_written_in_code_imports_as_the_rbd_it_describes():
    import surpyval as sp
    from repyability import BetaFactor
    from repyability.rbd.ccf import CCFGroup
    from repyability.rbd.helper_classes import PerfectReliability
    from repyability.rbd.non_repairable_rbd import NonRepairableRBD
    from repyability.rbd.repeated_node import RepeatedNode
    from repyability.rbd.repeated_standby_node import RepeatedStandbyNode
    from repyability.rbd.standby_node import StandbyModel

    w = sp.Weibull.from_params([1000, 2.0])
    nested = NonRepairableRBD([("s", "m"), ("m", "e")], {"m": sp.Exponential.from_params([2e-4])},
                              input_node="s", output_node="e")
    rbd = NonRepairableRBD(
        [(0, 1), (0, 2), (0, 3), (1, "gate"), (2, "gate"), (3, "gate"), ("gate", ("x", 1)), (("x", 1), "pack"),
         ("pack", "spare"), ("spare", "sub"), (0, "copy"), ("copy", "sub"), ("sub", 9)],
        {1: w, 2: w, 3: sp.LogNormal.from_params([7, 0.4], gamma=5),
         "gate": PerfectReliability, ("x", 1): RepeatedNode(w, 3, "parallel"),
         "pack": StandbyModel([w, w, w], k=1, switching_probability=0.9),
         "spare": RepeatedStandbyNode(sp.Exponential.from_params([1e-3]), 2), "sub": nested, "copy": 1},
        k={"gate": 2},
        ccf_groups=[CCFGroup([1, 2], BetaFactor(0.1, basis="rate"))],
    )
    [d] = _import(rbd.to_json(), "plant.json")
    assert d.source_format == "RePyability JSON" and d.name == "plant"
    assert _notes(d) == []
    norm = rbd_graph.normalize_graph(d.graph)
    by_label = {n["data"]["label"]: n for n in norm["nodes"]}
    assert by_label["gate"]["type"] == "knode" and by_label["gate"]["data"]["n"] == 2
    assert by_label['["x", 1]']["type"] == "parallel" and by_label['["x", 1]']["data"]["n"] == 3
    assert by_label["pack"]["type"] == "standby" and by_label["pack"]["data"]["startProb"] == 0.9
    assert by_label["spare"]["type"] == "standby" and by_label["spare"]["data"]["spares"] == 1
    assert by_label["copy"]["data"]["repeat_of"] == by_label["1"]["id"]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        expected = rbd.sf(np.array(TIMES))
    np.testing.assert_allclose(_r_at(_reliability(norm, None)), expected, rtol=5e-3)


def _ccf_pair(model):
    import surpyval as sp
    from repyability.rbd.ccf import CCFGroup
    from repyability.rbd.non_repairable_rbd import NonRepairableRBD

    w = sp.Weibull.from_params([1000, 2.0])
    return NonRepairableRBD([("in", "a"), ("in", "b"), ("a", "out"), ("b", "out")], {"a": w, "b": w},
                            input_node="in", output_node="out", ccf_groups=[CCFGroup(["a", "b"], model)])


def test_ccf_groups_import_on_either_basis():
    """#210: a rate-basis group (Reliafy's lifetime default) imports as a
    plain group; a probability-basis one (RePyability's default) keeps its
    basis, with a note, and analyses as the library does."""
    from repyability import BetaFactor

    rate = _ccf_pair(BetaFactor(0.2, basis="rate"))
    [d] = _import(rate.to_json())
    assert _notes(d) == []
    [group] = d.graph["ccf_groups"]
    assert group["beta"] == 0.2 and "basis" not in group
    np.testing.assert_allclose(_r_at(_reliability(rbd_graph.normalize_graph(d.graph), None)),
                               rate.sf(np.array(TIMES)), rtol=1e-9)

    prob = _ccf_pair(BetaFactor(0.2))
    [d] = _import(prob.to_json())
    assert d.graph["ccf_groups"][0]["basis"] == "probability"
    assert any("failure probability" in n and "rate" in n for n in _notes(d))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        expected = prob.sf(np.array(TIMES))
    np.testing.assert_allclose(_r_at(_reliability(rbd_graph.normalize_graph(d.graph), None)), expected,
                               rtol=1e-9)


def test_export_writes_the_basis_the_app_analyses():
    """#210/#174: the exported group is the rate-basis one the app uses, so the
    library gets the app's numbers; an explicit probability basis is kept."""
    from repyability.rbd.serialisation import rbd_from_json

    graph = {
        "unit": "Hours",
        "nodes": [{"id": "input", "type": "input", "data": {"label": "Input"}},
                  {"id": "a", "type": "component", "data": {"label": "A", "model": _w(1000, 2.0)}},
                  {"id": "b", "type": "component", "data": {"label": "B", "model": _w(1000, 2.0)}},
                  {"id": "output", "type": "output", "data": {"label": "Output"}}],
        "edges": [{"source": "input", "target": "a"}, {"source": "input", "target": "b"},
                  {"source": "a", "target": "output"}, {"source": "b", "target": "output"}],
        "ccf_groups": [{"id": "g", "members": ["a", "b"], "beta": 0.1}],
    }
    doc = json.loads(_export(graph))
    assert doc["ccf_groups"][0]["model"] == {"kind": "beta_factor", "beta": 0.1, "basis": "rate"}
    rbd = rbd_from_json(_export(graph))
    np.testing.assert_allclose(rbd.sf(np.array(TIMES)), _r_at(_reliability(graph)), rtol=1e-9)
    graph["ccf_groups"][0]["basis"] = "probability"
    assert json.loads(_export(graph))["ccf_groups"][0]["model"] == {"kind": "beta_factor", "beta": 0.1}


def test_what_reliafy_cant_hold_is_listed_and_left_without_a_model():
    import surpyval as sp
    from repyability.rbd.ccf import MGL, CCFGroup
    from repyability.rbd.non_repairable_rbd import NonRepairableRBD
    from repyability.rbd.degrading_node import DegradingNode
    from repyability.rbd.standby_node import StandbyModel

    w = sp.Weibull.from_params([1000, 2.0])
    rbd = NonRepairableRBD(
        [("in", "a"), ("in", "b"), ("in", "c"), ("a", "out"), ("b", "out"), ("c", "deg"), ("deg", "two"),
         ("two", "out")],
        {"a": w, "b": w, "c": sp.Uniform.from_params([0, 100]),
         "deg": DegradingNode([(1.0, w), (0.5, w)]),
         "two": StandbyModel([w, w, w], k=2)},
        input_node="in", output_node="out", k={"out": 2},
        capacity={"a": 1.0, "b": 2.0, "c": 1.0, "deg": 1.0, "two": 1.0},
        ccf_groups=[CCFGroup(["a", "b"], MGL(0.1))],
    )
    [d] = _import(rbd.to_json())
    notes = " ".join(d.warnings)
    assert "capacities" not in notes and "MGL" not in notes
    # MGL on a pair is the beta factor (#84): it comes across as a group.
    assert [g["beta"] for g in d.graph["ccf_groups"]] == [0.1]
    # Capacities come onto the blocks drawn for them (#122).
    caps = {n["data"].get("label"): n["data"].get("capacity") for n in d.graph["nodes"]}
    assert caps["a"] == 1.0 and caps["b"] == 2.0
    # A Uniform is a Reliafy distribution since #72: it comes across as one.
    assert "“c” was imported without" not in notes
    c = next(n for n in d.graph["nodes"] if n["id"] == "c" or n["data"].get("label") == "c")
    assert c["data"]["model"]["distribution_id"] == "uniform"
    assert "“deg” was imported without a life model — its model is a degrading" in notes
    # Two of three running (#84): a standby block with k = 2 and one spare.
    two = next(n for n in d.graph["nodes"] if n["data"].get("label") == "two")
    assert two["type"] == "standby" and two["data"]["k"] == 2 and two["data"]["spares"] == 1
    # k on the output: a vote node in front of it.
    vote = next(n for n in d.graph["nodes"] if n["type"] == "knode")
    assert vote["data"]["n"] == 2 and {"source": vote["id"], "target": "output"} in d.graph["edges"]
    rbd_graph.normalize_graph(d.graph)


def test_repairable_library_file_imports_imperfect_repair():
    import surpyval as sp
    from repyability import RepairableRBD

    w, r = sp.Weibull.from_params([1000, 2.0]), sp.Exponential.from_params([0.1])
    rbd = RepairableRBD(
        [("in", "a"), ("a", "out")],
        {"a": {"reliability": w, "repairability": r, "repair": {"model": "kijima1", "q": 0.5}}},
        input_node="in", output_node="out")
    [d] = _import(rbd.to_json())
    assert d.graph["repairable"] is True
    # Kijima's virtual age (#68) comes across as the block's repair quality.
    a = next(n for n in d.graph["nodes"] if n["type"] == "component")
    assert a["data"]["repair_quality"] == {"model": "kijima1", "q": 0.5}
    assert not any("imperfect repair" in w for w in d.warnings)
    rbd_graph.normalize_graph(d.graph)


# ---------------------------------------------------------------------------
# Untrusted files
# ---------------------------------------------------------------------------
def test_sniffing_picks_repyability_json_and_leaves_storm_json_to_galileo():
    from backend.services.rbd_import import galileo, repyability

    text = _export(_plant()).encode()
    assert repyability.sniff(text, "x.txt") and not galileo.sniff(text, "x.json")
    storm = b'{"toplevel": "1", "nodes": [{"data": {"id": "1", "type": "be", "rate": 0.1, "name": "A"}}]}'
    assert not repyability.sniff(storm, "x.json")
    from backend.services import uploads

    assert uploads.detect_format(text[:4096]) == "repyability"


@pytest.mark.parametrize("payload,match", [
    (b'{"repyability_version": "0.11", "type": "Nope"}', "isn't a RePyability diagram"),
    (b'{"repyability_version": "0.11", "type": "NonRepairableRBD", ', "isn't valid JSON"),
    (b'{"repyability_version": "0.11", "type": "NonRepairableRBD", "edges": []}', "no edges"),
    (b'{"repyability_version": "0.11", "type": "NonRepairableRBD", "edges": [[{"a": 1}, "b"]]}', "Node names"),
    (b'{"repyability_version": "0.11", "type": "NonRepairableRBD", "edges": "x"}', "must be a list"),
    (b'{"repyability_version": "0.11", "type": "NonRepairableRBD", "edges": [["a", "b"], ["c", "d"]]}',
     "set input_node"),
])
def test_malformed_files_are_refused_in_plain_words(payload, match):
    with pytest.raises(RbdImportError, match=match):
        rbd_import.import_file(payload, "x.json")


def test_deep_nesting_and_size_are_bounded():
    deep = {"kind": "surpyval", "model": {"parameterization": "parametric", "distribution": "Weibull",
                                          "param_names": ["alpha", "beta"], "params": [10, 1]}}
    for _ in range(40):
        deep = {"kind": "rbd", "rbd": {"type": "NonRepairableRBD", "edges": [["i", "m"], ["m", "o"]],
                                       "input_node": "i", "output_node": "o",
                                       "reliabilities": [{"node": "m", "model": deep}]}}
    doc = {"repyability_version": "0.11", **deep["rbd"]}
    with pytest.raises(RbdImportError, match="more than 16 deep"):
        rbd_import.import_file(json.dumps(doc).encode(), "x.json")
    with pytest.raises(RbdImportError, match="nested too deeply"):
        rbd_import.import_file(b'{"repyability_version": 1, "type": "NonRepairableRBD", "x": ' + b"[" * 100_000
                               + b"]" * 100_000 + b"}", "x.json")

    from backend.services.rbd_graph import MAX_BLOCKS

    n = MAX_BLOCKS + 10
    big = {"repyability_version": "0.11", "type": "NonRepairableRBD", "input_node": "i", "output_node": "o",
           "edges": [["i", f"b{j}"] for j in range(n)] + [[f"b{j}", "o"] for j in range(n)],
           "reliabilities": [{"node": f"b{j}", "model": {"kind": "perfect_reliability"}} for j in range(n)]}
    with pytest.raises(RbdImportError, match="more than 5,000 blocks"):
        rbd_import.import_file(json.dumps(big).encode(), "x.json")


def test_a_tampered_reliafy_part_is_not_trusted():
    doc = json.loads(_export(_plant()))
    doc["reliafy"]["graph"]["nodes"][1]["data"]["model"] = _w(1, 1)  # disagrees with the RePyability part
    [d] = _import(json.dumps(doc))
    assert "changed after Reliafy wrote it" in _notes(d)[0]
    a = next(n for n in d.graph["nodes"] if n["id"] == "a")
    assert a["data"]["model"]["params"][0]["value"] == 900.0  # the RePyability part wins

    doc["reliafy"]["graph"] = {"nodes": "nope"}
    [d] = _import(json.dumps(doc))
    assert "changed after Reliafy wrote it" in _notes(d)[0]


# ---------------------------------------------------------------------------
# The app: GET /api/rbds/{id}/export.json and POST /api/rbds/import
# ---------------------------------------------------------------------------
def _save(db, name, graph, owner):
    from backend.services import rbds as rbds_service

    return rbds_service.save_rbd(db, name, graph, owner)


def test_download_and_import_in_the_app(client):
    sub = _save(client.db, "Drive train", copy.deepcopy(SUB), USER["uid"])
    plant = _save(client.db, "Plant", _plant(sub.id), USER["uid"])

    r = client.get(f"/api/rbds/{plant.id}/export.json")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/json")
    assert 'filename="plant.json"' in r.headers["content-disposition"]
    assert r.json()["type"] == "NonRepairableRBD"

    r = client.post("/api/rbds/import", files={"file": ("plant.json", r.content, "application/json")})
    assert r.status_code == 200, r.text
    [d] = r.json()["diagrams"]
    assert d["source_format"] == "Reliafy (RePyability JSON)" and d["warnings"] == []
    assert d["name"] == "Plant"
    # Same account: the sub-system link and the layout come back as they were.
    assert d["graph"] == rbd_graph.normalize_graph(_plant(sub.id))

    # A diagram someone else owns: not found, as for the Python download.
    other = _save(client.db, "Theirs", _plant(sub.id), "someone-else")
    assert client.get(f"/api/rbds/{other.id}/export.json").status_code == 404


def test_download_refuses_workspace_only_models_in_plain_words(client):
    graph = {"nodes": [_node("input", "input", "Input"),
                       _node("ph", "component", "Bearing", model={"kind": "regression", "modelId": "m1"}),
                       _node("output", "output", "Output")],
             "edges": _edges(("input", "ph"), ("ph", "output"))}
    rbd = _save(client.db, "PH", graph, USER["uid"])
    r = client.get(f"/api/rbds/{rbd.id}/export.json")
    assert r.status_code == 422
    assert "“Bearing” uses a fitted proportional-hazards model" in r.json()["detail"]


def test_import_of_someone_elses_export_draws_their_subsystem_in_place(client):
    their = _save(client.db, "Drive train", copy.deepcopy(SUB), "someone-else")
    doc = json.loads(rbd_json.to_json(rbd_json.to_document(
        _plant(their.id), "Plant", resolve_subsystem=lambda _: copy.deepcopy(SUB))))
    r = client.post("/api/rbds/import", files={"file": ("plant.json", json.dumps(doc).encode(), "application/json")})
    [d] = r.json()["diagrams"]
    assert "graph" in d, d
    assert any("drawn in place" in w for w in d["warnings"])
    assert "sub/x" in {n["id"] for n in d["graph"]["nodes"]}


# ---------------------------------------------------------------------------
# MCP: export_rbd_json, and import_rbd takes it back
# ---------------------------------------------------------------------------
def test_mcp_export_and_import(env):
    from backend.services import rbds as rbds_service
    from backend.tests.test_mcp import A, B, _call, _err, _ok

    sub = _save(env.db, "Drive train", copy.deepcopy(SUB), A)
    plant = _save(env.db, "Plant", _plant(sub.id), A)

    out = _ok(_call(env.token[A], "export_rbd_json", {"rbd_id": plant.id}))
    assert out["filename"] == "plant.json" and out["notes"] and "rbd_from_json" in out["load"]
    assert json.loads(out["json"])["reliafy"]["name"] == "Plant"

    back = _ok(_call(env.token[A], "import_rbd", {"content": out["json"], "name": "Plant copy"}))
    [item] = back["diagrams"]
    assert back["saved"] and item["import_notes"] == []
    saved = rbds_service.get_rbd(env.db, item["id"], [A])
    assert saved.name == "Plant copy" and saved.graph == rbd_graph.normalize_graph(_plant(sub.id))

    # B can't read A's diagram, nor A's sub-system: it is drawn in place.
    assert "not found" in _err(_call(env.token[B], "export_rbd_json", {"rbd_id": plant.id})).lower()
    back = _ok(_call(env.token[B], "import_rbd", {"content": out["json"], "format": "repyability"}))
    assert any("drawn in place" in n for n in back["diagrams"][0]["import_notes"])
