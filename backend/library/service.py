"""Search and read the reliability data library.

The records are JSON files shipped with the app (``backend/library/data``,
one per source, built by an importer under ``backend/scripts``), read once
per process. Nothing here touches the database: the library is the same for
everyone, public, and changes only with a release.

A user's own libraries (:mod:`backend.library.user`) are merged beside the
published sources by the caller passing ``mine`` (their sources and records)
to :func:`search`, :func:`get`, :func:`detail` and :func:`sources`; their
records rank the same way and come first on a tie.

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

from backend.library import covariate, schema
from backend.errors import client_message

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
    index = [_index_entry(r) for r in records]
    for src in sources.values():
        mine = [r for r in records if r["source"] == src["id"]]
        src["records"] = len(mine)
        src["kinds"] = _count(mine, "kind")
        src["equipment_types"] = _count(mine, "equipment_type")
        src["components"] = len({r["name"] for r in mine})
    return {"sources": sources, "records": records, "by_id": by_id, "index": index}


def _index_entry(r: dict) -> dict[str, set[str]]:
    """The words of one record by field, as search scores them."""
    cond = r.get("conditions") or {}
    return {
        "code": _words(r.get("source_code", "").replace("-", " ")) | {r.get("source_code", "").lower()},
        "name": _words(r["name"]),
        "mode": _words(f"{r['failure_mode']['name']} {r['failure_mode']['code']}"),
        "equipment": _words(f"{schema.EQUIPMENT_TYPES.get(r['equipment_type'], '')} {r['equipment_type']}"),
        "conditions": _words(" ".join(str(v) for k, v in cond.items() if k != "industry")
                             + " " + _environment_words(r)),
        "text": _words(r.get("source_text", "")),
    }


def _environment_words(rec: dict) -> str:
    """A handbook record's environments, by symbol and name, so a search
    for 'naval' or 'missile launch' finds the parts that have a factor for
    it."""
    values = (rec.get("environment_factors") or rec.get("generic_rates") or {}).get("values") or {}
    return " ".join(f"{code} {schema.ENVIRONMENTS[code][0]}" for code in values)


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
    if rec.get("kind") in ("life", "covariate_model"):
        return str(u.get("as_given") or u.get("value") or "")
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
    if rec.get("kind") == "covariate_model":
        return f"covariate model ({covariate.rate_unit_words(rec)})"
    d = rec["distribution"]
    args = ", ".join(f"{p['name']}={_sig(p['value'])}" for p in d["params"])
    return f"{d['family']}({args})"


def _source_of(rec: dict, mine: Optional[dict] = None) -> dict:
    """The record's source: a published one, or one of the caller's libraries."""
    if mine and rec["source"] in mine["sources"]:
        return mine["sources"][rec["source"]]
    return _library()["sources"].get(rec["source"], {})


def _citation_text(rec: dict) -> Optional[str]:
    c = rec.get("citation")
    if not c:
        return None
    return f"{c.get('report') or c['title']}, {c['table']}, p. {c['page']}"


def resolve(record_id: str) -> dict:
    """A published record by id, for a covariate model's ``uses`` (LookupError when unknown)."""
    return get(record_id)


def covariate_brief(rec: dict) -> dict:
    """A covariate model in a few fields, for a list row: its rate unit, its modes (each with its
    base rate in words and how many condition factors it has), and how many inputs it reads."""
    m = covariate.model_of(rec)
    modes = []
    for mode in m.get("modes") or []:
        sub = get(mode["uses"]) if mode.get("uses") else None
        modes.append({"key": mode["key"], "name": mode.get("name"), "symbol": mode.get("symbol"),
                      "base": covariate.base_text(mode),
                      "base_symbol": (mode.get("base") or {}).get("symbol"),
                      "factors": len(mode.get("factors") or []),
                      **({"uses": mode["uses"], "uses_name": sub.get("name")} if sub else {})})
    try:
        n_inputs = len(covariate.inputs(rec, resolve))
    except (LookupError, covariate.CovariateError):
        n_inputs = len(m.get("inputs") or [])
    return {"rate_unit": covariate.rate_unit(rec), "rate_unit_words": covariate.rate_unit_words(rec),
            "per_cycle": covariate.per_cycle(rec), "equation": m.get("equation"), "formula": m.get("formula"),
            "modes": modes, "factors": covariate.factor_count(rec), "inputs": n_inputs,
            "chapter": (rec.get("conditions") or {}).get("chapter")}


