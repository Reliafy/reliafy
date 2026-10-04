"""Import an RBD from an Excel workbook (``.xlsx``): a block list and how the
blocks connect.

The template (download it from ``GET /api/rbds/import/template.xlsx`` —
:func:`build_template`) has two sheets:

* **Blocks** — one row per block: an ID and/or a name, a block type
  (``component`` when blank; ``k-of-n`` / ``2oo3``; ``standby``; ``series`` /
  ``parallel`` for n identical units), a failure distribution and its
  parameters, and optionally a repair time and the type's extras (required
  branches for k-of-n; spares, dormancy and switch reliability for standby;
  count for series/parallel);
* **Connections** — one row per arrow: from, to (block IDs or names).

A single sheet also works, with a **Feeds** column listing the blocks each
block feeds into (or **Fed by** listing what feeds it). Blocks with nothing
feeding them hang off the diagram's input; blocks feeding nothing go to its
output — so a plain list with no connections at all is read as series (with
a warning).

Parameter columns are named after the parameter (SurPyval's names, with
common synonyms): ``alpha`` (η, scale), ``beta`` (β, shape), ``mu``,
``sigma``, ``failure_rate`` (λ) and ``MTTF``/``MTBF`` (an exponential's mean:
the rate is 1 / MTTF). Supported distributions: see :data:`PARAMS_HELP`.
Repair: ``MTTR`` (exponential repair) or a repair distribution with
``repair alpha`` / ``repair beta`` / ``repair mu`` / ``repair sigma`` /
``repair rate`` columns; the diagram is repairable only when every block
that can fail has one (and only component and k-of-n blocks are used, as for
availability analysis) — otherwise the repair data is dropped with a warning.

A workbook that doesn't look like the template raises
:class:`ExcelNeedsMapping`; the frontend then asks the user to map columns
and calls again with an explicit ``mapping`` (see :func:`parse`).
"""

from __future__ import annotations

import io
import math
import re
from typing import Any, Optional

from backend.services import excel as xl

from .types import ImportedDiagram, RbdImportError

SOURCE_FORMAT = "Excel"
MAX_BLOCKS = 5000

_REF_SPLIT = re.compile(r"[;,\n|]")  # parts are stripped after splitting


class ExcelNeedsMapping(RbdImportError):
    """The workbook isn't laid out like the template: the user must say which
    sheet holds the blocks and which columns mean what."""

    code = "excel_mapping"


def _f(fid: str, label: str, synonyms: list[str], help: str = "", **extra) -> dict:
    return {"id": fid, "label": label, "synonyms": synonyms, "help": help, **extra}


