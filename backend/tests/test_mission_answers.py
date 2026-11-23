"""A mission's two answers (the Explorer's Missions tab): the chance of completing it and the
failures to expect during it, over the whole phased mission, checked by hand on exponential
blocks; a phased mission with covariates and a schedule gives the same chance it did before; the
setup (start, calendar, starting state) is kept and its length becomes the first phase."""

import math

import mongomock
import numpy as np
import pytest

from backend.services import mission_answers as ma
from backend.services import rbd_missions as rm
from backend.services import rbd_tvc
from backend.services import running_clock
from backend.services.rbd_graph import normalize_graph

OWNER = "org-mission-answers"
RATE = 0.01  # per hour


def _exp(rate=RATE):
    return {"distribution_id": "exponential", "params": [{"name": "failure_rate", "value": rate}]}


def _diagram(edges, models, **extra):
    nodes = [{"id": "input", "type": "input", "data": {}}, {"id": "output", "type": "output", "data": {}}]
    nodes += [{"id": nid, "type": "component", "data": {"label": nid.upper(), "model": model}} for nid, model in models.items()]
    return {"unit": "hours", "nodes": nodes, "edges": [{"source": s, "target": t} for s, t in edges], **extra}


def _series(**extra):
    return _diagram([("input", "a"), ("a", "b"), ("b", "output")], {"a": _exp(), "b": _exp()}, **extra)


def _parallel(**extra):
    return _diagram([("input", "a"), ("input", "b"), ("a", "output"), ("b", "output")], {"a": _exp(), "b": _exp()}, **extra)


def _mission(graph, phases):
    g = {**graph, "phases": phases, "mission_of": {"position_id": "p1"}, "mission_name": "Sortie"}
    return g, rm.find(g, rm.LEGACY_ID)


@pytest.fixture
def db():
    return mongomock.MongoClient().db


def test_series_by_hand_one_phase(db):
    g, mission = _mission(_series(), [{"name": "Whole mission", "duration": 30}])
    got = ma.answers(db, [OWNER], g, mission, simulate=True, today="2026-11-23")
    # Two blocks in series at 0.01 an hour for 30 hours.
    assert got["chance"]["value"] == pytest.approx(math.exp(-2 * RATE * 30), rel=1e-9)
    f = got["failures"]
    assert f["method"] == "exact"
    assert f["expected"] == pytest.approx(2 * RATE * 30, rel=1e-6)  # a renewal of exponentials: rate × time
    # The range of outcomes: Poisson(0.6)'s 5th and 95th percentiles are 0 and 2.
    assert (f["range"]["lower"], f["range"]["upper"]) == (0.0, 2.0)
    assert f["range"]["side"] == "two-sided" and f["range"]["level"] == 0.9
    assert ma.PLAN_NOTE in got["assumed"]


def test_parallel_two_phases_counts_part_failures_and_says_no_bound(db):
    g, mission = _mission(_parallel(), [{"name": "Out", "duration": 10}, {"name": "Back", "duration": 20}])
    got = ma.answers(db, [OWNER], g, mission, simulate=False, today="2026-11-23")
    assert got["chance"]["value"] == pytest.approx(1 - (1 - math.exp(-RATE * 30)) ** 2, rel=1e-9)
    assert got["chance"]["lower_bound"] is None and "several phases" in got["chance"]["bound_note"]
    # Free: the exact figure, the range is Pro.
    assert got["failures"]["expected"] == pytest.approx(2 * RATE * 30, rel=1e-6)
    assert got["failures"]["range"] is None and got["failures"]["pro"]


def test_a_phase_that_switches_a_block_off_has_no_failures_figure_yet(db):
    g, mission = _mission(_parallel(), [{"name": "Out", "duration": 10, "not_needed": ["b"]}, {"name": "Back", "duration": 20}])
    got = ma.answers(db, [OWNER], g, mission, today="2026-11-23")
    assert got["chance"]["value"] is not None
    assert got["failures"]["expected"] is None and "switch blocks off" in got["failures"]["note"]


def test_a_block_with_no_model_stops_both_answers(db):
    graph = _series()
    graph["nodes"][3]["data"].pop("model")
    g, mission = _mission(graph, [{"name": "Whole mission", "duration": 30}])
    got = ma.answers(db, [OWNER], g, mission, today="2026-11-23")
    assert [b["label"] for b in got["blocked"]] == ["B"]
    assert "chance" not in got


