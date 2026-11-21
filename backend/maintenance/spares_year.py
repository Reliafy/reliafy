"""Spares for the year from the register: every part a failure or a task uses, over a horizon,
against its stock and lead time (the engine and its rule: ``services.spares_year``).

What it reads, for the positions in scope (a position or location and everything in it, inside
the asset opened; a position class; a product's built items, or a planned fleet of one not yet
built; or the whole workspace):

* **failures**, on each position with an item fitted and a life model: the model in use on the
  position (a non-repairable life), else its class's fitted model (a class's own Spares always
  reads its class model, as its forecast does). The item's age and how fast it ages are the class
  forecast's (``forecast._calendar_age`` / ``_use_age``: the calendar, the operating plan's average
  over the horizon through RePyability's duty map, or the counter's recent rate). Each failure uses
  the parts on the position's parts list that replace it (role replacement) and any critical spare;
  where the list names no replacement part, its components (a bearing on a bearing position); where
  it names nothing, the spares of the fixed-interval task that replaces the same thing (a diaphragm
  that splits early takes the diaphragm kit).
* **planned jobs**: every task on those positions falling due in the horizon. A task in a work
  package falls due at the package's visits (a shutdown's "only if older than" makes the job
  depend on the item's age then); any other task on the dates RePyability's ``Task.due`` gives it
  (``position_forecast``: calendar rules, and tasks by use through the operating plan or the
  counter's rate). A fixed-interval task renews the item (a planned replacement: the failures after
  it count from new); others don't. A job uses its task's LSA spares (and consumables that name a
  catalogue part); a replacement whose LSA names none uses what a failure there uses.
* **age after a replacement**: an item renewed by a fixed-interval task counts its age from the
  task's last time done when that's after the item went in; a task by use with none recorded,
  from the reading its interval counts from (as its due dates do).

Nothing is stored; the stock is the catalogue's, usable stock counting a part's successors and
interchangeable parts in every store as one stock (a single site), as the parts lists do.
"""

from __future__ import annotations

import math
import zlib
from datetime import date, timedelta

from backend.maintenance import service as svc
from backend.maintenance.service import Invalid, Maintenance
from backend.services import spares
from backend.services import spares_year as engine

MAX_POSITIONS = 2000
MAX_MONTHS = 60
MAX_FLEET = 500
DEFAULT_LEAD_DAYS = 30  # as the class forecast assumes, and says so
SCOPES = ("position", "location", "class", "product", "workspace")


def _seed(position_id: str) -> int:
    """A stream per position, the same whatever the scope it's read in."""
    return zlib.crc32(position_id.encode())


# ---- what's in scope ------------------------------------------------------------------------

def _scope(m: Maintenance, scope: dict) -> tuple[str, dict, list[dict]]:
    """(kind, what it is, the live positions in it)."""
    from backend.maintenance import forecast as class_fc
    from backend.maintenance import position_forecast as pf

    designs = m._design_ids()
    if scope.get("position_id"):
        pid, root = scope["position_id"], scope.get("root") or None
        pos = m._get(pid, "Position")
        if root:
            if m.s.node(m.org, root) is None:
                raise svc.NotFound(f"Position {root}")
            if root != pid and root not in m._ancestor_ids(pid):
                raise Invalid("That position isn't inside the asset opened.")
        if pid in designs:
            top = m._design_root_of(pid)
            return _product_scope(m, top or pos, scope)
        nodes = [n for n, _d in pf._subtree(m, pid)]
        return "position", {"id": pos["id"], "name": pos.get("name", "")}, nodes
    if scope.get("location_id"):
        loc = m._get(scope["location_id"], "Location")
        inside = [p for p in m.s.nodes(m.org, "Position") if not p.get("retired") and p["id"] not in designs
                  and m._in_area(loc, p)]
        return "location", {"id": loc["id"], "name": loc.get("name", "")}, sorted(inside, key=_name)
    if scope.get("position_class"):
        name = m._class_name(scope["position_class"])
        node = m.s.node(m.org, svc.class_id(m.org, name))
        name = node["name"] if node else name
        return "class", {**m._class_view(name)}, class_fc._class_positions(m, name)
    if scope.get("product_id"):
        return _product_scope(m, m._live_design(scope["product_id"]), scope)
    everything = [p for p in m.s.nodes(m.org, "Position") if not p.get("retired") and p["id"] not in designs]
    return "workspace", {"name": "The whole workspace"}, sorted(everything, key=_name)


def _product_scope(m: Maintenance, top: dict, scope: dict) -> tuple[str, dict, list[dict]]:
    """A product: the positions of the items built from it."""
    nodes = []
    for built in sorted(m._built_tops(top["id"]), key=_name):
        if built.get("retired"):
            continue
        nodes.extend(p for p in m._tree_positions(built["id"]) if not p.get("retired"))
    return "product", {"id": top["id"], "name": top.get("name", ""), "built": len(m._built_tops(top["id"]))}, nodes


def _name(p: dict) -> str:
    return (p.get("name") or "").lower()


# ---- one position's unit: its life, age, and the jobs on it -----------------------------------

