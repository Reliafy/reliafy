"""RBD exchange in RePyability's JSON format (#174).

RePyability serialises a diagram with ``RBD.to_dict()`` / ``to_json()`` and
rebuilds it with ``rbd_from_dict`` / ``rbd_from_json``
(:mod:`repyability.rbd.serialisation`). :func:`to_document` turns a builder
graph into exactly that document, so a library user can load a Reliafy
diagram with ``rbd_from_json`` and get the RBD the app analyses:

* a **non-repairable** diagram is a ``NonRepairableRBD``, block by block as
  in "Download as Python" (:mod:`.rbd_export`): series/parallel count blocks
  and hot standby as ``RepeatedNode`` (or a small nested diagram when a hot
  spare has its own model), cold and warm standby as ``StandbyModel``, k-of-n
  vote nodes as a perfectly reliable node with ``k``, repeated blocks as
  RePyability repeated nodes, beta-factor common-cause groups (on the rate
  basis unless a group says otherwise, #210), and sub-systems
  as nested diagrams;
* a **repairable** diagram is the ``RepairableRBD`` the availability analysis
  builds (:func:`.rbd_analysis._build_repairable_rbd`), costs, maintenance,
  proof tests, standby groups, repair crews and maintenance groups included,
  and its common-cause groups wherever the analysis takes them in (#226).
  Where RePyability refuses them (a member whose life isn't exponential,
  say) the analysis leaves them out of every figure, and so does the
  document's RePyability part, so it gives the app's numbers; the groups
  stay in the diagram (the ``"reliafy"`` part's graph), and
  ``"reliafy".common_cause`` says why they're not in the RePyability part.

What RePyability's document has no place for (block labels and positions, the
time unit, links to saved models and sub-system diagrams, placeholder flags,
blocks pinned working or failed, a safety function's settings, RCM sources…)
rides along in a top-level ``"reliafy"`` object, which RePyability ignores.
Importing the file back (:mod:`.rbd_import.repyability`) restores the diagram
from it when the RePyability part is still what Reliafy wrote, so the round
trip loses nothing; a file edited in code is rebuilt from the RePyability
part.

Blocks whose model lives only in the user's workspace — a fitted
proportional-hazards, non-parametric or load-sharing (AFT) model — can't be
written as a plain document: the export refuses them by name (Download as
Python writes a placeholder for them instead). The exception (#372): a
repairable block on a covariate schedule goes in as RePyability's own
component — the fitted regression (surpyval's ``to_dict``) and its
``"covariates"`` schedule — so the document simulates what the app does.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Optional

from backend.services import import_guard, rbd_capacity, rbd_export, rbd_repeats
from backend.services import rbd_analysis as ra

#: The top-level key of Reliafy's own part of the document.
EXTENSION_KEY = "reliafy"
FORMAT = "reliafy-rbd"
FORMAT_VERSION = 1

#: What RePyability's document doesn't hold, kept in the ``"reliafy"`` part
#: (the export notes: the API reference and the MCP tool list them).
EXPORT_NOTES = (
    "Block labels and positions, the diagram's time unit, placeholder flags and RCM sources are kept in the "
    "file's \"reliafy\" part, which RePyability ignores.",
    "Links to saved models and sub-system diagrams are kept there too; RePyability gets each block's own "
    "parameters and each sub-system as a nested diagram.",
    "Blocks pinned working or failed keep their non-repairable model; the pins are a what-if for the analysis — pass "
    "them to RePyability as working_nodes / broken_nodes.",
    "A safety function's settings and the ownership horizon of a repairable diagram are Reliafy's only.",
)

_UNSUPPORTED = {
    "regression": "a fitted proportional-hazards model",
    "nonparametric": "a non-parametric model fitted to a dataset",
    "joint": ("a condition-based (joint) model's unit, which lives only in Reliafy (it is one unit given its "
              "readings, and RePyability's file can't carry the readings)"),
}


class ExportError(ValueError):
    """A diagram that can't be written as RePyability JSON (user-facing)."""


