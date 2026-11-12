"""Uncertainty and forecasts for repairable-system (recurrent-event) models.

:mod:`backend.recurrent` fits the models; this module answers "how many
failures, and how sure are we?" from a fit:

- **parameter uncertainty**: draws of a fit's parameters from its covariance
  (on the log scale for a positive parameter), so a range carries the fit's
  own uncertainty and not only the Poisson (or simulation) noise of the count;
- **unit differences**: in a fleet fitted with one minimal-repair model, each
  system's own failures against the model's expectation give it a rate factor
  (a gamma frailty, estimated from the spread between systems and shrunk
  towards 1 by how much evidence each system has), so a bad actor is forecast
  as one;
- **imperfect repair** forward: each system simulated from where its own
  history leaves it (SurPyval's ``forecast``), with the parameter
  uncertainty added by sigma points;
- the **Calculator**'s values with bounds (expected failures, failure rate,
  MTBF, for a covariate model at chosen covariate values) and the **overhaul
  interval**'s range.

Every interval follows :mod:`backend.levels`: 90% two-sided, and the MTBF's
one-sided 90% lower bound.
"""

from __future__ import annotations


import numpy as np

from backend import levels
from backend.warn_capture import ignore_warnings
from backend.fitting import FitError, _json_safe

DRAWS = 2000          # parameter draws for a minimal-repair range
RENEWAL_ITEMS = 1000  # simulated futures of each system, imperfect repair
SIGMA_ITEMS = 300     # ... at each sigma point (common random numbers)
SEED = 0

RANGE_NOTE = ("The range allows for chance and for the fit's own uncertainty (its parameters drawn from their "
              "estimated spread).")


# ---- Model kinds ------------------------------------------------------------------

def _is_renewal(model) -> bool:
    return type(model).__name__ == "RenewalModel"


def _is_regression(model) -> bool:
    return getattr(model, "coeffs", None) is not None and hasattr(model, "feature_names")


def nhpp_id(model) -> str | None:
    """``crow_amsaa``, ``duane``, ``hpp`` or ``cox_lewis`` for a Poisson-
    process fit; None otherwise."""
    name = getattr(getattr(model, "dist", None), "name", None)
    return {"Crow-AMSAA": "crow_amsaa", "Duane": "duane", "Homogeneous Poisson Process": "hpp",
            "Cox-Lewis": "cox_lewis"}.get(name)


def _same_curve(model):
    """The model to draw parameters from: a Duane fit on SurPyval 0.26 is
    drawn as its Crow-AMSAA twin (the same curve, with the right covariance;
    backend.recurrent.duane_needs_twin)."""
    from backend.recurrent import crow_twin

    return crow_twin(model) or model


def _fitter(model_id: str):
    from backend.recurrent import MODELS

    return MODELS[model_id]["fitter"]


# ---- Parameter draws -----------------------------------------------------------------

def _rng(seed=SEED):
    return np.random.default_rng(seed)


def _log_scaled(model) -> np.ndarray:
    """Which parameters are drawn on the log scale: the positive ones, except
    a Cox-Lewis model's (an intercept and a slope, either sign)."""
    p = np.asarray(model.params, dtype=float)
    if nhpp_id(model) == "cox_lewis":
        return np.zeros(p.size, dtype=bool)
    return p > 0


def param_draws(model, draws: int = DRAWS, rng=None) -> np.ndarray | None:
    """``(draws, p)`` parameter vectors from the fit's covariance (normal on
    the log scale for a positive parameter); None when the fit has no
    covariance (built from parameters, restored without its data)."""
    from backend.recurrent import model_covariance

    cov = model_covariance(model)
    p = np.asarray(model.params, dtype=float)
    if cov is None or cov.shape != (p.size, p.size) or not np.all(np.isfinite(cov)):
        return None
    logs = _log_scaled(model)
    J = np.where(logs, 1.0 / np.where(logs, p, 1.0), 1.0)
    cov_t = cov * np.outer(J, J)
    centre = np.where(logs, np.log(np.where(logs, p, 1.0)), p)
    cov_t = (cov_t + cov_t.T) / 2.0
    try:
        z = (rng or _rng()).multivariate_normal(centre, cov_t, size=draws, check_valid="raise", method="eigh")
    except (ValueError, np.linalg.LinAlgError):
        return None
    return np.where(logs, np.exp(z), z)


