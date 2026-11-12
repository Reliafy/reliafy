"""Download as Python for every model kind: the pieces each script shares.

Each kind's script (non-repairable, regression, time-varying covariates,
repairable, accelerated life, degradation, test plans) is built by its own
module from these parts, so every download reads the same way:

* a header saying what the script does, the library versions it was made
  with (a ``requirements`` line and the install commands), and how to run it;
* the data embedded as text, after the app's own preparation (censor flags
  the right way round, times in the model's unit), with a comment saying
  what was done;
* the same SurPyval call the app made, then the page's headline numbers,
  printed as ``label: value`` lines at the app's levels (90% one-sided for a
  life, 90% two-sided otherwise).

The printed lines are what the tests compare with the page, so keep their
labels stable: ``print_value`` / ``print_interval`` / ``print_bound`` write
them, and :func:`read_printed` reads them back.
"""

from __future__ import annotations

import io
import math
import re
from typing import Any, Iterable, Optional

import numpy as np
import pandas as pd

from backend.services import rbd_export

# Every interval the app shows is at 90% (backend/levels.py).
LEVEL_WORDS = "90%"


def versions() -> dict:
    """The SurPyval / RePyability versions this deployment runs."""
    return rbd_export.detect_versions()


def filename(name: str, fallback: str) -> str:
    """A safe file name for a download called ``name``."""
    stem = rbd_export.slugify(name or "")
    if stem == "reliability_block_diagram":  # slugify's own fallback
        stem = fallback
    return f"{stem}.py"


def _one_line(text: Any) -> str:
    return " ".join(str(text or "").split())


MODEL_LEAD = ("Exported from Reliafy. It refits the model the same way the app did, from",
              "the data embedded below, and prints the numbers the page shows.")


def header(title: str, what: str, *, notes: Iterable[str] = (), unit: str = "",
           needs_repyability: bool = False, lead: Iterable[str] = MODEL_LEAD) -> list[str]:
    """The script's docstring: what it does (``lead``: the opening sentence,
    a refit by default), the pinned versions and how to install them."""
    v = versions()
    pins = [f"surpyval=={v['surpyval']}"]
    if needs_repyability:
        pins.append(f"repyability=={v['repyability']}")
    lines = [
        '"""' + _one_line(title).replace('"""', "'''") + f": {what}",
        "",
        *lead,
    ]
    if unit:
        lines += ["", f"Times are in {unit}."]
    for note in notes:
        lines += ["", *_wrap(note)]
    lines += [
        "",
        f"Made with SurPyval {v['surpyval']}" + (f" and RePyability {v['repyability']}" if needs_repyability else "")
        + ". Other versions may give slightly different numbers.",
        "",
        f"requirements: {' '.join(pins)}",
        "",
        "Install and run:",
    ]
    if needs_repyability:
        lines += [f"    {c}" for c in rbd_export.install_commands(v)]
    else:
        lines.append(f'    pip install "surpyval=={v["surpyval"]}"')
    lines += ["    python this_file.py", '"""', ""]
    return lines


def _wrap(text: str, width: int = 78, prefix: str = "") -> list[str]:
    words, out, line = _one_line(text).split(), [], prefix
    for w in words:
        if len(line) + len(w) + 1 > width and line.strip():
            out.append(line.rstrip())
            line = prefix
        line += w + " "
    if line.strip():
        out.append(line.rstrip())
    return out


def comment(text: str) -> list[str]:
    """``text`` as ``#`` comment lines."""
    return _wrap(text, prefix="# ")


def csv_text(df: pd.DataFrame) -> str:
    """``df`` as CSV that reads back to the same numbers (pandas writes each
    float as its shortest exact text: 0.586, not 0.58599999999999997)."""
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue()


def csv_block(var: str, df: pd.DataFrame) -> list[str]:
    """``VAR = \"\"\"<csv>\"\"\"`` lines (the data embedded as text)."""
    text = csv_text(df).replace("\\", "\\\\").replace('"""', '\\"\\"\\"')
    return [f'{var} = """{text}"""']


