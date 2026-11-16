"""Lives on two clocks (hours and starts): the fit recovers a simulated fleet's
parameters, the life at a rate matches SurPyval called directly, a saved model
round-trips, and the REST routes serve it (free)."""

import io
import math

import mongomock
import numpy as np
import pandas as pd
import pytest
import surpyval as sp

from backend import fitting, two_clocks
from backend.fitting import FitError

OWNER = "user-two-clocks"
MAPPING = {"x": "hours", "x2": "starts", "c": "c"}
TRUE_K, TRUE_ALPHA, TRUE_BETA = 20.0, 30000.0, 2.5


def fleet(n: int = 240, seed: int = 42) -> pd.DataFrame:
    """A simulated fleet in three duties (SurPyval's worked example): one start is
    worth 20 hours, Weibull(30,000, 2.5) on the combined clock."""
    rng = np.random.default_rng(seed)
    rate = rng.choice([0.01, 0.05, 0.3], n, p=[0.4, 0.35, 0.25])
    life = TRUE_ALPHA * rng.weibull(TRUE_BETA, n) / (1 + TRUE_K * rate)
    followed = rng.uniform(5000, 25000, n)
    failed = life < followed
    hours = np.where(failed, life, followed)
    return pd.DataFrame({"hours": hours.round(0), "starts": np.round(rate * hours), "c": np.where(failed, 0, 1)})


@pytest.fixture(scope="module")
def fitted():
    return two_clocks.fit("weibull_two_clock", fleet(), MAPPING, "Hours")


def test_fit_recovers_the_simulated_fleet(fitted):
    model, result = fitted
    p = {r["name"]: r for r in result["params"]}
    assert result["kind"] == "two_clock"
    # The truth inside each 90% interval, the estimates close to SurPyval's documented ones.
    assert p["k"]["ci"][0] < TRUE_K < p["k"]["ci"][1]
    assert p["beta"]["ci"][0] < TRUE_BETA < p["beta"]["ci"][1]
    assert p["alpha"]["ci"][0] < TRUE_ALPHA < p["alpha"]["ci"][1]
    assert round(model.k, 1) == 18.4
    assert result["k_test"]["matters"] and result["k_test"]["p_value"] < 1e-50
    assert result["split"] == {"failed": 144, "running": 96}
    assert result["rates"] == {"typical": 0.05, "low": 0.00998, "high": 0.3}
    assert result["headline"].startswith("Wears by starts and by hours: one start wears it as much as 18.4 hours")
    assert "1 start every 20 hours" in result["headline"]


def test_life_at_a_rate_matches_surpyval_called_directly(fitted):
    model, _ = fitted
    direct = sp.WeibullEquivalence.fit(fleet()["hours"], fleet()["starts"], c=fleet()["c"])
    out = two_clocks.answer(model, {"rate": 0.125, "times": [1000, 4000], "reliability": [0.9]}, "Hours")
    life = direct.at_usage(0.125)
    b10 = next(b for b in out["life"]["b_lives"] if b["label"] == "B10")
    assert b10["value"] == pytest.approx(float(life.qf(0.1)), rel=1e-6)
    assert b10["lower"] == pytest.approx(float(life.quantile_cb(0.1, alpha_ci=0.1, bound="lower")), rel=1e-4)
    assert b10["lower"] < b10["value"]
    assert out["at_times"][1]["reliability"] == pytest.approx(float(life.sf(4000)), rel=1e-6)
    assert out["at_times"][1]["lower"] == pytest.approx(
        float(np.ravel(life.cb(4000, alpha_ci=0.1, bound="lower"))[0]), rel=1e-4)
    assert out["acceleration"] == pytest.approx(1 + model.k * 0.125)
    assert out["rate_words"] == "1 start every 8 hours"
    assert out["time_at_reliability"]["points"][0]["time"] == pytest.approx(float(life.qf(0.1)), rel=1e-6)


