"""Covariate models: a failure rate that is a base rate scaled by functions of
the conditions a part works in. The NSWC-11 mechanical handbook is a library of
them (Derryn, 9 Nov 2026: "literally just a library of covariate models").

A record of kind ``covariate_model`` holds its model in ``covariate_model``:

- ``inputs``: the conditions, each a number (``unit``, an optional handbook
  ``default`` and ``limits``) or a choice (``choices`` of {code, label}).
- ``derived``: named intermediate values (an L10 life, a stress), each an
  expression of the inputs and the values before it.
- ``modes``: the failure modes or parts whose rates add up to the total. A mode
  is ``base`` × each of its ``factors`` (× ``count``, an input, when there are
  several of the part), or ``uses`` another covariate record (its inputs then
  appear here under ``prefix``, e.g. ``seal.P_s``).
- ``checks``: conditions on the inputs together (FA at most 30% of FR) that
  refuse or warn, like an input's own limits.

A base or a factor is ``value`` (a constant), ``expr`` (an expression), or
``table`` (a lookup by one or two choice inputs). Expressions are a small,
safe language parsed with :mod:`ast` and walked here (never ``eval``):
numbers, the inputs' and derived values' names, + - * / ** and unary minus,
comparisons, ``and`` / ``or`` / ``not``, ``a if cond else b``, and the
functions in :data:`FUNCTIONS`. A choice input's value is its code, a string.

Limits: every number carries the range the handbook gives (or its figure's
axis covers), with the page. Outside a ``refuse`` limit the evaluation fails
and says which limit and where; outside a ``warn`` limit it computes and says
so. :func:`evaluate` is pure: the record, the values, and a resolver for the
records ``uses`` names.
"""

from __future__ import annotations

import ast
import math
from functools import lru_cache
from typing import Any, Callable, Optional

KIND = "covariate_model"
#: The units a covariate model's rate may be in, and their words.
RATE_UNITS = {
    "per_million_hours": "failures per million hours",
    "per_million_cycles": "failures per million cycles",
    "per_million_operations": "failures per million operations",
}
#: Per cycle (or operation): a prediction needs how many there are an hour.
PER_CYCLE_UNITS = {"per_million_cycles", "per_million_operations"}
SEVERITIES = ("refuse", "warn")
#: Deepest chain of ``uses`` (a pump uses a bearing record; nothing goes deeper than a few).
MAX_DEPTH = 4


def _interp(x: float, xs: list, ys: list) -> float:
    """Straight-line interpolation in a table (held flat beyond its ends)."""
    if len(xs) != len(ys) or len(xs) < 2:
        raise ValueError("interp needs two lists of the same length, at least two points")
    if x <= xs[0]:
        return float(ys[0])
    for (x0, y0), (x1, y1) in zip(zip(xs, ys), zip(xs[1:], ys[1:])):
        if x <= x1:
            return float(y0 + (y1 - y0) * (x - x0) / (x1 - x0))
    return float(ys[-1])


#: The functions an expression may call.
FUNCTIONS: dict[str, Callable[..., float]] = {
    "exp": math.exp, "ln": math.log, "log10": math.log10, "sqrt": math.sqrt, "abs": abs,
    "min": min, "max": max, "interp": _interp, "sinh": math.sinh, "cosh": math.cosh, "tanh": math.tanh,
    "atan": math.atan, "sin": math.sin, "cos": math.cos, "tan": math.tan, "pi": lambda: math.pi,
}
_BINOPS = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b, ast.Mult: lambda a, b: a * b,
           ast.Div: lambda a, b: a / b, ast.Pow: lambda a, b: a ** b}
_CMPOPS = {ast.Lt: lambda a, b: a < b, ast.LtE: lambda a, b: a <= b, ast.Gt: lambda a, b: a > b,
           ast.GtE: lambda a, b: a >= b, ast.Eq: lambda a, b: a == b, ast.NotEq: lambda a, b: a != b}


