"""NSWC-11 as a library of covariate models: the shipped data (in step with the chapter modules,
every record checked with the records it uses, every input limited), the evaluator (safe, limits
that refuse or warn with the page), the library's reads and its public evaluate route, the MCP
read with conditions, and a reliability prediction with NSWC-11 lines. Each chapter's own models
are tested against the handbook in test_library_nswc11_chNN.py."""

import math

import pytest
from fastapi.testclient import TestClient

from backend.library import convert, covariate, schema
from backend.library import service as library
from backend.scripts import build_nswc11
from backend.services import reliability_prediction as rp

NSWC = "nswc-11"
BEARING = "nswc-11:bearing-rolling-load-rating"
CHAPTERS = set(range(3, 24))


def _records():
    return [r for r in library._library()["records"] if r["source"] == NSWC]


# ---- the shipped data ------------------------------------------------------------------------

def test_the_data_file_is_what_the_chapter_modules_build():
    assert build_nswc11.main(["--check"]) == 0


def test_every_record_may_ship_with_the_records_it_uses():
    records = _records()
    assert records
    for r in records:
        assert schema.problems(r) == [] and covariate.problems(r, library.resolve) == [], r["id"]
        assert r["kind"] == "covariate_model" and r["basis"] == "prediction_model"
        assert r["citation"]["page"] and r["citation"]["equation"] and r["citation"]["chapter"] in CHAPTERS
        assert "did not take part" in r["licence"]["attribution"]
        # Every input of every model it reads (its parts' too) carries its unit and limits.
        for i in covariate.inputs(r, library.resolve):
            assert i["role"] in covariate.ROLES, (r["id"], i["key"])
            if i["kind"] == "number":
                assert "unit" in i and i["limits"], (r["id"], i["key"])
            if i.get("default") is not None:
                assert i["default_basis"] in ("handbook", "neutral", "typical"), (r["id"], i["key"])


def test_the_source_carries_the_navys_statement():
    src = next(s for s in library.sources()["sources"] if s["id"] == NSWC)
    assert "did not take part" in src["disclaimer"] and "not an official DoD document" in src["disclaimer"]
    assert src["disclaimer"] in src["caveats"] and "did not take part" in src["licence"]["note"]
    assert src["basis"] == "prediction_model" and src["records"] == len(_records())


# ---- the evaluator ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", ["__import__('os')", "x.real", "open('f')", "[i for i in x]", "lambda: 1",
                                  "x[0]", "f(x=1)", "True"])
def test_expressions_refuse_anything_but_arithmetic(text):
    with pytest.raises(covariate.ExpressionError):
        covariate.parse(text)


def test_expressions_compute():
    scope = {"a": 2.0, "kind": "ball"}
    assert covariate.evaluate_expr("3.0 if kind == 'ball' else 3.3", scope) == 3.0
    assert covariate.evaluate_expr("exp(ln(a)) * max(1, a) + interp(1.5, [1, 2], [10, 20])", scope) == pytest.approx(19)
    assert covariate.evaluate_expr("1 < a <= 2 and not a > 5", scope) is True
    assert covariate.names_in("exp(a) + b") == {"a", "b"}


def _model(**over):
    rec = {"id": "t:m", "name": "Test part", "kind": "covariate_model", "covariate_model": {
        "equation": "1-1", "page": "1-1", "formula": "λ = λB · C", "words": "w", "rate_unit": "per_million_hours",
        "inputs": [{"name": "x", "kind": "number", "label": "Load", "unit": "lbf", "role": "use",
                    "limits": [{"min": 0, "exclusive": True, "severity": "refuse", "why": "a load is positive"},
                               {"max": 10, "severity": "warn", "page": "1-2", "why": "Figure 1.1 covers 0 to 10"}]},
                   {"name": "k", "kind": "choice", "label": "Kind", "default": "a", "default_basis": "typical", "role": "design",
                    "choices": [{"code": "a", "label": "A"}, {"code": "b", "label": "B"}]}],
        "modes": [{"key": "m", "name": "Wear", "base": {"symbol": "λB", "value": 2.0, "page": "1-1"},
                   "factors": [{"symbol": "C_x", "name": "Load", "expr": "x ** 2", "page": "1-1"},
                               {"symbol": "C_k", "name": "Kind", "table": {"by": "k", "values": {"a": 1.0, "b": None}},
                                "page": "1-3"}]}]}}
    rec["covariate_model"].update(over)
    return rec


def test_a_model_is_its_base_times_its_factors():
    rec = _model()
    assert covariate.problems(rec) == []
    out = covariate.evaluate(rec, {"x": 3})
    assert out["total"] == 18 and out["warnings"] == [] and out["unit"] == "per_million_hours"
    assert [f["value"] for f in out["modes"][0]["factors"]] == [9, 1.0]