def test_round_trip_keeps_the_numbers_and_bounds(fitted):
    model, _ = fitted
    back = two_clocks.from_dict(model.to_dict())
    assert two_clocks.is_model(back)
    a, b = model.at_usage(0.2), back.at_usage(0.2)
    assert b.qf(0.1) == pytest.approx(a.qf(0.1))
    np.testing.assert_allclose(b.quantile_cb(0.1, alpha_ci=0.1), a.quantile_cb(0.1, alpha_ci=0.1), rtol=1e-9)


def test_refusals_say_what_to_do():
    df = fleet()
    with pytest.raises(FitError, match="model on hours and starts"):
        fitting.fit("weibull", df, MAPPING)
    with pytest.raises(FitError, match="starts \\(second clock\\) column"):
        fitting.fit("weibull_two_clock", df, {"x": "hours", "c": "c"})
    same = df.assign(starts=(df["hours"] * 0.1).round(6))
    with pytest.raises(FitError):
        fitting.fit("weibull_two_clock", same, MAPPING)
    with pytest.raises(FitError, match="late entry"):
        fitting.fit("weibull_two_clock", df.assign(tl=0), {**MAPPING, "tl": "tl"})
    with pytest.raises(two_clocks.TwoClockError, match="usage rate"):
        two_clocks.check_rate(-1)


