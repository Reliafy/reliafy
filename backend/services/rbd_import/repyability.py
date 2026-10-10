"""RePyability JSON import (#174): a diagram saved with RePyability's
``RBD.to_json()`` / ``to_dict()`` (``repyability.rbd.serialisation``), or
downloaded from Reliafy with "Download as RePyability JSON".

**Files from Reliafy** carry a ``"reliafy"`` part (see
:mod:`backend.services.rbd_json`) holding the diagram as the builder draws
it. When the RePyability part is still exactly what Reliafy would write for
it, the diagram comes back as it was — labels, positions, unit, pins, costs,
safety settings and all. Links to saved models and sub-system diagrams come
back only when the importing user can open them and they haven't changed
since (:meth:`ImportedDiagram.links`); otherwise a block keeps its own
parameters and a sub-system is drawn in place.

**Any other file** (or one edited in code after the download) is read from
the RePyability part:

* parametric SurPyval models in Reliafy's distributions -> blocks (an offset,
  ``p`` and ``f0`` kept; a fitted model's covariance isn't);
* ``RepeatedNode`` -> a series / parallel block of identical units;
  ``RepeatedStandbyNode`` and ``StandbyModel`` with one unit operating and
  identical spares -> a standby block (cold, warm or hot by the dormancy
  factor); perfect reliability -> a vote / junction node; perfect
  unreliability -> a block pinned failed; repeated nodes -> repeated blocks;
* ``k`` on a vote node is its n; on any other node a vote node is put in
  front of it;
* nested non-repairable diagrams are drawn in place, between two junctions;
* beta-factor common-cause groups, on either basis (the probability, RePyability's
  default, or the rate);
* repairable diagrams: life and repair models, instant repair, costs (a
  per-failure cost drawn from a uniform distribution -> a range), preventive
  maintenance (age, block, condition), proof tests, maintenance groups,
  repair crews and their priorities, standby groups (also one repaired one
  unit at a time), the system downtime cost rate.

What Reliafy can't hold is listed in the import notes, and the block is
imported without a model (to set before analysing) rather than guessed:
capacities, MGL common-cause models, degrading, regression,
load-sharing and non-parametric models, distributions Reliafy doesn't offer,
standby with more than one unit operating or mixed spares, imperfect repair,
replace-after-n-repairs, other nested repairable diagrams. The importer never
calls RePyability's or SurPyval's own loaders on the file: it reads the
document as data, within the import limits.
"""

from __future__ import annotations

import json
import math
from typing import Any, Callable, Optional

from backend.services import import_guard

from .types import ImportedDiagram, RbdImportError

SNIFF_BYTES = 64 * 1024
MAX_DEPTH = 16          # nested diagrams
MAX_LIST = 200_000      # entries in any one list of the document
_TYPES = ("NonRepairableRBD", "RepairableRBD")
_FIXED_RATE_LIFE = 1e11  # Reliafy's always-up vote node: Weibull(alpha 1e12, beta 1)


def sniff(data: bytes, filename: str) -> bool:
    head = data[:SNIFF_BYTES].decode("utf-8", "replace").lstrip("﻿ \t\r\n")
    if not head.startswith("{"):
        return False
    if '"repyability_version"' in head:
        return True
    return ('"edges"' in head and ('"reliabilities"' in head or '"components"' in head)
            and ('"NonRepairableRBD"' in head or '"RepairableRBD"' in head))


def parse(data: bytes, filename: str) -> list[ImportedDiagram]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise RbdImportError("The JSON file isn't UTF-8 text.") from None
    try:
        doc = json.loads(text)
    except RecursionError:
        raise RbdImportError("The JSON file is nested too deeply.") from None
    except ValueError as exc:
        raise RbdImportError(f"The file isn't valid JSON ({exc}).") from None
    network = isinstance(doc, dict) and doc.get("type") == "Network"  # #160: Reliafy's network files
    if not isinstance(doc, dict) or (doc.get("type") not in _TYPES and not network):
        raise RbdImportError(
            "This JSON isn't a RePyability diagram: its “type” must be NonRepairableRBD or RepairableRBD "
            "(save one with rbd.to_json()).")
    base = (filename or "").rsplit("/", 1)[-1]
    stem = (base.split(".", 1)[0] if "." in base else base) or "Imported diagram"
    if network:
        from backend.services import rbd_network

        return rbd_network.import_document(doc, stem)

    from backend.services import rbd_json

    ext = doc.get(rbd_json.EXTENSION_KEY)
    core = {k: v for k, v in doc.items() if k != rbd_json.EXTENSION_KEY}
    if isinstance(ext, dict) and ext.get("format") == rbd_json.FORMAT:
        saved = _Saved.read(ext)
        if saved is not None and saved.matches(core):
            return [saved.diagram(stem)]
        diagram = convert(core, stem)
        diagram.warnings.insert(0, (
            "This file's RePyability part was changed after Reliafy wrote it, so the diagram was rebuilt "
            "from it; block labels and the time unit were kept where the blocks still match."))
        if saved is not None:
            saved.overlay(diagram)
        return [diagram]
    return [convert(core, stem)]


