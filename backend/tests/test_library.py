"""The reliability data library (backend/library): the shipped records and
their schema, the importers' rules, search, the conversions to block models,
and the public routes. The MCP tool, /api/v1 and the CLI are checked here too
(the parity test in test_api_tools.py covers their routing). The sources: the
NRC / INL industry averages (field data) and MIL-HDBK-217F Notice 2 (a
handbook prediction model)."""

import copy
import json
import math

import pytest
import surpyval as sp
from fastapi.testclient import TestClient
from scipy import stats

from backend.library import convert, schema, service
from backend.scripts import import_mil_hdbk_217f as mil_importer
from backend.scripts import import_nrc_inl as importer
from backend.tests.test_mcp import _err, _ok
from backend.tests.test_mcp_plans import FREE, PRO, _call, env  # noqa: F401 - env is a fixture

NRC = "nrc-inl-2020"
MIL = "mil-hdbk-217f-n2"
N_NRC, N_MIL = 300, 158


def _rec(code: str) -> dict:
    return service.get(f"{NRC}:{importer.slug(code)}")


def _all() -> list[dict]:
    return service._library()["records"]


# ---- the shipped data ---------------------------------------------------------------------

def test_every_record_may_ship():
    records = _all()
    assert len(records) == N_NRC + N_MIL
    assert sum(r["source"] == NRC for r in records) == N_NRC and sum(r["source"] == MIL for r in records) == N_MIL
    assert [p for r in records for p in schema.problems(r)] == []
    assert len({r["id"] for r in records}) == len(records)
    for r in records:
        assert r["source"] in service._library()["sources"]
        assert r["licence"]["id"] in schema.LICENCES and r["licence"]["attribution"].strip()
        assert r["citation"]["url"].startswith("https://") and r["citation"]["retrieved"]
        assert r["basis"] in schema.BASES and r["units"]["value"] in schema.VALUE_UNITS[r["kind"]]


def test_the_data_files_carry_their_provenance():
    for path in service.DATA_DIR.glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["schema"] == schema.SCHEMA_VERSION
        src = data["source"]
        assert path.stem == src["id"]
        assert src["licence"]["id"] in schema.LICENCES and src["url"] and src["retrieved"] and src["sha256"]
        assert all(r["source"] == src["id"] for r in data["records"])
        # Every row of the table is either a record or skipped with its reason.
        assert all(s["reason"] for s in data["skipped"])


