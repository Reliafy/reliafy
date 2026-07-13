"""Non-parametric estimators (KM/NA/FH/Turnbull) as first-class models."""

import matplotlib

matplotlib.use("Agg")

import io

import mongomock
import numpy as np
import pandas as pd
import pytest

from backend import fitting

A = "user-a"
USERS = {A: {"uid": A, "email": "a@x.com", "name": "A"}}


def _life_df(n=60, seed=4):
    rng = np.random.default_rng(seed)
    t = rng.weibull(2.2, n) * 1000
    c = np.zeros(n, dtype=int)
    c[int(n * 0.8):] = 1
    return pd.DataFrame({"t": t, "c": c})


@pytest.mark.parametrize("did", ["kaplan_meier", "nelson_aalen", "fleming_harrington"])
def test_nonparametric_fit(did):
    r = fitting.fit(did, _life_df(), {"x": "t", "c": "c"}, None, None, "hours")
    assert r["kind"] == "nonparametric"
    assert r["params"] == [] and r["gof"] == []
    est = r["estimate"]
    assert len(est["x"]) == len(est["R"]) > 0
    R = np.array(est["R"])
    assert np.all(np.diff(R) <= 1e-9)          # monotone non-increasing
    assert R[0] <= 1.0
    assert r["metrics"]["median"] and r["metrics"]["mttf"]
    # sf is available (interpolated) so the calculator works.
    assert any(v is not None for v in r["functions"]["curves"]["sf"])


def test_turnbull_interval_censoring():
    df = pd.DataFrame({"lo": [0, 100, 200, 300, 150.0], "hi": [150, 250, 400, 600, 350.0]})
    r = fitting.fit("turnbull", df, {"xl": "lo", "xr": "hi"}, None, None, "hours")
    assert r["kind"] == "nonparametric"
    assert len(r["estimate"]["x"]) > 0


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


def test_nonparametric_in_distributions_endpoint(client):
    ids = [d["id"] for d in client.get("/api/distributions").json()["distributions"]]
    for did in ("kaplan_meier", "nelson_aalen", "fleming_harrington", "turnbull"):
        assert did in ids


def test_save_and_resolve_nonparametric(client):
    csv = io.BytesIO(_life_df().to_csv(index=False).encode())
    r = client.post(
        "/api/models",
        data={"name": "KM bearings", "distribution": "kaplan_meier", "x": "t", "c": "c", "unit": "hours"},
        files={"file": ("d.csv", csv, "text/csv")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "nonparametric"
    assert body["results"]["estimate"]["R"]
    assert body["dataset_id"]  # data uploaded

    # Refit-on-demand reconstruction works (downstream / RBD path).
    from backend.services import models as ms
    live = ms.get_live_model(client.db, body["id"], A)
    assert live is not None
    sf = float(np.asarray(live["model"].sf([500])).ravel()[0])
    assert 0.0 <= sf <= 1.0
