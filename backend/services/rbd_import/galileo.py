"""Galileo dynamic-fault-tree import (``.dft``, as used by FFORT / Storm /
DFTCalc), plus Storm's JSON variant of the same model.

Format: https://dftbenchmarks.utwente.nl/ffort/galileo.html. Each statement
ends with ``;``::

    toplevel "System";
    "System" or "A" "B" "Vote";
    "Vote" 2of3 "C1" "C2" "C3";           # fails when >= 2 of the 3 fail
    "Pumps" csp "P1" "P2";                # cold spare gate: primary + spares
    "A" lambda=1e-4 repair=0.1;           # exponential life, repair rate

Mapped to Reliafy:

* ``or`` / ``and`` / ``KofM`` -> series / parallel / k-of-n voting;
* ``csp`` / ``hsp`` / ``wsp`` whose children are basic events used nowhere
  else -> a ``standby`` block (cold, warm or hot, by the dormancy factor);
* ``lambda=`` -> Exponential (a rate); ``phases=N`` -> Erlang = Gamma(shape N,
  rate lambda); Storm's ``shape=``/``rate=`` (Weibull, ``rate`` being Storm's
  *scale*) and ``mean=``/``stddev=`` (LogNormal of the underlying normal);
* ``repair=`` -> exponential repair at that rate; the diagram is repairable
  only when every event has one and no standby block is needed;
* ``res=`` (restoration factor, exponential only) thins the failure rate to
  ``lambda * (1 - res)``;
* ``prob=0`` / ``lambda=0`` events never fail and drop out; ``prob=1`` events
  have failed from the start;
* any other ``prob=`` with no life distribution (a fixed failure probability)
  -> a block *without* a life model, listed in the import notes with its
  probability, as Open-PSA's fixed-probability events are (#188). Reliafy
  blocks have no fixed-probability model, and inventing a failure rate would
  change the answer, so the user sets one before analysing;
* a basic event under several gates -> a repeated block in each place (one
  component; see :mod:`.fault_tree`).

Refused (no RBD equivalent): ``pand``/``por``/``seq``/``fdep``/``pdep``/
``mutex`` and inspection modules, ``prob`` outside [0, 1], ``prob`` combined
with a life distribution, a fixed-probability unit in a spare gate, coverage (``cov`` < 1), replication (``repl``),
parameterised models, spare modules (a gate as a spare) and spares shared
between gates.
"""

from __future__ import annotations

import json
import math
import re
from typing import Optional

from backend.services import import_guard

from . import fault_tree as ft
from .types import ImportedDiagram, RbdImportError

MAX_STATEMENTS = 100_000
MAX_STATEMENT_CHARS = 64 * 1024  # one statement (a gate's or event's line)
SNIFF_BYTES = 64 * 1024

_DYNAMIC = {
    "pand": "priority-AND",
    "pand-inclusive": "priority-AND",
    "pand-exclusive": "priority-AND",
    "por": "priority-OR",
    "por-inclusive": "priority-OR",
    "por-exclusive": "priority-OR",
    "seq": "sequence enforcer",
    "fdep": "functional dependency",
    "mutex": "mutual exclusion",
}
_SPARE = {"csp": 0.0, "hsp": 1.0, "wsp": 0.5}  # default dormancy factors
_KOFM = re.compile(r"^(\d+)of(\d+)$", re.I)


def _has_toplevel(head: str) -> bool:
    """Whether a line starts with the ``toplevel`` keyword."""
    for line in head.splitlines():
        s = line.lstrip()
        if s[:8].lower() == "toplevel" and (len(s) == 8 or s[8].isspace() or s[8] == '"'):
            return True
    return False


def sniff(data: bytes, filename: str) -> bool:
    name = (filename or "").lower()
    if name.endswith(".dft") or name.endswith(".galileo"):
        return True
    head = data[:SNIFF_BYTES].decode("utf-8", "replace")
    if ";" in head and _has_toplevel(head):
        return True
    stripped = head.lstrip("﻿ \t\r\n")
    if stripped.startswith("{") and '"toplevel"' in head and '"nodes"' in head:
        return True
    return False


def parse(data: bytes, filename: str) -> list[ImportedDiagram]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    base = (filename or "").rsplit("/", 1)[-1]
    stem = (base[:base.rfind(".")] if "." in base else base) or "Imported DFT"
    if text.lstrip().startswith("{"):
        top, gates, events = _parse_json(text)
    else:
        top, gates, events = _parse_text(text)
    return [_convert(top, gates, events, stem)]


