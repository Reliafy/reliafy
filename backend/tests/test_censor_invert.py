"""A 1 = failed censor column can be flipped with the ``c_invert`` option.

Weibull++ and most spreadsheets mark failures with a 1 — the inverse of the
survival convention SurPyval uses. A consultant uploaded four such files and
was refused every time (test_censoring_guard.py covers the refusal); until now
the only fix was editing the CSV. The option inverts 0/1 on the server, before
the all-censored guard, and is stored with the fit options so a saved model
re-fits the same way round.
"""

import io

import mongomock
import numpy as np
import pandas as pd
import pytest

from backend import fitting
from backend.fitting import (
    CENSOR_CONVENTION,
    FitError,
    failure_count,
    invert_censor_column,
    options_from_form,
)

OWNER = "user-a"

# The consultant's file: 1 = failed for seven units, one still running.
_CSV = "Time,Censored\n100,1\n234,1\n500,1\n890,1\n900,1\n1230,1\n2345,1\n3546,0\n"
_MAPPING = {"x": "Time", "c": "Censored"}


def _df(csv=_CSV):
    return pd.read_csv(io.StringIO(csv))


# ---- (a) inverted, the file fits and has seven failures --------------------

def test_inverting_fits_the_file_with_seven_failures():
    flipped = invert_censor_column(_df(), "Censored")
    kwargs = fitting.build_fit_inputs(flipped, _MAPPING)
    assert failure_count(kwargs) == (7, 8)

    r = fitting.fit("weibull", _df(), _MAPPING, options={"c_invert": True})
    alpha = next(p["value"] for p in r["params"] if p["name"] == "alpha")
    # Same answer as hand-inverting the column (test_censoring_guard.py).
    assert alpha == pytest.approx(1372.92, rel=1e-3)
    # Persisted with the other fit options so a saved spec reproduces it.
    assert r["options"] == {"c_invert": True}


def test_inversion_does_not_touch_the_caller_or_other_codes():
    df = pd.DataFrame({"t": [1, 2, 3, 4], "c": [0, 1, -1, 2]})
    out = invert_censor_column(df, "c")
    assert out["c"].tolist() == [1, 0, -1, 2]
    assert df["c"].tolist() == [0, 1, -1, 2]  # input left alone


@pytest.mark.parametrize("bad", ["3", "", "yes", "0.5"])
def test_inversion_refuses_values_outside_the_censor_codes(bad):
    df = _df(_CSV.replace("3546,0", f"3546,{bad}"))
    with pytest.raises(FitError, match="can only be inverted"):
        fitting.fit("weibull", df, _MAPPING, options={"c_invert": True})


def test_inversion_is_ignored_without_a_censor_column():
    r = fitting.fit("weibull", _df(), {"x": "Time"}, options={"c_invert": True})
    assert "c_invert" not in (r.get("options") or {})


def test_inversion_applies_to_every_model_kind():
    """Regression, non-parametric and mixture paths read the same column."""
    df = _df()
    df["temp"] = np.linspace(20, 60, len(df))
    r = fitting.fit("weibull_ph", df, _MAPPING, covariates=["temp"],
                    options={"c_invert": True})
    assert r["options"] == {"c_invert": True}
    km = fitting.fit("kaplan_meier", df, _MAPPING, options={"c_invert": True})
    assert km["options"] == {"c_invert": True}


def test_options_from_form_reads_the_flag():
    assert options_from_form(c_invert="1")["c_invert"] is True
    assert options_from_form(c_invert="0") is None
    assert options_from_form(c_invert=None) is None
    both = options_from_form(offset="true", c_invert="true")
    assert both["offset"] is True and both["c_invert"] is True


# ---- (b) without it, the guard still refuses and names the checkbox --------

