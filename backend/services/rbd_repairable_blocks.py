"""Repairable-and-replaceable RBD blocks: a fitted repairable model as a block,
with a rule for when the unit is replaced with a new one.

A block in a repairable diagram can take a model fitted on Models › Repairable
(Crow-AMSAA, Duane, Cox-Lewis, HPP, ARA, ARI, G1, generalised renewal) as
how it fails between replacements. RePyability (0.17+) takes surpyval's fitted
repairable models as a component's ``"reliability"``: a Poisson process is
minimal repair of the life whose cumulative hazard is its cumulative
intensity, a renewal process repairs the unit by its own rule.

A unit that gets worse with every repair and is never replaced drives the
system's availability to zero, so such a block also needs a **replacement
rule**: replace it with a new one at an age, or after a number of repairs.
The rule is required unless the model, with its parameters as they are,
provably never wears out (its failure rate can't rise at any age):

* constant rate (HPP): always;
* Crow-AMSAA / Duane: shape β ≤ 1;
* Cox-Lewis: trend b ≤ 0;
* ARA / ARI / generalised renewal: the underlying life (or ARI's baseline
  intensity) never rises: exponential, or Weibull shape ≤ 1;
* G1: the same, and its gaps between failures don't shrink (q ≥ 0): a G1
  process whose gaps shrink wears out whatever its first life.

Graph format::

    node.data["model"] = {"kind": "repairable", "source": "saved" | "params",
                          "modelId": "<saved repairable model id>",   # saved
                          "name": "Feed pump repairs",
                          "form": "crow_amsaa" | "duane" | "cox_lewis" | "hpp"
                                  | "ara" | "ari" | "g1" | "grp_i" | "grp_ii",
                          "params": [{"name": "alpha", "value": 1200}, ...],
                          "options": {"m": 2, "baseline": "crow_amsaa"},   # ara / ari
                          "unit": "hour"}
    node.data["replacement"] = {"rule": "none" | "age" | "repairs",
                                "age": 8000,         # rule age: replaced at this age
                                "repairs": 3,        # rule repairs: replaced at the
                                                     #   next failure after 3 repairs
                                "duration": 8,       # age: time a planned replacement takes
                                "cost": 4000,        # age: what a planned replacement costs
                                "suggested": true}   # the optimiser's rule, untouched

How each figure is worked out follows RePyability's own
``analysis_routes()``: exact or numerical figures are free, simulated ones
are Pro. Since RePyability 0.19 a minimally repaired block (Crow-AMSAA,
Duane, Cox-Lewis) with a replacement rule has exact long-run values (each
replacement ends a renewal cycle; Cox-Lewis by quadrature, "numerical"), so
it is free; a block repaired imperfectly (ARA, ARI, G1, generalised renewal)
is still simulated. The route (and the price) follows RePyability with no
change here.
"""

from __future__ import annotations

import math
from typing import Any, Optional

import numpy as np

from backend.errors import client_message
from backend.services.rbd_analysis import AnalysisError

KIND = "repairable"
KEY = "replacement"
RULES = ("none", "age", "repairs")
MAX_REPAIRS = 999
PREFIX = "repairable:"  # a resolver id for a saved repairable model (models_service)

POISSON_FORMS = ("crow_amsaa", "duane", "cox_lewis", "hpp")
RENEWAL_FORMS = ("ara", "ari", "g1", "grp_i", "grp_ii")
FORMS = POISSON_FORMS + RENEWAL_FORMS
NAMES = {
    "crow_amsaa": "Crow-AMSAA", "duane": "Duane", "cox_lewis": "Cox-Lewis", "hpp": "Constant rate (HPP)",
    "ara": "ARA", "ari": "ARI", "g1": "G1 renewal", "grp_i": "Generalised renewal (Kijima I)",
    "grp_ii": "Generalised renewal (Kijima II)",
}
#: Each form's parameters, in surpyval's order.
PARAMS = {
    "crow_amsaa": ["alpha", "beta"], "duane": ["alpha", "b"], "cox_lewis": ["alpha", "beta"], "hpp": ["lambda"],
    "ara": ["rho", "alpha", "beta"], "g1": ["q", "alpha", "beta"],
    "grp_i": ["q", "alpha", "beta"], "grp_ii": ["q", "alpha", "beta"],
}
#: ARI's parameters by its baseline intensity.
ARI_PARAMS = {"crow_amsaa": ["rho", "alpha", "beta"], "duane": ["rho", "alpha", "b"],
              "cox_lewis": ["rho", "alpha", "beta"]}
BASELINES = ("crow_amsaa", "duane", "cox_lewis")

