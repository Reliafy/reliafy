"""SurPyval 0.23 adoption (#238): the renamed names, the newly refused
data, and the expectations that moved.

Every call into SurPyval goes through its 0.23 names, so these run clean with
``-W error::DeprecationWarning`` for SurPyval's own deprecations; saved models
keep Reliafy's (and old SurPyval's) keys and still load.
"""

import copy
import warnings

import matplotlib

matplotlib.use("Agg")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402
import surpyval as sp  # noqa: E402

from backend import fitting  # noqa: E402
from backend.fitting import FitError  # noqa: E402
from backend.services import rbd_analysis as ra  # noqa: E402
from backend.services import rbd_export  # noqa: E402
from backend.services import strategy  # noqa: E402


def _no_surpyval_deprecations():
    """Turn SurPyval's deprecations (all say "removed in v0.24") into errors."""
    ctx = warnings.catch_warnings()
    ctx.__enter__()
    warnings.filterwarnings("error", message=r".*removed in v0\.2", category=DeprecationWarning)
    return ctx


@pytest.fixture()
def strict():
    ctx = _no_surpyval_deprecations()
    try:
        yield
    finally:
        ctx.__exit__(None, None, None)


def test_the_pins_are_surpyval_0_23_and_repyability_0_13():
    """Reliafy stays on SurPyval 0.23, the version RePyability 0.13 targets."""
    import repyability

    assert sp.__version__ == "0.23"
    assert repyability.__version__ == "0.13"
    assert rbd_export.detect_versions() == {"surpyval": "0.23", "repyability": "0.13"}


# ---------------------------------------------------------------------------
# The limited-failure proportion: Reliafy's "p", SurPyval 0.23's ``lfp_p``
# ---------------------------------------------------------------------------
def test_surpyval_extras_translates_p_to_lfp_p():
    assert fitting.surpyval_extras({"gamma": 5, "p": 0.6, "f0": 0.1, "junk": 1}) == \
        {"gamma": 5.0, "lfp_p": 0.6, "f0": 0.1}
    assert fitting.surpyval_extras({"lfp_p": 0.4, "p": None}) == {"lfp_p": 0.4}
    assert fitting.surpyval_extras(None) == {}


def _lfp_df(seed=7):
    rng = np.random.default_rng(seed)
    n = 300
    fails = rng.uniform(size=n) < 0.6
    t = sp.Weibull.random(n, 100, 2.5, random_state=rng)
    x = np.where(fails, np.minimum(t, 400), 400)
    c = np.where(fails & (t < 400), 0, 1)
    return pd.DataFrame({"t": x, "c": c})


def test_an_lfp_fit_stores_p_from_lfp_p_and_rebuilds_without_warnings(strict):
    r = fitting.fit("weibull", _lfp_df(), {"x": "t", "c": "c"}, options={"lfp": True})
    p = r["extras"]["p"]
    assert 0.5 < p < 0.7
    # Every rebuild path (params-only model, strategy, RBD) reads the stored
    # "p" and passes SurPyval lfp_p -- no DeprecationWarning (strict).
    params = r["params"]
    alpha, beta = (q["value"] for q in params)
    want = sp.Weibull.from_params([alpha, beta], lfp_p=p)
    rebuilt = fitting.result_from_params("weibull", params, {"p": p})
    assert rebuilt["extras"] == {"p": p}
    model, _ = strategy._model_from_params("weibull", params, {"p": p})
    assert model.lfp_p == pytest.approx(p)
    node = ra._build_distribution({"distribution_id": "weibull", "params": params, "extras": {"p": p}}, "Pump")
    t = np.array([50.0, 150.0, 1e4])
    for m in (model, node):
        assert np.allclose(m.sf(t), want.sf(t))
    assert float(want.sf(1e6)) == pytest.approx(1 - p)


def test_fixed_lfp_p_is_passed_as_lfp_p(strict):
    r = fitting.fit("weibull", _lfp_df(), {"x": "t", "c": "c"},
                    options={"lfp": True, "fixed": {"p": 0.6}})
    assert r["extras"]["p"] == pytest.approx(0.6)


