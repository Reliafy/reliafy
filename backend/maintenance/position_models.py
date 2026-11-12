"""Life models on functional locations: the Explorer's Modelling tab.

A position (a functional location, or a position in a product's design) can
carry the life models that describe it: a Weibull fitted to its own failure
history, the model its position class pools, or any saved model (non-repairable,
repairable, degradation, accelerated life, condition and life) assigned by hand.
A link names the model; the model itself is never copied, so a refit or rename
in Models shows here, and one model can sit on many positions.

A link may say which of the position's failure modes it is for (none: every
failure of the position). The RCM uses the links: a failure mode's "Based on"
picker offers the position's models first, and the interval calculators start
from them when the decision has no evidence of its own.

Events (new types only; older logs replay unchanged):

* ``position.model_linked {id, position_id, model_type, model_id, role,
  failure_mode_ids, name, note, source, on}``: a model attached to a position.
  ``model_type`` is the store it lives in (:data:`MODEL_TYPES`); ``role`` how it
  came (:data:`ROLES`); ``name`` the model's name when linked (for the history
  and for reads that can't open the model); ``source`` what a fit was made from
  (scope, failures, suspensions, class) or the design position a built one came
  from.
* ``position.model_unlinked {id, on}``: taken off again (the model stays in
  Models).
* ``position.model_in_use_set {position_id, link_id}`` (Nov 2026): which of a position's
  rows is the model in use (one at a time). Without one, the in-use row is its own life
  model, else its RBD, else its prediction (:meth:`PositionModelOps.in_use_link`).
* ``position.model_relinked {id, model_id, name, note}`` (Nov 2026): a link pointed at
  another saved model of the same kind (or the same one), with the name and note it
  carries from then on. The link itself and what it is for stay as they were.

An RBD is a row too (``model_type`` and ``role`` ``rbd``, Nov 2026: "every position can
either have a life model, an RBD, or a prediction"): a saved diagram, built from the
positions inside (each block the child's model in use, else a flagged placeholder) or
linked as it is. The link points at the diagram; nothing is copied.

A built item inherits its product design's links the way it inherits the RCM: at
build time each copied position gets the design position's links (role
``design``), its failure modes matched by their words. A change to the design
afterwards doesn't reach the built item by itself.

The graph side (the events, the reads of what's linked) is :class:`PositionModelOps`,
a mixin of ``Maintenance``. The model store side (reading the models, fitting a
new one from the position's history, what uses a model) is the module functions
below, called by the REST routes and the MCP tool with the reader's database
handle and owners.
"""

from __future__ import annotations

import io
import re

from backend.maintenance.store import GraphStore

#: Where a linked model lives: the saved non-repairable models (also condition and
#: life, regression and competing risks), repairable, degradation and accelerated life.
#: covariate_record: an NSWC-11 covariate model with covariates left open at the position
#: (covariate_positions.py).
MODEL_TYPES = ("model", "recurrent_model", "degradation_model", "alt_model", "rbd", "covariate_record")
#: How a model came to the position: chosen from the library, fitted from history,
#: the position class's model, copied from the product design it was built from, or a
#: Bayesian update of a baseline with its history (backend/services/bayes_life.py).
ROLES = ("assigned", "fitted", "class", "design", "bayesian", "prediction", "rbd", "library")
MAX_LINKS_EACH = 50  # models on one position
FIT_SCOPES = ("auto", "position", "class")
FIT_DISTRIBUTIONS = ("weibull", "best", "lognormal", "exponential", "gamma")

#: The evidence type an RCM decision uses for each kind of model (rcm_decisions.CHECKED_TYPES).
EVIDENCE_TYPE = {"model": "model", "degradation_model": "degradation_model"}

# ---- projectors ---------------------------------------------------------------------------

_KEPT = ("position_id", "model_type", "model_id", "role", "name", "note", "source")


def _model_linked(s: GraphStore, org: str, p: dict) -> None:
    s.put_node(org, p["id"], "ModelLink", {k: p.get(k) for k in _KEPT}
               | {"failure_mode_ids": list(p.get("failure_mode_ids") or []), "linked_on": p.get("on"),
                  "removed": False})
    s.put_edge(org, "HAS_MODEL", p["position_id"], p["id"])


def _model_unlinked(s: GraphStore, org: str, p: dict) -> None:
    node = s.node(org, p["id"])
    s.patch_node(org, p["id"], {"removed": True, "unlinked_on": p.get("on")})
    if node and node.get("position_id"):
        s.delete_edge(org, "HAS_MODEL", node["position_id"], p["id"])


def _model_in_use_set(s: GraphStore, org: str, p: dict) -> None:
    for x in s.out(org, p["position_id"], "HAS_MODEL"):
        s.patch_node(org, x["id"], {"in_use": x["id"] == p["link_id"]})


def _model_relinked(s: GraphStore, org: str, p: dict) -> None:
    s.patch_node(org, p["id"], {"model_id": p["model_id"], "name": p["name"], "note": p["note"]})


PROJECTORS = {
    "position.model_linked": _model_linked,
    "position.model_unlinked": _model_unlinked,
    "position.model_in_use_set": _model_in_use_set,
    "position.model_relinked": _model_relinked,
}


def _sv():
    from backend.maintenance import service

    return service


# ---- the graph side (a mixin of Maintenance) ----------------------------------------------

class PositionModelOps:
    """Methods added to ``Maintenance``."""

    def _model_links(self, position_id: str) -> list[dict]:
        live = [x for x in self.s.out(self.org, position_id, "HAS_MODEL") if not x.get("removed")]
        return sorted(live, key=lambda x: (x.get("linked_on") or "", x["id"]))

    def _model_link_view(self, link: dict) -> dict:
        modes = []
        for mid in link.get("failure_mode_ids") or []:
            fm = self.s.node(self.org, mid)
            if fm:
                modes.append({"id": fm["id"], "text": fm.get("text", ""),
                              "gone": bool(fm.get("retired") or fm.get("merged_into"))})
        return {"id": link["id"], "position_id": link.get("position_id"), "model_type": link.get("model_type"),
                "model_id": link.get("model_id"), "role": link.get("role"), "name": link.get("name") or "",
                "note": link.get("note") or "", "source": link.get("source") or None, "failure_modes": modes,
                "linked_on": link.get("linked_on")}

    def position_models(self, position_id: str) -> list[dict]:
        """The models attached to a position, oldest first, the one in use marked (``in_use``)."""
        self._get(position_id, "Position")
        links = self._model_links(position_id)
        used = self._in_use_of(links)
        return [self._model_link_view(x) | {"in_use": x["id"] == used} for x in links]

    @staticmethod
    def _in_use_of(links: list[dict]) -> str | None:
        """The id of the row in use among a position's live links: the one set, else its own life
        model (the latest), else its RBD, else its prediction."""
        if not links:
            return None
        set_one = next((x for x in links if x.get("in_use")), None)
        if set_one:
            return set_one["id"]
        for roles in (None, ("rbd",), ("prediction",)):
            group = [x for x in links if (x.get("role") in roles if roles else x.get("role") not in ("rbd", "prediction"))]
            if group:
                return group[-1]["id"]  # the latest (links are oldest first)
        return links[-1]["id"]

    def in_use_link(self, position_id: str) -> dict | None:
        """The position's model in use (a link view), or None."""
        links = self._model_links(position_id)
        used = self._in_use_of(links)
        return next((self._model_link_view(x) | {"in_use": True} for x in links if x["id"] == used), None)

    def use_position_model(self, position_id: str, link_id: str) -> dict:
        """Make one of the position's rows the model in use."""
        sv = _sv()
        self._get(position_id, "Position")
        if not any(x["id"] == link_id for x in self._model_links(position_id)):
            raise sv.Invalid("That model isn't on this position (use_link_id: one of its models).")
        self._emit("position.model_in_use_set", {"position_id": position_id, "link_id": link_id})
        return self.in_use_link(position_id)

    def all_position_models(self, position_ids=None) -> list[dict]:
        """Every model attached to a position in use (only these positions, when given)."""
        wanted = set(position_ids) if position_ids is not None else None
        out = []
        for link in self.s.nodes(self.org, "ModelLink"):
            pid = link.get("position_id")
            if link.get("removed") or (wanted is not None and pid not in wanted):
                continue
            pos = self.s.node(self.org, pid, "Position")
            if pos is None or pos.get("retired"):
                continue
            out.append(self._model_link_view(link))
        used = {pid: self._in_use_of(self._model_links(pid)) for pid in {x["position_id"] for x in out}}
        for x in out:
            x["in_use"] = used.get(x["position_id"]) == x["id"]
        return sorted(out, key=lambda x: (x["position_id"] or "", x["linked_on"] or "", x["id"]))

    def model_link(self, link_id: str) -> dict:
        link = self._get(link_id, "ModelLink")
        if link.get("removed"):
            raise _sv().Invalid("That model was taken off its position.")
        return self._model_link_view(link)

    def class_model_of(self, position_id: str) -> dict | None:
        """The position class's fitted model ({position_class, model_id, ...}), or None."""
        sv = _sv()
        p = self._get(position_id, "Position")
        name = (p.get("position_class") or "").strip()
        if not name:
            return None
        node = self.s.node(self.org, sv.class_id(self.org, name)) or {}
        model = node.get("model")
        return {"position_class": node.get("name") or name, **model} if model and model.get("model_id") else None

    def _mode_ids_on(self, position_id: str, failure_mode_ids) -> list[str]:
        sv = _sv()
        ids = []
        for mid in failure_mode_ids or []:
            mid = str(mid or "").strip()
            if mid and mid not in ids:
                ids.append(mid)
        if len(ids) > sv.MAX_LIST:
            raise sv.Invalid(f"Name at most {sv.MAX_LIST} failure modes.")
        on = {fm["id"] for fm in self._modes_on(position_id)}
        stray = [mid for mid in ids if mid not in on]
        if stray:
            raise sv.Invalid("Pick failure modes of this position (failure_mode_ids: ids from its failure modes); "
                             f"not one of them: {', '.join(stray[:5])}.")
        return ids

    def link_position_model(self, position_id: str, model_type: str, model_id: str, role: str = "assigned",
                            failure_mode_ids=None, name: str = "", note: str = "", source: dict | None = None,
                            replace_link_id: str | None = None) -> dict:
        """Attach a model to a position (a link: the model isn't copied). failure_mode_ids:
        the failure modes it describes (none: every failure there). replace_link_id: a
        model on the position this one takes the place of (it's taken off)."""
        sv = _sv()
        p = self._get(position_id, "Position")
        if p.get("retired"):
            raise sv.Invalid(f"{p['name']} has been retired: restore it first.")
        if model_type not in MODEL_TYPES:
            raise sv.Invalid(f"The model type is one of {', '.join(MODEL_TYPES)}.")
        if role not in ROLES:
            raise sv.Invalid(f"The role is one of {', '.join(ROLES)}.")
        model_id = sv._text(model_id, "model id", required=True)
        modes = self._mode_ids_on(position_id, failure_mode_ids)
        live = self._model_links(position_id)
        if replace_link_id:
            old = next((x for x in live if x["id"] == replace_link_id), None)
            if old is None:
                raise sv.Invalid("The model to replace isn't on this position (replace_link_id: one of its models).")
        for x in live:
            if x["id"] != replace_link_id and x.get("model_type") == model_type and x.get("model_id") == model_id \
                    and sorted(x.get("failure_mode_ids") or []) == sorted(modes):
                raise sv.Invalid(f"“{x.get('name') or 'That model'}” is already on {p['name']}"
                                 f"{' for those failure modes' if modes else ''}.")
        if len(live) - (1 if replace_link_id else 0) >= MAX_LINKS_EACH:
            raise sv.Invalid(f"A position can carry at most {MAX_LINKS_EACH} models: take one off first.")
        day = self.today()
        if replace_link_id:
            self._emit("position.model_unlinked", {"id": replace_link_id, "on": day})
        link_id = sv.new_id()
        self._emit("position.model_linked", {
            "id": link_id, "position_id": position_id, "model_type": model_type, "model_id": model_id,
            "role": role, "failure_mode_ids": modes, "name": sv._text(name, "model's name")[:sv.SHORT_TEXT],
            "note": sv._text(note, "note"), "source": source or None, "on": day})
        return self.model_link(link_id)

    def unlink_position_model(self, link_id: str) -> dict:
        """Take a model off its position (the model stays in Models)."""
        link = self._get(link_id, "ModelLink")
        if link.get("removed"):
            raise _sv().Invalid("That model was already taken off.")
        self._emit("position.model_unlinked", {"id": link_id, "on": self.today()})
        return {"unlinked": link_id, "position_id": link.get("position_id"), "name": link.get("name") or ""}

    def relink_position_model(self, link_id: str, model_id: str, name: str, note: str = "") -> dict:
        """Point a link at another saved model of its kind (or leave it on the same one),
        with the name and note it carries from now on. The link, its position and the
        failure modes it is for stay."""
        sv = _sv()
        link = self._get(link_id, "ModelLink")
        if link.get("removed"):
            raise sv.Invalid("That model was taken off its position.")
        self._emit("position.model_relinked", {
            "id": link_id, "model_id": sv._text(model_id, "model id", required=True),
            "name": sv._text(name, "model's name", required=True)[:sv.SHORT_TEXT],
            "note": sv._text(note, "note")})
        return self.model_link(link_id)

    def _copy_model_links(self, mapping: dict) -> int:
        """A built item's positions take their design positions' models (role design),
        each failure mode matched by its words. ``mapping``: design position id → built."""
        made = 0
        day = self.today()
        for src_id, dst_id in mapping.items():
            links = self._model_links(src_id)
            if not links:
                continue
            by_text = {(fm.get("text") or "").strip().lower(): fm["id"] for fm in self._modes_on(dst_id)}
            for x in links:
                modes = []
                for mid in x.get("failure_mode_ids") or []:
                    fm = self.s.node(self.org, mid)
                    got = fm and by_text.get((fm.get("text") or "").strip().lower())
                    if got and got not in modes:
                        modes.append(got)
                self._emit("position.model_linked", {
                    "id": _sv().new_id(), "position_id": dst_id, "model_type": x.get("model_type"),
                    "model_id": x.get("model_id"), "role": "design", "failure_mode_ids": modes,
                    "name": x.get("name") or "", "note": x.get("note") or "",
                    "source": {"design_position_id": src_id, "design_role": x.get("role")}, "on": day})
                made += 1
        return made

    def decisions_using(self) -> dict:
        """Every live failure mode's decision evidence: {(type, id): [{failure_mode_id, text,
        position_id, position}]} (a combination's members' own evidence too)."""
        out: dict = {}
        for fm in self.s.nodes(self.org, "FailureMode"):
            if fm.get("retired") or fm.get("merged_into"):
                continue
            refs = [fm.get("evidence")] + [o.get("evidence") for o in fm.get("outcomes") or []]
            keys = {(e.get("type"), e.get("id")) for e in refs if isinstance(e, dict) and e.get("id")}
            if not keys:
                continue
            pos = self.s.inn(self.org, fm["id"], "CAN_FAIL_AS")
            entry = {"failure_mode_id": fm["id"], "text": fm.get("text", ""),
                     "position_id": pos[0]["id"] if pos else None, "position": pos[0]["name"] if pos else ""}
            for key in keys:
                out.setdefault(key, []).append(entry)
        return out


