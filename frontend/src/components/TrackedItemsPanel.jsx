import { useState } from "react";
import Modal from "./Modal.jsx";
import { createTrackedItem, addTrackedMeasurement } from "../api.js";

const fmt = (v, digits = 0) =>
  v === null || v === undefined ? "—" : Number(v).toLocaleString(undefined, { maximumFractionDigits: digits });

// Health badge from a cached prediction: how worried should the owner be?
export function healthBadge(pred) {
  if (!pred || pred.method === "error") return { label: "monitoring", cls: "health-grey" };
  if ((pred.prob_never_fails ?? 0) > 0.5) return { label: "may never fail", cls: "health-grey" };
  const p = pred.prob_failed;
  if (p === null || p === undefined) return { label: "estimate", cls: "health-grey" };
  if (p >= 0.5) return { label: "replace now", cls: "health-red" };
  if (p >= 0.05) return { label: "plan replacement", cls: "health-amber" };
  return { label: "healthy", cls: "health-green" };
}

export function rulText(pred, unit) {
  if (!pred || pred.method === "error") return "—";
  if (pred.rul === null || pred.rul === undefined) return "—";
  const u = unit ? ` ${unit}` : "";
  const base = `${fmt(pred.rul)}${u}`;
  const [lo, hi] = pred.rul_interval || [null, null];
  if (lo === null && hi === null) return base;
  if (hi === null) return `${base} (≥ ${fmt(lo)})`;
  return `${base} (${fmt(lo)}–${fmt(hi)})`;
}

