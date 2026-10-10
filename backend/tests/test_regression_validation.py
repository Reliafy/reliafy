"""How good is this regression model? (#176): Harrell's C, the integrated
Brier score against a covariate-free baseline and the time-dependent AUC —
stored at fit time, computed lazily (and cached) for older saved models,
and reported over MCP and the REST API."""

import io

import matplotlib

matplotlib.use("Agg")

import mongomock
import numpy as np
import pandas as pd
import pytest

from backend import model_validation as mv
from backend.fitting import REGRESSION_MODELS, fit

OWNER = "user-a"


def _rossi() -> pd.DataFrame:
    from surpyval.datasets import load_rossi_static

    df = load_rossi_static()[["week", "arrest", "fin", "age", "prio"]].copy()
    df["c"] = 1 - df["arrest"]  # Reliafy: 0 = failed, 1 = still running
    df["grp"] = np.where(df["fin"] == 1, "aid", "none")
    return df


MAPPING = {"x": "week", "c": "c"}


def _csv(df: pd.DataFrame) -> bytes:
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue().encode()


# ---- The scores --------------------------------------------------------------

def test_scores_match_surpyval_and_beat_the_baseline():
    from surpyval import KaplanMeier
    from surpyval.metrics import concordance_index, integrated_brier_score, survival_probability

    df = _rossi()
    v = fit("cox_ph", df, MAPPING, covariates=["fin", "age", "prio"])["validation"]
    assert v["available"] is True
    assert v["n_units"] == v["n_total"] == len(df) and v["sampled"] is False

    # Harrell's C equals SurPyval's on the linear predictor's ranking.
    from surpyval.univariate.regression import CoxPH

    model = CoxPH.fit_from_df(df, x_col="week", c_col="c", Z_cols=["fin", "age", "prio"])
    x, c = df["week"].to_numpy(float), df["c"].to_numpy()
    Z = df[["fin", "age", "prio"]]
    risk = model.Hf(np.full(len(df), np.median(x)), Z)
    assert v["concordance"]["value"] == pytest.approx(concordance_index(x, c, risk))
    assert 0.6 < v["concordance"]["value"] < 0.7
    assert v["concordance"]["rating"] == "weak"
    assert "comparable pairs" in v["concordance"]["reading"]

    # The integrated Brier score over the same grid, and the Kaplan-Meier baseline.
    b = v["brier"]
    times = np.unique(np.quantile(x[c == 0], np.linspace(0.1, 0.9, mv.N_TIMES)))
    times = times[times < x.max()]
    assert b["from"] == pytest.approx(times[0]) and b["to"] == pytest.approx(times[-1])
    assert b["model"] == pytest.approx(integrated_brier_score(x, c, survival_probability(model, Z, times), times))
    km = np.tile(KaplanMeier.fit(x, c).sf(times), (len(x), 1))
    assert b["baseline"] == pytest.approx(integrated_brier_score(x, c, km, times))
    assert b["model"] < b["baseline"]
    assert b["improvement"] == pytest.approx((b["baseline"] - b["model"]) / b["baseline"])
    assert "cut the prediction error" in b["reading"]

    # Time-dependent AUC at the failure-time quartiles.
    assert len(v["auc"]) == 3
    assert all(0.5 < a["value"] < 0.8 for a in v["auc"])
    assert [a["time"] for a in v["auc"]] == sorted(a["time"] for a in v["auc"])


@pytest.mark.parametrize("dist_id", ["weibull_ph", "weibull_aft", "lognormal_po", "weibull_ah"])
def test_every_regression_family_is_scored(dist_id):
    v = fit(dist_id, _rossi(), MAPPING, formula="grp + age + prio")["validation"]
    assert v["available"] is True
    assert 0.55 < v["concordance"]["value"] < 0.75
    assert v["brier"] is not None and v["auc"]


