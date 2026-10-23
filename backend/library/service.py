"""Search and read the reliability data library.

The records are JSON files shipped with the app (``backend/library/data``,
one per source, built by an importer under ``backend/scripts``), read once
per process. Nothing here touches the database: the library is the same for
everyone, public, and changes only with a release.

Search ranks a record by where the words of the query appear: the component's
name and the source's own code count most, then the failure mode, the
equipment type, the conditions, and the source's description least. Every
word must appear somewhere (a word matches a word it starts, so "leak" finds
"leakage"; a trailing plural "s" is ignored). Ties keep the source's own
order, which groups each component's failure modes together.
"""

from __future__ import annotations

import json
import logging
import math
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from backend.library import schema

logger = logging.getLogger(__name__)
DATA_DIR = Path(__file__).resolve().parent / "data"
DEFAULT_PAGE_SIZE = 25
MAX_PAGE_SIZE = 100

#: Field weights for ranking.
_WEIGHTS = {"code": 6, "name": 5, "mode": 4, "equipment": 3, "conditions": 2, "text": 1}
_WORD = re.compile(r"[a-z0-9<>]+")
#: Words a query may contain that say nothing about a record.
_STOP = {"a", "an", "the", "of", "and", "or", "for", "to", "in", "on", "per", "with", "at", "by"}


class LibraryNotFound(LookupError):
    pass


def _words(text: str) -> set[str]:
    return {_stem(w) for w in _WORD.findall(str(text or "").lower())}


def _stem(word: str) -> str:
    return word[:-1] if len(word) > 3 and word.endswith("s") and not word.endswith("ss") else word


