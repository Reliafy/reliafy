// The quick forecast tool opened from the Explorer (Open in › on a position, task or package;
// forecast plan step 2, Nov 2026): no form, the records are the inputs. The answer is lines by owner
// (GET /api/maintenance/<kind>/<id>/forecast-lines): each task's own line (certain), each failure
// mode's line with its follow-on (found at an inspection) and corrective (after a failure) lines
// (worked out, with ranges), a total, and what's not counted with where to fix it. Pure parts,
// tested in forecastLines.test.js; drawn by views/ForecastTool.jsx.

const sig = (v, n = 3) => Number(v).toLocaleString("en-GB", { maximumSignificantDigits: n });

const KIND_LABEL = { follow_on: "Follow-on: found at an inspection", corrective: "Corrective: after a failure" };
const NUMBER_WORDS = { certain: "Certain", "worked out": "Worked out", simulated: "Simulated" };

// The table's rows in order: tasks (and visits) first, then each failure mode with its two lines
// under it. [{id, depth, owner, meta, times, hours, cost, spares, number, gaps}]
export function tableRows(lines) {
  const all = lines?.lines || [];
  const planned = all.filter((l) => l.kind === "planned");
  const groups = all.filter((l) => l.kind === "failures");
  const rows = planned.map((l) => ({
    id: l.id, depth: 0, owner: l.owner, link: l.link || null,
    meta: [l.how_often, l.position?.name, l.does?.text].filter(Boolean).join(" · "),
    marker: l.does?.marker || null, line: l,
  }));
  for (const g of groups) {
    const on = g.on || g.position?.name || "";
    const found = g.found_share != null ? `finds ${Math.round(g.found_share * 100)}% in time` : "";
    rows.push({ id: g.id, depth: 0, owner: g.owner, link: g.link || null,
      meta: [on, g.life, found].filter(Boolean).join(" · "), line: g, group: true });
    for (const id of g.lines || []) {
      const l = all.find((x) => x.id === id);
      if (l) rows.push({ id: l.id, depth: 1, owner: KIND_LABEL[l.kind] || l.kind, meta: "", line: l });
    }
  }
  return rows;
}

// A line's cells: times (a range for a chance), hours, cost and spares, or why one isn't known.
export function cells(line, money = (v) => `$${sig(v, 4)}`) {
  const t = line.times || {};
  const chance = line.number !== "certain";
  const times = t.expected == null ? "—" : chance
    ? `${sig(t.expected)}${t.interval ? ` (${sig(t.interval[0])} to ${sig(t.interval[1])})` : ""}` : sig(t.expected);
  const gap = (view) => (line.gaps || []).find((g) => g.view === view)?.text || null;
  const amount = (b, fmt, view) => {
    if (line.kind === "failures") return { text: "", gap: null };
    if (b == null) return { text: null, gap: gap(view) };
    return { text: fmt(b.expected), gap: null };
  };
  const spares = (line.spares || []).map((s) => `${sig(s.expected)} × ${s.name}`).join("; ");
  return {
    times,
    hours: amount(line.hours, (v) => `${sig(v)} h`, "hours"),
    cost: amount(line.cost, money, "cost"),
    spares: line.kind === "failures" ? "" : spares || "—",
    number: NUMBER_WORDS[line.number] || line.number,
  };
}

const horizon = (months) => (Number(months) > 12 && Number(months) % 12 === 0 ? `the next ${Number(months) / 12} years` : `the next ${months} months`);

// The answer first, for a view: {lead, tiles [{label, value}], known, leavesOut}.
export function headline(out, view, money = (v) => `$${sig(v, 4)}`) {
  const tot = out.lines?.totals || {};
  const when = horizon(out.of?.months || 12);
  if (view === "spares") {
    const sp = tot.spares || {};
    const likes = sp.like_items;
    const certain = (sp.items || []).filter((x) => x.certain);
    const parts = [];
    if (likes) parts.push(`${sig(likes.expected)} like items to replace failures (${sig(likes.interval[0])} to ${sig(likes.interval[1])}, 90% two-sided)`);
    for (const c of certain) parts.push(`${sig(c.expected)} × ${c.name}`);
    return { lead: parts.length ? `${parts.join("; ")} in ${when}.` : `No spares recorded for this work in ${when}.`,
      tiles: [], known: sp.known !== false, leavesOut: sp.leaves_out || [] };
  }
  const key = view === "hours" ? "hours" : "cost";
  const t = tot[key] || {};
  const fmt = key === "hours" ? (v) => `${sig(v)} h` : money;
  const known = t.known !== false;
  const word = key === "hours" ? "known hours" : "known costs";
  const range = t.interval ? `${fmt(t.interval[0])} to ${fmt(t.interval[1])}` : null;
  const lead = `${fmt(t.expected || 0)}${known ? "" : ` ${word}`} expected in ${when}${range && t.interval[0] !== t.interval[1] ? ` (90% two-sided: ${range})` : ""}.`;
  const tiles = [];
  if (key === "cost" && t.by_kind) {
    tiles.push({ label: "Planned", value: money(t.by_kind.planned || 0) });
    if (out.lines.lines.some((l) => l.kind === "follow_on")) tiles.push({ label: "Follow-on", value: t.by_kind.follow_on ? money(t.by_kind.follow_on) : "not known" });
    if (out.lines.lines.some((l) => l.kind === "corrective")) tiles.push({ label: "Corrective", value: money(t.by_kind.corrective || 0) });
  }
  return { lead, tiles, known, leavesOut: t.leaves_out || [] };
}

// The line under the header: "3 lives (each 900 h) · Hours from the operating plan (…) · 12 months".
export function metaLine(out) {
  const groups = (out.lines?.lines || []).filter((l) => l.kind === "failures");
  const bits = [];
  if (groups.length) {
    const ages = groups.flatMap((g) => g.ages || []).filter((a) => a != null);
    const unit = groups[0].unit === "hours" ? "h" : groups[0].unit || "";
    const same = ages.length && ages.every((a) => a === ages[0]);
    bits.push(`${ages.length} ${ages.length === 1 ? "life" : "lives"}${ages.length ? (same ? ` (${ages.length === 1 ? "" : "each "}${sig(ages[0], 4)} ${unit})` : ` (${ages.map((a) => sig(a, 4)).join(", ")} ${unit})`) : ""}`);
  }
  if (out.hours_basis) bits.push(out.hours_basis);
  return bits.join(" · ");
}