def test_covariance_comes_from_covariance_not_cov_matrix(strict):
    r = fitting.fit("weibull", pd.DataFrame({"t": [120, 340, 510, 700, 980, 1200, 1500, 1800]}), {"x": "t"})
    assert all(p["se"] and p["ci"] for p in r["params"])


def test_ensure_covariance_backfills_through_the_new_attribute(strict):
    model = sp.Weibull.fit([120, 340, 510, 700, 980, 1200, 1500, 1800])
    want = model.covariance().copy()
    model._covariance = None  # as when SurPyval's Hessian came out non-finite
    fitting._ensure_covariance(model)
    assert np.allclose(model.covariance(), want, rtol=1e-3)
    # ... and the backfill is what to_dict saves (0.23's key).
    assert "covariance" in model.to_dict() and "cov_matrix" not in model.to_dict()


def test_a_model_saved_by_0_22_still_loads_with_its_covariance_and_lfp(strict):
    """Saved models carry 0.22's keys ("cov_matrix", "p"); SurPyval 0.23 reads
    them. (The other way -- a 0.23 dict read by 0.22 -- loses the covariance:
    the rollback note in the PR.)"""
    model = sp.Weibull.fit(x=[5, 8, 12, 20, 30, 40, 400, 400], c=[0, 0, 0, 0, 0, 0, 1, 1], lfp=True)
    d = model.to_dict()
    old = copy.deepcopy(d)
    old["cov_matrix"] = old.pop("covariance")
    old.pop("_neg_ll", None)
    assert old["p"] == pytest.approx(model.lfp_p)  # the saved key stays "p"
    cache_id = fitting.restore_live({"model": old, "grid": [0, 10, 20], "fields": []})
    back = fitting._entry_for(cache_id, None)["model"]
    assert back.lfp_p == pytest.approx(model.lfp_p)
    assert np.allclose(back.covariance(), model.covariance())


def test_exported_python_writes_lfp_p_and_needs_0_23(tmp_path):
    from backend.tests.test_rbd_export import WHEN, _io, _node, _run

    lfp = {"source": "params", "distribution": "Weibull", "distribution_id": "weibull",
           "params": [{"name": "alpha", "value": 100.0}, {"name": "beta", "value": 2.0}],
           "extras": {"p": 0.3}}
    graph = {"unit": "h", "nodes": [*_io(), _node("a", "component", "Seal", model=lfp)],
             "edges": [{"source": "input", "target": "a"}, {"source": "a", "target": "output"}]}
    code = rbd_export.to_python(graph, "LFP", exported_at=WHEN)
    assert "surv.Weibull.from_params([100.0, 2.0], lfp_p=0.3)" in code
    assert ", p=0.3" not in code
    head = code.split('"""')[1]
    assert "Needs SurPyval 0.23 or later" in head.replace("\n", " ")
    # A plain diagram doesn't carry the note.
    plain = copy.deepcopy(graph)
    plain["nodes"][-1]["data"]["model"].pop("extras")
    assert "Needs SurPyval 0.23" not in rbd_export.to_python(plain, "Plain", exported_at=WHEN)
    # The script runs on 0.23 without SurPyval's deprecations (they'd fail it)
    # and gives the app's numbers.
    strict_code = code.replace(
        "import surpyval as surv",
        "import warnings\nwarnings.filterwarnings('error', message=r'.*removed in v0\\.2', "
        "category=DeprecationWarning)\nimport surpyval as surv", 1)
    res, _ = _run(strict_code, tmp_path)
    for t, r in res["reliability"].items():
        assert r == pytest.approx(float(sp.Weibull.from_params([100, 2], lfp_p=0.3).sf(float(t))), rel=1e-12)


