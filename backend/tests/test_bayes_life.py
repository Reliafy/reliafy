"""A Bayesian update of a baseline with a few failures (backend/services/bayes_life.py, on
SurPyval 0.26's fit_bayes): flat priors and plenty of data give the maximum-likelihood fit;
no data leaves the baseline as given; one early failure pulls the life in; a saved update
is a normal saved model that rebuilds from its recipe; the position flow saves and attaches."""

from datetime import date, timedelta

import mongomock
import numpy as np
import pytest
import surpyval as sp

from backend.maintenance import position_models as pm
from backend.maintenance.service import PROJECTORS, Invalid, Maintenance
from backend.maintenance.store import GraphStore
from backend.services import bayes_life as bl

ORG = "org-bayes"
OWNERS = [ORG, "__samples__"]


@pytest.fixture()
def db(monkeypatch):
    from backend import db as db_mod
    from backend.services import samples

    d = mongomock.MongoClient()["bayes_life"]
    samples.seed_samples(d)
    monkeypatch.setattr(db_mod, "_db", d)  # a saved model's refit reads the app's database
    return d


def test_surpyval_is_the_version_with_bayesian_fitting():
    from importlib.metadata import version

    assert tuple(int(p) for p in version("surpyval").split(".")[:2]) >= (0, 26)


def test_flat_priors_and_plenty_of_data_give_the_mle():
    x = sp.Weibull.random(300, 2000, 1.8, random_state=7)
    rows = bl.given_rows(x.tolist(), [0] * len(x))
    xs, cs = bl.arrays(rows)
    model = bl._fit("weibull", xs, cs, {"alpha": sp.prior.flat(), "beta": sp.prior.flat()}, "hours")
    mle = sp.Weibull.fit(x)
    assert model.params[0] == pytest.approx(mle.alpha, rel=0.01)
    assert model.params[1] == pytest.approx(mle.beta, rel=0.02)


def test_no_data_leaves_the_baseline_as_given():
    base = {"source": "params", "name": "OEM", "distribution": "weibull", "unit": "hours",
            "params": {"alpha": 3000.0, "beta": 2.0}}
    model, result, _ = bl.update(base, "guide", [])
    assert model is None and result["can_save"] is False
    post = {p["name"]: p for p in result["posterior"]}
    assert post["alpha"]["median"] == pytest.approx(3000, rel=1e-6)
    assert post["beta"]["median"] == pytest.approx(2.0, rel=1e-6)
    # "Use it as a guide": each within about 30% (90% of the prior between).
    assert post["alpha"]["lower"] == pytest.approx(3000 / 1.3, rel=0.02)
    assert post["alpha"]["upper"] == pytest.approx(3000 * 1.3, rel=0.02)
    assert "stands as given" in result["words"]


def test_an_early_failure_pulls_the_life_in_and_the_result_says_so():
    base = {"source": "params", "name": "the class model", "distribution": "weibull", "unit": "hours",
            "params": {"alpha": 3000.0, "beta": 2.0}}
    rows = bl.given_rows([1400, 1900, 800, 800], [0, 0, 1, 1])
    model, result, _ = bl.update(base, "start", rows, age=1000)
    post = {p["name"]: p for p in result["posterior"]}
    assert post["alpha"]["median"] < 3000
    assert post["alpha"]["lower"] < post["alpha"]["median"] < post["alpha"]["upper"]
    assert result["counts"] == {"failures": 2, "suspensions": 2}
    assert result["moved"].startswith("2 failures at 1,400 and 1,900 hours pulled the characteristic life from 3,000")
    assert "90% chance it lies between" in result["words"] and "confidence" not in result["words"]
    assert 0 < result["at_age"]["lower"] < result["at_age"]["reliability"] < result["at_age"]["upper"] < 1
    c = result["curves"]
    assert len(c["x"]) == bl.GRID and c["baseline_sf"][0] == pytest.approx(1)
    # Trusting the baseline closely moves it less.
    _, close, _ = bl.update(base, "close", rows)
    assert {p["name"]: p for p in close["posterior"]}["alpha"]["median"] > post["alpha"]["median"]


