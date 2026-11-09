"""Helpers the NSWC-11 chapter modules write their models with.

Each chapter module (``chNN_<name>.py``) defines ``RECORDS``, a list of
:func:`record` results. ``backend.scripts.build_nswc11`` adds the source,
citation and licence to each and writes ``backend/library/data/nswc-11.json``.
The shapes are :mod:`backend.library.covariate`'s; these helpers only keep the
chapters short and every limit and factor cited.

Conventions:
- Input names are identifiers close to the handbook's symbols (``L_A``,
  ``nu_O``); ``symbol`` is the handbook's own, for display.
- Every number has limits: :func:`positive` (or another physical bound) that
  refuses, and the handbook's range (a stated range, or what its figure's axis
  covers) that warns, with the page.
- Pages are the handbook's own page labels ("7-11"), not the PDF's.
- A formula the extracted text scrambles is checked against the rendered page,
  and anything still ambiguous is said in a comment with the page.
"""

from __future__ import annotations

from typing import Any, Optional


def positive(why: str = "it must be more than zero") -> dict:
    return {"min": 0, "exclusive": True, "severity": "refuse", "why": why}


def non_negative(why: str = "it can't be negative") -> dict:
    return {"min": 0, "severity": "refuse", "why": why}


def refuse(min: Optional[float] = None, max: Optional[float] = None, why: str = "", page: Optional[str] = None,
           exclusive: bool = False) -> dict:
    out: dict[str, Any] = {"severity": "refuse", "why": why}
    if min is not None:
        out["min"] = min
    if max is not None:
        out["max"] = max
    if exclusive:
        out["exclusive"] = True
    if page:
        out["page"] = page
    return out


def warn(min: Optional[float] = None, max: Optional[float] = None, why: str = "", page: Optional[str] = None,
         exclusive: bool = False) -> dict:
    out = refuse(min, max, why, page, exclusive)
    out["severity"] = "warn"
    return out


#: Where a default comes from: the handbook gives or recommends it; it's the neutral value (the
#: factor is 1: the condition as designed); or it's a typical condition Reliafy picked (said so).
DEFAULT_BASES = ("handbook", "neutral", "typical")


def _default(out: dict, default: Any, basis: Optional[str]) -> None:
    if default is None:
        return
    if basis not in DEFAULT_BASES:
        raise ValueError(f"{out['name']}: say where its default comes from: one of {DEFAULT_BASES}")
    out["default"] = default
    out["default_basis"] = basis


def num(name: str, label: str, unit: str, limits: list[dict], default: Optional[float] = None,
        symbol: Optional[str] = None, page: Optional[str] = None, help: Optional[str] = None,
        default_basis: Optional[str] = None, when: Optional[str] = None, unused: Optional[float] = None) -> dict:
    """A number input. ``when``: an expression of the inputs before it; the input is asked for only
    when it's true (otherwise it takes ``unused``, 0 unless given), so a value one choice doesn't
    need is never a placeholder."""
    out: dict[str, Any] = {"name": name, "kind": "number", "label": label, "unit": unit, "limits": limits}
    _default(out, default, default_basis)
    if when:
        out["when"] = when
        if unused is not None:
            out["unused"] = unused
    if symbol:
        out["symbol"] = symbol
    if page:
        out["page"] = page
    if help:
        out["help"] = help
    return out


def choice(name: str, label: str, choices: list[tuple[str, str]], default: Optional[str] = None,
           symbol: Optional[str] = None, page: Optional[str] = None, help: Optional[str] = None,
           default_basis: Optional[str] = None) -> dict:
    out: dict[str, Any] = {"name": name, "kind": "choice", "label": label,
                           "choices": [{"code": c, "label": lab} for c, lab in choices]}
    _default(out, default, default_basis)
    if symbol:
        out["symbol"] = symbol
    if page:
        out["page"] = page
    if help:
        out["help"] = help
    return out


def _term(value: Optional[float], expr: Optional[str], table: Optional[dict]) -> dict:
    given = [k for k, v in (("value", value), ("expr", expr), ("table", table)) if v is not None]
    if len(given) != 1:
        raise ValueError("give exactly one of value, expr or table")
    return {given[0]: {"value": value, "expr": expr, "table": table}[given[0]]}


def table(by: str | list[str], values: dict) -> dict:
    """A lookup by one choice input (``by``) or two (``[outer, inner]``)."""
    return {"by": by, "values": values}


