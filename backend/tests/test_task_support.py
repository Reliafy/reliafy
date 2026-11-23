"""Supporting tasks: "keeps it on its life" (supporting.py). A new event only; rebuild equals live;
the record changes no forecast number (the what-ifs that use the impact come later)."""

import pytest

from backend.maintenance import supporting as sp
from backend.maintenance.service import Invalid
from backend.tests.test_explorer_redundancy import _ok, client  # noqa: F401
from backend.tests.test_maintenance_mcp import env  # noqa: F401
from backend.tests.test_rbd_tree_plan import _same_after_rebuild, db, m  # noqa: F401


def _setup(m):
    p = m.create_position("Spindle")["id"]
    wear = m.add_failure_mode(p, "Bearing worn out")["id"]
    seal = m.add_failure_mode(p, "Seal leaks")["id"]
    grease = m.create_task(p, "Grease the bearing", 50, "hours", failure_mode_ids=[wear])
    return p, wear, seal, grease


def test_a_routine_task_is_marked_supporting_with_defaults(m):
    p, wear, _, grease = _setup(m)
    view = m.set_task_support(grease["id"], {"failure_mode_ids": [wear], "impact": {"form": "hazard_ratio", "k": 2}})
    s = view["support"]
    assert s["failure_mode_ids"] == [wear]
    assert s["reference"] == {"value": 50.0, "unit": "hours"}  # the task's own interval when marked
    assert s["impact"] == {"form": "hazard_ratio", "k": 2.0}
    assert s["grace"] == 0.0 and s["source"] == "assumed" and s["note"] == ""
    assert s["words"] == "Keeps it on its life: Bearing worn out · failure rate × 2 if not done (Assumed)"
    assert s["marker"] == {"text": "Supports × 2", "title": "Keeps it on its life: failure rate × 2 if not done (Assumed)",
                           "assumed": True}
    assert view["restoration"]["words"] == sp_words()
    # The task table carries the marker; the RCM's brief carries the record.
    row = next(r for r in m.task_table(p)["tasks"] if r["id"] == grease["id"])
    assert row["support"]["text"] == "Supports × 2"
    _same_after_rebuild(m)


def sp_words():
    from backend.maintenance.restoration import SUPPORT_WORDS

    return SUPPORT_WORDS


def test_blank_impact_is_supports_with_no_modelled_impact(m):
    _, _, _, grease = _setup(m)
    s = m.set_task_support(grease["id"], True)["support"]
    assert s["impact"] is None and s["failure_mode_ids"] == []
    assert s["words"] == "Keeps it on its life: its whole life · no modelled impact"
    assert s["marker"]["text"] == "Supports" and s["marker"]["assumed"] is False
    # Cleared: not supporting.
    assert m.set_task_support(grease["id"], None)["support"] is None
    _same_after_rebuild(m)


def test_what_is_refused(m):
    p, wear, seal, grease = _setup(m)
    for bad, said in [({"failure_mode_ids": [seal]}, "only failure modes the task serves"),
                      ({"impact": {"form": "hazard_ratio", "k": 0.5}}, "from 1"),
                      ({"impact": {"form": "ageing_rate", "p": 2}}, "isn't taken yet"),
                      ({"impact": {"form": "hazard_ratio", "k": 2, "x": 1}}, "doesn't take x"),
                      ({"grace": 140}, "0% to 100%"),
                      ({"source": "guess"}, "source is one of"),
                      ({"reference": {"value": 3, "unit": "months"}}, "in the task's unit"),
                      ({"reference": 0}, "more than 0"),
                      ({"colour": "red"}, "doesn't take colour")]:
        with pytest.raises(Invalid, match=said):
            m.set_task_support(grease["id"], bad)
    check = m.create_task(p, "Check vibration", 1, "months", outcome="on_condition", failure_mode_ids=[wear])
    with pytest.raises(Invalid, match="is a check"):
        m.set_task_support(check["id"], True)


def test_a_fixed_interval_task_restores_none_while_supporting(m):
    p, wear, _, _ = _setup(m)
    oil = m.create_task(p, "Change the oil", 250, "hours", outcome="fixed_interval", failure_mode_ids=[wear])
    view = m.set_task_support(oil["id"], {"impact": 2.5, "source": "maker", "grace": 20, "note": "Manual 7.2"})
    assert m._get(oil["id"], "Task")["restoration"] == sp.RESTORES_NONE  # what forecasts and RBDs read
    assert view["restoration"]["source"] == "support"
    assert view["support"]["impact"] == {"form": "hazard_ratio", "k": 2.5} and view["support"]["grace"] == 20.0
    assert "(From the maker)" in view["support"]["words"]
    # Choosing another effect (as new) takes it off supporting.
    view = m.set_task_restoration(oil["id"], {"kind": "as_new"})
    assert view["support"] is None and view["restoration"]["words"] == "As new"
    # Marked again, then cleared: what it leaves the item as is back to not set.
    m.set_task_support(oil["id"], True)
    m.set_task_support(oil["id"], None)
    assert m._get(oil["id"], "Task").get("restoration") is None
    _same_after_rebuild(m)


def test_several_supporting_tasks_multiply(m):
    p, wear, _, grease = _setup(m)
    clean = m.create_task(p, "Clean the screen", 100, "hours", failure_mode_ids=[wear])
    m.set_task_support(grease["id"], {"failure_mode_ids": [wear], "impact": 2})
    view = m.set_task_support(clean["id"], {"impact": 1.5})  # its whole life: overlaps every mode
    c = view["support"]["combined"]
    assert c["k"] == 3.0 and {t["name"] for t in c["tasks"]} == {"Grease the bearing", "Clean the screen"}
    assert sp.combined({"id": "a", "support": {"impact": {"k": 2}}}, []) is None


def test_support_over_mcp_args(env):  # noqa: F811
    from backend.maintenance import mcp_tools

    _, table = mcp_tools.TOOL_TABLES["maintenance"]
    assert "support" in table["tasks.update"][1].split()


def test_support_over_rest(client):  # noqa: F811
    p = _ok(client.post("/api/maintenance/positions", json={"name": "Mower deck"}))["id"]
    fm = _ok(client.post(f"/api/maintenance/positions/{p}/failure-modes", json={"text": "Spindle bearing worn out"}))["id"]
    t = _ok(client.post(f"/api/maintenance/positions/{p}/tasks",
                        json={"name": "Grease the spindles", "interval": 50, "unit": "hours", "failure_mode_ids": [fm]}))["id"]
    view = _ok(client.patch(f"/api/maintenance/tasks/{t}", json={"support": {"failure_mode_ids": [fm],
                                                                             "impact": {"form": "hazard_ratio", "k": 3}}}))
    assert view["support"]["words"].startswith("Keeps it on its life: Spindle bearing worn out · failure rate × 3")
    table = _ok(client.get(f"/api/maintenance/task-table?position_id={p}"))
    assert table["tasks"][0]["support"]["text"] == "Supports × 3"
    r = client.patch(f"/api/maintenance/tasks/{t}", json={"support": {"grace": -1}})
    assert r.status_code == 422 or r.status_code == 400
    assert _ok(client.patch(f"/api/maintenance/tasks/{t}", json={"support": None}))["support"] is None
