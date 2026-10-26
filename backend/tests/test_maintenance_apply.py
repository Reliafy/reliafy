"""maintenance_apply: many maintenance changes in one MCP call. The batch is
the typed tools' own actions with refs between them, checked on a throwaway
copy before anything is written; deletes name what they delete; the answer
carries per-operation results, counts and the reverse operations."""

import json

import pytest

from backend.maintenance import apply as apply_mod
from backend.tests.test_maintenance_mcp import UID, _do, _get, _list, _ok, _session, env, free_env  # noqa: F401
from backend.tests.test_mcp_plans import _calls_used

pytestmark = pytest.mark.usefixtures("mcp_on")

BRANCH = [
    {"ref": "p", "do": "positions.create", "args": {"name": "Feed pump A", "position_class": "Feed pump"}},
    {"ref": "f", "do": "failure_modes.add_function", "args": {"position_id": "@p", "text": "Deliver 40 L/s"}},
    {"ref": "ff", "do": "failure_modes.add_functional_failure", "args": {"function_id": "@f", "text": "No flow"}},
    {"ref": "m1", "do": "failure_modes.add", "args": {"position_id": "@p", "functional_failure_id": "@ff",
                                                       "text": "Bearing worn"}},
    {"do": "failure_modes.update", "args": {"failure_mode_id": "@m1", "effects": "Pump trips."}},
    {"do": "failure_modes.decide", "args": {"failure_mode_id": "@m1", "consequence": "operational", "decision": {
        "outcome": "on_condition", "task": "Vibration check", "interval": 3, "interval_unit": "months"}}},
    {"ref": "m2", "do": "failure_modes.add", "args": {"position_id": "@p", "functional_failure_id": "@ff",
                                                       "text": "Seal leaks"}},
    {"do": "failure_modes.decide", "args": {"failure_mode_id": "@m2", "consequence": "operational",
                                             "decision": {"outcome": "rtf", "rtf_basis": "random"}}},
    {"ref": "t", "do": "tasks.create", "args": {"position_id": "@p", "name": "Grease bearings", "interval": 500,
                                                "unit": "hours", "source": "oem", "reference": "Manual 7.2"}},
    {"ref": "seal", "do": "parts.create", "args": {"part_number": "SK-40", "name": "Seal kit"}},
    {"do": "parts.add_to_position", "args": {"position_id": "@p", "part_id": "@seal", "role": "component",
                                              "critical": True}},
    {"ref": "fit", "do": "fitments.fit", "args": {"position_id": "@p", "item_name": "Pump", "serial": "N1",
                                                  "on": "2024-03"}},
    {"do": "items.update", "args": {"item_id": "@fit.fitted.item.id", "manufacturer": "KSB"}},
]


async def _apply(client, operations, **more):
    return await client.call_tool("maintenance_apply", {"operations": operations, **more})


def _events(client_env):
    from backend.routers import maintenance as router

    return router.get_store().event_count(UID)


