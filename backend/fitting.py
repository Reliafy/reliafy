"""Parametric model fitting and probability-plot data preparation.

Wraps SurPyval's parametric distributions. SurPyval does the heavy lifting
(parameter estimation, plotting positions, confidence bounds); this module
turns a CSV upload plus a column mapping into the ``x/c/n/xl/xr/tl/tr`` inputs
SurPyval expects, and shapes the plot data for a Plotly frontend.

The probability-plot axes are linearised with each distribution's own
``mpp_x_transform`` / ``mpp_y_transform`` so that a good fit plots as a straight
line. Because the transforms are applied here, the frontend can draw every
distribution on plain linear axes.

SurPyval's input model (see ``surpyval.utils.xcnt_handler``):

* ``x``    – observed values (1-D). Used for exact / right / left censored data.
* ``xl`` + ``xr`` – left and right bounds of interval-censored data. Must be
  supplied together and cannot be combined with ``x``.
* ``c``    – censoring flag per row: 0 observed, 1 right, -1 left, 2 interval.
* ``n``    – positive-integer count of observations per row.
* ``tl`` / ``tr`` – left / right truncation bounds per row (``-inf``/``inf``
  meaning untruncated on that side).
"""

from __future__ import annotations

import io
import json
import math
import re
import warnings
import uuid
from collections import OrderedDict
from typing import Optional

import numpy as np
import pandas as pd
from surpyval import (
    Exponential,
    ExponentialPH,
    Gamma,
    GammaPH,
    LogNormal,
    LogNormalPH,
    Normal,
    NormalPH,
    Weibull,
    WeibullPH,
)
from surpyval import ExpoWeibull, Gumbel, Logistic, LogLogistic
from surpyval import GumbelLEV, Rayleigh
from surpyval import MixtureModel
from surpyval.univariate.information_criteria import corrected_aic, ic_sample_size
from surpyval import Binomial, FlemingHarrington, KaplanMeier, NelsonAalen, Turnbull
from surpyval import success_run as _success_run
from surpyval import BetaGeometric, DiscreteWeibull, Geometric, NegativeBinomial, Poisson
from surpyval import (
    ExponentialAFT,
    GammaAFT,
    GumbelAFT,
    LogisticAFT,
    LogNormalAFT,
    NormalAFT,
    WeibullAFT,
)
from surpyval import (
    ExponentialPO,
    GammaPO,
    GumbelPO,
    LogisticPO,
    LogNormalPO,
    NormalPO,
    WeibullPO,
)
from surpyval import (
    ExponentialAH,
    GammaAH,
    GumbelAH,
    LogisticAH,
    LogNormalAH,
    NormalAH,
    WeibullAH,
)
from surpyval import GumbelPH, LogisticPH
from surpyval.univariate.regression import CoxPH

from backend import life_bounds, param_intervals
from backend.units import canonical_unit, unit_in_text
from backend.formula_check import FormulaRejected, check_formula
from backend.model_validation import validate_regression
from backend.services.method_labels import hides_solver_names, note_fit

# Plain distributions (no covariates), keyed by the id used in the API/URL.
# ``offsetable``: supports the 3-parameter offset (failure-free period) —
# only distributions on the half real line; a location shift is meaningless
# for full-real-line supports (Normal, Gumbel, Logistic).
DISTRIBUTIONS = {
    "weibull": {"name": "Weibull", "dist": Weibull, "offsetable": True},
    "exponential": {"name": "Exponential", "dist": Exponential, "offsetable": True},
    "normal": {"name": "Normal", "dist": Normal, "offsetable": False},
    "lognormal": {"name": "Lognormal", "dist": LogNormal, "offsetable": True},
    "gamma": {"name": "Gamma", "dist": Gamma, "offsetable": True},
    "loglogistic": {"name": "LogLogistic", "dist": LogLogistic, "offsetable": True},
    "expo_weibull": {"name": "Exponentiated Weibull", "dist": ExpoWeibull, "offsetable": True},
    "gumbel": {"name": "Gumbel (smallest EV)", "dist": Gumbel, "offsetable": False},
    "gumbel_lev": {"name": "Gumbel (largest EV)", "dist": GumbelLEV, "offsetable": False},
    "logistic": {"name": "Logistic", "dist": Logistic, "offsetable": False},
    "rayleigh": {"name": "Rayleigh", "dist": Rayleigh, "offsetable": True},
}

# Discrete lifetime distributions: for life measured in whole counts — cycles,
# shocks, or demands to failure — rather than continuous time. Same x/c/n
# mapping and standard ``.fit`` interface as the continuous distributions, but
# there's no probability paper (no ``mpp`` transforms), so they produce fitted
# parameters, reliability functions and goodness-of-fit without a probability
# plot. Kept separate from ``DISTRIBUTIONS`` so they don't enter the continuous
# "best fit" comparison, which mixes incompatible supports.
DISCRETE = {
    "discrete_weibull": {"name": "Discrete Weibull", "dist": DiscreteWeibull},
    "geometric": {"name": "Geometric", "dist": Geometric},
    "beta_geometric": {"name": "Beta-Geometric", "dist": BetaGeometric},
    "negative_binomial": {"name": "Negative Binomial", "dist": NegativeBinomial},
    "poisson": {"name": "Poisson", "dist": Poisson},
}

# Non-parametric estimators (no distribution assumed): the "estimation axis"
# of the same single-event life data. Same x/c/n/xl/xr/tl/tr mapping as the
# distributions; produce an empirical survival curve, not fitted parameters.
NONPARAMETRIC = {
    "kaplan_meier": {"name": "Kaplan-Meier", "est": KaplanMeier},
    "nelson_aalen": {"name": "Nelson-Aalen", "est": NelsonAalen},
    "fleming_harrington": {"name": "Fleming-Harrington", "est": FlemingHarrington},
    "turnbull": {"name": "Turnbull", "est": Turnbull},
}

# Regression models (require covariates). Each is fit with ``fitter.fit_from_df``
# using covariate columns or a formula. ``effect`` is what exp(coefficient)
# means: "hazard" (hazard ratio, proportional-hazards) or "aft" (time ratio /
# acceleration factor, accelerated-failure-time).
REGRESSION_MODELS = {
    "weibull_ph": {"name": "Weibull PH", "fitter": WeibullPH, "effect": "hazard"},
    "exponential_ph": {"name": "Exponential PH", "fitter": ExponentialPH, "effect": "hazard"},
    "lognormal_ph": {"name": "Lognormal PH", "fitter": LogNormalPH, "effect": "hazard"},
    "normal_ph": {"name": "Normal PH", "fitter": NormalPH, "effect": "hazard"},
    "gamma_ph": {"name": "Gamma PH", "fitter": GammaPH, "effect": "hazard"},
    "logistic_ph": {"name": "Logistic PH", "fitter": LogisticPH, "effect": "hazard"},
    "gumbel_ph": {"name": "Gumbel PH", "fitter": GumbelPH, "effect": "hazard"},
    "cox_ph": {"name": "Cox PH (semi-parametric)", "fitter": CoxPH, "effect": "hazard"},
    "weibull_aft": {"name": "Weibull AFT", "fitter": WeibullAFT, "effect": "aft"},
    "exponential_aft": {"name": "Exponential AFT", "fitter": ExponentialAFT, "effect": "aft"},
    "lognormal_aft": {"name": "Lognormal AFT", "fitter": LogNormalAFT, "effect": "aft"},
    "normal_aft": {"name": "Normal AFT", "fitter": NormalAFT, "effect": "aft"},
    "gamma_aft": {"name": "Gamma AFT", "fitter": GammaAFT, "effect": "aft"},
    "logistic_aft": {"name": "Logistic AFT", "fitter": LogisticAFT, "effect": "aft"},
    "gumbel_aft": {"name": "Gumbel AFT", "fitter": GumbelAFT, "effect": "aft"},
    "weibull_po": {"name": "Weibull PO", "fitter": WeibullPO, "effect": "odds"},
    "exponential_po": {"name": "Exponential PO", "fitter": ExponentialPO, "effect": "odds"},
    "lognormal_po": {"name": "Lognormal PO", "fitter": LogNormalPO, "effect": "odds"},
    "normal_po": {"name": "Normal PO", "fitter": NormalPO, "effect": "odds"},
    "gamma_po": {"name": "Gamma PO", "fitter": GammaPO, "effect": "odds"},
    "logistic_po": {"name": "Logistic PO", "fitter": LogisticPO, "effect": "odds"},
    "gumbel_po": {"name": "Gumbel PO", "fitter": GumbelPO, "effect": "odds"},
    "weibull_ah": {"name": "Weibull AH", "fitter": WeibullAH, "effect": "additive"},
    "exponential_ah": {"name": "Exponential AH", "fitter": ExponentialAH, "effect": "additive"},
    "lognormal_ah": {"name": "Lognormal AH", "fitter": LogNormalAH, "effect": "additive"},
    "normal_ah": {"name": "Normal AH", "fitter": NormalAH, "effect": "additive"},
    "gamma_ah": {"name": "Gamma AH", "fitter": GammaAH, "effect": "additive"},
    "logistic_ah": {"name": "Logistic AH", "fitter": LogisticAH, "effect": "additive"},
    "gumbel_ah": {"name": "Gumbel AH", "fitter": GumbelAH, "effect": "additive"},
}

# What exp(coefficient) means per regression effect (None = no natural ratio;
# additive-hazards coefficients are additive, shown as the coefficient only).
_RATIO_LABELS = {"hazard": "hazard ratio", "aft": "time ratio", "odds": "odds ratio"}

# Probabilities are clipped away from 0/1 before the y-transform, which would
# otherwise map them to +/- infinity.
_EPS = 1e-12

# In-memory store of fitted regression models so the calculator can re-evaluate
# the reliability functions at user-entered covariate values without re-fitting
# (the model handles its own encoding, including categoricals). Bounded so it
# can't grow without limit; ids are invalidated on process restart.
_MODEL_STORE: "OrderedDict[str, dict]" = OrderedDict()
_MODEL_STORE_MAX = 64


class ModelNotFound(KeyError):
    """Raised when an evaluate request references an unknown/expired model."""


def _store_model(model, grid: np.ndarray, fields: list) -> str:
    model_id = uuid.uuid4().hex
    _MODEL_STORE[model_id] = {"model": model, "grid": grid, "fields": fields}
    while len(_MODEL_STORE) > _MODEL_STORE_MAX:
        _MODEL_STORE.popitem(last=False)
    return model_id


def bind_owner(model_id: str | None, owner: str) -> None:
    """Tie a stored model to the account that fitted it, so the calculator
    endpoints only serve it back to that account."""
    entry = _MODEL_STORE.get(model_id) if model_id else None
    if entry is not None:
        entry["owner"] = owner


def _entry_for(model_id: str, owner: str | None) -> dict:
    """The stored model, or ModelNotFound. With ``owner`` given, an entry
    bound to someone else (or to no one) is treated as not found."""
    entry = _MODEL_STORE.get(model_id)
    if entry is None or (owner is not None and entry.get("owner") != owner):
        raise ModelNotFound(model_id)
    return entry


def serialize_live(cache_id: str) -> dict | None:
    """Serialise a stored live model (surpyval ``to_dict``) plus its evaluation
    grid and covariate fields, so it can be persisted in Mongo and rehydrated
    without re-fitting from the dataset. Returns ``None`` when there's nothing
    serialisable (e.g. a per-demand result has no surpyval model). Never raises —
    a failed serialisation just falls back to refit-on-demand."""
    entry = _MODEL_STORE.get(cache_id)
    if not entry:
        return None
    model = entry.get("model")
    if model is None or not hasattr(model, "to_dict"):
        return None
    try:
        return {
            "model": model.to_dict(),  # BSON-safe per surpyval 0.15+
            "grid": np.asarray(entry.get("grid"), dtype=float).tolist(),
            "fields": entry.get("fields") or [],
        }
    except Exception:  # noqa: BLE001 - never block a save on serialisation
        return None


def restore_live(serialized: dict) -> str:
    """Rehydrate a serialised model (from :func:`serialize_live`) into the live
    store; returns a fresh cache id. Raises on a bad payload — callers fall back
    to refit-on-demand."""
    import surpyval

    model = surpyval.from_dict(serialized["model"])
    grid = np.asarray(serialized.get("grid") or [], dtype=float)
    return _store_model(model, grid, serialized.get("fields") or [])


class FitError(ValueError):
    """Raised when the uploaded data cannot be turned into a fitted model."""


def csv_width(text: str, sep: str = ",") -> int:
    """Number of fields in the first record of CSV ``text`` (0 if empty).
    Counted with the stdlib reader, before pandas builds any columns."""
    import csv

    try:
        return len(next(csv.reader(io.StringIO(text), delimiter=sep), []))
    except csv.Error:
        return 0


def check_csv_shape(width: int, n_rows: int | None = None) -> None:
    """Refuse a table wider than ``MAX_CSV_COLS`` or longer than
    ``MAX_CSV_ROWS`` with a FitError the user can act on."""
    from backend import config

    if width > config.MAX_CSV_COLS:
        raise FitError(
            f"The file has {width:,} columns; the limit is {config.MAX_CSV_COLS:,}. "
            "Remove the columns you don't need and upload it again."
        )
    if n_rows is not None and n_rows > config.MAX_CSV_ROWS:
        raise FitError(
            f"The file has more than {config.MAX_CSV_ROWS:,} rows, the limit. "
            "Split it, or summarise repeated values with a count column."
        )


def read_csv_capped(buf, *, sep: str = ",", width_text: str | None = None, **kwargs) -> pd.DataFrame:
    """``pd.read_csv`` within the shape limits: the header's width is checked
    before parsing, and at most ``MAX_CSV_ROWS`` + 1 rows are read (one more
    than allowed, to tell "at the limit" from "over it"). Raises FitError."""
    from backend import config

    if width_text is not None:
        check_csv_shape(csv_width(width_text, sep if len(sep) == 1 else ","))
    df = pd.read_csv(buf, sep=sep, nrows=config.MAX_CSV_ROWS + 1, **kwargs)
    check_csv_shape(df.shape[1], len(df))
    return df


def _head_text(file_bytes: bytes, limit: int = 1024 * 1024) -> str:
    """The start of the file as text, enough to hold its header row."""
    return bytes(file_bytes[:limit]).decode("utf-8", errors="replace")


def read_dataframe(file_bytes: bytes) -> pd.DataFrame:
    """Parse uploaded bytes as a CSV into a DataFrame, within the
    ``MAX_CSV_COLS`` / ``MAX_CSV_ROWS`` limits."""
    try:
        df = read_csv_capped(io.BytesIO(file_bytes), width_text=_head_text(file_bytes))
    except FitError:
        raise
    except Exception as exc:  # pragma: no cover - pandas raises many types
        raise FitError(f"Could not parse the file as CSV: {exc}") from exc

    if df.empty or df.shape[1] == 0:
        raise FitError("The uploaded CSV is empty.")
    return df


def preview(file_bytes: bytes, rows: int = 5, distinct: bool = False) -> dict:
    """Return column names and a small sample of rows for the mapping UI.

    ``distinct`` adds ``n_unique``: each column's count of distinct non-blank
    values over every row, not just the sample (the degradation wizard checks
    the item id column has at least two items).
    """
    df = read_dataframe(file_bytes)
    columns = [str(c) for c in df.columns]
    sample = (
        df.head(rows)
        .astype(object)
        .where(pd.notna(df.head(rows)), None)
        .values.tolist()
    )
    out = {"columns": columns, "preview": sample, "n_rows": int(df.shape[0])}
    if distinct:
        out["n_unique"] = [int(n) for n in df.nunique(dropna=True).tolist()]
    return out


