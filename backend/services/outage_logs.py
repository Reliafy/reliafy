"""Outage logs: a diagram's observed up/down history (issue #159).

An outage log is a table of real outages — which asset, when it went down,
when it came back (blank = still down), and optionally why and whether it was
planned — linked to one of the owner's RBDs. Each asset name maps to a block
of the diagram. From it, RePyability's timelines
(:mod:`repyability.timelines`) give

* each block's up/down history (``Timeline.from_outages``);
* the system's, merged up the diagram's structure (``RBD.system_timeline``),
  each change keeping its *cause* — the block whose change took the system
  down (or brought it back) — and whether it was planned;
* the measures of either: uptime, downtime, availability, failures, planned
  outages and failures by cause.

Nothing here re-implements the merge: this module only reads the table,
turns dates into times on the diagram's axis, and lays the library's answer
out for the app, the REST API and the MCP tools.

Stored document (collection ``outage_logs``)::

    {_id, owner_id, rbd_id, name, created_at, updated_at,
     unit,                      # the diagram's time unit the times are in
     time_kind,                 # "datetime" | "number" — what the source held
     origin,                    # datetime logs: ISO time of t = 0, else None
     window: {start, end},      # observation window, in log time
     rows: [{asset, start, end, reason, planned}],   # end None = still down
     asset_map: {source asset name: node id},
     asset_units: {asset: unit number | "all"},   # explicit units of multi-unit blocks (#181)
     columns: {asset, start, end, duration, reason, planned},   # the mapping
     notes: [...]}              # what the import merged, guessed or dropped

Times in ``rows`` and ``window`` are numbers in ``unit``: for a datetime log
they are measured from ``origin`` (the window start the log was imported
with), so editing the window later only moves ``window``.
"""

from __future__ import annotations

import io
import math
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import numpy as np
import pandas as pd

from backend.services import access
from backend.units import unit_in_text

# Row cap per log: far beyond any real plant log of one diagram, and keeps a
# document well inside MongoDB's 16 MB.
MAX_ROWS = 20_000
MAX_ERRORS_SHOWN = 20

FIELDS = ("asset", "start", "end", "duration", "reason", "planned")

# Seconds per time unit (a month is a twelfth of a Julian year).
_UNIT_SECONDS = {
    "second": 1.0,
    "minute": 60.0,
    "hour": 3600.0,
    "day": 86400.0,
    "week": 7 * 86400.0,
    "month": 365.25 * 86400.0 / 12,
    "year": 365.25 * 86400.0,
}
_UNIT_ALIASES = {
    "s": "second", "sec": "second", "secs": "second", "seconds": "second",
    "min": "minute", "mins": "minute", "minutes": "minute",
    "h": "hour", "hr": "hour", "hrs": "hour", "hours": "hour",
    "d": "day", "days": "day",
    "w": "week", "wk": "week", "wks": "week", "weeks": "week",
    "mo": "month", "mon": "month", "mth": "month", "mths": "month", "months": "month",
    "y": "year", "yr": "year", "yrs": "year", "years": "year",
}

# Header patterns for auto-detecting the column mapping: per field, tried
# strongest first; fields are placed in the order of this dict, each column
# used once.
_HEADER_HINTS = {
    "start": (r"^(outage[ _-]?)?start", r"start|^begin", r"^(went[ _-]?)?down[ _-]?(at|date|date[ _-]?time)?$",
              r"^from$|^out$|^fail(ed|ure)?[ _-]?(at|date|time)$"),
    "end": (r"^(outage[ _-]?)?end", r"\bend\b|finish", r"restor|return|^back|^up[ _-]?(at|date|time)?$|^to$|"
                                                        r"until|resum"),
    "duration": (r"duration|downtime|hours[ _-]?down|^ttr|repair[ _-]?time",),
    "asset": (r"^(asset|component|equipment|block|node|tag)", r"asset|component|equipment|machine|item|tag",
              r"^name$|unit[ _-]?id|^unit$|^system$"),
    "planned": (r"planned|scheduled|^pm$",),
    "reason": (r"reason|cause|description|comment|notes?$|remark|mode|^type$|code",),
}

_TRUE = {"1", "y", "yes", "true", "t", "planned", "plan", "scheduled", "pm", "p", "maintenance", "x"}
_FALSE = {"", "0", "n", "no", "false", "f", "unplanned", "unscheduled", "failure", "fault", "breakdown", "cm",
          "corrective", "trip", "forced"}


class OutageLogError(ValueError):
    """A log that can't be read or analysed (the message is for the user)."""

    def __init__(self, message: str, errors: Optional[list] = None):
        super().__init__(message)
        self.errors = errors or []


class OutageLogNotFound(KeyError):
    """An outage log id the caller can't see."""


# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------

def time_unit(unit) -> Optional[str]:
    """The canonical clock unit ('hour', 'day', …) of a unit label, or None
    when it isn't a clock unit (cycles, km, blank)."""
    key = str(unit or "").strip().lower().rstrip(".")
    key = _UNIT_ALIASES.get(key, key)
    return key if key in _UNIT_SECONDS else None


def _unit_factor(source: str, target: str) -> float:
    """Multiply a time in ``source`` by this to get it in ``target``."""
    return _UNIT_SECONDS[source] / _UNIT_SECONDS[target]


# ---------------------------------------------------------------------------
# Reading the table
# ---------------------------------------------------------------------------

def read_table(text: str) -> pd.DataFrame:
    """Parse CSV, TSV or pasted spreadsheet text (header row first) into a
    frame of strings. The delimiter is chosen from tab / comma / semicolon /
    pipe by counting them in the header row, as dataset paste does."""
    text = (text or "").lstrip("﻿").strip()
    if not text:
        raise OutageLogError("The outage log is empty — give a header row and at least one outage.")
    header = next((ln for ln in text.splitlines() if ln.strip()), "")
    delim = max("\t,;|", key=lambda d: header.count(d))
    if header.count(delim) == 0:
        raise OutageLogError(
            "Only one column was found. An outage log needs at least an asset and a start column, separated "
            "by commas or tabs, with a header row.")
    try:
        df = pd.read_csv(io.StringIO(text), sep=delim, dtype=str, keep_default_na=False,
                         skipinitialspace=True, engine="python")
    except Exception as exc:  # noqa: BLE001 - pandas raises many kinds
        raise OutageLogError(f"Couldn't read the outage log: {exc}") from exc
    df.columns = [str(c).strip() for c in df.columns]
    df = df[[c for c in df.columns if c and not c.startswith("Unnamed:")]]
    if df.empty:
        raise OutageLogError("The outage log has a header row but no outages.")
    if len(df) > MAX_ROWS:
        raise OutageLogError(f"The outage log has {len(df):,} rows; the limit is {MAX_ROWS:,} per log. "
                             "Split it by period or by part of the plant.")
    return df


def detect_columns(columns: list[str]) -> dict:
    """A best-guess column mapping from the headers: ``{field: column}`` for
    the fields it could place (each column used once)."""
    out: dict[str, str] = {}
    used: set[str] = set()
    norm = {c: re.sub(r"\s+", " ", str(c).strip().lower()) for c in columns}
    for field, patterns in _HEADER_HINTS.items():
        for pattern in patterns:
            rx = re.compile(pattern)
            hit = next((c for c in columns if c not in used and rx.search(norm[c])), None)
            if hit is not None:
                out[field] = hit
                used.add(hit)
                break
    if "end" in out and "duration" in out:
        out.pop("duration")
    return out


