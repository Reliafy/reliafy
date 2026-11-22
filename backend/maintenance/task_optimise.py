"""Optimise… on a maintenance task: how often to do it, worked out from the life model of the
failure modes it prevents (Derryn, 22 Nov 2026: strategy "links the life model and the task…
it is how often it is done, but it is reliant on the life model so it needs to be on both
places").

For each failure mode the task serves, the calculator its kind of task calls for, the very ones
the RCM task card and Strategy use:

* replace or restore at an age (fixed_interval): the cost-optimal replacement age
  (``strategy.optimal_replacement``), with how far it moves across the model's 90% parameter
  bounds; the planned cost is the task's own (typed, or its LSA's labour and parts), the
  unplanned cost the failure's (a figure saved before, the position class's, or typed);
* check condition (on_condition): half the P-F interval (``rcm_intervals.on_condition_interval``);
* check a hidden function (failure_finding): the longest test interval that meets a target
  unavailability (``rcm_intervals.failure_finding_interval``);
* anything else (routine work, a mode run to failure): nothing to optimise, said so.

The life model is the mode's: the one an earlier Optimise rested on, the decision's evidence, a
model attached to the mode's position for it (or for every failure there), else the figures of a
saved analysis linked as evidence. A degradation model counts by its time to the limit.

``use`` saves the answer: the task takes the interval in its own unit (running hours meet the
calendar at the position's duty), the calculation is saved as a strategy analysis (so it shows in
Strategy's list too) carrying ``inputs.optimise`` (task, mode, position, model and the model's
fingerprint), linked as the mode's evidence, and one line on it goes in the mode's notes. The
model's fingerprint lets every reader say when the model has been refitted since: its optimum may
have moved. Nothing changes the interval by itself.

RePyability computes; Reliafy records: the calculators stay in their services; this module only
gathers the records they need and writes back what the user chose.
"""

from __future__ import annotations

import math
from datetime import date
from typing import Any, Optional

from backend.services import running_clock
from backend.services.strategy import StrategyError, fmt_num
from backend.units import normalize_unit, unit_in_text

#: What each kind of task works out, and the saved analysis's kind and name.
CALCULATORS = {
    "fixed_interval": {"key": "replacement", "analysis": "optimal_replacement", "word": "replacement interval",
                       "name": "optimal replacement"},
    "on_condition": {"key": "pf", "analysis": "on_condition_interval", "word": "check interval",
                     "name": "P-F calculator"},
    "failure_finding": {"key": "ff", "analysis": "failure_finding_interval", "word": "test interval",
                        "name": "failure-finding calculator"},
}
#: The models a task's interval can rest on (the position's model rows of these types).
LIFE_TYPES = ("model", "degradation_model")
#: The target unavailability assumed for a failure-finding task with none given.
DEFAULT_TARGET = 0.01
MODEL_PATH = {"model": "/models/m/{}", "degradation_model": "/models/degradation/{}"}


from backend.maintenance.service import Invalid  # noqa: E402


class OptimiseError(Invalid):
    """Inputs Optimise can't use; the message says what to change (answered 422, as Invalid)."""


# ---- small helpers ---------------------------------------------------------------------

def round_down(value) -> Optional[float]:
    """An interval rounded down to what a plan is set in, as the app's "Use" rounds it: three
    significant figures from 1,000, whole from 10, else to 0.1 (rcmIntervals.roundDown)."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v) or v <= 0:
        return None
    if v >= 1000:
        step = 10 ** (math.floor(math.log10(v + 1e-9)) - 2)
        return float(math.floor(v / step + 1e-9) * step)
    if v >= 10:
        return float(math.floor(v + 1e-9))
    return max(0.1, math.floor(v * 10 + 1e-9) / 10)


def _plain(v: float):
    """3.0 → 3, for a value a person reads back."""
    return int(v) if float(v).is_integer() else v


def _number(value, label: str) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise OptimiseError(f"{label} must be a number.") from None
    if not math.isfinite(v) or v < 0:
        raise OptimiseError(f"{label} must be 0 or more.")
    return v


def fingerprint(life: dict | None) -> str:
    """The model's parameters as a short text: it changes when the model is refitted (new
    parameters), not when it's renamed."""
    if not life:
        return ""
    params = ",".join(f"{p.get('name')}={float(p.get('value')):.6g}" for p in life.get("params") or []
                      if p.get("value") is not None)
    return f"{life.get('distribution_id') or ''}:{params}"


def _unit_words(unit) -> str:
    return unit_in_text(unit) if unit else ""


def _with_unit(value, unit) -> str:
    return f"{fmt_num(value)} {_unit_words(unit)}".strip()


# ---- the model a mode's interval rests on ----------------------------------------------

