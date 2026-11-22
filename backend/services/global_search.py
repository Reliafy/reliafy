"""One search for everything the viewer can open (the app's ⌘K search, and ``list kind
search`` over MCP, REST and the CLI).

It fans out to what each kind already keeps, reads names only, and ranks every hit the
same way, best first:

0. exact: the whole query is a key field (a name, a tag, a serial, a part number);
1. prefix: a key field starts with it;
2. word: every word typed starts a word of the record;
3. inside: every word is somewhere in it;
4. near: what's left is within a small typo (one letter wrong, missing, extra or
   swapped; two in a long word) of a word of the record that starts with the same letter.
   Codes (words with a digit) and words under four letters are never matched this way:
   TP-101 isn't GS-101, and "mower" isn't "lower" or "power". Near spellings are only
   offered when nothing matches as typed.

Access is the active workspace's, as its list pages have it: its own records, the shared
samples (in a personal workspace, minus the ones the viewer hid) and items shared with the
viewer; never another workspace's names. Reliafy Maintenance's records come only for a
viewer who may use it, from that workspace's own register, and work orders only with work
management on. The app's own pages and the how-to guides are searched in the browser
(``frontend/src/globalSearch.js``): they're part of the bundle.
"""

from __future__ import annotations

import re
import time
from datetime import datetime
from typing import Any, Callable, Iterable, Optional

from backend.services import access

MAX_QUERY = 200
MAX_WORDS = 8
DEFAULT_LIMIT = 5
MAX_LIMIT = 20
# The most documents of one collection a search reads (names only): far above any real
# workspace's, so a search stays bounded.
SCAN_CAP = 3000

_SPLIT = re.compile(r"[\s›/,;:()\[\]·|]+")


# ---- ranking ------------------------------------------------------------------------------

def _norm(text) -> str:
    return " ".join(str(text or "").lower().split())


def _near(a: str, b: str) -> bool:
    """Whether ``b`` (or the start of it, for a word still being typed) is within a small
    typo of ``a``: one edit for a word of up to seven letters, two for a longer one; a
    swap of two neighbours counts as one. Words under four letters, and codes (a word with a
    digit: a tag, a serial, a part number), must match as typed. The first letter must
    match (or be swapped with the second): a different first letter is another word
    ("mower" and "lower"), not a typo."""
    if len(a) < 4 or not b or any(ch.isdigit() for ch in a):
        return False
    if a[0] != b[0] and not (len(b) > 1 and a[0] == b[1] and a[1] == b[0]):
        return False
    most = 1 if len(a) <= 7 else 2
    for cand in {b, b[:len(a)], b[:len(a) + 1]}:
        if abs(len(cand) - len(a)) <= most and _distance(a, cand, most) <= most:
            return True
    return False


def _distance(a: str, b: str, most: int) -> int:
    """The optimal-string-alignment distance between two short words, giving up (most + 1)
    as soon as it must be larger than ``most``."""
    prev2: list[int] = []
    prev = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                cur[j] = min(cur[j], prev2[j - 2] + 1)
        if min(cur) > most:
            return most + 1
        prev2, prev = prev, cur
    return prev[-1]


class Matcher:
    """The query, and how well a record matches it (:meth:`tier`; None for not at all)."""

    def __init__(self, q, near: bool = True):
        self.q = _norm(q)[:MAX_QUERY]
        self.near = near
        self.words = [w for w in _SPLIT.split(self.q) if w][:MAX_WORDS]
        self._near: dict[tuple[str, str], bool] = {}

    def __bool__(self) -> bool:
        return bool(self.words)

    def _is_near(self, w: str, word: str) -> bool:
        key = (w, word)
        if key not in self._near:
            self._near[key] = _near(w, word)
        return self._near[key]

    def tier(self, keys: Iterable, extra: Iterable = ()) -> Optional[int]:
        keys = [_norm(k) for k in keys if k]
        text = " ".join(keys + [_norm(x) for x in extra if x])
        if not text or not self.words:
            return None
        if self.q in keys:
            return 0
        if any(k.startswith(self.q) for k in keys):
            return 1
        words = [w for w in _SPLIT.split(text) if w]
        if all(any(t.startswith(w) for t in words) for w in self.words):
            return 2
        missing = [w for w in self.words if w not in text]
        if not missing:
            return 3
        if self.near and all(any(self._is_near(w, t) for t in words) for w in missing):
            return 4
        return None


def ranked(hits: list[dict]) -> list[dict]:
    """Best first: by tier, then by name (A to Z)."""
    return sorted(hits, key=lambda h: (h["tier"], _norm(h.get("name")), h.get("id") or ""))


# ---- the kinds ----------------------------------------------------------------------------

