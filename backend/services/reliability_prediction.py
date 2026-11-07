"""Reliability prediction: a parts-count estimate of a design's failure rate
from handbook base rates, before there is any failure data.

A parts list is lines, each a part with how many there are and a handbook part
type (a record of the reliability data library whose basis is a prediction
model: MIL-HDBK-217F). A line's failure rate is

    λ = λb × πE × πQ × quantity

the handbook's base failure rate for that part type, its environment factor
for where the equipment works (one environment for the whole prediction), a
quality factor the user sets per line (1 unless they say otherwise) and the
quantity. The system is every part in series with a constant rate: the rates
add, MTBF = 1/λ and R(t) = exp(−λt) at the mission time.

The handbook's other factors (temperature, electrical stress, construction,
power and so on) aren't applied: every line says which ones, from its record's
``prediction.not_applied``. A parts count compares designs early; it never says
how the equipment will fail in service. Results are computed here and stored
with the prediction when it's saved (never taken from a client), so a saved
prediction is evidence that can be read back as it was.

Pure calculation first (:func:`compute`), then the read of a product's parts
list (:func:`lines_from_product`), then the store of saved predictions, which
mirrors :mod:`backend.services.strategy_store`.
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from backend.db import from_doc, to_doc
from backend.library import schema as library_schema
from backend.library import service as library_service
from backend.schema import ReliabilityPrediction
from backend.services import access

COLLECTION = "reliability_predictions"
#: The library source a parts count draws on (the only handbook source today).
HANDBOOK_SOURCE = "mil-hdbk-217f-n2"
DEFAULT_ENVIRONMENT = "GF"
DEFAULT_MISSION_HOURS = 1000.0
DEFAULT_QUALITY_FACTOR = 1.0
MAX_LINES = 500
MAX_QUANTITY = 1e6
MAX_MISSION_HOURS = 1e9
MAX_ASSEMBLY_DEPTH = 8
NAME_LENGTH = 200
TEXT_LENGTH = 120
PER_MILLION = 1e6

#: What this method applies, in the handbook's symbols.
APPLIED = [
    {"symbol": "λb", "name": "base failure rate"},
    {"symbol": "πE", "name": "environment"},
    {"symbol": "πQ", "name": "quality"},
]
METHOD = "Parts count: λ = Σ λb × πE × πQ × quantity over the lines (every part in series); R(t) = exp(−λt)."


class PredictionError(ValueError):
    """An input the prediction can't use, said for the user."""


class PredictionNotFound(KeyError):
    """A saved prediction id that's unknown or not visible."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---- environments ---------------------------------------------------------------------------

def environments() -> list[dict]:
    """The handbook's use environments: code, name and what each covers."""
    return [{"code": code, "name": name, "covers": covers}
            for code, (name, covers) in library_schema.ENVIRONMENTS.items()]


def environment_code(environment: Any) -> str:
    code = str(environment or "").strip().upper()
    if code not in library_schema.ENVIRONMENTS:
        choices = ", ".join(f"{c} ({n.lower()})" for c, (n, _) in library_schema.ENVIRONMENTS.items())
        raise PredictionError(f"Unknown environment '{environment}'. Use one of {choices}.")
    return code


# ---- the lines ------------------------------------------------------------------------------

def _text(value: Any, what: str, limit: int, required: bool = False) -> str:
    text = " ".join(str(value if value is not None else "").split())
    if required and not text:
        raise PredictionError(f"Each line needs a {what}.")
    return text[:limit]


def _number(value: Any, what: str, line: str, low: float, high: float, default: float | None = None) -> float:
    if value is None or value == "":
        if default is None:
            raise PredictionError(f"'{line}': {what} is required.")
        return default
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise PredictionError(f"'{line}': {what} must be a number.") from None
    if not math.isfinite(v) or not low < v <= high:
        raise PredictionError(f"'{line}': {what} must be above {low:g} and at most {high:g}.")
    return v


def assembly_path(value: Any) -> list[str]:
    """An assembly as a path of names: a list, or one string split on › / > |."""
    if value is None:
        return []
    if isinstance(value, str):
        parts = [p for p in (s.strip() for s in _split_path(value)) if p]
    elif isinstance(value, (list, tuple)):
        parts = [" ".join(str(p).split()) for p in value]
        parts = [p for p in parts if p]
    else:
        raise PredictionError("assembly is a name, a path such as 'Power › BMS board', or a list of names.")
    if len(parts) > MAX_ASSEMBLY_DEPTH:
        raise PredictionError(f"An assembly path goes at most {MAX_ASSEMBLY_DEPTH} levels deep.")
    return [p[:TEXT_LENGTH] for p in parts]