#: The suggested rule's simulation (renewal models): seeded, so it repeats.
SUGGEST_SEED = 1
SUGGEST_SAMPLES = 500
SUGGEST_MAX_FAILURES = 30


def is_repairable(model) -> bool:
    """Whether a block's model is a repairable model (this module's kind)."""
    return isinstance(model, dict) and model.get("kind") == KIND


def block_has(data: dict) -> bool:
    return is_repairable((data or {}).get("model"))


# ---------------------------------------------------------------------------
# The model
# ---------------------------------------------------------------------------

def _poisson_kind(model) -> Optional[str]:
    """The form of a surpyval Poisson process, or None."""
    name = getattr(getattr(model, "dist", None), "name", None)
    return {"Crow-AMSAA": "crow_amsaa", "Duane": "duane", "Cox-Lewis": "cox_lewis",
            "Homogeneous Poisson Process": "hpp"}.get(name)


def form_of(process) -> Optional[str]:
    """The form of a live surpyval repairable model, or None for one a block
    can't take (a regression on covariates, say)."""
    kind = _poisson_kind(process)
    if kind:
        return kind
    if type(process).__name__ != "RenewalModel":
        return None
    k = str(getattr(process, "kind", ""))  # surpyval's: "ARA Renewal", "ARI Recurrence", "G1 Renewal", ...
    if k.startswith("ARA"):
        return "ara"
    if k.startswith("ARI"):
        return "ari"
    if k.startswith("G1"):
        return "g1"
    if k == "Generalized Renewal":
        return "grp_ii" if str(getattr(process, "kijima_type", "i")) == "ii" else "grp_i"
    return None


def describe_process(process) -> dict:
    """``{form, params, options}`` of a live repairable model: what the block
    stores, the export writes and the pane shows."""
    form = form_of(process)
    if form is None:
        raise AnalysisError("This repairable model can't be a block: its failure rate depends on covariates or "
                            "a cause. Fit Crow-AMSAA, Duane, Cox-Lewis, HPP, ARA, ARI, G1 or a generalised renewal "
                            "model instead.")
    values = [float(v) for v in np.asarray(process.params, dtype=float).ravel()]
    names = list(getattr(process, "parameter_names", None) or PARAMS.get(form) or [])
    options: dict = {}
    if form in ("ara", "ari"):
        m = getattr(process, "m", 1)
        options["m"] = "all" if (isinstance(m, float) and not math.isfinite(m)) else int(m)
    if form == "ari":
        options["baseline"] = _poisson_kind(process.model) or "crow_amsaa"
    if form in ("ara", "g1", "grp_i", "grp_ii"):
        life = getattr(getattr(process, "model", None), "dist", None)
        life_name = getattr(life, "name", "Weibull")
        if life_name != "Weibull":
            options["life"] = str(life_name)
    return {"form": form, "params": [{"name": n, "value": v} for n, v in zip(names, values)], "options": options}


def _values(model: dict, names: list, where: str) -> list:
    given = {str(p.get("name")): p.get("value") for p in model.get("params") or [] if isinstance(p, dict)}
    missing = [n for n in names if n not in given]
    if missing:
        raise AnalysisError(f"{where}: its repairable model needs {', '.join(names)} (missing {', '.join(missing)}).")
    out = []
    for n in names:
        v = given[n]
        if isinstance(v, bool):
            v = None
        try:
            x = float(v)
        except (TypeError, ValueError):
            x = float("nan")
        if not math.isfinite(x):
            raise AnalysisError(f"{where}: its repairable model's {n} must be a number.")
        out.append(x)
    return out


def build_from_params(model: dict, where: str):
    """A surpyval repairable model from a block's stored form and parameters."""
    import surpyval as sp
    from surpyval import recurrent as rec

    form = model.get("form")
    if form not in FORMS:
        raise AnalysisError(f"{where}: its repairable model must be one of {', '.join(FORMS)} (got {form!r}).")
    opts = model.get("options") or {}
    try:
        if form in POISSON_FORMS:
            fitter = {"crow_amsaa": rec.CrowAMSAA, "duane": rec.Duane, "cox_lewis": rec.CoxLewis, "hpp": rec.HPP}[form]
            return fitter.from_params(_values(model, PARAMS[form], where))
        m = opts.get("m", 1)
        m = float("inf") if m == "all" else int(m or 1)
        if form == "ari":
            baseline = opts.get("baseline") or "crow_amsaa"
            if baseline not in BASELINES:
                raise AnalysisError(f"{where}: ARI's baseline must be one of {', '.join(BASELINES)}.")
            rho, *base = _values(model, ARI_PARAMS[baseline], where)
            fitter = {"crow_amsaa": rec.CrowAMSAA, "duane": rec.Duane, "cox_lewis": rec.CoxLewis}[baseline]
            return rec.ARI.fit_from_parameters(base, rho, m=m, baseline=fitter)
        restoration, *life = _values(model, PARAMS[form], where)
        if form == "ara":
            return rec.ARA.fit_from_parameters(life, restoration, m=m, dist=sp.Weibull)
        if form == "g1":
            return rec.GeneralizedOneRenewal.fit_from_parameters(life, restoration, dist=sp.Weibull)
        kijima = "ii" if form == "grp_ii" else "i"
        return rec.GeneralizedRenewal.fit_from_parameters(life, restoration, kijima=kijima, dist=sp.Weibull)
    except AnalysisError:
        raise
    except Exception as exc:  # noqa: BLE001 - surpyval validates the parameters
        raise AnalysisError(f"{where}: its repairable model can't be built: {client_message(exc)}") from None


