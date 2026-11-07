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

**The Signals tab in the Explorer is hidden for now.** Your channels and snapshots are
kept and the API and commands below keep working, but the screens described here
(the tab, its spectrum and its bands) aren't in the app at the moment. Links to a
channel open its position's Summary.

## 1. Add a channel

Open **Assets → Explorer**, pick the position or item the sensor is
on, and open the **Signals** tab. A fitted item has no row of its own: pick
the position it's fitted to, and its channels are under **On the fitted
item** on that tab (they go with the item when it moves). Press **Add a
channel** and give it:

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

### Or add one from a file

No device yet? On the Signals tab press **Add a snapshot from a file** and choose a
file from your logger:

- **JSON** in the format above (one snapshot, or a list of up to 20);
- **CSV or text** with one column of numbers per axis (a first row of names, and a
  `time` column in seconds, are read if present);
- a **WAV** recording (each channel becomes an axis, and the sample rate comes from the
  file).

![Adding a snapshot from a CSV file: a preview of the waveform, then the time taken, sample rate and axis names](/guides/img/signals-02-add.png)

You see the number of samples and a preview of the waveform, then fill in what the
file doesn't say: **when it was taken** (in your browser's time zone; Reliafy never
guesses), the **sample rate**, and the **axis names**. If the file has too many numbers
for one snapshot (500,000 in all), the page says how many it has and offers to use
only the first part. Nothing is sent until you press **Add the snapshot**.

## 3. Read the spectrum

![The Signals tab: the spectrum of the latest snapshot against a baseline, and a watched band's level over time](/guides/img/signals-01-spectrum.png)

The **Spectrum** chart shows the amplitude at each frequency, in the sensor's
unit, as the peak of a sine wave of that frequency. A steady 0.5 g shake at 50 Hz
shows as a 0.5 g peak at 50 Hz.

- **Add a snapshot** overlays another burst. Pick a **baseline** (an earlier,
  healthy burst) to compare against.
- **Hover a snapshot's name** above the chart and the others fade, so you can
  tell which line is which.
- Switch axis if the channel has several.
- **Hz or Orders.** If the channel has a running speed, switch the horizontal axis to
  **Orders** (multiples of running speed: 1 is one turn of the shaft). Each snapshot
  uses the speed it was taken at, so a peak that follows the speed stays in place.
- **Linear or Log.** Log makes small peaks next to large ones visible.
- **Zoom** with the chart's drag-to-zoom. The first view is thinned to keep the page
  quick (the highest point of each stretch is always kept); once you zoom in, Reliafy
  fetches every spectrum line in view.
- **Running only.** If snapshots say whether the machine was running, tick
  **Running only** to leave out the stopped ones. Snapshots that don't say are kept.

## 4. Watch a band

**Drag across the chart** to pick a frequency range (or type it in the From and To
boxes), then press **Watch this range**. Reliafy reads the RMS vibration inside
that range from every snapshot, old and new, and draws it in **Level over time**.

- Choose **Running speed** under *Follow* to set the band in multiples of the
  machine's speed, so it stays on the 1× peak when the speed drifts.
- The band is also a **measurement point** under *Summary → Measurements*. Give it
  alarm limits there and a snapshot past the limit opens an inspection.
  The **Measurements** tab lists it beside every other measuring point on the
  row and everything inside it, hand-read ones too, worst first, so you can see
  a whole system's readings and record new ones in one place.
- **Stop watching** ends a band. What it recorded stays.

### Change a band, and set levels

Press **Edit** beside a band to change its name, its range, or its levels.

![Editing a band: its range and its warning and alarm levels](/guides/img/signals-03-edit-band.png)

- **Warn** levels draw a dotted line on the band's chart. **Alarm** levels draw a dashed
  line and also open an inspection when the level passes them, as for any measurement
  point. Both are labelled on the chart. Leave a level empty for none.
- A **new range** doesn't rewrite the past. The band keeps what it recorded with the old
  range, carries on with the new range from the next snapshot, and the chart marks
  where it changed. If you want the new range worked out over all the earlier
  snapshots, add it as a new band instead (which is worked out from everything stored).
- Changing only the name or the levels takes effect at once and keeps one line.

## 5. Play the history

Under **Level over time**, **Play** steps through the snapshots. The whole
history plays in about two seconds, and each snapshot is held for as long, in
proportion, as it was until the next one. A long gap shows as a long pause. The
date shows beside the slider and a marker moves along the level chart.

Nothing is drawn between two snapshots; the chart holds one spectrum until the
next is due. If you prefer, tick **Smooth transition (display only)**: one real
spectrum fades into the next just before the change. It is a display effect and
invents no data. Play runs once and stops on the latest snapshot. Tick **Loop** to
repeat it: the latest snapshot rests a moment, and a note shows when it goes
back to the start.

## Time to the limit

Under the watch bands, **Time to the limit** answers "when will this band reach its
alarm limit?" for this one machine. It uses only the band's own readings: no
failure history is needed.

In words: the level drifts up (or down) at some average rate and wobbles around
that drift, so the time to reach the limit is a spread of dates, not one date. You
get the most likely date, a range (by default the 10% to 90% dates), and a table of
the chance of reaching the limit within a week, a month, three months and so on.

- **Two ranges.** The rate is worked out from your readings, so it is itself
  uncertain. The headline range allows for that, and with few readings its late end
  may be open ("cannot be bounded"): Reliafy says so instead of inventing a date.
  The spread of the process alone (rate known exactly) is shown below it.
- **Model.** *Random walk with drift* is the usual choice and copes with a noisy
  band. *Rises only* suits wear that never goes down and refuses a band that falls
  anywhere.
- **Limit.** It uses the band's alarm limit (high limit for a rising band, low
  limit for a falling one). Type a limit in the box to ask about another level.
- **Readings from.** If the part was renewed or the load changed, pick the date to
  start from, so old readings don't pull the trend.
- **Too little data.** With fewer than 6 readings, a band that is flat or heading
  away from the limit, or readings that fall exactly on a straight line, you get a
  plain message and no dates. With fewer than 12 readings the answer carries a
  "rough guide" note.

This is the time to the limit you chose, not to failure. It assumes the rate stays
as it has been, so a change in load, speed or maintenance makes it wrong.

Two buttons send the trend on. **Use in a degradation model** puts a copy of the
readings in Data (one row per reading: unit, age in days, value) and opens
[Degradation models](/models/degradation) on it, where you pick the threshold.
**Watch in Risk** adds a copy as an item of a tracked fleet in
[Condition monitoring](/risk). Both are copies as of today: they don't update when
new snapshots arrive, and the band's own series stays where it is. Age is counted
from the first reading used, not from when the part was fitted.

## Running speed from another sensor

A machine whose speed varies can have a **speed channel**: a second channel in rpm that
sends single values. Open **Running speed** on the Signals tab and choose it under
*Or take the speed from*. Each new snapshot then uses that channel's reading nearest
in time (within an hour), and falls back to the fixed rpm if there is none. Send the
speed reading before the burst or together with it: a speed that arrives later is not
applied to a snapshot already stored.

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
  8,300 points is about 100 kB of raw readings plus its spectrum. The tab shows how
  many snapshots the workspace holds and how much room they take. **Warn me at a
  size** sets a level at which the tab reminds you; it deletes nothing.
- Reliafy doesn't diagnose a fault. It shows the spectrum, keeps the history, and
  tells you when a band you chose changes.
- A microphone records sound, which can include speech. Don't point one at people.
