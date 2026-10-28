"""``maintenance_apply``: many changes to the maintenance tree in one call.

A batch is a list of the write actions the typed ``maintenance_<area>`` tools
already have (``{"do": "failure_modes.add", "args": {...}}``), run in order.
``ref`` names an operation's result so later ones can use it (``"@p"`` is op
p's ``id``; ``"@p.fitted.item.id"`` another field). Every operation keeps its
own argument check and error text, prefixed with its place in the batch.

Two passes. First every operation runs on a throwaway in-memory copy of the
workspace's graph (:func:`store.scratch_copy`): a failure there refuses the
whole batch and nothing is written. Then, unless ``dry_run``, the same
operations run on the live graph in order; a failure there (rare: a change
made meanwhile) stops the batch, or with ``on_error`` continue, runs the rest.

Delete-type operations need ``confirm``, the thing's name as it is now, so an
agent never deletes what it hasn't read. The answer carries each operation's
result, counts, the events written, and ``undo``: the reverse of every create
and retire it made.
"""

from __future__ import annotations

import contextvars
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

MAX_OPS = 200
MAX_DELETES = 50
AUTO_DRY_RUN_OVER = 25  # a bigger batch dry-runs unless told otherwise
SHOW_FULL_RESULTS_UP_TO = 50  # above this, results are cut to {id, name}
KEY_TTL = timedelta(hours=24)
MAX_KEY = 64
_REF = re.compile(r"^@([A-Za-z_][A-Za-z0-9_-]{0,39})(?:\.(.+))?$")
_REF_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,39}$")

#: The Maintenance a tool body acts on while a batch runs (the scratch copy's,
#: then the live one's), and whether this is the dry pass (bytes outside the
#: event log, a PDF's or a photo's, are left alone then).
ACTIVE_M: contextvars.ContextVar = contextvars.ContextVar("maintenance_apply_m", default=None)
DRY: contextvars.ContextVar = contextvars.ContextVar("maintenance_apply_dry", default=False)

#: Actions a batch can't carry: not tree edits, or with their own dry run, or
#: with side effects outside the event log. They stay single calls.
EXCLUDED = {
    "reliability.fit_class_model", "topology.generate_rbd", "workspace.set_time_zone",
    "workspace.import_history", "parts.import_bom", "parts.positions_from_structure", "item_classes.import",
    "item_classes.load_starter", "item_classes.import_conditions", "manufacturers.link_by_name",
    "positions.adopt_placements", "positions.add_sample_truck", "attachments.photo_link",
}

#: Delete-type actions: the argument naming what goes, for the confirm check.
DELETES = {
    "positions.retire": "position_id", "locations.retire": "location_id", "items.retire": "item_id",
    "fitments.void": "fitment_id", "tasks.retire": "task_id", "failure_modes.retire": "failure_mode_id",
    "failure_modes.remove_function": "function_id", "failure_modes.remove_functional_failure": "functional_failure_id",
    "failure_modes.merge": "failure_mode_id", "work_orders.cancel": "work_order_id",
    "work_orders.remove_entry": "entry_id", "measurements.void": "reading_id",
    "measurements.retire_point": "point_id", "parts.retire": "part_id", "parts.remove_from_position": "listing_id",
    "parts.remove_component": "component_id", "parts.unlink": "other_part_id", "topology.disconnect": "interface_id",
    "topology.retire_group": "group_id", "item_classes.retire": "item_class_id",
    "item_classes.retire_condition": "condition_id", "item_classes.remove_condition": "condition_id",
    "manufacturers.retire": "manufacturer_id", "manufacturers.merge": "manufacturer_id",
    "attachments.remove_photo": "photo_id", "attachments.unlink_photo": "photo_id",
    "attachments.remove_document": "document_id", "attachments.clear_coordinates": "target_id",
}

