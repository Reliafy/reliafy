"""Operating plans: how a position runs, saved as layers.

A plan is exact for the near term and rough after it ("today's and tomorrow's
runs, then about 3 hours a day"), so it has two layers:

* a **background** with no end, which applies wherever nothing more specific is
  given: ``continuous`` (all the time), ``shifts`` (a repeating week of clock
  times), ``roster`` (days on and off), ``rate`` (an amount of running spread
  evenly: 3 hours a day) or ``runs`` (only the runs listed; off otherwise);
* **specific** layers on top, each a list of ``runs`` (on, off) covering its own
  span (``covers``). Inside that span the runs are all the running there is;
  outside it the background applies.

The shape (saved inside ``operating_plan.set`` events, read unchanged later by
the scheduling library)::

    {"version": 1,
     "background": {"kind": "shifts", "shifts": [{"days": ["Monday", ...], "start": "06:00", "stop": "22:00"}]},
     "specific": [{"kind": "runs", "runs": [["2026-11-14T12:31", "2026-11-15T03:27"]],
                   "covers": ["2026-11-14T00:00", "2026-11-15T03:27"]}]}

    background kinds: {"kind": "continuous"}
                      {"kind": "roster", "on": 4, "off": 4, "anchor": "2026-11-16", "start": "07:00", "stop": "19:00"}
                      {"kind": "rate", "amount": 3, "per": "day", "meter": "hours"}
                      {"kind": "runs", "runs": [[on, off], ...]}

Times are the site's wall-clock times (the plan's ``time_zone``), to the minute.

The hours worked out here (``hours_by_day``, ``typical_week``) are a simple
in-app summary for the screen: clock hours with no daylight saving. The
scheduling library's forecast replaces them once the app adopts it. One rule
holds already: where specific runs hand over to the background, the background
counts only the time the runs don't cover, pro rata, so no hours appear or go
missing at the handover and each day's total is the sum of its parts.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

PLAN_VERSION = 1
BACKGROUND_KINDS = ("continuous", "shifts", "roster", "rate", "runs")
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
RATE_PER = {"day": 1.0, "week": 7.0, "month": 365.25 / 12, "year": 365.25}
MAX_RUNS = 2000
MAX_SHIFTS = 14


class PlanError(ValueError):
    """A plan that can't be saved; the message says what to change."""


def _clock(value, name: str) -> str:
    try:
        t = time.fromisoformat(str(value))
    except ValueError:
        raise PlanError(f"{name} is a clock time like 06:00; got {value!r}.") from None
    return t.strftime("%H:%M")


def _moment(value, name: str) -> datetime:
    try:
        m = datetime.fromisoformat(str(value).strip().replace(" ", "T"))
    except ValueError:
        raise PlanError(f"{name} is a date and time like 2026-11-14T12:31; got {value!r}.") from None
    return m.replace(tzinfo=None, second=0, microsecond=0)


def _text(m: datetime) -> str:
    return m.strftime("%Y-%m-%dT%H:%M")


def _weekday(value) -> str:
    name = value.strip().capitalize() if isinstance(value, str) else ""
    for day in WEEKDAYS:
        if len(name) >= 3 and day.startswith(name):
            return day
    raise PlanError(f"A day is a day of the week, such as 'Monday'; got {value!r}.")


def _number(value, name: str, lo: float, hi: float) -> float:
    if isinstance(value, bool):
        raise PlanError(f"{name} is a number, {lo:g} to {hi:g}; got {value!r}.")
    try:
        n = float(value)
    except (TypeError, ValueError):
        raise PlanError(f"{name} is a number, {lo:g} to {hi:g}; got {value!r}.") from None
    if not lo <= n <= hi:
        raise PlanError(f"{name} is a number, {lo:g} to {hi:g}; got {value!r}.")
    return int(n) if n.is_integer() else n


