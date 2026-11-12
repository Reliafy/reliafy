"""What a replace-or-restore task leaves the item as, and how its interval is counted (Nov 2026).

A fixed-interval task ("Overhaul the pump every 12 months") doesn't always renew the item. An
overhaul may take away only part of the age it has gained: the item is "younger" afterwards, not
new. That is a Kijima virtual age with a restoration factor ``q`` (SurPyval's generalised renewal):

* Kijima I: the task takes away a share of the age gained *since the last task*;
* Kijima II: the task takes away a share of the item's *whole* age;
* ``q`` = 0 is as good as new, ``q`` = 1 as bad as old. The app shows "restores X% of its age",
  X = (1 − q) × 100.

Every Nth task can be a full replacement instead, at its own cost. With no replacement cost
given, nothing is charged for it and the plan says so (never invented; a replacement usually costs
more than an overhaul).

Where it's set (Derryn, 12 Nov: "on the RCM decision"): on the task, for every failure mode it
serves, or by a failure mode's decision for its own share of the task. When one task serves
several modes whose decisions disagree, the RBD takes the *least* restoring of them and says so
(never an average).

A task can also be counted in running hours (``basis`` operating): its interval is time the
position runs, which the RBD puts on the calendar through the block's duty. A task counted on a
meter (hours, cycles) is in running time already.

At a shutdown, a task may be done only on an item older than a given age (``older_than``).

New events (older logs replay unchanged; each patches the task):

* ``task.restoration_set {id, restoration, failure_mode_id?}``: what the task leaves the item as,
  {kind: as_new | kijima1 | kijima2, q?, replace_every?, replacement_cost?}. Without
  ``failure_mode_id`` it's the task's own, for every mode it serves (any mode's own is cleared);
  with one, that mode's decision's (None clears it, and the task's own stands for that mode);
* ``task.basis_set {id, basis}``: "operating" or "calendar" (None: by its unit);
* ``task.shutdown_age_set {id, older_than}``: {value, unit} (None clears it).

Projectors read only the payload and the node, and write through the store interface.
"""

from __future__ import annotations

from backend.maintenance.store import GraphStore

KINDS = ("as_new", "kijima1", "kijima2")
BASES = ("calendar", "operating")
KIND_WORDS = {"as_new": "As new", "kijima1": "Kijima I", "kijima2": "Kijima II"}
OLDER_THAN_UNITS = ("days", "weeks", "months", "years")
MAX_REPLACE_EVERY = 100
MAX_COST = 1e12


# ---- projectors --------------------------------------------------------------------------

def _task_restoration_set(s: GraphStore, org: str, p: dict) -> None:
    task = s.node(org, p["id"]) or {}
    if p.get("failure_mode_id"):
        by_mode = {k: v for k, v in (task.get("restorations") or {}).items() if k != p["failure_mode_id"]}
        if p.get("restoration") is not None:
            by_mode[p["failure_mode_id"]] = dict(p["restoration"])
        s.patch_node(org, p["id"], {"restorations": by_mode})
    else:
        s.patch_node(org, p["id"], {"restoration": p.get("restoration"), "restorations": {}})


def _task_basis_set(s: GraphStore, org: str, p: dict) -> None:
    s.patch_node(org, p["id"], {"basis": p.get("basis")})


def _task_shutdown_age_set(s: GraphStore, org: str, p: dict) -> None:
    s.patch_node(org, p["id"], {"older_than": p.get("older_than")})


PROJECTORS = {
    "task.restoration_set": _task_restoration_set,
    "task.basis_set": _task_basis_set,
    "task.shutdown_age_set": _task_shutdown_age_set,
}


# ---- checking what's given -----------------------------------------------------------------

class RestorationError(ValueError):
    """A restoration, basis or age that can't be taken (the message says why)."""


def _num(value, what: str) -> float:
    try:
        x = float(value)
    except (TypeError, ValueError, OverflowError):
        raise RestorationError(f"The {what} must be a number.") from None
    if x != x or x in (float("inf"), float("-inf")):
        raise RestorationError(f"The {what} must be a number.")
    return x


