"""Moving RCM studies onto the maintenance positions.

An RCM study is a document of its own: functions › functional failures ›
failure modes, each mode with a decision. Applying it to a position copies the
failure modes and tasks across (``Maintenance.apply_rcm``), but its functions
and functional failures stayed in the study, so the two could drift apart. On
the positions the study's tree is the graph itself: a position PERFORMS
functions, a function FAILS_AS functional failures, a functional failure is
CAUSED_BY failure modes (docs/maintenance-graph.md).

For each study this module

* finds every position it was applied to (in any workspace: a sample study
  applied to someone's position counts), by the ``study_id`` / ``rcm_mode_id``
  its failure modes and tasks carry; a study never applied gets a new position
  in its owner's workspace (``position_from_rcm``; never for a sample);
* applies it once more, so each position has every mode and task (and each
  mode its decision and the evidence linked);
* adds the study's functions and functional failures to each position, and
  puts each failure mode under its functional failure;
* puts the study's description on the position's description (the app shows
  it clamped).

Every step matches what's already there (functions by ``rcm_function_id``,
functional failures by ``rcm_failure_id``, modes by ``rcm_mode_id``), so
running it again changes nothing. A dry run (the default) runs the same steps on
a throwaway copy of the graph and reports what would be written; nothing is
written anywhere. A real run marks each study it moved (``migrated_to``, the
position): the study is kept, unchanged, as read-only history.
"""

from __future__ import annotations

from backend.maintenance.service import (
    LONG_TEXT, PROJECTION_VERSION, PROJECTORS, Maintenance, NotFound, shortened,
)
from backend.maintenance.store import SYNC_BATCH, GraphStore, new_id

ACTOR = "rcm-migration"