def _runs(value, where: str) -> list[list[str]]:
    if not isinstance(value, list) or not value:
        raise PlanError(f"{where}: give at least one run, [on, off].")
    if len(value) > MAX_RUNS:
        raise PlanError(f"{where}: at most {MAX_RUNS} runs.")
    out = []
    for i, run in enumerate(value, 1):
        if isinstance(run, dict):
            run = [run.get("on"), run.get("off")]
        if not isinstance(run, (list, tuple)) or len(run) != 2:
            raise PlanError(f"{where}, run {i}: a run is [on, off].")
        on, off = _moment(run[0], f"run {i}'s on"), _moment(run[1], f"run {i}'s off")
        if off <= on:
            raise PlanError(f"{where}, run {i}: off ({_text(off)}) must be after on ({_text(on)}).")
        out.append((on, off))
    out.sort()
    for (a_on, a_off), (b_on, b_off) in zip(out, out[1:]):
        if b_on < a_off:
            raise PlanError(f"Two runs overlap: {_text(a_on)} to {_text(a_off)} and {_text(b_on)} to {_text(b_off)}. "
                            "Merge them or fix the times.")
    return [[_text(a), _text(b)] for a, b in out]


def _background(bg) -> dict:
    if not isinstance(bg, dict) or bg.get("kind") not in BACKGROUND_KINDS:
        raise PlanError(f"The plan's background is one of {', '.join(BACKGROUND_KINDS)}: "
                        "{kind: 'shifts', shifts: [{days: ['Monday'], start: '06:00', stop: '22:00'}]}.")
    kind = bg["kind"]
    if kind == "continuous":
        return {"kind": "continuous"}
    if kind == "shifts":
        shifts = bg.get("shifts")
        if not isinstance(shifts, list) or not shifts or len(shifts) > MAX_SHIFTS:
            raise PlanError(f"A repeating week has 1 to {MAX_SHIFTS} shifts, each {{days, start, stop}}.")
        out = []
        for i, sh in enumerate(shifts, 1):
            days = sh.get("days") if isinstance(sh, dict) else None
            if not isinstance(days, list) or not days:
                raise PlanError(f"Shift {i}: say which days it runs.")
            start, stop = _clock(sh.get("start"), f"shift {i}'s start"), _clock(sh.get("stop"), f"shift {i}'s stop")
            if start == stop:
                raise PlanError(f"Shift {i}: its start and stop are the same; for all day use All the time.")
            names = sorted({_weekday(d) for d in days}, key=WEEKDAYS.index)
            out.append({"days": names, "start": start, "stop": stop})
        plan = {"kind": "shifts", "shifts": out}
        _check_shift_overlap(plan)
        return plan
    if kind == "roster":
        on = int(_number(bg.get("on"), "days on", 1, 365))
        off = int(_number(bg.get("off"), "days off", 0, 365))
        try:
            anchor = date.fromisoformat(str(bg.get("anchor"))[:10]).isoformat()
        except ValueError:
            raise PlanError("A roster's anchor is the first day on, like 2026-11-16.") from None
        start = _clock(bg.get("start", "00:00"), "the roster's start")
        stop = _clock(bg.get("stop", "00:00"), "the roster's stop")
        return {"kind": "roster", "on": on, "off": off, "anchor": anchor, "start": start, "stop": stop}
    if kind == "rate":
        per = bg.get("per")
        if per not in RATE_PER:
            raise PlanError("A rate is per day, week, month or year.")
        amount = _number(bg.get("amount"), "the rate", 0.0, 24 * RATE_PER[per])
        if amount <= 0:
            raise PlanError("A rate is more than 0 hours (for a position that doesn't run, end its plan).")
        if bg.get("meter", "hours") != "hours":
            raise PlanError("A rate is in operating hours for now.")
        return {"kind": "rate", "amount": amount, "per": per, "meter": "hours"}
    return {"kind": "runs", "runs": _runs(bg.get("runs"), "The runs")}


