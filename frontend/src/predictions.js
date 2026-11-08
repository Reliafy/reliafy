// Reliability prediction (a parts count from handbook base rates): the
// addresses, the words the pages use, reading a pasted parts list, and the
// numbers as shown. Pure functions; the pages only display.
import { formatNumber, formatPercent } from "./format.js";
import { toCsv } from "./csv.js";

export const PREDICTIONS_PATH = "/predictions";
export const PREDICTIONS_GUIDE = "reliability-prediction";
export const PREDICTIONS_LABEL = "Reliability prediction";
export const PREDICTIONS_PURPOSE =
  "Estimate a design's failure rate from its parts list and handbook base rates, before there's any failure data.";

export const predictionPath = (id) => `${PREDICTIONS_PATH}/${encodeURIComponent(id)}`;

// The builder: blank, prefilled from a product (?product=) or from a saved
// prediction (?from=, to edit it or make a copy).
export function newPredictionPath({ product, from } = {}) {
  const q = new URLSearchParams();
  if (product) q.set("product", product);
  if (from) q.set("from", from);
  const s = q.toString();
  return `${PREDICTIONS_PATH}/new${s ? `?${s}` : ""}`;
}

// The defaults the page starts from (the server's; these match it).
export const DEFAULT_ENVIRONMENT = "GF";
export const DEFAULT_MISSION_HOURS = 1000;
export const DEFAULT_QUALITY_FACTOR = 1;

// A blank line as the builder keeps it (record: the chosen library record's
// brief, for the label; record_id is what's sent). A line with no handbook part
// type can carry a rate of the user's own (user_rate, per million hours: the
// handbook has no batteries) or be excluded (not an electronic part: left out).
export function blankLine(over = {}) {
  return {
    name: "", reference: "", quantity: 1, assembly: "", record_id: null, record: null, quality_factor: "",
    user_rate: "", excluded: false, ...over,
  };
}

// What the "no match" note of the part-type search says: the handbook's gaps and what to do instead.
export const NO_PART_TYPE_HINT = "MIL-HDBK-217F covers electronic parts only: it has no batteries and no mechanical "
  + "parts. Give a battery a rate of your own, and tick “Not electronic” for a mechanical part to leave it out.";

// The quality factor a part type takes when the line gives none, for the box's placeholder: its
// default grade (a parts-count type: commercial or non-MIL), else 1; "default" when the record
// came from a saved prediction without its grades (the server applies the same default).
export function defaultQuality(record) {
  if (record && !("quality_factor_default" in record)) return "default";
  return String(record?.quality_factor_default ?? DEFAULT_QUALITY_FACTOR);
}

// The quality grades of a part type, in words for a hint: "Class S 0.25; Class B 1; …".
export function qualityHint(record) {
  const levels = record?.quality_factors?.levels;
  if (levels?.length) {
    return `Quality factor πQ: ${levels.map((l) => `${l.name.split(":")[0]} ${l.value}`).join("; ")}.`
      + (record.quality_factor_default != null ? ` Left blank, ${record.quality_factor_default}.` : "");
  }
  if (record?.quality_factor_range) {
    return `Quality factor πQ, the handbook's range for this part: ${record.quality_factor_range[0]}–${record.quality_factor_range[1]}`;
  }
  return "Quality factor πQ: 1 unless you set it";
}

// A line from a product's parts list (the server gives assembly as a path).
export function lineFromServer(line) {
  return blankLine({
    name: line.name || "",
    reference: line.reference || "",
    quantity: line.quantity ?? 1,
    assembly: Array.isArray(line.assembly) ? line.assembly.join(" › ") : (line.assembly || ""),
    record_id: line.record_id || null,
    record: line.record_id ? { id: line.record_id, name: line.part_type || line.record_id } : null,
    quality_factor: line.quality_factor != null && line.quality_factor !== DEFAULT_QUALITY_FACTOR ? line.quality_factor : "",
    user_rate: line.rate_per_million_hours != null ? line.rate_per_million_hours : "",
    excluded: Boolean(line.excluded),
  });
}

// A saved prediction's lines, as the builder edits them (the results carry
// each record's name).
export function linesFromSaved(doc) {
  const names = new Map((doc?.results?.lines || []).map((l, i) => [i, l.part_type]));
  return (doc?.inputs?.lines || []).map((l, i) => lineFromServer({ ...l, part_type: names.get(i) }));
}