# The censoring convention, stated once and reused in every message that needs
# to explain it. Getting this backwards is the single most common upload error:
# a spreadsheet where 1 means "this one failed" is the exact inverse of what
# SurPyval (and every other survival tool) expects.
# The last sentence is the web app's remedy; programmatic callers (the MCP
# server) swap it for their own parameter via ``CENSOR_INVERT_HINT``.
CENSOR_INVERT_HINT = (
    "If your column marks failures with a 1, invert it: tick "
    "\"My censor column uses 1 = failed\" under the column mapping."
)
CENSOR_CONVENTION = (
    "Reliafy uses the survival-analysis convention: 0 = the unit failed "
    "(an observed event), 1 = it was still running when observation stopped "
    "(right-censored). " + CENSOR_INVERT_HINT
)

# Fit option that flips a 1 = failed censor column into the convention above.
# Lives in the options dict (and so in a saved model's ``spec.options``) rather
# than the mapping, because the mapping is column *names* only.
CENSOR_INVERT_KEY = "c_invert"

# Censor codes SurPyval understands (see the module docstring).
_CENSOR_CODES = (0, 1, -1, 2)


def invert_censor_column(df: pd.DataFrame, column: str) -> pd.DataFrame:
    """Return a copy of ``df`` with ``column``'s 0/1 flags swapped.

    Only the right-censoring pair is flipped (0 -> 1, 1 -> 0); left (-1) and
    interval (2) codes have no "other way round" and pass through untouched.
    Anything else in the column is refused up front — silently inverting a
    column of 3s and blanks would only move the confusion downstream.
    """
    if column not in df.columns:
        raise FitError(f"Censor column '{column}' isn't in the data.")
    raw = pd.to_numeric(df[column], errors="coerce")
    bad = df[column][raw.isna() | ~raw.isin(_CENSOR_CODES)]
    if len(bad):
        shown = ", ".join(str(v) for v in pd.unique(bad.astype(str))[:5])
        raise FitError(
            f"Censor column '{column}' can only be inverted when it holds "
            f"0/1 (with -1 or 2 for left/interval censoring); found: {shown}. "
            "Fix those values or clear the 1 = failed option."
        )
    out = df.copy()
    out[column] = raw.where(~raw.isin((0, 1)), 1 - raw)
    return out


def failure_count(kwargs: dict) -> tuple[int, int]:
    """(observed failures, total observations) from built fit inputs.

    An observation counts as a failure when its censor flag is 0. Interval and
    left censoring (2 / -1) are events too, but they enter through xl/xr and are
    counted here as observed rather than suspended.
    """
    x = kwargs.get("x")
    xl = kwargs.get("xl")
    total = int(np.size(x if x is not None else xl) or 0)
    c = kwargs.get("c")
    if c is None:
        return total, total
    c = np.asarray(c)
    n = kwargs.get("n")
    weights = np.asarray(n, dtype=float) if n is not None else np.ones_like(c, dtype=float)
    return int(np.sum(weights[c != 1])), int(np.sum(weights))


def check_fittable(kwargs: dict, distribution_name: str) -> None:
    """Refuse a fit that cannot work, with a message that names the likely cause.

    SurPyval guards the all-censored case but raises a bare ``IndexError`` when
    exactly one observation is a failure, which reaches the user as "list index
    out of range". Both cases nearly always mean an inverted censor column.
    """
    failures, total = failure_count(kwargs)
    if total and failures == 0:
        raise FitError(
            f"Every one of the {total} rows is marked as censored, so there is "
            f"nothing for {distribution_name} to fit. " + CENSOR_CONVENTION
        )


def _short_reason(lines: list[str], limit: int = 300) -> str:
    """A candidate's failure reason for ``selection.failed``: its first line,
    cut (if it must be) at a sentence, else a word, boundary — never mid-word."""
    text = lines[0].strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = cut.rfind(". ")
    if end >= limit // 2:
        return cut[:end + 1]
    return cut[:cut.rfind(" ")].rstrip(",;:") + "…"


def data_warnings(kwargs: dict) -> list[str]:
    """Warnings about the data itself that make any fit meaningless even
    when the optimiser reports success — today: every observed failure at the
    same time (zero variance), where no spread-describing distribution is
    identifiable and a "best fit" is decided by which fitters happen to
    converge."""
    x = kwargs.get("x")
    if x is None:
        return []
    x = np.asarray(x, dtype=float)
    c = kwargs.get("c")
    failed = x[np.asarray(c) == 0] if c is not None and np.size(c) == x.size else x
    failed = failed[np.isfinite(failed)]
    if failed.size >= 2 and float(np.ptp(failed)) == 0.0:
        return [
            f"All {failed.size} failure times are identical ({failed[0]:g}): the data has no spread, so no "
            "life distribution's shape can be estimated from it. Treat the fitted parameters and metrics as "
            "meaningless — check the data (units, rounding, a copied column)."
        ]
    return []


def _rows_phrase(rows: np.ndarray, times: np.ndarray, limit: int = 6) -> str:
    """'row 3 (time -1)' / 'rows 3, 7 and 9 (times -1, -2 and inf)', data rows
    counted from 1 under the header, at most ``limit`` named."""
    shown = [int(r) + 1 for r in rows[:limit]]
    vals = [f"{float(t):g}" for t in times[:limit]]
    more = len(rows) - len(shown)

    def join(items):
        if len(items) == 1:
            return items[0]
        return ", ".join(items[:-1]) + " and " + items[-1]

    if len(shown) == 1:
        text = f"row {shown[0]} (time {vals[0]})"
    else:
        text = f"rows {join([str(r) for r in shown])} (times {join(vals)})"
    if more > 0:
        text += f" and {more} more"
    return text


def outside_support_message(
    exc: Exception, times, c, distribution_name: str, support=(0.0, np.inf),
    offset: bool = False,
) -> Optional[str]:
    """A plain sentence naming the rows SurPyval's ``OutsideSupportError``
    refused, or ``None`` for any other error (or when no row can be named).

    SurPyval 0.23 refuses a time *censored* below the support (e.g. -1 on a
    Weibull) as it already refused an observed one (#611, #565): those rows
    used to be fitted and silently ignored. An offset fit also refuses an
    infinite time (#622). ``times``/``c`` are the fit's ``x`` and censoring,
    row for row with the data.
    """
    if type(exc).__name__ != "OutsideSupportError" or times is None:
        return None
    x = np.asarray(times, dtype=float).ravel()
    flags = np.zeros_like(x) if c is None else np.asarray(c, dtype=float).ravel()
    if flags.size != x.size:
        return None
    infinite = np.isinf(x)  # NaN (a blank cell) is another error's business
    lower = -np.inf if offset else float(support[0])
    # A right-censored time AT the lower end is fine ("still running at 0");
    # an observed or left-censored one there, or anything below, is not.
    below = np.isfinite(x) & ((x < lower) | ((x == lower) & (flags != 1)))
    bad = np.flatnonzero(infinite | below)
    if bad.size == 0:
        return None
    rows = _rows_phrase(bad, x[bad])
    one = bad.size == 1
    which = f"an offset {distribution_name}" if offset else f"a {distribution_name}"
    if np.all(infinite[bad]):
        why = ("it can't take an infinite time (a unit still running goes in "
               "as censored at the last time it was seen)")
    else:
        why = (f"it has no probability at or below {lower:g}, so a unit can't "
               "fail, or be censored, there")
    return (f"{rows[0].upper()}{rows[1:]} {'is' if one else 'are'} outside the "
            f"support of {which}: {why}. Correct or remove "
            f"{'that row' if one else 'those rows'} (SurPyval 0.23 refuses "
            f"{'it' if one else 'them'}; older versions silently ignored a "
            "censored one).")


# ---------------------------------------------------------------------------
# No finite maximum (#230)
# ---------------------------------------------------------------------------
# SurPyval 0.23 recognises fits whose likelihood keeps rising as a parameter
# runs off to infinity -- regression and accelerated-life fits (#628), offset
# fits running to the first failure or to a limiting family (#616, #622,
# #599), univariate runaways (#584) -- sets ``model.maximum`` to this and
# warns once, "No finite maximum: <what>. <consequence>; <advice>.".
NO_FINITE_MAXIMUM = "no finite maximum"
_NO_MAXIMUM_PREFIX = "No finite maximum"


def _join_names(names: list) -> str:
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def _runaway_parameters(text: str, coefficient_names: Optional[list]) -> list:
    """The parameters SurPyval's warning says run off, by name."""
    m = re.search(r"coefficient\(s\) \[([\d,\s]+)\]", text)
    if m:  # regression / accelerated life: numbers into the coefficients
        out = []
        for tok in m.group(1).split(","):
            j = int(tok)
            names = coefficient_names or []
            out.append(str(names[j]) if j < len(names) else f"coefficient {j}")
        return out
    m = re.search(r"keeps increasing as (.+?) runs? on", text)
    if m:  # univariate: "alpha (1.2e+05), beta (0.3)" or "gamma (-177)"
        return re.findall(r"([A-Za-z_]\w*) \(", m.group(1))
    if "the offset gamma" in text:
        return ["gamma"]
    return []


def _runaway_suggestion(text: str, kind: str) -> str:
    """SurPyval's advice, in Reliafy's words."""
    m = re.search(r"fit surpyval\.(\w+) instead", text)
    if m:
        limit = m.group(1)
        return (f"Fit a {limit} distribution instead: as the offset runs off, the model "
                f"turns into a {limit}, which fits these data at least as well.")
    if "how='MPS'" in text:
        return ("Fit by maximum product of spacings (MPS), the standard remedy for an offset "
                "fit, or fit without an offset.")
    if kind == "alt":
        return ("Spread the failures across more stress levels: with the failures at too few "
                "of them, the data can't fix how life changes with stress.")
    if "removing or coarsening the covariate" in text:
        return ("A covariate separates the failures from the survivors (for example, a level "
                "with no failures): remove or coarsen it, or collect failures at every level.")
    if "a fit needs a failure observed exactly" in text:
        return "A fit needs at least one failure observed exactly, or known to lie in an interval."
    return "A simpler distribution may describe these data: compare the fits with Best fit."


def no_maximum_notice(model, caught=(), coefficient_names: Optional[list] = None,
                      kind: str = "distribution") -> Optional[dict]:
    """``{maximum, parameters, message, suggestion, detail}`` when ``model``'s
    likelihood has no finite maximum, else ``None``.

    ``caught`` are the warnings recorded during the fit (SurPyval names the
    parameter and the way out there); ``coefficient_names`` name the
    coefficients a regression or accelerated-life warning numbers.
    """
    if getattr(model, "maximum", None) != NO_FINITE_MAXIMUM:
        return None
    text = next((str(w.message) for w in caught
                 if str(w.message).startswith(_NO_MAXIMUM_PREFIX)), "")
    params = _runaway_parameters(text, coefficient_names)
    if params:
        who = _join_names(params)
        verb = "runs" if len(params) == 1 else "run"
        lead = f"These data don't pin down the model: {who} {verb} off to infinity."
    else:
        lead = "These data don't pin down the model: a parameter runs off to infinity."
    return {
        "maximum": NO_FINITE_MAXIMUM,
        "parameters": params,
        "message": lead + " The numbers below aren't estimates.",
        "suggestion": _runaway_suggestion(text, kind),
        "detail": text or None,
    }


def reissue_deprecations(caught) -> None:
    """Re-issue the deprecation warnings a ``catch_warnings(record=True)``
    block swallowed, so a call into SurPyval through a name it has
    deprecated still reaches the warnings filter (and fails the suite run
    with ``-W error::DeprecationWarning``)."""
    for w in caught:
        if issubclass(w.category, (DeprecationWarning, FutureWarning)):
            warnings.warn_explicit(w.message, w.category, w.filename, w.lineno)


def without_intervals(params: list) -> list:
    """Parameters with their standard errors and intervals dropped: with no
    finite maximum they are meaningless (SurPyval says so), and a CI would
    read as an estimate's."""
    return [{**p, "se": None, "ci": None} if "se" in p else {**p, "ci": None} for p in params]


def no_maximum_reason(notice: dict) -> str:
    """One line for Best fit's "failed" list."""
    params = notice.get("parameters") or []
    if params:
        verb = "runs" if len(params) == 1 else "run"
        return f"no finite maximum: {_join_names(params)} {verb} off to infinity"
    return "no finite maximum: a parameter runs off to infinity"


def _fit_failure_hint(exc: Exception, kwargs: dict, distribution_name: str,
                      support=(0.0, np.inf), offset: bool = False) -> str:
    """Turn a fitter blow-up into something a user can act on."""
    support_msg = outside_support_message(
        exc, kwargs.get("x"), kwargs.get("c"), distribution_name, support, offset)
    if support_msg:
        return support_msg
    failures, total = failure_count(kwargs)
    raw = str(exc) or type(exc).__name__
    if total and failures <= 1:
        return (
            f"Only {failures} of the {total} rows is marked as a failure — too "
            f"few for {distribution_name}, which needs at least two observed "
            f"failures to estimate its parameters. " + CENSOR_CONVENTION
        )
    if isinstance(exc, IndexError):
        return (
            f"{distribution_name} couldn't be fitted to this data ({raw}). Check "
            "the column mapping — especially the censoring column."
        )
    return raw


def build_fit_inputs(df: pd.DataFrame, mapping: dict) -> dict:
    """Turn a column mapping into keyword arguments for ``<dist>.fit``.

    ``mapping`` maps any of ``x/c/n/xl/xr/tl/tr`` to a CSV column name. No
    validation is done here — SurPyval validates the combination of inputs and
    raises with a helpful message, which we surface. Columns are coerced to
    numbers (non-numeric cells become NaN, which SurPyval rejects), and blank
    truncation cells become the "untruncated" infinities.
    """
    mapping = {k: v for k, v in mapping.items() if v}  # drop unset fields

    kwargs: dict = {}
    for field, name in mapping.items():
        if name not in df.columns:
            raise FitError(f"The data has no column named '{name}'.")
        col = pd.to_numeric(df[name], errors="coerce").to_numpy(dtype=float)
        if field == "tl":
            col = np.where(np.isnan(col), -np.inf, col)
        elif field == "tr":
            col = np.where(np.isnan(col), np.inf, col)
        kwargs[field] = col

    return kwargs


def _covariance_of(model):
    """A fitted model's parameter covariance as a float array, or ``None``.

    SurPyval 0.23 reads it with ``covariance()``, which raises where there is
    none (a ``from_params`` model, a singular information); ``cov_matrix``,
    its name in 0.22, warns until 0.24 (#605)."""
    method = getattr(model, "covariance", None)
    if not callable(method):
        return None
    try:
        cov = method()
    except Exception:  # noqa: BLE001 - no covariance: no bounds
        return None
    if cov is None:
        return None
    return np.atleast_2d(np.asarray(cov, dtype=float))


