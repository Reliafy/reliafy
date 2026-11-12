"""A Bayesian update of a baseline life model with a few failures (Derryn, 9 Nov 2026:
"select a baseline something and fit with one or two failures").

In plain words: with plenty of failures a position's history says what its life
distribution is, so fit it. With one or two failures it says little on its own, but
there is usually a credible baseline: the position class's model, the vendor's numbers,
a sample or handbook model, or a belief such as "the B10 is about 5,000 hours". The
update starts from the baseline (the *prior*), weighs it by how much the user trusts it,
and lets the position's own failures and suspensions move it (the *posterior*). With no
history the baseline stands as given; with a lot the data win.

The arithmetic is SurPyval's (0.26, ``surpyval.bayes``): ``Dist.fit_bayes(x, c,
priors=...)`` on the same data a fit takes, exact on a grid, the same answer on every
machine. The baseline becomes a prior with SurPyval's helpers:

* a saved model fitted to data: ``prior.from_model(fit, weight=...)`` (its estimates and
  how sure they were; ``weight`` the trust: 1.0, 0.5 or 0.2);
* numbers only (typed, a handbook, a model saved from parameters):
  ``prior.from_params(dist, params, within=...)`` (each within 10%, 30% or 60%);
* a belief about a B-life: ``prior.on_quantities(Weibull, B10=around(...), beta=between(...))``.

The results are credible intervals, never confidence bounds: the parameters' are 90%
two-sided; the B10 and mean life carry a 90% one-sided lower bound ("we're 90% sure the
B10 is at least ..."), as every life bound in the app does. A saved update keeps its recipe (the data and the prior) and is
rebuilt by refitting (``rebuild``), about a third of a second, rather than storing the
posterior grid (megabytes).
"""

from __future__ import annotations

import io
import math
from typing import Any

import numpy as np
import pandas as pd
import surpyval as sp

METHOD = "bayesian_update"
LEVEL = 0.90  # the credible level shown everywhere (alpha 0.10)
ALPHA = 1 - LEVEL
GRID = 120  # points on the plotted curves

#: How much to trust the baseline, in words, and the prior width each means.
TRUST = {
    "close": {"label": "Trust it closely", "within": 0.10, "weight": 1.0,
              "words": "each number within about 10% (a fitted baseline counts as all its evidence)"},
    "guide": {"label": "Use it as a guide", "within": 0.30, "weight": 0.5,
              "words": "each number within about 30% (a fitted baseline counts as half its evidence)"},
    "start": {"label": "Only a starting point", "within": 0.60, "weight": 0.2,
              "words": "each number within about 60% (a fitted baseline counts as a fifth of its evidence)"},
}
DISTS = {"weibull": sp.Weibull, "exponential": sp.Exponential, "lognormal": sp.LogNormal}
DIST_IDS = {d.name: k for k, d in DISTS.items()}
LABELS = {"weibull": "Weibull", "exponential": "Exponential", "lognormal": "Lognormal"}
WORDS = {"alpha": "characteristic life", "beta": "shape", "failure_rate": "failure rate", "mu": "log-scale (mu)",
         "sigma": "spread (sigma)"}


class BayesError(ValueError):
    """A request the update can't do, said in words."""


def _f(v) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def num(v) -> str:
    """A number for a sentence: 3–4 significant figures, thousands separated."""
    x = _f(v)
    if x is None:
        return "—"
    if x != 0 and (abs(x) < 0.001 or abs(x) >= 1e9):
        return f"{x:.3g}"
    sig = 4 if abs(x) >= 1000 else 3
    r = float(f"{x:.{sig}g}")
    return f"{r:,.0f}" if r == int(r) and abs(r) >= 1 else f"{r:,}"


# ---- the baseline -----------------------------------------------------------------------

def _unit_word(unit) -> str:
    return str(unit or "").strip().lower()


