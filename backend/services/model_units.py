"""A saved model used on another clock of the same kind: its life converted.

A model fitted in days, put in a diagram (or a calculation) that counts in
hours, is the same life on a stretched time axis: ``T = c·t`` with ``c`` the
hours in a day (:func:`backend.units.unit_factor`, the app's one calendar
convention). So the model is converted, never read as if its days were hours.

How each family is converted (``c`` = new units per old unit):

* a scale parameter is multiplied by ``c`` (Weibull, log-logistic and
  exponentiated Weibull ``alpha``, Rayleigh ``sigma``), a location and its
  spread too (normal, Gumbel and logistic ``mu`` and ``sigma``), and so are
  the ends of a bounded life (uniform and four-parameter beta ``a``, ``b``);
* a rate is divided by ``c`` (exponential ``failure_rate``, gamma's rate
  ``beta``);
* a lognormal's ``mu`` (the log of its median) gains ``ln c``;
* shape parameters, a limited-failure share ``p`` and a zero-inflation
  share ``f0`` are unchanged; an offset ``gamma`` is multiplied by ``c``;
* a mixture converts each mode by its base distribution's rule;
* a repairable model: Crow-AMSAA ``alpha`` × c; Duane ``b`` ÷ c^alpha;
  Cox-Lewis ``alpha`` − ln c and ``beta`` ÷ c; HPP ``lambda`` ÷ c; the renewal
  forms (ARA, ARI, G1, generalised renewal) convert their Weibull life (or
  ARI's baseline intensity) and keep their restoration factor.

Anything with no such rule (the 0-to-1 beta, a Bayesian update's posterior
predictive, a regression model at its covariates) is wrapped instead:
:class:`TimeScaled` reads it at ``T / c``. Both give the same reliability at
every time; scaling the parameters keeps the model the engines' own kind, so
their exact methods still apply.

Units of different kinds (cycles in an hours diagram), and blank or unknown
units, are never converted here: the callers keep their warnings for them.
"""

from __future__ import annotations

import math
from typing import Optional

import numpy as np

from backend.units import canonical_unit, conversion_note, normalize_unit, unit_factor, unit_in_text

# Per distribution, how each parameter converts: "mul" (× c), "div" (÷ c), "log" (+ ln c);
# a parameter not listed (a shape) is unchanged.
_RULES: dict[str, dict[str, str]] = {
    "weibull": {"alpha": "mul"},
    "exponential": {"failure_rate": "div"},
    "normal": {"mu": "mul", "sigma": "mul"},
    "lognormal": {"mu": "log"},
    "gamma": {"beta": "div"},
    "loglogistic": {"alpha": "mul"},
    "expo_weibull": {"alpha": "mul"},
    "gumbel": {"mu": "mul", "sigma": "mul"},
    "gumbel_lev": {"mu": "mul", "sigma": "mul"},
    "logistic": {"mu": "mul", "sigma": "mul"},
    "rayleigh": {"sigma": "mul"},
    "beta4": {"a": "mul", "b": "mul"},
    "uniform": {"a": "mul", "b": "mul"},
}
#: Extras (Reliafy's names) that are times: an offset.
_TIME_EXTRAS = ("gamma",)
#: Model kinds converted here. Others keep their own handling: an accelerated life model at a
#: stress and a life on two clocks convert themselves, a mission's rates are per diagram unit, a
#: condition-based block's readings and age are in the model's unit (left as today).
_PLAIN_KINDS = (None, "", "distribution")


def _apply(rule: Optional[str], value: float, c: float) -> float:
    if rule == "mul":
        return value * c
    if rule == "div":
        return value / c
    if rule == "log":
        return value + math.log(c)
    return value


def scalable(dist_id) -> bool:
    """Whether a plain distribution (or a mixture of one) converts by its parameters."""
    if dist_id == "mixture":
        return True
    return dist_id in _RULES


def scale_params(dist_id: str, params: list, c: float, base_id: Optional[str] = None) -> Optional[list]:
    """``params`` (``[{name, value}]``) on a time axis ``c`` times longer, or None when the
    distribution has no rule (wrap it instead). A mixture's ``alpha1``, ``weight2`` … follow
    ``base_id``'s rules."""
    if dist_id == "mixture":
        from backend.services import rbd_mixture

        rules = _RULES.get(base_id or "weibull")
        if rules is None:
            return None
        out = []
        for p in params or []:
            split = rbd_mixture._numbered(str(p.get("name") or ""))
            stem = split[0] if split else str(p.get("name") or "")
            out.append(_scaled_param(p, rules.get(stem), c))
        return out
    rules = _RULES.get(dist_id)
    if rules is None:
        return None
    return [_scaled_param(p, rules.get(str(p.get("name") or "").lower()), c) for p in params or []]