def _check_mapping(columns: list[str], mapping: dict) -> dict:
    mapping = {k: (str(v).strip() if v else "") for k, v in (mapping or {}).items() if k in FIELDS}
    mapping = {k: v for k, v in mapping.items() if v}
    for field, col in mapping.items():
        if col not in columns:
            raise OutageLogError(f"Column '{col}' (for {field}) isn't in the log. Columns: {', '.join(columns)}.")
    missing = [f for f in ("asset", "start") if f not in mapping]
    if missing:
        raise OutageLogError(
            f"Say which column holds the {' and the '.join(missing)} of each outage. Columns: "
            f"{', '.join(columns)}.")
    if "end" in mapping and "duration" in mapping:
        raise OutageLogError("Map either an end column or a duration column, not both.")
    if "end" not in mapping and "duration" not in mapping:
        raise OutageLogError(
            "Say which column holds when each outage ended (blank = still down), or a duration column.")
    return mapping


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------

_NUMERIC_DATE = re.compile(r"^\s*(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2}|\d{4})\b")
_TIME_PARTS = ("", " %H:%M", " %H:%M:%S", " %H:%M:%S.%f", " %I:%M %p", " %I:%M:%S %p", "T%H:%M", "T%H:%M:%S")
_TEXT_DATES = ("%d %b %Y", "%d %B %Y", "%b %d %Y", "%B %d %Y", "%b %d, %Y", "%B %d, %Y", "%d-%b-%Y",
               "%d-%b-%y", "%Y/%m/%d", "%Y.%m.%d", "%Y%m%d")


def _number(value: str) -> Optional[float]:
    try:
        v = float(str(value).strip().replace(",", ""))
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _date_formats(order: str) -> list[str]:
    day = order == "dmy"
    bases = []
    for sep in ("/", "-", "."):
        for year in ("%Y", "%y"):
            bases.append(f"%d{sep}%m{sep}{year}" if day else f"%m{sep}%d{sep}{year}")
    bases += list(_TEXT_DATES)
    return [b + t for b in bases for t in _TIME_PARTS]


def choose_date_order(values: list[str], requested: str = "auto") -> tuple[str, Optional[str]]:
    """``(order, note)``: whether numeric dates like 03/04/2024 read day first
    ('dmy') or month first ('mdy'). ``requested`` other than 'auto' wins; else
    a day field over 12 settles it, and an ambiguous log reads day first, with
    a note saying so."""
    if requested in ("dmy", "mdy"):
        return requested, None
    first_big = second_big = False
    ambiguous = False
    for v in values:
        m = _NUMERIC_DATE.match(str(v))
        if not m:
            continue
        a, b = int(m.group(1)), int(m.group(2))
        first_big |= a > 12
        second_big |= b > 12
        ambiguous |= a <= 12 and b <= 12 and a != b
    if first_big and second_big:
        raise OutageLogError(
            "The dates mix day-first and month-first forms (some have a first field over 12, some a second): "
            "use one form throughout, ideally ISO (2024-03-14 08:30).")
    if second_big:
        return "mdy", None
    if first_big:
        return "dmy", None
    if ambiguous:
        return "dmy", ("Dates like 03/04/2024 were read day first (3 April 2024). If they're month first, "
                       "re-import with the date order set to month first.")
    return "dmy", None


def parse_datetime(value: str, order: str = "dmy") -> Optional[datetime]:
    """A date/time from ISO 8601 or a common spreadsheet form, as naive UTC
    (an explicit offset is converted; a naive time is taken as is). None if
    it isn't one."""
    s = str(value).strip()
    if not s:
        return None
    iso = s.replace("Z", "+00:00") if s.endswith("Z") else s
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        dt = None
    if dt is None:
        compact = re.sub(r"\s+", " ", s)
        for fmt in _date_formats(order):
            try:
                dt = datetime.strptime(compact, fmt)
                break
            except ValueError:
                continue
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _parse_planned(value: str) -> Optional[bool]:
    key = str(value or "").strip().lower()
    if key in _TRUE:
        return True
    if key in _FALSE:
        return False
    return None


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

def _norm_name(value) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def _whole(value, default: int) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def block_units(ntype: Optional[str], data: Optional[dict]) -> Optional[tuple[int, int]]:
    """``(units, k)`` for a block of several identical units — up while at
    least ``k`` of its ``units`` are (#181) — read as the analysis reads the
    block: a series count needs all ``n``, a parallel count any one, a standby
    group (the duty unit plus its spares) any one, a load-sharing group ``k``
    of its ``units``. None for a one-unit block: a component, a count of 1,
    or a sub-system (taken whole: its own diagram isn't in this one)."""
    data = data or {}
    if ntype in ("series", "parallel"):
        n = max(_whole(data.get("n"), 1), 1)
        spec = (n, n if ntype == "series" else 1)
    elif ntype == "standby":
        spec = (1 + max(_whole(data.get("spares"), 1) or 1, 1), 1)  # 0 spares reads as 1, as the analysis does
    elif ntype == "loadshare":
        n = max(_whole(data.get("units"), 2), 2)
        spec = (n, min(max(_whole(data.get("k"), 1), 1), n))
    else:
        return None
    return spec if spec[0] > 1 else None


def diagram_blocks(graph: dict) -> dict:
    """``{node id: {label, type, units}}`` for the diagram's blocks (no
    input/output); ``units`` is :func:`block_units` (None for one unit)."""
    out = {}
    for n in (graph or {}).get("nodes") or []:
        if n.get("type") in ("input", "output"):
            continue
        data = n.get("data") or {}
        out[str(n.get("id"))] = {"label": str(data.get("label") or n.get("id")), "type": n.get("type"),
                                 "units": block_units(n.get("type"), data)}
    return out


_KIND = {"series": "series count", "parallel": "parallel count", "standby": "standby group",
         "loadshare": "load-sharing group"}


def _split_target(target: str, blocks: dict) -> tuple[str, Any]:
    """A mapping target as ``(node id, unit)``: ``node`` (unit None: given
    one by default), ``node#2`` (its second unit) or ``node#all`` (the whole
    block, e.g. a shared header or the group's own controls)."""
    if target in blocks or "#" not in target:
        return target, None
    nid, _, unit = target.rpartition("#")
    if nid not in blocks:
        return target, None
    unit = unit.strip().lower()
    if unit in ("all", "*", "block"):
        return nid, "all"
    if not unit.isdigit():
        raise OutageLogError(f"'{target}': after the '#' give a unit number (1, 2, …) or 'all' for the whole block.")
    return nid, int(unit)


def _check_unit(name: str, nid: str, unit, blocks: dict) -> Any:
    """``unit`` checked against the block's units; a one-unit block's unit
    is dropped (the asset is the block)."""
    if unit is None:
        return None
    spec = blocks[nid]["units"]
    if spec is None:
        if unit in ("all", 1):
            return None
        raise OutageLogError(f"Asset '{name}' is mapped to unit {unit} of “{blocks[nid]['label']}”, which is one "
                             "unit: map it to the block itself.")
    if unit != "all" and not 1 <= unit <= spec[0]:
        raise OutageLogError(f"Asset '{name}' is mapped to unit {unit} of “{blocks[nid]['label']}”, which has "
                             f"{spec[0]} units (1 to {spec[0]}).")
    return unit


