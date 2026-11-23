"""Supporting tasks: "keeps it on its life" (Nov 2026).

A part's life model describes its life when it's looked after the way it was when the data was
collected. A supporting task (grease the bearing, change the oil, clean the screen) doesn't renew
the part: it keeps it on that life. So while it's done as planned it changes no failure in the
forecast, only its own line; its effect shows when it isn't done (dropped, stretched or overdue).

This module is the record only. The forecast is unchanged by it: a supporting task restores none
of the item's age (as servicing work was already taken to), and it reads "Keeps it on its life"
rather than "restores 0%". The what-ifs that apply the impact come later.

The record, on the task (``support``):

* ``failure_mode_ids``: the failure modes it supports, each one the task serves; [] for the
  part's whole life;
* ``reference``: {value, unit}, the interval the life model assumes ("this life assumes greasing
  every 50 h"), the task's own interval when it's first marked, in the task's unit;
* ``impact``: what not doing it does, a typed object so other forms can follow without a
  migration. Today one form: {form: "hazard_ratio", k}, "the failure rate × k while it isn't
  done". None: "supports, no modelled impact" (recorded for RCM, changes no numbers).
  Reserved for later: {form: "ageing_rate", ...}, the item ageing faster the longer it goes
  since the service (variable-speed ageing); refused until it's built;
* ``grace``: the share of its interval (0–100%) it may be overdue before the impact applies;
  0 by default;
* ``source``: assumed (typed: engineering judgement), maker (from the maker's guidance) or
  fitted (from a fit on the workspace's data); with ``note``.

Several supporting tasks on one part combine by multiplying their impacts: two at × 2 and × 1.5,
both not done, give × 3.

New event (older logs replay unchanged): ``task.support_set {id, support}`` (None clears it).
Projectors read only the payload, and write through the store interface.
"""

from __future__ import annotations

import math

from backend.maintenance.store import GraphStore

FORMS = ("hazard_ratio",)
#: Forms the record keeps room for, not taken yet.
LATER_FORMS = ("ageing_rate",)
SOURCES = ("assumed", "maker", "fitted")
SOURCE_WORDS = {"assumed": "Assumed", "maker": "From the maker", "fitted": "Fitted"}
MAX_K = 100.0
MAX_NOTE = 500
#: The kinds of task that can keep an item on its life: routine work (no kind) and replace or
#: restore at a fixed interval. A check (on condition, failure finding) finds a failure; it
#: doesn't hold one off.
KINDS = (None, "fixed_interval")
#: What a supporting task leaves the item as, for everything that reads ``restoration``.
RESTORES_NONE = {"kind": "kijima1", "q": 1.0}


# ---- the projector ---------------------------------------------------------------------------

def _task_support_set(s: GraphStore, org: str, p: dict) -> None:
    s.patch_node(org, p["id"], {"support": p.get("support")})


PROJECTORS = {"task.support_set": _task_support_set}


# ---- checking what's given -------------------------------------------------------------------

class SupportError(ValueError):
    """A supporting-task record that can't be taken (the message says why)."""


def _num(value, what: str) -> float:
    if isinstance(value, bool):
        raise SupportError(f"The {what} must be a number.")
    try:
        x = float(value)
    except (TypeError, ValueError, OverflowError):
        raise SupportError(f"The {what} must be a number.") from None
    if not math.isfinite(x):
        raise SupportError(f"The {what} must be a number.")
    return x


def clean_impact(value) -> dict | None:
    """{form: hazard_ratio, k} from a request (a bare number is k); None for no modelled impact."""
    if value in (None, "", {}):
        return None
    if not isinstance(value, dict):
        value = {"form": "hazard_ratio", "k": value}
    form = value.get("form") or "hazard_ratio"
    if form in LATER_FORMS:
        raise SupportError(f"impact form {form} isn't taken yet: give {{form: 'hazard_ratio', k}}.")
    if form not in FORMS:
        raise SupportError("impact is {form: 'hazard_ratio', k}: the failure rate × k while the task isn't done.")
    unknown = set(value) - {"form", "k"}
    if unknown:
        raise SupportError(f"impact doesn't take {', '.join(sorted(unknown))}: it takes form and k.")
    k = _num(value.get("k"), "impact (hazard × k)")
    if not 1 <= k <= MAX_K:
        raise SupportError(f"The impact k is from 1 (no change) to {MAX_K:g}: the failure rate × k while the task "
                           "isn't done.")
    return {"form": "hazard_ratio", "k": float(f"{k:.6g}")}


