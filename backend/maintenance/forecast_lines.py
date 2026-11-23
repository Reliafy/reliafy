"""A forecast as lines by owner (forecast plan step 2, Nov 2026; forecast-rules 1.1, 1.6, 1.11).

Every forecast line is one sum: how many times × what it needs each time (spares, hours, cost).
Each line has one owner:

* **planned work → the task:** its count from its schedule, certain (no range);
* **a package's visit cost (call-out, set-up) → the visits**, once a visit;
* **work after a failure → the failure mode** (its corrective response): the failures the plan
  leaves, a chance, worked out by RePyability with a range;
* **work after an inspection finds it → the same failure mode** (its follow-on): the failures that
  would have happened × the share the inspection finds in time.

A node's total is the sum of its lines, so nothing is counted twice. Each line says what kind of
number it is (certain, worked out or simulated) and what it leaves out. Nothing is filled in: a
failure mode with no cost of a failure says its cost is unknown, and the total is the "known"
total with what it leaves out underneath (forecast-rules 1.6). Corrective hours and the
follow-on's needs aren't recorded yet (plan steps 3 and 4), so those are listed as not counted.

Ranges are 90% two-sided (5th to 95th percentile). The failure lines' ranges come from each
life's distribution of the count of failures (RePyability's), each failure found with the
inspection's share independently of the others, and the lives independent of each other; the
certain lines are added to both ends. Built from ``position_forecast``'s answer; nothing is stored.
"""

from __future__ import annotations

from collections import defaultdict

import numpy as np

LEVELS = (0.05, 0.95)
MAX_SUPPORT = 20_000  # amounts in a sum worked out exactly; past this it is sampled (seeded)
SAMPLES = 20_000


def _r(v, digits: int = 9):
    if v is None:
        return None
    v = float(v)
    return float(f"{v:.{digits}g}") if np.isfinite(v) else None


def _pmf(fc) -> list[float] | None:
    """The chance of 0, 1, 2… failures over the horizon (if nothing found them), or None."""
    base = getattr(fc, "base", fc)
    probs = (getattr(base, "total", None) or {}).get("failure_probabilities")
    if not probs:
        return None
    p = np.clip(np.asarray(probs, dtype=float), 0, None)
    return list(p / p.sum()) if p.sum() > 0 else None


def _split(pmf: list[float], found: float, a_missed: float, a_found: float) -> dict:
    """The amount's distribution {amount: chance} when each of N failures (pmf) is found with
    chance ``found`` (charged ``a_found``) or missed (``a_missed``)."""
    from scipy.stats import binom

    out: dict = defaultdict(float)
    for n, pn in enumerate(pmf):
        if pn <= 0:
            continue
        if found <= 0:
            out[round(n * a_missed, 6)] += pn
            continue
        for k in range(n + 1):  # k found
            out[round(k * a_found + (n - k) * a_missed, 6)] += pn * float(binom.pmf(k, n, found))
    return dict(out)


def _convolve(a: dict, b: dict) -> dict | None:
    if len(a) * len(b) > MAX_SUPPORT * 4:
        return None
    out: dict = defaultdict(float)
    for x, px in a.items():
        for y, py in b.items():
            out[round(x + y, 6)] += px * py
    if len(out) > MAX_SUPPORT:
        return None
    return dict(out)


def _quantiles(dist: dict) -> tuple[float, float, float]:
    xs = np.array(sorted(dist))
    ps = np.array([dist[x] for x in xs])
    cum = np.cumsum(ps)
    lo = xs[min(len(xs) - 1, int(np.searchsorted(cum, LEVELS[0] - 1e-12)))]
    hi = xs[min(len(xs) - 1, int(np.searchsorted(cum, LEVELS[1] - 1e-12)))]
    return float(np.dot(xs, ps)), float(lo), float(hi)


def _sampled(parts: list[tuple[list, float, float, float]]) -> tuple[float, float, float]:
    rng = np.random.default_rng(20261123)
    total = np.zeros(SAMPLES)
    for part in parts:
        if part[0] == "joint":
            _, j, a, b = part
            flat = np.asarray(j, dtype=float).ravel()
            idx = rng.choice(flat.size, size=SAMPLES, p=flat / flat.sum())
            f, p = np.unravel_index(idx, np.asarray(j).shape)
            total += a * f + b * p
            continue
        pmf, found, a_m, a_f = part
        n = rng.choice(len(pmf), size=SAMPLES, p=np.asarray(pmf) / np.sum(pmf))
        k = rng.binomial(n, found) if found > 0 else np.zeros(SAMPLES, dtype=int)
        total += k * a_f + (n - k) * a_m
    return (float(total.mean()), float(np.quantile(total, LEVELS[0], method="inverted_cdf")),
            float(np.quantile(total, LEVELS[1], method="inverted_cdf")))


