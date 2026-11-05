"""The RePyability internals Reliafy uses, through ``repy_compat`` (and the
few that "Download as Python" copies into its scripts): each still exists
and gives what the app reads, so a library release that moves one fails
here rather than turning a figure blank in production."""

import importlib

import numpy as np
import pytest
import surpyval as sv
from repyability import FaultTree, RepairableRBD
from repyability.rbd.helper_classes import PerfectReliability

from backend.services import rbd_analysis as ra
from backend.services import repy_compat
from backend.services.rbd_fault_tree import fault_tree
from backend.tests.test_rbd_large_diagrams import _bridge


def _pumps(life=None, **extra) -> RepairableRBD:
    """A motor feeding two pumps in parallel, the pumps' repairs priced."""
    life = life or sv.Weibull.from_params([900.0, 1.2])
    repair = sv.Exponential.from_params([0.5])
    spec = {"reliability": life, "repairability": repair, "repair_cost": 100.0}
    edges = [("in", "m"), ("m", "a"), ("m", "b"), ("a", "out"), ("b", "out")]
    motor = {"reliability": sv.Exponential.from_params([1 / 2000]), "repairability": sv.Exponential.from_params([0.5])}
    return RepairableRBD(edges, {"in": PerfectReliability, "out": PerfectReliability, "m": motor,
                                 "a": dict(spec), "b": dict(spec)}, **extra)


# The private names the exported scripts import themselves (rbd_ccf).
SCRIPT_NAMES = {
    "repyability.rbd._ccf_groups": ("_require_free_members", "_require_ccf_long_run", "_require_groups_over_time",
                                    "_require_groups_simulated", "_require_ccf_frequencies"),
    "repyability.rbd._model_utils": ("parametric_spec",),
}


@pytest.mark.parametrize("module", sorted(SCRIPT_NAMES))
def test_the_names_scripts_import_are_there(module):
    mod = importlib.import_module(module)
    for name in SCRIPT_NAMES[module]:
        assert callable(getattr(mod, name)), f"{module}.{name}"


def test_every_helper_reaches_its_function():
    # One crew: its chain needs constant failure rates.
    rbd = _pumps(sv.Exponential.from_params([1 / 900]), repair_crews=1)
    availability = rbd.node_availability()
    failures, maintained = repy_compat.node_actions(rbd, "a", availability["a"])
    assert failures > 0 and maintained == 0.0
    assert sorted(map(str, repy_compat.crew_served(rbd))) == ["a", "b", "m"]
    probabilities, weights = repy_compat.chain_probabilities(rbd, set(), set())
    assert set(probabilities) >= {"a", "b", "m"} and np.isclose(np.sum(weights), 1.0)
    assert repy_compat.entropy_of(7) == repy_compat.entropy_of(7)
    reduction, sink = repy_compat.modular_reduction()
    assert isinstance(reduction, type) and sink is not None


def test_a_raw_run_gives_a_tally():
    rbd = _pumps()
    tally = repy_compat.run_simulations(rbd, 1000.0, set(), set(), "c", 20, False, None,
                                        entropy=repy_compat.entropy_of(3), common=True)
    assert len(tally.uptimes) == 20 and all(0 <= u <= 1000.0 for u in tally.uptimes)


def test_block_cycle_of_a_block_replaced_component():
    life = sv.Weibull.from_params([1000.0, 3.0])
    spec = {"reliability": life, "repairability": sv.Exponential.from_params([0.5]),
            "preventive": {"interval": 400.0, "duration": sv.Exponential.from_params([1.0]), "policy": "block"}}
    rbd = RepairableRBD([("in", "c"), ("c", "out")], {"in": PerfectReliability, "out": PerfectReliability, "c": spec})
    cycle = repy_compat.block_cycle(rbd, "c")
    assert 0 < cycle.before <= 400.0


def test_parametric_spec_rebuilds_a_limited_failure_model():
    """Since 0.14 the spec carries the limited-failure share: rebuilt with
    ``build``, never ``cls.from_params(params, **extras)``."""
    model = sv.Weibull.from_params([100.0, 2.0], lfp_p=0.3)
    spec = repy_compat.parametric_spec(model)
    assert spec.cls is sv.Weibull and list(spec.names)[:2] == ["alpha", "beta"]
    rebuilt = spec.build(list(spec.params))
    t = np.array([10.0, 100.0, 1e4])
    assert np.allclose(rebuilt.sf(t), model.sf(t))
    assert repy_compat.parametric_spec("a name") is None and repy_compat.parametric_spec(None) is None


# ---- Fault-tree importance: never dropped in silence --------------------------------

def test_fault_tree_conditioning_reads_the_top_event_and_both_conditionals():
    rbd, *_ = ra._build_rbd(_bridge())
    tree = FaultTree.from_rbd(rbd)
    top, occurred, not_occurred = repy_compat.fault_tree_conditioned(tree, 300.0)
    birnbaum = tree.birnbaum_importance(300.0)
    assert float(np.ravel(top)[0]) == pytest.approx(float(np.ravel(tree.ff(300.0))[0]), rel=1e-12)
    for e in tree.events:
        assert float(occurred[e][0] - not_occurred[e][0]) == pytest.approx(float(birnbaum[e]), rel=1e-9)


def test_every_event_has_every_importance_measure():
    """The measures come from one conditioning pass: a change in what it
    returns once left every event's importance empty, with no error."""
    res = fault_tree(_bridge(), t=300.0)
    measures = {"birnbaum", "criticality", "risk_achievement_worth", "risk_reduction_worth", "fussell_vesely"}
    assert res["events"]
    for e in res["events"]:
        assert set(e["importance"]) == measures, e["id"]
        assert all(v is not None and np.isfinite(v) for v in e["importance"].values()), e["id"]


def test_a_failed_importance_pass_is_logged(monkeypatch, caplog):
    def broken(tree, t):
        raise TypeError("changed")

    monkeypatch.setattr(repy_compat, "fault_tree_conditioned", broken)
    with caplog.at_level("ERROR"):
        res = fault_tree(_bridge(), t=300.0)
    assert "Fault-tree importance measures failed" in caplog.text
    # The tree, cut sets and Fussell-Vesely still stand.
    assert all("fussell_vesely" in e["importance"] for e in res["events"])
