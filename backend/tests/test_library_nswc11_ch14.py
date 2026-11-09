"""NSWC-11 Chapter 14, electric motors: the models against the handbook's own
equations, tables and figures (pages cited). The chapter has no worked example."""

import math

import pytest

from backend.library import covariate
from backend.library import service as library

STUB_RATES = {"nswc-11:shaft": 0.5, "nswc-11:bearing-rolling-load-rating": 2.0, "nswc-11:gear": 0.25}


def _stub(rid, rate):
    return {"id": rid, "name": rid, "kind": covariate.KIND, "covariate_model": {
        "rate_unit": "per_million_hours", "inputs": [], "derived": [], "checks": [],
        "modes": [{"key": "part", "name": "part", "base": {"value": rate, "page": "x"}, "factors": []}]}}


def resolve(rid):
    """The library, with the parts other chapters model swapped for fixed rates, so these tests check
    Chapter 14's own sum."""
    return _stub(rid, STUB_RATES[rid]) if rid in STUB_RATES else library.get(rid)


def lam(slug, **values):
    return covariate.evaluate(resolve(f"nswc-11:{slug}"), values, resolve)


def factors(out, key="windings"):
    row = next(m for m in out["modes"] if m["key"] == key)
    return {f["symbol"]: f["value"] for f in row["factors"]}, row


def test_winding_base_rate_default_is_40_per_million_hours():
    # p. 14-8: no maker's life → 25,000 hours, "failure rate λWI,B = 40.0 failures/million hours".
    out = lam("electric-motor-winding", supply="single_phase")
    assert round(out["total"], 1) == 40.0
    assert out["unit"] == "per_million_hours"


@pytest.mark.parametrize("T_O, c_t", [(40, 1.0), (50, 2.0), (30, 0.5), (80, 16.0)])
def test_temperature_factor_doubles_every_10_degrees(T_O, c_t):
    # Eq. 14-5, p. 14-11: C_T = 2^((T_O − 40)/10); Figure 14.1's axis runs to 20 at 80 °C.
    f, _ = factors(lam("electric-motor-winding", supply="single_phase", T_O=T_O))
    assert f["C_T"] == pytest.approx(c_t)


def test_class_f_in_class_b_environment_gap():
    # p. 14-11 says a Class F motor in a Class B environment "can be expected to last four times as long".
    # The classes are 25 °C apart (Table 14-2: 155 vs 130 °C); Eq. 14-5 makes that 2^2.5 = 5.66 times.
    # Four times is a 20 °C gap. The model follows Eq. 14-5; the text's "four" is documented, not hit.
    a = lam("electric-motor-winding", supply="single_phase", T_O=40)["total"]
    b = lam("electric-motor-winding", supply="single_phase", T_O=65)["total"]
    assert b / a == pytest.approx(2 ** 2.5)
    assert lam("electric-motor-winding", supply="single_phase", T_O=60)["total"] / a == pytest.approx(4.0)


def test_voltage_factors_by_supply():
    # Eq. 14-6 (single phase): 2^(10 V_D/V_R); Eq. 14-7 (three phase): 1 + (0.40 V_U)^2.5 (p. 14-12).
    f, row = factors(lam("electric-motor-winding", supply="single_phase", VD_VR=0.1, V_U=2))
    assert [x["symbol"] for x in row["factors"]] == ["C_T", "C_V", "C_alt"]
    assert f["C_V"] == pytest.approx(2.0)
    f, _ = factors(lam("electric-motor-winding", supply="three_phase", VD_VR=0.1, V_U=1))
    assert f["C_V"] == pytest.approx(1 + 0.4 ** 2.5)  # 1.101
    f, _ = factors(lam("electric-motor-winding", supply="three_phase", V_U=3))
    assert round(f["C_V"], 2) == 2.58  # inside Figure 14.3's 0-5 axis


def test_altitude_factor():
    # Eq. 14-8, p. 14-13: 1.0 to 3,300 ft, then 1 + 8e-5 (a − 3300).
    f, _ = factors(lam("electric-motor-winding", supply="single_phase", a=3300))
    assert f["C_alt"] == 1.0
    f, _ = factors(lam("electric-motor-winding", supply="single_phase", a=18000))
    assert f["C_alt"] == pytest.approx(1 + 8e-5 * 14700)  # 2.18, inside Figure 14.4's 0.5-2.5 axis


@pytest.mark.parametrize("motor_type, base, cv_eq", [("dc", 2.17, "14-6"), ("dc_brushless", 1.75, "14-6"),
                                                     ("ac_single", 6.90, "14-6"), ("ac_polyphase", 10.00, "14-7")])
def test_motor_sums_its_parts(motor_type, base, cv_eq):
    # Eq. 14-1, p. 14-7, with Tables 14-3 and 14-4 (p. 14-18); brushes 3.2 each, stator 0.001.
    n_bs = 2 if motor_type == "dc" else 0
    out = lam("electric-motor", motor_type=motor_type, load="medium_impact", n_BE=2, n_BS=n_bs, lambda_C=0.3,
              T_O=50, VD_VR=0.05, V_U=1)
    rates = {m["key"]: m["rate"] for m in out["modes"]}
    assert rates["motor"] == pytest.approx(base * 2.00)
    c_v = 2 ** 0.5 if cv_eq == "14-6" else 1 + 0.4 ** 2.5
    assert rates["windings"] == pytest.approx(40.0 * 2.0 * c_v)
    assert rates["brushes"] == pytest.approx(3.2 * n_bs)
    assert rates["stator"] == pytest.approx(0.001)
    assert rates["shaft"] == pytest.approx(0.5)
    assert rates["bearings"] == pytest.approx(4.0)
    assert rates["capacitor"] == pytest.approx(0.3)
    assert out["total"] == pytest.approx(sum(rates.values()))
    assert "gears" not in rates


def test_geared_motor_adds_its_gears():
    out = lam("electric-motor-geared", motor_type="ac_single", n_BE=2, n_GR=3)
    rates = {m["key"]: m["rate"] for m in out["modes"]}
    assert rates["gears"] == pytest.approx(0.75)
    assert out["total"] == pytest.approx(6.90 + 40.0 + 0.001 + 0.5 + 4.0 + 0.75)


def test_brush_checks_and_limits_warn_with_pages():
    words = " ".join(lam("electric-motor", motor_type="dc", n_BE=2)["warnings"])
    assert "brushed DC motor has brushes" in words
    words = " ".join(lam("electric-motor", motor_type="ac_polyphase", n_BE=2, V_U=3.5, T_O=90, a=20000,
                         VD_VR=0.5)["warnings"])
    for page in ("p. 14-12", "p. 14-13", "p. 14-14", "p. 14-15", "p. 14-17"):
        assert page in words
    with pytest.raises(covariate.CovariateError, match="Type of motor"):
        lam("electric-motor", n_BE=2)
    with pytest.raises(covariate.CovariateError):
        lam("electric-motor-winding", supply="single_phase", L_I=0)


def test_motor_reads_the_real_part_records():
    # Unstubbed: the motor's parts are the canonical Chapter 7, 8 and 20 records.
    rec = library.get("nswc-11:electric-motor-geared")
    used = {m["uses"] for m in rec["covariate_model"]["modes"] if m.get("uses")}
    assert used == {"nswc-11:shaft", "nswc-11:bearing-rolling-load-rating", "nswc-11:gear"}
    assert covariate.problems(rec, library.get) == []
    assert math.isfinite(lam("electric-motor", motor_type="ac_single", n_BE=1)["total"])