# ---------------------------------------------------------------------------
# Data SurPyval 0.23 refuses (#611, #565, #622): a plain sentence naming rows
# ---------------------------------------------------------------------------
def test_a_censored_time_below_zero_names_its_row():
    df = pd.DataFrame({"t": [-1.0, 5, 8, 12, 20, 30, 40], "c": [1, 0, 0, 0, 0, 1, 0]})
    with pytest.raises(FitError) as exc:
        fitting.fit("weibull", df, {"x": "t", "c": "c"})
    msg = str(exc.value)
    assert msg.startswith("Row 1 (time -1) is outside the support of a Weibull")
    assert "censored" in msg and "Correct or remove that row" in msg


def test_several_bad_rows_are_listed():
    df = pd.DataFrame({"t": [5.0, -2, 8, -3, 20, 30], "c": [0, 1, 0, -1, 0, 0]})
    with pytest.raises(FitError, match=r"^Rows 2 and 4 \(times -2 and -3\) are outside the support"):
        fitting.fit("weibull", df, {"x": "t", "c": "c"})


def test_an_offset_fit_names_an_infinite_row():
    df = pd.DataFrame({"t": [3.0, 5, 8, 12, 20, np.inf]})
    with pytest.raises(FitError, match=r"Row 6 \(time inf\) is outside the support of an offset Weibull: "
                                       r"it can't take an infinite time"):
        fitting.fit("weibull", df, {"x": "t"}, options={"offset": True})


def test_a_right_censored_zero_still_fits():
    df = pd.DataFrame({"t": [0.0, 5, 8, 12, 20], "c": [1, 0, 0, 0, 0]})
    assert fitting.fit("weibull", df, {"x": "t", "c": "c"})["params"]


def test_best_fit_names_the_rows_every_candidate_refuses():
    df = pd.DataFrame({"t": [-1.0, 5, 8, 12, 20, 30, 40], "c": [1, 0, 0, 0, 0, 1, 0]})
    # Whole-line distributions (Normal, Gumbel, ...) take the row; the
    # positive ones refuse it, named, in the "failed" list.
    r = fitting.fit("best", df, {"x": "t", "c": "c"})
    failed = {f["id"]: f["reason"] for f in r["selection"]["failed"]}
    assert failed["weibull"].startswith("Row 1 (time -1) is outside the support of a Weibull")
    assert r["distribution_id"] not in failed
    # When every candidate refuses the rows, the error names them.
    df = pd.DataFrame({"t": [5.0, np.inf, 8, 12], "c": [0, 0, 0, 0]})
    with pytest.raises(FitError, match=r"^Row 2 \(time inf\)"):
        fitting.fit("best", df, {"x": "t", "c": "c"})


def test_a_regression_fit_names_the_row():
    rng = np.random.default_rng(1)
    df = pd.DataFrame({"t": sp.Weibull.random(30, 100, 2, random_state=rng), "c": 0,
                       "z": rng.normal(size=30)})
    df.loc[4, "t"], df.loc[4, "c"] = -1.0, 1
    with pytest.raises(FitError, match=r"^Row 5 \(time -1\) is outside the support of a Weibull PH"):
        fitting.fit("weibull_ph", df, {"x": "t", "c": "c"}, ["z"])


def test_an_alt_fit_names_the_row():
    from backend import alt

    rng = np.random.default_rng(2)
    T = np.repeat([350.0, 380.0, 410.0], 10)
    df = pd.DataFrame({"t": sp.Weibull.random(30, 100, 2, random_state=rng) * np.exp(3000 / T - 8),
                       "c": 0, "T": T})
    df.loc[7, "t"], df.loc[7, "c"] = -1.0, 1
    with pytest.raises(FitError, match=r"^Row 8 \(time -1\) is outside the support of a Weibull"):
        alt.fit(df, {"x": "t", "c": "c"}, ["T"], "weibull", "arrhenius")