# ---- the model store side ----------------------------------------------------------------

def fetcher(db, owners, hidden=frozenset()):
    """fetch(model_type, model_id): the saved model a reader can open, or None
    (each looked up once)."""
    from backend.services import alt as alt_service
    from backend.services import degradation as degradation_service
    from backend.services import models as models_service
    from backend.services import recurrent as recurrent_service

    from backend.services import rbds as rbds_service

    from backend.maintenance import covariate_positions

    getters = {"model": models_service.get_model, "recurrent_model": recurrent_service.get_model,
               "degradation_model": degradation_service.get_model, "alt_model": alt_service.get_model,
               "rbd": rbds_service.get_rbd, "covariate_record": covariate_positions.record_doc}
    memo: dict = {}

    def fetch(model_type, model_id):
        key = (model_type, model_id)
        if key not in memo:
            get = getters.get(model_type)
            memo[key] = None if get is None or not model_id or model_id in hidden else get(db, model_id, owners)
        return memo[key]

    return fetch


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and abs(f) != float("inf") else None


def _ci(p: dict | None):
    ci = (p or {}).get("ci")
    if isinstance(ci, (list, tuple)) and len(ci) == 2:
        return _num(ci[0]), _num(ci[1])
    return _num((p or {}).get("lower")), _num((p or {}).get("upper"))


def _number(id_, label, value, lower=None, upper=None, unit="", bound=""):
    return {"id": id_, "label": label, "value": _num(value), "lower": _num(lower), "upper": _num(upper),
            "unit": unit or "", "bound": bound}


def _quality(count, kind: str, *, assumed=False, warning=None, what="failures") -> dict:
    """One word on how much to trust a fit, with why: Assumed (parameters typed in, no
    data), Check (the fit came with a warning), Rough (under 5 failures), Fair (under
    15) or Good. The thresholds are the fitting's own (loop.FEW_FAILURES, fitting.FEW_FAILURES)."""
    if assumed:
        return {"word": "Assumed", "tone": "neutral", "why": "Its parameters were typed in, not fitted to data."}
    if warning:
        return {"word": "Check", "tone": "warning", "why": str(warning)[:300]}
    if count is None:
        return {"word": "", "tone": "neutral", "why": ""}
    few, enough = (3, 8) if kind == "degradation" else (5, 15)
    n = int(count)
    said = f"{n:,} {what if n != 1 else what.rstrip('s')}"
    if n < few:
        return {"word": "Rough", "tone": "warning", "why": f"{said}: treat the numbers as rough."}
    if n < enough:
        return {"word": "Fair", "tone": "neutral", "why": f"{said}: usable, with wide bounds."}
    return {"word": "Good", "tone": "success", "why": f"{said}."}


DIST_LABELS = {"weibull": "Weibull", "exponential": "Exponential", "lognormal": "Lognormal", "normal": "Normal",
               "gamma": "Gamma", "loglogistic": "Log-logistic", "gumbel": "Gumbel"}


def summary(model_type: str, doc) -> dict:
    """A saved model in a row: its kind in words, family, unit, the headline numbers
    (with bounds where it has them), the data behind it and a one-word quality."""
    if model_type == "covariate_record":
        from backend.maintenance import covariate_positions

        return covariate_positions.summary(doc)
    r = dict(getattr(doc, "results", None) or {})
    unit = r.get("unit") or ""
    out = {"name": doc.name, "unit": unit, "family": "life", "kind": "", "numbers": [], "counts": {},
           "quality": _quality(None, "life"), "path": None, "trend": None,
           # The two-sided bounds' level: 90%; a repairable fit saved before the rule kept 95%.
           "ci_level": float(r.get("ci_level") or (0.95 if model_type == "recurrent_model" else 0.9))}
    if model_type == "model":
        kind = getattr(doc, "kind", "distribution")
        dist = r.get("distribution_id") or getattr(doc, "distribution_id", "")
        out["path"] = f"/models/m/{doc.id}"
        split = r.get("split") or {}
        failed = split.get("failed")
        if failed is None and isinstance((r.get("plot") or {}).get("scatter"), dict):
            failed = len(r["plot"]["scatter"].get("x") or [])
        out["counts"] = {"failures": failed, "suspensions": split.get("running"), "n": r.get("n")}
        assumed = not getattr(doc, "dataset_id", "") and kind == "distribution"
        if kind == "joint":
            out.update(family="condition", kind="Condition and life", path=f"/models/joint/{doc.id}")
            out["counts"] = {"failures": r.get("n_events"), "suspensions": r.get("n_running"), "n": r.get("n_items")}
            if r.get("marker"):
                out["numbers"].append({"id": "marker", "label": "Reading", "text": r["marker"]
                                       + (f" ({r['marker_unit']})" if r.get("marker_unit") else "")})
            out["quality"] = _quality(r.get("n_events"), "life")
            return out
        if kind == "competing_risks":
            out["kind"] = "Competing risks"
            out["counts"] = {"failures": r.get("failed"), "suspensions": r.get("running"), "n": r.get("n")}
            out["quality"] = _quality(r.get("failed"), "life")
            return out
        params = {str(p.get("name")): p for p in r.get("params") or []}
        label = DIST_LABELS.get(dist) or r.get("distribution") or dist or "Model"
        spec = getattr(doc, "spec", None) or {}
        if assumed and spec.get("params_only") and not spec.get("per_demand") and dist in DIST_LABELS:
            # Typed in: its numbers, so the row can offer Edit parameters… (no unlink and enter again).
            out["entered"] = {"distribution": dist, "unit": spec.get("unit") or unit,
                              "params": {k: _num(v.get("value")) for k, v in params.items()}}
        if kind == "regression":
            # A covariate (e.g. proportional-hazards) model as fitted: its covariates, and the figures at the
            # training data's averages; the stress at a position is set where it's used (an RBD block, a calculation).
            names = [c.get("name") for c in (r.get("functions") or {}).get("covariates") or [] if c.get("name")]
            means = r.get("at_covariate_means") or {}
            out["kind"] = r.get("distribution") or "Covariate model"
            out["covariates"] = names
            out["covariate_words"] = f"covariate model, covariates: {', '.join(names)}" if names else "covariate model"
            if means.get("mttf") is not None:
                out["numbers"].append(_number("mean", "Mean life", means.get("mttf"), None, None, unit))
            if means.get("b10") is not None:
                out["numbers"].append(_number("b10", "B10 life", means.get("b10"), None, None, unit))
            if means.get("covariates"):
                at = ", ".join(f"{c.get('name')} {_num(c.get('value')):g}" for c in means["covariates"]
                               if _num(c.get("value")) is not None)
                out["numbers"].append({"id": "reference", "label": "at", "text": f"the fit's average covariates ({at})"})
            out["quality"] = _quality(failed, "life", warning=r.get("fit_warning"))
            return out
        if r.get("method") == "bayesian_update":
            # Posterior medians with 90% credible intervals (bayes_life.py), never confidence bounds.
            bayes = r.get("bayes") or {}
            out["kind"] = f"{label} (Bayesian)"
            out["credible"] = True
            out["credible_level"] = float(r.get("credible_level") or 0.9)
            out["bayes_source"] = bayes_source(r)
            if dist == "weibull" and "alpha" in params and "beta" in params:
                lo, hi = _ci(params["alpha"])
                out["numbers"].append(_number("char_life", "Characteristic life", params["alpha"].get("value"), lo, hi,
                                              unit, "credible"))
                lo, hi = _ci(params["beta"])
                out["numbers"].append(_number("shape", "Shape", params["beta"].get("value"), lo, hi, "", "credible"))
            for key, label_ in (("mean", "Mean life"), ("b10", "B10 life")):
                b = bayes.get(key) or {}
                if b.get("point") is not None:
                    out["numbers"].append(_number(key, label_, b.get("point"), b.get("lower"), b.get("upper"), unit,
                                                  "credible"))
            out["quality"] = {"word": "Bayesian", "tone": "neutral",
                              "why": bayes.get("label") or "A Bayesian update of a baseline with this history."}
            return out
        out["kind"] = label if kind == "distribution" else (r.get("distribution") or label)
        if kind == "distribution" and dist == "weibull" and "alpha" in params and "beta" in params:
            lo, hi = _ci(params["alpha"])
            out["numbers"].append(_number("char_life", "Characteristic life", params["alpha"].get("value"), lo, hi, unit))
            lo, hi = _ci(params["beta"])
            out["numbers"].append(_number("shape", "Shape", params["beta"].get("value"), lo, hi))
        elif kind == "distribution" and dist == "exponential" and "failure_rate" in params:
            rate = _num(params["failure_rate"].get("value"))
            lo, hi = _ci(params["failure_rate"])
            out["numbers"].append(_number("mtbf", "MTBF", 1 / rate if rate else None, 1 / hi if hi else None,
                                          1 / lo if lo else None, unit))
        life = r.get("life") or {}
        mttf = life.get("mttf") or {}
        if mttf.get("value") is not None:
            out["numbers"].append(_number("mean", "Mean life", mttf.get("value"), mttf.get("lower"), None, unit,
                                          "lower"))
        b10 = next((b for b in life.get("b_lives") or [] if b.get("label") == "B10"), None)
        if b10 and b10.get("value") is not None:
            out["numbers"].append(_number("b10", "B10 life", b10.get("value"), b10.get("lower"), None, unit, "lower"))
        out["quality"] = _quality(failed, "life", assumed=assumed, warning=r.get("fit_warning"))
        return out
    if model_type == "recurrent_model":
        out["path"] = f"/models/recurrent/{doc.id}"
        family = (r.get("family") or "").upper()
        model = r.get("model") or {}
        out["family"] = "repairable"
        out["kind"] = f"Repairable ({family})" if family else f"Repairable ({model.get('name') or 'model'})"
        rate_lo, rate_hi = (r.get("rocof_ci") or [None, None])[:2] if r.get("rocof_ci") else (None, None)
        if r.get("rocof") is not None:
            out["numbers"].append(_number("rate", "Failure rate now", r.get("rocof"), rate_lo, rate_hi,
                                          f"per {unit.lower().rstrip('s')}" if unit else ""))
        if r.get("mtbf") is not None:
            lo, hi = (r.get("mtbf_ci") or [None, None])[:2] if r.get("mtbf_ci") else (None, None)
            out["numbers"].append(_number("mtbf", "MTBF now", r.get("mtbf"), lo, hi, unit))
        growth = r.get("growth") or (r.get("trend") or {}).get("trend")
        words = {"deteriorating": "Getting worse", "increasing": "Getting worse", "improving": "Getting better",
                 "decreasing": "Getting better", "steady": "Steady", "none": "Steady", "constant": "Steady"}
        if growth:
            out["trend"] = words.get(str(growth).lower(), str(growth).capitalize())
        out["counts"] = {"failures": r.get("n_events"), "systems": r.get("n_systems")}
        out["quality"] = _quality(r.get("n_events"), "life", assumed=not getattr(doc, "dataset_id", ""),
                                  what="failures")
        return out
    if model_type == "degradation_model":
        out["path"] = f"/models/degradation/{doc.id}"
        out["family"] = "degradation"
        out["kind"] = "Degradation"
        path = (r.get("path_model") or {}).get("name")
        if r.get("threshold") is not None:
            mu = r.get("measurement_unit") or ""
            out["numbers"].append({"id": "threshold", "label": "Fails at",
                                   "text": f"{_num(r['threshold']):g}{(' ' + mu) if mu else ''}"
                                           + (f" · {path.lower()} path" if path else "")})
        life_model = r.get("life_model") or {}
        if life_model.get("mean") is not None:
            out["numbers"].append(_number("mean", "Mean life", life_model.get("mean"), None, None, unit))
        out["counts"] = {"units": r.get("n_units"), "readings": r.get("n_measurements")}
        out["quality"] = _quality(r.get("n_units"), "degradation", what="units measured")
        return out
    if model_type == "alt_model":
        out["path"] = f"/models/alt/{doc.id}"
        out["family"] = "accelerated"
        out["kind"] = f"Accelerated life ({r.get('distribution') or 'model'})"
        out["counts"] = {"failures": r.get("n_failures"), "n": r.get("n")}
        out["quality"] = _quality(r.get("n_failures"), "life")
        # The model as fitted: its stresses, and the life at its lowest tested level (the stress at a
        # position is set where the model is used: an RBD block, a calculation).
        labels = [st.get("label") or st.get("column") or "" for st in r.get("stresses") or []]
        out["covariates"] = labels
        plain = [re.sub(r"\s*\(.*?\)", "", x).strip().lower() or x for x in labels]  # "Temperature (°C)" → "temperature"
        out["covariate_words"] = f"accelerated life, stress: {', '.join(plain)}" if labels else "accelerated life"
        ref = _alt_reference(r)
        if ref:
            lo, hi = (ref["level"].get("own") or {}).get("life_ci") or (None, None)
            out["numbers"].append(_number("char_life", "Characteristic life", ref["level"].get("characteristic_life"),
                                          lo, hi, unit))
            out["numbers"].append({"id": "reference", "label": "at", "text": f"its lowest tested stress ({ref['words']})"})
        return out
    return out


