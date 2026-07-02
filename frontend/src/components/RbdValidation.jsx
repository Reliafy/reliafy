// Shared RBD validation feedback, used on both the Builder and Calculator tabs.

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
  });
}

// Renders the outcome of a validate call: a green pass, or a red panel that
// explains what makes the RBD invalid and/or not analytically solvable.
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

  if (valid && analytic) {
    return (
      <div className="rbd-check rbd-check-ok">
        <span className="rbd-check-icon">✓</span>
        <div>
          <strong>Valid and analytically solvable.</strong>
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
        {!valid ? (
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
        ) : (
          <>
            <strong>Valid, but not analytically solvable.</strong>
            <p className="rbd-check-note">
              These nodes require simulation rather than a closed-form
              solution, so the system reliability can’t be computed exactly:
            </p>
            <ul className="rbd-check-list">
              {nonAnalyticList.map(([label, type]) => (
                <li key={label}>
                  {label} <span className="rbd-check-type">({type})</span>
                </li>
              ))}
            </ul>
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