def _cif_draws(model_id: str, P: np.ndarray, t) -> np.ndarray:
    """``(draws, len(t))``: Λ(t) under each parameter draw of a Poisson-
    process model."""
    t = np.atleast_1d(np.asarray(t, dtype=float))
    fitter = _fitter(model_id)
    out = np.empty((P.shape[0], t.size))
    with np.errstate(all="ignore"):
        for d, row in enumerate(P):
            out[d] = np.asarray(fitter.from_params(list(row)).cif(t), dtype=float)
    return out


def _quantiles(values, axis=0):
    v = np.asarray(values, dtype=float)
    lo, hi = np.nanquantile(v, [levels.Q_LOW, levels.Q_HIGH], axis=axis)
    return lo, hi


# ---- Unit differences (minimal repair) -------------------------------------------------

def unit_effects(model) -> dict | None:
    """Each fitted system's rate factor against the fleet model, from its own
    failures ``n`` and the model's expectation ``E`` over its window.

    The systems' spread beyond Poisson chance gives a gamma frailty variance
    ``s2`` (moment estimate, 0 when the spread is no more than chance), and a
    system's factor is its posterior mean ``(1/s2 + n) / (1/s2 + E)``: its
    own ratio n/E, shrunk towards 1 the fewer failures it has. ``None``
    without per-system data. ``{"s2", "systems": {id: {failures, expected,
    factor, shape, rate}}}``."""
    if not nhpp_id(model):
        return None
    try:
        with ignore_warnings(), np.errstate(all="ignore"):
            res = np.asarray(model.residuals("martingale"), dtype=float)
        data = model.data
        ids = list(data.ids)
    except Exception:  # noqa: BLE001 - no data
        return None
    c = np.asarray(data.c)
    n_rows = np.asarray(data.n) if getattr(data, "n", None) is not None else np.ones(len(c))
    item = np.asarray(data.i)
    n = np.array([float(n_rows[(item == s) & (c == 0)].sum()) for s in ids])
    E = n - res
    if len(ids) < 2 or not np.all(np.isfinite(E)) or np.any(E <= 0):
        return None
    s2 = max(0.0, float((((n - E) ** 2).sum() - n.sum()) / (E ** 2).sum()))
    systems = {}
    for s, ni, ei in zip(ids, n, E):
        if s2 > 0:
            shape, rate = 1.0 / s2 + ni, 1.0 / s2 + ei
        else:
            shape = rate = None
        systems[str(s)] = {"failures": float(ni), "expected": float(ei),
                           "factor": float(shape / rate) if s2 > 0 else 1.0, "shape": shape, "rate": rate}
    return {"s2": s2, "systems": systems}


def _key(name) -> str:
    return str(name or "").strip().casefold()


def match_systems(names, effects: dict | None) -> list:
    """The fitted system each item name is (case and spaces ignored), or None."""
    if not effects:
        return [None] * len(names)
    by_key = {_key(s): s for s in effects["systems"]}
    return [by_key.get(_key(nm)) for nm in names]


# ---- Minimal-repair fleet forecast --------------------------------------------------