def test_setup_is_kept_through_a_save_and_checked():
    g = normalize_graph({**_series(), "mission_of": {"position_id": "p1"}, "mission_name": "Year",
                         rm.SETUP_KEY: {"start": "2026-12-01", "calendar": {"hours_per_day": 8, "days_per_week": 5},
                                        "from": "today", "length": {"value": 12, "unit": "months"}}})
    assert g[rm.SETUP_KEY] == {"start": "2026-12-01", "calendar": {"hours_per_day": 8.0, "days_per_week": 5},
                               "from": "today", "length": {"value": 12.0, "unit": "months"}}
    with pytest.raises(rm.MissionError, match="days a week"):
        rm.parse_setup({"calendar": {"hours_per_day": 8, "days_per_week": 9}})
    with pytest.raises(rm.MissionError, match="date"):
        rm.parse_setup({"start": "next week"})


def test_a_calendar_length_becomes_running_hours_through_the_duty():
    own = ma.clock_for(None, None, {"calendar": {"hours_per_day": 8, "days_per_week": 5}})
    # 12 months at 8 h a day, 5 days a week: 365.25 × 40 / 7 hours.
    assert ma.running_length({"value": 12, "unit": "months"}, "hours", own) == pytest.approx(365.25 * 40 / 7)
    assert ma.running_length({"value": 10, "unit": "hours"}, "hours", own) == pytest.approx(10)
    # Linked, with no duty anywhere: it runs all the time.
    assert ma.running_length({"value": 2, "unit": "days"}, "hours", running_clock.CONTINUOUS) == pytest.approx(48)
    span = ma.calendar_span(80.0, "hours", own, "2026-12-01", "2026-11-23")
    assert span["start"] == "2026-12-01" and span["end"] == "2026-12-15"  # 80 h at 40 h a week: 14 days


# The phased mission with covariates and a time-varying one, as before this change: these figures
# come from dev before the Missions tab (the mission's own calculation, unchanged).
TVC_BEFORE = {"reliability": 0.00012142895795629582, "phase_ends": [0.00020874012247751317, 0.00012142895795630437]}


@pytest.fixture()
def pump(monkeypatch):
    from backend.services import covariate_binding as cb
    from backend.services import rbds as rbds_service
    from backend.tests.test_rbd_tvc_repairable import _entry, _fit, _graph
    import surpyval as sp

    entry = _entry(_fit(sp.ExponentialPH))
    monkeypatch.setattr(rbds_service, "resolvers", lambda db, owner: (None, lambda _: entry))
    monkeypatch.setattr(cb, "inputs_of", lambda b, db, owners: [])
    g = _graph(None, repairable=False)
    del g["nodes"][1]["data"]["covariate_schedules"]
    return g


TVC_PHASES = [{"name": "Run", "duration": 300, "values": {"load": {"table": [{"t": 0, "value": 1}, {"t": 120, "value": 2}]}}},
              {"name": "Rest", "duration": 50, "values": {"load": 1}}]


def test_a_phased_mission_with_covariates_and_a_schedule_gives_the_same_chance(db, pump):
    """The answers' chance is the mission's own calculation: a phased mission whose phases set a
    covariate (constant in one, on a schedule in the other) gives the same figures as before."""
    g, mission = _mission(pump, TVC_PHASES)
    own = rm.analyze(db, [OWNER], g, TVC_PHASES, weakest=False)
    assert own["reliability"] == pytest.approx(TVC_BEFORE["reliability"], rel=1e-12)
    assert [p["reliability_at_end"] for p in own["phases"]] == pytest.approx(TVC_BEFORE["phase_ends"], rel=1e-12)
    got = ma.answers(db, [OWNER], g, mission, simulate=True, today="2026-11-23")
    assert got["chance"]["value"] == pytest.approx(own["reliability"], rel=1e-12)
    assert got["phases"] == 2 and got["length"] == 350
    # Its covariate changes over the mission: the failures come from the (seeded) simulation.
    f = got["failures"]
    assert f["method"] == "simulated" and f["expected"] > 0 and f["range"]["lower"] <= f["expected"] <= f["range"]["upper"]


# ---- a mission built in the Missions tab ----------------------------------------------------------

@pytest.fixture()
def m():
    from backend.maintenance.service import PROJECTORS, Maintenance
    from backend.maintenance.store import GraphStore

    return Maintenance(GraphStore(":memory:", PROJECTORS), OWNER, "tester")


