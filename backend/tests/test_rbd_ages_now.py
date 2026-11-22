"""The RBD Calculator's "As of now" reads each block's age from the item fitted at the position it
stands for (rbd_tree_plan.ages_for_graph): the counter in the diagram's unit where there is one, the
days since it was fitted for a calendar unit, and a plain reason for a block with no age, so the
result is never the new-equipment figure without saying so."""

from datetime import date, timedelta

import pytest

from backend.maintenance import position_models as pm
from backend.maintenance import rbd_tree_plan as tp
from backend.tests.test_rbd_tree_plan import OWNERS, SAMPLE, _block_of, _graph, db, m  # noqa: F401
from backend.tests.test_maintenance_rcm_api import api  # noqa: F401
from backend.tests.test_maintenance_mcp import env  # noqa: F401

M = "/api/maintenance"


def _ago(days: int) -> str:
    return (date.today() - timedelta(days=days)).isoformat()


def _station(m, db, unit="Hours"):
    plant = m.create_position("Booster station")["id"]
    ids = {name: m.create_position(name, parent_id=plant)["id"] for name in ("Pump A", "Pump B", "Controller")}
    for p in ids.values():
        pm.link_saved(m, db, OWNERS, set(), p, "model", SAMPLE)
    link = pm.build_rbd(m, db, OWNERS, set(), plant)
    db.rbds.update_one({"_id": link["model_id"]}, {"$set": {"graph.unit": unit}})
    return ids, link["model_id"]


def test_a_block_takes_its_items_counter_hours_and_says_where_they_came_from(m, db):
    ids, rbd = _station(m, db)
    m.fit(ids["Pump A"], new_item={"name": "Pump serial 41"}, on=_ago(400))
    hours = m.add_point(ids["Pump A"], "Run hours", kind="counter", unit="hours")["id"]
    for day, value in ((400, 0), (100, 13000), (0, 14000)):
        m.record_reading(hours, value, on=_ago(day))
    m.fit(ids["Pump B"], new_item={"name": "Pump serial 42"}, on=_ago(10))  # no counter: runs all the time
    graph = _graph(db, rbd)
    out = tp.ages_for_graph(m, rbd, graph)
    a = out["blocks"][_block_of(graph, "Pump A")["id"]]
    assert a["age"] == pytest.approx(14000) and a["basis"] == "counter" and a["item"] == "Pump serial 41"
    assert "Run hours" in a["note"]
    b = out["blocks"][_block_of(graph, "Pump B")["id"]]
    assert b["age"] == pytest.approx(240) and b["basis"] == "continuous"  # 10 days × 24 h, and it says so
    c = out["blocks"][_block_of(graph, "Controller")["id"]]
    assert "age" not in c and c["reason"] == "nothing is fitted at Controller"
    assert out["position"]["name"] == "Booster station" and out["unlinked"] == []


def test_an_items_own_counter_is_its_age(m, db):
    ids, rbd = _station(m, db)
    fitted = m.fit(ids["Pump A"], new_item={"name": "Pump serial 41"}, on=_ago(800))
    item_id = fitted["fitted"]["item"]["id"] if "fitted" in fitted else m.position(ids["Pump A"])["fitted"]["item"]["id"]
    hours = m.add_point(None, "Run hours", kind="counter", unit="hours", item_id=item_id)["id"]
    m.record_reading(hours, 14000, on=_ago(5))
    graph = _graph(db, rbd)
    a = tp.ages_for_graph(m, rbd, graph)["blocks"][_block_of(graph, "Pump A")["id"]]
    # Not 800 days x 24 h running all the time: the item's own meter says 14,000.
    assert a["age"] == pytest.approx(14000) and a["basis"] == "counter" and "Run hours" in a["note"]


def test_a_calendar_diagram_counts_the_time_since_fitting(m, db):
    ids, rbd = _station(m, db, unit="Days")
    m.fit(ids["Pump A"], new_item={"name": "Pump"}, on=_ago(30))
    graph = _graph(db, rbd)
    a = tp.ages_for_graph(m, rbd, graph)["blocks"][_block_of(graph, "Pump A")["id"]]
    assert a["age"] == pytest.approx(30) and a["basis"] == "calendar"


def test_a_hand_drawn_diagram_names_every_block_as_unlinked(m, db):
    from backend.services import rbds as rbds_service

    rbd = rbds_service.save_rbd(db, "By hand", {"nodes": [{"id": "x", "type": "component", "data": {"label": "Fan"}}],
                                                "edges": [], "unit": "Hours"}, "org-tree-plan")
    out = tp.ages_for_graph(m, rbd.id, rbd.graph)
    assert out["blocks"] == {} and out["unlinked"] == ["x"] and out["position"] is None


def test_rest_ages_now(api):
    plant = api.post(f"{M}/positions", json={"name": "Station"}).json()["id"]
    a = api.post(f"{M}/positions", json={"name": "Pump A", "parent_id": plant}).json()["id"]
    api.post(f"{M}/positions/{a}/models", json={"model_id": SAMPLE})
    link = api.post(f"{M}/positions/{plant}/models", json={"build_rbd": True}).json()
    out = api.post(f"{M}/rbd-ages-now", json={"rbd_id": link["model_id"]})
    assert out.status_code == 200
    [row] = out.json()["blocks"].values()
    assert "reason" in row  # nothing fitted: said, not assumed new
    assert api.post(f"{M}/rbd-ages-now", json={"rbd_id": "nope"}).status_code == 404
