"""Closing the loop: the work done refits the life models, and the models
propose the plan.

* :func:`fit_class_model` pools every fitment of a class of position (one row
  each: days in service, failed or not), fits a life distribution with
  SurPyval, saves it to the workspace's models (so it's a normal Reliafy model:
  calculators, RBD blocks), and records it on the class.
* :func:`propose` works out, for every task on that class's positions, the
  interval the model and the class's costs support: optimal age replacement
  for a scheduled replacement, the failure-finding interval for a hidden
  failure's check. A proposal records the current and proposed interval and
  why; nothing changes until someone accepts it.
* :func:`refit_stale` (the daily run) refits classes with failures the model
  hasn't seen, and proposes again.
"""

from __future__ import annotations

import io
from datetime import date

import pandas as pd

from backend.maintenance.service import Invalid, Maintenance, NotFound, class_id
from backend.maintenance.store import new_id

MIN_FAILURES = 2  # to fit at all
FEW_FAILURES = 5  # below this, say the estimate is rough
CHANGE_THRESHOLD = 0.10  # propose only when the interval moves by more than 10%
DAYS_PER = {"days": 1.0, "weeks": 7.0, "months": 30.4375, "years": 365.25}


def _in_unit(days: float, unit: str) -> float:
    value = days / DAYS_PER[unit]
    return round(value, 1) if value < 10 else round(value)


def fit_class_model(m: Maintenance, db, position_class: str, distribution: str = "weibull") -> dict:
    """Fit and save a life model for a class from its pooled fitments."""
    from backend.services import datasets as datasets_service
    from backend.services import models as models_service

    data = m.class_life_data(position_class)
    rows = [r for r in data["rows"] if r["x"] > 0]
    failures = sum(1 for r in rows if r["c"] == 0)
    if failures < MIN_FAILURES:
        raise Invalid(f"{data['position_class']} has {failures} failure{'s' if failures != 1 else ''} "
                      f"on record; a life model needs at least {MIN_FAILURES}.")
    buf = io.StringIO()
    pd.DataFrame({"days": [r["x"] for r in rows], "censored": [r["c"] for r in rows]}).to_csv(buf, index=False)
    name = data["position_class"]
    dataset = datasets_service.create_dataset(db, f"{name}: maintenance life data.csv",
                                              buf.getvalue().encode(), m.org)
    model = models_service.save_model(db, f"{name} (from maintenance records)", dataset, distribution,
                                      {"x": "days", "c": "censored"}, [], None, "days", owner_id=m.org)
    params = [{"name": p["name"], "value": p["value"]} for p in model.results.get("params") or []]
    m._emit("class.model_fitted", {
        "id": class_id(name), "name": name, "model_id": model.id, "distribution": model.distribution_id,
        "params": params, "extras": (model.results.get("options") or None), "unit": "days",
        "fitted_on": date.today().isoformat(), "failures": failures, "suspensions": len(rows) - failures,
    })
    return {**m.position_class(name), "proposals": propose(m, name)}


def _describe(model: dict) -> str:
    params = {p["name"]: p["value"] for p in model.get("params") or []}
    dist = model.get("distribution", "")
    text = f"{dist.capitalize()} fit to {model['failures'] + model['suspensions']} fitments " \
           f"({model['failures']} failures, {model['suspensions']} removed or still in service)"
    if dist == "weibull" and "beta" in params:
        beta = params["beta"]
        shape = "wear-out" if beta > 1.2 else "random failures" if beta >= 0.8 else "early-life failures"
        text += f": shape β {beta:.2f} ({shape}), characteristic life {params.get('alpha', 0):,.0f} days"
    if model["failures"] < FEW_FAILURES:
        text += ". Few failures yet, so treat this as rough"
    return text


def propose(m: Maintenance, position_class: str) -> list[dict]:
    """Proposals for every task on the class's positions that the model and costs
    support changing. Returns the proposals made now."""
    from backend.services import strategy as strategy_service

    node = m.s.node(m.org, class_id(position_class))
    if not node or not node.get("model"):
        raise Invalid(f"Fit a life model for {position_class} first.")
    model = node["model"]
    made = []
    for position in m.s.nodes(m.org, "Position"):
        if (position.get("position_class") or "").strip().lower() != position_class.strip().lower() \
                or position.get("retired"):
            continue
        for task in m._tasks_on(position["id"]):
            unit = task["unit"]
            if unit not in DAYS_PER:
                continue  # by use: needs a model in that unit (not yet)
            proposal = None
            if task.get("outcome") == "fixed_interval" and node.get("planned_cost") is not None \
                    and node.get("failure_cost") is not None:
                try:
                    res = strategy_service.optimal_replacement(
                        model["distribution"], model["params"], node["planned_cost"], node["failure_cost"],
                        "days", model.get("extras"))
                except Exception:  # noqa: BLE001 - a model the calculator can't use proposes nothing
                    continue
                if res.get("beneficial") and res.get("optimal_time"):
                    days = float(res["optimal_time"])
                    saving = res.get("savings") or 0
                    proposal = ("interval", _in_unit(days, unit), unit,
                                f"{_describe(model)}. With a planned replacement at {node['planned_cost']:,.0f} "
                                f"and a failure at {node['failure_cost']:,.0f}, replacing every "
                                f"{_in_unit(days, unit):g} {unit} has the lowest long-run cost, "
                                f"{saving:.0%} below running to failure.")
                else:
                    proposal = ("retire", None, unit,
                                f"{_describe(model)}. With these costs no replacement age beats replacing "
                                f"on failure: there's no wear-out to get ahead of. Consider running to failure.")
            elif task.get("outcome") == "failure_finding" and node.get("availability_target"):
                try:
                    res = strategy_service.failure_finding(model["distribution"], model["params"],
                                                           node["availability_target"], "days",
                                                           model.get("extras"))
                except Exception:  # noqa: BLE001
                    continue
                days = float(res.get("interval") or 0)
                if days > 0:
                    proposal = ("interval", _in_unit(days, unit), unit,
                                f"{_describe(model)}. To keep the protective function available "
                                f"{node['availability_target']:.1%} of the time, check it every "
                                f"{_in_unit(days, unit):g} {unit} (2 × (1 − A) × MTTF).")
            if proposal is None:
                continue
            kind, interval, unit, reason = proposal
            if kind == "interval" and abs(interval - task["interval"]) <= CHANGE_THRESHOLD * task["interval"]:
                continue  # close enough already
            pending = next((p for p in m.s.inn(m.org, task["id"], "ABOUT")
                            if p["label"] == "Proposal" and p.get("status") == "pending"), None)
            if pending and pending.get("kind") == kind and (pending.get("proposed") or {}).get("interval") == interval:
                continue  # already proposed
            pid = new_id()
            m._emit("proposal.made", {
                "id": pid, "task_id": task["id"], "kind": kind, "class_name": node["name"],
                "current": {"interval": task["interval"], "unit": task["unit"]},
                "proposed": {"interval": interval, "unit": unit} if interval is not None else None,
                "reason": reason, "made_on": date.today().isoformat(),
            })
            made.append(next(p for p in m.proposals("pending") if p["id"] == pid))
    return made


def refit_stale(m: Maintenance, db) -> list[str]:
    """Refit every class whose model hasn't seen all its failures (and has costs or
    a target to propose against). Returns the classes refitted."""
    done = []
    for c in m.position_classes():
        model = c.get("model")
        if not model or c["failures"] <= model.get("failures", 0):
            continue
        try:
            fit_class_model(m, db, c["position_class"], model.get("distribution") or "weibull")
            done.append(c["position_class"])
        except (Invalid, NotFound):
            continue
    return done
