"""Common-cause groups in repairable diagrams over time (#226).

RePyability 0.12 follows a ``RepairableRBD``'s common-cause groups over time
(#158 there): the long run, A(t), the window's events and costs, the
simulation and the allocations. Reliafy takes them into every figure where
it does, and into none where it refuses (with its reason). Each figure is
checked against RePyability directly, then the fallbacks, the Design tab's
cheapest design, what to improve (the β lever), the interval choice, the
compute service, Download as Python, the RePyability JSON export and MCP."""

import copy
import json

import matplotlib

matplotlib.use("Agg")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
import surpyval as sv  # noqa: E402
from repyability import BetaFactor, CCFGroup, NodeState, RepairableRBD  # noqa: E402

from backend.services import compute_core, rbd_costs, rbd_export, rbd_intervals, rbd_json  # noqa: E402
from backend.services import rbd_analysis as ra  # noqa: E402
from backend.services import rbd_policies  # noqa: E402
from backend.services import rbd_sensitivity as rs  # noqa: E402
from backend.services.rbds import availability_cache_key  # noqa: E402
from backend.tests.test_mcp import env  # noqa: E402,F401 - a fixture
from backend.tests.test_rbd_costs import _exp, _io, _node, _w  # noqa: E402

E = sv.Exponential.from_params
BETA = 0.2
N = 200
WINDOW = 2000.0


def _graph(beta=BETA, life=None, **graph):
    """A controller in series with two pumps in parallel, the pumps a
    common-cause group; priced, with lost production at 100 an hour."""
    pump = life or _exp(1e-3)
    nodes = [_node("ctl", 100, 0, model=_exp(1e-4), repair=_exp(0.25), costs={"repair": 200}),
             _node("pa", 300, -60, model=pump, repair=_exp(0.02), costs={"repair": 500, "acquisition": 20000}),
             _node("pb", 300, 60, model=pump, repair=_exp(0.02), costs={"repair": 500, "acquisition": 20000})]
    edges = [("input", "ctl"), ("ctl", "pa"), ("ctl", "pb"), ("pa", "output"), ("pb", "output")]
    out = {"repairable": True, "unit": "hours", "nodes": [*_io(), *nodes],
           "edges": [{"id": f"e{i}", "source": a, "target": b} for i, (a, b) in enumerate(edges)],
           "costs": {"downtime_rate": 100, "horizon": 87600}, **graph}
    if beta:
        out["ccf_groups"] = [{"id": "ccf-1", "members": ["pa", "pb"], "beta": beta}]
    return out


def _spec(rate, repair, repair_cost, acquisition=None):
    out = {"reliability": E([rate]), "repairability": E([repair]), "repair_cost": repair_cost}
    if acquisition:
        out["acquisition_cost"] = acquisition
    return out


def _direct(beta=BETA, downtime=100.0, **kw):
    """The same diagram built with RePyability directly."""
    comps = {"ctl": _spec(1e-4, 0.25, 200.0), "pa": _spec(1e-3, 0.02, 500.0, 20000.0),
             "pb": _spec(1e-3, 0.02, 500.0, 20000.0)}
    edges = [("s", "ctl"), ("ctl", "pa"), ("ctl", "pb"), ("pa", "t"), ("pb", "t")]
    groups = [CCFGroup(["pa", "pb"], BetaFactor(beta, basis="rate"))] if beta else None
    return RepairableRBD(edges, comps, input_node="s", output_node="t", downtime_cost_rate=downtime,
                         ccf_groups=groups, **kw)


# ---- The figures, against RePyability ------------------------------------------------------

def test_long_run_figures_and_importance_are_repyabilitys():
    out = ra.analyze_availability(_graph(), simulate=False)
    direct = _direct()
    assert out["steady_state_availability"] == pytest.approx(direct.mean_availability(), rel=1e-12)
    assert out["mean_up_time"] == pytest.approx(direct.mean_up_time(), rel=1e-12)
    assert out["mean_down_time"] == pytest.approx(direct.mean_down_time(), rel=1e-12)
    assert out["failure_frequency"] == pytest.approx(direct.system_failure_frequency(), rel=1e-12)
    birnbaum = direct.birnbaum_importance()
    for nid in ("ctl", "pa", "pb"):
        assert out["importance"][nid]["birnbaum"] == pytest.approx(birnbaum[nid], rel=1e-9)
    # The groups cost availability, and the result says they're in it.
    without = ra.analyze_availability(_graph(beta=0), simulate=False)
    assert out["steady_state_availability"] < without["steady_state_availability"]
    cc = out["common_cause"]
    assert cc == {"groups": 1, "included": True, "reason": None, "basis": "rate",
                  "availability_without_common_cause": pytest.approx(without["steady_state_availability"],
                                                                     rel=1e-12)}
    assert "common_cause" not in without
    assert out["costs"]["cost_rate"] == pytest.approx(direct.expected_cost_rate(), rel=1e-12)


