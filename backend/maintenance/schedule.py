"""Maintenance scheduling: tasks on the calendar and tasks by use, and the
dates and times they fall due.

Moved from RePyability's ``repyability.maintenance`` (derrynknife/RePyability
#319, never released there): RePyability keeps to timelines (model time,
from a state), and calendars belong here. The use cases they were built
from are in ``docs/maintenance-scheduling.md``.

* **On the calendar:** a ``Task`` every so many days from its first date
  (``every=``, ``first=``), or on the days a ``Monthly`` rule names (``on=``:
  the 30th, the first Tuesday; ``starting=``, optionally, the date it applies
  from). A calendar task happens on its dates whatever the equipment does, so
  the dates it falls due in a period are date arithmetic, exact. Dates are
  whole days, and a period includes both of its ends ("through 31
  December"). Every schedule is a python-dateutil recurrence rule
  (``rrule``, the iCalendar standard's).
* **By use:** an ``Asset`` runs in ``Window``s of clock time (days of the
  week, from a start time to a stop time, overnight when the stop is
  earlier); each run adds its hours to the ``"hours"`` meter and one to
  ``"starts"``, from the meters as read at a time. A ``Task`` every
  ``Hours(...)`` or ``Starts(...)`` falls due when its meter crosses the next
  multiple after the reading at its last time (``last_done``): exact, with
  every run going ahead. Clock times, with no daylight saving.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, fields
from datetime import date, datetime, time, timedelta
from numbers import Real
from typing import Any, Dict, Iterator, Optional, Set, Tuple, Union

import numpy as np
from dateutil.rrule import DAILY, FR, MO, MONTHLY, SA, SU, TH, TU, WE, rrule


def _is_number(value) -> bool:
    """Whether ``value`` is a real number: not a bool, nor text that reads
    as a number."""
    if isinstance(value, (bool, np.bool_)):
        return False
    return isinstance(value, Real)


def _is_whole(value) -> bool:
    """Whether ``value`` is a whole number: ``3`` or ``3.0``, but not
    ``True``."""
    if isinstance(value, (bool, np.bool_)):
        return False
    if isinstance(value, (int, np.integer)):
        return True
    return isinstance(value, (float, np.floating)) and float(value).is_integer()


def _whole_number(value, name: str, minimum: int = 1) -> int:
    """``value`` as an ``int``, if it is a whole number of at least
    ``minimum``; else a ``ValueError`` that names it."""
    if not _is_whole(value) or value < minimum:
        raise ValueError(
            f"{name} must be a whole number, at least {minimum}, got {value!r}."
        )
    return int(value)


def _one_of(name: str, value, choices: tuple) -> None:
    """Refuse ``value`` for the option ``name`` unless it is one of
    ``choices``."""
    if value not in choices:
        listed = " or ".join(repr(c) for c in choices)
        raise ValueError(f"{name} must be {listed}, got {value!r}.")


def _plain(value) -> Any:
    """``value`` as plain data, for JSON: dates and times as ISO text,
    tuples as lists."""
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    return value


class _Result:
    """A result's fields as plain data (``to_dict``), ready for JSON."""

    def to_dict(self) -> dict:
        return {f.name: _plain(getattr(self, f.name)) for f in fields(self)}

#: The days of the week, by their names and the first three letters.
_DAYS = {
    name: number
    for number, full in enumerate(
        (
            "monday",
            "tuesday",
            "wednesday",
            "thursday",
            "friday",
            "saturday",
            "sunday",
        )
    )
    for name in (full, full[:3])
}

#: The meters an asset may have: what each run adds to them.
METERS = ("hours", "starts")

_HOUR = timedelta(hours=1)


def _weekdays(days) -> Tuple[int, ...]:
    """``days`` as weekday numbers (Monday 0): text naming days and ranges,
    separated by commas, such as ``"Mon-Fri"`` or ``"Mon, Wed, Fri"``; a
    range may wrap round the week (``"Fri-Mon"``)."""
    if not isinstance(days, str):
        raise TypeError(
            "days must be text naming days of the week, such as 'Mon-Fri' "
            f"or 'Mon, Wed, Fri'; got {days!r}."
        )
    numbers: Set[int] = set()
    for part in days.split(","):
        ends = [end.strip().lower() for end in part.split("-")]
        if len(ends) > 2 or not all(end in _DAYS for end in ends):
            raise ValueError(
                "days must name days of the week, or ranges of them, "
                f"separated by commas (such as 'Mon-Fri'); got {days!r}."
            )
        first, last = _DAYS[ends[0]], _DAYS[ends[-1]]
        numbers.update((first + k) % 7 for k in range((last - first) % 7 + 1))
    return tuple(sorted(numbers))


