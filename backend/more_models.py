"""More life models (#179, #72, #63), in the registries' own shape.

* Bounded distributions (Beta, Beta4, Uniform): fitted like any plain
  distribution, but kept out of Best fit and the mixtures — a support that
  stops at a bound can't fit most unbounded life data, and would silently
  drop out of the ranking.
* Discretized distributions (``surpyval.Discretize``): a continuous
  distribution on the counts 1, 2, 3, … — cycles or demands to failure.
* Semi-parametric regressions: Lin and Ying's additive hazards, the
  semi-parametric proportional odds model and Buckley-James AFT — the
  additive, odds and time-scale analogues of Cox.
* Shared frailty: a proportional-hazards model with a random multiplier on
  the hazard shared by every unit of a group (a site, a batch), with the
  group column chosen as "Group by".
* Royston-Parmar: a flexible parametric (spline) model, univariate.

Every number comes from SurPyval; this module only registers the models
and shapes what they report. The registries carry no imports from
:mod:`backend.fitting` (which merges them into its own), so the functions
that need fitting's helpers import it when called.
"""

from __future__ import annotations

import math
import warnings
from typing import Optional

import numpy as np
import pandas as pd
from surpyval import (
    AdditiveHazards,
    Beta,
    Beta4,
    BuckleyJames,
    CoxFrailty,
    Discretize,
    ExponentialFrailty,
    Gamma,
    GammaFrailty,
    LogLogistic,
    LogNormal,
    LogNormalFrailty,
    ProportionalOdds,
    RoystonParmar,
    Uniform,
    WeibullFrailty,
)

# ``more``: listed under "More models" in the picker, out of the way of the
# everyday ones. ``bounded``: a support with a finite end, so not a Best-fit
# or mixture candidate.
BOUNDED = {
    "beta": {"name": "Beta (0 to 1)", "dist": Beta, "offsetable": False, "bounded": True, "more": True},
    "beta4": {"name": "Beta (four-parameter)", "dist": Beta4, "offsetable": False, "bounded": True,
              "more": True},
    "uniform": {"name": "Uniform", "dist": Uniform, "offsetable": False, "bounded": True, "more": True},
}

# Discretize(Weibull) is the discrete Weibull already listed, and
# Discretize(Exponential) the geometric, so neither is repeated.
DISCRETIZED = {
    "discretized_lognormal": {"name": "Discretized lognormal", "dist": Discretize(LogNormal), "more": True},
    "discretized_gamma": {"name": "Discretized gamma", "dist": Discretize(Gamma), "more": True},
    "discretized_loglogistic": {"name": "Discretized log-logistic", "dist": Discretize(LogLogistic),
                                "more": True},
}

# ``semi``: a step-function baseline estimated from the data, as Cox's.
SEMI_PARAMETRIC = {
    "additive_hazards": {"name": "Additive hazards (Lin-Ying)", "fitter": AdditiveHazards,
                         "effect": "additive", "semi": True, "more": True},
    "proportional_odds": {"name": "Proportional odds (semi-parametric)", "fitter": ProportionalOdds,
                          "effect": "odds", "semi": True, "more": True},
    "buckley_james": {"name": "Buckley-James AFT", "fitter": BuckleyJames, "effect": "aft",
                      "semi": True, "more": True},
}

# Shared (gamma) frailty on a proportional-hazards model. ``group`` is the
# column the frailty is shared over, mapped as ``mapping["group"]``.
FRAILTY = {
    "weibull_frailty": {"name": "Weibull PH, shared frailty", "fitter": WeibullFrailty,
                        "effect": "hazard", "frailty": True, "more": True},
    "exponential_frailty": {"name": "Exponential PH, shared frailty", "fitter": ExponentialFrailty,
                            "effect": "hazard", "frailty": True, "more": True},
    "lognormal_frailty": {"name": "Lognormal PH, shared frailty", "fitter": LogNormalFrailty,
                          "effect": "hazard", "frailty": True, "more": True},
    "gamma_frailty": {"name": "Gamma PH, shared frailty", "fitter": GammaFrailty,
                      "effect": "hazard", "frailty": True, "more": True},
    "cox_frailty": {"name": "Cox PH, shared frailty", "fitter": CoxFrailty, "effect": "hazard",
                    "frailty": True, "semi": True, "more": True},
}

REGRESSION = {**SEMI_PARAMETRIC, **FRAILTY}