def filename(name: str) -> str:
    """The download file name for a diagram called ``name``."""
    return f"{rbd_export.slugify(name)}.json"


def _repyability_version() -> str:
    import repyability

    return repyability.__version__


def _serialise(model) -> dict:
    from repyability.rbd.serialisation import serialise_model

    return serialise_model(model)


class _Missing(Exception):
    """A block that can't be written (``str`` is the reason, per block)."""


class _Exporter:
    """Collects the blocks that can't be exported and the sub-system
    diagrams that were nested."""

    def __init__(self, resolve_model, resolve_subsystem, unit=None):
        self.resolve_model = resolve_model
        self.unit = unit  # the diagram's: a block fitted in another unit of its kind is converted to it
        self.resolve_subsystem = resolve_subsystem
        self.problems: list[str] = []
        self.subsystems: dict[str, dict] = {}
        self.common_cause: Optional[dict] = None

    # -- non-repairable models ------------------------------------------------------
    def spec(self, model: Optional[dict]) -> Optional[dict]:
        """A model spec with a saved model's parameters filled in (the
        block's own snapshot wins, as in the analysis), converted to the
        diagram's unit when it was fitted in another of the same kind (its
        parameters, as the analysis converts them)."""
        from backend.services import model_units

        spec = rbd_export._effective_spec(model, self.resolve_model)
        return model_units.convert_model(spec, self.unit)[0]

    def dist(self, model: Optional[dict], label: str):
        """A frozen SurPyval distribution for a block's model, or
        :class:`_Missing`. A saved Bayesian update is its posterior
        predictive (refitted from its history and prior), as the analysis
        takes it, which RePyability's JSON holds whole."""
        from backend.services import model_units

        recipe = rbd_export.bayes_recipe(model, self.resolve_model)
        if recipe is not None and model_units.convertible_kind(model) and \
                model_units.conversion(model, self.unit) is not None:
            raise _Missing(f"“{label}” uses a Bayesian update fitted in another unit, which RePyability's JSON "
                           "can't hold converted (Download as Python writes it)")
        if recipe is not None:
            from repyability import PosteriorPredictive

            try:
                return PosteriorPredictive(rbd_export.bayes_fit(recipe))
            except Exception:  # noqa: BLE001 - the block's own parameters below, as the analysis
                pass
        spec = self.spec(model)
        if not spec:
            raise _Missing(f"“{label}” has no non-repairable model")
        kind = spec.get("kind")
        if kind in _UNSUPPORTED:
            raise _Missing(f"“{label}” uses {_UNSUPPORTED[kind]}")
        if spec.get("_unresolved"):
            raise _Missing(f"“{label}” uses a saved model that couldn't be read")
        if model_units.needs_wrap(spec):
            raise _Missing(f"“{label}” uses a model fitted in another unit with no parameter rule for the change, "
                           "which RePyability's JSON can't hold converted (Download as Python writes it)")
        try:
            return ra._build_distribution(spec, label, None, None)
        except ra.AnalysisError as exc:
            raise _Missing(str(exc)) from None

    def model(self, model: Optional[dict], label: str) -> dict:
        return _serialise(self.dist(model, label))

    # -- non-repairable ---------------------------------------------------
    def block(self, node: dict, visited: frozenset) -> tuple[dict, Optional[int]]:
        """``(serialised model, k)`` for one block of a non-repairable diagram."""
        from repyability.rbd.repeated_node import RepeatedNode
        ntype = node.get("type")
        data = node.get("data") or {}
        label = data.get("label") or str(node.get("id"))
        if ntype == "knode":
            return {"kind": "perfect_reliability"}, max(int(data.get("n") or 1), 1)
        if ntype == "component":
            return self.model(data.get("model"), label), None
        if ntype in ("series", "parallel"):
            count = max(int(data.get("n") or 1), 1)
            unit = self.dist(data.get("model"), label)
            return _serialise(RepeatedNode(unit, count, ntype)), None
        if ntype == "standby":
            from backend.services import rbd_standby

            try:
                units = rbd_standby.build_units(data, label, lambda spec, where: self.dist(spec, where))
                dormancy = ra._standby_dormancy(data, label)
                k = rbd_standby.operating(data, label)
                start = rbd_standby.start_probability(data)
                if not (k == 1 and dormancy >= 1.0 and start == 1.0):
                    # Cold, warm, or hot with spares that may fail to start, k units
                    # running (#84), as the analysis builds it. One RePyability only
                    # simulates goes in as it is when the block is set to be simulated
                    # (the library simulates it there too), else it's refused.
                    model = rbd_standby.standby_model(data, label, units, dormancy, start)
                    if model.is_simulated and not data.get("simulate"):
                        rbd_standby.nonrepairable_model(data, label, units, dormancy, start)
                    return _serialise(model), None
            except (ra.AnalysisError, TypeError, ValueError) as exc:
                raise _Missing(str(exc)) from None
            # Hot standby: active parallel redundancy (as Download as Python).
            if all(u is units[0] for u in units):
                return _serialise(RepeatedNode(units[0], len(units), "parallel")), None
            members = [("duty", units[0])] + [(f"spare{i + 1}", m) for i, m in enumerate(units[1:])]
            return {"kind": "rbd", "rbd": _rbd_dict(
                "NonRepairableRBD",
                edges=[e for key, _ in members for e in (["in", key], [key, "out"])],
                input_node="in", output_node="out",
                reliabilities=[{"node": key, "model": _serialise(m)} for key, m in members],
            )}, None
        if ntype == "loadshare":
            raise _Missing(f"“{label}” is a load-sharing group on a fitted load-life (AFT) model")
        if ntype == "subsystem":
            return self.subsystem(data, label, visited), None
        raise _Missing(f"“{label}” is an unsupported block type ({ntype})")

    def subsystem(self, data: dict, label: str, visited: frozenset) -> dict:
        ref = data.get("rbd") or {}
        sub_id = ref.get("id")
        name = ref.get("name") or "sub-system"
        if not sub_id:
            raise _Missing(f"“{label}” is a sub-system with no diagram selected")
        if sub_id in visited:
            raise _Missing(f"“{label}”: sub-system “{name}” refers to itself")
        graph = None
        if self.resolve_subsystem is not None:
            try:
                graph = self.resolve_subsystem(sub_id)
            except Exception:  # noqa: BLE001 - treated as unresolvable
                graph = None
        if not graph:
            raise _Missing(f"“{label}”: sub-system “{name}” couldn't be read")
        self.subsystems.setdefault(sub_id, {"name": name, "graph": graph})
        return {"kind": "rbd", "rbd": self.nonrepairable(graph, visited | {sub_id})}

    def nonrepairable(self, graph: dict, visited: frozenset = frozenset()) -> dict:
        ra._check_limits(graph)
        nodes = graph.get("nodes") or []
        node_ids = {n.get("id") for n in nodes}
        edges = [[e["source"], e["target"]] for e in graph.get("edges") or []
                 if e.get("source") and e.get("target")]
        repeats, problems = rbd_repeats.find_repeats(nodes)
        if problems:
            raise ExportError(next(iter(problems.values())))
        reliabilities: list[dict] = []
        k: dict[Any, int] = {}
        for node in nodes:
            import_guard.check()  # an import compares a file with what Reliafy would write
            nid = node.get("id")
            if node.get("type") in ("input", "output"):
                continue
            if nid in repeats:
                reliabilities.append({"node": nid, "model": {"kind": "repeat_of", "node": repeats[nid]}})
                continue
            state = (node.get("data") or {}).get("state")
            try:
                model, k_required = self.block(node, visited)
            except _Missing as exc:
                if state not in ("working", "failed"):
                    self.problems.append(str(exc))
                    continue
                # A pinned block needs no model in Reliafy: it stands in as
                # what its pin makes it.
                kind = "perfect_reliability" if state == "working" else "perfect_unreliability"
                model, k_required = {"kind": kind}, None
            reliabilities.append({"node": nid, "model": model})
            if k_required is not None:
                k[nid] = k_required
        present = {r["node"] for r in reliabilities if r["node"] not in repeats}
        ccf = []
        for group in graph.get("ccf_groups") or []:
            members = list(dict.fromkeys(m for m in (group.get("members") or []) if m in present))
            try:
                beta = float(group.get("beta"))
            except (TypeError, ValueError):
                continue
            if len(members) >= 2 and 0.0 < beta < 1.0:
                # As the analysis builds it (#210): the rate basis unless the
                # group says probability, written as rbd_to_dict writes it
                # (the basis only when it isn't RePyability's default).
                try:
                    basis = ra.ccf_basis(group)
                except ra.AnalysisError as exc:
                    raise ExportError(str(exc)) from None
                from backend.services import rbd_ccf_models

                try:
                    # The beta factor, or the multiple Greek letter model (#84).
                    model = rbd_ccf_models.document_model(group, basis)
                except (ra.AnalysisError, TypeError, ValueError) as exc:
                    raise ExportError(str(exc)) from None
                ccf.append({"members": members, "model": model})
        return _rbd_dict(
            "NonRepairableRBD",
            edges=edges,
            k=[{"node": n, "k": v} for n, v in k.items()] or None,
            input_node="input" if "input" in node_ids else None,
            output_node="output" if "output" in node_ids else None,
            reliabilities=reliabilities,
            ccf_groups=ccf or None,
        )

    # -- repairable -------------------------------------------------------
    def repairable(self, graph: dict) -> dict:
        from repyability.rbd.serialisation import rbd_to_dict

        nodes = []
        scheduled: set = set()  # saved covariate models on a schedule (#372): their fits go in as they are
        for node in graph.get("nodes") or []:
            data = dict(node.get("data") or {})
            label = data.get("label") or str(node.get("id"))
            model = data.get("model") or {}
            if (node.get("type") == "component" and model.get("kind") == "regression"
                    and data.get("covariate_schedules")):
                if self.resolve_model is None or not (model.get("modelId") or model.get("model_id")):
                    self.problems.append(f"“{label}” uses a fitted covariate model that couldn't be read")
                scheduled.add(model.get("modelId") or model.get("model_id"))
                if data.get("repair"):
                    data["repair"] = self.spec(data["repair"])
                nodes.append({**node, "data": data})
                continue
            if node.get("type") in ("component", "standby") and data.get("model"):
                spec = self.spec(data["model"])
                if spec and spec.get("kind") in _UNSUPPORTED:
                    self.problems.append(f"“{label}” uses {_UNSUPPORTED[spec['kind']]}")
                data["model"] = spec
            if data.get("repair"):
                data["repair"] = self.spec(data["repair"])
            nodes.append({**node, "data": data})
        if self.problems:
            raise ExportError(self.message())
        spec_graph = {**graph, "nodes": nodes}
        try:
            # As the analysis builds it: the common-cause groups wherever it
            # takes them in (#226).
            resolve = (lambda mid: self.resolve_model(mid) if mid in scheduled else None) if scheduled else None
            rbd, *_ = ra._build_repairable_rbd(spec_graph, resolve_model=resolve,
                                               capacity=rbd_capacity.graph_capacities(graph))
        except ra.AnalysisError as exc:
            raise ExportError(f"This diagram can't be written as RePyability JSON yet: {exc}") from None
        self.common_cause = ra.common_cause_status(rbd)
        try:
            return rbd_to_dict(rbd)
        except NotImplementedError as exc:
            raise ExportError(f"RePyability can't write this diagram: {exc}") from None

    def message(self) -> str:
        shown = "; ".join(self.problems[:8])
        more = f" (and {len(self.problems) - 8} more)" if len(self.problems) > 8 else ""
        return (f"RePyability's JSON holds each block's own non-repairable model, so these blocks can't go in it: "
                f"{shown}{more}. Give them a parametric non-repairable model, or use Download as Python instead.")


