"""Closing the loop: the work done refits the non-repairable models, and the models
propose the plan.

* :func:`fit_class_model` pools every fitment of a class of position (one row
  each: days in service, or the use its position's counter counted, such as
  flight hours; failed or not), fits a life distribution with SurPyval, saves
  it to the workspace's models (so it's a normal Reliafy model: calculators,
  RBD blocks), and records it on the class with its unit.
* :func:`propose` works out, for every task on that class's positions, the
  interval the model and the class's costs support: optimal age replacement
  for a scheduled replacement, the failure-finding interval for a hidden
  failure's check, for tasks in the model's unit (on the calendar for a model
  in days, by use in the model's unit of use). A proposal records the current and proposed interval and
  why; nothing changes until someone accepts it.
* :func:`refit_stale` (the daily run) refits classes with failures the model
  hasn't seen, and proposes again.
"""

from __future__ import annotations

import io
import math

import pandas as pd

from backend.maintenance import service as svc
from backend.maintenance.service import Invalid, Maintenance, NotFound, class_id
from backend.maintenance.store import new_id

MIN_FAILURES = 2  # to fit at all
FEW_FAILURES = 5  # below this, say the estimate is rough
CHANGE_THRESHOLD = 0.10  # propose only when the interval moves by more than 10%
DAYS_PER = {"days": 1.0, "weeks": 7.0, "months": 30.4375, "years": 365.25}


def _in_unit(days: float, unit: str) -> float:
    value = days / DAYS_PER[unit]
    return round(value, 1) if value < 10 else round(value)


def _rounded(value: float) -> float:
    """An interval in a unit of use, rounded as the calendar's are."""
    return round(value, 1) if value < 10 else round(value)


def model_unit(model: dict | None) -> str:
    """A class model's unit: days for one on the calendar (and the models saved before
    units of use), else its unit of use (hours, km, cycles)."""
    unit = svc._norm_unit((model or {}).get("unit")) or "days"
    return "days" if unit in svc.CALENDAR_UNITS else unit


def fit_class_model(m: Maintenance, db, position_class: str, distribution: str = "weibull",
                    unit: str | None = None) -> dict:
    """Fit and save a non-repairable model for a class from its pooled fitments. ``unit``:
    days (lives on the calendar) or a counter's unit of use (hours, km, cycles: lives
    from the positions' counters); by default the unit of the class's model so far, else
    days."""
    from backend.services import datasets as datasets_service
    from backend.services import models as models_service

    if unit is None or str(unit).strip() == "":
        try:
            node = m.s.node(m.org, class_id(m.org, m._class_name(position_class))) or {}
        except (Invalid, NotFound):
            node = {}  # class_life_data says what's wrong
        unit = model_unit(node.get("model"))
    use = m._life_unit(unit)
    data = m.class_life_data(position_class, use)
    unit = use or "days"
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
        counted = f" counted in {unit}" if use else ""
        left_out = sum(1 for r in data.get("excluded") or [] if r["status"] == "failed")
        if left_out:
            hint += (f" {left_out} more failure{'s' if left_out != 1 else ''} can't be counted in {unit} yet "
                     "(see class_life_data's excluded: usually a counter reading after the failure).")
        raise Invalid(f"{data['position_class']} has {failures} failure{'s' if failures != 1 else ''}{counted} "
                      f"on record; a {distribution} model needs at least {needed}.{hint}")
    buf = io.StringIO()
    if any(r["c"] == 2 for r in rows):
        pd.DataFrame(_interval_rows(rows), columns=["shortest", "longest", "censored"]).to_csv(buf, index=False)
        mapping = {"xl": "shortest", "xr": "longest", "c": "censored"}
    else:
        pd.DataFrame({unit: [r["x"] for r in rows], "censored": [r["c"] for r in rows]}).to_csv(buf, index=False)
        mapping = {"x": unit, "c": "censored"}
    name = data["position_class"]
    in_unit = f" in {unit}" if use else ""
    dataset = datasets_service.create_dataset(db, f"{name}: maintenance life data{in_unit}.csv",
                                              buf.getvalue().encode(), m.org)
    model = models_service.save_model(db, f"{name} (from maintenance records{in_unit})", dataset, distribution,
                                      mapping, [], None, unit, owner_id=m.org)
    params = [{"name": p["name"], "value": p["value"]} for p in model.results.get("params") or []]
    m._emit("class.model_fitted", {
        "id": class_id(m.org, name), "name": name, "model_id": model.id, "distribution": model.distribution_id,
        "params": params, "extras": (model.results.get("options") or None), "unit": unit,
        "fitted_on": m.today(), "failures": failures, "suspensions": len(rows) - failures,
        # By use, failures the readings can't count yet aren't in the fit: the daily refit
        # waits for failures beyond those on record now, not for those to be counted.
        **({"failures_seen": m.position_class(name)["failures"]} if use else {}),
    })
    out = {**m.position_class(name), "proposals": propose(m, name), "uncertain": data["uncertain"]}
    if use:
        out |= {"unit": unit, "excluded": data["excluded"], "counters": data["counters"], "note": data["note"]}
    return out


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
        text += f": shape β {beta:.2f} ({shape}), characteristic life {params.get('alpha', 0):,.0f} " \
                f"{model_unit(model)}"
    if model["failures"] < FEW_FAILURES:
        text += ". Few failures yet, so treat this as rough"
    return text


