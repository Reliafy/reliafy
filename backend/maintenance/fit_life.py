"""Fit a life model to a position (the Modelling tab's "Fit a life model…", Derryn 9 Nov 2026:
"'From history' needs to include the class and Bayesian ... fit from a Bayesian prior").

Two choices, in plain words:

* **Which data:** this position's own history (each item fitted there: days in service, failed
  or still running), the class's pooled history (every position of the same class, the pool
  the class model uses), or both: this position's history, with the class's history as the
  prior.
* **Which method:** a plain fit (maximum likelihood: the numbers that make the data most likely,
  with 95% confidence bounds), or a fit with a prior (Bayesian: what was believed beforehand,
  moved by the data, with 90% credible intervals). The prior is the class's history, a saved
  model, numbers you know or a B10 you believe.

The class's history as a prior is SurPyval's power prior, ``prior.from_data(x, c, weight=...)``:
the class's own likelihood, counted at a weight (trust it closely: all of it; as a guide: half;
only a starting point: a fifth). At a weight below one SurPyval needs a proper prior on every
parameter besides, so very wide ones are added around the class's own fit (its life within a
factor of 20, a Weibull shape between 0.2 and 20) and the result says so. A saved model is
``prior.from_model``, numbers ``prior.from_params`` and a B10 ``prior.on_quantities``
(bayes_life.py builds those). The class's data are never both the data and the prior.
"""

from __future__ import annotations

import io

import numpy as np

DATA = ("position", "class", "both")
METHODS = ("mle", "bayes")
DISTRIBUTIONS = ("weibull", "exponential", "lognormal", "best")
WIDE = 20.0  # the class fit's life within a factor of this, when a weight below one needs it


def _sv():
    from backend.maintenance import service

    return service


def _refused(message: str, context: dict):
    """A refusal that still carries what the dialog shows beside it (the history used, its counts,
    the class's numbers): the preview answers it in words with these."""
    err = _sv().Invalid(message)
    err.context = context
    return err


def _in_unit(rows: list[dict], per: float, exclude) -> list[dict]:
    """Life rows (days) in a unit of ``per`` days, each marked used unless excluded."""
    skip = set(exclude or ())
    out = []
    for r in rows:
        row = {k: r.get(k) for k in ("fitment_id", "item", "from", "to", "status", "failure_mode", "position",
                                     "position_id")}
        row.update(c=r["c"], x=r["x"] / per, used=r.get("fitment_id") not in skip)
        if r["c"] == 2:
            row.update(xl=r["xl"] / per, xr=r["xr"] / per)
        if (row.get("xr") if r["c"] == 2 else row["x"]) <= 0:
            row["used"] = False
        out.append(row)
    return out


def _counts(rows: list[dict]) -> dict:
    used = [r for r in rows if r.get("used", True)]
    return {"failures": sum(1 for r in used if r["c"] != 1), "suspensions": sum(1 for r in used if r["c"] == 1)}


def class_summary(m, position_id: str) -> dict | None:
    """The class's pooled history in numbers: {name, positions, failures, suspensions}, or None."""
    p = m._get(position_id, "Position")
    name = (p.get("position_class") or "").strip()
    if not name:
        return None
    try:
        data = m.class_life_data(name)
    except _sv().NotFound:
        return {"name": name, "positions": 0, "failures": 0, "suspensions": 0}
    return {"name": data["position_class"], "positions": len({r["position_id"] for r in data["rows"]}),
            "failures": data["failures"], "suspensions": data["suspensions"]}


def _rows(m, position_id: str, scope: str, texts: set, exclude, per: float) -> list[dict]:
    from backend.maintenance.position_models import _rows_for

    sv = _sv()
    p = m._get(position_id, "Position")
    if scope == "class":
        name = (p.get("position_class") or "").strip()
        if not name:
            raise sv.Invalid(f"{p['name']} has no position class, so there's no class history to use.")
        try:
            raw = m.class_life_data(name)["rows"]
        except sv.NotFound:
            raw = []
    else:
        raw = m.design_rollup(position_id)["life_data"]["rows"] if m._design_root_of(position_id) else m.life_data(position_id)
    return _in_unit(_rows_for(m, raw, texts), per, exclude)


def _arrays(rows):
    from backend.services.bayes_life import arrays

    return arrays(rows)


