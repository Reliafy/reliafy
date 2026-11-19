"""A position's failure rate, one figure read by every tab that needs one.

The FME(C)A's criticality and the RBD built from the tree once each took a rate
of their own (a motor: 30 per million hours in the parts count, 80 typed in the
FME(C)A, 1,000 as an RBD placeholder). They now read the position's rate from
here, and say where it came from (plan row Q13, 10 Nov 2026; W3, 19 Nov):

1. its model in use, when that is a constant rate (exponential): "parts count"
   for a parts-count prediction, else "fitted model" or "assigned model";
2. else the parts count: the parts on the position's parts list (replacement
   parts and components, as the parts count counts them), each at its part
   number's rate in the nearest saved parts count, on the position or the
   nearest position above it. Matched by part number, never by name (names
   repeat), as the maintainability prediction matches them. Every listed part
   must have a rate there; one with none (a propeller, left out as not
   electronic) leaves the position without a rate rather than a partial one.

None when there is no such rate: nothing is ever made up. A rate typed on a
failure mode stays the analyst's override and is shown as such beside this one.
Reads only; nothing is stored.
"""

from __future__ import annotations

PER_MILLION = 1e6
#: How far up the tree a parts count is looked for.
MAX_UP = 12
ROLE_WORDS = {"prediction": "parts count", "fitted": "fitted model", "bayesian": "fitted model",
              "class": "fitted model", "assigned": "assigned model", "design": "assigned model",
              "library": "assigned model"}


def _exp_rate(doc) -> float | None:
    """A saved model's constant failure rate per hour, or None (not exponential, or not in hours)."""
    from backend.units import normalize_unit

    if doc is None or getattr(doc, "kind", "distribution") not in ("distribution", None):
        return None
    r = doc.results or {}
    if (r.get("distribution_id") or getattr(doc, "distribution_id", None)) != "exponential":
        return None
    params = {p.get("name"): p.get("value") for p in r.get("params") or [] if isinstance(p, dict)}
    rate = params.get("failure_rate")
    unit = normalize_unit(r.get("unit") or "hours") or "hour"
    per = {"hour": 1.0, "day": 24.0, "week": 168.0, "month": 730.5, "year": 8766.0}.get(unit)
    try:
        rate = float(rate)
    except (TypeError, ValueError):
        return None
    if per is None or rate < 0:
        return None
    return rate / per


def _out(per_hour: float, source: str, text: str, **extra) -> dict:
    return {"per_hour": per_hour, "per_million_hours": per_hour * PER_MILLION, "source": source,
            "text": text, **extra}


def _fmt(x: float) -> str:
    return f"{x:,.3g}" if x < 1000 else f"{x:,.0f}"


def _prediction_doc(db, owners, pid: str) -> dict | None:
    from backend.services import reliability_prediction as rp

    doc = rp.get_prediction(db, pid, owners) if pid else None
    if doc is None:
        return None
    return {"_id": doc.id, "name": doc.name, "results": doc.results or {}}


def _nearest_parts_count(m, db, owners, position_id: str) -> tuple[dict, dict] | None:
    """(the position holding it {id, name}, its rates by part number): the nearest saved parts
    count on the position or above it."""
    from backend.services import maintainability

    pid, seen = position_id, set()
    while pid and pid not in seen and len(seen) < MAX_UP:
        seen.add(pid)
        node = m.s.node(m.org, pid, "Position")
        if node is None:
            return None
        for x in m.position_models(pid):
            if x.get("role") != "prediction":
                continue
            doc = _prediction_doc(db, owners, (x.get("source") or {}).get("prediction_id") or "")
            got = maintainability.rates_of(doc) if doc else None
            if got and got["rates"]:
                return {"id": node["id"], "name": node["name"]}, got
        parent = m._parent(pid)
        pid = parent["id"] if parent and parent.get("label") == "Position" else None
    return None


def parts_count_rate(m, db, owners, position_id: str) -> dict | None:
    """The position's rate from the parts count (step 2 above), or None."""
    from backend.maintenance.position_models import PREDICTION_ROLES
    from backend.services.maintainability import ref_key

    listed = []
    for x in m._listings_at(position_id):
        if x.get("role") not in PREDICTION_ROLES:
            continue
        part = (m.s.out(m.org, x["id"], "LISTS") or [None])[0]
        if part is None:
            continue
        try:
            qty = float(x.get("quantity") or 1)
        except (TypeError, ValueError):
            qty = 1.0
        listed.append((part, qty))
    if not listed:
        return None
    found = _nearest_parts_count(m, db, owners, position_id)
    if found is None:
        return None
    holder, got = found
    total, parts = 0.0, []
    for part, qty in listed:
        each = got["rates"].get(ref_key(part.get("part_number") or ""))
        if each is None:
            return None  # a part the parts count has no rate for: no partial figure
        total += each * qty
        parts.append({"part_number": part.get("part_number") or "", "name": part.get("name") or "",
                      "quantity": qty, "each_per_million_hours": each})
    names = ", ".join(_part_words(p) for p in parts)
    return _out(total / PER_MILLION, "parts count",
                f"From the parts count: {_fmt(total)} per million hours ({names}; {got['name']} on {holder['name']})",
                prediction={"id": got["id"], "name": got["name"]}, on=holder, parts=parts)


def _part_words(p: dict) -> str:
    name = p["name"] or p["part_number"]
    return name if p["quantity"] == 1 else f"{name} ×{p['quantity']:g}"


def position_rate(m, db, owners, position_id: str, fetch=None) -> dict | None:
    """The position's failure rate (per hour and per million hours), its ``source`` ("parts count",
    "fitted model" or "assigned model") and ``text`` saying where it came from; None when it has none."""
    if fetch is None:
        from backend.maintenance.position_models import fetcher

        fetch = fetcher(db, owners)
    x = m.in_use_link(position_id)
    if x is not None and x.get("model_type") == "model":
        rate = _exp_rate(fetch("model", x["model_id"]))
        if rate is not None:
            source = ROLE_WORDS.get(x.get("role"), "assigned model")
            what = "From the parts count" if source == "parts count" else f"From its {source}"
            return _out(rate, source, f"{what}: {_fmt(rate * PER_MILLION)} per million hours ({x.get('name') or 'its model'})",
                        model={"id": x["model_id"], "name": x.get("name") or ""})
    return parts_count_rate(m, db, owners, position_id)