def _clock(value, name: str) -> time:
    """``value`` as a clock time: a ``datetime.time``, or text such as
    ``"06:00"``."""
    if isinstance(value, time):
        return value
    if isinstance(value, str):
        try:
            return time.fromisoformat(value)
        except ValueError:
            raise ValueError(
                f"{name} must be a clock time written as HH:MM, such as "
                f"'06:00'; got {value!r}."
            ) from None
    raise TypeError(
        f"{name} must be a clock time (a datetime.time, or text such as "
        f"'06:00'); got {value!r}."
    )


def _moment(value, name: str) -> datetime:
    """``value`` as a date and time: a ``datetime``, a ``date`` (its
    midnight), or ISO text such as ``"2026-10-12 06:00"``."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, time())
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            raise ValueError(
                f"{name} must be a date and time written as YYYY-MM-DD "
                f"HH:MM, such as '2026-10-12 06:00'; got {value!r}."
            ) from None
    raise TypeError(
        f"{name} must be a date and time (a datetime, or text such as "
        f"'2026-10-12 06:00'); got {value!r}."
    )


@dataclass(frozen=True, init=False)
class Window:
    """When an ``Asset`` runs: on the days named, from
    a start time to a stop time.

    Parameters
    ----------
    days : str
        The days of the week a run starts on: names or their first three
        letters, and ranges of them, separated by commas (``"Mon-Fri"``,
        ``"Sat"``, ``"Mon, Wed, Fri"``). A range may wrap round the week.
    start, stop : datetime.time or str
        The clock times a run starts and stops, such as ``"06:00"`` and
        ``"22:00"``. A stop earlier than the start is on the next day (a
        run overnight); the two may not be the same.

    Examples
    --------
    >>> from backend.maintenance.schedule import Window
    >>> shift = Window("Mon-Fri", "06:00", "22:00")
    >>> shift.hours
    16.0
    >>> Window("Fri", "22:00", "06:00").hours
    8.0
    """

    days: Tuple[int, ...]
    start: time
    stop: time

    def __init__(self, days, start, stop) -> None:
        start, stop = _clock(start, "start"), _clock(stop, "stop")
        if start == stop:
            raise ValueError(
                f"A run cannot start and stop at the same time ({start}): "
                "give when it stops."
            )
        object.__setattr__(self, "days", _weekdays(days))
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "stop", stop)

    @property
    def hours(self) -> float:
        """The hours of each run."""
        day = date(2000, 1, 3)
        begins, ends = self._run(day)
        return (ends - begins) / _HOUR

    def _run(self, day: date) -> Tuple[datetime, datetime]:
        """The run starting on ``day``: its start and stop."""
        begins = datetime.combine(day, self.start)
        ends = datetime.combine(day, self.stop)
        if self.stop < self.start:
            ends += timedelta(days=1)
        return begins, ends


@dataclass(frozen=True, init=False, eq=False)
class Asset:
    """An asset that runs to an operating schedule, with meters read at a
    time: a pump on shifts, an aircraft's flights.

    Parameters
    ----------
    name : str
        What the asset is called.
    runs : Window or sequence of Window
        When it runs. Its windows' runs may not overlap.
    meters : dict
        Its meters' readings: ``"hours"`` (its running hours) and
        ``"starts"`` (how many runs it has started), each at least 0.
    read_at : datetime.datetime or str
        When the meters were read, such as ``"2026-10-12 00:00"``. A run
        in progress then counts from that time on; one starting then
        counts its start.

    Examples
    --------
    >>> from backend.maintenance.schedule import Asset, Window
    >>> pump = Asset(
    ...     "pump 1",
    ...     runs=Window("Mon-Fri", "06:00", "22:00"),
    ...     meters={"hours": 12_340},
    ...     read_at="2026-10-12 00:00",
    ... )
    >>> pump.meters
    {'hours': 12340.0}
    """

    name: str
    runs: Tuple[Window, ...]
    meters: Dict[str, float]
    read_at: datetime

    def __init__(self, name: str, runs, meters, read_at) -> None:
        if not isinstance(name, str):
            raise TypeError(f"name must be text; got {name!r}.")
        windows = (runs,) if isinstance(runs, Window) else tuple(runs)
        if not windows or not all(isinstance(w, Window) for w in windows):
            raise TypeError(
                "runs must be a Window, or a sequence of them, at least "
                f"one; got {runs!r}."
            )
        if not isinstance(meters, dict) or not meters:
            raise TypeError(
                "meters must be a dict of readings, such as {'hours': "
                f"12340}}; got {meters!r}."
            )
        readings = {}
        for meter, reading in meters.items():
            if meter not in METERS:
                raise ValueError(
                    f"An asset has the meters {', '.join(METERS)}; got "
                    f"{meter!r}."
                )
            if not (
                _is_number(reading) and 0.0 <= float(reading) < math.inf
            ):
                raise ValueError(
                    f"The reading of meter {meter!r} must be a number, at "
                    f"least 0; got {reading!r}."
                )
            readings[meter] = float(reading)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "runs", windows)
        object.__setattr__(self, "meters", readings)
        object.__setattr__(self, "read_at", _moment(read_at, "read_at"))
        self._check_runs_apart()

    def _check_runs_apart(self) -> None:
        """Refuse windows whose runs overlap, which would count the same
        hours twice: over a fortnight, every run of every window."""
        start = self.read_at
        runs = list(self._runs(start, start + timedelta(days=15)))
        for (_, ended), (begun, _) in zip(runs, runs[1:]):
            if begun < ended:
                raise ValueError(
                    f"The runs of asset {self.name!r} overlap (one starts "
                    f"at {begun}, before another stops, at {ended}): each "
                    "hour may be in one run only."
                )

    def _runs(
        self, start: datetime, end: datetime
    ) -> Iterator[Tuple[datetime, datetime]]:
        """Every run that is going on or starts from ``start`` to before
        ``end``, in order of their starts."""
        day = start.date() - timedelta(days=1)
        while datetime.combine(day, time()) < end:
            runs = sorted(
                window._run(day)
                for window in self.runs
                if day.weekday() in window.days
            )
            for begins, ends in runs:
                if ends > start and begins < end:
                    yield begins, ends
            day += timedelta(days=1)


@dataclass(frozen=True, init=False)
class Hours:
    """A task's interval in running hours: ``Hours(500)``, a task every
    500 hours of an ``Asset``'s running."""

    amount: float

    def __init__(self, amount) -> None:
        if not (_is_number(amount) and 0.0 < float(amount) < math.inf):
            raise ValueError(
                f"Hours must be a number, more than 0; got {amount!r}."
            )
        object.__setattr__(self, "amount", float(amount))

    meter = "hours"