def build(model: dict, where: str, resolve_model=None):
    """The block's live surpyval repairable model: the saved fit (resolved in
    the caller's scope) or one built from the stored parameters."""
    if not is_repairable(model):
        raise AnalysisError(f"{where} has no repairable model.")
    model_id = model.get("modelId") or model.get("model_id")
    if model.get("source") == "saved" and model_id:
        if resolve_model is None:
            return build_from_params(model, where)
        entry = resolve_model(PREFIX + str(model_id))
        live = (entry or {}).get("model") if isinstance(entry, dict) else None
        if live is None:
            raise AnalysisError(f"{where}: its saved repairable model “{model.get('name') or model_id}” wasn't "
                                "found. Pick another model, or enter its parameters.")
        if form_of(live) is None:
            describe_process(live)  # raises the plain message
        return live
    return build_from_params(model, where)


def saved_entry(model: dict, resolve_model) -> Optional[dict]:
    """The resolver's entry for a block's saved repairable model (its live fit
    and saved results), or None."""
    model_id = model.get("modelId") or model.get("model_id") if isinstance(model, dict) else None
    if not model_id or resolve_model is None or model.get("source") != "saved":
        return None
    try:
        entry = resolve_model(PREFIX + str(model_id))
    except Exception:  # noqa: BLE001 - an unresolvable model has no saved intervals
        return None
    return entry if isinstance(entry, dict) else None


def persisted(saved_doc, where: str) -> dict:
    """The block's stored model for a saved repairable model doc (the graph
    normaliser's and the picker's shape)."""
    r = saved_doc.results or {}
    if r.get("family") == "regression":
        raise AnalysisError(f"{where}: “{saved_doc.name}” is a proportional-intensity model: its failure rate "
                            "depends on covariates, which an RBD block can't take. Pick a model without covariates.")
    form = (saved_doc.spec or {}).get("model_id") or (r.get("model") or {}).get("id") or "crow_amsaa"
    out = {"kind": KIND, "source": "saved", "modelId": saved_doc.id, "name": saved_doc.name, "form": form,
           "params": [{"name": p.get("name"), "value": p.get("value")} for p in r.get("params") or []
                      if isinstance(p, dict)],
           "unit": r.get("unit") or ""}
    opts = (saved_doc.spec or {}).get("options") or {}
    keep = {k: opts[k] for k in ("m", "baseline") if opts.get(k) not in (None, "")}
    if keep:
        out["options"] = keep
    return out


# ---------------------------------------------------------------------------
# Does it wear out?
# ---------------------------------------------------------------------------

_EPS = 1e-12


def _fmt(x: float) -> str:
    return f"{x:.3g}"


def _poisson_verdict(form: str, params) -> tuple[bool, str]:
    p = [float(v) for v in np.asarray(params, dtype=float).ravel()]
    if form == "hpp":
        return True, "constant rate"
    if form == "crow_amsaa":
        return p[1] <= 1.0 + _EPS, f"Crow-AMSAA, shape {_fmt(p[1])}"
    if form == "duane":
        return p[0] <= 1.0 + _EPS, f"Duane, shape {_fmt(p[0])}"
    return p[1] <= _EPS, f"Cox-Lewis, trend {_fmt(p[1])}"


def _life_verdict(life) -> tuple[bool, str]:
    name = getattr(getattr(life, "dist", None), "name", None)
    params = [float(v) for v in np.asarray(getattr(life, "params", []), dtype=float).ravel()]
    if name == "Exponential":
        return True, "exponential life"
    if name == "Weibull" and len(params) == 2:
        return params[1] <= 1.0 + _EPS, f"Weibull life, shape {_fmt(params[1])}"
    return False, f"{name or 'its'} life"


