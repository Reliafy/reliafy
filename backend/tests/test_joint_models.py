"""Condition and life: joint models of readings and failures (SurPyval's
``JointPH``), saved as models of kind ``joint``, fitted as a compute job,
and used as non-repairable RBD blocks (RePyability's ``JointNode``).

The synthetic fleet is drawn from the joint model itself: each unit's
reading follows its own straight line, and its failure time solves
``H(T) = E`` for the Weibull proportional hazards in the reading's current
value (and a covariate), so the fit should recover the parameters.
"""

import json

import matplotlib

matplotlib.use("Agg")

import mongomock
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from backend import joint

TRUE = dict(a=2.0, b=0.02, sd_a=0.3, sd_b=0.004, sd_noise=0.15, alpha=150.0, beta=2.0, zeta=0.8, ref=2.0,
            load=0.5)
LIFE_MAP = {"id": "unit", "x": "age", "c": "running"}
READ_MAP = {"id": "unit", "age": "age", "value": "value"}


def fleet(n=150, seed=7, stop=120.0, every=10.0):
    """``(lifetimes, readings)``: ``n`` units observed to ``stop`` days,
    read every ``every`` days; half carry load 1."""
    rng = np.random.default_rng(seed)
    grid = np.linspace(0, 1000, 20001)
    life, reads = [], []
    for k in range(n):
        load = k % 2
        a, b = rng.normal(TRUE["a"], TRUE["sd_a"]), rng.normal(TRUE["b"], TRUE["sd_b"])
        h = (TRUE["beta"] / TRUE["alpha"] * (np.maximum(grid, 1e-12) / TRUE["alpha"]) ** (TRUE["beta"] - 1)
             * np.exp(TRUE["zeta"] * (a + b * grid - TRUE["ref"]) + TRUE["load"] * load))
        H = np.concatenate([[0], np.cumsum((h[1:] + h[:-1]) / 2 * np.diff(grid))])
        T = float(np.interp(rng.exponential(), H, grid))
        end = min(T, stop)
        ages = np.arange(0.0, end, every)
        y = a + b * ages + rng.normal(0, TRUE["sd_noise"], ages.size)
        uid = f"U{k:03d}"
        life.append({"unit": uid, "age": round(end, 4), "running": int(T >= stop), "load": load})
        reads += [{"unit": uid, "age": float(t), "value": round(float(v), 5)} for t, v in zip(ages, y)]
    return pd.DataFrame(life), pd.DataFrame(reads)


@pytest.fixture(scope="module")
def fitted():
    """One fit of the 150-unit fleet, shared by the module."""
    L, R = fleet()
    items, summary = joint.build_items(L, R, LIFE_MAP, READ_MAP, ["load"])
    request = joint.fit_request(items, ["load"], path_model="linear", hazard_covariates=["load"],
                                path_covariates=[], unit="Days", marker="vibration", summary=summary)
    out = joint.run_fit(request)
    return {"items": items, "summary": summary, "out": out, "model": joint.restore(out["model"]), "L": L, "R": R}


# ---- The fit ---------------------------------------------------------------------------


def test_the_fit_recovers_the_fleets_parameters(fitted):
    rows = {r["name"]: r for r in fitted["out"]["results"]["params"]}
    truth = {"a": TRUE["a"], "b": TRUE["b"], "sd_a": TRUE["sd_a"], "sd_b": TRUE["sd_b"],
             "sd_noise": TRUE["sd_noise"], "beta": TRUE["beta"], "load": TRUE["load"],
             "marker_effect": TRUE["zeta"]}
    for name, value in truth.items():
        r = rows[name]
        assert abs(r["value"] - value) <= 3 * r["se"], (name, r["value"], value, r["se"])
    # alpha is reported at the mean reading: the true scale moved there.
    r = rows["alpha"]
    ref = fitted["model"].marker_reference
    alpha_at_ref = TRUE["alpha"] * np.exp(-TRUE["zeta"] * (ref - TRUE["ref"]) / TRUE["beta"])
    assert r["lower"] < alpha_at_ref < r["upper"]
    results = fitted["out"]["results"]
    assert results["fit_ok"] and results["maximum"] == "verified"
    assert results["path_covariates"] == {"a": [], "b": []} and results["hazard_covariates"] == ["load"]


def test_the_results_say_the_hazard_ratios_plainly_and_list_the_running_units(fitted):
    r = fitted["out"]["results"]
    hr = {h["name"]: h for h in r["hazard_ratios"]}
    assert hr["marker_effect"]["hr"] == pytest.approx(np.exp(next(
        p["value"] for p in r["params"] if p["name"] == "marker_effect")))
    assert hr["marker_effect"]["text"].startswith("Each 1 unit higher vibration multiplies the failure rate by")
    assert "at the same vibration" in hr["load"]["text"] and "90% CI" in hr["load"]["text"]
    assert r["horizons"]["labels"] == ["30 days", "90 days", "365 days"]
    running = fitted["L"][fitted["L"].running == 1]
    assert r["n_running"] == len(running) == len(r["risk"]) == len(fitted["out"]["units"])
    risks = [u["risk"][1] for u in r["risk"]]
    assert risks == sorted(risks, reverse=True)
    for u in r["risk"]:
        pred = joint.predict(fitted["model"], u["covariates"], fitted["out"]["units"][u["id"]]["markers"],
                             u["age"])
        assert u["survival"][0] == pytest.approx(float(pred.sf(u["age"] + 30.0)), rel=1e-9)
        assert u["median_reached"] == np.isfinite(pred.remaining_life(0.5))
    json.dumps(fitted["out"], allow_nan=False)  # strict JSON: it crosses the wire and into Mongo