def test_builds_a_pump_branch_in_one_call(env):
    async def flow(client):
        out = _ok(await _apply(client, BRANCH, idempotency_key="pump-a-1"))
        position = _ok(await _get(client, "position", out["results"][0]["id"]))
        rcm = _ok(await _get(client, "rcm", out["results"][0]["id"], scope="this"))
        again = _ok(await _apply(client, BRANCH, idempotency_key="pump-a-1"))
        clash = await _apply(client, BRANCH[:1], idempotency_key="pump-a-1")
        events = _ok(await _list(client, "events", limit=5))
        return out, position, rcm, again, clash, events

    out, position, rcm, again, clash, events = _session(env["token"], flow)
    assert out["ok"] and out["dry_run"] is False and out["applied"] == len(BRANCH) and out["failed"] is None
    assert [r["status"] for r in out["results"]] == ["ok"] * len(BRANCH)
    assert out["counts"] == {"creates": 8, "updates": 5, "deletes": 0, "other": 0} and out["events"] >= 13
    refs = {r["ref"]: r["id"] for r in out["results"] if r.get("ref")}
    assert position["name"] == "Feed pump A" and position["fitted"]["item"]["manufacturer"] == "KSB"
    assert sorted(t["name"] for t in position["tasks"]) == ["Grease bearings", "Vibration check"]
    assert position["parts_list"][0]["part"]["part_number"] == "SK-40" and position["parts_list"][0]["critical"]
    modes = rcm["positions"][0]["functions"][0]["failures"][0]["modes"]
    assert [(x["id"], x["decision"]["outcome"]) for x in modes] == [(refs["m1"], "on_condition"), (refs["m2"], "rtf")]
    # The reverse of every create, newest first; the updates, decide and fit are listed as not undone.
    undo = out["undo"]
    assert undo[0] == {"do": "parts.retire", "args": {"part_id": refs["seal"]}, "confirm": "Seal kit"}
    assert undo[-1] == {"do": "positions.retire", "args": {"position_id": refs["p"]}, "confirm": "Feed pump A"}
    assert {u["do"] for u in undo} == {"parts.retire", "tasks.retire", "failure_modes.retire",
                                      "failure_modes.remove_functional_failure", "failure_modes.remove_function",
                                      "positions.retire"}
    assert out["irreversible"] == [4, 5, 7, 10, 11, 12]
    # The same key and operations within a day: the stored answer, nothing run again.
    assert again["replayed"] is True and again["applied"] == len(BRANCH) and again["results"] == out["results"]
    assert clash.is_error and "different batch" in clash.content[0].text
    assert [e["type"] for e in events["events"]][:2] == ["item.updated", "item.fitted"] and events["events"][0]["seq"]


def test_refs_point_backwards_only_and_a_bad_path_refuses_the_batch(env):
    async def flow(client):
        before = _events(env)
        forward = await _apply(client, [
            {"do": "failure_modes.add_function", "args": {"position_id": "@p", "text": "x"}},
            {"ref": "p", "do": "positions.create", "args": {"name": "P"}}])
        unknown = await _apply(client, [{"do": "positions.create", "args": {"name": "P", "parent_id": "@nope"}}])
        bad_path = await _apply(client, [
            {"ref": "p", "do": "positions.create", "args": {"name": "P"}},
            {"do": "positions.update", "args": {"position_id": "@p.fitted.item.id", "tag": "T"}}])
        twice = await _apply(client, [{"ref": "p", "do": "positions.create", "args": {"name": "P"}},
                                      {"ref": "p", "do": "positions.create", "args": {"name": "Q"}}])
        return before, _events(env), forward, unknown, bad_path, twice

    before, after, forward, unknown, bad_path, twice = _session(env["token"], flow)
    assert before == after  # nothing was written by any of them
    assert forward.is_error and "@p isn't the ref of an earlier operation" in forward.content[0].text
    assert unknown.is_error and "@nope" in unknown.content[0].text
    assert twice.is_error and "used twice" in twice.content[0].text
    out = _ok(bad_path)
    assert out["ok"] is False and out["dry_run"] is True and out["failed"]["index"] == 1
    assert "@p: its result has no 'fitted.item.id'" in out["failed"]["error"] and "Nothing was written" in out["detail"]
    assert [r["status"] for r in out["results"]] == ["would", "failed"]