def _rbd_dict(rbd_type: str, *, edges, input_node=None, output_node=None, k=None,
              reliabilities=(), ccf_groups=None) -> dict:
    """A non-repairable diagram in ``rbd_to_dict``'s shape (and key order)."""
    return {
        "repyability_version": _repyability_version(),
        "type": rbd_type,
        "edges": [list(e) for e in edges],
        "k": k,
        "capacity": None,
        "input_node": input_node,
        "output_node": output_node,
        "on_infeasible_rbd": "raise",
        "reliabilities": list(reliabilities),
        "ccf_groups": ccf_groups,
    }


def core(graph: dict, resolve_model: Optional[Callable] = None,
         resolve_subsystem: Optional[Callable[[str], Optional[dict]]] = None) -> tuple[dict, dict]:
    """``(RePyability document, {sub-system id: {name, graph}})`` for a
    graph. Raises :class:`ExportError` naming the blocks that can't go in."""
    doc, subsystems, _ = _core(graph, resolve_model, resolve_subsystem)
    return doc, subsystems


def _core(graph: dict, resolve_model, resolve_subsystem) -> tuple[dict, dict, "_Exporter"]:
    ex = _Exporter(resolve_model, resolve_subsystem, (graph or {}).get("unit"))
    from backend.services import rbd_network

    try:
        if graph.get("repairable"):
            doc = ex.repairable(graph)
        elif rbd_network.is_network(graph):  # #160: a network's own document
            doc = rbd_network.json_core(ex, graph)
        else:
            doc = ex.nonrepairable(graph)
            # Block capacities (#122), as rbd_to_dict writes them.
            doc["capacity"] = rbd_capacity.document_capacity(graph)
    except ExportError:
        raise
    except ra.AnalysisError as exc:
        raise ExportError(str(exc)) from None
    except rbd_capacity.CapacityError as exc:
        raise ExportError(str(exc)) from None
    except (TypeError, ValueError, KeyError) as exc:
        raise ExportError(f"This diagram has a block setting RePyability can't read ({exc}).") from None
    if ex.problems:
        raise ExportError(ex.message())
    return doc, ex.subsystems, ex


