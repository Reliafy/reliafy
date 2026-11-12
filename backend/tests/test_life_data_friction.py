"""Friction fixes on the life-data pages (12 Nov walkthroughs): the Data
list's reading of a flag header and of a grouping column, plain words in a
regression's own checks, Rayleigh's failure pattern, a flag covariate's
calculator default, a prior fit's reliability bound and dataset names."""

import io

import mongomock
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend import fitting
from backend.regression_diagnostics import plain_check_text
from backend.services import datasets as ds


@pytest.fixture()
def client(monkeypatch):
    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    monkeypatch.setattr(db, "_db", mongomock.MongoClient()["reliafy_test"])
    monkeypatch.setattr(db, "_simulated", True)
    app.dependency_overrides[get_current_user] = lambda: {"uid": "friction-owner", "email": "o@x.org", "name": "o"}
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _idlers():
    """The walkthrough's idler sheet: one row per idler (ID-4400…), grouped by
    conveyor, a per-row Units column, "Failed (1=yes)" and a blank row."""
    rows = []
    for i in range(26):
        rows.append({"Idler No.": f"ID-{4400 + i}", "Conveyor": "CV-07" if i < 13 else "CV-12",
                     "Time in service": 1000 + 300 * i, "Units": "days" if i % 7 == 0 else "hrs",
                     "Failed (1=yes)": 1 if i % 26 < 10 else 0, "Comment": "seized" if i < 10 else None})
    rows.insert(5, {})
    return pd.DataFrame(rows)


def test_flag_header_says_what_one_means():
    assert ds.flag_header_meaning("Failed (1=yes)") == "failed"
    assert ds.flag_header_meaning("Running (1=yes)") == "running"
    assert ds.flag_header_meaning("Failed (1=no)") == "running"
    assert ds.flag_header_meaning("status (1 = failed)") == "failed"
    assert ds.one_means_failed("Failed (1=yes)") and ds.one_means_failed("status")
    assert not ds.one_means_failed("censored") and not ds.one_means_failed("Running (1=yes)")


def test_data_list_reads_the_idler_sheet_as_one_row_per_idler():
    out = ds.detect_tags(_idlers())
    # Not "2 conveyors · 16 failed" with time-varying covariates.
    assert out["summary"] == "26 idlers · 10 failed"
    assert "Time-varying covariates" not in out["tags"]
    assert "Non-repairable" in out["tags"]


def test_repeated_unit_histories_still_found():
    df = pd.DataFrame({"pump": ["P1", "P1", "P2", "P2"], "hours": [100, 250, 80, 300],
                       "failed": [1, 0, 1, 0]})
    assert ds._unit_column(df) == "pump"


def test_regression_checks_in_plain_words():
    assert plain_check_text("no evidence that its coefficient changes at t = 6.76e+03") == \
        "no evidence that its coefficient changes at age 6,760"
    assert "row 299 of the rows fitted" in plain_check_text(
        "no row moves the coefficient by more than 1 standard error (largest 0.504, row 298 of model.data)")
    assert plain_check_text("ICI at t = 3.5e+03 (25% of failures)") == \
        "At age 3,500 (when 25% of the failures had happened)"
    text = plain_check_text("E50 0.0193, E90 0.0565; predicted risk 0.024 to 0.478; outside the curve's 95% band "
                            "for 0% of units")
    assert text.startswith("predicted and observed chance of failing differ by 1.9% for a typical unit")
    assert "E50" not in text and "e+" not in text


def test_rayleigh_says_wear_out():
    assert fitting._randomness_verdict("rayleigh", [])["verdict"] == "wear_out"


def test_covariate_fields_carry_the_data_range():
    df = pd.DataFrame({"dusty": [0, 0, 1, 0, 1, 0, 0, 0], "load": [1.0, 2, 3, 4, 5, 6, 7, 8]})
    fields = {f["name"]: f for f in fitting._covariate_fields(df, ["dusty", "load"])}
    assert fields["dusty"]["flag"] is True and fields["dusty"]["default"] == 0.25
    assert fields["load"]["default"] == 4.5 and (fields["load"]["min"], fields["load"]["max"]) == (1.0, 8.0)
    assert "flag" not in fields["load"]


def test_negative_time_message_has_no_library_words():
    df = pd.DataFrame({"t": [-1.0, 5, 8, 12, 20, 30, 40], "c": [0, 0, 0, 0, 0, 1, 0]})
    with pytest.raises(fitting.FitError) as exc:
        fitting.fit("weibull", df, {"x": "t", "c": "c"})
    msg = str(exc.value)
    assert msg.startswith("Row 1 (time -1) is out of range for a Weibull")
    assert "SurPyval" not in msg and "support" not in msg


def test_excel_upload_saved_with_a_model_has_no_csv_in_its_name(client):
    csv = b"time,failed\n100,1\n200,1\n300,0\n400,1\n500,1\n"
    res = client.post("/api/models", data={"distribution": "weibull", "x": "time", "c": "failed", "c_invert": "true",
                                           "name": "Seal"},
                      files={"file": ("pump-seal-history - Seal history.csv", io.BytesIO(csv), "text/csv")})
    assert res.status_code == 200, res.text
    dataset = client.get(f"/api/datasets/{res.json()['dataset_id']}").json()
    assert dataset["name"] == "pump-seal-history - Seal history"