def clean(value) -> dict | None:
    """A restoration from a request, checked: {kind, q?, replace_every?, replacement_cost?}.
    None or {} for "not set" (as new, unless a decision says otherwise). ``restores`` (a
    percentage, 0–100) may be given in place of ``q``: q = 1 − restores/100."""
    if value in (None, "", {}):
        return None
    if not isinstance(value, dict):
        raise RestorationError("restoration is {kind: as_new | kijima1 | kijima2, q, replace_every, "
                               "replacement_cost}.")
    unknown = set(value) - {"kind", "q", "restores", "replace_every", "replacement_cost"}
    if unknown:
        raise RestorationError(f"restoration doesn't take {', '.join(sorted(unknown))}: it takes kind, q (or "
                               "restores, a %), replace_every and replacement_cost.")
    kind = value.get("kind") or ("kijima1" if value.get("q") not in (None, "") or value.get("restores")
                                 not in (None, "") else None)
    if kind not in KINDS:
        raise RestorationError(f"restoration.kind is one of {', '.join(KINDS)}.")
    if kind == "as_new":
        if any(value.get(k) not in (None, "") for k in ("q", "restores", "replace_every", "replacement_cost")):
            raise RestorationError("As new renews the item at every task: it takes no q, replace_every or "
                                   "replacement cost.")
        return {"kind": "as_new"}
    if value.get("q") not in (None, ""):
        q = _num(value["q"], "restoration factor q")
    elif value.get("restores") not in (None, ""):
        q = 1 - _num(value["restores"], "share of its age restored") / 100
    else:
        raise RestorationError("Say how much the task restores: q from 0 (as good as new) to 1 (as bad as old), "
                               "or restores, the % of its age it takes away.")
    if not -1e-9 <= q <= 1 + 1e-9:
        raise RestorationError("The restoration factor q is from 0 (as good as new) to 1 (as bad as old); "
                               "restores is from 0% to 100%.")
    out: dict = {"kind": kind, "q": round(min(max(q, 0.0), 1.0), 6)}
    every = value.get("replace_every")
    if every not in (None, ""):
        n = _num(every, "replace_every")
        if n != int(n) or not 2 <= n <= MAX_REPLACE_EVERY:
            raise RestorationError(f"replace_every is a whole number of tasks from 2 to {MAX_REPLACE_EVERY} (every "
                                   "Nth task is a full replacement).")
        if out["q"] == 0:
            raise RestorationError("A task that renews the item every time needs no replace_every.")
        out["replace_every"] = int(n)
    cost = value.get("replacement_cost")
    if cost not in (None, ""):
        if "replace_every" not in out:
            raise RestorationError("A replacement cost goes with replace_every (every Nth task is a full "
                                   "replacement).")
        c = _num(cost, "replacement cost")
        if not 0 <= c <= MAX_COST:
            raise RestorationError("The replacement cost is 0 or more.")
        out["replacement_cost"] = round(c, 2)
    return out


def clean_basis(value) -> str | None:
    if value in (None, ""):
        return None
    if value not in BASES:
        raise RestorationError(f"basis is one of {', '.join(BASES)} (or null: by the task's unit).")
    return value


def clean_older_than(value) -> dict | None:
    """{value, unit} (calendar units) or None."""
    if value in (None, "", {}):
        return None
    if not isinstance(value, dict):
        raise RestorationError("older_than is {value, unit}, e.g. {value: 18, unit: 'months'}.")
    unit = value.get("unit") or "months"
    if unit not in OLDER_THAN_UNITS:
        raise RestorationError(f"older_than's unit is one of {', '.join(OLDER_THAN_UNITS)}.")
    n = _num(value.get("value"), "age (older_than)")
    if not 0 < n <= 1200:
        raise RestorationError("older_than is a positive age.")
    return {"value": n, "unit": unit}


# ---- reading it ----------------------------------------------------------------------------

def _rank(r: dict | None) -> tuple:
    """How little a restoration restores (larger: less): as new least of all; then by q;
    at the same q Kijima I (only the age since the last task) restores less than Kijima II;
    a full replacement less often (or never) restores less."""
    if not r or r.get("kind") == "as_new":
        return (-1.0, 0, 0)
    every = r.get("replace_every")
    return (float(r.get("q") or 0), 1 if r["kind"] == "kijima1" else 0, every if every else 10 ** 6)


def words(r: dict | None) -> str:
    """"As new", "Restores 70% of its age (Kijima II) · every 3rd a replacement"."""
    if not r or r.get("kind") == "as_new":
        return "As new"
    pct = round((1 - float(r.get("q") or 0)) * 100, 1)
    pct_text = f"{pct:g}%"
    what = "of the age gained since the last task" if r["kind"] == "kijima1" else "of its age"
    out = f"Restores {pct_text} {what} ({KIND_WORDS[r['kind']]})"
    every = r.get("replace_every")
    if every:
        nth = {2: "2nd", 3: "3rd"}.get(every, f"{every}th")
        out += f" · every {nth} task a full replacement"
    return out


def effective(task: dict, modes: list[dict]) -> dict:
    """What a task leaves the item as, for the plan: {restoration (None: as new), words, source
    ('task' | 'decision' | None), by_mode [{failure_mode_id, text, restoration, words}], conflict
    (words, or None)}. ``modes``: the failure modes it serves ({id, text}). Each mode takes its
    decision's own restoration, else the task's; when they disagree the least restoring is taken
    and ``conflict`` says so."""
    own = task.get("restoration")
    mine = task.get("restorations") or {}
    rows = []
    for fm in modes:
        r = mine.get(fm["id"])
        rows.append({"failure_mode_id": fm["id"], "text": fm.get("text") or "", "restoration": r or own,
                     "own": r is not None, "words": words(r or own)})
    if not rows:
        chosen = own
        source = "task" if own else None
    else:
        chosen = max((x["restoration"] for x in rows), key=_rank)
        source = "decision" if any(x["own"] for x in rows) else ("task" if own else None)
    distinct = {words(x["restoration"]) for x in rows}
    conflict = None
    if len(distinct) > 1:
        conflict = ("Its failure modes' decisions disagree on what it leaves the item as ("
                    + "; ".join(f"{x['text'] or 'a mode'}: {x['words']}" for x in rows)
                    + f"). The RBD takes the least restoring: {words(chosen)}.")
    if chosen and chosen.get("kind") == "as_new":
        chosen = None
    return {"restoration": chosen, "words": words(chosen), "source": source, "by_mode": rows, "conflict": conflict}


