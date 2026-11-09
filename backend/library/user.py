"""A user's own data libraries (Derryn, 9 Nov 2026: "there also needs to be a
way to build a library. Therefore, default a model built in the platform to
not be in a library, but allow it to be added to one").

A library belongs to a workspace like every other saved kind (``owner_id``:
the user, or a team principal) and counts as one saved item toward the Free
plan's storage cap, whatever it holds. Its records are snapshots of saved
non-repairable life models, in the library's own record shape
(:mod:`backend.library.schema`, kind ``life``): the distribution, its
parameters with their bounds, the unit, the sample sizes and how it was
fitted, taken when the model is added. The record keeps ``model_id`` as a
link, so a later refit never changes the library quietly.

Two collections: ``libraries`` (name, description, notes) and
``library_records`` (one document per record, ``library_id`` and
``owner_id`` on each). Nothing here touches the published sources: they are
read-only data files (:mod:`backend.library.service`), and a user library is
merged beside them by :func:`mine`, which the search, the record reads and the
sources list take.
"""

from __future__ import annotations

import math
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from backend.library import schema
from backend.units import canonical_unit

COLLECTION = "libraries"
RECORDS = "library_records"

MAX_NAME = 120
MAX_DESCRIPTION = 300
MAX_NOTES = 4000
MAX_LABEL = 200
MAX_RECORDS = 500

#: The saved model kinds a record can be made from: parametric non-repairable
#: life models (the Fit dialog's Bayesian ones save as these too).
LIFE_FAMILIES = ("weibull", "exponential", "lognormal", "normal", "gamma")
#: How a saved model's ``results.method`` reads in a record.
METHODS = {"bayesian_update": "bayes", "library": "library", "params": "params"}
#: The level of a saved model's parameter intervals: a Bayesian update stores
#: ``credible_level``; a maximum-likelihood fit's are 95% Wald intervals.
MLE_LEVEL = 0.95


class LibraryError(ValueError):
    """A refused request, said in words."""


class LibraryNotFound(KeyError):
    """An unknown, hidden or not-owned library or record id."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _text(value, what: str, limit: int, required: bool = False) -> str:
    text = " ".join(str(value or "").split()) if not isinstance(value, str) or "\n" not in value else str(value).strip()
    if required and not text:
        raise LibraryError(f"The library needs {what}.")
    if len(text) > limit:
        raise LibraryError(f"{what[0].upper()}{what[1:]} is too long: at most {limit} characters.")
    return text


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-") or "all"


def _owners(owner) -> list[str]:
    return [owner] if isinstance(owner, str) else list(owner or [])


# ---- libraries -------------------------------------------------------------------------------

def _iso(value) -> Optional[str]:
    """A stored time as text, in UTC (the store keeps milliseconds and drops the zone)."""
    if not isinstance(value, datetime):
        return value
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def brief(lib: dict, records: int = 0) -> dict:
    """A library as the lists show it."""
    return {
        "id": lib["_id"], "name": lib["name"], "description": lib.get("description") or "",
        "notes": lib.get("notes") or "", "owner_id": lib.get("owner_id"), "records": records,
        "created_at": _iso(lib.get("created_at")), "updated_at": _iso(lib.get("updated_at")),
    }


def create(db, owner_id: str, name: str, description: str = "", notes: str = "") -> dict:
    """A new, empty library in the owner's workspace."""
    doc = {
        "_id": uuid.uuid4().hex, "owner_id": owner_id,
        "name": _text(name, "a name", MAX_NAME, required=True),
        "description": _text(description, "the description", MAX_DESCRIPTION),
        "notes": _text(notes, "the notes", MAX_NOTES),
        "created_at": _now(), "updated_at": _now(),
    }
    db[COLLECTION].insert_one(doc)
    return brief(db[COLLECTION].find_one({"_id": doc["_id"]}) or doc)


def list_libraries(db, owners, hidden=frozenset()) -> list[dict]:
    """The libraries the owners hold, newest first, each with its record count."""
    rows = [d for d in db[COLLECTION].find({"owner_id": {"$in": _owners(owners)}}).sort("created_at", -1)
            if d["_id"] not in hidden]
    counts = _record_counts(db, [d["_id"] for d in rows])
    return [brief(d, counts.get(d["_id"], 0)) for d in rows]


