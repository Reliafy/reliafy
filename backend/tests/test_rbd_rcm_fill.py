"""Fill a repairable block's maintenance from an RCM study (#100): which
tasks map onto a scheduled replacement or a proof test (and which can't, and
why), who may read them, and that the recorded link changes neither the
analysis nor the saved-result key."""

import copy
from types import SimpleNamespace

import matplotlib

matplotlib.use("Agg")

import mongomock  # noqa: E402
import numpy as np  # noqa: E402
import pytest  # noqa: E402

from backend.services import rbd_analysis as ra  # noqa: E402
from backend.services import rbd_rcm  # noqa: E402
from backend.services.rbds import availability_cache_key  # noqa: E402
from backend.tests.test_rbd_costs import _exp, _ln, _node, _series, _w  # noqa: E402
from backend.tests.test_teams import (  # noqa: E402,F401 - fixture
    A, B, C, _create_team, _make_pro, _register, client,
)


def _analysis(kind, inputs, results, name="Evidence"):
    return SimpleNamespace(kind=kind, inputs=inputs, results=results, name=name)


REPLACEMENT = _analysis(
    "optimal_replacement",
    {"planned_cost": 200.0, "unplanned_cost": 1500.0, "unit": "hours"},
    {"beneficial": True, "optimal_time": 612.4, "unit": "hours"},
    name="Bearing replacement",
)
FINDING = _analysis("failure_finding", {"unit": "hours"}, {"interval": 176.0, "unit": "hours"},
                    name="Brake circuit FFI")


# ---------------------------------------------------------------------------
# Mapping one decision
# ---------------------------------------------------------------------------
def test_fixed_interval_fills_an_age_replacement_with_the_analysis_cost():
    decision = {"outcome": "fixed_interval", "interval": 580, "interval_unit": "hours",
                "evidence": {"type": "strategy_analysis", "id": "x"}}
    m = rbd_rcm.map_decision(decision, REPLACEMENT, "hours")
    assert m["target"] == "preventive"
    # The task's own interval wins over the analysis's optimum; the cost of a
    # planned replacement comes from the analysis; nothing else is filled.
    assert m["fill"] == {"policy": "age", "interval": 580.0, "cost": 200.0}
    assert m["sources"] == {"interval": "task", "cost": "analysis"}
    assert m["analysis_name"] == "Bearing replacement"
    # Without the analysis there's no cost to fill.
    m = rbd_rcm.map_decision(decision, None, "hours")
    assert m["fill"] == {"policy": "age", "interval": 580.0} and m["sources"] == {"interval": "task"}
    assert "analysis_name" not in m


def test_a_task_without_an_interval_takes_its_analysis_interval():
    m = rbd_rcm.map_decision({"outcome": "failure_finding"}, FINDING, "Hours")
    assert m["target"] == "inspection"
    assert m["fill"] == {"interval": 176.0} and m["sources"] == {"interval": "analysis"}
    assert m["interval_unit"] == "hours"
    m = rbd_rcm.map_decision({"outcome": "fixed_interval"}, REPLACEMENT, "hours")
    assert m["fill"]["interval"] == pytest.approx(612.4) and m["sources"]["interval"] == "analysis"
    # An analysis of the wrong kind lends nothing.
    m = rbd_rcm.map_decision({"outcome": "failure_finding"}, REPLACEMENT, "hours")
    assert "target" not in m and "no interval" in m["reason"]


@pytest.mark.parametrize("decision, needle", [
    ({"outcome": "on_condition", "task": "Measure pad wear"}, "Condition monitoring"),
    ({"outcome": "rtf", "rtf_basis": "random"}, "Run-to-failure"),
    ({"outcome": "redesign"}, "redesign"),
    ({"outcome": "accept"}, "Accepting the risk"),
    (None, "No task has been decided"),
    ({"outcome": "fixed_interval"}, "no interval"),
    ({"outcome": "fixed_interval", "interval": 30, "interval_unit": "days"}, "in days but this diagram is in hours"),
])
def test_unmappable_tasks_say_why(decision, needle):
    m = rbd_rcm.map_decision(decision, None, "hours")
    assert set(m) == {"reason"} and needle in m["reason"], m


