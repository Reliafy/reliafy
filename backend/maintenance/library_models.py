"""Reliability data library records on the Modelling tab (Derryn, 9 Nov 2026: "a good way to use
models from a library. Especially the NUREG life models").

The library (backend/library) holds published component failure data: the NRC/INL 2020
industry-average parameters (failure rates per hour with a gamma uncertainty distribution, and
probabilities per demand with a beta) and handbook base rates. A record can be used two ways:

* **as a position's model** (Life model › From the data library…): a rate becomes an exponential
  model at the record's mean rate, its 5–95% range kept as the interval (labelled as the
  source's uncertainty, not a fit's confidence). The saved model and the link keep the record id
  and its citation: the licence asks for the record to be cited wherever it's used. A probability
  per demand isn't a life over time, and Reliafy's per-demand models are fitted from counts of
  demands and failures, which a record doesn't give: that's refused in words.
* **as a prior** (the Fit dialog's "A library record"): on an exponential, the record's gamma on the
  rate is the prior exactly (conjugate: the update is in closed form, and the result says so). On a
  Weibull or lognormal, the rate becomes a prior on the mean life, ``prior.on_quantities(dist,
  mean=around(1/mean, between=(1/p95, 1/p05)), ...)``, with the shape held between the bounds the
  user gives (default 0.5 to 5, said in the result). A per-demand record would be a prior on a
  Bernoulli probability, but a position's history counts lives, not demands: refused in words.
* **a life record** (a user library's snapshot of a saved model, backend/library/user.py) is a model
  of its own family with the snapshot's parameters and bounds, and as a prior it's SurPyval's
  ``from_params`` shape: each parameter about its value, 90% (or the bounds' level) between the
  record's bounds; with no bounds, within 30% of its value, and the note says so.
"""

from __future__ import annotations

DEFAULT_SHAPE = (0.5, 5.0)


def _sv():
    from backend.maintenance import service

    return service


def mine_for(db, owners) -> dict | None:
    """The caller's own libraries, for the reads that take them (None without a db)."""
    from backend.library import user as user_lib

    if db is None or owners is None:
        return None
    return user_lib.mine(db, owners)


def record(record_id: str, db=None, owners=None) -> dict:
    """The library record (its full shape), a published one or one of the owners' own, or an
    Invalid in words."""
    from backend.library import service as library_service

    sv = _sv()
    try:
        return library_service.get(str(record_id or ""), mine_for(db, owners))
    except Exception:  # noqa: BLE001 - an unknown id
        raise sv.Invalid(f"There's no library record '{record_id}': search the data library for one.") from None


def brief(rec: dict, mine: dict | None = None) -> dict:
    from backend.library import service as library_service

    return library_service.brief(rec, mine)


def cite(rec: dict, mine: dict | None = None) -> str:
    """"NRC/INL 2020, Motor-operated valve: fails to open (INL/EXT-21-65055, Table 1, p. 6)"; for a user
    library's record, "<library>, <label> (from the model <name>)"."""
    b = brief(rec, mine)
    if rec.get("basis") == "fitted":
        m = rec.get("model") or {}
        return f"{b.get('source')}, {b.get('label')}" + (f" (from the model {m['name']})" if m.get("name") else "")
    return f"{b.get('source')}, {b.get('label')}" + (f" ({b['citation']})" if b.get("citation") else "")


def _per_hour(rec: dict) -> bool:
    return (rec.get("kind") == "rate") and str((rec.get("units") or {}).get("value") or "").startswith("per_hour")


def _refuse_per_demand(rec: dict, use: str):
    b = brief(rec)
    return _sv().Invalid(
        f"“{b['label']}” is a probability per demand ({b['mean']:.3g} {b['units']}), not a life over time, so it can't "
        + ("be a position's life model: Reliafy's per-demand models are fitted from counts of demands and failures, "
           "which a library record doesn't give. Use its mean where a probability on demand is asked for."
           if use == "model" else
           "be a prior on a life model: it would be a prior on a probability per demand, and this position's history "
           "counts lives, not demands."))


def why_not(rec: dict, use: str = "model") -> str | None:
    """Why a record can't be a model (or a prior), in words; None when it can (the library's
    ``usable_as``, which the pickers search by, says the same)."""
    if rec.get("basis") == "prediction_model":
        b = brief(rec)
        return (f"“{b['label']}” is a handbook base rate for a parts count: on its own it isn't a model (the "
                "environment and quality factors make the rate). Use it in a prediction (Prediction › Add a "
                "prediction on a position).")
    if rec.get("kind") == "life":
        return None
    if not _per_hour(rec):
        return str(_refuse_per_demand(rec, use))
    return None