@lru_cache(maxsize=1)
def _library() -> dict[str, Any]:
    sources: dict[str, dict] = {}
    records: list[dict] = []
    for path in sorted(DATA_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        src = data["source"]
        sources[src["id"]] = {**src, "data_version": data.get("data_version"),
                              "skipped": len(data.get("skipped") or [])}
        records.extend(data["records"])
    if not records:  # e.g. an ignore file kept the data out of the build
        logger.warning("The reliability data library has no records (looked in %s).", DATA_DIR)
    by_id = {r["id"]: r for r in records}
    index = []
    for r in records:
        cond = r.get("conditions") or {}
        index.append({
            "code": _words(r.get("source_code", "").replace("-", " ")) | {r.get("source_code", "").lower()},
            "name": _words(r["name"]),
            "mode": _words(f"{r['failure_mode']['name']} {r['failure_mode']['code']}"),
            "equipment": _words(f"{schema.EQUIPMENT_TYPES[r['equipment_type']]} {r['equipment_type']}"),
            "conditions": _words(" ".join(str(v) for k, v in cond.items() if k != "industry")),
            "text": _words(r.get("source_text", "")),
        })
    for src in sources.values():
        mine = [r for r in records if r["source"] == src["id"]]
        src["records"] = len(mine)
        src["kinds"] = _count(mine, "kind")
        src["equipment_types"] = _count(mine, "equipment_type")
        src["components"] = len({r["name"] for r in mine})
    return {"sources": sources, "records": records, "by_id": by_id, "index": index}


def _count(records: list[dict], key: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in records:
        out[r[key]] = out.get(r[key], 0) + 1
    return dict(sorted(out.items()))


def _score(entry: dict[str, set[str]], tokens: list[str], whole: str) -> int:
    if whole and whole in entry["code"]:
        return 1000  # the source's own code, typed in full
    total = 0
    for t in tokens:
        best = 0
        for field, words in entry.items():
            if t in words or (len(t) >= 3 and any(w.startswith(t) for w in words)):
                best = max(best, _WEIGHTS[field])
        if best == 0:
            return 0
        total += best
    return total


def _check_choice(name: str, value: Optional[str], allowed) -> None:
    if value is not None and value not in allowed:
        raise ValueError(f"Unknown {name} '{value}'. Use one of: {', '.join(sorted(allowed))}.")


def units_text(rec: dict) -> str:
    """The value's unit in words: 'per hour (calendar)', 'per demand'."""
    u = rec.get("units") or {}
    text = {"per_hour": "per hour", "per_hour_per_foot": "per hour per foot of pipe",
            "per_demand": "per demand"}.get(u.get("value"), u.get("value") or "")
    if u.get("time_basis") == "calendar":
        text += " (calendar)"
    elif u.get("time_basis") == "operating":
        text += " (running)"
    return text


def _sig(x: Optional[float], digits: int = 4) -> Optional[float]:
    if x is None or not isinstance(x, (int, float)) or not math.isfinite(x) or x == 0:
        return x
    return float(f"{x:.{digits}g}")


def distribution_text(rec: dict) -> str:
    d = rec["distribution"]
    args = ", ".join(f"{p['name']}={_sig(p['value'])}" for p in d["params"])
    return f"{d['family']}({args})"


def brief(rec: dict) -> dict:
    """A record as a search result row."""
    src = _library()["sources"].get(rec["source"], {})
    s = rec.get("summary") or {}
    return {
        "id": rec["id"], "label": rec["label"], "name": rec["name"],
        "equipment_type": rec["equipment_type"], "kind": rec["kind"],
        "failure_mode": rec["failure_mode"]["name"],
        "mean": s.get("mean"), "p05": s.get("p05"), "p95": s.get("p95"),
        "units": units_text(rec), "distribution": distribution_text(rec),
        "basis": rec["basis"], "source": src.get("short_name", rec["source"]),
        "citation": f"{rec['citation'].get('report') or rec['citation']['title']}, "
                    f"{rec['citation']['table']}, p. {rec['citation']['page']}",
    }


def search(query: Optional[str] = None, source: Optional[str] = None, equipment_type: Optional[str] = None,
           kind: Optional[str] = None, page: int = 1, page_size: int = DEFAULT_PAGE_SIZE) -> dict:
    """A page of the records matching ``query`` and the filters, best first,
    with the total and the counts by equipment type, kind and source (of the
    query's matches, before the filters narrow them, so a filter shows what
    choosing it would give)."""
    lib = _library()
    _check_choice("source", source, lib["sources"])
    _check_choice("equipment_type", equipment_type, schema.EQUIPMENT_TYPES)
    _check_choice("kind", kind, schema.KINDS)
    page = 1 if page is None else int(page)
    page_size = DEFAULT_PAGE_SIZE if page_size is None else int(page_size)
    if page < 1:
        raise ValueError("page starts at 1.")
    if not 1 <= page_size <= MAX_PAGE_SIZE:
        raise ValueError(f"page_size must be 1 to {MAX_PAGE_SIZE}.")
    text = " ".join(str(query or "").split())[:200]
    tokens = [_stem(t) for t in _WORD.findall(text.lower()) if t not in _STOP][:12]
    whole = text.lower() if "-" in text and " " not in text else ""  # a full code, e.g. MDP-FTS-NS

    matched: list[tuple[int, int, dict]] = []
    for i, (rec, entry) in enumerate(zip(lib["records"], lib["index"])):
        score = _score(entry, tokens, whole) if tokens else 1
        if score:
            matched.append((score, i, rec))
    counts = {"equipment_type": _count([m[2] for m in matched], "equipment_type"),
              "kind": _count([m[2] for m in matched], "kind"),
              "source": _count([m[2] for m in matched], "source")}
    hits = [m for m in matched
            if (source is None or m[2]["source"] == source)
            and (equipment_type is None or m[2]["equipment_type"] == equipment_type)
            and (kind is None or m[2]["kind"] == kind)]
    hits.sort(key=lambda m: (-m[0], m[1]))
    total = len(hits)
    start = (page - 1) * page_size
    rows = [brief(m[2]) for m in hits[start:start + page_size]]
    return {
        "query": text or None,
        "filters": {k: v for k, v in (("source", source), ("equipment_type", equipment_type), ("kind", kind)) if v},
        "total": total, "page": page, "page_size": page_size,
        "pages": max(1, math.ceil(total / page_size)),
        "results": rows,
        "counts": counts,
    }


def get(record_id: str) -> dict:
    """One record in full."""
    rec = _library()["by_id"].get(str(record_id or "").strip())
    if rec is None:
        raise LibraryNotFound(f"Library record '{record_id}' not found. Search the library for ids.")
    return rec


def detail(record_id: str) -> dict:
    """A record with what a block would use: the default conversion (see
    :mod:`backend.library.convert`), or why it needs more input."""
    from backend.library import convert

    rec = get(record_id)
    try:
        model = convert.to_block_model(rec)
    except convert.ConversionError as exc:
        model = {"needs": str(exc)}
    src = _library()["sources"].get(rec["source"], {})
    return {"record": rec, "units": units_text(rec), "block_model": model,
            "caveats": src.get("caveats") or []}


def sources() -> dict:
    """The sources with their licences and what each holds."""
    lib = _library()
    out = []
    for s in lib["sources"].values():
        out.append({k: s.get(k) for k in (
            "id", "name", "short_name", "publisher", "title", "report", "edition", "year", "url", "home",
            "basis", "licence", "description", "caveats", "retrieved", "records", "components", "kinds",
            "equipment_types", "skipped", "data_version")})
    return {
        "sources": out,
        "total_records": len(lib["records"]),
        "equipment_types": schema.EQUIPMENT_TYPES,
        "kinds": schema.KINDS,
        "bases": schema.BASES,
    }