def check_plan(plan) -> dict:
    """``plan`` checked and tidied (sorted runs, day names in full, the version
    added); PlanError, saying what to change, when it can't be saved."""
    if not isinstance(plan, dict):
        raise PlanError("A plan is {background: {...}, specific: [...]}.")
    extra = sorted(set(plan) - {"background", "specific", "version"})
    if extra:
        raise PlanError(f"A plan doesn't take {', '.join(extra)}.")
    bg = _background(plan.get("background"))
    specific = []
    for i, layer in enumerate(plan.get("specific") or [], 1):
        if not isinstance(layer, dict) or layer.get("kind", "runs") != "runs":
            raise PlanError(f"Specific layer {i} is {{kind: 'runs', runs: [[on, off], ...], covers?: [from, to]}}.")
        runs = _runs(layer.get("runs"), f"Specific layer {i}")
        if layer.get("covers"):
            cover = [_moment(layer["covers"][0], "covers' start"), _moment(layer["covers"][1], "covers' end")]
        else:
            # Default: from the start of the first run's day to the end of the last run.
            first = _moment(runs[0][0], "on")
            cover = [datetime.combine(first.date(), time()), _moment(runs[-1][1], "off")]
        if cover[1] <= cover[0] or _moment(runs[0][0], "on") < cover[0] or _moment(runs[-1][1], "off") > cover[1]:
            raise PlanError(f"Specific layer {i}: its runs must lie inside the span it covers.")
        specific.append({"kind": "runs", "runs": runs, "covers": [_text(cover[0]), _text(cover[1])]})
    if specific and bg["kind"] == "runs":
        raise PlanError("With a background of runs only, put every run in it (no specific runs on top).")
    spans = sorted((s["covers"][0], s["covers"][1]) for s in specific)
    for a, b in zip(spans, spans[1:]):
        if b[0] < a[1]:
            raise PlanError(f"Two lots of specific runs cover the same time ({b[0]} to {a[1]}): merge them.")
    return {"version": PLAN_VERSION, "background": bg, "specific": specific}


def _day_shifts(bg: dict, day: date) -> list[tuple[datetime, datetime]]:
    """A shifts or roster background's runs that start on ``day``."""
    if bg["kind"] == "shifts":
        found = [sh for sh in bg["shifts"] if WEEKDAYS[day.weekday()] in sh["days"]]
    else:
        cycle = bg["on"] + bg["off"]
        k = (day - date.fromisoformat(bg["anchor"])).days % cycle
        found = [bg] if k < bg["on"] else []
    out = []
    for sh in found:
        a = datetime.combine(day, time.fromisoformat(sh["start"]))
        b = datetime.combine(day, time.fromisoformat(sh["stop"]))
        if b <= a:
            b += timedelta(days=1)
        out.append((a, b))
    return out


def _check_shift_overlap(bg: dict) -> None:
    runs = sorted(r for k in range(8) for r in _day_shifts(bg, date(2024, 1, 1) + timedelta(days=k)))
    for (a_on, a_off), (b_on, b_off) in zip(runs, runs[1:]):
        if b_on < a_off:
            raise PlanError(f"Two shifts overlap on {WEEKDAYS[b_on.weekday()]} ({a_on:%H:%M}–{a_off:%H:%M} and "
                            f"{b_on:%H:%M}–{b_off:%H:%M}): the same hour can't count twice.")


def _clip(intervals, lo: datetime, hi: datetime):
    return [(max(a, lo), min(b, hi)) for a, b in intervals if b > lo and a < hi]


def _minus(lo: datetime, hi: datetime, covers) -> list[tuple[datetime, datetime]]:
    """[lo, hi) less the covered spans."""
    free = [(lo, hi)]
    for c0, c1 in covers:
        nxt = []
        for a, b in free:
            if c1 <= a or c0 >= b:
                nxt.append((a, b))
                continue
            if a < c0:
                nxt.append((a, c0))
            if c1 < b:
                nxt.append((c1, b))
        free = nxt
    return free


def _hours(intervals) -> float:
    return sum((b - a).total_seconds() for a, b in intervals) / 3600


