"""Lives on two clocks (hours and starts, flight hours and landings...): the fit
recovers a simulated fleet's parameters, the life at a rate matches SurPyval called
directly, a saved model round-trips (its second clock's unit too), every word uses
the user's units, and the REST routes serve it (free)."""

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
    with pytest.raises(FitError, match="model on two clocks"):
        fitting.fit("weibull", df, MAPPING)
    with pytest.raises(FitError, match="second clock's column"):
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
    assert bad.status_code == 422 and "starts per hour" in bad.json()["detail"]  # its column is "starts"
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


def test_rbd_block_at_a_rate_matches_a_hand_calculation(rbd_db):
    from backend.services import rbd_analysis as ra
    from backend.services import rbd_two_clocks, rbds, repy_compat

    # RePyability 0.19.1, the pin, takes the life at a rate as a block itself (no stand-in).
    assert repy_compat.native_usage_blocks()
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
    assert isinstance(life, sp.LifeAtUsage) and life.rate == 0.125


def test_rbd_block_goes_to_repyability_as_the_life_at_a_rate(rbd_db, monkeypatch):
    """The diagram RePyability is given holds the LifeAtUsage itself (its native block), and an
    older RePyability without it is refused in words rather than given a stand-in."""
    import repyability
    from repyability.rbd import _usage

    from backend.services import rbd_analysis as ra
    from backend.services import rbds, repy_compat

    doc = _save_two_clock(rbd_db)
    block = {"source": "saved", "kind": "two_clock", "modelId": doc.id, "usage_rate": 0.125}
    _, resolve_model = rbds.resolvers(rbd_db, OWNER)
    given = []
    real = repyability.NonRepairableRBD.__init__

    def spy(self, edges, reliabilities, *args, **kwargs):
        given.extend(v for v in dict(reliabilities).values() if _usage.is_life_at_usage(v))
        real(self, edges, reliabilities, *args, **kwargs)

    monkeypatch.setattr(repyability.NonRepairableRBD, "__init__", spy)
    ra.analyze(_diagram(block), resolve_model=resolve_model, at_times=[1000.0])
    assert given and all(life.rate == 0.125 for life in given)

    monkeypatch.setattr(repy_compat, "native_usage_blocks", lambda: False)
    with pytest.raises(ra.AnalysisError, match="RePyability 0.19.1"):
        ra.analyze(_diagram(block), resolve_model=resolve_model, at_times=[1000.0])


def test_rbd_band_carries_the_two_clock_fits_uncertainty(rbd_db):
    """The confidence band draws the two-clock fit's parameters, k included: the block is
    uncertain (not fixed), the band holds the point curve, and a faster rate (where k
    matters more) widens it."""
    from backend.services import rbd_analysis as ra
    from backend.services import rbds

    doc = _save_two_clock(rbd_db)
    _, resolve_model = rbds.resolvers(rbd_db, OWNER)

    def run(rate):
        block = {"source": "saved", "kind": "two_clock", "modelId": doc.id, "usage_rate": rate}
        return ra.analyze(_diagram(block), resolve_model=resolve_model, at_times=[5000.0],
                          band={"level": 0.9, "times": [5000.0]})

    out = run(0.125)
    band = out["band"]
    assert [u["id"] for u in band["uncertain"]] == ["a"] and not band["fixed"]
    (row,) = band["targets"]["reliability"]
    assert row["lower"] < out["at"]["sf"][0] < row["upper"]
    # The draws agree with SurPyval's own 90% bounds on the life at the rate (delta method).
    live = resolve_model(doc.id)["model"]
    (lo, hi), = live.at_usage(0.125).cb(np.array([5000.0]), on="sf", alpha_ci=0.1)
    assert row["lower"] == pytest.approx(lo, abs=0.01) and row["upper"] == pytest.approx(hi, abs=0.01)
    fast = run(0.3)["band"]["targets"]["reliability"][0]
    slow = run(0.0)["band"]["targets"]["reliability"][0]
    assert slow["upper"] - slow["lower"] > 0.0 and fast["upper"] - fast["lower"] > 0.0
    assert fast["value"] < slow["value"]


def test_rbd_block_without_a_rate_says_to_set_one(rbd_db):
    from backend.services import rbd_analysis as ra
    from backend.services import rbds

    doc = _save_two_clock(rbd_db)
    _, resolve_model = rbds.resolvers(rbd_db, OWNER)
    with pytest.raises(ra.AnalysisError, match="set its usage rate, starts per hour"):
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
    with pytest.raises(Invalid, match="0 or more"):
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
    # A second clock with a one-clock model is refused in words.
    bad = client.post("/api/v1/analyse/fit", json={**body, "distribution": "weibull"}, headers=head)
    assert "model on two clocks" in bad.text
    # The second clock's own unit: every answer says landings, never starts.
    r = client.post("/api/v1/analyse/fit", json={**body, "second_clock_unit": "landing"}, headers=head)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["second_clock_unit"] == "landings"
    assert out["answer"].startswith("Wears by landings and by hours: one landing wears it as much as 18.4 hours")
    assert "start" not in out["answer"] and "landings per hour" in out["use"]
    r = client.post("/api/v1/change/model_fit", json={**body, "name": "Struts", "second_clock_unit": "landings"},
                    headers=head)
    assert r.status_code == 200, r.text
    at = client.post("/api/v1/analyse/reliability_at", json={"model_id": r.json()["model_id"], "times": [4000],
                                                              "usage_rate": 0.125}, headers=head).json()
    assert at["rate_words"] == "1 landing every 8 hours" and at["usage_rate_unit"] == "landings per hour"
    assert "start" not in at["answer"]
    # A unit with no second clock is refused, not ignored.
    lone = client.post("/api/v1/analyse/fit", json={"distribution": "weibull", "data": [1.0, 2.0, 3.0],
                                                    "second_clock_unit": "cycles"}, headers=head)
    assert lone.status_code >= 400 and "second_clock_unit" in lone.text