def test_a_b10_belief_is_a_baseline_too():
    base = bl.baseline_from(None, OWNERS, set(), {"b10": {"value": 5000, "low": 3000, "high": 8000},
                                                 "shape": {"low": 1.2, "high": 4}, "unit": "hours"})
    _, result, _ = bl.update(base, "guide", [])
    b10 = next(p for p in result["prior"] if p["name"] == "B10")
    assert b10["lower"] == pytest.approx(3000, rel=0.05) and b10["upper"] == pytest.approx(8000, rel=0.05)


def test_a_saved_update_is_a_normal_model_that_rebuilds(db):
    from backend.services import models as models_service

    base = bl.baseline_from(db, OWNERS, set(), {"model_id": "sample-model-bearings-weibull"})
    assert base["source"] == "model" and base["live"] is not None  # its fit: from_model
    rows = bl.given_rows([300.0, 900.0], [0, 1])
    model, result, priors = bl.update(base, "guide", rows)
    doc = bl.save(db, ORG, model, result, priors)
    assert doc.name.startswith("Bayesian update of Bearing life") and doc.name.endswith("1 failure, 1 suspension")
    saved = models_service.get_model(db, doc.id, OWNERS)
    assert saved.results["method"] == "bayesian_update" and saved.results["params"][0]["ci"][0] is not None
    public = models_service.public_results(saved)
    assert "confidence_path" not in public["functions"] and "credible" in public["functions"]["bands_note"]
    # The calculator's live model is the rebuilt posterior: its reliability matches the saved curve.
    out = models_service.evaluate_at(db, saved, [500.0], OWNERS)
    assert out is not None
    live = bl.rebuild(saved.spec)
    assert float(np.ravel(live.sf(500.0))[0]) == pytest.approx(float(np.ravel(model.sf(500.0))[0]), rel=1e-6)
    # An update of an update keeps the earlier prior and takes the new history.
    again = bl.baseline_from(db, OWNERS, set(), {"model_id": doc.id})
    assert again["source"] == "update"
    _, r2, _ = bl.update(again, "guide", bl.given_rows([300.0, 700.0, 900.0], [0, 0, 1]))
    assert r2["counts"]["failures"] == 2 and r2["trust"]["id"] == "kept"


def test_the_position_flow_previews_saves_and_attaches(db):
    m = Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")
    pump = m.create_position("Pump A")["id"]
    start = date(2023, 1, 1)
    m.fit(pump, new_item={"name": "P1"}, on=start.isoformat())
    m.remove(pump, on=(start + timedelta(days=60)).isoformat(), reason="failure")
    m.fit(pump, new_item={"name": "P2"}, on=(start + timedelta(days=60)).isoformat())
    with pytest.raises(Invalid, match="no class model"):
        pm.bayes_position(m, db, OWNERS, set(), pump)
    preview = pm.bayes_position(m, db, OWNERS, set(), pump, {"model_id": "sample-model-bearings-weibull"})
    assert preview["counts"]["failures"] == 1 and preview["rows"][0]["x"] == pytest.approx(60 * 24)  # hours
    one = preview["rows"][0]["fitment_id"]
    without = pm.bayes_position(m, db, OWNERS, set(), pump, {"model_id": "sample-model-bearings-weibull"}, exclude=[one])
    assert without["counts"]["failures"] == 0
    link = pm.bayes_position(m, db, OWNERS, set(), pump, {"model_id": "sample-model-bearings-weibull"}, save=True)
    assert link["role"] == "bayesian" and pm.source_text(link).startswith("Bayesian update of Bearing life")
    [row] = pm.describe(m, db, OWNERS, set(), m.position_models(pump))
    assert row["model"]["kind"] == "Weibull (Bayesian)" and row["model"]["quality"]["word"] == "Bayesian"
    assert {n["id"] for n in row["model"]["numbers"]} >= {"char_life", "shape", "mean", "b10"}
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before


def test_a_unit_of_use_baseline_refuses_the_position_history():
    with pytest.raises(bl.BayesError, match="unit of use"):
        bl.time_factor("cycles")
