"""Recurrent-event models beyond minimal repair (#65): intensity regression,
imperfect repair, gapped observation windows and failures by cause, each
checked against SurPyval called directly."""

import io
import json
import warnings

import mongomock
import numpy as np
import pandas as pd
import pytest

from backend.tests.test_recurrent import A, _client

CMP_MAP = {"i": "compressor", "x": "hours", "t": "test_end", "mode": "failure_mode"}
PUMP_MAP = {"i": "pump", "x": "hours", "tr": "observed_to", "mode": "cause", "z": ["site", "duty_pct"]}


def _compressors() -> pd.DataFrame:
    from backend.services.samples import _COMPRESSOR_EVENTS_CSV

    return pd.read_csv(io.BytesIO(_COMPRESSOR_EVENTS_CSV))


def _pumps() -> pd.DataFrame:
    from backend.services.samples import _PUMP_REPAIRS_CSV

    return pd.read_csv(io.BytesIO(_PUMP_REPAIRS_CSV))


def _with_end_rows(df, sys_col, time_col, end_col):
    ends = df.groupby(sys_col)[end_col].max()
    x = np.r_[df[time_col].to_numpy(float), ends.to_numpy(float)]
    i = np.r_[df[sys_col].astype(str).to_numpy(), ends.index.astype(str).to_numpy()]
    c = np.r_[np.zeros(len(df)), np.ones(len(ends))].astype(int)
    return x, i, c


def _quiet(fn, *args, **kwargs):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return fn(*args, **kwargs)


# ---- Proportional intensity ----------------------------------------------------

def test_proportional_intensity_matches_surpyval_and_reads_each_covariate():
    from surpyval.recurrent import CrowAMSAA, ProportionalIntensityNHPP

    from backend import recurrent as rec

    df = _pumps()
    payload, cache_id = rec.fit(df, PUMP_MAP, "pi_nhpp", "hours")
    json.dumps(payload, allow_nan=False)
    assert payload["family"] == "regression" and payload["model"]["id"] == "pi_nhpp"

    # SurPyval directly: the text covariate as an indicator against the level
    # most pumps have (five each: alphabetical, Coastal).
    Z = pd.DataFrame({"site: Inland": (df.site == "Inland").astype(float), "duty_pct": df.duty_pct.astype(float)})
    direct = _quiet(ProportionalIntensityNHPP.fit, df.hours.to_numpy(float), Z, i=df.pump.to_numpy(),
                    tr=df.observed_to.to_numpy(float), dist=CrowAMSAA)
    # Each estimate and SurPyval's param_cb (SurPyval 0.23 has no summary()
    # on this model): the baseline in params, the coefficients in coeffs.
    estimate = dict(zip(direct.parameter_names, [*direct.params, *direct.coeffs]))
    by_name = {c["name"]: c for c in payload["coefficients"]}
    for name in ("site: Inland", "duty_pct"):
        assert by_name[name]["coef"] == pytest.approx(estimate[name], rel=1e-6)
        lo = float(np.ravel(direct.param_cb(name, alpha_ci=0.05))[0])
        assert by_name[name]["ratio_ci"][0] == pytest.approx(np.exp(lo), rel=1e-6)
    params = {p["name"]: p for p in payload["params"]}
    assert params["beta"]["value"] == pytest.approx(estimate["beta"], rel=1e-6)
    assert params["beta"]["ci"][0] == pytest.approx(float(np.ravel(direct.param_cb("beta", alpha_ci=0.05))[0]),
                                                    rel=1e-6)

    # Plain readings: inland pumps fail more often, and higher duty too.
    site = by_name["site: Inland"]
    assert site["effect"] == "higher" and "Coastal" in site["reading"] and "×" in site["reading"]
    assert by_name["duty_pct"]["effect"] == "higher" and "% more often" in by_name["duty_pct"]["reading"]
    assert payload["covariates"][0] == {"column": "site", "kind": "category", "reference": "Coastal",
                                        "levels": ["Coastal", "Inland"]}
    # One fitted line per site, the average pump's for the calculator.
    assert [g["label"] for g in payload["mcf"]["groups"]] == ["site Coastal", "site Inland"]
    assert payload["mcf"]["groups"][1]["mcf"][-1] > payload["mcf"]["groups"][0]["mcf"][-1]
    assert payload["growth"] == "deteriorating" and payload["mtbf"] > 0 and payload["rocof_ci"]
    assert payload["trend_tests"] and payload["system_residuals"]
    # Its intensity needs covariates: no overhaul, no "expected by" without them.
    live = rec.get_live(cache_id)
    with pytest.raises(rec.FitError, match="minimal-repair"):
        rec.optimal_overhaul(live, 100, 1000)
    with pytest.raises(rec.FitError, match="covariates"):
        rec.predict(live, 1000)