# ---------------------------------------------------------------------------
# Files Reliafy wrote: the "reliafy" part
# ---------------------------------------------------------------------------
class _Saved:
    """The builder graph Reliafy stored next to the RePyability part."""

    def __init__(self, name: str, graph: dict, subsystems: dict):
        self.name = name
        self.graph = graph
        self.subsystems = subsystems

    @classmethod
    def read(cls, ext: dict) -> Optional["_Saved"]:
        from backend.services.rbd_graph import GraphError, check_limits

        graph = ext.get("graph")
        subs = ext.get("subsystems") or {}
        if not isinstance(graph, dict) or not isinstance(subs, dict) or len(subs) > 1000:
            return None
        clean: dict[str, dict] = {}
        try:
            check_limits(graph)
            for sub_id, entry in subs.items():
                import_guard.check()
                if not isinstance(entry, dict) or not isinstance(entry.get("graph"), dict):
                    return None
                check_limits(entry["graph"])
                clean[str(sub_id)] = {"name": str(entry.get("name") or "Sub-system")[:200],
                                      "graph": entry["graph"]}
        except GraphError:
            return None
        return cls(str(ext.get("name") or "")[:200], graph, clean)

    def _resolve(self, sub_id: str) -> Optional[dict]:
        entry = self.subsystems.get(sub_id)
        return entry["graph"] if entry else None

    def matches(self, core: dict) -> bool:
        """Whether the RePyability part is exactly what Reliafy writes for
        the stored graph (so nothing was edited outside Reliafy)."""
        from backend.services import rbd_json

        try:
            expected, _ = rbd_json.core(self.graph, None, self._resolve)
        except import_guard.ImportBudgetExceeded:
            raise
        except Exception:  # noqa: BLE001 - untrusted graph: no match
            return False
        return rbd_json.comparable(expected) == rbd_json.comparable(core)

    def diagram(self, stem: str) -> ImportedDiagram:
        d = ImportedDiagram(self.name or stem, {}, [], "Reliafy (RePyability JSON)")
        d.graph, d.warnings = self.portable(None, None)

        def links(saved_model: Optional[Callable], saved_rbd: Optional[Callable]) -> None:
            d.graph, d.warnings = self.portable(saved_model, saved_rbd)

        d.links = links
        return d

    # -- links to the importing user's saved models and diagrams ---------
    def portable(self, saved_model, saved_rbd) -> tuple[dict, list[str]]:
        """The stored graph, keeping only the links ``saved_model`` /
        ``saved_rbd`` (id -> the user's readable saved model / diagram, or
        None) confirm; the rest are cut (a block keeps its own parameters, a
        sub-system is drawn in place)."""
        notes: list[str] = []
        unlinked: list[str] = []
        graph = self._relink(self.graph, saved_model, saved_rbd, unlinked, notes, frozenset())
        if unlinked:
            notes.insert(0, (
                f"{_names(unlinked)} used saved models you can't open here (or that were refit since): "
                "they keep the parameters in the file, without the link."))
        return graph, notes

    def _relink(self, graph, saved_model, saved_rbd, unlinked, notes, visited) -> dict:
        graph = json.loads(json.dumps(graph))  # a private copy
        nodes: list[dict] = []
        more_edges: list[dict] = []
        more_ccf: list[dict] = []
        ends: dict[str, tuple[str, str]] = {}
        for node in graph.get("nodes") or []:
            import_guard.check()
            if not isinstance(node, dict):
                continue
            data = node.get("data") if isinstance(node.get("data"), dict) else {}
            node["data"] = data
            label = str(data.get("label") or node.get("id"))
            for key in ("model", "standbyModel", "repair"):
                model = data.get(key)
                if isinstance(model, dict) and (model.get("modelId") or model.get("model_id")):
                    if not _same_saved_model(model, saved_model):
                        data[key] = _unlinked(model)
                        unlinked.append(label)
            ref = data.get("rbd")
            if node.get("type") == "subsystem" and isinstance(ref, dict) and ref.get("id"):
                sub_id = str(ref["id"])
                if not self._same_saved_rbd(sub_id, saved_rbd):
                    sub = self.subsystems.get(sub_id)
                    if sub is None or sub_id in visited or len(visited) >= MAX_DEPTH:
                        raise RbdImportError(f"“{label}”: its sub-system diagram is missing from the file.")
                    inner = self._relink(sub["graph"], saved_model, saved_rbd, unlinked, notes,
                                         visited | {sub_id})
                    new_nodes, new_edges, new_ccf, ends[str(node.get("id"))] = _inline(node, inner)
                    nodes.extend(new_nodes)
                    more_edges.extend(new_edges)
                    more_ccf.extend(new_ccf)
                    notes.append(f"“{label}” linked the sub-system “{sub['name']}”, which you can't open here "
                                 "(or which has changed since): its diagram is drawn in place.")
                    if data.get("state") == "working":
                        notes.append(f"“{label}” was pinned working; the pin was dropped when its diagram was "
                                     "drawn in place.")
                    continue
            nodes.append(node)
        graph["nodes"] = nodes
        if ends:
            edges = []
            for e in graph.get("edges") or []:
                if not isinstance(e, dict):
                    continue
                s, t = str(e.get("source")), str(e.get("target"))
                edges.append({"source": ends[s][1] if s in ends else s,
                              "target": ends[t][0] if t in ends else t})
            graph["edges"] = edges + more_edges
            if more_ccf:
                graph["ccf_groups"] = list(graph.get("ccf_groups") or []) + more_ccf
            for n in nodes:  # the drawn-in-place blocks have no place yet: lay it out again
                n.pop("position", None)
        return graph

    def _same_saved_rbd(self, sub_id: str, saved_rbd) -> bool:
        """The user can open the sub-system and it still holds the diagram
        the file was written with."""
        from backend.services import rbd_json

        if saved_rbd is None:
            return False
        try:
            current = saved_rbd(sub_id)
            stored = self.subsystems.get(sub_id)
            if current is None or stored is None:
                return False

            def resolve(i):
                found = saved_rbd(i)
                return found.graph if found is not None else None

            now, _ = rbd_json.core(current.graph or {}, None, resolve)
            then, _ = rbd_json.core(stored["graph"], None, self._resolve)
        except import_guard.ImportBudgetExceeded:
            raise
        except Exception:  # noqa: BLE001 - can't compare: draw it in place
            return False
        return rbd_json.comparable(now) == rbd_json.comparable(then)

    def overlay(self, diagram: ImportedDiagram) -> None:
        """Labels and the time unit from the stored graph, onto a diagram
        rebuilt from an edited RePyability part, where the ids still match."""
        stored = {str(n.get("id")): n for n in self.graph.get("nodes") or [] if isinstance(n, dict)}
        for node in diagram.graph["nodes"]:
            old = stored.get(node["id"])
            if old is None or old.get("type") != node["type"] or node["type"] in ("input", "output"):
                continue
            label = (old.get("data") or {}).get("label")
            if isinstance(label, str) and label.strip():
                node["data"]["label"] = label[:200]
        unit = self.graph.get("unit")
        if isinstance(unit, str):
            diagram.graph["unit"] = unit[:40]
        if self.name:
            diagram.name = self.name


