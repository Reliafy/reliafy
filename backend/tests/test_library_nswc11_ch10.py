"""NSWC-11 Chapter 10, pumps: the fluid driver against Tables 10-3 to 10-5 and
Figures 10.4 and 10.5, and the assembly as the sum of its parts (pages cited).
The chapter has no worked example."""

import pytest

from backend.library import covariate
from backend.library import service as library


def stub(slug, rate, unit="per_million_hours"):
    """A one-number record standing in for a part's own model (another chapter's)."""
    return {"id": f"nswc-11:{slug}", "kind": covariate.KIND, "name": slug, "covariate_model": {
        "rate_unit": unit, "inputs": [], "modes": [{"key": "x", "name": slug, "base": {"value": rate, "page": "-"}}]}}


STUBS = {r["id"]: r for r in (stub("seal-mechanical", 3.0), stub("shaft", 0.05),
                              stub("bearing-rolling-load-rating", 2.0))}


def resolve(rid):
    return STUBS.get(rid) or library.get(rid)


def fd(**values):
    return covariate.evaluate(library.get("nswc-11:pump-fluid-driver"), values, library.get)


FD = dict(driver="centrifugal_mixed_radial", casing="double_volute", Q=100, Q_r=100, V_O=1800, V_D=1800)


def factors(out):
    return {f["symbol"]: f["value"] for f in out["modes"][0]["factors"]}


def c_pf(casing, q):
    driver = "rotary_gear" if casing == "displacement" else "centrifugal_mixed_radial"
    return factors(fd(**{**FD, "casing": casing, "driver": driver, "Q": q * 100}))["C_PF"]


@pytest.mark.parametrize("casing, q, read", [
    # Read from Figure 10.4 (p. 10-16), to about ±0.1.
    ("ordinary_volute", 0.1, 9.75), ("ordinary_volute", 0.5, 7.25), ("ordinary_volute", 0.6, 6.2),
    ("ordinary_volute", 0.7, 5.05), ("ordinary_volute", 1.4, 4.95), ("ordinary_volute", 1.7, 6.8),
    ("modified_volute", 0.1, 5.15), ("modified_volute", 1.7, 2.55),
    ("double_volute", 0.1, 1.0), ("double_volute", 1.7, 0.63),
    ("displacement", 0.1, 0.9), ("displacement", 1.7, 2.67),
])
def test_flow_factor_table_10_3_follows_figure_10_4(casing, q, read):
    assert c_pf(casing, q) == pytest.approx(read, abs=0.12)


def test_ordinary_volute_uses_the_cube_the_figure_shows():
    # Table 10-3 prints the last term as 1.77 (Q/Qr)^2; the figure fits (Q/Qr)^3 (see the module docstring).
    assert c_pf("ordinary_volute", 0.6) == pytest.approx(9.94 - 0.54 - 3.6 + 1.77 * 0.216)
    assert c_pf("ordinary_volute", 1.05) == 1.0  # the table's flat 1.0 between 1.0 and 1.1


@pytest.mark.parametrize("ratio, read", [(0.5, 2.0), (1.0, 5.0), (2.0, 12.3)])
def test_speed_factor_follows_figure_10_5(ratio, read):
    # Eq. 10-4, Figure 10.5 (p. 10-17), read to about ±0.1.
    assert factors(fd(**{**FD, "V_O": 1800 * ratio}))["C_PS"] == pytest.approx(read, abs=0.12)


def test_fluid_driver_rate_tables_10_4_and_10_5():
    out = fd(**{**FD, "driver": "rotary_screw", "casing": "displacement", "F_AC": 20, "duty": "over_10h",
                "load": "heavy_shock"})
    f = factors(out)
    assert out["modes"][0]["base"]["value"] == 0.58
    assert f["C_C"] == pytest.approx(1.6) and f["C_SF"] == 1.75 and f["C_PS"] == pytest.approx(5.0)
    assert out["total"] == pytest.approx(0.58 * (0.80 + 1.1) * 5.0 * 1.6 * 1.75)


def test_driver_and_casing_must_agree_and_flow_warns_outside_the_table():
    out = fd(**{**FD, "casing": "displacement", "Q": 200})
    words = " ".join(out["warnings"])
    assert "centrifugal pump" in words and "p. 10-18" in words


def test_pump_assembly_is_the_sum_of_its_parts():
    # Eq. 10-2 (p. 10-10): seals + shaft + bearings + casing (0.01) + fluid driver, all per million hours. The
    # shaft is per million hours too (Reliafy's reading, readings.SHAFT_PER_HOUR: p. 10-10 lists it so), added
    # as it is. One pump speed and one filter size go to the fluid driver (and the seals and bearings).
    driver_inputs = {k: v for k, v in FD.items() if k != "V_O"}
    values = {"n": 1800, "filter_um": 10, "n_SE": 2, "n_BE": 3, **{f"fluid_driver.{k}": v for k, v in driver_inputs.items()}}
    out = covariate.evaluate(library.get("nswc-11:pump"), values, resolve)
    rates = {m["key"]: m["rate"] for m in out["modes"]}
    driver = fd(**FD, F_AC=10)["total"]  # V_O = the pump's 1800 rpm, F_AC = its 10 µm filter (C_C = 1.1)
    assert factors(fd(**FD, F_AC=10))["C_C"] == pytest.approx(1.1)
    assert rates == pytest.approx({"seals": 6.0, "shaft": 0.05, "bearings": 6.0, "casing": 0.01,
                                   "fluid_driver": driver})
    assert out["total"] == pytest.approx(12.06 + driver)
    assert "Reliafy's reading" in next(m for m in out["modes"] if m["key"] == "shaft")["note"]


def test_pump_enters_its_speed_and_filter_once():
    keys = {i["key"] for i in covariate.inputs(library.get("nswc-11:pump"), library.get)}
    assert {"n", "filter_um"} <= keys
    assert not {"seals.n", "seals.C_o", "bearings.n", "fluid_driver.V_O", "fluid_driver.F_AC"} & keys
