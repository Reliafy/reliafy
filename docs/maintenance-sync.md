# Maintenance: changes from a device that works offline

Work happens where there is no signal. A device (a phone, a tablet, a script on
a laptop in a plant room) can queue what its user did and send it later:

```
POST /api/v1/maintenance/sync/push     up to 50 queued changes
POST /api/v1/maintenance/sync/photo    one queued photo
```

Both are REST only, for Reliafy Maintenance's users, with the `write` scope.
The code is `backend/maintenance/sync.py` and `backend/routers/maintenance_sync.py`.

## An op

Each queued change is an **op**: one of the maintenance tool's actions, with
what a device adds to it.

```json
{
  "device_id": "5a0c…", "device_tz": "Australia/Brisbane",
  "ops": [{
    "op_id": "0b1f6c0e-7a4b-4d0e-9a53-0d0a8f2f8a11",
    "device_seq": 17,
    "command": "work_orders.update",
    "args": {"work_order_id": "…", "append_note": "Gland weeping"},
    "expects": {"work_order_status": ["open", "in_progress"]},
    "device_time": "2026-11-02T05:20:05Z",
    "clock_offset_ms": -1200,
    "depends_on": ["…the op before it on the same work order…"]
  }]
}
```

| Field | Meaning |
|---|---|
| `op_id` | A UUID the device makes for the change. The server remembers it: the same op sent again is answered `duplicate` and nothing is recorded twice. |
| `device_seq` | 1, 2, 3 … on that device. Ops in a push are applied in this order, whatever order they arrive in. |
| `command`, `args` | `work_orders.status`, `work_orders.update` (only `append_note`, with an optional `at`), `work_orders.check`, `work_orders.mark`, `work_orders.labour`, `work_orders.part_used`, `work_orders.close`, `measurements.record`: the same arguments as the action of that name. `photos.add` (`target_id`, `caption`) goes to the photo route. |
| `expects` | What the device saw when the change was made. Checked against what is so now: `work_order_status` (a list the work order must still be in), `fitment_id` (what was fitted, or null), `checklist_length`, `last_reading` (`{point_id, value}`). |
| `device_time` | The device's clock when the change was made (ISO, `Z` or an offset). |
| `clock_offset_ms` | The server's clock minus the device's, if the device has measured it; else null. |
| `depends_on` | Earlier op ids this one follows. It waits (`held`) until they are applied. |

## The answer

```json
{
  "ops": [{"op_id": "…", "status": "applied", "work_order_id": "…"}],
  "work_orders": {"<id>": { …the work order as it is now… }},
  "points": {"<id>": { …a point a reading was for… }},
  "server_time": "2026-11-04T03:00:07Z", "today": "2026-11-04", "time_zone": "Australia/Brisbane"
}
```

| `status` | Meaning | What the device does |
|---|---|---|
| `applied` | Recorded now. | Marks it sent. |
| `duplicate` | Recorded before. | Marks it sent. |
| `held` | An op it follows hasn't been applied (`waiting_on`). | Keeps it; sends it after that one. |
| `needs_decision` | Not recorded. `reason` is `closed_elsewhere`, `cancelled`, `precondition` (with `expectation`), `refused`, `not_found` or `clock`; `message` says it in plain words. | Shows it to the person. |
| `retry` | Not now (too many changes this minute). | Sends it again later, unchanged. |
| `refused` | The op is malformed. | Reports it; sending it again won't help. |

`work_orders` and `points` hold everything the ops touched as it is after the
push, whatever each op's answer, so the device can replace its copies.

## Once only, whole or not at all

Each op is one event in the log, `op.applied`, holding the events the command
comes to: a close's readings, its actions and the close itself. One event is
written whole or not at all, so a failure half way through a close leaves
nothing behind and the op can simply be sent again.

The op's id is in that event. The projector remembers it on a `SyncOp` node
and ignores a later `op.applied` with the same id, so even two sends of one op
that cross (two servers, each seeing "not applied yet") are recorded once, on
every copy of the graph and after any rebuild. The id is remembered for as
long as the log is kept.

A command runs first on a throwaway copy of the workspace, through the same
`Maintenance` methods as every other caller. What it wrote there is then
appended to the real log as the one event. A refusal writes nothing.

Histories that read the log event by event (`explain_task`) read an
`op.applied` as the events inside it. `GET /api/maintenance/events?type=…`
does not: a device's change is listed as `op.applied`.

## Time

A change is dated when it was made, not when it arrived. `device_time` plus
`clock_offset_ms` is that moment; its day in the workspace's time zone is the
change's "today" (a status change, a tick, a close with no `on`), and an
appended note keeps the moment itself. Dates given in `args` (`on`, `at`) are
taken as given.

A clock may run up to 10 minutes ahead of the server. Past that the op is
answered `needs_decision` with reason `clock`.

## Photos

`POST /api/v1/maintenance/sync/photo?op=<the op as JSON>` with the image as
the body (or multipart field `file`). The photo's id is worked out from the
op's id, so the image is stored once however often it is sent. Once it has
been recorded, a resend may leave the body out. The answer is
`{op, photo, work_orders, points, server_time, …}`.

## The pack: what to take offline

```
POST /api/v1/maintenance/sync/pack     {"work_order_ids": [...]?, "if_mark": N?}
```

One answer with what a device needs to do its work with no connection (`read`
scope): every open work order in full, the most overdue first (at most 200;
`more` says some were left out), or just the ones named. A work order in full
is the view the app's own page reads: its position and location, tasks,
checklist and instructions, the points to read with their last readings,
failure modes and suggested parts. `briefs` are the list rows, `parts` the
catalogue (number, name, unit) for "part used", `gone` the named ids that no
longer exist.

`mark` counts the workspace's changes. Send it back as `if_mark`: when nothing
has changed the answer is `{"unchanged": true, …}` and the device keeps what
it has.
