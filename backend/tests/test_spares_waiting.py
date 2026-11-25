"""A unit waiting for a spare can't fail again (25 Nov 2026, as RePyability#546 did for its long-run
stock): the rotable pool's pipeline and the shortfall at a stock take that in. Each figure is checked
against a chain solved here independently (the machine-repairman birth-death chain for a pool, the
pure-birth chain for a window's shortfall), to 1e-9, and the old figures are named where they move."""

import math

import numpy as np
import pytest
import surpyval
from scipy.linalg import expm
from scipy.stats import poisson

from backend.services import fleet as fleet_service
from backend.services import spares


def _pool_chain(n: int, a: float, stock: int) -> np.ndarray:
    """The machine-repairman chain's long-run distribution of the number away (in repair), solved
    from its generator: ``n`` units each failing at rate ``a`` (per turnaround) while running, one
    repair per unit away at rate 1 (the turnaround as the time unit), ``stock`` in the pool. With
    ``k`` away, ``max(0, k - stock)`` units wait and can't fail."""
    size = stock + n + 1
    q = np.zeros((size, size))
    for k in range(size):
        up = n - max(0, k - stock)
        if k + 1 < size:
            q[k, k + 1] = a * up
        if k > 0:
            q[k, k - 1] = k
        q[k, k] = -q[k].sum()
    lhs = np.vstack([q.T, np.ones(size)])
    rhs = np.zeros(size + 1)
    rhs[-1] = 1.0
    return np.linalg.lstsq(lhs, rhs, rcond=None)[0]


def _window_chain_short(n: int, u: float, stock: float, per: float = 1.0) -> float:
    """The shortfall at ``stock`` after ``u`` of each unit's hazard, from the pure-birth chain: ``k``
    failures so far, the stock covering ``m`` jobs, ``max(0, k - m)`` units down and not failing."""
    m = math.floor(stock / per + 1e-9)
    size = m + n + 1
    q = np.zeros((size, size))
    for k in range(size - 1):
        q[k, k + 1] = n - max(0, k - m)
        q[k, k] = -q[k, k + 1]
    p = expm(q * u)[0]
    left = stock - m * per
    return float(sum(p[k] * max(0.0, (k - m) * per - left) for k in range(m + 1, size)))


@pytest.mark.parametrize("a, fill", [(0.3, 1 / 1.3), (3.0, 0.25)])
def test_one_spare_one_unit_meets_one_over_one_plus_lambda_l(a, fill):
    # The old figure was e^-a: 0.7408 at 0.3, 0.0498 at 3.
    d = spares.Demand.from_pmf(spares.poisson_pmf(a)).with_waiting(spares.Waiting(1, exact=True))
    held = d.pooled(1)
    assert held.probs[:3] == pytest.approx(_pool_chain(1, a, 1), abs=1e-9)
    # A demand finds k away as often as a random time does, weighed by the units still running.
    running = np.array([1.0, 1.0, 0.0])
    at_demand = held.probs[:3] * running / (held.probs[:3] * running).sum()
    assert at_demand[0] == pytest.approx(fill, abs=1e-12)
    assert at_demand[0] != pytest.approx(math.exp(-a), abs=1e-3)


@pytest.mark.parametrize("n", [1, 2, 3])
@pytest.mark.parametrize("a", [0.3, 1.0, 3.0])
def test_a_small_fleets_pool_is_the_birth_death_chain(n, a):
    d = spares.Demand.from_pmf(spares.poisson_pmf(n * a)).with_waiting(spares.Waiting(n, exact=True))
    for stock in range(6):
        chain = _pool_chain(n, a, stock)
        held = d.pooled(stock)
        got = np.pad(held.probs, (0, max(0, chain.size - held.probs.size)))[:chain.size]
        assert got == pytest.approx(chain, abs=1e-9)
        assert held.probs[chain.size:].sum() == pytest.approx(0.0, abs=1e-12)
        assert d.pool_risk(stock) == pytest.approx(chain[stock + 1:].sum(), abs=1e-9)
        assert d.pool_short(stock) == pytest.approx(sum((k - stock) * chain[k] for k in range(stock + 1, chain.size)),
                                                    abs=1e-9)
        # Never more risk than the demand going on while units wait.
        assert d.pool_risk(stock) <= d.prob_short(stock) + 1e-12


@pytest.mark.parametrize("n", [1, 2, 3])
@pytest.mark.parametrize("u", [0.1, 0.6, 3.0])
def test_a_windows_shortfall_is_the_pure_birth_chain(n, u):
    for stock in range(5):
        assert spares.poisson_short(n * u, n, stock) == pytest.approx(_window_chain_short(n, u, stock), abs=1e-9)
    # Two parts a job, three in stock: the third part covers no whole job.
    assert spares.poisson_short(n * u, n, 3, per=2) == pytest.approx(_window_chain_short(n, u, 3, per=2), abs=1e-9)
    # One unit, one spare, u = 3: short P(N >= 2) = 1 - 4e^-3 = 0.8009 (it was E[(N - 1)+] = 2.0498).
    assert spares.poisson_short(3.0, 1, 1) == pytest.approx(1 - 4 * math.exp(-3), abs=1e-12)


