// Shared RBD validation feedback, used on both the Builder and Calculator tabs.
import { NO_BLOCKS } from "../rbdReadiness.js";

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
    // A network is checked as one; phases add their own warnings (#160).
    ...(graph.network ? { network: graph.network } : {}),
    ...(graph.phases ? { phases: graph.phases } : {}),
  });
}

// Renders the outcome of a validate call: a green pass, an amber pass that
// carries warnings (never green, #305), or a red panel that explains what
// makes the RBD invalid, and notes which nodes are simulated.
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

  // Nothing to check yet (#271): only Input and Output, or no block on a
  // path between them. A next step, not an error.
  if (validation.empty) {
    return (
      <div className="rbd-check rbd-check-todo">
        <span className="rbd-check-icon">+</span>
        <div>
          <strong>{validation.empty === NO_BLOCKS ? "Nothing to check yet." : "Not connected yet."}</strong>
          <p className="rbd-check-note">{validation.errors?.[0]}</p>
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
  const hasWarnings = !!warnings && warnings.length > 0;
  const okClass = "rbd-check " + (hasWarnings ? "rbd-check-caveat" : "rbd-check-ok");
  const okIcon = hasWarnings ? "!" : "✓";

  // "exact", "numerical (no simulation)" or "simulated": a route in words (#313:
// the method is said in a sentence, not a badge per figure).
const ROUTE_WORDS = { exact: "exact", numerical: "numerical", simulated: "simulated", refused: "simulated" };
function routesSentence(routes) {
  const parts = [
    ["Long-run figures", routes.long_run?.route],
    ["availability over time", routes.over_time?.route],
    ["expected failures and downtime", routes.window?.route],
  ].filter(([, r]) => r);
  return parts.map(([what, r]) => `${what} ${ROUTE_WORDS[r] || r}`).join("; ") + ".";
}

// A repairable diagram (#154): how each availability figure is computed.
  const routes = validation.availability_routes;
  if (valid && routes) {
    const overTime = routes.over_time?.route;
    const exactOverTime = overTime === "exact" || overTime === "numerical";
    return (
      <div className={okClass}>
        <span className="rbd-check-icon">{okIcon}</span>
        <div>
          <strong>
            {exactOverTime
              ? "Valid — availability computed with no simulation."
              : "Valid — availability over time needs the simulation."}
          </strong>
          <p className="rbd-check-note">
            {routesSentence(routes)}{" "}
            {exactOverTime
              ? "The simulation adds the spread of outcomes (distributions, criticality)."
              : routes.over_time?.reason || ""}
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
      <div className={okClass}>
        <span className="rbd-check-icon">{okIcon}</span>
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