def map_assets(names: list[str], graph: dict, overrides: Optional[dict] = None
               ) -> tuple[dict, list[str], list, dict]:
    """``(asset_map, unmapped, notes, asset_units)``: each source asset name
    matched to a block — by an explicit override, else its node id, else its
    label (case and spacing ignored). A k-of-n vote gate takes no outages.

    An override may name a unit of a multi-unit block (#181): ``node#2``, or
    ``node#all`` for an asset that stands for the whole block; those land in
    ``asset_units`` ({asset: unit number or "all"}). Other assets on a
    multi-unit block are given its free units in turn (see
    :func:`unit_assignment`)."""
    blocks = diagram_blocks(graph)
    by_id = {_norm_name(nid): nid for nid in blocks}
    by_label: dict[str, list[str]] = {}
    for nid, b in blocks.items():
        by_label.setdefault(_norm_name(b["label"]), []).append(nid)
    overrides = {str(k): (str(v) if v else "") for k, v in (overrides or {}).items()}
    out: dict[str, str] = {}
    units: dict[str, Any] = {}
    unmapped: list[str] = []
    notes: list[str] = []
    for name in names:
        if name in overrides:
            target, unit = _split_target(overrides[name], blocks)
            if not target:
                unmapped.append(name)
                continue
            if target not in blocks:
                raise OutageLogError(f"Asset '{name}' is mapped to '{target}', which isn't a block of this diagram.")
            if blocks[target]["type"] == "knode":
                raise OutageLogError(f"Asset '{name}' is mapped to the vote gate “{blocks[target]['label']}”: a "
                                     "gate is logic, not equipment, and takes no outages.")
            out[name] = target
            unit = _check_unit(name, target, unit, blocks)
            if unit is not None:
                units[name] = unit
            continue
        key = _norm_name(name)
        if key in by_id and blocks[by_id[key]]["type"] != "knode":
            out[name] = by_id[key]
            continue
        hits = [nid for nid in by_label.get(key, []) if blocks[nid]["type"] != "knode"]
        if len(hits) == 1:
            out[name] = hits[0]
        else:
            if len(hits) > 1:
                notes.append(f"Asset '{name}' matches {len(hits)} blocks with that label — map it by hand.")
            unmapped.append(name)
    return out, unmapped, notes, units


def unit_assignment(asset_map: dict, asset_units: Optional[dict], blocks: dict) -> tuple[dict, list[str]]:
    """``(units, problems)``: per asset on a multi-unit block, the unit it
    is (#181) — its explicit one (``asset_units``), else the block's free
    units in turn, assets in name order — or "all" for a whole-block asset.
    Assets on one-unit blocks aren't listed. ``problems`` names each block
    with more assets than free units (they can't all be told apart)."""
    explicit = asset_units or {}
    on: dict[str, list[str]] = {}
    for asset, nid in (asset_map or {}).items():
        if nid in blocks and blocks[nid].get("units"):
            on.setdefault(nid, []).append(asset)
    units: dict[str, Any] = {}
    problems: list[str] = []
    for nid, assets in on.items():
        n = blocks[nid]["units"][0]
        taken = set()
        rest = []
        for a in sorted(assets, key=lambda s: (_norm_name(s), s)):
            u = explicit.get(a)
            if u == "all" or (isinstance(u, int) and 1 <= u <= n):
                units[a] = u
                if u != "all":
                    taken.add(u)
            else:
                rest.append(a)
        free = [u for u in range(1, n + 1) if u not in taken]
        if len(rest) > len(free):
            label = blocks[nid]["label"]
            problems.append(
                f"{len(rest) + len(taken)} assets are mapped to units of “{label}”, which has {n} "
                f"({', '.join(sorted(assets)[:8])}{'…' if len(assets) > 8 else ''}). Say which unit each is — map "
                f"an asset that replaced another to the same unit (e.g. '{nid}#1'), or one that stands for the "
                f"whole block to '{nid}#all'.")
            continue
        units.update(zip(rest, free))
    return units, problems


def _unit_notes(asset_map: dict, asset_units: Optional[dict], blocks: dict) -> list[str]:
    """What each multi-unit block's assets were taken as (#181)."""
    units, problems = unit_assignment(asset_map, asset_units, blocks)
    notes = list(problems)
    per: dict[str, list] = {}
    for asset, u in units.items():
        per.setdefault(asset_map[asset], []).append((asset, u))
    for nid, items in per.items():
        b = blocks[nid]
        n, k = b["units"]
        need = "all" if k == n else ("any one" if k == 1 else f"{k}")
        down = ("down while any unit is" if k == n else
                ("down only while both units are" if n == 2 else f"down only while all {n} units are") if k == 1 else f"down while fewer than {k} of its {n} are up")
        parts = [f"{a} is {'the whole block' if u == 'all' else f'unit {u}'}"
                 for a, u in sorted(items, key=lambda x: (x[1] == "all", x[1] if x[1] != "all" else 0, x[0]))]
        notes.append(f"“{b['label']}” is a {_KIND.get(b['type'], 'group')} of {n} units ({need} needed), so it is "
                     f"{down}: {'; '.join(parts)}.")
        if k < n and len(items) == 1 and items[0][1] != "all":
            notes.append(f"Only one unit of “{b['label']}” has outages in the log, so they never take the block "
                         f"down on their own. If that asset stands for the whole block, map it to '{nid}#all'.")
    return notes


def merge_outages(outages: list[dict]) -> tuple[list[dict], list[tuple]]:
    """Merge overlapping outages (one asset, or one block): ``(merged,
    merges)`` where each merged outage spans its parts, is still open if any
    part is, is planned only if every part is, and lists the rows it came
    from; ``merges`` is ``(rows merged,)`` per merge."""
    if not outages:
        return [], []
    items = sorted(outages, key=lambda o: (o["start"], math.inf if o["end"] is None else o["end"]))
    merged: list[dict] = []
    merges: list[tuple] = []
    for o in items:
        if merged:
            cur = merged[-1]
            cur_end = math.inf if cur["end"] is None else cur["end"]
            if o["start"] < cur_end:
                end = None if (cur["end"] is None or o["end"] is None) else max(cur["end"], o["end"])
                reasons = [r for r in (cur.get("reason") or "").split("; ") + [o.get("reason") or ""] if r]
                cur.update(
                    end=end,
                    planned=bool(cur["planned"] and o["planned"]),
                    reason="; ".join(dict.fromkeys(reasons)),
                    rows=[*cur.get("rows", []), *o.get("rows", [])],
                )
                cur["_merged"] = True
                continue
        merged.append({**o, "rows": list(o.get("rows", []))})
    for m in merged:
        if m.pop("_merged", False):
            merges.append(tuple(m["rows"]))
    return merged, merges