@dataclass(frozen=True, init=False)
class Starts:
    """A task's interval in starts: ``Starts(1000)``, a task every 1,000
    runs an ``Asset`` starts (an aircraft's cycles, a
    pump's starts)."""

    amount: float

    def __init__(self, amount) -> None:
        if not (_is_whole(amount) and amount >= 1):
            raise ValueError(
                f"Starts must be a whole number, at least 1; got {amount!r}."
            )
        object.__setattr__(self, "amount", float(amount))

    meter = "starts"


Usage = Union[Hours, Starts]


def crossings(
    asset: Asset,
    every: Usage,
    last_done: float,
    start: datetime,
    end: datetime,
) -> Tuple[Tuple[float, ...], Tuple[datetime, ...]]:
    """The readings at which a task every ``every`` of ``asset``, last done
    at ``last_done``, falls due from ``start`` to before ``end``, and the
    times its meter crosses them (see the module's notes)."""
    meter = asset.meters[every.meter]
    target = last_done + every.amount
    readings, times = [], []
    for begins, ends in asset._runs(asset.read_at, end):
        if every.meter == "starts":
            if begins < asset.read_at:
                continue
            meter += 1.0
            while target <= meter:
                if begins >= start:
                    readings.append(target)
                    times.append(begins)
                target += every.amount
        else:
            begun = max(begins, asset.read_at)
            run = (ends - begun) / _HOUR
            while target <= meter + run:
                moment = begun + (target - meter) * _HOUR
                if moment >= end:
                    break
                if moment >= start:
                    readings.append(target)
                    times.append(moment)
                target += every.amount
            meter += run
    return tuple(readings), tuple(times)


