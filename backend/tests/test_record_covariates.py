"""Every input a library record needs is a covariate of the record (backend/library/record_covariates.py),
handled by the one mechanism NSWC-11, ALT and PH already use: the evaluator per record kind, the
NRC/INL components (backend/library/components.py), the prior path, old saved data read as fixed
covariates, positions and RBD blocks, and the API."""

import math

import mongomock
import pytest

from backend.library import components, convert, covariate, schema
from backend.library import record_covariates as rc
from backend.library import service as library
from backend.maintenance import covariate_positions as cp
from backend.maintenance import library_models as lm
from backend.maintenance import position_models as pm
from backend.maintenance.service import PROJECTORS, Invalid, Maintenance
from backend.maintenance.store import GraphStore
from backend.services import covariate_binding as cb
from backend.services import models as models_service
from backend.services import rbd_analysis, rbds
from backend.services import reliability_prediction as rp

ORG = "org-reccov"
OWNERS = [ORG, "__samples__"]
PIPE = "nrc-inl-2020:pipe-sws-els"  # gamma per hour per foot, calendar
DEMAND = "nrc-inl-2020:aov-fto"  # beta per demand
MIL = "mil-hdbk-217f-n2"
BEARING = "nswc-11:bearing-rolling-load-rating"
COND = {"L_S": 5000, "F_R": 1000, "n": 1800}
STANDBY_PUMP = "nrc-inl-2020:component:motor-driven-pump-normally-standby"


def _id(code: str) -> str:
    """A record id by its source code (ids are lower case)."""
    return next(r["id"] for r in library._library()["records"] if r.get("source_code") == code)


def _mean(rid: str) -> float:
    rec = library.get(rid)
    return schema.mean_of(rec["distribution"]["family"], schema.param_dict(rec["distribution"]))


@pytest.fixture()
def m():
    return Maintenance(GraphStore(":memory:", PROJECTORS), ORG, "tester")


@pytest.fixture()
def db():
    from backend.services import samples

    d = mongomock.MongoClient()["record_covariates"]
    samples.seed_samples(d)
    return d


# ---- the evaluator, per kind of record -------------------------------------------------------

def test_every_record_declares_its_covariates_in_the_one_shape():
    keys = {"key", "name", "label", "kind", "role", "limits", "help", "group", "unit"}
    for rec in library._library()["records"]:
        for i in rc.inputs(rec):
            # NSWC-11's own inputs keep the handbook's shape (a choice has no unit or limits).
            assert (keys if rec["kind"] != "covariate_model" else {"key", "name", "label", "kind", "role"}) <= set(i), (rec["id"], i["key"])
            assert i["role"] in ("design", "use", "environment"), (rec["id"], i["key"])
            if i["kind"] == "choice":
                assert i["choices"], (rec["id"], i["key"])
    pipe = {i["key"]: i for i in rc.inputs(library.get(_id("PIPE-SWS-ELS")))}
    assert set(pipe) == {"length_ft", "clock", "running_hours_per_year"} and pipe["length_ft"]["role"] == "design"
    assert pipe["running_hours_per_year"]["needed_if"] == {"clock": ["operating"]}
    assert [i["key"] for i in rc.inputs(library.get(DEMAND))] == ["demands_per_year"]
    by_env = sum(1 for r in library._library()["records"] if r["source"] == MIL
                 and any(i["key"] == "environment" for i in rc.inputs(r)))
    grades = sum(1 for r in library._library()["records"] if r["source"] == MIL
                 and any(i["key"] == "quality" for i in rc.inputs(r)))
    assert (by_env, grades) == (230, 65)


def test_a_pipe_is_its_rate_per_foot_times_its_length():
    pipe = library.get(_id("PIPE-SWS-ELS"))
    got = rc.evaluate(pipe, {"length_ft": 120})
    assert got["failure_rate"] == pytest.approx(_mean(pipe["id"]) * 120, rel=1e-12)
    assert got["scale"] == pytest.approx(120) and got["rate_uncertainty"]["length_ft"] == 120
    with pytest.raises(rc.RecordCovariateError) as err:
        rc.evaluate(pipe, {})
    assert err.value.missing == ["length_ft"] and "Pipe length is needed" in str(err.value)
    # The old argument is an alias: the same number.
    old = convert.to_block_model(pipe, length_ft=120)
    assert old["failure_rate"] == got["failure_rate"]