def _life(m: Maintenance, pos: dict, fetch, class_only: bool):
    """(dist, unit, label, None) for the position's life model, or (None, None, None, why not)."""
    from backend.services.strategy import StrategyError, _model_from_params

    if not class_only and fetch is not None:
        link = m.in_use_link(pos["id"])
        if link is not None and link["model_type"] == "model":
            doc = fetch("model", link["model_id"])
            r = dict(getattr(doc, "results", None) or {}) if doc is not None else {}
            if doc is not None and getattr(doc, "kind", "distribution") == "distribution" \
                    and (r.get("extras") or {}).get("p") is None:
                dist_id = r.get("distribution_id") or getattr(doc, "distribution_id", "")
                try:
                    dist, label = _model_from_params(dist_id, r.get("params") or [], r.get("extras"))
                    unit = svc._norm_unit(r.get("unit") or (getattr(doc, "spec", None) or {}).get("unit")) or "days"
                    return dist, unit, f"{label} ({link.get('name') or 'model in use'})", None
                except StrategyError:
                    pass
    key = m._class_key(pos)
    node = m.s.node(m.org, svc.class_id(m.org, key)) if key else None
    model = (node or {}).get("model")
    if not model:
        return None, None, None, "no life model (none in use here, and its class has none fitted)"
    if (model.get("extras") or {}).get("p") is not None:
        return None, None, None, "its class's model is a limited-failure-population fit: no renewals from it"
    try:
        dist, label = _model_from_params(model["distribution"], model["params"], model.get("extras"))
    except StrategyError as exc:
        return None, None, None, f"its class's model can't be evaluated: {exc}"
    return dist, svc._norm_unit(model.get("unit")) or "days", f"{label} (the {m._class_label(key)} class's)", None


def _fail_parts(m: Maintenance, position_id: str) -> dict[str, float]:
    """The parts a failure here uses, per job: the replacement part and any critical spare; on a parts
    list naming no replacement part, its components too (what a repair there uses: a bearing listed on
    a bearing position). Consumables never."""
    out: dict[str, float] = {}
    listings = m._listings_at(position_id)
    has_replacement = any(x["role"] == "replacement" for x in listings)
    for listing in listings:
        wanted = listing["role"] == "replacement" or listing.get("critical") or (
            listing["role"] == "component" and not has_replacement)
        if not wanted:
            continue
        pid = m.s.out(m.org, listing["id"], "LISTS")[0]["id"]
        out[pid] = out.get(pid, 0.0) + float(listing["quantity"])
    return out


def _renewal_parts(tasks: list[dict]) -> dict[str, float]:
    """What a failure uses where the parts list says nothing: the spares of the fixed-interval task
    that replaces the same thing (a diaphragm that splits early takes the diaphragm kit)."""
    for task in sorted(tasks, key=lambda t: (t.get("name") or "", t["id"])):
        if task.get("outcome") == "fixed_interval":
            parts = _task_parts(task)
            if parts:
                return parts
    return {}


def _task_parts(task: dict) -> dict[str, float]:
    """The catalogue parts a task's LSA says it uses: its spares, and consumables naming a part."""
    out: dict[str, float] = {}
    r = task.get("resources") or {}
    for line in list(r.get("spares") or []) + list(r.get("consumables") or []):
        pid = line.get("part_id")
        if not pid:
            continue
        try:
            qty = float(line.get("qty") if line.get("qty") not in (None, "") else 1)
        except (TypeError, ValueError):
            continue
        if qty > 0:
            out[pid] = out.get(pid, 0.0) + qty
    return out


def _older_than(task: dict, unit: str, per_day: float) -> float | None:
    """A shutdown task's "only if older than", in the life's unit."""
    older = task.get("older_than")
    if not older:
        return None
    days = float(older["value"]) * svc._DAYS_PER.get(str(older["unit"]), 1.0)
    if unit in svc.CALENDAR_UNITS:
        return days / svc._DAYS_PER[unit]
    return days * per_day  # a calendar age on a clock by use: at its rate


def _package_dates(m: Maintenance, task: dict, entry: dict, end: str, today: str) -> list[str]:
    """A packaged task's visits from today to ``end`` (an overdue one: today)."""
    due = m._package_due(task, entry)
    nxt = due.get("next_due")
    out: list[str] = []
    while nxt and nxt < end and len(out) < 400:
        out.append(max(nxt, today))
        nxt = m._later_visit(entry["root"], entry["package"], entry["member"], nxt)
    return out


def _dated_tasks(m: Maintenance, pos: dict, root, start: date, end: date) -> tuple[dict, list[dict]]:
    """The position's tasks on dates, as the forecast puts them (RePyability's ``Task.due``):
    {task_id: [dates]}, and those it can't put on dates (with why)."""
    from backend.maintenance import position_forecast as pf

    hours_map = pf._hours_map(m, pos, root, start, end + timedelta(days=1))
    rows, skipped, _lib = pf._task_rows(m, pos, hours_map, start, end)
    usage = hours_map["usage"] if hours_map else None
    out = {}
    for lib, _view, task, _basis, first, _by_use in rows:
        due = lib.due(start, end, usage=usage)
        days = [d.isoformat() for d in due.done]
        if first:
            days.insert(0, max(date.fromisoformat(first), start).isoformat())
        out[task["id"]] = days
    return out, skipped


