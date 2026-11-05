"""Progression: how fast a watched level is heading for its limit.

A band (or any automated condition point) is a series of readings over time. For
one unit this module fits that series with one of SurPyval's degradation
*processes* and asks when it will first reach the alarm limit.

In plain words. The reading drifts at some average rate and wobbles around that
drift. So the time to reach the limit is not a date but a spread of dates: "most
likely about 40 days, a 1 in 10 chance within 18 days". Two processes are offered:

* ``wiener``: a random walk with drift (it can go down a little as well as up;
  the default, and the only one for a noisy band);
* ``gamma``: a path that only ever rises, in jumps (wear-like; it refuses a
  series that falls anywhere).

Two kinds of uncertainty are shown, and kept apart:

* the *spread of the process* (``range``): even with the rate known exactly the
  crossing time varies. This is SurPyval's ``predict_rul`` interval;
* the *uncertainty in the rate itself* (``range_allowing_for_the_fit``), because
  it was estimated from a few readings. This comes from SurPyval's Wald bounds on
  the first-passage distribution (``cb``). It can be open-ended: with little data
  the late end may be unbounded, and then it says so rather than inventing one.

Nothing here invents a bound. With fewer than ``MIN_READINGS`` readings, a series
that isn't heading for the limit, or a series with no scatter at all, the answer is
a plain message and no dates.

The functions work on a measurement point id and read its series from the series
store, so they serve any automated point; a band is the usual one. Times are
counted in days from the last reading used.
"""

from __future__ import annotations

import io
import warnings
from datetime import datetime, timedelta, timezone

import numpy as np

from backend.maintenance.series import parse_time

MIN_READINGS = 6  # fewer and no crossing time is given
ROUGH_BELOW = 12  # fewer than this and the answer carries a caution
MAX_READINGS = 500  # a longer series is thinned (evenly in time order) before fitting
PROCESSES = ("wiener", "gamma")
HORIZONS_DAYS = (7, 30, 90, 180, 365)
GRID_POINTS = 160
GRID_SPAN = 25.0  # the chance curve runs out to this many times the median
MAX_DAYS = 36500  # beyond a century nothing is reported as a date

#: The MCP / REST / CLI table (maintenance ``progression.<action>``).
PROGRESSION = {
    "time_to_limit": ("point_id", "process limit since confidence", """When a watched band (or any automated
        condition point) is expected to reach its alarm limit, for this one unit, with the uncertainty. Fits the
        point's own readings with a SurPyval degradation process: wiener (random walk with drift; the default) or
        gamma (rises only). limit: the level to reach (default: the point's alarm_above for a rising trend, alarm_below
        for a falling one). since: start from this date (ISO 8601), e.g. after the part was renewed. confidence: the
        range asked for, default 0.8 (the 10% to 90% chance dates). With fewer than 6 readings, a series not heading
        for the limit, or one with no scatter at all, you get a plain message and no dates. It is the time to the
        limit, not to failure."""),
    "series": ("point_id", "since unit_name", """The point's readings as a degradation series: rows of unit, age_days,
        value (age counted in days from the first reading used, or from since) and the same as CSV text, ready for a
        dataset to use in a degradation model or a tracked item. A copy: it doesn't link to the point."""),
}

ASSUMPTION = {
    "wiener": ("The level is modelled as a random walk with a steady average drift: each day it moves by the "
               "drift plus random wobble that grows with the square root of time. It assumes the drift stays the "
               "same from here (no change in load or speed, no repair) and that the wobble is independent from "
               "one reading to the next. Sensor noise is counted as part of the wobble."),
    "gamma": ("The level is modelled as a path that only ever rises, in small random jumps whose average size "
              "per day stays the same. It assumes the rate of wear stays the same from here and that each reading "
              "is the true level (no sensor noise)."),
}


class NoAnswer(Exception):
    """The series can't give a crossing time; ``status`` says why."""

    def __init__(self, status: str, message: str):
        super().__init__(message)
        self.status = status