# ---------------------------------------------------------------------------
# Text format
# ---------------------------------------------------------------------------


def _strip_comments(text: str) -> str:
    """Drop ``/* ... */`` blocks (each becomes a space; an unclosed one is
    kept), then ``// ...`` to the end of the line. Linear scans."""
    out, i = [], 0
    while True:
        a = text.find("/*", i)
        if a == -1:
            break
        b = text.find("*/", a + 2)
        if b == -1:
            break
        out.append(text[i:a])
        out.append(" ")
        i = b + 2
    out.append(text[i:])
    text = "".join(out)
    out, i = [], 0
    while True:
        a = text.find("//", i)
        if a == -1:
            break
        out.append(text[i:a])
        e = text.find("\n", a)
        i = len(text) if e == -1 else e
    out.append(text[i:])
    return "".join(out)


def _closing_quote(stmt: str, start: int) -> int:
    """Index of the ``"`` closing a quoted name opened at ``start`` (a quote
    after an odd run of backslashes is escaped), or -1."""
    j = start + 1
    while True:
        j = stmt.find('"', j)
        if j == -1:
            return -1
        k, slashes = j - 1, 0
        while k > start and stmt[k] == "\\":
            slashes += 1
            k -= 1
        if slashes % 2 == 0:
            return j
        j += 1


def _tokens(stmt: str) -> list[tuple[str, bool]]:
    """``(token, quoted)`` pairs: ``"quoted names"`` (backslash escapes kept
    as written) and bare words split on whitespace and quotes. ``a = b``
    joins to ``a=b``."""
    toks: list[tuple[str, bool]] = []
    i, n, quotes = 0, len(stmt), True
    while i < n:
        q = stmt.find('"', i) if quotes else -1
        seg = stmt[i:] if q == -1 else stmt[i:q]
        toks.extend((t, False) for t in seg.replace('"', " ").split())
        if q == -1:
            break
        end = _closing_quote(stmt, q)
        if end == -1:
            # An unclosed quote is skipped; no later quote can close either.
            quotes = False
            i = q + 1
            continue
        toks.append((stmt[q + 1:end], True))
        i = end + 1
    joined: list[tuple[str, bool]] = []
    for tok, quoted in toks:
        if (joined and not quoted and not joined[-1][1]
                and (tok.startswith("=") or joined[-1][0].endswith("="))):
            joined[-1] = (joined[-1][0] + tok, False)
        else:
            joined.append((tok, quoted))
    return joined


def _parse_text(text: str):
    top: Optional[str] = None
    gates: dict[str, tuple[str, list[str]]] = {}   # name -> (type, children)
    events: dict[str, dict[str, str]] = {}          # name -> attributes
    statements = [s.strip() for s in _strip_comments(text).split(";")]
    statements = [s for s in statements if s]
    if len(statements) > MAX_STATEMENTS:
        raise RbdImportError("The Galileo file has too many statements to import.")
    for stmt in statements:
        import_guard.check()
        if len(stmt) > MAX_STATEMENT_CHARS:
            raise RbdImportError(
                f"A statement in the Galileo file is longer than {MAX_STATEMENT_CHARS // 1024} KB "
                f"(“{stmt[:40]}…”) — too long to import.")
        toks = _tokens(stmt)  # tolerates "prob = 0.1"
        if not toks:
            continue
        first, quoted = toks[0]
        if not quoted and first.lower() == "toplevel":
            if len(toks) != 2:
                raise RbdImportError(f"Couldn't read the Galileo line “{stmt[:80]}”.")
            top = toks[1][0]
            continue
        if not quoted and first.lower() == "param":
            raise RbdImportError(
                "This is a parametric DFT (it declares “param”). Substitute the parameter "
                "values first — Reliafy imports concrete numbers only.")
        if len(toks) < 2:
            raise RbdImportError(f"Couldn't read the Galileo line “{stmt[:80]}”.")
        name = first
        if name in gates or name in events:
            raise RbdImportError(f"“{name}” is defined twice in the Galileo file.")
        second, second_quoted = toks[1]
        if not second_quoted and "=" in second:
            attrs: dict[str, str] = {}
            for tok, q in toks[1:]:
                if q or "=" not in tok:
                    raise RbdImportError(
                        f"Basic event “{name}”: couldn't read “{tok}” — expected attribute=value.")
                key, _, value = tok.partition("=")
                attrs[key.strip().lower()] = value.strip()
            events[name] = attrs
        else:
            gtype = second.lower()
            gates[name] = (gtype, [t for t, _ in toks[2:]])
    if top is None:
        raise RbdImportError("The Galileo file has no “toplevel” line naming the top event.")
    return top, gates, events


