"""Deleting a row of a position's RCM with everything under it, and undoing it.

The RCM and FME(C)A tabs' "Delete…" on a function, a performance standard, a
functional failure or a failure mode takes everything below it, the way a
position's delete does (tree_delete.py): a function takes its performance
standards, functional failures, the failure modes under them (and those placed
directly under it, the FME(C)A's way), their tasks and the documents on it; a
standard takes the functional failures that breach it, with their modes and
tasks; a functional failure its modes and tasks; a failure mode its tasks. A
task serving a failure mode outside what goes is unlinked and kept; one serving
only what goes is retired. Links from a functional failure to the failures it
causes or results from go too. Nothing is erased: the log keeps every event and
the whole lot comes back as a unit with :meth:`RcmDeleteOps.restore_rcm`.

The plain removes (``remove_function`` and the rest without ``cascade``) keep
their old meaning: the failure modes stay on the position, unassigned.

Built from the events each step already has (``functional_failure.unlinked``,
``task.unlinked``, ``task.retired``, ``failure_mode.retired``,
``functional_failure.removed``, ``standard.removed``, ``document.removed``,
``function.removed``), so every view treats it as it treats those. New events
(older logs replay unchanged):

* ``rcm.deleted {id, n, root_id, kind, name, position_id, on, functions,
  standards, functional_failures, failure_modes, tasks, task_links, links,
  breaches, documents}``: the record of one delete (an ``RcmDeletion`` node;
  ``n`` numbers them, so the latest of a root is the one restored);
* ``rcm.restored {id, on}``: that delete was undone;
* ``function.restored {id, on}``, ``functional_failure.restored {id, on}``: a
  removed one back in use;
* ``standard.restored {id, on, functional_failure_ids}``: a removed standard
  back, breached again by those functional failures (its removal unlinked them).
"""

from __future__ import annotations

from backend.maintenance.store import GraphStore, new_id

KINDS = ("function", "standard", "functional_failure", "failure_mode")
LABELS = {"function": "Function", "standard": "Standard", "functional_failure": "FunctionalFailure",
          "failure_mode": "FailureMode"}
TASK_REASON = "Its failure mode was deleted."  # restore_failure_mode brings back tasks retired with this reason


# ---- projectors ---------------------------------------------------------------------------

_RECORD = ("root_id", "kind", "name", "position_id", "on", "functions", "standards", "functional_failures",
           "failure_modes", "tasks", "task_links", "links", "breaches", "documents")


def _rcm_deleted(s: GraphStore, org: str, p: dict) -> None:
    s.put_node(org, p["id"], "RcmDeletion", {k: p.get(k) for k in _RECORD} | {"n": p["n"], "restored": False})


def _rcm_restored(s: GraphStore, org: str, p: dict) -> None:
    s.patch_node(org, p["id"], {"restored": True, "restored_on": p.get("on")})


def _back(s: GraphStore, org: str, p: dict) -> None:
    """A removed function or functional failure back in use (the day kept)."""
    s.patch_node(org, p["id"], {"removed": False, "removed_on": None, "removed_reason": "",
                                "restored_on": p.get("on")})


def _standard_restored(s: GraphStore, org: str, p: dict) -> None:
    _back(s, org, p)
    for ff_id in p.get("functional_failure_ids") or []:
        for old in s.out(org, ff_id, "BREACHES"):
            s.delete_edge(org, "BREACHES", ff_id, old["id"])
        s.put_edge(org, "BREACHES", ff_id, p["id"])


PROJECTORS = {
    "rcm.deleted": _rcm_deleted,
    "rcm.restored": _rcm_restored,
    "function.restored": _back,
    "functional_failure.restored": _back,
    "standard.restored": _standard_restored,
}


def _sv():
    from backend.maintenance import service

    return service


def _plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def _quoted(text) -> str:
    text = " ".join(str(text or "").split())
    return f"“{text[:80]}{'…' if len(text) > 80 else ''}”"


# ---- the operations (a mixin of Maintenance) ----------------------------------------------

