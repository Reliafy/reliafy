"""The RCM evidence check: a decision on a position against the saved model or
analysis it links (backend/maintenance/rcm_decisions.py), read live."""

import matplotlib

matplotlib.use("Agg")

import io

import mongomock
import numpy as np
import pandas as pd
import pytest

from backend.maintenance import rcm_graph
from backend.maintenance.service import PROJECTORS, Maintenance
from backend.maintenance.store import GraphStore


@pytest.fixture()
def session(monkeypatch):
    from backend import db

    test_db = mongomock.MongoClient()["reliafy_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    yield test_db


A = "user-a"


def _csv(kind: str) -> bytes:
    rng = np.random.default_rng(7)
    if kind == "wear":
        x = np.round(rng.weibull(3.0, 80) * 100, 2)
    else:  # random
        x = np.round(rng.exponential(100, 80), 2)
    buf = io.StringIO()
    pd.DataFrame({"t": x}).to_csv(buf, index=False)
    return buf.getvalue().encode()


def _make_model(session, owner, kind, distribution="weibull"):
    from backend.services import datasets as ds
    from backend.services import models as ms

    dataset = ds.create_dataset(session, f"{kind}.csv", _csv(kind), owner)
    return ms.save_model(session, f"{kind} model", dataset, distribution, {"x": "t"}, [], None, owner_id=owner)


def _make_replacement(session, owner, beneficial: bool):
    """Save an optimal-replacement analysis; wear-out params + high failure cost
    -> beneficial, exponential -> not beneficial."""
    from backend.services import strategy_store

    if beneficial:
        inputs = {"distribution_id": "weibull",
                  "params": [{"name": "alpha", "value": 1000.0}, {"name": "beta", "value": 3.0}],
                  "planned_cost": 100.0, "unplanned_cost": 2000.0, "unit": "hours"}
    else:
        inputs = {"distribution_id": "exponential",
                  "params": [{"name": "failure_rate", "value": 0.001}],
                  "planned_cost": 100.0, "unplanned_cost": 2000.0, "unit": "hours"}
    return strategy_store.save_analysis(session, "repl", "optimal_replacement", inputs, owner)


def _status(session, owner, decision):
    """Decide one failure mode on a position of ``owner``'s and read the check."""
    m = Maintenance(GraphStore(":memory:", PROJECTORS), owner, "tester")
    pid = m.create_position("Thing")["id"]
    mode = m.add_failure_mode(pid, "Mode", consequence="operational")
    # Hidden and operational: the RCM decision diagram allows every single outcome there.
    m.decide_failure_mode(mode["id"], decision=decision, hidden=True)
    return rcm_graph.mode_status(session, m.rcm_mode(mode["id"]), owner)["decision"]


# ---- Evidence-status rules ------------------------------------------------------

def test_rtf_random_statuses(session):
    wear = _make_model(session, A, "wear")             # beta ~ 3 -> wear_out
    random_m = _make_model(session, A, "random")       # beta ~ 1 -> random
    expo = _make_model(session, A, "random", "exponential")

    d = {"outcome": "rtf", "rtf_basis": "random", "evidence": {"type": "model", "id": random_m.id}}
    assert _status(session, A, d)["status"] == "supported"

    d["evidence"]["id"] = wear.id
    r = _status(session, A, d)
    assert r["status"] == "contradicted"
    assert "wear-out" in r["summary"]

    d["evidence"]["id"] = expo.id
    assert _status(session, A, d)["status"] == "supported"

    # Old model without CI info -> inconclusive with a re-save hint.
    session.models.update_one({"_id": wear.id}, {"$unset": {"results.randomness": ""}})
    session.models.update_one({"_id": wear.id}, {"$set": {"results.params": [
        {"name": "alpha", "value": 100.0}, {"name": "beta", "value": 3.0}]}})
    d["evidence"]["id"] = wear.id
    r = _status(session, A, d)
    assert r["status"] == "inconclusive" and "re-save" in r["reason"]


def test_replacement_statuses(session):
    good = _make_replacement(session, A, beneficial=True)
    bad = _make_replacement(session, A, beneficial=False)

    fixed = {"outcome": "fixed_interval", "evidence": {"type": "strategy_analysis", "id": good.id}}
    r = _status(session, A, fixed)
    assert r["status"] == "supported" and "Optimal interval" in r["summary"]

    fixed["evidence"]["id"] = bad.id
    assert _status(session, A, fixed)["status"] == "contradicted"

    rtf_u = {"outcome": "rtf", "rtf_basis": "uneconomic",
             "evidence": {"type": "strategy_analysis", "id": bad.id}}
    assert _status(session, A, rtf_u)["status"] == "supported"
    rtf_u["evidence"]["id"] = good.id
    assert _status(session, A, rtf_u)["status"] == "contradicted"


def test_on_condition_ffi_mismatch_unevidenced_stale(session):
    from backend.services import datasets as ds
    from backend.services import degradation as deg
    from backend.services import strategy_store

    # Degradation model for on_condition.
    rows = []
    rng = np.random.default_rng(0)
    for u in range(4):
        for t in np.arange(1, 7) * 50.0:
            rows.append({"i": f"u{u}", "t": t, "y": 1 + (0.02 + 0.003 * u) * t + rng.normal(0, 0.05)})
    buf = io.StringIO(); pd.DataFrame(rows).to_csv(buf, index=False)
    dataset = ds.create_dataset(session, "deg.csv", buf.getvalue().encode(), A)
    dmodel = deg.save_model(session, "Deg", dataset,
                            {"mapping": {"i": "i", "x": "t", "y": "y"}, "threshold": 8.0,
                             "path": "linear", "distribution_id": "weibull",
                             "population_method": "moments", "unit": "h", "measurement_unit": "mm"}, A)
    oc = {"outcome": "on_condition", "evidence": {"type": "degradation_model", "id": dmodel.id}}
    assert _status(session, A, oc)["status"] == "supported"

    # Failure finding.
    ffi = strategy_store.save_analysis(session, "ffi", "failure_finding",
        {"distribution_id": "exponential", "params": [{"name": "failure_rate", "value": 0.001}],
         "target_availability": 0.99, "unit": "h"}, A)
    ff = {"outcome": "failure_finding", "evidence": {"type": "strategy_analysis", "id": ffi.id}}
    r = _status(session, A, ff)
    assert r["status"] == "supported" and "Check every" in r["summary"]

    # Type mismatch -> inconclusive.
    mm = {"outcome": "on_condition", "evidence": {"type": "strategy_analysis", "id": ffi.id}}
    assert _status(session, A, mm)["status"] == "inconclusive"

    # Unevidenced.
    assert _status(session, A, {"outcome": "fixed_interval", "evidence": None})["status"] == "unevidenced"

    # Redesign / accept -> no status.
    assert _status(session, A, {"outcome": "redesign"})["status"] is None

    # Stale: delete the artifact.
    deg.delete_model(session, dmodel.id, A)
    assert _status(session, A, oc)["status"] == "stale"


def test_another_owners_evidence_is_stale_to_the_reader(session):
    """The check reads the evidence as the position's owner: someone else's
    model, however it got linked, resolves to nothing."""
    theirs = _make_model(session, "user-b", "random")
    d = {"outcome": "rtf", "rtf_basis": "random", "evidence": {"type": "model", "id": theirs.id}}
    assert _status(session, A, d)["status"] == "stale"
    assert _status(session, "user-b", d)["status"] == "supported"


def test_unit_mismatch_blocks_support(session):
    """A task interval in a different unit than its evidence resolves
    inconclusive — units are free text, so only definite disagreement trips."""
    analysis = _make_replacement(session, A, beneficial=True)  # unit: hours

    def status_for(interval_unit, interval=500):
        return _status(session, A, {
            "outcome": "fixed_interval", "task": "replace", "interval": interval,
            "interval_unit": interval_unit,
            "evidence": {"type": "strategy_analysis", "id": analysis.id},
        })

    # Definite mismatch -> inconclusive with a unit-specific reason.
    bad = status_for("km")
    assert bad["status"] == "inconclusive" and "Unit mismatch" in bad["reason"]
    # Aliases of the same unit agree.
    assert status_for("hrs")["status"] == "supported"
    assert status_for("hours")["status"] == "supported"
    # Another time unit is checked after conversion, not marked a mismatch, and says so.
    # (12 days, near the optimum: 500 days would be far longer than it supports.)
    days = status_for("days", 12)
    assert days["status"] == "supported" and "Unit mismatch" not in str(days)
    assert days["unit_conversion"] == "evidence in hours, task interval in days: converted at 1 day = 24 hours (running all the time)"
    assert "≈ 298 hours, about 12.4 days" in days["summary"], days["summary"]


def test_interval_far_shorter_than_the_evidence_supports_says_so(session):
    """An interval far shorter than its evidence supports isn't "supported": the check
    gives both intervals and how many times as often the task is done. Oil changed
    every 25 h against a cost-optimal change at about 101 h reads contradicted; 100 h
    and 60 h (over half of it) read supported. Longer than a P-F check interval
    allows stays contradicted as before."""
    from backend.services import strategy_store

    oil = strategy_store.save_analysis(session, "oil", "optimal_replacement", {
        "distribution_id": "lognormal", "params": [4.840310090876535, 0.10595790857024777],
        "planned_cost": 74.0, "unplanned_cost": 250.0, "unit": "hours"}, A)
    assert round(oil.results["optimal_time"]) == 101

    def fixed(interval):
        return _status(session, A, {"outcome": "fixed_interval", "task": "Change oil", "interval": interval,
                                    "interval_unit": "hours",
                                    "evidence": {"type": "strategy_analysis", "id": oil.id}})

    r = fixed(25)
    assert r["status"] == "contradicted"
    assert "set every 25 hours" in r["summary"] and "about 101 hours" in r["summary"]
    assert "about 4 times as often" in r["summary"]
    assert "Optimal interval ≈ 101 hours" in r["summary"]
    assert r["interval_share"] == pytest.approx(25 / oil.results["optimal_time"], rel=1e-3)
    assert fixed(100)["status"] == "supported"
    assert fixed(60)["status"] == "supported"
    # The same check in days: 25 h is about 1 day, against 101 h (about 4.2 days).
    days = _status(session, A, {"outcome": "fixed_interval", "task": "Change oil", "interval": 1,
                                "interval_unit": "days", "evidence": {"type": "strategy_analysis", "id": oil.id}})
    assert days["status"] == "contradicted" and "set every 1 day," in days["summary"]

    pf = strategy_store.save_analysis(session, "belt", "on_condition_interval", {
        "pf_interval": 127, "pf_unit": "hours", "unit": "hours"}, A)

    def check(interval):
        return _status(session, A, {"outcome": "on_condition", "task": "Check belt", "interval": interval,
                                    "interval_unit": "hours",
                                    "evidence": {"type": "strategy_analysis", "id": pf.id}})

    r = check(25)
    assert r["status"] == "contradicted" and "set every 25 hours" in r["summary"]
    assert check(50)["status"] == "supported"
    longer = check(200)
    assert longer["status"] == "contradicted" and "longer than" in longer["summary"]


def test_fixed_interval_far_longer_than_its_cost_optimum_says_so(session):
    """The mirror of the short side: a fixed-interval task set at more than twice its
    cost-optimal age (about 101 h for the oil) reads contradicted, with both intervals;
    up to twice it stays supported."""
    from backend.services import strategy_store

    oil = strategy_store.save_analysis(session, "oil", "optimal_replacement", {
        "distribution_id": "lognormal", "params": [4.840310090876535, 0.10595790857024777],
        "planned_cost": 74.0, "unplanned_cost": 250.0, "unit": "hours"}, A)

    def fixed(interval):
        return _status(session, A, {"outcome": "fixed_interval", "task": "Change oil", "interval": interval,
                                    "interval_unit": "hours",
                                    "evidence": {"type": "strategy_analysis", "id": oil.id}})

    r = fixed(250)
    assert r["status"] == "contradicted"
    assert "set every 250 hours, far longer than the cost-optimal interval" in r["summary"]
    assert "about 101 hours: about twice as long as the evidence supports" in r["summary"]
    assert r["interval_share"] == pytest.approx(250 / oil.results["optimal_time"], rel=1e-3)
    assert "about 4 times as long" in fixed(400)["summary"]
    assert fixed(200)["status"] == "supported"  # 1.98 times: within twice
    assert fixed(150)["status"] == "supported"
