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
readings.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta, timezone

MAX_BATCH = 10_000


def parse_time(value) -> datetime:
    """An ISO time, or seconds since 1970; now when not given. Always UTC."""
    if value in (None, ""):
        return datetime.now(timezone.utc)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), timezone.utc)
    text = str(value).strip().replace("Z", "+00:00")
    try:
        t = datetime.fromisoformat(text)
    except ValueError:
        try:
            return datetime.fromtimestamp(float(text), timezone.utc)
        except ValueError:
            raise ValueError(f"'{value}' isn't a time (ISO 8601, or seconds since 1970).") from None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


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
        return row and {"t": row[0], "value": row[1]}

    def daily(self, org: str, point: str, days: int = 400) -> list[dict]:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        with self._lock:
            rows = self._conn.execute(
                "SELECT substr(t, 1, 10) AS d, v FROM series WHERE org = ? AND point = ? AND t >= ? ORDER BY t",
                (org, point, since)).fetchall()
        last: dict[str, float] = {}
        for d, v in rows:
            last[d] = v
        return [{"on": d, "value": v} for d, v in last.items()]

    def recent(self, org: str, point: str, n: int = 50) -> list[dict]:
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
        return doc and {"t": _iso(doc["t"]), "value": doc["v"]}

    def daily(self, org: str, point: str, days: int = 400) -> list[dict]:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        last: dict[str, float] = {}
        for doc in self._c.find({"m.org": org, "m.point": point, "t": {"$gte": since}}).sort("t", 1):
            last[_iso(doc["t"])[:10]] = doc["v"]
        return [{"on": d, "value": v} for d, v in last.items()]

    def recent(self, org: str, point: str, n: int = 50) -> list[dict]:
        return [{"t": _iso(d["t"]), "value": d["v"]}
                for d in self._c.find({"m.org": org, "m.point": point}).sort("t", -1).limit(n)]


def _iso(t: datetime) -> str:
    return (t if t.tzinfo else t.replace(tzinfo=timezone.utc)).isoformat()