class RcmDeleteOps:
    """Methods added to ``Maintenance``."""

    def _rcm_root(self, kind: str, root_id) -> tuple[dict, dict]:
        """The live row a delete starts from, and its position."""
        sv = _sv()
        if kind not in KINDS:
            raise sv.Invalid(f"Delete a {', a '.join(k.replace('_', ' ') for k in KINDS)}.")
        root_id = str(root_id or "")
        if self.s.node(self.org, root_id, LABELS[kind]) is None:
            raise sv.NotFound(f"{LABELS[kind]} {root_id}")
        if kind == "function":
            return self._live_function(root_id)
        if kind == "standard":
            st, fn = self._live_standard(root_id)
            return st, self.s.inn(self.org, fn["id"], "PERFORMS")[0]
        if kind == "functional_failure":
            ff, _, position = self._live_ff(root_id)
            return ff, position
        return self._live_mode(root_id)

    def _rcm_delete_plan(self, kind: str, root_id) -> dict:
        """Everything one RCM delete would take, worked out before anything is written."""
        root, position = self._rcm_root(kind, root_id)
        functions, standards, ffs, modes, documents = [], [], [], [], []
        if kind == "function":
            functions = [root["id"]]
            standards = [st["id"] for st in self._standards_of(root["id"])]
            ffs = [ff["id"] for ff in self._failures_of(root["id"])]
            modes = [m["id"] for m in self._fn_direct_modes(root["id"])]
            documents = [d["id"] for d in self.documents_of(root["id"])]
        elif kind == "standard":
            standards = [root["id"]]
            ffs = sorted((ff for ff in self.s.inn(self.org, root["id"], "BREACHES") if not ff.get("removed")),
                         key=lambda f: (f.get("order") or 0, str(f.get("text") or "").lower()))
            ffs = [ff["id"] for ff in ffs]
        elif kind == "functional_failure":
            ffs = [root["id"]]
        else:
            modes = [root["id"]]
        for ff_id in ffs:
            modes += [m["id"] for m in self._ff_modes(ff_id) if m["id"] not in modes]
        going = set(modes)
        tasks, task_links, seen = [], [], set()
        for mode_id in modes:
            for t in self._mode_tasks(mode_id):
                if t["id"] in seen:
                    continue
                seen.add(t["id"])
                served = {m["id"] for m in self._task_modes(t["id"])}
                if served <= going:
                    tasks.append(t["id"])
                else:
                    task_links += [[t["id"], m] for m in sorted(served & going)]
        links = []
        for ff_id in ffs:
            for e in self.s.inn(self.org, ff_id, "RESULTS_FROM"):
                links.append([e["id"], ff_id])
            for c in self.s.out(self.org, ff_id, "RESULTS_FROM"):
                if [ff_id, c["id"]] not in links:
                    links.append([ff_id, c["id"]])
        # Standards that go: the functional failures that breach them, put back on undo.
        gone_std = set(standards)
        breaches = [[ff_id, st["id"]] for ff_id in ffs for st in self.s.out(self.org, ff_id, "BREACHES")
                    if st["id"] in gone_std]
        return {
            "root": root, "kind": kind, "position": position, "functions": functions, "standards": standards,
            "functional_failures": ffs, "failure_modes": modes, "tasks": tasks, "task_links": task_links,
            "links": links, "breaches": breaches, "documents": documents,
            "counts": {
                "standards": len(standards) - (1 if kind == "standard" else 0),
                "functional_failures": len(ffs) - (1 if kind == "functional_failure" else 0),
                "failure_modes": len(modes) - (1 if kind == "failure_mode" else 0),
                "tasks": len(tasks), "tasks_kept": len({t for t, _ in task_links}),
                "links": len(links), "documents": len(documents),
            },
        }

    @staticmethod
    def _rcm_delete_summary(plan: dict) -> str:
        """In a sentence: "Delete “Pump water” and everything under it? 2 functional
        failures, 5 failure modes, 3 tasks." """
        c = plan["counts"]
        parts = []
        if c["standards"]:
            parts.append(_plural(c["standards"], "performance standard"))
        if c["functional_failures"]:
            parts.append(_plural(c["functional_failures"], "functional failure"))
        if c["failure_modes"]:
            parts.append(_plural(c["failure_modes"], "failure mode"))
        if c["tasks"]:
            parts.append(_plural(c["tasks"], "task"))
        what = f"Delete {_quoted(plan['root'].get('text'))}" + (" and everything under it" if parts else "") + "?"
        return what + (" " + ", ".join(parts) + "." if parts else "")

    def rcm_delete_preview(self, kind: str, root_id) -> dict:
        """What deleting an RCM row with everything under it would take (nothing written)."""
        plan = self._rcm_delete_plan(kind, root_id)
        return {"dry_run": True, "kind": kind, "id": plan["root"]["id"], "name": plan["root"].get("text"),
                "position_id": plan["position"]["id"], **plan["counts"], "summary": self._rcm_delete_summary(plan)}

    def rcm_delete(self, kind: str, root_id) -> dict:
        """Delete a function, standard, functional failure or failure mode with
        everything under it (see the module docstring); undo with :meth:`restore_rcm`.
        Documents on a function are taken off with it; a kept PDF's bytes stay, so
        the undo brings it back whole."""
        plan = self._rcm_delete_plan(kind, root_id)
        root, today = plan["root"], self.today()
        for effect_id, cause_id in plan["links"]:
            self._link_event("functional_failure.unlinked", effect_id, cause_id)
        for task_id, mode_id in plan["task_links"]:
            self._emit("task.unlinked", {"id": task_id, "failure_mode_id": mode_id, "on": today})
        for t in plan["tasks"]:
            self._emit("task.retired", {"id": t, "on": today, "reason": TASK_REASON})
        for mode_id in plan["failure_modes"]:
            self._emit("failure_mode.retired", {"id": mode_id, "on": today})
        for ff_id in plan["functional_failures"]:
            self._emit("functional_failure.removed", {"id": ff_id, "on": today})
        for st_id in plan["standards"]:
            self._emit("standard.removed", {"id": st_id, "on": today})
        for d in plan["documents"]:
            self._emit("document.removed", {"id": d, "on": today})
        for fn_id in plan["functions"]:
            self._emit("function.removed", {"id": fn_id, "on": today})
        did = new_id()
        self._emit("rcm.deleted", {
            "id": did, "n": self.s.count(self.org, "RcmDeletion") + 1, "root_id": root["id"], "kind": kind,
            "name": root.get("text") or "", "position_id": plan["position"]["id"], "on": today,
            **{k: plan[k] for k in ("functions", "standards", "functional_failures", "failure_modes", "tasks",
                                    "task_links", "links", "breaches", "documents")},
        })
        summary = self._rcm_delete_summary(plan).replace("?", ".", 1).replace("Delete ", "Deleted ", 1)
        return {"deleted": root["id"], "deletion_id": did, "kind": kind, "name": root.get("text"),
                "position_id": plan["position"]["id"], **plan["counts"], "summary": summary,
                "removed": root["id"], "failure_modes_retired": plan["failure_modes"],
                "tasks_retired": plan["tasks"], "tasks_unlinked": sorted({t for t, _ in plan["task_links"]}),
                "documents_removed": plan["documents"], "links_removed": len(plan["links"])}

    def _latest_rcm_deletion(self, root_id: str) -> dict | None:
        found = [d for d in self.s.nodes(self.org, "RcmDeletion")
                 if d.get("root_id") == root_id and not d.get("restored")]
        return max(found, key=lambda d: d.get("n") or 0) if found else None

    def restore_rcm(self, root_id) -> dict:
        """Undo the latest delete (with everything under it) of a function,
        standard, functional failure or failure mode: everything it took comes
        back as it was. What has changed since (a failure mode of the same name
        added meanwhile, a task's position retired) is left and listed in
        ``skipped``."""
        sv = _sv()
        d = self._latest_rcm_deletion(str(root_id or ""))
        if d is None:
            raise sv.Invalid("Nothing deleted there to bring back.")
        position = self.s.node(self.org, d["position_id"]) or {}
        if position.get("retired"):
            raise sv.Invalid(f"{position.get('name') or 'Its position'} is deleted: restore that first.")
        if d["kind"] in ("standard", "functional_failure"):
            fn_id = (self.s.inn(self.org, d["root_id"], "HELD_TO" if d["kind"] == "standard" else "FAILS_AS")
                     or [{}])[0].get("id")
            fn = self.s.node(self.org, fn_id) if fn_id else None
            if fn is None or fn.get("removed"):
                raise sv.Invalid("Its function is deleted: restore that first.")
        today = self.today()
        skipped: list[str] = []

        def node(nid):
            return self.s.node(self.org, nid) or {}

        functions = [f for f in d.get("functions") or [] if node(f).get("removed")]
        for f in functions:
            self._emit("function.restored", {"id": f, "on": today})
        ffs_back = [f for f in d.get("functional_failures") or [] if node(f).get("removed")]
        standards = []
        for st in d.get("standards") or []:
            if node(st).get("removed"):
                breached = [ff for ff, s_id in d.get("breaches") or [] if s_id == st]
                self._emit("standard.restored", {"id": st, "on": today, "functional_failure_ids": breached})
                standards.append(st)
        for f in ffs_back:
            self._emit("functional_failure.restored", {"id": f, "on": today})
        modes = []
        for mode_id in d.get("failure_modes") or []:
            fm = node(mode_id)
            if not fm.get("retired") or fm.get("merged_into"):
                continue
            same = next((m for m in self._modes_on(d["position_id"]) if sv._same_text(m["text"], fm["text"])), None)
            if same:
                skipped.append(f"{_quoted(fm['text'])} didn't come back: {position.get('name') or 'the position'} "
                               "has a failure mode of that name now.")
                continue
            self._emit("failure_mode.restored", {"id": mode_id, "on": today})
            if any(ff.get("removed") for ff in self.s.inn(self.org, mode_id, "CAUSED_BY")):
                self._emit("failure_mode.assigned", {"id": mode_id, "functional_failure_id": None})
            if any(fn.get("removed") for fn in self.s.inn(self.org, mode_id, "FAILS_DIRECTLY_AS")):
                self._emit("failure_mode.placed", {"id": mode_id, "function_id": None})
            modes.append(mode_id)
        tasks = []
        for t in d.get("tasks") or []:
            task = node(t)
            if not task.get("retired"):
                continue
            subject = sv._subject(self.s, self.org, task)
            dead = [m for m in self.s.out(self.org, t, "MITIGATES") if m.get("retired") or m.get("merged_into")]
            if subject is None or subject.get("retired") or dead:
                skipped.append(f"The task {_quoted(task.get('name'))} wasn't put back on the schedule: "
                               + ("what it's on is deleted." if not dead else "its failure mode didn't come back."))
                continue
            self._emit("task.restored", {"id": t, "on": today})
            tasks.append(t)
        relinked = 0
        for task_id, mode_id in d.get("task_links") or []:
            task, fm = node(task_id), node(mode_id)
            if task and fm and not task.get("retired") and not fm.get("retired") \
                    and self.s.edge(self.org, "MITIGATES", task_id, mode_id) is None:
                self._emit("task.linked", {"id": task_id, "failure_mode_id": mode_id, "on": today})
                relinked += 1
        links = 0
        for effect_id, cause_id in d.get("links") or []:
            ends = [node(effect_id), node(cause_id)]
            places = [node(self._ff_position_id(x) or "") for x in (effect_id, cause_id)]
            if all(ends) and not any(e.get("removed") for e in ends) and all(places) \
                    and not any(p.get("retired") for p in places) \
                    and self.s.edge(self.org, "RESULTS_FROM", effect_id, cause_id) is None:
                self._link_event("functional_failure.linked", effect_id, cause_id)
                links += 1
        documents = [x for x in d.get("documents") or [] if node(x).get("removed")]
        for x in documents:
            self._emit("document.restored", {"id": x, "on": today})
        self._emit("rcm.restored", {"id": d["id"], "on": today})
        return {"restored": d["root_id"], "deletion_id": d["id"], "kind": d["kind"], "name": d.get("name"),
                "position_id": d["position_id"], "functions_restored": len(functions),
                "standards_restored": len(standards), "functional_failures_restored": len(ffs_back),
                "failure_modes_restored": len(modes), "tasks_restored": len(tasks), "tasks_relinked": relinked,
                "links_restored": links, "documents_restored": len(documents), "skipped": skipped}
