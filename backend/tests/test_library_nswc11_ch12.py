"""NSWC-11 Chapter 12, brakes and clutches: the models against the handbook's
equations and tables (pages cited). The chapter has no worked example. The
assemblies are tested with stand-in parts (a constant rate each), so their own
sums and unit conversions are checked whatever the other chapters' models give."""

import pytest

from backend.library import covariate
from backend.scripts.build_nswc11 import _record
from backend.scripts.nswc11 import ch12_brakes_clutches as ch12

RECORDS = {f"nswc-11:{r['slug']}": _record(r) for r in ch12.RECORDS}
WEAR = dict(material="sintered_bronze_dry", P=500, v_s=600, d=0.25, A=10, n_per_hour=20, lining_type="sintered_metallic")


def stub(rid, rate, unit="per_million_hours"):
    return {"id": rid, "kind": covariate.KIND, "name": rid, "covariate_model": {
        "rate_unit": unit, "inputs": [], "modes": [{"key": "m", "name": "m", "base": {"value": rate, "page": "x"}}]}}


STUBS = {"nswc-11:actuator-axial-load": stub("nswc-11:actuator-axial-load", 2.0, "per_million_cycles"),
         "nswc-11:spring-compression": stub("nswc-11:spring-compression", 3.0),
         "nswc-11:brake-friction-material": stub("nswc-11:brake-friction-material", 5.0),
         "nswc-11:clutch-friction-material": stub("nswc-11:clutch-friction-material", 7.0),
         "nswc-11:bearing-rolling-load-rating": stub("nswc-11:bearing-rolling-load-rating", 11.0),
         "nswc-11:seal-dynamic": stub("nswc-11:seal-dynamic", 13.0)}


def lam(slug, resolve=RECORDS.__getitem__, **values):
    return covariate.evaluate(RECORDS[f"nswc-11:{slug}"], values, resolve)


def factors(out):
    return {f["symbol"]: f["value"] for f in out["modes"][0]["factors"]}


def test_friction_records_have_no_problems():
    for rid, rec in RECORDS.items():
        assert covariate.problems(rec, {**RECORDS, **STUBS}.__getitem__) == [], rid


def test_brake_base_rate_is_eq_12_5_per_application_times_applications_an_hour():
    out = lam("brake-friction-material", t_b=3, **WEAR)
    per_application = 2.42e-10 * 500 * 600 * 3 / (0.25 * 10)  # Eq. 12-5, Table 12-8 sintered bronze (dry)
    c_t = 1.42 - 0.00154 * 660 + 0.00000138 * 660 ** 2  # Eq. 12-7 at 70 °F
    assert out["modes"][0]["base"]["value"] == pytest.approx(1e6 * 20 * per_application)
    assert out["total"] == pytest.approx(1e6 * 20 * per_application * c_t)
    assert out["unit"] == "per_million_hours"


@pytest.mark.parametrize("code, k", [("asbestos_1", 6.46e-11), ("asbestos_2", 8.09e-11), ("carbon_carbon", 2.24e-11),
                                     ("sintered_bronze_dry", 2.42e-10), ("non_asbestos_dry", 9.90e-10),
                                     ("sintered_bronze_wet", 5.02e-13), ("sintered_bronze_composite", 9.31e-11),
                                     ("sintered_resin_composite", 3.03e-11)])
def test_wear_coefficients_table_12_8(code, k):
    out = lam("clutch-friction-material", t_a=1, **{**WEAR, "material": code})
    assert next(x["value"] for x in out["derived"] if x["name"] == "k_o") == k


@pytest.mark.parametrize("lining, a, b, c", [("sintered_metallic", 1.42, 0.00154, 0.00000138),
                                             ("resin_asbestos", 2.79, 0.0109, 0.0000124),
                                             ("carbon_carbon", 3.80, 0.00759, 0.00000507),
                                             ("resin_asbestos_truck", 17.59, 0.0603, 0.0000534)])
def test_brake_temperature_factor_eqs_12_7_to_12_10(lining, a, b, c):
    for t in (-40, 70, 250):
        x = 590 + t
        f = factors(lam("brake-friction-material-known-rate", lambda_B=1, lining_type=lining, T=t))
        assert f["C_T"] == pytest.approx(a - b * x + c * x * x)
    # Each is about 1 at 70 °F (the truck resin-asbestos curve 1.05).
    assert factors(lam("brake-friction-material-known-rate", lambda_B=1, lining_type=lining))["C_T"] == \
        pytest.approx(1.0, abs=0.06)


def test_clutch_carbon_carbon_uses_its_own_page():
    # p. 12-19 prints 0.00758 where p. 12-13 prints 0.00759.
    f = factors(lam("clutch-friction-material-known-rate", lambda_B=1, lining_type="carbon_carbon", T=100))
    assert f["C_T"] == pytest.approx(3.80 - 0.00758 * 690 + 0.00000507 * 690 ** 2)


def test_brake_type_and_dust_factors():
    f = factors(lam("brake-friction-material-known-rate", lambda_B=1, lining_type="carbon_carbon", brake_type="drum"))
    assert f["C_BT"] == 1.25 and "C_RD" not in f  # dust only counts in heavy dust
    for binder, printed in [("phenolic", 3.5), ("oil_modified_phenolic", 1.2), ("rubber_phenolic", 1.1),
                            ("cashew", 1.1), ("oil_phenolic", 1.1)]:
        f = factors(lam("brake-friction-material-known-rate", lambda_B=1, lining_type="carbon_carbon",
                        brake_type="annulus", dust="heavy", binder=binder))
        assert (f["C_BT"], f["C_RD"]) == (0.90, printed)


def test_clutch_plates_multiply_as_printed():
    one = lam("clutch-friction-material", t_a=0.5, **WEAR)["total"]
    assert lam("clutch-friction-material", t_a=0.5, N_P=4, **WEAR)["total"] == pytest.approx(4 * one)


def test_brake_assembly_sums_parts_and_converts_actuator_cycles():
    resolve = {**RECORDS, **STUBS}.__getitem__
    out = lam("brake-assembly", resolve, AC_cycles_per_hour=10, n_SP=2, n_BE=4, n_SE=3)
    # Eq. 12-1: actuators 2 per million cycles × 10 an hour, springs, lining, bearings, seals, housing 3.0.
    assert out["total"] == pytest.approx(2 * 10 + 3 * 2 + 5 + 11 * 4 + 13 * 3 + 3.0)
    out = lam("clutch-assembly", resolve, AC_cycles_per_hour=10, n_SP=2, n_BE=4, n_SE=3)
    assert out["total"] == pytest.approx(2 * 10 + 11 * 4 + 7 + 13 * 3 + 3 * 2)  # Eq. 12-11


def test_limits():
    with pytest.raises(covariate.CovariateError, match="needed"):
        lam("brake-friction-material", **WEAR)
    with pytest.raises(covariate.CovariateError, match="at least one disk"):
        lam("clutch-friction-material-known-rate", lambda_B=1, lining_type="carbon_carbon", N_P=0)
