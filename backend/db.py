"""MongoDB connection and document helpers.

The app talks to MongoDB. When ``MONGODB_URI`` points at a cluster (e.g.
MongoDB Atlas) we use it — and a connection failure is fatal, because
silently serving an empty in-memory database would look like data loss to
users. With no URI configured (zero-config local dev), we fall back to an
in-memory MongoDB simulator (``mongomock``). The simulator is *not*
persistent: its data is lost when the process exits, and a clear warning is
logged on startup.
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
    """Connect to the configured cluster, or (no URI) the in-memory simulator.

    When MONGODB_URI is set, a connection failure raises: crashing lets the
    platform (Cloud Run, docker) retry or keep routing to healthy instances,
    instead of an instance quietly serving an empty database whose "saved"
    data vanishes at the next restart.
    """
    global _db, _simulated

    uri = config.MONGODB_URI
    if uri:
        import pymongo

        try:
            client = pymongo.MongoClient(
                uri,
                serverSelectionTimeoutMS=config.MONGODB_TIMEOUT_MS,
                appname="reliafy",
            )
            # Force server selection now so we fail fast.
            client.admin.command("ping")
        except Exception as exc:  # pragma: no cover - network dependent
            logger.error(
                "Could not reach MongoDB at the configured URI (%s). Refusing to "
                "fall back to the in-memory simulator while MONGODB_URI is set — "
                "that would silently serve an empty database.",
                exc,
            )
            raise RuntimeError("MongoDB is configured (MONGODB_URI) but unreachable.") from exc
        _db = client[config.MONGODB_DB]
        _simulated = False
        logger.info("Connected to MongoDB (database %r).", config.MONGODB_DB)
        return _db
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
    db.fleets.create_index([("owner_id", 1), ("created_at", -1)])
    db.tracked_fleets.create_index([("owner_id", 1), ("created_at", -1)])
    db.tracked_items.create_index([("fleet_id", 1)])
    db.teams.create_index([("members.uid", 1)])
    db.teams.create_index([("invites.email", 1)])
    db.users.create_index([("email_lc", 1)])
    db.shares.create_index([("recipient_uid", 1), ("collection", 1)])
    db.shares.create_index([("artifact_id", 1)])
    db.shares.create_index([("artifact_id", 1), ("recipient_uid", 1)], unique=True)
    # First-party analytics: traffic queries scan by recency; the TTL index
    # enforces the 90-day retention promise (Mongo drops old events itself).
    db.metrics_events.create_index(
        [("created_at", 1)], expireAfterSeconds=90 * 24 * 3600
    )
    db.public_links.create_index([("collection", 1), ("artifact_id", 1)])
    db.public_links.create_index([("grantor_uid", 1)])


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
