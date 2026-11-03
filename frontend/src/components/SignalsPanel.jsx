import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import Plot from "./Plot.jsx";
import { useConfirm } from "./ConfirmProvider.jsx";
import {
  addSignalBand, createSignalChannel, getSignalChannel, getSignalSpectra, listSignalChannels, previewSignalBand,
  removeSignalBand,
} from "../api.js";
import { ACCENT, COLORWAY, DANGER, REFERENCE } from "../plotTheme.js";
import {
  DEFAULT_LOOP_MS, SPEEDS, bandLabel, defaultPicks, elapsedFor, fmt, fmtBytes, fmtWhen, frameAt, toOrders,
} from "../signals.js";
import TimeToLimit from "./TimeToLimit.jsx";
import "./SignalsPanel.css";

// The Signals tab of the Explorer's panel (Operate › Assets › Explorer): the
// sensors on a position or an item that send snapshots (vibration bursts,
// spectra, pressures). One spectrum chart (overlay chosen snapshots and a
// baseline; hover a legend entry to find a snapshot; drag a frequency range to
// save it as a watch band), the band's level over time, and a player that steps
// through the history. Nothing is drawn between two snapshots: the chart holds
// one until the next is due.

const GUIDE = "/guides/signal-channels";
const SPECTRA_PER_REQUEST = 40;

export default function SignalsPanel({ row }) {
  const target = row.type === "item" ? { itemId: row.key } : { positionId: row.key };
  const [list, setList] = useState(null);
  const [error, setError] = useState(null);
  const [picked, setPicked] = useState(null); // channel id
  const [adding, setAdding] = useState(false);

  const load = useCallback(() => {
    setError(null);
    return listSignalChannels(target)
      .then((d) => setList(d.channels))
      .catch((e) => setError(e.message));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [row.key, row.type]);
  useEffect(() => {
    setList(null);
    setPicked(null);
    setAdding(false);
    load();
  }, [load]);

  if (error) return <p className="sg-note sg-bad" role="alert">Couldn't load the signals: {error}</p>;
  if (!list) return <p className="sg-note">Loading…</p>;
  const channel = list.find((c) => c.id === picked) || list[0];

  return (
    <div className="sg">
      {list.length === 0 && !adding && (
        <div className="card sg-empty">
          <h3>No sensor channels here yet</h3>
          <p>
            A signal channel takes snapshots from a sensor on this {row.type === "item" ? "item" : "position"}: a
            vibration burst, a spectrum the device already made, or a pressure. Reliafy works out the spectrum,
            lets you watch a frequency band over time, and raises an inspection when a band passes its limit.
          </p>
          <div className="sg-actions">
            <button type="button" onClick={() => setAdding(true)}>Add a channel</button>
            <Link to={GUIDE}>How signal channels work</Link>
          </div>
        </div>
      )}
      {adding && (
        <NewChannel target={target} onCancel={() => setAdding(false)}
                    onDone={(c) => { setAdding(false); setPicked(c.id); load(); }} />
      )}
      {list.length > 0 && !adding && (
        <div className="sg-bar">
          {list.length > 1 ? (
            <label className="sg-field">Channel
              <select value={channel.id} onChange={(e) => setPicked(e.target.value)}>
                {list.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </label>
          ) : <strong className="sg-name">{channel.name}</strong>}
          <button type="button" className="secondary sm" onClick={() => setAdding(true)}>Add a channel</button>
          <Link className="sg-help" to={GUIDE}>Guide</Link>
        </div>
      )}
      {channel && !adding && <ChannelView key={channel.id} summary={channel} onChanged={load} />}
    </div>
  );
}

function NewChannel({ target, onDone, onCancel }) {
  const [f, setF] = useState({ name: "", unit: "g", axes: "", sample_rate: "", rpm: "", tag: "" });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const set = (k) => (e) => setF((x) => ({ ...x, [k]: e.target.value }));
  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const axes = f.axes.split(",").map((a) => a.trim()).filter(Boolean);
      const made = await createSignalChannel({
        position_id: target.positionId, item_id: target.itemId, name: f.name, unit: f.unit,
        ...(axes.length ? { axes } : {}), ...(f.sample_rate ? { sample_rate: Number(f.sample_rate) } : {}),
        ...(f.rpm ? { rpm: Number(f.rpm) } : {}), tag: f.tag,
      });
      onDone(made);
    } catch (x) {
      setErr(x.message);
      setBusy(false);
    }
  };
  return (
    <form className="card sg-new" onSubmit={submit}>
      <h3>Add a signal channel</h3>
      <div className="sg-grid">
        <label className="sg-field">Name<input value={f.name} onChange={set("name")} required maxLength={200} placeholder="DE bearing" /></label>
        <label className="sg-field">Unit<input value={f.unit} onChange={set("unit")} required maxLength={20} placeholder="g, mm/s, kPa" /></label>
        <label className="sg-field">Axes (optional)<input value={f.axes} onChange={set("axes")} placeholder="X, Y, Z" /></label>
        <label className="sg-field">Sample rate, Hz (optional)<input type="number" inputMode="decimal" min="0" step="any" value={f.sample_rate} onChange={set("sample_rate")} /></label>
        <label className="sg-field">Running speed, rpm (optional)<input type="number" inputMode="decimal" min="0" step="any" value={f.rpm} onChange={set("rpm")} /></label>
        <label className="sg-field">Tag the device sends<input value={f.tag} onChange={set("tag")} maxLength={200} placeholder="pump.vib" /></label>
      </div>
      {err && <p className="sg-note sg-bad" role="alert">{err}</p>}
      <div className="sg-actions">
        <button type="submit" disabled={busy || !f.name.trim() || !f.unit.trim()}>{busy ? "Adding…" : "Add the channel"}</button>
        <button type="button" className="secondary" onClick={onCancel}>Cancel</button>
      </div>
    </form>
  );
}

