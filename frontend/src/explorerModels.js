// The Explorer's Modelling tab (Derryn, 9 Nov 2026: "a Modelling tab on the product and
// Explorer page ... life models against every functional location"): a tree-table like
// the RCM and Measurements tabs. The tree, arranged by positions, is the first column;
// under each position hang the life models attached to it (a Weibull fitted to its own
// history, its class's model, any saved model assigned), before the positions inside it,
// with Kind, Source, the headline numbers, Mean life (or B10), Confidence and Used by
// beside them. A position rolls up its own rows ("3 models · 1 stale"), and a closed one
// what's inside it too. Pure functions, tested in explorerModels.test.js; the cells are
// drawn by ModelTable.jsx. The links come from GET /api/maintenance/position-models.

export const MODEL_TYPE = "pmodel";
export const isModelRow = (r) => r?.type === MODEL_TYPE;

// A model row's key in the tree (a link's id could be any row's key).
export const modelKey = (linkId) => `L:${linkId}`;

const noStatus = () => ({ overdue: 0, open_work: 0, alarms: 0, next_due: null, not_analysed: 0, positions: 0, empty: 0 });
const blank = () => ({ n: 0, stale: 0, missing: 0 });

// The table's columns beside the tree. `usual: false`: offered in Columns…, off at first.
export const MODEL_COLUMNS = [
  { id: "kind", label: "Kind", width: 150 },
  { id: "source", label: "Source", width: 230 },
  { id: "numbers", label: "Headline", width: 260, title: "The model's main numbers in its unit, with 95% bounds where it has them" },
  { id: "mean", label: "Mean life", width: 150, num: true, title: "The mean life, with its 90% lower bound" },
  { id: "b10", label: "B10 life", width: 150, num: true, usual: false, title: "The age by which 10% have failed, with its 90% lower bound" },
  { id: "quality", label: "Confidence", width: 150, title: "How much data is behind it, in a word" },
  { id: "used", label: "Used by", width: 150, title: "RCM decisions that link it as evidence, and RBD blocks on it" },
];
export const MODEL_USUAL = MODEL_COLUMNS.filter((c) => c.usual !== false).map((c) => c.id);
export const MODEL_TREE_HEAD = "Position, and the life models on it";

// A number to 3–4 significant figures, thousands separated; "—" for none.
export function fmt(v) {
  const x = Number(v);
  if (v == null || !Number.isFinite(x)) return "—";
  if (x !== 0 && (Math.abs(x) < 0.001 || Math.abs(x) >= 1e9)) return x.toPrecision(3);
  const sig = Math.abs(x) >= 1000 ? 4 : 3;
  return Number(x.toPrecision(sig)).toLocaleString("en-AU", { maximumFractionDigits: 6 });
}

// A model's time unit as people write it ("Hours" → "hours").
export const unitWord = (unit) => String(unit || "").trim().toLowerCase();

// A level as a percentage: 0.9 → "90%".
const pct = (level) => `${Math.round(Number(level || 0.9) * 100)}%`;

// What a model's intervals are, for a column or a legend: a Bayesian update's are
// credible intervals at its level ("90% credible interval"), never "bounds" or
// "confidence"; a fitted model's are its 95% bounds.
export const boundsLabel = (model) => (model?.credible ? `${pct(model.credible_level)} credible interval` : "95% bounds");

// One number with its bounds and unit: "1,435 hours (1,234–1,669)"; a one-sided lower
// bound: "1,239 hours (≥ 1,109)"; a credible interval (a Bayesian update, `level` its
// level): "4.15 years, 90% credible 3.23–5.35".
export function withBounds(n, level = 0.9) {
  if (!n) return "—";
  if (n.text) return n.text;
  const u = n.unit ? ` ${unitWord(n.unit)}` : "";
  const lo = n.lower != null ? fmt(n.lower) : null;
  const hi = n.upper != null ? fmt(n.upper) : null;
  if (n.bound === "credible") return `${fmt(n.value)}${u}${lo && hi ? `, ${pct(level)} credible ${lo}–${hi}` : ""}`;
  const b = lo && hi ? ` (${lo}–${hi})` : lo && n.bound === "lower" ? ` (≥ ${lo})` : "";
  return `${fmt(n.value)}${u}${b}`;
}

const byId = (model, id) => (model?.numbers || []).find((n) => n.id === id) || null;