BLOCK_FIELDS = [
    _f("id", "Block ID", ["id", "block id", "ref", "reference", "tag", "key", "code", "block ref", "item id"],
       "What connections refer to. Blank: the name is used.", group="Block"),
    _f("label", "Name", ["name", "block name", "label", "description", "component", "component name",
                         "item", "equipment", "block", "asset"],
       "Shown on the block. Blank: the ID is used.", group="Block"),
    _f("type", "Block type", ["type", "block type", "kind", "node type"],
       "component (blank), k-of-n / 2oo3, standby, series, parallel.", group="Block"),
    _f("distribution", "Failure distribution", ["distribution", "failure distribution", "dist",
                                                 "life distribution", "model", "failure model"],
       "Weibull, Exponential, Lognormal, Normal, Gamma, …", group="Failure model"),
    _f("alpha", "alpha (η, scale)", ["alpha", "α", "eta", "η", "scale", "characteristic life", "weibull scale"],
       group="Failure model"),
    _f("beta", "beta (β, shape)", ["beta", "β", "shape", "weibull shape", "slope"], group="Failure model"),
    _f("mu", "mu (μ)", ["mu", "μ", "location", "log mean"], group="Failure model"),
    _f("sigma", "sigma (σ)", ["sigma", "σ", "std", "std dev", "stdev", "standard deviation", "sd", "log std"],
       group="Failure model"),
    _f("failure_rate", "Failure rate (λ)", ["failure rate", "failure_rate", "lambda", "λ", "rate", "hazard rate"],
       group="Failure model"),
    _f("mean", "MTTF / MTBF", ["mttf", "mtbf", "mean life", "mean time to failure",
                                "mean time between failures", "mean"],
       "Exponential: rate = 1 / MTTF.", group="Failure model"),
    _f("mttr", "MTTR", ["mttr", "mean time to repair", "repair time", "mean repair time", "time to repair"],
       "Exponential repair with this mean.", group="Repair"),
    _f("repair_distribution", "Repair distribution", ["repair distribution", "repair dist", "repair model"],
       group="Repair"),
    _f("repair_alpha", "Repair alpha", ["repair alpha", "repair eta", "repair scale"], group="Repair"),
    _f("repair_beta", "Repair beta", ["repair beta", "repair shape"], group="Repair"),
    _f("repair_mu", "Repair mu", ["repair mu", "repair location"], group="Repair"),
    _f("repair_sigma", "Repair sigma", ["repair sigma", "repair std", "repair sd"], group="Repair"),
    _f("repair_rate", "Repair rate", ["repair rate", "repair lambda"], group="Repair"),
    _f("required", "Required (k of n)", ["required", "k", "min working", "minimum working", "votes required",
                                         "k required", "required working"],
       "k-of-n: how many incoming branches must work.", group="Type extras"),
    _f("total", "Total (n)", ["total", "n", "out of", "n total", "branches"],
       "k-of-n: incoming branches (checked against the connections).", group="Type extras"),
    _f("count", "Count", ["count", "quantity", "qty", "units", "number of units"],
       "series / parallel: identical units in the block.", group="Type extras"),
    _f("spares", "Spares", ["spares", "spare", "spare units", "standby units", "number of spares"],
       "standby: spare units (default 1).", group="Type extras"),
    _f("dormancy", "Dormancy", ["dormancy", "dormancy factor", "standby factor"],
       "standby: 0 cold … 1 hot.", group="Type extras"),
    _f("switch", "Switch reliability", ["switch reliability", "switching probability", "switch probability",
                                        "start probability", "switch"],
       "Cold standby: probability the switch-over works.", group="Type extras"),
    _f("feeds", "Feeds (downstream)", ["feeds", "downstream", "to", "successors", "next", "feeds into",
                                      "outputs to", "connects to", "output to"],
       "Single-sheet layout: blocks this one feeds into.", group="Connections in this sheet"),
    _f("fed_by", "Fed by (upstream)", ["fed by", "upstream", "from", "predecessors", "previous",
                                      "inputs from", "input from"],
       "Single-sheet layout: blocks feeding this one.", group="Connections in this sheet"),
    _f("unit", "Time unit", ["unit", "units", "time unit", "time units"],
       "Hours, cycles, … (the diagram's time axis).", group="Block"),
]

CONNECTION_FIELDS = [
    _f("from", "From", ["from", "source", "upstream", "predecessor", "from block", "start"], required=True),
    _f("to", "To", ["to", "target", "downstream", "successor", "to block", "end"], required=True),
]

PARAMS_HELP = [
    ("Weibull", "alpha (η, scale), beta (β, shape)"),
    ("Exponential", "failure_rate (λ) — or MTTF / MTBF, and λ = 1 / MTTF"),
    ("Lognormal", "mu, sigma (of the log of time)"),
    ("Normal", "mu (mean) and sigma (standard deviation) — or MTTF as the mean"),
    ("Gamma", "alpha (shape), beta (rate)"),
    ("LogLogistic", "alpha (scale), beta (shape)"),
    ("Gumbel / Logistic", "mu, sigma"),
    ("Rayleigh", "sigma"),
    ("Exponentiated Weibull", "alpha, beta, mu"),
]

_BLOCK_SHEETS = ("blocks", "block", "components", "component list", "rbd", "diagram")
_CONNECTION_SHEETS = ("connections", "connection", "links", "edges", "arrows", "wiring")
_SKIP_SHEETS = ("readme", "read me", "instructions", "notes", "help", "about")
_INPUT_REFS = ("input", "in", "start", "source", "begin")
_OUTPUT_REFS = ("output", "out", "end", "sink", "finish")

_DIST_ALIASES = {
    "weibull": "weibull", "wbl": "weibull", "weibull 2p": "weibull", "2p weibull": "weibull",
    "2 parameter weibull": "weibull", "weibull 2 parameter": "weibull",
    "exponential": "exponential", "exp": "exponential", "expon": "exponential",
    "exponential 1p": "exponential", "1p exponential": "exponential",
    "constant failure rate": "exponential", "constant rate": "exponential",
    "normal": "normal", "gaussian": "normal",
    "lognormal": "lognormal", "log normal": "lognormal", "lognorm": "lognormal",
    "gamma": "gamma", "loglogistic": "loglogistic", "log logistic": "loglogistic",
    "gumbel": "gumbel", "logistic": "logistic", "rayleigh": "rayleigh",
    "exponentiated weibull": "expo_weibull", "expo weibull": "expo_weibull", "expoweibull": "expo_weibull",
}


# ---------------------------------------------------------------------------
# Format hooks for the dispatcher
# ---------------------------------------------------------------------------


