"""Fit a life model to a position (fit_life.py): which data (this position, the class, both) and
which method (a plain fit, or with a prior). The class's history as a power prior is SurPyval's
prior.from_data, the same as calling SurPyval directly; the class is never both data and prior;
a plain fit says confidence, a fit with a prior says credible."""

from datetime import date, timedelta

import mongomock
import numpy as np
import pytest
import surpyval as sp

from backend.maintenance import fit_life
from backend.maintenance import position_models as pm
from backend.maintenance.service import PROJECTORS, Invalid, Maintenance
from backend.maintenance.store import GraphStore

ORG = "org-fit"
OWNERS = [ORG, "__samples__"]


@pytest.fixture()
def m():
    return Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")


@pytest.fixture()
def db(monkeypatch):
    from backend import db as db_mod
    from backend.services import samples

    d = mongomock.MongoClient()["fit_life"]
    samples.seed_samples(d)
    monkeypatch.setattr(db_mod, "_db", d)
    return d


def _history(m, pid, lives, start=date(2018, 1, 1), running=True):
    on = start
    for i, life in enumerate(lives):
        m.fit(pid, new_item={"name": f"U{pid[-4:]}-{i}"}, on=on.isoformat())
        on = on + timedelta(days=life)
        m.remove(pid, on=on.isoformat(), reason="failure")
    if running:
        m.fit(pid, new_item={"name": f"U{pid[-4:]}-run"}, on=on.isoformat())


def _plant(m):
    """Three pumps of one class: two with history, one (the one fitted) with a single failure."""
    a = m.create_position("Pump A", position_class="Slurry pump")["id"]
    b = m.create_position("Pump B", position_class="Slurry pump")["id"]
    new = m.create_position("Pump C", position_class="Slurry pump")["id"]
    _history(m, a, [300, 420, 380, 510])
    _history(m, b, [350, 460, 330])
    _history(m, new, [200])
    return new


def test_the_class_history_as_a_power_prior_is_surpyvals(m, db):
    new = _plant(m)
    got = fit_life.fit(m, db, OWNERS, set(), new, data="both", trust="close")  # weight 1: no wide priors
    assert got["method"] == "bayes" and got["interval_label"] == "90% credible interval"
    # SurPyval directly: this pump's rows as the data, the other pumps' as the prior.
    own = [r for r in m.life_data(new)]
    others = [r for r in m.class_life_data("Slurry pump")["rows"] if r["position_id"] != new]
    xo, co = np.array([r["x"] for r in own], float), np.array([r["c"] for r in own])
    xc, cc = np.array([r["x"] for r in others], float), np.array([r["c"] for r in others])
    direct = sp.Weibull.fit_bayes(xo, c=co, priors=sp.prior.from_data(xc, c=cc, weight=1.0))
    post = {p["name"]: p["median"] for p in got["posterior"]}
    assert post["alpha"] == pytest.approx(direct.params[0], rel=0.01)
    assert post["beta"] == pytest.approx(direct.params[1], rel=0.02)
    assert "counted as all of its evidence" in got["label"] and "2 other positions" in got["label"]
    # As a guide (half the evidence): wider, and the wide priors it needed are said.
    half = fit_life.fit(m, db, OWNERS, set(), new, data="both", trust="guide")
    a1 = next(p for p in got["posterior"] if p["name"] == "alpha")
    a2 = next(p for p in half["posterior"] if p["name"] == "alpha")
    assert a2["upper"] - a2["lower"] > a1["upper"] - a1["lower"]
    assert "factor of 20" in half["words"]


def test_the_data_choices_and_the_labels(m, db):
    new = _plant(m)
    own = fit_life.fit(m, db, OWNERS, set(), new, data="position", method="mle", distribution="exponential")
    assert own["interval_label"] == "95% confidence bounds" and own["counts"]["failures"] == 1
    with pytest.raises(Invalid, match="a plain weibull fit needs at least 2"):
        fit_life.fit(m, db, OWNERS, set(), new, data="position", method="mle")
    pooled = fit_life.fit(m, db, OWNERS, set(), new, data="class", method="mle")
    assert pooled["counts"]["failures"] == 8 and "confidence" in pooled["words"]
    assert pooled["class_history"] == {"name": "Slurry pump", "positions": 3, "failures": 8, "suspensions": 3}
    with pytest.raises(Invalid, match="count it twice"):
        fit_life.fit(m, db, OWNERS, set(), new, data="class", method="bayes", prior={"kind": "class"})
    with_model = fit_life.fit(m, db, OWNERS, set(), new, data="class", method="bayes",
                              prior={"kind": "params", "distribution": "weibull", "unit": "days",
                                     "params": [{"name": "alpha", "value": 400}, {"name": "beta", "value": 3}]})
    assert with_model["interval_label"] == "90% credible interval" and with_model["counts"]["failures"] == 8
    with pytest.raises(Invalid, match="Best of"):
        fit_life.fit(m, db, OWNERS, set(), new, method="bayes", distribution="best")


def test_both_with_no_class_history_refuses_in_words(m, db):
    lone = m.create_position("Odd pump")["id"]
    _history(m, lone, [200])
    with pytest.raises(Invalid, match="no class history to use: it has no position class"):
        fit_life.fit(m, db, OWNERS, set(), lone, data="both")
    only = m.create_position("Only pump", position_class="Unique pump")["id"]
    _history(m, only, [200])
    with pytest.raises(Invalid, match="no history besides Only pump's own"):
        fit_life.fit(m, db, OWNERS, set(), only, data="both")


def test_saving_a_plain_fit_and_a_fit_with_a_prior(m, db):
    new = _plant(m)
    plain = fit_life.fit(m, db, OWNERS, set(), new, data="class", method="mle", save=True)
    assert plain["role"] == "fitted" and plain["source"]["scope"] == "class" and plain["fit"]["method"] == "mle"
    bayes = fit_life.fit(m, db, OWNERS, set(), new, data="both", trust="guide", save=True)
    assert bayes["role"] == "bayesian" and bayes["fit"]["interval_label"] == "90% credible interval"
    # Update with new failures… keeps working: the saved recipe (the power prior) is rebuilt.
    m.remove(new, on=(date(2018, 1, 1) + timedelta(days=350)).isoformat(), reason="failure")  # the running one fails
    again = pm.bayes_position(m, db, OWNERS, set(), new, {"model_id": bayes["model_id"]})
    assert again["counts"]["failures"] == 2 and again["trust"]["id"] == "kept"
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before
