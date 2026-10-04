"""How good is a regression model? (#176)

Scores a fitted regression (proportional-hazards, AFT, proportional-odds,
additive-hazards, Cox) model against the data it was fitted to, with
SurPyval's validation metrics:

* Harrell's concordance index (C): how well the model ranks which units fail
  first. 0.5 is a coin toss, 1 a perfect ranking.
* The integrated Brier score: the model's prediction error over the middle of
  the observed failure times, next to the same score for one Kaplan-Meier
  curve for every unit (the covariate-free baseline). Lower is better.
* Uno's time-dependent AUC at three horizons (the quartiles of the failure
  times): how well the model separates the units that have failed by then
  from those still running.

The computation is bounded: past ``MAX_UNITS`` units a random sample is
scored, drawn with a fixed seed so the numbers are the same every time, and
the result says so. Everything here is in-sample (the model is scored on its
own training data), which flatters it slightly; the result says that too.

:func:`validate_regression` never raises: anything it can't score comes back
as ``{"available": False, "reason": ...}``.
"""

from __future__ import annotations

import logging
import warnings

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

#: Units scored at most; larger data is sampled (without replacement).
MAX_UNITS = 20_000
#: Seed of that sample, so a model's scores never change between views.
SEED = 176
#: Horizons of the Brier-score integral, spread over the failure times.
N_TIMES = 20
#: The integral runs between these quantiles of the failure times.
SPAN = (0.10, 0.90)
#: Horizons of the time-dependent AUC: quartiles of the failure times.
AUC_QUANTILES = (0.25, 0.50, 0.75)

IN_SAMPLE_NOTE = ("Scored on the data the model was fitted to, so it reads a little better than it "
                  "would on new units.")


def unavailable(reason: str) -> dict:
    """The result when the metrics can't be computed, with the reason."""
    return {"available": False, "reason": reason}


def concordance_rating(c: float) -> str:
    """A word for Harrell's C: how well the model ranks units by risk."""
    if c < 0.55:
        return "no better than chance"
    if c < 0.65:
        return "weak"
    if c < 0.75:
        return "moderate"
    if c < 0.85:
        return "good"
    return "strong"


def concordance_reading(c: float) -> str:
    rating = concordance_rating(c)
    return (f"{rating[0].upper()}{rating[1:]}. In {c * 100:.0f}% of comparable pairs of units, the one "
            "that failed first was the one the model rated at higher risk (50% is a coin toss, 100% "
            "a perfect ranking).")


def brier_reading(improvement: float) -> str:
    """Plain reading of the model's Brier score against the baseline's.
    ``improvement`` is the relative reduction, (baseline - model) / baseline."""
    pct = improvement * 100
    if pct >= 1:
        return (f"The covariates cut the prediction error by {pct:.0f}% compared with one survival "
                "curve for every unit.")
    if pct > -1:
        return ("About the same prediction error as one survival curve for every unit: the covariates "
                "add little to the predicted survival.")
    return (f"{-pct:.0f}% more prediction error than one survival curve for every unit. The model "
            "predicts survival worse than ignoring the covariates; check the baseline distribution "
            "(or try Cox PH).")


def _finite(values) -> bool:
    return values is not None and bool(np.all(np.isfinite(values)))


def _column(df: pd.DataFrame, name: str | None, default: float) -> np.ndarray:
    if not name:
        return np.full(len(df), default, dtype=float)
    return pd.to_numeric(df[name], errors="coerce").to_numpy(dtype=float)


def _risk(model, x_ref: float, Z: pd.DataFrame) -> np.ndarray:
    """Risk scores, higher meaning an earlier failure: the cumulative hazard
    at a reference time (the median observed time). For the single-index
    models (PH, AFT, PO) that ranks units exactly as the linear predictor
    does; it also works for Cox and for additive hazards."""
    xs = np.full(len(Z), float(x_ref))
    try:
        risk = np.asarray(model.Hf(xs, Z), dtype=float).ravel()
        if risk.size == len(Z):
            return risk
    except Exception:  # noqa: BLE001 - fall back to 1 - sf
        pass
    return 1.0 - np.asarray(model.sf(xs, Z), dtype=float).ravel()


def validate_regression(model, df: pd.DataFrame, mapping: dict, covariates: list) -> dict:
    """Harrell's C, the integrated Brier score against a Kaplan-Meier
    baseline, and the time-dependent AUC of a fitted regression ``model``,
    scored on ``df`` (the data it was fitted to, censor column already in
    Reliafy's convention). ``covariates`` are the raw covariate columns the
    model reads. Never raises."""
    try:
        with warnings.catch_warnings(), np.errstate(all="ignore"):
            # Additive-hazards models warn when their hazard dips below 0;
            # those values are the model's own and are clipped below.
            warnings.simplefilter("ignore")
            return _validate(model, df, mapping, list(covariates or []))
    except Exception as exc:  # noqa: BLE001 - a score is never worth a failed fit
        logger.info("Regression validation failed: %s", exc)
        return unavailable("These scores couldn't be computed for this model.")


