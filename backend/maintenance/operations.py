"""Operations: what a built asset does, position by position (Nov 2026; the Explorer's Operations tab).

The record of how each position runs, read in one go for a whole asset:

* its **duty** (the operating plan: a repeating week, a roster, a rate, runs only, or all the
  time; operating_plan.py), its own or the one it takes from the nearest position above it with
  one ("own", "from Site A"). Inheritance is the same rule ``Maintenance.duty_of`` uses (and so
  running_clock, hour-based packages, forecasts and Optimise): a position with no plan of its own
  in force today runs to the nearest one above it, looked for only inside the asset opened;
* its **other use** (km or cycles a day: the plan's ``meters``);
* the **shutdown and outage windows** that take it off-line: shutdown packages (shutdowns.py) on it
  or on a position above it whose scope covers it, and out-of-service spans set on it or above it,
  each saying where it comes from;
* its **time zone** (the plan's, else the workspace's).

:meth:`OperationsOps.operation_windows` is the small API other features read (through
``shutdowns.shutdown_dates``, the seam "at shutdowns" uses) ("at shutdowns" on a
task or package schedule): one position's effective windows, inherited, in a date range. Nothing
here writes: a duty is set and cleared with ``set_operating_plan`` / ``end_operating_plan``, a
shutdown is a package (``set_package_shutdown``) and an outage is ``take_out_of_service``.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

#: How far ahead windows are listed by default (days from today).
HORIZON_DAYS = 365
#: At most this many windows per shutdown package in a range (a weekly shut over years).
MAX_WINDOWS = 200


def _sv():
    from backend.maintenance import service

    return service


class OperationsOps:
    """The Operations read: every position's effective duty, other use, windows and time zone."""

    # ---- the tree: each live position's parent, as the Explorer's tree has it -------------------

    def _ops_parents(self) -> tuple[dict, dict]:
        """({position id: its node}, {position id: the position it sits in, or None}) for every live
        position. A position carried by an item sits in the position that item is fitted to (as in
        the tree read), so a plan above an engine's turbo is the one on the bay the engine is in."""
        memo = self._memo.get("ops_parents")
        if memo is not None:
            return memo
        s, org = self.s, self.org
        live = {p["id"]: p for p in s.nodes(org, "Position") if not p.get("retired")}
        items = {i["id"] for i in s.nodes(org, "Item") if not i.get("retired")}
        part_of: dict[str, str] = {}
        for src, dst in s.pairs(org, "PART_OF"):
            part_of.setdefault(src, dst)
        fitted_at: dict[str, str] = {}
        at = dict(s.pairs(org, "AT"))
        holder = {dst: src for src, dst in s.pairs(org, "IN")}
        for f in s.nodes(org, "Fitment"):
            if f.get("voided") or f.get("to") is not None:
                continue
            item_id, pos_id = holder.get(f["id"]), at.get(f["id"])
            if item_id and pos_id:
                fitted_at[item_id] = pos_id
        parent: dict[str, str | None] = {}
        for pid in live:
            up = part_of.get(pid)
            if up in items:
                up = fitted_at.get(up)
            parent[pid] = up if up in live else None
        self._memo["ops_parents"] = (live, parent)
        return live, parent

    def _ops_scope(self, root: str | None) -> list[str]:
        """The positions on show: inside the asset opened (``root``: a position, a place or an
        item), else every live position that isn't part of a product's design (a design has no
        operations: the items built from it do)."""
        live, parent = self._ops_parents()
        if root in (None, ""):
            designs = self._design_ids()
            return [pid for pid in live if pid not in designs]
        node = self.s.node(self.org, str(root))
        if node is None or node.get("retired"):
            raise _sv().NotFound(root)
        if node["label"] == "Item":
            # An item's own tree: the positions it carries, and everything inside them.
            kids: dict[str | None, list[str]] = {}
            for pid, up in parent.items():
                kids.setdefault(up, []).append(pid)
            level = [p["id"] for p in self.s.inn(self.org, node["id"], "PART_OF")
                     if p["label"] == "Position" and p["id"] in live]
            out: list[str] = []
            while level:
                out += level
                level = [k for pid in level for k in kids.get(pid, ()) if k not in out]
            return out
        if node["label"] not in ("Position", "Location"):
            raise _sv().NotFound(root)
        return [pid for pid in self.positions_inside(node["id"]) if pid in live]

    # ---- duty: own, or inherited -----------------------------------------------------------------

    def _ops_duty_map(self, ids, root: str | None) -> dict:
        """{position id: (holder id or None, the plan record in force today or None)}: the plan each
        runs to, its own first, else the nearest above it with one, never above ``root``. Each
        position is worked out once (a memo up the tree), so a whole asset is one pass."""
        live, parent = self._ops_parents()
        today = self.today()
        out: dict[str, tuple] = self._memo.setdefault("ops_duty", {}).setdefault(root, {})

        def find(pid: str, seen: frozenset):
            if pid in out:
                return out[pid]
            own = self._plan_on(pid, today)
            if own is not None:
                out[pid] = (pid, own)
            else:
                up = parent.get(pid)
                if pid == root or up is None or up in seen:
                    out[pid] = (None, None)
                else:
                    out[pid] = find(up, seen | {pid})
            return out[pid]

        for pid in ids:
            find(pid, frozenset())
        return out

    def _ops_plan(self, record: dict) -> dict:
        """A plan record as the tab shows it (memoised per read: hours a week come from the library)."""
        memo = self._memo.setdefault("ops_plan", {})
        if record["id"] not in memo:
            brief = self._plan_brief(record, self.today())
            memo[record["id"]] = {k: brief[k] for k in ("id", "name", "text", "hours_per_week", "time_zone", "from",
                                                       "until")} | {"plan": record["plan"]}
        return memo[record["id"]]

    @staticmethod
    def _other_use(plan: dict | None) -> list[dict]:
        """A plan's use that isn't time: [{meter, amount, per, text: "400 km a day"}]."""
        out = []
        for rate in ((plan or {}).get("plan") or {}).get("meters") or []:
            out.append({"meter": rate["meter"], "amount": rate["amount"], "per": rate["per"],
                        "text": f"{rate['amount']:,g} {rate['meter']} a {rate['per']}"})
        return out

    # ---- shutdowns and outages -------------------------------------------------------------------

    def _ops_shutdown_packages(self, start: date, end: date) -> list[dict]:
        """Every live shutdown package with the positions it takes off-line and its windows from
        ``start`` to ``end``: [{package, subject, covers (set of position ids), windows}]. Memoised
        per read and range."""
        memo = self._memo.setdefault("ops_shutdowns", {})
        key = (start.isoformat(), end.isoformat())
        if key in memo:
            return memo[key]
        live, parent = self._ops_parents()
        kids: dict[str | None, list[str]] = {}
        for pid, up in parent.items():
            kids.setdefault(up, []).append(pid)

        def below(pid: str) -> set:
            found, level = set(), [pid]
            while level:
                found.update(level)
                level = [k for x in level for k in kids.get(x, ()) if k not in found]
            return found

        out = []
        for pkg in self.s.nodes(self.org, "WorkPackage"):
            sd = pkg.get("shutdown")
            if pkg.get("retired") or pkg.get("paused") or not sd:
                continue
            subject = self._package_made_on(pkg)
            if subject is None or subject["label"] != "Position" or subject["id"] not in live:
                continue
            covers: set = set()
            for pid in sd.get("scope") or [subject["id"]]:
                if pid in live:
                    covers |= below(pid)
            if sd.get("dates"):
                days = [d for d in sd["dates"] if start.isoformat() <= d <= end.isoformat()][:MAX_WINDOWS]
                rule = "on set dates"
            else:
                try:
                    days = [d.isoformat() for d in self._cadence(pkg).dates(start, end, MAX_WINDOWS)]
                except (ValueError, TypeError, KeyError):
                    days = []
                days = [d for d in days if self._in_season(pkg, d)]
                rule = self._cadence_text(pkg)
            hours = float(sd["duration_hours"])
            windows = []
            for d in days:
                a = datetime.fromisoformat(d)
                windows.append({"start": d, "end": (a + timedelta(hours=hours)).isoformat(timespec="minutes"),
                                "hours": hours})
            out.append({"package": pkg, "subject": subject, "covers": covers, "windows": windows, "rule": rule})
        memo[key] = out
        return out

    def _ops_outages(self, pid: str, today: str) -> list[dict]:
        """Out-of-service spans that hold ``pid`` now or later: set on it, or on a position or an
        item it's inside (as tasks are held: ``_out_of_service_on``)."""
        out, node_id, seen = [], pid, set()
        while node_id and node_id not in seen:
            seen.add(node_id)
            node = self.s.node(self.org, node_id)
            if node is None:
                break
            entry = node.get("out_of_service")
            if entry and entry.get("from") and not (entry.get("until") and entry["until"] <= today):
                out.append({"kind": "outage", "name": entry.get("reason") or "Out of service",
                            "start": entry["from"], "end": entry.get("until"), "hours": None, "cost": None,
                            "reason": entry.get("reason", ""), "rule": None, "package_id": None,
                            "source": {"id": node["id"], "name": node.get("name", ""), "kind": node["label"].lower()},
                            "own": node["id"] == pid})
            parent = self._parent(node_id) if node["label"] in ("Position", "Item") else None
            node_id = parent and parent["id"]
        return out

    def operation_windows(self, position_id: str, start=None, end=None, root: str | None = None) -> list[dict]:
        """The windows that take a position off-line from ``start`` (default today) to ``end``
        (default a year on), its own and those it inherits, oldest first:

        * ``kind`` "shutdown": a visit of a shutdown package on it or above it whose scope covers it
          (``start``, ``end`` as date-times, ``hours``, ``cost`` each time, ``rule`` its cadence,
          ``package_id``);
        * ``kind`` "outage": an out-of-service span on it or above it (``end`` None: open-ended).

        Each says ``source`` {id, name} (where it's set) and ``own``. ``root``: the asset opened;
        a shutdown set above it doesn't count. This is the read "at shutdowns" schedules use."""
        sv = _sv()
        node = self.s.node(self.org, str(position_id or ""))
        if node is None or node["label"] != "Position" or node.get("retired"):
            raise sv.NotFound(f"Position {position_id}")
        today = self.today()
        lo = date.fromisoformat(str(start)[:10]) if start not in (None, "") else date.fromisoformat(today)
        hi = date.fromisoformat(str(end)[:10]) if end not in (None, "") else lo + timedelta(days=HORIZON_DAYS)
        if hi < lo:
            raise sv.Invalid("The end of the range is on or after its start.")
        allowed = None
        if root not in (None, ""):
            allowed = set(self._ops_scope(root))
        return self._windows_for(node["id"], lo, hi, allowed, today)

    def _windows_for(self, pid: str, lo: date, hi: date, allowed, today: str) -> list[dict]:
        out = []
        for entry in self._ops_shutdown_packages(lo, hi):
            subject = entry["subject"]
            if pid not in entry["covers"] or (allowed is not None and subject["id"] not in allowed):
                continue
            sd, pkg = entry["package"]["shutdown"], entry["package"]
            for w in entry["windows"]:
                out.append({"kind": "shutdown", "name": pkg.get("name", ""), **w, "cost": sd.get("cost"),
                            "reason": "", "rule": entry["rule"], "package_id": pkg["id"],
                            "source": {"id": subject["id"], "name": subject.get("name", ""), "kind": "position"},
                            "own": subject["id"] == pid})
        for o in self._ops_outages(pid, today):
            if allowed is not None and o["source"]["kind"] == "position" and o["source"]["id"] not in allowed:
                continue
            if o["start"] <= hi.isoformat() and (o["end"] is None or o["end"] > lo.isoformat()):
                out.append(o)
        out.sort(key=lambda w: (w["start"], w["kind"], w["name"]))
        return out

    # ---- the read --------------------------------------------------------------------------------

    def operations(self, root: str | None = None, position_id: str | None = None,
                   horizon_days: int = HORIZON_DAYS) -> dict:
        """Every position's operations inside ``root`` (the asset opened; default every built
        asset), or one position's (``position_id``), in one read: {today, time_zone (the
        workspace's), horizon {from, to}, positions: [{id, name, parent_id, duty {source "own" |
        "inherited" | "none", from {id, name} (inherited), plan {id, name, text, hours_per_week,
        time_zone, from, until, plan}}, own_plan (its own plan in force today, or None), parent_duty
        (what Clear would leave it on: {source, from, text} or None), other_use [{meter, amount,
        per, text}], windows (operation_windows: own and inherited), time_zone {zone, source}}]}."""
        live, parent = self._ops_parents()
        if position_id not in (None, ""):
            node = self.s.node(self.org, str(position_id))
            if node is None or node["label"] != "Position" or node.get("retired"):
                raise _sv().NotFound(f"Position {position_id}")
            if root not in (None, "") and node["id"] not in set(self._ops_scope(root)):
                raise _sv().NotFound(f"Position {position_id}")
            ids = [node["id"]]
        else:
            ids = self._ops_scope(root)
        today = self.today()
        lo = date.fromisoformat(today)
        hi = lo + timedelta(days=max(1, min(int(horizon_days or HORIZON_DAYS), 3 * 366)))
        root_id = root if root not in (None, "") and root in live else None
        allowed = set(self._ops_scope(root)) if root not in (None, "") else None
        duty = self._ops_duty_map(ids, root_id)
        rows = []
        for pid in ids:
            holder, record = duty[pid]
            plan = self._ops_plan(record) if record else None
            if record is None:
                d = {"source": "none", "from": None, "plan": None}
            elif holder == pid:
                d = {"source": "own", "from": None, "plan": plan}
            else:
                d = {"source": "inherited", "from": {"id": holder, "name": live[holder].get("name", "")}, "plan": plan}
            # What clearing its own plan would leave it on: the duty of the position above it.
            parent_duty = None
            if d["source"] == "own" and parent.get(pid) and pid != root_id:
                up_holder, up_record = self._ops_duty_map([parent[pid]], root_id)[parent[pid]]
                parent_duty = ({"source": "none", "from": None, "text": "All the time"} if up_record is None else
                               {"source": "inherited", "from": {"id": up_holder, "name": live[up_holder].get("name", "")},
                                "text": self._ops_plan(up_record)["text"]})
            elif d["source"] == "own":
                parent_duty = {"source": "none", "from": None, "text": "All the time"}
            zone = plan["time_zone"] if plan else self.time_zone
            rows.append({
                "id": pid, "name": live[pid].get("name", ""), "parent_id": parent.get(pid),
                "duty": d, "own_plan": plan if d["source"] == "own" else None, "parent_duty": parent_duty,
                "other_use": self._other_use(plan),
                "windows": self._windows_for(pid, lo, hi, allowed, today),
                "time_zone": {"zone": zone, "source": "plan" if plan else "workspace"},
            })
        return {"today": today, "time_zone": self.time_zone, "horizon": {"from": lo.isoformat(), "to": hi.isoformat()},
                "positions": rows}
