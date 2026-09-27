"""Import ReliaSoft BlockSim / Synthesis project files.

A BlockSim project (``.rsrp``, ``.rsr9`` … ``.rsrNN``) is a Microsoft Access
(Jet 4) database; the "packed" form (``.rsgz9`` … ``.rsgzNN``) is the same
database gzipped. The importer works in three steps, each testable alone:

1. :func:`read_tables` — the handful of tables we need, as lists of row dicts
   (via ``access_parser``, a pure-Python Jet reader, fed from memory).
2. :func:`extract_project` — tables -> a plain, JSON-like *project* dict (the
   intermediate form; the diagram drawings are decoded from their .NET
   ``BinaryFormatter`` blobs here, see :mod:`.nrbf`)::

       {"units":    {id: {"name", "multiplier", "category"}},
        "models":   {id: {"name", "type", "unit", "params": {param_id: value}}},
        "urds":     {id: {"name", "model", "task", "scheduled_tasks"}},
        "tasks":    {id: {"name", "duration_model", "restoration", "pool", "crews"}},
        "switches": {id: {"name", "p_switch", "quiescent_model", "delay"}},
        "diagrams": [{"id", "name", "kind": "rbd"|"ft", "simulation",
                      "blocks": {block_id: {...}}, "edges": [[src, dst], ...],
                      "containers": {container_id: [[member_id, ...], ...]}}]}

3. :func:`convert_project` — project -> one Reliafy compact graph per diagram.

What maps, and how (the tests' module docstring has the evidence):

* Blocks with a failure model -> ``component``; blocks with no model (BlockSim's
  "Start"/"End" style non-failing blocks, junctions) and Node blocks ->
  ``knode`` (``n`` = paths required), which then collapse into Reliafy's
  input/output or a neighbour where that's exactly equivalent.
* Subdiagram blocks are inlined (their labels prefixed with the block name);
  every folio is also imported as a diagram of its own.
* Fault-tree folios become their success-space RBD: OR gate -> series, AND ->
  parallel, k-failures vote over m inputs -> (m - k + 1)-of-m.
* Standby containers -> ``standby`` when there is one active unit and the
  spares share a model (dormant failure model: none -> cold, same as active ->
  hot, other -> hot with a warning). Load-sharing containers of identical
  exponential units -> one block with the exact Gamma(n - k + 1, lambda) life;
  any other load-sharing container -> a conservative independent k-of-n.
* All stored times are in hours (the category's base unit); a model's unit is
  its display unit, and the diagram takes the most common one.
* Weibull (1/2-parameter), exponential (1-parameter), normal and lognormal
  models are decoded; other ReliaSoft models are left for the user to set
  (the block imports without a model and a warning lists the raw values).
* Repair: a simulation diagram in which every block has a corrective task with
  a decodable duration is imported as ``repairable``; otherwise repair data is
  dropped with a warning.
"""

from __future__ import annotations

import logging
import math
import re
import zlib
from collections import Counter
from typing import Any, Optional

from .nrbf import NrbfError, parse_streams
from .types import MAX_DECOMPRESSED_BYTES, ImportedDiagram, RbdImportError

LOG = logging.getLogger(__name__)

SOURCE_FORMAT = "ReliaSoft BlockSim"

_GZIP_MAGIC = b"\x1f\x8b"
_JET_MAGICS = (b"Standard Jet DB", b"Standard ACE DB")
_EXT_RE = re.compile(r"\.(rsgz\d*|rsr\d*|rsrp)$", re.IGNORECASE)

# A single NRBF blob inside the database (a diagram drawing) is small; cap it.
_MAX_BLOB_BYTES = 32 * 1024 * 1024
# Guards on the converted graph.
_MAX_NODES = 5000
_MAX_SUBDIAGRAM_DEPTH = 25

# BlockDataType enumeration (ReliaSoft Synthesis API).
BT_REGULAR, BT_NODE, BT_SUBDIAGRAM, BT_JUNCTION = 0, 1, 2, 3
BT_STANDBY, BT_LOADSHARE = 4, 5
BT_GATE_AND, BT_GATE_OR, BT_GATE_VOTE = 20, 21, 22
BT_IN_STANDBY, BT_IN_LOADSHARE = 101, 102
BT_ANNOTATION = 90
_GATE_NAMES = {23: "inhibit", 24: "NOT", 25: "XOR", 26: "NAND", 27: "NOR"}
_OTHER_BLOCK_NAMES = {50: "operational phase", 51: "maintenance phase", 52: "phase subdiagram",
                      53: "phase node", 54: "phase stop"}

# ModelTypeEnum (ReliaSoft Synthesis API).
MODEL_TYPE_NAMES = {
    0: "fixed unreliability", 1: "fixed duration", 2: "fixed cost", 3: "diagram analysis",
    100: "1-parameter Weibull", 101: "2-parameter Weibull", 102: "3-parameter Weibull",
    103: "mixed Weibull (2 subpopulations)", 104: "mixed Weibull (3 subpopulations)",
    105: "mixed Weibull (4 subpopulations)", 106: "1-parameter exponential",
    107: "2-parameter exponential", 108: "normal", 109: "lognormal",
    110: "generalized gamma", 111: "gamma", 112: "logistic", 113: "loglogistic",
    114: "Gumbel",
}

# rsModelParam.ParameterID for the model types whose storage has been decoded
# (cross-checked against published values in ReliaSoft's example projects — see
# the module docstring of the tests). ``unit_param`` is the trailing parameter
# every single-population model carries; it is 1.0 in every stored model we've
# seen, and a model with any other value there is not imported (its meaning —
# most likely the fraction of the population that can fail — isn't confirmed).
_W_BETA, _W_ETA, _W_UNIT = 1000, 1001, 1002
_E_MEAN, _E_UNIT = 1033, 1034
_N_MEAN, _N_STD, _N_UNIT = 1037, 1038, 1039
_LN_MEAN, _LN_STD, _LN_UNIT = 1040, 1041, 1042
_DECODED = {
    100: ({_W_BETA, _W_ETA}, _W_UNIT),
    101: ({_W_BETA, _W_ETA}, _W_UNIT),
    106: ({_E_MEAN}, _E_UNIT),
    108: ({_N_MEAN, _N_STD}, _N_UNIT),
    109: ({_LN_MEAN, _LN_STD}, _LN_UNIT),
}

# ReliaSoft unit name -> the builder's unit label.
_UNIT_LABELS = {
    "second": "Seconds", "minute": "Minutes", "hour": "Hours", "day": "Days",
    "week": "Weeks", "month": "Months", "year": "Years", "cycle": "Cycles",
}


# ---------------------------------------------------------------------------
# Sniffing and decompression
# ---------------------------------------------------------------------------

