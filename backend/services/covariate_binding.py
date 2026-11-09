"""Covariates fixed at a position, the rest set in an RBD: one mechanism for NSWC-11 covariate
models, accelerated life (ALT) models and proportional-hazards (PH) models (Derryn, 9 Nov 2026:
"When applying a covariate model to a location, the user can choose to fix some, all, or none of
the covariates. These could be design parameters or they could be use or environmental. If they
are use or env one can set them in the RBD"; and "make it the same for ALT, allow them to be fixed
or variables").

A **binding** says which model and what's fixed::

    {"source": "nswc" | "alt" | "ph",
     "ref": "<library record id (nswc) or saved model id (alt, ph)>",
     "fixed": {input key: value},        # fixed at the position
     "roles": {input key: "design" | "use" | "environment"}}   # ALT / PH only: what each one is

Every source's covariates come out as the same inputs (:func:`inputs_of`, the shape
``backend.library.covariate`` gives NSWC-11's), so one form fixes them at a position and one
panel sets the rest on an RBD block. NSWC-11 inputs carry their role from the handbook's table;
an ALT stress or a PH covariate is use until the user says otherwise.

In an RBD a block whose model is ``{"kind": "bound", "binding": {...}}`` takes, for each input
the position left open, in this order: its own value (``data.covariate_values``), the diagram's
Use or Environment value it's matched to (``graph.conditions``: by the input's key, symbol or
label and its unit, or the block's ``data.covariate_map``), then a default the source gives (the
handbook's, or the PH fit's average). No value and no default: the block needs it, and the
calculation says which blocks need what, never guessing (:func:`resolve_node`).
:func:`bind_graph` turns every bound block into a model the analysis already knows: NSWC-11 an
exponential at its rate, ALT the model at that stress (``kind: alt_stress``), PH the regression
model with the values.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Optional

#: Words that mark an ALT stress or PH covariate as where it works, until the user says otherwise.
_ENVIRONMENT_WORDS = ("temp", "humid", "vibration", "contamin", "dust", "salt", "altitude", "ambient")


def _guess_role(text: str) -> str:
    low = str(text or "").lower()
    return "environment" if any(w in low for w in _ENVIRONMENT_WORDS) else "use"


SOURCES = {"nswc": "NSWC-11 covariate model", "alt": "Accelerated life model", "ph": "Proportional-hazards model"}
ROLES = ("design", "use", "environment")
#: Where a block's value came from, in words.
FROM = {"fixed": "fixed at the position", "block": "this block", "diagram": "the diagram's {role}: {name}",
        "default": "the default"}
HOURS = {"hour": 1.0, "day": 24.0, "week": 168.0, "month": 730.5, "year": 8766.0, "minute": 1 / 60}


class BindingError(ValueError):
    """A binding that can't be used, said for the user."""


# ---- the inputs, the same shape for every source -----------------------------------------------

def _nswc(ref: str) -> dict:
    from backend.library import service as library

    try:
        rec = library.get(ref)
    except library.LibraryNotFound:
        raise BindingError(f"There's no library record '{ref}'.") from None
    if rec.get("kind") != "covariate_model":
        raise BindingError(f"'{rec['label']}' isn't a covariate model.")
    return rec


def _cycles_input(rec: dict) -> dict:
    from backend.library import covariate

    word = "Operations" if covariate.rate_unit(rec) == "per_million_operations" else "Cycles"
    return {"key": "cycles_per_hour", "name": "cycles_per_hour", "kind": "number", "role": "use",
            "label": f"{word} an hour", "unit": "per hour", "group": None,
            "limits": [{"min": 0, "exclusive": True, "severity": "refuse", "why": "it must work to wear"}],
            "help": f"Its rate is {covariate.rate_unit_words(rec)}: how many it makes an hour turns it into a rate "
                    "per hour."}


def _alt_doc(ref: str, db, owners):
    from backend.services import alt as alt_service

    doc = alt_service.get_model(db, ref, owners) if db is not None else None
    if doc is None:
        raise BindingError(f"There's no accelerated life model '{ref}' you can open.")
    return doc


def _ph_doc(ref: str, db, owners):
    from backend.services import models as models_service

    doc = models_service.get_model(db, ref, owners) if db is not None else None
    if doc is None or getattr(doc, "kind", "") != "regression":
        raise BindingError(f"There's no proportional-hazards model '{ref}' you can open.")
    return doc


