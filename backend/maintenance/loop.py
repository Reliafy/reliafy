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
import math

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
    # A row whose life is a range (dates known only roughly) counts while its
    # longest life is above 0.
    rows = [r for r in data["rows"] if (r["xr"] if r["c"] == 2 else r["x"]) > 0]
    failures = sum(1 for r in rows if r["c"] != 1)
    # A constant failure rate has one parameter: one failure (and the time in
    # service around it) is enough. Every other distribution needs two.
    needed = 1 if distribution == "exponential" else MIN_FAILURES
    if failures < needed:
        hint = (" With one failure, fit distribution 'exponential' (a constant failure rate) until more "
                "are on record." if failures == 1 else "")
        raise Invalid(f"{data['position_class']} has {failures} failure{'s' if failures != 1 else ''} "
                      f"on record; a {distribution} model needs at least {needed}.{hint}")
    buf = io.StringIO()
    if any(r["c"] == 2 for r in rows):
        pd.DataFrame(_interval_rows(rows), columns=["shortest", "longest", "censored"]).to_csv(buf, index=False)
        mapping = {"xl": "shortest", "xr": "longest", "c": "censored"}
    else:
        pd.DataFrame({"days": [r["x"] for r in rows], "censored": [r["c"] for r in rows]}).to_csv(buf, index=False)
        mapping = {"x": "days", "c": "censored"}
    name = data["position_class"]
    dataset = datasets_service.create_dataset(db, f"{name}: maintenance life data.csv",
                                              buf.getvalue().encode(), m.org)
    model = models_service.save_model(db, f"{name} (from maintenance records)", dataset, distribution,
                                      mapping, [], None, "days", owner_id=m.org)
    params = [{"name": p["name"], "value": p["value"]} for p in model.results.get("params") or []]
    m._emit("class.model_fitted", {
        "id": class_id(m.org, name), "name": name, "model_id": model.id, "distribution": model.distribution_id,
        "params": params, "extras": (model.results.get("options") or None), "unit": "days",
        "fitted_on": m.today(), "failures": failures, "suspensions": len(rows) - failures,
    })
    return {**m.position_class(name), "proposals": propose(m, name), "uncertain": data["uncertain"]}


def _interval_rows(rows: list[dict]) -> list[tuple]:
    """Life data as SurPyval's interval form (shortest, longest, censoring): an exact
    life is the same at both ends; a failure known to lie in a range is interval
    censored (2), or left censored (-1, failed by the longest) when the range starts
    at 0; anything else is censored at the shortest life it surely reached (1)."""
    out = []
    for r in rows:
        if r["c"] == 2:
            out.append((r["xr"], r["xr"], -1) if r["xl"] <= 0 else (r["xl"], r["xr"], 2))
        else:
            out.append((r["x"], r["x"], r["c"]))
    return out


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

    node = m.s.node(m.org, class_id(m.org, position_class))
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
                "reason": reason, "made_on": m.today(),
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


def economics(m: Maintenance, position_class: str, interval: float | None = None, unit: str = "months",
              horizon_years: float = 10, discount_rate: float = 0.07) -> dict:
    """What the class's replacement plan costs a year, against the best interval and
    running to failure, from its life model and costs: and, given an interval, what that
    would cost (a what-if). Each with its net present cost over the horizon."""
    import numpy as np

    from backend.services import strategy as strategy_service

    node = m.s.node(m.org, class_id(m.org, position_class))
    if not node or not node.get("model"):
        raise Invalid(f"Fit a life model for {position_class} first.")
    if node.get("planned_cost") is None or node.get("failure_cost") is None:
        raise Invalid(f"Set {position_class}'s costs (a planned replacement and a failure) first.")
    if not 0 <= float(discount_rate) < 1 or not 0 < float(horizon_years) <= 100:
        raise Invalid("The discount rate is 0 to 1 (e.g. 0.07) and the horizon 1 to 100 years.")
    if interval is not None and not (math.isfinite(float(interval)) and 0 < float(interval) <= 1e6):
        raise Invalid("A what-if interval is a positive number of days, weeks, months or years.")
    model = node["model"]
    res = strategy_service.optimal_replacement(model["distribution"], model["params"], node["planned_cost"],
                                               node["failure_cost"], "days", model.get("extras"))
    t, rate = np.asarray(res["curve"]["t"], float), np.asarray(res["curve"]["cost_rate"], float)
    ok = np.isfinite(rate)
    t, rate = t[ok], rate[ok]

    def per_day(days: float) -> float:
        return float(np.interp(days, t, rate, right=res["run_to_failure_cost_rate"]))

    r, h = float(discount_rate), float(horizon_years)
    annuity = h if r == 0 else (1 - (1 + r) ** -h) / r

    def option(label, per_day_cost, n, interval_text):
        yearly = per_day_cost * 365.25 * n
        return {"plan": label, "interval": interval_text, "per_year": round(yearly, 2),
                "net_present_cost": round(yearly * annuity, 2)}

    positions = [p for p in m.s.nodes(m.org, "Position")
                 if (p.get("position_class") or "").strip().lower() == position_class.strip().lower()
                 and not p.get("retired")]
    n = len(positions)
    tasks = [t_ for p in positions for t_ in m._tasks_on(p["id"])
             if t_.get("outcome") == "fixed_interval" and t_["unit"] in DAYS_PER]
    out = {"position_class": node["name"], "positions": n, "horizon_years": h, "discount_rate": r,
           "options": []}
    if tasks:
        current = sum(per_day(t_["interval"] * DAYS_PER[t_["unit"]]) for t_ in tasks) + \
            res["run_to_failure_cost_rate"] * (n - len({m.s.out(m.org, t_["id"], "ON")[0]["id"] for t_ in tasks}))
        intervals = sorted({f"{t_['interval']:g} {t_['unit']}" for t_ in tasks})
        out["options"].append(option("current plan", current, 1, ", ".join(intervals)))
    if res.get("beneficial") and res.get("optimal_time"):
        best = float(res["optimal_time"])
        unit_best = unit if unit in DAYS_PER else "months"
        out["options"].append(option("best interval", per_day(best), n, f"{_in_unit(best, unit_best):g} {unit_best}"))
    out["options"].append(option("run to failure", res["run_to_failure_cost_rate"], n, "replace on failure"))
    if interval is not None:
        if unit not in DAYS_PER or float(interval) <= 0:
            raise Invalid("A what-if interval is a positive number of days, weeks, months or years.")
        out["options"].append(option("what if", per_day(float(interval) * DAYS_PER[unit]), n,
                                     f"{float(interval):g} {unit}"))
    cheapest = min(out["options"], key=lambda o: o["per_year"])
    out["cheapest"] = cheapest["plan"]
    out["note"] = (f"Long-run cost per year across {n} position{'s' if n != 1 else ''}, from the "
                   f"{model['distribution']} model and the costs; net present cost over {h:g} years at "
                   f"{r:.0%}. Treat it as rough with few failures on record ({model['failures']}).")
    return out
