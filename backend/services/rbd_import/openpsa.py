"""Open-PSA Model Exchange Format (MEF) fault-tree import.

Spec: https://open-psa.github.io/mef/ (schema 2.0d). The root element is
``<opsa-mef>``; XFTA's dialect (``<open-psa>``) is accepted too.

Supported:

* ``define-fault-tree`` / ``define-gate`` / ``define-component`` containers,
  and gates, events and parameters defined at model level or in
  ``model-data``;
* ``and`` / ``or`` / ``atleast min=`` (and ``cardinality`` whose ``max`` is
  the number of inputs), nested formulas, references via ``gate``,
  ``basic-event``, ``house-event`` or untyped ``event``;
* house events and constants (``constant``, ``bool``, XFTA ``true``/``false``);
* basic events with ``exponential`` (λ, mission time — ``c × t`` scales the
  rate by ``c``), ``Weibull`` (α scale, β shape, t0, t — t0 is dropped with a
  warning; the compact graph carries no location offset), ``GLM`` (γ, λ, μ, t:
  failure rate λ, exponential repair at rate μ; γ ≠ 0 dropped with a
  warning) and ``periodic-test`` (imported as its failure rate λ, with a
  warning that the test schedule is not modelled);
* ``define-parameter`` (with ``unit`` — a rate in ``hours-1`` makes the
  diagram's unit ``hours``) and arithmetic expressions; uncertainty deviates
  (lognormal/normal/uniform/gamma/beta) are replaced by their mean, with a
  warning;
* ``define-CCF-group model="beta-factor"`` -> ``ccf_groups`` (other CCF
  models are skipped with a warning).

A basic event used under several gates (a repeated event) becomes a repeated
block, drawn in each place but analysed as one component (see
:mod:`.fault_tree`).

Refused: non-coherent logic (``not``, ``xor``, ``nand``, ``nor``, ``iff``,
``imply``) and basic events with a fixed probability and no failure-time
model.

Parsing uses ``defusedxml`` (no entity expansion, no external entities or DTD
fetching) and bounds the element depth.
"""

from __future__ import annotations

import math
import re
from typing import Optional

from defusedxml import ElementTree as SafeET
from defusedxml.common import DefusedXmlException

from . import fault_tree as ft
from .types import ImportedDiagram, RbdImportError

MAX_XML_DEPTH = 400
MAX_ROOTS = 20
_ROOT_TAGS = ("opsa-mef", "open-psa")
_NON_COHERENT = {"not": "NOT", "xor": "XOR", "nand": "NAND", "nor": "NOR",
                 "iff": "IFF", "imply": "IMPLY"}
_REF_TAGS = ("gate", "basic-event", "house-event", "event")


def _tag(el) -> str:
    return el.tag.rsplit("}", 1)[-1] if isinstance(el.tag, str) else ""


def sniff(data: bytes, filename: str) -> bool:
    head = data[:65536].decode("utf-8", "replace")
    if re.search(r"<\s*(opsa-mef|open-psa)[\s>/]", head):
        return True
    name = (filename or "").lower()
    return name.endswith(".opsa") and "<" in head


def _parse_xml(data: bytes):
    try:
        root = SafeET.fromstring(data, forbid_dtd=False, forbid_entities=True, forbid_external=True)
    except DefusedXmlException:
        raise RbdImportError(
            "The XML file declares entities or external references, which aren't allowed "
            "in uploads. Remove the DOCTYPE entity declarations and try again.") from None
    except SafeET.ParseError as exc:
        raise RbdImportError(f"The file isn't well-formed XML ({exc}).") from None
    # Bound the nesting depth (iteratively).
    stack = [(root, 1)]
    while stack:
        el, d = stack.pop()
        if d > MAX_XML_DEPTH:
            raise RbdImportError(f"The XML is nested more than {MAX_XML_DEPTH} levels deep.")
        stack.extend((c, d + 1) for c in el)
    if _tag(root) not in _ROOT_TAGS:
        raise RbdImportError("This XML isn't an Open-PSA model (expected an <opsa-mef> root).")
    return root


