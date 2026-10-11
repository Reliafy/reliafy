"""What changed in a workspace over a period (#41): "what changed since last month?".

Every fact here is read from what Reliafy stores — timestamps, the refit and
forecast logs below, fleet alert firings and simulation runs — and compared by
fixed rules, never estimated. Where nothing is stored to compare against, the
summary says so in ``not_compared`` and leaves the part out.

What is compared, and from what:

* new and changed items: each artifact's ``created_at`` / ``updated_at``;
* refits whose answer moved: ``model_refits``, written by every refit of a
  saved life model (:func:`record_refit`, from ``models.update_fit``) with the
  fit's B10, MTTF and randomness verdict before and after — the engine's own
  numbers from the saved results, nothing recomputed;
* fleet forecasts whose expected failures moved: ``fleet_forecasts``, the
  expected failures each time a forecast is computed for the app or for usage
  arriving through the API (:func:`note_forecast`, at most one a day unless it
  changed), against the fleet's live forecast now;
* fleet alerts that fired: ``fleet_alert_events``;
* RCM evidence that changed: decisions whose linked life model was refitted
  in the period, with the evidence status before (where the stored fit
  decides it) and now;
* availability simulations whose answer moved: a diagram's newest finished run
  in the period against its newest before it (``rbd_jobs``, kept 7 or 90 days).

Scope follows the workspace's list rule (``AccessCtx.list_owners``): personal
is the user's own items, a team workspace is the team's. Shared samples and
items shared with the user are never part of it.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from backend.config import SAMPLE_OWNER

logger = logging.getLogger(__name__)

DEFAULT_DAYS = 30
MAX_DAYS = 366
# A refit's B10 or MTTF, or a fleet's expected failures, "moved" when it
# changed by more than this fraction of its earlier value.
MOVE_FRACTION = 0.10
# An availability "moved" when it changed by more than this (0.5 percentage points).
AVAILABILITY_POINTS = 0.005
# A new visit starts after this long without loading the app.
VISIT_GAP = timedelta(minutes=30)
# A forecast is logged at most this often while its value holds.
FORECAST_LOG_EVERY = timedelta(hours=24)
# The most rows of each kind returned (counts are always complete).
MAX_ROWS = 50
# Live forecasts recomputed for the comparison, per request.
MAX_FLEETS = 25
# Logs are kept this long.
LOG_DAYS = 800

# collection -> (label, url prefix)
COLLECTIONS = {
    "models": ("Life model", "/modelling/m/"),
    "recurrent_models": ("Repairable-system model", "/modelling/recurrent/"),
    "alt_models": ("Accelerated test model", "/modelling/alt/"),
    "degradation_models": ("Degradation model", "/modelling/degradation/"),
    "datasets": ("Dataset", "/datasets/d/"),
    "rbds": ("Block diagram", "/rbds/b/"),
    "fleets": ("Failure forecast", "/fleet/forecasts/"),
    "tracked_fleets": ("Tracked fleet", "/fleet/tracking/"),
    "rcm_studies": ("RCM study", "/rcm/studies/"),
    "strategy_analyses": ("Strategy analysis", "/strategy/analyses/"),
}

NOT_COMPARED = [
    {"what": "Failures recorded against the forecast",
     "why": "Failure forecasts store each item's use, not the failures it had, so actual failures "
            "can't be set against what was forecast."},
    {"what": "Other models' refits",
     "why": "Only life models keep their earlier answer when refitted. Repairable-system, accelerated "
            "test and degradation models keep just their latest fit."},
    {"what": "Block diagram answers other than availability simulations",
     "why": "Reliability, MTTF and the other diagram results are worked out when you open them and "
            "aren't kept, so earlier answers can't be compared. Simulation runs are kept 7 days "
            "(90 on Pro)."},
    {"what": "Strategy analyses and degradation models",
     "why": "A saved analysis keeps the result it was saved with and a degradation model isn't refitted "
            "in place, so they show as new or renamed, never as moved."},
]


class PeriodError(ValueError):
    """A period the summary can't use (HTTP 422)."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value):
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _iso(value):
    value = _aware(value)
    return value.isoformat() if value else None


def ensure_indexes(db) -> None:
    db.model_refits.create_index([("model_id", 1), ("at", 1)])
    db.model_refits.create_index([("owner_id", 1), ("at", -1)])
    db.model_refits.create_index([("at", 1)], expireAfterSeconds=LOG_DAYS * 24 * 3600)
    db.fleet_forecasts.create_index([("fleet_id", 1), ("at", -1)])
    db.fleet_forecasts.create_index([("at", 1)], expireAfterSeconds=LOG_DAYS * 24 * 3600)


