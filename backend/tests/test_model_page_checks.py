"""What the model page's Diagnostics and Data tabs read from a fit: the
failures on the time scale beside the probability plot (the fitted curve over
the data, and the P-P plot), a discrete fit's observed against expected
counts, a non-parametric estimate's life table, and a Royston-Parmar spline
compared with the plain distributions."""

import io

import matplotlib

matplotlib.use("Agg")

import mongomock
import numpy as np
import pandas as pd
import pytest

from backend.fitting import fit

A = "user-a"
USERS = {A: {"uid": A, "email": "a@x.com", "name": "A"}}


def _df(text: str) -> pd.DataFrame:
    return pd.read_csv(io.StringIO(text))


PUMPS = "months,censored\n" + "".join(f"{v},0\n" for v in (4, 7, 9, 11, 13, 15, 16, 18, 19, 21, 23, 24, 26)) \
    + "36,1\n36,1\n36,1\n"


def test_distribution_plot_carries_the_failures_on_the_time_scale():
    result = fit("weibull", _df(PUMPS), {"x": "months", "c": "censored"})
    emp = result["plot"]["empirical"]
    # One point per failure, none for the units still running.
    assert len(emp["x"]) == 13 == len(result["plot"]["scatter"]["x"])
    assert emp["x"][0] == pytest.approx(4.0)
    assert emp["method"] == "Nelson-Aalen"
    # The data's fraction failed rises; the model's is its CDF at each time.
    assert all(b >= a for a, b in zip(emp["F"], emp["F"][1:]))
    assert all(0 < f < 1 for f in emp["model_F"])
    alpha = next(p["value"] for p in result["params"] if p["name"] == "alpha")
    beta = next(p["value"] for p in result["params"] if p["name"] == "beta")
    assert emp["model_F"][0] == pytest.approx(1 - np.exp(-((4.0 / alpha) ** beta)), rel=1e-6)


def test_offset_fit_points_are_on_the_raw_time_scale():
    df = _df("hours\n" + "".join(f"{v}\n" for v in (140, 160, 175, 190, 205, 230, 260, 300, 340, 410)))
    result = fit("weibull", df, {"x": "hours"}, options={"offset": True, "how": "MPS"})
    emp = result["plot"]["empirical"]
    assert emp["x"][0] == pytest.approx(140.0)
    assert emp["model_F"][0] > 0


def test_mixture_plot_carries_the_failures_too():
    times = [312, 420, 506, 588, 655, 719, 773, 824, 889, 946, 998, 1051, 1104, 1158, 1203, 1259, 1312, 1366,
             1421, 1485, 1542, 1607, 1683, 1764, 1842, 1925, 2014, 2118, 2233, 2401]
    df = pd.DataFrame({"hours": times})
    result = fit("mixture", df, {"x": "hours"}, options={"mixture": 2, "mixture_distribution": "weibull"})
    emp = result["plot"]["empirical"]
    assert len(emp["x"]) == 30
    assert all(0 <= f <= 1 for f in emp["model_F"])


def test_discrete_fit_counts_observed_against_expected():
    df = _df("cycles,censored\n" + "".join(f"{v},0\n" for v in (2, 3, 3, 4, 5, 5, 6, 8, 10, 12)) + "12,1\n12,1\n")
    result = fit("geometric", df, {"x": "cycles", "c": "censored"})
    counts = result["counts"]
    assert counts["k"] == list(range(1, 13))
    # Every unit is at risk at count 1; two failed at count 3.
    assert counts["at_risk"][0] == 12
    assert counts["failed"][2] == 2
    # The model's expected failures add up to about the observed failures.
    assert sum(counts["expected"]) == pytest.approx(sum(counts["failed"]), rel=0.25)
    # The chance of failing at exactly each count: the model's pmf, and the
    # data's own Kaplan-Meier step, both between 0 and 1.
    p = next(q["value"] for q in result["params"] if q["name"] == "p")
    assert counts["pmf"][0] == pytest.approx(p, rel=1e-6)
    assert all(0 <= v <= 1 for v in counts["observed"])


def test_kaplan_meier_estimate_carries_its_life_table():
    result = fit("kaplan_meier", _df(PUMPS), {"x": "months", "c": "censored"})
    est = result["estimate"]
    assert len(est["at_risk"]) == len(est["x"]) == len(est["failed"])
    assert est["at_risk"][0] == 16
    assert est["failed"][0] == 1


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
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _save(client, distribution: str) -> dict:
    res = client.post(
        "/api/models",
        data={"name": f"Pumps {distribution}", "distribution": distribution, "x": "months", "c": "censored",
              "unit": "months"},
        files={"file": ("pumps.csv", PUMPS.encode(), "text/csv")},
    )
    assert res.status_code == 200, res.text
    return res.json()


def test_a_royston_parmar_spline_is_compared_with_the_plain_distributions(client):
    model = _save(client, "royston_parmar")
    res = client.post(f"/api/models/{model['id']}/compare")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["criterion"] == "aic"
    assert any(c["id"] == "weibull" for c in body["candidates"])


def test_a_non_parametric_estimate_still_cannot_be_compared(client):
    model = _save(client, "kaplan_meier")
    assert client.post(f"/api/models/{model['id']}/compare").status_code == 422
