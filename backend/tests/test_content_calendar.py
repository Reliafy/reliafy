"""#344/#367: the machine-readable content calendar the drafting job reads."""

import pathlib
from datetime import date

import yaml

CALENDAR = pathlib.Path(__file__).resolve().parents[2] / ".github" / "content" / "calendar.yml"

EXPECTED = [
    ("2026-10-12", "tutorial", "Import your RBDs from BlockSim, Open-PSA, Galileo and Excel"),
    ("2026-10-19", "commentary", "Spreadsheets: where reliability analysis quietly goes wrong"),
    ("2026-10-26", "tutorial", "Verify a safety function's PFDavg and SIL"),
    ("2026-11-02", "whatsnew", "What's new in Reliafy: November 2026"),
    ("2026-11-09", "technical", "How long will this take? Survival analysis on our own run times"),
    ("2026-11-16", "commentary", "AI agents will read your failure data next: what to check"),
    ("2026-11-23", "tutorial", "Design to a target: reliability allocation"),
    ("2026-12-07", "whatsnew", "What's new in Reliafy: December 2026"),
    ("2026-12-14", "technical", "Failure modes that compete"),
    ("2026-12-21", "commentary", "Run to failure is a decision, not a default"),
    ("2027-01-04", "whatsnew", "What's new in Reliafy: January 2027"),
    ("2027-01-11", "technical", "to be chosen"),
    ("2027-01-18", "commentary", "to be chosen"),
    ("2027-01-25", "tutorial", "Production availability: energy lost, not just downtime"),
]


def _load():
    return yaml.safe_load(CALENDAR.read_text(encoding="utf-8"))


def test_calendar_parses_with_the_agreed_slots():
    cal = _load()
    slots = [(s["date"], s["type"], s["title"]) for s in cal["slots"]]
    assert slots == EXPECTED
    assert cal["timezone"] == "Australia/Brisbane" and cal["publish_time"] == "10:00"


def test_slots_are_well_formed():
    cal = _load()
    dates = [s["date"] for s in cal["slots"]]
    # Quoted strings (YAML would otherwise make dates objects), sorted, unique.
    assert all(isinstance(d, str) for d in dates)
    assert dates == sorted(dates) and len(set(dates)) == len(dates)
    for s in cal["slots"]:
        assert set(s) == {"date", "type", "title"}, s
        assert date.fromisoformat(s["date"]).weekday() == 0, f"{s['date']} isn't a Monday"
        assert s["type"] in cal["types"], s
        assert s["title"].strip()
    assert set(cal["types"]) == {"whatsnew", "technical", "commentary", "tutorial"}
    assert not set(cal["skipped_weeks"]) & set(dates)
    assert cal["cadence"]["short_posts_per_week"] == [2, 3]
    assert cal["cadence"]["evergreen_pages_per_month"] == [1, 2]


def test_one_whats_new_in_the_first_week_of_each_month():
    months = {}
    for s in _load()["slots"]:
        if s["type"] == "whatsnew":
            months.setdefault(s["date"][:7], []).append(s["date"])
    assert months == {"2026-11": ["2026-11-02"], "2026-12": ["2026-12-07"], "2027-01": ["2027-01-04"]}
    assert all(int(d[8:]) <= 7 for ds in months.values() for d in ds)