def num(value: Any) -> str:
    """A Python literal for a number that reads back exactly."""
    if value is None:
        return "None"
    f = float(value)
    if math.isnan(f):
        return "np.nan"
    if math.isinf(f):
        return "np.inf" if f > 0 else "-np.inf"
    if f == int(f) and abs(f) < 1e15:
        return repr(int(f)) if isinstance(value, (int, np.integer)) else repr(f)
    return repr(f)


def array(values: Optional[Iterable]) -> str:
    """``np.array([...])`` for ``values`` (exact; infinities kept)."""
    if values is None:
        return "None"
    vals = np.asarray(list(values), dtype=float).ravel()
    return "np.array([" + ", ".join(num(v) for v in vals) + "])"


def literal(value: Any) -> str:
    """A Python literal for plain data (dicts, lists, strings, numbers)."""
    if isinstance(value, dict):
        return "{" + ", ".join(f"{literal(k)}: {literal(v)}" for k, v in value.items()) + "}"
    if isinstance(value, (list, tuple)):
        inner = ", ".join(literal(v) for v in value)
        return f"[{inner}]" if isinstance(value, list) else f"({inner}{',' if len(value) == 1 else ''})"
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return repr(value)
    if isinstance(value, (int, float, np.integer, np.floating)):
        return num(value)
    return repr(value)


# The helpers every script defines once, before its numbers.
PRINT_HELPERS = '''
def fmt(value):
    """A number to 6 significant figures, or "none" when there isn't one."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "none"
    return f"{value:.6g}" if np.isfinite(value) else "none"


def print_value(label, value, unit=""):
    """One headline number."""
    print(f"{label}: {fmt(value)}{(' ' + unit) if unit and fmt(value) != 'none' else ''}")


def print_interval(label, value, low, high, unit=""):
    """A number with its 90% two-sided interval."""
    tail = f" ({fmt(low)} to {fmt(high)}, 90% two-sided)" if low is not None and high is not None else ""
    print(f"{label}: {fmt(value)}{(' ' + unit) if unit else ''}{tail}")


def print_bound(label, value, bound, side="lower", unit=""):
    """A number with its 90% one-sided bound (lower for a life)."""
    tail = f" ({side} bound {fmt(bound)}, 90% one-sided)" if bound is not None and np.isfinite(float(bound)) else ""
    print(f"{label}: {fmt(value)}{(' ' + unit) if unit else ''}{tail}")
'''.strip("\n").splitlines()


_LINE = re.compile(r"^(?P<label>[^:]+): (?P<value>-?[0-9.eE+-]+|none)(?P<rest>.*)$")
_TAIL_INTERVAL = re.compile(r"\((?P<lo>-?[0-9.eE+-]+|none) to (?P<hi>-?[0-9.eE+-]+|none), 90% two-sided\)")
_TAIL_BOUND = re.compile(r"\((?:lower|upper) bound (?P<b>-?[0-9.eE+-]+|none), 90% one-sided\)")


def _f(text: Optional[str]) -> Optional[float]:
    if text is None or text == "none":
        return None
    try:
        return float(text)
    except ValueError:
        return None


def read_printed(stdout: str) -> dict:
    """The ``label: value`` lines a script printed, as ``{label: {"value",
    "low", "high", "bound"}}`` (the tests compare them with the page)."""
    out: dict = {}
    for line in stdout.splitlines():
        m = _LINE.match(line.strip())
        if not m:
            continue
        rest = m["rest"]
        entry = {"value": _f(m["value"]), "low": None, "high": None, "bound": None}
        iv = _TAIL_INTERVAL.search(rest)
        if iv:
            entry["low"], entry["high"] = _f(iv["lo"]), _f(iv["hi"])
        bd = _TAIL_BOUND.search(rest)
        if bd:
            entry["bound"] = _f(bd["b"])
        out[m["label"].strip()] = entry
    return out


def assemble(*parts: Iterable[str]) -> str:
    """The script from its parts, ending in one newline."""
    lines: list[str] = []
    for part in parts:
        lines.extend(part)
    return "\n".join(lines).rstrip("\n") + "\n"