def _words_for_data(data: str, cls: dict | None) -> str:
    if data == "class":
        return f"the class {cls['name']}'s pooled history ({cls['positions']} positions)" if cls else "the class's history"
    return "this position's history"


def fit(m, db, owners, hidden, position_id: str, data: str = "position", method: str = "mle", prior: dict | None = None,
        distribution: str = "weibull", failure_mode_ids=None, exclude=(), trust: str = "guide", age=None,
        save: bool = False, name: str | None = None, note: str = "", replace_link_id: str | None = None,
        owner_id: str | None = None) -> dict:
    """The fit, previewed (``save`` false) or saved to Models and attached. ``prior``: {kind: class |
    model | params | b10, ...} for method bayes (kind class is the class's history as a power prior;
    the others as bayes_life.baseline_from takes them: model_id; distribution, params, unit; b10,
    shape, unit). ``data`` both is this position's history with the class's history as the prior."""
    import surpyval as sp

    from backend.services import bayes_life as bl

    sv = _sv()
    if data not in DATA:
        raise sv.Invalid(f"The data is one of {', '.join(DATA)}.")
    if method not in METHODS:
        raise sv.Invalid(f"The method is one of {', '.join(METHODS)} (mle: a plain fit; bayes: with a prior).")
    if distribution not in DISTRIBUTIONS:
        raise sv.Invalid(f"The distribution is one of {', '.join(DISTRIBUTIONS)}.")
    p = m._get(position_id, "Position")
    if p.get("retired"):
        raise sv.Invalid(f"{p['name']} has been retired: restore it first.")
    prior = dict(prior or {})
    if data == "both":
        if prior and prior.get("kind") not in (None, "class"):
            raise sv.Invalid("“Both” already uses the class's history as the prior; to use another prior, choose "
                             "this position's history with that prior.")
        method, prior = "bayes", {"kind": "class"}
    if method == "bayes":
        if not prior:
            prior = {"kind": "class"}
        if data == "class" and prior.get("kind") == "class":
            raise sv.Invalid("The class's pooled history is the data here, so it can't be the prior too: that would "
                             "count it twice. Choose a saved model, numbers you know or a B10 as the prior.")
        if distribution == "best":
            raise sv.Invalid("“Best of” is for a plain fit; with a prior, choose Weibull, exponential or lognormal.")
    modes = m._mode_ids_on(position_id, failure_mode_ids)
    texts = {(m.s.node(m.org, mid) or {}).get("text", "").strip().lower() for mid in modes}
    cls = class_summary(m, position_id)
    if (data == "class" or prior.get("kind") == "class") and (cls is None or not cls["failures"] + cls["suspensions"]):
        raise sv.Invalid(f"{p['name']} has no class history to use: " + (
            "it has no position class." if cls is None else f"no position of the class {cls['name']} has any history yet.")
            + " Choose this position's history, or another prior.")

    base = None
    unit = "days"
    if method == "bayes" and prior.get("kind") == "library":
        from backend.maintenance import library_models

        base = library_models.prior_base(prior, distribution, db, owners)
        unit, distribution = base["unit"], base["distribution"]
    elif method == "bayes" and prior.get("kind") == "around":
        base = around_prior(prior, distribution)
        unit = base.get("unit") or "days"
        distribution = base["distribution"]
    elif method == "bayes" and prior.get("kind") != "class":
        spec = {k: v for k, v in prior.items() if k != "kind"}
        try:
            base = bl.baseline_from(db, owners, hidden, spec)
        except bl.BayesError as err:
            raise sv.Invalid(str(err)) from None
        unit = base.get("unit") or "days"
        distribution = base["distribution"]
    try:
        per = bl.time_factor(unit)
    except bl.BayesError as err:
        raise sv.Invalid(str(err)) from None
    rows = _rows(m, position_id, "class" if data == "class" else "position", texts, exclude, per)
    counts = _counts(rows)
    context = {"rows": rows, "counts": counts, "class_history": cls, "unit": unit, "method": method, "data": data}
    try:
        return _fit_on(m, db, p, position_id, data, method, prior, distribution, modes, texts, trust, age, save, name,
                       note, replace_link_id, owner_id, cls, base, unit, per, rows, counts)
    except sv.Invalid as err:
        if getattr(err, "context", None) is None:
            raise _refused(str(err), context) from None
        raise


