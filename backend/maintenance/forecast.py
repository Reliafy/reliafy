"""Failure forecast per position class (#407): from the register itself.

Every position of a class with an item fitted is one unit of a fleet running on
the class's fitted life model (:func:`loop.fit_class_model`). Its age is how
long the item has been in that position: days on the calendar for a model in
calendar units (the same life the class's life data counts), else the use the
position's counter in the model's unit has added since the item went in. It
adds that much each period: the period's days, or the counter's recent rate
(the fleet ingest's EWMA estimate over the last year of readings). A position
with nothing fitted, or with no counter rate to go on, is listed, not forecast.

The forecast is the fleet forecast's renewals engine
(``services.fleet._forecast_renewals``): a failed item is replaced and its
replacement can fail again. Each failure uses the parts on that position's parts
list that replace it (the replacement part, and any critical spare) at their
quantity per job, so the same simulation gives each part's demand as a
distribution per period, against its stock. Class costs price the failures, and
the class's scheduled replacements falling due price the planned work.

Each part also gets stock levels (#31, ``services.spares``): how many to hold for
a service level over its lead time plus the review period, when to reorder, and
the chance today's stock runs out, read off the raw simulated demand over those
windows (a second run of the same engine that keeps every failure's time).

Nothing is stored: it's worked out on read, and kept briefly for repeat reads
until the workspace's next event (fitments, close-outs, manual readings) or a
few minutes (a feed's readings arrive without one).
"""

from __future__ import annotations

import copy
import threading
import time
import uuid
from collections import OrderedDict
from datetime import date, datetime, timedelta, timezone

import numpy as np

from backend.maintenance import service as svc
from backend.maintenance.service import Invalid, Maintenance, class_id
from backend.services import spares

PERIODS = ("month", "quarter", "year")
MAX_PERIODS = 120
MAX_HORIZON_DAYS = 10 * 365.25 + 1  # 10 years ahead at most
MAX_PARTS = 25  # parts tallied per class (the replacement parts and critical spares)
MAX_RANKED = 100  # positions listed in at_risk
RATE_WINDOW_DAYS = 365  # counter readings the usage rate is estimated from
LEVEL = 0.8  # P10–P90
DEFAULT_LEAD_DAYS = 30  # a part's lead time when it has none (said so: "assumed")
MAX_LEAD_DAYS = spares.MAX_LEAD_DAYS
CACHE_SECONDS = 300
_CACHE: OrderedDict = OrderedDict()
_CACHE_SIZE = 32
_LOCK = threading.Lock()


def _q(values, q: float) -> float:
    """A quantile that is a value the simulation can give (whole failures, whole
    jobs' parts), not one between two."""
    return float(np.quantile(values, q, method="inverted_cdf"))


def _num(v: float) -> str:
    return f"{v:.1f}" if v < 10 else f"{v:,.0f}"


def _class_positions(m: Maintenance, name: str) -> list[dict]:
    wanted = name.strip().lower()
    return sorted((p for p in m.s.nodes(m.org, "Position")
                   if (p.get("position_class") or "").strip().lower() == wanted and not p.get("retired")),
                  key=lambda p: p["name"].lower())


def _calendar_age(m: Maintenance, position_id: str, fitment: dict) -> float:
    """Days the fitted item has been in the position, as its life-data row counts
    them: a start known only roughly takes the middle of its range."""
    row = next((r for r in m.life_data(position_id) if r["fitment_id"] == fitment["id"]), None)
    if row is None:
        return float((date.fromisoformat(m.today()) - date.fromisoformat(fitment["from"])).days)
    return (row["xl"] + row["xr"]) / 2 if "xl" in row else float(row["x"])