# ---- the operations (methods added to ``Maintenance``) ---------------------------------------

def _sv():
    from backend.maintenance import service

    return service


class RestorationOps:
    """Setting what a task leaves the item as, how its interval is counted, and its age limit
    at a shutdown; and reading them for the task's view and the RBD plan."""

    def _live_task(self, task_id) -> dict:
        task = self._get(str(task_id or ""), "Task")
        if task.get("retired"):
            raise _sv().Invalid("That task has been retired.")
        return task

    def _task_modes(self, task_id: str) -> list[dict]:
        return sorted(({"id": fm["id"], "text": fm.get("text") or ""}
                       for fm in self.s.out(self.org, task_id, "MITIGATES") if not fm.get("retired")),
                      key=lambda x: (x["text"], x["id"]))

    def set_task_restoration(self, task_id, restoration, failure_mode_id=None) -> dict:
        """What a replace-or-restore (fixed-interval) task leaves the item as: as new, or restored
        partly (Kijima I or II, restoration factor q), with every Nth task a full replacement.
        failure_mode_id: one failure mode's decision's own (the task's stands for the others);
        without it, the task's own for every mode (any mode's own cleared). None clears it."""
        sv = _sv()
        task = self._live_task(task_id)
        try:
            value = clean(restoration)
        except RestorationError as err:
            raise sv.Invalid(str(err)) from None
        from backend.maintenance.rbd_tree_plan import task_kind

        kind = task_kind(self, task)
        if value is not None and kind != "fixed_interval":
            raise sv.Invalid(f"“{task['name']}” isn't a replace-or-restore task (its kind is "
                             f"{kind or 'routine work'}): what it leaves the item as applies to a fixed-interval "
                             "task. Set its kind first.")
        mode = str(failure_mode_id or "").strip() or None
        if mode:
            if self.s.edge(self.org, "MITIGATES", task["id"], mode) is None:
                raise sv.Invalid(f"“{task['name']}” doesn't serve that failure mode.")
            if (task.get("restorations") or {}).get(mode) == value:
                return self._task_view(self._get(task["id"], "Task"))
        elif task.get("restoration") == value and not task.get("restorations"):
            return self._task_view(self._get(task["id"], "Task"))
        self._emit("task.restoration_set", {"id": task["id"], "restoration": value}
                   | ({"failure_mode_id": mode} if mode else {}))
        return self._task_view(self._get(task["id"], "Task"))

    def set_task_basis(self, task_id, basis) -> dict:
        """Count the task's interval in running hours ("operating": the time the position runs,
        put on the calendar through an RBD block's duty) or on the calendar; None: by its unit. A
        task counted on a meter is in running time already."""
        sv = _sv()
        task = self._live_task(task_id)
        try:
            value = clean_basis(basis)
        except RestorationError as err:
            raise sv.Invalid(str(err)) from None
        if value is not None and not sv._is_calendar(task["unit"]):
            raise sv.Invalid(f"“{task['name']}” is counted on a meter ({task['unit']}), which is running time "
                             "already: a basis applies to a task every so many days, weeks, months or years.")
        if value != task.get("basis"):
            self._emit("task.basis_set", {"id": task["id"], "basis": value})
        return self._task_view(self._get(task["id"], "Task"))

    def set_task_older_than(self, task_id, older_than) -> dict:
        """At a shutdown, do the task only on an item older than this ({value, unit}); None
        clears it (every shut)."""
        sv = _sv()
        task = self._live_task(task_id)
        try:
            value = clean_older_than(older_than)
        except RestorationError as err:
            raise sv.Invalid(str(err)) from None
        if value != task.get("older_than"):
            self._emit("task.shutdown_age_set", {"id": task["id"], "older_than": value})
        return self._task_view(self._get(task["id"], "Task"))

    def _restoration_view(self, task: dict, by_use: bool) -> dict:
        """The task view's fields: restoration (effective), basis, older_than."""
        eff = effective(task, self._task_modes(task["id"]))
        basis = "operating" if by_use else (task.get("basis") or "calendar")
        return {"restoration": {**eff, "own": task.get("restoration")}, "basis": basis,
                "basis_set": task.get("basis"), "older_than": task.get("older_than")}
