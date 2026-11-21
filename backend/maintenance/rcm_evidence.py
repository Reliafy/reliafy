"""The evidence an RCM decision can rest on, found from where the decision is (Nov 2026).

A decision's rationale starts with nothing linked ("None linked") and stays so until the user
links something. Linking means finding it: the picker asks :func:`candidates` for what is
relevant to the failure mode's position, ranked

1. for this failure mode (a model attached for it, a report naming it),
2. on this position (its life models, the analyses run on them or for it, its failure history,
   its condition readings, its failure reports),
3. from its class (the class's fitted model and pooled history, and analyses run on it),
4. elsewhere in the library (other saved analyses of the kind the decision expects),

searchable (``q``) and filterable by kind. Nothing here links anything.

Three of the kinds live on the maintenance graph, not in a collection: a failure history (a
position's, or ``class:<key>`` for a class's pooled one), a measuring point (its readings) and a
failure report. They're linked, not checked (rcm_decisions.GRAPH_TYPES); the read hands each
over as the decision's ``linked`` ({name, path, summary}, :func:`graph_ref`), or None once gone.

A fit or a history may rest on part of the record only: ``window`` {since, until} bounds the
fitment start dates (:func:`in_window`), so "lives fitted since 2022" can be fitted
(position_models.fit_position_model) and linked with the window kept beside it.
"""

from __future__ import annotations

from backend.maintenance import rcm_decisions

#: The kinds of evidence the picker lists, in its filter's order.
KINDS = ("model", "analysis", "history", "readings", "failure_report", "degradation_model")
KIND_WORDS = {"model": "Life models", "analysis": "Saved analyses", "history": "Failure history",
              "readings": "Condition readings", "failure_report": "Failure reports",
              "degradation_model": "Degradation models"}
#: Where a candidate is from, best first.
SCOPES = ("mode", "position", "class", "library")
SCOPE_WORDS = {"mode": "For this failure mode", "position": "On this position", "class": "From its class",
               "library": "Elsewhere in your library"}
MAX_CANDIDATES = 200
_CLASS = "class:"


def missing_words(etype: str) -> str:
    return {"history": "Evidence of type history names a position on this tree (its id), or class:<class> for a "
                       "class's pooled history; there's no such history here.",
            "point": "Evidence of type point names a measuring point on this tree (its id); there's no such point "
                     "here.",
            "failure_report": "Evidence of type failure_report names a failure report on this tree (its id); "
                              "there's no such report here."}[etype]


def in_window(rows: list[dict], window: dict | None) -> list[dict]:
    """The rows whose fitment started inside ``window`` ({since?, until?}, ISO days, both inclusive)."""
    if not window:
        return rows
    since, until = window.get("since"), window.get("until")
    return [r for r in rows if (not since or str(r.get("from") or "") >= since)
            and (not until or str(r.get("from") or "") <= until)]


def _counts(rows: list[dict]) -> tuple[int, int]:
    return len(rows), sum(1 for r in rows if r.get("c") != 1)


def _history_rows(m, hid: str) -> tuple[list[dict], str, str] | None:
    """(rows, name, path) of a history: a position's, or a class's pooled one; None when it's gone."""
    if hid.startswith(_CLASS):
        key = hid[len(_CLASS):]
        try:
            got = m.class_life_data(key)
        except Exception:  # noqa: BLE001 - a class with no positions left: gone
            return None
        label = got.get("position_class") or key
        return got["rows"], f"{label} (class): pooled failure history", "/asset-register/explorer?arrange=classes"
    p = m.s.node(m.org, hid, "Position")
    if p is None or p.get("retired"):
        return None
    return m.life_data(hid), f"{p['name']}: failure history", f"/asset-register/explorer?tab=history&sel={hid}"


