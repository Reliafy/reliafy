# Signal snapshots: the data format

A **signal channel** is a sensor on a position or an item (a vibration sensor on a
pump, a pressure transducer on its discharge). It sends **snapshots**: a burst of
samples, a spectrum the device already made, or a single value. Reliafy
Maintenance only (beta).

Send them with `POST /api/ingest/maintenance/snapshots` (an `ingest`-scope token),
`reliafy ingest snapshot file.json`, `reliafy.push_snapshot(...)`, or the
`maintenance signals.add_snapshot` tool.

## One snapshot

```json
{
  "tag": "pump.vib",
  "time": "2026-11-03T10:00:00+10:00",
  "sample_rate": 3200,
  "unit": "g",
  "running": true,
  "rpm": 2980,
  "axes": {
    "X": [0.012, -0.034, 0.101],
    "Y": [0.002, 0.018, -0.044],
    "Z": [-0.071, 0.005, 0.063]
  }
}
```

| Field | Meaning |
|---|---|
| `tag` or `channel_id` | Which channel. The tag is set when the channel is made. |
| `time` | **Required.** ISO 8601 **with a time zone** (`Z` or an offset), or seconds since 1970. There is no "now" default, so a batch of old files isn't stamped today. |
| `axes` | `{axis name: [samples]}`: one list per axis, all the same length (at least 16). `samples` is a shorthand for a single axis. |
| `sample_rate` | Hz. Needed with samples, unless the channel has one. |
| `unit` | Optional. If given it must equal the channel's unit: Reliafy doesn't convert. |
| `running` | Optional. `true` when the machine was running (kept with the snapshot). |
| `rpm` | Optional running speed. Default: the channel's. Used by bands set in multiples of running speed. |
| `note` | Optional text. |

A batch is `{"snapshots": [ ... up to 20 ... ]}`. The answer lists each one:
`stored`, `duplicate`, or an `error` saying what to fix, plus the value each watch
band and level added.

## A spectrum the device made

```json
{
  "tag": "fan.casing",
  "time": "2026-11-03T10:00:00Z",
  "spectrum": {
    "df": 0.5,
    "amplitudes": {"X": [0.0, 0.01, 0.4, 2.0]},
    "window": "hann",
    "amplitude": "peak"
  }
}
```

`df` is Hz per line (from 0 Hz); or give `freqs: [...]`, one per line, when the lines
aren't evenly spaced. `amplitudes` is `{axis: [...]}` (or one list). `amplitude` is
`peak` (default) or `rms`. `window` is `hann`, `hamming`, `blackman`, `flattop` or
`rectangular`; an unstated window is stored as `unknown` and bands read the lines
as sent. When a snapshot has samples, Reliafy computes the spectrum from them and
doesn't store a spectrum you also sent.

## A single value (a slow pressure)

```json
{"tag": "pump.p", "time": "2026-11-03T10:00:00+10:00", "value": 190.4}
```

`values: {"axis": number}` for more than one. No spectrum is made; add a **level**
(`stat: value`) to chart it, trend it and alarm on it like any measurement point.

## What Reliafy works out

From samples, per axis, once on arrival: the spectrum (mean removed, Hann window,
single-sided, as the **peak** amplitude of a sine at each frequency, in the signal's
unit) and the overall levels: RMS, peak, crest factor (peak / RMS) and kurtosis
(3 for normal noise). The mean is ignored (a sensor offset, gravity).

A **watch band** is a frequency range (Hz, or multiples of the running speed). At
each snapshot it adds the RMS inside the range to an ordinary measurement point, so
alarm limits, trends and projected alarm dates work unchanged.

## Limits

* One snapshot is at most 5 MB of JSON (about 500,000 numbers across all axes). A
  larger one is refused with a message; send long recordings as shorter bursts.
* The same channel and time (to the millisecond) again is reported as a
  duplicate and changes nothing, so a gateway can safely resend.
* Up to 6 axes and 40 bands and levels per channel. 5,000 snapshots a day per
  workspace.
* Everything is kept for now: raw samples and the spectrum. A burst of
  8,300 points on three axes is about 100 kB raw plus the spectrum.
