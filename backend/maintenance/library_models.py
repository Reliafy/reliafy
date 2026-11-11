"""Reliability data library records on the Modelling tab (Derryn, 9 Nov 2026: "a good way to use
models from a library. Especially the NUREG life models").

The library (backend/library) holds published component failure data: the NRC/INL 2020
industry-average parameters (failure rates per hour with a gamma uncertainty distribution, and
probabilities per demand with a beta) and handbook base rates. A record can be used two ways:

* **as a position's model** (Life model › From the data library…): a rate becomes an exponential
  model at the record's mean rate, keeping the record's gamma on that rate (``rate_uncertainty``)
  and its 5–95% range as the interval (labelled as the spread across plants from the source, not
  a fit's confidence). A rate per foot of pipe takes a length. The saved model and the link keep the record id
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


def why_not(rec: dict, use: str = "model") -> str | None:
    """Why a record can't be a model (or a prior), in words; None when it can once its covariates are
    given (the library's ``usable_as``, which the pickers search by, says the same)."""
    from backend.library import service as library_service

    if library_service.usable_as(rec, use):
        return None
    b = brief(rec)
    if rec.get("kind") == "covariate_model":
        return (f"“{b['label']}” is a handbook covariate model: its rate depends on the conditions it works in, and it "
                "gives a point rate with no spread. Attach it at a position (Life model › From the data library…, "
                "fixing its covariates there or in the RBD), or use it in a prediction.")
    if rec.get("basis") == "prediction_model":
        return (f"“{b['label']}” is a handbook rate: a point value with no spread from plant to plant, so it can't be a "
                "prior. Use it as a model (with its environment), or in a prediction.")
    return f"“{b['label']}” can't be {library_service.USES.get(use, use)}."


def record_covariates(rec: dict, covariates: dict | None = None, length_ft: float | None = None) -> dict:
    """The covariates a model or prior from ``rec`` is made with: ``covariates`` over the old
    ``length_ft`` argument (an alias)."""
    from backend.library import record_covariates as rc

    return rc.from_legacy({"length_ft": length_ft}, covariates)


def _evaluate(rec: dict, covariates: dict, time_unit: str = "hours") -> dict:
    """The one evaluator on a record's covariates, or Invalid with everything still missing."""
    from backend.library import record_covariates as rc

    try:
        return rc.evaluate(rec, covariates, time_unit)
    except rc.RecordCovariateError as exc:
        err = _sv().Invalid(" ".join(exc.problems))
        err.missing = exc.missing
        raise err from None


def covariates_of(results: dict | None) -> dict:
    """The covariates a model from the library was made with (read-time: a model saved before
    covariates kept only ``length_ft``, and the clock of the record's own): {values, words, legacy}."""
    lib = (results or {}).get("library") or {}
    if isinstance(lib.get("covariates"), dict):
        return {"values": lib["covariates"], "words": lib.get("covariates_words") or "", "legacy": False}
    vals = {}
    if lib.get("length_ft") is not None:
        vals["length_ft"] = lib["length_ft"]
    words = f"Pipe length {lib['length_ft']:g} ft" if vals else ""
    return {"values": vals, "words": words, "legacy": True}


def save_record_model(db, owner_id: str, record_id: str, name: str | None = None, owners=None,
                      length_ft: float | None = None, covariates: dict | None = None):
    """A record saved as an exponential model in the owner's models, under its covariates (a pipe's
    length, the clock and running hours, the demands a year for a probability per demand, a handbook
    part's environment and quality: backend/library/record_covariates.py). The model is the record's
    mean rate (per hour, on the clock asked for), with the record's distribution on that rate kept
    (``results.rate_uncertainty``: NRC/INL give the rate as a gamma across plants) and its 5–95% range
    as the interval, labelled as the source's spread, not a fit's confidence; the record id, its
    citation and the covariates kept. ``length_ft`` is the old name of the pipe's length. Nothing
    missing is guessed: a covariate with no value and no default is refused in words. A life record
    is saved as a model of its own family with the record's parameters and bounds. ``owners``: the
    principals whose own libraries the record may come from (the owner alone by default)."""
    from backend.library import components
    from backend.library import record_covariates as rc
    from backend.services import models as models_service

    if components.is_component_id(record_id):
        return save_component_model(db, owner_id, record_id, covariates, name), None
    mine = mine_for(db, owners if owners is not None else [owner_id])
    rec = record(record_id, db, owners if owners is not None else [owner_id])
    words = why_not(rec, "model")
    if words:
        raise _sv().Invalid(words)
    b = brief(rec, mine)
    if rec.get("kind") == "life":
        return _save_life_model(db, owner_id, rec, b, name, mine), rec
    cov = record_covariates(rec, covariates, length_ft)
    if rc.LENGTH in cov and not rc.per_foot(rec):
        raise _sv().Invalid(f"“{b['label']}” isn't a rate per foot of pipe: leave out the length.")
    made = _evaluate(rec, cov)
    used = made["covariates"]
    said = rc.words(rec, {k: v for k, v in used.items() if made["covariates_from"].get(k) == "given"})
    rate = float(made["failure_rate"])
    bounds = made.get("bounds_rate") or made.get("bounds") or {}
    lo, hi = bounds.get("p05"), bounds.get("p95")
    default = f"{b['label']} ({b['source']})"
    if rc.per_foot(rec):
        default = f"{b['label']}, {used[rc.LENGTH]:g} ft ({b['source']})"
    name = (name or default)[:200]
    notes = f"From the reliability data library: {cite(rec)}."
    if said:
        notes += f" Its covariates: {said}."
    if rc.per_foot(rec):
        notes += f" The source's rate is per foot of pipe; this model is for {used[rc.LENGTH]:g} feet."
    notes += " " + " ".join(made.get("assumptions") or [])
    model = models_service.import_model(db, owner_id, name, "exponential", unit="Hours",
                                        params=[{"name": "failure_rate", "value": rate}], notes=notes.strip())
    changes = {
        "results.method": "library",
        "results.library": {"record_id": rec["id"], "source": b.get("source"), "label": b.get("label"),
                            "citation": b.get("citation"), "units": b.get("units"), "distribution": b.get("distribution"),
                            "mean": b.get("mean"), "p05": b.get("p05"), "p95": b.get("p95"),
                            "covariates": used, "covariates_words": said, "clock": made.get("clock"),
                            **({"length_ft": used[rc.LENGTH]} if rc.per_foot(rec) else {})},
        "spec.library_record_id": rec["id"],
    }
    if lo is not None and hi is not None:
        changes["results.params.0.ci"] = [lo, hi]
        changes["results.ci_note"] = CI_NOTE
    unc = made.get("rate_uncertainty")
    if unc:
        changes["results.rate_uncertainty"] = with_source(unc, b)
    db.models.update_one({"_id": model.id}, {"$set": changes})
    return models_service.get_model(db, model.id), rec


def save_component_model(db, owner_id: str, component_id: str, covariates: dict | None, name: str | None = None,
                         binding: dict | None = None):
    """An NRC/INL component (its failure modes together) saved as an exponential at its constant rate
    over the period its covariates give (−ln R ÷ the calendar hours), the modes' 5–95% range across
    plants as the interval, the component and its covariates kept."""
    from backend.library import components
    from backend.services import models as models_service

    sv = _sv()
    try:
        comp = components.get(component_id)
        got = components.evaluate(comp, covariates or {})
    except components.ComponentNotFound as exc:
        raise sv.Invalid(str(exc)) from None
    except components.ComponentError as exc:
        err = sv.Invalid(" ".join(exc.problems))
        err.missing = exc.missing
        raise err from None
    rate = got["rate_per_calendar_hour"]
    if not rate > 0:
        raise sv.Invalid("Its rate comes out at 0 for these covariates: give some demands, running or calendar hours.")
    model = models_service.import_model(
        db, owner_id, (name or f"{comp['label']} (NRC/INL 2020)")[:200], "exponential", unit="Hours",
        params=[{"name": "failure_rate", "value": rate}],
        notes=(f"From the reliability data library: the NRC/INL 2020 component {comp['label']}, its failure modes as "
               f"competing risks. {got['words']} As a constant rate per calendar hour: −ln(R) ÷ the calendar hours. "
               "Industry averages, not this equipment's own data."))
    lib = {"component_id": comp["id"], "source": "NRC/INL 2020", "label": comp["label"],
           "citation": "INL/EXT-21-65055, Table 1 and Appendix A", "covariates": got["covariates"],
           "probability": got["probability"]}
    changes = {"results.method": "library", "spec.library_component_id": comp["id"], "results.library": lib,
               "results.params.0.ci": [got["bounds_rate"]["p05"], got["bounds_rate"]["p95"]],
               "results.ci_note": "5–95% from the modes' spread across plants (the source's), not a fit's confidence."}
    if binding:
        changes["results.covariate_binding"] = binding
    db.models.update_one({"_id": model.id}, {"$set": changes})
    return models_service.get_model(db, model.id)


#: What a library model's interval is, on the model page.
CI_NOTE = ("5–95% across plants (from the source): the record's spread of the failure rate from plant to plant, "
           "not a confidence bound from a fit.")


def with_source(unc: dict, b: dict) -> dict:
    """The rate's distribution with the record's source name and citation, for the model page's words."""
    return {**unc, "source": {**(unc.get("source") or {}), "name": b.get("source"), "citation": b.get("citation")}}


def reattach_rate_uncertainty(results: dict, spec: dict | None) -> dict | None:
    """The rate distribution of a model saved from a published NRC/INL-style rate record before
    models kept it: rebuilt from the record, scaled by the model's rate over the record's mean (so a
    length or unit already applied carries over). None when the model isn't one, already has it,
    or the record is gone. Read-only: nothing is written back."""
    if not isinstance(results, dict) or results.get("rate_uncertainty") or results.get("method") != "library":
        return None
    lib = results.get("library") or {}
    record_id = lib.get("record_id") or (spec or {}).get("library_record_id")
    if not record_id or (results.get("distribution_id") or "exponential") != "exponential":
        return None
    try:
        from backend.library import convert
        from backend.library import service as library_service

        rec = library_service.get(str(record_id))
        if rec.get("kind") != "rate":
            return None
        rate = next(float(p["value"]) for p in results.get("params") or [] if p.get("name") == "failure_rate")
        mean = convert.spread(rec)["mean"]
        if not (rate > 0 and mean and mean > 0):
            return None
        per_foot = (rec.get("units") or {}).get("value") == "per_hour_per_foot"
        feet = lib.get("length_ft") or (1.0 if per_foot else None)  # saved before lengths: for one foot
        unc = convert.rate_uncertainty(rec, rate / mean, rate, feet, results.get("unit") or "hours")
        if unc is None:
            return None
        return with_source(unc, brief(rec))
    except Exception:  # noqa: BLE001 - an unknown record or an odd old model: show it as it was
        return None


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
           replace_link_id: str | None = None, owners=None, length_ft: float | None = None,
           covariates: dict | None = None) -> dict:
    """A library record as the position's model with every covariate set: an exponential at the
    record's mean rate (per hour) under them, the record's 5–95% range as its interval (a life record:
    a model of its own family with the record's parameters); the link's source names the record, cites
    it and keeps the covariates. To fix some and set the rest in an RBD, bind it instead
    (covariate_positions.bind with source library)."""
    modes = m._mode_ids_on(position_id, failure_mode_ids)
    model, rec = save_record_model(db, owner_id, record_id, owners=owners, length_ft=length_ft, covariates=covariates)
    if rec is None:  # a component: its modes together
        return m.link_position_model(position_id, "model", model.id, "library", modes, model.name, note,
                                     {"library": dict((model.results or {}).get("library") or {})}, replace_link_id)
    b = brief(rec, mine_for(db, owners if owners is not None else [owner_id]))
    lib = (model.results or {}).get("library") or {}
    source = {"library": {"record_id": rec["id"], "source": b.get("source"), "label": b.get("label"),
                          "citation": b.get("citation"),
                          **({"covariates": lib["covariates"]} if lib.get("covariates") else {})}}
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


