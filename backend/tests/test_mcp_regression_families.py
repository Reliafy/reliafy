"""MCP: Best fit's score, the shared frailty's family and the model checks."""

import matplotlib

matplotlib.use("Agg")

import pytest  # noqa: E402

from backend.services import datasets as datasets_service  # noqa: E402
from backend.tests.test_mcp import A, _call, _err, _ok, env  # noqa: E402,F401
from backend.tests.test_regression_families import DF, SITES  # noqa: E402

pytestmark = pytest.mark.usefixtures("mcp_on")


def _ds(env, df):
    return datasets_service.create_dataset(env.db, "d", df.to_csv(index=False).encode(), A).id


def test_best_fit_criterion(env):
    out = _ok(_call(env.token[A], "life_data_analysis", {
        "action": "fit", "distribution": "best", "data": [float(x) for x in range(5, 80, 3)], "criterion": "bic"}))
    sel = out["selection"]
    assert sel["criterion"] == "bic" and sel["candidates"][0]["delta"] == 0 and sel["guidance"] is not None
    err = _err(_call(env.token[A], "life_data_analysis", {
        "action": "fit", "distribution": "weibull", "data": [1.0, 2, 3, 4, 5, 9], "criterion": "bic"}))
    assert "best" in err


def test_frailty_family_and_model_checks(env):
    args = {"dataset_id": _ds(env, SITES), "distribution": "weibull_frailty", "time_column": "t",
            "censor_column": "c", "covariates": ["z"], "group_column": "site", "frailty_family": "lognormal"}
    out = _ok(_call(env.token[A], "life_data_analysis", {"action": "fit", **args}))
    assert out["frailty"]["family"] == "lognormal"
    assert out["diagnostics"]["model_checks"]["available"]
    bad = _err(_call(env.token[A], "life_data_analysis", {"action": "fit", **args, "distribution": "weibull_ph",
                                                          "group_column": None}))
    assert "frailty" in bad


def test_loglogistic_aft_by_id(env):
    out = _ok(_call(env.token[A], "life_data_analysis", {
        "action": "fit", "dataset_id": _ds(env, DF), "distribution": "loglogistic_aft", "time_column": "t",
        "censor_column": "c", "covariates": ["temp", "load"]}))
    assert out["distribution_id"] == "loglogistic_aft" and out["diagnostics"]["model_checks"]["rows"]
