"""Maintainability prediction: how long corrective maintenance takes, from a
parts list and the time each repair takes, element by element.

The method is the handbook one (MIL-HDBK-472 style), in plain words:

* each line of the parts list is a thing that can fail and be repaired; its
  repair time is the sum of its elements (fault isolation, access, remove and
  replace, reassemble and restore, check out), its MTTR;
* each line counts by how often it's the thing being repaired: its failure
  rate times its quantity (λ·q). With no failure rates every line counts the
  same, and the result says so;
* the system's mean corrective maintenance time (Mct) is the weighted mean of
  the lines' MTTRs: Σ(λ·q·MTTR) / Σ(λ·q);
* M_max is the time by which a chosen share of repairs (95% by default) is
  done. Each line's repair time is taken as lognormal with its MTTR as the
  mean and the spread the user gave (sigma, or the time that share of its
  repairs is done by); the system's repair-time distribution is the mix of
  the lines', each weighted by λ·q, and M_max is that mix's percentile, found
  numerically. A line with no spread counts as always taking its MTTR; with no
  spread on any line, M_max isn't available;
* inherent availability A_i = MTBF / (MTBF + Mct), when the failure rates give
  a system MTBF (1 / Σλ·q), or one is typed in;
* the Pareto: each line's share of the maintenance time, λ·q·MTTR / Σ.

Saved predictions keep the inputs and the results computed from them at save
time (never results from the client), owner-scoped like the other stores
(:mod:`backend.services.strategy_store`).
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone

from backend.db import from_doc, to_doc
from backend.schema import MaintainabilityPrediction
from backend.services import access

COLLECTION = "maintainability_predictions"

MAX_LINES = 500
MAX_NAME = 200
MAX_SIGMA = 3.0
MIN_PERCENTILE, MAX_PERCENTILE = 0.5, 0.999

#: The elements of a repair, in the order they happen, with the words the app
#: and the results use.
ELEMENTS = (
    ("isolation", "Fault isolation"),
    ("access", "Access (disassembly)"),
    ("replace", "Remove and replace"),
    ("restore", "Reassemble and restore"),
    ("checkout", "Check out and align"),
)
ELEMENT_KEYS = tuple(k for k, _ in ELEMENTS)

#: Repair-time units and how many hours each is.
UNITS = {"minutes": 1.0 / 60.0, "hours": 1.0}
#: Failure-rate units and how many per hour each is.
RATE_UNITS = {"per_million_hours": 1e-6, "per_hour": 1.0}
RATE_UNIT_TEXT = {"per_million_hours": "per million hours", "per_hour": "per hour"}

#: What may stand between the names of an assembly path; the first is the one shown.
_SEPARATORS = "›>/\\»"


class MaintainabilityError(ValueError):
    """A refused input, said plainly."""


class PredictionNotFound(KeyError):
    """An unknown, hidden or not-owned prediction id."""


# ---- the numbers ---------------------------------------------------------------------------

def _num(value, what: str, lo: float | None = None, hi: float | None = None, allow_none: bool = False):
    if value is None or value == "":
        if allow_none:
            return None
        raise MaintainabilityError(f"{what} is needed.")
    try:
        x = float(value)
    except (TypeError, ValueError):
        raise MaintainabilityError(f"{what} must be a number.") from None
    if not math.isfinite(x):
        raise MaintainabilityError(f"{what} must be a finite number.")
    if lo is not None and x < lo:
        raise MaintainabilityError(f"{what} can't be less than {lo:g}.")
    if hi is not None and x > hi:
        raise MaintainabilityError(f"{what} can't be more than {hi:g}.")
    return x


def _text(value, what: str, limit: int = MAX_NAME) -> str:
    text = " ".join(str(value if value is not None else "").split())
    if len(text) > limit:
        raise MaintainabilityError(f"{what} is too long (at most {limit} characters).")
    return text


def assembly_path(text) -> list[str]:
    """"Propulsion › Motor 1" (or with / or >) as its names, top first."""
    # Plain string splitting, so the time taken grows only with the text's length.
    text = " ".join(str(text or "").split())
    for sep in _SEPARATORS[1:]:
        text = text.replace(sep, _SEPARATORS[0])
    return [p.strip() for p in text.split(_SEPARATORS[0]) if p.strip()]


def _z(p: float) -> float:
    from scipy.special import ndtri

    return float(ndtri(p))


def _phi(x: float) -> float:
    from scipy.special import ndtr

    return float(ndtr(x))


def sigma_from_maximum(mean: float, maximum: float, p: float) -> float:
    """The lognormal sigma whose mean is ``mean`` and whose ``p``-quantile is
    ``maximum``: ln(max/mean) = z·σ − σ²/2, the smaller root."""
    if maximum <= mean:
        raise MaintainabilityError("the time most repairs are done by must be more than the MTTR.")
    z = _z(p)
    ratio = math.log(maximum / mean)
    disc = z * z - 2.0 * ratio
    if disc < 0:
        most = math.exp(z * z / 2.0)
        raise MaintainabilityError(
            f"at {p:.0%} a lognormal repair time can't be more than about {most:.1f}× its MTTR; "
            "lower it, or give sigma instead.")
    return z - math.sqrt(disc)


def _line_cdf(line: dict, t: float) -> float:
    """P(this line's repair is done by t)."""
    sigma = line["sigma"]
    if not sigma:
        return 1.0 if t >= line["mttr"] else 0.0
    if t <= 0:
        return 0.0
    return _phi((math.log(t) - line["mu"]) / sigma)


def mixture_quantile(lines: list[dict], weights: list[float], p: float) -> float:
    """The p-quantile of the mix of the lines' repair times (each a lognormal,
    or a point at its MTTR with no spread), by bisection."""
    total = sum(weights)

    def cdf(t: float) -> float:
        return sum(w * _line_cdf(ln, t) for ln, w in zip(lines, weights)) / total

    lo = 0.0
    hi = max(ln["mttr"] for ln in lines)
    while cdf(hi) < p:
        hi *= 2.0
        if hi > 1e12:  # pragma: no cover - defensive
            break
    for _ in range(200):
        mid = (lo + hi) / 2.0
        if cdf(mid) >= p:
            hi = mid
        else:
            lo = mid
        if hi - lo <= 1e-9 * max(hi, 1.0):
            break
    return hi


# ---- the inputs ----------------------------------------------------------------------------

def _line(raw, i: int, unit: str, p: float) -> dict:
    """One line checked: its name, quantity, elements and spread."""
    if not isinstance(raw, dict):
        raise MaintainabilityError(f"Line {i + 1} must be an object (name, elements, …).")
    ref = _text(raw.get("ref"), f"line {i + 1}'s ref", 80)
    name = _text(raw.get("name"), f"line {i + 1}'s name")
    if not name and not ref:
        raise MaintainabilityError(f"Line {i + 1} needs a name (or a ref such as its part number).")
    label = name or ref
    quantity = _num(raw.get("quantity", 1), f"{label}: quantity", lo=0, hi=1e6)
    if quantity is None:
        quantity = 1.0
    elements_in = raw.get("elements") or {}
    if not isinstance(elements_in, dict):
        raise MaintainabilityError(f"{label}: elements must be an object of times, e.g. {{'isolation': 10}}.")
    unknown = sorted(set(elements_in) - set(ELEMENT_KEYS))
    if unknown:
        raise MaintainabilityError(f"{label}: unknown repair element {', '.join(unknown)} "
                                   f"(the elements are {', '.join(ELEMENT_KEYS)}).")
    elements = {}
    for key, word in ELEMENTS:
        v = _num(elements_in.get(key), f"{label}: {word.lower()}", lo=0, hi=1e6, allow_none=True)
        if v is not None:
            elements[key] = v
    if elements:
        mttr = sum(elements.values())
        if raw.get("mttr") not in (None, ""):
            typed = _num(raw.get("mttr"), f"{label}: MTTR", lo=0)
            if abs(typed - mttr) > 1e-6 * max(1.0, mttr):
                raise MaintainabilityError(f"{label}: its MTTR ({typed:g}) isn't the sum of its elements "
                                           f"({mttr:g} {unit}); give one or the other.")
    else:
        mttr = _num(raw.get("mttr"), f"{label}: MTTR (or its repair elements)", lo=0, hi=1e6)
    if quantity > 0 and mttr <= 0:
        raise MaintainabilityError(f"{label}: the repair time must be more than 0 {unit}.")
    rate = _num(raw.get("failure_rate"), f"{label}: failure rate", lo=0, hi=1e12, allow_none=True)
    sigma = _num(raw.get("sigma"), f"{label}: sigma", lo=0, hi=MAX_SIGMA, allow_none=True)
    maximum = _num(raw.get("maximum"), f"{label}: the time most repairs are done by", lo=0, hi=1e7,
                   allow_none=True)
    if sigma is not None and maximum is not None:
        raise MaintainabilityError(f"{label}: give sigma or the time most repairs are done by, not both.")
    if sigma == 0:
        sigma = None
    if maximum is not None and mttr > 0:
        try:
            sigma = sigma_from_maximum(mttr, maximum, p)
        except MaintainabilityError as exc:
            raise MaintainabilityError(f"{label}: {exc}") from None
    return {
        "ref": ref, "name": name, "label": label,
        "assembly": assembly_path(raw.get("assembly")),
        "quantity": quantity, "failure_rate": rate, "mttr": mttr, "elements": elements,
        "sigma": sigma, "maximum": maximum,
        "mu": (math.log(mttr) - sigma * sigma / 2.0) if (sigma and mttr > 0) else None,
    }


def check_inputs(inputs: dict) -> dict:
    """The inputs as compute() uses them, every one checked."""
    if not isinstance(inputs, dict):
        raise MaintainabilityError("The inputs must be an object.")
    unit = str(inputs.get("unit") or "hours").strip().lower()
    if unit not in UNITS:
        raise MaintainabilityError("unit must be minutes or hours.")
    rate_unit = str(inputs.get("failure_rate_unit") or "per_million_hours").strip().lower()
    if rate_unit not in RATE_UNITS:
        raise MaintainabilityError("failure_rate_unit must be per_million_hours or per_hour.")
    p = _num(inputs.get("percentile", 0.95), "percentile", lo=MIN_PERCENTILE, hi=MAX_PERCENTILE)
    raw_lines = inputs.get("lines")
    if not isinstance(raw_lines, list) or not raw_lines:
        raise MaintainabilityError("Give at least one line: {name, quantity?, failure_rate?, elements or mttr}.")
    if len(raw_lines) > MAX_LINES:
        raise MaintainabilityError(f"At most {MAX_LINES} lines in one prediction.")
    lines = [_line(raw, i, unit, p) for i, raw in enumerate(raw_lines)]
    if not any(ln["quantity"] > 0 for ln in lines):
        raise MaintainabilityError("Every line has quantity 0: nothing to repair.")
    mtbf = _num(inputs.get("mtbf"), "MTBF", lo=1e-9, allow_none=True)
    return {
        "unit": unit, "failure_rate_unit": rate_unit, "percentile": p, "lines": lines, "mtbf": mtbf,
        "product_id": _text(inputs.get("product_id"), "product_id", 80) or None,
        "product_name": _text(inputs.get("product_name"), "product_name") or None,
    }


# ---- the computation -----------------------------------------------------------------------

def _rates_note(source: str, missing: list[str], prediction: dict | None, rate_unit: str) -> str | None:
    if source == "equal":
        if missing:
            shown = ", ".join(missing[:5]) + (", …" if len(missing) > 5 else "")
            return (f"{len(missing)} line{'s have' if len(missing) != 1 else ' has'} no failure rate ({shown}), "
                    "so every line counts the same. Give a rate for each line, or a saved reliability "
                    "prediction for the product, to weight them and to get availability.")
        return "No failure rates were given, so every line counts the same."
    if source == "reliability_prediction" and prediction:
        return f"Failure rates come from the reliability prediction “{prediction.get('name')}”."
    if source == "mixed" and prediction:
        return (f"Failure rates come from the reliability prediction “{prediction.get('name')}” where a line "
                "matches it, else as typed.")
    return f"Failure rates as typed, {RATE_UNIT_TEXT[rate_unit]}."


def compute(inputs: dict, prediction: dict | None = None) -> dict:
    """The results for ``inputs`` (see the module docstring). ``prediction``:
    a saved reliability prediction's rates for the same product
    ({id, name, rates: {ref or name (lower-case): rate}, unit}), used for
    the lines that match it and have no rate typed."""
    chk = check_inputs(inputs)
    unit, rate_unit, p, lines = chk["unit"], chk["failure_rate_unit"], chk["percentile"], chk["lines"]
    to_hours = UNITS[unit]
    rate_per_hour = RATE_UNITS[rate_unit]

    # Each line's failure rate, in the inputs' unit: typed, else the reliability prediction's.
    found = 0
    pred_rates = (prediction or {}).get("rates") or {}
    pred_unit = (prediction or {}).get("unit")
    pred_factor = (RATE_UNITS.get(pred_unit, rate_per_hour) / rate_per_hour) if pred_rates else 1.0
    for ln in lines:
        ln["rate_source"] = "typed" if ln["failure_rate"] is not None else None
        if ln["failure_rate"] is None and pred_rates:
            for key in (ln["ref"], ln["name"]):
                hit = pred_rates.get(key.lower()) if key else None
                if hit is not None:
                    ln["failure_rate"] = float(hit) * pred_factor
                    ln["rate_source"] = "reliability_prediction"
                    found += 1
                    break
    counted = [ln for ln in lines if ln["quantity"] > 0]
    missing = [ln["label"] for ln in counted if ln["failure_rate"] is None]
    typed = sum(1 for ln in counted if ln["rate_source"] == "typed")
    if missing:
        source = "equal"
    elif found and typed:
        source = "mixed"
    elif found:
        source = "reliability_prediction"
    else:
        source = "typed"
    rated = source != "equal"
    for ln in lines:
        ln["weight"] = (ln["failure_rate"] if rated else 1.0) * ln["quantity"]
    total_w = sum(ln["weight"] for ln in lines)
    if total_w <= 0:
        raise MaintainabilityError("Every line's failure rate is 0: nothing fails, so there's nothing to repair. "
                                   "Leave the rates out to weight the lines equally.")

    # Mean corrective maintenance time, and where the time goes.
    mct = sum(ln["weight"] * ln["mttr"] for ln in lines) / total_w
    total_time = sum(ln["weight"] * ln["mttr"] for ln in lines)
    elements = {}
    split_time = 0.0
    for key, word in ELEMENTS:
        t = sum(ln["weight"] * ln["elements"].get(key, 0.0) for ln in lines) / total_w
        split_time += t
        elements[key] = {"label": word, "time": t, "share": (t / mct) if mct > 0 else 0.0}
    unsplit = max(mct - split_time, 0.0)
    if unsplit > 1e-9 * max(mct, 1.0):
        elements["unsplit"] = {"label": "Not split into elements", "time": unsplit, "share": unsplit / mct}

    # M_max: the mix's percentile.
    with_spread = [ln for ln in lines if ln["sigma"] and ln["weight"] > 0]
    without = [ln for ln in lines if not ln["sigma"] and ln["weight"] > 0]
    z = _z(p)
    m_max = None
    m_max_note = None
    if with_spread:
        used = [ln for ln in lines if ln["weight"] > 0]
        m_max = mixture_quantile(used, [ln["weight"] for ln in used], p)
        if without:
            m_max_note = (f"{len(without)} line{'s have' if len(without) != 1 else ' has'} no spread and "
                          f"count{'' if len(without) != 1 else 's'} as always taking their MTTR, so M_max may "
                          "be low. Give each line a spread for a full answer.")
    else:
        m_max_note = ("M_max needs a spread on the lines: sigma, or the time most repairs of the line are "
                      "done by. Without one the lines' repair times are points, and only Mct is known.")

    # Availability, from the rates (or a typed MTBF).
    system_rate = sum(ln["failure_rate"] * ln["quantity"] for ln in lines) if rated else None
    mtbf_hours = chk["mtbf"]
    mtbf_source = "typed" if mtbf_hours is not None else None
    if mtbf_hours is None and system_rate:
        mtbf_hours = 1.0 / (system_rate * rate_per_hour)
        mtbf_source = "rates"
    mct_hours = mct * to_hours
    availability = None
    availability_note = None
    if mtbf_hours:
        availability = mtbf_hours / (mtbf_hours + mct_hours)
    elif system_rate == 0:
        availability_note = "Every failure rate is 0, so there's no MTBF to set availability against."
    else:
        availability_note = ("Inherent availability needs the system's MTBF: give a failure rate on every line "
                             "(or a saved reliability prediction for the product), or type the MTBF in hours.")

    # The Pareto and the roll-up by assembly.
    out_lines = []
    for i, ln in enumerate(lines):
        share = (ln["weight"] * ln["mttr"] / total_time) if total_time > 0 else 0.0
        out_lines.append({
            "ref": ln["ref"], "name": ln["name"], "assembly": " › ".join(ln["assembly"]),
            "quantity": ln["quantity"], "failure_rate": ln["failure_rate"], "rate_source": ln["rate_source"],
            "mttr": ln["mttr"], "elements": dict(ln["elements"]), "sigma": ln["sigma"],
            "m_max": (math.exp(ln["mu"] + z * ln["sigma"]) if ln["sigma"] else None),
            "weight": ln["weight"], "share": share, "index": i,
        })
    pareto = sorted((dict(x) for x in out_lines if x["weight"] > 0), key=lambda x: (-x["share"], x["index"]))
    running = 0.0
    for row in pareto:
        running += row["share"]
        row["cumulative"] = min(running, 1.0)
    assemblies: dict[tuple, dict] = {}
    for ln in lines:
        for depth in range(1, len(ln["assembly"]) + 1):
            key = tuple(ln["assembly"][:depth])
            a = assemblies.setdefault(key, {"path": " › ".join(key), "level": depth, "lines": 0, "weight": 0.0,
                                            "time": 0.0, "failure_rate": 0.0 if rated else None})
            a["lines"] += 1
            a["weight"] += ln["weight"]
            a["time"] += ln["weight"] * ln["mttr"]
            if rated:
                a["failure_rate"] += ln["failure_rate"] * ln["quantity"]
    rollup = []
    for key in sorted(assemblies):
        a = assemblies[key]
        rollup.append({
            "path": a["path"], "level": a["level"], "lines": a["lines"], "failure_rate": a["failure_rate"],
            "mct": (a["time"] / a["weight"]) if a["weight"] > 0 else None,
            "share": (a["time"] / total_time) if total_time > 0 else 0.0,
        })

    return {
        "unit": unit, "failure_rate_unit": rate_unit, "percentile": p,
        "product": ({"id": chk["product_id"], "name": chk["product_name"]} if chk["product_id"] else None),
        "weights": {"source": source, "note": _rates_note(source, missing, prediction, rate_unit),
                    "prediction": ({"id": prediction.get("id"), "name": prediction.get("name")}
                                   if prediction and found else None),
                    "missing": missing},
        "mct": mct, "mct_hours": mct_hours, "elements": elements,
        "m_max": m_max, "m_max_note": m_max_note,
        "mtbf_hours": mtbf_hours, "mtbf_source": mtbf_source,
        "system_failure_rate": system_rate, "availability": availability, "availability_note": availability_note,
        "lines": out_lines, "pareto": pareto, "assemblies": rollup,
        "counts": {"lines": len(lines), "with_rates": sum(1 for ln in counted if ln["failure_rate"] is not None),
                   "with_spread": len(with_spread)},
    }


# ---- failure rates from a saved reliability prediction -------------------------------------

_RATE_KEYS = ("failure_rate", "lambda", "rate")
_NAME_KEYS = ("ref", "part_number", "reference", "name", "part", "label")


def prediction_rates(db, product_id, owners) -> dict | None:
    """The failure rates a saved reliability prediction holds for ``product_id``
    (the newest one of the caller's or the samples'), keyed by the line's ref
    and name, lower-case: {id, name, rates, unit}. None when there's no such
    prediction, or the collection isn't there. Its shape isn't ours, so this
    reads what it can and never fails."""
    if not product_id:
        return None
    try:
        docs = list(db["reliability_predictions"].find(
            {"owner_id": {"$in": list(owners)}}).sort("updated_at", -1).limit(100))
    except Exception:  # noqa: BLE001 - another feature's collection: never block this one
        return None
    for doc in docs:
        inputs = doc.get("inputs") if isinstance(doc.get("inputs"), dict) else {}
        results = doc.get("results") if isinstance(doc.get("results"), dict) else {}
        pid = doc.get("product_id") or inputs.get("product_id") or (results.get("product") or {}).get("id")
        if str(pid or "") != str(product_id):
            continue
        rows = results.get("lines") or inputs.get("lines") or doc.get("lines") or []
        rates: dict[str, float] = {}
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            rate = next((row[k] for k in _RATE_KEYS if isinstance(row.get(k), (int, float))), None)
            if rate is None or not math.isfinite(float(rate)):
                continue
            for k in _NAME_KEYS:
                key = " ".join(str(row.get(k) or "").split()).lower()
                if key:
                    rates.setdefault(key, float(rate))
        if not rates:
            continue
        unit = next((x for x in (doc.get("failure_rate_unit"), inputs.get("failure_rate_unit"),
                                 results.get("failure_rate_unit"), results.get("rate_unit"))
                     if isinstance(x, str) and x in RATE_UNITS), None)
        return {"id": doc.get("_id"), "name": doc.get("name") or "reliability prediction", "rates": rates,
                "unit": unit}
    return None


# ---- lines from a product ------------------------------------------------------------------

def product_lines(m, product_id: str) -> dict:
    """A product's parts list as prediction lines: every lowest-level part of
    its part's structure, with how many go into one product and the
    assemblies it sits in. ``m`` is the workspace's Maintenance."""
    product = m.product(product_id)
    part = product.get("part")
    if not part:
        return {"product": {"id": product["id"], "name": product["name"]}, "part": None, "lines": [],
                "note": "This product has no part yet, so it has no parts list: give it one on its page, or "
                        "type the lines here."}
    structure = m.part_structure(part["id"])
    lines: list[dict] = []

    def walk(node: dict, path: list[str]) -> None:
        children = node.get("children") or []
        for child in children:
            if child.get("children"):
                walk(child, [*path, child.get("name") or child.get("part_number") or ""])
            else:
                lines.append({"ref": child.get("part_number") or "", "name": child.get("name") or "",
                              "assembly": " › ".join(p for p in path if p), "quantity": child.get("total") or 1,
                              "level": child.get("level") or ""})

    walk(structure.get("tree") or {}, [])
    return {"product": {"id": product["id"], "name": product["name"]},
            "part": {"id": part["id"], "part_number": part.get("part_number", ""), "name": part.get("name", "")},
            "lines": lines, "note": None if lines else "The product's part has nothing in it yet: add what goes "
                                                        "in it on the part's page, or type the lines here."}


# ---- the store -----------------------------------------------------------------------------

def _now():
    return datetime.now(timezone.utc)


def _list_query(owner_id, shared=frozenset()):
    query = {"owner_id": {"$in": access.owner_in(owner_id)}}
    if shared:
        return {"$or": [query, {"_id": {"$in": sorted(shared)}}]}
    return query


def headline(doc: MaintainabilityPrediction) -> str:
    """One line for the list: 'Mct 2.5 hours · M_max 6.1 hours · A 99.9%'."""
    r = doc.results or {}
    unit = r.get("unit") or "hours"
    parts = []
    if r.get("mct") is not None:
        parts.append(f"Mct {fmt_num(r['mct'])} {unit}")
    if r.get("m_max") is not None:
        parts.append(f"M_max {fmt_num(r['m_max'])} {unit}")
    if r.get("availability") is not None:
        parts.append(f"A {r['availability'] * 100:.4g}%")
    return " · ".join(parts) or "Maintainability prediction"


def fmt_num(x) -> str:
    """3 to 4 significant figures, no exponent for everyday sizes."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(v):
        return "—"
    if v == 0:
        return "0"
    a = abs(v)
    if a < 0.001 or a >= 1e7:
        return f"{v:.3g}"
    digits = 4 if a >= 100 else 3
    return f"{v:,.{max(digits - 1 - math.floor(math.log10(a)), 0)}f}"


def save_prediction(db, name: str, inputs: dict, owner_id: str, prediction: dict | None = None,
                    ) -> MaintainabilityPrediction:
    name = _text(name, "the name")
    if not name:
        raise MaintainabilityError("The prediction needs a name.")
    results = compute(inputs or {}, prediction)
    doc = MaintainabilityPrediction(id=uuid.uuid4().hex, name=name, owner_id=owner_id, inputs=inputs or {},
                                    results=results)
    db[COLLECTION].insert_one(to_doc(doc))
    return doc


def list_predictions(db, owner_id, hidden=frozenset(), shared=frozenset()) -> list[MaintainabilityPrediction]:
    return [from_doc(MaintainabilityPrediction, d)
            for d in db[COLLECTION].find(_list_query(owner_id, shared)).sort("created_at", -1)
            if d["_id"] not in hidden]


def get_prediction(db, prediction_id: str, owner_id=None) -> MaintainabilityPrediction | None:
    query: dict = {"_id": prediction_id}
    if owner_id is not None:
        query["owner_id"] = {"$in": access.owner_in(owner_id)}
    return from_doc(MaintainabilityPrediction, db[COLLECTION].find_one(query))


def update_prediction(db, prediction_id: str, owner_id: str, name=None, inputs=None,
                      prediction: dict | None = None) -> MaintainabilityPrediction:
    """Rename a prediction, or give it new inputs (its results are recomputed)."""
    doc = get_prediction(db, prediction_id, owner_id)
    if doc is None or doc.owner_id != owner_id:
        raise PredictionNotFound(prediction_id)
    changes: dict = {}
    if name is not None:
        text = _text(name, "the name")
        if not text:
            raise MaintainabilityError("The prediction needs a name.")
        changes["name"] = doc.name = text
    if inputs is not None:
        doc.results = changes["results"] = compute(inputs, prediction)
        doc.inputs = changes["inputs"] = inputs
    if not changes:
        raise MaintainabilityError("Nothing to change: give a name or new inputs.")
    doc.updated_at = changes["updated_at"] = _now()
    db[COLLECTION].update_one({"_id": prediction_id, "owner_id": owner_id}, {"$set": changes})
    return doc


def delete_prediction(db, prediction_id: str, owner_id: str) -> None:
    if db[COLLECTION].delete_one({"_id": prediction_id, "owner_id": owner_id}).deleted_count == 0:
        raise PredictionNotFound(prediction_id)