def nhpp_forecast(model, ages, rates, periods: int, names=None, draws: int = DRAWS, year_groups=None) -> dict:
    """Failures of repairable items over ``periods`` under a Poisson-process
    fit: each item at age ``a`` using ``r`` a period expects
    ``w·(Λ(a + k·r) − Λ(a))`` within ``k`` periods, ``w`` its rate factor
    (its own history when its name is a fitted system, else 1).

    The ranges are the 5th and 95th percentiles of the count simulated over
    the fit's parameter draws, each item's rate factor (a fitted system's
    posterior; for any other item, the fleet's spread between systems) and
    Poisson chance. Without a covariance (a model built from parameters) the
    range is Poisson, given the model."""
    from scipy.stats import poisson

    model = _same_curve(model)
    model_id = nhpp_id(model)
    ages = np.asarray(ages, dtype=float)
    rates = np.asarray(rates, dtype=float)
    k = ages.size
    names = list(names or [None] * k)
    steps = np.arange(0, periods + 1, dtype=float)
    grid = ages[:, None] + rates[:, None] * steps[None, :]          # (k, periods + 1)
    with np.errstate(all="ignore"):
        base = np.asarray(model.cif(grid.ravel()), dtype=float).reshape(grid.shape)
    base = np.nan_to_num(base - base[:, :1], nan=0.0, posinf=0.0)      # cumulative, from 0
    effects = unit_effects(model)
    yearly = None
    matched = match_systems(names, effects)
    factor = np.array([effects["systems"][m]["factor"] if m else 1.0 for m in matched])
    cum = base[:, 1:] * factor[:, None]
    per_period = np.diff(np.concatenate([np.zeros((k, 1)), cum], axis=1), axis=1).sum(axis=0)
    expected = float(cum[:, -1].sum())

    P = param_draws(model, draws) if model_id else None
    rng = _rng(SEED + 1)
    if P is not None and k:
        s2 = effects["s2"] if effects else 0.0
        shape = np.array([effects["systems"][m]["shape"] if (m and s2 > 0) else (1.0 / s2 if s2 > 0 else np.nan)
                          for m in matched])
        rate_g = np.array([effects["systems"][m]["rate"] if (m and s2 > 0) else (1.0 / s2 if s2 > 0 else np.nan)
                           for m in matched])
        flat = grid.ravel()
        counts = np.empty((P.shape[0], periods))
        for d, row in enumerate(P):
            with np.errstate(all="ignore"):
                lam = np.asarray(_fitter(model_id).from_params(list(row)).cif(flat), dtype=float).reshape(grid.shape)
            inc = np.nan_to_num(np.diff(lam, axis=1), nan=0.0, posinf=0.0)
            w = rng.gamma(shape, 1.0 / rate_g) if s2 > 0 else np.ones(k)
            counts[d] = rng.poisson(np.maximum((inc * w[:, None]).sum(axis=0), 0.0))
        totals = np.cumsum(counts, axis=1)
        lo, hi = _quantiles(totals[:, -1])
        p_lo, p_hi = _quantiles(counts)
        method = "simulated"
        if year_groups is not None:
            yearly = [[float(v) for v in _quantiles(counts[:, g].sum(axis=1))] for g in year_groups]
    else:
        lo, hi = (poisson.ppf(q, max(expected, 1e-300)) if expected > 0 else 0.0 for q in (levels.Q_LOW, levels.Q_HIGH))
        ends = [np.where(per_period > 0, poisson.ppf(q, np.maximum(per_period, 1e-300)), 0.0)
                for q in (levels.Q_LOW, levels.Q_HIGH)]
        p_lo, p_hi = ends
        method = "poisson"
        if year_groups is not None:
            yearly = [[float(poisson.ppf(q, mu)) if mu > 0 else 0.0 for q in (levels.Q_LOW, levels.Q_HIGH)]
                      for mu in (float(per_period[g].sum()) for g in year_groups)]

    per_item = []
    for i in range(k):
        mu = float(cum[i, -1])
        row = {"expected": mu, "prob_any": float(-np.expm1(-mu)), "rate_factor": float(factor[i])}
        if matched[i]:
            sysd = effects["systems"][matched[i]]
            row["history"] = {"system": matched[i], "failures": sysd["failures"], "expected": sysd["expected"]}
        per_item.append(row)
    n_matched = sum(1 for m in matched if m)
    return {
        "expected": expected,
        "interval": [float(lo), float(hi)],
        "per_period": [float(v) for v in per_period],
        "per_period_interval": [[float(a), float(b)] for a, b in zip(np.atleast_1d(p_lo), np.atleast_1d(p_hi))],
        "per_item": per_item,
        "interval_method": method,
        "units": _units_note(effects, n_matched, k, method),
        "yearly_interval": yearly,
    }


def _units_note(effects, n_matched: int, k: int, method: str) -> dict:
    """What the forecast assumed about differences between items, in words."""
    s2 = effects["s2"] if effects else None
    if effects is None:
        text = "Every item gets the model's fleet rate: the model has no per-system history to tell items apart."
    elif s2 == 0:
        text = ("The model's systems fail at about the rate it expects, each within chance, so every item gets "
                "the fleet rate.")
    elif n_matched:
        text = (f"{n_matched} of {k} item{'s' if k != 1 else ''} named as a system in the model's data "
                f"{'get' if n_matched != 1 else 'gets'} a rate from {'their' if n_matched != 1 else 'its'} own "
                "history (shrunk towards the fleet rate the fewer failures there are); any other item gets the "
                "fleet rate, and its range allows for the spread between systems.")
    else:
        text = ("No item is named as a system in the model's data, so each gets the fleet rate; the range allows "
                "for the spread between systems. Name items as the model's systems to use their own history.")
    out = {"spread": s2, "matched": n_matched, "text": text}
    if method == "poisson":
        out["text"] += " The range is chance only: this model has no fit uncertainty to add (built from parameters)."
    else:
        out["text"] += " " + RANGE_NOTE
    return out