@pytest.fixture()
def sdb(monkeypatch):
    """The seeded db as the app's own, so a saved fit can be brought back."""
    from backend import db as db_mod
    from backend.services import samples

    d = mongomock.MongoClient()["mission_answers"]
    samples.seed_samples(d)
    monkeypatch.setattr(db_mod, "_db", d)
    monkeypatch.setattr(db_mod, "_simulated", True)
    return d


def test_a_tab_mission_on_a_covariate_model_with_two_phases(m, sdb):
    """Built as the Missions tab builds it (runs on the position's model, 12 months at its own duty of
    8 h a day, 5 days a week): one phase of the whole length in running hours; then a second phase
    with its own covariate value, and both answers over the two phases."""
    from backend.maintenance import position_models as pm

    owners = [OWNER, "__samples__"]
    seal = m.create_position("Seal")["id"]
    ph = pm.link_saved(m, sdb, owners, set(), seal, "model", "sample-model-seal-weibull-ph")
    setup = {"start": "2026-12-01", "calendar": {"hours_per_day": 8, "days_per_week": 5}, "from": "new"}
    made = pm.build_mission_rbd(m, sdb, owners, set(), seal, OWNER, "Hot season", link_id=ph["id"], setup=setup,
                                length={"value": 12, "unit": "months"})
    graph = sdb.rbds.find_one({"_id": made["rbd"]["id"]})["graph"]
    assert graph[rm.SETUP_KEY] == {**setup, "calendar": {"hours_per_day": 8.0, "days_per_week": 5},
                                   "length": {"value": 12.0, "unit": "months"}}
    unit_hours = ma.running_length({"value": 12, "unit": "months"}, graph["unit"], ma.clock_for(None, None, setup))
    assert [p["name"] for p in graph["phases"]] == ["Whole mission"]
    assert graph["phases"][0]["duration"] == pytest.approx(unit_hours, rel=1e-6)
    [row] = [r for r in rm.position_missions(m, sdb, owners, position_ids=[seal]) if r["rbd"]]
    cov = row["missions"][0]["covariates"][0]["name"]
    # Two phases: the first half at one value of the covariate, the second at another.
    half = graph["phases"][0]["duration"] / 2
    phases = [{"name": "Cool", "duration": half, "values": {cov: 20}}, {"name": "Hot", "duration": half, "values": {cov: 60}}]
    g, mission = rm.save(graph, rm.LEGACY_ID, phases=phases)
    own = rm.analyze(sdb, owners, g, mission["phases"], weakest=False)
    got = ma.answers(sdb, owners, g, mission, m=m, position_id=seal, today=m.today(), simulate=True)
    assert got["chance"]["value"] == pytest.approx(own["reliability"], rel=1e-12)
    assert got["phases"] == 2 and got["length"] == pytest.approx(2 * half)
    assert got["calendar"]["start"] == "2026-12-01" and got["calendar"]["end"] >= "2027-11-30"
    f = got["failures"]
    assert f["method"] == "simulated" and f["range"]["side"] == "two-sided"


def test_runs_on_an_rbd_below_or_the_tree_in_series(m, sdb):
    from backend.maintenance import position_models as pm
    from backend.maintenance.service import Invalid
    from backend.services import rbds as rbds_service

    owners = [OWNER, "__samples__"]
    site = m.create_position("Site")["id"]
    plant = m.create_position("Pump station", parent_id=site)["id"]
    for name in ("Pump A", "Pump B"):
        p = m.create_position(name, parent_id=plant)["id"]
        pm.link_saved(m, sdb, owners, set(), p, "model", "sample-model-bearings-weibull")
    drawn = rbds_service.save_rbd(sdb, "Station, as drawn", _parallel(), OWNER)
    link = pm.link_rbd(m, sdb, owners, set(), plant, drawn.id)
    # From the site: runs on the station's RBD, a position below it.
    made = pm.build_mission_rbd(m, sdb, owners, set(), site, OWNER, "Duty", link_id=link["id"])
    assert made["built_from"] == "copy" and made["position_id"] == site
    # The tree, in series, even where the position has an RBD of its own: and it says so.
    tree = pm.build_mission_rbd(m, sdb, owners, set(), plant, OWNER, "Tree run", tree=True,
                                length={"value": 10, "unit": "hours"})
    assert tree["built_from"] == "tree" and "series" in (tree["series_warning"] or "")
    assert sdb.rbds.find_one({"_id": tree["rbd"]["id"]})["graph"]["phases"][0]["duration"] == 10
    lone = m.create_position("Lone")["id"]
    with pytest.raises(Invalid, match="no positions inside"):
        pm.build_mission_rbd(m, sdb, owners, set(), lone, OWNER, "x", tree=True)