def test_covariate_errors_are_plain():
    from backend import recurrent as rec

    df = _pumps()
    with pytest.raises(rec.FitError, match="covariate"):
        rec.fit(df, {**PUMP_MAP, "z": []}, "pi_nhpp")
    one = df.assign(site="Coastal")
    with pytest.raises(rec.FitError, match="one value only"):
        rec.fit(one, PUMP_MAP, "pi_nhpp")
    blank = df.copy()
    blank.loc[3, "duty_pct"] = np.nan
    with pytest.raises(rec.FitError, match="blank on 1 event row"):
        rec.fit(blank, PUMP_MAP, "pi_nhpp")


# ---- Imperfect repair ----------------------------------------------------------

@pytest.mark.parametrize("model_id,kijima", [("grp_i", "i"), ("grp_ii", "ii")])
def test_generalized_renewal_matches_surpyval(model_id, kijima):
    from surpyval.recurrent import GeneralizedRenewal

    from backend import recurrent as rec

    df = _compressors()
    payload, cache_id = rec.fit(df, CMP_MAP, model_id, "hours", gof_test=False)
    json.dumps(payload, allow_nan=False)
    x, i, c = _with_end_rows(df, "compressor", "hours", "test_end")
    direct = _quiet(GeneralizedRenewal.fit, x, i=i, c=c, kijima=kijima)
    q = float(direct.params[0])
    rest = payload["restoration"]
    assert rest["parameter"] == "q" and rest["value"] == pytest.approx(q, rel=1e-6)
    assert rest["effectiveness"] == pytest.approx(1 - q, rel=1e-6)
    lo, hi = direct.param_cb("q", alpha_ci=0.05)
    assert rest["effectiveness_ci"] == pytest.approx([1 - hi, 1 - lo], rel=1e-6)
    assert f"{round((1 - q) * 100)}%" in rest["sentence"]

    rt = direct.repair_test()
    verdict = payload["repair_test"]
    assert verdict["perfect"]["p_value"] == pytest.approx(rt.perfect.p_value, rel=1e-6)
    assert verdict["minimal"]["p_value"] == pytest.approx(rt.minimal.p_value, rel=1e-6)
    assert verdict["verdict"] == "partial"  # both rejected on the compressors

    # Each compressor's next failure, from SurPyval's next-failure survival.
    nf = payload["next_failure"]
    assert nf["n_systems"] == 4
    first = nf["units"][0]
    sf = direct.next_failure_sf(np.array([first["median"]]))
    row = list(direct.unit_states().index.astype(str)).index(first["system"])
    assert float(np.ravel(sf[row])[0]) == pytest.approx(0.5, abs=0.01)
    assert first["age"] == 5000 and first["failures"] in (7, 8)
    assert len(nf["curves"]) == 4 and len(nf["curves"][0]["sf"]) == len(nf["x"])
    # No closed-form intensity: the fitted MCF is simulated, and no overhaul.
    assert payload["mcf"]["fitted"]["simulated"] is True
    live = rec.get_live(cache_id)
    with pytest.raises(rec.FitError, match="minimal-repair"):
        rec.optimal_overhaul(live, 100, 1000)
    # Predictions start from each system's history, so it isn't serialised.
    assert rec.serialize_live(cache_id) is None
    out = rec.next_failure(live, 0.0, within=[500.0])
    assert 0 < out["within"][0]["prob_failure"] < 1 and out["mean_time_to_next_failure"] > 0


