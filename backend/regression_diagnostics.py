"""Does a regression model's assumption hold? (#61)

The checks SurPyval gives a Cox proportional-hazards model, shaped for the
app's Validation tab and the API, with a plain verdict first and the numbers
second:

* the proportional-hazards test (Grambsch-Therneau, ``check_ph``): one row
  per covariate and a GLOBAL row. A small p-value says a covariate's effect
  changes over time, so one hazard ratio misstates it. A parametric PH model
  (Weibull PH, …) makes the same assumption; it is tested with a Cox model on
  the same covariates, the standard test of it;
* robust (sandwich) standard errors, optionally clustered by a column
  (``summary(robust=True, cluster=)``), against the model's own;
* the tie method of a Cox fit (Efron, Breslow, exact or Kalbfleisch-Prentice)
  and a stratified Cox fit (``strata_col``: a baseline hazard per stratum);
* on request, the residuals behind the test (``compute_residuals``: scaled
  Schoenfeld against time, martingale and deviance against the linear
  predictor), thinned for plotting.

Every statistic is SurPyval's. :func:`diagnose` never raises: a check it
can't run comes back as ``{"available": False, "reason": ...}``.

The Cox fit options live here too (``options["cox"]``: ``tie_method``,
``strata``, ``cluster``), with :class:`StratifiedCox`, which lets the rest of
the app evaluate a stratified model as it does any other — the stratum read
from its column in the covariate row.
"""

from __future__ import annotations

import json
import logging
import warnings
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

COX_KEY = "cox"
TIE_METHODS = {
    "efron": "Efron",
    "breslow": "Breslow",
    "exact": "exact",
    "kalbfleisch-prentice": "Kalbfleisch-Prentice",
}
DEFAULT_TIES = "efron"
#: A significance level for the verdicts.
ALPHA = 0.05
#: The proportional-hazards test of a parametric PH model fits a Cox model
#: to the same rows; past this many it isn't run (the fit stays quick).
MAX_AUX_ROWS = 50_000
#: Fewer clusters than this and clustered standard errors aren't trusted.
MIN_CLUSTERS = 10
#: Points per residual plot; more are thinned evenly over the x-axis.
MAX_POINTS = 400
#: Bins of the trend line drawn through the scaled Schoenfeld residuals.
TREND_BINS = 10


class CoxOptionError(ValueError):
    """A Cox fit option that can't be used (a message for the user)."""


# ---------------------------------------------------------------------------
# Cox fit options
# ---------------------------------------------------------------------------

def cox_options_from_form(text: Optional[str]) -> Optional[dict]:
    """The optional ``cox`` form field: a JSON object of Cox fit options,
    ``{"tie_method": "breslow", "strata": "site", "cluster": "unit_id"}``."""
    if not text or not str(text).strip():
        return None
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        raise CoxOptionError('cox must be a JSON object, e.g. {"tie_method": "breslow"}.') from None
    if not isinstance(value, dict):
        raise CoxOptionError('cox must be a JSON object, e.g. {"tie_method": "breslow"}.')
    return value


def with_cox_form(options: Optional[dict], text: Optional[str]) -> Optional[dict]:
    """Fit ``options`` with the ``cox`` form field's options added. A bad
    field raises ``fitting.FitError``, as every other fit option does."""
    from backend.fitting import FitError  # here: fitting imports this module

    try:
        cox = cox_options_from_form(text)
    except CoxOptionError as exc:
        raise FitError(str(exc)) from exc
    if not cox:
        return options
    return {**(options or {}), COX_KEY: cox}


