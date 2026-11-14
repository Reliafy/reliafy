"""A Bayesian-update block in the diagram downloads (Python and RePyability JSON): the
download is the model's posterior predictive, refitted from the history and prior saved
with it, so it gives the screen's numbers, not the distribution at the parameters'
middle values."""

import json

import matplotlib

matplotlib.use("Agg")

import mongomock  # noqa: E402
import numpy as np  # noqa: E402
import pytest  # noqa: E402

from backend.services import rbd_analysis as ra  # noqa: E402
from backend.services import rbds  # noqa: E402
from backend.tests.test_rbd_bayesian_blocks import _one_block, _saved_update  # noqa: E402
from backend.tests.test_rbd_export import _run  # noqa: E402

OWNER = "user-bayes"


@pytest.fixture()
def db(monkeypatch):
    from backend import db as db_mod

    d = mongomock.MongoClient()["rbd_bayes_export"]
    monkeypatch.setattr(db_mod, "_db", d)
    return d


def _weibull_update(db):
    # A Weibull baseline (5,000 h, shape 2) trusted only as a starting point, then two
    # failures and two survivors.
    return _saved_update(db, {"distribution": "weibull", "params": {"alpha": 5000, "beta": 2},
                              "unit": "hours"}, "start", [900.0, 1500.0, 2000.0, 2500.0], [0, 0, 1, 1])


def _app(db, graph):
    _, resolve_model = rbds.resolvers(db, OWNER)
    return ra.analyze(graph, resolve_model=resolve_model)


def test_the_python_download_reproduces_a_bayesian_blocks_curve(db, tmp_path):
    model, block = _weibull_update(db)
    graph = _one_block(block)
    app = _app(db, graph)
    _, code = rbds.export_python(db, "Seal", graph, OWNER)
    assert "fit_bayes(" in code and "PosteriorPredictive(" in code
    assert max(len(line) for line in code.splitlines()) <= 79
    res, _ = _run(code, tmp_path)

    # The same time axis and the same R(t): the predictive's, not the middle values'.
    assert res["t_max"] == pytest.approx(app["time"][-1], rel=1e-9)
    np.testing.assert_allclose(res["curve"]["sf"], app["system"]["sf"], atol=1e-9)
    for t, r in res["reliability"].items():
        assert r == pytest.approx(float(np.ravel(model.sf(float(t)))[0]), abs=1e-9)
    assert res["mttf"] == pytest.approx(app["mttf"], rel=1e-6)

    # The middle values' curve is a different one (what the download wrote before).
    mid = {p["name"]: p["value"] for p in block["params"]}
    t = float(next(iter(res["reliability"])))
    middle = float(np.exp(-((t / mid["alpha"]) ** mid["beta"])))
    assert abs(res["reliability"][next(iter(res["reliability"]))] - middle) > 1e-3


def test_a_count_block_on_a_bayesian_model(db, tmp_path):
    # A count block's time axis is a small Monte-Carlo mean in the app, so compare R(t) on the
    # script's own axis with the app's diagram.
    model, block = _weibull_update(db)
    graph = _one_block(block, n=3)
    _, code = rbds.export_python(db, "Seals", graph, OWNER)
    res, _ = _run(code, tmp_path, name="seals.py")
    _, resolve_model = rbds.resolvers(db, OWNER)
    rbd, *_ = ra._build_rbd(graph, resolve_model=resolve_model)
    t = np.array(res["curve"]["t"])
    np.testing.assert_allclose(res["curve"]["sf"], rbd.sf(t), atol=1e-12)
    np.testing.assert_allclose(res["curve"]["sf"], np.ravel(model.sf(t)) ** 3, atol=1e-9)


def test_an_exponential_update_with_a_huge_scale_downloads_finite(db, tmp_path):
    # A gamma posterior whose predictive (a Lomax) overflows in plain floats: RePyability's
    # closed form keeps it finite, in the script as in the app.
    _, block = _saved_update(db, {"distribution": "exponential", "params": {"failure_rate": 1e-8},
                                  "unit": "hours"}, "close", [5000.0, 8000.0], [1, 1], name="Valve update")
    graph = _one_block(block)
    app = _app(db, graph)
    _, code = rbds.export_python(db, "Valve", graph, OWNER)
    res, _ = _run(code, tmp_path, name="valve.py")
    assert all(np.isfinite(res["curve"]["sf"]))
    np.testing.assert_allclose(res["curve"]["sf"], app["system"]["sf"], atol=1e-9)


def test_the_json_download_holds_the_posterior_predictive(db):
    from repyability.rbd.serialisation import rbd_from_json

    model, block = _weibull_update(db)
    graph = _one_block(block)
    _, text = rbds.export_json(db, "Seal", graph, OWNER)
    loaded = rbd_from_json(json.loads(text) if not isinstance(text, str) else text)
    for t in (500.0, 1000.0, 3000.0):
        assert float(np.ravel(loaded.sf(t))[0]) == pytest.approx(float(np.ravel(model.sf(t))[0]), rel=1e-6)


def test_a_bayesian_block_whose_recipe_is_gone_keeps_its_parameters(db, tmp_path):
    # A saved model that can no longer be read: the block's own parameters, as the app does.
    _, block = _weibull_update(db)
    block = {**block, "modelId": "gone"}
    graph = _one_block(block)
    _, code = rbds.export_python(db, "Seal", graph, OWNER)
    assert "fit_bayes(" not in code and "surv.Weibull.from_params(" in code