# ---- Imperfect repair forward --------------------------------------------------------

_RESTORATION_LIMITS = {"GeneralizedRenewal": (0.0, None), "ARA": (0.0, 1.0), "ARI": (0.0, 1.0),
                       "GeneralizedOneRenewal": (-0.99, None)}


def _renewal_clone(model, params):
    """The renewal model with other parameters (restoration first), its data
    kept so each system's history still sets its state."""
    d = model.to_dict()
    lo, hi = _RESTORATION_LIMITS.get(d.get("family"), (None, None))
    q = float(params[0])
    q = max(q, lo) if lo is not None else q
    q = min(q, hi) if hi is not None else q
    clone = type(model).from_dict({**d, "restoration": q, "params": [float(v) for v in params[1:]]})
    try:
        clone.data = model.data
    except Exception:  # noqa: BLE001 - from new only
        pass
    return clone


def _sigma_points(model):
    """Unscented sigma points of a renewal fit's parameters (log scale for
    the positive lifetime parameters; a restoration parameter on its edge,
    with no variance, held): ``[(params), ...]`` pairs, or [] without a
    covariance."""
    from backend.recurrent import model_covariance

    cov = model_covariance(model)
    p = np.asarray(model.params, dtype=float)
    if cov is None or cov.shape != (p.size, p.size):
        return []
    free = np.flatnonzero(np.isfinite(np.diag(cov)) & (np.diag(cov) > 0))
    if not free.size:
        return []
    sub = cov[np.ix_(free, free)]
    if not np.all(np.isfinite(sub)):
        return []
    logs = np.array([j > 0 and p[j] > 0 for j in free])  # the restoration parameter leads, natural scale
    J = np.where(logs, 1.0 / np.where(logs, p[free], 1.0), 1.0)
    sub = sub * np.outer(J, J)
    try:
        vals, vecs = np.linalg.eigh((sub + sub.T) / 2.0)
    except np.linalg.LinAlgError:
        return []
    root = vecs * np.sqrt(np.clip(vals, 0.0, None))
    n = free.size
    out = []
    for j in range(n):
        pair = []
        for sign in (1.0, -1.0):
            step = sign * np.sqrt(n) * root[:, j]
            q = p.copy()
            q[free] = np.where(logs, p[free] * np.exp(step), p[free] + step)
            pair.append(q)
        out.append(tuple(pair))
    return out


def _nb_quantiles(mean, var):
    """5th and 95th percentiles of a count with this mean and variance: a
    negative binomial when over-dispersed, else Poisson."""
    from scipy.stats import nbinom, poisson

    mean = np.atleast_1d(np.asarray(mean, dtype=float))
    var = np.atleast_1d(np.asarray(var, dtype=float))
    lo, hi = np.zeros_like(mean), np.zeros_like(mean)
    for j, (m, v) in enumerate(zip(mean, var)):
        if not (m > 0):
            continue
        if v > m * (1 + 1e-9):
            r = m * m / (v - m)
            pr = r / (r + m)
            lo[j], hi[j] = nbinom.ppf(levels.Q_LOW, r, pr), nbinom.ppf(levels.Q_HIGH, r, pr)
        else:
            lo[j], hi[j] = poisson.ppf(levels.Q_LOW, m), poisson.ppf(levels.Q_HIGH, m)
    return lo, hi


def _renewal_means(model, horizons, rows, ages, items: int, seed) -> tuple[np.ndarray, np.ndarray, float]:
    """``(per_unit, total_var)``: each chosen unit's expected cumulative
    failures at each horizon (fitted systems by their ``rows`` in the data,
    the others new at ``ages`` with no failure yet), and the simulated
    variance of their total at the last horizon."""
    import surpyval

    k = len(rows) + len(ages)
    out = np.zeros((k, horizons.size))
    var = 0.0
    with ignore_warnings(), np.errstate(all="ignore"):
        if rows:
            fc = surpyval.forecast(model, horizon=horizons, items=items, random_state=seed,
                                   alpha_ci=1 - levels.LEVEL)
            per = np.asarray(fc.per_unit, dtype=float).reshape(-1, horizons.size)
            chosen = per[rows]
            out[: len(rows)] = chosen
            whole = float(per[:, -1].sum())
            var += float(fc.variance[-1]) * (float(chosen[:, -1].sum()) / whole if whole > 0 else 1.0)
        if ages:
            fc = surpyval.forecast(model, age=np.asarray(ages, dtype=float), horizon=horizons, items=items,
                                   random_state=seed, alpha_ci=1 - levels.LEVEL)
            out[len(rows):] = np.asarray(fc.per_unit, dtype=float).reshape(-1, horizons.size)
            var += float(fc.variance[-1])
    return out, var