def fit_dataset(db, owners, dataset_id: str | None, time_column: str, censor_column: str | None, unit: str,
                prior: dict, distribution: str = "exponential", trust: str = "guide", c_invert: bool = False,
                hidden=(), content: bytes | None = None, c_map: dict | None = None, age=None):
    """Life data fitted with a prior: a saved dataset (``dataset_id``) or a table given as CSV
    (``content``: values pasted or a file, on New model), its ``time_column`` and ``censor_column``
    (0 failed, 1 still running; ``c_invert`` flips 0/1, ``c_map`` maps other values to 0 or 1).
    The prior is any but the class's history (fit_life.prior_base: a library record, a saved model,
    numbers, around a value or a B10), read the way the Explorer's "Fit a life model…" reads it.
    Returns (the SurPyval model or None, the result as the fit dialogs show it)."""
    from backend import fitting
    from backend.maintenance import fit_life
    from backend.services import bayes_life as bl
    from backend.services import datasets as datasets_service

    sv = _sv()
    if (prior or {}).get("kind") == "class":
        raise sv.Invalid("A class's history is a prior only on a position (in the Explorer); here choose a saved "
                         "model, a library record, numbers you know, a range or a B10.")
    if (prior or {}).get("kind") not in fit_life.PRIOR_KINDS:
        raise sv.Invalid(f"The prior's kind is one of {', '.join(fit_life.PRIOR_KINDS)}.")
    ds = None
    if content is not None:
        try:
            df = fitting.read_dataframe(content)
        except fitting.FitError as err:
            raise sv.Invalid(str(err)) from None
    else:
        ds = datasets_service.get_dataset(db, str(dataset_id or ""), owners)
        if ds is None:
            raise sv.NotFound(f"Dataset {dataset_id}")
        df = datasets_service.load_dataframe(ds)
    if time_column not in df.columns:
        raise sv.Invalid(f"The data has no column '{time_column}'.")
    if censor_column and censor_column not in df.columns:
        raise sv.Invalid(f"The data has no column '{censor_column}'.")
    # The prior is built in the data's unit, so the fit, its numbers and the saved model are all in it.
    prior = _typed_in_unit(dict(prior), unit, sv)
    if prior.get("kind") == "library":
        base = prior_base(prior, distribution, db, owners, to_unit=unit)
    else:
        base = fit_life.prior_base(prior, distribution, db, owners, hidden)
        if not base.get("unit"):
            base = {**base, "unit": unit}  # a prior with no unit of its own is in the data's
        if prior.get("kind") == "model":
            base = _base_in_unit(base, unit, sv)
    per = _per(unit, base["unit"], sv)  # 1 unless the data's unit isn't one of time
    times = df[time_column]
    if not all(isinstance(v, (int, float)) for v in times.dropna().tolist()) or times.isna().any():
        raise sv.Invalid(f"“{time_column}” must hold a number on every row: the time to failure or removal.")
    x = [float(v) * per for v in times.tolist()]
    c = [_flag(v, c_invert, c_map, censor_column, sv) for v in df[censor_column].tolist()] if censor_column \
        else [0] * len(x)
    try:
        rows = bl.given_rows(x, c)
    except bl.BayesError as err:
        raise sv.Invalid(str(err)) from None
    priors, extra = fit_life.prior_priors(base, trust)
    if base.get("unit_note"):
        extra = f"{extra} {base['unit_note']}".strip()
    try:
        model, result, _ = bl.update(base, trust if base["source"] != "update" else "guide", rows,
                                     float(age) * per if age else None, priors, subject="the best B10")
    except Exception as err:  # noqa: BLE001 - SurPyval's refusals in words
        raise sv.Invalid(f"The fit with that prior didn't work: {err}") from None
    result.update(method="bayes", interval_label=f"{bl.LEVEL:.0%} credible interval", prior_kind=prior.get("kind"),
                  dataset={"id": ds.id, "name": ds.name} if ds is not None else None)
    if extra:
        result["prior_note"] = extra
        result["words"] = f"{result.get('words', '')} {extra}".strip()
    return model, result