def test_units_compare_through_their_aliases_and_a_missing_unit_passes():
    d = {"outcome": "failure_finding", "interval": 100, "interval_unit": "hrs"}
    assert rbd_rcm.map_decision(d, None, "Hours")["target"] == "inspection"
    assert rbd_rcm.map_decision(d, None, "")["target"] == "inspection"
    assert rbd_rcm.map_decision({**d, "interval_unit": None}, None, "cycles")["target"] == "inspection"


def test_the_sample_rcm_study_maps_its_bearing_and_brake_circuit_tasks():
    from backend.schema import RcmStudy
    from backend.db import from_doc
    from backend.services import samples

    db = mongomock.MongoClient()["reliafy_test"]
    samples.seed_samples(db)
    study = from_doc(RcmStudy, db.rcm_studies.find_one({"_id": "sample-rcm-truck"}))
    out = rbd_rcm.maintenance_tasks(db, study, [study.owner_id], unit="hours")
    rows = {t["mode_id"]: t for t in out["tasks"]}
    assert out["study"].startswith("Delivery truck") and out["mappable"] == 2
    bearing = rows["sample-rcm-m3"]
    assert bearing["target"] == "preventive" and bearing["outcome_label"] == "Fixed-interval replacement"
    assert bearing["fill"] == {"policy": "age", "interval": 580.0, "cost": 200.0}
    brakes = rows["sample-rcm-m2"]
    assert brakes["target"] == "inspection" and brakes["sources"] == {"interval": "analysis"}
    assert brakes["fill"]["interval"] > 0
    for mid in ("sample-rcm-m1", "sample-rcm-m4", "sample-rcm-m5"):
        assert rows[mid]["reason"] and "target" not in rows[mid]
    # A diagram in another unit gets nothing converted behind its back.
    days = rbd_rcm.maintenance_tasks(db, study, [study.owner_id], unit="days")
    assert days["mappable"] == 0


# ---------------------------------------------------------------------------
# Access: only studies (and evidence) the caller can read
# ---------------------------------------------------------------------------
def _tree(evidence_id=None, interval=None):
    decision = {"outcome": "fixed_interval", "task": "Replace the bearing"}
    if interval:
        decision.update(interval=interval, interval_unit="hours")
    if evidence_id:
        decision["evidence"] = {"type": "strategy_analysis", "id": evidence_id}
    return [{"text": "Rotate", "failures": [{"text": "Seizes", "modes": [
        {"id": "m1", "text": "Bearing wear", "consequence": "operational", "decision": decision}]}]}]


def _replacement_body(name="Repl"):
    return {"name": name, "kind": "optimal_replacement", "inputs": {
        "distribution_id": "weibull",
        "params": [{"name": "alpha", "value": 1000.0}, {"name": "beta", "value": 3.0}],
        "planned_cost": 150.0, "unplanned_cost": 2000.0, "unit": "hours"}}


def _save_replacement(client, headers=None):
    r = client.post("/api/strategy/analyses", json=_replacement_body(), headers=headers or {})
    assert r.status_code == 200, r.json()
    return r.json()["id"]


def test_tasks_endpoint_respects_study_access(client):
    _make_pro(client.db, A)
    client.act_as(A)
    aid = _save_replacement(client)
    sid = client.post("/api/rcm/studies", json={"name": "Mine"}).json()["id"]
    assert client.put(f"/api/rcm/studies/{sid}/tree",
                      json={"functions": _tree(aid, interval=500)}).status_code == 200
    r = client.get(f"/api/rcm/studies/{sid}/maintenance-tasks", params={"unit": "hours"})
    assert r.status_code == 200
    [task] = r.json()["tasks"]
    assert task["fill"] == {"policy": "age", "interval": 500.0, "cost": 150.0}
    assert task["task"] == "Replace the bearing"

    # Someone else can't read the study, so gets nothing from it.
    client.act_as(C)
    assert client.get(f"/api/rcm/studies/{sid}/maintenance-tasks").status_code == 404
    # Nor does citing A's analysis in C's own study lend C its cost.
    own = client.post("/api/rcm/studies", json={"name": "Theirs"}).json()["id"]
    # Saving that link is refused; the study stands for one saved before.
    assert client.put(f"/api/rcm/studies/{own}/tree",
                      json={"functions": _tree(aid, interval=500)}).status_code == 422
    from backend.services import rcm as rcm_service

    client.db.rcm_studies.update_one(
        {"_id": own}, {"$set": {"functions": rcm_service.clean_tree(_tree(aid, interval=500))}})
    [task] = client.get(f"/api/rcm/studies/{own}/maintenance-tasks").json()["tasks"]
    assert task["fill"] == {"policy": "age", "interval": 500.0} and "cost" not in task["sources"]
    # Unknown ids are the same 404.
    assert client.get("/api/rcm/studies/nope/maintenance-tasks").status_code == 404