def life_of(model_type: str, doc) -> dict:
    """A saved model as what the calculators take: {type, id, name, path, family, unit,
    distribution_id, params (with their bounds), extras, words} or, for one they can't take,
    the same with ``usable`` False and ``why``."""
    base = {"type": model_type, "id": doc.id, "name": doc.name,
            "path": MODEL_PATH.get(model_type, "/models/m/{}").format(doc.id)}
    r = getattr(doc, "results", None) or {}
    if model_type == "degradation_model":
        life = r.get("life_model") or {}
        threshold = r.get("threshold")
        mu = f" {r['measurement_unit']}" if r.get("measurement_unit") else ""
        if not life.get("distribution_id"):
            return {**base, "family": "degradation", "usable": False,
                    "why": "This degradation model has no time-to-limit distribution yet: refit it."}
        return {**base, "family": "degradation", "usable": True, "unit": r.get("unit") or getattr(doc, "unit", "") or "",
                "distribution_id": life["distribution_id"], "params": life.get("params") or [], "extras": None,
                "words": f"time to the limit ({fmt_num(threshold)}{mu}), {life.get('distribution') or life['distribution_id']}"
                if threshold is not None else f"time to the limit, {life.get('distribution') or life['distribution_id']}"}
    kind = getattr(doc, "kind", None)
    if kind == "joint" or (r.get("kind") == "joint"):
        base["path"] = f"/models/joint/{doc.id}"
        return {**base, "family": "condition", "usable": False,
                "why": "A condition and life model gives each unit's risk from its latest readings (Risk now, on its "
                       "page), not one interval for every unit. Link the mode's life model to work out an interval."}
    if kind != "distribution":
        return {**base, "family": "life", "usable": False,
                "why": f"“{doc.name}” is a {kind or 'non-distribution'} model: the calculators take a plain life "
                       "distribution (a Weibull, lognormal, …)."}
    params = [{k: p[k] for k in ("name", "value", "ci") if k in p} for p in r.get("params") or []]
    dist = r.get("distribution") or r.get("distribution_id") or getattr(doc, "distribution_id", "")
    return {**base, "family": "life", "usable": True, "unit": r.get("unit") or "",
            "distribution_id": r.get("distribution_id") or getattr(doc, "distribution_id", None),
            "params": params, "extras": r.get("extras") or None,
            "words": str(dist).capitalize() if dist else "life model"}


def _analysis_life(artifact) -> dict | None:
    """A saved replacement or failure-finding analysis's own figures, when no model is linked."""
    inputs = artifact.inputs or {}
    if artifact.kind not in ("optimal_replacement", "failure_finding_interval", "failure_finding") \
            or not inputs.get("distribution_id"):
        return None
    return {"type": None, "id": None, "name": artifact.name, "path": f"/strategy/analyses/{artifact.id}",
            "family": "analysis", "usable": True, "unit": inputs.get("unit") or inputs.get("model_unit") or "",
            "distribution_id": inputs["distribution_id"], "params": inputs.get("params") or [],
            "extras": inputs.get("extras") or None, "words": str(inputs["distribution_id"]).capitalize(),
            "note": f"No model is linked: these are the figures saved with “{artifact.name}”. Link the model "
                    "they came from to keep the task and the model in step."}


def _links_for(m, position_id: str, mode_id: str) -> list[dict]:
    """The position's model rows a mode's interval can rest on: those for this mode first, then
    those for every failure there (rows for other modes only are left out)."""
    try:
        links = m.position_models(position_id)
    except Exception:  # noqa: BLE001 - a position that's gone has none
        return []
    rank = lambda x: 0 if any(f["id"] == mode_id for f in x["failure_modes"]) else 1 if not x["failure_modes"] else 2  # noqa: E731
    return [x for x in sorted(links, key=rank) if rank(x) < 2 and x["model_type"] in LIFE_TYPES]


def _member(decision: dict | None, task_id: str) -> dict | None:
    """The decision (or its combination member) whose task is ``task_id``, or None."""
    if not decision:
        return None
    for o in decision.get("outcomes") or []:
        if o.get("task_id") == task_id:
            return o
    if not decision.get("outcomes") and decision.get("task_id") == task_id:
        return decision
    return None


def _evidence_of(decision: dict | None, task_id: str) -> dict:
    holder = _member(decision, task_id)
    return (holder or {}).get("evidence") or ((decision or {}).get("evidence") if holder is not None else None) or {}


# ---- reading a task --------------------------------------------------------------------

def _task_info(m, task_id: str) -> dict:
    lsa = m.task_lsa(task_id)
    task = lsa["task"]
    subject = task.get("subject") or {}
    unit = task.get("unit") or ""
    return {"id": task["id"], "name": task.get("name") or "", "interval": task.get("interval"), "unit": unit,
            "outcome": task.get("outcome"), "position_id": subject.get("id") if subject.get("kind") == "position" else None,
            "position_name": subject.get("name"), "modes": lsa.get("modes") or [],
            "restoration": task.get("restoration") or {}}


def _kind_for(task: dict, mode: dict) -> str | None:
    """What kind of task it is for this mode: its decision member's outcome, else its own kind."""
    holder = _member(mode.get("decision"), task["id"])
    return (holder or {}).get("outcome") or task.get("outcome")


