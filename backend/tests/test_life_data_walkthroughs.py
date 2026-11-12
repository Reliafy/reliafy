"""Wrong numbers and blocked jobs from the 12 Nov 2026 non-repairable life-data walkthroughs.

Each test runs the walkthrough's own sheet (``walkthrough_data``) and checks the number the app now
gives against SurPyval or the hand count the walkthrough made.
"""

import matplotlib

matplotlib.use("Agg")

import io

import mongomock
import numpy as np
import pandas as pd
import pytest
import surpyval as sp

from backend import competing_risks as cr
from backend import fitting, life_bounds, life_requirement
from backend.services import bayes_life as bl
from backend.services import compare_groups as cg
from backend.services import datasets as datasets_service
from backend.services import strategy as strategy_service
from backend.tests import walkthrough_data as w


def _df(text: str) -> pd.DataFrame:
    return pd.read_csv(io.StringIO(text))


# ---- W11: Compare groups reads the status column the fit reads -----------------------------

def test_status_words_and_phrases_are_read_by_their_meaning():
    code = datasets_service.status_code
    assert code("Failed") == 0 and code("Removed, OK") == 1 and code("Running") == 1
    assert code("Found failed") == 0 and code("OK at last check") == 1
    assert code("Not failed") is None and code("Failed, OK") is None and code("") is None


def test_compare_groups_reads_a_text_status_column_as_the_fit_does():
    df = _df(w.BEARINGS)
    data = cg.prepare(df, time_column="Run hours", group_column="Supplier", censor_column="Status")
    assert data["read_as"]["failed"] == 35 and data["read_as"]["running"] == 25
    assert data["read_as"]["meanings"] == {"Removed, OK": "still running", "Failed": "failed"}
    out = cg.compare_groups(data, group_column="Supplier", unit="hours")
    # The walkthrough's hand check: log-rank 5.50 (p 0.019), B averages 1,273 h more over 6,630 h.
    assert out["logrank"]["statistic"] == pytest.approx(5.501, abs=1e-3)
    d = out["rmst_differences"][0]
    assert d["difference"] == pytest.approx(1273.0, abs=1.0)
    assert out["read_as"]["failed"] == 35
    # The same with a word map, as the page's buttons send it.
    mapped = cg.prepare(df, time_column="Run hours", group_column="Supplier", censor_column="Status",
                        c_map={"Failed": 0, "Removed, OK": 1})
    assert np.array_equal(mapped["c"], data["c"])


def test_compare_groups_never_counts_running_units_as_failed_by_default():
    df = _df(w.BEARINGS)
    col, note, flip = cg.auto_status(df, time_column="Run hours", group_column="Supplier", censor_column=None,
                                     cause_column=None)
    assert col == "Status" and "Status" in note and flip is False
    # Said in so many words, every row is a failure (the old default, now only on request).
    assert cg.auto_status(df, time_column="Run hours", group_column="Supplier", censor_column=None,
                          cause_column=None, all_failed=True) == (None, None, False)
    # A 0/1 flag named "failed" is 1 = failed: flipped.
    flags = pd.DataFrame({"t": [1, 2, 3, 4], "g": ["a", "a", "b", "b"], "failed": [1, 0, 1, 1]})
    assert cg.auto_status(flags, time_column="t", group_column="g", censor_column=None, cause_column=None)[0::2] \
        == ("failed", True)


def test_a_status_word_with_no_meaning_is_asked_about_in_words():
    df = _df(w.BEARINGS).replace({"Removed, OK": "Pending"})
    with pytest.raises(cg.CompareGroupsError, match="Say whether “Pending”"):
        cg.prepare(df, time_column="Run hours", group_column="Supplier", censor_column="Status")


def test_the_dataset_profile_names_the_status_column_and_its_values(monkeypatch):
    df = _df(w.BEARINGS)
    monkeypatch.setattr(datasets_service, "load_dataframe", lambda _ds: df)
    prof = datasets_service.profile(type("D", (), {"measurements": None})())
    assert prof["status_column"] == "Status"
    assert prof["values"]["Status"] == {"Failed": 35, "Removed, OK": 25}
    assert "Bearing" not in prof["values"]  # one value per row: not a few-valued column


