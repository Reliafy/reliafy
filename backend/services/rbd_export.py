"""Export a saved RBD as a standalone, runnable Python script.

:func:`to_python` turns a builder graph (the React Flow ``nodes``/``edges``
document :mod:`backend.services.rbd_analysis` analyses) into a PEP 8 script
that rebuilds the same diagram with SurPyval + RePyability and runs the same
calculation the app does:

* a **non-repairable** diagram prints the system reliability at a few times,
  the MTTF (the integral of R(t), exactly as the app computes it), the B10/B50
  lives and the six importance measures at the app's representative time;
* a **repairable** diagram prints the exact steady-state availability, mean
  up/down time and failure frequency, then runs the same seeded availability
  simulation (``t_simulation``, ``N``) as the app.

The translation mirrors ``rbd_analysis`` block by block — one RBD node per
builder node, series/parallel count blocks and hot standby as a single
equivalent node, cold standby as a ``StandbyModel``, k-of-n voting gates as a
perfectly reliable node with ``k``, beta-factor common-cause groups, nested
sub-systems as nested RBDs, pinned blocks via ``working_nodes`` /
``broken_nodes``. Anything a plain script can't reproduce (a fitted
proportional-hazards / non-parametric / load-sharing model, an unresolvable
sub-system, a block with no life model) becomes a clearly marked placeholder
that raises with an explanation instead of silently computing something else.

The output is deterministic for a given graph and ``exported_at``: nodes and
edges keep the graph's own order and every generated name is stable.
"""

from __future__ import annotations

import builtins
import json
import keyword
import re
import textwrap
import unicodedata
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Optional

import numpy as np

from backend.fitting import DISTRIBUTIONS
from backend.services import rbd_analysis

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_VERSIONS = {"surpyval": "0.20.0", "repyability": "0.8.0"}
_SURPYVAL_GIT = "https://github.com/derrynknife/SurPyval.git"
_REPYABILITY_GIT = "https://github.com/derrynknife/RePyability.git"

# Names the script itself uses at module level; block variables avoid them
# (as well as keywords and builtins such as ``filter`` or ``input``).
_RESERVED = {
    "np", "os", "json", "surv", "plt", "rbd", "rbd_independent", "main",
    "missing_model", "voting_gate", "mean_time_to_failure", "b_life",
    "save_results", "results",
}


# ---------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------
def _pin_from(path: Path, pattern: str) -> Optional[str]:
    try:
        match = re.search(pattern, path.read_text(encoding="utf-8"))
    except OSError:
        return None
    return match.group(1) if match else None


def _installed(dist: str) -> Optional[str]:
    try:
        from importlib.metadata import version

        return version(dist)
    except Exception:  # noqa: BLE001 - not installed / no metadata
        return None


@lru_cache(maxsize=1)
def detect_versions() -> dict:
    """The SurPyval / RePyability versions this deployment is built with.

    Read from the pins the build uses (SurPyval in ``requirements.txt``,
    RePyability in the ``Dockerfile``); in the runtime image, where only
    ``requirements.txt`` is copied, fall back to the installed package and
    finally to the known-good defaults.
    """
    surpyval = _pin_from(
        _REPO_ROOT / "requirements.txt", r"SurPyval\.git@v?([0-9][\w.\-]*)"
    ) or _installed("surpyval")
    repyability = _pin_from(
        _REPO_ROOT / "Dockerfile", r"RePyability\.git@v?([0-9][\w.\-]*)"
    ) or _installed("repyability")
    return {
        "surpyval": surpyval or _DEFAULT_VERSIONS["surpyval"],
        "repyability": repyability or _DEFAULT_VERSIONS["repyability"],
    }


# ---------------------------------------------------------------------------
# Small formatting helpers
# ---------------------------------------------------------------------------
def slugify(name: str) -> str:
    """A safe, importable file stem for a diagram name."""
    text = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore")
    slug = re.sub(r"[^a-z0-9]+", "_", text.decode("ascii").lower()).strip("_")
    if len(slug) > 60:  # trim at a word boundary
        slug = slug[:61].rsplit("_", 1)[0] or slug[:60]
    if not slug:
        return "reliability_block_diagram"
    return slug if not slug[0].isdigit() else f"rbd_{slug}"


def filename(name: str) -> str:
    """The download file name for a diagram called ``name``."""
    return f"{slugify(name)}.py"


def _one_line(text: Any) -> str:
    """Collapse whitespace/control characters so text is safe in a comment."""
    out = "".join(" " if unicodedata.category(c)[0] == "C" else c for c in str(text))
    return re.sub(r"\s+", " ", out).strip()


def _lit(value: Any) -> str:
    """A Python literal for an id/label, double-quoted for strings (a JSON
    string is also a valid Python string literal)."""
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    return repr(value)


def _num(value: Any) -> str:
    """A float literal that round-trips exactly (``repr``)."""
    return repr(float(value))


def _comment(text: str, indent: str = "") -> list[str]:
    """``text`` as ``#`` comment lines wrapped to 79 columns."""
    return [
        f"{indent}# {ln}"
        for ln in textwrap.wrap(
            _one_line(text), width=77 - len(indent),
            break_long_words=False, break_on_hyphens=False,
        )
    ]


def _str_lines(text: str, indent: str) -> list[str]:
    """A long string literal split into implicitly concatenated pieces."""
    pieces = textwrap.wrap(
        _one_line(text), width=max(79 - len(indent) - 4, 30),
        drop_whitespace=False, break_long_words=True, break_on_hyphens=False,
    ) or [""]
    return [f"{indent}{_lit(piece)}" for piece in pieces]


class _Names:
    """Stable, unique snake_case identifiers derived from block labels."""

    def __init__(self):
        self.used: set[str] = set(_RESERVED)

    def make(self, label: str, fallback: str = "block") -> str:
        text = unicodedata.normalize("NFKD", label or "").encode("ascii", "ignore")
        base = re.sub(r"[^a-z0-9]+", "_", text.decode("ascii").lower()).strip("_")
        base = base[:40].rstrip("_") or fallback
        if base[0].isdigit():
            base = f"{fallback}_{base}"
        if keyword.iskeyword(base) or base in dir(builtins):
            base = f"{base}_block"
        name, i = base, 2
        while name in self.used:
            name = f"{base}_{i}"
            i += 1
        self.used.add(name)
        return name


