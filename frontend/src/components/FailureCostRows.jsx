import { useEffect, useState } from "react";
import { getFailureModeCosts, updateFailureMode } from "../api.js";
import { saveErrorText } from "../confirm.js";
import { checkFigure, costFields, placeholderFor, usedText } from "../failureCosts.js";
import { PanelField } from "./PanelField.jsx";
import { StepLabel } from "./RcmModeTasks.jsx";

// A failure mode's "What a failure costs" (the RCM tab's step 2, under its consequence): what one
// failure costs to put right, how long it stops the asset, and what an hour out of use costs
// (backend/maintenance/failure_costs.py). A figure left empty takes the position class's, shown as
// the placeholder; the line under the fields says what one failure costs all in and where each
// figure came from. The forecast (Maintenance › Forecast…) and Optimise… charge each failure this.
// Grid rows of the panel's step grid (`rw-sg`): a label cell, then the fields.
export default function FailureCostRows({ modeId, readOnly = false, onSaid = null }) {
  const [costs, setCosts] = useState(null);
  const [error, setError] = useState(null);
  const [saved, setSaved] = useState({});
  useEffect(() => {
    let live = true;
    setCosts(null); setError(null); setSaved({});
    getFailureModeCosts(modeId).then((d) => live && setCosts(d)).catch((e) => live && setError(e.message));
    return () => { live = false; };
  }, [modeId]);
  const save = (key, raw) => {
    const res = checkFigure(key, raw);
    if (res.error) return res.error;
    return updateFailureMode(modeId, { [key]: res.value }).then((out) => {
      if (out?.costs) setCosts(out.costs);
      setSaved((s) => ({ ...s, [key]: (s[key] || 0) + 1 }));
      onSaid?.("Saved the failure cost.");
      return true;
    }, (e) => saveErrorText(e, { offline: navigator.onLine === false }));
  };
  return (
    <>
      <StepLabel>What a failure costs</StepLabel>
      <div className="rw-sc fcost">
        {error && <p className="fcost-note">Couldn&apos;t read the failure cost: {error}</p>}
        {!costs && !error && <p className="fcost-note">Loading…</p>}
        {costs && (
          <>
            <div className="fcost-fields">
              {costFields().map((f) => (
                <PanelField key={`${modeId}:${f.key}`} label={f.label} help={f.help} type="number" suffix={f.suffix} optional
                            value={costs.own?.[f.key] ?? ""} placeholder={placeholderFor(f.key, costs)} readOnly={readOnly}
                            saved={saved[f.key] || 0} onCommit={(raw) => save(f.key, raw)} />
              ))}
            </div>
            <p className="fcost-note">{usedText(costs.used)}</p>
          </>
        )}
      </div>
    </>
  );
}
