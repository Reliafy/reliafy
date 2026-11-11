"""An item class's fleet (class_fleet.py, the Explorer arranged by Classes): the
positions whose fitted item is of the class or a class inside it, each scored with the
condition and life model linked to its own position, from that position's own data; a
member that can't be scored says why; nothing here writes to the graph."""

from datetime import date, timedelta

import mongomock
import pytest

from backend import joint
from backend.maintenance import class_fleet
from backend.maintenance import position_models as pm
from backend.maintenance.service import PROJECTORS, Invalid, Maintenance, NotFound
from backend.maintenance.store import GraphStore
from backend.services import joint as joint_service

ORG = "org-fleet"
OWNERS = [ORG, "__samples__"]
JOINT = "sample-joint-feed-pumps"  # ages in days, vibration in mm/s, one covariate: load


@pytest.fixture()
def m():
    return Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")


@pytest.fixture()
def db():
    from backend.services import samples

    d = mongomock.MongoClient()["class_fleet"]
    samples.seed_samples(d)
    return d


def _same_after_rebuild(m):
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before


def _classes(m):
    rot = m.create_item_class("Rotating equipment")["id"]
    pump = m.create_item_class("Pump", parent_id=rot)["id"]
    cent = m.create_item_class("Centrifugal pump", parent_id=pump)["id"]
    return rot, pump, cent


def _day(m, ago: int) -> str:
    return (date.fromisoformat(m.today()) - timedelta(days=ago)).isoformat()


def _pump(m, name, item_class=None, age=100, duty="Feed pump", in_service=True, parent=None):
    """A position with an item fitted ``age`` days ago, of the item class given."""
    pid = m.create_position(name, tag=name.upper().replace(" ", "-"), parent_id=parent, position_class=duty)["id"]
    new = {"name": f"{name} unit", "serial": f"S-{name[-1]}"}
    if in_service:
        new["in_service_date"] = _day(m, age)
    item = m.fit(pid, new_item=new, on=_day(m, age))["fitted"]["item"]["id"]
    if item_class:
        m.assign_item_class(item, item_class)
    return pid, item


def _readings(m, pid, age, slope=0.02, unit="mm/s", every=10, name="Vibration"):
    point = m.add_point(pid, name, kind="condition", unit=unit)["id"]
    for d in range(0, age + 1, every):
        m.record_reading(point, round(2 + slope * d, 2), on=_day(m, age - d))
    return point


def _link(m, db, pid, model_id=JOINT):
    return pm.link_saved(m, db, OWNERS, set(), pid, "model", model_id, None)


def _fleet(m, db, class_id, position_id=None):
    return class_fleet.fleet(m, db, OWNERS, set(), class_id, position_id)


def _by_name(out):
    return {r["position"]["name"]: r for r in out["members"]}


# ---- who is in a class's fleet ---------------------------------------------------------------------------------------------

def test_members_are_the_positions_whose_item_is_of_the_class_or_inside_it(m, db):
    rot, pump, cent = _classes(m)
    valve = m.create_item_class("Valve")["id"]
    a, a_item = _pump(m, "Pump A", cent, age=300)
    b, _ = _pump(m, "Pump B", pump, age=40, duty="Transfer pump")
    _pump(m, "Valve V", valve)
    _pump(m, "Meter X")  # an item with no class
    m.create_position("Spare bay")  # nothing fitted
    part = m.create_part("Close-coupled pump", "CC-50")["id"]
    m.assign_item_class(part, cent)
    c = m.create_position("Pump C", position_class="Feed pump")["id"]
    m.fit(c, new_item={"name": "From the catalogue", "part_id": part}, on=_day(m, 10))

    out = _fleet(m, db, pump)
    assert out["item_class"]["name"] == "Pump" and out["today"] == m.today() and out["age_unit"] == "Days"
    assert out["horizons"] == {"labels": ["30 days", "90 days", "365 days"], "values": [30.0, 90.0, 365.0]}
    assert [r["position"]["name"] for r in out["members"]] == ["Pump A", "Pump B", "Pump C"] and out["positions"] == 3
    rows = _by_name(out)
    assert rows["Pump A"]["position"] == {"id": a, "name": "Pump A", "tag": "PUMP-A", "position_class": "Feed pump"}
    assert rows["Pump A"]["item"] == {"id": a_item, "name": "Pump A unit", "serial": "S-A"}
    assert rows["Pump A"]["age"] == 300.0 and rows["Pump A"]["in_service"] == _day(m, 300)
    assert rows["Pump A"]["item_class"]["name"] == "Centrifugal pump" and rows["Pump B"]["item_class"]["name"] == "Pump"
    # An item takes its catalogue part's class.
    assert rows["Pump C"]["item_class"]["name"] == "Centrifugal pump" and rows["Pump C"]["age"] == 10.0
    assert out["position_classes"] == ["Feed pump", "Transfer pump"]
    # The class above takes in everything inside it; a class on its own branch only its own.
    assert [r["position"]["name"] for r in _fleet(m, db, rot)["members"]] == ["Pump A", "Pump B", "Pump C"]
    assert [r["position"]["name"] for r in _fleet(m, db, cent)["members"]] == ["Pump A", "Pump C"]
    assert [r["position"]["name"] for r in _fleet(m, db, valve)["members"]] == ["Valve V"]
    # No model anywhere: a dash for each (no risk keys, no reason) and one note saying how to get risk.
    assert all(r["model"] is None and not r["scored"] and r["why"] is None and "risk" not in r for r in out["members"])
    assert (out["scored"], out["no_model"], out["not_scored"], out["models"]) == (0, 3, 0, [])
    assert out["note"].startswith("None of these positions has a condition and life model") and "Modelling" in out["note"]
    with pytest.raises(NotFound):
        _fleet(m, db, "no-such-class")
    _same_after_rebuild(m)


