"""Demonstration test planning (#158): the strategy calculator, its REST
endpoints, the saved analysis and the public link. The MCP tool is covered in
test_mcp.py."""

import math

import mongomock
import pytest
from scipy import stats

from backend.services import strategy as st
from backend.services import strategy_store
from backend.services.strategy import StrategyError, demonstration_test

A = "user-a"
USERS = {A: {"uid": A, "email": "a@x.com", "name": "Alice"}}


# ---- service: known values -----------------------------------------------------------


@pytest.mark.parametrize("R, C", [(0.95, 0.95), (0.9, 0.9), (0.99, 0.95), (0.999, 0.9), (0.8, 0.5)])
def test_success_run_matches_the_closed_form(R, C):
    # Zero failures: n = ln(1 - C) / ln(R), rounded up.
    out = demonstration_test(R, C)
    assert out["units"] == math.ceil(math.log(1 - C) / math.log(R) - 1e-12)
    assert out["failures"] == 0 and out["solve_for"] == "units" and out["method"] == "attribute"


def test_the_textbook_59_units():
    out = demonstration_test(0.95, 0.95, mission_time=1000, unit="hours")
    assert out["units"] == 59
    assert out["test_time_per_unit"] == 1000 and out["total_test_time"] == 59_000
    assert out["summary"] == (
        "Test 59 units for 1,000 hours each with no failures to show R(1,000 hours) ≥ 95% at 95% confidence."
    )
    # 59 units demonstrate a little more than the target; a design at the target passes < 5% of the time.
    assert out["demonstrated_reliability"] == pytest.approx(0.9505, abs=1e-4)
    assert out["consumer_risk"] <= 0.05


@pytest.mark.parametrize("r", [1, 2, 3, 5])
def test_allowed_failures_against_a_direct_binomial_computation(r):
    R, C = 0.95, 0.9
    n = demonstration_test(R, C, failures=r)["units"]
    # The smallest n whose chance of <= r failures, at the target, is at most 1 - C.
    assert stats.binom.cdf(r, n, 1 - R) <= 1 - C
    assert stats.binom.cdf(r, n - 1, 1 - R) > 1 - C


def test_tradeoff_units_against_allowed_failures():
    out = demonstration_test(0.95, 0.95, mission_time=1000, unit="hours")
    t = out["tradeoff"]
    assert t["failures"] == [0, 1, 2, 3] and t["solve_for"] == "units"
    assert len(t["rows"]) == 1  # no shape: no test-length trade-off
    assert t["rows"][0]["values"] == [59, 93, 124, 153] and t["rows"][0]["selected"]


def test_failures_beyond_three_get_their_own_column():
    out = demonstration_test(0.95, 0.95, failures=5)
    assert out["tradeoff"]["failures"] == [0, 1, 2, 3, 5]
    assert out["tradeoff"]["rows"][0]["values"][-1] == out["units"]


def test_extended_test_with_a_weibull_shape_matches_the_library():
    from repyability import demonstrated_reliability, demonstration_sample_size

    out = demonstration_test(0.95, 0.95, mission_time=1000, test_multiple=2, shape=2, unit="hours")
    assert out["units"] == demonstration_sample_size(0.95, 0.95, test_multiple=2.0, shape=2.0) == 15
    assert out["test_time_per_unit"] == 2000
    assert out["demonstrated_reliability"] == pytest.approx(
        demonstrated_reliability(15, 0.95, test_multiple=2.0, shape=2.0))
    assert "2,000 hours each (2× the mission)" in out["summary"]
    assert "Weibull shape of 2" in out["summary"]
    assert any("β = 2" in a for a in out["assumptions"])
    # Units against test length x allowed failures; the plan's own row is marked.
    rows = {row["key"]: row for row in out["tradeoff"]["rows"]}
    assert set(rows) == {1.0, 1.5, 2.0, 2.5, 3.0}
    assert rows[1.0]["values"] == [59, 93, 124, 153]
    assert rows[2.0]["values"][0] == 15 and rows[2.0]["selected"]
    for f in range(4):  # longer tests need fewer units
        col = [rows[k]["values"][f] for k in sorted(rows)]
        assert col == sorted(col, reverse=True)
    assert rows[3.0]["x"] == 3000 and rows[3.0]["label"] == "3,000 hours (3×)"