def renewal_forecast(model, ages, rates, periods: int, names=None, year_groups=None) -> dict:
    """Failures of repairable items over ``periods`` under an imperfect-
    repair fit, by simulation. An item named as a system in the model's data
    starts from where that system's history leaves it (its age at the end of
    its record, its failures and repairs); any other item is taken as having
    run its age since new with no failure yet. The range adds the fit's
    uncertainty (sigma points over its parameters, common random numbers) to
    the simulated spread, as a negative binomial with that mean and
    variance."""
    ages = np.asarray(ages, dtype=float)
    rates = np.asarray(rates, dtype=float)
    k = ages.size
    names = list(names or [None] * k)
    try:
        ids = [str(s) for s in model.data.ids]
    except Exception:  # noqa: BLE001 - no data: every item from new
        ids = []
    by_key = {_key(s): j for j, s in enumerate(ids)}
    match = [by_key.get(_key(nm)) for nm in names]
    steps = np.arange(1, periods + 1, dtype=float)
    cum = np.zeros((k, periods))
    total_var = 0.0
    points = _sigma_points(model)
    sigma_totals = []  # [(plus, minus)] of (periods,) totals
    for rate in np.unique(rates[rates > 0]):
        idx = np.flatnonzero(rates == rate)
        fitted = [i for i in idx if match[i] is not None]
        fresh = [i for i in idx if match[i] is None]
        order = fitted + fresh
        horizons = rate * steps
        means, var = _renewal_means(model, horizons, [match[i] for i in fitted], [ages[i] for i in fresh],
                                    RENEWAL_ITEMS, SEED)
        cum[order] = means
        total_var += var
        for j, (plus, minus) in enumerate(points):
            pair = []
            for params in (plus, minus):
                try:
                    clone = _renewal_clone(model, params)
                    m, _ = _renewal_means(clone, horizons, [match[i] for i in fitted], [ages[i] for i in fresh],
                                          SIGMA_ITEMS, SEED)
                    pair.append(m.sum(axis=0))
                except Exception:  # noqa: BLE001 - a sigma point the model refuses: drop it
                    pair = None
                    break
            if pair is None:
                continue
            if len(sigma_totals) <= j:
                sigma_totals.append([np.zeros(periods), np.zeros(periods)])
            sigma_totals[j][0] += pair[0]
            sigma_totals[j][1] += pair[1]
    totals = cum.sum(axis=0)
    per_period = np.diff(np.concatenate([[0.0], totals]))
    n = len(sigma_totals)
    if n:
        centre = np.mean([t for pair in sigma_totals for t in pair], axis=0)
        param_var = np.sum([(pair[0] - centre) ** 2 + (pair[1] - centre) ** 2 for pair in sigma_totals], axis=0) / (2 * n)
    else:
        param_var = np.zeros(periods)
    sim_disp = total_var / totals[-1] if totals[-1] > 0 else 1.0
    lo, hi = _nb_quantiles(totals[-1], totals[-1] * sim_disp + param_var[-1])
    period_param = np.diff(np.concatenate([[0.0], np.sqrt(param_var)])) ** 2
    p_lo, p_hi = _nb_quantiles(per_period, per_period * sim_disp + period_param)
    yearly = None
    if year_groups is not None:
        # Each year as the periods are read: its mean, the simulation's spread
        # and the fit's, from the cumulative spread at the year's two ends.
        sd = np.sqrt(param_var)
        means = np.array([float(per_period[g].sum()) for g in year_groups])
        fit_var = np.array([(sd[g[-1]] - (sd[g[0] - 1] if g[0] > 0 else 0.0)) ** 2 for g in year_groups])
        y_lo, y_hi = _nb_quantiles(means, means * sim_disp + fit_var)
        yearly = [[float(a), float(b)] for a, b in zip(np.atleast_1d(y_lo), np.atleast_1d(y_hi))]
    per_item = []
    for i in range(k):
        mu = float(cum[i, -1])
        row = {"expected": mu, "prob_any": float(-np.expm1(-mu))}
        if match[i] is not None:
            row["history"] = {"system": ids[match[i]]}
        else:
            row["from_new"] = True
        per_item.append(row)
    n_matched = sum(1 for m in match if m is not None)
    text = (f"Imperfect repair, simulated: {n_matched} of {k} item{'s' if k != 1 else ''} named as a system in the "
            "model's data start from where that system's own history leaves it (its age at the end of its record). "
            if n_matched else "Imperfect repair, simulated. ")
    if n_matched < k:
        text += ("Items not in the model's data are taken as having run their age since new with no failure yet: "
                 "name items as the model's systems to start them from their own history. ")
    text += RANGE_NOTE if n else "The range is the simulated spread only: this model has no fit uncertainty to add."
    return {
        "expected": float(totals[-1]),
        "interval": [float(lo[0]), float(hi[0])],
        "per_period": [float(v) for v in per_period],
        "per_period_interval": [[float(a), float(b)] for a, b in zip(p_lo, p_hi)],
        "per_item": per_item,
        "interval_method": "simulated",
        "units": {"matched": n_matched, "spread": None, "text": text},
        "yearly_interval": yearly,
    }


