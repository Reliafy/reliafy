"""Libraries: shareable collections of datasets and models (Derryn, 13 Nov 2026).

A library (the ``libraries`` collection, :mod:`backend.library.user` made the
first ones) belongs to one workspace (``owner_id``) and holds entries (the
``library_records`` collection): each a **snapshot** of a dataset (its rows,
its measurements part and its reading) or of a saved model (the whole
document), taken when it was added. Later edits in the workspace don't change
the library; the owner can take a new snapshot ("Update from the original"),
which bumps the entry's ``version``. Nothing is ever added automatically.

A library is one of three things:

- **private**: its owner's workspace only;
- **workspaces**: also read by the workspaces listed in ``shared_with``
  (principals: a user id for a personal workspace, ``team:<id>`` for a team);
- **public**: read by anyone, signed out included; used (copied) by anyone
  signed in. Making it public takes a licence that allows republishing, a
  source or citation, and the owner's word that they have the right to
  publish it (the data-library rule: only public-domain, open or CC BY data
  is republished, each cited).

Only the owner changes a library. Using an entry copies it into the user's
own workspace (a new dataset or model, counted against their caps) with
``from_library`` saying where it came from. Datasets stay atomic: a library
groups them, never merges or links them; a model entry only *shows* the
dataset it was fitted on when that dataset's snapshot is in the same library.

The published handbooks (:mod:`backend.library.service`) are listed beside
the user libraries as built-in, public, read-only libraries.
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from backend.db import from_doc, to_doc
from backend.library import service as published
from backend.library import user as user_lib

COLLECTION = user_lib.COLLECTION
RECORDS = user_lib.RECORDS

VISIBILITIES = ("private", "workspaces", "public")
LICENCES = {
    "public-domain": "Public domain",
    "cc0": "CC0 1.0",
    "cc-by-4.0": "CC BY 4.0",
    "own-cc-by-4.0": "Our own data, published under CC BY 4.0",
}
MAX_SOURCE = 300
MAX_CITATION = 1000
MAX_WORKSPACES = 50
MAX_ENTRIES = user_lib.MAX_RECORDS
PREVIEW_ROWS = 50
HEADLINE_CONFIDENCE = 0.90

#: The model collections an entry can be taken from, what the app calls each and its page.
MODEL_KINDS = {
    "models": ("Non-repairable", "/models/m/"),
    "recurrent_models": ("Repairable", "/models/recurrent/"),
    "alt_models": ("Accelerated life", "/models/alt/"),
}

LibraryError = user_lib.LibraryError
LibraryNotFound = user_lib.LibraryNotFound


class NotAllowed(PermissionError):
    """The caller may read the library but not change it."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


_iso = user_lib._iso
_text = user_lib._text


def builtin_ids() -> set[str]:
    return set(published._library()["sources"])


# ---- who sees what -----------------------------------------------------------------------------

def visible_query(principals) -> dict:
    """The libraries a reader with these principals sees (None: signed out, public only)."""
    if not principals:
        return {"visibility": "public"}
    principals = list(principals)
    return {"$or": [{"owner_id": {"$in": principals}},
                    {"visibility": "workspaces", "shared_with": {"$in": principals}},
                    {"visibility": "public"}]}


def relation(lib: dict, write_owner: Optional[str], principals) -> str:
    """yours (the current workspace owns it), shared (another of your workspaces owns it, or it's shared
    with one of them) or public."""
    principals = list(principals or [])
    if write_owner and lib.get("owner_id") == write_owner:
        return "yours"
    if lib.get("owner_id") in principals:
        return "shared"
    if lib.get("visibility") == "workspaces" and set(lib.get("shared_with") or []) & set(principals):
        return "shared"
    return "public"


def get_visible(db, library_id: str, principals) -> Optional[dict]:
    q = visible_query(principals)
    return db[COLLECTION].find_one({"$and": [{"_id": str(library_id or "")}, q]})


def visibility_of(lib: dict) -> str:
    v = lib.get("visibility")
    return v if v in VISIBILITIES else "private"


# ---- the shapes --------------------------------------------------------------------------------