@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", True)  # Free plan: the fit and the rate stay free
    test_db = mongomock.MongoClient()["reliafy_two_clocks"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    app.dependency_overrides[get_current_user] = lambda: {"uid": OWNER, "email": "t@example.org", "name": "T"}
    tc = TestClient(app)
    tc.db = test_db
    try:
        yield tc
    finally:
        app.dependency_overrides.clear()


def _files():
    return {"file": ("fleet.csv", io.BytesIO(fleet().to_csv(index=False).encode()), "text/csv")}


def test_listed_fitted_saved_and_used_at_a_rate_on_free(client):
    listed = client.get("/api/distributions").json()["distributions"]
    assert {d["id"] for d in listed if d.get("two_clock")} == set(two_clocks.MODELS)

    r = client.post("/api/fit/weibull_two_clock", data={"x": "hours", "x2": "starts", "c": "c", "unit": "hours"},
                    files=_files())
    assert r.status_code == 200, r.text
    fresh = r.json()
    assert fresh["kind"] == "two_clock" and fresh["unit"] == "Hours"
    at = client.post(fresh["functions"]["at_rate_path"], json={"rate": 0.3}).json()
    assert at["rate_words"] == "1 start every 3.33 hours"

    r = client.post("/api/models", data={"name": "Turbines", "distribution": "weibull_two_clock", "x": "hours",
                                         "x2": "starts", "c": "c", "unit": "hours"}, files=_files())
    assert r.status_code == 200, r.text
    saved = r.json()
    assert saved["kind"] == "two_clock"
    # Brought back from its saved to_dict, not refitted: the same numbers.
    from backend.services import models as models_service

    models_service._LIVE.clear()
    out = client.post(f"/api/models/{saved['id']}/at-rate", json={"rate": 0.3}).json()
    assert out["life"]["b_lives"][2]["value"] == pytest.approx(at["life"]["b_lives"][2]["value"], rel=1e-9)
    default = client.post(f"/api/models/{saved['id']}/at-rate", json={}).json()
    assert default["rate"] == 0.05
    bad = client.post(f"/api/models/{saved['id']}/at-rate", json={"rate": "fast"})
    assert bad.status_code == 422 and "starts per hour" in bad.json()["detail"]
    script = client.get(f"/api/models/{saved['id']}/export.py")
    assert script.status_code == 200, script.text
    assert "WeibullEquivalence.fit_from_df" in script.text and "at_usage(RATE)" in script.text


# ---- an RBD block at a rate -------------------------------------------------------------

def _save_two_clock(db, name="Turbines"):
    from backend.services import datasets as datasets_service
    from backend.services import models as models_service

    ds = datasets_service.create_dataset(db, "fleet", fleet().to_csv(index=False).encode(), OWNER)
    return models_service.save_model(db, name, ds, "weibull_two_clock", MAPPING, None, None, "hours",
                                     owner_id=OWNER)


def _diagram(block, n=1):
    node = {"id": "a", "type": "component", "data": {"label": "Turbine", "model": block}}
    if n > 1:
        node = {"id": "a", "type": "series", "data": {"label": "Turbines", "model": block, "n": n}}
    return {"unit": "hours", "nodes": [{"id": "input", "type": "input", "data": {}}, node,
                                       {"id": "output", "type": "output", "data": {}}],
            "edges": [{"id": "e1", "source": "input", "target": "a"},
                      {"id": "e2", "source": "a", "target": "output"}]}


@pytest.fixture()
def rbd_db(monkeypatch):
    from backend import db as db_mod

    d = mongomock.MongoClient()["rbd_two_clocks"]
    monkeypatch.setattr(db_mod, "_db", d)
    monkeypatch.setattr(db_mod, "_simulated", True)
    return d


@pytest.mark.parametrize("native", [False, True])
def test_rbd_block_at_a_rate_matches_a_hand_calculation(rbd_db, monkeypatch, native):
    from backend.services import rbd_analysis as ra
    from backend.services import rbd_two_clocks, rbds, repy_compat

    if native and not repy_compat.native_usage_blocks():
        # RePyability 0.19 still analyses a LifeAtUsage (it has sf/ff/random); the native block adds saving
        # and the lever. Forced here so the native path is covered before the pin moves.
        monkeypatch.setattr(repy_compat, "native_usage_blocks", lambda: True)
    elif not native:
        monkeypatch.setattr(repy_compat, "native_usage_blocks", lambda: False)
    doc = _save_two_clock(rbd_db)
    alpha, beta, k = (p["value"] for p in doc.results["params"])
    block = {"source": "saved", "kind": "two_clock", "modelId": doc.id, "usage_rate": 0.125}
    _, resolve_model = rbds.resolvers(rbd_db, OWNER)
    out = ra.analyze(_diagram(block), resolve_model=resolve_model, at_times=[1000.0, 5000.0])
    a = 1 + k * 0.125  # combined hours per running hour
    hand = [math.exp(-((t * a / alpha) ** beta)) for t in (1000.0, 5000.0)]
    assert out["at"]["sf"] == pytest.approx(hand, rel=1e-6)
    three = ra.analyze(_diagram(block, n=3), resolve_model=resolve_model, at_times=[1000.0])
    assert three["at"]["sf"][0] == pytest.approx(hand[0] ** 3, rel=1e-6)
    life = rbd_two_clocks.block_life(block, "Turbine", resolve_model)
    assert (type(life).__name__ == "LifeAtUsage") == native


def test_rbd_block_without_a_rate_says_to_set_one(rbd_db):
    from backend.services import rbd_analysis as ra
    from backend.services import rbds

    doc = _save_two_clock(rbd_db)
    _, resolve_model = rbds.resolvers(rbd_db, OWNER)
    with pytest.raises(ra.AnalysisError, match="starts per running hour"):
        ra.analyze(_diagram({"source": "saved", "kind": "two_clock", "modelId": doc.id}),
                   resolve_model=resolve_model, at_times=[1000.0])


# ---- the Explorer: the rate from the operating plan -------------------------------------

WEEKDAYS_6_TO_22 = {"background": {"kind": "shifts", "shifts": [
    {"days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"], "start": "06:00", "stop": "22:00"}]}}