def sniff(data: bytes, filename: str) -> bool:
    name = (filename or "").lower()
    if name.endswith((".xlsx", ".xlsm", ".xls", ".xlsb", ".ods")):
        return True
    if data[:4] != b"PK\x03\x04":
        return False
    return b"xl/workbook" in data[:65536] or b"[Content_Types].xml" in data[:4096] and b"xl/" in data[:65536]


def parse(data: bytes, filename: str, mapping: Optional[dict] = None) -> list[ImportedDiagram]:
    """One diagram from the workbook — auto-detected when it follows the
    template, else from an explicit ``mapping``::

        {"blocks": {"sheet": "Sheet1", "header_row": 1,
                    "mapping": {"label": "Component", "distribution": "Dist", ...}},
         "connections": {"sheet": "Links", "header_row": 1,
                         "mapping": {"from": "From", "to": "To"}}}   # optional
    """
    base = (filename or "").rsplit("/", 1)[-1]
    stem = (base[:base.rfind(".")] if "." in base else base) or "Imported diagram"
    try:
        if mapping:
            blocks, links = _explicit(data, filename, mapping)
        else:
            blocks, links = _detect(data, filename)
    except xl.ExcelError as exc:
        raise RbdImportError(str(exc)) from None
    graph, warnings = _convert(blocks, links)
    return [ImportedDiagram(name=stem, graph=graph, warnings=warnings, source_format=SOURCE_FORMAT)]


# ---------------------------------------------------------------------------
# Finding the tables
# ---------------------------------------------------------------------------


class _Sheet:
    """A table plus its column mapping, read row by row as field -> value."""

    def __init__(self, table: xl.Table, mapping: dict[str, str]):
        self.table = table
        self.mapping = mapping
        idx = {h: i for i, h in enumerate(table.header)}
        for fid, col in mapping.items():
            if col not in idx:
                raise RbdImportError(f"Sheet “{table.sheet}” has no column “{col}”.")
        self._cols = {fid: idx[col] for fid, col in mapping.items()}

    def records(self):
        for rnum, row in zip(self.table.row_numbers, self.table.rows):
            yield rnum, {fid: row[i] for fid, i in self._cols.items()}


def _is_blocks(guess: dict) -> bool:
    has_name = "id" in guess or "label" in guess
    has_model = any(k in guess for k in ("distribution", "failure_rate", "mean", "alpha", "type"))
    return has_name and has_model


def _detect(data: bytes, filename: str):
    info = xl.inspect(data, filename)
    names = [s["name"] for s in info["sheets"]]
    tables: dict[str, xl.Table] = {}

    def table(name):
        if name not in tables:
            tables[name] = xl.read_table(data, name, None, filename)
        return tables[name]

    candidates = [n for n in names if xl.norm(n) not in _SKIP_SHEETS]
    ordered = ([n for n in candidates if xl.norm(n) in _BLOCK_SHEETS]
               + [n for n in candidates if xl.norm(n) not in _BLOCK_SHEETS + _CONNECTION_SHEETS])
    blocks = None
    for name in ordered:
        try:
            t = table(name)
        except xl.ExcelError:
            continue
        guess = xl.guess_mapping(t.header, BLOCK_FIELDS)
        if _is_blocks(guess):
            blocks = _Sheet(t, guess)
            break
    if blocks is None:
        raise ExcelNeedsMapping(
            "This workbook isn't laid out like Reliafy's RBD template (a Blocks sheet with a "
            "name and a failure distribution per block). Map its columns to continue, or "
            "download the template.")

    links = None
    for name in candidates:
        if name == blocks.table.sheet:
            continue
        try:
            t = table(name)
        except xl.ExcelError:
            continue
        guess = xl.guess_mapping(t.header, CONNECTION_FIELDS)
        if "from" in guess and "to" in guess and (xl.norm(name) in _CONNECTION_SHEETS or links is None):
            links = _Sheet(t, guess)
            if xl.norm(name) in _CONNECTION_SHEETS:
                break
    return blocks, links


def _explicit(data: bytes, filename: str, mapping: dict):
    spec = mapping.get("blocks") if isinstance(mapping, dict) else None
    if not isinstance(spec, dict):
        raise RbdImportError("The column mapping needs a “blocks” sheet.")
    fields = {f["id"] for f in BLOCK_FIELDS}
    cols = {k: v for k, v in (spec.get("mapping") or {}).items() if v and k in fields}
    if "id" not in cols and "label" not in cols:
        raise RbdImportError("Map a column to the block ID or Name.")
    blocks = _Sheet(xl.read_table(data, spec.get("sheet"), _row(spec.get("header_row")), filename), cols)
    links = None
    cspec = mapping.get("connections")
    if isinstance(cspec, dict) and cspec.get("sheet"):
        ccols = {k: v for k, v in (cspec.get("mapping") or {}).items() if v and k in ("from", "to")}
        if len(ccols) != 2:
            raise RbdImportError("Map both the From and To columns of the connections sheet.")
        links = _Sheet(xl.read_table(data, cspec["sheet"], _row(cspec.get("header_row")), filename), ccols)
    return blocks, links