def wear_verdict(process) -> dict:
    """Whether the model, with its parameters as they are, never wears out:
    ``{never_wears_out, basis, text}``. ``text`` says which applied, in words."""
    form = form_of(process)
    if form in POISSON_FORMS:
        never, basis = _poisson_verdict(form, process.params)
    elif form in RENEWAL_FORMS:
        inner = getattr(process, "model", None)
        inner_form = _poisson_kind(inner)
        if inner_form:  # ARI: its baseline intensity
            never, basis = _poisson_verdict(inner_form, inner.params)
            basis = f"{NAMES[form]} on {basis}"
        else:
            never, basis = _life_verdict(inner)
            basis = f"{NAMES[form]}, {basis}"
        if form == "g1":
            q = float(getattr(process, "restoration", 0.0))
            if q < -_EPS:
                never = False
                basis += f", gaps shrinking (q {_fmt(q)})"
    else:
        never, basis = False, "a form whose rate can rise"
    if never:
        text = f"No replacement needed: this model's failure rate never rises ({basis})."
    else:
        text = f"Replacement needed: this model's failure rate rises with age ({basis})."
    return {"never_wears_out": bool(never), "basis": basis, "text": text}


#: The saved interval's parameter that decides wear-out, and the line, by form
#: (and ARI's baseline); ``"q"`` for G1 is checked the other way (below 0).
def _deciding(form: str, options: dict) -> list[tuple[str, float, str]]:
    if form == "crow_amsaa":
        return [("beta", 1.0, "above")]
    if form == "duane":
        return [("alpha", 1.0, "above")]
    if form == "cox_lewis":
        return [("beta", 0.0, "above")]
    if form == "ari":
        base = (options or {}).get("baseline") or "crow_amsaa"
        return _deciding(base, {})
    if form in ("ara", "grp_i", "grp_ii"):
        return [("beta", 1.0, "above")]
    if form == "g1":
        return [("beta", 1.0, "above"), ("q", 0.0, "below")]
    return []


def band_crosses(model: dict, entry: Optional[dict]) -> Optional[str]:
    """For a block with no replacement rule: whether its saved fit's 90%
    parameter interval reaches into wear-out, so some of the uncertainty
    draws would wear out and never be replaced. The parameter that does, in
    words, or None."""
    r = (entry or {}).get("results") or {}
    form = model.get("form")
    cis = {str(p.get("name")): p.get("ci") for p in r.get("params") or [] if isinstance(p, dict)}
    for name, line, side in _deciding(form, model.get("options") or {}):
        ci = cis.get(name)
        if not (isinstance(ci, (list, tuple)) and len(ci) == 2):
            continue
        try:
            lo, hi = float(ci[0]), float(ci[1])
        except (TypeError, ValueError):
            continue
        if side == "above" and hi > line + _EPS:
            return f"its {name} could be up to {_fmt(hi)} (90% interval), past {_fmt(line)}"
        if side == "below" and lo < line - _EPS:
            return f"its {name} could be as low as {_fmt(lo)} (90% interval), below {_fmt(line)}"
    return None


# ---------------------------------------------------------------------------
# The replacement rule
# ---------------------------------------------------------------------------

def _num(value, what: str, label: str, *, positive: bool = False, integer: bool = False):
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, bool):
        raise AnalysisError(f"“{label}”: the {what} must be a number.")
    try:
        x = float(value)
    except (TypeError, ValueError):
        raise AnalysisError(f"“{label}”: the {what} must be a number.") from None
    if not math.isfinite(x) or x < 0 or (positive and x == 0):
        raise AnalysisError(f"“{label}”: the {what} must be {'above 0' if positive else '0 or more'}.")
    if integer:
        if x != int(x):
            raise AnalysisError(f"“{label}”: the {what} must be a whole number.")
        return int(x)
    return x