# Univariate models fitted by their own fitter rather than a distribution's
# ``from_params``; their results are kind "flexible".
FLEXIBLE = {
    "royston_parmar": {"name": "Royston-Parmar (flexible spline)", "fitter": RoystonParmar, "more": True},
}
FLEXIBLE_KIND = "flexible"

GROUP_KEY = "group"

# Step-function regressions: a Cox-like baseline estimated from the data.
_STEP_MODELS = {"AdditiveHazardsModel", "ProportionalOddsModel", "BuckleyJamesModel", "CoxFrailtyModel"}

# What each of these models has no likelihood for, in words (no AIC either).
NO_LIKELIHOOD_NOTE = {
    "additive_hazards": ("Lin and Ying's estimator solves estimating equations rather than maximising a "
                         "likelihood, so there is no log-likelihood, AIC or BIC. Judge it by how well it ranks "
                         "the units (Validation)."),
    "buckley_james": ("Buckley-James iterates least squares on the log times with the error distribution "
                      "left unspecified, so there is no log-likelihood, AIC or BIC. Judge it by how well it "
                      "ranks the units (Validation)."),
}


def is_step_model(model) -> bool:
    """A regression whose baseline is a step function estimated from the data."""
    return type(model).__name__ in _STEP_MODELS


def check_group(distribution: str, mapping: dict, covariates: Optional[list] = None) -> dict:
    """The column mapping with ``group`` checked: required for a frailty
    model, refused for any other (where it would be silently ignored, or
    read as a data column). Raises :class:`backend.fitting.FitError`."""
    from backend.fitting import FitError

    mapping = dict(mapping or {})
    group = mapping.get(GROUP_KEY)
    entry = REGRESSION.get(distribution) or {}
    if entry.get("frailty"):
        if not group:
            raise FitError(f"{entry['name']} needs a Group by column — the site, batch or unit each row "
                           "belongs to, whose shared frailty it estimates.")
        if group in (covariates or []):
            raise FitError(f"'{group}' is the Group by column, so it can't be a covariate too.")
        if group in [v for k, v in mapping.items() if k != GROUP_KEY and v]:
            raise FitError(f"'{group}' is already mapped to another field; Group by needs its own column.")
    elif group:
        raise FitError("Group by applies to the shared-frailty models only — choose one (e.g. "
                       "weibull_frailty), or drop the group column.")
    return mapping


def regression_fit_kwargs(distribution: str, mapping: dict, fit_kwargs: dict) -> dict:
    """``fit_from_df`` keyword arguments for one of these regressions: the
    group column for a frailty model, and the data forms SurPyval doesn't
    take refused in words first. ``fit_kwargs`` is the generic set built by
    ``_fit_regression``."""
    from backend.fitting import FitError

    entry = REGRESSION.get(distribution)
    if entry is None:
        return fit_kwargs
    name = entry["name"]
    if "xl_col" in fit_kwargs:
        raise FitError(f"{name} can't fit interval-censored (inspection) data. Choose a parametric "
                       "regression model (e.g. Weibull PH), which takes the intervals as they are.")
    allowed_trunc = {"tl_col"} if distribution == "proportional_odds" else set()
    trunc = [k for k in ("tl_col", "tr_col") if k in fit_kwargs and k not in allowed_trunc]
    if trunc:
        raise FitError(f"{name} doesn't take truncated (delayed-entry) data. Choose a parametric regression "
                       "model (e.g. Weibull PH) for truncated data.")
    out = dict(fit_kwargs)
    if entry.get("frailty"):
        out["group_col"] = mapping[GROUP_KEY]
    return out


