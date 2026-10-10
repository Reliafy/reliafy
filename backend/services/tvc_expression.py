"""A covariate's path over time typed as an expression in ``t`` (#52).

Someone writes ``90 if t % 24 < 8 else 30`` or ``60 * 1.1 ** floor(t / 1000)``
for how a block's load (temperature, duty…) changes over its life. That text
is untrusted and runs on the server, so it is evaluated by ``simpleeval``'s
base evaluator — never ``eval`` — and locked down further before it gets
there:

* **Names:** ``t``, ``pi`` and ``e`` only. **Functions:** ``sin``, ``cos``,
  ``tan``, ``exp``, ``log``, ``log2``, ``sqrt``, ``floor``, ``ceil``, ``abs``,
  ``min`` and ``max``, called by name with plain arguments.
* **No compound types:** no lists, tuples, dicts, sets, comprehensions,
  lambdas, attribute access, subscripts, strings or f-strings. The syntax tree
  is checked against an allow-list before anything is evaluated, and the base
  evaluator (not ``EvalWithCompoundTypes``) refuses them again.
* **No dunders:** text holding ``__`` is refused outright.
* **Size guards:** at most :data:`MAX_CHARS` characters, :data:`MAX_NODES`
  syntax nodes and :data:`MAX_DEPTH` levels of nesting, so parsing, checking
  and each evaluation are bounded.
* **Power guard:** every number is a float (integer literals are read as
  floats, ``floor``/``ceil`` return floats), so ``**`` can never build a huge
  integer; it runs as ``math.pow`` with the exponent capped at
  :data:`MAX_EXPONENT`, and an overflow is infinity (clipped later to the
  model's fitted range). Strings can't be written at all, so no string can
  grow.

A model can only be evaluated along a covariate that changes in *steps*, so
the expression must be step-valued: ``t`` may reach the value only through
``floor``, ``ceil``, ``//`` or a comparison. That proof is SurPyval's (the
same check ``StepSchedule.from_expression`` makes), run on the parsed tree
before the expression is ever evaluated.

:class:`Expression` evaluates one scalar ``t`` at a time, so ``if``/``else``
reads naturally. :func:`change_points` samples it over a window and finds
each step's time by bisection; :attr:`Expression.period` spots an expression
that depends on ``t`` only through ``t % P`` (a duty cycle), which then needs
sampling over one period only.
"""

from __future__ import annotations

import ast
import math
import time
from typing import Optional

import simpleeval

MAX_CHARS = 400
MAX_NODES = 150
MAX_DEPTH = 40
MAX_EXPONENT = 1e6
# Sampling: points per window by default and at most, and the share of
# sampled intervals that may hold a step before the window is "too fast".
BASE_POINTS = 2048
MAX_POINTS = 50_000
MAX_CHANGE_SHARE = 0.25
_GOLDEN = (math.sqrt(5.0) - 1.0) / 2.0
# Wall-clock guard for one materialisation (every evaluation is bounded, so
# this only matters for the largest windows).
TIME_LIMIT_S = 3.0

NAMES = ("t", "pi", "e")


class ExpressionError(ValueError):
    """An expression that can't be used, in plain words."""


def _f(x) -> float:
    if isinstance(x, bool):
        return float(x)
    if not isinstance(x, (int, float)):
        raise ExpressionError("Only numbers can be used in a schedule.")
    return float(x)


def _exp(x):
    try:
        return math.exp(_f(x))
    except OverflowError:
        return math.inf


def _floor(x):
    return float(math.floor(_f(x)))


def _ceil(x):
    return float(math.ceil(_f(x)))


def _log(x, base=None):
    return math.log(_f(x)) if base is None else math.log(_f(x), _f(base))


def _min(*args):
    return min(_f(a) for a in args)


def _max(*args):
    return max(_f(a) for a in args)


# name -> (callable, fewest args, most args)
FUNCTIONS = {
    "sin": (lambda x: math.sin(_f(x)), 1, 1),
    "cos": (lambda x: math.cos(_f(x)), 1, 1),
    "tan": (lambda x: math.tan(_f(x)), 1, 1),
    "exp": (_exp, 1, 1),
    "log": (_log, 1, 2),
    "log2": (lambda x: math.log2(_f(x)), 1, 1),
    "sqrt": (lambda x: math.sqrt(_f(x)), 1, 1),
    "floor": (_floor, 1, 1),
    "ceil": (_ceil, 1, 1),
    "abs": (lambda x: abs(_f(x)), 1, 1),
    "min": (_min, 2, 10),
    "max": (_max, 2, 10),
}