def test_one_assets_fleet_has_only_what_is_inside_that_asset(m, db):
    """Two assets with items of one class: with ``within`` (an asset's top position) the
    members, counts, duties, models and notes are that asset's alone; a position its fitted
    item carries is inside it, as the tree nests it; with no ``within``, every asset."""
    _, pump, cent = _classes(m)
    valve = m.create_item_class("Valve")["id"]
    site = m.create_location("North site")["id"]
    yard = m.create_location("North yard", parent_id=site)["id"]
    north = m.create_position("North station", location_id=yard)["id"]
    south = m.create_position("South station")["id"]
    n1, n1_item = _pump(m, "North pump 1", cent, parent=north)
    n2, _ = _pump(m, "North pump 2", pump, duty="Transfer pump", parent=north)
    # A position North pump 1's item carries (its booster), with an item of the class fitted.
    nb = m.create_position("North booster", parent_id=n1_item, position_class="Booster")["id"]
    booster = m.fit(nb, new_item={"name": "Booster unit"}, on=_day(m, 20))["fitted"]["item"]["id"]
    m.assign_item_class(booster, cent)
    s1, _ = _pump(m, "South pump 1", cent, duty="Ballast pump", parent=south)
    _pump(m, "South valve", valve, parent=south)
    _link(m, db, s1)

    everything = _fleet(m, db, pump)
    assert sorted(r["position"]["name"] for r in everything["members"]) == [
        "North booster", "North pump 1", "North pump 2", "South pump 1"]
    assert (everything["positions"], everything["no_model"]) == (4, 3)

    mine = class_fleet.fleet(m, db, OWNERS, set(), pump, within=north)
    assert [r["position"]["id"] for r in mine["members"]] == [nb, n1, n2]
    assert mine["positions"] == 3 and (mine["scored"], mine["no_model"], mine["not_scored"]) == (0, 3, 0)
    assert mine["models"] == [] and mine["position_classes"] == ["Booster", "Feed pump", "Transfer pump"]
    assert mine["note"].startswith("None of these positions has a condition and life model")
    assert not any("South" in r["position"]["name"] for r in mine["members"])
    # South alone: its one pump, its model; the valve isn't of the class.
    theirs = class_fleet.fleet(m, db, OWNERS, set(), pump, within=south)
    assert [r["position"]["id"] for r in theirs["members"]] == [s1]
    assert theirs["positions"] == 1 and theirs["no_model"] == 0 and [x["id"] for x in theirs["models"]] == [JOINT]
    assert theirs["position_classes"] == ["Ballast pump"]
    # A class used only in the other asset: nothing here.
    assert class_fleet.fleet(m, db, OWNERS, set(), valve, within=north)["positions"] == 0
    assert class_fleet.fleet(m, db, OWNERS, set(), valve, within=south)["positions"] == 1
    # One member, inside the asset or not.
    assert class_fleet.fleet(m, db, OWNERS, set(), pump, position_id=n1, within=north)["member"]["position"]["id"] == n1
    with pytest.raises(Invalid, match="inside that tree"):
        class_fleet.fleet(m, db, OWNERS, set(), pump, position_id=s1, within=north)
    with pytest.raises(NotFound):
        class_fleet.fleet(m, db, OWNERS, set(), pump, within="no-such-position")
    # The same "inside" as the tree read: every position the tree nests under the asset.
    rows = {r["id"]: r for r in m.tree_rows()["positions"]}

    def under(top):
        return {pid for pid in rows if pid == top or _up_to(rows, pid, top)}

    assert m.positions_inside(north) == under(north) == {north, n1, n2, nb}
    assert m.positions_inside(south) == under(south)
    # A place: every position there or at a place inside it (set or inherited), the same members.
    assert m.positions_inside(site) == m.positions_inside(yard) == {north, n1, n2, nb}
    at_site = class_fleet.fleet(m, db, OWNERS, set(), pump, within=site)
    assert sorted(r["position"]["id"] for r in at_site["members"]) == sorted([nb, n1, n2])
    # The carrying item moves to South: its booster goes with it.
    m.move_item(n1_item, south)
    assert nb in m.positions_inside(south) and nb not in m.positions_inside(north)
    assert nb not in m.positions_inside(site)
    _same_after_rebuild(m)


