import { useState } from "react";
import { createSignalChannel } from "../api.js";
import "./SignalsPanel.css";

// Add a signal channel (a sensor that sends snapshots) on a position or an
// item: `target` is { positionId } or { itemId }. Used by the Explorer's
// Measurements tab ("Add a sensor channel…") and the channel lists.
export default function NewChannel({ target, onDone, onCancel }) {
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