@lru_cache(maxsize=None)
def _surpyval_attr(dist_id: str) -> Optional[str]:
    """The ``surpyval.<Name>`` attribute of a distribution in DISTRIBUTIONS."""
    import surpyval

    entry = DISTRIBUTIONS.get(dist_id)
    if entry is None:
        return None
    for attr in sorted(dir(surpyval)):
        if getattr(surpyval, attr, None) is entry["dist"]:
            return attr
    return None


# Unit hints for the parameters whose unit is the diagram's time unit.
_PARAM_UNITS = {
    ("weibull", "alpha"): "{u}",
    ("exponential", "failure_rate"): "1/{u}",
    ("normal", "mu"): "{u}",
    ("normal", "sigma"): "{u}",
    ("lognormal", "mu"): "ln({u})",
    ("rayleigh", "sigma"): "{u}",
    ("loglogistic", "alpha"): "{u}",
    ("expo_weibull", "alpha"): "{u}",
}


# ---------------------------------------------------------------------------
# Life models -> SurPyval expressions
# ---------------------------------------------------------------------------
class _Missing(Exception):
    """A block whose model can't be reproduced in a plain script."""


def _effective_spec(model: Optional[dict], resolve_model) -> Optional[dict]:
    """The model spec with a saved model's fitted parameters filled in.

    The app analyses the parameters stored on the block (a snapshot of the
    saved fit taken when it was picked), so those win; ``resolve_model`` only
    supplies what the block lacks (parameters, kind, name).
    """
    if not model:
        return model
    model_id = model.get("modelId") or model.get("model_id")
    if not model_id or resolve_model is None:
        return model
    has_params = bool(model.get("params")) and model.get("distribution_id")
    if has_params and model.get("kind") and model.get("name"):
        return model
    try:
        saved = resolve_model(model_id)
    except Exception:  # noqa: BLE001 - treated as unresolvable
        saved = None
    if not saved:
        return {**model, "_unresolved": True} if not has_params else model
    merged = dict(model)
    for key in ("kind", "name", "distribution", "unit"):
        if not merged.get(key) and saved.get(key):
            merged[key] = saved[key]
    if not has_params:
        for key in ("distribution_id", "distribution", "params", "extras"):
            if saved.get(key) is not None:
                merged[key] = saved[key]
    return merged


def _describe(model: dict) -> str:
    return _one_line(model.get("distribution") or model.get("name") or "model")


def _dist_expr(model: Optional[dict], label: str, unit: str) -> tuple[str, str]:
    """``(expression, description)`` for a plain parametric life model, else
    raise :class:`_Missing` with a user-facing explanation."""
    if not model:
        raise _Missing(
            f"Block '{label}' has no life model in Reliafy. Set its "
            "distribution here, e.g. surv.Weibull.from_params([alpha, beta])."
        )
    kind = model.get("kind")
    what = _describe(model)
    if kind == "regression":
        raise _Missing(
            f"Block '{label}' uses a fitted proportional-hazards/regression "
            f"model ({what}), which Reliafy evaluates at the covariate values "
            "set on the calculator. Set its parameters here, e.g. "
            "surv.Weibull.from_params([alpha, beta]) for the covariates you "
            "want."
        )
    if kind == "nonparametric":
        raise _Missing(
            f"Block '{label}' uses a non-parametric model ({what}) fitted to "
            "a saved dataset, which isn't included in this script. Set a "
            "parametric life model here, or refit it with e.g. "
            "surv.KaplanMeier.fit(x, c)."
        )
    if model.get("_unresolved"):
        raise _Missing(
            f"Block '{label}' uses a saved model that couldn't be read. Set "
            "its parameters here, e.g. surv.Weibull.from_params([alpha, beta])."
        )
    dist_id = model.get("distribution_id")
    entry = DISTRIBUTIONS.get(dist_id)
    attr = _surpyval_attr(dist_id) if entry else None
    if entry is None or attr is None:
        raise _Missing(
            f"Block '{label}' uses a distribution ('{what}') Reliafy can't "
            "analyse in an RBD. Set a supported life model here."
        )
    params = model.get("params") or []
    try:
        by_name = {p["name"]: float(p["value"]) for p in params if "name" in p}
        names = list(getattr(entry["dist"], "param_names", []) or [])
        if names and all(n in by_name for n in names):
            pairs = [(n, by_name[n]) for n in names]
        else:  # the order they were given in, as the app does
            pairs = [(p.get("name") or f"p{i}", float(p["value"]))
                     for i, p in enumerate(params)]
    except (KeyError, TypeError, ValueError):
        pairs = []
    if not pairs:
        raise _Missing(
            f"Block '{label}' is missing its {what} parameters. Set them here."
        )
    extras = []
    for key in ("gamma", "p", "f0"):
        value = (model.get("extras") or {}).get(key)
        if value is not None:
            extras.append((key, float(value)))
    args = ", ".join(_num(v) for _, v in pairs)
    expr = f"surv.{attr}.from_params([{args}]"
    expr += "".join(f", {k}={_num(v)}" for k, v in extras) + ")"

    def fmt(n, v):
        hint = _PARAM_UNITS.get((dist_id, n)) if unit else None
        return f"{n}={v:g}" + (f" {hint.format(u=unit)}" if hint else "")

    desc = f"{entry['name']}(" + ", ".join(fmt(n, v) for n, v in pairs)
    desc += "".join(f", {k}={v:g}" for k, v in extras) + ")"
    return expr, desc