def test_each_running_units_chance_carries_its_90_percent_upper_bound(fitted):
    """The pull list says how sure: each chance of failing with its one-sided
    90% upper bound (one less the lower bound on survival), and each median
    life left with its lower bound."""
    r = fitted["out"]["results"]
    bounded = [u for u in r["risk"] if u.get("risk_upper")]
    assert len(bounded) == len(r["risk"])
    h = r["horizons"]["values"]
    for u in r["risk"][:5]:
        assert all(up >= p - 1e-12 for up, p in zip(u["risk_upper"], u["risk"]))
        pred = joint.predict(fitted["model"], u["covariates"], fitted["out"]["units"][u["id"]]["markers"],
                             u["age"])
        lower = np.ravel(pred.cb(u["age"] + np.asarray(h), on="sf", alpha_ci=0.1, bound="lower"))
        assert u["risk_upper"] == pytest.approx(list(1 - lower), rel=1e-9)
        assert u["life_level"] == pytest.approx(0.9)
        if u["median_reached"] and u["median_lower"] is not None:
            assert u["median_lower"] <= u["median_remaining"] + 1e-9


def test_risk_bounds_stop_at_their_time_budget(fitted):
    model, units = fitted["model"], fitted["out"]["units"]
    h = fitted["out"]["results"]["horizons"]["values"]
    rows, notes = joint.risk_table(model, units, h, bounds_seconds=-1.0)
    assert rows and not any(u.get("risk_upper") for u in rows)
    assert any("90% bounds" in n for n in notes)
    # The whole table has a budget too: past it, the rest are left to the unit view.
    rows, notes = joint.risk_table(model, units, h, risk_seconds=-1.0)
    assert rows == [] and any("would take too long" in n for n in notes)


def test_the_data_checks_say_what_to_fix():
    L, R = fleet(n=20)
    bad = R.copy()
    bad.loc[0, "age"] = 999.0
    with pytest.raises(joint.FitError, match="reading after their age"):
        joint.build_items(L, bad, LIFE_MAP, READ_MAP)
    twice = pd.concat([L, L.iloc[[0]]])
    with pytest.raises(joint.FitError, match="appears more than once"):
        joint.build_items(twice, R, LIFE_MAP, READ_MAP)
    with pytest.raises(joint.FitError, match="censoring column"):
        joint.build_items(L, R, {"id": "unit", "x": "age"}, READ_MAP)
    extra = pd.concat([R, pd.DataFrame([{"unit": "ghost", "age": 1.0, "value": 2.0}])])
    _, summary = joint.build_items(L, extra, LIFE_MAP, READ_MAP)
    assert summary["unmatched_ids"] == ["ghost"] and "aren't in the lifetimes table" in summary["notes"][0]
    # c_invert flips 0 and 1: every unit's flag is then the other way round.
    flipped = L.assign(running=1 - L.running)
    items, _ = joint.build_items(flipped, R, LIFE_MAP, READ_MAP, c_invert=True)
    assert [it["c"] for it in items] == L.running.tolist()


def test_a_saved_fit_round_trips(fitted):
    m = fitted["model"]
    back = joint.restore(json.loads(json.dumps(m.to_dict())))
    uid, inp = next(iter(fitted["out"]["units"].items()))
    t = inp["age"] + np.array([5.0, 20.0, 60.0])
    a = joint.predict(m, inp["covariates"], inp["markers"], inp["age"])
    b = joint.predict(back, inp["covariates"], inp["markers"], inp["age"])
    assert np.allclose(a.sf(t), b.sf(t), rtol=1e-12)
    assert list(back.params) == pytest.approx(list(m.params))


def test_download_as_python_refits_with_fit_from_df(fitted, tmp_path):
    src = joint.python_script("Pumps", fitted["items"], ["load"], path_model="linear",
                              hazard_covariates=["load"], path_covariates=[], unit="Days", marker="vibration",
                              horizon=90)
    assert "fit_from_df(" in src and 'c_col="censored"' in src and 'markers_col="readings"' in src
    compile(src, "pumps.py", "exec")
    ns: dict = {"__name__": "exported"}
    exec(compile(src, "pumps.py", "exec"), ns)  # runs the refit (prints the model)
    assert list(ns["model"].params) == pytest.approx(list(fitted["model"].params), rel=1e-6)


# ---- RBD blocks ------------------------------------------------------------------------


def _graph(fitted, parallel=False, repairable=False):
    units = list(fitted["out"]["units"])
    a = {"kind": "joint", "modelId": "jm", "unit": "Days", "joint_unit": {"id": units[0]}}
    b = {"kind": "joint", "modelId": "jm", "unit": "Days",
         "joint_unit": {"age": 60.0, "markers": [[0, 2.1], [30, 2.6], [60, 3.2]], "covariates": {"load": 1}}}
    nodes = [{"id": "input", "type": "input", "data": {}},
             {"id": "a", "type": "component", "data": {"label": "Pump A", "model": a}},
             {"id": "b", "type": "component", "data": {"label": "Pump B", "model": b}},
             {"id": "output", "type": "output", "data": {}}]
    if parallel:
        edges = [("input", "a"), ("input", "b"), ("a", "output"), ("b", "output")]
    else:
        edges = [("input", "a"), ("a", "b"), ("b", "output")]
    g = {"unit": "Days", "nodes": nodes, "edges": [{"source": s, "target": t} for s, t in edges]}
    if repairable:
        g["repairable"] = True
    return g