# Each kind's group, in the order groups show on a tie (a better match puts its group first).
KINDS = {
    "asset": "Assets", "position": "Positions", "location": "Locations", "item": "Items",
    "part": "Parts", "product": "Products", "work_order": "Work orders",
    "dataset": "Data", "model": "Models", "rbd": "RBDs", "fault_tree": "Fault trees",
    "analysis": "Saved analyses", "report": "Reports", "library": "Libraries",
    "library_record": "Library records",
}
MAINTENANCE_KINDS = ("asset", "position", "location", "item", "part", "product", "work_order")

STRATEGY_LABELS = {
    "optimal_replacement": "Optimal replacement", "compare_two": "Two-model comparison",
    "failure_finding": "Failure finding", "demonstration_test": "Test plan (demonstration test)",
    "on_condition_interval": "Check interval (P-F)", "failure_finding_interval": "Test interval",
    "calendar_replacement": "Shutdown calendar", "overhaul_replace": "Overhaul and replace",
    "sequential_test": "Test plan (sequential test)",
}

# (kind, collection, the page a record opens on, what it is in words, extra words to match).
# A record's page is the base plus its id; the words come from its document.
_COLLECTIONS: list[tuple[str, str, str, Callable[[dict], str]]] = [
    ("dataset", "datasets", "/data/", lambda d: "Data"),
    ("model", "models", "/models/m/", lambda d: _life_label(d)),
    ("model", "recurrent_models", "/models/recurrent/", lambda d: "Repairable model"),
    ("model", "alt_models", "/models/alt/", lambda d: "Accelerated life model"),
    ("model", "degradation_models", "/models/degradation/", lambda d: "Degradation model"),
    ("rbd", "rbds", "/systems/b/", lambda d: "Reliability block diagram"),
    ("fault_tree", "fault_trees", "/systems/fault-trees/", lambda d: "Fault tree"),
    ("analysis", "strategy_analyses", "/strategy/analyses/",
     lambda d: STRATEGY_LABELS.get(d.get("kind"), "Strategy analysis")),
    ("analysis", "fleets", "/forecasts/", lambda d: "Fleet forecast"),
    ("analysis", "tracked_fleets", "/risk/", lambda d: "Condition monitoring"),
    ("analysis", "reliability_predictions", "/predictions/", lambda d: "Reliability prediction"),
    ("analysis", "maintainability_predictions", "/maintainability/", lambda d: "Maintainability prediction"),
    ("analysis", "rcm_studies", "/maintenance/rcm/", lambda d: "RCM study"),
    ("library", "libraries", "/libraries/", lambda d: "Your library"),
]
# Every field a search reads from those documents: names and what's needed to describe them.
_FIELDS = {"name": 1, "kind": 1, "owner_id": 1, "updated_at": 1, "created_at": 1, "description": 1,
           "notes": 1, "distribution_id": 1, "results.distribution": 1, "spec.distribution_id": 1}


def _life_label(doc: dict) -> str:
    if doc.get("kind") == "joint":
        return "Condition and life model"
    dist = (doc.get("results") or {}).get("distribution") or doc.get("distribution_id") or ""
    dist = str(dist).split("(")[0].strip()
    words = "Non-repairable model" + (" (proportional hazards)" if doc.get("kind") == "regression" else "")
    return f"{words} · {dist.capitalize() if dist.islower() else dist}" if dist else words


def _iso(value) -> Optional[str]:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value) if value else None


def _scope(db, ctx: access.AccessCtx, collection: str) -> dict:
    """The active workspace's documents, as its list pages read them: its own, the samples
    (personal only), and those shared with the viewer (personal only)."""
    query: dict = {"owner_id": {"$in": access.owner_in(ctx.list_owners)}}
    if ctx.is_personal and ctx.share_fallback and collection in access.SHARABLE_COLLECTIONS:
        shared = access.shared_ids(db, ctx.uid, collection)
        if shared:
            query = {"$or": [query, {"_id": {"$in": sorted(shared)}}]}
    return query


