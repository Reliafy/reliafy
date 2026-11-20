"""A block's model fitted in another unit of the same kind is converted to the
diagram's unit (model_units), never read as if its days were hours."""

from __future__ import annotations

import math

import numpy as np
import pytest
import surpyval as sp

from backend import units
from backend.fitting import DISTRIBUTIONS
from backend.services import model_units, rbd_analysis, rbd_uncertainty

X_DAYS = np.array([12.0, 30, 45, 61, 80, 95, 120, 150, 170, 210])
C = np.array([0, 0, 0, 1, 0, 0, 0, 1, 0, 0])
TIMES_H = [100.0, 500.0, 1500.0, 3000.0, 4500.0]


def _model(dist_id, values, unit, **extra):
    names = DISTRIBUTIONS[dist_id]["dist"].parameter_names
    return {"source": "params", "distribution_id": dist_id, "unit": unit,
            "params": [{"name": n, "value": float(v)} for n, v in zip(names, values)], **extra}


def _graph(model, unit="Hours", **graph_extra):
    return {"unit": unit, **graph_extra, "nodes": [
        {"id": "input", "type": "input", "data": {}},
        {"id": "a", "type": "component", "data": {"label": "Pump", "model": model}},
        {"id": "output", "type": "output", "data": {}}],
        "edges": [{"source": "input", "target": "a"}, {"source": "a", "target": "output"}]}


def _sf(graph, times=TIMES_H):
    out = rbd_analysis.analyze(graph, at_times=times)
    return np.asarray(out["at"]["sf"], dtype=float), out


# ---- the units ------------------------------------------------------------------------

def test_unit_factor_uses_the_apps_calendar_convention():
    assert units.unit_factor("Days", "Hours") == 24
    assert units.unit_factor("hours", "days") == pytest.approx(1 / 24)
    assert units.unit_factor("Months", "Hours") == pytest.approx(365.25 / 12 * 24)
    assert units.unit_factor("Years", "Days") == 365.25
    assert units.unit_factor("Weeks", "Days") == 7
    assert units.unit_factor("Miles", "Kilometres") == pytest.approx(1.609344)
    # Same unit, other kinds, blank and unknown: no factor, never a guess.
    for a, b in (("hrs", "Hours"), ("Cycles", "Hours"), ("km", "hours"), ("", "Hours"), ("Hours", None),
                 ("flight hours", "Hours"), ("Starts", "Cycles")):
        assert units.unit_factor(a, b) is None, (a, b)
    assert units.conversion_note("Months", "Hours") == "1 month = 730.5 hours, at 365.25 / 12 days a month"
    assert units.conversion_note("Hours", "Days") == "1 day = 24 hours"


@pytest.mark.parametrize("dist_id,values", [
    ("weibull", [10, 2]), ("exponential", [0.1]), ("normal", [10, 2]), ("lognormal", [2, 0.5]),
    ("gamma", [2, 0.3]), ("loglogistic", [10, 3]), ("expo_weibull", [10, 2, 1.5]), ("gumbel", [10, 2]),
    ("gumbel_lev", [10, 2]), ("logistic", [10, 2]), ("rayleigh", [5]), ("beta4", [2, 3, 1, 20]),
    ("uniform", [1, 20]),
])
def test_every_family_rule_keeps_the_life(dist_id, values):
    c = 24.0
    t = np.array([0.5, 3, 7, 12, 18])
    dist = DISTRIBUTIONS[dist_id]["dist"]
    before = dist.from_params(values)
    after = dist.from_params(model_units.scale_values(dist_id, values, c))
    assert np.max(np.abs(before.sf(t) - after.sf(c * t))) < 1e-12


# ---- the 1e-9 checks: a days model in an hours diagram ---------------------------------

@pytest.mark.parametrize("dist_id,fitter", [
    ("weibull", sp.Weibull), ("exponential", sp.Exponential), ("gamma", sp.Gamma), ("normal", sp.Normal)])