def test_a_failing_operation_anywhere_means_nothing_is_written(env):
    async def flow(client):
        before = _events(env)
        out = _ok(await _apply(client, [
            {"ref": "p", "do": "positions.create", "args": {"name": "P"}},
            {"do": "tasks.create", "args": {"position_id": "@p", "name": "x" * 300, "interval": 1}},
            {"do": "positions.create", "args": {"name": "Q"}}]))
        typed = _ok(await _apply(client, [{"do": "positions.create", "args": {"name": "P", "cascade": 3}}]))
        extra = _ok(await _apply(client, [{"do": "positions.create", "args": {"name": "P", "reason": "x"}}]))
        return before, _events(env), out, typed, extra, _ok(await client.call_tool("maintenance_overview", {}))

    before, after, out, typed, extra, overview = _session(env["token"], flow)
    assert before == after and overview["summary"]["positions"] == 0
    assert out["ok"] is False and out["failed"]["index"] == 1 and out["failed"]["do"] == "tasks.create"
    assert "op 1 (tasks.create): The task's name is at most 200 characters" in out["failed"]["error"]
    assert [r["status"] for r in out["results"]] == ["would", "failed", "skipped"]
    assert typed["failed"]["error"].startswith("op 0 (positions.create): action 'create': cascade:")
    assert "action 'create' doesn't take reason" in extra["failed"]["error"]


def test_deletes_need_confirm_dry_run_by_default_and_undo_restores(env):
    async def flow(client):
        pump = _ok(await _do(client, "maintenance_positions", "create", name="Pump A"))["id"]
        mode = _ok(await _do(client, "maintenance_failure_modes", "add", position_id=pump, text="Bearing worn"))["id"]
        task = _ok(await _do(client, "maintenance_tasks", "create", position_id=pump, name="Grease", interval=3))["id"]
        unconfirmed = await _apply(client, [{"do": "failure_modes.retire", "args": {"failure_mode_id": mode}}])
        wrong = await _apply(client, [{"do": "failure_modes.retire", "args": {"failure_mode_id": mode},
                                       "confirm": "Seal leaks"}])
        ops = [{"do": "failure_modes.retire", "args": {"failure_mode_id": mode}, "confirm": "bearing  WORN"},
               {"do": "tasks.retire", "args": {"task_id": task, "reason": "dup"}, "confirm": "Grease"},
               {"do": "positions.update", "args": {"position_id": pump, "tag": "P-1"}}]
        rehearsed = _ok(await _apply(client, ops))
        still = _ok(await _get(client, "position", pump))
        done = _ok(await _apply(client, ops, dry_run=False))
        gone = _ok(await _get(client, "position", pump))
        undone = _ok(await _apply(client, done["undo"], dry_run=False))
        back = _ok(await _get(client, "position", pump))
        same_batch = _ok(await _apply(client, [
            {"ref": "q", "do": "positions.create", "args": {"name": "Temp"}},
            {"do": "positions.retire", "args": {"position_id": "@q"}}], dry_run=False))
        return unconfirmed, wrong, rehearsed, still, done, gone, undone, back, same_batch

    unconfirmed, wrong, rehearsed, still, done, gone, undone, back, same_batch = _session(env["token"], flow)
    assert unconfirmed.is_error and "op 0 (failure_modes.retire): to delete it, repeat with confirm 'Bearing worn'." \
        in unconfirmed.content[0].text
    assert wrong.is_error and "confirm 'Bearing worn'" in wrong.content[0].text
    assert rehearsed["dry_run"] is True and rehearsed["would_apply"] == 3 and "dry run" in rehearsed["detail"]
    assert rehearsed["counts"] == {"creates": 0, "updates": 1, "deletes": 2, "other": 0}
    assert len(still["failure_modes"]) == 1 and len(still["tasks"]) == 1 and still["tag"] == ""
    assert done["dry_run"] is False and done["applied"] == 3 and done["events"] == 3
    assert gone["failure_modes"] == [] and gone["tasks"] == [] and gone["tag"] == "P-1"
    assert done["undo"] == [{"do": "tasks.restore", "args": {"task_id": still["tasks"][0]["id"]}},
                            {"do": "failure_modes.restore", "args": {"failure_mode_id": still["failure_modes"][0]["id"]}}]
    assert done["irreversible"] == [2]
    assert undone["applied"] == 2 and undone["dry_run"] is False  # restores aren't deletes: no dry run forced
    assert [m["text"] for m in back["failure_modes"]] == ["Bearing worn"] and [t["name"] for t in back["tasks"]] == ["Grease"]
    assert undone["undo"][0]["do"] == "failure_modes.retire" and undone["undo"][0]["confirm"] == "Bearing worn"
    assert same_batch["ok"] and same_batch["applied"] == 2  # deleting what the batch made needs no confirm