def _documents(db, ctx, match: Matcher, wanted: set[str]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for kind, coll, base, what in _COLLECTIONS:
        if kind not in wanted:
            continue
        for d in db[coll].find(_scope(db, ctx, coll), _FIELDS).limit(SCAN_CAP):
            if d["_id"] in ctx.hidden:
                continue
            tier = match.tier([d.get("name")], [d.get("description"), d.get("notes")])
            if tier is None:
                continue
            path = base + str(d["_id"])
            if coll == "models" and d.get("kind") == "joint":
                path = "/models/joint/" + str(d["_id"])
            out.setdefault(kind, []).append({
                "kind": kind, "id": str(d["_id"]), "name": d.get("name") or "(no name)", "tier": tier,
                "context": what(d), "path": path,
                "updated_at": _iso(d.get("updated_at") or d.get("created_at")),
                "sample": d.get("owner_id") == access.SAMPLE_OWNER,
            })
    if "report" in wanted:
        for d in db.reports.find({"owner_id": ctx.write_owner}, _FIELDS).limit(SCAN_CAP):
            tier = match.tier([d.get("name")], [d.get("description")])
            if tier is not None:
                out.setdefault("report", []).append({
                    "kind": "report", "id": str(d["_id"]), "name": d.get("name") or "(untitled)", "tier": tier,
                    "context": "Report", "path": f"/reports?open={d['_id']}",
                    "updated_at": _iso(d.get("updated_at") or d.get("created_at")), "sample": False,
                })
    return out


def _library_records(db, ctx, match: Matcher, limit: int) -> tuple[int, list[dict]]:
    """The published handbooks' records and the workspace's own libraries' (their search,
    which knows records' codes and equipment words), each ranked here like the rest."""
    from backend.library import service as library_service
    from backend.library import user as user_lib

    mine = user_lib.mine(db, access.owner_in(ctx.list_owners), ctx.hidden)
    try:
        found = library_service.search(match.q, page_size=min(50, max(limit * 4, limit)), mine=mine)
    except ValueError:
        return 0, []
    hits = []
    for r in found["results"]:
        tier = match.tier([r.get("name"), r.get("label")], [r.get("equipment_type"), r.get("failure_mode")])
        source, _, code = str(r["id"]).partition(":")
        bits = [r.get("source"), r.get("failure_mode"), r.get("units")]
        hits.append({
            "kind": "library_record", "id": r["id"], "name": r.get("name") or r.get("label") or r["id"],
            "tier": 3 if tier is None else tier, "context": " · ".join(str(b) for b in bits if b),
            "path": f"/libraries/{source}/{code}", "updated_at": None, "sample": not r.get("mine"),
        })
    return found["total"], hits


def parse_kinds(kinds) -> set[str]:
    """``kinds`` (a list, or words split by commas) as known kinds; none named: every kind."""
    if not kinds:
        return set(KINDS)
    if isinstance(kinds, str):
        kinds = kinds.split(",")
    named = {str(k).strip() for k in kinds if str(k).strip()}
    unknown = sorted(named - set(KINDS))
    if unknown:
        raise ValueError(f"Unknown kind {', '.join(unknown)}: use any of {', '.join(KINDS)}.")
    return named


def search(db, ctx: access.AccessCtx, q, kinds=None, limit: Any = DEFAULT_LIMIT,
           maintenance: Optional[Callable[[], Any]] = None, work_orders: bool = False) -> dict:
    """Every kind's best ``limit`` matches for ``q``, grouped by kind: the group with the
    best match first (KINDS order on a tie), each group best first, with its total.
    ``maintenance``: the workspace's Reliafy Maintenance (a function making it), only when
    the viewer may use it; ``work_orders``: work management is on."""
    started = time.perf_counter()
    try:
        limit = max(1, min(int(limit), MAX_LIMIT))
    except (TypeError, ValueError):
        raise ValueError("limit is a whole number from 1 to 20.")
    wanted = parse_kinds(kinds)
    if not Matcher(q):
        return {"q": "", "groups": [], "took_ms": 0}
    # As typed first; near spellings only when nothing matches that way, so a real match
    # never sits beside near-misses ("mower" finding "Lower bathroom").
    out = _search(db, ctx, Matcher(q, near=False), wanted, limit, maintenance, work_orders)
    if not out["groups"]:
        out = _search(db, ctx, Matcher(q), wanted, limit, maintenance, work_orders)
    out["took_ms"] = round((time.perf_counter() - started) * 1000, 1)
    return out


def _search(db, ctx, match: Matcher, wanted: set, limit: int, maintenance, work_orders: bool) -> dict:
    found: dict[str, list[dict]] = _documents(db, ctx, match, wanted)
    totals: dict[str, int] = {}
    if "library_record" in wanted:
        total, hits = _library_records(db, ctx, match, limit)
        if hits:
            found["library_record"], totals["library_record"] = hits, total
    m_kinds = wanted & set(MAINTENANCE_KINDS)
    if not work_orders:
        m_kinds.discard("work_order")
    if maintenance is not None and m_kinds:
        for kind, (total, hits) in maintenance().search_records(match.tier, m_kinds, limit).items():
            if hits:
                found[kind], totals[kind] = hits, total
    order = list(KINDS)
    groups = []
    for kind, hits in found.items():
        hits = ranked(hits)
        groups.append({"kind": kind, "label": KINDS[kind], "total": totals.get(kind, len(hits)),
                       "results": hits[:limit]})
    groups.sort(key=lambda g: (g["results"][0]["tier"], order.index(g["kind"])))
    return {"q": match.q, "groups": groups}