def _split_path(text: str) -> list[str]:
    for sep in ("›", " > ", " / ", "|"):
        if sep in text:
            return text.split(sep)
    return [text]


def normalise_lines(lines: Any) -> list[dict]:
    """The lines as the calculation (and a saved prediction) keeps them:
    name, reference, quantity, assembly (a path), record_id and
    quality_factor, each checked. Raises :class:`PredictionError`."""
    if not isinstance(lines, list):
        raise PredictionError("lines must be a list of parts: [{name, quantity, record_id, ...}].")
    if not lines:
        raise PredictionError("The parts list is empty: add at least one line.")
    if len(lines) > MAX_LINES:
        raise PredictionError(f"A parts list has at most {MAX_LINES} lines.")
    out = []
    for i, raw in enumerate(lines, 1):
        if not isinstance(raw, dict):
            raise PredictionError(f"Line {i} must be an object: {{name, quantity, record_id, ...}}.")
        name = _text(raw.get("name"), "name", NAME_LENGTH)
        if not name:
            raise PredictionError(f"Line {i} needs a name (the part).")
        record_id = _text(raw.get("record_id"), "record id", NAME_LENGTH) or None
        line = {
            "name": name,
            "reference": _text(raw.get("reference"), "reference", TEXT_LENGTH),
            "quantity": _number(raw.get("quantity"), "quantity", name, 0, MAX_QUANTITY, default=1.0),
            "assembly": assembly_path(raw.get("assembly")),
            "record_id": record_id,
            "quality_factor": _number(raw.get("quality_factor"), "quality_factor (πQ)", name, 0, 1e4,
                                      default=DEFAULT_QUALITY_FACTOR),
        }
        if raw.get("notes"):
            line["notes"] = _text(raw.get("notes"), "notes", 500)
        out.append(line)
    return out


def normalise_inputs(inputs: dict | None) -> dict:
    """A prediction's inputs, checked: environment, mission_time (hours),
    lines, and the product they came from (kept as given: id, name, rev,
    part_number) and notes."""
    inputs = inputs or {}
    out = {
        "environment": environment_code(inputs.get("environment") or DEFAULT_ENVIRONMENT),
        "mission_time": _number(inputs.get("mission_time"), "mission_time (hours)", "mission time", 0,
                                MAX_MISSION_HOURS, default=DEFAULT_MISSION_HOURS),
        "lines": normalise_lines(inputs.get("lines")),
    }
    product = inputs.get("product")
    if isinstance(product, dict) and (product.get("name") or product.get("id")):
        out["product"] = {k: _text(product.get(k), k, NAME_LENGTH) or None
                          for k in ("id", "name", "rev", "part_number")}
        if out["product"]["id"]:
            out["product_id"] = out["product"]["id"]  # the key other predictions find the product by
    notes = _text(inputs.get("notes"), "notes", 2000)
    if notes:
        out["notes"] = notes
    return out


# ---- the handbook records --------------------------------------------------------------------

def _record(record_id: str, line_name: str) -> dict:
    try:
        rec = library_service.get(record_id)
    except library_service.LibraryNotFound:
        raise PredictionError(f"'{line_name}': no library record '{record_id}'. Search the library for the part "
                              f"type (source {HANDBOOK_SOURCE}).") from None
    if rec.get("basis") != "prediction_model" or not rec.get("prediction"):
        raise PredictionError(f"'{line_name}': '{rec['label']}' is {rec.get('basis', 'field data').replace('_', ' ')}, "
                              f"not a handbook part type. A parts count uses handbook base rates: search the "
                              f"library with source {HANDBOOK_SOURCE}.")
    return rec


def _quality_range(rec: dict) -> tuple[list | None, bool]:
    """The handbook's πQ range for the record, and whether its model has a
    quality factor at all."""
    pred = rec.get("prediction") or {}
    rng = pred.get("quality_factor_range")
    has = bool(rng) or any(f.get("symbol") == "πQ" for f in pred.get("not_applied") or [])
    return (list(rng) if rng else None), has


def _environment_factor(rec: dict, code: str, line_name: str) -> float | None:
    """The record's πE for the environment; None when the handbook's model for
    this part has no environment factor (a few parts)."""
    factors = rec.get("environment_factors")
    if not factors:
        return None
    values = factors.get("values") or {}
    if code not in values:
        from backend.library import convert

        raise PredictionError(f"'{line_name}': the handbook gives no {code} ({library_schema.ENVIRONMENTS[code][0].lower()}) "
                              f"factor for '{rec['name']}'. It has {convert.environment_choices(rec)}.")
    return float(values[code])