def _resolver(fitted):
    entry = {"kind": "joint", "model": fitted["model"], "units": fitted["out"]["units"], "name": "Pumps"}
    return lambda mid: entry if mid == "jm" else None


@pytest.mark.parametrize("parallel", [False, True])
def test_an_rbd_of_joint_blocks_is_the_product_of_their_predictions(fitted, parallel):
    from backend.services import rbd_analysis

    t = np.array([5.0, 15.0, 40.0])
    out = rbd_analysis.analyze(_graph(fitted, parallel), resolve_model=_resolver(fitted), at_times=t.tolist(),
                               t_max=60.0)
    inp = fitted["out"]["units"][list(fitted["out"]["units"])[0]]
    pa = joint.predict(fitted["model"], inp["covariates"], inp["markers"], inp["age"])
    pb = joint.predict(fitted["model"], {"load": 1}, [[0, 2.1], [30, 2.6], [60, 3.2]], 60.0)
    ra, rb = pa.sf(pa.age + t), pb.sf(pb.age + t)
    expect = 1 - (1 - ra) * (1 - rb) if parallel else ra * rb
    assert out["at"]["sf"] == pytest.approx(expect.tolist(), rel=1e-9, abs=1e-12)
    ages = {n["id"]: n.get("joint_age") for n in out["nodes"]}
    assert ages == {"a": inp["age"], "b": 60.0}


def test_repairable_diagrams_and_several_unit_blocks_refuse_joint_blocks(fitted):
    from backend.services import rbd_analysis

    with pytest.raises(rbd_analysis.AnalysisError, match="repairable diagram replaces a failed unit"):
        rbd_analysis.analyze_availability(_graph(fitted, repairable=True), resolve_model=_resolver(fitted),
                                          simulate=False)
    g = _graph(fitted)
    g["nodes"][1]["type"] = "parallel"
    g["nodes"][1]["data"]["n"] = 2
    with pytest.raises(rbd_analysis.AnalysisError, match="single component block"):
        rbd_analysis.analyze(g, resolve_model=_resolver(fitted), t_max=60.0)
    # As of now: the block is already as of now; another age is refused.
    with pytest.raises(rbd_analysis.AnalysisError, match="already as of now"):
        rbd_analysis.analyze(_graph(fitted), resolve_model=_resolver(fitted), current_state={"a": {"age": 10}})


def test_no_mean_life_for_a_unit_whose_reading_falls_away(fitted):
    """A falling reading leaves a chance of never failing: no MTTF, and the
    axis runs far enough to show the curve level off."""
    from backend.services import rbd_analysis

    g = _graph(fitted)
    g["nodes"] = [g["nodes"][0], g["nodes"][2], g["nodes"][3]]
    g["nodes"][1]["data"]["model"]["joint_unit"] = {"age": 80.0, "markers": [[0, 2.0], [40, 1.0], [80, 0.0]],
                                                    "covariates": {"load": 0}}
    g["edges"] = [{"source": "input", "target": "b"}, {"source": "b", "target": "output"}]
    out = rbd_analysis.analyze(g, resolve_model=_resolver(fitted))
    assert out["mttf"] is None and any("No mean life is shown" in w for w in out["warnings"])
    assert out["system"]["sf"][-1] > 0.01


# ---- What the risk follows: the reading's level, its rate of change, or both -----------

SLOPE = 1.0  # per mm/s a year of the unit's rise


def slope_fleet(n=200, seed=11, follow=2.0, every=1 / 12):
    """``(lifetimes, readings)`` in years: each unit's reading a line from 3.0
    (sd 0.6) rising 1.0 a year (sd 0.5), read monthly with noise 0.3; the
    hazard Weibull (alpha 3, beta 2) times ``exp(SLOPE * rate)``, whatever
    the level. Followed for ``follow`` years."""
    rng = np.random.default_rng(seed)
    t = np.linspace(0.0, 30.0, 60001)
    life, reads = [], []
    for k in range(n):
        a, b = rng.normal(3.0, 0.6), rng.normal(1.0, 0.5)
        h = 2.0 / 3.0 * (t / 3.0) * np.exp(SLOPE * b)
        H = np.concatenate([[0], np.cumsum((h[1:] + h[:-1]) / 2 * np.diff(t))])
        T = float(np.interp(rng.exponential(), H, t))
        end = min(T, follow)
        ages = np.arange(0.0, end, every)
        y = a + b * ages + rng.normal(0, 0.3, ages.size)
        uid = f"B{k:03d}"
        life.append({"unit": uid, "age": round(end, 5), "running": int(T >= follow)})
        reads += [{"unit": uid, "age": round(float(s), 5), "value": round(float(v), 5)} for s, v in zip(ages, y)]
    return pd.DataFrame(life), pd.DataFrame(reads)


@pytest.fixture(scope="module")
def slope_fits():
    L, R = slope_fleet()
    items, summary = joint.build_items(L, R, LIFE_MAP, READ_MAP)
    out = {}
    for link in ("slope", "value"):
        request = joint.fit_request(items, [], path_model="linear", unit="Years", marker="vibration",
                                    marker_unit="mm/s", summary=summary, link=link)
        out[link] = joint.run_fit(request)
    return {"items": items, **out}