def covariate_inputs(rec: dict) -> list[dict]:
    """Every input a covariate model reads (its own and its parts'), as the Conditions editor
    shows them."""
    keep = ("key", "name", "group", "role", "kind", "label", "symbol", "unit", "default", "default_basis", "limits",
            "choices", "page", "help")
    every = covariate.inputs(rec, resolve)
    keys = {i["key"] for i in every}
    out = []
    for i in every:
        row = {k: i[k] for k in keep if k in i}
        # An input the model reads only when others have certain values ("when"), as terms the editor can
        # check: [{key, op, value}], every one to hold. Left off (always asked) when it isn't that plain,
        # or when one of the others isn't entered here.
        terms = covariate.when_terms(i["when"]) if i.get("when") else None
        prefix = i["key"][:len(i["key"]) - len(i["name"])]
        if terms and all(prefix + t["name"] in keys for t in terms):
            row["needed_when"] = [{"key": prefix + t["name"], "op": t["op"], "value": t["value"]} for t in terms]
        out.append(row)
    return out


def record_inputs(rec: dict) -> list[dict]:
    """The covariates a record reads (backend/library/record_covariates.py), as the shared input
    component shows them."""
    from backend.library import record_covariates as rc

    if rec.get("kind") == "covariate_model":
        return rc.inputs(rec, resolve)
    return rc.inputs(rec)


def evaluate(record_id: str, values: Optional[dict] = None, mine: Optional[dict] = None,
             time_unit: str = "hours") -> dict:
    """A record's rate under its covariates (by key; a missing one takes its default), or a
    component's chance of failing over a period: {ok, result, warnings} or {ok: false, problems,
    missing} when a covariate is missing, not a number, or past a limit (an NSWC-11 one says the
    handbook's page). A covariate model's result is its modes and total, as before; any other
    record's is the one evaluator's (record_covariates.evaluate). Raises LibraryNotFound, or
    ValueError for values that aren't an object."""
    from backend.library import components
    from backend.library import record_covariates as rc

    if values is not None and not isinstance(values, dict):
        raise ValueError("covariates must be an object of covariate key to value.")
    if components.is_component_id(record_id):
        try:
            comp = components.get(record_id)
        except components.ComponentNotFound as exc:
            raise LibraryNotFound(str(exc)) from None
        try:
            result = components.evaluate(comp, values or {})
        except components.ComponentError as exc:
            return {"ok": False, "component_id": comp["id"], "problems": exc.problems, "missing": exc.missing}
        return {"ok": True, "component_id": comp["id"], "result": result, "warnings": []}
    rec = get(record_id, mine)
    src = _source_of(rec, mine)
    if rec.get("kind") == "covariate_model":
        try:
            result = covariate.evaluate(rec, {k: v for k, v in (values or {}).items() if k != rc.CYCLES or
                                              not covariate.per_cycle(rec)}, resolve)
        except covariate.CovariateError as exc:
            return {"ok": False, "record_id": rec["id"], "problems": exc.problems, "missing": exc.missing,
                    "disclaimer": src.get("disclaimer")}
        out = {"ok": True, "record_id": rec["id"], "result": result, "warnings": result.pop("warnings"),
               "disclaimer": src.get("disclaimer")}
        if covariate.per_cycle(rec) and (values or {}).get(rc.CYCLES) not in (None, ""):
            try:
                out["rate"] = rc.evaluate(rec, values, time_unit)
            except rc.RecordCovariateError as exc:
                out["rate_problems"] = exc.problems
        return out
    try:
        result = rc.evaluate(rec, values or {}, time_unit, require_rate=False)
    except rc.RecordCovariateError as exc:
        return {"ok": False, "record_id": rec["id"], "problems": exc.problems, "missing": exc.missing,
                "disclaimer": src.get("disclaimer")}
    return {"ok": True, "record_id": rec["id"], "result": result, "warnings": result.pop("warnings"),
            "disclaimer": src.get("disclaimer")}