def parse_log(
    text: str,
    graph: dict,
    mapping: Optional[dict] = None,
    *,
    unit: Optional[str] = None,
    window_start=None,
    window_end=None,
    date_order: str = "auto",
    asset_map: Optional[dict] = None,
) -> dict:
    """Read, check and normalise an outage log against a diagram.

    ``mapping`` maps the fields (asset, start, end or duration, reason,
    planned) to columns; omitted, it is detected from the headers. ``unit``
    is the unit numeric times (and durations) are in — by default the
    diagram's; dates are converted to the diagram's unit, which must then be
    a clock unit. ``window_start`` / ``window_end`` (dates for a dated log,
    numbers otherwise) default to the first outage start and the last record.

    Returns the document fields (``rows``, ``window``, ``origin`` …) plus
    ``columns`` (the table's headers), ``assets`` and ``unmapped``. Raises
    :class:`OutageLogError` listing every bad row, so a fix can be made in one
    go.
    """
    df = read_table(text)
    columns = list(df.columns)
    detected = not mapping
    mapping = _check_mapping(columns, mapping or detect_columns(columns))

    diagram_unit = str((graph or {}).get("unit") or "").strip()
    log_unit = diagram_unit or (str(unit or "").strip())
    notes: list[str] = []
    if detected:
        notes.append("Columns detected from the headers: " + ", ".join(f"{k} = '{v}'" for k, v in mapping.items())
                     + ".")

    errors: list[str] = []
    raw: list[dict] = []
    values_for_order: list[str] = []
    for i, rec in enumerate(df.to_dict("records")):
        row_no = i + 2  # 1-based, after the header row
        asset = str(rec.get(mapping["asset"], "")).strip()
        start = str(rec.get(mapping["start"], "")).strip()
        end = str(rec.get(mapping["end"], "")).strip() if "end" in mapping else ""
        duration = str(rec.get(mapping["duration"], "")).strip() if "duration" in mapping else ""
        if not asset and not start and not end and not duration:
            continue  # a blank line
        if not asset:
            errors.append(f"Row {row_no}: no asset.")
            continue
        if not start:
            errors.append(f"Row {row_no} ({asset}): no outage start.")
            continue
        planned = False
        if "planned" in mapping:
            flag = _parse_planned(rec.get(mapping["planned"], ""))
            if flag is None:
                errors.append(f"Row {row_no} ({asset}): planned is '{rec.get(mapping['planned'])}' — use yes/no "
                              "(or planned/unplanned, 1/0).")
                continue
            planned = flag
        reason = str(rec.get(mapping["reason"], "")).strip() if "reason" in mapping else ""
        raw.append({"row": row_no, "asset": asset, "start": start, "end": end, "duration": duration,
                    "reason": reason[:200], "planned": planned})
        values_for_order += [start, end]

    if not raw and not errors:
        raise OutageLogError("The outage log has no outages.")

    # Numbers or dates: decided over every start and end cell.
    cells = [v for r in raw for v in (r["start"], r["end"]) if v]
    window_cells = [str(w) for w in (window_start, window_end) if w not in (None, "")]
    numeric = all(_number(v) is not None for v in cells)
    time_kind = "number" if numeric else "datetime"

    if time_kind == "number":
        source = time_unit(unit) if unit else None
        target = time_unit(log_unit)
        factor = 1.0
        if unit and log_unit and _norm_name(unit) != _norm_name(log_unit):
            if source is None or target is None:
                raise OutageLogError(
                    f"The times are in {unit_in_text(unit)} but the diagram's unit is {unit_in_text(log_unit)}, "
                    "and one of them isn't a clock "
                    "unit, so they can't be converted. Give the times in the diagram's unit.")
            factor = _unit_factor(source, target)
            notes.append(f"Times converted from {unit_in_text(unit)} to the diagram's unit "
                         f"({unit_in_text(log_unit)}).")
        dur_factor = factor
        origin = None
    else:
        target = time_unit(log_unit)
        if target is None:
            raise OutageLogError(
                (f"The diagram's unit is '{log_unit}', which isn't a clock unit, " if log_unit else
                 "The diagram has no time unit, ")
                + "so dates can't be turned into times on its axis. Set the diagram's unit (hours, days, …) and "
                  "save it, or give the outage times as numbers in the diagram's unit.")
        order, note = choose_date_order(values_for_order + window_cells, date_order)
        if note:
            notes.append(note)
        dur_source = time_unit(unit) if unit else target
        if unit and dur_source is None:
            raise OutageLogError(f"'{unit}' isn't a clock unit for the durations.")
        dur_factor = _unit_factor(dur_source, target)
        factor = None
        origin = None

    def as_time(value: str, what: str, row) -> Optional[Any]:
        if time_kind == "number":
            v = _number(value)
            if v is None:
                errors.append(f"Row {row['row']} ({row['asset']}): {what} '{value}' isn't a number.")
                return None
            return v * factor
        dt = parse_datetime(value, order)
        if dt is None:
            errors.append(f"Row {row['row']} ({row['asset']}): {what} '{value}' isn't a date and time we can "
                          "read — use ISO (2024-03-14 08:30) or day/month/year.")
        return dt

    parsed = []
    for r in raw:
        start = as_time(r["start"], "start", r)
        end = None
        if r["end"]:
            end = as_time(r["end"], "end", r)
            if end is None:
                continue
        elif r["duration"]:
            d = _number(r["duration"])
            if d is None or d < 0:
                errors.append(f"Row {r['row']} ({r['asset']}): duration '{r['duration']}' isn't a time ≥ 0.")
                continue
            if start is not None:
                d = d * dur_factor
                end = start + (d if time_kind == "number" else timedelta(seconds=d * _UNIT_SECONDS[target]))
        if start is None:
            continue
        if end is not None and end < start:
            errors.append(f"Row {r['row']} ({r['asset']}): ends ({r['end'] or r['duration']}) before it starts "
                          f"({r['start']}).")
            continue
        parsed.append({**r, "start": start, "end": end})

    def window_value(value, what):
        if value in (None, ""):
            return None
        if time_kind == "number":
            v = _number(value)
            if v is None:
                raise OutageLogError(f"The window {what} '{value}' isn't a number (the log's times are numbers).")
            return v * factor
        dt = parse_datetime(str(value), order)
        if dt is None:
            raise OutageLogError(f"The window {what} '{value}' isn't a date and time we can read.")
        return dt

    w_start = window_value(window_start, "start")
    w_end = window_value(window_end, "end")

    if errors:
        errors.sort(key=lambda e: int(re.match(r"Row (\d+)", e).group(1)))  # stable: in row order
        shown = errors[:MAX_ERRORS_SHOWN]
        more = len(errors) - len(shown)
        raise OutageLogError(
            f"{len(errors)} row{'s' if len(errors) != 1 else ''} of the outage log can't be read — fix "
            f"{'them' if len(errors) != 1 else 'it'} and import again:\n- " + "\n- ".join(shown)
            + (f"\n- … and {more} more." if more > 0 else ""),
            errors=errors)
    if not parsed:
        raise OutageLogError("The outage log has no outages.")

    starts = [p["start"] for p in parsed]
    ends = [p["end"] if p["end"] is not None else p["start"] for p in parsed]
    first, last = min(starts), max(ends)
    defaulted = []
    if w_start is None:
        w_start = first
        defaulted.append("start (the first outage start)")
    if w_end is None:
        w_end = last
        defaulted.append("end (the last record)")
    if not w_end > w_start:
        raise OutageLogError("The observation window must end after it starts.")
    if defaulted:
        notes.append("Observation window " + " and ".join(defaulted) + " taken from the log; set the window to "
                     "when observation really began and ended for a fair availability.")
    open_rows = [p for p in parsed if p["end"] is None]
    if open_rows and "end (the last record)" in defaulted:
        notes.append(f"{len(open_rows)} outage{'s are' if len(open_rows) != 1 else ' is'} still open and run"
                     f"{'' if len(open_rows) != 1 else 's'} to the window end.")

    # Onto the diagram's axis: datetimes measured from the window start.
    if time_kind == "datetime":
        origin_dt = w_start
        to_num = lambda dt: (dt - origin_dt).total_seconds() / _UNIT_SECONDS[target]  # noqa: E731
        for p in parsed:
            p["start"] = to_num(p["start"])
            p["end"] = None if p["end"] is None else to_num(p["end"])
        window = {"start": 0.0, "end": to_num(w_end)}
        origin = origin_dt.isoformat()
    else:
        window = {"start": float(w_start), "end": float(w_end)}

    # Overlapping outages of one asset merge into one.
    by_asset: dict[str, list] = {}
    for p in parsed:
        by_asset.setdefault(p["asset"], []).append(
            {"start": float(p["start"]), "end": None if p["end"] is None else float(p["end"]),
             "reason": p["reason"], "planned": p["planned"], "rows": [p["row"]]})
    rows: list[dict] = []
    for asset, items in by_asset.items():
        merged, merges = merge_outages(items)
        for rows_merged in merges:
            notes.append(f"{asset}: overlapping outages in rows {', '.join(map(str, rows_merged))} merged into one.")
        for m in merged:
            rows.append({"asset": asset, "start": m["start"], "end": m["end"], "reason": m.get("reason") or "",
                         "planned": bool(m["planned"])})
    rows.sort(key=lambda r: (r["start"], r["asset"]))

    names = list(by_asset)
    amap, unmapped, map_notes, aunits = map_assets(names, graph, asset_map)
    notes += map_notes
    if unmapped:
        notes.append(f"{len(unmapped)} asset{'s' if len(unmapped) != 1 else ''} not matched to a block "
                     f"({', '.join(unmapped[:10])}{'…' if len(unmapped) > 10 else ''}) — their outages are left "
                     "out until mapped.")
    blocks = diagram_blocks(graph)
    unit_notes = _unit_notes(amap, aunits, blocks)
    given, _ = unit_assignment(amap, aunits, blocks)
    assets = [{"name": n, "n_outages": sum(1 for r in rows if r["asset"] == n), "node_id": amap.get(n),
               "label": blocks.get(amap.get(n) or "", {}).get("label"),
               **({"unit": given[n]} if n in given else {})} for n in names]

    return {
        "unit": log_unit,
        "time_kind": time_kind,
        "origin": origin,
        "window": window,
        "rows": rows,
        "asset_map": amap,
        "asset_units": aunits,
        "columns": mapping,
        "notes": notes + unit_notes,
        "unit_notes": unit_notes,
        "headers": columns,
        "assets": assets,
        "unmapped": unmapped,
    }


