"""The evidence an RCM decision can link, found from where it is (rcm_evidence.py): the
position's and its class's life models, the analyses run on them, the failure history, the
condition readings and the failure reports, ranked and searchable; nothing linked until the user
links it; a failure history, readings or a failure report linked (not checked); and a fit limited
to the lives fitted in a window, which the evidence keeps."""

from datetime import date, timedelta

import mongomock
import numpy as np
import pytest
import surpyval as sp

from backend.config import SAMPLE_OWNER
from backend.maintenance import position_models as pm
from backend.maintenance import rcm_decisions, rcm_evidence, rcm_graph
from backend.maintenance.service import PROJECTORS, Invalid, Maintenance
from backend.maintenance.store import GraphStore
from backend.services import strategy_store
from backend.tests.test_maintenance_rcm_api import api  # noqa: F401 - fixture

ORG = "org-evidence"
OWNERS = [ORG, SAMPLE_OWNER]


@pytest.fixture()
def m():
    return Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")


@pytest.fixture()
def db():
    from backend.services import samples

    d = mongomock.MongoClient()["rcm_evidence_candidates"]
    samples.seed_samples(d)
    return d


def _history(m, pid, lives, start, failed=None):
    """Items fitted one after another, each removed after its life: failed, or changed on schedule."""
    on = start
    for i, life in enumerate(lives):
        m.fit(pid, new_item={"name": f"Seal {pid[-4:]}-{i}"}, on=on.isoformat())
        on = on + timedelta(days=life)
        m.remove(pid, on=on.isoformat(), reason="failure" if (failed is None or failed[i]) else "planned")
    return on


def _seal_pump(m):
    pump = m.create_position("Pump SP-01", position_class="Mechanical seal")["id"]
    fn = m.add_function(pump, "Pump slurry", "50 L/s")
    ff = m.add_functional_failure(fn["id"], "Leaks")
    mode = m.add_failure_mode(pump, "Seal faces worn", functional_failure_id=ff["id"])["id"]
    return pump, mode


def test_a_fit_on_lives_since_a_date_matches_surpyval_on_those_lives(m, db):
    pump, mode = _seal_pump(m)
    # Before 2022 the seals ran to failure (long lives); since, they're changed at about 180 days.
    old = [520, 610, 480, 700, 560, 450, 630]
    after = _history(m, pump, old, date(2010, 3, 1))
    assert after < date(2022, 1, 1)
    new = [150, 182, 181, 175, 179, 120, 181, 180]
    new_failed = [True, False, False, False, False, True, False, False]
    _history(m, pump, new, date(2022, 1, 1), new_failed)

    link = pm.fit_position_model(m, db, pump, scope="position", window={"since": "2022-01-01"})
    src = link["source"]
    assert src["window"] == {"since": "2022-01-01", "lives": 8, "failures": 2}
    assert "since 1 Jan 2022" in link["name"]
    assert pm.source_text(link).endswith("only 8 lives fitted since 1 Jan 2022 (2 failed)")
    doc = db.models.find_one({"_id": link["model_id"]})
    got = {p["name"]: p["value"] for p in doc["results"]["params"]}
    # Hand check: SurPyval's Weibull on the eight lives fitted since 2022 alone (each removed: a failure
    # c=0, a change on schedule c=1).
    x = np.array(new, dtype=float)
    c = np.array([0 if f else 1 for f in new_failed])
    ref = sp.Weibull.fit(x=x, c=c)
    assert got["alpha"] == pytest.approx(ref.alpha, rel=1e-6)
    assert got["beta"] == pytest.approx(ref.beta, rel=1e-6)
    # The whole history gives a different answer: the window changed the data, not the method.
    whole = pm.fit_position_model(m, db, pump, scope="position")
    assert whole["source"]["failures"] == 9 and "window" not in whole["source"]
    with pytest.raises(Invalid, match="window until is a date|is a date"):
        pm.fit_position_model(m, db, pump, window={"until": "soon"})
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before


