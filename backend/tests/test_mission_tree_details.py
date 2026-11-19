"""The Explorer's mission tree: each phase's covariates (automatic, from the life models of the
mission's RBD) and node status rules (a block's state in the phase: standby, warm standby,
guaranteed working, not needed), the phase results kept for the tree, and the covariate list the
builder's Phased mission editor reads (one list, one store: the RBD's own phases).

Guaranteed working is checked against RePyability's own ``PhasedMission.from_diagram`` (the
pinned release's ``"guaranteed"`` state) and closed forms; warm standby by hand."""

import math

import pandas as pd
import pytest
import surpyval as sp
from repyability import MissionPhase, NonRepairableRBD, PhasedMission

from backend import fitting
from backend.services import rbd_missions as rm
from backend.services import rbd_phases, samples
from backend.services.rbd_graph import normalize_graph

E = math.exp
INTERVALS = {"i": "pump", "xl": "start_h", "xr": "stop_h", "c": "censored"}


def _exp(rate):
    return {"distribution_id": "exponential", "params": [{"name": "failure_rate", "value": rate}]}


def _weibull(alpha, beta):
    return {"distribution_id": "weibull", "params": [{"name": "alpha", "value": alpha}, {"name": "beta", "value": beta}]}


def _diagram(edges, models):
    nodes = [{"id": "input", "type": "input", "data": {}}, {"id": "output", "type": "output", "data": {}}]
    for nid, model in models.items():
        nodes.append({"id": nid, "type": "component", "data": {"label": nid.upper(), "model": model}})
    return {"unit": "hours", "nodes": nodes, "edges": [{"source": s, "target": t} for s, t in edges]}


def _series(a, b):
    return _diagram([("input", "a"), ("a", "b"), ("b", "output")], {"a": a, "b": b})


# ---- the stored shape ---------------------------------------------------------------------------

def test_guaranteed_and_dormancy_are_kept_and_one_state_per_block():
    [p] = rbd_phases.parse_phases([{"name": "Climb", "duration": 2, "guaranteed": ["a", "a"], "standby": ["b"],
                                    "dormancy": {"b": 0.25, "a": 0.5, "c": 0.1}}])
    # Dormancy goes with a standby block only (a's and c's are dropped: they're not standing by).
    assert p == {"name": "Climb", "duration": 2.0, "standby": ["b"], "guaranteed": ["a"], "dormancy": {"b": 0.25}}
    with pytest.raises(rbd_phases.PhaseError, match="one state in a phase"):
        rbd_phases.parse_phases([{"name": "Climb", "duration": 1, "guaranteed": ["a"], "not_needed": ["a"]}])
    with pytest.raises(rbd_phases.PhaseError, match="dormancy of 'b' must be a number from 0 to 1"):
        rbd_phases.parse_phases([{"name": "Climb", "duration": 1, "standby": ["b"], "dormancy": {"b": 2}}])
    # Carried through every save of the diagram.
    g = normalize_graph({**_series(_exp(0.01), _exp(0.02)), "phases": [p]})
    assert g["phases"][0]["guaranteed"] == ["a"]
    assert g["phases"][0]["dormancy"] == {"b": 0.25}


# ---- the figures ---------------------------------------------------------------------------------

def test_guaranteed_matches_repyabilitys_own_mission_exponential_and_weibull():
    life = sp.Weibull.from_params([50.0, 2.5])
    graph = _series(_exp(0.01), _weibull(50.0, 2.5))
    phases = [{"name": "one", "duration": 30.0, "guaranteed": ["b"]}, {"name": "two", "duration": 20.0}]
    out = rbd_phases.analyze_phases(graph, phases=phases)
    rbd = NonRepairableRBD([("s", "a"), ("a", "b"), ("b", "t")], {"a": sp.Exponential.from_params([0.01]), "b": life})
    ref = PhasedMission.from_diagram(rbd, [MissionPhase("one", 30.0, blocks={"b": "guaranteed"}),
                                           MissionPhase("two", 20.0)])
    closed = E(-0.01 * 50.0) * float(life.sf(50.0)) / float(life.sf(30.0))
    assert out["reliability"] == pytest.approx(closed, rel=1e-9)
    assert out["reliability"] == pytest.approx(ref.reliability(), rel=1e-9)
    # In phase one only a can fail.
    assert out["phases"][0]["failure_probability"] == pytest.approx(1 - E(-0.01 * 30.0), rel=1e-9)
    assert out["phases"][0]["guaranteed"] == ["B"]
    assert rbd_phases.GUARANTEED_NOTE in out["notes"]


