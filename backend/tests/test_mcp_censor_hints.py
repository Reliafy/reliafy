"""The fit tools' sanity checks on the censor column (#190).

A censor column named like a failure flag ("failed", "is_failed", "status")
usually means 1 = failed — the inverse of Reliafy's convention — and a roughly
even split fits silently with the flags backwards. The fit result warns when
c_invert isn't set, and echoes the counts it used so they can be checked
against what the user said. The helpers and ``env`` fixture come from test_mcp.
"""

import pytest

from backend.tests.test_mcp import A, TIMES, FLAGS, _call, _ok, env  # noqa: F401 - env is a fixture

# 1 = failed, as the spreadsheet in the report had it: 7 failures, 3 running.
FAILED = [1 - f for f in FLAGS]


def _dataset(env, column: str) -> str:
    csv = f"hours,{column}\n" + "\n".join(f"{t},{c}" for t, c in zip(TIMES, FAILED))
    return _ok(_call(env.token[A], "upload_dataset", {"name": "Pumps", "csv": csv}))["id"]


def test_a_failure_named_column_warns_without_c_invert(env):
    ds = _dataset(env, "failed")
    args = {"dataset_id": ds, "time_column": "hours", "censor_column": "failed"}
    out = _ok(_call(env.token[A], "fit_distribution", args))
    # Non-blocking: the fit still runs (the way the caller asked), led by the warning.
    assert out["params"] and list(out)[0] == "warnings"
    warning = out["warnings"][0]
    assert 'The censor column "failed" sounds like 1 = failed' in warning
    assert "refit with c_invert=true" in warning
    # As fitted, the 1s were read as running.
    assert (out["n_failed"], out["n_right_censored"]) == (3, 7)

    fixed = _ok(_call(env.token[A], "fit_distribution", {**args, "c_invert": True}))
    assert "warnings" not in fixed
    assert (fixed["n_failed"], fixed["n_right_censored"]) == (7, 3)

    saved = _ok(_call(env.token[A], "fit_and_save_model", {**args, "name": "Pumps"}))
    assert saved["saved"] and "sounds like 1 = failed" in saved["warnings"][0]
    assert saved["n_failed"] == 3


@pytest.mark.parametrize("column", ["status", "is_failed", "Failure", "isFailed", "broken", "event"])
def test_failure_names_are_matched_on_tokens(env, column):
    out = _ok(_call(env.token[A], "fit_distribution", {
        "dataset_id": _dataset(env, column), "time_column": "hours", "censor_column": column}))
    assert any(f'"{column}" sounds like 1 = failed' in w for w in out.get("warnings", []))


@pytest.mark.parametrize("column", ["censored", "running", "suspended", "c", "flag", "failure_mode"])
def test_censor_like_names_do_not_warn(env, column):
    out = _ok(_call(env.token[A], "fit_distribution", {
        "dataset_id": _dataset(env, column), "time_column": "hours", "censor_column": column}))
    assert "warnings" not in out


def test_counts_lead_the_result_and_cover_every_censoring_kind(env):
    out = _ok(_call(env.token[A], "fit_distribution", {"data": TIMES, "censored": FLAGS, "unit": "hours"}))
    assert list(out)[:3] == ["saved", "n_failed", "n_right_censored"]
    assert (out["n_failed"], out["n_right_censored"]) == (7, 3)
    assert "n_left_censored" not in out and "n_interval_censored" not in out

    # Counts weight rows by `counts`; uncensored data is all failures.
    out = _ok(_call(env.token[A], "fit_distribution", {"data": TIMES, "counts": [2] * len(TIMES)}))
    assert (out["n_failed"], out["n_right_censored"]) == (20, 0)

    out = _ok(_call(env.token[A], "fit_distribution", {
        "data": [10, 20, 30, 40, 50, 60, 70], "data_right": [10, 30, 30, 45, 50, 60, 80],
        "censored": [0, 2, -1, 2, 0, 1, 2]}))
    assert (out["n_failed"], out["n_right_censored"], out["n_left_censored"], out["n_interval_censored"]) == (2, 1, 1, 3)