# ---------------------------------------------------------------------------
# Storm JSON variant
# ---------------------------------------------------------------------------

_JSON_GATES = {"and": "and", "or": "or", "vot": "vot", "spare": "spare",
               "pand": "pand", "por": "por", "seq": "seq", "fdep": "fdep",
               "pdep": "pdep", "mutex": "mutex"}


def _parse_json(text: str):
    try:
        doc = json.loads(text)
    except ValueError as exc:
        raise RbdImportError(f"The DFT JSON file isn't valid JSON ({exc}).") from None
    if not isinstance(doc, dict) or "nodes" not in doc or "toplevel" not in doc:
        raise RbdImportError("The DFT JSON file needs “toplevel” and “nodes”.")
    raw = doc.get("nodes") or []
    if not isinstance(raw, list) or len(raw) > MAX_STATEMENTS:
        raise RbdImportError("The DFT JSON “nodes” must be a list of a sensible size.")
    by_id: dict[str, dict] = {}
    for item in raw:
        data = item.get("data") if isinstance(item, dict) else None
        if not isinstance(data, dict) or data.get("id") is None:
            raise RbdImportError("Each DFT JSON node needs a “data” object with an “id”.")
        by_id[str(data["id"])] = data
    names = {i: str(d.get("name") or i) for i, d in by_id.items()}
    if len(set(names.values())) != len(names):
        names = {i: f"{names[i]} [{i}]" for i in by_id}
    top_id = str(doc["toplevel"])
    if top_id not in by_id:
        raise RbdImportError("The DFT JSON “toplevel” doesn't match any node id.")
    gates: dict[str, tuple[str, list[str]]] = {}
    events: dict[str, dict[str, str]] = {}
    for i, d in by_id.items():
        typ = str(d.get("type") or "").lower()
        if typ.startswith("be"):
            events[names[i]] = _json_event_attrs(names[i], d)
            continue
        kids = [names.get(str(c)) for c in d.get("children") or []]
        if None in kids:
            raise RbdImportError(f"Gate “{names[i]}” refers to a child id that doesn't exist.")
        if typ == "vot":
            k = int(d.get("voting") or 0)
            gates[names[i]] = (f"{k}of{len(kids)}", kids)
        elif typ == "spare":
            # Storm JSON has one spare type; dormancy comes from the events.
            gates[names[i]] = ("wsp", kids)
        else:
            gates[names[i]] = (_JSON_GATES.get(typ, typ), kids)
    return names[top_id], gates, events


def _json_event_attrs(name: str, d: dict) -> dict[str, str]:
    dist = str(d.get("distribution") or ("exponential" if "rate" in d else "")).lower()
    attrs: dict[str, str] = {}
    if dist == "exponential":
        attrs["lambda"] = str(d.get("rate"))
    elif dist == "erlang":
        attrs["lambda"] = str(d.get("rate"))
        attrs["phases"] = str(d.get("phases"))
    elif dist == "weibull":
        attrs["shape"] = str(d.get("shape"))
        attrs["rate"] = str(d.get("rate"))
    elif dist == "lognormal":
        attrs["mean"] = str(d.get("mean"))
        attrs["stddev"] = str(d.get("stddev"))
    elif dist == "const":
        attrs["prob"] = "1" if str(d.get("failed")).lower() in ("true", "1") else "0"
    elif dist == "probability":
        attrs["prob"] = str(d.get("prob"))
    else:
        raise RbdImportError(f"Basic event “{name}”: unsupported distribution “{dist or '?'}”.")
    if d.get("dorm") is not None:
        attrs["dorm"] = str(d["dorm"])
    if d.get("repair") is not None:
        attrs["repair"] = str(d["repair"])
    return attrs


# ---------------------------------------------------------------------------
# Conversion
# ---------------------------------------------------------------------------