# ---------------------------------------------------------------------------
# Expectations that moved
# ---------------------------------------------------------------------------
def test_turnbull_fits_untruncated_interval_data_by_the_em_icm():
    """#620: Turnbull's default (Fleming-Harrington) curve on untruncated
    interval data comes from the non-parametric MLE's expected counts. On
    SurPyval's five-interval example R(5) moves 0.2948 (0.22, EM) -> 0.2771
    (0.23, EM-ICM), and R(9) 0.2631 -> 0.2771."""
    df = pd.DataFrame({"lo": [1, 2, 3, 1, 9], "hi": [5, 3, 6, 8, 10]})
    r = fitting.fit("turnbull", df, {"xl": "lo", "xr": "hi"}, None, None, "hours")
    R = dict(zip(r["estimate"]["x"], r["estimate"]["R"]))
    assert R[5.0] == pytest.approx(0.27711205, abs=1e-6)
    assert R[9.0] == pytest.approx(0.27711205, abs=1e-6)
    assert R[10.0] == pytest.approx(0.10194383, abs=1e-6)


def test_cox_reports_partial_likelihood_criteria_and_coefficient_cis():
    """#604, #613: Cox now has a covariance (so coefficient CIs) and AIC/BIC
    on its partial likelihood -- labelled so, and never ranked against a
    parametric model's."""
    rng = np.random.default_rng(4)
    n = 80
    z = rng.integers(0, 2, n)
    t = sp.Weibull.random(n, 100, 1.5, random_state=rng) * np.exp(-0.7 * z)
    df = pd.DataFrame({"t": t, "c": (rng.uniform(size=n) < 0.2).astype(int), "z": z,
                       "age": rng.normal(size=n)})
    r = fitting.fit("cox_ph", df, {"x": "t", "c": "c"}, ["z", "age"])
    assert all(c["ci"] for c in r["coefficients"])
    labels = {g["id"]: g["label"] for g in r["gof"]}
    assert labels["log_likelihood"] == "Log partial likelihood"
    assert labels["aic"] == "AIC (partial)" and labels["bic"] == "BIC (partial)"
    assert all(g["partial"] for g in r["gof"])
    assert "never with a parametric model" in r["gof_note"]
    # A parametric PH fit is not labelled.
    ph = fitting.fit("weibull_ph", df, {"x": "t", "c": "c"}, ["z", "age"])
    assert "gof_note" not in ph and not any(g.get("partial") for g in ph["gof"])


def test_the_mixture_workaround_agrees_with_surpyval_0_23():
    """``_mixture_log_likelihood`` / ``_MixtureFit`` exist because SurPyval's
    ``loglike`` was the EM objective. In 0.23 ``MixtureModel.log_likelihood``
    is the fitted log-likelihood with ``aic()``/``bic()`` (#572): the
    workaround must agree with it before it can be retired."""
    rng = np.random.default_rng(0)
    x = np.round(np.abs(np.concatenate([sp.Weibull.random(200, 300, 4.0, random_state=rng),
                                        sp.Weibull.random(200, 1500, 1.2, random_state=rng)])), 3)
    raw = sp.MixtureModel(dist=sp.Weibull, m=2)
    raw.fit(x=x)
    assert fitting._mixture_log_likelihood(raw, x) == pytest.approx(raw.log_likelihood, rel=1e-9)
    r = fitting.fit("mixture", pd.DataFrame({"hours": x}), {"x": "hours"})
    gof = {g["id"]: g["value"] for g in r["gof"]}
    assert gof["log_likelihood"] == pytest.approx(raw.log_likelihood, rel=1e-6)
    assert gof["aic"] == pytest.approx(raw.aic(), rel=1e-6)
    assert gof["bic"] == pytest.approx(raw.bic(), rel=1e-6)


