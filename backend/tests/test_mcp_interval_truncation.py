"""Interval censoring, truncation and the fit method through the MCP fit tools (#182).

fitting.py has always taken the app's x / xl+xr / c / n / tl / tr mapping and a
``how``; these check the MCP tools reach the same fit, save the same spec as
the web app's /api/models, and explain the inputs when they're misused. The
helpers and ``env`` fixture come from test_mcp.
"""

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend.tests.test_mcp import A, TIMES, FLAGS, _call, _err, _ok, _run, env  # noqa: F401 - env is a fixture

# Six-monthly inspections: a unit found failed at an inspection failed some
# time after the previous one (flag 2); the rest failed in view or are running.
LOWER = [0, 4380, 4380, 8760, 2000, 5000, 8760, 13140, 3100, 9000]
UPPER = [4380, 8760, 8760, 13140, 2000, 5000, 13140, 13140, 3100, 9000]
IFLAGS = [2, 2, 2, 2, 0, 0, 2, 1, 0, 1]
# Units already in service when records began enter at these ages.
ENTRY = [0, 0, 500, 0, 300, 0, 0, 800, 0, 0]


def _direct(cols: dict, mapping: dict, **options):
    from backend import fitting

    return fitting.fit("weibull", pd.DataFrame(cols), mapping, options=options or None)


def _values(result):
    return [p["value"] for p in result["params"]]


def _csv(cols: dict) -> str:
    keys = list(cols)
    return "\n".join([",".join(keys), *(",".join("" if v is None else str(v) for v in row)
                                        for row in zip(*cols.values()))])


def test_inline_interval_censoring_matches_fitting(env):
    out = _ok(_call(env.token[A], "fit_distribution", {"data": LOWER, "data_right": UPPER, "censored": IFLAGS}))
    ref = _direct({"xl": LOWER, "xr": UPPER, "c": IFLAGS}, {"xl": "xl", "xr": "xr", "c": "c"})
    assert _values(out) == pytest.approx(_values(ref))
    # The censoring counts name the interval rows (#190's check, with flag 2).
    assert out["censoring"] == {"n_failed": 3, "n_right_censored": 2, "n_left_censored": 0,
                                "n_interval_censored": 5}
    # The interval rows count: the fit isn't the one that ignores the bounds.
    single = _direct({"x": UPPER, "c": [0 if f == 2 else f for f in IFLAGS]}, {"x": "x", "c": "c"})
    assert _values(out) != pytest.approx(_values(single))

    # Without flags, unequal bounds read as intervals and equal ones as failures.
    inferred = _ok(_call(env.token[A], "fit_distribution", {"data": [10, 20, 30, 40, 55], "data_right": [10, 25, 30, 48, 55]}))
    ref = _direct({"xl": [10, 20, 30, 40, 55], "xr": [10, 25, 30, 48, 55]}, {"xl": "xl", "xr": "xr"})
    assert _values(inferred) == pytest.approx(_values(ref))


def test_inline_truncation_scalar_or_per_row(env):
    a = env.token[A]
    scalar = _ok(_call(a, "fit_distribution", {"data": TIMES, "censored": FLAGS, "trunc_left": 100}))
    ref = _direct({"x": TIMES, "c": FLAGS, "tl": [100] * len(TIMES)}, {"x": "x", "c": "c", "tl": "tl"})
    assert _values(scalar) == pytest.approx(_values(ref))
    plain = _direct({"x": TIMES, "c": FLAGS}, {"x": "x", "c": "c"})
    assert _values(scalar) != pytest.approx(_values(plain))

    # Per row, with null for "not truncated"; right truncation alongside.
    entry = [None if e == 0 else e for e in ENTRY]
    per_row = _ok(_call(a, "fit_distribution", {
        "data": TIMES, "censored": FLAGS, "trunc_left": entry, "trunc_right": 5000}))
    ref = _direct({"x": TIMES, "c": FLAGS, "tl": ENTRY, "tr": [5000] * len(TIMES)},
                  {"x": "x", "c": "c", "tl": "tl", "tr": "tr"})
    assert _values(per_row) == pytest.approx(_values(ref))


