"""Overhaul every X, replace after N overhauls (RePyability 0.19's overhaul-and-replace policy)."""

import math

import mongomock
import numpy as np
import pytest

from backend.fitting import FitError
from backend.services.overhaul_replace import optimal_overhaul_replace
from backend.tests.test_mcp import _ok
from backend.tests.test_mcp_plans import FREE, PRO, _call, env  # noqa: F401

CROW = {"model_id": "crow_amsaa", "params": [100.0, 2.5]}
COSTS = {"cost_repair": 1, "cost_overhaul": 5, "cost_replace": 20, "overhaul_restores": 40}


def _cif(t, alpha, beta):
    return (np.asarray(t, dtype=float) / alpha) ** beta


def _brute(alpha, beta, cr, co, cp, f, kmax):
    """The cost rate g(X, K) written out from scratch (not RePyability's code) and minimised on a
    fine grid: periods of X, an overhaul keeps a share f of the age, a replacement after K periods."""
    best = (math.inf, None, None)
    for k in range(1, kmax + 1):
        x = np.linspace(5.0, 1500.0, 300_000)
        v = np.zeros_like(x)
        repairs = np.zeros_like(x)
        for _ in range(k):
            repairs += _cif(v + x, alpha, beta) - _cif(v, alpha, beta)
            v = f * (v + x)
        g = (cr * repairs + (k - 1) * co + cp) / (k * x)
        i = int(np.argmin(g))
        if g[i] < best[0]:
            best = (float(g[i]), float(x[i]), k)
    return best


def test_the_library_example_and_a_brute_force_grid_agree():
    out = optimal_overhaul_replace(CROW, **COSTS, unit="hours", max_overhauls=4)
    b = out["best"]
    # RePyability's own docstring example: K = 2 periods (one overhaul), X = 177.7, g = 0.1172.
    assert (b["overhauls"], b["cycles"]) == (1, 2)
    assert b["interval"] == pytest.approx(177.7, abs=0.05) and b["cost_rate"] == pytest.approx(0.1172, abs=5e-5)
    g, x, k = _brute(100.0, 2.5, 1.0, 5.0, 20.0, 0.6, 5)
    assert k == b["cycles"] and x == pytest.approx(b["interval"], rel=2e-3) and g == pytest.approx(b["cost_rate"], rel=1e-6)
    # The table's best X for each N is the minimum of its own row, and the best row is the best plan.
    rows = out["by_overhauls"]
    assert [r["overhauls"] for r in rows] == [0, 1, 2, 3, 4]
    assert min(rows, key=lambda r: r["cost_rate"])["best"] and rows[1]["best"]
    for r in rows:
        gk, xk, _ = _brute(100.0, 2.5, 1.0, 5.0, 20.0, 0.6, 1) if r["overhauls"] == 0 else (None, None, None)
        if gk is not None:
            assert r["interval"] == pytest.approx(xk, rel=2e-3)
    # Repairs per cycle come back from the cost rate.
    assert b["repairs_per_cycle"] == pytest.approx((b["cost_rate"] * 2 * b["interval"] - 5 - 20) / 1.0, rel=1e-9)


def test_replace_only_matches_the_closed_form():
    # N = 0: g(T) = (cr (T/a)^b + cp) / T, lowest at T* = a (cp / (cr (b - 1)))^(1/b).
    out = optimal_overhaul_replace({"model_id": "crow_amsaa", "params": [1000.0, 2.0]}, cost_repair=100,
                                   cost_overhaul=500, cost_replace=1000, overhaul_restores=50, unit="hours")
    ro = next(c for c in out["comparisons"] if c["id"] == "replace_only")
    assert ro["interval"] == pytest.approx(1000.0 * (1000 / 100) ** 0.5, rel=1e-6)
    assert out["by_overhauls"][0]["interval"] == pytest.approx(ro["interval"], rel=1e-12)
    ids = {c["id"] for c in out["comparisons"]}
    assert ids == {"run_to_failure", "overhaul_only", "replace_only"}
    assert all(c["saving_pct"] is None or c["saving_pct"] > -100 for c in out["comparisons"])


