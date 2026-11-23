"""What a supporting task's impact does to a forecast (forecast plan step 7, Nov 2026; forecast-rules 4.2
and 4.3).

A supporting task (greasing, an oil change: supporting.py) keeps the part on the life its model
describes. While it's done as planned it changes nothing but its own line. Its impact, "the failure
rate × k while it isn't done", shows only when it isn't:

* **dropped**: the part runs at × k the whole time;
* **stretched** from its reference interval τ₀ (plus its grace g) to τ: the part runs on its normal
  hazard until the task is overdue, then at × k until it's next done. Averaged over a cycle that is
  × (1 + (k − 1) × the overdue share), the overdue share being 1 − τ₀(1 + g) ÷ τ (rule 8). Applied to
  the whole period as a hazard ratio (SurPyval's ``hr``), it's within about 1% of a full simulation
  while the interval is a small share of the life; past 20% of the mean life it's said to be
  approximate (rule 4.3);
* **shortened** below the reference: no modelled benefit (the model has no data there), said so;
* the plan itself already **past** its reference (the task's own interval made longer than the
  reference): the impact applies in the forecast as recorded too (rule 2);
* several supporting tasks on one part **multiply** (rule 6).

Nothing here is written: a what-if is worked out and shown beside the plan as recorded.
"""

from __future__ import annotations

import math

APPROX_SHARE = 0.20  # an interval past this share of the mean life: the averaged ratio is approximate


def plan_of(whatif: dict | None, task_id: str) -> dict | None:
    """The what-if for one task: {drop: true}, {interval: x} (in the task's unit), or None."""
    got = (whatif or {}).get(task_id)
    if not got:
        return None
    if got.get("drop"):
        return {"drop": True}
    try:
        value = float(got.get("interval"))
    except (TypeError, ValueError):
        return None
    return {"interval": value} if value > 0 else None


def multiplier(support: dict, task_interval, plan: dict | None) -> dict:
    """{mult, k, overdue_share, interval, reference, change, words} for one supporting task: the hazard
    ratio its impact puts on the part, as recorded (plan None) or under a what-if."""
    imp = (support or {}).get("impact") or {}
    k = imp.get("k")
    ref = float(((support or {}).get("reference") or {}).get("value") or task_interval or 0)
    grace = float((support or {}).get("grace") or 0.0) / 100.0
    tau = math.inf if (plan or {}).get("drop") else float((plan or {}).get("interval") or task_interval or ref)
    change = "drop" if (plan or {}).get("drop") else ("interval" if plan else None)
    out = {"k": k, "reference": ref, "grace": grace * 100, "interval": None if math.isinf(tau) else tau,
           "change": change}
    if not k:
        return {**out, "mult": 1.0, "overdue_share": 0.0, "words": "supports, no modelled impact: no change"}
    limit = ref * (1.0 + grace)
    if math.isinf(tau):
        return {**out, "mult": float(k), "overdue_share": 1.0,
                "words": f"not done: the failure rate × {k:.3g} the whole time"}
    if tau <= limit:
        words = ("shorter than its reference interval: no modelled benefit (the model has no data there)"
                 if tau < ref else "within its reference interval and grace: no change")
        return {**out, "mult": 1.0, "overdue_share": 0.0, "words": words}
    share = 1.0 - limit / tau
    mult = 1.0 + (float(k) - 1.0) * share
    return {**out, "mult": mult, "overdue_share": share,
            "words": f"every {tau:g} against a reference of {ref:g}: overdue {share:.0%} of the time, so the failure "
                     f"rate × {mult:.3g} on average"}


def applies(m, task: dict, position_id: str, mode_ids) -> bool:
    """Whether the supporting task holds up this life: a life for failure modes it supports; or, for
    support of the part's whole life, a life at the task's position or inside it."""
    from backend.maintenance import service as sv

    support = task.get("support") or {}
    named = set(support.get("failure_mode_ids") or [])
    if named:
        if mode_ids is None:
            return any(fm["id"] in named for fm in m._modes_on(position_id))
        return bool(named & set(mode_ids))
    subject = sv._subject(m.s, m.org, task)
    if subject is None:
        return False
    return subject["id"] == position_id or subject["id"] in m._ancestor_ids(position_id)


def supporting_tasks(m, position_ids) -> list[dict]:
    """The live supporting tasks on these positions and above them."""
    from backend.maintenance import service as sv

    seen, out = set(), []
    wanted = set(position_ids)
    for pid in list(position_ids):
        wanted.update(m._ancestor_ids(pid))
    for task in m.s.nodes(m.org, "Task"):
        if task.get("retired") or not task.get("support") or task["id"] in seen:
            continue
        subject = sv._subject(m.s, m.org, task)
        if subject is not None and subject["id"] in wanted:
            seen.add(task["id"])
            out.append(task)
    return sorted(out, key=lambda t: (t.get("name") or "", t["id"]))


