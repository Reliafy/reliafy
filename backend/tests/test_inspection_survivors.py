"""Inspection (interval) data that also holds units still running.

Field inspection records give two times for a unit found failed (the last
inspection it passed and the one that found it failed) and one for a unit
that never failed. Three ways a spreadsheet writes the survivors must all
fit to the same answer as rows coded 2 (interval) / 1 (still running):

- a blank latest time;
- the same time twice beside a Failed / Still running column;
- the same time twice beside a 2 / 1 code column.
"""

import io

import numpy as np
import pandas as pd
import pytest

from backend import fitting
from backend.fitting import FitError
from backend.services import model_split

# 40 valves inspected every 200 hours to 1,000: 25 found failed, 15 still fine.
_WINDOWS = ([(0, 200)] * 2 + [(200, 400)] * 6 + [(400, 600)] * 7 + [(600, 800)] * 6 + [(800, 1000)] * 4)
_N_RUNNING = 15
_MAP = {"xl": "last_ok", "xr": "found_failed"}


def _blank():
    rows = [f"{lo},{hi}" for lo, hi in _WINDOWS] + ["1000,"] * _N_RUNNING
    return pd.read_csv(io.StringIO("last_ok,found_failed\n" + "\n".join(rows) + "\n"))


def _status():
    rows = [f"{lo},{hi},F" for lo, hi in _WINDOWS] + ["1000,1000,S"] * _N_RUNNING
    return pd.read_csv(io.StringIO("last_ok,found_failed,status\n" + "\n".join(rows) + "\n"))


def _coded():
    rows = [f"{lo},{hi},2" for lo, hi in _WINDOWS] + ["1000,1000,1"] * _N_RUNNING
    return pd.read_csv(io.StringIO("last_ok,found_failed,censor_code\n" + "\n".join(rows) + "\n"))


def _params(result):
    return {p["name"]: p["value"] for p in result["params"]}


def _b10(result):
    p = _params(result)
    return p["alpha"] * (-np.log(0.9)) ** (1 / p["beta"])


@pytest.fixture(scope="module")
def reference():
    """The answer from rows coded the SurPyval way, as the API sends them."""
    import surpyval

    lo = np.array([w[0] for w in _WINDOWS] + [1000] * _N_RUNNING, dtype=float)
    hi = np.array([w[1] for w in _WINDOWS] + [1000] * _N_RUNNING, dtype=float)
    c = np.array([2] * len(_WINDOWS) + [1] * _N_RUNNING)
    model = surpyval.Weibull.fit(xl=lo, xr=hi, c=c)
    return {"alpha": float(model.params[0]), "beta": float(model.params[1]), "b10": float(model.qf(0.1))}


def test_a_blank_latest_time_is_a_unit_still_running(reference):
    r = fitting.fit("weibull", _blank(), _MAP)
    assert _params(r) == pytest.approx({"alpha": reference["alpha"], "beta": reference["beta"]}, rel=1e-6)
    assert _b10(r) == pytest.approx(reference["b10"], rel=1e-6)
    assert r["split"] == {"failed": 25, "running": 15, "other": 0}


def test_failed_between_two_times_is_an_interval_and_running_is_censored(reference):
    r = fitting.fit("weibull", _status(), {**_MAP, "c": "status"}, options={"c_map": {"F": 0, "S": 1}})
    assert _b10(r) == pytest.approx(reference["b10"], rel=1e-6)
    assert r["split"] == {"failed": 25, "running": 15, "other": 0}


def test_a_code_column_fits_the_same(reference):
    r = fitting.fit("weibull", _coded(), {**_MAP, "c": "censor_code"})
    assert _b10(r) == pytest.approx(reference["b10"], rel=1e-6)


def test_survivors_are_not_read_as_failures(reference):
    # The wrong reading: every survivor an exact failure at 1,000 hours.
    wrong = fitting.fit("weibull", _coded(), _MAP)
    assert _b10(wrong) > reference["b10"] * 1.2
    # ... which the reading says before the fit, rather than passing in silence.
    notes = fitting.reading_notes(_coded(), _MAP)
    assert len(notes) == 1 and notes[0].startswith("15 rows have the same earliest and latest time")
    assert fitting.reading_notes(_coded(), {**_MAP, "c": "censor_code"}) == []
    assert fitting.reading_notes(_blank(), _MAP) == []


def test_a_regression_reads_the_rows_the_same_way():
    df = _blank().assign(temp=[40 + (i % 5) * 10 for i in range(40)])
    coded = _coded().assign(temp=df["temp"])
    r = fitting.fit("weibull_ph", df, _MAP, covariates=["temp"])
    ref = fitting.fit("weibull_ph", coded, {**_MAP, "c": "censor_code"}, covariates=["temp"])
    assert [p["value"] for p in r["params"]] == pytest.approx([p["value"] for p in ref["params"]], rel=1e-5)