def clean_cox_options(distribution: str, opts, columns, covariates=None) -> dict:
    """``opts`` checked against the data: the tie method one SurPyval knows,
    the strata and cluster columns in ``columns`` and the strata column not a
    covariate. Defaults are dropped, so an all-default spec is ``{}``. Raises
    :class:`CoxOptionError`."""
    if not opts:
        return {}
    if not isinstance(opts, dict):
        raise CoxOptionError("Cox options must be an object.")
    unknown = sorted(set(opts) - {"tie_method", "strata", "cluster"})
    if unknown:
        raise CoxOptionError(f"Unknown Cox option(s): {', '.join(unknown)}. Use tie_method, strata or cluster.")
    out = {}
    ties = str(opts.get("tie_method") or "").strip().lower()
    if ties and ties != DEFAULT_TIES:
        if ties not in TIE_METHODS:
            raise CoxOptionError(f"Unknown tie method '{ties}'. Use one of: {', '.join(TIE_METHODS)}.")
        out["tie_method"] = ties
    for key, what in (("strata", "stratify on"), ("cluster", "cluster by")):
        col = str(opts.get(key) or "").strip()
        if not col:
            continue
        if col not in set(map(str, columns)):
            raise CoxOptionError(f"Can't {what} '{col}': the data has no such column.")
        out[key] = col
    if out and distribution != "cox_ph":
        raise CoxOptionError("Tie methods, strata and clusters apply to Cox PH only. Choose Cox PH, or drop them.")
    if out.get("strata") and out["strata"] in set(covariates or []):
        raise CoxOptionError(f"'{out['strata']}' is a covariate: stratify on a column that isn't one (each "
                             "stratum gets its own baseline hazard instead of a coefficient).")
    return out


def cox_fit_kwargs(opts: dict) -> dict:
    """The extra ``CoxPH.fit_from_df`` keywords for cleaned options."""
    kwargs = {}
    if opts.get("tie_method"):
        kwargs["tie_method"] = opts["tie_method"]
    if opts.get("strata"):
        kwargs["strata_col"] = opts["strata"]
    return kwargs


class StratifiedCox:
    """A stratified Cox model that reads its stratum from the covariate row.

    SurPyval's stratified Cox evaluates one stratum's baseline at a time
    (``sf(x, Z, stratum=)``). Wrapped, ``sf(x, Z)`` works as for any other
    regression model, with the stratum taken from ``Z[column]`` — so the
    calculator, the validation scores, fleets and RBD nodes evaluate it with
    no special case. Rows of ``Z`` pair with ``x`` (or one row serves every
    ``x``), and rows in different strata are evaluated per stratum.
    Everything else is the wrapped model's."""

    # A stratified step curve gives no B-lives (see fitting.regression_metrics_at_defaults).
    qf = None

    def __init__(self, model, column: str):
        self._model = model
        self.strata_column = column
        self._by_text = {str(label): label for label in model.strata_labels}

    def __getattr__(self, name):
        return getattr(self._model, name)

    @property
    def inner(self):
        return self._model

    def _label(self, value):
        key = str(value)
        if key not in self._by_text:
            # A numeric column read back as text ("1.0" for 1).
            try:
                num = float(key)
                key = next((k for k in self._by_text if _same_number(k, num)), key)
            except ValueError:
                pass
        if key not in self._by_text:
            raise ValueError(f"Unknown {self.strata_column} '{value}': the strata are "
                             f"{', '.join(self._by_text)}.")
        return self._by_text[key]

    def _call(self, fn: str, x, Z):
        if not isinstance(Z, pd.DataFrame) or self.strata_column not in Z.columns:
            raise ValueError(f"This Cox model is stratified by {self.strata_column}: give it in the covariates.")
        x = np.atleast_1d(np.asarray(x, dtype=float))
        rest = Z.drop(columns=[self.strata_column])
        labels = [self._label(v) for v in Z[self.strata_column]]
        f = getattr(self._model, fn)
        if len(Z) == 1:
            return np.asarray(f(x, rest, stratum=labels[0]), dtype=float)
        if len(Z) != x.size:
            raise ValueError("Give one covariate row, or one per time.")
        out = np.full(x.size, np.nan)
        keys = np.array([str(lab) for lab in labels])
        for key in np.unique(keys):
            idx = np.flatnonzero(keys == key)
            out[idx] = np.asarray(f(x[idx], rest.iloc[idx], stratum=self._by_text[key]), dtype=float).ravel()
        return out

    def sf(self, x, Z):
        return self._call("sf", x, Z)

    def ff(self, x, Z):
        return self._call("ff", x, Z)

    def hf(self, x, Z):
        return self._call("hf", x, Z)

    def Hf(self, x, Z):
        return self._call("Hf", x, Z)

    def df(self, x, Z):
        return self._call("df", x, Z)