def clean(value, task: dict, modes: list[dict]) -> dict | None:
    """A supporting-task record from a request, checked against the task and the failure modes it
    serves (``modes``: [{id, text}]). None, {} or False: not a supporting task."""
    if value in (None, "", {}, False):
        return None
    if value is True:
        value = {}
    if not isinstance(value, dict):
        raise SupportError("support is {failure_mode_ids?, reference?, impact?, grace?, source?, note?}.")
    unknown = set(value) - {"failure_mode_ids", "reference", "impact", "grace", "source", "note"}
    if unknown:
        raise SupportError(f"support doesn't take {', '.join(sorted(unknown))}: it takes failure_mode_ids, "
                           "reference, impact, grace, source and note.")
    served = {m["id"] for m in modes}
    ids = value.get("failure_mode_ids") or []
    if isinstance(ids, str):
        ids = [ids]
    if not isinstance(ids, list) or not all(isinstance(x, str) for x in ids):
        raise SupportError("failure_mode_ids is a list of the failure modes it supports ([]: the part's whole life).")
    wrong = [x for x in ids if x not in served]
    if wrong:
        raise SupportError("It can support only failure modes the task serves: link the task to the mode first.")
    ref = value.get("reference")
    unit = task.get("unit")
    if ref in (None, "", {}):
        if task.get("interval") in (None, ""):
            raise SupportError("Give the reference interval: the interval the life model assumes.")
        ref = {"value": task["interval"], "unit": unit}
    elif not isinstance(ref, dict):
        ref = {"value": ref, "unit": unit}
    if (ref.get("unit") or unit) != unit:
        raise SupportError(f"The reference interval is in the task's unit ({unit}).")
    every = _num(ref.get("value"), "reference interval")
    if every <= 0:
        raise SupportError("The reference interval is more than 0.")
    grace = value.get("grace")
    grace = 0.0 if grace in (None, "") else _num(grace, "grace (% of its interval)")
    if not 0 <= grace <= 100:
        raise SupportError("The grace is 0% to 100% of its interval.")
    source = value.get("source") or "assumed"
    if source not in SOURCES:
        raise SupportError(f"source is one of {', '.join(SOURCES)}.")
    note = str(value.get("note") or "").strip()
    if len(note) > MAX_NOTE:
        raise SupportError(f"The note is up to {MAX_NOTE} characters.")
    return {"failure_mode_ids": sorted(set(ids)), "reference": {"value": float(f"{every:.6g}"), "unit": unit},
            "impact": clean_impact(value.get("impact")), "grace": float(f"{grace:.6g}"), "source": source,
            "note": note}


# ---- reading it ------------------------------------------------------------------------------

def _x(k: float) -> str:
    return f"× {k:.3g}"


def impact_words(impact: dict | None) -> str:
    """"failure rate × 2 if not done", or "no modelled impact"."""
    if not impact:
        return "no modelled impact"
    return f"failure rate {_x(impact['k'])} if not done"


def words(support: dict | None, mode_text: dict | None = None) -> str:
    """"Keeps it on its life: Bearing wear · failure rate × 2 if not done (Assumed)"."""
    if not support:
        return ""
    names = [(mode_text or {}).get(x) or "a failure mode" for x in support.get("failure_mode_ids") or []]
    what = ", ".join(names) if names else "its whole life"
    out = f"Keeps it on its life: {what} · {impact_words(support.get('impact'))}"
    if support.get("impact"):
        out += f" ({SOURCE_WORDS.get(support.get('source'), 'Assumed')})"
    return out