def _up_to(rows, pid, top):
    seen = set()
    while pid is not None and pid not in seen:
        seen.add(pid)
        pid = rows[pid].get("parent_id")
        if pid == top:
            return True
    return False


def test_tree_rows_say_each_position_item_class(m):
    _, pump, cent = _classes(m)
    a, _ = _pump(m, "Pump A", cent)
    b, _ = _pump(m, "Meter X")
    e = m.create_position("Spare bay")["id"]
    rows = {r["id"]: r for r in m.tree_rows()["positions"]}
    assert rows[a]["item_class_id"] == cent
    assert "item_class_id" not in rows[b] and "item_class_id" not in rows[e]
    _same_after_rebuild(m)


# ---- one position on its own -----------------------------------------------------------------------------------------------

def test_one_position_whatever_its_item_class(m, db):
    """The Condition monitoring tab on a position: the member row a class's fleet gives, with its
    curves, for an item with a class, an item with none, and no item at all."""
    _, pump, cent = _classes(m)
    load = m.create_condition("Load", kind="value")["id"]
    a, _ = _pump(m, "Pump A", cent, age=100)
    b, b_item = _pump(m, "Pump B", age=80)  # an item with no class
    for pid, age in ((a, 100), (b, 80)):
        _readings(m, pid, age)
        m.apply_condition(pid, load, value=1)
        _link(m, db, pid)
    c, _ = _pump(m, "Pump C", cent, age=30)  # no model
    d, _ = _pump(m, "Pump D", age=30)  # a model, no readings
    _link(m, db, d)
    empty = m.create_position("Spare bay", tag="SB-1", position_class="Feed pump")["id"]
    before = m.s.snapshot()

    def one(pid):
        return class_fleet.position(m, db, OWNERS, set(), pid)

    # With a class: the row and curves the class's own read gives for that member.
    got, want = one(a), _fleet(m, db, pump, a)
    assert got["member"] == want["member"] and got["model"] == want["model"]
    assert got["item_class"]["name"] == "Centrifugal pump" and got["why"] is None
    assert got["position"] == {"id": a, "name": "Pump A", "tag": "PUMP-A", "position_class": "Feed pump"}
    assert (got["today"], got["age_unit"], got["horizons"]) == (want["today"], want["age_unit"], want["horizons"])
    # An item with no class is scored the same way: the class was never part of the sums.
    got = one(b)
    row = got["member"]
    assert got["item_class"] is None and row["item_class"] is None and row["item"]["id"] == b_item
    assert row["scored"] and len(row["risk"]) == 3 and all(0.0 <= x <= 1.0 for x in row["risk"])
    assert row["unit"]["unit_id"] == "Pump B" and row["unit"]["age"] == 80.0 and row["unit"]["prediction"]
    assert got["model"]["id"] == JOINT
    # No model: the row with its facts and no risk; the page says how to link one.
    got = one(c)
    assert got["model"] is None and got["member"]["model"] is None and not got["member"]["scored"]
    assert got["member"]["why"] is None and got["member"]["age"] == 30.0 and "unit" not in got["member"]
    # A model that can't score it yet: the reason, in words.
    got = one(d)
    assert got["model"]["id"] == JOINT and not got["member"]["scored"] and "unit" not in got["member"]
    assert got["member"]["why"].startswith("No measurement point for")
    # Nothing fitted: no member, and why.
    got = one(empty)
    assert got["member"] is None and got["model"] is None and got["item_class"] is None
    assert got["why"].startswith("No item is fitted here") and got["position"]["tag"] == "SB-1"
    with pytest.raises(NotFound):
        one("no-such-position")
    assert m.s.snapshot() == before  # a read
    _same_after_rebuild(m)