# ---- the calculation -------------------------------------------------------------------------

def _sig(x: float | None, digits: int = 6) -> float | None:
    if x is None or not math.isfinite(x) or x == 0:
        return x
    return float(f"{x:.{digits}g}")


def _share(part: float, total: float) -> float:
    return part / total if total > 0 else 0.0


def _label(path: list[str]) -> str:
    return " › ".join(path)


def _assembly_rows(lines: list[dict]) -> list[dict]:
    """The assemblies' rates: every path prefix, in order of first appearance
    (a tree walked top down), with the lines under it at any depth; then a
    row for lines in no assembly, when there are both."""
    seen: list[tuple[str, ...]] = []
    for line in lines:
        path = tuple(line["assembly"])
        for depth in range(1, len(path) + 1):
            prefix = path[:depth]
            if prefix not in seen:
                seen.append(prefix)
    order = sorted(seen, key=lambda p: _tree_key(p, seen))
    rows = []
    for prefix in order:
        under = [ln for ln in lines if tuple(ln["assembly"][:len(prefix)]) == prefix]
        rows.append(_group_row(list(prefix), under, depth=len(prefix) - 1))
    loose = [ln for ln in lines if not ln["assembly"]]
    if order and loose:
        rows.append(_group_row([], loose, depth=0, name="Not in an assembly"))
    return rows


def _tree_key(path: tuple, order: list) -> tuple:
    """Sort assemblies as a tree: each path right after its parent, siblings in
    the order they first appeared."""
    return tuple(order.index(path[:d]) for d in range(1, len(path) + 1))


def _group_row(path: list[str], under: list[dict], depth: int, name: str | None = None) -> dict:
    rate = sum(ln["rate_per_million_hours"] or 0.0 for ln in under)
    return {
        "path": path, "name": name or path[-1], "label": _label(path), "depth": depth,
        "lines": len(under), "assigned": sum(1 for ln in under if ln["record_id"]),
        "parts": _sig(sum(ln["quantity"] for ln in under)),
        "rate_per_million_hours": rate, "rate_per_hour": rate / PER_MILLION,
        "mtbf_hours": PER_MILLION / rate if rate > 0 else None,
    }


def _pareto(rows: list[tuple[str, float, dict]], total: float) -> list[dict]:
    rows = sorted(rows, key=lambda r: -r[1])
    out, cumulative = [], 0.0
    for name, rate, extra in rows:
        cumulative += _share(rate, total)
        out.append({"name": name, "rate_per_million_hours": rate, "share": _share(rate, total),
                    "cumulative_share": min(cumulative, 1.0), **extra})
    return out


