"""The time unit is the model's own: it goes into SurPyval as ``unit=`` on
every fit and every model made from parameters, a saved model keeps it in its
``to_dict``, a model saved before that keeps its saved unit, and Download as
Python passes it into the script's call."""

import matplotlib

matplotlib.use("Agg")

import mongomock  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402

from backend import fitting  # noqa: E402
from backend.tests.python_scripts import run  # noqa: E402

A = "user-a"
USER = {"uid": A, "email": "a@x.com", "name": "A"}

TIMES = [120, 340, 510, 700, 980, 1200, 1500, 1800, 2100, 2500, 2900, 3300]
CENSOR = [0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 1, 1]
LIFE = pd.DataFrame({"t": TIMES, "c": CENSOR, "temp": [40, 45, 50, 55, 42, 47, 52, 57, 44, 49, 54, 59]})
MAP = {"x": "t", "c": "c"}
PUMPS = "months,censored\n" + "".join(f"{v},0\n" for v in (4, 7, 9, 11, 13, 15, 16, 18, 19, 21, 23, 24, 26)) \
    + "36,1\n36,1\n36,1\n"


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
    app.dependency_overrides[get_current_user] = lambda: USER
    tc = TestClient(app)
    tc.db = test_db
    try:
        yield tc
    finally:
        app.dependency_overrides.clear()


def _live(result):
    return fitting._MODEL_STORE[result["functions"]["model_id"]]["model"]