def _counter_rate(readings: list[dict]) -> tuple[float | None, int]:
    """Use per day from a counter's readings over the last year: the fleet
    ingest's EWMA estimate, fed the readings in order. ``(None, 0)`` when there
    aren't two readings at least a day apart."""
    from backend.services import ingest

    if not readings:
        return None, 0
    cutoff = (date.fromisoformat(readings[-1]["on"]) - timedelta(days=RATE_WINDOW_DAYS)).isoformat()
    scratch: dict = {}
    for r in readings:
        if r["on"] >= cutoff:
            at = datetime.fromisoformat(r["on"]).replace(tzinfo=timezone.utc)
            ingest.apply_reading(scratch, float(r["value"]), at, 1.0)
    n = int(scratch.get("estimated_rate_n") or 0)
    rate = scratch.get("estimated_rate")
    return (max(0.0, float(rate)), n) if n and rate is not None else (None, 0)


def _use_age(m: Maintenance, position_id: str, fitment: dict, unit: str) -> dict:
    """Age and rate in a unit of use, from the position's counter in that unit:
    {age, per_day, counter} or {reason} when they can't be had."""
    counter = svc._counter_on(m.s, m.org, position_id, unit)
    if counter is None:
        return {"reason": f"no {unit} counter on this position"}
    readings = svc._readings(m.s, m.org, counter, m.tz)
    per_day, _n = _counter_rate(readings)
    if per_day is None:
        return {"reason": f"its {unit} counter needs two readings at least a day apart in the last year "
                          "for a usage rate"}
    start = svc._reading_at(readings, fitment["from"])
    if start is None:
        since = [r for r in readings if r["on"] >= fitment["from"]]
        if not since:
            return {"reason": f"no {unit} reading since the item was fitted"}
        start = since[0]["value"]
    last = readings[-1]
    # Read some days ago: what it has added since, at its rate.
    ahead = max(0, (date.fromisoformat(m.today()) - date.fromisoformat(last["on"])).days) * per_day
    return {"age": max(0.0, float(last["value"]) - float(start) + ahead), "per_day": per_day,
            "counter": {"id": counter["id"], "name": counter["name"], "reading": last["value"], "read_on": last["on"]}}


def _spare_columns(m: Maintenance, units: list[dict]) -> tuple[list[dict], np.ndarray]:
    """The parts a failure at each forecast position uses: what replaces the
    item (role replacement) and any critical spare, by quantity per job. One
    entry per part, and a matrix of quantity per job (positions × parts)."""
    parts: dict[str, dict] = {}
    per_unit: list[dict[str, float]] = []
    for u in units:
        mine: dict[str, float] = {}
        for listing in m._listings_at(u["id"]):
            if listing["role"] != "replacement" and not listing.get("critical"):
                continue
            view = m._listing_view(listing)
            pid = view["part"]["id"]
            mine[pid] = mine.get(pid, 0.0) + float(view["quantity"])
            entry = parts.setdefault(pid, {"part": view["part"], "roles": set(), "critical": False,
                                           "usable_on_hand": view["usable_on_hand"], "min_on_hand": None,
                                           "use_instead": view["use_instead"], "positions": 0, "per_job": set()})
            entry["roles"].add(view["role"])
            entry["critical"] = entry["critical"] or view["critical"]
            entry["positions"] += 1
            entry["per_job"].add(float(view["quantity"]))
            if view["min_on_hand"] is not None:
                entry["min_on_hand"] = max(entry["min_on_hand"] or 0.0, float(view["min_on_hand"]))
        per_unit.append(mine)
    ordered = sorted(parts.items(), key=lambda kv: ("replacement" not in kv[1]["roles"], not kv[1]["critical"],
                                                    kv[1]["part"]["part_number"].lower()))[:MAX_PARTS]
    matrix = np.array([[mine.get(pid, 0.0) for pid, _ in ordered] for mine in per_unit],
                      dtype=float).reshape(len(units), len(ordered))
    return [entry for _pid, entry in ordered], matrix


def _planned(m: Maintenance, positions: list[dict], starts: list[str], end: str) -> list[int]:
    """Scheduled replacements (fixed-interval tasks) on the class's positions falling
    due in each period: the next due date (overdue: the first period), then every
    interval on the calendar. A task by use counts its next due date only."""
    counts = [0] * len(starts)
    for p in positions:
        for task in m._tasks_on(p["id"]):
            if task.get("outcome") != "fixed_interval":
                continue
            due = m._task_view(task)["next_due"]
            seen = 0
            while due and due < end and seen < 1000:
                k = max(0, sum(1 for s in starts if s <= due) - 1)
                counts[k] += 1
                seen += 1
                if not svc._is_calendar(task["unit"]):
                    break
                due = svc.add_interval(due, task["interval"], task["unit"])
    return counts


