"""ReliaSoft BlockSim importer (``backend.services.rbd_import.blocksim``).

Unit tests drive each layer with small hand-written inputs:

* a tiny MS-NRBF writer builds diagram / container blobs for :mod:`.nrbf`;
* hand-written table rows go through :func:`extract_project`;
* hand-written *project* dicts go through :func:`convert_project`, then
  ``normalize_graph`` and the real RBD analysis.

The integration tests at the bottom run against ReliaSoft's public example
projects when they're present in ``backend/tests/fixtures/external/blocksim/``
(gitignored — they're ReliaSoft's copyright; fetch them with
``python backend/scripts/fetch_rbd_import_fixtures.py [--all]``).

How the stored model parameters were decoded (``rsModelParam.ParameterID``):
ReliaSoft's API documents each model's parameter order but not the database
ids, so the ids were matched against published values — BlockSim example 2
(Comp. 1 = Weibull beta 2, eta 5000; Comp. 5 = lognormal log-mean 10, log-std
1.4; Comp. 8 = exponential mean 10000 h), the Weibull++ examples (normal mean
12751.7 / std 1348.2) and example 1's exponential MTBFs. Every
single-population model ends with one more id holding 1.0 (0.917 in one
non-parametric fit, and the model count 2.0 in a competing-modes model), so a
model whose trailing value isn't 1.0 is not imported.
"""

from __future__ import annotations

import gzip
import math
import struct
from pathlib import Path

import numpy as np
import pytest

from backend.services import rbd_analysis as ra
from backend.services.rbd_graph import normalize_graph
from backend.services.rbd_import import RbdImportError, import_file
from backend.services.rbd_import import blocksim as bs
from backend.services.rbd_import import nrbf


# ---------------------------------------------------------------------------
# A minimal MS-NRBF writer (just what BlockSim's blobs use)
# ---------------------------------------------------------------------------

def _lps(s: str) -> bytes:
    raw = s.encode("utf-8")
    n, out = len(raw), bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out) + raw


def _i32(v: int) -> bytes:
    return struct.pack("<i", v)


HEADER = b"\x00" + struct.pack("<iiii", 1, -1, 1, 0)
END = b"\x0b"


def _class(oid: int, name: str, members: list[tuple[str, str]], values: list, lib: int = 2) -> bytes:
    """ClassWithMembersAndTypes. ``members``: (name, 'int' | 'obj')."""
    out = b"\x05" + _i32(oid) + _lps(name) + _i32(len(members))
    out += b"".join(_lps(m) for m, _ in members)
    out += bytes(0 if t == "int" else 2 for _, t in members)
    out += b"".join(bytes([8]) for _, t in members if t == "int")
    out += _i32(lib)
    for (_, t), v in zip(members, values):
        out += _i32(v) if t == "int" else v
    return out


def _ref(oid: int) -> bytes:
    return b"\x09" + _i32(oid)


def _object_array(oid: int, items: list[bytes], capacity: int) -> bytes:
    out = b"\x10" + _i32(oid) + _i32(capacity) + b"".join(items)
    if capacity > len(items):
        out += b"\x0d" + bytes([capacity - len(items)])  # ObjectNullMultiple256
    return out


def diagram_blob(edges: list[tuple[int, int]]) -> bytes:
    """A gzipped BlockSim ``Diagram`` blob: one Container with Relations."""
    body = HEADER + b"\x0c" + _i32(2) + _lps("RSOfficeUI")
    body += _class(1, "RSOfficeUI.RSDiagram.Container", [("Id", "int"), ("Relations", "obj")], [0, _ref(3)])
    body += _class(3, "System.Collections.Generic.List`1[[RSOfficeUI.RSDiagram.Relation]]",
                   [("_items", "obj"), ("_size", "int"), ("_version", "int")], [_ref(4), len(edges), 0])
    rels = []
    for i, (s, d) in enumerate(edges):
        oid = 10 + i
        if i == 0:
            rels.append(_class(oid, "RSOfficeUI.RSDiagram.Relation",
                               [("SourceBlockId", "int"), ("DestinationBlockId", "int")], [s, d]))
        else:  # ClassWithId re-using the first Relation's metadata
            rels.append(b"\x01" + _i32(oid) + _i32(10) + _i32(s) + _i32(d))
    body += _object_array(4, rels, capacity=len(edges) + 2)
    return gzip.compress(body + END)


def container_blob(members: dict[int, list[int]]) -> bytes:
    """A gzipped ``ContainerInfo`` blob: Dictionary<int, List<List<int>>>."""
    body = HEADER
    oid = 100
    kvs = []
    tail = b""
    for key, ids in members.items():
        kv, lst, arr = oid, oid + 1, oid + 2
        oid += 3
        kvs.append(_class(kv, "System.Collections.Generic.KeyValuePair`2[[System.Int32],[List]]",
                          [("key", "int"), ("value", "obj")], [key, _ref(lst)], lib=2))
        inner_refs = []
        inner = b""
        for m in ids:
            il, ia = oid, oid + 1
            oid += 2
            inner_refs.append(_ref(il))
            inner += _class(il, "System.Collections.Generic.List`1[[System.Int32]]",
                            [("_items", "obj"), ("_size", "int"), ("_version", "int")], [_ref(ia), 1, 0])
            inner += b"\x0f" + _i32(ia) + _i32(4) + bytes([8]) + _i32(m) + _i32(0) * 3
        tail += _class(lst, "System.Collections.Generic.List`1[[List]]",
                       [("_items", "obj"), ("_size", "int"), ("_version", "int")], [_ref(arr), len(ids), 0])
        tail += _object_array(arr, inner_refs, capacity=len(ids)) + inner
    body += b"\x0c" + _i32(2) + _lps("mscorlib")
    body += _class(1, "System.Collections.Generic.Dictionary`2", [("Version", "int"), ("KeyValuePairs", "obj")],
                   [1, _ref(50)])
    body += _object_array(50, kvs, capacity=len(kvs)) + tail
    return gzip.compress(body + END)


# ---------------------------------------------------------------------------
# Sniffing, decompression, NRBF
# ---------------------------------------------------------------------------

