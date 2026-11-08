"""The LSA on a task (Nov 2026): what doing it needs, set by its own event
(task.resources_set) and read on the task as ``resources``; the rollups a
visit or a package needs; the MCP action (maintenance tasks.set_resources) and
the app's routes. The RCM says what and why; the LSA says how."""

import pytest

from backend.maintenance.service import PROJECTORS, Invalid, Maintenance
from backend.maintenance.store import GraphStore
from backend.tests.test_maintenance_mcp import _do, _list, _ok, _session, env  # noqa: F401
from backend.tests.test_maintenance_rcm_api import api  # noqa: F401

ORG = "user-a"
M = "/api/maintenance"


@pytest.fixture()
def m():
    return Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")


def _rebuilds_the_same(m):
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before


def _events(m, type):
    return [e for e in m.s.events(ORG, 1000) if e["type"] == type]


def _pool(m):
    pool = m.create_position("Pool")
    chlor = m.create_position("Chlorinator", parent_id=pool["id"])
    point = m.add_point(chlor["id"], "Free chlorine", kind="condition", unit="mg/L")
    cell = m.create_part("CELL-1", "Chlorinator cell", unit_cost=400)
    test = m.create_task(pool["id"], "Test the water", 1, "weeks", trade="Pool technician")
    clean = m.create_task(chlor["id"], "Clean the cell", 3, "months")
    return pool, chlor, point, cell, test, clean


def test_resources_are_set_projected_merged_and_cleared(m):
    pool, chlor, point, cell, test, clean = _pool(m)
    view = m.set_task_resources(test["id"], {
        "labour": [{"trade": "Pool technician", "people": 1, "hours": 0.5}],
        "tools": [{"name": "Photometer", "point_id": point["id"]}],
        "consumables": [{"name": "DPD tablets", "qty": 2, "unit": "each", "cost": 1.5}],
        "access": {"downtime_hours": 0, "permits": ["  "]},
        "method": "Home kit",
    })
    r = view["resources"]
    assert r["labour"] == [{"trade": "Pool technician", "people": 1, "hours": 0.5}]
    assert r["tools"][0]["point"] == {"id": point["id"], "name": "Free chlorine", "unit": "mg/L", "kind": "point"}
    assert r["method"] == "Home kit" and r["access"] == {"downtime_hours": 0}
    assert r["labour_hours"] == 0.5 and r["people"] == 1 and r["materials_cost"] == 1.5
    assert r["cost_estimate"] is None  # no trade rates kept: never invented
    # Another section only: the rest kept; the same again writes nothing.
    view = m.set_task_resources(test["id"], {"spares": [{"part_id": cell["id"], "qty": 1}], "duration_hours": 1})
    assert view["resources"]["method"] == "Home kit"
    assert view["resources"]["spares"] == [{"part_id": cell["id"], "name": "Chlorinator cell", "qty": 1,
                                            "part_number": "CELL-1", "unit_cost": 400}]
    assert view["resources"]["materials_cost"] == 401.5
    m.set_task_resources(test["id"], {"duration_hours": 1})
    assert len(_events(m, "task.resources_set")) == 2
    _rebuilds_the_same(m)
    # null clears a section; resources null clears the lot.
    assert m.set_task_resources(test["id"], {"method": None})["resources"]["method"] == ""
    cleared = m.set_task_resources(test["id"], None)["resources"]
    assert cleared["labour"] == [] and cleared["tools"] == [] and cleared["labour_hours"] == 0
    assert m.s.node(ORG, test["id"]).get("resources") is None
    _rebuilds_the_same(m)


@pytest.mark.parametrize("bad, words", [
    ({"crew": []}, "doesn't take crew"),
    ({"labour": {"trade": "x"}}, "must be a list"),
    ({"labour": [{"trade": "Fitter"}]}, "needs hours"),
    ({"labour": [{"trade": "Fitter", "people": 1.5, "hours": 1}]}, "whole number"),
    ({"tools": [{"qty": 1}]}, "tool's name is required"),
    ({"tools": [{"name": "Meter", "point_id": "nope"}]}, "live measuring point"),
    ({"spares": [{"qty": 1}]}, "required"),
    ({"consumables": [{"name": "Grease"}]}, "needs a qty"),
    ({"consumables": [{"name": "Grease", "qty": 1, "cost": -2}]}, "can't be negative"),
    ({"access": {"ladder": True}}, "doesn't take ladder"),
    ({"access": {"permits": "Hot work"}}, "permits must be a list"),
    ({"duration_hours": "soon"}, "must be a number"),
    ("all of it", "must be an object"),
])
def test_resources_are_checked(m, bad, words):
    _, _, _, _, test, _ = _pool(m)
    with pytest.raises(Invalid, match=words):
        m.set_task_resources(test["id"], bad)
    assert _events(m, "task.resources_set") == []


def test_a_missing_part_is_not_found_and_a_retired_task_refused(m):
    _, _, _, _, test, clean = _pool(m)
    with pytest.raises(Exception):
        m.set_task_resources(test["id"], {"spares": [{"part_id": "nope", "qty": 1}]})
    m.retire_task(clean["id"], "done with")
    with pytest.raises(Invalid, match="retired"):
        m.set_task_resources(clean["id"], {"method": "x"})


