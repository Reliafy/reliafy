"""Lives on two clocks: parts that wear by two measures of use at once.

In plain words: a motor wears while it runs and every time it starts; an
aircraft part wears by flight hours and by landings; a press by hours and by
cycles. Two units with the same hours aren't equally worn if one made ten
times as many starts (or landings, cycles, shots, km). So the life is fitted
on one combined clock,

    combined age = first clock + k x second clock,

where ``k`` is what one unit of the second clock (one start, one landing) is
worth in the first clock's unit, learnt from the data together with the life
distribution on the combined clock. A unit used at a steady ``rate`` (second
clock per unit of the first) then ages ``1 + k x rate`` combined units per
unit, so its life on the first clock is an ordinary life model, with bounds
that carry the uncertainty in ``k``.

The second clock's unit is the user's ("cycles", "landings", "starts"): typed
on the dataset's reading (``x2_unit``), defaulted from the column's name, and
kept on the fit, the saved model and its ``to_dict``. A model saved before
the unit existed reads as "starts" (display only; nothing is rewritten).

Every number is SurPyval's (0.28): ``WeibullEquivalence.fit_from_df`` fits
it, and ``EquivalenceModel.at_usage(rate)`` gives the life at one rate (a
``LifeAtUsage``) that every life-model consumer takes. This module only
shapes those numbers for the app and the API.

Free: a two-clock fit is a numerical maximum-likelihood fit, like any other.
"""

from __future__ import annotations

import math
import re
from typing import Optional

import numpy as np
import pandas as pd
import surpyval as sp

from backend import levels
from backend.units import singular_unit, unit_in_text
from backend.warn_capture import collect_warnings, ignore_warnings

KIND = "two_clock"
#: The mapping key of the second clock's column (SurPyval's ``x2``).
X2 = "x2"
#: The second clock's unit: the reading's key, the fit option and form field.
UNIT_KEY = "x2_unit"
#: What a model saved before the second clock had a unit reads as (display only).
LEGACY_UNIT = "starts"
#: Second-clock units an operating plan supplies (its runs per hour).
RUN_UNITS = ("starts", "start", "runs", "run")

#: The fit picker's two-clock models: id -> (SurPyval fitter, name).
MODELS = {
    "weibull_two_clock": {"fitter": sp.WeibullEquivalence, "name": "Weibull on two clocks",
                          "base": "weibull", "dist": "Weibull"},
    "lognormal_two_clock": {"fitter": sp.LogNormalEquivalence, "name": "Lognormal on two clocks",
                            "base": "lognormal", "dist": "Lognormal"},
    "exponential_two_clock": {"fitter": sp.ExponentialEquivalence, "name": "Exponential on two clocks",
                              "base": "exponential", "dist": "Exponential"},
}
DEFAULT = "weibull_two_clock"
PARAM_WORDS = {"alpha": "characteristic life", "beta": "shape", "mu": "log-scale (mu)", "sigma": "spread (sigma)",
               "failure_rate": "failure rate"}
#: Mapping keys a two-clock fit can't take (said in words, never dropped).
_REFUSED = {"xl": "inspection ranges", "xr": "inspection ranges", "tr": "an observation end",
            "tl": "late entry", "i": "an item timeline", "e": "failure modes", "g": "groups",
            "group": "groups"}
MAX_RATE = 1e6


class TwoClockError(ValueError):
    """A request the two-clock fit or its use can't do, said in words."""


def is_two_clock(distribution: str) -> bool:
    return distribution in MODELS


def is_model(model) -> bool:
    """A fitted SurPyval two-clock model (``EquivalenceModel``)."""
    cls = getattr(sp, "EquivalenceModel", None)
    return cls is not None and isinstance(model, cls)


# ---- words and numbers ------------------------------------------------------------------

