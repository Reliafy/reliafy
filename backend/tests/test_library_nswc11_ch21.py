"""NSWC-11 Chapter 21, belt and chain drives: the models against the handbook's
equations, figures and tables (pages cited). The chapter has no worked example."""

import pytest

from backend.library import covariate
from backend.library import service as library
from backend.scripts.nswc11.ch21_belt_chain import BELT_TYPES


def lam(slug, **values):
    return covariate.evaluate(library.get(f"nswc-11:{slug}"), values, library.get)


def factors(out, key):
    mode = next(m for m in out["modes"] if m["key"] == key)
    return {f["symbol"]: f["value"] for f in mode["factors"]}


BELT = dict(hp_O=10, hp_D=10, PD=4.5, belt_type="A", torque="normal", service="intermittent", driven_load="light",
            shock="none", pulley_type="grooved")


def test_belt_drive_is_eq_21_7():
    # Eq. 21-7, p. 21-11: 40 · C_BL · C_t · C_PD · C_BT · C_BV · C_SV + λ_P
    out = lam("belt-drive", **BELT)
    c_bl = 0.3 + (1 / 1.1) ** 4.2
    # The belt temperature defaults to 85 °F, the rating temperature (p. 21-3): C_t = 2^(45/55) = 1.763.
    c_t = 2 ** ((85 - 40) / 55)
    assert factors(out, "belt")["C_t"] == pytest.approx(c_t) and round(c_t, 2) == 1.76
    assert out["total"] == pytest.approx(40 * c_bl * c_t * 2.0 * 0.93 * 1.0 * 1.1 + 1.5)
    assert lam("belt-drive", **BELT, T_O=40)["total"] == pytest.approx(40 * c_bl * 1.0 * 2.0 * 0.93 * 1.0 * 1.1 + 1.5)
    assert out["unit"] == "per_million_hours"


@pytest.mark.parametrize("ratio, read", [(0.7, 0.45), (1.0, 1.0), (1.5, 4.0), (2.0, 12.6)])
def test_belt_load_factor_follows_figure_21_6(ratio, read):
    # Figure 21.6, p. 21-12: C_BL = 0.3 + (ratio/1.1)^4.2. Points read from the curve; the printed
    # formula gives 0.97 at a ratio of 1 where the curve reads about 1.0.
    c = factors(lam("belt-drive", **{**BELT, "hp_O": 10 * ratio}), "belt")["C_BL"]
    assert c == pytest.approx(read, rel=0.08)


@pytest.mark.parametrize("T, read", [(-20, 1.0), (40, 1.0), (100, 2.1), (150, 4.0), (200, 7.5)])
def test_belt_temperature_factor_follows_figure_21_7(T, read):
    # Figure 21.7, p. 21-13: 1 to 40 °F, then 2^((T - 40)/55); points read from the curve.
    c = factors(lam("belt-drive", **{**BELT, "T_O": T}), "belt")["C_t"]
    assert c == pytest.approx(read, rel=0.05)


@pytest.mark.parametrize("PD, read", [(2.5, 6.5), (3.0, 4.5), (4.5, 2.0), (8.5, 0.56)])
def test_pulley_factor_follows_figure_21_8(PD, read):
    # Figure 21.8, p. 21-14: C_PD = 2 (4.5/PD)^2.
    assert factors(lam("belt-drive", **{**BELT, "PD": PD}), "belt")["C_PD"] == pytest.approx(read, rel=0.03)


def test_belt_type_table_21_2():
    printed = {"SPZ": 0.8, "SPA": 0.48, "SPB": 0.33, "SPC": 0.18, "Y": 9.09, "Z": 4.16, "A": 0.93, "B": 0.54,
               "C": 0.30, "D": 0.14}
    assert {c: v for c, _, v in BELT_TYPES} == printed
    assert factors(lam("belt-drive", **{**BELT, "belt_type": "Y"}), "belt")["C_BT"] == 9.09


