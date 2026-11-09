"""Build the library's NSWC-11 data file from the chapter modules.

    python -m backend.scripts.build_nswc11            # writes the data file
    python -m backend.scripts.build_nswc11 --check    # fails if it's out of date

The source is the *Handbook of Reliability Prediction Procedures for
Mechanical Equipment* (CARDEROCKDIV, NSWC-11, May 2011, Naval Surface Warfare
Center Carderock Division): "Approved for Public Release; Distribution is
Unlimited", a U.S. Navy work. Unlike the other sources, nothing is parsed from
the PDF: each component's model (its base rate, condition factors, inputs and
the handbook's limits on them) is written by hand in
``backend/scripts/nswc11/chNN_*.py`` from the handbook's pages, each cited by
chapter, page and equation. The PDF isn't committed; its SHA-256 is recorded
so a revised handbook is a reviewed change.

The handbook's preface asks two things of anything built on it, and the data
carries both: equations only with their procedures and parameter limits (every
input has its range, checked when a model is evaluated), and a statement that
CDNSWC and the Navy did not take part in or approve the product (the source's
licence note and caveats, shown wherever the models are).
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import pkgutil
import sys
from pathlib import Path

from backend.library import covariate, schema
from backend.scripts import nswc11

SOURCE_ID = "nswc-11"
OUT = Path(__file__).resolve().parents[1] / "library" / "data" / f"{SOURCE_ID}.json"
DATA_VERSION = 1
RETRIEVED = "2026-11-09"
PDF_SHA256 = "942867dee3ac372b554b93fc596b6443984c516521c5fc95dcdd875017a59fc2"
TITLE = "Handbook of Reliability Prediction Procedures for Mechanical Equipment"
PUBLISHER = "Naval Surface Warfare Center, Carderock Division (U.S. Navy)"
REPORT = "CARDEROCKDIV, NSWC-11"
URL = "https://www.navsea.navy.mil/Home/Warfare-Centers/NSWC-Carderock/"
DISCLAIMER = ("CDNSWC (the Naval Surface Warfare Center, Carderock Division) and the U.S. Navy did not take part in "
              "making Reliafy and do not approve it. The handbook is the result of a research programme, not an "
              "official DoD document.")
ATTRIBUTION = ("Source: Handbook of Reliability Prediction Procedures for Mechanical Equipment, CARDEROCKDIV NSWC-11 "
               "(Naval Surface Warfare Center, Carderock Division, May 2011). Approved for public release; "
               "distribution is unlimited. A U.S. Government work; the models are written out by Reliafy with the "
               "handbook's procedures and parameter limits. " + DISCLAIMER)

CHAPTERS = {
    3: "Seals and gaskets", 4: "Springs", 5: "Solenoids, contactors", 6: "Valve assemblies", 7: "Bearings",
    8: "Gears and splines", 9: "Actuators", 10: "Pumps", 11: "Fluid filters", 12: "Brakes and clutches",
    13: "Compressors", 14: "Electric motors", 15: "Accumulators, reservoirs", 16: "Threaded fasteners",
    17: "Mechanical couplings", 18: "Slider crank mechanisms", 19: "Sensors and transducers", 20: "Shafts",
    21: "Belt and chain drives", 22: "Fluid conductors", 23: "Miscellaneous parts",
}

SOURCE = {
    "id": SOURCE_ID,
    "name": "NSWC-11: covariate models for mechanical parts (base rate × condition factors)",
    "short_name": "NSWC-11",
    "publisher": PUBLISHER,
    "title": TITLE,
    "report": REPORT,
    "edition": "May 2011",
    "year": 2011,
    "url": URL,
    "home": URL,
    "basis": "prediction_model",
    "licence": {
        "id": "us-government-work",
        "name": "U.S. Government work (no copyright asserted)",
        "attribution": ATTRIBUTION,
        "note": ("A U.S. Navy handbook marked \"Approved for Public Release; Distribution is Unlimited\". Its preface "
                 "asks that equations are never used without their procedures and parameter limits, and that any "
                 "product using it states that CDNSWC and the Navy have not participated in its development or "
                 "approved it. " + DISCLAIMER),
    },
    "description": ("Covariate models for mechanical parts: each part's failure rate is a base rate scaled by factors "
                    "for the conditions it works in (load, speed, temperature, pressure, contamination, material and "
                    "more), with the handbook's limits on every input. Seals, springs, solenoids, valves, bearings, "
                    "gears, actuators, pumps, filters, brakes and clutches, compressors, electric motors, "
                    "accumulators, fasteners, couplings, slider cranks, sensors, shafts, belt and chain drives, "
                    "fluid conductors and miscellaneous parts."),
    "caveats": [
        DISCLAIMER,
        "A handbook prediction model, not failures counted in service: never mix it with field data.",
        "Each model is only as good as the conditions you give it. Outside the handbook's limits Reliafy refuses or "
        "warns, and says which limit and on which page.",
        "The handbook says its equations were validated only in part, with limited funding: use it to compare "
        "designs and find the weak parts, not as a measure of how your equipment will fail.",
        "Some rates are per million cycles or operations, not hours: a prediction needs how many there are an hour.",
    ],
    "retrieved": RETRIEVED,
    "sha256": {"nswc11.pdf": PDF_SHA256},
    "table": "Chapters 3 to 23: each component's failure rate model, its multiplying factors and their limits",
    "disclaimer": DISCLAIMER,
}

UNIT_AS_GIVEN = covariate.RATE_UNITS


def chapter_modules(lenient: bool = False) -> list:
    names = sorted(m.name for m in pkgutil.iter_modules(nswc11.__path__) if m.name.startswith("ch"))
    out = []
    for n in names:
        try:
            out.append(importlib.import_module(f"backend.scripts.nswc11.{n}"))
        except Exception as exc:  # noqa: BLE001 - lenient builds report and skip a broken chapter
            if not lenient:
                raise
            print(f"Left out {n}: {type(exc).__name__}: {exc}", file=sys.stderr)
    return out


def _with_roles(slug: str, m: dict) -> dict:
    """The model with each input's role (design, use or environment) from roles.py, where every
    input's is said once, reviewed in one place rather than scattered through the chapters."""
    from backend.scripts.nswc11.roles import ROLES

    mine = ROLES.get(slug) or {}
    inputs = []
    for i in m["inputs"]:
        role = i.get("role") or mine.get(i["name"])
        if role is None:
            raise ValueError(f"{slug}: input {i['name']} has no role in backend/scripts/nswc11/roles.py")
        inputs.append({**i, "role": role})
    return {**m, "inputs": inputs}


