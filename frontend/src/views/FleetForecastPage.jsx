import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import CopyId from "../components/CopyId.jsx";
import Plot from "../components/Plot.jsx";
import { ACCENT, INK, sentence } from "../plotTheme.js";
import Select from "../components/Select.jsx";
import FleetAlertsCard from "../components/FleetAlertsCard.jsx";
import { ShareButton } from "../components/ShareDialog.jsx";
import { getFleet, putFleetItems, renameFleet } from "../api.js";
import { toCsv } from "../csv.js";

const METHOD_OPTIONS = [
  { value: "renewals", label: "Failures with replacement", hint: "Failed items are replaced and can fail again — spares demand." },
  { value: "single", label: "First failures only", hint: "Each item fails at most once — which items are at risk." },
];

const RATE_SOURCE_OPTIONS = [
  { value: "manual", label: "Manual", hint: "The usage per period typed here (and per-item overrides)." },
  { value: "estimated", label: "Estimated from API readings", hint: "Each item's rate learned from timestamped meter readings." },
];

// Period labels the server can turn into wall-clock time (mirrors
// backend/services/fleet.py PERIOD_DAYS) — others can't have rates estimated.
const CALENDAR_UNITS = ["day", "week", "month", "quarter", "year"];
const isCalendarUnit = (label) => {
  const key = String(label || "").trim().toLowerCase();
  return CALENDAR_UNITS.includes(key) || (key.endsWith("s") && CALENDAR_UNITS.includes(key.slice(0, -1)));
};

const TrashIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M4 7h16M9 7V5h6v2M7 7l1 13h8l1-13" />
  </svg>
);

const fmt = (v, d = 1) =>
  v === null || v === undefined ? "—" : Number(v).toLocaleString(undefined, { maximumFractionDigits: d });

const blank = (v) => v === null || v === undefined || v === "";

// A covariate value as typed: numbers go to the server as numbers.
const coerce = (field, raw) =>
  field.type === "number" && raw !== "" && !Number.isNaN(Number(raw)) ? Number(raw) : raw;