def propose(m: Maintenance, position_class: str) -> list[dict]:
    """Proposals for every task on the class's positions that the model and costs
    support changing. Returns the proposals made now."""
    from backend.services import strategy as strategy_service

    node = m.s.node(m.org, class_id(m.org, position_class))
    if not node or not node.get("model"):
        raise Invalid(f"Fit a non-repairable model for {position_class} first.")
    model = node["model"]
    life_unit = model_unit(model)
    by_use = life_unit != "days"

    def in_task_unit(t: float, unit: str) -> float:
        return _rounded(t) if by_use else _in_unit(t, unit)

    made = []
    for position in m.s.nodes(m.org, "Position"):
        if (position.get("position_class") or "").strip().lower() != position_class.strip().lower() \
                or position.get("retired"):
            continue
        for task in m._tasks_on(position["id"]):
            unit = task["unit"]
            if by_use:
                if svc._norm_unit(unit) != life_unit:
                    continue  # a model by use proposes for tasks by that use only
            elif unit not in DAYS_PER:
                continue  # by use: needs a model in that unit (fit the class's model in it)
            proposal = None
            if task.get("outcome") == "fixed_interval" and node.get("planned_cost") is not None \
                    and node.get("failure_cost") is not None:
                try:
                    res = strategy_service.optimal_replacement(
                        model["distribution"], model["params"], node["planned_cost"], node["failure_cost"],
                        life_unit, model.get("extras"))
                except Exception:  # noqa: BLE001 - a model the calculator can't use proposes nothing
                    continue
                if res.get("beneficial") and res.get("optimal_time"):
                    best = float(res["optimal_time"])
                    saving = res.get("savings") or 0
                    proposal = ("interval", in_task_unit(best, unit), unit,
                                f"{_describe(model)}. With a planned replacement at {node['planned_cost']:,.0f} "
                                f"and a failure at {node['failure_cost']:,.0f}, replacing every "
                                f"{in_task_unit(best, unit):g} {unit} has the lowest long-run cost, "
                                f"{saving:.0%} below running to failure.")
                else:
                    proposal = ("retire", None, unit,
                                f"{_describe(model)}. With these costs no replacement age beats replacing "
                                f"on failure: there's no wear-out to get ahead of. Consider running to failure.")
            elif task.get("outcome") == "failure_finding" and node.get("availability_target"):
                try:
                    res = strategy_service.failure_finding(model["distribution"], model["params"],
                                                           node["availability_target"], life_unit,
                                                           model.get("extras"))
                except Exception:  # noqa: BLE001
                    continue
                every = float(res.get("interval") or 0)
                if every > 0:
                    proposal = ("interval", in_task_unit(every, unit), unit,
                                f"{_describe(model)}. To keep the protective function available "
                                f"{node['availability_target']:.1%} of the time, check it every "
                                f"{in_task_unit(every, unit):g} {unit} (2 × (1 − A) × MTTF).")
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
        if not model or c["failures"] <= model.get("failures_seen", model.get("failures", 0)):
            continue
        try:
            fit_class_model(m, db, c["position_class"], model.get("distribution") or "weibull")
            done.append(c["position_class"])
        except (Invalid, NotFound):
            continue
    return done


