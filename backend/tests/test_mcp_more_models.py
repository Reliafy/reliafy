"""MCP: the models of #179 / #72 / #63 by id, with a Group by column for
shared frailty, checked against SurPyval called directly."""

import matplotlib

matplotlib.use("Agg")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
import surpyval as sp  # noqa: E402

from backend.services import datasets as datasets_service  # noqa: E402
from backend.tests.test_mcp import A, _call, _err, _ok, env  # noqa: E402,F401
from backend.tests.test_more_models import DF  # noqa: E402


def _dataset(env):
    return datasets_service.create_dataset(env.db, "sites", DF.to_csv(index=False).encode(), A).id


def test_frailty_by_group_column(env):
    ds = _dataset(env)
    args = {"dataset_id": ds, "distribution": "weibull_frailty", "time_column": "t", "censor_column": "c",
            "covariates": ["z"], "group_column": "site"}
    out = _ok(_call(env.token[A], "fit_distribution", args))
    direct = sp.WeibullFrailty.fit_from_df(DF, x_col="t", group_col="site", Z_cols=["z"], c_col="c")
    assert out["frailty"]["theta"] == pytest.approx(direct.theta, rel=1e-6)
    assert out["coefficients"][0]["value"] == pytest.approx(direct.beta[0], rel=1e-6)
    assert out["coef_table"][-1]["name"] == "theta"

    saved = _ok(_call(env.token[A], "fit_and_save_model", {**args, "name": "Sites"}))
    detail = _ok(_call(env.token[A], "get_model", {"model_id": saved["model_id"]}))
    assert detail["frailty"]["group_column"] == "site"
    rel = _ok(_call(env.token[A], "reliability_at", {"model_id": saved["model_id"], "times": [5.0],
                                                     "covariates": {"z": 1}}))
    expect = float(direct.sf(np.array([5.0]), np.array([[1.0]]))[0])
    assert rel["points"][0]["reliability"] == pytest.approx(expect, rel=1e-6)

    no_group = _err(_call(env.token[A], "fit_distribution", {**args, "group_column": None}))
    assert "Group by" in no_group
    missing = _err(_call(env.token[A], "fit_distribution", {**args, "group_column": "plant"}))
    assert "plant" in missing
    inline = _err(_call(env.token[A], "fit_distribution", {"data": [1, 2, 3], "group_column": "site"}))
    assert "group_column" in inline


@pytest.mark.parametrize("dist", ["additive_hazards", "proportional_odds", "buckley_james", "cox_frailty"])
def test_semi_parametric_ids(env, dist):
    ds = _dataset(env)
    args = {"dataset_id": ds, "distribution": dist, "time_column": "t", "censor_column": "c",
            "covariates": ["z", "temp"]}
    if dist == "cox_frailty":
        args["group_column"] = "site"
    out = _ok(_call(env.token[A], "fit_distribution", args))
    assert out["kind"] == "regression" and out["semi_parametric"] is True
    assert len(out["coefficients"]) == 2 and all(c["ci"] for c in out["coefficients"])


def test_bounded_discretized_and_flexible_ids(env):
    x = np.random.default_rng(1).beta(2, 5, 40).tolist()
    out = _ok(_call(env.token[A], "fit_distribution", {"data": x, "distribution": "beta"}))
    assert [p["value"] for p in out["params"]] == pytest.approx(list(sp.Beta.fit(x).params), rel=1e-6)

    k = np.maximum(np.ceil(np.random.default_rng(2).lognormal(2, 0.5, 60)), 1).tolist()
    out = _ok(_call(env.token[A], "fit_distribution", {"data": k, "distribution": "discretized_lognormal"}))
    assert [p["value"] for p in out["params"]] == pytest.approx(
        list(sp.Discretize(sp.LogNormal).fit(k).params), rel=1e-6)

    t, c = DF.t.tolist(), DF.c.tolist()
    saved = _ok(_call(env.token[A], "fit_and_save_model", {"data": t, "censored": c, "name": "RP",
                                                          "distribution": "royston_parmar"}))
    assert saved["kind"] == "flexible" and saved["spline"]["n_terms"] == 3
    rel = _ok(_call(env.token[A], "reliability_at", {"model_id": saved["model_id"], "times": [5.0]}))
    direct = sp.RoystonParmar.fit(x=np.asarray(t), c=np.asarray(c))
    assert rel["points"][0]["reliability"] == pytest.approx(float(direct.sf(np.array([5.0]))[0]), rel=1e-6)
    detail = _ok(_call(env.token[A], "get_model", {"model_id": saved["model_id"]}))
    assert detail["life"]["b_lives"]