def _class_costs(m, position: dict) -> dict:
    name = position.get("position_class") or position.get("class_key")
    if not name:
        return {}
    try:
        cls = m.position_class(name)
    except Exception:  # noqa: BLE001 - a class that's gone gives nothing
        return {}
    return {**(cls.get("costs") or {}), "class": cls.get("position_class") or name}


def _given_model(fetch, given: dict | None):
    if not given or not given.get("id"):
        return None
    mtype = given.get("type") or "model"
    if mtype not in LIFE_TYPES:
        raise OptimiseError("model_type must be model (a non-repairable model) or degradation_model.")
    doc = fetch(mtype, given["id"])
    if doc is None:
        raise OptimiseError("That model wasn't found, or you can't open it.")
    return life_of(mtype, doc)


def _mode_model(m, fetch, mode: dict, position: dict, task_id: str, given: dict | None):
    """(life, previous analysis, choices): the model this mode's interval rests on (None with none),
    the saved analysis linked as its evidence (its inputs fill what's left), and the position's
    model rows it could rest on instead."""
    choices = []
    for link in _links_for(m, position["id"], mode["id"]):
        doc = fetch(link["model_type"], link["model_id"])
        if doc is not None:
            life = life_of(link["model_type"], doc)
            choices.append({"type": link["model_type"], "id": doc.id, "name": doc.name, "link_id": link["id"],
                            "usable": life["usable"], "why": life.get("why"),
                            "for_mode": any(f["id"] == mode["id"] for f in link["failure_modes"])})
    evidence = _evidence_of(mode.get("decision"), task_id)
    artifact = fetch(evidence["type"], evidence["id"]) if evidence.get("type") and evidence.get("id") else None
    previous = artifact if evidence.get("type") == "strategy_analysis" else None
    life = _given_model(fetch, given)
    source = "chosen" if life else None
    if life is None and previous is not None:
        ref = ((previous.inputs or {}).get("optimise") or {}).get("model") or {}
        doc = fetch(ref.get("type"), ref.get("id")) if ref.get("type") in LIFE_TYPES and ref.get("id") else None
        if doc is not None:
            life, source = life_of(ref["type"], doc), "optimised"
    if life is None and evidence.get("type") in LIFE_TYPES and artifact is not None:
        life, source = life_of(evidence["type"], artifact), "evidence"
    if life is None:
        for c in choices:
            if c["usable"]:
                life, source = life_of(c["type"], fetch(c["type"], c["id"])), "position"
                break
    if life is None and previous is not None:
        life = _analysis_life(previous)
        source = "analysis" if life else None
    if life is not None:
        life = {**life, "source": source,
                "link_id": next((c["link_id"] for c in choices if c["id"] == life.get("id")), None)}
    return life, previous, choices


# ---- the calculations ------------------------------------------------------------------

def _to_task_unit(value: float, model_unit, task_unit, clock) -> tuple[Optional[float], str]:
    """``value`` (in the model's unit) in the task's unit, and how it was converted ('' for the
    same unit); (None, why) when the two can't meet."""
    if not task_unit or not model_unit or running_clock.same_clock(model_unit, task_unit) \
            or normalize_unit(model_unit) == normalize_unit(task_unit):
        return value, ""
    why = running_clock.refusal(model_unit, task_unit, clock)
    if why:
        return None, why
    conv = running_clock.conversion(model_unit, task_unit, clock)
    if not conv:
        return None, (f"The model is in {_unit_words(model_unit)} and the task in {_unit_words(task_unit)}: "
                      "they can't be compared. Change the task's unit, or pick a model in its unit.")
    return value * conv["factor"], running_clock.note(conv, value)


def _source(value, source: str, text: str) -> dict:
    return {"value": value, "source": source, "text": text}


def failure_cost_of(m, mode, position, prev: dict, previous, cls: dict) -> dict:
    """What one failure of this mode costs, all in, with where the figure came from: the one saved
    with the last replacement analysis, else the position class's failure cost, else missing (the user
    types it). The one place Optimise reads a failure's cost: when failure modes and classes carry
    their own failure cost and downtime, read it here first."""
    if prev.get("unplanned_cost") is not None:
        return _source(prev["unplanned_cost"], "analysis", f"From “{previous.name}”, saved before.")
    if cls.get("failure_cost") is not None:
        return _source(cls["failure_cost"], "class", f"What a failure costs in its class, {cls['class']}.")
    return _source(None, "missing", "Enter what a failure costs, all in: the repair, the parts, the downtime "
                                    "and the call-out.")