def _chance_sum(parts) -> dict | None:
    """{expected, interval, method} of the sum over failure lines' amounts; None with none."""
    if not parts:
        return None
    dist: dict | None = {0.0: 1.0}
    for part in parts:
        if part[0] == "joint":
            # Failures and planned replacements together (age replacement: worked_part.py), a × f + b × p.
            _, j, a, b = part
            one: dict = defaultdict(float)
            for (f, p), w in np.ndenumerate(np.asarray(j, dtype=float)):
                if w > 0:
                    one[round(a * f + b * p, 6)] += float(w)
        else:
            one = _split(*part)
        dist = _convolve(dist, one) if dist is not None else None
        if dist is None:
            break
    if dist is not None:
        mean, lo, hi = _quantiles(dist)
        return {"expected": mean, "interval": [lo, hi], "method": "worked out"}
    mean, lo, hi = _sampled(parts)
    return {"expected": mean, "interval": [lo, hi], "method": "sampled"}


def _count_range(pmf: list[float] | None, share: float) -> list | None:
    """The 90% range of the count of failures × a share kept (found, or missed)."""
    if pmf is None:
        return None
    d = _split(pmf, 1.0 - share, 1.0, 0.0) if share < 1.0 else {float(n): p for n, p in enumerate(pmf)}
    _, lo, hi = _quantiles(d)
    return [lo, hi]


def _number(method: str | None) -> str:
    return "simulated" if method and "simul" in str(method) else "worked out"


def _modes_text(row: dict) -> str:
    modes = [x.get("text") or "" for x in row.get("failure_modes") or []]
    return ", ".join(x for x in modes if x) or row.get("name") or "Its life"


