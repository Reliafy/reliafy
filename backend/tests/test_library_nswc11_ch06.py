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
    notes = rec("valve-poppet")["notes"]
    assert "Table 1-1" in notes and "0.597" in notes and "usually well below 1" in notes


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


SEAL = {"Q_f": 0.06, "D_SL": 0.34, "M": 500, "C": 910, "f": 35, "T_R": 250}
SPRING = {"G_M": 11.5e6, "D_W": 0.085, "D_C": 0.58, "N_a": 14, "T_S": 245e3, "L1": 3.35, "L2": 2.28}
SOLENOID = {"T_R": 130, "T_O": 70}
SHARED = {"P1": 3000, "P2": 15, "T_O": 100, "source": "piston_pump", "FR": 10}


def _pre(prefix, d):
    return {f"{prefix}.{k}": v for k, v in d.items()}


def test_valve_assembly_is_per_hour_at_one_operation_a_minute():
    # Eq. 6-1 (p. 6-3) with every part on one time basis, as the handbook's rule (pp. 12-10, 12-16) and
    # Chapter 1's worked valve (Table 1-1, Figure 1.3, p. 1-12/1-13) do: the poppet's rate per million
    # operations × 60 operations an hour, plus the seal, spring, solenoid and housing per million hours.
    poppet_inputs = {k: POPPET[k] for k in ("Q_f", "f", "S_S", "D_S", "L_W", "F_L")}
    out = lam("valve-assembly", ops_per_hour=60, **SHARED, **_pre("poppet", poppet_inputs), **_pre("seal", SEAL),
              **_pre("spring", SPRING), **_pre("solenoid", SOLENOID))
    assert out["unit"] == "per_million_hours"
    parts = {m["key"]: m["rate"] for m in out["modes"]}
    # Each part by hand, from its own record under the same conditions:
    poppet = lam("valve-poppet", **{**POPPET, **SHARED})["total"]  # per million operations
    seal = lam("seal-static", **SEAL, **SHARED)["total"]
    spring = lam("spring-compression", **SPRING, cycle_rate=1.0)["total"]  # one spring cycle per operation
    solenoid = 2.77 * (1 / 1.5 ** ((130 - 70 - 20) / 10)) ** 3 * 1.1 * 60  # Eq. 5-1 at 1 operation a minute
    assert parts["poppet"] == pytest.approx(poppet * 60)
    assert parts["seal"] == pytest.approx(seal) and parts["spring"] == pytest.approx(spring)
    assert parts["solenoid"] == pytest.approx(solenoid) and parts["housing"] == pytest.approx(0.01)
    hand = poppet * 60 + seal + spring + solenoid + 0.01
    assert out["total"] == pytest.approx(hand)
    assert round(out["total"], 2) == 10.20
    # Before the fix the record summed these unconverted and labelled the sum per million operations
    # (2.71), which a prediction then multiplied by 60 an hour: 162.6 per million hours, 16× too high.
    unconverted = poppet + seal + spring + solenoid + 0.01
    assert round(unconverted * 60, 1) == 162.6
    # The shared conditions are entered once: not again under the seal or poppet.
    keys = {i["key"] for i in covariate.inputs(rec("valve-assembly"), library.get)}
    assert {"P1", "T_O", "ops_per_hour"} <= keys
    assert not {"seal.P1", "poppet.T_O", "spring.cycle_rate", "solenoid.ops_per_min"} & keys
    with pytest.raises(covariate.CovariateError, match="Unknown input"):
        lam("valve-assembly", **{"seal.P1": 3000})
    no_solenoid = lam("valve-assembly", ops_per_hour=60, n_solenoids=0, **SHARED, **_pre("poppet", poppet_inputs),
                      **_pre("seal", SEAL), **_pre("spring", SPRING))
    assert no_solenoid["total"] == pytest.approx(out["total"] - parts["solenoid"])


def test_sliding_valve_assembly_converts_its_spool():
    spool = dict(Q_f=0.05, B=600, D_SP=1.0, mu=0.5, F_L=0.5)
    out = lam("valve-assembly-sliding", ops_per_hour=6, **SHARED, **_pre("spool", spool), **_pre("seal", SEAL),
              **_pre("spring", SPRING), **_pre("solenoid", SOLENOID))
    per_op = lam("valve-sliding", **spool, **SHARED)["total"]
    parts = {m["key"]: m for m in out["modes"]}
    assert parts["spool"]["rate"] == pytest.approx(per_op * 6) and parts["spool"]["scale"] == 6
    assert out["unit"] == "per_million_hours"


def test_limits_refuse_and_warn_with_the_page():
    with pytest.raises(covariate.CovariateError, match="Contact pressure"):
        lam("valve-poppet", **{**POPPET, "S_S": 0})
    with pytest.raises(covariate.CovariateError, match="Table 6-6 has no reliable value"):
        lam("valve-poppet", **{**POPPET, "fluid": "water", "T_O": 0})
    out = lam("valve-sliding", P1=3000, Q_f=0.05, B=100, D_SP=5, mu=0.5, **FLUID)
    words = " ".join(out["warnings"])
    assert "p. 6-26" in words and "p. 6-27" in words
    assert lam("valve-housing")["total"] == 0.01