# ---------------------------------------------------------------------------
# Script assembly
# ---------------------------------------------------------------------------
class _Script:
    """Accumulates the block definitions and records what gets imported."""

    def __init__(self, unit: str, resolve_model, resolve_subsystem):
        self.unit = unit
        self.resolve_model = resolve_model
        self.resolve_subsystem = resolve_subsystem
        self.names = _Names()
        self.imports: set[str] = set()
        self.uses_surv = False
        self.uses_missing = False
        self.uses_voting_gate = False
        self.lines: list[str] = []  # block definitions, in order
        self.subsystems: dict[str, str] = {}  # rbd id -> variable
        self.placeholders: list[str] = []  # labels of raising blocks

    # -- emitters ---------------------------------------------------------
    def comment(self, text: str) -> None:
        self.lines.extend(_comment(text))

    def missing(self, var: str, message: str, label: str) -> str:
        self.uses_missing = True
        self.placeholders.append(label)
        self.lines.append(
            "# TODO: placeholder - this block raises until you set its model."
        )
        self.lines.append(f"{var} = missing_model(")
        self.lines.extend(_str_lines(message, "    "))
        self.lines.append(")")
        return var

    def dist(self, spec, label, var, prefix_comment: str = "") -> str:
        """Emit ``var = surv.X.from_params(...)`` (or a placeholder)."""
        spec = _effective_spec(spec, self.resolve_model)
        try:
            expr, desc = _dist_expr(spec, label, self.unit)
        except _Missing as exc:
            return self.missing(var, str(exc), label)
        self.uses_surv = True
        head = f"{prefix_comment or label}: {desc}"
        self.comment(head)
        if spec and (spec.get("modelId") or spec.get("model_id")):
            name = _one_line(spec.get("name") or "")
            self.comment(f'Fitted in Reliafy - saved model "{name}".' if name
                         else "Fitted in Reliafy (a saved model).")
        if spec and spec.get("placeholder"):
            self.lines.append(
                "# NOTE: placeholder parameters - illustrative values, "
                "replace with real data."
            )
        line = f"{var} = {expr}"
        if len(line) > 79:
            line = f"{var} = (\n    {expr}\n)"
        self.lines.append(line)
        return var

    # -- non-repairable blocks -------------------------------------------
    def block(self, node: dict, visited: frozenset) -> tuple[str, Optional[int]]:
        """Emit one builder node's reliability; return ``(expr, k)``."""
        ntype = node.get("type")
        data = node.get("data") or {}
        label = _one_line(data.get("label") or node.get("id"))
        pinned = data.get("state") in ("working", "failed")

        if ntype == "knode":
            n = max(int(data.get("n") or 1), 1)
            self.imports.add("PerfectReliability")
            return "PerfectReliability", n

        var = self.names.make(label)
        snapshot = (len(self.lines), len(self.placeholders), set(self.imports),
                    self.uses_surv, self.uses_missing, dict(self.subsystems))
        self.lines.append("")
        expr = self._nonrepairable_block(node, ntype, data, label, var, visited)
        if pinned and len(self.placeholders) > snapshot[1]:
            # Reliafy analyses a pinned block via the override alone, so a
            # block it can't model stands in as perfectly reliable (never
            # consulted) rather than stopping the script.
            (start, n_missing, self.imports, self.uses_surv,
             self.uses_missing, self.subsystems) = snapshot
            del self.lines[start:]
            del self.placeholders[n_missing:]
            self.lines.append("")
            self.comment(
                f"{label}: pinned {data.get('state')} in Reliafy - its model "
                "isn't needed (the override below fixes its state), so it "
                "stands in as perfectly reliable."
            )
            self.imports.add("PerfectReliability")
            self.lines.append(f"{var} = PerfectReliability")
            return var, None
        return expr, None

    def _nonrepairable_block(self, node, ntype, data, label, var, visited):
        if ntype == "component":
            return self.dist(data.get("model"), label, var)

        if ntype in ("series", "parallel"):
            count = max(int(data.get("n") or 1), 1)
            unit_var = self.dist(data.get("model"), f"{label} (one unit)",
                                 self.names.make(f"{var}_unit"))
            self.imports.add("RepeatedNode")
            meaning = ("all must work" if ntype == "series"
                       else "any one is enough")
            self.comment(f"{label}: {count} identical units in {ntype} "
                         f"({meaning}).")
            self.lines.append(
                f'{var} = RepeatedNode({unit_var}, {count}, "{ntype}")'
            )
            return var

        if ntype == "standby":
            return self._standby(data, label, var)

        if ntype == "loadshare":
            return self.missing(var, (
                f"Block '{label}' is a load-sharing group whose units follow a "
                "fitted accelerated-failure-time (AFT) load-life model saved "
                "in Reliafy, which isn't included in this script. Rebuild it "
                "with repyability.LoadSharingModel([aft_model] * units, "
                "load=..., k=...) using your own fitted AFT model."
            ), label)

        if ntype == "subsystem":
            return self._subsystem(data, label, var, visited)

        return self.missing(var, (
            f"Block '{label}' is an unsupported block type ('{ntype}')."
        ), label)

    def _standby(self, data, label, var):
        spares = int(data.get("spares") or 1)
        spares = max(spares, 0)
        primary_spec = data.get("model")
        spare_spec = data.get("standbyModel") or data.get("model")
        same = spare_spec is primary_spec or spare_spec == primary_spec
        if same:
            duty = self.dist(primary_spec, f"{label} (each unit)",
                             self.names.make(f"{var}_unit"))
            spare = duty
        else:
            duty = self.dist(primary_spec, f"{label} (duty unit)",
                             self.names.make(f"{var}_duty"))
            spare = self.dist(spare_spec, f"{label} (spare)",
                              self.names.make(f"{var}_spare"))
        n_units = 1 + spares
        if data.get("cold"):
            try:
                switch = float(data.get("startProb", 1.0))
            except (TypeError, ValueError):
                switch = 1.0
            self.imports.add("StandbyModel")
            self.comment(
                f"{label}: cold standby - the duty unit plus {spares} "
                f"dormant spare{'s' if spares != 1 else ''}, switched in on "
                f"failure (each start succeeds with probability {switch:g})."
            )
            units = ", ".join([duty] + [spare] * spares)
            line = f"{var} = StandbyModel([{units}], k=1, " \
                   f"switching_probability={_num(switch)})"
            if len(line) > 79:
                self.lines.append(f"{var} = StandbyModel(")
                self.lines.append(f"    [{units}],")
                self.lines.append("    k=1,")
                self.lines.append(f"    switching_probability={_num(switch)},")
                self.lines.append(")")
            else:
                self.lines.append(line)
            return var
        self.comment(
            f"{label}: hot standby - all {n_units} units run from t=0, so it "
            "is active parallel redundancy (any one unit is enough)."
        )
        if same:
            self.imports.add("RepeatedNode")
            self.lines.append(
                f'{var} = RepeatedNode({duty}, {n_units}, "parallel")'
            )
            return var
        # Different spare model: a small nested parallel diagram.
        self.imports.add("NonRepairableRBD")
        members = [("duty", duty)] + [
            (f"spare{i + 1}", spare) for i in range(spares)
        ]
        self.lines.append(f"{var} = NonRepairableRBD(")
        self.lines.append("    [")
        for key, _ in members:
            self.lines.append(f'        ("in", "{key}"), ("{key}", "out"),')
        self.lines.append("    ],")
        self.lines.append("    {")
        self.lines.extend(f'        "{key}": {v},' for key, v in members)
        self.lines.append("    },")
        self.lines.append('    input_node="in",')
        self.lines.append('    output_node="out",')
        self.lines.append(")")
        return var

    def _subsystem(self, data, label, var, visited):
        ref = data.get("rbd") or {}
        sub_id = ref.get("id")
        sub_name = _one_line(ref.get("name") or "sub-system")
        if not sub_id:
            return self.missing(var, (
                f"Block '{label}' is a sub-system with no diagram selected."
            ), label)
        if sub_id in visited:
            return self.missing(var, (
                f"Block '{label}': sub-system '{sub_name}' refers to itself "
                "(a cycle), so it can't be built."
            ), label)
        if sub_id in self.subsystems:
            self.comment(f"{label}: the nested diagram '{sub_name}' again.")
            self.lines.append(f"{var} = {self.subsystems[sub_id]}")
            return var
        graph = None
        if self.resolve_subsystem is not None:
            try:
                graph = self.resolve_subsystem(sub_id)
            except Exception:  # noqa: BLE001 - treated as unresolvable
                graph = None
        if not graph:
            return self.missing(var, (
                f"Block '{label}' is a nested sub-system ('{sub_name}') that "
                "couldn't be included in this export. Rebuild that diagram "
                "here as a NonRepairableRBD (or export it from Reliafy "
                "separately and import it)."
            ), label)
        self.lines.append("")
        self.comment(
            f"--- Sub-system '{sub_name}' (used by block '{label}'): a nested "
            "diagram analysed as a single block. ---"
        )
        section = self.diagram(graph, visited | {sub_id}, top=False)
        self.lines.append("")
        self.comment(f"{label}: the nested diagram '{sub_name}'.")
        self.imports.add("NonRepairableRBD")
        self._rbd_call(var, section, with_ccf=True)
        self.subsystems[sub_id] = var
        return var

    # -- whole diagrams -----------------------------------------------------
    def diagram(self, graph: dict, visited: frozenset, top: bool) -> dict:
        """Emit every block of ``graph``; return its structure for the
        ``NonRepairableRBD(...)`` call."""
        nodes = graph.get("nodes") or []
        node_ids = {n.get("id") for n in nodes}
        edges = [
            (e["source"], e["target"])
            for e in graph.get("edges") or []
            if e.get("source") and e.get("target")
        ]
        rel: list[tuple[Any, str, str]] = []  # (id, expr, label)
        k: dict[Any, int] = {}
        working, broken = [], []
        for node in nodes:
            ntype = node.get("type")
            if ntype in ("input", "output"):
                continue
            nid = node.get("id")
            data = node.get("data") or {}
            label = _one_line(data.get("label") or nid)
            expr, k_required = self.block(node, visited)
            if k_required is not None:
                k[nid] = k_required
            rel.append((nid, expr, label))
            if data.get("state") == "working":
                working.append(nid)
            elif data.get("state") == "failed":
                broken.append(nid)
        present = {nid for nid, _, _ in rel}
        ccf = []
        for g in graph.get("ccf_groups") or []:
            members = [m for m in (g.get("members") or []) if m in present]
            members = list(dict.fromkeys(members))
            if len(members) < 2:
                continue
            try:
                beta = float(g.get("beta"))
            except (TypeError, ValueError):
                continue
            if 0.0 < beta < 1.0:
                ccf.append((members, beta))
        return {
            "edges": edges,
            "rel": rel,
            "k": k,
            "input": "input" if "input" in node_ids else None,
            "output": "output" if "output" in node_ids else None,
            "ccf": ccf,
            "working": working if top else [],
            "broken": broken if top else [],
            "ignored_pins": (working + broken) if not top else [],
        }

    def _rbd_call(self, var: str, s: dict, with_ccf: bool) -> None:
        """Emit an inline ``var = NonRepairableRBD(...)`` for a sub-system."""
        L = self.lines
        L.append(f"{var} = NonRepairableRBD(")
        L.append("    [")
        for src, dst in s["edges"]:
            L.append(f"        ({_lit(src)}, {_lit(dst)}),")
        L.append("    ],")
        L.append("    {")
        for nid, expr, label in s["rel"]:
            L.append(f"        {_lit(nid)}: {expr},  # {label[:60]}")
        L.append("    },")
        if s["k"]:
            L.append("    k={" + ", ".join(
                f"{_lit(n)}: {v}" for n, v in s["k"].items()) + "},")
        if s["input"]:
            L.append(f"    input_node={_lit(s['input'])},")
        if s["output"]:
            L.append(f"    output_node={_lit(s['output'])},")
        if with_ccf and s["ccf"]:
            self.imports.update({"CCFGroup", "BetaFactor"})
            L.append("    ccf_groups=[")
            for members, beta in s["ccf"]:
                L.append(f"        CCFGroup(members={_lit(members)}, "
                         f"model=BetaFactor({_num(beta)})),")
            L.append("    ],")
        L.append(")")
        if s["ignored_pins"]:
            self.comment(
                "Blocks pinned working/failed inside a sub-system are not "
                "overridden (Reliafy only applies pins on the top diagram)."
            )