def _summary(values: np.ndarray, qs=(0.1, 0.5, 0.9)) -> dict:
    out = {"mean": float(values.mean())}
    for q in qs:
        out[f"p{round(q * 100)}"] = _q(values, q)
    return out


def _stocking_options(service_level, lead_time_days, review_days) -> dict:
    """The request's what-ifs for the spares stock levels: a service level and a
    lead time for every part (each part's own, else the defaults, otherwise), and
    the review period."""
    try:
        return {"service_level": spares.service_level(service_level),
                "lead_time_days": spares.duration(lead_time_days, "lead time (days)", MAX_LEAD_DAYS),
                "review_days": spares.duration(review_days, "review period (days)", MAX_LEAD_DAYS) or 0.0}
    except spares.SparesError as exc:
        raise Invalid(str(exc)) from None


def class_forecast(m: Maintenance, position_class, period: str = "month", periods=12, service_level=None,
                   lead_time_days=None, review_days=None) -> dict:
    """The class's failure forecast: see the module docstring. Cached briefly.
    service_level, lead_time_days and review_days set the spares' stock levels
    (#31): see :func:`_stocking`."""
    opts = _stocking_options(service_level, lead_time_days, review_days)
    period = (period or "month").strip().lower()
    if period not in PERIODS:
        raise Invalid(f"The period is one of {', '.join(PERIODS)}.")
    try:
        periods = int(periods if periods not in (None, "") else 12)
    except (TypeError, ValueError):
        raise Invalid("periods must be a whole number.") from None
    from backend.services.fleet import period_days

    days = period_days(period)
    if not 1 <= periods <= MAX_PERIODS or periods * days > MAX_HORIZON_DAYS:
        raise Invalid(f"Forecast 1 to {MAX_PERIODS} periods, at most 10 years ahead.")
    name = m._class_name(position_class)
    # As the class is written on its positions (or its node), not as asked.
    node = m.s.node(m.org, class_id(m.org, name))
    name = node["name"] if node else name
    # Kept per store (a token on it: an id() can be reused once a store is gone)
    # until the organisation's next event, or for a few minutes.
    store_key = getattr(m.s, "_forecast_key", None)
    if store_key is None:
        store_key = m.s._forecast_key = uuid.uuid4().hex
    key = (store_key, m.org, m.s.event_count(m.org), m.today(), name.lower(), period, periods,
           *sorted(opts.items()))
    now = time.monotonic()
    with _LOCK:
        hit = _CACHE.get(key)
        if hit and now - hit[0] < CACHE_SECONDS:
            return copy.deepcopy(hit[1])
    out = _forecast(m, name, period, periods, days, opts)
    with _LOCK:
        _CACHE[key] = (now, out)
        while len(_CACHE) > _CACHE_SIZE:
            _CACHE.popitem(last=False)
    return copy.deepcopy(out)