def save_record_model(db, owner_id: str, record_id: str, name: str | None = None, owners=None):
    """A rate record saved as an exponential model in the owner's models (the record's mean rate per
    hour; its 5–95% range as the interval, labelled as the source's uncertainty; the record id and
    citation kept). A life record is saved as a model of its own family with the record's parameters
    and bounds. ``owners``: the principals whose own libraries the record may come from (the owner
    alone by default)."""
    from backend.services import models as models_service

    mine = mine_for(db, owners if owners is not None else [owner_id])
    rec = record(record_id, db, owners if owners is not None else [owner_id])
    words = why_not(rec, "model")
    if words:
        raise _sv().Invalid(words)
    b = brief(rec, mine)
    if rec.get("kind") == "life":
        return _save_life_model(db, owner_id, rec, b, name, mine), rec
    rate = float(b["mean"])
    name = (name or f"{b['label']} ({b['source']})")[:200]
    model = models_service.import_model(db, owner_id, name, "exponential", unit="Hours",
                                        params=[{"name": "failure_rate", "value": rate}],
                                        notes=f"From the reliability data library: {cite(rec)}.")
    note_ci = ("The interval is the source's 5–95% uncertainty range on the rate (the industry-average spread), not "
               "a confidence bound from a fit.")
    db.models.update_one({"_id": model.id}, {"$set": {
        "results.method": "library",
        "results.params.0.ci": [b.get("p05"), b.get("p95")],
        "results.ci_note": note_ci,
        "results.library": {"record_id": rec["id"], "source": b.get("source"), "label": b.get("label"),
                            "citation": b.get("citation"), "units": b.get("units"), "distribution": b.get("distribution"),
                            "mean": b.get("mean"), "p05": b.get("p05"), "p95": b.get("p95")},
        "spec.library_record_id": rec["id"],
    }})
    return models_service.get_model(db, model.id), rec


def _save_life_model(db, owner_id: str, rec: dict, b: dict, name: str | None, mine: dict | None):
    """A life record (a saved model's snapshot) as a model of its own family in the owner's models,
    with the snapshot's parameters, their bounds as the interval (labelled as the record's), the
    record id and where it came from kept."""
    from backend.library import convert
    from backend.services import models as models_service

    made = convert.life_to_model(rec)
    name = (name or f"{b['label']} ({b['source']})")[:200]
    model = models_service.import_model(db, owner_id, name, made["model"]["distribution_id"], unit=made["unit"] or None,
                                        params=made["model"]["params"],
                                        notes=f"From the data library: {cite(rec, mine)}.")
    bounds = made.get("bounds") or {}
    level = made.get("bounds_level")
    changes = {"results.method": "library", "spec.library_record_id": rec["id"],
               "results.library": {"record_id": rec["id"], "source": b.get("source"), "label": b.get("label"),
                                   "citation": b.get("citation"), "units": b.get("units"),
                                   "distribution": b.get("distribution"), "mean": b.get("mean"), "p05": b.get("p05"),
                                   "p95": b.get("p95"), "library_id": rec["source"], "model": rec.get("model")}}
    if bounds:
        for i, p in enumerate(made["model"]["params"]):
            if p["name"] in bounds:
                changes[f"results.params.{i}.ci"] = bounds[p["name"]]
        changes["results.ci_note"] = (
            f"The interval is the library record's: the {level:.0%} bounds of the model it was taken from "
            "when it was added to the library." if level else
            "The interval is the library record's: the bounds of the model it was taken from.")
    db.models.update_one({"_id": model.id}, {"$set": changes})
    return models_service.get_model(db, model.id)


def attach(m, db, owner_id: str, position_id: str, record_id: str, failure_mode_ids=None, note: str = "",
           replace_link_id: str | None = None, owners=None) -> dict:
    """A library record as the position's model: an exponential at the record's mean rate (per hour),
    the record's 5–95% range as its interval (a life record: a model of its own family with the
    record's parameters); the link's source names the record and cites it."""
    modes = m._mode_ids_on(position_id, failure_mode_ids)
    model, rec = save_record_model(db, owner_id, record_id, owners=owners)
    b = brief(rec, mine_for(db, owners if owners is not None else [owner_id]))
    source = {"library": {"record_id": rec["id"], "source": b.get("source"), "label": b.get("label"),
                          "citation": b.get("citation")}}
    return m.link_position_model(position_id, "model", model.id, "library", modes, model.name, note, source,
                                 replace_link_id)