// The Headline cell: characteristic life and shape for a Weibull, MTBF for an
// exponential, the failure rate and trend for a repairable model, where a degradation
// model fails; a model with none of these, its mean life.
export function headline(model) {
  if (!model) return "";
  const parts = [];
  const lv = model.credible_level;
  const life = byId(model, "char_life");
  const shape = byId(model, "shape");
  if (life) parts.push(`Life ${withBounds(life, lv)}`);
  if (shape) parts.push(`shape ${withBounds(shape, lv)}`);
  const mtbf = byId(model, "mtbf");
  const rate = byId(model, "rate");
  if (rate) parts.push(`Rate ${withBounds(rate)}`);
  else if (mtbf) parts.push(`MTBF ${withBounds(mtbf)}`);
  if (model.trend) parts.push(model.trend);
  for (const id of ["threshold", "marker", "reference"]) {
    const n = byId(model, id);
    if (n) parts.push(`${n.label} ${n.text}`);
  }
  if (!parts.length && byId(model, "mean")) parts.push(`Mean life ${withBounds(byId(model, "mean"), lv)}`);
  return parts.join(" · ");
}

// The Mean life / B10 cells.
export const meanText = (model) => (byId(model, "mean") ? withBounds(byId(model, "mean"), model.credible_level) : "—");
export const b10Text = (model) => (byId(model, "b10") ? withBounds(byId(model, "b10"), model.credible_level) : "—");

// The data behind it in a few words: "30 failures, 0 suspensions", "6 units measured".
export function countsText(model) {
  const c = model?.counts || {};
  const n = (v, one, many = `${one}s`) => `${Number(v).toLocaleString("en-AU")} ${Number(v) === 1 ? one : many}`;
  if (c.units != null) return n(c.units, "unit measured", "units measured");
  const out = [];
  if (c.failures != null) out.push(n(c.failures, "failure"));
  if (c.suspensions != null) out.push(n(c.suspensions, "suspension"));
  if (c.systems != null) out.push(n(c.systems, "system"));
  return out.join(", ");
}

// The Used by cell: "2 decisions · 1 RBD", "" for none.
export function usedText(link) {
  const d = link?.used_by?.decisions?.length || 0;
  const r = link?.used_by?.rbds?.length || 0;
  const out = [];
  if (d) out.push(`${d} decision${d === 1 ? "" : "s"}`);
  if (r) out.push(`${r} RBD${r === 1 ? "" : "s"}`);
  return out.join(" · ");
}

// What a link is for: its failure modes, or every failure of the position.
export const forText = (link) => (link?.failure_modes?.length
  ? link.failure_modes.map((f) => f.text).join(", ") : "All failures of this position");

// The tree with each position's model rows in it. The display given is left as it
// is; position rows gain `lsum` (their own rows' counts), `lall` (theirs and every
// position's inside them) and `modelKids`.
export function graftModels(display, links = []) {
  const rows = new Map();
  for (const [k, r] of display.rows) rows.set(k, { ...r, kids: [...r.kids] });
  const out = { ...display, rows, models: true };
  for (const r of rows.values()) {
    if (r.type === "pos") Object.assign(r, { lsum: blank(), lall: blank(), modelKids: 0 });
  }
  const byPos = new Map();
  for (const link of links) {
    const p = rows.get(link.position_id);
    if (!p || p.type !== "pos") continue;
    if (!byPos.has(p.key)) byPos.set(p.key, []);
    byPos.get(p.key).push(link);
  }
  for (const [pk, list] of byPos) {
    const p = rows.get(pk);
    const keys = [];
    for (const link of list) {
      const key = modelKey(link.id);
      const name = link.model?.name || link.name || "(a model that's gone)";
      rows.set(key, {
        key, type: MODEL_TYPE, parent: pk, kids: [], depth: p.depth + 1, own: noStatus(), sum: noStatus(),
        ref: {
          name, link, position_id: pk, family: link.model?.family || "life",
          search: [name, link.model?.kind, link.source_text, forText(link)].filter(Boolean).join(" ").toLowerCase(),
        },
      });
      keys.push(key);
      p.lsum.n += 1;
      if (link.stale) p.lsum.stale += 1;
      if (!link.model) p.lsum.missing += 1;
    }
    p.kids = [...keys, ...p.kids];
    p.modelKids = keys.length;
  }
  const total = (k) => {
    const r = rows.get(k);
    if (r.lallDone) return r.lall;
    const t = { ...r.lsum };
    for (const c of r.kids) {
      if (rows.get(c)?.type === "pos") {
        const s = total(c);
        t.n += s.n;
        t.stale += s.stale;
        t.missing += s.missing;
      }
    }
    r.lall = t;
    r.lallDone = true;
    return t;
  };
  for (const r of rows.values()) if (r.type === "pos") total(r.key);
  for (const r of rows.values()) delete r.lallDone;
  return out;
}