def brief(rec: dict, mine: Optional[dict] = None) -> dict:
    """A record as a search result row."""
    src = _source_of(rec, mine)
    s = rec.get("summary") or {}
    return {
        "id": rec["id"], "label": rec["label"], "name": rec["name"],
        "equipment_type": rec["equipment_type"], "kind": rec["kind"],
        "failure_mode": rec["failure_mode"]["name"],
        "mean": s.get("mean"), "p05": s.get("p05"), "p95": s.get("p95"),
        **({"covariate": covariate_brief(rec)} if rec.get("kind") == "covariate_model" else {}),
        "units": units_text(rec), "distribution": distribution_text(rec),
        "basis": rec["basis"], "source": src.get("short_name", rec["source"]),
        "citation": _citation_text(rec),
        # A user library's record: its library, the model it was taken from and its family's parameters.
        **({"mine": True, "library_id": rec["source"], "model": rec.get("model"), "b10": s.get("b10"),
            "family": rec["distribution"]["family"], "params": rec["distribution"]["params"],
            "evidence": rec.get("evidence")} if src.get("mine") else {}),
        **({"environment_factors": rec["environment_factors"]["values"]} if rec.get("environment_factors") else {}),
        # A parts-count part type: its generic rate per environment (per million hours), and its quality grades.
        **({"generic_rates": rec["generic_rates"]["values"], "method": "parts_count"} if rec.get("generic_rates") else {}),
        **({"quality_factors": {"levels": rec["quality_factors"]["levels"],
                                "default": rec["quality_factors"].get("default")}} if rec.get("quality_factors") else {}),
        # A handbook part type: its base rate as printed and the handbook's πQ range (a parts count's inputs).
        **({"per_million_hours": rec["prediction"].get("per_million_hours"),
            "quality_factor_range": rec["prediction"].get("quality_factor_range"),
            "quality_factor_default": rec["prediction"].get("quality_factor_default")} if rec.get("prediction") else {}),
    }


#: What a record can be used as on its own: a life model (an exponential at its rate) or a prior
#: on one, once its covariates are given (a pipe's length, the running hours for another clock, the
#: demands a year for a probability per demand, a handbook part's environment). A handbook rate (a
#: point value, no spread) can be a model but not a prior; a covariate model (NSWC-11) is attached
#: at a position with its covariates fixed there or set in the RBD.
USES = {"model": "a life model", "prior": "a prior on a life model",
        "attach": "a position's model (a life model, or a covariate model with covariates fixed there)"}


def usable_as(rec: dict, use: str) -> bool:
    """Whether the record can be ``use`` ("model", "prior" or "attach"), its covariates given. A
    life record (a life distribution, or a saved model's snapshot) always can."""
    if use == "attach" and rec.get("kind") == "covariate_model":
        return True
    if rec.get("kind") == "life":
        return True
    if rec.get("basis") == "prediction_model":
        return use != "prior" and rec.get("kind") == "rate"
    if rec.get("kind") == "per_demand":
        return True
    return rec.get("kind") == "rate" and str((rec.get("units") or {}).get("value") or "").startswith("per_hour")


def left_out_by(records: list, use: str) -> dict:
    """Why records were left out of a search for ``use``: {prediction_model: n, per_demand: n, other: n}."""
    out: dict = {}
    for rec in records:
        if usable_as(rec, use):
            continue
        why = "prediction_model" if rec.get("basis") == "prediction_model" else \
            "per_demand" if rec.get("kind") == "per_demand" else "other"
        out[why] = out.get(why, 0) + 1
    return out


