"""Validation for user-supplied regression formulas.

formulaic evaluates formula factors as Python, so a formula is only accepted
when every name in it is a dataset column or one of a few known transforms,
and it contains nothing but arithmetic and grouping. That keeps the useful
grammar (``age + C(site)``, ``a*b``, ``log(load)``, ``I(t**2)``,
``poly(x, 2)``, `` `col with spaces` ``) while ruling out attribute access,
strings, subscripts and calls to anything else.
"""

from __future__ import annotations

import re
from typing import Iterable

MAX_FORMULA_LENGTH = 300
MAX_NUMBER = 10

# Transforms a formula may call. Each name must be followed by "(".
ALLOWED_FUNCTIONS = frozenset({"C", "I", "center", "scale", "log", "exp", "poly"})

_TOKEN = re.compile(
    r"""
      (?P<ws>\s+)
    | (?P<quoted>`[^`]*`)
    | (?P<name>[A-Za-z_][A-Za-z0-9_]*)
    | (?P<number>\d+(?:\.\d+)?)
    | (?P<op>\*\*|[+\-*/:(),])
    """,
    re.VERBOSE,
)


class FormulaRejected(ValueError):
    """The formula uses something outside the permitted grammar."""


def check_formula(formula: str, columns: Iterable[object]) -> str:
    """Return ``formula`` stripped if it is safe to evaluate, else raise."""
    if not isinstance(formula, str):
        raise FormulaRejected("The formula must be text.")
    text = formula.strip()
    if not text:
        raise FormulaRejected("The formula is empty.")
    if len(text) > MAX_FORMULA_LENGTH:
        raise FormulaRejected(
            f"The formula is too long (max {MAX_FORMULA_LENGTH} characters)."
        )

    cols = {str(c) for c in columns}
    tokens: list[tuple[str, str]] = []
    pos = 0
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m:
            raise FormulaRejected(
                f"The formula contains an unsupported character: {text[pos]!r}."
            )
        pos = m.end()
        if m.lastgroup != "ws":
            tokens.append((m.lastgroup, m.group()))

    depth = 0
    for i, (kind, value) in enumerate(tokens):
        nxt = tokens[i + 1][1] if i + 1 < len(tokens) else None
        if kind == "name":
            if nxt == "(":
                if value not in ALLOWED_FUNCTIONS:
                    raise FormulaRejected(
                        f"'{value}(...)' isn't supported in formulas. Use "
                        f"column names, + - * / : **, and "
                        f"{', '.join(sorted(ALLOWED_FUNCTIONS))}."
                    )
            elif value not in cols:
                raise FormulaRejected(f"Column '{value}' isn't in the data.")
        elif kind == "quoted":
            if value[1:-1] not in cols:
                raise FormulaRejected(f"Column {value} isn't in the data.")
        elif kind == "number":
            if float(value) > MAX_NUMBER:
                raise FormulaRejected(
                    f"Numbers in formulas are limited to {MAX_NUMBER} or less."
                )
        elif value == "(":
            depth += 1
        elif value == ")":
            depth -= 1
            if depth < 0:
                raise FormulaRejected("The formula has an unmatched ')'.")
    if depth:
        raise FormulaRejected("The formula has an unmatched '('.")
    return text
