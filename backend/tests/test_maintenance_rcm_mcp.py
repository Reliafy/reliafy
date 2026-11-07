"""The RCM on the asset tree, driven the way an agent drives it: over MCP only,
from an empty workspace. Build a pump's RCM (a function with two performance
standards and their limits, functional failures breaching them, modes with
effects, decisions, two tasks on one mode, one by use), link a cause between
levels, check the evidence, ask what's missing, move things (including a task by
use that needs a choice), rearrange performance standards, retire and restore,
and undo through maintenance_apply. Every id the next call needs comes from an
earlier answer, and every refusal says what to do next."""

import pytest

from backend.tests.test_maintenance_mcp import _do, _get, _list, _ok, _session, env  # noqa: F401



def _err(result) -> str:
    assert result.is_error, result.structured_content
    return result.content[0].text


async def _apply(client, operations, **more):
    return await client.call_tool("maintenance", {"action": "apply", "operations": operations, **more})


async def _pump_rcm(client) -> dict:
    """A cooling-water system with Pump A (and Motor A inside it) and Pump B, each
    pump with a run-hours counter, and Pump A's RCM built one call at a time, as
    an agent would, each id taken from the answer before."""
    ids = {}
    ids["sys"] = _ok(await _do(client, "maintenance", "positions.create", name="Cooling water system"))["id"]
    for key, name in (("a", "Pump A"), ("b", "Pump B")):
        ids[key] = _ok(await _do(client, "maintenance", "positions.create", name=name, parent_id=ids["sys"],
                                 position_class="CW pump"))["id"]
        point = _ok(await _do(client, "maintenance", "measurements.add_point", position_id=ids[key],
                              name="Run hours", kind="counter", unit="hours"))
        ids[f"hours_{key}"] = point["id"]
        _ok(await _do(client, "maintenance", "measurements.record", point_id=point["id"], value=12000,
                      on="2026-10-01"))
    fn = _ok(await _do(client, "maintenance", "failure_modes.add_function", position_id=ids["a"],
                       text="Pump cooling water to the heat exchangers"))
    ids["fn"] = fn["id"]
    flow = _ok(await _do(client, "maintenance", "failure_modes.add_standard", function_id=fn["id"], text="At least 40 L/s", parameter="flow",
                         comparator=">=", value=40, unit="L/s", when="while the plant runs"))
    pressure = _ok(await _do(client, "maintenance", "failure_modes.add_standard", function_id=fn["id"], text="Discharge 5.5 to 6.5 bar",
                             parameter="discharge pressure", comparator="between", value="5.5-6.5", unit="bar",
                             source="Design basis DB-12"))
    ids["flow"], ids["pressure"] = flow["id"], pressure["id"]
    ids["low_flow"] = _ok(await _do(client, "maintenance", "failure_modes.add_functional_failure", function_id=fn["id"],
                                    text="Flow below 40 L/s", standard_id=flow["id"]))["id"]
    ids["bad_pressure"] = _ok(await _do(client, "maintenance", "failure_modes.add_functional_failure", function_id=fn["id"],
                                        text="Pressure outside 5.5-6.5 bar", standard_id=pressure["id"]))["id"]
    ids["no_flow"] = _ok(await _do(client, "maintenance", "failure_modes.add_functional_failure", function_id=fn["id"],
                                   text="No flow at all"))["id"]
    impeller = _ok(await _do(client, "maintenance", "failure_modes.add", position_id=ids["a"], functional_failure_id=ids["low_flow"],
                             text="Impeller worn"))
    ids["impeller"] = impeller["id"]
    _ok(await _do(client, "maintenance", "failure_modes.update", failure_mode_id=impeller["id"],
                  effects="Flow falls slowly; the exchanger outlet runs hot."))
    _ok(await _do(client, "maintenance", "failure_modes.decide", failure_mode_id=impeller["id"], consequence="operational",
                  decision={"outcome": "on_condition", "task": "Check flow against the pump curve", "interval": 3,
                            "interval_unit": "months"}))
    bearing = _ok(await _do(client, "maintenance", "failure_modes.add", position_id=ids["a"], functional_failure_id=ids["no_flow"],
                            text="Bearing seized"))
    ids["bearing"] = bearing["id"]
    decided = _ok(await _do(client, "maintenance", "failure_modes.decide", failure_mode_id=bearing["id"], consequence="operational",
                            decision={"outcome": "fixed_interval", "task": "Replace bearings", "interval": 20000,
                                      "interval_unit": "hours"}))
    ids["replace"] = decided["decision"]["task_id"]
    ids["vibration"] = _ok(await _do(client, "maintenance", "failure_modes.add_task", failure_mode_id=bearing["id"], name="Vibration check",
                                     interval=1, unit="months", outcome="on_condition"))["id"]
    relief = _ok(await _do(client, "maintenance", "failure_modes.add", position_id=ids["a"], functional_failure_id=ids["bad_pressure"],
                           text="Relief valve stuck shut"))
    ids["relief"] = relief["id"]
    ids["relief_decided"] = _ok(await _do(client, "maintenance", "failure_modes.decide", failure_mode_id=relief["id"], consequence="hidden",
                                          decision={"outcome": "rtf", "rtf_basis": "random"}))
    ids["seal"] = _ok(await _do(client, "maintenance", "failure_modes.add", position_id=ids["a"], text="Seal leaks"))["id"]
    # The motor inside the pump, and the system above it, linked by cause.
    ids["motor"] = _ok(await _do(client, "maintenance", "positions.create", name="Motor A", parent_id=ids["a"]))["id"]
    mfn = _ok(await _do(client, "maintenance", "failure_modes.add_function", position_id=ids["motor"], text="Drive the pump at 1480 rpm"))
    ids["motor_stops"] = _ok(await _do(client, "maintenance", "failure_modes.add_functional_failure", function_id=mfn["id"],
                                       text="Motor doesn't turn"))["id"]
    winding = _ok(await _do(client, "maintenance", "failure_modes.add", position_id=ids["motor"], functional_failure_id=ids["motor_stops"],
                            text="Winding insulation fails"))
    _ok(await _do(client, "maintenance", "failure_modes.decide", failure_mode_id=winding["id"], consequence="operational",
                  decision={"outcome": "on_condition", "task": "Insulation resistance test", "interval": 12,
                            "interval_unit": "months"}))
    sfn = _ok(await _do(client, "maintenance", "failure_modes.add_function", position_id=ids["sys"], text="Supply cooling water to the plant",
                        standard="Supply below 30 °C; at least 80 L/s\nNo leaks to the drain"))
    ids["sfn"] = sfn["id"]
    ids["no_water"] = _ok(await _do(client, "maintenance", "failure_modes.add_functional_failure", function_id=sfn["id"],
                                    text="No cooling water"))["id"]
    return ids