def test_registry_regression_ids_all_score():
    """Every registered regression family gets the block (available or with a reason)."""
    df = _rossi()
    grouped = df.assign(site=[f"S{i % 12}" for i in range(len(df))])
    for dist_id in REGRESSION_MODELS:
        if REGRESSION_MODELS[dist_id].get("frailty"):  # needs its Group by column (#179)
            v = fit(dist_id, grouped, {**MAPPING, "group": "site"}, covariates=["fin", "age", "prio"])["validation"]
        else:
            v = fit(dist_id, df, MAPPING, covariates=["fin", "age", "prio"])["validation"]
        assert "available" in v, dist_id
        assert v["available"] or v["reason"], dist_id


def test_c_invert_scores_the_flipped_data():
    df = _rossi()
    normal = fit("weibull_ph", df, MAPPING, covariates=["age", "prio"])["validation"]
    flipped = df.assign(c=1 - df["c"])
    inverted = fit("weibull_ph", flipped, MAPPING, covariates=["age", "prio"],
                   options={"c_invert": True})["validation"]
    assert inverted["concordance"]["value"] == pytest.approx(normal["concordance"]["value"])
    assert inverted["brier"]["model"] == pytest.approx(normal["brier"]["model"])


def test_large_data_is_sampled_with_a_fixed_seed(monkeypatch):
    monkeypatch.setattr(mv, "MAX_UNITS", 200)
    df = _rossi()  # 432 units
    a = fit("weibull_ph", df, MAPPING, covariates=["age", "prio"])["validation"]
    b = fit("weibull_ph", df, MAPPING, covariates=["age", "prio"])["validation"]
    assert a["sampled"] is True and a["n_units"] == 200 and a["n_total"] == 432
    assert a["seed"] == mv.SEED and "200 of the 432 units" in a["sample_note"]
    assert a["concordance"] == b["concordance"] and a["brier"] == b["brier"]


def test_counts_are_units():
    from surpyval.univariate.regression import CoxPH

    df = pd.DataFrame({"t": [5, 8, 12, 20, 30, 7, 15, 25], "c": [0, 0, 0, 1, 0, 0, 0, 1],
                       "n": [3, 2, 4, 5, 1, 2, 2, 3], "z": [1, 1, 1, 1, 1, 0, 0, 0]})
    model = CoxPH.fit_from_df(df, x_col="t", c_col="c", n_col="n", Z_cols=["z"])
    v = mv.validate_regression(model, df, {"x": "t", "c": "c", "n": "n"}, ["z"])
    assert v["available"] is True and v["n_total"] == v["n_units"] == 22


def test_counts_are_sampled_without_replacement(monkeypatch):
    from surpyval.univariate.regression import CoxPH

    monkeypatch.setattr(mv, "MAX_UNITS", 10)
    df = pd.DataFrame({"t": [5, 8, 12, 20, 30, 7, 15, 25], "c": [0, 0, 0, 1, 0, 0, 0, 1],
                       "n": [3, 2, 4, 5, 1, 2, 2, 3], "z": [1, 1, 1, 1, 1, 0, 0, 0]})
    model = CoxPH.fit_from_df(df, x_col="t", c_col="c", n_col="n", Z_cols=["z"])
    v = mv.validate_regression(model, df, {"x": "t", "c": "c", "n": "n"}, ["z"])
    assert v["sampled"] is True and v["n_units"] == 10 and v["n_total"] == 22


def test_left_censored_truncated_and_too_few_failures_are_not_available():
    from surpyval import WeibullPH

    df = _rossi()
    model = WeibullPH.fit_from_df(df, x_col="week", c_col="c", Z_cols=["age"])
    left = df.assign(c=np.where(np.arange(len(df)) == 0, -1, df["c"]))
    v = mv.validate_regression(model, left, MAPPING, ["age"])
    assert v == {"available": False, "reason": v["reason"]} and "left- or interval-censored" in v["reason"]

    trunc = df.assign(tl=np.where(np.arange(len(df)) < 5, 1.0, np.nan))
    v = mv.validate_regression(model, trunc, {**MAPPING, "tl": "tl"}, ["age"])
    assert v["available"] is False and "truncated" in v["reason"]
    # A mapped but empty truncation column is no truncation at all.
    v = mv.validate_regression(model, df.assign(tl=np.nan), {**MAPPING, "tl": "tl"}, ["age"])
    assert v["available"] is True

    one = df.assign(c=np.where(np.arange(len(df)) == 0, 0, 1))
    v = mv.validate_regression(model, one, MAPPING, ["age"])
    assert v["available"] is False and "two failures" in v["reason"]