class _Model:
    """Everything defined in the file, keyed by name. Elements declared
    ``role="private"`` (or inside a private container) are keyed
    ``"<container>.<name>"`` and resolved from inside that container first."""

    def __init__(self, root):
        self.gates: dict[str, object] = {}        # key -> define-gate element
        self.events: dict[str, object] = {}       # key -> define-basic-event
        self.houses: dict[str, object] = {}       # key -> define-house-event
        self.params: dict[str, object] = {}       # key -> define-parameter
        self.scope_of: dict[int, str] = {}        # id(element) -> container path
        self.gate_ft: dict[str, str] = {}         # gate key -> fault tree name
        self.ccf: list = []                       # define-CCF-group elements
        self.fault_trees: list[str] = []
        self._alias: dict[int, dict[str, str]] = {}
        self._lower: dict[int, dict[str, str]] = {}
        self._collect(root, "", "public")

    def _collect(self, el, path: str, role: str):
        for child in el:
            t = _tag(child)
            name = child.get("name") or ""
            child_role = child.get("role") or role
            if t in ("define-fault-tree", "define-component"):
                if t == "define-fault-tree":
                    self.fault_trees.append(name)
                self._collect(child, f"{path}.{name}" if path else name, child_role)
            elif t == "model-data":
                self._collect(child, path, child_role)
            elif t in ("define-gate", "define-basic-event", "define-house-event", "define-parameter"):
                table, kind = {
                    "define-gate": (self.gates, "gate"),
                    "define-basic-event": (self.events, "basic event"),
                    "define-house-event": (self.houses, "house event"),
                    "define-parameter": (self.params, "parameter"),
                }[t]
                if not name:
                    raise RbdImportError(f"A {kind} definition has no name.")
                key = f"{path}.{name}" if (child_role == "private" and path) else name
                if key in table:
                    raise RbdImportError(f"The {kind} “{name}” is defined twice.")
                table[key] = child
                self.scope_of[id(child)] = path
                if path and key == name:
                    self._alias.setdefault(id(table), {})[f"{path}.{name}"] = key
                if t == "define-gate":
                    self.gate_ft[key] = path.split(".", 1)[0]
            elif t == "define-CCF-group":
                self.ccf.append(child)
                self.scope_of[id(child)] = path

    def lookup(self, table: dict, ref: str, scope: str = "") -> Optional[str]:
        s = scope
        while s:
            if f"{s}.{ref}" in table:
                return f"{s}.{ref}"
            s = s.rpartition(".")[0]
        if ref in table:
            return ref
        alias = self._alias.get(id(table), {})
        if ref in alias:
            return alias[ref]
        lower = self._lower.get(id(table))
        if lower is None:
            lower = self._lower[id(table)] = {k.lower(): k for k in table}
        return lower.get(ref.lower())


def _children(el):
    """Formula children (skip label/attributes)."""
    return [c for c in el if _tag(c) not in ("label", "attributes")]


def _label(el) -> Optional[str]:
    for c in el:
        if _tag(c) == "label" and (c.text or "").strip():
            return " ".join(c.text.split())[:200]
    return None