def _same_number(text: str, num: float) -> bool:
    try:
        return float(text) == num
    except ValueError:
        return False


def stratify(model, opts: dict):
    """``model`` wrapped in :class:`StratifiedCox` when it is stratified."""
    column = (opts or {}).get("strata")
    if column and getattr(model, "is_stratified", False):
        return StratifiedCox(model, column)
    return model


def strata_field(df: pd.DataFrame, column: str) -> dict:
    """The calculator input of a strata column: a choice of its levels."""
    values = df[column].dropna()
    levels = sorted({_level_text(v) for v in values})
    mode = values.map(_level_text).mode()
    return {"name": str(column), "type": "category", "options": levels,
            "default": str(mode.iloc[0]) if len(mode) else (levels[0] if levels else ""), "stratum": True}


def _level_text(value) -> str:
    if isinstance(value, (float, np.floating)) and float(value).is_integer():
        return str(int(value))
    return str(value)


# ---------------------------------------------------------------------------
# The checks
# ---------------------------------------------------------------------------

def unavailable(reason: str) -> dict:
    return {"available": False, "reason": reason}


def _num(v) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if np.isfinite(f) else None


def _fmt_p(p: Optional[float]) -> str:
    if p is None:
        return "p not defined"
    return "p < 0.001" if p < 0.001 else f"p = {p:.2g}" if p < 0.01 else f"p = {p:.2f}"


def _names(names: list) -> str:
    names = list(names)
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


def ph_test(cox, source: str = "model", transform: str = "km") -> dict:
    """The Grambsch-Therneau test of ``cox`` (SurPyval's ``check_ph``), with
    a verdict: ``holds`` (no covariate and not the GLOBAL row below
    ``ALPHA``), ``check`` (the GLOBAL row is fine but a covariate isn't) or
    ``fails`` (the GLOBAL row is below ``ALPHA``)."""
    table = cox.check_ph(transform=transform).reset_index()
    rows, glob = [], None
    for rec in table.to_dict("records"):
        row = {"covariate": str(rec["covariate"]), "statistic": _num(rec["statistic"]),
               "df": int(rec["df"]), "p": _num(rec["p"])}
        if row["covariate"] == "GLOBAL":
            glob = row
        else:
            rows.append(row)
    if glob is None or glob["p"] is None:
        return unavailable("The test is undefined here: the failures don't spread over enough distinct times.")
    flagged = [r["covariate"] for r in rows if r["p"] is not None and r["p"] < ALPHA]
    worst = min((r for r in rows if r["p"] is not None), key=lambda r: r["p"], default=None)
    if glob["p"] < ALPHA:
        verdict, tone = "fails", "caveat"
        title = "Hazards don't look proportional"
        who = _names(flagged) if flagged else (worst["covariate"] if worst else "a covariate")
        reading = (f"The effect of {who} seems to change over time ({_fmt_p(glob['p'])} overall), so one "
                   "hazard ratio misstates it. Look at the Schoenfeld residuals; if one trends, stratify on "
                   "that covariate (Cox PH) or try an accelerated-failure-time model.")
    elif flagged:
        verdict, tone = "check", "caveat"
        title = "Mostly proportional; check " + _names(flagged)
        ps = ", ".join(f"{r['covariate']} {_fmt_p(r['p'])}" for r in rows if r["covariate"] in flagged)
        reading = (f"Overall the hazards look proportional ({_fmt_p(glob['p'])}), but the effect of "
                   f"{_names(flagged)} may change over time ({ps}). Check its Schoenfeld residuals for a trend.")
    else:
        verdict, tone = "holds", "good"
        title = "Hazards look proportional"
        reading = (f"No sign that any covariate's effect changes over time ({_fmt_p(glob['p'])} overall): "
                   "one hazard ratio per covariate describes the data.")
    out = {"available": True, "test": "Grambsch-Therneau", "transform": transform, "alpha": ALPHA,
           "rows": rows, "global": glob, "verdict": verdict, "tone": tone, "title": title,
           "reading": reading, "flagged": flagged, "source": source}
    if source == "cox":
        out["source_note"] = ("Tested with a Cox model on the same covariates: the standard test of the "
                              "proportional-hazards assumption this model makes.")
    return out