def _f(v) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def summary_rows(model) -> list[dict]:
    """``model.summary()`` as plain rows: the part (baseline, coefficients,
    frailty), the name, the estimate, exp(estimate), its standard error, the
    95% interval and the Wald p-value, None where SurPyval gives none."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            table = model.summary()
    except Exception:  # noqa: BLE001 - a model without a table reports none
        return []
    if not isinstance(table, pd.DataFrame) or table.empty:
        return []
    table = table.reset_index()
    rows = []
    for rec in table.to_dict("records"):
        rows.append({
            "part": str(rec.get("part") or ("coefficients" if "covariate" in rec else "parameters")),
            "name": str(rec.get("name", rec.get("covariate", ""))),
            "value": _f(rec.get("coef")),
            "exp_value": _f(rec.get("exp(coef)")),
            "se": _f(rec.get("se(coef)")),
            "ci": [_f(rec.get("coef lower 95%")), _f(rec.get("coef upper 95%"))]
            if _f(rec.get("coef lower 95%")) is not None else None,
            "p": _f(rec.get("p")),
        })
    return rows


def _frailty_block(model, mapping: dict) -> dict:
    """The shared frailty in plain terms: its variance θ with a 95% interval
    (profile likelihood for a parametric baseline, which stays finite where
    there is no frailty in the data; Wald for Cox), Kendall's τ between two
    units of a group, and each group's estimated frailty."""
    theta = _f(getattr(model, "theta", None))
    method = "lr" if type(model).__name__ == "FrailtyModel" else "wald"
    ci = None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            cb = np.asarray(model.param_cb("theta", alpha_ci=0.05, method=method), dtype=float).ravel()
        if cb.size == 2:
            ci = [_f(cb[0]), _f(cb[1])]
    except Exception:  # noqa: BLE001 - no interval rather than a wrong one
        ci = None
    tau = _f(getattr(model, "kendall_tau", None))
    frailties = getattr(model, "frailties", None) or {}
    groups = sorted(({"label": str(k), "frailty": _f(v)} for k, v in dict(frailties).items()),
                    key=lambda g: -(g["frailty"] or 0.0))
    return {
        "group_column": mapping.get(GROUP_KEY),
        "family": getattr(model, "family", "gamma"),
        "theta": theta,
        "theta_ci": ci,
        "theta_ci_method": "profile likelihood" if method == "lr" else "Wald",
        "kendall_tau": tau,
        "n_groups": int(getattr(model, "n_groups", len(groups)) or len(groups)),
        "groups": groups,
        # Plain words: is there a site effect at all?
        "reading": frailty_reading(theta, ci),
    }


def frailty_reading(theta: Optional[float], ci) -> str:
    """One sentence on whether the groups differ."""
    if theta is None:
        return "The spread between groups couldn't be estimated."
    if ci and ci[0] is not None and ci[0] <= 1e-3:
        return ("The groups may not differ at all: the spread between them (θ) could be zero at 95% "
                "confidence.")
    return ("The groups differ: some fail consistently sooner than others, beyond what the covariates "
            "explain (θ is above zero at 95% confidence).")


def enrich_regression(distribution: str, model, result: dict, mapping: dict) -> dict:
    """What these regressions report beyond the generic fields: the full
    coefficient table, bootstrap intervals for Buckley-James (which has no
    standard errors), the frailty block, a note where there's no likelihood,
    and the calculator's function list cut to the functions the model has."""
    entry = REGRESSION.get(distribution)
    if entry is None:
        return result
    out = dict(result)
    rows = summary_rows(model)
    if rows:
        out["coef_table"] = rows
    p_by_name = {r["name"]: r["p"] for r in rows if r["part"] in ("coefficients", "parameters")}
    coefficients = [dict(c, p=p_by_name.get(c["name"])) if p_by_name.get(c["name"]) is not None else c
                    for c in out.get("coefficients") or []]
    if distribution == "buckley_james" and coefficients and not out.get("no_finite_maximum"):
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                boot = np.asarray(model.bootstrap_ci(alpha_ci=0.05, n_boot=200, random_state=0), dtype=float)
            if boot.shape == (len(coefficients), 2):
                coefficients = [dict(c, ci=[_f(lo), _f(hi)]) for c, (lo, hi) in zip(coefficients, boot)]
                out["ci_method"] = "bootstrap (200 resamples)"
        except Exception:  # noqa: BLE001 - no interval rather than a wrong one
            pass
    out["coefficients"] = coefficients
    if entry.get("frailty"):
        out["frailty"] = _frailty_block(model, mapping)
        # The baseline by its distribution's own parameter names, with
        # SurPyval's interval that stays in the parameter's support (the
        # generic path reads the names off ``model.distribution``, which a
        # frailty model calls ``dist``).
        baseline = [r for r in rows if r["part"] == "baseline"]
        if baseline and len(baseline) == len(out.get("params") or []) and not out.get("no_finite_maximum"):
            out["params"] = [{"name": r["name"], "value": r["value"], "ci": r["ci"]} for r in baseline]
    if entry.get("semi"):
        out["semi_parametric"] = True
    note = NO_LIKELIHOOD_NOTE.get(distribution)
    if note and not out.get("gof"):
        out["gof_note"] = note
    functions = out.get("functions")
    if functions and functions.get("curves"):
        curves = functions["curves"]
        functions = dict(functions)
        functions["meta"] = [m for m in functions.get("meta") or [] if curves.get(m["id"]) is not None]
        out["functions"] = functions
    return out