def _alt_reference(results: dict) -> dict | None:
    """An ALT's lowest tested level, {level, stress, words}: the reference its row and plot show."""
    levels = sorted([lvl for lvl in results.get("levels") or [] if lvl.get("stress")], key=lambda lvl: lvl["stress"])
    if not levels:
        return None
    stresses = results.get("stresses") or []
    words = []
    for i, v in enumerate(levels[0]["stress"]):
        st = stresses[i] if i < len(stresses) else {}
        unit = st.get("unit") or ""
        words.append(f"{st.get('label') or st.get('column') or 'stress'} {_num(v):g}{(' ' + unit) if unit else ''}")
    return {"level": levels[0], "stress": levels[0]["stress"], "words": ", ".join(words)}


def bayes_source(results: dict) -> str:
    """A Bayesian update's Source in words: its baseline and its data ("Bayesian update of an
    assumed seal-and-bearing baseline · 0 failures, 1 suspension")."""
    bayes = results.get("bayes") or {}
    split = results.get("split") or {}
    f, s = int(split.get("failed") or 0), int(split.get("running") or 0)
    base = (bayes.get("baseline") or {}).get("name") or "a baseline"
    return (f"Bayesian update of {base} · {f} failure{'' if f == 1 else 's'}, "
            f"{s} suspension{'' if s == 1 else 's'}")


def rbds_using(db, owners, hidden=frozenset()) -> dict:
    """{model id: [{id, name}]}: the reader's RBDs with a block on each saved model."""
    from backend.services import rbds as rbds_service

    keys = ("modelId", "model_id", "saved_model_id")
    out: dict = {}
    for rbd in rbds_service.list_rbds(db, owners, hidden):
        seen = set()
        for node in (rbd.graph or {}).get("nodes") or []:
            data = node.get("data") or {}
            for part in ("model", "repair"):
                m = data.get(part)
                if isinstance(m, dict):
                    for k in keys:
                        if isinstance(m.get(k), str) and m[k]:
                            seen.add(m[k])
        for mid in seen:
            out.setdefault(mid, []).append({"id": rbd.id, "name": rbd.name})
    return out


def describe(m, db, owners, hidden, links: list[dict], age: float | None = None) -> list[dict]:
    """Each link with its model's summary (``model`` null when the reader can't open it
    any more: deleted, or not theirs) and what uses the model: the RCM decisions that
    link it as evidence and the RBDs with a block on it."""
    fetch = fetcher(db, owners, hidden)
    decisions = m.decisions_using() if links else {}
    rbds = rbds_using(db, owners, hidden) if links else {}
    out = []
    for link in links:
        doc = fetch(link["model_type"], link["model_id"])
        etype = EVIDENCE_TYPE.get(link["model_type"])
        used = decisions.get((etype, link["model_id"]), []) if etype else []
        if link["model_type"] == "rbd":
            model = rbd_summary(db, owners, doc, age) if doc is not None else None
        else:
            model = summary(link["model_type"], doc) if doc is not None else None
        text = (model or {}).get("bayes_source") or source_text(link)
        if (link.get("source") or {}).get("binding_words"):  # covariates fixed here (covariate_positions.py)
            text = f"{text} ({link['source']['binding_words']})"
        elif link.get("role") == "library" and doc is not None and link["model_type"] == "model":
            # A record with every covariate set here (a pipe's length...): its covariates, fixed, read
            # from the saved model (one saved before covariates kept only its length).
            from backend.maintenance.library_models import covariates_of

            fixed = covariates_of(getattr(doc, "results", None))
            if fixed["words"]:
                text = f"{text} (fixed here: {fixed['words']})"
        if link["model_type"] == "rbd":
            text = rbd_source(link, model)
        if model and model.get("covariate_words") and link.get("role") in ("assigned", "design"):
            text = f"{text} ({model['covariate_words']})"
        if model and link.get("role") == "prediction":
            model = {**model, "kind": "Prediction (parts count)", "family": "life",
                     "quality": {"word": "Predicted", "tone": "neutral",
                                 "why": "A handbook parts count: no failure data behind it, and no bounds."}}
        out.append({**link, "model": model,
                    "source_text": text, "stale": stale(m, link),
                    "used_by": {"decisions": used, "rbds": rbds.get(link["model_id"], [])}})
    return out


def _placeholders(graph: dict) -> list[str]:
    out = []
    for n in (graph or {}).get("nodes") or []:
        d = n.get("data") or {}
        if (d.get("model") or {}).get("placeholder"):
            out.append(d.get("label") or n.get("id"))
    return out


def rbd_summary(db, owners, doc, age: float | None = None) -> dict:
    """An RBD in a row: the system's mean life, B10 and (with ``age``) reliability there, from the exact
    analysis (no simulation: a repairable diagram's availability is simulated on its own page),
    and its placeholders."""
    from backend.services import rbds as rbds_service

    graph = doc.graph or {}
    unit = graph.get("unit") or ""
    blocks = [n for n in graph.get("nodes") or [] if n.get("type") not in ("input", "output")]
    ph = _placeholders(graph)
    out = {"name": doc.name, "unit": unit, "family": "rbd", "kind": "RBD", "numbers": [], "trend": None,
           "counts": {"blocks": len(blocks), "placeholders": len(ph)}, "placeholders": ph,
           "path": f"/systems/b/{doc.id}", "repairable": bool(graph.get("repairable")),
           "quality": ({"word": f"{len(ph)} placeholder{'s' if len(ph) != 1 else ''}", "tone": "warning",
                        "why": f"Placeholder models stand in for {', '.join(ph)}: the figures aren't real until they "
                               "have models."} if ph else {"word": "", "tone": "neutral", "why": ""})}
    if graph.get("repairable"):
        out["numbers"].append({"id": "reference", "label": "", "text": "a repairable diagram: open it to simulate "
                                                                       "availability"})
        return out
    try:
        res = rbds_service.analyze_graph(db, graph, owners, at_times=[float(age)] if age else None)
    except Exception as err:  # noqa: BLE001 - a row says why rather than failing the read
        out["analysis_error"] = str(err)[:300]
        return out
    # A non-repairable diagram has no repair, so its mean is the mean life (time to the
    # system's first failure), never an MTBF; one that can be infinite (a cure fraction, a
    # block that never fails) isn't shown as a number. The system curve is exact from the
    # blocks' point models, so neither has bounds: the note says so.
    exact = "no bounds: the system curve is exact from the blocks' point models"
    mean = _number("mean", "Mean life", res.get("mttf"), None, None, unit) | {"note": exact}
    if mean["value"] is None:
        mean = {**mean, "text": "not finite (the system may never fail)", "note": ""}
    out["numbers"].append(mean)
    b10 = _number("b10", "B10 life", (res.get("blife") or {}).get("b10"), None, None, unit)
    out["numbers"].append(b10 | {"note": exact if b10["value"] is not None else ""})
    at = res.get("at") or {}
    if age and at.get("sf"):
        r = _num(at["sf"][0])
        u = unit.lower()
        out["numbers"].append({"id": "reference", "label": "", "text": f"reliability {r:.1%} at {_num(age):g}{(' ' + u) if u else ''}"
                               if r is not None else ""})
        out["at_age"] = {"age": float(age), "reliability": r}
    out["curves"] = {"x": res.get("time"), "sf": (res.get("system") or {}).get("sf"), "hf": None, "sf_lower": None,
                     "sf_upper": None, "band": None, "what": "System reliability"}
    return out


def rbd_source(link: dict, model: dict | None) -> str:
    """An RBD row's Source: "Built from 5 positions inside · 2 placeholders" or "Linked: <name>"."""
    src = link.get("source") or {}
    ph = len((model or {}).get("placeholders") or [])
    tail = f" · {ph} placeholder{'s' if ph != 1 else ''}" if ph else ""
    if src.get("built_from") is not None:
        n = int(src["built_from"])
        return f"Built from {n} position{'s' if n != 1 else ''} inside{tail}"
    if src.get("new"):
        return f"New RBD{' (one block for the position itself)' if src['new'] == 'self' else ''}{tail}"
    return f"Linked: {(model or {}).get('name') or link.get('name') or 'an RBD'}{tail}"


def stale(m, link: dict) -> str | None:
    """Why a fitted model is behind its history ("2 failures since it was fitted"), or None:
    failures recorded at the position (or its class) since the fit."""
    src = link.get("source") or {}
    if link.get("role") not in ("fitted", "bayesian") or src.get("failures") is None:
        return None
    sv = _sv()
    try:
        if src.get("scope") == "class":
            rows = m.class_life_data(src.get("class_name") or "")["rows"]
        elif src.get("scope") == "position":
            rows = m.life_data(link["position_id"])
        else:
            return None
    except (sv.NotFound, sv.Invalid):
        return None
    texts = {(f.get("text") or "").strip().lower() for f in link.get("failure_modes") or []}
    now = sum(1 for r in _rows_for(m, rows, texts) if r["c"] != 1)
    more = now - int(src["failures"])
    if more <= 0:
        return None
    if link.get("role") == "bayesian":
        return f"{more} failure{'s' if more != 1 else ''} since it was updated: update it with them"
    return f"{more} failure{'s' if more != 1 else ''} since it was fitted: refit it"