# ---- Recording (hooks) ---------------------------------------------------------------

def _b_life(results: dict, label: str):
    for b in ((results.get("life") or {}).get("b_lives") or []):
        if b.get("label") == label:
            return b.get("value")
    return None


def fit_answer(results: dict | None) -> dict:
    """The headline of a saved fit, as stored: what a refit is compared on."""
    r = results or {}
    randomness = r.get("randomness") or None
    return {
        "kind": r.get("kind"),
        "distribution": r.get("distribution"),
        "distribution_id": r.get("distribution_id"),
        "n": r.get("n"),
        "unit": r.get("unit") or "",
        "b10": _b_life(r, "B10"),
        "mttf": ((r.get("life") or {}).get("mttf") or {}).get("value"),
        "randomness": randomness,
    }


def record_refit(db, model_id: str, owner_id: str, before_results, after_results, now=None) -> None:
    """Log one refit of a saved life model (best-effort: never fails the refit)."""
    try:
        if owner_id == SAMPLE_OWNER:
            return
        db.model_refits.insert_one({
            "_id": uuid.uuid4().hex,
            "model_id": model_id,
            "owner_id": owner_id,
            "at": now or _now(),
            "before": fit_answer(before_results),
            "after": fit_answer(after_results),
        })
    except Exception:  # noqa: BLE001
        logger.warning("refit log failed model=%s", model_id, exc_info=True)


def note_forecast(db, fleet, forecast: dict | None, now=None) -> None:
    """Log a fleet's expected failures from a forecast just computed, at most
    once a day while it holds (best-effort)."""
    try:
        if fleet is None or fleet.owner_id == SAMPLE_OWNER or not forecast:
            return
        if forecast.get("status") != "ok" or forecast.get("expected") is None:
            return
        expected = float(forecast["expected"])
        now = now or _now()
        last = db.fleet_forecasts.find_one({"fleet_id": fleet.id}, sort=[("at", -1)])
        if last is not None:
            same = abs(float(last.get("expected") or 0.0) - expected) <= 1e-9 * max(1.0, abs(expected))
            if same and now - _aware(last["at"]) < FORECAST_LOG_EVERY:
                return
        settings = fleet.settings or {}
        db.fleet_forecasts.insert_one({
            "_id": uuid.uuid4().hex,
            "fleet_id": fleet.id,
            "owner_id": fleet.owner_id,
            "at": now,
            "expected": expected,
            "periods": forecast.get("periods", settings.get("periods")),
            "period_label": forecast.get("period_label", settings.get("period_label")),
        })
    except Exception:  # noqa: BLE001
        logger.warning("forecast log failed fleet=%s", getattr(fleet, "id", None), exc_info=True)


def note_visit(db, uid: str, now=None) -> None:
    """On loading the app: when the last load was a visit ago, keep its time
    as the previous visit ("since my last visit")."""
    try:
        now = now or _now()
        doc = db.users.find_one({"_id": uid}, {"last_login": 1}) or {}
        last = _aware(doc.get("last_login"))
        if last is not None and now - last >= VISIT_GAP:
            db.users.update_one({"_id": uid}, {"$set": {"previous_visit_at": last}})
    except Exception:  # noqa: BLE001
        logger.debug("visit note failed", exc_info=True)


# ---- The period ----------------------------------------------------------------------

def _plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def _day(dt: datetime) -> str:
    return f"{dt.day} {dt.strftime('%b %Y')}"


def resolve_period(db, uid: str, since: str | None = None, days: int | None = None, now=None) -> dict:
    """``{"since", "until", "label", "kind"}`` for a request: ``since`` is
    ``last_visit`` or an ISO date/time; else ``days`` (default 30)."""
    now = now or _now()
    if since == "last_visit":
        doc = db.users.find_one({"_id": uid}, {"previous_visit_at": 1}) or {}
        visit = _aware(doc.get("previous_visit_at"))
        if visit is not None:
            return {"since": visit, "until": now, "kind": "last_visit",
                    "label": f"since your last visit ({_day(visit)})"}
        start = now - timedelta(days=DEFAULT_DAYS)
        return {"since": start, "until": now, "kind": "days", "days": DEFAULT_DAYS,
                "label": f"in the last {DEFAULT_DAYS} days",
                "note": "No earlier visit is recorded yet, so this covers the last 30 days."}
    if since:
        start = _aware(since.strip())
        if start is None:
            raise PeriodError("since must be 'last_visit' or a date like 2026-09-01.")
        if start >= now:
            raise PeriodError("since must be in the past.")
        if now - start > timedelta(days=MAX_DAYS):
            raise PeriodError(f"since can go back at most {MAX_DAYS} days.")
        return {"since": start, "until": now, "kind": "date", "label": f"since {_day(start)}"}
    n = DEFAULT_DAYS if days is None else int(days)
    if not 1 <= n <= MAX_DAYS:
        raise PeriodError(f"days must be between 1 and {MAX_DAYS}.")
    return {"since": now - timedelta(days=n), "until": now, "kind": "days", "days": n,
            "label": "in the last day" if n == 1 else f"in the last {n} days"}


