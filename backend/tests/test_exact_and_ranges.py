"""Exact values on some rows, only a range on others.

A sheet can map ``x`` beside an ``xl``/``xr`` range: a row with ``x`` filled
is that exact value, a row with ``x`` blank is read from its range (as
inspection data is). Every fit must give SurPyval's own answer for the same
rows, coded the SurPyval way (exact rows 0 or 1 at one value, range rows 2
between two values).
"""

import io

import numpy as np
import pandas as pd
import pytest

from backend import fitting
from backend.fitting import FitError
from backend.services import model_split

# 12 exact failures, 4 still running, 10 failures only known to lie in a range.
_EXACT = [310, 420, 515, 600, 655, 720, 790, 860, 905, 990, 1080, 1200]
_RUNNING = [1300, 1300, 1400, 1500]
_RANGES = [(200, 400), (400, 600), (400, 600), (600, 800), (600, 800), (600, 800),
           (800, 1000), (800, 1000), (1000, 1200), (1000, 1200)]


def _sheet(status=True):
    rows = [f"{v},,,Failed" for v in _EXACT] + [f"{v},,,Running" for v in _RUNNING]
    rows += [f",{lo},{hi},Failed" for lo, hi in _RANGES]
    if not status:
        rows = [r.rsplit(",", 1)[0] for r in rows if not r.endswith("Running")]
    head = "Cycles,Last good,Found failed" + (",Status" if status else "")
    return pd.read_csv(io.StringIO(head + "\n" + "\n".join(rows) + "\n"))


_MAP = {"x": "Cycles", "xl": "Last good", "xr": "Found failed", "c": "Status"}
_C_MAP = {"c_map": {"Failed": 0, "Running": 1}}


def _reference(running=True):
    """SurPyval fitted directly: x as [lower, upper] per row with its flag."""
    import surpyval

    exact = _EXACT + (_RUNNING if running else [])
    xl = np.array(exact + [lo for lo, _ in _RANGES], dtype=float)
    xr = np.array(exact + [hi for _, hi in _RANGES], dtype=float)
    c = np.array([0] * len(_EXACT) + ([1] * len(_RUNNING) if running else []) + [2] * len(_RANGES))
    return surpyval.Weibull.fit(xl=xl, xr=xr, c=c)


def _params(result):
    return [p["value"] for p in result["params"]]


def test_exact_rows_and_range_rows_fit_as_surpyval_does():
    r = fitting.fit("weibull", _sheet(), _MAP, options=dict(_C_MAP))
    ref = _reference()
    assert _params(r) == pytest.approx(list(ref.params), rel=1e-6)
    assert r["split"] == {"failed": 22, "running": 4, "other": 0}
    assert r["interval_censored"] is True


def test_without_a_status_column_every_row_is_a_failure():
    df = _sheet(status=False)
    r = fitting.fit("weibull", df, {k: v for k, v in _MAP.items() if k != "c"})
    assert _params(r) == pytest.approx(list(_reference(running=False).params), rel=1e-6)


def _with_three_both_filled():
    """The sheet plus 3 rows that give x and a range both: they say two things."""
    extra = pd.DataFrame({"Cycles": [500.0, 700.0, 50.0], "Last good": [400.0, 600.0, 900.0],
                          "Found failed": [600.0, 800.0, 1100.0], "Status": ["Failed", "Failed", "Running"]})
    df = _sheet()
    return pd.concat([df.iloc[:5], extra, df.iloc[5:]], ignore_index=True)


def test_rows_with_x_and_a_range_both_filled_are_left_out_with_a_warning():
    df = _with_three_both_filled()
    r = fitting.fit("weibull", df, _MAP, options=dict(_C_MAP))
    # The fit equals SurPyval on the other rows, whatever those three say.
    assert _params(r) == pytest.approx(list(_reference().params), rel=1e-6)
    assert r["split"] == {"failed": 22, "running": 4, "other": 0}
    warning = ("3 rows have x ('Cycles') and a range ('Last good' to 'Found failed') both filled, "
               "so they are left out of the fit: rows 6, 7 and 8.")
    assert warning in r["warnings"]
    assert r["x_and_range_rows"]["count"] == 3
    assert r["x_and_range_rows"]["rows"] == [6, 7, 8]
    reading = fitting.data_reading(fitting.map_censor_column(df, "Status", _C_MAP["c_map"]), _MAP)
    assert reading["total"] == 26
    assert reading["x_and_range_rows"]["warning"] == warning


def test_x_with_only_one_range_cell_is_an_exact_value():
    df = _sheet()
    df.loc[0, "Last good"] = 1
    r = fitting.fit("weibull", df, _MAP, options=dict(_C_MAP))
    assert _params(r) == pytest.approx(list(_reference().params), rel=1e-6)
    assert not any("both filled" in w for w in r.get("warnings") or [])