def _renewed_age(m: Maintenance, pos: dict, fitment: dict, unit: str, per_day: float, age: float,
                 tasks: list[dict]) -> tuple[float, str | None]:
    """The item's age counted from the last replacement by a fixed-interval task, when that's after
    it went in: (age, why) or (age, None) unchanged."""
    today = date.fromisoformat(m.today())
    best, why = age, None
    for task in tasks:
        if task.get("outcome") != "fixed_interval":
            continue
        if svc._is_calendar(task["unit"]):
            done = task.get("last_done")
            if done and done >= fitment["from"] and unit in svc.CALENDAR_UNITS:
                since = (today - date.fromisoformat(done)).days / svc._DAYS_PER[unit]
                if since < best:
                    best, why = since, f"from {task['name']}, last done {done}"
            continue
        if unit in svc.CALENDAR_UNITS:
            continue
        counter = m._use_counter(pos["id"], unit)
        if counter is None:
            continue
        readings = svc._readings(m.s, m.org, counter, m.tz)
        if not readings:
            continue
        base = task.get("last_done_reading")
        if base is None:
            base = svc._reading_at(readings, task.get("last_done") or task["start"])
        if base is None:
            base = float(readings[0]["value"])
        last = readings[-1]
        ahead = max(0, (today - date.fromisoformat(last["on"][:10])).days) * per_day
        fitted_at = svc._reading_at(readings, fitment["from"])
        if fitted_at is not None and float(base) < fitted_at:
            continue  # counted from before this item went in
        since = max(0.0, float(last["value"]) + ahead - float(base))
        if since < best:
            best, why = since, f"from {task['name']}'s last change at {float(base):,.6g} {unit}"
    return best, why


def _units(m: Maintenance, positions: list[dict], *, root, horizon_days: float, fetch, class_only: bool,
           leave_out: set, include_all: bool = False) -> tuple[list[dict], list[dict], list[dict]]:
    """Each position as the engine's unit; what isn't forecast (and why); the tasks left off dates."""
    from backend.maintenance import forecast as class_fc

    today = m.today()
    start = date.fromisoformat(today)
    end = start + timedelta(days=math.ceil(horizon_days))
    end_iso = end.isoformat()
    index = m._package_index()
    units, not_forecast, not_dated = [], [], []
    for pos in positions[:MAX_POSITIONS]:
        brief = {"id": pos["id"], "name": pos.get("name", "")}
        tasks = [t for t in m._tasks_on(pos["id"]) if not svc._on_event_only(t)]
        fail_parts = _fail_parts(m, pos["id"]) or _renewal_parts(tasks)
        jobs_wanted = [t for t in tasks if _task_parts(t) or (t.get("outcome") == "fixed_interval")]
        if not fail_parts and not jobs_wanted and not include_all:
            continue
        unit = {"id": pos["id"], "label": pos.get("name", ""), "position": brief, "seed": _seed(pos["id"]),
                "dist": None, "age": 0.0, "per_day": 0.0, "fail_parts": fail_parts, "planned": []}
        life_unit = "days"
        fitment = m.current_fitment(pos["id"])
        if include_all or fail_parts or any(t.get("outcome") == "fixed_interval" for t in jobs_wanted):
            dist, life_unit, label, why = _life(m, pos, fetch, class_only)
            if fitment is None:
                why = "nothing fitted"
            if why is None:
                if life_unit in svc.CALENDAR_UNITS:
                    per = svc._DAYS_PER[life_unit]
                    age, per_day, basis = class_fc._calendar_age(m, pos["id"], fitment) / per, 1.0 / per, "calendar"
                else:
                    use = class_fc._use_age(m, pos["id"], fitment, life_unit, horizon_days)
                    if "reason" in use:
                        why = use["reason"]
                    else:
                        age, per_day, basis = use["age"], use["per_day"], use["basis"]
            if why is None:
                age, renewed = _renewed_age(m, pos, fitment, life_unit, per_day, age, tasks)
                unit.update(dist=dist, age=age, per_day=per_day, model=label, unit=life_unit, rate_basis=basis,
                            age_from=renewed)
            elif fail_parts or include_all:
                not_forecast.append({"position": brief, "reason": why})
        dated, skipped = _dated_tasks(m, pos, root, start, end) if jobs_wanted else ({}, [])
        for s in skipped:
            if any(s["task"]["id"] == t["id"] for t in jobs_wanted):
                not_dated.append({**s, "position": brief})
        for task in jobs_wanted:
            entry = index.get(task["id"])
            package = None
            if entry is not None and entry["active"]:
                days = _package_dates(m, task, entry, end_iso, today)
                package = {"id": entry["root"]["id"], "name": entry["root"]["name"],
                           "shutdown": bool(entry["package"].get("shutdown") or entry["root"].get("shutdown"))}
            elif entry is not None:
                days = []  # held: its package is paused
            else:
                days = dated.get(task["id"], [])
            if task["id"] in leave_out and days:
                days = days[1:]  # a what-if: the next one left out
            renews = task.get("outcome") == "fixed_interval"
            parts = _task_parts(task) or (dict(fail_parts) if renews else {})
            if not parts:
                continue
            min_age = (_older_than(task, life_unit, unit["per_day"]) if package and package["shutdown"] else None)
            for d in days:
                day = (date.fromisoformat(d) - start).days
                if 0 <= day < horizon_days:
                    unit["planned"].append({"day": float(day), "min_age": min_age, "renews": renews, "parts": parts,
                                            "label": task["name"], "task": {"id": task["id"], "name": task["name"]},
                                            "position": brief, **({"package": package} if package else {})})
        unit["planned"].sort(key=lambda p: p["day"])
        if unit["dist"] is None and not unit["planned"]:
            continue
        units.append(unit)
    return units, not_forecast, not_dated