def test_ara_ari_and_g1_options_and_words():
    from surpyval.recurrent import ARA, ARI, GeneralizedOneRenewal

    from backend import recurrent as rec

    df = _compressors()
    x, i, c = _with_end_rows(df, "compressor", "hours", "test_end")

    ara, _ = rec.fit(df, CMP_MAP, "ara", "hours", gof_test=False, options={"m": "3"})
    direct = _quiet(ARA.fit, x, i=i, c=c, m=3)
    assert ara["options"] == {"m": 3} and "ARA3" in ara["model"]["name"]
    assert ara["restoration"]["value"] == pytest.approx(float(direct.params[0]), rel=1e-6)
    assert "last 3 repairs" in ara["restoration"]["sentence"]

    ari, _ = rec.fit(df, CMP_MAP, "ari", "hours", gof_test=False, options={"m": "all", "baseline": "crow_amsaa"})
    direct = _quiet(ARI.fit, x, i=i, c=c, m=np.inf)
    assert ari["options"] == {"baseline": "crow_amsaa", "m": "all"}
    assert ari["restoration"]["value"] == pytest.approx(float(direct.params[0]), rel=1e-6)
    assert "failure rate" in ari["restoration"]["sentence"]
    assert ari["repair_test"]["perfect"]["hypothesis"] == "maximal repair"

    g1, _ = rec.fit(df, CMP_MAP, "g1", "hours", gof_test=False)
    direct = _quiet(GeneralizedOneRenewal.fit, x, i=i, c=c)
    assert g1["restoration"]["ratio"] == pytest.approx(1 + float(direct.params[0]), rel=1e-6)
    assert "shrinks" in g1["restoration"]["sentence"]  # the compressors deteriorate
    assert g1["repair_test"]["minimal"] is None

    with pytest.raises(rec.FitError, match="memory"):
        rec.fit(df, CMP_MAP, "ara", options={"m": "0"})
    with pytest.raises(rec.FitError, match="baseline"):
        rec.fit(df, CMP_MAP, "ari", options={"baseline": "weibull"})


# ---- Failures by cause -----------------------------------------------------------

def test_by_cause_matches_cause_specific_mcf_and_nhpp():
    from surpyval.recurrent import CauseSpecificMCF, CauseSpecificNHPP

    from backend import recurrent as rec

    df = _compressors()
    payload, _ = rec.fit(df, CMP_MAP, "crow_amsaa", "hours", gof_test=False)
    bc = payload["by_cause"]
    assert [c["label"] for c in bc["causes"]] == ["valve", "bearing", "seal", "electrical"]
    assert sum(c["failures"] for c in bc["causes"]) == 30

    x, i, e, tr = (df.hours.to_numpy(float), df.compressor.to_numpy(), df.failure_mode.to_numpy(object),
                   df.test_end.to_numpy(float))
    mcf = CauseSpecificMCF.fit(x, i=i, e=e, tr=tr)
    para = _quiet(CauseSpecificNHPP.fit, x, i=i, e=e, tr=tr)
    valve = bc["causes"][0]
    assert valve["mcf"]["mcf"] == pytest.approx(list(mcf.models["valve"].mcf_hat))
    cb = mcf.mcf_cb(np.asarray(valve["mcf"]["x"]), "valve", alpha_ci=0.05)
    assert valve["mcf"]["upper"] == pytest.approx(list(np.max(cb, axis=1)))
    assert valve["fit"]["beta"] == pytest.approx(float(para.models["valve"].params[1]), rel=1e-6)
    assert valve["fit"]["growth"] == "deteriorating"
    # The causes' likelihoods are separate: the joint AIC is the sum.
    assert bc["aic"] == pytest.approx(sum(m.aic() for m in para.models.values()), rel=1e-6)

    # A blank cause on a failure is counted as such, not dropped.
    blank = df.copy()
    blank.loc[0, "failure_mode"] = None
    labels = [c["label"] for c in rec.fit(blank, CMP_MAP, "hpp", gof_test=False)[0]["by_cause"]["causes"]]
    assert "No cause given" in labels


# ---- Gapped observation windows --------------------------------------------------