def test_explorer_rate_comes_from_the_operating_plan_and_can_be_overridden(rbd_db):
    from backend.maintenance import position_models as pm
    from backend.maintenance.service import PROJECTORS, Invalid, Maintenance
    from backend.maintenance.store import GraphStore

    m = Maintenance(GraphStore(":memory:", PROJECTORS), OWNER, "tester")
    doc = _save_two_clock(rbd_db)
    owners = [OWNER]
    pump = m.create_position("Gas turbine 1")["id"]
    link = pm.link_saved(m, rbd_db, owners, set(), pump, "model", doc.id)

    # No plan yet: the fleet's typical rate, said so.
    d = pm.detail(m, rbd_db, owners, set(), link["id"])
    assert d["two_clock"]["usage_rate"]["source"] == "fleet" and d["two_clock"]["usage_rate"]["rate"] == 0.05

    # Weekdays 06:00-22:00: one run (one start) a weekday of 16 hours, so 1/16 start per hour.
    m.set_operating_plan(pump, WEEKDAYS_6_TO_22, name="Day shifts")
    d = pm.detail(m, rbd_db, owners, set(), link["id"])
    rate = d["two_clock"]["usage_rate"]
    assert rate["source"] == "plan" and rate["rate"] == pytest.approx(1 / 16, rel=1e-6)
    assert rate["text"].startswith("From the operating plan")
    at = d["two_clock"]["at_rate"]
    assert at["rate_words"] == "1 start every 16 hours" and at["source"]["kind"] == "plan"
    live = sp.from_dict(doc.serialized["model"])
    assert at["life"]["b_lives"][2]["value"] == pytest.approx(float(live.at_usage(1 / 16).qf(0.1)), rel=1e-9)

    # Set by hand wins, says the plan's rate beside it, replays, and clears back to the plan.
    m.set_link_usage_rate(link["id"], 0.5)
    d = pm.detail(m, rbd_db, owners, set(), link["id"])
    assert d["two_clock"]["usage_rate"]["source"] == "set" and d["two_clock"]["usage_rate"]["rate"] == 0.5
    assert "operating plan gives 1 start every 16 hours" in d["two_clock"]["usage_rate"]["text"]
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before
    m.set_link_usage_rate(link["id"], None)
    assert pm.detail(m, rbd_db, owners, set(), link["id"])["two_clock"]["usage_rate"]["source"] == "plan"
    with pytest.raises(Invalid, match="starts per hour"):
        m.set_link_usage_rate(link["id"], -2)


def test_strategy_gets_the_plain_distribution_at_the_rate(fitted):
    model, _ = fitted
    dist = two_clocks.answer(model, {"rate": 0.2}, "Hours")["as_distribution"]
    plain = sp.Weibull.from_params([p["value"] for p in dist["params"]])
    t = np.array([500.0, 3000.0, 9000.0])
    np.testing.assert_allclose(plain.sf(t), model.at_usage(0.2).sf(t), rtol=1e-12)
    assert dist["distribution_id"] == "weibull"


# ---- tools: MCP and its REST twin --------------------------------------------------------

@pytest.mark.usefixtures("mcp_on")
def test_tools_fit_save_and_use_at_a_rate(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.routers import ingest as ingest_router
    from backend.services import tokens

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    test_db = mongomock.MongoClient()["reliafy_two_clock_tools"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    ingest_router._hits.clear()
    test_db.users.insert_one({"_id": OWNER, "email": "t@example.org", "name": "T", "plan": "pro",
                              "email_verified": True})
    head = {"Authorization": f"Bearer {tokens.create_token(test_db, OWNER, 'api')['token']}"}
    client = TestClient(__import__("backend.main", fromlist=["app"]).app)
    df = fleet()
    body = {"distribution": "weibull_two_clock", "data": df["hours"].tolist(), "second_clock": df["starts"].tolist(),
            "censored": df["c"].tolist(), "unit": "hours"}
    r = client.post("/api/v1/analyse/fit", json=body, headers=head)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["kind"] == "two_clock" and out["answer"].startswith("Wears by")
    assert {p["name"] for p in out["params"]} == {"alpha", "beta", "k"}
    r = client.post("/api/v1/change/model_fit", json={**body, "name": "Turbines"}, headers=head)
    assert r.status_code == 200, r.text
    mid = r.json()["model_id"]
    at = client.post("/api/v1/analyse/reliability_at", json={"model_id": mid, "times": [4000],
                                                              "usage_rate": 0.125}, headers=head).json()
    direct = sp.WeibullEquivalence.fit(df["hours"], df["starts"], c=df["c"]).at_usage(0.125)
    assert at["points"][0]["reliability"] == pytest.approx(float(direct.sf(4000)), rel=1e-6)
    assert at["points"][0]["reliability_lower_90"] < at["points"][0]["reliability"]
    # A starts column with a one-clock model is refused in words.
    bad = client.post("/api/v1/analyse/fit", json={**body, "distribution": "weibull"}, headers=head)
    assert "hours and starts" in bad.text
