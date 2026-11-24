"""A mission on a position over the API (maintenance models.link with mission, get.position with missions): the Missions
tab's New mission… and its phases in one call, made once however often it's re-run, with the same
checks as the app, a write-scope token, and its answers through analyse rbd_mission."""

import pytest

from backend.tests.test_api_tools import A, GRAPH, WEIBULL, env, maint  # noqa: F401 - fixtures

pytestmark = pytest.mark.usefixtures("mcp_on")

SORTIE = [{"name": "Take-off", "duration": 0.2}, {"name": "Transit", "duration": 2},
          {"name": "Survey", "duration": 5.6}, {"name": "Return", "duration": 2}, {"name": "Landing", "duration": 0.2}]
REPAIR = {"distribution_id": "exponential", "params": [{"name": "failure_rate", "value": 0.5}]}


def _position_with_rbd(maint, repairable=False):
    """A position flown on a saved two-block RBD of its own (linked as its model)."""
    pos = maint.post("/api/v1/maintenance/positions.create", {"name": "Power module"}).json()
    graph = GRAPH
    if repairable:
        graph = {**GRAPH, "nodes": [{**n, "repair": REPAIR} if n["type"] == "component" else n for n in GRAPH["nodes"]]}
    rbd = maint.post("/api/v1/change/rbd_create", {"name": "Generator pair", "unit": "hours",
                                                   "repairable": repairable, **graph})
    assert rbd.status_code == 200, rbd.text
    link = maint.post("/api/v1/maintenance/models.link", {"position_id": pos["id"], "rbd_id": rbd.json()["id"]})
    assert link.status_code == 200, link.text
    return pos["id"], rbd.json()["id"]


def _sortie(maint, pid, **extra):
    spec = {"name": "10 flight-hour sortie", "clock": "operating", "label": "flight hours",
            "length": 10, "length_unit": "hours", "phases": SORTIE, **extra}
    return _mission(maint, pid, {k: v for k, v in spec.items() if v is not None})


def _mission(maint, pid, spec, token=None):
    return maint.post("/api/v1/maintenance/models.link", {"position_id": pid, "mission": spec}, token=token)


def _missions(maint, pid, token=None):
    r = maint.post("/api/v1/maintenance/get.position", {"id": pid, "missions": True}, token=token)
    assert r.status_code == 200, r.text
    return [x for row in r.json()["links"] if (row.get("rbd") or {}).get("mission_rbd") for x in row["missions"]]


def test_a_sortie_is_made_with_its_phases_clock_and_label(maint):
    pid, _ = _position_with_rbd(maint)
    r = _sortie(maint, pid)
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["created"] is True and got["mission_id"] == "mission" and got["built_from"] == "copy"
    m = got["mission"]
    assert m["name"] == "10 flight-hour sortie"
    assert m["phase_names"] == ["Take-off", "Transit", "Survey", "Return", "Landing"]
    assert m["phase_durations"] == [0.2, 2, 5.6, 2, 0.2] and m["duration"] == pytest.approx(10)
    assert m["setup"]["clock"] == "operating" and m["setup"]["label"] == "flight hours"
    assert m["setup"]["length"] == {"value": 10.0, "unit": "hours"}
    assert got["rbd"]["name"] == "Power module — 10 flight-hour sortie"
    assert f"tab=missions&mission={got['rbd']['id']}%3Amission&on={pid}" in got["url"]
    [listed] = _missions(maint, pid)
    assert listed["name"] == "10 flight-hour sortie" and listed["phases"] == 5