def use_per_year(m: Maintenance, positions: list[dict], unit: str) -> tuple[dict, list[dict]]:
    """How much use (in ``unit``) each position adds a year: from its operating plan (its
    own or the nearest above) over the year ahead, through RePyability's duty map, else
    its counter's recent rate. ({position id: {per_year, basis, counter}}, [positions
    without one, with why])."""
    from backend.maintenance import forecast

    rates, missing = {}, []
    for p in positions:
        brief = {"id": p["id"], "name": p["name"]}
        counter = m._use_counter(p["id"], unit)
        if counter is None:
            missing.append({"position": brief, "reason": f"no {unit} counter on this position or above it"})
            continue
        readings = svc._readings(m.s, m.org, counter, m.tz)
        planned = forecast._plan_rate(m, p["id"], counter, readings, 365.25) if readings else None
        if planned is not None:
            per_day, basis = planned[0], "plan"
        else:
            per_day, basis = forecast._counter_rate(readings)[0], "counter"
        if per_day is None:
            missing.append({"position": brief, "reason": f"its {unit} counter needs two readings at least a day "
                                                         "apart in the last year for a usage rate"})
            continue
        rates[p["id"]] = {"per_year": per_day * 365.25, "basis": basis,
                          "counter": {"id": counter["id"], "name": counter["name"]}}
    return rates, missing


def economics(m: Maintenance, position_class: str, interval: float | None = None, unit: str | None = None,
              horizon_years: float = 10, discount_rate: float = 0.07) -> dict:
    """What the class's replacement plan costs a year, against the best interval and
    running to failure, from its non-repairable model and costs: and, given an interval, what that
    would cost (a what-if). Each with its net present cost over the horizon. ``unit``: the
    what-if's and the best interval's unit (default months; for a model by use, its unit).

    A model by use (flight hours) gives a cost per unit of use: each position's use a year
    (its operating plan, else its counter's rate) turns that into a cost a year."""
    import numpy as np

    from backend.services import strategy as strategy_service

    node0 = m.s.node(m.org, class_id(m.org, position_class)) or {}
    if node0.get("model") and model_unit(node0["model"]) != "days":
        return _economics_by_use(m, position_class, interval, unit, horizon_years, discount_rate)
    unit = unit or "months"

    node = m.s.node(m.org, class_id(m.org, position_class))
    if not node or not node.get("model"):
        raise Invalid(f"Fit a non-repairable model for {position_class} first.")
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