def _validate(model, df: pd.DataFrame, mapping: dict, covariates: list) -> dict:
    from surpyval import KaplanMeier
    from surpyval.metrics import auc_td, concordance_index, integrated_brier_score, survival_probability

    mapping = {k: v for k, v in (mapping or {}).items() if v}
    if not mapping.get("x"):
        return unavailable("The model has no time column to score against.")
    for key in ("xl", "xr"):
        if mapping.get(key):
            return unavailable("Not available for interval data: the scores need each unit's failure or "
                               "suspension time.")
    for key in ("tl", "tr"):
        if mapping.get(key) and np.isfinite(_column(df, mapping[key], np.nan)).any():
            return unavailable("Not available for truncated data: the scores assume every unit was "
                               "watched from time zero.")

    x = _column(df, mapping["x"], np.nan)
    c = _column(df, mapping.get("c"), 0.0)
    n = _column(df, mapping.get("n"), 1.0)
    covs = [col for col in covariates if col in df.columns]
    keep = np.isfinite(x) & np.isfinite(c) & np.isfinite(n) & (n > 0)
    if covs:
        keep &= df[covs].notna().all(axis=1).to_numpy()
    x, c, n = x[keep], c[keep], n[keep]
    Z = df.loc[keep, covs].reset_index(drop=True)

    if not np.isin(c, (0, 1)).all():
        return unavailable("Not available with left- or interval-censored rows: the scores need each "
                           "unit's failure or suspension time.")
    if not np.allclose(n, np.round(n)):
        return unavailable("Not available with fractional counts.")
    counts = np.round(n).astype(np.int64)
    total = int(counts.sum())

    # One row per unit; past MAX_UNITS a sample of units, without replacement.
    sampled = total > MAX_UNITS
    if sampled:
        counts = np.random.default_rng(SEED).multivariate_hypergeometric(counts, MAX_UNITS)
    idx = np.repeat(np.arange(x.size), counts)
    x, c = x[idx], c[idx].astype(int)
    Z = Z.iloc[idx].reset_index(drop=True)

    failed = x[c == 0]
    if failed.size < 2:
        return unavailable("Needs at least two failures to score the model.")

    risk = _risk(model, float(np.median(x)), Z)
    ok = np.isfinite(risk)
    if not ok.all():
        x, c, risk, Z = x[ok], c[ok], risk[ok], Z.loc[ok].reset_index(drop=True)
        failed = x[c == 0]
    c_index = float(concordance_index(x, c, risk))
    if not np.isfinite(c_index):
        return unavailable("These scores couldn't be computed for this model.")

    out: dict = {
        "available": True,
        "concordance": {
            "value": c_index,
            "rating": concordance_rating(c_index),
            "reading": concordance_reading(c_index),
        },
        "brier": None,
        "auc": [],
        "n_units": int(x.size),
        "n_total": total,
        "sampled": sampled,
        "note": IN_SAMPLE_NOTE,
    }
    if sampled:
        out["seed"] = SEED
        out["sample_note"] = (f"Scored on a random sample of {x.size:,} of the {total:,} units (fixed "
                              "seed, so the scores don't change).")

    # Horizons strictly inside the follow-up, where the censoring weights exist.
    t_max = float(x.max())
    times = np.unique(np.quantile(failed, np.linspace(*SPAN, N_TIMES)))
    times = times[(times > 0) & (times < t_max)]
    if times.size >= 2:
        S = np.clip(survival_probability(model, Z, times), 0.0, 1.0)
        km = np.asarray(KaplanMeier.fit(x, c).sf(times), dtype=float)
        S0 = np.tile(km, (x.size, 1))
        ibs = integrated_brier_score(x, c, S, times)
        ibs0 = integrated_brier_score(x, c, S0, times)
        if _finite(ibs) and _finite(ibs0) and ibs0 > 0:
            improvement = (ibs0 - ibs) / ibs0
            out["brier"] = {
                "model": float(ibs),
                "baseline": float(ibs0),
                "improvement": float(improvement),
                "from": float(times[0]),
                "to": float(times[-1]),
                "reading": brier_reading(improvement),
            }

    horizons = np.unique(np.quantile(failed, AUC_QUANTILES))
    horizons = horizons[(horizons > 0) & (horizons < t_max)]
    if horizons.size:
        S_h = survival_probability(model, Z, horizons)
        _, auc = auc_td(x, c, 1.0 - S_h, horizons)
        out["auc"] = [{"time": float(t), "value": float(a)} for t, a in zip(horizons, auc) if np.isfinite(a)]
    return out