def robust(cox, cluster: Optional[np.ndarray] = None, cluster_name: Optional[str] = None) -> dict:
    """Robust (sandwich) standard errors of a Cox model next to its own
    (SurPyval's ``summary(robust=True, cluster=)``), with a verdict on how
    far apart they are."""
    plain = cox.summary()
    rob = cox.summary(robust=True, cluster=cluster) if cluster is not None else cox.summary(robust=True)
    rows, worst = [], (0.0, None)
    for name in rob.index:
        se, rse = _num(plain.loc[name, "se(coef)"]), _num(rob.loc[name, "se(coef)"])
        change = (rse / se - 1.0) if se and rse is not None else None
        if change is not None and abs(change) > abs(worst[0]):
            worst = (change, str(name))
        rows.append({
            "covariate": str(name), "coef": _num(rob.loc[name, "coef"]), "ratio": _num(rob.loc[name, "exp(coef)"]),
            "se": se, "robust_se": rse, "change": change,
            "ratio_lower": _num(rob.loc[name, "exp(coef) lower 95%"]),
            "ratio_upper": _num(rob.loc[name, "exp(coef) upper 95%"]),
            "p": _num(rob.loc[name, "p"]),
        })
    out = {"available": True, "rows": rows, "cluster": cluster_name, "max_change": worst[0]}
    by = f", clustered by {cluster_name}" if cluster_name else ""
    pct = abs(worst[0]) * 100
    if cluster is not None:
        k = int(pd.Series(cluster).nunique())
        out["n_clusters"] = k
        if k < MIN_CLUSTERS:
            out.update(tone="caveat", title="Too few clusters to trust",
                       reading=(f"Only {k} {cluster_name} group{'s' if k != 1 else ''}: clustered standard errors "
                                f"need many more (at least {MIN_CLUSTERS}, ideally 30 or more) to be trusted. "
                                "Use the model's own intervals."))
            return out
    if pct < 20:
        out.update(tone="good", title="Close to the model's",
                   reading=(f"The robust standard errors{by} are within {pct:.0f}% of the model's own, so its "
                            "intervals and p-values stand."))
    else:
        out.update(tone="caveat", title="Different from the model's",
                   reading=(f"The robust standard errors{by} differ from the model's by up to {pct:.0f}% "
                            f"({worst[1]}): quote the robust intervals below."))
    return out


def ties(df: pd.DataFrame, mapping: dict, method: str) -> dict:
    """The tie method of a Cox fit, and how many failure times are shared."""
    x = pd.to_numeric(df[mapping["x"]], errors="coerce").to_numpy(dtype=float) if mapping.get("x") else np.array([])
    c = (pd.to_numeric(df[mapping["c"]], errors="coerce").to_numpy(dtype=float)
         if mapping.get("c") else np.zeros(x.size))
    n = (pd.to_numeric(df[mapping["n"]], errors="coerce").to_numpy(dtype=float)
         if mapping.get("n") else np.ones(x.size))
    ok = np.isfinite(x) & (c == 0) & np.isfinite(n) & (n > 0)
    counts = pd.Series(n[ok]).groupby(x[ok]).sum()
    shared = int((counts > 1).sum())
    label = TIE_METHODS.get(method, method)
    if shared == 0:
        reading = "No two failures share a time, so the tie method makes no difference."
    else:
        reading = (f"{shared} failure time{'s are' if shared != 1 else ' is'} shared by more than one unit; "
                   f"{label}'s method handles them" + (" (the default)." if method == DEFAULT_TIES else "."))
    return {"method": method, "label": label, "shared_times": shared, "reading": reading}