def baseline_from(db, owners, hidden, spec: dict) -> dict:
    """The baseline as {source, name, distribution, params {name: value}, unit, model_id?,
    live?, recipe?, belief?}. ``spec``: {model_id} (a saved non-repairable model the reader can
    open, or an earlier update, whose prior and data it carries on), {distribution, params,
    unit, name?} (typed), or {b10: {value, low, high}, shape: {low, high}, unit} (a belief)."""
    from backend import fitting
    from backend.services import models as models_service

    spec = dict(spec or {})
    if spec.get("model_id"):
        doc = models_service.get_model(db, str(spec["model_id"]), owners)
        if doc is None or doc.id in (hidden or ()):
            raise BayesError("The baseline model wasn't found.")
        r = doc.results or {}
        if (doc.spec or {}).get("method") == METHOD:
            recipe = (doc.spec or {}).get("bayes") or {}
            return {"source": "update", "name": (r.get("bayes") or {}).get("baseline", {}).get("name") or doc.name,
                    "distribution": (doc.spec or {}).get("distribution_id"), "unit": r.get("unit") or "",
                    "params": {p["name"]: p["value"] for p in r.get("params") or []}, "model_id": doc.id,
                    "recipe": recipe, "model_name": doc.name}
        dist = r.get("distribution_id") or doc.distribution_id
        if doc.kind != "distribution" or dist not in DISTS:
            raise BayesError(f"“{doc.name}” is a {LABELS.get(dist, r.get('distribution') or doc.kind)} model: the "
                             "update takes a Weibull, exponential or lognormal baseline.")
        live = None
        if doc.dataset_id:
            try:
                live = fitting._MODEL_STORE[models_service._live_cache_id(db, doc.id, owners)]["model"]
            except Exception:  # noqa: BLE001 - without its fit the baseline is its numbers
                live = None
        return {"source": "model", "name": doc.name, "distribution": dist, "unit": r.get("unit") or "",
                "params": {p["name"]: float(p["value"]) for p in r.get("params") or []}, "model_id": doc.id,
                "live": live}
    if spec.get("b10"):
        b, s = spec.get("b10") or {}, spec.get("shape") or {}
        v, lo, hi = _f(b.get("value")), _f(b.get("low")), _f(b.get("high"))
        slo, shi = _f(s.get("low")) or 1.2, _f(s.get("high")) or 4.0
        if not (v and lo and hi and 0 < lo < v < hi):
            raise BayesError("Say the B10 as about a value, between a lower and a higher one (low < value < high).")
        if not 0 < slo < shi:
            raise BayesError("The shape's range must be low < high, both above 0.")
        return {"source": "belief", "name": f"a B10 of about {num(v)} {_unit_word(spec.get('unit'))}".strip(),
                "distribution": "weibull", "unit": spec.get("unit") or "", "params": {},
                "belief": {"b10": [v, lo, hi], "shape": [slo, shi]}}
    dist = str(spec.get("distribution") or "").lower()
    if dist not in DISTS:
        raise BayesError("Give the baseline as model_id, as distribution (weibull, exponential, lognormal) and "
                         "params, or as a B10 belief.")
    raw = spec.get("params") or {}
    given = {str(p.get("name")): _f(p.get("value")) for p in raw} if isinstance(raw, list) else \
        {str(k): _f(v) for k, v in raw.items()}
    names = list(DISTS[dist].parameter_names)
    if any(given.get(n) is None for n in names):
        raise BayesError(f"A {LABELS[dist]} baseline takes {', '.join(names)}.")
    return {"source": "params", "name": spec.get("name") or f"{LABELS[dist]} ({', '.join(f'{n} {num(given[n])}' for n in names)})",
            "distribution": dist, "unit": spec.get("unit") or "", "params": {n: given[n] for n in names}}


def priors_for(base: dict, trust: str):
    """The prior from the baseline and the trust (TRUST)."""
    if trust not in TRUST:
        raise BayesError(f"How much to trust it is one of {', '.join(TRUST)}.")
    t = TRUST[trust]
    dist = DISTS[base["distribution"]]
    if base["source"] == "belief":
        v, lo, hi = base["belief"]["b10"]
        slo, shi = base["belief"]["shape"]
        return sp.prior.on_quantities(sp.Weibull, B10=sp.prior.around(v, between=(lo, hi)),
                                      beta=sp.prior.between(slo, shi))
    if base.get("live") is not None:
        try:
            return sp.prior.from_model(base["live"], weight=t["weight"])
        except Exception:  # noqa: BLE001 - a fit without a usable covariance: its numbers
            pass
    return sp.prior.from_params(dist, [base["params"][n] for n in dist.parameter_names], within=t["within"])