def _same_saved_model(model: dict, saved_model) -> bool:
    """The user can open the saved model and its parameters are still the
    block's own (the analysis uses the block's)."""
    from backend.services import rbd_graph

    if saved_model is None:
        return False
    model_id = str(model.get("modelId") or model.get("model_id"))
    try:
        current = rbd_graph.normalize_model({"saved_model_id": model_id}, "block", saved_model)
    except import_guard.ImportBudgetExceeded:
        raise
    except Exception:  # noqa: BLE001 - unreadable or not a life model
        return False
    if current.get("distribution_id") != model.get("distribution_id"):
        return False
    if _param_map(current.get("params")) != _param_map(model.get("params")):
        return False
    return _extras(current.get("extras")) == _extras(model.get("extras"))


def _param_map(params) -> dict:
    out = {}
    for p in params or []:
        try:
            out[str(p.get("name"))] = float(p.get("value"))
        except (AttributeError, TypeError, ValueError):
            out[str(p)] = None
    return out


def _extras(extras) -> dict:
    if not isinstance(extras, dict):
        return {}
    return {k: float(v) for k, v in extras.items() if k in ("gamma", "p", "f0") and v is not None}


def _unlinked(model: dict) -> dict:
    out = {k: model[k] for k in ("distribution", "distribution_id", "params", "extras", "placeholder")
           if model.get(k) is not None}
    out["source"] = "params"
    return out
def _inline(node: dict, inner: dict) -> tuple[list, list, list, tuple[str, str]]:
    """A sub-system block's diagram drawn in its place: ``(nodes, edges,
    common-cause groups, (entry, exit))``. Its blocks get ids prefixed by the
    block's, between an in and an out junction that take the block's
    connections. Pins inside a sub-system aren't applied by the analysis, so
    they're dropped; a block pinned failed stays failed (its out junction)."""
    nid = str(node.get("id"))
    label = str((node.get("data") or {}).get("label") or nid)
    ids: dict[str, str] = {}
    nodes = []
    for sub in inner.get("nodes") or []:
        sid = str(sub.get("id"))
        data = dict(sub.get("data") or {})
        data.pop("state", None)
        if sub.get("type") in ("input", "output"):
            end = "in" if sub.get("type") == "input" else "out"
            ids[sid] = f"{nid}/{end}"
            jdata = {"label": f"{label} ({end})", "n": 1}
            if end == "out" and (node.get("data") or {}).get("state") == "failed":
                jdata["state"] = "failed"
            nodes.append({"id": ids[sid], "type": "knode", "data": jdata})
            continue
        ids[sid] = f"{nid}/{sid}"
        if data.get("repeat_of") not in (None, ""):
            data["repeat_of"] = f"{nid}/{data['repeat_of']}"
        nodes.append({"id": ids[sid], "type": sub.get("type"), "data": data})
    entry, exit_ = f"{nid}/in", f"{nid}/out"
    if entry not in ids.values() or exit_ not in ids.values():
        raise RbdImportError(f"“{label}”: its sub-system diagram has no input or output node.")
    edges = [{"source": ids.get(str(e.get("source")), f"{nid}/{e.get('source')}"),
              "target": ids.get(str(e.get("target")), f"{nid}/{e.get('target')}")}
             for e in inner.get("edges") or [] if isinstance(e, dict)]
    ccf = [{**g, "id": f"{nid}/{g.get('id') or i}", "members": [ids.get(str(m), f"{nid}/{m}") for m in g.get("members") or []]}
           for i, g in enumerate(inner.get("ccf_groups") or []) if isinstance(g, dict)]
    return nodes, edges, ccf, (entry, exit_)



# ---------------------------------------------------------------------------
# Any RePyability file: read the RePyability part
# ---------------------------------------------------------------------------
def convert(core: dict, stem: str) -> ImportedDiagram:
    conv = _Converter(core.get("type") == "RepairableRBD")
    graph = conv.top(core)
    conv.finish_notes()
    return ImportedDiagram(stem, graph, conv.notes, "RePyability JSON")


def _names(labels: list[str], limit: int = 8) -> str:
    labels = list(dict.fromkeys(labels))
    shown = ", ".join(f"“{n}”" for n in labels[:limit])
    return shown + (f" and {len(labels) - limit} more" if len(labels) > limit else "")


