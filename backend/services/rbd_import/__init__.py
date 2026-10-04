"""Import reliability block diagrams from other tools' files.

Supported: ReliaSoft BlockSim project databases (``.rsgzNN`` / ``.rsrNN`` /
``.rsrp``), Open-PSA Model Exchange Format XML, Galileo dynamic-fault-tree
text (``.dft``), Excel workbooks of blocks + connections (``.xlsx``, see
:mod:`.excel`) and RePyability's JSON (``RBD.to_json()``, and Reliafy's own
"Download as RePyability JSON", see :mod:`.repyability`). :func:`import_file`
picks the format by content, then filename.
"""

from __future__ import annotations

import importlib
from typing import Optional

from .types import MAX_UPLOAD_BYTES, ImportedDiagram, RbdImportError

__all__ = ["FORMATS", "ImportedDiagram", "RbdImportError", "UNIT_MISSING", "apply_time_unit", "import_file",
           "link_references"]

# module name -> human label, in sniffing order (binary formats first).
FORMATS = {
    "excel": "Excel workbook",
    "blocksim": "ReliaSoft BlockSim",
    "repyability": "RePyability JSON",
    "openpsa": "Open-PSA MEF",
    "galileo": "Galileo DFT",
}


#: The import note for a diagram whose file states no time unit (#187).
UNIT_MISSING = (
    "The file doesn't state a time unit, so the diagram's unit is blank. Its failure rates and times "
    "are per whatever unit the source model used (Galileo and Open-PSA rates are usually per hour): "
    "set the diagram's unit to match before reading any results."
)


def apply_time_unit(diagrams: list[ImportedDiagram], time_unit: Optional[str] = None) -> None:
    """Settle each diagram's time unit (#187): the unit the file states wins;
    otherwise ``time_unit`` (the caller's word for what the rates are per);
    otherwise the unit stays blank and :data:`UNIT_MISSING` leads the import
    notes. The parameters are never rescaled."""
    given = (time_unit or "").strip()
    for d in diagrams:
        stated = str(d.graph.get("unit") or "").strip()
        if stated:
            if given and given.lower() != stated.lower():
                d.warnings.insert(0, (
                    f"The file states its time unit ({stated}), so the diagram uses it; time_unit "
                    f"“{given}” was ignored — the parameters are in the file's unit."))
        elif given:
            d.graph["unit"] = given
            d.warnings.insert(0, (
                f"The file doesn't state a time unit; its rates and times were read as per {given}, "
                "as given."))
        else:
            d.warnings.insert(0, UNIT_MISSING)


def _module(name: str):
    return importlib.import_module(f"{__name__}.{name}")


def import_file(data: bytes, filename: str, excel_mapping: Optional[dict] = None,
                format: Optional[str] = None, time_unit: Optional[str] = None) -> list[ImportedDiagram]:
    """Parse an uploaded file into one or more diagrams.

    ``excel_mapping`` (Excel workbooks only) says which sheets and columns
    hold the blocks and connections when the workbook doesn't follow the
    template (see :func:`.excel.parse`). ``format`` (a :data:`FORMATS` key)
    skips the sniffing and parses the file as that format. ``time_unit`` is
    the diagrams' unit when the file states none (see :func:`apply_time_unit`)."""
    if not data:
        raise RbdImportError("The file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise RbdImportError(
            f"The file is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB — "
            "export just the project that holds the diagram."
        )
    if format and format not in FORMATS:
        raise RbdImportError(f"Unknown format “{format}” — use one of {', '.join(FORMATS)}.")
    for name, label in FORMATS.items():
        if format and name != format:
            continue
        mod = _module(name)
        if format or mod.sniff(data, filename or ""):
            if name == "excel":
                diagrams = mod.parse(data, filename or "", excel_mapping)
            else:
                diagrams = mod.parse(data, filename or "")
            for d in diagrams:
                d.source_format = d.source_format or label
            if not diagrams:
                raise RbdImportError(f"No reliability block diagrams found in this {label} file.")
            apply_time_unit(diagrams, time_unit)
            return diagrams
    raise RbdImportError(
        "Unrecognised file. Reliafy imports ReliaSoft BlockSim projects (.rsgz / .rsr — "
        "use File › Pack and E-mail in BlockSim), Open-PSA XML, Galileo .dft files, "
        "RePyability JSON and Excel workbooks (.xlsx — download the template)."
    )


def link_references(diagrams: list[ImportedDiagram], saved_model=None, saved_rbd=None) -> None:
    """Restore the links an imported diagram may carry to the user's saved
    models and sub-system diagrams (RePyability JSON written by Reliafy).

    ``saved_model`` / ``saved_rbd`` map an id to the saved model / diagram the
    importing user can open (None otherwise). Without this call a diagram
    keeps no links: each block keeps its own parameters and each sub-system
    is drawn in place, so the graph is valid for anyone."""
    for d in diagrams:
        if d.links is not None:
            d.links(saved_model, saved_rbd)