def _f(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def num(v) -> str:
    """A number for a sentence: 3-4 significant figures, thousands separated."""
    x = _f(v)
    if x is None:
        return "—"
    if x != 0 and (abs(x) < 0.001 or abs(x) >= 1e9):
        return f"{x:.3g}"
    sig = 4 if abs(x) >= 1000 else 3
    r = float(f"{x:.{sig}g}")
    return f"{r:,.0f}" if r == int(r) and abs(r) >= 1 else f"{r:,}"


_FILLER = {"no", "num", "number", "of", "count", "counts", "total", "cum", "cumulative", "n", "nr", "qty",
           "since", "new", "at", "failure", "to", "date", "the"}
_PLURAL_WORD = re.compile(r"^(.*?)([A-Za-z]{3,})$", re.S)


def plural_unit(unit) -> str:
    """A unit read for many: "cycle" → "cycles"; "cycles", "km", "kWh" and
    anything not a plain lower-case word stay as they are."""
    text = str(unit or "").strip()
    m = _PLURAL_WORD.match(text)
    if not m:
        return text
    word = m.group(2)
    if not word.islower() or word.endswith(("s", "x", "z", "ch", "sh", "y")) or word in ("km", "mm"):
        return text
    return m.group(1) + word + "s"


def clean_unit(unit) -> str:
    """The second clock's unit as typed, tidied: trimmed, at most 40
    characters, read for many ("cycle" → "cycles"); blank as blank."""
    text = " ".join(str(unit or "").split())[:40]
    return plural_unit(text) if text else ""


def default_unit(column) -> str:
    """The second clock's unit guessed from its column's name: "starts",
    "Landings" → "landings", "num_cycles" → "cycles", "Distance (km)" → "km";
    "uses" when the name says nothing."""
    name = str(column or "").strip()
    paren = re.search(r"\(([^()]+)\)\s*$", name)
    if paren:
        return clean_unit(paren.group(1).lower())
    words = [w for w in re.split(r"[^A-Za-z]+", re.sub(r"([a-z])([A-Z])", r"\1 \2", name).lower())
             if len(w) > 1 and w not in _FILLER]
    return clean_unit(" ".join(words[-2:])) if words else "uses"


def unit_of(model=None, results: Optional[dict] = None) -> str:
    """The second clock's unit of a fit, a saved model's results or a live
    model; "starts" for one saved before the unit existed."""
    for u in ((results or {}).get("second_unit"), getattr(model, "second_unit", None)):
        if u:
            return clean_unit(u)
    return LEGACY_UNIT


def clock_words(clocks, unit: str = "", second_unit: str = "") -> dict:
    """How to say the two clocks: the first in the model's unit ("hours"), the
    second in its own ("cycles"; "starts" when none was ever given)."""
    first, second = (list(clocks or ()) + ["x1", "x2"])[:2]
    first_word = unit_in_text(unit) or "hours"
    second_word = clean_unit(second_unit) or LEGACY_UNIT
    return {"first": str(first), "second": str(second), "first_word": first_word,
            "first_one": singular_unit(first_word) or first_word, "second_word": second_word,
            "second_one": singular_unit(second_word) or second_word,
            "rate_unit": f"{second_word} per {singular_unit(first_word) or first_word}"}


def words_of(model, unit: str = "", results: Optional[dict] = None) -> dict:
    """:func:`clock_words` for a live model (and its saved results)."""
    return clock_words(getattr(model, "clocks", None), unit or getattr(model, "unit", "") or "",
                       unit_of(model, results))


def results_words(results: Optional[dict]) -> dict:
    """:func:`clock_words` from a saved model's results alone."""
    r = results or {}
    c = r.get("clocks") or {}
    return clock_words([c.get("first") or "x1", c.get("second") or "x2"], r.get("unit") or "", unit_of(None, r))


def _plural(text: str, words: dict, which: str) -> str:
    return words[f"{which}_word"] if text != "1" else words[f"{which}_one"]


def rate_words(rate: float, words: dict) -> str:
    """"1 landing every 3 flight hours" (or "2.5 cycles per hour"; "no starts")."""
    r = _f(rate)
    if r is None or r <= 0:
        return f"no {words['second_word']}"
    every = 1.0 / r
    if every >= 1:
        return f"1 {words['second_one']} every {num(every)} {_plural(num(every), words, 'first')}"
    return f"{num(r)} {_plural(num(r), words, 'second')} per {words['first_one']}"


def rate_help(words: Optional[dict] = None) -> str:
    """"cycles per hour (0.125 is 1 cycle every 8 hours)"."""
    w = words or clock_words(None)
    return f"{w['rate_unit']} (0.125 is 1 {w['second_one']} every 8 {w['first_word']})"


def check_rate(rate, words: Optional[dict] = None) -> float:
    """A usage rate (the second clock per unit of the first), or TwoClockError."""
    r = _f(rate)
    if r is None:
        raise TwoClockError(f"Give the usage rate as a number: {rate_help(words)}." if words else
                            "Give the usage rate as a number: the second clock per unit of the first "
                            "(0.125 is 1 every 8).")
    if r < 0 or r > MAX_RATE:
        raise TwoClockError(f"The usage rate is {rate_help(words)}: 0 or more." if words else
                            "The usage rate is the second clock per unit of the first: 0 or more "
                            "(0.125 is 1 every 8).")
    return r


# ---- the data ---------------------------------------------------------------------------

def _column(df: pd.DataFrame, name: str, what: str) -> np.ndarray:
    if not name or name not in df.columns:
        raise TwoClockError(f"Pick the column of {what}.")
    values = pd.to_numeric(df[name], errors="coerce").to_numpy(dtype=float)
    return values


def inputs(df: pd.DataFrame, mapping: dict) -> dict:
    """The fit's inputs from a mapping: ``x`` the first clock (hours), ``x2``
    the second (starts, cycles, landings...), ``c`` and ``n`` as usual. Rows with a blank clock are
    left out and counted."""
    mapping = mapping or {}
    refused = sorted({w for k, w in _REFUSED.items() if mapping.get(k)})
    if refused:
        raise TwoClockError("A fit on two clocks takes each unit's two measures of use at its failure (or now, "
                            f"if still running), a status and a count; not {' or '.join(refused)}. Clear "
                            "those columns to fit it.")
    x1 = _column(df, mapping.get("x"), "the first clock (running hours, say)")
    x2 = _column(df, mapping.get(X2), "the second clock (starts, cycles, landings...)")
    c = np.zeros(len(df)) if not mapping.get("c") else pd.to_numeric(df[mapping["c"]], errors="coerce").to_numpy(
        dtype=float)
    n = np.ones(len(df)) if not mapping.get("n") else pd.to_numeric(df[mapping["n"]], errors="coerce").to_numpy(
        dtype=float)
    keep = np.isfinite(x1) & np.isfinite(x2) & np.isfinite(c) & np.isfinite(n)
    if (c[keep] == 2).any():
        raise TwoClockError("Interval-censored rows (status 2) can't be fitted on two clocks: an interval on two "
                            "clocks needs both ends on each. Use failed (0), still running (1) or failed before "
                            "it was seen (-1).")
    if (x1[keep] < 0).any() or (x2[keep] < 0).any():
        raise TwoClockError("Neither clock can be negative.")
    if not keep.any():
        raise TwoClockError("No row has a value on both clocks.")
    out = {"x1": x1[keep], "x2": x2[keep], "c": c[keep].astype(int), "n": n[keep],
           "dropped": int((~keep).sum())}
    if not (out["c"] == 0).any():
        raise TwoClockError("No unit failed: a life needs at least one failure.")
    return out


def fleet_rates(x1: np.ndarray, x2: np.ndarray, n: Optional[np.ndarray] = None) -> dict:
    """Each unit's usage rate (its second clock per unit of the first) summarised: the fleet's
    typical rate (the median) and its 10th and 90th percentiles."""
    ok = (x1 > 0) & np.isfinite(x1) & np.isfinite(x2)
    rates = x2[ok] / x1[ok]
    if not rates.size:
        return {"typical": None, "low": None, "high": None}
    weights = None if n is None else np.asarray(n, dtype=float)[ok]
    if weights is not None and np.any(weights != 1):
        order = np.argsort(rates)
        cum = np.cumsum(weights[order]) / weights.sum()
        pick = lambda q: float(rates[order][min(int(np.searchsorted(cum, q)), rates.size - 1)])  # noqa: E731
        lo, mid, hi = pick(0.1), pick(0.5), pick(0.9)
    else:
        lo, mid, hi = (float(v) for v in np.quantile(rates, [0.1, 0.5, 0.9]))
    return {"typical": _round_rate(mid), "low": _round_rate(lo), "high": _round_rate(hi)}


def _round_rate(r: float) -> float:
    return float(f"{r:.3g}") if r > 0 else 0.0


# ---- the fit ----------------------------------------------------------------------------

def fit_model(distribution: str, df: pd.DataFrame, mapping: dict, unit: str = "", second_unit: str = ""):
    """``(model, inputs)``: SurPyval's fit on the two clocks. TwoClockError for
    data it can't take (SurPyval's own reasons, in its words). The model keeps
    the second clock's unit (``second_unit``; from the column's name if blank)."""
    entry = MODELS.get(distribution)
    if entry is None:
        raise TwoClockError(f"Unknown two-clock model {distribution!r}: one of {', '.join(MODELS)}.")
    data = inputs(df, mapping)
    clocks = (str(mapping.get("x")), str(mapping.get(X2)))
    try:
        with collect_warnings(RuntimeWarning, UserWarning), np.errstate(all="ignore"):
            model = entry["fitter"].fit(data["x1"], data["x2"], c=data["c"], n=data["n"], clocks=clocks)
    except (ValueError, TypeError, np.linalg.LinAlgError) as exc:
        text = str(exc)
        if "same" in text.lower() and "rate" in text.lower():
            w = clock_words(clocks, unit, second_unit or default_unit(mapping.get(X2)))
            text = (f"Every unit made the same {w['rate_unit']}, so the data can't tell what one "
                    f"{w['second_one']} costs from the life itself. A two-clock fit needs units used at different "
                    "rates.")
        raise TwoClockError(text) from None
    if unit:
        model.unit = unit
    model.second_unit = clean_unit(second_unit) or default_unit(mapping.get(X2))
    return model, data


def _param_rows(model, words: Optional[dict] = None) -> list[dict]:
    """The parameters with their 90% two-sided intervals (``k``'s by the
    profile likelihood where it sits on its edge at 0)."""
    rows = []
    for name, value in zip(model.parameter_names, model.params):
        lo = hi = None
        with ignore_warnings(RuntimeWarning, UserWarning), np.errstate(all="ignore"):
            try:
                method = "lr" if (name == "k" and float(value) <= 1e-9) else "wald"
                lo, hi = (float(v) for v in model.param_cb(name, alpha_ci=levels.ALPHA, method=method))
            except (ValueError, TypeError, np.linalg.LinAlgError):
                lo = hi = None
        said = (f"{words['first_word']} one {words['second_one']} is worth" if name == "k" and words
                else PARAM_WORDS.get(name, name))
        rows.append({"name": name, "value": float(value), "words": said,
                     "ci": [_f(lo), _f(hi) if hi != math.inf else None]})
    return rows


def _k_test(model) -> Optional[dict]:
    try:
        with ignore_warnings(RuntimeWarning, UserWarning):
            t = model.k_lr_test()
    except (ValueError, TypeError):
        return None
    p = _f(t.get("p_value"))
    return {"statistic": _f(t.get("statistic")), "p_value": p,
            "matters": bool(p is not None and p < levels.ALPHA)}


def life_at(model, rate):
    """The life of a unit used at ``rate`` (second clock per unit of the first)
    as an ordinary life model on the first clock: SurPyval's ``at_usage``, its
    bounds carrying ``k``'s uncertainty."""
    return model.at_usage(check_rate(rate, words_of(model)))


def _grid(life, points: int = 120) -> np.ndarray:
    try:
        hi = float(life.qf(0.99))
    except Exception:  # noqa: BLE001 - the plot still needs an end
        hi = None
    if hi is None or not math.isfinite(hi) or hi <= 0:
        hi = 1.0
    return np.linspace(0.0, hi, points)


def curves_at(life) -> dict:
    """The reliability over the first clock at a rate, with its 90% two-sided band."""
    grid = _grid(life)
    with np.errstate(all="ignore"), ignore_warnings(RuntimeWarning, UserWarning):
        sf = np.asarray(life.sf(grid), dtype=float)
        hf = np.asarray(life.hf(grid), dtype=float)
        try:
            inner = grid[1:]
            band = np.asarray(life.cb(inner, alpha_ci=levels.ALPHA), dtype=float).reshape(-1, 2)
            lower = np.concatenate([[1.0], band[:, 0]])
            upper = np.concatenate([[1.0], band[:, 1]])
        except (ValueError, TypeError, np.linalg.LinAlgError):
            lower = upper = None

    def col(a):
        return None if a is None else [_f(v) for v in a]

    return {"x": grid.tolist(), "sf": col(sf), "hf": col(hf), "sf_lower": col(lower), "sf_upper": col(upper),
            "level": levels.LEVEL}


def as_distribution(life) -> Optional[dict]:
    """The life at a rate as the plain distribution it equals in hours (exact: each
    distribution here is closed under a change of time scale, so it is the combined-clock
    distribution with time divided by ``1 + k rate``): {distribution_id, params [{name,
    value}]} for tools that take a distribution and its parameters (Strategy). Point
    values only; the bounds stay with the two-clock model. None for another family."""
    model = life.model
    return distribution_in_hours(model.dist.name, list(model.parameter_names[:-1]), model.dist_params,
                                 float(life.acceleration))


def distribution_in_hours(dist_name: str, names, values, acceleration: float) -> Optional[dict]:
    """A combined-clock distribution (``dist_name`` with parameters ``names`` = ``values``)
    of a unit that ages ``acceleration`` combined units per hour, as the plain distribution
    it is in hours (see :func:`as_distribution`); None for another family."""
    p = dict(zip(names, (float(v) for v in values)))
    a = float(acceleration)
    if dist_name == "Weibull":
        out = ("weibull", [("alpha", p["alpha"] / a), ("beta", p["beta"])])
    elif dist_name == "Exponential":
        out = ("exponential", [("failure_rate", p["failure_rate"] * a)])
    elif dist_name == "LogNormal":
        out = ("lognormal", [("mu", p["mu"] - math.log(a)), ("sigma", p["sigma"])])
    else:
        return None
    return {"distribution_id": out[0], "params": [{"name": k, "value": v} for k, v in out[1]]}


def at_rate(model, rate, unit: str = "", source: Optional[dict] = None) -> dict:
    """What a unit at ``rate`` gets: its life (B-lives and mean life, each with
    its 90% one-sided lower bound), the curve with its band, and a sentence.
    ``source`` (optional) says where the rate came from (an operating plan)."""
    from backend import life_bounds

    words = words_of(model, unit)
    r = check_rate(rate, words)
    life = life_at(model, r)
    summary = life_bounds.life_summary(life, life_bounds.DEFAULT_CONFIDENCE, with_bounds=True)
    b10 = next((b for b in summary["b_lives"] if b.get("label") == "B10"), None)
    acc = num(life.acceleration)
    sentence = (f"At {rate_words(r, words)}, its B10 life is {num(b10 and b10.get('value'))} {words['first_word']}"
                + (f" (at least {num(b10['lower'])} {words['first_word']}, 90% one-sided)"
                   if b10 and _f(b10.get("lower")) is not None else "")
                + f": each {words['first_one']} ages it {acc} combined {_plural(acc, words, 'first')}.")
    out = {"rate": r, "rate_words": rate_words(r, words), "acceleration": float(life.acceleration),
           "every": (1.0 / r) if r > 0 else None, "life": summary, "sentence": sentence,
           "curves": curves_at(life), "unit": unit or "", "clocks": words, "second_unit": words["second_word"],
           "as_distribution": as_distribution(life)}
    if source:
        out["source"] = source
    return out


def headline(model, typical: Optional[float], unit: str, test: Optional[dict]) -> str:
    """The answer in plain words first: what one unit of the second clock costs,
    then the life at the fleet's typical rate."""
    words = words_of(model, unit)
    k = float(model.k)
    first = (f"Wears by {words['second_word']} and by {words['first_word']}: one {words['second_one']} wears it "
             f"as much as {num(k)} {_plural(num(k), words, 'first')}.")
    if test is not None and not test["matters"]:
        first = (f"The data can't tell {words['second_word']} from no effect (p = {num(test['p_value'])}): "
                 f"{words['first_word']} alone may do. Best estimate: one {words['second_one']} is worth "
                 f"{num(k)} {_plural(num(k), words, 'first')}.")
    if typical is None:
        return first
    try:
        return first + " " + at_rate(model, typical, unit)["sentence"]
    except (TwoClockError, ValueError):
        return first


def rate_table(model, rates: dict, unit: str) -> list[dict]:
    """B10 (with its 90% lower bound) and mean life at the fleet's low, typical
    and high rates, each said in words."""
    from backend import life_bounds

    words = words_of(model, unit)
    rows, seen = [], set()
    for label, key in (("Low", "low"), ("Typical", "typical"), ("High", "high")):
        r = rates.get(key)
        if r is None or r in seen:
            continue
        seen.add(r)
        life = model.at_usage(r)
        s = life_bounds.life_summary(life, life_bounds.DEFAULT_CONFIDENCE, with_bounds=True)
        b10 = next((b for b in s["b_lives"] if b.get("label") == "B10"), {})
        rows.append({"label": label, "rate": r, "rate_words": rate_words(r, words), "b10": _f(b10.get("value")),
                     "b10_lower": _f(b10.get("lower")), "mean": _f((s.get("mttf") or {}).get("value"))})
    return rows


def result(model, data: dict, distribution: str, unit: str = "") -> dict:
    """The fit payload the app and the API show (and a saved model keeps)."""
    entry = MODELS[distribution]
    rates = fleet_rates(data["x1"], data["x2"], data["n"])
    test = _k_test(model)
    words = words_of(model, unit)
    failed = int(np.sum(data["n"][data["c"] == 0]))
    running = int(np.sum(data["n"][data["c"] == 1]))
    left = int(np.sum(data["n"][data["c"] == -1]))
    warnings = []
    if data.get("dropped"):
        warnings.append(f"{data['dropped']} row(s) without both {words['first_word']} and "
                        f"{words['second_word']} were left out.")
    if getattr(model, "maximum", "verified") not in ("verified", None):
        warnings.append(f"The fit's maximum is {model.maximum}: treat its numbers with care.")
    if test is not None and not test["matters"]:
        warnings.append(f"The data can't tell {words['second_word']} from no effect (p = {num(test['p_value'])}).")
    out = {
        "kind": KIND,
        "distribution": entry["name"],
        "distribution_id": distribution,
        "base_distribution": entry["base"],
        "clocks": words,
        "second_unit": words["second_word"],
        "params": _param_rows(model, words),
        "k": float(model.k),
        "k_test": test,
        "rates": rates,
        "default_rate": rates.get("typical"),
        "rate_table": rate_table(model, rates, unit),
        "headline": headline(model, rates.get("typical"), unit, test),
        "split": {"failed": failed, "running": running, **({"left_censored": left} if left else {})},
        "n": int(np.sum(data["n"])),
        "log_likelihood": _f(-model._neg_ll) if getattr(model, "_neg_ll", None) is not None else None,
        "ci_level": levels.LEVEL,
        "warnings": warnings,
    }
    try:
        out["aic"] = _f(model.aic())
    except Exception:  # noqa: BLE001 - a criterion is a nicety
        pass
    if rates.get("typical") is not None:
        out["at_rate"] = at_rate(model, rates["typical"], unit)
    return out


def fit(distribution: str, df: pd.DataFrame, mapping: dict, unit: str = "",
        second_unit: str = "") -> tuple[object, dict]:
    """``(model, result)`` for a fit on two clocks."""
    model, data = fit_model(distribution, df, mapping, unit, second_unit)
    return model, result(model, data, distribution, unit)


def to_dict(model) -> dict:
    """A live two-clock model as SurPyval's ``to_dict``, plus the second
    clock's unit (``second_unit``), which SurPyval doesn't keep."""
    d = model.to_dict()
    if getattr(model, "second_unit", None):
        d["second_unit"] = clean_unit(model.second_unit)
    return d


def from_dict(d: dict):
    """A saved two-clock model rebuilt (:func:`to_dict`'s form), its second
    clock's unit with it. One saved before the unit existed has none, and
    reads as "starts" (:func:`unit_of`)."""
    model = sp.from_dict(d)
    unit = clean_unit((d or {}).get("second_unit"))
    if unit and is_model(model):
        model.second_unit = unit
    return model


# ---- Download as Python ----------------------------------------------------------------

def python_script(title: str, df: pd.DataFrame, mapping: dict, distribution: str, unit: str,
                  rate: Optional[float], second_unit: str = "") -> list[str]:
    """The body of a Download as Python script: the data embedded, SurPyval's fit,
    and the life at the typical rate with its 90% one-sided lower bounds."""
    from backend.services import python_export as px

    entry = MODELS[distribution]
    fitter = entry["fitter"].dist.name + "Equivalence"
    cols = {"first": mapping["x"], "second": mapping[X2]}
    words = clock_words(None, unit, second_unit)
    frame = pd.DataFrame({mapping["x"]: pd.to_numeric(df[mapping["x"]], errors="coerce"),
                          mapping[X2]: pd.to_numeric(df[mapping[X2]], errors="coerce")})
    if mapping.get("c"):
        frame["c"] = pd.to_numeric(df[mapping["c"]], errors="coerce")
    if mapping.get("n"):
        frame["n"] = pd.to_numeric(df[mapping["n"]], errors="coerce")
    frame = frame.dropna()
    call = [f"x_cols=[{cols['first']!r}, {cols['second']!r}]"]
    if mapping.get("c"):
        call.append("c_col='c'")
    if mapping.get("n"):
        call.append("n_col='n'")
    rate_line = f"RATE = {px.num(rate) if rate is not None else '0.0'}  # {words['rate_unit']}"
    return [
        *px.comment(f"The data, one row per unit: its {words['first_word']} and {words['second_word']} at its "
                    "failure, or now if still running; c is 0 = failed, 1 = still running, -1 = failed before it "
                    "was seen; n how many units."),
        *px.csv_block("DATA", frame),
        f"UNIT = {unit!r}",
        rate_line,
        "",
        "data = pd.read_csv(io.StringIO(DATA))",
        f"model = {fitter}.fit_from_df(data, {', '.join(call)})",
        "print(model)",
        "print()",
        "for name in model.parameter_names:",
        "    low, high = model.param_cb(name, alpha_ci=0.10)",
        "    print_interval(name, model.params[model.parameter_names.index(name)], low, high)",
        "",
        f"# The life of a unit used at RATE ({words['rate_unit']}), as an ordinary life in "
        f"{words['first_word']} (bounds include k's uncertainty).",
        "life = model.at_usage(RATE)",
        "for p, label in ((0.01, 'B1'), (0.10, 'B10'), (0.50, 'B50')):",
        "    print_bound(label, life.qf(p), life.quantile_cb(p, alpha_ci=0.10, bound='lower'), unit=UNIT)",
        "print_value('mean life', life.mean(), UNIT)",
    ]


# ---- the calculator at a rate ------------------------------------------------------------

MAX_POINTS = 50


def reliability_at(life, times) -> list[dict]:
    """Reliability at each time (the model's unit) with its 90% one-sided lower bound."""
    ts = [check_time(t) for t in (times if isinstance(times, (list, tuple)) else [times])]
    if len(ts) > MAX_POINTS:
        raise TwoClockError(f"At most {MAX_POINTS} times at a time.")
    arr = np.asarray(ts, dtype=float)
    with np.errstate(all="ignore"), ignore_warnings(RuntimeWarning, UserWarning):
        sf = np.asarray(life.sf(arr), dtype=float)
        try:
            lower = np.asarray(life.cb(arr, alpha_ci=levels.ALPHA, bound="lower"), dtype=float).reshape(-1)
        except (ValueError, TypeError, np.linalg.LinAlgError):
            lower = np.full(arr.size, np.nan)
    return [{"t": float(t), "reliability": _f(r), "lower": _f(lo) if t > 0 else _f(r)}
            for t, r, lo in zip(arr, sf, lower)]


def check_time(t) -> float:
    x = _f(t)
    if x is None or x < 0:
        raise TwoClockError("Each time is a number in the model's unit, 0 or more.")
    return x


def answer(model, body: Optional[dict], unit: str = "") -> dict:
    """The app's and the API's request on a two-clock model: ``{"rate"}`` (the
    second clock per unit of the first; the fit's typical rate when left out and ``default_rate`` given),
    optionally ``"times"`` (reliability there, each with its 90% lower bound) and
    ``"reliability"`` (the hours at each reliability, each with its 90% lower
    bound)."""
    from backend import life_bounds

    body = dict(body or {})
    if body.get("rate") in (None, "") and body.get("default_rate") is not None:
        body["rate"] = body["default_rate"]
    if body.get("rate") in (None, ""):
        raise TwoClockError(f"Give the usage rate: {rate_help(words_of(model, unit))}.")
    out = at_rate(model, body["rate"], unit, body.get("source"))
    life = life_at(model, out["rate"])
    if body.get("times") is not None:
        out["at_times"] = reliability_at(life, body["times"])
    if body.get("reliability") is not None:
        rel = body["reliability"] if isinstance(body["reliability"], (list, tuple)) else [body["reliability"]]
        if len(rel) > MAX_POINTS:
            raise TwoClockError(f"At most {MAX_POINTS} reliabilities at a time.")
        out["time_at_reliability"] = life_bounds.time_at_reliability(life, rel, life_bounds.DEFAULT_CONFIDENCE,
                                                                     "lower", with_bounds=True)
    return out
