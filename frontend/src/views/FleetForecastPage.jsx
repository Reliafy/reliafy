import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import CopyId from "../components/CopyId.jsx";
import Plot from "react-plotly.js";
import Select from "../components/Select.jsx";
import { ShareButton } from "../components/ShareDialog.jsx";
import { getFleet, putFleetItems, renameFleet } from "../api.js";

const METHOD_OPTIONS = [
  { value: "renewals", label: "Failures with replacement", hint: "Failed items are replaced and can fail again — spares demand." },
  { value: "single", label: "First failures only", hint: "Each item fails at most once — which items are at risk." },
];

const TrashIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M4 7h16M9 7V5h6v2M7 7l1 13h8l1-13" />
  </svg>
);

const fmt = (v, d = 1) =>
  v === null || v === undefined ? "—" : Number(v).toLocaleString(undefined, { maximumFractionDigits: d });

function csvCell(v) {
  const s = String(v ?? "");
  return /[",\n]/.test(s) ? `"${s.replaceAll('"', '""')}"` : s;
}

// One fleet forecast: settings + items in local state; Save PUTs the whole
// set and returns a freshly computed forecast (never stored server-side).
export default function FleetForecastPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [fleet, setFleet] = useState(null);
  const [settings, setSettings] = useState(null);
  const [items, setItems] = useState([]);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [conflict, setConflict] = useState(false);

  const load = () => {
    getFleet(id)
      .then((f) => {
        if (!f?.id) throw new Error("Unexpected response from the server.");
        setFleet(f);
        setSettings(f.settings || {});
        setItems(f.items || []);
        setDirty(false);
        setConflict(false);
      })
      .catch((e) => setError(e.message));
  };
  useEffect(load, [id]);

  if (error && !fleet) return <div className="app"><div className="card error">{error}</div></div>;
  if (!fleet || !settings) return <div className="app"><div className="card empty">Loading…</div></div>;

  const readOnly = fleet.read_only;
  const forecast = fleet.forecast || {};
  const perItem = Object.fromEntries((forecast.per_item || []).map((r) => [r.id, r]));
  const unit = forecast.unit || "";

  const setSetting = (key, value) => { setSettings((s) => ({ ...s, [key]: value })); setDirty(true); };
  const setItem = (idx, key, value) => {
    setItems((xs) => xs.map((it, i) => (i === idx ? { ...it, [key]: value } : it)));
    setDirty(true);
  };
  const addItem = () => { setItems((xs) => [...xs, { name: "", current_use: 0, rate: null }]); setDirty(true); };
  const removeItem = (idx) => { setItems((xs) => xs.filter((_, i) => i !== idx)); setDirty(true); };

  const onSave = async () => {
    setSaving(true);
    setError(null);
    try {
      const fresh = await putFleetItems(id, settings, items, fleet.updated_at);
      setFleet(fresh);
      setSettings(fresh.settings || {});
      setItems(fresh.items || []);
      setDirty(false);
    } catch (err) {
      if (err.code === "conflict") { setError(err.message); setConflict(true); }
      else setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  const onRename = async () => {
    const name = window.prompt("Forecast name", fleet.name);
    if (!name || !name.trim() || name.trim() === fleet.name) return;
    try {
      const updated = await renameFleet(id, name.trim());
      setFleet((f) => ({ ...f, name: updated.name }));
    } catch (err) {
      setError(err.message);
    }
  };

  const exportCsv = () => {
    const header = ["item", "current_use", "rate_per_period", "prob_any_failure", "expected_failures"];
    const rows = [header, ...items.map((it) => {
      const r = perItem[it.id] || {};
      return [it.name, it.current_use, it.rate ?? settings.default_rate, r.prob_any ?? "", r.expected ?? ""];
    })];
    rows.push([]);
    rows.push(["fleet_expected", forecast.expected ?? ""]);
    rows.push(["interval_p10", forecast.interval?.[0] ?? "", "interval_p90", forecast.interval?.[1] ?? ""]);
    const blob = new Blob([rows.map((r) => r.map(csvCell).join(",")).join("\n")], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${fleet.name.replace(/[^\w\- ]+/g, "").trim() || "fleet-forecast"}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const periodLabels = Array.from({ length: forecast.periods || 0 }, (_, i) => i + 1);

  return (
    <div className="app">
      <header>
        <div>
          <div className="crumb">
            <button className="crumb-link" onClick={() => navigate("/fleet")}>Fleet</button> /{" "}
            <button className="crumb-link" onClick={() => navigate("/fleet/forecasts")}>Failure forecasts</button> /{" "}
            <b>{fleet.name}</b>
          </div>
          <h1>
            {fleet.name}
            {fleet.is_sample && <span className="sample-tag">Sample</span>}
            {fleet.shared_by && <span className="sample-tag shared" title={`Shared by ${fleet.shared_by}`}>Shared</span>}
            {dirty && <span className="dirty-tag">unsaved</span>}
          </h1>
          <p>
            Against{" "}
            <Link to={`/modelling/m/${fleet.model_id}`} className="evidence-link">
              {forecast.model_name || "the linked model"}
            </Link>
            {unit ? ` · time in ${unit}` : ""}
            {fleet.updated_by ? ` · last edited by ${fleet.updated_by}` : ""}
          </p>
          <CopyId id={fleet.id} />
        </div>
        <div className="head-actions">
          <ShareButton collection="fleets" artifactId={fleet.id} name={fleet.name} readOnly={readOnly} />
          {!readOnly && <button className="secondary" onClick={onRename}>Rename</button>}
          <button className="secondary" onClick={exportCsv}>Export CSV</button>
          {!readOnly && (
            <button onClick={onSave} disabled={saving || !dirty}>
              {saving ? "Computing…" : dirty ? "Save & forecast" : "Saved"}
            </button>
          )}
        </div>
      </header>

      {error && (
        <div className="card error">
          {error}
          {conflict && (
            <div style={{ marginTop: "0.6rem" }}>
              <button className="secondary" onClick={load}>Reload latest version</button>
            </div>
          )}
        </div>
      )}

      {forecast.status === "stale" && (
        <div className="card upgrade-nudge">
          <p>{forecast.reason || "The linked life model is unavailable."}</p>
        </div>
      )}

      {forecast.status === "ok" && (
        <div className="stats">
          <div className="stat">
            <div className="k">Expected failures</div>
            <div className="v">{fmt(forecast.expected)}</div>
          </div>
          <div className="stat">
            <div className="k">P10 – P90</div>
            <div className="v sm">{fmt(forecast.interval?.[0])} – {fmt(forecast.interval?.[1])}</div>
          </div>
          <div className="stat">
            <div className="k">Horizon</div>
            <div className="v sm">{forecast.periods} {forecast.period_label}</div>
          </div>
          <div className="stat">
            <div className="k">Method</div>
            <div className="v sm">{forecast.method === "renewals" ? "with replacement" : "first failures"}</div>
          </div>
        </div>
      )}

      <div className="card">
        <div className="row" style={{ gap: "0.8rem", alignItems: "flex-end", flexWrap: "wrap" }}>
          <label className="login-field" style={{ width: 110 }}>
            <span>Horizon</span>
            <input type="number" min="1" max="120" value={settings.periods ?? 12} disabled={readOnly}
                   onChange={(e) => setSetting("periods", e.target.value)} />
          </label>
          <label className="login-field" style={{ width: 130 }}>
            <span>Period</span>
            <input type="text" value={settings.period_label ?? "months"} disabled={readOnly}
                   onChange={(e) => setSetting("period_label", e.target.value)} />
          </label>
          <label className="login-field" style={{ width: 190 }}>
            <span>Usage per period{unit ? ` (${unit})` : ""}</span>
            <input type="number" min="0" step="any" value={settings.default_rate ?? 0} disabled={readOnly}
                   onChange={(e) => setSetting("default_rate", e.target.value)} />
          </label>
          <label className="login-field" style={{ minWidth: 230 }}>
            <span>Counting method</span>
            <Select value={settings.method || "renewals"} onChange={(v) => setSetting("method", v)}
                    options={METHOD_OPTIONS} disabled={readOnly} />
          </label>
        </div>
      </div>

      <div className="card" style={{ marginTop: "1rem" }}>
        <div className="bill-head">
          <h2 style={{ margin: 0 }}>Items</h2>
          {!readOnly && (
            <button className="secondary" onClick={addItem}>+ Add item</button>
          )}
        </div>
        {items.length === 0 ? (
          <p className="muted-line">No items yet — add each in-service unit with its accumulated use.</p>
        ) : (
          <table className="lib-table">
            <thead>
              <tr>
                <th style={{ width: "30%" }}>Item</th>
                <th style={{ width: 170 }}>Current use{unit ? ` (${unit})` : ""}</th>
                <th style={{ width: 190 }}>Rate override</th>
                <th style={{ width: 130 }}>P(failure)</th>
                <th style={{ width: 140 }}>Expected failures</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {items.map((it, idx) => {
                const r = perItem[it.id] || {};
                return (
                  <tr key={it.id || idx} className="lib-row">
                    <td>
                      <input className="cell-input" type="text" value={it.name} placeholder="e.g. Truck 07"
                             disabled={readOnly} onChange={(e) => setItem(idx, "name", e.target.value)} />
                    </td>
                    <td>
                      <input className="cell-input" type="number" min="0" step="any" value={it.current_use}
                             disabled={readOnly} onChange={(e) => setItem(idx, "current_use", e.target.value)} />
                    </td>
                    <td>
                      <input className="cell-input" type="number" min="0" step="any"
                             value={it.rate ?? ""} placeholder={`default (${settings.default_rate ?? 0})`}
                             disabled={readOnly}
                             onChange={(e) => setItem(idx, "rate", e.target.value === "" ? null : e.target.value)} />
                    </td>
                    <td className="lib-n">{r.prob_any === undefined || dirty ? "—" : `${(r.prob_any * 100).toFixed(0)}%`}</td>
                    <td className="lib-n">{r.expected === undefined || dirty ? "—" : fmt(r.expected, 2)}</td>
                    <td className="lib-actions">
                      {!readOnly && (
                        <div className="lib-acts">
                          <button className="act del" title="Remove item" onClick={() => removeItem(idx)}>
                            <TrashIcon />
                          </button>
                        </div>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
        {dirty && items.length > 0 && (
          <p className="muted-line" style={{ marginTop: "0.6rem" }}>
            Unsaved changes — hit "Save &amp; forecast" to recompute the columns.
          </p>
        )}
      </div>

      {forecast.status === "ok" && (forecast.per_period || []).some((v) => v > 0) && (
        <div className="card" style={{ marginTop: "1rem" }}>
          <h2>Expected failures per {String(forecast.period_label || "period").replace(/s$/, "")}</h2>
          <Plot
            data={[{
              type: "bar",
              x: periodLabels,
              y: forecast.per_period,
              marker: { color: "rgba(47, 109, 246, 0.75)" },
              hovertemplate: "%{y:.2f} expected<extra></extra>",
            }]}
            layout={{
              height: 260,
              margin: { l: 46, r: 12, t: 8, b: 40 },
              xaxis: { title: { text: forecast.period_label || "period" }, dtick: 1 },
              yaxis: { title: { text: "expected failures" }, rangemode: "tozero" },
              paper_bgcolor: "rgba(0,0,0,0)",
              plot_bgcolor: "rgba(0,0,0,0)",
              font: { family: "IBM Plex Mono, monospace", size: 11 },
            }}
            config={{ displayModeBar: false, responsive: true }}
            style={{ width: "100%" }}
          />
        </div>
      )}
    </div>
  );
}