def parse_rule(data: dict, label: str) -> dict:
    """The block's replacement rule, checked: ``{"rule": "none"}``,
    ``{"rule": "age", "age", "duration"?, "cost"?}`` or
    ``{"rule": "repairs", "repairs"}`` (plus ``suggested``)."""
    raw = data.get(KEY)
    if raw in (None, "", {}):
        return {"rule": "none"}
    if not isinstance(raw, dict):
        raise AnalysisError(f"“{label}”: its replacement rule must be an object of rule, age or repairs.")
    unknown = set(raw) - {"rule", "age", "repairs", "duration", "cost", "suggested"}
    if unknown:
        raise AnalysisError(f"“{label}”: unknown replacement setting(s) {', '.join(sorted(map(str, unknown)))} — "
                            "use rule, age, repairs, duration and cost.")
    rule = raw.get("rule") or "none"
    if rule not in RULES:
        raise AnalysisError(f"“{label}”: the replacement rule must be none, age or repairs (got {rule!r}).")
    out: dict = {"rule": rule}
    if raw.get("suggested"):
        out["suggested"] = True
    if rule == "age":
        age = _num(raw.get("age"), "replacement age", label, positive=True)
        if age is None:
            raise AnalysisError(f"“{label}”: replacing at an age needs the age.")
        out["age"] = age
        for key, what in (("duration", "planned replacement time"), ("cost", "planned replacement cost")):
            v = _num(raw.get(key), what, label)
            if v is not None:
                out[key] = v
    elif rule == "repairs":
        n = _num(raw.get("repairs"), "number of repairs", label, integer=True)
        if n is None:
            raise AnalysisError(f"“{label}”: replacing after repairs needs the number of repairs.")
        if n > MAX_REPAIRS:
            raise AnalysisError(f"“{label}”: the number of repairs before replacement is at most {MAX_REPAIRS}.")
        out["repairs"] = n
    return out


def rule_words(rule: dict, unit: str = "") -> str:
    """"Replace at age 8,000 h", "Replace after 3 repairs", "No replacement"."""
    from backend.units import unit_in_text, with_unit

    if rule.get("rule") == "age":
        return "Replace at age " + with_unit(f"{rule['age']:,.6g}", unit_in_text(unit))
    if rule.get("rule") == "repairs":
        n = rule["repairs"]
        return "Replace at every failure" if n == 0 else f"Replace after {n} repair{'' if n == 1 else 's'}"
    return "No replacement"


def check(data: dict, label: str, ntype: str = "component", repairable: bool = True, process=None) -> list[str]:
    """What stops a block on a repairable model (the Validate step's errors,
    and what calculation refuses). Empty when it's fine. ``process`` (the live
    model) adds the wear-out rule; without it only the settings are checked."""
    if not block_has(data):
        if data.get(KEY) not in (None, "", {}):
            return [f"“{label}”: a replacement rule goes with a repairable model — pick one for the block, or "
                    "clear the rule."]
        return []
    if not repairable:
        return [f"“{label}”: a repairable model (how a unit fails between replacements) needs a repairable "
                "diagram — switch the diagram to availability, or pick a non-repairable model."]
    if ntype != "component":
        return [f"“{label}”: a repairable model goes on a single block, not a {ntype} group."]
    out = []
    if (data.get("repair_quality") or {}).get("model", "perfect") not in ("perfect", None):
        out.append(f"“{label}”: a repairable model brings its own repairs — clear the block's repair quality.")
    try:
        rule = parse_rule(data, label)
    except AnalysisError as exc:
        return out + [client_message(exc)]
    if rule["rule"] == "age" and (data.get("preventive") or data.get("inspection")):
        out.append(f"“{label}”: it's replaced at an age by its replacement rule — clear its scheduled maintenance "
                   "or proof tests in the Maintenance plan.")
    if rule["rule"] == "repairs" and (data.get("preventive") or {}).get("policy") == "condition":
        out.append(f"“{label}”: a block replaced on condition can't also be replaced after a number of repairs.")
    if process is not None:
        form = form_of(process)
        verdict = wear_verdict(process)
        if form == "hpp" and rule["rule"] != "none":
            out.append(f"“{label}”: a constant-rate model never wears out, so it needs no replacement rule — "
                       "clear the rule.")
        elif rule["rule"] == "none" and not verdict["never_wears_out"] and not (
                data.get("preventive") or {}).get("policy") in ("age", "block"):
            out.append(missing_rule_message(label, verdict))
    return out


def validation_errors(graph: dict) -> list[str]:
    """The Validate step's problems with a repairable diagram's blocks on
    repairable models (and stray replacement rules), read from the stored
    parameters (calculation re-checks them on the saved fit)."""
    out: list[str] = []
    for node in graph.get("nodes") or []:
        ntype = node.get("type")
        data = node.get("data") or {}
        if ntype in ("input", "output", "knode") or not (block_has(data) or data.get(KEY)):
            continue
        label = data.get("label") or node.get("id")
        process = None
        model = data.get("model") or {}
        if block_has(data) and ntype == "component" and (model.get("form") or model.get("source") != "saved"):
            try:
                process = build_from_params(data["model"], f"“{label}”")
            except AnalysisError as exc:
                out.append(client_message(exc))
                continue
        out.extend(check(data, label, ntype or "component", bool(graph.get("repairable")), process))
    return out