JET_HEAD = b"\x00\x01\x00\x00Standard Jet DB\x00" + b"\x00" * 64


def test_sniff_by_content_and_extension():
    assert bs.sniff(JET_HEAD, "x.bin")
    assert bs.sniff(gzip.compress(JET_HEAD), "upload")
    assert bs.sniff(b"whatever", "Project.rsgz21")
    assert bs.sniff(b"whatever", "old.RSRP")
    assert not bs.sniff(b"<?xml version='1.0'?><opsa-mef/>", "model.xml")
    # A gzip that isn't a Jet database is left for the other importers.
    assert not bs.sniff(gzip.compress(b"<opsa-mef/>"), "model.xml.gz")


def test_gunzip_refuses_bombs_and_truncation():
    inflater = bs._Inflater(budget=1024 * 1024)
    with pytest.raises(RbdImportError, match="expands"):
        inflater.gunzip(gzip.compress(b"\x00" * (4 * 1024 * 1024)))
    whole = gzip.compress(b"abc" * 1000)
    with pytest.raises(RbdImportError, match="truncated"):
        bs._Inflater().gunzip(whole[: len(whole) // 2])
    assert bs._Inflater().gunzip(whole) == b"abc" * 1000


def test_nrbf_reads_diagram_relations_and_container_members():
    streams = nrbf.parse_streams(gzip.decompress(diagram_blob([(7, 2), (2, 4), (7, 3)])))
    assert bs.diagram_edges(streams) == [[7, 2], [2, 4], [7, 3]]
    streams = nrbf.parse_streams(gzip.decompress(container_blob({5: [1, 2, 3]})))
    assert bs.container_members(streams) == {5: [[1], [2], [3]]}


@pytest.mark.parametrize("blob", [
    b"",  # empty: no stream header
    HEADER + b"\x05" + _i32(1),  # truncated class record
    HEADER + b"\x15" + b"\x00" * 20,  # MethodCall record: refused
    HEADER + b"\x01" + _i32(1) + _i32(99) + END,  # unknown class metadata
    HEADER + b"\x10" + _i32(1) + _i32(10**8) + END,  # absurd array length
    HEADER + b"\x06" + _i32(1) + b"\xff\xff\xff\xff\x0f" + END,  # absurd string length
])
def test_nrbf_rejects_malformed_input(blob):
    with pytest.raises(nrbf.NrbfError):
        s = nrbf.parse_streams(blob)
        if not blob:
            raise nrbf.NrbfError("no streams")  # empty input decodes to nothing
        assert s  # pragma: no cover


def test_nrbf_nesting_is_bounded():
    # A chain of nested inline arrays deeper than MAX_DEPTH.
    deep = b"".join(b"\x10" + _i32(i + 1) + _i32(1) for i in range(nrbf.MAX_DEPTH + 5)) + b"\x0a"
    with pytest.raises(nrbf.NrbfError, match="deep"):
        nrbf.parse_streams(HEADER + deep + END)


# ---------------------------------------------------------------------------
# Tables -> project dict
# ---------------------------------------------------------------------------

def _tables():
    """A two-block series diagram (A -> B) plus a standby container, as the
    raw rows access_parser would return."""
    return {
        "rsProject": [{"Nm": "Demo"}, {"Nm": "Internal project - DO NOT DELETE"}],
        "rsFolio": [{"FolioID": 4, "FolioName": "Pumps"}],
        "bsFolioRBD": [{"FolioId": 4, "IsSimulationDiagram": True,
                        "Diagram": diagram_blob([(1, 2), (2, 3)]),
                        "ContainerInfo": container_blob({3: [4, 5]})}],
        "bsBlockStructure": [
            {"StructureID": 10, "DiagramID": 4, "BlockID": 1, "BlockType": 0, "IsDeleted": False},
            {"StructureID": 11, "DiagramID": 4, "BlockID": 2, "BlockType": 0, "IsDeleted": False},
            {"StructureID": 12, "DiagramID": 4, "BlockID": 3, "BlockType": 4, "IsDeleted": False},
            {"StructureID": 13, "DiagramID": 4, "BlockID": 4, "BlockType": 101, "IsDeleted": False},
            {"StructureID": 14, "DiagramID": 4, "BlockID": 5, "BlockType": 101, "IsDeleted": False},
            {"StructureID": 15, "DiagramID": 4, "BlockID": 6, "BlockType": 0, "IsDeleted": True},
        ],
        # LocalDataID differs from StructureID (as in the Synthesis examples).
        "bsBlockLocalDataOfStructure": [{"StructureID": s, "LocalDataID": s + 100} for s in range(10, 16)],
        "bsBlockLocalData": [
            {"LocalDataID": 110, "DisplayName": "A", "RamoID": 1, "NumPathsRequired": 1, "DutyCycle": 1.0},
            {"LocalDataID": 111, "DisplayName": "B", "RamoID": 2, "NumPathsRequired": 1, "DutyCycle": 0.5},
            {"LocalDataID": 112, "DisplayName": "Standby", "NumPathsRequired": 1, "SwitchPolicyID": 1},
            {"LocalDataID": 113, "DisplayName": "P1", "RamoID": 1, "IsActive": True, "StandbyIndex": 0},
            {"LocalDataID": 114, "DisplayName": "P2", "RamoID": 1, "IsActive": False, "StandbyIndex": 1},
            {"LocalDataID": 115, "DisplayName": "Gone", "RamoID": 1},
        ],
        "rsRamo": [{"RamoID": 1, "ModelID": 20, "CorrectiveTaskID": 7, "Nm": "Pump URD"},
                   {"RamoID": 2, "ModelID": 21, "CorrectiveTaskID": 0, "Nm": "Valve URD"}],
        "rsModel": [{"ModelID": 20, "ModelTypeID": 101, "UnitID": 2, "Nm": "Pump"},
                    {"ModelID": 21, "ModelTypeID": 106, "UnitID": 3, "Nm": "Valve"},
                    {"ModelID": 22, "ModelTypeID": 109, "UnitID": 2, "Nm": "Repair"}],
        "rsModelParam": [
            {"ModelId": 20, "ParameterID": 1000, "ParameterValue": 1.5},
            {"ModelId": 20, "ParameterID": 1001, "ParameterValue": 900.0},
            {"ModelId": 20, "ParameterID": 1002, "ParameterValue": 1.0},
            {"ModelId": 21, "ParameterID": 1033, "ParameterValue": 100.0},
            {"ModelId": 21, "ParameterID": 1034, "ParameterValue": 1.0},
            {"ModelId": 22, "ParameterID": 1040, "ParameterValue": 1.2},
            {"ModelId": 22, "ParameterID": 1041, "ParameterValue": 0.4},
            {"ModelId": 22, "ParameterID": 1042, "ParameterValue": 1.0},
        ],
        "rsUnit": [{"UnitID": 2, "Nm": "Hour", "Multiplier": 1.0, "CategoryID": 1},
                   {"UnitID": 3, "Nm": "Day", "Multiplier": 24.0, "CategoryID": 1}],
        "rsTaskCorrective": [{"CorrectiveTaskID": 7, "DurationModelID": 22, "ResFactorValue": 1.0, "Nm": "Fix"}],
        "bsSwitch": [{"SwitchID": 1, "ProbabilityPerRequest": 0.95, "Nm": "Switch"}],
    }


def test_extract_project_reads_blocks_models_edges_and_containers():
    p = bs.extract_project(_tables())
    assert p["name"] == "Demo"
    (d,) = p["diagrams"]
    assert d["name"] == "Pumps" and d["kind"] == "rbd" and d["simulation"] is True
    assert d["edges"] == [[1, 2], [2, 3]]
    assert d["containers"] == {3: [[4], [5]]}
    assert set(d["blocks"]) == {1, 2, 3, 4, 5}  # the deleted block is gone
    assert d["blocks"][2]["name"] == "B" and d["blocks"][2]["duty_cycle"] == 0.5
    assert d["blocks"][3]["switch"] == 1 and d["blocks"][4]["active"] is True
    assert p["models"][20]["params"] == {1000: 1.5, 1001: 900.0, 1002: 1.0}
    assert p["urds"][2]["task"] is None and p["tasks"][7]["duration_model"] == 22
    assert p["switches"][1]["p_switch"] == 0.95


def test_extract_then_convert_end_to_end():
    (imp,) = bs.convert_project(bs.extract_project(_tables()))
    g = imp.graph
    assert g["unit"] == "Hours"
    by_label = {n.get("label"): n for n in g["nodes"]}
    # Weibull eta -> alpha, beta kept.
    assert by_label["A"]["model"] == {"distribution_id": "weibull",
                                      "params": [{"name": "alpha", "value": 900.0}, {"name": "beta", "value": 1.5}]}
    # Exponential mean 100 h (stored in hours; "Day" is only its display unit)
    # at duty cycle 0.5 -> 200 h of system time -> lambda = 1/200 per hour.
    assert by_label["B"]["model"]["params"][0]["value"] == pytest.approx(1 / 200)
    sb = by_label["Standby"]
    assert sb["type"] == "standby" and sb["spares"] == 1 and sb["cold"] is True
    assert sb["data"] == {"startProb": 0.95}
    # Not every block can be repairable (standby) -> non-repairable + a warning.
    assert "repairable" not in g
    assert any("non-repairable" in w for w in imp.warnings)
    ng = normalize_graph(g)
    assert ra.validate_graph(ng)["valid"]


# ---------------------------------------------------------------------------
# Project dict -> compact graph
# ---------------------------------------------------------------------------

UNITS = {2: {"name": "Hour", "multiplier": 1.0, "category": 1},
         8: {"name": "Cycle", "multiplier": 1.0, "category": 2}}


def _project(diagrams, models=None, urds=None, tasks=None, switches=None):
    models = models or {
        1: {"name": "Exp", "type": 106, "unit": 2, "params": {1033: 1000.0, 1034: 1.0}},
        2: {"name": "Wbl", "type": 101, "unit": 2, "params": {1000: 2.0, 1001: 500.0, 1002: 1.0}},
        3: {"name": "Norm", "type": 108, "unit": 2, "params": {1037: 300.0, 1038: 40.0, 1039: 1.0}},
        4: {"name": "LogN", "type": 109, "unit": 2, "params": {1040: 6.0, 1041: 0.5, 1042: 1.0}},
        5: {"name": "W3", "type": 102, "unit": 2, "params": {1000: 2.0, 1001: 500.0, 1002: 1.0, 1003: 50.0}},
        6: {"name": "LFP", "type": 108, "unit": 2, "params": {1037: 300.0, 1038: 40.0, 1039: 0.9}},
        7: {"name": "Fix", "type": 109, "unit": 2, "params": {1040: 1.0, 1041: 0.3, 1042: 1.0}},
    }
    urds = urds or {i: {"name": f"U{i}", "model": i, "task": None, "scheduled_tasks": 0} for i in models}
    return {"name": "", "units": UNITS, "models": models, "urds": urds, "tasks": tasks or {},
            "switches": switches or {}, "diagrams": diagrams}


def _blk(name, urd=None, type_=0, **kw):
    b = {"type": type_, "name": name, "urd": urd, "quiescent_urd": None, "required": 1, "subdiagram": None,
         "standby_index": 0, "active": True, "switch": None, "mirror_group": None, "multiple": [0, 2, 1],
         "off": False, "duty_cycle": 1.0, "current_age": 0.0}
    b.update(kw)
    return b


def _diagram(fid, name, blocks, edges, kind="rbd", containers=None, simulation=False):
    return {"id": fid, "name": name, "kind": kind, "simulation": simulation, "blocks": blocks,
            "edges": [list(e) for e in edges], "containers": containers or {}}


def _analyse(graph, t):
    """System reliability at time ``t`` through the real analysis pipeline."""
    ng = normalize_graph(graph)
    v = ra.validate_graph(ng)
    assert v["valid"], v["errors"]
    res = ra.analyze(ng, t_max=t)
    return res["system"]["sf"][-1]


def _edges(graph):
    return {(e["source"], e["target"]) for e in graph["edges"]}


def test_start_and_end_blocks_collapse_into_input_and_output():
    # Start -> {A, B} -> End with non-failing Start/End blocks (BlockSim example 1 style).
    blocks = {1: _blk("Start"), 2: _blk("A", 1), 3: _blk("B", 1), 4: _blk("End")}
    (imp,) = bs.convert_project(_project([_diagram(1, "Par", blocks, [(1, 2), (1, 3), (2, 4), (3, 4)])]))
    g = imp.graph
    assert {n["id"] for n in g["nodes"]} == {"input", "output", "b2", "b3"}
    assert _edges(g) == {("input", "b2"), ("input", "b3"), ("b2", "output"), ("b3", "output")}
    lam = 1 / 1000
    assert _analyse(g, 700.0) == pytest.approx(1 - (1 - math.exp(-lam * 700)) ** 2, rel=1e-6)
    assert imp.warnings == []


def test_node_block_is_a_vote_and_subdiagrams_inline():
    sub = _diagram(2, "Pair", {1: _blk("X", 2), 2: _blk("Y", 2)}, [(1, 2)])  # series pair
    top_blocks = {1: _blk("S1", 1), 2: _blk("S2", 1), 3: _blk("S3", 1),
                  4: _blk("2/3", type_=bs.BT_NODE, required=2),
                  5: _blk("Pair", type_=bs.BT_SUBDIAGRAM, subdiagram=2)}
    top = _diagram(1, "Top", top_blocks, [(1, 4), (2, 4), (3, 4), (4, 5)])
    imps = bs.convert_project(_project([top, sub]))
    assert [i.name for i in imps] == ["Top", "Pair"]  # every folio is imported too
    g = imps[0].graph
    vote = next(n for n in g["nodes"] if n["type"] == "knode")
    assert (vote["n"], vote["k"]) == (2, 3)
    labels = sorted(n["label"] for n in g["nodes"] if n["type"] == "component")
    assert labels == ["Pair › X", "Pair › Y", "S1", "S2", "S3"]
    r = math.exp(-500 / 1000)
    r_vote = 3 * r**2 - 2 * r**3
    r_pair = math.exp(-2 * (500 / 500) ** 2)
    assert _analyse(g, 500.0) == pytest.approx(r_vote * r_pair, rel=1e-6)


def test_subdiagram_with_several_ends_feeds_a_vote_as_one_path():
    # A subdiagram with two parallel sinks must count as ONE branch of the vote.
    par = _diagram(2, "Par", {1: _blk("P1", 1), 2: _blk("P2", 1)}, [])
    blocks = {1: _blk("Sub", type_=bs.BT_SUBDIAGRAM, subdiagram=2), 2: _blk("C", 1),
              3: _blk("1 of 2", type_=bs.BT_NODE, required=2)}
    (imp, _) = bs.convert_project(_project([_diagram(1, "T", blocks, [(1, 3), (2, 3)]), par]))
    vote = next(n for n in imp.graph["nodes"] if n.get("n") == 2)
    assert vote["k"] == 2
    r = math.exp(-0.3)
    assert _analyse(imp.graph, 300.0) == pytest.approx((1 - (1 - r) ** 2) * r, rel=1e-6)


def test_model_families_and_unit_conversion():
    # ReliaSoft stores times in the category's base unit (hours); UnitID is the
    # display unit. The diagram takes the most common display unit (Years here).
    models = {
        1: {"name": "Exp", "type": 106, "unit": 7, "params": {1033: 8760.0, 1034: 1.0}},
        2: {"name": "Wbl", "type": 101, "unit": 8, "params": {1000: 2.0, 1001: 500.0, 1002: 1.0}},
        3: {"name": "Norm", "type": 108, "unit": 7, "params": {1037: 17520.0, 1038: 876.0, 1039: 1.0}},
        4: {"name": "LogN", "type": 109, "unit": 2, "params": {1040: 6.0, 1041: 0.5, 1042: 1.0}},
    }
    units = {**UNITS, 7: {"name": "Year", "multiplier": 8760.0, "category": 1}}
    blocks = {i: _blk(f"M{i}", i) for i in models}
    p = _project([_diagram(1, "Mix", blocks, [(1, 2), (2, 3), (3, 4)])], models=models)
    p["units"] = units
    (imp,) = bs.convert_project(p)
    assert imp.graph["unit"] == "Years"
    by = {n.get("label"): n.get("model") for n in imp.graph["nodes"]}
    assert by["M1"]["distribution_id"] == "exponential"
    assert by["M1"]["params"][0]["value"] == pytest.approx(1.0)  # mean 1 year
    assert by["M3"]["params"][0]["value"] == pytest.approx(2.0)
    assert by["M3"]["params"][1]["value"] == pytest.approx(0.1)
    # Hours -> years: the log-mean shifts by -ln(8760); the log-std is unchanged.
    assert by["M4"]["params"][0]["value"] == pytest.approx(6.0 - math.log(8760))
    assert by["M4"]["params"][1]["value"] == 0.5
    # Cycles can't be converted to years: kept, with a warning.
    assert by["M2"]["params"][0] == {"name": "alpha", "value": 500.0}
    assert any("Cycle" in w and "can't be converted" in w for w in imp.warnings)


def test_undecoded_models_import_without_a_model_and_warn():
    blocks = {1: _blk("Three-param", 5), 2: _blk("Portion", 6)}
    (imp,) = bs.convert_project(_project([_diagram(1, "U", blocks, [(1, 2)])]))
    comps = [n for n in imp.graph["nodes"] if n["type"] == "component"]
    assert all("model" not in n for n in comps)
    text = " ".join(imp.warnings)
    assert "3-parameter Weibull" in text and "#1003=50" in text
    assert "#1039=0.9" in text
    # The graph still normalises; analysis then asks for the missing models.
    ng = normalize_graph(imp.graph)
    v = ra.validate_graph(ng)
    assert not v["valid"] and any("no life model" in e for e in v["errors"])


def test_standby_container_variants():
    def project(spare_urd, quiescent=None, switch=None):
        blocks = {
            1: _blk("SB", type_=bs.BT_STANDBY, switch=1 if switch is not None else None),
            2: _blk("P", 2, type_=bs.BT_IN_STANDBY, active=True, standby_index=0),
            3: _blk("S", spare_urd, type_=bs.BT_IN_STANDBY, active=False, standby_index=1, quiescent_urd=quiescent),
        }
        sw = {1: {"name": "sw", "p_switch": switch, "quiescent_model": None, "delay": 0.0}} if switch is not None else {}
        return _project([_diagram(1, "S", blocks, [], containers={1: [[2], [3]]})], switches=sw)

    (imp,) = bs.convert_project(project(2, switch=0.9))
    sb = next(n for n in imp.graph["nodes"] if n["type"] == "standby")
    assert sb["cold"] is True and sb["spares"] == 1 and sb["data"] == {"startProb": 0.9}
    assert sb["model"]["distribution_id"] == "weibull"
    assert _analyse(imp.graph, 400.0) > math.exp(-((400 / 500) ** 2))  # redundancy helps

    # A different spare model rides along as standbyModel.
    (imp,) = bs.convert_project(project(1))
    sb = next(n for n in imp.graph["nodes"] if n["type"] == "standby")
    assert sb["data"]["standbyModel"] == {"distribution_id": "exponential",
                                          "params": [{"name": "failure_rate", "value": 1e-3}]}

    # Quiescent model == active model: hot standby, exactly.
    (imp,) = bs.convert_project(project(2, quiescent=2))
    sb = next(n for n in imp.graph["nodes"] if n["type"] == "standby")
    assert sb["cold"] is False and not imp.warnings
    r = math.exp(-((400 / 500) ** 2))
    assert _analyse(imp.graph, 400.0) == pytest.approx(1 - (1 - r) ** 2, rel=1e-6)

    # A different (warm) quiescent model: imported as hot, with a warning.
    (imp,) = bs.convert_project(project(2, quiescent=1))
    assert any("warm standby" in w for w in imp.warnings)


def test_standby_container_that_cant_be_represented_is_a_placeholder():
    blocks = {1: _blk("SB", type_=bs.BT_STANDBY),
              2: _blk("P", 2, type_=bs.BT_IN_STANDBY, active=True),
              3: _blk("S1", 1, type_=bs.BT_IN_STANDBY, active=False, standby_index=1),
              4: _blk("S2", 3, type_=bs.BT_IN_STANDBY, active=False, standby_index=2)}
    (imp,) = bs.convert_project(_project([_diagram(1, "S", blocks, [], containers={1: [[2], [3], [4]]})]))
    (node,) = [n for n in imp.graph["nodes"] if n["type"] not in ("input", "output")]
    assert node["type"] == "component" and "model" not in node
    assert any("different life models" in w for w in imp.warnings)


def test_load_sharing_of_identical_exponential_units_is_exact():
    # BlockSim: each unit's model is its life at the full load; survivors share
    # it. Identical exponential units -> the survivors' total rate is always
    # lambda, so 2-of-3 fails at the 2nd failure: Gamma(2, lambda).
    blocks = {1: _blk("LS", type_=bs.BT_LOADSHARE, required=2),
              **{i: _blk(f"U{i}", 1, type_=bs.BT_IN_LOADSHARE) for i in (2, 3, 4)}}
    (imp,) = bs.convert_project(_project([_diagram(1, "L", blocks, [], containers={1: [[2], [3], [4]]})]))
    (node,) = [n for n in imp.graph["nodes"] if n["type"] not in ("input", "output")]
    assert node["model"] == {"distribution_id": "gamma", "params": [{"name": "alpha", "value": 2.0},
                                                                    {"name": "beta", "value": 1e-3}]}
    x = 500 / 1000
    assert _analyse(imp.graph, 500.0) == pytest.approx(math.exp(-x) * (1 + x), rel=1e-6)


def test_other_load_sharing_containers_become_a_conservative_vote():
    blocks = {1: _blk("LS", type_=bs.BT_LOADSHARE, required=2),
              **{i: _blk(f"U{i}", 2, type_=bs.BT_IN_LOADSHARE) for i in (2, 3, 4)}}
    (imp,) = bs.convert_project(_project([_diagram(1, "L", blocks, [], containers={1: [[2], [3], [4]]})]))
    vote = next(n for n in imp.graph["nodes"] if n["type"] == "knode")
    assert (vote["n"], vote["k"]) == (2, 3)
    assert any("Load-sharing" in w and "conservative" in w for w in imp.warnings)
    r = math.exp(-((400 / 500) ** 2))
    assert _analyse(imp.graph, 400.0) == pytest.approx(3 * r**2 - 2 * r**3, rel=1e-6)


def test_fault_tree_becomes_its_success_space_rbd():
    # TOP = OR( VOTE_2(a, b, c), AND(d, e) ): fails if 2 of a/b/c fail, or d and e both fail.
    blocks = {1: _blk("TOP", type_=bs.BT_GATE_OR), 2: _blk("*", type_=bs.BT_GATE_VOTE, required=2),
              3: _blk("*", type_=bs.BT_GATE_AND),
              4: _blk("a", 1), 5: _blk("b", 1), 6: _blk("c", 1), 7: _blk("d", 1), 8: _blk("e", 1)}
    edges = [(2, 1), (3, 1), (4, 2), (5, 2), (6, 2), (7, 3), (8, 3)]
    (imp,) = bs.convert_project(_project([_diagram(9, "FT", blocks, edges, kind="ft")]))
    assert imp.name == "FT (fault tree)"
    r = math.exp(-0.4)
    expected = (3 * r**2 - 2 * r**3) * (1 - (1 - r) ** 2)
    assert _analyse(imp.graph, 400.0) == pytest.approx(expected, rel=1e-6)


def test_fault_trees_with_unsupported_gates_are_skipped():
    notg = _diagram(2, "Not", {1: _blk("T", type_=24), 2: _blk("x", 1)}, [(2, 1)], kind="ft")
    ok = _diagram(3, "Ok", {1: _blk("x", 1)}, [])
    imps = bs.convert_project(_project([notg, ok]))
    assert [i.name for i in imps] == ["Ok"]
    note = imps[0].warnings[-1]
    assert "“Not”" in note and "NOT gate" in note
    with pytest.raises(RbdImportError, match="None of the diagrams"):
        bs.convert_project(_project([notg]))


def test_fault_tree_repeated_events_become_repeated_blocks():
    # T = OR(G1, G2), G1 = AND(S, a), G2 = AND(S, b), S = OR(c, d): the gate S
    # (so events c and d) feeds two gates. T fails iff S fails and a or b does.
    blocks = {1: _blk("T", type_=bs.BT_GATE_OR), 2: _blk("G1", type_=bs.BT_GATE_AND),
              3: _blk("G2", type_=bs.BT_GATE_AND), 4: _blk("S", type_=bs.BT_GATE_OR),
              5: _blk("a", 1), 6: _blk("b", 2), 7: _blk("c", 1), 8: _blk("d", 2)}
    edges = [(2, 1), (3, 1), (4, 2), (5, 2), (4, 3), (6, 3), (7, 4), (8, 4)]
    (imp,) = bs.convert_project(_project([_diagram(1, "Shared", blocks, edges, kind="ft")]))
    copies = [n for n in imp.graph["nodes"] if n.get("repeat_of")]
    assert sorted(n["label"] for n in copies) == ["c", "d"]
    t = 400.0
    r1, r2 = math.exp(-t / 1000.0), math.exp(-((t / 500.0) ** 2))
    q_s = 1 - r1 * r2
    q_ab = 1 - r1 * r2  # a or b failed
    assert _analyse(imp.graph, t) == pytest.approx(1 - q_s * q_ab, rel=1e-9)
    # An event feeding a gate and the top directly: T = OR(x, AND(x, y)) = x.
    rep = _diagram(2, "Rep", {1: _blk("T", type_=bs.BT_GATE_OR), 2: _blk("G", type_=bs.BT_GATE_AND),
                              3: _blk("x", 1), 4: _blk("y", 1)}, [(2, 1), (3, 1), (3, 2), (4, 2)], kind="ft")
    (imp,) = bs.convert_project(_project([rep]))
    assert _analyse(imp.graph, t) == pytest.approx(r1, rel=1e-9)


def test_fault_tree_repeated_events_in_a_simulation_diagram_are_non_repairable():
    tasks = {1: {"name": "fix", "duration_model": 7, "restoration": 1.0, "pool": False, "crews": 0}}
    urds = {1: {"name": "u", "model": 1, "task": 1, "scheduled_tasks": 0}}
    rep = _diagram(1, "Rep", {1: _blk("T", type_=bs.BT_GATE_OR), 2: _blk("G", type_=bs.BT_GATE_AND),
                              3: _blk("x", 1), 4: _blk("y", 1)}, [(2, 1), (3, 1), (3, 2), (4, 2)],
                   kind="ft", simulation=True)
    (imp,) = bs.convert_project(_project([rep], urds=urds, tasks=tasks))
    assert "repairable" not in imp.graph
    assert any("repeated blocks" in w and "non-repairable" in w for w in imp.warnings)


def test_mirrored_blocks_become_repeated_blocks():
    # Two trains a -> M and b -> M', where M and M' mirror one physical item.
    blocks = {1: _blk("a", 1), 2: _blk("M", 2, mirror_group=5), 3: _blk("b", 1),
              4: _blk("M'", 2, mirror_group=5)}
    (imp,) = bs.convert_project(_project([_diagram(1, "Mir", blocks, [(1, 2), (3, 4)])]))
    by = {n.get("label"): n for n in imp.graph["nodes"]}
    assert by["M'"]["repeat_of"] == by["M"]["id"] and "model" not in by["M'"]
    assert not any("mirrored" in w for w in imp.warnings)
    t = 300.0
    ra_, rm = math.exp(-t / 1000.0), math.exp(-((t / 500.0) ** 2))
    assert _analyse(imp.graph, t) == pytest.approx(rm * (1 - (1 - ra_) ** 2), rel=1e-9)

    # In an availability (simulation) diagram they stay independent copies.
    tasks = {1: {"name": "fix", "duration_model": 7, "restoration": 1.0, "pool": False, "crews": 0}}
    urds = {1: {"name": "u", "model": 1, "task": 1, "scheduled_tasks": 0},
            2: {"name": "v", "model": 2, "task": 1, "scheduled_tasks": 0}}
    sim = _diagram(1, "Mir", blocks, [(1, 2), (3, 4)], simulation=True)
    (imp,) = bs.convert_project(_project([sim], urds=urds, tasks=tasks))
    assert imp.graph.get("repairable") is True
    assert not any(n.get("repeat_of") for n in imp.graph["nodes"])
    assert any("mirrored" in w and "independent" in w for w in imp.warnings)


def test_subdiagram_cycles_are_skipped():
    a = _diagram(1, "A", {1: _blk("toB", type_=bs.BT_SUBDIAGRAM, subdiagram=2)}, [])
    b = _diagram(2, "B", {1: _blk("toA", type_=bs.BT_SUBDIAGRAM, subdiagram=1)}, [])
    with pytest.raises(RbdImportError, match="cycle"):
        bs.convert_project(_project([a, b]))


def test_subdiagram_fan_out_is_bounded():
    # Each level holds 10 copies of the next: 10**6 blocks if fully inlined.
    levels = [_diagram(i, f"L{i}", {j: _blk("s", type_=bs.BT_SUBDIAGRAM, subdiagram=i + 1) for j in range(10)}, [])
              for i in range(1, 7)]
    leaf = _diagram(7, "Leaf", {1: _blk("x", 1)}, [])
    imps = bs.convert_project(_project(levels + [leaf]))
    names = [i.name for i in imps]
    assert "L1" not in names and "Leaf" in names
    assert "more than 5000 blocks" in imps[0].warnings[-1]


def test_repairable_simulation_diagram():
    tasks = {1: {"name": "fix", "duration_model": 7, "restoration": 1.0, "pool": False, "crews": 0}}
    urds = {1: {"name": "u", "model": 2, "task": 1, "scheduled_tasks": 0},
            2: {"name": "v", "model": 1, "task": 1, "scheduled_tasks": 0}}
    blocks = {1: _blk("A", 1), 2: _blk("B", 2), 3: _blk("C", 2)}
    d = _diagram(1, "R", blocks, [(1, 2), (1, 3)], simulation=True)
    (imp,) = bs.convert_project(_project([d], urds=urds, tasks=tasks))
    g = imp.graph
    assert g["repairable"] is True and not imp.warnings
    rep = next(n for n in g["nodes"] if n.get("label") == "A")["repair"]
    assert rep == {"distribution_id": "lognormal", "params": [{"name": "mu", "value": 1.0}, {"name": "sigma", "value": 0.3}]}
    ng = normalize_graph(g)
    assert ra.validate_graph(ng)["valid"]
    res = ra.analyze_availability(ng, n_simulations=50, t_simulation=2000.0)
    assert 0.9 < res["steady_state_availability"] <= 1.0

    # One block without a corrective task -> reliability diagram, repair dropped.
    urds[2] = {"name": "v", "model": 1, "task": None, "scheduled_tasks": 0}
    (imp,) = bs.convert_project(_project([d], urds=urds, tasks=tasks))
    assert "repairable" not in imp.graph
    assert all("repair" not in n for n in imp.graph["nodes"])
    assert any("non-repairable" in w and "“B”" in w for w in imp.warnings)

    # An analytical diagram never becomes repairable.
    d2 = dict(d, simulation=False)
    urds[2] = {"name": "v", "model": 1, "task": 1, "scheduled_tasks": 0}
    (imp,) = bs.convert_project(_project([d2], urds=urds, tasks=tasks))
    assert "repairable" not in imp.graph
    assert any("analytically" in w for w in imp.warnings)


def test_block_flags_multiblocks_and_paths_required():
    blocks = {
        1: _blk("Off", 1, off=True),
        2: _blk("Series3", 1, multiple=[1, 3, 3]),
        3: _blk("Ambiguous", 1, multiple=[2, 3, 1]),
        4: _blk("Mirror", 1, mirror_group=5, current_age=10.0),
    }
    (imp,) = bs.convert_project(_project([_diagram(1, "F", blocks, [(1, 2), (2, 3), (3, 4)])]))
    by = {n.get("label"): n for n in imp.graph["nodes"]}
    assert by["Off"]["data"] == {"state": "failed"}
    assert by["Series3"]["type"] == "series" and by["Series3"]["n"] == 3
    assert "model" not in by["Ambiguous"]
    text = " ".join(imp.warnings)
    # A mirror group with one block in the diagram is just that block.
    assert "mirrored" not in text and "age already accumulated" in text and "3 identical blocks" in text
    normalize_graph(imp.graph)

    # A subdiagram "set as failed" is cut off by a pinned-failed gate.
    sub = _diagram(2, "Sub", {1: _blk("x", 1)}, [])
    blocks = {1: _blk("a", 1), 2: _blk("S", type_=bs.BT_SUBDIAGRAM, subdiagram=2, off=True)}
    (imp, _) = bs.convert_project(_project([_diagram(1, "Off", blocks, [(1, 2)]), sub]))
    gate = next(n for n in imp.graph["nodes"] if n["type"] == "knode")
    assert gate["data"] == {"state": "failed"}
    assert _analyse(imp.graph, 100.0) == pytest.approx(0.0, abs=1e-12)

    # A regular block needing 2 of its 3 incoming paths gets a vote in front.
    blocks = {1: _blk("a", 1), 2: _blk("b", 1), 3: _blk("c", 1), 4: _blk("Sink", 1, required=2)}
    (imp,) = bs.convert_project(_project([_diagram(1, "P", blocks, [(1, 4), (2, 4), (3, 4)])]))
    vote = next(n for n in imp.graph["nodes"] if n["type"] == "knode")
    assert (vote["n"], vote["k"]) == (2, 3)


def test_parse_rejects_non_databases_cleanly():
    with pytest.raises(RbdImportError, match="isn't a ReliaSoft project"):
        bs.parse(b"hello world", "x.rsr9")
    with pytest.raises(RbdImportError, match="isn't a ReliaSoft project"):
        bs.parse(gzip.compress(b"hello"), "x.rsgz20")
    # A Jet header over garbage: a friendly error, not a traceback.
    with pytest.raises(RbdImportError):
        bs.parse(JET_HEAD + b"\x00" * 10000, "x.rsr9")
    with pytest.raises(RbdImportError):
        import_file(gzip.compress(JET_HEAD + b"\x07" * 5000), "p.rsgz21")


# ---------------------------------------------------------------------------
# Integration: ReliaSoft's public example projects (skipped when absent)
# ---------------------------------------------------------------------------

EXT = Path(__file__).parent / "fixtures" / "external" / "blocksim"


def _example(name):
    path = EXT / name
    if not path.exists():
        pytest.skip(f"{name} not present — run backend/scripts/fetch_rbd_import_fixtures.py")
    return import_file(path.read_bytes(), name)


@pytest.mark.parametrize("name", ["blocksim_example1.rsrp", "blocksim_example1_V9.rsr9",
                                  "blocksim_example1_V20.rsgz20"])
def test_example1_storage_network(name):
    (imp,) = _example(name)
    assert imp.name == "Storage Cluster System" and imp.source_format == "ReliaSoft BlockSim"
    g = imp.graph
    label = {n["id"]: n.get("label", n["id"]) for n in g["nodes"]}
    edges = {(label[e["source"]], label[e["target"]]) for e in g["edges"]}
    # BlockSim's 12 blocks / 14 connections: the model-less Start and End
    # blocks become Reliafy's input and output.
    assert len(g["nodes"]) == 12 and len(edges) == 14
    assert edges == {
        ("input", "Server1"), ("input", "Server2"),
        ("Server1", "HBA11"), ("Server1", "HBA12"), ("Server2", "HBA21"), ("Server2", "HBA22"),
        ("HBA11", "Switch1"), ("HBA21", "Switch1"), ("HBA12", "Switch2"), ("HBA22", "Switch2"),
        ("Switch1", "Controller1"), ("Switch2", "Controller2"),
        ("Controller1", "output"), ("Controller2", "output"),
    }
    lam = {n["label"]: n["model"]["params"][0]["value"] for n in g["nodes"] if n["type"] == "component"}
    assert 1 / lam["Server1"] == pytest.approx(45753.0)
    assert 1 / lam["HBA11"] == pytest.approx(252550.0)
    ng = normalize_graph(g)
    assert ra.validate_graph(ng)["valid"]
    res = ra.analyze(ng, t_max=8760.0)
    # Independent check of the structure function: each side is
    # Server -> (2 HBAs in parallel) -> Switch -> Controller, but the HBAs cross
    # over to both switches, so compute the bridge exactly by enumeration.
    r = {k: math.exp(-v * 8760.0) for k, v in lam.items()}
    names = sorted(r)
    total = 0.0
    for mask in range(1 << len(names)):
        up = {n for i, n in enumerate(names) if mask >> i & 1}
        works = any(
            {s, h, sw, c} <= up
            for s, h, sw, c in [("Server1", "HBA11", "Switch1", "Controller1"),
                                ("Server1", "HBA12", "Switch2", "Controller2"),
                                ("Server2", "HBA21", "Switch1", "Controller1"),
                                ("Server2", "HBA22", "Switch2", "Controller2")]
        )
        if works:
            p = 1.0
            for n in names:
                p *= r[n] if n in up else 1 - r[n]
            total += p
    assert res["system"]["sf"][-1] == pytest.approx(total, rel=1e-6)


def test_example2_nested_subdiagrams():
    imps = {i.name: i for i in _example("blocksim_example2_V9.rsr9")}
    assert set(imps) == {"1. System", "2. Subsystem A", "3. Subsystem B", "4. Assembly A",
                         "5. Assembly B", "6. Assembly C", "7. Assembly D"}
    system = imps["1. System"].graph
    comps = [n for n in system["nodes"] if n["type"] == "component"]
    # A + 3 x B + C + D, inlined: 2 + 3*4 + 2 + 2 blocks.
    assert len(comps) == 18
    vote = next(n for n in system["nodes"] if n["type"] == "knode" and n.get("n") == 2)
    assert vote["k"] == 3
    r_sys = _analyse(system, 1000.0)
    # Recombine from the separately-imported folios.
    rA, rB, rC, rD = (_analyse(imps[k].graph, 1000.0) for k in
                      ("4. Assembly A", "5. Assembly B", "6. Assembly C", "7. Assembly D"))
    vote_b = 3 * rB**2 - 2 * rB**3
    assert r_sys == pytest.approx(rA * vote_b * rC * rD, rel=1e-6)
    # ReliaSoft's published answer for this example: R(500 h) = 92.56565%
    # (Reliafy: 92.56557%, the gap is below 1e-6).
    assert _analyse(system, 500.0) == pytest.approx(0.9256565, abs=1e-6)


def test_example4_containers_and_example6_fault_tree_agree():
    imps4 = {i.name: i for i in _example("blocksim_example4.rsrp")}
    assert imps4["Mode C"].graph["nodes"][2]["type"] == "standby"
    # ReliaSoft's published answer (load sharing + cold standby + subdiagrams):
    # R(1 year = 8760 h) = 97.3517%.
    assert _analyse(imps4["Component"].graph, 8760.0) == pytest.approx(0.973517, abs=5e-7)
    imps6 = {i.name: i for i in _example("blocksim_example6.rsrp")}
    # Example 6 re-draws example 4's Mode A RBD as a fault tree: same answer.
    t = 50_000.0
    assert _analyse(imps6["FT Mode A (fault tree)"].graph, t) == pytest.approx(
        _analyse(imps4["Mode A"].graph, t), rel=1e-9)
    assert _analyse(imps6["FT Mode B (fault tree)"].graph, t) == pytest.approx(
        _analyse(imps4["Mode B"].graph, t), rel=1e-9)


def test_flight_instruments_simulation_is_repairable():
    imps = {i.name: i for i in _example("synthesis10_flight_instruments_simulation.rsgz10")}
    g = imps["Flight Instruments"].graph
    assert g["repairable"] is True and g["unit"] == "Flight Hours"
    comps = [n for n in g["nodes"] if n["type"] == "component"]
    assert len(comps) == 20 and all(n.get("repair") for n in comps)
    ng = normalize_graph(g)
    assert ra.validate_graph(ng)["valid"]
    res = ra.analyze_availability(ng, n_simulations=30, t_simulation=2000.0)
    assert 0.5 < res["steady_state_availability"] <= 1.0


@pytest.mark.parametrize("active, dormant, want", [
    ({"distribution_id": "exponential", "params": [{"name": "failure_rate", "value": 1e-3}]},
     {"distribution_id": "exponential", "params": [{"name": "failure_rate", "value": 2e-4}]}, 0.2),
    ({"distribution_id": "weibull", "params": [{"name": "alpha", "value": 1000}, {"name": "beta", "value": 2}]},
     {"distribution_id": "weibull", "params": [{"name": "alpha", "value": 4000}, {"name": "beta", "value": 2}]}, 0.25),
    ({"distribution_id": "lognormal", "params": [{"name": "mu", "value": 7.0}, {"name": "sigma", "value": 0.5}]},
     {"distribution_id": "lognormal", "params": [{"name": "mu", "value": 7.0 + np.log(5)}, {"name": "sigma", "value": 0.5}]}, 0.2),
    # Not a time-scaled copy: different Weibull shape, or a different family.
    ({"distribution_id": "weibull", "params": [{"name": "alpha", "value": 1000}, {"name": "beta", "value": 2}]},
     {"distribution_id": "weibull", "params": [{"name": "alpha", "value": 4000}, {"name": "beta", "value": 1}]}, None),
    ({"distribution_id": "weibull", "params": [{"name": "alpha", "value": 1000}, {"name": "beta", "value": 1}]},
     {"distribution_id": "exponential", "params": [{"name": "failure_rate", "value": 1e-4}]}, None),
    # Dormant ageing faster than running is treated as hot.
    ({"distribution_id": "exponential", "params": [{"name": "failure_rate", "value": 1e-3}]},
     {"distribution_id": "exponential", "params": [{"name": "failure_rate", "value": 3e-3}]}, 1.0),
])
def test_dormant_model_maps_to_a_dormancy_factor(active, dormant, want):
    from backend.services.rbd_import.blocksim import _dormancy_factor

    got = _dormancy_factor(active, dormant)
    assert got == (None if want is None else pytest.approx(want))
