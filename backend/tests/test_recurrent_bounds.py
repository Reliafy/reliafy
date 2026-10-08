"""#81: repairable systems — β's confidence interval decides the growth
verdict; ROCOF / MTBF bounds and the demonstrated MTBF (Crow's exact bounds
where the test design allows); the Laplace and MIL-HDBK-189C trend tests; AIC,
BIC and the Cramér-von Mises goodness-of-fit test; per-system residuals; and
Cox-Lewis as an alternative model. Every number is checked against SurPyval
called directly on the same data."""

import json

import mongomock
import numpy as np
import pandas as pd
import pytest
from surpyval.recurrent import CoxLewis, CrowAMSAA, Duane, HPP, laplace, mil_hdbk_189c

from backend.tests.test_mcp import A, _call, _ok, env  # noqa: F401 - env is a fixture

# Three systems, each observed from 0 to 300 hours: a time-terminated test.
TIMES = {"A": [100, 180, 240, 280], "B": [120, 210, 270], "C": [90, 160, 220, 260, 290]}
END = 300.0


def _frame(times=TIMES, end=END) -> pd.DataFrame:
    return pd.DataFrame([{"system": s, "time": t, "obs_end": end} for s, ts in times.items() for t in ts])


def _arrays(times=TIMES):
    x = np.array([t for ts in times.values() for t in ts], dtype=float)
    i = np.array([s for s, ts in times.items() for _ in ts])
    return x, i


MAPPING = {"i": "system", "x": "time", "tr": "obs_end"}


def _ref(fitter=CrowAMSAA, times=TIMES, end=END):
    x, i = _arrays(times)
    return fitter.fit(x=x, i=i, tr=np.full(x.size, end))


def _fit(model_id="crow_amsaa", df=None, mapping=MAPPING):
    from backend import recurrent as rec

    payload, cache_id = rec.fit(_frame() if df is None else df, mapping, model_id, "hours")
    json.dumps(payload, allow_nan=False)
    return payload, cache_id


# ---- β's interval and the growth verdict ----------------------------------------


def test_beta_interval_matches_surpyval_and_decides_the_verdict():
    r, _ = _fit()
    ref = _ref()
    lo, hi = ref.param_cb("beta", alpha_ci=0.05)
    assert r["beta"] == pytest.approx(ref.params[1], rel=1e-9)
    assert r["beta_ci"] == pytest.approx([lo, hi], rel=1e-9)
    assert {p["name"]: p["ci"] for p in r["params"]}["beta"] == pytest.approx([lo, hi], rel=1e-9)
    assert lo > 1 and r["growth"] == "deteriorating"
    b = r["growth_basis"]
    assert b["rule"] == "interval" and b["no_trend"] == 1.0 and b["level"] == 0.95
    assert b["ci"] == pytest.approx([lo, hi], rel=1e-9)


def test_interval_that_includes_one_is_stable_even_outside_the_old_band():
    """β = 1.3 would have been 'deteriorating' under the fixed 0.95–1.05 band;
    with only a handful of events its interval includes 1, so the data don't
    show a trend."""
    times = {"S1": [300, 700, 1000, 1250, 1450, 1600]}
    df = pd.DataFrame({"system": "S1", "time": times["S1"]})
    r, _ = _fit(df=df, mapping={"i": "system", "x": "time"})
    x = np.array(times["S1"], dtype=float)
    ref = CrowAMSAA.fit(x=x, i=np.array(["S1"] * x.size))
    lo, hi = ref.param_cb("beta", alpha_ci=0.05)
    assert not 0.95 <= r["beta"] <= 1.05
    assert lo < 1 < hi
    assert r["growth"] == "stable" and r["growth_basis"]["ci"] == pytest.approx([lo, hi], rel=1e-9)


def test_duane_shape_interval_is_its_alpha():
    r, _ = _fit("duane")
    ref = _ref(Duane)
    assert r["beta_ci"] == pytest.approx(ref.param_cb("alpha", alpha_ci=0.05), rel=1e-9)
    assert r["growth_basis"]["parameter"] == "alpha"


def test_from_params_has_no_interval_so_the_value_decides():
    from backend import recurrent as rec

    for beta, want in ((1.02, "deteriorating"), (1.0, "stable"), (0.98, "improving")):
        r, _ = rec.fit_from_params("crow_amsaa", [{"name": "alpha", "value": 100}, {"name": "beta", "value": beta}],
                                   1000, "hours")
        assert r["growth"] == want and r["growth_basis"]["rule"] == "value" and r["beta_ci"] is None
        assert r["trend_tests"] == [] and r["rocof"] == pytest.approx(
            float(CrowAMSAA.from_params([100, beta]).iif(1000.0)), rel=1e-12)