def test_a_fleet_whose_risk_follows_the_rate_gives_its_slope_effect_back(slope_fits):
    r = slope_fits["slope"]["results"]
    assert r["link"] == "slope" and r["link_label"] == "Rate of change" and r["fit_ok"]
    rows = {p["name"]: p for p in r["params"]}
    assert "marker_effect" not in rows
    slope = rows["slope_effect"]
    assert slope["part"] == "link" and slope["lower"] < SLOPE < slope["upper"]  # its 90% interval
    assert "per 1 mm/s per year faster rise in vibration" in slope["meaning"]
    assert "holds steady" in rows["alpha"]["meaning"]
    (hr,) = r["hazard_ratios"]
    assert hr["name"] == "slope_effect" and hr["label"] == "Rate of change of vibration"
    assert hr["unit"] == "mm/s per year" and hr["hr"] == pytest.approx(np.exp(slope["value"]))
    assert hr["text"].startswith("Each 1 mm/s per year faster rise in vibration multiplies the failure rate by")
    assert "per_year" not in hr  # already per year
    # The same data with the risk on the level fits worse.
    v = slope_fits["value"]["results"]
    assert v["link"] == "value" and v["aic"] > r["aic"]
    json.dumps(slope_fits["slope"], allow_nan=False)
    # Saved and read back, it still follows the rate.
    assert tuple(joint.restore(slope_fits["slope"]["model"]).link) == ("slope",)


def test_a_slope_effect_in_days_also_says_it_per_year():
    rows = [{"part": "link", "name": "slope_effect", "value": 365.25, "lower": 0.0, "upper": 730.5,
             "hr": float("inf"), "hr_lower": 1.0, "hr_upper": float("inf")}]
    (hr,) = joint.hazard_ratios(rows, "vibration", unit="Days", marker_unit="mm/s", link="slope")
    assert hr["unit"] == "mm/s per day"
    # A coefficient per (mm/s a day) is 365.25 times the one per (mm/s a year).
    assert hr["per_year"]["hr"] == pytest.approx(np.e) and hr["per_year"]["lower"] == pytest.approx(1.0)
    assert "Per year: Each 1 mm/s per year faster rise multiplies the failure rate by 2.72" in hr["text"]


def test_level_and_rate_together_and_the_scripts_link(slope_fits):
    src = joint.python_script("Bearings", slope_fits["items"], [], path_model="linear", unit="Years",
                              marker="vibration", link="slope")
    assert "JointPH(Weibull, LinearPath, link='slope')" in src
    ns: dict = {"__name__": "exported"}
    exec(compile(src, "bearings.py", "exec"), ns)  # refits it as the app did
    assert list(ns["model"].params) == pytest.approx(slope_fits["slope"]["model"]["params"], rel=1e-6)
    both = joint.python_script("Bearings", slope_fits["items"], [], path_model="linear", link=["value", "slope"])
    assert "link=['value', 'slope']" in both
    plain = joint.python_script("Bearings", slope_fits["items"], [], path_model="linear")
    assert "link=" not in plain


def test_the_link_is_checked_and_a_rate_needs_a_path_with_a_finite_slope_at_new():
    assert joint.link_id(None) == joint.link_id("") == "value"  # models saved before the choice
    assert joint.link_id(["slope", "value"]) == joint.link_id("value_slope") == "value_slope"
    with pytest.raises(joint.FitError, match="Unknown link"):
        joint.link_id("area")
    L, R = fleet(n=20)
    items, _ = joint.build_items(L, R, LIFE_MAP, READ_MAP)
    for path in ("logarithmic", "power"):
        for link in ("slope", "value_slope"):
            with pytest.raises(joint.FitError, match="use a linear or exponential path"):
                joint.fit_request(items, [], path_model=path, link=link)
    joint.fit_request(items, [], path_model="power", link="value")
    opts = joint.options()
    assert [o["id"] for o in opts["links"]] == ["value", "slope", "value_slope", "cumulative"]
    assert opts["default_link"] == "value" and opts["exposure_links"] == ["cumulative"]
    assert set(opts["slope_paths"]) == {"linear", "exponential", "quadratic"}


CUMULATIVE = 0.3  # per (mm/s)·year of the area under the unit's reading


def cumulative_fleet(n=200, seed=13, follow=3.0, every=1 / 12, level=0.0):
    """``(lifetimes, readings)`` in years: each unit's reading a line from 3.0
    (sd 0.8) rising 0.5 a year (sd 0.3), read monthly with noise 0.3; the
    hazard Weibull (alpha 4, beta 2) times ``exp(CUMULATIVE * area)``, the
    area under the reading less ``level`` since new."""
    rng = np.random.default_rng(seed)
    t = np.linspace(0.0, 30.0, 60001)
    life, reads = [], []
    for k in range(n):
        a, b = rng.normal(3.0, 0.8), rng.normal(0.5, 0.3)
        h = 2.0 / 4.0 * (t / 4.0) * np.exp(CUMULATIVE * ((a - level) * t + b * t * t / 2))
        H = np.concatenate([[0], np.cumsum((h[1:] + h[:-1]) / 2 * np.diff(t))])
        T = float(np.interp(rng.exponential(), H, t))
        end = min(T, follow)
        ages = np.arange(0.0, end, every)
        y = a + b * ages + rng.normal(0, 0.3, ages.size)
        uid = f"C{k:03d}"
        life.append({"unit": uid, "age": round(end, 5), "running": int(T >= follow)})
        reads += [{"unit": uid, "age": round(float(s), 5), "value": round(float(v), 5)} for s, v in zip(ages, y)]
    return pd.DataFrame(life), pd.DataFrame(reads)


