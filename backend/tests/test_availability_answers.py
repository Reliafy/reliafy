"""The repairable analyze_rbd answer an agent reads (#184, #185, #186).

The CW pump train of the agent test drive: an MCC, a strainer with block PM,
a 1+1 cold standby pair on a Weibull life and a check valve, with one repair
crew — simulation-only, since the crews' Markov chain has no place for a
standby group. And a 1oo2 safety function with a common-cause group.
"""

import json
import math

import matplotlib

matplotlib.use("Agg")

import pytest  # noqa: E402

from backend.services import availability_answer  # noqa: E402
from backend.services import rbd_analysis as ra  # noqa: E402
from backend.tests.test_mcp import REPAIRABLE_STAGES, A, _call, _ok, env  # noqa: E402,F401 - env is a fixture
from backend.tests.test_rbd_costs import _exp, _io, _ln, _node, _w  # noqa: E402

FIGURES = ("steady_state_availability", "unavailability", "mean_up_time", "mean_down_time", "failure_frequency",
           "figures_basis", "importance")


def _cw_train():
    nodes = [
        _node("mcc", model=_exp(1e-5), repair=_exp(0.25)),
        _node("strainer", model=_w(4000, 2.0), repair=_ln(1.0, 0.3), preventive={"interval": 2000, "duration": 2}),
        {"id": "pumps", "type": "standby", "position": {"x": 0, "y": 0},
         "data": {"label": "CW pumps A/B (duty/standby)", "model": _w(3000, 1.8), "repair": _ln(2.5, 0.5),
                  "spares": 1, "dormancy": 0}},
        _node("cv", model=_exp(2e-5), repair=_exp(0.2)),
    ]
    ids = ["input", "mcc", "strainer", "pumps", "cv", "output"]
    return {"repairable": True, "unit": "hours", "nodes": [*_io(), *nodes],
            "edges": [{"id": f"e{i}", "source": a, "target": b} for i, (a, b) in enumerate(zip(ids, ids[1:]))],
            "repair_crews": {"crews": 1}}


def _sif(beta=0.05):
    """1oo2 transmitters (λ = 1e-6/h, proof-tested yearly) -> logic solver -> trip valve."""
    def tested(nid, rate):
        return _node(nid, model=_exp(rate), instant_repair=True, inspection={"interval": 8760})

    nodes = [tested("pt1", 1e-6), tested("pt2", 1e-6), tested("ls", 5e-8), tested("valve", 2e-7)]
    edges = [("input", "pt1"), ("input", "pt2"), ("pt1", "ls"), ("pt2", "ls"), ("ls", "valve"), ("valve", "output")]
    return {"repairable": True, "unit": "hours", "nodes": [*_io(), *nodes],
            "edges": [{"id": f"e{i}", "source": a, "target": b} for i, (a, b) in enumerate(edges)],
            "safety_function": True, "target_sil": 2,
            "ccf_groups": [{"id": "c1", "members": ["pt1", "pt2"], "beta": beta}]}


def _saved(env, graph):
    rid = _ok(_call(env.token[A], "create_rbd", {"name": "Diagram", "repairable": True,
                                                 "stages": REPAIRABLE_STAGES}))["id"]
    env.db.rbds.update_one({"_id": rid}, {"$set": {"graph": graph}})
    return rid


def _analyze(env, rid, **kw):
    return _ok(_call(env.token[A], "analyze_rbd", {"rbd_id": rid, **kw}))


# ---- #184: simulate=false on a simulation-only diagram says so --------------------------

def test_simulation_only_diagram_without_the_simulation_is_not_available(env):
    out = _analyze(env, _saved(env, _cw_train()), simulate=False)
    assert out["available"] is False and out["needs_simulation"] is True and out["code"] == "needs_simulation"
    assert "simulate=true" in out["reason"] and "standby group" in out["reason"]
    assert out["simulation"] == {"available": False, "state": "not_run"}
    assert not set(FIGURES) & set(out), "no page of null figures"
    assert out["exact"]["status"] == "simulation_only"


def test_analyze_rbd_description_documents_the_needs_simulation_answer(env):
    """The tool description tells an agent what the #184 answer looks like
    and what to do with it."""
    from backend.tests.test_mcp import _run

    tools = {t.name: t for t in _run(env.token[A], lambda c: c.list_tools()).tools}
    text = " ".join(tools["analyze_rbd"].description.split())
    assert "simulate=false" in text and "available=false" in text
    assert "needs_simulation=true, code 'needs_simulation'" in text
    assert "call again with simulate=true" in text and "export_rbd_python" in text


