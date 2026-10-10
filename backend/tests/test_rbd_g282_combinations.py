"""The #282 features together: what each does with the others' block options.

- A mixture life with a capacity is priced exactly, as RePyability gives it.
- A block repaired imperfectly (Kijima) has no exact long-run values, so the
  exact-only production availability and target allocation say so plainly.
- A common-cause group (beta or MGL) keeps its members out of a repairable
  allocation, and a non-repairable one is refused, the same either way.
- A phased mission follows a block's covariate schedule, and says so.
- A network is refused by every availability route and by the quote.
- The quote counts a k-of-n standby group's running units.
"""

import copy

import numpy as np
import pytest
import surpyval as sp
from repyability import RepairableRBD

from backend import fitting
from backend.services import rbd_allocation, rbd_analysis, rbd_capacity, rbd_graph, rbd_phases
from backend.services import runtime_quote
from backend.services.rbd_analysis import AnalysisError
from backend.tests import test_rbd_tvc as tvc
from backend.tests.test_rbd_block_options import MIX, _mixture
from backend.tests.test_rbd_capacity import CAPS, EDGES, RATES, _plant


def _exp(rate):
    return {"source": "params", "distribution_id": "exponential", "params": [{"name": "failure_rate", "value": rate}]}


def _three(repairable=True, ccf=None, **extra):
    """Three exponential blocks in parallel; ``extra[id]`` adds to a block's data."""
    nodes = [{"id": "input", "type": "input", "data": {}}, {"id": "output", "type": "output", "data": {}}]
    for i in "abc":
        data = {"label": i.upper(), "model": _exp(0.001)}
        if repairable:
            data["repair"] = _exp(0.1)
        data.update(extra.get(i, {}))
        nodes.append({"id": i, "type": "component", "data": data})
    edges = [{"source": "input", "target": i} for i in "abc"] + [{"source": i, "target": "output"} for i in "abc"]
    graph = {"nodes": nodes, "edges": edges, "unit": "Hours", "repairable": repairable}
    if ccf:
        graph["ccf_groups"] = [ccf]
    return rbd_graph.normalize_graph(graph)


KIJIMA = {"repair_quality": {"model": "kijima1", "q": 0.5}}
BETA = {"id": "g1", "members": ["a", "b", "c"], "beta": 0.1}
MGL = {**BETA, "mgl": [0.3]}


# ---- capacity with a mixture life or imperfect repair -------------------------------

def test_a_mixture_life_with_a_capacity_matches_the_library():
    graph = _plant()
    graph["nodes"][2]["data"]["model"] = {**MIX, "source": "params"}
    res = rbd_capacity.production(rbd_graph.normalize_graph(graph))
    comps = {n: {"reliability": sp.Exponential.from_params([f]), "repairability": sp.Exponential.from_params([r])}
             for n, (f, r) in RATES.items()}
    comps["a"]["reliability"] = _mixture()
    lib = RepairableRBD(EDGES, comps, input_node="s", output_node="t", capacity=CAPS).capacity_distribution()
    assert res["production_availability"] == pytest.approx(lib.delivered_fraction(100.0), rel=1e-9)


def test_imperfect_repair_leaves_the_production_availability_out_in_plain_words():
    graph = _plant()
    graph["nodes"][2]["data"].update(KIJIMA)
    with pytest.raises(rbd_capacity.CapacityError, match="“A” is repaired imperfectly.*perfect repair"):
        rbd_capacity.production(rbd_graph.normalize_graph(graph))


# ---- allocation with common cause, imperfect repair and mixtures --------------------

@pytest.mark.parametrize("group", [BETA, MGL])
def test_common_cause_members_keep_their_availability_beta_or_mgl(group):
    with pytest.raises(rbd_allocation.AllocationError, match="members of a common-cause group"):
        rbd_allocation.allocate(_three(ccf=group), 0.9999999, "availability")
    with pytest.raises(rbd_allocation.AllocationError, match="common-cause groups"):
        rbd_allocation.allocate(_three(False, ccf=group), 0.99, "cost_based", t=100)


def test_a_common_cause_pair_leaves_the_third_block_free():
    group = {**MGL, "members": ["a", "b"], "mgl": None}
    res = rbd_allocation.allocate(_three(ccf=group), 0.9999999, "availability")
    kept = {b["label"] for b in res["blocks"] if b.get("kept")}
    assert kept == {"A", "B"} and res["system"]["allocated"] == pytest.approx(0.9999999, abs=1e-9)


def test_imperfect_repair_refuses_allocation_in_plain_words():
    with pytest.raises(rbd_allocation.AllocationError, match="target allocation is worked out exactly"):
        rbd_allocation.allocate(_three(a=KIJIMA), 0.9999999, "availability")


def test_a_mixture_life_is_allocated():
    res = rbd_allocation.allocate(_three(a={"model": {**MIX, "source": "params"}}), 0.9999999, "availability")
    assert res["system"]["allocated"] == pytest.approx(0.9999999, abs=1e-9)


# ---- phases with covariate schedules ------------------------------------------------