def test_a_cheaper_plan_of_another_kind_is_said():
    # In the library example, overhauling forever (no replacement) is cheaper than any plan up to 4 overhauls.
    out = optimal_overhaul_replace(CROW, **COSTS, max_overhauls=4)
    assert out["cheaper"] in ("overhaul_only", "run_to_failure")
    assert any("costs" in w and "less" in w for w in out["warnings"])
    assert "less again" in out["sentence"]


def test_no_wear_out_means_repair_on_failure():
    out = optimal_overhaul_replace({"model_id": "crow_amsaa", "params": [100.0, 1.0]}, **COSTS)
    assert out["pays"] is False and out["best"] is None and "Repair it when it fails" in out["sentence"]


def test_units_follow_the_model_and_scale():
    a = optimal_overhaul_replace(CROW, **COSTS, unit="Flight hours", max_overhauls=4)
    b = optimal_overhaul_replace({"model_id": "crow_amsaa", "params": [200.0, 2.5]}, **COSTS, unit="Flight hours",
                                 max_overhauls=4)
    assert a["unit"] == "Flight hours" and "Flight hours" in a["sentence"]
    # Twice the time scale: twice the interval, half the cost rate.
    assert b["best"]["interval"] == pytest.approx(2 * a["best"]["interval"], rel=1e-6)
    assert b["best"]["cost_rate"] == pytest.approx(a["best"]["cost_rate"] / 2, rel=1e-6)


def test_downtime_is_costed():
    plain = optimal_overhaul_replace(CROW, **COSTS, max_overhauls=4)
    down = optimal_overhaul_replace(CROW, **{**COSTS, "cost_overhaul": 3, "cost_replace": 10}, max_overhauls=4,
                                    downtime_overhaul=2, downtime_replace=5, downtime_cost=2)
    assert down["costs"]["overhaul"] == 7 and down["costs"]["replace"] == 20
    with pytest.raises(FitError, match="cost of an hour down"):
        optimal_overhaul_replace(CROW, **COSTS, downtime_repair=1)
    assert plain["best"]["interval"] != down["best"]["interval"]


@pytest.mark.parametrize("bad,match", [
    ({"cost_overhaul": 0.5}, "more than a repair"),
    ({"overhaul_restores": 0}, "takes off none"),
    ({"overhaul_restores": 120}, "percentage"),
    ({"cost_replace": None}, "replacement cost"),
])
def test_inputs_it_cant_use_say_what_to_do(bad, match):
    with pytest.raises(FitError, match=match):
        optimal_overhaul_replace(CROW, **{**COSTS, **bad})


