"""A column that gives each row's time unit ("hrs" on most rows, "days" on a
few) is read with the ``u_col`` option.

A sheet of 26 idler bearings logged mostly in hours, four rows in days by
another fitter, with a "Failed (1=yes)" flag. Read as hours throughout, the
four day rows became three failures at 89-262 "hours", the fit turned into
early-life failures (beta 0.62, B10 809 h) and nothing on the page said so.
Converted first, the fit matches SurPyval on the converted times (beta 1.24,
B10 2,963 h, at least 1,729 h at 90%), and a fit that leaves such a column
unread says so in its warnings (Diagnostics shows them).
"""

import io


import numpy as np
import pandas as pd
import pytest
import surpyval as sp

from backend import fitting, unit_column
from backend.fitting import FitError

_ROWS = [
    (11116, "hrs", 1), (11447, "hrs", 0), (7208, "hrs", 0), (133.4, "days", 0), (4892, "hrs", 1),
    (14765, "hrs", 0), (639, "hrs", 1), (9282, "hrs", 0), (3063, "hrs", 0), (261.7, "days", 1),
    (5626, "hrs", 0), (6442, "hrs", 1), (13048, "hrs", 1), (11666, "hrs", 0), (17402, "hrs", 0),
    (213.9, "days", 1), (15610, "hrs", 0), (4555, "hrs", 0), (6931, "hrs", 1), (11632, "hrs", 0),
    (2491, "hrs", 1), (89.4, "days", 1), (13169, "hrs", 0), (4007, "hrs", 0), (9590, "hrs", 0),
    (8492, "hrs", 0),
]
_CSV = "Time in service,Units,Failed (1=yes)\n" + "".join(f"{t},{u},{f}\n" for t, u, f in _ROWS)
_MAPPING = {"x": "Time in service", "c": "Failed (1=yes)"}


def _df():
    return pd.read_csv(io.StringIO(_CSV))


def _b10(result):
    return next(b for b in result["life"]["b_lives"] if b["label"] == "B10")


def _reference():
    hours = np.array([t * 24 if u == "days" else t for t, u, _ in _ROWS], dtype=float)
    c = np.array([1 - f for _, _, f in _ROWS])
    return sp.Weibull.fit(x=hours, c=c)


def test_detects_a_mixed_unit_column_with_its_counts():
    assert unit_column.detect(_df(), _MAPPING) == {"column": "Units", "counts": {"Hours": 22, "Days": 4}}
    # One unit throughout isn't mixed; a column in the mapping isn't a candidate.
    assert unit_column.detect(_df().assign(Units="hrs"), _MAPPING) is None
    assert unit_column.detect(_df(), {**_MAPPING, "g": "Units"}) is None


def test_converted_rows_give_surpyvals_fit_on_the_converted_times():
    r = fitting.fit("weibull", _df(), _MAPPING, unit="Hours", options={"c_invert": True, "u_col": "Units"})
    ref = _reference()
    params = {p["name"]: p["value"] for p in r["params"]}
    assert params["alpha"] == pytest.approx(ref.alpha, rel=1e-6)
    assert params["beta"] == pytest.approx(ref.beta, rel=1e-6)
    b10 = _b10(r)
    assert b10["value"] == pytest.approx(ref.qf(0.1), rel=1e-6)
    assert b10["value"] == pytest.approx(2963, abs=1)
    assert b10["lower"] == pytest.approx(1729, abs=1)
    assert r["split"]["failed"] == 10 and r["split"]["running"] == 16
    assert r["unit_conversion"] == {
        "column": "Units", "to": "Hours", "converted": 4, "counts": {"Hours": 22, "Days": 4},
        "note": r["unit_conversion"]["note"]}
    assert "4 rows were converted to hours" in r["unit_conversion"]["note"]
    assert r["unit_conversion"]["note"] in r["warnings"]
    # Stored with the fit options, so a saved model refits the same way.
    assert r["options"]["u_col"] == "Units"


def test_to_days_the_same_fit_scaled():
    hours = fitting.fit("weibull", _df(), _MAPPING, unit="Hours", options={"c_invert": True, "u_col": "Units"})
    days = fitting.fit("weibull", _df(), _MAPPING, unit="Days", options={"c_invert": True, "u_col": "Units"})
    assert _b10(days)["value"] == pytest.approx(_b10(hours)["value"] / 24, rel=1e-4)
    assert days["unit_conversion"]["converted"] == 22


def test_a_fit_that_ignores_the_column_warns_with_the_counts():
    r = fitting.fit("weibull", _df(), _MAPPING, unit="Hours", options={"c_invert": True})
    # The number the walkthrough found: early-life failures from day rows read as hours.
    assert _b10(r)["value"] == pytest.approx(809, abs=1)
    assert any("22 in hours and 4 in days" in w and "read as hours" in w for w in r["warnings"])


def test_refusals_in_plain_words():
    with pytest.raises(FitError, match="pick Minutes, Hours"):
        fitting.fit("weibull", _df(), _MAPPING, unit="Cycles", options={"u_col": "Units"})
    bad = _df()
    bad.loc[0, "Units"] = "shifts"
    with pytest.raises(FitError, match="“shifts”"):
        fitting.fit("weibull", bad, _MAPPING, unit="Hours", options={"u_col": "Units"})
    blank = _df()
    blank.loc[0, "Units"] = None
    with pytest.raises(FitError, match="1 row has a time but no unit"):
        fitting.fit("weibull", blank, _MAPPING, unit="Hours", options={"u_col": "Units"})


def test_the_form_field():
    assert fitting.options_from_form(u_col=" Units ") == {"offset": False, "zi": False, "lfp": False, "u_col": "Units"}


# ---- API round trip ---------------------------------------------------------

OWNER = "user-a"


@pytest.fixture()
def client(monkeypatch):
    import mongomock
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


def _upload():
    return {"file": ("idlers.csv", io.BytesIO(_CSV.encode()), "text/csv")}


def test_u_col_travels_through_fit_save_and_refit(client):
    form = {**_MAPPING, "c_invert": "1", "u_col": "Units", "unit": "Hours"}
    fit = client.post("/api/fit/weibull", data=form, files=_upload())
    assert fit.status_code == 200, fit.text
    assert fit.json()["unit_conversion"]["converted"] == 4

    saved = client.post("/api/models", data={"name": "Idlers", "distribution": "weibull", **form}, files=_upload())
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["spec"]["options"]["u_col"] == "Units"
    assert body["results"]["params"] == fit.json()["params"]

    refit = client.put(f"/api/models/{body['id']}/fit", json={
        "distribution": "weibull", "mapping": _MAPPING, "c_invert": True, "u_col": "Units", "unit": "Hours"})
    assert refit.status_code == 200, refit.text
    assert refit.json()["results"]["params"] == body["results"]["params"]