def scale_param(name: str, value, k: float):
    """A parameter in the data's unit, from one in a unit ``k`` times as long as it is short: one data unit is
    ``k`` of the prior's (days data, an hours prior: k = 24). Lives (alpha, a mean, a B10) divide by k, a rate
    multiplies, a lognormal's mu moves by log k; a shape or a spread doesn't change."""
    import math

    if value is None:
        return None
    v = float(value)
    if name in ("alpha", "mean", "B10", "b10", "value", "low", "high"):
        return v / k
    if name == "failure_rate":
        return v * k
    if name == "mu":
        return v - math.log(k)
    return v


def _typed_in_unit(prior: dict, unit: str, sv) -> dict:
    """Numbers typed for the prior (params, around, a B10) in the data's unit: converted when given in another
    unit of time; with no unit, they are the data's."""
    kind = prior.get("kind")
    if kind not in ("params", "around", "b10"):
        return prior
    given = prior.get("unit") or unit
    k = _per(unit, given, sv)
    out = {**prior, "unit": unit}
    if k == 1.0:
        return out
    if kind == "params":
        raw = prior.get("params") or []
        items = raw if isinstance(raw, list) else [{"name": n, "value": v} for n, v in raw.items()]
        out["params"] = [{"name": p.get("name"), "value": scale_param(str(p.get("name")), p.get("value"), k)} for p in items]
    elif kind == "around":
        moved = {}
        for name, spec in (prior.get("params") or {}).items():
            spec = dict(spec or {})
            if spec.get("about") is not None:
                spec["about"] = scale_param(name, spec["about"], k)
            if spec.get("between"):
                spec["between"] = sorted(scale_param(name, v, k) for v in spec["between"])
            moved[name] = spec
        out["params"] = moved
    else:
        out["b10"] = {key: scale_param(key, v, k) for key, v in (prior.get("b10") or {}).items()}
    return out


