"""Signal channels: a sensor that sends snapshots rather than single numbers.

A channel sits on a position or an item (a vibration sensor on a pump, a
pressure transducer on its discharge). It takes *snapshots*: a burst of raw
samples per axis (sample rate, units), a spectrum the device already computed,
or just a scalar value (a slow pressure). On arrival the server works out the
spectrum once (Hann window, single-sided peak amplitude, in the input units)
and the overall levels (RMS, peak, crest factor, kurtosis per axis) and keeps
them with the samples.

A *watch band* (a frequency range) or an *overall level* is a derived point
(derived.py): each snapshot adds one value to an ordinary measurement point, so
alarms, trends and condition monitoring work on it unchanged.

Storage is the snapshot store (Mongo in a deployment, SQLite locally), behind
the small interface below so another store can replace it. Everything is kept:
see ``apply_retention``.

Definitions worth knowing:

* Spectrum amplitude is the *peak* amplitude of a sine at that frequency, in the
  signal's unit (a 0.5 g tone at 50 Hz reads 0.5 g at 50 Hz).
* A band level is the RMS of the signal inside the band: the square root of
  the sum of ``A**2 / 2`` over the bins in the band, divided by the window's
  equivalent noise bandwidth in bins (1.5 for Hann), which makes a tone read
  ``A / sqrt(2)`` wherever it falls between bins.
* Overall RMS and peak ignore the signal's mean (a sensor's offset or gravity);
  kurtosis is the plain fourth-moment ratio (3 for noise from a normal
  distribution).
"""

from __future__ import annotations

import base64
import json
import math
import sqlite3
import threading
import zlib
from datetime import datetime, timezone

import numpy as np

from backend.maintenance import derived
from backend.maintenance.series import parse_time

MAX_SNAPSHOT_BYTES = 5_000_000  # a request body
MAX_VALUES = 500_000  # numbers in one snapshot, all axes (about 5 MB as JSON text)
MAX_AXES = 6
MAX_CHANNELS = 200
MAX_BANDS_PER_CHANNEL = 40
MAX_SNAPSHOTS_PER_DAY = 5000  # per workspace, counted at the server's day
MIN_SAMPLES = 16
UNIT_MAX = 20
SPEED_UNITS = ("rpm", "r/min", "1/min")

#: Equivalent noise bandwidth of a window, in bins.
ENBW = {"hann": 1.5, "hamming": 1.3628, "blackman": 1.7268, "rectangular": 1.0, "flattop": 3.7702}
SETTINGS_ID = "signal-settings"
SPEED_WINDOW_MS = 3_600_000  # a speed reading counts if it is within an hour of the snapshot
STATS = ("rms", "peak", "crest", "kurtosis", "mean", "value")


def apply_retention(store, org: str, channel_id: str) -> None:
    """TODO: retention. For now every snapshot is kept, raw and spectrum, whatever
    its age: how much that really costs is being measured first (see the channel's
    ``snapshots.bytes``). Thinning, if it comes, goes here and is called after each
    snapshot is stored. It deletes nothing today."""
    return None


# ---- the maths -----------------------------------------------------------------------------


def spectrum_of(x: np.ndarray, fs: float) -> tuple[float, np.ndarray]:
    """``(df, amplitudes)``: the single-sided peak-amplitude spectrum of ``x`` (mean
    removed, Hann window, ``2|X| / sum(w)``) at 0, df, 2 df ... Nyquist."""
    n = len(x)
    x = np.asarray(x, dtype=float)
    w = np.hanning(n + 1)[:-1]  # the periodic Hann window
    spec = np.abs(np.fft.rfft((x - x.mean()) * w)) / w.sum()
    amp = 2.0 * spec
    amp[0] = spec[0]
    if n % 2 == 0:
        amp[-1] = spec[-1]  # Nyquist is not mirrored
    return fs / n, amp


def levels_of(x: np.ndarray) -> dict:
    """Overall levels of a waveform (the mean removed)."""
    x = np.asarray(x, dtype=float)
    mean = float(x.mean())
    ac = x - mean
    rms = float(math.sqrt(float(np.mean(ac * ac))))
    peak = float(np.max(np.abs(ac)))
    var = float(np.mean(ac * ac))
    kurt = float(np.mean(ac ** 4) / (var * var)) if var > 0 else None
    return {"mean": mean, "rms": rms, "peak": peak, "crest": peak / rms if rms > 0 else None, "kurtosis": kurt}


def band_rms(f0: float, df: float, amp: np.ndarray, low: float, high: float, enbw: float = 1.5,
             freqs: np.ndarray | None = None) -> float | None:
    """RMS inside ``low``..``high`` Hz (inclusive), or None when no bin falls in it."""
    f = freqs if freqs is not None else f0 + df * np.arange(len(amp))
    pick = (f >= low) & (f <= high) & (f > 0)
    if not pick.any():
        return None
    return float(math.sqrt(float(np.sum(amp[pick] ** 2)) / 2.0 / enbw))


def _sig(values, digits: int = 6) -> list:
    return [float(f"{v:.{digits}g}") for v in np.asarray(values, dtype=float).tolist()]


def pack(a) -> bytes:
    return zlib.compress(np.asarray(a, dtype="<f4").tobytes(), 6)


def unpack(b: bytes) -> np.ndarray:
    return np.frombuffer(zlib.decompress(b), dtype="<f4").astype(float)


def pack64(a) -> bytes:
    return zlib.compress(np.asarray(a, dtype="<f8").tobytes(), 6)


def unpack64(b: bytes) -> np.ndarray:
    return np.frombuffer(zlib.decompress(b), dtype="<f8").copy()


def _size(doc: dict) -> int:
    total = 0
    for k in _BLOBS:
        v = doc.get(k)
        if isinstance(v, dict):
            total += sum(len(b) for b in v.values())
        elif v:
            total += len(v)
    return total


# ---- the snapshot store --------------------------------------------------------------------

_BLOBS = ("spectrum", "raw", "freqs")


def _encode(doc: dict) -> str:
    def conv(v):
        if isinstance(v, bytes):
            return {"$b": base64.b64encode(v).decode("ascii")}
        if isinstance(v, dict):
            return {k: conv(x) for k, x in v.items()}
        return v
    return json.dumps(conv(doc))


def _decode(text: str) -> dict:
    def conv(v):
        if isinstance(v, dict):
            if set(v) == {"$b"}:
                return base64.b64decode(v["$b"])
            return {k: conv(x) for k, x in v.items()}
        return v
    return conv(json.loads(text))


def _head(doc: dict) -> dict:
    return {k: v for k, v in doc.items() if k not in _BLOBS}