def test_a_rate_changes_clock_only_with_the_hours_it_runs():
    run = library.get(_id("MDP-FTR>1H"))  # per hour of running
    lam = _mean(run["id"])
    assert rc.evaluate(run, {})["failure_rate"] == pytest.approx(lam)  # its own clock by default
    with pytest.raises(rc.RecordCovariateError) as err:
        rc.evaluate(run, {"clock": "calendar"})
    assert err.value.missing == ["running_hours_per_year"]
    cal = rc.evaluate(run, {"clock": "calendar", "running_hours_per_year": 4380})
    assert cal["failure_rate"] == pytest.approx(lam * 4380 / 8760) and cal["clock"] == "calendar"
    leak = library.get(_id("MDP-ELS"))  # per calendar hour
    per_run = rc.evaluate(leak, {"clock": "operating", "running_hours_per_year": 2190})
    assert per_run["failure_rate"] == pytest.approx(_mean(leak["id"]) * 8760 / 2190)
    # Running hours given with the record's own clock aren't used (as before), and say so.
    same = rc.evaluate(run, {"running_hours_per_year": 100})
    assert same["failure_rate"] == pytest.approx(lam) and any("isn't used" in w for w in same["warnings"])
    with pytest.raises(rc.RecordCovariateError, match="at most 8760"):
        rc.evaluate(run, {"clock": "calendar", "running_hours_per_year": 9000})
    # The old arguments: the same number.
    old = convert.rate_to_exponential(run, time_basis="calendar", operating_hours_per_year=4380)
    assert old["failure_rate"] == pytest.approx(cal["failure_rate"], rel=1e-12)


def test_a_probability_per_demand_is_a_rate_with_its_demands_a_year():
    rec = library.get(DEMAND)
    q = _mean(DEMAND)
    alone = rc.evaluate(rec, {}, require_rate=False)
    assert alone["probability"] == pytest.approx(q) and "failure_rate" not in alone
    with pytest.raises(rc.RecordCovariateError) as err:
        rc.evaluate(rec, {})
    assert err.value.missing == ["demands_per_year"]
    got = rc.evaluate(rec, {"demands_per_year": 52})
    assert got["failure_rate"] == pytest.approx(q * 52 / 8760) and got["clock"] == "calendar"
    assert got["model"]["distribution_id"] == "exponential" and got["scale"] == pytest.approx(52 / 8760)


def _old_handbook_rate_per_hour(rec, env, quality_factor=None):
    """MIL-HDBK-217F as the conversions and the parts count computed it before covariates."""
    if rec.get("generic_rates"):
        q = rec.get("quality_factors") or {}
        level = next((lv for lv in q.get("levels") or [] if lv["code"] == q.get("default")), None)
        pi_q = quality_factor if quality_factor is not None else (level["value"] if level else 1.0)
        return rec["generic_rates"]["values"][env] * 1e-6 * pi_q
    return rec["prediction"]["per_million_hours"] * 1e-6 * rec["environment_factors"]["values"][env] * (quality_factor or 1.0)


