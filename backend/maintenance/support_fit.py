"""A supporting task's impact fitted from history (forecast plan step 9, Nov 2026; forecast-rules 4.7).

The impact is one number: the failure rate × k while the task is overdue (past its reference interval
plus its grace). From the records it can be estimated, not assumed:

* **the history:** each item fitted where the task holds the life up (its position and below, or the
  positions of the failure modes it names), from when it went in to when it came out (a failure of a
  supported mode, or still running); the task's doings (its closed work orders, and when it was last
  done); the clock (the hours counter there, else the calendar for a task by the calendar). Each
  item's time is cut where the task falls overdue and where it's done again, so every stretch is
  "on time" or "overdue";
* **a covariate fit** (SurPyval's ``WeibullPH.fit_tvc_timeline``, the age since the item went in as
  the time, overdue as a time-varying covariate): the hazard ratio exp(b) with its 90% two-sided range;
* **a group comparison** beside it: failures per hour overdue against failures per hour on time
  (exact conditional range), which ignores ageing but needs nothing fitted;
* **the identifiability check**: if service timing barely varies (almost all the time on time, or
  almost all of it overdue), or there are too few failures, the effect can't be estimated, and it
  says so rather than give a number.

A range that includes 1 is "not shown to matter in this data": offered as "supports, no modelled
impact". The study behind this (two clocks and variable-speed ageing on SurPyval 0.29) found that
fits like this need varied service timing; with everyone on time, nothing can be said. Reads only;
using the answer is the task's support record (``set_task_support``, source "fitted", with the fit as
its evidence).
"""

from __future__ import annotations

import math
import warnings
from datetime import date

import numpy as np

LEVEL = 0.90
MIN_FAILURES = 5
MIN_SHARE = 0.02  # less than 2% of the time overdue (or on time): service timing barely varies


def _units(units: list[dict]):
    """SurPyval's timeline rows from [{rows: [(a0, a1, overdue)], failed}]: one row per stretch (its start
    and its covariate), then the end with c 0 (failed) or 1 (still running)."""
    ids, xs, zs, cs = [], [], [], []
    for n, u in enumerate(units):
        rows = [r for r in u["rows"] if r[1] > r[0]]
        if not rows:
            continue
        for a0, _a1, z in rows:
            ids.append(n)
            xs.append(a0)
            zs.append(float(z))
            cs.append(1)
        ids.append(n)
        xs.append(rows[-1][1])
        zs.append(0.0)
        cs.append(0 if u["failed"] else 1)
    return np.array(ids), np.array(xs, float), np.array(zs, float)[:, None], np.array(cs)


def _exposure(units: list[dict]) -> dict:
    t_on = t_late = 0.0
    f_on = f_late = 0
    for u in units:
        rows = [r for r in u["rows"] if r[1] > r[0]]
        for a0, a1, z in rows:
            if z:
                t_late += a1 - a0
            else:
                t_on += a1 - a0
        if u["failed"] and rows:
            if rows[-1][2]:
                f_late += 1
            else:
                f_on += 1
    return {"t_on": t_on, "t_late": t_late, "f_on": f_on, "f_late": f_late}


def group_comparison(e: dict) -> dict | None:
    """Failures per hour overdue against on time: the rate ratio and its exact 90% range (conditional on
    the total: the overdue failures are binomial with chance π = T_late·k ÷ (T_on + T_late·k))."""
    from scipy.stats import beta

    f, t_on, t_late = e["f_on"] + e["f_late"], e["t_on"], e["t_late"]
    if not f or not t_on or not t_late:
        return None
    a = (1 - LEVEL) / 2
    lo_p = beta.ppf(a, e["f_late"], f - e["f_late"] + 1) if e["f_late"] else 0.0
    hi_p = beta.ppf(1 - a, e["f_late"] + 1, f - e["f_late"]) if e["f_late"] < f else 1.0

    def k_of(p):
        return (p / (1 - p)) * (t_on / t_late) if p < 1 else math.inf

    k = (e["f_late"] / t_late) / (e["f_on"] / t_on) if e["f_on"] else math.inf
    return {"k": k, "range": [k_of(lo_p), k_of(hi_p)], "method": "group comparison: failures per hour overdue "
            "against on time"}