def _curves(model_type: str, doc, db, owners) -> dict | None:
    """The plot's lines: reliability and hazard over time, with the reliability's 90%
    two-sided bounds where the model has them (``band`` says the level)."""
    r = dict(doc.results or {})
    if model_type == "model" and doc.kind == "joint":
        s = r.get("survival_new") or {}
        if s.get("x") and s.get("sf"):
            return {"x": s["x"], "sf": s["sf"], "sf_lower": s.get("sf_lower"), "sf_upper": s.get("sf_upper"),
                    "hf": None, "what": "Reliability of a new unit",
                    "band": {"kind": "confidence", "level": float(r.get("confidence") or 0.95)}
                    if s.get("sf_lower") else None}
        return None
    if model_type == "alt_model":
        # At its lowest tested level, with the Wald band: the model as fitted (a position's stress is set
        # where the model is used).
        ref = _alt_reference(r)
        if not ref:
            return None
        from backend.services import alt as alt_service

        try:
            ev = alt_service.evaluate(db, doc.id, list(ref["stress"]), owners)
        except Exception:  # noqa: BLE001 - no plot rather than a failed read
            return None
        c = ev.get("curves") or {}
        band = (ev.get("bounds") or {}).get("band") or {}
        out = {"x": c.get("x"), "sf": c.get("sf"), "hf": c.get("hf"), "sf_lower": None, "sf_upper": None,
               "band": None, "what": f"Reliability at its lowest tested stress ({ref['words']})"}
        if band.get("x") and band.get("lower") and len(band["x"]) == len(band["lower"]):
            import numpy as np

            x = np.asarray(c.get("x") or [], dtype=float)
            if len(x):
                out["sf_lower"] = np.interp(x, band["x"], band["lower"]).tolist()
                out["sf_upper"] = np.interp(x, band["x"], band["upper"]).tolist()
                out["band"] = {"kind": "confidence", "level": float((ev.get("bounds") or {}).get("confidence") or 0.9)}
        return out if out["x"] and out["sf"] else None
    if model_type == "model":
        c = (r.get("functions") or {}).get("curves") or {}
        if not c.get("x") or not c.get("sf"):
            return None
        out = {"x": c["x"], "sf": c["sf"], "hf": c.get("hf"), "sf_lower": None, "sf_upper": None,
               "what": "Reliability at the fit's average covariates" if doc.kind == "regression" else "Reliability",
               "band": None}
        if model_type == "model" and (doc.spec or {}).get("method") == "bayesian_update":
            # The posterior-predictive band: the credible interval on R(t) at each age (SurPyval's cri),
            # from the model rebuilt from its recipe; never confidence bounds.
            from backend.services import bayes_life

            level = float(r.get("credible_level") or bayes_life.LEVEL)
            try:
                band = bayes_life.rebuild(doc.spec).cri(c["x"], alpha_ci=1 - level)
                out["sf_lower"] = [bayes_life._f(v) for v in band[:, 0]]
                out["sf_upper"] = [bayes_life._f(v) for v in band[:, 1]]
                out["band"] = {"kind": "credible", "level": level}
            except Exception:  # noqa: BLE001 - the line stands without its band
                pass
        elif model_type == "model" and doc.kind in ("distribution", "discrete") and doc.dataset_id:
            from backend.services import models as models_service

            try:
                cb = models_service.confidence(db, doc.id, {"on": "sf"}, owners)
                if cb.get("lower") and len(cb["lower"]) == len(c["x"]):
                    out["sf_lower"], out["sf_upper"] = cb.get("lower"), cb.get("upper")
                    out["band"] = {"kind": "confidence", "level": round(1.0 - float(cb.get("alpha_ci") or 0.1), 6)}
            except Exception:  # noqa: BLE001 - the line stands without its bounds
                pass
        return out
    if model_type == "degradation_model":
        c = (r.get("life_model") or {}).get("curves") or {}
        if c.get("x") and c.get("sf"):
            return {"x": c["x"], "sf": c["sf"], "hf": c.get("hf"), "sf_lower": None, "sf_upper": None,
                    "what": "Reliability (from the wear reaching its limit)"}
        return None
    if model_type == "recurrent_model":
        mcf = r.get("mcf") or {}
        x, y = mcf.get("x") or mcf.get("t"), mcf.get("y") or mcf.get("mcf") or mcf.get("model")
        if isinstance(x, list) and isinstance(y, list) and len(x) == len(y) and x:
            return {"x": x, "mcf": y, "what": "Expected failures so far (mean cumulative function)"}
        return None
    return None


def _params(doc) -> list[dict]:
    rows = []
    for p in (doc.results or {}).get("params") or []:
        if not isinstance(p, dict) or "value" not in p:
            continue
        lo, hi = _ci(p)
        rows.append({"name": str(p.get("name")), "label": p.get("part_label") or "", "value": _num(p.get("value")),
                     "lower": lo, "upper": hi, "meaning": p.get("meaning") or ""})
    return rows


def origin_text(link: dict, doc) -> str:
    """Where the model's time starts, in words."""
    unit = ((doc.results or {}).get("unit") or "").lower() if doc is not None else ""
    if link.get("role") == "fitted":
        return "Days in service, from the day each item was fitted to the position."
    if link.get("model_type") == "recurrent_model":
        return f"The system's age{f' in {unit}' if unit else ''}: failures and repairs counted from the start of records."
    return f"Age since new{f', in {unit}' if unit else ''}, as in the saved model."


def source_text(link: dict, position_name: str = "") -> str:
    """How the model came to the position, in words."""
    src = link.get("source") or {}
    role = link.get("role")
    if role == "fitted":
        f, s = src.get("failures") or 0, src.get("suspensions") or 0
        counts = f"{f} failure{'' if f == 1 else 's'}, {s} suspension{'' if s == 1 else 's'}"
        if src.get("scope") == "class":
            return f"Fitted from the class {src.get('class_name') or ''}'s pooled history: {counts}".replace("  ", " ")
        if src.get("scope") == "design":
            return f"Fitted from the built units' history: {counts}"
        return f"Fitted from this position's history: {counts}"
    if role == "class":
        return f"From the class {src.get('class_name') or ''}".strip()
    if role == "bayesian":
        return src.get("label") or f"Bayesian update of {src.get('baseline') or 'a baseline'}"
    if role == "design":
        return "From the product's design"
    if role == "library":
        from backend.maintenance.library_models import source_text as library_source

        return library_source(src)
    if role == "prediction":
        env = src.get("environment_name") or src.get("environment") or ""
        return f"Predicted from its parts list (parts count{', ' + env if env else ''})"
    return f"Assigned: {link.get('name') or 'a saved model'}"


def detail(m, db, owners, hidden, link_id: str, age: float | None = None) -> dict:
    """One link in full, for the panel: the model's summary, its parameters with bounds,
    the plot's lines, the data behind it (counts, unit, where time starts), what uses it
    and the notes. An RBD: its blocks (each block's model and the position it came from)
    and the system figures (``age``: the reliability there)."""
    link = m.model_link(link_id)
    [row] = describe(m, db, owners, hidden, [link], age)
    doc = fetcher(db, owners, hidden)(link["model_type"], link["model_id"])
    pos = m.s.node(m.org, link["position_id"], "Position") or {}
    if link["model_type"] == "rbd":
        return {**row, "position": {"id": pos.get("id"), "name": pos.get("name", "")}, "params": [],
                "curves": (row.get("model") or {}).get("curves"), "origin": "", "model_notes": "",
                "blocks": rbd_blocks(m, link, doc) if doc is not None else [], "stress_note": None, "prediction": None}
    notes = ""
    if doc is not None:
        notes = str(((doc.spec or {}).get("notes")) or (doc.results or {}).get("notes") or "")
        if not isinstance(notes, str):
            notes = ""
    return {**row, "position": {"id": pos.get("id"), "name": pos.get("name", "")},
            "source_text": row["source_text"],
            "params": _params(doc) if doc is not None else [],
            "curves": _curves(link["model_type"], doc, db, owners) if doc is not None else None,
            "origin": origin_text(link, doc), "model_notes": notes[:2000],
            # A covariate model is shown as fitted: the stress is set where it's used.
            "stress_note": (f"Covariates: {(link.get('source') or {})['binding_words']}." if (
                link.get("source") or {}).get("binding_words") else
                "Shown as fitted. The stress (or covariates) at this position is set where the model is "
                "used: an RBD block or a calculation." if (row.get("model") or {}).get("covariate_words")
                else None),
            "prediction": prediction_detail(db, owners, link) if link.get("role") == "prediction" else None}


def link_saved(m, db, owners, hidden, position_id: str, model_type: str, model_id: str, failure_mode_ids=None,
               note: str = "", replace_link_id: str | None = None) -> dict:
    """Attach a saved model the reader can open (theirs or a sample) to a position."""
    sv = _sv()
    if model_type not in MODEL_TYPES:
        raise sv.Invalid(f"The model type is one of {', '.join(MODEL_TYPES)}.")
    doc = fetcher(db, owners, hidden)(model_type, str(model_id or ""))
    if doc is None:
        raise sv.NotFound(f"Model {model_id}")
    return m.link_position_model(position_id, model_type, doc.id, "assigned", failure_mode_ids, doc.name, note,
                                 None, replace_link_id)


def link_from_class(m, db, owners, hidden, position_id: str, failure_mode_ids=None, note: str = "",
                    replace_link_id: str | None = None) -> dict:
    """Attach the position class's fitted model to the position."""
    sv = _sv()
    p = m._get(position_id, "Position")
    cm = m.class_model_of(position_id)
    if cm is None:
        if not (p.get("position_class") or "").strip():
            raise sv.Invalid(f"{p['name']} has no position class: set one, or assign a saved model.")
        raise sv.Invalid(f"The class {p['position_class']} has no fitted model yet: fit one from its pooled history "
                         "(Fit from history…, or maintenance reliability.fit_class_model).")
    doc = fetcher(db, owners, hidden)("model", cm["model_id"])
    return m.link_position_model(position_id, "model", cm["model_id"], "class", failure_mode_ids,
                                 doc.name if doc is not None else f"{cm['position_class']} (class model)", note,
                                 {"class_name": cm["position_class"]}, replace_link_id)


def _rows_for(m, rows: list[dict], texts: set[str]) -> list[dict]:
    """Life rows for the failure modes named (their words, lower case): a failure by
    another mode censors the row at the life it surely reached (it survived these modes
    that long). With none named every failure counts."""
    if not texts:
        return rows
    out = []
    for r in rows:
        if r["c"] == 1:
            out.append(r)
            continue
        f = m.s.node(m.org, r.get("fitment_id")) if r.get("fitment_id") else None
        fm = f and f.get("failure_mode_id") and m.s.node(m.org, f["failure_mode_id"])
        if fm and (fm.get("text") or "").strip().lower() in texts:
            out.append(r)
        else:
            out.append({k: v for k, v in r.items() if k not in ("xl", "xr")}
                       | {"c": 1, "x": r["xl"] if r["c"] == 2 else r["x"]})
    return out