# ---- ROCOF / MTBF bounds and the demonstrated MTBF ---------------------------------


def test_time_terminated_crow_amsaa_gets_crow_exact_bounds():
    r, _ = _fit()
    ref = _ref()
    assert r["end_of_observation"] == END
    assert r["bounds_method"] == "crow"
    assert r["rocof"] == pytest.approx(float(ref.iif(END)), rel=1e-12)
    assert r["mtbf"] == pytest.approx(float(ref.mtbf(END)), rel=1e-12)
    assert r["mtbf_ci"] == pytest.approx(ref.mtbf_cb(END, alpha_ci=0.05, method="crow"), rel=1e-9)
    assert r["rocof_ci"] == pytest.approx(ref.iif_cb(END, alpha_ci=0.05, method="crow"), rel=1e-9)
    dm = r["demonstrated_mtbf"]
    assert dm["method"] == "crow" and dm["confidence"] == 0.9 and dm["at"] == END
    assert dm["lower"] == pytest.approx(float(ref.mtbf_cb(END, alpha_ci=0.10, bound="lower", method="crow")),
                                        rel=1e-9)
    assert dm["lower"] < r["mtbf"]


def test_mil_hdbk_189c_single_system_example():
    """SurPyval's documented growth test: one prototype stopped at 2000 h
    (a c = 1 end-of-test row), demonstrated MTBF 300 h."""
    x = [40, 110, 210, 340, 500, 690, 920, 1180, 1480, 1800, 2000]
    c = [0] * 10 + [1]
    df = pd.DataFrame({"system": "P1", "time": x, "c": c})
    r, _ = _fit(df=df, mapping={"i": "system", "x": "time", "c": "c"})
    ref = CrowAMSAA.fit(x, c=c)
    assert r["mtbf"] == pytest.approx(300.0, abs=0.1)
    assert r["bounds_method"] == "crow"
    assert r["demonstrated_mtbf"]["lower"] == pytest.approx(
        float(ref.mtbf_cb(2000.0, alpha_ci=0.10, bound="lower", method="crow")), rel=1e-9)
    # The end-of-test row isn't an event: both trend tests see 10 failures.
    assert r["trend_tests"][0]["p_value"] == pytest.approx(laplace(x, c=c).p_value, rel=1e-12)
    assert r["trend_tests"][1]["p_value"] == pytest.approx(mil_hdbk_189c(x, c=c).p_value, rel=1e-12)


def test_unequal_windows_fall_back_to_wald_bounds():
    df = _frame()
    df.loc[df.system == "B", "obs_end"] = 280.0
    r, _ = _fit(df=df)
    x, i = _arrays()
    ref = CrowAMSAA.fit(x=x, i=i, tr=df["obs_end"].to_numpy(dtype=float))
    assert r["bounds_method"] == "wald" and r["demonstrated_mtbf"]["method"] == "wald"
    assert r["mtbf_ci"] == pytest.approx(ref.mtbf_cb(END, alpha_ci=0.05), rel=1e-9)
    assert r["rocof_ci"] == pytest.approx(ref.iif_cb(END, alpha_ci=0.05), rel=1e-9)
    assert r["demonstrated_mtbf"]["lower"] == pytest.approx(
        float(ref.mtbf_cb(END, alpha_ci=0.10, bound="lower")), rel=1e-9)


def test_hpp_gets_wald_bounds_and_no_growth_verdict():
    r, _ = _fit("hpp")
    ref = _ref(HPP)
    assert r["growth"] is None and r["beta"] is None
    assert r["mtbf"] == pytest.approx(float(ref.mtbf(END)), rel=1e-12)
    assert r["mtbf_ci"] == pytest.approx(ref.mtbf_cb(END, alpha_ci=0.05), rel=1e-9)
    assert r["bounds_method"] == "wald"


# ---- Trend tests ------------------------------------------------------------------