def test_mil_hdbk_217f_environment_and_quality_give_todays_numbers():
    checked = 0
    for rec in library._library()["records"]:
        if rec["source"] != MIL or not (rec.get("environment_factors") or rec.get("generic_rates")):
            continue
        for env in (rec.get("environment_factors") or rec.get("generic_rates"))["values"]:
            got = rc.evaluate(rec, {"environment": env})
            assert got["failure_rate"] == pytest.approx(_old_handbook_rate_per_hour(rec, env), rel=1e-12), (rec["id"], env)
            checked += 1
        with pytest.raises(rc.RecordCovariateError) as err:
            rc.evaluate(rec, {})
        assert err.value.missing == ["environment"]
    assert checked > 2000
    # A grade other than the lowest: its πQ.
    ic = next(r for r in library._library()["records"] if (r.get("quality_factors") or {}).get("levels"))
    s_grade = next(lv for lv in ic["quality_factors"]["levels"] if lv["code"] == "S")
    got = rc.evaluate(ic, {"environment": "GF", "quality": "S"})
    assert got["failure_rate"] == pytest.approx(ic["generic_rates"]["values"]["GF"] * 1e-6 * s_grade["value"])
    with pytest.raises(rc.RecordCovariateError, match="Quality grade must be one of"):
        rc.evaluate(ic, {"environment": "GF", "quality": "Z"})
    # A part-stress πQ as a number multiplies; left at 1 it isn't applied.
    diode = library.get(f"{MIL}:6-1-general-purpose-analog")
    got = rc.evaluate(diode, {"environment": "GF", "quality_factor": 2.4})
    assert got["failure_rate"] == pytest.approx(0.0038e-6 * 6 * 2.4)
    assert any("× πQ 2.4 (as given)" in a for a in got["assumptions"])


def test_a_saved_prediction_gives_the_same_numbers_through_the_covariates():
    """Every MIL-HDBK-217F part type in a parts count, with and without a quality factor, as a saved
    prediction keeps its lines (environment once, quality_factor per line): the rate is today's."""
    recs = [r for r in library._library()["records"] if r["source"] == MIL
            and "GF" in ((r.get("environment_factors") or r.get("generic_rates") or {}).get("values") or {})]
    lines = []
    for i, r in enumerate(recs):
        has_q = r.get("quality_factors") or (r.get("prediction") or {}).get("quality_factor_range") or any(
            f.get("symbol") == "πQ" for f in (r.get("prediction") or {}).get("not_applied") or [])
        lines.append({"name": f"P{i}", "record_id": r["id"], "quantity": 3,
                      **({"quality_factor": 1.7} if has_q and i % 2 else {})})
    out = rp.compute(lines, "GF", 1000)
    for line, row, r in zip(lines, out["lines"], recs):
        want = _old_handbook_rate_per_hour(r, "GF", line.get("quality_factor")) * 1e6 * 3
        assert row["rate_per_million_hours"] == pytest.approx(want, rel=1e-12), r["id"]
        assert row["covariates"]["environment"] == "GF" and row["covariates_from"]["environment"] == "prediction"
    # A line's own environment is the same number as the whole prediction's.
    one = recs[0]
    by_line = rp.compute([{"name": "A", "record_id": one["id"], "covariates": {"environment": "NS"}}], "GF", 1000)
    by_all = rp.compute([{"name": "A", "record_id": one["id"]}], "NS", 1000)
    assert by_line["lines"][0]["rate_per_million_hours"] == by_all["lines"][0]["rate_per_million_hours"]
    assert by_line["lines"][0]["covariates_from"]["environment"] == "line"


def test_nswc_11_is_unchanged():
    rec = library.get(BEARING)
    got = rc.evaluate(rec, COND)
    want = covariate.evaluate(rec, COND, library.resolve)["total"] / 1e6
    assert got["rate_per_hour"] == pytest.approx(want, rel=1e-15)
    # The binding's own evaluation (NSWC-11 at a position) is the same number.
    made = cb.concrete({"source": "nswc", "ref": BEARING}, {**COND}, "hours")
    assert made["params"][0]["value"] == pytest.approx(got["failure_rate"], rel=1e-15)
    per_cycle = next(r for r in library._library()["records"] if r["source"] == "nswc-11" and covariate.per_cycle(r))
    with pytest.raises(rc.RecordCovariateError, match="an hour is needed"):
        rc.evaluate(per_cycle, {})


# ---- components: a set of failure modes ------------------------------------------------------