def test_a_rerun_changes_the_same_mission_by_name_or_ref(maint):
    pid, _ = _position_with_rbd(maint)
    first = _sortie(maint, pid).json()
    again = _sortie(maint, pid, phases=SORTIE[:2] + [{"name": "Survey", "duration": 7.8}]).json()
    assert again["created"] is False and again["rbd"]["id"] == first["rbd"]["id"]
    assert again["mission"]["phase_names"] == ["Take-off", "Transit", "Survey"]
    assert len(_missions(maint, pid)) == 1
    # A ref finds it again under a new name: it's renamed, not doubled.
    keyed = _sortie(maint, pid, name="Survey sortie", ref="sortie-1").json()
    assert keyed["created"] is True  # no mission had that ref yet
    renamed = _sortie(maint, pid, name="Long survey sortie", ref="sortie-1").json()
    assert renamed["created"] is False and renamed["rbd"]["id"] == keyed["rbd"]["id"]
    assert renamed["mission"]["name"] == "Long survey sortie" and renamed["ref"] == "sortie-1"
    assert renamed["rbd"]["name"] == "Power module — Long survey sortie"
    assert sorted(x["name"] for x in _missions(maint, pid)) == ["10 flight-hour sortie", "Long survey sortie"]
    # Renaming onto another mission's name is refused.
    r = _sortie(maint, pid, name="10 flight-hour sortie", ref="sortie-1")
    assert r.status_code >= 400 and "already has a mission" in r.text
    # A new length alone: one phase of that length, as a new mission starts.
    one = _mission(maint, pid, {"ref": "sortie-1", "length": 4, "length_unit": "hours"}).json()
    assert one["mission"]["phase_names"] == ["Whole mission"] and one["mission"]["duration"] == pytest.approx(4)


def test_the_apps_checks_hold(maint):
    pid, _ = _position_with_rbd(maint)
    bad = _sortie(maint, pid, length=9)
    assert bad.status_code >= 400 and "add up to 10" in bad.text
    r = _sortie(maint, pid, length_unit="months")
    assert r.status_code >= 400 and "operating-time mission" in r.text
    r = _sortie(maint, pid, phases=[{"name": "Take-off"}])
    assert r.status_code >= 400 and "duration" in r.text
    r = _mission(maint, pid, {"length_unit": "hours"})
    assert r.status_code >= 400 and "length_unit goes with a length" in r.text
    r = _mission(maint, "nope", {"name": "x"})
    assert r.status_code >= 400
    r = _mission(maint, pid, {"name": "x", "colour": "red"})
    assert r.status_code >= 400 and "doesn't take colour" in r.text
    assert _missions(maint, pid) == []  # nothing half-made


def test_a_read_token_reads_missions_but_cannot_make_one(maint):
    pid, _ = _position_with_rbd(maint)
    r = _mission(maint, pid, {"name": "x"}, token=maint.read_only)
    assert r.status_code == 403
    _sortie(maint, pid)
    assert len(_missions(maint, pid, token=maint.read_only)) == 1


def test_its_answers_are_read_through_analyse_rbd_mission(maint):
    pid, _ = _position_with_rbd(maint)
    rid = _sortie(maint, pid).json()["rbd"]["id"]
    r = maint.post("/api/v1/analyse/rbd_mission", {"rbd_id": rid, "mission_id": "mission", "answers": True})
    assert r.status_code == 200, r.text
    got = r.json()
    assert [p["name"] for p in got["phases"]] == ["Take-off", "Transit", "Survey", "Return", "Landing"]
    assert 0 < got["result"]["mission_reliability"] <= 1
    summary = got["answers"]["summary"]
    assert summary["chance"] is not None and summary["length"]


def test_a_repairable_rbd_is_flown_as_the_app_flies_it(maint):
    """The app copies a repairable RBD without its repairs; the API does the same, and the
    repairable diagram itself still takes no mission (change rbd_mission's rule is unchanged)."""
    pid, rbd_id = _position_with_rbd(maint, repairable=True)
    models = maint.post("/api/v1/maintenance/get.position", {"id": pid}).json().get("models") or []
    link = next(x["id"] for x in models if x.get("model_id") == rbd_id)
    r = _sortie(maint, pid, link_id=link)
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["built_from"] == "copy" and "repairs and planned work" in got["notes"][0]
    copy = maint.post("/api/v1/get/rbd", {"id": got["rbd"]["id"]}).json()
    assert copy.get("repairable") is False
    refused = maint.post("/api/v1/change/rbd_mission", {"rbd_id": rbd_id, "name": "x", "phases": SORTIE})
    assert refused.status_code >= 400 and "non-repairable" in refused.text
