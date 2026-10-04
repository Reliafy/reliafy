"""ALT confidence bounds at the use stress (#231) and regression / ALT fits
from inspection (interval-censored) data (#237), on SurPyval 0.23.

Every number is checked against SurPyval called directly: the bounds are
``cb`` / ``quantile_cb`` / ``param_cb`` with ``method`` wald, lr or bootstrap
(#583, #617), and the interval fits are ``fit`` with a two-column ``x``
(#571). The bootstrap runs as a compute job (``alt_bounds``); the same seed
gives the same bounds in the job and in-process.
"""

import json

import matplotlib

matplotlib.use("Agg")

import mongomock
import numpy as np
import pandas as pd
import pytest
import surpyval as sp
from fastapi.testclient import TestClient

from backend import alt
from backend.fitting import FitError

OWNER = "user-a"


def _alt_df(seed=1, n_per=24, cutoff=5000.0):
    """72 units at three temperatures (K), Arrhenius-Weibull, stopped at
    ``cutoff`` hours — SurPyval's #583 design in miniature."""
    rng = np.random.default_rng(seed)
    T = np.repeat([350.0, 375.0, 400.0], n_per)
    life = np.exp(-12 + 7000 / T)
    x = life * rng.weibull(2.5, T.size)
    c = (x > cutoff).astype(int)
    return pd.DataFrame({"hours": np.minimum(x, cutoff), "tempK": T, "cens": c})


def _inspected(df, every=500.0):
    """The same units read out every ``every`` hours: a failure is only known
    to lie between two inspections (flag 2); survivors stay right-censored."""
    lo = np.floor(df["hours"] / every) * every
    hi = lo + every
    run = df["cens"].to_numpy() == 1
    lo[run] = df["hours"][run]
    hi[run] = df["hours"][run]
    return pd.DataFrame({"lo": lo, "hi": hi, "tempK": df["tempK"], "flag": np.where(run, 1, 2)})


def _direct(df, *, x="hours", c="cens", t=None):
    xs = df[x].to_numpy(float) if isinstance(x, str) else df[list(x)].to_numpy(float)
    kw = {"c": df[c].to_numpy(int)} if c else {}
    if t is not None:
        kw["t"] = t
    return sp.AcceleratedLife(sp.Weibull, alt._LM["Exponential"]).fit(
        x=xs, Z=df[["tempK"]].to_numpy(float), **kw)


USE = [323.0]


# ---- #237: inspection data --------------------------------------------------------

def test_alt_interval_fit_matches_surpyval_two_column_x():
    df = _inspected(_alt_df())
    payload, cid = alt.fit(df, {"xl": "lo", "xr": "hi", "c": "flag"}, ["tempK"], "weibull", "arrhenius", "hours")
    json.dumps(payload)
    ref = _direct(df, x=("lo", "hi"), c="flag")
    np.testing.assert_allclose(alt.get_live(cid).params, ref.params, rtol=1e-9)
    assert payload["interval_censored"] is True and payload["n"] == 72
    # Bootstrap resamples exact and right-censored data only (#617).
    assert payload["bounds_methods"] == ["wald", "lr"]
    # Interval rows are drawn on the life-stress plot as ranges at their stress.
    obs = payload["life_stress_plot"]["observations"]
    assert obs["n_ranges"] == int((df["flag"] == 2).sum())
    seg = obs["ranges"]
    assert len(seg["stress"]) == len(seg["time"]) == 3 * obs["n_ranges"]
    assert seg["time"][0] < seg["time"][1] and seg["time"][2] is None
    # The probability plot places the intervals with Turnbull.
    assert any(s["scatter"] for s in payload["probability_plot"]["series"])
    # The no-intervals fit is a different (biased) one.
    mid = df.assign(mid=(df["lo"] + df["hi"]) / 2, c0=np.where(df["flag"] == 1, 1, 0))
    assert not np.allclose(_direct(mid, x="mid", c="c0").params, ref.params, rtol=1e-3)


def test_alt_interval_without_flags_and_blank_upper_bounds():
    df = _inspected(_alt_df()).drop(columns="flag")
    run = df["lo"] == df["hi"]
    with_flags, _ = alt.fit(_inspected(_alt_df()), {"xl": "lo", "xr": "hi", "c": "flag"}, ["tempK"],
                            "weibull", "arrhenius")
    # A blank upper bound: never found failed, so still running past the lower.
    blank = df.copy()
    blank.loc[run, "hi"] = np.nan
    no_flags, _ = alt.fit(blank, {"xl": "lo", "xr": "hi"}, ["tempK"], "weibull", "arrhenius")
    assert [p["value"] for p in no_flags["params"]] == pytest.approx([p["value"] for p in with_flags["params"]])
    # ... and with the flags too (1 = still running at the lower bound).
    flagged, _ = alt.fit(blank.assign(flag=_inspected(_alt_df())["flag"]), {"xl": "lo", "xr": "hi", "c": "flag"},
                         ["tempK"], "weibull", "arrhenius")
    assert [p["value"] for p in flagged["params"]] == pytest.approx([p["value"] for p in with_flags["params"]])


