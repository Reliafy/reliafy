"""Build the library's NRC / INL data file from the published report.

    pip install pdfplumber==0.11.10       # only this script needs it
    python -m backend.scripts.import_nrc_inl AvgPara2020.pdf [--retrieved 2026-10-23]

The source is Table 1 ("Component UR data and results") of *Industry-Average
Performance for Components and Initiating Events at U.S. Commercial Nuclear
Power Plants: 2020 Update* (INL/EXT-21-65055, November 2021), prepared by
Idaho National Laboratory for the U.S. Nuclear Regulatory Commission and
published at :data:`SOURCE_URL`. Download it by hand (one file; the report
isn't committed: it's 4.6 MB and the data file carries everything used). The
script checks the PDF's SHA-256 against :data:`SOURCE_SHA256`, so a changed
report can't slip in unnoticed, reads the table, turns each row into a
library record (:func:`record_from_row`, pure, so it's tested without the
PDF), checks every record (``backend.library.schema.problems``) and writes
``backend/library/data/nrc-inl-2020.json`` only when all of them pass.

What's kept from each row: the code, the source's description (as given),
the data source, failures, demands or hours, the number of components, the
distribution, the estimation method, the 5th / median / mean / 95th values,
alpha and beta, the error factor and the date range. Rows that aren't a
component failure distribution are skipped, each with its reason
(:data:`SKIPPED`): the report's other tables (train unavailability, special
events, initiating events) aren't read at all.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

SOURCE_ID = "nrc-inl-2020"
SOURCE_URL = "https://nrcoe.inl.gov/publicdocs/AvgPerf/AvgPara2020.pdf"
SOURCE_SHA256 = "fd7b697974ddb4db9400fefc2c70776d687ed2461dc2bf7e941630da70f3ae12"
#: Table 1 is on these PDF pages (1-based); the report's printed page number
#: is the PDF page less this offset (PDF page 30 is report page 6).
TABLE_PAGES = range(30, 39)
PAGE_OFFSET = 24
OUT = Path(__file__).resolve().parents[1] / "library" / "data" / f"{SOURCE_ID}.json"
DATA_VERSION = 1

TITLE = ("Industry-Average Performance for Components and Initiating Events at U.S. Commercial Nuclear "
         "Power Plants: 2020 Update")
PUBLISHER = "Idaho National Laboratory, for the U.S. Nuclear Regulatory Commission"
ATTRIBUTION = ("Source: Z. Ma, T. E. Wierman and K. J. Kvarfordt, Industry-Average Performance for Components "
               "and Initiating Events at U.S. Commercial Nuclear Power Plants: 2020 Update, INL/EXT-21-65055 "
               "(Idaho National Laboratory for the U.S. NRC, November 2021), Table 1. A U.S. Government work; "
               "republished by Reliafy.")

SOURCE = {
    "id": SOURCE_ID,
    "name": "NRC / INL industry-average parameter estimates (2020 update)",
    "short_name": "NRC/INL 2020",
    "publisher": PUBLISHER,
    "title": TITLE,
    "report": "INL/EXT-21-65055",
    "edition": "2020 update",
    "year": 2021,
    "url": SOURCE_URL,
    "home": "https://nrcoe.inl.gov/AvgPerf",
    "basis": "field_data",
    "licence": {
        "id": "us-government-work",
        "name": "U.S. Government work (no copyright asserted)",
        "attribution": ATTRIBUTION,
        "note": ("Prepared for the U.S. NRC under an NRC agreement; the report carries the standard U.S. "
                 "Government disclaimer and no copyright notice, and the NRC's site disclaimer says its "
                 "material has no restrictions on use and asks for credit."),
    },
    "description": ("Failure rates and per-demand failure probabilities for components at U.S. commercial "
                    "nuclear power plants, from operating experience 2006 to 2020 (some older), as gamma and "
                    "beta distributions with their 5th and 95th percentiles."),
    "caveats": [
        "Industry averages for U.S. nuclear power plants: generic estimates, not your equipment's own data.",
        "The report advises checking that these distributions are consistent with plant data before using "
        "them as Bayesian priors.",
        "Rates for leaks, spurious operation, plugging and similar modes are per calendar hour, whether the "
        "plant was running or shut down; fail-to-run rates are per hour of running.",
    ],
}

# ---- the report's components and failure modes, in the library's words ----------------------
#
# code: (name, equipment type, Appendix A section, its first page). The appendix
# has each component's full data sheet; the record cites it so a reader can check.
COMPONENTS: dict[str, tuple[str, str, str, str]] = {
    "AOV": ("Air-operated valve", "valve", "A-1.1", "A-1"),
    "MOV": ("Motor-operated valve", "valve", "A-1.2", "A-4"),
    "BFV": ("Motor-operated butterfly valve", "valve", "A-1.2", "A-4"),
    "HOV": ("Hydraulic-operated valve", "valve", "A-1.3", "A-7"),
    "SOV": ("Solenoid-operated valve", "valve", "A-1.4", "A-9"),
    "EOV": ("Explosive-operated valve", "valve", "A-1.5", "A-11"),
    "VBV": ("Vacuum breaker valve", "valve", "A-1.6", "A-13"),
    "TBV": ("Turbine bypass valve", "valve", "A-1.7", "A-15"),
    "MSV": ("Main steam isolation valve", "valve", "A-1.8", "A-17"),
    "CKV": ("Check valve", "valve", "A-1.9", "A-19"),
    "XVM": ("Manual valve", "valve", "A-1.10", "A-22"),
    "FCV": ("Flow control valve", "valve", "A-1.11", "A-24"),
    "FRV": ("Feedwater regulating valve", "valve", "A-1.11", "A-24"),
    "MDP": ("Motor-driven pump", "pump", "A-2.1", "A-26"),
    "TDP": ("Turbine-driven pump", "pump", "A-2.2", "A-34"),
    "EDP": ("Engine-driven pump", "pump", "A-2.4", "A-38"),
    "PDP": ("Positive displacement pump", "pump", "A-2.5", "A-41"),
    "PMP": ("Pump volute (centrifugal pump, driver excluded)", "pump", "A-2.6", "A-45"),
    "EDG": ("Emergency diesel generator", "generator", "A-3.1", "A-46"),
    "HTG": ("Hydro turbine generator", "generator", "A-3.2", "A-49"),
    "CTG": ("Combustion turbine generator", "generator", "A-3.3", "A-50"),
    "HCS": ("High-pressure core spray diesel generator", "generator", "A-3.4", "A-51"),
    "SBO": ("Station blackout generator", "generator", "A-3.5", "A-52"),
    "SRV": ("Safety relief valve", "relief_valve", "A-4.1", "A-53"),
    "SVV": ("Code safety valve", "relief_valve", "A-4.2", "A-55"),
    "PORV": ("Power-operated relief valve", "relief_valve", "A-4.3", "A-57"),
    "RVL": ("Low-capacity relief valve", "relief_valve", "A-4.4", "A-59"),
    "BCH": ("Battery charger", "electrical", "A-5.1", "A-61"),
    "BAT": ("Battery", "electrical", "A-5.2", "A-63"),
    "ABT": ("Automatic bus transfer switch", "electrical", "A-5.3", "A-64"),
    "CRB": ("Circuit breaker", "electrical", "A-5.4", "A-66"),
    "INV": ("Inverter", "electrical", "A-5.5", "A-69"),
    "BUS": ("Electrical bus", "electrical", "A-5.6", "A-70"),
    "MCC": ("Motor control centre", "electrical", "A-5.7", "A-71"),
    "TFM": ("Transformer", "electrical", "A-5.8", "A-72"),
    "SEQ": ("Load sequencer", "electrical", "A-5.9", "A-73"),
    "FUS": ("Fuse", "electrical", "A-5.10", "A-74"),
    "FLT": ("Filter", "filter_strainer", "A-6.1", "A-77"),
    "FLTSC": ("Self-cleaning strainer", "filter_strainer", "A-6.2", "A-79"),
    "SMP": ("Containment sump strainer", "filter_strainer", "A-6.3", "A-80"),
    "TSA": ("Travelling screen", "filter_strainer", "A-6.4", "A-81"),
    "TRK": ("Trash rack", "filter_strainer", "A-6.5", "A-82"),
    "BIS": ("Bistable (trip unit)", "instrument_control", "A-7.1", "A-83"),
    "PLF": ("Process logic (flow)", "instrument_control", "A-7.2", "A-84"),
    "PLL": ("Process logic (level)", "instrument_control", "A-7.2", "A-84"),
    "PLP": ("Process logic (pressure)", "instrument_control", "A-7.2", "A-84"),
    "PLDT": ("Process logic (temperature difference)", "instrument_control", "A-7.2", "A-84"),
    "STF": ("Flow sensor/transmitter", "instrument_control", "A-7.3", "A-85"),
    "STL": ("Level sensor/transmitter", "instrument_control", "A-7.3", "A-85"),
    "STP": ("Pressure sensor/transmitter", "instrument_control", "A-7.3", "A-85"),
    "STT": ("Temperature sensor/transmitter", "instrument_control", "A-7.3", "A-85"),
    "RTB": ("Reactor trip breaker", "instrument_control", "A-7.4", "A-86"),
    "MSW": ("Manual switch", "instrument_control", "A-7.5", "A-87"),
    "RLY": ("Relay", "instrument_control", "A-7.6", "A-88"),
    "CRD": ("Control rod drive", "control_rod", "A-8.1", "A-89"),
    "ROD": ("Control rod", "control_rod", "A-8.2", "A-91"),
    "HCU": ("Hydraulic control unit", "control_rod", "A-8.3", "A-92"),
    "AOD": ("Air-operated damper", "damper", "A-9.1", "A-93"),
    "HOD": ("Hydraulic-operated damper", "damper", "A-9.1", "A-93"),
    "MOD": ("Motor-operated damper", "damper", "A-9.1", "A-93"),
    "AHU": ("Air handling unit", "hvac", "A-9.2", "A-96"),
    "CHL": ("Chiller", "hvac", "A-9.3", "A-99"),
    "FAN": ("Ventilation fan", "fan", "A-9.4", "A-102"),
    "MDC": ("Motor-driven air compressor", "compressed_air", "A-10.1", "A-107"),
    "EDC": ("Engine-driven air compressor", "compressed_air", "A-10.1", "A-107"),
    "ADU": ("Air dryer", "compressed_air", "A-10.2", "A-110"),
    "ACC": ("Accumulator", "vessel_tank", "A-10.3", "A-111"),
    "CTF": ("Cooling tower fan", "fan", "A-10.4", "A-113"),
    "TNK": ("Tank", "vessel_tank", "A-10.5", "A-117"),
    "ORF": ("Orifice", "pipe", "A-10.6", "A-120"),
    "PIPE": ("Pipe", "pipe", "A-10.7", "A-121"),
    "HTX": ("Heat exchanger", "heat_exchanger", "A-10.8", "A-123"),
}

#: Failure mode codes: (plain name, what "failed" means).
MODES: dict[str, tuple[str, str]] = {
    "FTO": ("Fails to open", "Does not open when demanded."),
    "FTC": ("Fails to close", "Does not close (or reclose) when demanded."),
    "FTOC": ("Fails to open or close", "Does not change position when demanded, either way."),
    "FC": ("Fails to control", "Does not regulate or control as required while in service."),
    "SOP": ("Spurious operation", "Changes state with no demand (opens, closes, trips or transfers by itself)."),
    "ILS": ("Internal leak, small", "Leaks through the closed boundary (seat), up to 50 gpm."),
    "ILL": ("Internal leak, large", "Leaks through the closed boundary (seat), over 50 gpm."),
    "ELS": ("External leak, small", "Leaks out of the pressure boundary, up to 50 gpm."),
    "ELL": ("External leak, large", "Leaks out of the pressure boundary, over 50 gpm (rupture)."),
    "FTS": ("Fails to start", "Does not start when demanded."),
    "FTR": ("Fails to run", "Stops running before its mission is done."),
    "FTR<1H": ("Fails to run, first hour", "Stops running within the first hour after starting."),
    "FTR>1H": ("Fails to run, after the first hour", "Stops running after its first hour."),
    "FTLR": ("Fails to load and run", "Does not take its load and run through the first hour."),
    "FTOP": ("Fails to operate", "Does not perform its function when needed (or while in service)."),
    "FF": ("Fails to transfer", "Does not transfer to the other supply when demanded."),
    "PG": ("Plugs", "Becomes blocked enough to restrict the flow it must pass."),
    "BYP": ("Bypass", "Lets debris past (the filtering function is lost)."),
    "LOHT": ("Loss of heat transfer", "Plugging or fouling stops it transferring the heat it must."),
    "RUP": ("Rupture", "The tank boundary fails (rupture)."),
}
#: Running modes: their exposure is hours of running. Every other rate's is
#: calendar hours (the report: leak, spurious-operation and similar rates use
#: reactor-years whether the plant is critical or shut down).
RUNNING_MODES = {"FTR", "FTR<1H", "FTR>1H", "FTLR"}

#: Tokens in a code that say where or how the component works.
SYSTEMS = {
    "CCW": "Component cooling water", "SWS": "Service water", "SSW": "Standby service water",
    "SWN": "Service water (normally running)", "CWS": "Circulating water", "AFW": "Auxiliary feedwater",
    "HCI": "High-pressure coolant injection", "RCI": "Reactor core isolation cooling", "MFW": "Main feedwater",
    "IAS": "Instrument air", "CIA": "Containment instrument air", "MSS": "Main steam",
    "RCS": "Reactor coolant", "RAW": "Raw (untreated) water", "CLEAN": "Clean water", "OTHER": "Not service water",
}
PLANT_TYPES = {"PWR": "Pressurised water reactor", "BWR": "Boiling water reactor"}
RATINGS = {
    "CRBHV": "High voltage (13.8 and 16 kV)", "CRBMV": "Medium voltage (4160 V and 6.9 kV)",
    "CRB-FTOC-480": "Low voltage (480 V)", "CRB-SOP-480": "Low voltage (480 V)", "CRBDC": "DC",
    "BUS-FTOP-AC": "AC", "BUS-FTOP-DC": "DC",
}
SERVICES = {"PRESS-LIQ": "Pressurised liquid", "UNPRESS-LIQ": "Unpressurised liquid", "GAS": "Gas"}

METHODS = {
    "EB/PL/KS": "Empirical Bayes at plant level, with the Kass-Steffey adjustment",
    "JNID/IL": "Jeffreys noninformative prior, industry-level data",
    "JNID": "Jeffreys noninformative prior",
    "CNID": "Constrained noninformative prior",
    "EB": "Empirical Bayes",
    "Bayes": "Bayesian update",
}

#: Corrections to the source's text, each said in the record's notes.
TEXT_FIXES = {
    # The PDF's text for this row is garbled ("Fails To Open+D174 PWRs)"); the
    # next row is the same component's fails-to-close, which reads cleanly.
    "SVV-FTO-PWR-MSS": "Safety Valve Fails To Open (Main Steam System, PWRs)",
}
#: Rows whose source text names something other than the code's component or
#: mode: kept as given, with a note.
TEXT_MISMATCH = {
    "TDP-ELL": "The source's description names a turbine bypass valve; the code is the turbine-driven pump's.",
    "STR-FLT-ELL": "The source's description says small; the code (ELL) and note c make it the large leak.",
    "TNK-PRESS-LIQ-ELL": "The source's description says small; the code (ELL) and note c make it the large leak.",
    "TNK-UNPRESS-LIQ-ELL": "The source's description says small; the code (ELL) and note c make it the large "
                           "leak.",
    "TNK-GAS-ELL": "The source's description says small leakage; the code (ELL) makes it the large leak.",
}
#: Codes whose failure mode isn't the obvious token.
MODE_OVERRIDES = {"PMP-Volute": "FTR", "TNK-FC": "RUP"}

#: Rows left out, by code prefix rule, with why.
SKIP_REASONS = {
    "point": ("A point estimate with no spread for an event frequency (relief valves opening during a plant "
              "event), not a component failure distribution."),
    "lognormal": "Given only as a mean and an error factor, with no distribution parameters.",
}


def _clean(text) -> str:
    return " ".join(str(text or "").split())


def _number(text) -> float | None:
    t = _clean(text).replace(",", "")
    if not t or t in ("--", "-") or t.startswith("(note"):
        return None
    try:
        return float(t)
    except ValueError:
        return None


def _int(text) -> int | None:
    v = _number(text)
    return None if v is None else int(round(v))


def _lower_first(text: str) -> str:
    """'Main steam' -> 'main steam' for a label, but 'DC' stays 'DC'."""
    return text if text[:2].isupper() else text[:1].lower() + text[1:]


def normal_code(code: str) -> str:
    """The row's code, joined up and with the source's one typo fixed."""
    code = "".join(str(code).split())
    return re.sub(r"-{2,}", "-", code)


def slug(code: str) -> str:
    s = code.lower().replace("<", "-lt").replace(">", "-gt")
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def component_of(code: str) -> str:
    """The component a code is about (a key of :data:`COMPONENTS`)."""
    if code.startswith("STR-FLTSC"):
        return "FLTSC"
    if code.startswith(("STR-FLT", "FLT-")):
        return "FLT"
    if code.startswith("STR-PG-SUMP"):
        return "SMP"
    if code.startswith("CRB"):
        return "CRB"
    if code.startswith("MOV") and "BFV" in code.split("-"):
        return "BFV"
    if code.startswith("EDG") and code.endswith("-HCS"):
        return "HCS"
    if code.startswith("EDG") and code.endswith("-SBO"):
        return "SBO"
    return code.split("-")[0]


def mode_of(code: str) -> str:
    if code in MODE_OVERRIDES:
        return MODE_OVERRIDES[code]
    for token in code.split("-")[1:]:
        if token in MODES:
            return token
    raise ValueError(f"{code}: no failure mode in the code")


def conditions_of(code: str, description: str) -> dict:
    tokens = code.split("-")
    out: dict = {"industry": "U.S. commercial nuclear power plants"}
    text = description.lower()
    if "NS" in tokens or "normally standby" in text or "(standby)" in text:
        out["operating_mode"] = "standby"
    elif "NR" in tokens or "normally running" in text:
        out["operating_mode"] = "running"
    systems = [SYSTEMS[t] for t in tokens[1:] if t in SYSTEMS]
    if systems:
        out["system"] = " / ".join(systems)
    plants = [PLANT_TYPES[t] for t in tokens if t in PLANT_TYPES]
    if not plants and "bwr only" in text:
        plants = [PLANT_TYPES["BWR"]]
    if plants:
        out["plant_type"] = plants[0]
    for prefix, rating in RATINGS.items():
        if code == prefix or code.startswith(prefix + "-"):
            out["rating"] = rating
    for key, service in SERVICES.items():
        if f"-{key}-" in f"-{code}-":
            out["service"] = service
            break
    return out


def record_from_row(cells: list, code: str, report_page: int, retrieved: str) -> dict | str:
    """One Table 1 row as a library record, or the reason it's skipped.

    ``cells``: the row's 16 cells after the code, in the table's order:
    description, data source, failures, demands or hours, d or h, components,
    distribution, analysis type, 5th, median, mean, 95th, alpha, beta, error
    factor, date range."""
    (desc, data_source, failures, exposure, d_or_h, components, family, method,
     p05, median, mean, p95, alpha, beta, ef, period) = [_clean(c) for c in cells]
    code = normal_code(code)
    family_l = family.lower()
    if family_l.startswith("point"):
        return SKIP_REASONS["point"]
    if family_l == "lognormal" and (_number(alpha) is None or _number(beta) is None):
        return SKIP_REASONS["lognormal"]
    if family_l not in ("gamma", "beta"):
        raise ValueError(f"{code}: unexpected distribution {family!r}")

    comp_key = component_of(code)
    name, equipment_type, section, section_page = COMPONENTS[comp_key]
    mode = mode_of(code)
    mode_name, meaning = MODES[mode]
    notes: list[str] = []
    source_text = TEXT_FIXES.get(code, desc)
    if code in TEXT_FIXES:
        notes.append(f"The source's description is garbled in the PDF (\"{desc}\"); shown as corrected.")
    if code in TEXT_MISMATCH:
        notes.append(TEXT_MISMATCH[code])
    raw_code = code

    kind = "rate" if family_l == "gamma" else "per_demand"
    if kind == "rate":
        per_foot = d_or_h.lower() == "h-ft"
        value_unit = "per_hour_per_foot" if per_foot else "per_hour"
        time_basis = "operating" if mode in RUNNING_MODES else "calendar"
        if d_or_h.lower() == "d":
            notes.append("The source's d-or-h column says demands, but a gamma distribution is a rate: read as "
                         "per hour, as the report's other rates.")
        if time_basis == "calendar":
            notes.append("Per calendar hour: exposure counts the time the plant was running or shut down, not "
                         "hours of running.")
        else:
            notes.append("Per hour of running.")
        if per_foot:
            notes.append("Per hour per foot of pipe: multiply by the length of pipe.")
    else:
        value_unit, time_basis = "per_demand", None
        if d_or_h.lower() != "d":
            notes.append("The source's d-or-h column says hours, but a beta distribution is a probability per "
                         "demand: read as per demand.")

    if data_source.upper().startswith("NUREG/CR-6928") or failures.startswith("(note c)"):
        notes.append("Large-leak rate estimated from the small-leak rate with NUREG/CR-6928's ratio (the "
                     "report's note c): large leaks are too rare to estimate directly.")
    if failures.startswith("(note d)"):
        notes.append("Estimated from the level instrument's data (the report's note d).")

    n_failures = _int(failures)
    exposure_v = _number(exposure)
    evidence = {
        "failures": n_failures,
        "demands": int(exposure_v) if (kind == "per_demand" and exposure_v is not None) else None,
        "exposure": exposure_v if kind == "rate" else None,
        "exposure_unit": ("hour-feet" if value_unit == "per_hour_per_foot" else "hours") if kind == "rate" else None,
        "components": _int(components) or None,
        "sites": None,
        "period": period.replace("--", "–") if period not in ("", "--") else None,
        "data_source": data_source,
        "method": METHODS.get(method, method or None),
    }
    a, b = _number(alpha), _number(beta)
    cond = conditions_of(code, source_text)
    extras = [("normally " if k == "operating_mode" else "") + _lower_first(cond[k])
              for k in ("operating_mode", "system", "plant_type", "rating", "service") if k in cond]
    label = f"{name}: {mode_name.lower()}" + (f" ({'; '.join(extras)})" if extras else "")
    page = str(report_page)
    record = {
        "id": f"{SOURCE_ID}:{slug(raw_code)}",
        "version": DATA_VERSION,
        "source": SOURCE_ID,
        "source_code": raw_code,
        "name": name,
        "label": label,
        "equipment_type": equipment_type,
        "kind": kind,
        "basis": "field_data",
        "failure_mode": {"code": mode, "name": mode_name, "meaning": meaning},
        "distribution": {"family": family_l, "params": [{"name": "alpha", "value": a}, {"name": "beta", "value": b}]},
        "summary": {"mean": _number(mean), "median": _number(median), "p05": _number(p05), "p95": _number(p95),
                    "error_factor": _number(ef)},
        "units": {"value": value_unit, "time_basis": time_basis,
                  "as_given": {"per_hour": "per hour", "per_hour_per_foot": "per hour per foot",
                               "per_demand": "per demand"}[value_unit]},
        "evidence": evidence,
        "conditions": cond,
        "source_text": source_text,
        "citation": {
            "title": TITLE, "publisher": PUBLISHER, "report": SOURCE["report"], "edition": SOURCE["edition"],
            "year": SOURCE["year"], "table": "Table 1", "page": page,
            "data_sheet": f"Appendix {section}, p. {section_page}",
            "url": SOURCE_URL, "retrieved": retrieved,
        },
        "licence": {k: SOURCE["licence"][k] for k in ("id", "name", "attribution")},
        "notes": notes,
    }
    return record


def extract(pdf_path: str) -> list[tuple[str, int, list]]:
    """Table 1's rows from the PDF: (code, report page, the 16 cells after it)."""
    try:
        import pdfplumber  # noqa: PLC0415 - only this script needs it
    except ImportError:  # pragma: no cover - a maintainer's tool
        sys.exit("This script needs pdfplumber: pip install pdfplumber==0.11.10")
    rows = []
    with pdfplumber.open(pdf_path) as pdf:
        for pdf_page in TABLE_PAGES:
            table = pdf.pages[pdf_page - 1].extract_tables()[0]
            header = table[0]
            code_col = header.index("Component Failure\nMode")
            for raw in table[3:]:
                code = raw[code_col]
                if not code:
                    continue  # a wrapped label or the notes
                cells = [c for c in raw[code_col + 1:] if c not in (None, "")]
                if len(cells) != 16:
                    raise ValueError(f"{code}: expected 16 cells, found {len(cells)}")
                rows.append((code, pdf_page - PAGE_OFFSET, cells))
    return rows