class CovariateError(ValueError):
    """Inputs the model can't use (or a model that's wrong), said for the user.
    ``problems`` lists every reason; the message joins them."""

    def __init__(self, problems: list[str]):
        self.problems = list(problems)
        super().__init__(" ".join(self.problems))


class ExpressionError(ValueError):
    pass


# ---- expressions ----------------------------------------------------------------------------

@lru_cache(maxsize=4096)
def parse(text: str) -> ast.AST:
    """The expression's tree, checked: only the nodes and functions this
    language allows. Raises :class:`ExpressionError`."""
    try:
        tree = ast.parse(str(text), mode="eval")
    except SyntaxError as exc:
        raise ExpressionError(f"can't read the expression '{text}': {exc.msg}") from None
    for node in ast.walk(tree):
        if isinstance(node, (ast.Expression, ast.Load, ast.Name, ast.IfExp, ast.Compare, ast.BoolOp, ast.And,
                             ast.Or, ast.Not, ast.USub, ast.UAdd, ast.List, ast.Tuple)
                      ) or type(node) in _BINOPS or type(node) in _CMPOPS:
            continue
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float, str)) and not isinstance(node.value, bool):
            continue
        if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
            continue
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd, ast.Not)):
            continue
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FUNCTIONS \
                and not node.keywords:
            continue
        raise ExpressionError(f"'{text}' uses something an expression may not ({type(node).__name__})")
    return tree