def test_the_reading_counts_each_kind_of_row():
    want = {"failed": 0, "running": 15, "left": 2, "interval": 23, "total": 40}
    assert fitting.data_reading(_blank(), _MAP) == want
    assert fitting.data_reading(_coded(), {**_MAP, "c": "censor_code"}) == want
    mapped = fitting.map_censor_column(_status(), "status", {"F": 0, "S": 1})
    assert fitting.data_reading(mapped, {**_MAP, "c": "status"}) == want
    # Plain times with a flag, weighted by a count column.
    df = pd.DataFrame({"t": [10, 20, 30], "c": [0, 1, 0], "n": [5, 100, 3]})
    assert fitting.data_reading(df, {"x": "t", "c": "c", "n": "n"}) == {
        "failed": 8, "running": 100, "left": 0, "interval": 0, "total": 108}


def test_a_blank_earliest_time_was_found_failed_at_the_first_look():
    read = fitting.read_interval_rows([np.nan, 200.0, 400.0], [200.0, 400.0, np.nan])
    assert read["c"].tolist() == [-1, 2, 1]
    assert read["xl"].tolist() == [200.0, 200.0, 400.0]
    assert read["xr"].tolist() == [200.0, 400.0, 400.0]


def test_rows_coded_already_pass_through_untouched():
    read = fitting.read_interval_rows([400.0, 1000.0, 300.0], [600.0, 1000.0, 300.0], [2, 1, 0])
    assert read["c"].tolist() == [2, 1, 0]
    # No blanks and no status column: nothing is added.
    assert "c" not in fitting.read_interval_rows([400.0, 500.0], [600.0, 500.0])


@pytest.mark.parametrize("xl, xr, c, says", [
    ([np.nan, 1.0], [np.nan, 2.0], None, "Row 1 has no time in 'last_ok' or 'found_failed'"),
    ([5.0, 1.0], [2.0, 2.0], None, "In row 1 the earliest time ('last_ok') is after the latest"),
    ([1.0, 1.0], [2.0, 2.0], [1, 2], "Row 1 is marked still running but has two different times"),
    ([1.0, 1.0], [np.nan, 2.0], [2, 2], "Row 1 is marked as an interval but has only one time"),
])
def test_rows_that_cannot_be_read_are_refused_in_plain_words(xl, xr, c, says):
    with pytest.raises(FitError) as err:
        fitting.read_interval_rows(xl, xr, c, "last_ok", "found_failed", "status")
    assert says in str(err.value)
    assert "nan" not in str(err.value).lower()


def test_a_library_message_keeps_its_words_and_drops_its_arrays():
    exc = ValueError("Censor flag indicates not interval censored but has interval window.\nx:\n[[400. 600.]\n [1. 2.]]")
    msg = fitting._fit_failure_hint(exc, {"xl": np.array([1.0, 2.0, 3.0])}, "Weibull")
    assert msg == "Censor flag indicates not interval censored but has interval window."


def test_a_saved_models_split_counts_inspection_failures():
    kwargs = fitting.build_fit_inputs(_blank(), _MAP)
    assert model_split.split_of_inputs(kwargs) == {"failed": 25, "running": 15, "other": 0}


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


def test_the_reading_endpoint(client):
    csv = _coded().to_csv(index=False).encode()
    r = client.post("/api/data-reading", files={"file": ("valves.csv", csv, "text/csv")},
                    data={"xl": "last_ok", "xr": "found_failed", "c": "censor_code"})
    assert r.status_code == 200, r.text
    assert r.json() == {"failed": 0, "running": 15, "left": 2, "interval": 23, "total": 40, "notes": []}
    r = client.post("/api/data-reading", files={"file": ("valves.csv", csv, "text/csv")},
                    data={"xl": "last_ok", "xr": "found_failed"})
    assert r.json()["failed"] == 15 and len(r.json()["notes"]) == 1
    words = _status().to_csv(index=False).encode()
    r = client.post("/api/data-reading", files={"file": ("valves.csv", words, "text/csv")},
                    data={"xl": "last_ok", "xr": "found_failed", "c": "status", "c_map": '{"F": 0, "S": 1}'})
    assert (r.json()["running"], r.json()["interval"], r.json()["left"]) == (15, 23, 2)
    assert client.post("/api/data-reading", data={"x": "t"}).status_code == 422


def test_callers_that_send_codes_keep_the_strict_reading():
    """The API and MCP tools send censor codes: a 0 beside two different
    times is refused there (flag it 2), as before."""
    coded = _coded().assign(censor_code=0)
    with pytest.raises(FitError, match="not interval censored"):
        fitting.fit("weibull", coded.head(25), {**_MAP, "c": "censor_code"}, options={"strict_intervals": True})
    r = fitting.fit("weibull", _coded(), {**_MAP, "c": "censor_code"}, options={"strict_intervals": True})
    assert "strict_intervals" not in (r.get("options") or {})