def fit_position_model(m, db, position_id: str, distribution: str = "weibull", failure_mode_ids=None,
                       scope: str = "auto", note: str = "", replace_link_id: str | None = None) -> dict:
    """Fit a non-repairable model to a position's own failure history (a design position:
    the history of the units built from it), or to its class's pooled history when its own
    is thin (scope auto), save it to Models and attach it (role fitted). failure_mode_ids:
    the failure modes it's for (failures by other modes count as suspensions)."""
    import pandas as pd

    from backend.maintenance import loop
    from backend.services import datasets as datasets_service
    from backend.services import models as models_service

    sv = _sv()
    if distribution not in FIT_DISTRIBUTIONS:
        raise sv.Invalid(f"The distribution is one of {', '.join(FIT_DISTRIBUTIONS)}.")
    if scope not in FIT_SCOPES:
        raise sv.Invalid(f"The scope is one of {', '.join(FIT_SCOPES)}.")
    p = m._get(position_id, "Position")
    if p.get("retired"):
        raise sv.Invalid(f"{p['name']} has been retired: restore it first.")
    modes = m._mode_ids_on(position_id, failure_mode_ids)
    texts = {(m.s.node(m.org, mid) or {}).get("text", "").strip().lower() for mid in modes}
    design = m._design_root_of(position_id)
    if design:
        own, own_scope = m.design_rollup(position_id)["life_data"]["rows"], "design"
    else:
        own, own_scope = m.life_data(position_id), "position"

    def usable(rows):
        rows = [r for r in _rows_for(m, rows, texts) if (r["xr"] if r["c"] == 2 else r["x"]) > 0]
        return rows, sum(1 for r in rows if r["c"] != 1)

    needed = 1 if distribution == "exponential" else loop.MIN_FAILURES
    rows, failures = usable(own)
    used, class_name = own_scope, ""
    class_failures = None
    if scope == "class" or (scope == "auto" and failures < needed):
        class_name = (p.get("position_class") or "").strip()
        if class_name:
            try:
                crows, class_failures = usable(m.class_life_data(class_name)["rows"])
            except sv.NotFound:
                crows, class_failures = [], 0
            if scope == "class" or class_failures >= needed:
                rows, failures, used = crows, class_failures, "class"
        elif scope == "class":
            raise sv.Invalid(f"{p['name']} has no position class to pool from.")
    if failures < needed:
        whose = "its class's pooled history" if used == "class" else (
            "the units built from it" if used == "design" else "this position's history")
        also = (f" (its class {class_name} has {class_failures})" if class_failures is not None and used != "class"
                else "")
        for_modes = " for those failure modes" if modes else ""
        hint = " With one failure, fit exponential (a constant failure rate) until more are on record." \
            if failures == 1 and distribution != "exponential" else ""
        raise sv.Invalid(f"{whose[0].upper()}{whose[1:]} has {failures} failure{'s' if failures != 1 else ''}"
                         f"{for_modes}{also}; a {distribution} model needs at least {needed}.{hint} "
                         "Or assign a saved model instead.")
    buf = io.StringIO()
    if any(r["c"] == 2 for r in rows):
        pd.DataFrame(loop._interval_rows(rows), columns=["shortest", "longest", "censored"]).to_csv(buf, index=False)
        mapping = {"xl": "shortest", "xr": "longest", "c": "censored"}
    else:
        pd.DataFrame({"days": [r["x"] for r in rows], "censored": [r["c"] for r in rows]}).to_csv(buf, index=False)
        mapping = {"x": "days", "c": "censored"}
    what = p["name"] if used != "class" else class_name
    if modes:
        words = ", ".join(sorted((m.s.node(m.org, mid) or {}).get("text", "") for mid in modes))
        what = f"{what}: {words}"
    name = f"{what[:150]} (from maintenance records)"
    dataset = datasets_service.create_dataset(db, f"{what[:150]}: maintenance life data.csv",
                                              buf.getvalue().encode(), m.org)
    model = models_service.save_model(db, name, dataset, distribution, mapping, [], None, "days", owner_id=m.org)
    source = {"scope": used, "failures": failures, "suspensions": len(rows) - failures,
              "distribution": model.distribution_id} | ({"class_name": class_name} if used == "class" else {})
    return m.link_position_model(position_id, "model", model.id, "fitted", modes, model.name, note, source,
                                 replace_link_id)


def bayes_position(m, db, owners, hidden, position_id: str, baseline: dict | None = None, trust: str = "guide",
                   exclude=(), age=None, save: bool = False, name: str | None = None, note: str = "",
                   replace_link_id: str | None = None, owner_id: str | None = None) -> dict:
    """A Bayesian update of a baseline with this position's history (bayes_life.py): the
    preview (``save`` false: what the prior says, the history it uses, the update, the plot),
    or saved to Models and attached here (role bayesian). ``baseline`` left out: the position
    class's model. ``exclude``: fitment ids to leave out."""
    from backend.services import bayes_life

    sv = _sv()
    p = m._get(position_id, "Position")
    if p.get("retired"):
        raise sv.Invalid(f"{p['name']} has been retired: restore it first.")
    spec = dict(baseline or {})
    if not spec:
        cm = m.class_model_of(position_id)
        if cm is None:
            words = (f"{p['name']} has no class model to start from: pick a saved model, give numbers you know or a "
                     "B10 you believe.")
            if save:
                raise sv.Invalid(f"Pick a baseline: {words}")
            # The preview says so in words (not a refusal): the dialog shows it while the class's model is chosen.
            return {"needs_baseline": True, "words": words, "position": {"id": p["id"], "name": p["name"]}}
        spec = {"model_id": cm["model_id"]}
    try:
        base = bayes_life.baseline_from(db, owners, hidden, spec)
        rows = bayes_life.position_rows(m, position_id, base.get("unit") or "days", exclude)
        model, result, priors = bayes_life.update(base, trust, rows, age)
    except bayes_life.BayesError as err:
        raise sv.Invalid(str(err)) from None
    result["position"] = {"id": p["id"], "name": p["name"]}
    if not save:
        return result
    if model is None:
        raise sv.Invalid("There's no history at this position to update with yet: the baseline stands as it is.")
    doc = bayes_life.save(db, owner_id or m.org, model, result, priors, name, note)
    source = {"method": bayes_life.METHOD, "label": result["label"], "baseline": base["name"],
              "baseline_model_id": base.get("model_id"), "trust": result["trust"]["id"], "scope": "position",
              "failures": result["counts"]["failures"], "suspensions": result["counts"]["suspensions"]}
    link = m.link_position_model(position_id, "model", doc.id, "bayesian", None, doc.name, note, source,
                                 replace_link_id)
    return {**link, "update": {k: result[k] for k in ("words", "posterior", "b10", "mean", "counts", "label")}}


# ---- reliability prediction rows (the parts-count method) ---------------------------------
#
# A position's predicted failure rate from its parts list (Derryn, 9 Nov 2026: "failure
# prediction in the sense of the parts/component method; this is the only place that should
# go"): the parts listed at the position and every position inside it (replacement parts and
# components; consumables aren't in it), together with, on a product's design, the parts of its
# bill of materials that no parts list in it has (a part on both is counted once, from the parts
# lists, with what's inside it). Each part takes a handbook part type (MIL-HDBK-217F base rate) and a
# quality factor, or an NSWC-11 mechanical component with its conditions (a covariate model); the environment is set once on the position (default: the nearest position
# above with a prediction, else the handbook's ground fixed). The parts count itself is
# backend/services/reliability_prediction.py. It's saved as a reliability prediction (on the
# Predictions page, linked back to the position) and as an exponential model at its rate, so
# the RCM, the calculators and RBDs use it like any model; the link (role prediction) names the
# model and the prediction.

PREDICTION_ROLES = ("replacement", "component")


def _branch(m, root_id: str) -> list[tuple[str, list[str]]]:
    """The position and every position inside it, each with its path below the root."""
    out, stack = [], [(root_id, [])]
    while stack:
        pid, path = stack.pop()
        out.append((pid, path))
        kids = sorted([c for c in m.s.inn(m.org, pid, "PART_OF") if c["label"] == "Position" and not c.get("retired")],
                      key=lambda c: c["name"].lower(), reverse=True)
        stack += [(c["id"], path + [c["name"]]) for c in kids]
    return out


def _assigned(assign: dict | None, previous: dict, part_id, reference) -> dict:
    a = (assign or {}).get(part_id) or (assign or {}).get(reference) or previous.get(reference) or {}
    return a if isinstance(a, dict) else {"record_id": a}


def _line_type(a: dict) -> dict:
    """What a line takes from its assignment: a handbook part type (and a quality factor, or
    None for the part type's default; an NSWC-11 part type: its conditions and, for a rate per
    cycle, its cycles an hour), a rate of the user's own per part, or left out as not an
    electronic part."""
    out = {"record_id": a.get("record_id") or None, "quality_factor": a.get("quality_factor") or None}
    if a.get("record_id") and isinstance(a.get("conditions"), dict) and a["conditions"]:
        out["conditions"] = dict(a["conditions"])
    if a.get("record_id") and a.get("cycles_per_hour") not in (None, ""):
        out["cycles_per_hour"] = a["cycles_per_hour"]
    for k in ("environment", "quality"):  # a handbook part's own covariates (record_covariates.py)
        if a.get("record_id") and a.get(k) not in (None, ""):
            out[k] = a[k]
    if a.get("record_id") and isinstance(a.get("covariates"), dict) and a["covariates"]:
        out["covariates"] = dict(a["covariates"])
    if a.get("rate_per_million_hours") not in (None, ""):
        out["rate_per_million_hours"] = a["rate_per_million_hours"]
    if a.get("excluded"):
        out["excluded"] = True
    return out


def _left_out_keys(left_out) -> set[str]:
    return {str(k) for k in (left_out or []) if isinstance(k, (str, int)) and str(k)}


def _sample_tree(m, position_id: str) -> bool:
    """Whether the position is in a copy of the sample product: its design, or a unit built from it."""
    from backend.maintenance import templates

    top, seen = m.s.node(m.org, position_id, "Position"), set()
    while top and top["id"] not in seen:
        seen.add(top["id"])
        parent = m._parent(top["id"])
        if not parent or parent.get("label") != "Position":
            break
        top = parent
    design = top if not top or top.get("design") else m.s.node(m.org, top.get("design_position_id") or "", "Position")
    return templates.is_sample_product(design)


def _started(a: dict, reference: str, sample: bool) -> dict:
    """A line's assignment, with the sample's conditions for its part where it has an NSWC-11
    model and none of its own yet (the sample product only: its motors, templates.py)."""
    if not sample or not a.get("record_id") or a.get("conditions"):
        return a
    from backend.maintenance import templates

    start = templates.sample_part_conditions(reference, a["record_id"])
    return {**a, "conditions": start} if start else a


def prediction_lines(m, position_id: str, assign: dict | None = None, previous: dict | None = None,
                     left_out=None) -> dict:
    """The parts-count lines for a position: {lines (each with part_id, and listing_id and
    position {id, name} when it's on a parts list), source ("parts lists", "bill of materials" or
    "parts lists and bill of materials"), positions, warnings}. A product's design counts both: its
    positions' parts lists, then the parts of its bill of materials that none of them lists (so a
    part added to a parts list never takes the bill of materials' other lines away, and a part on
    both is counted once, as its parts lists have it). ``assign`` {part id or part number:
    {record_id, quality_factor} or {rate_per_million_hours} or {excluded: true}} and ``previous`` (the last prediction's, by part
    number) give part types. ``left_out`` [listing id or part number]: lines left out of this
    prediction (they stay on the parts list); None takes the last prediction's (``previous``'s
    ``_left_out``)."""
    from backend.services import reliability_prediction as rp

    root = m._get(position_id, "Position")
    previous = previous or {}
    out_keys = _left_out_keys(previous.get("_left_out") if left_out is None else left_out)
    sample = _sample_tree(m, position_id)
    lines, warnings, n, branch = [], [], 0, []
    for pid, path in _branch(m, position_id):
        n += 1
        branch.append({"id": pid, "name": path[-1] if path else root["name"], "depth": len(path)})
        here = None
        for x in m._listings_at(pid):
            view = m._listing_view(x)
            if view["role"] not in PREDICTION_ROLES:
                continue
            here = here or view["position"]
            part = view["part"]
            ref = part.get("part_number") or ""
            a = _assigned(assign, previous, part["id"], ref)
            if a.get("record_id") and not a.get("conditions"):
                # A part on an NSWC-11 model its position fixes covariates of starts from them.
                from backend.maintenance import covariate_positions

                fixed = covariate_positions.prediction_conditions(m, pid, a["record_id"])
                if fixed:
                    a = {**a, "conditions": {k: v for k, v in fixed.items() if k != "cycles_per_hour"},
                         **({"cycles_per_hour": fixed["cycles_per_hour"]} if "cycles_per_hour" in fixed else {})}
            a = _started(a, ref, sample)
            lines.append({"part_id": part["id"], "listing_id": view["id"], "position": dict(here), "role": view["role"],
                          "name": part.get("name") or ref or "Part", "reference": ref,
                          "quantity": view.get("quantity") or 1, "assembly": list(path), **_line_type(a),
                          "left_out": view["id"] in out_keys})
    source = "parts lists"
    if root.get("design"):
        # A product's design: its bill of materials too, less the parts a parts list has already.
        on_lists = len(lines)
        bom = rp.lines_from_product(m, position_id, skip=frozenset(ln["reference"].lower() for ln in lines
                                                                   if ln["reference"]))
        if bom.get("lines") or not on_lists:
            warnings += bom.get("warnings") or []
        for ln in bom.get("lines") or []:
            a = _started(_assigned(assign, previous, None, ln.get("reference")), ln.get("reference") or "", sample)
            lines.append({**ln, "part_id": None, **_line_type(a),
                          "left_out": bool(ln.get("reference")) and ln.get("reference") in out_keys})
        if len(lines) > on_lists or not on_lists:
            source = "parts lists and bill of materials" if on_lists else "bill of materials"
    return {"lines": lines, "source": source, "positions": n, "warnings": warnings,
            "position": {"id": root["id"], "name": root["name"]}, "branch": branch}


