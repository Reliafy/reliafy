"""Say plainly when a fit has no finite maximum (#230).

Some data leave the likelihood rising as a parameter runs off to infinity;
the estimates then mean nothing. SurPyval 0.23 recognises it for accelerated
life and regression fits (#628), offset fits (#616, #622, #599) and
univariate runaways (#584), setting ``model.maximum``. Reliafy names the
parameter, passes on the way out, keeps such a fit out of Best fit's ranking,
and tells MCP callers not to quote the numbers.
"""

import matplotlib

matplotlib.use("Agg")

import mongomock  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402
import surpyval as sp  # noqa: E402

from backend import alt, fitting  # noqa: E402
from backend.mcp_server import _fit_summary  # noqa: E402


def _alt_test(draw):
    """SurPyval #583's two-stress test (Arrhenius in temperature, power in
    voltage, 12 units a cell, ended at 3000 h); draw 54 puts all six failures
    in the 125 C / 500 V cell (SurPyval's #628 test)."""
    T, V = np.meshgrid(np.array([85.0, 105.0, 125.0]) + 273.15, [450.0, 500.0], indexing="ij")
    Z = np.repeat(np.column_stack([T.ravel(), V.ravel()]), 12, axis=0)
    rng = np.random.default_rng([617, 600, draw])
    life = 600.0 * np.exp(0.7 / 8.617e-5 / Z[:, 0]) * Z[:, 1] ** -3.0
    t = life * rng.weibull(2.2, len(Z))
    return pd.DataFrame({"t": np.minimum(t, 3000.0), "c": (t > 3000.0).astype(int),
                         "T": Z[:, 0], "V": Z[:, 1]})


def test_an_alt_fit_with_every_failure_in_one_cell_says_so():
    payload, cache_id = alt.fit(_alt_test(54), {"x": "t", "c": "c"}, ["T", "V"], "weibull", "dual_power")
    assert payload["maximum"] == "no finite maximum"
    notice = payload["no_finite_maximum"]
    assert notice["parameters"] == ["c", "m", "n"]  # DualPower's coefficients, by name
    assert notice["message"] == ("These data don't pin down the model: c, m and n run off to infinity. "
                                 "The numbers below aren't estimates.")
    assert notice["suggestion"].startswith("Spread the failures across more stress levels")
    assert notice["detail"].startswith("No finite maximum")
    # Its standard errors and bounds mean nothing: no intervals are shown.
    assert all(c["ci"] is None for c in payload["coefficients"] + payload["params"])


def test_an_alt_fit_with_a_maximum_carries_no_notice():
    payload, _ = alt.fit(_alt_test(4), {"x": "t", "c": "c"}, ["T", "V"], "weibull", "power_exponential")
    assert payload["maximum"] == "verified"
    assert "no_finite_maximum" not in payload


def test_the_use_level_evaluation_carries_the_warning(monkeypatch):
    from backend.services import alt as alt_service
    from backend.services import datasets as datasets_service

    db = mongomock.MongoClient()["nomax"]
    df = _alt_test(54)
    ds = datasets_service.create_dataset(db, "alt", df.to_csv(index=False).encode(), "u1")
    doc = alt_service.save_model(db, "One cell", ds, {
        "mapping": {"x": "t", "c": "c"}, "stress_cols": ["T", "V"],
        "distribution_id": "weibull", "life_model_id": "dual_power"}, "u1")
    out = alt_service.evaluate(db, doc.id, [330.0, 300.0], "u1")
    assert out["no_finite_maximum"]["parameters"] == ["c", "m", "n"]


def _separated(seed=3, n=60):
    rng = np.random.default_rng(seed)
    t = sp.Weibull.random(n, 100, 2, random_state=rng)
    c = (rng.uniform(size=n) < 0.3).astype(int)
    # grp is 1 on exactly the censored rows: a level with no failures.
    return pd.DataFrame({"t": t, "c": c, "grp": c, "age": rng.normal(size=n)})