def test_availability_over_time_events_and_costs_are_repyabilitys():
    exact = ra.exact_availability(_graph(), horizon=WINDOW)
    direct = _direct()
    assert exact["status"] == "ok" and exact["common_cause_included"] is True
    t = np.asarray(exact["curve"]["t"])
    assert np.allclose(exact["curve"]["availability"], direct.point_availability(t), rtol=1e-9, atol=1e-12)
    events = direct.expected_events(WINDOW)
    assert exact["mission_availability"] == pytest.approx(direct.mission_availability(WINDOW), rel=1e-9)
    assert exact["expected_failures"] == pytest.approx(events.system_failures, rel=1e-12)
    assert exact["downtime"] == pytest.approx(events.system_downtime, rel=1e-12)
    assert exact["cost"]["mean"] == pytest.approx(float(direct.expected_cost(WINDOW).mean), rel=1e-12)
    pa = next(r for r in exact["per_node"] if r["id"] == "pa")
    assert pa["failures"] == pytest.approx(events.node_failures["pa"], rel=1e-12)
    # Over time the shared cause shows: more failures than independent pumps.
    independent = ra.exact_availability(_graph(beta=0), horizon=WINDOW)
    assert exact["expected_failures"] > independent["expected_failures"]
    assert "common_cause_included" not in independent


def test_the_simulation_takes_the_groups_in():
    out = ra.analyze_availability(_graph(), t_simulation=WINDOW, n_simulations=N, seed=7)
    direct = _direct()
    res = direct.availability(t_simulation=WINDOW, mc_samples=N, method="c", seed=7, antithetic=True,
                              control_variate=False, conditional=False)
    assert out["has_simulation"] and out["common_cause"]["included"] is True
    assert out["precision"]["simulated_window_availability"] == pytest.approx(
        res.mean_availability_interval(0.95).estimate, rel=1e-12)
    assert out["simulated"]["failure_frequency"] == pytest.approx(res.failure_frequency, rel=1e-12)
    # The window's mean is the exact one with the groups.
    assert out["precision"]["window_availability"] == pytest.approx(direct.mission_availability(WINDOW), rel=1e-9)
    # Without the groups the same seed gives another history.
    plain = ra.analyze_availability(_graph(beta=0), t_simulation=WINDOW, n_simulations=N, seed=7)
    assert plain["precision"]["simulated_window_availability"] != out["precision"]["simulated_window_availability"]


def test_the_compute_service_gives_the_in_process_result_for_the_same_seed():
    graph = _graph()
    for options in ({"n_simulations": 40}, {"n_simulations": 40, "seed": 99, "t_simulation": WINDOW}):
        request = json.loads(json.dumps(compute_core.availability_request(graph, **options)))
        remote = compute_core.run("availability", request)
        local = compute_core.to_wire(ra.analyze_availability(graph, **options))
        assert remote == local, options
        assert remote["common_cause"]["included"] is True


def test_hidden_failures_tested_in_no_time_are_followed_too():
    """A 1oo2 of proof-tested channels repaired at once: the PFDavg is the
    unavailability, with the group, in every figure."""
    def channel(nid):
        return _node(nid, model=_exp(1e-5), instant_repair=True, inspection={"interval": 8760})

    edges = [("input", "a"), ("input", "b"), ("a", "output"), ("b", "output")]
    g = {"repairable": True, "unit": "hours", "nodes": [*_io(), channel("a"), channel("b")],
         "edges": [{"source": s, "target": t} for s, t in edges], "safety_function": True,
         "ccf_groups": [{"id": "c", "members": ["a", "b"], "beta": 0.1}]}
    out = ra.analyze_availability(g, simulate=False)
    spec = {"reliability": E([1e-5]), "repairability": "instant", "inspection": {"interval": 8760.0}}
    direct = RepairableRBD([("s", "a"), ("s", "b"), ("a", "t"), ("b", "t")], {"a": spec, "b": spec},
                           input_node="s", output_node="t", ccf_groups=[CCFGroup(["a", "b"], BetaFactor(0.1))])
    assert out["safety"]["pfd_avg"] == pytest.approx(direct.mean_unavailability(), rel=1e-12)
    assert out["unavailability"] == pytest.approx(out["safety"]["pfd_avg"], rel=1e-9)
    assert out["common_cause"]["included"] is True
    exact = ra.exact_availability(g, horizon=3 * 8760.0)
    assert exact["status"] == "ok"
    assert exact["mission_availability"] == pytest.approx(direct.mission_availability(3 * 8760.0), rel=1e-9)