def inputs_of(binding: dict, db=None, owners=None) -> list[dict]:
    """The model's covariates as inputs ({key, label, symbol, unit, kind, role, default, limits,
    choices, group, help}), whatever the source."""
    source, ref, roles = binding.get("source"), str(binding.get("ref") or ""), binding.get("roles") or {}
    if source == "nswc":
        from backend.library import covariate
        from backend.library import service as library

        rec = _nswc(ref)
        out = library.covariate_inputs(rec)
        if covariate.per_cycle(rec):
            out.append(_cycles_input(rec))
        return out
    if source == "alt":
        doc = _alt_doc(ref, db, owners)
        r = doc.results or {}
        levels = [lvl.get("stress") or [] for lvl in r.get("levels") or []]
        out = []
        for i, st in enumerate(r.get("stresses") or []):
            key = str(st.get("column") or st.get("label") or f"stress_{i + 1}")
            tested = [row[i] for row in levels if len(row) > i and row[i] is not None]
            limits = []
            if tested:
                limits.append({"min": min(tested), "max": max(tested), "severity": "warn", "page": None,
                               "why": "outside the tested stresses, so the model extrapolates"})
            out.append({"key": key, "name": key, "kind": "number", "label": st.get("label") or key,
                        "unit": st.get("unit") or "", "role": roles.get(key) or _guess_role(f"{key} {st.get('label')}"),
                        "group": None,
                        "limits": limits, "help": "A stress of the accelerated life model."})
        return out
    if source == "ph":
        doc = _ph_doc(ref, db, owners)
        fields = ((doc.results or {}).get("functions") or {}).get("covariates") or []
        out = []
        for f in fields:
            key = str(f.get("name"))
            number = f.get("type", "number") == "number"
            item = {"key": key, "name": key, "kind": "number" if number else "choice", "label": key,
                    "unit": f.get("unit") or "", "role": roles.get(key) or _guess_role(key), "group": None, "limits": [],
                    "help": "A covariate of the proportional-hazards model."}
            if f.get("default") is not None:
                item.update(default=f["default"], default_basis="typical")
            if not number:
                item["choices"] = [{"code": str(c), "label": str(c)} for c in f.get("choices") or f.get("levels") or []]
            out.append(item)
        return out
    raise BindingError(f"A binding's source is one of {', '.join(SOURCES)}.")


def _number(inp: dict, value: Any) -> Any:
    if inp.get("kind") == "choice":
        codes = [c["code"] for c in inp.get("choices") or []]
        if codes and str(value) not in codes:
            raise BindingError(f"{inp['label']} must be one of {', '.join(codes)}.")
        return str(value)
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise BindingError(f"{inp['label']} must be a number.") from None
    if not math.isfinite(v):
        raise BindingError(f"{inp['label']} must be a finite number.")
    for limit in inp.get("limits") or []:
        if limit.get("severity", "refuse") != "refuse":
            continue
        lo, hi, excl = limit.get("min"), limit.get("max"), limit.get("exclusive")
        if (lo is not None and (v < lo or (excl and v == lo))) or (hi is not None and (v > hi or (excl and v == hi))):
            raise BindingError(f"{inp['label']} is {v:g}{(' ' + inp['unit']) if inp.get('unit') else ''}: "
                               f"{limit.get('why') or 'outside its limits'}.")
    return v


def normalise(binding: Any, db=None, owners=None) -> dict:
    """A binding checked: a known source and model, fixed values for inputs it has (each a number
    within its hard limits, or one of its choices), roles that are design, use or environment."""
    if not isinstance(binding, dict):
        raise BindingError("A binding is {source, ref, fixed?, roles?}.")
    source = binding.get("source")
    if source not in SOURCES:
        raise BindingError(f"A binding's source is one of {', '.join(SOURCES)}.")
    ref = str(binding.get("ref") or "").strip()
    if not ref:
        raise BindingError("A binding needs ref: the library record or saved model.")
    roles = binding.get("roles") or {}
    if not isinstance(roles, dict) or any(v not in ROLES for v in roles.values()):
        raise BindingError("roles maps an input to design, use or environment.")
    out = {"source": source, "ref": ref, "fixed": {}, "roles": {}}
    inputs = {i["key"]: i for i in inputs_of({**out, "roles": roles}, db, owners)}
    if source in ("alt", "ph"):  # NSWC-11's roles are the handbook's: fixed in the data
        out["roles"] = {k: v for k, v in roles.items() if k in inputs}
    fixed = binding.get("fixed") or {}
    if not isinstance(fixed, dict):
        raise BindingError("fixed maps an input to its value at the position.")
    unknown = sorted(k for k in fixed if k not in inputs)
    if unknown:
        raise BindingError(f"Unknown input{'s' if len(unknown) > 1 else ''} {', '.join(unknown)}: "
                           f"it has {', '.join(inputs) or 'none'}.")
    for k, v in fixed.items():
        if v is None or v == "":
            continue
        out["fixed"][k] = _number(inputs[k], v)
    return out