def _scaled_param(p, rule, c: float):
    if not isinstance(p, dict):
        return p
    try:
        value = float(p.get("value"))
    except (TypeError, ValueError):
        return dict(p)  # left for the builder to refuse in its own words
    out = {**p, "value": _apply(rule, value, c)}
    ci = p.get("ci")
    if isinstance(ci, (list, tuple)) and len(ci) == 2:
        try:
            ends = sorted(_apply(rule, float(v), c) for v in ci)  # a rate's interval flips
            out["ci"] = ends
        except (TypeError, ValueError):
            pass
    return out


def scale_extras(extras: Optional[dict], c: float) -> Optional[dict]:
    """A model's extras with its offset converted (shares unchanged)."""
    if not extras:
        return extras
    out = dict(extras)
    for key in _TIME_EXTRAS:
        if out.get(key) is not None:
            try:
                out[key] = float(out[key]) * c
            except (TypeError, ValueError):
                pass
    return out


def scale_values(dist_id: str, values, c: float) -> Optional[list]:
    """Parameter values in the distribution's own order, converted; None without a rule."""
    from backend.fitting import DISTRIBUTIONS

    entry = DISTRIBUTIONS.get(dist_id)
    if entry is None or dist_id not in _RULES:
        return None
    names = list(entry["dist"].parameter_names)
    rules = _RULES[dist_id]
    return [_apply(rules.get(n), float(v), c) for n, v in zip(names, values)]


# -- repairable models ---------------------------------------------------------------------

def _weibull_life(values: dict, c: float) -> dict:
    return {**values, "alpha": values["alpha"] * c} if "alpha" in values else values


def _poisson(form: str, values: dict, c: float) -> dict:
    out = dict(values)
    if form == "crow_amsaa" and "alpha" in out:
        out["alpha"] = out["alpha"] * c
    elif form == "duane" and "alpha" in out and "b" in out:
        out["b"] = out["b"] / c ** out["alpha"]
    elif form == "cox_lewis" and "alpha" in out and "beta" in out:
        out["alpha"] = out["alpha"] - math.log(c)
        out["beta"] = out["beta"] / c
    elif form == "hpp" and "lambda" in out:
        out["lambda"] = out["lambda"] / c
    return out


def scale_repairable_params(model: dict, c: float) -> Optional[list]:
    """A block's repairable model's parameters on a time axis ``c`` times longer, or None
    for a form with no rule."""
    form = model.get("form")
    params = model.get("params") or []
    try:
        values = {str(p.get("name")): float(p.get("value")) for p in params if isinstance(p, dict)}
    except (TypeError, ValueError):
        return None
    if form in ("crow_amsaa", "duane", "cox_lewis", "hpp"):
        new = _poisson(form, values, c)
    elif form == "ari":
        new = _poisson((model.get("options") or {}).get("baseline") or "crow_amsaa", values, c)
    elif form in ("ara", "g1", "grp_i", "grp_ii"):
        new = _weibull_life(values, c)
    else:
        return None
    return [{**p, "value": new.get(str(p.get("name")), p.get("value"))} if isinstance(p, dict) else p
            for p in params]


# -- the wrapper ---------------------------------------------------------------------------

class _Name:
    def __init__(self, name: str):
        self.name = name


class TimeScaled:
    """A life read on a clock ``c`` times finer (``T = c·t``): every function of time at
    ``T / c``, densities and rates divided by ``c``, lives and draws multiplied by it."""

    def __init__(self, model, c: float):
        self.model = model
        self.c = float(c)
        inner = getattr(model, "dist", None)
        self.dist = inner if getattr(inner, "name", None) else _Name(type(model).__name__)

    @property
    def _hi(self):  # a regression node's fitted range (rbd_analysis._model_hi), on this clock
        hi = getattr(self.model, "_hi", None)
        return float(hi) * self.c if hi else None

    def _t(self, x):
        return np.asarray(x, dtype=float) / self.c

    def sf(self, x, *args, **kwargs):
        return self.model.sf(self._t(x), *args, **kwargs)

    def ff(self, x, *args, **kwargs):
        return self.model.ff(self._t(x), *args, **kwargs)

    def df(self, x, *args, **kwargs):
        return np.asarray(self.model.df(self._t(x), *args, **kwargs), dtype=float) / self.c

    def hf(self, x, *args, **kwargs):
        return np.asarray(self.model.hf(self._t(x), *args, **kwargs), dtype=float) / self.c

    def Hf(self, x, *args, **kwargs):
        return self.model.Hf(self._t(x), *args, **kwargs)

    def qf(self, p, *args, **kwargs):
        return np.asarray(self.model.qf(p, *args, **kwargs), dtype=float) * self.c

    def cs(self, x, X, *args, **kwargs):
        return self.model.cs(self._t(x), np.asarray(X, dtype=float) / self.c, *args, **kwargs)

    def random(self, size, *args, **kwargs):
        return np.asarray(self.model.random(size, *args, **kwargs), dtype=float) * self.c

    def mean(self, *args, **kwargs):
        return float(self.model.mean(*args, **kwargs)) * self.c