# ---- risk now, member by member ----------------------------------------------------------------------------------------

def test_each_member_is_scored_with_its_own_position_model(m, db):
    _, pump, cent = _classes(m)
    load = m.create_condition("Load", kind="value")["id"]
    spec = {"Pump A": (100, 0.02, 0), "Pump B": (150, 0.035, 1), "Pump C": (60, 0.015, 0)}
    ids = {}
    for name, (age, slope, heavy) in spec.items():
        ids[name], _ = _pump(m, name, cent, age=age)
        _readings(m, ids[name], age, slope)
        m.apply_condition(ids[name], load, value=heavy)
        _link(m, db, ids[name])
    plain, _ = _pump(m, "Pump D", pump, age=20)  # no model: listed, with a dash
    before = m.s.snapshot()

    out = _fleet(m, db, pump)
    assert m.s.snapshot() == before  # a read
    assert (out["positions"], out["scored"], out["no_model"], out["not_scored"]) == (4, 3, 1, 0)
    assert out["note"].startswith("1 of these positions has no condition and life model")
    assert [x["id"] for x in out["models"]] == [JOINT] and out["models"][0]["positions"] == 3
    assert out["models"][0]["path"] == f"/models/joint/{JOINT}" and out["models"][0]["marker_unit"] == "mm/s"
    scored = [r for r in out["members"] if r["scored"]]
    # Highest chance of failing in the next 90 days first; the one with no model last.
    assert [r["risk"][1] for r in scored] == sorted((r["risk"][1] for r in scored), reverse=True)
    assert out["members"][-1]["position"]["id"] == plain and out["members"][-1]["model"] is None
    assert scored[0]["position"]["name"] == "Pump B"  # the oldest, steepest and most loaded

    # The numbers are the model's own: the same prediction asked of it directly.
    live = joint_service.live(pm.fetcher(db, OWNERS, set())("model", JOINT))
    rows = _by_name(out)
    for name, (age, slope, heavy) in spec.items():
        r = rows[name]
        markers = [[float(d), round(2 + slope * d, 2)] for d in range(0, age + 1, 10)]
        want = joint.risk_row(joint.predict(live, {"load": float(heavy)}, markers, float(age)), [30.0, 90.0, 365.0])
        assert r["risk"] == pytest.approx(want["risk"]) and r["survival"] == pytest.approx(want["survival"])
        assert r["median_remaining"] == pytest.approx(want["median_remaining"], rel=1e-5)
        assert all(0.0 <= x <= 1.0 for x in r["risk"]) and r["risk"] == sorted(r["risk"])
        assert r["covariates"] == {"load": float(heavy)} and r["n_readings"] == len(markers) and r["why"] is None
        assert r["last_reading"] == {"on": _day(m, age % 10), "value": markers[-1][1], "unit": "mm/s"}
        assert r["point"]["name"] == "Vibration" and r["point"]["on"] == "position"
        assert r["model"] == {"id": JOINT, "name": rows[name]["model"]["name"]}


def test_one_member_with_its_curves(m, db):
    _, pump, cent = _classes(m)
    load = m.create_condition("Load", kind="value")["id"]
    a, _ = _pump(m, "Pump A", cent, age=100)
    _readings(m, a, 100)
    m.apply_condition(a, load, value=1)
    _link(m, db, a)
    other, _ = _pump(m, "Valve V", m.create_item_class("Valve")["id"])

    one = _fleet(m, db, pump, a)
    assert "members" not in one and one["model"]["id"] == JOINT and one["model"]["unit"] == "Days"
    row = one["member"]
    assert row["scored"] and row["risk"] == pytest.approx(_by_name(_fleet(m, db, pump))["Pump A"]["risk"])
    unit = row["unit"]
    assert unit["unit_id"] == "Pump A" and unit["source"] == "position" and unit["age"] == 100.0
    assert unit["horizons"]["labels"] == ["30 days", "90 days", "365 days"]
    assert unit["prediction"] and len(unit["markers"]) == 11 and unit["marker_now"] is not None
    with pytest.raises(Invalid, match="no item of the class Pump"):
        _fleet(m, db, pump, other)