def _forecast(m: Maintenance, name: str, period: str, periods: int, days: float, opts: dict | None = None) -> dict:
    from backend.maintenance.loop import FEW_FAILURES
    from backend.services import fleet
    from backend.services.strategy import StrategyError, _model_from_params

    node = m.s.node(m.org, class_id(m.org, name)) or {}
    model = node.get("model")
    if not model:
        raise Invalid(f"Fit a life model for {name} first (maintenance_reliability fit_class_model).")
    unit = svc._norm_unit(model.get("unit")) or "days"
    calendar = unit in svc.CALENDAR_UNITS
    if (model.get("extras") or {}).get("p") is not None:
        raise Invalid("The class's model is a limited-failure-population fit: replacements can't be drawn from "
                      "it, so there's no forecast with renewals. Refit it with another distribution.")
    try:
        dist, _label = _model_from_params(model["distribution"], model["params"], model.get("extras"))
    except StrategyError as exc:
        raise Invalid(f"The class's model can't be evaluated: {exc}") from None

    today = m.today()
    start = date.fromisoformat(today)
    starts = [(start + timedelta(days=round(k * days))).isoformat() for k in range(periods + 1)]
    positions = _class_positions(m, name)
    units, skipped = [], []
    for p in positions:
        fitment = m.current_fitment(p["id"])
        brief = {"id": p["id"], "name": p["name"]}
        if fitment is None:
            skipped.append({"position": brief, "reason": "nothing fitted"})
            continue
        item = m.s.inn(m.org, fitment["id"], "IN")
        row = {"id": p["id"], "name": p["name"], "position": brief, "fitted_on": fitment["from"],
               "item": m._item_brief(item[0] if item else None)}
        if calendar:
            per = svc._DAYS_PER[unit]
            row.update(age=_calendar_age(m, p["id"], fitment) / per, rate=days / per, rate_basis="calendar")
        else:
            use = _use_age(m, p["id"], fitment, unit)
            if "reason" in use:
                skipped.append({"position": brief, "item": row["item"], "reason": use["reason"]})
                continue
            row.update(age=use["age"], rate=use["per_day"] * days, rate_basis="counter", counter=use["counter"])
        units.append(row)

    word = f"{period}{'s' if periods != 1 else ''}"
    base = {
        "position_class": name, "status": "ok", "today": today, "period": period, "periods": periods,
        "period_days": days, "horizon_end": starts[-1], "interval_level": LEVEL,
        "model": {k: model.get(k) for k in ("model_id", "distribution", "params", "fitted_on", "failures",
                                            "suspensions")} | {"unit": unit},
        "n_positions": len(positions), "n_forecast": len(units),
        "n_not_forecast": len(skipped), "not_forecast": skipped[:MAX_RANKED],
    }
    notes = []
    if (model.get("failures") or 0) < FEW_FAILURES:
        notes.append(f"The model rests on {model.get('failures') or 0} failures: treat the forecast as rough.")
    if any(s["reason"] != "nothing fitted" for s in skipped):
        notes.append("Positions without a usage rate aren't forecast (not counted as no failures): record "
                     f"readings on their {unit} counter.")

    spares_cols, matrix = _spare_columns(m, units)
    weights = np.column_stack([np.ones(len(units)), matrix]) if units else np.zeros((0, 1 + len(spares_cols)))
    if units:
        ages = np.array([u["age"] for u in units], dtype=float)
        rates = np.array([u["rate"] for u in units], dtype=float)
        sim = fleet._forecast_renewals(dist, ages, rates * periods, rates, periods, units, weights=weights)
        tally = sim["tally"].astype(float)
        sims = sim["sims"]
        nxt = fleet._cond_prob(dist, ages, rates)
    else:
        sims, tally, nxt, sim = 0, np.zeros((1, periods, weights.shape[1])), np.zeros(0), {"per_item": []}

    failures = tally[:, :, 0]
    total = failures.sum(axis=1)
    expected = float(total.mean())
    interval = [_q(total, 0.1), _q(total, 0.9)]
    per_period = []
    for k in range(periods):
        col = failures[:, k]
        end = (date.fromisoformat(starts[k + 1]) - timedelta(days=1)).isoformat()
        per_period.append({"start": starts[k], "end": end, "expected": float(col.mean()), "p10": _q(col, 0.1),
                           "p90": _q(col, 0.9)})

    ranked = []
    for u, p_next, row in zip(units, nxt, sim["per_item"]):
        ranked.append({**{k: u[k] for k in ("position", "item", "fitted_on", "rate_basis")},
                       "age": round(u["age"], 2), "rate_per_period": round(u["rate"], 3),
                       **({"counter": u["counter"]} if "counter" in u else {}),
                       "prob_next_period": float(p_next), "prob_in_horizon": row["prob_any"],
                       "expected_failures": row["expected"]})
    ranked.sort(key=lambda r: (-r["prob_next_period"], r["position"]["name"].lower()))

    spare_rows = []
    for j, entry in enumerate(spares_cols, start=1):
        demand = tally[:, :, j]
        cum = np.cumsum(demand, axis=1)
        have = float(entry["usable_on_hand"])
        # P(the stock in hand covers the demand to the end of each period).
        cumulative = [{**_summary(cum[:, k], (0.1, 0.5, 0.9, 0.95)),
                       "prob_covered": float((cum[:, k] <= have + 1e-9).mean())} for k in range(periods)]
        covered = sum(1 for c in cumulative if c["p90"] <= have + 1e-9)
        pt = entry["part"]
        unit_text = pt.get("unit") or "each"
        words = (f"≈ {_num(cumulative[-1]['mean'])} needed over the next {periods} {word} (likely "
                 f"{cumulative[-1]['p10']:g}–{cumulative[-1]['p90']:g}); {have:g} usable in stock.")
        if covered < periods:
            words += (f" Stock covers {covered} {period}{'s' if covered != 1 else ''} at the likely high end "
                      f"(P90); {cumulative[0]['prob_covered']:.0%} chance it covers the first {period}.")
        spare_rows.append({
            "part": pt, "roles": sorted(entry["roles"]), "critical": entry["critical"],
            "positions": entry["positions"], "per_job": sorted(entry["per_job"]), "unit": unit_text,
            "usable_on_hand": have, "min_on_hand": entry["min_on_hand"], "use_instead": entry["use_instead"],
            "stock": m._stock_rows(m._stocks(pt["id"])),
            "expected": cumulative[-1]["mean"], "interval": [cumulative[-1]["p10"], cumulative[-1]["p90"]],
            "per_period": [_summary(demand[:, k]) for k in range(periods)],
            "cumulative": cumulative, "covered_periods": covered,
            "short": cumulative[-1]["p90"] > have + 1e-9, "summary": words,
        })

    out = {**base, "sims": sims, "expected": expected, "interval": interval,
           "headline": _headline(name, expected, interval, periods, word, len(units)),
           "basis": (f"{len(units)} of {len(positions)} positions forecast from the "
                     f"{str(model.get('distribution')).capitalize()} model; a failed item is replaced and its "
                     "replacement can fail again."),
           "per_period": per_period, "at_risk": ranked[:MAX_RANKED], "at_risk_truncated": len(ranked) > MAX_RANKED,
           "spares": spare_rows, "budget": _budget(m, node, positions, failures, starts, periods)}
    out["stocking"] = _stocking(m, dist, units, matrix, spare_rows, opts or _stocking_options(None, None, None),
                                periods, days, starts)
    if out["budget"] and out["budget"].get("planned"):
        notes.append("Planned replacements aren't taken off the failure count (each failure is replaced like for "
                     "like), so with a replacement plan in place the failures err high.")
    out["notes"] = notes
    return out