# ---- The Calculator -------------------------------------------------------------------

def _profile_vector(model, results: dict, profile: dict | None) -> tuple[np.ndarray, str]:
    """The covariate row for a covariate model: each category's level (its
    indicator columns) and each number, the rest at the fleet's average.
    ``(z, label)``."""
    names = list(model.feature_names or [])
    avg = dict((results or {}).get("average_profile") or {})
    z = np.array([float(avg.get(nm, 0.0)) for nm in names])
    labels = []
    for meta in (results or {}).get("covariates") or []:
        col = meta.get("column")
        if col not in (profile or {}):
            continue
        value = profile[col]
        if meta.get("kind") == "category":
            level = str(value)
            if level not in [str(v) for v in meta.get("levels") or []]:
                raise FitError(f"“{level}” isn't a level of {col}: choose one of "
                               f"{', '.join(str(v) for v in meta.get('levels') or [])}.")
            for j, nm in enumerate(names):
                if nm.startswith(col + ": "):
                    z[j] = 1.0 if nm == f"{col}: {level}" else 0.0
            labels.append(f"{col} {level}")
        else:
            try:
                v = float(value)
            except (TypeError, ValueError):
                raise FitError(f"{col} must be a number.")
            if col in names:
                z[names.index(col)] = v
            labels.append(f"{col} {v:g}")
    return z, ", ".join(labels)


def _first(v):
    a = np.asarray(v, dtype=float).ravel()
    return float(a[0]) if a.size and np.isfinite(a[0]) else None


def _pair(v):
    a = np.asarray(v, dtype=float).ravel()
    return [float(min(a[0], a[1])), float(max(a[0], a[1]))] if a.size >= 2 and np.all(np.isfinite(a[:2])) else None