def test_trend_tests_match_surpyval_with_delayed_entry():
    """Each system tested on its own window, entry (tl) to close (tr)."""
    df = _frame()
    df["start"] = df.system.map({"A": 50.0, "B": 0.0, "C": 80.0})
    r, _ = _fit(df=df, mapping={**MAPPING, "tl": "start"})
    x, i = _arrays()
    tl, tr = df["start"].to_numpy(dtype=float), np.full(x.size, END)
    model = CrowAMSAA.fit(x=x, i=i, tl=tl, tr=tr)
    by_id = {t["id"]: t for t in r["trend_tests"]}
    assert set(by_id) == {"laplace", "mil_hdbk_189c"}
    for test_id in by_id:
        want = model.trend_test(test_id)
        assert by_id[test_id]["statistic"] == pytest.approx(want.statistic, rel=1e-12)
        assert by_id[test_id]["p_value"] == pytest.approx(want.p_value, rel=1e-12)
        assert by_id[test_id]["significant"] == (want.p_value < 0.05)
    assert by_id["mil_hdbk_189c"]["dof"] == model.trend_test("mil_hdbk_189c").dof
    # The model's tests are SurPyval's standalone ones on the same windows.
    windows = {s: (float(df[df.system == s]["start"].iloc[0]), END) for s in TIMES}
    T = {s: w[1] for s, w in windows.items()}
    TL = {s: w[0] for s, w in windows.items()}
    assert by_id["mil_hdbk_189c"]["p_value"] == pytest.approx(mil_hdbk_189c(x, i, T=T, tl=TL).p_value, rel=1e-12)
    assert by_id["laplace"]["p_value"] == pytest.approx(laplace(x, i, T=T, tl=TL).p_value, rel=1e-12)
    # ``trend`` (Laplace) is kept for older readers.
    assert r["trend"] == by_id["laplace"]


def test_trend_labels():
    r, _ = _fit()
    for t in r["trend_tests"]:
        assert t["trend"] in ("increasing", "decreasing", "no trend")
        if not t["significant"]:
            assert t["trend"] == "no trend"
    assert [t["test"] for t in r["trend_tests"]] == ["Laplace", "MIL-HDBK-189C"]


# ---- Goodness of fit --------------------------------------------------------------


def test_aic_bic_and_cramer_von_mises_match_surpyval():
    r, _ = _fit()
    ref = _ref()
    gof = {g["id"]: g["value"] for g in r["gof"]}
    assert gof["aic"] == pytest.approx(ref.aic(), rel=1e-9)
    assert gof["bic"] == pytest.approx(ref.bic(), rel=1e-9)
    assert gof["neg_ll"] == pytest.approx(ref.neg_ll(), rel=1e-9)
    cvm = ref.cramer_von_mises(n_boot=200, random_state=0)
    assert r["gof_test"]["statistic"] == pytest.approx(cvm.statistic, rel=1e-9)
    assert r["gof_test"]["p_value"] == pytest.approx(cvm.p_value, rel=1e-12)
    assert r["gof_test"]["n_boot"] == 200 and r["gof_test"]["adequate"] == (cvm.p_value >= 0.05)


def test_cramer_von_mises_replicates_shrink_and_stop_with_size():
    from backend import recurrent as rec

    model = _ref()
    assert rec.cramer_von_mises(model, 12)["n_boot"] == 200
    assert rec.cramer_von_mises(model, 4000)["n_boot"] == 100
    skipped = rec.cramer_von_mises(model, 20_000)
    assert skipped["p_value"] is None and "Skipped" in skipped["reason"]


def test_refit_for_the_live_model_skips_the_bootstrap():
    r, _ = _fit()
    from backend import recurrent as rec

    payload, _ = rec.fit(_frame(), MAPPING, "crow_amsaa", "hours", gof_test=False)
    assert payload["gof_test"] is None and payload["trend_tests"] == r["trend_tests"]


def test_system_residuals_are_surpyvals_martingale_residuals():
    r, _ = _fit()
    ref = _ref()
    res = dict(zip(ref.data.items, ref.residuals("martingale")))
    rows = r["system_residuals"]
    assert [row["system"] for row in rows] == sorted(res, key=lambda s: -res[s])
    for row in rows:
        assert row["excess"] == pytest.approx(res[row["system"]], abs=1e-9)
        assert row["failures"] == len(TIMES[row["system"]])
        assert row["expected"] == pytest.approx(float(ref.cif(END)), rel=1e-9)


# ---- Cox-Lewis --------------------------------------------------------------------


def test_cox_lewis_fit_matches_surpyval_and_its_slope_decides():
    from backend import recurrent as rec

    r, cache_id = _fit("cox_lewis")
    ref = _ref(CoxLewis)
    assert [p["name"] for p in r["params"]] == ["alpha", "beta"]
    assert [p["value"] for p in r["params"]] == pytest.approx(ref.params, rel=1e-6)
    lo, hi = ref.param_cb("beta", alpha_ci=0.05)
    assert r["growth_basis"]["no_trend"] == 0.0 and r["growth_basis"]["ci"] == pytest.approx([lo, hi], rel=1e-6)
    assert r["growth"] == ("deteriorating" if lo > 0 else "improving" if hi < 0 else "stable")
    assert r["beta"] is None and r["beta_ci"] is None  # not a power-law shape
    assert r["rocof"] == pytest.approx(float(ref.iif(END)), rel=1e-6)
    assert r["bounds_method"] == "wald"
    # A rising log-linear intensity has a finite overhaul optimum.
    out = rec.optimal_overhaul(rec.get_live(cache_id), 1, 10)
    assert out["shape"] is None and out["log_linear_slope"] > 0 and out["optimal"]["interval"] > 0