# ---------------------------------------------------------------------------
# App defaults (time axis, simulation horizon)
# ---------------------------------------------------------------------------
def _default_t_max(graph: dict, resolve_model, resolve_subsystem,
                   visited: frozenset = frozenset()) -> Optional[float]:
    """The app's default time-axis end: the largest per-block time scale
    (``rbd_analysis._model_hi``). A nested sub-system contributes the
    largest scale of its own blocks (the app estimates it by simulation)."""
    his = []
    for node in graph.get("nodes") or []:
        ntype = node.get("type")
        if ntype in ("input", "output", "knode", None):
            continue
        data = node.get("data") or {}
        if ntype == "subsystem":
            sub_id = (data.get("rbd") or {}).get("id")
            if not sub_id or sub_id in visited or resolve_subsystem is None:
                continue
            try:
                sub = resolve_subsystem(sub_id)
            except Exception:  # noqa: BLE001
                sub = None
            if sub:
                hi = _default_t_max(sub, resolve_model, resolve_subsystem,
                                    visited | {sub_id})
                if hi:
                    his.append(hi)
            continue
        data = dict(data)
        for key in ("model", "standbyModel"):
            if data.get(key):
                data[key] = _effective_spec(data[key], resolve_model)
        try:
            model, _ = rbd_analysis._node_reliability(
                {**node, "data": data}, None, set(), None, None
            )
            hi = rbd_analysis._model_hi(model)
        except Exception:  # noqa: BLE001 - the script raises for this block
            continue
        if hi:
            his.append(float(hi))
    return max(his) if his else None


