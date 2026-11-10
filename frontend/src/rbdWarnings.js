// A validation result's warnings, with the "like blocks wired in series" hints
// folded. A diagram can carry several of those at once (a diagram built from a
// tree wires every position in series, so each set of numbered positions gets
// one), and a list of them buries everything else. Two or more become one line
// that opens to the list; one is said in full, like any other warning.
//
// ``validation.series_hints`` names which of ``validation.warnings`` they are.
// Returns { plain, hints, summary }: the warnings to list as they are, the
// folded hints (empty when nothing is folded) and the line that stands for them.
export function foldWarnings(validation) {
  const warnings = validation?.warnings || [];
  const marked = new Set(validation?.series_hints || []);
  const hints = warnings.filter((w) => marked.has(w));
  if (hints.length < 2) return { plain: warnings, hints: [], summary: null };
  return {
    plain: warnings.filter((w) => !marked.has(w)),
    hints,
    summary: `${hints.length} groups of like blocks are in series: check whether any are redundant`,
  };
}