def _num(name: str, key: str, value: str, signed: bool = False) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise RbdImportError(
            f"Basic event “{name}”: {key}={value} isn't a number (expressions and "
            "parameters aren't supported).") from None
    if not math.isfinite(v) or (v < 0 and not signed):
        raise RbdImportError(f"Basic event “{name}”: {key}={value} must be a non-negative number.")
    return v


_KNOWN_ATTRS = {"lambda", "prob", "dorm", "repair", "phases", "res", "interval",
                "shape", "rate", "scale", "mean", "stddev", "cov", "repl"}


def _event(name: str, attrs: dict[str, str], warnings: list[str],
           fixed: Optional[dict[str, float]] = None) -> tuple[ft.Leaf, Optional[float], Optional[float]]:
    """Return ``(leaf, repair_rate, explicit_dormancy)`` for a basic event.

    A fixed failure probability (``prob=`` strictly between 0 and 1, no life
    distribution) is recorded in ``fixed`` and becomes a block with no model."""
    unknown = sorted(set(attrs) - _KNOWN_ATTRS)
    if unknown:
        raise RbdImportError(
            f"Basic event “{name}” uses {', '.join(a + '=' for a in unknown)}, which Reliafy "
            "doesn't support.")
    if "repl" in attrs and _num(name, "repl", attrs["repl"]) != 1:
        raise RbdImportError(
            f"Basic event “{name}” is replicated (repl={attrs['repl']}); expand it into "
            "separate events before importing.")
    if "cov" in attrs and _num(name, "cov", attrs["cov"]) < 1:
        raise RbdImportError(
            f"Basic event “{name}” has imperfect coverage (cov={attrs['cov']}): an uncovered "
            "fault fails the whole system, which a block diagram can't express.")
    dorm = _num(name, "dorm", attrs["dorm"]) if "dorm" in attrs else None
    repair = _num(name, "repair", attrs["repair"]) if "repair" in attrs else None
    if repair == 0:
        repair = None
    has_life = any(k in attrs for k in ("lambda", "shape", "mean"))

    if "prob" in attrs:
        p = _num(name, "prob", attrs["prob"], signed=True)
        if not 0 <= p <= 1:
            raise RbdImportError(f"Basic event “{name}”: prob={attrs['prob']} isn't between 0 and 1.")
        if has_life:
            if p == 1:
                pass  # certainly subject to its life distribution
            elif p == 0:
                return ft.Leaf(name, constant=False), None, dorm
            else:
                raise RbdImportError(
                    f"Basic event “{name}” fails only with probability {p} and otherwise "
                    "never — Reliafy blocks need a plain life distribution.")
        elif p == 0:
            return ft.Leaf(name, constant=False), None, dorm
        elif p == 1:
            return ft.Leaf(name, constant=True), None, dorm
        # No time model: a block without a life model, which the user must
        # set before analysing — never an invented rate (as Open-PSA, #188).
        if fixed is not None:
            fixed[name] = p
        return ft.Leaf(name, {"type": "component"}), repair, dorm

    if "lambda" in attrs:
        lam = _num(name, "lambda", attrs["lambda"])
        phases = attrs.get("phases")
        n_ph = 1
        if phases is not None:
            n_ph_f = _num(name, "phases", phases)
            if n_ph_f < 1 or n_ph_f != int(n_ph_f):
                raise RbdImportError(f"Basic event “{name}”: phases={phases} must be a whole number ≥ 1.")
            n_ph = int(n_ph_f)
        res = _num(name, "res", attrs["res"]) if "res" in attrs else 0.0
        if res:
            if res >= 1:
                return ft.Leaf(name, constant=False), None, dorm
            if n_ph != 1:
                raise RbdImportError(
                    f"Basic event “{name}”: a restoration factor on an Erlang (phases>1) "
                    "event isn't supported.")
            lam *= 1.0 - res
            warnings.append(
                f"“{name}”: restoration factor res={attrs['res']} applied as an effective failure "
                f"rate λ(1−res) = {lam:g}.")
        if lam == 0:
            return ft.Leaf(name, constant=False), None, dorm
        model = ft.exponential_model(lam) if n_ph == 1 else ft.gamma_model(n_ph, lam)
    elif "shape" in attrs:
        scale_key = "scale" if "scale" in attrs else "rate"
        if scale_key not in attrs:
            raise RbdImportError(f"Basic event “{name}”: a Weibull needs shape= and rate= (scale).")
        model = ft.weibull_model(_num(name, scale_key, attrs[scale_key]), _num(name, "shape", attrs["shape"]))
    elif "mean" in attrs:
        if "stddev" not in attrs:
            raise RbdImportError(f"Basic event “{name}”: a lognormal needs mean= and stddev=.")
        model = ft.lognormal_model(_num(name, "mean", attrs["mean"], signed=True),
                                   _num(name, "stddev", attrs["stddev"]))
    else:
        raise RbdImportError(f"Basic event “{name}” has no failure distribution (lambda=...).")
    node = {"type": "component", "model": model}
    return ft.Leaf(name, node), repair, dorm


