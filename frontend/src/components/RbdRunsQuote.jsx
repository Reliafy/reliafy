import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { quoteRbdSimulation } from "../api.js";
import { runsPath } from "../rbdRuns.js";
import "./RbdRuns.css";

// Beside "Run simulation" (#286): how long the run should take, quoted before
// it runs ("About 15 s, up to 40 s"), and the diagram's run history (#112).
// Nothing shows while the quote loads, or when there's none (a block whose
// mean life isn't known before the run).
export default function RbdRunsQuote({ graph, tMax = null, quick = false, currentState = null, rbdId = null }) {
  const [quote, setQuote] = useState(null);
  const key = JSON.stringify({ graph, tMax, quick, currentState });
  useEffect(() => {
    let live = true;
    setQuote(null);
    if (!graph?.repairable) return undefined;
    quoteRbdSimulation({ graph, tMax, quick, currentState })
      .then((q) => live && setQuote(q?.available ? q : null))
      .catch(() => {}); // no quote: the button stands alone
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);
  if (!quote && !rbdId) return null;
  return (
    <span className="rbd-run-quote">
      {quote && (
        <span title="Estimated from past runs' times: the typical time, and the time 9 in 10 runs finish within">
          {quote.text.charAt(0).toUpperCase() + quote.text.slice(1)}
        </span>
      )}
      {rbdId && <Link to={runsPath(rbdId)}>Run history</Link>}
    </span>
  );
}
