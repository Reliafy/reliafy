""""Chance a spare starts" on a standby block (RePyability 0.17's
``start_probability``): a spare that fails to start is skipped and the next
one tried, on cold, warm and hot standby alike. Until this the app sent it as a
failed switch, which ends the arrangement (``switching_probability``), and left
it out on warm and hot blocks.
"""

import pytest
import surpyval as sp
from repyability.rbd.standby_node import StandbyModel

from backend.services import rbd_analysis as ra
from backend.services import rbd_graph


def E(rate):
    return {"distribution_id": "exponential", "params": [{"name": "failure_rate", "value": rate}]}


def W(alpha, beta):
    return {"distribution_id": "weibull", "params": [{"name": "alpha", "value": alpha}, {"name": "beta", "value": beta}]}


def _series(block):
    nodes = [{"id": "input", "type": "input"}, block, {"id": "output", "type": "output"}]
    return rbd_graph.normalize_graph({"nodes": nodes, "edges": [{"source": "input", "target": block["id"]},
                                                                 {"source": block["id"], "target": "output"}],
                                      "unit": "Hours"})


def _standby(**data):
    return {"id": "s", "type": "standby", "label": "Pumps", "model": E(1e-3), "spares": 2, **data}


UNIT = sp.Exponential.from_params([1e-3])


def test_cold_spare_that_fails_to_start_is_skipped():
    # One running, two cold spares, each starting 9 times in 10: 0.881 at 1,000 h
    # (the app showed 0.848, the failed-switch answer).
    out = ra.analyze(_series(_standby(dormancy=0, cold=True, startProb=0.9)), at_times=[1000.0])
    assert out["at"]["sf"][0] == pytest.approx(0.881, abs=5e-4)
    direct = StandbyModel([UNIT] * 3, start_probability=0.9)
    assert out["at"]["sf"][0] == pytest.approx(float(direct.sf(1000.0)), rel=1e-6)


def test_warm_spares_take_the_start_chance():
    # Warm (ageing at 0.3), two spares, 0.9 start chance: 0.827 (the app showed 0.864,
    # leaving the start chance out).
    out = ra.analyze(_series(_standby(dormancy=0.3, startProb=0.9)), at_times=[1000.0])
    assert out["at"]["sf"][0] == pytest.approx(0.827, abs=5e-4)
    direct = StandbyModel([UNIT] * 3, dormancy_factor=0.3, start_probability=0.9)
    assert out["at"]["sf"][0] == pytest.approx(float(direct.sf(1000.0)), rel=1e-6)


def test_hot_spares_take_the_start_chance():
    out = ra.analyze(_series(_standby(dormancy=1, startProb=0.9)), at_times=[1000.0])
    direct = StandbyModel([UNIT] * 3, dormancy_factor=1.0, start_probability=0.9)
    assert out["at"]["sf"][0] == pytest.approx(float(direct.sf(1000.0)), rel=1e-6)
    perfect = ra.analyze(_series(_standby(dormancy=1)), at_times=[1000.0])["at"]["sf"][0]
    assert out["at"]["sf"][0] < perfect


def test_no_warning_that_the_start_chance_is_ignored():
    warnings_ = ra.validate_graph(_series(_standby(dormancy=0.5, startProb=0.9)))["warnings"]
    assert not any("start" in w.lower() for w in warnings_), warnings_


@pytest.mark.parametrize("data", [
    {"k": 2, "dormancy": 0.3},  # warm, two running: exact for exponential units since 0.17
    {"k": 3, "dormancy": 0, "cold": True, "standbyModel": E(2e-3)},  # different cold spares, three running
    {"k": 2, "dormancy": 0.3, "startProb": 0.9},
])
def test_exponential_cases_once_refused_are_now_exact(data):
    g = _series(_standby(**data))
    assert not ra.validate_graph(g)["errors"]
    out = ra.analyze(g, at_times=[500.0])
    k = data["k"]
    spare = sp.Exponential.from_params([2e-3]) if data.get("standbyModel") else UNIT
    direct = StandbyModel([UNIT] * k + [spare] * 2, k=k, dormancy_factor=data.get("dormancy", 0.0),
                          start_probability=data.get("startProb", 1.0))
    assert not direct.is_simulated
    assert out["at"]["sf"][0] == pytest.approx(float(direct.sf(500.0)), rel=1e-6)


@pytest.mark.parametrize("data, needle", [
    ({"k": 2, "dormancy": 0.3, "model": W(1000, 2)}, "warm standby with 2 units running"),
    ({"k": 3, "dormancy": 0, "cold": True, "model": W(1000, 2), "standbyModel": W(1500, 2)},
     "units that differ"),
    ({"k": 2, "dormancy": 1, "model": W(1000, 2), "startProb": 0.9}, "hot standby with 2 units running"),
])
def test_cases_the_library_still_refuses_are_said_plainly(data, needle):
    errors = ra.validate_graph(_series(_standby(**data)))["errors"]
    assert any(needle in e for e in errors), errors