// The lines as the server takes them: the blank rows dropped, the quantity a
// number, the quality factor only when set (left blank, the part type's default
// grade), a rate of the user's own or "excluded" instead of a part type.
export function linesForServer(lines) {
  return lines
    .filter((l) => String(l.name || "").trim())
    .map((l) => {
      const out = { name: String(l.name).trim(), quantity: Number(l.quantity) || 1 };
      if (String(l.reference || "").trim()) out.reference = String(l.reference).trim();
      if (String(l.assembly || "").trim()) out.assembly = String(l.assembly).trim();
      if (l.excluded) {
        out.excluded = true;
        return out;
      }
      if (l.record_id) out.record_id = l.record_id;
      else if (String(l.user_rate ?? "").trim() !== "") {
        out.rate_per_million_hours = Number(l.user_rate);
        return out;
      }
      const q = String(l.quality_factor ?? "").trim();
      if (q !== "" && l.record_id) out.quality_factor = Number(q);
      return out;
    });
}

// Why the lines can't be calculated yet (null when they can).
export function linesProblem(lines) {
  const kept = lines.filter((l) => String(l.name || "").trim());
  if (!kept.length) return "Add at least one part.";
  const bad = kept.find((l) => !(Number(l.quantity) > 0));
  if (bad) return `${bad.name}: the quantity must be more than 0.`;
  const q = kept.find((l) => String(l.quality_factor ?? "").trim() !== "" && !(Number(l.quality_factor) > 0));
  if (q) return `${q.name}: the quality factor must be more than 0.`;
  const r = kept.find((l) => !l.excluded && !l.record_id && String(l.user_rate ?? "").trim() !== "" && !(Number(l.user_rate) > 0));
  if (r) return `${r.name}: a rate you give must be more than 0 per million hours.`;
  if (!kept.some((l) => !l.excluded && (l.record_id || String(l.user_rate ?? "").trim() !== ""))) {
    return "Give at least one part a handbook part type (or a rate of your own).";
  }
  return null;
}

// A pasted parts list, one part per line: "name", "name, qty",
// "name, qty, assembly" (comma, tab or semicolon separated), or "4 x name" /
// "name x4" / "name ×4". A header row (name / part … qty / quantity) is
// skipped. Lines with nothing in them are skipped.
const HEADER = /^(name|part|description|item)\b/i;
const LEADING_QTY = /^(\d+(?:\.\d+)?)\s*[x×]\s+(.+)$/i;
const TRAILING_QTY = /^(.+?)\s+[x×]\s*(\d+(?:\.\d+)?)$/i;

export function parsePartsList(text) {
  const out = [];
  const rows = String(text || "").split(/\r?\n/);
  rows.forEach((raw, i) => {
    const row = raw.trim();
    if (!row) return;
    const cells = row.split(/\t|;|,/).map((c) => c.trim());
    if (i === 0 && cells.length > 1 && HEADER.test(cells[0]) && /^(qty|quantity|n|count)\b/i.test(cells[1])) return;
    let name = cells[0];
    let quantity = 1;
    let assembly = "";
    if (cells.length > 1 && cells[1] !== "" && Number.isFinite(Number(cells[1]))) {
      quantity = Number(cells[1]);
      assembly = cells.slice(2).filter(Boolean).join(" › ");
    } else if (cells.length > 1) {
      assembly = cells.slice(1).filter(Boolean).join(" › ");
    }
    let m = LEADING_QTY.exec(name);
    if (m) {
      quantity = Number(m[1]);
      name = m[2].trim();
    } else if ((m = TRAILING_QTY.exec(name))) {
      quantity = Number(m[2]);
      name = m[1].trim();
    }
    if (!name) return;
    out.push(blankLine({ name, quantity: quantity > 0 ? quantity : 1, assembly }));
  });
  return out;
}

// ---- the numbers as shown ------------------------------------------------------