def _is_jet(head: bytes) -> bool:
    return head[4:19] in _JET_MAGICS


def sniff(data: bytes, filename: str) -> bool:
    if _is_jet(data[:32]):
        return True
    if data[:2] == _GZIP_MAGIC:
        try:
            d = zlib.decompressobj(16 + zlib.MAX_WBITS)
            head = d.decompress(data[:65536], 64)
        except zlib.error:
            head = b""
        if _is_jet(head):
            return True
    return bool(_EXT_RE.search(filename or ""))


class _Inflater:
    """gunzip with a shared output budget (no gzip bombs)."""

    def __init__(self, budget: int = MAX_DECOMPRESSED_BYTES):
        self.budget = budget

    def gunzip(self, data: bytes, limit: Optional[int] = None) -> bytes:
        limit = min(limit or self.budget, self.budget)
        d = zlib.decompressobj(16 + zlib.MAX_WBITS)
        out = bytearray()
        buf = data
        try:
            while True:
                chunk = d.decompress(buf, 1 << 20)
                out += chunk
                if len(out) > limit:
                    raise RbdImportError(
                        "This file expands to more data than Reliafy will read "
                        f"({limit // (1024 * 1024)} MB) — export just the project that holds the diagram."
                    )
                if d.eof:
                    break
                buf = d.unconsumed_tail
                if not buf and not chunk:
                    break
        except zlib.error as exc:
            raise RbdImportError(f"The compressed data in this file is damaged ({exc}).") from None
        if not d.eof:
            raise RbdImportError("The file is truncated — the compressed data ends early. Re-export it and try again.")
        self.budget -= len(out)
        return bytes(out)


# ---------------------------------------------------------------------------
# Step 1: the Access database -> tables
# ---------------------------------------------------------------------------

TABLES = (
    "rsProject", "rsFolio", "bsFolioRBD", "bsFolioFaultTree", "bsBlockStructure",
    "bsBlockLocalData", "bsBlockLocalDataOfStructure", "rsRamo", "rsModel",
    "rsModelParam", "rsUnit", "rsTaskCorrective", "rsTaskCorrectiveCrew",
    "rsRamoTask", "bsSwitch",
)


def _jet_classes():
    """Subclasses of access_parser's reader that work from bytes in memory and
    can't loop forever on a crafted file (bounded memo/overflow page walks)."""
    import struct

    from access_parser import access_parser as ap

    class SafeTable(ap.AccessTable):
        def _merge_table_data(self, first_page):
            seen, data, page = set(), b"", first_page
            while page:
                if page in seen or len(seen) > 4096:
                    raise ValueError("table definition pages loop")
                seen.add(page)
                table = self._table_defs.get(page * self.page_size)
                if table is None:
                    raise ValueError("missing table definition page")
                header = ap.TDEF_HEADER.parse(table)
                data += table[header.header_end:]
                page = header.next_page_ptr
            return data

        def _parse_memo(self, relative_obj_data, return_raw=False):
            parsed = ap.MEMO.parse(relative_obj_data)
            length = parsed.memo_length
            if length & 0x80000000:
                n = length & 0x3FFFFFFF
                memo = relative_obj_data[parsed.memo_end:parsed.memo_end + n]
            elif length & 0x40000000:
                memo = self._get_overflow_record(parsed.record_pointer) or b""
            else:
                memo, seen, ptr = b"", set(), parsed.record_pointer
                while ptr:
                    if ptr in seen or len(seen) > len(self._data_pages) + 1:
                        raise ValueError("long-value pages loop")
                    seen.add(ptr)
                    rec = self._get_overflow_record(ptr)
                    if not rec or len(rec) < 4:
                        raise ValueError("missing long-value page")
                    ptr = struct.unpack("<I", rec[:4])[0]
                    memo += rec[4:]
            if not memo:
                return None
            if return_raw:
                return memo
            return ap.parse_type(ap.TYPE_TEXT, memo, len(memo), version=self.version)

    class MemoryAccessParser(ap.AccessParser):
        def __init__(self, data: bytes):  # noqa: D401 - mirrors the parent
            self.db_data = data
            self._parse_file_header(data)
            ps = self.page_size
            self._table_defs, self._data_pages, self._all_pages = {}, {}, {}
            for off in range(0, len(data) - ps + 1, ps):
                magic = data[off:off + 2]
                if magic == b"\x01\x01":
                    self._data_pages[off] = data[off:off + ps]
                elif magic == b"\x02\x01":
                    self._table_defs[off] = data[off:off + ps]
            self._tables_with_data = self._link_tables_to_data()
            self.catalog = self._parse_catalog()
            self.extra_props = {}  # MSysObjects formatting props: not needed

        def _parse_catalog(self):
            page = self._tables_with_data.get(2 * self.page_size)
            if page is None:
                raise ValueError("no catalog")
            cat = SafeTable(page, self.version, self.page_size, self._data_pages, self._table_defs).parse()
            out = {}
            for i, name in enumerate(cat.get("Name") or []):
                try:
                    if cat["Type"][i] == 1:
                        out[name] = cat["Id"][i]
                except (IndexError, KeyError):
                    continue
            return out

        def get_table(self, table_name):
            offset = self.catalog.get(table_name)
            if not offset:
                return None
            offset *= self.page_size
            table = self._tables_with_data.get(offset)
            if table is None:
                tdef = self._table_defs.get(offset)
                if tdef is None:
                    return None
                table = ap.TableObj(offset=offset, val=tdef)
            return SafeTable(table, self.version, self.page_size, self._data_pages, self._table_defs)

        def parse_table(self, table_name):
            table = self.get_table(table_name)
            return table.parse() if table is not None else None

    return MemoryAccessParser


def read_tables(db_bytes: bytes, names=TABLES) -> dict[str, list[dict]]:
    """Read ``names`` from a Jet database held in memory into row dicts."""
    MemoryAccessParser = _jet_classes()
    ap_log = logging.getLogger("access_parser")
    prev = ap_log.level
    ap_log.setLevel(logging.CRITICAL)  # it logs every oddity at ERROR
    try:
        db = MemoryAccessParser(db_bytes)
        out: dict[str, list[dict]] = {}
        for name in names:
            cols = db.parse_table(name) if name in db.catalog else None
            if not cols:
                out[name] = []
                continue
            cols = {k: v for k, v in cols.items() if isinstance(v, list)}
            lengths = {len(v) for v in cols.values()}
            if len(lengths) > 1:
                raise RbdImportError(
                    f"Reliafy couldn't read the '{name}' table of this project reliably "
                    "(its rows are damaged or use an unsupported layout)."
                )
            n = lengths.pop() if lengths else 0
            out[name] = [{c: cols[c][i] for c in cols} for i in range(n)]
        return out
    finally:
        ap_log.setLevel(prev)