def test_windows_by_hand_and_from_columns_match_surpyval():
    from surpyval.recurrent import CrowAMSAA, NonParametricCounting

    from backend import recurrent as rec
    from backend import recurrent_models as extra

    df = _compressors()
    # CMP-1 was out of service from 2,100 to 2,700 hours: drop its failure in the gap.
    gapped = df[~((df.compressor == "CMP-1") & (df.hours > 2100) & (df.hours <= 2700))]
    text = "CMP-1, 0, 2100\nCMP-1, 2700, 5000"
    payload, _ = rec.fit(gapped, CMP_MAP, "crow_amsaa", "hours", gof_test=False, windows=text)
    windows = {s: [(0.0, 5000.0)] for s in ("CMP-2", "CMP-3", "CMP-4")}
    windows["CMP-1"] = [(0.0, 2100.0), (2700.0, 5000.0)]
    direct = CrowAMSAA.fit(gapped.hours.to_numpy(float), i=gapped.compressor.to_numpy(), windows=windows)
    assert [p["value"] for p in payload["params"]] == pytest.approx(list(direct.params), rel=1e-6)
    npc = NonParametricCounting.fit(gapped.hours.to_numpy(float), i=gapped.compressor.to_numpy(), windows=windows)
    assert payload["mcf"]["observed"]["mcf"] == pytest.approx(list(npc.mcf_hat))
    assert payload["windows"]["systems_with_gaps"] == 1 and payload["windows"]["gap_time"] == pytest.approx(600)
    assert payload["end_of_observation"] == 5000
    assert payload["by_cause"]["causes"] == [] and "windows" in payload["by_cause"]["reason"]

    # The same windows from two columns; a row with no failure time is a window
    # with no failures in it.
    cols = gapped.assign(w_start=0.0, w_end=5000.0)
    cols.loc[cols.compressor == "CMP-1", "w_end"] = 2100.0
    extra_row = {"compressor": "CMP-1", "hours": None, "test_end": 5000, "failure_mode": None,
                 "w_start": 2700.0, "w_end": 5000.0}
    cols = pd.concat([cols, pd.DataFrame([extra_row])], ignore_index=True)
    # CMP-1's failures after the gap sit in the 2,700-5,000 window.
    cols.loc[(cols.compressor == "CMP-1") & (cols.hours > 2700), ["w_start", "w_end"]] = [2700.0, 5000.0]
    by_cols, _ = rec.fit(cols, {**CMP_MAP, "ws": "w_start", "we": "w_end"}, "crow_amsaa", gof_test=False)
    assert [p["value"] for p in by_cols["params"]] == pytest.approx(list(direct.params), rel=1e-6)

    with pytest.raises(rec.FitError, match="overlap"):
        extra.windows_from(df, CMP_MAP, "A, 0, 10\nA, 5, 20")
    with pytest.raises(rec.FitError, match="system CMP-1"):
        rec.fit(df, CMP_MAP, "crow_amsaa", windows="CMP-1, 0, 2000\nCMP-1, 2700, 5000")  # 2,050 h is in the gap
    with pytest.raises(rec.FitError, match="Observation gaps"):
        rec.fit(gapped, CMP_MAP, "grp_i", windows=text)
    with pytest.raises(rec.FitError, match="system, start, end"):
        extra.parse_windows("CMP-1 0 2100")


def test_crow_amsaa_restarts_a_search_that_wanders_off():
    from surpyval.recurrent import CrowAMSAA

    from backend import recurrent as rec

    df = _pumps()
    payload, _ = rec.fit(df, {k: v for k, v in PUMP_MAP.items() if k != "z"}, "crow_amsaa", gof_test=False)
    # The same fit on times rescaled to the unit interval (whose scale maps back).
    s = float(df.hours.max())
    unit = CrowAMSAA.fit(df.hours.to_numpy(float) / s, i=df.pump.to_numpy(), tr=df.observed_to.to_numpy(float) / s)
    alpha, beta = (p["value"] for p in payload["params"])
    assert alpha == pytest.approx(unit.params[0] * s, rel=1e-4) and beta == pytest.approx(unit.params[1], rel=1e-4)
    assert np.isfinite(payload["mtbf"])


# ---- API, persistence, samples, fleets --------------------------------------------