def test_rest_route_free_saved_model_and_saved_analysis(monkeypatch):
    from backend.auth import get_current_user
    from backend.services import recurrent as recurrent_service
    from backend.tests.test_recurrent import _client

    test_db = mongomock.MongoClient()["reliafy_test"]
    client, app = _client(monkeypatch, test_db)
    # A Free account (no plan): exact maths is free.
    app.dependency_overrides[get_current_user] = lambda: {"uid": "free-a", "email": "a@x.com", "name": "A"}
    try:
        doc = recurrent_service.save_from_params(test_db, "Gearbox", "crow_amsaa",
                                                 [{"name": "alpha", "value": 100.0}, {"name": "beta", "value": 2.5}],
                                                 1000, "Flight hours", "free-a")
        body = {**COSTS, "max_overhauls": 4}
        r = client.post("/api/strategy/overhaul-replace", json={**body, "recurrent_model_id": doc.id})
        assert r.status_code == 200, r.text
        out = r.json()
        assert out["unit"] == "Flight hours" and out["best"]["cycles"] == 2
        inline = client.post("/api/strategy/overhaul-replace", json={**body, "form": "crow_amsaa",
                                                                      "params": [100.0, 2.5]}).json()
        assert inline["best"]["cost_rate"] == pytest.approx(out["best"]["cost_rate"], rel=1e-9)
        assert client.post("/api/strategy/overhaul-replace", json={**body, "recurrent_model_id": "nope"}).status_code == 404
        bad = client.post("/api/strategy/overhaul-replace", json={**body, "form": "crow_amsaa", "params": [100.0, 2.5],
                                                                   "cost_overhaul": 0.5})
        assert bad.status_code == 422 and "more than a repair" in bad.json()["detail"]
        # Saved as a strategy analysis: recomputed on the server from the inputs.
        saved = client.post("/api/strategy/analyses", json={"name": "Gearbox plan", "kind": "overhaul_replace",
                                                            "inputs": {**body, "form": "crow_amsaa",
                                                                       "params": [{"name": "alpha", "value": 100.0},
                                                                                  {"name": "beta", "value": 2.5}],
                                                                       "unit": "Flight hours"}})
        assert saved.status_code == 200, saved.text
        assert saved.json()["results"]["best"]["cycles"] == 2
        listed = client.get("/api/strategy/analyses").json()["analyses"]
        assert any(a["kind"] == "overhaul_replace" and "replace after 1" in a["headline"] for a in listed)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.usefixtures("mcp_on")
def test_mcp_action_free_and_pro_and_saved_model(env):  # noqa: F811
    from backend.services import recurrent as recurrent_service

    args = {"action": "optimal_overhaul_replace", **COSTS, "form": "crow_amsaa", "params": [100.0, 2.5],
            "unit": "hours", "max_overhauls": 4}
    pro = _ok(_call(env.oauth[PRO], "analyse", args))
    assert pro["best"]["cycles"] == 2 and "curve" not in pro and "curve_omitted" in pro
    # Exact, so a Free account gets it within its allowance.
    free = _ok(_call(env.oauth[FREE], "analyse", args))
    assert free["best"] == pro["best"]
    doc = recurrent_service.save_from_params(env.db, "Gearbox", "crow_amsaa",
                                             [{"name": "alpha", "value": 100.0}, {"name": "beta", "value": 2.5}],
                                             1000, "Flight hours", PRO)
    by_id = _ok(_call(env.oauth[PRO], "analyse", {"action": "optimal_overhaul_replace", **COSTS,
                                                   "model_id": doc.id, "max_overhauls": 4, "include_curve": True}))
    assert by_id["unit"] == "Flight hours" and by_id["curve"]["series"]
    assert by_id["best"]["cost_rate"] == pytest.approx(pro["best"]["cost_rate"], rel=1e-9)


def test_a_strategy_saved_for_a_model_on_a_position_names_its_row(monkeypatch):
    """The Explorer shows a Strategy item under a model's row only once a strategy is saved for it:
    the list says which row (the link id it was saved with)."""
    from backend.auth import get_current_user
    from backend.tests.test_recurrent import _client

    test_db = mongomock.MongoClient()["reliafy_test"]
    client, app = _client(monkeypatch, test_db)
    app.dependency_overrides[get_current_user] = lambda: {"uid": "u1", "email": "a@x.com", "name": "A"}
    try:
        inputs = {**COSTS, "form": "crow_amsaa", "params": [100.0, 2.5], "max_overhauls": 4}
        client.post("/api/strategy/analyses", json={"name": "Plain", "kind": "overhaul_replace", "inputs": inputs})
        client.post("/api/strategy/analyses", json={"name": "On a row", "kind": "overhaul_replace",
                                                    "inputs": {**inputs, "position_link_id": "L-1",
                                                               "position_id": "P-1"}})
        rows = {a["name"]: a for a in client.get("/api/strategy/analyses").json()["analyses"]}
        assert "position_link_id" not in rows["Plain"] and rows["On a row"]["position_link_id"] == "L-1"
    finally:
        app.dependency_overrides.clear()
