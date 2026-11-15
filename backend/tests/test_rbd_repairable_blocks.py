"""Repairable-and-replaceable RBD blocks (#367): a fitted repairable model as a
block, with a replacement rule.

The rule is required unless the model, as entered, never wears out; each
exception (and its boundary) is allowed without a rule and each rising case
refused in plain words. How the long-run figures are worked out comes from
RePyability's ``analysis_routes()``: a simulated route is Pro, and the block
turns free on its own when RePyability reports an exact route. The simulated
availability of a Crow-AMSAA block replaced after N repairs is checked
against a hand renewal-reward calculation.
"""

import json
import math
import warnings

import pytest
from repyability.rbd.repairable_rbd import RepairableRBD

from backend.services import rbd_analysis as ra
from backend.services import rbd_export, rbd_graph, rbd_import, rbd_json
from backend.services import rbd_repairable_blocks as rrb
from backend.tests.test_mcp import A, _call, _err, _ok, env  # noqa: F401 - env is a fixture
from backend.tests.test_public_links import client  # noqa: F401 - fixture
from backend.tests.test_rbd_export import _run

warnings.filterwarnings("ignore", category=RuntimeWarning)

MTTR = 5.0
REPAIR = {"source": "params", "distribution_id": "exponential",
          "params": [{"name": "failure_rate", "value": 1 / MTTR}]}


def M(form, *values, **options):
    names = rrb.PARAMS.get(form) or rrb.ARI_PARAMS[options.get("baseline", "crow_amsaa")]
    out = {"kind": "repairable", "source": "params", "form": form,
           "params": [{"name": n, "value": v} for n, v in zip(names, values)]}
    if options:
        out["options"] = options
    return out


def _graph(model, rule=None, repairable=True, **data):
    block = {"label": "Pump", "model": model, "repair": REPAIR, **data}
    if rule is not None:
        block["replacement"] = rule
    return {"repairable": repairable, "unit": "Hours",
            "nodes": [{"id": "input", "type": "input", "data": {}},
                      {"id": "p", "type": "component", "data": block},
                      {"id": "output", "type": "output", "data": {}}],
            "edges": [{"source": "input", "target": "p"}, {"source": "p", "target": "output"}]}


def _errors(model, rule=None, **data):
    return ra.validate_graph(_graph(model, rule, **data))["errors"]


# ---------------------------------------------------------------------------
# Does it wear out? The exceptions, their boundaries, and the rising cases
# ---------------------------------------------------------------------------

NEVER = [
    ("HPP", M("hpp", 0.01)),
    ("Crow-AMSAA shape 0.7", M("crow_amsaa", 100.0, 0.7)),
    ("Crow-AMSAA shape exactly 1", M("crow_amsaa", 100.0, 1.0)),
    ("Duane shape exactly 1", M("duane", 1.0, 0.01)),
    ("Duane shape 0.6", M("duane", 0.6, 0.05)),
    ("Cox-Lewis trend exactly 0", M("cox_lewis", -4.0, 0.0)),
    ("Cox-Lewis falling", M("cox_lewis", -4.0, -0.002)),
    ("ARA Weibull shape exactly 1", M("ara", 0.5, 100.0, 1.0, m=2)),
    ("ARA Weibull shape 0.8", M("ara", 0.5, 100.0, 0.8, m=1)),
    ("ARI on Crow-AMSAA shape 0.9", M("ari", 0.5, 100.0, 0.9, m=1, baseline="crow_amsaa")),
    ("G1 shape 0.9, gaps growing", M("g1", 0.1, 100.0, 0.9)),
    ("GRP Kijima I shape 1", M("grp_i", 0.5, 100.0, 1.0)),
]

RISING = [
    ("Crow-AMSAA shape 1.01", M("crow_amsaa", 100.0, 1.01), "Crow-AMSAA, shape 1.01"),
    ("Duane shape 1.5", M("duane", 1.5, 0.01), "Duane, shape 1.5"),
    ("Cox-Lewis trend 0.001", M("cox_lewis", -4.0, 0.001), "Cox-Lewis, trend 0.001"),
    ("ARA Weibull shape 1.8", M("ara", 0.5, 100.0, 1.8, m=2), "Weibull life, shape 1.8"),
    ("ARI on Duane shape 1.4", M("ari", 0.5, 1.4, 0.01, m=1, baseline="duane"), "Duane, shape 1.4"),
    ("G1 gaps shrinking", M("g1", -0.1, 100.0, 0.9), "gaps shrinking"),
]