# ---------------------------------------------------------------------------
# Persistence (owner-only; never on a sample)
# ---------------------------------------------------------------------------

def _now():
    return datetime.now(timezone.utc)


def create_log(db, rbd, parsed: dict, owner_id: str, name: str = "") -> dict:
    """Save a parsed log against ``rbd`` (which ``owner_id`` must own)."""
    if rbd.owner_id != owner_id:
        raise OutageLogError("Outage logs can only be added to your own diagrams.")
    now = _now()
    doc = {
        "_id": uuid.uuid4().hex,
        "owner_id": owner_id,
        "rbd_id": rbd.id,
        "name": (name or "").strip()[:120] or f"Outage log {now:%Y-%m-%d}",
        "created_at": now,
        "updated_at": now,
        **{k: parsed[k] for k in ("unit", "time_kind", "origin", "window", "rows", "asset_map", "columns")},
        # The units' notes are worked out afresh with each history (the
        # diagram or the mapping may change), so they aren't stored.
        "notes": [n for n in parsed["notes"] if n not in (parsed.get("unit_notes") or [])],
        "asset_units": parsed.get("asset_units") or {},
    }
    db.outage_logs.insert_one(doc)
    return doc


def _readable(owners) -> list[str]:
    """Principals whose logs a caller may read: theirs and their teams', never
    the samples' (a log is never shared with a sample or a share)."""
    from backend.config import SAMPLE_OWNER

    return [o for o in access.owner_in(owners) if o != SAMPLE_OWNER]


def list_logs(db, rbd_id: str, owners) -> list[dict]:
    return list(db.outage_logs.find({"rbd_id": rbd_id, "owner_id": {"$in": _readable(owners)}},
                                    {"rows": 0}).sort("created_at", -1))


def get_log(db, log_id: str, owners, rbd_id: Optional[str] = None) -> Optional[dict]:
    query: dict = {"_id": log_id, "owner_id": {"$in": _readable(owners)}}
    if rbd_id:
        query["rbd_id"] = rbd_id
    return db.outage_logs.find_one(query)


def latest_log(db, rbd_id: str, owners) -> Optional[dict]:
    docs = list(db.outage_logs.find({"rbd_id": rbd_id, "owner_id": {"$in": _readable(owners)}})
                .sort("created_at", -1).limit(1))
    return docs[0] if docs else None


def update_log(db, log: dict, graph: dict, *, name=None, asset_map=None, window_start=None,
               window_end=None) -> dict:
    """Rename a log, re-map its assets or move its window (numbers in the
    log's unit, or dates for a dated log). Returns the updated document."""
    changes: dict = {}
    if name is not None:
        changes["name"] = str(name).strip()[:120] or log.get("name")
    if asset_map is not None:
        names = sorted({r["asset"] for r in log.get("rows") or []})
        old_map, old_units = log.get("asset_map") or {}, log.get("asset_units") or {}
        given = {str(k): v for k, v in asset_map.items()}
        # An asset re-sent mapped to the block it was already on keeps its unit
        # (the builder sends plain node ids); one moved elsewhere loses it.
        overrides = {n: (f"{old_map[n]}#{old_units[n]}" if n in old_units and n in old_map
                         and given.get(n, old_map[n]) == old_map[n] else given.get(n, old_map.get(n, "")))
                     for n in names}
        amap, _, _, aunits = map_assets(names, graph, overrides)
        changes["asset_map"] = amap
        changes["asset_units"] = aunits
    if window_start not in (None, "") or window_end not in (None, ""):
        window = dict(log.get("window") or {})
        for key, value in (("start", window_start), ("end", window_end)):
            if value in (None, ""):
                continue
            window[key] = _window_time(log, value, key)
        if not window["end"] > window["start"]:
            raise OutageLogError("The observation window must end after it starts.")
        changes["window"] = window
    if changes:
        changes["updated_at"] = _now()
        db.outage_logs.update_one({"_id": log["_id"], "owner_id": log["owner_id"]}, {"$set": changes})
    return {**log, **changes}