def _convert(top: str, gates, events, stem: str) -> ImportedDiagram:
    warnings: list[str] = []
    for name, (gtype, kids) in gates.items():
        if gtype in _DYNAMIC or gtype.startswith("pdep"):
            label = _DYNAMIC.get(gtype, "probabilistic dependency")
            why = ("its outcome depends on the order in which events fail"
                   if gtype.startswith(("pand", "por", "seq"))
                   else "one event forcing or excluding the failure of others")
            raise RbdImportError(
                f"Gate “{name}” is a {label} gate ({gtype}). A reliability block diagram can't "
                f"express {why}, so this dynamic fault tree can't be imported.")
        if "insp" in gtype:
            raise RbdImportError(
                f"“{name}” is an inspection module ({gtype}). Periodic inspection and "
                "maintenance can't be expressed in a reliability block diagram.")
        if gtype not in ("and", "or") and gtype not in _SPARE and not _KOFM.match(gtype):
            raise RbdImportError(f"Gate “{name}” has an unknown gate type “{gtype}”.")
        if not kids:
            raise RbdImportError(f"Gate “{name}” has no inputs.")
        for c in kids:
            if c not in gates and c not in events:
                raise RbdImportError(f"Gate “{name}” uses “{c}”, which isn't defined.")
    if top not in gates and top not in events:
        raise RbdImportError(f"The top event “{top}” isn't defined.")

    # Only the events under the top event matter (dynamic gates were refused
    # above wherever they are, since an FDEP acts from outside the tree).
    reach, stack = set(), [top]
    while stack:
        n = stack.pop()
        if n in reach:
            continue
        reach.add(n)
        if n in gates:
            stack.extend(gates[n][1])

    nodes: dict[str, ft.Node] = {}
    repair: dict[str, Optional[float]] = {}
    dorm: dict[str, Optional[float]] = {}
    fixed: dict[str, float] = {}
    for name, attrs in events.items():
        if name not in reach:
            continue
        leaf, rep, d = _event(name, attrs, warnings, fixed)
        nodes[name] = leaf
        repair[name] = rep
        dorm[name] = d

    # Which events feed which gates (to spot spares shared across gates).
    parents: dict[str, list[str]] = {}
    for g, (_, kids) in gates.items():
        if g not in reach:
            continue
        for c in kids:
            parents.setdefault(c, []).append(g)

    has_standby = False
    for name, (gtype, kids) in gates.items():
        if name not in reach:
            continue
        m = _KOFM.match(gtype)
        if gtype in ("and", "or"):
            nodes[name] = ft.Gate(name, gtype, list(kids))
        elif m:
            k, total = int(m.group(1)), int(m.group(2))
            if total != len(kids):
                warnings.append(
                    f"Gate “{name}” is written {gtype} but has {len(kids)} inputs; read as "
                    f"{k} of {len(kids)}.")
            nodes[name] = ft.Gate(name, "atleast", list(kids), k)
        else:
            nodes[name] = _spare_block(name, gtype, kids, nodes, gates, parents, dorm, warnings)
            has_standby = True

    tree = ft.FaultTree(nodes, top)
    # Events actually in play (standby groups hide their members).
    in_tree = _reachable(tree)
    used_events = [e for e in nodes if e in events and e in in_tree]
    repairs = [repair[e] for e in used_events if nodes[e].constant is None]
    all_repair = bool(repairs) and all(r is not None for r in repairs)
    any_repair = any(r is not None for r in repair.values())
    repairable = False
    if all_repair and not has_standby:
        repairable = True
        for e in used_events:
            if nodes[e].constant is None:
                nodes[e].node["repair"] = ft.exponential_model(repair[e])
    elif any_repair:
        why = ("the model uses spare gates, which repairable diagrams don't support"
               if has_standby else "not every basic event has a repair rate")
        warnings.append(
            f"Repair rates were dropped and the diagram imported as non-repairable: {why}.")

    shown_fixed = [e for e in used_events if e in fixed]
    if shown_fixed:
        n = len(shown_fixed)
        shown = [f"“{e}” (p = {fixed[e]:.3g})" for e in shown_fixed]
        more_txt = f" and {n - 10} more" if n > 10 else ""
        warnings.append(
            f"{n} basic event(s) have a fixed probability and no failure-time model: "
            f"{', '.join(shown[:10])}{more_txt}. Reliafy blocks need a life distribution, so "
            f"{'it was' if n == 1 else 'they were'} imported as "
            f"block{'' if n == 1 else 's'} WITHOUT a life model — set one (e.g. an "
            "exponential failure rate) before analysing. Nothing was assumed for "
            f"{'it' if n == 1 else 'them'}.")

    graph, more = ft.to_graph(tree, unit="", repairable=repairable)
    warnings.extend(more)
    return ImportedDiagram(name=stem or top, graph=graph, warnings=warnings)