@pytest.mark.parametrize("name,model", NEVER, ids=[n for n, _ in NEVER])
def test_a_model_that_never_wears_out_needs_no_rule(name, model):
    process = rrb.build(model, "Pump")
    verdict = rrb.wear_verdict(process)
    assert verdict["never_wears_out"], verdict
    assert verdict["text"].startswith("No replacement needed: this model's failure rate never rises (")
    assert _errors(model) == []


@pytest.mark.parametrize("name,model,basis", RISING, ids=[n for n, *_ in RISING])
def test_a_model_that_wears_out_is_refused_without_a_rule(name, model, basis):
    verdict = rrb.wear_verdict(rrb.build(model, "Pump"))
    assert not verdict["never_wears_out"] and basis in verdict["basis"]
    assert verdict["text"].startswith("Replacement needed: this model's failure rate rises with age (")
    [msg] = _errors(model)
    assert "replacement needed" in msg and basis in msg and "availability falls towards zero" in msg
    # Calculation refuses it in the same words.
    with pytest.raises(ra.AnalysisError, match="replacement needed"):
        ra.analyze_availability(_graph(model), n_simulations=20)
    # A rule clears it.
    assert _errors(model, {"rule": "repairs", "repairs": 2}) == []
    assert _errors(model, {"rule": "age", "age": 150}) == []


def test_the_rule_is_checked_in_plain_words():
    ca = M("crow_amsaa", 100.0, 1.8)
    assert any("constant-rate model never wears out" in e
               for e in _errors(M("hpp", 0.01), {"rule": "repairs", "repairs": 2}))
    assert any("needs the age" in e for e in _errors(ca, {"rule": "age"}))
    assert any("whole number" in e for e in _errors(ca, {"rule": "repairs", "repairs": 1.5}))
    assert any("brings its own repairs" in e
               for e in _errors(ca, {"rule": "repairs", "repairs": 2}, repair_quality={"model": "kijima1", "q": 0.5}))
    assert any("clear its scheduled maintenance" in e
               for e in _errors(ca, {"rule": "age", "age": 100}, preventive={"policy": "age", "interval": 200}))
    # A non-repairable diagram can't take one.
    errors = ra.validate_graph(_graph(ca, {"rule": "repairs", "repairs": 2}, repairable=False))["errors"]
    assert any("needs a repairable diagram" in e for e in errors)
    # A rule with no repairable model.
    g = _graph(ca, {"rule": "repairs", "repairs": 2})
    g["nodes"][1]["data"]["model"] = {"source": "params", "distribution_id": "weibull",
                                      "params": [{"name": "alpha", "value": 100}, {"name": "beta", "value": 2}]}
    assert any("goes with a repairable model" in e for e in ra.validate_graph(g)["errors"])


# ---------------------------------------------------------------------------
# The numbers: a hand renewal-reward check, and how each route is priced
# ---------------------------------------------------------------------------

def test_crow_amsaa_replaced_after_n_repairs_matches_a_hand_renewal_reward():
    """Crow-AMSAA (alpha 100 h, beta 1.8), repaired minimally and replaced at the next failure after 2
    repairs (the 3rd failure), each repair (and the replacement) taking 5 h on average.

    By hand: a cycle runs to the 3rd failure of a power-law process, E[T3] = alpha * Gamma(3 + 1/beta) /
    Gamma(3) = 176.76 h of running, then is down 3 x 5 h = 15 h. Long-run availability = 176.76 / 191.76
    = 0.9218. RePyability 0.18 has no exact route for this, so it's simulated (Pro): over a long window
    the simulated mean is within its interval of the hand figure."""
    alpha, beta, n = 100.0, 1.8, 3
    t_n = alpha * math.exp(math.lgamma(n + 1 / beta) - math.lgamma(n))
    hand = t_n / (t_n + n * MTTR)
    assert t_n == pytest.approx(176.7595, rel=1e-6) and hand == pytest.approx(0.921777, rel=1e-5)

    out = ra.analyze_availability(_graph(M("crow_amsaa", alpha, beta), {"rule": "repairs", "repairs": 2}),
                                  t_simulation=100_000, n_simulations=200)
    assert out["steady_state_availability"] is None and out["availability_basis"] == "simulation"
    assert out["long_run_method"]["route"] == "refused" and "“Pump”" in out["long_run_method"]["reason"]
    prec = out["precision"]
    assert abs(prec["window_availability"] - hand) < max(3 * prec["standard_error"], 0.002)


