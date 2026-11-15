"""Covariates that change over time on RBD blocks (#52).

A block backed by a covariate regression model (PH, AFT, PO, AH or Cox) is
evaluated at fixed covariate values by default — the calculator's
"Set covariates". A covariate can instead follow a **schedule** over the
diagram's time: mission phases, a duty cycle, a stepped ramp or a geometric
growth. The schedule is stored on the block, under ``data.covariate_schedules``::

    {"load_pct": {"expression": "90 if t % 24 < 8 else 30"},
     "site":     {"table": [{"t": 0, "value": "north"}, {"t": 4000, "value": "south"}],
                  "period": 8760}}

* an **expression** in ``t`` (numeric covariates), checked and evaluated by
  :mod:`.tvc_expression`'s locked-down evaluator; or
* a **table** of phases — the value from each time on — optionally repeating
  every ``period`` (categorical covariates, or numeric ones by hand).

Lowering (this module) turns the block's schedules into one SurPyval
``StepSchedule``: each scheduled covariate's steps are found, the others hold
their calculator value, numeric values are clipped to the model's fitted
range (with a warning: the model says nothing beyond it), and the rows are
encoded as the model's design (a formula's categorical levels too). A
schedule that only repeats (``t % P``, or a table with a period) becomes
SurPyval's cyclic schedule, exact to any time; any other is laid out to the
time asked for and extended when a later time is asked.

The block is then RePyability's ``RegressionNode`` with that schedule:
its reliability is the model's ``sf_tvc`` along the path, so the system
reliability, importance, MTTF, B-lives, fault tree, conditional and "as of
now" figures all take it unchanged.

In a **repairable** diagram the schedule belongs to the plant, not the unit
(RePyability's repairable ``"covariates"``): the load follows the diagram's
clock, and a repaired or replaced unit carries on under the load in force at
that time (a repair resets its age as the repair says; the schedule keeps
running). Such a block has no reliability of its own, so only the
simulations take it: its figures are simulated (Pro), and RePyability's own
refusals (an accelerated-failure-time model with imperfect repair, a
proportional-odds or Cox model, a duty, a common-cause group) are shown in
its words. Standby spares refuse schedules in both kinds of diagram (a
spare's path would start when it's switched in).

A **mission phase** can give a covariate a schedule too, over the phase's
own time (:func:`phase_steps`): the mission then follows it within the
phase, on the mission's clock.
"""

from __future__ import annotations

import bisect
import math
from typing import Optional

import numpy as np

from backend.services.tvc_expression import Expression, ExpressionError, change_points

KEY = "covariate_schedules"
MAX_COVARIATES = 20
MAX_TABLE_ROWS = 50
# Steps a laid-out schedule may hold, and a repeating one over the times asked.
MAX_SEGMENTS = 5000
MAX_CYCLIC_SEGMENTS = 20_000
MAX_PATTERN = 1000
# Memory guards for evaluating a block along its schedule (a hourly-stepped
# schedule out to tens of thousands of hours once took a 2 GiB instance down):
# SurPyval's step-path sum lays out a (segments x query times) table, so the
# query times go in chunks of at most this many cells (~8 MB a temporary);
# the exact cumulative path (PH and PO models) holds a few numbers a segment,
# up to this many segments (and replaces MAX_CYCLIC_SEGMENTS there).
MAX_EVAL_CELLS = 1_000_000
MAX_CUMULATIVE_SEGMENTS = 500_000

#: In words, on every repairable result with a block on a schedule.
REPAIRABLE_NOTE = (
    "Covariate schedules follow the plant's clock: the load follows the diagram's schedule, and a repaired or "
    "replaced unit carries on under the load in force at that time (a repair resets its age, not the schedule). "
    "Blocks on a schedule have no reliability of their own, so these figures are simulated.")
STANDBY_REASON = (
    "a standby block can't follow a covariate schedule: a spare's covariates would start when it's switched "
    "in, not on the diagram's clock. Use a constant value, or model the units as parallel blocks.")


class ScheduleError(ValueError):
    """A schedule that can't be used, in plain words."""


def _fmt(v: float) -> str:
    if v is None or not math.isfinite(v):
        return "∞" if v == math.inf else "−∞" if v == -math.inf else "—"
    return f"{v:,.6g}"


def _with_unit(v: float, unit: Optional[str]) -> str:
    if not unit:
        return _fmt(v)
    return f"{_fmt(v)}{unit}" if unit == "%" else f"{_fmt(v)} {unit}"


# ---------------------------------------------------------------------------
# The stored shape
# ---------------------------------------------------------------------------

def _number(value, what: str) -> float:
    if isinstance(value, bool):
        raise ScheduleError(f"{what} must be a number.")
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise ScheduleError(f"{what} must be a number.") from None
    if not math.isfinite(v):
        raise ScheduleError(f"{what} must be a finite number.")
    return v