def _prediction_links(m, position_id: str) -> list[dict]:
    return [x for x in m.position_models(position_id) if x.get("role") == "prediction"]


def default_environment(m, position_id: str) -> str:
    """The environment a new prediction starts from: this position's last, else the nearest
    position above with one, else the handbook's default (the sample product: its own,
    templates.SAMPLE_PRODUCT_ENVIRONMENT)."""
    from backend.maintenance import templates
    from backend.services import reliability_prediction as rp

    pid = position_id
    seen = set()
    while pid and pid not in seen:
        seen.add(pid)
        for x in _prediction_links(m, pid):
            env = (x.get("source") or {}).get("environment")
            if env:
                return env
        parent = m._parent(pid)
        pid = parent["id"] if parent and parent.get("label") == "Position" else None
    return templates.SAMPLE_PRODUCT_ENVIRONMENT if _sample_tree(m, position_id) else rp.DEFAULT_ENVIRONMENT


def _previous_types(db, owners, m, position_id: str) -> dict:
    """The part types the position's last prediction used, by part number."""
    from backend.services import reliability_prediction as rp

    out = {}
    for x in _prediction_links(m, position_id):
        doc = rp.get_prediction(db, (x.get("source") or {}).get("prediction_id") or "", owners)
        inputs = (doc.inputs or {}) if doc else {}
        for ln in (inputs.get("lines") or []) + (inputs.get("left_out") or []):
            if ln.get("reference") and (ln.get("record_id") or ln.get("excluded")
                                        or ln.get("rate_per_million_hours") is not None):
                out[ln["reference"]] = _line_type(ln)
        # The lines left out of it (by parts-list entry; a bill of materials' by part number).
        keys = [ln.get("listing_id") or ln.get("reference") for ln in inputs.get("left_out") or []]
        out["_left_out"] = [k for k in keys if k]
    return out


def _no_lines_result(environment: str, mission_time) -> dict:
    """The result when every line is left out of the prediction: nothing counted."""
    from backend.services import reliability_prediction as rp

    env = rp.environment_code(environment or rp.DEFAULT_ENVIRONMENT)
    hours = mission_time if isinstance(mission_time, (int, float)) and mission_time > 0 else rp.DEFAULT_MISSION_HOURS
    return {"failure_rate_per_million_hours": 0.0, "failure_rate_per_hour": 0.0, "mtbf_hours": None,
            "reliability_at_mission": None, "mission_time_hours": hours, "lines": [], "excluded": [],
            "unassigned": [], "warnings": [], "counts": {"lines": 0, "assigned": 0, "unassigned": 0, "excluded": 0},
            "environment": {"code": env}}


def predict_position(m, db, owners, hidden, position_id: str, environment: str | None = None,
                     mission_time=None, assign: dict | None = None, save: bool = False, note: str = "",
                     replace_link_id: str | None = None, owner_id: str | None = None, left_out=None) -> dict:
    """The parts count for a position: previewed (``save`` false: the lines with their part
    types, the environment and the result), or saved as a prediction and an exponential model and
    attached (role prediction; an earlier prediction on the position is replaced). ``left_out``
    [parts-list entry id or part number]: lines kept on the parts list but left out of this
    prediction (None: the last prediction's). The result's lines are the counted lines only, in
    order; the left-out ones are its ``left_out`` and the saved inputs' ``left_out``."""
    from backend.db import to_doc
    from backend.schema import ReliabilityPrediction
    from backend.services import models as models_service
    from backend.services import reliability_prediction as rp

    sv = _sv()
    p = m._get(position_id, "Position")
    if p.get("retired"):
        raise sv.Invalid(f"{p['name']} has been retired: restore it first.")
    env = environment or default_environment(m, position_id)
    if left_out is not None and not isinstance(left_out, list):
        raise sv.Invalid("left_out must be a list of parts-list entry ids (or part numbers).")
    got = prediction_lines(m, position_id, assign, _previous_types(db, owners, m, position_id), left_out)
    if not got["lines"] and save:
        raise sv.Invalid(f"{p['name']} has no parts list (nor anything inside it): add the parts it's made of to its "
                         "parts list first.")
    plain = ("part_id", "listing_id", "position", "role", "left_out")
    counted = [{k: v for k, v in ln.items() if k not in plain} for ln in got["lines"] if not ln["left_out"]]
    skipped = [ln for ln in got["lines"] if ln["left_out"]]
    raw = {"environment": env, "mission_time": mission_time, "notes": note or "",
           "lines": counted or [{"name": "-"}]}
    try:
        inputs = rp.normalise_inputs(raw)
        if counted:
            results = rp.results_for(inputs)
        else:
            inputs["lines"] = []
            results = _no_lines_result(inputs["environment"], inputs["mission_time"])
    except rp.PredictionError as err:
        raise sv.Invalid(str(err)) from None
    # What was left out, kept with the prediction (so refreshing it leaves them out again).
    inputs["left_out"] = [{"listing_id": ln.get("listing_id"), "name": ln["name"], "reference": ln.get("reference") or "",
                           "quantity": ln.get("quantity") or 1, "assembly": list(ln.get("assembly") or []),
                           **{k: v for k, v in _line_type(ln).items() if v is not None}} for ln in skipped]
    results["left_out"] = [{"name": ln["name"], "reference": ln.get("reference") or "", "quantity": ln.get("quantity") or 1}
                           for ln in skipped]
    results.setdefault("counts", {})["left_out"] = len(skipped)
    preview = {**got, "environment": inputs["environment"], "mission_time": inputs["mission_time"], "results": results}
    if not save:
        return preview
    rate = results.get("failure_rate_per_hour")
    if not rate:
        raise sv.Invalid("No part on the list has a handbook part type yet: choose one for each part (the "
                         "others are left out), then save.")
    owner = owner_id or m.org
    inputs["position"] = {"id": p["id"], "name": p["name"]}
    name = f"{p['name']}: parts count"[:200]
    pred = ReliabilityPrediction(id=sv.new_id(), name=name, owner_id=owner, inputs=inputs, results=results)
    db[rp.COLLECTION].insert_one(to_doc(pred))
    env_info = results.get("environment") or {}
    model = models_service.import_model(
        db, owner, f"{p['name']} (predicted, parts count)"[:200], "exponential", unit="Hours",
        params=[{"name": "failure_rate", "value": float(rate)}],
        notes=_model_note(p["name"], results, env_info.get("name") or inputs["environment"]))
    db.models.update_one({"_id": model.id}, {"$set": {"results.method": "parts_count",
                                                      "results.prediction_id": pred.id}})
    old = replace_link_id or next((x["id"] for x in _prediction_links(m, position_id)), None)
    counts = results.get("counts") or {}
    source = {"prediction_id": pred.id, "environment": inputs["environment"],
              "environment_name": env_info.get("name"), "mission_time": inputs["mission_time"],
              "rate_per_million_hours": results.get("failure_rate_per_million_hours"),
              "mtbf_hours": results.get("mtbf_hours"), "lines": counts.get("lines"), "assigned": counts.get("assigned"),
              "parts_source": got["source"]}
    link = m.link_position_model(position_id, "model", model.id, "prediction", None, model.name, note, source, old)
    return {**link, "prediction": {"id": pred.id, "results": results}}


def _model_note(name: str, results: dict, environment: str) -> str:
    """The saved model's note: which handbooks its parts count used (and the Navy's statement when
    NSWC-11 is one)."""
    books = [h["short_name"] for h in results.get("handbooks") or []] or ["MIL-HDBK-217F"]
    note = f"A {' and '.join(books)} parts count of {name}'s parts list in {environment}."
    if results.get("disclaimer"):
        note += " " + results["disclaimer"]
    return note


def prediction_detail(db, owners, link: dict) -> dict | None:
    """The saved prediction behind a prediction row: every line's contribution, the factors and
    the handbook, as the Predictions page shows them."""
    from backend.services import reliability_prediction as rp

    pid = (link.get("source") or {}).get("prediction_id")
    doc = rp.get_prediction(db, pid, owners) if pid else None
    if doc is None:
        return None
    return {"id": doc.id, "name": doc.name, "results": doc.results, "environment": (doc.inputs or {}).get("environment"),
            "mission_time": (doc.inputs or {}).get("mission_time")}


# ---- RBD rows ---------------------------------------------------------------------------

def _model_words(model: dict) -> str:
    if not isinstance(model, dict):
        return ""
    name = model.get("name") or model.get("distribution") or model.get("distribution_id") or "model"
    params = ", ".join(f"{p.get('name')} {_num(p.get('value')):g}" for p in model.get("params") or []
                       if _num(p.get("value")) is not None)
    return f"{name}{(' (' + params + ')') if params and not model.get('name') else ''}"


def rbd_blocks(m, link: dict, doc) -> list[dict]:
    """An RBD's blocks for the panel: each block's label, its model in words (placeholder or not),
    and the position it came from (a block built from a position inside this one)."""
    from backend.maintenance import rbd_derive

    kids = {rbd_derive._bid(c["id"]): c for c in m.s.inn(m.org, link["position_id"], "PART_OF")
            if c["label"] == "Position"}
    out = []
    for n in (doc.graph or {}).get("nodes") or []:
        if n.get("type") in ("input", "output"):
            continue
        d = n.get("data") or {}
        model = d.get("model") or {}
        sub = d.get("rbd") or {}
        kid = kids.get(n.get("id"))
        out.append({"id": n.get("id"), "label": d.get("label") or n.get("id"), "type": n.get("type"),
                    "model": (f"RBD: {sub.get('name') or 'a sub-system'}" if sub else _model_words(model)) or "—",
                    "placeholder": bool(model.get("placeholder")), "source": d.get("model_source") or None,
                    "position": {"id": kid["id"], "name": kid["name"]} if kid else None})
    return out


def _convert(dist_id: str, params: list[dict], factor: float) -> list[dict] | None:
    """A distribution's parameters with time multiplied by ``factor`` (one model unit = factor
    diagram units); None for one this can't convert."""
    import math

    p = {x["name"]: float(x["value"]) for x in params}
    if dist_id == "weibull" and {"alpha", "beta"} <= set(p):
        return [{"name": "alpha", "value": p["alpha"] * factor}, {"name": "beta", "value": p["beta"]}]
    if dist_id == "exponential" and "failure_rate" in p:
        return [{"name": "failure_rate", "value": p["failure_rate"] / factor}]
    if dist_id == "lognormal" and {"mu", "sigma"} <= set(p):
        return [{"name": "mu", "value": p["mu"] + math.log(factor)}, {"name": "sigma", "value": p["sigma"]}]
    if dist_id == "normal" and {"mu", "sigma"} <= set(p):
        return [{"name": "mu", "value": p["mu"] * factor}, {"name": "sigma", "value": p["sigma"] * factor}]
    return None


_HOURS_IN = {"hour": 1.0, "day": 24.0, "week": 168.0, "month": 730.5, "year": 8766.0, "minute": 1 / 60}


def _factor(model_unit: str, diagram_unit: str) -> float | None:
    from backend.units import normalize_unit

    a, b = normalize_unit(model_unit) or "hour", normalize_unit(diagram_unit) or "hour"
    if a == b:
        return 1.0
    if a in _HOURS_IN and b in _HOURS_IN:
        return _HOURS_IN[a] / _HOURS_IN[b]
    return None


#: How deep Build from what's inside goes for a position inside with no model of its own.
MAX_NEST = 6


def _descendant_units(m, docs_of, position_id: str, depth: int = 0) -> list[str]:
    """The units of the models in use at and below the positions inside ``position_id``."""
    from backend.units import canonical_unit

    out = []
    if depth > MAX_NEST:
        return out
    for c in m.s.inn(m.org, position_id, "PART_OF"):
        if c["label"] != "Position" or c.get("retired"):
            continue
        x = m.in_use_link(c["id"])
        d = docs_of(x) if x else None
        if d is not None and x["model_type"] == "model" and (d.results or {}).get("unit"):
            out.append(canonical_unit(d.results["unit"]))
        elif d is None:
            out += _descendant_units(m, docs_of, c["id"], depth + 1)
    return out


def _open_covariates_below(m, position_id: str, depth: int = 0) -> bool:
    """Whether a position inside ``position_id`` (any depth) has a model in use with covariates
    left open at the position (a bound block, covariate_positions.py)."""
    from backend.maintenance import covariate_positions

    if depth > MAX_NEST:
        return False
    for c in m.s.inn(m.org, position_id, "PART_OF"):
        if c["label"] != "Position" or c.get("retired"):
            continue
        x = m.in_use_link(c["id"])
        if x is not None and covariate_positions.block_model(x) is not None:
            return True
        if _open_covariates_below(m, c["id"], depth + 1):
            return True
    return False


