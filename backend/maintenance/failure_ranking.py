"""The failure ranking (FRACAS): which positions, parts or failure modes fail most below a
position, over a window (the Explorer's History tab, Ranking; Nov 2026).

What's counted, in one place:

* **failure reports** at the position and everything inside it, by when they occurred,
  except rejected ones; **no fault found** is a removal, not a failure, so it is shown as
  its own count and never ranked;
* **corrective failures in the log**: an item taken off for a failure (``item.removed``
  or a past fitment with reason failure), an item an inspection found failed
  (``fitment.found_failed``) and a repair recorded against a failure mode. Each is the same
  failure as a report when a report at the same position names the same failure mode (or
  either names none) within ``SAME_FAILURE_DAYS`` days of it (an item with several reports
  is several failures, so the life data's one-failure-per-fitment rule isn't used here). One report
  takes the place of at most one event.

Each group's **operating hours** over the window come from each position's running time,
on one stated basis (Derryn, 21 Nov 2026): its duty (the operating plan's hours a day,
``running_clock``), else its hours counter's recent rate, else running all the time (24 h
a day). The rate a group has is ``failures / hours``, with a **90% two-sided** range from
the exact Poisson (chi-square) limits. Its **expected** count is what it would have at the
pooled rate of every group here given its hours, and the p-value is the exact Poisson
chance of this many or more (or this few or fewer) by chance alone. No verdicts: the
numbers and what they mean, the analyst decides. Small counts (fewer than three, with
fewer than three expected) say "too few to tell".

**Downtime and cost** of each failure are its failure mode's figures per failure (else its
position class's: ``failure_costs.py``), not typed on the report; failures with none set
are counted and said.

Reads only; nothing is stored.
"""

from __future__ import annotations

import math
from datetime import date, timedelta

from dateutil.relativedelta import relativedelta
from scipy import stats

from backend.maintenance import service as svc
from backend.maintenance.service import Invalid, Maintenance, NOT_FAILURE_STATUSES
from backend.services import running_clock

RANK_BY = ("failures", "rate", "downtime", "cost")
GROUP_BY = ("position", "part", "failure_mode")
WINDOWS = ("12m", "all", "range")
#: A corrective event this close to a report at the same position is the same failure.
SAME_FAILURE_DAYS = 14
#: Fewer failures than this, with fewer expected too: "too few to tell".
TOO_FEW = 3
LEVEL = 0.90
PER = 1000.0  # rates per 1,000 operating hours
MAX_ROWS = 500


# ---- statistics ----------------------------------------------------------------------------

def poisson_range(n: int, hours: float | None, level: float = LEVEL) -> dict | None:
    """The rate per 1,000 h for n failures in ``hours`` with its exact two-sided range
    (Garwood's chi-square limits): {value, lower, upper}; None without hours."""
    if not hours or hours <= 0:
        return None
    a = (1 - level) / 2
    lo = 0.0 if n == 0 else stats.chi2.ppf(a, 2 * n) / 2
    hi = stats.chi2.ppf(1 - a, 2 * n + 2) / 2
    k = PER / hours
    return {"value": n * k, "lower": float(lo) * k, "upper": float(hi) * k}


def chance(n: int, expected: float) -> tuple[float, str]:
    """(p, direction): the exact Poisson chance of n or more when n is at least the
    expected count ("more"), else of n or fewer ("fewer")."""
    if n >= expected:
        return float(stats.poisson.sf(n - 1, expected)) if n > 0 else 1.0, "more"
    return float(stats.poisson.cdf(n, expected)), "fewer"


def _two_figures(x: float) -> str:
    if x < 100:
        return f"{round(x):,}"
    digits = int(math.floor(math.log10(x))) - 1
    return f"{int(round(x, -digits)):,}"


def chance_words(p: float) -> str:
    """"less than 1 time in 1,000", "about 1 time in 45", "about 3 times in 10"."""
    if p < 0.001:
        return "less than 1 time in 1,000"
    if p >= 0.15:
        tens = max(1, min(10, round(p * 10)))
        return "about every time" if tens >= 10 else f"about {tens} {'time' if tens == 1 else 'times'} in 10"
    return f"about 1 time in {_two_figures(1 / p)}"