@dataclass
class UsageDue(_Result):
    """When a ``Task`` by use falls due in a period:
    returned by its ``due``.

    Attributes
    ----------
    task : str
        The task's name.
    start, end : datetime.date
        The period's first and last days, both included.
    meter : str
        The meter the task goes by: ``"hours"`` or ``"starts"``.
    readings : tuple of float
        The meter readings at which it falls due in the period, in order.
    times : tuple of datetime.datetime
        When the meter reaches each of them.
    count : int
        How many fall due in the period.
    cost : float or None
        What they cost: the task's cost each time, times ``count``; None
        if the task was given no cost.
    """

    task: str
    start: date
    end: date
    meter: str
    readings: Tuple[float, ...]
    times: Tuple[datetime, ...]
    count: int
    cost: Optional[float]


#: The days of the week, by name, as dateutil's weekdays.
_WEEKDAYS = {
    "Monday": MO,
    "Tuesday": TU,
    "Wednesday": WE,
    "Thursday": TH,
    "Friday": FR,
    "Saturday": SA,
    "Sunday": SU,
}

#: The weekdays of a month a monthly rule may name: first to fourth, and
#: last to fourth from last, which every month has.
_NTHS = (1, 2, 3, 4, -1, -2, -3, -4)


def _date(value, name: str) -> date:
    """``value`` as a ``date``: a ``datetime.date``, or ISO text such as
    ``"2026-07-15"``; a ``datetime`` is refused, as a task's dates are
    whole days."""
    if isinstance(value, datetime):
        raise TypeError(
            f"{name} must be a date (a datetime.date, or text such as "
            f"'2026-07-15'), without a time of day; got {value!r}."
        )
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            raise ValueError(
                f"{name} must be a date written as YYYY-MM-DD, such as "
                f"'2026-07-15'; got {value!r}."
            ) from None
    raise TypeError(
        f"{name} must be a date (a datetime.date, or text such as "
        f"'2026-07-15'); got {value!r}."
    )


def _interval(value) -> timedelta:
    """``value`` as a whole number of days, at least one: a
    ``datetime.timedelta``, or a number of days."""
    if isinstance(value, timedelta):
        days = value / timedelta(days=1)
        if not days.is_integer() or days < 1:
            raise ValueError(
                "every must be a whole number of days, at least one; got "
                f"{value!r}."
            )
        return value
    if _is_number(value):
        return timedelta(days=_whole_number(value, "every"))
    raise TypeError(
        "every must be a datetime.timedelta or a number of days (a task "
        "by use takes Hours(...) or Starts(...)); got "
        f"{value!r}."
    )


def _midnight(day: date) -> datetime:
    """``day`` as dateutil takes it, a ``datetime`` at its start."""
    return datetime.combine(day, time())