def test_a_regression_fit_names_the_covariate_that_runs_off():
    r = fitting.fit("weibull_ph", _separated(), {"x": "t", "c": "c"}, ["grp", "age"])
    assert r["maximum"] == "no finite maximum"
    notice = r["no_finite_maximum"]
    assert notice["parameters"] == ["grp"]
    assert notice["message"].startswith("These data don't pin down the model: grp runs off to infinity.")
    assert "remove or coarsen it" in notice["suggestion"]
    assert all(c["ci"] is None for c in r["coefficients"] + r["params"])
    # An ordinary regression fit reports its verified maximum, and no notice.
    ok = fitting.fit("weibull_ph", _separated().assign(grp=np.arange(60) % 2), {"x": "t", "c": "c"},
                     ["grp", "age"])
    assert ok["maximum"] == "verified" and "no_finite_maximum" not in ok


# SurPyval's #487 sample: the offset Weibull's likelihood rises all the way to
# gamma = 55, the first failure.
RUN_ONTO_FIRST = [55, 60, 70, 80, 95, 120, 140]


def test_an_offset_fit_onto_the_first_failure_points_at_mps():
    r = fitting.fit("weibull", pd.DataFrame({"t": RUN_ONTO_FIRST}), {"x": "t"}, options={"offset": True})
    assert r["maximum"] == "no finite maximum" and r["fit_ok"] is False
    notice = r["no_finite_maximum"]
    assert notice["parameters"] == ["gamma"]
    assert "maximum product of spacings (MPS)" in notice["suggestion"]
    # The fit warning is the plain one (shown once, not "the optimiser failed").
    assert r["fit_warning"] == f"{notice['message']} {notice['suggestion']}"
    assert all(p["ci"] is None and p["se"] is None for p in r["params"])
    # MPS, the way out, has an interior offset.
    mps = fitting.fit("weibull", pd.DataFrame({"t": RUN_ONTO_FIRST}), {"x": "t"},
                      options={"offset": True, "how": "MPS"})
    assert "no_finite_maximum" not in mps


def _left_skewed():
    """SurPyval #622's seed 14: an offset Weibull on it runs to its limit,
    the Gumbel."""
    rng = np.random.default_rng(14)
    n = int(rng.choice([15, 30, 100]))
    gamma = float(rng.uniform(0, 50))
    beta = float(rng.uniform(0.8, 4))
    return pd.DataFrame({"t": gamma + sp.Weibull.random(n, 10, beta, random_state=rng)})


def test_an_offset_fit_running_to_its_limit_names_the_limit():
    r = fitting.fit("weibull", _left_skewed(), {"x": "t"}, options={"offset": True})
    notice = r["no_finite_maximum"]
    assert "gamma" in notice["parameters"]
    assert notice["suggestion"].startswith("Fit a Gumbel distribution instead")


def test_best_fit_names_the_reason_in_its_failed_list():
    r = fitting.fit("best", pd.DataFrame({"t": RUN_ONTO_FIRST}), {"x": "t"}, options={"offset": True})
    failed = {f["id"]: f["reason"] for f in r["selection"]["failed"]}
    assert failed["weibull"] == "no finite maximum: gamma runs off to infinity"
    assert r["distribution_id"] not in failed
    assert "no_finite_maximum" not in r


def test_mcp_leads_with_it_and_drops_the_metrics():
    r = fitting.fit("weibull_ph", _separated(), {"x": "t", "c": "c"}, ["grp", "age"])
    out = _fit_summary(r)
    assert list(out)[:3] == ["fit_ok", "maximum", "warning"]
    assert out["fit_ok"] is False and out["maximum"] == "no finite maximum"
    assert "grp runs off to infinity" in out["warning"] and "Don't quote" in out["warning"]
    assert out["metrics"] is None and "no finite maximum" in out["metrics_omitted"]
    ok = _fit_summary(fitting.fit("weibull", pd.DataFrame({"t": [120, 340, 510, 700, 980]}), {"x": "t"}))
    assert ok["maximum"] == "verified" and "fit_ok" not in ok


@pytest.mark.parametrize("how", ["MPS", "MPP"])
def test_a_fit_without_a_likelihood_maximum_is_not_flagged_as_failed(how):
    """MPS / MPP fits report ``maximum = "not applicable"``; they used to be
    flagged "did not reach a verified maximum" and fit_ok false."""
    r = fitting.fit("weibull", pd.DataFrame({"t": [120, 340, 510, 700, 980, 1200]}), {"x": "t"},
                    options={"how": how})
    assert r["maximum"] == "not applicable"
    assert r["fit_ok"] is True and "fit_warning" not in r
