# ResultSummary

The answer, first: one plain sentence with the numbers in bold, then at most four tiles, then (outside this component) one chart, then the rest folded under `ResultDetails`.

## Props

- `tone` — "good" (green: a good verdict) | "caveat" (amber: a warning, or a result with a catch) | "bad" (red: a failing verdict, e.g. a requirement not met) | "neutral" (a plan or a fact). Good, caveat and bad carry an icon (✓ ! ✕) so the tone isn't colour alone.
- `sentence` — the answer, with `<b>` around its numbers (tabular, 600).
- `stats` — `[{label, value, hint?}]`, at most 4; values formatted by the caller (`formatNumber`, `formatPercent`).
- children — an optional short muted line under the sentence.

Write the sentence as the decision ("Replace at 9,800 hours…"), not the statistic's name.