def to_document(graph: dict, name: str, resolve_model: Optional[Callable] = None,
                resolve_subsystem: Optional[Callable[[str], Optional[dict]]] = None) -> dict:
    """The diagram as a RePyability document plus Reliafy's own part."""
    doc, subsystems, ex = _core(graph or {}, resolve_model, resolve_subsystem)
    doc[EXTENSION_KEY] = {
        "format": FORMAT,
        "version": FORMAT_VERSION,
        "name": name or "",
        "graph": graph or {},
        "subsystems": subsystems,
    }
    if ex.common_cause is not None:
        # Whether the RePyability part has the diagram's common-cause groups
        # (#226): as the analysis does, and why not.
        doc[EXTENSION_KEY]["common_cause"] = {k: ex.common_cause[k] for k in ("groups", "included", "reason")}
    return doc


def to_json(doc: dict) -> str:
    """The document as JSON text (strict: no NaN or Infinity)."""
    try:
        return json.dumps(doc, indent=2, allow_nan=False, ensure_ascii=False) + "\n"
    except ValueError:
        raise ExportError("This diagram holds a value that isn't a finite number, which JSON can't store.") from None


def comparable(doc: dict) -> Any:
    """A document as plain JSON values, without Reliafy's part or the
    version stamps — what two exports of the same diagram share."""

    def strip(value):
        if isinstance(value, dict):
            return {k: strip(v) for k, v in value.items() if k not in ("repyability_version", EXTENSION_KEY)}
        if isinstance(value, (list, tuple)):
            return [strip(v) for v in value]
        return value

    return strip(json.loads(json.dumps(doc, allow_nan=True)))