STOCKING_NOTE = (
    "Stock levels are read off the simulated demand itself, not a normal approximation. Hold covers each part's "
    "lead time plus the review period at its service level; reorder at covers the lead time alone. Usable stock in "
    "every store counts as one stock: a single site. A repairable part's pool covers its repair turnaround (one "
    "repair shop, every unit sent comes back).")


def _days(v: float) -> str:
    return f"{v:g} day{'s' if v != 1 else ''}"


def _part_stocking(node: dict, opts: dict) -> dict:
    """One part's stock-level inputs, and where each came from: the request (a
    what-if for every part), the part's own, or the default."""
    if opts["service_level"] is not None:
        level, level_basis = opts["service_level"], "request"
    elif node.get("service_level") is not None:
        level, level_basis = float(node["service_level"]), "part"
    else:
        level, level_basis = spares.DEFAULT_SERVICE_LEVEL, "default"
    if opts["lead_time_days"] is not None:
        lead, lead_basis = opts["lead_time_days"], "request"
    elif node.get("lead_time_days") is not None:
        lead, lead_basis = float(node["lead_time_days"]), "part"
    else:
        lead, lead_basis = float(DEFAULT_LEAD_DAYS), "assumed"
    turnaround = node.get("turnaround_days")
    repairable = bool(node.get("repairable")) and turnaround is not None
    review = float(opts["review_days"] or 0)
    return {"part_settings": {k: node.get(k) for k in svc.PART_STOCKING},
            "service_level": level, "service_level_basis": level_basis, "lead_time_days": lead,
            "lead_time_basis": lead_basis, "review_days": review, "repairable": repairable,
            "turnaround_days": float(turnaround) if turnaround is not None else None,
            "window_days": float(turnaround) if repairable else lead + review}