def _fit_on(m, db, p, position_id, data, method, prior, distribution, modes, texts, trust, age, save, name, note,
            replace_link_id, owner_id, cls, base, unit, per, rows, counts):
    import surpyval as sp

    from backend.services import bayes_life as bl

    sv = _sv()

    if method == "mle":
        result, model = _mle(p, rows, counts, distribution, unit, data, cls)
        c = result.get("curves") or {}
        if age and c.get("x") and c.get("sf"):
            # Reliability at the age asked, read off the fitted curve (and its 95% band).
            t = float(age)
            at = lambda ys: float(np.interp(t, c["x"], ys)) if ys else None  # noqa: E731
            result["at_age"] = {"age": t, "reliability": at(c["sf"]), "lower": at(c.get("sf_lower")),
                                "upper": at(c.get("sf_upper"))}
    else:
        if prior.get("kind") == "class":
            # The class's other positions: this one's own history is the data, so it isn't in the prior too.
            class_rows = [r for r in _rows(m, position_id, "class", texts, (), per) if r.get("position_id") != position_id]
            if not class_rows:
                raise sv.Invalid(f"The class {cls['name']} has no history besides {p['name']}'s own, so there's no class "
                                 "prior to use: fit this position's history, or choose another prior.")
            base, priors, extra = _class_prior(sp, distribution, class_rows, trust, cls, unit)
            try:
                bl.update(base, trust, rows, None, priors) if not extra else None
            except ValueError as err:
                if "finite mass" not in str(err):
                    raise sv.Invalid(f"The fit with that prior didn't work: {err}") from None
                base, priors, extra = _class_prior(sp, distribution, class_rows, trust, cls, unit, force_wide=True)
        elif base.get("source") == "around":
            priors, extra = base["priors"], ""
        elif base.get("source") == "library":
            priors, extra = base["priors"], base["note"]
        else:
            # An earlier update as the prior carries its own (bayes_life.update reads its recipe).
            priors, extra = (None if base["source"] == "update" else bl.priors_for(base, trust)), ""
        try:
            model, result, priors = bl.update(base, trust if base["source"] != "update" else "guide", rows, age, priors)
        except Exception as err:  # noqa: BLE001 - SurPyval refuses some posteriors in words: pass them on
            raise sv.Invalid(f"The fit with that prior didn't work: {err}") from None
        result.update(method="bayes", interval_label=f"{bl.LEVEL:.0%} credible interval", data=data,
                      class_history=cls, prior_kind=prior.get("kind"))
        if extra:
            result["words"] = f"{result.get('words', '')} {extra}".strip()
            result["prior_note"] = extra
    result["position"] = {"id": p["id"], "name": p["name"]}
    result["class_history"] = cls
    result["failure_modes"] = [{"id": mid, "text": (m.s.node(m.org, mid) or {}).get("text", "")} for mid in modes]
    if not save:
        result.pop("_model", None)
        return result
    return _save(m, db, p, result, model, rows, modes, data, method, distribution, unit, name, note, replace_link_id,
                 owner_id or m.org, cls)


def _class_prior(sp, distribution: str, class_rows: list[dict], trust: str, cls: dict, unit: str,
                 force_wide: bool = False):
    """The class's history as a power prior, with the wide priors a weight below one needs. Returns
    (base for the result, priors, the words saying what was added)."""
    from backend.services import bayes_life as bl

    dist = bl.DISTS[distribution]
    cx, cc = _arrays(class_rows)
    if not (cc == 2).any():
        cx = cx[:, 0]  # plain ages: SurPyval's power prior takes them as fit does
    weight = bl.TRUST.get(trust, bl.TRUST["guide"])["weight"]
    power = sp.prior.from_data(x=cx, c=cc, dist=dist, weight=weight)
    params, extra = {}, ""
    priors: list = [power]
    try:
        mle = dist.fit(x=cx, c=cc)
        params = dict(zip(dist.parameter_names, [float(v) for v in mle.params]))
    except Exception:  # noqa: BLE001 - without the class's own fit there's no centre for the wide priors
        mle = None
    if (weight < 1 or force_wide) and params:
        wide = {}
        if distribution == "weibull":
            a = params["alpha"]
            wide = {"alpha": sp.prior.around(a, between=(a / WIDE, a * WIDE)), "beta": sp.prior.between(0.2, 20)}
            extra = (f"So the maths has an answer with this little history, the life was also held within a factor of {WIDE:g} of "
                     "the class's and the shape between 0.2 and 20: wide enough to say almost nothing.")
        elif distribution == "lognormal":
            mu = params["mu"]
            wide = {"mu": sp.prior.around(mu, between=(mu - 3, mu + 3)), "sigma": sp.prior.between(0.05, 5)}
            extra = "So the maths has an answer with this little history, the spread was also held between 0.05 and 5: very wide."
        if wide:
            priors.append(wide)
    word = {1.0: "all", 0.5: "half", 0.2: "a fifth"}.get(weight, f"{weight:g}")
    others = len({r.get("position_id") for r in class_rows})
    fails = sum(1 for r in class_rows if r["c"] != 1)
    name = (f"the class {cls['name']}'s pooled history ({fails} failure{'s' if fails != 1 else ''} at {others} other "
            f"position{'s' if others != 1 else ''}, counted as {word} of its evidence)")
    base = {"source": "class", "name": name, "distribution": distribution, "unit": unit, "params": params}
    return base, priors, extra


