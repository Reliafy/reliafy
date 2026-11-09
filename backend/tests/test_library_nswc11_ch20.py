"""NSWC-11 Chapter 20, shafts: the model against the handbook's equations and
tables (pages cited). The chapter has no worked example."""

import math

import pytest

from backend.library import covariate
from backend.library import service as library


def lam(**values):
    return covariate.evaluate(library.get("nswc-11:shaft"), values, library.get)


# Sections M and N absent: no need to type zeros, and a polished shaft needs no tensile strength.
SHAFT = dict(N_cycles=1e8, F=100, E=30e6, len_X=4, D_X=1.5, len_L=6, D_L=2.0, r=0.1, D_big=2.0, d_small=1.5)


def factors(out):
    return {f["symbol"]: f["value"] for f in out["modes"][0]["factors"]}


def test_shaft_model_multiplies_base_by_its_factors():
    out = lam(**SHAFT)
    f = factors(out)
    assert out["modes"][0]["base"]["value"] == pytest.approx(1e6 / 1e8)  # Eq. 20-4
    assert f["C_f"] == 1.0 and f["C_T"] == 1.0  # polished, 160 °F
    i = lambda d: math.pi * d ** 4 / 64  # noqa: E731
    assert f["C_DY"] == pytest.approx(0.0043 * 100 / (30e6 * 0.007) * (4 ** 3 / i(1.5) + 6 ** 3 / i(2.0)))
    c_scr = (0.3 / (0.1 / 1.5)) ** 0.2 * (2.0 / 1.5) ** (1 - 0.1 / 1.5)
    # Eq. 20-9 prints a sum, but C_SC,G = 1.0 with no grooves (p. 20-8) is a product's neutral value: Reliafy's
    # reading is C_SC,R × C_SC,G (the sum would add 1 to every plain shaft: +68 % here).
    assert f["C_SC"] == pytest.approx(c_scr)
    assert out["total"] == pytest.approx(0.01 * f["C_DY"] * c_scr)
    # Reliafy's reading (readings.SHAFT_PER_HOUR): per million hours, as every assembly lists the shaft.
    assert out["unit"] == "per_million_hours"
    notes = library.get("nswc-11:shaft")["notes"]
    assert notes.count("Reliafy's reading") == 3 and "p. 20-10" in notes and "p. 20-5" in notes


def test_review_shaft_hand_calculation():
    # The review's test shaft: N 4.4×10⁶, 100 lb at a 6 in overhang of 1.5 in, r 0.15, D/d 1.8/1.5, polished.
    out = lam(N_cycles=4.4e6, F=100, E=30e6, len_X=6, D_X=1.5, r=0.15, D_big=1.8, d_small=1.5)
    c_dy = 0.0043 * 100 / (30e6 * 0.007) * (6 ** 3 / (math.pi * 1.5 ** 4 / 64))
    c_sc = (0.3 / 0.1) ** 0.2 * 1.2 ** 0.9
    assert out["total"] == pytest.approx(1e6 / 4.4e6 * c_dy * c_sc)
    assert round(out["total"], 6) == 0.000594  # per million hours (was 0.000998 per million cycles)


@pytest.mark.parametrize("finish, ts, expected", [
    ("ground", 100, 0.89),
    ("hot_rolled", 100, 0.94 - 0.46 + 8.37e-6 * 1e4),
    ("machined", 100, 1.07 - 0.51 + 2.21e-5 * 1e4 - 3.57e-8 * 1e6),
    ("forged", 150, 0.75 - 4.06e-3 * 150 + 7.58e-6 * 150 ** 2),
])
def test_surface_finish_table_20_3(finish, ts, expected):
    # Table 20-3's endurance factors; Reliafy's reading (readings.SHAFT_FINISH_INVERTED) divides by them, so a
    # rougher finish raises the rate (forged at 100 kpsi: 2.38 × a polished shaft, not 0.42 ×).
    assert factors(lam(**{**SHAFT, "finish": finish, "T_S": ts}))["C_f"] == pytest.approx(1 / expected)


def test_rougher_finish_raises_the_rate():
    polished = lam(**SHAFT)["total"]
    forged = lam(**{**SHAFT, "finish": "forged", "T_S": 100})["total"]
    assert forged / polished == pytest.approx(1 / (0.75 - 0.406 + 0.0758)) and round(forged / polished, 2) == 2.38
    with pytest.raises(covariate.CovariateError) as exc:
        lam(**{**SHAFT, "finish": "machined"})
    assert exc.value.missing == ["T_S"]


@pytest.mark.parametrize("groove, printed", [("hD0.05_hr0.1", 1.10), ("hD0.10_hr6.0", 2.25), ("hD0.20_hr8.0", 2.00),
                                             ("hD0.30_hr1.0", 1.10)])
def test_groove_table_20_4(groove, printed):
    out = lam(**{**SHAFT, "groove": groove})
    d = {x["name"]: x["value"] for x in out["derived"]}
    assert d["C_SC_G"] == printed
    assert factors(out)["C_SC"] == pytest.approx(d["C_SC_R"] * printed)


def test_temperature_factor_eq_20_5():
    assert factors(lam(**{**SHAFT, "T_AT": 300}))["C_T"] == pytest.approx(760 / 620)


def test_a_section_with_length_needs_a_diameter_and_one_section_is_needed():
    with pytest.raises(covariate.CovariateError) as exc:
        lam(**{**SHAFT, "len_M": 3})
    assert exc.value.missing == ["D_M"]
    with pytest.raises(covariate.CovariateError, match="section X"):
        lam(**{**SHAFT, "len_X": 0})


def test_handbook_ranges_warn_with_the_page():
    out = lam(**{**SHAFT, "finish": "machined", "T_S": 300, "E": 5e6})
    assert "p. 20-11" in " ".join(out["warnings"])
