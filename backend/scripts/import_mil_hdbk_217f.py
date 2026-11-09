"""Build the library's MIL-HDBK-217F data file from the handbook.

    pip install pdfplumber==0.11.10       # only this script needs it
    python -m backend.scripts.import_mil_hdbk_217f DIR --retrieved 2026-10-23

The source is *MIL-HDBK-217F, Reliability Prediction of Electronic Equipment*
(U.S. Department of Defense, 2 December 1991) as amended by Notice 2 (28
February 1995): DISTRIBUTION STATEMENT A, approved for public release,
distribution unlimited. Download both parts by hand from ASSIST
(:data:`ASSIST_URL`, document MIL-HDBK-217) into one folder, as the file
names in :data:`DOCUMENTS`:

- ``MIL-HDBK-217F.pdf``: "Revision F" (205 pages);
- ``MIL-HDBK-217F-NOTICE-2.pdf``: "Revision F Change Notice 2" (80 pages).

Notice 1 (10 July 1992) isn't needed: none of the pages read here are its.
The PDFs aren't committed (19 MB; the data file carries everything used).

Why the tables are typed in here, not read from the PDF: the handbook is a
1990s scan with an OCR text layer that misreads digits (1728 as 1720, 1.0 as
1,0), so parsing it would ship wrong numbers quietly. The base failure rates
and environment factors below were typed from the page images, and the
script checks them against the PDF in two ways before it writes anything:

1. Each document's content fingerprint (:func:`content_sha256`) must match
   the reviewed copy's. ASSIST stamps every download with the time it was
   downloaded, so a file's own SHA-256 differs from one download to the
   next; the fingerprint hashes every page's content and images and leaves
   out only that stamp, so a revised handbook still fails it.
2. Every number typed here must appear in the OCR text of the page it's
   cited from, unless :data:`OCR_MISREADS` says how the OCR misread it (each
   checked by eye against the page image).

Then each part becomes a record (:func:`records`, pure, so it's tested
without the PDFs), every record is checked (``backend.library.schema
.problems``) and ``backend/library/data/mil-hdbk-217f-n2.json`` is written
only when all of them pass.

What a record holds: the part's base failure rate λb (per million hours in
the handbook, stored per hour) and the section's environment factors πE by
the handbook's 14 environments. Reliafy applies λb × πE only. The handbook's
other factors (temperature, stress, quality and so on) need the user's
design detail, so each record names the factors it leaves out, and the
handbook's full model, rather than present λb × πE as the prediction.
Parts whose base rate isn't one number (it's a formula of temperature,
frequency or voltage, or per junction, hole or kilometre) are skipped, each
with its reason (:data:`SKIPPED`).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

SOURCE_ID = "mil-hdbk-217f-n2"
ASSIST_URL = "https://quicksearch.dla.mil/qsDocDetails.aspx?ident_number=53939"
OUT = Path(__file__).resolve().parents[1] / "library" / "data" / f"{SOURCE_ID}.json"
DATA_VERSION = 1

TITLE = "Military Handbook: Reliability Prediction of Electronic Equipment"
PUBLISHER = "U.S. Department of Defense"
REPORT = "MIL-HDBK-217F, Notice 2"
ATTRIBUTION = ("Source: MIL-HDBK-217F, Military Handbook: Reliability Prediction of Electronic Equipment "
               "(U.S. Department of Defense, 2 December 1991), with Notice 2 (28 February 1995). Distribution "
               "Statement A: approved for public release; distribution unlimited. A U.S. Government work; "
               "republished by Reliafy.")

#: The two documents, as downloaded from ASSIST and reviewed. ``file_sha256``
#: is the reviewed download's own hash (for the record: another download's
#: differs by its stamp); ``content_sha256`` is what the script checks.
DOCUMENTS = {
    "F": {"file": "MIL-HDBK-217F.pdf", "part": "Revision F", "date": "2 December 1991", "pages": 205,
          "file_sha256": "1cb2e7baa45a4d96560b69b6f410653fd7b7cb094f329ee19d4453a8be4d9951",
          "content_sha256": "1353f27981ff8dd89fcd2ed48830274dcc3fededcce295f068fe0aecc75d44f4"},
    "N2": {"file": "MIL-HDBK-217F-NOTICE-2.pdf", "part": "Notice 2", "date": "28 February 1995", "pages": 80,
           "file_sha256": "6952b7a74ebfce42c2a0688880140c6ef6684f1ab64619e5c1bc0ed92ce2203e",
           "content_sha256": "8f4112d40ee848e088a8425f89a65fa21c55674498bc2ad7169a5fc6a917d4e8"},
}
#: The stamp ASSIST adds to every page of a download (its own content
#: streams), which :func:`content_sha256` leaves out.
STAMP_MARKS = (b"assist.dla.mil", b"Check the source to verify")

SOURCE = {
    "id": SOURCE_ID,
    "name": "MIL-HDBK-217F (Notice 2): base failure rates for electronic parts",
    "short_name": "MIL-HDBK-217F N2",
    "publisher": PUBLISHER,
    "title": TITLE,
    "report": REPORT,
    "edition": "Revision F (2 December 1991) with Notice 2 (28 February 1995)",
    "year": 1995,
    "url": ASSIST_URL,
    "home": "https://quicksearch.dla.mil/",
    "basis": "prediction_model",
    "licence": {
        "id": "us-government-work",
        "name": "U.S. Government work (no copyright asserted)",
        "attribution": ATTRIBUTION,
        "note": ("A U.S. Department of Defense handbook. Both the handbook and Notice 2 carry Distribution "
                 "Statement A (\"Approved for public release; distribution unlimited\") and no copyright "
                 "notice; the official copies are free to download from ASSIST."),
    },
    "description": ("Base failure rates (λb) for electronic part types from the part stress models of the "
                    "U.S. military's reliability prediction handbook, with each section's environment factors "
                    "(πE) for its 14 use environments, from ground, benign to cannon, launch; and, from its "
                    "parts count method (Appendix A), generic failure rates (λg) by environment with their "
                    "quality factors (πQ) for microcircuits, laser diodes, motors, synchros and resolvers, "
                    "circuit boards, quartz crystals and incandescent lamps."),
    "caveats": [
        "A handbook prediction model, not failures counted in service: never mix it with field data.",
        "Reliafy uses the base failure rate × the environment factor only (a parts-count record: the generic "
        "rate for the environment × the quality factor). The handbook's other factors (temperature, electrical "
        "stress, quality and more) aren't applied: each record names them, and real rates depend on them. "
        "Quality alone can move a rate by a factor of 10 or more.",
        "The handbook covers electronic parts only: it has no batteries and no mechanical parts.",
        "The models were last revised in 1995 and describe parts of that era; newer parts are often more "
        "reliable than the handbook predicts.",
        "The handbook is guidance for comparing designs early, not a measure of how your equipment will fail.",
    ],
}

#: The handbook's environments in its own order (columns of every πE table).
ENV_ORDER = ("GB", "GF", "GM", "NS", "NU", "AIC", "AIF", "AUC", "AUF", "ARW", "SF", "MF", "ML", "CL")
NA = None  # "N/A" in a πE table: the handbook gives no factor for that environment

#: Factor symbols and their plain names.
FACTOR_NAMES = {
    "πT": "temperature", "πP": "power dissipation", "πS": "electrical stress", "πQ": "quality",
    "πC": "construction or configuration", "πV": "voltage stress", "πSR": "series resistance",
    "πA": "application", "πR": "power or current rating", "πL": "load stress", "πU": "use",
    "πK": "mating and unmating cycles", "πF": "function",
}


def _f(symbol: str, name: str | None = None) -> tuple[str, str]:
    return symbol, name or FACTOR_NAMES[symbol]


# ---- the tables, typed from the page images ----------------------------------------------
#
# Each group is one section's base failure rate table and its environment
# factor table. ``rates`` and ``env`` give (document, printed page, PDF page)
# for the citation and the OCR check. Each part: (style, specification,
# the handbook's description as printed, λb as printed, and optionally the
# words for its id when the description is too long for one). ``name`` turns
# the description into the record's name ("{text}": the description itself).

GROUPS: list[dict] = [
    {
        "section": "6.1", "title": "Diodes, low frequency", "equipment_type": "semiconductor",
        "rates": ("N2", "6-2", 29), "env": ("F", "6-3", 49), "specification": "MIL-S-19500",
        "formula": "λp = λb πT πS πC πQ πE",
        "not_applied": [_f("πT"), _f("πS"), _f("πC", "contact construction"), _f("πQ")],
        "quality_range": (0.7, 8.0),
        "env_values": ("1.0", "6.0", "9.0", "9.0", "19", "13", "29", "20", "43", "24", ".50", "14", "32", "320"),
        "name": "Diode, low frequency, {text}",
        "parts": [
            (None, None, "General Purpose Analog", ".0038"),
            (None, None, "Switching", ".0010"),
            (None, None, "Fast Recovery Power Rectifier", ".025"),
            (None, None, "Power Rectifier/Schottky Power Diode", ".0030"),
            (None, None, "Transient Suppressor/Varistor", ".0013"),
            (None, None, "Current Regulator", ".0034"),
            (None, None, "Voltage Regulator and Voltage Reference (Avalanche and Zener)", ".0020"),
        ],
    },
    {
        "section": "6.2", "title": "Diodes, high frequency (microwave, RF)", "equipment_type": "semiconductor",
        "rates": ("F", "6-4", 50), "env": ("F", "6-5", 51), "specification": "MIL-S-19500",
        "formula": "λp = λb πT πA πR πQ πE",
        "not_applied": [_f("πT"), _f("πA"), _f("πR", "power rating"), _f("πQ")],
        "quality_range": (0.5, 50),
        "env_values": ("1.0", "2.0", "5.0", "4.0", "11", "4.0", "5.0", "7.0", "12", "16", ".50", "9.0", "24", "250"),
        "name": "Diode, high frequency, {text}",
        "parts": [
            (None, None, "Si IMPATT (≤ 35 GHz)", ".22"),
            (None, None, "Gunn/Bulk Effect", ".18"),
            (None, None, "Tunnel and Back (Including Mixers, Detectors)", ".0023"),
            (None, None, "PIN", ".0081"),
            (None, None, "Schottky Barrier (Including Detectors) and Point Contact (200 MHz ≤ Frequency ≤ 35 GHz)",
             ".027", "schottky barrier and point contact"),
            (None, None, "Varactor and Step Recovery", ".0025"),
        ],
    },
    {
        "section": "6.3", "title": "Transistors, low frequency, bipolar", "equipment_type": "semiconductor",
        "rates": ("F", "6-6", 52), "env": ("F", "6-7", 53), "specification": "MIL-S-19500",
        "formula": "λp = λb πT πA πR πS πQ πE",
        "not_applied": [_f("πT"), _f("πA"), _f("πR", "power rating"), _f("πS", "voltage stress"), _f("πQ")],
        "quality_range": (0.7, 8.0),
        "env_values": ("1.0", "6.0", "9.0", "9.0", "19", "13", "29", "20", "43", "24", ".50", "14", "32", "320"),
        "name": "Transistor, low frequency, bipolar, {text}",
        "parts": [(None, None, "NPN and PNP", ".00074")],
    },
    {
        "section": "6.4", "title": "Transistors, low frequency, Si FET", "equipment_type": "semiconductor",
        "rates": ("F", "6-8", 54), "env": ("F", "6-8", 54), "specification": "MIL-S-19500",
        "formula": "λp = λb πT πA πQ πE",
        "not_applied": [_f("πT"), _f("πA"), _f("πQ")],
        "quality_range": (0.7, 8.0),
        "env_values": ("1.0", "6.0", "9.0", "9.0", "19", "13", "29", "20", "43", "24", ".50", "14", "32", "320"),
        "name": "Transistor, low frequency, silicon FET, {text}",
        "parts": [(None, None, "MOSFET", ".012"), (None, None, "JFET", ".0045")],
    },
    {
        "section": "6.5", "title": "Transistors, unijunction", "equipment_type": "semiconductor",
        "rates": ("F", "6-9", 55), "env": ("F", "6-9", 55), "specification": "MIL-S-19500",
        "formula": "λp = λb πT πQ πE",
        "not_applied": [_f("πT"), _f("πQ")],
        "quality_range": (0.7, 8.0),
        "env_values": ("1.0", "6.0", "9.0", "9.0", "19", "13", "29", "20", "43", "24", ".50", "14", "32", "320"),
        "name": "Transistor, unijunction",
        "parts": [(None, None, "All Unijunction", ".0083")],
    },
    {
        "section": "6.10", "title": "Thyristors and SCRs", "equipment_type": "semiconductor",
        "rates": ("F", "6-17", 63), "env": ("F", "6-18", 64), "specification": "MIL-S-19500",
        "formula": "λp = λb πT πR πS πQ πE",
        "not_applied": [_f("πT"), _f("πR", "current rating"), _f("πS", "voltage stress"), _f("πQ")],
        "quality_range": (0.7, 8.0),
        "env_values": ("1.0", "6.0", "9.0", "9.0", "19", "13", "29", "20", "43", "24", ".50", "14", "32", "320"),
        "name": "Thyristor or SCR (all types)",
        "parts": [(None, None, "All Types", ".0022", "thyristor")],
    },
    {
        "section": "6.11", "title": "Optoelectronics: detectors, isolators, emitters",
        "equipment_type": "semiconductor",
        "rates": ("F", "6-19", 65), "env": ("F", "6-19", 65), "specification": "MIL-S-19500",
        "formula": "λp = λb πT πQ πE",
        "not_applied": [_f("πT"), _f("πQ")],
        "quality_range": (0.7, 8.0),
        "env_values": ("1.0", "2.0", "8.0", "5.0", "12", "4.0", "6.0", "6.0", "8.0", "17", ".50", "9.0", "24", "450"),
        "name": "Optoelectronic device, {text}",
        "parts": [
            (None, None, "Photodetector, Photo-Transistor", ".0055"),
            (None, None, "Photodetector, Photo-Diode", ".0040"),
            (None, None, "Opto-Isolator, Photodiode Output, Single Device", ".0025"),
            (None, None, "Opto-Isolator, Phototransistor Output, Single Device", ".013"),
            (None, None, "Opto-Isolator, Photodarlington Output, Single Device", ".013"),
            (None, None, "Opto-Isolator, Light Sensitive Resistor, Single Device", ".0064"),
            (None, None, "Opto-Isolator, Photodiode Output, Dual Device", ".0033"),
            (None, None, "Opto-Isolator, Phototransistor Output, Dual Device", ".017"),
            (None, None, "Opto-Isolator, Photodarlington Output, Dual Device", ".017"),
            (None, None, "Opto-Isolator, Light Sensitive Resistor, Dual Device", ".0086"),
            (None, None, "Emitter, Infrared Light Emitting Diode (IRLED)", ".0013"),
            (None, None, "Emitter, Light Emitting Diode (LED)", ".00023"),
        ],
    },
    {
        "section": "9.1", "title": "Resistors", "equipment_type": "resistor",
        "rates": ("N2", "9-1", 32), "env": ("N2", "9-3", 34),
        "formula": "λp = λb πT πP πS πQ πE",
        "not_applied": [_f("πT"), _f("πP"), _f("πS", "power stress"), _f("πQ")],
        "quality_range": (0.03, 10),
        "env_values": ("1.0", "4.0", "16", "12", "42", "18", "23", "31", "43", "63", ".50", "37", "87", "1728"),
        "name": "{text}",
        "parts": [
            ("RC", "MIL-R-11", "Resistor, Fixed, Composition (Insulated)", ".0017"),
            ("RCR", "MIL-R-39008", "Resistor, Fixed, Composition (Insulated) Est. Rel.", ".0017"),
            ("RL", "MIL-R-22684", "Resistor, Fixed, Film, Insulated", ".0037"),
            ("RLR", "MIL-R-39017", "Resistor, Fixed, Film (Insulated), Est. Rel.", ".0037"),
            ("RN (R, C or N)", "MIL-R-55182", "Resistor, Fixed, Film, Established Reliability", ".0037"),
            ("RM", "MIL-R-55342", "Resistor, Fixed, Film, Chip, Established Reliability", ".0037"),
            ("RN", "MIL-R-10509", "Resistor, Fixed Film (High Stability)", ".0037"),
            ("RD", "MIL-R-11804", "Resistor, Fixed, Film (Power Type)", ".0037"),
            ("RZ", "MIL-R-83401", "Resistor Networks, Fixed, Film", ".0019"),
            ("RB", "MIL-R-93", "Resistor, Fixed, Wirewound (Accurate)", ".0024"),
            ("RBR", "MIL-R-39005", "Resistor, Fixed, Wirewound (Accurate) Est. Rel.", ".0024"),
            ("RW", "MIL-R-26", "Resistor, Fixed, Wirewound (Power Type)", ".0024"),
            ("RWR", "MIL-R-39007", "Resistor, Fixed, Wirewound (Power Type) Est. Rel.", ".0024"),
            ("RE", "MIL-R-18546", "Resistor, Fixed, Wirewound (Power Type, Chassis Mounted)", ".0024"),
            ("RER", "MIL-R-39009", "Resistor, Fixed, Wirewound (Power Type, Chassis Mounted) Est. Rel.", ".0024"),
            ("RTH", "MIL-R-23648", "Thermistor, (Thermally Sensitive Resistor), Insulated", ".0019"),
            ("RT", "MIL-R-27208", "Resistor, Variable, Wirewound (Lead Screw Activated)", ".0024"),
            ("RTR", "MIL-R-39015", "Resistor, Variable, Wirewound (Lead Screw Activated), Established Reliability",
             ".0024"),
            ("RR", "MIL-R-12934", "Resistor, Variable, Wirewound, Precision", ".0024"),
            ("RA", "MIL-R-19", "Resistor, Variable, Wirewound (Low Operating Temperature)", ".0024"),
            ("RK", "MIL-R-39002", "Resistor, Variable, Wirewound, Semi-Precision", ".0024"),
            ("RP", "MIL-R-22", "Resistor, Wirewound, Power Type", ".0024"),
            ("RJ", "MIL-R-22097", "Resistor, Variable, Nonwirewound", ".0037"),
            ("RJR", "MIL-R-39035", "Resistor, Variable, Nonwirewound Est. Rel.", ".0037"),
            ("RV", "MIL-R-94", "Resistor, Variable, Composition", ".0037"),
            ("RQ", "MIL-R-39023", "Resistor, Variable, Nonwirewound, Precision", ".0037"),
            ("RVC", "MIL-R-23285", "Resistor, Variable, Nonwirewound", ".0037"),
        ],
    },
    {
        "section": "10.1", "title": "Capacitors", "equipment_type": "capacitor",
        # The table runs onto a second page from its 14th row (CK).
        "rates": ("N2", "10-1", 35), "rates_2": ("N2", "10-2", 36, 13), "env": ("N2", "10-5", 39),
        "formula": "λp = λb πT πC πV πSR πQ πE",
        "not_applied": [_f("πT"), _f("πC", "capacitance"), _f("πV"), _f("πSR"), _f("πQ")],
        "quality_range": (0.001, 10),
        "env_values": ("1.0", "10", "20", "7.0", "15", "12", "15", "25", "30", "40", ".50", "20", "50", "570"),
        "name": "{text}",
        "parts": [
            ("CP", "MIL-C-25", "Capacitor, Fixed, Paper-Dielectric, Direct Current (Hermetically Sealed in Metal "
             "Cases)", ".00037"),
            ("CA", "MIL-C-12889", "Capacitor, By-Pass, Radio-Interference Reduction, Paper Dielectric, AC and DC "
             "(Hermetically sealed in Metallic Cases)", ".00037"),
            ("CZ, CZR", "MIL-C-11693", "Capacitor, Feed through, Radio Interference Reduction AC and DC "
             "(Hermetically sealed in metal cases), Established and Nonestablished Reliability", ".00037"),
            ("CQ, CQR", "MIL-C-19978", "Capacitor, Fixed Plastic (or Paper-Plastic) Dielectric (Hermetically sealed "
             "in metal, ceramic or glass cases), Established and Nonestablished Reliability", ".00051"),
            ("CH", "MIL-C-18312", "Capacitor, Fixed, Metallized (Paper, Paper Plastic or Plastic Film) Dielectric, "
             "Direct Current (Hermetically Sealed in Metal Cases)", ".00037"),
            ("CHR", "MIL-C-39022", "Capacitor, Fixed, Metallized Paper, Paper-Plastic Film or Plastic Film "
             "Dielectric", ".00051"),
            ("CFR", "MIL-C-55514", "Capacitor, Fixed, Plastic (or Metallized Plastic) Dielectric, Direct Current "
             "in Non-Metal Cases", ".00051"),
            ("CRH", "MIL-C-83421", "Capacitor, Fixed Supermetallized Plastic Film Dielectric (DC, AC or DC and AC) "
             "Hermetically Sealed in Metal Cases, Established Reliability", ".00051"),
            ("CM", "MIL-C-5", "Capacitors, Fixed, Mica Dielectric", ".00076"),
            ("CMR", "MIL-C-39001", "Capacitor, Fixed, Mica Dielectric, Established Reliability", ".00076"),
            ("CB", "MIL-C-10950", "Capacitor, Fixed, Mica Dielectric, Button Style", ".00076"),
            ("CY", "MIL-C-11272", "Capacitor, Fixed, Glass Dielectric", ".00076"),
            ("CYR", "MIL-C-23269", "Capacitor, Fixed, Glass Dielectric, Established Reliability", ".00076"),
            ("CK", "MIL-C-11015", "Capacitor, Fixed, Ceramic Dielectric (General Purpose)", ".00099"),
            ("CKR", "MIL-C-39014", "Capacitor, Fixed, Ceramic Dielectric (General Purpose), Established "
             "Reliability", ".00099"),
            ("CC, CCR", "MIL-C-20", "Capacitor, Fixed, Ceramic Dielectric (Temperature Compensating), Established "
             "and Nonestablished Reliability", ".00099"),
            ("CDR", "MIL-C-55681", "Capacitor, Chip, Multiple Layer, Fixed, Ceramic Dielectric, Established "
             "Reliability", ".0020"),
            ("CSR", "MIL-C-39003", "Capacitor, Fixed, Electrolytic (Solid Electrolyte), Tantalum, Established "
             "Reliability", ".00040"),
            ("CWR", "MIL-C-55365", "Capacitor, Fixed, Electrolytic (Tantalum), Chip, Established Reliability",
             ".00005"),
            ("CL", "MIL-C-3965", "Capacitor, Fixed, Electrolytic (Nonsolid Electrolyte), Tantalum", ".00040"),
            ("CLR", "MIL-C-39006", "Capacitor, Fixed, Electrolytic (Nonsolid Electrolyte), Tantalum, Established "
             "Reliability", ".00040"),
            ("CRL", "MIL-C-83500", "Capacitor, Fixed, Electrolytic (Nonsolid Electrolyte), Tantalum Cathode",
             ".00040"),
            ("CU, CUR", "MIL-C-39018", "Capacitor, Fixed, Electrolytic (Aluminum Oxide), Established Reliability "
             "and Nonestablished Reliability", ".00012"),
            ("CE", "MIL-C-62", "Capacitor, Fixed Electrolytic (DC, Aluminum, Dry Electrolyte, Polarized)", ".00012"),
            ("CV", "MIL-C-81", "Capacitor, Variable, Ceramic Dielectric (Trimmer)", ".0079"),
            ("PC", "MIL-C-14409", "Capacitor, Variable (Piston Type, Tubular Trimmer)", ".0060"),
            ("CT", "MIL-C-92", "Capacitor, Variable, Air Dielectric (Trimmer)", ".0000072"),
            ("CG", "MIL-C-23183", "Capacitor, Fixed or Variable, Vacuum Dielectric", ".0060"),
        ],
    },
    {
        "section": "11.1", "title": "Inductive devices, transformers", "equipment_type": "inductive",
        "rates": ("N2", "11-1", 41), "env": ("N2", "11-1", 41),
        "specification": "MIL-T-27, MIL-T-21038, MIL-T-55631",
        "formula": "λp = λb πT πQ πE",
        "not_applied": [_f("πT", "hot-spot temperature"), _f("πQ")],
        "quality_range": (1, 3),
        "env_values": ("1.0", "6.0", "12", "5.0", "16", "6.0", "8.0", "7.0", "9.0", "24", ".50", "13", "34", "610"),
        "name": "Transformer, {text}",
        "parts": [
            (None, None, "Flyback (< 20 Volts)", ".0054"),
            (None, None, "Audio (15 - 20K Hz)", ".014"),
            (None, None, "Low Power Pulse (Peak Pwr. < 300W, Avg. Pwr. < 5W)", ".022"),
            (None, None, "High Power, High Power Pulse (Peak Power ≥ 300W, Avg. Pwr. ≥ 5W)", ".049"),
            (None, None, "RF (10K - 10M Hz)", ".13"),
        ],
    },
    {
        "section": "11.2", "title": "Inductive devices, coils", "equipment_type": "inductive",
        "rates": ("N2", "11-3", 43), "env": ("N2", "11-3", 43),
        "specification": "MIL-C-15305, MIL-C-83446, MIL-C-39010",
        "formula": "λp = λb πT πQ πE",
        "not_applied": [_f("πT", "hot-spot temperature"), _f("πQ")],
        "quality_range": (0.03, 3.0),
        "env_values": ("1.0", "6.0", "12", "5.0", "16", "6.0", "8.0", "7.0", "9.0", "24", ".50", "13", "34", "610"),
        "name": "Coil, {text}",
        "parts": [
            (None, None, "Fixed Inductor or Choke", ".000030"),
            (None, None, "Variable Inductor", ".000050"),
        ],
    },
    {
        "section": "12.3", "title": "Rotating devices, elapsed time meters", "equipment_type": "instrument_control",
        "rates": ("N2", "12-5", 49), "env": ("N2", "12-5", 49),
        "formula": "λp = λb πT πE",
        "not_applied": [_f("πT", "temperature stress")],
        "quality_range": None,
        "env_values": ("1.0", "2.0", "12", "7.0", "18", "5.0", "8.0", "16", "25", "26", ".50", "14", "38", NA),
        "name": "Elapsed time meter, {text}",
        "parts": [
            (None, None, "A.C.", "20"),
            (None, None, "Inverter Driven", "30"),
            (None, None, "Commutator D.C.", "80"),
        ],
    },
    {
        "section": "13.2", "title": "Relays, solid state and time delay", "equipment_type": "instrument_control",
        "rates": ("N2", "13-3", 52), "env": ("N2", "13-3", 52), "specification": "MIL-R-28750, MIL-R-83726",
        "formula": "λp = λb πQ πE",
        "not_applied": [_f("πQ")],
        "quality_range": (1.0, 1.9),
        "env_values": ("1.0", "3.0", "12", "6.0", "17", "12", "19", "21", "32", "23", ".40", "12", "33", "590"),
        "name": "Relay, {text}",
        "notes": ["The handbook's default model for when the relay's own components aren't known; summing their "
                  "rates is its more accurate method."],
        "parts": [
            (None, None, "Solid State", ".029"),
            (None, None, "Solid State Time Delay", ".029"),
            (None, None, "Hybrid", ".029"),
        ],
    },
    {
        "section": "14.1", "title": "Switches", "equipment_type": "switch",
        "rates": ("N2", "14-1", 53), "env": ("N2", "14-2", 54),
        "formula": "λp = λb πL πC πQ πE",
        "not_applied": [_f("πL"), _f("πC", "contact configuration"), _f("πQ")],
        "quality_range": (1, 2),
        "env_values": ("1.0", "3.0", "18", "8.0", "29", "10", "18", "13", "22", "46", ".50", "25", "67", "1200"),
        "name": "Switch, {text}",
        "parts": [
            (None, None, "Centrifugal", "3.4"),
            (None, None, "Dual-In-line Package", ".00012"),
            (None, None, "Limit", "4.3"),
            (None, None, "Liquid Level", "2.3"),
            (None, None, "Microwave (Waveguide)", "1.7"),
            (None, None, "Pressure", "2.8"),
            (None, None, "Pushbutton", ".10"),
            (None, None, "Reed", ".0010"),
            (None, None, "Rocker", ".023"),
            (None, None, "Rotary", ".11"),
            (None, None, "Sensitive", ".49"),
            (None, None, "Thermal", ".031"),
            (None, None, "Thumbwheel", ".18"),
            (None, None, "Toggle", ".10"),
        ],
    },
    {
        "section": "14.2", "title": "Switches, circuit breakers", "equipment_type": "electrical",
        "rates": ("N2", "14-3", 55), "env": ("N2", "14-3", 55),
        "specification": "MIL-C-13516, MIL-C-55629, MIL-C-83383, MIL-C-39019, W-C-375",
        "formula": "λp = λb πC πU πQ πE",
        "not_applied": [_f("πC", "configuration"), _f("πU"), _f("πQ")],
        "quality_range": (1.0, 8.4),
        "env_values": ("1.0", "2.0", "15", "8.0", "27", "7.0", "9.0", "11", "12", "46", ".50", "25", "66", NA),
        "name": "Circuit breaker, {text}",
        "parts": [
            (None, None, "Magnetic", ".34"),
            (None, None, "Thermal", ".34"),
            (None, None, "Thermal-Magnetic", ".34"),
        ],
    },
    {
        "section": "15.1", "title": "Connectors, general", "equipment_type": "connector",
        "rates": ("N2", "15-1", 56), "env": ("N2", "15-2", 57),
        "formula": "λp = λb πT πK πQ πE",
        "not_applied": [_f("πT", "insert temperature"), _f("πK"), _f("πQ")],
        "quality_range": (1, 2),
        "env_values": ("1.0", "1.0", "8.0", "5.0", "13", "3.0", "5.0", "8.0", "12", "19", ".50", "10", "27", "490"),
        "name": "Connector, {text}",
        "notes": ["The rate is for a mated pair of connectors; the handbook halves it for one connector."],
        "parts": [
            (None, None, "Circular/Cylindrical", ".0010"),
            (None, None, "Card Edge (PCB)", ".040"),
            (None, None, "Hexagonal", ".15"),
            (None, None, "Rack and Panel", ".021"),
            (None, None, "Rectangular", ".046"),
            (None, None, "RF Coaxial", ".00041"),
            (None, None, "Telephone", ".0075"),
            (None, None, "Power", ".0070"),
            (None, None, "Triaxial", ".0036"),
        ],
    },
    {
        "section": "15.2", "title": "Connectors, sockets", "equipment_type": "connector",
        "rates": ("N2", "15-3", 58), "env": ("N2", "15-3", 58),
        "formula": "λp = λb πP πQ πE",
        "not_applied": [_f("πP", "number of active pins"), _f("πQ")],
        "quality_range": (0.3, 1.0),
        "env_values": ("1.0", "3.0", "14", "6.0", "18", "8.0", "12", "11", "13", "25", ".50", "14", "36", "650"),
        "name": "Socket, {text}",
        "notes": ["The active-pins factor (left out) runs from 1.0 for one pin to 22 for 180 pins."],
        "parts": [
            (None, "MIL-S-83734", "Dual-In-Line Package", ".00064"),
            (None, "MIL-S-83734", "Single-In-Line Package", ".00064"),
            (None, "MIL-S-38533", "Chip Carrier", ".00064"),
            (None, None, "Pin Grid Array", ".00064"),
            (None, "MIL-S-12883", "Relay", ".037"),
            (None, "MIL-S-12883", "Transistor", ".0051"),
            (None, "MIL-S-12883", "Electron Tube, CRT", ".011"),
        ],
    },
    {
        "section": "17.1", "title": "Connections", "equipment_type": "connector",
        "rates": ("N2", "17-1", 63), "env": ("N2", "17-1", 63),
        "formula": "λp = λb πE",
        "not_applied": [],
        "quality_range": None,
        "env_values": ("1.0", "2.0", "7.0", "4.0", "11", "4.0", "6.0", "6.0", "8.0", "16", ".50", "9.0", "24", "420"),
        "name": "Connection, {text}",
        "notes": ["The rate is for one connection. Connections to a circuit board with plated through holes or "
                  "surface mounting belong to the board's own model, not this one."],
        "parts": [
            (None, None, "Hand Solder, w/o Wrapping", ".0013"),
            (None, None, "Hand Solder, w/Wrapping", ".000070"),
            (None, None, "Crimp", ".00026"),
            (None, None, "Weld", ".000015"),
            (None, None, "Solderless Wrap", ".0000068"),
            (None, None, "Clip Termination", ".00012"),
            (None, None, "Reflow Solder", ".000069"),
            (None, None, "Spring Contact", ".17"),
            (None, None, "Terminal Block", ".062"),
        ],
    },
    {
        "section": "18.1", "title": "Meters, panel", "equipment_type": "instrument_control",
        "rates": ("F", "18-1", 169), "env": ("F", "18-1", 169), "specification": "MIL-M-10304",
        "formula": "λp = λb πA πF πQ πE",
        "not_applied": [_f("πA", "application (AC or DC)"), _f("πF"), _f("πQ")],
        "quality_range": (1.0, 3.4),
        "env_values": ("1.0", "4.0", "25", "12", "35", "28", "42", "58", "73", "60", "1.1", "60", NA, NA),
        "name": "Panel meter (electrical indicating, ruggedised)",
        "parts": [(None, None, "All", ".090", "panel meter")],
    },
    {
        "section": "21.1", "title": "Electronic filters, non-tunable", "equipment_type": "electronic_other",
        "rates": ("F", "21-1", 172), "env": ("F", "21-1", 172),
        "formula": "λp = λb πQ πE",
        "not_applied": [_f("πQ")],
        "quality_range": (1.0, 2.9),
        "env_values": ("1.0", "2.0", "6.0", "4.0", "9.0", "7.0", "9.0", "11", "13", "11", ".80", "7.0", "15", "120"),
        "name": "Electronic filter, {text}",
        "notes": ["The handbook's default model for when the filter's own components aren't known; summing their "
                  "rates is its more accurate method."],
        "parts": [
            (None, "MIL-F-15733", "MIL-F-15733, Ceramic-Ferrite Construction (Styles FL 10-16, 22, 24, 30-32, 34, "
             "35, 38, 41-43, 45, 47-50, 61-65, 70, 81-93, 95, 96)", ".022", "mil-f-15733 ceramic-ferrite"),
            (None, "MIL-F-15733", "MIL-F-15733, Discrete LC Components, (Styles FL 37, 53, 74)", ".12",
             "mil-f-15733 discrete lc"),
            (None, "MIL-F-18327", "MIL-F-18327, Discrete LC Components (Composition 1)", ".12",
             "mil-f-18327 composition 1"),
            (None, "MIL-F-18327", "MIL-F-18327, Discrete LC and Crystal Components (Composition 2)", ".27",
             "mil-f-18327 composition 2"),
        ],
    },
    {
        "section": "22.1", "title": "Fuses", "equipment_type": "electrical",
        "rates": ("F", "22-1", 173), "env": ("F", "22-1", 173),
        "specification": "W-F-1726, W-F-1814, MIL-F-5372, MIL-F-23419, MIL-F-15160",
        "formula": "λp = λb πE",
        "not_applied": [],
        "quality_range": None,
        "env_values": ("1.0", "2.0", "8.0", "5.0", "11", "9.0", "12", "15", "18", "16", ".90", "10", "21", "230"),
        "name": "Fuse",
        "notes": ["Fuses opening or shorting from fatigue and corrosion, from life tests: a fuse that blows "
                  "because of an overload elsewhere isn't a fuse failure."],
        "parts": [(None, None, "W-F-1726, W-F-1814, MIL-F-5372, MIL-F-23419, MIL-F-15160", ".010", "fuse")],
    },
    {
        "section": "23.1", "title": "Miscellaneous parts: microwave ferrite devices",
        "equipment_type": "electronic_other",
        "rates": ("F", "23-1", 174), "env": ("F", "23-2", 175),
        "formula": "λp = rate × πE",
        "not_applied": [],
        "quality_range": None,
        "env_values": ("1.0", "2.0", "8.0", "5.0", "12", "5.0", "8.0", "7.0", "11", "17", ".50", "9.0", "24", "450"),
        "name": "Microwave ferrite device, {text}",
        "parts": [
            (None, None, "Isolators & Circulators (≤100W)", "0.10"),
            (None, None, "Isolators & Circulators (>100W)", "0.20"),
            (None, None, "Phase Shifter (Latching)", "0.10"),
        ],
    },
    {
        "section": "23.1", "title": "Miscellaneous parts: dummy loads", "equipment_type": "electronic_other",
        "rates": ("F", "23-1", 174), "env": ("F", "23-2", 175),
        "formula": "λp = rate × πE",
        "not_applied": [],
        "quality_range": None,
        "env_values": ("1.0", "2.0", "10", "5.0", "17", "6.0", "8.0", "14", "22", "25", ".50", "14", "36", "660"),
        "name": "Dummy load, {text}",
        "parts": [
            (None, None, "< 100W", "0.010", "dummy load up to 100w"),
            (None, None, "100W to ≤ 1000W", "0.030", "dummy load 100w to 1000w"),
            (None, None, "> 1000W", "0.10", "dummy load over 1000w"),
        ],
    },
    {
        "section": "23.1", "title": "Miscellaneous parts", "equipment_type": "electronic_other",
        "rates": ("F", "23-1", 174), "env": None,
        "formula": "λp (a fixed rate: no factors)",
        "not_applied": [],
        "quality_range": None,
        "env_values": None,
        "name": "{text}",
        "parts": [
            (None, "MIL-V-95", "Vibrator (MIL-V-95), 60-cycle", "15"),
            (None, "MIL-V-95", "Vibrator (MIL-V-95), 120-cycle", "20"),
            (None, "MIL-V-95", "Vibrator (MIL-V-95), 400-cycle", "40"),
            (None, None, "Neon Lamp", "0.20"),
            (None, None, "Single Fiber Optic Connector", "0.10"),
            (None, None, "Microwave Variable Element (Tuned Stubs & Cavities)", "0.10"),
        ],
        "part_notes": {
            "Single Fiber Optic Connector": "The handbook cautions that many mating cycles may seriously degrade "
                                            "it.",
        },
    },
    {
        "section": "5.6", "title": "Microcircuits, SAW devices", "equipment_type": "microcircuit",
        "rates": ("N2", "5-10", 25), "env": ("N2", "5-10", 25), "retrieved": "2026-11-08",
        "formula": "λp = 2.1 πQ πE",
        "not_applied": [_f("πQ")],
        "quality_range": (0.10, 1.0),
        "env_values": (".5", "2.0", "4.0", "4.0", "6.0", "4.0", "5.0", "5.0", "8.0", "8.0", ".50", "5.0", "12", "220"),
        "name": "{text}",
        "part_names": {"Surface Acoustic Wave Devices": "Microcircuit, surface acoustic wave (SAW) device"},
        "parts": [(None, None, "Surface Acoustic Wave Devices", "2.1", "saw device")],
        "part_notes": {
            "Surface Acoustic Wave Devices": "πQ is .10 for devices screened with 10 temperature cycles (−55 °C to "
                                             "+125 °C) and end point electrical tests at the temperature extremes, "
                                             "and 1.0 for none beyond best commercial practice.",
        },
    },
    {
        "section": "8.1", "title": "Lasers, helium and argon", "equipment_type": "electronic_other",
        "rates": ("F", "8-2", 77), "env": ("F", "8-2", 77), "retrieved": "2026-11-08",
        "formula": "λp = λMEDIA πE + λCOUPLING πE",
        "not_applied": [],
        "quality_range": None,
        "env_values": (".30", "1.0", "4.0", "3.0", "4.0", "4.0", "6.0", "7.0", "9.0", "5.0", ".10", "3.0", "8.0", NA),
        "name": "{text}",
        "part_names": {"He/Ne": "Laser, helium neon (He/Ne)", "He/Cd": "Laser, helium cadmium (He/Cd)",
                       "Argon": "Laser, argon"},
        "parts": [
            (None, None, "He/Ne", "84", "laser helium neon"),
            (None, None, "He/Cd", "228", "laser helium cadmium"),
            (None, None, "Argon", "463", "laser argon"),
        ],
        "notes": ["The rate is the lasing media rate λMEDIA plus the coupling rate λCOUPLING, both times πE: "
                  "helium lasers 84 (He/Ne) or 228 (He/Cd) + 0 (the handbook calls helium coupling negligible), "
                  "argon 457 + 6."],
        "part_notes": {
            "Argon": "The handbook notes that an argon laser's mirrors can be expected to deteriorate after about "
                     "10,000 hours if in contact with the discharge region, when the tube is refilled periodically.",
        },
    },
]

#: Numbers the OCR text of their page misreads, each checked by eye against
#: the page image: (document, printed page, the number as typed) -> what the
#: OCR text has instead.
OCR_MISREADS: dict[tuple[str, str, str], str] = {
    ("F", "6-4", ".0025"): "'.0’025' (varactor and step recovery)",
    ("F", "6-8", ".012"): "nothing: the MOSFET row's rate is missing from the text",
    ("F", "6-8", ".0045"): "nothing: the JFET row's rate is missing from the text",
    ("F", "6-9", "320"): "nothing: the CL row's factor is missing from the text",
    ("N2", "9-3", "1728"): "'1720' (CL)",
    ("N2", "10-2", ".00012"): "nothing: the CU, CUR and CE rows' rates are missing from the text",
    ("N2", "11-1", ".50"): "'50' (SF)",
    ("N2", "14-1", "4.3"): "a garbled line (limit switch)",
    ("N2", "17-1", "11"): "nothing: the NU row's factor is missing from the text",
    ("N2", "5-10", "12"): "'42' (ML)",
    ("N2", "5-10", "2.1"): "nothing: the formula line (λp = 2.1 πQ πE) is missing from the text",
    ("F", "8-2", "463"): "not printed as one number: argon's λMEDIA 457 + λCOUPLING 6, both on the page",
}

#: What isn't imported, and why. Each a (section, what, reason).
SKIPPED: list[tuple[str, str, str]] = [
    ("5.1-5.5", "Microcircuits, part stress model (gate arrays, microprocessors, memories, VHSIC, GaAs)",
     "The model adds a die term and a package term (C1 πT + C2 πE), each from the device's complexity and "
     "package. Imported instead: the parts-count generic rates (Appendix A) by complexity band."),
    ("5.3", "Microcircuits, VHSIC/VHSIC-like and VLSI CMOS",
     "Appendix A refers these to the section 5.3 model (die area, package, ESD rating): no generic rate."),
    ("5.7", "Microcircuits, magnetic bubble memories",
     "The rate is a formula of the number of chips, loops and dissipative elements, and the duty cycle."),
    ("5.5", "Microcircuits, hybrids",
     "The handbook gives no generic rate: each hybrid is unique, and its rate is the sum of the parts in it."),
    ("6.1", "Diodes, low frequency: power rectifier with high voltage stacks",
     "The base rate is per junction (.0050 per junction): it needs the number of junctions."),
    ("6.6-6.9", "Transistors, high frequency (low noise bipolar, high power bipolar, GaAs FET, Si FET)",
     "The base rate is a formula of frequency and output power (or a table of them), not one number per type."),
    ("6.12", "Optoelectronics, alphanumeric displays",
     "The base rate is a formula of the number of characters and whether a logic chip is included."),
    ("6.13", "Optoelectronics, laser diodes, part stress model",
     "The base rate depends on the material and on optical power and current. Imported instead: the "
     "parts-count generic rates (Appendix A)."),
    ("7.1-7.3", "Tubes (including travelling wave tubes and magnetrons)",
     "Not imported in this release: the base rates depend on tube type, power and frequency, and few designs "
     "use tubes now. Appendix A has no generic rates for tubes (it refers to section 7)."),
    ("8.2-8.4", "Lasers, carbon dioxide (sealed and flowing) and solid state (Nd:YAG, ruby)",
     "The rates are formulas of tube current, gas flow or the flashlamp's pulse energy and rate; Appendix A "
     "has no generic rates for lasers (it refers to section 8)."),
    ("12.1", "Rotating devices, motors, life model",
     "A life model for bearings and windings (characteristic lives by temperature), not a constant base rate. "
     "Imported instead: the parts-count generic rates (Appendix A, 10-year design life)."),
    ("12.2", "Rotating devices, synchros and resolvers, part stress model",
     "The base rate is a formula of the frame temperature. Imported instead: the parts-count generic rates "
     "(Appendix A)."),
    ("13.1", "Relays, mechanical",
     "The base rate depends on the ambient temperature (.0059 at 25 °C to .031 at 125 °C for a 125 °C rated "
     "relay): no one number per type."),
    ("16.1", "Interconnection assemblies with plated through holes, part stress model",
     "The base rate is per plated through hole, weighted by the number of circuit planes: it needs the board's "
     "hole counts. Imported instead: the parts-count generic rate (Appendix A)."),
    ("16.2", "Interconnection assemblies, surface mount technology, part stress model",
     "A wear-out model in thermal cycles, not a constant base rate. Imported instead: the parts-count generic "
     "rate (Appendix A)."),
    ("19.1", "Quartz crystals, part stress model",
     "The base rate is a formula of frequency (.013 f^0.23). Imported instead: the parts-count generic rate "
     "(Appendix A, 50 MHz)."),
    ("20.1", "Lamps, incandescent, part stress model",
     "The base rate is a formula of rated voltage (.074 Vr^1.29). Imported instead: the parts-count generic "
     "rates (Appendix A)."),
    ("23.1", "Fiber optic cables", "The rate is per kilometre of fibre, a unit the library doesn't convert."),
    ("23.1", "Microwave attenuators", "The handbook refers these to the resistor model (style RD)."),
    ("23.1", "Microwave fixed elements (directional couplers, fixed stubs and cavities)",
     "The handbook gives their rate as negligible, not a number."),
    ("23.1", "Terminations (thin or thick film loads in stripline and thin film circuits)",
     "Given as 0.030 × πE without saying which environment table applies."),
    ("Appendix A", "Parts count: discrete semiconductors, resistors, capacitors, inductive devices, elapsed time "
                   "meters, relays, switches, connectors, connections, meters, filters and fuses",
     "Not imported in this release: the library has these parts' part stress base rates and environment "
     "factors instead."),
    ("—", "Batteries and mechanical parts",
     "MIL-HDBK-217F covers electronic parts only: it has no batteries and no mechanical parts."),
]


# ---- the records -----------------------------------------------------------------------------

#: Words kept as printed: proper names and units (acronyms, part numbers and
#: anything with a digit are kept anyway).
_KEEP = {"Si", "Hz", "Schottky", "Gunn", "Zener"}
#: The handbook's American spellings, in the names (its own text keeps them).
_BRITISH = {"aluminum": "aluminium", "metallized": "metallised", "supermetallized": "supermetallised",
            "polarized": "polarised", "fiber": "fibre"}


def _keep(word: str) -> bool:
    return (sum(c.isupper() for c in word) >= 2 or any(c.isdigit() for c in word) or word in _KEEP
            or not word[:1].isalpha())


def plain(text: str) -> str:
    """The handbook's Title Case description in lower case, keeping acronyms,
    part numbers and proper names ('Fixed, Film (High Stability)' -> 'fixed,
    film (high stability)'; 'PIN', 'RF', 'MIL-F-15733', 'Schottky' stay),
    with British spelling."""
    text = re.sub(r"\bEst\.\s*Rel\.", "Established Reliability", text)
    words = re.split(r"(\s+|[(),/&]|-(?=[A-Za-z]))", text)
    words = [w if not w.strip() or _keep(w) else w.lower() for w in words]
    return "".join(_BRITISH.get(w, w) for w in words)


def slug(text: str) -> str:
    s = text.lower().replace("≤", "le").replace("≥", "ge").replace("<", "lt").replace(">", "gt").replace("&", "and")
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def number(printed: str) -> float:
    return float(printed)


def _name(group: dict, text: str) -> str:
    own = (group.get("part_names") or {}).get(text)
    if own:
        return own
    template = group["name"]
    if "{text}" not in template:
        return template
    body = plain(text)
    if template == "{text}":
        return body[:1].upper() + body[1:]
    return template.format(text=body)


def rate_page(group: dict, index: int) -> tuple[str, str, int]:
    """Where the group's ``index``-th part's base rate is printed: (document,
    printed page, PDF page)."""
    second = group.get("rates_2")
    if second and index >= second[3]:
        return second[:3]
    return group["rates"]


def record(group: dict, index: int, retrieved: str) -> dict:
    """The ``index``-th part of a group as a library record."""
    style, spec, text, printed, *own_key = group["parts"][index]
    lam = number(printed)
    per_hour = float(f"{printed}e-6")  # the printed digits, without float noise from × 1e-6
    section = group["section"]
    doc, page, _ = rate_page(group, index)
    name = _name(group, text)
    code = f"{section} {style}" if style else f"{section} {text}"
    if own_key:
        key = f"{section} {own_key[0]}"
    elif style:
        key = f"{section} {style.split()[0]} {spec.split('-')[-1]}"
    else:
        key = f"{section} {text}"
    full_model = not group["not_applied"]
    label = f"{name}" + (f" ({style}, {spec})" if style else "") + (
        ": failure rate" if full_model else ": base failure rate")
    pages = [page]
    env = None
    if group["env_values"]:
        env_doc, env_page, _ = group["env"]
        values = {e: number(v) for e, v in zip(ENV_ORDER, group["env_values"]) if v is not NA}
        env = {"symbol": "πE", "table": f"Section {section}, Environment Factor πE", "page": env_page,
               "document": DOCUMENTS[env_doc]["part"], "values": values,
               "not_given": [e for e, v in zip(ENV_ORDER, group["env_values"]) if v is NA]}
        if env_page != page:
            pages.append(env_page)
    not_applied = [{"symbol": s, "name": n} for s, n in group["not_applied"]]
    notes = []
    if full_model:
        notes.append("This is the handbook's whole model for this part: the rate"
                     + (" times the environment factor." if env else "."))
    else:
        left_out = ", ".join(f"{f['symbol']} ({f['name']})" for f in not_applied)
        notes.append(f"Base failure rate only. The handbook's model is {group['formula']}; Reliafy applies λb × πE "
                     f"and leaves out {left_out}. Real rates depend on them.")
    if group.get("quality_range"):
        lo, hi = group["quality_range"]
        notes.append(f"The quality factor πQ (left out) runs from {lo:g} to {hi:g} for these parts.")
    notes.extend(group.get("notes") or [])
    if (group.get("part_notes") or {}).get(text):
        notes.append(group["part_notes"][text])
    if env and env["not_given"]:
        notes.append(f"The handbook gives no environment factor for {', '.join(env['not_given'])}.")
    conditions = {"industry": "Military and aerospace electronics (handbook prediction)",
                  "section": f"{section} {group['title']}"}
    if spec or group.get("specification"):
        conditions["specification"] = spec or group["specification"]
    if style:
        conditions["style"] = style
    rec = {
        "id": f"{SOURCE_ID}:{slug(key)}",
        "version": DATA_VERSION,
        "source": SOURCE_ID,
        "source_code": code,
        "name": name,
        "label": label,
        "equipment_type": group["equipment_type"],
        "kind": "rate",
        "basis": "prediction_model",
        "failure_mode": {"code": "ALL", "name": "Any failure",
                         "meaning": "The part stops doing its job, in any way: the handbook's rate covers every "
                                    "failure mode together."},
        "distribution": {"family": "point", "params": [{"name": "value", "value": per_hour}]},
        "summary": {"mean": per_hour, "median": None, "p05": None, "p95": None, "error_factor": None},
        "units": {"value": "per_hour", "time_basis": "operating", "as_given": "failures per million hours"},
        "evidence": {"failures": None, "demands": None, "exposure": None, "exposure_unit": None, "components": None,
                     "sites": None, "period": None, "data_source": "MIL-HDBK-217F part stress model",
                     "method": "Handbook prediction model (base failure rate and factors)"},
        "conditions": conditions,
        "prediction": {"formula": group["formula"] + " (failures per million hours)", "per_million_hours": lam,
                       "applied": ["λb", "πE"] if env and not full_model else [],
                       "not_applied": not_applied,
                       "quality_factor_range": list(group["quality_range"]) if group.get("quality_range") else None},
        "environment_factors": env,
        "source_text": text,
        "citation": {
            "title": TITLE, "publisher": PUBLISHER, "report": REPORT, "edition": SOURCE["edition"],
            "year": 1995 if doc == "N2" else 1991, "table": f"Section {section}, Base Failure Rate",
            "page": ", ".join(pages), "document": DOCUMENTS[doc]["part"],
            "url": ASSIST_URL, "retrieved": group.get("retrieved") or retrieved,
        },
        "licence": {k: SOURCE["licence"][k] for k in ("id", "name", "attribution")},
        "notes": notes,
    }
    if env is None:
        del rec["environment_factors"]
    return rec


# ---- the parts-count tables (Appendix A), typed from the page images ------------------------
#
# Appendix A's parts count method: λ = Σ N (λg πQ), with λg the generic failure rate of a part
# type in each environment (the handbook's part stress model worked out at its default values,
# environment included) and πQ its quality factor. The tables are printed sideways and their
# OCR text is unreadable, so these numbers can't be checked against the text the way the part
# stress tables are: each was typed from the page image and checked against a second,
# independent reading of the same images, and where a row is one base rate times the section's
# πE (quartz crystals, circuit boards) against that product too (``test_library`` keeps those
# checks). Where the two readings differed (bipolar microprocessors up to 16 bits, CL: 5.8;
# resolvers, AUF: 2.8), the cell was read again at higher magnification. Each group: section, title, the page (document, printed page, PDF page), the
# equipment type, the quality table (a key of PC_QUALITY, or None where the handbook gives
# none), the factors the generic rate holds at the handbook's defaults (``held``), notes, and
# rows of (the row's words, the package or assumption printed with it, 14 rates as printed, in
# ENV_ORDER; "*" where the handbook marks the part not normally used in that environment).

PC_RETRIEVED = "2026-11-08"
NOT_USED = "*"

#: The quality factor tables Appendix A gives with its generic rates: each level (code, the
#: handbook's words, πQ as printed) and the default a parts list without a grade takes (the
#: lowest grade the handbook lists: commercial or unknown screening for microcircuits, non-MIL
#: for the other parts), or None where the handbook names no such grade.
PC_QUALITY: dict[str, dict] = {
    "microcircuit": {
        "page": ("N2", "A-4", 67), "table": "Appendix A, Quality Factors πQ (microcircuits)",
        "levels": [
            ("S", "Class S: procured to MIL-M-38510 class S, MIL-I-38535 class U, or hybrids to MIL-H-38534 "
                  "class S (quality level K)", ".25"),
            ("B", "Class B: procured to MIL-M-38510 class B, MIL-I-38535 class Q, or hybrids to MIL-H-38534 "
                  "class B (quality level H)", "1.0"),
            ("B-1", "Class B-1: fully compliant with MIL-STD-883 paragraph 1.2.1 and procured to a MIL drawing, "
                    "DESC drawing or other government approved documentation (not hybrids)", "2.0"),
            ("commercial", "Other commercial or unknown screening levels", "10"),
        ],
        "default": "commercial",
        "note": "A custom screening programme has πQ = 2 + 87 ÷ the sum of its MIL-STD-883 tests' point "
                "valuations (page A-4); the handbook's examples give 3.1 and 5.5.",
    },
    "laser_diode": {
        "page": ("N2", "A-6", 69), "table": "Appendix A, Discrete Semiconductor Quality Factors πQ (laser diodes)",
        "levels": [
            ("hermetic", "Hermetic package", "1.0"),
            ("nonhermetic_facet", "Nonhermetic with facet coating", "1.0"),
            ("nonhermetic", "Nonhermetic without facet coating", "3.3"),
        ],
        "default": None,
        "note": None,
    },
    "pth_board": {
        "page": ("N2", "A-11", 74), "table": "Appendix A, πQ Factor for Use with Section 11-22 Devices",
        "levels": [("mil", "MIL-SPEC", "1.0"), ("non_mil", "Non-MIL", "2.0")],
        "default": "non_mil", "note": None,
    },
    "crystal": {
        "page": ("N2", "A-11", 74), "table": "Appendix A, πQ Factor for Use with Section 11-22 Devices",
        "levels": [("mil", "MIL-SPEC", "1.0"), ("non_mil", "Non-MIL", "2.1")],
        "default": "non_mil", "note": None,
    },
}

_MICRO_HELD = [
    ("πT", "temperature", "the junction temperature printed for each environment (50 to 90 °C)"),
    ("C1, C2", "die complexity and package", "the band's complexity and the package printed with it"),
    ("πL", "learning", "1, a device in production 2 years or more (multiply by up to 2.0 for a newer one)"),
]
_MICRO_DEFAULTS = ("Appendix A's defaults: πT from the activation energy (Ea) shown, solder or weld seal DIPs and "
                   "PGAs with the pins shown, πL = 1 (device in production 2 years or more).")


def _micro(section: str, family: str, ea: str, page: tuple, rows: list, words: str) -> dict:
    return {"section": section, "family": family, "title": f"Microcircuits, {family}", "page": page,
            "table": "Appendix A, Generic Failure Rate λg for Microcircuits", "equipment_type": "microcircuit",
            "quality": "microcircuit", "held": _MICRO_HELD, "name": f"Microcircuit, {words}, {{row}}",
            "notes": [f"Activation energy Ea = {ea} eV. " + _MICRO_DEFAULTS], "rows": rows}


_A2 = ("N2", "A-2", 65)
_A3 = ("N2", "A-3", 66)

PARTS_COUNT: list[dict] = [
    _micro("5.1", "bipolar gate/logic arrays, digital", ".4", _A2, [
        ("1 to 100 gates", "16 pin DIP", (".0036", ".012", ".024", ".024", ".035", ".025", ".030", ".032", ".049", ".047", ".0036", ".030", ".069", "1.2")),
        ("101 to 1,000 gates", "24 pin DIP", (".0060", ".020", ".038", ".037", ".055", ".039", ".048", ".051", ".077", ".074", ".0060", ".046", ".11", "1.9")),
        ("1,001 to 3,000 gates", "40 pin DIP", (".011", ".035", ".066", ".065", ".097", ".070", ".085", ".091", ".14", ".13", ".011", ".082", ".19", "3.3")),
        ("3,001 to 10,000 gates", "128 pin PGA", (".033", ".12", ".22", ".22", ".33", ".23", ".28", ".30", ".46", ".44", ".033", ".28", ".65", "12")),
        ("10,000 to 30,000 gates", "180 pin PGA", (".052", ".17", ".33", ".33", ".48", ".34", ".42", ".45", ".68", ".65", ".052", ".41", ".95", "17")),
        ("30,000 to 60,000 gates", "224 pin PGA", (".075", ".23", ".44", ".43", ".63", ".46", ".56", ".61", ".90", ".85", ".075", ".53", "1.2", "21")),
    ], "bipolar gate/logic array (digital)"),
    _micro("5.1", "bipolar linear", ".65", _A2, [
        ("1 to 100 transistors", "14 pin DIP", (".0095", ".024", ".039", ".034", ".049", ".057", ".062", ".12", ".13", ".076", ".0095", ".044", ".096", "1.1")),
        ("101 to 300 transistors", "18 pin DIP", (".017", ".041", ".065", ".054", ".078", ".10", ".11", ".22", ".24", ".13", ".017", ".072", ".15", "1.4")),
        ("301 to 1,000 transistors", "24 pin DIP", (".033", ".074", ".11", ".092", ".13", ".19", ".19", ".41", ".44", ".22", ".033", ".12", ".26", "2.0")),
        ("1,001 to 10,000 transistors", "40 pin DIP", (".050", ".12", ".18", ".15", ".21", ".29", ".30", ".63", ".67", ".35", ".050", ".19", ".41", "3.4")),
    ], "bipolar linear"),
    _micro("5.1", "bipolar programmable logic arrays", ".4", _A2, [
        ("up to 200 gates", "16 pin DIP", (".0061", ".016", ".029", ".027", ".040", ".032", ".037", ".044", ".061", ".054", ".0061", ".034", ".076", "1.2")),
        ("201 to 1,000 gates", "24 pin DIP", (".011", ".028", ".048", ".045", ".065", ".054", ".063", ".077", ".10", ".089", ".011", ".057", ".12", "1.9")),
        ("1,001 to 5,000 gates", "40 pin DIP", (".022", ".052", ".087", ".082", ".12", ".099", ".11", ".14", ".19", ".16", ".022", ".10", ".22", "3.3")),
    ], "bipolar programmable logic array"),
    _micro("5.1", "MOS gate/logic arrays, digital", ".35", _A2, [
        ("1 to 100 gates", "16 pin DIP", (".0057", ".015", ".027", ".027", ".039", ".029", ".035", ".039", ".056", ".052", ".0057", ".033", ".074", "1.2")),
        ("101 to 1,000 gates", "24 pin DIP", (".010", ".026", ".045", ".043", ".062", ".049", ".057", ".066", ".092", ".083", ".010", ".053", ".12", "1.9")),
        ("1,001 to 3,000 gates", "40 pin DIP", (".019", ".047", ".080", ".077", ".11", ".088", ".10", ".12", ".17", ".15", ".019", ".095", ".21", "3.3")),
        ("3,001 to 10,000 gates", "128 pin PGA", (".049", ".14", ".25", ".24", ".36", ".27", ".32", ".36", ".51", ".48", ".049", ".30", ".69", "12")),
        ("10,001 to 30,000 gates", "180 pin PGA", (".084", ".22", ".39", ".37", ".54", ".42", ".49", ".56", ".79", ".72", ".084", ".46", "1.0", "17")),
        ("30,000 to 60,000 gates", "224 pin PGA", (".13", ".31", ".53", ".51", ".73", ".59", ".69", ".82", "1.1", ".98", ".13", ".63", "1.4", "21")),
    ], "MOS gate/logic array (digital)"),
    _micro("5.1", "MOS linear", ".65", _A2, [
        ("1 to 100 transistors", "14 pin DIP", (".0095", ".024", ".039", ".034", ".049", ".057", ".062", ".12", ".13", ".076", ".0095", ".044", ".096", "1.1")),
        ("101 to 300 transistors", "18 pin DIP", (".017", ".041", ".065", ".054", ".078", ".10", ".11", ".22", ".24", ".13", ".017", ".072", ".15", "1.4")),
        ("301 to 1,000 transistors", "24 pin DIP", (".033", ".074", ".11", ".092", ".13", ".19", ".19", ".41", ".44", ".22", ".033", ".12", ".26", "2.0")),
        ("1,001 to 10,000 transistors", "40 pin DIP", (".05", ".12", ".18", ".15", ".21", ".29", ".30", ".63", ".67", ".35", ".05", ".19", ".41", "3.4")),
    ], "MOS linear"),
    _micro("5.1", "MOS floating gate programmable logic arrays", ".35", _A2, [
        ("up to 500 gates", "24 pin DIP", (".0046", ".018", ".035", ".035", ".052", ".035", ".044", ".044", ".070", ".070", ".0046", ".044", ".10", "1.9")),
        ("501 to 2,000 gates", "28 pin DIP", (".0056", ".021", ".042", ".042", ".062", ".042", ".052", ".053", ".084", ".083", ".0056", ".052", ".12", "2.3")),
        ("2,001 to 5,000 gates", "28 pin DIP", (".0061", ".022", ".043", ".042", ".063", ".043", ".054", ".055", ".086", ".084", ".0061", ".053", ".13", "2.3")),
        ("5,001 to 20,000 gates", "40 pin DIP", (".0095", ".033", ".064", ".063", ".094", ".065", ".080", ".083", ".13", ".13", ".0095", ".079", ".19", "3.3")),
    ], "MOS floating gate programmable logic array"),
    _micro("5.1", "microprocessors, bipolar", ".4", _A2, [
        ("up to 8 bits", "40 pin DIP", (".028", ".061", ".098", ".091", ".13", ".12", ".13", ".17", ".22", ".18", ".028", ".11", ".24", "3.3")),
        ("up to 16 bits", "64 pin PGA", (".052", ".11", ".18", ".16", ".23", ".21", ".24", ".32", ".39", ".31", ".052", ".20", ".41", "5.8")),
        ("up to 32 bits", "128 pin PGA", (".11", ".23", ".36", ".33", ".47", ".44", ".49", ".65", ".81", ".65", ".11", ".42", ".86", "12")),
    ], "microprocessor (bipolar)"),
    _micro("5.1", "microprocessors, MOS", ".35", _A2, [
        ("up to 8 bits", "40 pin DIP", (".048", ".089", ".13", ".12", ".16", ".16", ".17", ".24", ".28", ".22", ".048", ".15", ".28", "3.4")),
        ("up to 16 bits", "64 pin PGA", (".093", ".17", ".24", ".22", ".29", ".30", ".32", ".45", ".52", ".40", ".093", ".27", ".50", "5.6")),
        ("up to 32 bits", "128 pin PGA", (".19", ".34", ".49", ".45", ".60", ".61", ".66", ".90", "1.1", ".82", ".19", ".54", "1.0", "12")),
    ], "microprocessor (MOS)"),
    _micro("5.2", "MOS memories, ROM", ".6", _A3, [
        ("up to 16K", "24 pin DIP", (".0047", ".018", ".036", ".035", ".053", ".037", ".045", ".048", ".074", ".071", ".0047", ".044", ".11", "1.9")),
        ("16K to 64K", "28 pin DIP", (".0059", ".022", ".043", ".042", ".063", ".045", ".055", ".060", ".090", ".086", ".0059", ".053", ".13", "2.3")),
        ("64K to 256K", "28 pin DIP", (".0067", ".023", ".045", ".044", ".066", ".048", ".059", ".068", ".099", ".089", ".0067", ".055", ".13", "2.3")),
        ("256K to 1 MB", "40 pin DIP", (".011", ".036", ".068", ".066", ".098", ".075", ".090", ".11", ".15", ".14", ".011", ".083", ".20", "3.3")),
    ], "memory, MOS ROM"),
    _micro("5.2", "MOS memories, PROM, UVEPROM, EEPROM, EAPROM", ".6", _A3, [
        ("up to 16K", "24 pin DIP", (".0049", ".018", ".036", ".036", ".053", ".037", ".046", ".049", ".075", ".072", ".0048", ".045", ".11", "1.9")),
        ("16K to 64K", "28 pin DIP", (".0061", ".022", ".044", ".043", ".064", ".046", ".056", ".062", ".093", ".087", ".0062", ".054", ".13", "2.3")),
        ("64K to 256K", "28 pin DIP", (".0072", ".024", ".046", ".045", ".067", ".051", ".061", ".073", ".10", ".092", ".0072", ".057", ".13", "2.3")),
        ("256K to 1 MB", "40 pin DIP", (".012", ".038", ".071", ".068", ".10", ".080", ".095", ".12", ".16", ".14", ".012", ".086", ".20", "3.3")),
    ], "memory, MOS PROM, UVEPROM, EEPROM or EAPROM"),
    _micro("5.2", "MOS memories, DRAM", ".6", _A3, [
        ("up to 16K", "18 pin DIP", (".0040", ".014", ".027", ".027", ".040", ".029", ".035", ".040", ".059", ".055", ".0040", ".034", ".080", "1.4")),
        ("16K to 64K", "22 pin DIP", (".0055", ".019", ".036", ".034", ".051", ".039", ".047", ".056", ".079", ".070", ".0055", ".043", ".10", "1.7")),
        ("64K to 256K", "24 pin DIP", (".0074", ".023", ".043", ".040", ".060", ".049", ".058", ".076", ".10", ".084", ".0074", ".051", ".12", "1.9")),
        ("256K to 1 MB", "28 pin DIP", (".011", ".032", ".057", ".053", ".077", ".070", ".080", ".12", ".15", ".11", ".011", ".067", ".15", "2.3")),
    ], "memory, MOS DRAM"),
    _micro("5.2", "MOS memories, SRAM (MOS and BiMOS)", ".6", _A3, [
        ("up to 16K", "18 pin DIP", (".0079", ".022", ".038", ".034", ".050", ".048", ".054", ".083", ".10", ".073", ".0079", ".044", ".098", "1.4")),
        ("16K to 64K", "22 pin DIP", (".014", ".034", ".057", ".050", ".073", ".077", ".085", ".14", ".17", ".11", ".014", ".065", ".14", "1.8")),
        ("64K to 256K", "24 pin DIP", (".023", ".053", ".084", ".071", ".10", ".12", ".13", ".25", ".27", ".16", ".023", ".092", ".19", "1.9")),
        ("256K to 1 MB", "28 pin DIP", (".043", ".092", ".14", ".11", ".16", ".22", ".23", ".46", ".49", ".26", ".043", ".15", ".30", "2.3")),
    ], "memory, MOS or BiMOS SRAM"),
    _micro("5.2", "bipolar memories, ROM, PROM", ".6", _A3, [
        ("up to 16K", "24 pin DIP", (".010", ".028", ".050", ".046", ".067", ".062", ".070", ".10", ".13", ".096", ".010", ".058", ".13", "1.9")),
        ("16K to 64K", "28 pin DIP", (".017", ".043", ".071", ".063", ".091", ".095", ".11", ".18", ".21", ".14", ".017", ".081", ".18", "2.3")),
        ("64K to 256K", "28 pin DIP", (".028", ".065", ".10", ".085", ".12", ".15", ".16", ".30", ".33", ".19", ".028", ".11", ".23", "2.3")),
        ("256K to 1 MB", "40 pin DIP", (".053", ".12", ".18", ".15", ".21", ".27", ".29", ".56", ".61", ".33", ".053", ".19", ".39", "3.4")),
    ], "memory, bipolar ROM or PROM"),
    _micro("5.2", "bipolar memories, SRAM", ".6", _A3, [
        ("up to 16K", "24 pin DIP", (".0075", ".023", ".043", ".041", ".060", ".050", ".058", ".077", ".10", ".084", ".0075", ".052", ".12", "1.9")),
        ("16K to 64K", "28 pin DIP", (".012", ".033", ".058", ".054", ".079", ".072", ".083", ".12", ".15", ".11", ".012", ".069", ".15", "2.3")),
        ("64K to 256K", "28 pin DIP", (".018", ".045", ".074", ".065", ".095", ".10", ".11", ".19", ".22", ".14", ".018", ".084", ".18", "2.3")),
        ("256K to 1 MB", "40 pin DIP", (".033", ".079", ".13", ".11", ".16", ".18", ".20", ".35", ".39", ".24", ".033", ".14", ".30", "3.4")),
    ], "memory, bipolar SRAM"),
    _micro("5.4", "GaAs MMIC", "1.5", _A3, [
        ("1 to 100 active elements", "8 pin DIP", (".0013", ".0052", ".010", ".010", ".016", ".011", ".013", ".015", ".022", ".021", ".0013", ".013", ".031", ".57")),
        ("101 to 1,000 active elements", "16 pin DIP", (".0028", ".011", ".022", ".022", ".034", ".023", ".028", ".030", ".047", ".045", ".0028", ".028", ".068", "1.2")),
    ], "GaAs MMIC"),
    _micro("5.4", "GaAs digital", "1.4", _A3, [
        ("1 to 1,000 active elements", "36 pin DIP", (".0066", ".026", ".052", ".052", ".078", ".054", ".067", ".078", ".12", ".11", ".0066", ".065", ".16", "2.9")),
        ("1,001 to 10,000 active elements", "64 pin PGA", (".013", ".050", ".10", ".10", ".15", ".10", ".13", ".15", ".23", ".20", ".013", ".13", ".30", "5.5")),
    ], "GaAs digital"),
    {
        "section": "6.13", "family": "laser diodes", "title": "Optoelectronics, laser diodes", "page": ("N2", "A-6", 69),
        "table": "Appendix A, Generic Failure Rate λg for Discrete Semiconductors", "equipment_type": "semiconductor",
        "quality": "laser_diode", "name": "Laser diode, {row}",
        "held": [("πT", "temperature", "the junction temperature printed for each environment (50 to 90 °C)"),
                 ("πI", "forward current", "a forward peak current of .5 A"),
                 ("πA", "application", "pulsed, duty cycle .6"),
                 ("πP", "power degradation", "1 (ratio of required to rated optical power .5)")],
        "notes": ["Appendix A's defaults (page A-13): forward peak current .5 A, pulsed with a duty cycle of .6, "
                  "required to rated optical power .5."],
        "rows": [
            ("GaAs/Al GaAs", None, ("5.1", "16", "78", "39", "120", "58", "86", "86", "110", "240", "2.6", "87", "350", "3600")),
            ("In GaAs/In GaAsP", None, ("9.0", "28", "135", "69", "200", "100", "150", "150", "200", "400", "4.5", "150", "600", "6200")),
        ],
    },
    {
        "section": "12.1", "family": "motors", "title": "Rotating devices, motors", "page": ("N2", "A-9", 72),
        "table": "Appendix A, Generic Failure Rate λg for Inductive, Electromechanical and Miscellaneous Parts",
        "equipment_type": "rotating", "quality": None, "name": "Motor, {row}",
        "held": [("αB", "bearing characteristic life", "the handbook's value at the ambient temperature printed for each environment"),
                 ("αW", "winding characteristic life", "the handbook's value at the ambient temperature printed for each environment"),
                 ("LC", "design life", "10 years (87,600 hours)")],
        "notes": ["The handbook's motor model (section 12.1) is life based: it works out an average failure rate "
                  "over the motor's design life from the bearings' and windings' characteristic lives at its "
                  "temperature. That model isn't applied here: these are Appendix A's generic rates, which assume a "
                  "10-year (87,600 hour) design life at the ambient temperature printed for each environment "
                  "(30 to 70 °C).",
                  "The handbook's motor models cover motors up to 1 horsepower. It gives no quality factor for "
                  "rotating devices."],
        "rows": [
            ("general", None, ("6.9", "6.8", "8.3", "6.8", "8.3", "13", "13", "30", "30", "13", "6.9", NOT_USED, NOT_USED, NOT_USED)),
            ("sensor", None, ("27", "27", "33", "27", "33", "52", "52", "1.2e+02", "1.2e+02", "52", "27", "33", "52", "27")),
            ("servo", None, ("5.4", "5.4", "6.5", "5.4", "6.5", "10", "10", "23", "23", "10", "5.4", "6.5", "10", "5.4")),
            ("stepper", None, ("1.2", "1.2", "1.4", "1.2", "1.4", "2.3", "2.3", "5.3", "5.3", "2.3", "1.2", "1.4", "2.3", "1.2")),
        ],
    },
    {
        "section": "12.2", "family": "synchros and resolvers", "title": "Rotating devices, synchros and resolvers",
        "page": ("N2", "A-9", 72),
        "table": "Appendix A, Generic Failure Rate λg for Inductive, Electromechanical and Miscellaneous Parts",
        "equipment_type": "rotating", "quality": None, "name": "{row}",
        "held": [("λb", "base rate (frame temperature)", "the ambient temperature printed for each environment"),
                 ("πS", "size", "size 10 to 16"), ("πN", "number of brushes", "3 brushes")],
        "notes": ["Appendix A's defaults: size 10 to 16, 3 brushes. The handbook gives no quality factor for "
                  "rotating devices."],
        "rows": [
            ("Synchro", None, (".031", ".071", ".47", ".25", ".70", ".19", ".28", "1.1", "1.8", "1.2", ".016", ".54", "1.7", "24")),
            ("Resolver", None, (".047", ".11", ".70", ".37", "1.0", ".28", ".43", "1.7", "2.8", "1.8", ".023", ".81", "2.6", NOT_USED)),
        ],
    },
    {
        "section": "16.1", "family": "plated through hole circuit boards", "title": "Interconnection assemblies with plated through holes",
        "page": ("N2", "A-10", 73),
        "table": "Appendix A, Generic Failure Rate λg for Inductive, Electromechanical and Miscellaneous Parts",
        "equipment_type": "circuit_board", "quality": "pth_board",
        "name": "Printed circuit board, plated through holes",
        "held": [("N1, N2", "solder joints", "1,000 wave solder joints, no hand soldering"),
                 ("πC", "complexity", "3 circuit planes")],
        "notes": ["Appendix A's defaults: 1,000 wave solder joints, 3 circuit planes, no hand soldering. The "
                  "handbook's model (section 16.1) counts the board's plated through holes; for a board far from "
                  "these defaults, work it out from section 16.1."],
        "rows": [("", None, (".022", ".045", ".16", ".11", ".29", ".11", ".18", ".36", ".62", ".42", ".011", ".22", ".60", "11"))],
    },
    {
        "section": "16.2", "family": "surface mount technology circuit boards", "title": "Interconnection assemblies, surface mount technology",
        "page": ("N2", "A-10", 73),
        "table": "Appendix A, Generic Failure Rate λg for Inductive, Electromechanical and Miscellaneous Parts",
        "equipment_type": "circuit_board", "quality": None,
        "name": "Printed circuit board, surface mount technology",
        "held": [("ΔT, CR", "thermal cycling", "the design and the default ΔT values of the handbook's section 16.2 example"),
                 ("LC", "design life", "the section 16.2 example's")],
        "notes": ["The handbook's surface mount model (section 16.2) is a wear-out model: the solder joints' "
                  "cycles to failure under the board's thermal cycling. That model isn't applied here: these are "
                  "Appendix A's generic rates for the design of its section 16.2 example with the default ΔT "
                  "values. The handbook gives no quality factor for these boards."],
        "rows": [("", None, (".0025", ".37", "1.8", "1.8", "42", "6.1", "6.1", "35", "35", "6.1", ".0025", "11", ".11", ".11"))],
    },
    {
        "section": "19.1", "family": "quartz crystals", "title": "Quartz crystals", "page": ("N2", "A-10", 73),
        "table": "Appendix A, Generic Failure Rate λg for Inductive, Electromechanical and Miscellaneous Parts",
        "equipment_type": "electronic_other", "quality": "crystal", "specification": "MIL-C-3098",
        "name": "Quartz crystal",
        "held": [("λb", "base rate (frequency)", "50 MHz")],
        "notes": ["Appendix A's default: a 50 MHz crystal. The handbook's base rate is .013 f^0.23 (f in MHz), "
                  "so a crystal far from 50 MHz differs a little (10 MHz: about 30% lower)."],
        "rows": [("", None, (".032", ".096", ".32", ".19", ".51", ".38", ".54", ".70", ".90", ".74", ".016", ".42", "1.0", "16"))],
    },
    {
        "section": "20.1", "family": "lamps, incandescent", "title": "Lamps, incandescent", "page": ("N2", "A-10", 73),
        "table": "Appendix A, Generic Failure Rate λg for Inductive, Electromechanical and Miscellaneous Parts",
        "equipment_type": "electronic_other", "quality": None, "name": "Lamp, incandescent, {row}",
        "held": [("λb", "base rate (rated voltage)", "a 28 volt rating"), ("πU", "utilisation", "a utilisation rate of .5")],
        "notes": ["Appendix A's defaults: a utilisation rate of .5 and a 28 volt rating. The handbook gives no "
                  "quality factor for lamps."],
        "rows": [
            ("AC", None, ("3.9", "7.8", "12", "12", "16", "16", "16", "19", "23", "19", "2.7", "16", "23", "100")),
            ("DC", None, ("13", "26", "38", "38", "51", "51", "51", "64", "77", "64", "9.0", "51", "77", "350")),
        ],
    },
]


def _pc_quality(key: str | None) -> dict | None:
    if not key:
        return None
    q = PC_QUALITY[key]
    doc, page, _ = q["page"]
    levels = [{"code": c, "name": n, "value": number(v)} for c, n, v in q["levels"]]
    return {"symbol": "πQ", "table": q["table"], "page": page, "document": DOCUMENTS[doc]["part"],
            "levels": levels, "default": q["default"], **({"note": q["note"]} if q.get("note") else {})}


def parts_count_record(group: dict, index: int, retrieved: str) -> dict:
    """The ``index``-th row of an Appendix A table as a library record: the generic failure rate
    λg for each environment (``generic_rates``), the quality factor table, and the factors the
    rate holds at the handbook's defaults. The record's own value (its distribution) is the
    ground, benign (GB) rate, the first column: a parts count reads the rate for its
    environment from ``generic_rates``."""
    row, package, printed = group["rows"][index]
    doc, page, _ = group["page"]
    section = group["section"]
    values = {e: number(v) for e, v in zip(ENV_ORDER, printed) if v != NOT_USED}
    not_given = [e for e, v in zip(ENV_ORDER, printed) if v == NOT_USED]
    ref = printed[0]
    per_hour = float(f"{float(ref):g}e-6")
    name = group["name"].format(row=row) if "{row}" in group["name"] else group["name"]
    name = name[:1].upper() + name[1:]
    quality = _pc_quality(group.get("quality"))
    q_values = [lv["value"] for lv in quality["levels"]] if quality else []
    q_default = next((lv["value"] for lv in quality["levels"] if lv["code"] == quality["default"]), None) \
        if quality else None
    held = [{"symbol": s, "name": n, "held_at": at} for s, n, at in group["held"]]
    notes = ["Parts count (Appendix A): λ = λg × πQ, where λg is the handbook's generic failure rate for the "
             "environment (its part stress model at default values, environment included)."]
    notes += group.get("notes") or []
    if package:
        notes.append(f"Default package: {package}.")
    if quality:
        lv = "; ".join(f"{x['name']} {x['value']:g}" for x in quality["levels"])
        notes.append(f"Quality factor πQ: {lv}."
                     + (f" With no grade given, a parts count takes {q_default:g} ("
                        f"{next(x['name'] for x in quality['levels'] if x['code'] == quality['default']).lower()})."
                        if q_default is not None else ""))
    if not_given:
        notes.append(f"The handbook marks this part not normally used in {', '.join(not_given)}: no rate there.")
    key = f"a {section} {group['family']} {row}".strip()
    conditions = {"industry": "Military and aerospace electronics (handbook prediction)",
                  "section": f"{section} {group['title']}", "method": "Parts count (Appendix A)"}
    if package:
        conditions["package"] = package
    if group.get("specification"):
        conditions["specification"] = group["specification"]
    source_text = ", ".join(x for x in (group["family"], row) if x)
    rec = {
        "id": f"{SOURCE_ID}:{slug(key)}",
        "version": DATA_VERSION,
        "source": SOURCE_ID,
        "source_code": f"A {section} {source_text}",
        "name": name,
        "label": f"{name}: generic failure rate (parts count)",
        "equipment_type": group["equipment_type"],
        "kind": "rate",
        "basis": "prediction_model",
        "failure_mode": {"code": "ALL", "name": "Any failure",
                         "meaning": "The part stops doing its job, in any way: the handbook's rate covers every "
                                    "failure mode together."},
        "distribution": {"family": "point", "params": [{"name": "value", "value": per_hour}]},
        "summary": {"mean": per_hour, "median": None, "p05": None, "p95": None, "error_factor": None},
        "units": {"value": "per_hour", "time_basis": "operating", "as_given": "failures per million hours"},
        "evidence": {"failures": None, "demands": None, "exposure": None, "exposure_unit": None, "components": None,
                     "sites": None, "period": None, "data_source": "MIL-HDBK-217F parts count method (Appendix A)",
                     "method": "Handbook prediction model (generic failure rates by environment)"},
        "conditions": conditions,
        "prediction": {
            "method": "parts_count",
            "formula": "λ = λg πQ (failures per million hours; λg for the environment)",
            "per_million_hours": number(ref),
            "reference_environment": "GB",
            "applied": ["λg", "πQ"] if quality else ["λg"],
            "not_applied": held,
            "quality_factor_range": [min(q_values), max(q_values)] if quality else None,
            "quality_factor_default": q_default,
        },
        "generic_rates": {"symbol": "λg", "table": group["table"], "page": page, "document": DOCUMENTS[doc]["part"],
                          "values": values, "not_given": not_given},
        "source_text": source_text,
        "citation": {
            "title": TITLE, "publisher": PUBLISHER, "report": REPORT, "edition": SOURCE["edition"],
            "year": 1995 if doc == "N2" else 1991, "table": group["table"],
            "page": page + (f", {quality['page']}" if quality and quality["page"] != page else ""),
            "document": DOCUMENTS[doc]["part"], "url": ASSIST_URL, "retrieved": PC_RETRIEVED,
        },
        "licence": {k: SOURCE["licence"][k] for k in ("id", "name", "attribution")},
        "notes": notes,
    }
    if quality:
        rec["quality_factors"] = quality
    return rec


def records(retrieved: str) -> list[dict]:
    out, seen = [], set()
    for group in GROUPS:
        for i in range(len(group["parts"])):
            rec = record(group, i, retrieved)
            if rec["id"] in seen:
                raise ValueError(f"duplicate id {rec['id']}")
            seen.add(rec["id"])
            out.append(rec)
    for group in PARTS_COUNT:
        for i in range(len(group["rows"])):
            rec = parts_count_record(group, i, retrieved)
            if rec["id"] in seen:
                raise ValueError(f"duplicate id {rec['id']}")
            seen.add(rec["id"])
            out.append(rec)
    return out


# ---- checking the PDFs -----------------------------------------------------------------------

def without_stamp(streams: list[bytes]) -> list[bytes]:
    """A page's content streams less the ones ASSIST adds to stamp a download."""
    return [s for s in streams if not any(mark in s for mark in STAMP_MARKS)]


def content_sha256(pdf_path: str) -> str:
    """SHA-256 of every page's content streams (less the download stamp) and
    the images they draw, in page order."""
    from pdfminer.pdfdocument import PDFDocument  # noqa: PLC0415 - only this script needs it
    from pdfminer.pdfpage import PDFPage
    from pdfminer.pdfparser import PDFParser
    from pdfminer.pdftypes import PDFStream, resolve1

    h = hashlib.sha256()
    with open(pdf_path, "rb") as f:
        for i, page in enumerate(PDFPage.create_pages(PDFDocument(PDFParser(f)))):
            h.update(f"page {i + 1}\n".encode())
            contents = resolve1(page.attrs.get("Contents"))
            streams = contents if isinstance(contents, list) else [contents]
            for data in without_stamp([resolve1(s).get_data() for s in streams if s is not None]):
                h.update(data)
            xobjects = resolve1((resolve1(page.attrs.get("Resources")) or {}).get("XObject")) or {}
            for name in sorted(xobjects):
                x = resolve1(xobjects[name])
                if isinstance(x, PDFStream):
                    h.update(str(name).encode())
                    h.update(x.rawdata or b"")
    return h.hexdigest()


def numbers_in(text: str) -> set[float]:
    """Every number in a page's OCR text (a comma read as a decimal point)."""
    out = set()
    for tok in re.findall(r"\d*[.,]?\d+", text or ""):
        try:
            out.add(round(float(tok.replace(",", ".")), 9))
        except ValueError:
            continue
    return out


def ocr_problems(page_text: dict[tuple[str, int], str]) -> list[str]:
    """Each typed number missing from the OCR text of its page and not in
    :data:`OCR_MISREADS`. ``page_text``: (document, PDF page) -> text."""
    bad = []

    def check(doc: str, printed_page: str, pdf_page: int, printed: str) -> None:
        if round(number(printed), 9) in numbers_in(page_text.get((doc, pdf_page), "")):
            return
        if (doc, printed_page, printed) not in OCR_MISREADS:
            bad.append(f"{doc} p. {printed_page} (PDF page {pdf_page}): {printed} isn't in the page's text")

    for group in GROUPS:
        for i, part in enumerate(group["parts"]):
            check(*rate_page(group, i), part[3])
        if group["env_values"]:
            for value in group["env_values"]:
                if value is not NA:
                    check(group["env"][0], group["env"][1], group["env"][2], value)
    return bad


def _page_texts(folder: Path) -> dict[tuple[str, int], str]:
    try:
        import pdfplumber  # noqa: PLC0415 - only this script needs it
    except ImportError:  # pragma: no cover - a maintainer's tool
        sys.exit("This script needs pdfplumber: pip install pdfplumber==0.11.10")
    wanted: dict[str, set[int]] = {}
    for g in GROUPS:
        for key in ("rates", "rates_2", "env"):
            if g.get(key):
                wanted.setdefault(g[key][0], set()).add(g[key][2])
    out = {}
    for doc, pages in wanted.items():
        with pdfplumber.open(folder / DOCUMENTS[doc]["file"]) as pdf:
            for n in pages:
                out[(doc, n)] = pdf.pages[n - 1].extract_text() or ""
    return out


def build(folder: str, retrieved: str) -> dict:
    folder_p = Path(folder)
    for doc in DOCUMENTS.values():
        path = folder_p / doc["file"]
        if not path.exists():
            sys.exit(f"Missing {path}: download \"{doc['part']}\" of MIL-HDBK-217 from {ASSIST_URL} and save it "
                     f"as {doc['file']}.")
        digest = content_sha256(str(path))
        if digest != doc["content_sha256"]:
            sys.exit(f"{doc['file']}: content fingerprint {digest} isn't the reviewed copy's "
                     f"{doc['content_sha256']}. The handbook may have changed: review the new pages and the "
                     "typed tables before changing DOCUMENTS.")
    misread = ocr_problems(_page_texts(folder_p))
    if misread:
        sys.exit("Typed numbers not found on their pages (check each against the page image, then fix the "
                 "table or add it to OCR_MISREADS):\n" + "\n".join(misread))
    from backend.library import schema

    recs = records(retrieved)
    bad = [p for r in recs for p in schema.problems(r)]
    if bad:
        sys.exit("Records that can't ship:\n" + "\n".join(bad))
    return {
        "schema": schema.SCHEMA_VERSION,
        "data_version": DATA_VERSION,
        "source": {**SOURCE, "retrieved": retrieved,
                   "sha256": {d["file"]: d["content_sha256"] for d in DOCUMENTS.values()},
                   "documents": list(DOCUMENTS.values()),
                   "table": "The part stress models' base failure rate (λb) and environment factor (πE) tables, "
                            "sections 5.6, 6, 8.1 and 9 to 23, and Appendix A's parts-count generic failure rates "
                            "(λg) and quality factors (πQ) for microcircuits, laser diodes, rotating devices, "
                            "circuit boards, quartz crystals and incandescent lamps"},
        "skipped": [{"code": s, "page": None, "what": what, "reason": reason} for s, what, reason in SKIPPED],
        "records": recs,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("folder", help="The folder holding " + " and ".join(d["file"] for d in DOCUMENTS.values()))
    p.add_argument("--retrieved", required=True, help="The date you downloaded them, YYYY-MM-DD.")
    p.add_argument("--out", default=str(OUT))
    ns = p.parse_args(argv)
    data = build(ns.folder, ns.retrieved)
    Path(ns.out).parent.mkdir(parents=True, exist_ok=True)
    Path(ns.out).write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{len(data['records'])} records, {len(data['skipped'])} skipped -> {ns.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