# ---- The summary ---------------------------------------------------------------------

def _scope(list_owners) -> list[str]:
    owners = [list_owners] if isinstance(list_owners, str) else list(list_owners or [])
    return [o for o in owners if o and o != SAMPLE_OWNER]


def _in_period(value, since, until) -> bool:
    value = _aware(value)
    return value is not None and since <= value <= until


def _who(doc: dict, uid: str):
    by = doc.get("updated_by") or {}
    if not by or by.get("uid") == uid:
        return None
    return by.get("name")


def _items(db, owners, since, until, uid) -> tuple[list, list, dict]:
    """New and changed items, newest first, and every in-scope id by collection."""
    new, changed = [], []
    ids: dict[str, dict[str, dict]] = {}
    for coll, (label, prefix) in COLLECTIONS.items():
        ids[coll] = {}
        for doc in db[coll].find({"owner_id": {"$in": owners}},
                                 {"name": 1, "created_at": 1, "updated_at": 1, "updated_by": 1,
                                  "functions": 1}):
            ids[coll][doc["_id"]] = doc
            created, updated = _aware(doc.get("created_at")), _aware(doc.get("updated_at"))
            row = {"collection": coll, "type": label, "id": doc["_id"], "name": doc.get("name") or "Untitled",
                   "url": prefix + doc["_id"]}
            if created and since <= created <= until:
                new.append({**row, "at": created.isoformat()})
            elif updated and since <= updated <= until and (created is None or updated > created):
                who = _who(doc, uid)
                changed.append({**row, "at": updated.isoformat(), **({"by": who} if who else {})})
    # Tracked fleets change when readings arrive on their items.
    tracked = ids["tracked_fleets"]
    if tracked:
        readings: dict[str, list] = {}
        for item in db.tracked_items.find({"fleet_id": {"$in": list(tracked)}}, {"fleet_id": 1, "updated_at": 1}):
            at = _aware(item.get("updated_at"))
            if at is not None and since <= at <= until:
                readings.setdefault(item["fleet_id"], []).append(at)
        listed = {r["id"] for r in new + changed}
        for fid, stamps in readings.items():
            if fid in listed:
                continue
            doc = tracked[fid]
            changed.append({"collection": "tracked_fleets", "type": COLLECTIONS["tracked_fleets"][0], "id": fid,
                            "name": doc.get("name") or "Untitled", "url": COLLECTIONS["tracked_fleets"][1] + fid,
                            "at": max(stamps).isoformat(),
                            "detail": f"new readings on {_plural(len(stamps), 'item')}"})
    new.sort(key=lambda r: r["at"], reverse=True)
    changed.sort(key=lambda r: r["at"], reverse=True)
    return new, changed, ids


def _rel(before, after):
    try:
        b, a = float(before), float(after)
    except (TypeError, ValueError):
        return None
    if b == 0:
        return None if a == 0 else float("inf")
    return (a - b) / abs(b)


_VERDICT = {"random": "random", "wear_out": "wear-out", "infant_mortality": "infant mortality",
            "inconclusive": "inconclusive"}


def _verdict(answer: dict):
    return ((answer or {}).get("randomness") or {}).get("verdict")