# ---------------------------------------------------------------------------
# Step 2: tables -> project dict
# ---------------------------------------------------------------------------

def _int(v, default=None):
    try:
        if v is None or v == "":
            return default
        return int(v)
    except (TypeError, ValueError):
        return default


def _float(v, default=None):
    try:
        if v is None or v == "":
            return default
        f = float(v)
        return f if math.isfinite(f) else default
    except (TypeError, ValueError):
        return default


def _ref(v) -> Optional[int]:
    """A foreign key: None for missing / 0 / negative."""
    i = _int(v)
    return i if i and i > 0 else None


def _unique(rows: list[dict], key: str) -> dict:
    out: dict = {}
    for r in rows:
        k = _int(r.get(key))
        if k is not None and k not in out:
            out[k] = r
    return out


def _decode_blob(blob, inflater: _Inflater):
    if not blob:
        return []
    raw = bytes(blob)
    if raw[:2] == _GZIP_MAGIC:
        raw = inflater.gunzip(raw, _MAX_BLOB_BYTES)
    return parse_streams(raw)


def diagram_edges(streams) -> list[list[int]]:
    """``[source, destination]`` block ids of every connection in a decoded
    ``Diagram`` blob (``RSDiagram.Relation`` records of each ``Container``)."""
    edges: list[list[int]] = []
    seen = set()
    for st in streams:
        for container in st.iter_objects("RSDiagram.Container"):
            for rel in st.list_items(container.get("Relations")):
                if rel is None or not hasattr(rel, "get"):
                    continue
                s, d = _int(rel.get("SourceBlockId")), _int(rel.get("DestinationBlockId"))
                if s is None or d is None or (s, d) in seen:
                    continue
                seen.add((s, d))
                edges.append([s, d])
    return edges


def container_members(streams) -> dict[int, list[list[int]]]:
    """Container block id -> its member paths, from a ``ContainerInfo`` blob
    (a ``Dictionary<int, List<List<int>>>``)."""
    out: dict[int, list[list[int]]] = {}
    for st in streams:
        for kv in st.iter_objects("", contains="Generic.KeyValuePair`2"):
            key = _int(kv.get("key"))
            if key is None:
                continue
            paths = []
            for inner in st.list_items(kv.get("value")):
                ids = []
                if inner is not None and hasattr(inner, "get"):
                    items = st.deref(inner.get("_items"))
                    size = _int(inner.get("_size"), 0)
                    if isinstance(items, list):
                        ids = [_int(x) for x in items[:size] if _int(x) is not None]
                if ids:
                    paths.append(ids)
            out[key] = paths
    return out


def extract_project(tables: dict[str, list[dict]], inflater: Optional[_Inflater] = None) -> dict:
    """Turn the raw tables into the importer's intermediate project dict."""
    inflater = inflater or _Inflater()
    t = {name: tables.get(name) or [] for name in TABLES}

    units = {
        uid: {"name": str(r.get("Nm") or ""), "multiplier": _float(r.get("Multiplier")),
              "category": _int(r.get("CategoryID"))}
        for uid, r in _unique(t["rsUnit"], "UnitID").items()
    }
    params: dict[int, dict[int, float]] = {}
    for r in t["rsModelParam"]:
        mid = _int(r.get("ModelId", r.get("ModelID")))
        pid = _int(r.get("ParameterID", r.get("ParameterId")))
        val = _float(r.get("ParameterValue"))
        if mid is None or pid is None or val is None:
            continue
        params.setdefault(mid, {}).setdefault(pid, val)
    models = {
        mid: {"name": str(r.get("Nm") or ""), "type": _int(r.get("ModelTypeID"), 0),
              "unit": _ref(r.get("UnitID")), "params": params.get(mid, {})}
        for mid, r in _unique(t["rsModel"], "ModelID").items()
    }
    scheduled = Counter(_int(r.get("RamoID")) for r in t["rsRamoTask"])
    urds = {
        rid: {"name": str(r.get("Nm") or ""), "model": _ref(r.get("ModelID")),
              "task": _ref(r.get("CorrectiveTaskID")), "scheduled_tasks": scheduled.get(rid, 0)}
        for rid, r in _unique(t["rsRamo"], "RamoID").items()
    }
    crews = Counter(_int(r.get("CorrectiveTaskID")) for r in t["rsTaskCorrectiveCrew"])
    tasks = {
        tid: {"name": str(r.get("Nm") or ""), "duration_model": _ref(r.get("DurationModelID")),
              "restoration": _float(r.get("ResFactorValue"), 1.0),
              "pool": bool(_ref(r.get("PoolID"))), "crews": crews.get(tid, 0)}
        for tid, r in _unique(t["rsTaskCorrective"], "CorrectiveTaskID").items()
    }
    switches = {
        sid: {"name": str(r.get("Nm") or ""), "p_switch": _float(r.get("ProbabilityPerRequest"), 1.0),
              "quiescent_model": _ref(r.get("QuiescentDistrID")), "delay": _float(r.get("DelayTime"), 0.0)}
        for sid, r in _unique(t["bsSwitch"], "SwitchID").items()
    }

    folio_names = {fid: str(r.get("FolioName") or "") for fid, r in _unique(t["rsFolio"], "FolioID").items()}
    local = _unique(t["bsBlockLocalData"], "LocalDataID")
    local_of = {}
    for r in t["bsBlockLocalDataOfStructure"]:
        sid, lid = _int(r.get("StructureID")), _int(r.get("LocalDataID"))
        if sid is not None and lid is not None:
            local_of.setdefault(sid, lid)

    blocks_by_diagram: dict[int, dict[int, dict]] = {}
    for r in t["bsBlockStructure"]:
        if r.get("IsDeleted"):
            continue
        did, bid, sid = _int(r.get("DiagramID")), _int(r.get("BlockID")), _int(r.get("StructureID"))
        if did is None or bid is None:
            continue
        ld = local.get(local_of.get(sid, sid), {})
        blocks_by_diagram.setdefault(did, {})[bid] = {
            "type": _int(r.get("BlockType"), 0),
            "name": str(ld.get("DisplayName") or "").strip() or f"Block {bid}",
            "urd": _ref(ld.get("RamoID")),
            "quiescent_urd": _ref(ld.get("QuiescentRamoID")),
            "required": max(_int(ld.get("NumPathsRequired"), 1) or 1, 1),
            "subdiagram": _ref(ld.get("SubdiagramID")),
            "standby_index": _int(ld.get("StandbyIndex"), 0),
            "active": bool(ld.get("IsActive")),
            "switch": _ref(ld.get("SwitchPolicyID")),
            "mirror_group": _ref(ld.get("MirrorGroupID")),
            "multiple": [_int(ld.get("MultipleType"), 0), _int(ld.get("MultipleNum"), 1),
                         _int(ld.get("MultipleParallelRequired"), 1)],
            "off": bool(ld.get("IsOff")),
            "duty_cycle": _float(ld.get("DutyCycle"), 1.0),
            "current_age": _float(ld.get("CurrentAge"), 0.0),
        }

    diagrams = []
    for kind, table in (("rbd", "bsFolioRBD"), ("ft", "bsFolioFaultTree")):
        for r in t[table]:
            fid = _int(r.get("FolioId", r.get("FolioID")))
            if fid is None:
                continue
            name = folio_names.get(fid) or f"Diagram {fid}"
            try:
                edges = diagram_edges(_decode_blob(r.get("Diagram"), inflater))
                containers = container_members(_decode_blob(r.get("ContainerInfo"), inflater))
            except NrbfError as exc:
                raise RbdImportError(
                    f"Reliafy couldn't decode the drawing of diagram “{name}” ({exc})."
                ) from None
            diagrams.append({
                "id": fid, "name": name, "kind": kind,
                "simulation": bool(r.get("IsSimulationDiagram")),
                "blocks": blocks_by_diagram.get(fid, {}),
                "edges": edges, "containers": containers,
            })
    projects = [str(r.get("Nm") or "") for r in t["rsProject"] if not str(r.get("Nm") or "").startswith("Internal project")]
    return {"name": projects[0] if projects else "", "units": units, "models": models, "urds": urds,
            "tasks": tasks, "switches": switches, "diagrams": diagrams}