def _fleet_units(m: Maintenance, top: dict, size: int, hours_per_day, horizon_days: float, fetch) -> tuple:
    """A product not yet built: ``size`` new units of each design position, each from new today. A
    life by use ages ``hours_per_day``; a fixed-interval task in the design falls due every interval
    from new (by use at that rate)."""
    units, not_forecast = [], []
    for pos in m._tree_positions(top["id"]):
        if pos.get("retired"):
            continue
        brief = {"id": pos["id"], "name": pos.get("name", "")}
        tasks = [t for t in m._tasks_on(pos["id"]) if not svc._on_event_only(t)
                 and (_task_parts(t) or t.get("outcome") == "fixed_interval")]
        fail_parts = _fail_parts(m, pos["id"]) or _renewal_parts(tasks)
        if not fail_parts and not tasks:
            continue
        dist, life_unit, label, why = _life(m, pos, fetch, False)
        per_day = 0.0
        if why is None:
            if life_unit in svc.CALENDAR_UNITS:
                per_day = 1.0 / svc._DAYS_PER[life_unit]
            elif life_unit == "hours" and hours_per_day:
                per_day = float(hours_per_day)
            else:
                why = f"this life is in {life_unit}: say how many {life_unit} a day each unit runs"
        if why and fail_parts:
            not_forecast.append({"position": brief, "reason": why})
            dist = None
        planned = []
        for task in tasks:
            renews = task.get("outcome") == "fixed_interval"
            parts = _task_parts(task) or (dict(fail_parts) if renews else {})
            unit_t = svc._norm_unit(task["unit"]) or "days"
            if unit_t in svc.CALENDAR_UNITS:
                every = float(task["interval"]) * svc._DAYS_PER[unit_t]
            elif unit_t == "hours" and hours_per_day:
                every = float(task["interval"]) / float(hours_per_day)
            else:
                continue
            k = 1
            while parts and every > 0 and k * every < horizon_days and k < 400:
                planned.append({"day": float(math.floor(k * every)), "renews": renews, "parts": parts,
                                "label": task["name"], "task": {"id": task["id"], "name": task["name"]},
                                "position": brief})
                k += 1
        for n in range(size):
            units.append({"id": f"{pos['id']}#{n + 1}", "label": f"{pos.get('name', '')} (unit {n + 1})",
                          "position": brief, "seed": _seed(f"{pos['id']}#{n + 1}"), "dist": dist, "age": 0.0,
                          "per_day": per_day, "fail_parts": fail_parts,
                          "planned": [dict(p) for p in planned], "model": label, "unit": life_unit})
    return units, not_forecast


# ---- the parts ---------------------------------------------------------------------------------

def _usable(m: Maintenance, pt: dict) -> float:
    """Usable stock of a part: it, what supersedes it and what's interchangeable, in every store."""
    chain = m._successors(pt)
    skip = {pt["id"]} | {c["id"] for c in chain}
    alts = {}
    for src in [pt] + chain:
        for a in m.s.out(m.org, src["id"], "INTERCHANGEABLE"):
            if a["id"] not in skip:
                alts[a["id"]] = a
    return sum(m._part_brief(x)["on_hand"] for x in [pt, *chain, *alts.values()])


def _counted(m: Maintenance, pt: dict) -> dict:
    """When the part's stock was last counted: per store, and the oldest of them (None when a store
    holding it, or every store, was never counted)."""
    rows = []
    for st in m._stocks(pt["id"]):
        loc = m.s.out(m.org, st["id"], "AT")[0]
        rows.append({"location": {"id": loc["id"], "name": loc["name"]}, "quantity": st["quantity"],
                     "counted": st.get("counted")})
    dated = [r["counted"]["on"] for r in rows if r.get("counted")]
    oldest = min(dated) if dated and len(dated) == len(rows) else None
    return {"stores": sorted(rows, key=lambda r: r["location"]["name"].lower()), "counted_on": oldest,
            "never_counted": not dated}


def _settings(pt: dict, level, lead) -> dict:
    if level is not None:
        sl, sl_basis = level, "request"
    elif pt.get("service_level") is not None:
        sl, sl_basis = float(pt["service_level"]), "part"
    else:
        sl, sl_basis = spares.DEFAULT_SERVICE_LEVEL, "default"
    if lead is not None:
        lt, lt_basis = lead, "request"
    elif pt.get("lead_time_days") is not None:
        lt, lt_basis = float(pt["lead_time_days"]), "part"
    else:
        lt, lt_basis = float(DEFAULT_LEAD_DAYS), "assumed"
    return {"service_level": sl, "service_level_basis": sl_basis, "lead_time_days": lt, "lead_time_basis": lt_basis}


def options(service_level=None, lead_time_days=None, review_days=None, months=12) -> dict:
    try:
        months = int(months if months not in (None, "") else 12)
    except (TypeError, ValueError):
        raise Invalid("months must be a whole number.") from None
    if not 1 <= months <= MAX_MONTHS:
        raise Invalid(f"The horizon is 1 to {MAX_MONTHS} months.")
    try:
        return {"service_level": spares.service_level(service_level),
                "lead_time_days": spares.duration(lead_time_days, "lead time (days)", spares.MAX_LEAD_DAYS),
                "review_days": spares.duration(review_days, "review period (days)", spares.MAX_LEAD_DAYS) or 0.0,
                "months": months}
    except spares.SparesError as exc:
        raise Invalid(str(exc)) from None