def _tested_pair(repair=None, test_duration=None):
    """A 1oo2 of proof-tested channels, a common-cause group, as a safety
    function: repaired at once (no ``repair``) or over ``repair``, its
    tests taking ``test_duration`` (None: no time)."""
    def channel(nid):
        inspection = {"interval": 8760, **({"duration": test_duration} if test_duration else {})}
        kw = {"repair": repair} if repair else {"instant_repair": True}
        return _node(nid, model=_exp(1e-5), inspection=inspection, **kw)

    edges = [("input", "a"), ("input", "b"), ("a", "output"), ("b", "output")]
    return {"repairable": True, "unit": "hours", "nodes": [*_io(), channel("a"), channel("b")],
            "edges": [{"source": s, "target": t} for s, t in edges], "safety_function": True,
            "ccf_groups": [{"id": "c", "members": ["a", "b"], "beta": 0.1}]}


def _tested_direct(repair, inspection=None):
    spec = {"reliability": E([1e-5]), "repairability": repair,
            "inspection": {"interval": 8760.0, **(inspection or {})}}
    return RepairableRBD([("s", "a"), ("s", "b"), ("a", "t"), ("b", "t")], {"a": spec, "b": spec},
                         input_node="s", output_node="t", ccf_groups=[CCFGroup(["a", "b"], BetaFactor(0.1))])


def test_a_mean_repair_time_keeps_the_group_in_every_figure():
    """RePyability 0.13 (#220 there): proof-tested members repaired over an
    exponential time are followed too (0.12 left the group out), so the
    usual SIL case, a 1oo2 with a β and an MRT, has it in every figure."""
    g = _tested_pair(repair=_exp(1 / 8))
    out = ra.analyze_availability(g, simulate=False)
    assert out["common_cause"]["included"] is True and out["safety"]["common_cause"]["included"] is True
    direct = _tested_direct(E([1 / 8]))
    assert out["safety"]["pfd_avg"] == pytest.approx(direct.mean_unavailability(), rel=1e-9)
    # The repairs' downtime adds to the PFDavg of instant repairs.
    instant = ra.analyze_availability(_tested_pair(), simulate=False)
    assert out["safety"]["pfd_avg"] > instant["safety"]["pfd_avg"]
    assert ra.exact_availability(g, horizon=3 * 8760.0).get("common_cause_included") is True


def test_proof_tests_that_take_time_keep_the_group_in_the_pfdavg():
    """Tests that take time are followed by the group's long-run chain
    (#220), but RePyability 0.13 doesn't work out their failure frequency
    with the groups: the figures leave the group out, with that reason, and
    the PFDavg takes it in."""
    g = _tested_pair(repair=_exp(1 / 8), test_duration=_exp(0.5))
    out = ra.analyze_availability(g, simulate=False)
    assert out["common_cause"]["included"] is False and "tests that take time" in out["common_cause"]["reason"]
    assert out["safety"]["common_cause"]["included"] is True
    direct = _tested_direct(E([1 / 8]), {"duration": E([0.5])})
    assert out["safety"]["pfd_avg"] == pytest.approx(direct.mean_unavailability(), rel=1e-9)
    note = rbd_policies.common_cause_note(g, out)
    assert note["availability_with_common_cause"] == pytest.approx(1 - out["safety"]["pfd_avg"], rel=1e-12)


# ---- Where RePyability refuses them: left out of every figure, and why ---------------------

def _without_figures(graph):
    return ra.analyze_availability({**graph, "ccf_groups": []}, simulate=False)


