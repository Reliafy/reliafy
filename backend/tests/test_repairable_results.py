"""Repairable-model results checked against known processes: three data
sets made here from a known truth (a fleet with three bad actors, compressors
under Kijima I repair, a field trial at two sites with staggered ends).

- Duane intervals equal Crow-AMSAA's (the same process and likelihood);
- the imperfect-repair verdict follows the restoration interval;
- fleet forecasts give a bad actor its own rate, carry the fit's uncertainty
  in their range, and take imperfect-repair models (simulation);
- the Calculator's bounds, beyond the data too, and per covariate level;
- a growth projection of a trial whose units ended at different times;
- a fit with no end of record says so;
- models saved before the 90% rule read at 90%, without rewriting them.
"""

import matplotlib

matplotlib.use("Agg")

import mongomock  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402

from backend.tests.test_fleet import client  # noqa: E402,F401 - a fixture

A = "user-a"

FLEET_MAP = {"i": "truck", "x": "hours", "tr": "observed_to"}
CMP_MAP = {"i": "compressor", "x": "hours", "tr": "records_end"}
TRIAL_MAP = {"i": "unit", "x": "hours", "tr": "trial_end", "mode": "mode"}


def _data():
    """The three data sets, from one seeded generator (in this order)."""
    rng = np.random.default_rng(23)
    trucks = [f"HT-{k:02d}" for k in range(1, 13)]
    bad = {"HT-04", "HT-09", "HT-11"}
    ends = dict(zip(trucks, [16400, 14200, 18000, 15600, 12000, 17200, 13300, 15000, 16800, 11500, 14800, 17600]))
    rows = []
    for tk in trucks:
        eta, T, s = (2000.0 if tk in bad else 3000.0), ends[tk], 0.0
        while True:
            s += rng.exponential()
            t = eta * s ** (1 / 1.6)
            if t > T:
                break
            rows.append((tk, round(t), T))
    fleet = pd.DataFrame(rows, columns=["truck", "hours", "observed_to"])
    comps = [f"CMP-{k}" for k in range(1, 6)]
    cend = dict(zip(comps, [12000, 11000, 12000, 9500, 10500]))
    rows = []
    for cp in comps:
        v = t = 0.0
        while True:
            x = 2500.0 * ((v / 2500.0) ** 2.4 - np.log(rng.uniform())) ** (1 / 2.4) - v
            t += x
            if t > cend[cp]:
                break
            rows.append((cp, round(t), cend[cp]))
            v += 0.6 * x
    cmp = pd.DataFrame(rows, columns=["compressor", "hours", "records_end"])
    units = [f"PD-{k:02d}" for k in range(1, 11)]
    site = {u: ("Inland" if k % 2 == 1 else "Coastal") for k, u in enumerate(units)}
    uend = dict(zip(units, [4000, 4000, 3800, 3800, 3500, 3500, 3200, 3200, 3000, 3000]))
    rows = []
    for u in units:
        lam, s = 0.12 * (2.0 if site[u] == "Inland" else 1.0), 0.0
        while True:
            s += rng.exponential()
            t = (s / lam) ** (1 / 0.55)
            if t > uend[u]:
                break
            rows.append((u, site[u], round(t), uend[u],
                         rng.choice(["seal", "controller", "bearing", "connector"], p=[0.4, 0.3, 0.15, 0.15])))
    trial = pd.DataFrame(rows, columns=["unit", "site", "hours", "trial_end", "mode"])
    return fleet, cmp, trial


FLEET, CMP, TRIAL = _data()


def _fit(df, mapping, model_id="crow_amsaa"):
    from backend import recurrent as rec

    payload, cid = rec.fit(df, mapping, model_id, "hours", gof_test=False)
    return payload, rec.get_live(cid)


# ---- Duane = Crow-AMSAA ---------------------------------------------------------------

def test_duane_interval_is_crow_amsaas():
    duane, _ = _fit(FLEET, FLEET_MAP, "duane")
    crow, _ = _fit(FLEET, FLEET_MAP)
    assert duane["beta"] == pytest.approx(crow["beta"], rel=1e-4)
    assert duane["beta_ci"] == pytest.approx(crow["beta_ci"], rel=1e-4)
    # Pinned: 90% 1.37–1.75 (SurPyval 0.26's own Duane said 1.51–1.58).
    assert duane["beta_ci"] == pytest.approx([1.373, 1.747], abs=2e-3)
    assert duane["demonstrated_mtbf"]["lower"] == pytest.approx(crow["demonstrated_mtbf"]["lower"], rel=1e-4)
    assert duane["demonstrated_mtbf"]["lower"] == pytest.approx(520.0, abs=1.0)


