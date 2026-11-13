"""A dataset's reading as the caller gave it, and what it carries into fits.

- A column the caller lists in ``not_used`` takes no role, even when the
  guess would have read it as the item column (i).
- "Time-varying covariates" needs covariates and a start/stop (or timeline)
  layout: an item replaced several times (one row per life, the last one
  running) with no covariates is several lives per item, never TVC.
- A model fitted from a saved dataset with no ``unit`` named takes the
  reading's unit (life, ALT, recurrent and condition-and-life fits).

The helpers and ``env`` fixture come from test_mcp.
"""

import io

import pandas as pd
import pytest

from backend.services import dataset_reading
from backend.services import datasets as ds_service
from backend.tests.test_mcp import A, _call, _ok, env  # noqa: F401 - env is a fixture

pytestmark = pytest.mark.usefixtures("mcp_on")

# The shape found on production (invented data): one row per item life, an
# item replaced several times has several rows, its last one still running.
COLUMNS = ["Equipment Unit ID", "Equipment Class", "Operating Hours Since Renewal (h)", "Status", "Failure Mode"]
MODES = ["Bearing wear", "Seal leak", "Impeller damage"]


def _lives() -> pd.DataFrame:
    rows = []
    for cls, prefix in (("Pump", "PMP"), ("Fan", "FAN")):
        for u in range(6):
            n = 3 if u % 2 == 0 else 1
            for k in range(n):
                last = k == n - 1
                rows.append([f"{prefix}-{u:03d}", cls, [4200, 1800, 3100][k] + 100 * u,
                             "Running" if last and u % 4 == 0 else "Failed",
                             "" if last and u % 4 == 0 else MODES[(u + k) % 3]])
    return pd.DataFrame(rows, columns=COLUMNS)


UPLOAD = {"action": "dataset_upload", "name": "Rotating equipment", "dataset_col": "Equipment Class",
          "x_col": "Operating Hours Since Renewal (h)", "c_col": "Status",
          "c_meanings": {"Failed": 0, "Running": 1}, "e_col": "Failure Mode",
          "not_used": ["Equipment Unit ID"], "z_cols": [], "unit": "hours"}


def _part() -> pd.DataFrame:
    return _lives().query("`Equipment Class` == 'Pump'").drop(columns=["Equipment Class"])


def test_not_used_wins_over_a_guessed_role():
    csv = _part().to_csv(index=False).encode()
    base = dataset_reading.guess_for_bytes(csv)
    assert base["i"] == "Equipment Unit ID"  # the guess reads it as the item column
    out = dataset_reading.merged(base, {"not_used": ["Equipment Unit ID"], "z": []})
    assert out["i"] == "" and out["not_used"] == ["Equipment Unit ID"]
    # A role the caller names explicitly still wins over not_used.
    named = dataset_reading.merged(base, {"i": "Equipment Unit ID", "not_used": ["Equipment Unit ID"]})
    assert named["i"] == "Equipment Unit ID" and "Equipment Unit ID" not in named["not_used"]


def test_several_lives_per_item_without_covariates_are_not_time_varying():
    df = ds_service.read_dataframe(_part().to_csv(index=False).encode())
    out = ds_service.detect_tags(df)
    assert "Time-varying covariates" not in out["tags"]
    assert out["tags"] == ["Non-repairable"]
    assert "Non-repairable model with time-varying covariates" not in out["use_for"]


def test_a_reading_without_covariates_drops_time_varying_covariates():
    detected = {"tags": ["Non-repairable", "Time-varying covariates"],
                "use_for": ["Non-repairable model with time-varying covariates"]}
    out = ds_service.with_reading_covariates(detected, [])
    assert out["tags"] == ["Non-repairable"] and out["use_for"] == ["Non-repairable model"]
    kept = ds_service.with_reading_covariates(detected, ["load"])
    assert kept["tags"] == ["Non-repairable", "Time-varying covariates"]


def test_start_stop_rows_with_a_changing_text_covariate_stay_time_varying():
    rows = [["TX-1", 0, 5, 1, "low"], ["TX-1", 5, 9, 0, "high"], ["TX-2", 0, 4, 1, "high"],
            ["TX-2", 4, 10, 1, "low"], ["TX-3", 0, 7, 1, "low"], ["TX-3", 7, 8, 0, "high"]]
    out = ds_service.detect_tags(pd.DataFrame(rows, columns=["transformer", "start_h", "stop_h", "censored", "duty"]))
    assert out["tags"] == ["Non-repairable", "Time-varying covariates"]