def _num(x: float) -> str:
    """3 significant figures, in full."""
    if x == 0:
        return "0"
    if abs(x) >= 100:
        return f"{round(x):,}"
    digits = 2 - int(math.floor(math.log10(abs(x))))
    return f"{round(x, digits):,.{max(0, digits)}f}"


def _plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n:,} {one if n == 1 else (many or one + 's')}"


# ---- the scope -----------------------------------------------------------------------------

def _scope_tree(m: Maintenance, root_id: str) -> tuple[list[str], dict[str, str]]:
    """Every live position inside ``root_id`` as the tree nests them (``_report_scope``'s
    walk), and each one's parent position."""
    out, queue, parent = [root_id], [root_id], {}
    seen = {root_id}
    while queue and len(out) < m._MAX_BELOW:
        nid = queue.pop(0)
        holders = [nid]
        fitted = m.current_fitment(nid)
        item = fitted and m.s.inn(m.org, fitted["id"], "IN")
        if item:
            holders.append(item[0]["id"])
        for holder in holders:
            for c in m.s.inn(m.org, holder, "PART_OF"):
                if c["label"] == "Position" and c["id"] not in seen and not c.get("retired"):
                    seen.add(c["id"])
                    parent[c["id"]] = nid
                    out.append(c["id"])
                    queue.append(c["id"])
    return out, parent


class _Hours:
    """Each position's operating hours a day, on the one basis (duty, readings, all the time)."""

    def __init__(self, m: Maintenance, root: str | None):
        self.m, self.root, self.memo = m, root, {}

    def rate(self, pid: str) -> tuple[float, str]:
        if pid in self.memo:
            return self.memo[pid]
        m = self.m
        clock = running_clock.for_position(m, pid, self.root)
        if clock.basis in ("duty", "idle"):
            out = (clock.hours_per_day, "duty")
        else:
            counter = m._use_counter(pid, "hours")
            readings = svc._readings(m.s, m.org, counter, m.tz) if counter else []
            per_day = svc._rate(readings) if len(readings) >= 2 else None
            out = (min(per_day, 24.0), "readings") if per_day and per_day > 0 else (24.0, "continuous")
        self.memo[pid] = out
        return out

    def hours(self, pid: str, days: float) -> float:
        return self.rate(pid)[0] * max(0.0, days)


def _window(m: Maintenance, window, since, until) -> dict:
    today = date.fromisoformat(m.today())
    window = window or ("range" if since or until else "12m")
    if window not in WINDOWS:
        raise Invalid(f"window is one of {', '.join(WINDOWS)} (12m: the last 12 months, the default).")
    hi = date.fromisoformat(svc._day(until, "until date")) if until else today
    hi = min(hi, today)
    if window == "12m":
        lo = today - relativedelta(years=1) + timedelta(days=1)
    elif window == "range" and since:
        lo = date.fromisoformat(svc._day(since, "since date"))
    else:
        lo = None  # all: from the first record in the scope
    if lo is not None and lo > hi:
        raise Invalid("since is after until.")
    return {"kind": window, "since": lo, "until": hi}


# ---- the failures --------------------------------------------------------------------------

def _part_key(m: Maintenance, item: dict | None) -> tuple[str, str, str | None] | None:
    """(key, name, part id) of an item's part number, else its item class; None with neither."""
    if not item:
        return None
    part = m._item_part(item["id"])
    if part and part.get("part_number"):
        return ("part:" + part["part_number"].strip().lower(), part["part_number"], part["id"])
    cls, _ = m._effective_class(item)
    if cls and cls.get("name"):
        return ("class:" + cls["name"].strip().lower(), cls["name"], None)
    return None


def _report_part(r: dict) -> tuple[str, str, str | None] | None:
    if r.get("part_number"):
        return ("part:" + r["part_number"].strip().lower(), r["part_number"], r.get("part_id"))
    if r.get("item_class_name"):
        return ("class:" + r["item_class_name"].strip().lower(), r["item_class_name"], None)
    return None