def _mle(p, rows: list[dict], counts: dict, distribution: str, unit: str, data: str, cls):
    """A plain fit (maximum likelihood) in the shape the dialog shows, with 95% confidence bounds."""
    import pandas as pd

    from backend import fitting
    from backend.maintenance import loop

    sv = _sv()
    used = [r for r in rows if r.get("used", True)]
    needed = 1 if distribution == "exponential" else loop.MIN_FAILURES
    if counts["failures"] < needed:
        hint = " With one failure, fit exponential (a constant failure rate), or use a prior." \
            if counts["failures"] == 1 and distribution != "exponential" else " Or fit with a prior."
        raise sv.Invalid(f"{_words_for_data(data, cls)[0].upper()}{_words_for_data(data, cls)[1:]} has "
                         f"{counts['failures']} failure{'s' if counts['failures'] != 1 else ''}; a plain "
                         f"{distribution} fit needs at least {needed}.{hint}")
    df, mapping = _frame(pd, used)
    res = fitting.fit(distribution, df, mapping, unit=unit)
    params = {pp["name"]: pp for pp in res.get("params") or []}
    post = []
    for pname, pp in params.items():
        ci = pp.get("ci") or [None, None]
        post.append({"name": pname, "label": {"alpha": "characteristic life", "beta": "shape", "failure_rate":
                                              "failure rate", "mu": "log-scale (mu)", "sigma": "spread (sigma)"}.get(pname, pname),
                     "median": pp.get("value"), "lower": ci[0], "upper": ci[1], "baseline": None})
    life = res.get("life") or {}
    b10 = next((b for b in life.get("b_lives") or [] if b.get("label") == "B10"), {})
    mttf = life.get("mttf") or {}
    curves = (res.get("functions") or {}).get("curves") or {}
    out_curves = {"x": curves.get("x"), "sf": curves.get("sf"), "hf": curves.get("hf"), "sf_lower": None,
                  "sf_upper": None, "baseline_sf": None}
    try:
        cb = fitting.confidence_bounds((res.get("functions") or {}).get("model_id"), on="sf")
        out_curves["sf_lower"], out_curves["sf_upper"] = cb.get("lower"), cb.get("upper")
    except Exception:  # noqa: BLE001 - the line stands without its band
        pass
    from backend.services.bayes_life import num

    u = unit.lower()
    lead = next((x for x in post if x["name"] in ("alpha", "failure_rate", "mu")), None)
    shape = next((x for x in post if x["name"] == "beta"), None)
    words = (f"A plain fit (maximum likelihood) to {counts['failures']} failure{'s' if counts['failures'] != 1 else ''} "
             f"and {counts['suspensions']} suspension{'s' if counts['suspensions'] != 1 else ''} in "
             f"{_words_for_data(data, cls)}")
    if lead and lead["name"] == "alpha":
        words += (f": characteristic life about {num(lead['median'])} {u} (95% confidence {num(lead['lower'])}–"
                  f"{num(lead['upper'])})")
        if shape:
            words += f", shape {num(shape['median'])}"
    words += "."
    result = {
        "plot": res.get("plot"),  # the probability plot (data points, the fit, its bounds), as on the Models page
        "method": "mle", "interval_label": "95% confidence bounds", "data": data, "distribution": res.get("distribution_id"),
        "distribution_label": res.get("distribution"), "unit": unit, "counts": counts, "rows": rows, "prior": [],
        "posterior": post,
        "b10": {"point": b10.get("value"), "lower": b10.get("lower"), "upper": None, "bound": "lower"} if b10 else None,
        "mean": {"point": mttf.get("value"), "lower": mttf.get("lower"), "upper": None, "bound": "lower"} if mttf else None,
        "curves": out_curves, "words": words, "can_save": True,
        "label": f"{p['name']}: plain fit to {_words_for_data(data, cls)}",
    }
    return result, None