def marker(support: dict | None) -> dict | None:
    """The Maintenance table's small marker: {text, title, assumed}."""
    if not support:
        return None
    imp = support.get("impact")
    return {"text": f"Supports {_x(imp['k'])}" if imp else "Supports",
            "title": "Keeps it on its life: " + impact_words(imp)
                     + (f" ({SOURCE_WORDS.get(support.get('source'), 'Assumed')})" if imp else ""),
            "assumed": bool(imp) and support.get("source", "assumed") == "assumed"}


def _overlaps(a: dict, b: dict) -> bool:
    """Whether two supporting tasks hold up the same life: either supports the whole life, or
    they share a failure mode."""
    x, y = set(a.get("failure_mode_ids") or []), set(b.get("failure_mode_ids") or [])
    return not x or not y or bool(x & y)


def combined(task: dict, others: list[dict]) -> dict | None:
    """Several supporting tasks on one part multiply: {k, tasks [{id, name, k}]} for this task and
    the others on the same subject whose support overlaps it, each with an impact; None when it's
    the only one with an impact."""
    own = task.get("support")
    if not own:
        return None
    rows = [t for t in [task, *others] if t.get("support") and (t["support"].get("impact") or {}).get("k")
            and (t["id"] == task["id"] or _overlaps(own, t["support"]))]
    if len(rows) < 2:
        return None
    k = math.prod(float(t["support"]["impact"]["k"]) for t in rows)
    return {"k": float(f"{k:.4g}"), "tasks": [{"id": t["id"], "name": t.get("name") or "",
                                              "k": t["support"]["impact"]["k"]} for t in rows]}


# ---- the operations (methods added to ``Maintenance``) ---------------------------------------

def _sv():
    from backend.maintenance import service

    return service


class SupportOps:
    """Marking a task as one that keeps an item on its life, and reading it for the task's view."""

    def set_task_support(self, task_id, support) -> dict:
        """Mark a task as supporting (it keeps the item on its life model: greasing, an oil change)
        with what it supports, its reference interval, the optional impact if it isn't done, grace
        and source; None clears it. A fixed-interval task marked so restores none of the item's age
        (it doesn't renew it); cleared, what it leaves the item as is back to not set."""
        sv = _sv()
        task = self._live_task(task_id)
        from backend.maintenance.rbd_tree_plan import task_kind

        kind = task_kind(self, task)
        try:
            value = clean(support, task, self._task_modes(task["id"]))
        except SupportError as err:
            raise sv.Invalid(str(err)) from None
        if value is not None and kind not in KINDS:
            raise sv.Invalid(f"“{task['name']}” is a check ({kind.replace('_', ' ')}): it finds a failure on its way "
                             "rather than keeping the item on its life. Only routine work or a replace-or-restore "
                             "task can be supporting.")
        if value == task.get("support"):
            return self._task_view(self._get(task["id"], "Task"))
        if kind == "fixed_interval":
            if value is not None and (task.get("restoration") != RESTORES_NONE or task.get("restorations")):
                self._emit("task.restoration_set", {"id": task["id"], "restoration": dict(RESTORES_NONE)})
            elif value is None and task.get("restoration") == RESTORES_NONE and not task.get("restorations"):
                self._emit("task.restoration_set", {"id": task["id"], "restoration": None})
        self._emit("task.support_set", {"id": task["id"], "support": value})
        return self._task_view(self._get(task["id"], "Task"))

    def _support_view(self, task: dict) -> dict:
        """The task view's ``support``: the record, in words, the failure modes it names and how it
        combines with the other supporting tasks on its subject. None when it isn't supporting."""
        own = task.get("support")
        if not own:
            return {"support": None}
        modes = {m["id"]: m["text"] for m in self._task_modes(task["id"])}
        others = []
        for subject in self.s.out(self.org, task["id"], "ON"):
            others = [t for t in self.s.inn(self.org, subject["id"], "ON") if t.get("label") == "Task"
                      and t["id"] != task["id"] and not t.get("retired") and t.get("support")]
        return {"support": {**own, "words": words(own, modes), "marker": marker(own),
                            "modes": [{"id": x, "text": modes.get(x, "")} for x in own.get("failure_mode_ids") or []],
                            "combined": combined(task, others)}}