def covariate_fit(units: list[dict]) -> dict | None:
    """SurPyval WeibullPH.fit_tvc_timeline: age since fitted as the time, overdue (0 or 1) as a time-varying
    covariate; the hazard ratio exp(b) and its 90% two-sided range."""
    import surpyval as sp

    i, x, z, c = _units(units)
    if not len(i):
        return None
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            m = sp.WeibullPH.fit_tvc_timeline(i=i, x=x, Z=z, c=c)
            lo, hi = m.param_cb("coef_0", alpha_ci=1 - LEVEL)
        b = float(np.asarray(m.params, float)[2])
    except Exception:  # noqa: BLE001 - a fit that doesn't converge gives no number, said so
        return None
    if not all(math.isfinite(v) for v in (b, lo, hi)):
        return None
    alpha, shape = (float(v) for v in np.asarray(m.params, float)[:2])
    return {"k": math.exp(b), "range": [math.exp(float(lo)), math.exp(float(hi))],
            "method": "covariate fit (SurPyval Weibull PH, overdue as a time-varying covariate)",
            "baseline": {"alpha": alpha, "beta": shape}}


def estimate(units: list[dict]) -> dict:
    """The impact from a history (see the module docstring): {identifiable, why, k, range, method, shown,
    words, covariate, group, exposure}."""
    e = _exposure(units)
    failures = e["f_on"] + e["f_late"]
    total = e["t_on"] + e["t_late"]
    share = e["t_late"] / total if total else 0.0
    out = {"exposure": {**e, "overdue_share": share, "failures": failures}, "identifiable": False,
           "k": None, "range": None, "method": None, "shown": False, "covariate": None, "group": None}
    if failures < MIN_FAILURES:
        out["why"] = (f"Too few failures to estimate it: {failures} in this history ({MIN_FAILURES} or more are "
                      "needed).")
    elif share < MIN_SHARE or share > 1 - MIN_SHARE:
        out["why"] = (f"Service timing barely varies ({share:.0%} of the time overdue), so the effect can't be "
                      "estimated: the data has nothing to compare.")
    if out.get("why"):
        out["words"] = out["why"]
        return out
    out["group"] = group_comparison(e)
    out["covariate"] = covariate_fit(units)
    best = out["covariate"] or out["group"]
    if best is None:
        out["why"] = out["words"] = "The fit didn't settle on an answer: the history can't say."
        return out
    lo, hi = best["range"]
    out.update(identifiable=True, k=best["k"], range=[lo, hi], method=best["method"], shown=lo > 1.0 or hi < 1.0)

    def num(v):
        return "∞" if not math.isfinite(v) else f"{v:.2g}" if v < 10 else f"{v:,.0f}"

    rng = f"90% two-sided: {num(lo)} to {num(hi)}"
    if not out["shown"]:
        out["words"] = (f"Not shown to matter in this data: failure rate × {num(best['k'])} while overdue ({rng}), "
                        "a range that includes no change. Record it as supporting with no modelled impact.")
    elif best["k"] < 1:
        out["words"] = (f"Overdue looks no worse here (× {num(best['k'])}, {rng}): the impact is recorded as no "
                        "modelled impact.")
        out["shown"] = False
    else:
        out["words"] = (f"Fitted: failure rate × {num(best['k'])} while overdue ({rng}), from {failures} failures "
                        f"and {share:.0%} of the time overdue.")
    return out


# ---- the history from the records -----------------------------------------------------------------

