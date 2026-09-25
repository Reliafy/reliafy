"""Optimal overhaul interval (minimal repair + overhaul, via RePyability)."""

import mongomock
import numpy as np
import pytest

from backend.tests.test_recurrent import _client

A = "user-a"
B = "user-b"


def _crow(alpha, beta):
    from surpyval.recurrent import CrowAMSAA

    return CrowAMSAA.from_params([alpha, beta])


@pytest.mark.parametrize("alpha,beta,cr,co", [(1000.0, 2.0, 100.0, 1000.0), (250.0, 1.4, 3.0, 50.0), (5e4, 3.5, 1.0, 400.0)])
def test_crow_amsaa_deteriorating_has_finite_optimum_matching_closed_form(alpha, beta, cr, co):
    from backend import recurrent as rec
    from repyability.repairable import Repairable

    out = rec.optimal_overhaul(_crow(alpha, beta), cr, co)
    opt = out["optimal"]
    assert opt is not None and np.isfinite(opt["interval"]) and opt["interval"] > 0
    t_star = opt["interval"]

    # It's a minimum of the long-run cost rate g(T) = (cr·Λ(T) + co) / T.
    r = Repairable(_crow(alpha, beta))
    r.set_repair_and_overhaul_costs(cr, co)
    assert opt["cost_rate"] <= r.cost_rate(0.5 * t_star)
    assert opt["cost_rate"] <= r.cost_rate(2.0 * t_star)

    # Closed form for the power-law NHPP. Reliafy's Crow-AMSAA cif is
    # Λ(t) = (t/α)^β, i.e. λ·t^β with λ = α^-β, so
    # T* = [co / ((β−1)·cr·λ)]^(1/β) = α·[co / ((β−1)·cr)]^(1/β).
    lam = alpha ** -beta
    closed = (co / ((beta - 1.0) * cr * lam)) ** (1.0 / beta)
    assert t_star == pytest.approx(closed, rel=1e-5)
    # ...and Λ(T*) = co / (cr·(β−1)), g(T*) = β·cr·Λ(T*)/T*.
    assert opt["expected_failures_per_cycle"] == pytest.approx(co / (cr * (beta - 1.0)), rel=1e-4)
    assert out["shape"] == pytest.approx(beta)

    # Curve for the chart brackets T*, and no-overhaul costs more over it.
    t = out["curve"]["t"]
    assert len(t) == 200 and t[0] < t_star < t[-1]
    assert out["never_overhaul"]["cost_rate"] > opt["cost_rate"] and out["saving_pct"] > 0


def test_improving_system_has_no_optimum():
    from backend import recurrent as rec

    out = rec.optimal_overhaul(_crow(1000.0, 0.7), 100, 1000)
    assert out["optimal"] is None and "decreasing" in out["reason"]
    assert out["never_overhaul"]["limit_cost_rate"] == 0.0


def test_params_spec_is_accepted():
    from backend import recurrent as rec

    out = rec.optimal_overhaul({"model_id": "crow_amsaa", "params": [{"name": "alpha", "value": 1000}, {"name": "beta", "value": 2}]}, 100, 1000)
    assert out["optimal"]["interval"] == pytest.approx(1000 * 10 ** 0.5, rel=1e-5)


def test_hpp_has_no_optimum():
    from backend import recurrent as rec
    from surpyval.recurrent import HPP

    x = np.cumsum(np.random.default_rng(0).exponential(10.0, 50))
    out = rec.optimal_overhaul(HPP.fit(x), 100, 1000)
    assert out["optimal"] is None and "constant" in out["reason"]
    assert out["never_overhaul"]["limit_cost_rate"] > 0


@pytest.mark.parametrize("cr,co", [(0, 100), (-5, 100), (10, 0), (10, -1), ("x", 100), (100, 100), (200, 100)])
def test_invalid_costs_raise(cr, co):
    from backend import recurrent as rec
    from backend.fitting import FitError

    with pytest.raises(FitError):
        rec.optimal_overhaul(_crow(1000.0, 2.0), cr, co)


def test_api_overhaul_owner_share_and_isolation(monkeypatch):
    from backend.auth import get_current_user

    test_db = mongomock.MongoClient()["reliafy_test"]
    client, app = _client(monkeypatch, test_db)
    user = {"uid": A}
    app.dependency_overrides[get_current_user] = lambda: {"uid": user["uid"], "email": f"{user['uid']}@x.com", "name": user["uid"]}
    try:
        r = client.post("/api/recurrent/from-params", data={
            "name": "Pump fleet", "model": "crow_amsaa", "alpha": 1000, "beta": 2.0, "horizon": 5000, "unit": "hours"})
        assert r.status_code == 200, r.text
        mid = r.json()["id"]
        url = f"/api/recurrent/models/{mid}/overhaul"

        r = client.post(url, json={"cost_repair": 100, "cost_overhaul": 1000})
        assert r.status_code == 200, r.text
        assert r.json()["optimal"]["interval"] == pytest.approx(1000 * 10 ** 0.5, rel=1e-5)

        # Non-positive / missing / inverted costs -> 422 with a string detail.
        for body in ({"cost_repair": 0, "cost_overhaul": 1000}, {"cost_repair": 100, "cost_overhaul": -1},
                     {"cost_repair": 100}, {"cost_repair": 500, "cost_overhaul": 100}):
            r = client.post(url, json=body)
            assert r.status_code == 422 and isinstance(r.json()["detail"], str)

        # Another user can't see it...
        user["uid"] = B
        assert client.post(url, json={"cost_repair": 100, "cost_overhaul": 1000}).status_code == 404

        # ...but a read-only viewer may compute it (recurrent models aren't in
        # SHARABLE_COLLECTIONS yet, so use the read-only sample path).
        from backend import config

        test_db.recurrent_models.update_one({"_id": mid}, {"$set": {"owner_id": config.SAMPLE_OWNER}})
        before = test_db.recurrent_models.find_one({"_id": mid})
        assert client.get(f"/api/recurrent/models/{mid}").json()["read_only"] is True
        r = client.post(url, json={"cost_repair": 100, "cost_overhaul": 1000})
        assert r.status_code == 200, r.text
        assert r.json()["optimal"] is not None
        assert test_db.recurrent_models.find_one({"_id": mid}) == before  # computing wrote nothing
    finally:
        app.dependency_overrides.clear()