def _demand(events: dict, start: float, length: float, weights: np.ndarray):
    """One part's simulated demand over ``length`` periods from ``start``."""
    return spares.Demand.from_samples(spares.window_demand(events, start, start + length, weights)[:, 0])


def _stocking(m: Maintenance, dist, units: list[dict], matrix: np.ndarray, rows: list[dict], opts: dict,
              periods: int, days: float, starts: list[str]) -> dict:
    """Each spare's stock levels (#31), on its row as ``stocking``: hold N, reorder
    at, the risk at today's usable stock, what holding N costs, a risk curve for
    any stock, and the same for a window starting at each period. Returns what
    applies to them all."""
    from backend.services import fleet
    from backend.services.strategy import StrategyError

    meta = {"service_level": opts["service_level"], "default_service_level": spares.DEFAULT_SERVICE_LEVEL,
            "lead_time_days": opts["lead_time_days"], "default_lead_time_days": DEFAULT_LEAD_DAYS,
            "review_days": opts["review_days"], "note": STOCKING_NOTE}
    if not rows or not units:
        return meta
    inputs = [_part_stocking(m.s.node(m.org, r["part"]["id"]) or {}, opts) for r in rows]
    ages = np.array([u["age"] for u in units], dtype=float)
    rates = np.array([u["rate"] for u in units], dtype=float)
    horizon = (periods - 1) + max(i["window_days"] for i in inputs) / days
    try:
        events = fleet._renewal_events(dist, ages, rates, horizon)
    except StrategyError as exc:
        return {**meta, "error": str(exc)}
    meta["sims"] = events["sims"]
    for j, (row, inp) in enumerate(zip(rows, inputs)):
        weights = matrix[:, j:j + 1]
        level = inp["service_level"]
        protect = [_demand(events, k, inp["window_days"] / days, weights) for k in range(periods)]
        lead = None if inp["repairable"] else [_demand(events, k, inp["lead_time_days"] / days, weights)
                                               for k in range(periods)]
        now = spares.answer(protect[0], lead[0] if lead else None, row["usable_on_hand"], level,
                            row["part"].get("unit_cost"))
        plan = [{"start": starts[k], "hold": protect[k].quantile(level),
                 "reorder_at": lead[k].quantile(level) if lead else None,
                 "expected_demand": protect[k].mean} for k in range(periods)]
        if inp["repairable"]:
            window = f"the repair turnaround ({_days(inp['window_days'])})"
        elif inp["review_days"]:
            window = f"the lead time and review period ({_days(inp['window_days'])})"
        else:
            window = f"the lead time ({_days(inp['lead_time_days'])})"
        words = spares.sentence(now, level, window, row["unit"], inp["repairable"], inp["review_days"] > 0)
        if inp["lead_time_basis"] == "assumed" and not inp["repairable"]:
            words += f" No lead time is set for this part: {DEFAULT_LEAD_DAYS} days assumed."
        row["stocking"] = {**inp, **now, "per_period": plan, "summary": words}
    return meta


def _headline(name, expected, interval, periods, word, n) -> str:
    if not n:
        return f"No position of {name} has an item fitted that can be forecast."
    return (f"≈ {_num(expected)} failure{'s' if round(expected, 1) != 1 else ''} in the next {periods} {word} "
            f"(likely {interval[0]:g}–{interval[1]:g})")


