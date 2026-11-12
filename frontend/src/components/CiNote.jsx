import { LEVEL_TEXT } from "../levels.js";

// How the parameter intervals are taken (#265): a positive parameter's
// interval (90% two-sided, the app's rule; ``level`` says it) is computed on
// the log scale and transformed back, so it never goes below zero. Shown
// under a parameter table whenever one has intervals.
export default function CiNote({ params, note, level = LEVEL_TEXT }) {
  if (!(params || []).some((p) => p && p.ci)) return null;
  return (
    <p className="param-ci-note" title={note || undefined}>
      {level} intervals (two-sided); positive parameters use the log scale, so they stay above zero.
    </p>
  );
}