def _ensure_covariance(model) -> None:
    """Work around a SurPyval numerical issue so confidence bounds are available.

    For large-scale fits (e.g. a Weibull with a scale parameter in the
    thousands) SurPyval's autograd Hessian can evaluate to NaN, leaving the
    model without a covariance matrix and therefore without confidence bounds.
    When that happens, recompute the covariance as the inverse of a
    finite-difference Hessian of the model's own negative log-likelihood at the
    MLE, using a per-parameter *relative* step so large magnitudes don't
    overflow. The point estimates are untouched — only the (missing) covariance
    is filled in. On any failure the model is left as-is and the band is simply
    omitted.
    """
    cov = _covariance_of(model)
    if cov is not None and np.all(np.isfinite(cov)):
        return  # SurPyval already produced a usable covariance.
    # LFP/ZI fits carry the extra parameter inside the covariance (k+1 square);
    # recomputing over the base params alone would swap in a wrong-shaped
    # matrix and break the confidence bands. Leave those as-is.
    if float(getattr(model, "f0", 0.0) or 0.0) != 0.0:
        return
    if float(getattr(model, "lfp_p", 1.0) or 1.0) != 1.0:
        return
    try:
        params = np.asarray(model.params, dtype=float)
        gamma = float(getattr(model, "gamma", 0.0) or 0.0)
        f0 = float(getattr(model, "f0", 0.0) or 0.0)
        p = float(getattr(model, "lfp_p", 1.0) or 1.0)
        surv_data = model.surv_data
        neg_ll = model.dist._neg_ll_func

        def nll(theta):
            return float(neg_ll(surv_data, *theta, gamma, f0, p))

        n = len(params)
        step = np.maximum(np.abs(params), 1.0) * (np.finfo(float).eps ** (1 / 3)) * 50
        hess = np.empty((n, n))
        for i in range(n):
            for j in range(n):
                ei = np.zeros(n)
                ei[i] = step[i]
                ej = np.zeros(n)
                ej[j] = step[j]
                hess[i, j] = (
                    nll(params + ei + ej)
                    - nll(params + ei - ej)
                    - nll(params - ei + ej)
                    + nll(params - ei - ej)
                ) / (4 * step[i] * step[j])
        recomputed = np.linalg.inv(hess)
        if np.all(np.isfinite(recomputed)) and np.all(np.diag(recomputed) > 0):
            # SurPyval 0.23 keeps the covariance in ``_covariance`` (read by
            # ``covariance()``, saved by ``to_dict``); assigning the old
            # ``cov_matrix`` name warns until 0.24 (#605).
            model._covariance = recomputed
            model.hess_inv = recomputed
    except Exception:  # pragma: no cover - defensive; the band is just omitted
        pass


def failure_positions_mask(model, n_points: int):
    """Mask over ``get_plot_data()``'s ``x_``/``F`` keeping only exact failures.

    On probability paper only failures are plotted; censored units adjust the
    failures' plotting positions but are not points themselves. SurPyval returns
    a position for every observation, giving each censored one the *previous
    failure's* F — which would draw a duplicated, misleading point (and pull the
    apparent fit away from the line). Filter them out.
    """
    data = getattr(model, "data", None)
    c = None
    if isinstance(data, dict):
        c = data.get("c")
    elif data is not None:
        c = getattr(data, "c", None)
    if c is None:
        return np.ones(n_points, dtype=bool)
    c = np.asarray(c).ravel()
    if c.size != n_points:  # counts/aggregation changed the length — don't guess
        return np.ones(n_points, dtype=bool)
    return c == 0


def _expo_weibull_paper_y(p: np.ndarray, mu: float) -> np.ndarray:
    """The Exponentiated Weibull's probability-paper y, ``log(-log(1 - p**(1/mu)))``,
    computed in log space. SurPyval's ``mpp_y_transform`` raises ``p`` to
    ``1/mu`` directly, which underflows to 0 — and the point to −inf — for the
    very small ``mu`` a fit to near-uniform data can reach (SurPyval 0.21's MLE
    finds such corners where 0.20 stopped short). Identical where that is
    finite: with ``a = log(p)/mu``, ``p**(1/mu) = exp(a)`` and, once ``exp(a)``
    underflows, ``log(-log1p(-exp(a))) → a``."""
    a = np.log(p) / float(mu)
    with np.errstate(divide="ignore", over="ignore", invalid="ignore"):
        y = np.log(-np.log1p(-np.exp(a)))
    return np.where(np.isfinite(y), y, a)


def _shape_plot(model, dist, heuristic: str = "Nelson-Aalen", paper_params=None) -> dict:
    """Shape SurPyval's plot data into Plotly-ready (already-linearised) arrays.

    Both axes are transformed with the distribution's own probability-paper
    functions, so the frontend draws on plain linear axes.

    ``paper_params`` overrides the parameters handed to those transforms. It
    exists for mixtures, whose ``params`` is a 2-D (components x parameters)
    array — unpacking that gives a transform a whole row where it expects a
    scalar (Gamma reads ``params[0]`` as its shape). The paper is only a choice
    of axes, so one component's parameters define it perfectly well.
    """
    data = model.get_plot_data(heuristic=heuristic)
    params = model.params if paper_params is None else paper_params

    def ty(p):
        p = np.clip(np.asarray(p, dtype=float), _EPS, 1 - _EPS)
        if dist is ExpoWeibull:
            return _expo_weibull_paper_y(p, params[-1])
        return dist.mpp_y_transform(p, *params)

    def tx(x):
        return dist.mpp_x_transform(np.asarray(x, dtype=float))

    scatter_x = tx(data["x_"])
    scatter_y = ty(data["F"])
    keep = failure_positions_mask(model, scatter_x.size)
    scatter_x, scatter_y = scatter_x[keep], scatter_y[keep]

    line_x = tx(data["x_model"])
    line_y = ty(data["cdf"])

    # A mixture fit has no covariance matrix, so SurPyval returns no bounds
    # column pair — draw the fit without a confidence band rather than failing.
    bounds = np.asarray(data.get("cbs"), dtype=float) if data.get("cbs") is not None else None
    has_bounds = bounds is not None and bounds.ndim == 2 and bounds.shape[1] >= 2
    lower = ty(bounds[:, 0]) if has_bounds else None
    upper = ty(bounds[:, 1]) if has_bounds else None

    x_ticks = tx(data["x_ticks"])
    y_ticks = ty(np.asarray(data["y_ticks"], dtype=float))

    x_range = [
        float(tx(np.array([data["x_scale_min"]]))[0]),
        float(tx(np.array([data["x_scale_max"]]))[0]),
    ]
    y_range = [
        float(ty(np.array([data["y_scale_min"]]))[0]),
        float(ty(np.array([data["y_scale_max"]]))[0]),
    ]

    return {
        "scatter": {"x": scatter_x.tolist(), "y": scatter_y.tolist()},
        "line": {"x": line_x.tolist(), "y": line_y.tolist()},
        "bounds": None if not has_bounds else {
            "x": line_x.tolist(),
            "lower": lower.tolist(),
            "upper": upper.tolist(),
        },
        "x_range": x_range,
        "y_range": y_range,
        "x_ticks": {"vals": x_ticks.tolist(), "labels": list(data["x_ticks_labels"])},
        "y_ticks": {
            "vals": y_ticks.tolist(),
            "labels": list(data["y_ticks_labels"]),
        },
    }


def covariate_units_from_form(text: Optional[str]) -> Optional[dict]:
    """The optional ``covariate_units`` form field (#265): a JSON object,
    ``{"temp_C": "°C"}``; blank gives None."""
    if not text or not str(text).strip():
        return None
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        raise FitError('covariate_units must be a JSON object, e.g. {"temp_C": "°C"}.')
    if not isinstance(value, dict):
        raise FitError('covariate_units must be a JSON object, e.g. {"temp_C": "°C"}.')
    return value


def options_from_form(
    offset: Optional[str] = None,
    zi: Optional[str] = None,
    lfp: Optional[str] = None,
    fixed: Optional[str] = None,
    mixture: Optional[str] = None,
    mixture_distribution: Optional[str] = None,
    how: Optional[str] = None,
    c_invert: Optional[str] = None,
    include_mixtures: Optional[str] = None,
) -> Optional[dict]:
    """Build an options dict from HTML-form string fields (both fit routers)."""

    def truthy(v):
        return str(v or "").strip().lower() in {"1", "true", "yes", "on"}

    opts = {"offset": truthy(offset), "zi": truthy(zi), "lfp": truthy(lfp)}
    if truthy(c_invert):
        opts[CENSOR_INVERT_KEY] = True
    if fixed and str(fixed).strip():
        try:
            opts["fixed"] = json.loads(fixed)
        except json.JSONDecodeError:
            raise FitError('fixed must be valid JSON, e.g. {"beta": 2}.')
    if mixture and str(mixture).strip():
        try:
            opts["mixture"] = int(str(mixture).strip())
        except ValueError:
            raise FitError("mixture must be a whole number of components.")
    if mixture_distribution and str(mixture_distribution).strip():
        opts["mixture_distribution"] = str(mixture_distribution).strip()
    if how and str(how).strip():
        opts["how"] = str(how).strip()
    if truthy(include_mixtures):
        opts["include_mixtures"] = True
    return opts if any(opts.values()) else None


# ---------------------------------------------------------------------------
# Fit methods (SurPyval's ``how=``) and what each distribution / option allows.
#
# Every rule below is SurPyval's, read off ``_validate_fit_inputs`` and then
# confirmed by actually fitting each combination. They are DERIVED, not listed
# by hand: a hand-written capability table is exactly the kind of thing that
# drifts silently when the library moves.
# ---------------------------------------------------------------------------
FIT_METHODS = [
    {"id": "MLE", "name": "Maximum likelihood (MLE)",
     "hint": "The default. Uses all the information in the data, including censoring."},
    {"id": "MPP", "name": "Probability plot (MPP)",
     "hint": "Median-rank regression on probability paper — what a hand-drawn fit does."},
    {"id": "MPS", "name": "Maximum product spacing (MPS)",
     "hint": "Robust where MLE struggles, e.g. small samples or a threshold near the data."},
    {"id": "MSE", "name": "Mean square error (MSE)",
     "hint": "Least squares against the empirical estimate."},
    {"id": "MOM", "name": "Method of moments (MOM)",
     "hint": "Matches the distribution's moments to the sample's. No censoring or truncation."},
]
FIT_METHOD_IDS = [m["id"] for m in FIT_METHODS]
DEFAULT_FIT_METHOD = "MLE"


def _supports_offset(dist) -> bool:
    """SurPyval allows an offset only on a half-line ``[0, inf)`` support."""
    lo, hi = dist.support
    return lo == 0 and math.isinf(hi)


def _supports_zi(dist) -> bool:
    """Zero-inflation needs mass at exactly zero, so the support must start there."""
    return dist.support[0] == 0


def distribution_capabilities(dist_id: str) -> dict:
    """What a plain distribution supports, for the picker and for validation."""
    dist = DISTRIBUTIONS[dist_id]["dist"]
    return {
        "methods": [m for m in FIT_METHOD_IDS
                    if m != "MPP" or bool(getattr(dist, "supports_mpp", True))],
        "offsetable": _supports_offset(dist),
        "zi": _supports_zi(dist),
        "lfp": True,
    }


def methods_for_data(mapping: Optional[dict]) -> dict:
    """Methods the *data* rules out, keyed by method id -> why.

    MOM can't take censoring or truncation; MSE can't take truncation; MPS
    and MPP (without the Turnbull heuristic, which isn't offered) can't take
    interval bounds. Known from the column mapping alone, so the picker can
    grey them out rather than letting the fit fail.
    """
    mapping = mapping or {}
    interval = bool(mapping.get("xl") or mapping.get("xr"))
    censored = bool(mapping.get("c")) or interval
    truncated = bool(mapping.get("tl") or mapping.get("tr"))
    out = {}
    if censored:
        out["MOM"] = "Method of moments doesn't support censored data."
    if interval:
        out["MPS"] = "Maximum product spacing doesn't support interval-censored data."
        out["MPP"] = "Probability plotting doesn't support interval-censored data."
    if truncated:
        out["MOM"] = "Method of moments doesn't support truncation."
        out["MSE"] = "Mean square error doesn't support truncation."
    return out


# Pseudo-distribution id: fit every plain distribution and keep the lowest-AIC.
BEST_ID = "best"


def _normalize_mixture(value) -> int:
    """``mixture`` is the component count: absent/1 means an ordinary single fit."""
    if value in (None, "", False):
        return 0
    try:
        m = int(value)
    except (TypeError, ValueError):
        raise FitError("mixture must be a whole number of components.")
    if m <= 1:
        return 0
    if m > MIXTURE_MAX_COMPONENTS:
        raise FitError(
            f"At most {MIXTURE_MAX_COMPONENTS} mixture components — beyond that "
            "the components stop being identifiable from field data."
        )
    return m