def test_a_standby_pump_against_a_hand_calculation():
    """Motor-driven pump, normally standby, over a year with 12 starts and 24 running hours: the
    modes as competing risks. Fails to start on each of 12 demands; fails to run in the first hour of
    each run (12 h) and after it (the other 12 h); leaks over every calendar hour."""
    comp = components.get(STANDBY_PUMP)
    assert [m["code"] for m in comp["modes"]] == ["MDP-FTS-NS", "MDP-FTR<1H", "MDP-FTR>1H", "MDP-ELS", "MDP-ELL"]
    q = _mean(_id("MDP-FTS-NS"))
    l1, l2 = _mean(_id("MDP-FTR<1H")), _mean(_id("MDP-FTR>1H"))
    leaks = _mean(_id("MDP-ELS")) + _mean(_id("MDP-ELL"))
    survive = (1 - q) ** 12 * math.exp(-(l1 * 12 + l2 * 12 + leaks * 8760))
    got = components.evaluate(comp, {"demands": 12, "running_hours": 24})
    assert got["probability"] == pytest.approx(1 - survive, rel=1e-12)
    assert got["rare_event_sum"] == pytest.approx(12 * q + 12 * l1 + 12 * l2 + leaks * 8760, rel=1e-12)
    assert got["rate_per_calendar_hour"] == pytest.approx(-math.log(survive) / 8760, rel=1e-12)
    assert got["bounds"]["p05"] < got["probability"] < got["bounds"]["p95"]
    assert sum(m["share"] for m in got["modes"] if m["counted"]) == pytest.approx(1)
    # A 24-hour mission: one start, 24 running hours, 24 calendar hours (the NRC's sum, near enough).
    mission = components.evaluate(comp, {"demands": 1, "running_hours": 24, "calendar_hours": 24})
    assert mission["exposures"]["first_hour"] == 1 and mission["exposures"]["after_first_hour"] == 23
    assert mission["probability"] == pytest.approx(q + l1 + 23 * l2 + leaks * 24, rel=1e-3)
    with pytest.raises(components.ComponentError) as err:
        components.evaluate(comp, {})
    assert set(err.value.missing) == {"demands", "running_hours"}
    with pytest.raises(components.ComponentError, match="more than the calendar hours"):
        components.evaluate(comp, {"demands": 1, "running_hours": 100, "calendar_hours": 50})


def test_components_group_by_name_and_pooling_group():
    every = components.all_components()
    ids = [c["id"] for c in every]
    assert len(ids) == len(set(ids)) and len(every) > 60
    for c in every:
        assert sum(m["counted"] for m in c["modes"]) >= 2, c["label"]
        assert "((" not in c["label"] and "))" not in c["label"], c["label"]
        assert len({m["record_id"] for m in c["modes"]}) == len(c["modes"]), c["label"]
    labels = {c["label"]: c for c in every}
    assert {"Motor-driven pump (normally standby)", "Motor-driven pump (normally running)",
            "Motor-driven pump (service water)", "Self-cleaning strainer (service water, normally running)"} <= set(labels)
    # FTOC pools fails to open and fails to close: those are listed, not added.
    aov = {m["code"]: m for m in labels["Air-operated valve"]["modes"]}
    assert aov["AOV-FTOC"]["counted"] and not aov["AOV-FTO"]["counted"] and not aov["AOV-FTC"]["counted"]
    # A component's own mode replaces the generic one of its family (spurious operation, CCW).
    ccw = {m["code"] for m in labels["Air-operated valve (component cooling water)"]["modes"]}
    assert "AOV-SOP-CCW" in ccw and "AOV-SOP" not in ccw
    # A sensor's fails to operate has both a demand and a calendar part: both added.
    flow = labels["Flow sensor/transmitter"]["modes"]
    assert {m["trigger"] for m in flow if m["counted"]} == {"demand", "calendar"}
    # A pipe needs its length; a narrower duplicate is listed, not added.
    pipe = labels["Pipe (service water)"]
    assert [i["key"] for i in components.inputs(pipe)] == ["length_ft", "calendar_hours"]
    ssw = {m["code"]: m for m in labels["Self-cleaning strainer (standby service water)"]["modes"]}
    assert not ssw["STR-FLTSC-PG-EE-SSW"]["counted"]
    assert not any(c["name"] == "Reactor trip breaker" for c in every)  # its parts are inside the whole