def prior_table(dist_id: str, priors) -> list[dict]:
    """What the prior says before any data: each parameter's, the B10's and the mean life's
    median and 90% range. A prior on quantities (a library record's mean life with the shape
    between two bounds; a B10 belief) is sampled: its quantities are independent beliefs, so
    drawing each and mapping them to the parameters is the prior exactly, where SurPyval's grid
    check can fail on the long tail the mean life implies. Everything else is SurPyval's prior
    check."""
    from surpyval.bayes.prior import OnQuantities

    if isinstance(priors, OnQuantities):
        table = _sampled_table(dist_id, priors)
    else:
        table = sp.prior.check(DISTS[dist_id], priors).table
    out = []
    for key in [*DISTS[dist_id].parameter_names, "B10", "mean"]:
        if key in table:
            med, lo, hi = table[key]
            out.append({"name": key, "label": WORDS.get(key, "B10 life" if key == "B10" else "mean life"),
                        "median": _f(med), "lower": _f(lo), "upper": _f(hi)})
    return out


PRIOR_DRAWS = 40_000  # samples of a prior on quantities (a few ms; the 5–95% to about 1%)


def _draw_quantities(dist_id: str, priors, n: int, rng) -> dict:
    """Each statement of an on_quantities prior drawn on its own scale: {("mean",): values,
    ("q", 0.1): values, ("param", "beta"): values}."""
    from surpyval.bayes.transforms import Transform

    dist = DISTS[dist_id]
    out = {}
    for _, spec, p in priors.statements:
        if spec[0] == "param":
            t = Transform.for_bounds(dist.bounds[list(dist.parameter_names).index(spec[1])])
        elif spec[0] == "R":
            t = Transform("logit", 0.0, 1.0)
        else:
            t = Transform("log", 0.0, np.inf)
        out[tuple(spec)] = np.asarray(t.to_theta(p.draw_phi(n, t, rng)), dtype=float)
    return out


def _params_from_quantities(dist_id: str, drawn: dict) -> dict | None:
    """The parameters each draw implies, from the quantities stated (one shape or spread statement
    and one of the mean, a B-life or a reliability at a time), or None for a shape of statement
    not worked out here."""
    from scipy import special, stats

    params = {spec[1]: v for spec, v in drawn.items() if spec[0] == "param"}
    scale = {spec: v for spec, v in drawn.items() if spec[0] != "param"}
    if dist_id == "exponential":
        if "failure_rate" in params:
            return params
        if len(scale) != 1:
            return None
        (spec, v), = scale.items()
        if spec[0] == "mean":
            return {"failure_rate": 1 / v}
        if spec[0] == "q":
            return {"failure_rate": -np.log1p(-float(spec[1])) / v}
        if spec[0] == "R":
            return {"failure_rate": -np.log(v) / float(spec[1])}
        return None
    if len(scale) != 1 or len(params) != 1:
        return None
    (spec, v), = scale.items()
    if dist_id == "weibull" and "beta" in params:
        beta = params["beta"]
        if spec[0] == "mean":
            alpha = v / special.gamma(1 + 1 / beta)
        elif spec[0] == "q":
            alpha = v / (-np.log1p(-float(spec[1]))) ** (1 / beta)
        elif spec[0] == "R":
            alpha = float(spec[1]) / (-np.log(v)) ** (1 / beta)
        else:
            return None
        return {"alpha": alpha, "beta": beta}
    if dist_id == "lognormal" and "sigma" in params:
        sigma = params["sigma"]
        if spec[0] == "mean":
            mu = np.log(v) - sigma ** 2 / 2
        elif spec[0] == "q":
            mu = np.log(v) - sigma * stats.norm.ppf(float(spec[1]))
        elif spec[0] == "R":
            mu = np.log(float(spec[1])) - sigma * stats.norm.ppf(1 - v)
        else:
            return None
        return {"mu": mu, "sigma": sigma}
    return None


def _quantities_of(dist_id: str, params: dict) -> dict:
    """The B10 and the mean life of each parameter draw."""
    from scipy import special, stats

    if dist_id == "weibull":
        a, b = params["alpha"], params["beta"]
        return {"B10": a * (-np.log(0.9)) ** (1 / b), "mean": a * special.gamma(1 + 1 / b)}
    if dist_id == "lognormal":
        mu, sg = params["mu"], params["sigma"]
        return {"B10": np.exp(mu + sg * stats.norm.ppf(0.1)), "mean": np.exp(mu + sg ** 2 / 2)}
    r = params["failure_rate"]
    return {"B10": -np.log(0.9) / r, "mean": 1 / r}