@dataclass(frozen=True, init=False)
class Monthly:
    """A monthly rule naming the days a ``Task`` falls
    due (its ``on``): a day of the month (the 30th), or a weekday of it
    (the first Tuesday).

    Parameters
    ----------
    day : int, optional
        The day of the month, 1 to 31.
    weekday : str, optional
        The day of the week, by name (``"Tuesday"``; any case), with
        ``nth``. Give a ``day`` or a ``weekday``, not both.
    nth : int, optional
        Which of the month's ``weekday`` s: 1 to 4 (the first to the
        fourth), or -1 to -4 (the last to the fourth from last), which
        every month has.
    short_months : {"last", "skip"}, optional
        With a ``day`` past the 28th, what a month too short for it does:
        ``"last"`` (the default) falls due on its last day instead (the
        28th or 29th of February for the 30th); ``"skip"`` does not fall
        due that month.

    Examples
    --------
    On the 30th of every month, on 28 February in 2027:

    >>> from backend.maintenance.schedule import Monthly, Task
    >>> readings = Task("meter reading", on=Monthly(day=30))
    >>> due = readings.due("2027-01-01", "2027-03-31")
    >>> [day.isoformat() for day in due.dates]
    ['2027-01-30', '2027-02-28', '2027-03-30']

    On the first Tuesday:

    >>> pumps = Task("check pumps", on=Monthly(weekday="Tuesday", nth=1))
    >>> pumps.due("2026-10-11", "2026-12-31").count
    2
    """

    day: Optional[int]
    weekday: Optional[str]
    nth: Optional[int]
    short_months: Optional[str]

    def __init__(
        self, *, day=None, weekday=None, nth=None, short_months=None
    ) -> None:
        if (day is None) == (weekday is None):
            raise ValueError(
                "Monthly takes a day of the month (Monthly(day=30)) or a "
                "weekday (Monthly(weekday='Tuesday', nth=1)), not both or "
                "neither."
            )
        if day is not None:
            day = _whole_number(day, "day")
            if day > 31:
                raise ValueError(f"day must be 1 to 31; got {day!r}.")
            if nth is not None:
                raise ValueError(
                    "nth goes with a weekday, which this rule has not: it "
                    f"is on day {day} of the month."
                )
            short_months = "last" if short_months is None else short_months
            _one_of("short_months", short_months, ("last", "skip"))
        else:
            name = weekday.capitalize() if isinstance(weekday, str) else None
            if name not in _WEEKDAYS:
                raise ValueError(
                    "weekday must be a day of the week, such as 'Tuesday'; "
                    f"got {weekday!r}."
                )
            weekday = name
            if not _is_whole(nth) or int(nth) not in _NTHS:
                raise ValueError(
                    "nth must be 1 to 4 (the first to the fourth) or -1 to "
                    "-4 (the last to the fourth from last), which every "
                    f"month has; got {nth!r}."
                )
            nth = int(nth)
            if short_months is not None:
                raise ValueError(
                    "short_months goes with a day of the month: every month "
                    f"has a {_ordinal(nth)} {weekday}."
                )
        object.__setattr__(self, "day", day)
        object.__setattr__(self, "weekday", weekday)
        object.__setattr__(self, "nth", nth)
        object.__setattr__(self, "short_months", short_months)

    def _rule(self, first: date) -> rrule:
        """The rule's dates from ``first`` on."""
        start = _midnight(first)
        if self.weekday is not None:
            assert self.nth is not None
            weekday = _WEEKDAYS[self.weekday](self.nth)
            return rrule(MONTHLY, dtstart=start, byweekday=weekday)
        assert self.day is not None
        if self.day <= 28 or self.short_months == "skip":
            return rrule(MONTHLY, dtstart=start, bymonthday=self.day)
        # The latest of the 28th up to the day that the month has.
        return rrule(
            MONTHLY,
            dtstart=start,
            bymonthday=tuple(range(28, self.day + 1)),
            bysetpos=-1,
        )


def _ordinal(nth: int) -> str:
    """``nth`` in words: "first", "last", "second from last"."""
    words = {1: "first", 2: "second", 3: "third", 4: "fourth"}
    if nth > 0:
        return words[nth]
    return "last" if nth == -1 else f"{words[-nth]} from last"


