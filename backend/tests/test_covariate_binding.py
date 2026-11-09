"""Covariates fixed at a position, the rest set in an RBD (covariate_binding.py,
covariate_positions.py): one mechanism for NSWC-11 covariate models, ALT and PH models. A
position fixes some, all or none; a block built from the tree takes the rest from its own values,
then the diagram's Use and Environment values (matched by name and unit, or mapped), then a
default the source gives; anything still missing stops the calculation and says which blocks need
what."""

import math

import mongomock
import pytest

from backend.maintenance import covariate_positions as cp
from backend.maintenance import position_models as pm
from backend.maintenance.service import PROJECTORS, Invalid, Maintenance
from backend.maintenance.store import GraphStore
from backend.library import service as library
from backend.services import covariate_binding as cb
from backend.services import rbd_analysis, rbds
from backend.services.rbd_graph import GraphError, normalize_graph

ORG = "org-binding"
OWNERS = [ORG, "__samples__"]
BEARING = "nswc-11:bearing-rolling-load-rating"
ALT = "sample-alt-seal"
PH = "sample-model-pump-load-weibull-ph"
COND = {"L_S": 5000, "F_R": 1000, "n": 1800}


@pytest.fixture()
def m():
    return Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")


@pytest.fixture()
def db():
    from backend.services import samples

    d = mongomock.MongoClient()["covariate_binding"]
    samples.seed_samples(d)
    return d


def _rate(values):
    return library.evaluate(BEARING, values)["result"]["total"]


# ---- the binding and a block's values ----------------------------------------------------------

def test_every_source_gives_the_same_inputs(db):
    nswc = cb.inputs_of({"source": "nswc", "ref": BEARING})
    assert {i["role"] for i in nswc} == {"design", "use", "environment"}
    alt = cb.inputs_of({"source": "alt", "ref": ALT}, db, OWNERS)
    assert [i["key"] for i in alt] == ["temp_C", "load"]
    assert [i["role"] for i in alt] == ["environment", "use"]  # a temperature is where it works
    assert alt[0]["limits"][0]["severity"] == "warn"  # outside the tested stresses: extrapolated
    ph = cb.inputs_of({"source": "ph", "ref": PH}, db, OWNERS)
    assert ph[0]["key"] == "load_pct" and ph[0]["default"] is not None
    # The user's word on what a covariate is wins.
    tagged = cb.inputs_of({"source": "alt", "ref": ALT, "roles": {"temp_C": "design"}}, db, OWNERS)
    assert tagged[0]["role"] == "design"


def test_a_binding_is_checked():
    with pytest.raises(cb.BindingError, match="Unknown input"):
        cb.normalise({"source": "nswc", "ref": BEARING, "fixed": {"nope": 1}})
    with pytest.raises(cb.BindingError, match="the bearing must turn"):
        cb.normalise({"source": "nswc", "ref": BEARING, "fixed": {"n": 0}})
    with pytest.raises(cb.BindingError, match="source"):
        cb.normalise({"source": "x", "ref": BEARING})
    b = cb.normalise({"source": "nswc", "ref": BEARING, "fixed": {"L_S": "5000", "bearing_type": "roller", "F_R": ""}})
    assert b["fixed"] == {"L_S": 5000.0, "bearing_type": "roller"}


def test_a_blocks_values_come_from_the_position_the_block_the_diagram_or_a_default():
    b = cb.normalise({"source": "nswc", "ref": BEARING, "fixed": {"L_S": 5000}})
    inputs = cb.inputs_of(b)
    conditions = [{"name": "Radial load", "role": "use", "unit": "lbf", "value": 1000},
                  {"name": "Shaft speed", "role": "use", "unit": "rpm", "value": 900},
                  {"name": "Temperature", "role": "environment", "unit": "°C", "value": 200}]
    got = cb.resolve_node(b, inputs, {"n": 1800}, conditions, {"T_O": "Temperature"})
    s = got["sources"]
    assert s["L_S"]["from"] == "fixed" and s["n"]["from"] == "block"
    assert s["F_R"] == {"from": "diagram", "name": "Radial load", "words": "the diagram's Use: Radial load"}
    assert s["T_O"]["from"] == "diagram" and got["values"]["T_O"] == 200  # mapped: the names differ
    assert s["R"]["from"] == "default" and got["missing"] == []
    # Not matched (a different unit), not mapped, no default: missing, never guessed.
    got = cb.resolve_node(b, inputs, {}, [{"name": "Radial load", "role": "use", "unit": "N", "value": 4448}])
    assert [i["key"] for i in got["missing"]] == ["F_R", "n"]
    assert cb.needs_words("Bearing A", got["missing"]) == "Bearing A needs Radial load (Use, lbf), Operating speed (Use, rpm)"


