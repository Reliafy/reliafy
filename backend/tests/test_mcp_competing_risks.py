"""The fit tools take a failure-mode column (#177) and report non-parametric
life (#85), consistently with the app."""

import numpy as np
import pytest
from surpyval import CompetingRisks, KaplanMeier

from backend import fitting
from backend.services import datasets as datasets_service
from backend.services import samples
from backend.tests.test_mcp import A, FLAGS, TIMES, _call, _err, _ok, env  # noqa: F401 - env is a fixture

X = [50, 220, 340, 410, 920, 1400, 1960, 2600, 2810, 3050, 3430, 4180, 4720, 5240]
MODES = ["seal", "seal", "seal", "seal", "impeller", "seal", "seal", "bearing", "bearing", "bearing",
         "bearing", None, None, None]
SITES = ["A", "B"] * 7


def test_inline_fit_by_failure_mode(env):  # noqa: F811 - the fixture
    out = _ok(_call(env.token[A], "fit_distribution", {
        "distribution": "competing_risks", "data": X, "causes": MODES, "groups": SITES, "unit": "hours"}))
    assert out["kind"] == "competing_risks" and out["failed"] == 11 and out["still_running"] == 3
    model = CompetingRisks.fit(X, MODES, how="Kaplan-Meier")
    first = out["failure_modes"][0]
    assert first["mode"] == "seal" and first["failures"] == 6
    assert first["units_failed_from_it_by_horizon"] == pytest.approx(float(model.cif([out["horizon"]], "seal")[0]))
    assert out["reading"] and out["gray"]["available"] and "curves" not in out
    # A cause column with a single distribution is refused, as is one without causes.
    assert "competing" in _err(_call(env.token[A], "fit_distribution", {"data": X, "causes": MODES}))
    assert "failure mode" in _err(_call(env.token[A], "fit_distribution", {"distribution": "competing_risks",
                                                                           "data": X}))


def test_saved_from_a_dataset_and_read_back(env):  # noqa: F811
    csv = next(d for d in samples.SAMPLE_DATASETS if d["id"] == "sample-ds-pump-modes")["csv"]
    ds = datasets_service.create_dataset(env.db, "Pumps by mode", csv, A)
    saved = _ok(_call(env.token[A], "fit_and_save_model", {
        "name": "Pumps by mode", "distribution": "competing_risks_cox", "dataset_id": ds.id,
        "time_column": "hours", "cause_column": "failure_mode", "group_column": "site",
        "covariates": ["duty_pct"], "unit": "hours"}))
    assert saved["saved"] and saved["regression"]["model"] == "Cox"
    detail = _ok(_call(env.token[A], "get_model", {"model_id": saved["model_id"]}))
    assert detail["kind"] == "competing_risks" and detail["failure_modes"][0]["mode"] == "bearing wear"
    assert detail["gray"]["sentence"].startswith("Seal leak differs by site")
    assert detail["reading"] == saved["reading"]
    assert "Column 'nope'" in _err(_call(env.token[A], "fit_distribution", {
        "distribution": "competing_risks", "dataset_id": ds.id, "time_column": "hours", "cause_column": "nope"}))


def test_kaplan_meier_life_with_its_restricted_mean(env):  # noqa: F811
    out = _ok(_call(env.token[A], "fit_and_save_model", {
        "name": "KM", "distribution": "kaplan_meier", "data": TIMES, "censored": FLAGS, "unit": "hours"}))
    km = KaplanMeier.fit(np.asarray(TIMES, dtype=float), np.asarray(FLAGS))
    mttf = out["life"]["mttf"]
    assert mttf["value"] == pytest.approx(float(km.mean(max(TIMES))))
    assert mttf["lower"] == pytest.approx(float(km.mean_cb(max(TIMES), alpha_ci=0.2)[0]))
    detail = _ok(_call(env.token[A], "get_model", {"model_id": out["model_id"]}))
    assert detail["life"]["b_lives"][3]["value"] == pytest.approx(float(fitting._life_metrics(km)["median"]))