def missing_rule_message(label: str, verdict: dict) -> str:
    return (f"“{label}”: replacement needed — this model's failure rate rises with age ({verdict['basis']}), so "
            "if it's never replaced it wears out and its availability falls towards zero. Add a replacement rule "
            "(at an age, or after a number of repairs), or use Find the best replacement rule.")


def spec_entries(data: dict, label: str, resolve_model=None) -> tuple[dict, Optional[dict]]:
    """``(spec keys, preventive data)`` for the block's rule: RePyability's
    ``replace_after`` for "after N repairs" (the (N+1)-th failure since it was
    renewed), or the block's age replacement as ``preventive`` data for
    :func:`rbd_maintenance.preventive_spec` to check and build."""
    rule = parse_rule(data, label)
    if rule["rule"] == "repairs":
        return {"replace_after": rule["repairs"] + 1}, None
    if rule["rule"] == "age":
        pm: dict = {"policy": "age", "interval": rule["age"]}
        if "duration" in rule:
            pm["duration"] = rule["duration"]
        cost = rule.get("cost")
        if cost is None:
            cost = (data.get("costs") or {}).get("replace")
        if cost is not None:
            pm["cost"] = cost
        return {}, pm
    return {}, None


def first_life_mean(model: dict) -> Optional[float]:
    """The mean time to a new unit's first failure, from the block's stored
    parameters (RePyability's own translation of the model into a life), or
    None."""
    try:
        from repyability.rbd import _processes

        process = build_from_params(model, "the block")
        life = (_processes.first_life(process) if form_of(process) in RENEWAL_FORMS
                else _processes.as_spec("u", {"reliability": process})["reliability"])
        mean = float(np.ravel(life.mean())[0])
    except Exception:  # noqa: BLE001 - only sizes a window
        return None
    return mean if math.isfinite(mean) and mean > 0 else None


def settling_time(data: dict, mttr: Optional[float]) -> Optional[float]:
    """How long a block on a repairable model takes to settle, roughly: one
    replacement cycle (to its replacement age, or about N + 1 lives for N
    repairs), plus a repair; a single life when it's never replaced."""
    life = first_life_mean(data.get("model") or {})
    if life is None:
        return None
    try:
        rule = parse_rule(data, "the block")
    except AnalysisError:
        rule = {"rule": "none"}
    cycle = rule["age"] if rule["rule"] == "age" else life * (rule.get("repairs", 0) + 1)
    return cycle + (mttr or 0.0)


# ---------------------------------------------------------------------------
# The block on its own: the pane's summary, the suggested rule and the route
# ---------------------------------------------------------------------------

def _single_rbd(spec):
    from repyability.rbd.repairable_rbd import RepairableRBD

    return RepairableRBD([("input", "u"), ("u", "output")], {"u": spec}, input_node="input", output_node="output")


ROUTE_WORDS = {
    "exact": "worked out exactly",
    "numerical": "worked out numerically",
    "simulated": "simulated",
}


def block_route(spec) -> dict:
    """How this block's long-run availability is worked out, read from
    RePyability's ``analysis_routes()`` (never by model family): exact or
    numerical → free, otherwise simulated → Pro."""
    rbd = _single_rbd(spec)
    routes = rbd.analysis_routes()
    long_run = routes.get("mean_availability")
    route = getattr(long_run, "route", None) or "refused"
    if route in ("exact", "numerical"):
        return {"route": route, "price": "free", "words": ROUTE_WORDS[route].capitalize() + " · Free"}
    sim = routes.get("availability")
    reason = getattr(long_run, "reason", None) or ""
    if getattr(sim, "route", None) == "simulated":
        return {"route": "simulated", "price": "pro", "words": "Simulated · Pro", "reason": reason}
    return {"route": "refused", "price": None, "words": "Can't be worked out", "reason": reason}