def _table(raw, period, name: str, field: Optional[dict]) -> dict:
    if not isinstance(raw, list) or not raw:
        raise ScheduleError(f"{name}: a phase table needs at least one row, from time 0.")
    if len(raw) > MAX_TABLE_ROWS:
        raise ScheduleError(f"{name}: a phase table can have at most {MAX_TABLE_ROWS} rows.")
    categorical = bool(field) and field.get("type") != "number"
    rows = []
    for k, row in enumerate(raw):
        if not isinstance(row, dict) or "t" not in row or "value" not in row:
            raise ScheduleError(f"{name}: each phase is {{\"t\": time, \"value\": value}}.")
        t = _number(row["t"], f"{name}, phase {k + 1}: the time")
        if t < 0:
            raise ScheduleError(f"{name}, phase {k + 1}: the time must be 0 or more.")
        value = row["value"]
        if categorical:
            value = str(value)
            options = [str(o) for o in field.get("options") or []]
            if options and value not in options:
                raise ScheduleError(f"{name}, phase {k + 1}: “{value}” isn't one of the model's levels "
                                    f"({', '.join(options)}).")
        elif isinstance(value, str) and not (field and field.get("type") == "number"):
            value = value.strip()
            if not value:
                raise ScheduleError(f"{name}, phase {k + 1}: give a value.")
        else:
            value = _number(value, f"{name}, phase {k + 1}: the value")
        rows.append({"t": t, "value": value})
    times = [r["t"] for r in rows]
    if times[0] != 0:
        raise ScheduleError(f"{name}: the first phase starts at time 0.")
    if any(b <= a for a, b in zip(times, times[1:])):
        raise ScheduleError(f"{name}: phases must start at increasing times, each at its own time.")
    out: dict = {"table": rows}
    if period not in (None, ""):
        p = _number(period, f"{name}: the repeat period")
        if p <= 0:
            raise ScheduleError(f"{name}: the repeat period must be more than 0.")
        if times[-1] >= p:
            raise ScheduleError(f"{name}: every phase must start within one period (before {_fmt(p)}).")
        out["period"] = p
    return out


def normalise(raw, fields: Optional[list] = None) -> Optional[dict]:
    """The stored schedules, checked; None for none. ``fields`` (the block
    model's covariate inputs) names the covariates there are; without them
    only the shapes and expressions are checked. Raises
    :class:`ScheduleError`."""
    if raw in (None, {}):
        return None
    if not isinstance(raw, dict):
        raise ScheduleError("covariate_schedules maps each covariate's name to its schedule.")
    if len(raw) > MAX_COVARIATES:
        raise ScheduleError(f"At most {MAX_COVARIATES} covariates can follow a schedule.")
    by_name = {f.get("name"): f for f in fields or []}
    out = {}
    for name, spec in raw.items():
        name = str(name)
        field = by_name.get(name)
        if fields is not None and field is None:
            known = ", ".join(by_name) or "none"
            raise ScheduleError(f"Unknown covariate “{name}”: this block's model has {known}.")
        if not isinstance(spec, dict):
            raise ScheduleError(f"{name}: a schedule is {{\"expression\": …}} or {{\"table\": […]}}.")
        has_expr, has_table = spec.get("expression") not in (None, ""), spec.get("table") is not None
        if has_expr == has_table:
            raise ScheduleError(f"{name}: give an expression or a phase table, not both.")
        if has_expr:
            if field and field.get("type") != "number":
                raise ScheduleError(f"{name} is categorical: give its levels as a phase table, not an expression.")
            try:
                expr = Expression(spec["expression"])
            except ExpressionError as exc:
                raise ScheduleError(f"{name}: {exc}") from None
            out[name] = {"expression": expr.text}
        else:
            out[name] = _table(spec["table"], spec.get("period"), name, field)
    return out or None


SCHEDULED_TYPES = ("component", "series", "parallel")


def on_node(data: dict, ntype: str) -> Optional[dict]:
    """A block's ``covariate_schedules`` as given (MCP, import), checked
    against its model's covariates; None when empty. Raises
    :class:`ScheduleError`."""
    raw = (data or {}).get(KEY)
    if raw in (None, {}):
        return None
    if ntype not in SCHEDULED_TYPES:
        raise ScheduleError(f"covariate_schedules apply to {', '.join(SCHEDULED_TYPES)} blocks, not {ntype}.")
    model = (data or {}).get("model") or {}
    if model.get("kind") != "regression":
        raise ScheduleError("covariate_schedules need a saved covariate (regression) model on the block — e.g. "
                            "a Weibull PH model — whose covariates they set over time.")
    return normalise(raw, model.get("covariates") or None)


def of_node(data: dict) -> Optional[dict]:
    """The schedules stored on a block (unchecked), or None."""
    raw = (data or {}).get(KEY)
    return raw if isinstance(raw, dict) and raw else None