def test_cox_lewis_falling_intensity_never_pays_to_overhaul():
    from backend import recurrent as rec

    out = rec.optimal_overhaul({"model_id": "cox_lewis", "params": [-2.0, -0.001]}, 1, 10)
    assert out["optimal"] is None and "decreasing" in out["reason"]


def test_cox_lewis_cannot_be_built_from_the_power_law_form():
    from backend import recurrent as rec
    from backend.fitting import FitError

    with pytest.raises(FitError, match="fit it to event data"):
        rec.fit_from_params("cox_lewis", [{"name": "alpha", "value": 1}, {"name": "beta", "value": 0.1}], 10)


# ---- Saved before #81: filled in on read --------------------------------------------


def _client(monkeypatch, test_db):
    from backend.tests.test_recurrent import _client as client

    return client(monkeypatch, test_db)


def test_older_saved_model_is_backfilled_on_read(monkeypatch):
    from backend.auth import get_current_user

    test_db = mongomock.MongoClient()["reliafy_test"]
    client, app = _client(monkeypatch, test_db)
    csv = _frame().to_csv(index=False).encode()
    form = {"i": "system", "x": "time", "tr": "obs_end", "model": "crow_amsaa", "unit": "hours", "name": "Fleet"}
    try:
        app.dependency_overrides[get_current_user] = lambda: {"uid": A, "email": "a@x.com", "name": "A"}
        r = client.post("/api/recurrent/models", data=form, files={"file": ("e.csv", csv, "text/csv")})
        assert r.status_code == 200, r.text
        model_id = r.json()["id"]
        assert r.json()["results"]["bounds_method"] == "crow"

        # Strip it back to a pre-#81 save (band verdict, Laplace only) with a projection.
        old = {k: v for k, v in r.json()["results"].items()
               if k not in ("trend_tests", "gof_test", "beta_ci", "growth_basis", "rocof_ci", "mtbf_ci",
                            "demonstrated_mtbf", "bounds_method", "system_residuals", "end_of_observation")}
        test_db.recurrent_models.update_one({"_id": model_id},
                                            {"$set": {"results": {**old, "projection": {"T": 300}}}})

        got = client.get(f"/api/recurrent/models/{model_id}").json()["results"]
        assert [t["id"] for t in got["trend_tests"]] == ["laplace", "mil_hdbk_189c"]
        assert got["demonstrated_mtbf"]["method"] == "crow" and got["projection"] == {"T": 300}
        stored = test_db.recurrent_models.find_one({"_id": model_id})["results"]
        assert "trend_tests" in stored and stored["gof_test"]["n_boot"] == 200
    finally:
        app.dependency_overrides.clear()


# ---- MCP get_model ----------------------------------------------------------------


def test_mcp_get_model_reports_the_evidence(env):
    from backend.services import datasets as datasets_service
    from backend.services import recurrent as recurrent_service

    ds = datasets_service.create_dataset(env.db, "events.csv", _frame().to_csv(index=False).encode(), A)
    doc = recurrent_service.save_model(
        env.db, "Fleet", ds, {"mapping": MAPPING, "model_id": "crow_amsaa", "unit": "hours"}, A)
    out = _ok(_call(env.token[A], "get_model", {"model_id": doc.id}))
    ref = _ref()
    lo, hi = ref.param_cb("beta", alpha_ci=0.05)
    assert out["growth"] == "deteriorating"
    assert out["beta_ci_95"] == [float(f"{lo:.4g}"), float(f"{hi:.4g}")]
    assert "excludes 1" in out["growth_basis"]
    dm = out["demonstrated_mtbf"]
    assert dm["lower_bound"] == float(f"{float(ref.mtbf_cb(END, alpha_ci=0.1, bound='lower', method='crow')):.4g}")
    assert dm["confidence"] == 0.9 and "Crow" in dm["method"]
    assert out["mtbf_ci_95"] == [float(f"{v:.4g}") for v in ref.mtbf_cb(END, alpha_ci=0.05, method="crow")]
    assert [t["test"] for t in out["trend_tests"]] == ["Laplace", "MIL-HDBK-189C"]
    assert out["gof"]["bic"] == float(f"{ref.bic():.4g}")
    assert out["gof_test"]["test"] == "Cramér-von Mises" and out["gof_test"]["n_boot"] == 200
    assert out["systems_vs_model"][0]["system"] == "C"
