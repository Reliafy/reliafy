// "Outage history" tab of the RBD builder (issue #159): import a real outage
// log against the saved diagram, then show the system's observed history —
// merged through the diagram by RePyability's timelines on the server — with
// its KPIs, a timeline chart, every system outage and the block behind it,
// the blocks ranked by their share of the downtime, and life/repair models
// fitted from the same log, ready to put on the blocks.
import { useCallback, useEffect, useMemo, useState } from "react";
import Plot from "./Plot.jsx";
import Select from "./Select.jsx";
import {
  deleteOutageLog,
  fitOutageModels,
  getOutageHistory,
  listOutageLogs,
  previewOutageLog,
  saveOutageLog,
  updateOutageLog,
} from "../api.js";
import "./OutageHistory.css";

const FIELDS = [
  { key: "asset", label: "Asset", help: "The block (its label or id) each outage belongs to", req: true },
  { key: "start", label: "Down", help: "When the outage started (date-time or a number)", req: true },
  { key: "end", label: "Back up", help: "When it ended — a blank cell means still down" },
  { key: "duration", label: "Duration", help: "Instead of an end: how long it lasted" },
  { key: "reason", label: "Reason", help: "Optional reason or failure mode" },
  { key: "planned", label: "Planned", help: "Optional yes/no for planned maintenance outages" },
];

const UNIT_SECONDS = {
  second: 1, minute: 60, hour: 3600, day: 86400, week: 604800, month: 2629800, year: 31557600,
};
const UNIT_ALIASES = { s: "second", min: "minute", h: "hour", hr: "hour", d: "day", wk: "week", mo: "month", y: "year", yr: "year" };
function unitSeconds(unit) {
  let key = String(unit || "").trim().toLowerCase().replace(/\.$/, "");
  key = UNIT_ALIASES[key] || key.replace(/s$/, "");
  return UNIT_SECONDS[key] || null;
}

const FAIL = "#d0473a";
const PLANNED = "#e0a030";

function fmt(v, digits = 4) {
  if (v == null || !Number.isFinite(Number(v))) return "—";
  const n = Number(v);
  if (n !== 0 && (Math.abs(n) >= 1e6 || Math.abs(n) < 1e-3)) return n.toExponential(2);
  return Number(n.toPrecision(digits)).toLocaleString();
}
const pct = (v, d = 2) => (v == null ? "—" : `${(v * 100).toFixed(d)}%`);
const when = (iso) => (iso ? iso.replace("T", " ") : "");

// ---------------------------------------------------------------------------
// Import: paste or pick a file, map the columns, check, save
// ---------------------------------------------------------------------------

