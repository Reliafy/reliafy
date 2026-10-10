"""A block's model entered as its mean, and its mean and median (#299).

Checked against SurPyval called directly: the parameters found for a mean
give that mean back from SurPyval's own ``mean()``, and the echo's mean and
median are SurPyval's ``mean()`` and ``qf(0.5)``.
"""

import math

import pytest
import surpyval as sv
from fastapi.testclient import TestClient

from backend import config
from backend.services import rbd_block_inputs as bi
from backend.tests.test_mcp import env  # noqa: F401 - a fixture


def _values(out):
    return [p["value"] for p in out["params"]]


@pytest.mark.parametrize("dist_id, cls, mean, given", [
    ("exponential", sv.Exponential, 1000.0, {}),
    ("exponential", sv.Exponential, 2.5e-7, {}),
    ("weibull", sv.Weibull, 12000.0, {"beta": 1.6}),
    ("weibull", sv.Weibull, 3.0, {"beta": 0.7}),
    ("lognormal", sv.LogNormal, 13.6, {"sigma": 0.5}),
    ("normal", sv.Normal, 50000.0, {"sigma": 900.0}),
    ("gamma", sv.Gamma, 200.0, {"alpha": 2.0}),
    ("loglogistic", sv.LogLogistic, 120.0, {"beta": 3.0}),
])
def test_a_mean_gives_parameters_whose_surpyval_mean_is_that_mean(dist_id, cls, mean, given):
    out = bi.from_mean(dist_id, mean, given)
    model = cls.from_params(_values(out))
    assert float(model.mean()) == pytest.approx(mean, rel=1e-9)
    assert out["mean"] == pytest.approx(float(model.mean()), rel=1e-12)
    assert out["median"] == pytest.approx(float(model.qf(0.5)), rel=1e-12)
    # The given shape or spread is kept as entered.
    for name, value in given.items():
        assert next(p["value"] for p in out["params"] if p["name"] == name) == value


def test_the_parameters_are_in_surpyvals_order_and_names():
    out = bi.from_mean("weibull", 1000.0, {"beta": 2.0})
    assert [p["name"] for p in out["params"]] == list(sv.Weibull.parameter_names)
    assert out["params"][0]["value"] == pytest.approx(1000.0 / math.gamma(1.5), rel=1e-9)


def test_the_echo_is_surpyvals_mean_and_median():
    """The user who typed μ = ln 12 for "about 12 h": the mean is 13.6 h."""
    out = bi.summary("lognormal", [{"name": "mu", "value": math.log(12)}, {"name": "sigma", "value": 0.5}])
    model = sv.LogNormal.from_params([math.log(12), 0.5])
    assert out["mean"] == pytest.approx(float(model.mean()), rel=1e-12)
    assert out["mean"] == pytest.approx(13.6, abs=0.01)
    assert out["median"] == pytest.approx(12.0, rel=1e-6)


def test_a_mean_that_does_not_exist_is_none_not_a_number():
    out = bi.summary("loglogistic", [{"name": "alpha", "value": 100}, {"name": "beta", "value": 0.8}])
    assert out["mean"] is None and out["median"] == pytest.approx(100.0)


@pytest.mark.parametrize("args, words", [
    (("rayleigh", 100.0, {}), "enter its parameters"),
    (("weibull", -5.0, {"beta": 2}), "positive number"),
    (("weibull", 100.0, {}), "shape β"),
    (("lognormal", 100.0, {"sigma": 0}), "spread σ"),
    (("loglogistic", 100.0, {"beta": 0.9}), "above 1"),
    (("nonsense", 100.0, {}), "Unknown distribution"),
])
def test_what_cannot_be_built_is_refused_in_words(args, words):
    with pytest.raises(bi.BlockInputError, match=words):
        bi.from_mean(*args)


def test_missing_parameters_are_named():
    with pytest.raises(bi.BlockInputError, match="beta"):
        bi.summary("weibull", [{"name": "alpha", "value": 10}])


def test_the_forms_list_what_each_distribution_takes_with_its_mean():
    forms = bi.mean_entry_forms()
    assert forms["exponential"] == {"given": []}
    assert forms["weibull"] == {"given": ["beta"]} and forms["lognormal"] == {"given": ["sigma"]}


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(config, "AUTH_DISABLED", True)
    from backend.main import app

    return TestClient(app)


def test_the_endpoints(client):
    forms = client.get("/api/rbd-blocks/mean-forms").json()["forms"]
    assert "weibull" in forms
    r = client.post("/api/rbd-blocks/model", json={"distribution_id": "weibull", "mean": 12000, "given": {"beta": 1.6}})
    assert r.status_code == 200
    body = r.json()
    assert float(sv.Weibull.from_params(_values(body)).mean()) == pytest.approx(12000, rel=1e-9)
    r = client.post("/api/rbd-blocks/model", json={"distribution_id": "exponential",
                                                   "params": [{"name": "failure_rate", "value": 1e-3}]})
    assert r.json()["mean"] == pytest.approx(1000) and r.json()["median"] == pytest.approx(1000 * math.log(2))
    r = client.post("/api/rbd-blocks/model", json={"distribution_id": "rayleigh", "mean": 10})
    assert r.status_code == 422 and "parameters" in r.json()["detail"]


# ---- Agents: a block model given as its mean (create_rbd, edit_rbd) ------------------------

def test_agents_can_give_a_block_its_mean(env):  # noqa: F811 - env is a fixture
    from backend.tests.test_mcp_rbd_edit import _chain, _create, _edit, _node
    from backend.tests.test_mcp import _err, _ok

    graph = _chain("p1", "p2", model={"distribution_id": "weibull", "mean": 12000, "given": {"beta": 1.6}})
    rid = _create(env, graph)["id"]
    model = _node(env, rid, "p1")["data"]["model"]
    assert set(model) >= {"distribution_id", "params"} and "mean" not in model
    assert float(sv.Weibull.from_params(_values(model)).mean()) == pytest.approx(12000, rel=1e-9)
    # edit_rbd update_node takes the same: an exponential MTBF needs nothing else.
    _ok(_edit(env, rid, {"op": "update_node", "id": "p2", "model": {"distribution_id": "exponential", "mean": 500}}))
    assert _node(env, rid, "p2")["data"]["model"]["params"] == [{"name": "failure_rate", "value": pytest.approx(1 / 500)}]
    # A mean SurPyval can't meet is refused in words.
    bad = {"distribution_id": "weibull", "mean": 100}
    assert "shape β" in _err(_edit(env, rid, {"op": "update_node", "id": "p2", "model": bad}))