def test_a_days_model_gives_the_refit_in_hours(dist_id, fitter):
    days = fitter.fit(X_DAYS, C)
    hours = fitter.fit(X_DAYS * 24, C)
    got, out = _sf(_graph(_model(dist_id, days.params, "Days")))
    want, _ = _sf(_graph(_model(dist_id, hours.params, "Hours")))
    assert np.max(np.abs(got - want)) < 1e-9
    (conv,) = out["unit_conversions"]
    assert conv["from"] == "Days" and conv["to"] == "Hours" and conv["factor"] == 24
    assert "“Pump”: fitted in days, shown in hours (1 day = 24 hours)." == conv["note"]
    assert not any("not converted" in w for w in rbd_analysis.unit_warnings(_graph(_model(dist_id, days.params, "Days"))))


def test_lognormal_and_offset_and_mixture_match_the_same_life_in_hours():
    """A refit's optimiser stops near 1e-8 for these, so the truth is the same
    life written in hours (lognormal mu + ln 24, the offset and scale × 24)."""
    c = 24.0
    cases = [
        (_model("lognormal", [4.45, 0.95], "Days"), _model("lognormal", [4.45 + math.log(c), 0.95], "Hours")),
        (_model("weibull", [120, 1.4], "Days", extras={"gamma": 10.0}),
         _model("weibull", [120 * c, 1.4], "Hours", extras={"gamma": 10.0 * c})),
    ]
    mix = {"source": "params", "distribution_id": "mixture", "base_distribution_id": "weibull", "mixture": 2,
           "params": [{"name": "alpha1", "value": 12}, {"name": "beta1", "value": 0.7},
                      {"name": "weight1", "value": 0.2}, {"name": "alpha2", "value": 900},
                      {"name": "beta2", "value": 3.5}, {"name": "weight2", "value": 0.8}]}
    mix_h = {**mix, "params": [{**p, "value": p["value"] * c if p["name"].startswith("alpha") else p["value"]}
                               for p in mix["params"]]}
    cases.append(({**mix, "unit": "Days"}, {**mix_h, "unit": "Hours"}))
    for days, hours in cases:
        got, _ = _sf(_graph(days))
        want, _ = _sf(_graph(hours))
        assert np.max(np.abs(got - want)) < 1e-9, days


def test_months_and_years_use_the_convention():
    month_h = 365.25 / 12 * 24
    got, out = _sf(_graph(_model("weibull", [20, 1.8], "Months")))
    want, _ = _sf(_graph(_model("weibull", [20 * month_h, 1.8], "Hours")))
    assert np.max(np.abs(got - want)) < 1e-12
    assert "365.25 / 12 days a month" in out["unit_conversions"][0]["note"]
    got, out = _sf(_graph(_model("weibull", [2, 1.8], "Years"), unit="Days"), [100.0, 400.0, 900.0])
    want, _ = _sf(_graph(_model("weibull", [2 * 365.25, 1.8], "Days"), unit="Days"), [100.0, 400.0, 900.0])
    assert np.max(np.abs(got - want)) < 1e-12


def test_a_family_with_no_rule_is_wrapped():
    """The 0-to-1 beta has no scale: it is read at T / c instead."""
    got, out = _sf(_graph(_model("beta", [2, 3], "Days")), [2.4, 12.0, 20.0])
    want = sp.Beta.from_params([2, 3]).sf(np.array([2.4, 12.0, 20.0]) / 24)
    assert np.max(np.abs(got - want)) < 1e-12
    assert out["unit_conversions"]


# ---- what isn't converted ---------------------------------------------------------------

@pytest.mark.parametrize("model_unit,diagram", [("Cycles", "Hours"), ("Kilometres", "Hours"),
                                                ("Starts", "Hours"), ("", "Hours"), ("Days", "")])
def test_other_kinds_and_blank_units_are_as_before(model_unit, diagram):
    model = _model("weibull", [100, 2], model_unit)
    g = _graph(model, unit=diagram)
    got, out = _sf(g)
    want = sp.Weibull.from_params([100, 2]).sf(np.array(TIMES_H))
    assert np.max(np.abs(got - want)) < 1e-12  # read as it is, as today
    assert "unit_conversions" not in out
    if model_unit and diagram:
        (w,) = rbd_analysis.unit_warnings(g)
        assert "not converted" in w