# ---- the prior path ----------------------------------------------------------------------------

def test_the_prior_takes_the_records_covariates():
    pipe_id = _id("PIPE-SWS-ELS")
    rec = library.get(pipe_id)
    alpha, beta = (schema.param_dict(rec["distribution"])[k] for k in ("alpha", "beta"))
    # A pipe's prior is for its length (it used to be one foot, whatever the pipe).
    base = lm.prior_base({"record_id": pipe_id, "covariates": {"length_ft": 100}}, "exponential")
    assert base["params"]["failure_rate"] == pytest.approx(_mean(pipe_id) * 100)
    prior = base["priors"]["failure_rate"]
    assert prior.dist.mean(*prior.params) == pytest.approx(alpha / (beta / 100), rel=1e-9) if hasattr(prior, "dist") else True
    assert "Pipe length 100 ft" in base["note"] and base["covariates"]["length_ft"] == 100
    with pytest.raises(Invalid, match="Pipe length is needed"):
        lm.prior_base({"record_id": pipe_id}, "exponential")
    assert lm.prior_base({"record_id": pipe_id, "length_ft": 50}, "exponential")["params"]["failure_rate"] == \
        pytest.approx(_mean(pipe_id) * 50)  # the old name
    # The clock: a fails-to-run rate as a prior on calendar time.
    run = lm.prior_base({"record_id": _id("MDP-FTR>1H"), "covariates": {"clock": "calendar", "running_hours_per_year": 4380}},
                        "weibull")
    assert run["clock"] == "calendar" and "per calendar hour" in run["note"]
    plain = lm.prior_base({"record_id": _id("MDP-FTR>1H")}, "exponential")
    assert plain["params"]["failure_rate"] == pytest.approx(_mean(_id("MDP-FTR>1H")))
    # A probability per demand, with its demands a year.
    pd = lm.prior_base({"record_id": DEMAND, "covariates": {"demands_per_year": 24}}, "exponential")
    assert pd["params"]["failure_rate"] == pytest.approx(_mean(DEMAND) * 24 / 8760)
    # A handbook rate is a point value: no prior. A covariate model says so in its own words.
    with pytest.raises(Invalid, match="no spread"):
        lm.prior_base({"record_id": f"{MIL}:6-1-general-purpose-analog", "covariates": {"environment": "GF"}}, "exponential")
    with pytest.raises(Invalid, match="handbook covariate model"):
        lm.prior_base({"record_id": BEARING}, "exponential")


# ---- old saved data, read as fixed covariates --------------------------------------------------

def test_a_model_saved_before_shows_its_length_as_a_fixed_covariate(m, db):
    model, _ = lm.save_record_model(db, ORG, _id("PIPE-SWS-ELS"), length_ft=250)
    assert model.results["library"]["covariates"]["length_ft"] == 250
    # As the old code saved it: the length only, no covariates.
    db.models.update_one({"_id": model.id}, {"$unset": {"results.library.covariates": "", "results.library.covariates_words": ""}})
    old = models_service.get_model(db, model.id)
    assert "covariates" not in old.results["library"]
    page = models_service.public_results(old)
    assert page["library"]["covariates"] == {"length_ft": 250} and page["library"]["covariates_words"] == "Pipe length 250 ft"
    assert "covariates" not in db.models.find_one({"_id": model.id})["results"]["library"]  # read-only
    # A position linked to it says what's fixed there.
    pos = m.create_position("Header pipe")["id"]
    m.link_position_model(pos, "model", model.id, "library", None, model.name, "",
                          {"library": {"record_id": _id("PIPE-SWS-ELS"), "source": "NRC/INL 2020", "label": "Pipe"}})
    [row] = pm.describe(m, db, OWNERS, set(), m.position_models(pos))
    assert "fixed here: Pipe length 250 ft" in row["source_text"]


# ---- at a position, the rest in the RBD --------------------------------------------------------