def test_solving_for_test_time_per_unit_matches_the_library():
    from repyability import demonstration_test_multiple

    out = demonstration_test(0.95, 0.95, mission_time=1000, shape=2, units=20, unit="hours")
    k = demonstration_test_multiple(0.95, 20, 0.95, shape=2.0)
    assert out["solve_for"] == "test_time" and out["units"] == 20
    assert out["test_multiple"] == pytest.approx(k)
    assert out["test_time_per_unit"] == pytest.approx(1000 * k)
    assert out["summary"].startswith("Test 20 units for 1,709 hours each (1.71× the mission)")
    # The plan demonstrates the target exactly.
    assert out["demonstrated_reliability"] == pytest.approx(0.95)
    rows = {row["key"]: row for row in out["tradeoff"]["rows"]}
    assert rows[20]["selected"] and rows[20]["values"][0] == pytest.approx(1000 * k)
    assert set(rows) == {10, 15, 20, 30, 40}


def test_too_few_units_for_more_failures_are_blank_in_the_tradeoff():
    out = demonstration_test(0.9, 0.9, shape=1.5, units=2)
    rows = {row["key"]: row for row in out["tradeoff"]["rows"]}
    assert rows[1]["values"][1:] == [None, None, None]
    assert rows[2]["values"][0] is not None and rows[2]["values"][2] is None


def test_without_a_mission_time_the_plan_is_in_missions():
    out = demonstration_test(0.95, 0.95, failures=1)
    assert out["units"] == 93 and out["test_time_per_unit"] is None
    assert out["summary"] == (
        "Test 93 units for one mission each with at most 1 failure to show a mission reliability ≥ 95% "
        "at 95% confidence."
    )


def test_design_reliability_reports_the_chance_of_passing():
    from repyability import demonstration_pass_probability

    out = demonstration_test(0.95, 0.95, design_reliability=0.99)
    assert out["pass_probability"] == pytest.approx(demonstration_pass_probability(0.99, 59))
    assert "true reliability is 99% passes this test 55% of the time" in out["summary"]


def test_mtbf_test_matches_the_chi_squared_bound():
    from repyability import mtbf_test_time

    out = demonstration_test(method="mtbf", mtbf=1000, units=4, unit="hours")
    assert out["total_test_time"] == pytest.approx(mtbf_test_time(1000.0))
    assert out["total_test_time"] == pytest.approx(1000 * stats.chi2.ppf(0.95, 2) / 2)
    assert out["test_time_per_unit"] == pytest.approx(out["total_test_time"] / 4)
    assert out["summary"] == (
        "Run 2,996 hours of total test time with no failures to show MTBF ≥ 1,000 hours at 95% confidence "
        "— about 749 hours on each of 4 units."
    )
    totals = out["tradeoff"]["rows"][0]["values"]
    assert totals[2] == pytest.approx(mtbf_test_time(1000.0, failures=2))


# ---- service: validation --------------------------------------------------------------


@pytest.mark.parametrize("kwargs, message", [
    ({"reliability": 1.0}, "Target reliability must be strictly between 0 and 1"),
    ({"reliability": 0}, "Target reliability must be strictly between 0 and 1"),
    ({"reliability": None}, "Target reliability must be a number"),
    ({"reliability": 0.9, "confidence": 1.2}, "Confidence must be strictly between 0 and 1"),
    ({"reliability": 0.9, "confidence": 0}, "Confidence must be strictly between 0 and 1"),
    ({"reliability": 0.9, "failures": -1}, "Allowed failures must be between 0 and 100"),
    ({"reliability": 0.9, "failures": 1.5}, "Allowed failures must be a whole number"),
    ({"reliability": 0.9, "mission_time": -5}, "Mission time must be a positive number"),
    ({"reliability": 0.9, "test_multiple": 2}, "needs the Weibull shape"),
    ({"reliability": 0.9, "test_multiple": 0}, "Test length (multiple of the mission) must be a positive"),
    ({"reliability": 0.9, "test_multiple": 2, "shape": -1}, "Weibull shape (beta) must be a positive"),
    ({"reliability": 0.9, "units": 10}, "give the Weibull shape"),
    ({"reliability": 0.9, "units": 2, "failures": 2, "shape": 2}, "must be more than the failures allowed"),
    ({"reliability": 0.9, "units": 0, "shape": 2}, "Units on test must be between 1"),
    ({"reliability": 0.9, "design_reliability": 1.5}, "Design reliability must be strictly between"),
    ({"reliability": 0.9, "method": "bayes"}, "method must be one of"),
    ({"method": "mtbf"}, "Enter the MTBF"),
    ({"method": "mtbf", "mtbf": -10}, "Target MTBF must be a positive number"),
])
def test_validation(kwargs, message):
    with pytest.raises(StrategyError, match=message.replace("(", r"\(").replace(")", r"\)")):
        demonstration_test(**kwargs)


def test_blank_optional_fields_are_ignored():
    out = demonstration_test("0.95", "0.95", mission_time="", failures="", test_multiple="", shape="", units="")
    assert out["units"] == 59


# ---- saved analysis -----------------------------------------------------------------


