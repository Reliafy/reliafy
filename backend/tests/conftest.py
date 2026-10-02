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
def _no_background_usage_rollup(monkeypatch):
    """Usage logging rolls up finished days in a background thread at most
    every few minutes; tests call usage.rollup() themselves rather than race
    a thread over the in-memory database."""
    from backend.services import usage

    monkeypatch.setattr(usage, "_next_rollup", float("inf"))