def _events(m: Maintenance, positions: list[str]) -> list[dict]:
    """Corrective failures recorded in the log at these positions (not yet matched to reports)."""
    wanted = set(positions)
    out = []
    for pid in positions:
        fitments = m._fitments_at(pid)
        if not fitments:
            continue
        for f in fitments:
            day, source = None, None
            if f.get("found_failed"):
                day, source = f["found_failed"]["on"], "found failed at an inspection"
            elif f.get("end_reason") == "failure" and f.get("to"):
                day, source = f["to"], "removed for a failure"
            if day is None:
                continue
            item = m.s.inn(m.org, f["id"], "IN")
            out.append({"position_id": pid, "day": day[:10], "mode_id": f.get("failure_mode_id"),
                        "item": item[0] if item else None, "source": source, "fitment_id": f["id"]})
    for a in m.s.nodes(m.org, "Action"):
        if a.get("kind") != "repair":
            continue
        modes = m.s.out(m.org, a["id"], "FOUND")
        on = m.s.out(m.org, a["id"], "ON")
        fitment = next((x for x in on if x["label"] == "Fitment"), None)
        at = fitment and m.s.out(m.org, fitment["id"], "AT")
        pid = at[0]["id"] if at else None
        if not modes or pid not in wanted:
            continue
        item = m.s.inn(m.org, fitment["id"], "IN")
        out.append({"position_id": pid, "day": str(a["on"])[:10], "mode_id": modes[0]["id"],
                    "item": item[0] if item else None, "source": "a repair", "action_id": a["id"]})
    return out


def _same(r: dict, e: dict) -> bool:
    if r["position_id"] != e["position_id"]:
        return False
    gap = abs((date.fromisoformat(r["occurred_on"]) - date.fromisoformat(e["day"])).days)
    if gap > SAME_FAILURE_DAYS:
        return False
    a, b = r.get("failure_mode_id"), e.get("mode_id")
    return not a or not b or a == b


# ---- the ranking ---------------------------------------------------------------------------