def scope_of(m: Maintenance, rid=None, root=None, fleet_size=None, hours_per_day=None) -> dict:
    """The scope an id names: a position (a product's design top: the product), a location, else a
    position class's name; no id, the whole workspace."""
    if not rid:
        return {}
    node = m.s.node(m.org, str(rid))
    if node is not None and node.get("label") == "Position":
        if node.get("design") and m._parent(node["id"]) is None:
            return {"product_id": node["id"], "fleet_size": fleet_size, "hours_per_day": hours_per_day}
        return {"position_id": node["id"], "root": root, "fleet_size": fleet_size, "hours_per_day": hours_per_day}
    if node is not None and node.get("label") == "Location":
        return {"location_id": node["id"]}
    if m._resolve_class(rid) is None:
        raise svc.NotFound(f"No position, location or position class {rid}")
    return {"position_class": rid}


def build(m: Maintenance, scope: dict, *, horizon_days: float, fetch=None, leave_out=()) -> dict:
    """The units in scope and their simulated events: what every answer reads."""
    kind, what, positions = _scope(m, scope)
    leave = {str(x) for x in (leave_out or [])}
    fleet_size = None
    if kind == "product" and not what.get("built"):
        size = scope.get("fleet_size")
        if size not in (None, ""):
            try:
                fleet_size = int(size)
            except (TypeError, ValueError):
                raise Invalid("The planned fleet size must be a whole number.") from None
            if not 1 <= fleet_size <= MAX_FLEET:
                raise Invalid(f"The planned fleet size is 1 to {MAX_FLEET}.")
    if fleet_size:
        top = m._get(what["id"], "Position")
        units, not_forecast = _fleet_units(m, top, fleet_size, scope.get("hours_per_day"), horizon_days, fetch)
        not_dated = []
    else:
        units, not_forecast, not_dated = _units(m, positions, root=scope.get("root") or None,
                                                horizon_days=horizon_days, fetch=fetch,
                                                class_only=kind == "class", leave_out=leave)
    try:
        events = engine.simulate(units, horizon_days)
    except engine.SparesYearError as exc:
        raise Invalid(str(exc)) from None
    return {"kind": kind, "what": what, "positions": len(positions), "units": units, "events": events,
            "not_forecast": not_forecast, "not_dated": not_dated, "fleet_size": fleet_size,
            "horizon_days": horizon_days}


def _part_ids(units: list[dict]) -> list[str]:
    seen: dict[str, None] = {}
    for u in units:
        for pid in u["fail_parts"]:
            seen.setdefault(pid)
        for p in u["planned"]:
            for pid in p["parts"]:
                seen.setdefault(pid)
    return list(seen)


def part_rows(m: Maintenance, ctx: dict, opts: dict, part_ids=None) -> list[dict]:
    """Each part's row of the answer."""
    today = date.fromisoformat(m.today())
    units, events, horizon = ctx["units"], ctx["events"], ctx["horizon_days"]
    rows = []
    for pid in part_ids or _part_ids(units):
        pt = m.s.node(m.org, pid, "Part")
        if pt is None:
            continue
        st = _settings(pt, opts["service_level"], opts["lead_time_days"])
        usable = float(_usable(m, pt))
        ans = engine.answer_part(events, units, pid, horizon_days=horizon, lead_days=st["lead_time_days"],
                                 level=st["service_level"], usable=usable, review_days=opts["review_days"],
                                 today=today, months=opts.get("months"))
        on_failure = sorted({u["position"]["name"] for u in units if u["fail_parts"].get(pid)}, key=str.lower)
        on_jobs = sorted({p["position"]["name"] for u in units for p in u["planned"] if p["parts"].get(pid)},
                         key=str.lower)
        brief = m._part_brief(pt)
        label = f"{pt.get('part_number') or ''} {pt.get('name') or ''}".strip()
        row = {"part": {k: brief.get(k) for k in ("id", "part_number", "name", "unit", "unit_cost")},
               **st, "review_days": opts["review_days"], **ans, **_counted(m, pt),
               "positions": {"failures": on_failure, "planned": on_jobs},
               "critical": any(x.get("critical") for x in m._listings_of(pid))}
        horizon_words = f"the next {opts['months']} month{'s' if opts['months'] != 1 else ''}"
        row["summary"] = engine.words(row, label, st["service_level"], st["lead_time_days"], horizon_words,
                                      pt.get("unit") or "")
        if st["lead_time_basis"] == "assumed":
            row["summary"] += f" No lead time is set for this part: {DEFAULT_LEAD_DAYS} days assumed."
        rows.append(row)
    rows.sort(key=lambda r: (not r["critical"], (r["part"]["part_number"] or "").lower()))
    return rows