def _invalid():
    from backend.maintenance.service import Invalid

    return Invalid


def _iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _num(v):
    v = float(v)
    return v if np.isfinite(v) else None


def _sig(v, digits: int = 4):
    return None if v is None else float(f"{v:.{digits}g}")


def _readings(m, point: dict, since) -> list[tuple[datetime, float]]:
    """The point's readings oldest first, one per time, from ``since``; thinned if long."""
    raw = m.s.series.recent(m.org, point["id"], 5000)
    start = parse_time(since) if since not in (None, "") else None
    rows: dict[datetime, float] = {}
    for r in raw:
        t = datetime.fromisoformat(str(r["t"]).replace("Z", "+00:00"))
        t = t if t.tzinfo else t.replace(tzinfo=timezone.utc)
        if start is not None and t < start:
            continue
        rows[t] = float(r["value"])
    out = sorted(rows.items())
    if len(out) > MAX_READINGS:
        keep = sorted(set(np.linspace(0, len(out) - 1, MAX_READINGS).round().astype(int).tolist()))
        out = [out[i] for i in keep]
    return out


def _check_point(m, point_id) -> dict:
    Invalid = _invalid()
    point = m._get(str(point_id or ""), "MeasurementPoint")
    if point.get("source") != "automated":
        raise Invalid(f"{point['name']} is a manual point; time to the limit is worked out from an automated "
                      "series (a band or level of a signal channel, or a sensor feed).")
    return point


def _limit_for(point: dict, limit, last: float, slope: float) -> tuple[float, str]:
    """``(limit, where it came from)``; the direction follows from the limit and the latest level."""
    Invalid = _invalid()
    if limit not in (None, ""):
        try:
            value = float(limit)
        except (TypeError, ValueError):
            raise Invalid("limit must be a number.") from None
        if not np.isfinite(value):
            raise Invalid("limit must be a finite number.")
        return value, "given"
    above, below = point.get("alarm_above"), point.get("alarm_below")
    if above is not None and below is not None:
        return (above, "alarm_above") if slope >= 0 else (below, "alarm_below")
    if above is not None:
        return above, "alarm_above"
    if below is not None:
        return below, "alarm_below"
    raise NoAnswer("no_limit", "There is no limit to reach. Set an alarm limit on the band, or give a limit.")


def _explain(err: Exception, process: str) -> NoAnswer:
    text = str(err)
    low = text.lower()
    if "sigma is 0" in low or "noise-free" in low or "no finite maximum" in low:
        return NoAnswer("no_scatter", "The readings fall exactly on a straight line, so there is no scatter to "
                        "judge the uncertainty from. If that is real, the time to the limit is just the distance "
                        "left divided by the rate. If the readings are rounded or smoothed, send the unrounded ones.")
    if "not positive" in low or "mu = 0" in low or "never moves" in low or "never reaches" in low:
        return NoAnswer("not_moving", "The level is not moving toward the limit (it is flat, or heading away), "
                        "so no time to the limit can be given.")
    if "monotone" in low or "decreases over at least one" in low:
        return NoAnswer("not_rising_only", "The readings go down as well as up, so the rising-only model does not "
                        "fit. Use the random-walk model instead.")
    return NoAnswer("error", f"The readings could not be fitted ({text[:200]}).")


def _fit(process: str, days, level, threshold: float):
    from surpyval.degradation import GammaProcess, WienerProcess

    fitter = WienerProcess if process == "wiener" else GammaProcess
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            model = fitter.fit(days, level, np.zeros(len(days)), threshold=threshold)
        except ValueError as err:
            raise _explain(err, process) from None
    for w in caught:
        if "no finite maximum" in str(w.message):
            raise _explain(ValueError(str(w.message)), process)
    return model