def _counts(db, ids: list[str]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {i: {"data": 0, "model": 0, "total": 0} for i in ids}
    if not ids:
        return out
    for d in db[RECORDS].find({"library_id": {"$in": ids}}, {"library_id": 1, "entry_type": 1}):
        c = out.setdefault(d["library_id"], {"data": 0, "model": 0, "total": 0})
        c["data" if d.get("entry_type") == "data" else "model"] += 1
        c["total"] += 1
    return out


def _licence(lib: dict) -> Optional[dict]:
    lid = lib.get("licence")
    return {"id": lid, "name": LICENCES[lid]} if lid in LICENCES else None


def card(lib: dict, counts: dict, rel: str, can_edit: bool) -> dict:
    """A user library as the lists show it."""
    return {
        "id": lib["_id"], "name": lib.get("name") or "", "description": lib.get("description") or "",
        "builtin": False, "visibility": visibility_of(lib), "relation": rel,
        "counts": counts or {"data": 0, "model": 0, "total": 0},
        "licence": _licence(lib), "source": lib.get("source") or "", "citation": lib.get("citation") or "",
        "updated_at": _iso(lib.get("updated_at")), "can_edit": bool(can_edit), "url": f"/libraries/{lib['_id']}",
    }


def builtin_card(src: dict) -> dict:
    """A published handbook as a built-in, public, read-only library."""
    cite = ", ".join(str(x) for x in (src.get("title"), src.get("report"), src.get("year")) if x)
    lic = src.get("licence") or {}
    return {
        "id": src["id"], "name": src.get("short_name") or src.get("name") or src["id"],
        "description": src.get("description") or "", "builtin": True, "visibility": "public", "relation": "public",
        "counts": {"data": 0, "model": int(src.get("records") or 0), "total": int(src.get("records") or 0)},
        "licence": {"id": lic.get("id"), "name": lic.get("name")} if lic else None,
        "source": src.get("publisher") or "", "citation": cite, "updated_at": src.get("retrieved"),
        "can_edit": False, "url": f"/libraries/{src['id']}",
    }


def builtin_cards() -> list[dict]:
    return [builtin_card(s) for s in published._library()["sources"].values()]


def list_cards(db, principals, write_owner: Optional[str], can_write=None, hidden=frozenset(),
               limit: int = 300) -> list[dict]:
    """Every library the reader sees: theirs first (newest first), then shared, then public (others',
    then the built-in handbooks)."""
    docs = [d for d in db[COLLECTION].find(visible_query(principals)).sort("updated_at", -1).limit(limit)
            if d["_id"] not in hidden]
    counts = _counts(db, [d["_id"] for d in docs])
    order = {"yours": 0, "shared": 1, "public": 2}
    rows = []
    for d in docs:
        rel = relation(d, write_owner, principals)
        rows.append(card(d, counts.get(d["_id"]), rel, bool(can_write and can_write(d.get("owner_id")))))
    rows.sort(key=lambda r: order[r["relation"]])
    return rows + builtin_cards()


# ---- entries -----------------------------------------------------------------------------------

def _entry_type(doc: dict) -> str:
    return "data" if doc.get("entry_type") == "data" else "model"


def _origin_url(doc: dict) -> Optional[str]:
    o = doc.get("origin") or {}
    if not o.get("id"):
        m = doc.get("model") or {}
        return f"/models/m/{m['id']}" if m.get("id") else None
    if o.get("collection") == "datasets":
        return f"/data/{o['id']}"
    return MODEL_KINDS.get(o.get("collection"), ("", "/models/m/"))[1] + o["id"]


def _origin_id(doc: dict) -> Optional[str]:
    return (doc.get("origin") or {}).get("id") or (doc.get("model") or {}).get("id")


def _origin_collection(doc: dict) -> str:
    return (doc.get("origin") or {}).get("collection") or ("datasets" if _entry_type(doc) == "data" else "models")


def entry_out(doc: dict, by_origin: dict[str, dict], owner_view: bool, db=None, principals=None) -> dict:
    """An entry as the library page lists it. ``by_origin``: the library's data entries by the id of the
    dataset each was taken from (for "fitted on ↑")."""
    kind = _entry_type(doc)
    out: dict[str, Any] = {
        "id": doc.get("id") or doc["_id"], "library_id": doc["library_id"], "type": kind,
        "name": doc.get("entry_name") or doc.get("name") or "",
        "version": int(doc.get("version") or 1),
        "added_at": _iso(doc.get("created_at")), "updated_at": _iso(doc.get("updated_at") or doc.get("created_at")),
        "tags": list(doc.get("tags") or []),
        "source": doc.get("entry_source") or "",
    }
    if kind == "data":
        d = doc.get("data") or {}
        out["data"] = {"n_rows": int(d.get("n_rows") or 0), "columns": [c.get("name") for c in d.get("columns") or []],
                       "reading_summary": d.get("reading_summary") or "",
                       "has_measurements": bool(d.get("measurements"))}
    else:
        snap = doc.get("snapshot") or {}
        coll = snap.get("collection") or "models"
        mdoc = snap.get("doc") or {}
        results = mdoc.get("results") or {}
        ds_id = mdoc.get("dataset_id") or ""
        fitted = by_origin.get(ds_id) if ds_id else None
        legacy = doc.get("distribution") or {}
        out["model"] = {
            "collection": coll, "kind_label": MODEL_KINDS.get(coll, ("Non-repairable",))[0],
            "distribution": results.get("distribution") or mdoc.get("distribution_id") or legacy.get("family") or "",
            "unit": results.get("unit") or (mdoc.get("spec") or {}).get("unit") or (doc.get("units") or {}).get("value") or "",
            "headline": doc.get("headline"),
            "fitted_on": {"entry_id": fitted.get("id") or fitted["_id"], "name": fitted.get("entry_name") or fitted.get("name")}
            if fitted else None,
            "basis_text": doc.get("basis_text") or basis_text(coll, mdoc, doc.get("entry_source") or ""),
            "has_dataset": bool(fitted),
            "copyable": bool(snap.get("doc")),
        }
    if owner_view:
        oid = _origin_id(doc)
        exists = False
        if oid and db is not None:
            exists = db[_origin_collection(doc)].find_one(
                {"_id": oid, "owner_id": {"$in": list(principals or [])}}, {"_id": 1}) is not None
        out["origin"] = {"id": oid, "exists": exists, "url": _origin_url(doc)} if oid else None
    return out


def entries_of(db, lib: dict, owner_view: bool, principals=None) -> list[dict]:
    docs = list(db[RECORDS].find({"library_id": lib["_id"]}).sort("created_at", 1))
    by_origin = {_origin_id(d): d for d in docs if _entry_type(d) == "data" and _origin_id(d)}
    return [entry_out(d, by_origin, owner_view, db, principals) for d in docs]


def library_out(db, lib: dict, rel: str, can_edit: bool, principals=None) -> dict:
    out = card(lib, _counts(db, [lib["_id"]]).get(lib["_id"]), rel, can_edit)
    out.update({
        "notes": lib.get("notes") or "", "rights_confirmed": bool(lib.get("rights_confirmed")),
        "shared_with": [display_workspace(w) for w in lib.get("shared_with") or []] if can_edit else [],
        "indexable": visibility_of(lib) == "public",
        "entries": entries_of(db, lib, can_edit, principals),
    })
    return out


def builtin_out(library_id: str) -> Optional[dict]:
    src = published._library()["sources"].get(library_id)
    if src is None:
        return None
    return {**builtin_card(src), "notes": "", "rights_confirmed": True, "shared_with": [], "indexable": True,
            "entries": []}


def entry_detail(db, lib: dict, entry_id: str, owner_view: bool, principals=None) -> dict:
    doc = db[RECORDS].find_one({"_id": str(entry_id or ""), "library_id": lib["_id"]})
    if doc is None:
        raise LibraryNotFound(entry_id)
    docs = list(db[RECORDS].find({"library_id": lib["_id"], "entry_type": "data"}))
    by_origin = {_origin_id(d): d for d in docs if _origin_id(d)}
    out = entry_out(doc, by_origin, owner_view, db, principals)
    if out["type"] == "data":
        d = doc.get("data") or {}
        out["data"]["reading"] = d.get("reading")
        out["data"]["preview"] = _preview(d.get("blob") or b"")
    else:
        mdoc = (doc.get("snapshot") or {}).get("doc") or {}
        results = mdoc.get("results") or {}
        params = results.get("params") or (doc.get("distribution") or {}).get("params") or []
        out["model"]["params"] = [{k: p.get(k) for k in ("name", "value", "ci") if p.get(k) is not None}
                                  for p in params if isinstance(p, dict)]
        out["model"]["n"] = results.get("n")
        out["model"]["split"] = results.get("split")
    return out


def _preview(blob: bytes) -> dict:
    from backend.services import datasets as datasets_service

    try:
        p = datasets_service._preview(bytes(blob), PREVIEW_ROWS)
        return {"columns": p.get("columns") or [], "rows": p.get("preview") or []}
    except Exception:  # noqa: BLE001 - a preview never fails the read
        return {"columns": [], "rows": []}


def all_entries(db, principals, write_owner, entry_type: str, query: str = "", hidden=frozenset(),
                limit: int = 500) -> list[dict]:
    """Every entry of one type in the user libraries the reader sees (the Data and Models views)."""
    libs = {d["_id"]: d for d in db[COLLECTION].find(visible_query(principals)) if d["_id"] not in hidden}
    if not libs:
        return []
    q = {"library_id": {"$in": list(libs)}}
    q["entry_type"] = "data" if entry_type == "data" else {"$ne": "data"}
    docs = list(db[RECORDS].find(q).sort("created_at", -1).limit(limit))
    data_docs = list(db[RECORDS].find({"library_id": {"$in": list(libs)}, "entry_type": "data"}))
    by_lib_origin: dict[str, dict] = {}
    for d in data_docs:
        by_lib_origin.setdefault(d["library_id"], {})[_origin_id(d)] = d
    words = [w for w in str(query or "").lower().split() if w]
    out = []
    for d in docs:
        lib = libs[d["library_id"]]
        e = entry_out(d, by_lib_origin.get(d["library_id"], {}), False)
        hay = " ".join([e["name"], lib.get("name") or "", " ".join(e["tags"]),
                        (e.get("data") or {}).get("reading_summary", ""), (e.get("model") or {}).get("distribution", ""),
                        (e.get("model") or {}).get("basis_text", "")]).lower()
        if words and not all(w in hay for w in words):
            continue
        e["library"] = {"id": lib["_id"], "name": lib.get("name") or "", "builtin": False,
                        "relation": relation(lib, write_owner, principals)}
        out.append(e)
    return out


# ---- making and changing a library -------------------------------------------------------------

def create(db, owner_id: str, name: str, description: str = "", notes: str = "", source: str = "",
           citation: str = "") -> dict:
    """A new, private, empty library in the owner's workspace."""
    lib = user_lib.create(db, owner_id, name, description, notes)
    changes = {"visibility": "private", "shared_with": [],
               "source": _text(source, "the source", MAX_SOURCE), "citation": _text(citation, "the citation", MAX_CITATION)}
    db[COLLECTION].update_one({"_id": lib["id"]}, {"$set": changes})
    return db[COLLECTION].find_one({"_id": lib["id"]})


def update(db, lib: dict, name=None, description=None, notes=None, source=None, citation=None) -> dict:
    changes: dict = {}
    if name is not None:
        changes["name"] = _text(name, "a name", user_lib.MAX_NAME, required=True)
    if description is not None:
        changes["description"] = _text(description, "the description", user_lib.MAX_DESCRIPTION)
    if notes is not None:
        changes["notes"] = _text(notes, "the notes", user_lib.MAX_NOTES)
    if source is not None:
        changes["source"] = _text(source, "the source", MAX_SOURCE)
    if citation is not None:
        changes["citation"] = _text(citation, "the citation", MAX_CITATION)
    if not changes:
        raise LibraryError("Nothing to change: give a name, a description, notes, a source or a citation.")
    if visibility_of(lib) == "public" and not (changes.get("citation", lib.get("citation")) or "").strip():
        raise LibraryError("A public library needs its source or citation: make it private first to clear it.")
    changes["updated_at"] = _now()
    db[COLLECTION].update_one({"_id": lib["_id"]}, {"$set": changes})
    return db[COLLECTION].find_one({"_id": lib["_id"]})


def workspace_principal(db, raw: str) -> str:
    """A workspace ID as typed (a team's id, ``team:<id>``, or a personal workspace's id) as the principal
    a library is shared with. LibraryError when no workspace has it."""
    wid = str(raw or "").strip()
    if not wid:
        raise LibraryError("A workspace ID is empty.")
    bare = wid[len("team:"):] if wid.startswith("team:") else wid
    if db.teams.find_one({"_id": bare}, {"_id": 1}) is not None:
        return f"team:{bare}"
    if not wid.startswith("team:") and db.users.find_one({"_id": wid}, {"_id": 1}) is not None:
        return wid
    raise LibraryError(f"No workspace has the ID “{wid}”. Ask its owner for the ID shown on their Libraries "
                       "sharing panel.")


def display_workspace(principal: str) -> str:
    return principal[len("team:"):] if str(principal).startswith("team:") else str(principal)


def workspace_id_of(write_owner: Optional[str]) -> Optional[str]:
    """The ID the caller's current workspace is shared with by (what the sharing panel shows them)."""
    return display_workspace(write_owner) if write_owner else None


def set_visibility(db, lib: dict, visibility: str, workspaces=None, licence=None, source=None, citation=None,
                   rights_confirmed=None) -> dict:
    """Private, shared with workspaces (their IDs) or public (a licence, a source or citation, and the
    owner's word that they may publish it)."""
    if visibility not in VISIBILITIES:
        raise LibraryError("Visibility is private, workspaces or public.")
    changes: dict = {"visibility": visibility}
    if source is not None:
        changes["source"] = _text(source, "the source", MAX_SOURCE)
    if citation is not None:
        changes["citation"] = _text(citation, "the citation", MAX_CITATION)
    if licence is not None:
        if licence not in LICENCES and licence != "":
            raise LibraryError("The licence is one of: " + ", ".join(f"{k} ({v})" for k, v in LICENCES.items()) + ".")
        changes["licence"] = licence or None
    if workspaces is not None:
        given = [w for w in workspaces if str(w or "").strip()]
        if len(given) > MAX_WORKSPACES:
            raise LibraryError(f"At most {MAX_WORKSPACES} workspaces.")
        principals = []
        for w in given:
            p = workspace_principal(db, w)
            if p == lib.get("owner_id"):
                continue  # its own workspace always sees it
            if p not in principals:
                principals.append(p)
        changes["shared_with"] = principals
    if visibility == "workspaces" and not changes.get("shared_with", lib.get("shared_with")):
        raise LibraryError("Give at least one workspace ID to share the library with.")
    if visibility == "public":
        missing = []
        lic = changes.get("licence", lib.get("licence"))
        if lic not in LICENCES:
            missing.append("a licence (Public domain, CC0, CC BY 4.0, or your own data under CC BY 4.0)")
        if not (changes.get("citation", lib.get("citation")) or changes.get("source", lib.get("source")) or "").strip():
            missing.append("its source or citation")
        if rights_confirmed is not True:
            missing.append("your confirmation that you have the right to publish it")
        if missing:
            raise LibraryError("To make the library public, give " + _and(missing) + ". Only public-domain, open or "
                               "CC BY data may be published, each cited.")
        changes["rights_confirmed"] = True
        changes["published_at"] = _now()
    elif rights_confirmed is not None:
        changes["rights_confirmed"] = bool(rights_confirmed)
    changes["updated_at"] = _now()
    db[COLLECTION].update_one({"_id": lib["_id"]}, {"$set": changes})
    return db[COLLECTION].find_one({"_id": lib["_id"]})


def _and(words: list[str]) -> str:
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]


