"""User-configured alerts on a fleet forecast's expected failures.

Rules are evaluated each time usage for the fleet arrives through the ingest
API, against the forecast just recomputed from those readings. Three kinds:

* ``above``  — metric: expected failures over the whole forecast horizon
  (``compute(...)["expected"]``, the fleet page's headline). Edge-triggered:
  fires once when the value crosses above ``threshold`` (``armed`` → False)
  and re-arms when it drops back to or below it. One email per crossing.
* ``change`` — same metric; fires when the value has moved ``percent`` % or
  more from its baseline (the value at the last firing, else at creation);
  the baseline then moves to the new value.
* ``within`` — metric: cumulative expected failures over the first
  ``y_periods`` periods of the forecast's ``per_period`` series (a fractional
  last period interpolated linearly). Edge-triggered like ``above``: fires
  when armed and the value is ≥ ``x``; re-arms when it drops below ``x``. If
  the horizon is later shortened below ``y_periods`` the rule evaluates over
  the periods available (``truncated`` in the API).

Every firing is recorded in ``fleet_alert_events`` and emailed to the rule's
creator. This is a transactional, user-configured alert, so it is not gated
on the marketing ``email_updates_opt_out`` flag.
"""

from __future__ import annotations

import html as html_lib
import logging
import math
import uuid
from datetime import datetime, timezone

from backend.config import SAMPLE_OWNER
from backend.db import from_doc
from backend.schema import Fleet
from backend.services import email as email_service
from backend.services import fleet as fleet_service

logger = logging.getLogger(__name__)

KINDS = ("above", "change", "within")
MAX_RULES = 10
MAX_PERCENT = 1000.0
_CONDITION_KEYS = ("kind", "threshold", "percent", "x", "y_periods")


class AlertValidationError(ValueError):
    """Invalid rule input (HTTP 422)."""


class AlertLimitError(ValueError):
    """Too many rules on one fleet (HTTP 422)."""


class AlertNotFound(KeyError):
    """Unknown rule id for this fleet."""


def _now():
    return datetime.now(timezone.utc)


