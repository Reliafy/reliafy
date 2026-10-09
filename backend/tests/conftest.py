"""Suite-wide test settings."""

import pytest


@pytest.fixture(autouse=True)
def _fast_sample_availability(monkeypatch):
    """Seeding precomputes the repairable sample's availability result
    (SAMPLE_AVAIL_SIMS Monte-Carlo runs, ~10 s in production). Many tests seed
    the samples; a handful of replications keeps them quick."""
    from backend.services import samples

    monkeypatch.setattr(samples, "SAMPLE_AVAIL_SIMS", 10)


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
