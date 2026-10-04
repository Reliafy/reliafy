"""Per-demand (Binomial) reliability models."""

import mongomock
import pytest
from scipy import stats

from backend import fitting
from backend.tests.test_mcp import env  # noqa: F401 - fixture

A = "user-a"
USERS = {A: {"uid": A, "email": "a@x.com", "name": "A"}}


def test_result_per_demand_math():
    r = fitting.result_per_demand(130, 3)
    assert r["kind"] == "per_demand"
    d = r["per_demand"]
    assert d["p"] == pytest.approx(3 / 130)
    assert d["reliability"] == pytest.approx(1 - 3 / 130)
    lo, hi = d["ci"]
    assert 0 < lo < d["p"] < hi < 0.1
    # Exact (Clopper-Pearson) since SurPyval 0.23 (#233): 3 in 130 was Wilson's
    # [0.00788, 0.06565]; it is [0.00478, 0.06596], as scipy's binomtest.
    exact = stats.binomtest(3, 130).proportion_ci(0.95, method="exact")
    assert (lo, hi) == pytest.approx((exact.low, exact.high), rel=1e-9)
    assert d["method"] == "exact" and d["confidence"] == 0.95
    assert d["reliability_ci"] == pytest.approx([1 - hi, 1 - lo])
    assert r["functions"] is None and r["gof"] == []


def test_per_demand_edge_cases():
    zero = fitting.result_per_demand(50, 0)
    assert zero["per_demand"]["p"] == 0.0 and zero["per_demand"]["ci"][0] == pytest.approx(0, abs=1e-9)
    allf = fitting.result_per_demand(50, 50)
    assert allf["per_demand"]["p"] == 1.0 and allf["per_demand"]["ci"][1] == pytest.approx(1, abs=1e-9)
    for bad in ((0, 0), (10, 11), (-1, 0)):
        with pytest.raises(fitting.FitError):
            fitting.result_per_demand(*bad)


def test_success_run_zero_failures():
    # Classic "59 for 95/95": 59 clean demands demonstrate ~95% reliability at 95%.
    r = fitting.result_per_demand(59, 0, confidence=0.95)
    sr = r["per_demand"]["success_run"]
    assert sr["confidence"] == 0.95
    assert sr["reliability_lower"] == pytest.approx(0.95, abs=5e-3)
    # Formula check: R = (1 - C)^(1/n).
    assert fitting.result_per_demand(22, 0, confidence=0.90)["per_demand"]["success_run"]["reliability_lower"] \
        == pytest.approx((1 - 0.90) ** (1 / 22))
    # The success run is the exact one-sided bound -- the same number from
    # one method.
    assert sr["reliability_lower"] == pytest.approx(r["per_demand"]["reliability_lower"], rel=1e-12)
    # Only applies with zero failures.
    assert "success_run" not in fitting.result_per_demand(100, 3)["per_demand"]
    # Confidence is validated.
    for bad in (0.0, 1.0, 1.5, -0.1):
        with pytest.raises(fitting.FitError):
            fitting.result_per_demand(59, 0, confidence=bad)


# ---------------------------------------------------------------------------
# Several batches, exact bounds (#233)
# ---------------------------------------------------------------------------
BATCHES = [{"label": "Site A", "demands": 20, "failures": 1},
           {"label": "Site B", "demands": 50, "failures": 0},
           {"label": "Site C", "demands": 80, "failures": 3}]


@pytest.mark.parametrize("confidence", [0.8, 0.9, 0.95, 0.99])
def test_batches_pool_with_exact_bounds(confidence):
    r = fitting.result_per_demand(confidence=confidence, batches=BATCHES)
    d = r["per_demand"]
    assert d["demands"] == 150 and d["failures"] == 4
    assert d["p"] == pytest.approx(4 / 150)
    # Exact for unequal batches: the failures in all the demands are binomial
    # in their total (SurPyval #608), so the bound is Clopper-Pearson on 4/150.
    exact = stats.binomtest(4, 150).proportion_ci(confidence, method="exact")
    assert d["ci"] == pytest.approx([exact.low, exact.high], rel=1e-9)
    # One-sided: the upper bound on p at the same confidence.
    upper = stats.binomtest(4, 150).proportion_ci(2 * confidence - 1, method="exact").high
    assert d["p_upper"] == pytest.approx(upper, rel=1e-9)
    assert d["reliability_lower"] == pytest.approx(1 - upper, rel=1e-9)
    assert [b["label"] for b in d["batches"]] == ["Site A", "Site B", "Site C"]
    assert d["batches"][2]["p"] == pytest.approx(3 / 80)


def test_one_batch_is_the_single_count():
    one = fitting.result_per_demand(confidence=0.9, batches=[{"demands": 130, "failures": 3}])
    two = fitting.result_per_demand(130, 3, confidence=0.9)
    assert one == two and "batches" not in one["per_demand"]


def test_zero_failures_in_every_batch_is_a_success_run():
    r = fitting.result_per_demand(batches=[{"demands": 30, "failures": 0}, {"demands": 29, "failures": 0}])
    d = r["per_demand"]
    assert d["success_run"]["reliability_lower"] == pytest.approx(0.05 ** (1 / 59))
    assert d["reliability_lower"] == pytest.approx(0.05 ** (1 / 59), rel=1e-12)


@pytest.mark.parametrize("bad, match", [
    ([], "at least one batch"),
    ([{"demands": 0, "failures": 0}], "positive"),
    ([{"demands": 10, "failures": 1}, {"demands": 5, "failures": 6}], "Batch 2: failures"),
    ([{"demands": 2.5, "failures": 1}], "whole number"),
    (["x"], "must be an object"),
])
def test_bad_batches_are_refused(bad, match):
    with pytest.raises(fitting.FitError, match=match):
        fitting.result_per_demand(batches=bad)