def build(pdf_path: str, retrieved: str) -> dict:
    digest = hashlib.sha256(Path(pdf_path).read_bytes()).hexdigest()
    if digest != SOURCE_SHA256:
        sys.exit(f"The PDF's SHA-256 is {digest}, not the reviewed report's {SOURCE_SHA256}. Review the new "
                 "report before changing SOURCE_SHA256.")
    from backend.library import schema

    records, skipped, seen = [], [], set()
    for code, page, cells in extract(pdf_path):
        rec = record_from_row(cells, code, page, retrieved)
        if isinstance(rec, str):
            skipped.append({"code": normal_code(code), "page": str(page), "reason": rec})
            continue
        if rec["id"] in seen:
            raise ValueError(f"duplicate id {rec['id']}")
        seen.add(rec["id"])
        records.append(rec)
    bad = [p for r in records for p in schema.problems(r)]
    if bad:
        sys.exit("Records that can't ship:\n" + "\n".join(bad))
    return {
        "schema": schema.SCHEMA_VERSION,
        "data_version": DATA_VERSION,
        "source": {**SOURCE, "retrieved": retrieved, "sha256": SOURCE_SHA256,
                   "table": "Table 1, Component UR data and results (report pages 6-14)"},
        "skipped": skipped,
        "records": records,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("pdf", help="AvgPara2020.pdf, downloaded from " + SOURCE_URL)
    p.add_argument("--retrieved", required=True, help="The date you downloaded it, YYYY-MM-DD.")
    p.add_argument("--out", default=str(OUT))
    ns = p.parse_args(argv)
    data = build(ns.pdf, ns.retrieved)
    Path(ns.out).parent.mkdir(parents=True, exist_ok=True)
    Path(ns.out).write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{len(data['records'])} records, {len(data['skipped'])} skipped -> {ns.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