def _window_time(log: dict, value, what: str) -> float:
    if log.get("time_kind") == "datetime":
        if isinstance(value, (int, float)):
            return float(value)
        dt = parse_datetime(str(value), "dmy")
        if dt is None:
            raise OutageLogError(f"The window {what} '{value}' isn't a date and time we can read.")
        origin = datetime.fromisoformat(log["origin"])
        return (dt - origin).total_seconds() / _UNIT_SECONDS[time_unit(log["unit"])]
    v = _number(value)
    if v is None:
        raise OutageLogError(f"The window {what} '{value}' isn't a number.")
    return v


def delete_log(db, log_id: str, owner_id: str) -> bool:
    return db.outage_logs.delete_one({"_id": log_id, "owner_id": owner_id}).deleted_count > 0


def delete_for_rbd(db, rbd_id: str, owner_id: str) -> int:
    return db.outage_logs.delete_many({"rbd_id": rbd_id, "owner_id": owner_id}).deleted_count


def summary(log: dict) -> dict:
    """A log's metadata for lists and responses (no rows)."""
    rows = log.get("rows")
    out = {
        "id": log["_id"],
        "rbd_id": log["rbd_id"],
        "name": log.get("name"),
        "unit": log.get("unit") or "",
        "time_kind": log.get("time_kind"),
        "origin": log.get("origin"),
        "window": log.get("window"),
        "asset_map": log.get("asset_map") or {},
        "asset_units": log.get("asset_units") or {},
        "columns": log.get("columns") or {},
        "notes": log.get("notes") or [],
        "created_at": _iso(log.get("created_at")),
        "updated_at": _iso(log.get("updated_at")),
    }
    if rows is not None:
        out["n_outages"] = len(rows)
        out["assets"] = sorted({r["asset"] for r in rows})
    if log.get("origin"):
        out["window_dates"] = {k: _at(log, v) for k, v in (log.get("window") or {}).items()}
    return out


def _iso(value) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime) and value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _at(log: dict, t: Optional[float]) -> Optional[str]:
    """A log time as an ISO date-time (dated logs), else None."""
    if t is None or not log.get("origin"):
        return None
    unit = time_unit(log.get("unit"))
    if unit is None:
        return None
    origin = datetime.fromisoformat(log["origin"])
    return (origin + timedelta(seconds=float(t) * _UNIT_SECONDS[unit])).isoformat(timespec="minutes")


# ---------------------------------------------------------------------------
# Analysis: RePyability's timelines
# ---------------------------------------------------------------------------

def _structure(graph: dict):
    """The diagram's structure as a RePyability ``RBD`` (no life models: an
    observed history needs none), its blocks, and its vote gates."""
    from repyability import RBD

    nodes = (graph or {}).get("nodes") or []
    edges = [(str(e["source"]), str(e["target"])) for e in (graph or {}).get("edges") or []
             if e.get("source") and e.get("target")]
    if not edges:
        raise OutageLogError("The diagram has no connections, so there's no structure to merge the outages through.")
    ids = {str(n.get("id")) for n in nodes}
    for kind in ("input", "output"):
        if sum(1 for n in nodes if n.get("type") == kind) != 1:
            raise OutageLogError(f"The diagram needs exactly one {kind} node.")
    k: dict[str, int] = {}
    gates: set[str] = set()
    for n in nodes:
        if n.get("type") == "knode":
            nid = str(n.get("id"))
            gates.add(nid)
            try:
                k[nid] = max(int((n.get("data") or {}).get("n") or 1), 1)
            except (TypeError, ValueError):
                raise OutageLogError(f"Vote node “{(n.get('data') or {}).get('label') or nid}”: n must be a whole "
                                     "number.") from None
    try:
        rbd = RBD(edges, k=k or None, input_node="input" if "input" in ids else None,
                  output_node="output" if "output" in ids else None)
    except Exception as exc:  # noqa: BLE001 - RePyability's structure errors
        raise OutageLogError(f"The diagram isn't a valid block diagram: {exc}") from exc
    return rbd, diagram_blocks(graph), gates


def node_outages(log: dict, units: Optional[dict] = None) -> tuple[dict, dict]:
    """``(per node, info)``: each mapped block's outages on the window's axis
    (0 to its length), clipped to the window and merged where two of its
    assets overlap; ``info`` counts what was dropped or merged.

    ``units`` ({asset: unit}, :func:`unit_assignment`) keeps the units of a
    multi-unit block apart (#181): each outage carries its ``unit`` (None on
    a one-unit block) and only one unit's outages merge."""
    w0 = float(log["window"]["start"])
    w1 = float(log["window"]["end"])
    length = w1 - w0
    amap = log.get("asset_map") or {}
    units = units or {}
    per: dict[str, list] = {}
    outside = unmapped = 0
    for i, r in enumerate(log.get("rows") or []):
        nid = amap.get(r["asset"])
        if not nid:
            unmapped += 1
            continue
        start = r["start"] - w0
        end = None if r["end"] is None else r["end"] - w0
        if start >= length or (end is not None and (end < 0 or (end == 0 and start < 0))):
            outside += 1
            continue
        start = max(start, 0.0)
        if end is not None and end >= length:
            end = None  # runs to the window end
        per.setdefault(nid, []).append({"start": start, "end": end, "planned": bool(r.get("planned")),
                                        "reason": r.get("reason") or "", "rows": [i], "asset": r["asset"],
                                        "unit": units.get(r["asset"])})
    merged_nodes = 0
    for nid, items in per.items():
        groups: dict[Any, list] = {}
        for o in items:
            groups.setdefault(o["unit"], []).append(o)
        out = []
        for unit, group in groups.items():
            merged, merges = merge_outages(group)
            merged_nodes += len(merges)
            out += [{**m, "unit": unit} for m in merged]
        per[nid] = sorted(out, key=lambda o: (o["start"], math.inf if o["end"] is None else o["end"]))
    return per, {"length": length, "outside": outside, "unmapped": unmapped, "merged": merged_nodes}


def _outage_timeline(items: list, length: float, name):
    from repyability import Timeline

    if not items:
        return Timeline([], end=length, name=name)
    return Timeline.from_outages([(o["start"], o["end"]) for o in items], end=length,
                                 planned=[o["planned"] for o in items], name=name)


def _block_timeline(nid: str, block: dict, items: list, length: float):
    """``(block timeline, unit timelines)``. A one-unit block's timeline is
    its outages'. A multi-unit block's (#181) is RePyability's k-out-of-n
    merge of its units' — up while at least ``k`` of them are — in series
    with any whole-block outages; ``unit timelines`` is ``{unit: timeline}``
    (empty for a one-unit block)."""
    from repyability.timelines import k_out_of_n, series

    spec = block.get("units")
    if spec is None or all(o.get("unit") in (None, "all") for o in items):
        # One unit, or a block whose assets are all taken whole.
        return _outage_timeline(items, length, nid), {}
    n, k = spec
    unit_tls = {u: _outage_timeline([o for o in items if o.get("unit") == u], length, f"{nid}#{u}")
                for u in range(1, n + 1)}
    merged = k_out_of_n(k, {f"{nid}#{u}": tl for u, tl in unit_tls.items()}, name=nid)
    whole = [o for o in items if o.get("unit") in (None, "all")]
    if whole:
        merged = series({f"{nid}#units": merged, f"{nid}#all": _outage_timeline(whole, length, f"{nid}#all")},
                        name=nid)
    return merged, unit_tls


