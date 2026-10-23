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
                    "(πE) for its 14 use environments, from ground, benign to cannon, launch."),
    "caveats": [
        "A handbook prediction model, not failures counted in service: never mix it with field data.",
        "Reliafy uses the base failure rate × the environment factor only. The handbook's other factors "
        "(temperature, electrical stress, quality and more) aren't applied: each record names them, and "
        "real rates depend on them. Quality alone can move a rate by a factor of 10 or more.",
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
}

#: What isn't imported, and why. Each a (section, what, reason).
SKIPPED: list[tuple[str, str, str]] = [
    ("5.1-5.13", "Microcircuits (gate arrays, memories, VHSIC, GaAs, hybrids, SAW, bubble memories)",
     "The model adds a die term and a package term (C1 πT + C2 πE), each from the device's complexity and "
     "package: there is no one base failure rate per part type."),
    ("6.1", "Diodes, low frequency: power rectifier with high voltage stacks",
     "The base rate is per junction (.0050 per junction): it needs the number of junctions."),
    ("6.6-6.9", "Transistors, high frequency (low noise bipolar, high power bipolar, GaAs FET, Si FET)",
     "The base rate is a formula of frequency and output power (or a table of them), not one number per type."),
    ("6.12", "Optoelectronics, alphanumeric displays",
     "The base rate is a formula of the number of characters and whether a logic chip is included."),
    ("6.13", "Optoelectronics, laser diodes",
     "The base rate depends on the material and on optical power and current."),
    ("7.1-7.3", "Tubes (including travelling wave tubes and magnetrons)",
     "Not imported in this release: the base rates depend on tube type, power and frequency, and few designs "
     "use tubes now."),
    ("8.1-8.4", "Lasers", "The base rates depend on the laser's construction, power and pumping."),
    ("12.1", "Rotating devices, motors",
     "A life model for bearings and windings (characteristic lives by temperature), with no environment "
     "factor: not a constant base rate."),
    ("12.2", "Rotating devices, synchros and resolvers",
     "The base rate is a formula of the frame temperature."),
    ("13.1", "Relays, mechanical",
     "The base rate depends on the ambient temperature (.0059 at 25 °C to .031 at 125 °C for a 125 °C rated "
     "relay): no one number per type."),
    ("16.1", "Interconnection assemblies with plated through holes",
     "The base rate is per plated through hole, weighted by the number of circuit planes: it needs the board's "
     "hole counts."),
    ("16.2", "Interconnection assemblies, surface mount technology",
     "A wear-out model in thermal cycles, not a constant base rate."),
    ("19.1", "Quartz crystals", "The base rate is a formula of frequency (.013 f^0.23)."),
    ("20.1", "Lamps, incandescent", "The base rate is a formula of rated voltage (.074 Vr^1.29)."),
    ("23.1", "Fiber optic cables", "The rate is per kilometre of fibre, a unit the library doesn't convert."),
    ("23.1", "Microwave attenuators", "The handbook refers these to the resistor model (style RD)."),
    ("23.1", "Microwave fixed elements (directional couplers, fixed stubs and cavities)",
     "The handbook gives their rate as negligible, not a number."),
    ("23.1", "Terminations (thin or thick film loads in stripline and thin film circuits)",
     "Given as 0.030 × πE without saying which environment table applies."),
    ("Appendix A", "Parts count method (generic failure rates by environment)",
     "A different method, for early estimates: not imported in this release."),
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
            "url": ASSIST_URL, "retrieved": retrieved,
        },
        "licence": {k: SOURCE["licence"][k] for k in ("id", "name", "attribution")},
        "notes": notes,
    }
    if env is None:
        del rec["environment_factors"]
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
                            "sections 6 and 9 to 23"},
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