def search(query: Optional[str] = None, source: Optional[str] = None, equipment_type: Optional[str] = None,
           kind: Optional[str] = None, page: int = 1, page_size: int = DEFAULT_PAGE_SIZE,
           use: Optional[str] = None, mine: Optional[dict] = None, failure_mode: Optional[str] = None,
           facets: bool = False) -> dict:
    """A page of the records matching ``query`` and the filters, best first,
    with the total and the counts by equipment type, kind and source (of the
    query's matches, before the filters narrow them, so a filter shows what
    choosing it would give). ``use`` ("model" or "prior") keeps only the
    records that can be that on their own (:func:`usable_as`), and
    ``left_out`` says how many the other filters matched but it hid, by why.
    ``mine`` (:func:`backend.library.user.mine`): the caller's own libraries,
    searched beside the published sources (first on a tie). ``failure_mode``
    keeps the records with that failure mode's name (any case). ``facets``
    adds what each filter's choices would give with the other filters (and
    ``use``) kept: the app's record picker fills its dropdowns from them."""
    lib = _library()
    own = mine or {"sources": {}, "records": []}
    # Several sources, comma-separated (the parts-count picker searches both handbooks at once).
    picked = [x.strip() for x in str(source).split(",") if x.strip()] if source else []
    for one in picked:
        _check_choice("source", one, {**own["sources"], **lib["sources"]})
    _check_choice("equipment_type", equipment_type, schema.EQUIPMENT_TYPES)
    _check_choice("kind", kind, schema.KINDS)
    _check_choice("use", use, USES)
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
    pairs = [(rec, _index_entry(rec)) for rec in own["records"]] + list(zip(lib["records"], lib["index"]))
    for i, (rec, entry) in enumerate(pairs):
        score = _score(entry, tokens, whole) if tokens else 1
        if score:
            matched.append((score, i, rec))
    counts = {"equipment_type": _count([m[2] for m in matched], "equipment_type"),
              "kind": _count([m[2] for m in matched], "kind"),
              "source": _count([m[2] for m in matched], "source")}
    mode = " ".join(str(failure_mode or "").split()).lower() or None
    wanted = {"source": source, "equipment_type": equipment_type, "kind": kind, "failure_mode": mode}

    if len(picked) > 1:
        wanted["source"] = None

    def keeps(rec: dict, skip: Optional[str] = None) -> bool:
        if len(picked) > 1 and rec["source"] not in picked:
            return False
        return all(v is None or k == skip or _facet_value(rec, k) == v for k, v in wanted.items())

    hits = [m for m in matched if keeps(m[2])]
    left_out = left_out_by([m[2] for m in hits], use) if use else {}
    if use:
        hits = [m for m in hits if usable_as(m[2], use)]
    hits.sort(key=lambda m: (-m[0], m[1]))
    total = len(hits)
    start = (page - 1) * page_size
    rows = [brief(m[2], own) for m in hits[start:start + page_size]]
    return {
        "query": text or None,
        "filters": {k: v for k, v in (("source", source), ("equipment_type", equipment_type), ("kind", kind),
                                                ("failure_mode", failure_mode), ("use", use)) if v},
        "total": total, "page": page, "page_size": page_size,
        **({"left_out": left_out} if use else {}),
        "pages": max(1, math.ceil(total / page_size)),
        "results": rows,
        "counts": counts,
        **({"facets": {key: _facet_counts([m[2] for m in matched if keeps(m[2], key) and (not use or usable_as(m[2], use))], key)
                       for key in ("equipment_type", "failure_mode", "kind")}} if facets else {}),
    }


def _facet_value(rec: dict, key: str) -> str:
    if key == "failure_mode":
        return " ".join(str((rec.get("failure_mode") or {}).get("name") or "").split()).lower()
    return rec[key]


def _facet_counts(records: list[dict], key: str) -> dict[str, int]:
    """Counts by ``key``; failure modes by their name as written (the first
    spelling met), empty names left out."""
    out: dict[str, int] = {}
    for r in records:
        v = (r.get("failure_mode") or {}).get("name", "").strip() if key == "failure_mode" else r[key]
        if v:
            out[v] = out.get(v, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: kv[0].lower()))


def get(record_id: str, mine: Optional[dict] = None) -> dict:
    """One record in full (a published one, or one of the caller's own)."""
    wanted = str(record_id or "").strip()
    rec = _library()["by_id"].get(wanted)
    if rec is None and mine:
        rec = next((r for r in mine["records"] if r["id"] == wanted), None)
    if rec is None:
        raise LibraryNotFound(f"Library record '{record_id}' not found. Search the library for ids.")
    return rec