# ---- the second clock's own unit (Derryn, 16 Nov 2026: "more general" than starts) -----------

LANDINGS = {"x": "hours", "x2": "landings", "c": "c"}


def flights() -> pd.DataFrame:
    return fleet().rename(columns={"starts": "landings"})


def _all_words(result: dict) -> str:
    """Every sentence a fit shows."""
    at = result.get("at_rate") or {}
    return " ".join([result["headline"], *result["warnings"], at.get("sentence", ""), at.get("rate_words", ""),
                     *(r["rate_words"] for r in result["rate_table"]), *(p["words"] for p in result["params"])])


def test_the_unit_defaults_from_the_column_and_can_be_typed():
    assert two_clocks.default_unit("starts") == "starts"
    assert two_clocks.default_unit("Landings") == "landings"
    assert two_clocks.default_unit("num_cycles") == "cycles"
    assert two_clocks.default_unit("StartCount") == "starts"
    assert two_clocks.default_unit("Distance (km)") == "km"
    assert two_clocks.default_unit("x2") == "uses"
    assert two_clocks.clean_unit(" cycle ") == "cycles"
    assert two_clocks.clean_unit("kWh") == "kWh"
    _, result = two_clocks.fit("weibull_two_clock", flights(), LANDINGS, "Hours")
    assert result["second_unit"] == "landings"
    _, typed = two_clocks.fit("weibull_two_clock", flights(), LANDINGS, "Hours", "deck landing")
    assert typed["second_unit"] == "deck landings"


def test_every_word_uses_the_users_units():
    model, result = two_clocks.fit("weibull_two_clock", flights(), LANDINGS, "flight hours", "cycle")
    words = _all_words(result)
    assert "start" not in words.lower()
    assert result["headline"].startswith(
        "Wears by cycles and by flight hours: one cycle wears it as much as 18.4 flight hours.")
    assert "1 cycle every 20 flight hours" in result["headline"]
    assert result["clocks"]["rate_unit"] == "cycles per flight hour"
    assert next(p for p in result["params"] if p["name"] == "k")["words"] == "flight hours one cycle is worth"
    at = two_clocks.answer(model, {"rate": 2.5}, "flight hours")
    assert at["rate_words"] == "2.5 cycles per flight hour"
    assert at["sentence"].startswith("At 2.5 cycles per flight hour, its B10 life is ")
    one = two_clocks.answer(model, {"rate": 1}, "flight hours")
    assert one["rate_words"] == "1 cycle every 1 flight hour"
    with pytest.raises(two_clocks.TwoClockError, match="cycles per flight hour"):
        two_clocks.answer(model, {"rate": "fast"}, "flight hours")
    script = "\n".join(two_clocks.python_script("Struts", flights(), LANDINGS, "weibull_two_clock", "flight hours",
                                                0.05, "cycles"))
    assert "# cycles per flight hour" in script and "start" not in script.lower()


def test_the_unit_round_trips_through_to_dict_and_the_saved_live_model():
    model, _ = two_clocks.fit("weibull_two_clock", flights(), LANDINGS, "Hours", "landings")
    d = two_clocks.to_dict(model)
    assert d["second_unit"] == "landings"
    back = two_clocks.from_dict(d)
    assert back.second_unit == "landings"
    assert two_clocks.answer(back, {"rate": 0.125}, "Hours")["rate_words"] == "1 landing every 8 hours"
    # The app's own serialisation (a saved model's ``serialized``) carries it too.
    cache = fitting._store_model(model, np.array([0.0, 1.0]), [])
    restored = fitting._MODEL_STORE[fitting.restore_live(fitting.serialize_live(cache))]["model"]
    assert restored.second_unit == "landings"


