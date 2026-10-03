"""Shared shapes for RBD importers.

Every format module (``blocksim``, ``openpsa``, ``galileo``) exposes::

    sniff(data: bytes, filename: str) -> bool
    parse(data: bytes, filename: str) -> list[ImportedDiagram]

``parse`` returns one :class:`ImportedDiagram` per diagram in the file. Its
``graph`` is a *compact* graph — the shape :func:`backend.services.rbd_graph.normalize_graph`
accepts (the same one the assistant and the MCP server write): nodes with ids
``"input"`` and ``"output"`` plus ``component`` / ``knode`` / ``standby`` /
``series`` / ``parallel`` nodes, inline ``{distribution_id, params}`` models,
and optional ``repairable`` and ``ccf_groups``. Anything the source file holds
that Reliafy can't represent goes in ``warnings`` (imported approximately) or
makes the importer raise :class:`RbdImportError` (can't be imported honestly).
A format that states no time unit leaves the graph's ``unit`` blank;
:func:`backend.services.rbd_import.import_file` then defaults it to Hours.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Uploads are untrusted: cap the raw file and anything we decompress from it.
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_DECOMPRESSED_BYTES = 200 * 1024 * 1024


class RbdImportError(ValueError):
    """A file that can't be imported (user-facing text)."""


@dataclass
class ImportedDiagram:
    name: str
    graph: dict
    warnings: list[str] = field(default_factory=list)
    source_format: str = ""
    # The file states several time units that disagree, so the diagram's unit
    # is left blank (with a warning) rather than defaulted (see ``import_file``).
    unit_conflict: bool = False
