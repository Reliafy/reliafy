"""The repairable analyze_rbd response over MCP (#184, #185, #186): what an
agent reads when nothing was computed, when common cause is left out of the
headline figures, and the shape of the routes, importance and availability.

The diagrams are the ones from the agent test drive: the CW pump train (MCC,
strainer with block PM, 1+1 standby pumps on a Weibull life, check valve, one
repair crew) and a 1oo2 transmitter safety function with a beta-factor
common-cause group.
"""

from backend.tests.test_mcp import A, _call, _ok, env  # noqa: F401 - env is a fixture


def _m(dist, **params):
    return {"distribution_id": dist, "params": [{"name": k, "value": v} for k, v in params.items()]}


REPAIR = _m("lognormal", mu=1.5, sigma=0.5)


def _cw_pump_train():
    return {
        "nodes": [
            {"id": "input", "type": "input"}, {"id": "output", "type": "output"},
            {"id": "mcc", "type": "component", "label": "MCC", "model": _m("exponential", failure_rate=2e-5),
             "repair": REPAIR},
            {"id": "strainer", "type": "component", "label": "Suction strainer",
             "model": _m("weibull", alpha=8000, beta=2.5), "repair": REPAIR,
             "preventive": {"policy": "block", "interval": 4000}},
            {"id": "pumps", "type": "standby", "label": "CW pumps A/B (duty/standby)",
             "model": _m("weibull", alpha=12000, beta=1.8), "repair": REPAIR, "spares": 1},
            {"id": "cv", "type": "component", "label": "Discharge check valve",
             "model": _m("exponential", failure_rate=1e-5), "repair": REPAIR},
        ],
        "edges": [{"source": "input", "target": "mcc"}, {"source": "mcc", "target": "strainer"},
                  {"source": "strainer", "target": "pumps"}, {"source": "pumps", "target": "cv"},
                  {"source": "cv", "target": "output"}],
    }


def _create_cw(env):
    return _ok(_call(env.token[A], "create_rbd", {"name": "CW pump train", "repairable": True,
                                                  **_cw_pump_train(), "repair_crews": 1}))["id"]


def _analyze(env, rid, **kw):
    return _ok(_call(env.token[A], "analyze_rbd", {"rbd_id": rid, **kw}))


def _edit(env, rid, *ops):
    return _ok(_call(env.token[A], "edit_rbd", {"rbd_id": rid, "ops": list(ops)}))


# ---- #184 nothing computed: say so, and drop the null figures ---------------------

def test_simulation_only_diagram_without_the_simulation_says_so(env):
    rid = _create_cw(env)
    out = _analyze(env, rid, simulate=False)
    assert out["available"] is False and out["needs_simulation"] is True
    assert "simulate=true" in out["reason"] and "export_rbd_python" in out["reason"]
    for key in ("steady_state_availability", "unavailability", "mean_up_time", "mean_down_time",
                "failure_frequency", "figures_basis", "importance"):
        assert key not in out, key
    assert out["exact"]["status"] == "simulation_only"
    assert out["simulation"] == {"available": False, "state": "not_run"}


def test_edit_reports_the_saved_simulation_it_discards(env):
    rid = _create_cw(env)
    ran = _analyze(env, rid, simulate=True)
    assert ran["available"] is True and ran["mean_up_time"] > 0
    # The saved result is served without a new run.
    saved = _analyze(env, rid, simulate=False)
    assert saved["available"] is True and saved["simulation"]["state"] == "saved"
    # A rename leaves the analysis (and the saved result) as it was...
    out = _edit(env, rid, {"op": "set", "name": "CW pumps"})
    assert out["saved_simulation"] == {"status": "kept"}
    # ...a dry run of a real change says what it would do...
    dry = _ok(_call(env.token[A], "edit_rbd", {"rbd_id": rid, "dry_run": True,
                                                "ops": [{"op": "set", "repair_crews": 2}]}))
    assert dry["saved_simulation"]["status"] == "discarded" and "would discard" in dry["saved_simulation"]["message"]
    assert _analyze(env, rid, simulate=False)["available"] is True
    # ...and the change itself discards it, which analyze_rbd then explains.
    out = _edit(env, rid, {"op": "set", "repair_crews": 2})
    assert out["saved_simulation"]["status"] == "discarded"
    assert "discarded the saved simulation result" in out["saved_simulation"]["message"]
    after = _analyze(env, rid, simulate=False)
    assert after["available"] is False and after["needs_simulation"] is True
    assert "before it was last edited" in after["reason"]
    # Edits after that have no saved result to report on.
    assert "saved_simulation" not in _edit(env, rid, {"op": "set", "name": "CW"})