def _row(value) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise RbdImportError("The header row must be a row number.") from None


# ---------------------------------------------------------------------------
# Cells
# ---------------------------------------------------------------------------


def _text(v: Any) -> str:
    return "" if v is None else " ".join(str(v).split())


_THOUSANDS = re.compile(r"^-?\d{1,3}(,\d{3})+(\.\d+)?$")


def _number(v: Any, what: str) -> Optional[float]:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        x = float(v)
    else:
        s = str(v).strip().replace(" ", "")
        if _THOUSANDS.match(s):
            s = s.replace(",", "")
        try:
            x = float(s)
        except ValueError:
            raise RbdImportError(f"{what} “{_text(v)}” isn't a number.") from None
    if not math.isfinite(x):
        raise RbdImportError(f"{what} must be a finite number.")
    return x


def _positive(v: Any, what: str) -> Optional[float]:
    x = _number(v, what)
    if x is not None and x <= 0:
        raise RbdImportError(f"{what} must be greater than zero (got {x:g}).")
    return x


def _whole(v: Any, what: str, minimum: int) -> Optional[int]:
    x = _number(v, what)
    if x is None:
        return None
    if x != int(x) or x < minimum:
        raise RbdImportError(f"{what} must be a whole number ≥ {minimum} (got {x:g}).")
    return int(x)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


def _dist_id(raw: str, where: str) -> str:
    from backend import fitting

    key = xl.norm(raw)
    if key in _DIST_ALIASES:
        return _DIST_ALIASES[key]
    if "3p" in key.split() or "3 parameter" in key:
        raise RbdImportError(
            f"{where}: 3-parameter (offset) distributions aren't supported in the template — "
            "give a 2-parameter fit.")
    try:
        return fitting.resolve_distribution_id(raw)
    except fitting.FitError:
        names = ", ".join(n for n, _ in PARAMS_HELP)
        raise RbdImportError(f"{where}: unsupported distribution “{raw}”. Use one of: {names}.") from None


def _model(rec: dict, where: str, prefix: str = "") -> Optional[dict]:
    """``{distribution_id, params}`` from a row, or None when it has none.

    ``prefix`` = ``"repair_"`` reads the repair columns (``repair_rate`` is
    the repair's failure_rate; ``mttr`` its mean)."""
    from backend import fitting

    def val(name):
        key = prefix + ("rate" if prefix and name == "failure_rate" else name)
        return rec.get(key)

    mean_key = "mttr" if prefix else "mean"
    raw_dist = _text(rec.get(prefix + "distribution"))
    given = {p: val(p) for p in ("alpha", "beta", "mu", "sigma", "failure_rate")}
    given = {k: v for k, v in given.items() if v not in (None, "")}
    mean = rec.get(mean_key)
    mean = None if mean in (None, "") else mean
    what = "Repair" if prefix else "Failure"
    if not raw_dist:
        if not given and mean is None:
            return None
        if set(given) <= {"failure_rate"}:
            dist = "exponential"
        elif set(given) >= {"alpha", "beta"} and not set(given) & {"mu", "sigma"}:
            dist = "weibull"
        else:
            raise RbdImportError(
                f"{where}: say which {what.lower()} distribution the parameters belong to "
                f"(the {prefix + 'distribution' if prefix else 'distribution'} column is blank).")
    else:
        dist = _dist_id(raw_dist, where)
    names = list(getattr(fitting.DISTRIBUTIONS[dist]["dist"], "parameter_names", []))
    params = []
    for name in names:
        v = given.get(name)
        label = f"{where}: {what.lower()} {name}"
        if v is None and mean is not None and dist == "exponential" and name == "failure_rate":
            params.append({"name": name, "value": 1.0 / _positive(mean, f"{where}: {'MTTR' if prefix else 'MTTF'}")})
            continue
        if v is None and mean is not None and dist == "normal" and name == "mu":
            v = mean
        if v is None:
            need = " and ".join(names)
            hint = " (or MTTR)" if prefix and dist == "exponential" else " (or MTTF)" if dist == "exponential" else ""
            raise RbdImportError(f"{where}: a {fitting.DISTRIBUTIONS[dist]['name']} {what.lower()} model needs "
                                 f"{need}{hint} — the {name} cell is blank.")
        x = _number(v, label) if name == "mu" else _positive(v, label)
        params.append({"name": name, "value": x})
    return {"distribution_id": dist, "params": params}