def _replacement(m, mode, position, task, life, previous, over: dict) -> dict:
    """The cost-optimal replacement age for one mode."""
    from backend.services import strategy

    prev = (previous.inputs or {}) if previous is not None and previous.kind == "optimal_replacement" else {}
    cost = m.task_cost(task["id"])
    cls = _class_costs(m, position)
    planned = over.get("planned_cost")
    if planned is not None:
        planned = _source(planned, "typed", "Typed here.")
    elif cost.get("amount") is not None and (cost.get("source") == "typed" or (cost.get("lsa") or {}).get("complete", True)):
        where = "typed on the task" if cost.get("source") == "typed" else "from its LSA: labour at the trade rates, and parts"
        planned = _source(cost["amount"], "task", f"The task's cost each time ({where}).")
    elif cost.get("amount") is not None:
        # Its LSA leaves something unpriced (a trade with no rate): never used silently as the whole cost.
        lsa = cost.get("lsa") or {}
        gaps = ", ".join([*(lsa.get("missing_rates") or []), *(lsa.get("missing_prices") or [])]) or "some of its lines"
        lack = f"the task's LSA has no price for {gaps}, so its {fmt_num(cost['amount'])} leaves that out"
        if prev.get("planned_cost") is not None:
            planned = _source(prev["planned_cost"], "analysis", f"From “{previous.name}”: {lack}.")
        else:
            planned = _source(cost["amount"], "task_partial", f"Only part of it: {lack}. Set the rate, or type the cost.")
    elif prev.get("planned_cost") is not None:
        planned = _source(prev["planned_cost"], "analysis", f"From “{previous.name}”.")
    elif cls.get("planned_cost") is not None:
        planned = _source(cls["planned_cost"], "class", f"From its class, {cls['class']}.")
    else:
        planned = _source(None, "missing", "The task has no cost yet: enter what a planned replacement costs, "
                                           "or set the task's cost (typed, or from its LSA).")
    unplanned = over.get("unplanned_cost")
    unplanned = (_source(unplanned, "typed", "Typed here.") if unplanned is not None
                 else failure_cost_of(m, mode, position, prev, previous, cls))
    inputs = {"planned_cost": planned, "unplanned_cost": unplanned}
    if life is None or not life.get("usable"):
        return {"inputs": inputs}
    if planned["value"] is None or unplanned["value"] is None:
        return {"inputs": inputs, "problem": (planned if planned["value"] is None else unplanned)["text"]}
    try:
        out = strategy.optimal_replacement(life["distribution_id"], life["params"], planned["value"],
                                           unplanned["value"], unit=life.get("unit") or None, extras=life.get("extras"))
    except StrategyError as exc:
        return {"inputs": inputs, "problem": str(exc)}
    sent = {"distribution_id": life["distribution_id"], "params": life["params"], "planned_cost": planned["value"],
            "unplanned_cost": unplanned["value"], "unit": life.get("unit") or None, "extras": life.get("extras")}
    if not out.get("beneficial") or out.get("optimal_time") is None:
        return {"inputs": inputs, "result": out, "sent": sent, "words": out.get("recommendation") or "",
                "use": None, "none": out.get("recommendation") or "No replacement age pays off."}
    clock = running_clock.for_position(m, position["id"])
    value, how = _to_task_unit(float(out["optimal_time"]), life.get("unit"), task["unit"], clock)
    if value is None:
        return {"inputs": inputs, "result": out, "sent": sent, "problem": how}
    use = round_down(value)
    span = out.get("optimal_time_range") or {}
    rng = None
    if span.get("lower") is not None and span.get("upper") is not None:
        lo, _ = _to_task_unit(float(span["lower"]), life.get("unit"), task["unit"], clock)
        hi, _ = _to_task_unit(float(span["upper"]), life.get("unit"), task["unit"], clock)
        if lo is not None and hi is not None:
            rng = {"lower": lo, "upper": hi, "unit": task["unit"], "level": span.get("level") or 0.9,
                   "note": out.get("optimal_time_range_note")}
    saving = out.get("savings") or 0
    words = (f"Replace every {_with_unit(use, task['unit'])}: the lowest long-run cost, {saving:.0%} below running "
             "to failure.")
    if rng:
        words += (f" Across the model's {rng['level']:.0%} parameter bounds the best age runs from "
                  f"{_with_unit(rng['lower'], task['unit'])} to {_with_unit(rng['upper'], task['unit'])}.")
    else:
        words += f" {out.get('optimal_time_range_note') or ''}".rstrip()
    return {"inputs": inputs, "result": out, "sent": sent, "words": words,
            "use": {"value": _plain(use), "unit": task["unit"]}, "range": rng, "converted": how or None,
            "exact": value}


def _clock_inputs(m, position_id, unit) -> dict:
    if not (running_clock.is_running_hours(unit) or running_clock.is_use(unit)):
        return {}
    clock = running_clock.for_position(m, position_id)
    return {"hours_per_day": clock.hours_per_day, "clock": clock.to_dict()}


def _task_time_unit(unit) -> Optional[str]:
    from backend.services.rcm_intervals import TASK_UNIT

    key = normalize_unit(unit)
    return TASK_UNIT.get(key)


