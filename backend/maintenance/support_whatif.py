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
