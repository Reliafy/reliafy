"""A covariate model at a position, with some, all or none of its covariates fixed there
(Derryn, 9 Nov 2026): an NSWC-11 covariate model, an accelerated life (ALT) model or a
proportional-hazards (PH) model. The binding (backend/services/covariate_binding.py) is kept on the
link's source; what the position leaves open is set where the model is used: a block of an RBD
built from the tree, or the diagram's Use and Environment values.

* NSWC-11, every covariate fixed: a plain constant-rate model (an exponential at its rate per hour,
  saved to Models and cited), linked with role library.
* NSWC-11, some open: the record itself (model type ``covariate_record``), with the binding.
* ALT and PH: the saved model as it is, with the binding (every stress fixed is a plain
  constant-stress model). A link with no binding works as it always has.
"""

from __future__ import annotations

from types import SimpleNamespace

MODEL_TYPE = "covariate_record"


def _sv():
    from backend.maintenance import service

    return service


def record_doc(db, record_id: str, owners=None):
    """An NSWC-11 record as a model a link can name (the fetcher's ``covariate_record``), or None."""
    from backend.library import service as library

    try:
        rec = library.get(str(record_id or ""))
    except library.LibraryNotFound:
        return None
    if rec.get("kind") != "covariate_model":
        return None
    return SimpleNamespace(id=rec["id"], name=rec["label"], kind="covariate", results={"unit": "Hours"}, spec={},
                           dataset_id="", record=rec)


def summary(doc) -> dict:
    """The record in a row of the Modelling tab."""
    from backend.library import covariate

    rec = doc.record
    return {"name": doc.name, "unit": "Hours", "family": "life", "kind": "Covariate model (NSWC-11)",
            "numbers": [{"id": "reference", "label": "rate", "text": covariate.rate_unit_words(rec)}],
            "counts": {}, "quality": {"word": "Predicted", "tone": "neutral",
                                      "why": "A handbook covariate model: no failure data behind it, and no bounds."},
            "path": "/models/library/" + rec["id"].replace(":", "/", 1), "trend": None,
            "covariate_words": "covariate model"}


def binding_words(binding: dict, inputs: list[dict]) -> str:
    """'3 of 14 covariates fixed here; the rest set where it's used'."""
    fixed = len([i for i in inputs if i["key"] in (binding.get("fixed") or {})])
    if fixed == len(inputs):
        return f"every covariate fixed here ({fixed})"
    return f"{fixed} of {len(inputs)} covariates fixed here; the rest set where it's used"


def bind(m, db, owner_id: str, owners, position_id: str, binding, failure_mode_ids=None, note: str = "",
         replace_link_id: str | None = None) -> dict:
    """Link a covariate model to the position with the covariates ``binding`` fixes (some, all or
    none). Raises Invalid for a binding that can't be used."""
    from backend.services import covariate_binding as cb

    sv = _sv()
    try:
        b = cb.normalise(binding, db, owners)
        inputs = cb.inputs_of(b, db, owners)
    except cb.BindingError as exc:
        raise sv.Invalid(str(exc)) from None
    open_ = [i for i in inputs if i["key"] not in b["fixed"]]
    words = binding_words(b, inputs)
    source = {"binding": b, "binding_words": words}
    if b["source"] == "nswc":
        from backend.maintenance import library_models

        rec = library_models.record(b["ref"], db, owners)
        brief = library_models.brief(rec)
        source["library"] = {"record_id": rec["id"], "source": brief.get("source"), "label": brief.get("label"),
                             "citation": brief.get("citation")}
        if not open_:
            return _constant_nswc(m, db, owner_id, position_id, rec, b, source, failure_mode_ids, note,
                                  replace_link_id)
        return m.link_position_model(position_id, MODEL_TYPE, rec["id"], "library", failure_mode_ids, rec["label"],
                                     note, source, replace_link_id)
    from backend.maintenance.position_models import fetcher

    model_type = "alt_model" if b["source"] == "alt" else "model"
    doc = fetcher(db, owners)(model_type, b["ref"])
    if doc is None:
        raise sv.NotFound(f"Model {b['ref']}")
    return m.link_position_model(position_id, model_type, doc.id, "assigned", failure_mode_ids, doc.name, note,
                                 source, replace_link_id)


def _constant_nswc(m, db, owner_id, position_id, rec, b, source, failure_mode_ids, note, replace_link_id):
    """Every covariate fixed: the model is a constant rate at this position, saved as an exponential."""
    from backend.services import covariate_binding as cb
    from backend.services import models as models_service

    sv = _sv()
    try:
        made = cb.concrete(b, b["fixed"], "hours")
    except cb.BindingError as exc:
        raise sv.Invalid(str(exc)) from None
    rate = made["params"][0]["value"]
    p = m._get(position_id, "Position")
    name = f"{rec['name']} at {p['name']} (NSWC-11)"[:200]
    from backend.library import service as library

    disclaimer = (library._library()["sources"].get(rec["source"]) or {}).get("disclaimer") or ""
    model = models_service.import_model(
        db, owner_id, name, "exponential", unit="Hours", params=[{"name": "failure_rate", "value": rate}],
        notes=f"NSWC-11 {rec['source_code']} with every covariate fixed at {p['name']}. {disclaimer}".strip())
    db.models.update_one({"_id": model.id}, {"$set": {"results.method": "library", "spec.library_record_id": rec["id"],
                                                      "results.covariate_binding": b}})
    return m.link_position_model(position_id, "model", model.id, "library", failure_mode_ids, model.name, note,
                                 {**source, "rate_per_hour": rate}, replace_link_id)


def block_model(link: dict):
    """The RBD block a bound link becomes: ``{"model": {"kind": "bound", ...}}``, or None when the
    link isn't bound (or is a constant-rate NSWC-11 model, a plain saved model)."""
    b = (link.get("source") or {}).get("binding")
    if not isinstance(b, dict):
        return None
    if b.get("source") == "nswc" and link.get("model_type") == "model":
        return None  # every covariate fixed: the saved exponential
    return {"model": {"kind": "bound", "binding": b, "name": link.get("name")}}


def prediction_conditions(m, position_id: str, record_id: str) -> dict | None:
    """The covariates a position fixes for an NSWC-11 record (a parts-count line on that record
    starts from them), or None."""
    for x in m.position_models(position_id):
        b = (x.get("source") or {}).get("binding") or {}
        if b.get("source") == "nswc" and b.get("ref") == record_id and b.get("fixed"):
            return dict(b["fixed"])
    return None
