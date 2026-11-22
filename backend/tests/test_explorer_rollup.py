"""The Explorer aggregates downwards: the Condition monitoring tab on a node with positions
below it (class_fleet.below) and the Summary's roll-up counts (rollup.rollup), on a tree of
several levels, cut to the asset opened."""

import pytest

from backend.maintenance import class_fleet, rollup
from backend.maintenance.service import Invalid, NotFound
from backend.tests.test_class_fleet import OWNERS, _classes, _day, _link, _pump, _readings, client, db, m  # noqa: F401


def _tree(m, db):
    """A site (a place) with a station, two trains inside it and pumps in the trains; one pump
    on the station itself; another station elsewhere."""
    _, pump, cent = _classes(m)
    load = m.create_condition("Load", kind="value")["id"]
    site = m.create_location("North site")["id"]
    station = m.create_position("Station", location_id=site)["id"]
    train_a = m.create_position("Train A", parent_id=station)["id"]
    train_b = m.create_position("Train B", parent_id=station)["id"]
    own, _ = _pump(m, "Station pump", cent, age=60, parent=station)
    ids = {}
    for name, parent, age, slope, heavy in (("Pump A1", train_a, 100, 0.02, 0), ("Pump B1", train_b, 150, 0.035, 1)):
        ids[name], _ = _pump(m, name, cent, age=age, parent=parent)
        _readings(m, ids[name], age, slope)
        m.apply_condition(ids[name], load, value=heavy)
        _link(m, db, ids[name])
    # Readings but no model: listed, with a dash. No monitoring at all: left out.
    ids["Pump B2"], _ = _pump(m, "Pump B2", pump, age=30, parent=train_b)
    _readings(m, ids["Pump B2"], 30)
    ids["Pump B3"], _ = _pump(m, "Pump B3", pump, age=30, parent=train_b)
    other = m.create_position("South station")["id"]
    south, _ = _pump(m, "South pump", cent, age=90, parent=other)
    _readings(m, south, 90)
    return {"site": site, "station": station, "a": train_a, "b": train_b, "own": own, "other": other,
            "south": south, **ids}


def test_condition_below_lists_every_monitored_position_beneath_with_where_it_lives(m, db):
    t = _tree(m, db)
    before = m.s.snapshot()
    out = class_fleet.below(m, db, OWNERS, set(), t["station"])
    assert m.s.snapshot() == before  # a read
    names = [r["position"]["name"] for r in out["members"]]
    # Monitored ones only (B3 has nothing), the highest risk first, the one without a model after.
    assert names == ["Pump B1", "Pump A1", "Pump B2"]
    assert (out["positions"], out["scored"], out["no_model"], out["below"]) == (3, 2, 1, 7)
    b1 = out["members"][0]
    assert b1["subject"] == {"id": t["Pump B1"], "name": "Pump B1", "within": "Station › Train B"}
    assert b1["here"] is False and b1["median_lower"] is not None and b1["median_lower"] <= b1["median_remaining"]
    # Never a total: each row's own chances.
    assert "total" not in out and len(b1["risk"]) == len(out["horizons"]["labels"])
    # A train: only its own branch.
    assert [r["position"]["name"] for r in class_fleet.below(m, db, OWNERS, set(), t["a"])["members"]] == ["Pump A1"]


def test_the_nodes_own_position_comes_first(m, db):
    t = _tree(m, db)
    out = class_fleet.below(m, db, OWNERS, set(), t["b"])
    assert [r["position"]["name"] for r in out["members"]] == ["Pump B1", "Pump B2"]
    # A pump with monitoring of its own, with a child that has some: itself first though less at risk.
    kid, _ = _pump(m, "Seal pot", None, age=40, parent=t["Pump A1"])
    _readings(m, kid, 40)
    mine = class_fleet.below(m, db, OWNERS, set(), t["Pump A1"])
    assert [r["position"]["name"] for r in mine["members"]] == ["Pump A1", "Seal pot"]
    assert mine["members"][0]["here"] is True and mine["members"][0]["subject"]["id"] == t["Pump A1"]


def test_a_place_and_the_asset_opened(m, db):
    t = _tree(m, db)
    at_site = class_fleet.below(m, db, OWNERS, set(), t["site"])
    assert sorted(r["position"]["name"] for r in at_site["members"]) == ["Pump A1", "Pump B1", "Pump B2"]
    assert at_site["node"]["kind"] == "location"
    # Opened on one asset (?root=): only that asset's positions.
    assert [r["position"]["name"] for r in class_fleet.below(m, db, OWNERS, set(), t["site"], within=t["a"])["members"]] == ["Pump A1"]
    with pytest.raises(Invalid):
        class_fleet.below(m, db, OWNERS, set(), t["other"], within=t["station"])
    with pytest.raises(NotFound):
        class_fleet.below(m, db, OWNERS, set(), "nope")


def test_rollup_counts_everything_beneath_at_every_depth(m, db):
    t = _tree(m, db)
    m.create_task(t["station"], "Walk round", 7, unit="days")
    m.create_task(t["Pump B1"], "Grease", 30, unit="days")
    m.create_task(t["Pump B2"], "Inspect", 90, unit="days")
    m.add_failure_mode(t["Pump B1"], "Bearing worn")
    m.add_failure_mode(t["Pump B1"], "Seal leaking")
    m.add_failure_mode(t["station"], "Power lost")
    m.file_failure_report(t["Pump A1"], "Seal leak", occurred_on=_day(m, 5))
    out = rollup.rollup(m, t["station"])
    assert out["node"] == {"id": t["station"], "kind": "position", "name": "Station"}
    # Below it: two trains, its own pump and four in the trains.
    assert out["inside"]["positions"] == 7
    assert out["inside"]["items"] == 5 and out["here"]["items"] == 0
    assert (out["here"]["tasks"], out["inside"]["tasks"]) == (1, 2)
    assert (out["here"]["models"], out["inside"]["models"]) == (0, 2)
    assert (out["here"]["failure_modes"], out["inside"]["failure_modes"]) == (1, 2)
    assert (out["inside"]["failure_reports"], out["inside"]["open_reports"]) == (1, 1)
    # A train: only its own branch; another asset never counts.
    b = rollup.rollup(m, t["b"])
    assert (b["inside"]["positions"], b["inside"]["tasks"], b["inside"]["models"]) == (3, 2, 1)
    site = rollup.rollup(m, t["site"])
    assert site["inside"]["positions"] == 8 and site["here"]["positions"] == 0 and site["inside"]["tasks"] == 3
    assert rollup.rollup(m, t["site"], within=t["a"])["inside"]["positions"] == 2


def test_both_over_rest(client):  # noqa: F811
    post = lambda path, body: client.post(f"/api/maintenance{path}", json=body).json()  # noqa: E731
    top = post("/positions", {"name": "Plant"})["id"]
    kid = post("/positions", {"name": "Pump", "parent_id": top})["id"]
    post(f"/positions/{kid}/fit", {"new_item": {"name": "Unit"}})
    post(f"/positions/{kid}/points", {"name": "Vibration", "kind": "condition", "unit": "mm/s"})
    r = client.get(f"/api/maintenance/condition-below/{top}")
    assert r.status_code == 200, r.text
    assert [x["subject"]["name"] for x in r.json()["members"]] == ["Pump"]
    out = client.get(f"/api/maintenance/rollup/{top}", params={"within": top}).json()
    assert out["inside"]["positions"] == 1 and out["inside"]["items"] == 1
    assert client.get("/api/maintenance/rollup/nope").status_code == 404
    assert client.get("/api/maintenance/condition-below/nope").status_code == 404
