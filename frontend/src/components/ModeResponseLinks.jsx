import { useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { getFailureModeCosts } from "../api.js";
import { responseLine } from "../failureCosts.js";
import { explorerHere } from "../products.js";
import { StepLabel } from "./RcmModeTasks.jsx";

// A failure mode's responses, read-only on the RCM tab (Derryn, 23 Nov 2026: "needs to be in the
// maintenance logic"): what's done if it fails, and when an inspection finds it, each one line with
// the way to the Maintenance tab, where they're tasks raised by the event (responses.py) and edited
// with the cost of the failure itself. "If it fails: Replace drive belt (1.5 h, $85) · Edit in
// Maintenance ›"; "No response if it fails · Add in Maintenance ›". The RCM decision stays here.
// Grid rows of the panel's step grid (`rw-sg`).
export default function ModeResponseLinks({ modeId, positionId }) {
  const location = useLocation();
  const [costs, setCosts] = useState(null);
  useEffect(() => {
    let live = true;
    setCosts(null);
    getFailureModeCosts(modeId).then((d) => live && setCosts(d)).catch(() => live && setCosts({ failed: true }));
    return () => { live = false; };
  }, [modeId]);
  if (!costs || costs.failed) return null;
  const where = (kind) => {
    const resp = costs.responses?.[kind];
    return explorerHere(location.pathname, location.search, resp
      ? { sel: positionId, tab: "maintenance", mtask: resp.id }
      : { sel: positionId, tab: "maintenance", addtask: positionId, respond: kind, fm: modeId });
  };
  const kinds = ["failure", ...(costs.has_check || costs.responses?.found ? ["found"] : [])];
  return (
    <>
      <StepLabel>Responses</StepLabel>
      <div className="rw-sc mresp-links">
        {kinds.map((kind) => {
          const line = responseLine(kind, costs.responses?.[kind], costs.used);
          return (
            <p key={kind} className="mresp-line" data-kind={kind}>
              <span className={line.gap ? "mresp-gap" : undefined}>{line.text}</span>
              {" · "}<Link to={where(kind)} className="mresp-go">{line.action} ›</Link>
            </p>
          );
        })}
      </div>
    </>
  );
}