def _economics_by_use(m: Maintenance, position_class: str, interval, unit, horizon_years, discount_rate) -> dict:
    """:func:`economics` for a class whose model counts use: the cost rate is per unit
    of use, and each position's use a year makes it a cost a year."""
    import numpy as np

    from backend.services import strategy as strategy_service

    node = m.s.node(m.org, class_id(m.org, position_class))
    if node.get("planned_cost") is None or node.get("failure_cost") is None:
        raise Invalid(f"Set {position_class}'s costs (a planned replacement and a failure) first.")
    if not 0 <= float(discount_rate) < 1 or not 0 < float(horizon_years) <= 100:
        raise Invalid("The discount rate is 0 to 1 (e.g. 0.07) and the horizon 1 to 100 years.")
    model = node["model"]
    life = model_unit(model)
    what_unit = svc._norm_unit(unit) if unit else life
    if what_unit not in DAYS_PER and what_unit != life:
        raise Invalid(f"{node['name']}'s model counts {life}: a what-if interval is in {life}, or in days, "
                      "weeks, months or years.")
    if interval is not None and not (math.isfinite(float(interval)) and 0 < float(interval) <= 1e9):
        raise Invalid(f"A what-if interval is a positive number of {what_unit}.")
    res = strategy_service.optimal_replacement(model["distribution"], model["params"], node["planned_cost"],
                                               node["failure_cost"], life, model.get("extras"))
    t, rate = np.asarray(res["curve"]["t"], float), np.asarray(res["curve"]["cost_rate"], float)
    ok = np.isfinite(rate)
    t, rate = t[ok], rate[ok]
    rtf = float(res["run_to_failure_cost_rate"])

    def per_use(x: float) -> float:
        return float(np.interp(x, t, rate, right=rtf))

    r, h = float(discount_rate), float(horizon_years)
    annuity = h if r == 0 else (1 - (1 + r) ** -h) / r

    def option(label, yearly, interval_text):
        return {"plan": label, "interval": interval_text, "per_year": round(yearly, 2),
                "net_present_cost": round(yearly * annuity, 2)}

    positions = [p for p in m.s.nodes(m.org, "Position")
                 if (p.get("position_class") or "").strip().lower() == position_class.strip().lower()
                 and not p.get("retired")]
    rates, missing = use_per_year(m, positions, life)
    costed = [p for p in positions if p["id"] in rates]
    if not costed:
        raise Invalid(f"No position of {node['name']} has a usage rate in {life}: give them an operating plan, "
                      f"or record readings on their {life} counters.")
    yearly_use = {p["id"]: rates[p["id"]]["per_year"] for p in costed}
    total = sum(yearly_use.values())

    def as_use(value: float, u: str, pid: str) -> float:
        """An interval as use at a position: by use as it is, on the calendar through its rate."""
        return value * DAYS_PER[u] / 365.25 * yearly_use[pid] if u in DAYS_PER else value

    out = {"position_class": node["name"], "positions": len(costed), "horizon_years": h, "discount_rate": r,
           "unit": life, "options": [],
           "use_per_year": [{"position": {"id": p["id"], "name": p["name"]},
                             "per_year": round(rates[p["id"]]["per_year"], 2), "basis": rates[p["id"]]["basis"],
                             "counter": rates[p["id"]]["counter"]} for p in costed],
           "not_costed": missing}
    tasks = [(p["id"], t_) for p in costed for t_ in m._tasks_on(p["id"])
             if t_.get("outcome") == "fixed_interval"
             and (t_["unit"] in DAYS_PER or svc._norm_unit(t_["unit"]) == life)]
    if tasks:
        current = sum(per_use(as_use(t_["interval"], t_["unit"], pid)) * yearly_use[pid] for pid, t_ in tasks)
        current += rtf * sum(v for pid, v in yearly_use.items() if pid not in {pid_ for pid_, _ in tasks})
        intervals = sorted({f"{t_['interval']:g} {t_['unit']}" for _, t_ in tasks})
        out["options"].append(option("current plan", current, ", ".join(intervals)))
    if res.get("beneficial") and res.get("optimal_time"):
        best = float(res["optimal_time"])
        out["options"].append(option("best interval", per_use(best) * total, f"{_rounded(best):g} {life}"))
    out["options"].append(option("run to failure", rtf * total, "replace on failure"))
    if interval is not None:
        value = float(interval)
        yearly = sum(per_use(as_use(value, what_unit, pid)) * v for pid, v in yearly_use.items())
        out["options"].append(option("what if", yearly, f"{value:g} {what_unit}"))
    cheapest = min(out["options"], key=lambda o: o["per_year"])
    out["cheapest"] = cheapest["plan"]
    n = len(costed)
    note = (f"Long-run cost per year across {n} position{'s' if n != 1 else ''}: the {model['distribution']} "
            f"model's cost per {life[:-1] if life.endswith('s') and len(life) > 3 else life} with the costs, times each position's {life} a year "
            f"({total:,.0f} {life} a year in all, from operating plans or the counters' recent rates); net present "
            f"cost over {h:g} years at {r:.0%}. Treat it as rough with few failures on record ({model['failures']}).")
    if missing:
        note += (f" {len(missing)} position{'s' if len(missing) != 1 else ''} without a usage rate "
                 f"{'aren' if len(missing) != 1 else 'isn'}'t costed (see not_costed).")
    out["note"] = note
    return out