def test_ara_is_simulated_and_priced_pro():
    g = _graph(M("ara", 0.5, 100.0, 1.8, m=2), {"rule": "repairs", "repairs": 3},
               costs={"repair": 100, "replace": 2000})
    summary = rrb.block_summary(g["nodes"][1], unit="Hours")
    assert summary["route"]["route"] == "simulated" and summary["route"]["price"] == "pro"
    assert summary["route"]["words"] == "Simulated · Pro"
    out = ra.analyze_availability(g, n_simulations=40)
    assert out["has_simulation"] and out["steady_state_availability"] is None
    assert 0 < out["precision"]["window_availability"] < 1


def test_price_follows_analysis_routes_not_the_model_family(monkeypatch):
    """When RePyability reports an exact route (as it will once it works out a minimally repaired block's
    replacement cycle), the same block is free with no change here."""
    node = _graph(M("crow_amsaa", 100.0, 1.8), {"rule": "repairs", "repairs": 2})["nodes"][1]
    assert rrb.block_summary(node, unit="Hours", want_suggestion=False)["route"]["price"] == "pro"

    real = RepairableRBD.analysis_routes

    def exact(self):
        routes = dict(real(self))
        routes["mean_availability"] = type(routes["availability"])(route="exact", reason="Renewal reward.",
                                                                   nodes=())
        return routes

    monkeypatch.setattr(RepairableRBD, "analysis_routes", exact)
    route = rrb.block_summary(node, unit="Hours", want_suggestion=False)["route"]
    assert route == {"route": "exact", "price": "free", "words": "Worked out exactly · Free"}


def test_hpp_needs_no_rule_and_is_exact():
    node = _graph(M("hpp", 0.01))["nodes"][1]
    s = rrb.block_summary(node, unit="Hours")
    assert s["rule_offered"] is False and s["rule_required"] is False
    assert s["route"]["price"] == "free" and s["route"]["route"] == "exact"
    out = ra.analyze_availability(_graph(M("hpp", 0.01)), simulate=False)
    assert out["steady_state_availability"] == pytest.approx(100 / (100 + MTTR), rel=1e-9)


# ---------------------------------------------------------------------------
# The suggested rule
# ---------------------------------------------------------------------------

def test_suggested_rule_best_age_for_a_poisson_process():
    from repyability import Repairable
    from surpyval import recurrent as rec

    g = _graph(M("crow_amsaa", 100.0, 1.8), costs={"repair": 100, "replace": 2000})
    s = rrb.block_summary(g["nodes"][1], unit="Hours")["suggestion"]
    unit = Repairable(rec.CrowAMSAA.from_params([100.0, 1.8]))
    unit.set_repair_and_overhaul_costs(100, 2000)
    want = unit.optimal_overhaul_policy().interval
    assert s["available"] and s["rule"]["rule"] == "age" and s["rule"]["suggested"]
    assert s["rule"]["age"] == pytest.approx(want, rel=1e-3)
    assert s["words"].startswith("Suggested: replace at age ") and s["words"].endswith(
        "hours (best cost; repairs assumed instant)")


def test_suggested_rule_best_repairs_for_a_renewal_process():
    g = _graph(M("ara", 0.3, 100.0, 2.5, m=1), costs={"repair": 50, "replace": 1000})
    s = rrb.block_summary(g["nodes"][1], unit="Hours")["suggestion"]
    assert s["available"] and s["rule"]["rule"] == "repairs" and s["rule"]["repairs"] >= 0
    assert s["words"].startswith("Suggested: replace ") and s["words"].endswith("(best cost)")
    # The same each time (a fixed seed).
    assert rrb.block_summary(g["nodes"][1], unit="Hours")["suggestion"]["rule"] == s["rule"]


def test_no_suggestion_without_costs_or_when_it_never_wears_out():
    s = rrb.block_summary(_graph(M("crow_amsaa", 100.0, 1.8))["nodes"][1])["suggestion"]
    assert not s["available"] and "repair cost and replacement cost" in s["reason"]
    s = rrb.block_summary(_graph(M("crow_amsaa", 100.0, 0.8), costs={"repair": 1, "replace": 9})["nodes"][1])
    assert not s["suggestion"]["available"] and s["suggestion"]["reason"].startswith("No replacement needed")


# ---------------------------------------------------------------------------
# Long-run band: refused for a no-rule block whose fit could wear out
# ---------------------------------------------------------------------------