class SqliteSnapshots:
    """Snapshots in a table beside the graph (a local install, and tests)."""

    def __init__(self, conn: sqlite3.Connection, lock=None):
        self._conn = conn
        self._lock = lock or threading.RLock()
        conn.executescript(
            "CREATE TABLE IF NOT EXISTS snapshots (org TEXT NOT NULL, channel TEXT NOT NULL, t_ms INTEGER NOT NULL,"
            " head TEXT NOT NULL, body TEXT NOT NULL, PRIMARY KEY (org, channel, t_ms));")

    def put(self, org: str, channel: str, t_ms: int, doc: dict) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO snapshots (org, channel, t_ms, head, body) VALUES (?, ?, ?, ?, ?)",
                (org, channel, t_ms, json.dumps(_head(doc)), _encode({k: doc[k] for k in _BLOBS if k in doc})))
        return cur.rowcount == 1

    def exists(self, org: str, channel: str, t_ms: int) -> bool:
        with self._lock:
            return bool(self._conn.execute("SELECT 1 FROM snapshots WHERE org = ? AND channel = ? AND t_ms = ?",
                                           (org, channel, t_ms)).fetchall())

    def get(self, org: str, channel: str, t_ms: int) -> dict | None:
        with self._lock:
            row = self._conn.execute("SELECT head, body FROM snapshots WHERE org = ? AND channel = ? AND t_ms = ?",
                                     (org, channel, t_ms)).fetchone()
        return row and {**json.loads(row[0]), **_decode(row[1])}

    def heads(self, org: str, channel: str, since_ms=None, until_ms=None, limit=None) -> list[dict]:
        """Snapshot headings (no samples or spectrum), oldest first; with a limit, the newest ``limit``."""
        sql = "SELECT head FROM snapshots WHERE org = ? AND channel = ?"
        args: list = [org, channel]
        if since_ms is not None:
            sql, args = sql + " AND t_ms >= ?", args + [since_ms]
        if until_ms is not None:
            sql, args = sql + " AND t_ms <= ?", args + [until_ms]
        sql += " ORDER BY t_ms DESC" + (" LIMIT ?" if limit else "")
        with self._lock:
            rows = self._conn.execute(sql, args + ([limit] if limit else [])).fetchall()
        return [json.loads(r[0]) for r in reversed(rows)]

    def iterate(self, org: str, channel: str):
        with self._lock:
            keys = [r[0] for r in self._conn.execute(
                "SELECT t_ms FROM snapshots WHERE org = ? AND channel = ? ORDER BY t_ms", (org, channel))]
        for t_ms in keys:
            doc = self.get(org, channel, t_ms)
            if doc:
                yield doc

    def stats(self, org: str, channel: str) -> dict:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*), MIN(t_ms), MAX(t_ms) FROM snapshots WHERE org = ? AND channel = ?",
                (org, channel)).fetchone()
        count = row[0] or 0
        size = sum(h.get("size", 0) for h in self.heads(org, channel)) if count else 0
        return {"count": count, "first_ms": row[1], "last_ms": row[2], "bytes": size}


class MongoSnapshots:
    """Snapshots in a MongoDB collection (a deployment)."""

    def __init__(self, db, collection: str = "maintenance_snapshots"):
        self._c = db[collection]
        try:
            self._c.create_index([("org", 1), ("channel", 1), ("t_ms", 1)], unique=True)
        except Exception:  # noqa: BLE001 - the simulator may not
            pass

    def put(self, org: str, channel: str, t_ms: int, doc: dict) -> bool:
        from pymongo.errors import DuplicateKeyError

        try:
            self._c.insert_one({**doc, "org": org, "channel": channel, "t_ms": t_ms})
        except DuplicateKeyError:
            return False
        return True

    def exists(self, org: str, channel: str, t_ms: int) -> bool:
        return self._c.count_documents({"org": org, "channel": channel, "t_ms": t_ms}, limit=1) > 0

    def get(self, org: str, channel: str, t_ms: int) -> dict | None:
        doc = self._c.find_one({"org": org, "channel": channel, "t_ms": t_ms})
        return doc and {k: v for k, v in doc.items() if k not in ("_id", "org", "channel")}

    def heads(self, org: str, channel: str, since_ms=None, until_ms=None, limit=None) -> list[dict]:
        query: dict = {"org": org, "channel": channel}
        if since_ms is not None or until_ms is not None:
            query["t_ms"] = {**({"$gte": since_ms} if since_ms is not None else {}),
                             **({"$lte": until_ms} if until_ms is not None else {})}
        cursor = self._c.find(query, {"_id": 0, "org": 0, "channel": 0, **{k: 0 for k in _BLOBS}}).sort("t_ms", -1)
        if limit:
            cursor = cursor.limit(int(limit))
        return list(reversed(list(cursor)))

    def iterate(self, org: str, channel: str):
        for doc in self._c.find({"org": org, "channel": channel}, {"_id": 1}).sort("t_ms", 1):
            full = self._c.find_one({"_id": doc["_id"]})
            yield {k: v for k, v in full.items() if k not in ("_id", "org", "channel")}

    def stats(self, org: str, channel: str) -> dict:
        heads = self.heads(org, channel)
        return {"count": len(heads), "first_ms": heads[0]["t_ms"] if heads else None,
                "last_ms": heads[-1]["t_ms"] if heads else None, "bytes": sum(h.get("size", 0) for h in heads)}


# ---- projectors (the events) ---------------------------------------------------------------


def _channel_added(s, org: str, p: dict) -> None:
    from backend.maintenance.service import _subject_id

    s.put_node(org, p["id"], "SignalChannel", {
        "name": p["name"], "quantity": p.get("quantity", ""), "unit": p.get("unit", ""),
        "sample_rate": p.get("sample_rate"), "axes": p.get("axes") or [], "rpm": p.get("rpm"),
        "tag": p.get("tag", ""), "mount": p.get("mount", ""), "created": p["on"]})
    s.put_edge(org, "ON", p["id"], _subject_id(p))


def _channel_updated(s, org: str, p: dict) -> None:
    s.patch_node(org, p["id"], p["changes"])


def _channel_retired(s, org: str, p: dict) -> None:
    s.patch_node(org, p["id"], {"retired": True, "retired_on": p.get("on"), "retired_reason": p.get("reason", "")})


def _channel_restored(s, org: str, p: dict) -> None:
    s.patch_node(org, p["id"], {"retired": False, "retired_on": None, "retired_reason": "", "restored_on": p.get("on")})


def _band_limits(s, org: str, p: dict) -> None:
    """signal_band.limits: the warning levels of a band or level (shown as lines; they
    open no work: the alarm limits are the point's own)."""
    s.patch_node(org, p["id"], {"warn_above": p.get("warn_above"), "warn_below": p.get("warn_below")})


def _settings_set(s, org: str, p: dict) -> None:
    """signal_settings.set: workspace-wide choices for signal storage (one node, replaced each time)."""
    s.put_node(org, SETTINGS_ID, "SignalSettings", {"storage_cap_mb": p.get("storage_cap_mb")})


PROJECTORS = {
    "signal_band.limits": _band_limits, "signal_settings.set": _settings_set,
    "signal_channel.added": _channel_added, "signal_channel.updated": _channel_updated,
    "signal_channel.retired": _channel_retired, "signal_channel.restored": _channel_restored,
    **derived.PROJECTORS,
}


# ---- the derived rules ---------------------------------------------------------------------