# ---------------------------------------------------------------------------
# Step 3: project -> compact graphs
# ---------------------------------------------------------------------------

class _Skip(Exception):
    """This diagram can't be imported (message says why)."""


def _fmt(v: float) -> str:
    return f"{v:.6g}"


def _names(items: list[str], limit: int = 6) -> str:
    items = list(dict.fromkeys(items))
    shown = ", ".join(f"“{x}”" for x in items[:limit])
    if len(items) > limit:
        shown += f" and {len(items) - limit} more"
    return shown


class _Converter:
    """Builds one diagram's compact graph."""

    def __init__(self, project: dict, diagram: dict):
        self.p = project
        self.top = diagram
        self.by_id = {d["id"]: d for d in project["diagrams"]}
        self.nodes: dict[str, dict] = {}
        self.edges: dict[tuple[str, str], None] = {}  # an ordered set
        self.warnings: list[str] = []
        self.notes: dict[str, list[str]] = {}
        self.empty_refs = 0
        self.has_repair_data = False
        self.all_repairable = True
        self._seq = 0
        self.unit = self._pick_unit()

    # -- helpers ---------------------------------------------------------
    def warn(self, msg: str):
        if msg not in self.warnings:
            self.warnings.append(msg)

    def note(self, kind: str, label: str):
        """Collect a block for a warning shared by many blocks (see NOTES)."""
        self.notes.setdefault(kind, []).append(label)

    def _new_id(self, base: str) -> str:
        nid = base
        while nid in self.nodes or nid in ("input", "output"):
            self._seq += 1
            nid = f"{base}_{self._seq}"
        if len(self.nodes) >= _MAX_NODES:
            raise _Skip(f"it expands to more than {_MAX_NODES} blocks once subdiagrams are inlined")
        return nid

    def add_node(self, base: str, node: dict) -> str:
        nid = self._new_id(base)
        node["id"] = nid
        self.nodes[nid] = node
        return nid

    def junction(self, base: str, n: int = 1, label: str = "") -> str:
        return self.add_node(base, {"type": "knode", "label": label or ("Junction" if n == 1 else f"{n}-of-k"),
                                    "n": max(int(n), 1), "_synthetic": not label})

    def connect(self, src: str, dst: str):
        if src != dst:
            self.edges.setdefault((src, dst), None)

    # -- units -----------------------------------------------------------
    def _walk_models(self, diagram: dict, seen: set) -> list[int]:
        if diagram["id"] in seen:
            return []
        seen.add(diagram["id"])
        out = []
        for b in diagram["blocks"].values():
            urd = self.p["urds"].get(b.get("urd"))
            if urd and urd.get("model") in self.p["models"]:
                out.append(urd["model"])
            sub = self.by_id.get(b.get("subdiagram")) if b.get("type") == BT_SUBDIAGRAM else None
            if sub:
                out += self._walk_models(sub, seen)
        return out

    def _pick_unit(self) -> Optional[int]:
        units = Counter(self.p["models"][m].get("unit") for m in self._walk_models(self.top, set()))
        units.pop(None, None)
        return units.most_common(1)[0][0] if units else None

    def unit_label(self) -> str:
        u = self.p["units"].get(self.unit)
        if not u or not u.get("name"):
            return "Hours"
        name = u["name"].strip()
        return _UNIT_LABELS.get(name.lower().rstrip("s"), name)

    def _unit_factor(self, unit_id: Optional[int], what: str) -> float:
        """Multiply a stored time value by this to express it in the diagram unit.

        ReliaSoft stores every time value in the base unit of its category
        (the unit whose multiplier is 1 — hours for time); a model's
        ``UnitID`` is only the unit it is *displayed* in. (Evidence: BlockSim
        example 3 publishes eta = 6.89 years and stores 60356.4 = 6.89 x 8760
        with UnitID "Year".) So converting is a division by the diagram unit's
        multiplier, provided both units measure the same kind of thing."""
        dst = self.p["units"].get(self.unit)
        if not dst or not dst.get("multiplier") or dst["multiplier"] <= 0:
            return 1.0
        src = self.p["units"].get(unit_id)
        if src and src.get("category") != dst.get("category"):
            self.warn(
                f"{what} is measured in {src.get('name') or 'another unit'}, which can't be converted to "
                f"{dst.get('name') or 'the diagram unit'}; its values were imported unchanged."
            )
            return 1.0
        return 1.0 / dst["multiplier"]

    # -- models ----------------------------------------------------------
    def life_model(self, model_id: Optional[int], label: str, time_scale: float = 1.0,
                   what: str = "failure") -> tuple[Optional[dict], Optional[str]]:
        """``(compact model, None)`` or ``(None, reason it couldn't be mapped)``.

        ``time_scale`` stretches the time axis (duty cycle: a block running at
        duty d ages d times faster, so its life in system time is 1/d)."""
        m = self.p["models"].get(model_id)
        if m is None:
            return None, f"its {what} model is missing from the project"
        mtype, ps = m.get("type"), m.get("params") or {}
        type_name = MODEL_TYPE_NAMES.get(mtype, f"model type {mtype}")
        raw = ", ".join(f"#{k}={_fmt(v)}" for k, v in sorted(ps.items())) or "none"
        spec = _DECODED.get(mtype)
        if spec is None:
            return None, f"its {what} model “{m.get('name')}” is a {type_name}, which Reliafy can't read from BlockSim files yet (stored parameters: {raw})"
        needed, unit_param = spec
        extra = set(ps) - needed - {unit_param}
        if not needed <= set(ps) or extra or ps.get(unit_param, 1.0) != 1.0:
            return None, f"its {what} model “{m.get('name')}” ({type_name}) has parameters Reliafy doesn't recognise (stored parameters: {raw})"
        f = self._unit_factor(m.get("unit"), f"The {what} model “{m.get('name')}”") * time_scale
        if mtype in (100, 101):
            beta, eta = ps[_W_BETA], ps[_W_ETA]
            if beta <= 0 or eta <= 0:
                return None, f"its {what} model has a non-positive Weibull parameter"
            return {"distribution_id": "weibull",
                    "params": [{"name": "alpha", "value": eta * f}, {"name": "beta", "value": beta}]}, None
        if mtype == 106:
            mean = ps[_E_MEAN]
            if mean <= 0:
                return None, f"its {what} model has a non-positive mean time"
            return {"distribution_id": "exponential", "params": [{"name": "failure_rate", "value": 1.0 / (mean * f)}]}, None
        if mtype == 108:
            mu, sd = ps[_N_MEAN], ps[_N_STD]
            if sd <= 0:
                return None, f"its {what} model has a non-positive standard deviation"
            return {"distribution_id": "normal",
                    "params": [{"name": "mu", "value": mu * f}, {"name": "sigma", "value": sd * f}]}, None
        mu, sd = ps[_LN_MEAN], ps[_LN_STD]  # 109: log-mean / log-std, like SurPyval
        if sd <= 0:
            return None, f"its {what} model has a non-positive log-standard deviation"
        return {"distribution_id": "lognormal",
                "params": [{"name": "mu", "value": mu + math.log(f)}, {"name": "sigma", "value": sd}]}, None

    def block_models(self, b: dict, label: str, duty: float):
        """``(failure model, repair model, reason_if_no_failure_model)`` for a block."""
        urd = self.p["urds"].get(b.get("urd"))
        if urd is None:
            return None, None, None
        if urd.get("scheduled_tasks"):
            self.note("scheduled", label)
        model, why = self.life_model(urd.get("model"), label, 1.0 / duty if duty > 0 else 1.0)
        repair = None
        task = self.p["tasks"].get(urd.get("task"))
        if task is not None:
            self.has_repair_data = True
            if task.get("duration_model") is None:
                self.note("instant_repair", label)
            else:
                repair, rwhy = self.life_model(task.get("duration_model"), label, 1.0, what="repair-duration")
                if repair is None:
                    self.warn(f"The repair data of “{label}” wasn't imported: {rwhy}.")
            if repair is not None:
                if task.get("restoration") not in (None, 1.0):
                    self.note("restoration", label)
                if task.get("pool") or task.get("crews"):
                    self.note("logistics", label)
        return model, repair, why

    # -- blocks ----------------------------------------------------------
    def _component(self, base: str, label: str, b: dict, duty: float) -> str:
        model, repair, why = self.block_models(b, label, duty)
        node: dict[str, Any] = {"type": "component", "label": label}
        if model is not None:
            node["model"] = model
        elif why:
            self.warn(f"“{label}” was imported without a life model — {why}. Set it on the block before analysing.")
        if repair is not None:
            node["_repair"] = repair
        if b.get("off"):
            node["_state"] = "failed"
        if (b.get("current_age") or 0) > 0:
            self.note("age", label)
        if b.get("mirror_group"):
            self.note("mirror", label)
        return self.add_node(base, node)

    def _placeholder(self, base: str, label: str, why: str) -> tuple[list[str], str]:
        self.warn(f"“{label}” was imported as a plain block without a life model — {why}. Set it before analysing.")
        nid = self.add_node(base, {"type": "component", "label": label})
        return [nid], nid

    def fragment(self, diagram: dict, bid: int, base: str, prefix: str, duty: float,
                 stack: tuple) -> tuple[list[str], str]:
        """Build one block; returns ``(entry node ids, exit node id)``."""
        b = diagram["blocks"][bid]
        btype = b.get("type")
        name = str(b.get("name") or "").strip()
        if name in ("", "*"):  # BlockSim's default caption for gates/containers
            sub = self.by_id.get(b.get("subdiagram")) if btype == BT_SUBDIAGRAM else None
            name = (sub["name"] if sub else {BT_STANDBY: "Standby container", BT_LOADSHARE: "Load-sharing container",
                                              BT_NODE: "Node"}.get(btype, f"Block {bid}"))
        label = f"{prefix}{name}"
        duty = duty * (b.get("duty_cycle") or 1.0)
        req = b.get("required") or 1

        if btype in (BT_NODE, BT_JUNCTION):
            k = self.junction(base, req, label)
            if b.get("off"):
                self.nodes[k]["_state"] = "failed"
            return [k], k

        if btype == BT_SUBDIAGRAM:
            sub = self.by_id.get(b.get("subdiagram"))
            mult = list(b.get("multiple") or [0, 1])
            if sub is None or not sub.get("blocks"):
                self.empty_refs += 1
                return self._placeholder(base, label, "the diagram it stands for is missing or empty in this file")
            if mult[0] and len(mult) > 1 and (mult[1] or 0) > 1:
                return self._placeholder(base, label, "it represents several copies of its subdiagram, which Reliafy can't expand yet")
            ins, out = self.expand(sub, f"{base}.", f"{label} › ", duty, stack)
            if req > 1 or b.get("off"):
                # A gate in front: k-of-n over the incoming paths, and/or the
                # "set as failed" what-if pinned on it (cuts the subdiagram off).
                k = self.junction(f"{base}.in", req, f"{label} ({req} paths)" if req > 1 else f"{label} (off)")
                if b.get("off"):
                    self.nodes[k]["_state"] = "failed"
                for i in ins:
                    self.connect(k, i)
                ins = [k]
            return ins, out

        if btype in (BT_STANDBY, BT_LOADSHARE):
            return self.container(diagram, bid, base, label, duty)

        if btype in _GATE_NAMES or btype in _OTHER_BLOCK_NAMES:
            what = _GATE_NAMES.get(btype) and f"a {_GATE_NAMES[btype]} gate" or f"a {_OTHER_BLOCK_NAMES[btype]} block"
            raise _Skip(f"it uses {what}, which has no reliability-block-diagram equivalent")

        if btype not in (BT_REGULAR, BT_IN_STANDBY, BT_IN_LOADSHARE):
            return self._placeholder(base, label, f"BlockSim block type {btype} isn't supported")

        if not self.p["urds"].get(b.get("urd")):
            # No failure definition: a non-failing block (BlockSim's Start/End
            # style blocks) — a perfect junction.
            k = self.junction(base, req, label)
            if b.get("off"):
                self.nodes[k]["_state"] = "failed"
            return [k], k

        mult = list(b.get("multiple") or [0, 1, 1])
        mult += [1] * (3 - len(mult))
        mtype, num, mreq = mult[0], mult[1], mult[2]
        if mtype and num and num > 1:
            if mreq != num:
                return self._placeholder(
                    base, label,
                    f"it represents {num} identical blocks of which {mreq} are required, an arrangement "
                    "Reliafy can't read from BlockSim files yet"
                )
            # All units required: series of `num`, whatever the arrangement.
            nid = self._component(base, label, b, duty)
            node = self.nodes[nid]
            node.update(type="series", n=num)
            if "_repair" in node:
                self.warn(f"“{label}” (a multi-block) can't carry repair data in Reliafy.")
            return [nid], nid

        comp = self._component(base, label, b, duty)
        if req > 1:
            k = self.junction(f"{base}.in", req, f"{label} ({req} paths)")
            self.connect(k, comp)
            return [k], comp
        return [comp], comp

    def container(self, diagram: dict, bid: int, base: str, label: str, duty: float):
        b = diagram["blocks"][bid]
        blocks = diagram["blocks"]
        paths = diagram.get("containers", {}).get(bid)
        if paths is None:
            inside = BT_IN_STANDBY if b["type"] == BT_STANDBY else BT_IN_LOADSHARE
            same = [x for x, v in blocks.items() if v.get("type") == b["type"]]
            if len(same) != 1:
                return self._placeholder(base, label, "its member blocks couldn't be identified")
            paths = [[x] for x, v in blocks.items() if v.get("type") == inside]
        if any(len(p) != 1 for p in paths):
            return self._placeholder(base, label, "its paths hold several blocks each, which Reliafy can't import yet")
        members = [blocks[p[0]] | {"_bid": p[0]} for p in paths if p and p[0] in blocks]
        if not members:
            return self._placeholder(base, label, "it has no member blocks")
        req = b.get("required") or 1

        if b["type"] == BT_LOADSHARE:
            n = len(members)
            if req > n:
                return self._placeholder(base, label, f"it needs {req} of its {n} units")
            # BlockSim takes a unit's life model as its life carrying the
            # container's whole load, and scales each survivor's life by its
            # share (checked against example 4: R(8760 h) = 0.973517 and B10 =
            # 14715.6 h reproduced exactly). For identical exponential units the
            # survivors' total failure rate is then always the full-load rate
            # lambda, whatever the weights, so the container fails at the
            # (n - k + 1)th failure: an Erlang, i.e. Gamma(n - k + 1, lambda).
            simple = all(m.get("type") in (BT_IN_LOADSHARE, BT_REGULAR) and not m.get("off") for m in members)
            models = []
            if simple:
                for m in members:
                    mdl, _rep, _why = self.block_models(m, f"{label} › {m['name']}",
                                                         duty * (m.get("duty_cycle") or 1.0))
                    models.append(mdl)
            if simple and models and models[0] is not None and models[0]["distribution_id"] == "exponential" \
                    and all(mm == models[0] for mm in models):
                rate = models[0]["params"][0]["value"]
                nid = self.add_node(base, {
                    "type": "component", "label": label,
                    "model": {"distribution_id": "gamma", "params": [
                        {"name": "alpha", "value": float(n - req + 1)}, {"name": "beta", "value": rate}]},
                })
                self.all_repairable = False
                self.warn(
                    f"Load-sharing container “{label}” ({req} of {n} identical exponential units) was imported "
                    f"as one block with the exact equivalent life: gamma(shape {n - req + 1}, rate {_fmt(rate)})."
                )
                return [nid], nid
            fork_ins, outs = [], []
            for m in members:
                ins, out = self.fragment(diagram, m["_bid"], f"{base}.{m['_bid']}", f"{label} › ", duty, ())
                fork_ins += ins
                outs.append(out)
            k = self.junction(f"{base}.vote", req, f"{label} ({req} of {len(members)})")
            for o in outs:
                self.connect(o, k)
            self.warn(
                f"Load-sharing container “{label}” was imported as an independent {req}-out-of-{n} vote with "
                "every unit at its full-load life. BlockSim shares the load, so its units last longer until "
                "others fail; this approximation is conservative (pessimistic)."
            )
            return fork_ins, k

        # Standby container.
        if req != 1:
            return self._placeholder(base, label, f"it's a standby container needing {req} active paths; Reliafy's standby block runs one unit at a time")
        members.sort(key=lambda m: (m.get("standby_index") or 0))
        active = [m for m in members if m.get("active")] or members[:1]
        if len(active) != 1:
            return self._placeholder(base, label, "it has several active units; Reliafy's standby block runs one unit at a time")
        primary = active[0]
        spares = [m for m in members if m is not primary]
        if not spares:
            return self._placeholder(base, label, "it has no standby units")
        if any(m.get("type") not in (BT_IN_STANDBY, BT_REGULAR) for m in members):
            return self._placeholder(base, label, "its units are subdiagrams, which Reliafy's standby block can't hold")
        pmodel, _prep, pwhy = self.block_models(primary, f"{label} › {primary['name']}", duty * (primary.get("duty_cycle") or 1.0))
        if pmodel is None:
            return self._placeholder(base, label, f"its active unit “{primary['name']}” — {pwhy or 'has no failure model'}")
        smodels = []
        for s in spares:
            smodel, _srep, swhy = self.block_models(s, f"{label} › {s['name']}", duty * (s.get("duty_cycle") or 1.0))
            if smodel is None:
                return self._placeholder(base, label, f"its standby unit “{s['name']}” — {swhy or 'has no failure model'}")
            smodels.append(smodel)
        if any(m != smodels[0] for m in smodels):
            return self._placeholder(base, label, "its standby units have different life models; Reliafy's standby block uses one model for all spares")

        # Quiescent (dormant) behaviour of the spares.
        quiescent = set()
        for s in spares:
            q = s.get("quiescent_urd")
            qmodel = None
            if q:
                qurd = self.p["urds"].get(q)
                qmodel, _ = self.life_model(qurd.get("model") if qurd else None, label)
                quiescent.add("hot" if qmodel is not None and qmodel == smodels[0] else "warm")
            else:
                quiescent.add("cold")
        if quiescent == {"cold"}:
            cold = True
        elif quiescent == {"hot"}:
            cold = False
        else:
            cold = False
            self.warn(
                f"The standby units of “{label}” can fail while dormant at a reduced rate (warm standby). "
                "Reliafy has cold and hot standby only, so it was imported as hot standby — conservative; "
                "the BlockSim result lies between cold and hot."
            )
        data: dict[str, Any] = {}
        sw = self.p["switches"].get(b.get("switch"))
        if sw is not None:
            p_switch = sw.get("p_switch")
            if p_switch is not None and p_switch < 1.0:
                if cold:
                    data["startProb"] = p_switch
                else:
                    self.warn(f"The switch of “{label}” succeeds with probability {_fmt(p_switch)}; Reliafy applies switch reliability to cold standby only, so it was ignored.")
            if sw.get("quiescent_model"):
                self.warn(f"The switch of “{label}” can itself fail over time in BlockSim; Reliafy only models its success probability on demand.")
            if (sw.get("delay") or 0) > 0:
                self.warn(f"The switch of “{label}” has a switching delay in BlockSim; Reliafy switches instantly.")
        if smodels[0] != pmodel:
            data["standbyModel"] = smodels[0]
        node = {"type": "standby", "label": label, "model": pmodel, "spares": len(spares), "cold": cold}
        if data:
            node["data"] = data
        if b.get("off"):
            node["_state"] = "failed"
        nid = self.add_node(base, node)
        self.all_repairable = False
        return [nid], nid

    # -- diagrams --------------------------------------------------------
    def expand(self, diagram: dict, base: str, prefix: str, duty: float, stack: tuple) -> tuple[list[str], str]:
        """Inline a diagram; returns ``(entry node ids, exit node id)``."""
        if diagram["id"] in stack:
            raise _Skip(f"its subdiagrams refer back to “{diagram['name']}” (a cycle)")
        if len(stack) >= _MAX_SUBDIAGRAM_DEPTH:
            raise _Skip("its subdiagrams are nested too deeply")
        stack = stack + (diagram["id"],)
        if diagram.get("kind") == "ft":
            return self.expand_fault_tree(diagram, base, prefix, duty, stack)

        blocks = diagram["blocks"]
        members = {m for paths in (diagram.get("containers") or {}).values() for p in paths for m in p}
        for bid, blk in blocks.items():
            if blk.get("type") in (BT_IN_STANDBY, BT_IN_LOADSHARE):
                members.add(bid)
        ids = [bid for bid, blk in blocks.items() if bid not in members and blk.get("type") != BT_ANNOTATION]
        if not ids:
            raise _Skip("it has no blocks")
        frag = {bid: self.fragment(diagram, bid, f"{base}b{bid}", prefix, duty, stack) for bid in ids}
        preds: dict[int, set] = {bid: set() for bid in ids}
        succs: dict[int, set] = {bid: set() for bid in ids}
        dropped = 0
        for s, d in diagram.get("edges") or []:
            if s in frag and d in frag and s != d:
                succs[s].add(d)
                preds[d].add(s)
            else:
                dropped += 1
        if dropped:
            LOG.debug("blocksim: %d connections to hidden/deleted blocks dropped in %s", dropped, diagram["name"])
        for s in ids:
            for d in sorted(succs[s]):
                for i in frag[d][0]:
                    self.connect(frag[s][1], i)
        sources = [bid for bid in ids if not preds[bid]]
        sinks = [bid for bid in ids if not succs[bid]]
        if not sources or not sinks:
            raise _Skip("its connections form a loop with no start or end")
        ins = [i for bid in sources for i in frag[bid][0]]
        if len(sinks) == 1:
            return ins, frag[sinks[0]][1]
        out = self.junction(f"{base}end")
        for bid in sinks:
            self.connect(frag[bid][1], out)
        return ins, out

    def expand_fault_tree(self, diagram: dict, base: str, prefix: str, duty: float, stack: tuple):
        """A fault tree's success-space RBD (edges run child -> gate)."""
        blocks = diagram["blocks"]
        children: dict[int, list[int]] = {bid: [] for bid in blocks}
        parents: dict[int, list[int]] = {bid: [] for bid in blocks}
        for s, d in diagram.get("edges") or []:
            if s in blocks and d in blocks and s != d and s not in children[d]:
                children[d].append(s)
                parents[s].append(d)
        # Containers in a fault tree list their units as the container's inputs.
        containers = dict(diagram.get("containers") or {})
        for bid, kids in children.items():
            if blocks[bid].get("type") in (BT_STANDBY, BT_LOADSHARE) and bid not in containers:
                containers[bid] = [[c] for c in kids]
        diagram = {**diagram, "containers": containers}
        shared = [blocks[b]["name"] for b, ps in parents.items() if len(ps) > 1]
        if shared:
            raise _Skip(f"events {_names(shared)} feed more than one gate (repeated events), which a block diagram can't represent")
        tops = [bid for bid in blocks if not parents[bid] and blocks[bid].get("type") != BT_ANNOTATION]
        if len(tops) != 1:
            raise _Skip("it doesn't have exactly one top event" if tops else "it has no events")

        def build(bid: int, depth: int) -> tuple[list[str], str]:
            if depth > 200:
                raise _Skip("its gates are nested too deeply")
            b = blocks[bid]
            btype = b.get("type")
            nb = f"{base}b{bid}"
            if btype not in (BT_GATE_AND, BT_GATE_OR, BT_GATE_VOTE):
                return self.fragment(diagram, bid, nb, prefix, duty, stack)
            kids = [build(c, depth + 1) for c in children[bid]]
            if not kids:
                raise _Skip(f"gate “{b.get('name')}” has no inputs")
            if btype == BT_GATE_OR:  # any input event fails it -> all must work: series
                for (_, out), (nxt_ins, _) in zip(kids, kids[1:]):
                    for i in nxt_ins:
                        self.connect(out, i)
                return kids[0][0], kids[-1][1]
            if btype == BT_GATE_AND:
                need = 1
            else:  # vote: the event occurs when `required` inputs fail
                need = len(kids) - (b.get("required") or 1) + 1
                if need < 1:
                    raise _Skip(f"vote gate “{b.get('name')}” needs more failures than it has inputs")
            label = f"{prefix}{b.get('name')}" if b.get("name") not in ("*", "", None) else ""
            k = self.junction(nb, need, label or (f"{need} of {len(kids)}" if need > 1 else ""))
            ins = []
            for kid_ins, out in kids:
                ins += kid_ins
                self.connect(out, k)
            return ins, k

        return build(tops[0], 0)

    # -- final assembly ----------------------------------------------------
    def _bypass_junctions(self):
        """Remove synthetic / perfect ``n = 1`` junctions where that's exactly
        equivalent, so BlockSim Start/End blocks become Reliafy's input/output."""
        preds: dict[str, set] = {}
        succs: dict[str, set] = {}
        for s, d in self.edges:
            succs.setdefault(s, set()).add(d)
            preds.setdefault(d, set()).add(s)
        changed = True
        while changed:
            changed = False
            for nid, node in list(self.nodes.items()):
                if node["type"] != "knode" or node.get("n", 1) != 1 or node.get("_state"):
                    continue
                ps, ss = preds.get(nid, set()), succs.get(nid, set())
                if not ps or not ss or ("input" in ps and "output" in ss):
                    continue
                # Safe when every successor is OR-like (edge multiplicity is
                # irrelevant), or when there's a single predecessor that takes
                # this junction's place one-for-one (keeps vote counts exact).
                or_succs = all(d == "output" or self.nodes[d]["type"] != "knode" or self.nodes[d].get("n", 1) == 1
                               for d in ss)
                (p0,) = ps if len(ps) == 1 else (None,)
                single = p0 is not None and not (ss & succs.get(p0, set()))
                if not (or_succs or single):
                    continue
                for s in ps:
                    del self.edges[(s, nid)]
                    succs[s].discard(nid)
                for d in ss:
                    del self.edges[(nid, d)]
                    preds[d].discard(nid)
                for s in ps:
                    for d in ss:
                        if s != d and (s, d) not in self.edges:
                            self.edges[(s, d)] = None
                            succs.setdefault(s, set()).add(d)
                            preds.setdefault(d, set()).add(s)
                preds.pop(nid, None)
                succs.pop(nid, None)
                del self.nodes[nid]
                changed = True

    def build(self) -> ImportedDiagram:
        ins, out = self.expand(self.top, "", "", 1.0, ())
        for i in ins:
            self.connect("input", i)
        self.connect(out, "output")
        self._bypass_junctions()
        for kind, text in NOTES.items():
            if self.notes.get(kind):
                self.warn(text.format(names=_names(self.notes[kind])))
        real = [n for n in self.nodes.values() if n["type"] != "knode"]
        if self.empty_refs and len(real) == self.empty_refs:
            raise _Skip("its subdiagram blocks point at diagrams that are empty or missing")

        comps = [n for n in self.nodes.values() if n["type"] == "component"]
        failing = [n for n in comps if n.get("_state") != "failed"]
        only_simple = all(n["type"] in ("component", "knode") for n in self.nodes.values())
        with_repair = [n for n in failing if n.get("_repair")]
        repairable = bool(
            self.top.get("simulation") and self.all_repairable and only_simple and failing
            and all(n.get("model") and n.get("_repair") for n in failing)
        )
        if not repairable and (with_repair or self.has_repair_data):
            labels = [n["label"] for n in with_repair]
            if not self.top.get("simulation"):
                why = "BlockSim analyses this diagram analytically (without maintenance)"
            elif not only_simple:
                why = "it has blocks Reliafy's availability analysis doesn't support (standby, multi-blocks)"
            else:
                missing = [n["label"] for n in failing if not (n.get("model") and n.get("_repair"))]
                why = f"not every block has a usable failure and repair model ({_names(missing)})"
            self.warn(
                "Imported as a non-repairable (reliability) diagram because " + why + "; "
                + (f"the repair data on {_names(labels)} was dropped." if labels else "its repair data was dropped.")
            )

        indegree = Counter(d for _, d in self.edges)
        nodes = [{"id": "input", "type": "input"}, {"id": "output", "type": "output"}]
        for nid, n in self.nodes.items():
            node = {k: v for k, v in n.items() if not k.startswith("_")}
            data = dict(node.pop("data", {}) or {})
            if n.get("_state"):
                data["state"] = n["_state"]
            if repairable and n.get("_repair"):
                node["repair"] = n["_repair"]
            if node["type"] == "knode":
                node["k"] = indegree[nid]
            if data:
                node["data"] = data
            nodes.append(node)
        graph = {
            "nodes": nodes,
            "edges": [{"source": s, "target": d} for s, d in self.edges],
            "unit": self.unit_label(),
        }
        if repairable:
            graph["repairable"] = True
        name = self.top["name"] + (" (fault tree)" if self.top.get("kind") == "ft" else "")
        return ImportedDiagram(name=name, graph=graph, warnings=list(self.warnings), source_format=SOURCE_FORMAT)