def _seeded(fn, *args):
    """Run ``fn`` under a fixed NumPy seed (the app's series/parallel time
    scale is a small Monte-Carlo mean), restoring the caller's RNG state."""
    state = np.random.get_state()
    np.random.seed(20240925)
    try:
        return fn(*args)
    finally:
        np.random.set_state(state)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def to_python(
    graph: dict,
    name: str,
    resolve_model: Optional[Callable[[str], Optional[dict]]] = None,
    resolve_subsystem: Optional[Callable[[str], Optional[dict]]] = None,
    versions: Optional[dict] = None,
    exported_at: Optional[datetime] = None,
) -> str:
    """Render ``graph`` as a standalone Python script.

    ``resolve_model(model_id)`` returns a saved model's summary —
    ``{"name", "kind", "distribution_id", "distribution", "params",
    "extras", "unit"}`` — or ``None``; it fills in a saved-model block's
    fitted parameters when the block doesn't carry them.
    ``resolve_subsystem(rbd_id)`` returns a nested diagram's graph (or
    ``None``); without it sub-system blocks become explanatory placeholders.
    ``versions`` overrides :func:`detect_versions` and ``exported_at`` the
    export timestamp (both mainly for tests).
    """
    graph = graph or {}
    versions = {**detect_versions(), **(versions or {})}
    exported_at = exported_at or datetime.now(timezone.utc)
    unit = _one_line(graph.get("unit") or "")
    repairable = bool(graph.get("repairable"))
    script = _Script(unit, resolve_model, resolve_subsystem)
    if repairable:
        body = _repairable_body(script, graph)
    else:
        body = _nonrepairable_body(script, graph, resolve_model,
                                   resolve_subsystem)
    header = _header(name, unit, repairable, versions, exported_at,
                     script.placeholders, filename(name))
    imports = _imports(script, repairable)
    helpers = _helpers(script)
    parts = [helpers] if helpers else []
    parts.append(body)
    # PEP 8: two blank lines around top-level definitions.
    text = (header + "\n\n" + imports + "\n\n\n"
            + "\n\n\n".join(p.strip("\n") for p in parts) + "\n")
    # Collapse runs of blank lines (PEP 8: at most two).
    return re.sub(r"\n{4,}", "\n\n\n", text)


def _header(name, unit, repairable, versions, exported_at, placeholders,
            file_name):
    title = _one_line(name or "Untitled RBD").replace("\\", "/")
    title = title.replace('"""', "'''")
    sp, rp = versions["surpyval"], versions["repyability"]
    what = (
        "the same availability calculation as Reliafy: the exact steady-state "
        "availability, mean up/down time and failure frequency, then the "
        "same seeded Monte-Carlo availability simulation."
        if repairable else
        "the same reliability calculation as Reliafy: the system reliability "
        "R(t), the MTTF, the B10/B50 lives and the component importance "
        "measures."
    )
    lines = [
        f'"""{title}',
        "",
        "Reliability block diagram exported from Reliafy <https://reliafy.com>",
        f"on {exported_at.astimezone(timezone.utc):%Y-%m-%d} (UTC).",
        "",
        *textwrap.wrap(
            "This standalone script rebuilds the diagram with SurPyval + "
            "RePyability and runs " + what, 79),
        "",
        f"Tested with surpyval=={sp} and repyability=={rp}. Install them with:",
        "",
        f'    pip install "git+{_SURPYVAL_GIT}@v{sp}"',
        "    pip install networkx tqdm",
        "    pip install --no-deps \\",
        f'        "git+{_REPYABILITY_GIT}@v{rp}"',
        "",
        *textwrap.wrap(
            "RePyability's package metadata still pins an older SurPyval, so "
            "(like Reliafy's own build) it is installed with --no-deps after "
            "SurPyval and its two extra dependencies. matplotlib (installed "
            "with SurPyval) is only used for the optional plot.", 79),
        "",
        "Run:",
        "",
        f"    python {file_name}",
        "",
    ]
    if repairable:
        lines += textwrap.wrap(
            "Set RELIAFY_N_SIMS to change the number of simulated histories "
            "(default 2000, as in Reliafy; fewer runs faster). The "
            "steady-state figures are exact and don't depend on it.", 79)
        lines.append("")
    lines += textwrap.wrap(
        "Set RELIAFY_RESULTS_JSON=results.json to also save the numbers as "
        "JSON.", 79)
    lines.append("")
    lines.append(f"Times are in {unit}." if unit else
                 "Times are in the diagram's time unit (none was set).")
    if placeholders:
        lines.append("")
        lines += textwrap.wrap(
            "NOTE: some blocks couldn't be exported with their model and "
            "raise until you set one (search for 'TODO: placeholder'): "
            + ", ".join(placeholders) + ".", 79)
    lines.append('"""')
    return "\n".join(lines)


def _imports(script: _Script, repairable: bool) -> str:
    out = ["import json", "import os", "", "import numpy as np"]
    if script.uses_surv or (repairable and script.uses_voting_gate):
        out.append("import surpyval as surv")
    names = sorted(script.imports)
    if names:
        line = "from repyability import " + ", ".join(names)
        if len(line) > 79:
            out.append("from repyability import (")
            out.extend(f"    {n}," for n in names)
            out.append(")")
        else:
            out.append(line)
    return "\n".join(out)


