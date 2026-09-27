import { useEffect, useState } from "react";
import { createFleetAlert, deleteFleetAlert, listFleetAlerts, updateFleetAlert } from "../api.js";

const TrashIcon = () => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M4 7h16M9 7V5h6v2M7 7l1 13h8l1-13" />
  </svg>
);

const fmt = (v, d = 1) =>
  v === null || v === undefined ? "—" : Number(v).toLocaleString(undefined, { maximumFractionDigits: d });

const periodsText = (y, label) => {
  const unit = String(label || "periods");
  return `${fmt(y, 2)} ${Number(y) === 1 && /s$/i.test(unit) ? unit.slice(0, -1) : unit}`;
};

function conditionText(rule, label) {
  if (rule.kind === "above") return `Expected failures rise above ${fmt(rule.threshold, 2)}`;
  if (rule.kind === "change") return `Expected failures change by ${fmt(rule.percent, 1)}% or more`;
  return `${fmt(rule.x, 2)} or more failures expected within ${periodsText(rule.y_periods, label)}`;
}

const KINDS = [
  { value: "above", text: () => "Rises above N" },
  { value: "change", text: () => "Changes by more than P%" },
  { value: "within", text: (label) => `X or more failures within Y ${label}` },
];

// Email alerts on the fleet's forecast — only rendered for users who can edit
// the fleet. Rules are evaluated server-side when usage arrives via the API.
// ``version`` (the fleet's updated_at) reloads the list after a save, since the
// horizon and current values can change.
export default function FleetAlertsCard({ fleetId, version }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [kind, setKind] = useState("above");
  const [threshold, setThreshold] = useState("");
  const [percent, setPercent] = useState("25");
  const [x, setX] = useState("1");
  const [y, setY] = useState("3");
  const [busy, setBusy] = useState(false);

  const load = () =>
    listFleetAlerts(fleetId)
      .then((d) => { setData(d); setError(null); })
      .catch((e) => setError(e.message));
  useEffect(() => { load(); }, [fleetId, version]);
  // The alert email's "Manage alerts" link lands on #alerts; the card renders
  // after its fetch, so scroll once it exists.
  const loaded = !!data;
  useEffect(() => {
    if (loaded && window.location.hash === "#alerts") {
      document.getElementById("alerts")?.scrollIntoView({ block: "start" });
    }
  }, [loaded]);

  if (!data) {
    return error ? <div className="card error" style={{ marginTop: "1rem" }}>{error}</div> : null;
  }

  const label = data.period_label || "periods";
  const rules = data.alerts || [];
  const full = rules.length >= (data.max_alerts || 10);

  const onAdd = async (e) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const rule = { kind };
    if (kind === "above") rule.threshold = threshold === "" ? null : Number(threshold);
    if (kind === "change") rule.percent = percent === "" ? null : Number(percent);
    if (kind === "within") { rule.x = x === "" ? null : Number(x); rule.y_periods = y === "" ? null : Number(y); }
    try {
      await createFleetAlert(fleetId, rule);
      setThreshold("");
      await load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  const onToggle = async (rule) => {
    try {
      await updateFleetAlert(fleetId, rule.id, { enabled: !rule.enabled });
      await load();
    } catch (err) {
      setError(err.message);
    }
  };

  const onDelete = async (rule) => {
    try {
      await deleteFleetAlert(fleetId, rule.id);
      await load();
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <div className="card fleet-alerts" id="alerts" style={{ marginTop: "1rem" }}>
      <div className="bill-head">
        <h2 style={{ margin: 0 }}>Alerts</h2>
        <span className="muted-line">
          Now: <b>{fmt(data.current_value)}</b> expected failures over {periodsText(data.periods, label)}
        </span>
      </div>
      <p className="muted-line">
        Checked each time usage for this fleet arrives through the API (Pro). You'll get one email per crossing.
      </p>

      {rules.length === 0 ? (
        <p className="muted-line">No alerts yet.</p>
      ) : (
        <ul className="fleet-alert-list">
          {rules.map((rule) => (
            <li key={rule.id} className={"fleet-alert-row" + (rule.enabled ? "" : " off")}>
              <div className="fleet-alert-main">
                <div className="fleet-alert-cond">{conditionText(rule, label)}</div>
                <div className="hint">
                  {rule.kind === "within" && rule.current_value != null && <>Now {fmt(rule.current_value, 2)} · </>}
                  {rule.last_fired_at
                    ? `Last fired ${new Date(rule.last_fired_at).toLocaleString()}${rule.last_fired_value != null ? ` at ${fmt(rule.last_fired_value)}` : ""}`
                    : "Not fired yet"}
                  {!rule.mine && " · set by a teammate"}
                </div>
                {rule.truncated && (
                  <div className="hint fleet-alert-warn">
                    The horizon is now {periodsText(data.periods, label)} — shorter than this window, so it's
                    checked over the {label} available.
                  </div>
                )}
              </div>
              <label className="set-check fleet-alert-toggle">
                <input type="checkbox" checked={rule.enabled} onChange={() => onToggle(rule)} />
                <span>{rule.enabled ? "On" : "Off"}</span>
              </label>
              <div className="lib-acts">
                <button className="act del" title="Delete alert" onClick={() => onDelete(rule)}>
                  <TrashIcon />
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}

      {!full && (
        <form className="fleet-alert-form" onSubmit={onAdd}>
          <div className="fleet-alert-kinds" role="radiogroup" aria-label="Alert type">
            {KINDS.map((k) => (
              <label key={k.value} className="set-check">
                <input type="radio" name="fleet-alert-kind" value={k.value}
                       checked={kind === k.value} onChange={() => setKind(k.value)} />
                <span>{k.text(label)}</span>
              </label>
            ))}
          </div>
          <div className="row" style={{ marginTop: "0.6rem", alignItems: "flex-end" }}>
            {kind === "above" && (
              <label className="login-field" style={{ width: 170 }}>
                <span>Expected failures (N)</span>
                <input type="number" min="0" step="any" required value={threshold}
                       placeholder={fmt(data.current_value)} onChange={(e) => setThreshold(e.target.value)} />
              </label>
            )}
            {kind === "change" && (
              <label className="login-field" style={{ width: 150 }}>
                <span>Percent (P)</span>
                <input type="number" min="0.1" max="1000" step="any" required value={percent}
                       onChange={(e) => setPercent(e.target.value)} />
              </label>
            )}
            {kind === "within" && (
              <>
                <label className="login-field" style={{ width: 130 }}>
                  <span>Failures (X)</span>
                  <input type="number" min="0.01" step="any" required value={x} onChange={(e) => setX(e.target.value)} />
                </label>
                <label className="login-field" style={{ width: 150 }}>
                  <span>Within (Y {label})</span>
                  <input type="number" min="0.1" max={data.periods || undefined} step="any" required value={y}
                         onChange={(e) => setY(e.target.value)} />
                </label>
              </>
            )}
            <button type="submit" disabled={busy}>{busy ? "Adding…" : "Add alert"}</button>
          </div>
        </form>
      )}
      {full && <p className="muted-line">This fleet has the maximum of {data.max_alerts} alerts.</p>}
      {error && <div className="error" style={{ marginTop: "0.6rem", marginBottom: 0 }}>{error}</div>}
    </div>
  );
}