def calculate(model, results: dict, t: float, start: float | None = None, profile: dict | None = None) -> dict:
    """The Calculator's values at ``t`` with their bounds: expected failures
    per system from new N(t), the failure rate and the MTBF (its 90% range
    and one-sided 90% lower bound), and over ``[start, t]`` the expected
    failures per system. A covariate model is evaluated at ``profile``
    (``{column: level or number}``, the rest at the fleet's average); an
    imperfect-repair model by simulation from new."""
    try:
        t = float(t)
    except (TypeError, ValueError):
        raise FitError("t must be a number.")
    if not np.isfinite(t) or t <= 0:
        raise FitError("t must be a positive time.")
    if start is not None:
        start = float(start)
        if not np.isfinite(start) or start < 0 or start >= t:
            raise FitError("The window's start must be at least 0 and before t.")
    alpha = 1 - levels.LEVEL
    out: dict = {"t": t, "start": start, "level": levels.LEVEL}
    if _is_renewal(model):
        return _json_safe({**out, **_renewal_calc(model, t, start)})

    if _is_regression(model):
        z, label = _profile_vector(model, results, profile)
        Z = z[None, :]
        out["profile"] = label or "the fleet's average covariates"
        tt = np.array([t])
        with ignore_warnings(), np.errstate(all="ignore"):
            n_t = _first(model.cif(tt, Z))
            rocof = _first(model.iif(tt, Z))
            try:
                n_ci = _pair(model.cif_cb(tt, Z, alpha_ci=alpha))
                r_ci = _pair(model.iif_cb(tt, Z, alpha_ci=alpha))
                r_up = _first(model.iif_cb(tt, Z, alpha_ci=alpha, bound="upper"))
            except Exception:  # noqa: BLE001 - no likelihood
                n_ci = r_ci = r_up = None
            n_s = _first(model.cif(np.array([start]), Z)) if start is not None else None
        out.update(_rates(n_t, n_ci, rocof, r_ci, r_up))
        if start is not None and n_t is not None and n_s is not None:
            out["window"] = {"expected": n_t - n_s, "ci": None,
                             "note": "No range on a window for a covariate model yet."}
        out["bounds_note"] = "Wald (delta method), at these covariate values."
        return _json_safe(out)

    model = src = _same_curve(model)  # SurPyval 0.26's Duane bounds (backend.recurrent.duane_needs_twin)
    model_id = nhpp_id(model)
    if model_id is None:
        raise FitError("This model can't be evaluated here.")
    tt = np.array([t])
    with ignore_warnings(), np.errstate(all="ignore"):
        n_t = _first(model.cif(tt))
        rocof = _first(model.iif(tt))
        try:
            n_ci = _pair(src.cif_cb(tt, alpha_ci=alpha))
            r_ci = _pair(src.iif_cb(tt, alpha_ci=alpha))
            r_up = _first(src.iif_cb(tt, alpha_ci=alpha, bound="upper"))
        except Exception:  # noqa: BLE001 - built from parameters: no likelihood
            n_ci = r_ci = r_up = None
    out.update(_rates(n_t, n_ci, rocof, r_ci, r_up))
    if n_ci is None:
        out["bounds_note"] = "No bounds: this model was built from parameters, not fitted, so it has no uncertainty."
    else:
        out["bounds_note"] = "Wald (delta method) from the fit."
    if start is not None:
        with np.errstate(all="ignore"):
            n_s = _first(model.cif(np.array([start])))
        win = {"expected": (n_t - n_s) if n_t is not None and n_s is not None else None, "ci": None}
        P = param_draws(model)
        if P is not None:
            lam = _cif_draws(model_id, P, [start, t])
            lo, hi = _quantiles(lam[:, 1] - lam[:, 0])
            win["ci"] = [float(lo), float(hi)]
        out["window"] = win
    return _json_safe(out)


def _rates(n_t, n_ci, rocof, r_ci, r_up) -> dict:
    mtbf = 1.0 / rocof if rocof and rocof > 0 else None
    mtbf_ci = [1.0 / r_ci[1], 1.0 / r_ci[0]] if r_ci and r_ci[0] > 0 else None
    mtbf_lower = 1.0 / r_up if r_up and r_up > 0 else None
    return {"expected": {"value": n_t, "ci": n_ci},
            "rocof": {"value": rocof, "ci": r_ci},
            "mtbf": {"value": mtbf, "ci": mtbf_ci, "lower": mtbf_lower}}


def _renewal_calc(model, t: float, start: float | None) -> dict:
    """N(t) from new for an imperfect-repair model, simulated (fixed seed),
    beyond the data too, with the fit's uncertainty by sigma points."""
    grid = np.array([v for v in (start, t) if v is not None], dtype=float)

    def mcf(m, items):
        with ignore_warnings(), np.errstate(all="ignore"):
            return np.asarray(m.mcf(grid, items=items, random_state=SEED), dtype=float).ravel()

    base = mcf(model, 4000)
    spread = []
    for plus, minus in _sigma_points(model):
        try:
            spread.append((mcf(_renewal_clone(model, plus), 1000), mcf(_renewal_clone(model, minus), 1000)))
        except Exception:  # noqa: BLE001
            continue
    ci = win_ci = None
    if spread:
        n = len(spread)
        centre = np.mean([v for pair in spread for v in pair], axis=0)
        var = np.sum([(a - centre) ** 2 + (b - centre) ** 2 for a, b in spread], axis=0) / (2 * n)
        sd = np.sqrt(var)
        ci = [max(0.0, float(base[-1] - levels.Z * sd[-1])), float(base[-1] + levels.Z * sd[-1])]
        if start is not None:
            d = np.array([b[1] - b[0] for pair in spread for b in pair])
            dc = d.mean()
            sdw = float(np.sqrt(np.sum((d - dc) ** 2) / (2 * n)))
            w = float(base[1] - base[0])
            win_ci = [max(0.0, w - levels.Z * sdw), w + levels.Z * sdw]
    out = {"expected": {"value": float(base[-1]), "ci": ci},
           "rocof": {"value": None, "ci": None}, "mtbf": {"value": None, "ci": None, "lower": None},
           "rate_reason": ("An imperfect-repair model's failure rate depends on each system's own repairs: see "
                           "Plan ahead › Next failure for each system's, or From now on for the fleet."),
           "simulated": True,
           "bounds_note": ("Simulated from new (each repair as the model estimates), with the fit's uncertainty "
                           "added by sigma points." if spread else "Simulated from new; this fit has no "
                           "uncertainty to add.")}
    if start is not None:
        out["window"] = {"expected": float(base[1] - base[0]), "ci": win_ci}
    return out


