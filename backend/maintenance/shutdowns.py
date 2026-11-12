"""Shutdowns: a work package that takes its position off-line for a fixed time (Nov 2026).

A shutdown is a work package (work-packages step 4) whose visits are planned outages: "the line
is shut 3 days every 12 months; everything gets its PM then". Its calendar is the package's own
set dates (or a list of dates given here), and the tasks in it are the work done at the shut,
so a task is never owned twice. A task in it may be done only on an item older than a given age
(``task.shutdown_age_set``, restoration.py).

What it adds to the package (``package.shutdown_set {id, shutdown}``, a new event; None makes it
an ordinary package again):

* ``duration_hours``: how long the shut holds its scope off-line;
* ``cost``: charged at each shut (optional);
* ``scope``: the positions it takes down, None (the default) for the package's whole position,
  or a chosen set of positions inside it (a section of the line);
* ``idle_ageing``: True (the default): an item not worked on keeps ageing through the shut;
  False: it stands still until the shut ends;
* ``dates``: the shuts' start dates, in place of the package's cadence (optional).

The RBD reads it (rbd_tree_plan.py), never writes it.
"""

from __future__ import annotations

from datetime import date

from backend.maintenance.store import GraphStore

MAX_DATES = 100
MAX_SCOPE = 200
MAX_HOURS = 24 * 366
MAX_COST = 1e12


def _package_shutdown_set(s: GraphStore, org: str, p: dict) -> None:
    s.patch_node(org, p["id"], {"shutdown": p.get("shutdown")})


PROJECTORS = {"package.shutdown_set": _package_shutdown_set}


class ShutdownError(ValueError):
    """A shutdown that can't be taken (the message says why)."""


def clean(value) -> dict | None:
    """A shutdown from a request, checked (positions in its scope are checked by the caller).
    None or {} for "not a shutdown"."""
    if value in (None, "", {}):
        return None
    if not isinstance(value, dict):
        raise ShutdownError("shutdown is {duration_hours, cost?, scope?: [position ids], idle_ageing?, dates?}.")
    unknown = set(value) - {"duration_hours", "cost", "scope", "idle_ageing", "dates"}
    if unknown:
        raise ShutdownError(f"shutdown doesn't take {', '.join(sorted(unknown))}.")
    try:
        hours = float(value.get("duration_hours"))
    except (TypeError, ValueError, OverflowError):
        raise ShutdownError("Say how long the shutdown lasts: duration_hours, e.g. 72.") from None
    if not 0 < hours <= MAX_HOURS:
        raise ShutdownError("A shutdown lasts more than 0 hours and at most a year.")
    out: dict = {"duration_hours": round(hours, 3), "idle_ageing": value.get("idle_ageing") is not False}
    if value.get("cost") not in (None, ""):
        try:
            cost = float(value["cost"])
        except (TypeError, ValueError, OverflowError):
            raise ShutdownError("The shutdown's cost must be a number.") from None
        if not 0 <= cost <= MAX_COST:
            raise ShutdownError("The shutdown's cost is 0 or more.")
        out["cost"] = round(cost, 2)
    scope = value.get("scope")
    if scope not in (None, "", []):
        if not isinstance(scope, list) or not all(isinstance(x, str) and x for x in scope):
            raise ShutdownError("scope is a list of position ids (leave it out for the whole position).")
        if len(scope) > MAX_SCOPE:
            raise ShutdownError(f"A shutdown's scope names at most {MAX_SCOPE} positions.")
        out["scope"] = list(dict.fromkeys(scope))
    else:
        out["scope"] = None
    dates = value.get("dates")
    if dates not in (None, "", []):
        if not isinstance(dates, list) or len(dates) > MAX_DATES:
            raise ShutdownError(f"dates is a list of up to {MAX_DATES} dates, e.g. ['2027-03-01'].")
        try:
            days = sorted({date.fromisoformat(str(d)).isoformat() for d in dates})
        except ValueError:
            raise ShutdownError("Each of dates is a date like 2027-03-01.") from None
        gaps = [(date.fromisoformat(b) - date.fromisoformat(a)).days * 24 for a, b in zip(days, days[1:])]
        if any(g <= hours for g in gaps):
            raise ShutdownError("Two shutdowns overlap: each must end before the next starts.")
        out["dates"] = days
    return out


def words(sd: dict | None) -> str:
    """"Off-line 72 h each time · costs 15,000 · keeps ageing"."""
    if not sd:
        return ""
    parts = [f"off-line {sd['duration_hours']:g} h each time"]
    if sd.get("cost") is not None:
        parts.append(f"costs {sd['cost']:,.2f}".rstrip("0").rstrip("."))
    if sd.get("idle_ageing") is False:
        parts.append("idle items don't age")
    return " · ".join(parts)