def test_long_run_band_refused_when_the_fit_reaches_into_wear_out():
    model = {**M("crow_amsaa", 100.0, 0.95), "source": "saved", "modelId": "m1"}
    g = _graph(model)
    near = {"model": None, "results": {"params": [{"name": "alpha", "value": 100.0, "ci": [60.0, 160.0]},
                                                  {"name": "beta", "value": 0.95, "ci": [0.8, 1.12]}]}}
    clear = {"model": None, "results": {"params": [{"name": "beta", "value": 0.7, "ci": [0.55, 0.9]}]}}
    msg = rrb.long_run_band_refusal(g, lambda mid: near)
    assert msg and "No long-run band for “Pump”" in msg and "beta could be up to 1.12" in msg
    assert "bands over a set period still work" in msg
    assert rrb.long_run_band_refusal(g, lambda mid: clear) is None
    # With a rule, the draws are replaced too: no refusal.
    assert rrb.long_run_band_refusal(_graph(model, {"rule": "age", "age": 300}), lambda mid: near) is None


# ---------------------------------------------------------------------------
# Saved models, the graph format, MCP and the exports
# ---------------------------------------------------------------------------

def test_a_saved_repairable_model_resolves_by_prefix(client):
    from backend.services import models as models_service
    from backend.services import recurrent as recurrent_service
    from backend.tests.test_public_links import A

    client.act_as(A)
    db = client.db
    doc = recurrent_service.save_from_params(db, "Feed pump repairs", "crow_amsaa",
                                             [{"name": "alpha", "value": 120.0}, {"name": "beta", "value": 1.6}],
                                             2000, "hours", A)
    entry = models_service.get_live_model(db, rrb.PREFIX + doc.id, A)
    assert entry["name"] == "Feed pump repairs" and rrb.form_of(entry["model"]) == "crow_amsaa"
    stored = rbd_graph.normalize_model({"repairable_model_id": doc.id}, "node 'p'",
                                       lambda mid: models_service.get_model(db, mid, A))
    assert stored["kind"] == "repairable" and stored["source"] == "saved" and stored["modelId"] == doc.id
    assert stored["form"] == "crow_amsaa"
    assert {p["name"]: p["value"] for p in stored["params"]} == pytest.approx({"alpha": 120.0, "beta": 1.6})

    node = {"id": "p", "type": "component", "data": {"label": "Pump", "model": stored, "repair": REPAIR,
                                                      "costs": {"repair": 100, "replace": 2000},
                                                      "replacement": {"rule": "repairs", "repairs": 2}}}
    r = client.post("/api/rbds/repairable-block", json={"node": node, "unit": "Hours"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["model"]["name"] == "Feed pump repairs" and body["verdict"]["never_wears_out"] is False
    assert body["rule_words"] == "Replace after 2 repairs" and body["route"]["price"] == "pro"
    assert body["suggestion"]["available"] and body["suggestion"]["rule"]["rule"] == "age"
    r = client.post("/api/rbds/repairable-block", json={"node": {"id": "x", "type": "component", "data": {}}})
    assert r.status_code == 422 and "has no repairable model" in r.json()["detail"]


def test_repairable_blocks_over_mcp(env):
    graph = {"nodes": [{"id": "input", "type": "input"},
                       {"id": "p", "type": "component", "label": "Pump",
                        "model": {"repairable_form": "crow_amsaa",
                                  "params": [{"name": "alpha", "value": 100}, {"name": "beta", "value": 1.8}]},
                        "repair": {"distribution_id": "exponential",
                                   "params": [{"name": "failure_rate", "value": 0.2}]},
                        "replacement": {"rule": "repairs", "repairs": 2}},
                       {"id": "output", "type": "output"}],
             "edges": [{"source": "input", "target": "p"}, {"source": "p", "target": "output"}]}
    rbd = _ok(_call(env.token[A], "change", {"action": "rbd_create", "name": "Worn pump", "repairable": True,
                                             **graph}))
    node = lambda: next(n for n in env.db.rbds.find_one({"_id": rbd["id"]})["graph"]["nodes"] if n["id"] == "p")
    data = node()["data"]
    assert data["model"]["kind"] == "repairable" and data["model"]["form"] == "crow_amsaa"
    assert data["replacement"] == {"rule": "repairs", "repairs": 2}
    _ok(_call(env.token[A], "change", {"action": "rbd_edit", "rbd_id": rbd["id"], "ops": [
        {"op": "update_node", "id": "p", "replacement": {"rule": "age", "age": 400}}]}))
    assert node()["data"]["replacement"] == {"rule": "age", "age": 400.0}
    # The compact form an agent reads back writes the same block.
    got = _ok(_call(env.token[A], "get", {"kind": "rbd", "id": rbd["id"]}))
    compact = next(n for n in got["graph"]["nodes"] if n["id"] == "p")
    assert compact["model"]["repairable_form"] == "crow_amsaa" and compact["replacement"]["rule"] == "age"
    msg = _err(_call(env.token[A], "change", {"action": "rbd_edit", "rbd_id": rbd["id"], "ops": [
        {"op": "update_node", "id": "p", "replacement": {"rule": "sometimes"}}]}))
    assert "rule" in msg


def test_the_guide_explains_it():
    from backend import mcp_guide

    text = mcp_guide.TOPICS["rbds"][1] if hasattr(mcp_guide, "TOPICS") else str(mcp_guide.__dict__)
    assert "repairable_model_id" in text and "REQUIRED unless the model never wears out" in text


@pytest.mark.parametrize("model,rule", [
    (M("crow_amsaa", 100.0, 1.8), {"rule": "repairs", "repairs": 2}),
    (M("crow_amsaa", 100.0, 1.8), {"rule": "age", "age": 300.0}),
    (M("ara", 0.5, 100.0, 1.8, m=2), {"rule": "repairs", "repairs": 3}),
    (M("hpp", 0.01), None),
])
def test_json_export_round_trips(model, rule):
    g = _graph(model, rule, costs={"repair": 100, "replace": 2000})
    doc = rbd_json.to_document(g, "Worn")
    [d] = rbd_import.import_file(rbd_json.to_json(doc).encode(), "w.json")
    data = next(n for n in d.graph["nodes"] if n["type"] == "component")["data"]
    assert data["model"]["kind"] == "repairable" and data["model"]["form"] == model["form"]
    assert data.get("replacement") == rule
    # RePyability's own part loads as the diagram the app analyses.
    from repyability.rbd.serialisation import rbd_from_json

    core = {k: v for k, v in doc.items() if k != "reliafy"}
    rebuilt = rbd_from_json(json.dumps(core))
    if rule and rule["rule"] == "repairs":
        assert core["components"][0]["component"]["replace_after"] == rule["repairs"] + 1
    assert rebuilt.analysis_routes()["availability"].route == "simulated"


def test_python_export_runs_and_matches_the_app(tmp_path):
    g = _graph(M("crow_amsaa", 100.0, 1.8), {"rule": "repairs", "repairs": 2}, costs={"repair": 100, "replace": 2000})
    code = rbd_export.to_python(g, "Worn pump")
    assert "from surpyval import recurrent as rec" in code
    assert "rec.CrowAMSAA.from_params([100.0, 1.8])" in code and '"replace_after": 3' in code
    assert "Replacement needed: this model's failure rate rises with age" in code
    res, _ = _run(code, tmp_path, n_sims="40")
    app = ra.analyze_availability(g, n_simulations=40)
    assert res["n_simulations"] == app["n_simulations"] == 40
    assert res["t_simulation"] == pytest.approx(app["t_simulation"])
    for key in ("mean_up_time", "mean_down_time", "failure_frequency"):
        assert res["simulated"][key] == pytest.approx(app[key], rel=1e-9), key


def test_age_rule_python_export(tmp_path):
    g = _graph(M("crow_amsaa", 100.0, 1.8), {"rule": "age", "age": 250, "duration": 4, "cost": 1500})
    code = rbd_export.to_python(g, "Worn pump")
    assert '"preventive": {"interval": 250' in code and '"policy": "age"' in code
    res, _ = _run(code, tmp_path, n_sims="20")
    assert res["n_simulations"] == 20


def test_free_user_gets_no_simulation_for_a_simulated_block(monkeypatch):
    """Pro gating: the simulated route needs Pro. RePyability gives no exact long-run figure for this
    block yet, so a free user meets the paywall (with the free quick run offered); Pro simulates."""
    from backend.tests import test_availability_paid as paid

    fixture = paid.client.__wrapped__(monkeypatch)
    tc = next(fixture)
    try:
        g = _graph(M("crow_amsaa", 100.0, 1.8), {"rule": "repairs", "repairs": 2})
        tc.act_as(paid.FREE)
        # No exact long-run figure to fall back on: the Pro paywall, with the free quick run offered.
        r = tc.post("/api/rbds/analyze", json={"graph": g})
        assert paid._paywall(r), r.text
        tc.act_as(paid.PRO)
        body = tc.post("/api/rbds/analyze", json={"graph": g, "simulate": True}).json()
        assert body["has_simulation"] is True and 0 < body["precision"]["window_availability"] < 1
    finally:
        fixture.close()