def _tree_parts(m, db, owners, hidden, position_id: str, with_self: bool = False, owner_id: str | None = None,
                unit: str | None = None, depth: int = 0):
    """What Build from what's inside works from: (position, fetch, the live positions inside, the
    diagram's unit, block(child) -> (block data, note), nested placeholders).

    Each block is the child's life model in use; with none, its class's fitted model; with none
    and positions inside it (a sub-assembly whose lives are its parts': Propulsion's motors and
    propellers), its own RBD built from what's inside it (``owner_id`` given: saved, linked there,
    reused when it has one), as a sub-system block. Only a child with none of these is a placeholder
    (flagged, never invented). Each block says where its model came from (``data.model_source``).
    ``with_self``: block() also takes the position itself (a leaf's one-block diagram). ``unit``:
    the diagram's (a nested one takes its parent's); else the commonest of the models below."""
    from collections import Counter

    from backend.units import canonical_unit

    p = m._get(position_id, "Position")
    fetch = fetcher(db, owners, hidden)
    children = [c for c in m.s.inn(m.org, position_id, "PART_OF") if c["label"] == "Position" and not c.get("retired")]
    in_use = {c["id"]: m.in_use_link(c["id"]) for c in [*children, *([p] if with_self else [])]}
    if with_self and (in_use.get(p["id"]) or {}).get("model_type") not in (None, "model"):
        # The position's own block takes its life model (the latest), never one of its own RBDs.
        own = [x for x in m.position_models(p["id"]) if x.get("model_type") == "model" and x.get("role") != "prediction"]
        in_use[p["id"]] = own[-1] if own else None
    docs = {cid: fetch(x["model_type"], x["model_id"]) if x else None for cid, x in in_use.items()}
    if unit is None:
        units = Counter(canonical_unit((d.results or {}).get("unit") or "") for cid, d in docs.items()
                        if d is not None and in_use[cid]["model_type"] == "model" and (d.results or {}).get("unit"))
        if not units and owner_id is not None:
            units = Counter(_descendant_units(m, lambda x: fetch(x["model_type"], x["model_id"]), position_id))
        unit = units.most_common(1)[0][0] if units else "Hours"
    nested_placeholders: list[str] = []

    def life(child, d, source: str):
        r = d.results or {}
        f = _factor(r.get("unit") or unit, unit)
        if f == 1.0:
            return {"model": {"saved_model_id": d.id}, "data": {"model_source": source}}, None
        conv = _convert(r.get("distribution_id") or d.distribution_id, r.get("params") or [], f) if f and \
            d.kind == "distribution" else None
        if conv is None:
            return None, f"{child['name']}'s model is in {r.get('unit')}, which can't be put in {unit}: a placeholder stands in."
        return ({"model": {"distribution_id": r.get("distribution_id") or d.distribution_id, "params": conv,
                           **({"extras": r["extras"]} if r.get("extras") else {})},
                 "data": {"model_source": f"{source}, put in {unit}"}},
                f"{child['name']}'s model ({d.name}) is in {r.get('unit')}: its numbers were put in {unit}.")

    def block(child):
        x, d = in_use.get(child["id"]), docs.get(child["id"])
        if x is None or d is None:
            cm = m.class_model_of(child["id"])
            cd = fetch("model", cm["model_id"]) if cm else None
            if cd is not None and cd.kind in ("distribution", "regression"):
                return life(child, cd, f"Its class's fitted model ({cm['position_class']}: {cd.name})")
            inside = [c for c in m.s.inn(m.org, child["id"], "PART_OF") if c["label"] == "Position"
                      and not c.get("retired")]
            if inside and owner_id is not None and depth < MAX_NEST and child["id"] != position_id:
                if _open_covariates_below(m, child["id"]):
                    return None, (f"{child['name']}'s parts have models with covariates left open, which a "
                                  "sub-system's blocks can't take from this diagram yet: a placeholder stands in.")
                sub = build_rbd(m, db, owners, hidden, child["id"], owner_id, _unit=unit, _depth=depth + 1)
                nested_placeholders.extend(f"{child['name']} › {ph}" for ph in sub.get("placeholders") or [])
                if sub.get("existing"):
                    nested_placeholders.extend(f"{child['name']} › {ph}" for ph in
                                               _placeholders((fetch("rbd", sub["model_id"]).graph or {})))
                return ({"data": {"rbd": {"id": sub["model_id"], "name": sub["name"]}, "model_source": f"Its own RBD, built from the {len(inside)} position"
                                                  f"{'s' if len(inside) != 1 else ''} inside it ({sub['name']})"}},
                        None)
            return None, None
        from backend.maintenance import covariate_positions

        bound = covariate_positions.block_model(x)
        if bound is not None:  # covariates left open at the position: set on the block or the diagram
            return bound, None
        if x["model_type"] == "rbd":
            return {"data": {"rbd": {"id": d.id, "name": d.name}, "model_source": f"Its RBD in use ({d.name})"}}, None
        if x["model_type"] != "model" or d.kind not in ("distribution", "regression"):
            return None, (f"{child['name']}'s model in use ({d.name}) isn't a life distribution an RBD block can take: "
                          "a placeholder stands in.")
        return life(child, d, f"Its model in use ({d.name})")

    return p, fetch, children, unit, block, nested_placeholders


def _tree_graph(m, db, owners, hidden, position_id: str):
    """A new diagram from the positions inside (normalised and laid out): (graph, built, position,
    children, fetch). Raises Invalid where it can't be made."""
    from backend.maintenance import rbd_derive
    from backend.services.rbd_graph import GraphError, normalize_graph, wrap_layout

    p, fetch, children, unit, block, _ = _tree_parts(m, db, owners, hidden, position_id)
    built = rbd_derive.build(m, position_id, block_model=block, unit=unit)
    try:
        graph = normalize_graph(built["graph"], resolve_saved_model=lambda mid: fetch("model", mid))
    except GraphError as err:
        raise _sv().Invalid(f"The diagram couldn't be made: {err}") from None
    graph["nodes"] = wrap_layout(graph["nodes"])
    return graph, built, p, children, fetch


def build_rbd(m, db, owners, hidden, position_id: str, owner_id: str | None = None,
              replace_link_id: str | None = None, note: str = "", _unit: str | None = None,
              _depth: int = 0) -> dict:
    """"Build an RBD from what's inside": a new diagram whose blocks are the positions one level
    inside (each block the child's model in use: a saved model, or its own RBD as a sub-system;
    else a placeholder, flagged, never invented), wired by their connections and redundancy
    groups (in series with none), saved under Design › Systems and linked here (role rbd).
    ``replace_link_id`` (the position's built RBD row): rebuild into the same diagram, adding the
    positions inside that aren't blocks yet and keeping every edit made to it.

    One built diagram per position: asked to build where there is one already (no
    ``replace_link_id``), nothing is made or saved and that row comes back with ``existing``
    true, so building twice never leaves two diagrams. Where its diagram has since been deleted,
    the row is built again in place."""
    from backend.maintenance import rbd_derive
    from backend.services import rbds as rbds_service
    from backend.services.rbd_graph import GraphError, normalize_graph, wrap_layout

    sv = _sv()
    p, fetch, children, unit, block, nested = _tree_parts(m, db, owners, hidden, position_id,
                                                          owner_id=owner_id or m.org, unit=_unit, depth=_depth)
    old_link = None
    if not replace_link_id:
        had = built_rbd_link(m.position_models(position_id))
        if had is not None and fetch("rbd", had["model_id"]) is not None:
            return {**had, "existing": True, "notes": [], "placeholders": []}
        if had is not None:  # its diagram is gone: built again into the same row
            replace_link_id = had["id"]
    if replace_link_id:
        old_link = next((x for x in m.position_models(position_id) if x["id"] == replace_link_id), None)
        if old_link is None or old_link["model_type"] != "rbd":
            raise sv.Invalid("Rebuild names this position's RBD row (replace_link_id).")
    built = rbd_derive.build(m, position_id, block_model=block, unit=unit)
    resolve = lambda mid: fetch("model", mid)  # noqa: E731
    try:
        graph = normalize_graph(built["graph"], resolve_saved_model=resolve)
        graph["nodes"] = wrap_layout(graph["nodes"])  # a long chain folds to fit the pane it opens in
        existing = None
        if old_link is not None:
            existing = fetch("rbd", old_link["model_id"])
            if existing is not None and built.get("redundancy") and _unrewired(existing.graph or {}):
                # Still in series as first built, and the tree now says which positions back each
                # other up: wired as the tree says, each block keeping what was set on it.
                graph = _rewired(existing.graph or {}, graph, resolve)
                built["notes"].insert(0, "Rewired from the redundancy sets marked in the tree ("
                                      + ", ".join(g["name"] for g in built["redundancy"]) + ").")
            elif existing is not None:
                graph = _add_new_blocks(existing.graph or {}, built["graph"], resolve)
        name = existing.name if existing is not None else f"{p['name']} (from the tree)"
        rbd = rbds_service.save_rbd(db, name, graph, owner_id or m.org, rbd_id=existing.id if existing else None)
    except GraphError as err:
        raise sv.Invalid(f"The diagram couldn't be made: {err}") from None
    source = {"built_from": len(children), "position_ids": [c["id"] for c in children], "notes": built["notes"][:20]}
    # A rebuilt row stays the one in use if it was set to be.
    was_in_use = bool(replace_link_id and (m.s.node(m.org, replace_link_id) or {}).get("in_use"))
    link = m.link_position_model(position_id, "rbd", rbd.id, "rbd", None, rbd.name, note, source, replace_link_id)
    if was_in_use:
        m.use_position_model(position_id, link["id"])
    if nested:
        built["notes"].append(f"Placeholders inside sub-systems: {', '.join(nested[:8])}"
                              f"{' …' if len(nested) > 8 else ''}. Give each a model on the Modelling tab and rebuild.")
    return {**link, "notes": built["notes"], "placeholders": built["placeholders"] + nested}


def new_rbd(m, db, owners, hidden, position_id: str, owner_id: str, repairable: bool = False,
            start: str = "blank", note: str = "") -> dict:
    """New blank RBD: a diagram of the position's own (any position, a leaf included), saved under
    Design › Systems and linked here as its RBD, as a built one is. ``start``: "blank" (just In and
    Out) or "self" (one block for the position itself, its life model in use; with none, a
    placeholder, flagged). ``repairable``: a repairable diagram (availability), else non-repairable.
    {link..., notes, placeholders}."""
    from backend.maintenance import rbd_derive
    from backend.services import rbds as rbds_service
    from backend.services.rbd_graph import GraphError, normalize_graph, wrap_layout

    sv = _sv()
    if start not in ("blank", "self"):
        raise sv.Invalid("start is blank (an empty diagram) or self (one block for the position itself).")
    p = m._get(position_id, "Position")
    if p.get("retired"):
        raise sv.Invalid(f"{p['name']} has been retired: restore it first.")
    fetch = fetcher(db, owners, hidden)
    nodes = [{"id": "in", "type": "input"}, {"id": "out", "type": "output"}]
    edges, notes, placeholders, unit = [], [], [], "Hours"
    if start == "self":
        _, _, _, unit, block, _ = _tree_parts(m, db, owners, hidden, position_id, with_self=True)
        fields, said = block(p)
        if said:
            notes.append(said)
        if fields is None:
            fields = {"model": dict(rbd_derive.PLACEHOLDER), "data": {"model_source": "A placeholder: no model in use"}}
            placeholders.append(p["name"])
            notes.append(f"{p['name']} has no life model in use: a placeholder (flagged) stands in. Give it one on "
                         "the Modelling tab, or set the block's model in the builder.")
        bid = rbd_derive._bid(p["id"])
        nodes.append({"id": bid, "type": "component", "label": p["name"], **fields})
        edges = [{"source": "in", "target": bid}, {"source": bid, "target": "out"}]
    graph = {"unit": unit, "nodes": nodes, "edges": edges, **({"repairable": True} if repairable else {})}
    try:
        graph = normalize_graph(graph, resolve_saved_model=lambda mid: fetch("model", mid))
        graph["nodes"] = wrap_layout(graph["nodes"])
        rbd = rbds_service.save_rbd(db, f"{p['name']} RBD"[:200], graph, owner_id or m.org)
    except GraphError as err:
        raise sv.Invalid(f"The diagram couldn't be made: {err}") from None
    source = {"new": start, "repairable": bool(repairable)}
    link = m.link_position_model(position_id, "rbd", rbd.id, "rbd", None, rbd.name, note, source, None)
    return {**link, "notes": notes, "placeholders": placeholders}