def test_converting_twice_changes_nothing():
    g, convs = model_units.convert_graph(_graph(_model("weibull", [10, 2], "Days")))
    again, more = model_units.convert_graph(g)
    assert len(convs) == 1 and more == [] and again is g
    assert g["nodes"][1]["data"]["model"]["params"][0]["value"] == 240


# ---- the band, importance, a sub-system --------------------------------------------------

class _Live:
    """A saved fit as the band's resolver hands it back."""

    def __init__(self, fit):
        self.fit = fit

    def __call__(self, model_id):
        return {"model": self.fit, "name": "Pump life"}


def test_the_band_draws_are_converted_too():
    days = sp.Weibull.fit(X_DAYS, C)
    hours = sp.Weibull.fit(X_DAYS * 24, C)

    def saved(fit, unit):
        return {**_model("weibull", fit.params, unit), "source": "saved", "modelId": "m1", "name": "Pump life"}

    got = rbd_analysis.analyze(_graph(saved(days, "Days")), resolve_model=_Live(days), at_times=TIMES_H,
                               band={"level": 0.9})
    want = rbd_analysis.analyze(_graph(saved(hours, "Hours")), resolve_model=_Live(hours), at_times=TIMES_H,
                                band={"level": 0.9})
    assert got["band"]["uncertain"], got["band"]  # carried uncertainty, not "stale"
    for key in ("sf_lower", "sf_upper"):
        a, b = np.asarray(got["band"][key], dtype=float), np.asarray(want["band"][key], dtype=float)
        # The same seed draws the same lives: the fit's covariance on the log scale doesn't depend
        # on its unit, so the draws differ only by the two fits' optimiser.
        assert np.max(np.abs(a - b)) < 1e-6, key
    assert got["band"]["mttf"]["lower"] == pytest.approx(want["band"]["mttf"]["lower"], rel=1e-6)
    converted, _ = model_units.convert_model(saved(days, "Days"), "Hours")
    assert rbd_uncertainty._matches(converted, days)  # still the saved fit, not "re-pick it"


def test_importance_uses_the_converted_model():
    nodes = [{"id": "input", "type": "input", "data": {}},
             {"id": "a", "type": "component", "data": {"label": "Pump", "model": _model("weibull", [100, 2], "Days")}},
             {"id": "b", "type": "component", "data": {"label": "Fan", "model": _model("weibull", [2400, 2], "Hours")}},
             {"id": "output", "type": "output", "data": {}}]
    edges = [{"source": "input", "target": "a"}, {"source": "a", "target": "b"}, {"source": "b", "target": "output"}]
    got = rbd_analysis.analyze({"unit": "Hours", "nodes": nodes, "edges": edges}, evaluate_at=1000.0)
    nodes[1]["data"]["model"] = _model("weibull", [2400, 2], "Hours")
    want = rbd_analysis.analyze({"unit": "Hours", "nodes": nodes, "edges": edges}, evaluate_at=1000.0)
    for measure in ("birnbaum", "fussell_vesely", "risk_achievement_worth"):
        assert got["importance"][measure] == pytest.approx(want["importance"][measure], rel=1e-9), measure
    assert got["importance"]["reliability"] == pytest.approx(want["importance"]["reliability"], rel=1e-9)


def test_a_sub_system_converts_to_the_parent_diagrams_unit():
    sub = _graph(_model("weibull", [100, 2], "Days"), unit="Days")
    parent = {"unit": "Hours", "nodes": [
        {"id": "input", "type": "input", "data": {}},
        {"id": "s", "type": "subsystem", "data": {"label": "Skid", "rbd": {"id": "sub1"}}},
        {"id": "output", "type": "output", "data": {}}],
        "edges": [{"source": "input", "target": "s"}, {"source": "s", "target": "output"}]}
    out = rbd_analysis.analyze(parent, resolve_subsystem=lambda _id: sub, at_times=TIMES_H)
    want = sp.Weibull.from_params([2400, 2]).sf(np.array(TIMES_H))
    assert np.max(np.abs(np.asarray(out["at"]["sf"]) - want)) < 1e-12
    assert [c["label"] for c in out["unit_conversions"]] == ["Skid › Pump"]