def test_guaranteed_in_parallel_matches_repyability():
    graph = _diagram([("input", "a"), ("input", "b"), ("a", "output"), ("b", "output")],
                     {"a": _exp(0.02), "b": _weibull(40.0, 1.8)})
    phases = [{"name": "one", "duration": 15.0}, {"name": "two", "duration": 10.0, "guaranteed": ["a"]},
              {"name": "three", "duration": 12.0}]
    out = rbd_phases.analyze_phases(graph, phases=phases)
    rbd = NonRepairableRBD([("s", "a"), ("s", "b"), ("a", "t"), ("b", "t")],
                           {"a": sp.Exponential.from_params([0.02]), "b": sp.Weibull.from_params([40.0, 1.8])})
    ref = PhasedMission.from_diagram(rbd, [MissionPhase("one", 15.0), MissionPhase("two", 10.0, blocks={"a": "guaranteed"}),
                                           MissionPhase("three", 12.0)])
    assert out["reliability"] == pytest.approx(ref.reliability(), rel=1e-9)


def test_warm_standby_ages_at_its_dormancy():
    # A runs; B stands by through phase one, ageing at half A's rate while idle, and is called on if
    # A fails; both run in phase two. By hand (exponential lives, rate 0.01): A survives phase one
    # (B alive or not), or A fails at s and B, still alive, runs from s to 30.
    graph = _diagram([("input", "a"), ("input", "b"), ("a", "output"), ("b", "output")],
                     {"a": _exp(0.01), "b": _exp(0.01)})
    cold = rbd_phases.analyze_phases(graph, phases=[{"name": "one", "duration": 10, "standby": ["b"]},
                                                    {"name": "two", "duration": 20}])
    warm = rbd_phases.analyze_phases(graph, phases=[{"name": "one", "duration": 10, "standby": ["b"],
                                                     "dormancy": {"b": 0.5}}, {"name": "two", "duration": 20}])
    pair = 1 - (1 - E(-0.2)) ** 2
    assert cold["reliability"] == pytest.approx(E(-0.1) * pair + 0.1 * E(-0.3), rel=1e-9)
    hand = E(-0.1) * (E(-0.05) * pair + (1 - E(-0.05)) * E(-0.2)) + 2 * E(-0.3) * (1 - E(-0.05))
    assert warm["reliability"] == pytest.approx(hand, rel=1e-9)
    assert warm["reliability"] < cold["reliability"]
    assert rbd_phases.WARM_NOTE in warm["notes"]


def test_a_node_status_rule_changes_the_mission_result():
    graph = _series(_exp(0.01), _exp(0.02))
    working = rm.analyze(None, [], graph, [{"name": "one", "duration": 10}, {"name": "two", "duration": 20}],
                         inputs_for=lambda b: [])
    held = rm.analyze(None, [], graph, [{"name": "one", "duration": 10, "guaranteed": ["b"]},
                                        {"name": "two", "duration": 20}], inputs_for=lambda b: [])
    assert working["reliability"] == pytest.approx(E(-0.03 * 30), rel=1e-9)
    assert held["reliability"] == pytest.approx(E(-0.01 * 30) * E(-0.02 * 20), rel=1e-9)


def test_python_export_reproduces_a_mission_with_guaranteed_blocks(tmp_path):
    from backend.services import rbd_export
    from backend.tests.test_rbd_export import _run

    graph = {**_series(_exp(0.01), _exp(0.02)), "phases": [{"name": "one", "duration": 10, "guaranteed": ["a"]},
                                                            {"name": "two", "duration": 20}]}
    code = rbd_export.to_python(graph, "Held")
    assert 'BlockSetting(state="guaranteed")' in code
    results, _ = _run(code, tmp_path)
    assert results["phased_mission"]["reliability"] == pytest.approx(E(-0.02 * 30) * E(-0.01 * 20), rel=1e-9)


