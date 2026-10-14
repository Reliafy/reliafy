import { useMemo, useState } from "react";
import Button from "./ui/Button.jsx";
import { browserTimeZone, shouldSuggestTimeZone, timeZoneOptions } from "../workspaceDate.js";

// A workspace's time zone: a select of IANA zones (blank = UTC), with the
// browser's zone offered when it isn't the one set. `onSave(zone)` returns a
// promise; `readOnly` shows the zone without the controls (a team member who
// isn't the owner).
export default function TimeZonePicker({ value, onSave, readOnly = false }) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const browser = browserTimeZone();
  const zones = useMemo(() => {
    const all = timeZoneOptions();
    return value && !all.includes(value) ? [value, ...all] : all;
  }, [value]);

  const save = async (zone) => {
    setSaving(true);
    setError("");
    try {
      await onSave(zone || null);
    } catch (err) {
      setError(err.message || "Couldn't save the time zone.");
    } finally {
      setSaving(false);
    }
  };

  if (readOnly) {
    return <p className="muted-line" style={{ margin: 0 }}>{value || "Not set (UTC)"} · the team owner sets it.</p>;
  }
  return (
    <>
      <div className="row" style={{ gap: "0.6rem", alignItems: "flex-end", flexWrap: "wrap" }}>
        <label className="login-field" style={{ flex: "1 1 240px", maxWidth: 360, marginBottom: 0 }}>
          <span>Time zone</span>
          <select value={value || ""} disabled={saving} onChange={(e) => save(e.target.value)}>
            <option value="">Not set (UTC)</option>
            {zones.map((z) => <option key={z} value={z}>{z.replaceAll("_", " ")}</option>)}
          </select>
        </label>
        {browser && browser !== value && (value || shouldSuggestTimeZone(null, browser)) && (
          <Button variant="secondary" onClick={() => save(browser)} disabled={saving}>
            Use {browser.replaceAll("_", " ")} (this device)
          </Button>
        )}
      </div>
      {error && <div className="error" style={{ marginBottom: 0 }}>{error}</div>}
    </>
  );
}