def test_limits_refuse_or_warn_and_say_where():
    rec = _model()
    out = covariate.evaluate(rec, {"x": 12})
    assert out["warnings"] == ["Load is 12 lbf; the handbook's range is at most 10 lbf: Figure 1.1 covers 0 to 10 "
                               "(NSWC-11 p. 1-2)."]
    with pytest.raises(covariate.CovariateError) as err:
        covariate.evaluate(rec, {"x": 0, "k": "z", "y": 1})
    words = err.value.problems
    assert any(p.startswith("Unknown input y") for p in words)
    assert "Load is 0 lbf; must be more than 0 lbf: a load is positive." in words
    assert "Kind must be one of a, b, not 'z'." in words
    with pytest.raises(covariate.CovariateError, match="Load is needed, in lbf"):
        covariate.evaluate(rec, {})
    with pytest.raises(covariate.CovariateError, match="gives no value for this combination"):
        covariate.evaluate(rec, {"x": 1, "k": "b"})
    with pytest.raises(covariate.CovariateError, match="Not a number|must be a number"):
        covariate.evaluate(rec, {"x": "lots"})


def test_a_model_that_reads_a_name_it_doesnt_have_is_refused():
    bad = _model(modes=[{"key": "m", "name": "Wear", "base": {"symbol": "λB", "expr": "q * 2", "page": "1"}}])
    assert any("reads q" in p for p in covariate.problems(bad))


def test_a_mode_that_uses_another_record_namespaces_its_inputs():
    part = _model()
    whole = {"id": "t:w", "name": "Assembly", "kind": "covariate_model", "covariate_model": {
        "equation": "1-2", "page": "1-2", "formula": "λ = n λ_part + 0.5", "words": "w", "rate_unit": "per_million_hours",
        "inputs": [{"name": "n", "kind": "number", "label": "How many", "unit": "", "default": 2, "default_basis": "handbook",
                    "role": "design",
                    "limits": [{"min": 0, "severity": "refuse"}]}],
        "modes": [{"key": "part", "name": "Parts", "uses": "t:m", "count": "n"},
                  {"key": "casing", "name": "Casing", "base": {"symbol": "λC", "value": 0.5, "page": "1-2"}}]}}
    resolve = {"t:m": part}.__getitem__
    assert covariate.problems(whole, resolve) == []
    assert [i["key"] for i in covariate.inputs(whole, resolve)] == ["n", "part.x", "part.k"]
    out = covariate.evaluate(whole, {"part.x": 1}, resolve)
    assert out["total"] == 2 * 2.0 + 0.5 and out["modes"][0]["parts"]["total"] == 2.0
    with pytest.raises(covariate.CovariateError, match=r"Load \(Parts\) is needed") as err:
        covariate.evaluate(whole, {}, resolve)
    assert err.value.missing == ["part.x"]  # what a partial set still needs, by key
    assert [i["key"] for i in covariate.open_inputs(whole, {"n": 2}, resolve)] == ["part.x", "part.k"]
    # None of the part: it adds nothing and its inputs aren't needed.
    assert covariate.evaluate(whole, {"n": 0}, resolve)["total"] == 0.5


# ---- the library's reads ----------------------------------------------------------------------

def test_search_detail_and_evaluate():
    both = library.search("bearing", source=f"mil-hdbk-217f-n2,{NSWC}", page_size=100)
    assert {r["id"].split(":")[0] for r in both["results"]} <= {"mil-hdbk-217f-n2", NSWC}
    assert any(r["id"].startswith(NSWC) for r in both["results"])
    with pytest.raises(ValueError):
        library.search("x", source="mil-hdbk-217f-n2,nope")
    found = library.search("bearing", source=NSWC)
    assert found["total"] >= 2 and found["results"][0]["covariate"]["rate_unit"] == "per_million_hours"
    assert library.search(kind="covariate_model")["total"] == len(_records())
    d = library.detail(BEARING)
    assert "covariate model" in d["block_model"]["needs"] and d["covariate"]["inputs"] and d["disclaimer"]
    ok = library.evaluate(BEARING, {"L_S": 5000, "F_R": 1000, "n": 1800})
    assert ok["ok"] and ok["result"]["total"] > 0 and "did not take part" in ok["disclaimer"]
    no = library.evaluate(BEARING, {"L_S": 5000})
    assert not no["ok"] and any("p. 7-" in p for p in no["problems"])
    with pytest.raises(ValueError, match="isn't a covariate model"):
        library.evaluate("nrc-inl-2020:mdp-fts-ns", {})
    with pytest.raises(convert.ConversionError):
        convert.to_block_model(library.get(BEARING))
    assert not library.usable_as(library.get(BEARING), "model")