def test_an_rbd_graph_takes_a_bound_block():
    graph = {"nodes": [{"id": "in", "type": "input"}, {"id": "out", "type": "output"},
                       {"id": "a", "type": "component", "label": "A",
                        "model": {"kind": "bound", "binding": {"source": "nswc", "ref": BEARING}},
                        "covariate_values": {"n": 1800}}],
             "edges": [{"source": "in", "target": "a"}, {"source": "a", "target": "out"}],
             "conditions": [{"name": "Temperature", "role": "environment", "unit": "°C", "value": 80}]}
    g = normalize_graph(graph)
    node = next(n for n in g["nodes"] if n["id"] == "a")
    assert node["data"]["model"]["kind"] == "bound" and node["data"]["covariate_values"] == {"n": 1800}
    assert g["conditions"] == [{"name": "Temperature", "role": "environment", "unit": "°C", "value": 80}]
    with pytest.raises(GraphError, match="role is use or environment"):
        normalize_graph({**graph, "conditions": [{"name": "x", "role": "design", "value": 1}]})
    with pytest.raises(GraphError, match="named twice"):
        normalize_graph({**graph, "conditions": [{"name": "x", "value": 1}, {"name": "X", "value": 2}]})


# ---- at a position, then in the RBD built from the tree --------------------------------------

def _system(m):
    """A gearbox with two bearings inside it, in series."""
    box = m.create_position("Gearbox")["id"]
    a = m.create_position("Input bearing", parent_id=box)["id"]
    b = m.create_position("Output bearing", parent_id=box)["id"]
    return box, a, b


def _analyse(db, graph, covariates=None):
    return rbds.analyze_graph(db, graph, OWNERS, t_max=2000, covariates=covariates)


def test_fixing_every_covariate_makes_a_plain_constant_rate_model(m, db):
    box, a, _ = _system(m)
    every = {i["key"]: COND.get(i["key"], i.get("default")) for i in cb.inputs_of({"source": "nswc", "ref": BEARING})}
    link = cp.bind(m, db, ORG, OWNERS, a, {"source": "nswc", "ref": BEARING, "fixed": every})
    assert link["model_type"] == "model" and link["role"] == "library"
    model = db.models.find_one({"_id": link["model_id"]})
    assert model["distribution_id"] == "exponential" and "did not take part" in model["spec"]["notes"]
    assert model["results"]["params"][0]["value"] == pytest.approx(_rate(COND) / 1e6)
    [row] = pm.describe(m, db, OWNERS, set(), m.position_models(a))
    assert "every covariate fixed here" in row["source_text"]