# ---------------------------------------------------------------------------
# Royston-Parmar (flexible parametric, univariate)
# ---------------------------------------------------------------------------

def _km_estimate(kwargs: dict) -> Optional[dict]:
    """The data's own survival curve (Kaplan-Meier, or Turnbull for
    interval / left-censored or truncated data), for the fit to be read
    against."""
    from surpyval import KaplanMeier, Turnbull

    c = np.asarray(kwargs.get("c", []), dtype=float)
    hard = "xl" in kwargs or "tl" in kwargs or "tr" in kwargs or bool(np.any((c == -1) | (c == 2)))
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            est = (Turnbull if hard else KaplanMeier).fit(**kwargs)
        xs = np.asarray(est.x, dtype=float)
        R = np.asarray(est.R, dtype=float)
        keep = np.isfinite(xs) & np.isfinite(R)
        return {"x": xs[keep].tolist(), "R": R[keep].tolist(), "cb_lower": [], "cb_upper": [],
                "label": "Turnbull" if hard else "Kaplan-Meier"}
    except Exception:  # noqa: BLE001 - the overlay is a convenience
        return None


RP_PARAM_LABELS = "Spline coefficient"


def fit_flexible(distribution: str, df: pd.DataFrame, mapping: dict) -> dict:
    """Fit a Royston-Parmar model (three spline terms on the log cumulative
    hazard, proportional-hazards scale) and build its payload: parameters
    with their intervals, the fitted curves beside the data's own
    Kaplan-Meier curve, the goodness of fit (comparable with the plain
    distributions' AIC on the same data), and B-lives with bounds."""
    from backend import fitting, life_bounds
    from backend.services.method_labels import note_fit

    entry = FLEXIBLE[distribution]
    try:
        kwargs = fitting.build_fit_inputs(df, mapping)
        fitting.check_fittable(kwargs, entry["name"])
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            model = note_fit(entry["fitter"].fit(**kwargs))
        fitting.reissue_deprecations(caught)
        curves = fitting._function_curves(model)
        gof = fitting._goodness_of_fit(model)
    except fitting.FitError:
        raise
    except Exception as exc:
        raise fitting.FitError(str(exc) or type(exc).__name__) from exc

    names = list(getattr(model, "parameter_names", None) or [f"gamma_{i}" for i in range(len(model.params))])
    params = fitting._params_with_uncertainty(model, names)
    unverified = getattr(model, "maximum", "verified") != "verified"
    cache_id = fitting._store_model(model, np.asarray(curves["x"], dtype=float), [])
    result = {
        "distribution": entry["name"],
        "distribution_id": distribution,
        "kind": FLEXIBLE_KIND,
        "params": params,
        "n": int(getattr(model, "n", 0) or len(df)),
        "plot": None,
        "estimate": _km_estimate(kwargs),
        "functions": {"meta": fitting.FUNCTIONS, "curves": curves, "model_id": cache_id},
        "gof": gof,
        "spline": {"knots": [float(k) for k in np.asarray(getattr(model, "knots", []), dtype=float)],
                   "scale": getattr(model, "scale", "hazard"),
                   "n_terms": max(len(params) - 1, 0)},
        "maximum": getattr(model, "maximum", None),
        "fit_ok": not unverified,
    }
    rows = summary_rows(model)
    if rows:
        result["coef_table"] = rows
    if unverified:
        result["fit_warning"] = ("The maximum-likelihood search did not reach a verified maximum; check the "
                                 "curve against the data before relying on it.")
    life = life_bounds.life_for(model)
    if life:
        result["life"] = life
    return result


def picker_flags(entry: dict) -> dict:
    """The model list's flags for one registry entry (``/api/distributions``):
    ``more`` (tucked under "More models"), ``bounded``, ``frailty`` (asks for
    a Group by column) and ``semi`` (a step-function baseline)."""
    return {k: True for k in ("more", "bounded", "frailty", "semi") if entry.get(k)}


def flexible_listing() -> list[dict]:
    """``/api/distributions`` entries for the univariate flexible models."""
    return [{"id": key, "name": entry["name"], "covariates": False, "flexible": True, "params": [],
             **picker_flags(entry)} for key, entry in FLEXIBLE.items()]
