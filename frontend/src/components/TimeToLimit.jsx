import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import Plot from "./Plot.jsx";
import Modal from "./Modal.jsx";
import {
  createTrackedItem, getBandDegradationSeries, getTimeToLimit, listTrackedFleets, pasteDataset,
} from "../api.js";
import { ACCENT, DANGER, REFERENCE } from "../plotTheme.js";
import { PROCESSES, dateText, datasetName, daysText, measurementsOf, percent, usefulHorizons } from "../timeToLimit.js";
import "./TimeToLimit.css";

const GUIDE = "/guides/signal-channels#time-to-the-limit";

// "Time to the limit" for one watched band (Signals tab): the band's own history is fitted with a
// degradation process and the panel says when it is expected to reach the alarm limit, with the
// uncertainty, or says plainly why it can't yet. Two ways on: use the trend in a degradation model
// (a copy goes to Data), or watch it in Risk (a copy goes to a tracked fleet).
export default function TimeToLimit({ bands, channelName, selectedId }) {
  const navigate = useNavigate();
  const live = bands.filter((b) => !b.retired);
  const [pointId, setPointId] = useState(selectedId && live.some((b) => b.point_id === selectedId) ? selectedId : live[0]?.point_id);
  const [process, setProcess] = useState("wiener");
  const [since, setSince] = useState("");
  const [limit, setLimit] = useState("");
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState(null);
  const [fleets, setFleets] = useState(null); // null: modal closed

  useEffect(() => {
    if (selectedId && live.some((b) => b.point_id === selectedId)) setPointId(selectedId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId]);

  const band = live.find((b) => b.point_id === pointId) || live[0];
  const latest = band?.latest?.t;
  useEffect(() => {
    if (!band) return undefined;
    let stale = false;
    setError(null);
    getTimeToLimit(band.point_id, { process, since: since || undefined, limit: limit === "" ? undefined : limit })
      .then((r) => { if (!stale) setResult(r); })
      .catch((e) => { if (!stale) { setResult(null); setError(e.message); } });
    return () => { stale = true; };
  }, [band?.point_id, process, since, limit, latest]);

  const traces = useMemo(() => {
    if (!band || !result) return [];
    const out = [{ type: "scatter", mode: "lines+markers", x: band.series.map((p) => p.t), y: band.series.map((p) => p.value),
      line: { color: REFERENCE, width: 1.5 }, marker: { size: 4, color: REFERENCE }, name: "Readings",
      hovertemplate: `%{x|%d %b %Y}<br>%{y:.3g} ${band.unit}<extra></extra>` }];
    const tr = result.trend;
    if (tr) {
      out.push({ type: "scatter", mode: "lines", x: tr.fitted.map((p) => p.t), y: tr.fitted.map((p) => p.value),
        line: { color: ACCENT, width: 2 }, name: "Fitted trend", hoverinfo: "skip" });
      out.push({ type: "scatter", mode: "lines", x: tr.projection.map((p) => p.t), y: tr.projection.map((p) => p.value),
        line: { color: ACCENT, width: 2, dash: "dash" }, name: "Expected path", hoverinfo: "skip" });
    }
    const ttl = result.time_to_limit;
    const wide = ttl?.range_allowing_for_the_fit;
    if (ttl && result.status === "ok" && result.limit) {
      const ends = [[wide?.early_at, "Earliest"], [ttl.median_at, "Most likely"], [wide?.late_at, "Latest"]].filter(([t]) => t);
      out.push({ type: "scatter", mode: "markers", x: ends.map(([t]) => t), y: ends.map(() => result.limit.value),
        marker: { size: 9, color: ACCENT, symbol: "diamond" }, text: ends.map(([, l]) => l), name: "When it reaches the limit",
        hovertemplate: "%{text}: %{x|%d %b %Y}<extra></extra>" });
    }
    return out;
  }, [band, result]);

  if (!band) return null;
  const shapes = result?.limit ? [{ type: "line", xref: "paper", x0: 0, x1: 1, y0: result.limit.value, y1: result.limit.value,
    line: { color: DANGER, width: 1.5, dash: "dot" } }] : [];
  const ok = result?.status === "ok";
  const ttl = result?.time_to_limit;
  const rows = usefulHorizons(ttl?.chance_by);
  const wide = ttl?.range_allowing_for_the_fit;

  const useInModel = async () => {
    setBusy(true);
    setNote(null);
    try {
      const s = await getBandDegradationSeries(band.point_id, { since: since || undefined });
      if (!s.n_readings) throw new Error("This band has no readings yet.");
      const made = await pasteDataset(datasetName(band.name, channelName), s.csv, false);
      navigate(`/models/degradation?dataset=${made.id}`);
    } catch (e) {
      setNote({ error: true, text: e.message });
    } finally {
      setBusy(false);
    }
  };

  const openWatch = async () => {
    setNote(null);
    setFleets([]);
    try {
      const d = await listTrackedFleets();
      setFleets((d.fleets || []).filter((f) => !f.is_sample && !f.shared_by));
    } catch (e) {
      setFleets(null);
      setNote({ error: true, text: e.message });
    }
  };
  const watch = async (fleet) => {
    setBusy(true);
    try {
      const s = await getBandDegradationSeries(band.point_id, { since: since || undefined });
      if (!s.n_readings) throw new Error("This band has no readings yet.");
      const item = await createTrackedItem(fleet.model_id, {
        name: `${channelName} - ${band.name}`, fleetId: fleet.id, measurements: measurementsOf(s.rows),
        meta: { source: "signal band", unit: s.level_unit },
      });
      setFleets(null);
      setNote({ text: `Added "${item.name}" to ${fleet.name}. It is a copy of the readings as of today.`, to: `/risk/${fleet.id}` });
    } catch (e) {
      setNote({ error: true, text: e.message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="card sg-card ttl" aria-label="Time to the limit">
      <div className="sg-bar">
        <h3 className="sg-h">Time to the limit</h3>
        <Link className="sg-help" to={GUIDE}>How this works</Link>
      </div>
      <div className="sg-bar">
        <label className="sg-field">Band
          <select value={band.point_id} onChange={(e) => setPointId(e.target.value)}>
            {live.map((b) => <option key={b.point_id} value={b.point_id}>{b.name}</option>)}
          </select>
        </label>
        <label className="sg-field">Model
          <select value={process} onChange={(e) => setProcess(e.target.value)} title={PROCESSES.find((p) => p.id === process).hint}>
            {PROCESSES.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
          </select>
        </label>
        <label className="sg-field">Limit ({band.unit})
          <input type="number" step="any" value={limit} onChange={(e) => setLimit(e.target.value)}
                 placeholder={band.alarm_above ?? band.alarm_below ?? "needed"} />
        </label>
        <label className="sg-field">Readings from
          <input type="date" value={since} onChange={(e) => setSince(e.target.value)} />
        </label>
      </div>

      {error && <p className="sg-note sg-bad" role="alert">{error}</p>}
      {!result && !error && <p className="sg-note">Working it out…</p>}
      {result && (
        <>
          <p className={ok ? "ttl-answer" : "ttl-answer ttl-plain"} role="status" data-status={result.status}>{result.message}</p>
          {result.status === "too_few" && (
            <progress className="ttl-progress" max={result.minimum_readings} value={Math.min(result.n_readings, result.minimum_readings)}
                      aria-label={`${result.n_readings} of ${result.minimum_readings} readings`} />
          )}
          {(result.warnings || []).map((w) => <p key={w} className="sg-note ttl-warn">{w}</p>)}
          {result.trend && (
            <Plot data={traces}
                  layout={{ height: 270, showlegend: true, legend: { orientation: "h", y: -0.32 }, hovermode: "closest",
                            margin: { t: 8, b: 60 }, shapes, xaxis: { type: "date" },
                            yaxis: { title: { text: `${band.name} (${band.unit || "units"})` } } }}
                  download={`${channelName} ${band.name} time to limit`} />
          )}
          {ok && (
            <>
              <p className="sg-meta">
                Average drift {result.trend.drift_per_day > 0 ? "up" : "down"} {Math.abs(result.trend.drift_per_day)} {band.unit} a day
                {result.trend.wobble_per_sqrt_day ? `, wobble ${result.trend.wobble_per_sqrt_day} ${band.unit} per square-root day` : ""}
                , from {result.n_readings} readings over {Math.round(result.span_days)} days.
              </p>
              <div className="maint-scroll">
                <table className="sg-table ttl-table">
                  <thead>
                    <tr><th>Chance of reaching the limit within</th><th>Chance</th><th>Allowing for the fit</th></tr>
                  </thead>
                  <tbody>
                    {rows.map((r) => (
                      <tr key={r.days}>
                        <td>{daysText(r.days)}</td><td>{percent(r.chance)}</td>
                        <td>{r.low === undefined ? "–" : `${percent(r.low)} to ${percent(r.high)}`}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <p className="sg-hint">
                Spread of the process alone (rate known exactly): {daysText(ttl.range.early_days)} to {daysText(ttl.range.late_days)}
                {wide.early_at && wide.late_at ? `. Allowing for the fit: ${dateText(wide.early_at)} to ${dateText(wide.late_at)}.` : "."}
              </p>
            </>
          )}
          <details className="ttl-assume">
            <summary>What this assumes</summary>
            <p>{result.assumption}</p>
            <p>This is the time to the limit you chose, not to failure. If the part was renewed or the load changed, start the
              readings after that with "Readings from".</p>
          </details>
        </>
      )}

      <div className="sg-actions ttl-actions">
        <button type="button" className="secondary" onClick={useInModel} disabled={busy}>Use in a degradation model</button>
        <button type="button" className="secondary" onClick={openWatch} disabled={busy}>Watch in Risk</button>
      </div>
      {note && (
        <p className={note.error ? "sg-note sg-bad" : "sg-note"} role="status">
          {note.text} {note.to && <Link to={note.to}>Open it</Link>}
        </p>
      )}
      {fleets && (
        <Modal title="Watch in Risk" className="modal-sm" onClose={() => setFleets(null)} locked={busy}
               footer={<button className="secondary" onClick={() => setFleets(null)}>Cancel</button>}>
          {fleets.length === 0 ? (
            <p>There is no tracked fleet to add it to yet. A tracked fleet runs against a degradation model: use this band's
              trend in a degradation model first, then start a fleet in <Link to="/risk">Condition monitoring</Link>.</p>
          ) : (
            <>
              <p>Add this band's readings as an item in a tracked fleet. It is a copy as of today; it does not update by itself.</p>
              <ul className="ttl-fleets">
                {fleets.map((f) => (
                  <li key={f.id}><button type="button" className="secondary" disabled={busy} onClick={() => watch(f)}>{f.name}</button>
                    <span className="sg-meta"> {f.model_name}</span></li>
                ))}
              </ul>
            </>
          )}
        </Modal>
      )}
    </section>
  );
}