def test_alt_mapping_takes_x_or_both_interval_columns():
    df = _inspected(_alt_df())
    for mapping in ({"xl": "lo"}, {"x": "lo", "xl": "lo", "xr": "hi"}):
        with pytest.raises(FitError, match="not both"):
            alt.fit(df, mapping, ["tempK"], "weibull", "arrhenius")


def test_alt_truncation_matches_surpyval():
    df = _alt_df().assign(entry=10.0)
    payload, cid = alt.fit(df, {"x": "hours", "c": "cens", "tl": "entry"}, ["tempK"], "weibull", "arrhenius")
    t = np.column_stack([np.full(len(df), 10.0), np.full(len(df), np.inf)])
    np.testing.assert_allclose(alt.get_live(cid).params, _direct(df, t=t).params, rtol=1e-9)
    assert payload["bounds_methods"] == ["wald", "lr", "bootstrap"]


def _reg_df(seed=3, n=120):
    rng = np.random.default_rng(seed)
    age = rng.uniform(0, 2, n)
    t = sp.Weibull.random(n, 100, 2.0) * np.exp(-0.4 * age)
    lo = np.floor(t / 20) * 20
    hi = lo + 20
    flag = np.full(n, 2)
    run = t > 150
    lo[run], hi[run], flag[run] = 150, 150, 1
    return pd.DataFrame({"lo": lo, "hi": hi, "flag": flag, "age": age})


@pytest.mark.parametrize("model_id, fitter", [("weibull_ph", sp.WeibullPH), ("lognormal_aft", sp.LogNormalAFT)])
def test_regression_interval_fit_matches_surpyval(model_id, fitter):
    from backend import fitting

    df = _reg_df()
    out = fitting.fit(model_id, df, {"xl": "lo", "xr": "hi", "c": "flag"}, covariates=["age"])
    ref = fitter.fit(df[["lo", "hi"]].to_numpy(), df[["age"]].to_numpy(), c=df["flag"].to_numpy())
    got = [p["value"] for p in out["params"]] + [c["value"] for c in out["coefficients"]]
    np.testing.assert_allclose(got, ref.params, rtol=1e-8)
    assert out["interval_censored"] is True and out["n"] == len(df)
    assert out["validation"] == {"available": False, "reason": pytest.approx(out["validation"]["reason"])}
    assert "interval data" in out["validation"]["reason"]
    # The calculator's grid reaches the last finite inspection.
    assert out["functions"]["curves"]["x"][-1] >= df["hi"].max()


def test_regression_interval_refuses_cox_and_half_mappings():
    from backend import fitting

    df = _reg_df()
    with pytest.raises(FitError, match="Cox PH can't fit interval-censored"):
        fitting.fit("cox_ph", df, {"xl": "lo", "xr": "hi", "c": "flag"}, covariates=["age"])
    with pytest.raises(FitError, match="not both"):
        fitting.fit("weibull_ph", df, {"xl": "lo", "c": "flag"}, covariates=["age"])


# ---- #231: bounds at the use stress -------------------------------------------------

@pytest.fixture(scope="module")
def fitted():
    payload, cid = alt.fit(_alt_df(), {"x": "hours", "c": "cens"}, ["tempK"], "weibull", "arrhenius", "hours")
    return payload, alt.get_live(cid)


