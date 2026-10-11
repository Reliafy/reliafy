// "What changed" (#41): the server computes every fact (GET /api/changes);
// this turns them into rows for the panel, the page and the assistant.
import { formatNumber, formatPercent } from "./format.js";

export const PERIODS = [
  { value: "30", label: "Last 30 days" },
  { value: "7", label: "Last 7 days" },
  { value: "last_visit", label: "Since last visit" },
];

// The request for a period choice: { days } or { since }.
export function periodQuery(value) {
  if (value === "last_visit") return { since: "last_visit" };
  const days = Number(value);
  return { days: Number.isFinite(days) && days > 0 ? days : 30 };
}

// The sentence with its counts marked for bold: [{ text, bold }]. The period
// before the colon ("In the last 30 days", "Since your last visit (3 Oct
// 2026)") stays plain.
export function sentenceParts(sentence) {
  const text = String(sentence || "");
  const cut = text.indexOf(": ");
  if (cut < 0) return text ? [{ text, bold: false }] : []; // "Nothing changed …"
  const lead = text.slice(0, cut + 2);
  const counts = text
    .slice(lead.length)
    .split(/(\d[\d,.]*)/)
    .filter((s) => s !== "")
    .map((t) => ({ text: t, bold: /^\d/.test(t) }));
  return [{ text: lead, bold: false }, ...counts];
}

function signedPercent(change) {
  if (change == null || !Number.isFinite(change)) return null;
  const s = formatPercent(Math.abs(change));
  return `${change < 0 ? "−" : "+"}${s}`;
}

function withUnit(v, unit) {
  const s = formatNumber(v);
  return unit && s !== "—" ? `${s} ${unit.toLowerCase()}` : s;
}

