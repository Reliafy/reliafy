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
now" figures all take it unchanged. Repairable diagrams refuse schedules (a
repaired item would restart its path from its own time zero, not the
diagram's clock), and so do standby spares (a spare's path would start when
it's switched in).
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

REPAIRABLE_REASON = (
    "covariate schedules apply to non-repairable diagrams only: after a repair the item's covariates would "
    "restart from its own time zero, not follow the diagram's clock. Remove the schedule (Set covariates → "
    "Constant) or make the diagram non-repairable.")
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
            super().__init__(model, schedule=plan.schedule(self._horizon))

        def _cover(self, x) -> None:
            x = np.asarray(x, dtype=float)
            finite = x[np.isfinite(x)]
            x_max = float(finite.max()) if finite.size else 0.0
            plan = self._plan
            if plan.period:
                n = len(self.schedule.edges) - 1
                if math.ceil(x_max / plan.period) * n > MAX_CYCLIC_SEGMENTS:
                    from backend.services.rbd_analysis import AnalysisError

                    raise AnalysisError(
                        f"{self.label}: its schedule repeats every {_fmt(plan.period)}, too often to follow out to "
                        f"{_fmt(x_max)} (more than {MAX_CYCLIC_SEGMENTS:,} steps). Shorten the window.")
                return
            if not plan.varies or x_max <= self._horizon:
                return
            self._horizon = x_max * 2.0
            try:
                self.schedule = plan.schedule(self._horizon)
            except ScheduleError as exc:
                from backend.services.rbd_analysis import AnalysisError

                raise AnalysisError(f"{self.label}: {exc}") from None
            self._grid = None

        def _sf_at(self, x):
            self._cover(x)
            return super()._sf_at(x)

        def ff(self, x):
            self._cover(np.atleast_1d(np.asarray(x, dtype=float)))
            return super().ff(x)

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
    if repairable:
        raise ScheduleError(f"{label}: {REPAIRABLE_REASON}")
    if ntype == "standby" and not _hot(data):
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


def refuse_repairable(data: dict, label: str) -> None:
    """A repairable diagram's block with a schedule: ``AnalysisError``."""
    if of_node(data) and ((data or {}).get("model") or {}).get("kind") == "regression":
        raise _analysis_error(f"{label}: {REPAIRABLE_REASON}")


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