def test_duane_workaround_is_gated_on_the_library_version(monkeypatch):
    import importlib.metadata as md

    from backend import recurrent as rec

    monkeypatch.setattr(md, "version", lambda name: "0.27")
    assert rec.duane_needs_twin() is False
    monkeypatch.setattr(md, "version", lambda name: "0.26")
    assert rec.duane_needs_twin() is True


# ---- Imperfect repair: the verdict follows the interval -----------------------------------

@pytest.mark.parametrize("model_id", ["grp_i", "grp_ii", "ara", "ari"])
def test_verdict_never_names_an_end_the_interval_rules_out(model_id):
    r, _ = _fit(CMP, CMP_MAP, model_id)
    rest, rt = r["restoration"], r["repair_test"]
    lo, hi = rest["effectiveness_ci"]
    assert rest["ci_method"] == "lr"
    if rt["verdict"] == "minimal":
        assert lo <= 0
    if rt["verdict"] in ("perfect", "maximal"):
        assert hi >= 1
    if rt["verdict"] == "partial":
        assert lo > 0 and hi < 1
    assert f"{round(max(rest['effectiveness'], 0) * 100)}%" in rt["sentence"]


def test_kijima_i_says_what_it_restores_not_as_bad_as_old():
    r, _ = _fit(CMP, CMP_MAP, "grp_i")
    rest, rt = r["restoration"], r["repair_test"]
    # Truth: each repair restores 40% of the age gained; the estimate is about half.
    assert 0.3 < rest["effectiveness"] < 0.7
    assert rt["verdict"] != "minimal"
    assert "Crow-AMSAA" not in rt["sentence"]
    assert "restores about" in rest["sentence"] and "q = " in rest["sentence"]


# ---- Fleet forecasts ------------------------------------------------------------------------

def _truth_fleet_count(h=6000.0, sims=4000):
    """The true process's failures over the next ``h`` from each truck's end."""
    rng = np.random.default_rng(5)
    ends = FLEET.groupby("truck").observed_to.max()
    mean = sum(((e + h) / eta) ** 1.6 - (e / eta) ** 1.6
               for tk, e in ends.items() for eta in [2000.0 if tk in {"HT-04", "HT-09", "HT-11"} else 3000.0])
    return float(np.mean(rng.poisson(mean, sims)))


def test_bad_actors_get_their_own_rate_and_truth_is_in_range():
    from backend import recurrent_forecast as rf

    _, live = _fit(FLEET, FLEET_MAP)
    ends = FLEET.groupby("truck").observed_to.max()
    fc = rf.nhpp_forecast(live, ends.values, np.full(12, 500.0), 12, names=list(ends.index))
    by = dict(zip(ends.index, fc["per_item"]))
    assert by["HT-11"]["rate_factor"] > 1.5 and by["HT-11"]["expected"] > 15  # truth about 18
    assert by["HT-03"]["rate_factor"] < 1
    truth = _truth_fleet_count()
    assert fc["interval"][0] <= truth <= fc["interval"][1]
    # Wider than the Poisson range given the model (106–134 at 80%, 104–137 at 90%).
    assert fc["interval"][0] < 104 and fc["interval"][1] > 137
    assert fc["units"]["matched"] == 12


def test_forecast_range_carries_parameter_uncertainty():
    """The Crow-AMSAA forecast of the compressors against an independent
    simulation over the fit's covariance (20,000 draws)."""
    from scipy.stats import multivariate_normal  # noqa: F401 - the reference below uses numpy

    from backend import recurrent_forecast as rf

    _, live = _fit(CMP, CMP_MAP)
    ages = np.array([12000.0, 11000.0, 12000.0, 9500.0, 10500.0])
    h = 667.0 * 12
    fc = rf.nhpp_forecast(live, ages, np.full(5, 667.0), 12)
    rng = np.random.default_rng(11)
    p = np.asarray(live.params, dtype=float)
    cov = np.asarray(live.covariance(), dtype=float) / np.outer(p, p)
    P = np.exp(rng.multivariate_normal(np.log(p), cov, 20000))
    lam = lambda t: (t[None, :] / P[:, [0]]) ** P[:, [1]]  # noqa: E731
    counts = rng.poisson((lam(ages + h) - lam(ages)).sum(axis=1))
    lo, hi = np.quantile(counts, [0.05, 0.95])
    assert fc["interval"][0] == pytest.approx(lo, rel=0.06)
    assert fc["interval"][1] == pytest.approx(hi, rel=0.06)
    assert fc["interval_method"] == "simulated"