def test_a_diagram_with_exact_figures_stays_available_with_a_headline(env):
    graph = _cw_train()
    graph.pop("repair_crews")
    for n in graph["nodes"]:
        if n["type"] in ("component", "standby"):
            n["data"].pop("preventive", None)
            n["data"].update(model=_exp(1 / 3000), repair=_exp(0.2))
    out = _analyze(env, _saved(env, graph), simulate=False)
    assert out["available"] is True and "needs_simulation" not in out
    assert out["availability"]["basis"] == "exact"
    assert out["availability"]["value"] == out["steady_state_availability"] is not None


# ---- #185: common cause beside the headline availability --------------------------------

def test_common_cause_left_out_of_the_availability_is_said(env):
    out = _analyze(env, _saved(env, _sif()), simulate=False)
    safety, cc = out["safety"], out["common_cause"]
    assert safety["common_cause"]["included"] is True
    assert cc["groups"] == 1 and cc["included"] is False
    assert cc["availability_with_common_cause"] == pytest.approx(1 - safety["pfd_avg"], rel=1e-12)
    # The CCF-free figures are lower in unavailability than the PFDavg, and say so.
    assert out["unavailability"] < safety["pfd_avg"]
    # A safety function leads with the figure with common cause (#265), the
    # one without it alongside.
    head = out["availability"]
    assert head["common_cause_included"] is True
    assert head["value"] == head["with_common_cause"] == pytest.approx(cc["availability_with_common_cause"])
    assert head["without_common_cause"]["value"] == out["steady_state_availability"]
    assert "common_cause_included" not in head["without_common_cause"]
    assert safety["common_cause_included"] is True
    assert any("leave out the diagram's 1 common-cause group" in w and "pfd_avg includes" in w
               for w in out["warnings"])
    # Without groups there's nothing to say.
    plain = _analyze(env, _saved(env, _sif() | {"ccf_groups": []}), simulate=False)
    assert "common_cause" not in plain and "common_cause_included" not in plain["availability"]


# ---- #186: Reliafy's words, each reason once, no null importance, one headline ----------

def test_simulated_answer_is_compact_and_in_reliafys_words(env):
    out = _analyze(env, _saved(env, _cw_train()), simulate=True)
    text = json.dumps(out, ensure_ascii=False)
    assert "availability()" not in text and "cost()" not in text
    assert "5 components" not in text and "5 repair jobs" in text
    exact = out["exact"]
    (refused,) = exact["refused"]
    assert set(refused["routes"]) == {"mean_availability", "point_availability", "mission_availability",
                                      "expected_failures", "expected_events"}
    assert text.count(refused["reason"]) == 1
    # Existing fields stay: every route keeps its route and a reason.
    assert all(exact["routes"][k]["route"] == "refused" and exact["routes"][k]["reason"] for k in refused["routes"])
    assert out["long_run_method"]["route"] == "refused"
    # No table of nulls.
    assert out["importance"] == {} and "criticality" in out["importance_note"]
    # The headline: the simulated window's mean, with its interval.
    head = out["availability"]
    p = out["precision"]
    assert head["basis"] == "simulation" and head["value"] == p["window_availability"]
    assert head["lower"] <= head["value"] <= head["upper"]
    # One block count: the standby group is one block.
    assert exact["n_blocks"] == out["repair_crews"]["blocks"] == 4


@pytest.mark.parametrize("raw, plain", [
    ("… which component “Pumps” is. Simulate the system with availability() or cost().",
     "… which component “Pumps” is. Simulate the system."),
    ("known only by simulation, with availability().", "known only by simulation."),
    ("Simulate them with availability() or cost(); the availability over time is exact.",
     "Simulate them; the availability over time is exact."),
    ("Simulate it with availability(demand=...).", "Simulate it."),
    ("With 2 repair crew(s) for 5 components, a component can wait.",
     "With 2 repair crews for 5 repair jobs (each unit of a standby group is one), a component can wait."),
])
def test_plain_reason(raw, plain):
    assert ra.plain_reason(raw) == plain
    assert ra.plain_reason(plain) == plain  # idempotent: saved results are cleaned again


def test_a_saved_result_is_cleaned_too():
    old = {"long_run_method": {"route": "refused", "reason": "x. Simulate the system with availability() or cost()."},
           "exact": {"message": "m with availability().", "routes": {"a": {"route": "refused",
                                                                         "reason": "r with availability()."}}}}
    new = ra.plain_reasons(old)
    assert "availability()" not in json.dumps(new) and "availability()" in json.dumps(old)


def test_count_blocks_counts_a_standby_group_once():
    assert ra.count_blocks(_cw_train()) == 4


def test_headline_falls_back_to_the_exact_window_mean():
    payload = {"has_simulation": False, "steady_state_availability": None,
               "exact": {"status": "ok", "mission_availability": 0.99, "window": 1000.0, "unit": "hours",
                         "method": {"mission_availability": "numerical"}}}
    out = availability_answer.finish({"available": True}, payload)
    assert out["availability"]["value"] == 0.99 and out["availability"]["basis"] == "exact"
    assert math.isclose(out["availability"]["value"], 0.99)