def test_rollup_adds_up_a_visit(m):
    pool, chlor, point, cell, test, clean = _pool(m)
    m.set_task_resources(test["id"], {"labour": [{"people": 1, "hours": 0.5}],  # no trade: the task's
                                      "tools": [{"name": "photometer", "qty": 1}],
                                      "consumables": [{"name": "DPD tablets", "qty": 2, "unit": "each", "cost": 1}],
                                      "access": {"permits": ["chemical handling"]}})
    m.set_task_resources(clean["id"], {"labour": [{"trade": "Pool technician", "people": 2, "hours": 1}],
                                       "tools": [{"name": "Photometer", "qty": 2}, {"name": "Brush"}],
                                       "spares": [{"part_id": cell["id"], "qty": 1}, {"name": "O-ring", "qty": 2}],
                                       "consumables": [{"name": "DPD tablets", "qty": 3, "unit": "each"},
                                                       {"name": "Acid", "qty": 1, "unit": "L"}],
                                       "access": {"permits": ["Chemical handling", "Isolation"]}})
    # Rows by position: the chlorinator's first, so its spelling of a shared line is kept.
    rows = m.task_table(position_id=pool["id"])["tasks"]
    out = m.lsa_rollup(rows)
    assert out["tasks"] == 2 and out["labour_hours"] == 2.5
    assert out["labour"] == [{"trade": "Pool technician", "hours": 2.5, "people": 2}]
    assert out["tools"] == [{"name": "Brush", "qty": None}, {"name": "Photometer", "qty": 2}]
    assert [(s["name"], s["qty"]) for s in out["spares"]] == [("Chlorinator cell", 1), ("O-ring", 2)]
    assert out["consumables"] == [{"name": "Acid", "unit": "L", "qty": 1, "cost": None},
                                  {"name": "DPD tablets", "unit": "each", "qty": 5, "cost": 1}]
    assert out["permits"] == ["Chemical handling", "Isolation"]
    # A package's read and the packages list carry the same rollup for its members.
    pkg = m.create_package("Pool weekly", position_id=pool["id"], every=1, unit="weeks", weekday="saturday",
                           tasks=[test["id"]])
    assert m.package(pkg["id"])["rollup"]["labour_hours"] == 0.5
    [listed] = m.packages()["packages"]
    assert listed["rollup"]["tools"] == [{"name": "photometer", "qty": 1}]


def test_task_table_and_lsa_page_carry_the_record(m):
    pool, chlor, point, cell, test, clean = _pool(m)
    m.add_position_part(chlor["id"], cell["id"], role="component")
    m.set_task_resources(clean["id"], {"labour": [{"trade": "Fitter", "people": 1, "hours": 2}]})
    row = next(r for r in m.task_table(position_id=pool["id"])["tasks"] if r["id"] == clean["id"])
    assert row["resources"]["labour_hours"] == 2
    page = m.task_lsa(test["id"])  # on the pool: the points and parts inside it too
    assert page["task"]["id"] == test["id"]
    assert [p["name"] for p in page["points"]] == ["Free chlorine"]
    assert [p["part_number"] for p in page["parts"]] == ["CELL-1"]


def test_a_copied_position_copies_the_record_less_its_points(m):
    pool, chlor, point, cell, test, clean = _pool(m)
    m.set_task_resources(clean["id"], {"tools": [{"name": "Photometer", "point_id": point["id"]}],
                                       "method": "Shop sample"})
    copy = m.copy_position(chlor["id"], "Chlorinator 2", parent_id=pool["id"])
    [task] = [t for t in m.position(copy["id"])["tasks"]]
    assert task["resources"]["method"] == "Shop sample"
    assert task["resources"]["tools"] == [{"name": "Photometer"}]
    _rebuilds_the_same(m)


@pytest.mark.usefixtures("mcp_on")
def test_over_mcp(env):
    async def flow(client):
        pos = _ok(await _do(client, "maintenance", "positions.create", name="Pool"))
        task = _ok(await _do(client, "maintenance", "tasks.create", position_id=pos["id"], name="Test water",
                             interval=1, unit="weeks"))
        set_ = _ok(await _do(client, "maintenance", "tasks.set_resources", task_id=task["id"], resources={
            "labour": [{"trade": "Pool technician", "people": 1, "hours": 0.5}], "method": "Home kit"}))
        bad = await _do(client, "maintenance", "tasks.set_resources", task_id=task["id"], resources={"crew": 1})
        await _do(client, "maintenance", "packages.create", name="Weekly", position_id=pos["id"], every=1,
                  unit="weeks", tasks=[task["id"]])
        listed = _ok(await _list(client, "packages"))
        return set_, bad, listed

    set_, bad, listed = _session(env["token"], flow)
    assert set_["resources"]["labour_hours"] == 0.5 and set_["resources"]["method"] == "Home kit"
    assert bad.is_error and "doesn't take crew" in bad.content[0].text
    assert listed["packages"][0]["rollup"]["labour"] == [{"trade": "Pool technician", "hours": 0.5, "people": 1}]


def test_the_app_routes(api):
    """PATCH the task with resources, read its LSA page."""
    site = api.post(f"{M}/positions", json={"name": "Pool"}).json()
    made = api.post(f"{M}/positions/{site['id']}/tasks", json={"name": "Skim", "interval": 1, "unit": "weeks"}).json()
    r = api.patch(f"{M}/tasks/{made['id']}", json={"resources": {"tools": [{"name": "Skimmer"}]}})
    assert r.status_code == 200, r.text
    assert r.json()["resources"]["tools"] == [{"name": "Skimmer"}]
    assert api.patch(f"{M}/tasks/{made['id']}", json={"resources": {"tools": "Skimmer"}}).status_code == 422
    page = api.get(f"{M}/tasks/{made['id']}/lsa")
    assert page.status_code == 200 and page.json()["task"]["resources"]["tools"] == [{"name": "Skimmer"}]