def history(m, task: dict) -> tuple[list[dict], dict]:
    """The items' stretches on time and overdue, from the records: ([{rows, failed, position}], {clock,
    reference, services, why?})."""
    from backend.maintenance import service as sv
    from backend.maintenance.position_forecast import _subtree

    support = task.get("support") or {}
    ref = float((support.get("reference") or {}).get("value") or task.get("interval") or 0)
    limit_units = ref * (1.0 + float(support.get("grace") or 0.0) / 100.0)
    unit = sv._norm_unit(task.get("unit")) or "days"
    subject = sv._subject(m.s, m.org, task)
    info = {"reference": ref, "unit": unit, "services": 0, "items": 0}
    if subject is None or subject.get("label") != "Position":
        return [], {**info, "why": "Only a task on a position has a history to fit from."}
    named = set(support.get("failure_mode_ids") or [])
    if named:
        positions = sorted({m.s.inn(m.org, fm, "CAN_FAIL_AS")[0]["id"] for fm in named
                            if m.s.inn(m.org, fm, "CAN_FAIL_AS")})
    else:
        positions = [n["id"] for n, _d in _subtree(m, subject["id"])]
    services = sorted({w["closed"][:10] for w in m.s.inn(m.org, task["id"], "FOR")
                       if w.get("label") == "WorkOrder" and w.get("status") == "closed" and w.get("closed")})
    if task.get("last_done") and not m._renewed_by_fit(task):
        services = sorted(set(services) | {task["last_done"][:10]})
    info["services"] = len(services)
    today = m.today()
    units = []
    for pid in positions:
        if unit == "hours":
            counter = m._use_counter(pid, "hours")
            readings = sv._readings(m.s, m.org, counter, m.tz) if counter else []
            if not readings:
                continue

            def clock(day, readings=readings):
                v = sv._reading_at(readings, day)
                return None if v is None else float(v)
            limit = limit_units
        elif unit in sv.CALENDAR_UNITS:
            def clock(day):
                return float(date.fromisoformat(day[:10]).toordinal())
            limit = limit_units * sv._DAYS_PER[unit]
        else:
            return [], {**info, "why": f"A task by {task.get('unit')} can't be fitted yet: hours or the calendar only."}
        for f in m._fitments_at(pid):
            if f.get("voided") or not f.get("from"):
                continue
            start, end = str(f["from"])[:10], str(f.get("to") or today)[:10]
            t0, t1 = clock(start), clock(end)
            if t0 is None or t1 is None or t1 <= t0:
                continue
            # A new item arrives serviced (rule 11): its clock since service starts at the fitting.
            rows, cur, served = [], t0, t0
            cuts = sorted(c for c in (clock(d) for d in services if start < d <= end) if c is not None and c > t0)
            for nxt in [*cuts, t1]:
                if nxt <= cur:
                    served = max(served, nxt)
                    continue
                due = served + limit
                if cur < due < nxt:
                    rows.append((cur - t0, due - t0, 0))
                    rows.append((due - t0, nxt - t0, 1))
                else:
                    rows.append((cur - t0, nxt - t0, 1 if due <= cur else 0))
                cur = served = nxt
            failed = f.get("end_reason") == "failure" and (not named or f.get("failure_mode_id") in named)
            units.append({"rows": rows, "failed": failed, "position": pid})
    info["items"] = len(units)
    info["clock"] = "running hours from the hours counter" if unit == "hours" else "days on the calendar"
    if not units:
        info["why"] = ("No items with a history here: nothing has been fitted and run where this task holds the life "
                       "up" + (", or no hours counter readings" if unit == "hours" else "") + ".")
    return units, info


class SupportFitOps:
    """Fitting a supporting task's impact from its history (methods added to ``Maintenance``)."""

    def fit_support(self, task_id: str) -> dict:
        """What the history says the impact is (reads only): {task, history, ...estimate}."""
        from backend.maintenance import service as sv

        task = self._get(str(task_id), "Task")
        if not task.get("support"):
            raise sv.Invalid("Mark the task as supporting first (it keeps the item on its life), then fit its impact.")
        units, info = history(self, task)
        base = {"task": {"id": task["id"], "name": task.get("name") or ""}, "history": info}
        if info.get("why"):
            return {**base, "identifiable": False, "k": None, "range": None, "shown": False, "words": info["why"],
                    "exposure": None}
        got = estimate(units)
        if got.get("k") is not None and got["shown"] and got["k"] >= 1:
            got["use"] = {"impact": {"form": "hazard_ratio", "k": float(f"{min(got['k'], 100.0):.3g}")},
                          "source": "fitted",
                          "evidence": {"method": got["method"], "k": got["k"], "low": got["range"][0],
                                       "high": got["range"][1] if math.isfinite(got["range"][1]) else None,
                                       "failures": got["exposure"]["failures"],
                                       "overdue_share": got["exposure"]["overdue_share"], "fitted_on": self.today()}}
        elif got.get("identifiable"):
            got["use"] = {"impact": None, "source": "fitted",
                          "evidence": {"method": got["method"], "k": got["k"], "low": got["range"][0],
                                       "high": got["range"][1] if math.isfinite(got["range"][1]) else None,
                                       "failures": got["exposure"]["failures"],
                                       "overdue_share": got["exposure"]["overdue_share"], "fitted_on": self.today(),
                                       "not_shown": True}}
        return {**base, **got}