def _sampled_table(dist_id: str, priors, n: int = PRIOR_DRAWS, seed: int = 20261109) -> dict:
    """The prior check's table ({quantity: (median, lower, upper)}) from draws of a prior on
    quantities; empty for a shape of statement not worked out here."""
    rng = np.random.default_rng(seed)
    params = _params_from_quantities(dist_id, _draw_quantities(dist_id, priors, n, rng))
    if params is None:
        return {}
    values = {**params, **_quantities_of(dist_id, params)}
    table = {}
    for key, v in values.items():
        v = np.asarray(v, dtype=float)
        v = v[np.isfinite(v)]
        if len(v):
            med, lo, hi = np.quantile(v, [0.5, ALPHA / 2, 1 - ALPHA / 2])
            table[key] = (float(med), float(lo), float(hi))
    return table


# ---- the data ---------------------------------------------------------------------------

def time_factor(unit) -> float:
    """Days in one of the baseline's units ("hours" → 1/24); a BayesError for a unit of use."""
    from backend.services.rcm_intervals import DAYS_IN
    from backend.units import normalize_unit

    key = normalize_unit(unit) or "day"
    if key not in DAYS_IN:
        raise BayesError(f"The baseline is in {unit}, a unit of use: a position's history is in days in service. "
                         "Use a baseline in a unit of time (hours, days, years), or give the data yourself.")
    return DAYS_IN[key]


def position_rows(m, position_id: str, unit, exclude=()) -> list[dict]:
    """A position's history (a design position: its built units') as rows in the baseline's
    unit: one per item fitted there, failed (c 0), still running or removed (1), or failed
    between two ages (2: xl..xr). ``exclude``: fitment ids the user unticked (kept, marked)."""
    per = time_factor(unit)
    rows = m.design_rollup(position_id)["life_data"]["rows"] if m._design_root_of(position_id) \
        else m.life_data(position_id)
    skip = set(exclude or ())
    out = []
    for r in rows:
        row = {"fitment_id": r.get("fitment_id"), "item": r.get("item"), "from": r.get("from"), "to": r.get("to"),
               "status": r.get("status"), "failure_mode": r.get("failure_mode"), "c": r["c"],
               "x": r["x"] / per, "used": r.get("fitment_id") not in skip}
        if r["c"] == 2:
            row.update(xl=r["xl"] / per, xr=r["xr"] / per)
        if (row.get("xr") if r["c"] == 2 else row["x"]) <= 0:
            row["used"] = False
        out.append(row)
    return out


