"""Suite-wide test settings."""

import pytest


@pytest.fixture(autouse=True)
def _fast_sample_availability(monkeypatch):
    """Seeding precomputes the repairable sample's availability result
    (SAMPLE_AVAIL_SIMS Monte-Carlo runs, ~10 s in production). Many tests seed
    the samples; a handful of replications keeps them quick."""
    from backend.services import samples

    monkeypatch.setattr(samples, "SAMPLE_AVAIL_SIMS", 10)


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "real_seed: seed the samples for real, not from the suite's snapshot")
    config.addinivalue_line(
        "markers", "sqlite_only: tests the SQLite maintenance graph itself (skipped in the Neo4j parity run)")


# The samples, seeded once per test run: (collection, documents) pairs.
_SEED_SNAPSHOT: list | None = None

# Seeds the samples into an empty in-memory database, in a process of its
# own so no test's patches reach it, and pickles the documents to stdout.
_SEED_SCRIPT = """
import pickle, sys
from datetime import datetime, timezone
import mongomock
mongomock.utcnow = lambda: datetime.now(timezone.utc).replace(tzinfo=None)
from backend import config
from backend.services import samples
samples.SAMPLE_AVAIL_SIMS = 10
db = mongomock.MongoClient()[config.MONGODB_DB]
samples.seed_samples(db)
pickle.dump([(n, list(db[n].find())) for n in db.list_collection_names()], sys.stdout.buffer)
"""


def _sample_snapshot() -> list:
    global _SEED_SNAPSHOT
    if _SEED_SNAPSHOT is None:
        import pickle
        import subprocess
        import sys
        from pathlib import Path

        root = Path(__file__).resolve().parents[2]
        out = subprocess.run([sys.executable, "-c", _SEED_SCRIPT], cwd=root,
                             capture_output=True, check=True)
        _SEED_SNAPSHOT = pickle.loads(out.stdout)
    return _SEED_SNAPSHOT


@pytest.fixture(autouse=True)
def _seed_samples_once(monkeypatch, request):
    """Seeding fits every sample model (the imperfect-repair one runs a
    bootstrap goodness-of-fit test) and takes about 15 s; dozens of tests
    seed a fresh database, many through the app's startup. The samples are
    seeded once per run, in a clean process, and a seed into a database
    holding none of them copies those documents. A database that already
    holds any of them (a re-seed, an upgrade) is seeded for real, as is any
    test marked ``real_seed``."""
    if request.node.get_closest_marker("real_seed"):
        return
    import copy

    from backend import config as app_config
    from backend.services import samples

    real_seed = samples.seed_samples

    def seed_from_snapshot(db) -> None:
        if not app_config.SEED_SAMPLES:
            return
        snapshot = _sample_snapshot()
        if any(db[name].count_documents({"_id": {"$in": [d["_id"] for d in docs]}})
               for name, docs in snapshot if docs):
            return real_seed(db)
        for name, docs in snapshot:
            if docs:
                db[name].insert_many(copy.deepcopy(docs))

    monkeypatch.setattr(samples, "seed_samples", seed_from_snapshot)


@pytest.fixture(autouse=True)
def _fresh_exact_cache():
    """The exact availability figures are kept in a per-process cache; each
    test starts without another's."""
    from backend.services import rbds

    rbds.clear_exact_lru()
    yield
    rbds.clear_exact_lru()


@pytest.fixture(autouse=True)
def _no_background_usage_rollup(monkeypatch):
    """Usage logging rolls up finished days in a background thread at most
    every few minutes; tests call usage.rollup() themselves rather than race
    a thread over the in-memory database."""
    from backend.services import usage

    monkeypatch.setattr(usage, "_next_rollup", float("inf"))


@pytest.fixture(autouse=True)
def _mongomock_utcnow_without_deprecation(monkeypatch):
    """The in-memory database expires TTL-indexed documents by
    ``datetime.utcnow()``, deprecated since Python 3.12, so a run with
    ``-W error::DeprecationWarning`` fails inside it. The same naive UTC time,
    as mongomock's docs suggest patching it."""
    from datetime import datetime, timezone

    import mongomock

    monkeypatch.setattr(mongomock, "utcnow", lambda: datetime.now(timezone.utc).replace(tzinfo=None))


@pytest.fixture(autouse=True)
def _fresh_email_verification_cache():
    """Email-verification lookups are cached per process; each test starts
    without another's answers."""
    from backend.services import email_trust

    email_trust.clear_cache()
    yield
    email_trust.clear_cache()


@pytest.fixture(autouse=True)
def _mcp_switch_fresh(monkeypatch):
    """The MCP switch's per-process cache starts empty in every test (each has
    its own database), and no MCP_ENABLED from the environment leaks in."""
    from backend import config as app_config
    from backend.services import mcp_switch

    monkeypatch.setattr(app_config, "MCP_ENABLED", None)
    mcp_switch.clear_cache()
    yield
    mcp_switch.clear_cache()


@pytest.fixture()
def mcp_on(monkeypatch):
    """MCP switched on, for tests of what it does once on (on the cloud,
    with billing enabled, it is off by default)."""
    from backend import config as app_config

    monkeypatch.setattr(app_config, "MCP_ENABLED", True)


@pytest.fixture(autouse=True)
def _maintenance_graph_backend(request, monkeypatch):
    """MAINTENANCE_TEST_GRAPH=neo4j (with NEO4J_TEST_URI): the maintenance test
    modules make their graphs in Neo4j instead of SQLite (backend/tests/
    neo4j_support.py). Tests of SQLite's own workings are marked sqlite_only."""
    import os

    if os.environ.get("MAINTENANCE_TEST_GRAPH") != "neo4j" or not hasattr(request.module, "GraphStore"):
        yield
        return
    if request.node.get_closest_marker("sqlite_only"):
        pytest.skip("tests the SQLite graph itself")
    from backend.tests import neo4j_support

    if not neo4j_support.configured():
        pytest.skip("NEO4J_TEST_URI isn't set")
    created: set = set()
    monkeypatch.setattr(request.module, "GraphStore", neo4j_support.store_factory(created))
    yield
    neo4j_support.drop(created)