def test_saved_analysis_round_trip(monkeypatch):
    from backend import db as db_module

    session = mongomock.MongoClient()["reliafy_test"]
    monkeypatch.setattr(db_module, "_db", session)
    monkeypatch.setattr(db_module, "_simulated", True)

    inputs = {"method": "attribute", "reliability": 0.95, "confidence": 0.95, "mission_time": 1000,
              "failures": 0, "test_multiple": 2, "shape": 2, "unit": "hours",
              "results": {"units": 1}}  # a client can't smuggle results in
    doc = strategy_store.save_analysis(session, "Pump qualification", "demonstration_test", inputs, A)
    assert doc.kind == "demonstration_test"
    assert doc.results["units"] == 15  # recomputed server-side
    assert strategy_store.headline(doc) == "15 units × 2,000 hours, 0 failures"

    again = strategy_store.get_analysis(session, doc.id, A)
    assert again.results == doc.results and again.inputs["shape"] == 2

    mtbf = strategy_store.save_analysis(
        session, "Controller MTBF", "demonstration_test",
        {"method": "mtbf", "mtbf": 5000, "confidence": 0.9, "failures": 1, "unit": "hours"}, A)
    assert strategy_store.headline(mtbf) == "19,449 hours total test time, ≤1 failure"

    with pytest.raises(StrategyError):
        strategy_store.save_analysis(session, "Bad", "demonstration_test", {"reliability": 2}, A)


# ---- REST ---------------------------------------------------------------------------


@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app
    from backend.routers import ingest as ingest_router

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    test_db = mongomock.MongoClient()["reliafy_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    ingest_router._hits.clear()
    app.dependency_overrides[get_current_user] = lambda: USERS[A]
    test_db.users.update_one({"_id": A}, {"$set": {"email": "a@x.com", "email_lc": "a@x.com", "name": "Alice"}},
                             upsert=True)
    tc = TestClient(app)
    tc.db = test_db
    try:
        yield tc
    finally:
        app.dependency_overrides.clear()


def test_app_endpoint(client):
    r = client.post("/api/strategy/demonstration-test", json={
        "reliability": 0.9, "confidence": 0.9, "mission_time": 500, "failures": 1, "unit": "cycles"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["units"] == 38 and body["tradeoff"]["rows"][0]["values"][1] == 38
    assert body["summary"].startswith("Test 38 units for 500 cycles each with at most 1 failure")

    r = client.post("/api/strategy/demonstration-test", json={"reliability": 1.5})
    assert r.status_code == 422 and "between 0 and 1" in r.json()["detail"]
    r = client.post("/api/strategy/demonstration-test", json={"reliability": 0.9, "failures": 0.5})
    assert r.status_code == 422 and "whole number" in r.json()["detail"]


def test_saved_analysis_endpoint_and_public_link(client):
    r = client.post("/api/strategy/analyses", json={
        "name": "Seal qualification", "kind": "demonstration_test",
        "inputs": {"reliability": 0.95, "confidence": 0.95, "mission_time": 1000, "unit": "hours"}})
    assert r.status_code == 200, r.text
    saved = r.json()
    assert saved["results"]["units"] == 59 and saved["headline"] == "59 units × 1,000 hours, 0 failures"

    listed = client.get("/api/strategy/analyses").json()["analyses"]
    assert [a["kind"] for a in listed] == ["demonstration_test"]

    link = client.post("/api/public-links", json={"collection": "strategy_analyses", "artifact_id": saved["id"]})
    assert link.status_code == 200
    pub = client.get(f"/api/public/{link.json()['token']}")
    assert pub.status_code == 200
    art = pub.json()["artifact"]
    assert art["kind"] == "demonstration_test" and art["results"]["summary"].startswith("Test 59 units")


def test_v1_endpoint(client):
    raw = client.post("/api/tokens", json={"name": "test"}).json()["token"]
    auth = {"Authorization": f"Bearer {raw}"}
    r = client.post("/api/v1/strategy/demonstration-test", headers=auth, json={
        "reliability": 0.95, "confidence": 0.95, "mission_time": 1000, "test_multiple": 2, "shape": 2,
        "unit": "hours"})
    assert r.status_code == 200, r.text
    assert r.json()["units"] == 15
    r = client.post("/api/v1/strategy/demonstration-test", headers=auth, json={"reliability": 0.95, "units": 10})
    assert r.status_code == 422 and "Weibull shape" in r.json()["detail"]
    assert client.post("/api/v1/strategy/demonstration-test", json={"reliability": 0.95}).status_code == 401


def test_fmt_num_used_for_large_plans():
    out = st.demonstration_test(0.9999, 0.9)
    assert out["units"] == 23_025 and "Test 23,025 units" in out["summary"]
