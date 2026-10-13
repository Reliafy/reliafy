"""Reliafy Maintenance: importing positions and item history from a sheet."""

import pytest

from backend.maintenance import importer
from backend.maintenance.service import PROJECTORS, Invalid, Maintenance
from backend.maintenance.store import GraphStore

ROWS = [
    {"Functional location": "House > Pool > Pump", "Class": "Pool pump", "Equipment": "Astral CTX",
     "Serial": "A1", "Installed": "2018-01-10", "Removed": "2020-03-01", "Failed": "yes", "Failure mode": "Bearing"},
    {"Functional location": "House > Pool > Pump", "Class": "Pool pump", "Equipment": "Astral CTX",
     "Serial": "A2", "Installed": "2020-03-01", "Removed": "2023-05-20", "Failed": "yes", "Failure mode": "bearing"},
    {"Functional location": "House > Pool > Pump", "Class": "Pool pump", "Equipment": "Astral CTX",
     "Serial": "A3", "Installed": "2023-05-20", "Removed": "", "Failed": "", "Failure mode": ""},
    {"Functional location": "House > Pool > Filter", "Class": "", "Equipment": "", "Serial": "",
     "Installed": "", "Removed": "", "Failed": "", "Failure mode": ""},
]


def test_dry_run_then_import_builds_positions_history_and_failures():
    m = Maintenance(GraphStore(":memory:", PROJECTORS), "user-i")
    preview = importer.run(m, ROWS, dry_run=True)
    assert preview == {"rows": 4, "positions_created": 4, "items_created": 3, "fitments": 3, "failures": 2,
                       "dry_run": True}
    assert m.tree() == []  # nothing written by a dry run
    done = importer.run(m, ROWS)
    assert done["positions_created"] == 4
    [house] = m.tree()
    pool = house["children"][0]
    assert [c["name"] for c in pool["children"]] == ["Filter", "Pump"]
    pump = next(c for c in pool["children"] if c["name"] == "Pump")
    rows = m.life_data(pump["id"])
    assert [(r["c"], r["failure_mode"]) for r in rows] == [(0, "Bearing"), (0, "Bearing"), (1, None)]
    assert m.position_classes()[0]["failures"] == 2
    again = importer.run(m, ROWS[3:])  # existing positions are reused
    assert again["positions_created"] == 0


def test_bad_rows_write_nothing():
    m = Maintenance(GraphStore(":memory:", PROJECTORS), "user-i")
    bad = [dict(ROWS[0]), {**ROWS[1], "Installed": "2019-06-01"}]  # overlaps the first
    with pytest.raises(Invalid, match="two items"):
        importer.run(m, bad)
    with pytest.raises(Invalid, match="isn't a date"):
        importer.run(m, [{**ROWS[0], "Installed": "last spring"}])
    with pytest.raises(Invalid, match="position column"):
        importer.run(m, [{"Thing": "x"}])
    assert m.tree() == []


def test_a_csv_is_checked_before_its_parsed(monkeypatch):
    import pandas as pd

    def no_parse(*a, **k):
        raise AssertionError("parsed")

    monkeypatch.setattr(pd, "read_csv", no_parse)
    wide = b",".join(b"c%d" % i for i in range(importer.MAX_COLS + 1)) + b"\nx\n"
    with pytest.raises(Invalid, match="columns"):
        importer.rows_from_file(wide, "x.csv")
    with pytest.raises(Invalid, match="first line"):
        importer.rows_from_file(b"c" * (importer.MAX_LINE + 1) + b"\n", "x.csv")
    with pytest.raises(Invalid, match="rows"):
        importer.rows_from_file(b"position\n" + b"a\n" * (importer.MAX_ROWS + 1), "x.csv")
    with pytest.raises(Invalid, match="characters"):
        importer.rows_from_file(b"position\n" + b"a" * (importer.MAX_CELL + 1) + b"\n", "x.csv")
    with pytest.raises(Invalid, match="cells"):
        importer.rows_from_file(b"position\n" + b",".join([b"a"] * (importer.MAX_COLS + 1)) + b"\n", "x.csv")


def test_a_small_csv_still_imports():
    rows = importer.rows_from_file(b"\xef\xbb\xbfposition,item,fitted\nHouse > Pump,Astral,2024-01-01\n\n", "x.csv")
    assert rows == [{"position": "House > Pump", "item": "Astral", "fitted": "2024-01-01"}]


def test_rows_given_directly_have_the_same_limits():
    m = Maintenance(GraphStore(":memory:", PROJECTORS), "user-i")
    with pytest.raises(Invalid, match="columns"):
        importer.run(m, [{f"c{i}": "" for i in range(importer.MAX_COLS + 1)}])
    with pytest.raises(Invalid, match="characters"):
        importer.run(m, [{"position": "a" * (importer.MAX_CELL + 1)}])
    with pytest.raises(Invalid, match="rows"):
        importer.run(m, [{"position": "a"}] * (importer.MAX_ROWS + 1))