def _pf(m, mode, position, task, previous, over: dict) -> dict:
    """Half the P-F interval (or the net P-F interval) for one mode."""
    from backend.services import rcm_intervals

    prev = (previous.inputs or {}) if previous is not None and previous.kind == "on_condition_interval" else {}
    pf = over.get("pf_interval")
    if pf is not None:
        pf_in = _source(pf, "typed", "Typed here.")
        pf_unit = over.get("pf_unit") or prev.get("pf_unit") or task["unit"] or "hours"
    elif prev.get("pf_interval") is not None:
        pf_in = _source(prev["pf_interval"], "analysis", f"From “{previous.name}”, saved before.")
        pf_unit = over.get("pf_unit") or prev.get("pf_unit") or task["unit"]
    else:
        pf_in = _source(None, "missing", "Enter the P-F interval: how long from the first sign you can detect (a crack, "
                                         "a noise, a rise in temperature) to the failure.")
        pf_unit = over.get("pf_unit") or task["unit"] or "hours"
    act = over.get("act_time") if over.get("act_time") is not None else prev.get("act_time")
    inputs = {"pf_interval": pf_in, "pf_unit": pf_unit, "act_time": _source(act, "typed" if over.get("act_time") is not None
                                                                              else "analysis" if act is not None else "none",
                                                                              "From finding the warning to the fix being done.")}
    if pf_in["value"] is None:
        return {"inputs": inputs, "problem": pf_in["text"]}
    sent = {"pf_interval": pf_in["value"], "pf_unit": pf_unit, "act_time": act,
            "detection_probability": prev.get("detection_probability"),
            "unit": _task_time_unit(task["unit"]) if _task_time_unit(task["unit"]) else (task["unit"] or None),
            "current_interval": task.get("interval"), "current_unit": task["unit"] or None,
            **_clock_inputs(m, position["id"], pf_unit)}
    sent = {k: v for k, v in sent.items() if v is not None}
    try:
        out = rcm_intervals.on_condition_interval(**sent)
    except StrategyError as exc:
        return {"inputs": inputs, "problem": str(exc)}
    rec = out.get("recommended") or {}
    if not rec.get("value"):
        return {"inputs": inputs, "result": out, "sent": sent, "words": out.get("summary") or "", "use": None,
                "none": out.get("summary") or "No check interval."}
    return {"inputs": inputs, "result": out, "sent": sent, "words": out.get("summary") or "",
            "use": {"value": _plain(float(rec["value"])), "unit": rec.get("unit") or task["unit"]},
            "range": None, "range_note": "No range: the P-F interval is a figure you give, not a fitted model."}


def _ff(m, mode, position, task, life, previous, over: dict) -> dict:
    """The longest test interval that meets a target unavailability, for one mode."""
    from backend.services import rcm_intervals

    prev = (previous.inputs or {}) if previous is not None and previous.kind == "failure_finding_interval" else {}
    target = over.get("target_unavailability")
    if target is not None:
        t_in = _source(target, "typed", "Typed here.")
    elif prev.get("target_unavailability") is not None:
        t_in = _source(prev["target_unavailability"], "analysis", f"From “{previous.name}”, saved before.")
    else:
        t_in = _source(DEFAULT_TARGET, "assumed", "Assumed: failed when needed at most 1 time in 100, a common "
                                                  "starting point. Change it to the target your risk needs.")
    inputs = {"target_unavailability": t_in}
    if life is None or not life.get("usable"):
        return {"inputs": inputs}
    sent = {"distribution_id": life["distribution_id"], "params": [{k: p[k] for k in ("name", "value")} for p in life["params"]],
            "extras": life.get("extras"), "model_unit": life.get("unit") or None,
            "target_unavailability": t_in["value"], "unit": _task_time_unit(task["unit"]) or None,
            "current_interval": task.get("interval"), "current_unit": task["unit"] or None,
            **_clock_inputs(m, position["id"], life.get("unit"))}
    sent = {k: v for k, v in sent.items() if v is not None}
    try:
        out = rcm_intervals.failure_finding_interval(**sent)
    except StrategyError as exc:
        return {"inputs": inputs, "problem": str(exc)}
    rec = out.get("recommended") or {}
    if not rec.get("value"):
        return {"inputs": inputs, "result": out, "sent": sent, "words": out.get("summary") or "", "use": None,
                "none": out.get("summary") or "No test interval meets the target."}
    return {"inputs": inputs, "result": out, "sent": sent, "words": out.get("summary") or "",
            "use": {"value": _plain(float(rec["value"])), "unit": rec.get("unit") or task["unit"]}, "range": None,
            "range_note": "No range: the test interval is worked out at the model's estimate."}


NOTHING = {
    "rtf": "Run to failure: there's no interval to optimise. The failure is left to happen and fixed when it does.",
    None: "Routine work (lubricate, clean, adjust): its interval isn't set by a failure model, so there's nothing "
          "to optimise here. Make it a replace-at-age, condition check or failure-finding task to work one out.",
    "redesign": "A redesign isn't done at an interval: there's nothing to optimise.",
}


def _partial_restoration(task: dict, mode_id: str) -> str | None:
    """Why the replacement age can't set this task: it leaves the item less than new for this mode
    (restoration.py), or None when it renews it."""
    r = task.get("restoration") or {}
    mine = next((x for x in r.get("by_mode") or [] if x.get("failure_mode_id") == mode_id), None)
    value = (mine or {}).get("restoration") if mine else r.get("restoration")
    if not value or value.get("kind") in (None, "as_new"):
        return None
    words = (mine or {}).get("words") or r.get("words") or "it restores only part of the age"
    return (f"This task doesn't leave the item as new ({words[0].lower() + words[1:]}), and the replacement age "
            "assumes it does, so it can't set this interval. Its effect shows in a repairable RBD's maintenance "
            "plan instead; make it a replacement (as new) to optimise it here.")