function ChannelView({ summary, onChanged }) {
  const confirm = useConfirm();
  const [ch, setCh] = useState(null);
  const [error, setError] = useState(null);
  const [axis, setAxis] = useState(null);
  const [picked, setPicked] = useState([]);
  const [baseline, setBaseline] = useState(null);
  const [hot, setHot] = useState(null); // the legend entry under the pointer
  const [range, setRange] = useState(null); // { low, high } in Hz
  const [tick, setTick] = useState(0); // spectra arrived
  const cache = useRef(new Map()); // "axis|id" -> { freqs, amps } | "loading"
  const [bandSel, setBandSel] = useState("preview");
  const [preview, setPreview] = useState(null);
  const [notice, setNotice] = useState(null);

  const reload = useCallback(() => getSignalChannel(summary.id).then((d) => {
    setCh(d);
    return d;
  }), [summary.id]);

  useEffect(() => {
    let live = true;
    reload().then((d) => {
      if (!live) return;
      const a = d.axes?.[0] || d.snapshots.index[0] && Object.keys(d.snapshots.index[0].levels || {})[0] || "value";
      setAxis(a);
      const p = defaultPicks(d.snapshots.index);
      setPicked(p.picked);
      setBaseline(p.baseline);
    }).catch((e) => live && setError(e.message));
    return () => { live = false; };
  }, [reload]);

  const index = ch?.snapshots.index || [];
  const axes = useMemo(() => {
    if (!ch) return [];
    if (ch.axes?.length) return ch.axes;
    const seen = new Set();
    for (const s of index) Object.keys(s.levels || {}).forEach((k) => seen.add(k));
    return [...seen];
  }, [ch, index]);
  const byId = useMemo(() => new Map(index.map((s) => [s.id, s])), [index]);
  const withSpectrum = useMemo(() => index.filter((s) => s.source !== "value"), [index]);
  const hasSpectra = withSpectrum.length > 0;

  // Fetch the spectra asked for (those not already in the cache).
  const need = useCallback(async (ids) => {
    if (!axis) return;
    const todo = ids.filter((id) => !cache.current.has(`${axis}|${id}`) && byId.get(id)?.source !== "value");
    for (const id of todo) cache.current.set(`${axis}|${id}`, "loading");
    for (let i = 0; i < todo.length; i += SPECTRA_PER_REQUEST) {
      const chunk = todo.slice(i, i + SPECTRA_PER_REQUEST);
      try {
        const got = await getSignalSpectra(summary.id, chunk, { axis });
        for (const sp of got.spectra) {
          const s = sp.spectrum;
          cache.current.set(`${axis}|${sp.id}`, s ? { freqs: s.freqs, amps: s.amplitudes[axis] || Object.values(s.amplitudes)[0] } : null);
        }
      } catch (e) {
        for (const id of chunk) cache.current.delete(`${axis}|${id}`);
        setNotice(e.message);
      }
      setTick((t) => t + 1);
    }
  }, [axis, byId, summary.id]);

  // The player.
  const times = useMemo(() => withSpectrum.map((s) => new Date(s.t).getTime()), [withSpectrum]);
  const [playing, setPlaying] = useState(false);
  const [head, setHead] = useState(null); // index into withSpectrum while playing or scrubbed
  const [speed, setSpeed] = useState(1);
  const [loop, setLoop] = useState(false);
  const [cue, setCue] = useState(false);
  const [loadingAll, setLoadingAll] = useState(false);
  const clock = useRef({ start: 0, from: 0 });

  const play = async () => {
    if (!withSpectrum.length) return;
    setLoadingAll(true);
    await need(withSpectrum.map((s) => s.id));
    setLoadingAll(false);
    const from = head != null && head < withSpectrum.length - 1 ? elapsedFor(times, head, DEFAULT_LOOP_MS) : 0;
    clock.current = { start: performance.now(), from, speed };
    setHead(head != null && head < withSpectrum.length - 1 ? head : 0);
    setPlaying(true);
  };
  useEffect(() => {
    if (!playing) return undefined;
    let raf = 0;
    const step = (now) => {
      const { start, from } = clock.current;
      const f = frameAt(times, from + (now - start) * speed, { loopMs: DEFAULT_LOOP_MS, loop });
      setHead(f.index);
      setCue(f.wrapped);
      if (f.done) {
        setPlaying(false);
        return;
      }
      raf = requestAnimationFrame(step);
    };
    // Speed changes carry on from where the head is.
    clock.current = { start: performance.now(), from: head != null ? elapsedFor(times, head, DEFAULT_LOOP_MS) : 0 };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playing, speed, loop, times]);

  const scrub = (i) => {
    setPlaying(false);
    setCue(false);
    setHead(i);
    need([withSpectrum[i].id]);
  };

  // Spectra for what's picked, when the axis or picks change.
  useEffect(() => {
    if (!axis || !ch) return;
    need([...picked, ...(baseline ? [baseline] : [])]);
  }, [axis, ch, picked, baseline, need]);

  // Preview the dragged range's level over time.
  useEffect(() => {
    if (!range || !axis || !hasSpectra || range.high <= range.low) { setPreview(null); return undefined; }
    let live = true;
    const t = setTimeout(() => {
      previewSignalBand(summary.id, { low: range.low, high: range.high, axis })
        .then((d) => live && setPreview(d.series))
        .catch(() => live && setPreview(null));
    }, 300);
    return () => { live = false; clearTimeout(t); };
  }, [range, axis, hasSpectra, summary.id]);

  if (error) return <p className="sg-note sg-bad" role="alert">Couldn't load this channel: {error}</p>;
  if (!ch || !axis) return <p className="sg-note">Loading…</p>;

  const unit = ch.unit;
  const last = index[index.length - 1];
  const sel = (id) => {
    const c = cache.current.get(`${axis}|${id}`);
    return c && c !== "loading" ? c : null;
  };

  // ---- the spectrum chart
  const traces = [];
  const entries = [];
  if (baseline && byId.get(baseline)) entries.push({ id: baseline, kind: "baseline", color: REFERENCE });
  picked.forEach((id, n) => { if (byId.get(id) && id !== baseline) entries.push({ id, kind: "snapshot", color: COLORWAY[(n + 1) % COLORWAY.length] }); });
  const headId = head != null ? withSpectrum[head]?.id : null;
  const labelOf = (id) => fmtWhen(byId.get(id)?.t);
  const dim = (id) => (hot && hot !== id ? 0.15 : 1);
  for (const e of entries) {
    const s = sel(e.id);
    if (!s) continue;
    traces.push({
      type: "scatter", mode: "lines", x: s.freqs, y: s.amps, name: labelOf(e.id), opacity: dim(e.id),
      line: { color: e.color, width: hot === e.id ? 2.6 : 1.3, dash: e.kind === "baseline" ? "dot" : "solid" },
      hovertemplate: `%{x:.4g} Hz<br>%{y:.3g} ${unit}<extra>${labelOf(e.id)}</extra>`,
    });
  }
  const hs = headId ? sel(headId) : null;
  if (hs) {
    traces.push({
      type: "scatter", mode: "lines", x: hs.freqs, y: hs.amps, name: labelOf(headId),
      line: { color: ACCENT, width: 2.2 },
      hovertemplate: `%{x:.4g} Hz<br>%{y:.3g} ${unit}<extra>${labelOf(headId)}</extra>`,
    });
  }
  const shapes = range && range.high > range.low
    ? [{ type: "rect", xref: "x", yref: "paper", x0: range.low, x1: range.high, y0: 0, y1: 1,
         fillcolor: "rgba(47,109,246,0.12)", line: { width: 0 }, layer: "below" }] : [];
  for (const b of ch.bands.filter((x) => !x.retired && x.rule.type === "band" && x.rule.axis === axis && x.rule.in === "Hz")) {
    shapes.push({ type: "rect", xref: "x", yref: "paper", x0: b.rule.low, x1: b.rule.high, y0: 0, y1: 0.04,
                  fillcolor: "rgba(20,23,28,0.35)", line: { width: 0 } });
  }
  const spectrumLayout = {
    height: 320, dragmode: "select", selectdirection: "h", hovermode: "closest", showlegend: false,
    xaxis: { title: { text: "Frequency (Hz)" }, rangemode: "tozero" },
    yaxis: { title: { text: `Amplitude (${unit}, peak)` }, rangemode: "tozero" },
    shapes, margin: { t: 8 },
  };
  const onSelected = (ev) => {
    const x = ev?.range?.x;
    if (x && x[1] > x[0]) setRange({ low: Math.max(0, Number(fmt(x[0], 4))), high: Number(fmt(x[1], 4)) });
  };

  // ---- the band chart
  const bands = ch.bands.filter((b) => !b.retired);
  const chosen = bands.find((b) => b.point_id === bandSel) || null;
  const bandSeries = chosen ? chosen.series : preview;
  const bandUnit = chosen ? chosen.unit : unit;
  const headTime = headId ? byId.get(headId)?.t : last?.t;
  const markerAt = (series) => {
    if (!series || head == null) return null;
    const t0 = new Date(headTime).getTime();
    const hit = series.find((p) => Math.abs(new Date(p.t).getTime() - t0) < 1000);
    return hit ? hit : null;
  };
  const marker = markerAt(bandSeries);
  const bandTraces = bandSeries && bandSeries.length ? [
    { type: "scatter", mode: "lines+markers", x: bandSeries.map((p) => p.t), y: bandSeries.map((p) => p.value),
      line: { color: REFERENCE, width: 1.5, shape: "hv" }, marker: { size: 4, color: REFERENCE }, name: "Band level",
      hovertemplate: `%{x|%d %b %Y %H:%M}<br>%{y:.3g} ${bandUnit}<extra></extra>` },
    ...(marker ? [{ type: "scatter", mode: "markers", x: [marker.t], y: [marker.value], name: "Now showing",
                    marker: { size: 12, color: ACCENT, line: { color: "#fff", width: 2 } }, hoverinfo: "skip" }] : []),
  ] : [];
  const limitShapes = chosen ? [chosen.alarm_above, chosen.alarm_below].filter((v) => v !== null && v !== undefined)
    .map((v) => ({ type: "line", xref: "paper", x0: 0, x1: 1, yref: "y", y0: v, y1: v, line: { color: DANGER, width: 1, dash: "dash" } })) : [];

  const saveBand = async (form) => {
    const rpm = ch.rpm;
    const orders = form.unit === "orders";
    const body = {
      name: form.name.trim(), axis, unit: form.unit,
      low: orders ? Number(fmt(toOrders(range.low, rpm), 4)) : range.low,
      high: orders ? Number(fmt(toOrders(range.high, rpm), 4)) : range.high,
    };
    const made = await addSignalBand(summary.id, body);
    await reload();
    setBandSel(made.point_id);
    setNotice(`Saved “${body.name}”. It now adds a level to every snapshot${made.history_written ? ` (${made.history_written} stored so far)` : ""} and is listed under Measurements.`);
    onChanged?.();
  };
  const removeBand = async (b) => {
    if (!(await confirm({
      title: `Stop watching “${b.name}”?`,
      body: "It stops adding values to its measurement point. What it has recorded stays.",
      confirmLabel: "Stop watching",
    }))) return;
    await removeSignalBand(b.point_id);
    if (bandSel === b.point_id) setBandSel("preview");
    await reload();
    onChanged?.();
  };

  const more = ch.snapshots.count > ch.snapshots.shown;
  return (
    <>
      <p className="sg-meta">
        {ch.snapshots.count === 0 ? "No snapshots yet." : (
          <>Last snapshot {fmtWhen(last?.t)} · {ch.snapshots.count.toLocaleString("en-GB")} snapshot{ch.snapshots.count === 1 ? "" : "s"}
            {ch.rpm ? <> · {fmt(ch.rpm, 4)} rpm</> : null} · {fmtBytes(ch.snapshots.bytes)} held · {unit}</>
        )}
      </p>
      {ch.snapshots.count === 0 && (
        <div className="card sg-empty">
          <h3>Waiting for the first snapshot</h3>
          <p>
            Send a snapshot from the sensor{ch.tag ? <> under the tag <code>{ch.tag}</code></> : null}, with an API token
            that can ingest, to <code>POST /api/ingest/maintenance/snapshots</code>. The guide has the format and an example.
          </p>
          <div className="sg-actions"><Link to={GUIDE}>How to send snapshots</Link></div>
        </div>
      )}
      {notice && <p className="sg-note" role="status">{notice} <button type="button" className="link" onClick={() => setNotice(null)}>Dismiss</button></p>}

      {ch.snapshots.count > 0 && !hasSpectra && <ScalarSeries ch={ch} axis={axis} axes={axes} setAxis={setAxis} />}

      {hasSpectra && (
        <section className="card sg-card" aria-label="Spectrum">
          <div className="sg-bar">
            <h3 className="sg-h">Spectrum</h3>
            {axes.length > 1 && (
              <label className="sg-field">Axis
                <select value={axis} onChange={(e) => setAxis(e.target.value)}>{axes.map((a) => <option key={a}>{a}</option>)}</select>
              </label>
            )}
            <label className="sg-field">Add a snapshot
              <select value="" onChange={(e) => e.target.value && setPicked((p) => (p.includes(e.target.value) ? p : [...p, e.target.value].slice(-8)))}>
                <option value="">Choose…</option>
                {[...withSpectrum].reverse().map((s) => <option key={s.id} value={s.id}>{fmtWhen(s.t)}{s.running === false ? " (stopped)" : ""}</option>)}
              </select>
            </label>
            <label className="sg-field">Baseline
              <select value={baseline || ""} onChange={(e) => setBaseline(e.target.value || null)}>
                <option value="">None</option>
                {withSpectrum.map((s) => <option key={s.id} value={s.id}>{fmtWhen(s.t)}</option>)}
              </select>
            </label>
          </div>
          <ul className="sg-legend" aria-label="Snapshots on the chart" onMouseLeave={() => setHot(null)}>
            {entries.map((e) => (
              <li key={e.id}>
                <span className="sg-chip" tabIndex={0} onMouseEnter={() => setHot(e.id)} onFocus={() => setHot(e.id)} onBlur={() => setHot(null)}>
                  <span className="sg-swatch" style={{ background: e.color }} aria-hidden="true" />
                  {labelOf(e.id)}{e.kind === "baseline" ? " (baseline)" : ""}
                  <button type="button" className="sg-x" aria-label={`Remove ${labelOf(e.id)} from the chart`}
                          onClick={() => (e.kind === "baseline" ? setBaseline(null) : setPicked((p) => p.filter((x) => x !== e.id)))}>×</button>
                </span>
              </li>
            ))}
            {headId && <li><span className="sg-chip sg-chip-now"><span className="sg-swatch" style={{ background: ACCENT }} aria-hidden="true" />Showing {labelOf(headId)}</span></li>}
          </ul>
          <Plot data={traces} layout={spectrumLayout} onSelected={onSelected} download={`${ch.name} spectrum`} />
          {!traces.length && <p className="sg-note">Loading spectra…</p>}
          <p className="sg-hint">Drag across the chart to pick a frequency range, or type it below.</p>

          <BandForm range={range} setRange={setRange} rpm={ch.rpm} axis={axis}
                    onSave={saveBand} />
        </section>
      )}

      {hasSpectra && (
        <section className="card sg-card" aria-label="Level over time">
          <div className="sg-bar">
            <h3 className="sg-h">Level over time</h3>
            <label className="sg-field">Band
              <select value={bandSel} onChange={(e) => setBandSel(e.target.value)}>
                <option value="preview">{range ? "The range picked above (not saved)" : "Pick a range above"}</option>
                {bands.map((b) => <option key={b.point_id} value={b.point_id}>{b.name}</option>)}
              </select>
            </label>
          </div>
          {bandSeries && bandSeries.length > 0 ? (
            <Plot data={bandTraces}
                  layout={{ height: 200, showlegend: false, hovermode: "closest", margin: { t: 8 }, shapes: limitShapes,
                            xaxis: { type: "date" }, yaxis: { title: { text: `RMS level (${bandUnit || "units"})` }, rangemode: "tozero" } }}
                  download={`${ch.name} band level`} />
          ) : (
            <p className="sg-note">{chosen ? "This band has no values yet." : "Drag a range on the spectrum to see how its level has changed."}</p>
          )}
          <Player
            times={times} withSpectrum={withSpectrum} head={head} playing={playing} loop={loop} setLoop={setLoop}
            speed={speed} setSpeed={setSpeed} cue={cue} loading={loadingAll} onPlay={play}
            onPause={() => setPlaying(false)} onScrub={scrub} />
        </section>
      )}

      {bands.length > 0 && (
        <section className="card sg-card" aria-label="Watch bands">
          <h3 className="sg-h">Watch bands and levels</h3>
          <div className="maint-scroll">
            <table className="sg-table">
              <thead><tr><th>Name</th><th>What it reads</th><th>Latest</th><th /></tr></thead>
              <tbody>
                {bands.map((b) => (
                  <tr key={b.point_id}>
                    <td>{b.name}</td>
                    <td>{bandLabel(b.rule)}</td>
                    <td>{b.latest ? <>{fmt(b.latest.value)} {b.unit}{b.status !== "ok" ? <strong className="sg-bad"> ({b.status})</strong> : null}</> : "–"}</td>
                    <td><button type="button" className="ghost sm" onClick={() => removeBand(b)}>Stop watching</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="sg-hint">Each band is also a measurement point (see Summary › Measurements), so its alarm limits, trend and projected alarm date work as for any other.</p>
        </section>
      )}
      {bands.length > 0 && <TimeToLimit bands={bands} channelName={ch.name} selectedId={bandSel === "preview" ? null : bandSel} />}
      {more && <p className="sg-hint">Showing the latest {ch.snapshots.shown} of {ch.snapshots.count.toLocaleString("en-GB")} snapshots.</p>}
    </>
  );
}

function BandForm({ range, setRange, rpm, onSave, axis }) {
  const [name, setName] = useState("");
  const [unit, setUnit] = useState("Hz");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const low = range?.low ?? "";
  const high = range?.high ?? "";
  const valid = range && range.high > range.low && range.low >= 0;
  const set = (k) => (e) => {
    const v = e.target.value === "" ? "" : Number(e.target.value);
    setRange((r) => ({ low: r?.low ?? 0, high: r?.high ?? 0, [k]: v }));
  };
  const suggested = valid
    ? unit === "orders" ? `${fmt(toOrders(range.low, rpm), 3)}–${fmt(toOrders(range.high, rpm), 3)}× speed` : `${fmt(range.low, 4)}–${fmt(range.high, 4)} Hz`
    : "";
  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      await onSave({ name: name || `Band ${suggested}`, unit });
      setName("");
    } catch (x) {
      setErr(x.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <form className="sg-band" onSubmit={submit}>
      <label className="sg-field">From (Hz)<input type="number" inputMode="decimal" min="0" step="any" value={low} onChange={set("low")} /></label>
      <label className="sg-field">To (Hz)<input type="number" inputMode="decimal" min="0" step="any" value={high} onChange={set("high")} /></label>
      <label className="sg-field">Name<input value={name} onChange={(e) => setName(e.target.value)} placeholder={suggested || "Band name"} maxLength={200} /></label>
      {rpm ? (
        <label className="sg-field">Follow
          <select value={unit} onChange={(e) => setUnit(e.target.value)}>
            <option value="Hz">These Hz</option>
            <option value="orders">Running speed ({fmt(rpm, 4)} rpm)</option>
          </select>
        </label>
      ) : null}
      <button type="submit" disabled={!valid || busy}>{busy ? "Saving…" : "Watch this range"}</button>
      {range && <button type="button" className="ghost" onClick={() => setRange(null)}>Clear</button>}
      {err && <p className="sg-note sg-bad" role="alert">{err}</p>}
      {valid && <p className="sg-hint sg-full">Watches the RMS level of axis {axis} in this range at every snapshot{unit === "orders" ? ", moving with the speed each snapshot was taken at" : ""}.</p>}
    </form>
  );
}

function Player({ times, withSpectrum, head, playing, loop, setLoop, speed, setSpeed, cue, loading, onPlay, onPause, onScrub }) {
  const n = withSpectrum.length;
  if (n < 2) return <p className="sg-hint">The player needs at least two snapshots.</p>;
  const shown = head ?? n - 1;
  return (
    <div className="sg-player" role="group" aria-label="Play through the snapshots">
      <button type="button" className="sg-play" onClick={playing ? onPause : onPlay} disabled={loading}
              aria-label={playing ? "Pause" : "Play through the snapshots"}>
        {loading ? "Loading…" : playing ? "❚❚ Pause" : "▶ Play"}
      </button>
      <input type="range" min={0} max={n - 1} value={shown} onChange={(e) => onScrub(Number(e.target.value))}
             aria-label="Snapshot" aria-valuetext={fmtWhen(withSpectrum[shown].t)} />
      <output className="sg-date" aria-live="off">{fmtWhen(withSpectrum[shown].t)}</output>
      <label className="sg-field sg-inline">Speed
        <select value={speed} onChange={(e) => setSpeed(Number(e.target.value))}>
          {SPEEDS.map((s) => <option key={s} value={s}>{s}×</option>)}
        </select>
      </label>
      <label className="sg-check"><input type="checkbox" checked={loop} onChange={(e) => setLoop(e.target.checked)} /> Loop</label>
      {cue && <span className="sg-cue" role="status">↺ Back to the first snapshot</span>}
      <p className="sg-hint sg-full">
        The whole history plays in about {DEFAULT_LOOP_MS / 1000} seconds. Each snapshot is held for as long, in proportion,
        as it was until the next, so a long gap shows as a long pause. Nothing is drawn in between.
      </p>
    </div>
  );
}

// A channel whose snapshots are single values (a pressure): no spectrum, just the series.
function ScalarSeries({ ch, axis, axes, setAxis }) {
  const idx = ch.snapshots.index;
  const rows = idx.map((s) => ({ t: s.t, v: s.levels?.[axis]?.value })).filter((r) => r.v !== undefined && r.v !== null);
  return (
    <section className="card sg-card" aria-label="Readings">
      <div className="sg-bar">
        <h3 className="sg-h">Readings</h3>
        {axes.length > 1 && (
          <label className="sg-field">Axis<select value={axis} onChange={(e) => setAxis(e.target.value)}>{axes.map((a) => <option key={a}>{a}</option>)}</select></label>
        )}
      </div>
      <Plot data={[{ type: "scatter", mode: "lines+markers", x: rows.map((r) => r.t), y: rows.map((r) => r.v),
                     line: { color: ACCENT, width: 1.5 }, marker: { size: 4 }, name: ch.name,
                     hovertemplate: `%{x|%d %b %Y %H:%M}<br>%{y:.4g} ${ch.unit}<extra></extra>` }]}
            layout={{ height: 240, showlegend: false, margin: { t: 8 }, xaxis: { type: "date" }, yaxis: { title: { text: ch.unit } } }}
            download={`${ch.name} readings`} />
      <p className="sg-hint">
        These are single values, with no spectrum. To trend them and set alarm limits, add a level (<code>signals.add_level</code>,
        stat <code>value</code>): it becomes a measurement point. See the <Link to={GUIDE}>guide</Link>.
      </p>
    </section>
  );
}