def _record_counts(db, library_ids: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    if not library_ids:
        return out
    for d in db[RECORDS].find({"library_id": {"$in": library_ids}}, {"library_id": 1}):
        out[d["library_id"]] = out.get(d["library_id"], 0) + 1
    return out


def get_library(db, library_id: str, owners=None) -> Optional[dict]:
    """One library's document (raw), or None when it isn't theirs."""
    query: dict = {"_id": str(library_id or "")}
    if owners is not None:
        query["owner_id"] = {"$in": _owners(owners)}
    return db[COLLECTION].find_one(query)


def update(db, library_id: str, owner_id: str, name=None, description=None, notes=None) -> dict:
    """Rename a library, or change its description or notes."""
    doc = get_library(db, library_id, owner_id)
    if doc is None or doc.get("owner_id") != owner_id:
        raise LibraryNotFound(library_id)
    changes: dict = {}
    if name is not None:
        changes["name"] = _text(name, "a name", MAX_NAME, required=True)
    if description is not None:
        changes["description"] = _text(description, "the description", MAX_DESCRIPTION)
    if notes is not None:
        changes["notes"] = _text(notes, "the notes", MAX_NOTES)
    if not changes:
        raise LibraryError("Nothing to change: give a name, a description or notes.")
    changes["updated_at"] = _now()
    db[COLLECTION].update_one({"_id": doc["_id"]}, {"$set": changes})
    return brief(db[COLLECTION].find_one({"_id": doc["_id"]}) or {**doc, **changes},
                 _record_counts(db, [doc["_id"]]).get(doc["_id"], 0))


def delete(db, library_id: str, owner_id: str) -> int:
    """Delete a library and its records (the models they came from stay).
    Returns how many records went with it."""
    doc = get_library(db, library_id, owner_id)
    if doc is None or doc.get("owner_id") != owner_id:
        raise LibraryNotFound(library_id)
    removed = db[RECORDS].delete_many({"library_id": doc["_id"]}).deleted_count
    db[COLLECTION].delete_one({"_id": doc["_id"]})
    return int(removed)


# ---- records ---------------------------------------------------------------------------------

def why_not_model(model) -> Optional[str]:
    """Why a saved model can't be a library record, in words; None when it can.
    Records hold parametric non-repairable life models (Weibull, exponential,
    lognormal, normal, gamma; a Bayesian update of one too), with the plain
    parameters of the family: nothing with an offset, a mixture, a fixed
    fraction that never fails, or covariates."""
    if model is None:
        return "That model wasn't found."
    r = model.results or {}
    if model.kind != "distribution":
        return (f"“{model.name}” is a {r.get('distribution') or model.kind} model: a library record holds a "
                "parametric life model (Weibull, exponential, lognormal, normal or gamma).")
    family = r.get("distribution_id") or model.distribution_id
    if family not in LIFE_FAMILIES:
        return (f"“{model.name}” is a {r.get('distribution') or family} model: a library record holds a Weibull, "
                "exponential, lognormal, normal or gamma life model.")
    names = [p.get("name") for p in r.get("params") or []]
    if sorted(names) != sorted(schema.FAMILIES[family]):
        return (f"“{model.name}” has more than a {family}'s own parameters ({', '.join(map(str, names))}): a "
                "record holds the plain family (no offset, mixture, fixed fraction or covariates).")
    if any(not isinstance(p.get("value"), (int, float)) or not math.isfinite(p["value"]) for p in r.get("params") or []):
        return f"“{model.name}” has no finite parameter values to keep."
    return None


def snapshot(model, label: str, equipment_type: str, failure_mode: str, notes: str, library_id: str,
             owner_id: str) -> dict:
    """A saved model as a library record: the distribution and its parameters
    with their bounds, the unit, the sample sizes and how it was fitted, taken
    now. ``model_id`` links back; a later refit doesn't change the record."""
    r = model.results or {}
    family = r.get("distribution_id") or model.distribution_id
    level = r.get("credible_level") if r.get("method") == "bayesian_update" else (
        MLE_LEVEL if any(p.get("ci") for p in r.get("params") or []) else None)
    params = []
    for p in r.get("params") or []:
        entry: dict = {"name": p["name"], "value": float(p["value"])}
        ci = p.get("ci")
        if (isinstance(ci, (list, tuple)) and len(ci) == 2
                and all(isinstance(v, (int, float)) and math.isfinite(v) for v in ci)):
            entry["ci"] = [float(ci[0]), float(ci[1])]
        params.append(entry)
    values = {p["name"]: p["value"] for p in params}
    unit = canonical_unit(r.get("unit") or (model.spec or {}).get("unit") or "")
    split = r.get("split") or {}
    method = METHODS.get(r.get("method"), "mle" if model.dataset_id else "params")
    mode = _text(failure_mode, "the failure mode", MAX_LABEL)
    name = _text(label, "a label", MAX_LABEL, required=True)
    rid = uuid.uuid4().hex
    return {
        "_id": f"{library_id}:{rid}", "id": f"{library_id}:{rid}", "library_id": library_id, "owner_id": owner_id,
        "source": library_id, "version": 1, "schema": schema.SCHEMA_VERSION,
        "name": name, "label": f"{name}: {mode}" if mode else name,
        "equipment_type": equipment_type if equipment_type in schema.EQUIPMENT_TYPES else "other",
        "kind": "life", "basis": "fitted",
        "failure_mode": {"code": _slug(mode), "name": mode or "All failures"},
        "distribution": {"family": family, "params": params, **({"level": level} if level else {})},
        "units": {"value": unit or "units", "as_given": unit or ""},
        "summary": {k: v for k, v in schema.life_summary(family, values).items() if v is not None},
        "evidence": {"n": r.get("n"), "failures": split.get("failed"), "suspensions": split.get("running"),
                     "method": method},
        "model": {"id": model.id, "name": model.name, "distribution": r.get("distribution") or family,
                  "created_at": model.created_at.isoformat() if isinstance(model.created_at, datetime) else None},
        "notes": _text(notes, "the notes", MAX_NOTES),
        "source_text": _text(notes, "the notes", MAX_NOTES),
        "created_at": _now(),
    }


def add_model(db, library_id: str, owner_id: str, model, label=None, equipment_type="other", failure_mode="",
              notes="") -> dict:
    """Add a saved model to a library as a record (a snapshot of it now)."""
    lib = get_library(db, library_id, owner_id)
    if lib is None or lib.get("owner_id") != owner_id:
        raise LibraryNotFound(library_id)
    words = why_not_model(model)
    if words:
        raise LibraryError(words)
    if db[RECORDS].count_documents({"library_id": lib["_id"]}) >= MAX_RECORDS:
        raise LibraryError(f"“{lib['name']}” already holds {MAX_RECORDS} records, the most a library takes.")
    rec = snapshot(model, label or model.name, equipment_type or "other", failure_mode or "", notes or "",
                   lib["_id"], owner_id)
    db[RECORDS].insert_one(dict(rec))
    db[COLLECTION].update_one({"_id": lib["_id"]}, {"$set": {"updated_at": _now()}})
    return record_doc(db[RECORDS].find_one({"_id": rec["_id"]}) or rec)


def remove_record(db, record_id: str, owner_id: str) -> dict:
    """Take a record out of its library (the model it came from stays)."""
    doc = db[RECORDS].find_one({"_id": str(record_id or ""), "owner_id": owner_id})
    if doc is None:
        raise LibraryNotFound(record_id)
    db[RECORDS].delete_one({"_id": doc["_id"]})
    db[COLLECTION].update_one({"_id": doc["library_id"]}, {"$set": {"updated_at": _now()}})
    return {"removed": True, "record_id": doc["_id"], "library_id": doc["library_id"]}


def record_doc(doc: dict) -> dict:
    """A stored record as the library's record shape (no Mongo id, dates as text)."""
    out = {k: v for k, v in doc.items() if k != "_id"}
    out["created_at"] = _iso(out.get("created_at"))
    return out


def records_of(db, library_id: str) -> list[dict]:
    return [record_doc(d) for d in db[RECORDS].find({"library_id": library_id}).sort("created_at", -1)]


# ---- merged beside the published sources ----------------------------------------------------

def source_of(lib: dict, records: list[dict]) -> dict:
    """A user library in the sources list's shape, marked ``mine``."""
    counts: dict[str, dict[str, int]] = {"kind": {}, "equipment_type": {}}
    for r in records:
        for key in counts:
            counts[key][r[key]] = counts[key].get(r[key], 0) + 1
    b = brief(lib, len(records))
    return {
        **b, "short_name": lib["name"], "mine": True, "basis": "fitted", "licence": None,
        "publisher": None, "title": None, "report": None, "edition": None, "year": None, "url": None, "home": None,
        "caveats": [], "retrieved": None, "skipped": 0, "data_version": None,
        "components": len({r["name"] for r in records}),
        "kinds": dict(sorted(counts["kind"].items())), "equipment_types": dict(sorted(counts["equipment_type"].items())),
    }


def mine(db, owners, hidden=frozenset(), can_write=None) -> dict[str, Any]:
    """The owners' libraries and records as the library service merges them:
    ``{"sources": {id: source}, "records": [record, ...]}``. ``can_write``:
    a function of an owner id saying whether the caller may change it (the
    sources carry ``read_only``)."""
    libs = [d for d in db[COLLECTION].find({"owner_id": {"$in": _owners(owners)}}).sort("created_at", -1)
            if d["_id"] not in hidden]
    if not libs:
        return {"sources": {}, "records": []}
    by_lib: dict[str, list[dict]] = {d["_id"]: [] for d in libs}
    for d in db[RECORDS].find({"library_id": {"$in": list(by_lib)}}).sort("created_at", -1):
        by_lib[d["library_id"]].append(record_doc(d))
    sources = {}
    records: list[dict] = []
    for lib in libs:
        src = source_of(lib, by_lib[lib["_id"]])
        src["read_only"] = not can_write(lib.get("owner_id")) if can_write else False
        sources[lib["_id"]] = src
        records.extend(by_lib[lib["_id"]])
    return {"sources": sources, "records": records}


def model_link(db, rec: dict, owners) -> Optional[dict]:
    """The model a record came from, if it still resolves for the reader:
    ``{id, name, exists}``."""
    m = rec.get("model") or {}
    if not m.get("id"):
        return None
    doc = db.models.find_one({"_id": m["id"], "owner_id": {"$in": _owners(owners)}}, {"name": 1})
    return {"id": m["id"], "name": doc.get("name") if doc else m.get("name"), "exists": doc is not None}
