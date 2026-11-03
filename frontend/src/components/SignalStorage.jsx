import { useEffect, useState } from "react";
import { getSignalStorage, setSignalStorageCap } from "../api.js";
import { fmtMB } from "../signals.js";

// What the workspace's snapshots take up, with an optional warning level.
// It only warns: nothing is ever deleted. Shown once there is something stored.

export default function SignalStorage({ refresh }) {
  const [st, setSt] = useState(null);
  const [editing, setEditing] = useState(false);
  const [cap, setCap] = useState("");
  const [err, setErr] = useState(null);

  useEffect(() => {
    let live = true;
    getSignalStorage().then((d) => live && setSt(d)).catch(() => live && setSt(null));
    return () => { live = false; };
  }, [refresh]);
  if (!st || (st.snapshots === 0 && !st.cap_mb)) return null;

  const save = async (value) => {
    setErr(null);
    try {
      setSt(await setSignalStorageCap(value));
      setEditing(false);
    } catch (x) {
      setErr(x.message);
    }
  };
  return (
    <div className={`sg-storage${st.over_cap ? " sg-over" : ""}`} role={st.over_cap ? "alert" : "status"}>
      <span>
        Snapshots in this workspace: <strong>{st.snapshots.toLocaleString("en-GB")}</strong> using <strong>{fmtMB(st.bytes)}</strong>
        {st.cap_mb ? <> of the {st.cap_mb} MB warning level</> : null}.
      </span>
      {st.over_cap && <strong> Over the level you set. Nothing is deleted: this is a reminder to decide what to keep.</strong>}
      {!editing ? (
        <button type="button" className="link" onClick={() => { setCap(st.cap_mb ? String(st.cap_mb) : ""); setEditing(true); }}>
          {st.cap_mb ? "Change the warning level" : "Warn me at a size"}
        </button>
      ) : (
        <form className="sg-inline-row" onSubmit={(e) => { e.preventDefault(); save(cap === "" ? null : Number(cap)); }}>
          <label className="sg-field">Warn above (MB)
            <input type="number" inputMode="decimal" min="1" step="any" value={cap} onChange={(e) => setCap(e.target.value)} placeholder="no warning" />
          </label>
          <button type="submit" className="sm">Save</button>
          {st.cap_mb && <button type="button" className="secondary sm" onClick={() => save(null)}>Turn off</button>}
          <button type="button" className="ghost sm" onClick={() => setEditing(false)}>Cancel</button>
        </form>
      )}
      {err && <span className="sg-bad" role="alert"> {err}</span>}
    </div>
  );
}