def _record(raw: dict) -> dict:
    m = _with_roles(raw["slug"], raw["covariate_model"])
    chapter = raw["chapter"]
    title = CHAPTERS[chapter]
    n_modes = len(m["modes"])
    return {
        "id": f"{SOURCE_ID}:{raw['slug']}",
        "version": 1,
        "source": SOURCE_ID,
        "source_code": f"Eq. {m['equation']}",
        "name": raw["name"],
        "label": f"{raw['name']} (NSWC-11 Eq. {m['equation']})",
        "equipment_type": raw["equipment_type"],
        "kind": covariate.KIND,
        "basis": "prediction_model",
        "failure_mode": {"code": "ALL", "name": "All its failure modes" if n_modes > 1 else "Any failure",
                         "meaning": (f"The sum of {n_modes} parts or failure modes, each a base rate scaled by "
                                     "its conditions." if n_modes > 1 else
                                     "Its failure rate as the handbook models it: a base rate scaled by its "
                                     "conditions.")},
        "failure_modes": raw.get("failure_modes") or [],
        "units": {"value": m["rate_unit"], "time_basis": "operating", "as_given": UNIT_AS_GIVEN[m["rate_unit"]]},
        "summary": {"mean": None},
        "covariate_model": m,
        "conditions": {"industry": "Mechanical equipment (handbook prediction)",
                       "chapter": f"Chapter {chapter}: {title}", "section": raw["section"]},
        "source_text": f"{title}: {raw['section']}",
        "citation": {"title": TITLE, "publisher": PUBLISHER, "report": REPORT, "year": 2011,
                     "table": f"Chapter {chapter}, section {raw['section'].split(' ')[0]}, Eq. {m['equation']}",
                     "page": m["page"], "chapter": chapter, "equation": m["equation"], "url": URL,
                     "retrieved": RETRIEVED},
        "licence": {"id": "us-government-work", "attribution": ATTRIBUTION},
        **({"notes": raw["notes"]} if raw.get("notes") else {}),
    }


def build(lenient: bool = False) -> dict:
    """Every chapter's records, checked. ``lenient`` (while chapters are being written): a chapter
    that won't import, or a record with problems (or that uses one that isn't there yet), is left
    out and reported instead of stopping the build."""
    records = []
    for mod in chapter_modules(lenient):
        for r in getattr(mod, "RECORDS", []):
            try:
                records.append(_record(r))
            except Exception as exc:  # noqa: BLE001
                if not lenient:
                    raise
                print(f"Left out {mod.__name__} {r.get('slug')}: {type(exc).__name__}: {exc}", file=sys.stderr)
    by_id = {r["id"]: r for r in records}
    if len(by_id) != len(records):
        raise SystemExit("Two records share an id.")

    def resolve(rid: str) -> dict:
        if rid not in by_id:
            raise LookupError(rid)
        return by_id[rid]

    while True:
        bad = {r["id"]: schema.problems(r) + covariate.problems(r, resolve) for r in records}
        bad = {k: v for k, v in bad.items() if v}
        if not bad:
            break
        if not lenient:
            raise SystemExit("Not written:\n" + "\n".join(p for v in bad.values() for p in v))
        for v in bad.values():
            print("Left out: " + "; ".join(v), file=sys.stderr)
        records = [r for r in records if r["id"] not in bad]
        by_id = {r["id"]: r for r in records}
    return {"schema": schema.SCHEMA_VERSION, "data_version": DATA_VERSION, "source": SOURCE, "skipped": [],
            "records": records}


def dumps(data: dict) -> str:
    return json.dumps(data, indent=1, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--check", action="store_true", help="fail if the data file isn't what the modules build")
    ap.add_argument("--lenient", action="store_true", help="leave out (and report) what doesn't pass, for drafts")
    args = ap.parse_args(argv)
    text = dumps(build(args.lenient))
    if args.check:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != text:
            print(f"{OUT} is out of date: run python -m backend.scripts.build_nswc11", file=sys.stderr)
            return 1
        return 0
    tmp = OUT.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, OUT)  # whole or not at all (several writers may build at once)
    print(f"Wrote {OUT} ({len(json.loads(text)['records'])} records).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
