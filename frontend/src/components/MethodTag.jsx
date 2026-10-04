// How a figure is computed (RePyability's analysis_routes, #154): exact
// (closed forms), numerical (deterministic, e.g. a renewal equation on a
// grid, to about 1e-7) or simulated. Shared by the availability results and
// the Validate panel.
const METHOD_HELP = {
  exact: "Exact: closed forms, or the exact structure function over exact block values. No simulation.",
  numerical:
    "Numerical: computed deterministically (each block's renewal equation solved on a grid, to about 1e-7). Same answer every time; no simulation.",
  simulated: "Simulated: a Monte-Carlo estimate.",
  refused: "Not available for this diagram.",
};

const LABELS = { exact: "Exact", numerical: "Numerical", simulated: "Simulated", refused: "Not available" };

export default function MethodTag({ method }) {
  if (!method || !LABELS[method]) return null;
  return (
    <span className={`rbd-method ${method}`} title={METHOD_HELP[method]}>
      {LABELS[method]}
    </span>
  );
}