def test_runs_short_drops_a_down_units_later_failures():
    # One run, two units, stock 1: unit 0 fails at t1 (covered), at t2 (short, down), at t3 (never
    # happens: it's waiting); unit 1 fails at t4 (short). Old count: 3 short; now 2.
    sim = np.zeros(4, dtype=int)
    unit = np.array([0, 0, 0, 1])
    assert spares.runs_short(sim, unit, 1.0, 1, 1) == 2.0
    assert spares.Demand.from_samples([4]).expected_short(1) == 3.0
    # A planned job left undone is short, but its unit keeps running.
    assert spares.runs_short(sim, unit, 1.0, 1, 1, fails=[True, False, True, True]) == 3.0
    # Two parts a job and three in stock: the second job is one part short.
    assert spares.runs_short(sim[:2], unit[:2], 2.0, 1, 3) == 1.0
    assert spares.runs_short(np.zeros(0), np.zeros(0), 1.0, 10, 0) == 0.0


def test_runs_short_matches_the_closed_form():
    rng = np.random.default_rng(7)
    n, u, sims = 3, 0.6, 100_000
    counts = rng.poisson(u, (sims, n))
    sim = np.concatenate([np.repeat(np.arange(sims), counts[:, i]) for i in range(n)])
    unit = np.concatenate([np.full(counts[:, i].sum(), i) for i in range(n)])
    order = np.argsort(rng.uniform(size=sim.size))
    for stock in (0, 1, 2):
        got = spares.runs_short(sim[order], unit[order], 1.0, sims, stock)
        assert got == pytest.approx(spares.poisson_short(n * u, n, stock), abs=0.01)


def _hpp(rate=0.02):
    class Hpp:
        def cif(self, x):
            return rate * np.asarray(x, dtype=float)

    return Hpp()


def test_a_repairable_fleets_pool_and_shortfall():
    ages, rates = np.array([100.0, 300]), np.array([50.0, 50])
    pool = fleet_service.spares_answer({"repairable": True, "turnaround": 1, "stock": 3}, "repairable", _hpp(), ages,
                                       rates, 4, "months")
    chain = _pool_chain(2, 1.0, 3)
    assert pool["risk_at_stock"] == pytest.approx(chain[4:].sum(), abs=1e-9)  # 0.1121; it was P(N > 3) = 0.1429
    assert pool["expected_short"] == pytest.approx(chain[4] + 2 * chain[5], abs=1e-9)
    assert pool["hold"] == 4 and {p["hold"] for p in pool["per_period"]} == {4.0}
    assert pool["waiting"]["exact"] and dict(pool["risk_curve"])[3.0] == pytest.approx(pool["risk_at_stock"], abs=1e-6)
    # Bought, not pooled: the stock-out chance and hold don't move; the shortfall does.
    out = fleet_service.spares_answer({"lead_time": 2, "stock": 1}, "repairable", _hpp(), ages, rates, 4, "months")
    assert out["hold"] == poisson.ppf(0.95, 4) and out["risk_at_stock"] == pytest.approx(poisson.sf(1, 4))
    assert out["expected_short"] == pytest.approx(_window_chain_short(2, 2.0, 1), abs=1e-9)
    assert out["expected_short"] < sum((k - 1) * poisson.pmf(k, 4) for k in range(2, 60))
    assert out["waiting"] == {"units": 2, "exact": True, "note": spares.WAITING_EXACT}


def test_units_that_differ_are_approximate_and_said():
    # Different use rates: the units aren't alike, so the reweighting is an approximation.
    pool = fleet_service.spares_answer({"repairable": True, "turnaround": 1}, "repairable", _hpp(),
                                       np.array([100.0, 300]), np.array([20.0, 80]), 4, "months")
    assert pool["waiting"] == {"units": 2, "exact": False, "note": spares.WAITING_APPROX}
    # A wear-out life's pool, renewals simulated: approximate too.
    weib = fleet_service.spares_answer({"repairable": True, "turnaround": 1}, "renewals",
                                       surpyval.Weibull.from_params([100.0, 3.0]), np.array([10.0, 50, 80]),
                                       np.full(3, 30.0), 3, "months")
    assert weib["waiting"]["exact"] is False and weib["waiting"]["units"] == 3


def test_a_renewals_fleets_shortfall_is_counted_run_by_run():
    # Four items on one constant rate (Poisson 2.4 over the lead time), one in stock.
    ages, rates = np.array([10.0, 50, 80, 200]), np.full(4, 30.0)
    exp = surpyval.Exponential.from_params([0.01])
    out = fleet_service.spares_answer({"lead_time": 2, "stock": 1}, "renewals", exp, ages, rates, 6, "months")
    assert out["expected_short"] == pytest.approx(spares.poisson_short(2.4, 4, 1), abs=0.05)  # 1.19; it was 1.49
    assert out["risk_at_stock"] == pytest.approx(poisson.sf(1, 2.4), abs=0.03)  # unchanged
    assert out["waiting"]["exact"]


def test_first_failures_need_no_change():
    # Each item fails at most once already: nothing waits that would have failed again.
    dist = surpyval.Weibull.from_params([100.0, 2.0])
    out = fleet_service.spares_answer({"lead_time": 3, "stock": 1}, "single", dist, np.array([20.0, 60, 90]),
                                      np.full(3, 10.0), 6, "weeks")
    assert "waiting" not in out