# -- a block's model -----------------------------------------------------------------------

def conversion(model, to_unit) -> Optional[dict]:
    """``{"from", "to", "factor"}`` when ``model`` (a block's stored model) has a unit that
    converts to ``to_unit``; None when the units are the same, differ in kind, or either is
    blank or unknown."""
    if not isinstance(model, dict):
        return None
    c = unit_factor(model.get("unit"), to_unit)
    if c is None:
        return None
    return {"from": canonical_unit(model.get("unit")), "to": canonical_unit(to_unit), "factor": c}


def convertible_kind(model) -> bool:
    """Whether this module converts a block model of this kind."""
    if not isinstance(model, dict):
        return False
    kind = model.get("kind")
    return kind in _PLAIN_KINDS or kind in ("regression", "repairable")


def convert_model(model, to_unit) -> tuple[object, Optional[dict]]:
    """``(model, conversion)``: a block's stored model in ``to_unit`` and what was done, or the
    model as it is and None. A converted model keeps what it was in ``converted`` (its unit,
    parameters and extras before, the factor, and ``wrap`` when it is read through
    :class:`TimeScaled`); its ``unit`` becomes ``to_unit``. Converting twice changes nothing."""
    if not convertible_kind(model) or model.get("converted"):
        return model, None
    conv = conversion(model, to_unit)
    if conv is None:
        return model, None
    c = conv["factor"]
    record = {**conv, "params": model.get("params"), "extras": model.get("extras")}
    out = dict(model)
    kind = model.get("kind")
    params = None
    if kind == "repairable":
        params = scale_repairable_params(model, c)
        if params is None:
            return model, None  # a form with no rule: left as today, with its warning
    elif kind == "regression":
        record["wrap"] = True
    else:
        from backend.services import rbd_mixture

        params = scale_params(model.get("distribution_id"), model.get("params") or [], c,
                              rbd_mixture.base_id(model) if rbd_mixture.is_mixture(model) else None)
        if params is None:
            record["wrap"] = True
    if params is not None:
        out["params"] = params
        if model.get("extras"):
            out["extras"] = scale_extras(model.get("extras"), c)
    out["unit"] = conv["to"]
    out["converted"] = record
    return out, conv


def wrap(built, model):
    """``built`` (a model's live object) read on the diagram's clock when ``model`` was
    converted; callers use it where the live object didn't come from converted parameters (a
    family with no rule, a regression model, a Bayesian update's posterior predictive)."""
    conv = (model or {}).get("converted") if isinstance(model, dict) else None
    if not conv:
        return built
    return TimeScaled(built, conv["factor"])


def needs_wrap(model) -> bool:
    conv = (model or {}).get("converted") if isinstance(model, dict) else None
    return bool(conv and conv.get("wrap"))


def draw_in_unit(model: dict, dist_id: str, values, extras: Optional[dict]):
    """A parameter draw of a converted block's saved fit (in the fit's own unit), converted the
    same way: ``(values, extras)``; as it is when the block wasn't converted."""
    conv = (model or {}).get("converted")
    if not conv:
        return values, extras
    c = conv["factor"]
    scaled = scale_values(dist_id, values, c)
    return (scaled if scaled is not None else values), scale_extras(extras, c)


# -- a diagram -----------------------------------------------------------------------------

def _slots(node: dict) -> list[tuple]:
    from backend.services import rbd_standby

    data = node.get("data") or {}
    paths = rbd_standby.model_paths(data)
    if isinstance(data.get("repair"), dict):
        paths.append(("repair",))
    return paths


def used_note(conv: dict, what: str = "answer", source: str = "model") -> str:
    """"model in days, answer in hours: converted at 1 day = 24 hours" — what a calculation
    that converted a model says (``what`` names the other clock: interval, period, answer;
    ``source`` what was converted: a model, the evidence)."""
    keys = {normalize_unit(conv["from"]), normalize_unit(conv["to"])}
    # No position, so no duty: an hour is a calendar hour (running_clock has the rule at a position).
    running = " (running all the time)" if "hour" in keys and keys & {"day", "week", "month", "year"} else ""
    return (f"{source} in {unit_in_text(conv['from'])}, {what} in {unit_in_text(conv['to'])}: converted at "
            f"{conversion_note(conv['from'], conv['to'])}{running}")