NOTES = {
    "scheduled": "Scheduled maintenance and inspection tasks aren't imported (on {names}).",
    "instant_repair": "The corrective tasks on {names} have no duration (instantaneous replacement), which Reliafy's repair models can't express.",
    "restoration": "Reliafy repairs restore blocks to as good as new; the corrective tasks on {names} use a different restoration factor in BlockSim.",
    "logistics": "Crew and spare-part logistic delays aren't imported — repair durations only (on {names}).",
    "age": "Reliafy starts every block new; {names} start with an age already accumulated in BlockSim.",
    "mirror": "{names} are mirrored blocks in BlockSim (one physical item drawn in several places); Reliafy treats each copy as an independent block.",
}


def convert_project(project: dict) -> list[ImportedDiagram]:
    """One :class:`ImportedDiagram` per BlockSim diagram that can be imported."""
    out: list[ImportedDiagram] = []
    skipped: list[str] = []
    for diagram in project.get("diagrams") or []:
        if not diagram.get("blocks"):
            skipped.append(f"“{diagram['name']}” (it's empty)")
            continue
        try:
            out.append(_Converter(project, diagram).build())
        except _Skip as exc:
            skipped.append(f"“{diagram['name']}” ({exc})")
    if not out:
        if skipped:
            raise RbdImportError("None of the diagrams in this BlockSim project could be imported: " + "; ".join(skipped) + ".")
        raise RbdImportError("No reliability block diagrams or fault trees found in this BlockSim project.")
    if skipped:
        out[0].warnings.append("Not imported from this project: " + "; ".join(skipped) + ".")
    return out


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def parse(data: bytes, filename: str) -> list[ImportedDiagram]:
    inflater = _Inflater()
    try:
        raw = inflater.gunzip(data) if data[:2] == _GZIP_MAGIC else data
        if not _is_jet(raw[:32]):
            raise RbdImportError(
                "This isn't a ReliaSoft project database. Export the project from BlockSim "
                "(File › Pack and E-mail gives a .rsgz file) and upload that."
            )
        tables = read_tables(raw)
        if not tables.get("bsBlockStructure") and not tables.get("bsFolioRBD"):
            raise RbdImportError("This ReliaSoft project has no BlockSim diagrams in it.")
        project = extract_project(tables, inflater)
        return convert_project(project)
    except RbdImportError:
        raise
    except MemoryError:
        raise RbdImportError("This BlockSim project is too large to import.") from None
    except Exception as exc:  # noqa: BLE001 - any parser failure is a bad upload
        LOG.info("blocksim import failed: %s", exc, exc_info=True)
        raise RbdImportError(
            "Reliafy couldn't read this BlockSim project — the file looks damaged or was saved by "
            "a version whose layout Reliafy doesn't know. Try Pack and E-mail from BlockSim and upload the .rsgz."
        ) from None