def recently_used(db, owners, limit: int = 5) -> list[dict]:
    """The records behind the owner's latest models from the library: [{record_id, label, source, model}]."""
    from backend.services import access

    out, seen = [], set()
    for d in db.models.find({"owner_id": {"$in": access.owner_in(owners)}, "results.method": "library"}).sort("created_at", -1):
        lib = (d.get("results") or {}).get("library") or {}
        if lib.get("record_id") in seen:
            continue
        seen.add(lib.get("record_id"))
        out.append({"record_id": lib.get("record_id"), "label": lib.get("label"), "source": lib.get("source"),
                    "model": {"id": d["_id"], "name": d.get("name")}})
        if len(out) >= limit:
            break
    return out


def fit_dataset(db, owners, dataset_id: str, time_column: str, censor_column: str | None, unit: str,
                prior: dict, distribution: str = "exponential", trust: str = "guide", c_invert: bool = False):
    """A saved dataset fitted with a library record as the prior (the Library page's "Use as a prior…"
    from the Models area): (the SurPyval model or None, the result as the Fit dialog shows it)."""
    from backend.services import bayes_life as bl
    from backend.services import datasets as datasets_service

    sv = _sv()
    ds = datasets_service.get_dataset(db, dataset_id, owners)
    if ds is None:
        raise sv.NotFound(f"Dataset {dataset_id}")
    df = datasets_service.load_dataframe(ds)
    if time_column not in df.columns:
        raise sv.Invalid(f"The dataset has no column '{time_column}'.")
    if censor_column and censor_column not in df.columns:
        raise sv.Invalid(f"The dataset has no column '{censor_column}'.")
    base = prior_base(prior, distribution, db, owners)
    per = _per(unit, base["unit"], sv)  # one dataset unit in the prior's unit
    x = [float(v) * per for v in df[time_column].tolist()]
    c = [int(v) for v in df[censor_column].tolist()] if censor_column else [0] * len(x)
    if c_invert:
        c = [1 - v for v in c]
    try:
        rows = bl.given_rows(x, c)
    except bl.BayesError as err:
        raise sv.Invalid(str(err)) from None
    try:
        model, result, _ = bl.update(base, trust, rows, None, base["priors"])
    except Exception as err:  # noqa: BLE001 - SurPyval's refusals in words
        raise sv.Invalid(f"The fit with that prior didn't work: {err}") from None
    result.update(method="bayes", interval_label=f"{bl.LEVEL:.0%} credible interval", prior_note=base["note"],
                  dataset={"id": ds.id, "name": ds.name})
    result["words"] = f"{result.get('words', '')} {base['note']}".strip()
    return model, result


def _per(unit: str, base_unit: str, sv) -> float:
    """How many of the prior's unit one data unit is: time units convert; a unit of use (cycles,
    kilometres) only matches itself."""
    from backend.services import bayes_life as bl
    from backend.units import normalize_unit

    if (normalize_unit(unit) or "") == (normalize_unit(base_unit) or ""):
        return 1.0
    try:
        return bl.time_factor(unit) / bl.time_factor(base_unit)
    except bl.BayesError:
        raise sv.Invalid(f"The data is in {unit} and the record in {base_unit or 'its own unit'}: give the data in "
                         "the record's unit, or choose a record in a unit of time.") from None


def source_text(src: dict) -> str:
    lib = src.get("library") or {}
    label = str(lib.get("label") or "").replace(": ", " ", 1)
    return f"Library: {lib.get('source')}, {label}" + (f" ({lib['citation']})" if lib.get("citation") else "")