def test_fix_some_at_a_position_then_set_the_rest_in_the_rbd(m, db):
    box, a, b = _system(m)
    # Design fixed at each position; use and environment left open.
    for pid, rating in ((a, 5000), (b, 8000)):
        link = cp.bind(m, db, ORG, OWNERS, pid, {"source": "nswc", "ref": BEARING,
                                                 "fixed": {"L_S": rating, "bearing_type": "ball"}})
        assert link["model_type"] == cp.MODEL_TYPE and "2 of 14 covariates fixed here" in link["source"]["binding_words"]
    [row] = pm.describe(m, db, OWNERS, set(), m.position_models(a))
    assert row["model"]["kind"] == "Covariate model (NSWC-11)"
    built = pm.build_rbd(m, db, OWNERS, set(), box, owner_id=ORG)
    graph = db.rbds.find_one({"_id": built["model_id"]})["graph"]
    blocks = {n["data"]["label"]: n for n in graph["nodes"] if n["type"] == "component"}
    assert blocks["Input bearing"]["data"]["model"]["kind"] == "bound"
    # Nothing set yet: the calculation says which blocks need what.
    with pytest.raises(rbd_analysis.AnalysisError) as err:
        _analyse(db, graph)
    assert "Input bearing needs Radial load (Use, lbf), Operating speed (Use, rpm)" in str(err.value)
    assert "Output bearing needs" in str(err.value)
    # The diagram's Use values apply to every block; one block overrides its speed.
    graph["conditions"] = [{"name": "Radial load", "role": "use", "unit": "lbf", "value": 1000},
                           {"name": "Operating speed", "role": "use", "unit": "rpm", "value": 1800}]
    blocks["Output bearing"]["data"]["covariate_values"] = {"n": 900}
    out = _analyse(db, graph)
    lam = _rate({**COND, "L_S": 5000}) + _rate({"L_S": 8000, "F_R": 1000, "n": 900})
    assert out["mttf"] == pytest.approx(1e6 / lam, rel=1e-3)
    # A harsher environment for every block: the system's life falls.
    graph["conditions"].append({"name": "Bearing operating temperature", "role": "environment", "unit": "°C",
                                "value": 220})
    assert _analyse(db, graph)["mttf"] < out["mttf"]


def test_an_alt_model_fixed_at_a_position_is_a_constant_stress_model(m, db):
    from backend.services import alt as alt_service

    box, a, _ = _system(m)
    link = cp.bind(m, db, ORG, OWNERS, a, {"source": "alt", "ref": ALT, "fixed": {"temp_C": 70, "load": 0.6}})
    assert link["model_type"] == "alt_model" and "every covariate fixed here" in link["source"]["binding_words"]
    built = pm.build_rbd(m, db, OWNERS, set(), box, owner_id=ORG)
    graph = db.rbds.find_one({"_id": built["model_id"]})["graph"]
    graph["nodes"] = [n for n in graph["nodes"] if n.get("data", {}).get("label") != "Output bearing"]
    graph["edges"] = [{"source": "in", "target": n["id"]} for n in graph["nodes"] if n["type"] == "component"] + \
                     [{"source": n["id"], "target": "out"} for n in graph["nodes"] if n["type"] == "component"]
    out = _analyse(db, graph)
    at = alt_service.evaluate(db, ALT, [70, 0.6], OWNERS, mission_time=500)
    t = out["time"]
    i = min(range(len(t)), key=lambda j: abs(t[j] - 500))
    assert out["system"]["sf"][i] == pytest.approx(at["metrics"]["mission_reliability"], abs=0.02)


def test_an_alt_model_left_variable_is_set_in_the_rbd(m, db):
    _, a, _ = _system(m)
    link = cp.bind(m, db, ORG, OWNERS, a, {"source": "alt", "ref": ALT, "fixed": {"load": 0.6}})
    block = cp.block_model(link)
    graph = {"unit": "hours", "nodes": [{"id": "in", "type": "input"}, {"id": "out", "type": "output"},
                                        {"id": "s", "type": "component", "label": "Seal", **block}],
             "edges": [{"source": "in", "target": "s"}, {"source": "s", "target": "out"}]}
    graph = normalize_graph(graph)
    with pytest.raises(rbd_analysis.AnalysisError, match=r"Seal needs Temperature \(°C\) \(Environment\)"):
        _analyse(db, graph)
    graph["conditions"] = [{"name": "Temperature (°C)", "role": "environment", "unit": "", "value": 70}]
    cool = _analyse(db, graph)["mttf"]
    graph["nodes"][-1]["data"]["covariate_values"] = {"temp_C": 95}  # this block runs hotter
    assert _analyse(db, graph)["mttf"] < cool


