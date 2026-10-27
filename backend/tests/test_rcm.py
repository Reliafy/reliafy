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
    m.decide_failure_mode(mode["id"], decision=decision)
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

    def status_for(interval_unit):
        return _status(session, A, {
            "outcome": "fixed_interval", "task": "replace", "interval": 500,
            "interval_unit": interval_unit,
            "evidence": {"type": "strategy_analysis", "id": analysis.id},
        })

    # Definite mismatch -> inconclusive with a unit-specific reason.
    bad = status_for("km")
    assert bad["status"] == "inconclusive" and "Unit mismatch" in bad["reason"]
    # Aliases of the same unit agree.
    assert status_for("hrs")["status"] == "supported"
    assert status_for("hours")["status"] == "supported"