def _pow(a, b):
    a, b = _f(a), _f(b)
    if abs(b) > MAX_EXPONENT:
        raise ExpressionError(f"A power above {MAX_EXPONENT:,.0f} can't be used.")
    try:
        return math.pow(a, b)
    except OverflowError:
        # Odd whole powers keep the sign of a negative base.
        odd = b.is_integer() and int(b) % 2 == 1
        return -math.inf if (a < 0 and odd) else math.inf
    except ValueError:
        raise ExpressionError("A negative number can't be raised to a fractional power.") from None


def _div(a, b):
    return _f(a) / _f(b)


def _floordiv(a, b):
    return _f(a) // _f(b)


def _mod(a, b):
    return _f(a) % _f(b)


_OPERATORS = {
    ast.Add: lambda a, b: _f(a) + _f(b),
    ast.Sub: lambda a, b: _f(a) - _f(b),
    ast.Mult: lambda a, b: _f(a) * _f(b),
    ast.Div: _div,
    ast.FloorDiv: _floordiv,
    ast.Mod: _mod,
    ast.Pow: _pow,
    ast.USub: lambda a: -_f(a),
    ast.UAdd: lambda a: _f(a),
    ast.Not: lambda a: not a,
    ast.Eq: lambda a, b: _f(a) == _f(b),
    ast.NotEq: lambda a, b: _f(a) != _f(b),
    ast.Lt: lambda a, b: _f(a) < _f(b),
    ast.LtE: lambda a, b: _f(a) <= _f(b),
    ast.Gt: lambda a, b: _f(a) > _f(b),
    ast.GtE: lambda a, b: _f(a) >= _f(b),
}

# The syntax an expression may hold; anything else is refused before it runs.
_ALLOWED = (
    ast.Expression, ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare, ast.IfExp, ast.Call, ast.Name,
    ast.Constant, ast.Load, ast.And, ast.Or, *_OPERATORS,
)

# Words for the syntax people most often try, for the refusal message.
_SYNTAX_WORDS = {
    "Attribute": "attribute access (a dot after a name)",
    "Subscript": "indexing with [ ]",
    "List": "lists", "Tuple": "tuples (commas outside a function call)", "Dict": "dictionaries",
    "Set": "sets", "ListComp": "comprehensions", "SetComp": "comprehensions", "DictComp": "comprehensions",
    "GeneratorExp": "comprehensions", "Lambda": "lambda functions", "JoinedStr": "text",
    "NamedExpr": "assignments", "Starred": "* arguments", "keyword": "named arguments",
    "BitAnd": "the & operator", "BitOr": "the | operator", "BitXor": "the ^ operator",
    "LShift": "the << operator", "RShift": "the >> operator", "Invert": "the ~ operator",
    "MatMult": "the @ operator", "In": "'in'", "NotIn": "'not in'", "Is": "'is'", "IsNot": "'is not'",
    "Await": "await", "Yield": "yield", "YieldFrom": "yield",
}

_HELP = ("Use t (time), numbers, + - * / // % **, comparisons, 'x if condition else y', "
         "and the functions " + ", ".join(FUNCTIONS) + ".")


def _fmt(v: float) -> str:
    return f"{v:,.6g}"


def _check_tree(tree: ast.Expression) -> None:
    """Refuse any syntax outside the allow-list, unknown names and
    functions, wrong argument counts, and trees too big or deep."""
    count = 0
    stack = [(tree, 0)]
    while stack:
        node, depth = stack.pop()
        count += 1
        if count > MAX_NODES:
            raise ExpressionError("That expression is too long — keep it to a few terms.")
        if depth > MAX_DEPTH:
            raise ExpressionError("That expression is nested too deeply.")
        if not isinstance(node, _ALLOWED):
            what = _SYNTAX_WORDS.get(type(node).__name__, type(node).__name__)
            raise ExpressionError(f"A schedule can't use {what}. {_HELP}")
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                raise ExpressionError(f"A schedule can only use numbers, not text. {_HELP}")
        elif isinstance(node, ast.Name):
            if node.id not in NAMES:
                if node.id in FUNCTIONS:
                    raise ExpressionError(f"{node.id} is a function: call it with brackets, e.g. {node.id}(t / 100).")
                raise ExpressionError(f"Unknown name “{node.id}”: the only names are t, pi and e.")
        elif isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in FUNCTIONS:
                name = node.func.id if isinstance(node.func, ast.Name) else None
                raise ExpressionError(
                    (f"Unknown function “{name}”. " if name else "Only the listed functions can be called. ")
                    + f"The functions are {', '.join(FUNCTIONS)}.")
            if node.keywords:
                raise ExpressionError(f"A schedule can't use named arguments. {_HELP}")
            _, lo, hi = FUNCTIONS[node.func.id]
            n = len(node.args)
            if not lo <= n <= hi:
                want = str(lo) if lo == hi else f"{lo} to {hi}"
                raise ExpressionError(f"{node.func.id}() takes {want} argument{'s' if hi > 1 else ''}, not {n}.")
            # The function name itself is checked here, not as a free name.
            stack.extend((a, depth + 1) for a in node.args)
            continue
        stack.extend((child, depth + 1) for child in ast.iter_child_nodes(node))


