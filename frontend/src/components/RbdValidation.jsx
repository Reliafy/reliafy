// Shared RBD validation feedback, used on both the Builder and Calculator tabs.
import MethodTag from "./MethodTag.jsx";

// A structural signature of the diagram (ignoring node positions) so callers
// can tell when it has changed since the last validation.
export function graphSignature(graph) {
  return JSON.stringify({
    nodes: (graph.nodes || []).map((n) => ({
      id: n.id,
      type: n.type,
      data: n.data,
    })),
    edges: (graph.edges || []).map((e) => ({
      source: e.source,
      target: e.target,
    })),
    unit: graph.unit || "",
    // Diagram-level costs (#99) change a repairable diagram's results.
    ...(graph.costs ? { costs: graph.costs } : {}),
  });
}

// Renders the outcome of a validate call: a green pass, or a red panel that
// explains what makes the RBD invalid, and notes which nodes are simulated.
// ``stale`` means the diagram has changed since this result was produced.
export default function ValidationPanel({ validation, stale }) {
  if (!validation) return null;

  if (stale) {
    return (
      <div className="rbd-check rbd-check-bad">
        <span className="rbd-check-icon">⟳</span>
        <div>
          <strong>The diagram has changed since the last check.</strong>
          <p className="rbd-check-note">Validate again to refresh the result.</p>
        </div>
      </div>
    );
  }

  const {
    valid,
    analytic,
    errors,
    warnings,
    non_analytic_nodes: nonAnalytic,
  } = validation;
  const nonAnalyticList = Object.entries(nonAnalytic || {});

  // A repairable diagram (#154): how each availability figure is computed.
  const routes = validation.availability_routes;
  if (valid && routes) {
    const overTime = routes.over_time?.route;
    const exactOverTime = overTime === "exact" || overTime === "numerical";
    return (
      <div className="rbd-check rbd-check-ok">
        <span className="rbd-check-icon">✓</span>
        <div>
          <strong>
            {exactOverTime
              ? "Valid — availability computed with no simulation."
              : "Valid — availability over time needs the simulation."}
          </strong>
          <p className="rbd-check-note">
            Long-run figures <MethodTag method={routes.long_run?.route} /> · availability over time{" "}
            <MethodTag method={overTime} /> · expected failures and downtime{" "}
            <MethodTag method={routes.window?.route} />
            {exactOverTime
              ? ". The simulation adds the spread of outcomes (distributions, criticality)."
              : `. ${routes.over_time?.reason || ""}`}
          </p>
          {warnings && warnings.length > 0 && (
            <ul className="rbd-check-list rbd-check-warn">
              {warnings.map((w, i) => (
                <li key={i}>⚠ {w}</li>
              ))}
            </ul>
          )}
        </div>
      </div>
    );
  }

  // A valid diagram is always calculable. Closed-form when every node is
  // analytic; otherwise the standby / load-sharing nodes are simulated, which
  // is worth saying but is not a problem.
  if (valid) {
    return (
      <div className="rbd-check rbd-check-ok">
        <span className="rbd-check-icon">✓</span>
        <div>
          <strong>
            {analytic ? "Valid and analytically solvable." : "Valid — estimated by simulation."}
          </strong>
          {nonAnalyticList.length > 0 && (
            <p className="rbd-check-note">
              These nodes have no closed-form solution, so the system curve is
              estimated by simulation:{" "}
              {nonAnalyticList.map(([label, type]) => `${label} (${type})`).join(", ")}.
            </p>
          )}
          {warnings && warnings.length > 0 && (
            <ul className="rbd-check-list rbd-check-warn">
              {warnings.map((w, i) => (
                <li key={i}>⚠ {w}</li>
              ))}
            </ul>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="rbd-check rbd-check-bad">
      <span className="rbd-check-icon">✕</span>
      <div>
        {!valid && (
          <>
            <strong>This isn’t a valid reliability block diagram yet.</strong>
            {errors && errors.length > 0 && (
              <ul className="rbd-check-list">
                {errors.map((e, i) => (
                  <li key={i}>{e}</li>
                ))}
              </ul>
            )}
          </>
        )}
        {warnings && warnings.length > 0 && (
          <ul className="rbd-check-list rbd-check-warn">
            {warnings.map((w, i) => (
              <li key={i}>⚠ {w}</li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