def _aux_cox(df: pd.DataFrame, mapping: dict, fit_kwargs: dict):
    """A Cox model on the rows and covariates of a parametric PH fit, for its
    proportional-hazards test; ``(model, None)`` or ``(None, reason)``."""
    from surpyval.univariate.regression import CoxPH

    if mapping.get("xl") or mapping.get("xr"):
        return None, ("Not available for interval (inspection) data: the test needs each failure's exact "
                      "time.")
    if mapping.get("tr"):
        return None, "Not available for right-truncated data."
    if len(df) > MAX_AUX_ROWS:
        return None, f"Not run on more than {MAX_AUX_ROWS:,} rows."
    keep = {k: v for k, v in fit_kwargs.items() if k in ("x_col", "Z_cols", "formula", "c_col", "n_col", "tl_col")}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return CoxPH.fit_from_df(df, **keep), None


def diagnose(model, df: pd.DataFrame, mapping: dict, fit_kwargs: dict, distribution: str, effect: str,
             cox_opts: Optional[dict] = None) -> tuple[dict, object]:
    """The checks of a fitted regression ``model`` (stored with the fit) and
    the Cox model they ran on, kept for :func:`residuals` (None when there is
    none). Never raises."""
    try:
        with warnings.catch_warnings(), np.errstate(all="ignore"):
            warnings.simplefilter("ignore")
            return _diagnose(model, df, mapping, fit_kwargs, distribution, effect, cox_opts or {})
    except Exception as exc:  # noqa: BLE001 - a check is never worth a failed fit
        logger.info("Regression diagnostics failed: %s", exc)
        return {"ph_test": unavailable("These checks couldn't be run for this model.")}, None


def _diagnose(model, df, mapping, fit_kwargs, distribution, effect, cox_opts):
    out: dict = {}
    mapping = {k: v for k, v in (mapping or {}).items() if v}
    cox, source, reason = None, "model", None
    if distribution == "cox_ph":
        cox = getattr(model, "inner", model)
        out["ties"] = ties(df, mapping, cox_opts.get("tie_method") or DEFAULT_TIES)
        if cox_opts.get("strata"):
            column = cox_opts["strata"]
            levels = list(getattr(cox, "strata_labels", []) or [])
            out["strata"] = {"column": column, "levels": [_level_text(v) for v in levels],
                             "reading": (f"Stratified by {column}: each of its {len(levels)} levels has its own "
                                         "baseline hazard, and the covariates' effects are shared.")}
            reason = ("Not available for a stratified Cox model: each stratum has its own baseline hazard. "
                      "Fit it unstratified to test the assumption.")
            out["ph_test"] = unavailable(reason)
            out["robust"] = unavailable(reason)
            return out, None
    elif effect == "hazard":
        cox, reason = _aux_cox(df, mapping, fit_kwargs)
        source = "cox"
    else:
        what = {"aft": "an accelerated-failure-time model: covariates stretch or shrink time",
                "odds": "a proportional-odds model: covariates scale the odds of failure",
                "additive": "an additive-hazards model: covariates add to the hazard"}.get(effect, "this model")
        out["ph_test"] = {"available": False, "applies": False,
                          "reason": f"Doesn't apply: this is {what}, not a proportional-hazards model."}
        return out, None
    if cox is None:
        out["ph_test"] = unavailable(reason or "Not available for this model.")
        return out, None
    try:
        out["ph_test"] = ph_test(cox, source)
    except Exception as exc:  # noqa: BLE001 - the other checks still stand
        out["ph_test"] = unavailable(f"The test couldn't be run: {str(exc).strip() or type(exc).__name__}.")
    if not out["ph_test"].get("available"):
        cox_kept = None  # no test, so no residuals behind it
    else:
        cox_kept = cox
    if distribution == "cox_ph":
        col = cox_opts.get("cluster")
        try:
            cluster = None
            if col:
                cluster = df[col].to_numpy()
                n_fit = len(np.asarray(cox._fit_data["x"])) if hasattr(cox, "_fit_data") else len(df)
                if n_fit != len(cluster):
                    raise ValueError("some rows were dropped from the fit (missing values), so the clusters "
                                     "don't line up with them")
            out["robust"] = robust(cox, cluster, col)
        except Exception as exc:  # noqa: BLE001
            out["robust"] = unavailable(f"Robust standard errors couldn't be computed: "
                                        f"{str(exc).strip() or type(exc).__name__}.")
    return out, cox_kept