// One covariate (regression) or stress (ALT) input (#234): a number box, or
// the model's levels for a categorical covariate. Blank = the default shown.
// ``compact`` (an item's cell) shows the inherited value alone, greyed.
function CovariateInput({ field, value, placeholder, disabled, onChange, className, compact = false }) {
  const inherited = blank(placeholder) ? null : compact ? String(placeholder) : `default (${placeholder})`;
  if (field.type !== "number" && (field.options || []).length) {
    return (
      <Select
        value={blank(value) ? "" : String(value)}
        onChange={(v) => onChange(v)}
        disabled={disabled}
        placeholder={inherited || "choose…"}
        options={[
          { value: "", label: inherited || "—" },
          ...field.options.map((o) => ({ value: String(o), label: String(o) })),
        ]}
      />
    );
  }
  return (
    <input className={className} type={field.type === "number" ? "number" : "text"} step="any"
           value={blank(value) ? "" : value}
           placeholder={inherited || "required"}
           disabled={disabled}
           onChange={(e) => onChange(coerce(field, e.target.value))} />
  );
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
  // A fleet on a recurrent model: repairable items, every failure counted (#235).
  const repairable = fleet.model_kind === "recurrent";
  const forecast = fleet.forecast || {};
  const perItem = Object.fromEntries((forecast.per_item || []).map((r) => [r.id, r]));
  const unit = forecast.unit || "";
  // A regression or ALT model (#234): each item at its own covariates/stress.
  const fields = forecast.covariate_fields || [];
  const byConditions = fields.length > 0 || ["regression", "alt"].includes(fleet.model_kind);
  const fleetCovariates = settings.covariates || {};
  const fieldLabel = (f) => f.label || f.name;
  const fleetDefault = (f) => (blank(fleetCovariates[f.name]) ? f.default : fleetCovariates[f.name]);
  const modelUrl = forecast.model_url
    || (fleet.model_kind === "alt" ? `/modelling/alt/${fleet.model_id}`
      : repairable ? `/modelling/recurrent/${fleet.model_id}` : `/modelling/m/${fleet.model_id}`);
  const single = (settings.method || "renewals") === "single";
  const showService = single && !repairable && !blank(settings.warranty_periods);
  const itemName = Object.fromEntries(items.map((it) => [it.id, it.name]));
  // "Which items are at risk": the five most likely to fail (first failures).
  const atRisk = forecast.status === "ok" && forecast.method === "single" && !dirty
    ? [...(forecast.per_item || [])].filter((r) => r.prob_any > 0)
        .sort((a, b) => b.prob_any - a.prob_any).slice(0, 5)
    : [];

  const setSetting = (key, value) => { setSettings((s) => ({ ...s, [key]: value })); setDirty(true); };
  const setItem = (idx, key, value) => {
    setItems((xs) => xs.map((it, i) => (i === idx ? { ...it, [key]: value } : it)));
    setDirty(true);
  };
  const withValue = (values, name, value) => {
    const next = { ...(values || {}) };
    if (blank(value)) delete next[name];
    else next[name] = value;
    return next;
  };
  const setFleetCovariate = (name, value) => {
    setSettings((s) => ({ ...s, covariates: withValue(s.covariates, name, value) }));
    setDirty(true);
  };
  const setItemCovariate = (idx, name, value) => {
    setItems((xs) => xs.map((it, i) => (i === idx ? { ...it, covariates: withValue(it.covariates, name, value) } : it)));
    setDirty(true);
  };
  const addItem = () => {
    setItems((xs) => [...xs, { name: "", current_use: 0, rate: null, ...(repairable ? { next_service_at: null } : {}) }]);
    setDirty(true);
  };
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
    const header = ["item", "current_use", "rate_per_period", ...fields.map((f) => f.name),
                    "prob_any_failure", "expected_failures"];
    if (repairable) header.push("next_service_at", "prob_failure_before_service");
    const rows = [header, ...items.map((it) => {
      const r = perItem[it.id] || {};
      const row = [it.name, it.current_use, it.rate ?? settings.default_rate,
                   ...fields.map((f) => r.covariates?.[f.name] ?? it.covariates?.[f.name] ?? fleetDefault(f) ?? ""),
                   r.prob_any ?? "", r.expected ?? ""];
      if (repairable) row.push(it.next_service_at ?? "", r.prob_before_service ?? "");
      return row;
    })];
    rows.push([]);
    rows.push(["fleet_expected", forecast.expected ?? ""]);
    rows.push(["interval_p10", forecast.interval?.[0] ?? "", "interval_p90", forecast.interval?.[1] ?? ""]);
    if (forecast.per_period_interval) {
      rows.push([]);
      rows.push(["period", "expected", "p10", "p90"]);
      (forecast.per_period || []).forEach((v, i) =>
        rows.push([i + 1, v, forecast.per_period_interval[i]?.[0] ?? "", forecast.per_period_interval[i]?.[1] ?? ""]));
    }
    const blob = new Blob([toCsv(rows)], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${fleet.name.replace(/[^\w\- ]+/g, "").trim() || "fleet-forecast"}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const periodLabels = Array.from({ length: forecast.periods || 0 }, (_, i) => i + 1);
  const periodBand = forecast.per_period_interval;
  const periodWord = String(forecast.period_label || "period").replace(/s$/, "");

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
            <Link to={modelUrl} className="evidence-link">
              {forecast.model_name || "the linked model"}
            </Link>
            {forecast.model_kind === "alt" ? " (ALT)" : forecast.model_kind === "regression" ? " (regression)" : ""}
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

      {forecast.status === "ok" && (forecast.warnings || []).map((w) => (
        <div key={w} className="card upgrade-nudge"><p>{w}</p></div>
      ))}

      {forecast.status === "ok" && (
        <div className="stats">
          <div className="stat">
            <div className="k">Expected failures</div>
            <div className="v">{fmt(forecast.expected)}</div>
          </div>
          <div className="stat"
               title={forecast.interval_method === "exact"
                 ? "The exact 80% prediction interval of the count (Poisson-binomial), given the model."
                 : repairable
                 ? "The 10th to 90th percentiles of the Poisson count, given the model."
                 : "The 10th to 90th percentiles of the simulated counts."}>
            <div className="k">P10 – P90{forecast.interval_method === "exact" ? " (exact)" : ""}</div>
            <div className="v sm">{fmt(forecast.interval?.[0])} – {fmt(forecast.interval?.[1])}</div>
          </div>
          <div className="stat">
            <div className="k">Horizon</div>
            <div className="v sm">{forecast.periods} {forecast.period_label}</div>
          </div>
          <div className="stat">
            <div className="k">Method</div>
            <div className="v sm">
              {repairable ? "every failure (repairable)" : forecast.method === "renewals" ? "with replacement" : "first failures"}
            </div>
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
          {!repairable && (
            <label className="login-field" style={{ minWidth: 230 }}>
              <span>Counting method</span>
              <Select value={settings.method || "renewals"} onChange={(v) => setSetting("method", v)}
                      options={byConditions
                        ? METHOD_OPTIONS.map((o) => (o.value === "renewals"
                          ? { ...o, disabled: true, hint: "Each item is forecast at its own conditions: first failures only." }
                          : o))
                        : METHOD_OPTIONS}
                      disabled={readOnly} />
            </label>
          )}
          <label className="login-field" style={{ minWidth: 250 }}>
            <span>Usage rate</span>
            <Select value={settings.rate_source || "manual"} onChange={(v) => setSetting("rate_source", v)}
                    options={RATE_SOURCE_OPTIONS} disabled={readOnly} />
          </label>
        </div>
        {repairable && (
          <p className="muted-line">
            Repairable items: each failure is repaired and the item runs on, so every repeat failure is counted
            from the item’s age (time since new) under the recurrent model. Ranges are Poisson P10–P90.
          </p>
        )}
        {single && !repairable && (
          <div className="row fleet-warranty">
            <label className="login-field" style={{ width: 200 }}>
              <span>Warranty: use{unit ? ` (${unit})` : ""}</span>
              <input type="number" min="0" step="any" value={settings.warranty_use ?? ""} placeholder="no limit"
                     disabled={readOnly}
                     onChange={(e) => setSetting("warranty_use", e.target.value === "" ? null : e.target.value)} />
            </label>
            <label className="login-field" style={{ width: 200 }}>
              <span>Warranty: {settings.period_label || "periods"} in service</span>
              <input type="number" min="0" step="any" value={settings.warranty_periods ?? ""} placeholder="no limit"
                     disabled={readOnly}
                     onChange={(e) => setSetting("warranty_periods", e.target.value === "" ? null : e.target.value)} />
            </label>
            <p className="muted-line">
              Failures after an item's warranty ends (whichever limit comes first) aren't counted.
              {forecast.out_of_warranty
                ? ` ${forecast.out_of_warranty} item${forecast.out_of_warranty === 1 ? " is" : "s are"} already out of warranty.`
                : ""}
            </p>
          </div>
        )}
        <p className="muted-line" style={{ marginBottom: 0 }}>
          {settings.rate_source === "estimated"
            ? "Each item uses the rate estimated from meter readings sent through the API with a read_at time; items without one fall back to their override, then the usage per period."
            : "Rates come from the usage per period and per-item overrides. Switch to “Estimated” to use rates learned from timestamped API meter readings."}
        </p>
        {!isCalendarUnit(settings.period_label) && (
          <p className="hint fleet-alert-warn" style={{ marginBottom: 0 }}>
            “{settings.period_label}” isn’t a calendar unit (days, weeks, months, quarters or years), so usage
            rates can’t be estimated from API readings — items use their manual rates.
          </p>
        )}
      </div>

      {fields.length > 0 && (
        <div className="card" style={{ marginTop: "1rem" }}>
          <h2 style={{ marginTop: 0 }}>{forecast.model_kind === "alt" ? "Operating stress" : "Operating conditions"}</h2>
          <p className="muted-line" style={{ marginTop: 0 }}>
            {forecast.model_kind === "alt"
              ? "The stress every item runs at, unless an item sets its own below."
              : "The covariate values every item runs at, unless an item sets its own below. Blank uses the model's default (the training-data mean, or its most common level)."}
          </p>
          <div className="row" style={{ gap: "0.8rem", alignItems: "flex-end", flexWrap: "wrap" }}>
            {fields.map((f) => (
              <label key={f.name} className="login-field" style={{ width: 190 }}>
                <span>{fieldLabel(f)}</span>
                <CovariateInput field={f} value={fleetCovariates[f.name]} placeholder={f.default}
                                disabled={readOnly} onChange={(v) => setFleetCovariate(f.name, v)} />
              </label>
            ))}
          </div>
        </div>
      )}

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
          <div className="fleet-items-scroll">
            <table className={"lib-table fleet-items" + (repairable ? " repairable" : "")}>
              <thead>
                <tr>
                  <th style={{ minWidth: 150 }}>Item</th>
                  <th style={{ width: 150 }}>Current use{unit ? ` (${unit})` : ""}</th>
                  <th style={{ width: 170 }}>Rate override</th>
                  {fields.map((f) => <th key={f.name} style={{ minWidth: 130 }}>{fieldLabel(f)}</th>)}
                  {showService && <th style={{ width: 130 }}>In service ({settings.period_label || "periods"})</th>}
                  {repairable && <th style={{ width: 150 }}>Next service at</th>}
                  <th style={{ width: 110 }}>{repairable ? "P(≥1 failure)" : "P(failure)"}</th>
                  <th style={{ width: 120 }}>Expected failures</th>
                  {repairable && <th style={{ width: 150 }}>P(fail before service)</th>}
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
                        {it.estimated_rate_n >= 1 && (
                          <div className="hint fleet-rate-est"
                               title={`Estimated from ${it.estimated_rate_n} interval(s) between API meter readings`}>
                            est. {fmt(it.estimated_rate)} / {String(settings.period_label || "period").replace(/s$/i, "")}
                            {!dirty && r.rate_basis === "estimated" ? " · in use" : ` · n=${it.estimated_rate_n}`}
                          </div>
                        )}
                      </td>
                      {fields.map((f) => (
                        <td key={f.name}>
                          <CovariateInput field={f} className="cell-input" value={it.covariates?.[f.name]}
                                          placeholder={fleetDefault(f)} disabled={readOnly} compact
                                          onChange={(v) => setItemCovariate(idx, f.name, v)} />
                        </td>
                      ))}
                      {showService && (
                        <td>
                          <input className="cell-input" type="number" min="0" step="any"
                                 value={it.service_periods ?? ""} placeholder="from use ÷ rate"
                                 title="How long the item has been in service; blank estimates it from its use at its rate."
                                 disabled={readOnly}
                                 onChange={(e) => setItem(idx, "service_periods", e.target.value === "" ? null : e.target.value)} />
                        </td>
                      )}
                      {repairable && (
                        <td>
                          <input className="cell-input" type="number" min="0" step="any"
                                 value={it.next_service_at ?? ""} placeholder="—" disabled={readOnly}
                                 title={`The use${unit ? ` (${unit})` : ""} the item is next serviced at`}
                                 onChange={(e) => setItem(idx, "next_service_at", e.target.value === "" ? null : e.target.value)} />
                        </td>
                      )}
                      <td className="lib-n">{r.prob_any === undefined || dirty ? "—" : `${(r.prob_any * 100).toFixed(0)}%`}</td>
                      <td className="lib-n">{r.expected === undefined || dirty ? "—" : fmt(r.expected, 2)}</td>
                      {repairable && (
                        <td className="lib-n">
                          {dirty || it.next_service_at == null || it.next_service_at === ""
                            ? "—"
                            : r.service_overdue
                            ? <span className="fleet-alert-warn" title="The item's use is past its next service">overdue</span>
                            : r.prob_before_service == null
                            ? "—"
                            : `${(r.prob_before_service * 100).toFixed(0)}%`}
                        </td>
                      )}
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
          </div>
        )}
        {dirty && items.length > 0 && (
          <p className="muted-line" style={{ marginTop: "0.6rem" }}>
            Unsaved changes — hit "Save &amp; forecast" to recompute the columns.
          </p>
        )}
      </div>

      {atRisk.length > 0 && (
        <div className="card" style={{ marginTop: "1rem" }}>
          <h2 style={{ marginTop: 0 }}>Most at risk</h2>
          <p className="muted-line" style={{ marginTop: 0 }}>
            The items most likely to fail within {forecast.periods} {forecast.period_label}
            {byConditions ? ", each at its own conditions" : ""}.
          </p>
          <ol className="fleet-risk-list">
            {atRisk.map((r) => (
              <li key={r.id}>
                <span className="fleet-risk-name">{itemName[r.id] || r.id}</span>
                <span className="fleet-risk-p">{(r.prob_any * 100).toFixed(r.prob_any < 0.1 ? 1 : 0)}%</span>
                {r.covariates && Object.keys(r.covariates).length > 0 && (
                  <span className="hint fleet-risk-cond">
                    {fields.map((f) => `${fieldLabel(f)} ${r.covariates[f.name]}`).join(" · ")}
                  </span>
                )}
              </li>
            ))}
          </ol>
        </div>
      )}

      {!readOnly && <FleetAlertsCard fleetId={fleet.id} version={fleet.updated_at} />}

      {forecast.status === "ok" && (forecast.per_period || []).some((v) => v > 0) && (
        <div className="card" style={{ marginTop: "1rem" }}>
          <h2>Expected failures per {periodWord}</h2>
          <Plot
            data={[{
              type: "bar",
              x: periodLabels,
              y: forecast.per_period,
              marker: { color: ACCENT },
              ...(periodBand ? {
                error_y: {
                  type: "data",
                  symmetric: false,
                  array: forecast.per_period.map((v, i) => Math.max(0, (periodBand[i]?.[1] ?? v) - v)),
                  arrayminus: forecast.per_period.map((v, i) => Math.max(0, v - (periodBand[i]?.[0] ?? v))),
                  color: INK,
                  thickness: 1,
                  width: 3,
                },
                customdata: periodBand,
                hovertemplate: "%{y:.2f} expected (P10–P90 %{customdata[0]}–%{customdata[1]})<extra></extra>",
              } : { hovertemplate: "%{y:.2f} expected<extra></extra>" }),
            }]}
            layout={{
              height: 260,
              bargap: 0.35,
              // Whole periods, at most about a dozen labels.
              xaxis: { title: { text: sentence(forecast.period_label || "period") }, tick0: 1, dtick: Math.max(1, Math.ceil(periodLabels.length / 12)) },
              yaxis: { title: { text: "Expected failures" }, rangemode: "tozero" },
            }}
          />
          {periodBand && (
            <p className="muted-line" style={{ margin: "0.3rem 0 0" }}>
              Whiskers: each {periodWord}'s {repairable ? "Poisson" : "exact"} P10–P90 count.
            </p>
          )}
        </div>
      )}
    </div>
  );
}
