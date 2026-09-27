"""Import reliability block diagrams from other tools' files.

Supported: ReliaSoft BlockSim project databases (``.rsgzNN`` / ``.rsrNN`` /
``.rsrp``), Open-PSA Model Exchange Format XML, and Galileo dynamic-fault-tree
text (``.dft``). :func:`import_file` picks the format by content, then filename.
"""

from __future__ import annotations

import importlib

from .types import MAX_UPLOAD_BYTES, ImportedDiagram, RbdImportError

__all__ = ["FORMATS", "ImportedDiagram", "RbdImportError", "import_file"]

# module name -> human label, in sniffing order (binary formats first).
FORMATS = {
    "blocksim": "ReliaSoft BlockSim",
    "openpsa": "Open-PSA MEF",
    "galileo": "Galileo DFT",
}


def _module(name: str):
    return importlib.import_module(f"{__name__}.{name}")


def import_file(data: bytes, filename: str) -> list[ImportedDiagram]:
    """Parse an uploaded file into one or more diagrams."""
    if not data:
        raise RbdImportError("The file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise RbdImportError(
            f"The file is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB — "
            "export just the project that holds the diagram."
        )
    for name, label in FORMATS.items():
        mod = _module(name)
        if mod.sniff(data, filename or ""):
            diagrams = mod.parse(data, filename or "")
            for d in diagrams:
                d.source_format = d.source_format or label
            if not diagrams:
                raise RbdImportError(f"No reliability block diagrams found in this {label} file.")
            return diagrams
    raise RbdImportError(
        "Unrecognised file. Reliafy imports ReliaSoft BlockSim projects (.rsgz / .rsr — "
        "use File › Pack and E-mail in BlockSim), Open-PSA XML and Galileo .dft files."
    )