def test_what_a_batch_cant_carry_and_its_limits(env):
    async def flow(client):
        return (await _apply(client, [{"do": "reliability.fit_class_model", "args": {"position_class": "x"}}]),
                await _apply(client, [{"do": "workspace.set_time_zone", "args": {"time_zone": "UTC"}}]),
                await _apply(client, [{"do": "attachments.add_document", "args": {"upload_id": "u", "target_id": "t"}}]),
                await _apply(client, [{"do": "positions.nope", "args": {}}]),
                await _apply(client, [{"do": "rockets.launch", "args": {}}]),
                await _apply(client, [{"do": "positions.create", "args": {"name": "P"}, "extra": 1}]),
                await _apply(client, [{"do": "positions.create", "args": {"name": f"P{i}"}}
                                      for i in range(apply_mod.MAX_OPS + 1)]),
                await _apply(client, [{"do": "positions.retire", "args": {"position_id": "x"}, "confirm": "x"}
                                      for _ in range(apply_mod.MAX_DELETES + 1)]),
                await _apply(client, []),
                await _apply(client, [{"do": "positions.create", "args": {"name": "P"}}], idempotency_key="k" * 65),
                await _apply(client, [{"do": "positions.create", "args": "no"}]))

    pro, tz, pdf, action, area, extra, many, deletes, empty, key, args = _session(env["token"], flow)
    assert "isn't allowed in a batch" in pro.content[0].text and "maintenance_reliability fit_class_model" in pro.content[0].text
    assert "isn't allowed in a batch" in tz.content[0].text
    assert "a PDF (upload_id)" in pdf.content[0].text
    assert "no write action 'positions.nope'" in action.content[0].text
    assert "no write action 'rockets.launch'" in area.content[0].text and "Areas: attachments, failure_modes" in area.content[0].text
    assert "unknown field extra" in extra.content[0].text
    assert "At most 200 operations" in many.content[0].text
    assert "At most 50 delete-type operations" in deletes.content[0].text
    assert empty.is_error and "at least one" in empty.content[0].text
    assert key.is_error and ("64" in key.content[0].text)
    assert "args is an object" in args.content[0].text


def test_a_big_batch_dry_runs_by_default_and_cuts_the_results(env):
    ops = [{"ref": f"p{i}", "do": "positions.create", "args": {"name": f"Pump {i:02d}"}} for i in range(60)]

    async def flow(client):
        rehearsed = _ok(await _apply(client, ops))
        done = _ok(await _apply(client, ops, dry_run=False))
        overview = _ok(await client.call_tool("maintenance_overview", {}))
        return rehearsed, done, overview

    rehearsed, done, overview = _session(env["token"], flow)
    assert rehearsed["dry_run"] is True and rehearsed["would_apply"] == 60 and "over 25 operations" in rehearsed["detail"]
    assert overview["summary"]["positions"] == 60 and done["applied"] == 60
    assert done["results"][0]["result"] == {"id": done["results"][0]["id"], "name": "Pump 00"} and "results_cut" in done
    assert len(done["undo"]) == 60