def _refits(db, model_docs: dict, since, until) -> tuple[list, dict]:
    """Each model refitted in the period: its answer at the start (before its
    first refit in the period) against its answer now (after its last)."""
    if not model_docs:
        return [], {}
    by_model: dict[str, list] = {}
    for row in db.model_refits.find({"model_id": {"$in": list(model_docs)},
                                     "at": {"$gte": since, "$lte": until}}).sort("at", 1):
        by_model.setdefault(row["model_id"], []).append(row)
    out = []
    for mid, rows in by_model.items():
        before, after = rows[0].get("before") or {}, rows[-1].get("after") or {}
        moved = []
        for key, label in (("b10", "B10"), ("mttf", "MTTF")):
            change = _rel(before.get(key), after.get(key))
            if change is not None and abs(change) > MOVE_FRACTION:
                moved.append({"measure": label, "before": before.get(key), "after": after.get(key),
                              "change": None if change == float("inf") else change})
        if before.get("distribution_id") and after.get("distribution_id") and \
                before["distribution_id"] != after["distribution_id"]:
            moved.append({"measure": "Distribution", "before": before.get("distribution"),
                          "after": after.get("distribution")})
        if _verdict(before) and _verdict(after) and _verdict(before) != _verdict(after):
            moved.append({"measure": "Failure pattern", "before": _VERDICT.get(_verdict(before), _verdict(before)),
                          "after": _VERDICT.get(_verdict(after), _verdict(after))})
        comparable = any(before.get(k) is not None and after.get(k) is not None for k in ("b10", "mttf"))
        doc = model_docs[mid]
        out.append({
            "id": mid, "name": doc.get("name") or "Untitled", "url": COLLECTIONS["models"][1] + mid,
            "at": _iso(rows[-1]["at"]), "refits": len(rows), "unit": after.get("unit") or before.get("unit") or "",
            "before": {k: before.get(k) for k in ("distribution", "n", "b10", "mttf")},
            "after": {k: after.get(k) for k in ("distribution", "n", "b10", "mttf")},
            "moved": moved, "comparable": comparable or bool(moved),
        })
    out.sort(key=lambda r: r["at"] or "", reverse=True)
    out.sort(key=lambda r: not r["moved"])
    return out, by_model


def _forecasts(db, fleet_docs: dict, owners, since, until) -> tuple[list, int]:
    """Fleets whose expected failures moved: the forecast logged last before
    the period against the live forecast now. Returns (rows, fleets with no
    forecast logged before the period)."""
    from backend.db import from_doc
    from backend.schema import Fleet
    from backend.services import fleet as fleet_service

    out, unrecorded = [], 0
    for fid, doc in list(fleet_docs.items()):
        base = db.fleet_forecasts.find_one({"fleet_id": fid, "at": {"$lte": since}}, sort=[("at", -1)])
        if base is None:
            unrecorded += 1
            continue
        if len(out) >= MAX_FLEETS:
            break
        fleet = from_doc(Fleet, db.fleets.find_one({"_id": fid}))
        try:
            forecast = fleet_service.compute(db, fleet, [*owners, SAMPLE_OWNER, fleet.owner_id])
        except Exception:  # noqa: BLE001 - a fleet that can't be forecast is left out
            logger.warning("forecast for changes failed fleet=%s", fid, exc_info=True)
            continue
        if forecast.get("status") != "ok":
            continue
        note_forecast(db, fleet, forecast)
        now_value = float(forecast["expected"])
        change = _rel(base.get("expected"), now_value)
        label = (fleet.settings or {}).get("period_label", "months")
        out.append({
            "id": fid, "name": doc.get("name") or "Untitled", "url": COLLECTIONS["fleets"][1] + fid,
            "before": {"expected": base.get("expected"), "at": _iso(base["at"]),
                       "periods": base.get("periods"), "period_label": base.get("period_label")},
            "after": {"expected": now_value, "periods": forecast.get("periods"), "period_label": label},
            "change": None if change in (None, float("inf")) else change,
            "moved": change is not None and abs(change) > MOVE_FRACTION,
        })
    out.sort(key=lambda r: (not r["moved"], -abs(r["change"] or 0)))
    return out, unrecorded


def _alerts(db, fleet_docs: dict, since, until) -> list:
    from backend.db import from_doc
    from backend.schema import Fleet
    from backend.services import fleet_alerts

    if not fleet_docs:
        return []
    out = []
    fleets: dict = {}
    for ev in db.fleet_alert_events.find({"fleet_id": {"$in": list(fleet_docs)},
                                          "created_at": {"$gte": since, "$lte": until}}).sort("created_at", -1):
        fid = ev["fleet_id"]
        if fid not in fleets:
            fleets[fid] = from_doc(Fleet, db.fleets.find_one({"_id": fid}))
        rule = {k: ev.get(k) for k in ("kind", "threshold", "percent", "x", "y_periods")}
        try:
            title = fleet_alerts.render(fleets[fid], rule, ev.get("previous_value"), ev.get("baseline_value"),
                                        float(ev.get("new_value")), _aware(ev["created_at"]))["text"].split("\n")[0]
        except Exception:  # noqa: BLE001 - the firing stands without its sentence
            title = f"An alert on {fleet_docs[fid].get('name')} fired"
        out.append({"fleet_id": fid, "fleet": fleet_docs[fid].get("name"), "url": COLLECTIONS["fleets"][1] + fid,
                    "kind": ev.get("kind"), "at": _iso(ev["created_at"]), "text": title,
                    "previous_value": ev.get("previous_value"), "new_value": ev.get("new_value"),
                    "emailed": bool(ev.get("sent"))})
    return out