def normalize_options(distribution: str, options: Optional[dict]) -> dict:
    """Validate/clean fit options (offset, zi, lfp, fixed) for a distribution.

    Raises :class:`FitError` on invalid combinations so both routers share the
    same messages.
    """
    opts = dict(options or {})
    out = {
        "offset": bool(opts.get("offset")),
        "zi": bool(opts.get("zi")),
        "lfp": bool(opts.get("lfp")),
        "fixed": opts.get("fixed") or None,
        "mixture": _normalize_mixture(opts.get("mixture")),
        "how": (opts.get("how") or "").strip().upper() or None,
        # Best fit only: let two-component mixtures compete (#236).
        "include_mixtures": bool(opts.get("include_mixtures")),
    }
    if out["include_mixtures"] and distribution != BEST_ID:
        raise FitError(
            "Two-mode mixtures compete only in Best fit — choose Best fit, or the Mixture "
            "model to fit one on purpose."
        )
    if out["how"] == DEFAULT_FIT_METHOD:
        out["how"] = None  # the default carries no information; keep specs clean
    if out["how"] and out["how"] not in FIT_METHOD_IDS:
        raise FitError(
            f"Unknown fit method '{out['how']}'. Choose one of: "
            f"{', '.join(FIT_METHOD_IDS)}."
        )
    if distribution == MIXTURE_ID:
        # SurPyval's MixtureModel.fit takes the data arguments only — there is
        # nowhere to put an offset, a cure fraction or a fixed parameter, so
        # refuse the combination rather than silently dropping it.
        clashes = [k for k in ("offset", "zi", "lfp", "fixed") if out[k]]
        if clashes:
            raise FitError(
                "A mixture can't be combined with "
                f"{', '.join(sorted(clashes))} — fit those on a single distribution."
            )
        if out["how"]:
            raise FitError(
                "A mixture is always fitted by expectation-maximisation — the "
                "fit method can't be chosen for it."
            )
        base = mixture_base(opts)
        if base not in DISTRIBUTIONS:
            raise FitError(
                f"'{base}' can't be mixed. Choose one of: {', '.join(DISTRIBUTIONS)}."
            )
        return {"mixture": out["mixture"] or MIXTURE_DEFAULT_COMPONENTS,
                "mixture_distribution": base}
    if out["mixture"] or opts.get("mixture_distribution"):
        raise FitError(
            "Mixture settings only apply to the Mixture model — select it in the "
            "model list first."
        )
    if not any([out["offset"], out["zi"], out["lfp"], out["fixed"], out["how"],
                out["include_mixtures"]]):
        return {}
    if out["include_mixtures"]:
        # A mixture is fitted by maximum likelihood (EM) with none of these:
        # ranked beside fits that have them, it wouldn't be the same contest.
        clashes = [label for key, label in (
            ("offset", "an offset"), ("zi", "zero-inflation"), ("lfp", "a limited failure population"),
        ) if out[key]]
        if out["how"] and out["how"] != "MLE":
            clashes.append(f"the {out['how']} fit method")
        if clashes:
            raise FitError(
                "Two-mode mixtures are fitted by maximum likelihood with no offset, cure fraction or "
                f"zero-inflation, so they can't compete with {' or '.join(clashes)} — turn "
                f"{'that' if len(clashes) == 1 else 'those'} off, or the mixtures."
            )

    # SurPyval's cross-option rules, enforced here so the message is ours.
    if out["how"] and out["how"] != "MLE" and (out["lfp"] or out["zi"]):
        which = " and ".join(
            n for n, on in (("limited failure population", out["lfp"]),
                            ("zero-inflation", out["zi"])) if on)
        raise FitError(
            f"A model with {which} can only be fitted by maximum likelihood."
        )
    if out["how"] == "MPP" and out["fixed"]:
        raise FitError("Probability plotting (MPP) can't hold parameters fixed.")
    if distribution == BEST_ID:
        if out["fixed"]:
            raise FitError(
                "Fix parameters after choosing a specific distribution — "
                "'Best fit' compares models with different parameter sets."
            )
        # offset applies only to the offsetable candidates; handled per-fit.
        return {k: v for k, v in out.items() if v}
    entry = DISTRIBUTIONS.get(distribution)
    if entry is None:
        raise FitError(
            "Fit options (offset/zi/lfp/fixed) apply to plain distributions only, "
            "not regression models."
        )
    caps = distribution_capabilities(distribution)
    if out["how"] and out["how"] not in caps["methods"]:
        raise FitError(
            f"{entry['name']} can't be fitted by {out['how']}. Available: "
            f"{', '.join(caps['methods'])}."
        )
    if out["zi"] and not caps["zi"]:
        raise FitError(
            f"{entry['name']} can't be zero-inflated — zero-inflation needs a "
            "distribution whose support starts at 0."
        )
    if out["offset"] and not entry.get("offsetable"):
        raise FitError(
            f"{entry['name']} doesn't support an offset — its support is the "
            "whole real line, so a failure-free period isn't meaningful."
        )
    fixed = out["fixed"]
    if fixed is not None:
        if not isinstance(fixed, dict):
            raise FitError('fixed must be an object like {"beta": 2}.')
        names = set(getattr(entry["dist"], "parameter_names", []) or [])
        # Extras can be fixed too when their option is active.
        if out["offset"]:
            names.add("gamma")
        if out["lfp"]:
            names.add("p")
        if out["zi"]:
            names.add("f0")
        unknown = set(fixed) - names
        if unknown:
            raise FitError(
                f"Can't fix {', '.join(sorted(unknown))} — {entry['name']}'s "
                f"parameters are: {', '.join(sorted(names))}."
            )
        try:
            out["fixed"] = {k: float(v) for k, v in fixed.items()}
        except (TypeError, ValueError):
            raise FitError("Fixed parameter values must be numbers.")
    return {k: v for k, v in out.items() if v}


@hides_solver_names
def fit(
    distribution: str,
    df: pd.DataFrame,
    mapping: dict,
    covariates: Optional[list] = None,
    formula: Optional[str] = None,
    unit: Optional[str] = None,
    options: Optional[dict] = None,
    covariate_units: Optional[dict] = None,
) -> dict:
    """Fit ``distribution`` (plain or proportional hazards) and build the payload.

    If ``distribution`` is a regression model it is fit with covariate columns
    (``covariates``) or a ``formula``; otherwise the plain distribution path is
    used. ``unit`` is the (optional) unit of ``x`` carried through for display;
    ``covariate_units`` (optional, regression only) the unit of each covariate,
    ``{"temp_C": "°C"}``, shown with its calculator input and coefficient.
    ``options`` (plain distributions only) may hold ``offset``/``zi``/``lfp``
    booleans and a ``fixed`` mapping. ``options["c_invert"]`` applies to every
    model kind: it flips a 1 = failed censor column into the convention before
    anything (including the all-censored guard) looks at it. Any SurPyval
    error is wrapped in :class:`FitError`.
    """
    options = dict(options or {})
    c_invert = bool(options.pop(CENSOR_INVERT_KEY, False)) and bool(mapping.get("c"))
    if c_invert:
        df = invert_censor_column(df, mapping["c"])
    options = normalize_options(distribution, options)
    if distribution in REGRESSION_MODELS:
        result = _fit_regression(distribution, df, mapping, covariates, formula, covariate_units)
    elif distribution == BEST_ID:
        result = _fit_best(df, mapping, options)
    elif distribution in NONPARAMETRIC:
        result = _fit_nonparametric(distribution, df, mapping)
    elif distribution in DISCRETE:
        result = _fit_discrete(distribution, df, mapping)
    elif distribution == MIXTURE_ID:
        result = _fit_mixture(mixture_base(options), df, mapping,
                              options.get("mixture") or MIXTURE_DEFAULT_COMPONENTS)
    elif distribution in DISTRIBUTIONS:
        result = _fit_distribution(distribution, df, mapping, options)
    else:
        raise FitError(
            f"Unknown model '{distribution}'. Available: "
            f"{', '.join([BEST_ID, *DISTRIBUTIONS, MIXTURE_ID, *DISCRETE, *NONPARAMETRIC, *REGRESSION_MODELS])}."
        )
    result["unit"] = canonical_unit(unit)  # #265: "hours", "hrs" → "Hours"
    if result.get("kind") in ("distribution", "discrete", "regression") and param_intervals.note_for(
            result.get("params")):
        result["ci_note"] = param_intervals.CI_NOTE
    if result.get("mixture_summary") and result["unit"]:
        result["mixture_summary"] = (mixture_summary(result, unit_in_text(result["unit"]))
                                     or result["mixture_summary"])
    if result.get("kind") == "distribution":
        # B-lives and MTTF with their 90% lower bounds (#288).
        entry = _MODEL_STORE.get((result.get("functions") or {}).get("model_id"))
        life = life_bounds.life_for(entry and entry.get("model"), bool(result.get("no_finite_maximum")))
        if life:
            result["life"] = life
    if c_invert:
        # Persist alongside the other fit options so a saved model's spec
        # re-fits the data the same way round (see models_service._refit).
        result["options"] = {**(result.get("options") or {}), CENSOR_INVERT_KEY: True}
    # Confidence bounds and probability-paper transforms can produce non-finite
    # values at the extremes (e.g. a Weibull bound that maps to ±inf/NaN). These
    # are not valid JSON, so coerce them to null — Plotly renders them as gaps.
    return _json_safe(result)


