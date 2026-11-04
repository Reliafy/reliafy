import { useState } from "react";
import { updateSignalBand } from "../api.js";
import { fmt } from "../signals.js";

// Change a watch band: its name, its range and its levels (warn and alarm, above
// and below). A new range does not rewrite the past: the band keeps what it
// recorded and carries on with the new range from the next snapshot, and the
// trend marks where it changed. Warn levels draw a line; alarm levels also open
// an inspection, as for any measurement point.

const blank = (v) => (v === null || v === undefined ? "" : String(v));
const num = (t) => (t.trim() === "" ? null : Number(t));

export default function SignalBandEditor({ band, rpm, onSaved, onCancel }) {
  const isBand = band.rule.type === "band";
  const [f, setF] = useState({
    name: band.name, low: blank(band.rule.low), high: blank(band.rule.high), unit: band.rule.in || "Hz",
    warn_above: blank(band.warn_above), alarm_above: blank(band.alarm_above),
    warn_below: blank(band.warn_below), alarm_below: blank(band.alarm_below),
  });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const set = (k) => (e) => setF((x) => ({ ...x, [k]: e.target.value }));
  const rangeChanged = isBand && (Number(f.low) !== band.rule.low || Number(f.high) !== band.rule.high || f.unit !== band.rule.in);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const body = {
        name: f.name.trim(), warn_above: num(f.warn_above), alarm_above: num(f.alarm_above),
        warn_below: num(f.warn_below), alarm_below: num(f.alarm_below),
      };
      if (rangeChanged) Object.assign(body, { low: Number(f.low), high: Number(f.high), unit: f.unit });
      const out = await updateSignalBand(band.point_id, body);
      await onSaved(out);
    } catch (x) {
      setErr(x.message);
      setBusy(false);
    }
  };
  const u = band.unit || "units";
  return (
    <form className="sg-edit" onSubmit={submit} aria-label={`Edit ${band.name}`}>
      <h4>Edit “{band.name}”</h4>
      <div className="sg-grid">
        <label className="sg-field">Name<input value={f.name} onChange={set("name")} required maxLength={200} /></label>
        {isBand && (
          <>
            <label className="sg-field">From ({f.unit === "orders" ? "× speed" : "Hz"})
              <input type="number" inputMode="decimal" min="0" step="any" value={f.low} onChange={set("low")} required />
            </label>
            <label className="sg-field">To ({f.unit === "orders" ? "× speed" : "Hz"})
              <input type="number" inputMode="decimal" min="0" step="any" value={f.high} onChange={set("high")} required />
            </label>
            {(rpm || band.rule.in === "orders") && (
              <label className="sg-field">Follows
                <select value={f.unit} onChange={set("unit")}>
                  <option value="Hz">These Hz</option>
                  <option value="orders">Running speed</option>
                </select>
              </label>
            )}
          </>
        )}
        <label className="sg-field">Warn above ({u})<input type="number" inputMode="decimal" step="any" value={f.warn_above} onChange={set("warn_above")} /></label>
        <label className="sg-field">Alarm above ({u})<input type="number" inputMode="decimal" step="any" value={f.alarm_above} onChange={set("alarm_above")} /></label>
        <label className="sg-field">Warn below ({u})<input type="number" inputMode="decimal" step="any" value={f.warn_below} onChange={set("warn_below")} /></label>
        <label className="sg-field">Alarm below ({u})<input type="number" inputMode="decimal" step="any" value={f.alarm_below} onChange={set("alarm_below")} /></label>
      </div>
      <p className="sg-hint">
        Leave a level empty for none. A warning only draws a line on the chart; an alarm also opens an inspection when the
        level passes it.
        {rangeChanged && (
          <strong> A new range starts from the next snapshot. What the band recorded so far stays as it was measured (the old
            range, {fmt(band.rule.low)} to {fmt(band.rule.high)}), and the chart marks the change. To see the new range over
            earlier snapshots, add it as a new band.</strong>
        )}
      </p>
      {err && <p className="sg-note sg-bad" role="alert">{err}</p>}
      <div className="sg-actions">
        <button type="submit" disabled={busy || !f.name.trim()}>{busy ? "Saving…" : "Save changes"}</button>
        <button type="button" className="secondary" onClick={onCancel}>Cancel</button>
      </div>
    </form>
  );
}