def compute(lines: Any, environment: Any = DEFAULT_ENVIRONMENT, mission_time: Any = DEFAULT_MISSION_HOURS) -> dict:
    """The parts count for ``lines`` in ``environment`` (a handbook symbol
    such as GF) with reliability at ``mission_time`` hours. Lines without a
    record_id are listed and left out of the total, with a warning. Raises
    :class:`PredictionError` for anything it can't use."""
    inputs = normalise_inputs({"lines": lines, "environment": environment, "mission_time": mission_time})
    code, t = inputs["environment"], inputs["mission_time"]
    env_name, env_covers = library_schema.ENVIRONMENTS[code]
    warnings: list[str] = []
    out_lines: list[dict] = []
    not_applied: dict[str, dict] = {}
    records: dict[str, dict] = {}
    sources: dict[str, dict] = {}
    for line in inputs["lines"]:
        row = {**line, "assembly_label": _label(line["assembly"])}
        if not line["record_id"]:
            row.update({"assigned": False, "part_type": None, "category": None, "base_rate_per_million_hours": None,
                        "environment_factor": None, "quality_factor_range": None, "each_per_million_hours": None,
                        "rate_per_million_hours": None, "rate_per_hour": None, "share": None, "not_applied": [],
                        "line_warnings": ["No handbook part type: left out of the total."]})
            out_lines.append(row)
            continue
        rec = _record(line["record_id"], line["name"])
        pred = rec["prediction"]
        base = float(pred["per_million_hours"])
        pi_e = _environment_factor(rec, code, line["name"])
        q_range, has_q = _quality_range(rec)
        pi_q = line["quality_factor"]
        line_warnings: list[str] = []
        if not has_q and pi_q != DEFAULT_QUALITY_FACTOR:
            raise PredictionError(f"'{line['name']}': the handbook's model for '{rec['name']}' has no quality "
                                  f"factor; leave quality_factor at 1.")
        if q_range and not (q_range[0] <= pi_q <= q_range[1]):
            line_warnings.append(f"πQ {pi_q:g} is outside the handbook's {q_range[0]:g}–{q_range[1]:g} for "
                                 f"{rec['name']}.")
        if pi_e is None:
            line_warnings.append(f"The handbook gives no environment factor for {rec['name']}: λb × πQ only.")
        each = base * (pi_e if pi_e is not None else 1.0) * pi_q
        rate = each * line["quantity"]
        left_out = [f for f in pred.get("not_applied") or [] if f.get("symbol") != "πQ"]
        for f in left_out:  # the same symbol means different things in different sections (πC)
            not_applied.setdefault(f"{f['symbol']} {f['name']}", f)
        row.update({
            "assigned": True,
            "part_type": rec["name"], "part_type_label": rec["label"],
            "category": library_schema.EQUIPMENT_TYPES.get(rec["equipment_type"], rec["equipment_type"]),
            "equipment_type": rec["equipment_type"],
            "section": (rec.get("conditions") or {}).get("section") or rec.get("source_code"),
            "base_rate_per_million_hours": base,
            "environment_factor": pi_e,
            "quality_factor_range": q_range,
            "each_per_million_hours": each,
            "rate_per_million_hours": rate, "rate_per_hour": rate / PER_MILLION,
            # The same rate under the name other predictions read it by (a maintainability
            # prediction weights its lines by these, matched by reference or name).
            "failure_rate": rate, "failure_rate_unit": "per_million_hours",
            "share": None,
            "applied": [a["symbol"] for a in APPLIED if a["symbol"] != "πE" or pi_e is not None],
            "not_applied": left_out,
            "line_warnings": line_warnings,
        })
        warnings.extend(f"'{line['name']}': {w}" for w in line_warnings)
        records[rec["id"]] = {"label": rec["label"], "version": rec["version"], "source": rec["source"],
                              "citation": f"{rec['citation'].get('report') or rec['citation']['title']}, "
                                          f"{rec['citation']['table']}, p. {rec['citation']['page']}"}
        if rec["source"] not in sources:
            sources[rec["source"]] = _source(rec["source"])
        out_lines.append(row)

    assigned = [ln for ln in out_lines if ln["assigned"]]
    unassigned = [ln for ln in out_lines if not ln["assigned"]]
    total = sum(ln["rate_per_million_hours"] for ln in assigned)
    for ln in assigned:
        ln["share"] = _share(ln["rate_per_million_hours"], total)
    if unassigned:
        names = ", ".join(f"{ln['name']} (×{ln['quantity']:g})" for ln in unassigned[:6])
        more = f" and {len(unassigned) - 6} more" if len(unassigned) > 6 else ""
        warnings.insert(0, f"{len(unassigned)} line{'s have' if len(unassigned) != 1 else ' has'} no handbook part "
                           f"type and {'are' if len(unassigned) != 1 else 'is'} left out of the total: {names}{more}.")
    if not assigned:
        warnings.insert(0, "No line has a handbook part type yet, so there is no total.")

    by_category: dict[str, dict] = {}
    for ln in assigned:
        c = by_category.setdefault(ln["category"], {"rate": 0.0, "lines": 0, "parts": 0.0})
        c["rate"] += ln["rate_per_million_hours"]
        c["lines"] += 1
        c["parts"] += ln["quantity"]
    mtbf = PER_MILLION / total if total > 0 else None
    reliability = math.exp(-total / PER_MILLION * t) if total > 0 else None
    return {
        "method": METHOD,
        "environment": {"code": code, "name": env_name, "covers": env_covers},
        "mission_time_hours": t,
        "failure_rate_per_million_hours": total,
        "failure_rate_per_hour": total / PER_MILLION,
        "mtbf_hours": mtbf,
        "reliability_at_mission": reliability,
        "unreliability_at_mission": (1 - reliability) if reliability is not None else None,
        "counts": {"lines": len(out_lines), "assigned": len(assigned), "unassigned": len(unassigned),
                   "parts": _sig(sum(ln["quantity"] for ln in out_lines)),
                   "parts_assigned": _sig(sum(ln["quantity"] for ln in assigned))},
        "lines": out_lines,
        "unassigned": [{k: ln[k] for k in ("name", "reference", "quantity", "assembly")} for ln in unassigned],
        "assemblies": _assembly_rows(out_lines),
        "pareto": {
            "by_line": _pareto([(ln["name"], ln["rate_per_million_hours"],
                                 {"part_type": ln["part_type"], "quantity": ln["quantity"],
                                  "assembly": ln["assembly_label"]}) for ln in assigned], total),
            "by_category": _pareto([(name, c["rate"], {"lines": c["lines"], "parts": _sig(c["parts"])})
                                    for name, c in by_category.items()], total),
        },
        "factors": {
            "applied": [dict(a) for a in APPLIED],
            "not_applied": [{"symbol": f["symbol"], "name": f["name"]} for f in not_applied.values()],
            "quality_factor_default": DEFAULT_QUALITY_FACTOR,
            "note": ("Each line's rate is λb × πE × πQ × quantity. The handbook's other factors aren't applied; "
                     "real rates depend on them, and quality alone can move a rate by a factor of 10 or more."),
        },
        "records": records,
        "sources": list(sources.values()),
        "warnings": warnings,
    }