def test_a_ph_model_takes_its_covariates_the_same_way(m, db, monkeypatch):
    from backend import db as db_module

    monkeypatch.setattr(db_module, "get_db", lambda: db)  # the PH model refits from its dataset there
    _, a, _ = _system(m)
    link = cp.bind(m, db, ORG, OWNERS, a, {"source": "ph", "ref": PH, "roles": {"load_pct": "use"}})
    assert link["model_type"] == "model" and link["source"]["binding"]["fixed"] == {}
    graph = normalize_graph({"unit": "hours", "nodes": [
        {"id": "in", "type": "input"}, {"id": "out", "type": "output"},
        {"id": "p", "type": "component", "label": "Pump", **cp.block_model(link)}],
        "edges": [{"source": "in", "target": "p"}, {"source": "p", "target": "out"}]})
    light = _analyse(db, {**graph, "conditions": [{"name": "load_pct", "role": "use", "unit": "%", "value": 40}]})
    heavy = _analyse(db, {**graph, "conditions": [{"name": "load_pct", "role": "use", "unit": "%", "value": 100}]})
    assert math.isfinite(light["mttf"]) and heavy["mttf"] != light["mttf"]


def test_existing_alt_and_ph_links_without_a_binding_work_as_before(m, db):
    box, a, b = _system(m)
    pm.link_saved(m, db, OWNERS, set(), a, "model", PH)
    built = pm.build_rbd(m, db, OWNERS, set(), box, owner_id=ORG)
    graph = db.rbds.find_one({"_id": built["model_id"]})["graph"]
    node = next(n for n in graph["nodes"] if n.get("data", {}).get("label") == "Input bearing")
    assert node["data"]["model"].get("kind") == "regression"


def test_a_parts_count_line_starts_from_the_fixed_values(m, db):
    pos = m.create_position("Drive")["id"]
    part = m.create_part("B-1", "Bearing")["id"]
    m.add_position_part(pos, part, role="component", quantity=1)
    cp.bind(m, db, ORG, OWNERS, pos, {"source": "nswc", "ref": BEARING, "fixed": COND})
    got = pm.predict_position(m, db, OWNERS, set(), pos, assign={"B-1": {"record_id": BEARING}})
    assert got["lines"][0]["conditions"] == COND
    assert got["results"]["failure_rate_per_million_hours"] == pytest.approx(_rate(COND))


def test_a_bad_binding_is_refused_at_the_position(m, db):
    _, a, _ = _system(m)
    with pytest.raises(Invalid, match="Unknown input"):
        cp.bind(m, db, ORG, OWNERS, a, {"source": "nswc", "ref": BEARING, "fixed": {"zzz": 1}})


def test_an_assembly_is_per_hour_and_never_multiplied_again():
    # NSWC-11 assemblies are per million hours, their per-cycle parts converted inside them (pp. 12-10, 12-16):
    # a bound block takes the assembly's rate as it is, and adds no cycles an hour of its own. A gear coupling
    # has its own "cycles_per_hour" input, which it must still read.
    ref = "nswc-11:coupling-gear"
    keys = [i["key"] for i in cb.inputs_of({"source": "nswc", "ref": ref})]
    assert keys.count("cycles_per_hour") == 1
    values = {"lambda_CP_B": 2.0, "cycles_per_hour": 10, "n_GR": 1, "n_SE": 1,
              "gears.V_o": 1800, "gears.V_d": 1800, "gears.L_O": 1000, "gears.L_D": 1000,
              "seals.P1": 100, "seals.Q_f": 0.06, "seals.D_SL": 2, "seals.n": 100, "seals.V_lin": 0, "seals.M": 500,
              "seals.C": 910, "seals.f": 15, "seals.T_R": 250, "seals.T_O": 100, "seals.source": "piston_pump",
              "seals.FR": 10}
    per_million = library.evaluate(ref, values)["result"]["total"]
    model = cb.concrete({"source": "nswc", "ref": ref}, values)
    assert model["params"][0]["value"] == pytest.approx(per_million / 1e6)
    # The gear at its design point gives its base rate (Reliafy's reading, p. 8-8): 1,080 per million hours.
    gears = next(m for m in library.evaluate(ref, values)["result"]["modes"] if m["key"] == "gears")
    assert gears["rate"] == pytest.approx(1080.0)