def _helpers(script: _Script) -> str:
    out = []
    if script.uses_missing:
        out.append(textwrap.dedent('''
            def missing_model(message):
                """Stand-in for a block whose model couldn't be exported."""
                raise NotImplementedError(message)
        '''))
    if script.uses_voting_gate:
        out.append(textwrap.dedent('''
            def voting_gate():
                """A k-of-n voting gate in an availability model: pure logic that
                never fails (RePyability needs every node to be a repairable
                component), exactly as Reliafy models it."""
                return NonRepairable(
                    surv.Weibull.from_params([1e12, 1.0]),
                    surv.LogNormal.from_params([0.1, 0.1]),
                )
        '''))
    return "\n\n\n".join(h.strip("\n") for h in out)


def _edges_lines(edges) -> list[str]:
    out = [
        "# Connections, input to output (block ids as in the Reliafy diagram).",
        "EDGES = [",
    ]
    out += [f"    ({_lit(a)}, {_lit(b)})," for a, b in edges]
    out.append("]")
    return out


def _nonrepairable_body(script: _Script, graph, resolve_model,
                        resolve_subsystem) -> str:
    L = script.lines
    L.append("# " + "-" * 75)
    L.append("# Blocks: one life model per block, built exactly as Reliafy "
             "builds them.")
    L.append("# " + "-" * 75)
    s = script.diagram(graph, frozenset(), top=True)
    script.imports.add("NonRepairableRBD")

    t_max = _seeded(_default_t_max, graph, resolve_model, resolve_subsystem)
    t_max = float(t_max) if t_max and np.isfinite(t_max) and t_max > 0 else 1.0

    out = list(L)
    out.append("")
    out.append("")
    out.append("# " + "-" * 75)
    out.append("# The diagram")
    out.append("# " + "-" * 75)
    out += _edges_lines(s["edges"])
    out.append("")
    out.append("# Each block's reliability model.")
    out.append("RELIABILITIES = {")
    for nid, expr, label in s["rel"]:
        note = (f"  # voting gate: {s['k'][nid]} of its inputs must work"
                if nid in s["k"] else "")
        out.append(f"    {_lit(nid)}: {expr},{note}")
    out.append("}")
    out.append("")
    out.append("# k-out-of-n voting gates: how many incoming branches must work.")
    out.append("K = {" + ", ".join(f"{_lit(n)}: {v}" for n, v in s["k"].items())
               + "}")
    out.append("")
    out.append("LABELS = {")
    for nid, _, label in s["rel"]:
        out.append(f"    {_lit(nid)}: {_lit(label)},")
    out.append("}")
    out.append("")
    out += _pins(s)
    out.append("")
    io = []
    if s["input"]:
        io.append(f"input_node={_lit(s['input'])}")
    if s["output"]:
        io.append(f"output_node={_lit(s['output'])}")
    io_args = "".join(f"    {a},\n" for a in io)
    if s["ccf"]:
        script.imports.update({"CCFGroup", "BetaFactor"})
        out.append("# Common-cause failure: a beta-factor share of each "
                   "member's failures takes")
        out.append("# the whole group out together.")
        out.append("CCF_GROUPS = [")
        for members, beta in s["ccf"]:
            out.append("    CCFGroup(")
            out.append(f"        members={_lit(members)},")
            out.append(f"        model=BetaFactor({_num(beta)}),")
            out.append("    ),")
        out.append("]")
        out.append("")
        out.append("rbd = NonRepairableRBD(\n    EDGES,\n    RELIABILITIES,\n"
                   "    k=K,\n" + io_args + "    ccf_groups=CCF_GROUPS,\n)")
        out.append("")
        out.append("# RePyability's importance measures assume independent "
                   "blocks, so (as in")
        out.append("# Reliafy) they are evaluated on the same diagram without "
                   "the coupling.")
        out.append("rbd_independent = NonRepairableRBD(\n    EDGES,\n"
                   "    RELIABILITIES,\n    k=K,\n" + io_args + ")")
        imp_rbd = "rbd_independent"
    else:
        out.append("rbd = NonRepairableRBD(\n    EDGES,\n    RELIABILITIES,\n"
                   "    k=K,\n" + io_args + ")")
        imp_rbd = "rbd"
    out.append("")
    out.append("")
    out.append("# " + "-" * 75)
    out.append("# The calculation")
    out.append("# " + "-" * 75)
    out.append(f"UNIT = {_lit(script.unit)}")
    out.append("# Reliafy's default time axis for this diagram: out to the "
               "longest-lived")
    out.append("# block's 99th-percentile life, on a 200-point grid.")
    out.append(f"T_MAX = {_num(t_max)}")
    out.append("GRID_POINTS = 200")
    out.append("")
    out.append("")
    out.append(_NONREPAIRABLE_MAIN.replace("__IMP__", imp_rbd).strip("\n"))
    return "\n".join(out)


def _pins(s: dict) -> list[str]:
    return [
        "# What-if overrides: blocks pinned working (perfectly reliable) or "
        "failed",
        "# in Reliafy. Add block ids here to explore other scenarios.",
        f"WORKING_NODES = {_set_literal(s['working'])}",
        f"BROKEN_NODES = {_set_literal(s['broken'])}",
    ]


def _set_literal(items) -> str:
    return "{" + ", ".join(_lit(i) for i in items) + "}" if items else "set()"