def failure_ranking(m: Maintenance, position_id, group_by="position", rank_by="failures", window=None,
                    since=None, until=None) -> dict:
    """The groups below ``position_id`` (a position and everything inside it, or a product's
    design: the items built from it), ranked by ``rank_by`` over the window. See the module."""
    if group_by not in GROUP_BY:
        raise Invalid(f"group_by is one of {', '.join(GROUP_BY)}.")
    if rank_by not in RANK_BY:
        raise Invalid(f"rank_by is one of {', '.join(RANK_BY)}.")
    if not position_id:
        raise Invalid("Give the position_id to rank what's inside it.")
    root = m._get(position_id, "Position")
    win = _window(m, window, since, until)

    # Where to look, and which group a position is in (Position: the level just below the
    # one opened; a design: the item built from it, each a unit).
    design = bool(m._design_root_of(position_id))
    unit_of: dict[str, dict] = {}
    if design:
        at = m._design_report_scope(position_id)
        positions = list(at)
        for pid, (_impl, unit) in at.items():
            unit_of[pid] = unit
        clock_root = None
    else:
        positions, parent = _scope_tree(m, position_id)
        clock_root = position_id
    hours = _Hours(m, clock_root)
    names: dict[str, str] = {}

    def name_of(pid: str) -> str:
        if pid not in names:
            names[pid] = (m.s.node(m.org, pid) or {}).get("name") or ""
        return names[pid]

    def position_group(pid: str) -> str:
        if design:
            return unit_of[pid]["top_position_id"]
        node = pid
        while node in parent and parent[node] != position_id:
            node = parent[node]
        return node if node in parent else position_id

    # The failures: reports, then the log's corrective events not already reported.
    wanted = set(positions)
    reports = [r for r in m.s.nodes(m.org, "FailureReport")
               if r.get("position_id") in wanted and r.get("occurred_on") and r.get("status") != "rejected"]
    events = _events(m, positions)
    starts = [r["occurred_on"] for r in reports] + [e["day"] for e in events]
    if win["since"] is None:
        froms = [f["from"][:10] for pid in positions for f in m._fitments_at(pid) if f.get("from")]
        first = min(starts + froms, default=None)
        win["since"] = date.fromisoformat(first) if first else win["until"]
    lo, hi = win["since"].isoformat(), win["until"].isoformat()
    days = (win["until"] - win["since"]).days + 1

    def inside(day: str) -> bool:
        return lo <= day[:10] <= hi

    nff = [r for r in reports if r["status"] == "no_fault_found" and inside(r["occurred_on"])]
    counted_reports = sorted((r for r in reports if r["status"] not in NOT_FAILURE_STATUSES),
                             key=lambda r: (r["occurred_on"], r["number"]))
    taken: set = set()
    kept_events, merged = [], 0
    for e in sorted(events, key=lambda e: e["day"]):
        match = next((r for r in counted_reports if r["id"] not in taken and _same(r, e)), None)
        if match is not None:
            taken.add(match["id"])
            merged += 1
        else:
            kept_events.append(e)
    failures = []
    for r in counted_reports:
        if inside(r["occurred_on"]):
            failures.append({"position_id": r["position_id"], "day": r["occurred_on"],
                             "mode_id": r.get("failure_mode_id"), "part": _report_part(r), "source": "report",
                             "report_id": r["id"]})
    for e in kept_events:
        if inside(e["day"]):
            failures.append({"position_id": e["position_id"], "day": e["day"], "mode_id": e["mode_id"],
                             "part": _part_key(m, e["item"]), "source": e["source"]})

    # Each failure's downtime and cost: its mode's figures, else its position class's.
    cost_memo: dict = {}

    def consequence(f: dict) -> dict:
        key = (f["position_id"], f["mode_id"])
        if key not in cost_memo:
            node = m.s.node(m.org, f["position_id"]) or {"id": f["position_id"]}
            cost_memo[key] = m.failure_consequence(node, [f["mode_id"]] if f["mode_id"] else [])
        return cost_memo[key]

    # The groups, with their hours over the window.
    groups: dict[str, dict] = {}

    def group(key: str, name: str, link: dict | None, filter_: dict, hours_: float | None = None) -> dict:
        if key not in groups:
            groups[key] = {"key": key, "name": name, "link": link, "filter": filter_, "hours": hours_,
                           "failures": [], "no_fault_found": 0, "positions": set()}
        return groups[key]

    mode_text: dict[str, str] = {}

    def mode_of(mid: str | None) -> dict | None:
        if not mid:
            return None
        if mid not in mode_text:
            fm = m.s.node(m.org, mid, "FailureMode") or {}
            if fm.get("merged_into"):
                fm = m.s.node(m.org, fm["merged_into"], "FailureMode") or fm
            mode_text[mid] = fm.get("text") or ""
        return {"id": mid, "text": mode_text[mid]}

    def mode_key(mid: str | None) -> str:
        mode = mode_of(mid)
        return "mode:" + " ".join(mode["text"].lower().split()) if mode and mode["text"] else "mode:none"

    def key_of(f: dict) -> str:
        if group_by == "position":
            return "pos:" + position_group(f["position_id"])
        if group_by == "part":
            return f["part"][0] if f["part"] else "part:none"
        return mode_key(f["mode_id"])

    if group_by == "position":
        tops = ({u["top_position_id"] for u in unit_of.values()} if design
                else {p for p in positions if parent.get(p) == position_id})
        for top in tops:
            name = name_of(top)
            serial = next((u["serial"] for u in unit_of.values() if u["top_position_id"] == top), None) if design \
                else None
            group("pos:" + top, f"{name} (serial {serial})" if serial else name, {"kind": "position", "id": top},
                  {"position_id": top}, hours.hours(top, days))
        if not tops or any(position_group(f["position_id"]) == position_id for f in failures):
            # At the position opened itself; its hours are its children's when it has any.
            group("pos:" + position_id, f"{root['name']} itself" if tops else root["name"],
                  {"kind": "position", "id": position_id}, {"position_id": position_id, "below": False},
                  None if tops else hours.hours(position_id, days))
    elif group_by == "failure_mode":
        for pid in positions:
            for fm in m._modes_on(pid):
                g = group(mode_key(fm["id"]), fm.get("text") or "", {"kind": "failure_mode", "id": fm["id"]},
                          {"failure_mode_id": fm["id"]}, 0.0)
                ids = g["filter"]["failure_mode_id"].split(",")
                if fm["id"] not in ids:
                    g["filter"]["failure_mode_id"] = ",".join(ids + [fm["id"]])
                if pid not in g["positions"]:
                    g["positions"].add(pid)
                    g["hours"] += hours.hours(pid, days)
    else:
        for pid in positions:
            fitments = sorted(m._fitments_at(pid), key=lambda f: f["from"])
            for k, f in enumerate(fitments):
                item = m.s.inn(m.org, f["id"], "IN")
                part = _part_key(m, item[0] if item else None)
                if not part:
                    continue
                # The first item known here is taken to have been there since the window began.
                a = win["since"] if k == 0 else max(win["since"], date.fromisoformat(f["from"][:10]))
                b = min(win["until"], date.fromisoformat(f["to"][:10]) if f.get("to") else win["until"])
                span = (b - a).days + (0 if f.get("to") else 1)
                if span <= 0:
                    continue
                g = group(part[0], part[1], {"kind": "part", "id": part[2]} if part[2] else None,
                          {"part_id": part[2]} if part[2] else {}, 0.0)
                g["hours"] = (g["hours"] or 0.0) + hours.hours(pid, span)
                g["positions"].add(pid)

    for f in failures:
        key = key_of(f)
        if key not in groups:
            if group_by == "failure_mode":
                mode = mode_of(f["mode_id"])
                group(key, mode["text"] if mode else "No failure mode given",
                      {"kind": "failure_mode", "id": mode["id"]} if mode else None,
                      {"failure_mode_id": mode["id"]} if mode else {}, None)
            elif group_by == "part":
                part = f["part"]
                group(key, part[1] if part else "No part or item class recorded",
                      {"kind": "part", "id": part[2]} if part and part[2] else None,
                      {"part_id": part[2]} if part and part[2] else {}, None)
        groups[key]["failures"].append(f)
    for r in nff:
        f = {"position_id": r["position_id"], "mode_id": r.get("failure_mode_id"), "part": _report_part(r)}
        key = key_of(f)
        if key in groups:
            groups[key]["no_fault_found"] += 1

    # Pooled: the failures in groups with hours, over those hours.
    known = [g for g in groups.values() if g["hours"]]
    pooled_n = sum(len(g["failures"]) for g in known)
    pooled_h = sum(g["hours"] for g in known)
    pooled = pooled_n / pooled_h if pooled_h > 0 else None
    baseline = "if every failure mode here failed at the same rate" if group_by == "failure_mode" \
        else "at the rate of everything here pooled"

    rows = []
    missing_cost = 0
    for g in groups.values():
        n = len(g["failures"])
        down, cost, no_down, no_cost = 0.0, 0.0, 0, 0
        for f in g["failures"]:
            c = consequence(f)
            if c.get("downtime_hours") is None:
                no_down += 1
            else:
                down += float(c["downtime_hours"])
            if c.get("per_failure") is None:
                no_cost += 1
            else:
                cost += float(c["per_failure"])
        missing_cost += no_cost
        rate = poisson_range(n, g["hours"])
        expected = pooled * g["hours"] if pooled is not None and g["hours"] else None
        row = {"key": g["key"], "name": g["name"], "link": g["link"], "filter": g["filter"], "failures": n,
               "no_fault_found": g["no_fault_found"],
               "reports": sum(1 for f in g["failures"] if f["source"] == "report"),
               "hours": g["hours"], "rate_per_1000h": rate,
               "downtime_hours": down if n - no_down else (0.0 if not n else None), "downtime_missing": no_down,
               "cost": cost if n - no_cost else (0.0 if not n else None), "cost_missing": no_cost,
               "expected": expected, "p_value": None, "direction": None, "too_few": False}
        if expected is not None:
            p, direction = chance(n, expected)
            row |= {"p_value": p, "direction": direction}
            failures_words = _plural(n, "failure")
            if n < TOO_FEW and expected < TOO_FEW:
                row["too_few"] = True
                row["sentence"] = (f"{failures_words} where {_num(expected)} would be expected {baseline}: too few "
                                   "to tell apart from chance.")
            else:
                many = "this many or more" if direction == "more" else "this few or fewer"
                row["sentence"] = (f"{failures_words} where {_num(expected)} would be expected {baseline}; {many} "
                                   f"would happen by chance {chance_words(p)}.")
        else:
            row["sentence"] = (f"{_plural(n, 'failure')}; no operating hours for this group, so no rate or "
                               "expected count.")
        rows.append(row)

    def metric(r: dict):
        if rank_by == "failures":
            return r["failures"]
        if rank_by == "rate":
            return (r["rate_per_1000h"] or {}).get("value")
        if rank_by == "downtime":
            return r["downtime_hours"]
        return r["cost"]

    rows.sort(key=lambda r: (metric(r) is None, -(metric(r) or 0), -r["failures"], r["name"].lower()))
    total_metric = sum(metric(r) or 0 for r in rows)
    running = 0.0
    for k, r in enumerate(rows):
        v = metric(r)
        r["rank"] = k + 1
        r["value"] = v
        r["share"] = (v or 0) / total_metric if total_metric else None
        running += v or 0
        r["cumulative_share"] = running / total_metric if total_metric else None
    rows = rows[:MAX_ROWS]

    n_all = len(failures)
    basis_counts = {"duty": 0, "readings": 0, "continuous": 0}
    for _rate, kind in hours.memo.values():
        basis_counts[kind] += 1
    bits = []
    if basis_counts["duty"]:
        bits.append(f"the duty in Operations ({_plural(basis_counts['duty'], 'position')})")
    if basis_counts["readings"]:
        bits.append(f"the hours readings' recent rate ({_plural(basis_counts['readings'], 'position')})")
    if basis_counts["continuous"]:
        bits.append(f"running all the time, 24 h a day, with no duty or readings "
                    f"({_plural(basis_counts['continuous'], 'position')})")
    window_words = ("the last 12 months" if win["kind"] == "12m"
                    else f"{svc._short_day(lo)} to {svc._short_day(hi)}")
    by_words = {"position": "unit" if design else "position", "part": "part", "failure_mode": "failure mode"}[group_by]
    rank_words = {"failures": "failures", "rate": "failure rate", "downtime": "downtime", "cost": "cost"}[rank_by]
    if n_all:
        top = rows[0]
        sentence = (f"{_plural(n_all, 'failure')} in {window_words} below {root['name']}. By {rank_words}, the "
                    f"{by_words} at the top is {top['name']}"
                    + (f": {_share_words(top['share'])} of the total." if top["share"] and rank_by != "rate" else
                       f": {_num(top['value'])} per 1,000 h." if rank_by == "rate" and top["value"] is not None else "."))
    else:
        sentence = f"No failures recorded in {window_words} below {root['name']}."
    notes = [
        "Counted: failure reports (not rejected; no fault found is shown on its own and never counted as a "
        "failure) and the corrective failures in the log (items removed for a failure, found failed at an "
        "inspection, or repaired for a failure mode). A logged failure within "
        f"{SAME_FAILURE_DAYS} days of a report at the same position, with the same failure mode or none, is "
        "the same failure and counted once" + (f" ({_plural(merged, 'was', 'were')} merged)." if merged else "."),
        "Rates are failures per 1,000 operating hours, with a 90% two-sided range (exact Poisson).",
        "Operating hours: " + ("; ".join(bits) if bits else "none") + ".",
        "Downtime and cost are each failure's figures from its failure mode, else its position's class, not "
        "typed on the report" + (f"; {_plural(missing_cost, 'failure')} had no cost set." if missing_cost else "."),
    ]
    if group_by == "part":
        notes.append("A part's hours are the hours of the positions it was fitted at; the first item known at a "
                     "position is taken to have been there since the window began.")
    return {
        "scope": {"id": position_id, "name": root["name"], "kind": "design" if design else "position",
                  "positions": len(positions)},
        "window": {"kind": win["kind"], "since": lo, "until": hi, "days": days},
        "group_by": group_by, "rank_by": rank_by, "level": LEVEL,
        "rows": rows,
        "totals": {"failures": n_all, "no_fault_found": len(nff),
                   "reports": sum(1 for f in failures if f["source"] == "report"),
                   "logged": sum(1 for f in failures if f["source"] != "report"), "merged": merged,
                   # By part or failure mode the groups' hours overlap (a position's hours count for each of
                   # its modes), so their sum isn't the fleet's: totals give hours and a rate by position only.
                   "hours": (pooled_h or None) if group_by == "position" else None,
                   "rate_per_1000h": poisson_range(pooled_n, pooled_h) if group_by == "position" else None,
                   "downtime_hours": sum(r["downtime_hours"] or 0 for r in rows),
                   "cost": sum(r["cost"] or 0 for r in rows), "cost_missing": missing_cost},
        "basis": {"counts": basis_counts, "text": "Operating hours: " + ("; ".join(bits) if bits else "none")},
        "sentence": sentence, "notes": notes,
    }


def _share_words(share: float) -> str:
    return f"{share * 100:.0f}%" if share >= 0.1 else f"{share * 100:.1f}%"
