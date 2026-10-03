"""Import reliability block diagrams from other tools' files.

Supported: ReliaSoft BlockSim project databases (``.rsgzNN`` / ``.rsrNN`` /
``.rsrp``), Open-PSA Model Exchange Format XML, Galileo dynamic-fault-tree
text (``.dft``) and Excel workbooks of blocks + connections (``.xlsx``, see
:mod:`.excel`). :func:`import_file` picks the format by content, then filename.
"""

from __future__ import annotations

import importlib
from typing import Optional

from .types import MAX_UPLOAD_BYTES, ImportedDiagram, RbdImportError

__all__ = ["FORMATS", "ImportedDiagram", "RbdImportError", "import_file"]

# module name -> human label, in sniffing order (binary formats first).
FORMATS = {
    "excel": "Excel workbook",
    "blocksim": "ReliaSoft BlockSim",
    "openpsa": "Open-PSA MEF",
    "galileo": "Galileo DFT",
}


def _module(name: str):
    return importlib.import_module(f"{__name__}.{name}")


def import_file(data: bytes, filename: str, excel_mapping: Optional[dict] = None,
                format: Optional[str] = None, unit: Optional[str] = None) -> list[ImportedDiagram]:
    """Parse an uploaded file into one or more diagrams.

    ``excel_mapping`` (Excel workbooks only) says which sheets and columns
    hold the blocks and connections when the workbook doesn't follow the
    template (see :func:`.excel.parse`). ``format`` (a :data:`FORMATS` key)
    skips the sniffing and parses the file as that format. ``unit`` is the
    time unit the file's rates and times are in, for a file that doesn't say;
    without it such a diagram's unit defaults to Hours (see :func:`_set_unit`)."""
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
                _set_unit(d, unit)
            if not diagrams:
                raise RbdImportError(f"No reliability block diagrams found in this {label} file.")
            return diagrams
    raise RbdImportError(
        "Unrecognised file. Reliafy imports ReliaSoft BlockSim projects (.rsgz / .rsr — "
        "use File › Pack and E-mail in BlockSim), Open-PSA XML, Galileo .dft files and "
        "Excel workbooks (.xlsx — download the template)."
    )


DEFAULT_UNIT = "Hours"


def _same_unit(a: str, b: str) -> bool:
    return a.strip().lower().rstrip("s") == b.strip().lower().rstrip("s")


def _set_unit(d: ImportedDiagram, unit: Optional[str]) -> None:
    """Give a diagram whose file states no time unit the ``unit`` asked for,
    else Hours (the usual convention for failure rates, and the rest of
    Reliafy's default), saying so in an import note. A unit the file states
    wins over ``unit``."""
    unit = (unit or "").strip()[:40]
    stated = str(d.graph.get("unit") or "").strip()
    if stated:
        if unit and not _same_unit(unit, stated):
            d.warnings.append(f"The file gives its time unit as “{stated}”, so the unit given on import "
                              f"(“{unit}”) was ignored.")
        return
    if unit:
        d.graph["unit"] = unit
        d.warnings.append(f"Rates and times were read in “{unit}”, the unit given on import.")
    elif not d.unit_conflict:
        d.graph["unit"] = DEFAULT_UNIT
        d.warnings.append(
            f"The {d.source_format} file doesn't state a time unit, so the diagram's unit was set to "
            f"{DEFAULT_UNIT}: its rates were read per hour and its times in hours. If they're in "
            "another unit, change the diagram's unit.")
