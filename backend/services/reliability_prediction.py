"""Reliability prediction: a parts-count estimate of a design's failure rate
from handbook base rates, before there is any failure data.

A parts list is lines, each a part with how many there are and a handbook part
type (a record of the reliability data library whose basis is a prediction
model: MIL-HDBK-217F). A line's failure rate is

    λ = λb × πE × πQ × quantity

the handbook's base failure rate for that part type, its environment factor
for where the equipment works (one environment for the whole prediction), a
quality factor the user sets per line (1 unless they say otherwise) and the
quantity. A parts-count part type (the handbook's Appendix A: microcircuits,
motors, circuit boards, crystals and so on) gives its generic rate for the
environment instead, environment included: λ = λg × πQ × quantity, where πQ
is the record's default grade (commercial or non-MIL, the lowest the handbook
lists) unless the line gives one.

A mechanical part can take an NSWC-11 component (the Navy's mechanical
handbook, a library of covariate models): its rate is the component's total
under the line's ``conditions`` (the model's inputs, by key; a missing one
takes the handbook's default), times the quantity. It has no environment or
quality factor: the conditions are its environment. A model whose rate is per
million cycles or operations needs ``cycles_per_hour`` to become a rate per
hour. A line whose conditions are incomplete or past a limit the handbook sets
is listed with what it needs and left out of the total, like a line with no
part type, so a preview still computes.

Two kinds of line need no part type. A part the handbook has no type for
(it has no batteries) can carry a rate the user gives,
``rate_per_million_hours`` per part, shown as user-given. A part that isn't
electronic (an airframe, a propeller) can be ``excluded``: it's listed as left
out, and the result says so, so a bill of materials with mechanical lines
still computes for its electronics. The system is every part in series with a constant rate: the rates
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
from backend.library import record_covariates
from backend.library import service as library_service
from backend.schema import ReliabilityPrediction
from backend.services import access

COLLECTION = "reliability_predictions"
#: The library sources a parts count draws on: MIL-HDBK-217F for electronic parts, NSWC-11 (covariate
#: models) for mechanical ones.
HANDBOOK_SOURCE = "mil-hdbk-217f-n2"
MECHANICAL_SOURCE = "nswc-11"
HANDBOOK_SOURCES = (HANDBOOK_SOURCE, MECHANICAL_SOURCE)
MAX_CONDITIONS = 200
MAX_CYCLES_PER_HOUR = 1e7
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
#: Applied too, when a line uses one.
GENERIC = {"symbol": "λg", "name": "generic failure rate for the environment (parts count, Appendix A)"}
USER_GIVEN = {"symbol": "λ", "name": "a rate you gave (user-given, not from the handbook)"}
METHOD = "Parts count: λ = Σ λb × πE × πQ × quantity over the lines (every part in series); R(t) = exp(−λt)."
def method_text(electronic: list[str], mechanical: list[str], generic: bool) -> str:
    """The method in words when NSWC-11 lines are in: which lines used which handbook."""
    def names(xs: list[str]) -> str:
        return ", ".join(xs[:8]) + (f" and {len(xs) - 8} more" if len(xs) > 8 else "")

    parts = ["Parts count: λ = Σ over the lines (every part in series); R(t) = exp(−λt)."]
    if electronic:
        parts.append(f"MIL-HDBK-217F N2 lines ({names(electronic)}): λb × πE × πQ × quantity"
                     + (", or λg × πQ × quantity for a part type with generic rates." if generic else "."))
    if mechanical:
        parts.append(f"NSWC-11 lines ({names(mechanical)}): the component's covariate model (base rate × condition "
                     "factors, summed over its parts) under the line's conditions × quantity; a rate per cycle × "
                     "the cycles an hour.")
    return " ".join(parts)


METHOD_GENERIC = ("Parts count: λ = Σ λb × πE × πQ × quantity over the lines, or λg × πQ × quantity for a "
                  "part type with the handbook's generic rates (every part in series); R(t) = exp(−λt).")
#: A rate a user gives, per million hours: above 0 and at most this.
MAX_USER_RATE = 1e6
EXCLUDED_NOTE = "Not an electronic part: left out."


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


def _flag(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def normalise_lines(lines: Any) -> list[dict]:
    """The lines as the calculation (and a saved prediction) keeps them:
    name, reference, quantity, assembly (a path), record_id and
    quality_factor (None: the part type's default), each checked; and, when
    given, rate_per_million_hours (a rate the user gives, per part, for a
    part with no handbook type) or excluded (not an electronic part: left
    out). Raises :class:`PredictionError`."""
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
        q = raw.get("quality_factor")
        line = {
            "name": name,
            "reference": _text(raw.get("reference"), "reference", TEXT_LENGTH),
            "quantity": _number(raw.get("quantity"), "quantity", name, 0, MAX_QUANTITY, default=1.0),
            "assembly": assembly_path(raw.get("assembly")),
            "record_id": record_id,
            "quality_factor": None if q is None or q == "" else _number(q, "quality_factor (πQ)", name, 0, 1e4),
        }
        user_rate = raw.get("rate_per_million_hours")
        if user_rate is not None and user_rate != "":
            if record_id:
                raise PredictionError(f"'{name}': give a handbook part type or a rate of your own, not both.")
            line["rate_per_million_hours"] = _number(user_rate, "rate_per_million_hours", name, 0, MAX_USER_RATE)
            if line["quality_factor"] is not None:
                raise PredictionError(f"'{name}': a rate you give has no quality factor; leave quality_factor out.")
        if _flag(raw.get("excluded")):
            if record_id or "rate_per_million_hours" in line:
                raise PredictionError(f"'{name}': a line left out (not an electronic part) can't also have a part "
                                      "type or a rate.")
            line["excluded"] = True
        for k in ("environment", "quality"):  # a saved line's own covariates, read back as they were kept
            if raw.get(k) not in (None, "") and record_id:
                raw = {**raw, "covariates": {**(raw.get("covariates") or {}), k: raw[k]}}
        covs = raw.get("covariates")
        if covs not in (None, {}, ""):
            # The line's covariates, the one mechanism's names (backend/library/record_covariates.py):
            # a handbook part's environment (this line's own, over the prediction's) and quality grade
            # or πQ; an NSWC-11 part's conditions and cycles an hour. Kept in the fields below.
            if not isinstance(covs, dict):
                raise PredictionError(f"'{name}': covariates must be an object of covariate to value.")
            if not record_id:
                raise PredictionError(f"'{name}': covariates go with a handbook part type (record_id).")
            covs = {k: v for k, v in covs.items() if v is not None and v != ""}
            if "environment" in covs:
                line["environment"] = environment_code(covs.pop("environment"))
            if "quality" in covs:
                line["quality"] = _text(covs.pop("quality"), "quality grade", TEXT_LENGTH)
            if "quality_factor" in covs:
                if line["quality_factor"] is not None:
                    raise PredictionError(f"'{name}': give quality_factor once.")
                line["quality_factor"] = _number(covs.pop("quality_factor"), "quality_factor (πQ)", name, 0, 1e4)
            if "cycles_per_hour" in covs and raw.get("cycles_per_hour") in (None, ""):
                raw = {**raw, "cycles_per_hour": covs.pop("cycles_per_hour")}
            if covs:
                raw = {**raw, "conditions": {**(raw.get("conditions") or {}), **covs}}
        conditions = raw.get("conditions")
        if conditions not in (None, {}, ""):
            if not record_id:
                raise PredictionError(f"'{name}': conditions go with an NSWC-11 part type (record_id).")
            line["conditions"] = _conditions(conditions, name)
        cph = raw.get("cycles_per_hour")
        if cph is not None and cph != "":
            if not record_id:
                raise PredictionError(f"'{name}': cycles_per_hour goes with an NSWC-11 part type (record_id).")
            line["cycles_per_hour"] = _number(cph, "cycles_per_hour", name, 0, MAX_CYCLES_PER_HOUR)
        if raw.get("notes"):
            line["notes"] = _text(raw.get("notes"), "notes", 500)
        out.append(line)
    return out


def _conditions(value: Any, name: str) -> dict:
    """A line's conditions for an NSWC-11 model: {input key: number or choice code}, kept as given
    (the model checks them against its limits when it's evaluated)."""
    if not isinstance(value, dict):
        raise PredictionError(f"'{name}': conditions must be an object of input to value, e.g. "
                              "{\"L_S\": 5000, \"bearing_type\": \"ball\"}.")
    if len(value) > MAX_CONDITIONS:
        raise PredictionError(f"'{name}': at most {MAX_CONDITIONS} conditions.")
    out: dict[str, Any] = {}
    for key, v in value.items():
        k = str(key).strip()[:TEXT_LENGTH]
        if not k or v is None or v == "":
            continue
        if isinstance(v, bool):
            raise PredictionError(f"'{name}': condition {k} must be a number or a choice, not true or false.")
        if isinstance(v, (int, float)):
            if not math.isfinite(v):
                raise PredictionError(f"'{name}': condition {k} must be a finite number.")
            out[k] = float(v)
        elif isinstance(v, str):
            text = v.strip()[:TEXT_LENGTH]
            try:
                num = float(text)
                out[k] = num if math.isfinite(num) else text
            except ValueError:
                out[k] = text
        else:
            raise PredictionError(f"'{name}': condition {k} must be a number or a choice.")
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
                              f"type (source {HANDBOOK_SOURCE}, or {MECHANICAL_SOURCE} for a mechanical part).") from None
    if rec.get("basis") != "prediction_model" or not (rec.get("prediction") or rec.get("kind") == "covariate_model"):
        raise PredictionError(f"'{line_name}': '{rec['label']}' is {rec.get('basis', 'field data').replace('_', ' ')}, "
                              f"not a handbook part type. A parts count uses handbook base rates: search the "
                              f"library with source {HANDBOOK_SOURCE} (or {MECHANICAL_SOURCE}).")
    return rec


def _quality_range(rec: dict) -> tuple[list | None, bool]:
    """The handbook's πQ range for the record, and whether its model has a
    quality factor at all."""
    pred = rec.get("prediction") or {}
    rng = pred.get("quality_factor_range")
    has = bool(rng) or any(f.get("symbol") == "πQ" for f in pred.get("not_applied") or [])
    return (list(rng) if rng else None), has


def _line_rate(rec: dict, code: str, line_name: str) -> tuple[float, float | None]:
    """A line's rate per part before quality, per million hours, for the environment: (the
    rate, πE or None). A part stress record: λb × πE (πE None when its model has none). A
    parts-count record: its generic rate λg for the environment, environment included (πE
    None)."""
    if rec.get("generic_rates"):
        _environment_factor(rec, code, line_name)  # raises for an environment it has no rate for
        return float(rec["generic_rates"]["values"][code]), None
    base = float(rec["prediction"]["per_million_hours"])
    pi_e = _environment_factor(rec, code, line_name)
    return base * (pi_e if pi_e is not None else 1.0), pi_e


def _environment_factor(rec: dict, code: str, line_name: str) -> float | None:
    """The record's πE for the environment; None when the handbook's model for
    this part has no environment factor (a few parts). For a parts-count record
    (generic rates by environment), the environment's rate over the record's
    own value, so the value × it is the environment's generic rate. An
    environment the handbook gives nothing for raises :class:`PredictionError`."""
    if rec.get("generic_rates"):
        from backend.library import convert

        values = rec["generic_rates"]["values"]
        if code not in values:
            raise PredictionError(f"'{line_name}': the handbook gives no {code} "
                                  f"({library_schema.ENVIRONMENTS[code][0].lower()}) rate for '{rec['name']}': it "
                                  f"marks the part not normally used there. It has {convert.environment_choices(rec)}.")
        return convert.generic_rate(rec, code)["factor"]
    factors = rec.get("environment_factors")
    if not factors:
        return None
    values = factors.get("values") or {}
    if code not in values:
        from backend.library import convert

        raise PredictionError(f"'{line_name}': the handbook gives no {code} ({library_schema.ENVIRONMENTS[code][0].lower()}) "
                              f"factor for '{rec['name']}'. It has {convert.environment_choices(rec)}.")
    return float(values[code])


# ---- an NSWC-11 line (a covariate model) -------------------------------------------------------

def _covariate_line(rec: dict, line: dict) -> dict:
    """An NSWC-11 line's rate per part, per million hours, under its conditions: {each, result,
    warnings} or {problems} (what it needs before it counts)."""
    from backend.library import covariate

    conditions = line.get("conditions") or {}
    try:
        result = covariate.evaluate(rec, conditions, library_service.resolve)
    except covariate.CovariateError as exc:
        return {"problems": exc.problems}
    problems = []
    each = result["total"]
    cph = line.get("cycles_per_hour")
    if covariate.per_cycle(rec):
        if cph is None:
            problems.append(f"Its rate is {covariate.rate_unit_words(rec)}: give how many "
                            f"{'operations' if 'operations' in result['unit'] else 'cycles'} it makes an hour "
                            "(cycles_per_hour) to turn it into a rate per hour.")
        else:
            each = result["total"] * cph  # per million cycles × cycles an hour = per million hours
    if problems:
        return {"problems": problems}
    return {"each": each, "result": result, "warnings": result.pop("warnings")}


def _covariate_summary(rec: dict, line: dict, got: dict) -> dict:
    """What a line shows of its NSWC-11 model: each mode's rate, the conditions used (defaults
    filled), the unit, and the handbook's equation."""
    r = got.get("result") or {}
    return {
        "equation": (rec.get("covariate_model") or {}).get("equation"),
        "unit": (rec.get("units") or {}).get("value"), "unit_words": (rec.get("units") or {}).get("as_given"),
        "cycles_per_hour": line.get("cycles_per_hour"),
        "total_in_unit": r.get("total"),
        "modes": [{"key": m["key"], "name": m.get("name"), "rate": m["rate"]} for m in r.get("modes") or []],
        "conditions": line.get("conditions") or {},
        "problems": got.get("problems") or [],
        "warnings": got.get("warnings") or [],
    }


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
        "lines": len(under), "assigned": sum(1 for ln in under if ln["assigned"]),
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
    held: dict[str, dict] = {}
    records: dict[str, dict] = {}
    sources: dict[str, dict] = {}
    used_generic = used_user = False
    mechanical: list[str] = []  # the lines on an NSWC-11 model
    needing: list[str] = []  # NSWC-11 lines whose conditions aren't complete yet
    for line in inputs["lines"]:
        row = {**line, "assembly_label": _label(line["assembly"]), "excluded": bool(line.get("excluded")),
               "user_given": False, "generic_rate": False, "handbook": None}
        if line.get("excluded") or (not line["record_id"] and "rate_per_million_hours" not in line):
            row.update({"assigned": False, "part_type": None, "category": None, "base_rate_per_million_hours": None,
                        "environment_factor": None, "quality_factor_range": None, "each_per_million_hours": None,
                        "rate_per_million_hours": None, "rate_per_hour": None, "share": None, "not_applied": [],
                        "line_warnings": [EXCLUDED_NOTE if line.get("excluded")
                                          else "No handbook part type: left out of the total."]})
            out_lines.append(row)
            continue
        if not line["record_id"]:  # a rate the user gave, per part
            used_user = True
            each = line["rate_per_million_hours"]
            rate = each * line["quantity"]
            row.update({
                "assigned": True, "user_given": True,
                "part_type": "Rate you gave (user-given)", "part_type_label": "A rate you gave, not from the handbook",
                "category": "Rates you gave", "equipment_type": None, "section": None,
                "base_rate_per_million_hours": each, "environment_factor": None, "quality_factor": None,
                "quality_factor_source": "none", "quality_factor_range": None,
                "each_per_million_hours": each, "rate_per_million_hours": rate, "rate_per_hour": rate / PER_MILLION,
                "failure_rate": rate, "failure_rate_unit": "per_million_hours", "share": None,
                "applied": [USER_GIVEN["symbol"]], "not_applied": [],
                "line_warnings": ["User-given rate: not from the handbook, and not changed by the environment."],
            })
            out_lines.append(row)
            continue
        rec = _record(line["record_id"], line["name"])
        if rec.get("kind") == "covariate_model":
            if line["quality_factor"] is not None:
                raise PredictionError(f"'{line['name']}': an NSWC-11 model has no quality factor; leave "
                                      "quality_factor out.")
            got = _covariate_line(rec, line)
            cov = _covariate_summary(rec, line, got)
            sources.setdefault(rec["source"], _source(rec["source"]))
            mechanical.append(line["name"])
            records[rec["id"]] = {"label": rec["label"], "version": rec["version"], "source": rec["source"],
                                  "citation": _citation(rec)}
            base_row = {"part_type": rec["name"], "part_type_label": rec["label"], "handbook": "NSWC-11",
                        "category": library_schema.EQUIPMENT_TYPES.get(rec["equipment_type"], rec["equipment_type"]),
                        "equipment_type": rec["equipment_type"],
                        "section": (rec.get("conditions") or {}).get("section") or rec.get("source_code"),
                        "environment_factor": None, "quality_factor": None, "quality_factor_source": "none",
                        "quality_factor_range": None, "covariate": cov, "not_applied": []}
            if got.get("problems"):
                needs = "; ".join(got["problems"])
                row.update({**base_row, "assigned": False, "needs_conditions": True,
                            "base_rate_per_million_hours": None, "each_per_million_hours": None,
                            "rate_per_million_hours": None, "rate_per_hour": None, "share": None,
                            "line_warnings": [f"Needs its conditions before it counts: {needs}"]})
                needing.append(line["name"])
                out_lines.append(row)
                continue
            each = got["each"]
            rate = each * line["quantity"]
            line_warnings = list(got["warnings"])
            row.update({**base_row, "assigned": True, "needs_conditions": False,
                        "base_rate_per_million_hours": each, "each_per_million_hours": each,
                        "rate_per_million_hours": rate, "rate_per_hour": rate / PER_MILLION,
                        "failure_rate": rate, "failure_rate_unit": "per_million_hours", "share": None,
                        "applied": ["λ (covariate model)"], "line_warnings": line_warnings})
            warnings.extend(f"'{line['name']}': {w}" for w in line_warnings)
            out_lines.append(row)
            continue
        pred = rec["prediction"]
        generic = bool(rec.get("generic_rates"))
        used_generic = used_generic or generic
        # The line's covariates (backend/library/record_covariates.py): its environment (its own, else
        # the prediction's), its quality grade or πQ. The factors are the one mechanism's; the
        # arithmetic is the parts count's own, so saved predictions give the same numbers.
        line_code = line.get("environment") or code
        base, pi_e = _line_rate(rec, line_code, line["name"])
        q_range, has_q = _quality_range(rec)
        if line.get("quality"):
            levels = [lv["code"] for lv in (rec.get("quality_factors") or {}).get("levels") or []]
            if not levels:
                raise PredictionError(f"'{line['name']}': '{rec['name']}' has no quality grades; give quality_factor "
                                      "(πQ) as a number.")
            if line["quality"] not in levels:
                raise PredictionError(f"'{line['name']}': the quality grade is one of {', '.join(levels)}.")
        hf = record_covariates.handbook_factors(rec, {"quality": line.get("quality"),
                                                      "quality_factor": line["quality_factor"]})
        pi_q, q_source, q_level = hf["pi_q"], hf["quality_source"], hf["quality_level"]
        row["covariates"] = {"environment": line_code, **({"quality": hf["quality_code"]} if hf["quality_code"] else {}),
                             **({"quality_factor": pi_q} if q_source == "given" and not hf["quality_code"] else {})}
        row["covariates_from"] = {"environment": "line" if line.get("environment") else "prediction",
                                  **({"quality": "given" if line.get("quality") else "default"}
                                     if hf["quality_code"] else {})}
        line_warnings: list[str] = []
        if not has_q and pi_q != DEFAULT_QUALITY_FACTOR:
            raise PredictionError(f"'{line['name']}': the handbook's model for '{rec['name']}' has no quality "
                                  f"factor; leave quality_factor out (or at 1).")
        if q_range and not (q_range[0] <= pi_q <= q_range[1]):
            line_warnings.append(f"πQ {pi_q:g} is outside the handbook's {q_range[0]:g}–{q_range[1]:g} for "
                                 f"{rec['name']}.")
        if pi_e is None and not generic:
            line_warnings.append(f"The handbook gives no environment factor for {rec['name']}: λb × πQ only.")
        each = base * pi_q
        rate = each * line["quantity"]
        if generic:
            left_out = []
            for f in pred.get("not_applied") or []:
                held.setdefault(f"{f['symbol']} {f['name']}", f)
        else:
            left_out = [f for f in pred.get("not_applied") or [] if f.get("symbol") != "πQ"]
            for f in left_out:  # the same symbol means different things in different sections (πC)
                not_applied.setdefault(f"{f['symbol']} {f['name']}", f)
        if generic:
            applied = ["λg"] + (["πQ"] if has_q else [])
        else:
            applied = [a["symbol"] for a in APPLIED if a["symbol"] != "πE" or pi_e is not None]
        row.update({
            "assigned": True, "generic_rate": generic,
            "part_type": rec["name"], "part_type_label": rec["label"],
            "category": library_schema.EQUIPMENT_TYPES.get(rec["equipment_type"], rec["equipment_type"]),
            "equipment_type": rec["equipment_type"],
            "section": (rec.get("conditions") or {}).get("section") or rec.get("source_code"),
            "base_rate_per_million_hours": base if generic else float(pred["per_million_hours"]),
            "environment_factor": pi_e,
            "quality_factor": pi_q, "quality_factor_source": q_source,
            **({"quality_level": q_level} if q_level else {}),
            "quality_factor_range": q_range,
            "each_per_million_hours": each,
            "rate_per_million_hours": rate, "rate_per_hour": rate / PER_MILLION,
            # The same rate under the name other predictions read it by (a maintainability
            # prediction weights its lines by these, matched by reference or name).
            "failure_rate": rate, "failure_rate_unit": "per_million_hours",
            "share": None,
            "applied": applied,
            "not_applied": left_out,
            **({"held_at_defaults": pred.get("not_applied") or []} if generic else {}),
            "line_warnings": line_warnings,
        })
        warnings.extend(f"'{line['name']}': {w}" for w in line_warnings)
        row["handbook"] = "MIL-HDBK-217F N2" if rec["source"] == HANDBOOK_SOURCE else rec["source"]
        records[rec["id"]] = {"label": rec["label"], "version": rec["version"], "source": rec["source"],
                              "citation": _citation(rec)}
        if rec["source"] not in sources:
            sources[rec["source"]] = _source(rec["source"])
        out_lines.append(row)

    assigned = [ln for ln in out_lines if ln["assigned"]]
    excluded = [ln for ln in out_lines if ln["excluded"]]
    pending = [ln for ln in out_lines if ln.get("needs_conditions")]
    unassigned = [ln for ln in out_lines if not ln["assigned"] and not ln["excluded"] and not ln.get("needs_conditions")]
    total = sum(ln["rate_per_million_hours"] for ln in assigned)
    for ln in assigned:
        ln["share"] = _share(ln["rate_per_million_hours"], total)
    if unassigned:
        names = ", ".join(f"{ln['name']} (×{ln['quantity']:g})" for ln in unassigned[:6])
        more = f" and {len(unassigned) - 6} more" if len(unassigned) > 6 else ""
        warnings.insert(0, f"{len(unassigned)} line{'s have' if len(unassigned) != 1 else ' has'} no handbook part "
                           f"type and {'are' if len(unassigned) != 1 else 'is'} left out of the total: {names}{more}.")
    if pending:
        names = ", ".join(ln["name"] for ln in pending[:6]) + (f" and {len(pending) - 6} more" if len(pending) > 6 else "")
        warnings.insert(0, f"{len(pending)} NSWC-11 line{'s need' if len(pending) != 1 else ' needs'} "
                           f"{'their' if len(pending) != 1 else 'its'} conditions before "
                           f"{'they count' if len(pending) != 1 else 'it counts'}, so "
                           f"{'they are' if len(pending) != 1 else 'it is'} left out of the total: {names}.")
    if not assigned:
        warnings.insert(0, "No line has a handbook part type yet, so there is no total.")
    left_out = None
    if excluded:
        names = ", ".join(f"{ln['name']} (×{ln['quantity']:g})" if ln["quantity"] != 1 else ln["name"]
                          for ln in excluded)
        left_out = (f"Left out as not electronic parts ({len(excluded)} {'lines' if len(excluded) != 1 else 'line'}): "
                    f"{names}. The handbook covers electronic parts only, so the total is for the electronics.")
    if used_user:
        warnings.append("Some lines use a rate you gave, not the handbook's: the result is only as good as those "
                        "rates.")

    by_category: dict[str, dict] = {}
    for ln in assigned:
        c = by_category.setdefault(ln["category"], {"rate": 0.0, "lines": 0, "parts": 0.0})
        c["rate"] += ln["rate_per_million_hours"]
        c["lines"] += 1
        c["parts"] += ln["quantity"]
    mtbf = PER_MILLION / total if total > 0 else None
    reliability = math.exp(-total / PER_MILLION * t) if total > 0 else None
    applied_list = [dict(a) for a in APPLIED] + ([dict(GENERIC)] if used_generic else []) + (
        [dict(USER_GIVEN)] if used_user else [])
    electronic = [ln["name"] for ln in assigned if ln.get("handbook") and ln.get("handbook") != "NSWC-11"]
    counted_mech = [ln["name"] for ln in assigned if ln.get("handbook") == "NSWC-11"]
    method = METHOD_GENERIC if used_generic else METHOD
    if mechanical:
        method = method_text(electronic, counted_mech, used_generic)
    handbooks = []
    if electronic:
        handbooks.append({"source": HANDBOOK_SOURCE, "short_name": "MIL-HDBK-217F N2", "lines": electronic})
    if counted_mech:
        handbooks.append({"source": MECHANICAL_SOURCE, "short_name": "NSWC-11", "lines": counted_mech})
    disclaimer = (sources.get(MECHANICAL_SOURCE) or {}).get("disclaimer") if mechanical else None
    return {
        "method": method,
        "handbooks": handbooks,
        **({"disclaimer": disclaimer} if disclaimer else {}),
        "environment": {"code": code, "name": env_name, "covers": env_covers},
        "mission_time_hours": t,
        "failure_rate_per_million_hours": total,
        "failure_rate_per_hour": total / PER_MILLION,
        "mtbf_hours": mtbf,
        "reliability_at_mission": reliability,
        "unreliability_at_mission": (1 - reliability) if reliability is not None else None,
        "counts": {"lines": len(out_lines), "assigned": len(assigned), "unassigned": len(unassigned),
                   **({"needs_conditions": len(pending)} if pending else {}),
                   "excluded": len(excluded),
                   "parts": _sig(sum(ln["quantity"] for ln in out_lines)),
                   "parts_assigned": _sig(sum(ln["quantity"] for ln in assigned))},
        "lines": out_lines,
        "unassigned": [{k: ln[k] for k in ("name", "reference", "quantity", "assembly")} for ln in unassigned],
        "needs_conditions": [{k: ln[k] for k in ("name", "reference", "quantity", "assembly")} for ln in pending],
        "excluded": [{k: ln[k] for k in ("name", "reference", "quantity", "assembly")} for ln in excluded],
        "left_out_note": left_out,
        "assemblies": _assembly_rows(out_lines),
        "pareto": {
            "by_line": _pareto([(ln["name"], ln["rate_per_million_hours"],
                                 {"part_type": ln["part_type"], "quantity": ln["quantity"],
                                  "assembly": ln["assembly_label"]}) for ln in assigned], total),
            "by_category": _pareto([(name, c["rate"], {"lines": c["lines"], "parts": _sig(c["parts"])})
                                    for name, c in by_category.items()], total),
        },
        "factors": {
            "applied": applied_list,
            "not_applied": [{"symbol": f["symbol"], "name": f["name"]} for f in not_applied.values()],
            "held_at_defaults": [{"symbol": f["symbol"], "name": f["name"], "held_at": f.get("held_at")}
                                 for f in held.values()],
            "quality_factor_default": DEFAULT_QUALITY_FACTOR,
            "note": ("Each line's rate is λb × πE × πQ × quantity (a parts-count part type: λg × πQ × quantity, "
                     "its generic rate holding the handbook's other factors at their defaults). The handbook's other "
                     "factors aren't applied; real rates depend on them, and quality alone can move a rate by a "
                     "factor of 10 or more."),
        },
        "records": records,
        "sources": list(sources.values()),
        "warnings": warnings,
    }


def _citation(rec: dict) -> str:
    c = rec["citation"]
    return f"{c.get('report') or c['title']}, {c['table']}, p. {c['page']}"


def _source(source_id: str) -> dict:
    src = next((s for s in library_service.sources()["sources"] if s["id"] == source_id), None)
    if src is None:
        return {"id": source_id}
    return {k: src.get(k) for k in ("id", "name", "short_name", "report", "edition", "url", "caveats")} | {
        "attribution": (src.get("licence") or {}).get("attribution"),
        "licence": (src.get("licence") or {}).get("name"),
        **({"disclaimer": src["disclaimer"]} if src.get("disclaimer") else {}),
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
                              "assembly": list(path), "record_id": None, "quality_factor": None})

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