_NONREPAIRABLE_MAIN = '''
def mean_time_to_failure(model, horizon, **overrides):
    """MTTF as the integral of R(t) dt, computed exactly as Reliafy does.

    The horizon is doubled (up to 8 times) until R(t) has decayed below 1e-4,
    then R(t) is integrated with the trapezoid rule on 4000 points.
    (RePyability's own ``rbd.mean()`` is a slower Monte-Carlo estimate.)
    """
    t_end = horizon
    for _ in range(8):
        if model.sf(np.array([t_end]), **overrides)[0] < 1e-4:
            break
        t_end *= 2.0
    grid = np.linspace(0.0, t_end, 4000)
    return float(np.trapezoid(model.sf(grid, **overrides), grid))


def b_life(times, sf, fraction):
    """Time by which ``fraction`` of systems have failed, read off the
    reliability curve (None if that is beyond the time axis)."""
    target = 1.0 - fraction
    if sf[0] <= target:
        return float(times[0])
    below = np.nonzero(sf <= target)[0]
    if not below.size:
        return None
    i = below[0]
    s0, s1 = sf[i - 1], sf[i]
    if s1 == s0:
        return float(times[i])
    step = (s0 - target) / (s0 - s1)
    return float(times[i - 1] + step * (times[i] - times[i - 1]))


def save_results(results):
    """Write the numbers to $RELIAFY_RESULTS_JSON, when it is set."""
    path = os.environ.get("RELIAFY_RESULTS_JSON")
    if path:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(results, fh, indent=2)


def main():
    overrides = {"working_nodes": WORKING_NODES, "broken_nodes": BROKEN_NODES}
    unit = f" {UNIT}" if UNIT else ""

    # System reliability R(t) over the time axis.
    times = np.linspace(0.0, T_MAX, GRID_POINTS)
    system_sf = np.asarray(rbd.sf(times, **overrides), dtype=float)

    mttf = mean_time_to_failure(rbd, T_MAX, **overrides)
    b10 = b_life(times, system_sf, 0.10)
    b50 = b_life(times, system_sf, 0.50)

    # R(t) at a few round times around the MTTF, plus the calculator's
    # default read-out time (the middle of the time axis).
    checkpoints = [float(f"{mttf * f:.2g}") for f in (0.25, 0.5, 1.0, 2.0)]
    checkpoints.append(float(f"{T_MAX / 2:.4g}"))
    print("System reliability R(t)")
    reliability = {}
    for t in checkpoints:
        r = float(rbd.sf(t, **overrides))
        reliability[repr(t)] = r
        print(f"  R({t:,.6g}{unit}) = {r:.6f}")

    print(f"MTTF: {mttf:,.6g}{unit}")
    for name, value in (("B10", b10), ("B50", b50)):
        shown = f"{value:,.6g}{unit}" if value is not None else "beyond T_MAX"
        print(f"{name} life: {shown}")

    # Importance measures at Reliafy's representative time: where the system
    # reliability is closest to 0.9 (else the middle of the time axis).
    i = int(np.argmin(np.abs(system_sf - 0.9)))
    if not 0.0 < system_sf[i] < 1.0:
        i = GRID_POINTS // 2
    t_rep = float(times[i])
    model = __IMP__
    with np.errstate(all="ignore"):
        measures = {
            "Birnbaum": model.birnbaum_importance(t_rep, **overrides),
            "Fussell-Vesely": model.fussell_vesely(
                t_rep, fv_type="c", **overrides
            ),
            "Criticality": model.criticality_importance(t_rep, **overrides),
            "RAW": model.risk_achievement_worth(t_rep, **overrides),
            "RRW": model.risk_reduction_worth(t_rep, **overrides),
            "Improvement": model.improvement_potential(t_rep, **overrides),
        }
    blocks = [n for n in LABELS if n not in K]  # voting gates aren't blocks
    width = max([len(LABELS[n][:28]) for n in blocks] + [5])
    print(f"\\nImportance at t = {t_rep:,.6g}{unit}")
    print("  " + "Block".ljust(width) + "".join(
        f"{name:>15}" for name in measures))
    importance = {name: {} for name in measures}
    for node in blocks:
        row = "  " + LABELS[node][:28].ljust(width)
        for name, values in measures.items():
            value = float(np.atleast_1d(values[node])[0])
            importance[name][node] = value
            row += f"{value:>15.4g}"
        print(row)

    results = {
        "unit": UNIT,
        "t_max": T_MAX,
        "reliability": reliability,
        "mttf": mttf,
        "b10": b10,
        "b50": b50,
        "importance_time": t_rep,
        "importance": importance,
        "curve": {"t": times.tolist(), "sf": system_sf.tolist()},
    }
    save_results(results)

    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("(Install matplotlib to plot the reliability curve.)")
    else:
        fig, ax = plt.subplots()
        ax.plot(times, system_sf)
        ax.set_xlabel(f"Time ({UNIT})" if UNIT else "Time")
        ax.set_ylabel("System reliability R(t)")
        ax.set_ylim(0.0, 1.02)
        ax.grid(True, alpha=0.3)
        plt.show()
    return results


if __name__ == "__main__":
    main()
'''