@pytest.mark.parametrize("method", ["wald", "lr"])
def test_bounds_match_surpyval(fitted, method):
    _, m = fitted
    b = alt.use_level_bounds(m, USE, "arrhenius", method=method, confidence=0.9, mission_time=2000.0)
    json.dumps(b)
    Z = np.array([USE])
    q = m.quantile_cb([0.1, 0.01], Z, alpha_ci=0.1, bound="lower", method=method)
    assert [b["b_lives"]["b10"]["lower"], b["b_lives"]["b1"]["lower"]] == pytest.approx(q.tolist(), rel=1e-9)
    assert b["b_lives"]["b10"]["value"] == pytest.approx(float(np.ravel(m.qf(0.1, Z))[0]), rel=1e-12)
    band = m.cb(np.asarray(b["band"]["x"]), Z, on="sf", alpha_ci=0.1, method=method)
    np.testing.assert_allclose(b["band"]["lower"], band[:, 0], rtol=1e-9)
    np.testing.assert_allclose(b["band"]["upper"], band[:, 1], rtol=1e-9)
    assert len(b["band"]["x"]) == alt.BAND_POINTS[method]
    r_lo = m.cb([2000.0], Z, on="sf", alpha_ci=0.1, bound="lower", method=method)
    assert b["mission"]["lower"] == pytest.approx(float(np.ravel(r_lo)[0]), rel=1e-9)
    assert b["mission"]["lower"] < b["mission"]["reliability"] < 1
    coeffs = {c["name"]: c for c in b["coefficients"]}
    assert set(coeffs) == {"beta", "a", "b"} and coeffs["beta"]["kind"] == "shape"
    assert coeffs["a"]["ci"] == pytest.approx(m.param_cb("a", alpha_ci=0.1, method=method).tolist(), rel=1e-9)
    assert b["warnings"] == []  # 71 failures: no few-failures warning


def test_bootstrap_bounds_match_surpyval_with_the_same_seed(fitted):
    _, m = fitted
    b = alt.use_level_bounds(m, USE, "arrhenius", method="bootstrap", n_boot=100, seed=7)
    q = m.quantile_cb([0.1, 0.01], [USE], bound="lower", method="bootstrap", n_boot=100, random_state=7)
    assert [b["b_lives"]["b10"]["lower"], b["b_lives"]["b1"]["lower"]] == pytest.approx(q.tolist(), rel=1e-9)
    assert b["n_boot"] == 100 and b["seed"] == 7


def test_compute_job_gives_the_in_process_bootstrap(fitted):
    """Same seed, same bounds: the compute service's runner refits the model
    from the request's data and runs the same function (#146's rule)."""
    from backend.services import compute_core

    _, m = fitted
    inputs = alt.build_inputs(_alt_df(), {"x": "hours", "c": "cens"}, ["tempK"])
    request = compute_core.alt_bounds_request(
        inputs, distribution_id="weibull", life_model_id="arrhenius", use_stress=USE, confidence=0.95,
        mission_time=1500.0, t_max=40000.0, n_boot=100, seed=alt.BOOTSTRAP_SEED)
    json.dumps(request)  # self-contained, plain JSON
    job = compute_core.run("alt_bounds", request)
    local = compute_core.to_wire(alt.use_level_bounds(
        m, USE, "arrhenius", method="bootstrap", mission_time=1500.0, t_max=40000.0, n_boot=100))
    assert job == local


def test_compute_job_carries_truncation():
    from backend.services import compute_core

    df = _alt_df().assign(entry=10.0)
    inputs = alt.build_inputs(df, {"x": "hours", "c": "cens", "tl": "entry"}, ["tempK"])
    request = compute_core.alt_bounds_request(
        inputs, distribution_id="weibull", life_model_id="arrhenius", use_stress=USE, confidence=0.9,
        mission_time=None, t_max=None, n_boot=100, seed=1)
    assert request["data"]["t"][0] == [10.0, None]
    model = alt.refit(inputs, "weibull", "arrhenius")
    assert compute_core.run("alt_bounds", request) == compute_core.to_wire(
        alt.use_level_bounds(model, USE, "arrhenius", method="bootstrap", confidence=0.9, n_boot=100, seed=1))


def test_bootstrap_refused_for_interval_data_and_lr_needs_the_data():
    df = _inspected(_alt_df())
    _, cid = alt.fit(df, {"xl": "lo", "xr": "hi", "c": "flag"}, ["tempK"], "weibull", "arrhenius")
    with pytest.raises(FitError, match="Bootstrap bounds aren't available for inspection"):
        alt.use_level_bounds(alt.get_live(cid), USE, "arrhenius", method="bootstrap")
    lr = alt.use_level_bounds(alt.get_live(cid), USE, "arrhenius", method="lr")
    assert 0 < lr["b_lives"]["b10"]["lower"] < lr["b_lives"]["b10"]["value"]
    # A model rehydrated from its saved dict keeps no data: Wald only.
    restored = alt.get_live(alt.restore_live(alt.serialize_live(cid)))
    assert not alt.has_data(restored)
    with pytest.raises(FitError, match="need the data"):
        alt.use_level_bounds(restored, USE, "arrhenius", method="lr")
    assert alt.use_level_bounds(restored, USE, "arrhenius")["b_lives"]["b10"]["lower"] > 0