#: Creates, and the delete that undoes each: (action, the argument it takes).
CREATES = {
    "positions.create": ("positions.retire", "position_id"), "positions.copy": ("positions.retire", "position_id"),
    "locations.create": ("locations.retire", "location_id"), "items.create": ("items.retire", "item_id"),
    "failure_modes.add": ("failure_modes.retire", "failure_mode_id"),
    "failure_modes.add_function": ("failure_modes.remove_function", "function_id"),
    "failure_modes.add_functional_failure": ("failure_modes.remove_functional_failure", "functional_failure_id"),
    "failure_modes.add_task": ("tasks.retire", "task_id"),
    "tasks.create": ("tasks.retire", "task_id"), "work_orders.open": ("work_orders.cancel", "work_order_id"),
    "measurements.add_point": ("measurements.retire_point", "point_id"), "parts.create": ("parts.retire", "part_id"),
    "topology.connect": ("topology.disconnect", "interface_id"),
    "topology.create_group": ("topology.retire_group", "group_id"),
    "item_classes.create": ("item_classes.retire", "item_class_id"),
    "item_classes.create_condition": ("item_classes.retire_condition", "condition_id"),
    "manufacturers.create": ("manufacturers.retire", "manufacturer_id"),
    "attachments.add_document": ("attachments.remove_document", "document_id"),
}

#: Retires and the restore that undoes each (and back).
RESTORES = {
    "positions.retire": "positions.restore", "locations.retire": "locations.restore", "items.retire": "items.restore",
    "tasks.retire": "tasks.restore", "failure_modes.retire": "failure_modes.restore", "parts.retire": "parts.restore",
    "measurements.retire_point": "measurements.restore_point", "item_classes.retire": "item_classes.restore",
    "item_classes.retire_condition": "item_classes.restore_condition", "manufacturers.retire": "manufacturers.restore",
    "topology.disconnect": "topology.reconnect", "topology.retire_group": "topology.restore_group",
    "attachments.remove_document": "attachments.restore_document",
}
RETIRES = {restore: retire for retire, restore in RESTORES.items()}

#: Links and the unlink that undoes each (and back): the same arguments.
LINKS = {"tasks.link": "tasks.unlink", "tasks.unlink": "tasks.link"}

_UPDATE_WORDS = ("update", "set_", "assign", "decide", "move", "link", "correct", "check", "status", "place",
                 "reorder", "stock", "labour", "part_used", "cost", "accept", "reject", "apply_", "exclude_",
                 "add_to_position", "add_component", "fit", "remove", "close", "generate", "record", "photo",
                 "coordinates", "restore", "reconnect", "unlink_cause", "link_cause", "add_past")


class BatchRefused(ValueError):
    """The batch can't run as given (before anything is written)."""


def _norm(text) -> str:
    return " ".join(str(text or "").lower().split())


def _hash(operations: list) -> str:
    return hashlib.sha256(json.dumps(operations, sort_keys=True, default=str).encode()).hexdigest()[:32]


def classify(do: str) -> str:
    """create, delete, update or other, for the counts."""
    if do in DELETES:
        return "delete"
    if do in CREATES or do.split(".")[1].startswith(("create", "add", "open", "connect")):
        return "create"
    if any(w in do.split(".")[1] for w in _UPDATE_WORDS):
        return "update"
    return "other"