def test_validation_never_raises():
    class Broken:
        def Hf(self, *a):
            raise RuntimeError("boom")

        def sf(self, *a):
            raise RuntimeError("boom")

    v = mv.validate_regression(Broken(), _rossi(), MAPPING, ["age"])
    assert v["available"] is False and v["reason"]


def test_readings():
    assert mv.concordance_rating(0.5) == "no better than chance"
    assert mv.concordance_rating(0.6) == "weak"
    assert mv.concordance_rating(0.8) == "good"
    assert mv.concordance_rating(0.9) == "strong"
    assert mv.concordance_reading(0.72).startswith("Moderate. In 72% of")
    assert "about the same" in mv.brier_reading(0.004).lower()
    assert "worse than ignoring" in mv.brier_reading(-0.05)


def test_plain_distributions_have_no_block():
    df = _rossi()
    assert "validation" not in fit("weibull", df, MAPPING)


# ---- Saved models: stored at fit time, lazy + cached for older ones ----------

@pytest.fixture()
def session(monkeypatch):
    from backend import db

    test_db = mongomock.MongoClient()["reliafy_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    yield test_db


def _saved(session):
    from backend.services import datasets as ds
    from backend.services import models as ms

    d = ds.create_dataset(session, "rossi.csv", _csv(_rossi()), OWNER)
    return ms.save_model(session, "Rossi PH", d, "weibull_ph", MAPPING, [], "grp + age + prio",
                         owner_id=OWNER)


def test_saved_model_stores_the_scores(session):
    m = _saved(session)
    stored = session.models.find_one({"_id": m.id})["results"]["validation"]
    assert stored["available"] is True and stored["concordance"]["value"] > 0.6


def test_older_model_is_scored_lazily_and_cached(session, monkeypatch):
    from backend.services import models as ms

    m = _saved(session)
    expected = m.results["validation"]
    # A model saved before #176: no scores in its results.
    session.models.update_one({"_id": m.id}, {"$unset": {"results.validation": ""}})
    old = ms.get_model(session, m.id, OWNER)
    assert "validation" not in old.results

    v = ms.ensure_validation(session, old)
    assert v["concordance"]["value"] == pytest.approx(expected["concordance"]["value"])
    assert session.models.find_one({"_id": m.id})["results"]["validation"] == v

    # Cached: a second read doesn't refit.
    monkeypatch.setattr(ms, "_refit_result", lambda *a: pytest.fail("refitted"))
    assert ms.ensure_validation(session, ms.get_model(session, m.id, OWNER)) == v


def test_older_model_without_its_dataset_is_not_available(session):
    from backend.services import models as ms

    m = _saved(session)
    session.models.update_one({"_id": m.id}, {"$unset": {"results.validation": ""}})
    session.datasets.delete_many({})
    v = ms.ensure_validation(session, ms.get_model(session, m.id, OWNER))
    assert v["available"] is False and "no longer in Reliafy" in v["reason"]
    # Nothing cached: there was nothing to compute it from.
    assert "validation" not in session.models.find_one({"_id": m.id})["results"]


def test_non_regression_models_have_no_scores(session):
    from backend.services import datasets as ds
    from backend.services import models as ms

    d = ds.create_dataset(session, "rossi.csv", _csv(_rossi()), OWNER)
    m = ms.save_model(session, "W", d, "weibull", MAPPING, [], None, owner_id=OWNER)
    assert ms.ensure_validation(session, m) is None


def test_refit_replaces_the_scores(session):
    from backend.services import models as ms

    m = _saved(session)
    before = m.results["validation"]["concordance"]["value"]
    ms.update_fit(session, m.id, OWNER, "weibull_ph", MAPPING, ["age"], None, None, None)
    after = session.models.find_one({"_id": m.id})["results"]["validation"]["concordance"]["value"]
    assert after != pytest.approx(before)


# ---- API ---------------------------------------------------------------------

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
    app.dependency_overrides[get_current_user] = lambda: {"uid": OWNER, "email": "a@example.org", "name": "A"}
    tc = TestClient(app)
    tc.db = test_db
    try:
        yield tc
    finally:
        app.dependency_overrides.clear()


def test_validation_endpoint(client):
    r = client.post(
        "/api/models",
        data={"name": "Rossi", "distribution": "cox_ph", "x": "week", "c": "c", "z": ["fin", "age", "prio"]},
        files={"file": ("rossi.csv", io.BytesIO(_csv(_rossi())), "text/csv")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["results"]["validation"]["available"] is True
    model_id = body["id"]

    client.db.models.update_one({"_id": model_id}, {"$unset": {"results.validation": ""}})
    assert "validation" not in client.get(f"/api/models/{model_id}").json()["results"]
    got = client.get(f"/api/models/{model_id}/validation")
    assert got.status_code == 200 and got.json()["concordance"]["value"] == pytest.approx(
        body["results"]["validation"]["concordance"]["value"])
    assert client.get(f"/api/models/{model_id}").json()["results"]["validation"] == got.json()

    assert client.get("/api/models/nope/validation").status_code == 404


def test_validation_endpoint_refuses_plain_models(client):
    r = client.post(
        "/api/models",
        data={"name": "W", "distribution": "weibull", "x": "week", "c": "c"},
        files={"file": ("rossi.csv", io.BytesIO(_csv(_rossi())), "text/csv")},
    )
    assert client.get(f"/api/models/{r.json()['id']}/validation").status_code == 422


def test_rest_api_v1_model_reports_the_scores(client):
    client.db.users.update_one({"_id": OWNER}, {"$set": {"uid": OWNER, "email": "a@example.org", "name": "A"}},
                               upsert=True)
    raw = client.post("/api/tokens", json={"name": "test"}).json()["token"]
    auth = {"Authorization": f"Bearer {raw}"}
    r = client.post(
        "/api/models",
        data={"name": "Rossi", "distribution": "weibull_ph", "x": "week", "c": "c", "z": ["age", "prio"]},
        files={"file": ("rossi.csv", io.BytesIO(_csv(_rossi())), "text/csv")},
    )
    model_id = r.json()["id"]
    client.db.models.update_one({"_id": model_id}, {"$unset": {"results.validation": ""}})
    got = client.get(f"/api/v1/models/{model_id}", headers=auth)
    assert got.status_code == 200, got.text
    assert got.json()["validation"]["available"] is True


# ---- MCP ---------------------------------------------------------------------

from backend.tests.test_mcp import A as MCP_A, _call, _ok, env  # noqa: E402,F401 - the MCP harness


def test_mcp_fit_and_get_model_report_the_scores(env):
    ds = _ok(_call(env.token[MCP_A], "upload_dataset", {"name": "Rossi", "csv": _csv(_rossi()).decode()}))
    args = {"dataset_id": ds["id"], "distribution": "weibull_ph", "time_column": "week",
            "censor_column": "c", "covariates": ["fin", "age", "prio"]}
    fitted = _ok(_call(env.token[MCP_A], "fit_distribution", args))
    v = fitted["validation"]
    assert v["available"] is True and v["brier"]["model"] < v["brier"]["baseline"] and v["auc"]

    saved = _ok(_call(env.token[MCP_A], "fit_and_save_model", {**args, "name": "Rossi PH"}))
    assert saved["validation"]["concordance"] == v["concordance"]

    # A model saved before #176 is scored on read, and the scores are cached.
    env.db.models.update_one({"_id": saved["model_id"]}, {"$unset": {"results.validation": ""}})
    got = _ok(_call(env.token[MCP_A], "get_model", {"model_id": saved["model_id"]}))
    assert got["validation"]["concordance"]["value"] == pytest.approx(v["concordance"]["value"])
    assert env.db.models.find_one({"_id": saved["model_id"]})["results"]["validation"]["available"] is True


def test_mcp_plain_fits_have_no_scores(env):
    out = _ok(_call(env.token[MCP_A], "fit_distribution", {"data": [10, 20, 30, 45, 60]}))
    assert "validation" not in out