def _rcm(db, study_docs: dict, model_docs: dict, refit_rows: dict, owners) -> list:
    """Decisions whose linked life model was refitted in the period."""
    from backend.db import from_doc
    from backend.schema import RcmStudy
    from backend.services import rcm as rcm_service

    if not refit_rows:
        return []
    out = []
    for sid, sdoc in study_docs.items():
        study = None
        for fn in sdoc.get("functions") or []:
            for failure in fn.get("failures") or []:
                for mode in failure.get("modes") or []:
                    decision = mode.get("decision") or {}
                    evidence = decision.get("evidence") or {}
                    if evidence.get("type") != "model" or evidence.get("id") not in refit_rows:
                        continue
                    if study is None:
                        study = from_doc(RcmStudy, db.rcm_studies.find_one({"_id": sid}))
                        resolved = rcm_service.resolve(db, study, [*owners, SAMPLE_OWNER])
                        statuses = {m.get("id"): (m.get("decision") or {}).get("status")
                                    for f in resolved["functions"] for fl in f["failures"] for m in fl["modes"]}
                    rows = refit_rows[evidence["id"]]
                    before = None
                    if decision.get("outcome") == "rtf" and decision.get("rtf_basis") == "random":
                        prior = rows[0].get("before") or {}
                        before = rcm_service._check_randomness(
                            SimpleNamespace(results={"kind": prior.get("kind"),
                                                     "distribution_id": prior.get("distribution_id"),
                                                     "randomness": prior.get("randomness")})).get("status")
                    now_status = statuses.get(mode.get("id"))
                    model = model_docs.get(evidence["id"]) or {}
                    out.append({
                        "study_id": sid, "study": sdoc.get("name") or "Untitled",
                        "url": COLLECTIONS["rcm_studies"][1] + sid,
                        "mode": mode.get("text"), "outcome": decision.get("outcome"),
                        "evidence": model.get("name"), "evidence_url": COLLECTIONS["models"][1] + evidence["id"],
                        "at": _iso(rows[-1]["at"]), "status_before": before, "status": now_status,
                        "status_changed": before is not None and before != now_status,
                    })
    out.sort(key=lambda r: (not r["status_changed"], r["study"]))
    return out


def _availability(job):
    return (((job or {}).get("result") or {}).get("precision") or {}).get("window_availability")


def _runs(db, rbd_docs: dict, since, until) -> list:
    """Diagrams whose availability simulation moved between the newest run
    before the period and the newest in it."""
    if not rbd_docs:
        return []
    out = []
    query = {"kind": "availability", "status": "done", "rbd_id": {"$in": list(rbd_docs)}}
    latest: dict[str, dict] = {}
    counts: dict[str, int] = {}
    for job in db.rbd_jobs.find({**query, "finished_at": {"$gte": since, "$lte": until}},
                                {"rbd_id": 1, "finished_at": 1, "result.precision": 1}).sort("finished_at", -1):
        counts[job["rbd_id"]] = counts.get(job["rbd_id"], 0) + 1
        latest.setdefault(job["rbd_id"], job)
    for rid, job in latest.items():
        prior = db.rbd_jobs.find_one({**query, "rbd_id": rid, "finished_at": {"$lt": since}},
                                     {"finished_at": 1, "result.precision": 1}, sort=[("finished_at", -1)])
        now_a, before_a = _availability(job), _availability(prior)
        doc = rbd_docs[rid]
        moved = now_a is not None and before_a is not None and abs(now_a - before_a) > AVAILABILITY_POINTS
        out.append({
            "id": rid, "name": doc.get("name") or "Untitled", "url": COLLECTIONS["rbds"][1] + rid,
            "runs": counts[rid], "at": _iso(job.get("finished_at")), "run_id": job["_id"],
            "before": None if prior is None else {"availability": before_a, "at": _iso(prior.get("finished_at")),
                                                  "run_id": prior["_id"]},
            "after": {"availability": now_a},
            "moved": moved,
            "diagram_changed": _in_period(doc.get("updated_at"), since, until),
        })
    out.sort(key=lambda r: (not r["moved"], r["name"]))
    return out