@dataclass(frozen=True, init=False)
class Task:
    """A task: on the calendar, every so many days from its first date or
    on the days a monthly rule names, whatever the equipment does; or by
    use, every so many hours or starts of an asset.

    Parameters
    ----------
    name : str
        What the task is called.
    every : datetime.timedelta, int, Hours or Starts, optional
        An interval between one time and the next: on the calendar, a
        whole number of days, at least one, as a ``timedelta``
        (``timedelta(weeks=1)``) or a number of days (``7``); by use, the
        running hours or starts of ``asset`` (``Hours``,
        ``Starts``). Give ``every`` or ``on``.
    on : Monthly, optional
        A rule naming the days the task falls due
        (``Monthly``: the 30th, the first Tuesday).
    first : datetime.date or str, optional
        With an interval on the calendar: the first time the task is done,
        as a date or as text such as ``"2026-07-15"``.
    starting : datetime.date or str, optional
        With a rule (``on``): the date from which it applies. By default
        None: the rule's days whenever asked.
    cost : float, optional
        What it costs each time it is done, at least 0, in your currency.
        By default None: not given, and the dates it falls due have no
        cost.
    asset : Asset, optional
        For a task by use: the ``Asset`` whose meter it
        goes by.
    last_done : float, optional
        For a task by use: the meter reading at its last time, at most the
        asset's reading, which must not yet have reached the next.

    Examples
    --------
    A weekly task first done on Wednesday 15 July 2026 falls due 12 times
    from Sunday 11 October to the end of 2026, at 250 each time 3000:

    >>> from datetime import timedelta
    >>> from backend.maintenance.schedule import Task
    >>> conveyor = Task(
    ...     "inspect conveyor",
    ...     every=timedelta(weeks=1),
    ...     first="2026-07-15",
    ...     cost=250.0,
    ... )
    >>> due = conveyor.due("2026-10-11", "2026-12-31")
    >>> due.count, due.cost
    (12, 3000.0)
    >>> due.dates[0], due.dates[-1]
    (datetime.date(2026, 10, 14), datetime.date(2026, 12, 30))

    On the 30th of each month (the last day of a shorter one):

    >>> from backend.maintenance.schedule import Monthly
    >>> readings = Task("meter reading", on=Monthly(day=30))
    >>> [day.isoformat() for day in readings.due(
    ...     "2027-01-01", "2027-03-31").dates]
    ['2027-01-30', '2027-02-28', '2027-03-30']

    By use: a pump that runs 06:00 to 22:00 on weekdays, serviced every
    500 running hours, its meter at 12,340 hours on Monday 12 October
    2026, before its start:

    >>> from backend.maintenance.schedule import Asset, Hours, Window
    >>> pump = Asset(
    ...     "pump 1",
    ...     runs=Window("Mon-Fri", "06:00", "22:00"),
    ...     meters={"hours": 12_340},
    ...     read_at="2026-10-12 00:00",
    ... )
    >>> service = Task(
    ...     "pump service", every=Hours(500), asset=pump, last_done=12_000
    ... )
    >>> [str(time) for time in service.due("2026-10-12", "2026-12-31").times]
    ['2026-10-23 22:00:00', '2026-12-08 10:00:00']
    """

    name: str
    every: Union[timedelta, Hours, Starts, None]
    on: Optional[Monthly]
    first: Optional[date]
    starting: Optional[date]
    cost: Optional[float]
    asset: Optional[Asset]
    last_done: Optional[float]

    def __init__(
        self,
        name: str,
        *,
        every=None,
        on=None,
        first=None,
        starting=None,
        cost=None,
        asset=None,
        last_done=None,
    ) -> None:
        if not isinstance(name, str):
            raise TypeError(f"name must be text; got {name!r}.")
        if cost is not None and not (
            _is_number(cost) and 0.0 <= float(cost) < float("inf")
        ):
            raise ValueError(
                f"cost must be a number, at least 0 (or None); got {cost!r}."
            )
        if isinstance(every, Monthly):
            raise TypeError(
                "A monthly rule names the days a task falls due: give it as "
                "on=Monthly(...), not every=."
            )
        if (every is None) == (on is None):
            raise TypeError(
                "A task needs an interval (every=...) or a rule naming its "
                "days (on=Monthly(...)), one of them."
            )
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "cost", None if cost is None else float(cost))
        for field in ("every", "on", "first", "starting", "asset"):
            object.__setattr__(self, field, None)
        object.__setattr__(self, "last_done", None)
        if on is not None:
            self._on_rule(on, first, starting, asset, last_done)
        elif isinstance(every, (Hours, Starts)):
            object.__setattr__(self, "every", every)
            self._by_use(first, starting, asset, last_done)
        else:
            self._interval(every, first, starting, asset, last_done)

    def _on_rule(self, on, first, starting, asset, last_done) -> None:
        """Check and keep a task on the days a rule names."""
        if not isinstance(on, Monthly):
            raise TypeError(
                f"on must be a rule naming days (Monthly(...)); got {on!r}."
            )
        if first is not None:
            raise ValueError(
                "A rule's days are not counted from a first time: give the "
                "date it applies from as starting=, not first=."
            )
        if asset is not None or last_done is not None:
            raise ValueError(
                "asset and last_done go with a task by use (every=Hours(...) "
                "or Starts(...)), not with a rule naming days."
            )
        object.__setattr__(self, "on", on)
        if starting is not None:
            object.__setattr__(self, "starting", _date(starting, "starting"))

    def _interval(self, every, first, starting, asset, last_done) -> None:
        """Check and keep a task every so many days from its first date."""
        if asset is not None or last_done is not None:
            raise ValueError(
                "asset and last_done go with a task by use (every=Hours(...) "
                f"or Starts(...)); this one is every {every!r}."
            )
        if starting is not None:
            raise ValueError(
                "starting goes with a rule naming days (on=); an interval "
                "counts from the first time the task is done (first=)."
            )
        if first is None:
            raise TypeError(
                "A task every so many days needs the first time it is done "
                "(first=...)."
            )
        object.__setattr__(self, "every", _interval(every))
        object.__setattr__(self, "first", _date(first, "first"))

    def _by_use(self, first, starting, asset, last_done) -> None:
        """Check and keep a task by use: its asset, with the meter it goes
        by, and the reading at its last time."""
        every = self.every
        assert isinstance(every, (Hours, Starts))
        if first is not None or starting is not None:
            raise ValueError(
                "A task by use falls due by its asset's meter, not from a "
                "date: give last_done (the meter reading at its last time), "
                "and no first or starting."
            )
        if not isinstance(asset, Asset):
            raise TypeError(
                f"A task by use needs its asset (asset=...); got {asset!r}."
            )
        if every.meter not in asset.meters:
            raise ValueError(
                f"Asset {asset.name!r} has no {every.meter!r} meter, which "
                "this task goes by."
            )
        if not (
            _is_number(last_done) and 0.0 <= float(last_done) < math.inf
        ):
            raise ValueError(
                "last_done must be the meter reading at the task's last "
                f"time, a number at least 0; got {last_done!r}."
            )
        reading = asset.meters[every.meter]
        if float(last_done) > reading:
            raise ValueError(
                f"last_done ({float(last_done):g}) is past the asset's "
                f"{every.meter} reading ({reading:g})."
            )
        if reading >= float(last_done) + every.amount:
            raise ValueError(
                f"The task is due already: the asset's {every.meter} reading "
                f"({reading:g}) has reached last_done plus every "
                f"({float(last_done) + every.amount:g})."
            )
        object.__setattr__(self, "asset", asset)
        object.__setattr__(self, "last_done", float(last_done))

    def due(self, start, end) -> Union["TaskDates", UsageDue]:
        """When the task falls due from ``start`` to ``end``, both days
        included.

        Parameters
        ----------
        start, end : datetime.date or str
            The first and last days of the period, as dates or as text
            such as ``"2026-12-31"``. For a task by use, the period may not
            start before the day its asset's meters were read.

        Returns
        -------
        TaskDates or UsageDue
            A task on the calendar: its dates in the period
            (``TaskDates``); a task by use: the
            readings and times it falls due
            (``UsageDue``); with how many there are,
            and what they cost.
        """
        start, end = _date(start, "start"), _date(end, "end")
        if end < start:
            raise ValueError(
                f"The period ends ({end}) before it starts ({start})."
            )
        if self.asset is not None:
            return self._due_by_use(start, end)
        times = self._rule(start).between(
            _midnight(start), _midnight(end), inc=True
        )
        dates = tuple(time.date() for time in times)
        cost = None if self.cost is None else len(dates) * self.cost
        return TaskDates(self.name, start, end, dates, len(dates), cost)

    def _due_by_use(self, start: date, end: date) -> UsageDue:
        """When a task by use falls due from ``start`` to ``end``."""
        asset, every = self.asset, self.every
        assert asset is not None and isinstance(every, (Hours, Starts))
        assert self.last_done is not None
        if start < asset.read_at.date():
            raise ValueError(
                f"The period starts ({start}) before the meters of asset "
                f"{asset.name!r} were read ({asset.read_at})."
            )
        begins = max(_moment(start, "start"), asset.read_at)
        ends = _moment(end + timedelta(days=1), "end")
        readings, times = crossings(asset, every, self.last_done, begins, ends)
        cost = None if self.cost is None else len(times) * self.cost
        return UsageDue(
            self.name,
            start,
            end,
            every.meter,
            readings,
            times,
            len(times),
            cost,
        )

    def _rule(self, start: date) -> rrule:
        """The task's dates as a dateutil rule: a rule's from the date it
        applies from (or the period's ``start``), an interval's from its
        first date."""
        if self.on is not None:
            applies = start if self.starting is None else self.starting
            return self.on._rule(applies)
        assert self.first is not None and isinstance(self.every, timedelta)
        return rrule(
            DAILY, dtstart=_midnight(self.first), interval=self.every.days
        )


@dataclass
class TaskDates(_Result):
    """The dates a ``Task`` falls due in a period:
    returned by its ``due``.

    Attributes
    ----------
    task : str
        The task's name.
    start, end : datetime.date
        The period's first and last days, both included.
    dates : tuple of datetime.date
        The dates the task falls due in the period, in order.
    count : int
        How many there are.
    cost : float or None
        What they cost: the task's cost each time, times ``count``; None
        if the task was given no cost.
    """

    task: str
    start: date
    end: date
    dates: Tuple[date, ...]
    count: int
    cost: Optional[float]