// "B10 1,200 → 900 hours (−25%)" for each measure a refit moved.
export function refitDetail(r) {
  if (!r.moved?.length) {
    return r.comparable ? "Refitted; B10 and MTTF held" : "Refitted; no B10 or MTTF to compare";
  }
  const text = r.moved
    .map((m) => {
      if (m.measure === "B10" || m.measure === "MTTF") {
        const pct = signedPercent(m.change);
        return `${m.measure} ${formatNumber(m.before)} → ${withUnit(m.after, r.unit)}${pct ? ` (${pct})` : ""}`;
      }
      return `${m.measure.toLowerCase()} ${m.before} → ${m.after}`;
    })
    .join("; ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function forecastDetail(f) {
  const label = f.after?.period_label || "periods";
  const pct = signedPercent(f.change);
  return `Expected failures ${formatNumber(f.before?.expected)} → ${formatNumber(f.after?.expected)} over ${f.after?.periods ?? ""} ${label}${pct ? ` (${pct})` : ""}`.replace(/\s+/g, " ");
}

const STATUS = {
  supported: "supported", contradicted: "contradicted", inconclusive: "inconclusive",
  unevidenced: "unevidenced", stale: "stale",
};

export function rcmDetail(e) {
  const now = STATUS[e.status] || e.status || "no status";
  const was = e.status_changed ? `${STATUS[e.status_before] || e.status_before} → ${now}` : now;
  return `“${e.mode}”: ${e.evidence || "its model"} was refitted; evidence ${was}`;
}

export function simulationDetail(s) {
  const runs = `${s.runs} run${s.runs === 1 ? "" : "s"}`;
  if (s.before?.availability == null || s.after?.availability == null) return `${runs}; nothing earlier to compare`;
  const pct = (a) => `${formatNumber(a * 100, { sig: 4 })}%`;
  const move = `availability ${pct(s.before.availability)} → ${pct(s.after.availability)}`;
  return `${runs}; ${move}${s.diagram_changed ? " (the diagram was edited too)" : ""}`;
}

// Every fact as one row, most important first:
// { key, kind, tone, name, url, detail, at }. tone, a chip's colour where it
// means something: "warning" (an alert fired), "danger" (evidence now
// contradicts the decision), else null.
export function changeRows(data) {
  if (!data) return [];
  const rows = [];
  for (const a of data.alerts || []) {
    rows.push({ key: `alert-${a.fleet_id}-${a.at}`, kind: "Fleet alert", tone: "warning", name: a.fleet,
      url: a.url, detail: a.text, at: a.at });
  }
  for (const r of (data.refits || []).filter((x) => x.moved?.length)) {
    rows.push({ key: `refit-${r.id}`, kind: "Refit moved", tone: null, name: r.name, url: r.url,
      detail: refitDetail(r), at: r.at });
  }
  for (const f of (data.forecasts || []).filter((x) => x.moved)) {
    rows.push({ key: `forecast-${f.id}`, kind: "Forecast moved", tone: null, name: f.name, url: f.url,
      detail: forecastDetail(f), at: null });
  }
  for (const e of data.rcm_evidence || []) {
    rows.push({ key: `rcm-${e.study_id}-${e.mode}-${e.evidence_url}`, kind: "RCM evidence",
      tone: e.status === "contradicted" ? "danger" : null, name: e.study, url: e.url,
      detail: rcmDetail(e), at: e.at });
  }
  for (const s of (data.simulations || []).filter((x) => x.moved)) {
    rows.push({ key: `sim-${s.id}`, kind: "Simulation moved", tone: null, name: s.name,
      url: s.before?.run_id ? `/rbds/runs/compare?ids=${s.before.run_id},${s.run_id}` : `/rbds/runs/${s.run_id}`,
      detail: simulationDetail(s), at: s.at });
  }
  for (const n of data.new || []) {
    rows.push({ key: `new-${n.collection}-${n.id}`, kind: `New ${n.type.toLowerCase()}`, tone: null,
      name: n.name, url: n.url, detail: null, at: n.at });
  }
  for (const c of data.changed || []) {
    rows.push({ key: `changed-${c.collection}-${c.id}`, kind: `${c.type} changed`, tone: null, name: c.name,
      url: c.url, detail: c.detail || (c.by ? `by ${c.by}` : null), at: c.at });
  }
  for (const r of (data.refits || []).filter((x) => !x.moved?.length)) {
    rows.push({ key: `refit-${r.id}`, kind: "Refitted", tone: null, name: r.name, url: r.url,
      detail: refitDetail(r), at: r.at });
  }
  for (const f of (data.forecasts || []).filter((x) => !x.moved)) {
    rows.push({ key: `forecast-${f.id}`, kind: "Forecast held", tone: null, name: f.name, url: f.url,
      detail: forecastDetail(f), at: null });
  }
  for (const s of (data.simulations || []).filter((x) => !x.moved)) {
    rows.push({ key: `sim-${s.id}`, kind: "Simulated", tone: null, name: s.name, url: s.url,
      detail: simulationDetail(s), at: s.at });
  }
  return rows;
}

// The tool result the in-app assistant words its answer from: the computed
// sentence, the counts, the rows (capped) and what couldn't be compared.
export function changesForAssistant(data, limit = 25) {
  const rows = changeRows(data);
  return {
    period: data.period?.label,
    since: data.since,
    sentence: data.sentence,
    counts: data.counts,
    changes: rows.slice(0, limit).map(({ kind, name, url, detail, at }) => ({
      kind, name, path: url, ...(detail ? { detail } : {}), ...(at ? { at } : {}),
    })),
    ...(rows.length > limit ? { more: rows.length - limit } : {}),
    thresholds: `A refit or forecast "moved" when it changed by more than ${formatPercent(data.thresholds?.relative ?? 0.1)}; a simulation when availability moved more than ${data.thresholds?.availability_points ?? 0.5} percentage points.`,
    not_compared: (data.not_compared || []).map((n) => `${n.what}: ${n.why}`),
    ...(data.period?.note ? { note: data.period.note } : {}),
  };
}