class _Converter:
    def __init__(self, model: _Model):
        self.m = model
        self.warnings: list[str] = []
        self.nodes: dict[str, ft.Node] = {}
        self.units: set[str] = set()
        self.fixed_prob: list[str] = []
        self.no_data: list[str] = []
        self.ccf_members: dict[str, object] = {}   # event -> CCF group element
        self.anon = 0
        self.depth = 0
        self.scope: list[str] = [""]
        self._warned: set[str] = set()
        self._notes: dict[str, list[str]] = {}
        for g in model.ccf:
            members = [c for c in g.iter() if _tag(c) == "basic-event" and c.get("name")]
            for mem in members:
                self.ccf_members.setdefault(mem.get("name"), g)

    def warn(self, msg: str):
        if msg not in self._warned:
            self._warned.add(msg)
            self.warnings.append(msg)

    def note(self, kind: str, name: str):
        """Collect an approximation that applies per event; reported once."""
        names = self._notes.setdefault(kind, [])
        if name not in names:
            names.append(name)

    def all_warnings(self) -> list[str]:
        out = list(self.warnings)
        for kind, names in self._notes.items():
            out.append(_NOTES[kind].format(names=_names(names)))
        return out

    # -- formulas ---------------------------------------------------------
    def gate(self, name: str):
        if name in self.nodes:
            return name
        self.depth += 1
        if self.depth > ft.MAX_DEPTH:
            raise RbdImportError(
                f"The fault tree is nested more than {ft.MAX_DEPTH} gates deep — too deep to import.")
        try:
            return self._gate(name)
        finally:
            self.depth -= 1

    def _gate(self, name: str):
        el = self.m.gates[name]
        kids = _children(el)
        if len(kids) != 1:
            raise RbdImportError(f"Gate “{name}” should hold exactly one formula.")
        self.nodes[name] = None  # placeholder: loops are caught by fault_tree
        self.scope.append(self.m.scope_of.get(id(el), ""))
        try:
            node = self.formula(kids[0], name, _label(el))
        finally:
            self.scope.pop()
        self.nodes[name] = node
        return name

    def formula(self, el, name: str, label: Optional[str] = None, depth: int = 0) -> ft.Node:
        """Build the node for formula ``el`` under ``name``."""
        if depth > ft.MAX_DEPTH:
            raise RbdImportError("The fault tree's formulas are nested too deeply.")
        t = _tag(el)
        if t in _NON_COHERENT:
            raise RbdImportError(
                f"Gate “{name}” uses {_NON_COHERENT[t]} logic. A reliability block diagram can only "
                "express coherent logic (AND / OR / at-least), so this tree can't be imported.")
        if t in ("and", "or", "atleast", "cardinality"):
            kids = _children(el)
            refs = [self.operand(c, name, depth + 1) for c in kids]
            if t == "atleast":
                k = self._int_attr(el, "min", name)
                return ft.Gate(name, "atleast", refs, k, label=label)
            if t == "cardinality":
                lo = self._int_attr(el, "min", name)
                hi = self._int_attr(el, "max", name)
                if hi < len(refs):
                    raise RbdImportError(
                        f"Gate “{name}” is a cardinality gate with an upper bound "
                        f"({hi} of {len(refs)}) — that is non-coherent logic.")
                return ft.Gate(name, "atleast", refs, lo, label=label)
            return ft.Gate(name, t, refs, label=label)
        # A single reference or constant as the whole formula: a pass-through.
        ref = self.operand(el, name, depth + 1)
        return ft.Gate(name, "or", [ref], label=label)

    @staticmethod
    def _int_attr(el, key, name) -> int:
        try:
            return int(el.get(key))
        except (TypeError, ValueError):
            raise RbdImportError(f"Gate “{name}”: <{_tag(el)}> needs a whole-number {key}=.") from None

    def operand(self, el, parent: str, depth: int) -> str:
        """Name of the tree node an operand refers to (creating it)."""
        t = _tag(el)
        if t in _REF_TAGS:
            ref = el.get("name") or ""
            return self.reference(t, ref, parent)
        if t in ("constant", "bool", "true", "false"):
            value = t == "true" if t in ("true", "false") else str(el.get("value")).lower() == "true"
            cname = f"<{'true' if value else 'false'}>"
            self.nodes.setdefault(cname, ft.Leaf(cname, constant=value))
            return cname
        # Nested anonymous formula (counts towards the nesting bound).
        self.anon += 1
        aname = f"{parent} #{self.anon}"
        self.depth += 1
        try:
            if self.depth > ft.MAX_DEPTH:
                raise RbdImportError(
                    f"The fault tree is nested more than {ft.MAX_DEPTH} levels deep — too deep to import.")
            self.nodes[aname] = self.formula(el, aname, None, depth)
        finally:
            self.depth -= 1
        self.nodes[aname].label = parent
        return aname

    def reference(self, kind: str, ref: str, parent: str) -> str:
        m = self.m
        tables = {"gate": [m.gates], "basic-event": [m.events], "house-event": [m.houses],
                  "event": [m.gates, m.events, m.houses]}[kind]
        for table in tables:
            name = m.lookup(table, ref, self.scope[-1])
            if name is None:
                continue
            if table is m.gates:
                return self.gate(name)
            if table is m.houses:
                return self.house(name)
            return self.basic_event(name)
        if kind in ("basic-event", "event") and ref in self.ccf_members:
            return self.basic_event(ref)
        if kind == "basic-event":
            # Referenced but never defined: no data to build a block from.
            self.no_data.append(ref)
            self.nodes.setdefault(ref, ft.Leaf(ref, constant=False))
            return ref
        raise RbdImportError(
            f"Gate “{parent}” refers to “{ref}”, which isn't defined in this file. (If the model "
            "is split over several files, merge them into one before importing.)")

    def house(self, name: str) -> str:
        key = f"house:{name}"
        if key not in self.nodes:
            el = self.m.houses[name]
            value = False
            for c in _children(el):
                if _tag(c) in ("constant", "bool"):
                    value = str(c.get("value")).lower() == "true"
                elif _tag(c) in ("true", "false"):
                    value = _tag(c) == "true"
            self.nodes[key] = ft.Leaf(key, constant=value, label=name)
        return key

    # -- basic events -----------------------------------------------------
    def basic_event(self, name: str) -> str:
        if name in self.nodes:
            return name
        el = self.m.events.get(name)
        expr = None
        if el is not None:
            kids = _children(el)
            expr = kids[0] if kids else None
        if expr is None and name in self.ccf_members:
            expr = _ccf_distribution(self.ccf_members[name])
        if expr is None:
            self.no_data.append(name)
            self.nodes[name] = ft.Leaf(name, constant=False)
            return name
        scope = self.m.scope_of.get(id(el), "") if el is not None else ""
        label = _label(el) if el is not None else None
        if not label and scope and name.startswith(scope + "."):
            label = name[len(scope) + 1:]  # a private event: show its local name
        self.scope.append(scope)
        try:
            self.nodes[name] = self.event_model(name, expr, label)
        finally:
            self.scope.pop()
        return name

    def event_model(self, name: str, expr, label) -> ft.Leaf:
        expr = self._deref(expr)
        t = _tag(expr).lower()
        args = _children(expr)
        if t == "exponential":
            if len(args) != 2:
                raise RbdImportError(f"Basic event “{name}”: <exponential> takes λ and a time.")
            lam = self.num(args[0], name)
            factor = self._time_factor(args[1], name)
            if factor is None:
                return self._fixed(name, 1 - math.exp(-lam * self.num(args[1], name)))
            if factor != 1:
                self.note("time_factor", name)
            return self._life(name, ft.exponential_model(lam * factor), label, lam * factor)
        if t == "weibull":
            if len(args) not in (3, 4):
                raise RbdImportError(f"Basic event “{name}”: <Weibull> takes α, β, t0 and a time.")
            alpha, beta = self.num(args[0], name), self.num(args[1], name)
            t0 = self.num(args[2], name) if len(args) == 4 else 0.0
            if t0:
                self.note("weibull_t0", name)
            return self._life(name, ft.weibull_model(alpha, beta), label, None)
        if t == "glm":
            if len(args) != 4:
                raise RbdImportError(f"Basic event “{name}”: <GLM> takes γ, λ, μ and a time.")
            gamma, lam, mu = (self.num(a, name) for a in args[:3])
            if gamma:
                self.note("glm_gamma", name)
            leaf = self._life(name, ft.exponential_model(lam), label, lam)
            if mu > 0 and leaf.constant is None:
                leaf.node["repair"] = ft.exponential_model(mu)
            return leaf
        if t == "periodic-test":
            if not args:
                raise RbdImportError(f"Basic event “{name}”: <periodic-test> has no arguments.")
            lam = self.num(args[0], name)
            self.note("periodic_test", name)
            return self._life(name, ft.exponential_model(lam), label, lam)
        # Anything else is a plain number: a fixed probability.
        return self._fixed(name, self.num(expr, name))

    def _life(self, name, model, label, rate) -> ft.Leaf:
        if rate is not None and rate == 0:
            return ft.Leaf(name, constant=False, label=label)
        for p in model["params"]:
            if not (math.isfinite(p["value"]) and p["value"] > 0):
                raise RbdImportError(f"Basic event “{name}”: parameter {p['name']}={p['value']:g} "
                                     "must be positive.")
        return ft.Leaf(name, {"type": "component", "model": model}, label=label)

    def _fixed(self, name, p) -> ft.Leaf:
        if p == 0:
            return ft.Leaf(name, constant=False)
        if p == 1:
            return ft.Leaf(name, constant=True)
        self.fixed_prob.append(name)
        return ft.Leaf(name, constant=False)

    # -- expressions ------------------------------------------------------
    def _deref(self, el, depth=0):
        """Follow ``<parameter>`` references to the defining expression."""
        while _tag(el) == "parameter":
            depth += 1
            if depth > 50:
                raise RbdImportError("Parameters refer to each other in a loop.")
            name = self.m.lookup(self.m.params, el.get("name") or "", self.scope[-1])
            if name is None:
                raise RbdImportError(f"Parameter “{el.get('name')}” isn't defined.")
            pel = self.m.params[name]
            self._note_unit(pel)
            kids = _children(pel)
            if len(kids) != 1:
                raise RbdImportError(f"Parameter “{name}” should hold one expression.")
            el = kids[0]
        return el

    def _note_unit(self, pel):
        unit = (pel.get("unit") or "").strip()
        if unit.endswith("-1"):
            self.units.add(unit[:-2])
        elif unit and unit not in ("bool", "int", "float", "fraction", "probability"):
            self.units.add(unit)

    def _time_factor(self, el, name) -> Optional[float]:
        """``c`` when ``el`` is ``c × mission time`` (c = 1 for the bare
        mission time); ``None`` for a constant time."""
        el = self._deref(el)
        t = _tag(el)
        if t in ("system-mission-time", "mission-time"):
            return 1.0
        if t == "mul":
            factors = [self._time_factor(c, name) for c in _children(el)]
            timed = [f for f in factors if f is not None]
            if len(timed) != 1:
                return None
            rest = [self.num(c, name) for c, f in zip(_children(el), factors) if f is None]
            return timed[0] * math.prod(rest)
        return None

    def num(self, el, name: str, depth: int = 0) -> float:
        if depth > 100:
            raise RbdImportError(f"“{name}”: the expression is nested too deeply.")
        el = self._deref(el)
        t = _tag(el)
        args = _children(el)
        try:
            if t in ("float", "int"):
                return float(el.get("value"))
            if t == "bool":
                return 1.0 if str(el.get("value")).lower() == "true" else 0.0
            if t == "pi":
                return math.pi
            vals = [self.num(a, name, depth + 1) for a in args]
            if t == "mul":
                return math.prod(vals)
            if t == "add":
                return sum(vals)
            if t == "sub":
                return vals[0] - sum(vals[1:])
            if t == "div":
                out = vals[0]
                for v in vals[1:]:
                    out /= v
                return out
            if t == "neg":
                return -vals[0]
            if t == "exp":
                return math.exp(vals[0])
            if t == "log":
                return math.log(vals[0])
            if t == "sqrt":
                return math.sqrt(vals[0])
            if t == "pow":
                return vals[0] ** vals[1]
            if t in ("lognormal-deviate", "normal-deviate"):
                self._mean_warning(name)
                return vals[0]
            if t == "uniform-deviate":
                self._mean_warning(name)
                return (vals[0] + vals[1]) / 2
            if t == "gamma-deviate":
                self._mean_warning(name)
                return vals[0] * vals[1]
            if t == "beta-deviate":
                self._mean_warning(name)
                return vals[0] / (vals[0] + vals[1])
        except (TypeError, ValueError, IndexError, ZeroDivisionError, OverflowError):
            raise RbdImportError(f"“{name}”: couldn't evaluate the <{t}> expression.") from None
        if t in ("system-mission-time", "mission-time"):
            raise RbdImportError(
                f"“{name}”: the mission time is used as a number here, which Reliafy can't "
                "turn into a life distribution.")
        raise RbdImportError(f"“{name}”: unsupported expression <{t}>.")

    def _mean_warning(self, name):
        self.note("deviate_mean", name)


