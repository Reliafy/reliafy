"""Missions and tree-built RBDs: what a walk-through found unclear.

- A mission's own RBD is renamed with the mission ("<position> — <mission>"), unless the diagram
  was renamed by hand.
- A rebuild keeps blocks whose positions were deleted since (every edit is kept) but names them,
  and the RBD's plan read from the tree names them too.
- Running-time maintenance with Runs blank runs all the time: running hours are calendar hours.
- The Missions tab is told which positions have a model in use that can't be a block."""

import mongomock
import pytest

from backend.maintenance import position_models as pm
from backend.maintenance import rbd_tree_plan
from backend.maintenance.service import PROJECTORS, Maintenance
from backend.maintenance.store import GraphStore
from backend.services import rbd_maintenance
from backend.services import rbd_missions as rm

ORG = "org-mission-friction"
OWNERS = [ORG, "__samples__"]
SAMPLE = "sample-model-bearings-weibull"


@pytest.fixture()
def m():
    return Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")


@pytest.fixture()
def db():
    from backend.services import samples

    d = mongomock.MongoClient()["mission_friction"]
    samples.seed_samples(d)
    return d


def _station(m, db, n=2):
    plant = m.create_position("Pump station")["id"]
    kids = []
    for i in range(n):
        k = m.create_position(f"Pump {chr(65 + i)}", parent_id=plant)["id"]
        pm.link_saved(m, db, OWNERS, set(), k, "model", SAMPLE)
        kids.append(k)
    return plant, kids


def test_renaming_a_mission_renames_its_own_rbd(m, db):
    plant, _ = _station(m, db)
    made = pm.build_mission_rbd(m, db, OWNERS, set(), plant, ORG, "Mission 1")
    before = db.rbds.find_one({"_id": made["rbd"]["id"]})["graph"]
    after, _ = rm.save(before, rm.LEGACY_ID, name="Summer peak")
    assert rm.rbd_name_after("Pump station — Mission 1", before, after) == "Pump station — Summer peak"
    # Renamed by hand: left alone. Not a mission's own diagram: left alone.
    assert rm.rbd_name_after("My diagram", before, after) == "My diagram"
    assert rm.rbd_name_after("Pump station — Mission 1", {}, {"mission_name": "X"}) == "Pump station — Mission 1"


def test_a_rebuild_names_blocks_whose_positions_were_deleted(m, db):
    plant, (a, b) = _station(m, db)
    link = pm.build_rbd(m, db, OWNERS, set(), plant)
    m.retire_position(b, "gone", cascade=True)
    again = pm.build_rbd(m, db, OWNERS, set(), plant, replace_link_id=link["id"])
    assert any("“Pump B” stands for a position no longer inside Pump station" in n for n in again["notes"])
    graph = db.rbds.find_one({"_id": again["model_id"]})["graph"]
    gone = rbd_tree_plan.gone_blocks(m, plant, graph, [a, b])
    assert [(g["label"], g["why"]) for g in gone] == [("Pump B", "deleted")]
    # The plan read from the tree names it too (the deleted id stays in the built row's source).
    plans = rbd_tree_plan.plans_for_graph(m, again["model_id"], graph)
    assert [g["label"] for g in plans["gone"]] == ["Pump B"]
    # Delete the block from the diagram: nothing named any more.
    kept = {**graph, "nodes": [n for n in graph["nodes"] if (n.get("data") or {}).get("label") != "Pump B"]}
    assert rbd_tree_plan.plans_for_graph(m, again["model_id"], kept)["gone"] == []


def test_running_time_with_runs_blank_is_calendar_time():
    data = {"preventive": {"policy": "age", "operating_interval": 12000}}
    assert rbd_maintenance.preventive_spec(data, "Pump")["interval"] == pytest.approx(12000)
    half = {**data, "duty": 0.5}
    assert rbd_maintenance.preventive_spec(half, "Pump")["interval"] == pytest.approx(24000)


def test_the_missions_read_names_positions_whose_model_cant_be_a_block(m, db):
    from backend.routers import maintenance as router

    plant, (a, _b) = _station(m, db)
    lone = m.create_position("Lone RBD position")["id"]
    from backend.services import rbds as rbds_service

    rbd = rbds_service.save_rbd(db, "Repairable", {"unit": "hours", "repairable": True, "nodes": [], "edges": []}, ORG)
    pm.link_rbd(m, db, OWNERS, set(), lone, rbd.id)

    class Ctx:
        read_owners = OWNERS
        hidden = set()

    resp = router.position_missions(None, session=db, ctx=Ctx(), m=m)
    import json

    body = json.loads(resp.body)
    assert a in body["has_model"]
    # An RBD in use isn't a "model that can't be a block": the RBD has its own reason.
    assert lone not in body["other_model"]