def test_without_the_option_the_guard_refuses_and_points_at_the_checkbox():
    with pytest.raises(FitError) as e:
        fitting.fit("weibull", _df(), _MAPPING)
    msg = str(e.value)
    assert "Only 1 of the 8 rows" in msg
    assert CENSOR_CONVENTION in msg
    assert "1 = failed" in msg

    all_ones = _df(); all_ones["Censored"] = 1
    with pytest.raises(FitError, match="nothing for Weibull to fit"):
        fitting.fit("weibull", all_ones, _MAPPING)
    # ...and inverted, the all-censored file is all failures and fits.
    r = fitting.fit("weibull", all_ones, _MAPPING, options={"c_invert": True})
    assert r["params"]


# ---- (c) a saved model with c_invert in its spec re-fits identically -------

@pytest.fixture()
def session(monkeypatch):
    from backend import db

    test_db = mongomock.MongoClient()["reliafy_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    yield test_db


def test_saved_model_keeps_the_inversion_and_refits_identically(session):
    from backend.services import datasets as ds
    from backend.services import models as ms

    d = ds.create_dataset(session, "consultant.csv", _CSV.encode(), OWNER)
    model = ms.save_model(
        session, "Pump seals", d, "weibull", _MAPPING, [], None,
        owner_id=OWNER, options={"c_invert": True},
    )
    assert model.spec["options"] == {"c_invert": True}
    assert model.spec["mapping"] == _MAPPING  # the flag isn't a column

    # Refit-on-demand goes through the stored spec alone.
    cache_id = ms._refit(model)
    live = fitting._MODEL_STORE[cache_id]["model"]
    assert list(live.params) == pytest.approx(
        [p["value"] for p in model.results["params"]])

    # An in-place edit that keeps the flag gives the same fit back...
    edited = ms.update_fit(
        session, model.id, OWNER, "weibull", _MAPPING, [], None, None,
        {"c_invert": True},
    )
    assert edited.spec["options"] == {"c_invert": True}
    assert [p["value"] for p in edited.results["params"]] == pytest.approx(
        [p["value"] for p in model.results["params"]])

    # ...and dropping it is refused by the guard, leaving the model untouched.
    with pytest.raises(FitError, match="1 = failed"):
        ms.update_fit(session, model.id, OWNER, "weibull", _MAPPING, [], None, None, None)
    assert ms.get_model(session, model.id, OWNER).spec["options"] == {"c_invert": True}


# ---- API round trip ---------------------------------------------------------

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
    app.dependency_overrides[get_current_user] = lambda: {
        "uid": OWNER, "email": "a@example.com", "name": "A"}
    tc = TestClient(app)
    try:
        yield tc
    finally:
        app.dependency_overrides.clear()


def test_c_invert_travels_through_fit_save_and_refit(client):
    form = {"x": "Time", "c": "Censored"}

    refused = client.post(
        "/api/fit/weibull", data={**form, "c_invert": "0"},
        files={"file": ("c.csv", io.BytesIO(_CSV.encode()), "text/csv")},
    )
    assert refused.status_code == 422
    assert "1 = failed" in refused.json()["detail"]

    fit = client.post(
        "/api/fit/weibull", data={**form, "c_invert": "1"},
        files={"file": ("c.csv", io.BytesIO(_CSV.encode()), "text/csv")},
    )
    assert fit.status_code == 200, fit.text
    assert fit.json()["options"] == {"c_invert": True}

    saved = client.post(
        "/api/models",
        data={"name": "Seals", "distribution": "weibull", **form, "c_invert": "1"},
        files={"file": ("c.csv", io.BytesIO(_CSV.encode()), "text/csv")},
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["spec"]["options"] == {"c_invert": True}
    assert body["spec"]["mapping"] == form

    refit = client.put(
        f"/api/models/{body['id']}/fit",
        json={"distribution": "weibull", "mapping": form, "c_invert": True},
    )
    assert refit.status_code == 200, refit.text
    assert refit.json()["spec"]["options"] == {"c_invert": True}
    assert refit.json()["results"]["params"] == body["results"]["params"]
