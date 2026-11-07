"""The intended ("designed") shape of the maintenance graph, for the Data model page.

The live graph says what has been built (``graph_cypher.graph_schema``). A
design document says what is meant to be there: the kinds of node and the
relationships between them, each relationship decided or still proposed. The
Data model page draws the two over each other so the gaps show.

The document is not part of the code: it is one document in ``app_settings``,
written by the owner's own tooling, and read here for people with graph access
only. Nothing in the app writes it. Its shape::

    {_id: "data_model",
     nodes: [{id, label, structure?, definition?}],
     edges: [{from, type, to, status: "decided" | "proposed", note?}],
     updated?}                      # an ISO date-time (string or date)

- ``id`` is the node's key in this document; ``from`` and ``to`` name ids.
- ``label`` is the graph label it stands for (the live schema's label), which
  is how the page matches a designed node to a built one.
- ``structure`` is a short grouping word shown with the node; ``definition`` a
  sentence or two saying what it is. ``note`` says why an edge is there.

Everything is plain text: control characters are dropped and nothing is ever
rendered as HTML. Sizes are capped so a bad document can't swamp the page.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

logger = logging.getLogger(__name__)

SETTINGS_ID = "data_model"
MAX_NODES = 200
MAX_EDGES = 1000

_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _plain(value: str | None) -> str | None:
    """Plain text: no control characters (tabs and new lines kept), trimmed."""
    if value is None:
        return None
    return _CONTROL.sub("", value).strip()


class DesignNode(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=64)
    structure: str | None = Field(default=None, max_length=80)
    definition: str | None = Field(default=None, max_length=1000)

    @field_validator("id", "label")
    @classmethod
    def _key(cls, v: str) -> str:
        if not _KEY.match(v):
            raise ValueError("use letters, digits and underscores, starting with a letter")
        return v

    @field_validator("structure", "definition")
    @classmethod
    def _text(cls, v: str | None) -> str | None:
        return _plain(v) or None


class DesignEdge(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    from_: str = Field(alias="from", min_length=1, max_length=64)
    type: str = Field(min_length=1, max_length=64)
    to: str = Field(min_length=1, max_length=64)
    status: Literal["decided", "proposed"] = "decided"
    note: str | None = Field(default=None, max_length=1000)

    @field_validator("type")
    @classmethod
    def _key(cls, v: str) -> str:
        if not _KEY.match(v):
            raise ValueError("use letters, digits and underscores, starting with a letter")
        return v

    @field_validator("note")
    @classmethod
    def _text(cls, v: str | None) -> str | None:
        return _plain(v) or None


class DataModelDesign(BaseModel):
    """The design document as stored (``_id`` and any other extra keys ignored)."""

    model_config = ConfigDict(extra="ignore")

    nodes: list[DesignNode] = Field(max_length=MAX_NODES)
    edges: list[DesignEdge] = Field(default_factory=list, max_length=MAX_EDGES)
    updated: datetime | str | None = None

    @field_validator("updated")
    @classmethod
    def _updated(cls, v: datetime | str | None) -> str | None:
        if v is None:
            return None
        if isinstance(v, datetime):
            return v.isoformat()
        text = _plain(v) or ""
        if len(text) > 40:
            raise ValueError("too long for a date")
        return text or None

    @model_validator(mode="after")
    def _references(self) -> "DataModelDesign":
        ids = [n.id for n in self.nodes]
        dup = sorted({i for i in ids if ids.count(i) > 1})
        if dup:
            raise ValueError(f"node ids used twice: {', '.join(dup[:5])}")
        known = set(ids)
        for e in self.edges:
            for end in (e.from_, e.to):
                if end not in known:
                    raise ValueError(f"edge {e.from_} {e.type} {e.to} names a node that isn't listed: {end}")
        return self

    def public(self) -> dict:
        return {"available": True,
                "nodes": [n.model_dump() for n in self.nodes],
                "edges": [e.model_dump(by_alias=True) for e in self.edges],
                "updated": self.updated}


def load(db) -> dict:
    """The stored design, checked, as the page draws it; or ``{available: false,
    reason}`` when there is none or it doesn't pass the checks (the reason says
    which, in plain words, without echoing the document)."""
    doc = db.app_settings.find_one({"_id": SETTINGS_ID})
    if not doc:
        return {"available": False, "reason": "No design has been stored yet."}
    try:
        return DataModelDesign.model_validate(doc).public()
    except ValidationError as err:
        logger.warning("data_model design document fails its checks: %d problem(s)", err.error_count())
        first = err.errors()[0]
        where = ".".join(str(p) for p in first.get("loc", ()))
        return {"available": False,
                "reason": f"The stored design doesn't pass its checks ({where or 'document'}: {first.get('msg')})."}