def _timelines(graph: dict, log: dict):
    from repyability import Timeline

    rbd, blocks, gates = _structure(graph)
    units, problems = unit_assignment(log.get("asset_map") or {}, log.get("asset_units"), blocks)
    if problems:
        raise OutageLogError(" ".join(problems))
    per, info = node_outages(log, units)
    length = info["length"]
    unknown = [nid for nid in per if nid not in blocks]
    if unknown:
        raise OutageLogError(
            f"The log maps assets to block(s) no longer in the diagram ({', '.join(unknown)}). Re-map them.")
    timelines = {}
    unit_timelines: dict[str, dict] = {}
    for nid in blocks:
        items = per.get(nid, [])
        if nid in gates or not items:
            timelines[nid] = Timeline([], end=length, name=nid)
            continue
        timelines[nid], unit_tls = _block_timeline(nid, blocks[nid], items, length)
        if unit_tls:
            unit_timelines[nid] = unit_tls
    info["units"] = unit_timelines
    info["assignment"] = units
    try:
        system = rbd.system_timeline(timelines)
    except ValueError as exc:
        raise OutageLogError(f"Couldn't merge the outages through the diagram: {exc}") from exc
    return system, timelines, blocks, gates, per, info


def _f(v) -> Optional[float]:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _round(v, digits: int = 6):
    v = _f(v)
    return None if v is None else float(f"{v:.{digits}g}")


def system_history(graph: dict, log: dict) -> dict:
    """The diagram's observed history from an outage log.

    Every block's timeline is built from its outages, merged up the diagram
    with ``RBD.system_timeline``, and read back: the system's up/down
    history, its availability over the window, its outages (each with the
    block the library attributes it to — the one whose outage took the
    system down — and the blocks down with it), and per block its own
    downtime and outages and its share of the system's downtime.
    """
    system, timelines, blocks, gates, per, info = _timelines(graph, log)
    length = info["length"]
    w0 = float(log["window"]["start"])

    changes = system.changes.tolist()
    causes = system.causes
    planned = system.planned.tolist()
    outages = []
    # The system starts up (every block does), so its changes alternate down,
    # up, down, …: change 2i takes it down, 2i + 1 brings it back.
    for i in range(0, len(changes), 2):
        start = changes[i]
        restored = i + 1 < len(changes)
        end = changes[i + 1] if restored else length
        cause = causes[i]
        down_with = [nid for nid, tl in timelines.items()
                     if nid != cause and nid not in gates and not tl.state(start)]
        outages.append({
            "n": len(outages) + 1,
            "start": _round(start + w0, 10),
            "end": _round(end + w0, 10),
            "duration": _round(end - start, 10),
            "ongoing": not restored,
            "planned": bool(planned[i]),
            "cause": cause,
            "cause_label": blocks.get(cause, {}).get("label", cause),
            "restored_by": causes[i + 1] if restored else None,
            "down_with": down_with,
            "down_with_labels": [blocks[n]["label"] for n in down_with],
        })
        if log.get("origin"):
            outages[-1]["start_at"] = _at(log, start + w0)
            outages[-1]["end_at"] = _at(log, end + w0)

    total_down = float(system.downtime)
    attributed: dict[str, float] = {}
    caused: dict[str, int] = {}
    for o in outages:
        attributed[o["cause"]] = attributed.get(o["cause"], 0.0) + (o["duration"] or 0.0)
        caused[o["cause"]] = caused.get(o["cause"], 0) + 1
    failures_by_cause = system.failures_by_cause()

    components = []
    for nid, b in blocks.items():
        if nid in gates:
            continue
        tl = timelines[nid]
        down = float(tl.downtime)
        components.append({
            "node_id": nid,
            "label": b["label"],
            "outages": int(tl.failures + tl.planned_outages),
            "failures": int(tl.failures),
            "planned_outages": int(tl.planned_outages),
            "downtime": _round(down, 10),
            "availability": _round(tl.availability),
            "system_outages": caused.get(nid, 0),
            "system_failures": int(failures_by_cause.get(nid, 0)),
            "system_downtime": _round(attributed.get(nid, 0.0), 10),
            "share": _round(attributed.get(nid, 0.0) / total_down) if total_down > 0 else 0.0,
        })
        if nid in info["units"]:
            # A multi-unit block (#181): its record above is the block's (down
            # only while too few units were up); each unit's own is here.
            components[-1]["units_required"] = b["units"][1]
            components[-1]["units"] = [
                {"unit": u, "assets": sorted(a for a, v in info["assignment"].items()
                                             if v == u and (log.get("asset_map") or {}).get(a) == nid),
                 "outages": int(utl.failures + utl.planned_outages), "downtime": _round(float(utl.downtime), 10),
                 "availability": _round(utl.availability)}
                for u, utl in info["units"][nid].items()]
    components.sort(key=lambda c: (-(c["system_downtime"] or 0), -(c["downtime"] or 0), c["label"]))

    n_out = len(outages)
    uptime = float(system.uptime)
    failures = int(system.failures)
    kpis = {
        "window": length,
        "availability": _round(system.availability),
        "uptime": _round(uptime, 10),
        "downtime": _round(total_down, 10),
        "outages": n_out,
        "failures": failures,
        "planned_outages": int(system.planned_outages),
        "mean_downtime": _round(total_down / n_out) if n_out else None,
        "mtbf": _round(uptime / failures) if failures else None,
        "ongoing": bool(outages and outages[-1]["ongoing"]),
    }

    # The step line: the system's state from 0 to the end, on the log's axis.
    xs = [w0]
    ys = [1]
    state = 1
    for t in changes:
        xs += [t + w0]
        state = 1 - state
        ys += [state]
    xs.append(length + w0)
    ys.append(state)

    bars = []
    for nid, items in per.items():
        if nid not in blocks or nid in gates:
            continue
        if nid in info["units"]:
            # A multi-unit block's bars are when the block itself was down.
            tl = timelines[nid]
            flags = tl.planned.tolist()
            for j, (a, b) in enumerate(tl.down_intervals.tolist()):
                bars.append({"node_id": nid, "start": a + w0, "end": b + w0, "planned": bool(flags[2 * j]),
                             "ongoing": 2 * j + 1 >= len(flags)})
            continue
        for o in items:
            end = length if o["end"] is None else o["end"]
            bars.append({"node_id": nid, "start": o["start"] + w0, "end": end + w0, "planned": o["planned"],
                         "ongoing": o["end"] is None})

    notes = list(log.get("notes") or [])
    notes += [n for n in _unit_notes(log.get("asset_map") or {}, log.get("asset_units"), blocks) if n not in notes]
    if info["outside"]:
        one = info["outside"] == 1
        notes.append(f"{info['outside']} outage{'' if one else 's'} fall{'s' if one else ''} outside the "
                     f"observation window and {'is' if one else 'are'} left out.")
    if info["unmapped"]:
        one = info["unmapped"] == 1
        notes.append(f"{info['unmapped']} outage{'' if one else 's'} of unmapped assets {'is' if one else 'are'} "
                     "left out — map their assets to blocks to include them.")
    if info["merged"]:
        one = info["merged"] == 1
        notes.append(f"{info['merged']} overlap{'' if one else 's'} between assets mapped to the same block "
                     f"{'was' if one else 'were'} merged.")
    diagram_unit = str((graph or {}).get("unit") or "").strip()
    if diagram_unit and log.get("unit") and _norm_name(diagram_unit) != _norm_name(log["unit"]):
        notes.append(f"The log's times are in {unit_in_text(log['unit'])}, but the diagram's unit is now "
                     f"{unit_in_text(diagram_unit)}: "
                     "re-import the log in the diagram's unit.")
    if any(b["type"] == "subsystem" for b in blocks.values()):
        notes.append("Sub-system blocks are each taken whole: an outage mapped to one means the whole sub-system "
                     "was down.")

    return {
        "log_id": log.get("_id"),
        "unit": log.get("unit") or "",
        "window": {"start": w0, "end": w0 + length},
        "window_dates": ({"start": _at(log, w0), "end": _at(log, w0 + length)} if log.get("origin") else None),
        "kpis": kpis,
        "outages": outages,
        "components": components,
        "series": {"t": xs, "up": ys},
        "bars": bars,
        "notes": notes,
    }