def export_note(data: dict, label: str) -> str:
    """The "Download as Python" comment for a block along a schedule."""
    paths = "; ".join(f"{name} = {describe(spec)}" for name, spec in (of_node(data) or {}).items())
    return (f"{label}: its covariates follow a schedule in Reliafy - {paths} (t in the diagram's time unit; "
            "values held within the model's fitted range). Reliafy evaluates the fitted model along that path. "
            "To reproduce it, fit the model with SurPyval, build the path with surv.StepSchedule "
            "(from_changepoints, or cyclic for a repeating one) and use "
            "repyability.RegressionNode(model, schedule=schedule) as this block.")


def describe(spec: dict) -> str:
    """One schedule in words (export comments, the canvas)."""
    if "expression" in spec:
        return spec["expression"]
    phases = ", ".join(f"{r['value']} from {_fmt(r['t'])}" for r in spec.get("table") or [])
    return phases + (f", repeating every {_fmt(spec['period'])}" if spec.get("period") else "")


# ---------------------------------------------------------------------------
# A schedule within a mission phase (#372)
# ---------------------------------------------------------------------------
#: The most steps one phase's schedules may make (the mission follows each).
MAX_PHASE_STEPS = 2000


def is_schedule(value) -> bool:
    """Whether a phase's covariate value is a schedule over the phase."""
    return isinstance(value, dict) and ("expression" in value or "table" in value)


def phase_schedule(raw, name: str) -> dict:
    """A phase's covariate value given as a schedule over the phase's own
    time (``t`` from the phase's start): ``{"expression": …}`` or
    ``{"table": [{t, value}], "period"?}``, checked. Raises
    :class:`ScheduleError`."""
    return normalise({name: raw})[name]


def phase_steps(spec: dict, duration: float, name: str = "the covariate") -> tuple[list, list]:
    """A phase schedule's steps over ``[0, duration)``, in phase time:
    ``(times, values)``, the first at 0. A phase of no length takes the
    value at 0. Raises :class:`ScheduleError`."""
    field = {"name": name, "type": "number" if "expression" in spec else "category"}
    if "table" in spec and all(not isinstance(r.get("value"), str) for r in spec["table"]):
        field["type"] = "number"
    track = _Track(name, field, spec, None)
    if not track.varies:
        return [0.0], [track.constant]
    end = max(float(duration), 0.0)
    if end <= 0:
        times, values = track.steps(1e-9) if not track.period else track.pattern()
        return [0.0], [values[0]]
    times, values = track.steps(end)
    keep = [i for i, t in enumerate(times) if t < end]
    if len(keep) > MAX_PHASE_STEPS:
        raise ScheduleError(f"{name} changes {len(keep):,} times in the phase: at most {MAX_PHASE_STEPS:,}. "
                            "Use fewer, longer steps.")
    return [float(times[i]) for i in keep], [values[i] for i in keep]


def phase_words(spec: dict) -> str:
    """A phase schedule in words: "follows 100 if t % 24 < 16 else 40"."""
    return f"follows {describe(spec)}"


# ---------------------------------------------------------------------------
# Lowering to a StepSchedule
# ---------------------------------------------------------------------------

class _Track:
    """One covariate's path: constant, repeating (``period``) or laid out
    over a window."""

    def __init__(self, name: str, field: dict, spec: Optional[dict], constant):
        self.name = name
        self.field = field
        self.numeric = field.get("type") == "number"
        self.period: Optional[float] = None
        self.expr: Optional[Expression] = None
        self.table: Optional[list] = None
        self.constant = constant
        if spec is None:
            return
        if "expression" in spec:
            try:
                self.expr = Expression(spec["expression"])
            except ExpressionError as exc:
                raise ScheduleError(f"{name}: {exc}") from None
            if not self.expr.uses_t:
                self.constant, self.expr = self.expr(0.0), None
            else:
                self.period = self.expr.period
        else:
            self.table = [(float(r["t"]), r["value"] if not self.numeric else float(r["value"]))
                          for r in spec["table"]]
            self.period = spec.get("period")
            if len(self.table) == 1 and not self.period:
                self.constant, self.table = self.table[0][1], None

    @property
    def varies(self) -> bool:
        return self.expr is not None or self.table is not None

    def pattern(self) -> tuple[list, list]:
        """Steps within one period ``[0, P)``."""
        if self.table is not None:
            return [t for t, _ in self.table], [v for _, v in self.table]
        try:
            times, values = change_points(self.expr, 0.0, float(self.period))
        except ExpressionError as exc:
            raise ScheduleError(f"{self.name}: {exc}") from None
        keep = [i for i, t in enumerate(times) if t < self.period]
        if len(keep) > MAX_PATTERN:
            raise ScheduleError(f"{self.name}: at most {MAX_PATTERN:,} steps in one period.")
        return [times[i] for i in keep], [values[i] for i in keep]

    def steps(self, horizon: float) -> tuple[list, list]:
        """Steps over ``[0, horizon]``."""
        if not self.varies:
            return [0.0], [self.constant]
        if self.period:
            times, values = self.pattern()
            reps = int(math.ceil(horizon / self.period)) or 1
            if reps * len(times) > MAX_SEGMENTS:
                raise ScheduleError(
                    f"{self.name} repeats {reps:,} times by {_fmt(horizon)} — too many steps to follow "
                    "alongside another changing covariate. Give them the same repeat period, or shorten the window.")
            out_t, out_v = [], []
            for k in range(reps):
                out_t += [k * self.period + t for t in times]
                out_v += values
            return out_t, out_v
        if self.table is not None:
            return [t for t, _ in self.table], [v for _, v in self.table]
        try:
            return change_points(self.expr, 0.0, float(horizon))
        except ExpressionError as exc:
            raise ScheduleError(f"{self.name}: {exc}") from None