@pytest.mark.parametrize("change, needle", [
    (lambda g: g, None),
    (lambda g: _graph(life=_w(1500, 1.5)), "exponential"),
    (lambda g: {**g, "repair_crews": {"crews": 1}}, "repair crews"),
    (lambda g: _pinned(g, "pa"), "held working or broken"),
], ids=["followed", "weibull", "crews", "pinned"])
def test_refused_groups_fall_back_with_the_reason(change, needle):
    graph = change(_graph())
    out = ra.analyze_availability(graph, simulate=False)
    cc = out["common_cause"]
    if needle is None:
        assert cc["included"] is True
        return
    assert cc["included"] is False and needle in cc["reason"]
    # Every figure is the diagram's without its groups: none mixes the two.
    without = _without_figures(graph)
    for key in ("steady_state_availability", "mean_up_time", "failure_frequency"):
        assert out[key] == without[key], key
    exact = ra.exact_availability(graph, horizon=WINDOW)
    plain = ra.exact_availability({**graph, "ccf_groups": []}, horizon=WINDOW)
    assert exact.get("common_cause_included") is False
    assert exact.get("mission_availability") == plain.get("mission_availability")
    # The note beside the figures and the Validate step say why.
    note = rbd_policies.common_cause_note(graph, out)
    assert note["included"] is False and needle in note["note"] and "optimistic" in note["note"]
    assert any("leave out the diagram's 1 common-cause group" in w and needle in w
               for w in ra.validate_graph(graph)["warnings"])


def _pinned(graph, nid):
    g = copy.deepcopy(graph)
    for n in g["nodes"]:
        if n["id"] == nid:
            n["data"]["state"] = "working"
    return g


def test_a_pinned_block_outside_the_group_keeps_it():
    out = ra.analyze_availability(_pinned(_graph(), "ctl"), simulate=False)
    assert out["common_cause"]["included"] is True
    assert out["steady_state_availability"] == pytest.approx(
        _direct().mean_availability(working_nodes={"ctl"}), rel=1e-12)


def test_crews_never_claim_the_groups():
    """Limited repair crews don't take common cause in: RePyability 0.13
    refuses the groups there (0.12's crew chain dropped them), so neither the
    figures nor a safety function's PFDavg say they include common cause."""
    g = {**_graph(), "repair_crews": {"crews": 1}, "safety_function": True}
    out = ra.analyze_availability(g, simulate=False)
    assert out["common_cause"]["included"] is False and out["safety"]["common_cause"]["included"] is False
    assert "repair crews" in out["safety"]["common_cause"]["note"]


def test_as_of_now_falls_back_but_the_pfdavg_keeps_them():
    """Started from a state, a member's group can't be followed (its chains
    start every member new): the run leaves the groups out, while the
    PFDavg, a long-run value, keeps them."""
    g = {**_graph(), "safety_function": True}
    state = ra.parse_current_state(g, {"pa": {"down": True, "since": 2.0}})
    out = ra.analyze_availability(g, state=state, n_simulations=40)
    assert out["common_cause"]["included"] is False and "current state" in out["common_cause"]["reason"]
    assert out["safety"]["common_cause"]["included"] is True
    assert out["safety"]["pfd_avg"] == pytest.approx(_direct().mean_unavailability(), rel=1e-12)
    note = rbd_policies.common_cause_note(g, out)
    assert note["availability_with_common_cause"] == pytest.approx(1 - out["safety"]["pfd_avg"], rel=1e-12)
    # A state on a block outside the group keeps them.
    other = ra.analyze_availability(g, state=ra.parse_current_state(g, {"ctl": {"age": 10.0}}), n_simulations=40)
    assert other["common_cause"]["included"] is True


def test_saved_results_before_226_are_redone():
    """Results saved before the groups were followed left them out: their
    key changes for a repairable diagram with groups, and only for one."""
    import backend.services.rbds as rbds

    plain = _graph(beta=0)
    assert availability_cache_key(_graph()) != availability_cache_key({**_graph(), "ccf_groups": []})
    assert "ccf_over_time" not in rbds.canonical_analysis_graph(plain)
    assert rbds.canonical_analysis_graph(_graph())["ccf_over_time"] == 1
    assert "ccf_over_time" not in rbds.canonical_analysis_graph({**_graph(), "repairable": False})
    legacy = rbd_policies.common_cause_note(_graph(), {"steady_state_availability": 0.99})
    assert legacy["included"] is False and "Run the analysis again" in legacy["note"]