// A position row's roll-up: its own rows when open, everything inside it when closed
// ("3 models · 1 stale"); "" with none.
export function rollupText(r, open = false) {
  const s = open ? r.lsum : r.lall;
  if (!s?.n) return "";
  const parts = [`${s.n.toLocaleString("en-AU")} model${s.n === 1 ? "" : "s"}`];
  if (s.stale) parts.push(`${s.stale.toLocaleString("en-AU")} stale`);
  if (s.missing) parts.push(`${s.missing.toLocaleString("en-AU")} missing`);
  return parts.join(" · ");
}

// A row's ⋯: Open, Open in Models, Refit… (a fitted one), Replace with…, Unlink….
export function rowActions(r, { viewOnly = null } = {}) {
  const link = r.ref.link;
  const off = viewOnly ? { disabled: true, title: viewOnly } : {};
  return [
    { id: "model-open", label: "Open" },
    link.model?.path ? { id: "model-page", label: "Open in Models" } : null,
    link.role === "fitted" ? { id: "model-refit", label: "Refit…", ...off } : null,
    link.role === "prediction" ? { id: "model-predict", label: "Refresh the prediction…", ...off } : null,
    // A Bayesian update takes the position's new failures; a plain Weibull, exponential or
    // lognormal model can be the baseline of one (bayesUpdate.js).
    link.role === "bayesian" ? { id: "model-bayes", label: "Update with new failures…", ...off }
      : link.model && /^(Weibull|Exponential|Lognormal)$/.test(link.model.kind || "") ? { id: "model-bayes", label: "Update with this position's history…", ...off } : null,
    { id: "model-replace", label: "Replace with…", ...off },
    { id: "model-unlink", label: "Unlink…", ...off },
  ].filter(Boolean);
}

// The tab's chip: models behind their history or gone.
export const MODEL_CHIPS = [
  { id: "stale", label: "Stale", rcmOnly: true, tab: "models",
    title: "Fitted models with failures recorded since, and models that are gone", test: (r) => isModelRow(r) && (!!r.ref.link.stale || !r.ref.link.model) },
];

// The positions to open when the tab opens: the way down to the one picked.
export function openForModels(display, positionKey) {
  const out = [];
  for (let k = positionKey; k != null; k = display.rows.get(k)?.parent) out.push(k);
  return out;
}

// The models on a position, as the RCM's evidence picker offers them first: those
// named for the failure mode at the top, then those for every failure there; each
// with the evidence type a decision links ({type, id}) and why it's offered.
// `links`: GET /api/maintenance/position-models's for the position.
const EVIDENCE = { model: "model", degradation_model: "degradation_model" };
export function attachedFor(links = [], { modeId = null, expectedType = null } = {}) {
  const out = [];
  for (const l of links) {
    const type = EVIDENCE[l.model_type];
    if (!type || (expectedType && type !== expectedType)) continue;
    const forMode = !!modeId && (l.failure_modes || []).some((f) => f.id === modeId);
    const forAll = !(l.failure_modes || []).length;
    if (!forMode && !forAll) continue;
    out.push({ type, id: l.model_id, label: l.model?.name || l.name, rank: forMode ? 0 : 1,
      meta: forMode ? "On this position, for this failure mode" : "On this position" });
  }
  out.sort((a, b) => a.rank - b.rank);
  const seen = new Set();
  return out.filter((o) => (seen.has(o.id) ? false : seen.add(o.id)));
}

// "Add a prediction…" (a parts count from the position's parts list): the part types chosen
// in the dialog as the server takes them, {part number (or part id): {record_id, quality_factor}};
// lines with no part type are left out (and out of the total, as the parts count says).
export function predictionAssign(lines = []) {
  const out = {};
  for (const l of lines) {
    const key = l.reference || l.part_id;
    const record = l.record?.id || l.record_id;
    if (!key || !record) continue;
    const q = Number(l.quality_factor);
    out[key] = { record_id: record, ...(Number.isFinite(q) && q > 0 && q !== 1 ? { quality_factor: q } : {}) };
  }
  return out;
}

// A prediction row's numbers in words: "12.3 failures per million hours · MTBF 81,300 hours".
export function predictionWords(source = {}) {
  const rate = source.rate_per_million_hours;
  if (!rate) return "No part types chosen yet";
  return `${fmt(rate)} failures per million hours · MTBF ${fmt(source.mtbf_hours)} hours`;
}