def test_a_model_in_weeks_is_read_in_days(m, db):
    """The table is in days whatever the model's own unit: ages and horizons go to the
    model in its unit, and the life left comes back in days."""
    doc = db.models.find_one({"_id": JOINT})
    doc.update(_id="own-weeks", id="own-weeks", owner_id=ORG, name="Pumps by the week")
    doc["results"] = {**doc["results"], "unit": "Weeks"}
    db.models.insert_one(doc)
    _, _, cent = _classes(m)
    load = m.create_condition("Load", kind="value")["id"]
    a, _ = _pump(m, "Pump A", cent, age=350)
    _readings(m, a, 350, slope=0.002, every=70)
    m.apply_condition(a, load, value=0)
    _link(m, db, a, "own-weeks")

    row = _fleet(m, db, cent)["members"][0]
    live = joint_service.live(pm.fetcher(db, OWNERS, set())("model", "own-weeks"))
    markers = [[d / 7, round(2 + 0.002 * d, 2)] for d in range(0, 351, 70)]
    want = joint.risk_row(joint.predict(live, {"load": 0.0}, markers, 50.0), [30 / 7, 90 / 7, 365 / 7])
    assert row["scored"] and row["age"] == 350.0 and row["risk"] == pytest.approx(want["risk"])
    assert row["median_remaining"] == pytest.approx(want["median_remaining"] * 7, rel=1e-5)
    # The member's own charts stay in the model's unit.
    assert _fleet(m, db, cent, a)["member"]["unit"]["age"] == pytest.approx(50.0)


def test_a_position_with_no_link_uses_its_position_class_model(m, db):
    """A position class's fitted model reaches every position of that duty; a model
    linked to the position itself comes first."""
    from backend.maintenance.service import class_id

    doc = db.models.find_one({"_id": JOINT})
    doc.update(_id="own-pumps", id="own-pumps", owner_id=ORG, name="Our pumps")
    db.models.insert_one(doc)
    _, _, cent = _classes(m)
    load = m.create_condition("Load", kind="value")["id"]
    a, _ = _pump(m, "Pump A", cent, duty="Feed pump")
    b, _ = _pump(m, "Pump B", cent, duty="Feed pump")
    c, _ = _pump(m, "Pump C", cent, duty="Transfer pump")
    for pid in (a, b, c):
        _readings(m, pid, 100)
        m.apply_condition(pid, load, value=0)
    m._emit("class.model_fitted", {
        "id": class_id(m.org, "Feed pump"), "name": "Feed pump", "model_id": JOINT, "distribution": "joint",
        "params": [], "extras": None, "unit": "days", "fitted_on": m.today(), "failures": 12, "suspensions": 3})
    _link(m, db, b, "own-pumps")

    rows = _by_name(_fleet(m, db, cent))
    assert rows["Pump A"]["scored"] and rows["Pump A"]["model"]["id"] == JOINT
    assert rows["Pump B"]["scored"] and rows["Pump B"]["model"] == {"id": "own-pumps", "name": "Our pumps"}
    assert rows["Pump C"]["model"] is None and not rows["Pump C"]["scored"]
    _same_after_rebuild(m)


# ---- a member that can't be scored says why ----------------------------------------------------------------------------