def _crossing(grid, p, target):
    """The first grid time at which the curve ``p`` reaches ``target`` (None if it doesn't)."""
    above = np.nonzero(np.asarray(p) >= target)[0]
    if not len(above):
        return None
    k = int(above[0])
    if k == 0:
        return float(grid[0])
    x0, x1, y0, y1 = grid[k - 1], grid[k], p[k - 1], p[k]
    return float(x0 + (x1 - x0) * (target - y0) / (y1 - y0)) if y1 > y0 else float(x1)


def time_to_limit(m, point_id, process="wiener", limit=None, since=None, confidence=0.8) -> dict:
    """See ``PROGRESSION["time_to_limit"]``. Returns a dict with ``status`` ("ok" when a time
    is given) and a plain ``message``; never dates without a status of "ok" or "already_past"."""
    Invalid = _invalid()
    if process not in PROCESSES:
        raise Invalid(f"process must be one of: {', '.join(PROCESSES)}.")
    try:
        confidence = float(0.8 if confidence in (None, "") else confidence)
    except (TypeError, ValueError):
        raise Invalid("confidence must be a number between 0.5 and 0.99.") from None
    if not 0.5 <= confidence <= 0.99:
        raise Invalid("confidence must be between 0.5 and 0.99.")
    point = _check_point(m, point_id)
    rows = _readings(m, point, since)
    out = {"point_id": point["id"], "name": point["name"], "unit": point.get("unit", ""), "process": process,
           "assumption": ASSUMPTION[process], "n_readings": len(rows), "minimum_readings": MIN_READINGS,
           "since": since or None, "confidence": confidence, "warnings": [], "limit": None,
           "time_to_limit": None, "trend": None}
    if len(rows) < MIN_READINGS:
        return out | {"status": "too_few", "message": (
            f"{len(rows)} reading{'s' if len(rows) != 1 else ''} so far; at least {MIN_READINGS} are needed "
            "before a time to the limit can be worked out honestly. It will appear as the readings come in.")}
    times = [t for t, _ in rows]
    t0, t_last = times[0], times[-1]
    days = np.array([(t - t0).total_seconds() / 86400.0 for t in times])
    values = np.array([v for _, v in rows])
    out |= {"first": {"t": _iso(t0), "value": values[0]}, "last": {"t": _iso(t_last), "value": values[-1]},
            "span_days": _sig(days[-1])}
    if days[-1] <= 0:
        return out | {"status": "too_few", "message": "All the readings are at one moment; the level needs to be "
                      "read over a period before a trend can be worked out."}
    slope = float(np.polyfit(days, values, 1)[0])
    try:
        lim, where = _limit_for(point, limit, values[-1], slope)
    except NoAnswer as err:
        return out | {"status": err.status, "message": str(err)}
    if where == "alarm_above":
        sign = 1.0
    elif where == "alarm_below":
        sign = -1.0
    else:
        sign = 1.0 if lim > values[-1] or (lim == values[-1] and slope >= 0) else -1.0
    rising = sign > 0
    out["limit"] = {"value": lim, "from": where, "direction": "rising" if rising else "falling"}
    if len(rows) < ROUGH_BELOW:
        out["warnings"].append(f"Only {len(rows)} readings: treat this as a rough guide; the range will narrow as "
                               "more arrive.")
    level = sign * values
    threshold = sign * lim
    if level[-1] >= threshold:
        reached = next(t for t, v in zip(times, level) if v >= threshold)
        return out | {"status": "already_past", "message": (
            f"The level is already {'above' if rising else 'below'} the limit ({_sig(values[-1])} against "
            f"{_sig(lim)}); it first passed it on {reached.date().isoformat()}."),
            "time_to_limit": {"median_days": 0.0, "median_at": _iso(t_last)}}
    age = (datetime.now(timezone.utc) - t_last).total_seconds() / 86400.0
    if age > max(7.0, 0.25 * days[-1]):
        out["warnings"].append(f"The last reading is {age:.0f} days old; the dates count from it, not from today.")
    try:
        model = _fit(process, days, level, threshold)
        current = float(level[-1])
        rul = model.predict_rul(current, alpha_ci=1.0 - confidence)
    except NoAnswer as err:
        return out | {"status": err.status, "message": str(err)}
    except ValueError as err:
        no = _explain(err, process)
        return out | {"status": no.status, "message": str(no)}
    median = float(rul.rul)
    lo_days, hi_days = (float(v) for v in rul.rul_interval)
    if not (np.isfinite(median) and 0 < median < MAX_DAYS):
        return out | {"status": "not_moving", "message": "The level is moving too slowly toward the limit for a "
                      "date to mean anything (over a century)."}

    # The chance of having reached the limit by each day from the last reading, with the bounds
    # that allow for the rate itself being an estimate.
    grid = np.linspace(0.0, median * GRID_SPAN, GRID_POINTS + 1)[1:]
    grid = np.unique(np.concatenate([np.geomspace(max(median / 400.0, 1e-6), median * GRID_SPAN, GRID_POINTS),
                                     grid]))
    ff = np.asarray(model.ff(grid, y0=current), dtype=float)
    bounds = None
    try:
        with np.errstate(all="ignore"), warnings.catch_warnings():
            warnings.simplefilter("ignore")
            bounds = np.asarray(model.cb(grid, on="ff", alpha_ci=0.1, y0=current), dtype=float)
    except Exception:  # noqa: BLE001 - the bounds are an extra; the answer stands without them
        out["warnings"].append("The uncertainty in the rate could not be worked out, so only the spread of the "
                               "process is shown.")
    tail = (1.0 - confidence) / 2.0
    wide_early = wide_late = None
    wide_note = None
    if bounds is not None and np.isfinite(bounds).all() and bounds.shape == (len(grid), 2):
        # The upper bound on the chance reaches the early tail first; the lower bound reaches the late one last.
        wide_early = _crossing(grid, np.maximum.accumulate(bounds[:, 1]), tail)
        wide_late = _crossing(grid, np.maximum.accumulate(bounds[:, 0]), 1.0 - tail)
        if wide_late is None:
            wide_note = (f"the late end cannot be bounded within {grid[-1]:.0f} days: with this much data the "
                         "level could be drifting much more slowly")
    chance = []
    for h in HORIZONS_DAYS:
        if h > grid[-1]:
            continue
        i = int(np.searchsorted(grid, h))
        entry = {"days": h, "chance": _sig(float(np.interp(h, grid, ff)))}
        if bounds is not None and np.isfinite(bounds).all() and bounds.shape == (len(grid), 2):
            entry["low"] = _sig(float(np.interp(h, grid, bounds[:, 0])))
            entry["high"] = _sig(float(np.interp(h, grid, bounds[:, 1])))
        chance.append(entry)

    def at(days_from_last):
        return None if days_from_last is None else _iso(t_last + timedelta(days=days_from_last))

    ttl = {"median_days": _sig(median), "median_at": at(median),
           "range": {"early_days": _sig(lo_days), "late_days": _sig(hi_days), "early_at": at(lo_days),
                     "late_at": at(hi_days), "chance_each_end": _sig(tail)},
           "range_allowing_for_the_fit": {"early_days": _sig(wide_early), "late_days": _sig(wide_late),
                                          "early_at": at(wide_early), "late_at": at(wide_late), "note": wide_note},
           "chance_by": chance,
           "curve": {"days": [_sig(float(d)) for d in grid[::4]], "chance": [_sig(float(v)) for v in ff[::4]]}}
    # Per day: the drift (random walk), or the gamma process's mean rate (shape rate / rate).
    drift = sign * (float(model.mu) if process == "wiener" else float(model.alpha) / float(model.beta))
    wobble = float(model.sigma) if process == "wiener" else None
    # The fitted drift line over the readings, and the projection from the last one to the median crossing.
    start_level = values[-1] - drift * days[-1]
    fitted = [{"t": _iso(t0), "value": _sig(start_level, 6)}, {"t": _iso(t_last), "value": _sig(values[-1], 6)}]
    projection = [{"t": _iso(t_last), "value": _sig(values[-1], 6)}, {"t": at(median), "value": _sig(lim, 6)}]
    out["trend"] = {"drift_per_day": _sig(drift), "wobble_per_sqrt_day": _sig(wobble),
                    "drift_per_day_text": "rising" if drift > 0 else "falling", "fitted": fitted,
                    "projection": projection}
    out["time_to_limit"] = ttl
    plain = _plain(out, rising)
    return out | {"status": "ok", "message": plain}