def test_diagram_with_exact_figures_is_unchanged(env):
    graph = _cw_pump_train()
    graph["nodes"][4] = {"id": "pumps", "type": "component", "label": "CW pump", "model": _m(
        "exponential", failure_rate=1e-4), "repair": REPAIR}
    rid = _ok(_call(env.token[A], "create_rbd", {"name": "Exact", "repairable": True, **graph}))["id"]
    out = _analyze(env, rid, simulate=False)
    assert out["available"] is True and "needs_simulation" not in out
    assert 0 < out["steady_state_availability"] < 1


# ---- #185 common cause left out of the headline figures: say so -----------------

def _sif():
    """1oo2 pressure transmitters -> logic solver -> trip valve, proof-tested yearly."""
    def block(nid, label, rate):
        return {"id": nid, "type": "component", "label": label, "model": _m("exponential", failure_rate=rate),
                "instant_repair": True, "inspection": {"interval": 8760}}

    return {
        "nodes": [{"id": "input", "type": "input"}, {"id": "output", "type": "output"},
                  block("pt_a", "PT A", 1e-6), block("pt_b", "PT B", 1e-6),
                  block("ls", "Logic solver", 1e-7), block("tv", "Trip valve", 2e-6)],
        "edges": [{"source": "input", "target": "pt_a"}, {"source": "input", "target": "pt_b"},
                  {"source": "pt_a", "target": "ls"}, {"source": "pt_b", "target": "ls"},
                  {"source": "ls", "target": "tv"}, {"source": "tv", "target": "output"}],
    }


def _create_sif(env, **settings):
    return _ok(_call(env.token[A], "create_rbd", {"name": "High-pressure trip", "repairable": True, **_sif(),
                                                  **settings}))["id"]


def test_headline_availability_says_it_leaves_common_cause_out(env):
    rid = _create_sif(env, safety_function=True, target_sil=2)
    before = _analyze(env, rid, simulate=False)
    assert "common_cause" not in before
    assert not any("common cause" in w for w in before.get("warnings") or [])

    _edit(env, rid, {"op": "add_ccf", "members": ["pt_a", "pt_b"], "beta": 0.05})
    out = _analyze(env, rid, simulate=False)
    # The headline figures are those without common cause; PFDavg takes it in.
    assert out["unavailability"] == before["unavailability"]
    assert out["safety"]["common_cause"]["included"] is True
    assert out["safety"]["pfd_avg"] > out["unavailability"]
    cc = out["common_cause"]
    assert cc["groups"] == 1 and cc["included"] is False
    assert "leave out the 1 common-cause group" in cc["note"] and "safety.pfd_avg includes them" in cc["note"]
    # Beside the headline figures, and in the warnings with both numbers.
    keys = list(out)
    assert keys.index("steady_state_availability") < keys.index("common_cause") < keys.index("safety")
    warning = next(w for w in out["warnings"] if "leave out common cause" in w)
    assert f"{out['unavailability']:.4g}" in warning and f"{out['safety']['pfd_avg']:.4g}" in warning


def test_common_cause_outside_a_safety_function_is_noted(env):
    rid = _create_sif(env)
    _edit(env, rid, {"op": "add_ccf", "members": ["pt_a", "pt_b"], "beta": 0.05})
    out = _analyze(env, rid, simulate=False)
    assert out["common_cause"]["included"] is False and "safety_function=true" in out["common_cause"]["note"]
    assert any("so they are optimistic" in w for w in out["warnings"])