def graph_ref(m, evidence: dict) -> dict | None:
    """{name, path, summary} of a linked failure history, measuring point or failure report, or None
    once it has gone (deleted, retired or rejected)."""
    etype, eid = evidence.get("type"), str(evidence.get("id") or "")
    if not eid:
        return None
    if etype == "history":
        got = _history_rows(m, eid)
        if got is None:
            return None
        rows, name, path = got
        window = evidence.get("window")
        lives, failed = _counts(in_window(rows, window))
        if window:
            summary = rcm_decisions.window_words({**window, "lives": lives, "failures": failed})
        else:
            summary = f"{lives:,} li{'fe' if lives == 1 else 'ves'}, {failed:,} failed"
        return {"name": name, "path": path, "summary": summary}
    if etype == "point":
        mp = m.s.node(m.org, eid, "MeasurementPoint")
        if mp is None or mp.get("retired"):
            return None
        view = m.point(eid)
        on = (m.s.out(m.org, eid, "ON") or [None])[0]
        where = on["id"] if on else ""
        last = (f"last {view['reading']:g}{(' ' + view['unit']) if view.get('unit') else ''}"
                if isinstance(view.get("reading"), (int, float)) else "no readings yet")
        return {"name": f"{mp['name']} readings", "path": f"/asset-register/explorer?tab=measurements&sel={where}",
                "summary": last}
    if etype == "failure_report":
        r = m.s.node(m.org, eid, "FailureReport")
        if r is None or r.get("removed"):
            return None
        label = f"FR-{r.get('number')}" if r.get("number") is not None else "Failure report"
        return {"name": f"{label}: {r.get('title') or ''}".strip(": "),
                "path": f"/asset-register/explorer?tab=reports&sel={r.get('position_id') or ''}&report={eid}",
                "summary": f"occurred {r.get('occurred_on') or 'on a day not given'}, {r.get('status') or ''}".rstrip(", ")}
    return None


def _model_meta(doc) -> str:
    if doc is None:
        return ""
    parts = [str(getattr(doc, "distribution_id", "") or "").replace("_", " ").capitalize()]
    results = getattr(doc, "results", None) or {}
    n, f = results.get("n"), results.get("n_failures") or results.get("failures")
    if isinstance(n, int):
        parts.append(f"{n:,} lives" + (f", {f:,} failed" if isinstance(f, int) else ""))
    return " · ".join(p for p in parts if p)


