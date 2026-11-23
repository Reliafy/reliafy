"""Open in › (Hours, Spares and Cost forecast) inside an asset opened with ?root=: one isolation
check for every forecast (Maintenance.forecast_within), with "inside" as the Explorer shows it.

The bug it guards: the forecasts walked a position's PART_OF parents only, so with a place opened
(a location root) every task was refused, and a position carried by a fitted item was refused
under the position its item is fitted to. Each case below is a row the Explorer shows.
"""

import pytest

from backend.maintenance import forecast_details as fd
from backend.maintenance import forecast_lines as fl
from backend.maintenance import position_forecast as pf
from backend.maintenance import spares_year as sy
from backend.maintenance.service import Invalid
from backend.tests.test_maintenance_forecast_engine import _m

ORG = "org-forecast-isolation"
REFUSED = "isn't inside the asset opened. Open the Explorer on the whole register to forecast it."


def _no_fetch(*_a, **_k):
    return None


@pytest.fixture
def site():
    """House › Kitchen › Dishwasher, House › Bathroom › Extractor fan; the kitchen's positions at the
    place Kitchen (a room), the bathroom's at Bathroom; a truck whose fitted engine carries a turbo
    position; another house outside everything."""
    m = _m(ORG)
    kitchen_room = m.create_location("Kitchen room")["id"]
    bathroom_room = m.create_location("Bathroom room")["id"]
    house = m.create_position("House")["id"]
    kitchen = m.create_position("Kitchen", parent_id=house, location_id=kitchen_room)["id"]
    dishwasher = m.create_position("Dishwasher", parent_id=kitchen)["id"]
    bathroom = m.create_position("Bathroom", parent_id=house, location_id=bathroom_room)["id"]
    fan = m.create_position("Extractor fan", parent_id=bathroom)["id"]
    truck = m.create_position("Haul truck")["id"]
    engine_bay = m.create_position("Engine", parent_id=truck)["id"]
    engine = m.fit(engine_bay, new_item={"name": "Engine 77"}, on="2026-01-05")["fitted"]["item"]["id"]
    turbo = m.create_position("Turbo", parent_id=engine)["id"]
    other = m.create_position("Other house")["id"]
    t = {
        "dishwasher": m.create_task(dishwasher, "Clean the filter", 1, "months")["id"],
        "kitchen": m.create_task(kitchen, "Check the sink trap", 3, "months")["id"],
        "fan": m.create_task(fan, "Clean the fan", 6, "months")["id"],
        "turbo": m.create_task(turbo, "Inspect the turbo", 3, "months")["id"],
        "other": m.create_task(other, "Not ours", 1, "months")["id"],
    }
    ids = dict(house=house, kitchen=kitchen, dishwasher=dishwasher, bathroom=bathroom, fan=fan, truck=truck,
               engine_bay=engine_bay, engine=engine, turbo=turbo, other=other, kitchen_room=kitchen_room,
               bathroom_room=bathroom_room)
    return m, ids, t


def _lines(m, kind, node, root):
    return fl.node_forecast(m, _no_fetch, kind, node, root, 12)


def _task_ids(out):
    return {x["id"] for x in out["tasks"]}


def test_a_task_row_in_a_place_opened(site):
    """The owner's case: Open in › on a task row in the Maintenance tab with a place opened."""
    m, n, t = site
    out = _lines(m, "task", t["dishwasher"], n["kitchen_room"])
    assert _task_ids(out) == {t["dishwasher"]}
    assert out["from"]["name"] == "Clean the filter"


def test_a_task_on_a_position_an_item_carries(site):
    """A position carried by a fitted item sits in the position the item is fitted to."""
    m, n, t = site
    for root in (n["truck"], n["engine_bay"]):
        assert _task_ids(_lines(m, "task", t["turbo"], root)) == {t["turbo"]}
    assert _task_ids(_lines(m, "position", n["turbo"], n["truck"])) == {t["turbo"]}