def test_an_agent_builds_reads_and_questions_a_pumps_rcm(env):
    async def flow(client):
        ids = await _pump_rcm(client)
        linked = _ok(await _do(client, "maintenance", "failure_modes.link_cause", functional_failure_id=ids["no_flow"],
                               cause_id=ids["motor_stops"]))
        wrong_way = await _do(client, "maintenance", "failure_modes.link_cause", functional_failure_id=ids["motor_stops"],
                              cause_id=ids["no_flow"])
        up = _ok(await _do(client, "maintenance", "failure_modes.link_cause", functional_failure_id=ids["no_water"], cause_id=ids["no_flow"]))
        rcm = _ok(await _get(client, "rcm", ids["a"], scope="this"))
        mode = _ok(await _get(client, "failure_mode", ids["bearing"]))
        impeller = _ok(await _get(client, "failure_mode", ids["impeller"]))
        measured = _ok(await _get(client, "task_measurement", ids["replace"]))
        gaps = _ok(await _list(client, "rcm_gaps"))
        branch = _ok(await _list(client, "rcm_gaps", target_id=ids["motor"]))
        return ids, wrong_way, linked, up, rcm, mode, impeller, measured, gaps, branch

    ids, wrong_way, linked, up, rcm, mode, impeller, measured, gaps, branch = _session(env["token"], flow)
    # The reverse of a link already there would close a loop: refused, saying what to do.
    assert "go round in a circle" in _err(wrong_way) and "swap them" in _err(wrong_way)
    assert linked["changed"] and [c["id"] for c in linked["causes"]] == [ids["motor_stops"]]
    assert up["explained_below"] and up["covered"]

    # A hidden failure run to failure is kept, with a word to relay.
    assert "Hidden consequences usually take failure_finding" in ids["relief_decided"]["advice"]

    # The read back: the standards with their limits, each functional failure under the one it breaches.
    fn = rcm["positions"][0]["functions"][0]
    assert [(s["text"], s["comparator"], s["value"], s["unit"]) for s in fn["standards"]] == [
        ("At least 40 L/s", ">=", 40.0, "L/s"), ("Discharge 5.5 to 6.5 bar", "between", "5.5-6.5", "bar")]
    assert {ff["text"]: (ff["standard"] or {}).get("id") for ff in fn["failures"]} == {
        "Flow below 40 L/s": ids["flow"], "Pressure outside 5.5-6.5 bar": ids["pressure"], "No flow at all": None}
    bearing = next(m for ff in fn["failures"] for m in ff["modes"] if m["id"] == ids["bearing"])
    # Lean for an agent: a mode's tasks once (not again under its decision), no text that repeats the name.
    assert "tasks" not in bearing["decision"] and bearing["decision"]["task_id"] == ids["replace"]
    assert [(t["name"], t["unit"]) for t in bearing["tasks"]] == [("Replace bearings", "hours"),
                                                                  ("Vibration check", "months")]
    assert "text" not in bearing["tasks"][0]

    # One mode in full, by its id alone: where it sits and the tasks it could share.
    assert mode["position"] == {"id": ids["a"], "name": "Pump A"}
    assert mode["function"]["id"] == ids["fn"] and mode["functional_failure"]["id"] == ids["no_flow"]
    assert mode["decision"]["status"] == "unevidenced" and len(mode["tasks"]) == 2
    assert {t["name"] for t in impeller["available"]} == {"Replace bearings", "Vibration check"}
    assert measured["by_use"] and measured["measurement"]["id"] == ids["hours_a"]

    # What's missing, workspace-wide and for one branch.
    assert [m["text"] for m in gaps["undecided"]] == ["Seal leaks"]
    assert {m["text"]: m["outcome"] for m in gaps["no_task"]} == {"Relief valve stuck shut": "rtf",
                                                                    "Seal leaks": None}
    assert [(m["text"], m["position"]["name"]) for m in gaps["hidden_without_failure_finding"]] == [
        ("Relief valve stuck shut", "Pump A")]
    assert gaps["functional_failures_empty"] == [] and gaps["standards_without_failure"] == []
    assert gaps["counts"]["undecided"] == 1 and gaps["modes"] == 5 and gaps["evidence_to_check"] == []
    assert branch["positions"] == 1 and branch["modes"] == 1 and branch["undecided"] == []


