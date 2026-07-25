"""The model reference must stay in step with the registries.

Two guarantees, both enforced here rather than by remembering:
  1. The generated catalogue.json matches what the registries currently hold.
  2. Every catalogued entry has prose written for it.

Add a distribution and this fails until the reference is updated — which is the
whole point of generating the catalogue instead of hand-writing it.
"""

import json
import pathlib
import re

import pytest

from backend.scripts.export_reference import OUT, build

CONTENT = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src" / "content" / "reference"


def test_catalogue_json_is_current():
    assert OUT.exists(), "run: python -m backend.scripts.export_reference"
    on_disk = json.loads(OUT.read_text())
    assert on_disk == build(), (
        "the committed reference catalogue is stale — regenerate it with:\n"
        "  python -m backend.scripts.export_reference"
    )


def _documented_ids(family_id: str) -> set:
    """Entry ids that have a `## <id>` section in the family's markdown."""
    path = CONTENT / f"{family_id}.md"
    if not path.exists():
        return set()
    return set(re.findall(r"^##[ \t]+(\S+)\s*$", path.read_text(), re.M))


@pytest.mark.parametrize("family", build()["families"], ids=lambda f: f["id"])
def test_every_entry_has_prose(family):
    documented = _documented_ids(family["id"])
    missing = [e["id"] for e in family["entries"] if e["id"] not in documented]
    assert not missing, (
        f"reference prose missing for {family['id']}: {', '.join(missing)}\n"
        f"add a `## <id>` section to frontend/src/content/reference/{family['id']}.md"
    )


def test_no_prose_for_entries_that_do_not_exist():
    """Catch the reverse drift: a section left behind after an id is removed."""
    stale = {}
    for family in build()["families"]:
        ids = {e["id"] for e in family["entries"]}
        extra = _documented_ids(family["id"]) - ids
        if extra:
            stale[family["id"]] = sorted(extra)
    assert not stale, f"reference prose for entries that no longer exist: {stale}"
