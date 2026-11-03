---
title: "Watch a vibration or pressure sensor on your equipment"
task: "How do I send a sensor's readings to Reliafy, see its spectrum, and get an alert when one part of it grows?"
category: "Maintenance strategy"
prerequisites: "A position or item in your asset tree, and a device or script that can send JSON with an API token."
unlisted: "true"
order: 60
---

A vibration sensor sends a short burst of readings every so often, not one
number. Reliafy keeps each burst as a **snapshot**, works out its **spectrum**
(how much vibration there is at each frequency), and lets you **watch** the
part of the spectrum that matters, such as the frequency of one shaft turn.
Each watched band becomes an ordinary measurement point, so alarm limits,
trends and projected alarm dates work on it as they do on any other.

This is in beta. A slow sensor, like a pressure transducer, works the same way
without the spectrum.

## 1. Add a channel

Open **Operate → Assets → Explorer**, pick the position or item the sensor is
on, and open the **Signals** tab. Press **Add a channel** and give it:

- a **name** (for example *DE bearing*) and the **unit** the sensor reports (g,
  mm/s, kPa);
- the **axes**, if it has several (a three-way accelerometer: `X, Y, Z`);
- the **sample rate** in Hz, and the **running speed** in rpm if the machine
  has one steady speed. Speed lets you watch a band as "1× running speed" that
  follows the machine;
- the **tag** your device will send it under.

## 2. Send snapshots

Your device or gateway posts JSON to
`POST /api/ingest/maintenance/snapshots`, using an API token with the *ingest*
scope (Settings → API access):

```json
{
  "tag": "pump.vib",
  "time": "2026-11-03T10:00:00+10:00",
  "sample_rate": 3200,
  "running": true,
  "axes": {"X": [0.012, -0.034, 0.101], "Y": [0.002, 0.018, -0.044], "Z": [-0.071, 0.005, 0.063]}
}
```

- The **time needs a time zone** (`Z` or an offset). There is no "now" default.
- Send **only when the machine runs** if you can, and set `running`. A rare burst
  with the machine off is a useful picture of the sensor's own noise.
- A snapshot can be up to 5 MB, about 500,000 numbers. Longer recordings go in
  as several bursts.
- Sending the same channel and time again is safe: it is reported as a duplicate.
- A device that already makes its own spectrum can send that instead (`spectrum`),
  and a slow sensor can send a single `value`.

From the command line: `reliafy ingest snapshot burst.json`. The format is
written out in full in `docs/signal-snapshots.md` in the app's repository.

## 3. Read the spectrum

The **Spectrum** chart shows the amplitude at each frequency, in the sensor's
unit, as the peak of a sine wave of that frequency. A steady 0.5 g shake at 50 Hz
shows as a 0.5 g peak at 50 Hz.

- **Add a snapshot** overlays another burst. Pick a **baseline** (an earlier,
  healthy burst) to compare against.
- **Hover a snapshot's name** above the chart and the others fade, so you can
  tell which line is which.
- Switch axis if the channel has several.

## 4. Watch a band

**Drag across the chart** to pick a frequency range (or type it in the From and To
boxes), then press **Watch this range**. Reliafy reads the RMS vibration inside
that range from every snapshot, old and new, and draws it in **Level over time**.

- Choose **Running speed** under *Follow* to set the band in multiples of the
  machine's speed, so it stays on the 1× peak when the speed drifts.
- The band is also a **measurement point** under *Summary → Measurements*. Give it
  alarm limits there and a snapshot past the limit opens an inspection.
- **Stop watching** ends a band. What it recorded stays.

## 5. Play the history

Under **Level over time**, **Play** steps through the snapshots. The whole
history plays in about two seconds, and each snapshot is held for as long, in
proportion, as it was until the next one. A long gap shows as a long pause. The
date shows beside the slider and a marker moves along the level chart.

Nothing is drawn between two snapshots; the chart holds one spectrum until the
next is due. Play runs once and stops on the latest snapshot. Tick **Loop** to
repeat it: the latest snapshot rests a moment, and a note shows when it goes
back to the start.

## A pressure sensor

A slow pressure (a reading a minute, say) has no spectrum. Add a channel in kPa, send
`{"tag": "...", "time": "...", "value": 190.4}`, and the Signals tab draws the
readings. To trend it and set alarm limits, add a **level** with stat `value`
(`maintenance signals.add_level`): it becomes a measurement point like a band.
For a very frequent slow sensor the plain readings feed
(`POST /api/ingest/maintenance/readings`) is lighter, because it stores a number and
not a snapshot.

## What to keep in mind

- Everything is kept for now, raw readings and spectra. A three-axis burst of
  8,300 points is about 100 kB of raw readings plus its spectrum; the channel shows
  how much it holds.
- Reliafy doesn't diagnose a fault. It shows the spectrum, keeps the history, and
  tells you when a band you chose changes.
- A microphone records sound, which can include speech. Don't point one at people.
