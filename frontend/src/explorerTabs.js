// The tabs of the Explorer's detail panel (Operate › Assets › Explorer): what
// the panel beside the tree can show for the row picked. Summary for every kind
// of row; RCM for a position (its functions, how they fail, the failure modes
// and their decisions, read from the asset tree itself). A tab a kind doesn't
// have isn't shown (never greyed out).
//
// Adding a tab is one entry here (id, label, the kinds of row that have it) and
// its body in TreeDetail. The address names the tab (?tab=rcm, left out for
// Summary); the tab picked stays as you walk the tree, shown on every row of a
// kind that has it, Summary on the others.

export const TABS = [
  { id: "summary", label: "Summary", title: "What it is, where it is, its work and what's inside it", kinds: ["pos", "loc", "item", "group"] },
  { id: "rcm", label: "RCM", title: "What this position does, how it can fail, and the decision for each failure mode", kinds: ["pos"] },
];
const BY_ID = new Map(TABS.map((t) => [t.id, t]));
export const DEFAULT_TAB = "summary";

// The tab the address asks for, if it's one (else Summary).
export function tabParam(value) {
  return BY_ID.has(value) ? value : DEFAULT_TAB;
}

// The tabs a row has.
export function tabsFor(row) {
  if (!row) return [];
  return TABS.filter((t) => t.kinds.includes(row.type));
}

// The tab to show for a row: the one picked if the row has it, else Summary.
export function shownTab(wanted, row) {
  return tabsFor(row).some((t) => t.id === wanted) ? wanted : DEFAULT_TAB;
}

// The RCM tab shows the position picked in the tree; ?inside=1 adds the
// positions inside it ("Include positions inside").
export const insideParam = (value) => value === "1";