@pytest.fixture(scope="module")
def cumulative_fits():
    L, R = cumulative_fleet()
    items, summary = joint.build_items(L, R, LIFE_MAP, READ_MAP)
    out = {}
    for link in ("cumulative", "value"):
        request = joint.fit_request(items, [], path_model="linear", unit="Years", marker="vibration",
                                    marker_unit="mm/s", summary=summary, link=link)
        out[link] = joint.run_fit(request)
    return {"items": items, **out}


def test_a_fleet_whose_risk_follows_its_accumulated_exposure_gives_its_effect_back(cumulative_fits):
    r = cumulative_fits["cumulative"]["results"]
    assert r["link"] == "cumulative" and r["link_label"] == "Accumulated exposure" and r["fit_ok"]
    assert r["exposure_above"] is None and r["exposure_text"] is None
    rows = {p["name"]: p for p in r["params"]}
    area = rows["cumulative_effect"]
    assert area["part"] == "link" and area["lower"] < CUMULATIVE < area["upper"]  # its 90% interval
    assert "per extra 1 mm/s·year of accumulated vibration (one year at 1 mm/s higher)" in area["meaning"]
    assert "no accumulated exposure" in rows["alpha"]["meaning"]
    (hr,) = r["hazard_ratios"]
    assert hr["label"] == "Accumulated vibration" and hr["unit"] == "mm/s·year"
    assert hr["hr"] == pytest.approx(np.exp(area["value"]))
    assert hr["text"].startswith("Each extra 1 mm/s·year of accumulated vibration (one year at 1 mm/s higher) "
                                 "multiplies the failure rate by")
    # The same data with the risk on the level fits worse.
    assert cumulative_fits["value"]["results"]["aic"] > r["aic"]
    json.dumps(cumulative_fits["cumulative"], allow_nan=False)
    assert tuple(joint.restore(cumulative_fits["cumulative"]["model"]).link) == ("cumulative",)


def test_a_cumulative_effect_in_days_also_says_it_per_year():
    rows = [{"part": "link", "name": "cumulative_effect", "value": 1 / 365.25, "lower": 0.0, "upper": 2 / 365.25,
             "hr": 1.0027, "hr_lower": 1.0, "hr_upper": 1.0055}]
    (hr,) = joint.hazard_ratios(rows, "vibration", unit="Days", marker_unit="mm/s", link="cumulative")
    assert hr["unit"] == "mm/s·day"
    # A coefficient per (mm/s)·day is 1/365.25 of the one per (mm/s)·year.
    assert hr["per_year"]["hr"] == pytest.approx(np.e) and hr["per_year"]["upper"] == pytest.approx(np.e ** 2)
    assert "Per year: Each year at 1 mm/s higher multiplies the failure rate by 2.72" in hr["text"]


def test_counting_exposure_above_a_level_is_subtracting_it_by_hand():
    level = 2.0
    L, R = cumulative_fleet(n=120, seed=5, level=level)
    items, summary = joint.build_items(L, R, LIFE_MAP, READ_MAP)
    by_hand_items, _ = joint.build_items(L, R.assign(value=R["value"] - level), LIFE_MAP, READ_MAP)
    kw = dict(path_model="linear", unit="Years", marker="vibration", marker_unit="mm/s", link="cumulative")
    above = joint.run_fit(joint.fit_request(items, [], summary=summary, exposure=level, **kw))
    by_hand = joint.run_fit(joint.fit_request(by_hand_items, [], summary=summary, **kw))
    assert above["model"]["params"] == pytest.approx(by_hand["model"]["params"], rel=1e-6, abs=1e-8)
    r = above["results"]
    assert r["exposure_above"] == level
    assert r["exposure_text"] == "Exposure is counted above 2 mm/s: only the vibration above it adds to the total."
    assert "counted above 2 mm/s" in {p["name"]: p for p in r["params"]}["cumulative_effect"]["meaning"]
    # The units' risk and the charts' readings are as read: the level goes back on.
    assert np.ravel([u["risk"] for u in r["risk"]]) == pytest.approx(
        np.ravel([u["risk"] for u in by_hand["results"]["risk"]]), rel=1e-6)
    assert [u["marker_now"] for u in r["risk"]] == pytest.approx(
        [u["marker_now"] + level for u in by_hand["results"]["risk"]], rel=1e-9)
    assert r["path"]["mean"] == pytest.approx([m + level for m in by_hand["results"]["path"]["mean"]], rel=1e-9)
    assert r["path"]["sample"][0]["values"] == pytest.approx(
        [v + level for v in by_hand["results"]["path"]["sample"][0]["values"]], abs=1e-9)
    # A saved model read back predicts from readings as entered.
    model = joint.restore(above["model"], r["exposure_above"])
    plain = joint.restore(by_hand["model"])
    uid, inp = next(iter(above["units"].items()))
    view = joint.unit_view(model, {}, inp["markers"], inp["age"], "Years")
    hand = joint.unit_view(plain, {}, joint._shift(inp["markers"], level), inp["age"], "Years")
    assert view["risk"] == pytest.approx(hand["risk"], rel=1e-9)
    assert np.ravel(view["markers"]) == pytest.approx(np.ravel(inp["markers"]), abs=1e-12)
    assert np.ravel(view["prediction"]["markers"]) == pytest.approx(np.ravel(inp["markers"]), abs=1e-12)
    assert view["prediction"]["marker"]["mean"] == pytest.approx(
        [m + level for m in hand["prediction"]["marker"]["mean"]], rel=1e-9)
    # The script takes the level off the readings, then refits to the same numbers.
    src = joint.python_script("Hydraulics", items, [], path_model="linear", unit="Years", marker="vibration",
                              link="cumulative", exposure=level)
    assert 'readings["value"] = readings["value"] - 2' in src and "link='cumulative'" in src
    ns: dict = {"__name__": "exported"}
    exec(compile(src, "hydraulics.py", "exec"), ns)
    assert list(ns["model"].params) == pytest.approx(above["model"]["params"], rel=1e-5)


