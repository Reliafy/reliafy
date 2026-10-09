"""SurPyval 0.24 adoption (#329): the pins, the results that moved, and the
new behaviour Reliafy keeps out on purpose.

0.24 removes the names 0.23 deprecated; Reliafy already called the new ones
(test_surpyval_023.py), so the suite runs clean with
``-W error::DeprecationWarning``. RePyability 0.13 runs on it unchanged
(test_rbd_analysis.py, test_rbd_export.py exercise the pairing).
"""

import matplotlib

matplotlib.use("Agg")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402
import repyability  # noqa: E402
import surpyval as sp  # noqa: E402
from surpyval.recurrent import CrowAMSAA  # noqa: E402

from backend import fitting  # noqa: E402
from backend import recurrent as rec  # noqa: E402
from backend.fitting import FitError  # noqa: E402
from backend.services import rbd_export  # noqa: E402


def test_the_pins_are_surpyval_0_24_and_repyability_0_13():
    assert sp.__version__ == "0.24"
    assert repyability.__version__ == "0.13"
    assert rbd_export.detect_versions() == {"surpyval": "0.24", "repyability": "0.13"}


# ---------------------------------------------------------------------------
# Growth projection with BC modes (#730): the bias-corrected shape
# ---------------------------------------------------------------------------
# MIL-HDBK-189's test-fix-find-test example, as SurPyval's own test has it:
# one system to T = 400, 56 failures: 10 A, 14 BC (BC17..BC28), 32 BD (BD1..BD16).
HDBK = """
0.7 BC17, 3.7 BC17, 13.2 BC17, 15 BD1, 17.6 BC18, 25.3 BD2, 47.5 BD3,
54 BD4, 54.5 BC19, 56.4 BD5, 63.6 A, 72.2 BD5, 99.2 BC20, 99.6 BD6,
100.3 BD7, 102.5 A, 112 BD8, 112.2 BC21, 120.9 BD2, 121.9 BC22, 125.5 BD9,
133.4 BD10, 151 BC23, 163 BC24, 164.7 BD9, 174.5 BC25, 177.4 BD10,
191.6 BC26, 192.7 BD11, 213 A, 244.8 A, 249 BD12, 250.8 A, 260.1 BD1,
263.5 BD8, 273.1 A, 274.7 BD6, 282.8 BC27, 285 BD13, 304 BD9, 315.4 BD4,
317.1 A, 320.6 A, 324.5 BD12, 324.9 BD10, 342 BD5, 350.2 BD3, 355.2 BC28,
364.6 BD10, 364.9 A, 366.3 BD2, 373 BD8, 379.4 BD14, 389 BD15, 394.9 A,
395.2 BD16
"""
FEFS = [0.67, 0.72, 0.77, 0.77, 0.87, 0.92, 0.5, 0.85, 0.89, 0.74, 0.7, 0.63, 0.64, 0.72, 0.69, 0.46]
MAP = {"i": "sys", "x": "t", "mode": "m"}


def test_bc_mode_projection_reproduces_the_handbook():
    """0.23 gave a demonstrated MTBF of 7.707 and a projected 11.006 here;
    0.24 takes the demonstrated intensity from the bias-corrected shape and
    gives the handbook's 7.847 and 11.294."""
    rows = [r.split() for r in HDBK.split(",")]
    df = pd.DataFrame({"sys": "P1", "t": [float(t) for t, _ in rows], "m": [m for _, m in rows]})
    fef = {f"BD{j + 1}": v for j, v in enumerate(FEFS)}
    bc = [f"BC{j}" for j in range(17, 29)]
    out = rec.growth_projection(df, MAP, fef, bc=bc, test_end=400)
    assert out["failures"] == {"A": 10, "BC": 14, "BD": 32}
    assert out["demonstrated_basis"] == "crow_amsaa"
    assert out["demonstrated"]["mtbf"] == pytest.approx(7.84708, abs=1e-5)
    assert out["projected"]["mtbf"] == pytest.approx(11.29418, abs=1e-5)


def test_bc_modes_with_one_failure_say_why():
    df = pd.DataFrame({"sys": "P1", "t": [50.0], "m": ["seal"]})
    with pytest.raises(FitError, match=r"modes fixed during the test \(BC\).*at least 2 failures"):
        rec.growth_projection(df, MAP, {}, bc=["seal"], test_end=400)
    # Without BC modes one failure still projects (the average intensity).
    out = rec.growth_projection(df, MAP, {"seal": 0.7}, test_end=400)
    ref = CrowAMSAA.projection([50.0, 400.0], ["seal", None], {"seal": 0.7}, c=[0, 1])
    assert out["projected"]["mtbf"] == pytest.approx(ref.projected_mtbf, rel=1e-12)


# ---------------------------------------------------------------------------
# New in 0.24, deliberately not surfaced yet
# ---------------------------------------------------------------------------
def test_cox_gets_a_qf_but_no_metrics_at_the_covariate_means():
    """0.24 gives CoxPH a step-curve ``qf`` (#662). Reliafy still gives no
    median / B10 / MTTF for a Cox model: its B10 would be an event time, and
    its curve often stops short of 0 (no mean)."""
    rng = np.random.default_rng(5)
    n = 60
    z = rng.normal(size=n)
    t = sp.Weibull.random(n, 100, 1.5, random_state=rng) * np.exp(-0.5 * z)
    df = pd.DataFrame({"t": t, "c": (rng.uniform(size=n) < 0.2).astype(int), "z": z})
    r = fitting.fit("cox_ph", df, {"x": "t", "c": "c"}, ["z"])
    model = fitting._MODEL_STORE[r["functions"]["model_id"]]["model"]
    assert callable(getattr(model, "qf", None))
    assert "at_covariate_means" not in r and r["metrics_note"] == fitting.REGRESSION_METRICS_NOTE
    assert fitting.regression_metrics_at_defaults(model, r["functions"]["covariates"]) is None