def _json_safe(value):
    """Recursively replace non-finite floats (NaN, ±inf) with ``None`` so the
    payload is valid JSON (``json.dumps`` with ``allow_nan=False``)."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, np.floating):
        f = float(value)
        return f if math.isfinite(f) else None
    if isinstance(value, np.integer):
        return int(value)
    return value


def resolve_distribution_id(name: str) -> str:
    """Map a SurPyval distribution name (or a Reliafy id) to a Reliafy id.

    Accepts 'Weibull', 'weibull', 'LogNormal', 'lognormal', 'ExpoWeibull',
    'expo_weibull', etc. Raises FitError for anything unsupported.
    """
    if not name:
        raise FitError("No distribution given.")
    key = str(name).strip().lower().replace(" ", "_")
    if key in DISTRIBUTIONS:
        return key
    aliases = {
        "expoweibull": "expo_weibull",
        "exponentiatedweibull": "expo_weibull",
        "log_normal": "lognormal",
        "log_logistic": "loglogistic",
    }
    if key in aliases:
        return aliases[key]
    # Match by the human name of each distribution ("Weibull" -> "weibull").
    for did, entry in DISTRIBUTIONS.items():
        if entry["name"].lower().replace(" ", "_") == key:
            return did
    raise FitError(
        f"'{name}' isn't a supported plain distribution. Supported: "
        f"{', '.join(DISTRIBUTIONS)}."
    )


def param_values(distribution_id: str, params: list, where: str = "") -> list[float]:
    """Parameter values of ``params`` in the distribution's own SurPyval order.

    ``params`` is a list of ``{name, value}``. Named parameters must use the
    distribution's SurPyval names (any order, case-insensitive) — an
    unrecognised name such as ``mttf`` or ``scale`` is refused rather than
    read by position, which would silently put the value in the wrong slot.
    A list with no names at all is taken in order (the /api/v1 shorthand
    ``[1200, 2.5]``) but must then have exactly one value per parameter.
    Raises :class:`FitError` naming the valid parameters.
    """
    entry = DISTRIBUTIONS.get(distribution_id) or DISCRETE.get(distribution_id)
    if entry is None:
        raise FitError(
            f"'{distribution_id}' isn't a supported plain distribution. "
            f"Supported: {', '.join(DISTRIBUTIONS)}."
        )
    names = list(getattr(entry["dist"], "parameter_names", []) or [])
    prefix = f"{where}: " if where else ""
    takes = f"{entry['name']} takes the parameters {', '.join(names)}"
    params = list(params or [])
    if not params:
        raise FitError(f"{prefix}no parameter values supplied — {takes}.")

    def number(p) -> float:
        try:
            v = float(p["value"])
        except (KeyError, TypeError, ValueError):
            raise FitError(f"{prefix}parameter '{p.get('name', '?')}' must be a number.") from None
        if not math.isfinite(v):
            raise FitError(f"{prefix}parameter '{p.get('name', '?')}' must be a finite number.")
        return v

    named = [p for p in params if isinstance(p, dict) and p.get("name") not in (None, "")]
    if not named:
        values = [number(p) for p in params]
        if names and len(values) != len(names):
            raise FitError(f"{prefix}{takes} ({len(names)} values), got {len(values)}.")
        return values
    if len(named) != len(params):
        raise FitError(f"{prefix}give every parameter a name, or none — {takes}.")

    lookup = {n.lower(): n for n in names}
    given: dict[str, float] = {}
    unknown = []
    for p in named:
        key = lookup.get(str(p["name"]).strip().lower())
        if key is None:
            unknown.append(str(p["name"]))
            continue
        if key in given:
            raise FitError(f"{prefix}parameter '{key}' is given twice.")
        given[key] = number(p)
    missing = [n for n in names if n not in given]
    if unknown or missing:
        problem = "; ".join(filter(None, (
            f"unknown: {', '.join(unknown)}" if unknown else "",
            f"missing: {', '.join(missing)}" if missing else "",
        )))
        raise FitError(f"{prefix}{takes} (SurPyval names) — {problem}.")
    return [given[n] for n in names]


def result_from_params(
    distribution_id: str,
    params: list,
    extras: Optional[dict] = None,
    unit: Optional[str] = None,
) -> dict:
    """Build a result payload from parameters alone (no data).

    Used by model import when only the fitted parameters are supplied: there
    are no observations, so there's no probability plot or goodness-of-fit —
    but the reliability functions and life metrics are fully available.
    """
    entry = DISTRIBUTIONS.get(distribution_id)
    if entry is None:
        raise FitError(
            f"'{distribution_id}' isn't a supported plain distribution. "
            f"Supported: {', '.join(DISTRIBUTIONS)}."
        )
    dist = entry["dist"]
    values = param_values(distribution_id, params)
    kwargs = {
        k: float(v) for k, v in (extras or {}).items()
        if k in ("gamma", "p", "f0") and v is not None
    }
    try:
        model = dist.from_params(values, **surpyval_extras(kwargs))
    except Exception as exc:
        raise FitError(str(exc) or f"{type(exc).__name__}") from exc

    names = list(getattr(dist, "parameter_names", []) or [f"p{i}" for i in range(len(values))])
    result = {
        "distribution": entry["name"],
        "distribution_id": distribution_id,
        "kind": "distribution",
        "params": [{"name": n, "value": v, "se": None, "ci": None} for n, v in zip(names, values)],
        "n": None,
        "plot": None,
        "functions": {"meta": FUNCTIONS, "curves": _function_curves(model)},
        "gof": [],
        "unit": canonical_unit(unit),
        "params_only": True,
    }
    if kwargs:
        result["extras"] = kwargs
        result["extra_params"] = [{"name": _EXTRA_LABELS[k], "value": v} for k, v in kwargs.items()]
    randomness = _randomness_verdict(distribution_id, result["params"])
    if randomness is not None:
        result["randomness"] = randomness
    life = life_bounds.life_for(model)  # values only: no data, no covariance
    if life:
        result["life"] = life
    return _json_safe(result)


PER_DEMAND_MAX_BATCHES = 500


def _whole(value, what: str) -> int:
    try:
        f = float(value)
    except (TypeError, ValueError):
        raise FitError(f"{what} must be a whole number.") from None
    if not math.isfinite(f) or f != int(f):
        raise FitError(f"{what} must be a whole number.")
    return int(f)


def per_demand_batches(batches) -> list[dict]:
    """Validate ``[{demands, failures, label?}, ...]``: one row per batch of
    demands (a site, a lot, a test campaign). Raises :class:`FitError`."""
    if not isinstance(batches, (list, tuple)) or not batches:
        raise FitError("Give at least one batch of demands and failures.")
    if len(batches) > PER_DEMAND_MAX_BATCHES:
        raise FitError(f"At most {PER_DEMAND_MAX_BATCHES} batches.")
    out = []
    for i, b in enumerate(batches, start=1):
        if not isinstance(b, dict):
            raise FitError(f"Batch {i} must be an object with demands and failures.")
        where = f"Batch {i}" if len(batches) > 1 else "The count"
        demands = _whole(b.get("demands"), f"{where}: demands")
        failures = _whole(b.get("failures"), f"{where}: failures")
        if demands <= 0:
            raise FitError(f"{where}: the number of demands must be a positive whole number."
                           if len(batches) > 1 else "Number of demands must be a positive integer.")
        if not 0 <= failures <= demands:
            raise FitError(f"{where}: failures must be between 0 and its number of demands."
                           if len(batches) > 1 else
                           "Failures must be between 0 and the number of demands.")
        label = str(b.get("label") or b.get("batch") or "").strip()[:80]
        out.append({"label": label or f"Batch {i}", "demands": demands, "failures": failures})
    return out


def per_demand_batches_from_df(df: pd.DataFrame, demands_col: str, failures_col: str,
                               label_col: Optional[str] = None) -> list[dict]:
    """Batches from a dataset: one row per batch. Blank rows are skipped."""
    for col in (demands_col, failures_col, label_col):
        if col and col not in df.columns:
            raise FitError(f"The data has no column named '{col}'.")
    rows = []
    for i, (_, row) in enumerate(df.iterrows(), start=1):
        d, f = row[demands_col], row[failures_col]
        if pd.isna(d) and pd.isna(f):
            continue
        rows.append({"demands": d, "failures": f,
                     "label": str(row[label_col]) if label_col and not pd.isna(row[label_col]) else f"Row {i}"})
    return per_demand_batches(rows)


@hides_solver_names
def result_per_demand(
    demands: Optional[int] = None,
    failures: Optional[int] = None,
    confidence: float = 0.95,
    batches: Optional[list] = None,
) -> dict:
    """Per-demand (Binomial) reliability: probability of failure per demand.

    For one-shot / protective equipment where "reliability" is per demand, not
    over time. From one count (``demands``, ``failures``) or several batches
    of different sizes (``batches``: proof tests from several sites, lots of
    different sizes), pooled into one ``p``: SurPyval 0.23's ``Binomial``
    takes a number of trials per row (#608), and its ``param_cb("p")`` gives
    the **exact** Clopper-Pearson bounds (#580), which hold for unequal
    batches -- the failures in all the demands are binomial in their total.
    Pooling assumes every batch has the same ``p``.

    Reports at ``confidence``: the two-sided interval on ``p`` and on the
    per-demand reliability ``1 - p``, and the one-sided upper bound on ``p``
    (lower bound on reliability). With zero failures that one-sided bound is
    the success-run demonstration, ``R >= (1 - C)**(1/n)`` (59 clean demands
    demonstrate 95% reliability at 95% confidence) -- the same number, now
    from one method. (Before SurPyval 0.23 the interval was Wilson's, at 95%
    whatever the confidence.)
    """
    if batches is None:
        batches = [{"demands": demands, "failures": failures}]
    rows = per_demand_batches(batches)
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        raise FitError("Confidence must be a number between 0 and 1.")
    if not (0.0 < confidence < 1.0):
        raise FitError("Confidence must be between 0 and 1 (e.g. 0.95).")
    alpha = 1.0 - confidence

    n_demands = int(sum(r["demands"] for r in rows))
    n_failures = int(sum(r["failures"] for r in rows))
    model = note_fit(Binomial.fit([r["failures"] for r in rows], n_trials=[r["demands"] for r in rows]))
    p = float(model.params[1])
    lo, hi = (float(v) for v in np.ravel(model.param_cb("p", alpha_ci=alpha)))
    p_upper = float(np.ravel(model.param_cb("p", alpha_ci=alpha, bound="upper"))[0])
    ci = [max(0.0, lo), min(1.0, hi)]

    per_demand = {
        "demands": n_demands, "failures": n_failures,
        "p": p, "ci": ci, "reliability": 1.0 - p,
        "reliability_ci": [1.0 - ci[1], 1.0 - ci[0]],
        "p_upper": p_upper, "reliability_lower": 1.0 - p_upper,
        "confidence": confidence, "method": "exact",
    }
    if len(rows) > 1:
        per_demand["batches"] = [
            {**r, "p": r["failures"] / r["demands"]} for r in rows]
    # Zero-failure demonstration test: the success-run lower bound on reliability.
    if n_failures == 0:
        r_lower = float(_success_run(n_demands, alpha_ci=alpha))
        per_demand["success_run"] = {
            "confidence": confidence,
            "reliability_lower": r_lower,
        }

    return _json_safe({
        "distribution": "Per-demand (Binomial)",
        "distribution_id": "binomial",
        "kind": "per_demand",
        "params": [{"name": "p", "value": p, "se": None, "ci": ci}],
        "n": n_demands,
        "per_demand": per_demand,
        "functions": None,
        "gof": [],
    })


# Best fit's mixture candidates (#236): two components of each, opt-in.
BEST_MIXTURE_BASES = ("weibull", "lognormal")
BEST_MIXTURE_COMPONENTS = 2
MIXTURE_CRITERION = "bic"  # decides only whether the best mixture beats the best single


def _criteria(gof: list) -> dict:
    """``{aic, aic_c, bic}`` from a goodness-of-fit list (finite ones only)."""
    return {g["id"]: float(g["value"]) for g in gof
            if g["id"] in ("aic", "aic_c", "bic") and math.isfinite(float(g["value"]))}


def _fit_best(df: pd.DataFrame, mapping: dict, options: Optional[dict] = None) -> dict:
    """Fit every plain distribution and return the full result for the
    lowest-AIC winner, with the ranking attached as ``selection``.

    The scoring pass is fits-only (no plots); the winner is then refit through
    the normal path so its payload is identical to a direct fit. Options apply
    per candidate where valid (offset only on offsetable distributions).

    With ``include_mixtures`` (#236), two-component Weibull and LogNormal
    mixtures compete too. The single distributions are ranked exactly as
    without them (by AIC); BIC decides only whether the best mixture beats
    the best single distribution — a mixture has more than twice the
    parameters, and AIC's penalty is too light to stop one fitting noise.
    A mixture that wins is listed first; otherwise the singles' ranking
    stands and the mixtures follow it. ``selection.decision`` says which
    criterion decided, in plain words too. A winning mixture's payload is
    the Mixture model's, built from the candidate fit itself.
    """
    options = dict(options or {})
    with_mixtures = bool(options.pop("include_mixtures", False))
    criterion = "aic"  # the single distributions' ranking, mixtures or not
    try:
        base_kwargs = build_fit_inputs(df, mapping)
    except Exception as exc:
        raise FitError(str(exc) or f"{type(exc).__name__}") from exc

    ranking = []
    failed = []
    support_msg = None  # rows every candidate refused (SurPyval 0.23)
    for dist_id, entry in DISTRIBUTIONS.items():
        kwargs = dict(base_kwargs)
        for key in ("zi", "lfp"):
            if options.get(key):
                kwargs[key] = True
        if options.get("offset") and entry.get("offsetable"):
            kwargs["offset"] = True
        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                model = note_fit(entry["dist"].fit(**kwargs), kwargs.get("how"))
            reissue_deprecations(caught)
            scores = _criteria(_goodness_of_fit(model))
        except Exception as exc:
            # A distribution that won't fit this data is skipped — and listed.
            refused = outside_support_message(
                exc, kwargs.get("x"), kwargs.get("c"), entry["name"],
                getattr(entry["dist"], "support", (0.0, np.inf)), bool(kwargs.get("offset")))
            support_msg = support_msg or refused
            failed.append({"id": dist_id, "name": entry["name"],
                           "reason": refused or _short_reason(
                               str(exc).strip().splitlines() or [type(exc).__name__])})
            continue
        no_max = no_maximum_notice(model, caught)
        if no_max:
            # Its numbers aren't estimates, so its AIC ranks nothing (#230).
            failed.append({"id": dist_id, "name": entry["name"],
                           "reason": no_maximum_reason(no_max)})
            continue
        if criterion not in scores:
            failed.append({"id": dist_id, "name": entry["name"],
                           "reason": f"no finite {criterion.upper()}"})
            continue
        ranking.append({"id": dist_id, "name": entry["name"], **scores})

    mixtures = {}  # candidate id -> (base id, fitted SurPyval mixture)
    mixture_ranking = []
    bases = BEST_MIXTURE_BASES if with_mixtures else ()
    for base in bases:
        entry = DISTRIBUTIONS[base]
        cid = f"{MIXTURE_ID}:{base}"
        label = f"{entry['name']} mixture ({BEST_MIXTURE_COMPONENTS} components)"
        try:
            check_fittable(dict(base_kwargs), f"a {entry['name']} mixture")
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                raw = _fit_raw_mixture(entry["dist"], BEST_MIXTURE_COMPONENTS, dict(base_kwargs))
        except Exception as exc:  # noqa: BLE001 - skipped, and listed
            failed.append({"id": cid, "name": label, "reason": _short_reason(
                str(exc).strip().splitlines() or [type(exc).__name__])})
            continue
        if getattr(raw, "maximum", "verified") != "verified":
            # As SurPyval's fit_best sets it aside: a likelihood with no
            # maximum, or a search that stopped short, ranks nothing.
            failed.append({"id": cid, "name": label,
                           "reason": "no finite maximum: a component collapsed onto a point"
                           if raw.maximum == NO_FINITE_MAXIMUM else
                           "its fit is not a verified maximum"})
            continue
        c = np.asarray(raw.data.c, dtype=float)
        nn = np.asarray(raw.data.n, dtype=float)
        fit = _MixtureFit(raw, n_obs=int(nn.sum()), log_likelihood=_mixture_log_likelihood(raw),
                          ic_n=ic_sample_size(c, nn))
        scores = _criteria(_goodness_of_fit(fit))
        if MIXTURE_CRITERION not in scores:
            failed.append({"id": cid, "name": label, "reason": f"no finite {MIXTURE_CRITERION.upper()}"})
            continue
        mixtures[cid] = (base, raw)
        mixture_ranking.append({"id": cid, "name": label, "mixture": BEST_MIXTURE_COMPONENTS,
                                "base_distribution_id": base, **scores})

    if not ranking and not mixture_ranking:
        if support_msg:
            raise FitError(support_msg)
        raise FitError("None of the distributions could be fit to this data.")
    ranking.sort(key=lambda r: r[criterion])
    mixture_ranking.sort(key=lambda r: r[MIXTURE_CRITERION])
    decision = mixture_decision(ranking, mixture_ranking) if with_mixtures else None
    if decision and decision["mixture_wins"]:
        ranking = [mixture_ranking[0], *ranking, *mixture_ranking[1:]]
    else:
        ranking = [*ranking, *mixture_ranking]

    winner = ranking[0]["id"]
    if winner in mixtures:
        base, raw = mixtures[winner]
        result = _fit_mixture(base, df, mapping, BEST_MIXTURE_COMPONENTS, raw=raw)
        summary = mixture_summary(result)
        if summary:
            result["mixture_summary"] = summary
    else:
        win_options = dict(options)
        if win_options.get("offset") and not DISTRIBUTIONS[winner].get("offsetable"):
            win_options.pop("offset")
        result = _fit_distribution(winner, df, mapping, win_options)
    result["selection"] = {"criterion": criterion, "candidates": ranking}
    if with_mixtures:
        result["selection"].update({"include_mixtures": True, "mixture_criterion": MIXTURE_CRITERION,
                                    "decision": decision, "summary": decision["summary"]})
    if failed:
        result["selection"]["failed"] = failed
        result["warnings"] = [
            *(result.get("warnings") or []),
            f"Only {len(ranking)} of the {len(DISTRIBUTIONS) + len(bases)} candidates could be fitted "
            f"(failed: {', '.join(f['name'] for f in failed)}), so the choice is among those only.",
        ]
    return result


def _ic(value: float) -> str:
    return f"{float(value):,.1f}"


def mixture_decision(singles: list, mixtures: list) -> dict:
    """Whether Best fit's best two-mode mixture beats its best single
    distribution (#236), on BIC only: ``{criterion, mixture_wins, mixture,
    single, margin, summary}``, ``margin`` the single's BIC less the
    mixture's (positive when the mixture wins). ``singles`` are ranked by
    AIC, ``mixtures`` by BIC, best first."""
    single = singles[0] if singles else None
    mix = mixtures[0] if mixtures else None
    out = {"criterion": MIXTURE_CRITERION, "mixture_wins": False,
           "mixture": mix["id"] if mix else None, "single": single["id"] if single else None, "margin": None}
    rule = ("The single distributions are ranked by AIC, as without mixtures; BIC decides only whether "
            "a mixture beats the best of them.")
    if mix is None:
        out["summary"] = ("No two-mode mixture could be fitted, so the single distributions are ranked by AIC "
                          "as usual.")
    elif single is None:
        out["mixture_wins"] = True
        out["summary"] = (f"No single distribution could be fitted, so the best two-mode mixture by BIC, "
                          f"the {mix['name']}, is kept.")
    elif MIXTURE_CRITERION not in single:
        out["summary"] = (f"The best single distribution, {single['name']}, has no finite BIC to compare a "
                          f"mixture with, so it is kept. {rule}")
    else:
        margin = float(single[MIXTURE_CRITERION]) - float(mix[MIXTURE_CRITERION])
        out["margin"] = margin
        out["mixture_wins"] = margin > 0
        if margin > 0:
            out["summary"] = (f"A two-mode mixture beats the best single distribution by {_ic(margin)} on BIC: "
                              f"the {mix['name']}, BIC {_ic(mix['bic'])}, against {single['name']}, "
                              f"BIC {_ic(single['bic'])}. {rule}")
        else:
            out["summary"] = (f"No two-mode mixture beats the best single distribution on BIC: "
                              f"{single['name']}, BIC {_ic(single['bic'])}, is ahead of the {mix['name']}, "
                              f"BIC {_ic(mix['bic'])}, by {_ic(-margin)}, so it is kept. {rule}")
    return out


def _num(value: float) -> str:
    """A number for a sentence: two or three significant figures."""
    v = float(value)
    if abs(v) >= 100:
        return f"{v:,.0f}"
    return f"{v:.2g}" if abs(v) < 1 else f"{v:.3g}"


def mixture_summary(result: dict, unit: Optional[str] = None) -> Optional[str]:
    """A two-component mixture in plain words (#236): what share fails early
    and how, and how the rest fail. For a Weibull mixture the shapes say
    whether each mode is early failures, random or wear-out; for any mixture
    each mode's median life is given."""
    if result.get("mixture") != 2:
        return None
    by = {p["name"]: float(p["value"]) for p in result.get("params") or []}
    base = result.get("base_distribution_id")
    unit = f" {unit}" if unit else ""
    try:
        dist = DISTRIBUTIONS[base]["dist"]
        names = list(getattr(dist, "parameter_names", []) or [])
        comps = []
        for j in (1, 2):
            values = [by[f"{name}{j}"] for name in names]
            median = float(np.ravel(dist.qf(0.5, *values))[0])
            comps.append({"w": by[f"weight{j}"], "values": dict(zip(names, values)), "median": median})
    except (KeyError, TypeError, ValueError, IndexError):
        return None
    early, late = sorted(comps, key=lambda comp: comp["median"])
    share = round(100 * early["w"])
    if base == "weibull":
        def mode(beta: float) -> str:
            if beta < 0.95:
                return "early failures"
            if beta <= 1.05:
                return "random failures"
            return "wear-out"
        b_early, b_late = early["values"]["beta"], late["values"]["beta"]
        text = (f"Two failure modes: about {share}% {mode(b_early)} with β ≈ {_num(b_early)} "
                f"(median life {_num(early['median'])}{unit}), the rest {mode(b_late)} with "
                f"β ≈ {_num(b_late)} (median {_num(late['median'])}{unit}).")
    else:
        text = (f"Two failure modes: about {share}% fail early (median life {_num(early['median'])}{unit}), "
                f"the rest later (median {_num(late['median'])}{unit}).")
    return (f"{text} If your records say which mode each failure was, split the data by failure mode "
            "and fit each mode on its own.")


def surpyval_extras(extras: Optional[dict]) -> dict:
    """Reliafy's stored extras as SurPyval ``from_params`` keywords.

    Reliafy keeps the limited-failure proportion as ``p`` -- in saved models,
    the API and MCP -- and SurPyval 0.23 calls it ``lfp_p`` (``p`` warns until
    0.24, then fails; #608). ``lfp_p`` is read too. Offset ``gamma`` and
    zero-inflation ``f0`` keep their names. ``None`` values are dropped."""
    out = {}
    for key, value in (extras or {}).items():
        if value is None:
            continue
        if key in ("p", "lfp_p"):
            out["lfp_p"] = float(value)
        elif key in ("gamma", "f0"):
            out[key] = float(value)
    return out


# Extra fitted quantities from fit options: attribute name -> display label.
_EXTRA_LABELS = {
    "gamma": "gamma (offset)",
    "p": "p (max fraction failing)",
    "f0": "f0 (failed at t=0)",
}


def _extract_extras(model, options: dict) -> dict:
    """Pull the extra fitted quantities (offset gamma, LFP p, ZI f0)."""
    extras = {}
    if options.get("offset"):
        extras["gamma"] = float(getattr(model, "gamma"))
    if options.get("lfp"):
        # Stored as "p", Reliafy's name (API, MCP, saved models); SurPyval
        # 0.23 calls it ``lfp_p`` (#608).
        extras["p"] = float(getattr(model, "lfp_p"))
    if options.get("zi"):
        extras["f0"] = float(getattr(model, "f0"))
    return extras


# Mixtures beyond three components are rarely identifiable from field data —
# the extra weights soak up noise and the components stop meaning anything.
MIXTURE_MAX_COMPONENTS = 4
MIXTURE_DEFAULT_COMPONENTS = 2
MIXTURE_DEFAULT_DISTRIBUTION = "weibull"

# Pseudo-distribution id, like BEST_ID: one entry in the model list. Which
# distribution to mix and how many components are fit *options*, so the picker
# stays one line per concept instead of gaining a near-duplicate of every
# continuous distribution.
MIXTURE_ID = "mixture"


def mixture_base(options: Optional[dict]) -> str:
    """The distribution being mixed, defaulting to Weibull."""
    return (options or {}).get("mixture_distribution") or MIXTURE_DEFAULT_DISTRIBUTION


def _mixture_log_likelihood(model, x=None, c=None, n=None) -> float:
    """Observed-data log-likelihood of a fitted mixture.

    SurPyval's ``MixtureModel.loglike`` was the **EM objective**, not this — it
    is not comparable with a single distribution's log-likelihood, and using it
    for AIC makes a mixture look better than a single fit even on single-mode
    data. So we compute the real thing: each observation contributes the mixed
    density (exact), the mixed survival (right-censored), the mixed CDF
    (left-censored) or the mixed probability of its interval
    (interval-censored), and a truncated observation is conditioned on the
    mixed probability of its truncation window.

    SurPyval 0.23's ``MixtureModel.log_likelihood`` is this same quantity
    (#572); a test holds the two together on every kind of data, so Best fit
    can rank a mixture beside single distributions (#236). With ``x`` omitted
    the data are the ones the mixture was fitted to (with their truncation);
    given ``x`` (``c``, ``n``), the rows are exact / right / left-censored.
    """
    if x is None:
        data = model.data
        x = np.asarray(data.x, dtype=float)
        c = np.asarray(data.c, dtype=float)
        n = np.asarray(data.n, dtype=float)
        t = np.asarray(data.t, dtype=float)
    else:
        x = np.asarray(x, dtype=float)
        c = np.zeros(x.shape[0]) if c is None else np.asarray(c, dtype=float)
        n = np.ones(x.shape[0]) if n is None else np.asarray(n, dtype=float)
        t = None
    rows = x.shape[0]
    lead = x[:, 0] if x.ndim == 2 else x
    trail = x[:, -1] if x.ndim == 2 else x
    tl = np.full(rows, -np.inf) if t is None else t[:, 0]
    tr = np.full(rows, np.inf) if t is None else t[:, 1]
    # As SurPyval reads the rows (#310): a censored row with a finite
    # truncation bound on its censored side is the interval up to that bound.
    left_iv = (c == -1) & np.isfinite(tl)
    right_iv = (c == 1) & np.isfinite(tr)
    interval = (c == 2) | left_iv | right_iv
    lo = np.where(left_iv, tl, lead)
    hi = np.where(right_iv, tr, np.where(c == 2, trail, lead))
    truncated = np.isfinite(tl) | np.isfinite(tr)

    params = np.asarray(model.params, dtype=float).reshape(model.m, -1)
    weights = np.ravel(np.asarray(model.w, dtype=float))
    dist = model.dist

    def cdf_at(v, pj):  # F(v), with F(-inf) = 0 and F(inf) = 1
        finite = np.isfinite(v)
        inner = np.ravel(dist.ff(np.where(finite, v, 0.0), *pj))
        return np.where(finite, inner, np.where(v > 0, 1.0, 0.0))

    dens, surv, cdf, window, kept = (np.zeros(rows) for _ in range(5))
    with np.errstate(all="ignore"):
        for wj, pj in zip(weights, params):
            dens += wj * np.ravel(dist.df(lead, *pj))
            surv += wj * np.ravel(dist.sf(lead, *pj))
            cdf += wj * np.ravel(dist.ff(lead, *pj))
            if interval.any():
                window += wj * (cdf_at(hi, pj) - cdf_at(lo, pj))
            if truncated.any():
                kept += wj * (cdf_at(tr, pj) - cdf_at(tl, pj))
        floor = 1e-300
        like = np.where(interval, window,
                        np.where(c == 0, dens, np.where(c == 1, surv, cdf)))
        ll = np.log(np.clip(like, floor, None))
        if truncated.any():
            ll = ll - np.where(truncated, np.log(np.clip(kept, floor, None)), 0.0)
    total = float(np.sum(n * ll))
    return total if math.isfinite(total) else float("nan")


class _MixtureFit:
    """Gives SurPyval's ``MixtureModel`` the surface the payload builders expect.

    A ``MixtureModel`` has sf/ff/df/mean/get_plot_data but no ``hf`` (derived
    here as f/R), no ``qf`` (inverted numerically, so B-life still works), no
    ``aic``/``bic`` (computed from the real log-likelihood above) and no
    covariance — so parameters come back without confidence intervals, which is
    honest: the fit doesn't produce them.
    """

    def __init__(self, model, n_obs: int, log_likelihood: float, ic_n: float | None = None):
        self._model = model
        self.log_likelihood = log_likelihood
        self._n_obs = int(n_obs)
        # BIC's and AICc's sample size: the observed failures, as SurPyval
        # counts it for every model (ic_sample_size), so a mixture's BIC sits
        # on the same scale as a single distribution's in Best fit (#236).
        self._ic_n = float(n_obs) if ic_n is None else float(ic_n)
        # m components x per-component params, plus m-1 free weights.
        self._k = int(model.m) * int(np.asarray(model.params).reshape(model.m, -1).shape[1]) \
            + int(model.m) - 1

    def __getattr__(self, name):  # delegate everything not overridden
        return getattr(self._model, name)

    def hf(self, x):
        with np.errstate(all="ignore"):
            sf = np.asarray(self._model.sf(x), dtype=float)
            return np.asarray(self._model.df(x), dtype=float) / np.where(sf > 0, sf, np.nan)

    def qf(self, p):
        """Quantiles by bisection on the (monotone) mixed CDF."""
        p = np.atleast_1d(np.asarray(p, dtype=float))
        hi = np.full(p.shape, 1.0)
        with np.errstate(all="ignore"):
            for _ in range(200):  # grow until the CDF exceeds every target
                if np.all(np.ravel(self._model.ff(hi)) >= p) or np.all(hi > 1e12):
                    break
                hi = hi * 2.0
            lo = np.zeros_like(hi)
            for _ in range(100):
                mid = 0.5 * (lo + hi)
                too_low = np.ravel(self._model.ff(mid)) < p
                lo = np.where(too_low, mid, lo)
                hi = np.where(too_low, hi, mid)
        out = 0.5 * (lo + hi)
        return out if out.size > 1 else float(out[0])

    def aic(self) -> float:
        return 2 * self._k - 2 * self.log_likelihood

    def aic_c(self) -> float:
        return corrected_aic(self.aic(), self._k, self._ic_n)

    def bic(self) -> float:
        return self._k * math.log(max(self._ic_n, 1)) - 2 * self.log_likelihood


def _fit_raw_mixture(dist, m: int, kwargs: dict):
    """A SurPyval mixture of ``m`` copies of ``dist`` fitted to ``kwargs``."""
    raw = MixtureModel(dist=dist, m=int(m))
    raw.fit(**kwargs)
    return note_fit(raw)


def _fit_mixture(distribution: str, df: pd.DataFrame, mapping: dict, m: int, raw=None) -> dict:
    """Fit a mixture of ``m`` copies of a plain distribution — two or more
    failure modes muddled into one dataset, which on probability paper is the
    classic S-curve that no single distribution can follow.

    ``distribution`` is the base distribution id whose copies form the mixture.
    ``raw``, a SurPyval mixture already fitted to these data (Best fit's
    candidate), is used as it is rather than fitted again.
    """
    base = distribution
    entry = DISTRIBUTIONS[base]
    dist = entry["dist"]
    kwargs = {}
    try:
        kwargs = build_fit_inputs(df, mapping)
        check_fittable(kwargs, f"a {entry['name']} mixture")
        if raw is None:
            raw = _fit_raw_mixture(dist, m, kwargs)
        # MixtureModel exposes a SurpyvalData object (attribute access), unlike a
        # plain Parametric whose .data is a dict.
        x = np.asarray(raw.data.x, dtype=float)
        nn = np.asarray(raw.data.n, dtype=float) if getattr(raw.data, "n", None) is not None else None
        c = np.asarray(raw.data.c, dtype=float)
        model = _MixtureFit(raw, n_obs=int(np.sum(nn)) if nn is not None else x.shape[0],
                            log_likelihood=_mixture_log_likelihood(raw),
                            ic_n=ic_sample_size(c, nn if nn is not None else np.ones(c.shape[0])))
        # Draw on the paper of the first component — see _shape_plot.
        paper = np.asarray(raw.params, dtype=float).reshape(raw.m, -1)[0]
        plot = _shape_plot(model, dist, heuristic="Nelson-Aalen", paper_params=paper)
        curves = _function_curves(model)
        gof = _goodness_of_fit(model)
    except FitError:
        raise
    except Exception as exc:
        raise FitError(_fit_failure_hint(exc, kwargs, f"a {entry['name']} mixture")) from exc

    base_names = list(getattr(dist, "parameter_names", []) or [])
    values = np.asarray(raw.params, dtype=float).reshape(raw.m, -1)
    weights = np.ravel(np.asarray(raw.w, dtype=float))
    params = []
    for j in range(raw.m):
        for k, name in enumerate(base_names or [f"p{k}" for k in range(values.shape[1])]):
            params.append({"name": f"{name}{j + 1}", "value": float(values[j][k])})
        params.append({"name": f"weight{j + 1}", "value": float(weights[j])})

    cache_id = _store_model(model, np.asarray(curves["x"], dtype=float), [])
    return {
        "distribution": f"{entry['name']} mixture ({raw.m} components)",
        "distribution_id": MIXTURE_ID,
        "base_distribution_id": base,
        "kind": "distribution",
        "mixture": int(raw.m),
        "params": params,
        "n": int(np.sum(nn)) if nn is not None else int(x.shape[0]),
        "plot": plot,
        "functions": {"meta": FUNCTIONS, "curves": curves, "model_id": cache_id},
        "gof": gof,
        # Echoed so the saved spec carries it — models.save_model persists
        # result["options"], and without this a saved mixture would silently
        # refit as a single distribution when reopened.
        "options": {"mixture": int(raw.m), "mixture_distribution": base},
    }


def _fit_distribution(
    distribution: str, df: pd.DataFrame, mapping: dict, options: Optional[dict] = None
) -> dict:
    entry = DISTRIBUTIONS[distribution]
    dist = entry["dist"]
    options = options or {}

    try:
        kwargs = build_fit_inputs(df, mapping)
        check_fittable(kwargs, entry["name"])
        for key in ("offset", "zi", "lfp", "fixed", "how"):
            if options.get(key):
                kwargs[key] = options[key]
        if kwargs.get("fixed") and "p" in kwargs["fixed"]:
            # Reliafy's "p" is SurPyval 0.23's ``lfp_p`` (#608).
            kwargs["fixed"] = {("lfp_p" if k == "p" else k): v for k, v in kwargs["fixed"].items()}
        # Some fitters (MPS in particular) warn that the optimisation failed and
        # then return numbers anyway. Silently handing those to a user is worse
        # than the fit being unavailable, so capture and report it.
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            model = note_fit(dist.fit(**kwargs), kwargs.get("how"))
        reissue_deprecations(caught)
        # No finite maximum (#230): say which parameter runs off, and why.
        no_max = no_maximum_notice(model, caught)
        # SurPyval 0.22 records whether every likelihood fit reached a verified
        # maximum (``model.maximum``); its warning's wording is no longer
        # "... FAILED ...". Older fits only had the warning text.
        # Only a likelihood fit has a maximum to miss: MPS / MPP / MOM fits
        # report "not applicable" (they were flagged as failed before #230).
        unverified = getattr(model, "maximum", "verified") in ("unverified", NO_FINITE_MAXIMUM)
        fit_warning = next(
            (str(w.message) for w in caught
             if "FAILED" in str(w.message).upper() or "verified maximum" in str(w.message)), None
        )
        if unverified and not fit_warning:
            fit_warning = "The maximum-likelihood search did not reach a verified maximum."
        # Backfill the covariance when SurPyval's Hessian came out non-finite
        # (otherwise the confidence band would be all-NaN).
        _ensure_covariance(model)

        # Left (c=-1) and interval (c=2) censoring, and right truncation,
        # require the Turnbull estimator for the empirical plotting positions.
        c = np.asarray(model.data["c"])
        t = model.data.get("t")
        right_truncated = t is not None and np.any(np.isfinite(np.asarray(t, dtype=float)[..., -1]))
        heuristic = ("Turnbull" if np.any((c == -1) | (c == 2)) or right_truncated
                     else "Nelson-Aalen")
        plot = _shape_plot(model, dist, heuristic=heuristic)
        curves = _function_curves(model)
        gof = _goodness_of_fit(model)
    except FitError:
        raise
    except Exception as exc:
        raise FitError(_fit_failure_hint(
            exc, kwargs, entry["name"], getattr(dist, "support", (0.0, np.inf)),
            bool(options.get("offset")))) from exc

    param_names = (
        getattr(model, "parameter_names", None)
        or getattr(dist, "parameter_names", None)
        or [f"p{i}" for i in range(len(model.params))]
    )
    params = _params_with_uncertainty(model, param_names, param_intervals.bounds_of(dist))
    if no_max:
        params = without_intervals(params)

    # Stash the live model so its confidence bounds can be recomputed on demand
    # (configurable level / bound) over the same grid the curves use.
    cache_id = _store_model(model, np.asarray(curves["x"], dtype=float), [])
    result = {
        "distribution": entry["name"],
        "distribution_id": distribution,
        "kind": "distribution",
        "params": params,
        "n": int(np.sum(model.data["n"])),
        "plot": plot,
        "functions": {"meta": FUNCTIONS, "curves": curves, "model_id": cache_id},
        "gof": gof,
    }
    if options:
        # Extra fitted quantities ride separately from ``params`` so every
        # downstream ``from_params(values)`` reconstruction stays valid; the
        # extras are re-applied via keyword arguments where models are rebuilt.
        extras = _extract_extras(model, options)
        if extras:
            result["extras"] = extras
            result["extra_params"] = [
                {"name": _EXTRA_LABELS[k], "value": v} for k, v in extras.items()
            ]
        result["options"] = {
            k: options[k] for k in ("offset", "zi", "lfp", "fixed", "how")
            if options.get(k)
        }
    result["maximum"] = getattr(model, "maximum", None)
    if no_max:
        result["no_finite_maximum"] = no_max
        fit_warning = f"{no_max['message']} {no_max['suggestion']}"
        result["fit_warning"] = fit_warning
        if result.get("plot"):
            # The band comes from the same meaningless covariance.
            result["plot"] = {**result["plot"], "bounds": None}
    elif fit_warning:
        result["fit_warning"] = (
            f"{fit_warning.strip()} The parameters below came back from a fit the "
            "optimiser reported as failed — check them against another method "
            "before relying on them."
        )
    # Explicit flag for programmatic callers: the headline numbers above come
    # from a fit that didn't converge (fit_warning says why).
    result["fit_ok"] = not fit_warning
    notes = data_warnings(kwargs)
    if notes:
        result["warnings"] = notes
    randomness = _randomness_verdict(distribution, params)
    if randomness is not None:
        if fit_warning:
            # #215: no verdict from parameters the optimiser didn't settle on.
            randomness = {**randomness, "verdict": "inconclusive",
                          "reason": "The fit didn't converge, so its shape says nothing about the failure "
                                    "pattern."}
        result["randomness"] = randomness
    return result


# Value-axis columns for a discrete fit (event, interval and truncation
# bounds). All must land on the positive integers; ``n`` is a repeat count and
# is integer by construction, so it's not checked here.
_DISCRETE_AXIS_KEYS = ("x", "xl", "xr", "tl", "tr")


def _validate_discrete_inputs(kwargs: dict) -> None:
    """Discrete distributions live on the positive integers {1, 2, 3, ...}.

    SurPyval accepts floating-point values without complaint and would silently
    fit nonsense, so reject non-integer or sub-1 values up front with a clear
    message (the caller can pick a continuous distribution instead).
    """
    for key in _DISCRETE_AXIS_KEYS:
        if key not in kwargs:
            continue
        arr = np.asarray(kwargs[key], dtype=float)
        arr = arr[np.isfinite(arr)]
        if arr.size == 0:
            continue
        non_integer = np.unique(arr[np.mod(arr, 1) != 0])
        if non_integer.size:
            examples = ", ".join(f"{v:g}" for v in non_integer[:3])
            raise FitError(
                "Discrete distributions need whole-number counts — cycles, shocks "
                f"or demands to failure. Found non-integer values ({examples}). "
                "Round the data to whole numbers, or choose a continuous distribution."
            )
        if np.any(arr < 1):
            raise FitError(
                "Discrete distributions count from 1 (the first cycle or demand); "
                "values below 1 aren't supported. Shift a zero-based count by 1."
            )


def _fit_discrete(distribution: str, df: pd.DataFrame, mapping: dict) -> dict:
    """Fit a discrete lifetime distribution (Discrete Weibull / Geometric /
    Negative Binomial) to whole-count data.

    Same estimation machinery as the continuous distributions — fitted
    parameters (with confidence intervals), reliability functions and
    goodness-of-fit — but discrete models carry no probability-paper
    transforms, so there's no probability plot. Life metrics (median / MTTF /
    B10) come through as for any other model.
    """
    entry = DISCRETE[distribution]
    dist = entry["dist"]
    try:
        kwargs = build_fit_inputs(df, mapping)
        _validate_discrete_inputs(kwargs)
        model = note_fit(dist.fit(**kwargs))
        curves = _function_curves(model)
        gof = _goodness_of_fit(model)
        metrics = _life_metrics(model)
    except Exception as exc:
        raise FitError(str(exc) or f"{type(exc).__name__}") from exc

    param_names = (
        getattr(model, "parameter_names", None)
        or getattr(dist, "parameter_names", None)
        or [f"p{i}" for i in range(len(model.params))]
    )
    params = _params_with_uncertainty(model, param_names, param_intervals.bounds_of(dist))

    cache_id = _store_model(model, np.asarray(curves["x"], dtype=float), [])
    return {
        "distribution": entry["name"],
        "distribution_id": distribution,
        "kind": "discrete",
        "params": params,
        "n": int(np.sum(model.data["n"])),
        "plot": None,
        "functions": {"meta": FUNCTIONS, "curves": curves, "model_id": cache_id},
        "gof": gof,
        "metrics": metrics,
    }


def _fit_nonparametric(distribution: str, df: pd.DataFrame, mapping: dict) -> dict:
    """Fit a non-parametric survival estimator (KM/NA/FH/Turnbull).

    Produces an empirical step survival curve with confidence bounds instead
    of fitted parameters — no probability plot, no goodness-of-fit. The
    reliability functions (sf/ff via interpolation) and life metrics are
    still available, so the model reads back like any other in the calculator.
    """
    entry = NONPARAMETRIC[distribution]
    est = entry["est"]
    try:
        kwargs = build_fit_inputs(df, mapping)
        model = note_fit(est.fit(**kwargs))
        xs = np.asarray(model.x, dtype=float)
        R = np.asarray(model.R, dtype=float)
        try:
            cb = np.asarray(model.cb(model.x, on="sf", alpha_ci=0.05), dtype=float)
            lower, upper = cb[:, 0], cb[:, 1]
        except Exception:  # not all estimators expose bounds for all data
            lower = upper = np.full_like(R, np.nan)
        curves = _function_curves(model)
        metrics = _life_metrics(model)
    except Exception as exc:
        raise FitError(str(exc) or f"{type(exc).__name__}") from exc

    finite = np.isfinite(xs)
    # Stash the live estimator so downstream consumers (RBD) can resolve it via
    # the same refit-on-demand path regression models use (get_live_model).
    cache_id = _store_model(model, np.asarray(curves["x"], dtype=float), [])
    return {
        "distribution": entry["name"],
        "distribution_id": distribution,
        "kind": "nonparametric",
        "params": [],
        "n": int(np.asarray(model.data["n"]).sum()) if hasattr(model, "data") else int(finite.sum()),
        "estimate": {
            "x": [float(v) for v in xs[finite]],
            "R": [float(v) for v in R[finite]],
            "cb_lower": [None if not np.isfinite(v) else float(v) for v in lower[finite]],
            "cb_upper": [None if not np.isfinite(v) else float(v) for v in upper[finite]],
        },
        "functions": {"meta": FUNCTIONS, "curves": curves, "model_id": cache_id},
        "gof": [],
        "metrics": metrics,
    }


def _life_metrics(model) -> dict:
    """Median / MTTF / B10 from any model exposing qf() and mean()."""
    def q(p):
        try:
            v = float(np.asarray(model.qf(p)).ravel()[0])
            return v if np.isfinite(v) else None
        except Exception:
            return None
    try:
        mttf = float(model.mean())
        mttf = mttf if np.isfinite(mttf) else None
    except Exception:
        mttf = None
    return {"median": q(0.5), "b10": q(0.1), "mttf": mttf}


def _params_with_uncertainty(model, param_names, bounds: Optional[dict] = None) -> list[dict]:
    """Parameter estimates with standard errors and 95% Wald CIs from the
    fit's covariance matrix.

    ``bounds`` (``{name: (lower, upper)}``, SurPyval's declared parameter
    bounds) puts a positive parameter's interval on the log scale and a
    (0, 1) one's on the logit scale, so neither leaves its support: a small
    sample's Weibull shape no longer gets a negative lower bound (#265). An
    unbounded parameter keeps ``value ± 1.96·se``.
    """
    values = np.atleast_1d(np.asarray(model.params, dtype=float))
    ses = [None] * len(values)
    cov = _covariance_of(model)
    if cov is not None:
        if cov.shape == (len(values), len(values)) and np.all(np.isfinite(cov)):
            diag = np.diag(cov)
            ses = [float(np.sqrt(d)) if d > 0 else None for d in diag]

    bounds = bounds or {}
    out = []
    for name, value, se in zip(param_names, values, ses):
        entry = {"name": name, "value": float(value)}
        if se is not None and math.isfinite(se):
            entry["se"] = se
            lower, upper = (tuple(bounds.get(name) or ()) + (None, None))[:2]
            entry["ci"] = param_intervals.wald_interval(float(value), se, lower, upper)
        else:
            entry["se"] = None
            entry["ci"] = None
        out.append(entry)
    return out


def _randomness_verdict(distribution_id: str, params: list[dict]) -> dict | None:
    """Whether the fitted model is consistent with random (constant-rate)
    failures — the statistical evidence behind a run-to-failure decision.

    Weibull: read the shape parameter's 95% CI against 1. Exponential: random
    by construction (memoryless). Other distributions can't establish this and
    return no block.
    """
    if distribution_id == "exponential":
        return {"verdict": "random", "basis": "memoryless"}
    if distribution_id != "weibull":
        return None

    beta = next((p for p in params if p["name"] == "beta"), None)
    if beta is None:
        return None
    block = {"basis": "beta_ci", "beta": beta["value"], "beta_ci": beta.get("ci")}
    ci = beta.get("ci")
    if not ci:
        block["verdict"] = "inconclusive"
    elif ci[0] <= 1.0 <= ci[1]:
        block["verdict"] = "random"
    elif ci[0] > 1.0:
        block["verdict"] = "wear_out"
    else:
        block["verdict"] = "infant_mortality"
    return block


def _fit_regression(
    distribution: str,
    df: pd.DataFrame,
    mapping: dict,
    covariates: Optional[list],
    formula: Optional[str],
    covariate_units: Optional[dict] = None,
) -> dict:
    entry = REGRESSION_MODELS[distribution]
    fitter = entry["fitter"]
    mapping = {k: v for k, v in mapping.items() if v}

    # Only pass columns that were actually mapped — not every fitter (e.g. Cox)
    # accepts every optional column keyword. Inspection (interval-censored)
    # data maps ``xl``/``xr`` in place of ``x`` (#237): SurPyval 0.23's
    # ``fit_from_df`` takes them as ``xl_col``/``xr_col`` (#571), the same
    # model as ``fit`` with a two-column ``x``.
    interval = bool(mapping.get("xl") or mapping.get("xr"))
    if interval:
        if not (mapping.get("xl") and mapping.get("xr")) or mapping.get("x"):
            raise FitError("Map the failure time to x, or inspection data to both xl (the last inspection "
                           "it passed) and xr (the one that found it failed), not both.")
        if distribution == "cox_ph":
            raise FitError("Cox PH can't fit interval-censored (inspection) data: its partial likelihood "
                           "needs each failure's exact time. Choose a parametric regression model (e.g. "
                           "Weibull PH), which takes the intervals as they are.")
        fit_kwargs = {"xl_col": mapping["xl"], "xr_col": mapping["xr"]}
    else:
        fit_kwargs = {"x_col": mapping.get("x")}
    for field, kw in (("c", "c_col"), ("n", "n_col"), ("tl", "tl_col"), ("tr", "tr_col")):
        if mapping.get(field):
            fit_kwargs[kw] = mapping[field]
    if formula:
        try:
            fit_kwargs["formula"] = check_formula(formula, df.columns)
        except FormulaRejected as exc:
            raise FitError(str(exc)) from exc
    elif covariates:
        fit_kwargs["Z_cols"] = list(covariates)

    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            model = note_fit(fitter.fit_from_df(df, **fit_kwargs))
        reissue_deprecations(caught)
        gof = _goodness_of_fit(model)
    except Exception as exc:
        x_col, c_col = mapping.get("x") or mapping.get("xl"), mapping.get("c")
        msg = None
        if x_col in df.columns:
            base = getattr(fitter, "distribution", None)
            msg = outside_support_message(
                exc, pd.to_numeric(df[x_col], errors="coerce").to_numpy(dtype=float),
                pd.to_numeric(df[c_col], errors="coerce").to_numpy(dtype=float)
                if c_col in df.columns else None,
                entry["name"], getattr(base, "support", (0.0, np.inf)))
        raise FitError(msg or str(exc) or f"{type(exc).__name__}") from exc

    params_arr = np.asarray(model.params, dtype=float)
    k_dist = int(getattr(model, "k_dist", 0) or 0)

    # Standard errors (baseline params then coefficients) for 95% Wald intervals.
    # Unavailable for semi-parametric Cox / when the Hessian is singular.
    try:
        ses = np.asarray(model.standard_errors(), dtype=float).ravel()
        if ses.size != params_arr.size:
            ses = None
    except Exception:  # noqa: BLE001
        ses = None

    def _ci(i, bounds=(None, None)):
        if ses is None or not np.isfinite(ses[i]):
            return None
        # A positive baseline parameter's interval on the log scale (#265);
        # the coefficients are unbounded, so theirs is symmetric.
        return param_intervals.wald_interval(float(params_arr[i]), float(ses[i]), *bounds[:2])

    # Baseline distribution parameters (empty for semi-parametric Cox).
    base_dist = getattr(model, "distribution", None)
    base_names = getattr(base_dist, "parameter_names", None) or [
        f"p{i}" for i in range(k_dist)
    ]
    base_bounds = param_intervals.bounds_of(base_dist)
    baseline = [
        {"name": name, "value": float(params_arr[i]),
         "ci": _ci(i, tuple(base_bounds.get(name) or (None, None)))}
        for i, name in enumerate(base_names)
    ]

    # Regression coefficients with a 95% CI. exp(coefficient) is a hazard ratio
    # (PH), time ratio (AFT) or odds ratio (PO); additive-hazards coefficients
    # have no natural ratio, so ``ratio``/``ratio_label`` are omitted for AH.
    # ``ratio_label`` in the payload tells the UI which; ``hazard_ratio`` is kept
    # for backward compatibility with saved models.
    effect = entry.get("effect", "hazard")
    ratio_label = _RATIO_LABELS.get(effect)  # None for additive hazards
    feature_names = getattr(model, "feature_names", None) or [
        f"b{i}" for i in range(len(params_arr) - k_dist)
    ]
    coefficients = []
    for j, name in enumerate(feature_names):
        value = float(params_arr[k_dist + j])
        coef = {"name": name, "value": value, "ci": _ci(k_dist + j)}
        if ratio_label is not None:
            coef["ratio"] = float(np.exp(value))
            coef["hazard_ratio"] = coef["ratio"]  # backward compat
        coefficients.append(coef)

    x_col = mapping.get("x") or mapping.get("xl")
    x_vals = (
        pd.to_numeric(df[x_col], errors="coerce").dropna().to_numpy()
        if x_col
        else np.array([])
    )
    n = int(x_vals.size)
    if interval:
        # The calculator's grid reaches the latest finite inspection bound.
        upper = pd.to_numeric(df[mapping["xr"]], errors="coerce").to_numpy(dtype=float)
        x_vals = np.concatenate([x_vals[np.isfinite(x_vals)], upper[np.isfinite(upper)]])

    # Build the calculator: derive the raw covariate input fields, a time grid,
    # and the function curves at the default covariate values. Stash the model
    # so the frontend can re-evaluate at other covariate values.
    raw_vars = _raw_covariates(model, covariates)
    fields = _covariate_fields(df, raw_vars)
    units = clean_covariate_units(covariate_units, raw_vars)
    if units:
        # Optional units (#265): on each calculator input and on the
        # coefficient of a covariate entered as it is (per unit of it).
        fields = [{**f, "unit": units[f["name"]]} if f["name"] in units else f for f in fields]
        coefficients = [{**c, "covariate_unit": units[c["name"]]} if c["name"] in units else c
                        for c in coefficients]
    hi = float(x_vals.max()) * 1.2 if x_vals.size else 1.0
    grid = np.linspace(0.0, hi, 300)
    default_row = pd.DataFrame({f["name"]: [f["default"]] for f in fields})
    try:
        curves = _eval_functions(model, grid, default_row if fields else None)
    except Exception:
        curves = None
    model_id = _store_model(model, grid, fields)

    functions = None
    if curves is not None:
        functions = {
            "meta": FUNCTIONS,
            "curves": curves,
            "covariates": fields,
            "model_id": model_id,
        }

    no_max = no_maximum_notice(model, caught, list(feature_names), kind="regression")
    extra = {"no_finite_maximum": no_max} if no_max else {}
    if no_max:
        baseline, coefficients = without_intervals(baseline), without_intervals(coefficients)
    if distribution == "cox_ph" and gof:
        # SurPyval 0.23 gives Cox its maximised *partial* likelihood, with AIC
        # and BIC on it (R's logLik.coxph; #604). Those compare Cox models on
        # the same data only, never a Cox model with a parametric one: say so
        # on every number.
        partial = {"log_likelihood": "Log partial likelihood"}
        gof = [{**g, "label": partial.get(g["id"], f"{g['label']} (partial)"), "partial": True}
               for g in gof]
        extra["gof_note"] = (
            "A Cox model's log-likelihood, AIC and BIC are on its partial likelihood: compare them "
            "only with other Cox models on the same data, never with a parametric model's.")
    # #265: a regression model has no single median / B10 / MTTF — they
    # depend on the covariates. Say so, and give them at the covariate means
    # (the calculator's defaults), clearly labelled.
    extra["metrics_note"] = REGRESSION_METRICS_NOTE
    if not no_max:
        at_means = regression_metrics_at_defaults(model, fields)
        if at_means is not None:
            extra["at_covariate_means"] = at_means
    if units:
        extra["covariate_units"] = units
    return {
        **extra,
        "maximum": getattr(model, "maximum", None),
        "distribution": entry["name"],
        "distribution_id": distribution,
        "kind": "regression",
        "effect": effect,
        "ratio_label": ratio_label,
        "params": baseline,
        "coefficients": coefficients,
        "n": n,
        **({"interval_censored": True} if interval else {}),
        "gof": gof,
        "functions": functions,
        # How good is this model? Harrell's C, Brier score, AUC (#176).
        "validation": validate_regression(model, df, mapping, raw_vars),
    }


def _raw_covariates(model, covariates: Optional[list]) -> list:
    """Names of the raw covariate columns the model was fit on."""
    spec = getattr(model, "_model_spec", None)
    required = getattr(spec, "required_variables", None)
    if required:
        return list(required)
    return list(covariates or [])


REGRESSION_METRICS_NOTE = (
    "Regression model: life metrics depend on the covariates; use reliability_at with covariates, "
    "or the model's covariate means.")


def clean_covariate_units(units, names=None) -> dict:
    """``{covariate: unit}`` from an optional mapping (#265): units trimmed,
    blanks dropped and, when ``names`` is given, only the model's own
    covariates kept. Not a dict (or empty): {}."""
    from backend.units import clean_label_unit

    if not isinstance(units, dict):
        return {}
    keep = set(names) if names is not None else None
    out = {}
    for name, unit in units.items():
        name, unit = str(name).strip(), clean_label_unit(unit)
        if name and unit and (keep is None or name in keep):
            out[name] = unit
    return out


def regression_metrics_at_defaults(model, fields: list) -> Optional[dict]:
    """A parametric regression model's median, B10 and MTTF at the covariate
    row the calculator opens on (each numeric covariate at its training-data
    mean, a categorical one at its most common level), labelled with that
    row; None for a model without a quantile function (Cox) or when they
    can't be computed."""
    qf = getattr(model, "qf", None)
    if not callable(qf):
        return None
    Z = pd.DataFrame({f["name"]: [f["default"]] for f in fields}) if fields else None
    try:
        with np.errstate(all="ignore"), warnings.catch_warnings():
            warnings.simplefilter("ignore")
            q = np.asarray(qf(np.array([0.5, 0.1, 1e-6, 1.0 - 1e-9]), Z), dtype=float).ravel()
            median, b10, lo, hi = (float(v) for v in q[:4])
            mttf = None
            if np.isfinite(lo) and np.isfinite(hi) and 0 < lo < hi:
                # The mean life, ∫ S(t) dt, on a geometric grid to where
                # S ≈ 1e-9 (fine near 0 and over a long tail alike).
                t = np.concatenate([[0.0], np.geomspace(lo, hi, 4000)])
                s = np.asarray(model.sf(t, Z), dtype=float).ravel()
                if s.size == t.size and np.all(np.isfinite(s)):
                    mttf = float(np.trapezoid(s, t)) if hasattr(np, "trapezoid") else float(np.trapz(s, t))
    except Exception:  # noqa: BLE001 - a convenience: absent rather than wrong
        return None

    def _ok(v):
        return v if v is not None and np.isfinite(v) and v >= 0 else None

    return {
        "median": _ok(median), "b10": _ok(b10), "mttf": _ok(mttf),
        "covariates": [{"name": f["name"], "value": f["default"],
                        "basis": "mean" if f.get("type") == "number" else "most common level",
                        **({"unit": f["unit"]} if f.get("unit") else {})} for f in fields],
        "label": "At the training data's covariate means (a categorical covariate at its most common level).",
    }


def _covariate_fields(df: pd.DataFrame, raw_vars) -> list:
    """Describe each covariate input for the calculator (type + default)."""
    raw = set(raw_vars)
    fields = []
    for col in df.columns:  # df order for stable presentation
        if col not in raw:
            continue
        series = df[col]
        if pd.api.types.is_numeric_dtype(series):
            mean = pd.to_numeric(series, errors="coerce").mean()
            fields.append(
                {
                    "name": str(col),
                    "type": "number",
                    "default": round(float(mean), 4) if pd.notna(mean) else 0.0,
                }
            )
        else:
            values = series.dropna().astype(str)
            options = sorted(values.unique().tolist())
            mode = values.mode()
            default = str(mode.iloc[0]) if len(mode) else (options[0] if options else "")
            fields.append(
                {
                    "name": str(col),
                    "type": "category",
                    "options": options,
                    "default": default,
                }
            )
    return fields


def _custom_grid(grid, x_min=None, x_max=None) -> np.ndarray:
    """A grid over ``[x_min, x_max]`` at the stored grid's resolution, so the
    calculator can recompute the curves out to (or in to) a chosen x-axis limit.
    A ``None`` bound keeps the stored grid's end; an invalid range is ignored."""
    g = np.asarray(grid, dtype=float)
    if x_min is None and x_max is None:
        return g
    lo = float(x_min) if x_min is not None else float(g[0])
    hi = float(x_max) if x_max is not None else float(g[-1])
    if not (np.isfinite(lo) and np.isfinite(hi)) or hi <= lo:
        return g
    n = int(g.size) if g.size >= 2 else 300
    return np.linspace(lo, hi, n)


def evaluate(model_id: str, values: dict, x_min=None, x_max=None, *, owner: str | None = None) -> dict:
    """Re-evaluate the reliability functions at given covariate ``values``,
    optionally over a custom ``[x_min, x_max]`` grid. ``owner`` restricts the
    lookup to a model bound to that account (see :func:`bind_owner`)."""
    entry = _entry_for(model_id, owner)
    model, fields = entry["model"], entry["fields"]
    grid = _custom_grid(entry["grid"], x_min, x_max)

    row = {}
    for f in fields:
        value = values.get(f["name"], f["default"])
        if f["type"] == "number":
            try:
                value = float(value)
            except (TypeError, ValueError):
                value = float(f["default"])
        else:
            value = str(value)
        row[f["name"]] = [value]

    df_row = pd.DataFrame(row) if row else None
    try:
        curves = _eval_functions(model, grid, df_row)
    except Exception as exc:
        raise FitError(str(exc) or f"{type(exc).__name__}") from exc
    return {"curves": curves}


# Reliability functions confidence bounds can be computed on, and the bound
# types SurPyval's ``cb`` accepts.
_CB_FUNCTIONS = {"sf", "ff", "hf", "Hf", "df"}
_CB_BOUNDS = {"two-sided", "lower", "upper"}


def confidence_bounds(
    model_id: str,
    on: str = "sf",
    alpha_ci: float = 0.05,
    bound: str = "two-sided",
    x_min=None,
    x_max=None,
    *,
    owner: str | None = None,
) -> dict:
    """Confidence bounds of a fitted model's ``on`` function over its grid.

    Wraps SurPyval's ``model.cb`` — configurable significance ``alpha_ci`` and
    ``bound`` (two-sided / lower / upper). Available for plain, discrete and
    non-parametric models; regression (proportional-hazards) models don't
    expose confidence bounds. Two-sided returns both arrays; a one-sided bound
    returns just the relevant side (the other is ``None``).
    """
    if on not in _CB_FUNCTIONS:
        raise FitError(f"Can't compute confidence bounds on '{on}'.")
    if bound not in _CB_BOUNDS:
        raise FitError(f"Unknown bound '{bound}' — use two-sided, lower or upper.")
    if not 0.0 < alpha_ci < 1.0:
        raise FitError("Confidence level must be between 0% and 100% (exclusive).")

    entry = _entry_for(model_id, owner)
    model = entry["model"]
    grid = _custom_grid(entry["grid"], x_min, x_max)
    if not hasattr(model, "cb"):
        raise FitError("This model type doesn't provide confidence bounds.")

    try:
        with np.errstate(all="ignore"), warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            cb = _cb_off_pinned_points(model, grid, on, alpha_ci, bound)
    except Exception as exc:
        raise FitError(str(exc) or f"{type(exc).__name__}") from exc

    def _col(a):
        return [None if not np.isfinite(v) else float(v) for v in np.asarray(a, dtype=float)]

    if cb.ndim == 2:  # two-sided → columns [lower, upper]
        lower, upper = _col(cb[:, 0]), _col(cb[:, 1])
    elif bound == "lower":
        lower, upper = _col(cb), None
    else:  # upper
        lower, upper = None, _col(cb)

    return {
        "x": grid.tolist(),
        "on": on,
        "alpha_ci": alpha_ci,
        "bound": bound,
        "lower": lower,
        "upper": upper,
    }


def _cb_off_pinned_points(model, grid, on, alpha_ci, bound) -> np.ndarray:
    """``model.cb`` over ``grid``, leaving out the points where a parametric
    model's reliability is pinned at 1 or 0 (before a lifetime's support
    starts, at t = 0): its value there is certain, so the bound is the value
    itself. Asked there, SurPyval 0.23's Wald bound has a zero variance it
    calls undefined, and returns nan at every point of the call — a lognormal's
    calculator lost its whole band to the grid's t = 0."""
    if not hasattr(model, "dist"):
        return np.asarray(model.cb(grid, on=on, alpha_ci=alpha_ci, bound=bound), dtype=float)
    sf = np.asarray(model.sf(grid), dtype=float)
    free = np.isfinite(sf) & (sf > 0) & (sf < 1)
    if free.all() or not free.any():
        return np.asarray(model.cb(grid, on=on, alpha_ci=alpha_ci, bound=bound), dtype=float)
    inner = np.asarray(model.cb(grid[free], on=on, alpha_ci=alpha_ci, bound=bound), dtype=float)
    value = np.asarray(getattr(model, on)(grid[~free]), dtype=float)
    out = np.empty((grid.size, 2) if inner.ndim == 2 else grid.size, dtype=float)
    out[free] = inner
    out[~free] = value[:, None] if inner.ndim == 2 else value
    return out


# The reliability functions exposed in the calculator tab, with display labels.
FUNCTIONS = [
    {"id": "sf", "label": "Survival / reliability, R(t)"},
    {"id": "ff", "label": "Unreliability / CDF, F(t)"},
    {"id": "hf", "label": "Hazard rate, h(t)"},
    {"id": "Hf", "label": "Cumulative hazard, H(t)"},
    {"id": "df", "label": "Density, f(t)"},
]


def _eval_functions(model, grid, Z=None) -> dict:
    """Evaluate sf/ff/hf/Hf/df over ``grid`` (optionally at covariates ``Z``).

    Additive-hazards models allow the hazard — and thus the cumulative hazard —
    to go negative, which makes sf = exp(-H) exceed 1 (an impossible reliability).
    We do NOT silently clamp that away: the fit is unreliable and the user should
    pick a different model form. Instead we flag it with ``curves["warning"]`` so
    the calculator can show it, while returning the true (out-of-range) values.
    """
    grid = np.asarray(grid, dtype=float)
    curves = {"x": grid.tolist()}
    raw = {}
    for fn in ("sf", "ff", "hf", "Hf", "df"):
        with np.errstate(all="ignore"):
            func = getattr(model, fn)
            y = np.asarray(func(grid) if Z is None else func(grid, Z), dtype=float)
        raw[fn] = y
        # JSON can't carry inf/nan; null them so the frontend skips those points.
        curves[fn] = [None if not np.isfinite(v) else float(v) for v in y]

    Hf, sf = raw["Hf"], raw["sf"]
    negative_hazard = bool(
        (np.isfinite(Hf) & (Hf < -1e-9)).any() or (np.isfinite(sf) & (sf > 1.0 + 1e-6)).any()
    )
    if negative_hazard:
        curves["warning"] = (
            "The cumulative hazard goes negative here, so the reliability rises "
            "above 1 — which is impossible. This additive-hazards fit is unreliable "
            "at these covariate values; try a proportional-hazards (…_ph / cox_ph) "
            "or accelerated-failure-time (…_aft) model instead."
        )
    return curves


def _function_curves(model, points: int = 300) -> dict:
    """Evaluate sf/ff/hf/Hf/df over a grid from 0 to the 99th quantile."""
    try:
        hi = float(model.qf(0.99))
    except Exception:
        hi = None
    lfp = float(getattr(model, "lfp_p", 1.0) or 1.0)
    if (hi is None or not np.isfinite(hi)) and lfp < 1.0:
        # A limited failure population never reaches F = 0.99 (only lfp_p
        # ever fails): span 99% of the failures that do happen. Without
        # this a params-only LFP model (no data to fall back on) failed.
        try:
            hi = float(model.qf(0.99 * lfp))
        except Exception:
            hi = None
    if (hi is None or not np.isfinite(hi) or hi <= 0) and getattr(model, "data", None) is None:
        hi = 1.0
    if hi is None or not np.isfinite(hi) or hi <= 0:
        # Fall back to the data range if the quantile is unavailable.
        xd = np.asarray(model.data["x"], dtype=float)
        xd = xd[np.isfinite(xd)]
        hi = float(xd.max()) * 1.5 if xd.size else 1.0
    return _eval_functions(model, np.linspace(0.0, hi, points))


def _goodness_of_fit(model) -> list:
    """Collect goodness-of-fit metrics as labelled, ordered entries."""

    def _value(attr):
        v = getattr(model, attr, None)
        if callable(v):  # aic/aic_c/bic are methods; log_likelihood is not
            try:
                v = v()
            except Exception:
                return None
        return v

    # Plain distributions expose log_likelihood; regression models expose the
    # negative log-likelihood instead, so fall back to that.
    ll = _value("log_likelihood")
    if ll is None:
        nll = _value("_neg_ll")
        ll = -nll if nll is not None else None

    candidates = [
        ("log_likelihood", "Log-likelihood", ll),
        ("aic", "AIC", _value("aic")),
        ("aic_c", "AICc", _value("aic_c")),
        ("bic", "BIC", _value("bic")),
    ]

    out = []
    for id_, label, value in candidates:
        if value is None:
            continue
        try:
            value = float(value)
        except (TypeError, ValueError):
            continue
        if np.isfinite(value):
            out.append({"id": id_, "label": label, "value": value})
    return out


# Backwards-compatible helper used in tests / simple callers.
def extract_times(file_bytes: bytes, column: Optional[str] = None) -> np.ndarray:
    """Read a CSV and pull out a single column of failure times as ``x``."""
    df = read_dataframe(file_bytes)
    if column is None:
        for name in df.columns:
            coerced = pd.to_numeric(df[name], errors="coerce")
            if coerced.notna().any():
                column = name
                break
        if column is None:
            raise FitError("No numeric column found in the CSV.")
    kwargs = build_fit_inputs(df, {"x": column})
    return kwargs["x"]