def test_few_failures_warn_and_inputs_are_checked():
    df = _alt_df(cutoff=250.0)
    assert (df["cens"] == 0).sum() < alt.FEW_FAILURES
    _, cid = alt.fit(df, {"x": "hours", "c": "cens"}, ["tempK"], "weibull", "arrhenius")
    b = alt.use_level_bounds(alt.get_live(cid), USE, "arrhenius")
    assert b["warnings"] and b["warnings"][0].startswith("Only ")
    m = alt.get_live(cid)
    for kwargs, msg in (({"method": "jackknife"}, "Unknown bounds method"), ({"confidence": 1.2}, "at least 0.5"),
                        ({"mission_time": -1}, "positive"), ({"method": "bootstrap", "n_boot": 5}, "between 100")):
        with pytest.raises(FitError, match=msg):
            alt.use_level_bounds(m, USE, "arrhenius", **kwargs)
    with pytest.raises(FitError, match="dimensions"):
        alt.use_level_bounds(m, [300.0, 10.0], "arrhenius")


def test_evaluate_uses_qf_and_carries_wald_bounds(fitted):
    _, m = fitted
    ev = alt.evaluate(m, USE, "arrhenius", ref_stress=[400.0], mission_time=2000.0)
    json.dumps(ev)
    assert ev["metrics"]["b10"] == pytest.approx(float(np.ravel(m.qf(0.1, [USE]))[0]), rel=1e-12)
    assert ev["metrics"]["mission_reliability"] == pytest.approx(float(np.ravel(m.sf([2000.0], [USE]))[0]))
    assert ev["bounds"]["method"] == "wald" and ev["bounds"]["band"]["x"][-1] == pytest.approx(ev["t_max"])
    # The fit's coefficient CIs are SurPyval's param_cb (log scale for beta).
    payload, _ = fitted
    beta = payload["params"][0]
    assert beta["ci"] == pytest.approx(m.param_cb("beta").tolist(), rel=1e-9)


# ---- Service, routes and the compute job --------------------------------------------