def suggest(process, data: dict, label: str) -> dict:
    """The best replacement rule for the block's costs: RePyability's
    ``Repairable.optimal_overhaul_policy`` (best age, Barlow-Hunter: repairs
    take no time) for a Poisson process, and ``optimal_failure_limit_policy``
    (best number of repairs, simulated with a fixed seed) for a renewal
    process. ``{"available": False, "reason"}`` when there's nothing to find
    or the costs aren't set."""
    import warnings

    from repyability import Repairable

    form = form_of(process)
    verdict = wear_verdict(process)
    if verdict["never_wears_out"]:
        return {"available": False, "reason": verdict["text"]}
    costs = data.get("costs") or {}

    def plain(v):
        if isinstance(v, dict):  # a range: its mean, as the exact cost rate takes it
            try:
                return (float(v.get("min")) + float(v.get("max"))) / 2.0
            except (TypeError, ValueError):
                return None
        try:
            x = float(v)
        except (TypeError, ValueError):
            return None
        return x if math.isfinite(x) else None

    cr, creplace = plain(costs.get("repair")), plain(costs.get("replace"))
    planned = plain(((data.get(KEY) or {}) if isinstance(data.get(KEY), dict) else {}).get("cost"))
    if not cr or not creplace or cr <= 0 or creplace <= 0:
        return {"available": False,
                "reason": "Set the block's repair cost and replacement cost (Costs) to find the best replacement rule."}
    try:
        with warnings.catch_warnings(), np.errstate(all="ignore"):
            warnings.simplefilter("ignore")
            if form in POISSON_FORMS:
                co = planned if planned and planned > cr else creplace
                if co <= cr:
                    return {"available": False,
                            "reason": "A replacement must cost more than a repair to find the best replacement age."}
                unit = Repairable(process)
                unit.set_repair_and_overhaul_costs(cr, co)
                policy = unit.optimal_overhaul_policy()
                age = float(policy.interval)
                if not math.isfinite(age) or age <= 0:
                    return {"available": False, "reason": "Replacing never pays for this model at these costs."}
                return {"available": True, "rule": {"rule": "age", "age": float(f"{age:.4g}"), "suggested": True},
                        "cost_rate": float(policy.cost_rate), "basis": "age",
                        "note": "best cost; repairs assumed instant"}
            unit = Repairable(process)
            # RePyability's diagram charges a replacement its repair and replacement costs.
            unit.set_repair_and_overhaul_costs(cr, cr + creplace)
            policy = unit.optimal_failure_limit_policy(seed=SUGGEST_SEED, mc_samples=SUGGEST_SAMPLES,
                                                       max_failures=SUGGEST_MAX_FAILURES)
            n = int(policy.failure_count)
            return {"available": True, "rule": {"rule": "repairs", "repairs": max(n - 1, 0), "suggested": True},
                    "cost_rate": float(policy.cost_rate), "basis": "repairs", "note": "best cost"}
    except Exception as exc:  # noqa: BLE001 - the optimiser's own reason
        return {"available": False, "reason": f"The best rule couldn't be found: {client_message(exc)}"}


def suggestion_words(s: dict, unit: str = "") -> Optional[str]:
    if not s.get("available"):
        return None
    return f"Suggested: {rule_words(s['rule'], unit)[0].lower()}{rule_words(s['rule'], unit)[1:]} ({s['note']})"


def block_summary(node: dict, resolve_model=None, unit: str = "", repairable: bool = True,
                  want_suggestion: bool = True) -> dict:
    """What the pane's "Repairs and replacement" section shows for a block:
    the model in words, the wear-out verdict, the rule, the suggested rule
    and how its long-run availability is worked out (exact/simulated, Free/
    Pro). Raises :class:`AnalysisError` (user-facing)."""
    from backend.services import rbd_maintenance
    from backend.services.rbd_analysis import _repair_distribution

    if not isinstance(node, dict):
        raise AnalysisError("Send the block as the builder stores it.")
    data = node.get("data") or {}
    label = data.get("label") or node.get("id") or "The block"
    model = data.get("model")
    if not is_repairable(model):
        raise AnalysisError(f"“{label}” has no repairable model.")
    process = build(model, f"“{label}”", resolve_model)
    described = describe_process(process)
    verdict = wear_verdict(process)
    problems = check(data, label, node.get("type") or "component", repairable, process)
    try:
        rule = parse_rule(data, label)
    except AnalysisError:
        rule = {"rule": "none"}
    out: dict = {
        "label": label,
        "model": {"name": model.get("name") or NAMES.get(described["form"]), "form": described["form"],
                  "form_name": NAMES.get(described["form"]), "params": described["params"],
                  "options": described["options"], "source": model.get("source")},
        "verdict": verdict,
        "rule_required": not verdict["never_wears_out"],
        "rule_offered": described["form"] != "hpp",
        "rule": rule,
        "rule_words": rule_words(rule, unit),
        "problems": problems,
    }
    if rule["rule"] == "none" and verdict["never_wears_out"]:
        crosses = band_crosses(model, saved_entry(model, resolve_model))
        if crosses:
            out["band_note"] = band_refusal(label, crosses)
    if want_suggestion and out["rule_offered"]:
        s = suggest(process, data, label)
        out["suggestion"] = {**s, **({"words": suggestion_words(s, unit)} if s.get("available") else {})}
    if not problems:
        try:
            repair = "instant" if data.get("instant_repair") else _repair_distribution(data, label, resolve_model)
            spec: dict[str, Any] = {"reliability": process, "repairability": repair}
            extra, pm = spec_entries(data, label, resolve_model)
            spec.update(extra)
            if pm:
                spec["preventive"] = rbd_maintenance.preventive_spec({**data, "preventive": pm}, label, resolve_model)
            out["route"] = block_route(spec)
        except AnalysisError as exc:
            out["route"] = None
            out["problems"] = [client_message(exc)]
        except Exception as exc:  # noqa: BLE001 - RePyability's reason, worded for a user
            out["route"] = None
            out["problems"] = [f"“{label}”: {client_message(exc)}"]
    return out


