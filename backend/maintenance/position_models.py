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
MODEL_TYPES = ("model", "recurrent_model", "degradation_model", "alt_model")
#: How a model came to the position: chosen from the library, fitted from history,
#: the position class's model, copied from the product design it was built from, or a
#: Bayesian update of a baseline with its history (backend/services/bayes_life.py).
ROLES = ("assigned", "fitted", "class", "design", "bayesian", "prediction")
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


PROJECTORS = {
    "position.model_linked": _model_linked,
    "position.model_unlinked": _model_unlinked,
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
        """The models attached to a position, oldest first."""
        self._get(position_id, "Position")
        return [self._model_link_view(x) for x in self._model_links(position_id)]

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

    getters = {"model": models_service.get_model, "recurrent_model": recurrent_service.get_model,
               "degradation_model": degradation_service.get_model, "alt_model": alt_service.get_model}
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
    r = dict(getattr(doc, "results", None) or {})
    unit = r.get("unit") or ""
    out = {"name": doc.name, "unit": unit, "family": "life", "kind": "", "numbers": [], "counts": {},
           "quality": _quality(None, "life"), "path": None, "trend": None}
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


def describe(m, db, owners, hidden, links: list[dict]) -> list[dict]:
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
        model = summary(link["model_type"], doc) if doc is not None else None
        text = (model or {}).get("bayes_source") or source_text(link)
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
    """The plot's lines: reliability and hazard over time, with the reliability's 95%
    bounds where the model has them."""
    r = dict(doc.results or {})
    if model_type == "model" and doc.kind == "joint":
        s = r.get("survival_new") or {}
        if s.get("x") and s.get("sf"):
            return {"x": s["x"], "sf": s["sf"], "sf_lower": s.get("sf_lower"), "sf_upper": s.get("sf_upper"),
                    "hf": None, "what": "Reliability of a new unit"}
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
                out["band"] = {"kind": "confidence", "level": 0.95}
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
                    out["band"] = {"kind": "confidence", "level": 0.95}
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
    if role == "prediction":
        env = src.get("environment_name") or src.get("environment") or ""
        return f"Predicted from its parts list (parts count{', ' + env if env else ''})"
    return f"Assigned: {link.get('name') or 'a saved model'}"


def detail(m, db, owners, hidden, link_id: str) -> dict:
    """One link in full, for the panel: the model's summary, its parameters with bounds,
    the plot's lines, the data behind it (counts, unit, where time starts), what uses it
    and the notes."""
    link = m.model_link(link_id)
    [row] = describe(m, db, owners, hidden, [link])
    doc = fetcher(db, owners, hidden)(link["model_type"], link["model_id"])
    pos = m.s.node(m.org, link["position_id"], "Position") or {}
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
            "stress_note": ("Shown as fitted. The stress (or covariates) at this position is set where the model is "
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
            raise sv.Invalid(f"Pick a baseline: {p['name']} has no class model to start from.")
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
# components; consumables aren't in it), or a product design's bill of materials where its
# positions list none. Each part takes a handbook part type (MIL-HDBK-217F base rate) and a
# quality factor; the environment is set once on the position (default: the nearest position
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


def prediction_lines(m, position_id: str, assign: dict | None = None, previous: dict | None = None) -> dict:
    """The parts-count lines for a position: {lines (each with part_id), source ("parts lists" or
    "bill of materials"), positions, warnings}. ``assign`` {part id or part number: {record_id,
    quality_factor}} and ``previous`` (the last prediction's, by part number) give part types."""
    from backend.services import reliability_prediction as rp

    root = m._get(position_id, "Position")
    previous = previous or {}
    lines, warnings, n = [], [], 0
    for pid, path in _branch(m, position_id):
        n += 1
        for x in m._listings_at(pid):
            view = m._listing_view(x)
            if view["role"] not in PREDICTION_ROLES:
                continue
            part = view["part"]
            ref = part.get("part_number") or ""
            a = _assigned(assign, previous, part["id"], ref)
            lines.append({"part_id": part["id"], "name": part.get("name") or ref or "Part", "reference": ref,
                          "quantity": view.get("quantity") or 1, "assembly": list(path),
                          "record_id": a.get("record_id") or None, "quality_factor": a.get("quality_factor") or 1.0})
    source = "parts lists"
    if not lines and root.get("design"):
        bom = rp.lines_from_product(m, position_id)
        warnings += bom.get("warnings") or []
        for ln in bom.get("lines") or []:
            a = _assigned(assign, previous, None, ln.get("reference"))
            lines.append({**ln, "part_id": None, "record_id": a.get("record_id") or None,
                          "quality_factor": a.get("quality_factor") or 1.0})
        source = "bill of materials"
    return {"lines": lines, "source": source, "positions": n, "warnings": warnings,
            "position": {"id": root["id"], "name": root["name"]}}


def _prediction_links(m, position_id: str) -> list[dict]:
    return [x for x in m.position_models(position_id) if x.get("role") == "prediction"]


def default_environment(m, position_id: str) -> str:
    """The environment a new prediction starts from: this position's last, else the nearest
    position above with one, else the handbook's default."""
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
    return rp.DEFAULT_ENVIRONMENT


def _previous_types(db, owners, m, position_id: str) -> dict:
    """The part types the position's last prediction used, by part number."""
    from backend.services import reliability_prediction as rp

    out = {}
    for x in _prediction_links(m, position_id):
        doc = rp.get_prediction(db, (x.get("source") or {}).get("prediction_id") or "", owners)
        for ln in ((doc.inputs or {}).get("lines") if doc else None) or []:
            if ln.get("reference") and ln.get("record_id"):
                out[ln["reference"]] = {"record_id": ln["record_id"], "quality_factor": ln.get("quality_factor") or 1.0}
    return out


def predict_position(m, db, owners, hidden, position_id: str, environment: str | None = None,
                     mission_time=None, assign: dict | None = None, save: bool = False, note: str = "",
                     replace_link_id: str | None = None, owner_id: str | None = None) -> dict:
    """The parts count for a position: previewed (``save`` false: the lines with their part
    types, the environment and the result), or saved as a prediction and an exponential model and
    attached (role prediction; an earlier prediction on the position is replaced)."""
    from backend.db import to_doc
    from backend.schema import ReliabilityPrediction
    from backend.services import models as models_service
    from backend.services import reliability_prediction as rp

    sv = _sv()
    p = m._get(position_id, "Position")
    if p.get("retired"):
        raise sv.Invalid(f"{p['name']} has been retired: restore it first.")
    env = environment or default_environment(m, position_id)
    got = prediction_lines(m, position_id, assign, _previous_types(db, owners, m, position_id))
    if not got["lines"]:
        raise sv.Invalid(f"{p['name']} has no parts list (nor anything inside it): add the parts it's made of to its "
                         "parts list first.")
    raw = {"environment": env, "mission_time": mission_time, "notes": note or "",
           "lines": [{k: v for k, v in ln.items() if k != "part_id"} for ln in got["lines"]]}
    try:
        inputs = rp.normalise_inputs(raw)
        results = rp.results_for(inputs)
    except rp.PredictionError as err:
        raise sv.Invalid(str(err)) from None
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
        notes=f"A MIL-HDBK-217F parts count of {p['name']}'s parts list in {env_info.get('name') or inputs['environment']}.")
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