@pytest.mark.parametrize("node,root", [
    ("house", "house"),  # the node opened itself
    ("kitchen", "house"),  # a child
    ("dishwasher", "house"),  # deeper
    ("kitchen", "kitchen_room"),  # a place opened: its top position
    ("dishwasher", "kitchen_room"),  # and one inside it
])
def test_a_position_row(site, node, root):
    m, n, t = site
    out = _lines(m, "position", n[node], n[root])
    want = {"house": {t["dishwasher"], t["kitchen"], t["fan"]}, "kitchen": {t["dishwasher"], t["kitchen"]},
            "dishwasher": {t["dishwasher"]}}[node]
    assert _task_ids(out) == want


def test_a_row_above_the_place_opened_counts_only_whats_in_it(site):
    """A place opened by Positions shows the positions its positions sit in (House, muted): Open in ›
    there forecasts what's inside the place below it, never the bathroom's."""
    m, n, t = site
    out = _lines(m, "position", n["house"], n["kitchen_room"])
    assert _task_ids(out) == {t["dishwasher"], t["kitchen"]}
    assert {p["position"]["id"] for p in out["by_position"]} <= {n["house"], n["kitchen"], n["dishwasher"]}
    assert n["house"] not in {p["position"]["id"] for p in out["by_position"]}


def test_a_package_row(site):
    m, n, t = site
    pkg = m.create_package("Kitchen round", position_id=n["kitchen"], tasks=[t["dishwasher"], t["kitchen"]])["id"]
    for root in (n["house"], n["kitchen"], n["kitchen_room"], None):
        assert _task_ids(_lines(m, "package", pkg, root)) == {t["dishwasher"], t["kitchen"]}
    # A package across the house, opened from a room: only what's in the room counts.
    sink = m.create_task(n["kitchen"], "Descale the tap", 6, "months")["id"]
    both = m.create_package("House round", position_id=n["house"], tasks=[sink, t["fan"]])["id"]
    assert _task_ids(_lines(m, "package", both, n["kitchen_room"])) == {sink}
    assert _task_ids(_lines(m, "package", both, n["house"])) == {sink, t["fan"]}


def test_outside_the_asset_is_refused_saying_what_to_do(site):
    m, n, t = site
    for kind, node, root in [("position", n["other"], n["house"]), ("task", t["other"], n["house"]),
                             ("task", t["fan"], n["kitchen_room"]), ("position", n["turbo"], n["house"])]:
        with pytest.raises(Invalid, match=REFUSED):
            _lines(m, kind, node, root)
    # The same one check in every forecast that takes the asset opened.
    with pytest.raises(Invalid, match=REFUSED):
        pf.position_forecast(m, n["other"], root=n["house"])
    with pytest.raises(Invalid, match=REFUSED):
        fd.forecast_details(m, n["other"], root=n["house"], basis="calendar")
    with pytest.raises(Invalid, match=REFUSED):
        sy._scope(m, {"position_id": n["other"], "root": n["house"]})


def test_every_forecast_takes_a_place_opened(site):
    m, n, t = site
    out = pf.position_forecast(m, n["kitchen"], root=n["kitchen_room"])
    assert _task_ids(out) == {t["dishwasher"], t["kitchen"]}
    out = fd.forecast_details(m, n["house"], root=n["kitchen_room"], basis="calendar")
    assert {x["id"] for x in out["tasks"]} == {t["dishwasher"], t["kitchen"]}
    kind, _what, nodes = sy._scope(m, {"position_id": n["house"], "root": n["kitchen_room"]})
    assert kind == "position" and {p["id"] for p in nodes} == {n["kitchen"], n["dishwasher"]}
    kind, _what, nodes = sy._scope(m, {"position_id": n["engine_bay"], "root": n["truck"]})
    assert {p["id"] for p in nodes} == {n["engine_bay"]}