_NOTES = {
    "time_factor": "Exponential events over a multiple of the mission time ({names}) were "
                   "imported with their rate scaled by that multiple.",
    "weibull_t0": "The Weibull location t0 of {names} was dropped (an imported diagram can't carry "
                  "an offset) — conservative, as failures may then start earlier.",
    "glm_gamma": "The GLM failure-on-demand probability γ of {names} was dropped; only the failure "
                 "rate λ and repair rate μ were imported.",
    "periodic_test": "Periodically tested events ({names}) were imported with their failure rate λ "
                     "only; the test interval, test duration and repair aren't modelled.",
    "deviate_mean": "Uncertainty distributions on the parameters of {names} were replaced by their "
                    "mean value.",
}


def _ccf_distribution(group):
    for c in group:
        if _tag(c) == "distribution":
            kids = _children(c)
            return kids[0] if kids else None
    return None


def _ccf_groups(conv: _Converter, used: set[str]) -> list[dict]:
    out = []
    for g in conv.m.ccf:
        name = g.get("name") or "?"
        members = [c.get("name") for c in g.iter() if _tag(c) == "basic-event" and c.get("name")]
        if not any(m in used for m in members):
            continue
        model = (g.get("model") or "").lower()
        if model != "beta-factor":
            conv.warn(f"Common-cause group “{name}” uses the {g.get('model')} model; only beta-factor "
                      "groups are imported, so this one was skipped.")
            continue
        factors = [c for c in g.iter() if _tag(c) == "factor"]
        if len(factors) != 1:
            conv.warn(f"Common-cause group “{name}”: expected one beta factor; skipped.")
            continue
        kids = _children(factors[0])
        beta = conv.num(kids[0], name) if kids else float("nan")
        if not (0 < beta < 1):
            conv.warn(f"Common-cause group “{name}”: beta={beta:g} is outside (0, 1); skipped.")
            continue
        out.append({"name": name, "members": [m for m in members if m in used], "beta": beta})
    return out