def test_a_model_saved_before_units_reads_starts_and_is_not_rewritten(rbd_db):
    from backend.services import models as models_service

    doc = _save_two_clock(rbd_db)
    doc.serialized["model"].pop("second_unit", None)
    results = {k: v for k, v in doc.results.items() if k != "second_unit"}
    results["clocks"] = {**results["clocks"], "second": "Start count", "second_word": "start count"}
    rbd_db.models.update_one({"_id": doc.id}, {"$set": {"results": results, "serialized": doc.serialized},
                                               "$unset": {"spec.options.x2_unit": ""}})
    stored = rbd_db.models.find_one({"_id": doc.id})
    models_service._LIVE.clear()
    old = models_service.get_model(rbd_db, doc.id, OWNER)
    live = models_service.two_clock_live(rbd_db, old, [OWNER])
    at = two_clocks.answer(live, {"rate": 0.125}, "Hours")
    assert at["rate_words"] == "1 start every 8 hours" and at["clocks"]["rate_unit"] == "starts per hour"
    assert two_clocks.results_words(old.results)["second_word"] == "starts"
    assert rbd_db.models.find_one({"_id": doc.id}) == stored  # read only: nothing rewritten


def test_a_saved_model_keeps_the_unit_from_the_form(client):
    r = client.post("/api/models", data={"name": "Struts", "distribution": "weibull_two_clock", "x": "hours",
                                         "x2": "landings", "x2_unit": "landing", "c": "c", "unit": "hours"},
                    files={"file": ("f.csv", io.BytesIO(flights().to_csv(index=False).encode()), "text/csv")})
    assert r.status_code == 200, r.text
    saved = r.json()
    doc = client.db.models.find_one({"_id": saved["id"]})
    assert doc["results"]["second_unit"] == "landings"
    assert doc["spec"]["options"]["x2_unit"] == "landings"  # a refit keeps it
    assert doc["serialized"]["model"]["second_unit"] == "landings"
    from backend.services import models as models_service

    models_service._LIVE.clear()
    out = client.post(f"/api/models/{saved['id']}/at-rate", json={"rate": 0.125}).json()
    assert out["rate_words"] == "1 landing every 8 hours" and "start" not in out["sentence"]
    bad = client.post(f"/api/models/{saved['id']}/at-rate", json={"rate": "fast"})
    assert bad.status_code == 422 and "landings per hour" in bad.json()["detail"]
    script = client.get(f"/api/models/{saved['id']}/export.py").text
    assert "landings per hour" in script and "starts" not in script


def test_the_reading_keeps_the_second_clocks_unit():
    from backend.services import dataset_reading as dr

    cols = [{"name": n} for n in ("hours", "num_landings", "status")]
    r = dr.normalize({"x": "hours", "c": "status", "x2": "num_landings"}, cols)
    assert r["x2_unit"] == "landings"
    r = dr.normalize({"x": "hours", "c": "status", "x2": "num_landings", "x2_unit": "cycle"}, cols)
    assert r["x2_unit"] == "cycles"
    assert "second clock = num_landings (cycles)" in dr.summary(r)
    mapping, options = dr.life_mapping(r)
    assert options["x2_unit"] == "cycles"
    assert dr.normalize({"x": "hours", "x2_unit": "cycles"}, cols)["x2_unit"] == ""


def test_the_operating_plan_gives_starts_but_not_landings(rbd_db):
    """A plan counts runs: it can say how often a unit starts, never how often it lands."""
    from backend.maintenance import position_models as pm
    from backend.maintenance.service import PROJECTORS, Maintenance
    from backend.maintenance.store import GraphStore
    from backend.services import datasets as datasets_service
    from backend.services import models as models_service

    m = Maintenance(GraphStore(":memory:", PROJECTORS), OWNER, "tester")
    ds = datasets_service.create_dataset(rbd_db, "flights", flights().to_csv(index=False).encode(), OWNER)
    doc = models_service.save_model(rbd_db, "Struts", ds, "weibull_two_clock", LANDINGS, None, None, "hours",
                                    owner_id=OWNER)
    owners = [OWNER]
    strut = m.create_position("Main gear strut")["id"]
    m.set_operating_plan(strut, WEEKDAYS_6_TO_22, name="Day shifts")
    link = pm.link_saved(m, rbd_db, owners, set(), strut, "model", doc.id)
    rate = pm.detail(m, rbd_db, owners, set(), link["id"])["two_clock"]["usage_rate"]
    assert rate["source"] == "fleet" and rate["rate"] == 0.05 and rate["plan"] is None
    assert rate["text"].startswith("The operating plan counts runs, not landings: set the landings per hour here.")
    assert "typical rate in the data" in rate["text"]
    # Typed by hand, it wins; cleared, it goes back to the fleet's rate, never the plan's runs.
    m.set_link_usage_rate(link["id"], 0.4)
    d = pm.detail(m, rbd_db, owners, set(), link["id"])
    assert d["two_clock"]["usage_rate"]["source"] == "set" and "operating plan gives" not in d["two_clock"]["usage_rate"]["text"]
    assert d["two_clock"]["at_rate"]["rate_words"] == "1 landing every 2.5 hours"
    m.set_link_usage_rate(link["id"], None)
    assert pm.detail(m, rbd_db, owners, set(), link["id"])["two_clock"]["usage_rate"]["source"] == "fleet"
    # A diagram built from the position runs the block at the same rate, said in landings.
    row = pm.summary("model", doc)
    assert any(n["label"] == "Hours per landing" for n in row["numbers"])