def parse(operations, tables: dict) -> list[dict]:
    """The operations checked for shape: a list of {ref?, do, args, confirm?},
    each ``do`` a known write action, refs unique and never forward."""
    if not isinstance(operations, list) or not operations:
        raise BatchRefused("operations is a list of {do, args, ref?, confirm?}, at least one.")
    if len(operations) > MAX_OPS:
        raise BatchRefused(f"At most {MAX_OPS} operations in one batch (this one has {len(operations)}): split it.")
    seen: set[str] = set()
    out = []
    deletes = 0
    for i, op in enumerate(operations):
        at = f"op {i}"
        if not isinstance(op, dict):
            raise BatchRefused(f"{at}: each operation is an object {{do, args, ref?, confirm?}}.")
        do = op.get("do")
        if not isinstance(do, str) or "." not in do:
            raise BatchRefused(f"{at}: do is '<area>.<action>', e.g. 'positions.create'.")
        area, action = do.split(".", 1)
        table = tables.get(f"maintenance_{area}")
        if table is None or action not in table[1]:
            areas = ", ".join(sorted(t[len("maintenance_"):] for t in tables))
            raise BatchRefused(f"{at}: no write action '{do}'. Areas: {areas}; each tool's description lists its "
                               "actions.")
        if do in EXCLUDED:
            raise BatchRefused(f"{at}: {do} isn't allowed in a batch (it has its own dry run, or acts outside the "
                               f"tree): call maintenance_{area} {action} on its own.")
        args = op.get("args")
        if args is None:
            args = {}
        if not isinstance(args, dict):
            raise BatchRefused(f"{at} ({do}): args is an object of the action's arguments.")
        if do == "attachments.add_document" and args.get("upload_id"):
            raise BatchRefused(f"{at} ({do}): a PDF (upload_id) goes through maintenance_attachments add_document "
                               "on its own; in a batch, add a link (url).")
        ref = op.get("ref")
        if ref is not None:
            if not isinstance(ref, str) or not _REF_NAME.match(ref):
                raise BatchRefused(f"{at}: ref is a short name (letters, digits, _ and -), e.g. 'p1'.")
            if ref in seen:
                raise BatchRefused(f"{at}: ref '{ref}' is used twice.")
        for name, _ in _refs_in(args):
            if name not in seen:
                raise BatchRefused(f"{at} ({do}): @{name} isn't the ref of an earlier operation (refs can't point "
                                   "forward).")
        if ref is not None:
            seen.add(ref)
        confirm = op.get("confirm")
        if confirm is not None and not isinstance(confirm, str):
            raise BatchRefused(f"{at}: confirm is text: the name of what's being deleted.")
        if do in DELETES:
            deletes += 1
        extra = set(op) - {"ref", "do", "args", "confirm"}
        if extra:
            raise BatchRefused(f"{at}: unknown field{'s' if len(extra) != 1 else ''} {', '.join(sorted(extra))}: an "
                               "operation has do, args, ref and confirm only.")
        out.append({"index": i, "ref": ref, "do": do, "area": area, "action": action, "args": args,
                    "confirm": confirm})
    if deletes > MAX_DELETES:
        raise BatchRefused(f"At most {MAX_DELETES} delete-type operations in one batch (this one has {deletes}).")
    return out


def _refs_in(value) -> list[tuple[str, str | None]]:
    """Every @ref in an argument value (nested lists and objects too)."""
    found: list[tuple[str, str | None]] = []
    if isinstance(value, str):
        m = _REF.match(value)
        if m:
            found.append((m.group(1), m.group(2)))
    elif isinstance(value, dict):
        for v in value.values():
            found.extend(_refs_in(v))
    elif isinstance(value, list):
        for v in value:
            found.extend(_refs_in(v))
    return found


def _pick(result, path: str | None):
    """A field of an operation's result: its id, or a dotted path."""
    if path is None:
        if isinstance(result, dict) and result.get("id"):
            return result["id"]
        raise BatchRefused("its result has no id: name the field you want, e.g. @ref.position.id")
    at = result
    for part in path.split("."):
        if isinstance(at, list) and part.isdigit():
            at = at[int(part)]
        elif isinstance(at, dict) and part in at:
            at = at[part]
        else:
            raise BatchRefused(f"its result has no '{path}'")
    return at


def resolve(value, results: dict[str, Any], at: str):
    """The argument value with every @ref replaced by the earlier result's field."""
    if isinstance(value, str):
        m = _REF.match(value)
        if m:
            name, path = m.group(1), m.group(2)
            if name not in results:
                raise BatchRefused(f"{at}: @{name} refers to an operation that failed or was skipped.")
            try:
                return _pick(results[name], path)
            except BatchRefused as err:
                raise BatchRefused(f"{at}: @{name}: {err}.") from None
        return value
    if isinstance(value, dict):
        return {k: resolve(v, results, at) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v, results, at) for v in value]
    return value


# ---- what a delete must be confirmed with -------------------------------------------