def test_the_candidates_are_what_is_relevant_ranked_and_searchable(m, db):
    pump, mode = _seal_pump(m)
    _history(m, pump, [300, 420, 380, 510], date(2019, 1, 1))
    other = m.create_position("Pump SP-02", position_class="Mechanical seal")["id"]
    _history(m, other, [350, 460, 390], date(2019, 2, 1))
    fitted = pm.link_saved(m, db, OWNERS, set(), pump, "model", "sample-model-bearings-weibull", [mode])
    point = m.add_point(pump, "Seal leak rate", kind="condition", unit="mL/min")["id"]
    m.record_reading(point, 3.5, on="2026-11-01")
    report = m.file_failure_report(pump, "Seal leaking at the gland", occurred_on="2026-10-01",
                                   failure_mode_id=mode)["id"]
    db.strategy_analyses.insert_one({"_id": "an-1", "id": "an-1", "name": "Seal replacement", "owner_id": ORG,
                                     "kind": "optimal_replacement",
                                     "inputs": {"model_id": fitted["model_id"], "model_name": fitted["name"]},
                                     "results": {"optimal_time": 250, "unit": "days"}})
    analysis = strategy_store.get_analysis(db, "an-1", ORG)

    got = rcm_evidence.candidates(m, db, OWNERS, set(), pump, mode)
    rows = [(c["type"], c["id"], c["scope"]) for c in got["candidates"]]
    # This mode's first: the model fitted for it, then the analysis run on it and its report.
    assert rows[0] == ("model", fitted["model_id"], "mode")
    assert ("strategy_analysis", analysis.id, "mode") in rows
    assert ("failure_report", report, "mode") in rows
    assert ("history", pump, "position") in rows
    assert ("history", "class:Mechanical seal", "class") in rows
    assert ("point", point, "position") in rows
    scopes = [c["scope"] for c in got["candidates"]]
    assert scopes == sorted(scopes, key=rcm_evidence.SCOPES.index)
    assert {k["id"] for k in got["kinds"]} >= {"model", "analysis", "history", "readings", "failure_report"}
    only = rcm_evidence.candidates(m, db, OWNERS, set(), pump, mode, kind="readings")["candidates"]
    assert [c["id"] for c in only] == [point]
    found = rcm_evidence.candidates(m, db, OWNERS, set(), pump, mode, q="gland")["candidates"]
    assert [c["id"] for c in found] == [report]
    with pytest.raises(Invalid, match="kind is one of"):
        rcm_evidence.candidates(m, db, OWNERS, set(), pump, mode, kind="nonsense")
    # Nothing was linked by looking: the decision still has none.
    assert (m.rcm_mode(mode).get("decision") or {}).get("evidence") is None


def test_history_readings_and_reports_link_as_evidence_and_go_stale(m, db):
    pump, mode = _seal_pump(m)
    _history(m, pump, [300, 420], date(2020, 1, 1))
    _history(m, pump, [150, 170, 160], date(2022, 3, 1), [True, False, False])
    point = m.add_point(pump, "Seal leak rate", kind="condition", unit="mL/min")["id"]
    report = m.file_failure_report(pump, "Seal leaking", occurred_on="2026-10-01")["id"]

    def check(evidence):
        m.decide_failure_mode(mode, consequence="operational",
                              decision={"outcome": "fixed_interval", "interval": 180, "interval_unit": "days",
                                        "evidence": evidence})
        return rcm_graph.mode_status(db, m.rcm_mode(mode), OWNERS)["decision"]

    d = check({"type": "history", "id": pump, "window": {"since": "2022-01-01"}})
    assert d["status"] == "linked" and d["evidence_kind"] == "history"
    assert d["artifact_name"] == "Pump SP-01: failure history"
    assert "3 lives fitted since 1 Jan 2022 (1 failed)" in d["summary"]
    assert d["window_words"] == "lives fitted since 1 Jan 2022"
    d = check({"type": "point", "id": point})
    assert d["status"] == "linked" and d["artifact_name"] == "Seal leak rate readings"
    d = check({"type": "failure_report", "id": report})
    assert d["status"] == "linked" and d["artifact_name"].endswith("Seal leaking")
    assert d["artifact_link_path"].endswith(f"&report={report}")
    with pytest.raises(Invalid, match="no such point"):
        check({"type": "point", "id": "not-a-point"})
    with pytest.raises(rcm_decisions.RcmValidationError, match="date window goes with"):
        rcm_decisions.clean_decision({"outcome": "fixed_interval", "interval": 1, "interval_unit": "days",
                                      "evidence": {"type": "point", "id": point, "window": {"since": "2022-01-01"}}})
    # Gone: the point retired, the link stays and says so.
    check({"type": "point", "id": point})
    m.retire_point(point)
    assert rcm_graph.mode_status(db, m.rcm_mode(mode), OWNERS)["decision"]["status"] == "stale"
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before


def test_the_candidates_route(api):
    M = "/api/maintenance"
    pump = api.post(f"{M}/positions", json={"name": "Pump SP-09"}).json()["id"]
    mode = api.post(f"{M}/positions/{pump}/failure-modes", json={"text": "Seal faces worn"}).json()["id"]
    r = api.get(f"{M}/rcm/evidence-candidates", params={"position_id": pump, "mode_id": mode})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["position"]["name"] == "Pump SP-09" and body["mode"]["text"] == "Seal faces worn"
    # Nothing on record at the position yet: only the library's analyses are offered, and nothing is linked.
    assert {c["scope"] for c in body["candidates"]} <= {"library"}
    assert api.get(f"{M}/rcm/evidence-candidates", params={"position_id": pump, "kind": "x"}).status_code == 422


def test_a_study_off_the_tree_refuses_the_trees_records():
    from backend.services import rcm as studies

    with pytest.raises(rcm_decisions.RcmValidationError, match="isn't on the asset tree"):
        studies._study_decision({"outcome": "fixed_interval", "interval": 6, "interval_unit": "months",
                                 "evidence": {"type": "history", "id": "p1"}})
    assert studies._study_decision({"outcome": "accept", "evidence": {"type": "report", "id": "r1"}})["evidence"] == \
        {"type": "report", "id": "r1"}