function ImportPanel({ rbdId, unit, blocks: initialBlocks, onSaved, onCancel }) {
  const [csv, setCsv] = useState("");
  const [name, setName] = useState("");
  const [preview, setPreview] = useState(null);
  const [mapping, setMapping] = useState(null);
  const [opts, setOpts] = useState({ unit: "", date_order: "auto", window_start: "", window_end: "" });
  const [assetMap, setAssetMap] = useState({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const run = useCallback(
    async (nextMapping, nextOpts, nextAssetMap) => {
      if (!csv.trim()) return;
      setBusy(true);
      setError(null);
      try {
        const body = {
          csv,
          mapping: nextMapping || undefined,
          unit: nextOpts.unit || undefined,
          date_order: nextOpts.date_order,
          window_start: nextOpts.window_start || undefined,
          window_end: nextOpts.window_end || undefined,
          asset_map: Object.keys(nextAssetMap).length ? nextAssetMap : undefined,
        };
        const p = await previewOutageLog(rbdId, body);
        setPreview(p);
        if (!nextMapping) setMapping(p.mapping || p.detected || {});
      } catch (err) {
        setPreview(null);
        setError(err.message);
      } finally {
        setBusy(false);
      }
    },
    [csv, rbdId]
  );

  const onFile = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setCsv(await file.text());
    if (!name) setName(file.name.replace(/\.(csv|tsv|txt)$/i, ""));
    setPreview(null);
    setMapping(null);
  };

  const setField = (key, value) => {
    const next = { ...mapping, [key]: value };
    if (key === "end" && value) next.duration = "";
    if (key === "duration" && value) next.end = "";
    setMapping(next);
    run(next, opts, assetMap);
  };
  const setOpt = (key, value) => setOpts((o) => ({ ...o, [key]: value }));
  const mapAsset = (asset, nodeId) => {
    const next = { ...assetMap, [asset]: nodeId };
    setAssetMap(next);
    run(mapping, opts, next);
  };

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const log = await saveOutageLog(rbdId, {
        csv,
        name,
        mapping,
        unit: opts.unit || undefined,
        date_order: opts.date_order,
        window_start: opts.window_start || undefined,
        window_end: opts.window_end || undefined,
        asset_map: Object.keys(assetMap).length ? assetMap : undefined,
      });
      onSaved(log);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const headers = preview?.headers || [];
  const blocks = preview?.blocks || initialBlocks || [];
  const columnOptions = [{ value: "", label: "— none —" }, ...headers.map((h) => ({ value: h, label: h }))];

  return (
    <div className="outage-import card">
      <div className="ds-section-h">Import an outage log</div>
      <p className="hint">
        One row per outage: the asset, when it went down and when it came back (blank = still down), with an
        optional reason and planned flag. Dates (ISO or day/month/year) are converted to the diagram's unit
        {unit ? ` (${unit})` : ""}; plain numbers are read as times in it.
      </p>
      <div className="outage-import-src">
        <textarea
          className="outage-paste"
          rows={6}
          placeholder={"asset,down,back up,reason\nPump A,2024-03-14 08:00,2024-03-14 11:30,seal leak"}
          value={csv}
          onChange={(e) => { setCsv(e.target.value); setPreview(null); setMapping(null); }}
          aria-label="Paste the outage log"
        />
        <div className="outage-import-side">
          <label className="secondary outage-file">
            Choose a CSV file…
            <input type="file" accept=".csv,.tsv,.txt,text/csv,text/plain" onChange={onFile} hidden />
          </label>
          <input
            className="outage-input"
            placeholder="Name (optional)"
            value={name}
            onChange={(e) => setName(e.target.value)}
            aria-label="Log name"
          />
          <button type="button" disabled={!csv.trim() || busy} onClick={() => run(null, opts, assetMap)}>
            {preview ? "Check again" : "Read columns"}
          </button>
          {onCancel && (
            <button type="button" className="linkish" onClick={onCancel}>Cancel</button>
          )}
        </div>
      </div>

      {error && <div className="error">{error}</div>}

      {preview && mapping && (
        <>
          <div className="mapper outage-mapper">
            <div className="map-group">
              <div className="map-group-title"><span>Columns</span></div>
              <div className="map-fields outage-map-fields">
                {FIELDS.map((f) => (
                  <label
                    key={f.key}
                    className={"map-field" + (mapping[f.key] ? " selected" : "")}
                    title={`${f.label}${f.req ? " (required)" : ""} — ${f.help}`}
                  >
                    <span className="map-badge">
                      {f.label}
                      {f.req && <i className="req">*</i>}
                    </span>
                    <Select
                      className="sel-embedded"
                      value={mapping[f.key] || ""}
                      onChange={(v) => setField(f.key, v)}
                      options={columnOptions}
                    />
                  </label>
                ))}
              </div>
            </div>
            <div className="outage-opts">
              <label>
                <span>Window start</span>
                <input className="outage-input" value={opts.window_start} placeholder="first outage"
                  onChange={(e) => setOpt("window_start", e.target.value)}
                  onBlur={() => run(mapping, opts, assetMap)} />
              </label>
              <label>
                <span>Window end</span>
                <input className="outage-input" value={opts.window_end} placeholder="last record"
                  onChange={(e) => setOpt("window_end", e.target.value)}
                  onBlur={() => run(mapping, opts, assetMap)} />
              </label>
              <label>
                <span>Dates like 03/04</span>
                <Select
                  value={opts.date_order}
                  onChange={(v) => { const o = { ...opts, date_order: v }; setOpts(o); run(mapping, o, assetMap); }}
                  options={[
                    { value: "auto", label: "Detect" },
                    { value: "dmy", label: "Day first" },
                    { value: "mdy", label: "Month first" },
                  ]}
                />
              </label>
              <label>
                <span>Numbers / durations in</span>
                <input className="outage-input" value={opts.unit} placeholder={unit || "diagram unit"}
                  onChange={(e) => setOpt("unit", e.target.value)}
                  onBlur={() => run(mapping, opts, assetMap)} />
              </label>
            </div>
          </div>

          {preview.ok ? (
            <div className="outage-check">
              <p>
                <b>{preview.n_outages}</b> outage{preview.n_outages === 1 ? "" : "s"} over a window of{" "}
                <b>{fmt(preview.window.end - preview.window.start)}</b> {preview.unit}
                {preview.origin ? ` from ${when(preview.origin)}` : ""}.
              </p>
              <div className="outage-assets">
                {preview.assets.map((a) => (
                  <div className={"outage-asset" + (a.node_id ? "" : " unmapped")} key={a.name}>
                    <span className="outage-asset-name" title={a.name}>{a.name}</span>
                    <span className="muted-line">{a.n_outages} outage{a.n_outages === 1 ? "" : "s"} →</span>
                    <Select
                      value={a.node_id || ""}
                      onChange={(v) => mapAsset(a.name, v)}
                      options={[{ value: "", label: "— not mapped —" }, ...blocks.map((b) => ({ value: b.id, label: b.label }))]}
                    />
                  </div>
                ))}
              </div>
              {preview.notes?.length > 0 && (
                <ul className="outage-notes">
                  {preview.notes.map((n, i) => <li key={i}>{n}</li>)}
                </ul>
              )}
              <div className="rbd-calc-actions">
                <button type="button" disabled={busy} onClick={save}>Save log and show history</button>
              </div>
            </div>
          ) : (
            <div className="error outage-errors">
              {preview.errors?.length ? (
                <>
                  <b>{preview.errors.length} row{preview.errors.length === 1 ? "" : "s"} can't be read:</b>
                  <ul>{preview.errors.slice(0, 20).map((e, i) => <li key={i}>{e}</li>)}</ul>
                </>
              ) : (
                preview.error
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Results
// ---------------------------------------------------------------------------

function TimelineChart({ history, labels }) {
  const unit = history.unit || "";
  const sec = unitSeconds(unit);
  const origin = history.window_dates?.start ? new Date(history.window_dates.start + "Z") : null;
  // A dated log is drawn on a date axis; otherwise in the diagram's unit.
  const dated = !!(origin && sec);
  const w0 = history.window.start;
  const toX = (t) => (dated ? new Date(origin.getTime() + (t - w0) * sec * 1000).toISOString() : t);
  const span = (a, b) => (dated ? (b - a) * sec * 1000 : b - a);

  const order = useMemo(() => {
    const ids = [...new Set(history.bars.map((b) => b.node_id))];
    const rank = Object.fromEntries(history.components.map((c, i) => [c.node_id, i]));
    return ids.sort((a, b) => (rank[b] ?? 0) - (rank[a] ?? 0));
  }, [history]);

  const barTrace = (planned) => {
    const bars = history.bars.filter((b) => b.planned === planned);
    return {
      type: "bar",
      orientation: "h",
      name: planned ? "Planned outage" : "Unplanned outage",
      y: bars.map((b) => labels[b.node_id] || b.node_id),
      base: bars.map((b) => toX(b.start)),
      x: bars.map((b) => span(b.start, b.end)),
      customdata: bars.map((b) => [fmt(b.end - b.start), b.ongoing ? " (still down)" : ""]),
      hovertemplate: `%{y}: down %{customdata[0]} ${unit}%{customdata[1]}<extra></extra>`,
      marker: { color: planned ? PLANNED : FAIL, line: { width: 0 } },
      xaxis: "x",
      yaxis: "y",
      width: 0.6,
    };
  };

  const data = [
    {
      type: "scatter",
      mode: "lines",
      name: "System",
      x: history.series.t.map(toX),
      y: history.series.up,
      line: { shape: "hv", color: "#2f6df6", width: 2 },
      hovertemplate: "%{y:.0f}<extra>System up (1) / down (0)</extra>",
      xaxis: "x",
      yaxis: "y2",
      showlegend: false,
    },
    barTrace(false),
    barTrace(true),
  ].filter((t) => t.type !== "bar" || t.y.length);

  const rows = Math.max(order.length, 1);
  const height = 150 + rows * 26;
  return (
    <div className="outage-chart">
      <Plot
        data={data}
        layout={{
          autosize: true,
          height,
          margin: { l: 110, r: 16, t: 10, b: 40 },
          paper_bgcolor: "rgba(0,0,0,0)",
          plot_bgcolor: "rgba(0,0,0,0)",
          barmode: "overlay",
          bargap: 0.3,
          showlegend: true,
          legend: { orientation: "h", x: 0, y: -0.12, yanchor: "top", font: { size: 11 } },
          xaxis: {
            type: dated ? "date" : "linear",
            title: dated ? undefined : `Time (${unit || "diagram unit"})`,
            range: [toX(w0), toX(history.window.end)],
            gridcolor: "#eef1f5",
            zeroline: false,
          },
          yaxis: {
            domain: [0, rows > 0 ? 0.74 : 0],
            categoryorder: "array",
            categoryarray: order.map((id) => labels[id] || id),
            automargin: true,
            gridcolor: "#f4f5f7",
          },
          yaxis2: {
            domain: [0.8, 1],
            range: [-0.15, 1.15],
            tickvals: [0, 1],
            ticktext: ["Down", "Up"],
            gridcolor: "#f4f5f7",
            zeroline: false,
            title: { text: "System", font: { size: 11 } },
          },
        }}
        useResizeHandler
        style={{ width: "100%" }}
        config={{ displayModeBar: false, responsive: true }}
      />
    </div>
  );
}

function OutageTable({ history }) {
  const [all, setAll] = useState(false);
  const unit = history.unit || "";
  const rows = all ? history.outages : history.outages.slice(0, 50);
  if (!history.outages.length) return <p className="muted-line">The system never went down in the window.</p>;
  return (
    <div className="rbd-avail-imp">
      <div className="ds-section-h">System outages</div>
      <div className="rbd-avail-imp-scroll">
        <table className="calc-table outage-table">
          <thead>
            <tr>
              <th>#</th>
              <th>Down</th>
              <th>Duration ({unit || "unit"})</th>
              <th title="The block whose outage took the system down (RePyability's attribution)">Caused by</th>
              <th title="Other blocks already down when the system went down">Also down</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((o) => (
              <tr key={o.n}>
                <td>{o.n}</td>
                <td>{o.start_at ? when(o.start_at) : fmt(o.start, 6)}</td>
                <td>
                  {fmt(o.duration)}
                  {o.ongoing && <span className="outage-tag">still down</span>}
                  {o.planned && <span className="outage-tag planned">planned</span>}
                </td>
                <td className="calc-row-label"><b>{o.cause_label}</b></td>
                <td>{o.down_with_labels.join(", ") || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {history.outages.length > rows.length && (
        <button type="button" className="linkish" onClick={() => setAll(true)}>
          Show all {history.outages.length} outages
        </button>
      )}
    </div>
  );
}

function Ranking({ history }) {
  const unit = history.unit || "";
  const comps = history.components;
  return (
    <div className="rbd-avail-imp">
      <div className="ds-section-h">What drove the downtime</div>
      <div className="rbd-avail-nodes">
        {comps.filter((c) => c.system_downtime > 0).map((c) => (
          <div className="rbd-avail-bar" key={c.node_id}>
            <span className="rbd-avail-bar-label" title={c.label}>{c.label}</span>
            <span className="rbd-avail-bar-track">
              <span className="rbd-avail-bar-fill" style={{ width: `${Math.round((c.share || 0) * 100)}%` }} />
            </span>
            <span className="rbd-avail-bar-pct">{((c.share || 0) * 100).toFixed(1)}%</span>
          </div>
        ))}
      </div>
      <div className="rbd-avail-imp-scroll">
        <table className="calc-table">
          <thead>
            <tr>
              <th>Block</th>
              <th title="System outages this block caused">System outages</th>
              <th title="System downtime in the outages it caused">System downtime</th>
              <th>Share</th>
              <th title="The block's own outages (failures + planned)">Own outages</th>
              <th>Own downtime</th>
              <th>Own availability</th>
            </tr>
          </thead>
          <tbody>
            {comps.map((c) => (
              <tr key={c.node_id}>
                <td className="calc-row-label">{c.label}</td>
                <td>{c.system_outages}</td>
                <td>{fmt(c.system_downtime)} {unit}</td>
                <td>{pct(c.share, 1)}</td>
                <td>{c.outages}{c.planned_outages ? ` (${c.planned_outages} planned)` : ""}</td>
                <td>{fmt(c.downtime)} {unit}</td>
                <td>{pct(c.availability, 2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

const paramText = (params) => (params || []).map((p) => `${p.name} ${fmt(p.value)}`).join(", ");

function FitPanel({ rbdId, logId, readOnly, onApplyModels }) {
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [picked, setPicked] = useState({});
  const [applied, setApplied] = useState(null);

  const run = async () => {
    setBusy(true);
    setError(null);
    setApplied(null);
    try {
      const r = await fitOutageModels(rbdId, logId, { distribution: "weibull", repair_distribution: "lognormal" });
      setResult(r);
      setPicked(Object.fromEntries(r.components.filter((c) => c.life?.model).map((c) => [c.node_id, true])));
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const apply = () => {
    const updates = {};
    for (const c of result.components) {
      if (!picked[c.node_id]) continue;
      const u = {};
      if (c.life?.model) u.model = c.life.model;
      if (c.repair?.model) u.repair = c.repair.model;
      if (Object.keys(u).length) updates[c.node_id] = u;
    }
    onApplyModels?.(updates);
    setApplied(Object.keys(updates).length);
  };

  return (
    <div className="rbd-avail-imp">
      <div className="ds-section-h">Life and repair models from this log</div>
      <p className="hint">
        Fits a Weibull to each block's times between failures (the last up period, and any cut short by a planned
        outage, right-censored) and a lognormal to its repair times.
      </p>
      {!result && (
        <div>
          <button type="button" className="secondary" disabled={busy} onClick={run}>
            {busy ? "Fitting…" : "Fit models from the log"}
          </button>
        </div>
      )}
      {error && <div className="error">{error}</div>}
      {result && (
        <>
          <div className="rbd-avail-imp-scroll">
            <table className="calc-table">
              <thead>
                <tr>
                  <th />
                  <th>Block</th>
                  <th>Life (Weibull)</th>
                  <th>Repair (lognormal)</th>
                </tr>
              </thead>
              <tbody>
                {result.components.map((c) => (
                  <tr key={c.node_id}>
                    <td>
                      <input
                        type="checkbox"
                        disabled={!c.life?.model && !c.repair?.model}
                        checked={!!picked[c.node_id]}
                        onChange={(e) => setPicked((p) => ({ ...p, [c.node_id]: e.target.checked }))}
                        aria-label={`Use the models for ${c.label}`}
                      />
                    </td>
                    <td className="calc-row-label">{c.label}</td>
                    <td>
                      {c.life?.model ? paramText(c.life.params) : <span className="muted-line">{c.life?.error}</span>}
                      <div className="muted-line">{c.life?.failures} failures, {c.life?.censored} censored</div>
                    </td>
                    <td>
                      {c.repair?.model ? paramText(c.repair.params) : <span className="muted-line">{c.repair?.error}</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="muted-line">{result.note}</p>
          {!readOnly && onApplyModels && (
            <div className="rbd-calc-actions">
              <button type="button" onClick={apply} disabled={!Object.values(picked).some(Boolean)}>
                Use on the ticked blocks
              </button>
              {applied != null && (
                <span className="rbd-saved-note">
                  Put on {applied} block{applied === 1 ? "" : "s"} in the builder — save the diagram to keep them.
                </span>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function HistoryView({ history, labels }) {
  const k = history.kpis;
  const unit = history.unit || "";
  const u = unit ? ` ${unit}` : "";
  return (
    <div className="rbd-avail">
      <div className="rbd-avail-hero">
        <div className="rbd-avail-big">{pct(k.availability, 3)}</div>
        <div className="rbd-avail-cap">
          Observed availability over {fmt(k.window)}
          {u}
          {history.window_dates ? ` (${when(history.window_dates.start)} to ${when(history.window_dates.end)})` : ""}
        </div>
      </div>
      <div className="rbd-avail-metrics">
        <div className="alt-metric"><span className="k">System outages</span><span className="v">{k.outages}</span></div>
        <div className="alt-metric"><span className="k">Failures / planned</span><span className="v">{k.failures} / {k.planned_outages}</span></div>
        <div className="alt-metric"><span className="k">Total downtime</span><span className="v">{fmt(k.downtime)}{u}</span></div>
        <div className="alt-metric"><span className="k">Mean downtime</span><span className="v">{fmt(k.mean_downtime)}{k.mean_downtime != null ? u : ""}</span></div>
        <div className="alt-metric" title="Uptime per system failure"><span className="k">Observed MTBF</span><span className="v">{fmt(k.mtbf)}{k.mtbf != null ? u : ""}</span></div>
      </div>
      <TimelineChart history={history} labels={labels} />
      <OutageTable history={history} />
      <Ranking history={history} />
      {history.notes?.length > 0 && (
        <ul className="outage-notes">
          {history.notes.map((n, i) => <li key={i}>{n}</li>)}
        </ul>
      )}
    </div>
  );
}

export default function OutageHistory({ rbdId, graph, readOnly, onApplyModels }) {
  const [logs, setLogs] = useState(null);
  const [activeId, setActiveId] = useState(null);
  const [history, setHistory] = useState(null);
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState(null);

  const labels = useMemo(
    () => Object.fromEntries((graph?.nodes || []).map((n) => [n.id, n.data?.label || n.id])),
    [graph]
  );
  const blocks = useMemo(
    () => (graph?.nodes || [])
      .filter((n) => !["input", "output", "knode"].includes(n.type))
      .map((n) => ({ id: n.id, label: n.data?.label || n.id })),
    [graph]
  );

  const load = useCallback(async () => {
    if (!rbdId) return;
    setError(null);
    try {
      const r = await listOutageLogs(rbdId);
      setLogs(r.logs);
      setActiveId((cur) => (cur && r.logs.some((l) => l.id === cur) ? cur : r.logs[0]?.id || null));
    } catch (err) {
      setError(err.message);
      setLogs([]);
    }
  }, [rbdId]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (!rbdId || !activeId) { setHistory(null); return; }
    let live = true;
    setHistory(null);
    getOutageHistory(rbdId, activeId)
      .then((h) => live && setHistory(h))
      .catch((err) => live && setError(err.message));
    return () => { live = false; };
  }, [rbdId, activeId]);

  if (!rbdId) {
    return (
      <div className="outage-empty card note">
        <b>Save the diagram first.</b> An outage log is kept with a saved diagram: its assets are matched to the
        blocks, and the outages are merged through the diagram's structure.
      </div>
    );
  }
  if (error && !logs?.length) return <div className="error">{error}</div>;
  if (logs == null) return <p className="muted-line">Loading…</p>;

  const active = logs.find((l) => l.id === activeId);
  const onSaved = (log) => {
    setImporting(false);
    setLogs((ls) => [log, ...(ls || [])]);
    setActiveId(log.id);
    if (log.history) setHistory(log.history);
  };
  const remove = async () => {
    if (!active) return;
    await deleteOutageLog(rbdId, active.id);
    setActiveId(null);
    load();
  };
  const moveWindow = async (key, value) => {
    if (!active || !value) return;
    try {
      await updateOutageLog(rbdId, active.id, { [key]: value });
      setHistory(await getOutageHistory(rbdId, active.id));
      setError(null);
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <div className="outage-history">
      <p className="hint">
        The diagram's <b>observed</b> availability: real outages of its blocks, merged through its structure
        (series, parallel, k-of-n) by RePyability's timelines, with every system outage traced to the block that
        took it down. It works for any diagram, repairable or not, and uses the diagram as last saved.
      </p>
      {!readOnly && (logs.length === 0 || importing) && (
        <ImportPanel
          rbdId={rbdId}
          unit={graph?.unit}
          blocks={blocks}
          onSaved={onSaved}
          onCancel={logs.length ? () => setImporting(false) : null}
        />
      )}
      {readOnly && logs.length === 0 && <p className="muted-line">No outage logs on this diagram.</p>}

      {logs.length > 0 && !importing && (
        <div className="outage-bar">
          <Select
            value={activeId || ""}
            onChange={setActiveId}
            options={logs.map((l) => ({ value: l.id, label: `${l.name}${l.n_outages != null ? ` (${l.n_outages})` : ""}` }))}
          />
          {!readOnly && (
            <>
              <button type="button" className="secondary" onClick={() => setImporting(true)}>Import another log</button>
              <button type="button" className="secondary danger" onClick={remove}>Delete log</button>
            </>
          )}
        </div>
      )}
      {error && logs.length > 0 && <div className="error">{error}</div>}

      {active && !importing && history && (
        <>
          {!readOnly && (
            <div className="outage-window">
              <span className="muted-line">Observation window:</span>
              <input
                className="outage-input"
                key={`s-${active.id}`}
                defaultValue={history.window_dates ? when(history.window_dates.start) : history.window.start}
                onBlur={(e) => e.target.value !== String(e.target.defaultValue) && moveWindow("window_start", e.target.value)}
                aria-label="Window start"
              />
              <span className="muted-line">to</span>
              <input
                className="outage-input"
                key={`e-${active.id}`}
                defaultValue={history.window_dates ? when(history.window_dates.end) : history.window.end}
                onBlur={(e) => e.target.value !== String(e.target.defaultValue) && moveWindow("window_end", e.target.value)}
                aria-label="Window end"
              />
            </div>
          )}
          <HistoryView history={history} labels={labels} />
          <FitPanel rbdId={rbdId} logId={active.id} readOnly={readOnly} onApplyModels={onApplyModels} />
        </>
      )}
      {active && !importing && !history && !error && <p className="muted-line">Merging the outages…</p>}
    </div>
  );
}