// Failures per million hours: "2.08", "0.0228", "112".
export const fmtPerMillion = (v) => formatNumber(v, { sig: 3 });
// Per hour: scientific, "2.28e-8".
export function fmtPerHour(v) {
  if (v == null || !Number.isFinite(Number(v))) return "—";
  const n = Number(v);
  if (n === 0) return "0";
  const [m, e] = n.toExponential(2).split("e");
  return `${m.replace(/\.?0+$/, "")}e${Number(e)}`;
}
// MTBF in hours to 3–4 significant figures: "481,000", "8,910", "43,900,000".
export function fmtHours(v) {
  if (v == null || !Number.isFinite(Number(v))) return "—";
  const n = Number(v);
  if (n >= 1e7) return new Intl.NumberFormat("en-US", { maximumSignificantDigits: 3 }).format(n);
  return formatNumber(n, { sig: n >= 1000 ? 3 : 4 });
}
// Reliability as a percentage with enough figures to tell 99.9 from 99.99.
export function fmtReliability(r) {
  if (r == null || !Number.isFinite(Number(r))) return "—";
  const p = Number(r) * 100;
  if (p >= 90) return `${p.toFixed(p >= 99.99 ? 3 : 2)}%`;
  return formatPercent(r);
}
export const fmtShare = (s) => (s == null ? "—" : formatPercent(s));

export function fmtQuantity(q) {
  const n = Number(q);
  if (!Number.isFinite(n)) return "—";
  return Number.isInteger(n) ? n.toLocaleString("en-US") : formatNumber(n, { sig: 4 });
}

// The one-line answer: "112 failures per million hours (1.12e-4 per hour) ·
// MTBF 8,910 h · 98.9% reliable over 100 h".
export function summaryText(results) {
  if (!results) return "";
  const rate = results.failure_rate_per_million_hours;
  if (!rate) return "No part type assigned yet, so no failure rate.";
  const t = results.mission_time_hours;
  return `${fmtPerMillion(rate)} failures per million hours (${fmtPerHour(results.failure_rate_per_hour)} per hour) · `
    + `MTBF ${fmtHours(results.mtbf_hours)} h · ${fmtReliability(results.reliability_at_mission)} reliable over ${fmtHours(t)} h`;
}

// "Applied: λb, πE, πQ. Not applied: πT (temperature), πS (electrical stress)."
export function factorsText(factors) {
  if (!factors) return "";
  const applied = (factors.applied || []).map((f) => f.symbol).join(", ");
  const left = (factors.not_applied || []).map((f) => `${f.symbol} (${f.name})`).join(", ");
  const held = (factors.held_at_defaults || []).map((f) => `${f.symbol} (${f.name})`).join(", ");
  return `Applied: ${applied}.${left ? ` Not applied: ${left}.` : " That's the whole handbook model for these parts."}`
    + (held ? ` Held at the handbook's defaults in the generic rates: ${held}.` : "");
}

// The Pareto bars: the top n lines, the rest as "Other" (a line is named with
// its assembly where two lines share a name).
export function paretoBars(byLine, n = 10) {
  const rows = byLine || [];
  const names = new Map();
  for (const r of rows) names.set(r.name, (names.get(r.name) || 0) + 1);
  const label = (r) => (names.get(r.name) > 1 && r.assembly ? `${r.name} · ${r.assembly}` : r.name);
  const top = rows.slice(0, n).map((r) => ({ label: label(r), rate: r.rate_per_million_hours, share: r.share }));
  const rest = rows.slice(n);
  if (rest.length) {
    const rate = rest.reduce((a, r) => a + (r.rate_per_million_hours || 0), 0);
    const share = rest.reduce((a, r) => a + (r.share || 0), 0);
    top.push({ label: `Other (${rest.length} lines)`, rate, share, other: true });
  }
  return top;
}

// The lines as a CSV (Download as CSV).
export function linesCsv(results) {
  const head = ["Part", "Reference", "Assembly", "Quantity", "Handbook part type", "Record", "λb or λg per 10^6 h",
    "πE", "πQ", "Rate per 10^6 h", "Rate per hour", "Share"];
  const rows = (results?.lines || []).map((l) => [
    l.name, l.reference || "", l.assembly_label || "", l.quantity,
    l.excluded ? "Not electronic: left out" : (l.part_type || ""), l.record_id || "",
    l.base_rate_per_million_hours ?? "", l.environment_factor ?? "", l.assigned ? l.quality_factor : "",
    l.rate_per_million_hours ?? "", l.rate_per_hour ?? "", l.share ?? "",
  ]);
  return toCsv([head, ...rows]);
}

export function csvFileName(name) {
  const slug = String(name || "prediction").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
  return `${slug || "prediction"}-parts-count.csv`;
}