class _Recording(Maintenance):
    """A Maintenance that keeps the events it writes, for the report."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.written: list[tuple[str, dict]] = []

    def _emit(self, type: str, payload: dict) -> None:
        super()._emit(type, payload)
        self.written.append((type, payload))


def scratch_copy(store) -> GraphStore:
    """A throwaway in-memory graph with every event of ``store``'s log: the dry
    run writes here, never to the real log."""
    copy = GraphStore(":memory:", PROJECTORS, version=PROJECTION_VERSION)
    seq = 0
    while True:
        batch = store.log.since(seq, SYNC_BATCH)
        if not batch:
            break
        for e in batch:
            copy.log.append({"id": new_id(), "org": e["org"], "type": e["type"], "at": "", "actor": None,
                             "payload": e["payload"]})
        seq = batch[-1]["seq"]
    copy.sync()
    return copy


def _mode_ids(study) -> set[str]:
    return {m["id"] for fn in study.functions or [] for f in fn.get("failures") or []
            for m in f.get("modes") or [] if isinstance(m, dict) and m.get("id")}


def applied_index(store) -> dict[str, dict[str, set[str]]]:
    """Where studies were applied: study id (and each mode's rcm_mode_id) →
    {org: the live positions with a failure mode or task from it}."""
    out: dict[str, dict[str, set[str]]] = {}
    orgs = set(store.orgs_with("FailureMode")) | set(store.orgs_with("Task"))
    for org in sorted(orgs):
        live = {p["id"] for p in store.nodes(org, "Position") if not p.get("retired")}
        mode_pos = {dst: src for src, dst in store.pairs(org, "CAN_FAIL_AS")}
        task_on = {src: dst for src, dst in store.pairs(org, "ON")}
        marks = [(fm, mode_pos.get(fm["id"])) for fm in store.nodes(org, "FailureMode")]
        marks += [(t, task_on.get(t["id"])) for t in store.nodes(org, "Task") if not t.get("retired")]
        for node, pid in marks:
            if pid not in live:
                continue
            for key in (node.get("study_id"), node.get("rcm_mode_id")):
                if key:
                    out.setdefault(key, {}).setdefault(org, set()).add(pid)
    return out


def targets(index: dict, study) -> dict[str, list[str]]:
    """{org: [position ids]} the study was applied to."""
    found: dict[str, set[str]] = {}
    for key in (study.id, *_mode_ids(study)):
        for org, positions in (index.get(key) or {}).items():
            found.setdefault(org, set()).update(positions)
    return {org: sorted(p) for org, p in sorted(found.items())}


def _spine(m: Maintenance, position_id: str, study) -> None:
    """The study's functions and functional failures on the position, and each of
    its failure modes under its functional failure (what's there already is
    matched, not repeated)."""
    fns = {f.get("rcm_function_id"): f for f in m._functions_of(position_id) if f.get("rcm_function_id")}
    modes = {fm.get("rcm_mode_id"): fm for fm in m._modes_on(position_id) if fm.get("rcm_mode_id")}
    for fn in study.functions or []:
        found = fns.get(fn.get("id"))
        fn_id = found["id"] if found else m.add_function(
            position_id, shortened(fn.get("text"), LONG_TEXT)[0], shortened(fn.get("standard"), LONG_TEXT)[0],
            rcm_function_id=fn.get("id"), study_id=study.id)["id"]
        ffs = {x.get("rcm_failure_id"): x for x in m._failures_of(fn_id) if x.get("rcm_failure_id")}
        for failure in fn.get("failures") or []:
            ff = ffs.get(failure.get("id"))
            ff_id = ff["id"] if ff else m.add_functional_failure(
                fn_id, shortened(failure.get("text"), LONG_TEXT)[0], rcm_failure_id=failure.get("id"),
                study_id=study.id)["id"]
            for mode in failure.get("modes") or []:
                fm = modes.get(mode.get("id")) if isinstance(mode, dict) else None
                if fm is not None:
                    m.assign_failure_mode(fm["id"], ff_id)


def _describe(m: Maintenance, position_id: str, study) -> None:
    """The study's description at the end of the position's (once)."""
    said = (study.description or "").strip()
    if not said:
        return
    had = (m._get(position_id, "Position").get("description") or "").strip()
    if said in had:
        return
    room = LONG_TEXT - len(had) - 2 if had else LONG_TEXT
    if room < 40:
        return
    text = shortened(said, room)[0]
    m.update_position(position_id, description=f"{had}\n\n{text}" if had else text)


def migrate_study(store, db, study, index: dict, actor: str = ACTOR) -> dict:
    """Move one study onto its positions (writes to ``store``). Returns what was
    done: {study_id, name, owner, positions: [{org, id, name, created}], events,
    skipped}."""
    from backend.services import samples as samples_service
    from backend.services import time_zones

    out = {"study_id": study.id, "name": study.name, "owner": study.owner_id, "positions": [], "events": [],
           "skipped": None}
    if getattr(study, "migrated_to", None):
        out["skipped"] = f"already moved (to position {study.migrated_to})"
        return out
    if not _mode_ids(study) and not study.functions:
        out["skipped"] = "empty: no functions"
        return out
    where = targets(index, study)
    sample = samples_service.is_sample(study.owner_id)
    if not where and sample:
        out["skipped"] = "a sample not applied anywhere"
        return out
    if not where:
        where = {study.owner_id: []}
    for org, positions in where.items():
        m = _Recording(store, org, actor, limited=False, time_zone=time_zones.of_owner(db, org))
        if not positions:
            made = m.position_from_rcm(study)["position"]
            out["positions"].append({"org": org, "id": made["id"], "name": made["name"], "created": True})
            positions = [made["id"]]
        else:
            for pid in positions:
                try:
                    m.apply_rcm(pid, study)
                except NotFound:
                    continue
                out["positions"].append({"org": org, "id": pid, "name": m._get(pid, "Position")["name"],
                                         "created": False})
        for pid in positions:
            _spine(m, pid, study)
            _describe(m, pid, study)
        out["events"] += [(org, t, p) for t, p in m.written]
    return out


def migrate(db, store, *, owner: str | None = None, study_id: str | None = None, dry_run: bool = True,
            actor: str = ACTOR) -> list[dict]:
    """Move every RCM study (or one owner's, or one) onto the positions. With
    ``dry_run`` (the default) on a throwaway copy of the graph: nothing is
    written to the log or the studies. A real run marks each study moved into its
    owner's workspace (``migrated_to``: the position; samples are never marked)."""
    from backend.db import from_doc
    from backend.schema import RcmStudy
    from backend.services import samples as samples_service

    work = scratch_copy(store) if dry_run else store
    index = applied_index(work)
    query: dict = {}
    if owner:
        query["owner_id"] = owner
    if study_id:
        query["_id"] = study_id
    results = []
    for doc in db.rcm_studies.find(query).sort("created_at", 1):
        study = from_doc(RcmStudy, doc)
        result = migrate_study(work, db, study, index, actor)
        own = [p for p in result["positions"] if p["org"] == study.owner_id]
        if not dry_run and own and not samples_service.is_sample(study.owner_id):
            db.rcm_studies.update_one({"_id": study.id}, {"$set": {
                "migrated_to": own[0]["id"], "migrated_positions": [p["id"] for p in own]}})
            result["marked"] = own[0]["id"]
        results.append(result)
    return results


# ---- the report ------------------------------------------------------------------------

def _counts(events) -> dict[str, int]:
    out: dict[str, int] = {}
    for _, t, _ in events:
        out[t] = out.get(t, 0) + 1
    return out


WORDS = {
    "position.created": "position", "position.updated": "position description",
    "function.added": "function", "functional_failure.added": "functional failure",
    "failure_mode.added": "failure mode", "failure_mode.assigned": "failure mode put under its functional failure",
    "failure_mode.analysed": "decision or analysis copied", "task.added": "task", "task.updated": "task updated",
}


def report(results: list[dict], dry_run: bool) -> str:
    """The results in words, one block per study."""
    lines = [("DRY RUN: nothing was written. " if dry_run else "Written. ")
             + f"{len(results)} RCM {'study' if len(results) == 1 else 'studies'}."]
    for r in results:
        lines.append("")
        lines.append(f"Study {r['study_id']} “{r['name']}” (owner {r['owner']})")
        if r["skipped"]:
            lines.append(f"  skipped: {r['skipped']}")
            continue
        for p in r["positions"]:
            lines.append(f"  {'new position' if p['created'] else 'position'} {p['id']} “{p['name']}” "
                         f"in workspace {p['org']}")
        counts = _counts(r["events"])
        if not counts:
            lines.append("  nothing to do: already on its positions")
        for t, n in counts.items():
            lines.append(f"  {'would write' if dry_run else 'wrote'} {n} × {WORDS.get(t, t)} ({t})")
        for org, t, p in r["events"]:
            if t in ("function.added", "functional_failure.added"):
                lines.append(f"    + {WORDS[t]}: {shortened(p['text'], 90)[0]}")
        if r.get("marked"):
            lines.append(f"  marked moved to position {r['marked']}")
    return "\n".join(lines)
