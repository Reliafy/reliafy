import { useEffect, useState } from "react";
import Button from "./ui/Button.jsx";

const COMMON = ["$", "€", "£", "¥", "₹", "R"];

// A workspace's currency symbol: what costs are labelled with ("$255 a
// year"). Only a label: costs are numbers in whatever currency you use and
// nothing is converted. ``onSave(symbol)`` returns a promise; ``readOnly``
// shows it without the controls (a team member who isn't the owner).
export default function CurrencyPicker({ value, onSave, readOnly = false }) {
  const [text, setText] = useState(value || "$");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  useEffect(() => setText(value || "$"), [value]);

  if (readOnly) {
    return <p className="muted-line" style={{ margin: 0 }}>{value || "$"} · the team owner sets it.</p>;
  }
  const save = async (sym) => {
    setSaving(true);
    setError("");
    setSaved(false);
    try {
      await onSave(sym.trim() || null);
      setSaved(true);
    } catch (err) {
      setError(err.message || "Couldn't save the currency symbol.");
    } finally {
      setSaving(false);
    }
  };
  const dirty = text.trim() !== (value || "$");
  return (
    <>
      <form className="row" style={{ gap: "0.6rem", alignItems: "flex-end", flexWrap: "wrap" }}
            onSubmit={(e) => { e.preventDefault(); save(text); }}>
        <label className="login-field" style={{ width: 140, marginBottom: 0 }}>
          <span>Currency symbol</span>
          <input type="text" value={text} maxLength={4} list="currency-symbols" disabled={saving}
                 onChange={(e) => { setText(e.target.value); setSaved(false); }} />
          <datalist id="currency-symbols">
            {COMMON.map((c) => <option key={c} value={c} />)}
          </datalist>
        </label>
        <Button type="submit" variant="secondary" disabled={saving || !dirty || !text.trim()}>
          {saving ? "Saving…" : "Save"}
        </Button>
        {saved && !dirty && <span className="muted-line" role="status">Saved.</span>}
      </form>
      {error && <div className="error" style={{ marginBottom: 0 }}>{error}</div>}
    </>
  );
}