class _Floats(ast.NodeTransformer):
    """Integer literals as floats, so no arithmetic ever runs on big ints."""

    def visit_Constant(self, node):
        if isinstance(node.value, int) and not isinstance(node.value, bool):
            try:
                return ast.copy_location(ast.Constant(float(node.value)), node)
            except OverflowError:
                raise ExpressionError("That number is too large.") from None
        return node


def _step_valued(tree: ast.Expression, text: str) -> bool:
    """SurPyval's proof that ``t`` reaches the value only through a
    quantizer (floor, ceil, //) or a comparison."""
    try:
        from surpyval.univariate.regression.tvc_schedule import _varies_continuously
    except ImportError:  # pragma: no cover - the public route makes the same check
        from surpyval import StepSchedule, StepValuedError

        try:
            StepSchedule.from_expression(text, 1.0)
        except StepValuedError as exc:
            return "not step-valued" not in str(exc)
        except Exception:  # noqa: BLE001 - a function the engine's own evaluator lacks
            return True
        return True
    return not _varies_continuously(tree.body)


def _period(tree: ast.Expression) -> Optional[float]:
    """``P`` when every ``t`` sits in ``t % P`` (one positive constant ``P``):
    the expression then repeats every ``P``. None otherwise."""
    periods = set()
    uses = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id == "t":
            uses += 1
        if (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod) and isinstance(node.left, ast.Name)
                and node.left.id == "t" and isinstance(node.right, ast.Constant)):
            p = float(node.right.value)
            if math.isfinite(p) and p > 0:
                periods.add(p)
            else:
                return None
            uses -= 1
    if uses or len(periods) != 1:
        return None
    return periods.pop()


def _time_constants(tree: ast.Expression) -> list:
    """Positive constants that set the time scale of a step: divisors,
    moduli and comparison bounds."""
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Div, ast.FloorDiv, ast.Mod)):
            if isinstance(node.right, ast.Constant):
                out.append(abs(float(node.right.value)))
        elif isinstance(node, ast.Compare):
            for side in [node.left, *node.comparators]:
                if isinstance(side, ast.Constant):
                    out.append(abs(float(side.value)))
    return [v for v in out if math.isfinite(v) and v > 0]


class Expression:
    """A checked, step-valued expression in ``t``; call it with a time."""

    def __init__(self, text):
        if not isinstance(text, str):
            raise ExpressionError("A schedule expression must be text, e.g. 60 if t < 1000 else 90.")
        text = text.strip()
        if not text:
            raise ExpressionError("Type an expression in t, e.g. 60 if t < 1000 else 90.")
        if len(text) > MAX_CHARS:
            raise ExpressionError(f"That expression is too long — at most {MAX_CHARS} characters.")
        if "__" in text:
            raise ExpressionError("Double underscores can't be used in a schedule.")
        if "\n" in text or "\r" in text or ";" in text:
            raise ExpressionError("A schedule is a single expression on one line.")
        try:
            tree = ast.parse(text, mode="eval")
        except (SyntaxError, ValueError, RecursionError, MemoryError):
            raise ExpressionError(f"That isn't a valid expression. {_HELP}") from None
        _check_tree(tree)
        if not _step_valued(tree, text):
            raise ExpressionError(
                "The value changes smoothly with t, but a covariate here changes in steps. Wrap t in "
                "floor(…) or ceil(…), e.g. 60 + 5 * floor(t / 500), or use a comparison, e.g. "
                "60 if t < 1000 else 90.")
        self.text = text
        self.uses_t = any(isinstance(n, ast.Name) and n.id == "t" for n in ast.walk(tree))
        self.period = _period(tree) if self.uses_t else None
        self.time_constants = _time_constants(tree)
        self._tree = _Floats().visit(tree).body
        functions = {name: fn for name, (fn, _, _) in FUNCTIONS.items()}
        # The base evaluator: no compound types, comprehensions or lambdas.
        self._evaluator = simpleeval.SimpleEval(
            operators=dict(_OPERATORS), functions=functions,
            names={"t": 0.0, "pi": math.pi, "e": math.e})
        self(0.0)  # a value at the start, or the reason there is none

    def __call__(self, t: float) -> float:
        self._evaluator.names["t"] = float(t)
        try:
            v = self._evaluator.eval(self.text, previously_parsed=self._tree)
        except ExpressionError:
            raise
        except ZeroDivisionError:
            raise ExpressionError(f"It divides by zero at t = {_fmt(t)}.") from None
        except (ValueError, OverflowError):
            raise ExpressionError(
                f"It has no value at t = {_fmt(t)} (a logarithm or square root of a negative number, "
                "or a number too large to round).") from None
        except simpleeval.InvalidExpression as exc:
            raise ExpressionError(f"{exc} {_HELP}") from None
        except (TypeError, RecursionError, MemoryError, AttributeError, KeyError):
            raise ExpressionError(f"That expression can't be evaluated. {_HELP}") from None
        v = _f(v)
        if math.isnan(v):
            raise ExpressionError(f"It isn't a number at t = {_fmt(t)}.")
        return v


