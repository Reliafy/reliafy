"""Download as Python for regression models (fixed covariates and covariates
that change over time): each saved model's script, run in its own process,
prints the numbers the model page shows."""

import io
import json

import matplotlib

matplotlib.use("Agg")

import mongomock
import numpy as np
import pandas as pd
import pytest

from backend import fitting
from backend.services import regression_export, samples
from backend.tests.python_scripts import close, run

A = "user-a"
USERS = {A: {"uid": A, "email": "a@x.com", "name": "A"}}


def _fleet(n=80, seed=3) -> pd.DataFrame:
    """Units whose Weibull life shortens with load and differs by site; the
    test ends at 900 hours."""
    rng = np.random.default_rng(seed)
    rows = []
    for k in range(n):
        load = float(np.round(rng.uniform(0.5, 1.5), 3))
        site = ["East", "North", "West"][k % 3]
        temp = float(np.round(rng.normal(60, 8), 2))
        scale = 1000.0 * np.exp(-0.9 * (load - 1.0)) * {"East": 1.0, "North": 0.8, "West": 1.25}[site]
        t = float(scale * rng.weibull(1.8))
        failed = t < 900
        rows.append({"unit": f"U{k:03d}", "hours": round(min(t, 900.0), 3), "status": 0 if failed else 1,
                     "load": load, "site": site, "temp": temp, "batch": f"B{k % 6}"})
    return pd.DataFrame(rows)


FLEET = _fleet()


def _csv(df: pd.DataFrame) -> bytes:
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue().encode()


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
        c = TestClient(app)
        c.db = test_db
        yield c
    finally:
        app.dependency_overrides.clear()


def _save(client, df: pd.DataFrame, **form) -> dict:
    data = {"name": "Fleet", "unit": "hours", **form}
    res = client.post("/api/models", data=data, files={"file": ("fleet.csv", _csv(df), "text/csv")})
    assert res.status_code == 200, res.text
    return res.json()


def _source(client, saved: dict) -> str:
    """The script, from the route when it's mounted, else from the service."""
    res = client.get(f"/api/models/{saved['id']}/export.py")
    if res.status_code == 200:
        return res.text
    from backend.db import from_doc
    from backend.schema import Model
    from backend.services import datasets as datasets_service

    model = from_doc(Model, client.db.models.find_one({"_id": saved["id"]}))
    dataset = datasets_service.get_dataset(client.db, model.dataset_id, owner_id=model.owner_id)
    return regression_export.script(model, datasets_service.load_dataframe(dataset))


def _check(client, saved: dict, tmp_path) -> dict:
    """Run the script and check every number the page shows."""
    source = _source(client, saved)
    out = run(source, tmp_path)
    r = saved["results"]
    if r.get("frailty"):
        for p in r.get("params") or []:
            got = out[f"Baseline {p['name']}"]
            close(got["value"], p["value"])
            if p.get("ci"):
                close(got["low"], p["ci"][0])
                close(got["high"], p["ci"][1])
    else:
        for p in r.get("params") or []:
            got = out[f"Baseline {regression_export.label(p['name'])}"]
            close(got["value"], p["value"])
            if p.get("ci"):
                close(got["low"], p["ci"][0])
                close(got["high"], p["ci"][1])
    assert r["coefficients"], "a regression has coefficients"
    words = (r.get("ratio_label") or "")
    for c in r["coefficients"]:
        name = regression_export.label(c["name"])
        got = out[f"Coefficient {name}"]
        close(got["value"], c["value"])
        if c.get("ci"):
            close(got["low"], c["ci"][0])
            close(got["high"], c["ci"][1])
        else:
            assert got["low"] is None
        if words:
            ratio = out[f"{words[0].upper() + words[1:]} {name}"]
            close(ratio["value"], c["ratio"])
            if c.get("ratio_ci"):
                close(ratio["low"], c["ratio_ci"][0])
                close(ratio["high"], c["ratio_ci"][1])
    at = r.get("at_covariate_means")
    if at:
        close(out["Median life at the covariate means"]["value"], at["median"])
        close(out["B10 life at the covariate means"]["value"], at["b10"])
        close(out["Mean life at the covariate means"]["value"], at["mttf"], rel=1e-4)
    else:
        assert "Median life at the covariate means" not in out
    if r.get("frailty"):
        f = r["frailty"]
        got = out["Frailty variance theta"]
        close(got["value"], f["theta"])
        if f.get("theta_ci"):
            close(got["low"], f["theta_ci"][0])
            close(got["high"], f["theta_ci"][1])
    return {"source": source, "out": out}


