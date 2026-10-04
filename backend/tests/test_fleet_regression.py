"""Fleet forecasts from regression and ALT models, exact intervals and a
warranty limit (#234).

The first-failures forecast is SurPyval 0.23's ``forecast``. Each item adds
its own use per period, which Reliafy gives ``forecast`` as a per-item clock
(``fleet._ItemClock``); every check here is against the library called
directly (or, for mixed rates, a brute-force Poisson-binomial), never against
Reliafy's own numbers.
"""

import io

import matplotlib

matplotlib.use("Agg")

import mongomock
import numpy as np
import pandas as pd
import pytest
import surpyval as sp

from backend.tests.test_mcp import env  # noqa: F401 - a fixture

A = "user-a"
USERS = {A: {"uid": A, "email": "a@x.com", "name": "A", "email_verified": True}}


@pytest.fixture()
def session(monkeypatch):
    from backend import db

    test_db = mongomock.MongoClient()["reliafy_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    yield test_db


@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", True)
    test_db = mongomock.MongoClient()["reliafy_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    app.dependency_overrides[get_current_user] = lambda: USERS[A]
    test_db.users.update_one({"_id": A}, {"$set": {"email": "a@x.com", "email_lc": "a@x.com",
                                                  "email_verified": True, "name": "A", "plan": "pro"}},
                             upsert=True)
    tc = TestClient(app)
    tc.db = test_db
    try:
        yield tc
    finally:
        app.dependency_overrides.clear()


def _csv(df: pd.DataFrame) -> bytes:
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue().encode()


def _life_csv() -> bytes:
    rng = np.random.default_rng(7)
    return _csv(pd.DataFrame({"t": np.round(rng.weibull(2.5, 80) * 1000, 2)}))


def _regression_csv() -> bytes:
    rng = np.random.default_rng(3)
    n = 200
    load = rng.uniform(0.5, 1.5, n)
    site = rng.choice(["A", "B"], n)
    x = sp.Weibull.random(n, 1000, 2.0, random_state=rng) * np.exp(-0.8 * (load - 1)) * np.where(site == "B", 0.7, 1)
    c = (x > 1500).astype(int)
    return _csv(pd.DataFrame({"t": np.round(np.minimum(x, 1500), 3), "c": c, "load": np.round(load, 3),
                              "site": site}))


def _alt_csv() -> bytes:
    rng = np.random.default_rng(11)
    rows = []
    for T in (320.0, 340.0, 360.0):
        for xv in np.abs(sp.Weibull.random(30, np.exp(3600.0 / T), 2.1, random_state=rng)):
            rows.append({"hours": round(float(xv), 2), "tempK": T})
    return _csv(pd.DataFrame(rows))


def _life_model(session):
    from backend.services import datasets as ds
    from backend.services import models as ms

    dataset = ds.create_dataset(session, "life.csv", _life_csv(), A)
    return ms.save_model(session, "life", dataset, "weibull", {"x": "t"}, [], None, owner_id=A)


def _regression_model(session):
    from backend.services import datasets as ds
    from backend.services import models as ms

    dataset = ds.create_dataset(session, "reg.csv", _regression_csv(), A)
    return ms.save_model(session, "ph", dataset, "weibull_ph", {"x": "t", "c": "c"}, [], "load + site",
                         owner_id=A)


def _alt_model(session):
    from backend.services import alt as alt_service
    from backend.services import datasets as ds

    dataset = ds.create_dataset(session, "alt.csv", _alt_csv(), A)
    return alt_service.save_model(session, "arrhenius", dataset, {
        "mapping": {"x": "hours"}, "stress_cols": ["tempK"], "distribution_id": "weibull",
        "life_model_id": "arrhenius", "unit": "hours"}, A)


def _fleet(session, model_id, items, settings, model_kind=None):
    from backend.services import fleet as fs

    fleet = fs.create_fleet(session, "F", model_id, A, model_kind)
    base = {"periods": 6, "period_label": "months", "default_rate": 50.0, "method": "single"}
    return fs.replace_items(session, fleet.id, {**base, **settings}, items, A)


def _same(ours: dict, theirs):
    """Our first-failure forecast against ``surpyval.forecast`` at 80%."""
    assert ours["status"] == "ok", ours
    assert ours["interval_method"] == "exact" and ours["interval_level"] == 0.8
    assert ours["expected"] == pytest.approx(theirs.expected[-1], rel=1e-9)
    assert ours["interval"] == [theirs.lower[-1], theirs.upper[-1]]
    assert ours["per_period"] == pytest.approx(list(theirs.period_expected), rel=1e-9, abs=1e-12)
    assert ours["per_period_interval"] == [[a, b] for a, b in zip(theirs.period_lower, theirs.period_upper)]
    assert [r["prob_any"] for r in ours["per_item"]] == pytest.approx(list(theirs.probability[:, -1]), rel=1e-9)


# ---- Plain distributions: the exact interval ---------------------------------------

def test_single_forecast_is_surpyvals_forecast(session):
    from backend.services import fleet as fs

    model = _life_model(session)
    ages = [0.0, 250.0, 600.0, 900.0, 1400.0]
    fleet = _fleet(session, model.id, [{"name": f"i{k}", "current_use": a} for k, a in enumerate(ages)], {})
    ours = fs.compute(session, fleet, A, item_periods=True)
    dist = sp.Weibull.from_params([p["value"] for p in model.results["params"]])
    theirs = sp.forecast(dist, age=ages, horizon=50.0 * np.arange(1, 7), alpha_ci=0.2)
    _same(ours, theirs)
    # Whole failures at the interval's ends; item_periods gives each item's curve.
    assert all(float(v).is_integer() for v in ours["interval"])
    for row, curve in zip(ours["per_item"], theirs.probability):
        assert row["probability_by_period"] == pytest.approx(list(curve), rel=1e-9)
    assert "probability_by_period" not in fs.compute(session, fleet, A)["per_item"][0]


def test_mixed_rates_against_a_brute_force_poisson_binomial(session):
    """Each item on its own clock: probabilities from the model's conditional
    survival over its own use, and the interval of their exact sum."""
    from backend.services import fleet as fs

    model = _life_model(session)
    items = [{"name": "a", "current_use": 100, "rate": 10}, {"name": "b", "current_use": 700, "rate": 80},
             {"name": "c", "current_use": 300}, {"name": "d", "current_use": 1200, "rate": 0},
             {"name": "e", "current_use": 50, "rate": 150}]
    fleet = _fleet(session, model.id, items, {"periods": 4})
    ours = fs.compute(session, fleet, A)
    dist = sp.Weibull.from_params([p["value"] for p in model.results["params"]])
    rates = np.array([10, 80, 50, 0, 150], dtype=float)
    ages = np.array([100, 700, 300, 1200, 50], dtype=float)
    p = 1 - np.asarray(dist.cs(rates * 4, ages))
    assert [r["prob_any"] for r in ours["per_item"]] == pytest.approx(list(p), rel=1e-9)
    assert ours["per_item"][3]["prob_any"] == 0.0  # no use, no failure
    pmf = np.array([1.0])
    for pi in p:
        pmf = np.convolve(pmf, [1 - pi, pi])
    cdf = np.cumsum(pmf)
    lo, hi = np.searchsorted(cdf, [0.1, 0.9])
    assert ours["interval"] == [float(lo), float(hi)]
    assert ours["expected"] == pytest.approx(p.sum(), rel=1e-9)
    assert sum(ours["per_period"]) == pytest.approx(ours["expected"], rel=1e-9)


def test_use_and_calendar_warranty_limits(session):
    from backend.services import fleet as fs

    model = _life_model(session)
    dist = sp.Weibull.from_params([p["value"] for p in model.results["params"]])
    ages = [100.0, 400.0, 800.0]
    items = [{"name": f"i{k}", "current_use": a} for k, a in enumerate(ages)]
    horizon = 50.0 * np.arange(1, 7)

    # A use limit is forecast's own `limit` on the model's time scale.
    fleet = _fleet(session, model.id, items, {"warranty_use": 600})
    _same(fs.compute(session, fleet, A), sp.forecast(dist, age=ages, horizon=horizon, limit=600, alpha_ci=0.2))
    out = fs.compute(session, fleet, A)
    assert out["out_of_warranty"] == 1 and out["per_item"][2]["prob_any"] == 0.0

    # A calendar limit ends W periods after entering service: at a constant
    # rate that is a use limit of age + rate * (W - in service).
    timed = [{**it, "service_periods": s} for it, s in zip(items, (1.0, 5.0, 2.0))]
    fleet = _fleet(session, model.id, timed, {"warranty_periods": 8})
    limits = [a + 50.0 * (8 - s) for a, s in zip(ages, (1.0, 5.0, 2.0))]
    _same(fs.compute(session, fleet, A), sp.forecast(dist, age=ages, horizon=horizon, limit=limits, alpha_ci=0.2))
    # Without service_periods, time in service is read off use / rate.
    fleet = _fleet(session, model.id, items, {"warranty_periods": 8})
    limits = [a + 50.0 * (8 - a / 50.0) for a in ages]
    _same(fs.compute(session, fleet, A), sp.forecast(dist, age=ages, horizon=horizon, limit=limits, alpha_ci=0.2))


def test_an_item_past_the_models_support_counts_as_certain():
    """sf(age) = 0: no conditional chance to take, so it fails in period 1."""
    from backend.services import fleet as fs

    class Bounded:  # survival 1 - x/1000 on [0, 1000]
        def sf(self, x):
            return np.clip(1 - np.asarray(x, float) / 1000.0, 0, 1)

    items = [{"id": "a", "name": "fine"}, {"id": "b", "name": "past it"}]
    out = fs._forecast_single(Bounded(), np.array([100.0, 1200.0]), np.array([10.0, 10.0]), 3, items)
    assert out["per_item"][1]["prob_any"] == 1.0
    p = 1 - (1 - 130 / 1000) / (1 - 100 / 1000)
    assert out["expected"] == pytest.approx(1 + p)
    assert out["per_period"][0] == pytest.approx(1 + 1 - (1 - 110 / 1000) / 0.9)
    assert out["interval"][0] >= 1 and "past the age" in out["warnings"][0]


# ---- Regression models: each item at its own covariates -------------------------

def test_regression_fleet_forecasts_each_item_at_its_covariates(session):
    from backend.services import fleet as fs
    from backend.services import models as ms

    model = _regression_model(session)
    fleet = fs.create_fleet(session, "F", model.id, A)
    assert fleet.model_kind == "regression"
    assert fleet.settings["method"] == "single"  # a regression fleet counts first failures
    items = [{"name": "light", "current_use": 200, "covariates": {"load": 0.6, "site": "A"}},
             {"name": "heavy", "current_use": 500, "covariates": {"load": 1.4}},
             {"name": "default", "current_use": 800}]
    fleet = _fleet(session, model.id, items, {"covariates": {"site": "B"}})
    ours = fs.compute(session, fleet, A)
    entry = ms.get_live_model(session, model.id, A)
    load_default = next(f["default"] for f in entry["fields"] if f["name"] == "load")
    Z = pd.DataFrame({"load": [0.6, 1.4, load_default], "site": ["A", "B", "B"]})
    theirs = sp.forecast(entry["model"], age=[200, 500, 800], Z=Z, horizon=50.0 * np.arange(1, 7), alpha_ci=0.2)
    _same(ours, theirs)
    assert ours["model_kind"] == "regression"
    assert [f["name"] for f in ours["covariate_fields"]] == ["load", "site"]
    assert ours["per_item"][1]["covariates"] == {"load": 1.4, "site": "B"}
    assert ours["per_item"][2]["covariates"] == {"load": load_default, "site": "B"}


def test_regression_fleet_refusals(session):
    from backend.services import fleet as fs

    model = _regression_model(session)
    items = [{"name": "x", "current_use": 100}]
    renew = fs.compute(session, _fleet(session, model.id, items, {"method": "renewals"}), A)
    assert renew["status"] == "stale" and "first failures" in renew["reason"]
    typo = fs.compute(session, _fleet(session, model.id, items, {"covariates": {"lod": 1}}), A)
    assert typo["status"] == "stale" and "lod" in typo["reason"] and "load" in typo["reason"]
    level = fs.compute(session, _fleet(session, model.id, [{**items[0], "covariates": {"site": "C"}}], {}), A)
    assert level["status"] == "stale" and "one of A, B" in level["reason"]
    word = fs.compute(session, _fleet(session, model.id, [{**items[0], "covariates": {"load": "heavy"}}], {}), A)
    assert word["status"] == "stale" and "must be a number" in word["reason"]
    with pytest.raises(fs.FleetValidationError):
        _fleet(session, model.id, [{**items[0], "covariates": ["load", 1]}], {})


# ---- ALT models: each item at its own stress --------------------------------------

def test_alt_fleet_forecasts_each_item_at_its_stress(session):
    from backend.services import alt as alt_service
    from backend.services import fleet as fs

    model = _alt_model(session)
    items = [{"name": "cool", "current_use": 2000, "covariates": {"tempK": 300}},
             {"name": "hot", "current_use": 1000}]
    missing = fs.compute(session, _fleet(session, model.id, items, {}, model_kind="alt"), A)
    assert missing["status"] == "stale" and "tempK" in missing["reason"]
    assert missing["covariate_fields"] == [{"name": "tempK", "label": "tempK", "type": "number", "default": None}]

    fleet = _fleet(session, model.id, items, {"covariates": {"tempK": 320}, "default_rate": 200}, model_kind="alt")
    assert fleet.model_kind == "alt"
    ours = fs.compute(session, fleet, A)
    live = alt_service.get_live_model(session, model.id, A)
    theirs = sp.forecast(live, age=[2000, 1000], Z=[[300.0], [320.0]], horizon=200.0 * np.arange(1, 7),
                         alpha_ci=0.2)
    _same(ours, theirs)
    assert ours["model_kind"] == "alt" and ours["model_url"] == f"/modelling/alt/{model.id}"
    # Hotter runs fail sooner.
    assert ours["per_item"][1]["prob_any"] > ours["per_item"][0]["prob_any"]


def test_alt_fleet_needs_an_alt_model(session):
    from backend.services import fleet as fs

    life = _life_model(session)
    with pytest.raises(fs.FleetValidationError):
        fs.create_fleet(session, "F", life.id, A, "alt")
    with pytest.raises(fs.FleetValidationError, match="Unknown model kind"):
        fs.create_fleet(session, "F", life.id, A, "nope")


def test_api_creates_and_forecasts_an_alt_fleet(client):
    from backend.services import alt as alt_service
    from backend.services import datasets as ds

    dataset = ds.create_dataset(client.db, "alt.csv", _alt_csv(), A)
    model = alt_service.save_model(client.db, "arrhenius", dataset, {
        "mapping": {"x": "hours"}, "stress_cols": ["tempK"], "distribution_id": "weibull",
        "life_model_id": "arrhenius", "unit": "hours"}, A)
    r = client.post("/api/fleet/fleets", json={"name": "Ovens", "model_id": model.id, "model_kind": "alt"})
    assert r.status_code == 200, r.text
    assert r.json()["model_kind"] == "alt" and r.json()["settings"]["method"] == "single"
    fid = r.json()["id"]
    r = client.put(f"/api/fleet/fleets/{fid}/items", json={
        "settings": {**r.json()["settings"], "covariates": {"tempK": 330}, "warranty_use": "5000"},
        "items": [{"name": "Oven 1", "current_use": 100, "covariates": {"tempK": "345"}},
                  {"name": "Oven 2", "current_use": 4000, "service_periods": 3}]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["settings"]["warranty_use"] == 5000.0 and body["settings"]["covariates"] == {"tempK": 330.0}
    assert body["items"][0]["covariates"] == {"tempK": "345"} and body["items"][1]["service_periods"] == 3.0
    f = body["forecast"]
    assert f["status"] == "ok", f
    assert f["per_item"][0]["covariates"] == {"tempK": 345.0}
    got = client.get(f"/api/fleet/fleets/{fid}").json()
    assert got["model_kind"] == "alt" and got["forecast"]["expected"] == f["expected"]
    bad = client.put(f"/api/fleet/fleets/{fid}/items", json={"settings": {"warranty_use": -1}, "items": []})
    assert bad.status_code == 422


def test_api_reads_the_pre_unification_model_source(client):
    """A client still sending #234's ``model_source: "alt"`` gets an ALT fleet."""
    from backend.services import alt as alt_service
    from backend.services import datasets as ds

    dataset = ds.create_dataset(client.db, "alt.csv", _alt_csv(), A)
    model = alt_service.save_model(client.db, "arrhenius", dataset, {
        "mapping": {"x": "hours"}, "stress_cols": ["tempK"], "distribution_id": "weibull",
        "life_model_id": "arrhenius", "unit": "hours"}, A)
    r = client.post("/api/fleet/fleets", json={"name": "Ovens", "model_id": model.id, "model_source": "alt"})
    assert r.status_code == 200, r.text
    assert r.json()["model_kind"] == "alt" and "model_source" not in r.json()
    bad = client.post("/api/fleet/fleets", json={"name": "Ovens", "model_id": model.id, "model_source": "x"})
    assert bad.status_code == 422


# ---- One model_kind field, read from either branch's saved fleets ----------------

def test_fleets_saved_with_either_old_field_still_forecast(session):
    """#234 saved ``model_source`` (None / "alt") and #235 ``model_kind``
    ("life" / "recurrent"). Both are read as the one ``model_kind``."""
    from datetime import datetime, timezone

    from backend.schema import fleet_model_kind
    from backend.services import access
    from backend.services import fleet as fs

    assert fleet_model_kind({}) == "life"
    assert fleet_model_kind({"model_source": None}) == "life"
    assert fleet_model_kind({"model_source": "alt"}) == "alt"
    assert fleet_model_kind({"model_kind": "life", "model_source": "alt"}) == "alt"
    assert fleet_model_kind({"model_kind": "recurrent"}) == "recurrent"
    assert fleet_model_kind({"model_kind": "regression"}) == "regression"
    assert fleet_model_kind({"model_kind": "bogus"}) == "life"

    alt = _alt_model(session)
    now = datetime.now(timezone.utc)
    settings = {"periods": 6, "period_label": "months", "default_rate": 200.0, "method": "single",
                "rate_source": "manual", "covariates": {"tempK": 320.0}}
    session.fleets.insert_one({  # as #234 saved an ALT fleet: no model_kind
        "_id": "legacy-alt", "id": "legacy-alt", "name": "Ovens", "owner_id": A, "created_at": now, "updated_at": now,
        "model_id": alt.id, "model_source": "alt", "settings": settings,
        "items": [{"id": "i1", "name": "Oven", "current_use": 1000.0, "rate": None}]})
    fleet = fs.get_fleet(session, "legacy-alt", A)
    assert fleet.model_kind == "alt"
    out = fs.compute(session, fleet, A)
    assert out["status"] == "ok" and out["model_kind"] == "alt"
    assert access.refs_of("fleets", session.fleets.find_one({"_id": "legacy-alt"})) == [("alt_models", alt.id)]
    # An edit keeps it an ALT fleet.
    fs.replace_items(session, "legacy-alt", settings, fleet.items, A)
    assert fs.get_fleet(session, "legacy-alt", A).model_kind == "alt"

    reg = _regression_model(session)
    session.fleets.insert_one({  # as #234 saved a regression fleet: model_source None
        "_id": "legacy-reg", "id": "legacy-reg", "name": "Pumps", "owner_id": A, "created_at": now, "updated_at": now,
        "model_id": reg.id, "model_source": None, "settings": {**settings, "covariates": {"site": "B"}},
        "items": [{"id": "i1", "name": "Pump", "current_use": 200.0, "rate": None}]})
    fleet = fs.get_fleet(session, "legacy-reg", A)
    assert fleet.model_kind == "life"  # what it was saved as; the model's own fit decides the forecast
    out = fs.compute(session, fleet, A)
    assert out["status"] == "ok" and out["model_kind"] == "regression"
    assert access.refs_of("fleets", {"model_id": reg.id, "model_source": None}) == [("models", reg.id)]
    assert access.refs_of("fleets", {"model_id": "r1", "model_kind": "recurrent"}) == [("recurrent_models", "r1")]


# ---- MCP -------------------------------------------------------------------------

def test_mcp_fleet_forecast_names_items_and_gives_curves_on_request(env):
    from backend.services import fleet as fs
    from backend.tests.test_fleet_alerts import _mcp_fleet
    from backend.tests.test_mcp import _call, _ok

    fid = _mcp_fleet(env)
    fs.replace_items(env.db, fid, {"periods": 6, "default_rate": 5, "method": "single"},
                     [{"name": "Truck 1", "current_use": 30}, {"name": "Truck 2", "current_use": 90}], A)
    out = _ok(_call(env.token[A], "fleet_forecast", {"fleet_id": fid}))
    rows = out["forecast"]["per_item"]
    assert sorted(r["name"] for r in rows) == ["Truck 1", "Truck 2"]
    assert out["forecast"]["interval_method"] == "exact" and len(out["forecast"]["per_period_interval"]) == 6
    assert "probability_by_period" not in rows[0]
    curves = _ok(_call(env.token[A], "fleet_forecast", {"fleet_id": fid, "item_probabilities": True}))
    for row in curves["forecast"]["per_item"]:
        assert len(row["probability_by_period"]) == 6
        assert row["probability_by_period"][-1] == pytest.approx(row["prob_any"])


def test_mcp_lists_and_guards_regression_and_alt_fleets(env):
    from backend.services import fleet as fs
    from backend.tests.test_mcp import _call, _ok

    alt = _alt_model(env.db)
    reg = _regression_model(env.db)
    fa = fs.create_fleet(env.db, "Ovens", alt.id, A, "alt")
    fr = fs.create_fleet(env.db, "Pumps", reg.id, A)
    kinds = {f["id"]: f["model_kind"] for f in _ok(_call(env.token[A], "list_fleets", {}))["fleets"]}
    assert kinds[fa.id] == "alt" and kinds[fr.id] == "regression"
    out = _ok(_call(env.token[A], "fleet_forecast", {"fleet_id": fa.id}))
    assert out["fleet"]["model_kind"] == "alt" and "model_source" not in out["fleet"]
    # A regression model a fleet runs on can't be deleted through MCP.
    refused = _call(env.token[A], "delete_model", {"model_id": reg.id})
    assert refused.is_error and "Pumps" in refused.content[0].text
