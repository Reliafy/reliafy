"""A Bayesian-update model as an RBD block (RePyability 0.17 takes a Bayesian
fit as a life): the block is the model's posterior predictive, the curve its
own page shows, not the distribution at the parameters' middle values, and the
band draws from its posterior (a credible band)."""

import mongomock
import numpy as np
import pytest

from backend.services import bayes_life as bl
from backend.services import rbd_analysis as ra
from backend.services import rbds

OWNER = "user-bayes"


@pytest.fixture()
def db(monkeypatch):
    from backend import db as db_mod

    d = mongomock.MongoClient()["rbd_bayes"]
    monkeypatch.setattr(db_mod, "_db", d)
    return d


def _saved_update(db, base_spec, trust, x, c, name="Seal update"):
    base = bl.baseline_from(db, [OWNER], set(), base_spec)
    model, result, priors = bl.update(base, trust, bl.given_rows(x, c))
    doc = bl.save(db, OWNER, model, result, priors, name)
    res = doc.results
    block = {"source": "saved", "kind": "distribution", "modelId": doc.id, "name": doc.name,
             "distribution": res["distribution"], "distribution_id": res["distribution_id"],
             "params": res["params"]}
    return model, block


def _one_block(block, n=1):
    node = {"id": "a", "type": "component", "data": {"label": "Seal", "model": block}}
    if n > 1:
        node = {"id": "a", "type": "series", "data": {"label": "Seals", "model": block, "n": n}}
    return {"unit": "hours", "nodes": [{"id": "input", "type": "input", "data": {}}, node,
                                       {"id": "output", "type": "output", "data": {}}],
            "edges": [{"id": "e1", "source": "input", "target": "a"}, {"id": "e2", "source": "a", "target": "output"}]}


def _sf(model, t):
    return float(np.ravel(model.sf(t))[0])


def test_a_bayesian_block_is_its_models_own_curve_with_a_credible_band(db):
    # A Weibull baseline (5,000 h, shape 2) trusted only as a starting point, then two
    # failures and two survivors: the block was built from the posterior medians, which
    # put the chance of failing by 500 h well below the model page's.
    model, block = _saved_update(db, {"distribution": "weibull", "params": {"alpha": 5000, "beta": 2},
                                      "unit": "hours"}, "start", [900.0, 1500.0, 2000.0, 2500.0], [0, 0, 1, 1])
    _, resolve_model = rbds.resolvers(db, OWNER)
    out = ra.analyze(_one_block(block), resolve_model=resolve_model, at_times=[500.0, 1000.0],
                     band={"level": 0.9, "times": [500.0]})
    assert out["at"]["sf"][0] == pytest.approx(_sf(model, 500.0), rel=1e-6)
    assert out["at"]["sf"][1] == pytest.approx(_sf(model, 1000.0), rel=1e-6)
    band = out["band"]
    assert [b["id"] for b in band["uncertain"]] == ["a"] and not band["fixed"]
    assert band["kind"] == "credible"
    at = band["targets"]["reliability"][0]
    assert at["lower"] < out["at"]["sf"][0] < at["upper"]

    # Ten in series multiply the gap: the series block takes the same curve.
    series = ra.analyze(_one_block(block, n=10), resolve_model=resolve_model, at_times=[1000.0])
    assert series["at"]["sf"][0] == pytest.approx(_sf(model, 1000.0) ** 10, rel=1e-6)


def test_an_exponential_update_with_a_huge_scale_stays_finite(db):
    # A library-style rate (1e-8 per hour) trusted closely: a gamma posterior whose closed-form
    # predictive (a Lomax) overflows if worked out in plain floats.
    model, block = _saved_update(db, {"distribution": "exponential", "params": {"failure_rate": 1e-8},
                                      "unit": "hours"}, "close", [5000.0, 8000.0], [1, 1], name="Valve update")
    _, resolve_model = rbds.resolvers(db, OWNER)
    out = ra.analyze(_one_block(block), resolve_model=resolve_model, at_times=[1e5, 1e7])
    expected = [_sf(model, 1e5), _sf(model, 1e7)]
    assert all(np.isfinite(v) and 0 < v < 1 for v in out["at"]["sf"])
    assert out["at"]["sf"] == pytest.approx(expected, rel=1e-6)


def test_an_ordinary_saved_fit_is_still_built_from_its_parameters(db):
    # Only a Bayesian update changes: a block whose saved model can't be found keeps its numbers.
    block = {"source": "saved", "kind": "distribution", "modelId": "gone", "distribution_id": "weibull",
             "params": [{"name": "alpha", "value": 1000.0}, {"name": "beta", "value": 2.0}]}
    _, resolve_model = rbds.resolvers(db, OWNER)
    out = ra.analyze(_one_block(block), resolve_model=resolve_model, at_times=[500.0])
    assert out["at"]["sf"][0] == pytest.approx(np.exp(-(0.5 ** 2)), rel=1e-9)


def test_a_bayesian_block_in_a_repairable_diagram(db):
    model, block = _saved_update(db, {"distribution": "weibull", "params": {"alpha": 5000, "beta": 2},
                                      "unit": "hours"}, "start", [900.0, 1500.0, 2000.0, 2500.0], [0, 0, 1, 1])
    graph = _one_block(block)
    graph["repairable"] = True
    graph["nodes"][1]["data"]["repair"] = {"distribution_id": "exponential",
                                           "params": [{"name": "failure_rate", "value": 0.1}]}
    _, resolve_model = rbds.resolvers(db, OWNER)
    rbd, *_ = ra._build_repairable_rbd(graph, resolve_model=resolve_model)
    comp = rbd._init_args["components"]["a"]
    life = comp["reliability"] if isinstance(comp, dict) else comp.reliability
    assert float(np.ravel(life.sf(500.0))[0]) == pytest.approx(_sf(model, 500.0), rel=1e-6)