# ---------------------------------------------------------------------------
# Block types
# ---------------------------------------------------------------------------

_KOFN = re.compile(r"^(\d+)\s*(?:oo|of|out of|out of n|/)\s*(\d+)$")


def _block_type(raw: str, where: str) -> tuple[str, dict]:
    """``(node type, extras)`` — extras carry what the type word implies."""
    t = xl.norm(raw)
    if t in ("", "component", "block", "basic", "basic event", "unit", "item", "equipment", "c"):
        return "component", {}
    m = _KOFN.match(t) or _KOFN.match(str(raw).strip().lower())
    if m:
        return "knode", {"required": int(m.group(1)), "total": int(m.group(2))}
    if t in ("k of n", "kofn", "k out of n", "koon", "k oo n", "voting", "vote", "voter", "knode",
             "k n", "n of k", "voting node", "voting gate", "k of n node", "n out of k"):
        return "knode", {}
    if t in ("junction", "node", "join", "splitter"):
        return "knode", {"required": 1}
    if t in ("standby", "spare", "standby redundancy", "redundant standby", "cold standby", "cold spare"):
        return "standby", {"dormancy": 0.0} if "cold" in t else {}
    if t in ("warm standby", "warm spare"):
        return "standby", {"warm": True}
    if t in ("hot standby", "hot spare"):
        return "standby", {"dormancy": 1.0}
    if t in ("series", "series block", "in series"):
        return "series", {}
    if t in ("parallel", "parallel block", "in parallel", "active parallel", "redundant", "active redundancy"):
        return "parallel", {}
    raise RbdImportError(
        f"{where}: unknown block type “{raw}” — use component, k-of-n (or e.g. 2oo3), standby, "
        "series or parallel.")


# ---------------------------------------------------------------------------
# Conversion
# ---------------------------------------------------------------------------


def _key(s: str) -> str:
    return " ".join(str(s).split()).casefold()