def build(m, fc: dict, model_rows: list[dict], tree, root) -> dict:
    """The lines, totals by kind and what's not counted, from a position forecast's answer
    (``fc``) and its life forecasts (``model_rows``: {row, fc})."""
    from backend.maintenance import responses, supporting
    from backend.maintenance.position_forecast import _explorer_link

    lines: list[dict] = []
    gaps = {"hours": [], "cost": [], "spares": []}
    not_counted: list[dict] = []
    support_of: dict = {}
    for r in model_rows:
        for c in r["row"].get("tasks_not_counted") or []:
            if c.get("support"):
                support_of.setdefault(c["task"]["id"], []).append(_modes_text(r["row"]))
    counted_effect = {}
    for r in model_rows:
        for c in r["row"].get("tasks_counted") or []:
            counted_effect.setdefault(c["task"]["id"], c["effect"])

    # Age replacement (restart.py): a replacing task's planned count is a chance, from its life's joint
    # distribution of failures and planned replacements; the lives at each position, for the note on a
    # servicing task that restarts when the item is replaced.
    from backend.services import worked_part

    joint_of = {r["row"]["replacing_task"]["id"]: r for r in model_rows
                if r.get("joint") is not None and (r["row"].get("replacing_task") or {}).get("resets")}
    lives_at: dict = {}
    for r in model_rows:
        lives_at.setdefault(r["row"]["position"]["id"], []).append(r["row"])

    # Planned work: each task's own line, certain (a replacing task that restarts: worked out).
    for t in fc.get("tasks") or []:
        node = m.s.node(m.org, t["id"]) or {}
        n = int(t["count"])
        line = {"id": f"task:{t['id']}", "owner": t["name"], "owner_kind": "task", "kind": "planned",
                "number": "certain", "task_id": t["id"], "position": t["position"],
                "how_often": t.get("how_often") or "", "times": {"expected": n, "interval": None},
                "hours": None, "cost": None, "spares": [], "gaps": [], "does": None,
                "link": _explorer_link(t["position"]["id"], root, "maintenance", mtask=t["id"])}
        if node.get("support"):
            line["does"] = {"kind": "supports", "text": supporting.words(
                node["support"], {fm["id"]: fm.get("text") or "" for fm in m.s.out(m.org, t["id"], "MITIGATES")}),
                "marker": supporting.marker(node["support"])}
        elif t["id"] in counted_effect:
            line["does"] = {"kind": "credited", "text": counted_effect[t["id"]]}
        if t.get("labour_each"):
            line["hours"] = {"expected": _r(n * float(t["labour_each"])), "interval": None}
        else:
            line["gaps"].append({"view": "hours", "text": "no labour in its LSA"})
            gaps["hours"].append(f"{t['name']} (no labour hours)")
        if t.get("cost_each") is not None:
            line["cost"] = {"expected": _r(n * float(t["cost_each"])), "interval": None}
        else:
            line["gaps"].append({"view": "cost", "text": "no cost each time"})
            gaps["cost"].append(f"{t['name']} (no cost)")
        restart = m.task_on_replace(node)["value"] if node else "keep"
        line["on_replace"] = restart
        jr = joint_of.get(t["id"])
        if jr is not None:
            j = jr["joint"]
            planned = worked_part.block(j, 0, 1)
            line.update(number="worked out", joint_task=True,
                        times={"expected": _r(planned["expected"]), "interval": planned["interval"]},
                        note="Restarts after a failure (age replacement): how many it takes is a chance.")
            if t.get("labour_each"):
                line["hours"] = {"expected": _r(planned["expected"] * float(t["labour_each"])), "interval": None,
                                 "each": float(t["labour_each"])}
            if t.get("cost_each") is not None:
                line["cost"] = {"expected": _r(planned["expected"] * float(t["cost_each"])), "interval": None,
                                "each": float(t["cost_each"])}
            n = planned["expected"]
        elif restart == "restart" and t["id"] not in {(r["row"].get("replacing_task") or {}).get("id")
                                                      for r in model_rows}:
            rows_here = [r for r in lives_at.get(t["position"]["id"], []) if r.get("mean_life")]
            if rows_here and node.get("interval"):
                from backend.maintenance import restart as rs
                from backend.maintenance.position_forecast import _in_life_unit

                rate = sum(1.0 / r["mean_life"] for r in rows_here)
                every = _in_life_unit(node["interval"], node["unit"], rows_here[0]["unit"])
                share = rs.shortfall(every, 1.0 / rate) if every is not None else None
                if share is not None:
                    line["restart_share"] = _r(share, 3)
                    line["note"] = (
                        f"Restarts when the item is replaced: about one fewer for each replacement, half the time "
                        f"(about {share:.1%} fewer here); shown as scheduled." if share < rs.NOTE_BELOW else
                        f"Restarts when the item is replaced: about {share:.0%} fewer than scheduled, as each "
                        "replacement drops half an interval; shown as scheduled, as its exact range isn't "
                        "worked out yet.")
        view = m._task_view(node) if node else {}
        for sp in ((view.get("resources") or {}).get("spares") or []):
            try:
                qty = float(sp.get("qty") or 1)
            except (TypeError, ValueError):
                qty = 1.0
            line["spares"].append({"name": sp.get("name") or "a spare", "part_id": sp.get("part_id"),
                                   "expected": _r(n * qty), "interval": None})
        lines.append(line)

    t = fc["totals"]
    if t.get("visits") and t.get("visits_cost"):
        lines.append({"id": "visits", "owner": "Visits (call-out and set-up)", "owner_kind": "package", "kind": "planned",
                      "number": "certain", "times": {"expected": int(t["visits"]), "interval": None},
                      "hours": None, "cost": {"expected": _r(t["visits_cost"]), "interval": None}, "spares": [],
                      "gaps": [], "does": None})

    # Failures: per failure mode, the corrective response's line and (with an inspection) the
    # follow-on's. The same failure mode on several positions at the same cost (three spindle
    # bearings) is one owner, its counts summed and its range over all of them.
    cost_parts, spare_parts = [], []
    no_response = False
    hour_parts = []
    groups: dict = {}
    for r in model_rows:
        row, lib = r["row"], r["fc"]
        found = float(row.get("found_share") or 0.0)
        left = float(row["expected_failures"] or 0.0)
        n_all = left / (1.0 - found) if found and found < 1.0 else left
        each = row.get("cost_per_failure")
        follow = responses.response_view(m, row["response_mode"], "found") if found and row.get("response_mode") else None
        def sig(resp):
            return None if resp is None else (resp["name"], resp.get("hours_each"), resp.get("cost_each"),
                                              tuple((x["name"], x["qty"]) for x in resp.get("spares") or []))

        key = (_modes_text(row), each, round(found, 6), sig(row.get("response")), sig(follow))
        g = groups.setdefault(key, {"owner": key[0], "each": each, "found": found, "follow": follow, "n": 0.0, "pmfs": [],
                                    "positions": [], "rows": [], "methods": set(), "ranged": True})
        g["n"] += n_all
        pmf = _pmf(lib)
        if pmf is None:
            g["ranged"] = False
        else:
            g["pmfs"].append(pmf)
            rt = row.get("replacing_task") or {}
            if r.get("joint") is not None and rt.get("resets") and not found:
                task_line = next((x for x in lines if x.get("task_id") == rt["id"]), None) or {}
                cost_parts.append(("joint", r["joint"], float(each) if each is not None else 0.0,
                                   float((task_line.get("cost") or {}).get("each") or 0.0)))
                hour_parts.append(("joint", r["joint"], float((row.get("response") or {}).get("hours_each") or 0.0),
                                   float((task_line.get("hours") or {}).get("each") or 0.0)))
            else:
                cost_parts.append((pmf, found, float(each) if each is not None else 0.0,
                                   float((follow or {}).get("cost_each") or 0.0)))
                hour_parts.append((pmf, found, float((row.get("response") or {}).get("hours_each") or 0.0),
                                   float((follow or {}).get("hours_each") or 0.0)))
            spare_parts.append((pmf, 0.0, 1.0, 1.0))
        g["positions"].append(row["position"])
        g["rows"].append(row)
        g["methods"].add(_number(getattr(lib, "method", None)))

    def count_range(g, share):
        if not g["ranged"] or not g["pmfs"]:
            return None
        got = _chance_sum([(p, 1.0 - share, 1.0, 0.0) for p in g["pmfs"]])
        return [_r(got["interval"][0]), _r(got["interval"][1])] if got else None

    for k, g in enumerate(groups.values()):
        owner, each, found, n_all = g["owner"], g["each"], g["found"], g["n"]
        where = g["positions"][0]
        many = len(g["positions"]) > 1
        on = f"{len(g['positions'])} positions" if many else where["name"]
        number = "simulated" if "simulated" in g["methods"] else "worked out"
        prob = g["rows"][0].get("probability") if not found and not many else None
        gid = f"mode:{k}"
        rows0 = g["rows"][0]
        group = {"id": gid, "owner": owner, "owner_kind": "failure_mode", "kind": "failures", "number": number,
                 "positions": g["positions"], "position": where, "on": on, "life": rows0.get("name"),
                 "distribution": rows0.get("distribution"), "unit": rows0.get("unit"),
                 "ages": [x.get("age") for x in g["rows"]],
                 "times": {"expected": _r(n_all), "interval": count_range(g, 1.0), "probability": prob},
                 "found_share": _r(found, 3) if found else None, "hours": None, "cost": None, "spares": [], "gaps": [],
                 "link": _explorer_link(where["id"], root, "rcm")}
        response = rows0.get("response")
        missed_n = n_all * (1.0 - found)
        # What's done if it fails is a task on the Maintenance tab (raised by the failure): the link
        # opens it there, or the form to add it.
        respond_link = _explorer_link(where["id"], root, "maintenance", addtask=where["id"],
                                      fm=rows0.get("response_mode") or "", respond="failure")
        corrective = {"id": f"{gid}:corrective", "owner": owner, "owner_kind": "failure_mode", "kind": "corrective",
                      "group": gid, "number": number, "position": where, "on": on,
                      "times": {"expected": _r(missed_n), "interval": count_range(g, 1.0 - found),
                                "probability": prob},
                      "response": ({"id": response["id"], "name": response["name"]} if response else None),
                      "hours": None, "cost": None, "spares": [], "gaps": []}
        if response is None:
            no_response = True
            corrective["spares"] = [{"name": f"a like item ({owner})", "expected": _r(missed_n)}]
            corrective["gaps"].append({"view": "hours", "text": "no response if it fails, so the hours to put a "
                                                                "failure right are unknown"})
            gaps["hours"].append(f"{owner} on {on} (no response if it fails)")
            not_counted.append({"kind": "no_response", "position": where,
                                "text": f"{owner}: no response if it fails, so the hours and spares to put a failure "
                                        "right are unknown", "fix": "Add", "link": respond_link})
        else:
            if response.get("hours_each") is not None:
                corrective["hours"] = {"expected": _r(missed_n * response["hours_each"]), "interval": None,
                                       "each": response["hours_each"]}
            else:
                corrective["gaps"].append({"view": "hours", "text": "its response has no labour, so its hours are "
                                                                    "unknown"})
                gaps["hours"].append(f"{owner} on {on} (its response has no labour)")
            corrective["spares"] = [{"name": sp["name"], "part_id": sp.get("part_id"),
                                     "expected": _r(missed_n * sp["qty"])} for sp in response.get("spares") or []]
            if not corrective["spares"]:
                corrective["spares"] = [{"name": f"a like item ({owner})", "expected": _r(missed_n)}]
        if each is not None:
            corrective["cost"] = {"expected": _r(n_all * (1.0 - found) * float(each)), "interval": None,
                                  "each": each, "basis": rows0.get("cost_basis")}
        else:
            corrective["gaps"].append({"view": "cost", "text": "no response if it fails, so its failure cost is unknown"})
            gaps["cost"].append(f"{owner} on {on} (no cost of a failure)")
            if response is not None:
                not_counted.append({"kind": "no_failure_cost", "position": where,
                                    "text": f"{owner}: its response has no cost each time, so its failure cost is "
                                            "unknown", "fix": "Add", "link": respond_link})
        members = [corrective]
        if found:
            fr = g["follow"]
            found_n = n_all * found
            found_link = _explorer_link(where["id"], root, "maintenance", addtask=where["id"],
                                        fm=rows0.get("response_mode") or "", respond="found")
            follow = {"id": f"{gid}:follow_on", "owner": owner, "owner_kind": "failure_mode", "kind": "follow_on",
                      "group": gid, "number": number, "position": where, "on": on,
                      "times": {"expected": _r(found_n), "interval": count_range(g, found)},
                      "response": ({"id": fr["id"], "name": fr["name"]} if fr else None),
                      "hours": None, "cost": None, "spares": [], "gaps": []}
            if fr is None:
                follow["spares"] = [{"name": f"a like item ({owner})", "expected": _r(found_n)}]
                follow["gaps"] = [{"view": "hours", "text": "nothing recorded for when an inspection finds it"},
                                  {"view": "cost", "text": "nothing recorded for when an inspection finds it, so its "
                                                           "cost is unknown"}]
                gaps["hours"].append(f"{owner} on {on}: found at an inspection (nothing recorded for what's done then)")
                gaps["cost"].append(f"{owner} on {on}: found at an inspection (nothing recorded for what's done then)")
                not_counted.append({"kind": "no_follow_on", "position": where,
                                    "text": f"{owner}: nothing recorded for when an inspection finds it, so what "
                                            f"{_r(found_n, 3):g} finds need is unknown", "fix": "Add",
                                    "link": found_link})
            else:
                if fr.get("hours_each") is not None:
                    follow["hours"] = {"expected": _r(found_n * fr["hours_each"]), "interval": None,
                                       "each": fr["hours_each"]}
                else:
                    follow["gaps"].append({"view": "hours", "text": "what's done when it's found has no labour"})
                    gaps["hours"].append(f"{owner} on {on}: found at an inspection (no labour recorded)")
                if fr.get("cost_each") is not None:
                    follow["cost"] = {"expected": _r(found_n * fr["cost_each"]), "interval": None,
                                      "each": fr["cost_each"]}
                else:
                    follow["gaps"].append({"view": "cost", "text": "what's done when it's found has no cost"})
                    gaps["cost"].append(f"{owner} on {on}: found at an inspection (no cost recorded)")
                    not_counted.append({"kind": "no_follow_on_cost", "position": where,
                                        "text": f"{owner}: what's done when an inspection finds it has no cost each "
                                                "time", "fix": "Add", "link": found_link})
                follow["spares"] = [{"name": sp["name"], "part_id": sp.get("part_id"), "expected": _r(found_n * sp["qty"])}
                                    for sp in fr.get("spares") or []] or [
                    {"name": f"a like item ({owner})", "expected": _r(found_n)}]
            members.append(follow)
        group["lines"] = [x["id"] for x in members]
        lines.append(group)
        lines.extend(members)

    # Totals: the certain lines plus the chance of the failure lines (forecast-rules 1.4).
    certain_hours = sum((x["hours"] or {}).get("expected") or 0 for x in lines if x["number"] == "certain")
    certain_cost = sum((x["cost"] or {}).get("expected") or 0 for x in lines if x["number"] == "certain")
    failure_cost = sum((x["cost"] or {}).get("expected") or 0 for x in lines
                       if x.get("kind") in ("corrective", "follow_on") or x.get("joint_task"))
    chance = _chance_sum(cost_parts) if model_rows else None
    exact_ranges = len(cost_parts) == len(model_rows)
    cost_total = {"expected": _r(certain_cost + failure_cost),
                  "interval": ([_r(certain_cost + chance["interval"][0]), _r(certain_cost + chance["interval"][1])]
                               if chance and exact_ranges else None if model_rows else
                               [_r(certain_cost), _r(certain_cost)]),
                  "known": not gaps["cost"], "leaves_out": gaps["cost"],
                  "by_kind": {"planned": _r(sum((x["cost"] or {}).get("expected") or 0 for x in lines
                                                if x.get("kind") == "planned")),
                              "follow_on": _r(sum((x["cost"] or {}).get("expected") or 0 for x in lines
                                                  if x.get("kind") == "follow_on")),
                              "corrective": _r(sum((x["cost"] or {}).get("expected") or 0 for x in lines
                                                   if x.get("kind") == "corrective"))}}
    if model_rows and not exact_ranges:
        cost_total["range_note"] = "No range: a life here has no distribution of its count yet."
    failure_hours = sum((x["hours"] or {}).get("expected") or 0 for x in lines
                        if x.get("kind") in ("corrective", "follow_on") or x.get("joint_task"))
    hours_chance = _chance_sum(hour_parts) if failure_hours and len(hour_parts) == len(model_rows) else None
    hours_total = {"expected": _r(certain_hours + failure_hours),
                   "interval": ([_r(certain_hours + hours_chance["interval"][0]),
                                 _r(certain_hours + hours_chance["interval"][1])] if hours_chance else
                                [_r(certain_hours), _r(certain_hours)] if not failure_hours else None),
                   "known": not gaps["hours"], "leaves_out": gaps["hours"]}
    spares: dict = {}
    for x in lines:
        for sp in x.get("spares") or []:
            key = sp.get("part_id") or sp["name"]
            cur = spares.setdefault(key, {"name": sp["name"], "expected": 0.0, "certain": True, "owners": []})
            cur["expected"] = _r(cur["expected"] + (sp["expected"] or 0))
            cur["certain"] = cur["certain"] and x["number"] == "certain"
            if x["owner"] not in cur["owners"]:
                cur["owners"].append(x["owner"])
    # The like items failures use: one range over every life (independent).
    likes = _chance_sum(spare_parts) if spare_parts else None

    # Not counted: every gap, with where to fix it.
    prompts = fc.get("prompts") or {}
    for x in prompts.get("no_failure_cost") or []:
        if x.get("counted"):
            what = x["mode"]["text"] if x.get("mode") else x.get("life") or "A life"
            same = next((y for y in not_counted if y["kind"] == "no_response" and y["text"].startswith(f"{what}:")), None)
            if same is not None:
                same["text"] = f"{what}: no response if it fails, so the hours, spares and cost to put a failure right " \
                               "are unknown"
                continue
            not_counted.append({"kind": "no_failure_cost", "position": x["position"],
                                "text": f"{what}: no response if it fails, so its failure cost is unknown",
                                "fix": "Add", "link": x["link"]})
    for x in prompts.get("no_pf") or []:
        not_counted.append({"kind": "no_pf", "position": x["position"],
                            "text": f"{x['task']['name']}: its finds aren't counted: no P-F interval, so every failure "
                                    "goes to the corrective response", "fix": "Add the P-F interval", "link": x["link"]})
    modelled = {r["row"]["position"]["id"] for r in model_rows}
    left_out_at = {x["position"]["id"]: x for x in fc.get("not_forecast") or []}
    for node, _depth in tree:
        if node["id"] in modelled:
            continue
        why = left_out_at.get(node["id"])
        fitted = m.current_fitment(node["id"]) is not None
        if why is not None:
            if why.get("reason", "").startswith("left out: this position's failure modes have lives"):
                continue
            not_counted.append({"kind": "not_forecast", "position": {"id": node["id"], "name": node.get("name", "")},
                                "text": f"{node.get('name', '')}: {why['reason']}", "fix": "Open",
                                "link": _explorer_link(node["id"], root, "models")})
        elif fitted or m._modes_on(node["id"]):
            not_counted.append({"kind": "no_life_model", "position": {"id": node["id"], "name": node.get("name", "")},
                                "text": f"{node.get('name', '')}: no life model, so its failures are not forecast",
                                "fix": "Link a model", "link": _explorer_link(node["id"], root, "models")})
    for x in fc.get("not_on_dates") or []:
        not_counted.append({"kind": "not_on_dates", "position": x["position"],
                            "text": f"{x['task']['name']}: not counted, it can't be put on dates ({x['reason']})",
                            "fix": "Open", "link": _explorer_link(x["position"]["id"], root, "maintenance",
                                                                    mtask=x["task"]["id"])})
    for x in lines:
        for g in x.get("gaps") or []:
            if x.get("kind") == "planned":
                not_counted.append({"kind": f"task_no_{g['view']}", "position": x.get("position"),
                                    "text": f"{x['owner']}: {g['text']}", "fix": "Add", "link": x.get("link")})

    return {
        "lines": lines,
        "totals": {"hours": hours_total, "cost": cost_total,
                   "spares": {"items": list(spares.values()),
                              "like_items": ({"expected": _r(likes["expected"]),
                                              "interval": [_r(likes["interval"][0]), _r(likes["interval"][1])]}
                                             if likes else None),
                              "known": not gaps["spares"], "leaves_out": gaps["spares"]}},
        "not_counted": not_counted,
        "range": "90% two-sided: the 5th to the 95th percentile",
        "rule": ("Planned work belongs to its task; work after a failure, or after an inspection finds it, to the "
                 "failure mode. A node's total is every line at and below it, each counted once."),
    }