def test_api_fit_and_save_new_models(monkeypatch):
    from backend.auth import get_current_user
    from backend.services.samples import _PUMP_REPAIRS_CSV

    test_db = mongomock.MongoClient()["reliafy_test"]
    client, app = _client(monkeypatch, test_db)
    files = {"file": ("pumps.csv", _PUMP_REPAIRS_CSV, "text/csv")}
    form = {"i": "pump", "x": "hours", "tr": "observed_to", "mode": "cause", "unit": "hours"}
    try:
        app.dependency_overrides[get_current_user] = lambda: {"uid": A, "email": "a@x.com", "name": "A"}
        opts = client.get("/api/recurrent/options").json()
        assert {m["family"] for m in opts["models"]} == {"nhpp", "regression", "renewal"}

        r = client.post("/api/recurrent/fit", data={**form, "model": "pi_nhpp", "z": ["site", "duty_pct"],
                                                    "baseline": "duane"}, files=files)
        assert r.status_code == 200, r.text
        res = r.json()["results"]
        assert r.json()["spec"]["mapping"]["z"] == ["site", "duty_pct"]
        assert res["baseline"]["id"] == "duane" and len(res["coefficients"]) == 2

        r = client.post("/api/recurrent/models", data={**form, "name": "Pumps GRP", "model": "grp_ii"},
                        files=files)
        assert r.status_code == 200, r.text
        mid = r.json()["id"]
        detail = client.get(f"/api/recurrent/models/{mid}").json()
        assert detail["results"]["restoration"] and detail["results"]["by_cause"]["causes"]
        r = client.post(f"/api/recurrent/models/{mid}/overhaul", json={"cost_repair": 100, "cost_overhaul": 1000})
        assert r.status_code == 422 and "minimal-repair" in r.json()["detail"]
        assert client.post(f"/api/recurrent/models/{mid}/predict", json={"horizon": 4000}).json()[
            "expected_events"] > 0

        # Windows as JSON, on a minimal-repair model.
        windows = json.dumps({"P-01": [[0, 4000], [5000, 8760]]})
        r = client.post("/api/recurrent/fit", data={**form, "model": "crow_amsaa", "windows": windows},
                        files=files)
        assert r.status_code == 200, r.text
        assert r.json()["spec"]["windows"] == {"P-01": [[0.0, 4000.0], [5000.0, 8760.0]]}
        assert r.json()["results"]["windows"]["systems_with_gaps"] == 1
        r = client.post("/api/recurrent/fit", data={**form, "model": "crow_amsaa", "windows": "{bad"},
                        files=files)
        assert r.status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_older_model_with_a_cause_column_gets_by_cause_once():
    from backend import recurrent as rec
    from backend.services import datasets as ds_service
    from backend.services import recurrent as svc
    from backend.services.samples import _COMPRESSOR_EVENTS_CSV

    db = mongomock.MongoClient()["reliafy_test"]
    dataset = ds_service.create_dataset(db, "cmp.csv", _COMPRESSOR_EVENTS_CSV, A)
    spec = {"mapping": CMP_MAP, "model_id": "crow_amsaa", "unit": "hours"}
    doc = svc.save_model(db, "Old", dataset, spec, A)
    old = {k: v for k, v in doc.results.items() if k != "by_cause"}
    db.recurrent_models.update_one({"_id": doc.id}, {"$set": {"results": old}})
    fresh = svc.ensure_diagnostics(db, svc.get_model(db, doc.id, A))
    assert len(fresh.results["by_cause"]["causes"]) == 4
    assert "by_cause" in db.recurrent_models.find_one({"_id": doc.id})["results"]
    assert rec.MODELS  # the minimal-repair registry is unchanged


def test_samples_seed_the_new_models(monkeypatch):
    from backend import config
    from backend.services import samples

    monkeypatch.setattr(config, "SEED_SAMPLES", True)
    db = mongomock.MongoClient()["reliafy_test"]
    samples.seed_samples(db)
    pump = db.recurrent_models.find_one({"_id": "sample-rec-pumps-pi"})["results"]
    site = next(c for c in pump["coefficients"] if c["name"] == "site: Inland")
    assert site["effect"] == "higher" and pump["growth"] == "deteriorating"
    assert [c["label"] for c in pump["by_cause"]["causes"]][0] == "seal"
    grp = db.recurrent_models.find_one({"_id": "sample-rec-compressors-grp"})["results"]
    assert grp["repair_test"]["verdict"] == "partial" and 0.7 < grp["restoration"]["effectiveness"] < 0.9
    assert grp["gof_test"]["adequate"] is True


def test_fleet_refuses_a_covariate_or_imperfect_repair_model():
    from backend.services import datasets as ds_service
    from backend.services import fleet as fleet_service
    from backend.services import recurrent as svc
    from backend.services.samples import _COMPRESSOR_EVENTS_CSV

    db = mongomock.MongoClient()["reliafy_test"]
    dataset = ds_service.create_dataset(db, "cmp.csv", _COMPRESSOR_EVENTS_CSV, A)
    doc = svc.save_model(db, "GRP", dataset, {"mapping": CMP_MAP, "model_id": "grp_i", "unit": "hours"}, A)
    with pytest.raises(fleet_service.FleetValidationError, match="minimal-repair"):
        fleet_service.create_fleet(db, "Fleet", doc.id, A, model_kind="recurrent")