def _range_from_model(model, name: str) -> Optional[tuple]:
    """A covariate's range in the fitted data, from the model's own design
    (a column named as the covariate), when the inputs don't carry it."""
    names = list(getattr(model, "feature_names", None) or [])
    if name not in names:
        return None
    data = getattr(model, "data", None)
    Z = getattr(data, "Z", None) if data is not None else None
    if Z is None:
        fit_data = getattr(model, "_fit_data", None)
        Z = fit_data.get("Z") if isinstance(fit_data, dict) else None
    try:
        col = np.asarray(Z, dtype=float)[:, names.index(name)]
    except Exception:  # noqa: BLE001 - no design to read: no range
        return None
    col = col[np.isfinite(col)]
    return (float(col.min()), float(col.max())) if col.size else None


def fitted_range(model, field: dict) -> Optional[tuple]:
    """``(lowest, highest)`` of a numeric covariate in the model's data."""
    if field.get("type") != "number":
        return None
    lo, hi = field.get("min"), field.get("max")
    if lo is not None and hi is not None:
        return float(lo), float(hi)
    return _range_from_model(model, field["name"])


def _constant(field: dict, values: Optional[dict]):
    """A non-scheduled covariate's calculator value (its default when unset),
    read as the PH node reads it."""
    value = (values or {}).get(field["name"], field.get("default"))
    if field.get("type") == "number":
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(field.get("default") or 0.0)
    return str(value)


class Plan:
    """A block's covariates as one path: built with :meth:`schedule`."""

    def __init__(self, model, fields: list, schedules: dict, constants: Optional[dict] = None):
        if not fields:
            raise ScheduleError("This model has no covariates to schedule.")
        by_name = {f["name"]: f for f in fields}
        unknown = sorted(set(schedules) - set(by_name))
        if unknown:
            raise ScheduleError(f"Unknown covariate(s): {', '.join(unknown)}. This model's covariates are "
                                f"{', '.join(by_name)}.")
        checked = normalise(schedules, fields) or {}
        self.model = model
        self.fields = list(fields)
        self.tracks = [_Track(f["name"], f, checked.get(f["name"]), _constant(f, constants)) for f in fields]
        self.ranges = {f["name"]: fitted_range(model, f) for f in fields}
        varying = [tr for tr in self.tracks if tr.varies]
        periods = {tr.period for tr in varying}
        # Exact to any time when every changing covariate repeats on one period.
        self.period = periods.pop() if varying and len(periods) == 1 and None not in periods else None
        self.varies = bool(varying)
        self.notes: list = []

    # -- rows -------------------------------------------------------------
    def _rows(self, horizon: float) -> tuple[list, list]:
        """Joint change times and raw rows over ``[0, horizon]`` (or one
        period when the path repeats)."""
        steps = [tr.pattern() if (self.period and tr.varies) else tr.steps(horizon) for tr in self.tracks]
        times = sorted({t for ts, _ in steps for t in ts})
        rows = []
        for t in times:
            row = []
            for ts, vs in steps:
                i = bisect.bisect_right(ts, t) - 1
                row.append(vs[max(i, 0)])
            rows.append(row)
        return times, rows

    def _clip(self, times: list, rows: list) -> tuple[list, list]:
        """Numeric values held inside the fitted range, noting where they
        leave it."""
        self.notes = []
        out = [list(r) for r in rows]
        for j, tr in enumerate(self.tracks):
            if not tr.numeric:
                continue
            rng = self.ranges.get(tr.name)
            col = [r[j] for r in rows]
            if rng is None:
                if any(not math.isfinite(v) for v in col):
                    raise ScheduleError(f"{tr.name} goes to infinity, and the model's fitted range isn't known "
                                        "to hold it to.")
                continue
            lo, hi = rng
            unit = tr.field.get("unit")
            above = [t for t, v in zip(times, col) if v > hi]
            below = [t for t, v in zip(times, col) if v < lo]
            if above:
                self.notes.append(
                    f"{tr.name} goes above {_with_unit(hi, unit)}, the highest in the model's data, from t = "
                    f"{_fmt(above[0])}: it's held at {_with_unit(hi, unit)} there, as the model says nothing "
                    "beyond its data.")
            if below:
                self.notes.append(
                    f"{tr.name} goes below {_with_unit(lo, unit)}, the lowest in the model's data, from t = "
                    f"{_fmt(below[0])}: it's held at {_with_unit(lo, unit)} there, as the model says nothing "
                    "beyond its data.")
            for r in out:
                r[j] = min(max(r[j], lo), hi)
        # Rows equal after clipping are one step.
        keep = [0] + [i for i in range(1, len(out)) if out[i] != out[i - 1]]
        return [times[i] for i in keep], [out[i] for i in keep]

    def path(self, horizon: float) -> tuple[list, list, list]:
        """``(times, clipped rows, raw rows)`` over ``[0, horizon]`` (one
        period for a repeating path)."""
        times, raw = self._rows(horizon)
        clipped_t, clipped = self._clip(times, raw)
        limit = MAX_PATTERN if self.period else MAX_SEGMENTS
        if len(clipped_t) > limit:
            raise ScheduleError(
                f"The schedule has {len(clipped_t):,} steps by {_fmt(horizon)} — at most {limit:,} can be "
                "followed. Use fewer, longer steps or a shorter window.")
        return clipped_t, clipped, raw

    def schedule(self, horizon: float):
        """The SurPyval ``StepSchedule``: cyclic when the path repeats, else
        laid out to ``horizon`` (the last step held beyond it)."""
        import pandas as pd
        from surpyval import StepSchedule

        times, rows, _ = self.path(horizon)
        frame = pd.DataFrame(rows, columns=[tr.name for tr in self.tracks])
        for tr in self.tracks:
            frame[tr.name] = frame[tr.name].astype(float) if tr.numeric else frame[tr.name].astype(str)
        prepare = getattr(self.model, "_prepare_Z", None)
        try:
            Z = np.atleast_2d(np.asarray(prepare(frame) if callable(prepare) else frame.to_numpy(dtype=float),
                                         dtype=float))
            if self.period:
                if len(times) == 1:
                    return StepSchedule.from_changepoints([0.0], Z)
                return StepSchedule.cyclic(times, Z, self.period)
            return StepSchedule.from_changepoints(times, Z)
        except ScheduleError:
            raise
        except Exception as exc:  # noqa: BLE001 - the model's encoding refused a value
            raise ScheduleError(f"The model can't take this schedule: {exc}") from None