def test_team_study_tasks_are_read_in_the_team_workspace(client):
    _make_pro(client.db, A)
    _make_pro(client.db, B)
    _register(client.db, B)
    client.act_as(A)
    tid = _create_team(client)
    client.post(f"/api/teams/{tid}/members", json={"email": "b@x.com"})
    h = {"X-Workspace-Id": tid}
    aid = _save_replacement(client, h)
    sid = client.post("/api/rcm/studies", json={"name": "Team"}, headers=h).json()["id"]
    assert client.put(f"/api/rcm/studies/{sid}/tree", headers=h,
                      json={"functions": _tree(aid)}).status_code == 200

    client.act_as(B)  # a member: the study and its evidence
    r = client.get(f"/api/rcm/studies/{sid}/maintenance-tasks", headers=h, params={"unit": "hours"})
    assert r.status_code == 200, r.json()
    [task] = r.json()["tasks"]
    assert task["target"] == "preventive" and task["sources"] == {"interval": "analysis", "cost": "analysis"}
    assert task["fill"]["cost"] == 150.0

    client.act_as(C)  # not a member
    assert client.get(f"/api/rcm/studies/{sid}/maintenance-tasks").status_code == 404
    assert client.get(f"/api/rcm/studies/{sid}/maintenance-tasks", headers=h).status_code == 403


# ---------------------------------------------------------------------------
# The link is provenance only
# ---------------------------------------------------------------------------
SOURCE = {"study_id": "sample-rcm-truck", "mode_id": "sample-rcm-m3",
          "study": "Delivery truck — RCM demo (sample)", "mode": "Wheel-bearing fatigue",
          "target": "preventive", "filled": {"policy": "age", "interval": 580, "cost": 200}}


def _bearing(**extra):
    return _node("brg", 200, 0, model=_w(1000, 2.5), repair=_ln(3.0, 0.5), costs={"replace": 1500},
                 preventive={"policy": "age", "interval": 580, "cost": 200}, **extra)


def test_the_rcm_link_changes_neither_results_nor_the_cache_key():
    plain = _series(_bearing(), costs={"downtime_rate": 100})
    linked = _series(_bearing(rcm_source=copy.deepcopy(SOURCE)), costs={"downtime_rate": 100})
    assert availability_cache_key(linked) == availability_cache_key(plain)
    assert availability_cache_key(linked, 5000) == availability_cache_key(plain, 5000)
    assert ra.validate_graph(linked)["valid"]
    a = ra.analyze_availability(plain, n_simulations=60)
    b = ra.analyze_availability(linked, n_simulations=60)
    assert b["steady_state_availability"] == a["steady_state_availability"]
    assert b["costs"]["cost_rate"] == a["costs"]["cost_rate"]
    assert b["costs"]["simulated"]["mean"] == a["costs"]["simulated"]["mean"]
    assert np.array_equal(b["curve"]["availability"], a["curve"]["availability"])
    # The filled values themselves are analysed, so editing one still counts.
    edited = copy.deepcopy(linked)
    edited["nodes"][2]["data"]["preventive"]["interval"] = 600
    assert availability_cache_key(edited) != availability_cache_key(linked)


def test_the_rcm_link_survives_the_compact_graph_format():
    from backend.services.rbd_graph import compact_graph, normalize_graph

    g = _series(_bearing(rcm_source=copy.deepcopy(SOURCE)))
    back = compact_graph(g)
    brg = next(n for n in back["nodes"] if n["id"] == "brg")
    assert brg["rcm_source"] == SOURCE
    again = normalize_graph(back)
    data = next(n for n in again["nodes"] if n["id"] == "brg")["data"]
    assert data["rcm_source"] == SOURCE


def test_an_unlinked_exponential_block_is_unaffected():
    """A block with no maintenance and a stray link builds as a plain block."""
    from repyability import NonRepairable

    g = _series(_node("p", model=_exp(1e-3), repair=_exp(0.1), rcm_source=copy.deepcopy(SOURCE)))
    rbd = ra._build_repairable_rbd(g)[0]
    assert isinstance(rbd.components["p"], NonRepairable) and not rbd.costs