MONTHS = (12, 24, 36, 60)


MAX_WORTH = 8  # supporting tasks valued one by one in a forecast


def _failure_side(lines: dict) -> tuple[float, float, bool]:
    """(failures, their cost, cost known) over the corrective and follow-on lines."""
    n = c = 0.0
    known = True
    for x in lines.get("lines") or []:
        if x.get("kind") not in ("corrective", "follow_on"):
            continue
        n += float((x.get("times") or {}).get("expected") or 0.0)
        if x.get("cost") is None:
            known = False
        else:
            c += float(x["cost"].get("expected") or 0.0)
    return n, c, known


def worth(base: dict, dropped: dict, task: dict) -> dict:
    """A supporting task's worth (forecast-rules 4.3): the failures and their cost it avoids (the
    forecast with it dropped against the plan as recorded) for its own cost. A comparison: added to no
    total; the task's cost stays on the task, the failures on the failure mode."""
    n0, c0, k0 = _failure_side(base["lines"])
    n1, c1, k1 = _failure_side(dropped["lines"])
    line = next((x for x in base["lines"]["lines"] if x.get("task_id") == task["id"]), None) or {}
    own = (line.get("cost") or {}).get("expected")
    known = k0 and k1
    out = {"task_id": task["id"], "name": task.get("name") or "", "avoids_failures": _r(n1 - n0, 4),
           "avoids_cost": _r(c1 - c0) if known else None, "costs": own, "known": known,
           "k": ((task.get("support") or {}).get("impact") or {}).get("k"),
           "interval": task.get("interval"), "unit": task.get("unit"),
           "reference": ((task.get("support") or {}).get("reference") or {}).get("value")}
    if known and own is not None:
        out["net"] = _r((c1 - c0) - own)
        out["words"] = (f"Worth: avoids about ${c1 - c0:,.0f} of failures for ${own:,.0f}" if c1 - c0 >= own else
                        f"Worth: avoids about ${c1 - c0:,.0f} of failures for ${own:,.0f}: it costs more than it saves "
                        "here")
    else:
        out["words"] = (f"Worth: avoids about {n1 - n0:.2g} failures; their cost is unknown, so not in money"
                        if not known else f"Worth: avoids about ${c1 - c0:,.0f} of failures; its own cost isn't known")
    return out