def base(symbol: str, name: str, page: str, value: Optional[float] = None, expr: Optional[str] = None,
         table: Optional[dict] = None, equation: Optional[str] = None, source: Optional[str] = None) -> dict:
    out = {"symbol": symbol, "name": name, **_term(value, expr, table), "page": page}
    if equation:
        out["equation"] = equation
    if source:
        out["source"] = source
    return out


def factor(symbol: str, name: str, page: str, value: Optional[float] = None, expr: Optional[str] = None,
           table: Optional[dict] = None, equation: Optional[str] = None, source: Optional[str] = None,
           when: Optional[str] = None, words: Optional[str] = None) -> dict:
    """A multiplying factor. ``source``: the figure or table ("Figure 7.5");
    ``when``: an expression; the factor applies only when it's true;
    ``words``: what raises it, in plain words, for the record page."""
    out = {"symbol": symbol, "name": name, **_term(value, expr, table), "page": page}
    for k, v in (("equation", equation), ("source", source), ("when", when), ("words", words)):
        if v:
            out[k] = v
    return out


def mode(key: str, name: str, base: dict, factors: list[dict] = (), symbol: Optional[str] = None,
         count: Optional[str] = None, note: Optional[str] = None, meaning: Optional[str] = None,
         scale: Optional[str] = None, scale_label: Optional[str] = None, when: Optional[str] = None) -> dict:
    """A failure mode or part: ``base`` × ``factors`` (× ``count``). ``scale`` (with ``scale_label``)
    turns a per-cycle base into per hour inside a per-hour assembly; ``when`` leaves it out when false."""
    out: dict[str, Any] = {"key": key, "name": name, "base": base, "factors": list(factors)}
    for k, v in (("symbol", symbol), ("count", count), ("note", note), ("meaning", meaning), ("scale", scale),
                 ("scale_label", scale_label), ("when", when)):
        if v:
            out[k] = v
    return out


def uses(key: str, name: str, record: str, prefix: Optional[str] = None, symbol: Optional[str] = None,
         count: Optional[str] = None, note: Optional[str] = None, scale: Optional[str] = None,
         scale_label: Optional[str] = None, bind: Optional[dict] = None, when: Optional[str] = None) -> dict:
    """A mode whose rate is another NSWC-11 record's total (``record``: its slug). ``scale`` (with
    ``scale_label``): the expression a per-cycle part is multiplied by to be per hour (its cycles an
    hour, the handbook's rule, pp. 12-10, 12-16). ``bind``: {the part's input: an expression of the
    assembly's inputs}, a shared condition entered once. ``when``: the part is left out when false."""
    out: dict[str, Any] = {"key": key, "name": name, "uses": f"nswc-11:{record}"}
    for k, v in (("prefix", prefix), ("symbol", symbol), ("count", count), ("note", note), ("scale", scale),
                 ("scale_label", scale_label), ("bind", bind), ("when", when)):
        if v:
            out[k] = v
    return out


def derived(name: str, label: str, expr: str, unit: str = "", symbol: Optional[str] = None,
            page: Optional[str] = None, equation: Optional[str] = None, limits: Optional[list[dict]] = None) -> dict:
    out: dict[str, Any] = {"name": name, "label": label, "expr": expr, "unit": unit}
    for k, v in (("symbol", symbol), ("page", page), ("equation", equation), ("limits", limits)):
        if v:
            out[k] = v
    return out


def check(expr: str, why: str, page: Optional[str] = None, severity: str = "warn", when: Optional[str] = None) -> dict:
    out: dict[str, Any] = {"expr": expr, "why": why, "severity": severity}
    if page:
        out["page"] = page
    if when:
        out["when"] = when
    return out


def record(slug: str, name: str, equipment_type: str, chapter: int, section: str, equation: str, page: str,
           formula: str, words: str, inputs: list[dict], modes: list[dict], rate_unit: str = "per_million_hours",
           derived: list[dict] = (), checks: list[dict] = (), notes: Optional[str] = None,
           failure_modes: Optional[list[str]] = None) -> dict:
    """One component's model. ``formula``: the handbook's equation as text
    ("λ_BE = λ_BE,B · C_R · …"); ``words``: the model in plain words, first;
    ``failure_modes``: the handbook's failure modes it covers, in words (its
    failure mode table), for the record page."""
    return {
        "slug": slug, "name": name, "equipment_type": equipment_type, "chapter": chapter, "section": section,
        "notes": notes, "failure_modes": list(failure_modes or []),
        "covariate_model": {
            "equation": equation, "page": page, "formula": formula, "words": words, "rate_unit": rate_unit,
            "combine": "sum", "inputs": list(inputs), "derived": list(derived), "checks": list(checks),
            "modes": list(modes),
        },
    }