def test_a_member_that_cannot_be_scored_says_why_and_what_to_do(m, db):
    _, _, cent = _classes(m)
    load = m.create_condition("Load", kind="value")["id"]

    def member(name, **kw):
        pid, item = _pump(m, name, cent, **kw)
        _link(m, db, pid)
        return pid, item

    no_point, _ = member("Pump A")
    m.apply_condition(no_point, load, value=0)
    no_readings, _ = member("Pump B")
    m.add_point(no_readings, "Vibration", kind="condition", unit="mm/s")
    wrong_unit, _ = member("Pump C")
    _readings(m, wrong_unit, 100, unit="in/s")
    no_load, _ = member("Pump D")
    _readings(m, no_load, 100)
    two, _ = member("Pump E")
    _readings(m, two, 100, name="Drive end")
    _readings(m, two, 100, name="Non-drive end")
    m.apply_condition(two, load, value=0)
    # Readings taken on the position before this item went in were another item's.
    earlier = m.create_position("Pump F", position_class="Feed pump")["id"]
    m.fit(earlier, new_item={"name": "Old unit"}, on=_day(m, 400))
    point = m.add_point(earlier, "Vibration", kind="condition", unit="mm/s")["id"]
    m.record_reading(point, 3.1, on=_day(m, 300))
    m.remove(earlier, on=_day(m, 200), reason="failure")
    item = m.fit(earlier, new_item={"name": "New unit"}, on=_day(m, 50))["fitted"]["item"]["id"]
    m.assign_item_class(item, cent)
    m.apply_condition(earlier, load, value=0)
    _link(m, db, earlier)

    out = _fleet(m, db, cent)
    rows = _by_name(out)
    assert (out["scored"], out["no_model"], out["not_scored"], out["note"]) == (0, 0, 6, None)
    for r in out["members"]:
        assert not r["scored"] and r["model"]["id"] == JOINT and r["why"]
        assert not {"risk", "survival", "median_remaining", "unit"} & set(r)  # never a made-up number
    assert rows["Pump A"]["why"].startswith("No measurement point for vibration (mm/s)") and rows["Pump A"]["point"] is None
    assert rows["Pump B"]["why"].startswith("No vibration readings since this item went into service")
    assert "Record one on “Vibration”" in rows["Pump B"]["why"] and rows["Pump B"]["last_reading"] is None
    assert rows["Pump C"]["why"].startswith("Units don't match: the model reads vibration in mm/s")
    assert "Vibration in in/s" in rows["Pump C"]["why"] and rows["Pump C"]["point"] is None
    assert rows["Pump D"]["why"].startswith("No value for load.") and "value condition" in rows["Pump D"]["why"]
    assert rows["Pump D"]["last_reading"]["value"] == 4.0  # the reading still shows
    assert rows["Pump E"]["why"].startswith("More than one measurement point could be vibration (mm/s)")
    assert "Drive end" in rows["Pump E"]["why"] and "Non-drive end" in rows["Pump E"]["why"]
    assert rows["Pump F"]["age"] == 50.0 and rows["Pump F"]["n_readings"] == 0
    assert rows["Pump F"]["why"].startswith("No vibration readings since this item went into service")
    # The one member alone says the same, with no curves.
    one = _fleet(m, db, cent, no_load)["member"]
    assert one["why"] == rows["Pump D"]["why"] and "unit" not in one

    # Naming one of the two points after the reading settles which to use.
    m.add_point(two, "Vibration overall", kind="condition", unit="mm/s")
    assert _by_name(_fleet(m, db, cent))["Pump E"]["why"].startswith("No vibration readings")


def test_a_model_in_running_hours_is_not_scored_against_the_calendar(m, db):
    doc = db.models.find_one({"_id": JOINT})
    doc.update(_id="own-hours", id="own-hours", owner_id=ORG, name="Pumps by running hours")
    doc["results"] = {**doc["results"], "unit": "Hours"}
    db.models.insert_one(doc)
    _, _, cent = _classes(m)
    a, _ = _pump(m, "Pump A", cent)
    _readings(m, a, 100)
    _link(m, db, a, "own-hours")
    row = _fleet(m, db, cent)["members"][0]
    assert not row["scored"] and "risk" not in row
    assert row["why"].startswith("Units don't match: “Pumps by running hours” counts age in hours")
    assert "days, weeks, months or years" in row["why"]


def test_a_point_on_the_item_and_an_age_from_the_first_fitment(m, db):
    _, _, cent = _classes(m)
    load = m.create_condition("Load", kind="value")["id"]
    a, item = _pump(m, "Pump A", cent, age=80, in_service=False)
    point = m.add_point(None, "Vibration", kind="condition", unit="mm/s", item_id=item)["id"]
    for d in (0, 40, 80):
        m.record_reading(point, round(2 + 0.02 * d, 2), on=_day(m, 80 - d))
    m.apply_condition(a, load, value=0)
    _link(m, db, a)
    row = _fleet(m, db, cent)["members"][0]
    assert row["scored"] and row["age"] == 80.0 and row["in_service"] == _day(m, 80)
    assert row["point"]["on"] == "item" and row["n_readings"] == 3 and row["last_reading"]["value"] == 3.6


# ---- over REST -------------------------------------------------------------------------------------------------------------

