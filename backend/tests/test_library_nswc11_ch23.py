"""NSWC-11 Chapter 23, miscellaneous parts: the typical rates in the text, the
service tables 23-3, 23-8 and 23.14, and Eq. 23-1 (pages cited). The chapter has no
worked example."""

import pytest

from backend.library import covariate
from backend.library import service as library


def lam(slug, **values):
    return covariate.evaluate(library.get(f"nswc-11:{slug}"), values, library.get)


@pytest.mark.parametrize("slug, rate, unit", [
    ("axle", 0.01, "per_million_hours"),  # p. 23-3
    ("bushing", 0.72, "per_million_hours"),  # p. 23-6
    ("cam-mechanism", 6.1, "per_million_hours"),  # p. 23-8
    ("hinge", 0.5, "per_million_cycles"),  # p. 23-12
    ("key-pin", 0.35, "per_million_hours"),  # p. 23-13
    ("pillow-block", 5.0, "per_million_cycles"),  # p. 23-14, per million revolutions
    ("wire-rope", 17.5, "per_million_operations"),  # p. 23-22
])
def test_typical_rates(slug, rate, unit):
    out = lam(slug)
    assert out["total"] == pytest.approx(rate) and out["unit"] == unit


@pytest.mark.parametrize("loading, vibration, printed", [("light", "normal", 1.00), ("medium", "high", 1.88),
                                                         ("heavy", "normal", 1.67), ("very_heavy", "high", 3.75)])
def test_bolt_table_23_3(loading, vibration, printed):
    assert lam("bolt", loading=loading, vibration=vibration)["total"] == pytest.approx(0.12 * printed)


def test_bolt_count():
    assert lam("bolt", n_bolts=8)["total"] == pytest.approx(0.96)


def test_fitting_types():
    assert lam("fitting", fitting_type="threaded")["total"] == 1.3
    assert lam("fitting", fitting_type="quick_disconnect")["total"] == 2.4


@pytest.mark.parametrize("shock, duty, printed", [("uniform", "normal_low", 1.1), ("uniform", "high_high", 1.4),
                                                  ("medium", "normal_high", 1.5), ("heavy", "high_low", 1.5),
                                                  ("heavy", "high_high", 1.7)])
def test_flywheel_table_23_8(shock, duty, printed):
    assert lam("flywheel", shock=shock, duty=duty)["total"] == pytest.approx(0.2 * printed)


@pytest.mark.parametrize("env, humidity, printed", [("normal", "low", 1.0), ("normal", "high", 1.2),
                                                    ("random", "high", 1.4), ("continuous", "low", 1.5),
                                                    ("continuous", "high", 1.8)])
def test_setscrew_table_23_14(env, humidity, printed):
    assert lam("setscrew", environment=env, humidity=humidity)["total"] == pytest.approx(0.35 * printed)


def test_rivet_out_of_round_holes():
    assert lam("rivet")["total"] == pytest.approx(0.08)
    assert lam("rivet", holes="out_of_round")["total"] == pytest.approx(0.8)  # p. 23-18: "a factor of 10"


def test_power_screw_eq_23_1():
    # Eq. 23-1, p. 23-15: λ_PS = λ_PS,B (L_A/L_S)^3
    assert lam("power-screw", lam_PSB=4.0, L_A=500, L_S=1000)["total"] == pytest.approx(0.5)
    with pytest.raises(covariate.CovariateError, match="needed"):
        lam("power-screw", L_A=500, L_S=1000)


def test_pillow_block_from_l10_uses_the_chapter_7_bearing():
    out = lam("pillow-block-from-l10", **{"bearing.L10h": 10000, "bearing.L_A": 500, "bearing.L_S": 1000})
    direct = covariate.evaluate(library.get("nswc-11:bearing-rolling-known-l10"),
                                {"L10h": 10000, "L_A": 500, "L_S": 1000}, library.get)
    assert out["total"] == pytest.approx(direct["total"])
