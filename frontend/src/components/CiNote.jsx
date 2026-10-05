// How the parameter intervals are taken (#265): a positive parameter's 95%
// interval is computed on the log scale and transformed back, so it never
// goes below zero. Shown under a parameter table whenever one has intervals.
export default function CiNote({ params, note }) {
  if (!(params || []).some((p) => p && p.ci)) return null;
  return (
    <p className="param-ci-note" title={note || undefined}>
      95% intervals; positive parameters use the log scale, so they stay above zero.
    </p>
  );
}