def _sentence(label: str, counts: dict) -> str:
    """One plain sentence, most important first: alerts, answers that moved,
    RCM evidence, then items added and changed."""
    parts = []
    if counts["alerts"]:
        parts.append(_plural(counts["alerts"], "fleet alert") + " fired")
    kinds = [(counts["refits_moved"], "refit"), (counts["forecasts_moved"], "forecast"),
             (counts["runs_moved"], "simulation")]
    kinds = [(n, word) for n, word in kinds if n]
    if len(kinds) == 1:
        n, word = kinds[0]
        parts.append(_plural(n, word) + (" moved its answer" if n == 1 else " moved their answers"))
    elif kinds:
        total = sum(n for n, _ in kinds)
        parts.append(f"{total} answers moved ({', '.join(_plural(n, word) for n, word in kinds)})")
    if counts["rcm_evidence"]:
        parts.append("evidence changed on " + _plural(counts["rcm_evidence"], "RCM decision"))
    if counts["new"]:
        parts.append(_plural(counts["new"], "item") + (" was added" if counts["new"] == 1 else " were added"))
    if counts["changed"]:
        parts.append(f"{counts['changed']} changed" if counts["new"] else _plural(counts["changed"], "item") + " changed")
    if not parts:
        return f"Nothing changed {label}."
    lead = label[0].upper() + label[1:]
    body = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]
    return f"{lead}: {body}."


FLEETS_LEFT_OUT = {"what": "Fleet forecasts and alerts",
                   "why": "Fleets are part of Pro when used from an AI agent (MCP), so they're left out here."}


def summarize(db, list_owners, uid: str, period: dict, fleets: bool = True) -> dict:
    """The workspace's changes over ``period`` (from :func:`resolve_period`).
    ``fleets`` false leaves fleet forecasts and alerts out (a plan without them)."""
    since, until = period["since"], period["until"]
    owners = _scope(list_owners)
    new, changed, ids = _items(db, owners, since, until, uid)
    refits, refit_rows = _refits(db, ids["models"], since, until)
    refit_ids = {r["id"] for r in refits}
    changed = [r for r in changed if not (r["collection"] == "models" and r["id"] in refit_ids)]
    if fleets:
        forecasts, unrecorded = _forecasts(db, ids["fleets"], owners, since, until)
        alerts = _alerts(db, ids["fleets"], since, until)
    else:
        forecasts, unrecorded, alerts = [], 0, []
    rcm = _rcm(db, ids["rcm_studies"], ids["models"], refit_rows, owners)
    runs = _runs(db, ids["rbds"], since, until)

    counts = {
        "items": sum(len(docs) for docs in ids.values()),
        "new": len(new), "changed": len(changed),
        "refits": len(refits), "refits_moved": sum(1 for r in refits if r["moved"]),
        "forecasts_moved": sum(1 for r in forecasts if r["moved"]),
        "alerts": len(alerts), "rcm_evidence": len(rcm),
        "runs": sum(r["runs"] for r in runs), "runs_moved": sum(1 for r in runs if r["moved"]),
    }
    not_compared = list(NOT_COMPARED)
    if not fleets:
        not_compared.insert(0, FLEETS_LEFT_OUT)
    if unrecorded:
        not_compared.insert(0, {
            "what": f"Expected failures of {_plural(unrecorded, 'fleet')}",
            "why": "No forecast was recorded for them before this period, so there is nothing to compare "
                   "today's against. Forecasts are recorded when the fleet is opened or usage arrives."})
    out = {
        "since": since.isoformat(), "until": until.isoformat(),
        "period": {k: v for k, v in period.items() if k not in ("since", "until")},
        "sentence": _sentence(period["label"], counts),
        "counts": counts,
        "new": new[:MAX_ROWS], "changed": changed[:MAX_ROWS],
        "refits": refits[:MAX_ROWS], "forecasts": forecasts, "alerts": alerts[:MAX_ROWS],
        "rcm_evidence": rcm[:MAX_ROWS], "simulations": runs[:MAX_ROWS],
        "thresholds": {"relative": MOVE_FRACTION, "availability_points": AVAILABILITY_POINTS * 100},
        "not_compared": not_compared,
    }
    return out