# ---------------------------------------------------------------------------
# Residuals, on request
# ---------------------------------------------------------------------------

def _thin(x: np.ndarray, y: np.ndarray, limit: int = MAX_POINTS) -> dict:
    """Up to ``limit`` points spread evenly over ``x`` (sorted), 4 figures."""
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]
    order = np.argsort(x, kind="stable")
    x, y = x[order], y[order]
    if x.size > limit:
        idx = np.unique(np.linspace(0, x.size - 1, limit).round().astype(int))
        x, y = x[idx], y[idx]
    return {"x": [float(f"{v:.4g}") for v in x], "y": [float(f"{v:.4g}") for v in y]}


def _trend(x: np.ndarray, y: np.ndarray, bins: int = TREND_BINS) -> dict:
    """The mean residual in each of ``bins`` groups of equal size along
    ``x``: a guide for the eye (a flat line is what proportional hazards
    looks like), not a statistic."""
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]
    order = np.argsort(x, kind="stable")
    groups = [g for g in np.array_split(order, min(bins, x.size)) if g.size]
    return {"x": [float(np.mean(x[g])) for g in groups], "y": [float(np.mean(y[g])) for g in groups]}


def residuals(cox, source: str = "model") -> dict:
    """The residuals of a Cox model for plotting: scaled Schoenfeld residuals
    against failure time (one panel per covariate, with a trend line and its
    coefficient — the residuals are centred on it), and
    martingale and deviance residuals against the linear predictor."""
    if cox is None:
        return unavailable("No residuals for this model: they come from a Cox model, and this one has none.")
    try:
        return _residuals(cox, source)
    except Exception as exc:  # noqa: BLE001 - a plot is never worth a 500
        logger.info("Residuals failed: %s", exc)
        return unavailable("The residuals couldn't be computed for this model.")


def _residuals(cox, source: str) -> dict:
    with warnings.catch_warnings(), np.errstate(all="ignore"):
        warnings.simplefilter("ignore")
        data = cox._fit_data
        x = np.asarray(data["x"], dtype=float)
        c = np.asarray(data["c"], dtype=float)
        Zm = np.asarray(data["Z"], dtype=float)
        beta = np.asarray(cox.beta, dtype=float).ravel()
        names = list(getattr(cox, "feature_names", None) or [f"b{i}" for i in range(beta.size)])
        t_events = x[c == 0]
        sch = np.asarray(cox.compute_residuals("scaled_schoenfeld"), dtype=float).reshape(t_events.size, -1)
        lp = Zm.reshape(x.size, -1) @ beta
        mart = np.asarray(cox.compute_residuals("martingale"), dtype=float).ravel()
        dev = np.asarray(cox.compute_residuals("deviance"), dtype=float).ravel()
    out = {
        "available": True,
        # Scaled Schoenfeld residuals are centred on the coefficient
        # (Grambsch-Therneau): they read as the effect over time, beta(t).
        "schoenfeld": [{"covariate": names[j], "coef": float(beta[j]), **_thin(t_events, sch[:, j]),
                        "trend": _trend(t_events, sch[:, j])} for j in range(min(len(names), sch.shape[1]))],
        "martingale": _thin(lp, mart),
        "deviance": _thin(lp, dev),
        "n_events": int(t_events.size),
        "n": int(x.size),
        "source": source,
    }
    if source == "cox":
        out["source_note"] = "From a Cox model on the same covariates (the one the proportional-hazards test ran on)."
    return out