def test_remaining_life_is_found_one_age_at_a_time_where_the_librarys_solver_fails():
    from types import SimpleNamespace

    def library(p):
        raise np.linalg.LinAlgError("the integrand's curvature is not finite")

    model = SimpleNamespace(params=[10.0], parameter_names=["alpha"])
    # Weibull (alpha 10, beta 2) from new, seen at age 5: S(t) / S(5).
    pred = SimpleNamespace(model=model, age=5.0, sf=lambda t: np.exp(-(np.asarray(t) / 10) ** 2 + 0.25))
    exact = 10 * np.sqrt(0.25 - np.log1p(-np.array([0.1, 0.5, 0.9]))) - 5
    assert joint._remaining_life(pred, library, [0.1, 0.5, 0.9]) == pytest.approx(exact, rel=1e-7)
    assert joint._remaining_life(pred, library, 0.5) == pytest.approx(exact[1], rel=1e-7)
    never = SimpleNamespace(model=model, age=5.0, sf=lambda t: np.full(np.shape(t), 0.8))
    assert joint._remaining_life(never, library, 0.5) == np.inf  # never falls to a half: not reached

    def broken(t):
        raise np.linalg.LinAlgError("no")

    assert np.isnan(joint._remaining_life(SimpleNamespace(model=model, age=5.0, sf=broken), library, 0.5))


def test_a_level_needs_the_accumulated_exposure_link_and_a_number():
    L, R = fleet(n=20)
    items, _ = joint.build_items(L, R, LIFE_MAP, READ_MAP)
    for link in ("value", "slope", "value_slope"):
        with pytest.raises(joint.FitError, match="only changes the accumulated-exposure model"):
            joint.fit_request(items, [], path_model="linear", link=link, exposure=2.0)
    for bad in ("hot", float("nan"), float("inf")):
        with pytest.raises(joint.FitError, match="count exposure above"):
            joint.fit_request(items, [], path_model="linear", link="cumulative", exposure=bad)
    for path in joint.PATHS:  # the area is finite from new on every path offered
        joint.fit_request(items, [], path_model=path, link="cumulative", exposure="")
    assert joint.exposure_above("") is None and joint.exposure_above("2.5") == 2.5


# ---- The API: Pro gating, the job, the saved model ------------------------------------

FREE, PRO = "user-free", "user-pro"
USERS = {FREE: {"uid": FREE, "email": "free@example.org", "name": "Free", "email_verified": True},
         PRO: {"uid": PRO, "email": "pro@example.org", "name": "Pro", "email_verified": True}}


@pytest.fixture()
def client(monkeypatch):
    from backend import config, db
    from backend.auth import get_current_user
    from backend.main import app
    from backend.services import billing

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(config, "BILLING_ENABLED", True)
    test_db = mongomock.MongoClient()["reliafy_test"]
    monkeypatch.setattr(db, "_db", test_db)
    monkeypatch.setattr(db, "_simulated", True)
    for uid, user in USERS.items():
        test_db.users.update_one({"_id": uid}, {"$set": {"email": user["email"], "email_lc": user["email"],
                                                         "email_verified": True, "name": user["name"]}},
                                 upsert=True)
    billing.set_plan(test_db, PRO, "pro")
    tc = TestClient(app)
    tc.act_as = lambda uid: app.dependency_overrides.__setitem__(get_current_user, lambda: USERS[uid])
    tc.db = test_db
    try:
        yield tc
    finally:
        app.dependency_overrides.clear()


def paste_dataset(client, life, readings=None, name="Pump lives"):
    """One dataset: the life data pasted, its readings added as its measurements."""
    r = client.post("/api/datasets/paste", json={"name": name, "content": life.to_csv(index=False)})
    assert r.status_code == 200, r.text
    ds = r.json()["id"]
    if readings is not None:
        r = client.put(f"/api/datasets/{ds}/measurements/paste", json={"content": readings.to_csv(index=False)})
        assert r.status_code == 200, r.text
        assert r.json()["measurements"]["n_rows"] == len(readings)
    return ds


def _body(client, n=60):
    L, R = fleet(n=n)
    return {"name": "Pumps", "dataset_id": paste_dataset(client, L, R), "mapping": LIFE_MAP,
            "readings_mapping": READ_MAP, "covariates": ["load"], "unit": "Days", "marker": "vibration",
            "marker_unit": "mm/s"}