# ---------------------------------------------------------------------------
# Growth projection with BC modes: 0.23 takes the demonstrated intensity from
# the unadjusted Crow-AMSAA shape, and projects from one failure too
# ---------------------------------------------------------------------------
# MIL-HDBK-189's test-fix-find-test example: one system to T = 400, 56
# failures: 10 A, 14 BC (BC17..BC28), 32 BD (BD1..BD16).
HDBK = """
0.7 BC17, 3.7 BC17, 13.2 BC17, 15 BD1, 17.6 BC18, 25.3 BD2, 47.5 BD3,
54 BD4, 54.5 BC19, 56.4 BD5, 63.6 A, 72.2 BD5, 99.2 BC20, 99.6 BD6,
100.3 BD7, 102.5 A, 112 BD8, 112.2 BC21, 120.9 BD2, 121.9 BC22, 125.5 BD9,
133.4 BD10, 151 BC23, 163 BC24, 164.7 BD9, 174.5 BC25, 177.4 BD10,
191.6 BC26, 192.7 BD11, 213 A, 244.8 A, 249 BD12, 250.8 A, 260.1 BD1,
263.5 BD8, 273.1 A, 274.7 BD6, 282.8 BC27, 285 BD13, 304 BD9, 315.4 BD4,
317.1 A, 320.6 A, 324.5 BD12, 324.9 BD10, 342 BD5, 350.2 BD3, 355.2 BC28,
364.6 BD10, 364.9 A, 366.3 BD2, 373 BD8, 379.4 BD14, 389 BD15, 394.9 A,
395.2 BD16
"""
FEFS = [0.67, 0.72, 0.77, 0.77, 0.87, 0.92, 0.5, 0.85, 0.89, 0.74, 0.7, 0.63, 0.64, 0.72, 0.69, 0.46]
GROWTH_MAP = {"i": "sys", "x": "t", "mode": "m"}


def test_bc_mode_projection_on_the_handbook_example():
    from backend import recurrent as rec

    rows = [r.split() for r in HDBK.split(",")]
    df = pd.DataFrame({"sys": "P1", "t": [float(t) for t, _ in rows], "m": [m for _, m in rows]})
    fef = {f"BD{j + 1}": v for j, v in enumerate(FEFS)}
    bc = [f"BC{j}" for j in range(17, 29)]
    out = rec.growth_projection(df, GROWTH_MAP, fef, bc=bc, test_end=400)
    assert out["failures"] == {"A": 10, "BC": 14, "BD": 32}
    assert out["demonstrated_basis"] == "crow_amsaa"
    assert out["demonstrated"]["mtbf"] == pytest.approx(7.70690, abs=1e-5)
    assert out["projected"]["mtbf"] == pytest.approx(11.00604, abs=1e-5)


def test_bc_modes_with_one_failure_still_project():
    from surpyval.recurrent import CrowAMSAA

    from backend import recurrent as rec

    df = pd.DataFrame({"sys": "P1", "t": [50.0], "m": ["seal"]})
    out = rec.growth_projection(df, GROWTH_MAP, {}, bc=["seal"], test_end=400)
    ref = CrowAMSAA.projection([50.0, 400.0], ["seal", None], {}, bc=["seal"], c=[0, 1])
    assert out["projected"]["mtbf"] == pytest.approx(ref.projected_mtbf, rel=1e-12)


def test_cox_has_no_qf_and_no_metrics_at_the_covariate_means():
    """SurPyval 0.23 gives CoxPH no ``qf``: no median / B10 / MTTF for a Cox
    model (its B10 would be an event time on a curve that often stops short
    of 0)."""
    rng = np.random.default_rng(5)
    n = 60
    z = rng.normal(size=n)
    t = sp.Weibull.random(n, 100, 1.5, random_state=rng) * np.exp(-0.5 * z)
    df = pd.DataFrame({"t": t, "c": (rng.uniform(size=n) < 0.2).astype(int), "z": z})
    r = fitting.fit("cox_ph", df, {"x": "t", "c": "c"}, ["z"])
    model = fitting._MODEL_STORE[r["functions"]["model_id"]]["model"]
    assert not callable(getattr(model, "qf", None))
    assert "at_covariate_means" not in r and r["metrics_note"] == fitting.REGRESSION_METRICS_NOTE
    assert fitting.regression_metrics_at_defaults(model, r["functions"]["covariates"]) is None