# ---------------------------------------------------------------------------
# The RBD node
# ---------------------------------------------------------------------------

def _segments_to(schedule, t: float) -> int:
    """How many steps SurPyval lays the schedule out to by ``t``."""
    n = max(len(schedule.edges) - 1, 1)
    if schedule.period:
        return int(math.ceil(max(float(t), 0.0) / float(schedule.period)) or 1) * n
    return n


def _cumulative_table(model, schedule, horizon: float) -> tuple:
    """``(starts, Z, H before each step, H(start, z) of each step)`` up to
    ``horizon``: a few numbers a step, from one call of the model's ``Hf``
    each for the steps' starts and ends. For proportional hazards and odds
    the cumulative hazard along a step path is the running total of each
    step's ``Hf(end, z) - Hf(start, z)`` (SurPyval's own sum), so a query
    then costs one more ``Hf`` call, never a steps x times table."""
    starts, ends, Z = schedule.segments(float(horizon))
    Z = np.atleast_2d(np.asarray(Z, dtype=float))
    with np.errstate(divide="ignore", invalid="ignore"):
        h_start = np.asarray(model.Hf(starts, Z), dtype=float).ravel()
        h_end = np.asarray(model.Hf(ends, Z), dtype=float).ravel()
    h_start[0] = 0.0  # the first step runs from 0, where H is 0
    before = np.concatenate([[0.0], np.cumsum(h_end - h_start)[:-1]])
    return np.asarray(starts, dtype=float), Z, before, h_start


def _cumulative_H(model, table: tuple, x: np.ndarray) -> np.ndarray:
    """The cumulative hazard at ``x`` from :func:`_cumulative_table`."""
    _, starts, Z, before, h_start = table
    out = np.full(x.shape, np.nan, dtype=float)
    out[x <= 0] = 0.0
    out[x == np.inf] = np.inf
    live = np.isfinite(x) & (x > 0)
    if live.any():
        xs = x[live]
        i = np.clip(np.searchsorted(starts, xs, side="right") - 1, 0, len(starts) - 1)
        with np.errstate(divide="ignore", invalid="ignore"):
            h = np.asarray(model.Hf(xs, Z[i]), dtype=float).ravel()
        out[live] = before[i] + (h - h_start[i])
    return out


