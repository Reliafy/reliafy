"""The one-off move of an RCM study's paragraph from a position's description
to its operating context (backend/scripts/move_operating_context.py), on a
synthetic workspace: a dry run writes nothing, --apply moves it once."""

import mongomock
import pytest

from backend.maintenance.service import PROJECTORS, Maintenance, shortened
from backend.maintenance.store import GraphStore
from backend.scripts import move_operating_context as move

ORG = "user-a"
STUDY = "The line runs two shifts a day.\nWet, dusty and hot in summer; the pumps see sand after rain."


@pytest.fixture()
def m():
    return Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")


def test_split_finds_the_paragraph():
    assert move.split("Slurry pump\n\nRuns flat out.\n\nAnd hot.") == ("Slurry pump", "Runs flat out.\n\nAnd hot.")
    assert move.split("Slurry pump\n  \nRuns flat out.") == ("Slurry pump", "Runs flat out.")
    assert move.split("Slurry pump") is None and move.split("") is None
    # With the study's text: only that text, as it is, cut to fit, or the whole description.
    assert move.split(f"Slurry pump\n\nNotes.\n\n{STUDY}", STUDY) == ("Slurry pump\n\nNotes.", STUDY)
    cut = shortened(STUDY, 60)[0]
    assert cut.endswith("…") and move.split(f"Slurry pump\n\n{cut}", STUDY) == ("Slurry pump", cut)
    assert move.split(STUDY, STUDY) == ("", STUDY)
    assert move.split("Slurry pump\n\nSomething else.", STUDY) is None


def test_dry_run_then_apply_then_nothing_more(m):
    a = m.create_position("Pump 1", description=f"Slurry pump\n\n{STUDY}")
    b = m.create_position("Pump 2", description=f"Slurry pump\n\n{STUDY}", operating_context="Standby.")
    c = m.create_position("Pump 3", description="Slurry pump")
    ids = [a["id"], b["id"], c["id"], "nope"]
    events = m.s.event_count(ORG)

    dry = move.run(m.s, ORG, ids)
    assert m.s.event_count(ORG) == events  # the real log is untouched
    assert m.position(a["id"])["description"] == f"Slurry pump\n\n{STUDY}"
    text = move.report(dry, dry_run=True)
    assert text.startswith("DRY RUN") and "would move" in text and "no such position" in text
    assert [r.get("skipped", "") for r in dry][2].startswith("nothing to move")

    real = move.run(m.s, ORG, ids, dry_run=False)
    assert [r.get("moved") for r in real[:2]] == [STUDY, STUDY]
    pa, pb, pc = (m.position(x) for x in ids[:3])
    assert (pa["description"], pa["operating_context"]) == ("Slurry pump", STUDY)
    assert (pb["description"], pb["operating_context"]) == ("Slurry pump", f"Standby.\n\n{STUDY}")
    assert (pc["description"], pc["operating_context"]) == ("Slurry pump", "")
    before = m.s.snapshot()
    m.s.rebuild()
    assert m.s.snapshot() == before

    events = m.s.event_count(ORG)
    again = move.run(m.s, ORG, ids, dry_run=False)
    assert all(r.get("skipped") for r in again) and m.s.event_count(ORG) == events


def test_by_the_study_text_leaves_other_paragraphs(m):
    p = m.create_position("Pump 1", description=f"Slurry pump\n\nInstalled with a VSD.\n\n{STUDY}",
                          operating_context=STUDY)
    [row] = move.run(m.s, ORG, [p["id"]], study_text=STUDY, dry_run=False)
    got = m.position(p["id"])
    # Already in the operating context: only taken off the description, never added twice.
    assert row["moved"] == STUDY and got["operating_context"] == STUDY
    assert got["description"] == "Slurry pump\n\nInstalled with a VSD."


def test_main_reads_the_study_and_is_a_dry_run_by_default(m, monkeypatch, capsys):
    from backend import db as db_module
    from backend.routers import maintenance as router

    db = mongomock.MongoClient()["move_ctx"]
    db.rcm_studies.insert_one({"_id": "study-9", "description": STUDY})
    monkeypatch.setattr(db_module, "_db", db)
    monkeypatch.setattr(db_module, "_simulated", True)
    monkeypatch.setattr(router, "_store", m.s)
    p = m.create_position("Pump 1", description=f"Slurry pump\n\n{STUDY}")

    assert move.main(["--org", ORG, "--study", "study-9", p["id"]]) == 0
    assert "DRY RUN" in capsys.readouterr().out
    assert m.position(p["id"])["operating_context"] == ""
    assert move.main(["--org", ORG, "--study", "nope", p["id"]]) == 1
    assert move.main(["--org", ORG, "--study", "study-9", "--apply", p["id"]]) == 0
    assert m.position(p["id"])["operating_context"] == STUDY