def life_ratio(m, tasks: list[dict], position_id: str, mode_ids, whatif: dict | None, every_in_life=None,
               mean_life=None) -> dict | None:
    """The hazard ratio on one life from the supporting tasks that hold it up: {mult (their product),
    tasks [{id, name, ...multiplier}], approximate}; None when it's 1 (nothing changes)."""
    rows = []
    for task in tasks:
        if not applies(m, task, position_id, mode_ids):
            continue
        got = multiplier(task["support"], task.get("interval"), plan_of(whatif, task["id"]))
        if got["mult"] == 1.0:
            continue
        approx = False
        if got["interval"] is not None and got["overdue_share"] < 1.0 and every_in_life and mean_life:
            tau = every_in_life(got["interval"], task.get("unit"))
            approx = tau is not None and mean_life > 0 and tau / mean_life > APPROX_SHARE
        rows.append({"id": task["id"], "name": task.get("name") or "", **got, "approximate": approx})
    if not rows:
        return None
    return {"mult": math.prod(r["mult"] for r in rows), "tasks": rows, "approximate": any(r["approximate"] for r in rows)}


# ---- Optimise for a supporting task (forecast plan step 8; forecast-rules 4.4, decision 6) ----------------

CURVE_NEEDED = ("A best interval needs a curve: how the failure rate changes as the interval changes, fitted from "
                "data that records the time since service (a covariate fit). One number, × k, gives a break-even, "
                "not an interval.")


def interval_from_curve(curve: dict | None) -> dict | None:
    """The best interval from a fitted curve of the hazard against the interval (the future variable-speed
    ageing model), inside the range the data covers; None until one is fitted. Kept here so Optimise reads
    an interval from it the day it exists, without changing its screen."""
    return None


def break_even(m, fetch, task_id: str, root: str | None = None) -> dict | None:
    """For a supporting task with a one-number impact (× k if it isn't done): the break-even cost of one
    doing, which is the failures one interval of it holds off, in money. In words: it pays for itself if
    it costs less than (cost of a problem) × (problems an hour) × (k − 1) × (the reference interval). With
    an inspection finding some in time, a problem costs (found × the follow-on) + (missed × the corrective
    response). {k, reference, unit, per_problem, rate, break_even, task_cost, ratio, words, lives, gaps,
    interval: None, interval_needs}; None when the task isn't supporting with an impact."""
    from backend.maintenance import forecast_lines, responses
    from backend.maintenance import service as sv

    task = m._get(str(task_id), "Task")
    support = task.get("support") or {}
    k = (support.get("impact") or {}).get("k")
    if not k:
        return None
    subject = sv._subject(m.s, m.org, task)
    if subject is None or subject.get("label") != "Position":
        return None
    ref = float((support.get("reference") or {}).get("value") or task.get("interval") or 0)
    unit = sv._norm_unit(task.get("unit")) or "days"
    fc = forecast_lines.node_forecast(m, fetch, "position", subject["id"], root, 12)
    hours = sum(float(r.get("hours") or 0.0) for r in fc.get("rows") or [])
    days = (sv.date.fromisoformat(fc["end"]) - sv.date.fromisoformat(fc["start"])).days + 1
    span = hours if unit == "hours" else days / sv._DAYS_PER.get(unit, 1.0)
    gaps, lives, total = [], [], 0.0
    if not span:
        gaps.append("no running hours in the horizon to count failures an hour by")
    for row in fc.get("models") or []:
        modes = [x["id"] for x in row.get("failure_modes") or []] or None
        if not applies(m, task, row["position"]["id"], modes):
            continue
        found = float(row.get("found_share") or 0.0)
        left = float(row.get("expected_failures") or 0.0)
        problems = left / (1.0 - found) if found and found < 1.0 else left
        fail_cost = row.get("cost_per_failure")
        follow = responses.response_view(m, row["response_mode"], "found") if found and row.get("response_mode") else None
        follow_cost = (follow or {}).get("cost_each")
        what = f"{row['position']['name']}: {', '.join(x['text'] for x in row.get('failure_modes') or []) or row.get('name')}"
        if fail_cost is None:
            gaps.append(f"{what}: no cost of a failure, so its share isn't counted (add If it fails anyway)")
            continue
        if found and follow_cost is None:
            gaps.append(f"{what}: nothing recorded for a find, so finds are costed as nothing")
        per_problem = (1.0 - found) * float(fail_cost) + found * float(follow_cost or 0.0)
        rate = problems / span if span else 0.0
        share = per_problem * rate * (float(k) - 1.0) * ref
        total += share
        lives.append({"what": what, "problems": problems, "found_share": found or None, "per_problem": per_problem,
                      "rate": rate, "break_even": share})
    view = m._task_view(task)
    own = (view.get("cost") or {}).get("amount")
    unit_word = "h" if unit == "hours" else unit
    out = {"kind": "break_even", "k": k, "reference": ref, "unit": unit, "task_cost": own, "lives": lives,
           "gaps": gaps, "break_even": total if lives else None, "interval": interval_from_curve(None),
           "interval_needs": CURVE_NEEDED, "source": support.get("source") or "assumed",
           "assumed": (support.get("source") or "assumed") == "assumed"}
    if not lives:
        out["words"] = ("No break-even: none of the failures it holds up has a cost of a failure yet."
                        if gaps else "No break-even: no life model here that this task holds up.")
        return out
    out["ratio"] = (float(own) / total) if own is not None and total > 0 else None
    text = (f"It pays for itself if one doing costs less than ${total:,.0f}: the failures one {ref:g} {unit_word} "
            f"interval of it holds off (failure rate × {k:g} while it isn't done).")
    if own is not None:
        cost = f"{float(own):,.2f}".replace(".00", "")
        text += f" It costs ${cost} a time" + (f", {out['ratio']:.0%} of that." if out["ratio"] is not None else ".")
    out["words"] = text
    return out