# ---- covariates: automatic from the RBD's life models -------------------------------------------

def _pumps() -> pd.DataFrame:
    spec = next(d for d in samples.SAMPLE_DATASETS if d["id"] == "sample-ds-pump-load")
    return fitting.read_dataframe(spec["csv"])


@pytest.fixture(scope="module")
def entry():
    r = fitting.fit("weibull_ph", _pumps(), INTERVALS, ["load_pct"], unit="hours", covariate_units={"load_pct": "%"})
    return fitting._MODEL_STORE[r["functions"]["model_id"]]


def _with_ph(entry):
    """Block a a plain exponential; block p a saved PH model on load (put straight in the RBD)."""
    graph = _series(_exp(0.0001), _exp(0.0001))
    graph["nodes"][3]["data"] = {"label": "Pump", "model": {"kind": "regression", "modelId": "M",
                                                             "covariates": entry["fields"]}}
    return graph


def test_a_ph_block_puts_its_covariate_under_every_phase(entry):
    plain = _series(_exp(0.01), _exp(0.02))
    mission = {"id": "mission", "name": "Run", "phases": [{"name": "Idle", "duration": 100},
                                                         {"name": "Full", "duration": 100, "values": {"load_pct": 90}}]}
    assert rm.tree_info(plain, mission, rm.gather(plain, lambda b: [])["rows"])["covariates"] == []
    graph = _with_ph(entry)
    rows = rm.gather(graph, lambda b: [])["rows"]
    info = rm.tree_info(graph, mission, rows)
    assert [c["name"] for c in info["covariates"]] == ["load_pct"]
    assert info["covariates"][0]["feeds"] == ["Pump"]
    idle, full = info["phase_settings"]
    assert idle["covariates"][0]["value"] is None and full["covariates"][0]["value"] == 90.0
    # Unset: the fit's default stands in, and says so.
    assert idle["covariates"][0]["source"] == "default" and idle["covariates"][0]["missing"] == []


def test_a_phases_ph_value_reaches_the_mission(monkeypatch, entry):
    from backend.services import rbds as rbds_service

    monkeypatch.setattr(rbds_service, "resolvers", lambda db, owner: (None, lambda _id: entry))
    graph = _with_ph(entry)

    def run(load):
        return rm.analyze(None, [], graph, [{"name": "Run", "duration": 2000, "values": {"load_pct": load}}],
                          inputs_for=lambda b: [])["reliability"]

    low, high = run(60), run(90)
    assert high < low  # a harder phase: less chance of getting through
    Z = pd.DataFrame({"load_pct": [90.0]})
    pump = float(pd.Series(entry["model"].sf(2000.0, Z)).iloc[0])
    assert high == pytest.approx(E(-0.0001 * 2000) * pump, rel=1e-6)


def test_rules_and_result_phases_for_the_tree():
    graph = _diagram([("input", "a"), ("input", "b"), ("a", "output"), ("b", "output")], {"a": _exp(0.01), "b": _exp(0.01)})
    mission = {"id": "mission", "name": "Run", "phases": [
        {"name": "One", "duration": 10, "standby": ["b"], "dormancy": {"b": 0.2}},
        {"name": "Two", "duration": 10, "guaranteed": ["a"], "not_needed": ["gone"]}]}
    info = rm.tree_info(graph, mission, [])
    assert info["phase_settings"][0]["rules"] == [{"block": "b", "label": "B", "state": "standby", "dormancy": 0.2,
                                                    "start_probability": 1.0}]
    # A block no longer in the diagram has no row.
    assert info["phase_settings"][1]["rules"] == [{"block": "a", "label": "A", "state": "guaranteed"}]
    result = rm.analyze(None, [], graph, mission["phases"], inputs_for=lambda b: [])
    record = rm.result_record(graph, mission["phases"], result)
    assert [p["name"] for p in record["phases"]] == ["One", "Two"]
    summary = rm.summary(graph, mission, {"mission": record})
    assert summary["result"]["phases"][1]["conditional_failure"] == pytest.approx(result["phases"][1]["conditional_failure"])