def _frame(pd, used: list[dict]):
    from backend.maintenance import loop

    buf = io.StringIO()
    if any(r["c"] == 2 for r in used):
        pd.DataFrame(loop._interval_rows(used), columns=["shortest", "longest", "censored"]).to_csv(buf, index=False)
        mapping = {"xl": "shortest", "xr": "longest", "c": "censored"}
    else:
        pd.DataFrame({"time": [r["x"] for r in used], "censored": [r["c"] for r in used]}).to_csv(buf, index=False)
        mapping = {"x": "time", "c": "censored"}
    buf.seek(0)
    return pd.read_csv(buf), mapping


def _save(m, db, p, result, model, rows, modes, data, method, distribution, unit, name, note, replace_link_id,
          owner, cls):
    """Saved to Models and attached: a plain fit as a normal fitted model (role fitted), a fit with a
    prior as a Bayesian model with its recipe (role bayesian, so Update with new failures… works)."""
    import pandas as pd

    from backend.services import bayes_life as bl
    from backend.services import datasets as datasets_service
    from backend.services import models as models_service

    if method == "bayes":
        if model is None:
            raise _sv().Invalid("There's no history to fit to yet: nothing to save.")
        doc = bl.save(db, owner, model, result, None, name, note)
        source = {"method": bl.METHOD, "label": result["label"], "baseline": result["baseline"]["name"],
                  "baseline_model_id": result["baseline"].get("model_id"), "trust": result["trust"]["id"],
                  "scope": "class" if data == "class" else "position", "data": data,
                  "failures": result["counts"]["failures"], "suspensions": result["counts"]["suspensions"]}
        link = m.link_position_model(p["id"], "model", doc.id, "bayesian", modes, doc.name, note, source, replace_link_id)
        return {**link, "fit": {k: result.get(k) for k in ("words", "posterior", "b10", "mean", "counts", "label",
                                                          "interval_label", "method")}}
    used = [r for r in rows if r.get("used", True)]
    df, mapping = _frame(pd, used)
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    label = (name or f"{p['name']}{' (class ' + cls['name'] + ')' if data == 'class' and cls else ''} (from maintenance records)")[:200]
    dataset = datasets_service.create_dataset(db, f"{label[:150]}: life data.csv", buf.getvalue().encode(), owner)
    saved = models_service.save_model(db, label, dataset, distribution, mapping, [], None, unit, owner_id=owner)
    source = {"scope": "class" if data == "class" else "position", "failures": result["counts"]["failures"],
              "suspensions": result["counts"]["suspensions"], "distribution": saved.distribution_id, "method": "mle"} \
        | ({"class_name": cls["name"]} if data == "class" and cls else {})
    link = m.link_position_model(p["id"], "model", saved.id, "fitted", modes, saved.name, note, source, replace_link_id)
    return {**link, "fit": {k: result.get(k) for k in ("words", "posterior", "b10", "mean", "counts", "label",
                                                      "interval_label", "method")}}