def _names_of(m, node: dict) -> list[str]:
    """The strings that identify a node to a person (any one confirms a delete)."""
    label = node["label"]
    out = [node["id"]]
    for key in ("name", "text", "title", "part_number", "caption", "who", "part", "description"):
        if node.get(key):
            out.append(str(node[key]))
    if node.get("number") is not None:
        out.extend([str(node["number"]), f"#{node['number']}"])
    if label == "Fitment":
        for item in m.s.inn(m.org, node["id"], "IN"):
            out.append(item.get("name") or "")
    elif label == "Reading":
        out.append(f"{node.get('value')}")
    elif label == "PartListing":
        for pt in m.s.out(m.org, node["id"], "LISTS"):
            out.append(pt.get("part_number") or "")
    elif label == "Interface":
        src, dst = m.s.out(m.org, node["id"], "FROM"), m.s.out(m.org, node["id"], "TO")
        if src and dst:
            out.append(f"{src[0]['name']} > {dst[0]['name']}")
    elif label == "Stock":
        pass
    return [x for x in out if x]


def check_confirm(m, op: dict) -> None:
    """A delete-type operation names what it deletes: refused without the
    thing's name as it is now (an id made in this batch needs none)."""
    arg = DELETES.get(op["do"])
    if arg is None:
        return
    target = op["args"].get(arg)
    if isinstance(target, str) and _REF.match(target):
        return  # made in this batch
    node = m.s.node(m.org, str(target or "")) if target else None
    if node is None:
        return  # the action itself says "not found"
    names = _names_of(m, node)
    if op["confirm"] is not None and _norm(op["confirm"]) in {_norm(n) for n in names}:
        return
    shown = next((n for n in names[1:] if n), node["id"])
    raise BatchRefused(f"op {op['index']} ({op['do']}): to delete it, repeat with confirm '{shown}'.")


# ---- running --------------------------------------------------------------------------

def _brief(result) -> Any:
    if isinstance(result, dict):
        return {k: result[k] for k in ("id", "name", "text", "title", "number") if k in result}
    return result


def _undo_for(op: dict, result) -> dict | None:
    """The operation that reverses one that ran: a create's delete (with confirm),
    a retire's restore, a restore's retire. None: not undone automatically."""
    do = op["do"]
    if do in CREATES:
        reverse, arg = CREATES[do]
        if not isinstance(result, dict) or not result.get("id"):
            return None
        name = result.get("name") or result.get("text") or result.get("title") or result.get("part_number")
        if do == "work_orders.open" and result.get("number") is not None:
            name = f"#{result['number']}"
        return {"do": reverse, "args": {arg: result["id"]}, **({"confirm": name} if name else {})}
    if do in RESTORES:
        arg = DELETES[do]
        return {"do": RESTORES[do], "args": {arg: op["args"].get(arg)}}
    if do in RETIRES:
        retire = RETIRES[do]
        arg = DELETES[retire]
        target = op["args"].get(arg)
        name = result.get("name") or result.get("text") or result.get("title") if isinstance(result, dict) else None
        return {"do": retire, "args": {arg: target}, **({"confirm": name} if name else {})}
    if do in LINKS:
        return {"do": LINKS[do], "args": dict(op["args"])}
    return None


def run_pass(ops: list[dict], call, m, on_error: str, dry: bool) -> dict:
    """Run the operations in order through ``call(area, action, args)`` with
    ``m`` as the Maintenance they act on. Returns the per-op results."""
    token_m, token_dry = ACTIVE_M.set(m), DRY.set(dry)
    results: list[dict] = []
    by_ref: dict[str, Any] = {}
    failed = None
    try:
        for op in ops:
            entry = {"index": op["index"], "do": op["do"]}
            if op["ref"]:
                entry["ref"] = op["ref"]
            if failed is not None and on_error != "continue":
                results.append({**entry, "status": "skipped"})
                continue
            at = f"op {op['index']} ({op['do']})"
            try:
                args = resolve(op["args"], by_ref, at)
                result = call(op["area"], op["action"], args)
            except BatchRefused as err:
                text = str(err)
                entry.update(status="failed", error=text if text.startswith("op ") else f"{at}: {text}")
                results.append(entry)
                failed = failed or entry
                continue
            except Exception as err:  # noqa: BLE001 - a refusal, said by the action itself
                entry.update(status="failed", error=f"{at}: {_message(err)}")
                results.append(entry)
                failed = failed or entry
                continue
            if op["ref"]:
                by_ref[op["ref"]] = result
            entry["status"] = "would" if dry else "ok"
            if isinstance(result, dict) and result.get("id"):
                entry["id"] = result["id"]
            entry["result"] = result
            undo = _undo_for({**op, "args": args}, result)  # with its @refs resolved
            if undo:
                entry["undo"] = undo
            results.append(entry)
    finally:
        ACTIVE_M.reset(token_m)
        DRY.reset(token_dry)
    return {"results": results, "failed": failed}


