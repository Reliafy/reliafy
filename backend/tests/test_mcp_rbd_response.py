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
