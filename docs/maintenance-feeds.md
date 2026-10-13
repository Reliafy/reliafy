# Automated readings for Reliafy Maintenance

A measurement point either **counts use** (run hours, cycles, km) or shows
**condition** (vibration, temperature, wear). Its readings are entered by hand,
or **fed automatically**: a sensor, a PLC, a historian or Home Assistant posts
them to Reliafy under the point's **tag**.

- Manual readings are records in the maintenance event log.
- Fed readings go to the time-series store; only what they cause (an alarm
  crossed, a work order raised) goes into the log.
- A counter's feed drives tasks by use: the due date is projected from its
  recent rate. A condition feed past an alarm limit opens an inspection, one at a
  time per point.

## Set up a fed point

1. In Reliafy Maintenance, open the position, **Add a measurement**, choose
   *A feed* and give the tag your feed will send (e.g. `sensor.pool_pump_hours`).
2. In **Settings → API access**, create a token with the **ingest** scope.

## The endpoint

```
POST /api/ingest/maintenance/readings
Authorization: Bearer rlf_…
Content-Type: application/json

{"readings": [{"tag": "sensor.pool_pump_hours", "value": 1234.5, "time": "2026-10-13T10:00:00+10:00"}]}
```

`time` is optional (now), ISO 8601 or seconds since 1970. CSV works too
(`Content-Type: text/csv`, columns `tag,value,time`). Up to 10,000 readings a
request; 120 requests a minute. The response says how many were stored, any
tags no point uses, and any inspections raised.

## Home Assistant

`configuration.yaml`:

```yaml
rest_command:
  reliafy_reading:
    url: "https://reliafy.com/api/ingest/maintenance/readings"
    method: POST
    headers:
      Authorization: !secret reliafy_token   # "Bearer rlf_…"
      Content-Type: application/json
    payload: '{"readings": [{"tag": "{{ tag }}", "value": {{ value }}}]}'
```

An automation sending the pool pump's run hours every hour (a `history_stats`
or utility-meter sensor gives the hours):

```yaml
automation:
  - alias: "Reliafy: pool pump hours"
    trigger:
      - platform: time_pattern
        minutes: 0
    action:
      - service: rest_command.reliafy_reading
        data:
          tag: sensor.pool_pump_hours
          value: "{{ states('sensor.pool_pump_hours') }}"
```

A temperature on change works the same way, with a `state` trigger.
