"""A life model's data in words, "5 failed, 7 running" (#303).

A fit records how many units failed and how many were still running
(``split``), counted off the inputs SurPyval is given; a saved model opened
later shows the same, and one saved before fits recorded it gets it from its
dataset (with the censor column read the way the fit read it).
"""

import io

import mongomock
import numpy as np
import pandas as pd
import pytest
import surpyval

from backend import fitting
from backend.services import model_split

OWNER = "user-a"
X = [120.0, 210.0, 330.0, 450.0, 520.0, 610.0, 700.0, 700.0, 700.0, 700.0, 700.0, 700.0]
C = [0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1]
_CSV = "Time,Censored\n" + "".join(f"{x:g},{c}\n" for x, c in zip(X, C))
_MAPPING = {"x": "Time", "c": "Censored"}


def _df(csv=_CSV):
    return pd.read_csv(io.StringIO(csv))


def _surpyval_counts(model):
    """Failed / running as SurPyval's own fitted data holds them."""
    c, n = np.asarray(model.data["c"]), np.asarray(model.data["n"])
    return int(n[c == 0].sum()), int(n[c == 1].sum())


def test_a_fit_records_failed_and_running_as_surpyval_reads_the_data():
    r = fitting.fit("weibull", _df(), _MAPPING, unit="hours")
    assert r["split"] == {"failed": 5, "running": 7, "other": 0}
    direct = surpyval.Weibull.fit(x=np.array(X), c=np.array(C))
    assert (r["split"]["failed"], r["split"]["running"]) == _surpyval_counts(direct)
    assert sum(r["split"].values()) == r["n"]


def test_counts_weight_by_the_count_column_and_follow_the_inversion():
    df = pd.DataFrame({"t": [100, 200, 300], "c": [1, 1, 0], "n": [2, 3, 4]})
    r = fitting.fit("weibull", df, {"x": "t", "c": "c", "n": "n"}, options={"c_invert": True})
    # Inverted: the 1s failed (2 + 3), the 0 was still running (4).
    assert r["split"] == {"failed": 5, "running": 4, "other": 0}
    direct = surpyval.Weibull.fit(x=np.array([100, 200, 300]), c=np.array([0, 0, 1]), n=np.array([2, 3, 4]))
    assert (r["split"]["failed"], r["split"]["running"]) == _surpyval_counts(direct)


def test_best_fit_and_kaplan_meier_record_it_interval_data_does_not():
    assert fitting.fit("best", _df(), _MAPPING)["split"] == {"failed": 5, "running": 7, "other": 0}
    assert fitting.fit("kaplan_meier", _df(), _MAPPING)["split"]["running"] == 7
    df = pd.DataFrame({"lo": [10.0, 20.0, 30.0, 40.0], "hi": [15.0, 28.0, 35.0, 60.0]})
    assert "split" not in fitting.fit("weibull", df, {"xl": "lo", "xr": "hi"})


def test_split_of_inputs_counts_other_censoring_apart():
    out = model_split.split_of_inputs({"x": np.array([1.0, 2.0, 3.0, 4.0]), "c": np.array([0, 1, -1, 0])})
    assert out == {"failed": 2, "running": 1, "other": 1}
    assert model_split.split_of_inputs({"xl": np.array([1.0]), "xr": np.array([2.0])}) is None


# ---- a saved model's page --------------------------------------------------------------------

@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    test_db = mongomock.MongoClient()["reliafy_split_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    model_split._CACHE.clear()
    app.dependency_overrides[get_current_user] = lambda: {
        "uid": OWNER, "email": "a@example.com", "name": "A"}
    tc = TestClient(app)
    tc.db = test_db
    try:
        yield tc
    finally:
        app.dependency_overrides.clear()


def _save(client, csv=_CSV, **extra):
    saved = client.post(
        "/api/models",
        data={"name": "Pump bearings", "distribution": "weibull", **_MAPPING, **extra},
        files={"file": ("bearings.csv", io.BytesIO(csv.encode()), "text/csv")},
    )
    assert saved.status_code == 200, saved.text
    return saved.json()


def test_a_saved_model_says_failed_and_running(client):
    body = _save(client)
    got = client.get(f"/api/models/{body['id']}").json()
    assert got["results"]["split"] == {"failed": 5, "running": 7, "other": 0}


def test_a_model_saved_before_gets_it_from_its_dataset(client):
    # The consultant's file: 1 = failed, read inverted by the fit.
    csv = "Time,Censored\n" + "".join(f"{x:g},{1 - c}\n" for x, c in zip(X, C))
    body = _save(client, csv=csv, c_invert="1")
    client.db.models.update_one({"_id": body["id"]}, {"$unset": {"results.split": ""}})
    assert "split" not in client.db.models.find_one({"_id": body["id"]})["results"]
    got = client.get(f"/api/models/{body['id']}").json()
    assert got["results"]["split"] == {"failed": 5, "running": 7, "other": 0}
    # Nothing is written back to the saved model.
    assert "split" not in client.db.models.find_one({"_id": body["id"]})["results"]