def _record_levels(doc: dict) -> dict:
    return doc.get("levels") or {}


class _Rule:
    source_label = "SignalChannel"

    def records(self, m, source):
        for doc in m.s.snapshots.iterate(m.org, source["id"]):
            yield datetime.fromtimestamp(doc["t_ms"] / 1000, timezone.utc), doc

    def _check_axis(self, m, source, spec):
        sv = _sv()
        axis = spec.get("axis")
        known = list(source.get("axes") or [])
        if not known:
            latest = m.s.snapshots.heads(m.org, source["id"], limit=1)
            known = list(latest[0]["axes"]) if latest else []
        if axis in (None, ""):
            if len(known) == 1:
                axis = known[0]
            elif not known:
                axis = "value"  # a single-axis channel's unnamed axis
            else:
                raise sv.Invalid(f"Say which axis (axis): one of {', '.join(known)}.")
        elif known and axis not in known:
            raise sv.Invalid(f"The channel has no axis {axis}: its axes are {', '.join(known)}.")
        return str(axis)


class BandRule(_Rule):
    """RMS level inside a frequency range (Hz, or multiples of the running speed)."""

    def validate(self, m, source, spec):
        sv = _sv()
        low = sv._number(spec.get("low"), "low", 0, 1e7)
        high = sv._number(spec.get("high"), "high", 0, 1e7)
        if high <= low:
            raise sv.Invalid("The band's top (high) must be above its bottom (low).")
        unit = spec.get("in") or "Hz"
        if unit not in ("Hz", "orders"):
            raise sv.Invalid("in is Hz or orders (multiples of the running speed).")
        return {"type": "band", "axis": self._check_axis(m, source, spec), "low": low, "high": high, "in": unit,
                "measure": "rms"}

    def unit(self, source, spec):
        return source.get("unit", "")

    def describe(self, spec):
        u = "Hz" if spec["in"] == "Hz" else "x running speed"
        return f"RMS {spec['low']:g} to {spec['high']:g} {u}, axis {spec['axis']}"

    def compute(self, spec, doc):
        spectrum = (doc.get("spectrum") or {}).get(spec["axis"])
        if spectrum is None:
            return None
        low, high = spec["low"], spec["high"]
        if spec["in"] == "orders":
            if not doc.get("rpm"):
                return None
            hz = doc["rpm"] / 60.0
            low, high = low * hz, high * hz
        freqs = unpack64(doc["freqs"]) if doc.get("freqs") else None
        return band_rms(doc.get("f0", 0.0), doc["df"], unpack(spectrum), low, high, doc.get("enbw", 1.0), freqs)


class LevelRule(_Rule):
    """An overall level of the snapshot: rms, peak, crest, kurtosis, mean or a scalar value."""

    def validate(self, m, source, spec):
        sv = _sv()
        stat = spec.get("stat")
        if stat not in STATS:
            raise sv.Invalid(f"stat is one of {', '.join(STATS)}.")
        return {"type": "level", "axis": self._check_axis(m, source, spec), "stat": stat}

    def unit(self, source, spec):
        return "" if spec["stat"] in ("crest", "kurtosis") else source.get("unit", "")

    def describe(self, spec):
        return f"{spec['stat']} of axis {spec['axis']}"

    def compute(self, spec, doc):
        value = (_record_levels(doc).get(spec["axis"]) or {}).get(spec["stat"])
        return None if value is None else float(value)


derived.register("band", BandRule())
derived.register("level", LevelRule())


def _sv():
    from backend.maintenance import service

    return service


# ---- the operations (a mixin of Maintenance) -----------------------------------------------


def snapshot_id(channel_id: str, t_ms: int) -> str:
    return f"{channel_id}:{t_ms}"


def split_snapshot_id(value: str) -> tuple[str, int]:
    sv = _sv()
    channel, _, t = str(value or "").rpartition(":")
    if not channel or not t.lstrip("-").isdigit():
        raise sv.Invalid("A snapshot id looks like <channel id>:<milliseconds>; take it from the channel's snapshots.")
    return channel, int(t)


def _iso(t_ms: int) -> str:
    return datetime.fromtimestamp(t_ms / 1000, timezone.utc).isoformat().replace("+00:00", "Z")