# ---- snapshots ---------------------------------------------------------------------------------

def basis_text(collection: str, mdoc: dict, entry_source: str = "") -> str:
    """Where a model came from, in plain words (never a gap: a model needn't be fitted to data)."""
    if entry_source:
        return f"From a published source: {entry_source}"
    r = mdoc.get("results") or {}
    spec = mdoc.get("spec") or {}
    method = r.get("method") or spec.get("method")
    if method == "library":
        src = (r.get("library") or {}).get("source")
        return f"From {src}" if src else "From a published library"
    if method == "bayesian_update":
        return "A Bayesian update of a prior with data" if mdoc.get("dataset_id") else "A Bayesian update of a prior"
    if r.get("params_only") or spec.get("params_only") or method == "params":
        return "From parameters"
    if r.get("per_demand") or mdoc.get("kind") == "per_demand":
        return "From counts of demands and failures"
    split = r.get("split") or {}
    if mdoc.get("dataset_id"):
        if split.get("failed") is not None:
            return f"Fitted to data ({split.get('failed')} failed, {split.get('running') or 0} still running)"
        if r.get("n"):
            return f"Fitted to data ({r['n']} rows)"
        return "Fitted to data"
    return "From parameters"


def headline_of(db, model_id: str, owners, unit: str = "") -> Optional[dict]:
    """A non-repairable model's B10 with its 90% one-sided lower bound (None when it has no B10)."""
    from backend.services import models as models_service

    try:
        life = models_service.life(db, model_id, {"confidence": HEADLINE_CONFIDENCE}, owners)
    except Exception:  # noqa: BLE001 - a model with no quantile has no headline
        return None
    b10 = next((b for b in life.get("b_lives") or [] if b.get("label") == "B10"), None)
    if not b10 or not _finite(b10.get("value")):
        return None
    lower = b10.get("lower") if _finite(b10.get("lower")) else None
    u = f" {unit.lower()}" if unit else ""
    text = f"B10 {_sig(b10['value'])}{u}"
    text += f" (90% lower bound {_sig(lower)}{u})" if lower is not None else " (no confidence bound)"
    return {"label": "B10", "value": float(b10["value"]), "lower": float(lower) if lower is not None else None,
            "confidence": HEADLINE_CONFIDENCE, "bound": "lower", "unit": unit, "text": text}