def test_every_row_with_both_filled_is_refused():
    df = pd.DataFrame({"x": [1.0, 2.0], "l": [0.5, 1.5], "r": [1.5, 2.5]})
    with pytest.raises(FitError, match="Every row has x"):
        fitting.fit("weibull", df, {"x": "x", "xl": "l", "xr": "r"})


def test_a_row_with_no_value_at_all_is_refused_naming_the_three_columns():
    df = _sheet()
    df.loc[3, "Cycles"] = np.nan
    with pytest.raises(FitError, match=r"Row 4 has no value in 'Cycles', 'Last good' or 'Found failed'"):
        fitting.fit("weibull", df, _MAP, options=dict(_C_MAP))


def test_the_reading_and_split_count_each_kind_of_row():
    df = fitting.map_censor_column(_sheet(), "Status", _C_MAP["c_map"])
    assert fitting.data_reading(df, _MAP) == {"failed": 12, "running": 4, "left": 0, "interval": 10, "total": 26}
    assert model_split.data_split(df, _MAP) == {"failed": 22, "running": 4, "other": 0}


def test_only_x_and_only_a_range_still_fit_as_before():
    df = _sheet()
    only_x = fitting.fit("weibull", df.dropna(subset=["Cycles"]), {"x": "Cycles", "c": "Status"},
                         options=dict(_C_MAP))
    assert only_x.get("interval_censored") is None
    ranges = df[df["Cycles"].isna()]
    only_range = fitting.fit("weibull", ranges, {"xl": "Last good", "xr": "Found failed"})
    assert only_range["interval_censored"] is True


def test_a_regression_reads_the_rows_the_same_way():
    df = _sheet()
    df["temp"] = np.linspace(20, 60, len(df))
    r = fitting.fit("weibull_ph", df, _MAP, covariates=["temp"], options=dict(_C_MAP))
    coded = fitting.map_censor_column(df.copy(), "Status", _C_MAP["c_map"])
    exact = coded["Cycles"].notna()
    coded["lo"] = np.where(exact, coded["Cycles"], coded["Last good"])
    coded["hi"] = np.where(exact, coded["Cycles"], coded["Found failed"])
    coded["code"] = np.where(exact, coded["Status"], 2)
    ref = fitting.fit("weibull_ph", coded, {"xl": "lo", "xr": "hi", "c": "code"}, covariates=["temp"])
    assert _params(r) == pytest.approx(_params(ref), rel=1e-6)


@pytest.fixture()
def client(monkeypatch):
    import mongomock
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    monkeypatch.setattr(db, "_db", mongomock.MongoClient()["reliafy_test"])
    monkeypatch.setattr(db, "_simulated", True)
    app.dependency_overrides[get_current_user] = lambda: {"uid": "user-a", "email": "a@example.com", "name": "A"}
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_the_step_the_result_and_the_saved_model_all_carry_the_warning(client):
    csv = _with_three_both_filled().to_csv(index=False).encode()
    form = {"x": "Cycles", "xl": "Last good", "xr": "Found failed", "c": "Status",
            "c_map": '{"Failed": 0, "Running": 1}', "unit": "Cycles"}
    warning = ("3 rows have x ('Cycles') and a range ('Last good' to 'Found failed') both filled, "
               "so they are left out of the fit: rows 6, 7 and 8.")
    # The Data step's reading.
    r = client.post("/api/data-reading", files={"file": ("v.csv", csv, "text/csv")},
                    data={k: form[k] for k in ("x", "xl", "xr", "c", "c_map")})
    assert r.status_code == 200, r.text
    assert r.json()["x_and_range_rows"] == {"count": 3, "rows": [6, 7, 8], "warning": warning}
    assert r.json()["total"] == 26
    # The fit.
    fresh = client.post("/api/fit/weibull", data=form, files={"file": ("v.csv", csv, "text/csv")})
    assert fresh.status_code == 200, fresh.text
    assert warning in fresh.json()["warnings"]
    assert [p["value"] for p in fresh.json()["params"]] == pytest.approx(list(_reference().params), rel=1e-6)
    # The saved model, and the model page's read of it.
    saved = client.post("/api/models", data={**form, "name": "Valves", "distribution": "weibull"},
                        files={"file": ("v.csv", csv, "text/csv")})
    assert saved.status_code == 200, saved.text
    model = client.get(f"/api/models/{saved.json()['id']}").json()
    assert warning in model["results"]["warnings"]
    assert model["spec"]["mapping"] == {"x": "Cycles", "xl": "Last good", "xr": "Found failed", "c": "Status"}