@pytest.fixture(scope="module")
def entry():
    r = fitting.fit("weibull_ph", tvc._pumps(), tvc.INTERVALS, ["load_pct"], unit="hours",
                    covariate_units={"load_pct": "%"})
    return fitting._MODEL_STORE[r["functions"]["model_id"]]


def test_a_phased_mission_follows_a_covariate_schedule(entry):
    graph = tvc._graph({"load_pct": {"expression": "60 if t < 1000 else 90"}}, entry["fields"])
    along = rbd_analysis.analyze(graph, t_max=3000, resolve_model=lambda _: entry, at_times=[1000, 3000])
    phased = rbd_phases.analyze_phases({**graph, "phases": [{"name": "Low", "duration": 1000},
                                                            {"name": "High", "duration": 2000}]},
                                       resolve_model=lambda _: entry)
    np.testing.assert_allclose([p["reliability_at_end"] for p in phased["phases"]], along["at"]["sf"], rtol=1e-9)
    assert phased["notes"][0] == rbd_phases.SCHEDULE_NOTE
    plain = rbd_phases.analyze_phases(
        {**tvc._graph(None, entry["fields"]), "phases": [{"name": "All", "duration": 1000}]},
        resolve_model=lambda _: entry)
    assert plain["notes"] == [rbd_phases.STRESS_NOTE]


# ---- networks and the quote ---------------------------------------------------------

def test_a_network_is_never_an_availability_diagram_nor_quoted():
    graph = _three()
    graph["network"] = {"source": "input", "target": "output"}
    with pytest.raises(AnalysisError, match="is a network"):
        rbd_analysis._build_repairable_rbd(graph)
    quote = runtime_quote.quote_runtime(graph, {})
    assert quote["available"] is False and "network" in quote["reason"]


def test_the_quote_counts_a_k_of_n_standby_groups_running_units():
    graph = _three()
    one = runtime_quote.features(graph, {"t_simulation": 1000.0})["events_per_replication"] / 3
    standby = copy.deepcopy(graph)
    standby["nodes"][2] = {"id": "a", "type": "standby",
                           "data": {"label": "A", "model": _exp(0.001), "repair": _exp(0.1), "spares": 1, "k": 2}}
    f = runtime_quote.features(standby, {"t_simulation": 1000.0})
    assert f["events_per_replication"] == pytest.approx(5 * one)


@pytest.mark.parametrize("extra", [KIJIMA, {"model": {**MIX, "source": "params"}}, {"capacity": 5.0}])
def test_the_new_block_options_are_quoted(extra):
    assert runtime_quote.quote_runtime(_three(a=extra), {})["available"] is True


# ---- Download as Python with the options together -----------------------------------

def test_the_export_runs_with_kijima_mgl_capacity_and_a_demand(tmp_path):
    from backend.services import rbd_export
    from backend.tests.test_rbd_export import _run

    graph = _three(ccf={**MGL, "members": ["a", "b", "c"]}, a={**KIJIMA, "capacity": 50.0},
                   b={"capacity": 50.0}, c={"capacity": 50.0})
    graph["nodes"][2]["data"].pop("repair_quality")  # a common-cause member is repaired as good as new
    graph["nodes"].append({"id": "d", "type": "component",
                           "data": {"label": "D", "model": _exp(0.0005), "repair": _exp(0.2), **KIJIMA}})
    graph["edges"] = [e for e in graph["edges"] if e["target"] != "output"] + [
        {"source": i, "target": "d"} for i in "abc"] + [{"source": "d", "target": "output"}]
    graph["production"] = {"demand": 100.0, "unit": "m3/h"}
    graph = rbd_graph.normalize_graph(graph)
    res, proc = _run(rbd_export.to_python(graph, "Combined"), tmp_path, n_sims="30")
    # The simulation runs; the exact-only production availability says why it's missing.
    assert res and "No production availability: Component 'd' is repaired imperfectly" in proc.stdout


def test_the_export_runs_a_phased_mission_with_a_mixture_and_k_of_n_standby(tmp_path):
    from backend.services import rbd_export
    from backend.tests.test_rbd_export import _run

    graph = _three(False, a={"model": {**MIX, "source": "params"}})
    graph["nodes"].append({"id": "s", "type": "standby", "data": {
        "label": "S", "model": _exp(0.001), "spares": 1, "k": 2, "cold": True, "dormancy": 0, "startProb": 1}})
    graph["edges"] = [e for e in graph["edges"] if e["target"] != "output"] + [
        {"source": i, "target": "s"} for i in "abc"] + [{"source": "s", "target": "output"}]
    graph["phases"] = [{"name": "Start", "duration": 50}, {"name": "Run", "duration": 200, "not_needed": ["b"]}]
    graph = rbd_graph.normalize_graph(graph)
    want = rbd_phases.analyze_phases(graph)["reliability"]
    _, proc = _run(rbd_export.to_python(graph, "Mission"), tmp_path)
    assert f"Phased mission (exact): reliability {want:.6f}" in proc.stdout