def _moved(previous, life) -> bool:
    """Whether the model the saved analysis rested on has been refitted since."""
    ref = ((getattr(previous, "inputs", None) or {}).get("optimise") or {}).get("model") or {}
    return bool(ref.get("fingerprint") and life and life.get("id") == ref.get("id")
                and fingerprint(life) != ref["fingerprint"])


def optimise(m, db, owners, hidden, task_id: str, *, failure_mode_id: str | None = None, model: dict | None = None,
             planned_cost=None, unplanned_cost=None, pf_interval=None, pf_unit=None, act_time=None,
             target_unavailability=None) -> dict:
    """How often to do task ``task_id``, worked out for each failure mode it serves (or only
    ``failure_mode_id``). ``model`` ({type, id}) and the costs, P-F interval and target change what
    it starts from (for that one mode, with ``failure_mode_id``). Reads only."""
    from backend.maintenance.position_models import fetcher

    over = {"planned_cost": _number(planned_cost, "The planned cost"),
            "unplanned_cost": _number(unplanned_cost, "The unplanned cost"),
            "pf_interval": _number(pf_interval, "The P-F interval"), "pf_unit": pf_unit or None,
            "act_time": _number(act_time, "The time needed to act"),
            "target_unavailability": _number(target_unavailability, "The target unavailability")}
    if over["target_unavailability"] is not None and not 0 < over["target_unavailability"] < 1:
        raise OptimiseError("The target unavailability is a chance between 0 and 1 (0.01 for 1%).")
    task = _task_info(m, task_id)
    fetch = fetcher(db, owners, hidden)
    modes = task["modes"]
    if failure_mode_id:
        modes = [x for x in modes if x["id"] == failure_mode_id]
        if not modes:
            raise OptimiseError("That failure mode isn't one this task prevents (failure_mode_id: one of its modes).")
    out_modes = []
    for brief in modes:
        mode = m.rcm_mode(brief["id"])
        _, position = m._live_mode(brief["id"])
        kind = _kind_for(task, mode)
        calc = CALCULATORS.get(kind)
        row: dict[str, Any] = {"id": mode["id"], "text": mode.get("text") or "", "position_id": position["id"],
                               "position_name": position.get("name"), "kind": kind,
                               "calculator": calc["key"] if calc else None}
        if not calc:
            row["nothing"] = NOTHING.get(kind, NOTHING[None])
            out_modes.append(row)
            continue
        given = model if (failure_mode_id or len(modes) == 1) else None
        life, previous, choices = _mode_model(m, fetch, mode, position, task["id"], given)
        row.update({"model": life, "choices": choices,
                    "evidence": {"id": previous.id, "name": previous.name, "kind": previous.kind} if previous else None,
                    "moved": _moved(previous, life)})
        partial = _partial_restoration(task, mode["id"]) if calc["key"] == "replacement" else None
        if partial:
            # The replacement age assumes each task leaves it as new: a task that restores only part of
            # the age isn't one it can set (a wrong number would be worse than none).
            row["nothing"] = partial
            row["calculator"] = None
        elif calc["key"] == "replacement":
            row.update(_replacement(m, mode, position, task, life, previous, over))
        elif calc["key"] == "pf":
            row.update(_pf(m, mode, position, task, previous, over))
        else:
            row.update(_ff(m, mode, position, task, life, previous, over))
        if calc["key"] != "pf" and (life is None or not life.get("usable")):
            row["no_model"] = (life or {}).get("why") or (
                "No life model is linked to this failure mode. Link one (one of this position's models, or one "
                "from your models) or fit one from a dataset, and the interval is worked out from it.")
        out_modes.append(row)
    return {"task": {k: task[k] for k in ("id", "name", "interval", "unit", "outcome", "position_id", "position_name")},
            "modes": out_modes}


# ---- using the answer ------------------------------------------------------------------

def _analysis_inputs(row: dict, task: dict, life: dict | None) -> dict:
    """What the saved analysis keeps: the calculator's own inputs (so it recomputes the same), and
    ``optimise``, the task, mode and model it was worked out for."""
    calc = row["calculator"]
    sent = dict(row.get("sent") or {})
    model_ref = None
    if life and life.get("id"):
        model_ref = {"type": life["type"], "id": life["id"], "name": life["name"], "fingerprint": fingerprint(life)}
    extra = {"optimise": {"task_id": task["id"], "task_name": task["name"], "failure_mode_id": row["id"],
                          "position_id": row["position_id"], "model": model_ref, "use": row["use"]},
             "position_id": row["position_id"]}
    if life and life.get("link_id"):
        extra["position_link_id"] = life["link_id"]  # its model row on the Modelling tab shows it under Strategy
    if calc == "replacement":
        return {k: v for k, v in sent.items() if v is not None} | extra
    return sent | extra