@pytest.fixture()
def session(monkeypatch):
    from backend import db

    test_db = mongomock.MongoClient()["reliafy_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    yield test_db


def _save(session, df, mapping, name="Seal ALT"):
    from backend.services import alt as alt_service
    from backend.services import datasets as dsvc

    ds = dsvc.create_dataset(session, "alt.csv", df.to_csv(index=False).encode(), OWNER)
    spec = {"mapping": mapping, "stress_cols": ["tempK"], "stress_labels": ["Temperature (K)"],
            "distribution_id": "weibull", "life_model_id": "arrhenius", "unit": "hours"}
    return alt_service.save_model(session, name, ds, spec, OWNER)


def test_service_lr_refits_a_rehydrated_model_and_bootstrap_is_paid(session):
    from backend.services import alt as alt_service

    doc = _save(session, _alt_df(), {"x": "hours", "c": "cens"})
    alt._STORE.clear()
    alt_service._LIVE.clear()
    code, lr = alt_service.bounds(session, doc.id, OWNER, uid=OWNER, use_stress=USE, method="lr")
    assert code == 200 and lr["method"] == "lr"
    ref = _direct(_alt_df()).quantile_cb(0.1, [USE], bound="lower", method="lr")
    assert lr["b_lives"]["b10"]["lower"] == pytest.approx(float(np.ravel(ref)[0]), rel=1e-6)
    code, body = alt_service.bounds(session, doc.id, OWNER, uid=OWNER, use_stress=USE, method="bootstrap",
                                    entitled=False)
    assert code == 402 and body["code"] == "pro_required"


def test_service_caps_the_rows_of_the_slow_methods(session, monkeypatch):
    from backend.services import alt as alt_service

    doc = _save(session, _alt_df(), {"x": "hours", "c": "cens"})
    monkeypatch.setattr(alt, "MAX_ROWS_LR", 50)
    monkeypatch.setattr(alt, "MAX_ROWS_BOOTSTRAP", 50)
    for method in ("lr", "bootstrap"):
        with pytest.raises(FitError, match="up to 50 data rows"):
            alt_service.bounds(session, doc.id, OWNER, uid=OWNER, use_stress=USE, method=method)
    assert alt_service.bounds(session, doc.id, OWNER, uid=OWNER, use_stress=USE)[0] == 200  # Wald: no cap


def test_bootstrap_queues_a_job_and_the_job_view_shows_its_bounds(session, monkeypatch):
    from backend.services import alt as alt_service
    from backend.services import compute_core, compute_queue
    from backend.services import rbd_jobs

    doc = _save(session, _alt_df(), {"x": "hours", "c": "cens"})
    queued = []
    monkeypatch.setattr(compute_queue, "configured", lambda: True)
    monkeypatch.setattr(compute_queue, "enqueue", lambda job_id, kind, request: queued.append((job_id, kind, request)))
    code, body = alt_service.bounds(session, doc.id, OWNER, uid=OWNER, use_stress=USE, method="bootstrap",
                                    t_max=40000.0)
    assert code == 202 and body["job"]["kind"] == "alt_bounds"
    job_id, kind, request = queued[0]
    assert kind == "alt_bounds" and request["options"]["seed"] == alt.BOOTSTRAP_SEED
    # The same request again shares the job.
    code2, body2 = alt_service.bounds(session, doc.id, OWNER, uid=OWNER, use_stress=USE, method="bootstrap",
                                      t_max=40000.0)
    assert code2 == 202 and body2["job"]["job_id"] == job_id and len(queued) == 1

    result = compute_core.run(kind, request)  # what the compute service would post back
    assert rbd_jobs.apply_callback(session, {"job_id": job_id, "status": "done", "result": result})
    view = rbd_jobs.view(session, rbd_jobs.get(session, job_id), True)
    assert view["status"] == "done" and view["result"]["b_lives"] == result["b_lives"]
    code3, done = alt_service.bounds(session, doc.id, OWNER, uid=OWNER, use_stress=USE, method="bootstrap",
                                     t_max=40000.0)
    assert code3 == 200 and done["b_lives"] == result["b_lives"]


def test_bootstrap_refuses_interval_data_before_queueing(session):
    from backend.services import alt as alt_service

    doc = _save(session, _inspected(_alt_df()), {"xl": "lo", "xr": "hi", "c": "flag"})
    with pytest.raises(FitError, match="Bootstrap bounds aren't available"):
        alt_service.bounds(session, doc.id, OWNER, uid=OWNER, use_stress=USE, method="bootstrap")


def test_routes_fit_interval_data_and_serve_bounds(session, monkeypatch):
    from backend import config
    from backend.auth import get_current_user
    from backend.main import app
    from backend.services import billing as billing_service

    monkeypatch.setattr(config, "BILLING_ENABLED", False)
    app.dependency_overrides[get_current_user] = lambda: {"uid": OWNER, "email": "a@example.org", "name": "A"}
    try:
        client = TestClient(app)
        csv = _inspected(_alt_df()).to_csv(index=False).encode()
        form = {"xl": "lo", "xr": "hi", "c": "flag", "s1": "tempK", "unit": "hours"}
        r = client.post("/api/alt/fit", data=form, files={"file": ("insp.csv", csv, "text/csv")})
        assert r.status_code == 200, r.text
        assert r.json()["spec"]["mapping"] == {"xl": "lo", "xr": "hi", "c": "flag"}
        assert r.json()["results"]["interval_censored"] is True
        r = client.post("/api/alt/models", data={**form, "name": "Inspected", "dataset_id": r.json()["dataset_id"]})
        assert r.status_code == 200, r.text
        mid = r.json()["id"]

        r = client.post(f"/api/alt/models/{mid}/evaluate", json={"use_stress": USE, "mission_time": 2000,
                                                                 "confidence": 0.9})
        assert r.status_code == 200, r.text
        ev = r.json()
        assert ev["bounds"]["confidence"] == 0.9 and ev["bounds_methods"] == ["wald", "lr"]
        assert ev["metrics"]["mission_reliability"] >= ev["bounds"]["mission"]["lower"]

        r = client.post(f"/api/alt/models/{mid}/bounds", json={"use_stress": USE, "method": "lr",
                                                               "t_max": ev["t_max"]})
        assert r.status_code == 200 and r.json()["method"] == "lr"
        r = client.post(f"/api/alt/models/{mid}/bounds", json={"use_stress": USE, "method": "bootstrap"})
        assert r.status_code == 422 and "Bootstrap" in r.json()["detail"]

        monkeypatch.setattr(billing_service, "premium_compute_allowed", lambda *a, **k: False)
        r = client.post("/api/alt/models", data={"x": "hours", "c": "cens", "s1": "tempK", "name": "Exact"},
                        files={"file": ("exact.csv", _alt_df().to_csv(index=False).encode(), "text/csv")})
        r = client.post(f"/api/alt/models/{r.json()['id']}/bounds", json={"use_stress": USE, "method": "bootstrap"})
        assert r.status_code == 402 and r.json()["code"] == "pro_required"
    finally:
        app.dependency_overrides.clear()