def _finite(value) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    x = float(value)
    return x if math.isfinite(x) else None


def _whole(value) -> Optional[int]:
    x = _finite(value)
    return int(x) if x is not None and x == int(x) else None


def _list(value, what: str) -> list:
    if value is None:
        return []
    if not isinstance(value, list):
        raise RbdImportError(f"The diagram's “{what}” must be a list.")
    if len(value) > MAX_LIST:
        raise RbdImportError(f"The diagram's “{what}” has more than {MAX_LIST:,} entries.")
    return value


def _key(name) -> str:
    """A node name as a hashable key (JSON has no tuples: a list is one)."""
    if isinstance(name, str):
        return json.dumps(name)
    if isinstance(name, int) and not isinstance(name, bool):
        return json.dumps(name)
    if isinstance(name, float) and math.isfinite(name):
        return json.dumps(name)
    if isinstance(name, list) and len(name) <= 50:
        return "[" + ",".join(_key(part) for part in name) + "]"
    raise RbdImportError("Node names must be text, numbers or lists of them.")


def _label(name) -> str:
    text = name if isinstance(name, str) else json.dumps(name)
    return (" ".join(text.split()) or "Block")[:200]


def _surpyval_names() -> dict:
    from backend.fitting import DISTRIBUTIONS

    return {getattr(e["dist"], "name", ""): did for did, e in DISTRIBUTIONS.items()}


# A model's description by its RePyability kind, for the import notes.
_KIND_TEXT = {
    "degrading": "a degrading (multi-stage) model",
    "regression_node": "a fitted regression model",
    "load_sharing": "a load-sharing group",
    "non_repairable": "a repairable unit inside a non-repairable diagram",
    "standby": "a standby group",
    "repeated_standby": "a cold-standby group",
    "repeated_node": "a group of identical units",
    "rbd": "a nested diagram",
    "perfect_reliability": "perfect reliability",
    "perfect_unreliability": "a failed unit",
}


