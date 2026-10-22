"""The figures a report draft may use (#41): read off each item's stored
results, never computed here.

``facts(collection, payload)`` turns an item's public payload (exactly what
the report page will show) into short labelled lines such as
``"MTTF (mean life): 1,270 hours"``. The assistant words a narrative from
these lines only, and :func:`unverified_numbers` lists any number in its
draft that isn't among them, so the owner checks it before publishing.
Numbers are written once here, rounded to three significant figures, so
the draft can copy them exactly.
"""

from __future__ import annotations

import math
import re

_NUMBER = re.compile(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?")


def num(value, sig: int = 3) -> str | None:
    """A figure as the report shows it: three significant figures with
    thousands separators; scientific notation only for the very small or
    large. None for anything that isn't a finite number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    v = float(value)
    if not math.isfinite(v):
        return None
    if v == 0:
        return "0"
    if abs(v) < 1e-3 or abs(v) >= 1e7:
        return f"{v:.{sig - 1}e}"
    digits = sig - 1 - int(math.floor(math.log10(abs(v))))
    rounded = round(v, digits)
    if digits <= 0:
        return f"{int(rounded):,}"
    text = f"{rounded:,.{digits}f}".rstrip("0").rstrip(".")
    return text


def pct(value, sig: int = 3) -> str | None:
    """A fraction as a percentage."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return f"{num(value * 100, sig)}%"


def _unit(payload: dict, results: dict | None = None) -> str:
    unit = (results or {}).get("unit") or payload.get("unit") or ""
    return str(unit).lower()


def _with_unit(value, unit: str) -> str | None:
    text = num(value)
    return f"{text} {unit}".strip() if text is not None else None


def _add(lines: list, label: str, value: str | None) -> None:
    if value not in (None, ""):
        lines.append(f"{label}: {value}")


_PARAM_LABELS = {
    "alpha": "Scale α", "beta": "Shape β", "gamma": "Location γ", "mu": "Log-mean μ", "sigma": "Log-SD σ",
    "failure_rate": "Failure rate", "lambda": "Rate λ",
}


def _model(payload: dict) -> list[str]:
    r = payload.get("results") or {}
    unit = _unit(payload, r)
    lines: list[str] = []
    _add(lines, "Model", r.get("distribution") or payload.get("distribution"))
    _add(lines, "Data points", num(r.get("n") or payload.get("n")))
    kind = r.get("kind") or payload.get("kind")
    if kind == "competing_risks":
        _add(lines, "Summary", r.get("reading"))
        for c in r.get("causes") or []:
            _add(lines, f"Share of failures from {c.get('name')}", pct(c.get("share"), 2))
        return lines
    for p in r.get("params") or []:
        label = _PARAM_LABELS.get(p.get("name"), p.get("name"))
        _add(lines, label, num(p.get("value")))
    life = r.get("life") or {}
    mttf = (life.get("mttf") or {}).get("value")
    _add(lines, "MTTF (mean life)", _with_unit(mttf, unit))
    for b in life.get("b_lives") or []:
        if b.get("label") in ("B10", "B50"):
            name = "B10 life (10% failed)" if b["label"] == "B10" else "B50 life (median)"
            _add(lines, name, _with_unit(b.get("value"), unit))
    means = r.get("at_covariate_means") or {}
    if means:
        _add(lines, "MTTF at typical conditions", _with_unit(means.get("mttf"), unit))
        _add(lines, "B10 life at typical conditions", _with_unit(means.get("b10"), unit))
    for c in r.get("coefficients") or []:
        ratio = c.get("hazard_ratio") or c.get("ratio")
        _add(lines, f"Effect of {c.get('name')} ({r.get('ratio_label') or 'ratio'} per unit)", num(ratio))
    verdict = (r.get("randomness") or payload.get("randomness") or {}).get("verdict")
    if verdict:
        _add(lines, "Failure pattern", {"wear_out": "wear-out (failure rate rises with age)",
                                        "infant": "early-life failures (failure rate falls with age)",
                                        "random": "random (no clear trend with age)"}.get(verdict, verdict))
    return lines


def _recurrent(payload: dict) -> list[str]:
    r = payload.get("results") or {}
    unit = _unit(payload, r)
    lines: list[str] = []
    _add(lines, "Model", (r.get("model") or {}).get("name") or payload.get("model"))
    _add(lines, "Systems", num(r.get("n_systems")))
    _add(lines, "Failures recorded", num(r.get("n_events")))
    _add(lines, "Growth shape β", num(r.get("beta")))
    _add(lines, "Trend", r.get("growth"))
    _add(lines, "Current MTBF", _with_unit(r.get("mtbf"), unit))
    _add(lines, "Current failure rate (per " + (unit.rstrip("s") or "unit") + ")", num(r.get("rocof")))
    demo = r.get("demonstrated_mtbf") or {}
    _add(lines, "Demonstrated MTBF (lower bound)", _with_unit(demo.get("lower"), unit))
    _add(lines, "Repair effectiveness", (r.get("restoration") or {}).get("short"))
    _add(lines, "Repair quality", (r.get("repair_test") or {}).get("sentence"))
    return lines


def _degradation(payload: dict) -> list[str]:
    r = payload.get("results") or {}
    unit = _unit(payload, r)
    lines: list[str] = []
    _add(lines, "Wear path", (r.get("path_model") or {}).get("name"))
    _add(lines, "Units measured", num(r.get("n_units")))
    _add(lines, "Measurements", num(r.get("n_measurements")))
    threshold = num(r.get("threshold"))
    if threshold is not None:
        _add(lines, "Failure threshold", f"{threshold} {r.get('measurement_unit') or ''}".strip())
    _add(lines, "Mean life to the threshold", _with_unit((r.get("life_model") or {}).get("mean"), unit))
    return lines


def _strategy(payload: dict) -> list[str]:
    r = payload.get("results") or {}
    unit = str(r.get("unit") or "").lower()
    lines: list[str] = []
    _add(lines, "Answer", payload.get("headline"))
    _add(lines, "Recommendation", r.get("recommendation") or r.get("note"))
    _add(lines, "MTTF", _with_unit(r.get("mttf"), unit))
    _add(lines, "Replace at", _with_unit(r.get("optimal_time"), unit))
    _add(lines, "Saving against run-to-failure", pct(r.get("savings"), 2))
    _add(lines, "Planned cost", num(r.get("planned_cost")))
    _add(lines, "Unplanned cost", num(r.get("unplanned_cost")))
    _add(lines, "Check interval", _with_unit(r.get("interval"), unit))
    _add(lines, "Target availability", pct(r.get("target_availability")))
    return lines


def _fleet(payload: dict) -> list[str]:
    f = payload.get("forecast") or {}
    lines: list[str] = []
    _add(lines, "Answer", payload.get("headline"))
    if f.get("status") == "ok":
        _add(lines, "Expected failures", num(f.get("expected")))
        lo, hi = (f.get("interval") or [None, None])[:2]
        if num(lo) is not None and num(hi) is not None:
            _add(lines, "Likely range (P10–P90)", f"{num(lo)} to {num(hi)}")
        _add(lines, "Horizon", f"{f.get('periods')} {f.get('period_label') or 'periods'}")
        _add(lines, "Items", num(f.get("n_items")))
        _add(lines, "Non-repairable model", f.get("model_name"))
    elif f.get("reason"):
        _add(lines, "Forecast", f.get("reason"))
    return lines


def _rbd(payload: dict) -> list[str]:
    a = payload.get("analysis") or {}
    unit = str((payload.get("graph") or {}).get("unit") or "").lower()
    lines: list[str] = []
    nodes = [n for n in (payload.get("graph") or {}).get("nodes") or [] if n.get("type") not in ("input", "output")]
    _add(lines, "Blocks", num(len(nodes)))
    if not a:
        _add(lines, "Results", payload.get("analysis_note") or payload.get("analysis_error"))
        return lines
    if a.get("kind") == "repairable":
        _add(lines, "Long-run availability", pct(a.get("steady_state_availability"), 4))
        _add(lines, "Mean up time", _with_unit(a.get("mean_up_time"), unit))
        _add(lines, "Mean down time", _with_unit(a.get("mean_down_time"), unit))
        return lines
    _add(lines, "System MTTF", _with_unit(a.get("mttf"), unit))
    blife = a.get("blife") or {}
    _add(lines, "System B10 life (10% failed)", _with_unit(blife.get("b10"), unit))
    _add(lines, "System B50 life (median)", _with_unit(blife.get("b50"), unit))
    birnbaum = ((a.get("importance") or {}).get("birnbaum") or {})
    if birnbaum:
        labels = {n.get("id"): (n.get("data") or {}).get("label") or n.get("id") for n in nodes}
        top = max(birnbaum, key=lambda k: birnbaum[k] or 0)
        _add(lines, "Most important block", labels.get(top, top))
    return lines


def _rcm(payload: dict) -> list[str]:
    roll = payload.get("rollup") or {}
    lines: list[str] = []
    _add(lines, "System", payload.get("system"))
    _add(lines, "Failure modes", num(roll.get("modes")))
    _add(lines, "Decisions made", num(roll.get("decided")))
    _add(lines, "Decisions supported by evidence", num(roll.get("supported")))
    _add(lines, "Decisions the evidence contradicts", num(roll.get("contradicted")))
    return lines


def _dataset(payload: dict) -> list[str]:
    lines: list[str] = []
    _add(lines, "Rows", num(payload.get("n_rows")))
    _add(lines, "Columns", ", ".join(payload.get("preview_columns") or []) or None)
    return lines


_BY_COLLECTION = {
    "models": _model,
    "recurrent_models": _recurrent,
    "degradation_models": _degradation,
    "strategy_analyses": _strategy,
    "fleets": _fleet,
    "rbds": _rbd,
    "rcm_studies": _rcm,
    "datasets": _dataset,
}


def facts(collection: str, payload: dict | None) -> list[str]:
    """Labelled figures for one section's item (empty when there are none)."""
    if not payload:
        return []
    fn = _BY_COLLECTION.get(collection)
    try:
        return fn(payload) if fn else []
    except Exception:  # noqa: BLE001 - an odd payload drafts with fewer facts, not an error
        return []


def _canon(token: str) -> str:
    text = token.replace(",", "")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text.lstrip("-") or "0"


def numbers_in(text: str) -> set[str]:
    """Every number written in ``text``, canonicalised (no separators)."""
    return {_canon(m.group(0)) for m in _NUMBER.finditer(text or "")}


# Small counts a narrative may use without them being a "figure" ("two pumps",
# "3 sections", "1 in 10").
_SMALL = {str(i) for i in range(0, 13)}


def unverified_numbers(draft: str, sources: list[str]) -> list[str]:
    """Numbers in ``draft`` that appear in none of ``sources`` (the facts, the
    title and the item names), in the order they're written."""
    known = set().union(*(numbers_in(s) for s in sources)) if sources else set()
    out, seen = [], set()
    for m in _NUMBER.finditer(draft or ""):
        canon = _canon(m.group(0))
        if canon in known or canon in _SMALL or canon in seen:
            continue
        seen.add(canon)
        out.append(m.group(0))
    return out