def use(m, db, owners, hidden, owner_id: str, task_id: str, failure_mode_id: str | None = None, **given) -> dict:
    """Optimise's "Use every N": the task takes the interval worked out for its failure mode
    (``failure_mode_id``; may be left out when it serves one), the calculation is saved as a strategy
    analysis and linked as the mode's evidence (for its task), and one line on it goes in the mode's
    notes. Returns what changed, with the evidence check's status now."""
    from backend.maintenance import rcm_decisions
    from backend.maintenance.service import Invalid
    from backend.services import strategy_store

    task = _task_info(m, task_id)
    if not failure_mode_id:
        if len(task["modes"]) != 1:
            raise OptimiseError("This task prevents several failure modes: name the one whose interval it takes "
                                "(failure_mode_id).")
        failure_mode_id = task["modes"][0]["id"]
    read = optimise(m, db, owners, hidden, task_id, failure_mode_id=failure_mode_id, **given)
    row = read["modes"][0]
    if not row.get("calculator"):
        raise OptimiseError(row.get("nothing") or "There's nothing to optimise for this task.")
    if not row.get("use"):
        raise OptimiseError(row.get("problem") or row.get("no_model") or row.get("none") or "No interval was worked out.")
    calc = CALCULATORS[row["kind"]]
    life = row.get("model")
    m.update_task(task_id, interval=row["use"]["value"], unit=row["use"]["unit"])
    mode = m.rcm_mode(failure_mode_id)
    text = str(mode.get("text") or "Failure mode").strip()
    word = calc["word"]
    name = f"{text}: {word}" if len(text) + len(word) + 2 <= 120 else f"{text[:120 - len(word) - 3]}…: {word}"
    try:
        saved = strategy_store.save_analysis(db, name, calc["analysis"], _analysis_inputs(row, task, life), owner_id)
    except StrategyError as exc:
        raise OptimiseError(str(exc)) from None
    on = date.fromisoformat(str(m.today())[:10])
    based = f" on “{life['name']}”" if life and life.get("name") else ""
    line = (f"Interval from Optimise ({on.day} {on.strftime('%b %Y')}){based}: every "
            f"{_with_unit(row['use']['value'], row['use']['unit'])}. {row.get('words') or ''}").strip()
    notes = str(mode.get("notes") or "").rstrip()
    m.update_failure_mode(failure_mode_id, notes=f"{notes}\n\n{line}" if notes else line)
    linked, why = _link_evidence(m, failure_mode_id, task_id, {"type": "strategy_analysis", "id": saved.id}, Invalid)
    status = None
    if linked:
        decision = m.rcm_mode(failure_mode_id).get("decision")
        if decision:
            from backend.maintenance.rcm_decisions import evidence_fetcher

            clock = running_clock.for_position(m, row["position_id"])
            status = rcm_decisions.resolve_decision(decision, evidence_fetcher(db, owners, hidden), clock).get("status")
    return {"task_id": task_id, "failure_mode_id": failure_mode_id, "interval": row["use"]["value"],
            "unit": row["use"]["unit"], "words": row.get("words"), "notes_added": line,
            "analysis": {"id": saved.id, "name": saved.name, "kind": saved.kind},
            "model": {k: life.get(k) for k in ("type", "id", "name", "path")} if life and life.get("id") else None,
            "evidence_linked": linked, **({"evidence_not_linked": why} if why else {}), "evidence_status": status}


def _link_evidence(m, mode_id: str, task_id: str, evidence: dict, Invalid) -> tuple[bool, str | None]:
    """Make ``evidence`` the mode's evidence for this task (replacing what it had: the user chose
    to use this answer). A combination's member takes it on the member."""
    fm = m.rcm_mode(mode_id)
    decision = fm.get("decision")
    if not decision:
        return False, "The failure mode has no RCM decision yet, so there's no evidence to link: decide it on the RCM tab."
    members = decision.get("outcomes") or []
    if members:
        if not any(o.get("task_id") == task_id for o in members):
            return False, "The task isn't one of this failure mode's decided tasks."
        body = {"outcome": members[0]["outcome"], "evidence": None,
                "outcomes": [{"outcome": o["outcome"]} | ({"task_id": o["task_id"]} if o.get("task_id") else {})
                             | ({"evidence": evidence} if o.get("task_id") == task_id
                                else {"evidence": o["evidence"]} if o.get("evidence") else {})
                             | ({"on_found": o["on_found"]} if o.get("on_found") else {})
                             for o in members]}
        if decision.get("rtf_basis"):
            body["rtf_basis"] = decision["rtf_basis"]
        try:
            m.decide_failure_mode(mode_id, decision=body)
        except Invalid as err:
            return False, str(err)
        return True, None
    if decision.get("task_id") != task_id:
        return False, "The failure mode's decision is for another task."
    m.relink_evidence(mode_id, evidence)
    return True, None


# ---- both places: what a model sets, and what a task rests on -------------------------

def _analyses_for(db, owners, query: dict) -> list:
    from backend.schema import StrategyAnalysis
    from backend.services import access
    from backend.db import from_doc

    q = {"owner_id": {"$in": access.owner_in(owners)}, **query}
    return [from_doc(StrategyAnalysis, d) for d in db.strategy_analyses.find(q).sort("created_at", -1)]


