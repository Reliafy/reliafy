"""What a failure costs: its repair, and its downtime (Nov 2026).

A failure's consequence in money is three figures:

* ``failure_cost``: what one failure costs to put right (the repair or replacement in the field,
  the parts, any damage), in the workspace's currency;
* ``downtime_hours``: how long one failure keeps the position out of use;
* ``downtime_rate``: what an hour out of use costs (lost production, a hired replacement). Optional.

They live in two places, with one rule (the forecast and Optimise read them through
:meth:`FailureCostOps.failure_consequence`, nowhere else):

1. on the **failure mode** (its RCM consequence, Explorer › RCM, step 2): its own figures;
2. on the **position's class** (Assets › Classes): the default for every mode of its positions.

Each figure is taken from the mode when the mode has it, else from the class. A class's failure cost
falls back to its replacement cost (as before). A life that covers several failure modes (or every
failure of a position) takes the costliest of them, and says so. Nothing is ever invented: with no
figure anywhere, the cost is missing and the forecast says where to enter it.

All in, one failure costs ``failure_cost + downtime_hours × downtime_rate``.

New events (older logs replay unchanged):

* ``failure_mode.costs_set {id, costs: {failure_cost, downtime_hours, downtime_rate}}``: the mode's
  own figures, each a number or None (not set: the class's is used);
* ``class.downtime_set {id, name, downtime_hours, downtime_rate}``: a class's downtime per failure
  and cost an hour (its failure cost stays with ``class.costs_set``).

Projectors read only the payload and the node, and write through the store interface.
"""

from __future__ import annotations

import math

from backend.maintenance.store import GraphStore

FIELDS = ("failure_cost", "downtime_hours", "downtime_rate")
WORDS = {"failure_cost": "failure cost", "downtime_hours": "downtime per failure",
         "downtime_rate": "cost of an hour of downtime"}
MAX_COST = 1e12
MAX_HOURS = 100_000.0


# ---- projectors --------------------------------------------------------------------------

def _mode_costs_set(s: GraphStore, org: str, p: dict) -> None:
    costs = p.get("costs") or {}
    s.patch_node(org, p["id"], {k: costs.get(k) for k in FIELDS})


def _class_downtime_set(s: GraphStore, org: str, p: dict) -> None:
    from backend.maintenance.service import _class_upsert

    _class_upsert(s, org, p, {k: p.get(k) for k in ("downtime_hours", "downtime_rate")})


PROJECTORS = {
    "failure_mode.costs_set": _mode_costs_set,
    "class.downtime_set": _class_downtime_set,
}


# ---- checking what's given -----------------------------------------------------------------

class FailureCostError(ValueError):
    pass


def clean(key: str, value) -> float | None:
    """One figure as stored: a finite number, 0 or more (None or "" clears it)."""
    if value is None or value == "":
        return None
    try:
        v = float(value)
    except (TypeError, ValueError, OverflowError):
        raise FailureCostError(f"The {WORDS[key]} must be a number.") from None
    high = MAX_HOURS if key == "downtime_hours" else MAX_COST
    if not math.isfinite(v) or not 0 <= v <= high:
        raise FailureCostError(f"The {WORDS[key]} is a number from 0 to {high:,.0f}.")
    return v


# ---- reading them --------------------------------------------------------------------------

def _money(v) -> str:
    return f"${v:,.0f}" if v >= 100 else f"${v:,.2f}".replace(".00", "")


def per_failure(figures: dict) -> float | None:
    """One failure all in: its cost plus its downtime at the cost an hour; None with neither."""
    cost = figures.get("failure_cost")
    down = (figures.get("downtime_hours") or 0.0) * (figures.get("downtime_rate") or 0.0)
    if cost is None and not down:
        return None
    return float(cost or 0.0) + down