def band_refusal(label: str, crosses: str) -> str:
    return (f"No long-run band for “{label}”: it has no replacement rule, and {crosses}, where its failure rate "
            "would rise — those draws would wear out and never be replaced. The point answer and the bands over a "
            "set period still work; or add a replacement rule.")


def long_run_band_refusal(graph: dict, resolve_model) -> Optional[str]:
    """Why a diagram's long-run uncertainty band is refused: a block with no
    replacement rule whose fit's interval crosses into wear-out. None when no
    block does."""
    for node in graph.get("nodes") or []:
        data = node.get("data") or {}
        if node.get("type") != "component" or not block_has(data):
            continue
        label = data.get("label") or node.get("id")
        try:
            rule = parse_rule(data, label)
        except AnalysisError:
            continue
        if rule["rule"] != "none":
            continue
        crosses = band_crosses(data["model"], saved_entry(data["model"], resolve_model))
        if crosses:
            return band_refusal(label, crosses)
    return None


# ---------------------------------------------------------------------------
# Download as Python and imports
# ---------------------------------------------------------------------------

def script_model(model: dict, process=None) -> str:
    """Python that builds the block's repairable model with surpyval."""
    desc = describe_process(process) if process is not None else {
        "form": model.get("form"), "params": model.get("params") or [], "options": model.get("options") or {}}
    form = desc["form"]
    values = {str(p["name"]): float(p["value"]) for p in desc["params"]}
    opts = desc["options"] or {}
    if form in POISSON_FORMS:
        cls = {"crow_amsaa": "CrowAMSAA", "duane": "Duane", "cox_lewis": "CoxLewis", "hpp": "HPP"}[form]
        args = [values[n] for n in PARAMS[form]]
        return f"rec.{cls}.from_params({args!r})"
    m = opts.get("m", 1)
    m_text = "float('inf')" if m == "all" else repr(int(m))
    if form == "ari":
        base = opts.get("baseline") or "crow_amsaa"
        names = ARI_PARAMS[base]
        cls = {"crow_amsaa": "CrowAMSAA", "duane": "Duane", "cox_lewis": "CoxLewis"}[base]
        return (f"rec.ARI.fit_from_parameters({[values[n] for n in names[1:]]!r}, {values['rho']!r}, m={m_text}, "
                f"baseline=rec.{cls})")
    rest = values.get("rho", values.get("q"))
    life = [values["alpha"], values["beta"]]
    if form == "ara":
        return f"rec.ARA.fit_from_parameters({life!r}, {rest!r}, m={m_text}, dist=surv.Weibull)"
    if form == "g1":
        return f"rec.GeneralizedOneRenewal.fit_from_parameters({life!r}, {rest!r}, dist=surv.Weibull)"
    kij = "ii" if form == "grp_ii" else "i"
    return f"rec.GeneralizedRenewal.fit_from_parameters({life!r}, {rest!r}, kijima={kij!r}, dist=surv.Weibull)"


def script_entries(data: dict, label: str) -> list[str]:
    """The spec entries "Download as Python" writes for the rule (an age rule
    is written by the preventive code, as the block's age replacement)."""
    extra, _ = spec_entries(data, label)
    return [f'"replace_after": {extra["replace_after"]}'] if "replace_after" in extra else []


def from_process(process, label: str) -> Optional[dict]:
    """A block's stored model for a surpyval repairable model found in an
    imported RePyability document, or None for one a block can't take."""
    try:
        desc = describe_process(process)
    except AnalysisError:
        return None
    out = {"kind": KIND, "source": "params", "name": f"{NAMES[desc['form']]} ({label})", **desc}
    if not out.get("options"):
        out.pop("options", None)
    return out


def rule_from_spec(spec: dict) -> Optional[dict]:
    """A block's replacement rule from an imported component spec's
    ``replace_after`` (``preventive`` age replacement is imported as the
    block's maintenance, which works the same)."""
    n = spec.get("replace_after")
    if isinstance(n, (int, float)) and not isinstance(n, bool) and float(n) == int(n) and 1 <= n <= MAX_REPAIRS + 1:
        return {"rule": "repairs", "repairs": int(n) - 1}
    return None

