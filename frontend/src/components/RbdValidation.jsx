// Shared RBD validation feedback, used on both the Builder and Calculator tabs.
import { NO_BLOCKS } from "../rbdReadiness.js";
import { foldWarnings } from "../rbdWarnings.js";

// A structural signature of the diagram (ignoring node positions): rbdSignature.js.
export { graphSignature } from "../rbdSignature.js";

// The words (and icon) for "nothing to check" (#271), shared by the panel and
// the Builder's Validate button so they never disagree: no blocks yet ("+",
// add some), or blocks with no path from Input to Output.
export function emptyStatus(validation) {
  return validation?.empty === NO_BLOCKS
    ? { icon: "+", text: "Nothing to check yet" }
    : { icon: "!", text: "Not connected yet" };
}

// A result's warnings: each on its own line, the "like blocks in series" hints
// folded into one line that opens to the list when there are several
// (rbdWarnings.js), so they never bury the answer.
function Warnings({ validation }) {
  const { plain, hints, summary } = foldWarnings(validation);
  if (!plain.length && !hints.length) return null;
  const list = (items) => (
    <ul className="rbd-check-list rbd-check-warn">
      {items.map((w, i) => (
        <li key={i}>⚠ {w}</li>
      ))}
    </ul>
  );
  return (
    <>
      {plain.length > 0 && list(plain)}
      {hints.length > 0 && (
        <details className="rbd-check-fold rbd-check-warn">
          <summary>⚠ {summary}</summary>
          {list(hints)}
        </details>
      )}
    </>
  );
}

// Blocks on no life model (the check's ``needs_model``: [{id, label}]): the system isn't worked out
// until each has one, and no life is invented in its place. Each name opens the block's model
// (``onOpenBlock(id)``) where the page can; otherwise it's plain text.
export function NeedsModels({ blocks, onOpenBlock = null }) {
  if (!blocks?.length) return null;
  const one = blocks.length === 1;
  return (
    <div className="rbd-needs-models">
      <p>{one ? "This block needs" : "These blocks need"} a life model before the system can be worked out:</p>
      <ul className="rbd-check-list">
        {blocks.map((b) => (
          <li key={b.id}>
            {onOpenBlock ? (
              <button type="button" className="link" onClick={() => onOpenBlock(b.id)}
                title={`Give ${b.label} a life model`}>
                {b.label}: add a model
              </button>
            ) : b.label}
          </li>
        ))}
      </ul>
      <p className="rbd-check-note">
        A block that never fails (a frame, a pipe) can be marked Working under Status instead.
      </p>
    </div>
  );
}

// Renders the outcome of a validate call: a green pass, an amber pass that
// carries warnings (never green, #305), or a red panel that explains what
// makes the RBD invalid, and notes which nodes are simulated.
// ``stale`` means the diagram has changed since this result was produced.
export default function ValidationPanel({ validation, stale, onOpenBlock = null }) {
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
    const { icon, text } = emptyStatus(validation);
    return (
      <div className="rbd-check rbd-check-todo">
        <span className="rbd-check-icon">{icon}</span>
        <div>
          <strong>{text}.</strong>
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
          <Warnings validation={validation} />
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
          <Warnings validation={validation} />
        </div>
      </div>
    );
  }

  // The blocks on no life model are listed once, with links (their sentence is errors[0]).
  const needs = validation.needs_model || [];
  const others = needs.length ? (errors || []).slice(1) : errors || [];
  return (
    <div className="rbd-check rbd-check-bad">
      <span className="rbd-check-icon">✕</span>
      <div>
        {!valid && (
          <>
            <strong>
              {needs.length && others.length === 0
                ? "Not calculated yet: some blocks have no life model."
                : "This isn’t a valid reliability block diagram yet."}
            </strong>
            <NeedsModels blocks={needs} onOpenBlock={onOpenBlock} />
            {others.length > 0 && (
              <ul className="rbd-check-list">
                {others.map((e, i) => (
                  <li key={i}>{e}</li>
                ))}
              </ul>
            )}
          </>
        )}
        <Warnings validation={validation} />
      </div>
    </div>
  );
}
