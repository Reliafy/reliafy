"""Automated readings: the time-series store.

A sensor feed (a PLC's run-hours tag, Home Assistant pushing a temperature)
can send a reading a minute: far too many for the event log, which holds the
moments that matter (an alarm crossed, a work order raised). Feeds land here,
keyed by organisation and measurement point; the graph holds only the point,
with its source and tag.

* :class:`MongoSeries` — a MongoDB time-series collection (a deployment).
* :class:`SqliteSeries` — a table beside the graph (a local install).

Both answer the same questions: append readings, the latest one, the last
reading of each day (what the due-date and trend maths use), and recent raw
readings. Times are stored as they come (UTC); only the day a reading falls on
follows the workspace's time zone.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta, timezone, tzinfo

from backend.maintenance.read_cache import note_series_read, series_recording
from backend.services.time_zones import day_of

MAX_BATCH = 10_000


EARLIEST = datetime(2000, 1, 1, tzinfo=timezone.utc)
AHEAD = timedelta(days=1)  # a feed's clock may run a little ahead


def _from_epoch(seconds: float, value) -> datetime:
    try:
        return datetime.fromtimestamp(float(seconds), timezone.utc)
    except (OverflowError, OSError, ValueError):
        raise ValueError(f"'{str(value)[:40]}' isn't a time (ISO 8601, or seconds since 1970).") from None


def parse_time(value) -> datetime:
    """An ISO time, or seconds since 1970; now when not given. Always UTC, and
    between 2000-01-01 and a day from now."""
    if value in (None, ""):
        return datetime.now(timezone.utc)
    if isinstance(value, bool):
        raise ValueError(f"'{value}' isn't a time (ISO 8601, or seconds since 1970).")
    if isinstance(value, (int, float)):
        t = _from_epoch(value, value)
    else:
        text = str(value).strip().replace("Z", "+00:00")
        try:
            t = datetime.fromisoformat(text)
        except ValueError:
            t = _from_epoch(text, value)
        t = t if t.tzinfo else t.replace(tzinfo=timezone.utc)
    if not EARLIEST <= t <= datetime.now(timezone.utc) + AHEAD:
        raise ValueError(f"'{str(value)[:40]}' is outside the times accepted (2000-01-01 to a day from now).")
    return t


class SqliteSeries:
    def __init__(self, conn: sqlite3.Connection, lock=None):
        self._conn = conn
        self._lock = lock or threading.RLock()
        conn.executescript(
            "CREATE TABLE IF NOT EXISTS series (org TEXT NOT NULL, point TEXT NOT NULL, t TEXT NOT NULL, v REAL NOT NULL);"
            "CREATE INDEX IF NOT EXISTS series_point ON series (org, point, t);"
        )

    def append(self, org: str, point: str, rows: list[tuple[datetime, float]]) -> int:
        with self._lock:
            self._conn.executemany("INSERT INTO series (org, point, t, v) VALUES (?, ?, ?, ?)",
                                   [(org, point, t.astimezone(timezone.utc).isoformat(), float(v)) for t, v in rows])
        return len(rows)

    def latest(self, org: str, point: str) -> dict | None:
        with self._lock:
            row = self._conn.execute("SELECT t, v FROM series WHERE org = ? AND point = ? ORDER BY t DESC LIMIT 1",
                                     (org, point)).fetchone()
        out = row and {"t": row[0], "value": row[1]}
        note_series_read(("latest", org, point, None), out)
        return out

    def fingerprint(self, org: str, point: str, days: int | None = None) -> tuple:
        """(how many readings, the newest's time), over the last ``days`` or all: what a
        read of a point's history depends on (read_cache.py; readings are only ever added)."""
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat() if days is not None else ""
        with self._lock:
            row = self._conn.execute("SELECT count(*), max(t) FROM series WHERE org = ? AND point = ? AND t >= ?",
                                     (org, point, since)).fetchone()
        return tuple(row)

    def daily(self, org: str, point: str, days: int = 400, tz: tzinfo | None = None) -> list[dict]:
        """The last reading of each day, the days as they fall in ``tz`` (the
        workspace's zone; the server's when None)."""
        if series_recording():
            note_series_read(("fingerprint", org, point, days), self.fingerprint(org, point, days))
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        with self._lock:
            rows = self._conn.execute(
                "SELECT t, v FROM series WHERE org = ? AND point = ? AND t >= ? ORDER BY t",
                (org, point, since)).fetchall()
        last: dict[str, float] = {}
        for t, v in rows:
            last[day_of(datetime.fromisoformat(t), tz)] = v
        return [{"on": d, "value": v} for d, v in last.items()]

    def recent(self, org: str, point: str, n: int = 50) -> list[dict]:
        if series_recording():
            note_series_read(("fingerprint", org, point, None), self.fingerprint(org, point))
        with self._lock:
            rows = self._conn.execute("SELECT t, v FROM series WHERE org = ? AND point = ? ORDER BY t DESC LIMIT ?",
                                      (org, point, n)).fetchall()
        return [{"t": t, "value": v} for t, v in rows]


class MongoSeries:
    def __init__(self, db, collection: str = "maintenance_series"):
        if collection not in db.list_collection_names():
            try:
                db.create_collection(collection, timeseries={"timeField": "t", "metaField": "m",
                                                             "granularity": "minutes"})
            except Exception:  # noqa: BLE001 - an older server or the simulator: a plain collection does
                pass
        self._c = db[collection]
        try:
            self._c.create_index([("m.org", 1), ("m.point", 1), ("t", -1)])
        except Exception:  # noqa: BLE001
            pass

    def append(self, org: str, point: str, rows: list[tuple[datetime, float]]) -> int:
        if rows:
            self._c.insert_many([{"t": t, "m": {"org": org, "point": point}, "v": float(v)} for t, v in rows])
        return len(rows)

    def latest(self, org: str, point: str) -> dict | None:
        doc = next(iter(self._c.find({"m.org": org, "m.point": point}).sort("t", -1).limit(1)), None)
        out = doc and {"t": _iso(doc["t"]), "value": doc["v"]}
        note_series_read(("latest", org, point, None), out)
        return out

    def fingerprint(self, org: str, point: str, days: int | None = None) -> tuple:
        """(how many readings, the newest's time), over the last ``days`` or all (as SqliteSeries)."""
        query: dict = {"m.org": org, "m.point": point}
        if days is not None:
            query["t"] = {"$gte": datetime.now(timezone.utc) - timedelta(days=days)}
        newest = next(iter(self._c.find(query, {"t": 1}).sort("t", -1).limit(1)), None)
        return self._c.count_documents(query), newest and _iso(newest["t"])

    def daily(self, org: str, point: str, days: int = 400, tz: tzinfo | None = None) -> list[dict]:
        if series_recording():
            note_series_read(("fingerprint", org, point, days), self.fingerprint(org, point, days))
        since = datetime.now(timezone.utc) - timedelta(days=days)
        last: dict[str, float] = {}
        for doc in self._c.find({"m.org": org, "m.point": point, "t": {"$gte": since}}).sort("t", 1):
            last[day_of(doc["t"], tz)] = doc["v"]
        return [{"on": d, "value": v} for d, v in last.items()]

    def recent(self, org: str, point: str, n: int = 50) -> list[dict]:
        if series_recording():
            note_series_read(("fingerprint", org, point, None), self.fingerprint(org, point))
        return [{"t": _iso(d["t"]), "value": d["v"]}
                for d in self._c.find({"m.org": org, "m.point": point}).sort("t", -1).limit(n)]


def _iso(t: datetime) -> str:
    return (t if t.tzinfo else t.replace(tzinfo=timezone.utc)).isoformat()