def arrays(rows: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    """SurPyval's data: x as [lower, upper] per row (equal for an exact age), c the flags."""
    used = [r for r in rows if r.get("used", True)]
    x = np.array([[r["xl"], r["xr"]] if r["c"] == 2 else [r["x"], r["x"]] for r in used], dtype=float).reshape(-1, 2)
    c = np.array([r["c"] for r in used], dtype=int)
    return x, c


def given_rows(x, c) -> list[dict]:
    """Rows from data given directly (x ages, c flags: 0 failed, 1 still running)."""
    xs = list(x or [])
    cs = list(c or [0] * len(xs))
    if len(xs) != len(cs):
        raise BayesError("x and c must be the same length.")
    rows = []
    for xi, ci in zip(xs, cs):
        if int(ci) not in (0, 1):
            raise BayesError("c is 0 (failed) or 1 (still running) for each age.")
        if _f(xi) is None or float(xi) <= 0:
            raise BayesError("Each age must be a number above 0.")
        rows.append({"x": float(xi), "c": int(ci), "used": True})
    return rows


# ---- the update -------------------------------------------------------------------------

def _fit(dist_id: str, x, c, priors, unit):
    model = DISTS[dist_id].fit_bayes(x, c, priors=priors, unit=unit or None)
    ex = getattr(getattr(model, "posterior", None), "exact", None) or {}
    return _StableLomax(model, ex) if ex.get("family") == "gamma" else model


class _StableLomax:
    """An exponential with a gamma prior, whose predictive is closed form (Lomax): S(x) = (b / (b + x))^a,
    h(x) = a / (b + x). SurPyval 0.26 works out its density as a * b**a / (b + x)**(a + 1) in plain floats,
    which overflows (and so fails sf, hf, ... alike) when b is large: a library record's gamma on a rate
    per hour has b near 1e9 hours, and a above about 33 then overflows. These five are worked out here on
    the log scale; everything else is the SurPyval model's."""

    def __init__(self, model, exact: dict):
        self._model = model
        self._a, self._b = (float(v) for v in exact["params"])

    def __getattr__(self, name):
        return getattr(self._model, name)

    def _at(self, x, fn):
        x = np.asarray(x, dtype=float)
        xs = np.maximum(np.nan_to_num(x, nan=0.0), 0.0)
        return np.where(np.isnan(x), np.nan, fn(xs))

    def sf(self, x):
        return self._at(x, lambda t: np.exp(-self._a * np.log1p(t / self._b)))

    def ff(self, x):
        return self._at(x, lambda t: -np.expm1(-self._a * np.log1p(t / self._b)))

    def hf(self, x):
        return self._at(x, lambda t: self._a / (self._b + t))

    def Hf(self, x):  # noqa: N802 - SurPyval's name
        return self._at(x, lambda t: self._a * np.log1p(t / self._b))

    def df(self, x):
        return self._at(x, lambda t: self._a / (self._b + t) * np.exp(-self._a * np.log1p(t / self._b)))


def rebuild(spec: dict):
    """A saved update's model, refitted from its recipe (the data and the prior)."""
    from surpyval.bayes.prior import PriorSpec

    b = spec["bayes"]
    x = np.asarray(b["x"], dtype=float).reshape(-1, 2)
    return _fit(spec["distribution_id"], x, np.asarray(b["c"], dtype=int), PriorSpec.from_dict(b["priors"]),
                spec.get("unit"))


def _moved(base: dict, post: list[dict], rows: list[dict], unit: str) -> str:
    """What moved the baseline and how far, in words."""
    used = [r for r in rows if r.get("used", True)]
    fails = [r for r in used if r["c"] != 1]
    u = _unit_word(unit)
    if fails:
        ages = sorted(r["x"] for r in fails)
        at = ", ".join(num(a) for a in ages[:-1]) + (" and " if len(ages) > 1 else "") + num(ages[-1])
        who = f"{len(fails)} failure{'s' if len(fails) != 1 else ''} at {at}{(' ' + u) if u else ''}"
    else:
        who = f"{len(used)} unit{'s' if len(used) != 1 else ''} still running and none failed"
    if not base.get("params"):
        said = [f"{WORDS.get(p['name'], p['name'])} about {num(p['median'])}" for p in post if p["median"] is not None]
        return f"{who[0].upper()}{who[1:]} gave the belief its numbers: {', '.join(said)}." if said \
            else f"{who[0].upper()}{who[1:]} gave the belief its numbers."
    whose = "the prior's " if base.get("params_from") == "prior" else ""
    parts, still = [], []
    for p in post:
        b = base["params"].get(p["name"])
        if b is None or p["median"] is None:
            continue
        change = (p["median"] - b) / b if b else 0
        word = WORDS.get(p["name"], p["name"])
        if abs(change) < 0.05:
            still.append(word)
        else:
            unit_txt = f" {u}" if p["name"] == "alpha" and u else ""
            parts.append(f"{'pulled' if change < 0 else 'pushed'} the {word} from {whose}{num(b)}{unit_txt} to about "
                         f"{num(p['median'])}{unit_txt}")
    text = who + (" " + " and ".join(parts) if parts else " left the baseline about where it was")
    if still and parts:
        text += f"; the {' and the '.join(still)} barely moved"
    return text + "."


def update(base: dict, trust: str, rows: list[dict], age: float | None = None,
           priors=None, subject: str = "the position's best B10") -> tuple[Any, dict, Any]:
    """The update: (the SurPyval model or None with no data, the result for the reader, the prior).
    ``priors``: built by the caller (a power prior from the class's history: fit_life.py).
    ``subject``: what the result's words call the B10 (a dataset's fit isn't a position's)."""
    dist_id = base["distribution"]
    if priors is not None:
        pass
    elif base["source"] == "update":
        from surpyval.bayes.prior import PriorSpec

        priors = PriorSpec.from_dict(base["recipe"]["priors"])
    else:
        priors = priors_for(base, trust)
    unit = base.get("unit") or ""
    dist = DISTS[dist_id]
    x, c = arrays(rows)
    try:
        prior = prior_table(dist_id, priors)
    except Exception:  # noqa: BLE001 - a prior SurPyval can't summarise before data still fits
        prior = []
    if not base.get("params"):
        medians = {p["name"]: p["median"] for p in prior if p["name"] in dist.parameter_names and p["median"] is not None}
        if len(medians) == len(dist.parameter_names):
            # A baseline stated only as a prior: its medians are its numbers (the dashed curve, "moved from").
            base = {**base, "params": medians, "params_from": "prior"}
    failures = int(np.sum(c != 1))
    suspensions = int(np.sum(c == 1))
    t = TRUST.get(trust, TRUST["guide"])
    result = {
        "method": METHOD, "level": LEVEL, "distribution": dist_id, "distribution_label": LABELS[dist_id], "unit": unit,
        "baseline": {k: base.get(k) for k in ("source", "name", "model_id", "params", "params_from")},
        "trust": {"id": trust, **t} if base["source"] != "update" else {"id": "kept", "label": "As the earlier update",
                                                                          "words": "the earlier update's prior"},
        "counts": {"failures": failures, "suspensions": suspensions}, "prior": prior,
        "rows": rows, "label": label_for(base, failures, suspensions),
    }
    if not len(c):
        # No history: the baseline stands as given (the prior is the answer).
        result.update(posterior=[{**p, "baseline": base["params"].get(p["name"])} for p in prior
                                 if p["name"] in dist.parameter_names],
                      b10=next(({"point": p["median"], "lower": p["lower"], "upper": p["upper"]}
                                for p in prior if p["name"] == "B10"), None),
                      mean=next(({"point": p["median"], "lower": p["lower"], "upper": p["upper"]}
                                 for p in prior if p["name"] == "mean"), None),
                      at_age=None, curves=None, can_save=False,
                      words=f"No history to update with yet: the baseline ({base['name']}) stands as given, with the "
                            "range the trust allows. Add failures or running units first.")
        return None, result, priors
    from backend.warn_capture import collect_warnings

    with collect_warnings() as said:
        model = _fit(dist_id, x, c, priors, unit)
    # SurPyval says when the data disagree with the prior ("neither is taken as right"): pass it on.
    result["warnings"] = sorted({str(w.message) for w in said if "prior" in str(w.message).lower()})[:3]
    post = []
    for name, median in zip(dist.parameter_names, model.params):  # the params are the posterior medians
        lo, hi = model.param_cri(name, alpha_ci=ALPHA)
        post.append({"name": name, "label": WORDS.get(name, name), "median": _f(median),
                     "lower": _f(lo), "upper": _f(hi), "baseline": base["params"].get(name)})
    # B-lives and the mean life: a 90% one-sided lower credible bound (a lower
    # bound on life), the rule everywhere and what the saved model's page shows
    # (life_bounds). Parameters keep their 90% two-sided credible intervals.
    b10_lower = np.ravel(model.quantile_cri(0.1, alpha_ci=ALPHA, bound="lower"))[0]
    mean_lower = np.ravel(model.mean_cri(alpha_ci=ALPHA, bound="lower"))[0]
    result.update(
        posterior=post,
        b10={"point": _f(model.quantile_cri(0.1, alpha_ci=ALPHA, point=True)), "lower": _f(b10_lower), "upper": None,
             "bound": "lower", "level": LEVEL, "next_unit": _f(model.qf(0.1))},
        mean={"point": _f(np.ravel(model.mean())[0]), "lower": _f(mean_lower), "upper": None, "bound": "lower",
              "level": LEVEL},
        at_age=None, curves=curves(model, base, dist_id, float(np.max(x)) if len(x) else None), can_save=True,
    )
    if age is not None and _f(age) and float(age) > 0:
        lo_hi = np.ravel(model.cri(float(age), alpha_ci=ALPHA))
        result["at_age"] = {"age": float(age), "reliability": _f(np.ravel(model.sf(float(age)))[0]),
                            "lower": _f(lo_hi[0]), "upper": _f(lo_hi[1])}
    result["moved"] = _moved(base, post, rows, unit)
    u = _unit_word(unit)
    b = result["b10"]
    how = ("its earlier prior" if base["source"] == "update" else "as stated" if base["source"] in ("around", "belief", "library")
           else t["label"].lower())
    result["words"] = (f"{result['moved']} Starting from {base['name']} ({how}), "
                       f"{subject} is about {num(b['point'])}{(' ' + u) if u else ''}: we're {LEVEL:.0%} sure "
                       f"it's at least {num(b['lower'])}{(' ' + u) if u else ''} ({LEVEL:.0%} one-sided credible "
                       "bound).")
    return model, result, priors


def curves(model, base: dict, dist_id: str, x_max: float | None = None) -> dict:
    """The plot: the baseline's reliability and hazard, the updated (predictive) reliability
    and its 90% credible band, and the updated hazard, over ages to where 99% of new units have
    failed."""
    dist = DISTS[dist_id]
    hi = None
    for q in (0.99, 0.95, 0.9):
        try:
            v = float(np.ravel(model.qf(q))[0])
        except Exception:  # noqa: BLE001 - a quantile that doesn't converge: try a lower one
            continue
        if math.isfinite(v) and v > 0:
            hi = v
            break
    if hi is None:
        hi = float(x_max) * 2 if x_max else 1.0
    base_model = None
    if base.get("params") and all(n in base["params"] for n in dist.parameter_names):
        base_model = dist.from_params([base["params"][n] for n in dist.parameter_names])
        try:
            hi = max(hi, float(np.ravel(base_model.qf(0.99))[0]))
        except Exception:  # noqa: BLE001
            pass
    grid = np.linspace(0, hi, GRID)
    band = np.asarray(model.cri(grid, alpha_ci=ALPHA))
    fx = lambda a: [_f(v) for v in np.ravel(a)]  # noqa: E731
    out = {"x": fx(grid), "sf": fx(model.sf(grid)), "sf_lower": fx(band[:, 0]), "sf_upper": fx(band[:, 1]),
           "baseline_sf": fx(base_model.sf(grid)) if base_model is not None else None,
           "baseline_hf": fx(base_model.hf(grid)) if base_model is not None else None,
           "hf": fx(model.hf(grid))}
    return out


#: How a saved update was fitted, for the model page's "How it was fitted" and the API.
HOW = "Bayesian update"


def plot_for(model, dist_id: str, x, c) -> dict | None:
    """The probability plot of a saved update: the data's own points (Nelson-Aalen plotting
    positions, as a plain fit places them) with the updated model's line and its credible band on
    the distribution's paper. None when the points can't be placed (fewer than two failures: the
    prior is doing the work), and the page says so instead."""
    from backend import fitting

    if int(np.sum(np.asarray(c) != 1)) < 2:
        return None
    dist = DISTS[dist_id]
    try:
        plain = dist.fit(x, c)
        data = plain.get_plot_data(heuristic="Nelson-Aalen")
        shaped = fitting._shape_plot(plain, dist)
        params = list(np.ravel(model.params))
        grid = np.asarray(data["x_model"], dtype=float)
        eps = 1e-9

        def ty(pv):
            return dist.mpp_y_transform(np.clip(np.asarray(pv, dtype=float), eps, 1 - eps), *params)

        tx = dist.mpp_x_transform(grid)
        with np.errstate(all="ignore"):
            band = np.asarray(model.cri(grid, on="ff", alpha_ci=ALPHA), dtype=float).reshape(-1, 2)
            shaped["line"] = {"x": tx.tolist(), "y": ty(model.ff(grid)).tolist()}
            shaped["bounds"] = {"x": tx.tolist(), "lower": ty(band[:, 0]).tolist(), "upper": ty(band[:, 1]).tolist()}
        keep = fitting.failure_positions_mask(plain, len(data["x_"]))
        shaped["empirical"] = fitting._empirical_points(model, data, keep, "Nelson-Aalen")
        return shaped
    except Exception:  # noqa: BLE001 - a plot is a convenience, never a reason not to save
        return None


def plot_note(failures: int) -> str:
    """Why a saved update has no probability plot."""
    return (f"No probability plot: placing the points needs at least two failures, and this update has "
            f"{failures}. Until then the prior does the work; the Calculator draws the curve with its credible band.")


def label_for(base: dict, failures: int, suspensions: int) -> str:
    return (f"Bayesian update of {base['name']} with {failures} failure{'s' if failures != 1 else ''}, "
            f"{suspensions} suspension{'s' if suspensions != 1 else ''}")


def save(db, owner_id: str, model, result: dict, priors, name: str | None = None, notes: str = ""):
    """Save an update as a non-repairable model (the usual shape, so RBD blocks, evidence links
    and the calculators use it): its parameters are the posterior medians with 90% credible
    intervals, its curves the predictive ones, and its recipe (the data and the prior) rebuilds it."""
    from backend import fitting, life_bounds
    from backend.db import to_doc
    from backend.schema import Model
    from backend.services import datasets as datasets_service
    from backend.services import models as models_service
    from backend.units import canonical_unit

    if model is None:
        raise BayesError("There's no history to update with, so nothing to save: the baseline stands as it is.")
    dist_id = result["distribution"]
    rows = [r for r in result["rows"] if r.get("used", True)]
    xs, cs = arrays(rows)
    buf = io.StringIO()
    pd.DataFrame({"shortest": xs[:, 0], "longest": xs[:, 1], "censored": cs}).to_csv(buf, index=False)
    label = (name or result["label"]).strip()[:200]
    dataset = datasets_service.create_dataset(db, f"{label[:150]}: data.csv", buf.getvalue().encode(), owner_id)
    unit = result.get("unit") or ""
    grid = np.asarray(result["curves"]["x"], dtype=float)
    curves_all = fitting._eval_functions(model, grid)
    b10, mean = result["b10"], result["mean"]
    ci_note = (f"The bounds are {LEVEL:.0%} credible intervals from a Bayesian update: there's a {LEVEL:.0%} "
               "chance the value lies between them, given the baseline and the data. They aren't confidence "
               "bounds.")
    results = {
        "distribution": LABELS[dist_id], "distribution_id": dist_id, "kind": "distribution",
        "params": [{"name": p["name"], "value": p["median"], "se": None, "ci": [p["lower"], p["upper"]]}
                   for p in result["posterior"]],
        "n": int(len(cs)), "unit": canonical_unit(unit),
        # model_id: any value, so the reads point the calculator at the saved model (public_results).
        "functions": {"meta": fitting.FUNCTIONS, "curves": curves_all, "model_id": "saved"},
        "gof": [], "method": METHOD, "credible_level": LEVEL, "ci_note": ci_note,
        # The page's "How it was fitted" and the API read these; the plot is the data's points under
        # the updated line (None, with the reason, under two failures); the life card's B-lives and
        # mean carry their credible lower bounds (life_bounds knows a Bayesian fit).
        "options": {"how": HOW},
        "plot": plot_for(model, dist_id, xs, cs),
        "split": {"failed": result["counts"]["failures"], "running": result["counts"]["suspensions"], "other": 0},
        "bayes": {"label": result["label"], "baseline": result["baseline"], "trust": result["trust"],
                  "prior": result["prior"], "b10": b10, "mean": mean, "words": result.get("words", "")},
    }
    if results["plot"] is None:
        results["plot_note"] = plot_note(result["counts"]["failures"])
    life = life_bounds.life_for(model)
    if life:
        results["life"] = life
    spec = {"method": METHOD, "distribution_id": dist_id, "unit": unit,
            "mapping": {"xl": "shortest", "xr": "longest", "c": "censored"},
            "notes": notes or "",
            "bayes": {"x": xs.tolist(), "c": cs.tolist(), "priors": model.to_dict()["priors"]}}
    doc = Model(id=models_service.uuid.uuid4().hex, name=label, owner_id=owner_id, dataset_id=dataset.id,
                kind="distribution", distribution_id=dist_id, spec=spec, results=fitting._json_safe(results),
                serialized=None, surpyval_version=_sp_version())
    db.models.insert_one(to_doc(doc))
    return doc


def _sp_version() -> str | None:
    from importlib.metadata import version

    try:
        return version("surpyval")
    except Exception:  # noqa: BLE001
        return None


def live_cache_id(spec: dict) -> str:
    """Rebuild a saved update and keep it live for the calculators (fitting's store)."""
    from backend import fitting

    model = rebuild(spec)
    return fitting._store_model(model, np.linspace(0, _upper_time(model, spec.get("distribution_id")), 300), [])


def _upper_time(model, dist_id: str | None) -> float:
    """The time 99% have failed by, for the calculators' grid. The predictive quantile is a root
    search that can fail to converge on a long-tailed posterior (a shape well below 1), so it falls
    back to the posterior medians' own quantile."""
    try:
        t = float(np.ravel(model.qf(0.99))[0])
        if np.isfinite(t) and t > 0:
            return t
    except Exception:  # noqa: BLE001 - fall back below
        pass
    dist = DISTS.get(dist_id) if dist_id else None
    if dist is None:
        raise ValueError("Couldn't place this update's time range.")
    return float(np.ravel(dist.qf(0.99, *np.ravel(model.params)))[0])