def test_imperfect_repair_fleet_forecast(monkeypatch):
    from backend.services import datasets as ds_service
    from backend.services import fleet as fs
    from backend.services import recurrent as svc

    db = mongomock.MongoClient()["reliafy_test"]
    dataset = ds_service.create_dataset(db, "cmp.csv", CMP.to_csv(index=False).encode(), A)
    doc = svc.save_model(db, "GRP", dataset, {"mapping": CMP_MAP, "model_id": "grp_i", "unit": "hours"}, A)
    fleet = fs.create_fleet(db, "Compressors", doc.id, A, "recurrent")
    items = [{"name": n, "current_use": a} for n, a in
             zip(["CMP-1", "CMP-2", "CMP-3", "CMP-4", "CMP-5"], [12000, 11000, 12000, 9500, 10500])]
    fleet = fs.replace_items(db, fleet.id, {"periods": 12, "default_rate": 667}, items, A)
    out = fs.compute(db, fleet, [A])
    assert out["status"] == "ok" and out["family"] == "renewal"
    # The true process gives about 236 next year; the fit's own simulation about the same.
    assert 200 < out["expected"] < 270
    assert out["interval"][0] < 236 < out["interval"][1]
    assert all("history" in r for r in out["per_item"])
    assert sum(out["per_period"]) == pytest.approx(out["expected"], rel=1e-9)


def test_covariate_models_are_left_out_of_fleets_with_a_reason():
    from backend.services import datasets as ds_service
    from backend.services import fleet as fs
    from backend.services import recurrent as svc

    db = mongomock.MongoClient()["reliafy_test"]
    dataset = ds_service.create_dataset(db, "trial.csv", TRIAL.to_csv(index=False).encode(), A)
    doc = svc.save_model(db, "PI", dataset, {"mapping": {**TRIAL_MAP, "z": ["site"]}, "model_id": "pi_nhpp",
                                             "unit": "hours"}, A)
    with pytest.raises(fs.FleetValidationError, match="covariate"):
        fs.create_fleet(db, "F", doc.id, A, "recurrent")


# ---- The Calculator ---------------------------------------------------------------------------

def test_calculator_bounds_match_surpyval():
    from backend import recurrent_forecast as rf

    r, live = _fit(FLEET, FLEET_MAP)
    out = rf.calculate(live, r, 18000.0, start=16000.0)
    assert out["expected"]["value"] == pytest.approx(19.23, abs=0.01)
    assert out["expected"]["ci"] == pytest.approx(sorted(live.cif_cb(np.array([18000.0]), alpha_ci=0.1).ravel()),
                                                  rel=1e-9)
    assert out["mtbf"]["lower"] == pytest.approx(r["demonstrated_mtbf"]["lower"], rel=1e-6)
    w = out["window"]
    assert w["expected"] == pytest.approx(3.207, abs=0.001)
    assert w["ci"][0] < w["expected"] < w["ci"][1]


def test_calculator_imperfect_repair_beyond_the_data():
    from backend import recurrent_forecast as rf

    r, live = _fit(CMP, CMP_MAP, "grp_i")
    out = rf.calculate(live, r, 20000.0, start=12000.0)  # the data end at 12,000 h
    assert out["expected"]["value"] > 0 and out["window"]["expected"] > 0
    lo, hi = out["window"]["ci"]
    assert lo < out["window"]["expected"] < hi
    assert out["mtbf"]["value"] is None and out["rate_reason"]


def test_calculator_per_site_and_headline_by_level():
    from backend import recurrent_forecast as rf

    r, live = _fit(TRIAL, {**TRIAL_MAP, "z": ["site"]}, "pi_nhpp")
    coastal = rf.calculate(live, r, 6000.0, profile={"site": "Coastal"})
    inland = rf.calculate(live, r, 6000.0, profile={"site": "Inland"})
    # By hand from SurPyval: 730.7 h and 306.6 h at launch.
    assert coastal["mtbf"]["value"] == pytest.approx(730.7, rel=0.01)
    assert inland["mtbf"]["value"] == pytest.approx(306.6, rel=0.01)
    assert coastal["mtbf"]["lower"] < coastal["mtbf"]["value"]
    labels = {g["label"]: g["mtbf"] for g in r["rates_by_group"]}
    assert labels["site Coastal"] > labels["site Inland"]
    with pytest.raises(Exception, match="isn't a level"):
        rf.calculate(live, r, 6000.0, profile={"site": "Mars"})