def _still_evidence(m, analysis) -> dict | None:
    """The task and mode an Optimise analysis set, while it's still that mode's evidence for the
    task and the task is live: {task, mode}; else None."""
    o = (analysis.inputs or {}).get("optimise") or {}
    try:
        mode = m.rcm_mode(o.get("failure_mode_id"))
    except Exception:  # noqa: BLE001 - a mode that's gone
        return None
    ev = _evidence_of(mode.get("decision"), o.get("task_id"))
    if ev.get("type") != "strategy_analysis" or ev.get("id") != analysis.id:
        return None
    task = next((t for t in mode.get("tasks") or [] if t.get("id") == o.get("task_id")), None)
    if task is None:
        return None
    return {"task": task, "mode": mode}


def _root_of(m, position_id):
    """The top of the asset a position is in (the Explorer opens an asset on its own: ?root=)."""
    if not position_id:
        return None
    try:
        up = m._ancestor_ids(position_id)
    except Exception:  # noqa: BLE001 - a position that's gone
        return None
    return up[-1] if up else position_id


def tasks_set_by(m, db, owners, hidden, model_ids: list[str]) -> dict:
    """{model id: [{task_id, name, interval, unit, failure_mode_id, mode, position_id, analysis_id,
    moved}]}: the tasks whose interval an Optimise rests on each model (while it is still their
    evidence)."""
    from backend.maintenance.position_models import fetcher

    ids = [x for x in dict.fromkeys(model_ids) if x]
    if not ids:
        return {}
    fetch = fetcher(db, owners, hidden)
    out: dict = {}
    for a in _analyses_for(db, owners, {"inputs.optimise.model.id": {"$in": ids}}):
        if a.id in hidden:
            continue
        got = _still_evidence(m, a)
        if not got:
            continue
        o = a.inputs["optimise"]
        ref = o.get("model") or {}
        doc = fetch(ref.get("type"), ref.get("id"))
        life = life_of(ref["type"], doc) if doc is not None else None
        t = got["task"]
        out.setdefault(ref["id"], []).append({
            "task_id": t["id"], "name": t.get("name") or o.get("task_name"), "interval": t.get("interval"),
            "unit": t.get("unit"), "failure_mode_id": o.get("failure_mode_id"), "mode": got["mode"].get("text"),
            "position_id": o.get("position_id"), "root": _root_of(m, o.get("position_id")), "analysis_id": a.id,
            "moved": bool(life and ref.get("fingerprint") and fingerprint(life) != ref["fingerprint"])})
    return out


def basis(m, db, owners, hidden, task_id: str) -> dict:
    """What a task's interval rests on, mode by mode: the Optimise analysis linked as evidence, the
    model it used and whether that model has been refitted since (its optimum may have moved)."""
    from backend.maintenance.position_models import fetcher

    task = _task_info(m, task_id)
    fetch = fetcher(db, owners, hidden)
    rows = []
    for brief in task["modes"]:
        mode = m.rcm_mode(brief["id"])
        ev = _evidence_of(mode.get("decision"), task_id)
        a = fetch("strategy_analysis", ev.get("id")) if ev.get("type") == "strategy_analysis" else None
        o = ((a.inputs or {}).get("optimise") or {}) if a is not None else {}
        if not o or o.get("task_id") != task_id:
            continue
        ref = o.get("model") or {}
        doc = fetch(ref.get("type"), ref.get("id")) if ref.get("id") else None
        life = life_of(ref["type"], doc) if doc is not None else None
        rows.append({"failure_mode_id": brief["id"], "mode": brief.get("text"),
                     "analysis": {"id": a.id, "name": a.name, "kind": a.kind,
                                  "created_at": a.created_at.isoformat() if getattr(a, "created_at", None) else None},
                     "use": o.get("use"),
                     "model": {"type": ref.get("type"), "id": ref.get("id"), "name": (doc.name if doc is not None else ref.get("name")),
                               "path": MODEL_PATH.get(ref.get("type"), "/models/m/{}").format(ref.get("id")),
                               "gone": doc is None} if ref.get("id") else None,
                     "moved": bool(life and ref.get("fingerprint") and fingerprint(life) != ref["fingerprint"])})
    return {"task_id": task_id, "rests_on": rows}


def refitted_note(analysis, fetch) -> str | None:
    """For the RCM evidence check: a line when the model an Optimise analysis rested on has been
    refitted since (its optimum may have moved), else None. The status is left as it is."""
    ref = ((getattr(analysis, "inputs", None) or {}).get("optimise") or {}).get("model") or {}
    if not ref.get("fingerprint") or ref.get("type") not in LIFE_TYPES:
        return None
    doc = fetch(ref["type"], ref["id"])
    if doc is None:
        return None
    if fingerprint(life_of(ref["type"], doc)) == ref["fingerprint"]:
        return None
    return f"“{doc.name}” has been refitted since this was worked out: its optimum may have moved. Re-optimise the task."