def spares_year(m: Maintenance, scope: dict | None = None, *, months=12, service_level=None, lead_time_days=None,
                review_days=None, fetch=None, leave_out=(), curves: bool = False) -> dict:
    """Spares for the year (or ``months``) in a scope: one row per part with its demand (failures +
    planned), the stock to hold for its lead time at its service level, the usable stock and when it
    was counted, what to order now and by when, and what to buy over the horizon."""
    opts = options(service_level, lead_time_days, review_days, months)
    horizon = opts["months"] * 30.4375
    ctx = build(m, scope or {}, horizon_days=horizon, fetch=fetch, leave_out=leave_out)
    rows = part_rows(m, ctx, opts)
    if not curves:
        for r in rows:
            r.pop("risk_curve", None)
    today = m.today()
    end = (date.fromisoformat(today) + timedelta(days=math.ceil(horizon) - 1)).isoformat()
    notes = ["Usable stock counts a part's successors and interchangeable parts in every store: one site.",
             "A failed item is replaced at once with a like one; a planned replacement renews it.",
             "Each planned job is assumed done on its date."]
    if ctx["fleet_size"]:
        notes.append(f"No items are built from it yet: a planned fleet of {ctx['fleet_size']}, each new today.")
    if any(u.get("age_from") for u in ctx["units"]):
        notes.append("An item renewed by a fixed-interval task counts its age from its last replacement.")
    return {"scope": ctx["kind"], "of": ctx["what"], "today": today, "end": end, "months": opts["months"],
            "horizon_days": horizon, "sims": ctx["events"]["sims"], "rule": engine.RULE,
            "service_level": opts["service_level"], "lead_time_days": opts["lead_time_days"],
            "review_days": opts["review_days"], "fleet_size": ctx["fleet_size"],
            "parts": rows, "n_positions": ctx["positions"], "n_units": len(ctx["units"]),
            "not_forecast": ctx["not_forecast"], "not_dated": ctx["not_dated"],
            "units": [_unit_brief(u) for u in ctx["units"][:200]], "notes": notes}


def _unit_brief(u: dict) -> dict:
    return {"position": u["position"], "label": u["label"], "model": u.get("model"), "unit": u.get("unit"),
            "age": round(float(u["age"]), 3) if u.get("dist") is not None else None,
            "per_day": round(float(u["per_day"]), 4) if u.get("dist") is not None else None,
            "age_from": u.get("age_from"),
            "planned": [{"day": p["day"], "task": p.get("label"), "min_age": p.get("min_age")}
                        for p in u["planned"][:20]]}


CSV_COLUMNS = ("part_number", "name", "critical", "demand_mean", "demand_p10", "demand_p90", "failures_mean",
               "planned_mean", "service_level", "lead_time_days", "hold", "reorder_at", "usable_now", "counted_on",
               "order_now", "next_order_qty", "next_order_by", "buy_for_year", "buy_high_case")


def csv_text(out: dict) -> str:
    """The answer as CSV: one row a part, numbers as plain numbers (no units in the cells)."""
    import csv
    import io

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(CSV_COLUMNS)
    for r in out["parts"]:
        nxt = r["order_by"][0] if r["order_by"] else {}
        d = r["demand"]
        w.writerow([r["part"]["part_number"], r["part"]["name"], int(bool(r["critical"])), _r(d["mean"]),
                    _r(d["p10"]), _r(d["p90"]), _r(d["failures"]), _r(d["planned"]), r["service_level"],
                    _r(r["lead_time_days"]), _r(r["hold"]), "" if r["reorder_at"] is None else _r(r["reorder_at"]),
                    _r(r["usable_now"]), r["counted_on"] or "", _r(r["order_now"]), _r(nxt.get("qty", "")),
                    nxt.get("by", ""), _r(r["buy_for_year"]), _r(r["buy_high_case"])])
    return buf.getvalue()


def _r(v):
    if v in ("", None):
        return ""
    v = float(v)
    return int(v) if v.is_integer() else round(v, 3)


# ---- a position class's Spares (its forecast's spares, on this engine) -------------------------