def _convert(blocks: _Sheet, links: Optional[_Sheet]) -> tuple[dict, list[str]]:
    warnings: list[str] = []
    nodes: list[dict] = []
    by_ref: dict[str, list[str]] = {}   # id / label (casefolded) -> node ids
    rows: dict[str, dict] = {}          # node id -> record
    order: list[str] = []
    ids_seen: dict[str, int] = {}
    units: list[str] = []
    skipped = 0

    for rnum, rec in blocks.records():
        bid, label = _text(rec.get("id")), _text(rec.get("label"))
        if not bid and not label:
            if any(v not in (None, "") for v in rec.values()):
                skipped += 1
            continue
        if len(nodes) >= MAX_BLOCKS:
            raise RbdImportError(f"The sheet has more than {MAX_BLOCKS:,} blocks — too many to import.")
        ref = bid or label
        if bid:
            if _key(bid) in ids_seen:
                raise RbdImportError(
                    f"Block ID “{bid}” is used twice (rows {ids_seen[_key(bid)]} and {rnum}) — IDs must be unique.")
            ids_seen[_key(bid)] = rnum
        # The sheet's own ID when it makes a safe node id, else a numbered one.
        nid = re.sub(r"[^A-Za-z0-9_-]+", "_", ref).strip("_")[:40]
        if not nid or nid.lower() in ("input", "output") or nid in rows:
            nid = f"b{len(nodes) + 1}"
            while nid in rows:
                nid += "_"
        where = f"Block “{label or bid}” (row {rnum})"
        ntype, implied = _block_type(_text(rec.get("type")), where)
        node: dict = {"id": nid, "type": ntype, "label": label or bid}
        model = _model(rec, where)
        if ntype == "knode":
            if model is not None:
                warnings.append(f"{where} is a k-of-n voting node, which has no failure model — its distribution was ignored.")
            required = implied.get("required")
            if required is None:
                required = _whole(rec.get("required"), f"{where}: required", 1) or 1
            node["n"] = required
            node["_total"] = implied.get("total") or _whole(rec.get("total"), f"{where}: total", 1)
        else:
            if model is None:
                raise RbdImportError(f"{where} has no failure distribution — fill in the distribution and its parameters.")
            node["model"] = model
            if ntype in ("series", "parallel"):
                count = _whole(rec.get("count"), f"{where}: count", 1)
                if count is None:
                    raise RbdImportError(f"{where} is a {ntype} block: give its Count (how many identical units).")
                node["n"] = count
            elif ntype == "standby":
                spares = _whole(rec.get("spares"), f"{where}: spares", 1)
                node["spares"] = spares or 1
                dormancy = _number(rec.get("dormancy"), f"{where}: dormancy")
                if dormancy is None:
                    dormancy = implied.get("dormancy")
                if dormancy is None:
                    dormancy = 0.5 if implied.get("warm") else 0.0
                    if implied.get("warm"):
                        warnings.append(f"{where} is a warm standby with no dormancy factor — 0.5 was used.")
                if not 0.0 <= dormancy <= 1.0:
                    raise RbdImportError(f"{where}: the dormancy factor must be from 0 (cold) to 1 (hot).")
                node["dormancy"] = dormancy
                node["cold"] = dormancy == 0.0
                switch = _number(rec.get("switch"), f"{where}: switch reliability")
                if switch is not None:
                    if not 0.0 < switch <= 1.0:
                        raise RbdImportError(f"{where}: the switch reliability must be a probability (0–1].")
                    if dormancy == 0.0:
                        node["startProb"] = switch
                    else:
                        warnings.append(f"{where}: a switch reliability applies to cold standby only — ignored.")
            count = _number(rec.get("count"), f"{where}: count")
            if ntype == "component" and count not in (None, 1):
                warnings.append(
                    f"{where} has count {count:g}, which a component block ignores — set its type to "
                    "parallel or series for identical units.")
        repair = _model(rec, where, prefix="repair_")
        if repair is not None:
            node["_repair"] = repair
        if _text(rec.get("unit")):
            units.append(_text(rec.get("unit")))
        nodes.append(node)
        rows[nid] = rec
        order.append(nid)
        by_ref.setdefault(_key(ref), []).append(nid)
        if bid and label and _key(label) != _key(bid):
            by_ref.setdefault(_key(label), []).append(nid)

    if not nodes:
        raise RbdImportError(f"No blocks found on sheet “{blocks.table.sheet}” — each block needs an ID or a name.")
    if skipped:
        warnings.append(f"{skipped} row{'s' if skipped != 1 else ''} with no block ID or name {'were' if skipped != 1 else 'was'} skipped.")

    def resolve(raw: Any, where: str) -> list[str]:
        text = _text(raw)
        if not text:
            return []
        parts = [text] if _key(text) in by_ref or _special(text) else [p for p in (q.strip() for q in _REF_SPLIT.split(text)) if p]
        out = []
        for p in parts:
            hits = by_ref.get(_key(p))
            if hits:
                if len(set(hits)) > 1:
                    raise RbdImportError(f"{where}: “{p}” names more than one block — refer to blocks by a unique ID.")
                out.append(hits[0])
            elif _special(p):
                out.append(_special(p))
            else:
                raise RbdImportError(f"{where}: “{p}” isn't a block in the sheet.")
        return out

    edges: list[tuple[str, str]] = []
    for nid in order:
        rec = rows[nid]
        where = f"Block “{next(n['label'] for n in nodes if n['id'] == nid)}”"
        for t in resolve(rec.get("feeds"), f"{where} feeds"):
            edges.append((nid, t))
        for s in resolve(rec.get("fed_by"), f"{where} fed by"):
            edges.append((s, nid))
    if links is not None:
        for rnum, rec in links.records():
            where = f"Connections row {rnum}"
            srcs, tgts = resolve(rec.get("from"), where), resolve(rec.get("to"), where)
            if not srcs and not tgts:
                continue
            if not srcs or not tgts:
                raise RbdImportError(f"{where}: needs both a From and a To.")
            edges.extend((s, t) for s in srcs for t in tgts)

    seen, unique = set(), []
    for s, t in edges:
        if s == t:
            raise RbdImportError(f"Block “{_label(nodes, s)}” is connected to itself.")
        if s == "output" or t == "input":
            raise RbdImportError("Connections can't lead out of the output or into the input.")
        if (s, t) in seen:
            continue
        seen.add((s, t))
        unique.append((s, t))
    if len(unique) < len(edges):
        n = len(edges) - len(unique)
        warnings.append(f"{n} repeated connection{'s were' if n != 1 else ' was'} ignored.")
    edges = unique

    if not edges and len(order) > 1:
        edges = list(zip(order, order[1:]))
        warnings.append(
            "No connections were found (no Connections sheet or Feeds column), so the blocks "
            "were connected in series, in the order listed.")
    has_in = {t for _, t in edges}
    has_out = {s for s, _ in edges}
    for nid in order:
        if nid not in has_in:
            edges.append(("input", nid))
        if nid not in has_out:
            edges.append((nid, "output"))
    _check_acyclic(order, edges, nodes)

    # k-of-n totals come from the wiring.
    inbound: dict[str, int] = {}
    for _, t in edges:
        inbound[t] = inbound.get(t, 0) + 1
    for node in nodes:
        total = node.pop("_total", None)
        if node["type"] != "knode":
            continue
        k = inbound.get(node["id"], 0)
        if total is not None and total != k:
            warnings.append(
                f"Voting node “{node['label']}” says {total} branches but has {k} incoming "
                f"connection{'s' if k != 1 else ''}; {k} was used.")
        if node["n"] > k:
            raise RbdImportError(
                f"Voting node “{node['label']}” needs {node['n']} working branches but only "
                f"{k} connect into it.")
        node["k"] = k

    # Repair: all or nothing, and only where availability analysis applies.
    failing = [n for n in nodes if n["type"] != "knode"]
    with_repair = [n for n in failing if n.get("_repair")]
    repairable = False
    if with_repair:
        missing = [n["label"] for n in failing if not n.get("_repair")]
        other = sorted({n["type"] for n in failing if n["type"] != "component"})
        if missing:
            warnings.append(
                "Repair data was dropped and the diagram imported as non-repairable: not every "
                f"block has a repair time (missing: {_names(missing)}).")
        elif other:
            warnings.append(
                "Repair data was dropped and the diagram imported as non-repairable: "
                f"availability analysis doesn't support {', '.join(other)} blocks.")
        else:
            repairable = True
    for n in nodes:
        rep = n.pop("_repair", None)
        if repairable and rep is not None:
            n["repair"] = rep

    unit = ""
    if units:
        distinct = list(dict.fromkeys(u for u in units))
        unit = distinct[0]
        if len({_key(u) for u in distinct}) > 1:
            warnings.append(f"Blocks give different time units ({', '.join(distinct[:5])}); the diagram uses “{unit}”.")

    graph = {
        "nodes": [{"id": "input", "type": "input"}, *nodes, {"id": "output", "type": "output"}],
        "edges": [{"source": s, "target": t} for s, t in edges],
        "unit": unit,
    }
    if repairable:
        graph["repairable"] = True
    return graph, warnings