def test_a_library_record_fixed_at_a_position_and_set_in_the_rbd(m, db):
    box = m.create_position("Cooling loop")["id"]
    pump = m.create_position("Pump", parent_id=box)["id"]
    pipe = m.create_position("Pipe", parent_id=box)["id"]
    # The pipe's length fixed (design); the pump's fails-to-run rate left open, its clock changed in the RBD.
    cp.bind(m, db, ORG, OWNERS, pipe, {"source": "library", "ref": _id("PIPE-SWS-ELS"), "fixed": {"length_ft": 300}})
    link = cp.bind(m, db, ORG, OWNERS, pump, {"source": "library", "ref": _id("MDP-FTR>1H"), "fixed": {}})
    assert link["model_type"] == cp.MODEL_TYPE and "0 of 1 covariates fixed here" in link["source"]["binding_words"]
    # Its clock and running hours both fixed: a constant rate in calendar time, saved.
    both = cp.bind(m, db, ORG, OWNERS, m.create_position("Spare pump")["id"],
                   {"source": "library", "ref": _id("MDP-FTR>1H"), "fixed": {"clock": "calendar", "running_hours_per_year": 438}})
    assert both["model_type"] == "model"
    assert db.models.find_one({"_id": both["model_id"]})["results"]["params"][0]["value"] == pytest.approx(
        _mean(_id("MDP-FTR>1H")) * 438 / 8760)
    [row] = pm.describe(m, db, OWNERS, set(), m.position_models(pump))
    assert row["model"]["kind"].startswith("Library record")
    built = pm.build_rbd(m, db, OWNERS, set(), box, owner_id=ORG)
    graph = db.rbds.find_one({"_id": built["model_id"]})["graph"]
    blocks = {n["data"]["label"]: n for n in graph["nodes"] if n["type"] == "component"}
    # The pipe: its length fixed, its clock open (its own by default): 300 ft of pipe in the block.
    pipe_rate = _mean(_id("PIPE-SWS-ELS")) * 300
    assert blocks["Pump"]["data"]["model"]["kind"] == "bound"
    run = _mean(_id("MDP-FTR>1H"))

    def rates(g):
        bound, _, needs = cb.bind_graph(g, lambda b: cb.inputs_of(b, db, OWNERS))
        return {n["data"]["label"]: n["data"]["model"]["params"][0]["value"] for n in bound["nodes"]
                if n["type"] == "component" and "params" in (n["data"].get("model") or {})}, needs

    got, needs = rates(graph)
    assert not needs and got["Pump"] == pytest.approx(run) and got["Pipe"] == pytest.approx(pipe_rate)
    assert rbds.analyze_graph(db, graph, OWNERS, t_max=2000)["mttf"] > 0
    # The diagram's clock is calendar time: the block needs the hours it runs, said in words.
    blocks["Pump"]["data"]["covariate_values"] = {"clock": "calendar"}
    with pytest.raises(rbd_analysis.AnalysisError, match="Pump needs Running hours a year"):
        rbds.analyze_graph(db, graph, OWNERS, t_max=2000)
    graph["conditions"] = [{"name": "Running hours a year", "role": "use", "unit": "hours a year", "value": 876}]
    got, needs = rates(graph)
    assert not needs and got["Pump"] == pytest.approx(run * 876 / 8760)


def test_a_component_at_a_position(m, db):
    pos = m.create_position("AFW pump")["id"]
    fixed = {"demands": 12, "running_hours": 24}
    inputs = cb.inputs_of({"source": "component", "ref": STANDBY_PUMP})
    assert [i["key"] for i in inputs] == ["demands", "running_hours", "calendar_hours"]
    link = cp.bind(m, db, ORG, OWNERS, pos, {"source": "component", "ref": STANDBY_PUMP, "fixed": {**fixed, "calendar_hours": 8760}})
    model = db.models.find_one({"_id": link["model_id"]})
    want = components.evaluate(STANDBY_PUMP, fixed)["rate_per_calendar_hour"]
    assert model["results"]["params"][0]["value"] == pytest.approx(want)
    made = cb.concrete({"source": "component", "ref": STANDBY_PUMP}, fixed, "hours")
    assert made["params"][0]["value"] == pytest.approx(want)