def _sv():
    from backend.maintenance import service

    return service


class ShutdownOps:
    """Making a work package a shutdown, and reading the shutdowns on and inside a position."""

    def check_shutdown(self, shutdown) -> None:
        """Refuse a shutdown that can't be taken, before anything is written."""
        try:
            clean(shutdown)
        except ShutdownError as err:
            raise _sv().Invalid(str(err)) from None

    def set_package_shutdown(self, package_id, shutdown) -> dict:
        """Make the package a shutdown (its visits take its position, or the positions in scope,
        off-line for duration_hours, at cost), or an ordinary package again (None)."""
        sv = _sv()
        pkg = self._live_package(package_id)
        try:
            value = clean(shutdown)
        except ShutdownError as err:
            raise sv.Invalid(str(err)) from None
        if value is not None:
            chain = self._package_chain(pkg)
            if len(chain) > 1:
                raise sv.Invalid("A layer visits on its top package's dates: make the top package the shutdown.")
            subject = self._package_subject(pkg)
            if subject is None or subject["label"] != "Position":
                raise sv.Invalid("A shutdown is on a position (the plant or line it takes off-line), not a location.")
            if pkg["timing"] != "fixed" and not value.get("dates"):
                raise sv.Invalid("A shutdown is on set dates: give the package set dates, or list the shutdown's "
                                 "dates.")
            if value.get("scope"):
                inside = {subject["id"]} | {p["id"] for p in self._positions_inside(subject["id"])}
                for pid in value["scope"]:
                    if pid not in inside:
                        raise sv.Invalid(f"Position {pid} isn't {subject['name']} or inside it: a shutdown takes "
                                         "down its own position, or a set of positions inside it.")
                if value["scope"] == [subject["id"]]:
                    value["scope"] = None
        if value != pkg.get("shutdown"):
            self._emit("package.shutdown_set", {"id": pkg["id"], "shutdown": value, "on": self.today()})
        return self.package(pkg["id"])

    def _positions_inside(self, position_id: str, depth: int = 8) -> list[dict]:
        out, level = [], [position_id]
        for _ in range(depth):
            nxt = [c for pid in level for c in self.s.inn(self.org, pid, "PART_OF")
                   if c["label"] == "Position" and not c.get("retired")]
            if not nxt:
                break
            out += nxt
            level = [c["id"] for c in nxt]
        return out

    def _shutdown_view(self, pkg: dict) -> dict | None:
        sd = pkg.get("shutdown")
        if not sd:
            return None
        scope = None
        if sd.get("scope"):
            scope = [{"id": pid, "name": (self.s.node(self.org, pid) or {}).get("name") or pid} for pid in sd["scope"]]
        return {**sd, "scope": scope, "words": words(sd)}

    def shutdowns_for(self, position_id: str) -> list[dict]:
        """The live shutdown packages on a position or inside it: [{package, position, shutdown,
        next (the next shut's start date, on or after today), tasks (ids)}]."""
        here = {position_id} | {p["id"] for p in self._positions_inside(position_id)}
        out = []
        for pkg in self.s.nodes(self.org, "WorkPackage"):
            if pkg.get("retired") or not pkg.get("shutdown"):
                continue
            subject = self._package_subject(pkg)
            if subject is None or subject["id"] not in here:
                continue
            sd = pkg["shutdown"]
            today = self.today()
            if sd.get("dates"):
                nxt = next((d for d in sd["dates"] if d >= today), None)
            else:
                yesterday = (date.fromisoformat(today).toordinal() - 1)
                found = self._cadence(pkg).after(date.fromordinal(yesterday).isoformat())
                nxt = found and found.isoformat()
            tasks = [m["task_id"] for m in self._package_tree_members(pkg)]
            out.append({"package": {"id": pkg["id"], "name": pkg["name"], "every": pkg["every"], "unit": pkg["unit"],
                                    "cadence": self._cadence_text(pkg)},
                        "position": {"id": subject["id"], "name": subject.get("name") or ""},
                        "shutdown": sd, "next": nxt, "tasks": tasks, "today": today})
        out.sort(key=lambda x: (x["package"]["name"].lower(), x["package"]["id"]))
        return out

    def _package_tree_members(self, pkg: dict) -> list[dict]:
        return [m for p in self._package_tree(pkg) for m in p.get("members") or []]