def convert_spec(distribution_id, params, extras, from_unit, to_unit) -> tuple[list, Optional[dict], Optional[dict]]:
    """A plain distribution given as ``distribution_id`` + ``params`` (+ ``extras``) in
    ``from_unit``, in ``to_unit``: ``(params, extras, conversion)``; unchanged with None when the
    units don't convert or the family has no parameter rule."""
    model = {"distribution_id": distribution_id, "params": params, "extras": extras, "unit": from_unit}
    if distribution_id == "mixture" or not scalable(distribution_id):
        return params, extras, None
    new, conv = convert_model(model, to_unit)
    if conv is None:
        return params, extras, None
    return new["params"], new.get("extras"), conv


def words(conv: dict) -> str:
    """"fitted in days, shown in hours" — what a converted block says."""
    return f"fitted in {unit_in_text(conv['from'])}, shown in {unit_in_text(conv['to'])}"


def convert_graph(graph: dict, unit=None, prefix: str = "") -> tuple[dict, list]:
    """``(graph, conversions)``: a diagram with every block model whose unit converts to the
    diagram's (``unit``, default the graph's own) converted, and one entry per conversion
    ``{"id", "label", "from", "to", "factor", "repair", "note"}``. The graph passed in is not
    changed; a graph with nothing to convert comes back as it is."""
    if not isinstance(graph, dict):
        return graph, []
    to = unit if unit is not None else graph.get("unit")
    if normalize_unit(to) is None:
        return graph, []
    from backend.services import rbd_standby

    nodes = graph.get("nodes") or []
    out_nodes, conversions, changed = [], [], False
    for node in nodes:
        if not isinstance(node, dict):
            out_nodes.append(node)
            continue
        data = node.get("data") or {}
        new_data = None
        for path in _slots(node):
            model = rbd_standby.get_path(data, path)
            new, conv = convert_model(model, to)
            if conv is None:
                continue
            if new_data is None:
                new_data = dict(data)
            rbd_standby.set_path(new_data, path, new)
            label = prefix + str(data.get("label") or node.get("id"))
            repair = path == ("repair",)
            text = words(conv)
            conversions.append({
                "id": node.get("id"), "label": label, "from": conv["from"], "to": conv["to"],
                "factor": conv["factor"], "repair": repair,
                "note": (f"“{label}”{' (repair time)' if repair else ''}: {text} "
                         f"({conversion_note(conv['from'], conv['to'])})."),
            })
        if new_data is not None:
            changed = True
            out_nodes.append({**node, "data": new_data})
        else:
            out_nodes.append(node)
    if not changed:
        return graph, []
    return {**graph, "nodes": out_nodes}, conversions


def subsystem_resolver(resolve_subsystem, unit):
    """``resolve_subsystem`` whose diagrams come back in ``unit``: a sub-system's blocks are
    evaluated on the parent diagram's clock, so they convert to its unit."""
    if resolve_subsystem is None or normalize_unit(unit) is None:
        return resolve_subsystem

    def resolve(sub_id):
        sub = resolve_subsystem(sub_id)
        if not isinstance(sub, dict):
            return sub
        converted, _ = convert_graph(sub, unit)
        return {**converted, "unit": unit}

    return resolve


def subsystem_conversions(graph: dict, resolve_subsystem, unit=None, prefix: str = "",
                          visited: frozenset = frozenset()) -> list:
    """The conversions inside ``graph``'s sub-systems (nested too), labelled "Sub-system ›
    Block", for the result's list."""
    to = unit if unit is not None else (graph or {}).get("unit")
    if resolve_subsystem is None or normalize_unit(to) is None:
        return []
    out: list = []
    for node in (graph or {}).get("nodes") or []:
        if not isinstance(node, dict) or node.get("type") != "subsystem":
            continue
        data = node.get("data") or {}
        sub_id = (data.get("rbd") or {}).get("id")
        if not sub_id or sub_id in visited:
            continue
        try:
            sub = resolve_subsystem(sub_id)
        except Exception:  # noqa: BLE001 - the analysis reports a missing sub-system itself
            sub = None
        if not isinstance(sub, dict):
            continue
        label = prefix + str(data.get("label") or node.get("id")) + " › "
        _, convs = convert_graph(sub, to, prefix=label)
        out.extend(convs)
        out.extend(subsystem_conversions(sub, resolve_subsystem, to, label, visited | {sub_id}))
    return out
