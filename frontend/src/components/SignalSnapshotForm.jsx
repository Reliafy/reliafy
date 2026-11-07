import { useMemo, useState } from "react";
import Plot from "./Plot.jsx";
import { addSignalSnapshot } from "../api.js";
import { ACCENT } from "../plotTheme.js";
import {
  fmt, localToIso, parseCsv, parseJsonSnapshots, parseWav, sizeProblem, snapshotBody, thinWave, trimAxes,
} from "../signals.js";

// "Add a snapshot" on a channel (Signals tab): choose a JSON, CSV or WAV file,
// see what it holds, fill in what the file doesn't say (when it was taken, the
// sample rate, the axis names), and add it. The numbers are read in the browser
// and sent to the same route a device uses. Nothing is sent until you press Add.

const nowLocal = () => {
  const d = new Date();
  d.setSeconds(0, 0);
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
};

function kindOf(item) {
  if (item.axes || item.samples) return "samples";
  if (item.spectrum) return "a spectrum";
  return "a value";
}

export default function SignalSnapshotForm({ ch, onDone, onCancel }) {
  const [parsed, setParsed] = useState(null); // { kind: "json", list } | { kind: "axes", axes, sampleRate, source }
  const [error, setError] = useState(null);
  const [fileName, setFileName] = useState("");
  const [time, setTime] = useState("");
  const [rate, setRate] = useState(ch.sample_rate ? String(ch.sample_rate) : "");
  const [names, setNames] = useState("");
  const [scale, setScale] = useState("1");
  const [rpm, setRpm] = useState("");
  const [running, setRunning] = useState("unknown");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [results, setResults] = useState(null);

  const read = async (file) => {
    setError(null);
    setParsed(null);
    setResults(null);
    if (!file) return;
    setFileName(file.name);
    try {
      const lower = file.name.toLowerCase();
      let out;
      if (lower.endsWith(".wav")) {
        const w = parseWav(await file.arrayBuffer());
        out = { kind: "axes", axes: w.axes, sampleRate: w.sampleRate, source: "wav" };
      } else if (lower.endsWith(".json")) {
        out = { kind: "json", list: parseJsonSnapshots(await file.text()) };
      } else if (lower.endsWith(".csv") || lower.endsWith(".txt")) {
        const c = parseCsv(await file.text());
        out = { kind: "axes", axes: c.axes, sampleRate: c.sampleRate, source: "csv" };
      } else {
        throw Object.assign(new Error("Choose a .json, .csv, .txt or .wav file."), { plain: true });
      }
      if (out.kind === "axes") {
        if (out.sampleRate) setRate(String(out.sampleRate));
        const keys = Object.keys(out.axes);
        const declared = ch.axes || [];
        setNames((declared.length === keys.length ? declared : keys).join(", "));
        setScale("1");
      }
      setParsed(out);
    } catch (e) {
      setError(e.plain ? e.message : `Couldn't read that file: ${e.message}`);
    }
  };

  const problem = useMemo(() => (parsed?.kind === "axes" ? sizeProblem(parsed.axes) : null), [parsed]);
  const axisKeys = parsed?.kind === "axes" ? Object.keys(parsed.axes) : [];
  const nameList = names.split(",").map((n) => n.trim()).filter(Boolean);
  const namesOk = parsed?.kind !== "axes" || (nameList.length === axisKeys.length && new Set(nameList).size === nameList.length);
  const per = axisKeys.length ? parsed.axes[axisKeys[0]].length : 0;
  const wave = useMemo(() => (axisKeys.length ? thinWave(parsed.axes[axisKeys[0]]) : null), [parsed]); // eslint-disable-line react-hooks/exhaustive-deps

  const trim = () => setParsed((p) => ({ ...p, axes: trimAxes(p.axes, problem.fits) }));

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const out = [];
    try {
      if (parsed.kind === "axes") {
        const axes = Object.fromEntries(axisKeys.map((k, i) => [nameList[i], parsed.axes[k]]));
        const body = snapshotBody({ channelId: ch.id, time: localToIso(time), axes, sampleRate: rate, scale, rpm, running, note });
        const r = await addSignalSnapshot(body);
        out.push({ label: fileName, r });
      } else {
        for (const [i, item] of parsed.list.entries()) {
          const body = { ...item, channel_id: ch.id };
          delete body.tag;
          if (!body.time && time) body.time = localToIso(time);
          if (!body.time) {
            out.push({ label: `Snapshot ${i + 1}`, error: "It has no time. Add a time in the file, or set “Time taken” below to use for all of them." });
            continue;
          }
          try {
            out.push({ label: `Snapshot ${i + 1}`, r: await addSignalSnapshot(body) });
          } catch (x) {
            out.push({ label: `Snapshot ${i + 1}`, error: x.message });
          }
        }
      }
      setResults(out);
      if (out.some((o) => o.r && o.r.stored)) onDone?.(out);
    } catch (x) {
      setError(x.message);
    } finally {
      setBusy(false);
    }
  };

  const needsTime = parsed?.kind === "axes" || (parsed?.kind === "json" && parsed.list.some((i) => !i.time));
  const canAdd = parsed && !problem && namesOk && !busy
    && (parsed.kind === "json" ? parsed.list.every((i) => i.time || time) : (time && Number(rate) > 0));

  return (
    <form className="card sg-new" onSubmit={submit} aria-label="Add a snapshot">
      <h3>Add a snapshot to {ch.name}</h3>
      <p className="sg-hint">
        Choose a file from the sensor or logger: JSON (the format in the guide), CSV or text with one column of numbers per axis,
        or a WAV recording. Reliafy works out the spectrum when you add it. Values are taken to be in {ch.unit}.
      </p>
      <label className="sg-field">File (.json, .csv, .txt or .wav)
        <input type="file" accept=".json,.csv,.txt,.wav,application/json,text/csv,audio/wav" onChange={(e) => read(e.target.files?.[0])} />
      </label>
      {error && <p className="sg-note sg-bad" role="alert">{error}</p>}

      {parsed?.kind === "json" && (
        <div className="maint-scroll">
          <table className="sg-table">
            <thead><tr><th>Snapshot</th><th>Time in the file</th><th>Holds</th></tr></thead>
            <tbody>
              {parsed.list.map((item, i) => (
                <tr key={i}><td>{i + 1}</td><td>{item.time ? String(item.time) : <span className="sg-bad">none</span>}</td><td>{kindOf(item)}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {parsed?.kind === "axes" && (
        <>
          <p className="sg-meta">
            {fileName}: {axisKeys.length} axis{axisKeys.length === 1 ? "" : "es"}, {per.toLocaleString("en-GB")} samples each
            {Number(rate) > 0 ? <>, {fmt(per / Number(rate))} s at {fmt(Number(rate))} Hz</> : null}.
            {parsed.source === "wav" ? " WAV values run from −1 to 1 (full scale): set the scale below to turn them into " + ch.unit + "." : ""}
          </p>
          {wave && (
            <Plot data={[{ type: "scatter", mode: "lines", x: wave.x, y: wave.y, line: { color: ACCENT, width: 1 }, name: axisKeys[0], hoverinfo: "skip" }]}
                  layout={{ height: 140, showlegend: false, margin: { t: 6, b: 28 }, xaxis: { title: { text: "Sample number" } }, yaxis: { title: { text: `${axisKeys[0]}` } } }} />
          )}
          {problem && (
            <p className="sg-note sg-bad" role="alert">
              {problem.message} <button type="button" className="secondary sm" onClick={trim}>Use the first {problem.fits.toLocaleString("en-GB")}</button>
            </p>
          )}
        </>
      )}

      {parsed && (
        <div className="sg-grid">
          {needsTime && (
            <label className="sg-field">Time taken{parsed.kind === "json" ? " (for any snapshot without one)" : ""}
              <span className="sg-inline-row">
                <input type="datetime-local" value={time} onChange={(e) => setTime(e.target.value)} required={parsed.kind === "axes"} />
                <button type="button" className="secondary sm" onClick={() => setTime(nowLocal())}>Now</button>
              </span>
              <span className="sg-hint">In your browser's time zone. Reliafy never guesses a time.</span>
            </label>
          )}
          {parsed.kind === "axes" && (
            <>
              <label className="sg-field">Sample rate, Hz
                <input type="number" inputMode="decimal" min="0" step="any" value={rate} onChange={(e) => setRate(e.target.value)} required />
              </label>
              <label className="sg-field">Axis names (one per column)
                <input value={names} onChange={(e) => setNames(e.target.value)} placeholder="X, Y, Z" aria-invalid={!namesOk} />
                {!namesOk && <span className="sg-bad">Give {axisKeys.length} different name{axisKeys.length === 1 ? "" : "s"}, separated by commas.</span>}
              </label>
              {parsed.source === "wav" && (
                <label className="sg-field">{ch.unit} per full scale
                  <input type="number" inputMode="decimal" step="any" value={scale} onChange={(e) => setScale(e.target.value)} />
                </label>
              )}
              <label className="sg-field">Running speed, rpm (optional)
                <input type="number" inputMode="decimal" min="0" step="any" value={rpm} onChange={(e) => setRpm(e.target.value)} placeholder={ch.rpm ? `${ch.rpm} (the channel's)` : ""} />
              </label>
              <label className="sg-field">Was the machine running?
                <select value={running} onChange={(e) => setRunning(e.target.value)}>
                  <option value="unknown">Not stated</option>
                  <option value="yes">Running</option>
                  <option value="no">Stopped</option>
                </select>
              </label>
              <label className="sg-field">Note (optional)<input value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} /></label>
            </>
          )}
        </div>
      )}

      {results && (
        <ul className="sg-results" aria-label="Result">
          {results.map((o, i) => (
            <li key={i} className={o.error ? "sg-bad" : ""}>
              {o.error ? `${o.label}: ${o.error}` : o.r.duplicate ? `${o.label}: already stored for that time; nothing changed.` : `${o.label}: added.`}
              {o.r?.notes?.map((n) => <span key={n} className="sg-hint"> {n}</span>)}
            </li>
          ))}
        </ul>
      )}
      <div className="sg-actions">
        <button type="submit" disabled={!canAdd}>{busy ? "Adding…" : "Add the snapshot"}</button>
        <button type="button" className="secondary" onClick={onCancel}>{results ? "Close" : "Cancel"}</button>
      </div>
    </form>
  );
}