def _days_text(d) -> str:
    if d is None:
        return "?"
    if d < 1:
        return f"{d * 24:.0f} hours" if d >= 1 / 24 else "under an hour"
    if d < 60:
        return f"{d:.0f} days"
    if d < 730:
        return f"{d / 30.4:.0f} months"
    return f"{d / 365.25:.1f} years"


def _plain(out: dict, rising: bool) -> str:
    ttl = out["time_to_limit"]
    lim = out["limit"]["value"]
    wide = ttl["range_allowing_for_the_fit"]
    pct = f"{(1 - 2 * ttl['range']['chance_each_end']) * 100:.0f}%"
    text = (f"At the current rate the level is most likely to reach {_sig(lim)} {out['unit']} in about "
            f"{_days_text(ttl['median_days'])} (around {ttl['median_at'][:10]}). ")
    if wide["early_days"] is not None and wide["late_days"] is not None:
        text += (f"Allowing for the rate being estimated from only {out['n_readings']} readings, a {pct} range is "
                 f"{_days_text(wide['early_days'])} to {_days_text(wide['late_days'])}.")
    elif wide["early_days"] is not None:
        text += (f"Allowing for the rate being estimated from only {out['n_readings']} readings, it could be as "
                 f"soon as {_days_text(wide['early_days'])}, and {wide['note'] or 'there is no firm late end'}.")
    else:
        r = ttl["range"]
        text += (f"If the rate were known exactly, a {pct} range would be {_days_text(r['early_days'])} to "
                 f"{_days_text(r['late_days'])}; the uncertainty in the rate itself could not be worked out.")
    return text


