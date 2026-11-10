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

Where the failure rates come from. A line's rate is typed with it, or, when
the prediction is for a product (or position) that has a saved parts count (a
reliability prediction), read from that: the rate of one part, matched by
part number and never by name. A typed rate always wins and is shown as the
prediction's own; a line left blank takes the parts count's and follows it.
The results say which lines did which, and how the MTBF here compares with
the parts count's, with the reason when the two differ.

Saved predictions keep the inputs and the results computed from them at save
time (never results from the client), owner-scoped like the other stores
(:mod:`backend.services.strategy_store`). A prediction whose lines take the
parts count's rates is worked out again when it is read, if that parts count
has changed since (:func:`current`); one that uses only its own rates keeps
the results it was saved with.
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

#: How close two rates or MTBFs must be to read as the same at the figures shown.
_SAME = 5e-4


def ref_key(text) -> str:
    """A part number as lines are matched by it: lower-case, spaces squeezed."""
    return " ".join(str(text or "").split()).lower()


def _some(labels: list[str], most: int = 5) -> str:
    return ", ".join(labels[:most]) + (", …" if len(labels) > most else "")


def _count(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def _rates_note(source: str, missing: list[str], prediction: dict | None, rate_unit: str,
                tally: dict | None = None, product_name: str | None = None, has_product: bool = False,
                ) -> str | None:
    """Where the failure rates come from, in a line."""
    tally = tally or {}
    count = f"the parts count “{prediction.get('name')}”" if prediction else None
    if source == "equal":
        if not missing:
            return "No failure rates were given, so every line counts the same."
        head = (f"{len(missing)} line{'s have' if len(missing) != 1 else ' has'} no failure rate "
                f"({_some(missing)}), so every line counts the same.")
        if count:
            return (f"{head} {count[0].upper()}{count[1:]} has no rate for {'them' if len(missing) != 1 else 'it'} "
                    "(lines are matched by part number): type a rate for each, or give the parts count one, to "
                    "weight the lines and to get availability.")
        return (f"{head} Give a rate for each line, or a saved reliability prediction for the product, to "
                "weight them and to get availability.")
    if source == "reliability_prediction" and count:
        return (f"Every line's failure rate comes from {count}, matched by part number, and follows it when "
                "it changes.")
    if source == "mixed" and count:
        typed = tally.get("typed") or []
        return (f"{_count(tally.get('taken') or 0, 'line takes its', 'lines take their')} failure rate from "
                f"{count}, matched by part number, and {_count(len(typed), 'line uses', 'lines use')} a rate "
                f"typed here ({_some(typed)}).")
    own = f"This prediction uses its own failure rates, typed here ({RATE_UNIT_TEXT[rate_unit]})."
    if count:
        have = tally.get("available") or 0
        if have and tally.get("same") == have:
            return (f"{own} {count[0].upper()}{count[1:]} has a rate for {have} of these "
                    f"{_count(len(tally.get('typed') or []), 'line', 'lines')}, and the rates typed here are "
                    "the same.")
        if have:
            return (f"{own} {count[0].upper()}{count[1:]} has a rate for {have} of these "
                    f"{_count(len(tally.get('typed') or []), 'line', 'lines')}: clear a line's typed rate to "
                    "take it from there.")
        return (f"{own} {count[0].upper()}{count[1:]} has no rate for any of these lines (they are matched "
                "by part number).")
    if has_product:
        return (f"{own} There is no saved parts count (reliability prediction) for "
                f"{product_name or 'the product'} to take them from.")
    return own


def compute(inputs: dict, prediction: dict | None = None) -> dict:
    """The results for ``inputs`` (see the module docstring). ``prediction``:
    the saved parts count for the same product, as :func:`prediction_rates`
    gives it ({id, name, rates: {part number, lower-case: one part's rate},
    unit, …}). A line with no rate typed takes the rate of its part number
    there; a typed rate is kept and the parts count's shown beside it."""
    chk = check_inputs(inputs)
    unit, rate_unit, p, lines = chk["unit"], chk["failure_rate_unit"], chk["percentile"], chk["lines"]
    to_hours = UNITS[unit]
    rate_per_hour = RATE_UNITS[rate_unit]

    # Each line's failure rate, in the inputs' unit: typed, else the parts count's for its part number.
    found = 0
    pred_rates = (prediction or {}).get("rates") or {}
    pred_unit = (prediction or {}).get("unit")
    pred_factor = (RATE_UNITS.get(pred_unit, rate_per_hour) / rate_per_hour) if prediction else 1.0
    for ln in lines:
        key = ref_key(ln["ref"])
        hit = pred_rates.get(key) if key else None
        ln["parts_count_rate"] = float(hit) * pred_factor if hit is not None else None
        ln["rate_source"] = "typed" if ln["failure_rate"] is not None else None
        if ln["failure_rate"] is None and ln["parts_count_rate"] is not None:
            ln["failure_rate"] = ln["parts_count_rate"]
            ln["rate_source"] = "reliability_prediction"
            found += 1
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
            "parts_count_rate": ln["parts_count_rate"],
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

    tally, parts_count, compare = _against_parts_count(prediction, counted, mtbf_hours, mtbf_source,
                                                        pred_factor)
    return {
        "unit": unit, "failure_rate_unit": rate_unit, "percentile": p,
        "product": ({"id": chk["product_id"], "name": chk["product_name"]} if chk["product_id"] else None),
        "weights": {"source": source,
                    "note": _rates_note(source, missing, prediction, rate_unit, tally, chk["product_name"],
                                        bool(chk["product_id"])),
                    "prediction": ({"id": prediction.get("id"), "name": prediction.get("name")}
                                   if prediction and found else None),
                    "missing": missing, "parts_count": parts_count, "compare": compare},
        "mct": mct, "mct_hours": mct_hours, "elements": elements,
        "m_max": m_max, "m_max_note": m_max_note,
        "mtbf_hours": mtbf_hours, "mtbf_source": mtbf_source,
        "system_failure_rate": system_rate, "availability": availability, "availability_note": availability_note,
        "lines": out_lines, "pareto": pareto, "assemblies": rollup,
        "counts": {"lines": len(lines), "with_rates": sum(1 for ln in counted if ln["failure_rate"] is not None),
                   "with_spread": len(with_spread)},
    }


def _against_parts_count(prediction: dict | None, counted: list[dict], mtbf_hours, mtbf_source, factor: float,
                         ) -> tuple[dict, dict | None, dict | None]:
    """How the lines stand against the product's parts count: the tally the
    note is written from, the ``parts_count`` block of the results (None with
    no parts count) and the MTBF comparison (None when either has no MTBF)."""
    if not prediction:
        return {}, None, None
    taken = [ln["label"] for ln in counted if ln["rate_source"] == "reliability_prediction"]
    typed = [ln for ln in counted if ln["rate_source"] == "typed"]
    replaced, same, not_in = [], [], []
    for ln in typed:
        theirs = ln["parts_count_rate"]
        if theirs is None:
            not_in.append(ln["label"])
        elif abs(ln["failure_rate"] - theirs) <= _SAME * max(theirs, 1e-300):
            same.append(ln["label"])
        else:
            replaced.append(ln["label"])
    ours: dict[str, float] = {}
    for ln in counted:
        key = ref_key(ln["ref"])
        if key:
            ours[key] = ours.get(key, 0.0) + ln["quantity"]
    extra = [row["label"] for row in prediction.get("lines") or [] if row.get("key") not in ours]
    quantities = prediction.get("quantities") or {}
    labels = {ref_key(ln["ref"]): ln["label"] for ln in reversed(counted)}
    differ = [labels[key] for key in ours
              if key in quantities and abs(quantities[key] - ours[key]) > 1e-9 * max(ours[key], 1.0)]
    tally = {"taken": len(taken), "typed": [ln["label"] for ln in typed], "available": len(replaced) + len(same),
             "same": len(same)}
    total = prediction.get("failure_rate")
    theirs_mtbf = prediction.get("mtbf_hours")
    parts_count = {
        "id": prediction.get("id"), "name": prediction.get("name"), "stamp": prediction.get("stamp"),
        "failure_rate": (total * factor) if isinstance(total, (int, float)) else None,
        "mtbf_hours": theirs_mtbf, "taken": len(taken), "typed_over": replaced, "typed_same": same,
        "not_in": not_in, "extra": extra, "quantities_differ": differ,
    }
    compare = None
    if mtbf_hours and theirs_mtbf:
        agree = abs(mtbf_hours - theirs_mtbf) <= _SAME * theirs_mtbf
        reasons: list[str] = []
        if not agree:
            if mtbf_source == "typed":
                reasons.append("the MTBF here was typed in, in place of 1 ÷ the summed failure rates")
            else:
                if replaced:
                    reasons.append(f"{_count(len(replaced), 'line uses', 'lines use')} a rate typed here in place "
                                   f"of the parts count's ({_some(replaced)})")
                if not_in:
                    reasons.append(f"{_count(len(not_in), 'line has', 'lines have')} a rate typed here and none "
                                   f"in the parts count ({_some(not_in)})")
                if extra:
                    reasons.append(f"the parts count has {_count(len(extra), 'line that is', 'lines that are')} "
                                   f"not in this list ({_some(extra)})")
                if differ:
                    reasons.append(f"the quantities differ for {_some(differ)}")
                if not reasons:
                    reasons.append("the two were worked out from different lines")
        note = (f"The MTBF, {fmt_num(mtbf_hours)} hours, agrees with the parts count's." if agree else
                f"The MTBF here is {fmt_num(mtbf_hours)} hours; the parts count gives {fmt_num(theirs_mtbf)} "
                f"hours. They differ because {'; '.join(reasons)}.")
        compare = {"mtbf_hours": mtbf_hours, "parts_count_mtbf_hours": theirs_mtbf, "agree": agree,
                   "reasons": reasons, "note": note}
    return tally, parts_count, compare


# ---- failure rates from a saved parts count (a reliability prediction) ----------------------

_REF_KEYS = ("reference", "ref", "part_number")


def _number(x) -> float | None:
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(float(x)):
        return None
    return float(x)


def _reliability_docs(db, owners) -> list[dict]:
    """The readers' saved reliability predictions, newest first. Another
    feature's collection: an unreadable one is none, never an error here."""
    try:
        return list(db["reliability_predictions"].find(
            {"owner_id": {"$in": list(owners)}}).sort("updated_at", -1).limit(100))
    except Exception:  # noqa: BLE001 - never block this feature on that one
        return []


def _is_for(doc: dict, product_id) -> bool:
    """Whether a saved reliability prediction is the parts count of this
    product: made from its parts list (``inputs.product``), or on the product
    as a position (``inputs.position``; a product's id is its design
    position's)."""
    inputs = doc.get("inputs") if isinstance(doc.get("inputs"), dict) else {}
    results = doc.get("results") if isinstance(doc.get("results"), dict) else {}
    ids = [doc.get("product_id"), inputs.get("product_id")]
    for holder in (inputs.get("product"), inputs.get("position"), results.get("product")):
        if isinstance(holder, dict):
            ids.append(holder.get("id"))
    return str(product_id) in {str(x) for x in ids if x}


def prediction_rates(db, product_id, owners, docs: list[dict] | None = None) -> dict | None:
    """The parts count saved for ``product_id`` (a product, or the position it
    was made on): the newest of the readers' reliability predictions for it.
    None when there is none.

    {id, name, stamp, unit: "per_million_hours", rates: {part number
    (lower-case): the failure rate of ONE part}, quantities: {part number: how
    many the parts count has}, lines: [{key, label, total}] for every line
    with a rate (key "" with no part number), unrated: [names with no rate
    there], failure_rate (the whole count's, per million hours), mtbf_hours}.

    Lines are matched by part number only: names repeat ("Chip resistors"
    under three boards), so a name alone never picks a rate. A part number on
    several lines gets its parts' mean rate. Its shape isn't ours, so this
    reads what it can and never fails."""
    if not product_id:
        return None
    for doc in (docs if docs is not None else _reliability_docs(db, owners)):
        if not isinstance(doc, dict) or not _is_for(doc, product_id):
            continue
        results = doc.get("results") if isinstance(doc.get("results"), dict) else {}
        rows = results.get("lines")
        if not isinstance(rows, list) or not rows:
            continue
        sums: dict[str, list[float]] = {}
        lines, unrated = [], []
        for row in rows:
            if not isinstance(row, dict):
                continue
            ref = next((" ".join(str(row.get(k)).split()) for k in _REF_KEYS if str(row.get(k) or "").strip()), "")
            label = " ".join(str(row.get("name") or "").split()) or ref or "a line"
            quantity = _number(row.get("quantity"))
            quantity = 1.0 if quantity is None else quantity
            total = _number(row.get("rate_per_million_hours"))
            each = _number(row.get("each_per_million_hours"))
            if total is None and each is not None:
                total = each * quantity
            if total is None or row.get("excluded") or quantity <= 0:
                unrated.append(label)
                continue
            key = ref_key(ref)
            if key:
                held = sums.setdefault(key, [0.0, 0.0])
                held[0] += total
                held[1] += quantity
            lines.append({"key": key, "label": label, "total": total})
        return {
            "id": doc.get("_id"), "name": doc.get("name") or "reliability prediction",
            "stamp": str(doc.get("updated_at") or ""), "unit": "per_million_hours",
            "rates": {key: held[0] / held[1] for key, held in sums.items()},
            "quantities": {key: held[1] for key, held in sums.items()},
            "lines": lines, "unrated": unrated,
            "failure_rate": _number(results.get("failure_rate_per_million_hours")),
            "mtbf_hours": _number(results.get("mtbf_hours")),
        }
    return None


def follows_parts_count(results: dict | None) -> bool:
    """Whether saved results have lines that took a parts count's rates (and
    say which parts count): those are worked out again when it changes."""
    held = ((results or {}).get("weights") or {}).get("parts_count")
    return isinstance(held, dict) and bool(held.get("taken"))


def current(db, doc, owners, docs: list[dict] | None = None):
    """``doc`` with its results as they stand now. A prediction that uses only
    its own rates (and any saved before lines could follow a parts count) is
    returned as saved. One whose lines take a parts count's rates is worked
    out again, in memory, when that parts count has changed or been replaced;
    if the parts count can't be found the saved figures stay and say so."""
    if doc is None or not follows_parts_count(doc.results):
        return doc
    weights = doc.results["weights"]
    was = weights["parts_count"]
    now = prediction_rates(db, (doc.inputs or {}).get("product_id"), owners, docs)
    if now is None:
        doc.results = {**doc.results, "weights": {**weights, "as_saved": (
            "The parts count these failure rates came from can't be found now, so the figures are as they were "
            "when this prediction was last saved.")}}
        return doc
    if now.get("id") == was.get("id") and now.get("stamp") == was.get("stamp"):
        return doc
    try:
        doc.results = compute(doc.inputs, now)
    except MaintainabilityError:
        pass  # keep the saved figures
    return doc


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


def list_predictions(db, owner_id, hidden=frozenset(), shared=frozenset(), rate_owners=None,
                     ) -> list[MaintainabilityPrediction]:
    """The saved predictions, each with its results as they stand now
    (:func:`current`; ``rate_owners``: whose parts counts may be read,
    by default the same owners)."""
    out = [from_doc(MaintainabilityPrediction, d)
           for d in db[COLLECTION].find(_list_query(owner_id, shared)).sort("created_at", -1)
           if d["_id"] not in hidden]
    following = [d for d in out if follows_parts_count(d.results)]
    if following:
        owners = rate_owners if rate_owners is not None else access.owner_in(owner_id)
        docs = _reliability_docs(db, owners)
        for doc in following:
            current(db, doc, owners, docs)
    return out


def get_prediction(db, prediction_id: str, owner_id=None, as_saved: bool = False,
                   ) -> MaintainabilityPrediction | None:
    """One saved prediction, with its results as they stand now
    (:func:`current`) unless ``as_saved``."""
    query: dict = {"_id": prediction_id}
    if owner_id is not None:
        query["owner_id"] = {"$in": access.owner_in(owner_id)}
    doc = from_doc(MaintainabilityPrediction, db[COLLECTION].find_one(query))
    if doc is not None and owner_id is not None and not as_saved:
        current(db, doc, access.owner_in(owner_id))
    return doc


def update_prediction(db, prediction_id: str, owner_id: str, name=None, inputs=None,
                      prediction: dict | None = None) -> MaintainabilityPrediction:
    """Rename a prediction, or give it new inputs (its results are recomputed)."""
    doc = get_prediction(db, prediction_id, owner_id, as_saved=True)
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