def test_fitting_is_pro_and_the_saved_model_reads_back(client):
    client.act_as(FREE)
    body = _body(client)
    r = client.post("/api/joint/models", json=body)
    assert r.status_code == 402 and r.json()["code"] == "pro_required" and r.json()["upgrade"] is True
    assert client.post("/api/joint/check", json=body).json()["n_units"] == 60  # checking the data is free

    client.act_as(PRO)
    body = _body(client)
    r = client.post("/api/joint/models", json=body)
    assert r.status_code == 200, r.text
    mid = r.json()["model_id"]
    detail = client.get(f"/api/joint/models/{mid}").json()
    assert detail["kind"] == "joint" and detail["results"]["unit"] == "Days"
    assert [m["id"] for m in client.get("/api/joint/models").json()["models"]] == [mid]
    # Kept out of the life-model list (and every picker built on it).
    assert mid not in [m["id"] for m in client.get("/api/models").json()["models"]]
    uid = detail["running_units"][0]["id"]
    unit = client.get(f"/api/joint/models/{mid}/units/{uid}").json()
    assert unit["unit_id"] == uid and unit["prediction"]["x"][0] == unit["age"]
    entered = client.post(f"/api/joint/models/{mid}/predict",
                          json={"age": 50, "markers": [[0, 2.0], [40, 3.1]], "covariates": {"load": 1}})
    assert entered.status_code == 200 and entered.json()["age"] == 50
    bad = client.post(f"/api/joint/models/{mid}/predict", json={"age": 50, "markers": [[0, 2.0]]})
    assert bad.status_code == 422 and "load" in bad.json()["detail"]
    py = client.get(f"/api/joint/models/{mid}/export.py")
    assert py.status_code == 200 and "fit_from_df(" in py.text
    # The level is the default link; a model saved before the choice (no link) still opens and exports.
    assert detail["spec"]["link"] == "value" and detail["results"]["link"] == "value"
    client.db.models.update_one({"_id": mid}, {"$unset": {"spec.link": "", "results.link": "", "results.link_label": ""}})
    assert client.get(f"/api/joint/models/{mid}").status_code == 200
    py = client.get(f"/api/joint/models/{mid}/export.py")
    assert py.status_code == 200 and "link=" not in py.text
    # A rate-of-change link on a path whose rate is infinite at new is refused, saying what to use.
    bad = client.post("/api/joint/models", json={**body, "path_model": "logarithmic", "link": "slope"})
    assert bad.status_code == 422 and "linear or exponential" in bad.json()["detail"]
    # A level to count exposure above goes only with the accumulated-exposure link.
    bad = client.post("/api/joint/models", json={**body, "exposure_above": 2.0})
    assert bad.status_code == 422 and "accumulated-exposure" in bad.json()["detail"]
    above = client.post("/api/joint/models", json={**body, "name": "Above", "link": "cumulative",
                                                   "exposure_above": 2.0})
    assert above.status_code == 200, above.text
    aid = above.json()["model_id"]
    adetail = client.get(f"/api/joint/models/{aid}").json()
    assert adetail["spec"]["exposure_above"] == 2.0 and adetail["results"]["exposure_above"] == 2.0
    entered = client.post(f"/api/joint/models/{aid}/predict",
                          json={"age": 50, "markers": [[0, 2.0], [40, 3.1]], "covariates": {"load": 1}}).json()
    assert entered["markers"] == [[0.0, 2.0], [40.0, 3.1]]  # as entered, not less the level
    py = client.get(f"/api/joint/models/{aid}/export.py").text
    assert 'readings["value"] = readings["value"] - 2' in py and "link='cumulative'" in py
    # The dataset is the model's: neither it nor its measurements go while it stands.
    assert detail["spec"]["dataset_id"] == body["dataset_id"] and "lifetimes_dataset_id" not in detail["spec"]
    assert client.delete(f"/api/datasets/{body['dataset_id']}").status_code == 409
    assert client.delete(f"/api/datasets/{body['dataset_id']}/measurements").status_code == 409
    # Rehydrated through models_service.get_live_model, as an RBD resolves it.
    from backend.services import models as models_service

    entry = models_service.get_live_model(client.db, mid, [PRO])
    assert entry["kind"] == "joint" and uid in entry["units"]
    # Another user can't read it.
    client.act_as(FREE)
    assert client.get(f"/api/joint/models/{mid}").status_code == 404


def test_the_fit_runs_as_a_compute_job_and_saves_when_it_finishes(client, monkeypatch):
    from backend.services import compute_core, compute_queue, rbd_jobs

    queued = []
    monkeypatch.setattr(compute_queue, "configured", lambda: True)
    monkeypatch.setattr(compute_queue, "enqueue", lambda job_id, kind, request: queued.append((job_id, kind, request)))
    client.act_as(PRO)
    r = client.post("/api/joint/models", json=_body(client, n=50))
    assert r.status_code == 202 and r.json()["job"]["kind"] == "joint_fit"
    job_id, kind, request = queued[0]
    assert kind == "joint_fit" and client.db.models.count_documents({"kind": "joint"}) == 0
    # The compute service runs it and calls back; the web saves the model.
    result = compute_core.run(kind, json.loads(json.dumps(request)))
    assert rbd_jobs.apply_callback(client.db, {"job_id": job_id, "status": "done", "result": result})
    view = client.get(f"/api/rbd-jobs/{job_id}").json()
    assert view["status"] == "done" and view["result"]["model_id"]
    assert client.get(f"/api/joint/models/{view['result']['model_id']}").status_code == 200
    # A repeated callback saves nothing more.
    assert not rbd_jobs.apply_callback(client.db, {"job_id": job_id, "status": "done", "result": result})
    assert client.db.models.count_documents({"kind": "joint"}) == 1