def test_an_agent_moves_a_mode_whose_task_counts_hours_and_undoes_it(env):
    async def flow(client):
        ids = await _pump_rcm(client)
        asked = await _do(client, "maintenance", "failure_modes.move", failure_mode_id=ids["bearing"], position_id=ids["b"])
        batch = _ok(await _apply(client, [{"do": "failure_modes.move", "args": {
            "failure_mode_id": ids["bearing"], "position_id": ids["b"]}}]))
        moved = _ok(await _apply(client, [{"do": "failure_modes.move", "args": {
            "failure_mode_id": ids["bearing"], "position_id": ids["b"],
            "measurement": {"choice": "switch", "point_id": ids["hours_b"]}}}]))
        there = _ok(await _get(client, "task_measurement", ids["replace"]))
        back = _ok(await _apply(client, moved["undo"]))
        home = _ok(await _get(client, "task_measurement", ids["replace"]))
        kept = _ok(await _do(client, "maintenance", "failure_modes.move", failure_mode_id=ids["bearing"], position_id=ids["b"],
                             measurement={"choice": "keep"}))
        kept_counts = _ok(await _get(client, "task_measurement", ids["replace"]))
        _ok(await _do(client, "maintenance", "failure_modes.move", failure_mode_id=ids["bearing"], position_id=ids["a"],
                      functional_failure_id=ids["no_flow"]))
        _ok(await _do(client, "maintenance", "failure_modes.move", failure_mode_id=ids["bearing"], position_id=ids["b"],
                      measurement={"choice": "calendar", "interval": 24, "unit": "months"}))
        by_calendar = _ok(await _get(client, "task_measurement", ids["replace"]))
        return ids, asked, batch, moved, there, back, home, kept, kept_counts, by_calendar

    ids, asked, batch, moved, there, back, home, kept, kept_counts, by_calendar = _session(env["token"], flow)
    # The single call says what to send, with the id to switch to.
    words = _err(asked)
    assert "Replace bearings" in words and ids["hours_b"] in words
    assert f"{{choice: 'switch', point_id: '{ids['hours_b']}'}}" in words
    # The batch asks once, under failed (not again in its results), and writes nothing.
    assert not batch["ok"] and batch["failed"]["needs_choice"]["tasks"][0]["task_id"] == ids["replace"]
    assert "needs_choice" not in batch["results"][0] and batch["events"] == 0
    # Switched, then put back by the undo list, counting Pump A's meter again.
    assert moved["ok"] and there["measurement"]["id"] == ids["hours_b"]
    assert back["ok"] and home["measurement"]["id"] == ids["hours_a"] and home["fits"]
    # keep: still Pump A's meter, from Pump B; calendar: no counter at all.
    assert kept["position_id"] == ids["b"] and kept_counts["measurement"]["id"] == ids["hours_a"]
    assert not by_calendar["by_use"] and by_calendar["measurement"] is None