def given_with_class_prior(m, position_id: str, rows: list[dict], distribution: str = "weibull", trust: str = "guide",
                           age=None) -> dict:
    """Data given directly (in days), with a position's class's pooled history as the power prior
    (core analyse bayes_update, class_power_prior)."""
    import surpyval as sp

    from backend.services import bayes_life as bl

    sv = _sv()
    if distribution not in bl.DISTS:
        raise sv.Invalid("With a prior, the distribution is weibull, exponential or lognormal.")
    cls = class_summary(m, position_id)
    if cls is None or not cls["failures"] + cls["suspensions"]:
        raise sv.Invalid("That position has no class history to use as the prior.")
    class_rows = [r for r in _rows(m, position_id, "class", set(), (), 1.0) if r.get("position_id") != position_id]
    if not class_rows:
        raise sv.Invalid("That position's class has no history besides its own to use as the prior.")
    base, priors, extra = _class_prior(sp, distribution, class_rows, trust, cls, "days", force_wide=True)
    try:
        _, result, _ = bl.update(base, trust, rows, age, priors)
    except Exception as err:  # noqa: BLE001
        raise sv.Invalid(f"The fit with that prior didn't work: {err}") from None
    result.update(method="bayes", interval_label=f"{bl.LEVEL:.0%} credible interval", class_history=cls)
    if extra:
        result["words"] = f"{result.get('words', '')} {extra}".strip()
    return result


AROUND_PARAMS = {"weibull": ("alpha", "beta"), "exponential": ("failure_rate", "mean"), "lognormal": ("mu", "sigma")}
_AROUND_WORDS = {"alpha": "alpha", "beta": "beta", "failure_rate": "the failure rate", "mean": "the mean life",
                 "mu": "mu", "sigma": "sigma"}


def around_prior(prior: dict, distribution: str) -> dict:
    """"Around a value, between two bounds": per parameter of the distribution, {about?, between: [lo, hi]}
    (90% of the prior between them; about the middle, else just between them), SurPyval's
    prior.around(about, between=(lo, hi)) or prior.between(lo, hi). A parameter left out is the data's
    alone. An exponential's may be given as its mean life (mean) instead of its rate. Returns the base
    the update reads: {source: around, name (the belief in words), distribution, unit, params, priors}."""
    import surpyval as sp

    from backend.services import bayes_life as bl

    sv = _sv()
    dist_id = (prior.get("distribution") or distribution or "weibull").lower()
    if dist_id not in bl.DISTS:
        raise sv.Invalid("Around a value, between two bounds takes a Weibull, exponential or lognormal.")
    given = prior.get("params") or {}
    if not isinstance(given, dict):
        raise sv.Invalid("The prior's params are {name: {about, between: [low, high]}}.")
    allowed = AROUND_PARAMS[dist_id]
    stray = sorted(set(given) - set(allowed))
    if stray:
        raise sv.Invalid(f"A {dist_id} prior takes {', '.join(allowed)}; not {', '.join(stray)}.")
    priors, words, params = {}, [], {}
    for name in allowed:
        spec = given.get(name)
        if not spec:
            continue
        between = spec.get("between") or [None, None]
        lo, hi = bl._f(between[0] if len(between) > 0 else None), bl._f(between[1] if len(between) > 1 else None)
        about = bl._f(spec.get("about"))
        label = _AROUND_WORDS[name]
        if lo is None or hi is None:
            raise sv.Invalid(f"Give {label} both bounds (between a low and a high), or leave it out.")
        if not lo < hi:
            raise sv.Invalid(f"For {label}, the low bound must be below the high one.")
        if about is not None and not lo < about < hi:
            raise sv.Invalid(f"For {label}, “about” must lie between the bounds.")
        positive = name != "mu"
        if positive and lo <= 0:
            raise sv.Invalid(f"{label[0].upper()}{label[1:]} is positive: give bounds above 0.")
        key, lo_k, hi_k, about_k = name, lo, hi, about
        if name == "mean":  # an exponential's mean life, as its rate
            key, lo_k, hi_k, about_k = "failure_rate", 1 / hi, 1 / lo, (1 / about if about else None)
        if key in priors:
            raise sv.Invalid("Give the exponential's rate or its mean life, not both.")
        priors[key] = sp.prior.around(about_k, between=(lo_k, hi_k)) if about_k is not None else sp.prior.between(lo_k, hi_k)
        if about_k is not None:
            params[key] = about_k
        words.append(f"{label} about {bl.num(about)}, 90% between {bl.num(lo)} and {bl.num(hi)}" if about is not None
                     else f"{label} 90% between {bl.num(lo)} and {bl.num(hi)}")
    if not priors:
        raise sv.Invalid("Give at least one parameter's bounds (the others are left to the data).")
    names = bl.DISTS[dist_id].parameter_names
    return {"source": "around", "name": "; ".join(words), "distribution": dist_id, "unit": prior.get("unit") or "days",
            "params": params if all(n in params for n in names) else {}, "priors": priors}