# Table 21-3, p. 21-15: rows (driven load) × columns (torque, service), as printed.
TABLE_21_3 = {
    "light": {("normal", "intermittent"): 1.0, ("normal", "normal"): 1.1, ("normal", "continuous"): 1.2,
              ("high", "intermittent"): 1.1, ("high", "normal"): 1.2, ("high", "continuous"): 1.3},
    "heavier": {("normal", "intermittent"): 1.1, ("normal", "normal"): 1.2, ("normal", "continuous"): 1.3,
                ("high", "intermittent"): 1.2, ("high", "normal"): 1.3, ("high", "continuous"): 1.4},
}


@pytest.mark.parametrize("load, torque, service", [(ld, t, s) for ld, row in TABLE_21_3.items() for t, s in row])
def test_operating_service_expression_reproduces_table_21_3(load, torque, service):
    out = lam("belt-drive", **{**BELT, "driven_load": load, "torque": torque, "service": service})
    assert factors(out, "belt")["C_BV"] == pytest.approx(TABLE_21_3[load][(torque, service)])


@pytest.mark.parametrize("shock, torque, printed", [("none", "normal", 1.1), ("medium", "high", 1.5),
                                                    ("heavy", "high", 1.7), ("light", "normal", 1.2)])
def test_shock_table_21_4(shock, torque, printed):
    assert factors(lam("belt-drive", **{**BELT, "shock": shock, "torque": torque}), "belt")["C_SV"] == printed


def test_belt_pulleys_flat_and_grooved():
    flat = next(m for m in lam("belt-drive", **{**BELT, "pulley_type": "flat"})["modes"] if m["key"] == "pulleys")
    assert flat["rate"] == 0.8


def test_belt_limits_warn_with_pages_and_refuse():
    out = lam("belt-drive", **{**BELT, "hp_O": 25, "T_O": 210, "PD": 2})
    words = " ".join(out["warnings"])
    assert "p. 21-12" in words and "p. 21-13" in words and "p. 21-14" in words and "p. 21-11" in words
    with pytest.raises(covariate.CovariateError, match="needed"):
        lam("belt-drive", hp_O=10, hp_D=10, PD=4.5)


CHAIN = dict(P=0.75, n=40, ST=19)  # S = 0.75 · 19 · 40 / 12 = 47.5 ft/min


def test_chain_drive_is_eq_21_11_at_neutral_conditions():
    # Eq. 21-11, p. 21-23: 15 · C_CV · C_CS · C_CT · C_CI · C_ST + 0.8; every factor 1 here.
    out = lam("chain-drive", **CHAIN)
    assert out["total"] == pytest.approx(15.8)
    assert next(d for d in out["derived"] if d["name"] == "S")["value"] == pytest.approx(47.5)  # Eq. 21-8


@pytest.mark.parametrize("n, printed", [(40, 1.0), (42.2, 1.2), (84.2, 1.2), (85, 1.4), (134, 1.4)])
def test_chain_speed_table_21_8(n, printed):
    # S = 1.1875 n ft/min: < 50 → 1.0, 50–100 → 1.2, > 100–160 → 1.4.
    assert factors(lam("chain-drive", **{**CHAIN, "n": n}), "chain")["C_CS"] == printed


def test_chain_tables_21_7_9_10_and_figure_21_16():
    f = factors(lam("chain-drive", **CHAIN, load="some_impact", driver="moderate_shock", T_C=180,
                    lubrication="stream"), "chain")
    assert f["C_CV"] == 1.7 and f["C_CT"] == 1.5 and f["C_CI"] == 0.7
    f = factors(lam("chain-drive", **{**CHAIN, "ST": 15}, load="large_impact", T_C=250, lubrication="manual"),
                "chain")
    assert f["C_CV"] == 1.8 and f["C_CT"] == 2.0 and f["C_CI"] == 1.5
    assert f["C_ST"] == pytest.approx(19 / 15)  # Figure 21.16 reads about 1.27 at 15 teeth


def test_chain_beyond_its_tables_warns():
    out = lam("chain-drive", P=0.75, n=1000, ST=12, T_C=300)
    words = " ".join(out["warnings"])
    assert "p. 21-26" in words and "p. 21-27" in words and "p. 21-28" in words
    assert factors(out, "chain")["C_CS"] == 1.4