def test_an_agent_rearranges_performance_standards(env):
    async def flow(client):
        ids = await _pump_rcm(client)
        proposal = _ok(await _do(client, "maintenance", "failure_modes.split_standard", function_id=ids["sfn"]))
        stray = await _do(client, "maintenance", "failure_modes.split_standard", function_id=ids["sfn"], dry_run=False,
                          standards=[{"text": "Supply below 30 °C", "limit": 30}])
        split = _ok(await _do(client, "maintenance", "failure_modes.split_standard", function_id=ids["sfn"], dry_run=False, standards=[
            {"text": "Supply below 30 °C", "parameter": "supply temperature", "comparator": "<", "value": 30,
             "unit": "°C"}, {"text": "At least 80 L/s"}, {"text": "No leaks to the drain"}]))
        order = _ok(await _do(client, "maintenance", "failure_modes.reorder_standards", function_id=ids["fn"],
                              standard_ids=[ids["pressure"], ids["flow"]]))
        # What dragging a performance standard does: it and the functional failure breaching it, in one batch.
        carried = _ok(await _apply(client, [
            {"do": "failure_modes.move_standard", "args": {"standard_id": ids["flow"], "function_id": ids["sfn"]}},
            {"do": "failure_modes.move_functional_failure", "args": {
                "functional_failure_id": ids["low_flow"], "function_id": ids["sfn"], "standard_id": ids["flow"]}}]))
        system = _ok(await _get(client, "rcm", ids["sys"], scope="this"))
        undone = _ok(await _apply(client, carried["undo"]))
        pump = _ok(await _get(client, "rcm", ids["a"], scope="this"))
        return ids, order, carried, system, undone, pump, proposal, stray, split

    ids, order, carried, system, undone, pump, proposal, stray, split = _session(env["token"], flow)
    assert [s["id"] for s in order["standards"]] == [ids["pressure"], ids["flow"]]
    assert carried["ok"] and len(carried["undo"]) == 2
    moved_fn = system["positions"][0]["functions"][0]
    assert [s["text"] for s in moved_fn["standards"]][-1] == "At least 40 L/s"
    assert next(ff for ff in moved_fn["failures"] if ff["id"] == ids["low_flow"])["standard"]["id"] == ids["flow"]
    assert undone["ok"]
    fn = pump["positions"][0]["functions"][0]
    assert {s["id"] for s in fn["standards"]} == {ids["flow"], ids["pressure"]}
    assert next(ff for ff in fn["failures"] if ff["id"] == ids["low_flow"])["standard"]["id"] == ids["flow"]
    assert [p["text"] for p in proposal["proposed"]] == ["Supply below 30 °C", "at least 80 L/s",
                                                         "No leaks to the drain"]
    assert "not limit" in _err(stray)
    # The edited lines keep their structured limits.
    first = split["standards"][0]
    assert (first["parameter"], first["comparator"], first["value"], first["unit"]) == (
        "supply temperature", "<", 30, "°C")
    assert split["standards_without_failure"] == 3


