"""MongoDB connection and document helpers.

The app talks to MongoDB. When ``MONGODB_URI`` points at a reachable cluster
(e.g. MongoDB Atlas) we use it; otherwise — no URI configured, or the cluster
can't be reached within the timeout — we transparently fall back to an
in-memory MongoDB simulator (``mongomock``) so the app still runs locally with
zero external dependencies. The simulator is *not* persistent: its data is lost
when the process exits, and a clear warning is logged on startup.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Optional, Type, TypeVar

from backend import config

logger = logging.getLogger(__name__)

_db = None  # cached database handle (real Atlas or the simulator)
_simulated = False

T = TypeVar("T")


def _connect():
    """Connect to Atlas, or fall back to the in-memory simulator."""
    global _db, _simulated

    uri = config.MONGODB_URI
    if uri:
        try:
            import pymongo

            client = pymongo.MongoClient(
                uri,
                serverSelectionTimeoutMS=config.MONGODB_TIMEOUT_MS,
                appname="reliafy",
            )
            # Force server selection now so we fail fast and fall back.
            client.admin.command("ping")
            _db = client[config.MONGODB_DB]
            _simulated = False
            logger.info("Connected to MongoDB (database %r).", config.MONGODB_DB)
            return _db
        except Exception as exc:  # pragma: no cover - network dependent
            logger.warning(
                "Could not reach MongoDB at the configured URI (%s). Falling back "
                "to the in-memory simulator — data will NOT persist across "
                "restarts. Set MONGODB_URI to a reachable cluster to persist.",
                exc,
            )
    else:
        logger.warning(
            "No MONGODB_URI configured; using the in-memory MongoDB simulator. "
            "Data will NOT persist across restarts. Set MONGODB_URI (e.g. a "
            "MongoDB Atlas connection string) to persist."
        )

    import mongomock

    _db = mongomock.MongoClient()[config.MONGODB_DB]
    _simulated = True
    return _db


def get_db():
    """Return the (lazily-connected) MongoDB database handle."""
    if _db is None:
        _connect()
    return _db


def is_simulated() -> bool:
    """True when running against the in-memory simulator rather than Atlas."""
    get_db()
    return _simulated


def init_db() -> None:
    """Connect and ensure the indexes the queries rely on exist.

    Queries are scoped by ``owner_id`` (per-user isolation), so the indexes are
    compound with ``owner_id`` first.
    """
    db = get_db()
    db.datasets.create_index([("owner_id", 1), ("checksum", 1)])
    db.datasets.create_index([("owner_id", 1), ("created_at", -1)])
    db.models.create_index([("owner_id", 1), ("dataset_id", 1)])
    db.models.create_index([("owner_id", 1), ("created_at", -1)])
    db.rbds.create_index([("owner_id", 1), ("created_at", -1)])
    db.strategy_analyses.create_index([("owner_id", 1), ("created_at", -1)])
    db.rcm_studies.create_index([("owner_id", 1), ("created_at", -1)])
    db.degradation_models.create_index([("owner_id", 1), ("created_at", -1)])
    db.tracked_items.create_index([("owner_id", 1), ("model_id", 1)])
    db.tracked_items.create_index([("model_id", 1), ("created_at", -1)])


def get_session() -> Iterator:
    """FastAPI dependency. Yields the MongoDB database handle.

    Named ``get_session`` (and the value ``session`` in callers) for continuity
    with the previous SQL layer — the services treat it as the database.
    """
    yield get_db()


# ---- Pydantic-document mapping --------------------------------------------
# Documents use the model's ``id`` as the Mongo ``_id`` for fast, unique lookups.

def to_doc(obj) -> dict:
    """Serialise a pydantic model to a MongoDB document (``_id`` = ``id``)."""
    doc = obj.model_dump()
    doc["_id"] = doc["id"]
    return doc


def from_doc(cls: Type[T], doc: Optional[dict]) -> Optional[T]:
    """Rebuild a pydantic model from a MongoDB document, or None."""
    if doc is None:
        return None
    data = {k: v for k, v in doc.items() if k != "_id"}
    return cls(**data)