def _roots(model: _Model) -> list[str]:
    referenced: set[str] = set()
    for name, el in model.gates.items():
        scope = model.scope_of.get(id(el), "")
        for c in el.iter():
            if _tag(c) in ("gate", "event") and c.get("name"):
                ref = model.lookup(model.gates, c.get("name"), scope)
                if ref and ref != name:
                    referenced.add(ref)
    return [g for g in model.gates if g not in referenced]


def parse(data: bytes, filename: str) -> list[ImportedDiagram]:
    root = _parse_xml(data)
    model = _Model(root)
    if not model.gates:
        raise RbdImportError("The Open-PSA file defines no fault-tree gates.")
    roots = _roots(model)
    if not roots:
        raise RbdImportError("Every gate in the file feeds another gate, so there's no top event.")
    # Prefer a top gate named after its fault tree / the file when there are several.
    named = [r for r in roots if r in model.fault_trees
             or r.rsplit(".", 1)[-1].lower() in ("top", "top-event", "topevent", "failed", "failure")]
    if len(roots) > 1 and named:
        roots = named + [r for r in roots if r not in named]
    extra = []
    if len(roots) > MAX_ROOTS:
        extra = roots[MAX_ROOTS:]
        roots = roots[:MAX_ROOTS]

    diagrams, failures = [], []
    for top in roots:
        try:
            diagrams.append(_convert(model, top))
        except RbdImportError as exc:
            if len(roots) == 1:
                raise
            failures.append((top, str(exc)))
    if not diagrams:
        top, msg = failures[0]
        raise RbdImportError(
            f"None of the {len(roots)} top events could be imported. For “{top}”: {msg}")
    notes = [f"Top event “{t}” wasn't imported: {m}" for t, m in failures]
    if extra:
        notes.append(f"The file has {len(extra) + len(roots)} top events; only the first "
                     f"{MAX_ROOTS} were considered.")
    diagrams[0].warnings.extend(notes)
    return diagrams