class SignalOps:
    """Methods added to ``Maintenance``."""

    # -- channels

    def add_signal_channel(self, position_id, item_id, name, unit, quantity="", sample_rate=None, axes=None,
                           rpm=None, tag="", mount="") -> dict:
        """A signal channel on a position or an item: a sensor that sends snapshots (a burst
        of samples, a device's spectrum or a scalar). ``axes`` names its axes (a triaxial
        accelerometer: X, Y, Z); ``rpm`` is the running speed, for bands in multiples of it."""
        sv = _sv()
        _, on = self._subject_ref("signal channel", position_id, item_id, live_position=False)
        name = sv._text(name, "channel's name", required=True)
        unit = sv._text(unit, "unit", required=True)[:UNIT_MAX]
        tag = sv._text(tag, "tag")[:sv.SHORT_TEXT]
        if tag and any(c.get("tag") == tag and not c.get("retired") for c in self.s.nodes(self.org, "SignalChannel")):
            raise sv.Invalid(f"Tag {tag} is already used by another channel.")
        axes = [sv._text(a, "axis name", required=True)[:40] for a in (axes or [])]
        if len(set(axes)) != len(axes) or len(axes) > MAX_AXES:
            raise sv.Invalid(f"Axis names must be different, and at most {MAX_AXES}.")
        rate = None if sample_rate in (None, "") else sv._number(sample_rate, "sample rate", 0.001, 1e7)
        speed = None if rpm in (None, "") else sv._number(rpm, "rpm", 0.001, 1e6)
        self._quota("SignalChannel", MAX_CHANNELS, what="signal channels")
        cid = sv.new_id()
        self._emit("signal_channel.added", {
            "id": cid, **on, "name": name, "unit": unit, "quantity": sv._text(quantity, "quantity")[:40],
            "sample_rate": rate, "axes": axes, "rpm": speed, "tag": tag,
            "mount": sv._text(mount, "mount")[:sv.SHORT_TEXT], "on": self.today()})
        return self.signal_channel(cid)

    def update_signal_channel(self, channel_id, name=None, rpm=..., tag=None, mount=None, sample_rate=...,
                              speed_channel_id=...) -> dict:
        """Rename a channel, change its running speed (new snapshots take it; stored ones keep theirs),
        tag, mount text or nominal sample rate. ``speed_channel_id`` names a channel of single rpm
        readings to take the running speed from (the nearest reading in time); '' clears it."""
        sv = _sv()
        ch = self._live_channel(channel_id)
        changes: dict = {}
        if speed_channel_id is not ...:
            if speed_channel_id in (None, ""):
                changes["speed_channel_id"] = None
            else:
                src = self._live_channel(speed_channel_id)
                if src["id"] == ch["id"]:
                    raise sv.Invalid("A channel can't take its own speed from itself.")
                if str(src.get("unit", "")).strip().lower() not in SPEED_UNITS:
                    raise sv.Invalid(f"{src['name']} is in {src.get('unit') or 'no unit'}; a speed channel must be in rpm.")
                changes["speed_channel_id"] = src["id"]
        if name is not None:
            changes["name"] = sv._text(name, "channel's name", required=True)
        if rpm is not ...:
            changes["rpm"] = None if rpm in (None, "") else sv._number(rpm, "rpm", 0.001, 1e6)
        if sample_rate is not ...:
            changes["sample_rate"] = None if sample_rate in (None, "") else sv._number(sample_rate, "sample rate", 0.001, 1e7)
        if mount is not None:
            changes["mount"] = sv._text(mount, "mount")[:sv.SHORT_TEXT]
        if tag is not None:
            tag = sv._text(tag, "tag")[:sv.SHORT_TEXT]
            if tag and any(c.get("tag") == tag and c["id"] != channel_id and not c.get("retired")
                           for c in self.s.nodes(self.org, "SignalChannel")):
                raise sv.Invalid(f"Tag {tag} is already used by another channel.")
            changes["tag"] = tag
        if changes:
            self._emit("signal_channel.updated", {"id": ch["id"], "changes": changes})
        return self.signal_channel(channel_id)

    def retire_signal_channel(self, channel_id, reason="") -> dict:
        """Stop a channel taking snapshots (what it holds stays; so do its bands' series)."""
        sv = _sv()
        ch = self._live_channel(channel_id)
        self._emit("signal_channel.retired", {"id": ch["id"], "on": self.today(), "reason": sv._text(reason, "reason")})
        return {"retired": channel_id}

    def restore_signal_channel(self, channel_id) -> dict:
        sv = _sv()
        ch = self._get(str(channel_id or ""), "SignalChannel")
        tag = ch.get("tag")
        if tag and any(c.get("tag") == tag and c["id"] != channel_id and not c.get("retired")
                       for c in self.s.nodes(self.org, "SignalChannel")):
            raise sv.Invalid(f"Tag {tag} is used by another channel now: change that channel's tag first.")
        self._emit("signal_channel.restored", {"id": ch["id"], "on": self.today()})
        return self.signal_channel(channel_id)

    def _live_channel(self, channel_id) -> dict:
        sv = _sv()
        ch = self._get(str(channel_id or ""), "SignalChannel")
        if ch.get("retired"):
            raise sv.Invalid(f"{ch['name']} has been retired: restore it first.")
        return ch

    def _channel_by(self, channel_id, tag) -> dict:
        sv = _sv()
        if channel_id:
            return self._live_channel(channel_id)
        if tag:
            found = [c for c in self.s.nodes(self.org, "SignalChannel") if c.get("tag") == tag and not c.get("retired")]
            if found:
                return found[0]
            raise sv.Invalid(f"No channel has the tag {tag}.")
        raise sv.Invalid("Say which channel: channel_id or its tag.")

    def _channel_band(self, point: dict, channel_id: str) -> dict:
        rule = point["derived"]["rule"]
        latest = self.s.series.latest(self.org, point["id"])
        above, below = point.get("alarm_above"), point.get("alarm_below")
        value = latest and latest["value"]
        status = "ok" if value is None else "high" if above is not None and value >= above else \
            "low" if below is not None and value <= below else "ok"
        return {"point_id": point["id"], "name": point["name"], "rule": rule,
                "describe": derived.RULES[rule["type"]].describe(rule), "unit": point.get("unit", ""),
                "alarm_above": above, "alarm_below": below, "warn_above": point.get("warn_above"),
                "warn_below": point.get("warn_below"), "latest": latest and {"t": latest["t"], "value": value},
                "status": status, "retired": bool(point.get("retired"))}

    def signal_channels(self, position_id=None, item_id=None, include_retired=False) -> dict:
        """Channels (on one position or item, or all), each with its snapshot count."""
        out = []
        for ch in self.s.nodes(self.org, "SignalChannel"):
            if ch.get("retired") and not include_retired:
                continue
            on = self.s.out(self.org, ch["id"], "ON")
            if (position_id and (not on or on[0]["id"] != position_id)) or \
                    (item_id and (not on or on[0]["id"] != item_id)):
                continue
            stats = self.s.snapshots.stats(self.org, ch["id"])
            out.append(self._channel_head(ch, on) | {"snapshots": self._stats_view(stats)})
        return {"channels": sorted(out, key=lambda c: c["name"].lower())}

    @staticmethod
    def _stats_view(stats: dict) -> dict:
        return {"count": stats["count"], "bytes": stats["bytes"],
                "first": stats["first_ms"] and _iso(stats["first_ms"]),
                "last": stats["last_ms"] and _iso(stats["last_ms"])}

    def _channel_head(self, ch: dict, on: list) -> dict:
        target = on[0] if on else None
        item = None
        if target and target["label"] == "Item":
            # Where the item is fitted now (None: loose): the Explorer shows a fitted
            # item's channels on that position's Signals tab.
            fitment = self._current_fitment_of_item(target["id"])
            at = fitment and self.s.out(self.org, fitment["id"], "AT")
            item = {"id": target["id"], "name": target["name"],
                    "fitted_to": at and {"id": at[0]["id"], "name": at[0]["name"]} or None}
        return {"id": ch["id"], "name": ch["name"], "quantity": ch.get("quantity", ""), "unit": ch.get("unit", ""),
                "sample_rate": ch.get("sample_rate"), "axes": ch.get("axes") or [], "rpm": ch.get("rpm"),
                "tag": ch.get("tag", ""), "mount": ch.get("mount", ""), "retired": bool(ch.get("retired")),
                "speed_channel_id": ch.get("speed_channel_id") or None,
                "position": target and target["label"] == "Position" and {"id": target["id"], "name": target["name"]} or None,
                "item": item}

    def signal_channel(self, channel_id, snapshots=300, series=1000) -> dict:
        """One channel: its settings, watch bands (with their series), a size count and its
        most recent ``snapshots`` headings (time, running flag, rpm and levels per axis)."""
        ch = self._get(str(channel_id or ""), "SignalChannel")
        on = self.s.out(self.org, ch["id"], "ON")
        stats = self.s.snapshots.stats(self.org, ch["id"])
        bands = []
        for p in derived.points_of(self, ch["id"], live_only=False):
            if p.get("superseded_by"):
                continue  # an older version: shown as part of the band that replaced it
            band = self._channel_band(p, ch["id"])
            chain = self._versions(p)
            rows = []
            for v in chain:
                rows += list(reversed(self.s.series.recent(self.org, v["id"], series)))
            band["series"] = [{"t": r["t"], "value": r["value"]} for r in rows]
            if len(chain) > 1:
                band["versions"] = [{"point_id": v["id"], "describe": derived.RULES[v["derived"]["rule"]["type"]]
                                     .describe(v["derived"]["rule"]), "rule": v["derived"]["rule"],
                                     "name": v["name"], "from": v.get("applies_after")} for v in chain]
                band["changes"] = [{"t": v.get("applies_after"), "to": derived.RULES[v["derived"]["rule"]["type"]]
                                    .describe(v["derived"]["rule"])} for v in chain[1:]]
            bands.append(band)
        heads = self.s.snapshots.heads(self.org, ch["id"], limit=max(1, min(int(snapshots), 2000)))
        return self._channel_head(ch, on) | {
            "snapshots": self._stats_view(stats) | {"shown": len(heads), "index": [self._head_view(h) for h in heads]},
            "bands": sorted(bands, key=lambda b: b["name"].lower())}

    def _head_view(self, h: dict) -> dict:
        return {"id": snapshot_id(h["channel_id"], h["t_ms"]), "t": _iso(h["t_ms"]), "running": h.get("running"),
                "rpm": h.get("rpm"), "speed_from": h.get("speed_from"), "source": h.get("source"), "has_raw": bool(h.get("has_raw")),
                "bytes": h.get("size", 0),
                "levels": {a: {k: (None if v is None else float(f"{v:.5g}")) for k, v in lv.items()}
                           for a, lv in (h.get("levels") or {}).items()}}

    def signal_snapshots(self, channel_id, limit=300, since=None, until=None) -> dict:
        """Snapshot headings of a channel, oldest first (the newest ``limit``; ``since`` /
        ``until`` are times)."""
        ch = self._get(str(channel_id or ""), "SignalChannel")
        since_ms = None if since in (None, "") else int(parse_time(since).timestamp() * 1000)
        until_ms = None if until in (None, "") else int(parse_time(until).timestamp() * 1000)
        heads = self.s.snapshots.heads(self.org, ch["id"], since_ms, until_ms, max(1, min(int(limit), 2000)))
        return {"channel_id": ch["id"], "snapshots": [self._head_view(h) for h in heads]}

    def signal_snapshot(self, snapshot, axis=None, f_min=None, f_max=None, max_points=1500, raw=False) -> dict:
        """One snapshot: its levels and spectrum (thinned to ``max_points`` per axis by keeping each
        stretch's peak, so no peak is lost; ask for ``f_min`` / ``f_max`` for full detail in a range).
        ``raw`` adds the samples (at most 20,000 per axis, thinned evenly)."""
        sv = _sv()
        channel_id, t_ms = split_snapshot_id(snapshot)
        ch = self._get(channel_id, "SignalChannel")
        doc = self.s.snapshots.get(self.org, ch["id"], t_ms)
        if doc is None:
            raise sv.NotFound("Snapshot")
        out = self._head_view({**_head(doc), "channel_id": ch["id"]}) | {
            "channel_id": ch["id"], "unit": doc.get("unit", ""), "sample_rate": doc.get("sample_rate"),
            "window": doc.get("window"), "note": doc.get("note", ""), "axes": doc.get("axes") or []}
        axes = [axis] if axis else list(doc.get("axes") or [])
        if doc.get("spectrum"):
            for a in axes:
                if a not in doc["spectrum"]:
                    raise sv.Invalid(f"The snapshot has no axis {a}: its axes are {', '.join(doc['axes'])}.")
            n = int(doc["bins"])
            f = unpack64(doc["freqs"]) if doc.get("freqs") else doc.get("f0", 0.0) + doc["df"] * np.arange(n)
            lo = 0 if f_min in (None, "") else float(f_min)
            hi = float("inf") if f_max in (None, "") else float(f_max)
            pick = np.where((f >= lo) & (f <= hi))[0]
            cap = max(10, min(int(max_points), 20000))
            amps = {}
            freqs = None
            for a in axes:
                y = unpack(doc["spectrum"][a])[pick]
                x = f[pick]
                if len(y) > cap:
                    step = math.ceil(len(y) / cap)
                    pad = (-len(y)) % step
                    ym = np.pad(y, (0, pad), constant_values=-1).reshape(-1, step)
                    arg = ym.argmax(axis=1) + np.arange(ym.shape[0]) * step
                    arg = np.minimum(arg, len(y) - 1)
                    # one shared frequency axis across axes: the first axis's peaks
                    if freqs is None:
                        freqs, idx = x[arg], arg
                    y = y[idx]
                elif freqs is None:
                    freqs, idx = x, np.arange(len(y))
                amps[a] = _sig(y)
            out["spectrum"] = {"freqs": _sig(freqs if freqs is not None else []), "amplitudes": amps,
                               "decimated": bool(len(pick) > cap), "bins": int(len(pick)), "unit": doc.get("unit", ""),
                               "amplitude": "peak", "df": doc.get("df")}
        if raw:
            if not doc.get("raw"):
                raise sv.Invalid("This snapshot has no samples (only a spectrum or a value).")
            out["samples"] = {}
            for a in axes:
                x = unpack(doc["raw"][a])
                if len(x) > 20000:
                    x = x[:: math.ceil(len(x) / 20000)]
                out["samples"][a] = _sig(x)
        return out

    def signal_spectra(self, snapshots, axis=None, f_min=None, f_max=None, max_points=600) -> dict:
        """Several snapshots' spectra for one axis (the chart overlays them)."""
        sv = _sv()
        ids = sv._list(snapshots, "snapshots", 60)
        return {"spectra": [self.signal_snapshot(i, axis, f_min, f_max, max_points) for i in ids]}

    # -- snapshots

    def add_signal_snapshot(self, time, channel_id=None, tag=None, axes=None, samples=None, sample_rate=None,
                            unit=None, spectrum=None, value=None, values=None, running=None, rpm=None,
                            note="") -> dict:
        """Store one snapshot and add a value to every watch band and level of the channel.
        Idempotent on (channel, time to the millisecond): a repeat is reported, not stored again."""
        sv = _sv()
        ch = self._channel_by(channel_id, tag)
        try:
            when = parse_time(self._need_zone(time))
        except ValueError as err:
            raise sv.Invalid(str(err)) from None
        t_ms = int(round(when.timestamp() * 1000))
        when = datetime.fromtimestamp(t_ms / 1000, timezone.utc)
        base = {"snapshot_id": snapshot_id(ch["id"], t_ms), "channel_id": ch["id"], "t": _iso(t_ms)}
        if self.s.snapshots.exists(self.org, ch["id"], t_ms):
            return base | {"stored": False, "duplicate": True,
                           "note": "Already stored for that channel and time; nothing changed."}
        doc, notes = self._build_snapshot(ch, t_ms, axes, samples, sample_rate, unit, spectrum, value, values,
                                          running, rpm, note)
        if self.limited:
            day = datetime.now(timezone.utc).date().isoformat()
            used = getattr(self.s, "snapshot_days", {})
            used = {k: v for k, v in used.items() if k[1] == day}
            if used.get((self.org, day), 0) >= MAX_SNAPSHOTS_PER_DAY:
                raise sv.RateLimited(f"This workspace has stored {MAX_SNAPSHOTS_PER_DAY:,} snapshots today, the limit "
                                     "for a day.")
            used[(self.org, day)] = used.get((self.org, day), 0) + 1
            self.s.snapshot_days = used
        if not self.s.snapshots.put(self.org, ch["id"], t_ms, doc):  # lost a race with a repeat
            return base | {"stored": False, "duplicate": True,
                           "note": "Already stored for that channel and time; nothing changed."}
        apply_retention(self.s.snapshots, self.org, ch["id"])
        written = derived.on_source_data(self, ch, when, doc)
        return base | {"stored": True, "duplicate": False, "source": doc["source"], "axes": doc["axes"],
                       "levels": self._head_view({**_head(doc), "channel_id": ch["id"]})["levels"],
                       "bytes": doc["size"], "derived": written, "notes": notes}

    @staticmethod
    def _need_zone(time):
        sv = _sv()
        if time in (None, ""):
            raise sv.Invalid("A snapshot needs its time (ISO 8601 with a time zone, like 2026-11-03T10:00:00+10:00 "
                             "or ...Z): there's no default, so a batch of old files isn't all stamped today.")
        if isinstance(time, str):
            text = time.strip().replace("Z", "+00:00")
            try:
                parsed = datetime.fromisoformat(text)
            except ValueError:
                return time  # a number as text, or nonsense: parse_time says which
            if parsed.tzinfo is None:
                raise sv.Invalid(f"The time {time[:40]} has no time zone: add Z or an offset like +10:00.")
        return time

    def _build_snapshot(self, ch, t_ms, axes, samples, sample_rate, unit, spectrum, value, values, running,
                        rpm, note):
        sv = _sv()
        notes: list[str] = []
        if samples is not None:
            if axes:
                raise sv.Invalid("Give either axes (name: samples) or samples (one axis), not both.")
            axes = {(ch.get("axes") or ["value"])[0]: samples}
        given = [k for k, v in (("axes/samples", axes), ("spectrum", spectrum), ("value", value),
                                ("values", values)) if v not in (None, {}, [])]
        if not given or (len(given) > 1 and not (axes and spectrum and len(given) == 2)):
            raise sv.Invalid("Send samples (axes), a spectrum, or a value/values: "
                             + ("one of them." if not given else "not a mix of those."))
        u = sv._text(unit, "unit")[:UNIT_MAX] if unit else ""
        if u and ch.get("unit") and u != ch["unit"]:
            raise sv.Invalid(f"The snapshot is in {u} but the channel is in {ch['unit']}; Reliafy doesn't convert. "
                             "Send it in the channel's unit.")
        u = u or ch.get("unit", "")
        speed, speed_from = ch.get("rpm"), None
        if rpm not in (None, ""):
            speed = sv._number(rpm, "rpm", 0.001, 1e6)
        elif ch.get("speed_channel_id"):
            near = self._nearest_speed(ch["speed_channel_id"], t_ms)
            if near:
                speed, speed_from = near["rpm"], {"channel_id": ch["speed_channel_id"], "t": near["t"],
                                                  "gap_s": near["gap_s"]}
            else:
                notes.append("No speed reading within an hour of this snapshot: the channel's own rpm was used.")
        doc: dict = {"channel_id": ch["id"], "t_ms": t_ms, "running": None if running is None else bool(running),
                     "rpm": speed, "note": sv._text(note, "note")[:500], "unit": u}
        if speed_from:
            doc["speed_from"] = speed_from
        total = 0
        if axes:
            arrays = self._arrays(axes, ch)
            rate = sv._number(sample_rate if sample_rate not in (None, "") else ch.get("sample_rate"),
                              "sample rate (Hz)", 0.001, 1e7) if (sample_rate not in (None, "")
                                                               or ch.get("sample_rate")) else None
            if rate is None:
                raise sv.Invalid("Samples need a sample_rate in Hz (on the snapshot, or set on the channel).")
            names = list(arrays)
            n = len(next(iter(arrays.values())))
            if n < MIN_SAMPLES:
                raise sv.Invalid(f"A snapshot needs at least {MIN_SAMPLES} samples per axis.")
            total = n * len(names)
            if spectrum:
                notes.append("The spectrum you sent was not stored: with samples, the spectrum is computed from "
                             "them, so every snapshot is comparable.")
            spec, levels = {}, {}
            df = None
            for a, x in arrays.items():
                df, amp = spectrum_of(x, rate)
                spec[a] = pack(amp)
                levels[a] = levels_of(x)
            doc |= {"source": "samples", "sample_rate": rate, "n": n, "window": "hann", "enbw": ENBW["hann"],
                    "df": df, "f0": 0.0, "bins": n // 2 + 1, "axes": names, "levels": levels, "spectrum": spec,
                    "raw": {a: pack(x) for a, x in arrays.items()}, "has_raw": True}
        elif spectrum:
            doc |= self._vendor_spectrum(ch, spectrum)
            total = doc["bins"] * len(doc["axes"])
        else:
            scalars = values if values else {(ch.get("axes") or ["value"])[0]: value}
            if not isinstance(scalars, dict) or not scalars:
                raise sv.Invalid("values is {axis: number}.")
            levels = {}
            for a, v in scalars.items():
                levels[str(a)[:40]] = {"value": sv._number(v, "value", -sv.MAX_AMOUNT, sv.MAX_AMOUNT)}
            self._check_axis_names(list(levels), ch)
            doc |= {"source": "value", "axes": list(levels), "levels": levels, "has_raw": False}
        if total > MAX_VALUES:
            raise sv.Invalid(f"This snapshot has {total:,} numbers; the most is {MAX_VALUES:,} (about 5 MB). "
                             "Send it in shorter bursts.")
        doc["size"] = _size(doc)
        return doc, notes

    def _nearest_speed(self, speed_id: str, t_ms: int) -> dict | None:
        """The speed channel's reading nearest in time to ``t_ms`` (within an hour), or None."""
        try:
            src = self._get(speed_id, "SignalChannel")
        except Exception:  # noqa: BLE001 - the speed channel is gone
            return None
        best = None
        for h in self.s.snapshots.heads(self.org, src["id"], t_ms - SPEED_WINDOW_MS, t_ms + SPEED_WINDOW_MS):
            levels = next(iter((h.get("levels") or {}).values()), None) or {}
            value = levels.get("value")
            if value is None or value <= 0:
                continue
            gap = abs(h["t_ms"] - t_ms)
            if best is None or gap < best[0]:
                best = (gap, h["t_ms"], float(value))
        return best and {"rpm": best[2], "t": _iso(best[1]), "gap_s": round(best[0] / 1000, 1)}

    def _check_axis_names(self, names, ch):
        sv = _sv()
        declared = ch.get("axes") or []
        if len(names) > MAX_AXES:
            raise sv.Invalid(f"At most {MAX_AXES} axes.")
        if declared:
            bad = [a for a in names if a not in declared]
            if bad:
                raise sv.Invalid(f"The channel's axes are {', '.join(declared)}; the snapshot has {', '.join(bad)}.")

    def _arrays(self, axes, ch) -> dict:
        sv = _sv()
        if not isinstance(axes, dict) or not axes:
            raise sv.Invalid("axes is {axis name: [samples]}.")
        self._check_axis_names([str(a) for a in axes], ch)
        out = {}
        for a, v in axes.items():
            try:
                x = np.asarray(v, dtype=float)
            except (TypeError, ValueError):
                raise sv.Invalid(f"Axis {a}: samples must be a list of numbers.") from None
            if x.ndim != 1:
                raise sv.Invalid(f"Axis {a}: samples must be a flat list of numbers.")
            if not np.isfinite(x).all():
                raise sv.Invalid(f"Axis {a} has a value that isn't a finite number (NaN or infinity).")
            out[str(a)[:40]] = x
        if len({len(x) for x in out.values()}) != 1:
            raise sv.Invalid("Every axis needs the same number of samples.")
        return out

    def _vendor_spectrum(self, ch, spectrum) -> dict:
        sv = _sv()
        if not isinstance(spectrum, dict):
            raise sv.Invalid("spectrum is {df or freqs, amplitudes, window?, amplitude?}.")
        amps = spectrum.get("amplitudes")
        if isinstance(amps, list):
            amps = {(ch.get("axes") or ["value"])[0]: amps}
        if not isinstance(amps, dict) or not amps:
            raise sv.Invalid("spectrum.amplitudes is {axis name: [amplitude per line]} (or one list).")
        self._check_axis_names([str(a) for a in amps], ch)
        arrays = {}
        for a, v in amps.items():
            try:
                y = np.asarray(v, dtype=float)
            except (TypeError, ValueError):
                raise sv.Invalid(f"Axis {a}: amplitudes must be numbers.") from None
            if y.ndim != 1 or len(y) < 2 or not np.isfinite(y).all() or (y < 0).any():
                raise sv.Invalid(f"Axis {a}: amplitudes must be a list of at least 2 finite numbers, none negative.")
            arrays[str(a)[:40]] = y
        bins = len(next(iter(arrays.values())))
        if len({len(y) for y in arrays.values()}) != 1:
            raise sv.Invalid("Every axis needs the same number of spectrum lines.")
        kind = spectrum.get("amplitude") or "peak"
        if kind not in ("peak", "rms"):
            raise sv.Invalid("spectrum.amplitude is peak or rms.")
        factor = math.sqrt(2.0) if kind == "rms" else 1.0
        window = str(spectrum.get("window") or "unknown").lower()
        out: dict = {"source": "spectrum", "axes": list(arrays), "bins": bins, "has_raw": False,
                     "window": window, "enbw": ENBW.get(window, 1.0), "f0": 0.0, "sample_rate": None}
        if spectrum.get("freqs") is not None:
            f = np.asarray(spectrum["freqs"], dtype=float)
            if f.shape != (bins,) or not np.isfinite(f).all() or (np.diff(f) <= 0).any():
                raise sv.Invalid("spectrum.freqs must be increasing, one per amplitude.")
            df = float((f[-1] - f[0]) / (bins - 1))
            if np.allclose(f, f[0] + df * np.arange(bins), rtol=1e-6, atol=df * 1e-6):
                out |= {"df": df, "f0": float(f[0])}
            else:
                out |= {"df": df, "f0": float(f[0]), "freqs": pack64(f)}
        else:
            df = sv._number(spectrum.get("df"), "spectrum.df (Hz per line)", 1e-9, 1e7)
            out |= {"df": df, "f0": sv._number(spectrum.get("f0") or 0, "spectrum.f0", 0, 1e7)}
        freqs = unpack64(out["freqs"]) if out.get("freqs") else out["f0"] + out["df"] * np.arange(bins)
        out["spectrum"] = {a: pack(y * factor) for a, y in arrays.items()}
        out["levels"] = {a: {"rms": band_rms(0, 0, y * factor, 0, float("inf"), out["enbw"], freqs)}
                         for a, y in arrays.items()}
        return out

    # -- bands and levels

    def _check_band_limit(self, ch):
        sv = _sv()
        if len(derived.points_of(self, ch["id"])) >= MAX_BANDS_PER_CHANNEL:
            raise sv.Invalid(f"A channel can have at most {MAX_BANDS_PER_CHANNEL} bands and levels.")

    def add_signal_band(self, channel_id, name, low, high, axis=None, unit="Hz", alarm_above=None,
                        alarm_below=None, warn_above=None, warn_below=None) -> dict:
        """A watch band: a frequency range (Hz, or multiples of the running speed with unit
        'orders') whose RMS level each snapshot adds to a measurement point. Backfilled from the
        snapshots already stored. Its alarm limits work like any condition point's; warning
        levels (warn_above / warn_below) are drawn as lines and open no work."""
        sv = _sv()
        ch = self._live_channel(channel_id)
        self._check_band_limit(ch)
        name = sv._text(name, "band's name", required=True)
        return self._add_derived(ch, name, {"type": "band", "axis": axis, "low": low, "high": high, "in": unit},
                                 alarm_above, alarm_below, warn_above, warn_below)

    def add_signal_level(self, channel_id, name, stat, axis=None, alarm_above=None, alarm_below=None,
                         warn_above=None, warn_below=None) -> dict:
        """An overall level (rms, peak, crest, kurtosis, mean, or a scalar value) of each snapshot,
        as a measurement point. A channel with only scalar readings (a pressure) uses 'value'."""
        sv = _sv()
        ch = self._live_channel(channel_id)
        self._check_band_limit(ch)
        name = sv._text(name, "level's name", required=True)
        return self._add_derived(ch, name, {"type": "level", "axis": axis, "stat": stat}, alarm_above, alarm_below,
                                 warn_above, warn_below)

    def _warn_pair(self, warn_above, warn_below, alarm_above, alarm_below):
        """Check and clean warning levels: the warning comes before the alarm."""
        sv = _sv()
        above, below = self._amount_or_none(warn_above), self._amount_or_none(warn_below)
        if above is not None and below is not None and below >= above:
            raise sv.Invalid("The low warning must be below the high warning.")
        if above is not None and alarm_above is not None and above >= alarm_above:
            raise sv.Invalid("The high warning must be below the high alarm.")
        if below is not None and alarm_below is not None and below <= alarm_below:
            raise sv.Invalid("The low warning must be above the low alarm.")
        return above, below

    def _add_derived(self, ch, name, rule, alarm_above, alarm_below, warn_above=None, warn_below=None,
                     supersedes=None, applies_after=None) -> dict:
        on = self.s.out(self.org, ch["id"], "ON")[0]
        subject = {"position_id": on["id"]} if on["label"] == "Position" else {"subject": {"kind": "item", "id": on["id"]}}
        warn = self._warn_pair(warn_above, warn_below, self._amount_or_none(alarm_above),
                               self._amount_or_none(alarm_below))
        made = derived.add(self, ch, name, rule, subject, alarm_above, alarm_below, supersedes, applies_after)
        if warn != (None, None):
            self._emit("signal_band.limits", {"id": made["point_id"], "warn_above": warn[0], "warn_below": warn[1]})
        band = next(b for b in self.signal_channel(ch["id"], 1, 50)["bands"] if b["point_id"] == made["point_id"])
        return {"point_id": made["point_id"], "history_written": made["written"], "band": band}

    def remove_signal_band(self, point_id, reason="") -> dict:
        """Stop a band or level adding values (what it has recorded stays; retire only)."""
        sv = _sv()
        point = self._get(str(point_id or ""), "MeasurementPoint")
        if not point.get("derived"):
            raise sv.Invalid("That point isn't a band or level of a channel.")
        return self.retire_point(point_id, reason)

    def _versions(self, head: dict) -> list[dict]:
        """A band's versions, oldest first, ending with ``head``."""
        chain = [head]
        while chain[0].get("supersedes"):
            older = self.s.node(self.org, chain[0]["supersedes"])
            if not older:
                break
            chain.insert(0, older)
        return chain

    def update_signal_band(self, point_id, name=None, low=None, high=None, axis=None, unit=None,
                           alarm_above=..., alarm_below=..., warn_above=..., warn_below=...) -> dict:
        """Change a band's name, range or limits without losing its history.

        Name and limits change in place. A new range (``low``, ``high``, ``axis`` or ``unit``) makes a
        new *version* of the band: the old version stops (its recorded values stay, exactly as they
        were measured) and the new one takes snapshots that arrive from now, so the trend shows one
        line with the change marked. Earlier snapshots are not re-read with the new range: to see
        them that way, add a new band (which is worked out from everything stored)."""
        sv = _sv()
        point = self._live_point(point_id)
        if not point.get("derived"):
            raise sv.Invalid("That point isn't a band or level of a channel.")
        ch = self._get(point["derived"]["from"], "SignalChannel")
        old = point["derived"]["rule"]
        rule = derived.RULES[old["type"]]
        new_range = any(v is not None for v in (low, high, axis, unit))
        if new_range and old["type"] != "band":
            raise sv.Invalid("Only a band has a range to change.")
        above = point.get("alarm_above") if alarm_above is ... else self._amount_or_none(alarm_above)
        below = point.get("alarm_below") if alarm_below is ... else self._amount_or_none(alarm_below)
        w_above = point.get("warn_above") if warn_above is ... else warn_above
        w_below = point.get("warn_below") if warn_below is ... else warn_below
        if above is not None and below is not None and below >= above:
            raise sv.Invalid("The low alarm must be below the high alarm.")
        warn = self._warn_pair(w_above, w_below, above, below)
        new_name = point["name"] if name is None else sv._text(name, "band's name", required=True)
        spec = None
        if new_range:
            spec = rule.validate(self, ch, {"axis": old["axis"] if axis in (None, "") else axis,
                                            "low": old["low"] if low is None else low,
                                            "high": old["high"] if high is None else high,
                                            "in": old["in"] if unit in (None, "") else unit})
            if all(spec[k] == old[k] for k in ("axis", "low", "high", "in")):
                spec = None
        if spec is None:
            changes: dict = {}
            if new_name != point["name"]:
                changes["name"] = new_name
            if above != point.get("alarm_above"):
                changes["alarm_above"] = above
            if below != point.get("alarm_below"):
                changes["alarm_below"] = below
            if changes:
                self.update_point(point_id, **changes)
            if warn != (point.get("warn_above"), point.get("warn_below")):
                self._emit("signal_band.limits", {"id": point_id, "warn_above": warn[0], "warn_below": warn[1]})
            made = point_id
        else:
            # Check that the old version can stop before the new one starts.
            if any(t for t in self.s.nodes(self.org, "Task")
                   if not t.get("retired") and (t.get("point_id") or t.get("meter_id")) == point_id):
                raise sv.Invalid(f"A task goes by {point['name']}: point it at another counter first (maintenance "
                                 "tasks.update point_id), then change the range.")
            if any(w["label"] == "WorkOrder" and w["status"] in sv.OPEN_STATUSES
                   for w in self.s.inn(self.org, point_id, "ALARM_FOR")):
                raise sv.Invalid("It has an open alarm work order. Close or cancel it first.")
            last = self.s.snapshots.heads(self.org, ch["id"], limit=1)
            after = _iso(last[0]["t_ms"]) if last else datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            made = self._add_derived(ch, new_name, spec, above, below, warn[0], warn[1], supersedes=point_id,
                                     applies_after=after)["point_id"]
            self.retire_point(point_id, "Range changed: replaced by a new version of this band.")
        band = next(b for b in self.signal_channel(ch["id"], 1, 1000)["bands"] if b["point_id"] == made)
        return {"point_id": made, "new_version": spec is not None, "band": band}

    # -- storage

    def signal_storage(self) -> dict:
        """What the workspace's snapshots use: megabytes (as stored, raw plus spectrum, compressed),
        the number of snapshots, per channel, and the soft cap if one is set. Nothing is deleted."""
        per = []
        for ch in self.s.nodes(self.org, "SignalChannel"):
            st = self.s.snapshots.stats(self.org, ch["id"])
            per.append({"channel_id": ch["id"], "name": ch["name"], "count": st["count"], "bytes": st["bytes"],
                        "retired": bool(ch.get("retired"))})
        total = sum(c["bytes"] for c in per)
        cfg = self.s.node(self.org, SETTINGS_ID) or {}
        cap = cfg.get("storage_cap_mb")
        out = {"snapshots": sum(c["count"] for c in per), "bytes": total, "mb": round(total / 1e6, 2),
               "cap_mb": cap, "over_cap": bool(cap and total > cap * 1e6),
               "channels": sorted(per, key=lambda c: -c["bytes"])}
        if out["over_cap"]:
            out["warning"] = (f"Snapshots use {out['mb']} MB, over the {cap:g} MB warning level you set. Nothing is "
                              "deleted: this is a reminder to decide what to keep.")
        return out

    def set_signal_storage_cap(self, cap_mb=None) -> dict:
        """Set (or, with no value, clear) the size in MB at which the Signals tab warns. Default: off."""
        sv = _sv()
        cap = None if cap_mb in (None, "", 0) else sv._number(cap_mb, "cap (MB)", 1, 1e6)
        self._emit("signal_settings.set", {"storage_cap_mb": cap})
        return self.signal_storage()

    def preview_signal_band(self, channel_id, low, high, axis=None, unit="Hz", max_points=400) -> dict:
        """What a band would have read at every stored snapshot (nothing is saved)."""
        ch = self._get(str(channel_id or ""), "SignalChannel")
        rule = derived.RULES["band"]
        spec = rule.validate(self, ch, {"axis": axis, "low": low, "high": high, "in": unit})
        rows = []
        for when, doc in rule.records(self, ch):
            v = rule.compute(spec, doc)
            if v is not None:
                rows.append({"t": when.isoformat().replace("+00:00", "Z"), "value": v})
        if len(rows) > int(max_points):
            keep = np.linspace(0, len(rows) - 1, int(max_points)).round().astype(int)
            rows = [rows[i] for i in sorted(set(keep.tolist()))]
        return {"rule": spec, "series": rows}