def built_rbd_link(links: list) -> dict | None:
    """Of a position's model rows, its own RBD: built from what's inside, or started there (New blank
    RBD); the one in use first; or None."""
    built = [x for x in links or [] if x.get("model_type") == "rbd" and ((x.get("source") or {}).get("built_from") is not None
                                                                     or (x.get("source") or {}).get("new"))]
    return next((x for x in built if x.get("in_use")), built[0] if built else None)


#: Keys of a position's diagram a mission's copy of it leaves behind (its missions and links).
_NOT_COPIED = ("phases", "missions", "mission_name", "mission_of")
#: What a repairable diagram has that a mission (non-repairable, phased) doesn't use: the diagram's
#: crews, groups and costs, and each block's repair, planned work and costs.
_REPAIR_DIAGRAM_KEYS = ("repairable", "repair_crews", "maintenance_groups", "costs")
_REPAIR_BLOCK_KEYS = ("repair", "instant_repair", "preventive", "inspection", "duty", "crew_priority",
                      "maintenance_group", "tree_settings", "tree_plan", "costs", "spares")


def _mission_source_rbd(m, fetch, position_id: str):
    """The position's own RBD a mission starts from: the one in use, else the one built there, else
    the first linked; never a network (a mission isn't flown on one). None where it has none."""
    links = [x for x in m.position_models(position_id) if x.get("model_type") == "rbd"]
    built = built_rbd_link(links)
    links.sort(key=lambda x: (not x.get("in_use"), x is not built))
    for x in links:
        doc = fetch("rbd", x["model_id"])
        if doc is not None and not (doc.graph or {}).get("network"):
            return doc
    return None


def _mission_copy(graph: dict) -> tuple[dict, bool]:
    """A copy of a position's diagram for a mission, wired as it is (redundancy stays redundancy):
    its missions left behind and, from a repairable diagram, its repairs and planned work (a phased
    mission is non-repairable). (graph, was repairable)."""
    repairable = bool((graph or {}).get("repairable"))
    drop = _NOT_COPIED + (_REPAIR_DIAGRAM_KEYS if repairable else ())
    out = {k: v for k, v in (graph or {}).items() if k not in drop}
    if repairable:
        out["nodes"] = [{**n, "data": {k: v for k, v in (n.get("data") or {}).items() if k not in _REPAIR_BLOCK_KEYS}}
                        if isinstance(n, dict) else n for n in out.get("nodes") or []]
    return out, repairable


def build_mission_rbd(m, db, owners, hidden, position_id: str, owner_id: str, name: str | None = None) -> dict:
    """A new mission on a position, with an RBD of its own (one RBD per mission). It starts from a
    copy of the position's own RBD where it has one (wired as drawn there: parallel trains, standby
    and k-of-n stay as they are; a repairable one loses only its repairs and planned work), else is
    built from what's inside the position as Build from what's inside builds (placeholders flagged,
    never a made-up figure; blocks with no connections or redundancy groups go in series, and the
    mission then says so until its RBD is rewired), else is one block, its own model in use
    (``built_from``: copy, tree or model).
    Saved once as "<position> — <mission>", marked ``mission_of`` the position (not linked as one
    of its models). {rbd: {id, name}, mission: summary, notes, placeholders}."""
    from backend.services import rbd_missions
    from backend.services import rbds as rbds_service
    from backend.services.rbd_graph import GraphError, normalize_graph

    sv = _sv()
    p = m._get(position_id, "Position")
    if p.get("retired"):
        raise sv.Invalid(f"{p['name']} has been retired: restore it first.")
    taken = {x["name"].casefold() for x in rbd_missions.own_missions(m, db, owners, position_id)}
    if name is not None and str(name).strip():
        try:
            name = rbd_missions._name(name)
        except rbd_missions.MissionError as exc:
            raise sv.Invalid(str(exc)) from None
        if name.casefold() in taken:
            raise sv.Invalid(f"{p['name']} already has a mission named “{name}”: give this one its own name.")
    else:
        k = len(taken) + 1
        while f"mission {k}" in taken:
            k += 1
        name = f"Mission {k}"
    kids = [c for c in m.s.inn(m.org, position_id, "PART_OF") if c["label"] == "Position" and not c.get("retired")]
    notes, placeholders, source = [], [], "tree"
    owner = {"position_id": position_id}
    src = _mission_source_rbd(m, fetcher(db, owners, hidden), position_id)
    if src is not None:
        graph, was_repairable = _mission_copy(src.graph or {})
        notes = [f"Started from a copy of {src.name}, wired as it is there"
                 + (" (its repairs and planned work aren't part of a mission)." if was_repairable else ".")]
        source = "copy"
    elif kids:
        graph, built, _, _, _ = _tree_graph(m, db, owners, hidden, position_id)
        notes, placeholders = built["notes"], built["placeholders"]
        if rbd_missions.all_in_series(graph) and not built.get("redundancy"):
            # The tree doesn't say which positions are redundant: said on the mission until it's rewired.
            owner["built_in_series"] = True
    else:
        source = "model"
        graph, note = _one_block_graph(m, db, owners, hidden, p)
        notes = [note] if note else []
    graph = {**graph, "mission_of": owner, "mission_name": name}
    try:
        graph = normalize_graph(graph, resolve_saved_model=lambda mid: fetcher(db, owners, hidden)("model", mid))
        rbd = rbds_service.save_rbd(db, f"{p['name']} — {name}"[:200], graph, owner_id)
    except GraphError as err:
        raise sv.Invalid(f"The mission's RBD couldn't be made: {err}") from None
    mission = rbd_missions.find(rbd.graph or graph, rbd_missions.LEGACY_ID)
    return {"rbd": {"id": rbd.id, "name": rbd.name, "updated_at": rbd.updated_at.isoformat() if rbd.updated_at else None},
            "mission": rbd_missions.summary(rbd.graph or graph, mission), "position_id": position_id,
            "notes": notes[:20], "placeholders": placeholders, "built_from": source,
            "series_warning": rbd_missions.series_warning(rbd.graph or graph)}


def _one_block_graph(m, db, owners, hidden, p: dict) -> tuple[dict, str | None]:
    """A leaf position's mission diagram: one block, the position's own model in use (as a block
    built from it would take it), In → block → Out. Raises Invalid when it has no model an RBD block
    can take (never a placeholder: there would be nothing to fly)."""
    from backend.maintenance import rbd_derive
    from backend.services.rbd_graph import wrap_layout

    sv = _sv()
    _, _, _, unit, block, _ = _tree_parts(m, db, owners, hidden, p["id"], with_self=True)
    fields, note = block(p)
    if fields is not None and ("subsystem_rbd_id" in fields or (fields.get("data") or {}).get("rbd")):
        raise sv.Invalid(f"{p['name']}'s RBD is repairable or a network, which a mission isn't flown on. Make it "
                         "non-repairable, or give the position a life model.")
    if fields is None:
        raise sv.Invalid(note or f"{p['name']} has nothing inside and no model in use to build the mission's RBD "
                                 "from. Give it a life model on the Modelling tab, or add the positions inside it.")
    bid = rbd_derive._bid(p["id"])
    graph = {"unit": unit, "nodes": [{"id": "in", "type": "input"}, {"id": "out", "type": "output"},
                                     {"id": bid, "type": "component", "label": p["name"], **fields}],
             "edges": [{"source": "in", "target": bid}, {"source": bid, "target": "out"}]}
    try:
        from backend.services.rbd_graph import normalize_graph

        graph = normalize_graph(graph, resolve_saved_model=lambda mid: fetcher(db, owners, hidden)("model", mid))
    except Exception as err:  # noqa: BLE001 - shown in words
        raise sv.Invalid(f"The mission's RBD couldn't be made: {err}") from None
    graph["nodes"] = wrap_layout(graph["nodes"])
    return graph, (note or f"One block: {p['name']}'s own model in use (it has no positions inside).")


def blockable_positions(m, db, owners, hidden, links: list) -> list[str]:
    """Of the positions in ``links`` (model rows, as all_position_models gives them), those whose
    model in use a mission's one-block RBD can take (a life distribution or a covariate model): the
    Missions tab offers Add a mission on such a leaf."""
    from backend.maintenance import covariate_positions

    fetch = fetcher(db, owners, hidden)
    out = []
    for x in links:
        if not x.get("in_use"):
            continue
        if covariate_positions.block_model(x) is not None:
            out.append(x["position_id"])
            continue
        d = fetch(x["model_type"], x["model_id"])
        if d is None:
            continue
        if x["model_type"] == "model" and d.kind in ("distribution", "regression"):
            out.append(x["position_id"])
    return sorted(set(out))


def _unrewired(graph: dict) -> bool:
    """A diagram still wired as a first build with nothing redundant: every block in series."""
    from backend.services import rbd_missions

    return rbd_missions.all_in_series(graph) and not any(
        n.get("type") in ("knode", "standby", "parallel") for n in graph.get("nodes") or [])


def _rewired(old: dict, fresh: dict, resolve) -> dict:
    """``fresh`` (the tree's wiring, normalised) with each block's settings from ``old`` where it
    was there (its model, repair, costs, planned work, Runs share), the diagram's own settings
    (repairable, crews, costs) kept."""
    from backend.services.rbd_graph import normalize_graph, wrap_layout

    had = {n.get("id"): n for n in old.get("nodes") or [] if isinstance(n, dict)}
    nodes = []
    for n in fresh.get("nodes") or []:
        before = had.get(n.get("id"))
        if before is not None and before.get("type") == n.get("type") == "component":
            data = {**(n.get("data") or {}), **(before.get("data") or {})}
            if (n.get("data") or {}).get("duty") and not (before.get("data") or {}).get("duty"):
                data["duty"] = n["data"]["duty"]
            n = {**n, "data": data}
        nodes.append({k: v for k, v in n.items() if k != "position"})
    keep = {k: v for k, v in old.items() if k not in ("nodes", "edges")}
    out = normalize_graph({**keep, "nodes": nodes, "edges": fresh.get("edges") or []}, resolve_saved_model=resolve)
    out["nodes"] = wrap_layout(out["nodes"])
    return out


def _add_new_blocks(old: dict, fresh: dict, resolve) -> dict:
    """The diagram as it was, with the positions inside that aren't blocks yet added in series
    before the output (their models as built); every edit to the rest is kept."""
    from backend.services.rbd_graph import normalize_graph, wrap_layout

    have = {n.get("id") for n in old.get("nodes") or []}
    new = [n for n in fresh.get("nodes") or [] if n.get("type") == "component" and n["id"] not in have]
    # A block still standing on a placeholder takes the model its position has now (nothing else
    # about it changes); a block given a model by hand is left as it is.
    found = {n["id"]: n for n in fresh.get("nodes") or [] if n.get("type") == "component"
             and not (n.get("model") or {}).get("placeholder")}
    filled = []
    for n in old.get("nodes") or []:
        d = n.get("data") or {}
        f = found.get(n.get("id"))
        if f is None or not (d.get("model") or {}).get("placeholder"):
            filled.append(n)
            continue
        d = {k: v for k, v in d.items() if k not in ("model", "rbd")}
        if f.get("model") is not None:
            d["model"] = f["model"]
        d.update((f.get("data") or {}))
        filled.append({**n, "type": f.get("type") or n.get("type"), "data": d})
    if not new and filled == list(old.get("nodes") or []):
        return old
    nodes = [{k: v for k, v in n.items() if k != "position"} for n in filled] + new
    edges = [{"source": e.get("source"), "target": e.get("target")} for e in old.get("edges") or []]
    for b in new:
        into_out = [e for e in edges if e["target"] == "out"]
        edges = [e for e in edges if e["target"] != "out"] + [{"source": e["source"], "target": b["id"]} for e in into_out]
        edges.append({"source": b["id"], "target": "out"})
    out = normalize_graph({**{k: v for k, v in old.items() if k not in ("nodes", "edges")}, "nodes": nodes,
                           "edges": edges}, resolve_saved_model=resolve)
    out["nodes"] = wrap_layout(out["nodes"])
    return out


def link_rbd(m, db, owners, hidden, position_id: str, rbd_id: str, note: str = "",
             replace_link_id: str | None = None) -> dict:
    """Link an existing RBD (the reader's, or a sample) to a position, as it is."""
    sv = _sv()
    doc = fetcher(db, owners, hidden)("rbd", str(rbd_id or ""))
    if doc is None:
        raise sv.NotFound(f"RBD {rbd_id}")
    return m.link_position_model(position_id, "rbd", doc.id, "rbd", None, doc.name, note, None, replace_link_id)
