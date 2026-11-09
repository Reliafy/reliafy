"""NSWC-11 Chapter 6, valve assemblies: the models against the handbook's own
figures, tables and Chapter 1's worked example (pages cited)."""

import pytest

from backend.library import covariate
from backend.library import service as library


def rec(slug):
    return library.get(f"nswc-11:{slug}")


def lam(slug, **values):
    return covariate.evaluate(rec(slug), values, library.get)


def factors(out):
    return {f["symbol"]: f["value"] for f in out["modes"][0]["factors"]}


FLUID = dict(T_O=100, source="sliding_valve", FR=10, F_L=0.5)
# Table 1-1, p. 1-12: the example valve's poppet (ν_a = 2e-8 lbf·min/in², the reference viscosity).
POPPET = dict(P1=3000, P2=15, Q_f=0.06, f=35, S_S=4045, D_S=1.69, L_W=0.85, **FLUID)


def test_table_1_1_poppet():
    # The printed λ_P = 0.35 is the leakage form of p. 1-7 (Eq. 6-4 in Eq. 6-3) per million operations,
    # times the example's 0.5 operations an hour:
    per_op = 1.40 * 2e2 * 1.69 * 35e-6 ** 3 * (3000 ** 2 - 15 ** 2) * 1.00 / (0.06 * 2e-8 * 0.85 * 4045 ** 1.5)
    assert round(per_op * 0.5, 2) == 0.35
    # The library's model is the normalised Eq. 6-6 (p. 6-9). For the same poppet its factors are
    # C_P = (2985/3000)², C_Q = 0.055/0.06, C_F = 35^1.65/353, C_ν = 1, C_S = 0.26 (9000/4045)^1.5,
    # C_DT = 1.1·1.69 + 0.32, C_SW = 0.25 (land over 0.34 in). Table 1-1 gives no contamination or flow, so
    # C_N and C_W are left out of the comparison: 0.597 per million operations, 0.30 an hour at 0.5
    # operations an hour, against the printed 0.35. The gap is the handbook's two forms, not the model.
    out = lam("valve-poppet", **POPPET)
    f = factors(out)
    assert f["C_SW"] == 0.25 and f["C_ν"] == pytest.approx(1.0)
    without_n_w = out["total"] / (f["C_N"] * f["C_W"])
    expected = 1.40 * (2985 / 3000) ** 2 * (0.055 / 0.06) * 35 ** 1.65 / 353 * 0.26 * (9000 / 4045) ** 1.5 \
        * (1.1 * 1.69 + 0.32) * 0.25
    assert without_n_w == pytest.approx(expected)
    assert round(without_n_w, 3) == 0.597
    assert round(without_n_w * 0.5, 2) == 0.30
    assert out["unit"] == "per_million_operations"
    assert any("p. 6-25" in w for w in out["warnings"])  # L_W = 0.85 is past Figure 6.11


def test_poppet_figure_formulas():
    f = factors(lam("valve-poppet", **{**POPPET, "L_W": 0.18, "S_S": 9000, "D_S": 0.62, "F_L": 1.0}))
    assert f["C_SW"] == pytest.approx(3.55 - 24.52 * 0.18 + 72.99 * 0.18 ** 2 - 85.75 * 0.18 ** 3)
    assert f["C_SW"] == pytest.approx(1.0, abs=0.02)  # Figure 6.11 crosses 1.0 at about 0.18 in
    assert f["C_S"] == pytest.approx(0.26)
    assert f["C_DT"] == pytest.approx(1.002)
    assert f["C_W"] == pytest.approx(2.0)
    # Figure 6.6 is given above 50 psi only: lower pressures compute with a warning.
    out = lam("valve-poppet", **{**POPPET, "P1": 40, "P2": 14.7})
    assert any("p. 6-20" in w for w in out["warnings"])


def test_viscosity_uses_table_3_3_for_carbon_dioxide():
    # Table 6-6 (p. 6-31) prints CO2 as 0.7 to 0.9; Table 3-3 (p. 3-37) as 599.9 to 352.1, which its formula
    # supports. The model uses Table 3-3's row.
    f = factors(lam("valve-poppet", **{**POPPET, "fluid": "co2", "T_O": 100}))
    assert f["C_ν"] == pytest.approx(449.7)
    f = factors(lam("valve-poppet", **{**POPPET, "fluid": "sae20", "T_O": 125}))
    assert f["C_ν"] == pytest.approx((0.167 + 0.492) / 2)  # interpolated between the 50 °F steps


def test_sliding_valve():
    out = lam("valve-sliding", P1=3000, Q_f=0.05, B=600, D_SP=1.0, mu=0.5, **FLUID)
    f = factors(out)
    assert list(f) == ["C_P", "C_Q", "C_ν", "C_N", "C_B", "C_DS", "C_μ", "C_W"]
    assert f["C_B"] == pytest.approx(600 ** 2 / 6e5)
    assert f["C_DS"] == pytest.approx(0.615) and f["C_μ"] == 0.5
    assert out["total"] == pytest.approx(1.25 * f["C_P"] * f["C_Q"] * f["C_ν"] * f["C_N"] * 0.6 * 0.615 * 0.5 * 1.25)
    assert factors(lam("valve-sliding", P1=3000, Q_f=0.05, B=400, D_SP=1.0, mu=0.5, **FLUID))["C_B"] == 0.42


def test_valve_assembly_adds_its_parts_as_printed():
    values = {f"poppet.{k}": v for k, v in POPPET.items()}
    values.update({"seal.P1": 3000, "seal.Q_f": 0.06, "seal.D_SL": 0.34, "seal.M": 500, "seal.C": 910, "seal.f": 35,
                   "seal.T_R": 250, "seal.T_O": 200, "seal.source": "cylinder", "seal.FR": 10})
    values.update({"spring.G_M": 11.5e6, "spring.D_W": 0.085, "spring.D_C": 0.58, "spring.N_a": 14,
                   "spring.T_S": 245e3, "spring.L1": 3.35, "spring.L2": 2.28, "spring.cycle_rate": 0.5 / 60})
    values.update({"solenoid.T_R": 130, "solenoid.T_O": 110, "solenoid.ops_per_min": 0.5 / 60})
    out = lam("valve-assembly", **values)
    parts = {m["key"]: m["rate"] for m in out["modes"]}
    assert parts["housing"] == pytest.approx(0.01)
    assert out["total"] == pytest.approx(sum(parts.values()))
    assert out["unit"] == "per_million_operations"
    assert all(m.get("note") for m in out["modes"] if m["key"] != "poppet")
    no_solenoid = lam("valve-assembly", n_solenoids=0, **values)
    assert no_solenoid["total"] == pytest.approx(out["total"] - parts["solenoid"])


def test_limits_refuse_and_warn_with_the_page():
    with pytest.raises(covariate.CovariateError, match="Contact pressure"):
        lam("valve-poppet", **{**POPPET, "S_S": 0})
    with pytest.raises(covariate.CovariateError, match="Table 6-6 has no reliable value"):
        lam("valve-poppet", **{**POPPET, "fluid": "water", "T_O": 0})
    out = lam("valve-sliding", P1=3000, Q_f=0.05, B=100, D_SP=5, mu=0.5, **FLUID)
    words = " ".join(out["warnings"])
    assert "p. 6-26" in words and "p. 6-27" in words
    assert lam("valve-housing")["total"] == 0.01