def test_an_rbd_with_a_saved_joint_model_analyses_and_refuses_exports(client):
    client.act_as(PRO)
    mid = client.post("/api/joint/models", json=_body(client)).json()["model_id"]
    detail = client.get(f"/api/joint/models/{mid}").json()
    uid = detail["running_units"][0]["id"]
    model = {"source": "joint", "kind": "joint", "modelId": mid, "name": "Pumps", "unit": "Days",
             "joint_unit": {"id": uid}}
    graph = {"unit": "Days", "nodes": [
        {"id": "input", "type": "input", "data": {}},
        {"id": "a", "type": "component", "data": {"label": "Pump A", "model": model}},
        {"id": "output", "type": "output", "data": {}}],
        "edges": [{"source": "input", "target": "a"}, {"source": "a", "target": "output"}]}
    r = client.post("/api/rbds/analyze", json={"graph": graph, "t_max": 30})
    assert r.status_code == 200, r.text
    assert r.json()["nodes"][0]["joint_age"] == detail["running_units"][0]["age"]
    r = client.post("/api/rbds/analyze", json={"graph": {**graph, "repairable": True}})
    assert r.status_code == 422 and "condition-based block" in r.json()["detail"]
    rid = client.post("/api/rbds", json={"name": "Pump", "graph": graph}).json()["id"]
    js = client.get(f"/api/rbds/{rid}/export.json")
    assert js.status_code == 422 and "condition-based (joint) model" in js.json()["detail"]
    py = client.get(f"/api/rbds/{rid}/export.py")
    assert py.status_code == 200 and "condition-based block" in py.text and "JointNode" in py.text


def test_one_table_of_readings_and_outcomes_is_both_inputs(client):
    client.act_as(PRO)
    L, R = fleet(n=40)
    last = R.groupby("unit")["age"].transform("max")
    one = R.merge(L[["unit", "running"]], on="unit")
    one["outcome"] = one["running"].where(one["age"] == last.reindex(one.index).values)
    one = one[["unit", "age", "value", "outcome"]]
    pasted = client.post("/api/datasets/paste", json={"name": "Pumps in one", "content": one.to_csv(index=False)})
    assert pasted.status_code == 200, pasted.text
    ds = pasted.json()["id"]
    r = client.post("/api/joint/check", json={
        "dataset_id": ds, "mapping": {"id": "unit", "x": "age", "c": "outcome"}, "readings_mapping": READ_MAP})
    assert r.status_code == 200, r.text
    assert r.json()["n_units"] == one["unit"].nunique()
    # The way it was asked for before datasets held their measurements: the same id twice.
    legacy = client.post("/api/joint/check", json={
        "lifetimes_dataset_id": ds, "readings_dataset_id": ds, "mapping": {"id": "unit", "x": "age", "c": "outcome"},
        "readings_mapping": READ_MAP})
    assert legacy.status_code == 200 and legacy.json() == r.json()


def test_two_datasets_still_fit_as_before_and_refit_the_same_as_one(client):
    """A model saved with its life data and its readings in two datasets
    (how it was before) opens, refits and exports as it did; the same data
    as one dataset gives the same fit."""
    from backend.services import joint as joint_service

    client.act_as(PRO)
    L, R = fleet(n=50)
    life, reads = paste_dataset(client, L), paste_dataset(client, R, name="Pump vibration")
    legacy = {"name": "Pumps (two datasets)", "lifetimes_dataset_id": life, "readings_dataset_id": reads,
              "mapping": LIFE_MAP, "readings_mapping": READ_MAP, "covariates": ["load"], "unit": "Days",
              "marker": "vibration"}
    r = client.post("/api/joint/models", json=legacy)
    assert r.status_code == 200, r.text
    old = client.get(f"/api/joint/models/{r.json()['model_id']}").json()
    assert old["spec"]["lifetimes_dataset_id"] == life and old["spec"]["readings_dataset_id"] == reads
    assert client.delete(f"/api/datasets/{reads}").status_code == 409  # the readings dataset is still its data
    one = {**legacy, "name": "Pumps (one dataset)", "dataset_id": paste_dataset(client, L, R)}
    one.pop("lifetimes_dataset_id"), one.pop("readings_dataset_id")
    r = client.post("/api/joint/models", json=one)
    assert r.status_code == 200, r.text
    new = client.get(f"/api/joint/models/{r.json()['model_id']}").json()
    assert [p["value"] for p in new["results"]["params"]] == pytest.approx(
        [p["value"] for p in old["results"]["params"]])
    # Both read the same rows through the service.
    owners = [PRO]
    items_old, _ = joint_service.items_for(client.db, old["spec"], owners)
    items_new, _ = joint_service.items_for(client.db, new["spec"], owners)
    assert items_old == items_new
    assert client.get(f"/api/joint/models/{old['id']}/export.py").status_code == 200


# ---- The unit is the model's own (SurPyval's model.unit) -------------------------------


def test_the_joint_fit_carries_its_unit_and_its_script_passes_it(fitted):
    assert fitted["out"]["model"]["unit"] == "Days"  # the request's unit="Days"
    assert fitted["model"].unit == "Days"
    source = joint.python_script("Feed pumps", fitted["items"], ["load"], path_model="linear",
                                 hazard_covariates=["load"], path_covariates=[], unit="Days")
    assert "    unit='Days'," in source


def test_a_joint_model_saved_before_the_unit_loads_with_its_saved_unit(fitted):
    import copy

    from backend.schema import Model
    from backend.services import joint as joint_service

    old = copy.deepcopy(fitted["out"]["model"])
    old.pop("unit", None)
    doc = Model(id="old-joint", name="Old", kind=joint_service.KIND, results={"unit": "Days"},
                serialized={"format": "surpyval_joint", "model": old})
    assert joint_service.live(doc).unit == "Days"
    assert "unit" not in doc.serialized["model"]  # nothing rewritten