# ---- #186 response cleanups --------------------------------------------------------

BLOCKER = "it has no place for a standby group"


def test_refusal_reasons_are_in_mcp_terms_and_given_once(env):
    import json

    out = _analyze(env, _create_cw(env), simulate=False)
    text = json.dumps(out, ensure_ascii=False)
    # RePyability's Python API isn't something an MCP client can call.
    assert "availability()" not in text and "cost()" not in text
    reason = out["long_run_method"]["reason"]
    assert BLOCKER in reason and "analyze_rbd with simulate=true" in reason and "export_rbd_python" in reason
    # The crews' count is the repair jobs repair_crews counts (a standby unit each).
    assert "1 repair crew(s) for 5 repair jobs" in reason and out["repair_crews"]["jobs"] == 5
    # The blocker's paragraph once, not once per route.
    assert text.count(BLOCKER) == 1
    exact = out["exact"]
    assert exact["routes"]["mean_availability"] == {"route": "refused"}
    assert exact["routes"]["availability"] == {"route": "simulated"}
    refused = next(g for g in exact["route_reasons"] if "mean_availability" in g["routes"])
    assert set(refused["routes"]) >= {"mean_availability", "point_availability", "mission_availability",
                                      "expected_failures", "expected_events"}
    assert refused["reason"] == "As long_run_method.reason."
    assert exact["message"].endswith("long_run_method.reason says why.")


def test_simulated_result_has_a_headline_availability_and_no_null_importance(env):
    out = _analyze(env, _create_cw(env), simulate=True)
    head = out["availability"]
    assert head["basis"] == "simulation" and head["value"] == out["precision"]["window_availability"]
    assert head["interval"]["lower"] <= head["value"] <= head["interval"]["upper"]
    assert head["interval"]["confidence"] == out["precision"]["confidence"]
    # Nothing computed for importance: one note, not nine nulls per block.
    assert "importance" not in out
    assert "long_run_method" in out["importance_note"] and "criticality" in out["importance_note"]
    assert out["criticality"]


def test_exact_result_has_a_headline_availability_and_its_importance(env):
    graph = _cw_pump_train()
    graph["nodes"][4] = {"id": "pumps", "type": "component", "label": "CW pump", "model": _m(
        "exponential", failure_rate=1e-4), "repair": REPAIR}
    rid = _ok(_call(env.token[A], "create_rbd", {"name": "Exact", "repairable": True, **graph}))["id"]
    out = _analyze(env, rid, simulate=False)
    assert out["availability"] == {"value": out["steady_state_availability"], "basis": "exact",
                                   "measure": "long-run (steady-state) availability", "interval": None}
    assert set(out["importance"]) == {"mcc", "strainer", "pumps", "cv"} and "importance_note" not in out
    assert all(row["birnbaum"] is not None for row in out["importance"].values())


def test_block_counts_agree(env):
    from backend.services import rbd_analysis

    created = _ok(_call(env.token[A], "create_rbd", {"name": "CW", "repairable": True, **_cw_pump_train(),
                                                     "repair_crews": 1}))
    # The standby group is one block everywhere; its units are repair jobs.
    out = _analyze(env, created["id"], simulate=False)
    assert created["n_blocks"] == out["exact"]["n_blocks"] == 4
    assert out["repair_crews"]["blocks"] == 4
    assert rbd_analysis.count_blocks(_cw_pump_train()) == 4
    # A voting gate isn't a block.
    stage = {"label": "Pumps", "k_of_n": 2, "components": [
        {"label": f"Pump {i}", "distribution": "weibull",
         "params": [{"name": "alpha", "value": 900}, {"name": "beta", "value": 1.4}]} for i in (1, 2, 3)]}
    voted = _ok(_call(env.token[A], "create_rbd", {"name": "2oo3", "stages": [stage]}))
    assert any(n["type"] == "knode" for n in voted["nodes"]) and voted["n_blocks"] == 3