# ---- Design tab: the cheapest design --------------------------------------------------------

def test_cheapest_design_scores_with_the_group_and_draws_its_copies_in_it():
    g = _graph(costs={"downtime_rate": 5000, "horizon": 87600})
    out = rbd_costs.cheapest_design(g, horizon=87600)
    direct = _direct(downtime=5000.0)
    alloc = direct.allocate_redundancy(87600.0, nodes=["pa", "pb"], max_units=rbd_costs.MAX_COPIES)
    assert out["design"]["units"] == {k: int(v) for k, v in alloc.units.items()}
    assert out["design"]["total_cost"] == pytest.approx(alloc.total_cost, rel=1e-9)
    assert out["design"]["availability"] == pytest.approx(alloc.availability, rel=1e-9)
    assert out["current"]["availability"] == pytest.approx(direct.mean_availability(), rel=1e-12)
    assert out["common_cause"]["included"] is True and "copies join its group" in out["common_cause"]["note"]
    # Copies make it cheaper here, and drawn on the diagram they join the
    # group, so its analysis gives the design's figures.
    assert out["changed"] and out["graph"] is not None
    members = out["graph"]["ccf_groups"][0]["members"]
    copies = sum(out["design"]["units"].values())
    assert len(members) == copies
    applied = ra.analyze_availability(out["graph"], simulate=False)
    assert applied["common_cause"]["included"] is True
    assert applied["steady_state_availability"] == pytest.approx(out["design"]["availability"], rel=1e-9)
    total = ra._build_repairable_rbd(out["graph"])[0].total_cost(87600.0)
    assert total == pytest.approx(out["design"]["total_cost"], rel=1e-9)


def test_cheapest_design_without_the_group_says_why():
    out = rbd_costs.cheapest_design(_graph(life=_w(1500, 1.5)), horizon=87600)
    assert out["common_cause"]["included"] is False and "exponential" in out["common_cause"]["note"]


# ---- What to improve: the group's beta is a lever --------------------------------------------

def test_common_cause_beta_is_a_lever_with_repyabilitys_derivative():
    out = rs.analyze_sensitivity(_graph())
    assert out["status"] == "ok" and out["common_cause_included"] is True
    rows = {r["id"]: r for r in out["levers"]}
    beta = rows["pa+pb|ccf_beta"]
    assert beta["name"] == "Common-cause β" and beta["block"] == "Pa & Pb" and beta["block_id"] == "pa+pb"
    direct = _direct()
    sens = direct.parameter_sensitivity(of=("availability", "cost_rate"))
    assert beta["derivative"]["availability"] == pytest.approx(sens["availability"][("pa", "pb")]["ccf_beta"],
                                                               rel=1e-9)
    # A lower beta helps: the step's effect is RePyability's difference.
    assert beta["to"] == pytest.approx(BETA * 0.9) and beta["effect"]["availability"] > 0
    lower = _direct(beta=BETA * 0.9).mean_availability()
    assert beta["effect"]["availability"] == pytest.approx(lower - direct.mean_availability(), rel=1e-9)
    # The members' life moves together, as the group's lever.
    assert "pa+pb|reliability.failure_rate" in rows and "pa|reliability.failure_rate" not in rows
    assert any("β is a lever" in n for n in out["notes"])


def test_what_to_improve_leaves_a_refused_group_out_and_says_why():
    out = rs.analyze_sensitivity(_graph(life=_w(1500, 1.5)))
    assert out["common_cause_included"] is False
    assert not any("ccf_" in r["id"] for r in out["levers"])
    assert any("exponential" in n for n in out["notes"])


# ---- The interval optimiser -------------------------------------------------------------------

def test_proof_test_intervals_are_chosen_with_the_group():
    def valve(nid):
        return _node(nid, model=_exp(2e-6), instant_repair=True,
                     inspection={"interval": 8760, "cost": 500}, costs={"downtime": 10})

    edges = [("input", "v1"), ("input", "v2"), ("v1", "output"), ("v2", "output")]
    g = {"repairable": True, "unit": "hours", "nodes": [*_io(), valve("v1"), valve("v2")],
         "edges": [{"source": s, "target": t} for s, t in edges], "costs": {"downtime_rate": 5000},
         "ccf_groups": [{"id": "c", "members": ["v1", "v2"], "beta": 0.1}]}
    allowed = [730.0, 2190.0, 4380.0, 8760.0, 17520.0]
    out = rbd_intervals.optimise(g, allowed=allowed)
    assert out["common_cause"] == {"groups": 1, "included": True, "note": None}
    rbd = ra._build_repairable_rbd(g)[0]
    found = rbd.optimal_inspection_intervals(["v1", "v2"], allowed=allowed)
    chosen = {r["id"]: r["interval"] for r in out["blocks"]}
    assert chosen == {k: pytest.approx(v) for k, v in found.intervals.items()}
    assert out["plan"]["availability"] == pytest.approx(found.availability, rel=1e-9)