def candidates(m, db, owners, hidden, position_id: str, mode_id: str | None = None, q: str = "",
               kind: str | None = None, limit: int = MAX_CANDIDATES) -> dict:
    """What a decision on ``position_id`` (for ``mode_id``) could link as its evidence, best first:
    {position, mode, class, kinds: [{id, label, count}], candidates: [{type, id, kind, label, meta,
    scope, scope_words, window_ok}], total}. ``q`` matches the label and the words beside it; ``kind``
    (one of :data:`KINDS`) keeps one kind. Nothing is linked."""
    from backend.services import degradation as degradation_service
    from backend.services import models as models_service
    from backend.services import strategy_store

    sv_invalid = __import__("backend.maintenance.service", fromlist=["Invalid"]).Invalid
    if kind not in (None, "", *KINDS):
        raise sv_invalid(f"kind is one of {', '.join(KINDS)}.")
    p = m._get(position_id, "Position")
    mode = None
    if mode_id:
        node = m.s.node(m.org, mode_id, "FailureMode")
        if node is None:
            raise sv_invalid("That failure mode isn't on this tree.")
        mode = {"id": node["id"], "text": node.get("text") or ""}
    mode_words = (mode or {}).get("text", "").strip().lower()
    out: list[dict] = []
    seen: set = set()

    def add(etype, eid, ckind, label, meta, scope, **extra):
        key = (etype, eid)
        if key in seen:
            return
        seen.add(key)
        out.append({"type": etype, "id": eid, "kind": ckind, "label": label, "meta": meta, "scope": scope,
                    "scope_words": SCOPE_WORDS[scope], **extra})

    # Life (and degradation) models attached to the position, for this mode first.
    model_scope: dict[str, str] = {}
    for link in m.position_models(position_id):
        mtype = link.get("model_type")
        if mtype not in ("model", "degradation_model") or not link.get("model_id") or link["model_id"] in hidden:
            continue
        for_mode = bool(mode and mode["id"] in [x.get("id") for x in link.get("failure_modes") or []])
        scope = "mode" if for_mode else "position"
        if mtype == "model":
            doc = models_service.get_model(db, link["model_id"], owners)
            if doc is None:
                continue
            model_scope[doc.id] = scope
            source = link.get("source") or {}
            window = source.get("window")
            meta = " · ".join(x for x in (_model_meta(doc), rcm_decisions.window_words(window) if window else "",
                                          "in use" if link.get("in_use") else "") if x)
            add("model", doc.id, "model", doc.name, meta, scope, window=window or None)
        else:
            doc = degradation_service.get_model(db, link["model_id"], owners)
            if doc is not None:
                add("degradation_model", doc.id, "degradation_model", doc.name, "Degradation model", scope)
    class_model = m.class_model_of(position_id)
    if class_model and class_model.get("model_id") not in hidden:
        doc = models_service.get_model(db, class_model["model_id"], owners)
        if doc is not None:
            model_scope.setdefault(doc.id, "class")
            add("model", doc.id, "model", doc.name,
                " · ".join(x for x in (_model_meta(doc), f"the {class_model['position_class']} class's model") if x),
                "class")

    # Saved analyses: run on one of these models, or for this position, then the rest of the kinds an
    # interval or a run-to-failure decision takes.
    for a in strategy_store.list_analyses(db, owners, hidden):
        inputs = a.inputs or {}
        scope = model_scope.get(str(inputs.get("model_id") or ""))
        if scope is None and inputs.get("position_id") == position_id:
            scope = "position"
        if scope is None:
            if a.kind not in ("optimal_replacement", "failure_finding", "failure_finding_interval",
                              "on_condition_interval"):
                continue
            scope = "library"
        on = inputs.get("model_name")
        meta = " · ".join(x for x in (strategy_store.headline(a), f"on {on}" if on else "") if x)
        add("strategy_analysis", a.id, "analysis", a.name, meta, scope)

    # The failure history: the position's own, and its class's pooled one.
    rows = m.life_data(position_id)
    if rows:
        lives, failed = _counts(rows)
        first = min(str(r.get("from") or "") for r in rows)
        add("history", position_id, "history", f"{p['name']}: failure history",
            f"{lives:,} li{'fe' if lives == 1 else 'ves'}, {failed:,} failed, fitted since {first}", "position",
            window_ok=True)
    key = m._class_key(p)
    if key:
        try:
            pooled = m.class_life_data(key)
        except Exception:  # noqa: BLE001 - a class with no history
            pooled = None
        if pooled and pooled.get("rows"):
            lives, failed = _counts(pooled["rows"])
            add("history", _CLASS + key, "history", f"{pooled.get('position_class') or key} (class): pooled failure history",
                f"{lives:,} lives, {failed:,} failed, across its positions", "class", window_ok=True)

    # Condition readings on the position (a counter is a clock, not a condition).
    for point in m._points_on(position_id):
        if point.get("kind") == "counter":
            continue
        n = len(point.get("readings") or [])
        last = (f"last {point['reading']:g}{(' ' + point['unit']) if point.get('unit') else ''}"
                if isinstance(point.get("reading"), (int, float)) else "no readings yet")
        add("point", point["id"], "readings", f"{point['name']} readings",
            f"{n:,} recent reading{'' if n == 1 else 's'}, {last}", "position")

    # Failure reports on it and inside it: those naming this failure mode first.
    got = m.failure_reports(position_id=position_id, below=True, limit=100)
    for r in got.get("reports") or got.get("items") or []:
        fm = r.get("failure_mode") or {}
        fm_id = fm.get("id") if isinstance(fm, dict) else None
        fm_text = (fm.get("text") if isinstance(fm, dict) else fm) or ""
        for_mode = bool(mode and (fm_id == mode["id"] or (mode_words and fm_text.strip().lower() == mode_words)))
        label = f"{r.get('label') or 'FR'}: {r.get('title') or ''}".strip(": ")
        where = (r.get("position") or {}).get("name") if isinstance(r.get("position"), dict) else ""
        meta = " · ".join(x for x in (r.get("occurred_on"), r.get("status"), where, fm_text) if x)
        add("failure_report", r["id"], "failure_report", label, meta, "mode" if for_mode else "position")

    counts = {k: sum(1 for c in out if c["kind"] == k) for k in KINDS}
    words = " ".join(str(q or "").casefold().split())
    shown = [c for c in out if (not kind or c["kind"] == kind)
             and (not words or all(w in f"{c['label']} {c['meta']}".casefold() for w in words.split()))]
    shown.sort(key=lambda c: (SCOPES.index(c["scope"]), KINDS.index(c["kind"])))
    class_view = {"key": key, "name": m._class_label(key)} if key else None
    return {"position": {"id": p["id"], "name": p["name"]}, "mode": mode, "class": class_view,
            "kinds": [{"id": k, "label": KIND_WORDS[k], "count": counts[k]} for k in KINDS if counts[k]],
            "candidates": shown[:max(1, min(int(limit or MAX_CANDIDATES), MAX_CANDIDATES))], "total": len(shown)}