def test_the_data_ships_with_the_app():
    """The ignore files exclude every data/ folder (local app data), so the
    library's must be let back in: without it git wouldn't track the records
    and Cloud Build wouldn't upload them, and the library would be empty."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    for name in (".gitignore", ".gcloudignore"):
        lines = (root / name).read_text().splitlines()
        assert "!backend/library/data/" in lines, name
        assert lines.index("!backend/library/data/") > lines.index("data/"), name


def test_nrc_numbers_match_their_distributions_and_surpyval():
    """The table's mean and percentiles are its gamma / beta parameters' (to
    the printed rounding), and SurPyval agrees with the formulas."""
    rec = _rec("MDP-FTS-NS")  # beta(2.07, 3520): Table 1, mean 5.88E-04, 5th 1.09E-04, 95th 1.38E-03
    assert rec["kind"] == "per_demand" and rec["distribution"]["family"] == "beta"
    assert rec["evidence"]["failures"] == 227 and rec["evidence"]["demands"] == 410593
    b = sp.Beta.from_params([2.07, 3520.0])
    assert b.mean() == pytest.approx(rec["summary"]["mean"], rel=2e-3)
    assert b.qf(0.05) == pytest.approx(rec["summary"]["p05"], rel=5e-3)
    assert b.qf(0.95) == pytest.approx(rec["summary"]["p95"], rel=5e-3)
    rec = _rec("AOV-FC")  # gamma(1.26, 7.17E+06 h): mean 1.75E-07 per hour
    g = sp.Gamma.from_params([1.26, 7.17e6])
    assert g.mean() == pytest.approx(rec["summary"]["mean"], rel=5e-3)
    assert schema.mean_of("gamma", schema.param_dict(rec["distribution"])) == pytest.approx(g.mean())


def _good() -> dict:
    return copy.deepcopy(_rec("MDP-FTR>1H"))


@pytest.mark.parametrize("break_it, says", [
    (lambda r: r.pop("licence"), "licence"),
    (lambda r: r["licence"].update(id="all-rights-reserved"), "may republish"),
    (lambda r: r["licence"].update(attribution=" "), "attribution"),
    (lambda r: r.update(source=""), "missing source"),
    (lambda r: r["citation"].pop("url"), "citation is missing url"),
    (lambda r: r.update(basis="vendor brochure"), "unknown basis"),
    (lambda r: r["units"].update(value="per_fortnight"), "unknown units"),
    (lambda r: r["units"].update(time_basis=None), "time_basis"),
    (lambda r: r["distribution"].update(params=[{"name": "mu", "value": 1.0}, {"name": "sigma", "value": 1.0}]),
     "gamma takes alpha, beta"),
    (lambda r: r["distribution"].update(family="beta"), "can't describe a rate"),
    (lambda r: r["summary"].update(mean=r["summary"]["mean"] * 1.1), "disagrees with its parameters"),
    (lambda r: r["summary"].update(p95=r["summary"]["p95"] * 1.5), "p95"),
    (lambda r: r.update(equipment_type="spaceship"), "equipment_type"),
])
def test_a_record_that_cant_ship_is_caught(break_it, says):
    rec = _good()
    break_it(rec)
    found = schema.problems(rec)
    assert found and any(says in p for p in found), found


def test_other_sources_fit_the_same_schema():
    """A handbook point rate (MIL-HDBK-217F style, without environment
    factors) and a Weibull table row are records of the same shape."""
    base = _good()
    mil = {**copy.deepcopy(base), "id": "mil-217f:resistor", "basis": "prediction_model",
           "distribution": {"family": "point", "params": [{"name": "value", "value": 2.5e-9}]},
           "summary": {"mean": 2.5e-9}, "conditions": {"environment": "Ground, benign"},
           "prediction": {"formula": "λp = λb", "per_million_hours": 0.0025, "not_applied": []}}
    weibull = {**copy.deepcopy(base), "id": "table:bearing", "kind": "life", "basis": "field_data",
               "units": {"value": "hours", "time_basis": None},
               "distribution": {"family": "weibull", "params": [{"name": "alpha", "value": 40000.0},
                                                                {"name": "beta", "value": 1.3}]},
               "summary": {"mean": 40000.0 * math.gamma(1 + 1 / 1.3)}}
    assert schema.problems(mil) == [] and schema.problems(weibull) == []
    out = convert.rate_to_exponential(mil)
    assert out["failure_rate"] == 2.5e-9 and out["bounds"] == {"p05": None, "p95": None}
    life = convert.to_block_model(weibull)
    assert life["model"] == {"distribution_id": "weibull", "params": weibull["distribution"]["params"]}
    assert life["unit"] == "Hours"


# ---- the importer's rules (row -> record) ----------------------------------------------------

# Rows exactly as the PDF's Table 1 gives them (the 16 cells after the code).
ROWS = {
    ("MDP-FTS-NS", 8): ["Motor-Driven Pump Fails To Start,\nNormally Standby", "EPIX/RADS", "227", "410,593", "d",
                        "1311", "Beta", "EB/PL/KS", "1.09E-04", "4.96E-04", "5.88E-04", "1.38E-03", "2.070",
                        "3.520E+03", "2.8", "2006--2020"],
    ("MDP-FTR>1H", 8): ["Motor-Driven Pump FTR>1H", "EPIX/RADS", "92", "19,248,030", "h", "1311", "Gamma",
                        "EB/PL/KS", "3.58E-08", "3.77E-06", "8.12E-06", "3.10E-05", "0.511", "6.290E+04", "8.2",
                        "2006--2020"],
    ("AOV-ILL", 6): ["Air-Operated Valve Internal Leakage\n(Rupture)", "NUREG/CR-6928", "(note c)", "--", "h",
                     "8788", "Gamma", "JNID/IL", "6.85E-14", "1.56E-10", "6.40E-10", "2.93E-09", "0.300",
                     "4.688E+08", "18.8", "2006--2020"],
    ("CTF--FTR>1H", 14): ["Cooling Tower Fan Fails To Run >1H\n(Standby)", "EPIX/RADS", "0", "895,323", "h", "55",
                          "Gamma", "JNID/IL", "2.20E-09", "2.54E-07", "5.58E-07", "2.15E-06", "0.500", "8.950E+05",
                          "8.4", "2006--2020"],
}


@pytest.mark.parametrize("key", list(ROWS))
def test_the_importer_reproduces_the_shipped_records(key):
    code, page = key
    rec = importer.record_from_row(ROWS[key], code, page, "2026-10-23")
    assert rec == service.get(rec["id"])


def test_importer_rules():
    rate = importer.record_from_row(ROWS[("MDP-FTR>1H", 8)], "MDP-FTR>1H", 8, "2026-10-23")
    assert rate["units"]["time_basis"] == "operating" and rate["evidence"]["exposure"] == 19248030
    leak = importer.record_from_row(ROWS[("AOV-ILL", 6)], "AOV-ILL", 6, "2026-10-23")
    assert leak["units"]["time_basis"] == "calendar" and leak["evidence"]["failures"] is None
    assert any("note c" in n for n in leak["notes"])
    typo = importer.record_from_row(ROWS[("CTF--FTR>1H", 14)], "CTF--FTR>1H", 14, "2026-10-23")
    assert typo["source_code"] == "CTF-FTR>1H" and typo["id"] == f"{NRC}:ctf-ftr-gt1h"
    # A gamma row the table marks "d" is still a rate; a beta row marked "h" a demand probability.
    crd = _rec("CRD-FTOP")
    assert crd["kind"] == "rate" and any("d-or-h" in n for n in crd["notes"])
    ccw = _rec("MDP-FTS-CCW")
    assert ccw["kind"] == "per_demand" and any("d-or-h" in n for n in ccw["notes"])
    assert _rec("SVV-FTO-PWR-MSS")["source_text"] == "Safety Valve Fails To Open (Main Steam System, PWRs)"
    assert _rec("PIPE-SWS-ELS")["units"]["value"] == "per_hour_per_foot"
    point = ["Power-Operated Relief Valves Open During LOOP", "RV Update, Table", "--", "--", "d", "--",
             "Point Estimate", "Point Estimate", "--", "--", "9.23E-02", "--", "--", "--", "--", "1988--2020"]
    assert "point estimate" in importer.record_from_row(point, "PORV-LOOP", 10, "x").lower()
    skipped = json.loads((service.DATA_DIR / f"{NRC}.json").read_text())["skipped"]
    assert {s["code"] for s in skipped} == {"PORV-LOOP", "PORV-Transient", "HCU-FTI"}


# ---- search, get, sources ------------------------------------------------------------------------

def test_search_ranks_and_counts():
    out = service.search("motor-driven pump fails to start")
    assert out["total"] == 4 and out["page"] == 1 and out["pages"] == 1
    assert all(r["name"] == "Motor-driven pump" and r["failure_mode"] == "Fails to start" for r in out["results"])
    assert out["results"][0]["id"] == f"{NRC}:mdp-fts-ns"  # the source's order breaks ties
    # The component's name outranks a word only in the source's description.
    gen = service.search("diesel generator")["results"]
    assert gen[0]["name"] == "Emergency diesel generator"
    # The full code finds its record; every word must match; plurals and stop words don't matter.
    assert [r["id"] for r in service.search("MDP-FTS-NS")["results"]] == [f"{NRC}:mdp-fts-ns"]
    assert service.search("xyzzy")["total"] == 0
    assert service.search("pumps")["total"] == service.search("pump")["total"] == 41
    assert service.search("leak of the check valve")["total"] == 4
    leaks = service.search("leak", equipment_type="valve")
    assert leaks["total"] > 0 and all(r["equipment_type"] == "valve" for r in leaks["results"])
    # Counts are the query's matches before the filters narrow them.
    assert leaks["counts"]["equipment_type"]["valve"] == leaks["total"]
    assert sum(leaks["counts"]["equipment_type"].values()) > leaks["total"]
    row = service.search("MDP-FTR>1H")["results"][0]
    assert row["units"] == "per hour (running)" and row["distribution"] == "gamma(alpha=0.511, beta=62900.0)"
    assert row["citation"] == "INL/EXT-21-65055, Table 1, p. 8" and row["source"] == "NRC/INL 2020"


def test_search_pages():
    first = service.search(kind="per_demand", page_size=10)
    assert first["total"] == 89 and first["pages"] == 9 and len(first["results"]) == 10
    second = service.search(kind="per_demand", page=2, page_size=10)
    assert not {r["id"] for r in first["results"]} & {r["id"] for r in second["results"]}
    last = service.search(kind="per_demand", page=9, page_size=10)
    assert len(last["results"]) == 9
    assert service.search(kind="per_demand", page=10, page_size=10)["results"] == []
    seen = [r["id"] for p in range(1, 10) for r in service.search(kind="per_demand", page=p, page_size=10)["results"]]
    assert len(seen) == len(set(seen)) == 89
    browse = service.search(page_size=service.MAX_PAGE_SIZE)
    assert browse["total"] == N_NRC + N_MIL and browse["counts"]["source"] == {MIL: N_MIL, NRC: N_NRC}
    assert service.search(source=NRC)["results"][0]["id"] == f"{NRC}:aov-fto"


@pytest.mark.parametrize("kwargs, says", [
    ({"kind": "per_month"}, "Unknown kind"),
    ({"equipment_type": "spaceship"}, "Unknown equipment_type"),
    ({"source": "oreda"}, "Unknown source"),
    ({"page": 0}, "page starts at 1"),
    ({"page_size": 500}, "page_size must be 1 to 100"),
])
def test_search_refuses_bad_filters(kwargs, says):
    with pytest.raises(ValueError, match=says):
        service.search("pump", **kwargs)


def test_get_and_sources():
    d = service.detail(f"{NRC}:mdp-fts-ns")
    assert d["record"]["source_code"] == "MDP-FTS-NS" and d["units"] == "per demand"
    assert d["block_model"]["model"]["distribution_id"] == "binomial" and d["caveats"]
    assert "length_ft" in service.detail(f"{NRC}:pipe-sws-els")["block_model"]["needs"]
    with pytest.raises(service.LibraryNotFound):
        service.get("nope")
    src = service.sources()
    nrc = next(s for s in src["sources"] if s["id"] == NRC)
    assert nrc["records"] == N_NRC and src["total_records"] == N_NRC + N_MIL and nrc["components"] >= 70
    assert nrc["kinds"] == {"per_demand": 89, "rate": 211} and nrc["skipped"] == 3
    assert nrc["licence"]["id"] == "us-government-work" and "republished by Reliafy" in nrc["licence"]["attribution"]


# ---- conversions ---------------------------------------------------------------------------

def test_rate_to_exponential_matches_the_gamma():
    rec = _rec("MDP-FTR>1H")  # gamma(0.511, 6.29E+04) per hour of running
    a, b = 0.511, 6.29e4
    out = convert.rate_to_exponential(rec)
    assert out["model"] == {"distribution_id": "exponential", "params": [{"name": "failure_rate", "value": a / b}]}
    assert out["unit"] == "Hours" and out["time_basis"] == "operating"
    assert out["bounds"]["p05"] == pytest.approx(stats.gamma(a, scale=1 / b).ppf(0.05))
    assert out["bounds"]["p95"] == pytest.approx(stats.gamma(a, scale=1 / b).ppf(0.95))
    assert out["mean_time_to_failure"] == pytest.approx(b / a)
    assert out["source"]["id"] == rec["id"] and "Generic estimate" in out["badge"]
    per_year = convert.rate_to_exponential(rec, time_unit="years")
    assert per_year["failure_rate"] == pytest.approx(a / b * 8760) and per_year["unit"] == "Years"
    assert any("8,760" in x for x in per_year["assumptions"])
    median = convert.rate_to_exponential(rec, point="median")
    assert median["failure_rate"] == pytest.approx(stats.gamma(a, scale=1 / b).median())
    # The same failures on a calendar clock, for a pump that runs 2,000 hours a year.
    cal = convert.rate_to_exponential(rec, time_basis="calendar", operating_hours_per_year=2000)
    assert cal["failure_rate"] == pytest.approx(a / b * 2000 / 8760) and cal["time_basis"] == "calendar"


def test_calendar_rate_to_running_hours_needs_the_hours_a_year():
    rec = _rec("AOV-SOP")  # per calendar hour
    with pytest.raises(convert.ConversionError, match="operating_hours_per_year"):
        convert.rate_to_exponential(rec, time_basis="operating")
    out = convert.rate_to_exponential(rec, time_basis="operating", operating_hours_per_year=4380)
    assert out["failure_rate"] == pytest.approx(rec["summary"]["mean"] * 2, rel=5e-3)
    with pytest.raises(convert.ConversionError, match="0 to 8760"):
        convert.rate_to_exponential(rec, time_basis="operating", operating_hours_per_year=9000)
    with pytest.raises(convert.ConversionError, match="unit of time"):
        convert.rate_to_exponential(rec, time_unit="cycles")


def test_a_pipe_rate_needs_its_length():
    rec = _rec("PIPE-SWS-ELS")
    with pytest.raises(convert.ConversionError, match="length_ft"):
        convert.rate_to_exponential(rec)
    out = convert.rate_to_exponential(rec, length_ft=500)
    assert out["failure_rate"] == pytest.approx(0.5 / 7.256e8 * 500)
    with pytest.raises(convert.ConversionError, match="leave out length_ft"):
        convert.rate_to_exponential(_rec("MDP-FTR>1H"), length_ft=10)


def test_demand_probability_with_its_beta_spread():
    rec = _rec("EDG-FTS")  # beta(23.8, 1.07E+04): Table 1 mean 2.22E-03
    a, b = 23.8, 1.07e4
    out = convert.demand_to_per_demand(rec)
    assert out["probability"] == pytest.approx(a / (a + b))
    assert out["model"] == {"distribution_id": "binomial", "params": [{"name": "p", "value": a / (a + b)}]}
    assert out["bounds"]["p05"] == pytest.approx(stats.beta(a, b).ppf(0.05))
    assert out["bounds"]["p95"] == pytest.approx(stats.beta(a, b).ppf(0.95))
    assert out["start_success_probability"] == pytest.approx(1 - a / (a + b))
    assert "rate_model" not in out
    # Demanded 52 times a year: failures on demand as a rate in calendar time.
    weekly = convert.demand_to_per_demand(rec, demands_per_year=52, time_unit="years")
    assert weekly["rate_model"]["failure_rate"] == pytest.approx(a / (a + b) * 52)
    assert weekly["rate_model"]["time_basis"] == "calendar"
    with pytest.raises(convert.ConversionError, match="above 0"):
        convert.demand_to_per_demand(rec, demands_per_year=0)


def test_conversions_that_dont_fit_say_what_to_use():
    with pytest.raises(convert.ConversionError, match="Use demand_to_per_demand"):
        convert.rate_to_exponential(_rec("EDG-FTS"))
    with pytest.raises(convert.ConversionError, match="Use rate_to_exponential"):
        convert.demand_to_per_demand(_rec("EDG-FTR"))
    with pytest.raises(convert.ConversionError, match="isn't a life distribution"):
        convert.life_to_model(_rec("EDG-FTR"))
    with pytest.raises(convert.ConversionError, match="'mean' or 'median'"):
        convert.spread(_rec("EDG-FTR"), point="mode")


def test_spread_is_from_the_parameters():
    rec = _rec("AOV-FTC")  # an EB beta with a long tail: Table 1 error factor 6.4
    sp_ = convert.spread(rec)
    assert sp_["mean"] == pytest.approx(0.638 / (0.638 + 3380))
    assert sp_["error_factor"] == pytest.approx(rec["summary"]["error_factor"], rel=0.02)


# ---- the public routes ---------------------------------------------------------------------

@pytest.fixture()
def client(monkeypatch):
    from backend import config
    from backend.ratelimit import SlidingWindowLimiter
    from backend.routers import library as router

    monkeypatch.setattr(config, "AUTH_DISABLED", False)  # signed out, as on the cloud
    monkeypatch.setattr(router, "_LIMIT", SlidingWindowLimiter(1000))
    return TestClient(__import__("backend.main", fromlist=["app"]).app)


def test_public_routes_need_no_sign_in(client):
    r = client.get("/api/library/search", params={"q": "check valve", "kind": "rate", "page_size": 2})
    assert r.status_code == 200 and "public" in r.headers["cache-control"]
    body = r.json()
    assert body["total"] == 5 and len(body["results"]) == 2 and body["pages"] == 3
    assert client.get("/api/library/search", params={"kind": "weekly"}).status_code == 422
    r = client.get(f"/api/library/records/{NRC}:mdp-fts-ns")
    assert r.status_code == 200 and r.json()["record"]["licence"]["id"] == "us-government-work"
    assert client.get("/api/library/records/nope").status_code == 404
    assert client.get("/api/library/sources").json()["total_records"] == N_NRC + N_MIL


def test_public_routes_are_rate_limited(client, monkeypatch):
    from backend.ratelimit import SlidingWindowLimiter
    from backend.routers import library as router

    monkeypatch.setattr(router, "_LIMIT", SlidingWindowLimiter(2))
    assert client.get("/api/library/sources").status_code == 200
    assert client.get("/api/library/search").status_code == 200
    r = client.get("/api/library/search")
    assert r.status_code == 429 and r.headers["retry-after"] == "60"


# ---- MCP and /api/v1 ---------------------------------------------------------------------

@pytest.mark.usefixtures("mcp_on")
def test_the_library_tool_over_mcp_and_rest(env):
    token = env.oauth[FREE]  # a lookup: on the Free plan too, and never counted (below)
    found = _ok(_call(token, "library", {"action": "search", "query": "motor-driven pump", "kind": "rate",
                                         "page_size": 3}))
    assert found["data_notice"] and found["total"] > 3 and len(found["results"]) == 3
    one = _ok(_call(token, "library", {"action": "get", "id": found["results"][0]["id"]}))
    assert one["data_notice"] and one["record"]["licence"]["attribution"]
    assert one["block_model"]["model"]["distribution_id"] == "exponential"
    assert _ok(_call(token, "library", {"action": "sources"}))["total_records"] == N_NRC + N_MIL
    assert "not found" in _err(_call(token, "library", {"action": "get", "id": "nope"}))
    assert "Unknown equipment_type" in _err(_call(token, "library", {"action": "search",
                                                                     "equipment_type": "spaceship"}))
    assert "doesn't take" in _err(_call(token, "library", {"action": "sources", "query": "pump"}))

    api = TestClient(__import__("backend.main", fromlist=["app"]).app)
    r = api.post("/api/v1/library/search", json={"query": "check valve", "kind": "rate", "page_size": 2},
                 headers={"Authorization": f"Bearer {env.api[PRO]}"})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 5 and [x["id"] for x in body["results"]] == [
        x["id"] for x in service.search("check valve", kind="rate", page_size=2)["results"]]


# ---- MIL-HDBK-217F (Notice 2): handbook base rates with environment factors -------------

def _mil(key: str) -> dict:
    return service.get(f"{MIL}:{key}")


def _mils() -> list[dict]:
    return [r for r in _all() if r["source"] == MIL]


def test_mil_records_are_handbook_rates_kept_apart_from_field_data():
    for r in _mils():
        assert r["basis"] == "prediction_model" and r["kind"] == "rate"
        assert r["distribution"]["family"] == "point" and r["summary"]["p05"] is None
        assert r["units"] == {"value": "per_hour", "time_basis": "operating", "as_given": "failures per million hours"}
        pred = r["prediction"]
        assert pred["per_million_hours"] * 1e-6 == pytest.approx(r["summary"]["mean"], rel=1e-12)
        assert pred["formula"].startswith("λp") and isinstance(pred["not_applied"], list)
        if pred["not_applied"]:  # says plainly which of the handbook's factors aren't applied
            assert r["label"].endswith(": base failure rate") and "Base failure rate only" in r["notes"][0]
            assert all(f["symbol"] in pred["formula"] for f in pred["not_applied"])
        else:
            assert r["label"].endswith(": failure rate") and "whole model" in r["notes"][0]
        factors = r.get("environment_factors")
        if factors:
            assert set(factors["values"]) | set(factors["not_given"]) == set(schema.ENVIRONMENTS)
            assert factors["values"]["GB"] == 1.0  # every πE table is relative to ground, benign
    # Field data never carries a handbook's fields.
    assert not any("prediction" in r or "environment_factors" in r for r in _all() if r["source"] == NRC)
    with_env = [r for r in _mils() if r.get("environment_factors")]
    assert len(with_env) == N_MIL - 6  # six miscellaneous parts have a fixed rate with no factors


def test_mil_numbers_match_the_handbook():
    """Spot checks against the page images (failures per million hours)."""
    rc = _mil("9-1-rc-11")  # Notice 2, 9.1: RC (MIL-R-11) λb .0017; πE GF 4.0, CL 1728
    assert rc["prediction"]["per_million_hours"] == 0.0017 and rc["summary"]["mean"] == pytest.approx(1.7e-9)
    assert rc["environment_factors"]["values"]["GF"] == 4.0 and rc["environment_factors"]["values"]["CL"] == 1728
    assert rc["citation"]["page"] == "9-1, 9-3" and rc["citation"]["document"] == "Notice 2"
    assert [f["symbol"] for f in rc["prediction"]["not_applied"]] == ["πT", "πP", "πS", "πQ"]
    assert rc["prediction"]["quality_factor_range"] == [0.03, 10]
    ct = _mil("10-1-ct-92")  # 10.1: CT λb .0000072, on the table's second page
    assert ct["prediction"]["per_million_hours"] == 7.2e-6 and ct["citation"]["page"] == "10-2, 10-5"
    assert ct["environment_factors"]["values"]["CL"] == 570
    jfet = _mil("6-4-jfet")  # Revision F, 6.4 (unchanged by the notices): λb .0045
    assert jfet["prediction"]["per_million_hours"] == 0.0045 and jfet["citation"]["document"] == "Revision F"
    etm = _mil("12-3-a-c")  # 12.3: A.C. λb 20; πE CL N/A
    assert etm["environment_factors"]["not_given"] == ["CL"] and "CL" not in etm["environment_factors"]["values"]
    crimp = _mil("17-1-crimp")  # 17.1: λp = λb πE, the whole model
    assert crimp["prediction"]["not_applied"] == [] and crimp["environment_factors"]["values"]["NU"] == 11
    vib = _mil("23-1-vibrator-mil-v-95-60-cycle")
    assert vib["prediction"]["per_million_hours"] == 15 and "environment_factors" not in vib


def test_the_mil_importer_reproduces_the_shipped_records():
    assert mil_importer.records("2026-10-23") == _mils()
    data = json.loads((service.DATA_DIR / f"{MIL}.json").read_text(encoding="utf-8"))
    src = data["source"]
    assert src["basis"] == "prediction_model" and "Distribution Statement A" in src["licence"]["attribution"]
    assert {d["file"] for d in src["documents"]} == set(src["sha256"]) == {
        "MIL-HDBK-217F.pdf", "MIL-HDBK-217F-NOTICE-2.pdf"}
    assert all(len(d["content_sha256"]) == 64 for d in src["documents"])
    skipped = {s["what"] for s in data["skipped"]}
    assert len(data["skipped"]) == len(mil_importer.SKIPPED) and all(s["reason"] for s in data["skipped"])
    assert "Relays, mechanical" in skipped and any(w.startswith("Microcircuits") for w in skipped)


def test_mil_importer_rules():
    plain = mil_importer.plain
    assert plain("Resistor, Fixed, Film (Power Type)") == "resistor, fixed, film (power type)"
    assert plain("Resistor, Fixed, Wirewound (Accurate) Est. Rel.") == (
        "resistor, fixed, wirewound (accurate) established reliability")
    assert plain("Si IMPATT (≤ 35 GHz)") == "Si IMPATT (≤ 35 GHz)"
    assert plain("Capacitor, Fixed Electrolytic (DC, Aluminum, Dry Electrolyte, Polarized)") == (
        "capacitor, fixed electrolytic (DC, aluminium, dry electrolyte, polarised)")
    assert _mil("10-1-ce-62")["name"] == "Capacitor, fixed electrolytic (DC, aluminium, dry electrolyte, polarised)"
    assert mil_importer.slug("100W to ≤ 1000W") == "100w-to-le-1000w"
    caps = next(g for g in mil_importer.GROUPS if g["section"] == "10.1")
    assert mil_importer.rate_page(caps, 12)[1] == "10-1" and mil_importer.rate_page(caps, 13)[1] == "10-2"
    assert caps["parts"][13][0] == "CK"
    # The download stamp ASSIST adds to every page is left out of the fingerprint; the page itself isn't.
    page = [b"q /im1 Do Q", b"BT (Source: https://assist.dla.mil -- Downloaded: 2026-10-23T09:25Z) Tj ET",
            b"BT (Check the source to verify that this is the current version before use.) Tj ET"]
    assert mil_importer.without_stamp(page) == [b"q /im1 Do Q"]
    assert mil_importer.numbers_in("CL 1720 ML 1,0 .0017 x") == {1720.0, 1.0, 0.0017}


def _ocr_fixture() -> dict:
    """Page texts holding every typed number, as a clean OCR would read them."""
    texts: dict = {}
    for g in mil_importer.GROUPS:
        for i, part in enumerate(g["parts"]):
            doc, _, pdf_page = mil_importer.rate_page(g, i)
            texts[(doc, pdf_page)] = texts.get((doc, pdf_page), "") + f" {part[3]}"
        for v in g["env_values"] or ():
            if v is not None:
                texts[(g["env"][0], g["env"][2])] = texts.get((g["env"][0], g["env"][2]), "") + f" {v}"
    return texts


def test_mil_importer_checks_each_typed_number_on_its_page(monkeypatch):
    texts = _ocr_fixture()
    assert mil_importer.ocr_problems(texts) == []
    # A number the page doesn't show is caught, unless it's a misread checked by eye.
    texts[("N2", 34)] = texts[("N2", 34)].replace("1728", "1720")
    assert mil_importer.ocr_problems(texts) == []  # listed in OCR_MISREADS
    monkeypatch.setattr(mil_importer, "OCR_MISREADS", {})
    assert mil_importer.ocr_problems(texts) == ["N2 p. 9-3 (PDF page 34): 1728 isn't in the page's text"]


@pytest.mark.parametrize("break_it, says", [
    (lambda r: r.pop("prediction"), "prediction.formula"),
    (lambda r: r["prediction"].update(not_applied=[{"symbol": "πT"}]), "not_applied"),
    (lambda r: r["prediction"].update(per_million_hours=0.0018), "disagrees with the value"),
    (lambda r: r["environment_factors"]["values"].update(XX=2.0), "unknown environments XX"),
    (lambda r: r["environment_factors"]["values"].update(GF=0), "environment factor GF"),
    (lambda r: r.update(basis="field_data"), "only a prediction model has environment_factors"),
    (lambda r: r["licence"].update(attribution=""), "attribution"),
    (lambda r: r["citation"].pop("page"), "citation is missing page"),
])
def test_a_handbook_record_that_cant_ship_is_caught(break_it, says):
    rec = copy.deepcopy(_mil("9-1-rc-11"))
    assert schema.problems(rec) == []
    break_it(rec)
    found = schema.problems(rec)
    assert found and any(says in p for p in found), found


def test_search_mil_by_part_and_environment():
    resistors = service.search("resistor", equipment_type="resistor", page_size=100)
    assert resistors["total"] == 27 and all(r["source"] == "MIL-HDBK-217F N2" for r in resistors["results"])
    assert service.search("RCR")["results"][0]["id"] == f"{MIL}:9-1-rcr-39008"  # the style, as a code
    assert service.search("tantalum capacitor")["total"] == 5
    # An environment's name or symbol finds the parts with a factor for it: never field data.
    naval = service.search("naval sheltered", page_size=100)
    expect = sum(1 for r in _mils() if "NS" in (r.get("environment_factors") or {}).get("values", {}))
    assert naval["total"] == expect == N_MIL - 6 and naval["counts"]["source"] == {MIL: expect}
    assert service.search("capacitor missile launch")["total"] == 28
    assert service.search("elapsed time meter cannon launch")["total"] == 0  # its CL is N/A
    assert service.search("elapsed time meter ML")["total"] == 3
    row = service.search("crimp connection")["results"][0]
    assert row["environment_factors"]["NU"] == 11 and row["units"] == "per hour (running)"
    assert row["distribution"] == "point(value=2.6e-10)" and row["basis"] == "prediction_model"
    assert "environment_factors" not in service.search("MDP-FTS-NS")["results"][0]


def test_mil_rate_times_environment_factor():
    rc = _mil("9-1-rc-11")  # λb .0017 per million hours; πE GF 4.0
    out = convert.rate_to_exponential(rc, environment="GF")
    assert out["failure_rate"] == pytest.approx(0.0017 * 4.0 / 1e6)  # 6.8E-9 per hour
    assert out["model"] == {"distribution_id": "exponential",
                            "params": [{"name": "failure_rate", "value": out["failure_rate"]}]}
    assert out["environment"] == {"code": "GF", "name": "Ground, fixed", "factor": 4.0}
    assert out["bounds"] == {"p05": None, "p95": None} and out["time_basis"] == "operating"
    assert out["mean_time_to_failure"] == pytest.approx(1e6 / 0.0068)
    said = out["assumptions"][0]
    assert "0.0017 per million hours × πE 4" in said and "πT (temperature)" in said and "πQ (quality)" in said
    assert "Handbook prediction" in out["badge"]
    per_year = convert.rate_to_exponential(rc, environment="gf", time_unit="years")  # any case
    assert per_year["failure_rate"] == pytest.approx(0.0068e-6 * 8760)
    # Running 4,380 hours a year, on a calendar clock: half the rate per calendar hour.
    cal = convert.rate_to_exponential(rc, environment="GF", time_basis="calendar", operating_hours_per_year=4380)
    assert cal["failure_rate"] == pytest.approx(0.0068e-6 / 2)
    # Hand checks across sections: crimp .00026 × NU 11; fuse .010 × CL 230; CDR .0020 × ML 50;
    # LED .00023 × SF .50; A.C. elapsed time meter 20 × GM 12.
    for key, env, per_million in (("17-1-crimp", "NU", 0.00286), ("22-1-fuse", "CL", 2.3),
                                  ("10-1-cdr-55681", "ML", 0.1), ("6-11-emitter-light-emitting-diode-led", "SF",
                                                                  0.000115), ("12-3-a-c", "GM", 240)):
        got = convert.rate_to_exponential(_mil(key), environment=env)["failure_rate"]
        assert got == pytest.approx(per_million / 1e6), key
    crimp = convert.rate_to_exponential(_mil("17-1-crimp"), environment="NU")
    assert "whole model" in crimp["assumptions"][0]
    vib = convert.rate_to_exponential(_mil("23-1-vibrator-mil-v-95-60-cycle"))  # a fixed rate: no environment
    assert vib["failure_rate"] == pytest.approx(15e-6) and "environment" not in vib


def test_mil_conversions_say_what_to_supply():
    rc = _mil("9-1-rc-11")
    with pytest.raises(convert.ConversionError, match="give environment, one of GB \\(ground, benign\\)"):
        convert.rate_to_exponential(rc)
    with pytest.raises(convert.ConversionError, match="Unknown environment 'Mars'"):
        convert.rate_to_exponential(rc, environment="Mars")
    with pytest.raises(convert.ConversionError, match="no environment factor for CL"):
        convert.rate_to_exponential(_mil("12-3-a-c"), environment="CL")
    with pytest.raises(convert.ConversionError, match="leave out environment"):
        convert.rate_to_exponential(_mil("23-1-vibrator-mil-v-95-60-cycle"), environment="GB")
    with pytest.raises(convert.ConversionError, match="leave out environment"):
        convert.to_block_model(_rec("EDG-FTS"), environment="GB")
    with pytest.raises(convert.ConversionError, match="leave out environment"):
        convert.rate_to_exponential(_rec("EDG-FTR"), environment="GB")
    # detail: without an environment, the rate in each one and what to give; with one, the block model.
    d = service.detail(rc["id"])
    assert "give environment" in d["block_model"]["needs"] and len(d["environments"]) == 14
    assert d["environments"][1] == {"code": "GF", "name": "Ground, fixed", "factor": 4.0,
                                    "failure_rate_per_hour": pytest.approx(6.8e-9)}
    assert service.detail(rc["id"], environment="NS")["block_model"]["failure_rate"] == pytest.approx(12 * 1.7e-9)
    with pytest.raises(ValueError, match="Unknown environment"):
        service.detail(rc["id"], environment="XX")
    with pytest.raises(ValueError, match="leave out environment"):
        service.detail(f"{NRC}:mdp-fts-ns", environment="GB")
    assert "environments" not in service.detail(f"{NRC}:mdp-fts-ns")
    assert set(service.sources()["environments"]) == set(schema.ENVIRONMENTS)


def test_mil_source_and_public_route(client):
    mil = next(s for s in service.sources()["sources"] if s["id"] == MIL)
    assert mil["records"] == N_MIL and mil["basis"] == "prediction_model" and mil["skipped"] == 19
    assert mil["licence"]["id"] == "us-government-work" and mil["kinds"] == {"rate": N_MIL}
    r = client.get(f"/api/library/records/{MIL}:9-1-rc-11", params={"environment": "AIC"})
    assert r.status_code == 200 and r.json()["block_model"]["failure_rate"] == pytest.approx(18 * 1.7e-9)
    r = client.get(f"/api/library/records/{MIL}:9-1-rc-11", params={"environment": "XX"})
    assert r.status_code == 422 and "Unknown environment" in r.json()["detail"]
    assert "needs" in client.get(f"/api/library/records/{MIL}:9-1-rc-11").json()["block_model"]


# ---- the Free allowance: library lookups are never counted ---------------------------------

@pytest.mark.usefixtures("mcp_on")
def test_library_lookups_are_never_counted(env, monkeypatch):
    """Lookups aren't calculations: on every plan, library search / get /
    sources don't use the Free plan's monthly calls (or a grandfathered Agent
    plan's daily ones), and still work once the allowance is used up."""
    from backend import config
    from backend.tests.test_mcp_plans import AGENT, _calls_used

    monkeypatch.setattr(config, "MCP_FREE_MONTHLY_CALLS", 1)
    token = env.oauth[FREE]
    for _ in range(3):
        _ok(_call(token, "library", {"action": "search", "query": "resistor"}))
    _ok(_call(token, "library", {"action": "get", "id": f"{MIL}:9-1-rc-11", "environment": "GB"}))
    _ok(_call(token, "library", {"action": "sources"}))
    assert "not found" in _err(_call(token, "library", {"action": "get", "id": "nope"}))
    assert _calls_used(env.db, FREE) == 0
    _ok(_call(token, "list", {"kind": "models"}))  # the month's one call
    assert "this month's 1 free" in _err(_call(token, "list", {"kind": "models"}))
    out = _ok(_call(token, "library", {"action": "get", "id": f"{MIL}:9-1-rc-11", "environment": "GF"}))
    assert out["block_model"]["failure_rate"] == pytest.approx(6.8e-9)  # past the allowance, still there
    assert _calls_used(env.db, FREE) == 1
    agent = env.oauth[AGENT]
    _ok(_call(agent, "library", {"action": "search", "query": "capacitor"}))
    assert _calls_used(env.db, AGENT, "agent") == 0


@pytest.mark.usefixtures("mcp_on")
def test_the_library_environment_over_mcp_and_rest(env):
    one = _ok(_call(env.oauth[PRO], "library", {"action": "get", "id": f"{MIL}:17-1-crimp", "environment": "NU"}))
    assert one["block_model"]["failure_rate"] == pytest.approx(0.00286e-6)
    assert "Unknown environment" in _err(_call(env.oauth[PRO], "library", {"action": "get",
                                                                          "id": f"{MIL}:17-1-crimp",
                                                                          "environment": "XX"}))
    api = TestClient(__import__("backend.main", fromlist=["app"]).app)
    r = api.post("/api/v1/library/get", json={"id": f"{MIL}:9-1-rc-11", "environment": "GF"},
                 headers={"Authorization": f"Bearer {env.api[PRO]}"})
    assert r.status_code == 200 and r.json()["block_model"]["environment"]["factor"] == 4.0