def open_inputs(binding: dict, db=None, owners=None) -> list[dict]:
    """The inputs the position leaves open, to set where the model is used (an RBD block)."""
    fixed = binding.get("fixed") or {}
    return [i for i in inputs_of(binding, db, owners) if i["key"] not in fixed]


# ---- a block's values: its own, the diagram's, a default -------------------------------------

def _norm(text: Any) -> str:
    return " ".join(str(text or "").lower().replace("_", " ").split())


def _unit(text: Any) -> str:
    return _norm(text).replace("°", "").replace("deg ", "").strip()


def match_condition(inp: dict, conditions: list[dict], mapped: Optional[str] = None) -> Optional[dict]:
    """The diagram's Use or Environment value an input takes: the one the block maps it to by name,
    else one of the input's own role whose name is its key, symbol or label, in the same unit."""
    usable = [c for c in conditions or [] if isinstance(c, dict) and c.get("name") not in (None, "")
              and c.get("value") not in (None, "")]
    if mapped:
        return next((c for c in usable if _norm(c["name"]) == _norm(mapped)), None)
    names = {_norm(inp.get("key")), _norm(inp.get("name")), _norm(inp.get("symbol")), _norm(inp.get("label"))} - {""}
    for c in usable:
        if c.get("role") not in (None, inp.get("role")):
            continue
        if _norm(c["name"]) in names and _unit(c.get("unit")) == _unit(inp.get("unit")):
            return c
    return None


def resolve_node(binding: dict, inputs: list[dict], block_values: Optional[dict] = None,
                 conditions: Optional[list] = None, mapping: Optional[dict] = None) -> dict:
    """A bound block's value for every input, and where each came from: {values, sources: {key:
    {from, words}}, missing: [inputs]}. Fixed at the position first, then the block's own, then the
    diagram's matched value, then a default the source gives; else it's missing."""
    fixed = binding.get("fixed") or {}
    block_values = block_values or {}
    mapping = mapping or {}
    values, sources, missing = {}, {}, []
    for inp in inputs:
        key = inp["key"]
        if key in fixed:
            values[key], sources[key] = fixed[key], {"from": "fixed", "words": FROM["fixed"]}
            continue
        if block_values.get(key) not in (None, ""):
            values[key], sources[key] = block_values[key], {"from": "block", "words": FROM["block"]}
            continue
        c = match_condition(inp, conditions or [], mapping.get(key))
        if c is not None:
            role = (c.get("role") or inp.get("role") or "condition").capitalize()
            values[key] = c["value"]
            sources[key] = {"from": "diagram", "name": c["name"],
                            "words": FROM["diagram"].format(role=role, name=c["name"])}
            continue
        if inp.get("default") is not None:
            values[key], sources[key] = inp["default"], {"from": "default", "words": FROM["default"]}
            continue
        missing.append(inp)
    return {"values": values, "sources": sources, "missing": missing}


# ---- what a bound block is, for the analysis -------------------------------------------------

def _hours_per(unit: str) -> float:
    from backend.units import normalize_unit

    key = normalize_unit(unit or "") or "hour"
    if key not in HOURS:
        raise BindingError(f"A diagram in {unit} can't take a rate per hour: use hours, days, weeks, months or years.")
    return HOURS[key]


def concrete(binding: dict, values: dict, diagram_unit: str = "hours") -> dict:
    """The model a bound block is under ``values`` (every input set): NSWC-11 an exponential at
    its rate in the diagram's unit; ALT the model at that stress; PH the regression model, with the
    values to evaluate it at (``covariates``)."""
    source = binding["source"]
    if source == "nswc":
        from backend.library import covariate
        from backend.library import service as library

        rec = _nswc(binding["ref"])
        conds = {k: v for k, v in values.items() if k != "cycles_per_hour"}
        try:
            got = covariate.evaluate(rec, conds, library.resolve)
        except covariate.CovariateError as exc:
            raise BindingError(" ".join(exc.problems)) from None
        per_million = got["total"]
        if covariate.per_cycle(rec):
            per_million *= float(values.get("cycles_per_hour") or 0)
        rate = per_million / 1e6 * _hours_per(diagram_unit)
        if not rate > 0:
            raise BindingError("Its rate comes out at 0 for these values: check them against the handbook's limits.")
        return {"distribution_id": "exponential", "params": [{"name": "failure_rate", "value": rate}],
                "source": "bound", "warnings": got.get("warnings") or []}
    if source == "alt":
        return {"kind": "alt_stress", "model_id": binding["ref"], "stress": [float(values[k]) for k in values],
                "diagram_unit": diagram_unit}
    if source == "ph":
        return {"kind": "regression", "modelId": binding["ref"], "covariates": values}
    raise BindingError(f"Unknown source {source!r}.")