def class_spares(m: Maintenance, name: str, positions: list[dict], periods: int, days: float, starts: list[str],
                 opts: dict) -> tuple[list[dict], dict, dict]:
    """The class forecast's spares rows and stock levels (#31), from failures and planned jobs:
    (rows, stocking meta, {"failures": sims x periods failures, "planned": bool}) for its headline."""
    import numpy as np

    from backend.maintenance import forecast as class_fc

    meta = {"service_level": opts["service_level"], "default_service_level": spares.DEFAULT_SERVICE_LEVEL,
            "lead_time_days": opts["lead_time_days"], "default_lead_time_days": DEFAULT_LEAD_DAYS,
            "review_days": opts["review_days"], "note": class_fc.STOCKING_NOTE, "rule": engine.RULE}
    span = periods * days
    units, _nf, not_dated = _units(m, positions, root=None, horizon_days=span, fetch=None, class_only=True,
                                   leave_out=set(), include_all=True)
    pids = _part_ids(units)[:class_fc.MAX_PARTS]
    inputs = {pid: class_fc._part_stocking(m.s.node(m.org, pid) or {}, opts) for pid in pids}
    longest = max([i["window_days"] for i in inputs.values()] + [0.0])
    horizon = span + longest
    if longest > 0:
        units, _nf, not_dated = _units(m, positions, root=None, horizon_days=horizon, fetch=None, class_only=True,
                                       leave_out=set(), include_all=True)
    try:
        events = engine.simulate(units, horizon)
    except engine.SparesYearError as exc:
        return [], {**meta, "error": str(exc)}, {"failures": None, "planned": False, "per_unit": {}}
    meta["sims"] = events["sims"]
    ones = np.where(events["kind"] == 0, 1.0, 0.0)
    fails = np.stack([engine.window(events, ones, k * days, (k + 1) * days) for k in range(periods)], axis=1) \
        if events["sims"] else np.zeros((1, periods))
    planned_renewals = any(p.get("renews") for u in units for p in u["planned"])
    per_unit = {}
    sims = max(1, events["sims"])
    in_span = (events["kind"] == 0) & (events["t"] < span)
    for i, u in enumerate(units):
        mine = in_span & (events["unit"] == i)
        per_unit[u["id"]] = {"expected": float(mine.sum()) / sims,
                             "prob_any": float(np.unique(events["sim"][mine]).size) / sims}
    today = date.fromisoformat(m.today())
    word = f"{periods} {'month' if abs(days - 30.4375) < 1e-6 else 'period'}"
    rows = []
    listings = {}
    for u in units:
        for listing in m._listings_at(u["id"]):
            pid = m.s.out(m.org, listing["id"], "LISTS")[0]["id"]
            listings.setdefault(pid, []).append(m._listing_view(listing))
    for pid in pids:
        pt = m.s.node(m.org, pid, "Part")
        if pt is None:
            continue
        inp = inputs[pid]
        w = engine.part_weights(events, units, pid)
        per = [engine.window(events, w, k * days, (k + 1) * days) for k in range(periods)]
        cum = np.cumsum(np.stack(per, axis=1), axis=1)
        have = float(_usable(m, pt))
        cumulative = [{**class_fc._summary(cum[:, k], (0.1, 0.5, 0.9, 0.95)),
                       "prob_covered": float((cum[:, k] <= have + 1e-9).mean())} for k in range(periods)]
        covered = sum(1 for c in cumulative if c["p90"] <= have + 1e-9)
        views = listings.get(pid, [])
        roles = sorted({v["role"] for v in views} | ({"task"} if any(p["parts"].get(pid) and not
                                                                     u["fail_parts"].get(pid) for u in units
                                                                     for p in u["planned"]) else set()))
        unit_text = pt.get("unit") or "each"
        fail_mean = float(engine.window(events, w, 0.0, span, kind=0).mean())
        plan_mean = float(engine.window(events, w, 0.0, span, kind=1).mean())
        users = {u["id"] for u in units if u["fail_parts"].get(pid) or any(p["parts"].get(pid) for p in u["planned"])}
        words = (f"≈ {class_fc._num(cumulative[-1]['mean'])} needed over the next {word}s (likely "
                 f"{cumulative[-1]['p10']:g}–{cumulative[-1]['p90']:g})")
        if plan_mean > 1e-9:
            words += f": {class_fc._num(fail_mean)} failures + {class_fc._num(plan_mean)} planned"
        words += f"; {have:g} usable in stock."
        if covered < periods:
            words += (f" Stock covers {covered} period{'s' if covered != 1 else ''} at the likely high end "
                      f"(P90); {cumulative[0]['prob_covered']:.0%} chance it covers the first.")
        if len(users) < len({u["id"] for u in units}):
            words += f" Counts the {len(users)} position{'s' if len(users) != 1 else ''} whose parts list or tasks name it."
        brief = m._part_brief(pt)
        row = {
            "part": brief, "roles": roles, "critical": any(v["critical"] for v in views),
            "positions": len(users), "position_names": sorted({u["label"] for u in units if u["id"] in users},
                                                              key=str.lower),
            "per_job": sorted({float(v["quantity"]) for v in views}
                              | {float(p["parts"][pid]) for u in units for p in u["planned"] if p["parts"].get(pid)}),
            "unit": unit_text, "usable_on_hand": have,
            "min_on_hand": max([v["min_on_hand"] for v in views if v["min_on_hand"] is not None], default=None),
            "use_instead": next((v["use_instead"] for v in views if v["use_instead"]), None),
            "stock": m._stock_rows(m._stocks(pid)), **{k: v for k, v in m._count_age(m._stock_rows(m._stocks(pid))).items()},
            "expected": cumulative[-1]["mean"], "interval": [cumulative[-1]["p10"], cumulative[-1]["p90"]],
            "failures_expected": fail_mean, "planned_expected": plan_mean,
            "per_period": [class_fc._summary(x) for x in per], "cumulative": cumulative, "covered_periods": covered,
            "short": cumulative[-1]["p90"] > have + 1e-9, "summary": words,
        }
        level = inp["service_level"]
        protect = [spares.Demand.from_samples(engine.window(events, w, k * days, k * days + inp["window_days"]))
                   for k in range(periods)]
        lead = None if inp["repairable"] else [
            spares.Demand.from_samples(engine.window(events, w, k * days, k * days + inp["lead_time_days"]))
            for k in range(periods)]
        now = spares.answer(protect[0], lead[0] if lead else None, have, level, pt.get("unit_cost"))
        plan = [{"start": starts[k], "hold": protect[k].quantile(level),
                 "reorder_at": lead[k].quantile(level) if lead else None, "expected_demand": protect[k].mean}
                for k in range(periods)]
        if inp["repairable"]:
            window_words = f"the repair turnaround ({class_fc._days(inp['window_days'])})"
        elif inp["review_days"]:
            window_words = f"the lead time and review period ({class_fc._days(inp['window_days'])})"
        else:
            window_words = f"the lead time ({class_fc._days(inp['lead_time_days'])})"
        said = spares.sentence(now, level, window_words, unit_text, inp["repairable"], inp["review_days"] > 0)
        if inp["lead_time_basis"] == "assumed" and not inp["repairable"]:
            said += f" No lead time is set for this part: {DEFAULT_LEAD_DAYS} days assumed."
        jobs = engine._jobs(events, w, units, pid, horizon)
        order_now = max(0.0, now["hold"] - have)
        by = [] if inp["repairable"] else engine.order_plan(jobs, have, now["hold"], order_now, inp["window_days"],
                                                            inp["lead_time_days"], today)
        row["stocking"] = {**inp, **now, "per_period": plan, "summary": said, "order_now": order_now,
                           "order_by": by, "planned_in_window": protect[0].mean - float(
                               engine.window(events, w, 0.0, inp["window_days"], kind=0).mean())}
        rows.append(row)
    rows.sort(key=lambda r: ("replacement" not in r["roles"], not r["critical"], r["part"]["part_number"].lower()))
    return rows, {**meta, "not_dated": not_dated[:50]}, {"failures": fails, "planned": planned_renewals,
                                                         "per_unit": per_unit}