@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", True)
    test_db = mongomock.MongoClient()["reliafy_walkthroughs_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    app.dependency_overrides[get_current_user] = lambda: {"uid": "user-a", "email": "a@example.org"}
    tc = TestClient(app)
    tc.db = test_db
    try:
        yield tc
    finally:
        app.dependency_overrides.clear()


def test_the_compare_endpoint_reads_the_status_column_unless_told_every_row_failed(client):
    ds = client.post("/api/datasets/paste", json={"name": "Bearings", "content": w.BEARINGS}).json()
    url = f"/api/datasets/{ds['id']}/compare-groups"
    body = {"time_column": "Run hours", "group_column": "Supplier", "unit": "hours"}
    out = client.post(url, json=body).json()
    # The page's old default counted the 25 running bearings as failed: +916 h, not +1,273 h.
    assert out["read_as"]["failed"] == 35 and out["read_as"]["status_column"] == "Status"
    assert out["rmst_differences"][0]["difference"] == pytest.approx(1273.0, abs=1.0)
    assert any("Status" in n for n in out["notes"])
    every = client.post(url, json={**body, "all_failed": True}).json()
    assert every["read_as"]["failed"] == 60 and every["rmst_differences"][0]["difference"] == pytest.approx(916, abs=1)
    words = client.post(url, json={**body, "censor_column": "Status", "c_map": {"Failed": 0, "Removed, OK": 1}})
    assert words.status_code == 200 and words.json()["read_as"]["running"] == 25


# ---- W12: competing risks -------------------------------------------------------------------

def _seals():
    df = _df(w.SEALS)
    return df, {"x": "Hours", "c": "c", "e": "Failure mode"}


def _seal_fit():
    df, mapping = _seals()
    df["c"] = (df["Status"] != "Failed").astype(int)
    return cr.fit("competing_risks", df, mapping, unit="Hours")


def test_failures_by_the_horizon_are_counted_up_to_it():
    r = _seal_fit()
    assert r["horizon"] == 7000
    by = {k["name"]: (k["failures"], k["failures_by"]) for k in r["causes"]}
    # "Failures by mode, by 7,000 hours" was the all-time 22 and 15.
    assert by == {"Wear": (22, 19), "Installation": (15, 14)}


def test_one_share_of_failures_everywhere_the_estimate_by_the_horizon():
    r = _seal_fit()
    shares = {k["name"]: k["share"] for k in r["causes"]}
    assert shares["Wear"] == pytest.approx(0.689, abs=0.002)
    assert sum(shares.values()) == pytest.approx(1.0)


def test_life_with_a_mode_eliminated_is_the_other_modes_weibull():
    df, _ = _seals()
    r = _seal_fit()
    elim = {e["cause"]: e for e in r["eliminated"]}
    # Installation eliminated: wear alone, its failures as failures and everything else running.
    wear = sp.Weibull.fit(df["Hours"].to_numpy(float), c=np.where(df["Failure mode"] == "Wear", 0, 1))
    no_install = elim["Installation"]
    assert no_install["remaining"] == ["Wear"] and no_install["failures"] == 22
    assert no_install["b_life"] == pytest.approx(float(wear.qf(0.1)), rel=1e-6)
    assert no_install["b_life"] == pytest.approx(4076, abs=2)
    assert no_install["lower"] == pytest.approx(3631, abs=3)
    # Wear eliminated: what a redesign alone can't get past (the walkthrough's 1,865 h, at least 1,092 h).
    assert elim["Wear"]["b_life"] == pytest.approx(1865, abs=2) and elim["Wear"]["lower"] == pytest.approx(1092, abs=3)


def test_a_time_to_a_share_is_a_life_with_a_one_sided_bound():
    r = _seal_fit()
    one = r["one_sided"]
    assert one["level"] == pytest.approx(0.9) and set(one["upper"]) == {"Wear", "Installation"}
    # The one-sided 90% upper bound lies inside the two-sided 90% band's upper end.
    up2 = np.array(r["curves"]["upper"]["Wear"], dtype=float)
    up1 = np.array(one["upper"]["Wear"], dtype=float)
    ok = np.isfinite(up1) & np.isfinite(up2)
    assert (up1[ok] <= up2[ok] + 1e-9).all() and (up1[ok] < up2[ok]).any()
    assert r["ci_level"] == pytest.approx(0.9)


def test_a_saved_competing_risks_model_from_before_is_refitted_when_read(monkeypatch):
    from backend.schema import Model

    df, mapping = _seals()
    df["c"] = (df["Status"] != "Failed").astype(int)
    old = {k: v for k, v in _seal_fit().items() if k not in ("version", "one_sided", "eliminated")}
    old["ci_level"] = None
    model = Model(id="m1", name="Seals", owner_id="u", dataset_id="d1", kind="competing_risks",
                  distribution_id="competing_risks", spec={"mapping": mapping, "unit": "Hours"}, results=old)
    monkeypatch.setattr(datasets_service, "get_dataset", lambda *a, **k: object())
    monkeypatch.setattr(datasets_service, "load_dataframe", lambda _ds: df)
    fresh = cr.refreshed(None, model)
    assert fresh["version"] == cr.VERSION and fresh["ci_level"] == pytest.approx(0.9)
    assert {k["name"]: k["failures_by"] for k in fresh["causes"]} == {"Wear": 19, "Installation": 14}


def test_a_blank_status_can_mean_still_running():
    df, _ = _seals()
    out = fitting.map_censor_column(df, "Failure mode", {"Wear": 0, "Installation": 1, "": 1})
    assert int((out["Failure mode"] == 0).sum()) == 22 and int((out["Failure mode"] == 1).sum()) == 58
    with pytest.raises(fitting.FitError, match="Say what a blank means"):
        fitting.map_censor_column(df, "Failure mode", {"Wear": 0, "Installation": 1})


# ---- W13: inspection data -------------------------------------------------------------------

def _valves(**extra):
    df = _df(w.VALVES)
    mapping = {"xl": "Last good check (h)", "xr": "Found failed at (h)", "c": "Status", "tl": "Entered at (h)",
               **extra}
    return df, mapping


def test_turnbull_b_lives_are_the_inspection_interval_never_its_end_twice():
    df, mapping = _valves()
    res = fitting.fit("turnbull", df, mapping, unit="Hours",
                      options={"c_map": {"Found failed": 2, "OK at last check": 1}})
    lives = {b["label"]: b for b in res["life"]["b_lives"]}
    # B2 was "1,500 h, at least 1,500 h"; the estimate only knows it lies between 1,000 and 1,500 h.
    assert lives["B1"]["value"] is None and lives["B1"]["between"] == [1000.0, 1500.0]
    assert lives["B10"]["between"] == [1500.0, 2000.0]
    # No failure is known before 1,000 h, so how early the first 10% go can't be bounded from these data.
    assert lives["B10"]["lower"] is None and "1,000" in lives["B10"]["lower_note"]
    # The median's bound is the start of the interval its bound falls in, below the interval.
    assert lives["B50"]["between"] == [3000.0, 3500.0] and lives["B50"]["lower"] == 3000.0
    assert "Inspection data" in res["life"]["bounds_note"]


def test_turnbull_matches_surpyval_where_failures_are_known():
    df, _ = _valves()
    xl, xr = df["Last good check (h)"].to_numpy(float), df["Found failed at (h)"].to_numpy(float)
    c = np.where(np.isnan(xr), 1, 2)
    m = sp.Turnbull.fit(x=np.column_stack([xl, np.where(np.isnan(xr), xl, xr)]), c=c,
                        tl=df["Entered at (h)"].to_numpy(float))
    pt = life_bounds.time_at_reliability(m, [0.98])["points"][0]
    # SurPyval's step puts B2 at the interval's end (1,500 h): the app gives the interval.
    assert float(m.qf(0.02)) == 1500.0
    assert pt["time"] is None and pt["between"] == [1000.0, 1500.0]


def test_late_entry_is_kept_on_the_result():
    df, mapping = _valves()
    res = fitting.fit("weibull", df, mapping, unit="Hours", options={"c_map": {"Found failed": 2, "OK at last check": 1}})
    assert res["late_entry"] == {"column": "Entered at (h)", "units": 20}
    assert res["interval_censored"] is True
    # The walkthrough's numbers: B10 1,805 h (at least 1,558 h).
    b10 = next(b for b in res["life"]["b_lives"] if b["label"] == "B10")
    assert b10["value"] == pytest.approx(1805, abs=2) and b10["lower"] == pytest.approx(1558, abs=3)


def test_kaplan_meier_refuses_inspection_data_in_plain_words():
    df, mapping = _valves()
    with pytest.raises(fitting.FitError, match="needs exact failure times.*use Turnbull"):
        fitting.fit("kaplan_meier", df, mapping, options={"c_map": {"Found failed": 2, "OK at last check": 1}})


def test_a_dataset_detail_carries_the_last_models_column_reading():
    from backend.routers.models import _last_mapping
    from backend.schema import Model

    cols = [{"name": c} for c in ("Unit", "Entered at (h)", "Last good check (h)", "Found failed at (h)", "Status")]
    _, mapping = _valves()
    m = Model(id="m", name="Valves: Weibull", spec={"mapping": mapping, "unit": "Hours",
                                                    "options": {"c_map": {"Found failed": 2}, "offset": False}})
    out = _last_mapping([m], cols)
    assert out["mapping"]["tl"] == "Entered at (h)" and out["options"] == {"c_map": {"Found failed": 2}}
    assert out["model_name"] == "Valves: Weibull"
    # A Bayesian model saved before kept shortest / longest columns the dataset doesn't have: skipped.
    old = Model(id="o", name="Old", spec={"mapping": {"xl": "shortest", "xr": "longest", "c": "censored"}})
    assert _last_mapping([old], cols) is None


# ---- W14: few failures with a prior ---------------------------------------------------------

def _gearbox_posterior():
    from surpyval.bayes import prior

    df = _df(w.GEARBOXES)
    x, c = df["Hours"].to_numpy(float), (df["Status"] != "Failed").astype(int).to_numpy()
    return sp.Weibull.fit_bayes(x, c, priors={"alpha": prior.around(18500, between=(12000, 28000)),
                                              "beta": prior.around(2, between=(1.5, 2.5))})


def test_the_chance_a_b10_requirement_is_met_comes_from_the_posterior():
    m = _gearbox_posterior()
    # The walkthrough's 20,000-draw check gave about 54%.
    assert bl.chance_at_least(m, 0.1, 5000) == pytest.approx(0.55, abs=0.02)
    check = life_requirement.check_requirement(m, 10, 5000)
    assert check["verdict"] == "does_not_meet" and check["chance"] == pytest.approx(0.55, abs=0.02)
    assert "The chance that B10 is at least 5,000" in check["summary"]


def test_a_b10_belief_says_the_shape_it_assumed():
    base = bl.baseline_from(None, ["u"], set(), {"b10": {"value": 6000, "low": 4000, "high": 9000}, "unit": "hours"})
    assert "surprised under 4,000 or over 9,000" in base["name"]
    assert "shape not given, so taken as anywhere from 1.2 to 4" in base["name"]
    stated = bl.baseline_from(None, ["u"], set(), {"b10": {"value": 6000, "low": 4000, "high": 9000},
                                                   "shape": {"low": 1.5, "high": 2.5}, "unit": "hours"})
    assert "shape between 1.5 and 2.5" in stated["name"] and stated["belief"]["shape"] == [1.5, 2.5]


def test_a_fit_with_a_prior_saves_the_users_own_table_and_columns(client):
    from backend import config

    if not getattr(config, "BILLING_ENABLED", False):
        pytest.skip("billing off")
    ds = client.post("/api/datasets/paste", json={"name": "Gearboxes", "content": w.GEARBOXES}).json()
    body = {"dataset_id": ds["id"], "time_column": "Hours", "censor_column": "Status", "unit": "hours",
            "c_map": {"Failed": 0, "Running": 1}, "distribution": "weibull", "trust": "guide",
            "prior": {"kind": "around", "distribution": "weibull", "unit": "hours",
                      "params": {"alpha": {"about": 18500, "between": [12000, 28000]},
                                 "beta": {"about": 2, "between": [1.5, 2.5]}}}}
    preview = client.post("/api/models/fit-with-prior", json={**body, "need": 5000}).json()
    assert preview.get("refused") is None, preview
    assert preview["need"]["chance"] == pytest.approx(0.55, abs=0.03)
    saved = client.post("/api/models/fit-with-prior", json={**body, "save": True, "name": "Gearbox prior"})
    assert saved.status_code == 200, saved.text
    doc = client.db.models.find_one({"_id": saved.json()["id"]})
    # The dataset the user picked, read the way they read it: refittable with a prior again.
    assert doc["dataset_id"] == ds["id"]
    assert doc["spec"]["mapping"] == {"x": "Hours", "c": "Status"}
    assert doc["spec"]["options"] == {"c_map": {"Failed": 0, "Running": 1}}


# ---- W11: comparing two saved models --------------------------------------------------------

def test_compare_two_says_whether_the_b10s_are_clearly_apart():
    a = {"label": "Supplier A", "distribution_id": "weibull",
         "params": [{"name": "alpha", "value": 5307}, {"name": "beta", "value": 1.762}]}
    b = {"label": "Supplier B", "distribution_id": "weibull",
         "params": [{"name": "alpha", "value": 7441}, {"name": "beta", "value": 2.677}]}
    res = strategy_service.compare_two(a, b, unit="hours")
    out = strategy_service.with_life_bounds(res, {"a": {"b10": 1055, "median": 3663}, "b": {"b10": 2557, "median": 5900}})
    assert out["b"]["lower"]["b10"] == 2557
    assert out["b10_reading"].startswith("Supplier B's B10 is clearly longer: we're 90% sure it's at least 2,557")
    close = strategy_service.with_life_bounds(res, {"b": {"b10": 1000, "median": 5000}})
    assert "not clearly" in close["b10_reading"]


def test_mpp_and_friends_say_why_they_have_no_bound():
    df = _df(w.BEARINGS)
    df = df[df["Supplier"] == "Supplier B"]
    res = fitting.fit("weibull", df, {"x": "Run hours", "c": "Status"}, unit="Hours",
                      options={"how": "MPP", "c_map": {"Failed": 0, "Removed, OK": 1}})
    b10 = next(b for b in res["life"]["b_lives"] if b["label"] == "B10")
    assert b10["value"] == pytest.approx(3030, abs=2) and b10["lower"] is None
    assert "maximum likelihood" in res["life"]["bounds_note"] and "MPP" in res["life"]["bounds_note"]