def test_batches_from_a_dataset():
    import pandas as pd

    df = pd.DataFrame({"site": ["A", "B", None], "n": [20, 50, 80], "f": [1, 0, 3]})
    rows = fitting.per_demand_batches_from_df(df, "n", "f", "site")
    assert rows == [{"label": "A", "demands": 20, "failures": 1}, {"label": "B", "demands": 50, "failures": 0},
                    {"label": "Row 3", "demands": 80, "failures": 3}]
    with pytest.raises(fitting.FitError, match="no column named 'nope'"):
        fitting.per_demand_batches_from_df(df, "nope", "f")


@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient
    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    test_db = mongomock.MongoClient()["reliafy_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    app.dependency_overrides[get_current_user] = lambda: USERS[A]
    tc = TestClient(app)
    tc.db = test_db
    try:
        yield tc
    finally:
        app.dependency_overrides.clear()


def test_per_demand_endpoint(client):
    r = client.post("/api/models/per-demand", json={"name": "Relief valve", "demands": 130, "failures": 3})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "per_demand"
    assert body["results"]["per_demand"]["p"] == pytest.approx(3 / 130)
    assert body["dataset_id"] == ""

    # Reads back like any model.
    got = client.get(f"/api/models/{body['id']}").json()
    assert got["results"]["distribution"] == "Per-demand (Binomial)"

    # Validation.
    assert client.post("/api/models/per-demand", json={"name": "x", "demands": 10, "failures": 20}).status_code == 422
    assert client.post("/api/models/per-demand", json={"name": "", "demands": 10, "failures": 1}).status_code == 422

    # Success run: zero failures + confidence -> demonstrated reliability bound.
    sr = client.post("/api/models/per-demand",
                     json={"name": "Igniter demo", "demands": 59, "failures": 0, "confidence": 0.95})
    assert sr.status_code == 200, sr.text
    block = sr.json()["results"]["per_demand"]["success_run"]
    assert block["confidence"] == 0.95 and block["reliability_lower"] == pytest.approx(0.95, abs=5e-3)


def test_per_demand_endpoint_takes_batches_and_a_dataset(client):
    r = client.post("/api/models/per-demand", json={"name": "Deluge valves", "batches": BATCHES,
                                                     "confidence": 0.9})
    assert r.status_code == 200, r.text
    body = r.json()
    d = body["results"]["per_demand"]
    assert d["demands"] == 150 and d["confidence"] == 0.9 and len(d["batches"]) == 3
    assert body["spec"]["per_demand"]["batches"][0] == {"label": "Site A", "demands": 20, "failures": 1}

    from backend.services import datasets as datasets_service

    ds = datasets_service.create_dataset(client.db, "lots", b"lot,n,f\nL1,20,1\nL2,50,0\nL3,80,3\n", A)
    r = client.post("/api/models/per-demand", json={
        "name": "From lots", "dataset_id": ds.id, "demands_column": "n", "failures_column": "f",
        "batch_column": "lot"})
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["results"]["per_demand"]["p"] == pytest.approx(4 / 150)
    assert [b["label"] for b in got["results"]["per_demand"]["batches"]] == ["L1", "L2", "L3"]
    assert got["spec"]["source_dataset_id"] == ds.id

    bad = client.post("/api/models/per-demand", json={"name": "x", "dataset_id": ds.id, "demands_column": "n"})
    assert bad.status_code == 422 and "columns" in bad.json()["detail"]
    assert client.post("/api/models/per-demand", json={"name": "x"}).status_code == 422
    assert client.post("/api/models/per-demand", json={"name": "x", "dataset_id": "nope", "demands_column": "n",
                                                        "failures_column": "f"}).status_code == 404


def test_mcp_fit_per_demand_and_save(env):
    from backend.services import datasets as datasets_service
    from backend.tests.test_mcp import A as MA, _call, _err, _ok

    token = env.token[MA]
    out = _ok(_call(token, "fit_per_demand", {"batches": BATCHES, "confidence": 0.9}))
    assert out["saved"] is False and out["p"] == pytest.approx(4 / 150)
    exact = stats.binomtest(4, 150).proportion_ci(0.9, method="exact")
    assert out["p_interval"] == pytest.approx([exact.low, exact.high], rel=1e-9)
    assert out["bounds_method"].startswith("exact") and len(out["batches"]) == 3

    ds = datasets_service.create_dataset(env.db, "lots", b"lot,n,f\nL1,20,1\nL2,50,0\nL3,80,3\n", MA)
    by_data = _ok(_call(token, "fit_per_demand", {"dataset_id": ds.id, "demands_column": "n",
                                                  "failures_column": "f", "confidence": 0.9}))
    assert by_data["p_interval"] == out["p_interval"]
    assert "exactly one" in _err(_call(token, "fit_per_demand", {}))

    saved = _ok(_call(token, "fit_and_save_model", {"name": "Deluge valves", "demand_batches": BATCHES}))
    assert saved["saved"] is True and saved["kind"] == "per_demand" and saved["confidence"] == 0.95
    got = _ok(_call(token, "get_model", {"model_id": saved["model_id"]}))
    assert got["kind"] == "per_demand"
    assert "don't apply" in _err(_call(token, "fit_and_save_model", {
        "name": "x", "demand_batches": BATCHES, "data": [1, 2, 3]}))