def _special(ref: str) -> Optional[str]:
    k = xl.norm(ref)
    if k in _INPUT_REFS:
        return "input"
    if k in _OUTPUT_REFS:
        return "output"
    return None


def _label(nodes: list[dict], nid: str) -> str:
    return next((n["label"] for n in nodes if n["id"] == nid), nid)


def _names(items: list[str], limit: int = 6) -> str:
    shown = ", ".join(f"“{s}”" for s in items[:limit])
    return shown + (f" and {len(items) - limit} more" if len(items) > limit else "")


def _check_acyclic(order: list[str], edges: list[tuple[str, str]], nodes: list[dict]) -> None:
    adj: dict[str, list[str]] = {}
    for s, t in edges:
        adj.setdefault(s, []).append(t)
    state: dict[str, int] = {}
    for start in ["input", *order]:
        if state.get(start):
            continue
        stack = [(start, iter(adj.get(start, ())))]
        state[start] = 1
        while stack:
            node, it = stack[-1]
            nxt = next(it, None)
            if nxt is None:
                state[node] = 2
                stack.pop()
                continue
            if state.get(nxt) == 1:
                raise RbdImportError(
                    f"The connections form a loop through “{_label(nodes, nxt)}” — a block diagram "
                    "flows one way, from input to output.")
            if not state.get(nxt):
                state[nxt] = 1
                stack.append((nxt, iter(adj.get(nxt, ()))))


# ---------------------------------------------------------------------------
# Downloadable template
# ---------------------------------------------------------------------------

TEMPLATE_BLOCK_HEADER = ["ID", "Name", "Type", "Distribution", "alpha", "beta", "mu", "sigma",
                         "failure_rate", "MTTF", "Required", "Spares", "Dormancy", "MTTR", "Unit"]
TEMPLATE_BLOCKS = [
    ["F1", "Intake filter", "component", "Weibull", 8000, 1.8, None, None, None, None, None, None, None, None, "Hours"],
    ["P1", "Pump A", "component", "Weibull", 5000, 1.4, None, None, None, None, None, None, None, None, "Hours"],
    ["P2", "Pump B", "component", "Weibull", 5000, 1.4, None, None, None, None, None, None, None, None, "Hours"],
    ["P3", "Pump C", "component", "Weibull", 5000, 1.4, None, None, None, None, None, None, None, None, "Hours"],
    ["V", "2 of 3 pumps", "k-of-n", None, None, None, None, None, None, None, 2, None, None, None, None],
    ["C", "Controller", "standby", "Exponential", None, None, None, None, None, 20000, None, 1, 0, None, "Hours"],
    ["OV", "Outlet valve", "component", "Lognormal", None, None, 9.2, 0.6, None, None, None, None, None, None, "Hours"],
]
TEMPLATE_CONNECTIONS = [["F1", "P1"], ["F1", "P2"], ["F1", "P3"], ["P1", "V"], ["P2", "V"], ["P3", "V"],
                        ["V", "C"], ["C", "OV"]]


