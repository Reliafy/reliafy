"""Derived points: a measurement point whose readings are worked out from another
record's data, rather than sent by a feed or typed by a person.

A derived point has a *source* (here a signal channel: see ``signals.py``), a
*rule* (what to work out from each new piece of source data) and an ordinary
series: each value is appended to the same time-series store a feed's readings
go to, so alarms, trends, projected alarm dates and condition monitoring work on
it unchanged. Three things make one:

* ``add`` records the point (the ``derived_point.added`` event: the rule is in
  it, so the graph can always be rebuilt) and works out its history from the
  source data already there;
* ``on_source_data`` runs when new source data arrives: every live derived
  point of that source appends its next value;
* a rule is a small class registered under a name (``register``); a new kind of
  derived point is a new rule, not new plumbing.

Nothing here knows what a spectrum is. A rule says which kind of source it
reads (``source_label``), checks its own spec, lists the source's records
(``records``: time and data, oldest first) and works one value out of one
record (``compute``; ``None`` when that record has nothing for the rule).
"""

from __future__ import annotations

from datetime import datetime

from backend.services import time_zones

#: name -> rule. A rule has: ``source_label`` (the graph label of its source),
#: ``validate(m, source, spec) -> spec`` (raises Invalid), ``unit(source, spec)``,
#: ``describe(spec)``, ``records(m, source)`` and ``compute(spec, record)``.
RULES: dict[str, object] = {}


def register(name: str, rule) -> None:
    RULES[name] = rule


def _invalid():
    from backend.maintenance.service import Invalid

    return Invalid


def _derived_added(s, org: str, p: dict) -> None:
    """derived_point.added: a measurement point (condition, read from the series
    store like a feed's) that says where its values come from."""
    from backend.maintenance.service import _point_added

    _point_added(s, org, {**p, "kind": "condition", "source": "automated", "tag": ""})
    s.patch_node(org, p["id"], {"derived": {"from": p["source_id"], "rule": p["rule"]}})
    s.put_edge(org, "DERIVED_FROM", p["id"], p["source_id"])
    # A later version of a point (an edited band): the older one points forward, this one back,
    # and ``applies_after`` says where the older version's values end.
    if p.get("supersedes"):
        s.patch_node(org, p["id"], {"supersedes": p["supersedes"], "applies_after": p.get("applies_after")})
        s.patch_node(org, p["supersedes"], {"superseded_by": p["id"]})


PROJECTORS = {"derived_point.added": _derived_added}


def points_of(m, source_id: str, live_only: bool = True) -> list[dict]:
    """The derived points reading from a source."""
    return [p for p in m.s.inn(m.org, source_id, "DERIVED_FROM")
            if p["label"] == "MeasurementPoint" and not (live_only and p.get("retired"))]


def add(m, source: dict, name: str, rule_spec: dict, subject: dict, alarm_above=None, alarm_below=None,
        supersedes: str | None = None, applies_after: str | None = None) -> dict:
    """Make a derived point on ``subject`` (the ``position_id`` / ``subject`` payload of
    the source's ON edge) and give it the history the source already has. Returns
    ``{"point_id", "written", "work_order"}``. With ``supersedes`` (the id of the point this
    one replaces) it is a new *version*: it starts empty and takes only data that arrives
    from now, so the older version's recorded values are never reinterpreted."""
    from backend.maintenance.service import new_id

    Invalid = _invalid()
    rule = RULES.get(rule_spec.get("type"))
    if rule is None or rule.source_label != source["label"]:
        raise Invalid("That kind of derived point isn't available for this source.")
    spec = rule.validate(m, source, dict(rule_spec))
    above, below = m._amount_or_none(alarm_above), m._amount_or_none(alarm_below)
    if above is not None and below is not None and below >= above:
        raise Invalid("The low alarm must be below the high alarm.")
    m._quota("MeasurementPoint", 5000, what="measurement points")
    pid = new_id()
    m._emit("derived_point.added", {
        "id": pid, **subject, "source_id": source["id"], "rule": spec, "unit": rule.unit(source, spec),
        "name": name, "alarm_above": above, "alarm_below": below, "on": m.today(),
        **({"supersedes": supersedes, "applies_after": applies_after} if supersedes else {})})
    if supersedes:
        return {"point_id": pid, "written": 0, "work_order": None}
    point = m.s.node(m.org, pid)
    written, work_order = backfill(m, point, source)
    return {"point_id": pid, "written": written, "work_order": work_order}


def backfill(m, point: dict, source: dict) -> tuple[int, dict | None]:
    """Work out a derived point's values from every record its source holds, and
    append them (once: the series store can't take a value back, so this runs when the
    point is made). A condition past an alarm limit at the latest value opens an
    inspection, as a feed's would."""
    rule = RULES[point["derived"]["rule"]["type"]]
    rows = []
    for when, record in rule.records(m, source):
        value = rule.compute(point["derived"]["rule"], record)
        if value is not None:
            rows.append((when, value))
    return _write(m, point, rows)


def on_source_data(m, source: dict, when: datetime, record) -> list[dict]:
    """New source data: every live derived point of the source appends its value
    (if the rule has one for this record). Returns what was written."""
    out = []
    for point in points_of(m, source["id"]):
        rule = RULES.get(point["derived"]["rule"]["type"])
        if rule is None:
            continue
        value = rule.compute(point["derived"]["rule"], record)
        if value is None:
            continue
        _, work_order = _write(m, point, [(when, value)])
        out.append({"point_id": point["id"], "name": point["name"], "value": value,
                    **({"work_order": work_order} if work_order else {})})
    return out


def _write(m, point: dict, rows: list[tuple[datetime, float]]) -> tuple[int, dict | None]:
    if not rows:
        return 0, None
    rows = sorted(rows)
    stored = m.s.series.append(m.org, point["id"], rows)
    latest = m.s.series.latest(m.org, point["id"])
    day = time_zones.day_of(datetime.fromisoformat(latest["t"]), m.tz)
    return stored, m._check_alarm(point["id"], latest["value"], day)