def _budget(m: Maintenance, node: dict, positions, failures: np.ndarray, starts: list[str],
            periods: int) -> dict | None:
    """What the failures cost (each at the class's failure cost, else its default
    replacement cost), plus the scheduled replacements falling due at the planned
    cost; per period and in total, with the failures' P10–P90."""
    failure_cost, basis, currency = node.get("failure_cost"), "failure_cost", None
    if failure_cost is None and (node.get("replacement_cost") or {}).get("amount") is not None:
        failure_cost, basis = node["replacement_cost"]["amount"], "replacement_cost"
        currency = node["replacement_cost"].get("currency")
    planned_cost = node.get("planned_cost")
    if failure_cost is None and planned_cost is None:
        return None
    planned = _planned(m, positions, starts[:-1], starts[-1]) if planned_cost is not None else [0] * periods
    fc, pc = float(failure_cost or 0), float(planned_cost or 0)
    rows = []
    for k in range(periods):
        col = failures[:, k] * fc
        rows.append({"start": starts[k], "failures": float(col.mean()), "failures_p10": _q(col, 0.1),
                     "failures_p90": _q(col, 0.9), "planned": planned[k] * pc, "planned_count": planned[k]})
    total = failures.sum(axis=1) * fc
    plan_total = sum(planned) * pc
    return {
        "cost_per_failure": failure_cost, "basis": basis, "currency": currency, "planned_cost": planned_cost,
        "failures": float(total.mean()), "failures_interval": [_q(total, 0.1), _q(total, 0.9)],
        "planned": plan_total, "planned_count": sum(planned),
        "expected": float(total.mean()) + plan_total,
        "interval": [_q(total, 0.1) + plan_total, _q(total, 0.9) + plan_total],
        "per_period": rows,
    }


def without_plans(fc: dict) -> dict:
    """A class forecast with each spare's stock levels for now only: no plan per
    period or risk curve (those are in :func:`spares_plan`)."""
    out = dict(fc)
    drop = ("per_period", "risk_curve")
    out["spares"] = [{**s, "stocking": {k: v for k, v in s["stocking"].items() if k not in drop}}
                     if s.get("stocking") else s for s in fc["spares"]]
    return out


def spares_plan(fc: dict) -> dict:
    """The stocking plan from a class forecast: each spare's stock levels now and
    for a window starting at each period, with its risk curve."""
    keep = ("part", "unit", "critical", "roles", "positions", "per_job", "usable_on_hand", "min_on_hand",
            "use_instead")
    return {**{k: fc[k] for k in ("position_class", "today", "period", "periods", "horizon_end")},
            "stocking": fc.get("stocking"),
            "parts": [{**{k: s.get(k) for k in keep}, "stock_by_location": s.get("stock"),
                       **(s.get("stocking") or {}), "demand_per_period": s["per_period"]} for s in fc["spares"]]}


def digest_spares(m: Maintenance) -> tuple[list[dict], list[dict]]:
    """For the daily digest, from each class's forecast: critical spares whose
    expected use next month is more than is usable in stock, and parts with a
    lead time set whose usable stock is below the reorder point it needs (#31)."""
    short, below = [], []
    for c in m.position_classes():
        if not c.get("model"):
            continue
        try:
            fc = class_forecast(m, c["position_class"], "month", 1)
        except Invalid:
            continue
        for s in fc["spares"]:
            need = s["per_period"][0]["mean"]
            if s["critical"] and need > s["usable_on_hand"]:
                short.append({"position_class": c["position_class"], "part": s["part"], "expected": need,
                              "failures": fc["expected"], "usable_on_hand": s["usable_on_hand"]})
            st = s.get("stocking")
            if st and st["lead_time_basis"] == "part" and st.get("below_reorder"):
                below.append({"position_class": c["position_class"], "part": s["part"],
                              "usable_on_hand": s["usable_on_hand"], "reorder_at": st["reorder_at"],
                              "hold": st["hold"], "service_level": st["service_level"],
                              "lead_time_days": st["lead_time_days"], "repairable": st["repairable"]})
    return short, below


def short_next_month(m: Maintenance) -> list[dict]:
    """Critical spares whose expected use next month is more than is usable in stock."""
    return digest_spares(m)[0]