def detail(record_id: str, environment: Optional[str] = None, mine: Optional[dict] = None,
           model_link: Optional[dict] = None) -> dict:
    """A record with what a block would use: the default conversion (see
    :mod:`backend.library.convert`), or why it needs more input. A handbook
    record with environment factors converts for ``environment`` (e.g.
    'GF'); without one, ``environments`` lists the rate in each, so the
    caller can choose. A bad ``environment`` raises ValueError. A user
    library's record carries its ``library`` and ``model_link`` (the model it
    was taken from, if the caller can still open it)."""
    from backend.library import convert

    rec = get(record_id, mine)
    if environment is not None:
        try:
            model = convert.to_block_model(rec, environment=environment)
        except convert.ConversionError as exc:
            raise ValueError(str(exc)) from None
    else:
        try:
            model = convert.to_block_model(rec)
        except convert.ConversionError as exc:
            model = {"needs": client_message(exc)}
    src = _source_of(rec, mine)
    out = {"record": rec, "units": units_text(rec), "block_model": model, "caveats": src.get("caveats") or [],
           "covariates": record_inputs(rec)}
    from backend.library import components

    member_of = [components.brief(c) for c in components.all_components(rec["source"])
                 if any(m["record_id"] == rec["id"] for m in c["modes"])]
    if member_of:
        out["components"] = member_of
    if rec.get("kind") == "covariate_model":
        out["covariate"] = {**covariate_brief(rec), "inputs": covariate_inputs(rec)}
        out["disclaimer"] = src.get("disclaimer")
    if src.get("mine"):
        out["library"] = {k: src.get(k) for k in ("id", "name", "description", "notes", "read_only", "records")}
        out["model_link"] = model_link
    values = (rec.get("environment_factors") or {}).get("values")
    if values:
        out["environments"] = [
            {"code": code, "name": schema.ENVIRONMENTS[code][0], "factor": values[code],
             "failure_rate_per_hour": schema.param_dict(rec["distribution"])["value"] * values[code]}
            for code in schema.ENVIRONMENTS if code in values]
    generic = (rec.get("generic_rates") or {}).get("values")
    if generic:  # a parts-count record: λg per environment, before the quality factor
        out["environments"] = [
            {"code": code, "name": schema.ENVIRONMENTS[code][0], "generic_rate_per_million_hours": generic[code],
             "failure_rate_per_hour": generic[code] / 1e6}
            for code in schema.ENVIRONMENTS if code in generic]
    return out


def sources(mine: Optional[dict] = None) -> dict:
    """The sources with their licences and what each holds: the caller's own
    libraries first (``mine``), then the published ones."""
    lib = _library()
    out = []
    for s in (mine or {}).get("sources", {}).values():
        out.append({k: s.get(k) for k in (
            "id", "name", "short_name", "description", "notes", "basis", "licence", "records", "components", "kinds",
            "equipment_types", "mine", "read_only", "created_at", "updated_at", "owner_id")})
    for s in lib["sources"].values():
        out.append({k: s.get(k) for k in (
            "id", "name", "short_name", "publisher", "title", "report", "edition", "year", "url", "home",
            "basis", "licence", "description", "caveats", "retrieved", "records", "components", "kinds",
            "equipment_types", "skipped", "data_version", "disclaimer")})
    return {
        "sources": out,
        "total_records": len(lib["records"]) + len((mine or {}).get("records", [])),
        "equipment_types": schema.EQUIPMENT_TYPES,
        "kinds": schema.KINDS,
        "bases": schema.BASES,
        "environments": {code: {"name": name, "covers": covers}
                         for code, (name, covers) in schema.ENVIRONMENTS.items()},
    }


def components(source: Optional[str] = None, query: Optional[str] = None) -> dict:
    """The components (an equipment type in one of the source's pooling groups, its failure modes
    together: backend/library/components.py), of ``source``, matching every word of ``query``."""
    from backend.library import components as comp

    if source is not None and source not in _library()["sources"]:
        # A library of the user's own (or an unknown one) has no components: none, not an error.
        return {"source": source, "query": query or None, "total": 0, "components": []}
    tokens = [_stem(t) for t in _WORD.findall(str(query or "").lower()) if t not in _STOP][:12]
    rows = []
    for c in comp.all_components(source):
        words = _words(f"{c['label']} {' '.join(m['mode'] for m in c['modes'])} "
                       f"{schema.EQUIPMENT_TYPES.get(c['equipment_type'], '')}")
        if all(t in words or any(w.startswith(t) for w in words) for t in tokens):
            rows.append(comp.brief(c))
    return {"source": source, "query": query or None, "total": len(rows), "components": rows}


def component_detail(component_id: str) -> dict:
    """One component in full: its modes, its covariates and how they combine."""
    from backend.library import components as comp

    try:
        return comp.detail(component_id)
    except comp.ComponentNotFound as exc:
        raise LibraryNotFound(str(exc)) from None


def components_is(record_id: str) -> bool:
    """Whether an id names a component (an NRC/INL equipment type in one pooling group)."""
    from backend.library import components as comp

    return comp.is_component_id(record_id)
