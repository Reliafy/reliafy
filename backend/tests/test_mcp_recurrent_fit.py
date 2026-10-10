"""Recurrent models over MCP (#65, #137): fit_recurrent_model, and what
get_model / next_failure / optimal_overhaul say about the new families. The
fits are the app's (backend.recurrent, checked against SurPyval in
test_recurrent_models). The helpers and ``env`` fixture come from test_mcp.
"""

import io

import pandas as pd
import pytest

from backend import recurrent as rec
from backend.tests.test_mcp import A, _call, _err, _ok, env  # noqa: F401 - env is a fixture


def _compressors() -> pd.DataFrame:
    from backend.services.samples import _COMPRESSOR_EVENTS_CSV

    return pd.read_csv(io.BytesIO(_COMPRESSOR_EVENTS_CSV))


def _pumps() -> pd.DataFrame:
    from backend.services.samples import _PUMP_REPAIRS_CSV

    return pd.read_csv(io.BytesIO(_PUMP_REPAIRS_CSV))


def test_fit_recurrent_model_inline_crow_amsaa_matches_the_app_and_saves(env):
    df = _compressors()
    out = _ok(_call(env.token[A], "fit_recurrent_model", {
        "name": "Compressors", "model": "crow_amsaa", "times": df.hours.tolist(), "systems": df.compressor.tolist(),
        "observed_to": 5000, "causes": df.failure_mode.tolist(), "unit": "hours"}))
    ref, _ = rec.fit(df, {"i": "compressor", "x": "hours", "t": "test_end", "mode": "failure_mode"}, "crow_amsaa",
                     "hours", gof_test=False)
    assert out["saved"] and out["url"].endswith(f"/modelling/recurrent/{out['model_id']}")
    assert [p["value"] for p in out["params"]] == pytest.approx([p["value"] for p in ref["params"]])
    assert out["growth"] == "deteriorating" and out["family"] == "nhpp"
    assert [c["cause"] for c in out["by_cause"]] == ["valve", "bearing", "seal", "electrical"]
    doc = env.db.recurrent_models.find_one({"_id": out["model_id"]})
    assert doc["spec"]["mapping"] == {"i": "system", "x": "time", "tr": "observed_to", "mode": "cause"}

    # The saved model works with the minimal-repair tools.
    ov = _ok(_call(env.token[A], "optimal_overhaul", {"model_id": out["model_id"], "cost_repair": 100,
                                                      "cost_overhaul": 2000}))
    assert ov["optimal"]["interval"] > 0


def test_fit_recurrent_model_imperfect_repair_from_a_dataset(env):
    a = env.token[A]
    df = _compressors()
    ds = _ok(_call(a, "upload_dataset", {"name": "Compressors", "csv": df.to_csv(index=False)}))
    out = _ok(_call(a, "fit_recurrent_model", {
        "name": "Compressors GRP", "model": "grp_ii", "dataset_id": ds["id"], "system_column": "compressor",
        "time_column": "hours", "observed_to_column": "test_end", "unit": "hours"}))
    rest = out["repair_effectiveness"]
    assert 0.2 < rest["effectiveness"] < 0.5 and "of the system's age" in rest["reading"]
    assert out["repair_test"]["verdict"] == "partial"
    assert len(out["next_failure_by_system"]) == 4 and out["family"] == "renewal"

    got = _ok(_call(a, "get_model", {"model_id": out["model_id"]}))
    assert got["repair_test"]["verdict"] == "partial" and got["next_failure_by_system"]
    nf = _ok(_call(a, "next_failure", {"model_id": out["model_id"], "age": 0, "within": [500]}))
    assert 0 < nf["within"][0]["prob_failure"] < 1 and "Imperfect repair" in nf["assumption"]
    msg = _err(_call(a, "optimal_overhaul", {"model_id": out["model_id"], "cost_repair": 100,
                                             "cost_overhaul": 2000}))
    assert "minimal-repair model" in msg


def test_fit_recurrent_model_covariates_without_saving(env):
    df = _pumps()
    out = _ok(_call(env.token[A], "fit_recurrent_model", {
        "model": "pi_nhpp", "save": False, "times": df.hours.tolist(), "systems": df.pump.tolist(),
        "observed_to": df.observed_to.tolist(),
        "covariates": {"site": df.site.tolist(), "duty_pct": df.duty_pct.tolist()}, "unit": "hours"}))
    assert out["saved"] is False and env.db.recurrent_models.count_documents({"owner_id": A}) == 0
    effects = {e["covariate"]: e for e in out["covariate_effects"]}
    assert effects["site: Inland"]["effect"] == "higher" and "Coastal" in effects["site: Inland"]["reading"]
    ref, _ = rec.fit(df, {"i": "pump", "x": "hours", "tr": "observed_to", "z": ["site", "duty_pct"]}, "pi_nhpp",
                     gof_test=False)
    ratio = next(c["ratio"] for c in ref["coefficients"] if c["name"] == "site: Inland")
    assert effects["site: Inland"]["rate_ratio"] == pytest.approx(ratio, rel=1e-3)


def test_fit_recurrent_model_windows_and_plain_errors(env):
    a = env.token[A]
    df = _compressors()
    gapped = df[~((df.compressor == "CMP-1") & (df.hours > 2100) & (df.hours <= 2700))]
    out = _ok(_call(a, "fit_recurrent_model", {
        "model": "crow_amsaa", "save": False, "times": gapped.hours.tolist(), "systems": gapped.compressor.tolist(),
        "observed_to": 5000, "windows": {"CMP-1": [[0, 2100], [2700, 5000]]}}))
    assert out["observation_gaps"]["systems_with_gaps"] == 1
    assert "name" in _err(_call(a, "fit_recurrent_model", {"times": [1, 2], "systems": ["a", "a"]}))
    assert "exactly one" in _err(_call(a, "fit_recurrent_model", {"name": "X"}))
    assert "covariate" in _err(_call(a, "fit_recurrent_model", {
        "name": "X", "model": "pi_nhpp", "times": df.hours.tolist(), "systems": df.compressor.tolist()}))


def test_fit_recurrent_model_is_pro_only():
    from backend.mcp_server import PRO_ONLY_TOOLS

    assert "fit_recurrent_model" in PRO_ONLY_TOOLS