def test_dataset_columns_match_the_app_and_save_the_same_spec(env):
    from backend.main import app

    a = env.token[A]
    cols = {"lo": LOWER, "hi": UPPER, "flag": IFLAGS, "entry": ENTRY}
    ds = _ok(_call(a, "upload_dataset", {"name": "Inspections", "csv": _csv(cols)}))
    args = {"dataset_id": ds["id"], "time_column": "lo", "time_right_column": "hi", "censor_column": "flag",
            "trunc_left_column": "entry"}
    out = _ok(_call(a, "fit_distribution", args))
    ref = _direct(cols, {"xl": "lo", "xr": "hi", "c": "flag", "tl": "entry"})
    assert _values(out) == pytest.approx(_values(ref))

    # (MSE takes intervals but not truncation, so this one drops the entry ages.)
    args.pop("trunc_left_column")
    saved = _ok(_call(a, "fit_and_save_model", {**args, "name": "Inspected", "method": "MSE"}))
    spec = env.db.models.find_one({"_id": saved["model_id"]})["spec"]
    # What the web app's own save posts for the same columns and method.
    from backend.auth import get_current_user

    app.dependency_overrides[get_current_user] = lambda: {"uid": A, "email": "a@example.org", "name": "A"}
    try:
        rest = TestClient(app).post("/api/models", data={
            "name": "Inspected (app)", "distribution": "weibull", "dataset_id": ds["id"],
            "xl": "lo", "xr": "hi", "c": "flag", "how": "MSE"})
    finally:
        app.dependency_overrides.clear()
    assert rest.status_code == 200, rest.text
    assert spec["mapping"] == rest.json()["spec"]["mapping"] == {"xl": "lo", "xr": "hi", "c": "flag"}
    assert spec["options"] == rest.json()["spec"]["options"] == {"how": "MSE"}
    assert _values(saved) == pytest.approx(_values(rest.json()["results"]))


def test_inline_save_writes_the_app_columns_and_reopens(env):
    from backend import fitting
    from backend.services import datasets as datasets_service
    from backend.services import models as models_service

    a = env.token[A]
    saved = _ok(_call(a, "fit_and_save_model", {
        "name": "Inline intervals", "data": LOWER, "data_right": UPPER, "censored": IFLAGS,
        "trunc_left": [None if e == 0 else e for e in ENTRY]}))
    model = models_service.get_model(env.db, saved["model_id"], A)
    assert model.spec["mapping"] == {"xl": "xl", "xr": "xr", "c": "c", "tl": "tl"}
    dataset = datasets_service.get_dataset(env.db, saved["dataset_id"], A)
    assert [c["name"] for c in dataset.columns] == ["xl", "xr", "c", "tl"]
    # Blank truncation cells round-trip as "not truncated": the refit that
    # reopening the model runs from its stored dataset and spec matches.
    live = fitting._MODEL_STORE[models_service._refit(model)]["model"]
    assert list(live.params) == pytest.approx(_values(saved))