def series(m, point_id, since=None, unit_name=None) -> dict:
    """The point's readings as a degradation series (a copy). The unit is what the point measures
    (the position or item), or ``unit_name``; age is in days from the first reading used."""
    point = _check_point(m, point_id)
    rows = _readings(m, point, since)
    on = m.s.out(m.org, point["id"], "ON")
    name = (unit_name or "").strip() or (on[0]["name"] if on else point["name"])
    if not rows:
        return {"point_id": point["id"], "name": point["name"], "unit": point.get("unit", ""), "item": name,
                "rows": [], "csv": "", "n_readings": 0}
    t0 = rows[0][0]
    data = [{"unit": name, "age_days": round((t - t0).total_seconds() / 86400.0, 6), "value": v, "t": _iso(t)}
            for t, v in rows]
    buf = io.StringIO()
    buf.write("unit,age_days,value\n")
    for r in data:
        buf.write(f"\"{r['unit'].replace(chr(34), chr(34) * 2)}\",{r['age_days']},{r['value']:.10g}\n")
    return {"point_id": point["id"], "name": point["name"], "unit": point.get("unit", ""), "item": name,
            "level_unit": point.get("unit", ""), "n_readings": len(data), "age_starts": _iso(t0),
            "note": ("Age is counted in days from the first reading used, not from when the part was fitted. "
                     "Use since to start after a renewal."),
            "alarm_above": point.get("alarm_above"), "alarm_below": point.get("alarm_below"),
            "rows": data, "csv": buf.getvalue()}


class ProgressionOps:
    """Mixed into :class:`~backend.maintenance.service.Maintenance`."""

    def time_to_limit(self, point_id, process="wiener", limit=None, since=None, confidence=0.8) -> dict:
        return time_to_limit(self, point_id, process, limit, since, confidence)

    def progression_series(self, point_id, since=None, unit_name=None) -> dict:
        return series(self, point_id, since, unit_name)