def words(c: dict) -> str:
    """"$900 (the failure mode's) + 4 h down at $50 an hour (the Pump class's)"."""
    if c.get("per_failure") is None:
        return c.get("missing_text") or "no failure cost set"
    src = c.get("sources") or {}
    bits = []
    if c.get("failure_cost") is not None:
        bits.append(f"{_money(c['failure_cost'])} ({src.get('failure_cost')})")
    if c.get("downtime_hours"):
        if c.get("downtime_rate"):
            bits.append(f"{c['downtime_hours']:g} h down at {_money(c['downtime_rate'])} an hour "
                        f"({src.get('downtime_rate')})")
        else:
            bits.append(f"{c['downtime_hours']:g} h down ({src.get('downtime_hours')}; no cost an hour set)")
    return " + ".join(bits)


class FailureCostOps:
    """Setting a failure mode's and a class's failure costs, and reading the one figure a failure
    costs (methods added to ``Maintenance``)."""

    def set_mode_costs(self, mode_id, failure_cost=..., downtime_hours=..., downtime_rate=...) -> dict:
        """A failure mode's own failure cost, downtime per failure (hours) and cost of an hour down.
        A figure left out (``...``) stays as it is; None clears it (its class's is used)."""
        from backend.maintenance import service as sv

        fm, _position = self._live_mode(mode_id)
        given = {"failure_cost": failure_cost, "downtime_hours": downtime_hours, "downtime_rate": downtime_rate}
        now = {k: fm.get(k) for k in FIELDS}
        out = dict(now)
        for key, value in given.items():
            if value is ...:
                continue
            try:
                out[key] = clean(key, value)
            except FailureCostError as err:
                raise sv.Invalid(str(err)) from None
        if out != now:
            self._emit("failure_mode.costs_set", {"id": fm["id"], "costs": out})
        return self.mode_costs(fm["id"])

    def set_class_downtime(self, position_class, downtime_hours=..., downtime_rate=...) -> dict:
        """A class's downtime per failure (hours) and cost of an hour down: the default for its
        positions' failure modes. Left out (``...``): kept; None clears."""
        from backend.maintenance import service as sv

        name = self._class_name(position_class)
        node = self.s.node(self.org, sv.class_id(self.org, name)) or {}
        now = {k: node.get(k) for k in ("downtime_hours", "downtime_rate")}
        out = dict(now)
        for key, value in (("downtime_hours", downtime_hours), ("downtime_rate", downtime_rate)):
            if value is ...:
                continue
            try:
                out[key] = clean(key, value)
            except FailureCostError as err:
                raise sv.Invalid(str(err)) from None
        if out != now:
            self._emit("class.downtime_set", {"id": sv.class_id(self.org, name), "name": name, **out})
        return self.position_class(name)

    def _class_figures(self, position: dict) -> tuple[dict, str | None]:
        """The position class's figures ({failure_cost, downtime_hours, downtime_rate}, with where
        the failure cost came from) and the class's name, or ({}, None) with no class."""
        from backend.maintenance import service as sv

        key = self._class_key(position)
        if not key:
            return {}, None
        name = self._class_label(key)
        node = self.s.node(self.org, sv.class_id(self.org, key)) or {}
        out = {k: node.get(k) for k in FIELDS}
        out["_failure_from"] = f"the {name} class's failure cost"
        if out["failure_cost"] is None and (node.get("replacement_cost") or {}).get("amount") is not None:
            out["failure_cost"] = float(node["replacement_cost"]["amount"])
            out["_failure_from"] = f"the {name} class's replacement cost"
        return out, name

    def _mode_consequence(self, fm: dict | None, cls: dict, cls_name: str | None) -> dict:
        from backend.maintenance import responses

        figures, sources = {}, {}
        # The corrective response's cost each time ("If it fails anyway"): the failure mode's cost of a
        # failure, unless one is typed on the mode, which overrides it (forecast plan step 3).
        response = responses.response_view(self, fm["id"], "failure") if fm else None
        for key in FIELDS:
            own = (fm or {}).get(key)
            if own is not None:
                figures[key], sources[key] = float(own), "the failure mode's"
                if key == "failure_cost" and response and response.get("cost_each") is not None:
                    sources[key] = "the failure mode's, typed over its corrective response's"
            elif key == "failure_cost" and response and response.get("cost_each") is not None:
                figures[key] = float(response["cost_each"])
                sources[key] = f"its corrective response's ({response['name']})"
            elif cls.get(key) is not None:
                figures[key] = float(cls[key])
                sources[key] = cls["_failure_from"] if key == "failure_cost" else f"the {cls_name} class's"
            else:
                figures[key] = None
        total = per_failure(figures)
        down = (figures["downtime_hours"] or 0.0) * (figures["downtime_rate"] or 0.0)
        out = {**figures, "per_failure": total, "downtime_cost": down if figures["downtime_hours"] else None,
               "sources": sources, "mode": {"id": fm["id"], "text": fm.get("text") or ""} if fm else None,
               "class": cls_name, "response": response}
        if total is None:
            out["missing_text"] = (f"no failure cost set (on the failure mode, or its {cls_name} class)" if cls_name
                                   else "no failure cost set (enter it on the failure mode, or give the position "
                                        "a class with one)")
        out["text"] = words(out)
        return out

    def failure_consequence(self, position: dict, mode_ids=None) -> dict:
        """What one failure on ``position`` costs, for a life for ``mode_ids`` (None: every failure
        there): {failure_cost, downtime_hours, downtime_rate, downtime_cost, per_failure (all in, or
        None: not set anywhere), sources {field: where}, mode, class, text, by_mode [...], note}.
        Each figure is the mode's own, else the position class's; a life for several modes takes
        the costliest."""
        cls, cls_name = self._class_figures(position)
        if mode_ids is None:
            modes = [fm for fm in self._modes_on(position["id"])]
        else:
            modes = [fm for fm in (self.s.node(self.org, i) for i in mode_ids)
                     if fm and not fm.get("retired") and not fm.get("merged_into")]
        rows = [self._mode_consequence(fm, cls, cls_name) for fm in modes] or [
            self._mode_consequence(None, cls, cls_name)]
        priced = [r for r in rows if r["per_failure"] is not None]
        chosen = max(priced, key=lambda r: r["per_failure"]) if priced else rows[0]
        out = {**chosen, "by_mode": [r for r in rows if r["mode"]]}
        if len(rows) > 1 and len({r["per_failure"] for r in rows}) > 1:
            out["note"] = (f"this life covers {len(rows)} failure modes with different costs: the costliest, "
                           f"{chosen['mode']['text'] if chosen['mode'] else 'its class'}, is used")
            out["text"] += f" ({out['note']})"
        return out

    def mode_costs(self, mode_id: str) -> dict:
        """A failure mode's failure costs as the RCM panel shows them: {own {field: value}, used (the
        figures in force, with where each came from), class}."""
        fm, position = self._live_mode(mode_id)
        cls, cls_name = self._class_figures(position)
        used = self._mode_consequence(fm, cls, cls_name)
        return {"id": fm["id"], "own": {k: fm.get(k) for k in FIELDS},
                "class_figures": {k: cls.get(k) for k in FIELDS} if cls_name else None,
                "used": used, "class": cls_name, "responses": self.mode_responses(fm["id"]),
                "has_check": self._mode_has_check(fm)}

    def _mode_has_check(self, fm: dict) -> bool:
        """An on-condition or failure-finding check serves the mode: "If an inspection finds it" applies."""
        checks = ("on_condition", "failure_finding")
        if fm.get("outcome") in checks or any(o.get("outcome") in checks for o in fm.get("outcomes") or []):
            return True
        return any(t.get("label") == "Task" and not t.get("retired") and t.get("outcome") in checks
                   for t in self.s.inn(self.org, fm["id"], "MITIGATES"))