# ---------------------------------------------------------------------------
# Every fit path in fitting.fit
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("distribution, mapping, options, covariates", [
    ("weibull", MAP, None, None),
    ("lognormal", MAP, {"offset": True}, None),
    ("best", MAP, None, None),
    ("mixture", {"x": "t"}, None, None),
    ("kaplan_meier", MAP, None, None),
    ("turnbull", MAP, None, None),
    ("geometric", {"x": "t"}, None, None),
    ("weibull_ph", MAP, None, ["temp"]),
    ("cox_ph", MAP, None, ["temp"]),
], ids=["weibull", "offset", "best", "mixture", "kaplan_meier", "turnbull", "discrete", "weibull_ph", "cox_ph"])
def test_every_fit_carries_the_unit_on_the_surpyval_model(distribution, mapping, options, covariates):
    df = LIFE.copy()
    if distribution == "geometric":
        df["t"] = (df["t"] // 100).astype(int)
    result = fitting.fit(distribution, df, mapping, covariates=covariates, unit="hours", options=options)
    model = _live(result)
    assert model.unit == "Hours"  # the app's one spelling, now SurPyval's model.unit
    assert result["unit"] == "Hours"  # what every page and read shows, as before


def test_a_mixture_from_best_fit_keeps_the_unit_on_the_surpyval_mixture():
    result = fitting._fit_mixture("weibull", LIFE, {"x": "t"}, 2, unit="cycles")
    model = _live(result)
    assert model.unit == "Cycles"
    assert model.to_dict()["unit"] == "Cycles"


def test_free_text_never_fails_a_fit_and_is_kept_as_typed():
    for unit in ("operating hours", "landings", "kWh"):
        result = fitting.fit("weibull", LIFE, MAP, unit=f"  {unit} ")
        assert _live(result).unit == unit
        assert result["unit"] == unit


def test_no_unit_is_unknown_not_an_empty_label():
    for unit in (None, "", "   "):
        result = fitting.fit("weibull", LIFE, MAP, unit=unit)
        assert _live(result).unit is None
        assert result["unit"] == ""


def test_a_model_from_parameters_carries_the_unit():
    import surpyval as sp

    model = sp.Weibull.from_params([100.0, 2.0], unit=fitting.surpyval_unit("days"))
    assert model.unit == "Days"
    assert fitting.result_from_params("weibull", [{"name": "alpha", "value": 100.0},
                                                  {"name": "beta", "value": 2.0}], unit="days")["unit"] == "Days"


def test_stamp_unit_never_overwrites_and_never_blanks():
    import surpyval as sp

    model = sp.Weibull.from_params([100.0, 2.0], unit="Cycles")
    fitting.stamp_unit(model, "hours")
    assert model.unit == "Cycles"
    bare = sp.Weibull.from_params([100.0, 2.0])
    fitting.stamp_unit(bare, "")
    assert bare.unit is None
    fitting.stamp_unit(bare, "hrs")
    assert bare.unit == "Hours"


# ---------------------------------------------------------------------------
# Saved models: a round trip, and one saved before the unit went into SurPyval
# ---------------------------------------------------------------------------
def _save(client, csv=PUMPS, **form):
    res = client.post("/api/models", data={"name": "Pumps", "distribution": "weibull", "x": "months",
                                           "c": "censored", **form},
                      files={"file": ("data.csv", csv.encode(), "text/csv")})
    assert res.status_code == 200, res.text
    return res.json()


def _fresh_live(client, model_id):
    from backend.services import models as models_service

    models_service._LIVE.clear()
    fitting._MODEL_STORE.clear()
    return fitting._MODEL_STORE[models_service._live_cache_id(client.db, model_id, A)]["model"]


def test_a_saved_model_keeps_its_unit_through_save_and_reload(client):
    saved = _save(client, unit="days")
    doc = client.db["models"].find_one({"id": saved["id"]}) or client.db["models"].find_one({"_id": saved["id"]})
    assert doc["serialized"]["model"]["unit"] == "Days"
    assert _fresh_live(client, saved["id"]).unit == "Days"
    read = client.get(f"/api/models/{saved['id']}")
    assert read.status_code == 200 and read.json()["results"]["unit"] == "Days"


def test_a_model_saved_before_the_unit_loads_and_exports_with_its_saved_unit(client, tmp_path):
    saved = _save(client, unit="months")
    key = {"id": saved["id"]} if client.db["models"].find_one({"id": saved["id"]}) else {"_id": saved["id"]}
    client.db["models"].update_one(key, {"$unset": {"serialized.model.unit": ""}})
    before = client.db["models"].find_one(key)
    assert "unit" not in before["serialized"]["model"]
    live = _fresh_live(client, saved["id"])
    assert live.unit == "Months"  # from the saved unit, in memory
    after = client.db["models"].find_one(key)
    assert after["serialized"] == before["serialized"]  # nothing rewritten
    assert after["results"]["unit"] == "Months"
    script = client.get(f"/api/models/{saved['id']}/export.py").text
    assert "unit='Months'" in script
    printed = run(script, tmp_path)
    assert printed  # the script still runs and prints the page's numbers


def test_the_pump_sample_suggests_months_and_the_saved_model_is_in_months(client):
    from backend.services import datasets

    assert datasets._time_unit(["months", "censored"]) == "month"
    saved = _save(client, unit="month")
    assert _fresh_live(client, saved["id"]).unit == "Months"
    assert saved["results"]["unit"] == "Months"


# ---------------------------------------------------------------------------
# Download as Python
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("form, call", [
    ({}, "model = Weibull.fit(**fit_inputs, unit='Months')"),
    ({"distribution": "mixture"}, "model.fit(**fit_inputs, unit='Months')"),
    ({"distribution": "kaplan_meier"}, "model = KaplanMeier.fit(**fit_inputs, unit='Months')"),
], ids=["distribution", "mixture", "nonparametric"])
def test_download_as_python_passes_the_unit_into_the_fit(client, tmp_path, form, call):
    saved = _save(client, unit="months", **form)
    script = client.get(f"/api/models/{saved['id']}/export.py").text
    assert call in script
    run(script, tmp_path)


def test_download_as_python_of_a_model_from_parameters_passes_the_unit(client, tmp_path):
    res = client.post("/api/models/from-params", json={
        "name": "Seal", "distribution": "weibull", "unit": "hours",
        "params": [{"name": "alpha", "value": 1000.0}, {"name": "beta", "value": 2.0}]})
    assert res.status_code == 200, res.text
    script = client.get(f"/api/models/{res.json()['id']}/export.py").text
    assert "Weibull.from_params([1000.0, 2.0], unit='Hours')" in script
    run(script, tmp_path)


def test_no_unit_writes_no_unit_argument(client):
    saved = _save(client)
    script = client.get(f"/api/models/{saved['id']}/export.py").text
    assert "unit=" not in script.split("model = Weibull.fit(", 1)[1].split("\n", 1)[0]
    assert np.isfinite(saved["results"]["params"][0]["value"])


def test_a_dataset_whose_columns_name_no_unit_shows_the_unit_typed_for_its_fit(client):
    """Pasted values come in as "time" and "censored": the columns say no unit, so the Data list
    and the dataset's page showed none ("—") even after a fit in hours. The fit's unit is shown."""
    from backend.services.datasets import typed_time_unit

    csv = PUMPS.replace("months,censored", "time,censored")
    saved = _save(client, csv=csv, x="time", unit="hours")
    ds_id = saved["dataset_id"]
    assert client.get(f"/api/datasets/{ds_id}").json()["time_unit"] == "hour"
    listed = next(d for d in client.get("/api/datasets").json()["datasets"] if d["id"] == ds_id)
    assert listed["time_unit"] == "hour"
    # "No unit" stays none; a unit that isn't time keeps its own word.
    assert typed_time_unit("units") is None and typed_time_unit("") is None
    assert typed_time_unit("Operating hours") == "hour" and typed_time_unit("Starts") == "start"