def _convert(model: _Model, top: str) -> ImportedDiagram:
    conv = _Converter(model)
    conv.gate(top)
    tree = ft.FaultTree(conv.nodes, top)
    # Only report problems for events actually under this top event.
    used = _used_leaves(tree)
    if conv.no_data and set(conv.no_data) & used:
        names = sorted(set(conv.no_data) & used)
        raise RbdImportError(
            f"{len(names)} basic event(s) have no data ({_names(names)}), so there's nothing to "
            "build their blocks from.")
    fixed = sorted(set(conv.fixed_prob) & used)
    if fixed:
        raise RbdImportError(
            f"{len(fixed)} basic event(s) have a fixed probability and no failure-time model "
            f"({_names(fixed)}). Reliafy blocks need a life distribution (e.g. <exponential> "
            "with a failure rate), so this tree can't be imported as an RBD.")

    live = [n for n in used if isinstance(conv.nodes.get(n), ft.Leaf) and conv.nodes[n].constant is None]
    with_repair = [n for n in live if (conv.nodes[n].node or {}).get("repair")]
    repairable = bool(live) and len(with_repair) == len(live)
    if with_repair and not repairable:
        for n in with_repair:
            conv.nodes[n].node.pop("repair", None)
        conv.warn("Repair rates (GLM μ) were dropped and the diagram imported as non-repairable: "
                  "not every basic event has one.")
    ccf = _ccf_groups(conv, used)
    if ccf and repairable:
        conv.warn("Common-cause groups only apply to non-repairable (reliability) analysis; "
                  "they're ignored while the diagram is repairable.")
    unit = ""
    if len(conv.units) == 1:
        unit = next(iter(conv.units))
    elif len(conv.units) > 1:
        conv.warn(f"Parameters use several time units ({', '.join(sorted(conv.units))}); the "
                  "diagram's unit was left blank — check the rates are consistent.")
    graph, more = ft.to_graph(tree, unit=unit, repairable=repairable, ccf_groups=ccf)
    name = top
    ft_name = model.gate_ft.get(top)
    if ft_name and ft_name != top:
        name = f"{ft_name} — {top}"
    return ImportedDiagram(name=name, graph=graph, warnings=conv.all_warnings() + more)


def _used_leaves(tree: ft.FaultTree) -> set[str]:
    seen, stack = set(), [tree.top]
    while stack:
        n = stack.pop()
        if n in seen:
            continue
        seen.add(n)
        node = tree.nodes.get(n)
        if isinstance(node, ft.Gate):
            stack.extend(node.children)
    return {n for n in seen if isinstance(tree.nodes.get(n), ft.Leaf)}


def _names(names: list[str], limit: int = 6) -> str:
    shown = ", ".join(f"“{n}”" for n in names[:limit])
    return shown + (f" and {len(names) - limit} more" if len(names) > limit else "")
