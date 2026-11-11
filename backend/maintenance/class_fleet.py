"""An item class's fleet: the positions whose fitted item is of the class (or of
a class inside it) as one table, and each one's risk now.

The Explorer arranged by Classes shows the item-class taxonomy; choosing a
class shows this table beside the tree. Each member is a position with the
item fitted there, the duty it does (its position class), the item's age and
the last reading of the measurement being watched. A member whose position
has a condition and life model (linked on its Modelling tab, or through its
position class) is scored from that position's own data and nothing else:

* the item's age since new: from its in-service date, else the day it was
  first fitted anywhere, to today (the workspace's);
* its readings: the condition measurement point on the position, or on the
  item, in the model's reading unit, each reading's date turned into the
  item's age then (a point on the position counts from the day this item went
  in: earlier readings were another item's);
* its covariates: the value conditions that reach it, matched by name.

The tree and the model are independent: a fleet can mix members with a model,
with different models and with none. The table's ages and lives left are in
days whatever each model's own time unit (only models in calendar time are
scored), so the rows read as one table. A member that can't be scored says
why and what to do. The statistics are the model page's (``backend.joint``):
nothing is fitted here.

One position on its own (the Explorer's Condition monitoring tab on a
position) is the same read for that position alone, whatever its item's class:
``position``.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import date

#: The most members scored in one read (each a prediction); the rest are
#: listed with their age and reading, and the answer says so.
MAX_SCORED = 200
#: The most readings of one member a prediction takes (its latest).
MAX_READINGS_EACH = 500
#: The table's time unit and the stretches its risk columns look ahead.
AGE_UNIT = "Days"
#: Model time units an item's calendar age can be put in. Hours and smaller
#: are left out: a model in hours counts running hours, not the calendar.
CALENDAR = ("day", "week", "month", "year")
RISK_KEYS = ("survival", "risk", "median_remaining", "median_reached", "marker_now")


def _sv():
    from backend.maintenance import service

    return service


def _key(text) -> str:
    """A name for matching: case, spacing, underscores and hyphens aside."""
    return re.sub(r"[\s_\-]+", " ", str(text or "")).strip().lower()


def _unit_key(text) -> str:
    return re.sub(r"\s+", "", str(text or "")).lower()


def _round(v, sig: int = 6):
    return None if v is None else float(f"{float(v):.{sig}g}")


def _days(a: str, b: str) -> int:
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def item_class_ids(m) -> dict[str, str]:
    """Each classed item's effective item class (its own, else its part's), by
    item id, in two reads."""
    classed = dict(m.s.pairs(m.org, "CLASSED_AS"))
    part_of = dict(m.s.pairs(m.org, "OF_PART"))
    out = dict(classed)
    for item_id, part_id in part_of.items():
        if item_id not in out and part_id in classed:
            out[item_id] = classed[part_id]
    return out


def _members(m, class_id: str, within: set[str] | None = None) -> tuple[dict, list[tuple[dict, dict, dict, dict]]]:
    """The class, and ``(position, fitment, item, item class)`` for every live
    position whose fitted item is of the class or a class inside it, by name.
    ``within``: only those positions (one asset's tree)."""
    node = m._get(class_id, "ItemClass")
    inside = {c["id"]: c for c in m._class_subtree(class_id)}
    classes = item_class_ids(m)
    found = []
    for p in m.s.nodes(m.org, "Position"):
        if p.get("retired") or (within is not None and p["id"] not in within):
            continue
        f = m.current_fitment(p["id"])
        item = f and next((x for x in m.s.inn(m.org, f["id"], "IN") if x["label"] == "Item"), None)
        if item is not None and classes.get(item["id"]) in inside:
            found.append((p, f, item, inside[classes[item["id"]]]))
    return node, sorted(found, key=lambda x: ((x[0].get("name") or "").lower(), x[0]["id"]))


def _member(m, position_id: str) -> tuple[dict, tuple[dict, dict, dict, dict | None] | None]:
    """One position, and its ``(position, fitment, item, item class)``: the item
    fitted there now, whatever its class (None with no class); None with nothing
    fitted."""
    p = m._get(position_id, "Position")
    f = m.current_fitment(position_id)
    item = f and next((x for x in m.s.inn(m.org, f["id"], "IN") if x["label"] == "Item"), None)
    if item is None:
        return p, None
    class_id = item_class_ids(m).get(item["id"])
    return p, (p, f, item, m.s.node(m.org, class_id, "ItemClass") if class_id else None)


def position_model(m, fetch, position_id: str):
    """The condition and life model that scores a position: the one linked to
    it (the one in use, else the latest linked), else its position class's
    model when that is one. None with neither."""
    from backend.services import joint as joint_service

    found = []
    for x in m.position_models(position_id):
        if x.get("model_type") != "model":
            continue
        doc = fetch("model", x.get("model_id"))
        if doc is not None and doc.kind == joint_service.KIND:
            found.append((bool(x.get("in_use")), x.get("linked_on") or "", doc))
    if found:
        return max(found, key=lambda t: t[:2])[2]
    cm = m.class_model_of(position_id)
    doc = cm and fetch("model", cm.get("model_id"))
    return doc if doc is not None and doc.kind == joint_service.KIND else None


def _since(m, item: dict, fitment: dict) -> str:
    """The day the item's age counts from: its in-service date, else the day it
    was first fitted anywhere."""
    own = (item.get("in_service_date") or {}).get("date")
    if own:
        return own
    return min([f["from"] for f in m._fitments_of(item["id"]) if f.get("from")] or [fitment["from"]])


def _condition_points(m, position_id: str, item_id: str) -> list[dict]:
    """The live condition points on the position and on the item fitted there."""
    out = []
    for where, nid in (("position", position_id), ("item", item_id)):
        for x in m.s.inn(m.org, nid, "ON"):
            if x["label"] == "MeasurementPoint" and not x.get("retired") and x.get("kind", "counter") == "condition":
                out.append({**x, "_on": where})
    return sorted(out, key=lambda x: ((x.get("name") or "").lower(), x["id"]))


def _pick_point(points: list[dict], marker: str, marker_unit: str) -> tuple[dict | None, str | None]:
    """The point holding the model's reading: the one in the model's unit (by
    name when several are), or why none can be used."""
    what = marker or "the reading"
    unit_words = f" ({marker_unit})" if marker_unit else ""
    if not points:
        return None, (f"No measurement point for {what}{unit_words}. Add a condition point on the position or its "
                      "item and record readings.")
    named = [x for x in points if marker and _key(marker) in _key(x.get("name"))]
    same = points
    if marker_unit:
        same = [x for x in points if _unit_key(x.get("unit")) == _unit_key(marker_unit)]
        if not same:
            got = ", ".join(f"{x['name']} in {x.get('unit') or 'no unit'}" for x in (named or points)[:3])
            return None, (f"Units don't match: the model reads {what} in {marker_unit}; here there is {got}. "
                          f"Record {what} on a point in {marker_unit}.")
    if len(same) == 1:
        return same[0], None
    both = [x for x in same if x in named]
    if len(both) == 1:
        return both[0], None
    names = ", ".join(x["name"] for x in (both or same)[:4])
    return None, (f"More than one measurement point could be {what}{unit_words}: {names}. Name one of them "
                  f"“{what}” so it is clear which to use.")


def _readings(m, point: dict, start: str, today: str) -> list[dict]:
    """The point's readings from ``start`` to today, oldest first."""
    rows = _sv()._readings(m.s, m.org, point, m.tz)
    return [{"on": r["on"], "value": float(r["value"])} for r in rows
            if r.get("on") and r.get("value") is not None and start <= r["on"] <= today]


def _covariates(m, node: dict, names: list[str]) -> tuple[dict, list[str]]:
    """The model's covariates from the value conditions that reach the node
    (its own first, then from above), matched by name or code; and those with
    no value."""
    by: dict[str, float] = {}
    if names:
        for e in m._effective_conditions(node):
            if e.get("excluded") or e.get("value") is None:
                continue
            for k in (_key(e["condition"].get("name")), _key(e["condition"].get("code"))):
                if k:
                    by.setdefault(k, e["value"])
    found = {n: float(by[_key(n)]) for n in names if _key(n) in by}
    return found, [n for n in names if n not in found]


def _model_view(doc) -> dict:
    r = doc.results or {}
    return {"id": doc.id, "name": doc.name, "path": f"/models/joint/{doc.id}", "unit": r.get("unit") or "",
            "marker": r.get("marker") or "", "marker_unit": r.get("marker_unit") or "",
            "covariates": list(r.get("covariates") or [])}


def _scorer(m, db, owners, hidden):
    """What scores a member, for one read: ``row_for(member, with_curves, score)``
    gives its row, and ``models`` collects the models the rows used."""
    from backend import joint
    from backend.fitting import FitError
    from backend.maintenance import position_models as pm
    from backend.services import joint as joint_service
    from backend.units import normalize_unit

    fetch = pm.fetcher(db, owners, hidden)
    today = m.today()
    horizons = joint.horizons(AGE_UNIT)
    models: dict[str, dict] = {}
    live: dict[str, object] = {}

    def loaded(doc):
        """The model ready to predict, or why it can't be used here."""
        if doc.id not in live:
            unit = (doc.results or {}).get("unit") or ""
            if normalize_unit(unit) not in CALENDAR:
                live[doc.id] = (f"Units don't match: “{doc.name}” counts age in {unit.lower() or 'its own unit'}, "
                                "and an item's age here is calendar time. Risk needs a model with ages in days, "
                                "weeks, months or years.")
            else:
                try:
                    live[doc.id] = joint_service.live(doc)
                except FitError as err:
                    live[doc.id] = f"“{doc.name}” can't be used: {err}"
        return live[doc.id]

    def row_for(x, with_curves: bool = False, score: bool = True) -> dict:
        p, f, item, cls = x
        since = _since(m, item, f)
        age_days = max(_days(since, today), 0)
        doc = position_model(m, fetch, p["id"])
        row = {"position": {"id": p["id"], "name": p.get("name") or "", "tag": p.get("tag") or "",
                            "position_class": p.get("position_class") or ""},
               "item": {"id": item["id"], "name": item.get("name") or "", "serial": item.get("serial") or ""},
               "item_class": cls and {"id": cls["id"], "name": cls["name"]},
               "in_service": since, "age": float(age_days), "model": None, "point": None, "last_reading": None,
               "n_readings": 0, "covariates": {}, "scored": False, "why": None}
        points = _condition_points(m, p["id"], item["id"])
        results = (doc.results or {}) if doc is not None else {}
        marker, marker_unit = results.get("marker") or "", results.get("marker_unit") or ""
        if doc is not None:
            row["model"] = {"id": doc.id, "name": doc.name}
            models.setdefault(doc.id, {**_model_view(doc), "positions": 0})["positions"] += 1
            point, point_why = _pick_point(points, marker, marker_unit)
        else:
            point, point_why = (points[0] if len(points) == 1 else None), None
        readings = []
        if point is not None:
            row["point"] = {"id": point["id"], "name": point.get("name") or "", "unit": point.get("unit", ""),
                            "on": point["_on"]}
            # A point on the position counts from the day this item went in.
            start = max(since, f["from"]) if point["_on"] == "position" else since
            readings = _readings(m, point, start, today)
            row["n_readings"] = len(readings)
            row["last_reading"] = {**readings[-1], "unit": point.get("unit", "")} if readings else None
        if doc is None:
            return row
        names = list(results.get("covariates") or [])
        values, missing = _covariates(m, item, names)
        row["covariates"] = values
        model = loaded(doc)
        if isinstance(model, str):
            row["why"] = model
        elif point is None:
            row["why"] = point_why
        elif not readings:
            row["why"] = (f"No {marker or 'condition'} readings since this item went into service ({since}). "
                          f"Record one on “{point.get('name')}”.")
        elif missing:
            row["why"] = (f"No value for {', '.join(missing)}. Apply a value condition named “{missing[0]}” to the "
                          "position (or above it) with its value here.")
        elif not score:
            row["why"] = f"Risk is worked out for the first {MAX_SCORED} members by name; open this one for its own."
        if row["why"]:
            return row
        unit = results.get("unit") or ""
        per = joint.days_per(unit)
        markers = [[_days(since, r["on"]) / per, r["value"]] for r in readings[-MAX_READINGS_EACH:]]
        age, h = age_days / per, [d / per for d in horizons["values"]]
        try:
            if with_curves:
                own = {"values": h, "labels": horizons["labels"], "basis": horizons["basis"]}
                view = joint.unit_view(model, values, markers, age, unit, own)
                row["unit"] = {"unit_id": p.get("name") or "", "source": "position", **view}
                risk = {k: view[k] for k in RISK_KEYS}
            else:
                risk = joint.risk_row(joint.predict(model, values, markers, age), h)
        except (FitError, ValueError, ArithmeticError) as err:
            row["why"] = f"The model couldn't work out its risk: {err}"
            return row
        if any(v is None for v in risk["risk"]):
            row.pop("unit", None)
            row["why"] = "The model gave no number for this item at its age: check its readings and in-service date."
            return row
        # The table reads in days whatever the model's own unit.
        left = risk["median_remaining"]
        row.update(risk, median_remaining=None if left is None else _round(left * per), scored=True)
        return row

    return row_for, models, fetch, today, horizons


def fleet(m, db, owners, hidden, item_class_id: str, position_id: str | None = None,
          within: str | None = None) -> dict:
    """The class's members (every position whose fitted item is of the class or
    a class inside it) with duty, item, age and last reading, and each one's
    risk now where its position has a condition and life model, highest first.
    With ``position_id``: that one member alone, with its curves (``unit``: its
    survival from now and its reading's path, as the model page draws them, in
    its model's own time unit). With ``within`` (one asset: its top position, or
    the place it's at): only the members inside it (``positions_inside``), so
    the counts, the models in use, the duties and the notes are that asset's
    alone."""
    sv = _sv()
    inside = m.positions_inside(within) if within is not None else None
    node, members = _members(m, item_class_id, inside)
    if position_id is not None:
        members = [x for x in members if x[0]["id"] == position_id]
        if not members:
            raise sv.Invalid(f"That position has no item of the class {node['name']} fitted"
                             + (" inside that tree." if inside is not None else "."))
    row_for, models, fetch, today, horizons = _scorer(m, db, owners, hidden)
    out = {"item_class": m._class_brief(node), "today": today, "age_unit": AGE_UNIT,
           "horizons": {"labels": horizons["labels"], "values": horizons["values"]}}
    if position_id is not None:
        out["member"] = row_for(members[0], with_curves=True)
        doc = position_model(m, fetch, position_id)
        out["model"] = doc and _model_view(doc)
        return out
    rows = [row_for(x, score=k < MAX_SCORED) for k, x in enumerate(members)]
    rows.sort(key=lambda r: (not r["scored"], -(r["risk"][1] if r["scored"] else 0.0), r["model"] is None,
                             r["position"]["name"].lower(), r["position"]["id"]))
    scored = sum(1 for r in rows if r["scored"])
    no_model = sum(1 for r in rows if r["model"] is None)
    out.update(positions=len(rows), members=rows, models=sorted(models.values(), key=lambda v: v["name"].lower()),
               scored=scored, no_model=no_model, not_scored=len(rows) - scored - no_model)
    duties = Counter(r["position"]["position_class"] for r in rows if r["position"]["position_class"])
    out["position_classes"] = [name for name, _ in duties.most_common()]
    notes = []
    if no_model:
        which = ("None of these positions has a" if no_model == len(rows) else
                 f"{no_model} of these positions {'has' if no_model == 1 else 'have'} no")
        notes.append(f"{which} condition and life model. To see risk, link one to the position on its Modelling "
                     "tab.")
    if len(rows) > MAX_SCORED:
        notes.append(f"Risk is worked out for the first {MAX_SCORED} members by name; open any other for its own.")
    out["note"] = " ".join(notes) or None
    return out


def position(m, db, owners, hidden, position_id: str) -> dict:
    """One position's risk now (the Explorer's Condition monitoring tab on a
    position): ``member`` is its row as a class's fleet gives it, with its
    curves when it is scored, whatever its item's class (``item_class`` None
    with none); ``model`` the condition and life model that scores it (None
    with none linked). With nothing fitted there is no member: ``why`` says so."""
    p, member = _member(m, position_id)
    row_for, _, fetch, today, horizons = _scorer(m, db, owners, hidden)
    doc = position_model(m, fetch, position_id)
    out = {"position": {"id": p["id"], "name": p.get("name") or "", "tag": p.get("tag") or "",
                        "position_class": p.get("position_class") or ""},
           "item_class": m._class_brief(member[3]) if member else None, "today": today, "age_unit": AGE_UNIT,
           "horizons": {"labels": horizons["labels"], "values": horizons["values"]},
           "member": row_for(member, with_curves=True) if member else None,
           "model": doc and _model_view(doc), "why": None}
    if member is None:
        out["why"] = ("No item is fitted here, so there is no age or readings to work a risk out from. Fit an item "
                      "to see its risk.")
    return out
