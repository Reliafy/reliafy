import { useEffect, useState } from "react";
import { checkBlockMean } from "../api.js";
import { unitAbbr } from "./rbdModelText.js";
import { formatNumber } from "../format.js";
import "./RbdBlockOptions.css";

// "Check by simulation" (#326) on a standby or load-sharing block: the exact
// mean life beside the mean of 20,000 simulated lives and its 95% interval.
// ``node`` is the block as it would be saved ({type, data}); null while the
// dialog is incomplete.
export default function RbdMeanCheck({ node, unit }) {
  const [state, setState] = useState({ status: "idle" });
  // A change to the block makes the last check stale.
  const sig = JSON.stringify(node);
  useEffect(() => setState({ status: "idle" }), [sig]);
  const u = unitAbbr(unit);
  // Four figures: the exact mean and the interval usually agree to three.
  const n4 = (v) => formatNumber(v, { sig: 4 });
  const withU = (v) => `${n4(v)}${u ? ` ${u}` : ""}`;

  const run = async () => {
    setState({ status: "running" });
    try {
      setState({ status: "done", result: await checkBlockMean(node, unit) });
    } catch (e) {
      setState({ status: "error", message: e?.message || "Couldn't check the block." });
    }
  };

  const r = state.result;
  return (
    <div className="rbd-mean-check">
      <button type="button" className="secondary sm" onClick={run} disabled={!node || state.status === "running"}>
        {state.status === "running" ? "Checking…" : "Check by simulation"}
      </button>
      {state.status === "done" && r && (
        <p className="rbd-dlg-echo" role="status">
          Exact mean <b>{withU(r.exact_mean)}</b> · simulated <b>{withU(r.simulated.estimate)}</b>{" "}
          ({Math.round(r.simulated.confidence * 100)}% interval {n4(r.simulated.lower)} to{" "}
          {withU(r.simulated.upper)}, {formatNumber(r.simulated.n_samples)} lives)
          {!r.within && <span className="rbd-mean-check-off"> — outside the interval</span>}
        </p>
      )}
      {state.status === "error" && <p className="hint" role="alert">{state.message}</p>}
    </div>
  );
}