# ---------------------------------------------------------------------------
# Repairable (availability)
# ---------------------------------------------------------------------------
def _repairable_body(script: _Script, graph) -> str:
    L = script.lines
    L.append("# " + "-" * 75)
    L.append("# Blocks: each component fails by its life model and is "
             "restored by its")
    L.append("# repair-time model (a NonRepairable component in RePyability).")
    L.append("# " + "-" * 75)
    script.imports.update({"NonRepairable", "RepairableRBD"})
    nodes = graph.get("nodes") or []
    node_ids = {n.get("id") for n in nodes}
    edges = [
        (e["source"], e["target"])
        for e in graph.get("edges") or []
        if e.get("source") and e.get("target")
    ]
    comps: list[tuple[Any, str, str]] = []
    k: dict[Any, int] = {}
    working, broken = [], []
    for node in nodes:
        ntype = node.get("type")
        if ntype in ("input", "output"):
            continue
        nid = node.get("id")
        data = node.get("data") or {}
        label = _one_line(data.get("label") or nid)
        state = data.get("state")
        if state == "working":
            working.append(nid)
        elif state == "failed":
            broken.append(nid)
        pinned = state in ("working", "failed")
        if ntype == "knode":
            script.uses_voting_gate = True
            k[nid] = max(int(data.get("n") or 1), 1)
            comps.append((nid, "voting_gate()", label))
            continue
        var = script.names.make(label)
        L.append("")
        if ntype != "component":
            script.missing(var, (
                f"Block '{label}' is a '{ntype}' block, which Reliafy doesn't "
                "support in repairable (availability) diagrams - use "
                "component blocks (each with a life model and a repair time) "
                "and k-of-n gates."
            ), label)
            comps.append((nid, var, label))
            continue
        if pinned and not (data.get("model") and data.get("repair")):
            script.uses_voting_gate = True
            script.comment(
                f"{label}: pinned {state} in Reliafy with no life/repair "
                "model - the override fixes its state, so a never-failing "
                "stand-in is used."
            )
            L.append(f"{var} = voting_gate()")
            comps.append((nid, var, label))
            continue
        life = script.dist(data.get("model"), f"{label} (life)",
                           script.names.make(f"{var}_life"))
        repair_var = script.names.make(f"{var}_repair")
        if not data.get("repair"):
            repair = script.missing(repair_var, (
                f"Block '{label}' has no repair-time distribution. Repairable "
                "diagrams need one on every component, e.g. "
                "surv.LogNormal.from_params([mu, sigma])."
            ), label)
        else:
            repair = script.dist(data.get("repair"), f"{label} (repair time)",
                                 repair_var)
        line = f"{var} = NonRepairable({life}, {repair})"
        if len(line) > 79:
            line = f"{var} = NonRepairable(\n    {life},\n    {repair},\n)"
        L.append(line)
        comps.append((nid, var, label))

    horizon = rbd_analysis._availability_horizon(graph)

    out = list(L)
    out.append("")
    out.append("")
    out.append("# " + "-" * 75)
    out.append("# The diagram")
    out.append("# " + "-" * 75)
    out += _edges_lines(edges)
    out.append("")
    out.append("# Each block's repairable component.")
    out.append("COMPONENTS = {")
    for nid, expr, label in comps:
        out.append(f"    {_lit(nid)}: {expr},")
    out.append("}")
    out.append("")
    out.append("# k-out-of-n voting gates: how many incoming branches must work.")
    out.append("K = {" + ", ".join(f"{_lit(n)}: {v}" for n, v in k.items()) + "}")
    out.append("")
    out.append("LABELS = {")
    for nid, _, label in comps:
        out.append(f"    {_lit(nid)}: {_lit(label)},")
    out.append("}")
    out.append("")
    out += _pins({"working": working, "broken": broken})
    out.append("")
    if graph.get("ccf_groups"):
        out.append("# Common-cause groups are a reliability-only feature and "
                   "are ignored in an")
        out.append("# availability diagram (as in Reliafy).")
    io = []
    if "input" in node_ids:
        io.append("input_node='input'")
    if "output" in node_ids:
        io.append("output_node='output'")
    out.append("rbd = RepairableRBD(\n    EDGES,\n    COMPONENTS,\n    k=K,\n"
               + "".join(f"    {a},\n" for a in io) + ")")
    out.append("")
    out.append("")
    out.append("# " + "-" * 75)
    out.append("# The calculation")
    out.append("# " + "-" * 75)
    out.append(f"UNIT = {_lit(script.unit)}")
    out.append("# Reliafy's default simulation length: 10x the largest "
               "parameter in the")
    out.append("# diagram, long enough to reach steady state.")
    out.append(f"T_SIMULATION = {_num(horizon)}")
    out.append('N_SIMS = int(os.environ.get("RELIAFY_N_SIMS", "2000"))')
    out.append("")
    out.append("")
    out.append(_REPAIRABLE_MAIN.strip("\n"))
    return "\n".join(out)


_REPAIRABLE_MAIN = '''
def save_results(results):
    """Write the numbers to $RELIAFY_RESULTS_JSON, when it is set."""
    path = os.environ.get("RELIAFY_RESULTS_JSON")
    if path:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(results, fh, indent=2)


def main():
    overrides = {"working_nodes": WORKING_NODES, "broken_nodes": BROKEN_NODES}
    unit = f" {UNIT}" if UNIT else ""
    blocks = [n for n in LABELS if n not in K]  # voting gates aren't blocks

    # Exact long-run figures (independent blocks; Birnbaum/Vesely formula).
    with np.errstate(all="ignore"):
        availability = float(rbd.mean_availability(**overrides))
        mean_up = float(rbd.mean_up_time(**overrides))
        mean_down = float(rbd.mean_down_time(**overrides))
        frequency = float(rbd.system_failure_frequency(**overrides))
        birnbaum = rbd.birnbaum_importance(**overrides)
    print(f"Steady-state availability: {availability:.6f}")
    print(f"Unavailability: {1.0 - availability:.3e}")
    print(f"Mean up time: {mean_up:,.6g}{unit}")
    print(f"Mean down time: {mean_down:,.6g}{unit}")
    print(f"Failure frequency: {frequency:.6g} per unit time"
          + (f" ({UNIT})" if UNIT else ""))

    # Monte-Carlo availability over time, seeded exactly as in Reliafy.
    print(f"\\nSimulating {N_SIMS} histories of {T_SIMULATION:,.6g}{unit}...")
    sim = rbd.availability(
        t_simulation=T_SIMULATION, N=N_SIMS, method="c", seed=1, **overrides
    )
    print(f"  simulated mean up time: {sim.mean_up_time:,.6g}{unit}")
    print(f"  simulated mean down time: {sim.mean_down_time:,.6g}{unit}")
    print(f"  simulated failure frequency: {sim.failure_frequency:.6g}")

    node_availability = rbd.node_availability()
    downtime = {n: sim.node_downtime.get(n, 0.0) for n in blocks}
    total_downtime = sum(downtime.values()) or 1.0
    width = max([len(LABELS[n][:28]) for n in blocks] + [5])
    print("\\n  " + "Block".ljust(width) + f"{'Availability':>15}"
          f"{'Birnbaum':>12}{'Downtime share':>16}")
    per_block = {}
    for node in blocks:
        share = downtime[node] / total_downtime
        per_block[node] = {
            "availability": node_availability[node],
            "birnbaum": float(birnbaum[node]),
            "downtime_share": share,
        }
        print("  " + LABELS[node][:28].ljust(width)
              + f"{node_availability[node]:>15.6f}"
              + f"{float(birnbaum[node]):>12.4g}{share:>16.1%}")

    results = {
        "unit": UNIT,
        "steady_state_availability": availability,
        "mean_up_time": mean_up,
        "mean_down_time": mean_down,
        "failure_frequency": frequency,
        "t_simulation": T_SIMULATION,
        "n_simulations": N_SIMS,
        "simulated": {
            "mean_up_time": sim.mean_up_time,
            "mean_down_time": sim.mean_down_time,
            "failure_frequency": sim.failure_frequency,
        },
        "blocks": per_block,
    }
    save_results(results)

    try:
        import matplotlib.pyplot as plt
    except ImportError:
        print("(Install matplotlib to plot the availability curve.)")
    else:
        fig, ax = plt.subplots()
        ax.step(sim.timeline, sim.availability, where="post")
        ax.axhline(availability, linestyle="--", label="steady state")
        ax.set_xlabel(f"Time ({UNIT})" if UNIT else "Time")
        ax.set_ylabel("System availability A(t)")
        ax.legend()
        ax.grid(True, alpha=0.3)
        plt.show()
    return results


if __name__ == "__main__":
    main()
'''
