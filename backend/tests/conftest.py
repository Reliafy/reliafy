"""Suite-wide test settings."""

import pytest


@pytest.fixture(autouse=True)
def _fast_sample_availability(monkeypatch):
    """Seeding precomputes the repairable sample's availability result
    (SAMPLE_AVAIL_SIMS Monte-Carlo runs, ~10 s in production). Many tests seed
    the samples; a handful of replications keeps them quick."""
    from backend.services import samples

    monkeypatch.setattr(samples, "SAMPLE_AVAIL_SIMS", 10)