def test_the_real_run_stops_or_continues_on_a_failure():
    """run_pass with a call that fails on the second operation: stop skips the
    rest and continue runs them; what ran before stays applied either way."""
    from backend.maintenance.service import Invalid

    ops = apply_mod.parse([{"ref": "a", "do": "positions.create", "args": {"name": "A"}},
                           {"do": "positions.create", "args": {"name": "B"}},
                           {"do": "positions.update", "args": {"position_id": "@a", "tag": "T"}}],
                          {"maintenance_positions": ("action", {"create": ("name", "", ""), "update": ("position_id", "tag", "")})})
    log = []

    def call(area, action, args):
        log.append((action, args))
        if args.get("name") == "B":
            raise Invalid("B is already there.")
        return {"id": f"id-{args.get('name') or args.get('position_id')}", **args}

    stop = apply_mod.run_pass(ops, call, None, "stop", dry=False)
    assert [r["status"] for r in stop["results"]] == ["ok", "failed", "skipped"]
    assert stop["failed"]["error"] == "op 1 (positions.create): B is already there."
    go_on = apply_mod.run_pass(ops, call, None, "continue", dry=False)
    assert [r["status"] for r in go_on["results"]] == ["ok", "failed", "ok"]
    assert log[-1] == ("update", {"position_id": "id-A", "tag": "T"})
    summary = apply_mod.summarise(ops, go_on, False, 2)
    assert summary["applied"] == 2 and summary["failed"]["index"] == 1 and summary["ok"] is False
    assert summary["undo"] == [{"do": "positions.retire", "args": {"position_id": "id-A"}, "confirm": "A"}]
    assert summary["irreversible"] == [2]


def test_a_batch_counts_once_against_the_free_allowance(free_env):
    async def flow(client):
        out = await _apply(client, BRANCH[:4], dry_run=False)
        return out

    out = _ok(_session(free_env["oauth"], flow))
    assert out["applied"] == 4
    assert _calls_used(free_env["db"], UID) == 1


def test_the_dry_pass_leaves_bytes_outside_the_log_alone(env, monkeypatch, tmp_path):
    from backend.maintenance import photos
    from backend.maintenance.service import Maintenance
    from backend.routers import maintenance as router

    store = photos.FilePhotoStore(str(tmp_path))
    monkeypatch.setattr(router, "_photo_store", store)
    m = Maintenance(router.get_store(), UID, UID)
    pid = m.create_position("Pump")["id"]
    photo = "photo1"
    store.put(photo, "full", b"full"), store.put(photo, "thumb", b"thumb")
    m.add_photo(photo, pid, {"width": 1, "height": 1}, "Front")

    async def flow(client):
        rehearsed = _ok(await _apply(client, [{"do": "attachments.remove_photo", "args": {"photo_id": photo},
                                                "confirm": "Front"}]))
        kept = store.get(photo, "full")
        done = _ok(await _apply(client, [{"do": "attachments.remove_photo", "args": {"photo_id": photo},
                                           "confirm": "Front"}], dry_run=False))
        return rehearsed, kept, done, store.get(photo, "full")

    rehearsed, kept, done, gone = _session(env["token"], flow)
    assert rehearsed["would_apply"] == 1 and kept == b"full"
    assert done["applied"] == 1 and gone is None and m.photo(photo)["removed"] is True


def test_over_rest(env):
    """The twin route: POST /api/v1/maintenance_apply with the same body."""
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    headers = {"Authorization": f"Bearer {env['token']}"}
    r = client.post("/api/v1/maintenance_apply", json={"operations": BRANCH[:3]}, headers=headers)
    assert r.status_code == 200 and r.json()["applied"] == 3, r.text
    r = client.post("/api/v1/maintenance_apply", json={"operations": [{"do": "rockets.launch", "args": {}}]},
                    headers=headers)
    assert r.status_code == 422 and "no write action" in r.json()["detail"]
    r = client.post("/api/v1/maintenance_apply/run", json={}, headers=headers)
    assert r.status_code == 404
    listing = client.get("/api/v1/tools", headers=headers).json()
    tool = next(t for t in listing["tools"] if t["name"] == "maintenance_apply")
    assert tool["scope"] == "write" and tool["actions"][0]["path"] == "/api/v1/maintenance_apply"
    assert json.dumps(listing)  # serialisable