# ---- repairable diagrams -----------------------------------------------------------------

def _repairable(model, repair, unit="Hours"):
    return {"unit": unit, "repairable": True, "nodes": [
        {"id": "input", "type": "input", "data": {}},
        {"id": "a", "type": "component", "data": {"label": "Pump", "model": model, "repair": repair}},
        {"id": "output", "type": "output", "data": {}}],
        "edges": [{"source": "input", "target": "a"}, {"source": "a", "target": "output"}]}


def test_a_repairable_diagram_converts_the_life_and_the_repair_time():
    got = rbd_analysis.analyze_availability(
        _repairable(_model("weibull", [100, 2], "Days"), _model("lognormal", [1.0, 0.5], "Days")), simulate=False)
    want = rbd_analysis.analyze_availability(
        _repairable(_model("weibull", [2400, 2], "Hours"), _model("lognormal", [1.0 + math.log(24), 0.5], "Hours")),
        simulate=False)
    assert got["steady_state_availability"] == pytest.approx(want["steady_state_availability"], rel=1e-9)
    assert got["mean_up_time"] == pytest.approx(want["mean_up_time"], rel=1e-9)
    assert sorted(c["repair"] for c in got["unit_conversions"]) == [False, True]


def test_a_repairable_block_on_a_saved_repairable_model_converts():
    def block(alpha, beta, unit):
        return {"kind": "repairable", "source": "params", "form": "crow_amsaa", "unit": unit,
                "params": [{"name": "alpha", "value": alpha}, {"name": "beta", "value": beta}]}

    def graph(model):
        g = _repairable(model, _model("exponential", [0.1], "Hours"))
        g["nodes"][1]["data"]["replacement"] = {"rule": "age", "age": 2000, "duration": 8}
        return g

    got = rbd_analysis.analyze_availability(graph(block(50, 1.6, "Days")), simulate=False)
    want = rbd_analysis.analyze_availability(graph(block(1200, 1.6, "Hours")), simulate=False)
    assert got["steady_state_availability"] == pytest.approx(want["steady_state_availability"], rel=1e-9)
    assert got["unit_conversions"][0]["note"].startswith("“Pump”: fitted in days, shown in hours")


# ---- the downloads -----------------------------------------------------------------------

def _run_script(code, tmp_path):
    import json
    import os
    import subprocess
    import sys

    path = tmp_path / "diagram.py"
    path.write_text(code, encoding="utf-8")
    out = tmp_path / "diagram.json"
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env.update(MPLBACKEND="Agg", RELIAFY_RESULTS_JSON=str(out), RELIAFY_N_SIMS="60")
    proc = subprocess.run([sys.executable, str(path)], cwd=tmp_path, env=env, capture_output=True, text=True,
                          timeout=300)
    assert proc.returncode == 0, proc.stderr[-3000:]
    return json.loads(out.read_text())


@pytest.mark.parametrize("model", [_model("weibull", [100, 2], "Days"), _model("beta", [2, 3], "Days")])
def test_download_as_python_writes_the_conversion_out(tmp_path, model):
    from backend.services import rbd_export

    graph = _graph(model)
    app = rbd_analysis.analyze(graph)
    code = rbd_export.to_python(graph, "Mixed units")
    assert "fitted in days, shown in hours" in code
    res = _run_script(code, tmp_path)
    assert res["mttf"] == pytest.approx(app["mttf"], rel=1e-9)
    np.testing.assert_allclose(res["curve"]["sf"], app["system"]["sf"], atol=1e-9)


def test_repyability_json_holds_the_converted_parameters():
    from repyability.rbd.serialisation import rbd_from_json

    from backend.services import rbd_json

    graph = _graph(_model("weibull", [100, 2], "Days"))
    text = rbd_json.to_json(rbd_json.to_document(graph, "Mixed units"))
    rbd = rbd_from_json(text)
    want = sp.Weibull.from_params([2400, 2]).sf(np.array(TIMES_H))
    np.testing.assert_allclose(rbd.sf(np.array(TIMES_H)), want, atol=1e-12)