def _readme() -> list[list[str]]:
    rows = [
        ["Reliafy RBD import template"],
        [""],
        ["Fill in the Blocks and Connections sheets, save, and import the workbook on the RBDs page (Import)."],
        ["The example is a filter feeding three pumps (any 2 of 3 must work), then a controller with a cold spare and an outlet valve."],
        ["Replace it with your own blocks. Rows can be in any order; blank rows are ignored."],
        [""],
        ["Blocks sheet — one row per block"],
        ["ID", "Short reference used by Connections. Unique. Blank: the Name is used."],
        ["Name", "Shown on the block."],
        ["Type", "component (default when blank) · k-of-n (or 2oo3 / 2 of 3) · standby (cold / warm / hot standby) · series · parallel"],
        ["Distribution", "The failure distribution — see the table below. Blank with only failure_rate or MTTF means Exponential."],
        ["alpha … MTTF", "The distribution's parameters, one column each (leave the others blank)."],
        ["Required", "k-of-n only: how many of the incoming branches must work (default 1 — a plain junction)."],
        ["Spares", "standby only: number of spare units (default 1)."],
        ["Dormancy", "standby only: 0 = cold (spares don't age), 1 = hot, in between = warm (default 0)."],
        ["Count", "series / parallel only (add the column): how many identical units the block stands for."],
        ["Switch reliability", "cold standby only (add the column): probability the switch-over works."],
        ["MTTR", "Optional mean time to repair (exponential repair). Give it for every block to import a repairable (availability) diagram."],
        ["Repair distribution", "Optional instead of MTTR, with Repair alpha / Repair beta / Repair mu / Repair sigma / Repair rate columns."],
        ["Unit", "The time unit of the parameters (Hours, Cycles, …). One unit per diagram."],
        [""],
        ["Connections sheet — one row per arrow"],
        ["From", "The upstream block (ID or name)."],
        ["To", "The downstream block (ID or name)."],
        ["", "Blocks with nothing feeding them connect from the diagram's input; blocks feeding nothing connect to its output."],
        ["", "Single sheet instead? Add a Feeds column to Blocks listing the blocks each one feeds into (comma-separated)."],
        [""],
        ["Distributions and their parameter columns"],
    ]
    rows += [[name, params] for name, params in PARAMS_HELP]
    rows += [
        [""],
        ["Notes"],
        ["", "Formulas are fine — Reliafy reads the values Excel last calculated and saved."],
        ["", "Different column names work too: if Reliafy doesn't recognise the layout it asks you to map the columns."],
    ]
    return rows


def build_template() -> bytes:
    """The example workbook offered for download (README, Blocks, Connections)."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = Workbook()
    readme = wb.active
    readme.title = "README"
    bold = Font(bold=True)
    for row in _readme():
        readme.append(row)
    readme["A1"].font = Font(bold=True, size=14)
    for r in readme.iter_rows(min_row=2):
        cell = r[0]
        if cell.value and len(r) > 1 and not (r[1].value if len(r) > 1 else None):
            cell.font = bold
    readme.column_dimensions["A"].width = 24
    readme.column_dimensions["B"].width = 110
    for r in readme.iter_rows():
        for c in r:
            c.alignment = Alignment(wrap_text=True, vertical="top")

    head_fill = PatternFill("solid", fgColor="E8EEFB")

    def sheet(title, header, rows, widths):
        ws = wb.create_sheet(title)
        ws.append(header)
        for row in rows:
            ws.append(row)
        for i, cell in enumerate(ws[1]):
            cell.font = bold
            cell.fill = head_fill
            ws.column_dimensions[cell.column_letter].width = widths[i] if i < len(widths) else 12
        ws.freeze_panes = "A2"
        return ws

    sheet("Blocks", TEMPLATE_BLOCK_HEADER, TEMPLATE_BLOCKS,
          [8, 18, 12, 14, 10, 8, 8, 8, 12, 10, 10, 8, 10, 8, 9])
    sheet("Connections", ["From", "To"], TEMPLATE_CONNECTIONS, [12, 12])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