def _message(err: Exception) -> str:
    text = str(err) or type(err).__name__
    return re.sub(r"^Error executing tool [\w.-]+: ", "", text)


def summarise(ops: list[dict], passed: dict, dry: bool, events: int) -> dict:
    results = passed["results"]
    counts = {"creates": 0, "updates": 0, "deletes": 0, "other": 0}
    for op, r in zip(ops, results):
        if r["status"] in ("ok", "would"):
            counts[{"create": "creates", "update": "updates", "delete": "deletes"}.get(classify(op["do"]), "other")] += 1
    undo, irreversible = [], []
    for r in results:
        if r["status"] not in ("ok", "would"):
            continue
        if r.get("undo"):
            undo.append(r["undo"])
        else:
            irreversible.append(r["index"])
    cut = len(ops) > SHOW_FULL_RESULTS_UP_TO
    shown = []
    for r in results:
        row = {k: v for k, v in r.items() if k != "undo"}
        if cut and "result" in row:
            row["result"] = _brief(row["result"])
        shown.append(row)
    failed = passed["failed"]
    return {
        "dry_run": dry, "ok": failed is None,
        "applied": sum(1 for r in results if r["status"] == "ok"),
        "would_apply": sum(1 for r in results if r["status"] == "would"),
        "failed": {k: failed[k] for k in ("index", "do", "error")} if failed else None,
        "skipped": sum(1 for r in results if r["status"] == "skipped"),
        "counts": counts, "events": events, "results": shown,
        # The reverse of what ran, newest first: send it back through maintenance_apply to undo.
        "undo": list(reversed(undo)), "irreversible": irreversible,
        **({"results_cut": "Over 50 operations: each result is cut to its id and name; read records back with "
                           "maintenance_get."} if cut else {}),
    }


# ---- idempotency keys -----------------------------------------------------------------

def _keys(db):
    col = db["maintenance_apply_keys"]
    try:
        col.create_index("created_at", expireAfterSeconds=int(KEY_TTL.total_seconds()))
    except Exception:  # noqa: BLE001 - a simulator without TTL indexes: the check below still works
        pass
    return col


def replay(db, org: str, key: str, operations: list) -> dict | None:
    """The stored answer for a key used in the last 24 hours with the same
    operations; refused for the same key with other operations."""
    if len(key) > MAX_KEY:
        raise BatchRefused(f"idempotency_key is at most {MAX_KEY} characters.")
    doc = _keys(db).find_one({"_id": f"{org}:{key}"})
    if doc is None:
        return None
    if datetime.now(timezone.utc) - doc["created_at"].replace(tzinfo=timezone.utc) > KEY_TTL:
        return None
    if doc["hash"] != _hash(operations):
        raise BatchRefused(f"idempotency_key '{key}' was used for a different batch in the last 24 hours: pick "
                           "another key.")
    return {**doc["result"], "replayed": True}


def remember(db, org: str, key: str, operations: list, result: dict) -> None:
    _keys(db).replace_one({"_id": f"{org}:{key}"}, {
        "_id": f"{org}:{key}", "org": org, "hash": _hash(operations), "result": result,
        "created_at": datetime.now(timezone.utc)}, upsert=True)