def node_forecast(m, fetch, kind: str, node_id: str, root: str | None = None, months=12, whatif=None) -> dict:
    """The forecast with its lines for an Explorer node (Open in ›): a position and everything
    below it, one task (the position it's on, that task and the failures of the modes it serves),
    or a work package (its tasks, from where they meet). From today for ``months`` whole months."""
    from datetime import date

    from dateutil.relativedelta import relativedelta

    from backend.maintenance import position_forecast as pf
    from backend.maintenance.forecast_details import _package_tasks
    from backend.maintenance.service import Invalid, _subject

    try:
        months = int(months or 12)
    except (TypeError, ValueError):
        raise Invalid("months is 12, 24, 36 or 60.") from None
    if months not in MONTHS:
        raise Invalid("months is 12, 24, 36 or 60.")
    task_ids = None
    if kind == "position":
        position_id = m._get(str(node_id), "Position")["id"]
        name = (m.s.node(m.org, position_id) or {}).get("name", "")
    elif kind == "task":
        task = m._get(str(node_id), "Task")
        on = _subject(m.s, m.org, task)
        if on is None or on.get("label") != "Position":
            raise Invalid("Only a task on a position can be forecast here.")
        position_id, task_ids, name = on["id"], [task["id"]], task.get("name", "")
    elif kind == "package":
        pkg = m._get(str(node_id), "WorkPackage")
        task_ids = _package_tasks(m, pkg["id"])
        name = pkg.get("name", "")
        # Where its tasks meet, up the tree as the Explorer shows it (a position an item carries
        # sits in the position that item is fitted to).
        rows = m._tree_read()["positions"]
        chains = []
        for tid in task_ids:
            on = _subject(m.s, m.org, m.s.node(m.org, tid) or {})
            if on is not None and on.get("label") == "Position":
                chain, k = [], on["id"]
                while k and k not in chain:
                    chain.append(k)
                    k = (rows.get(k) or {}).get("parent_id")
                chains.append(list(reversed(chain)))
        if not chains:
            raise Invalid("This package has no task on a position to forecast.")
        common = []
        for level in zip(*chains):
            if len(set(level)) != 1:
                break
            common.append(level[0])
        scope = m.s.node(m.org, root) if root else None
        if scope is not None and scope.get("label") == "Position" and root not in common:
            position_id = root  # its tasks meet above the asset opened: the asset, and what's in it
        elif common:
            position_id = common[-1]
        elif scope is not None:
            raise Invalid("This package's tasks are on positions that sit under no one position here: "
                          "open Hours, Spares or Cost forecast from each position instead.")
        else:
            position_id = chains[0][-1]
    else:
        raise Invalid("Forecast a position, a task or a package.")
    start = date.fromisoformat(m.today())
    end = start + relativedelta(months=months) - relativedelta(days=1)
    def run(plan=None):
        return pf.position_forecast(m, position_id, root, "month", None, fetch=fetch, end=end.isoformat(),
                                    task_ids=task_ids, whatif=plan)

    out = run()
    out["of"] = {"kind": kind, "id": str(node_id), "name": name, "months": months}
    # Supporting tasks: each one's worth (dropped against as planned), and the what-if asked for.
    from backend.maintenance import support_whatif

    scope = [x["position"]["id"] for x in out.get("by_position") or []]
    in_scope = {x.get("task_id") for x in out["lines"]["lines"] if x.get("task_id")}
    tasks = [t for t in support_whatif.supporting_tasks(m, scope)
             if t["id"] in in_scope and ((t.get("support") or {}).get("impact") or {}).get("k")][:MAX_WORTH]
    worths = [worth(out, run({t["id"]: {"drop": True}}), t) for t in tasks]
    out["lines"]["worth"] = worths
    for x in out["lines"]["lines"]:
        got = next((w for w in worths if w["task_id"] == x.get("task_id")), None)
        if got:
            x["worth"] = got
    if whatif:
        if not isinstance(whatif, dict):
            raise Invalid("whatif is {task_id: {drop: true} or {interval: N}} for supporting tasks.")
        known = {t["id"] for t in support_whatif.supporting_tasks(m, scope)}
        wrong = [t for t in whatif if t not in known]
        if wrong:
            raise Invalid("A what-if changes a supporting task here (drop it, or stretch its interval).")
        changed = run(whatif)
        ratios = [r["support_hr"] for r in changed.get("models") or [] if r.get("support_hr")]
        out["whatif"] = {"plan": whatif, "lines": changed["lines"], "rows": changed["rows"],
                         "ratios": ratios, "approximate": any(r["approximate"] for r in ratios)}
    from backend.maintenance.forecast_start import _explorer_link as link_to
    from backend.maintenance.forecast_start import _path

    sel = {"task": f"MT:{node_id}", "package": f"MP:{node_id}"}.get(kind)
    out["from"] = {"kind": kind, "name": name, "path": _path(m, position_id, root),
                   "link": link_to(position_id, root, sel=sel)}
    return out