def _base_in_unit(base: dict, unit: str, sv) -> dict:
    """A saved model (or an earlier update) as the prior, in the data's unit: its numbers moved to it and the
    prior built from them (fit_life.prior_priors), and said so. In the same unit it's kept as it is."""
    k = _per(unit, base["unit"], sv)
    if k == 1.0:
        return base
    from backend.services import bayes_life as bl

    params = {n: scale_param(n, v, k) for n, v in (base.get("params") or {}).items()}
    out = {key: v for key, v in base.items() if key not in ("live", "recipe")}
    note = (f"The prior's numbers were moved from {bl._unit_word(base['unit'])} to {bl._unit_word(unit)}, the data's "
            "unit, so the result is in the data's unit.")
    return {**out, "source": "model" if base.get("source") == "update" else base.get("source"), "params": params,
            "unit": unit, "unit_note": note}


def _flag(v, c_invert: bool, c_map: dict | None, column: str, sv) -> int:
    """A status cell as 0 (failed) or 1 (still running): through ``c_map`` (keys compared as text) when
    given, else a 0/1 code, flipped by ``c_invert``."""
    if c_map:
        key = str(v).strip().lower()
        if key.endswith(".0"):
            key = key[:-2]
        for k, meaning in c_map.items():
            if str(k).strip().lower() == key:
                return int(meaning)
        raise sv.Invalid(f"“{column}” has the value “{v}”, which isn't given a meaning (failed or still running).")
    try:
        code = int(float(v))
    except (TypeError, ValueError):
        raise sv.Invalid(f"“{column}” has the value “{v}”: a status is 0 (failed) or 1 (still running).") from None
    return 1 - code if c_invert and code in (0, 1) else code


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