def names_in(text: str) -> set[str]:
    """The value names an expression reads (not its functions)."""
    tree = parse(text)
    funcs = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call)}
    called = {id(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
    del funcs
    return {n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and id(n) not in called}


def _eval(node: ast.AST, scope: dict[str, Any]) -> Any:
    if isinstance(node, ast.Expression):
        return _eval(node.body, scope)
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id not in scope:
            raise ExpressionError(f"no value named '{node.id}'")
        return scope[node.id]
    if isinstance(node, ast.BinOp):
        return _BINOPS[type(node.op)](_eval(node.left, scope), _eval(node.right, scope))
    if isinstance(node, ast.UnaryOp):
        v = _eval(node.operand, scope)
        return -v if isinstance(node.op, ast.USub) else (not v) if isinstance(node.op, ast.Not) else +v
    if isinstance(node, ast.Compare):
        left = _eval(node.left, scope)
        for op, right_node in zip(node.ops, node.comparators):
            right = _eval(right_node, scope)
            if not _CMPOPS[type(op)](left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            return all(_eval(v, scope) for v in node.values)
        return any(_eval(v, scope) for v in node.values)
    if isinstance(node, ast.IfExp):
        return _eval(node.body, scope) if _eval(node.test, scope) else _eval(node.orelse, scope)
    if isinstance(node, (ast.List, ast.Tuple)):
        return [_eval(e, scope) for e in node.elts]
    if isinstance(node, ast.Call):
        return FUNCTIONS[node.func.id](*[_eval(a, scope) for a in node.args])
    raise ExpressionError(f"can't evaluate {type(node).__name__}")


def evaluate_expr(text: str, scope: dict[str, Any]) -> Any:
    """The expression's value with ``scope``'s names. Arithmetic errors
    (division by zero, a log of a negative) raise ArithmeticError or
    ValueError for the caller to say in words."""
    return _eval(parse(text), scope)


# ---- the model's parts ----------------------------------------------------------------------

def model_of(rec: dict) -> dict:
    return rec.get("covariate_model") or {}


def rate_unit(rec: dict) -> str:
    return model_of(rec).get("rate_unit") or "per_million_hours"


def rate_unit_words(rec: dict) -> str:
    return RATE_UNITS.get(rate_unit(rec), rate_unit(rec))


def per_cycle(rec: dict) -> bool:
    return rate_unit(rec) in PER_CYCLE_UNITS


Resolver = Callable[[str], dict]


def inputs(rec: dict, resolve: Optional[Resolver] = None, prefix: str = "", group: Optional[str] = None,
           _depth: int = 0) -> list[dict]:
    """Every input the model reads, its own and (prefixed) those of the
    records its modes use, each with ``key`` (the name a value is given by)
    and ``group`` (None for the record's own, else the mode's name)."""
    out = []
    for i in model_of(rec).get("inputs") or []:
        out.append({**i, "key": f"{prefix}{i['name']}", "group": group})
    if resolve is None:
        return out
    for mode in model_of(rec).get("modes") or []:
        if mode.get("uses"):
            if _depth >= MAX_DEPTH:
                raise CovariateError([f"{rec.get('id')}: its modes use records too deeply."])
            sub = resolve(mode["uses"])
            label = mode.get("name") or sub.get("name")
            out += inputs(sub, resolve, f"{prefix}{mode.get('prefix') or mode['key']}.",
                          f"{group} › {label}" if group else label, _depth + 1)
    return out


def defaults(rec: dict, resolve: Optional[Resolver] = None) -> dict[str, Any]:
    """The handbook's default for every input that has one, by key."""
    return {i["key"]: i["default"] for i in inputs(rec, resolve) if i.get("default") is not None}


def _fmt(x: Any) -> str:
    if isinstance(x, (int, float)) and not isinstance(x, bool):
        if x == 0 or not math.isfinite(x):
            return str(x)
        return f"{float(f'{x:.4g}'):g}"
    return str(x)


def _page_text(page: Any) -> str:
    return f" (NSWC-11 p. {page})" if page else ""


def _limit_breached(value: float, limit: dict) -> Optional[str]:
    """The side of ``limit`` the value is past ('below' / 'above'), or None."""
    excl = bool(limit.get("exclusive"))
    lo, hi = limit.get("min"), limit.get("max")
    if lo is not None and (value < lo or (excl and value == lo)):
        return "below"
    if hi is not None and (value > hi or (excl and value == hi)):
        return "above"
    return None


def _limit_words(inp: dict, value: float, limit: dict, side: str) -> str:
    unit = f" {inp['unit']}" if inp.get("unit") else ""
    bound = limit["min"] if side == "below" else limit["max"]
    rel = ("must be more than" if limit.get("exclusive") else "must be at least") if side == "below" else (
        "must be less than" if limit.get("exclusive") else "must be at most")
    if limit.get("severity") == "warn":
        rel = rel.replace("must be", "the handbook's range is")
    label = inp.get("label") or inp["name"]
    group = f" ({inp['group']})" if inp.get("group") else ""
    why = f": {limit['why']}" if limit.get("why") else ""
    return f"{label}{group} is {_fmt(value)}{unit}; {rel} {_fmt(bound)}{unit}{why}{_page_text(limit.get('page'))}."


def _read_inputs(rec: dict, values: dict, prefix: str, refused: list, warnings: list, group: Optional[str]) -> dict:
    """The record's own inputs from ``values`` (by prefixed key) or their
    defaults, checked against their limits. Problems go on ``refused`` and
    ``warnings``; the scope (by plain name) is returned."""
    scope: dict[str, Any] = {}
    for inp in model_of(rec).get("inputs") or []:
        key = f"{prefix}{inp['name']}"
        info = {**inp, "group": group}
        raw = values.get(key)
        if raw is None or raw == "":
            raw = inp.get("default")
        label = inp.get("label") or inp["name"]
        where = f" ({group})" if group else ""
        if raw is None or raw == "":
            unit = f", in {inp['unit']}" if inp.get("unit") else ""
            refused.append(f"{label}{where} is needed{unit}: the handbook gives no default{_page_text(inp.get('page'))}.")
            continue
        if inp.get("kind") == "choice":
            codes = [c["code"] for c in inp.get("choices") or []]
            if str(raw) not in codes:
                refused.append(f"{label}{where} must be one of {', '.join(codes)}, not '{raw}'.")
                continue
            scope[inp["name"]] = str(raw)
            continue
        try:
            v = float(raw)
        except (TypeError, ValueError):
            refused.append(f"{label}{where} must be a number, not '{raw}'.")
            continue
        if not math.isfinite(v):
            refused.append(f"{label}{where} must be a finite number.")
            continue
        for limit in inp.get("limits") or []:
            side = _limit_breached(v, limit)
            if side:
                (refused if limit.get("severity", "refuse") == "refuse" else warnings).append(
                    _limit_words(info, v, limit, side))
        scope[inp["name"]] = v
    return scope


def _number(value: Any, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CovariateError([f"{what} isn't a number."])
    if not math.isfinite(value):
        raise CovariateError([f"{what} isn't finite for these inputs."])
    return float(value)


def _term(spec: dict, scope: dict, what: str) -> float:
    """A base or factor's value: a constant, an expression or a table lookup."""
    try:
        if "value" in spec:
            return _number(spec["value"], what)
        if "expr" in spec:
            return _number(evaluate_expr(spec["expr"], scope), what)
        if "table" in spec:
            t = spec["table"]
            by = t["by"] if isinstance(t["by"], list) else [t["by"]]
            cell: Any = t["values"]
            for name in by:
                key = scope.get(name)
                if not isinstance(cell, dict) or key not in cell:
                    raise CovariateError([f"{what}: the handbook's table has no value for {name} = {key}"
                                          f"{_page_text(spec.get('page'))}."])
                cell = cell[key]
            if cell is None:
                raise CovariateError([f"{what}: the handbook gives no value for this combination"
                                      f"{_page_text(spec.get('page'))}."])
            return _number(cell, what)
    except (ArithmeticError, ValueError, TypeError) as exc:
        if isinstance(exc, CovariateError):
            raise
        raise CovariateError([f"Can't compute {what} for these inputs ({exc}){_page_text(spec.get('page'))}."]) from None
    raise CovariateError([f"{what} has no value, expression or table."])


def _evaluate(rec: dict, values: dict, resolve: Optional[Resolver], prefix: str, group: Optional[str],
              refused: list, warnings: list, depth: int) -> Optional[dict]:
    model = model_of(rec)
    before = len(refused)
    scope = _read_inputs(rec, values, prefix, refused, warnings, group)
    own_ok = len(refused) == before
    # The modes that use other records read their own inputs; do them even when this record's
    # inputs are refused, so every missing input is listed at once.
    subs: dict[str, Optional[dict]] = {}
    for mode in model.get("modes") or []:
        if mode.get("uses"):
            if resolve is None or depth >= MAX_DEPTH:
                raise CovariateError([f"{rec.get('id')}: can't read the record its mode '{mode['key']}' uses."])
            sub = resolve(mode["uses"])
            label = mode.get("name") or sub.get("name")
            subs[mode["key"]] = _evaluate(sub, values, resolve, f"{prefix}{mode.get('prefix') or mode['key']}.",
                                          f"{group} › {label}" if group else label, refused, warnings, depth + 1)
    if not own_ok or any(v is None for v in subs.values()):
        return None  # something this record or a part of it needs is missing (already said)
    try:
        return _compute(rec, model, scope, subs, group, refused, warnings)
    except CovariateError as exc:
        refused.extend(exc.problems)
        return None


def _compute(rec: dict, model: dict, scope: dict, subs: dict, group: Optional[str], refused: list,
             warnings: list) -> Optional[dict]:
    derived = []
    try:
        for d in model.get("derived") or []:
            v = _number(evaluate_expr(d["expr"], scope), d.get("label") or d["name"])
            scope[d["name"]] = v
            derived.append({"name": d["name"], "symbol": d.get("symbol"), "label": d.get("label"),
                            "unit": d.get("unit"), "value": v})
            for limit in d.get("limits") or []:
                side = _limit_breached(v, limit)
                if side:
                    (refused if limit.get("severity", "refuse") == "refuse" else warnings).append(
                        _limit_words({**d, "group": group, "label": d.get("label") or d.get("symbol") or d["name"]},
                                     v, limit, side))
    except (ArithmeticError, ValueError, TypeError) as exc:
        if isinstance(exc, CovariateError):
            refused.extend(exc.problems)
        else:
            refused.append(f"Can't compute {d.get('label') or d['name']} for these inputs ({exc}).")
        return None
    for check in model.get("checks") or []:
        try:
            if check.get("when") and not evaluate_expr(check["when"], scope):
                continue
            ok = evaluate_expr(check["expr"], scope)
        except (ArithmeticError, ValueError, TypeError):
            ok = False
        if not ok:
            where = f" ({group})" if group else ""
            (refused if check.get("severity", "refuse") == "refuse" else warnings).append(
                f"{check['why']}{where}{_page_text(check.get('page'))}.")
    modes_out = []
    total = 0.0
    for mode in model.get("modes") or []:
        count = 1.0
        if mode.get("count"):
            count = float(scope.get(mode["count"], 1.0))
        if mode.get("uses"):
            sub = subs.get(mode["key"])
            if sub is None:
                continue
            each = sub["total"]
            row = {"key": mode["key"], "name": mode.get("name"), "symbol": mode.get("symbol"),
                   "uses": mode["uses"], "count": count, "each": each, "rate": each * count, "parts": sub,
                   **({"note": mode["note"]} if mode.get("note") else {})}
        else:
            base = _term(mode["base"], scope, f"{mode.get('name') or mode['key']}: {mode['base'].get('symbol') or 'base rate'}")
            factors = []
            each = base
            for f in mode.get("factors") or []:
                if f.get("when") and not evaluate_expr(f["when"], scope):
                    continue
                v = _term(f, scope, f"{f.get('name') or f['symbol']} ({f['symbol']})")
                factors.append({"symbol": f["symbol"], "name": f.get("name"), "value": v})
                each *= v
            row = {"key": mode["key"], "name": mode.get("name"), "symbol": mode.get("symbol"),
                   "base": {"symbol": mode["base"].get("symbol"), "value": base}, "factors": factors,
                   "count": count, "each": each, "rate": each * count,
                   **({"note": mode["note"]} if mode.get("note") else {})}
        if row["rate"] < 0 or not math.isfinite(row["rate"]):
            refused.append(f"{row['name'] or row['key']}'s rate comes out at {_fmt(row['rate'])} for these inputs, "
                           "which isn't a failure rate: check the inputs against the handbook's limits.")
        modes_out.append(row)
        total += row["rate"]
    return {"id": rec.get("id"), "name": rec.get("name"), "unit": rate_unit(rec), "unit_words": rate_unit_words(rec),
            "total": total, "modes": modes_out, "derived": derived, "inputs": scope}


def evaluate(rec: dict, values: Optional[dict] = None, resolve: Optional[Resolver] = None) -> dict:
    """λ for each mode and the total, in the record's rate unit, under
    ``values`` (by input key; a missing one takes the handbook's default).
    Returns {total, unit, unit_words, modes, derived, inputs, warnings}.
    Raises :class:`CovariateError` listing every input that's missing, not
    a number, or past a ``refuse`` limit."""
    if rec.get("kind") != KIND:
        raise CovariateError([f"'{rec.get('label') or rec.get('id')}' isn't a covariate model."])
    values = dict(values or {})
    known = {i["key"] for i in inputs(rec, resolve)}
    unknown = sorted(k for k in values if k not in known)
    refused: list[str] = []
    warnings: list[str] = []
    if unknown:
        refused.append(f"Unknown input{'s' if len(unknown) != 1 else ''} {', '.join(unknown)}: "
                       f"{rec.get('name')} reads {', '.join(sorted(known)) or 'none'}.")
    out = _evaluate(rec, values, resolve, "", None, refused, warnings, 0)
    if refused or out is None:
        raise CovariateError(refused or ["Can't compute this model."])
    out["warnings"] = warnings
    return out


# ---- checking a record ------------------------------------------------------------------------

def problems(rec: dict, resolve: Optional[Resolver] = None) -> list[str]:
    """Everything wrong with a covariate record's model (empty when it may ship):
    its inputs, limits, expressions (only names it has), tables (keyed by
    its choices), units and, with ``resolve``, the records it uses."""
    out: list[str] = []
    rid = rec.get("id") or "<no id>"

    def bad(msg: str) -> None:
        out.append(f"{rid}: {msg}")

    m = model_of(rec)
    if not m:
        bad("a covariate model needs covariate_model")
        return out
    if m.get("rate_unit") not in RATE_UNITS:
        bad(f"unknown rate_unit {m.get('rate_unit')!r}")
    for key in ("formula", "words", "equation", "page"):
        if not str(m.get(key) or "").strip():
            bad(f"covariate_model needs {key}")
    names: dict[str, dict] = {}
    for inp in m.get("inputs") or []:
        n = inp.get("name")
        if not isinstance(n, str) or not n.isidentifier():
            bad(f"input name {n!r} must be an identifier")
            continue
        if n in names:
            bad(f"input {n} is listed twice")
        names[n] = inp
        if not inp.get("label"):
            bad(f"input {n} needs a label")
        if inp.get("default") is not None and inp.get("default_basis") not in ("handbook", "neutral", "typical"):
            bad(f"input {n}'s default needs default_basis (handbook, neutral or typical)")
        if inp.get("kind") == "choice":
            codes = [c.get("code") for c in inp.get("choices") or []]
            if not codes or not all(isinstance(c, str) and c for c in codes) or len(set(codes)) != len(codes):
                bad(f"choice {n} needs distinct codes")
            if not all(c.get("label") for c in inp.get("choices") or []):
                bad(f"choice {n}: every choice needs a label")
            if inp.get("default") is not None and inp["default"] not in codes:
                bad(f"choice {n}'s default isn't one of its codes")
        elif inp.get("kind") == "number":
            if "unit" not in inp:
                bad(f"number {n} needs a unit ('' for a ratio)")
            limits = inp.get("limits") or []
            if not limits:
                bad(f"number {n} needs its limits (the handbook's range, or a physical one)")
            for limit in limits:
                if limit.get("min") is None and limit.get("max") is None:
                    bad(f"a limit on {n} needs a min or a max")
                if limit.get("severity", "refuse") not in SEVERITIES:
                    bad(f"a limit on {n} has an unknown severity")
                if limit.get("severity") == "warn" and not limit.get("page"):
                    bad(f"the handbook limit on {n} needs its page")
            d = inp.get("default")
            if d is not None:
                if not isinstance(d, (int, float)) or isinstance(d, bool):
                    bad(f"number {n}'s default must be a number")
                elif any(_limit_breached(float(d), lim) and lim.get("severity", "refuse") == "refuse" for lim in limits):
                    bad(f"number {n}'s default is outside its own limits")
        else:
            bad(f"input {n} has an unknown kind {inp.get('kind')!r}")
    scope = set(names)

    def check_expr(text: Any, what: str, allowed: set[str]) -> None:
        if not isinstance(text, str) or not text.strip():
            bad(f"{what} needs an expression")
            return
        try:
            missing = names_in(text) - allowed
        except ExpressionError as exc:
            bad(f"{what}: {exc}")
            return
        if missing:
            bad(f"{what} reads {', '.join(sorted(missing))}, which the model doesn't have")

    for d in m.get("derived") or []:
        if not str(d.get("name") or "").isidentifier() or d["name"] in scope:
            bad(f"derived value {d.get('name')!r} needs a new identifier")
            continue
        check_expr(d.get("expr"), f"derived {d['name']}", scope)
        scope.add(d["name"])
    for c in m.get("checks") or []:
        check_expr(c.get("expr"), "a check", scope)
        if c.get("when"):
            check_expr(c["when"], "a check's when", scope)
        if not c.get("why") or c.get("severity", "refuse") not in SEVERITIES:
            bad("a check needs why and a severity")

    def check_term(spec: Any, what: str) -> None:
        if not isinstance(spec, dict):
            bad(f"{what} must be an object")
            return
        given = [k for k in ("value", "expr", "table") if k in spec]
        if len(given) != 1:
            bad(f"{what} needs exactly one of value, expr or table")
            return
        if "value" in spec and not (isinstance(spec["value"], (int, float)) and math.isfinite(spec["value"])
                                    and spec["value"] >= 0):
            bad(f"{what}'s value must be a number of 0 or more")
        if "expr" in spec:
            check_expr(spec["expr"], what, scope)
        if "table" in spec:
            t = spec["table"]
            by = t.get("by") if isinstance(t.get("by"), list) else [t.get("by")]
            cell = t.get("values")
            for i, name in enumerate(by):
                inp = names.get(name)
                if not inp or inp.get("kind") != "choice":
                    bad(f"{what}'s table is keyed by {name!r}, which isn't one of its choice inputs")
                    return
                codes = {c["code"] for c in inp.get("choices") or []}
                rows = [cell] if i == 0 else [v for v in _walk(t.get("values"), i)]
                for row in rows:
                    if not isinstance(row, dict) or set(row) != codes:
                        bad(f"{what}'s table must give a value for every {name} choice")
                        return
        if not spec.get("page"):
            bad(f"{what} needs its page")

    keys = set()
    modes = m.get("modes") or []
    if not modes:
        bad("a covariate model needs at least one mode")
    for mode in modes:
        k = mode.get("key")
        if not k or k in keys:
            bad(f"mode key {k!r} must be set and distinct")
        keys.add(k)
        if not mode.get("name"):
            bad(f"mode {k} needs a name")
        if mode.get("count") and (mode["count"] not in names or names[mode["count"]].get("kind") != "number"):
            bad(f"mode {k}'s count must be a number input")
        if mode.get("uses"):
            if resolve is not None:
                try:
                    sub = resolve(mode["uses"])
                except LookupError:
                    bad(f"mode {k} uses {mode['uses']}, which isn't in the library")
                    continue
                if sub.get("kind") != KIND:
                    bad(f"mode {k} uses {mode['uses']}, which isn't a covariate model")
                elif rate_unit(sub) != rate_unit(rec) and not mode.get("note"):
                    bad(f"mode {k} uses a record in {rate_unit(sub)} in a model in {rate_unit(rec)}: say how "
                        "the handbook combines them in its note")
            continue
        check_term(mode.get("base"), f"mode {k}'s base")
        for f in mode.get("factors") or []:
            if not f.get("symbol") or not f.get("name"):
                bad(f"a factor of mode {k} needs a symbol and a name")
            if f.get("when"):
                check_expr(f["when"], f"factor {f.get('symbol')}'s when", scope)
            check_term(f, f"factor {f.get('symbol')} of mode {k}")
    return out


def _walk(values: Any, depth: int):
    """The dicts ``depth`` levels into a nested table."""
    level = [values]
    for _ in range(depth):
        level = [v for row in level if isinstance(row, dict) for v in row.values()]
    return level


def symbol_names(rec: dict) -> list[str]:
    """Every factor symbol across the record's own modes, once each, in order."""
    out: list[str] = []
    for mode in model_of(rec).get("modes") or []:
        for f in mode.get("factors") or []:
            if f["symbol"] not in out:
                out.append(f["symbol"])
    return out


def factor_count(rec: dict) -> int:
    """How many condition factors the record's own modes apply (a used record's count as one each)."""
    return sum(len(mode.get("factors") or []) or (1 if mode.get("uses") else 0)
               for mode in model_of(rec).get("modes") or [])


def base_text(mode: dict) -> str:
    """A mode's base rate in words: '2.4' or 'from the inputs'."""
    base = mode.get("base") or {}
    if "value" in base:
        return _fmt(base["value"])
    if mode.get("uses"):
        return "its own model"
    return "from the inputs"