# ---- Download as Python and the RePyability JSON give the app's numbers ---------------------

def test_the_python_export_follows_the_group_as_the_app_does(tmp_path):
    from backend.tests.test_rbd_export import WHEN, _run

    g = _graph()
    app = ra.analyze_availability(g, n_simulations=60)
    exact = ra.exact_availability(g)
    code = rbd_export.to_python(g, "Pumps", exported_at=WHEN)
    assert "CCFGroup(members=['pa', 'pb'], model=BetaFactor(0.2, basis='rate'))" in code
    assert "def common_cause_refusal(" in code
    res, _ = _run(code, tmp_path, n_sims="60")
    assert res["common_cause"] == {"groups": 1, "included": True, "reason": None}
    assert res["steady_state_availability"] == pytest.approx(app["steady_state_availability"], rel=1e-12)
    assert res["failure_frequency"] == pytest.approx(app["failure_frequency"], rel=1e-12)
    assert res["precision"]["simulated_window_availability"] == pytest.approx(
        app["precision"]["simulated_window_availability"], rel=1e-12)
    assert res["exact"]["mission_availability"] == pytest.approx(exact["mission_availability"], rel=1e-9)
    assert res["costs"]["cost_rate"] == pytest.approx(app["costs"]["cost_rate"], rel=1e-12)
    # What to improve: the same levers, the group's beta among them.
    improve = {f"{r['block']}|{r['lever']}": r for r in res["what_to_improve"]}
    app_rows = {r["id"]: r for r in rs.analyze_sensitivity(g)["levers"]}
    assert improve["pa+pb|ccf_beta"]["effect"] == pytest.approx(
        app_rows["pa+pb|ccf_beta"]["effect"]["availability"], rel=1e-9)


def test_the_python_export_falls_back_as_the_app_does(tmp_path):
    from backend.tests.test_rbd_export import WHEN, _run

    g = _graph(life=_w(1500, 1.5))
    app = ra.analyze_availability(g, n_simulations=60)
    res, proc = _run(rbd_export.to_python(g, "Worn pumps", exported_at=WHEN), tmp_path, n_sims="60")
    assert res["common_cause"]["included"] is False and "exponential" in res["common_cause"]["reason"]
    assert "Common-cause groups left out of every figure" in proc.stdout
    assert res["steady_state_availability"] == pytest.approx(app["steady_state_availability"], rel=1e-12)
    assert res["precision"]["simulated_window_availability"] == pytest.approx(
        app["precision"]["simulated_window_availability"], rel=1e-12)


def test_the_repyability_json_gives_the_apps_numbers():
    from repyability.rbd.serialisation import rbd_from_dict

    g = _graph()
    doc = rbd_json.to_document(g, "Pumps")
    assert doc["ccf_groups"] and doc["reliafy"]["common_cause"]["included"] is True
    rbd = rbd_from_dict(json.loads(rbd_json.to_json(doc)))
    app = ra.analyze_availability(g, simulate=False)
    assert rbd.mean_availability() == pytest.approx(app["steady_state_availability"], rel=1e-12)
    assert rbd.mission_availability(WINDOW) == pytest.approx(
        ra.exact_availability(g, horizon=WINDOW)["mission_availability"], rel=1e-9)
    # Refused, the RePyability part leaves them out as the analysis does; the
    # diagram (Reliafy's part) keeps them, and says why.
    worn = _graph(life=_w(1500, 1.5))
    doc = rbd_json.to_document(worn, "Worn pumps")
    assert not doc.get("ccf_groups") and doc["reliafy"]["graph"]["ccf_groups"]
    assert doc["reliafy"]["common_cause"]["included"] is False
    rbd = rbd_from_dict(json.loads(rbd_json.to_json(doc)))
    assert rbd.mean_availability() == pytest.approx(
        ra.analyze_availability(worn, simulate=False)["steady_state_availability"], rel=1e-12)