def test_weibull_ph_with_numeric_covariates(client, tmp_path):
    saved = _save(client, FLEET, distribution="weibull_ph", x="hours", c="status", z=["load", "temp"])
    done = _check(client, saved, tmp_path)
    assert "surpyval.WeibullPH.fit_from_df(" in done["source"]
    assert "Z_cols=['load', 'temp']" in done["source"]
    assert saved["results"]["at_covariate_means"]["median"] is not None
    # The headline: the script says what it is and how to install it.
    assert "requirements: surpyval==" in done["source"]


def test_a_text_covariate_is_a_category(client, tmp_path):
    saved = _save(client, FLEET, distribution="weibull_ph", x="hours", c="status", z=["load", "site"],
                  covariate_units=json.dumps({"load": "kN"}))
    done = _check(client, saved, tmp_path)
    assert "formula='load + site'" in done["source"]
    assert any("site[T." in c["name"] for c in saved["results"]["coefficients"])


def test_a_formula_with_an_interaction(client, tmp_path):
    saved = _save(client, FLEET, distribution="weibull_ph", x="hours", c="status", formula="load * temp")
    done = _check(client, saved, tmp_path)
    assert any(":" in c["name"] for c in saved["results"]["coefficients"])
    assert "formula='load * temp'" in done["source"]


@pytest.mark.parametrize("distribution", ["weibull_aft", "lognormal_po", "weibull_ah", "loglogistic_ph"])
def test_other_parametric_effects(client, tmp_path, distribution):
    saved = _save(client, FLEET, distribution=distribution, x="hours", c="status", z=["load"])
    done = _check(client, saved, tmp_path)
    if distribution == "loglogistic_ph":
        assert "surpyval.PH(surpyval.LogLogistic).fit_from_df(" in done["source"]


def test_cox_ph_with_ties_and_strata(client, tmp_path):
    saved = _save(client, FLEET, distribution="cox_ph", x="hours", c="status", z=["load"],
                  cox=json.dumps({"tie_method": "breslow", "strata": "site", "cluster": "batch"}))
    done = _check(client, saved, tmp_path)
    src = done["source"]
    assert "surpyval.CoxPH.fit_from_df(" in src and "tie_method='breslow'" in src and "strata_col='site'" in src
    assert "clustered by “batch”" in src.replace("\n# ", " ")
    assert saved["results"]["params"] == []


def test_buckley_james(client, tmp_path):
    saved = _save(client, FLEET, distribution="buckley_james", x="hours", c="status", z=["load"])
    done = _check(client, saved, tmp_path)
    assert "bootstrap_ci(" in done["source"]


def test_shared_frailty(client, tmp_path):
    saved = _save(client, FLEET, distribution="weibull_frailty", x="hours", c="status", z=["load"],
                  group="batch")
    done = _check(client, saved, tmp_path)
    assert "group_col='batch'" in done["source"]


def test_inspection_intervals(client, tmp_path):
    df = FLEET.copy()
    # Inspected every 100 hours: a failure is known to lie between two looks.
    df["last_ok"] = np.where(df["status"] == 0, np.floor(df["hours"] / 100) * 100, df["hours"])
    df["found"] = np.where(df["status"] == 0, np.floor(df["hours"] / 100) * 100 + 100, df["hours"])
    saved = _save(client, df, distribution="weibull_ph", xl="last_ok", xr="found", c="status", z=["load"])
    done = _check(client, saved, tmp_path)
    assert "xl_col='last_ok'" in done["source"]


def test_a_flipped_status_column(client, tmp_path):
    df = FLEET.copy()
    df["failed"] = 1 - df.pop("status")
    saved = _save(client, df, distribution="weibull_ph", x="hours", c="failed", z=["load"], c_invert="true")
    done = _check(client, saved, tmp_path)
    assert "flipped" in done["source"]
    # The same numbers as the unflipped data.
    plain = _save(client, FLEET, distribution="weibull_ph", x="hours", c="status", z=["load"])
    assert plain["results"]["coefficients"][0]["value"] == pytest.approx(
        saved["results"]["coefficients"][0]["value"])


def test_covariates_that_change_over_time(client, tmp_path):
    spec = next(d for d in samples.SAMPLE_DATASETS if d["id"] == "sample-ds-pump-load")
    df = fitting.read_dataframe(spec["csv"])
    saved = _save(client, df, distribution="weibull_ph", i="pump", xl="start_h", xr="stop_h", c="censored",
                  z=["load_pct"])
    done = _check(client, saved, tmp_path)
    assert ".fit_tvc_from_df(data, 'pump', 'start_h', 'stop_h', 'censored', Z_cols=['load_pct'])" in done["source"]


def test_a_non_regression_model_is_refused():
    from backend.schema import Model

    model = Model(id="m", name="Plain", owner_id=A, dataset_id="d", kind="distribution",
                  distribution_id="weibull", spec={"distribution_id": "weibull", "mapping": {"x": "hours"}},
                  results={"kind": "distribution"})
    with pytest.raises(fitting.FitError):
        regression_export.script(model, FLEET)