def _headline_from_summary(snap: dict) -> None:
    """A life model with no bounded B10 (from parameters, say): its B10 from the parameters, no bound."""
    b10 = (snap.get("summary") or {}).get("b10")
    if snap.get("headline") is not None or not _finite(b10):
        return
    unit = (snap.get("units") or {}).get("value") or ""
    u = f" {unit.lower()}" if unit and unit != "units" else ""
    snap["headline"] = {"label": "B10", "value": float(b10), "lower": None, "confidence": HEADLINE_CONFIDENCE,
                        "bound": "lower", "unit": unit, "text": f"B10 {_sig(b10)}{u} (no confidence bound)"}


def _finite(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _sig(v: float) -> str:
    """About 4 significant figures, with thousands separators."""
    if v == 0:
        return "0"
    if abs(v) >= 1000:
        return f"{round(v, 3 - int(math.floor(math.log10(abs(v))))):,.0f}"
    return f"{v:.4g}"


def _dataset_snapshot(db, dataset, owners, hidden=frozenset()) -> dict:
    from backend.services import dataset_reading
    from backend.services import datasets as datasets_service

    try:
        reading, _source = dataset_reading.for_dataset_db(db, dataset, owners, hidden)
    except Exception:  # noqa: BLE001 - a dataset whose reading can't be told keeps none
        reading = dataset.reading
    try:
        tags = list(datasets_service.dataset_tags(dataset).get("tags") or [])
    except Exception:  # noqa: BLE001
        tags = []
    part = dataset.measurements
    return {
        "data": {"name": dataset.name, "n_rows": dataset.n_rows, "columns": dataset.columns, "checksum": dataset.checksum,
                 "blob": bytes(dataset.data), "reading": reading,
                 "reading_summary": dataset_reading.summary(reading or {}),
                 "notes": dataset.notes,
                 "measurements": part.model_dump() if part is not None else None},
        "tags": tags, "entry_name": dataset.name,
    }


def _model_snapshot(db, collection: str, mdoc: dict, owners, entry_source: str = "") -> dict:
    kept = {k: v for k, v in mdoc.items() if k not in ("_id", "owner_id", "updated_by", "from_library")}
    results = kept.get("results") or {}
    unit = results.get("unit") or (kept.get("spec") or {}).get("unit") or ""
    headline = headline_of(db, mdoc["_id"], owners, unit) if collection == "models" else None
    label = MODEL_KINDS[collection][0]
    tags = [label]
    return {"snapshot": {"collection": collection, "doc": kept}, "headline": headline, "tags": tags,
            "entry_name": mdoc.get("name") or "", "basis_text": basis_text(collection, kept, entry_source)}


def _library_for_write(db, library_id: str, owner_id: str) -> dict:
    lib = db[COLLECTION].find_one({"_id": str(library_id or "")})
    if lib is None:
        raise LibraryNotFound(library_id)
    if lib.get("owner_id") != owner_id:
        raise NotAllowed(library_id)
    return lib


def add_dataset(db, lib: dict, dataset, owners, hidden=frozenset(), source: str = "") -> dict:
    """Add a snapshot of a dataset (its rows, measurements and reading) to the library."""
    _room(db, lib)
    if db[RECORDS].find_one({"library_id": lib["_id"], "origin.id": dataset.id, "entry_type": "data"}):
        raise LibraryError(f"“{dataset.name}” is already in “{lib['name']}”: use Update from the original on it.")
    snap = _dataset_snapshot(db, dataset, owners, hidden)
    return _insert(db, lib, "data", {"collection": "datasets", "id": dataset.id}, snap, source)


def life_fields(model, lib: dict, label: str, equipment_type: str = "other", failure_mode: str = "",
                notes: str = "") -> dict:
    """A parametric life model's record fields (backend.library.user.snapshot), so the entry is also found by
    the library search and used as a prior; {} for any other model."""
    if user_lib.why_not_model(model) is not None:
        return {}
    life = user_lib.snapshot(model, label or model.name, equipment_type or "other", failure_mode or "", notes or "",
                             lib["_id"], lib["owner_id"])
    for k in ("_id", "id", "created_at", "version", "library_id", "owner_id"):
        life.pop(k, None)
    return life


def add_model(db, lib: dict, collection: str, mdoc: dict, owners, source: str = "", label: Optional[str] = None,
              equipment_type: str = "other", failure_mode: str = "", notes: str = "", unique: bool = True) -> dict:
    """Add a snapshot of a saved model (any kind the app saves: fitted, from parameters, from a handbook, a
    Bayesian update) to the library. Its data isn't needed."""
    if collection not in MODEL_KINDS:
        raise LibraryError("A library takes non-repairable, repairable and accelerated life models.")
    _room(db, lib)
    if unique and db[RECORDS].find_one({"library_id": lib["_id"], "origin.id": mdoc["_id"], "entry_type": "model"}):
        raise LibraryError(f"“{mdoc.get('name')}” is already in “{lib['name']}”: use Update from the original on it.")
    source = _text(source, "the source", MAX_CITATION)
    snap = _model_snapshot(db, collection, mdoc, owners, source)
    if collection == "models":
        snap.update(life_fields(from_doc(_model_cls(collection), mdoc), lib, label or mdoc.get("name") or "",
                                equipment_type, failure_mode, notes))
        if label:
            snap["entry_name"] = label
            snap["custom_name"] = True
        _headline_from_summary(snap)
    return _insert(db, lib, "model", {"collection": collection, "id": mdoc["_id"]}, snap, source)


def _room(db, lib: dict) -> None:
    if db[RECORDS].count_documents({"library_id": lib["_id"]}) >= MAX_ENTRIES:
        raise LibraryError(f"“{lib['name']}” already holds {MAX_ENTRIES} entries, the most a library takes.")


def _insert(db, lib: dict, entry_type: str, origin: dict, snap: dict, source: str) -> dict:
    eid = f"{lib['_id']}:{uuid.uuid4().hex}"
    doc = {"_id": eid, "id": eid, "library_id": lib["_id"], "owner_id": lib["owner_id"], "entry_type": entry_type,
           "origin": origin, "version": 1, "created_at": _now(), "updated_at": _now(),
           "entry_source": _text(source, "the source", MAX_CITATION), **snap}
    doc.setdefault("source", lib["_id"])
    db[RECORDS].insert_one(doc)
    db[COLLECTION].update_one({"_id": lib["_id"]}, {"$set": {"updated_at": _now()}})
    return db[RECORDS].find_one({"_id": eid})


def refresh(db, lib: dict, entry_id: str, owners, hidden=frozenset()) -> dict:
    """Update from the original: a new snapshot of the dataset or model the entry was taken from, its
    version one up. The original must still be readable by the owner."""
    from backend.services import datasets as datasets_service

    doc = db[RECORDS].find_one({"_id": str(entry_id or ""), "library_id": lib["_id"]})
    if doc is None:
        raise LibraryNotFound(entry_id)
    oid, coll = _origin_id(doc), _origin_collection(doc)
    owners = list(owners or [])
    if _entry_type(doc) == "data":
        ds = datasets_service.get_dataset(db, oid or "", owners)
        if ds is None:
            raise LibraryError("The original dataset was deleted (or isn't in this workspace), so there's nothing "
                               "to update from. The library keeps its copy.")
        snap = _dataset_snapshot(db, ds, owners, hidden)
    else:
        mdoc = db[coll].find_one({"_id": oid or "", "owner_id": {"$in": owners}})
        if mdoc is None:
            raise LibraryError("The original model was deleted (or isn't in this workspace), so there's nothing to "
                               "update from. The library keeps its copy.")
        snap = _model_snapshot(db, coll, mdoc, owners, doc.get("entry_source") or "")
        if coll == "models":
            mode = doc.get("failure_mode") or {}
            name = (doc.get("entry_name") if doc.get("custom_name") else None) or snap["entry_name"]
            snap.update(life_fields(from_doc(_model_cls(coll), mdoc), lib, name, doc.get("equipment_type") or "other",
                                    "" if mode.get("code") == "all" else mode.get("name") or "", doc.get("notes") or ""))
            snap["entry_name"] = name
            _headline_from_summary(snap)
    snap["version"] = int(doc.get("version") or 1) + 1
    snap["updated_at"] = _now()
    db[RECORDS].update_one({"_id": doc["_id"]}, {"$set": snap})
    db[COLLECTION].update_one({"_id": lib["_id"]}, {"$set": {"updated_at": _now()}})
    return db[RECORDS].find_one({"_id": doc["_id"]})


def remove(db, lib: dict, entry_id: str) -> None:
    doc = db[RECORDS].find_one({"_id": str(entry_id or ""), "library_id": lib["_id"]})
    if doc is None:
        raise LibraryNotFound(entry_id)
    db[RECORDS].delete_one({"_id": doc["_id"]})
    db[COLLECTION].update_one({"_id": lib["_id"]}, {"$set": {"updated_at": _now()}})


def delete(db, lib: dict) -> int:
    removed = db[RECORDS].delete_many({"library_id": lib["_id"]}).deleted_count
    db[COLLECTION].delete_one({"_id": lib["_id"]})
    return int(removed)


# ---- using an entry (a copy in the user's own workspace) ---------------------------------------

def _model_cls(collection: str):
    from backend.schema import AltModelDoc, Model, RecurrentModelDoc

    return {"models": Model, "recurrent_models": RecurrentModelDoc, "alt_models": AltModelDoc}[collection]


def provenance(lib: dict, doc: dict) -> dict:
    return {"library_id": lib["_id"], "library_name": lib.get("name") or "", "entry_id": doc["_id"],
            "version": int(doc.get("version") or 1)}


def copy_dataset(db, lib: dict, doc: dict, owner_id: str, name: Optional[str] = None) -> dict:
    """The entry's dataset as a new dataset of the owner's (identical data they already have comes back
    instead, ``reused`` true)."""
    from backend.schema import Dataset, DatasetPart

    d = doc.get("data") or {}
    blob = bytes(d.get("blob") or b"")
    existing = db.datasets.find_one({"checksum": d.get("checksum"), "owner_id": owner_id}) if d.get("checksum") else None
    if existing is not None:
        return {"id": existing["_id"], "name": existing.get("name"), "url": f"/data/{existing['_id']}", "reused": True}
    part = d.get("measurements")
    ds = Dataset(id=uuid.uuid4().hex, name=_text(name or d.get("name") or doc.get("entry_name") or "Library data",
                                                  "a name", user_lib.MAX_NAME, required=True),
                 owner_id=owner_id, checksum=d.get("checksum") or "", n_rows=int(d.get("n_rows") or 0),
                 columns=d.get("columns") or [], data=blob, reading=d.get("reading"), notes=d.get("notes"),
                 measurements=DatasetPart(**part) if part else None, from_library=provenance(lib, doc))
    db.datasets.insert_one(to_doc(ds))
    return {"id": ds.id, "name": ds.name, "url": f"/data/{ds.id}", "reused": False}


def copy_model(db, lib: dict, doc: dict, owner_id: str, name: Optional[str] = None,
               dataset_id: str = "") -> dict:
    """The entry's model as a new model of the owner's, linked to ``dataset_id`` (a copy of the dataset it
    was fitted on) or to none."""
    snap = doc.get("snapshot") or {}
    coll = snap.get("collection")
    if coll not in MODEL_KINDS or not snap.get("doc"):
        raise LibraryError("This entry was added before libraries kept whole models: its owner can take a new copy "
                           "with Update from the original. Until then, use it from the record's page "
                           "(Use as a model…).")
    now = _now()
    body = {**snap["doc"], "id": uuid.uuid4().hex, "owner_id": owner_id, "dataset_id": dataset_id or "",
            "created_at": now, "updated_at": now, "from_library": provenance(lib, doc)}
    if name:
        body["name"] = _text(name, "a name", user_lib.MAX_NAME, required=True)
    model = _model_cls(coll)(**{k: v for k, v in body.items() if k != "_id"})
    db[coll].insert_one(to_doc(model))
    return {"id": model.id, "name": model.name, "url": MODEL_KINDS[coll][1] + model.id, "collection": coll}


def fitted_on_entry(db, lib: dict, doc: dict) -> Optional[dict]:
    ds_id = ((doc.get("snapshot") or {}).get("doc") or {}).get("dataset_id")
    if not ds_id:
        return None
    return db[RECORDS].find_one({"library_id": lib["_id"], "entry_type": "data", "origin.id": ds_id})


def entry_doc(db, lib: dict, entry_id: str) -> dict:
    doc = db[RECORDS].find_one({"_id": str(entry_id or ""), "library_id": lib["_id"]})
    if doc is None:
        raise LibraryNotFound(entry_id)
    return doc


def what_use_makes(db, lib: dict, doc: dict, with_dataset: bool) -> dict[str, int]:
    """How many datasets and models using the entry would create (for the caps)."""
    if _entry_type(doc) == "data":
        return {"datasets": 1, "models": 0}
    return {"datasets": 1 if with_dataset and fitted_on_entry(db, lib, doc) else 0, "models": 1}


def use(db, lib: dict, entry_id: str, owner_id: str, name: Optional[str] = None, with_dataset: bool = False) -> dict:
    """Use an entry: copy it into the owner's workspace, with where it came from."""
    doc = entry_doc(db, lib, entry_id)
    if _entry_type(doc) == "data":
        return {"dataset": copy_dataset(db, lib, doc, owner_id, name), "model": None}
    dataset = None
    if with_dataset:
        ds_doc = fitted_on_entry(db, lib, doc)
        if ds_doc is not None:
            dataset = copy_dataset(db, lib, ds_doc, owner_id)
    model = copy_model(db, lib, doc, owner_id, name, dataset["id"] if dataset else "")
    return {"dataset": dataset, "model": model}