def _cumulative_applies(model, schedule) -> bool:
    """Whether :func:`_cumulative_table` gives this model's ``Hf_tvc``:
    a proportional-hazards or -odds model on a baseline from 0, along a
    schedule from 0 — and checked against ``Hf_tvc`` itself at a few times
    over the first steps, so that a model the running total doesn't fit
    falls back to SurPyval's own sum (in chunks)."""
    try:
        from surpyval.univariate.regression._tvc_evaluation import PROPORTIONAL_HAZARD, PROPORTIONAL_ODDS

        if getattr(model, "kind", None) not in (PROPORTIONAL_HAZARD, PROPORTIONAL_ODDS):
            return False
        if float(model.distribution.support[0]) < 0 or float(schedule.edges[0]) != 0.0:
            return False
        edges = np.asarray(schedule.edges, dtype=float)
        finite = edges[np.isfinite(edges)]
        t_chk = float(schedule.period) * 2.5 if schedule.period else max(float(finite.max()) * 1.5, 1.0)
        table = (t_chk, *_cumulative_table(model, schedule, t_chk))
        x = np.concatenate([np.linspace(0.0, t_chk, 9)[1:], finite[1:6] + 1e-3 * t_chk])
        x = x[(x > 0) & (x <= t_chk)]
        want = np.asarray(model.Hf_tvc(x, schedule), dtype=float)
        got = _cumulative_H(model, table, x)
        return bool(np.allclose(got, want, rtol=1e-9, atol=1e-300))
    except Exception:  # noqa: BLE001 - not this model: SurPyval's own sum
        return False


_NODE_CLASS = None


