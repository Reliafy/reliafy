import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import Plot from "./Plot.jsx";
import { useConfirm } from "./ConfirmProvider.jsx";
import {
  addSignalBand, createSignalChannel, getSignalChannel, getSignalSpectra, listSignalChannels, previewSignalBand,
  removeSignalBand, updateSignalChannel,
} from "../api.js";
import { ACCENT, COLORWAY, DANGER, REFERENCE, WARNING } from "../plotTheme.js";
import {
  DEFAULT_LOOP_MS, SPEEDS, bandLabel, convertRange, defaultPicks, dropStopped, elapsedFor, fadeWeights, fmt, fmtBytes,
  fmtWhen, frameAt, hzRange, limitLines, runningOnly, xFor,
} from "../signals.js";
import SignalSnapshotForm from "./SignalSnapshotForm.jsx";
import SignalBandEditor from "./SignalBandEditor.jsx";
import SignalStorage from "./SignalStorage.jsx";
import "./SignalsPanel.css";

const flag = (key, fallback = false) => {
  try {
    const v = window.localStorage.getItem(key);
    return v === null ? fallback : v === "1";
  } catch {
    return fallback;
  }
};
const saveFlag = (key, on) => {
  try { window.localStorage.setItem(key, on ? "1" : "0"); } catch { /* private window: it just won't be remembered */ }
};

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
  const [storageTick, setStorageTick] = useState(0);

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
      <SignalStorage refresh={storageTick} />
      {channel && !adding && (
        <ChannelView key={channel.id} summary={channel} all={list}
                     onChanged={() => { setStorageTick((t) => t + 1); return load(); }} />
      )}
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