def test_an_agent_retires_restores_and_undoes(env):
    async def flow(client):
        ids = await _pump_rcm(client)
        unconfirmed = await _apply(client, [{"do": "failure_modes.retire", "args": {"failure_mode_id": ids["bearing"]}}])
        retired = _ok(await _apply(client, [{"do": "failure_modes.retire", "args": {
            "failure_mode_id": ids["bearing"]}, "confirm": "Bearing seized"}], dry_run=False))
        gone = await _do(client, "maintenance", "failure_modes.update", failure_mode_id=ids["bearing"], notes="x")
        restored = _ok(await _apply(client, retired["undo"]))
        mode = _ok(await _get(client, "failure_mode", ids["bearing"]))
        linked = _ok(await _apply(client, [{"do": "failure_modes.link_cause", "args": {
            "functional_failure_id": ids["no_flow"], "cause_id": ids["motor_stops"]}}]))
        again = _ok(await _apply(client, [{"do": "failure_modes.link_cause", "args": {
            "functional_failure_id": ids["no_flow"], "cause_id": ids["motor_stops"]}}]))
        unlinked = _ok(await _apply(client, linked["undo"]))
        ff = _ok(await _get(client, "failure_mode", ids["bearing"]))
        return ids, unconfirmed, retired, gone, restored, mode, linked, again, unlinked, ff

    ids, unconfirmed, retired, gone, restored, mode, linked, again, unlinked, ff = _session(env["token"], flow)
    assert "confirm 'Bearing seized'" in _err(unconfirmed)
    assert set(retired["results"][0]["result"]["tasks_retired"]) == {ids["replace"], ids["vibration"]}
    assert "restore brings it back" in _err(gone)
    assert restored["ok"] and mode["decision"]["outcome"] == "fixed_interval" and len(mode["tasks"]) == 2
    # A cause link undoes; linking what's linked already leaves nothing to undo.
    assert linked["undo"] == [{"do": "failure_modes.unlink_cause", "args": {
        "functional_failure_id": ids["no_flow"], "cause_id": ids["motor_stops"]}}]
    assert again["undo"] == [] and unlinked["ok"]
    assert ff["functional_failure"]["id"] == ids["no_flow"]


def test_refusals_say_what_to_do_next(env):
    async def flow(client):
        ids = await _pump_rcm(client)
        return ids, [await call for call in (
            _do(client, "maintenance", "failure_modes.add_standard", function_id=ids["low_flow"], text="x"),
            _do(client, "maintenance", "failure_modes.add_functional_failure", function_id="no-such-id", text="x"),
            _get(client, "rcm", ids["fn"]),
            _do(client, "maintenance", "failure_modes.decide", failure_mode_id=ids["impeller"], decision={"evidence": {
                "type": "model", "id": "m1"}}),
            _do(client, "maintenance", "failure_modes.decide", failure_mode_id=ids["impeller"], consequence="economic"),
        )]

    ids, (as_ff, nothing, fn_as_position, no_outcome, bad_consequence) = _session(env["token"], flow)
    assert _err(as_ff).endswith(f"Not found: no function with id {ids['low_flow']} in your maintenance workspace. "
                                f"{ids['low_flow']} is a functional failure (functional_failure_id).")
    assert "RCM ids are in maintenance get.rcm" in _err(nothing)
    assert f"{ids['fn']} is a function (function_id)" in _err(fn_as_position)
    assert "needs its outcome: on_condition, fixed_interval" in _err(no_outcome)
    assert "send the current one" in _err(no_outcome)
    assert "it's one of safety, environmental" in _err(bad_consequence)


@pytest.mark.parametrize("topic", ["plan"])
def test_the_guide_walks_an_agent_through_the_rcm(env, topic):
    async def flow(client):
        return _ok(await client.call_tool("maintenance", {"action": "guide", "topic": topic}))

    page = _session(env["token"], flow)["guide"]
    for words in ("RCM, step by step", "add_standard for each performance standard", "rcm_gaps",
                  "The decision vocabulary", "kind failure_mode", "dry_run=true: a preview"):
        assert words in page, words


def test_rcm_gaps_say_why_evidence_needs_a_look(env):
    from backend.services import samples

    samples.seed_samples(env["db"])  # the sample product's decisions link sample models and analyses

    async def flow(client):
        made = _ok(await _do(client, "maintenance", "products.add_sample"))
        return _ok(await _list(client, "rcm_gaps", target_id=made["product"]["id"]))

    gaps = _session(env["token"], flow)
    rows = gaps["evidence_to_check"]
    contradicted = [r for r in rows if r["status"] == "contradicted"]
    assert len(contradicted) == 4 and all("wear-out" in r["reason"] for r in contradicted)
    assert {r["position"]["name"] for r in contradicted} == {"Motor 1", "Motor 2", "Motor 3", "Motor 4"}
    assert all(r["functional_failure"]["text"] for r in rows)
    [unclear] = [r for r in rows if r["status"] == "inconclusive"]
    assert unclear["text"] == "Cell capacity fade" and "Unit mismatch" in unclear["reason"]
