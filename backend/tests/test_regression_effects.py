"""A regression's effects read the way the fitted model behaves.

SurPyval's accelerated-failure-time coefficient speeds the clock (a positive β
shortens the life) and its proportional-odds coefficient multiplies the odds of
surviving. The ratio shown is the time ratio (what the life is multiplied by)
and the odds ratio of having failed, so for every family a covariate that
shortens the life shows a time ratio below 1, and a hazard or odds ratio above
1. Checked against the fitted model's own median life, on data where dust
shortens the life and one site lasts longer than the others.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest
from scipy.optimize import brentq

from backend import fitting

SHAPE, SCALE = 1.8, 60_000.0


def _idlers(n: int = 300, seed: int = 7) -> pd.DataFrame:
    """Weibull proportional hazards: dust and load shorten the life, site
    North lasts longer than East and South; censored at random."""
    rng = np.random.default_rng(seed)
    site = rng.choice(["East", "North", "South"], size=n)
    load = rng.uniform(6, 12, size=n)
    dusty = (rng.uniform(size=n) < np.where(site == "East", 0.6, 0.3)).astype(int)
    eta = 0.10 * load + 0.70 * dusty - 0.6 * (site == "North")
    u = rng.uniform(size=n)
    life = SCALE * (-np.log(u) / np.exp(eta)) ** (1 / SHAPE)
    stop = rng.uniform(3_000, 26_000, size=n)
    return pd.DataFrame({"idler": [f"I-{k:03d}" for k in range(n)], "site": site, "load_kN": load.round(2),
                         "dusty": dusty, "hours": np.minimum(life, stop).round(1),
                         "running": (life > stop).astype(int)})


DF = _idlers()
MAP = {"x": "hours", "c": "running"}
COVS = ["load_kN", "dusty", "site"]

FAMILIES = sorted(k for k, e in fitting.REGRESSION_MODELS.items()
                  if e.get("effect") in ("aft", "odds", "hazard") and not e.get("frailty") and k != "cox_ph")


def _sf(model, z: dict, fields: list, x: float) -> float:
    row = pd.DataFrame({f["name"]: [z.get(f["name"], f["default"])] for f in fields})
    return float(np.ravel(fitting._eval_functions(model, np.array([x]), row)["sf"])[0])


def _median(model, z: dict, fields: list) -> float:
    return brentq(lambda x: _sf(model, z, fields, x) - 0.5, 1.0, 1e8)


@pytest.mark.parametrize("dist_id", FAMILIES)
def test_each_ratio_points_the_way_the_model_does(dist_id):
    r = fitting.fit(dist_id, DF, MAP, covariates=COVS)
    entry = fitting._MODEL_STORE[r["functions"]["model_id"]]
    model, fields = entry["model"], entry["fields"]
    coefs = {c["name"]: c for c in r["coefficients"]}
    base = {"load_kN": 9.0, "dusty": 0, "site": "East"}
    semi = fitting.REGRESSION_MODELS[dist_id].get("semi")
    for name, change in (("dusty", {"dusty": 1}), ("site[T.North]", {"site": "North"})):
        ratio = coefs[name]["ratio"]
        lo, hi = coefs[name]["ratio_ci"] or (None, None)
        # Fewer still running at 8,000 h: a shorter life.
        shorter = _sf(model, {**base, **change}, fields, 8_000.0) < _sf(model, base, fields, 8_000.0)
        if r["effect"] == "aft":
            assert (ratio < 1) == shorter, (dist_id, name, ratio)
            if not semi:
                # The time ratio is the life multiplier itself.
                life = _median(model, {**base, **change}, fields) / _median(model, base, fields)
                assert ratio == pytest.approx(life, rel=1e-3), (dist_id, name)
        else:
            # A hazard or odds ratio above 1 means a shorter life.
            assert (ratio > 1) == shorter, (dist_id, name, ratio)
        if lo is not None:
            assert lo < ratio < hi
    # Dust shortens the life, North lengthens it, whatever the family.
    shorter = coefs["dusty"]["ratio"] < 1 if r["effect"] == "aft" else coefs["dusty"]["ratio"] > 1
    assert shorter, dist_id
    assert r["base_levels"] == {"site": "East"}


def test_a_ticked_text_column_is_compared_as_groups():
    ticked = fitting.fit("weibull_ph", DF, MAP, covariates=COVS)
    formula = fitting.fit("weibull_ph", DF, MAP, formula="load_kN + dusty + site")
    assert [c["name"] for c in ticked["coefficients"]] == [c["name"] for c in formula["coefficients"]]
    for a, b in zip(ticked["coefficients"], formula["coefficients"]):
        assert a["value"] == pytest.approx(b["value"], rel=1e-6)
    names = [c["name"] for c in ticked["coefficients"]]
    assert "site[T.North]" in names and "site[T.South]" in names
    # The calculator offers the sites to choose from.
    site = next(f for f in ticked["functions"]["covariates"] if f["name"] == "site")
    assert site["type"] == "category" and site["options"] == ["East", "North", "South"]


def test_a_text_column_of_numbers_is_read_as_numbers():
    df = DF.assign(load_kN=DF["load_kN"].astype(str))
    r = fitting.fit("weibull_ph", df, MAP, covariates=["load_kN", "dusty"])
    assert [c["name"] for c in r["coefficients"]] == ["load_kN", "dusty"]


def test_a_column_that_cant_be_a_covariate_says_so_plainly():
    with pytest.raises(fitting.FitError) as err:
        fitting.fit("weibull_ph", DF, MAP, covariates=["idler", "dusty"])
    text = str(err.value)
    assert "“idler”" in text and "untick it" in text
    assert "Z_cols" not in text and "formula=" not in text
    with pytest.raises(fitting.FitError, match="same value in every row"):
        fitting.fit("weibull_ph", DF.assign(plant="A"), MAP, covariates=["plant", "dusty"])


def test_coefficient_ratio_by_effect():
    assert fitting.coefficient_ratio("hazard", math.log(2), [0.1, 1.0]) == (pytest.approx(2.0), [
        pytest.approx(math.exp(0.1)), pytest.approx(math.e)])
    ratio, ci = fitting.coefficient_ratio("aft", math.log(2), [0.1, 1.0])
    assert ratio == pytest.approx(0.5) and ci == [pytest.approx(math.exp(-1.0)), pytest.approx(math.exp(-0.1))]
    assert fitting.coefficient_ratio("odds", -math.log(3))[0] == pytest.approx(3.0)
    assert fitting.coefficient_ratio("aft", 0.2, None)[1] is None