def needs_words(label: str, missing: list[dict]) -> str:
    """'Pump A needs Temperature (Environment, °C), Load (Use, kW)'."""
    parts = [f"{i['label']} ({(i.get('role') or 'use').capitalize()}{', ' + i['unit'] if i.get('unit') else ''})"
             for i in missing]
    return f"{label} needs {', '.join(parts)}"


def bind_graph(graph: dict, inputs_for: Callable[[dict], list[dict]], covariates: Optional[dict] = None) -> tuple:
    """The graph with every bound block made concrete, and the covariate values for the PH and ALT
    ones: (graph, covariates, needs). ``inputs_for(binding)`` gives a binding's inputs (the caller
    reads the saved models). ``needs``: a line per block still missing a value; when there are
    any, the analysis stops and says them."""
    nodes = graph.get("nodes") or []
    if not any(((n.get("data") or {}).get("model") or {}).get("kind") == "bound" for n in nodes):
        return graph, covariates, []
    conditions = graph.get("conditions") or []
    unit = graph.get("unit") or "hours"
    covs = dict(covariates or {})
    needs: list[str] = []
    out_nodes = []
    for n in nodes:
        data = dict(n.get("data") or {})
        model = data.get("model") or {}
        if model.get("kind") != "bound":
            out_nodes.append(n)
            continue
        label = data.get("label") or n.get("id")
        binding = model.get("binding") or {}
        try:
            inputs = inputs_for(binding)
        except BindingError as exc:
            needs.append(f"{label}: {exc}")
            out_nodes.append(n)
            continue
        got = resolve_node(binding, inputs, data.get("covariate_values"), conditions, data.get("covariate_map"))
        if got["missing"]:
            needs.append(needs_words(label, got["missing"]))
            out_nodes.append(n)
            continue
        ordered = {i["key"]: got["values"][i["key"]] for i in inputs}
        try:
            made = concrete(binding, ordered, unit)
        except BindingError as exc:
            needs.append(f"{label}: {exc}")
            out_nodes.append(n)
            continue
        if made.get("kind") == "regression":
            covs[n.get("id")] = made.pop("covariates")
            fields = [{"name": i["key"], "type": "number" if i["kind"] == "number" else "category",
                       "default": ordered[i["key"]]} for i in inputs]
            made["covariates"] = fields
        data["model"] = made
        out_nodes.append({**n, "data": data})
    return {**graph, "nodes": out_nodes}, covs, needs


def bound_blocks(graph: dict, inputs_for: Callable[[dict], list[dict]]) -> list[dict]:
    """Each bound block of a diagram, as the calculator shows it: {id, label, binding, inputs (the
    ones its position left open), values, sources (where each value came from), missing, needs
    (words), problem (a model that can't be read)}."""
    out = []
    conditions = graph.get("conditions") or []
    for n in graph.get("nodes") or []:
        data = n.get("data") or {}
        model = data.get("model") or {}
        if model.get("kind") != "bound":
            continue
        label = data.get("label") or n.get("id")
        binding = model.get("binding") or {}
        row = {"id": n.get("id"), "label": label, "binding": binding, "name": model.get("name")}
        try:
            inputs = inputs_for(binding)
        except BindingError as exc:
            out.append({**row, "inputs": [], "values": {}, "sources": {}, "missing": [], "problem": str(exc)})
            continue
        got = resolve_node(binding, inputs, data.get("covariate_values"), conditions, data.get("covariate_map"))
        open_ = [i for i in inputs if i["key"] not in (binding.get("fixed") or {})]
        sources = {k: {**v, "value": got["values"].get(k)} for k, v in got["sources"].items()}
        out.append({**row, "inputs": open_, "fixed": binding.get("fixed") or {}, "values": got["values"],
                    "sources": sources, "missing": [i["key"] for i in got["missing"]],
                    "needs": needs_words(label, got["missing"]) if got["missing"] else None})
    return out