# ---- the API: REST and MCP give the same ------------------------------------------------------

def test_the_evaluate_route_and_components(monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config
    from backend.ratelimit import SlidingWindowLimiter
    from backend.routers import library as router

    monkeypatch.setattr(config, "AUTH_DISABLED", False)
    monkeypatch.setattr(router, "_LIMIT", SlidingWindowLimiter(1000))
    monkeypatch.setattr(router, "_EVAL_LIMIT", SlidingWindowLimiter(1000))
    c = TestClient(__import__("backend.main", fromlist=["app"]).app)
    pipe = _id("PIPE-SWS-ELS")
    r = c.post(f"/api/library/records/{pipe}/evaluate", json={"covariates": {"length_ft": 10}}).json()
    assert r["ok"] and r["result"]["failure_rate"] == pytest.approx(_mean(pipe) * 10)
    no = c.post(f"/api/library/records/{pipe}/evaluate", json={"covariates": {}}).json()
    assert not no["ok"] and no["missing"] == ["length_ft"]
    d = c.get(f"/api/library/records/{pipe}").json()
    assert [i["key"] for i in d["covariates"]] == ["length_ft", "clock", "running_hours_per_year"]
    assert d["components"][0]["label"] == "Pipe (service water)"
    listed = c.get("/api/library/components", params={"source": "nrc-inl-2020", "q": "pump standby"}).json()
    assert any(x["id"] == STANDBY_PUMP for x in listed["components"])
    one = c.get(f"/api/library/components/{STANDBY_PUMP}").json()
    assert len(one["modes"]) == 5 and one["inputs"][0]["key"] == "demands"
    ev = c.post(f"/api/library/records/{STANDBY_PUMP}/evaluate", json={"covariates": {"demands": 12, "running_hours": 24}}).json()
    assert ev["ok"] and ev["result"]["probability"] == pytest.approx(
        components.evaluate(STANDBY_PUMP, {"demands": 12, "running_hours": 24})["probability"])
    assert c.get("/api/library/components/nrc-inl-2020:component:nope").status_code == 404


def test_the_library_record_over_mcp_takes_covariates(env, mcp_on):  # noqa: F811 - fixtures
    from backend.tests.test_mcp import _ok
    from backend.tests.test_mcp_plans import PRO, _call

    token = env.oauth[PRO]
    pipe = _id("PIPE-SWS-ELS")
    one = _ok(_call(token, "get", {"kind": "library_record", "id": pipe, "covariates": {"length_ft": 10}}))
    assert one["evaluation"]["ok"] and one["evaluation"]["result"]["failure_rate"] == pytest.approx(_mean(pipe) * 10)
    assert [i["key"] for i in one["covariates"]][0] == "length_ft"
    # conditions is the old name of covariates; environment the old name of covariates.environment.
    old = _ok(_call(token, "get", {"kind": "library_record", "id": BEARING, "conditions": COND}))
    assert old["evaluation"]["result"]["total"] > 0
    diode = f"{MIL}:6-1-general-purpose-analog"
    env_old = _ok(_call(token, "get", {"kind": "library_record", "id": diode, "environment": "GF"}))
    env_new = _ok(_call(token, "get", {"kind": "library_record", "id": diode, "covariates": {"environment": "GF"}}))
    assert env_old["block_model"]["failure_rate"] == pytest.approx(env_new["evaluation"]["result"]["failure_rate"])
    comps = _ok(_call(token, "list", {"kind": "library", "components": True, "source": "nrc-inl-2020", "query": "standby pump"}))
    assert any(x["id"] == STANDBY_PUMP for x in comps["components"])
    comp = _ok(_call(token, "get", {"kind": "library_record", "id": STANDBY_PUMP, "covariates": {"demands": 12, "running_hours": 24}}))
    assert comp["evaluation"]["ok"] and len(comp["modes"]) == 5


from backend.tests.test_mcp_plans import env  # noqa: E402,F401 - the fixture