def lean_history(result: dict, top: int = 10) -> dict:
    """The MCP view: KPIs, the longest outages with their cause, and the
    component ranking (no chart arrays)."""
    worst = sorted(result["outages"], key=lambda o: -(o["duration"] or 0))[:top]
    keep = ("start", "end", "start_at", "end_at", "duration", "ongoing", "planned", "cause_label",
            "down_with_labels")
    return {
        "unit": result["unit"],
        "window": result["window"],
        **({"window_dates": result["window_dates"]} if result.get("window_dates") else {}),
        "kpis": result["kpis"],
        "top_outages": [{("cause" if k == "cause_label" else "down_with" if k == "down_with_labels" else k): o[k]
                         for k in keep if k in o} for o in worst],
        "components": [
            {**{k: c[k] for k in ("label", "node_id", "system_downtime", "share", "system_outages", "downtime",
                                  "outages")},
             **({"units": c["units"], "units_required": c["units_required"]} if c.get("units") else {})}
            for c in result["components"] if c["outages"] or c["system_outages"]
        ],
        "notes": result["notes"],
    }


# ---------------------------------------------------------------------------
# Fitting life and repair models from the log
# ---------------------------------------------------------------------------

def fit_data(graph: dict, log: dict) -> dict:
    """Per block, the lives and repairs its timeline shows: ``{node id:
    {"life": (x, c), "repair": (x, c)}}``. A life is an up period — a failure
    (c = 0) when an unplanned outage ends it, else right-censored (c = 1: cut
    off by the window's end or a planned outage). A repair is an unplanned
    outage's length, right-censored when still open at the window's end.

    A multi-unit block's model is its units' (#181), so its lives and repairs
    are its units' own, pooled — not the block's, which goes down only when
    too few units are up."""
    _, timelines, blocks, gates, per, info = _timelines(graph, log)
    length = info["length"]
    out = {}
    for nid, tl in timelines.items():
        if nid in gates:
            continue
        sources = list(info["units"][nid].values()) if nid in info["units"] else [tl]
        life_x, life_c, rep_x, rep_c = [], [], [], []
        for source in sources:
            lx, lc, rx, rc = _lives_and_repairs(source, length)
            life_x += lx
            life_c += lc
            rep_x += rx
            rep_c += rc
        out[nid] = {"label": blocks[nid]["label"], "life": (life_x, life_c), "repair": (rep_x, rep_c)}
        if nid in info["units"]:
            out[nid]["pooled_units"] = len(sources)
    return out


def _lives_and_repairs(tl, length: float) -> tuple[list, list, list, list]:
    changes = tl.changes.tolist()
    planned = tl.planned.tolist()
    life_x, life_c = [], []
    for a, b in tl.up_intervals.tolist():
        if b - a <= 0:
            continue
        # An up period ends at a change down (index of b among the
        # changes) or at the window's end.
        ended_by_failure = False
        if b < length:
            j = _change_index(changes, b, down=True)
            ended_by_failure = j is not None and not planned[j]
        life_x.append(b - a)
        life_c.append(0 if ended_by_failure else 1)
    rep_x, rep_c = [], []
    for idx, (a, b) in enumerate(tl.down_intervals.tolist()):
        j = 2 * idx  # the change down that opened it
        if j < len(planned) and planned[j]:
            continue
        if b - a <= 0:
            continue
        rep_x.append(b - a)
        rep_c.append(1 if (b >= length and j + 1 >= len(changes)) else 0)
    return life_x, life_c, rep_x, rep_c


def _change_index(changes: list, t: float, down: bool) -> Optional[int]:
    """The index of the change at ``t`` going down (even index) or up (odd)."""
    for j, c in enumerate(changes):
        if c == t and (j % 2 == 0) == down:
            return j
    return None


def fit_models(graph: dict, log: dict, distribution: str = "weibull",
               repair_distribution: str = "lognormal") -> dict:
    """Fit a life model (times between failures) and a repair model (repair
    durations) per block with Reliafy's fitting, from the log. Blocks with
    fewer than two failures (or repairs) aren't fitted and say why. Each
    fitted model comes back in the builder's block-model shape, ready to put
    on the block."""
    from backend import fitting
    from backend.services import rbd_graph

    data = fit_data(graph, log)
    unit = log.get("unit") or ""
    results = []
    for nid, d in data.items():
        entry: dict = {"node_id": nid, "label": d["label"]}
        if d.get("pooled_units"):
            entry["pooled_units"] = d["pooled_units"]
        for key, dist in (("life", distribution), ("repair", repair_distribution)):
            x, c = d[key]
            failures = sum(1 for v in c if v == 0)
            info = {"n": len(x), "failures": failures, "censored": len(x) - failures}
            if failures < 2:
                what = ("failure" if key == "life" else "completed repair") + ("" if failures == 1 else "s")
                info["error"] = f"{failures} {what} in the window — at least 2 are needed to fit."
                entry[key] = info
                continue
            try:
                result = fitting.fit(dist, pd.DataFrame({"x": x, "c": c}), {"x": "x", "c": "c"}, unit=unit)
            except fitting.FitError as exc:
                info["error"] = str(exc)
                entry[key] = info
                continue
            params = [{"name": p.get("name"), "value": p.get("value")} for p in result.get("params") or []]
            model = rbd_graph.normalize_model({"distribution_id": result.get("distribution_id") or dist,
                                               "params": params}, d["label"])
            info.update(distribution=result.get("distribution"), distribution_id=result.get("distribution_id"),
                        params=params, model=model, fit_ok=result.get("fit_ok", True))
            if result.get("fit_warning"):
                info["warning"] = result["fit_warning"]
            entry[key] = info
        results.append(entry)
    return {
        "unit": unit,
        "distribution": distribution,
        "repair_distribution": repair_distribution,
        "components": results,
        "note": ("Lives are the up periods between outages: one ended by an unplanned outage is a failure; one cut "
                 "off by the window's end or a planned outage is right-censored. The first up period counts from "
                 "the window start (its age then is unknown). Repairs are unplanned outages' lengths, "
                 "right-censored when still open. A block of several units (a standby group, a count, a "
                 "load-sharing group) is fitted on its units' own lives and repairs, pooled; a standby spare's "
                 "idle time counts as up time."),
    }