def _iso(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


# ---- Metrics ---------------------------------------------------------------------

def current_forecast(db, fleet: Fleet, owners) -> dict | None:
    """The fleet's live forecast, or None when it can't be computed."""
    forecast = fleet_service.compute(db, fleet, owners)
    return forecast if forecast.get("status") == "ok" else None


def current_value(db, fleet: Fleet, owners) -> float | None:
    """Expected failures over the fleet's horizon (the page headline)."""
    forecast = current_forecast(db, fleet, owners)
    return _expected(forecast)


def _expected(forecast: dict | None) -> float | None:
    if not forecast:
        return None
    try:
        return float(forecast.get("expected"))
    except (TypeError, ValueError):
        return None


def window_value(per_period, y_periods: float) -> tuple[float, bool]:
    """(cumulative expected failures over the first ``y_periods``, truncated?).

    Y = 2.5 → per_period[0] + per_period[1] + 0.5·per_period[2]. When the
    series is shorter than Y (horizon shortened) it sums what's there and
    reports ``truncated``.
    """
    series = [float(v) for v in (per_period or [])]
    y = float(y_periods)
    truncated = y > len(series)
    whole = min(int(math.floor(y)), len(series))
    total = sum(series[:whole])
    frac = y - math.floor(y)
    if frac > 0 and whole < len(series) and not truncated:
        total += frac * series[whole]
    return total, truncated


def rule_value(rule: dict, forecast: dict | None) -> float | None:
    """The metric a rule watches, from a forecast (None if unavailable)."""
    if not forecast:
        return None
    if rule["kind"] == "within":
        return window_value(forecast.get("per_period"), rule["y_periods"])[0]
    return _expected(forecast)


# ---- Validation ------------------------------------------------------------------

def _number(value, field: str) -> float:
    try:
        f = float(value)
    except (TypeError, ValueError):
        raise AlertValidationError(f"'{field}' must be a number.")
    if f != f or f in (float("inf"), float("-inf")):
        raise AlertValidationError(f"'{field}' must be finite.")
    return f


def _clean_condition(fleet: Fleet, kind, threshold=None, percent=None, x=None, y_periods=None) -> dict:
    empty = {"threshold": None, "percent": None, "x": None, "y_periods": None}
    if kind not in KINDS:
        raise AlertValidationError("kind must be 'above', 'change' or 'within'.")
    if kind == "above":
        if threshold in (None, ""):
            raise AlertValidationError("An 'above' alert needs a threshold.")
        t = _number(threshold, "threshold")
        if t < 0:
            raise AlertValidationError("The threshold can't be negative.")
        return {**empty, "kind": kind, "threshold": t}
    if kind == "change":
        if percent in (None, ""):
            raise AlertValidationError("A 'change' alert needs a percent.")
        p = _number(percent, "percent")
        if not 0 < p <= MAX_PERCENT:
            raise AlertValidationError("The percent must be above 0 and at most 1000.")
        return {**empty, "kind": kind, "percent": p}
    if x in (None, "") or y_periods in (None, ""):
        raise AlertValidationError("A 'within' alert needs x (failures) and y_periods.")
    xv = _number(x, "x")
    if xv <= 0:
        raise AlertValidationError("x (failures) must be above 0.")
    yv = _number(y_periods, "y_periods")
    horizon = int((fleet.settings or {}).get("periods", 12))
    label = (fleet.settings or {}).get("period_label", "months")
    if not 0 < yv <= horizon:
        raise AlertValidationError(
            f"y_periods must be above 0 and at most the forecast horizon ({horizon} {label})."
        )
    return {**empty, "kind": kind, "x": xv, "y_periods": yv}


def _armed_for(cond: dict, value: float | None) -> bool:
    """Initial/re-synced arm state: armed unless already past the trigger.

    An unknown value (model unavailable) arms, so the first real crossing
    still notifies.
    """
    if value is None:
        return True
    if cond["kind"] == "above":
        return value <= cond["threshold"]
    if cond["kind"] == "within":
        return value < cond["x"]
    return True


# ---- CRUD ------------------------------------------------------------------------

def public(doc: dict, uid: str | None = None, fleet: Fleet | None = None,
           forecast: dict | None = None) -> dict:
    """API shape of one rule (with its live value when a forecast is given)."""
    out = {
        "id": doc["_id"],
        "fleet_id": doc["fleet_id"],
        "kind": doc["kind"],
        "threshold": doc.get("threshold"),
        "percent": doc.get("percent"),
        "x": doc.get("x"),
        "y_periods": doc.get("y_periods"),
        "enabled": bool(doc.get("enabled", True)),
        "armed": bool(doc.get("armed", True)),
        "last_value": doc.get("last_value"),
        "baseline_value": doc.get("baseline_value"),
        "last_fired_at": _iso(doc.get("last_fired_at")),
        "last_fired_value": doc.get("last_fired_value"),
        "created_at": _iso(doc.get("created_at")),
        "updated_at": _iso(doc.get("updated_at")),
    }
    if uid is not None:
        out["mine"] = doc.get("owner_uid") == uid
    if fleet is not None and doc["kind"] == "within":
        out["truncated"] = float(doc["y_periods"]) > int((fleet.settings or {}).get("periods", 12))
    if forecast is not None:
        out["current_value"] = rule_value(doc, forecast)
    return out


def list_alerts(db, fleet_id: str) -> list[dict]:
    return list(db.fleet_alerts.find({"fleet_id": fleet_id}).sort("created_at", 1))


def create_alert(db, fleet: Fleet, owner_uid: str, owners, *, kind, threshold=None,
                 percent=None, x=None, y_periods=None, enabled=True) -> dict:
    cond = _clean_condition(fleet, kind, threshold, percent, x, y_periods)
    if db.fleet_alerts.count_documents({"fleet_id": fleet.id}) >= MAX_RULES:
        raise AlertLimitError(f"A fleet can have at most {MAX_RULES} alerts.")
    forecast = current_forecast(db, fleet, owners)
    value = rule_value(cond, forecast)
    now = _now()
    doc = {
        "_id": uuid.uuid4().hex,
        "fleet_id": fleet.id,
        "owner_uid": owner_uid,
        **cond,
        "enabled": bool(enabled),
        "created_at": now,
        "updated_at": now,
        "last_value": value,
        "armed": _armed_for(cond, value),
        "baseline_value": value,
        "last_fired_at": None,
        "last_fired_value": None,
    }
    db.fleet_alerts.insert_one(doc)
    return doc


def update_alert(db, fleet: Fleet, alert_id: str, owners, changes: dict) -> dict:
    doc = db.fleet_alerts.find_one({"_id": alert_id, "fleet_id": fleet.id})
    if doc is None:
        raise AlertNotFound(alert_id)
    merged = {k: changes.get(k, doc.get(k)) for k in _CONDITION_KEYS}
    cond = _clean_condition(fleet, **merged)
    enabled = bool(changes["enabled"]) if "enabled" in changes else bool(doc.get("enabled", True))
    update = {**cond, "enabled": enabled, "updated_at": _now()}

    condition_changed = any(cond[k] != doc.get(k) for k in _CONDITION_KEYS)
    re_enabled = enabled and not doc.get("enabled", True)
    if condition_changed or re_enabled:
        # Re-sync with the forecast as it is now: an edge-triggered rule arms
        # only if it isn't already past its trigger (no stale email on a
        # re-enable); a rule switched to 'change' starts from today's value.
        value = rule_value(cond, current_forecast(db, fleet, owners))
        update["last_value"] = value
        update["armed"] = _armed_for(cond, value)
        if cond["kind"] != doc["kind"]:
            update["baseline_value"] = value
            update["last_fired_value"] = None
    db.fleet_alerts.update_one({"_id": alert_id}, {"$set": update})
    return db.fleet_alerts.find_one({"_id": alert_id})


def delete_alert(db, fleet_id: str, alert_id: str) -> None:
    if db.fleet_alerts.delete_one({"_id": alert_id, "fleet_id": fleet_id}).deleted_count == 0:
        raise AlertNotFound(alert_id)


def delete_for_fleet(db, fleet_id: str) -> None:
    db.fleet_alerts.delete_many({"fleet_id": fleet_id})


# ---- Evaluation ------------------------------------------------------------------

def _baseline(rule: dict):
    value = rule.get("last_fired_value")
    return rule.get("baseline_value") if value is None else value


def _should_fire(rule: dict, new_value: float) -> tuple[bool, dict]:
    """(fire?, fields to $set) for one enabled rule and its new metric value."""
    kind = rule["kind"]
    if kind in ("above", "within"):
        armed = bool(rule.get("armed", True))
        if kind == "above":
            past = new_value > float(rule["threshold"])
        else:
            past = new_value >= float(rule["x"])
        if armed and past:
            return True, {"armed": False}
        if not past:
            return False, {"armed": True}
        return False, {}
    baseline = _baseline(rule)
    if baseline is None:
        # No value when the rule was created (model unavailable): today's
        # value becomes the baseline.
        return False, {"baseline_value": new_value}
    moved = abs(new_value - float(baseline)) / max(float(baseline), 1e-9) * 100
    if moved >= float(rule["percent"]):
        return True, {"baseline_value": new_value}
    return False, {}


def evaluate_fleet_alerts(db, fleet_id: str, new_value: float, reason: str = "",
                          forecast: dict | None = None) -> int:
    """Evaluate every enabled rule on a fleet; returns how many fired.

    ``new_value`` is the recomputed expected failures over the horizon;
    ``forecast`` (the full recomputed forecast) supplies the per-period
    series 'within' rules need — computed here if not passed. Each firing is
    emailed and recorded. Callers treat this as best-effort — ingestion
    must never fail because of an alert.
    """
    rules = list_alerts(db, fleet_id)
    if not rules:
        return 0
    fleet = from_doc(Fleet, db.fleets.find_one({"_id": fleet_id}))
    if fleet is None:
        return 0
    if forecast is None and any(r["kind"] == "within" and r.get("enabled", True) for r in rules):
        forecast = current_forecast(db, fleet, [fleet.owner_id, SAMPLE_OWNER])
    fired = 0
    for rule in rules:
        if not rule.get("enabled", True):
            continue
        try:
            value = float(new_value) if rule["kind"] != "within" else rule_value(rule, forecast)
            if value is None:
                continue
            fire, updates = _should_fire(rule, value)
            previous = rule.get("last_value")
            baseline = _baseline(rule)
            updates["last_value"] = value
            now = _now()
            if fire:
                updates["last_fired_at"] = now
                updates["last_fired_value"] = value
            db.fleet_alerts.update_one({"_id": rule["_id"]}, {"$set": updates})
            if fire:
                fired += 1
                _fire(db, fleet, rule, previous, baseline, value, now, reason)
        except Exception:
            logger.exception("fleet alert evaluation failed alert=%s fleet=%s", rule.get("_id"), fleet_id)
    return fired


def _fire(db, fleet: Fleet, rule: dict, previous, baseline, new_value: float, when, reason: str) -> None:
    event = {
        "_id": uuid.uuid4().hex,
        "alert_id": rule["_id"],
        "fleet_id": fleet.id,
        "uid": rule.get("owner_uid"),
        "kind": rule["kind"],
        "previous_value": previous,
        "new_value": new_value,
        "threshold": rule.get("threshold"),
        "percent": rule.get("percent"),
        "x": rule.get("x"),
        "y_periods": rule.get("y_periods"),
        "baseline_value": baseline if rule["kind"] == "change" else None,
        "reason": reason,
        "sent": False,
        "error": None,
        "created_at": when,
    }
    try:
        user = db.users.find_one({"_id": rule.get("owner_uid")}) or {}
        to = user.get("email")
        if not to:
            raise RuntimeError("The alert owner's account has no email address.")
        if not email_service.enabled():
            raise RuntimeError("Email isn't configured on this server (SMTP).")
        msg = render(fleet, rule, previous, baseline, new_value, when, reason)
        email_service.send_now(to, msg["subject"], msg["text"], html=msg["html"])
        event["sent"] = True
    except Exception as exc:
        logger.warning("fleet alert email not sent alert=%s: %s", rule["_id"], exc)
        event["error"] = str(exc) or exc.__class__.__name__
    db.fleet_alert_events.insert_one(event)


# ---- Email -----------------------------------------------------------------------

def _num(v) -> str:
    return f"{float(v):g}"


def _one(v) -> str:
    return "—" if v is None else f"{float(v):.1f}"


def _x(v) -> str:
    """A failure count to one decimal, unless that would hide precision (0.25)."""
    s = f"{float(v):.1f}"
    return s if float(s) == float(v) else f"{float(v):g}"


def _periods(y, label: str) -> str:
    label = str(label or "periods")
    if float(y) == 1 and label.lower().endswith("s"):
        label = label[:-1]
    return f"{_num(y)} {label}"


def render(fleet: Fleet, rule: dict, previous, baseline, new_value: float, when,
           reason: str = "") -> dict:
    """Subject, plain text and branded HTML for one firing."""
    from backend.services import email_templates as tpl

    esc = html_lib.escape
    settings = fleet.settings or {}
    label = settings.get("period_label", "months")
    horizon = _periods(settings.get("periods", 12), label)
    link = email_service._app_url(f"/fleet/forecasts/{fleet.id}")
    manage = f"{link}#alerts"
    stamp = when.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    via = reason or "a usage update received via the API"

    if rule["kind"] == "above":
        threshold = _num(rule["threshold"])
        subject = f"Fleet alert: {fleet.name} — expected failures above {threshold}"
        title = f"Expected failures for {fleet.name} rose above {threshold}"
        lead = f"Expected failures over the next {horizon}: {_one(previous)} → {_one(new_value)}."
    elif rule["kind"] == "within":
        window = _periods(rule["y_periods"], label)
        subject = f"Fleet alert: {fleet.name} — ≥ {_x(rule['x'])} failures now expected within {window}"
        title = f"{fleet.name}: {_x(rule['x'])} or more failures now expected within {window}"
        lead = f"Expected failures within the next {window}: {_one(previous)} → {_one(new_value)}."
        if float(rule["y_periods"]) > int(settings.get("periods", 12)):
            lead += f" (The forecast horizon is now {horizon}, so this covers only that.)"
    else:
        base = float(baseline) if baseline is not None else None
        pct = abs(new_value - base) / max(base, 1e-9) * 100 if base is not None else 0.0
        subject = f"Fleet alert: {fleet.name} — expected failures changed by {pct:.0f}%"
        direction = "rose" if base is None or new_value >= base else "fell"
        title = f"Expected failures for {fleet.name} {direction} by {pct:.0f}%"
        lead = f"Expected failures over the next {horizon}: {_one(base)} → {_one(new_value)}."
    trigger = f"Triggered by {via} at {stamp}."
    footer = ("You're getting this because you set an alert on this fleet. "
              f"Manage alerts: {manage}")
    signoff = "Reliafy, Brisbane, Australia · hello@reliafy.com"

    text = (
        f"{title}\n\n"
        f"{lead}\n\n"
        f"{trigger}\n\n"
        f"View the fleet: {link}\n\n"
        f"--\n{footer}\n{signoff}\n"
    )

    body = tpl.style_body(f"<p>{esc(trigger)}</p>")
    footer_html = (
        "You're getting this because you set an alert on this fleet.<br>"
        f'<a href="{esc(manage)}" style="color:{tpl.FAINT};text-decoration:underline;">Manage alerts</a>'
        " &nbsp;·&nbsp; Reliafy, Brisbane, Australia &nbsp;·&nbsp; "
        f'<a href="mailto:hello@reliafy.com" style="color:{tpl.FAINT};text-decoration:underline;">'
        "hello@reliafy.com</a>"
    )
    html = tpl.layout(
        body_html=body,
        base_url=email_service._app_url("/"),
        title=title,
        eyebrow="Fleet alert",
        lead=lead,
        preheader=lead,
        cta=("View the fleet", link),
        footer_html=footer_html,
    )
    return {"subject": subject, "text": text, "html": html}