def prior_base(prior: dict, distribution: str, db=None, owners=None) -> dict:
    """A library record as a prior: the base the update reads, {source: library, name, distribution, unit,
    params, priors, note}. ``db`` and ``owners`` let the record be one of the owners' own libraries."""
    import surpyval as sp

    from backend.services import bayes_life as bl

    sv = _sv()
    mine = mine_for(db, owners)
    rec = record(prior.get("record_id"), db, owners)
    words = why_not(rec, "prior")
    if words:
        raise sv.Invalid(words)
    b = brief(rec, mine)
    if rec.get("kind") == "life":
        return _life_prior_base(rec, b, mine, sp, bl, sv)
    mean, p05, p95 = float(b["mean"]), b.get("p05"), b.get("p95")
    dist_id = distribution if distribution in bl.DISTS else "exponential"
    params = rec.get("distribution") or {}
    family = params.get("family")
    named = {p["name"]: float(p["value"]) for p in params.get("params") or []}
    name = cite(rec)
    if dist_id == "exponential":
        if family == "gamma" and {"alpha", "beta"} <= set(named):
            priors = {"failure_rate": sp.Gamma.from_params([named["alpha"], named["beta"]])}
            note = ("The record's gamma on the failure rate is the prior exactly; with an exponential the update is "
                    "in closed form (conjugate).")
        elif p05 and p95:
            priors = {"failure_rate": sp.prior.around(mean, between=(float(p05), float(p95)))}
            note = "The record's mean rate, 90% between its 5% and 95% values, is the prior on the failure rate."
        else:
            raise sv.Invalid("That record gives no uncertainty range to use as a prior.")
        return {"source": "library", "name": name, "distribution": "exponential", "unit": "hours",
                "params": {"failure_rate": mean}, "priors": priors, "note": note}
    if not (p05 and p95):
        raise sv.Invalid("That record gives no uncertainty range to use as a prior.")
    shape = prior.get("shape") or list(DEFAULT_SHAPE)
    lo, hi = bl._f(shape[0]), bl._f(shape[1])
    if not (lo and hi and 0 < lo < hi):
        raise sv.Invalid("The shape's bounds must be low < high, both above 0.")
    shape_name = "beta" if dist_id == "weibull" else "sigma"
    priors = sp.prior.on_quantities(bl.DISTS[dist_id], mean=sp.prior.around(1 / mean, between=(1 / float(p95), 1 / float(p05))),
                                    **{shape_name: sp.prior.between(lo, hi)})
    said = "the default" if not prior.get("shape") else "as given"
    # around() puts the prior's median at the geometric middle of the bounds: say what was built.
    middle = (1 / float(p95) * 1 / float(p05)) ** 0.5
    note = (f"The record gives a failure rate; for a {bl.LABELS[dist_id]} it's a prior on the mean life (one over the "
            f"rate: 90% between {bl.num(1 / float(p95))} and {bl.num(1 / float(p05))} hours, centred on about "
            f"{bl.num(middle)}), with the {'shape' if dist_id == 'weibull' else 'spread'} between {bl.num(lo)} and "
            f"{bl.num(hi)} ({said}).")
    return {"source": "library", "name": name, "distribution": dist_id, "unit": "hours", "params": {},
            "priors": priors, "note": note}


#: The prior width (each parameter within this fraction of its value) a life record with no bounds gets.
DEFAULT_WITHIN = 0.30


def _life_prior_base(rec: dict, b: dict, mine: dict | None, sp, bl, sv) -> dict:
    """A life record (a saved model's snapshot) as the prior: in the record's own family and unit.
    With bounds on every parameter, each is "about its value, (the bounds' level) between them"
    (SurPyval's ``around``); without, each is within about 30% of its value (``from_params``), and
    the note says so."""
    d = rec["distribution"]
    family = d["family"]
    if family not in bl.DISTS:
        raise sv.Invalid(f"“{b['label']}” is a {family} model: a fit with a prior takes a Weibull, exponential or "
                         "lognormal record.")
    dist = bl.DISTS[family]
    values = {p["name"]: float(p["value"]) for p in d["params"]}
    bounds = {p["name"]: p["ci"] for p in d["params"] if p.get("ci")}
    level = float(d.get("level") or 0.9)
    unit = (rec.get("units") or {}).get("value") or "hours"
    name = cite(rec, mine)
    if all(n in bounds for n in dist.parameter_names):
        priors = {n: sp.prior.around(values[n], between=(float(bounds[n][0]), float(bounds[n][1])), mass=level)
                  for n in dist.parameter_names}
        said = ", ".join(f"{bl.WORDS.get(n, n)} {bl.num(values[n])} ({bl.num(bounds[n][0])} to {bl.num(bounds[n][1])})"
                         for n in dist.parameter_names)
        note = (f"The record's {bl.LABELS[family]} is the prior: each parameter about its value, {level:.0%} between "
                f"the record's bounds ({said}; {unit}).")
    else:
        priors = sp.prior.from_params(dist, [values[n] for n in dist.parameter_names], within=DEFAULT_WITHIN)
        said = ", ".join(f"{bl.WORDS.get(n, n)} {bl.num(values[n])}" for n in dist.parameter_names)
        note = (f"The record's {bl.LABELS[family]} is the prior ({said}; {unit}). It has no bounds, so each parameter "
                f"is taken as within about {DEFAULT_WITHIN:.0%} of its value (the default spread).")
    return {"source": "library", "name": name, "distribution": family, "unit": unit,
            "params": {n: values[n] for n in dist.parameter_names}, "priors": priors, "note": note}
