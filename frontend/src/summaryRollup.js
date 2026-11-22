const n = (k, one, many = `${one}s`) => `${k.toLocaleString("en-AU")} ${k === 1 ? one : many}`;

// Everything here and below, at every depth (Derryn, 22 Nov 2026: the Explorer aggregates
// downwards), counted by the server in one read (GET /rollup, inside the asset opened: ?root=):
// positions and fitted items below it, and the tasks, failure modes, models and failure reports
// on it and below it, each a chip that opens the tab listing them. Things are counted, never
// quantities: stock shared between positions isn't added up. Facts about the row itself (what's
// fitted, where it is) stay in Facts.
const ROLLUP = [
  { id: "positions", one: "position", below: true },
  { id: "items", one: "fitted item", below: true, asset: true },
  { id: "tasks", one: "task", tab: "maintenance" },
  { id: "failure_modes", one: "failure mode", tab: "rcm" },
  { id: "models", one: "model", tab: "models", title: "Life models, RBDs and predictions linked to positions (each RBD's missions are under it on the Models tab)" },
  { id: "failure_reports", one: "failure report", tab: "reports", open: "open_reports" },
];

export function rollupChips(data, { design = false } = {}) {
  if (!data) return [];
  const out = [];
  for (const c of ROLLUP) {
    if (c.asset && design) continue;
    const here = c.below ? 0 : data.here[c.id] || 0;
    const inside = data.inside[c.id] || 0;
    const total = here + inside;
    if (!total) continue;
    let text = `${n(total, c.one)}${c.below ? " below" : ""}`;
    if (c.open) {
      const open = (c.below ? 0 : data.here[c.open] || 0) + (data.inside[c.open] || 0);
      if (open) text += `, ${open.toLocaleString("en-AU")} open`;
    }
    const title = c.below ? `At every level below this one` : `${here.toLocaleString("en-AU")} here, ${inside.toLocaleString("en-AU")} below`;
    out.push({ id: c.id, text, title: c.title ? `${c.title}. ${title}` : title, tab: c.tab || null });
  }
  return out;
}