def from_now(model, horizon: float) -> dict:
    """The fleet's failures over the next ``horizon`` from where each fitted
    system is now (the end of its record), with each system's share: the
    model's own systems run through the forecast."""
    try:
        h = float(horizon)
    except (TypeError, ValueError):
        raise FitError("The horizon must be a number.")
    if not np.isfinite(h) or h <= 0:
        raise FitError("The horizon must be a positive time ahead.")
    if _is_regression(model):
        raise FitError("From now on isn't available for a covariate model yet.")
    try:
        ids = [str(s) for s in model.data.ids]
        x, item = np.asarray(model.data.x, dtype=float), np.asarray(model.data.i)
    except Exception:  # noqa: BLE001
        raise FitError("This model has no event data to start from (built from parameters).")
    ends = np.array([float(x[item == s].max()) for s in model.data.ids])
    rates = np.ones(len(ids))
    fc = (renewal_forecast if _is_renewal(model) else nhpp_forecast)(model, ends, rates * h, 1, names=ids)
    systems = [{"system": s, "age": float(a), "expected": r["expected"], **({"rate_factor": r["rate_factor"]}
               if "rate_factor" in r else {})} for s, a, r in zip(ids, ends, fc["per_item"])]
    systems.sort(key=lambda r: -r["expected"])
    return _json_safe({"horizon": h, "expected": fc["expected"], "interval": fc["interval"], "level": levels.LEVEL,
                       "systems": systems[:50], "n_systems": len(ids), "note": fc["units"]["text"]})


# ---- Overhaul interval range ---------------------------------------------------------------

def overhaul_range(model, cost_repair: float, cost_overhaul: float) -> dict:
    """The optimal overhaul interval's 90% range: the optimum of each of the
    fit's parameter draws (``Cr·(T·λ(T) − Λ(T)) = Co`` at T*). A draw whose
    rate doesn't rise has no finite optimum; when more than 5% of draws are
    like that the range has no upper end, and it says so."""
    from scipy.optimize import brentq

    model = _same_curve(model)
    model_id = nhpp_id(model)
    if model_id in (None, "hpp"):
        return {"ci": None, "reason": "No range: this model's rate doesn't rise, so there's no optimum to bound."}
    P = param_draws(model)
    if P is None:
        return {"ci": None, "reason": "No range: this model was built from parameters, so it has no fit "
                                      "uncertainty."}
    ratio = float(cost_overhaul) / float(cost_repair)
    stars = np.full(P.shape[0], np.inf)
    for d, row in enumerate(P):
        if model_id in ("crow_amsaa", "duane"):
            if model_id == "crow_amsaa":
                scale, beta = row
            else:
                beta, b = row
                scale = b ** (-1.0 / beta) if b > 0 and beta > 0 else np.nan
            if beta > 1.0 and np.isfinite(scale):
                stars[d] = scale * (ratio / (beta - 1.0)) ** (1.0 / beta)
        else:  # Cox-Lewis: λ = exp(a + b t)
            a, b = row
            if b <= 0:
                continue

            def g(T, a=a, b=b):
                lam = np.exp(a + b * T)
                return T * lam - (lam - np.exp(a)) / b - ratio

            hi = 1.0 / b
            try:
                while g(hi) < 0 and hi < 1e12:
                    hi *= 2.0
                stars[d] = brentq(g, 1e-12, hi) if g(hi) >= 0 else np.inf
            except (ValueError, OverflowError):
                continue
    lo, hi = np.quantile(stars, [levels.Q_LOW, levels.Q_HIGH])
    infinite = float(np.mean(~np.isfinite(stars)))
    return _json_safe({"ci": [float(lo), float(hi) if np.isfinite(hi) else None], "level": levels.LEVEL,
                       "no_optimum_share": infinite,
                       "reason": (f"In {infinite:.0%} of the fit's plausible versions the failure rate doesn't rise "
                                  "enough for an overhaul to pay, so the range has no upper end."
                                  if not np.isfinite(hi) else None)})