def test_mcp_upload_of_the_production_shape(env):
    a = env.token[A]
    out = _ok(_call(a, "change", {**UPLOAD, "csv": _lives().to_csv(index=False)}))
    assert len(out["datasets"]) == 2
    r = out["reading"]
    assert not r.get("i") and "Equipment Unit ID" in r["not_used"] and r["e"] == "Failure Mode"
    assert not r.get("z") and r["unit"] == "hours"
    listed = {d["id"]: d for d in _ok(_call(a, "list", {"kind": "datasets"}))["datasets"]}
    for d in out["datasets"]:
        got = _ok(_call(a, "get", {"kind": "dataset", "id": d["id"]}))
        assert not got["reading"].get("i")
        tags = listed[d["id"]]["tags"]
        assert "Time-varying covariates" not in tags and "Covariates" not in tags, tags
        assert "Non-repairable" in tags

    # Bug 2: a fit from the saved dataset with no unit keeps the reading's.
    ds_id = out["datasets"][0]["id"]
    fit = _ok(_call(a, "change", {"action": "model_fit", "name": "Pumps", "dataset_id": ds_id,
                                  "distribution": "weibull"}))
    doc = env.db.models.find_one({"_id": fit["model_id"]})
    assert (doc.get("results") or {}).get("unit", "").lower() == "hours"
    # A unit the caller names still wins.
    named = _ok(_call(a, "change", {"action": "model_fit", "name": "Pumps (days)", "dataset_id": ds_id,
                                    "distribution": "weibull", "unit": "days"}))
    assert (env.db.models.find_one({"_id": named["model_id"]}).get("results") or {}).get("unit", "").lower() == "days"


def test_alt_fit_from_a_dataset_takes_the_reading_unit(env):
    from backend.tests.test_alt_bounds_interval import _alt_df

    a = env.token[A]
    ds = _ok(_call(a, "change", {"action": "dataset_upload", "name": "ALT", "csv": _alt_df().to_csv(index=False),
                                 "x_col": "hours", "c_col": "cens", "z_cols": ["tempK"], "unit": "hours"}))
    out = _ok(_call(a, "change", {"action": "model_fit_alt", "name": "ALT", "dataset_id": ds["id"],
                                  "time_column": "hours", "censor_column": "cens", "stress_columns": ["tempK"]}))
    assert env.db.alt_models.find_one({"_id": out["model_id"]})["spec"]["unit"] == "hours"


def test_recurrent_fit_from_a_dataset_takes_the_reading_unit(env):
    from backend.services.samples import _COMPRESSOR_EVENTS_CSV

    a = env.token[A]
    df = pd.read_csv(io.BytesIO(_COMPRESSOR_EVENTS_CSV))
    ds = _ok(_call(a, "change", {"action": "dataset_upload", "name": "Compressors", "csv": df.to_csv(index=False),
                                 "x_col": "hours", "i_col": "compressor", "unit": "hours"}))
    out = _ok(_call(a, "change", {"action": "model_fit_recurrent", "name": "Compressors", "model": "crow_amsaa",
                                  "dataset_id": ds["id"], "system_column": "compressor", "time_column": "hours",
                                  "save": False}))
    assert out["unit"].lower() == "hours"
    # Fitting another column than the reading's time takes no unit from it.
    other = _ok(_call(a, "change", {"action": "model_fit_recurrent", "name": "Compressors", "model": "crow_amsaa",
                                    "dataset_id": ds["id"], "system_column": "compressor",
                                    "time_column": "test_end", "save": False}))
    assert not other["unit"]


def test_joint_fit_from_a_dataset_takes_the_reading_unit(env, monkeypatch):
    from backend import mcp_server
    from backend.tests.test_joint_models import fleet

    a = env.token[A]
    L, R = fleet(n=8)
    life = _ok(_call(a, "change", {"action": "dataset_upload", "name": "Pump lives", "csv": L.to_csv(index=False),
                                   "x_col": "age", "c_col": "running", "unit": "days"}))
    seen = {}

    def start_fit(db, *, body, **kw):
        seen.update(body)
        return 200, {"model_id": None, "results": {}}

    monkeypatch.setattr(mcp_server.joint_service, "start_fit", start_fit)
    _call(a, "analyse", {"action": "fit_joint", "dataset_id": life["id"], "unit_id_column": "unit",
                         "age_column": "age", "censor_column": "running", "reading_age_column": "age",
                         "reading_value_column": "value"})
    assert seen["unit"] == "days"
