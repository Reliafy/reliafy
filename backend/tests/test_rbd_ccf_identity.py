"""A block entered as its mean joins a common-cause group with a block typed
as the same parameters, and a group whose members differ fails the check.

RePyability compares a repairable common-cause group's members exactly (their
saved models), so "Mean 1,000,000 h" must give λ = 1e-6, not 1.0000000000000004e-6,
and Validate must say what Calculate would refuse rather than "Valid".
"""

import math

import pytest
import surpyval as sv
from fastapi.testclient import TestClient

from backend import config
from backend.services import rbd_analysis as ra
from backend.services import rbd_block_inputs as bi
from backend.services import rbd_graph


@pytest.mark.parametrize("mean", [1e6, 1000.0, 26280.0, 3.0, 2.5e-7, 8760.0 * 7])
def test_an_exponential_mean_gives_the_rate_one_over_it_exactly(mean):
    out = bi.from_mean("exponential", mean)
    assert out["params"] == [{"name": "failure_rate", "value": 1.0 / mean}]
    # SurPyval's own mean of that rate is the mean.
    assert float(sv.Exponential.from_params([1.0 / mean]).mean()) == pytest.approx(mean, rel=1e-12)


def test_a_mean_of_a_million_hours_is_a_rate_of_one_in_a_million():
    assert bi.from_mean("exponential", 1_000_000)["params"][0]["value"] == 1e-6


def test_a_normal_mean_is_its_mu():
    out = bi.from_mean("normal", 50000.0, {"sigma": 900.0})
    assert out["params"] == [{"name": "mu", "value": 50000.0}, {"name": "sigma", "value": 900.0}]


def _sig_figs(value: float) -> int:
    digits = repr(float(value)).lower().split("e")[0].replace("-", "").replace(".", "").lstrip("0")
    return len(digits.rstrip("0")) or 1


@pytest.mark.parametrize("dist_id, cls, mean, given", [
    ("weibull", sv.Weibull, 1e6, {"beta": 1.5}),
    ("weibull", sv.Weibull, 3.0, {"beta": 0.7}),
    ("lognormal", sv.LogNormal, 13.6, {"sigma": 0.5}),
    ("gamma", sv.Gamma, 200.0, {"alpha": 2.5}),
    ("loglogistic", sv.LogLogistic, 120.0, {"beta": 3.0}),
])
def test_a_solved_parameter_is_kept_to_twelve_significant_figures(dist_id, cls, mean, given):
    out = bi.from_mean(dist_id, mean, given)
    solved = next(p["value"] for p in out["params"] if p["name"] not in given)
    assert _sig_figs(solved) <= bi.SOLVED_SIG_FIGS
    # Still SurPyval's model with that mean.
    model = cls.from_params([p["value"] for p in out["params"]])
    assert float(model.mean()) == pytest.approx(mean, rel=1e-9)
    # The same mean always gives the same parameter.
    assert bi.from_mean(dist_id, mean, given)["params"] == out["params"]


def test_a_round_answer_stays_round():
    # A Weibull with β = 1 is an exponential: its scale is the mean.
    assert bi.from_mean("weibull", 1000.0, {"beta": 1.0})["params"][0]["value"] == 1000.0


# ---- The diagram: two shutdown valves in one common-cause group -----------------------------

def _valve(nid, model):
    return {"id": nid, "type": "component", "position": {"x": 0, "y": 0},
            "data": {"label": nid, "instant_repair": True, "inspection": {"interval": 8760}, "model": model}}


def _sif(model_b):
    typed = {"source": "params", "distribution_id": "exponential", "distribution": "Exponential",
             "params": [{"name": "failure_rate", "value": 1e-6}]}
    nodes = [{"id": "input", "type": "input", "data": {}, "position": {"x": 0, "y": 0}},
             _valve("Valve A", typed), _valve("Valve B", model_b),
             {"id": "output", "type": "output", "data": {}, "position": {"x": 0, "y": 0}}]
    edges = [{"id": f"e{i}", "source": s, "target": t} for i, (s, t) in enumerate(
        [("input", "Valve A"), ("input", "Valve B"), ("Valve A", "output"), ("Valve B", "output")])]
    return {"unit": "Hours", "repairable": True, "safety_function": True, "nodes": nodes, "edges": edges,
            "ccf_groups": [{"id": "valves", "members": ["Valve A", "Valve B"], "beta": 0.1}]}


def _mean_entered(mean):
    """Valve B as the block dialog saves a "Mean" entry: the parameters it made."""
    params = bi.from_mean("exponential", mean)["params"]
    return {"source": "params", "distribution_id": "exponential", "distribution": "Exponential", "params": params}


def test_a_mean_entered_block_joins_a_group_with_a_typed_one():
    graph = _sif(_mean_entered(1_000_000))
    check = ra.validate_graph(graph)
    assert check["valid"] and check["can_calculate"], check["errors"]
    rbd, *_ = ra._build_repairable_rbd(graph)  # RePyability accepts the group
    assert len(rbd.ccf_groups) == 1


def test_an_agents_mean_joins_the_group_too():
    # create_rbd / edit_rbd take {distribution_id, mean}: the same conversion.
    model = rbd_graph.normalize_model({"distribution_id": "exponential", "mean": 1_000_000}, "Valve B")
    assert model["params"] == [{"name": "failure_rate", "value": 1e-6}]
    assert ra.validate_graph(_sif(model))["valid"]


def test_validate_refuses_a_group_whose_members_differ_as_calculate_does():
    # A rate a hair off 1e-6 (as a mean once gave): RePyability refuses the group.
    off = {"source": "params", "distribution_id": "exponential", "distribution": "Exponential",
           "params": [{"name": "failure_rate", "value": 1.0000000000000004e-06}]}
    graph = _sif(off)
    check = ra.validate_graph(graph)
    assert not check["valid"] and not check["can_calculate"]
    assert len(check["errors"]) == 1
    message = check["errors"][0]
    assert "common-cause group" in message and "“Valve A”" in message and "“Valve B”" in message
    assert "CCF" not in message  # plain words
    with pytest.raises(ra.AnalysisError) as refused:
        ra._build_repairable_rbd(graph)
    assert str(refused.value) == message


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(config, "AUTH_DISABLED", True)
    from backend.main import app

    return TestClient(app)


def test_the_block_dialog_endpoint_and_the_analysis_agree(client):
    r = client.post("/api/rbd-blocks/model", json={"distribution_id": "exponential", "mean": 1_000_000})
    assert r.status_code == 200 and r.json()["params"] == [{"name": "failure_rate", "value": 1e-6}]
    model = {"source": "params", "distribution_id": "exponential", "distribution": "Exponential",
             "params": r.json()["params"]}
    graph = _sif(model)
    assert client.post("/api/rbds/validate", json={"graph": graph}).json()["valid"] is True
    analysed = client.post("/api/rbds/analyze", json={"graph": graph})
    assert analysed.status_code == 200, analysed.text
    assert math.isfinite(analysed.json()["steady_state_availability"])
    # A group whose members differ: the check and the calculation say the same.
    graph["nodes"][2]["data"]["model"]["params"][0]["value"] = 2e-6
    check = client.post("/api/rbds/validate", json={"graph": graph}).json()
    assert check["valid"] is False
    refused = client.post("/api/rbds/analyze", json={"graph": graph})
    assert refused.status_code == 422 and refused.json()["detail"] == check["errors"][0]
