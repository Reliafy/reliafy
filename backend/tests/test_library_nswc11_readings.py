"""NSWC-11: the four places the handbook contradicts itself, each a switch in
``backend/scripts/nswc11/readings.py``. The defaults are the review's
recommendations (9 Nov 2026); with a switch off the record follows the page
literally. Both settings must build, and each is checked by hand here."""

import importlib
from contextlib import contextmanager

import pytest

from backend.library import covariate
from backend.scripts import build_nswc11
from backend.scripts.nswc11 import readings

SWITCHES = ("SHAFT_PER_HOUR", "GEAR_NORMALISED_AT_DESIGN", "SHAFT_FINISH_INVERTED", "PILLOW_BLOCK_PER_HOUR")


def _reload_chapters():
    for mod in build_nswc11.chapter_modules():
        importlib.reload(mod)


@contextmanager
def library_with(**switches):
    """The library as the chapter modules build it with these switches (restored afterwards)."""
    before = {k: getattr(readings, k) for k in SWITCHES}
    try:
        for k, v in switches.items():
            setattr(readings, k, v)
        _reload_chapters()
        records = {r["id"]: r for r in build_nswc11.build()["records"]}
        yield records
    finally:
        for k, v in before.items():
            setattr(readings, k, v)
        _reload_chapters()


def ev(records, slug, **values):
    return covariate.evaluate(records[f"nswc-11:{slug}"], values, records.__getitem__)


GEAR_AT_DESIGN = dict(V_o=1800, V_d=1800, L_O=1000, L_D=1000)
SHAFT = dict(N_cycles=4.4e6, F=100, E=30e6, len_X=6, D_X=1.5, r=0.15, D_big=1.8, d_small=1.5)


def test_defaults_are_the_reviews_recommendations():
    assert all(getattr(readings, k) is True for k in SWITCHES)
    with library_with() as lib:
        assert ev(lib, "gear", **GEAR_AT_DESIGN)["total"] == pytest.approx(1080.0)
        assert ev(lib, "gear-known-rate", lambda_GB=10, **GEAR_AT_DESIGN)["total"] == pytest.approx(10.0)
        assert covariate.rate_unit(lib["nswc-11:shaft"]) == "per_million_hours"
        assert covariate.rate_unit(lib["nswc-11:pillow-block"]) == "per_million_hours"
        polished = ev(lib, "shaft", **SHAFT)["total"]
        forged = ev(lib, "shaft", **SHAFT, finish="forged", T_S=100)["total"]
        assert forged / polished == pytest.approx(1 / 0.4198)  # rougher → higher
        # Each record a reading touches says so, with its page.
        for slug, page in [("gear", "p. 8-8"), ("gear-known-rate", "p. 8-8"), ("spline", "p. 8-8"),
                           ("shaft", "p. 20-10"), ("shaft", "p. 20-5"), ("pillow-block", "p. 23-14"),
                           ("pump", "p. 10-10")]:
            text = lib[f"nswc-11:{slug}"].get("notes") or ""
            assert "Reliafy's reading" in text and page in text, slug


def test_every_switch_off_follows_the_page_literally():
    with library_with(**{k: False for k in SWITCHES}) as lib:
        # Gear (Eqs. 8-3, 8-6): 2.0 × 25.8 at the design point.
        assert ev(lib, "gear", **GEAR_AT_DESIGN)["total"] == pytest.approx(1080 * 2.0 * 2 ** 4.69)
        assert round(ev(lib, "gear-known-rate", lambda_GB=10, **GEAR_AT_DESIGN)["total"], 1) == 516.3
        # Shaft per million cycles, finish factor as printed (forged at 100 kpsi lowers the rate to 0.42 ×).
        shaft = lib["nswc-11:shaft"]
        assert covariate.rate_unit(shaft) == "per_million_cycles"
        polished = ev(lib, "shaft", **SHAFT)["total"]
        assert ev(lib, "shaft", **SHAFT, finish="forged", T_S=100)["total"] / polished == pytest.approx(0.4198)
        # The pump, motors and compressor convert the per-cycle shaft by its revolutions an hour.
        pump = {m["key"]: m for m in lib["nswc-11:pump"]["covariate_model"]["modes"]}
        assert pump["shaft"]["scale"] == "60 * n"
        comp = {m["key"]: m for m in lib["nswc-11:compressor"]["covariate_model"]["modes"]}
        assert comp["shaft"]["scale"] == "SH_cycles_per_hour"
        motor = {m["key"]: m for m in lib["nswc-11:electric-motor"]["covariate_model"]["modes"]}
        assert motor["shaft"]["scale"] == "60 * n"
        assert covariate.rate_unit(lib["nswc-11:pillow-block"]) == "per_million_cycles"


@pytest.mark.parametrize("switch", SWITCHES)
def test_each_switch_alone_builds(switch):
    with library_with(**{switch: False}) as lib:
        assert len(lib) == 69
