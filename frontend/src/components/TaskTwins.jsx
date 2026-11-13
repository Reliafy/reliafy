import { useEffect, useState } from "react";
import { getTaskTwins, updateMaintenanceTask } from "../api.js";
import { saveErrorText } from "../confirm.js";
import { twinOfferText, twinWrites, twinsToOffer } from "../taskTwins.js";

// After a task's interval changes: the same task on identical positions (same class, or the same
// parent and a name that differs only in its last letter or number) that still has another
// interval, offered in one line with "Apply to …" and "Not now". Nothing changes on a twin unless
// asked. Shared by the Explorer's Maintenance tab and the RCM's task details.
//   taskId, name    the task just changed; interval, unit: its new interval
//   onDone(said)    after Apply (said: what was done) or Not now (said: null); also when
//                   there's nothing to offer
export default function TaskTwins({ taskId, name, interval, unit, onDone }) {
  const [twins, setTwins] = useState(null);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(null);
  useEffect(() => {
    let on = true;
    getTaskTwins(taskId).then((out) => {
      if (!on) return;
      const offer = twinsToOffer(out, interval, unit);
      if (!offer.length) onDone(null);
      else setTwins(offer);
    }, () => { if (on) onDone(null); });
    return () => { on = false; };
  }, [taskId, interval, unit]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!twins) return null;
  const apply = async () => {
    setBusy(true);
    setFailed(null);
    try {
      for (const w of twinWrites(twins, interval, unit)) await updateMaintenanceTask(w.id, w.body);
    } catch (e) {
      setBusy(false);
      setFailed(saveErrorText(e, { offline: navigator.onLine === false }));
      return;
    }
    onDone(`Gave ${twins.length === 1 ? twins[0].position.name : `${twins.length} identical positions`} the same interval.`);
  };
  return (
    <div className="card task-twins" role="group" aria-label="The same task on identical positions">
      <p>{twinOfferText(name, twins, interval, unit)}</p>
      <div className="maint-row">
        <button type="button" className="sm" onClick={apply} disabled={busy} aria-busy={busy || undefined}>
          {busy ? "Applying…" : twins.length === 1 ? `Apply to ${twins[0].position.name}` : `Apply to all ${twins.length}`}
        </button>
        <button type="button" className="secondary sm" onClick={() => onDone(null)} disabled={busy}>Not now</button>
      </div>
      {failed && <p className="field-error" role="alert">{failed}</p>}
    </div>
  );
}