// Fleet table for a degradation model's tracked items, plus the register-item
// modal. Selecting a row surfaces its RUL chart in the parent.
export default function TrackedItemsPanel({ model, fleetId, items, selectedId, onSelect, onChanged, onDelete }) {
  const [registering, setRegistering] = useState(false);
  const [measuring, setMeasuring] = useState(null); // item receiving a new reading
  const unit = model?.results?.unit || model?.unit || "";

  return (
    <div className="card" style={{ marginTop: "1rem" }}>
      <div className="bill-head">
        <h2 style={{ margin: 0 }}>Tracked items</h2>
        {!(model?.read_only && !model?.is_sample) && (
        <button onClick={() => setRegistering(true)}>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 5v14M5 12h14" />
          </svg>
          Register item
        </button>
        )}
      </div>
      <p className="muted-line">
        Your monitored assets. Add measurements as inspections happen — the
        prediction updates each time.
      </p>

      {items.length === 0 ? (
        <div className="empty" style={{ padding: "1.6rem" }}>
          <p>No tracked items yet. Register one to get its first prediction.</p>
        </div>
      ) : (
        <table className="lib-table">
          <thead>
            <tr>
              <th>Item</th>
              <th>Health</th>
              <th>Remaining life</th>
              <th>Predicted crossing</th>
              <th style={{ width: 90 }}>Readings</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {items.map((it) => {
              const badge = healthBadge(it.prediction);
              const pred = it.prediction || {};
              return (
                <tr
                  key={it.id}
                  className={"lib-row" + (selectedId === it.id ? " selected-row" : "")}
                  onClick={() => onSelect(it.id)}
                >
                  <td>
                    <div className="lib-name">
                      {it.name}
                      {it.is_sample && <span className="sample-tag">Sample</span>}
                    </div>
                  </td>
                  <td><span className={`health-badge ${badge.cls}`}>{badge.label}</span></td>
                  <td className="lib-n">{rulText(pred, unit)}</td>
                  <td className="lib-n">
                    {pred.failure_time === null || pred.failure_time === undefined
                      ? "—"
                      : `${fmt(pred.failure_time)}${unit ? ` ${unit}` : ""}`}
                  </td>
                  <td className="lib-n">{it.n_measurements}</td>
                  <td className="lib-actions">
                    <div className="lib-acts">
                      {!(it.read_only ?? it.is_sample) && (
                        <button
                          className="act"
                          title="Add measurement"
                          onClick={(e) => { e.stopPropagation(); setMeasuring(it); }}
                        >
                          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <path d="M12 5v14M5 12h14" />
                          </svg>
                        </button>
                      )}
                      <button
                        className="act del"
                        title={it.is_sample ? "Hide sample item" : "Delete item"}
                        onClick={(e) => { e.stopPropagation(); onDelete(it); }}
                      >
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                          <path d="M4 7h16M9 7V5h6v2M7 7l1 13h8l1-13" />
                        </svg>
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}

      {registering && (
        <RegisterItemModal
          model={model}
          fleetId={fleetId}
          onClose={() => setRegistering(false)}
          onCreated={(item) => { setRegistering(false); onChanged(item); }}
        />
      )}

      {measuring && (
        <AddMeasurementModal
          model={model}
          item={measuring}
          onClose={() => setMeasuring(null)}
          onAdded={(item) => { setMeasuring(null); onSelect(item.id); onChanged(item); }}
        />
      )}
    </div>
  );
}

function AddMeasurementModal({ model, item, onClose, onAdded }) {
  const [t, setT] = useState("");
  const [y, setY] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const unit = model?.results?.unit || "";
  const mUnit = model?.results?.measurement_unit || "";
  const last = item.measurements?.[item.measurements.length - 1];

  const valid = t !== "" && y !== "" && Number.isFinite(Number(t)) && Number.isFinite(Number(y));

  const onSubmit = async () => {
    setBusy(true);
    setError(null);
    try {
      const updated = await addTrackedMeasurement(model.id, item.id, Number(t), Number(y));
      onAdded(updated);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      title={`New reading — ${item.name}`}
      className="modal-sm"
      onClose={onClose}
      locked={busy}
      footer={
        <div className="row" style={{ margin: 0, marginLeft: "auto" }}>
          <button className="secondary" onClick={onClose} disabled={busy}>Cancel</button>
          <button onClick={onSubmit} disabled={!valid || busy}>
            {busy ? "Predicting…" : "Add & re-predict"}
          </button>
        </div>
      }
    >
      {last && (
        <p className="muted-line" style={{ marginTop: 0 }}>
          Last reading: {last.y}{mUnit ? ` ${mUnit}` : ""} at {last.t}{unit ? ` ${unit}` : ""}.
        </p>
      )}
      <div className="row" style={{ gap: "0.6rem" }}>
        <label className="login-field" style={{ flex: 1 }}>
          <span>Time{unit ? ` (${unit})` : ""}</span>
          <input type="number" step="any" value={t} onChange={(e) => setT(e.target.value)} autoFocus />
        </label>
        <label className="login-field" style={{ flex: 1 }}>
          <span>Measurement{mUnit ? ` (${mUnit})` : ""}</span>
          <input type="number" step="any" value={y} onChange={(e) => setY(e.target.value)} />
        </label>
      </div>
      {error && <div className="error">{error}</div>}
    </Modal>
  );
}

function RegisterItemModal({ model, fleetId, onClose, onCreated }) {
  const [name, setName] = useState("");
  const [rows, setRows] = useState([{ t: "", y: "" }]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const unit = model?.results?.unit || "";
  const mUnit = model?.results?.measurement_unit || "";

  const setRow = (idx, key, value) =>
    setRows((rs) => rs.map((r, i) => (i === idx ? { ...r, [key]: value } : r)));

  const valid =
    name.trim() &&
    rows.some((r) => r.t !== "" && r.y !== "") &&
    rows.every((r) => (r.t === "" && r.y === "") || (Number.isFinite(Number(r.t)) && Number.isFinite(Number(r.y))));

  const onSubmit = async () => {
    setBusy(true);
    setError(null);
    try {
      const measurements = rows
        .filter((r) => r.t !== "" && r.y !== "")
        .map((r) => ({ t: Number(r.t), y: Number(r.y) }));
      const item = await createTrackedItem(model.id, { name: name.trim(), measurements, fleetId });
      onCreated(item);
    } catch (err) {
      setError(err.code === "cap" ? `${err.message}` : err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      title="Register a tracked item"
      className="modal-sm"
      onClose={onClose}
      locked={busy}
      footer={
        <div className="row" style={{ margin: 0, marginLeft: "auto" }}>
          <button className="secondary" onClick={onClose} disabled={busy}>Cancel</button>
          <button onClick={onSubmit} disabled={!valid || busy}>
            {busy ? "Predicting…" : "Register & predict"}
          </button>
        </div>
      }
    >
      <label className="login-field">
        <span>Item name</span>
        <input type="text" value={name} placeholder="e.g. Truck 14 — front left"
               onChange={(e) => setName(e.target.value)} />
      </label>

      <p className="muted-line" style={{ marginBottom: "0.4rem" }}>
        Initial measurements{unit || mUnit ? ` (time in ${unit || "?"}, value in ${mUnit || "?"})` : ""}:
      </p>
      {rows.map((r, idx) => (
        <div className="row" key={idx} style={{ gap: "0.6rem", marginTop: "0.35rem" }}>
          <input type="number" step="any" placeholder="time" value={r.t}
                 onChange={(e) => setRow(idx, "t", e.target.value)} style={{ flex: 1 }} />
          <input type="number" step="any" placeholder="measurement" value={r.y}
                 onChange={(e) => setRow(idx, "y", e.target.value)} style={{ flex: 1 }} />
        </div>
      ))}
      <button
        type="button"
        className="secondary"
        style={{ marginTop: "0.6rem" }}
        onClick={() => setRows((rs) => [...rs, { t: "", y: "" }])}
      >
        + Add measurement
      </button>

      {error && <div className="error">{error}</div>}
    </Modal>
  );
}