def test_from_now_and_overhaul_range():
    from backend import recurrent as rec
    from backend import recurrent_forecast as rf

    _, live = _fit(FLEET, FLEET_MAP)
    now = rf.from_now(live, 6000.0)
    assert now["interval"][0] < now["expected"] < now["interval"][1] and now["systems"][0]["system"] == "HT-11"
    out = rec.optimal_overhaul(live, 18000, 90000)
    lo, hi = out["interval_range"]["ci"]
    assert lo < out["optimal"]["interval"] < hi


# ---- Growth projection with staggered ends ------------------------------------------------------

def test_growth_projection_of_a_staggered_trial():
    from backend import recurrent as rec

    fef, bc = {"seal": 0.7, "connector": 0.7}, ["controller"]
    auto = rec.growth_projection(TRIAL, TRIAL_MAP, fef, bc=bc, unit="hours")
    typed = rec.growth_projection(TRIAL, TRIAL_MAP, fef, bc=bc, test_end=3000, unit="hours")
    for r in (auto, typed):
        assert r["T"] == 3000.0 and r["common_end"]["T"] == 3000.0
        assert r["projected"]["mtbf"] == pytest.approx(776.0, abs=1.0)
        assert r["demonstrated"]["mtbf"] == pytest.approx(319.7, abs=0.5)
    later = rec.growth_projection(TRIAL, TRIAL_MAP, fef, bc=bc, test_end=3500, unit="hours")
    assert later["common_end"]["excluded_systems"] and "left out" in later["common_end"]["text"]
    with pytest.raises(rec.FitError, match="reaches"):
        rec.growth_projection(TRIAL, TRIAL_MAP, fef, bc=bc, test_end=9000)


# ---- End of record ---------------------------------------------------------------------------

def test_no_record_end_is_warned():
    with_end, _ = _fit(FLEET, FLEET_MAP)
    without, _ = _fit(FLEET, {"i": "truck", "x": "hours"})
    assert not with_end.get("warnings")
    assert [w["id"] for w in without["warnings"]] == ["no_record_end"]
    assert without["beta"] > with_end["beta"]  # the fit changes without it: why the warning


def test_by_cause_reads_at_its_level():
    r, _ = _fit(TRIAL, TRIAL_MAP)
    assert r["by_cause"]["ci_level"] == 0.9
    assert all(c["fit"]["ci_level"] == 0.9 for c in r["by_cause"]["causes"])


# ---- Saved before the 90% rule ---------------------------------------------------------------

def test_saved_at_95_reads_at_90_without_rewriting():
    from backend.services import datasets as ds_service
    from backend.services import recurrent as svc

    db = mongomock.MongoClient()["reliafy_test"]
    dataset = ds_service.create_dataset(db, "fleet.csv", FLEET.to_csv(index=False).encode(), A)
    doc = svc.save_model(db, "Fleet", dataset, {"mapping": FLEET_MAP, "model_id": "crow_amsaa", "unit": "hours"}, A)
    fresh_ci = doc.results["beta_ci"]
    old = {k: v for k, v in doc.results.items() if k != "ci_level"}
    old["beta_ci"] = [1.34, 1.79]  # as a 95% save stored it
    db.recurrent_models.update_one({"_id": doc.id}, {"$set": {"results": old}})
    stored = svc.get_model(db, doc.id, A)
    shown = svc.current_results(db, stored)
    assert shown.results["ci_level"] == 0.9 and shown.results["beta_ci"] == pytest.approx(fresh_ci, rel=1e-6)
    assert shown.results["recomputed_on_read"] is True
    raw = db.recurrent_models.find_one({"_id": doc.id})
    assert "ci_level" not in raw["results"] and raw["results"]["beta_ci"] == [1.34, 1.79]


# ---- API ---------------------------------------------------------------------------------------

def test_calculate_and_from_now_routes(client):  # noqa: F811 - the fixture
    client.act_as("user-a")
    files = {"file": ("fleet.csv", FLEET.to_csv(index=False).encode(), "text/csv")}
    form = {"name": "Fleet", "i": "truck", "x": "hours", "tr": "observed_to", "unit": "hours"}
    saved = client.post("/api/recurrent/models", data=form, files=files)
    assert saved.status_code == 200, saved.text
    mid = saved.json()["id"]
    calc = client.post(f"/api/recurrent/models/{mid}/calculate", json={"t": 18000, "start": 16000})
    assert calc.status_code == 200 and calc.json()["window"]["ci"]
    bad = client.post(f"/api/recurrent/models/{mid}/calculate", json={"t": -1})
    assert bad.status_code == 422
    now = client.post(f"/api/recurrent/models/{mid}/from-now", json={"horizon": 6000})
    assert now.status_code == 200 and now.json()["n_systems"] == 12