def _reachable(tree: ft.FaultTree) -> set[str]:
    seen, stack = set(), [tree.top]
    while stack:
        n = stack.pop()
        if n in seen or n not in tree.nodes:
            continue
        seen.add(n)
        node = tree.nodes[n]
        if isinstance(node, ft.Gate):
            stack.extend(node.children)
    return seen


def _spare_block(name, gtype, kids, nodes, gates, parents, dorm, warnings) -> ft.Leaf:
    """A spare gate whose children are basic events -> one ``standby`` leaf."""
    modules = [c for c in kids if c in gates]
    if modules:
        raise RbdImportError(
            f"Spare gate “{name}” uses a sub-tree (“{modules[0]}”) as a spare module. Reliafy "
            "standby blocks hold individual units, so this can't be imported.")
    shared = [c for c in kids if len(parents.get(c, [])) > 1]
    if shared:
        raise RbdImportError(
            f"Spare gate “{name}” shares {', '.join('“' + s + '”' for s in shared)} with another "
            "gate. A shared spare (one unit available to several gates) has no block-diagram "
            "equivalent, and duplicating it would change the result.")
    if len(set(kids)) != len(kids):
        raise RbdImportError(f"Spare gate “{name}” lists the same unit twice.")
    leaves = [nodes[c] for c in kids]
    if any(lf.constant is not None for lf in leaves):
        raise RbdImportError(
            f"Spare gate “{name}” has a unit with a fixed state (prob=0/1 or lambda=0); give each "
            "unit a failure rate.")
    no_model = [c for c, lf in zip(kids, leaves) if not (lf.node or {}).get("model")]
    if no_model:
        raise RbdImportError(
            f"Spare gate “{name}” has a unit with a fixed failure probability "
            f"(“{no_model[0]}”); a standby block needs each unit's failure distribution, so give "
            "it a failure rate (lambda=...).")
    if len(kids) < 2:
        return ft.Leaf(name, dict(leaves[0].node), label=kids[0])
    primary, spares = leaves[0], leaves[1:]
    spare_keys = {ft.model_key(s.node["model"]) for s in spares}
    if len(spare_keys) > 1:
        raise RbdImportError(
            f"Spare gate “{name}” has spares with different failure distributions. A Reliafy "
            "standby block has one primary model and one (shared) spare model.")
    default = _SPARE[gtype]
    factors = [dorm[c] if dorm[c] is not None else default for c in kids[1:]]
    # Galileo's dormancy factor is exactly Reliafy's (RePyability's): an idle
    # spare fails at that fraction of its active rate — 0 cold, 1 hot.
    dormancy = max(factors)
    if len(set(factors)) > 1:
        warnings.append(
            f"Spare gate “{name}” has spares with different dormancy factors "
            f"({', '.join(f'{f:g}' for f in sorted(set(factors)))}). A Reliafy standby block has one, "
            f"so it was imported with the highest, {dormancy:g} — conservative: the imported "
            "reliability is a lower bound.")
    node = {"type": "standby", "model": primary.node["model"], "spares": len(spares),
            "cold": dormancy == 0, "dormancy": dormancy}
    if ft.model_key(spares[0].node["model"]) != ft.model_key(primary.node["model"]):
        node["standbyModel"] = spares[0].node["model"]
    return ft.Leaf(name, node)