def day_runs(plan: dict, day: date) -> dict:
    """What runs on ``day`` (00:00 to 24:00): ``runs`` as clock intervals (hours from
    midnight, each marked specific or background), ``spread`` (a rate's hours, spread
    over the day's uncovered time), and ``hours`` in all."""
    lo = datetime.combine(day, time())
    hi = lo + timedelta(days=1)
    covers = [(_moment(s["covers"][0], ""), _moment(s["covers"][1], "")) for s in plan.get("specific") or []]
    free = _minus(lo, hi, covers)
    out = []
    for s in plan.get("specific") or []:
        for a, b in _clip([(_moment(x, ""), _moment(y, "")) for x, y in s["runs"]], lo, hi):
            out.append((a, b, "specific"))
    bg = plan["background"]
    spread = 0.0
    if bg["kind"] == "continuous":
        out += [(a, b, "background") for a, b in free]
    elif bg["kind"] in ("shifts", "roster"):
        mine = _day_shifts(bg, day - timedelta(days=1)) + _day_shifts(bg, day)
        for a, b in mine:
            for f0, f1 in free:
                out += [(x, y, "background") for x, y in _clip([(a, b)], max(lo, f0), min(hi, f1))]
    elif bg["kind"] == "runs":
        out += [(a, b, "background") for a, b in _clip([(_moment(x, ""), _moment(y, "")) for x, y in bg["runs"]],
                                                       lo, hi)]
    else:  # rate: spread evenly over the time the specific runs don't cover, pro rata
        spread = bg["amount"] / RATE_PER[bg["per"]] * _hours(free) / 24
    out.sort()
    runs = [{"from": (a - lo).total_seconds() / 3600, "to": (b - lo).total_seconds() / 3600, "layer": layer}
            for a, b, layer in out]
    return {"date": day.isoformat(), "runs": runs, "spread": spread,
            "hours": _hours([(a, b) for a, b, _ in out]) + spread}


def hours_by_day(plan: dict, start: date, days: int = 14) -> list[dict]:
    """``day_runs`` for each of ``days`` days from ``start``."""
    return [day_runs(plan, start + timedelta(days=k)) for k in range(days)]


def typical_week(plan: dict) -> float | None:
    """The background's hours in an ordinary week (None for a background of runs only)."""
    bg = plan["background"]
    if bg["kind"] == "continuous":
        return 168.0
    if bg["kind"] == "rate":
        return bg["amount"] / RATE_PER[bg["per"]] * 7
    if bg["kind"] == "shifts":
        return sum(_hours(_day_shifts(bg, date(2024, 1, 1) + timedelta(days=k))) for k in range(7))
    if bg["kind"] == "roster":
        a, b = _day_shifts({**bg, "on": 1, "off": 0}, date(2024, 1, 1))[0]
        return _hours([(a, b)]) * 7 * bg["on"] / (bg["on"] + bg["off"])
    return None


def describe(plan: dict) -> str:
    """The plan in words: "Monday to Friday, 06:00 to 22:00", "3 hours a day"."""
    bg = plan["background"]
    if bg["kind"] == "continuous":
        text = "All the time"
    elif bg["kind"] == "rate":
        text = f"About {bg['amount']:g} hours a {bg['per']}"
    elif bg["kind"] == "roster":
        text = f"{bg['on']} days on, {bg['off']} off, {bg['start']} to {bg['stop']}"
    elif bg["kind"] == "runs":
        n = len(bg["runs"])
        text = f"{n} run{'s' if n != 1 else ''} only"
    else:
        parts = []
        for sh in bg["shifts"]:
            idx = [WEEKDAYS.index(d) for d in sh["days"]]
            if len(idx) > 2 and idx == list(range(idx[0], idx[-1] + 1)):
                days = f"{sh['days'][0]} to {sh['days'][-1]}"
            else:
                days = ", ".join(d[:3] for d in sh["days"])
            parts.append(f"{days}, {sh['start']} to {sh['stop']}")
        text = "; ".join(parts)
    runs = sum(len(s["runs"]) for s in plan.get("specific") or [])
    if runs:
        end = max(s["covers"][1] for s in plan["specific"])
        text += f"; {runs} set run{'s' if runs != 1 else ''} first, to {end.replace('T', ' ')}"
    return text