def _source(source_id: str) -> dict:
    src = next((s for s in library_service.sources()["sources"] if s["id"] == source_id), None)
    if src is None:
        return {"id": source_id}
    return {k: src.get(k) for k in ("id", "name", "short_name", "report", "edition", "url", "caveats")} | {
        "attribution": (src.get("licence") or {}).get("attribution"),
        "licence": (src.get("licence") or {}).get("name"),
    }


# ---- a product's parts list ------------------------------------------------------------------

def lines_from_structure(structure: dict) -> tuple[list[dict], list[str]]:
    """The lines a part's structure (``Maintenance.part_structure``) gives: each
    lowest-level part a line with the quantity in one of the top part and the
    parts above it as its assembly path; parts that hold parts are
    assemblies, not lines. Returns (lines, warnings)."""
    lines: list[dict] = []
    warnings: list[str] = []

    def walk(node: dict, path: list[str]) -> None:
        if node.get("more"):
            warnings.append(f"The structure under {node.get('name') or node.get('part_number')} was cut short: "
                            "some parts are missing from this list.")
        for child in node.get("children") or []:
            label = child.get("name") or child.get("part_number") or "Part"
            if child.get("children"):
                walk(child, path + [label])
            else:
                lines.append({"name": label, "reference": child.get("part_number") or "",
                              "quantity": child.get("total") if child.get("total") is not None else 1,
                              "assembly": list(path), "record_id": None,
                              "quality_factor": DEFAULT_QUALITY_FACTOR})

    walk(structure.get("tree") or {}, [])
    return lines, warnings


def lines_from_product(m, product_id: str) -> dict:
    """A product's parts list as prediction lines: the bill of materials of
    the product's part (``Maintenance.part_structure``), flattened to its
    lowest-level parts under their assemblies. ``m`` is the caller's
    Maintenance; its NotFound and Invalid pass through."""
    product = m.product(product_id)
    out = {"product": {"id": product["id"], "name": product["name"], "rev": product.get("rev") or None,
                       "part_number": (product.get("part") or {}).get("part_number")},
           "lines": [], "assemblies": 0, "warnings": []}
    part = product.get("part")
    if not part:
        out["warnings"].append(f"{product['name']} has no part yet, so no parts list: give the product a part with "
                               "a bill of materials, or type the parts list here.")
        return out
    structure = m.part_structure(part["id"])
    lines, warnings = lines_from_structure(structure)
    out["lines"] = lines
    out["assemblies"] = len({tuple(ln["assembly"][:d]) for ln in lines for d in range(1, len(ln["assembly"]) + 1)})
    out["warnings"] = warnings
    if not lines:
        out["warnings"].append(f"Nothing is inside {part['part_number']} yet: add what goes in it on the part's page, "
                               "or type the parts list here.")
    return out


# ---- saved predictions -----------------------------------------------------------------------

def _list_query(owner_id, shared=frozenset()):
    query = {"owner_id": {"$in": access.owner_in(owner_id)}}
    if shared:
        return {"$or": [query, {"_id": {"$in": sorted(shared)}}]}
    return query


def _name(name: Any) -> str:
    text = " ".join(str(name or "").split())
    if not text:
        raise PredictionError("The prediction needs a name.")
    return text[:NAME_LENGTH]