def _node_class():
    global _NODE_CLASS
    if _NODE_CLASS is not None:
        return _NODE_CLASS
    from repyability import RegressionNode

    class ScheduledNode(RegressionNode):
        """RePyability's regression node along a covariate schedule, laid
        out (when it doesn't simply repeat) to cover every time it is asked
        for."""

        def __init__(self, model, plan: Plan, hi: Optional[float], name: str):
            self._plan = plan
            self._hi = hi
            self.label = name
            self._horizon = max(float(hi or 1.0) * 2.0, 1.0)
            self._cum = None  # the exact cumulative path's table, when it applies
            self._cumulative = False
            schedule = plan.schedule(self._horizon)
            self._cumulative = _cumulative_applies(model, schedule)
            super().__init__(model, schedule=schedule)

        def _too_fine(self, x_max: float, limit: int):
            from backend.services.rbd_analysis import AnalysisError

            return AnalysisError(
                f"{self.label}: its schedule is too fine for this calculation over {_fmt(x_max)} — it would mean "
                f"following more than {limit:,} steps. Use fewer, longer steps (e.g. a coarser repeat pattern), "
                "a shorter time axis or a smaller survived-to age.")

        def _cover(self, x) -> None:
            x = np.asarray(x, dtype=float)
            finite = x[np.isfinite(x)]
            x_max = float(finite.max()) if finite.size else 0.0
            plan = self._plan
            if plan.period:
                n = len(self.schedule.edges) - 1
                limit = MAX_CUMULATIVE_SEGMENTS if self._cumulative else MAX_CYCLIC_SEGMENTS
                if math.ceil(x_max / plan.period) * n > limit:
                    raise self._too_fine(x_max, limit)
                return
            if not plan.varies or x_max <= self._horizon:
                return
            self._horizon = x_max * 2.0
            try:
                self.schedule = plan.schedule(self._horizon)
            except ScheduleError as exc:
                from backend.services.rbd_analysis import AnalysisError

                raise AnalysisError(f"{self.label}: {exc}") from None
            self._cum = None
            self._grid = None

        def _H(self, x: np.ndarray) -> np.ndarray:
            """The cumulative hazard along the schedule at ``x``, within the
            memory guards: exactly from a per-segment running total where
            the model allows (:func:`_cumulative_table`), else SurPyval's
            ``Hf_tvc`` over chunks of the query times."""
            self._cover(x)
            if self._cumulative:
                return self._H_cumulative(x)
            finite = x[np.isfinite(x)]
            x_max = float(finite.max()) if finite.size else 0.0
            n_seg = _segments_to(self.schedule, x_max)
            chunk = max(1, MAX_EVAL_CELLS // max(n_seg, 1))
            if x.size <= chunk:
                return np.asarray(self.model.Hf_tvc(x, self.schedule), dtype=float)
            # Sorted, so each chunk lays the path out only to its own last time.
            order = np.argsort(x, kind="stable")
            out = np.empty(x.size, dtype=float)
            for k in range(0, x.size, chunk):
                idx = order[k:k + chunk]
                out[idx] = np.asarray(self.model.Hf_tvc(x[idx], self.schedule), dtype=float)
            return out

        def _H_cumulative(self, x: np.ndarray) -> np.ndarray:
            finite = x[np.isfinite(x)]
            x_max = max(float(finite.max()) if finite.size else 0.0, 1.0)
            if self._cum is None or x_max > self._cum[0]:
                horizon = max(x_max, self._cum[0] * 2.0 if self._cum else self._horizon)
                if _segments_to(self.schedule, horizon) > MAX_CUMULATIVE_SEGMENTS:
                    horizon = x_max
                if _segments_to(self.schedule, horizon) > MAX_CUMULATIVE_SEGMENTS:
                    raise self._too_fine(x_max, MAX_CUMULATIVE_SEGMENTS)
                self._cum = (horizon, *_cumulative_table(self.model, self.schedule, horizon))
            return _cumulative_H(self.model, self._cum, x)

        def _sf_at(self, x):
            x = np.atleast_1d(np.asarray(x, dtype=float))
            return np.exp(-self._H(x))

        def ff(self, x):
            scalar = np.ndim(x) == 0
            x = np.atleast_1d(np.asarray(x, dtype=float))
            out = -np.expm1(-self._H(x))
            return out[0] if scalar else out

        def cs(self, x, X):
            from repyability.utils.wrappers import conditional_survival

            return conditional_survival(self, x, X)

    _NODE_CLASS = ScheduledNode
    return ScheduledNode


def build_node(entry: dict, schedules: dict, constants: Optional[dict], label: str):
    """The block's reliability along its schedule (RePyability's
    ``RegressionNode``), from the live model ``entry``. Raises
    :class:`ScheduleError`."""
    model = entry["model"]
    if not hasattr(model, "sf_tvc"):
        raise ScheduleError("this model can't be evaluated along a schedule.")
    plan = Plan(model, entry.get("fields") or [], schedules, constants)
    grid = entry.get("grid")
    hi = float(grid[-1]) if grid is not None and len(grid) else None
    try:
        node = _node_class()(model, plan, hi, label)
    except ScheduleError:
        raise
    except ValueError as exc:  # RePyability's probe of the model along the path
        raise ScheduleError(str(exc)) from None
    node.schedule_notes = [f"{label}: {n}" for n in plan.notes]
    return node


def refuse(data: dict, ntype: str, label: str, repairable: bool) -> None:
    """Raise :class:`ScheduleError` where a block's schedule can't apply."""
    if not of_node(data):
        return
    if ntype == "standby" and (repairable or not _hot(data)):
        raise ScheduleError(f"{label}: {STANDBY_REASON}")


def _hot(data: dict) -> bool:
    raw = data.get("dormancy")
    if raw is None or raw == "":
        return not data.get("cold")
    try:
        return float(raw) >= 1.0
    except (TypeError, ValueError):
        return False


def check_static(schedules: dict, model: Optional[dict], label: str) -> None:
    """Structural checks without the fitted model (diagram validation)."""
    fields = (model or {}).get("covariates") or None
    try:
        normalise(schedules, fields)
    except ScheduleError as exc:
        raise ScheduleError(f"{label}: {exc}") from None


class Values(dict):
    """A block's calculator covariate values, with its schedules attached
    (``schedules``) for :func:`node`."""

    schedules: dict = {}


def _analysis_error(text: str):
    from backend.services.rbd_analysis import AnalysisError

    return AnalysisError(text)


def attach(data: dict, ntype: str, label: str, cov_values: Optional[dict]):
    """A non-repairable block's covariate values with its stored schedules
    attached, checked as far as the block's own model snapshot allows; the
    values unchanged when it has none (or isn't a regression block, which a
    schedule can't apply to). Raises ``AnalysisError``."""
    schedules = of_node(data)
    model = (data or {}).get("model") or {}
    if not schedules or model.get("kind") != "regression":
        return cov_values
    try:
        refuse(data, ntype, label, repairable=False)
        check_static(schedules, model, label)
    except ScheduleError as exc:
        raise _analysis_error(str(exc)) from None
    out = Values(cov_values or {})
    out.schedules = schedules
    return out


def node(entry: dict, cov_values: "Values", where: str):
    """:func:`build_node` for the analysis (``AnalysisError`` in plain words)."""
    try:
        return build_node(entry, cov_values.schedules, dict(cov_values), where)
    except ScheduleError as exc:
        raise _analysis_error(f"{where}: {exc}") from None


#: How far a schedule that neither repeats nor is a table is laid out for a
#: repairable block, in multiples of the model's own time axis (its last
#: step held beyond); fewer when that would be too many steps.
REPAIRABLE_LAYOUT = (20.0, 5.0, 1.0)


#: RePyability's refusals for a block on a schedule end with what to do in
#: Python; the same advice in the app's words.
_PLAIN = (
    ("Fit a parametric regression (e.g. surv.WeibullPH) in surpyval.",
     "Fit a parametric covariate model (e.g. Weibull PH) in Models instead."),
    ("Fit a proportional hazards, additive hazards, accelerated failure time or accelerated life model in "
     "surpyval.", "Fit a proportional hazards, additive hazards or accelerated failure time model in Models instead."),
    ("give a Kijima repair (kijima1 or kijima2) or none.",
     "give it a repair quality (Kijima I or II) or repair as good as new."),
    ("give a proportional or additive hazards model, or repairs and tasks that renew.",
     "use a proportional or additive hazards model, or repairs and tasks that make it as good as new."),
)


def plain_refusal(text: str) -> str:
    """RePyability's refusal of a block on a covariate schedule without the
    Python it suggests (other text unchanged)."""
    if "covariate schedule" not in text and "its covariates" not in text:
        return text
    for code, words in _PLAIN:
        text = text.replace(code, words)
    return text.replace("Component “", "“").replace("”: its covariates: ", "”: ")


def repairable_schedule(data: dict, ntype: str, label: str, resolve_model, horizon: Optional[float] = None):
    """``(live regression model, StepSchedule, notes)`` for a repairable
    diagram's block on a covariate schedule (RePyability's repairable
    ``"covariates"``), or None for a block without one (or no model
    resolver: structural checks only). Non-scheduled covariates hold the
    block's own value (``covariate_values``) or the fit's default. Raises
    ``AnalysisError`` in plain words."""
    schedules = of_node(data)
    model = (data or {}).get("model") or {}
    if not schedules or model.get("kind") != "regression":
        return None
    try:
        refuse(data, ntype, label, repairable=True)
        check_static(schedules, model, label)
    except ScheduleError as exc:
        raise _analysis_error(str(exc)) from None
    if resolve_model is None:
        return None
    model_id = model.get("modelId") or model.get("model_id")
    entry = resolve_model(model_id) if model_id else None
    if not entry:
        raise _analysis_error(f"{label}: saved model not found — re-fit it or pick another.")
    try:
        plan = Plan(entry["model"], entry.get("fields") or [], schedules, (data or {}).get("covariate_values"))
    except ScheduleError as exc:
        raise _analysis_error(f"{label}: {exc}") from None
    grid = entry.get("grid")
    axis = float(grid[-1]) if grid is not None and len(grid) else 1.0
    spans = [float(horizon)] if horizon else [axis * k for k in REPAIRABLE_LAYOUT]
    last: Optional[ScheduleError] = None
    for span in spans:
        try:
            schedule = plan.schedule(max(span, 1e-9))
            break
        except ScheduleError as exc:
            last = exc
    else:
        raise _analysis_error(f"{label}: {last}")
    notes = [f"{label}: {n}" for n in plan.notes]
    if plan.varies and not plan.period and any(tr.expr is not None for tr in plan.tracks):
        notes.append(f"{label}: its schedule is followed to t = {_fmt(span)} and its last value held after that.")
    return entry["model"], schedule, notes


def notes_of(reliabilities: dict) -> list:
    """The extrapolation warnings of a built diagram's scheduled blocks (a
    series or parallel block's unit included)."""
    out: list = []
    for model in reliabilities.values():
        for part in [model, *(getattr(model, "models", None) or [])]:
            out.extend(getattr(part, "schedule_notes", None) or [])
    return list(dict.fromkeys(out))


# ---------------------------------------------------------------------------
# The modal's live preview
# ---------------------------------------------------------------------------

def preview(entry: dict, schedules: dict, constants: Optional[dict] = None, t_max: Optional[float] = None,
            points: int = 160) -> dict:
    """Each covariate's stair-step path and the block's reliability over
    ``[0, t_max]`` (the model's own axis by default): what the node
    covariate modal draws as you type. Raises :class:`ScheduleError`."""
    grid = entry.get("grid")
    hi = float(t_max) if t_max not in (None, "") else (float(grid[-1]) if grid is not None and len(grid) else 1.0)
    if not (math.isfinite(hi) and hi > 0):
        raise ScheduleError("The window must be a positive time.")
    node = build_node(entry, schedules, constants, "This block")
    plan = node._plan
    x = np.linspace(0.0, hi, max(int(points), 2))
    with np.errstate(all="ignore"):
        sf = np.asarray(node.sf(x), dtype=float)
    times, rows, raw = plan.path(hi)
    if plan.period:
        # One period's pattern, repeated across the window for the picture.
        reps = int(math.ceil(hi / plan.period))
        cap = max(1, 2000 // max(len(times), 1))
        reps = min(reps, cap)
        times = [k * plan.period + t for k in range(reps) for t in times]
        rows = rows * reps
    covariates = []
    for j, tr in enumerate(plan.tracks):
        values = [r[j] for r in rows]
        keep = [0] + [i for i in range(1, len(values)) if values[i] != values[i - 1]]
        covariates.append({
            "name": tr.name,
            "type": "number" if tr.numeric else "category",
            "unit": tr.field.get("unit"),
            "scheduled": tr.varies,
            "times": [float(times[i]) for i in keep if times[i] <= hi],
            "values": [values[i] for i in keep if times[i] <= hi],
            "range": list(plan.ranges[tr.name]) if plan.ranges.get(tr.name) else None,
        })
    return {
        "x": x.tolist(),
        "sf": [float(v) if np.isfinite(v) else None for v in sf],
        "covariates": covariates,
        "repeats_every": plan.period,
        "warnings": list(plan.notes),
    }