# ---- a work package's next visit: its parts against stock and lead time -----------------------

def package_parts(m: Maintenance, package_id: str, *, fetch=None, leave_out=(), service_level=None) -> dict:
    """The parts the package's next visit needs (its tasks' LSA spares, and what a replacement there
    uses), against usable stock, and when an order placed today arrives: before the visit or after,
    and the chance that what's wanted before it lands (the visit's jobs and failures everywhere the
    part is used) is more than the stock usable now. ``leave_out``: tasks taken off this visit (a
    what-if)."""
    pkg = m._live_package(package_id)
    root = m._package_chain(pkg)[-1]
    visits = m._package_next_visits(root, 1)
    if not visits:
        return {"package": {"id": root["id"], "name": root["name"]}, "visit": None, "parts": [],
                "summary": "No visit coming up: the package is paused or has no next date."}
    visit = visits[0]
    today = m.today()
    start = date.fromisoformat(today)
    day = max(0, (date.fromisoformat(visit["on"]) - start).days)
    leave = {str(x) for x in (leave_out or [])}
    lines: dict[str, list[dict]] = {}
    for tid in visit["task_ids"]:
        task = m.s.node(m.org, tid, "Task")
        if task is None:
            continue
        subject = svc._subject(m.s, m.org, task) or {}
        fail = _fail_parts(m, subject["id"]) if subject.get("label") == "Position" else {}
        parts = _task_parts(task) or (dict(fail) if task.get("outcome") == "fixed_interval" else {})
        for pid, qty in parts.items():
            lines.setdefault(pid, []).append({
                "task": {"id": tid, "name": task["name"]}, "position": {"id": subject.get("id"),
                                                                        "name": subject.get("name", "")},
                "qty": qty, "older_than": task.get("older_than") if pkg.get("shutdown") or root.get("shutdown")
                else None, "left_out": tid in leave})
    try:
        level = spares.service_level(service_level)
    except spares.SparesError as exc:
        raise Invalid(str(exc)) from None
    found = {pid: m.s.node(m.org, pid, "Part") for pid in lines}
    found = {pid: pt for pid, pt in found.items() if pt is not None}
    longest = max([_settings(pt, level, None)["lead_time_days"] for pt in found.values()] + [0.0])
    ctx = build(m, {}, horizon_days=max(longest, day + 1.0) + 1.0, fetch=fetch, leave_out=leave) if found else None
    rows = []
    for pid, jobs in sorted(lines.items(), key=lambda kv: (found.get(kv[0]) or {}).get("part_number", "")):
        pt = found.get(pid)
        if pt is None:
            continue
        st = _settings(pt, level, None)
        lead = st["lead_time_days"]
        # Each job's chance of being done (a shut's "only if older" may skip it).
        chances = {}
        for u in ctx["units"]:
            for j, p in enumerate(u["planned"]):
                if p.get("task") and p["day"] == float(day) and p["parts"].get(pid):
                    hit = (ctx["events"]["kind"] == 1) & (ctx["events"]["unit"] == ctx["units"].index(u)) \
                        & (ctx["events"]["job"] == j)
                    chances[p["task"]["id"]] = float(hit.sum()) / ctx["events"]["sims"]
        for j in jobs:
            j["chance_done"] = 0.0 if j["left_out"] else chances.get(j["task"]["id"], 1.0)
            # A shutdown task skipped on a younger item: it's that young whatever happens before the shut.
            j["too_young"] = not j["left_out"] and j["chance_done"] == 0.0
        needed = sum(j["qty"] * j["chance_done"] for j in jobs)
        most = sum(j["qty"] for j in jobs if j["chance_done"] > 0)
        usable = float(_usable(m, pt))
        arrives = (start + timedelta(days=math.ceil(lead))).isoformat()
        risk = engine.chance_short_before(ctx["events"], ctx["units"], pid, usable, lead)
        rows.append({"part": {k: pt.get(k) for k in ("id", "part_number", "name", "unit")}, "jobs": jobs,
                     "needed": needed, "needed_most": most, "usable_now": usable, "short": most > usable + 1e-9,
                     "left_after": usable - needed, **st, "order_today_arrives": arrives,
                     "arrives_before_visit": arrives <= visit["on"],
                     "chance_short_before_arrival": risk, **_counted(m, pt)})
    words = f"Next visit {engine._short(visit['on'])}: {len(rows)} part{'s' if len(rows) != 1 else ''}."
    short = [r for r in rows if r["short"]]
    if short:
        words += " Short: " + ", ".join(f"{r['part']['part_number']} (needs {r['needed_most']:g}, "
                                         f"{r['usable_now']:g} usable)" for r in short) + "."
    return {"package": {"id": root["id"], "name": root["name"], "shutdown": bool(root.get("shutdown"))},
            "visit": {"on": visit["on"], "tasks": len(visit["task_ids"])}, "today": today,
            "leave_out": sorted(leave), "parts": rows, "summary": words,
            "rule": ("The chance of running out counts every use of the part before an order placed today lands "
                     "(this visit's jobs and failures wherever the part is used) against the stock usable now.")}