@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config
    from backend import db as db_mod
    from backend.auth import get_current_user
    from backend.main import app
    from backend.routers import maintenance as router
    from backend.services import samples

    d = mongomock.MongoClient()["class_fleet_rest"]
    samples.seed_samples(d)
    monkeypatch.setattr(db_mod, "_db", d)
    monkeypatch.setattr(db_mod, "_simulated", True)
    monkeypatch.setattr(router, "_store", GraphStore(":memory:", PROJECTORS))
    monkeypatch.setattr(config, "MAINTENANCE_ENABLED", True)
    monkeypatch.setattr(config, "MAINTENANCE_EMAILS", {"a@x.com"})
    app.dependency_overrides[get_current_user] = lambda: {
        "uid": ORG, "email": "a@x.com", "name": "A", "email_verified": True}
    yield TestClient(app)
    app.dependency_overrides.pop(get_current_user, None)


def test_the_fleet_over_rest(client):
    post = lambda path, body: client.post(f"/api/maintenance{path}", json=body).json()  # noqa: E731
    today = date.fromisoformat(client.get("/api/maintenance/tree").json()["today"])
    since = (today - timedelta(days=90)).isoformat()
    pump = post("/item-classes", {"name": "Pump"})["id"]
    cent = post("/item-classes", {"name": "Centrifugal pump", "parent_id": pump})["id"]
    load = post("/conditions", {"name": "Load", "kind": "value"})["id"]
    a = post("/positions", {"name": "Pump A", "position_class": "Feed pump"})["id"]
    item = post(f"/positions/{a}/fit", {"new_item": {"name": "Unit", "in_service_date": since}, "on": since})
    post("/item-classes/assign", {"target_id": item["fitted"]["item"]["id"], "item_class_id": cent})
    point = post(f"/positions/{a}/points", {"name": "Vibration", "kind": "condition", "unit": "mm/s"})["id"]
    post(f"/points/{point}/readings", {"value": 2.1, "on": since})
    post(f"/points/{point}/readings", {"value": 3.7, "on": today.isoformat()})
    post(f"/conditions/of/{a}", {"condition_id": load, "value": 1})
    assert client.post(f"/api/maintenance/positions/{a}/models", json={"model_id": JOINT}).status_code == 200
    b = post("/positions", {"name": "Pump B"})["id"]
    other = post(f"/positions/{b}/fit", {"new_item": {"name": "Unclassed"}, "on": since})

    tree = {p["id"]: p for p in client.get("/api/maintenance/tree").json()["positions"]}
    assert tree[a]["item_class_id"] == cent and "item_class_id" not in tree[b]
    r = client.get(f"/api/maintenance/item-classes/{pump}/fleet")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["positions"] == 1 and out["scored"] == 1 and out["members"][0]["position"]["id"] == a
    assert len(out["members"][0]["risk"]) == 3 and out["members"][0]["median_remaining"] > 0
    one = client.get(f"/api/maintenance/item-classes/{pump}/fleet", params={"position_id": a}).json()
    assert one["member"]["unit"]["prediction"] and one["model"]["id"] == JOINT
    assert client.get("/api/maintenance/item-classes/nope/fleet").status_code == 404
    bad = client.get(f"/api/maintenance/item-classes/{pump}/fleet", params={"position_id": other["id"]})
    assert bad.status_code == 422 and "no item of the class Pump" in bad.json()["detail"]
    # One asset's tree (?within=, its top position): only the members inside it.
    assert client.get(f"/api/maintenance/item-classes/{pump}/fleet", params={"within": a}).json()["positions"] == 1
    assert client.get(f"/api/maintenance/item-classes/{pump}/fleet", params={"within": b}).json()["positions"] == 0
    assert client.get(f"/api/maintenance/item-classes/{pump}/fleet", params={"within": "nope"}).status_code == 404
    # One position on its own (its Condition monitoring tab), with a class or without one.
    mine = client.get(f"/api/maintenance/positions/{a}/condition")
    assert mine.status_code == 200, mine.text
    assert mine.json()["member"] == one["member"] and mine.json()["model"]["id"] == JOINT
    plain = client.get(f"/api/maintenance/positions/{b}/condition").json()
    assert plain["item_class"] is None and plain["model"] is None and plain["member"]["item"]["name"] == "Unclassed"
    assert client.get("/api/maintenance/positions/nope/condition").status_code == 404