def test_method_is_passed_and_checked(env):
    a = env.token[A]
    mps = _ok(_call(a, "fit_distribution", {"data": TIMES, "censored": FLAGS, "method": "MPS"}))
    assert mps["options"] == {"how": "MPS"}
    ref = _direct({"x": TIMES, "c": FLAGS}, {"x": "x", "c": "c"}, how="MPS")
    assert _values(mps) == pytest.approx(_values(ref))
    # MLE is the default, so it adds nothing to the spec.
    assert "options" not in _ok(_call(a, "fit_distribution", {"data": TIMES, "method": "MLE"}))

    msg = _err(_call(a, "fit_distribution", {"data": TIMES, "censored": FLAGS, "method": "MOM"}))
    assert "Method of moments doesn't support censored data" in msg and "MLE" in msg
    msg = _err(_call(a, "fit_distribution", {"data": TIMES, "trunc_left": 50, "method": "MSE"}))
    assert "doesn't support truncation" in msg
    msg = _err(_call(a, "fit_distribution", {"data": LOWER, "data_right": UPPER, "censored": IFLAGS,
                                             "method": "MPP"}))
    assert "interval-censored" in msg
    # The distribution's own method support comes from fitting.py too.
    msg = _err(_call(a, "fit_distribution", {"data": TIMES, "distribution": "kaplan_meier", "method": "MPS"}))
    assert "plain distributions only" in msg
    assert env.db.models.count_documents({}) == 0


def test_interval_flags_and_misplaced_inputs_explain_themselves(env):
    a = env.token[A]
    # Flag 2 with a single time per row: the error says how to give the bound
    # and where truncation goes.
    msg = _err(_call(a, "fit_distribution", {"data": TIMES, "censored": [2] + FLAGS[1:]}))
    assert "2 (interval-censored" in msg and "data_right" in msg and "time_right_column" in msg
    assert "trunc_left" in msg and "-1 (left-censored" in msg
    msg = _err(_call(a, "fit_distribution", {"data": LOWER, "data_right": UPPER, "censored": [0] * len(LOWER)}))
    assert "isn't 2" in msg and "x:" not in msg
    msg = _err(_call(a, "fit_distribution", {"data": TIMES, "data_right": TIMES, "censored": [2] + FLAGS[1:]}))
    assert "upper bound equals its lower bound" in msg

    msg = _err(_call(a, "fit_distribution", {"data": TIMES, "trunc_left_column": "entry"}))
    assert "trunc_left_column only applies with dataset_id" in msg
    msg = _err(_call(a, "fit_distribution", {"data": TIMES, "data_right": TIMES[:3]}))
    assert "`data_right` must have one entry per time" in msg
    msg = _err(_call(a, "fit_distribution", {"data": TIMES, "trunc_left": [1, 2]}))
    assert "`trunc_left` must have one entry per time" in msg

    ds = _ok(_call(a, "upload_dataset", {"name": "Seals", "csv": _csv(
        {"lo": LOWER, "hi": UPPER, "temp": list(range(len(LOWER)))})}))
    msg = _err(_call(a, "fit_distribution", {"dataset_id": ds["id"], "time_column": "lo", "trunc_left": 5}))
    assert "trunc_left only applies with inline data" in msg
    msg = _err(_call(a, "fit_distribution", {"dataset_id": ds["id"], "time_column": "lo",
                                             "time_right_column": "nope"}))
    assert "Column 'nope' isn't in the dataset" in msg
    # Parametric regression takes the intervals since #237; Cox's partial
    # likelihood can't, and says which models can.
    msg = _err(_call(a, "fit_distribution", {"dataset_id": ds["id"], "time_column": "lo", "time_right_column": "hi",
                                             "distribution": "cox_ph", "covariates": ["temp"]}))
    assert "Cox PH can't fit interval-censored" in msg and "Weibull PH" in msg


def test_schema_descriptions_and_instructions_name_the_new_inputs(env):
    from backend.mcp_server import INSTRUCTIONS

    tools = {t.name: t for t in _run(env.token[A], lambda c: c.list_tools()).tools}
    for name in ("fit_distribution", "fit_and_save_model"):
        schema = tools[name].input_schema
        for key in ("data_right", "trunc_left", "trunc_right", "time_right_column", "trunc_left_column",
                    "trunc_right_column", "method"):
            assert key in schema["properties"], (name, key)
        assert "2 = interval-censored" in str(schema) and "2 = interval-censored" in tools[name].description
        assert "trunc_left" in tools[name].description
    assert "2 = interval-censored" in INSTRUCTIONS and "trunc_left" in INSTRUCTIONS