def _resolution(expr: Expression, t0: float, t1: float) -> float:
    span = t1 - t0
    finest = span / MAX_POINTS
    coarsest = span / BASE_POINTS
    scale = min(expr.time_constants) / 8.0 if expr.time_constants else coarsest
    return max(finest, min(coarsest, scale))


def change_points(expr: Expression, t0: float, t1: float) -> tuple[list, list]:
    """``(times, values)``: the value from ``t0`` and each step in
    ``[t0, t1)``, the step times found by bisection between samples."""
    if not t1 > t0:
        return [float(t0)], [expr(t0)]
    if not expr.uses_t:
        return [float(t0)], [expr(t0)]
    step = _resolution(expr, t0, t1)
    n = int(math.floor((t1 - t0) / step)) + 1
    regular = [t0 + i * step for i in range(n)]
    # A second, irregular point in every interval (golden-ratio offsets), and
    # the times the expression compares t with: a path that repeats in step
    # with the grid can't hide between samples, and a threshold is never
    # stepped over.
    jitter = [t + step * (0.1 + 0.8 * ((i * _GOLDEN) % 1.0)) for i, t in enumerate(regular)]
    grid = sorted({*regular, *(t for t in jitter if t < t1), *(c for c in expr.time_constants if t0 < c < t1), t1})
    deadline = time.monotonic() + TIME_LIMIT_S
    values = []
    for i, t in enumerate(grid):
        if i % 2048 == 0 and time.monotonic() > deadline:
            raise ExpressionError("That schedule takes too long to work out over this window.")
        values.append(expr(t))
    changes = [i for i in range(len(grid) - 1) if values[i] != values[i + 1]]
    if len(changes) > MAX_CHANGE_SHARE * len(grid):
        raise ExpressionError(
            f"The value changes too often to follow over 0 to {_fmt(t1)}: more than once every "
            f"{_fmt(step * 2)}. Use a slower schedule, or a repeating one written with t % period.")
    times, out = [float(t0)], [values[0]]
    for i in changes:
        lo, hi, a, b = grid[i], grid[i + 1], values[i], values[i + 1]
        for _ in range(8):  # more than one step inside one sample interval
            edge, after = _bisect(expr, lo, hi, a)
            edge = edge if edge > times[-1] else hi
            times.append(edge)
            out.append(after)
            if after == b:
                break
            lo, a = edge, after
        else:
            raise ExpressionError(f"The value changes too often near t = {_fmt(lo)} to follow.")
        if time.monotonic() > deadline:
            raise ExpressionError("That schedule takes too long to work out over this window.")
    return times, out


def _bisect(expr: Expression, lo: float, hi: float, a: float) -> tuple[float, float]:
    """The first time after ``lo`` the value stops being ``a`` (to within
    floating point), as the shortest decimal within a billionth of it (1000
    rather than 1000.0000000001 for ``t > 1000``), and the value there."""
    tol = max(abs(hi) * 1e-12, 1e-12)
    for _ in range(80):
        if hi - lo <= tol:
            break
        mid = lo + (hi - lo) / 2.0
        if expr(mid) == a:
            lo = mid
        else:
            hi = mid
    after = expr(hi)
    near = max(abs(hi) * 1e-9, 1e-12)
    for digits in range(1, 17):
        c = float(f"{hi:.{digits}g}")
        if abs(c - hi) <= near:
            return c, after
    return hi, after