# ---- Compare with… ---------------------------------------------------------------------------

def test_compare_says_which_design_has_its_groups():
    from backend.services import rbd_compare

    out = rbd_compare.compare_availability(_graph(), _graph(beta=0.05), n_simulations=40)
    a, b = out["designs"]["a"], out["designs"]["b"]
    assert a["common_cause_included"] is True and b["common_cause_included"] is True
    assert a["steady_state_availability"] == pytest.approx(_direct().mean_availability(), rel=1e-12)
    assert b["steady_state_availability"] == pytest.approx(_direct(beta=0.05).mean_availability(), rel=1e-12)
    assert out["differences"]["availability"]["exact"] > 0


# ---- MCP ---------------------------------------------------------------------------------------

def _stage(label, *names, **extra):
    comps = [{"label": n, "distribution": "exponential", "params": [{"name": "failure_rate", "value": 1e-3}],
              "repair_distribution": "exponential", "repair_params": [{"name": "failure_rate", "value": 0.02}]}
             for n in names]
    return {"label": label, "components": comps, **extra}


def test_mcp_create_analyze_edit_improve_and_design(env, monkeypatch):
    from backend.services import billing as billing_service
    from backend.tests.test_mcp import A, _call, _ok

    monkeypatch.setattr(billing_service, "premium_compute_allowed", lambda db, user: True)
    made = _ok(_call(env.token[A], "create_rbd", {
        "name": "Pumps", "repairable": True,
        "stages": [_stage("Pumps", "Pump A", "Pump B", common_cause_beta=BETA)]}))
    rid = made["id"]
    graph = env.db.rbds.find_one({"_id": rid})["graph"]
    assert graph["ccf_groups"][0]["beta"] == BETA and len(graph["ccf_groups"][0]["members"]) == 2
    assert not any("common-cause" in w for w in made.get("warnings") or [])
    out = _ok(_call(env.token[A], "analyze_rbd", {"rbd_id": rid, "simulate": False}))
    a, b = graph["ccf_groups"][0]["members"]
    spec = {"reliability": E([1e-3]), "repairability": E([0.02])}
    direct = RepairableRBD([("s", a), ("s", b), (a, "t"), (b, "t")], {a: spec, b: spec}, input_node="s",
                           output_node="t", ccf_groups=[CCFGroup([a, b], BetaFactor(BETA, basis="rate"))])
    assert out["steady_state_availability"] == pytest.approx(direct.mean_availability(), rel=1e-12)
    assert out["availability"]["common_cause_included"] is True
    assert out["availability"]["without_common_cause"]["value"] > out["steady_state_availability"]
    assert out["common_cause"]["included"] is True
    # What to improve: the group's beta is a lever.
    improve = _ok(_call(env.token[A], "rbd_sensitivity", {"rbd_id": rid, "limit": 20}))
    assert any(r["id"].endswith("|ccf_beta") for r in improve["levers"])
    # remove_ccf / add_ccf on a repairable diagram: no "ignored" warning.
    edited = _ok(_call(env.token[A], "edit_rbd", {"rbd_id": rid, "ops": [
        {"op": "remove_ccf", "id": graph["ccf_groups"][0]["id"]},
        {"op": "add_ccf", "members": [a, b], "beta": 0.05}]}))
    assert not any("common-cause" in w for w in edited.get("warnings") or [])
    again = _ok(_call(env.token[A], "analyze_rbd", {"rbd_id": rid, "simulate": False}))
    direct = RepairableRBD([("s", a), ("s", b), (a, "t"), (b, "t")], {a: spec, b: spec}, input_node="s",
                           output_node="t", ccf_groups=[CCFGroup([a, b], BetaFactor(0.05))])
    assert again["steady_state_availability"] == pytest.approx(direct.mean_availability(), rel=1e-12)
    # The cheapest design, with the group.
    _ok(_call(env.token[A], "edit_rbd", {"rbd_id": rid, "ops": [
        {"op": "update_node", "ids": [a, b], "costs": {"acquisition": 5000}},
        {"op": "set", "costs": {"downtime_rate": 1000, "horizon": 87600}}]}))
    design = _ok(_call(env.token[A], "cheapest_design", {"rbd_id": rid}))
    assert design["available"] is True and design["common_cause"]["included"] is True