def prior_base(prior: dict, distribution: str, db=None, owners=None, to_unit: str | None = None) -> dict:
    """A library record as a prior: the base the update reads, {source: library, name, distribution, unit,
    params, priors, note}. ``db`` and ``owners`` let the record be one of the owners' own libraries.
    ``to_unit``: build it in this time unit (the data's) rather than the record's own, so the fit and
    its result are in the data's unit."""
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
        return _life_prior_base(rec, b, mine, sp, bl, sv, to_unit)
    from backend.library import record_covariates as rc

    cov = record_covariates(rec, prior.get("covariates"), prior.get("length_ft"))
    made = _evaluate(rec, cov)
    s_ = float(made["scale"])  # the rate (per hour, on its clock) over the record's own mean
    used = made["covariates"]
    said = rc.words(rec, {k: v for k, v in used.items() if made["covariates_from"].get(k) == "given"})
    params = rec.get("distribution") or {}
    family = params.get("family")
    named = {p["name"]: float(p["value"]) for p in params.get("params") or []}
    if rec.get("kind") == "per_demand":
        mean, p05, p95 = float(made["failure_rate"]), made["bounds_rate"]["p05"], made["bounds_rate"]["p95"]
    else:
        mean, p05, p95 = float(made["failure_rate"]), made["bounds"]["p05"], made["bounds"]["p95"]
    clock = made.get("clock") or "calendar"
    per = "per calendar hour" if clock == "calendar" else "per hour of running"
    cov_note = (f" Its covariates: {said}, so the rate is {bl.num(mean)} {per} (the record's × {bl.num(s_)})."
                if said and abs(s_ - 1) > 1e-12 else (f" Its covariates: {said}." if said else ""))
    # In the data's unit: a rate per hour times the hours in one data unit is the rate per data unit.
    unit_out, k = "hours", 1.0
    if to_unit:
        k = _per(to_unit, "hours", sv)
        unit_out = to_unit
        mean, p05, p95 = mean * k, (float(p05) * k if p05 else p05), (float(p95) * k if p95 else p95)
    u_word = "hours" if unit_out == "hours" else unit_out
    dist_id = distribution if distribution in bl.DISTS else "exponential"
    name = cite(rec)
    extra = {"covariates": used, "covariates_words": said, "clock": clock}
    if dist_id == "exponential":
        if family == "gamma" and {"alpha", "beta"} <= set(named) and rec.get("kind") == "rate":
            # A gamma(α, β) on λ is a gamma(α, β / s) on s × λ: the record's prior, scaled exactly.
            priors = {"failure_rate": sp.Gamma.from_params([named["alpha"], named["beta"] / (s_ * k)])}
            note = ("The record's gamma on the failure rate is the prior exactly; with an exponential the update is "
                    "in closed form (conjugate).") + cov_note
        elif p05 and p95:
            priors = {"failure_rate": sp.prior.around(mean, between=(float(p05), float(p95)))}
            note = ("The record's mean rate, 90% between its 5% and 95% values, is the prior on the failure rate."
                    + cov_note)
        else:
            raise sv.Invalid("That record gives no uncertainty range to use as a prior.")
        return {"source": "library", "name": name, "distribution": "exponential", "unit": unit_out,
                "params": {"failure_rate": mean}, "priors": priors, "note": note, **extra}
    if not (p05 and p95):
        raise sv.Invalid("That record gives no uncertainty range to use as a prior.")
    shape = prior.get("shape") or list(DEFAULT_SHAPE)
    lo, hi = bl._f(shape[0]), bl._f(shape[1])
    if not (lo and hi and 0 < lo < hi):
        raise sv.Invalid("The shape's bounds must be low < high, both above 0.")
    shape_name = "beta" if dist_id == "weibull" else "sigma"
    priors = sp.prior.on_quantities(bl.DISTS[dist_id], mean=sp.prior.around(1 / mean, between=(1 / float(p95), 1 / float(p05))),
                                    **{shape_name: sp.prior.between(lo, hi)})
    said_shape = "the default" if not prior.get("shape") else "as given"
    # around() puts the prior's median at the geometric middle of the bounds: say what was built.
    middle = (1 / float(p95) * 1 / float(p05)) ** 0.5
    note = (f"The record gives a failure rate; for a {bl.LABELS[dist_id]} it's a prior on the mean life (one over the "
            f"rate: 90% between {bl.num(1 / float(p95))} and {bl.num(1 / float(p05))} {u_word}, centred on about "
            f"{bl.num(middle)}), with the {'shape' if dist_id == 'weibull' else 'spread'} between {bl.num(lo)} and "
            f"{bl.num(hi)} ({said_shape}).") + cov_note
    return {"source": "library", "name": name, "distribution": dist_id, "unit": unit_out, "params": {},
            "priors": priors, "note": note, **extra}


#: The prior width (each parameter within this fraction of its value) a life record with no bounds gets.
DEFAULT_WITHIN = 0.30


def _life_prior_base(rec: dict, b: dict, mine: dict | None, sp, bl, sv, to_unit: str | None = None) -> dict:
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
    if to_unit:
        # In the data's unit: each parameter (and its bounds) moved to it.
        k = _per(to_unit, unit, sv)
        if k != 1.0:
            values = {n: scale_param(n, v, k) for n, v in values.items()}
            bounds = {n: sorted(scale_param(n, float(v), k) for v in ci) for n, ci in bounds.items()}
            unit = to_unit
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