function ChannelView({ summary, all, onChanged }) {
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
  const [xUnit, setXUnit] = useState("Hz"); // the chart's x axis: Hz or orders (multiples of running speed)
  const [logY, setLogY] = useState(false);
  const [runOnly, setRunOnly] = useState(() => flag(`signals.runningOnly.${summary.id}`));
  const [fade, setFade] = useState(false);
  const [blend, setBlend] = useState(0); // progress through the current hold, for the fade
  const [view, setView] = useState(null); // the zoomed x range [a, b] in the chart's unit
  const [detail, setDetail] = useState(null); // { key, data: Map id -> { freqs, amps }, full }
  const [addingSnap, setAddingSnap] = useState(false);
  const [editing, setEditing] = useState(null); // point id of the band being edited

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
      const p = defaultPicks(runningOnly(d.snapshots.index, flag(`signals.runningOnly.${summary.id}`)));
      setPicked(p.picked);
      setBaseline(p.baseline);
    }).catch((e) => live && setError(e.message));
    return () => { live = false; };
  }, [reload]);

  const allIndex = ch?.snapshots.index || [];
  const index = useMemo(() => runningOnly(allIndex, runOnly), [allIndex, runOnly]);
  const hasFlags = allIndex.some((s) => s.running === false);
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
      setBlend(f.progress || 0);
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
    setBlend(0);
    setHead(i);
    need([withSpectrum[i].id]);
  };

  const toggleRunOnly = (on) => {
    setRunOnly(on);
    saveFlag(`signals.runningOnly.${summary.id}`, on);
    setPlaying(false);
    setHead(null);
    const p = defaultPicks(runningOnly(allIndex, on));
    setPicked(p.picked);
    setBaseline(p.baseline);
  };

  // The x axis unit: a picked range follows it (in orders it needs a running speed).
  const changeUnit = (u) => {
    if (u === xUnit) return;
    setRange((r) => convertRange(r, xUnit, u, ch?.rpm));
    setView(null);
    setDetail(null);
    setXUnit(u);
  };

  // Spectra for what's picked, when the axis or picks change.
  useEffect(() => {
    if (!axis || !ch) return;
    need([...picked, ...(baseline ? [baseline] : [])]);
  }, [axis, ch, picked, baseline, need]);

  // Zoomed in: ask the server for every line in the visible range (the first view is thinned).
  const speedOf = useCallback((id) => byId.get(id)?.rpm || ch?.rpm || null, [byId, ch]);
  const viewKey = view ? `${view[0]}|${view[1]}|${xUnit}|${axis}` : null;
  useEffect(() => {
    if (!view || !axis || !ch) { setDetail(null); return undefined; }
    const ids = [...new Set([...picked, ...(baseline ? [baseline] : []), ...(head != null && withSpectrum[head] ? [withSpectrum[head].id] : [])])]
      .filter((id) => byId.get(id) && byId.get(id).source !== "value");
    let live = true;
    const t = setTimeout(async () => {
      const data = new Map();
      let full = true;
      await Promise.all(ids.map(async (id) => {
        const r = hzRange(view[0], view[1], speedOf(id), xUnit);
        if (!r) return;
        try {
          const got = await getSignalSpectra(summary.id, [id], { axis, maxPoints: 4000, fMin: r.f_min, fMax: r.f_max });
          const sp = got.spectra[0]?.spectrum;
          if (sp) {
            data.set(id, { freqs: sp.freqs, amps: sp.amplitudes[axis] || Object.values(sp.amplitudes)[0] });
            if (sp.decimated) full = false;
          }
        } catch { full = false; }
      }));
      if (live) setDetail({ key: viewKey, data, full });
    }, 350);
    return () => { live = false; clearTimeout(t); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewKey, picked, baseline, axis]);

  // Preview the dragged range's level over time.
  useEffect(() => {
    if (!range || !axis || !hasSpectra || range.high <= range.low) { setPreview(null); return undefined; }
    let live = true;
    const t = setTimeout(() => {
      previewSignalBand(summary.id, { low: range.low, high: range.high, axis, unit: xUnit === "orders" ? "orders" : "Hz" })
        .then((d) => live && setPreview(d.series))
        .catch(() => live && setPreview(null));
    }, 300);
    return () => { live = false; clearTimeout(t); };
  }, [range, axis, hasSpectra, summary.id, xUnit]);

  if (error) return <p className="sg-note sg-bad" role="alert">Couldn't load this channel: {error}</p>;
  if (!ch || !axis) return <p className="sg-note">Loading…</p>;

  const unit = ch.unit;
  const last = index[index.length - 1];
  const sel = (id) => {
    if (detail && detail.key === viewKey && detail.data.has(id)) return detail.data.get(id);
    const c = cache.current.get(`${axis}|${id}`);
    return c && c !== "loading" ? c : null;
  };
  const inOrders = xUnit === "orders";
  const canOrders = !!ch.rpm || allIndex.some((s) => s.rpm);
  let noSpeed = 0; // snapshots left out of the orders view for lack of a speed

  // ---- the spectrum chart
  const traces = [];
  const entries = [];
  if (baseline && byId.get(baseline)) entries.push({ id: baseline, kind: "baseline", color: REFERENCE });
  picked.forEach((id, n) => { if (byId.get(id) && id !== baseline) entries.push({ id, kind: "snapshot", color: COLORWAY[(n + 1) % COLORWAY.length] }); });
  const headId = head != null ? withSpectrum[head]?.id : null;
  const labelOf = (id) => fmtWhen(byId.get(id)?.t);
  const dim = (id) => (hot && hot !== id ? 0.15 : 1);
  const xUnitName = inOrders ? "×" : " Hz";
  const line = (id, s, extra) => {
    const x = xFor(s.freqs, speedOf(id), xUnit);
    if (!x) { noSpeed += 1; return null; }
    return {
      type: "scatter", mode: "lines", x, y: s.amps, name: labelOf(id), ...extra,
      hovertemplate: `%{x:.4g}${xUnitName}<br>%{y:.3g} ${unit}<extra>${labelOf(id)}</extra>`,
    };
  };
  for (const e of entries) {
    const s = sel(e.id);
    if (!s) continue;
    const t = line(e.id, s, { opacity: dim(e.id), line: { color: e.color, width: hot === e.id ? 2.6 : 1.3, dash: e.kind === "baseline" ? "dot" : "solid" } });
    if (t) traces.push(t);
  }
  // The head: with the optional fade, the current snapshot gives way to the next in the last part of its hold.
  const weights = fade && playing ? fadeWeights(blend) : { current: 1, next: 0 };
  const hs = headId ? sel(headId) : null;
  if (hs) {
    const t = line(headId, hs, { opacity: weights.current, line: { color: ACCENT, width: 2.2 } });
    if (t) traces.push(t);
  }
  const nextId = weights.next > 0 && head != null ? withSpectrum[head + 1]?.id : null;
  const ns = nextId ? sel(nextId) : null;
  if (ns) {
    const t = line(nextId, ns, { opacity: weights.next, line: { color: ACCENT, width: 2.2 } });
    if (t) traces.push(t);
  }
  const shapes = range && range.high > range.low
    ? [{ type: "rect", xref: "x", yref: "paper", x0: range.low, x1: range.high, y0: 0, y1: 1,
         fillcolor: "rgba(47,109,246,0.12)", line: { width: 0 }, layer: "below" }] : [];
  for (const b of ch.bands.filter((x) => !x.retired && x.rule.type === "band" && x.rule.axis === axis)) {
    // A band shows on the strip in the chart's unit: a Hz band in Hz view, an orders band in orders view.
    // (A band in the other unit is shown at the chart's current speed.)
    const k = ch.rpm ? ch.rpm / 60 : null;
    let x0 = b.rule.low;
    let x1 = b.rule.high;
    if (b.rule.in !== (inOrders ? "orders" : "Hz")) {
      if (!k) continue;
      [x0, x1] = inOrders ? [x0 / k, x1 / k] : [x0 * k, x1 * k];
    }
    shapes.push({ type: "rect", xref: "x", yref: "paper", x0, x1, y0: 0, y1: 0.04, fillcolor: "rgba(20,23,28,0.35)", line: { width: 0 } });
  }
  const spectrumLayout = {
    height: 320, dragmode: "select", selectdirection: "h", hovermode: "closest", showlegend: false,
    uirevision: `${xUnit}|${axis}|${runOnly}`,
    xaxis: { title: { text: inOrders ? "Order (multiples of running speed)" : "Frequency (Hz)" }, rangemode: "tozero" },
    yaxis: { title: { text: `Amplitude (${unit}, peak)${logY ? ", log scale" : ""}` }, ...(logY ? { type: "log" } : { rangemode: "tozero" }) },
    shapes, margin: { t: 8 },
  };
  const onSelected = (ev) => {
    const x = ev?.range?.x;
    if (x && x[1] > x[0]) setRange({ low: Math.max(0, Number(fmt(x[0], 4))), high: Number(fmt(x[1], 4)) });
  };
  // Zooming (the toolbar's, or double-click to reset): remember the visible range so the full detail can be fetched.
  const onRelayout = (ev) => {
    if (!ev) return;
    if (ev["xaxis.autorange"]) { setView(null); return; }
    const a = ev["xaxis.range[0]"] ?? ev["xaxis.range"]?.[0];
    const b = ev["xaxis.range[1]"] ?? ev["xaxis.range"]?.[1];
    if (Number.isFinite(a) && Number.isFinite(b) && b > a) setView([Math.max(0, a), b]);
  };

  // ---- the band chart
  const bands = ch.bands.filter((b) => !b.retired);
  const chosen = bands.find((b) => b.point_id === bandSel) || null;
  const bandSeries = dropStopped(chosen ? chosen.series : preview, allIndex, runOnly);
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
  // Warning (dotted, amber) and alarm (dashed, red) levels, each labelled; the band's changes of range as a marker.
  const lines = limitLines(chosen);
  const limitShapes = lines.map((l) => ({
    type: "line", xref: "paper", x0: 0, x1: 1, yref: "y", y0: l.value, y1: l.value,
    line: { color: l.kind === "alarm" ? DANGER : WARNING, width: 1.2, dash: l.kind === "alarm" ? "dash" : "dot" },
  }));
  const limitNotes = lines.map((l) => ({
    xref: "paper", x: 1, xanchor: "right", yref: "y", y: l.value, yanchor: "bottom", showarrow: false, text: l.label,
    font: { size: 11, color: l.kind === "alarm" ? DANGER : WARNING },
  }));
  const changes = (chosen?.changes || []).filter((c) => c.t);
  const changeShapes = changes.map((c) => ({ type: "line", xref: "x", x0: c.t, x1: c.t, yref: "paper", y0: 0, y1: 1, line: { color: REFERENCE, width: 1.2, dash: "dashdot" } }));
  const changeNotes = changes.map((c) => ({ xref: "x", x: c.t, yref: "paper", y: 1, yanchor: "top", xanchor: "left", showarrow: false, text: `Range changed: ${c.to}`, font: { size: 11, color: REFERENCE } }));

  const saveBand = async (form) => {
    // The picked range is in the chart's unit. In Hz view it can follow the speed instead (converted here).
    const k = ch.rpm ? ch.rpm / 60 : null;
    const toSpeed = !inOrders && form.unit === "orders";
    const body = {
      name: form.name.trim(), axis, unit: inOrders || toSpeed ? "orders" : "Hz",
      low: toSpeed ? Number(fmt(range.low / k, 4)) : range.low,
      high: toSpeed ? Number(fmt(range.high / k, 4)) : range.high,
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
      <div className="sg-bar">
        <button type="button" className="secondary sm" onClick={() => setAddingSnap(true)} disabled={addingSnap}>Add a snapshot from a file</button>
        {hasFlags && (
          <label className="sg-check">
            <input type="checkbox" checked={runOnly} onChange={(e) => toggleRunOnly(e.target.checked)} /> Running only
          </label>
        )}
      </div>
      {addingSnap && (
        <SignalSnapshotForm ch={ch} onCancel={() => setAddingSnap(false)}
                            onDone={async () => {
                              const d = await reload();
                              const p = defaultPicks(runningOnly(d.snapshots.index, runOnly));
                              setPicked(p.picked);
                              setBaseline(p.baseline);
                              setHead(null);
                              onChanged?.();
                            }} />
      )}
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

      <ChannelSettings ch={ch} all={all} onSaved={async () => { await reload(); onChanged?.(); }} />

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
          <div className="sg-toggles">
            {canOrders && (
              <div className="sg-seg" role="group" aria-label="Frequency axis">
                <button type="button" aria-pressed={!inOrders} onClick={() => changeUnit("Hz")}>Hz</button>
                <button type="button" aria-pressed={inOrders} onClick={() => changeUnit("orders")}>Orders</button>
              </div>
            )}
            <div className="sg-seg" role="group" aria-label="Amplitude axis">
              <button type="button" aria-pressed={!logY} onClick={() => setLogY(false)}>Linear</button>
              <button type="button" aria-pressed={logY} onClick={() => setLogY(true)}>Log</button>
            </div>
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
          <Plot data={traces} layout={spectrumLayout} onSelected={onSelected} onRelayout={onRelayout} download={`${ch.name} spectrum`} />
          {!traces.length && <p className="sg-note">Loading spectra…</p>}
          {inOrders && noSpeed > 0 && <p className="sg-hint">{noSpeed} snapshot{noSpeed === 1 ? " has" : "s have"} no running speed, so {noSpeed === 1 ? "it isn't" : "they aren't"} drawn in orders. Give the channel an rpm or a speed source below.</p>}
          {view && detail && detail.key === viewKey && (
            <p className="sg-hint">{detail.full ? "Zoomed: every spectrum line in view is drawn." : "Zoomed: the view is still thinned (keeping the peaks); zoom in further for every line."}</p>
          )}
          <p className="sg-hint">Drag across the chart to pick a {inOrders ? "range of orders" : "frequency range"}, or type it below. Use the chart's zoom to see every line in a range.</p>

          <BandForm range={range} setRange={setRange} rpm={ch.rpm} axis={axis} xUnit={xUnit}
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
                  layout={{ height: 200, showlegend: false, hovermode: "closest", margin: { t: 8 }, shapes: [...limitShapes, ...changeShapes],
                            annotations: [...limitNotes, ...changeNotes],
                            xaxis: { type: "date" }, yaxis: { title: { text: `RMS level (${bandUnit || "units"})` }, rangemode: "tozero" } }}
                  download={`${ch.name} band level`} />
          ) : (
            <p className="sg-note">{chosen ? "This band has no values yet." : "Drag a range on the spectrum to see how its level has changed."}</p>
          )}
          <Player
            times={times} withSpectrum={withSpectrum} head={head} playing={playing} loop={loop} setLoop={setLoop}
            speed={speed} setSpeed={setSpeed} fade={fade} setFade={setFade} cue={cue} loading={loadingAll} onPlay={play}
            onPause={() => setPlaying(false)} onScrub={scrub} />
        </section>
      )}

      {bands.length > 0 && (
        <section className="card sg-card" aria-label="Watch bands">
          <h3 className="sg-h">Watch bands and levels</h3>
          <div className="maint-scroll">
            <table className="sg-table">
              <thead><tr><th>Name</th><th>What it reads</th><th>Latest</th><th>Levels</th><th /></tr></thead>
              <tbody>
                {bands.map((b) => (
                  <tr key={b.point_id}>
                    <td>{b.name}</td>
                    <td>{bandLabel(b.rule)}{b.versions ? <span className="sg-hint"> (range changed {b.versions.length - 1} time{b.versions.length === 2 ? "" : "s"}; the trend marks when)</span> : null}</td>
                    <td>{b.latest ? <>{fmt(b.latest.value)} {b.unit}{b.status !== "ok" ? <strong className="sg-bad"> ({b.status})</strong> : null}</> : "–"}</td>
                    <td>{limitLines(b).length ? limitLines(b).map((l) => l.label).join("; ") : "none"}</td>
                    <td className="sg-rowact">
                      <button type="button" className="ghost sm" onClick={() => setEditing(editing === b.point_id ? null : b.point_id)}>Edit</button>
                      <button type="button" className="ghost sm" onClick={() => removeBand(b)}>Stop watching</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {editing && bands.find((b) => b.point_id === editing) && (
            <SignalBandEditor band={bands.find((b) => b.point_id === editing)} rpm={ch.rpm}
                              onCancel={() => setEditing(null)}
                              onSaved={async (out) => {
                                await reload();
                                setEditing(null);
                                setBandSel(out.point_id);
                                setNotice(out.new_version
                                  ? "Saved. The band carries on with its new range from the next snapshot; what it recorded before is unchanged, and the trend marks the change."
                                  : "Saved.");
                                onChanged?.();
                              }} />
          )}
          <p className="sg-hint">Each band is also a measurement point (see Summary › Measurements), so its alarm limits, trend and projected alarm date work as for any other.</p>
        </section>
      )}
      {more && <p className="sg-hint">Showing the latest {ch.snapshots.shown} of {ch.snapshots.count.toLocaleString("en-GB")} snapshots.</p>}
    </>
  );
}

function BandForm({ range, setRange, rpm, onSave, axis, xUnit }) {
  const orders = xUnit === "orders";
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
    ? orders ? `${fmt(range.low, 4)}–${fmt(range.high, 4)}× speed`
      : unit === "orders" && rpm ? `${fmt(range.low / (rpm / 60), 3)}–${fmt(range.high / (rpm / 60), 3)}× speed` : `${fmt(range.low, 4)}–${fmt(range.high, 4)} Hz`
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
      <label className="sg-field">From ({orders ? "× speed" : "Hz"})<input type="number" inputMode="decimal" min="0" step="any" value={low} onChange={set("low")} /></label>
      <label className="sg-field">To ({orders ? "× speed" : "Hz"})<input type="number" inputMode="decimal" min="0" step="any" value={high} onChange={set("high")} /></label>
      <label className="sg-field">Name<input value={name} onChange={(e) => setName(e.target.value)} placeholder={suggested || "Band name"} maxLength={200} /></label>
      {rpm && !orders ? (
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
      {valid && <p className="sg-hint sg-full">Watches the RMS level of axis {axis} in this range at every snapshot{orders || unit === "orders" ? ", moving with the speed each snapshot was taken at" : ""}.</p>}
    </form>
  );
}

function Player({ times, withSpectrum, head, playing, loop, setLoop, speed, setSpeed, fade, setFade, cue, loading, onPlay, onPause, onScrub }) {
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
      <label className="sg-check"><input type="checkbox" checked={fade} onChange={(e) => setFade(e.target.checked)} /> Smooth transition (display only)</label>
      {cue && <span className="sg-cue" role="status">↺ Back to the first snapshot</span>}
      <p className="sg-hint sg-full">
        The whole history plays in about {DEFAULT_LOOP_MS / 1000} seconds. Each snapshot is held for as long, in proportion,
        as it was until the next, so a long gap shows as a long pause. Nothing is drawn in between{fade ? ", except that the smooth transition fades one real spectrum into the next. It is a display effect, not a measurement" : ""}.
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

// A channel's running speed and where it comes from: fixed (rpm) or the nearest reading of another channel.
function ChannelSettings({ ch, all, onSaved }) {
  const [rpm, setRpm] = useState(ch.rpm ? String(ch.rpm) : "");
  const [src, setSrc] = useState(ch.speed_channel_id || "");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const speedChannels = all.filter((c) => c.id !== ch.id && /^(rpm|r\/min|1\/min)$/i.test((c.unit || "").trim()));
  const save = async (e) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      await updateSignalChannel(ch.id, { rpm: rpm === "" ? null : Number(rpm), speed_channel_id: src });
      await onSaved();
    } catch (x) {
      setErr(x.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <details className="sg-settings">
      <summary>Running speed{ch.rpm ? `: ${fmt(ch.rpm, 4)} rpm` : ""}{ch.speed_channel_id ? " (from a speed channel)" : ""}</summary>
      <form className="sg-band" onSubmit={save}>
        <label className="sg-field">Fixed speed, rpm
          <input type="number" inputMode="decimal" min="0" step="any" value={rpm} onChange={(e) => setRpm(e.target.value)} />
        </label>
        <label className="sg-field">Or take the speed from
          <select value={src} onChange={(e) => setSrc(e.target.value)}>
            <option value="">No speed channel</option>
            {speedChannels.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </label>
        <button type="submit" disabled={busy}>{busy ? "Saving…" : "Save"}</button>
        {err && <p className="sg-note sg-bad" role="alert">{err}</p>}
        <p className="sg-hint sg-full">
          With a speed channel (a channel in rpm that sends single values), each new snapshot uses that channel's reading nearest
          in time, if there is one within an hour; otherwise the fixed speed. A speed reading that arrives after the snapshot is
          not applied to it, so send the speed first or together. Bands in multiples of speed and the Orders view use it.
          {speedChannels.length === 0 ? " There is no channel in rpm on this workspace yet: add one with the unit rpm." : ""}
        </p>
      </form>
    </details>
  );
}