def test_the_builders_covariate_list_is_the_trees(client, entry):
    graph = {"unit": "hours", "nodes": [{"id": "input", "type": "input", "data": {}},
                                        {"id": "p", "type": "component", "data": {"label": "Pump", "model": {
                                            "kind": "regression", "modelId": "M", "covariates": entry["fields"]}}},
                                        {"id": "output", "type": "output", "data": {}}],
             "edges": [{"source": "input", "target": "p"}, {"source": "p", "target": "output"}]}
    res = client.post("/api/rbds/phases/covariates", json={"graph": graph})
    assert res.status_code == 200
    assert [r["name"] for r in res.json()["rows"]] == [r["name"] for r in rm.gather(graph, lambda b: [])["rows"]]


@pytest.fixture
def client(monkeypatch):
    import mongomock
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(db, "_db", mongomock.MongoClient()["reliafy_test"])
    monkeypatch.setattr(db, "_simulated", True)
    app.dependency_overrides[get_current_user] = lambda: {"uid": "u-mission-tree", "email": "m@example.org"}
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


# ---- one store: the builder's phases are the tree's ----------------------------------------------

ORG = "org-mission-tree"
OWNERS = [ORG, "__samples__"]
SAMPLE = "sample-model-bearings-weibull"


@pytest.fixture()
def m():
    from backend.maintenance.service import PROJECTORS, Maintenance
    from backend.maintenance.store import GraphStore

    return Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")


@pytest.fixture()
def db():
    import mongomock

    d = mongomock.MongoClient()["mission_tree"]
    samples.seed_samples(d)
    return d


def _station(m, db, name="Pump station"):
    from backend.maintenance import position_models as pm

    plant = m.create_position(name)["id"]
    for i in range(2):
        k = m.create_position(f"Pump {chr(65 + i)}", parent_id=plant)["id"]
        pm.link_saved(m, db, OWNERS, set(), k, "model", SAMPLE)
    made = pm.build_mission_rbd(m, db, OWNERS, set(), plant, ORG, "Run")
    return plant, made["rbd"]["id"]


def _tree_mission(m, db, plant, rbd_id):
    rows = rm.position_missions(m, db, OWNERS, position_ids=[plant])
    return next(x for row in rows if row["rbd"] and row["rbd"]["id"] == rbd_id for x in row["missions"])


def test_the_builders_phases_and_the_trees_are_one(m, db):
    from backend.services import rbds as rbds_service

    plant, rbd_id = _station(m, db)
    doc = db.rbds.find_one({"_id": rbd_id})
    block = next(n["id"] for n in doc["graph"]["nodes"] if n.get("type") == "component")
    # The tree (the mission's update route) adds a phase with a rule: the builder's graph has it.
    graph, _ = rm.save(doc["graph"], rm.LEGACY_ID, phases=[{"name": "Start", "duration": 5, "guaranteed": [block]}])
    rbds_service.save_rbd(db, doc["name"], graph, ORG, rbd_id=rbd_id)
    saved = db.rbds.find_one({"_id": rbd_id})["graph"]
    assert saved["phases"][0]["guaranteed"] == [block]
    tree = _tree_mission(m, db, plant, rbd_id)
    label = next(b["label"] for b in tree["blocks"] if b["id"] == block)
    assert tree["phase_settings"][0]["rules"] == [{"block": block, "label": label, "state": "guaranteed"}]
    # The builder (saving the whole graph) changes it to standby: the tree reads that.
    builder = {**saved, "phases": [{"name": "Start", "duration": 5, "standby": [block], "dormancy": {block: 0.3}}]}
    rbds_service.save_rbd(db, doc["name"], builder, ORG, rbd_id=rbd_id)
    tree = _tree_mission(m, db, plant, rbd_id)
    assert tree["phase_settings"][0]["rules"][0]["state"] == "standby"
    assert tree["phase_settings"][0]["rules"][0]["dormancy"] == 0.3


def test_the_tree_read_stays_inside_the_asset_open(m, db):
    from backend.routers import maintenance as router

    plant, rbd_id = _station(m, db)
    other, other_rbd = _station(m, db, "Other station")
    links = rm.position_missions(m, db, OWNERS, position_ids=router._within_ids(m, plant, None))
    ids = {row["rbd"]["id"] for row in links if row["rbd"]}
    assert rbd_id in ids and other_rbd not in ids
