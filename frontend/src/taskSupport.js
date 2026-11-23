// A supporting task: "keeps it on its life" (backend/maintenance/supporting.py). Greasing or an
// oil change doesn't renew the part; it keeps it on the life its model describes. The record:
// what it supports (failure modes the task serves, or its whole life), the reference interval
// the life model assumes, an optional impact if it isn't done ({form: "hazard_ratio", k}: the
// failure rate × k), grace (% of its interval overdue before the impact applies) and where the
// impact comes from. It's recorded only: the forecast is unchanged. Pure functions, tested alone.

export const SUPPORT_SOURCES = [
  ["assumed", "Assumed"],
  ["maker", "From the maker"],
  ["fitted", "Fitted"],
];
export const SOURCE_WORD = Object.fromEntries(SUPPORT_SOURCES);
export const COMBINE_HELP = "Several supporting tasks on one part multiply: × 2 and × 1.5, both not done, give × 3.";
export const SUPPORT_HELP = "It doesn't renew the part: it keeps it on the life its model describes, so the forecast is "
  + "unchanged while it's done. The impact says what not doing it would do.";
// The kinds that can be supporting: routine work (no kind) and replace at age.
export const canSupport = (outcome) => !outcome || outcome === "fixed_interval";

const text = (v) => (v == null ? "" : String(v));
const sig = (k) => Number(Number(k).toPrecision(3)).toLocaleString("en-AU");

// The form's fields from a task as read (its `support`, or none).
export function supportForm(task) {
  const s = task?.support || null;
  return {
    supporting: !!s,
    supports: new Set(s?.failure_mode_ids || []),
    reference: s ? text(s.reference?.value) : "",
    k: s?.impact?.k != null ? text(s.impact.k) : "",
    grace: s && s.grace ? text(s.grace) : "",
    supportSource: s?.source || "assumed",
    supportNote: s?.note || "",
  };
}

// What's wrong with the fields, in words (null: nothing).
export function supportProblem(f) {
  if (!f.supporting) return null;
  if (f.reference !== "" && !(Number(f.reference) > 0)) return "The reference interval is more than 0.";
  if (f.k !== "") {
    const k = Number(f.k);
    if (!Number.isFinite(k) || k < 1 || k > 100) return "The failure rate if it isn't done is × 1 (no change) to × 100.";
  }
  if (f.grace !== "") {
    const g = Number(f.grace);
    if (!Number.isFinite(g) || g < 0 || g > 100) return "The grace is 0% to 100% of its interval.";
  }
  return null;
}

// The record the fields say (null: not supporting). `modes`: the ids of the failure modes the
// task serves (a mode it no longer serves is dropped); `unit`: the task's unit.
export function supportOf(f, { modes = null, unit = null } = {}) {
  if (!f.supporting) return null;
  const ids = [...f.supports].filter((x) => !modes || modes.includes(x)).sort();
  const out = { failure_mode_ids: ids, impact: f.k === "" ? null : { form: "hazard_ratio", k: Number(f.k) },
    grace: f.grace === "" ? 0 : Number(f.grace), source: f.supportSource || "assumed", note: (f.supportNote || "").trim() };
  if (f.reference !== "") out.reference = { value: Number(f.reference), unit };
  return out;
}

const same = (a, b) => JSON.stringify(a ?? null) === JSON.stringify(b ?? null);
const stored = (s) => (s ? { failure_mode_ids: [...(s.failure_mode_ids || [])].sort(), impact: s.impact || null, grace: s.grace || 0,
  source: s.source || "assumed", note: s.note || "", reference: s.reference } : null);

// The PATCH body for what changed ({} when nothing did).
export function supportBody(task, f, opts = {}) {
  const want = supportOf(f, opts);
  const had = stored(task?.support);
  if (!want && !had) return {};
  if (!want) return { support: null };
  const full = { ...want, reference: want.reference || had?.reference };
  if (had && same(full, had)) return {};
  return { support: want };
}

// "Failure rate × 2 if not done", or "No modelled impact".
export function impactWords(impact) {
  return impact?.k != null ? `Failure rate × ${sig(impact.k)} if not done` : "No modelled impact";
}

// The record in words, as the server's supporting.words gives them ("Keeps it on its life:
// Bearing worn out · failure rate × 2 if not done"); `modeText`: {id: text}.
export function supportWords(s, modeText = {}) {
  if (!s) return "";
  const names = (s.failure_mode_ids || []).map((x) => modeText[x] || "a failure mode");
  const imp = impactWords(s.impact);
  return `Keeps it on its life: ${names.length ? names.join(", ") : "its whole life"} · ${imp[0].toLowerCase()}${imp.slice(1)}`;
}

// Whether this failure mode is one the task supports (a task supporting its whole life supports each).
export const supportsMode = (s, modeId) => !!s && (!(s.failure_mode_ids || []).length || s.failure_mode_ids.includes(modeId));

// The RCM's body for one failure mode: supported or not, keeping the rest of the record.
// Turning it on for a task that isn't supporting yet starts it on this mode alone.
export function modeSupportBody(task, modeId, on, { modes = [] } = {}) {
  const s = task?.support || null;
  if (on) {
    if (!s) return { support: { failure_mode_ids: [modeId] } };
    if (supportsMode(s, modeId)) return {};
    return { support: { ...stored(s), failure_mode_ids: [...s.failure_mode_ids, modeId].sort() } };
  }
  if (!supportsMode(s, modeId)) return {};
  // Its whole life → every mode it serves but this one; its last mode → not supporting.
  const rest = ((s.failure_mode_ids || []).length ? s.failure_mode_ids : modes).filter((x) => x !== modeId);
  if (!rest.length) return { support: null };
  return { support: { ...stored(s), failure_mode_ids: rest.sort() } };
}