class _Converter:
    def __init__(self, repairable: bool):
        self.repairable = repairable
        self.nodes: dict[str, dict] = {}
        self.order: list[str] = []
        self.edges: dict[tuple[str, str], None] = {}
        self.ccf: list[dict] = []
        self.notes: list[str] = []
        self.blocks_without: list[tuple[str, str]] = []   # (label, why)
        self.fitted: list[str] = []
        self.graph_extra: dict[str, Any] = {}
        self.dist_ids = _surpyval_names()
        self.votes: set[str] = set()   # vote nodes whose n is already their k

    # -- bookkeeping ------------------------------------------------------
    def note(self, text: str) -> None:
        if text not in self.notes:
            self.notes.append(text)

    def add(self, nid: str, ntype: str, data: dict) -> str:
        from backend.services.rbd_graph import MAX_BLOCKS

        import_guard.check()
        base, i = nid[:200], 1
        while nid in self.nodes or (ntype not in ("input", "output") and nid in ("input", "output")):
            i += 1
            nid = f"{base}_{i}"
        if len(self.nodes) >= MAX_BLOCKS + 2:
            raise RbdImportError(
                f"The diagram expands to more than {MAX_BLOCKS:,} blocks once its nested diagrams are drawn "
                "in place.")
        self.nodes[nid] = {"id": nid, "type": ntype, "data": data}
        self.order.append(nid)
        return nid

    def connect(self, src: str, dst: str) -> None:
        from backend.services.rbd_graph import MAX_EDGES

        if src != dst:
            self.edges.setdefault((src, dst), None)
            if len(self.edges) > MAX_EDGES:
                raise RbdImportError(f"The diagram has more than {MAX_EDGES:,} connections.")

    def without_model(self, nid_base: str, label: str, why: str) -> str:
        self.blocks_without.append((label, why))
        return self.add(nid_base, "component", {"label": label})

    def finish_notes(self) -> None:
        for label, why in self.blocks_without:
            self.note(f"“{label}” was imported without a life model — {why}. Set it before analysing.")
        if self.fitted:
            self.note(f"{_names(self.fitted)} use fitted models: Reliafy keeps their parameters, not the fit's "
                      "covariance (so no confidence band until you link a saved fit).")

    # -- life models ------------------------------------------------------
    def life(self, d, label: str, what: str = "life") -> tuple[Optional[dict], Optional[str]]:
        """``(builder model, None)`` or ``(None, why it can't be read)``."""
        if not isinstance(d, dict):
            return None, f"its {what} model isn't a model"
        kind = d.get("kind")
        if kind == "surpyval":
            m = d.get("model")
            if not isinstance(m, dict):
                return None, f"its {what} model isn't a model"
            if m.get("parameterization") != "parametric":
                return None, f"its {what} model is non-parametric ({str(m.get('model') or '')[:40]})"
            dist, names, values = m.get("distribution"), m.get("param_names"), m.get("params")
            extras = {}
            if m.get("offset") and _finite(m.get("gamma")) is not None:
                extras["gamma"] = _finite(m["gamma"])
            if m.get("lfp") and _finite(m.get("p")) is not None:
                extras["p"] = _finite(m["p"])
            if m.get("zi") and _finite(m.get("f0")) is not None:
                extras["f0"] = _finite(m["f0"])
            # A fitted model carries its covariance: "covariance" from SurPyval
            # 0.23 (#605), "cov_matrix" before.
            fitted = m.get("covariance") is not None or m.get("cov_matrix") is not None
            if fitted or str(m.get("how") or "") not in ("given parameters", "from_params", ""):
                self.fitted.append(label)
        elif kind == "parametric":  # RePyability's format before 0.10
            dist, names, values = d.get("dist"), None, d.get("params")
            raw = d.get("extras") if isinstance(d.get("extras"), dict) else {}
            extras = {k: _finite(raw[k]) for k in ("gamma", "p", "f0") if _finite(raw.get(k)) is not None}
        else:
            return None, f"its {what} model is {_KIND_TEXT.get(kind, 'a kind Reliafy can’t read')}"
        return self._parametric(dist, names, values, extras, what)

    def _parametric(self, dist, names, values, extras, what):
        from backend import fitting

        did = self.dist_ids.get(dist) if isinstance(dist, str) else None
        if did is None:
            shown = str(dist)[:40] if isinstance(dist, str) else "unknown"
            return None, f"its {what} model is a {shown} distribution, which Reliafy doesn't offer"
        entry = fitting.DISTRIBUTIONS[did]
        expected = list(entry["dist"].parameter_names)
        if not isinstance(values, list) or len(values) != len(expected):
            return None, f"its {what} model's parameters don't fit a {entry['name']}"
        numbers = [_finite(v) for v in values]
        if any(v is None for v in numbers):
            return None, f"its {what} model's parameters aren't all finite numbers"
        if names is not None and list(names) != expected:
            return None, f"its {what} model's parameters aren't a {entry['name']}'s ({', '.join(expected)})"
        model = {
            "source": "params",
            "distribution": entry["name"],
            "distribution_id": did,
            "params": [{"name": n, "value": v} for n, v in zip(expected, numbers)],
        }
        if extras:
            model["extras"] = extras
        return model, None

    def _fixed_time(self, d) -> Optional[float]:
        """The time of a SurPyval ``ExactEventTime`` (a fixed duration)."""
        if isinstance(d, dict) and d.get("kind") == "surpyval" and isinstance(d.get("model"), dict):
            m = d["model"]
            if m.get("distribution") == "ExactEventTime" and isinstance(m.get("params"), list) and len(m["params"]) == 1:
                return _finite(m["params"][0])
        return None

    def _cost(self, value, label: str, what: str):
        """A cost: a number, or a uniform distribution -> a ``{min, max}``
        range; None (and a note) for anything else."""
        x = _finite(value)
        if x is not None:
            return x
        if isinstance(value, dict) and isinstance(value.get("model"), dict):
            m = value["model"]
            if m.get("distribution") == "Uniform" and isinstance(m.get("params"), list) and len(m["params"]) == 2:
                low, high = (_finite(v) for v in m["params"])
                if low is not None and high is not None:
                    return {"min": low, "max": high}
        self.note(f"“{label}”: its {what} is drawn from a distribution Reliafy can't hold (only a fixed cost or a "
                  "uniform range), so it was left out.")
        return None

    # -- diagrams ---------------------------------------------------------
    def top(self, d: dict) -> dict:
        self.diagram(d, prefix="", depth=0, label="")
        graph = {
            "nodes": [self.nodes[n] for n in self.order],
            "edges": [{"source": s, "target": t} for s, t in self.edges],
            "unit": "",
        }
        if self.repairable:
            graph["repairable"] = True
        if self.ccf:
            graph["ccf_groups"] = self.ccf
        graph.update(self.graph_extra)
        return graph

    def diagram(self, d: dict, prefix: str, depth: int, label: str) -> tuple[str, str]:
        """Draw one diagram; returns its ``(entry, exit)`` node ids."""
        if depth > MAX_DEPTH:
            raise RbdImportError(f"The diagram nests diagrams more than {MAX_DEPTH} deep.")
        if not isinstance(d, dict) or d.get("type") not in _TYPES:
            raise RbdImportError("A nested diagram isn't a RePyability diagram.")
        repairable = d.get("type") == "RepairableRBD"
        raw_names: dict[str, Any] = {}   # key -> the name as the file gives it, in file order
        edges = []
        for e in _list(d.get("edges"), "edges"):
            import_guard.check()
            if not isinstance(e, list) or len(e) != 2:
                raise RbdImportError("Each edge must be a pair of node names.")
            a, b = _key(e[0]), _key(e[1])
            raw_names.setdefault(a, e[0])
            raw_names.setdefault(b, e[1])
            edges.append((a, b))
        if not edges:
            raise RbdImportError("The diagram has no edges.")
        entries_key = "components" if repairable else "reliabilities"
        value_key = "component" if repairable else "model"
        values: dict[str, Any] = {}
        for entry in _list(d.get(entries_key), entries_key):
            if not isinstance(entry, dict) or "node" not in entry:
                raise RbdImportError(f"Each of the diagram's “{entries_key}” needs a “node”.")
            key = _key(entry["node"])
            if key not in raw_names:
                self.note(f"“{_label(entry['node'])}” isn't connected to anything, so it was left out.")
                continue
            values[key] = entry.get(value_key)
        k_req: dict[str, int] = {}
        for entry in _list(d.get("k"), "k"):
            if not isinstance(entry, dict) or "node" not in entry:
                raise RbdImportError("Each entry of the diagram's “k” needs a “node” and a “k”.")
            k = _whole(entry.get("k"))
            if k is None or k < 1:
                raise RbdImportError("Each k must be a whole number, 1 or more.")
            k_req[_key(entry["node"])] = k
        if _list(d.get("capacity"), "capacity"):
            self.note("Node capacities (for RePyability's flow analysis) aren't imported: Reliafy's blocks "
                      "work or fail.")

        has_pred = {t for _, t in edges}
        has_succ = {s for s, _ in edges}
        in_key = self._end(d.get("input_node"), [n for n in raw_names if n not in has_pred], "input", raw_names)
        out_key = self._end(d.get("output_node"), [n for n in raw_names if n not in has_succ], "output", raw_names)
        for key, which in ((in_key, "input"), (out_key, "output")):
            if values.get(key) not in (None, {"kind": "perfect_reliability"}):
                self.note(f"The {which} node's own model isn't imported: Reliafy's input and output are perfect.")

        if depth == 0:
            entry_id = self.add("input", "input", {"label": "Input"})
            exit_id = self.add("output", "output", {"label": "Output"})
        else:
            entry_id = self.add(f"{prefix}in", "knode", {"label": f"{label} (in)", "n": 1})
            exit_id = self.add(f"{prefix}out", "knode", {"label": f"{label} (out)", "n": 1})
        ends: dict[str, tuple[str, str]] = {in_key: (entry_id, entry_id), out_key: (exit_id, exit_id)}

        # Every other node, in the order the file first names it.
        repeats: dict[str, str] = {}
        for key, raw in raw_names.items():
            if key in (in_key, out_key):
                continue
            import_guard.check()
            name_label = _label(raw)
            nid = f"{prefix}{name_label}"
            value = values.get(key)
            if not repairable and isinstance(value, dict) and value.get("kind") == "repeat_of":
                try:
                    repeats[key] = _key(value.get("node"))
                except RbdImportError:
                    repeats[key] = ""
                continue
            if key not in values:
                self.note(f"“{name_label}” has no model in the file: it was imported as a junction.")
                n = self.add(nid, "knode", {"label": name_label, "n": 1})
                ends[key] = (n, n)
                continue
            ends[key] = self.block(value, nid, name_label, depth, k_req.get(key), repairable)

        for key, target in repeats.items():
            name_label = _label(raw_names[key])
            nid = f"{prefix}{name_label}"
            original = ends.get(target)
            node = self.nodes.get(original[1]) if original else None
            if (node is not None and original[0] == original[1] and node["type"] == "component"
                    and node["data"].get("model") and not node["data"].get("repeat_of")):
                n = self.add(nid, "component", {"label": name_label, "repeat_of": node["id"]})
            else:
                n = self.without_model(nid, name_label, "it repeats a node Reliafy can't draw as a repeated block")
            ends[key] = (n, n)

        # k on any node but a vote node: a vote node in front of it.
        for key, k in k_req.items():
            if key not in ends or key == in_key or k < 2:
                continue
            entry, exit_ = ends[key]
            if entry in self.votes:
                continue
            vote = self.add(f"{entry} vote", "knode",
                            {"label": f"{k} of the inputs to {_label(raw_names[key])}", "n": k})
            self.connect(vote, entry)
            ends[key] = (vote, exit_)

        for s, t in edges:
            self.connect(ends[s][1], ends[t][0])
        self.ccf_groups(d.get("ccf_groups"), ends)
        if repairable and depth == 0:
            self.repairable_settings(d)
        return entry_id, exit_id

    def _end(self, given, candidates: list, which: str, raw_names: dict) -> str:
        if given is not None:
            key = _key(given)
            if key not in raw_names:
                raise RbdImportError(f"The diagram's {which}_node isn't on any edge.")
            return key
        if len(candidates) == 1:
            return candidates[0]
        raise RbdImportError(
            f"The diagram has no {which}_node and {'no' if not candidates else 'several'} "
            f"{'source' if which == 'input' else 'sink'} nodes — set {which}_node.")

    # -- blocks -----------------------------------------------------------
    def block(self, value, nid: str, label: str, depth: int, k: Optional[int],
              repairable: bool) -> tuple[str, str]:
        if repairable:
            return self.repairable_block(value, nid, label, k)
        kind = value.get("kind") if isinstance(value, dict) else None
        if kind == "perfect_reliability":
            n = self.add(nid, "knode", {"label": label, "n": k or 1})
            self.votes.add(n)
            return n, n
        if kind == "perfect_unreliability":
            self.note(f"“{label}” has failed for good (perfect unreliability): it was imported pinned failed.")
            n = self.add(nid, "component", {"label": label, "state": "failed"})
            return n, n
        if kind in ("surpyval", "parametric"):
            model, why = self.life(value, label)
            n = self.add(nid, "component", {"label": label, "model": model}) if model else \
                self.without_model(nid, label, why)
            return n, n
        if kind == "repeated_node":
            model, why = self.life(value.get("model"), label)
            repeats = _whole(value.get("repeats"))
            rkind = value.get("repeated_kind")
            if model and repeats and repeats >= 1 and rkind in ("series", "parallel"):
                data = {"label": label, "model": model}
                n = self.add(nid, "component", data) if repeats == 1 else \
                    self.add(nid, rkind, {**data, "n": repeats})
            else:
                n = self.without_model(nid, label, why or "its group of identical units can't be read")
            return n, n
        if kind == "repeated_standby":
            model, why = self.life(value.get("model"), label)
            repeats = _whole(value.get("repeats"))
            switch = _finite(value.get("switching_probability", 1.0))
            if model and repeats and repeats >= 1 and switch is not None and 0 <= switch <= 1:
                if repeats == 1:
                    n = self.add(nid, "component", {"label": label, "model": model})
                else:
                    n = self.add(nid, "standby", {"label": label, "model": model, "spares": repeats - 1,
                                                  "dormancy": 0, "cold": True, "startProb": switch})
            else:
                n = self.without_model(nid, label, why or "its cold-standby group can't be read")
            return n, n
        if kind == "standby":
            n = self.standby(value, nid, label)
            return n, n
        if kind == "rbd":
            inner = value.get("rbd")
            if isinstance(inner, dict) and inner.get("type") == "NonRepairableRBD":
                return self.diagram(inner, f"{nid}/", depth + 1, label)
            n = self.without_model(nid, label, "it is a nested repairable diagram")
            return n, n
        n = self.without_model(nid, label, f"its model is {_KIND_TEXT.get(kind, 'a kind Reliafy can’t read')}")
        return n, n

    def standby(self, value: dict, nid: str, label: str, repair: Optional[dict] = None) -> str:
        units = value.get("reliabilities")
        k = _whole(value.get("k", 1))
        dormancy = _finite(value.get("dormancy_factor", 0.0))
        switch = _finite(value.get("switching_probability", 1.0))
        if not isinstance(units, list) or not 2 <= len(units) <= 1001 or k != 1:
            return self.without_model(nid, label, "its standby group runs more than one unit at a time, or has "
                                                  "no spare" if k != 1 else "its standby group can't be read")
        models = [self.life(u, label) for u in units]
        bad = next((why for m, why in models if m is None), None)
        if bad:
            return self.without_model(nid, label, bad)
        duty, spare = models[0][0], models[1][0]
        if any(m != spare for m, _ in models[2:]):
            return self.without_model(nid, label, "its spares aren't identical, which Reliafy's standby block needs")
        if dormancy is None or not 0 <= dormancy <= 1 or switch is None or not 0 <= switch <= 1:
            return self.without_model(nid, label, "its dormancy factor or switching probability isn't a probability")
        if dormancy > 0 and switch < 1:
            self.note(f"“{label}”: its switching probability ({switch:g}) applies only to cold standby in Reliafy, "
                      "so this warm or hot standby switches perfectly.")
        data: dict[str, Any] = {"label": label, "model": duty, "spares": len(units) - 1,
                                "dormancy": dormancy, "cold": dormancy == 0}
        if spare != duty:
            data["standbyModel"] = spare
        if dormancy == 0 and switch < 1:
            data["startProb"] = switch
        return self.add(nid, "standby", data)

    # -- repairable blocks ------------------------------------------------
    def repairable_block(self, value, nid: str, label: str, k: Optional[int]) -> tuple[str, str]:
        kind = value.get("kind") if isinstance(value, dict) else None
        if kind == "perfect_reliability" or (kind == "non_repairable" and self._always_up(value)):
            n = self.add(nid, "knode", {"label": label, "n": k or 1})
            self.votes.add(n)
            return n, n
        if kind == "non_repairable":
            spec = {"reliability": value.get("reliability"), "repairability": value.get("time_to_replace")}
            n = self.component(spec, nid, label)
            return n, n
        if kind == "component_spec":
            n = self.component(value, nid, label)
            return n, n
        if kind == "rbd":
            n = self.one_at_a_time(value.get("rbd"), nid, label)
            return n, n
        n = self.without_model(nid, label, (f"in a repairable diagram it needs a life and a repair model, and "
                                            f"its model is {_KIND_TEXT.get(kind, 'a kind Reliafy can’t read')}"))
        return n, n

    def _always_up(self, value: dict) -> bool:
        rel = value.get("reliability") or {}
        m = rel.get("model") if isinstance(rel, dict) else None
        if not isinstance(m, dict) or m.get("distribution") != "Weibull":
            return False
        params = m.get("params") or []
        return (len(params) == 2 and (_finite(params[0]) or 0) >= _FIXED_RATE_LIFE and _finite(params[1]) == 1.0)

    def component(self, spec: dict, nid: str, label: str) -> str:
        life, why = self.life(spec.get("reliability"), label)
        if life is None:
            return self.without_model(nid, label, why)
        data: dict[str, Any] = {"label": label, "model": life}
        repair = spec.get("repairability")
        if repair == "instant":
            data["instant_repair"] = True
        else:
            model, why = self.life(repair, label, "repair")
            if model is None:
                fixed = self._fixed_time(repair)
                why = ("its repair takes a fixed time, which Reliafy's repair models can't express"
                       if fixed is not None else why)
                self.note(f"“{label}”: {why}; set its repair model before analysing.")
            else:
                data["repair"] = model
        costs = {}
        for key, app_key in (("repair_cost", "repair"), ("replace_cost", "replace")):
            if key in spec:
                cost = self._cost(spec[key], label, f"{app_key} cost")
                if cost is not None:
                    costs[app_key] = cost
        for key, app_key in (("downtime_cost", "downtime"), ("acquisition_cost", "acquisition")):
            x = _finite(spec.get(key))
            if x is not None:
                costs[app_key] = x
            elif key in spec:
                self._cost(spec[key], label, key.replace("_", " "))
        if costs:
            data["costs"] = costs
        if _finite(spec.get("priority")) is not None:
            data["crew_priority"] = _finite(spec["priority"])
        group = spec.get("group")
        if group is not None:
            data["maintenance_group"] = _label(group)
        for key in ("preventive", "inspection"):
            if isinstance(spec.get(key), dict):
                schedule = self.schedule(spec[key], label, key)
                if schedule:
                    data[key] = schedule
        if spec.get("repair") is not None:
            self.note(f"“{label}”: its imperfect repair (restoration factor) isn't imported — Reliafy repairs to "
                      "as good as new.")
        if spec.get("replace_after") is not None:
            self.note(f"“{label}”: replacement after a number of repairs isn't imported.")
        standby = spec.get("standby")
        if isinstance(standby, dict):
            return self.standby_group(standby, data, nid, label)
        return self.add(nid, "component", data)

    def schedule(self, spec: dict, label: str, key: str) -> Optional[dict]:
        out: dict[str, Any] = {}
        interval = _finite(spec.get("interval"))
        if interval is None:
            self.note(f"“{label}”: its {key} schedule has no interval, so it was left out.")
            return None
        out["interval"] = interval
        if key == "preventive":
            out["policy"] = spec.get("policy") if spec.get("policy") in ("age", "block", "condition") else "age"
        for field in ("threshold", "opportunity", "offset", "coverage", "full_test"):
            x = _finite(spec.get(field))
            if x is not None:
                out[field] = x
        duration = spec.get("duration", "instant")
        if duration != "instant":
            fixed = self._fixed_time(duration)
            if fixed is not None:
                out["duration"] = fixed
            else:
                model, why = self.life(duration, label, f"{key} duration")
                if model is None:
                    self.note(f"“{label}”: {why}; the {key} duration was left out (instant).")
                else:
                    out["duration"] = {k: v for k, v in model.items() if k != "source"}
        for field, what in (("cost", f"{key} cost"), ("inspection_cost", "inspection cost")):
            if field in spec:
                cost = self._cost(spec[field], label, what)
                if cost is not None:
                    out[field] = cost
        return out

    def standby_group(self, standby: dict, data: dict, nid: str, label: str) -> str:
        units = _whole(standby.get("units"))
        k = _whole(standby.get("k", 1))
        dormancy = _finite(standby.get("dormancy_factor", 0.0))
        switch = _finite(standby.get("switching_probability", 1.0))
        if units is None or units < 2 or k != 1 or dormancy is None or not 0 <= dormancy <= 1 \
                or switch is None or not 0 <= switch <= 1:
            return self.without_model(nid, label, "its standby group runs more than one unit at a time, or can't "
                                                  "be read")
        data.update({"spares": units - 1, "dormancy": dormancy, "cold": dormancy == 0})
        if dormancy == 0 and switch < 1:
            data["startProb"] = switch
        return self.add(nid, "standby", data)

    def one_at_a_time(self, inner, nid: str, label: str) -> str:
        """A one-block repairable diagram with one crew: Reliafy's standby
        group repaired one unit at a time."""
        if isinstance(inner, dict) and inner.get("type") == "RepairableRBD" and inner.get("repair_crews") == 1:
            comps = inner.get("components")
            if isinstance(comps, list) and len(comps) == 1 and isinstance(comps[0], dict):
                spec = comps[0].get("component")
                if isinstance(spec, dict) and spec.get("kind") == "component_spec" and isinstance(spec.get("standby"), dict):
                    created = self.component(spec, nid, label)
                    if self.nodes[created]["type"] == "standby":
                        self.nodes[created]["data"]["repair_one_at_a_time"] = True
                    return created
        return self.without_model(nid, label, "it is a nested repairable diagram")

    def repairable_settings(self, d: dict) -> None:
        rate = _finite(d.get("downtime_cost_rate"))
        if rate:
            self.graph_extra["costs"] = {"downtime_rate": rate}
        crews = _whole(d.get("repair_crews"))
        if crews is not None and crews >= 1:
            self.graph_extra["repair_crews"] = {"crews": crews}
        groups = {}
        for entry in _list(d.get("maintenance_groups"), "maintenance_groups"):
            if not isinstance(entry, dict) or entry.get("group") is None:
                continue
            options = {}
            if _finite(entry.get("setup_cost")):
                options["setup_cost"] = _finite(entry["setup_cost"])
            if entry.get("system_down") is True:
                options["system_down"] = True
            groups[_label(entry["group"])] = options
        if groups:
            self.graph_extra["maintenance_groups"] = groups

    def ccf_groups(self, groups, ends: dict) -> None:
        for entry in _list(groups, "ccf_groups"):
            if not isinstance(entry, dict) or not isinstance(entry.get("model"), dict):
                continue
            model = entry["model"]
            members = []
            for m in entry.get("members") or []:
                try:
                    end = ends.get(_key(m))
                except RbdImportError:
                    end = None
                node = self.nodes.get(end[1]) if end else None
                if node is not None and node["type"] == "component":
                    members.append(node["id"])
            beta = _finite(model.get("beta"))
            # RePyability's default basis is the probability (a file leaves it out).
            basis = model.get("basis", "probability")
            if (model.get("kind") != "beta_factor" or basis not in ("probability", "rate")
                    or beta is None or not 0 < beta < 1):
                self.note("A common-cause group that isn't a beta-factor model (MGL, say) isn't imported.")
                continue
            if len(set(members)) < 2:
                self.note("A common-cause group whose members aren't plain blocks isn't imported.")
                continue
            group = {"id": f"ccf-{len(self.ccf) + 1}", "members": list(dict.fromkeys(members)), "beta": beta}
            # Reliafy's default (#210) is the rate for lifetime analysis and the
            # probability in a repairable diagram: the basis is kept only
            # where it differs, so a file Reliafy wrote reads back unchanged.
            if basis != ("probability" if self.repairable else "rate"):
                group["basis"] = basis
            if basis == "probability" and not self.repairable:
                self.note("A common-cause group splits its members' failure probability (RePyability's default "
                          "basis), kept as it is: a rare-event model, so over a lifetime it overstates the "
                          "group's reliability and the MTTF isn't given. Set its basis to rate for lifetime "
                          "figures.")
            self.ccf.append(group)