@pytest.fixture()
def client(monkeypatch):
    from backend import config
    from backend.ratelimit import SlidingWindowLimiter
    from backend.routers import library as router

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(router, "_LIMIT", SlidingWindowLimiter(1000))
    return TestClient(__import__("backend.main", fromlist=["app"]).app)


def test_the_public_evaluate_route(client):
    r = client.post(f"/api/library/records/{BEARING}/evaluate", json={"values": {"L_S": 5000, "F_R": 1000, "n": 1800, "T_O": 300}})
    assert r.status_code == 200 and r.json()["ok"] and "p. 7-17" in " ".join(r.json()["warnings"])
    r = client.post(f"/api/library/records/{BEARING}/evaluate", json={"values": {"n": -1}})
    assert r.status_code == 200 and not r.json()["ok"]
    assert client.post("/api/library/records/nope/evaluate", json={"values": {}}).status_code == 404
    assert client.post("/api/library/records/nrc-inl-2020:mdp-fts-ns/evaluate", json={"values": {}}).status_code == 422
    assert client.get(f"/api/library/records/{BEARING}").json()["covariate"]["inputs"]


def test_the_library_record_over_mcp_takes_conditions(env, mcp_on):  # noqa: F811 - fixtures
    from backend.tests.test_mcp import _ok
    from backend.tests.test_mcp_plans import PRO, _call

    token = env.oauth[PRO]
    one = _ok(_call(token, "get", {"kind": "library_record", "id": BEARING, "conditions": {"L_S": 5000, "F_R": 1000, "n": 1800}}))
    assert one["evaluation"]["ok"] and one["evaluation"]["result"]["total"] > 0
    found = _ok(_call(token, "list", {"kind": "library", "record_kind": "covariate_model", "page_size": 3}))
    assert found["total"] == len(_records())


from backend.tests.test_mcp_plans import env  # noqa: E402,F401 - the fixture


# ---- a prediction with NSWC-11 lines -----------------------------------------------------------

def test_a_prediction_with_nswc_lines():
    cond = {"L_S": 5000, "F_R": 1000, "n": 1800}
    alone = library.evaluate(BEARING, cond)["result"]["total"]
    out = rp.compute([
        {"name": "Bearing", "quantity": 2, "record_id": BEARING, "conditions": cond},
        {"name": "Spare bearing", "record_id": BEARING},
        {"name": "Diode", "record_id": "mil-hdbk-217f-n2:6-1-general-purpose-analog"},
    ])
    by = {ln["name"]: ln for ln in out["lines"]}
    assert by["Bearing"]["rate_per_million_hours"] == pytest.approx(2 * alone)
    assert by["Bearing"]["handbook"] == "NSWC-11" and by["Diode"]["handbook"] == "MIL-HDBK-217F N2"
    assert by["Spare bearing"]["needs_conditions"] and not by["Spare bearing"]["assigned"]
    assert out["counts"]["needs_conditions"] == 1 and out["needs_conditions"][0]["name"] == "Spare bearing"
    assert out["failure_rate_per_million_hours"] == pytest.approx(2 * alone + by["Diode"]["rate_per_million_hours"])
    assert "NSWC-11 lines (Bearing)" in out["method"] and "MIL-HDBK-217F N2 lines (Diode)" in out["method"]
    assert "did not take part" in out["disclaimer"]
    assert {s["id"] for s in out["sources"]} == {NSWC, "mil-hdbk-217f-n2"}
    with pytest.raises(rp.PredictionError, match="no quality factor"):
        rp.compute([{"name": "B", "record_id": BEARING, "conditions": cond, "quality_factor": 2}])
    with pytest.raises(rp.PredictionError, match="conditions go with"):
        rp.compute([{"name": "B", "conditions": cond}])
    # A mechanical-only prediction says nothing of MIL-HDBK-217F's factors in its method.
    only = rp.compute([{"name": "Bearing", "record_id": BEARING, "conditions": cond}])
    assert only["handbooks"] == [{"source": NSWC, "short_name": "NSWC-11", "lines": ["Bearing"]}]
    assert math.isfinite(only["mtbf_hours"])


def test_a_rate_per_cycle_needs_the_cycles_an_hour():
    per_cycle = next((r for r in _records() if covariate.per_cycle(r)
                      and all(i.get("default") is not None for i in covariate.inputs(r, library.resolve))), None)
    if per_cycle is None:
        pytest.skip("no per-cycle model computes on its defaults alone")
    each = library.evaluate(per_cycle["id"], {})["result"]["total"]
    out = rp.compute([{"name": "Part", "record_id": per_cycle["id"]}])
    assert out["lines"][0]["needs_conditions"] and "an hour" in out["lines"][0]["line_warnings"][0]
    out = rp.compute([{"name": "Part", "record_id": per_cycle["id"], "cycles_per_hour": 30}])
    assert out["failure_rate_per_million_hours"] == pytest.approx(each * 30)