def results_for(inputs: dict) -> dict:
    """A saved prediction's results: the computation, with the product it was
    made from (so another prediction can find it by product id)."""
    results = compute(inputs["lines"], inputs["environment"], inputs["mission_time"])
    if inputs.get("product"):
        results["product"] = dict(inputs["product"])
    return results


def save_prediction(db, name: str, inputs: dict, owner_id: str) -> ReliabilityPrediction:
    """Save a prediction: its inputs checked, its results computed here."""
    name = _name(name)
    inputs = normalise_inputs(inputs)
    results = results_for(inputs)
    doc = ReliabilityPrediction(id=uuid.uuid4().hex, name=name, owner_id=owner_id, inputs=inputs, results=results)
    db[COLLECTION].insert_one(to_doc(doc))
    return doc


def list_predictions(db, owner_id, hidden=frozenset(), shared=frozenset()) -> list[ReliabilityPrediction]:
    return [from_doc(ReliabilityPrediction, d)
            for d in db[COLLECTION].find(_list_query(owner_id, shared)).sort("created_at", -1)
            if d["_id"] not in hidden]


def get_prediction(db, prediction_id: str, owner_id=None) -> ReliabilityPrediction | None:
    query: dict = {"_id": prediction_id}
    if owner_id is not None:
        query["owner_id"] = {"$in": access.owner_in(owner_id)}
    return from_doc(ReliabilityPrediction, db[COLLECTION].find_one(query))


def update_prediction(db, prediction_id: str, owner_id: str, name=None, inputs=None) -> ReliabilityPrediction:
    """Rename one of the owner's own predictions, or replace its inputs (the
    results are computed again). A sample or another's is not found."""
    doc = get_prediction(db, prediction_id, owner_id)
    if doc is None or doc.owner_id != owner_id:
        raise PredictionNotFound(prediction_id)
    changes: dict = {}
    if name is not None:
        doc.name = changes["name"] = _name(name)
    if inputs is not None:
        doc.inputs = changes["inputs"] = normalise_inputs(inputs)
        doc.results = changes["results"] = results_for(doc.inputs)
    if not changes:
        return doc
    doc.updated_at = changes["updated_at"] = _now()
    db[COLLECTION].update_one({"_id": prediction_id, "owner_id": owner_id}, {"$set": changes})
    return doc


def delete_prediction(db, prediction_id: str, owner_id: str) -> None:
    if db[COLLECTION].delete_one({"_id": prediction_id, "owner_id": owner_id}).deleted_count == 0:
        raise PredictionNotFound(prediction_id)


# ---- words for lists --------------------------------------------------------------------------

def fmt_sig(value: float | None, digits: int = 3) -> str:
    """A number to ``digits`` significant figures with thousands separators;
    '—' for none."""
    if value is None or not isinstance(value, (int, float)) or not math.isfinite(value):
        return "—"
    v = float(value)
    if v == 0:
        return "0"
    rounded = float(f"{v:.{digits}g}")
    if abs(rounded) >= 1000:
        return f"{rounded:,.0f}"
    return f"{rounded:g}"


def headline(doc: ReliabilityPrediction) -> str:
    """'2.08 per 10⁶ h · MTBF 481,000 h' for a list row."""
    r = doc.results or {}
    rate = r.get("failure_rate_per_million_hours")
    if not rate:
        return "No part types assigned yet"
    return f"{fmt_sig(rate)} per million hours · MTBF {fmt_sig(r.get('mtbf_hours'))} h"


def brief(doc: ReliabilityPrediction) -> dict:
    """A saved prediction as a list row (no access fields: the router adds
    is_sample and read_only)."""
    r = doc.results or {}
    counts = r.get("counts") or {}
    env = r.get("environment") or {}
    return {
        "id": doc.id, "name": doc.name, "headline": headline(doc),
        "environment": env.get("code"), "environment_name": env.get("name"),
        "lines": counts.get("lines"), "assigned": counts.get("assigned"), "parts": counts.get("parts"),
        "failure_rate_per_million_hours": r.get("failure_rate_per_million_hours"),
        "failure_rate_per_hour": r.get("failure_rate_per_hour"),
        "mtbf_hours": r.get("mtbf_hours"),
        "mission_time_hours": r.get("mission_time_hours"),
        "reliability_at_mission": r.get("reliability_at_mission"),
        "product": (doc.inputs or {}).get("product"),
        "updated_by": (doc.updated_by or {}).get("name"),
        "created_at": doc.created_at.isoformat(),
        "updated_at": doc.updated_at.isoformat(),
    }
